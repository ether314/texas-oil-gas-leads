"""Tests for d7_completions.py, d7_packs.stage_completions and d7_release.publish_files / the completion releases' pruning: the readable page-one previews of
the Texas completion images (synthetic packs built with Pillow; needs Pillow and poppler's pdftoppm; gh and the Commission's share are faked, no network).

Run: python3 -I tests/test_d7_completions.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import io
import json
import os
import random
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import date

sys.path.insert(0, PIPE)
import d7_completions as C  # noqa: E402
import d7_packs as P  # noqa: E402
import d7_release as R  # noqa: E402
from PIL import Image  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def page(w=850, h=1100, shade=255):
    im = Image.new("RGB", (w, h), (shade, shade, shade))
    for i in range(0, h, 40):
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


def png_bytes():
    b = io.BytesIO()
    page(w=600, h=800).save(b, "PNG")
    return b.getvalue()


SECRETS = ["ODOM", "ERNEST SMITH", "Concho", "GRATTON", "Winston", "Rosewood"]  # words from file names that must reach no data file, name or log line


def make_pack(path, packets=((("09", 364021), 5), (("08", 364022), 3), (("7C", 364023), 2)), extra=True):
    """Packets as (district, tracking) -> number of document groups. Each group is a W-2 form, a G-1 form, a TIF plat, a log and an unplaced-kind attachment."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for (district, tracking), n in packets:
            base = "%s/trackingNo_%d_Images_Submitted/" % (district, tracking)
            for t in range(1, n + 1):
                z.writestr(base + "cmpl_W2Form_PID_%d.pdf" % t if t == 1 else base + "cmpl_W2Form_PID_%d_%d.pdf" % (tracking, t), pdf_bytes())
            z.writestr(base + "ODOM %dH - PLAT.TIF" % tracking, tif_bytes())
            z.writestr(base + "ERNEST SMITH A %dH - GAU.pdf" % tracking, pdf_bytes())
            z.writestr(base + "Concho 20%d misc notes.pdf" % tracking, pdf_bytes())
            z.writestr("%s/trackingNo_%d/cmpl_G1Form_PID_%d.pdf" % (district, tracking, tracking), pdf_bytes(shade=250))
        if extra:
            z.writestr("08/trackingNo_%d/Rosewood scan saved as a TIF.tif" % 364022, png_bytes())  # a PNG with a .tif name, as the real pack has
            z.writestr("09/trackingNo_364021_Images_Submitted/GRATTON.csv", b"a,b\n1,2\n")  # not a document
    return path


def docs_of(path):
    z = zipfile.ZipFile(path)
    return z, P.documents(z)


tmp = tempfile.mkdtemp(prefix="cm-test-")
pack = make_pack(os.path.join(tmp, "10-30-2026.zip"))
z, docs = docs_of(pack)

# ------------------------------------------------------------------ the layout: how documents are grouped and numbered
layout, unplaced = P.completion_layout(docs)
got = [(d, t) for d, t, _ in layout]
check(got == [("08", "364022"), ("09", "364021"), ("7C", "364023")], "layout: packets sorted by district, then tracking number: %s" % got)
check(unplaced == 0, "layout: every document sat in a folder this reads")
by = {(d, t): items for d, t, items in layout}
# 5 groups of 5 for packet 09/364021: 5 W-2 forms in the _Images_Submitted folder, a plat, a log, an attachment there, and a G-1 in the plain folder
check(len(by[("09", "364021")]) == 5 + 3 + 1 and [s for s, _, _ in by[("09", "364021")]] == [0] + [1] * 8, "layout: the plain folder's documents come first (state 0), then the submitted folder's (state 1): %s" % [s for s, _, _ in by[("09", "364021")]])
check(len(by[("08", "364022")]) == 3 + 3 + 1 + 1 and [(s_, e) for s_, _, e in by[("08", "364022")]][:2] == [(0, ".tif"), (0, ".pdf")], "layout: a PNG named .tif is a document like another: %d documents" % len(by[("08", "364022")]))
odd = zipfile.ZipFile(os.path.join(tmp, "odd.zip"), "w")
for name in ("09/trackingNo_5/a.pdf", "09/notatracking/b.pdf", "toplevel.pdf", "09/trackingNo_5_Images_Approved/c.pdf", "../x/trackingNo_5/d.pdf", "ABCD/trackingNo_5/e.pdf", "09/trackingNo_000001/f.pdf", "09/trackingNo_1234567890123/g.pdf"):
    odd.writestr(name, pdf_bytes())
odd.close()
oz, odocs = docs_of(os.path.join(tmp, "odd.zip"))
olay, ounp = P.completion_layout(odocs)
check([(d, t, len(i)) for d, t, i in olay] == [("09", "1", 1), ("09", "5", 1)] and ounp == 6, "layout: a folder that is not trackingNo_<digits> (or _Images_Submitted), a district that is not 1 to 3 letters or digits, a file at the top and a tracking number past 12 digits are counted and never published; leading zeros go: %s %d" % ([(d, t) for d, t, _ in olay], ounp))
# the order does not depend on the zip's
shuffled = docs[:]
random.Random(3).shuffle(shuffled)
check([(d, t, [i.filename for _, i, _ in items]) for d, t, items in P.completion_layout(shuffled)[0]] == [(d, t, [i.filename for _, i, _ in items]) for d, t, items in layout], "layout: numbering does not depend on the order of the zip")

# ------------------------------------------------------------------ stage_completions: what is drawn, how it is named, what fails
logs = []
out = os.path.join(tmp, "stage")
res = P.stage_completions(z, docs, out, logs.append)
names = sorted(os.listdir(out))
total = sum(len(items) for _, _, items in layout)
check(res["docs"] == total and len(res["drawn"]) == total and names == res["drawn"] and res["failed"] == 0 and res["left_out"] == 0 and res["stopped"] is None, "stage: every document is drawn, one picture each (%d): %s" % (total, {k: v for k, v in res.items() if k not in ("packets", "drawn")}))
import re as _re  # noqa: E402
check(all(_re.fullmatch(r"cm_[0-9A-Za-z]{1,3}_\d{1,12}_\d{1,3}\.jpg", n) for n in names), "stage: every name is made up (cm_<district>_<tracking>_<n>.jpg): %s" % names[:3])
blob = " ".join(names) + " " + " ".join(logs) + json.dumps(res["packets"])
check(not any(w.lower() in blob.lower() for w in SECRETS), "stage: nothing from the pack's own file names reaches the names, the log or the rows")
check(all(os.path.getsize(os.path.join(out, n)) <= P.CM_PREVIEW_BYTES for n in names) and all(Image.open(os.path.join(out, n)).format == "JPEG" and Image.open(os.path.join(out, n)).width <= P.PREVIEW_W for n in names), "stage: every picture is a JPEG, at most %d px wide and %d bytes" % (P.PREVIEW_W, P.CM_PREVIEW_BYTES))
check(all(set(Image.open(os.path.join(out, n)).getexif().keys()) == set() for n in names), "stage: no metadata is copied from the scans")
rows = {(d, t): r for d, t, r in res["packets"]}
check(all(len(r) == len(by[k]) for k, r in rows.items()) and all(row[2] == 1 and 0 <= row[0] < len(P.CM_KINDS) and row[1] in (0, 1) for r in rows.values() for row in r), "stage: each packet's rows are [kind index, folder, 1] and as many as it has documents")
kinds = [P.CM_KINDS[row[0]] for row in rows[("09", "364021")]]
check(kinds[0] == "G-1 form" and kinds.count("W-2 form") == 5 and "Plat" in kinds and "Well log" in kinds and "Other attachment" in kinds, "stage: kinds are told by file name pattern: %s" % kinds)
check(len(logs) == 1 and logs[0].startswith("completion previews: %d of %d documents drawn" % (total, total)), "stage: one log line, with counts only: %s" % logs)
check(not os.path.exists(os.path.join(out, "x")) and set(os.listdir(os.path.dirname(out))) >= {"stage"}, "stage: nothing but pictures in the folder")
# a staging folder holds no source file after the run (the page files are removed as they are drawn)
check(all(n.endswith(".jpg") for n in os.listdir(out)), "stage: no source document is left in the folder")

# bad members and failures
bad = zipfile.ZipFile(os.path.join(tmp, "bad.zip"), "w")
bad.writestr("09/trackingNo_1/a.pdf", b"this is not a pdf at all")
bad.writestr("09/trackingNo_1/b.pdf", pdf_bytes())
bad.writestr("09/trackingNo_1/c.pdf", b"%PDF-1.4 truncated nonsense")
bad.writestr("09/trackingNo_1/d.tif", b"II*\x00garbage")
bad.close()
bz, bdocs = docs_of(os.path.join(tmp, "bad.zip"))
logs = []
r = P.stage_completions(bz, bdocs, os.path.join(tmp, "stage_bad"), logs.append)
check(r["docs"] == 4 and len(r["drawn"]) == 1 and r["failed"] == 3 and [row[2] for row in r["packets"][0][2]] == [0, 1, 0, 0], "stage: a file that is not what its name says, a truncated PDF and a broken TIFF have no preview and are counted, the rest is drawn: %s" % {k: v for k, v in r.items() if k != "packets"})
check("NotADocument" in logs[0] and len(os.listdir(os.path.join(tmp, "stage_bad"))) == 1, "stage: the log says what kind of failure and the failed ones leave no half-written file: %s" % logs)

big = zipfile.ZipFile(os.path.join(tmp, "big.zip"), "w")
big.writestr("09/trackingNo_1/a.pdf", pdf_bytes())
big.close()
bgz, bgdocs = docs_of(os.path.join(tmp, "big.zip"))
saved_max = P.MAX_ASSET
P.MAX_ASSET = 100
r = P.stage_completions(bgz, bgdocs, os.path.join(tmp, "stage_big"), lambda m: None)
P.MAX_ASSET = saved_max
check(r["docs"] == 1 and r["drawn"] == [] and r["failed"] == 1, "stage: a document past the size cap has no preview, and is counted")

# a broken tool: the run gives up after PREVIEW_GIVE_UP failures in a row instead of failing every document
many = zipfile.ZipFile(os.path.join(tmp, "many.zip"), "w")
for i in range(40):
    many.writestr("09/trackingNo_%d/a.pdf" % (100 + i), pdf_bytes())
many.close()
mz, mdocs = docs_of(os.path.join(tmp, "many.zip"))
real_render = P.render_preview


def broken(src, dest, max_bytes=None):
    raise RuntimeError("pdftoppm crashed")


P.render_preview = broken
logs = []
r = P.stage_completions(mz, mdocs, os.path.join(tmp, "stage_many"), logs.append, workers=1)
P.render_preview = real_render
check(r["drawn"] == [] and r["stopped"] == "%d previews in a row failed" % P.PREVIEW_GIVE_UP and r["failed"] >= P.PREVIEW_GIVE_UP and r["failed"] + r["left_out"] == 40 and r["left_out"] > 0, "stage: after %d failures in a row it stops (%d failed, %d left out)" % (P.PREVIEW_GIVE_UP, r["failed"], r["left_out"]))
check("RuntimeError x" in logs[0] and "left out" in logs[0], "stage: and the log says so: %s" % logs)

# the time budget
logs = []
r = P.stage_completions(mz, mdocs, os.path.join(tmp, "stage_late"), logs.append, seconds=-1)
check(r["drawn"] == [] and r["left_out"] == 40 and r["stopped"] == "the time budget ran out" and all(row[2] == 0 for _, _, rows_ in r["packets"] for row in rows_), "stage: a spent budget draws nothing, and every document is listed with no preview")
r = P.stage_completions(mz, mdocs, os.path.join(tmp, "stage_dl"), lambda m: None, deadline=time.time() - 5)
check(r["drawn"] == [] and r["left_out"] == 40, "stage: so does a capture deadline that has passed")

# tools missing
saved_tools = P.preview_tools
P.preview_tools = lambda: "pdftoppm (poppler-utils) is not installed"
try:
    P.stage_completions(mz, mdocs, os.path.join(tmp, "stage_none"), lambda m: None)
    check(False, "stage: missing tools raise ToolsMissing")
except P.ToolsMissing:
    check(True, "stage: missing tools raise ToolsMissing (the caller says so and publishes nothing)")
P.preview_tools = saved_tools
check(P.completion_name("7C", "364023", 12) == "cm_7C_364023_12.jpg", "the name of a preview is made from district, tracking number and place in the packet")
check(len(P.CM_KINDS) == 12 and set(P.kind_comp(b) for b in ["cmpl_W2Form_x.pdf", "cmpl_G1Form_x.pdf", "cmpl_L1Form_x.pdf", "cmpl_P4Form_x.pdf", "cmpl_G5Form_x.pdf", "a plat.pdf", "a log.pdf", "W-15.pdf", "P-16.pdf", "survey.pdf", "W-12.pdf", "misc.pdf"]) == set(P.CM_KINDS), "every label kind_comp returns is in CM_KINDS, and the other way round (the file stores an index into it)")

# ------------------------------------------------------------------ the day's file
packets = [["08", "364022", [[0, 0, 1], [1, 1, 1], [2, 1, 0]]], ["09", "364021", [[0, 0, 1], [11, 1, 1]]], ["7C", "364023", [[5, 1, 1]]]]
confirmed = {"cm_08_364022_1.jpg", "cm_08_364022_2.jpg", "cm_09_364021_1.jpg", "cm_09_364021_2.jpg", "cm_7C_364023_1.jpg"}
doc = C.make_doc("2026-10-31", "2026-10-30", "o/r", packets, confirmed, built="2026-11-01T03:30Z")
check(C.problems_of(doc, "2026-10-31") == [] and doc["docs"] == 6 and doc["previews"] == 5 and doc["parts"] == 1 and doc["per"] == 800 and doc["kinds"] == P.CM_KINDS, "file: a good day's file passes: %s" % C.problems_of(doc, "2026-10-31")[:2])
check(C.make_doc("2026-10-31", "2026-10-30", "o/r", packets, {"cm_08_364022_1.jpg"})["previews"] == 1, "file: a row is marked only when its preview is confirmed on the release, not because it was drawn")
check(C.make_doc("2026-10-31", "2026-10-30", "o/r", [["08", "1", [[0, 0, 1]]]], {"cm_08_1_1.jpg"})["packets"][0][2] == [[0, 0, 1]], "file: ... and a drawn, confirmed one is marked 1")


def broken_doc(**change):
    d = json.loads(json.dumps(doc))
    for k, v in change.items():
        d[k] = v
    return d


for label, d in [
    ("a wrong day", broken_doc(day="2026-10-30")), ("v 2", broken_doc(v=2)), ("a repo with a space", broken_doc(repo="o r")), ("a counts mismatch (docs)", broken_doc(docs=7)),
    ("a counts mismatch (previews)", broken_doc(previews=6)), ("parts that do not fit", broken_doc(parts=3)), ("an unexpected key", broken_doc(extra=1)), ("no packets", broken_doc(packets=[])),
    ("a kind index past the kinds", broken_doc(packets=[["08", "1", [[99, 0, 1]]]], docs=1, previews=1, parts=1)), ("a district that is a path", broken_doc(packets=[["../x", "1", [[0, 0, 1]]]], docs=1, previews=1, parts=1)),
    ("a tracking number that is text", broken_doc(packets=[["08", "ODOM", [[0, 0, 1]]]], docs=1, previews=1, parts=1)), ("a document that is not three numbers", broken_doc(packets=[["08", "1", [[0, 0]]]], docs=1, previews=1, parts=1)),
    ("fewer than half with a preview", broken_doc(packets=[["08", "1", [[0, 0, 1], [0, 0, 0], [0, 0, 0]]]], docs=3, previews=1, parts=1)), ("a per past 1000", broken_doc(per=2000)),
    ("a built time that is not a time", broken_doc(builtAt="yesterday")), ("kinds that are not texts", broken_doc(kinds=[1, 2])),
]:
    check(C.problems_of(d, "2026-10-31") != [], "file: refused for %s" % label)
check(C.problems_of("not an object") != [] and C.problems_of(None) != [], "file: anything that is not an object is refused")
big_packets = [["08", str(i), [[0, 0, 1]] * 7] for i in range(1, 160)]
bigdoc = C.make_doc("2026-10-31", "2026-10-30", "o/r", big_packets, {C.P.completion_name("08", str(i), s) for i in range(1, 160) for s in range(1, 8)})
check(bigdoc["docs"] == 159 * 7 and bigdoc["parts"] == 2 and C.problems_of(bigdoc, "2026-10-31") == [], "file: %d documents need two releases" % bigdoc["docs"])
marked = [[d, t, [[k, s_, 1] for k, s_, _ in rows_]] for d, t, rows_ in big_packets]
named = C.doc_names(marked)
check([p_ for _, p_ in named][:2] == [1, 1] and named[-1][1] == 2 and named[799][1] == 1 and named[800][1] == 2, "parts: documents 1 to 800 go on the first release, the rest on the second")
holey = [["08", "1", [[0, 0, 1], [0, 0, 0], [0, 0, 1]]]]
check(C.doc_names(holey) == [("cm_08_1_1.jpg", 1), ("cm_08_1_3.jpg", 1)], "parts: a document without a preview keeps its number and its place")
saved_per = C.PER_RELEASE
C.PER_RELEASE = 2
check(C.doc_names(holey) == [("cm_08_1_1.jpg", 1), ("cm_08_1_3.jpg", 2)], "parts: ... so the release a document is on never depends on which others have previews (the page counts the same way)")
C.PER_RELEASE = saved_per

# ------------------------------------------------------------------ choosing the day
daily = os.path.join(tmp, "daily")
os.makedirs(daily)


def write(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


write(os.path.join(daily, "index.json"), {"days": [{"d": "2026-10-29", "k": "recon"}, {"d": "2026-10-30", "k": "live"}, {"d": "2026-10-31", "k": "live"}, {"d": "2026-11-01", "k": "live"}]})
write(os.path.join(daily, "2026-10-30.json"), {"images": {"complimages": {"day": "2026-10-29", "bytes": 300_000_000}}})
write(os.path.join(daily, "2026-10-31.json"), {"images": {"complimages": {"day": "2026-10-30", "bytes": 468_514_243}}})
write(os.path.join(daily, "2026-11-01.json"), {"images": {"complimages": {"day": "2026-10-31", "bytes": 100, "empty": True}}})
cout = os.path.join(tmp, "cm")
check(C.candidates(daily) == [("2026-10-31", "2026-10-30", 468514243), ("2026-10-30", "2026-10-29", 300000000)], "pick: the live days with a pack that was not listed empty, newest first: %s" % C.candidates(daily))
check(C.pick(daily, cout) == ("2026-10-31", "2026-10-30", 468514243), "pick: the newest one that has no file yet")
os.makedirs(cout)
write(os.path.join(cout, "2026-10-31.json"), {})
check(C.pick(daily, cout) is None, "pick: nothing to do when the newest has its file (a night is not done twice)")
check(C.pick(daily, cout, "2026-10-30") == ("2026-10-30", "2026-10-29", 300000000) and C.pick(daily, cout, "2026-10-29") is None, "pick: --day names a day, and only a live day with a pack counts")
check(C.pick(os.path.join(tmp, "nowhere"), cout) is None, "pick: no archive, nothing to do")
check(C.pack_name("2026-10-30") == "10-30-2026.zip" and C.pack_name("2026-01-05") == "01-05-2026.zip", "the pack of a day is the Commission's MM-DD-YYYY.zip")
shutil.rmtree(cout)

# ------------------------------------------------------------------ the folder's check, its index and its pruning
out2 = os.path.join(tmp, "cm2")
check(C.check(out2) == [], "check: a folder that does not exist yet is fine")
os.makedirs(out2)
C.write_index(out2)
check(C.check(out2) == [] and json.load(open(os.path.join(out2, "index.json"))) == {"v": 1, "days": []}, "check: an empty folder with its empty index is fine")
for day in ("2026-09-01", "2026-10-31"):
    write(os.path.join(out2, day + ".json"), C.make_doc(day, day, "o/r", packets, confirmed, built="2026-11-01T03:30Z"))
check(any("index.json" in p for p in C.check(out2)), "check: an index that does not list the days that have files is refused")
C.write_index(out2)
check(C.check(out2) == [] and json.load(open(os.path.join(out2, "index.json")))["days"] == ["2026-09-01", "2026-10-31"], "check: the index lists exactly the days with a file")
write(os.path.join(out2, "notes.txt"), {})
check(any("notes.txt" in p for p in C.check(out2)), "check: a stray file is refused")
os.remove(os.path.join(out2, "notes.txt"))
write(os.path.join(out2, "2026-10-30.json"), {"v": 1})
check(any("2026-10-30.json" in p for p in C.check(out2)), "check: a day's file that is not valid is refused")
os.remove(os.path.join(out2, "2026-10-30.json"))
gone = C.prune_files(out2, "2026-10-31")
C.write_index(out2)
check(gone == ["2026-09-01"] and C.day_files(out2) == ["2026-10-31"] and C.check(out2) == [], "prune: files more than %d days before the newest day go, the index follows: %s" % (C.KEEP_DAYS, gone))
write(os.path.join(out2, "2026-10-01.json"), C.make_doc("2026-10-01", "2026-10-01", "o/r", packets, confirmed))
check(C.prune_files(out2, "2026-10-31") == [] and C.day_files(out2) == ["2026-10-01", "2026-10-31"], "prune: a day exactly %d days back stays" % C.KEEP_DAYS)
write(os.path.join(out2, "2026-10-01.json"), {"v": 1})  # bad now
for d in ("2026-10-01",):
    os.remove(os.path.join(out2, d + ".json"))

# ------------------------------------------------------------------ the releases (gh replaced): upload, listing, pruning


class FakeGh:
    """A tiny GitHub: releases by tag, each a set of file names."""

    def __init__(self, fail_upload_on=None, hide=()):
        self.releases, self.calls, self.fail_upload_on, self.hide = {}, [], fail_upload_on, set(hide)

    def __call__(self, args, timeout=300, retry=True):
        self.calls.append(args[:2])
        sub = " ".join(args[:2])
        tag = args[2] if len(args) > 2 else None
        if sub == "release view" and "tagName" in args:
            if tag not in self.releases:
                raise R.ReleaseError("release not found")
            return "{}"
        if sub == "release create":
            self.releases[tag] = set()
            return ""
        if sub == "release upload":
            files = [os.path.basename(a) for a in args[args.index("--clobber") + 1:]]
            if self.fail_upload_on and tag.endswith(self.fail_upload_on):
                raise R.ReleaseError("gh release upload failed: HTTP 502")
            self.releases[tag] |= set(files)
            return ""
        if sub == "release view":
            return json.dumps({"assets": [{"name": n} for n in sorted(self.releases[tag] - self.hide)]})
        if sub == "release list":
            return json.dumps([{"tagName": t} for t in sorted(self.releases)])
        if sub == "release delete":
            del self.releases[tag]
            return ""
        raise AssertionError(args)


real_gh = R._gh
gh = FakeGh()
R._gh = gh
names40 = ["cm_08_%d_1.jpg" % i for i in range(100)]
got = R.publish_files("o/r", "daily-2026-10-31-cm1", "t", "n", "/stage", names40, lambda m: None)
check(got == sorted(names40) and gh.calls[:2] == [["release", "view"], ["release", "create"]] and gh.calls.count(["release", "upload"]) == 3, "release: a missing release is created and the files go up in batches of %d: %d calls" % (R.BATCH, gh.calls.count(["release", "upload"])))
gh.calls.clear()
R.publish_files("o/r", "daily-2026-10-31-cm1", "t", "n", "/stage", names40[:5], lambda m: None)
check(["release", "create"] not in gh.calls, "release: an existing release is not created again (a retry of a night re-uploads with --clobber)")
gh = FakeGh(hide=["cm_08_1_1.jpg"])
R._gh = gh
got = R.publish_files("o/r", "daily-2026-10-31-cm1", "t", "n", "/stage", ["cm_08_1_1.jpg", "cm_08_2_1.jpg"], lambda m: None)
check(got == ["cm_08_2_1.jpg"], "release: a file the listing does not show is not reported as there")
gh = FakeGh(fail_upload_on="cm2")
R._gh = gh
logs = []
got = R.publish_files("o/r", "daily-2026-10-31-cm2", "t", "n", "/stage", names40, logs.append)
check(got == [] and any("uploading stopped" in m for m in logs), "release: a failing upload stops the rest and the confirmed list says nothing is there: %s" % logs[-2:])

# upload() spreads a day over its releases
gh = FakeGh()
R._gh = gh
big_names = [(P.completion_name("08", str(i), s), 1 if (i - 1) * 7 + s <= 800 else 2) for i in range(1, 160) for s in range(1, 8)]
big_names = [(n, 1 if idx < 800 else 2) for idx, (n, _) in enumerate(big_names)]
conf = C.upload("o/r", "2026-10-31", "/stage", big_names, lambda m: None)
check(sorted(gh.releases) == ["daily-2026-10-31-cm1", "daily-2026-10-31-cm2"] and len(gh.releases["daily-2026-10-31-cm1"]) == 800 and len(gh.releases["daily-2026-10-31-cm2"]) == len(big_names) - 800 and len(conf) == len(big_names), "upload: a day's previews go to daily-<day>-cm1, -cm2: %s" % {k: len(v) for k, v in gh.releases.items()})
# pruning
gh = FakeGh()
gh.releases = {t: set() for t in ["daily-2026-07-01", "daily-2026-10-30", "daily-2026-09-01-cm1", "daily-2026-09-01-cm2", "daily-2026-10-20-cm1", "daily-2026-10-31-cm1", "v1.0", "daily-2026-09-01-extra", "other-2026-01-01-cm1"]}
R._gh = gh
gone = R.prune("o/r", date.min, lambda m: None, cm_oldest_kept=date(2026, 10, 1))
check(gone == ["daily-2026-09-01-cm1", "daily-2026-09-01-cm2"] and "daily-2026-07-01" in gh.releases, "prune: completion releases older than their own cut-off go, and the day releases are not touched when only that cut-off is given: %s" % gone)
gone = R.prune("o/r", date(2026, 8, 1), lambda m: None)
check(gone == ["daily-2026-07-01"] and set(gh.releases) == {"daily-2026-10-30", "daily-2026-10-20-cm1", "daily-2026-10-31-cm1", "v1.0", "daily-2026-09-01-extra", "other-2026-01-01-cm1"}, "prune: as before, without a completion cut-off the same day cuts both kinds, and no other tag is ever touched: %s" % gone)
check(R.cm_tag_for(date(2026, 10, 31), 2) == "daily-2026-10-31-cm2", "the tag of a day's second release")
R._gh = real_gh

# ------------------------------------------------------------------ the whole run (the share and gh replaced)


class Args:
    def __init__(self, **kw):
        self.daily, self.out, self.day, self.repo, self.time_limit = daily, os.path.join(tmp, "run_out"), None, "o/r", 14
        self.dl, self.zip, self.no_upload = os.path.join(tmp, "dl"), None, False
        self.__dict__.update(kw)


os.makedirs(os.path.join(tmp, "dl"), exist_ok=True)
msgs = []
real_log, C.log = C.log, msgs.append
real_dl, real_ready, real_repo_name = C.download_pack, R.ready, R.repo_name
asked = []


def fake_download(pack_day, expect_bytes, dest_dir, deadline):
    asked.append((pack_day, expect_bytes))
    os.makedirs(dest_dir, exist_ok=True)
    return shutil.copy(pack, os.path.join(dest_dir, C.pack_name(pack_day)))


C.download_pack = fake_download
R.ready = lambda: None
gh = FakeGh()
R._gh = gh
a = Args()
code = C.run(a)
f = os.path.join(a.out, "2026-10-31.json")
d = json.load(open(f)) if os.path.exists(f) else {}
check(code == 0 and asked == [("2026-10-30", 468514243)] and d.get("docs") == total and d.get("previews") == total and C.check(a.out) == [], "run: the newest day without a file is downloaded, drawn, uploaded and written: %s" % msgs[-2:])
check(sorted(gh.releases) == ["daily-2026-10-31-cm1"] and len(gh.releases["daily-2026-10-31-cm1"]) == total, "run: the previews are on the day's release (%d)" % total)
check(json.load(open(os.path.join(a.out, "index.json"))) == {"v": 1, "days": ["2026-10-31"]}, "run: the index lists the day")
text = open(f).read() + " ".join(msgs) + " ".join(gh.releases["daily-2026-10-31-cm1"])
check(not any(w.lower() in text.lower() for w in SECRETS), "run: nothing from the pack's file names reaches the file, the log or the release's file names")
check(not [x for x in os.listdir(a.dl)] or all(not x.startswith("cm-") for x in os.listdir(a.dl)), "run: the download and the pictures are removed when the run ends: %s" % os.listdir(a.dl))
msgs.clear()
asked.clear()
code = C.run(a)
check(code == 0 and asked == [] and any("nothing to do" in m for m in msgs), "run: a second run the same night finds the day done and downloads nothing")

# failures leave nothing behind
for label, setup in [
    ("the share refusing", lambda: setattr(C, "download_pack", lambda *a_, **k: (_ for _ in ()).throw(rrc_error()))),
    ("a pack that is not a zip", lambda: setattr(C, "download_pack", lambda pd, eb, dd, dl: (os.makedirs(dd, exist_ok=True), open(os.path.join(dd, "x.zip"), "wb").write(b"nope"), os.path.join(dd, "x.zip"))[2])),
]:
    import rrc_share  # noqa: E402

    def rrc_error():
        return rrc_share.ShareError("share: HTTP 403 for https://example.invalid/x")
    C.download_pack = fake_download
    setup()
    a = Args(out=os.path.join(tmp, "fail_out"))
    msgs.clear()
    gh = FakeGh()
    R._gh = gh
    code = C.run(a)
    check(code == 1 and not os.path.exists(os.path.join(a.out, "2026-10-31.json")) and any("FAILED" in m for m in msgs) and not any("example.invalid" in m for m in msgs), "run: %s fails the run, writes no file, and the log has no web address: %s" % (label, msgs[-1:]))
C.download_pack = fake_download

# half the uploads lost: nothing is written, so the day is tried again
gh = FakeGh(hide=["cm_08_364022_%d.jpg" % i for i in range(1, 8)] + ["cm_09_364021_%d.jpg" % i for i in range(1, 10)])
R._gh = gh
a = Args(out=os.path.join(tmp, "half_out"))
msgs.clear()
code = C.run(a)
check(code == 1 and not os.path.exists(os.path.join(a.out, "2026-10-31.json")) and any("not fit to publish" in m and "fewer than 50%" in m for m in msgs), "run: a night on which fewer than half the previews are on the release writes no file and fails: %s" % msgs[-1:])
# a few lost: written, and the rows say which
gh = FakeGh(hide=["cm_08_364022_1.jpg", "cm_7C_364023_1.jpg"])
R._gh = gh
a = Args(out=os.path.join(tmp, "few_out"))
code = C.run(a)
d = json.load(open(os.path.join(a.out, "2026-10-31.json")))
check(code == 0 and d["previews"] == total - 2 and d["docs"] == total and [r for p in d["packets"] if p[0] == "08" and p[1] == "364022" for r in p[2]][0][2] == 0, "run: a few previews the listing does not confirm are written as having none (%d of %d)" % (d["previews"], d["docs"]))

# the tools missing, the gh missing, a pack with no documents
real_tools = P.preview_tools
P.preview_tools = lambda: "Pillow is not installed"
a = Args(out=os.path.join(tmp, "t_out"))
msgs.clear()
check(C.run(a) == 1 and any("cannot draw" in m for m in msgs) and not os.path.exists(a.out), "run: no Pillow or pdftoppm fails the run and writes nothing")
P.preview_tools = real_tools
R.ready = lambda: "no GH_TOKEN"
msgs.clear()
check(C.run(a) == 1 and any("cannot publish (no GH_TOKEN)" in m for m in msgs) and not os.path.exists(a.out), "run: no gh token fails the run and writes nothing")
R.ready = lambda: None
empty = zipfile.ZipFile(os.path.join(tmp, "empty.zip"), "w")
empty.writestr("readme.txt", "no documents")
empty.close()
C.download_pack = lambda pd, eb, dd, dl: (os.makedirs(dd, exist_ok=True), shutil.copy(os.path.join(tmp, "empty.zip"), os.path.join(dd, "e.zip")))[1]
msgs.clear()
check(C.run(a) == 1 and any("holds no documents" in m for m in msgs) and not os.path.exists(a.out), "run: a pack with no documents is not published as a day with none")
C.download_pack = fake_download

# testing options: --zip and --no-upload never publish
gh = FakeGh()
R._gh = gh
a = Args(out=os.path.join(tmp, "dry_out"), zip=pack, no_upload=True, day="2026-10-31")
check(C.run(a) == 0 and gh.calls == [] and json.load(open(os.path.join(a.out, "2026-10-31.json")))["previews"] == total, "run: --no-upload with --zip draws and writes the file and calls no gh")
try:
    C.main(["--zip", pack])
    check(False, "main: --zip needs --no-upload")
except SystemExit as e:
    check("no-upload" in str(e.code) or "scratch" in str(e.code), "main: --zip alone is refused")
try:
    C.main(["--no-upload"])
    check(False, "main: --no-upload with the real folder is refused")
except SystemExit as e:
    check("scratch folder" in str(e.code), "main: --no-upload is refused with the real output folder")
check(C.main(["--check", "--out", out2]) == 0 and C.main(["--check", "--out", os.path.join(tmp, "nope")]) == 0, "main: --check passes clean folders")
write(os.path.join(out2, "2026-10-29.json"), {"v": 3})
check(C.main(["--check", "--out", out2]) == 1, "main: --check fails a bad one (the workflow then drops the folder's changes)")

# ------------------------------------------------------------------ the committed folder
check(C.check() == [], "the committed daily-cm folder passes its own check: %s" % C.check()[:2])
check(P.CM_MAGIC[".tif"] == P.MAGIC[".tif"] + (b"\x89PNG",) and P.MAGIC[".tif"] == (b"II*\x00", b"MM\x00*"), "PNG content is accepted under a .tif name for completions only: the W-1 and survey staging checks are unchanged")

C.log = real_log
C.download_pack, R.ready, R.repo_name, R._gh = real_dl, real_ready, real_repo_name, real_gh
shutil.rmtree(tmp, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
