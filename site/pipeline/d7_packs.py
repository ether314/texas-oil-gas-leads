#!/usr/bin/env python3
"""D7 helper: look inside one day's RRC image pack and draw a contact sheet of first pages.

A pack is a zip of scanned filings (PDF and TIFF): approved W-1 letters and plats, directional survey reports, and the
forms, plats, logs and reports filed with completions. What this module publishes by default is deliberately thin:

  docs   how many documents of each kind the pack holds (and, for completions, how many packets they came from)
  sheet  one JPEG with page one of a spread of the documents, each shrunk to 112 px wide and blurred, which cannot be read

The filings carry lease names, well numbers and the names, phone numbers and addresses of individuals, so the sheet never
shows a page legibly, and documents are told apart by name pattern only and counted. Pillow and pdftoppm (poppler-utils)
draw the sheet; without either the counts are still produced and the sheet is skipped.

The one exception, decided on 2026-10-31 and recorded in the README: with --publish-docs the W-1 and survey packs are also
staged readable (stage_pack, below) so d7_release.py can attach them to a GitHub release and each drill's page can link
to its own filings. That is all this module stages: every document of all three packs, completion images included, is published by d12_wells.py
(from 2026-11-01), each under its well.

The pack is untrusted data. Members are read one at a time, capped in size, rendered under a timeout and never run.
Python standard library, plus Pillow and pdftoppm when a sheet is wanted.
"""
import collections
import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
import zlib

# A tile is 112 px wide, about 13 dots an inch for a letter page, and blurred: at 128 px without a blur the largest print on
# a cover page (an operator, a county) could still be read with a zoom, and the blur makes sure nothing is, whatever the page.
TILE_W, TILE_H, GAP, COLS = 112, 145, 4, 8
BLUR = 1.2
TILES = 16
MAX_MEMBER = 12_000_000  # bytes a member may unpack to before it is skipped
PER_FILE_SECONDS = 25
BUDGET_SECONDS = 100  # for all the tiles of one sheet
SHEET_BYTES = 120_000  # the sheet is recompressed until it fits
DOC_EXT = (".pdf", ".tif", ".tiff")
MAX_TYPES = 12  # completion packs have about a dozen kinds; beyond this the smallest fold into Other


class ToolsMissing(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ kinds (by name pattern)

def kind_w1(base):
    """'<permit>_<Kind>_<free text>.pdf': W1 is the approved W-1 letter, Plat a permit plat."""
    m = re.match(r"\d+_([A-Za-z0-9-]+?)_", base)
    return {"w1": "Approved W-1", "plat": "Permit plat"}.get(m.group(1).lower() if m else "", "Other")


def kind_dir(base):
    return "Directional survey" if base.lower().startswith("dir_survey_") else "Other"


FORMS = {"g1": "G-1 form", "w2": "W-2 form", "l1": "L-1 form", "p4": "P-4 form"}
ATTACHMENTS = [
    ("Plat", re.compile(r"plat", re.I)),
    ("Well log", re.compile(r"\blog\b|\bgau\b|\bgr\b|\bcnl\b|neutron|density|resist", re.I)),
    ("Cementing report (W-15)", re.compile(r"w-?15|cement", re.I)),
    ("Acreage designation (P-16)", re.compile(r"p-?16", re.I)),
    ("Directional survey", re.compile(r"survey|dir[ _-]?sur|\bds\b|deviation", re.I)),
    ("Inclination report (W-12)", re.compile(r"w-?12|inclin", re.I)),
]


def kind_comp(base):
    """Completion packets hold the forms the system makes (cmpl_<Form>Form_PID_<n>.pdf) and what the operator attached."""
    m = re.match(r"cmpl_([A-Za-z0-9]+?)Form", base, re.I)
    if m:
        return FORMS.get(m.group(1).lower(), "Other form")
    for label, rx in ATTACHMENTS:
        if rx.search(base):
            return label
    return "Other attachment"


KINDS = {"w1images": kind_w1, "dirsurveys": kind_dir, "complimages": kind_comp}


# ------------------------------------------------------------------------------------------------ what is in the pack

def documents(zf):
    """[(info, base name)] for the filings in a pack: PDF and TIFF members; folders, CSVs and the rest are left out."""
    out = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower().endswith(DOC_EXT):
            out.append((info, base))
    return out


def describe(docs, ds):
    """{'n': documents, 'types': [[kind, count], ...] largest first with 'Other' last (it also takes the kinds beyond the
    biggest few, so the counts add up to n), 'packets': completion packets or None}."""
    kind = KINDS[ds]
    counts = collections.Counter(kind(base) for _, base in docs)
    named = sorted(((k, n) for k, n in counts.items() if k != "Other"), key=lambda kv: (-kv[1], kv[0]))
    other = counts.get("Other", 0)
    if len(named) > MAX_TYPES - 1:
        other += sum(n for _, n in named[MAX_TYPES - 1:])
        named = named[:MAX_TYPES - 1]
    ranked = named + ([("Other", other)] if other else [])
    packets = None
    if ds == "complimages":  # <district>/trackingNo_<n>_Images_Submitted/<file>
        folders = {i.filename.replace("\\", "/").split("/")[1] for i, _ in docs if i.filename.replace("\\", "/").count("/") >= 2}
        packets = len(folders)
    return {"n": len(docs), "types": [[k, n] for k, n in ranked], "packets": packets}


# ------------------------------------------------------------------------------------------------ the contact sheet

def pick(docs, ds, count=TILES):
    """A spread of the documents, one kind after another so every kind shows, chosen by a hash of the name so the choice
    does not depend on the order in the zip. Members over MAX_MEMBER are never picked."""
    kind = KINDS[ds]
    groups = collections.defaultdict(list)
    for info, base in docs:
        if info.file_size <= MAX_MEMBER:
            groups[kind(base)].append((zlib.crc32(info.filename.encode("utf-8", "replace")), info))
    for g in groups.values():
        g.sort(key=lambda t: t[0])
    order = sorted(groups, key=lambda k: (-len(groups[k]), k))
    picks, depth = [], 0
    while len(picks) < count and any(depth < len(g) for g in groups.values()):
        for k in order:
            if depth < len(groups[k]) and len(picks) < count:
                picks.append(groups[k][depth][1])
        depth += 1
    return picks


def scrubbed_env():
    """The environment for a child that parses a file a server sent (poppler): everything but the tokens that can write to the repository."""
    return {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN") and not k.startswith("ACTIONS_")}


def render_first_page(zf, info, tmp, Image):
    """Page one of a member as a PIL image about twice the tile size, or raises."""
    data = zf.read(info)
    if info.filename.lower().endswith(".pdf"):
        src = os.path.join(tmp, "page.pdf")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-scale-to-x", str(TILE_W * 2), "-scale-to-y", "-1", "-jpeg", "-jpegopt", "quality=70",
                        src, os.path.join(tmp, "out")], check=True, timeout=PER_FILE_SECONDS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=scrubbed_env())
        out = sorted(f for f in os.listdir(tmp) if f.startswith("out"))
        with Image.open(os.path.join(tmp, out[0])) as im:
            return im.convert("RGB")
    with Image.open(io.BytesIO(data)) as im:
        im.seek(0)
        im.draft("RGB", (TILE_W * 2, TILE_H * 2))
        return im.convert("L").convert("RGB") if im.mode in ("1", "L", "P") else im.convert("RGB")


def contact_sheet(zf, docs, ds, out_path, count=TILES, log=print):
    """Write the sheet to out_path; return {'file': name, 'w', 'h', 'tiles', 'px'} or None when no page could be drawn."""
    try:
        from PIL import Image, ImageFilter
    except ImportError as e:
        raise ToolsMissing("Pillow is not installed") from e
    if shutil.which("pdftoppm") is None:
        raise ToolsMissing("pdftoppm (poppler-utils) is not installed")
    Image.MAX_IMAGE_PIXELS = 120_000_000  # a TIFF that unpacks past this is refused rather than drawn
    tiles, started, failed = [], time.time(), 0
    for info in pick(docs, ds, count):
        if time.time() - started > BUDGET_SECONDS or failed >= 6:
            break
        with tempfile.TemporaryDirectory() as tmp:
            try:
                im = render_first_page(zf, info, tmp, Image)
            except Exception:  # noqa: BLE001 - one bad scan must not stop the sheet
                failed += 1
                continue
        im.thumbnail((TILE_W, TILE_H), Image.LANCZOS)
        im = im.filter(ImageFilter.GaussianBlur(BLUR))
        tile = Image.new("RGB", (TILE_W, TILE_H), (233, 236, 239))
        tile.paste(im, ((TILE_W - im.width) // 2, (TILE_H - im.height) // 2))
        tiles.append(tile)
    if not tiles:
        return None
    rows = (len(tiles) + COLS - 1) // COLS
    width, height = COLS * (TILE_W + GAP) + GAP, rows * (TILE_H + GAP) + GAP
    sheet = Image.new("RGB", (width, height), (206, 212, 218))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (GAP + (i % COLS) * (TILE_W + GAP), GAP + (i // COLS) * (TILE_H + GAP)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    for quality in (62, 52, 42):
        sheet.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)  # no EXIF: nothing is copied from the scans
        if os.path.getsize(out_path) <= SHEET_BYTES:
            break
    log("pack sheet %s: %d tiles, %d bytes" % (os.path.basename(out_path), len(tiles), os.path.getsize(out_path)))
    return {"file": os.path.basename(out_path), "w": width, "h": height, "tiles": len(tiles), "px": TILE_W, "blur": BLUR}


def inspect_pack(zip_path, ds, sheet_path, log=print):
    """(docs, sheet) for one pack: the counts always, the sheet when Pillow and pdftoppm are there and a page could be drawn."""
    with zipfile.ZipFile(zip_path) as zf:
        docs = documents(zf)
        info = describe(docs, ds)
        sheet = None
        if docs:
            try:
                sheet = contact_sheet(zf, docs, ds, sheet_path, log=log)
            except ToolsMissing as e:
                log("%s: no sheet (%s)" % (ds, e))
    return info, sheet


# ------------------------------------------------------------------------------------------------ documents to publish
#
# Decided 2026-10-31 (README, Privacy): the approved W-1 letters, permit plats and directional surveys are republished
# readable, unmodified, as files of one GitHub release a day (d7_release.py), and each drill's page links to its own. They are the
# RRC's public records but can carry the names, phone numbers and addresses of individuals, and nothing here redacts them.
# This staging is only for the drill pages' links; d12_wells.py publishes every document of the three packs (completion images too), under its well.
# The contact sheet above stays blurred. Only run when asked (--publish-docs).

MAX_ASSET = 40_000_000  # bytes a document may be before it is left out (a release file may be 2 GB; the pack is untrusted)
MAGIC = {".pdf": (b"%PDF",), ".tif": (b"II*\x00", b"MM\x00*"), ".tiff": (b"II*\x00", b"MM\x00*")}
W1_NAME = re.compile(r"(\d+)_([A-Za-z0-9-]+?)_")
SURVEY_NAME = re.compile(r"dir_survey_(\d{1,12})\.pdf", re.I)
W1_KINDS = {"w1": "W1", "plat": "Plat"}
ISO_DAY = re.compile(r"\d{4}-\d\d-\d\d")


def copy_member(zf, info, dest):
    """Write one member to dest and return its size, or None (and no file) when it is too big or is not what its extension says.
    Names are made up by the caller, never taken from the pack, so nothing in the pack can pick a path."""
    ext = os.path.splitext(info.filename)[1].lower()
    if info.file_size > MAX_ASSET or ext not in MAGIC:
        return None
    written, head = 0, b""
    try:
        with zf.open(info) as src, open(dest, "wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                if not head:
                    head = chunk[:4]
                written += len(chunk)
                if written > MAX_ASSET:
                    raise ValueError("unpacks past the limit")
                dst.write(chunk)
        if head not in MAGIC[ext]:
            raise ValueError("not a %s file" % ext)
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error):
        if os.path.exists(dest):
            os.remove(dest)
        return None
    return written


def stage_w1(zf, docs, out_dir, log=print):
    """Copy each permit's approved W-1 letter and plats to out_dir as <permit>_W1.pdf, <permit>_Plat_1.pdf, ... (permit padded to
    7 digits like the report's rows; numbered when a permit has several of a kind). Returns {permit: [[suffix, bytes], ...]}."""
    groups = collections.defaultdict(list)
    for info, base in docs:
        m = W1_NAME.match(base)
        kind = W1_KINDS.get(m.group(2).lower()) if m else None
        if kind:
            groups[("%07d" % int(m.group(1)), kind)].append((info.filename, info, os.path.splitext(base)[1].lower()))
    os.makedirs(out_dir, exist_ok=True)
    out = collections.defaultdict(list)
    for (permit, kind), items in sorted(groups.items()):
        items.sort(key=lambda t: t[0])  # numbering must not depend on the zip's order
        for n, (_, info, ext) in enumerate(items, 1):
            suffix = kind + ("" if len(items) == 1 else "_%d" % n) + ext
            size = copy_member(zf, info, os.path.join(out_dir, "%s_%s" % (permit, suffix)))
            if size is None:
                log("w1images: one document of permit %s was left out (too large or not a document)" % permit)
            else:
                out[permit].append([suffix, size])
    return dict(out)


def _int(text):
    try:
        v = int(float(text))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def stage_surveys(zf, docs, out_dir, log=print):
    """Copy the directional survey PDFs to out_dir as dir_survey_<id>.pdf (the pack's own names, which are only digits) and read the
    pack's CSV for the well each belongs to. Returns [[api, county, 'M'|'O', from depth, to depth, start, end, lateral, id, bytes], ...]
    ('M' is an MWD survey, 'O' any other kind; the county is the API number's first three digits)."""
    meta = {}
    for info in zf.infolist():
        if info.filename.lower().endswith(".csv") and not info.is_dir() and info.file_size <= 5_000_000:
            for r in csv.DictReader(io.StringIO(zf.read(info).decode("latin-1"))):
                meta[(r.get("EXTERNAL_ATTACHMENT_ID") or "").strip()] = r
            break
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for info, base in sorted(docs, key=lambda t: t[1]):
        m = SURVEY_NAME.fullmatch(base)
        if not m:
            continue
        r = meta.get(m.group(1), {})
        api = (r.get("API_NO") or "").strip()
        api = api if re.fullmatch(r"\d{8}", api) else None
        size = copy_member(zf, info, os.path.join(out_dir, "dir_survey_%s.pdf" % m.group(1)))
        if size is None:
            log("dirsurveys: survey %s was left out (too large or not a PDF)" % m.group(1))
            continue
        day = lambda k: (r.get(k) or "").strip() if ISO_DAY.fullmatch((r.get(k) or "").strip()) else None  # noqa: E731
        label = (r.get("LATERAL_LABEL") or "").strip()
        out.append([api, api[:3] if api else None, "M" if "MWD" in (r.get("ATTACHMENT_TYPE_CODE") or "").upper() else "O",
                    _int(r.get("FROM_DEPTH")), _int(r.get("TO_DEPTH")), day("SURVEY_START_DT"), day("SURVEY_END_DT"),
                    label[:12] if re.fullmatch(r"[\w .-]{1,12}", label) else None, m.group(1), size])
    out.sort(key=lambda row: (row[0] or "", row[8]))
    return out


def stage_pack(zip_path, ds, out_dir, log=print):
    """Copy the publishable documents of a pack into out_dir. {'permits': ...} for the W-1 pack, {'surveys': ...} for the survey
    pack, None for any other (completion images are published by d12_wells.py, not here)."""
    if ds not in ("w1images", "dirsurveys"):
        return None
    with zipfile.ZipFile(zip_path) as zf:
        docs = documents(zf)
        if ds == "w1images":
            return {"permits": stage_w1(zf, docs, out_dir, log)}
        return {"surveys": stage_surveys(zf, docs, out_dir, log)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4 or sys.argv[1] not in KINDS:
        sys.exit("usage: d7_packs.py <w1images|dirsurveys|complimages> <pack.zip> <sheet.jpg>")
    d, s = inspect_pack(sys.argv[2], sys.argv[1], sys.argv[3])
    print(d)
    print(s)
