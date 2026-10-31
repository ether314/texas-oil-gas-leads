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

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
