"""Tests for d7_packs.py and its wiring in d7_daily.py (synthetic packs built with Pillow; needs Pillow and poppler's pdftoppm; no network).

Run: python3 -I tests/test_d7_packs.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import importlib.util
import io
import json
import os
import random
import sys
import tempfile
import time
import types
import zipfile
from datetime import date

sys.path.insert(0, PIPE)
import d7_packs as P  # noqa: E402
from PIL import Image  # noqa: E402

spec = importlib.util.spec_from_file_location("d7", _os.path.join(PIPE, "d7_daily.py"))
d7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d7)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def page(w=850, h=1100, shade=255):
    im = Image.new("RGB", (w, h), (shade, shade, shade))
    for i in range(0, h, 40):  # some "text" lines
        for x in range(60, w - 60, 3):
            im.putpixel((x, i), (30, 30, 30))
    return im


def pdf_bytes(**kw):
    b = io.BytesIO()
    page(**kw).save(b, "PDF", resolution=100)
    return b.getvalue()


def tif_bytes():
    b = io.BytesIO()
    page(shade=250).convert("L").convert("1").save(b, "TIFF", compression="group4")
    return b.getvalue()


SECRETS = ["ODOM", "ERNEST SMITH", "Concho", "917276", "GRATTON", "Winston"]  # names that must never reach a report


def make_comp(path, extra=True):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for t in range(1, 6):
            base = "09/trackingNo_%d_Images_Submitted/" % (364020 + t)
            z.writestr(base + "cmpl_W2Form_PID_%d.pdf" % t, pdf_bytes())
            z.writestr(base + "cmpl_G1Form_PID_%d.pdf" % t, pdf_bytes(shade=250))
            z.writestr(base + "ODOM %dH - PLAT.TIF" % t, tif_bytes())
            z.writestr(base + "ERNEST SMITH A %dH - GAU.pdf" % t, pdf_bytes())
            z.writestr(base + "Concho 20%d Production W15 .pdf" % t, pdf_bytes())
            z.writestr(base + "Concho 20%d misc notes.pdf" % t, pdf_bytes())
            z.writestr(base + "cmpl_P4Form_PID_%d.pdf" % t, pdf_bytes())
        if extra:
            z.writestr("7C/trackingNo_999999_Images_Submitted/broken scan.pdf", b"%PDF-1.4 this is not a pdf")
            z.writestr("7C/trackingNo_999999_Images_Submitted/readme.txt", b"hello")
            big = zipfile.ZipInfo("7C/trackingNo_999999_Images_Submitted/huge plat.pdf")
            big.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(big, b"0" * 13_000_000)


def make_w1(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(6):
            z.writestr("2026-10-29\\06\\917%03d_W1_AsApprovedW1-10-29-2026_LTR.pdf" % n, pdf_bytes(w=1100, h=850))
            z.writestr("2026-10-29\\06\\917%03d_Plat_GRATTON %dH final plat.pdf" % (n, n), pdf_bytes())
        z.writestr("2026-10-29\\06\\917276_Other_cover letter.pdf", pdf_bytes())


def make_dir(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(4):
            z.writestr("dir_survey_99%04d.pdf" % n, pdf_bytes())
        z.writestr("directional_surveys_10-29-2026_0.csv", "a,b\n1,2\n")


tmp = tempfile.mkdtemp()
comp, w1, dirz = (os.path.join(tmp, n) for n in ("comp.zip", "w1.zip", "dir.zip"))
make_comp(comp)
make_w1(w1)
make_dir(dirz)

# ------------------------------------------------------------------ kinds and counts
with zipfile.ZipFile(comp) as z:
    docs = P.documents(z)
    info = P.describe(docs, "complimages")
check(info["n"] == 5 * 7 + 1 + 1 and info["packets"] == 6, "complimages: documents are PDFs and TIFFs only (text file left out): n=%d packets=%s" % (info["n"], info["packets"]))
found = dict(info["types"])
check(found["W-2 form"] == 5 and found["G-1 form"] == 5 and found["P-4 form"] == 5 and found["Plat"] == 5 + 1, "complimages: forms and plats counted by pattern %r" % found)
check(found["Well log"] == 5 and found["Cementing report (W-15)"] == 5 and found["Other attachment"] == 5 + 1, "complimages: logs, W-15 and other attachments %r" % found)
check(sum(n for _, n in info["types"]) == info["n"], "complimages: the kinds add up to the document count")
check(info["types"][0][1] >= info["types"][-1][1] or info["types"][-1][0] == "Other", "complimages: largest kind first")

with zipfile.ZipFile(w1) as z:
    iw = P.describe(P.documents(z), "w1images")
check(dict(iw["types"]) == {"Approved W-1": 6, "Permit plat": 6, "Other": 1} and iw["types"][-1][0] == "Other" and iw["packets"] is None, "w1images: approved letters, plats and the rest %r" % iw["types"])
with zipfile.ZipFile(dirz) as z:
    idr = P.describe(P.documents(z), "dirsurveys")
check(idr["n"] == 4 and idr["types"] == [["Directional survey", 4]], "dirsurveys: the CSV is not a document")

# more kinds than fit: the smallest fold into Other and the total still adds up
old = P.MAX_TYPES
P.MAX_TYPES = 4
with zipfile.ZipFile(comp) as z:
    folded = P.describe(P.documents(z), "complimages")
P.MAX_TYPES = old
check(len(folded["types"]) == 4 and folded["types"][-1][0] == "Other" and sum(n for _, n in folded["types"]) == folded["n"], "describe: kinds beyond the limit fold into Other and still add up %r" % folded["types"])

# ------------------------------------------------------------------ the pick
with zipfile.ZipFile(comp) as z:
    docs = P.documents(z)
    pk = P.pick(docs, "complimages", 16)
    shuffled = docs[:]
    random.Random(3).shuffle(shuffled)
    pk2 = P.pick(shuffled, "complimages", 16)
check([i.filename for i in pk] == [i.filename for i in pk2], "pick: the same documents whatever the order in the zip")
kinds = {P.kind_comp(i.filename.rsplit("/", 1)[-1]) for i in pk}
check(len(pk) == 16 and len(kinds) >= 7, "pick: every kind shows before any repeats (%d kinds in 16 tiles)" % len(kinds))
check(all(i.file_size <= P.MAX_MEMBER for i in pk) and not any("huge" in i.filename for i in pk), "pick: a member over the size cap is never picked")

# ------------------------------------------------------------------ the sheet
logs = []
out = os.path.join(tmp, "img", "2026-10-30-complimages.jpg")
d, sheet = P.inspect_pack(comp, "complimages", out, logs.append)
check(sheet is not None and os.path.getsize(out) <= P.SHEET_BYTES, "sheet: written and within %d bytes (%s)" % (P.SHEET_BYTES, sheet))
with Image.open(out) as im:
    check(im.size == (sheet["w"], sheet["h"]) and im.format == "JPEG" and not im.getexif(), "sheet: a JPEG of the stated size with no metadata")
check(sheet["tiles"] == 16 and sheet["px"] == P.TILE_W == 112 and sheet["blur"] == P.BLUR == 1.2 and sheet["w"] == 8 * (P.TILE_W + P.GAP) + P.GAP and sheet["h"] == 2 * (P.TILE_H + P.GAP) + P.GAP, "sheet: 16 tiles of 112 px, blurred, in two rows (%dx%d)" % (sheet["w"], sheet["h"]))
check(sheet["tiles"] >= 14, "sheet: the broken scan and the oversized member were skipped, the rest drawn")
blob = json.dumps({"docs": d, "sheet": sheet}) + " ".join(logs)
check(not any(s.lower() in blob.lower() for s in SECRETS), "privacy: no file name, lease name or permit number appears in the counts, the sheet record or the log")

d1, s1 = P.inspect_pack(w1, "w1images", os.path.join(tmp, "img", "w1.jpg"), logs.append)
check(s1["tiles"] == 13 and d1["n"] == 13, "w1images: 13 documents, 13 tiles (fewer than 16, one row of 8 and one of 5)")
d2, s2 = P.inspect_pack(dirz, "dirsurveys", os.path.join(tmp, "img", "dir.jpg"), logs.append)
check(s2["tiles"] == 4 and s2["h"] == P.TILE_H + 2 * P.GAP, "dirsurveys: four tiles, one row")

def striped_pdf():
    im = Image.new("RGB", (850, 1100), (255, 255, 255))
    for y in range(0, 1100, 3):
        for x in range(0, 850):
            im.putpixel((x, y), (0, 0, 0))
    b = io.BytesIO()
    im.save(b, "PDF", resolution=100)
    return b.getvalue()


stripes = os.path.join(tmp, "stripes.zip")
with zipfile.ZipFile(stripes, "w") as z:
    z.writestr("dir_survey_1.pdf", striped_pdf())
dst, sst = P.inspect_pack(stripes, "dirsurveys", os.path.join(tmp, "img", "stripes.jpg"))
with Image.open(os.path.join(tmp, "img", "stripes.jpg")) as im:
    box = im.convert("L").crop((P.GAP + 20, P.GAP + 20, P.GAP + 90, P.GAP + 120))
    lo, hi = box.getextrema()
check(hi - lo <= 40, "blur: a page of fine black lines comes out as near-flat gray (range %d..%d), not stripes" % (lo, hi))

# an empty pack (only a CSV) has counts of zero and no sheet
empty = os.path.join(tmp, "empty.zip")
with zipfile.ZipFile(empty, "w") as z:
    z.writestr("directional_surveys_10-25-2026_0.csv", "a\n")
de, se = P.inspect_pack(empty, "dirsurveys", os.path.join(tmp, "img", "empty.jpg"), logs.append)
check(de == {"n": 0, "types": [], "packets": None} and se is None and not os.path.exists(os.path.join(tmp, "img", "empty.jpg")), "empty pack: zero documents, no sheet")

# ------------------------------------------------------------------ missing tools, bad zip
real_which = P.shutil.which
P.shutil.which = lambda name: None
msgs = []
dn, sn = P.inspect_pack(w1, "w1images", os.path.join(tmp, "img", "nope.jpg"), msgs.append)
P.shutil.which = real_which
check(dn["n"] == 13 and sn is None and any("pdftoppm" in m for m in msgs), "no pdftoppm: the counts still come, the sheet is skipped and says why")
saved = sys.modules.get("PIL")
sys.modules["PIL"] = None  # makes `from PIL import Image` raise ImportError
msgs = []
dn, sn = P.inspect_pack(w1, "w1images", os.path.join(tmp, "img", "nope.jpg"), msgs.append)
sys.modules["PIL"] = saved
check(dn["n"] == 13 and sn is None and any("Pillow" in m for m in msgs), "no Pillow: the counts still come, the sheet is skipped and says why")
junk = os.path.join(tmp, "junk.zip")
open(junk, "wb").write(b"not a zip at all")
try:
    P.inspect_pack(junk, "w1images", os.path.join(tmp, "img", "x.jpg"))
    check(False, "a file that is not a zip raises")
except zipfile.BadZipFile:
    check(True, "a file that is not a zip raises BadZipFile (pack_preview catches it)")

# ------------------------------------------------------------------ d7_daily wiring
class FakeShare:
    fail = False

    def __init__(self, guid, sess=None):
        self.guid, self.total = guid, 10
        self.s = types.SimpleNamespace(attempts=18, timeout=120, deadline=None)

    def open(self):
        pass

    def newest(self, n):
        return [{"name": "10-29-2026.zip", "modified": "2026-10-30T02:24:54", "bytes": 5_000_000, "size": "5 MB", "link": "x"}]

    def download(self, name, dest):
        if FakeShare.fail:
            raise d7.ShareError("share dropped the connection")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, name)
        make_comp(path, extra=False)
        return path


d7.Share = FakeShare
d7.Session = lambda *a, **k: types.SimpleNamespace(retries=0)
logged = []
d7.log = lambda m: logged.append(m)
R = date(2026, 10, 30)
ctx = {"R": R, "today": R, "dates": [date(2026, 10, 29), R], "dl": os.path.join(tmp, "dl"), "guid": {"complimages": "G"}, "packs": True,
       "img_out": os.path.join(tmp, "out", "img"), "lk": None}
ij = d7.images_job(ctx, "complimages")
got = ij["docs"][R]
check(got and got["docs"]["n"] == 5 * 7 and got["sheet"]["file"] == "2026-10-30-complimages.jpg" and os.path.isfile(os.path.join(tmp, "out", "img", "2026-10-30-complimages.jpg")),
      "images_job --packs: the live day's pack is counted and drawn into img/<day>-<pack>.jpg")
check(not os.path.exists(os.path.join(ctx["dl"], "pack-complimages-2026-10-30", "10-29-2026.zip")), "images_job --packs: the downloaded zip is deleted afterwards")
check(date(2026, 10, 29) not in ij["docs"], "images_job --packs: only the live day is opened")
FakeShare.fail = True
ij2 = d7.images_job(ctx, "complimages")
check(ij2["docs"][R] is None and any("pack preview SKIPPED" in m for m in logged) and ij2["picked"][R]["name"] == "10-29-2026.zip", "images_job --packs: a failed download skips the preview and keeps the dataset")
FakeShare.fail = False
ij3 = d7.images_job(dict(ctx, packs=False), "complimages")
check("docs" not in ij3, "images_job without --packs: no download")

# the reports carry docs and sheet for the live day only
jobs = {"complimages": ij}
reps = d7.build_reports(dict(ctx, dates=[R], lk=types.SimpleNamespace()), jobs, {}, {R: "live"})
blk = reps[R]["images"]["complimages"]
check(blk["docs"]["n"] == 35 and blk["sheet"]["tiles"] == 16 and blk["day"] == "2026-10-29", "build_reports: the pack block carries docs and sheet")

# ------------------------------------------------------------------ validate and prune
out = os.path.join(tmp, "out")
rep = reps[R]
rep.update({"kind": "live", "status": "ok", "capturedAt": "2026-10-31T03:20:00Z"})
rep["datasets"] = [{"id": s["id"], "title": s["title"], "cadence": None, "dataDay": None, "error": None, "file": None} for s in d7.DATASETS]
json.dump(rep, open(os.path.join(out, "2026-10-30.json"), "w"))
json.dump({"keep": 92, "days": [d7.headline(rep)]}, open(os.path.join(out, "index.json"), "w"))
json.dump({"days": [], "total": [], "newDrill": [], "horizontal": []}, open(os.path.join(out, "permits-series.json"), "w"))
problems = [p for p in d7.validate(out) if "sheet" in p or "kinds" in p]
check(problems == [], "validate: a sheet that exists and kinds that add up pass %r" % problems)
os.remove(os.path.join(out, "img", "2026-10-30-complimages.jpg"))
check(any("sheet is missing" in p for p in d7.validate(out)), "validate: a missing sheet is reported")
make_w1(os.path.join(tmp, "w1b.zip"))
P.inspect_pack(os.path.join(tmp, "w1b.zip"), "w1images", os.path.join(out, "img", "2026-10-30-w1images.jpg"))  # a sheet no day file refers to
open(os.path.join(out, "img", "2026-01-01-w1images.jpg"), "wb").write(b"x")
d7.prune_images(out)
check(os.path.isdir(os.path.join(out, "img")) is False, "prune_images: sheets no day file refers to are deleted, and the empty folder goes")
rep["images"]["complimages"]["sheet"]["file"] = "2026-10-30-w1images.jpg"
json.dump(rep, open(os.path.join(out, "2026-10-30.json"), "w"))
os.makedirs(os.path.join(out, "img"), exist_ok=True)
P.inspect_pack(os.path.join(tmp, "w1b.zip"), "w1images", os.path.join(out, "img", "2026-10-30-w1images.jpg"))
open(os.path.join(out, "img", "stale.jpg"), "wb").write(b"x")
d7.prune_images(out)
check(os.listdir(os.path.join(out, "img")) == ["2026-10-30-w1images.jpg"], "prune_images: the sheet a day file refers to stays, the stale one goes")

# ================================================================== readable previews (2026-11-01)
# page one of each published document, as a JPEG about 900 px wide beside it (<document>.jpg): readable, never blurred


def multi_page_pdf():
    """page one: white with dark lines; page two: solid black (a preview must be of page one only)"""
    b = io.BytesIO()
    page().save(b, "PDF", resolution=100, save_all=True, append_images=[Image.new("RGB", (850, 1100), (0, 0, 0))])
    return b.getvalue()


def tall_tif():
    """a 2550 x 3300 bilevel scan (300 dpi letter) with ruled lines: wider than a preview, so it is shrunk to 900"""
    im = Image.new("1", (2550, 3300), 1)
    for y in range(120, 3300, 120):
        im.paste(0, (180, y, 2370, y + 8))
    b = io.BytesIO()
    im.save(b, "TIFF", compression="group4")
    return b.getvalue()


def color_pdf():
    im = page()
    for x in range(100, 300):
        for y in range(100, 300):
            im.putpixel((x, y), (220, 30, 30))  # a red stamp
    b = io.BytesIO()
    im.save(b, "PDF", resolution=100)
    return b.getvalue()


def jpeg_of(path):
    with Image.open(path) as im:
        return im.format, im.mode, im.size, bool(im.getexif()), im.convert("L").getextrema()


pv = os.path.join(tmp, "pv")
os.makedirs(pv)
src = os.path.join(pv, "0917001_W1.pdf")
open(src, "wb").write(pdf_bytes())
n = P.render_preview(src, src + ".jpg")
fmt, mode, size, exif, ext = jpeg_of(src + ".jpg")
check(fmt == "JPEG" and 880 <= size[0] <= 920 and n == os.path.getsize(src + ".jpg") <= P.PREVIEW_BYTES, "preview: a JPEG about 900 px wide (%s), %d bytes, within %d" % (size, n, P.PREVIEW_BYTES))
check(mode == "L" and not exif, "preview: a gray page is saved gray, with no metadata (nothing is copied from the scan)")
check(ext[1] - ext[0] >= 200, "preview: readable, not blurred: the page keeps its full range of dark to white (%d..%d; the blurred contact sheet stays within 40)" % ext)
multi = os.path.join(pv, "0917002_W1.pdf")
open(multi, "wb").write(multi_page_pdf())
P.render_preview(multi, multi + ".jpg")
with Image.open(multi + ".jpg") as im:
    check(im.convert("L").resize((1, 1), Image.BOX).getpixel((0, 0)) > 200, "preview: page one only (page two is solid black, the preview is mostly white)")
col = os.path.join(pv, "0917003_Plat.pdf")
open(col, "wb").write(color_pdf())
P.render_preview(col, col + ".jpg")
check(jpeg_of(col + ".jpg")[1] == "RGB", "preview: a page with color in it (a stamp) stays in color")
tif = os.path.join(pv, "0917004_W1.tif")
open(tif, "wb").write(tall_tif())
n = P.render_preview(tif, tif + ".jpg")
fmt, mode, size, exif, ext = jpeg_of(tif + ".jpg")
check(fmt == "JPEG" and size[0] == 900 and mode == "L" and n <= P.PREVIEW_BYTES and ext[1] - ext[0] >= 200, "preview: a 300 dpi TIFF scan is shrunk to 900 px, gray and readable (%s, %d bytes)" % (size, n))
narrow = os.path.join(pv, "0917005_W1.tif")
open(narrow, "wb").write(tif_bytes())
P.render_preview(narrow, narrow + ".jpg")
check(jpeg_of(narrow + ".jpg")[2][0] == 850, "preview: a scan narrower than 900 px is not enlarged")

# a page that will not fit the cap is recompressed, then shrunk, and if nothing fits it is refused with no half-written file
rnd = random.Random(5)
busy = Image.new("L", (850, 1100), 255)
bp = busy.load()
for y in range(1100):
    for x in range(850):
        if rnd.random() < 0.12:
            bp[x, y] = rnd.randrange(0, 120)
bb = io.BytesIO()
busy.save(bb, "PDF", resolution=100)
bsrc = os.path.join(pv, "busy.pdf")
open(bsrc, "wb").write(bb.getvalue())
n = P.render_preview(bsrc, bsrc + ".jpg")
check(n <= P.PREVIEW_BYTES and jpeg_of(bsrc + ".jpg")[2][0] < 900, "preview: a busy page is recompressed (and narrowed if it must be) until it fits: %d bytes at %d px" % (n, jpeg_of(bsrc + ".jpg")[2][0]))
os.remove(bsrc + ".jpg")
real_cap = P.PREVIEW_BYTES
P.PREVIEW_BYTES = 3000
try:
    P.render_preview(bsrc, bsrc + ".jpg")
    check(False, "preview: a page that fits no size raises")
except ValueError:
    check(not os.path.exists(bsrc + ".jpg"), "preview: a page that fits no size is refused and leaves no file")
P.PREVIEW_BYTES = real_cap

# a damaged file raises and leaves nothing
broken = os.path.join(pv, "0917006_W1.pdf")
open(broken, "wb").write(b"%PDF-1.4 this is not a pdf")
try:
    P.render_preview(broken, broken + ".jpg")
    check(False, "preview: a damaged PDF raises")
except Exception:  # noqa: BLE001
    check(not os.path.exists(broken + ".jpg"), "preview: a damaged PDF raises and leaves no file")
hang = os.path.join(pv, "0917007_W1.pdf")
open(hang, "wb").write(pdf_bytes())
real_run = P.subprocess.run
seen_env = {}


def slow_run(cmd, **kw):
    seen_env.update(kw)
    raise P.subprocess.TimeoutExpired(cmd, kw.get("timeout"))


P.subprocess.run = slow_run
os.environ["GH_TOKEN"] = "secret-token"
try:
    P.render_preview(hang, hang + ".jpg")
    check(False, "preview: a render that hangs raises")
except P.subprocess.TimeoutExpired:
    check(seen_env.get("timeout") == P.PER_FILE_SECONDS and "GH_TOKEN" not in seen_env["env"] and not os.path.exists(hang + ".jpg"),
          "preview: pdftoppm runs under a %d s timeout without the repository token, and a hang leaves no file" % P.PER_FILE_SECONDS)
finally:
    P.subprocess.run = real_run
    del os.environ["GH_TOKEN"]

# staging: each staged document gets its preview beside it, and one that cannot be drawn costs nothing but itself
def make_w1_pv(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("2026-10-29\\06\\0917001_W1_letter.pdf", pdf_bytes(w=1100, h=850))
        z.writestr("2026-10-29\\06\\0917001_Plat_a.pdf", pdf_bytes())
        z.writestr("2026-10-29\\06\\0917001_Plat_b.pdf", color_pdf())
        z.writestr("2026-10-29\\06\\0917002_W1_letter.tif", tall_tif())
        z.writestr("2026-10-29\\06\\0917003_W1_letter.pdf", b"%PDF-1.4 this is not a pdf")  # staged (it starts like a PDF) but no page can be drawn
        z.writestr("2026-10-29\\06\\0917004_Other_cover.pdf", pdf_bytes())  # not a W-1 or a plat: never staged


w1pv = os.path.join(tmp, "w1pv.zip")
make_w1_pv(w1pv)
st_plain = os.path.join(tmp, "stage-plain")
res = P.stage_pack(w1pv, "w1images", st_plain, logs.append)
check("previews" not in res and sorted(os.listdir(st_plain)) == ["0917001_Plat_1.pdf", "0917001_Plat_2.pdf", "0917001_W1.pdf", "0917002_W1.tif", "0917003_W1.pdf"],
      "stage_pack without previews: the same files as before and no preview, no 'previews' key: %s" % sorted(os.listdir(st_plain)))
logs2 = []
st_pv = os.path.join(tmp, "stage-pv")
res = P.stage_pack(w1pv, "w1images", st_pv, logs2.append, previews=True)
want = ["0917001_Plat_1.pdf.jpg", "0917001_Plat_2.pdf.jpg", "0917001_W1.pdf.jpg", "0917002_W1.tif.jpg"]
check(res["previews"] == want and sorted(f for f in os.listdir(st_pv) if f.endswith(".jpg")) == want and sorted(res["permits"]) == ["0917001", "0917002", "0917003"],
      "stage_pack with previews: each readable document has <document>.jpg beside it, the damaged one has none and is still staged: %s" % res["previews"])
check(all(os.path.exists(os.path.join(st_pv, n[:-4])) for n in res["previews"]), "stage_pack with previews: every preview sits beside its document")
check(any("previews: 4 of 5 documents drawn, 1 failed" in m for m in logs2) and not any(".pdf" in m or "0917" in m for m in logs2 if m.startswith("previews")),
      "stage_pack with previews: one log line says 4 of 5 drawn and 1 failed, and names no file: %s" % [m for m in logs2 if m.startswith("previews")])
with Image.open(os.path.join(st_pv, "0917001_Plat_2.pdf.jpg")) as im:
    check(im.mode == "RGB", "stage_pack with previews: a color plat keeps its color")
sv_stage = os.path.join(tmp, "stage-sv")
res = P.stage_pack(dirz, "dirsurveys", sv_stage, logs2.append, previews=True)
check(res["previews"] == ["dir_survey_990000.pdf.jpg", "dir_survey_990001.pdf.jpg", "dir_survey_990002.pdf.jpg", "dir_survey_990003.pdf.jpg"] and len(res["surveys"]) == 4,
      "stage_pack with previews: each directional survey has dir_survey_<id>.pdf.jpg: %s" % res["previews"])
check(P.stage_pack(comp, "complimages", os.path.join(tmp, "stage-comp"), previews=True) is None and not os.path.exists(os.path.join(tmp, "stage-comp")),
      "stage_pack: completion images are never staged, with or without previews")

# the tools missing, a tool that always fails, a spent budget: the documents are staged all the same
P.shutil.which = lambda name: None
logs3 = []
res = P.stage_pack(w1pv, "w1images", os.path.join(tmp, "stage-notool"), logs3.append, previews=True)
P.shutil.which = real_which
check(res["previews"] == [] and len(res["permits"]) == 3 and not [f for f in os.listdir(os.path.join(tmp, "stage-notool")) if f.endswith(".jpg")] and any("5 left out (pdftoppm" in m for m in logs3),
      "stage_pack with pdftoppm missing: the documents are staged, no previews, and the log says why")
calls = []
real_render = P.render_preview


def failing(src_, dest_):
    calls.append(src_)
    raise ValueError("no")


P.render_preview = failing
many = os.path.join(tmp, "many.zip")
with zipfile.ZipFile(many, "w") as z:
    for k in range(30):
        z.writestr("dir_survey_%d.pdf" % (100 + k), pdf_bytes())
logs4 = []
res = P.stage_pack(many, "dirsurveys", os.path.join(tmp, "stage-many"), logs4.append, previews=True)
P.render_preview = real_render
check(res["previews"] == [] and len(res["surveys"]) == 30 and len(calls) == P.PREVIEW_GIVE_UP and any("left out (%d previews in a row failed)" % P.PREVIEW_GIVE_UP in m for m in logs4),
      "stage_pack: after %d failures in a row the rest of the pack goes without previews (%d tried), the 30 surveys are staged" % (P.PREVIEW_GIVE_UP, len(calls)))
calls.clear()
P.render_preview = failing
res = P.stage_pack(many, "dirsurveys", os.path.join(tmp, "stage-late"), logs4.append, previews=True, deadline=time.time() - 1)
P.render_preview = real_render
check(res["previews"] == [] and not calls and len(res["surveys"]) == 30, "stage_pack: past the capture's deadline no preview is started and the documents are still staged")

# ------------------------------------------------------------------ the day report and the release
class FakeRelease:
    """d7_release.publish with GitHub's listing replaced: `have` is what the listing will hold besides the documents"""
    ReleaseError = d7.d7_release.ReleaseError

    def __init__(self, have_previews=None, fail=False):
        self.have, self.fail, self.args = have_previews, fail, None

    def publish(self, repo, day, folder, names, log=print, optional=(), confirmed=None):
        self.args = (repo, day, folder, list(names), list(optional))
        if self.fail:
            raise self.ReleaseError("gh release upload failed")
        if confirmed is not None:
            confirmed.extend(n for n in optional if self.have is None or n in self.have)
        return "daily-" + day.isoformat()


def attach(fake, w1_previews, sv_previews, rows=None):
    """attach_documents on a staged W-1 pack of two permits and a survey pack of two surveys"""
    real = (d7.d7_release.publish, d7.d7_release.ready)
    d7.d7_release.publish, d7.d7_release.ready = fake.publish, lambda: None
    try:
        stage = {"permits": {"0917001": [["W1.pdf", 10], ["Plat.pdf", 20]], "0917002": [["W1.tif", 30]]}}
        surv = {"surveys": [[None, None, "M", None, None, None, None, None, "55", 3], [None, None, "O", None, None, None, None, None, "56", 4]]}
        if w1_previews is not None:
            stage["previews"] = w1_previews
        if sv_previews is not None:
            surv["previews"] = sv_previews
        jobs = {"w1images": {"staged": stage}, "dirsurveys": {"staged": surv}}
        report = {"permits": {"rows": rows or [["0917001", "003", "06", "1", None, 100, "V", None, None, None], ["0917002", "003", "06", "1", None, 100, "V", None, None, None]]}}
        c = {"R": date(2026, 10, 30), "stage": os.path.join(tmp, "stage-x"), "lk": types.SimpleNamespace(locator=types.SimpleNamespace(locate=lambda apis: {}))}
        tag = d7.attach_documents(c, jobs, report, "o/r", lambda m: None)
        return tag, report
    finally:
        d7.d7_release.publish, d7.d7_release.ready = real


ALL_PV = ["0917001_W1.pdf.jpg", "0917001_Plat.pdf.jpg", "0917002_W1.tif.jpg"]
fk = FakeRelease()
tag, report = attach(fk, ALL_PV, ["dir_survey_55.pdf.jpg", "dir_survey_56.pdf.jpg"])
rel = report["release"]
check(tag == "daily-2026-10-30" and len(fk.args[3]) == 5 and fk.args[4] == [n + ".jpg" for n in fk.args[3]],
      "attach_documents: every document's preview goes up with it as an optional file of the same release (%d documents, %d previews)" % (len(fk.args[3]), len(fk.args[4])))
check(rel["files"] == 5 and rel["previews"] == 5 and "noPreview" not in rel, "attach_documents: the release block says how many previews the listing confirmed, and none are missing: %s" % rel)
fk = FakeRelease(have_previews={"0917001_W1.pdf.jpg", "dir_survey_55.pdf.jpg"})
tag, report = attach(fk, ALL_PV, ["dir_survey_55.pdf.jpg", "dir_survey_56.pdf.jpg"])
rel = report["release"]
check(rel["previews"] == 2 and rel["noPreview"] == ["0917001_Plat.pdf", "0917002_W1.tif", "dir_survey_56.pdf"] and rel["previews"] + len(rel["noPreview"]) == rel["files"],
      "attach_documents: only a preview the release listing confirmed counts; the documents without one are named: %s" % rel)
fk = FakeRelease()
tag, report = attach(fk, ["0917001_W1.pdf.jpg", "0917009_W1.pdf.jpg"], None)
check(fk.args[4] == ["0917001_W1.pdf.jpg"] and report["release"]["previews"] == 1 and len(report["release"]["noPreview"]) == 4,
      "attach_documents: a preview of a document that is not published (another permit's) is never uploaded: %s" % report["release"])
tag, report = attach(FakeRelease(have_previews=set()), ALL_PV, None)
check(tag and "previews" not in report["release"] and "noPreview" not in report["release"] and report["release"]["files"] == 5,
      "attach_documents: no preview confirmed means no preview keys at all, and the document links stand: %s" % report["release"])
tag, report = attach(FakeRelease(), None, None)
check(tag and "previews" not in report["release"] and len(report["permits"]["rows"][0]) == 11, "attach_documents: a day captured without previews (older days, tools missing) still links its documents")
tag, report = attach(FakeRelease(fail=True), ALL_PV, None)
check(tag is None and "release" not in report and len(report["permits"]["rows"][0]) == 10, "attach_documents: a release that fails gives no links and no previews, as before")

# the validator holds the release block's preview fields to the documents
docs_rep = dict(rep)
docs_rep.update({"permits": {"day": "2026-10-29", "total": 2, "newDrill": 2, "horizontal": 0, "rows": [
    ["0917001", "003", "06", "1", None, 100, "V", None, None, None, ["W1.pdf", "Plat.pdf"]], ["0917002", "003", "06", "1", None, 100, "V", None, None, None, ["W1.tif"]]]}})
docs_rep["release"] = {"repo": "o/r", "tag": "daily-2026-10-30", "files": 3, "bytes": 60, "permits": 2, "surveys": 0, "previews": 2, "noPreview": ["0917002_W1.tif"]}


def problems_for(release):
    r = dict(docs_rep, release=release)
    json.dump(r, open(os.path.join(out, "2026-10-30.json"), "w"))
    json.dump({"keep": 92, "days": [d7.headline(r)]}, open(os.path.join(out, "index.json"), "w"))
    return [p for p in d7.validate(out) if "release" in p or "preview" in p]


good = dict(docs_rep["release"])
check(problems_for(good) == [], "validate: a release block whose previews and missing previews add up to its files passes %r" % problems_for(good))
check(problems_for({k: v for k, v in good.items() if k not in ("previews", "noPreview")}) == [], "validate: a release block with no preview fields (an older day) passes")
check(any("preview" in p for p in problems_for(dict(good, previews=3))), "validate: previews that do not add up with the documents without one are reported")
check(any("preview" in p for p in problems_for(dict(good, noPreview=["../x"]))), "validate: a document name that is not a plain file name is reported")
check(any("preview" in p for p in problems_for(dict(good, previews=True))), "validate: previews that is not a count is reported")

# ------------------------------------------------------------------ d7_release.publish with optional files (gh replaced)
import subprocess  # noqa: E402

RELEASE = d7.d7_release


def gh_fake(state, fail_jpg=False, hide_jpg=False):
    def run(cmd, capture_output=True, text=True, timeout=None):
        sub = " ".join(cmd[1:3])
        if sub == "release view" and "tagName" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        if sub == "release upload":
            files = [os.path.basename(a) for a in cmd[7:]]  # gh release upload <tag> --repo <repo> --clobber <files...>
            state["batches"].append(files)
            if fail_jpg and any(f.endswith(".jpg") for f in files):
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502: Bad Gateway")
            state["have"].update(files)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if sub == "release view":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"assets": [{"name": n} for n in sorted(state["have"]) if not (hide_jpg and n.endswith(".jpg"))]}), "")
        return subprocess.CompletedProcess(cmd, 0, "[]", "")
    return run


def publish_with(state, optional, **kw):
    saved = (RELEASE.subprocess.run, RELEASE.time.sleep)
    RELEASE.subprocess.run, RELEASE.time.sleep = gh_fake(state, **kw), lambda s: None
    got = []
    try:
        tag = RELEASE.publish("o/r", date(2026, 10, 30), "/stage", ["a.pdf", "b.pdf"], lambda m: None, optional=optional, confirmed=got)
    finally:
        RELEASE.subprocess.run, RELEASE.time.sleep = saved
    return tag, got


state = {"batches": [], "have": set()}
tag, got = publish_with(state, ["b.pdf.jpg", "a.pdf.jpg"])
check(tag == "daily-2026-10-30" and got == ["a.pdf.jpg", "b.pdf.jpg"] and state["batches"] == [["a.pdf", "b.pdf"], ["a.pdf.jpg", "b.pdf.jpg"]],
      "publish: the documents are uploaded first, the previews after, and the one listing confirms both: %s" % state["batches"])
state = {"batches": [], "have": set()}
tag, got = publish_with(state, ["a.pdf.jpg"], fail_jpg=True)
check(tag == "daily-2026-10-30" and got == [] and {"a.pdf", "b.pdf"} <= state["have"], "publish: previews that cannot be uploaded cost nothing but themselves: the documents are confirmed (%s)" % got)
state = {"batches": [], "have": set()}
tag, got = publish_with(state, ["a.pdf.jpg"], hide_jpg=True)
check(tag and got == [], "publish: a preview missing from the listing is not reported as there")
state = {"batches": [], "have": set()}
saved_limit = RELEASE.ASSET_LIMIT
RELEASE.ASSET_LIMIT = 3
tag, got = publish_with(state, ["a.pdf.jpg", "b.pdf.jpg"])
RELEASE.ASSET_LIMIT = saved_limit
check(got == ["a.pdf.jpg"], "publish: the previews are cut back to what the release's asset limit leaves room for after the documents: %s" % got)
state = {"batches": [], "have": set()}
saved = (RELEASE.subprocess.run, RELEASE.time.sleep)
RELEASE.subprocess.run, RELEASE.time.sleep = gh_fake(state), lambda s: None
try:
    RELEASE.publish("o/r", date(2026, 10, 30), "/stage", ["a.pdf"], lambda m: None)
    check(state["batches"] == [["a.pdf"]], "publish: called as before (no optional files) it behaves as before")
finally:
    RELEASE.subprocess.run, RELEASE.time.sleep = saved

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
