#!/usr/bin/env python3
"""D7: readable previews of the Texas completion images, as a step of the nightly capture of its own.

The Commission's "Imaged Completion Files" pack for a day holds about 1,000 scanned documents (560 MB): the completion forms the system
makes (W-2, G-1, L-1, P-4), plats, well logs, cementing reports and whatever else operators attached. The owner decided on 2026-10-31 that
every document of the Texas packs may be published readable (README, Privacy). For this pack that is a JPEG of page one of each document
and nothing else: the originals stay at the Commission (560 MB a day would be 50 GB a quarter, and a release holds 1,000 files).

What this does, for the newest day captured live whose pack landed and that has no file of its own yet:
  1. downloads that day's pack (one file, about 20 seconds; the capture's own copy is deleted when it is done, and a retry of a failed
     night needs one anyway);
  2. draws page one of every document (d7_packs.stage_completions, four at a time: about a minute) under made-up names
     `cm_<district>_<tracking>_<n>.jpg`: nothing in a name comes from the pack;
  3. uploads them as the files of two to three GitHub releases, `daily-YYYY-MM-DD-cm1`, `-cm2` (800 files each; d7_release.py);
  4. writes `site/public/data/daily-cm/<day>.json`: for each completion packet (district, tracking number) its documents' kinds (told by
     file-name pattern) and whether a preview is on the release. Only previews the releases' own listing confirmed are marked.
  5. removes the files and releases of days older than 31 days (about 100 MB a day of previews is what a month costs; the page says so).
Nothing is written unless at least half the documents have a confirmed preview, so a night that broke leaves nothing to commit, and the
next run (the 04:20 backup, or the next night) tries the day again. Run by .github/workflows/daily-rrc-report.yml after the Texas capture.

  python3 -I site/pipeline/d7_completions.py            do the newest day that needs it
  python3 -I site/pipeline/d7_completions.py --check    check the files already written (what the nightly runs before it commits)

Exit code: 0 when a day was done or there was nothing to do; 1 when it could not be done (the workflow turns the run red after committing
and publishing what else worked). The pack is untrusted data: members are copied out one at a time, capped in size, checked for what
they claim to be, drawn under a timeout with the repository tokens scrubbed from the child's environment, and never run.
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d7_daily as D  # noqa: E402 - the capture's own constants and helpers (share ids, atomic writes, the catalog page)
import d7_packs as P  # noqa: E402
import d7_release as R  # noqa: E402
import privacy_check  # noqa: E402
import rrc_share  # noqa: E402

DAILY = D.DEFAULT_OUT
OUT = os.path.join(SITE, "public", "data", "daily-cm")
KEEP_DAYS = 31  # a day's previews weigh about 100 MB: a month of them, not the archive's 92 days
PER_RELEASE = 800  # files on one release (GitHub's limit is 1,000)
TIME_LIMIT_MIN = 14  # no request starts after this; the step's own limit in the workflow is 18
RENDER_MIN = 8  # minutes after which no more previews are started: the upload needs the rest
MIN_SHARE = 0.5  # the file is written only if at least this share of the documents has a confirmed preview
DAY = re.compile(r"\d{4}-\d\d-\d\d")
DAY_FILE = re.compile(r"(\d{4}-\d\d-\d\d)\.json")
INDEX = "index.json"  # {"v": 1, "days": [the days that have a file]}: the page asks for a day's file only when this lists it (a request for a missing file is a failed request)
log = D.log


def day_files(out_dir):
    return sorted(m.group(1) for f in os.listdir(out_dir) for m in [DAY_FILE.fullmatch(f)] if m) if os.path.isdir(out_dir) else []


def write_index(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    D.write_json(os.path.join(out_dir, INDEX), {"v": 1, "days": day_files(out_dir)})


def part_of(index, per=None):
    """The release (1, 2, ...) that holds the document numbered `index` (0-based, in the file's order, drawn or not)."""
    return index // (PER_RELEASE if per is None else per) + 1


def candidates(daily_dir=DAILY):
    """[(report day, pack day, bytes)] of the days captured live whose completion pack landed and was not listed empty, newest first."""
    index = D.read_json(os.path.join(daily_dir, "index.json"), {}) or {}
    out = []
    for row in sorted((r for r in index.get("days", []) if isinstance(r, dict) and r.get("k") == "live"), key=lambda r: r.get("d", ""), reverse=True):
        day = D.read_json(os.path.join(daily_dir, "%s.json" % row.get("d")), {}) or {}
        pack = ((day.get("images") or {}).get("complimages")) or {}
        if DAY.fullmatch(str(pack.get("day"))) and isinstance(pack.get("bytes"), int) and pack["bytes"] >= 2048 and not pack.get("empty"):
            out.append((row["d"], pack["day"], pack["bytes"]))
    return out


def pick(daily_dir=DAILY, out_dir=OUT, only=None):
    """The (report day, pack day, bytes) to do: `only` if named, else the newest live day that has no file in out_dir. None when there is none."""
    found = candidates(daily_dir)
    if only:
        return next((c for c in found if c[0] == only), None)
    if not found:
        return None
    return None if os.path.exists(os.path.join(out_dir, "%s.json" % found[0][0])) else found[0]


def pack_name(pack_day):
    d = date.fromisoformat(pack_day)
    return "%02d-%02d-%04d.zip" % (d.month, d.day, d.year)


def doc_names(packets):
    """[(name, part)] of the documents with a preview drawn, in the file's order: the name is made up from the packet and the document's number
    in it, the part from the document's place in the whole list (a document without a preview still has its place, so parts never move)."""
    out, n = [], 0
    for district, tracking, rows in packets:
        for seq, row in enumerate(rows, 1):
            if row[2]:
                out.append((P.completion_name(district, tracking, seq), part_of(n)))
            n += 1
    return out


def make_doc(day, pack_day, repo, packets, confirmed, built=None):
    """The day's file. `packets` are stage_completions' rows (p = 1 for a preview drawn); `confirmed` the names the releases' listings hold:
    a row is marked 1 only when its preview is confirmed on the release, never because it was drawn."""
    rows_out, n_docs, n_prev = [], 0, 0
    for district, tracking, rows in packets:
        mine = []
        for seq, (k, st, drawn) in enumerate(rows, 1):
            p = 1 if drawn and P.completion_name(district, tracking, seq) in confirmed else 0
            mine.append([k, st, p])
            n_docs += 1
            n_prev += p
        rows_out.append([district, tracking, mine])
    return {"v": 1, "day": day, "packDay": pack_day, "repo": repo, "per": PER_RELEASE, "parts": max(1, math.ceil(n_docs / PER_RELEASE)),
            "kinds": list(P.CM_KINDS), "docs": n_docs, "previews": n_prev, "builtAt": built or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "packets": rows_out}


def problems_of(doc, name=None):
    """What is wrong with a day's file ([] when it is fit to publish): its shape, its counts, and that it holds nothing but codes and
    digits (the privacy gate's scan is run over its text too)."""
    bad = []

    def need(cond, msg):
        if not cond:
            bad.append(msg)
        return cond

    if not need(isinstance(doc, dict), "not an object"):
        return bad
    need(doc.get("v") == 1, "v must be 1")
    need(isinstance(doc.get("day"), str) and DAY.fullmatch(doc["day"]) and (name is None or name == doc["day"]), "day is not the file's day")
    need(isinstance(doc.get("packDay"), str) and DAY.fullmatch(doc["packDay"]), "packDay must be a day")
    need(isinstance(doc.get("repo"), str) and re.fullmatch(r"[\w.-]+/[\w.-]+", doc["repo"]), "repo must be owner/name")
    need(isinstance(doc.get("builtAt"), str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\dZ", doc["builtAt"]), "builtAt must be a UTC time")
    per, kinds, packets = doc.get("per"), doc.get("kinds"), doc.get("packets")
    need(type(per) is int and 1 <= per <= 1000, "per must be between 1 and 1000")
    if not (need(isinstance(kinds, list) and kinds and all(isinstance(k, str) and 0 < len(k) <= 40 for k in kinds), "kinds must be short texts")
            and need(isinstance(packets, list) and packets, "no packets") and type(per) is int):
        return bad
    docs = prev = 0
    for pk in packets:
        if not need(isinstance(pk, list) and len(pk) == 3 and isinstance(pk[0], str) and P.CM_DISTRICT.fullmatch(pk[0]) and isinstance(pk[1], str)
                    and re.fullmatch(r"[1-9]\d{0,11}|0", pk[1]) and isinstance(pk[2], list) and pk[2], "a packet is [district, tracking, documents]"):
            return bad
        for row in pk[2]:
            if not need(isinstance(row, list) and len(row) == 3 and all(type(v) is int for v in row) and 0 <= row[0] < len(kinds) and row[1] in (0, 1) and row[2] in (0, 1),
                        "a document is [kind index, 0 or 1, 0 or 1]"):
                return bad
            docs += 1
            prev += row[2]
    need(doc.get("docs") == docs, "docs is %r but the packets hold %d" % (doc.get("docs"), docs))
    need(doc.get("previews") == prev, "previews is %r but the packets mark %d" % (doc.get("previews"), prev))
    need(doc.get("parts") == max(1, math.ceil(docs / per)), "parts does not fit the document count")
    need(prev >= MIN_SHARE * docs, "fewer than %d%% of the documents have a preview" % (MIN_SHARE * 100))
    need(set(doc) == {"v", "day", "packDay", "repo", "per", "parts", "kinds", "docs", "previews", "builtAt", "packets"}, "unexpected keys: %s" % sorted(set(doc) ^ {"v", "day", "packDay", "repo", "per", "parts", "kinds", "docs", "previews", "builtAt", "packets"}))
    text = json.dumps(doc)
    for what in privacy_check.scan(text):
        bad.append("the file holds " + what)
    return bad


def check(out_dir=OUT, keep=KEEP_DAYS):
    """Problems in every file of out_dir ([] when the folder does not exist at all)."""
    if not os.path.isdir(out_dir):
        return []
    bad, days = [], []
    for f in sorted(os.listdir(out_dir)):
        m = DAY_FILE.fullmatch(f)
        if f == INDEX:
            continue
        if not m:
            bad.append("%s: a file that is not a day's" % f)
            continue
        days.append(m.group(1))
        doc = D.read_json(os.path.join(out_dir, f))
        bad += ["%s: %s" % (f, p) for p in problems_of(doc, m.group(1))]
    if len(days) > keep + 1:
        bad.append("%d files, more than the %d days kept" % (len(days), keep))
    index = D.read_json(os.path.join(out_dir, INDEX))
    if not (isinstance(index, dict) and index.get("v") == 1 and index.get("days") == days and set(index) == {"v", "days"}):
        bad.append("%s does not list exactly the days that have a file" % INDEX)
    return bad


def prune_files(out_dir, newest_day, keep=KEEP_DAYS):
    """Delete the files of days more than `keep` days before newest_day. Returns the days removed."""
    cut = (date.fromisoformat(newest_day) - timedelta(days=keep)).isoformat()
    gone = []
    for f in sorted(os.listdir(out_dir)):
        m = DAY_FILE.fullmatch(f)
        if m and m.group(1) < cut:
            os.remove(os.path.join(out_dir, f))
            gone.append(m.group(1))
    return gone


def upload(repo, day, stage_dir, names_parts, log=log):
    """Upload each part's previews to its release; return the set of names the releases' listings confirm."""
    day_date = date.fromisoformat(day)
    parts = sorted({p for _, p in names_parts})
    confirmed = set()
    for part in parts:
        mine = [n for n, p in names_parts if p == part]
        tag = R.cm_tag_for(day_date, part)
        title = "RRC completion images, report of %s (part %d of %d)" % (day, part, len(parts))
        notes = ("Page one of each document in the Railroad Commission's completion images for the report of %s (part %d of %d), drawn as pictures: readable, "
                 "nothing cropped, blurred or redacted. Public records; they can carry names, phone numbers and addresses of individuals. The Commission keeps "
                 "the originals. Removed after %d days. Made by site/pipeline/d7_completions.py." % (day, part, len(parts), KEEP_DAYS))
        confirmed |= set(R.publish_files(repo, tag, title, notes, stage_dir, mine, log))
    return confirmed


def download_pack(pack_day, expect_bytes, dest_dir, deadline):
    """Download the completion pack of `pack_day` from the Commission's share into dest_dir; returns its path."""
    guid = next(s["guid"] for s in D.DATASETS if s["id"] == "complimages")
    try:
        _rows, nightly = D.read_catalog()
        row = next((r for r in nightly if r["desc"].startswith("Imaged Completion Files")), None)
        guid = (D.guid_of(row["links"]) if row else None) or guid
    except Exception as e:  # noqa: BLE001 - the page is only a check that the share has not moved
        log("catalog: SKIPPED (%s); using the share this script has" % privacy_check.clean_error(e))
    sess = rrc_share.Session()
    sess.attempts, sess.timeout, sess.deadline = 3, 60, deadline
    rrc_share.DEADLINE = deadline
    sh = rrc_share.Share(guid, sess)
    sh.open()
    rows = sh.newest(14)
    name = pack_name(pack_day)
    row = next((r for r in rows if r["name"] == name), None)
    if row is None:
        raise RuntimeError("the pack %s is not among the newest 14 files of the share" % name)
    if expect_bytes and row["bytes"] and abs(row["bytes"] - expect_bytes) > 0.05 * expect_bytes:
        log("note: the share now lists %d bytes for the pack the capture counted at %d" % (row["bytes"], expect_bytes))
    return sh.download(name, dest_dir)


def run(a):
    started = time.time()
    deadline = started + a.time_limit * 60
    R.DEADLINE = deadline + 3 * 60
    todo = pick(a.daily, a.out, a.day)
    if not todo:
        log("completion previews: nothing to do (%s)" % ("no such live day with a completion pack" if a.day else "the newest live day has its file already, or no day has a pack"))
        return 0
    day, pack_day, pack_bytes = todo
    why = P.preview_tools()
    if why:
        log("completion previews: cannot draw (%s)" % why)
        return 1
    repo = a.repo or R.repo_name()
    if not a.no_upload:
        why = R.ready() or (None if repo else "no repository name")
        if why:
            log("completion previews: cannot publish (%s)" % why)
            return 1
    work = tempfile.mkdtemp(prefix="cm-", dir=a.dl)
    try:
        zip_path = a.zip or download_pack(pack_day, pack_bytes, os.path.join(work, "pack"), deadline)
        stage = os.path.join(work, "stage")
        with zipfile.ZipFile(zip_path) as zf:
            docs = P.documents(zf)
            if not docs:
                log("completion previews: the pack holds no documents; nothing to publish")
                return 1
            staged = P.stage_completions(zf, docs, stage, log, deadline=min(deadline, started + RENDER_MIN * 60))
        names_parts = doc_names(staged["packets"])
        if len(names_parts) < MIN_SHARE * staged["docs"]:
            log("completion previews: only %d of %d documents were drawn; nothing is published" % (len(names_parts), staged["docs"]))
            return 1
        confirmed = {n for n, _ in names_parts} if a.no_upload else upload(repo, day, stage, names_parts, log)
        doc = make_doc(day, pack_day, repo or "none/none", staged["packets"], confirmed)
        bad = problems_of(doc, day)
        if bad:
            log("completion previews: the file for %s is not fit to publish (%s); nothing is written" % (day, "; ".join(bad[:3])))
            return 1
        os.makedirs(a.out, exist_ok=True)
        D.write_json(os.path.join(a.out, "%s.json" % day), doc)
        log("completion previews: %s done, %d of %d documents in %d packets have a preview, %d bytes of file" % (
            day, doc["previews"], doc["docs"], len(doc["packets"]), os.path.getsize(os.path.join(a.out, "%s.json" % day))))
        gone = prune_files(a.out, day)
        write_index(a.out)
        if gone:
            log("completion previews: removed the files of %d days past the %d kept (%s ... %s)" % (len(gone), KEEP_DAYS, gone[0], gone[-1]))
        if not a.no_upload:
            try:
                R.prune(repo, date.min, log, cm_oldest_kept=date.fromisoformat(day) - timedelta(days=KEEP_DAYS))
            except R.ReleaseError as e:  # old releases outliving their day for one more night costs nothing else
                log("completion previews: removing aged-out releases SKIPPED (%s)" % privacy_check.clean_error(e))
        return 0
    except Exception as e:  # noqa: BLE001 - a refusing share, a dropped connection, a damaged zip: the day is tried again at the next run
        log("completion previews: FAILED (%s: %s)" % (type(e).__name__, privacy_check.clean_error(e)))
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="D7: readable previews of the Texas completion images (see the module docstring)")
    ap.add_argument("--daily", default=DAILY, help="the Daily archive (to find the live days and their packs)")
    ap.add_argument("--out", default=OUT, help="where the day files are written")
    ap.add_argument("--dl", default=os.path.join(os.path.dirname(SITE), "dl", "daily"), help="folder for the download and the previews (gitignored)")
    ap.add_argument("--day", help="do this report day instead of the newest that needs it (testing, or a repair by hand)")
    ap.add_argument("--repo", help="owner/name of the repository whose releases get the files (default: GITHUB_REPOSITORY, else the origin remote)")
    ap.add_argument("--time-limit", type=float, default=TIME_LIMIT_MIN, help="minutes after which no request is started (default %(default)s)")
    ap.add_argument("--check", action="store_true", help="only check the files already in --out")
    ap.add_argument("--zip", help="testing: use this pack instead of downloading one (needs --no-upload and --out somewhere else)")
    ap.add_argument("--no-upload", action="store_true", help="testing: draw and write the file but publish nothing (every drawn preview is marked as there; needs --out somewhere else)")
    a = ap.parse_args(argv)
    if a.check:
        bad = check(a.out)
        for p in bad:
            log("CHECK failed: " + p)
        log("completion previews: checks %s (%s)" % ("failed" if bad else "ok", a.out))
        return 1 if bad else 0
    if (a.zip or a.no_upload) and os.path.abspath(a.out) == OUT:
        sys.exit("--zip and --no-upload are for testing: give --out a scratch folder")
    if a.zip and not a.no_upload:
        sys.exit("--zip needs --no-upload")
    os.makedirs(a.dl, exist_ok=True)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
