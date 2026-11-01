#!/usr/bin/env python3
"""D12: the well-image archive. Every scanned document in the Railroad Commission's three image packs, tied to the well it is about.

The RRC publishes three zips a business day (NOTES_D7: W-1 images, directional surveys, completion images). The Daily report only counts
them and shows blurred sheets. This producer opens them, finds out which WELL each document belongs to, and publishes each document
readable and unmodified, with a readable picture of its first page, as files of GitHub releases. A well is its 8-digit API number
(the county code and the well's own number); the page is `#images`.

How a document finds its well (checked against the real packs of 2026-10-29: 73 of 74 W-1 permits, 58 of 58 surveys, 123 of 123 completion
packets tie; what does not is counted, never guessed):

  W-1 images           `<permit>_W1_*.pdf`, `<permit>_Plat_*.pdf`    the permit number -> the API number in the Drilling Permit Daily File
  directional surveys  `dir_survey_<id>.pdf`                         the pack's CSV: attachment id -> API_NO
  completion images    `<district>/trackingNo_<n>/<file>`            the completion data zip of the same day: packetData_<n>_*.dat -> API number

What is published, and where:

  data/wells/index.json          the packs done so far (day, pack, release tags, counts), the counties and the totals
  data/wells/county/<fips>.json  each well of the county: API, field, district, operator (a corporation, LLC or partnership only, as everywhere
                                 on the site) and its documents: stage, kind, pages, bytes, the file name and the release it is in
  GitHub releases                `wells-<day>-<pack>-<nn>`, at most 800 files each (a release holds 1000): `<api>_<p|d|c><n>.pdf|tif|png` is the
                                 document as the RRC made it, `<api>_<p|d|c><n>.jpg` page one as a picture 1000 px wide

What is NOT published: lease names, well numbers and landowner names (the packets carry them; the documents themselves do) and any file
name from a pack (names are made up here, because the RRC's carry lease and well names). Decided 2026-10-31 and 2026-11-01 by the owner
(README, Privacy): the documents are public records and are published readable; nothing is redacted; they can carry the names, phone numbers and
addresses of individuals. To remove one: delete its release file, then its entry in the county file.

A run does the newest `--days` (default 2) filing days that have a pack not done yet, newest first, so a pack that landed late or a night that
failed is picked up the next day; `--days` and `--window` reach further back by hand. Everything downloaded is untrusted data: members
are copied one at a time, size-limited and checked for the PDF or TIFF signature (a scan saved as .tif that is really a PNG is kept as a .png), never run; pdftoppm runs under a timeout and, where `prlimit`
exists, a memory limit, without the repository token. Standard library only, plus Pillow and pdftoppm (poppler-utils) for the previews.

  python3 -I site/pipeline/d12_wells.py                      the newest 2 days not done yet (needs GH_TOKEN, gh, Pillow, pdftoppm)
  python3 -I site/pipeline/d12_wells.py --days 5 --window 30  catch up
  python3 -I site/pipeline/d12_wells.py --check              validate the committed files
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
import zipfile
import zlib
import zoneinfo
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import rrc_share  # noqa: E402
from rrc_share import Session, Share, ShareError, TooSlow  # noqa: E402
import d7_packs  # noqa: E402
import d7_release  # noqa: E402
import privacy_check  # noqa: E402
import d7_daily  # noqa: E402  (its permit file reader and the share ids)

DEFAULT_OUT = os.path.join(SITE, "public", "data", "wells")
DATA = os.path.join(SITE, "public", "data")
KEEP_DAYS = 92  # the same archive window as the Daily report; the releases of older days are deleted with their entries
WINDOW_DAYS = 14  # how far back a run looks for a pack that is not done
SETTLE_MINUTES = 90  # a pack listed less than this long ago may still be being written
MAX_ASSETS = 800  # files per release (GitHub allows 1000)
PREVIEW_W = 1000  # px wide: a letter page at about 120 dots an inch, which reads
PREVIEW_MAX = 330_000  # bytes; a preview over this is drawn again at lower quality
PREVIEW_QUALITY = (60, 46, 34)
PER_DOC_SECONDS = 25
WORKERS = 4
MIN_PACK_BYTES = 2048  # the RRC lists an empty day as a 0.26 KB zip
RULES = 2  # what a run refuses, as a number: 2 since a scan saved as .tif that is a PNG is kept (as a .png) instead of refused. A pack recorded with refusals under older rules is done once more
PNG = b"\x89PNG"
# what a member's own first bytes may be, by the extension it is named with: the drill pages' table (PDF, TIFF), and a PNG under a .tif name (the RRC's completion packs hold a few)
ALLOWED = dict(d7_packs.MAGIC, **{".tif": d7_packs.MAGIC[".tif"] + (PNG,), ".tiff": d7_packs.MAGIC[".tiff"] + (PNG,)})
# GitHub's quota for the repository's token is shared with everything else in the run, the site's own deploy included: after about 4,500 uploads in 35 minutes (two runs, 2026-11-01) the next
# Pages deployment was refused ("API rate limit exceeded for installation") and the site stayed on the older build. A run stops starting packs once it has uploaded this many files
# (the files of a pack, picture and document, are 2 a document); what is left is done by the next run. One ordinary day is about 2,300 files.
MAX_FILES_PER_RUN = 3400
EST_FILES = {"w1": 400, "ds": 250, "ci": 2400}  # what a pack of that kind is expected to upload: judged before it is downloaded, from the real days of 2026-10-29 and 30 (336, 114, 1,816 and 322, 206, 2,114)

PACKS = {  # code: (stage letter, the Daily report's dataset id, label)
    "w1": ("p", "w1images", "W-1 permit letters and plats"),
    "ds": ("d", "dirsurveys", "directional surveys"),
    "ci": ("c", "complimages", "completion images"),
}
STAGE_PACK = {v[0]: k for k, v in PACKS.items()}
ORDER = ["w1", "ds", "ci"]  # the order a day's packs are done in: the small ones first, so a quota that runs short defers the big completion pack and not the others
W1_MAIN = re.compile(r"subscriptions_(\d{4})-(\d\d)-(\d\d)\.zip")
MDY_ZIP = re.compile(r"(\d\d)-(\d\d)-(\d{4})\.zip")
CI_PATH = re.compile(r"[0-9A-Za-z]+/trackingNo_(\d+)(?:_Images_\w+)?/")
PACKET_PATH = re.compile(r"([0-9A-Za-z]+)/trackingNo_(\d+)/packetData_\d+_(Approved|Submitted)\.dat")
API8 = re.compile(r"\d{8}")
FIELD_OK = re.compile(r"[A-Za-z0-9 ()&'./,#-]{1,60}")
TAG = re.compile(r"wells-(\d{4}-\d\d-\d\d)-(w1|ds|ci)-(\d\d)")
STEM = re.compile(r"(\d{8})_([pdc])(\d{1,4})")


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------------------------------------ what to do (pure)

def named_day(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def units_listed(rows):
    """{(day, pack): {name, bytes, modified}} from the four shares' listings: rows = {'w1': [...], 'ds': [...], 'ci': [...], 'cd': [...]}
    ('cd' is the completion data zip, which the completion images need to find their wells). A stray name or an impossible date is skipped."""
    out = {}
    for pack, listing in rows.items():
        for r in listing:
            if pack == "w1":
                m = W1_MAIN.fullmatch(r["name"])
                day = named_day(m.group(1), m.group(2), m.group(3)) if m else None
            else:
                m = MDY_ZIP.fullmatch(r["name"])
                day = named_day(m.group(3), m.group(1), m.group(2)) if m else None
            if day is not None:
                out[(day, pack)] = {"name": r["name"], "bytes": r.get("bytes") or 0, "modified": r.get("modified")}
    return out


def plan(listed, done, now, days=2, window=WINDOW_DAYS, only=None, settle=SETTLE_MINUTES):
    """The packs to do, newest filing day first, at most `days` distinct days that have one not done. `done` is {(day, pack): (name, bytes)} of
    the packs already published; `now` is a naive Central datetime (the shares list Central times). Returns (units, notes): units are
    [{day, pack, name, bytes, modified, cd}] and `cd` is the completion data zip a completion pack needs. A pack is left out when it is
    empty, was listed less than `settle` minutes ago, is already done under the same name and size, or (completions) has no data zip."""
    notes, todo = [], []
    today = now.date()
    for (day, pack), r in sorted(listed.items(), key=lambda kv: (-kv[0][0].toordinal(), ORDER.index(kv[0][1]) if kv[0][1] in ORDER else 9)):
        if pack == "cd" or (today - day).days > window or day > today or (only and day != only):
            continue
        if r["bytes"] < MIN_PACK_BYTES:
            continue
        if done.get((day, pack)) == (r["name"], r["bytes"]):
            continue
        if r.get("modified"):
            try:
                age = (now - datetime.fromisoformat(r["modified"])).total_seconds() / 60
            except ValueError:
                age = settle
            if age < settle:
                notes.append("%s %s: listed %d minutes ago, left for the next run" % (day, pack, age))
                continue
        cd = listed.get((day, "cd"))
        if pack == "ci" and (not cd or cd["bytes"] < MIN_PACK_BYTES):
            notes.append("%s ci: no completion data zip for the day, so the images cannot be tied to wells" % day)
            continue
        todo.append({"day": day, "pack": pack, "name": r["name"], "bytes": r["bytes"], "modified": r.get("modified"), "cd": cd["name"] if cd else None})
    keep, seen = [], []
    for u in todo:
        if u["day"] not in seen:
            if len(seen) >= days:
                continue
            seen.append(u["day"])
        keep.append(u)
    return keep, notes


# ------------------------------------------------------------------------------------------------ which well (pure)

def norm(path):
    return path.replace("\\", "/")


def clean_field(text):
    t = " ".join((text or "").split())
    return t if FIELD_OK.fullmatch(t) and not privacy_check.scan(t) else None


def permit_ties(perms):
    """{7-digit permit: {api, district, op}} from the Daily File's permits (d7_daily.read_daf)."""
    return {n: {"api": p["api"], "district": p["district"], "op": p["op"], "field": None} for n, p in perms.items() if p.get("api") and API8.fullmatch(p["api"])}


def survey_ties(zf):
    """{attachment id: {api, ...}} from the survey pack's CSV."""
    import csv
    import io
    out = {}
    for info in zf.infolist():
        if info.filename.lower().endswith(".csv") and not info.is_dir() and info.file_size <= 5_000_000:
            for r in csv.DictReader(io.StringIO(zf.read(info).decode("latin-1"))):
                api = (r.get("API_NO") or "").strip()
                if API8.fullmatch(api):
                    out[(r.get("EXTERNAL_ATTACHMENT_ID") or "").strip()] = {"api": api, "district": None, "op": None, "field": None}
            break
    return out


def packet_ties(path):
    """{tracking number: {api, district, op, field}} from the completion data zip (packetData_<n>_Approved|Submitted.dat: the PACKET line
    holds the tracking number, operator number, API number, district, county and field name; the landowner and lease names are never read)."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            m = PACKET_PATH.fullmatch(norm(info.filename))
            if not m or info.is_dir() or info.file_size > 5_000_000:
                continue
            pk = next((l.split("{") for l in z.read(info).decode("latin-1").replace("\r", "").split("\n") if l.startswith("PACKET{")), None)
            if not pk or len(pk) < 41 or not API8.fullmatch(pk[6].strip()):
                continue
            if m.group(2) in out and m.group(3) == "Submitted":
                continue  # the approved packet is the better record of the well
            out[m.group(2)] = {"api": pk[6].strip(), "district": m.group(1), "op": pk[5].strip(), "field": clean_field(pk[29])}
    return out


def sniff(zf, info):
    """The first four bytes of a member (b"" when it cannot be read: staging refuses it)."""
    try:
        with zf.open(info) as f:
            return f.read(4)
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error):
        return b""


def candidates(zf, pack, ties):
    """(docs, untied, rejected) for one pack: docs are the documents that tie to a well, each {info, api, district, op, field, kind, ext, stage};
    untied counts the documents no well could be found for."""
    docs, untied = [], 0
    kind_of = d7_packs.KINDS[PACKS[pack][1]]
    for info, base in d7_packs.documents(zf):
        key = None
        if pack == "w1":
            m = d7_packs.W1_NAME.match(base)
            key = "%07d" % int(m.group(1)) if m else None
        elif pack == "ds":
            m = d7_packs.SURVEY_NAME.fullmatch(base)
            key = m.group(1) if m else None
        else:
            m = CI_PATH.match(norm(info.filename))
            key = m.group(1) if m else None
        tie = ties.get(key) if key else None
        if not tie:
            untied += 1
            continue
        ext = os.path.splitext(base)[1].lower().lstrip(".")
        if ext in ("tif", "tiff") and sniff(zf, info) == PNG:
            ext = "png"  # a PNG saved as .tif: kept under the name its content has, so a viewer opens it as what it is
        docs.append({"info": info, "api": tie["api"], "district": tie.get("district"), "op": tie.get("op"), "field": tie.get("field"),
                     "kind": kind_of(base), "ext": "tif" if ext == "tiff" else ext, "stage": PACKS[pack][0], "key": norm(info.filename)})
    # numbering must not depend on the zip's order: by well, then kind, then the member's own path
    docs.sort(key=lambda d: (d["api"], d["kind"], d["key"]))
    seq = collections.Counter()
    for d in docs:
        seq[d["api"]] += 1
        d["f"] = "%s_%s%d" % (d["api"], d["stage"], seq[d["api"]])
    return docs, untied


def chunks(docs, cap=MAX_ASSETS):
    """The docs in groups whose files (the document and its preview) fit a release, a well's documents kept together where they can be."""
    out, cur, n = [], [], 0
    for d in docs:
        need = 2 if d.get("pv") else 1
        if cur and n + need > cap:
            out.append(cur)
            cur, n = [], 0
        cur.append(d)
        n += need
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------------------------------------------ staging and previews

def have_tools():
    """None when the previews can be drawn, else why not."""
    if shutil.which("pdftoppm") is None or shutil.which("pdfinfo") is None:
        return "poppler-utils (pdftoppm, pdfinfo) is not installed"
    try:
        import PIL  # noqa: F401
    except ImportError:
        return "Pillow is not installed"
    return None


def scrubbed_env():
    return d7_packs.scrubbed_env()


def _limit(cmd):
    """Put a memory and CPU limit on a child that parses a file a server sent, where prlimit exists."""
    pr = shutil.which("prlimit")
    return [pr, "--as=3221225472", "--cpu=40", "--"] + cmd if pr else cmd


def pdf_pages(path):
    try:
        out = subprocess.run(_limit(["pdfinfo", path]), capture_output=True, text=True, timeout=20, env=scrubbed_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def render_pdf(src, dest):
    """Page one of a PDF as a JPEG PREVIEW_W px wide at the first quality that fits PREVIEW_MAX. True when written."""
    prefix = dest[:-4] + ".pv"
    for q in PREVIEW_QUALITY:
        try:
            subprocess.run(_limit(["pdftoppm", "-f", "1", "-l", "1", "-scale-to-x", str(PREVIEW_W), "-scale-to-y", "-1", "-jpeg", "-jpegopt", "quality=%d" % q,
                                   "-singlefile", src, prefix]), check=True, timeout=PER_DOC_SECONDS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=scrubbed_env())
        except (OSError, subprocess.SubprocessError):
            return False
        out = prefix + ".jpg"
        if os.path.exists(out) and os.path.getsize(out) <= PREVIEW_MAX or q == PREVIEW_QUALITY[-1]:
            break
    out = prefix + ".jpg"
    if not os.path.exists(out) or os.path.getsize(out) < 200:
        return False
    os.replace(out, dest)
    return True


def render_tif(src, dest):
    """(written, pages) for a TIFF, or any scan Pillow reads by its content (a PNG saved as .tif): page one as a JPEG, no EXIF."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 120_000_000  # a TIFF that unpacks past this is refused rather than drawn
    try:
        with warnings.catch_warnings(), Image.open(src) as im:
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # between 1x and 2x the limit Pillow only warns; past 2x it raises and the file is skipped
            pages = getattr(im, "n_frames", 1)
            im.seek(0)
            im = im.convert("L") if im.mode in ("1", "L", "P", "LA") else im.convert("RGB")
            if im.width > PREVIEW_W:
                im = im.resize((PREVIEW_W, max(1, round(im.height * PREVIEW_W / im.width))), Image.LANCZOS)
            for q in PREVIEW_QUALITY:
                im.save(dest, "JPEG", quality=q, optimize=True)
                if os.path.getsize(dest) <= PREVIEW_MAX:
                    break
        return True, pages
    except Exception:  # noqa: BLE001 - one bad scan must not stop the pack (a bomb, a truncated file)
        if os.path.exists(dest):
            os.remove(dest)
        return False, None


def preview_one(d, stage_dir):
    src = os.path.join(stage_dir, "%s.%s" % (d["f"], d["ext"]))
    dest = os.path.join(stage_dir, d["f"] + ".jpg")
    if d["ext"] == "pdf":
        d["pg"] = pdf_pages(src)
        d["pv"] = 1 if render_pdf(src, dest) else 0
    else:
        ok, pages = render_tif(src, dest)
        d["pg"], d["pv"] = pages, 1 if ok else 0
    return d


def stage(zf, docs, stage_dir, log=log):
    """Copy each document to stage_dir under its made-up name, then draw page one of each (four at a time). Returns (kept, rejected): the docs
    that were copied, with 'b' (bytes), 'pg' (pages or None) and 'pv' (1 when a preview was drawn)."""
    os.makedirs(stage_dir, exist_ok=True)
    kept, rejected = [], 0
    for d in docs:
        size = d7_packs.copy_member(zf, d["info"], os.path.join(stage_dir, "%s.%s" % (d["f"], d["ext"])), ALLOWED)
        if size is None:
            rejected += 1
            continue
        d["b"] = size
        kept.append(d)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(lambda d: preview_one(d, stage_dir), kept))
    for d in kept:
        d.pop("info", None)
    log("staged %d documents (%d without a preview, %d refused)" % (len(kept), sum(1 for d in kept if not d["pv"]), rejected))
    return kept, rejected


# ------------------------------------------------------------------------------------------------ releases

RATE_LIMITED = re.compile(r"rate limit|scraping|abuse|wait a few minutes|retry-after|HTTP 429", re.I)


def gh(args, timeout=900):
    """A gh call, retried patiently and with one attempt at a time (no inner retries: asking again during a limit only extends it). A failure that reads as GitHub's secondary rate
    limit (it began on the second run of 2026-11-01, after about 4,500 uploads in 35 minutes: "... scraping GitHub ...") waits minutes, not seconds; any other failure waits seconds."""
    last = None
    for i in range(8):
        try:
            return d7_release._gh(args, timeout=timeout, retry=False)
        except d7_release.ReleaseError as e:
            last = e
            if d7_release.DEADLINE is not None and d7_release.DEADLINE - time.time() < 60:
                break
            limited = bool(RATE_LIMITED.search(str(e)))
            wait = min(180, 75 * (i + 1)) if limited else min(60, 10 * (i + 1))
            if d7_release.DEADLINE is not None:
                wait = min(wait, max(1, d7_release.DEADLINE - time.time() - 30))
            time.sleep(wait)
    raise last


def quota_line():
    """GitHub's REST quota for this token as one log line (asking for it is free), or None when gh cannot say: what the two runs of 2026-11-01 ran into was never visible in a log."""
    try:
        res = json.loads(d7_release._gh(["api", "rate_limit"], timeout=60, retry=False)).get("resources", {})
        parts = []
        for k in ("core", "integration_manifest", "code_scanning_upload"):
            if k in res and res[k].get("limit"):
                parts.append("%s %d of %d left, resets %s UTC" % (k, res[k]["remaining"], res[k]["limit"], datetime.fromtimestamp(res[k]["reset"], timezone.utc).strftime("%H:%M")))
        return "GitHub quota: " + "; ".join(parts) if parts else None
    except Exception:  # noqa: BLE001 - a log line is never worth a failure
        return None


CALLS_PER_FILE = 2  # measured on 2026-11-01: 339 files cost 687 of the REST quota (4,995 left before, 4,308 after)
RESERVE = 500  # calls left for the rest of the run, the site's own deploy included


class QuotaLow(RuntimeError):
    """The REST quota will not last for what is left to send and it does not reset in time: the pack is left for the next run (nothing is recorded for it)."""


def quota():
    """(calls left, reset time) of GitHub's REST quota for this token, or None when gh cannot say."""
    try:
        core = json.loads(d7_release._gh(["api", "rate_limit"], timeout=60, retry=False))["resources"]["core"]
        return int(core["remaining"]), float(core["reset"])
    except Exception:  # noqa: BLE001 - not knowing is not a reason to stop
        return None


def wait_for_quota(need, log=log):
    """Returns once `need` calls are left. When fewer are, waits for the hourly reset if that fits the run's time; otherwise raises QuotaLow. Uploads cost about two calls a file and a day is
    about 2,300 files, so one day alone can use the whole hour's 5,000 (the site's deploy was refused on 2026-11-01 for want of what the uploads had used)."""
    for _ in range(2):
        q = quota()
        if q is None or q[0] >= need:
            return
        wait = max(5.0, q[1] - time.time() + 15)
        room = (d7_release.DEADLINE - time.time() - 150) if d7_release.DEADLINE is not None else 3600
        if wait > room:
            raise QuotaLow("%d of GitHub's calls are left and about %d are needed; they reset in %d minutes, past this run's time" % (q[0], need, wait // 60))
        log("GitHub's quota has %d calls left and about %d are needed: waiting %d minutes for its reset" % (q[0], need, wait // 60 + 1))
        time.sleep(wait)
    raise QuotaLow("GitHub's quota is still short after its reset")


def tag_name(day, pack, n):
    return "wells-%s-%s-%02d" % (day.isoformat(), pack, n)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def assets_state(repo, tag):
    """{name: asset} of a release: size, state and, where the gh CLI gives it, the SHA-256 digest."""
    return {a["name"]: a for a in json.loads(gh(["release", "view", tag, "--repo", repo, "--json", "assets"], timeout=300)).get("assets", [])}


def same_file(asset, path):
    """True when the release already holds this file: uploaded completely, the same size and, where GitHub gives a digest, the same SHA-256."""
    if asset.get("state") not in (None, "uploaded") or asset.get("size") != os.path.getsize(path):
        return False
    digest = asset.get("digest") or ""
    return not digest.startswith("sha256:") or digest[7:] == sha256_of(path)


def upload_batches(repo, tag, folder, names, clobber):
    for i in range(0, len(names), d7_release.BATCH):
        gh(["release", "upload", tag, "--repo", repo, *(["--clobber"] if clobber else []), *[os.path.join(folder, n) for n in names[i:i + d7_release.BATCH]]])


def publish_chunk(repo, tag, day, pack, folder, names, log=log):
    """Create the release if it is not there, upload what it does not hold and require every file to be there, whole, afterwards. Raises ReleaseError otherwise.

    A file the release already holds (the same name, size and digest) is NOT uploaded again: `--clobber` deletes the old file before it uploads the new one, so a refusal in between
    (GitHub's upload limit, 2026-11-01) lost a file that was fine, and re-sending 800 correct files spent the very allowance that was running out. `--clobber` is only for a file that differs."""
    exists = True
    try:
        d7_release._gh(["release", "view", tag, "--repo", repo, "--json", "tagName"], retry=False)
    except d7_release.ReleaseError:
        exists = False
        notes = ("The Railroad Commission's scanned %s of %s, each tied to the well (API number) it is about. Public records, unmodified; they can carry "
                 "the names, phone numbers and addresses of individuals. A file named <api>_<p|d|c><n>.pdf, .tif or .png is the document; the same name with .jpg is its page one. "
                 "Removed when the day leaves the 92-day archive. Made by site/pipeline/d12_wells.py." % (PACKS[pack][2], day.isoformat()))
        gh(["release", "create", tag, "--repo", repo, "--prerelease", "--latest=false", "--title", "Well images, %s, %s" % (PACKS[pack][2], day.isoformat()), "--notes", notes], timeout=300)
    have = assets_state(repo, tag) if exists else {}
    new = [n for n in names if n not in have]
    changed = [n for n in names if n in have and not same_file(have[n], os.path.join(folder, n))]
    if new or changed:
        wait_for_quota(CALLS_PER_FILE * (len(new) + len(changed)) + RESERVE, log)
    upload_batches(repo, tag, folder, new, clobber=False)
    upload_batches(repo, tag, folder, changed, clobber=True)
    after = assets_state(repo, tag)
    bad = [n for n in names if n not in after or not same_file(after[n], os.path.join(folder, n))]
    if bad:
        raise d7_release.ReleaseError("%d of %d files are not on release %s, whole, after the upload (%s ...)" % (len(bad), len(names), tag, ", ".join(bad[:3])))
    log("release %s: %d files confirmed (%d uploaded, %d replaced, %d already there)" % (tag, len(names), len(new), len(changed), len(names) - len(new) - len(changed)))
    return len(new) + len(changed)


def publish_unit(repo, day, pack, folder, docs, log=log):
    """Upload every document of a pack in releases of at most MAX_ASSETS files. Sets d['tag'] on each doc; returns (tags, files sent): a file the release already held is not sent. All or
    nothing: a failure raises, and the caller records nothing (so no entry ever points at a file that is not there)."""
    tags, sent = [], 0
    for i, group in enumerate(chunks(docs), 1):
        tag = tag_name(day, pack, i)
        names = []
        for d in group:
            names.append("%s.%s" % (d["f"], d["ext"]))
            if d.get("pv"):
                names.append(d["f"] + ".jpg")
        sent += publish_chunk(repo, tag, day, pack, folder, names, log)
        for d in group:
            d["tag"] = tag
        tags.append(tag)
    return tags, sent


def prune_releases(repo, keep_from, log=log):
    """Delete the releases (and tags) of days older than keep_from. Only tags that are exactly wells-YYYY-MM-DD-<pack>-NN are touched."""
    out = d7_release._gh(["release", "list", "--repo", repo, "--limit", "1000", "--json", "tagName"])
    gone = []
    for row in json.loads(out):
        m = TAG.fullmatch(row.get("tagName") or "")
        if m and m.group(1) < keep_from.isoformat():
            d7_release._gh(["release", "delete", row["tagName"], "--repo", repo, "--yes", "--cleanup-tag"])
            gone.append(row["tagName"])
    if gone:
        log("release: removed %d aged-out releases (%s ... %s)" % (len(gone), gone[0], gone[-1]))
    return gone


# ------------------------------------------------------------------------------------------------ the files

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


class Lookups:
    """County names and the operators that may be named, from the committed site data (the same two sources as the Daily report)."""

    def __init__(self, data=DATA):
        geo = read_json(os.path.join(data, "counties.geo.json"), {"features": []})
        self.county = {f["properties"]["f"]: f["properties"]["n"] for f in geo["features"]}
        ops = read_json(os.path.join(data, "operators.json"), {"rows": []})
        self.operator = {r[1]: r[2] for r in ops["rows"]}

    def county_name(self, fips):
        return self.county.get(fips) or "Unknown"


class State:
    """What is published: the packs done (units) and the wells by county, in memory as one structure; load() and save() are the files."""

    def __init__(self):
        self.units = {}  # (day iso, pack) -> {name, bytes, docs, tied, untied, rejected, wells, tags, assetBytes}
        self.counties = {}  # fips -> {api: {a, fl, di, o, docs: [doc]}}   doc: {d, s, k, pg, b, x, f, tag, v}

    @classmethod
    def load(cls, out):
        st = cls()
        idx = read_json(os.path.join(out, "index.json"), None)
        if not idx:
            return st
        for u in idx.get("units", []):
            st.units[(u["d"], u["p"])] = {k: v for k, v in u.items() if k not in ("d", "p")}
        cdir = os.path.join(out, "county")
        for name in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
            sh = read_json(os.path.join(cdir, name), None)
            if not sh or not name.endswith(".json"):
                continue
            wells = {}
            for w in sh.get("wells", []):
                docs = [{"d": x["d"], "s": x["s"], "k": x["k"], "pg": x.get("pg"), "b": x["b"], "x": x["x"], "f": x["f"], "tag": sh["tags"][x["t"]], "v": x.get("v", 0)} for x in w["docs"]]
                wells[w["a"]] = {"a": w["a"], "fl": w.get("fl"), "di": w.get("di"), "o": w.get("o"), "on": w.get("on"), "docs": docs}
            st.counties[sh["county"]] = wells
        return st

    def done(self):
        """{(day, pack): (name, bytes)} of the packs that need no more work. A pack recorded with refusals under older rules (`rules` below RULES; a unit
        written before there were rules has none) is not done: it is read again once, and what a newer rule now accepts is published."""
        return {(date.fromisoformat(d), p): (u["name"], u["bytes"]) for (d, p), u in self.units.items() if not (u.get("rejected", 0) > 0 and u.get("rules", 1) < RULES)}

    def remove(self, day, pack):
        """Take a pack's documents (and its entry) out, wherever they are."""
        stage_letter = PACKS[pack][0]
        self.units.pop((day, pack), None)
        for fips in list(self.counties):
            wells = self.counties[fips]
            for api in list(wells):
                wells[api]["docs"] = [x for x in wells[api]["docs"] if not (x["d"] == day and x["s"] == stage_letter)]
                if not wells[api]["docs"]:
                    del wells[api]
            if not wells:
                del self.counties[fips]

    def add(self, day, pack, unit, docs, lk):
        """Add a pack's published documents (each with its tag) and its entry; replaces the same pack's earlier entry."""
        self.remove(day, pack)
        wells = set()
        for d in docs:
            fips = d["api"][:3]
            w = self.counties.setdefault(fips, {}).setdefault(d["api"], {"a": d["api"], "fl": None, "di": None, "o": None, "on": None, "docs": []})
            if d.get("field"):
                w["fl"] = d["field"]
            if d.get("district"):
                w["di"] = d["district"]
            if d.get("op") and d["op"].isdigit():
                w["o"] = d["op"]
                w["on"] = lk.operator.get(d["op"])  # None for anyone who may not be named
            w["docs"].append({"d": day, "s": d["stage"], "k": d["kind"], "pg": d.get("pg"), "b": d["b"], "x": d["ext"], "f": d["f"], "tag": d["tag"], "v": d.get("pv", 0)})
            wells.add(d["api"])
        tags = sorted({d["tag"] for d in docs})
        self.units[(day, pack)] = dict(unit, wells=len(wells), tags=tags, assetBytes=sum(d["b"] for d in docs))

    def prune(self, keep_from):
        """Remove every pack of a day before keep_from; returns their release tags."""
        gone = []
        for (d, p), u in sorted(self.units.items()):
            if d < keep_from.isoformat():
                gone += u.get("tags", [])
                self.remove(d, p)
        return gone

    def save(self, out, lk, generated, repo):
        cdir = os.path.join(out, "county")
        os.makedirs(cdir, exist_ok=True)
        counties, totals = [], {"wells": 0, "docs": 0, "bytes": 0, "stages": {"p": 0, "d": 0, "c": 0}}
        for fips, wells in sorted(self.counties.items()):
            tags = sorted({x["tag"] for w in wells.values() for x in w["docs"]})
            ti = {t: i for i, t in enumerate(tags)}
            rows, ndocs = [], 0
            for api in sorted(wells):
                w = wells[api]
                docs = sorted(w["docs"], key=lambda x: (x["d"], x["s"], x["f"]), reverse=True)
                rows.append({"a": api, "fl": w["fl"], "di": w["di"], "o": w["o"], "on": lk.operator.get(w["o"]) if w["o"] else None,  # re-derived at every save: a name the site may no longer use leaves the files at the next run
                             "docs": [{"d": x["d"], "s": x["s"], "k": x["k"], "pg": x["pg"], "b": x["b"], "x": x["x"], "f": x["f"], "t": ti[x["tag"]], "v": x["v"]} for x in docs]})
                ndocs += len(docs)
                for x in docs:
                    totals["bytes"] += x["b"]
                    totals["stages"][x["s"]] += 1
            write_json(os.path.join(cdir, fips + ".json"), {"v": 1, "county": fips, "name": lk.county_name(fips), "tags": tags, "wells": rows})
            counties.append([fips, lk.county_name(fips), len(rows), ndocs])
            totals["wells"] += len(rows)
            totals["docs"] += ndocs
        for name in os.listdir(cdir):
            if name.endswith(".json") and name[:-5] not in self.counties:
                os.remove(os.path.join(cdir, name))
        units = [dict({"d": d, "p": p}, **u) for (d, p), u in sorted(self.units.items(), reverse=True)]
        write_json(os.path.join(out, "index.json"), {"v": 1, "generated": generated, "repo": repo, "keepDays": KEEP_DAYS, "units": units, "counties": counties, "totals": totals})


# ------------------------------------------------------------------------------------------------ the check

def check(out, lk=None):
    """Problems with the published files, [] when none: every file parses, every document is where its county and the index say it is, the counts add up,
    every release tag a document names is listed by a pack, nothing a privacy rule forbids, only nameable operators."""
    lk = lk or Lookups()
    bad = []
    idx = read_json(os.path.join(out, "index.json"), None)
    if not idx:
        return ["index.json is missing or not JSON"]
    tags = set()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", str(idx.get("repo", ""))):
        bad.append("index.json names no repository (owner/name)")
    for u in idx.get("units", []):
        if u.get("p") not in PACKS or not re.fullmatch(r"\d{4}-\d\d-\d\d", str(u.get("d"))):
            bad.append("a unit with a bad day or pack: %r" % ({k: u.get(k) for k in ("d", "p")},))
            continue
        for t in u.get("tags", []):
            m = TAG.fullmatch(t)
            if not m or (m.group(1), m.group(2)) != (u["d"], u["p"]):
                bad.append("unit %s %s lists the tag %r" % (u["d"], u["p"], t))
            tags.add(t)
        if u.get("tied", 0) + u.get("untied", 0) + u.get("rejected", 0) != u.get("docs"):
            bad.append("unit %s %s: tied + untied + rejected is not docs" % (u["d"], u["p"]))
    order = [(str(u.get("d")), str(u.get("p"))) for u in idx.get("units", [])]
    if order != sorted(order, reverse=True):
        bad.append("units are not in the order the producer writes them (newest day first)")
    totals = collections.Counter()
    seen = set()
    listed = {(u["d"], u["p"]) for u in idx.get("units", [])}
    cdir = os.path.join(out, "county")
    names = sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []
    for name in names:
        text = open(os.path.join(cdir, name), encoding="utf-8").read()
        for why in privacy_check.scan(text):
            bad.append("%s holds %s" % (name, why))
        if len(text) > 2_500_000:
            bad.append("%s is %d bytes (over the 2.5 MB budget)" % (name, len(text)))
        sh = json.loads(text)
        if name != sh.get("county", "") + ".json" or not re.fullmatch(r"\d{3}", sh.get("county", "")):
            bad.append("%s names the county %r" % (name, sh.get("county")))
            continue
        for w in sh["wells"]:
            if not API8.fullmatch(w["a"]) or w["a"][:3] != sh["county"]:
                bad.append("%s: well %r is not in the county" % (name, w["a"]))
            if w["a"] in seen:
                bad.append("well %s is listed twice" % w["a"])
            seen.add(w["a"])
            if w.get("on") is not None and w["on"] != lk.operator.get(w.get("o")):
                bad.append("%s: well %s names an operator that may not be named" % (name, w["a"]))
            if not w["docs"]:
                bad.append("%s: well %s has no documents" % (name, w["a"]))
            for x in w["docs"]:
                m = STEM.fullmatch(x["f"])
                if (not m or m.group(1) != w["a"] or m.group(2) != x["s"] or x["x"] not in ("pdf", "tif", "png") or not isinstance(x["b"], int) or x["b"] <= 0
                        or not (0 <= x["t"] < len(sh["tags"])) or x["v"] not in (0, 1) or (x["pg"] is not None and not (isinstance(x["pg"], int) and x["pg"] > 0))):
                    bad.append("%s: well %s has a bad document %r" % (name, w["a"], x))
                    continue
                if sh["tags"][x["t"]] not in tags:
                    bad.append("%s: well %s names the release %s, which no pack lists" % (name, w["a"], sh["tags"][x["t"]]))
                if (x["d"], STAGE_PACK[x["s"]]) not in listed:
                    bad.append("%s: well %s has a document of %s that no pack lists" % (name, w["a"], x["d"]))
                totals["docs"] += 1
                totals["bytes"] += x["b"]
            totals["wells"] += 1
    t = idx.get("totals", {})
    if (t.get("wells"), t.get("docs"), t.get("bytes")) != (totals["wells"], totals["docs"], totals["bytes"]):
        bad.append("the index totals %r are not what the county files hold (%r)" % ((t.get("wells"), t.get("docs"), t.get("bytes")), (totals["wells"], totals["docs"], totals["bytes"])))
    if sum(c[2] for c in idx.get("counties", [])) != totals["wells"]:
        bad.append("the index's county rows do not add up to the wells")
    if len(json.dumps(idx)) > 120_000:
        bad.append("index.json is over its 120 KB budget")
    return bad


# ------------------------------------------------------------------------------------------------ the shares

class Shares:
    """The RRC side: listings and downloads. A class so a test can put files in its place.

    Every download gets a NEW session with its listing read again: a share's page (a JSF view) expires after a few minutes without a request, and
    the upload of one pack takes longer than that. The first real run (2026-11-01) read the completion pack and uploaded it in 7 minutes; the next
    five downloads, on the sessions opened before it, were answered HTTP 500 and ViewExpiredException."""

    def __init__(self, log=log):
        self.guid = {d["id"]: d["guid"] for d in d7_daily.DATASETS}
        self.log = log
        self.rows = {}  # how many of a share's newest files the listing reads (set by listings())
        self.key = {"w1": "w1images", "ds": "dirsurveys", "ci": "complimages", "cd": "completions"}

    def fresh(self, key, rows):
        """A share with a session of its own, opened now and listed newest first (what download() needs to find a file)."""
        sh = Share(self.guid[key], Session())
        sh.open()
        sh.newest(rows)
        return sh

    def listings(self, window):
        out = {}
        for pack, key in self.key.items():
            self.rows[pack] = (15 if pack == "w1" else 1) * (window + 6)
            sh = self.fresh(key, self.rows[pack])
            out[pack] = [dict(r) for r in sh.newest(self.rows[pack])]
            sh.s.close()
        return out

    def download(self, pack, name, dest_dir, limit):
        last = None
        for _ in range(2):  # a second try on a session of its own: the first may have met a view that expired between opening and asking
            sh = self.fresh(self.key[pack], self.rows.get(pack) or 60)
            sh.s.attempts, sh.s.timeout, sh.s.deadline = 3, 60, limit
            try:
                return sh.download(name, dest_dir)
            except (ShareError, OSError) as e:
                last = e
            finally:
                sh.s.close()
        raise last

    def permits(self, dest_dir, limit):
        last = None
        for _ in range(2):
            sh = Share(self.guid["permits"], Session())
            sh.open()
            sh.s.attempts, sh.s.timeout, sh.s.deadline = 3, 60, limit
            try:
                sh.newest(rrc_share.PAGE_ROWS)
                if "daf420.dat" not in sh.links:
                    sh.open()
                return sh.download("daf420.dat", dest_dir)
            except (ShareError, OSError) as e:
                last = e
            finally:
                sh.s.close()
        raise last


# ------------------------------------------------------------------------------------------------ one run

def do_unit(u, io, state, lk, repo, work, upload, perms_cache, log=log):
    """Download one pack, tie its documents to wells, stage them, upload them and record them; returns the files uploaded. Raises on a failure; nothing is recorded then."""
    day, pack = u["day"], u["pack"]
    folder = tempfile.mkdtemp(prefix="pack-%s-%s-" % (pack, day), dir=work)
    stage_dir = os.path.join(folder, "stage")
    limit = time.time() + 600
    if rrc_share.DEADLINE is not None:
        limit = min(limit, rrc_share.DEADLINE)
    try:
        path = io.download(pack, u["name"], os.path.join(folder, "zip"), limit)
        if pack == "w1":
            if "perms" not in perms_cache:
                perms_cache["perms"] = permit_ties(d7_daily.read_daf(io.permits(os.path.join(work, "permits-%s" % day), limit)))
            ties = perms_cache["perms"]
        elif pack == "ci":
            ties = packet_ties(io.download("cd", u["cd"], os.path.join(folder, "cd"), limit))
        else:
            ties = None
        with zipfile.ZipFile(path) as zf:
            if pack == "ds":
                ties = survey_ties(zf)
            docs, untied = candidates(zf, pack, ties)
            total = len(d7_packs.documents(zf))
            kept, rejected = stage(zf, docs, stage_dir, log)
        log("%s %s: %d documents, %d tied to a well, %d with no well found, %d refused" % (day, pack, total, len(kept), untied, rejected))
        if not kept:
            state.remove(day.isoformat(), pack)
            state.units[(day.isoformat(), pack)] = {"name": u["name"], "bytes": u["bytes"], "docs": total, "tied": 0, "untied": untied, "rejected": rejected, "rules": RULES, "wells": 0, "tags": [], "assetBytes": 0}
            return 0
        sent = 0
        if upload:
            sent = publish_unit(repo, day, pack, stage_dir, kept, log)[1]
        else:
            for d in kept:
                d["tag"] = tag_name(day, pack, 1)
        state.add(day.isoformat(), pack, {"name": u["name"], "bytes": u["bytes"], "docs": total, "tied": len(kept), "untied": untied, "rejected": rejected, "rules": RULES}, kept, lk)
        return sent
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run(a, io=None, now=None, log=log):
    """One run. Returns the exit code: 0 done (or nothing to do, or the RRC would not answer), 1 a pack failed, 2 the tools are missing."""
    started = time.time()
    out = a.out
    lk = Lookups()
    upload = not a.no_upload
    repo = a.repo or d7_release.repo_name() or ("" if upload else "local/local")
    if upload:
        why = d7_release.ready() or (None if repo else "no repository name")
        if why:
            log("cannot publish: %s" % why)
            return 2
    why = have_tools()
    if why:
        log("cannot draw previews: %s" % why)
        return 2
    d7_release.DEADLINE = started + a.budget * 60 + 120
    rrc_share.DEADLINE = started + a.budget * 60
    state = State.load(out)
    central = now or datetime.now(tz=zoneinfo.ZoneInfo("America/Chicago")).replace(tzinfo=None)
    keep_from = central.date() - timedelta(days=KEEP_DAYS)
    gone = state.prune(keep_from)
    io = io or Shares(log)
    try:
        listed = units_listed(io.listings(a.window))
    except (ShareError, TooSlow, OSError) as e:
        log("the shares did not answer (%s); nothing to do tonight" % privacy_check.clean_error(e))
        return 0
    todo, notes = plan(listed, state.done(), central, days=a.days, window=a.window, only=date.fromisoformat(a.day) if a.day else None)
    for n in notes:
        log(n)
    log("to do: %s" % (", ".join("%s %s" % (u["day"], u["pack"]) for u in todo) or "nothing"))
    work = tempfile.mkdtemp(prefix="d12-", dir=a.dl)
    failures, cache, uploaded = 0, {}, 0
    if upload and todo and quota_line():
        log(quota_line())
    try:
        for u in todo:
            if time.time() - started > a.budget * 60:
                log("out of time: %s %s and what follows are left for the next run" % (u["day"], u["pack"]))
                break
            if uploaded and uploaded + EST_FILES[u["pack"]] > a.max_files:
                log("%s %s: about %d files would pass this run's %d (%d uploaded so far), left for the next run" % (u["day"], u["pack"], EST_FILES[u["pack"]], a.max_files, uploaded))
                continue  # a smaller pack of an older day may still fit
            try:
                if upload:
                    wait_for_quota(RESERVE + 200, log)  # before a download of hundreds of megabytes: is there anything to send it with?
                uploaded += do_unit(u, io, state, lk, repo, work, upload, cache, log)
            except QuotaLow as e:  # not a failure: nothing was recorded for this pack, the files already sent stay, and the next run goes on from there
                log("%s %s deferred: %s; the next run does it" % (u["day"], u["pack"], e))
                break
            except Exception as e:  # noqa: BLE001 - one pack must not stop the next; nothing was recorded for it
                failures += 1
                log("%s %s FAILED: %s" % (u["day"], u["pack"], privacy_check.clean_error(e)))
                if RATE_LIMITED.search(str(e)):  # the next pack would meet the same limit after downloading 300 MB: the third run of 2026-11-01 spent 40 minutes that way
                    log("GitHub is rate limiting uploads: no further pack is started in this run (it will not clear sooner for being asked again)")
                    break
                continue
            state.save(out, lk, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), repo)  # after each pack, so a later failure keeps this one
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if upload and uploaded and quota_line():
        log("after %d files uploaded: %s" % (uploaded, quota_line()))
    if gone:  # the aged-out days leave the files even on a night with nothing new
        state.save(out, lk, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), repo)
    if gone and upload:
        try:
            prune_releases(repo, keep_from, log)
        except d7_release.ReleaseError as e:
            log("could not remove aged-out releases (%s); they are tried again next run" % privacy_check.clean_error(e))
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=DEFAULT_OUT, help="where the files are written (default: site/public/data/wells)")
    ap.add_argument("--dl", default=None, help="where packs are downloaded (default: the system's temporary folder)")
    ap.add_argument("--days", type=int, default=2, help="how many filing days to do, newest first (default 2)")
    ap.add_argument("--window", type=int, default=WINDOW_DAYS, help="how many days back to look (default %d)" % WINDOW_DAYS)
    ap.add_argument("--day", help="do only this filing day (YYYY-MM-DD)")
    ap.add_argument("--repo", help="owner/repo to publish to (default: the origin remote)")
    ap.add_argument("--budget", type=int, default=40, help="minutes after which no new pack or request is started (default 40)")
    ap.add_argument("--max-files", type=int, default=MAX_FILES_PER_RUN, help="files after which no new pack is started (default %d): GitHub's quota is shared with the site's own deploy" % MAX_FILES_PER_RUN)
    ap.add_argument("--no-upload", action="store_true", help="stage and write the files but upload nothing (needs --out somewhere other than the site's folder)")
    ap.add_argument("--check", action="store_true", help="validate the published files and exit")
    a = ap.parse_args(argv)
    if a.check:
        bad = check(a.out)
        print("\n".join(bad) if bad else "ok: the well-image files are consistent")
        return 1 if bad else 0
    if a.no_upload and os.path.abspath(a.out) == os.path.abspath(DEFAULT_OUT):
        sys.exit("--no-upload would write entries for files that are not on GitHub into the site's folder; give --out another folder")
    if not 1 <= a.days <= 10 or not 1 <= a.window <= 120 or not 5 <= a.budget <= 120 or not 100 <= a.max_files <= 20000:
        sys.exit("--days is 1 to 10, --window 1 to 120, --budget 5 to 120 and --max-files 100 to 20000")
    if a.day:
        try:
            date.fromisoformat(a.day)
        except ValueError:
            sys.exit("--day must look like 2026-10-30")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
