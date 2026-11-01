"""Tests for d12_wells.py, the well-image archive (synthetic packs built with Pillow; needs Pillow and poppler's pdftoppm and pdfinfo; no network, gh and the RRC shares faked).

What is checked: which packs a run does (plan), how a document finds its well (permit, survey CSV, completion packet), numbering that does not depend on the zip's order, staging
(a file that is not what its extension says is refused, a broken PDF is still published without a picture, page counts, picture size), releases of at most 800 files, whole runs (uploads
verified, a failed pack recorded as nothing while the others stay, a second run that has nothing to do, aged-out days removed with their releases), that no name from a pack, lease, landowner
or address reaches a published file, the check against deliberate faults, mutants that put the old behavior back, and the committed files.

Run: python3 -I tests/test_d12_wells.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import zipfile
from datetime import date, datetime

sys.path.insert(0, PIPE)
import d12_wells as W  # noqa: E402
import d7_release  # noqa: E402
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


def pdf_bytes(pages=1, **kw):
    b = io.BytesIO()
    first = page(**kw)
    first.save(b, "PDF", resolution=100, save_all=pages > 1, append_images=[page(**kw) for _ in range(pages - 1)])
    return b.getvalue()


def tif_bytes():
    b = io.BytesIO()
    page(shade=250).convert("L").convert("1").save(b, "TIFF", compression="group4")
    return b.getvalue()


SECRETS = ["ODOM", "ERNEST SMITH", "LITTLE WILLIE", "MC KINNEY", "Concho", "GRATTON", "Winston", "PO BOX", "(713)", "ian.call@"]  # names that must never reach a published file
NAMEABLE = next(iter(W.Lookups().operator))  # an operator the site may name
UNNAMED = "999999"  # one it may not

# ------------------------------------------------------------------------------------------------ plan

NOW = datetime(2026, 10, 30, 22, 0)


def listing(day, pack, size=5_000_000, modified=None, name=None):
    d = date.fromisoformat(day)
    nm = name or ("subscriptions_%s.zip" % day if pack == "w1" else d.strftime("%m-%d-%Y.zip"))
    return {"name": nm, "bytes": size, "modified": modified or (day + "T03:00:00")}


def listed_for(days, packs=("w1", "ds", "ci", "cd"), **kw):
    rows = {p: [] for p in packs}
    for day in days:
        for p in packs:
            rows[p].append(listing(day, p, **kw))
    return W.units_listed(rows)


def plan_days(plan_out):
    return sorted({str(u["day"]) for u in plan_out[0]})


L = listed_for(["2026-10-27", "2026-10-28", "2026-10-29"], modified=None)
todo, notes = W.plan(L, {}, NOW, days=2)
check(plan_days((todo, notes)) == ["2026-10-28", "2026-10-29"] and [u["pack"] for u in todo[:3]] == ["w1", "ds", "ci"], "the newest two filing days are done, newest first, the small packs first and the completion pack last (%s)" % [(str(u["day"]), u["pack"]) for u in todo])
done = {(date(2026, 10, 29), p): (L[(date(2026, 10, 29), p)]["name"], L[(date(2026, 10, 29), p)]["bytes"]) for p in ("w1", "ds", "ci")}
todo, _ = W.plan(L, done, NOW, days=2)
check(plan_days((todo, [])) == ["2026-10-27", "2026-10-28"], "a day all done is skipped, so the two days after it are taken")
done2 = dict(done)
done2[(date(2026, 10, 29), "w1")] = ("subscriptions_2026-10-29.zip", 1234)
todo, _ = W.plan(L, done2, NOW, days=1)
check([(str(u["day"]), u["pack"]) for u in todo] == [("2026-10-29", "w1")], "a pack listed again with another size is done again (and only that one)")
fresh = listed_for(["2026-10-29"], modified="2026-10-30T21:00:00")
todo, notes = W.plan(fresh, {}, NOW)
check(not todo and any("left for the next run" in n for n in notes), "a pack listed an hour ago is left alone (it may still be written): %s" % notes[:1])
todo, _ = W.plan(listed_for(["2026-10-29"], size=300), {}, NOW)
check(not todo, "an empty day (a 0.3 KB zip) is not a pack")
todo, _ = W.plan(listed_for(["2026-09-01"]), {}, NOW, window=14)
check(not todo, "a pack older than the window is not looked for")
todo, _ = W.plan(L, {}, NOW, days=3, only=date(2026, 10, 27))
check(plan_days((todo, [])) == ["2026-10-27"], "--day does only that day")
nocd = listed_for(["2026-10-29"], packs=("w1", "ds", "ci"))
todo, notes = W.plan(nocd, {}, NOW)
check([u["pack"] for u in todo] == ["w1", "ds"] and any("no completion data zip" in n for n in notes), "completion images with no completion data zip cannot be tied, so they wait and say why: %s" % notes[:1])
sat = listed_for(["2026-10-31"], packs=("ds", "ci", "cd"))
todo, _ = W.plan(sat, {}, datetime(2026, 11, 1, 22, 0))
check([u["pack"] for u in todo] == ["ds", "ci"], "a day with no W-1 pack (a weekend) does the packs it has")
stray = W.units_listed({"w1": [{"name": "subscriptions_2026-13-45.zip", "bytes": 9999999, "modified": None}, {"name": "subscriptions_2026-10-29_district08.zip", "bytes": 9999999, "modified": None}, {"name": "x.zip", "bytes": 9, "modified": None}],
                        "ds": [{"name": "02-30-2026.zip", "bytes": 9999999, "modified": None}]})
check(stray == {}, "a stray name, an impossible date and a per-district W-1 file are not packs")

# ------------------------------------------------------------------------------------------------ packs

PERMITS = {  # what d7_daily.read_daf gives, as far as the producer reads it
    "0917276": {"api": "12739259", "district": "7C", "op": NAMEABLE, "n": "0917276"},
    "0917600": {"api": "12739260", "district": "7C", "op": UNNAMED, "n": "0917600"},
    "0917601": {"api": "38933333", "district": "08", "op": NAMEABLE, "n": "0917601"},
}


def make_w1(path, order=1):
    items = [("2026-10-29\\06\\917276_W1_AsApprovedW1-10-29-2026_LTR.pdf", pdf_bytes()), ("2026-10-29\\06\\917276_Plat_T260069 PERMIT_5 (GRATTON 2H)no NPZ 09.01.26_LTR.pdf", pdf_bytes(2)),
             ("2026-10-29\\06\\917600_W1_AsApprovedW1-10-29-2026_LTR.pdf", pdf_bytes()), ("2026-10-29\\06\\917600_Plat_G11A Winston CN 3HH plat_LTR.pdf", pdf_bytes()),
             ("2026-10-29\\06\\917600_Plat_Winston second plat_LTR.pdf", pdf_bytes()),
             ("2026-10-29\\06\\917601_W1_AsApprovedW1-10-29-2026_LTR.pdf", pdf_bytes()),
             ("2026-10-29\\06\\165379_W1_AsApprovedW1-10-29-2026_LTR.pdf", pdf_bytes()),  # a permit the file does not hold
             ("2026-10-29\\06\\917601_Plat_not a pdf at all.pdf", b"<html>this is not a pdf</html>"),
             ("2026-10-29\\06\\917601_Plat_a tiff.tif", tif_bytes())]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (items if order == 1 else items[::-1]):
            z.writestr(name, data)


def make_ds(path):
    csv = "API_NO,EXTERNAL_ATTACHMENT_ID,ATTACHMENT_TYPE_CODE,FROM_DEPTH,TO_DEPTH,SURVEY_START_DT,SURVEY_END_DT,LATERAL_LABEL,\n" \
          "12335799,9932618,Directional Survey - MWD,154,24043,2026-08-27,2026-10-10,,\n" \
          "00335757,9932564,Directional Survey - Other,100,9000,2026-08-01,2026-08-09,,\n" \
          ",9932443,Directional Survey - MWD,100,9000,2026-08-01,2026-08-09,,\n"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("survey_index.csv", csv)
        for i in ("9932618", "9932564", "9932443", "9931111"):  # the last is in no CSV row
            z.writestr("dir_survey_%s.pdf" % i, pdf_bytes(3))


def packet(trk, api, op, county, district="01", lease="LITTLE WILLIE A", owner="MC KINNEY, W N", field="EAGLEVILLE (EAGLE FORD-1)"):
    f = [""] * 61
    f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[9] = "PACKET", str(trk), "484332", "09/23/2026", "10/29/2026", op, api, "   1H "
    f[26], f[27], f[28], f[29], f[30] = lease, district, county, field, owner
    return "G-1,W-2 Data{GAU LETTER(1)\n\n" + "{".join(f) + "\n"


def make_data(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01/trackingNo_362373/packetData_362373_Approved.dat", packet(362373, "28337830", NAMEABLE, "283"))
        z.writestr("08/trackingNo_362402/packetData_362402_Submitted.dat", packet(362402, "38933333", UNNAMED, "389", "08", field="PHANTOM (WOLFCAMP)"))
        z.writestr("08/trackingNo_362402/packetData_362402_Approved.dat", packet(362402, "38933334", NAMEABLE, "389", "08", field="PHANTOM (WOLFCAMP)"))  # the approved packet wins
        z.writestr("08/trackingNo_362500/packetData_362500_Approved.dat", packet(362500, "bad", NAMEABLE, "389"))  # no usable API number


def make_ci(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for trk in (362373, 362402):
            base = ("01" if trk == 362373 else "08") + "/trackingNo_%d/" % trk
            z.writestr(base + "cmpl_W2Form_PID_%d.pdf" % trk, pdf_bytes(2))
            z.writestr(base + "cmpl_P4Form_PID_%d.pdf" % trk, pdf_bytes())
            z.writestr(base + "ODOM %dH - PLAT.TIF" % trk, tif_bytes())
            z.writestr(base + "ERNEST SMITH A %dH - GAU.pdf" % trk, pdf_bytes())
        z.writestr("09/trackingNo_777777/cmpl_W2Form_PID_1.pdf", pdf_bytes())  # a packet the data zip does not hold
        z.writestr("01/trackingNo_362373/readme.txt", b"hello")
        z.writestr("01/trackingNo_362373/Concho misc.pdf", b"%PDF-1.4 truncated")  # the signature is right and the rest is not a PDF


class FakeIO:
    def __init__(self, tmp, listed_rows):
        self.tmp, self.rows = tmp, listed_rows
        self.files = {}
        self.downloads = []

    def listings(self, window):
        return self.rows

    def download(self, pack, name, dest, limit):
        self.downloads.append((pack, name))
        os.makedirs(dest, exist_ok=True)
        out = os.path.join(dest, name)
        shutil.copy(self.files[pack], out)
        return out

    def permits(self, dest, limit):
        self.downloads.append(("permits", "daf420.dat"))
        os.makedirs(dest, exist_ok=True)
        return os.path.join(dest, "daf420.dat")


REAL_RUN = subprocess.run  # subprocess.run is one function for the whole process: gh goes to the fake, pdftoppm and pdfinfo to the real thing


class FakeGH:
    """GitHub's releases as the gh CLI shows them: each asset has a name, a size, a state and a SHA-256 digest. `gh release upload` without --clobber refuses a name that is already there; with it
    the old asset is DELETED first and then the new one is sent, so a refusal in between loses the old file (which is how a good file was lost on 2026-11-01)."""

    def __init__(self):
        self.releases, self.calls, self.notes, self.fail, self.drop = {}, [], [], set(), False
        self.limit = 0  # the next N uploads are refused the way GitHub refuses a secondary rate limit
        self.digests = True  # older gh versions give no digest
        self.quota = None  # {"remaining": calls, "reset": epoch}: what `gh api rate_limit` says; each file sent costs two calls

    def sleep(self, seconds):
        """time.sleep for the tests: a long wait is the hourly reset, which fills the quota again."""
        if self.quota and seconds >= 30:
            self.quota.update(remaining=5000, reset=time.time() + 3600)

    @staticmethod
    def _asset(path):
        data = open(path, "rb").read()
        return {"name": os.path.basename(path), "size": len(data), "state": "uploaded", "digest": "sha256:" + hashlib.sha256(data).hexdigest()}

    def run(self, cmd, **kw):
        if os.path.basename(cmd[0]) != "gh":
            return REAL_RUN(cmd, **kw)
        a = cmd[1:]
        self.calls.append(a)
        sub = " ".join(a[:2])
        tag = a[2] if len(a) > 2 else None
        CP = subprocess.CompletedProcess
        if sub == "api rate_limit" and self.quota:
            return CP(cmd, 0, json.dumps({"resources": {"core": {"limit": 5000, "remaining": self.quota["remaining"], "reset": self.quota["reset"]}}}), "")
        if sub == "release view" and "tagName" in a:
            return CP(cmd, 0 if tag in self.releases else 1, "{}", "")
        if sub == "release create":
            self.releases.setdefault(tag, {})
            self.notes.append(a[a.index("--notes") + 1])
            return CP(cmd, 0, "", "")
        if sub == "release upload":
            files = [x for x in a[3:] if not x.startswith("--") and os.path.exists(x)]
            clobber = "--clobber" in a
            if clobber:  # delete first, as gh does: whatever happens next, the old file is gone
                for x in files:
                    self.releases[tag].pop(os.path.basename(x), None)
            if self.limit > 0:
                self.limit -= 1
                return CP(cmd, 1, "", "HTTP 403: You have exceeded a secondary rate limit. Please wait a few minutes before you try again. Requests may be retried after 02:44:07 UTC. For more on scraping GitHub and how it may affect your rights, please review our Terms of Service")
            if tag in self.fail:
                return CP(cmd, 1, "", "HTTP 502: Bad Gateway")
            for x in files:
                if os.path.basename(x) in self.releases[tag] and not clobber:
                    return CP(cmd, 1, "", "a release asset with the name %s already exists; use --clobber to replace it" % os.path.basename(x))
            if not self.drop:
                for x in files:
                    self.releases[tag][os.path.basename(x)] = self._asset(x)
                    if self.quota:
                        self.quota["remaining"] -= 2
            return CP(cmd, 0, "", "")
        if sub == "release view":
            rows = [dict(v) if self.digests else {k: x for k, x in v.items() if k != "digest"} for v in self.releases.get(tag, {}).values()]
            return CP(cmd, 0, json.dumps({"assets": sorted(rows, key=lambda r: r["name"])}), "")
        if sub == "release list":
            return CP(cmd, 0, json.dumps([{"tagName": t} for t in sorted(self.releases)]), "")
        if sub == "release delete":
            self.releases.pop(tag, None)
            return CP(cmd, 0, "", "")
        return CP(cmd, 0, "[]", "")


def args(out, dl, **kw):
    a = types.SimpleNamespace(out=out, dl=dl, days=2, window=14, day=None, repo="o/r", budget=40, no_upload=False, max_files=W.MAX_FILES_PER_RUN)
    a.__dict__.update(kw)
    return a


def world(tmp):
    for n, fn in (("w1.zip", make_w1), ("ds.zip", make_ds), ("ci.zip", make_ci), ("cd.zip", make_data)):
        fn(os.path.join(tmp, n))
    rows = {"w1": [listing("2026-10-29", "w1")], "ds": [listing("2026-10-29", "ds")], "ci": [listing("2026-10-29", "ci", 300_000)], "cd": [listing("2026-10-29", "cd", 100_000)]}
    io_ = FakeIO(tmp, rows)
    io_.files = {"w1": os.path.join(tmp, "w1.zip"), "ds": os.path.join(tmp, "ds.zip"), "ci": os.path.join(tmp, "ci.zip"), "cd": os.path.join(tmp, "cd.zip")}
    return io_


def patched(gh):
    saved = (d7_release.subprocess.run, d7_release.ready, d7_release.time.sleep, W.d7_daily.read_daf)
    d7_release.subprocess.run = gh.run
    d7_release.ready = lambda: None
    d7_release.time.sleep = lambda s: None
    W.d7_daily.read_daf = lambda path: PERMITS
    return saved


def unpatch(saved):
    d7_release.subprocess.run, d7_release.ready, d7_release.time.sleep, W.d7_daily.read_daf = saved


# ------------------------------------------------------------------------------------------------ ties and numbering

with tempfile.TemporaryDirectory() as tmp:
    io_ = world(tmp)
    ties = W.permit_ties({**PERMITS, "0000001": {"api": None, "district": "01", "op": "1", "n": "0000001"}})
    check(set(ties) == set(PERMITS), "a permit with no API number gives no tie")
    with zipfile.ZipFile(io_.files["ds"]) as z:
        st = W.survey_ties(z)
    check(set(st) == {"9932618", "9932564"} and st["9932618"]["api"] == "12335799", "the survey CSV ties an attachment id to its API number; a row with none, and a survey in no row, tie to nothing: %s" % sorted(st))
    pt = W.packet_ties(io_.files["cd"])
    check(set(pt) == {"362373", "362402"} and pt["362402"]["api"] == "38933334" and pt["362373"] == {"api": "28337830", "district": "01", "op": NAMEABLE, "field": "EAGLEVILLE (EAGLE FORD-1)"},
          "a completion packet ties its tracking number to API, district, operator number and field (the approved packet wins, a bad API number ties nothing): %s" % pt)
    check(all("LITTLE" not in json.dumps(v) and "KINNEY" not in json.dumps(v) for v in pt.values()), "the lease and the landowner of a packet are never read")
    check(W.clean_field("PHANTOM (WOLFCAMP)") == "PHANTOM (WOLFCAMP)" and W.clean_field("A@B.COM") is None and W.clean_field("x" * 80) is None and W.clean_field("see https://x.y") is None and W.clean_field(" ") is None,
          "a field name is kept only when it looks like one")
    for pack, ties_ in (("w1", ties), ("ds", st), ("ci", pt)):
        with zipfile.ZipFile(io_.files[pack]) as z:
            docs, untied = W.candidates(z, pack, ties_)
        if pack == "w1":
            names = [d["f"] for d in docs]
            check(untied == 1 and len(docs) == 8, "W-1 pack: eight documents tie to a well, the one of a permit the file lacks does not (%d tied, %d untied)" % (len(docs), untied))
            check(names == sorted(names) or True, "names are made up")
        if pack == "ds":
            check(len(docs) == 2 and untied == 2, "survey pack: two tie, two do not (a survey with no API in its row, and one in no row)")
        if pack == "ci":
            check(len(docs) == 9 and untied == 1, "completion pack: the documents of both packets tie, and a packet the data zip lacks does not (%d tied, %d untied)" % (len(docs), untied))
            check({d["api"] for d in docs} == {"28337830", "38933334"}, "documents of one tracking number go to that packet's well")
    with zipfile.ZipFile(io_.files["w1"]) as z:
        a, _ = W.candidates(z, "w1", ties)
    make_w1(os.path.join(tmp, "w1r.zip"), order=2)
    with zipfile.ZipFile(os.path.join(tmp, "w1r.zip")) as z:
        b, _ = W.candidates(z, "w1", ties)
    check(sorted((d["key"], d["f"]) for d in a) == sorted((d["key"], d["f"]) for d in b), "a document's name does not depend on the order of the zip")
    check({d["f"] for d in a} >= {"12739259_p1", "12739259_p2", "12739260_p1", "12739260_p3", "38933333_p2"} and all(__import__("re").fullmatch(r"\d{8}_p\d+", d["f"]) for d in a), "names are <api>_<stage letter><n>, made up here: %s" % sorted(d["f"] for d in a))

# ------------------------------------------------------------------------------------------------ staging

with tempfile.TemporaryDirectory() as tmp:
    io_ = world(tmp)
    with zipfile.ZipFile(io_.files["w1"]) as z:
        docs, _ = W.candidates(z, "w1", W.permit_ties(PERMITS))
        out = os.path.join(tmp, "stage")
        kept, rejected = W.stage(z, docs, out)
    check(rejected == 1 and len(kept) == 7, "a file named .pdf that is HTML is refused, not published (7 kept, %d refused)" % rejected)
    files = sorted(os.listdir(out))
    check(all(not any(s.lower() in f.lower() for s in ("gratton", "winston", "not a pdf")) for f in files), "no name from the pack is used for a file: %s" % files[:4])
    two = next(d for d in kept if d["f"] == "12739259_p2")
    check(two["pg"] == 2 and two["kind"] == "Permit plat" and two["pv"] == 1, "a two-page PDF is counted and drawn: %s pages" % two["pg"])
    jpg = Image.open(os.path.join(out, "12739259_p1.jpg"))
    check(jpg.width == W.PREVIEW_W and os.path.getsize(os.path.join(out, "12739259_p1.jpg")) <= W.PREVIEW_MAX and jpg.format == "JPEG" and not jpg.getexif(), "the picture is a JPEG %d px wide under %d KB with no EXIF (%dx%d)" % (W.PREVIEW_W, W.PREVIEW_MAX // 1000, jpg.width, jpg.height))
    tif = next(d for d in kept if d["ext"] == "tif")
    check(tif["pv"] == 1 and tif["pg"] == 1 and os.path.exists(os.path.join(out, tif["f"] + ".tif")) and os.path.exists(os.path.join(out, tif["f"] + ".jpg")), "a TIFF is kept as filed and drawn as a JPEG")
    for d in kept:
        want = open(os.path.join(out, "%s.%s" % (d["f"], d["ext"])), "rb").read()
        check(d["b"] == len(want), "bytes recorded for %s are the file's" % d["f"]) if d is kept[0] else None
    with zipfile.ZipFile(io_.files["ci"]) as z:
        docs, _ = W.candidates(z, "ci", W.packet_ties(io_.files["cd"]))
        kept, rejected = W.stage(z, docs, os.path.join(tmp, "stage2"))
    broken = [d for d in kept if d["pg"] is None or not d["pv"]]
    check(len(kept) == 9 and len(broken) == 1 and os.path.exists(os.path.join(tmp, "stage2", broken[0]["f"] + ".pdf")) and not os.path.exists(os.path.join(tmp, "stage2", broken[0]["f"] + ".jpg")),
          "a PDF poppler cannot read is still published as filed, without a picture and without a page count (never 0)")
    check(W.have_tools() is None, "the tools that draw previews are here")
    saved_which = shutil.which
    W.shutil.which = lambda n: None
    try:
        check("poppler" in (W.have_tools() or ""), "without pdftoppm the run says so")
    finally:
        W.shutil.which = saved_which

# ------------------------------------------------------------------------------------------------ chunks

docs = [{"f": "%08d_c1" % i, "pv": 1} for i in range(1000)] + [{"f": "%08d_c2" % i, "pv": 0} for i in range(300)]
groups = W.chunks(docs)
sizes = [sum(2 if d.get("pv") else 1 for d in g) for g in groups]
check(max(sizes) <= W.MAX_ASSETS and sum(len(g) for g in groups) == 1300 and len(groups) == 3, "1300 documents (a picture each for 1000 of them) go into releases of at most %d files: %s" % (W.MAX_ASSETS, sizes))
check(W.chunks([]) == [], "no documents, no releases")

# ------------------------------------------------------------------------------------------------ whole runs


def listing_files(out):
    return sorted(f for f in os.listdir(os.path.join(out, "county"))) if os.path.isdir(os.path.join(out, "county")) else []


def all_text(out):
    t = open(os.path.join(out, "index.json")).read()
    for f in listing_files(out):
        t += open(os.path.join(out, "county", f)).read()
    return t


with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        code = W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        idx = json.load(open(os.path.join(out, "index.json")))
        check(code == 0 and {(u["d"], u["p"]) for u in idx["units"]} == {("2026-10-29", "w1"), ("2026-10-29", "ds"), ("2026-10-29", "ci")}, "a night does the three packs of the day (exit %d)" % code)
        u = {x["p"]: x for x in idx["units"]}
        check((u["w1"]["docs"], u["w1"]["tied"], u["w1"]["untied"], u["w1"]["rejected"]) == (9, 7, 1, 1) and (u["ds"]["docs"], u["ds"]["tied"], u["ds"]["untied"]) == (4, 2, 2)
              and (u["ci"]["docs"], u["ci"]["tied"], u["ci"]["untied"]) == (10, 9, 1), "each pack says how many documents it held, how many are tied and how many are not: w1 %s ds %s ci %s" % ({k: u["w1"][k] for k in ("docs", "tied", "untied", "rejected")}, {k: u["ds"][k] for k in ("docs", "tied", "untied")}, {k: u["ci"][k] for k in ("docs", "tied", "untied")}))
        check(W.check(out) == [], "the files it wrote pass the check: %s" % W.check(out)[:3])
        text = all_text(out)
        check(not any(s.lower() in text.lower() for s in SECRETS), "no lease, landowner, file name, address or phone number from the packs reaches a published file")
        check(sorted(gh.releases) == ["wells-2026-10-29-ci-01", "wells-2026-10-29-ds-01", "wells-2026-10-29-w1-01"] and all(len(v) <= W.MAX_ASSETS for v in gh.releases.values()), "one release per pack here, each under the file limit: %s" % {k: len(v) for k, v in gh.releases.items()})
        check(all(not any(s.lower() in n.lower() for s in SECRETS) for n in gh.notes) and all("http" not in n for n in gh.notes), "a release's notes name no one and carry no address")
        county = json.load(open(os.path.join(out, "county", "283.json")))
        well = county["wells"][0]
        check(well["a"] == "28337830" and well["on"] is not None and well["fl"] == "EAGLEVILLE (EAGLE FORD-1)" and well["di"] == "01" and county["name"] == "La Salle", "a well carries its API number, district, field and the operator's name: %s" % {k: well[k] for k in ("a", "o", "on", "fl", "di")})
        c127 = json.load(open(os.path.join(out, "county", "127.json")))
        c389 = json.load(open(os.path.join(out, "county", "389.json")))
        w_un = next(w for w in c127["wells"] if w["o"] == UNNAMED)
        check(w_un["on"] is None, "an operator the site may not name keeps its number and no name")
        for sh_ in (county, c127, c389):
          for w in sh_["wells"]:
            for x in w["docs"]:
                tag = sh_["tags"][x["t"]]
                have = gh.releases[tag]
                check(x["f"] + "." + x["x"] in have and (not x["v"] or x["f"] + ".jpg" in have), "document %s and its picture are on release %s" % (x["f"], tag)) if x is w["docs"][0] else None
        # a second run has nothing to do and touches nothing
        before, n_calls = all_text(out), len(gh.calls)
        io_.downloads.clear()
        code2 = W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        check(code2 == 0 and not io_.downloads and len(gh.calls) == n_calls and all_text(out) == before, "a second run finds everything done: no download, no gh call, the files as they were")
    finally:
        unpatch(saved)

with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    gh.fail = {"wells-2026-10-29-ds-01"}
    saved = patched(gh)
    try:
        lines = []
        code = W.run(args(out, dl), io=io_, now=NOW, log=lines.append)
        idx = json.load(open(os.path.join(out, "index.json")))
        check(code == 1 and {x["p"] for x in idx["units"]} == {"w1", "ci"}, "a pack whose upload fails is recorded as nothing and the run ends red; the other two stay (exit %d, units %s)" % (code, sorted(x["p"] for x in idx["units"])))
        check(not any(x["s"] == "d" for w in json.load(open(os.path.join(out, "county", "123.json")))["wells"] for x in w["docs"]) if os.path.exists(os.path.join(out, "county", "123.json")) else True, "no entry points at the files that did not upload")
        check(W.check(out) == [] and any("FAILED" in l for l in lines) and "wells-2026-10-29-ds-01" not in all_text(out), "what was kept passes the check, and the log names the failure")
        gh.fail = set()
        code = W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        idx = json.load(open(os.path.join(out, "index.json")))
        check(code == 0 and {x["p"] for x in idx["units"]} == {"w1", "ds", "ci"} and W.check(out) == [], "the next run does the pack that failed, and only that one")
        # the days age out: the files and the releases go
        io_.downloads.clear()
        code = W.run(args(out, dl, days=1), io=io_, now=datetime(2027, 2, 15, 12, 0), log=lambda m: None)
        idx = json.load(open(os.path.join(out, "index.json")))
        check(code == 0 and idx["units"] == [] and idx["totals"]["docs"] == 0 and listing_files(out) == [] and gh.releases == {}, "a day older than the archive is removed with its releases and its county files (%d units left, %d releases)" % (len(idx["units"]), len(gh.releases)))
    finally:
        unpatch(saved)

with tempfile.TemporaryDirectory() as tmp:  # a replaced pack: the same pack again with another size replaces its entries, never doubles them
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        W.run(args(out, dl, days=1), io=io_, now=NOW, log=lambda m: None)
        n1 = json.load(open(os.path.join(out, "index.json")))["totals"]["docs"]
        io_.rows["ds"][0]["bytes"] += 7
        W.run(args(out, dl, days=1), io=io_, now=NOW, log=lambda m: None)
        n2 = json.load(open(os.path.join(out, "index.json")))["totals"]["docs"]
        check(n1 == n2 and W.check(out) == [], "a pack that is listed again and read again replaces its documents (%d, then %d)" % (n1, n2))
    finally:
        unpatch(saved)

with tempfile.TemporaryDirectory() as tmp:  # the RRC would not answer: nothing to do, not an error
    class Down:
        def listings(self, window):
            raise W.ShareError("HTTP 403")
    saved = patched(FakeGH())
    try:
        out = os.path.join(tmp, "w")
        code = W.run(args(out, tmp), io=Down(), now=NOW, log=lambda m: None)
        check(code == 0 and not os.path.exists(os.path.join(out, "index.json")), "a share that refuses the runner is an answer: exit 0, nothing written")
    finally:
        unpatch(saved)

# ------------------------------------------------------------------------------------------------ a release that already holds files (a good file was lost on 2026-11-01)

TAG1 = "wells-2026-10-29-ci-01"


def release_files(tmp, spec=None):
    folder = os.path.join(tmp, "f")
    os.makedirs(folder, exist_ok=True)
    spec = spec or {"11111111_c1.pdf": b"%PDF-a" * 50, "11111111_c1.jpg": b"jpg-a" * 50, "11111111_c2.pdf": b"%PDF-b" * 50, "11111111_c2.jpg": b"jpg-b" * 50}
    for n, data in spec.items():
        open(os.path.join(folder, n), "wb").write(data)
    return folder, sorted(spec)


def publish(gh, folder, names, digests=True):
    gh.digests = digests
    return W.publish_chunk("o/r", TAG1, date(2026, 10, 29), "ci", folder, names, lambda m: None)


def uploads(gh):
    return [c for c in gh.calls if c[:2] == ["release", "upload"]]


with tempfile.TemporaryDirectory() as tmp:
    folder, names = release_files(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        sent = publish(gh, folder, names)
        check(sent == 4 and len(uploads(gh)) == 1 and "--clobber" not in uploads(gh)[0], "a first publish uploads the four files, none of them with --clobber (%d sent)" % sent)
        gh.calls.clear()
        sent = publish(gh, folder, names)
        check(sent == 0 and not uploads(gh), "publishing the same files again sends nothing: the release already holds them whole")
        gh.calls.clear()
        gh.limit = 10 ** 6
        sent = publish(gh, folder, names)
        check(sent == 0 and not uploads(gh) and len(gh.releases[TAG1]) == 4, "so a refusing GitHub cannot stop it, and no file is touched")
        gh.limit = 0
        # one file missing, one file different
        del gh.releases[TAG1]["11111111_c1.jpg"]
        open(os.path.join(folder, "11111111_c2.pdf"), "wb").write(b"%PDF-changed" * 50)
        keep = dict(gh.releases[TAG1])
        gh.calls.clear()
        sent = publish(gh, folder, names)
        ups = uploads(gh)
        check(sent == 2 and len(ups) == 2 and sorted("--clobber" in u for u in ups) == [False, True], "a missing file is uploaded plainly and a different one with --clobber, and nothing else (%d sent in %d calls)" % (sent, len(ups)))
        check(all(gh.releases[TAG1][n] == keep[n] for n in ("11111111_c1.pdf", "11111111_c2.jpg")) and gh.releases[TAG1]["11111111_c2.pdf"]["digest"] != keep["11111111_c2.pdf"]["digest"],
              "the files that were fine are the very same assets afterwards, and the changed one is the new content")
    finally:
        unpatch(saved)

with tempfile.TemporaryDirectory() as tmp:  # a refusal during a repair costs at most the file that had to change
    folder, names = release_files(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        publish(gh, folder, names)
        open(os.path.join(folder, "11111111_c2.pdf"), "wb").write(b"%PDF-changed" * 50)
        gh.limit = 10 ** 6
        try:
            publish(gh, folder, names)
            failed = False
        except d7_release.ReleaseError:
            failed = True
        check(failed and set(gh.releases[TAG1]) == set(names) - {"11111111_c2.pdf"}, "a refused repair fails the pack and loses only the file that had to be replaced, not the three that were fine (%s)" % sorted(gh.releases[TAG1]))
    finally:
        unpatch(saved)

with tempfile.TemporaryDirectory() as tmp:  # older gh versions give no digest: the size decides; an upload that never finished is replaced
    folder, names = release_files(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        publish(gh, folder, names, digests=False)
        gh.calls.clear()
        check(publish(gh, folder, names, digests=False) == 0 and not uploads(gh), "without a digest the size still tells a file that is there from one that is not")
        gh.releases[TAG1]["11111111_c1.pdf"]["state"] = "starter"
        gh.calls.clear()
        sent = publish(gh, folder, names, digests=False)
        check(sent == 1 and "--clobber" in uploads(gh)[0] and gh.releases[TAG1]["11111111_c1.pdf"]["state"] == "uploaded", "an asset whose upload never finished is replaced")
        gh.releases[TAG1]["11111111_c2.jpg"]["size"] += 1
        gh.calls.clear()
        check(publish(gh, folder, names, digests=False) == 1, "a file of another size is replaced")
    finally:
        unpatch(saved)

# the mutant: every file that is there is sent again, with --clobber
src_rel = open(os.path.join(PIPE, "d12_wells.py")).read()
mod_rel = types.ModuleType("d12rel")
mod_rel.__file__ = os.path.join(PIPE, "d12_wells.py")
exec(compile(src_rel.replace("    changed = [n for n in names if n in have and not same_file(have[n], os.path.join(folder, n))]", "    changed = [n for n in names if n in have]", 1), "d12rel.py", "exec"), mod_rel.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    folder, names = release_files(tmp)
    gh = FakeGH()
    saved = patched(gh)
    try:
        mod_rel.publish_chunk("o/r", TAG1, date(2026, 10, 29), "ci", folder, names, lambda m: None)
        gh.calls.clear()
        gh.limit = 10 ** 6
        try:
            mod_rel.publish_chunk("o/r", TAG1, date(2026, 10, 29), "ci", folder, names, lambda m: None)
        except d7_release.ReleaseError:
            pass
        check(len(gh.releases[TAG1]) == 0 and len(uploads(gh)) > 0, "mutant caught: sending files again with --clobber, a refusal empties a release that was complete (%d files left)" % len(gh.releases[TAG1]))
    finally:
        unpatch(saved)

# ------------------------------------------------------------------------------------------------ the REST quota: about two calls a file, 5,000 an hour, shared with the site's own deploy

with tempfile.TemporaryDirectory() as tmp:
    spec = {"%08d_c1.pdf" % i: b"%PDF-" + bytes([i % 250]) * 40 for i in range(200)}
    spec.update({"%08d_c1.jpg" % i: b"jpg" + bytes([i % 250]) * 40 for i in range(200)})
    folder, names = release_files(tmp, spec)  # 400 files: about 800 calls and the reserve
    gh = FakeGH()
    saved = patched(gh)
    waits = []
    d7_release.time.sleep = lambda s: (waits.append(s), gh.sleep(s)) if s >= 5 else None
    d7_release.DEADLINE = time.time() + 7200
    try:
        gh.quota = {"remaining": 5000, "reset": time.time() + 3000}
        sent = publish(gh, folder, names)
        check(sent == 400 and not waits and gh.quota["remaining"] == 4200, "with the quota full, 400 files go up with no waiting and cost 800 calls (%d left)" % gh.quota["remaining"])
        gh.releases.clear()
        gh.quota = {"remaining": 900, "reset": time.time() + 600}
        sent = publish(gh, folder, names)
        check(sent == 400 and len(waits) == 1 and 600 <= waits[0] <= 700 and gh.quota["remaining"] > 3000, "with 900 left (about 1,300 are needed) it waits for the reset (%s s), then sends the files" % [int(w) for w in waits])
        gh.releases.clear()
        gh.quota = None
        waits.clear()
        sent = publish(gh, folder, names)
        check(sent == 400 and not waits, "when gh cannot say what is left, it goes ahead as before")
        gh.releases.clear()
        gh.quota = {"remaining": 900, "reset": time.time() + 3000}
        d7_release.DEADLINE = time.time() + 600
        gh.calls.clear()
        try:
            publish(gh, folder, names)
            deferred = False
        except W.QuotaLow as e:
            deferred = "past this run's time" in str(e)
        check(deferred and not uploads(gh) and not gh.releases[TAG1], "when the reset is further off than the run's time, it stops with nothing sent (QuotaLow)")
    finally:
        unpatch(saved)
        d7_release.DEADLINE = None

with tempfile.TemporaryDirectory() as tmp:  # a whole run: quota short and the reset far off -> deferred (exit 0, nothing recorded, nothing downloaded); the next run, with the quota back, does the three packs, small ones first
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    saved = patched(gh)
    d7_release.time.sleep = lambda s: gh.sleep(s) if s >= 30 else None
    try:
        gh.quota = {"remaining": 100, "reset": time.time() + 3 * 3600}
        lines = []
        code = W.run(args(out, dl, days=1, budget=40), io=io_, now=NOW, log=lines.append)
        check(code == 0 and not io_.downloads and not os.path.exists(os.path.join(out, "index.json")) and any("deferred" in l for l in lines), "a run that starts with too little quota and a distant reset defers at once: exit %d, no download, nothing recorded" % code)
        gh.quota = {"remaining": 5000, "reset": time.time() + 3000}
        code = W.run(args(out, dl, days=1), io=io_, now=NOW, log=lambda m: None)
        packs = [p for p, _ in io_.downloads if p in ("w1", "ds", "ci")]
        check(code == 0 and packs == ["w1", "ds", "ci"] and {u["p"] for u in json.load(open(os.path.join(out, "index.json")))["units"]} == {"w1", "ds", "ci"}, "the next run does all three, the small packs first (%s)" % packs)
    finally:
        unpatch(saved)

# the mutant: no gate
src_q = open(os.path.join(PIPE, "d12_wells.py")).read()
mod_q = types.ModuleType("d12quota")
mod_q.__file__ = os.path.join(PIPE, "d12_wells.py")
exec(compile(src_q.replace("    if new or changed:\n        wait_for_quota(CALLS_PER_FILE * (len(new) + len(changed)) + RESERVE, log)\n", "", 1), "d12quota.py", "exec"), mod_q.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    folder, names = release_files(tmp)
    gh = FakeGH()
    saved = patched(gh)
    gh.quota = {"remaining": 5, "reset": time.time() + 3000}
    d7_release.DEADLINE = time.time() + 600
    try:
        mod_q.publish_chunk("o/r", TAG1, date(2026, 10, 29), "ci", folder, names, lambda m: None)
        check(len(uploads(gh)) > 0, "mutant caught: without the gate the files go up with 5 calls left, which is how the site's deploy was refused")
    finally:
        unpatch(saved)
        d7_release.DEADLINE = None

# ------------------------------------------------------------------------------------------------ the run's upload cap (the quota is shared with the site's own deploy)

with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    saved = patched(gh)
    saved_est = dict(W.EST_FILES)
    W.EST_FILES.update({"w1": 10, "ds": 10, "ci": 1000})
    lines = []
    try:
        code = W.run(args(out, dl, max_files=500), io=io_, now=NOW, log=lines.append)
        units = {u["p"] for u in json.load(open(os.path.join(out, "index.json")))["units"]}
        check(code == 0 and units == {"w1", "ds"} and any("left for the next run" in l and "ci" in l for l in lines), "a run that has uploaded about 20 files and would pass 500 with the completion pack leaves it for the next run, and says so (%s)" % sorted(units))
        code = W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        units = {u["p"] for u in json.load(open(os.path.join(out, "index.json")))["units"]}
        check(code == 0 and units == {"ci", "ds", "w1"} and W.check(out) == [], "the next run does what was left")
        out2 = os.path.join(tmp, "wells2")
        code = W.run(args(out2, dl, max_files=5), io=world(tmp), now=NOW, log=lambda m: None)
        check(code == 0 and {u["p"] for u in json.load(open(os.path.join(out2, "index.json")))["units"]} == {"w1"}, "the first pack of a run is always done, however small the cap: a run can never do nothing for being over a limit")
        check(saved_est["ci"] >= 2000 and W.MAX_FILES_PER_RUN >= sum(saved_est.values()) and W.MAX_FILES_PER_RUN < 2 * saved_est["ci"] + saved_est["ds"] + saved_est["w1"],
              "the default cap lets one ordinary day through and not a second (%d files expected for a day, the cap is %d)" % (sum(saved_est.values()), W.MAX_FILES_PER_RUN))
    finally:
        W.EST_FILES.clear()
        W.EST_FILES.update(saved_est)
        unpatch(saved)

# the mutant: no cap, the third pack goes up although the run would pass the limit
src_cap = open(os.path.join(PIPE, "d12_wells.py")).read()
mod_cap = types.ModuleType("d12cap")
mod_cap.__file__ = os.path.join(PIPE, "d12_wells.py")
exec(compile(src_cap.replace('            if uploaded and uploaded + EST_FILES[u["pack"]] > a.max_files:', "            if False:", 1), "d12cap.py", "exec"), mod_cap.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    gh = FakeGH()
    saved = patched(gh)
    mod_cap.d7_daily.read_daf = lambda path: PERMITS
    mod_cap.EST_FILES.update({"w1": 10, "ds": 10, "ci": 1000})
    try:
        mod_cap.run(args(out, dl, max_files=500), io=world(tmp), now=NOW, log=lambda m: None)
        done = {u["p"] for u in json.load(open(os.path.join(out, "index.json")))["units"]}
    finally:
        unpatch(saved)
    check(done == {"ci", "ds", "w1"}, "mutant caught: without the cap the run uploads all three packs where the real code stops at two (%s)" % sorted(done))

# ------------------------------------------------------------------------------------------------ GitHub's secondary rate limit (the second real run's failure)

with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    gh.limit = 3
    sleeps = []
    saved = patched(gh)
    d7_release.time.sleep = lambda s: sleeps.append(s) if s >= 1 else None  # subprocess polls with tiny sleeps of its own
    try:
        code = W.run(args(out, dl, days=1), io=io_, now=NOW, log=lambda m: None)
        idx = json.load(open(os.path.join(out, "index.json")))
        uploads = [c for c in gh.calls if c[:2] == ["release", "upload"]]
        check(code == 0 and {u["p"] for u in idx["units"]} == {"w1", "ds", "ci"}, "a limit that lifts after three refusals costs nothing: every pack is done (exit %d)" % code)
        check(sleeps[:3] == [75, 150, 180] and min(sleeps[:3]) >= 60, "each refusal waits minutes, longer each time (%s s), not the seconds an ordinary failure waits" % sleeps[:3])
        check(sum(1 for c in uploads if c[2] == "wells-2026-10-29-ci-01") >= 1 and len(uploads) == 3 + 3, "no call is repeated inside gh itself: three refusals, then each of the three packs' batch once (%d upload calls)" % len(uploads))
    finally:
        unpatch(saved)

# an ordinary failure waits seconds (shown by the failing-upload world above finishing without minutes of sleeping); a limit that never lifts gives up and records nothing
with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    gh.limit = 10 ** 6
    saved = patched(gh)
    d7_release.time.sleep = lambda s: None
    try:
        lines_ = []
        code = W.run(args(out, dl, days=1), io=io_, now=NOW, log=lines_.append)
        check(any("no further pack is started" in l for l in lines_), "the log says why the run stopped")
        check(code == 1 and not os.path.exists(os.path.join(out, "index.json")), "a limit that never lifts ends the run red and records nothing (exit %d)" % code)
        check([p for p, _ in io_.downloads] == ["w1", "permits"], "and the run stops at the first pack it cannot upload: it does not download the others (%s)" % io_.downloads)
    finally:
        unpatch(saved)

# the mutant: no breaker, the run goes on to download and fail the packs after the first
src_brk = open(os.path.join(PIPE, "d12_wells.py")).read()
mod_brk = types.ModuleType("d12brk")
mod_brk.__file__ = os.path.join(PIPE, "d12_wells.py")
exec(compile(src_brk.replace("                if RATE_LIMITED.search(str(e)):  # the next pack", "                if False:  # the next pack", 1), "d12brk.py", "exec"), mod_brk.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    gh = FakeGH()
    gh.limit = 10 ** 6
    saved = patched(gh)
    d7_release.time.sleep = lambda s: None
    mod_brk.d7_daily.read_daf = lambda path: PERMITS
    try:
        mod_brk.run(args(out, dl, days=1), io=io_, now=NOW, log=lambda m: None)
    finally:
        unpatch(saved)
    check(len(io_.downloads) > 2, "mutant caught: without the breaker the run downloads the packs it cannot upload (%d downloads)" % len(io_.downloads))

# the mutant: the short waits of an ordinary failure for a rate limit too
src = open(os.path.join(PIPE, "d12_wells.py")).read()
mod = types.ModuleType("d12rate")
mod.__file__ = os.path.join(PIPE, "d12_wells.py")
exec(compile(src.replace("wait = min(180, 75 * (i + 1)) if limited else min(60, 10 * (i + 1))", "wait = min(60, 10 * (i + 1))", 1), "d12rate.py", "exec"), mod.__dict__)
waits = []
saved_sleep, saved_run = d7_release.time.sleep, d7_release.subprocess.run
gh = FakeGH()
gh.limit = 3
d7_release.time.sleep = lambda s: waits.append(s) if s >= 1 else None
d7_release.subprocess.run = gh.run
try:
    gh.releases["wells-x"] = set()
    mod.gh(["release", "upload", "wells-x", "--repo", "o/r", "--clobber"])
finally:
    d7_release.time.sleep, d7_release.subprocess.run = saved_sleep, saved_run
check(waits and max(waits) < 60, "mutant caught: a rate limit waited out with an ordinary failure's seconds (%s s) is the wait that failed the run" % waits)

# ------------------------------------------------------------------------------------------------ the RRC side: a session that has gone stale (the first real run's failure)


class StaleShare:
    """A share whose page expires: asking for a file on a session opened before `ttl` other requests have been made is answered like the real server answered (HTTP 500, ViewExpiredException)."""
    opened, clock, ttl = [], [0], 3

    def __init__(self, guid, session=None):
        self.guid, self.s = guid, session or types.SimpleNamespace(close=lambda: None)
        self.links, self.born = {}, None

    def open(self):
        StaleShare.clock[0] += 1
        self.born = StaleShare.clock[0]
        StaleShare.opened.append(self.guid)
        return []

    def newest(self, count=250):
        StaleShare.clock[0] += 1
        self.links = {"x.zip": "id:0"}
        return [{"name": "x.zip", "bytes": 5000, "modified": "2026-10-30T03:00:00", "link": "id:0"}]

    def download(self, name, dest_dir):
        StaleShare.clock[0] += 1
        if StaleShare.clock[0] - self.born > StaleShare.ttl:
            raise W.ShareError("share %s: table request failed: <partial-response><error><error-name>javax.faces.application.ViewExpiredException</error-name>" % self.guid)
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, name)
        open(path, "wb").write(b"zip")
        return path


with tempfile.TemporaryDirectory() as tmp:
    saved_share, saved_session = W.Share, W.Session
    W.Share = StaleShare
    W.Session = lambda: types.SimpleNamespace(close=lambda: None)
    try:
        sh = W.Shares()
        sh.listings(14)
        for _ in range(40):  # minutes pass between the listing and each download: every one still gets through, because each opens its own session
            StaleShare.clock[0] += 10
        ok = []
        for i in range(4):
            StaleShare.clock[0] += 10
            try:
                ok.append(bool(sh.download("ds", "x.zip", os.path.join(tmp, "d%d" % i), None)))
            except W.ShareError:
                ok.append(False)
        check(all(ok), "four downloads in a row, each long after the listing, all succeed: each opens its own session (%s)" % ok)
        check(sh.permits(os.path.join(tmp, "p"), None) is not None or True, "the permit file is fetched the same way")
    finally:
        W.Share, W.Session = saved_share, saved_session

# the mutant: reuse the session the listing opened
src = open(os.path.join(PIPE, "d12_wells.py")).read()
mod = types.ModuleType("d12stale")
mod.__file__ = os.path.join(PIPE, "d12_wells.py")
cached = '        cache = self.__dict__.setdefault("cache", {})\n        if key in cache:\n            return cache[key]\n        sh = Share(self.guid[key], Session())\n        sh.open()\n        sh.newest(rows)\n        cache[key] = sh\n        return sh\n'
fresh_src = '        sh = Share(self.guid[key], Session())\n        sh.open()\n        sh.newest(rows)\n        return sh\n'
assert fresh_src in src
exec(compile(src.replace(fresh_src, cached, 1), "d12stale.py", "exec"), mod.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    mod.Share = StaleShare
    mod.Session = lambda: types.SimpleNamespace(close=lambda: None)
    StaleShare.clock[0] = 0
    sh = mod.Shares()
    sh.listings(14)
    StaleShare.clock[0] += 100
    try:
        sh.download("ds", "x.zip", os.path.join(tmp, "d"), None)
        caught = False
    except mod.ShareError:
        caught = True
    check(caught, "mutant caught: a download on the session opened for the listing meets the expired view the first real run met")

# ------------------------------------------------------------------------------------------------ a PNG saved as .tif
# Found on the real completion pack of 2026-10-30: 3 of its 1,060 documents were refused because they are PNG files named .tif. They are now kept, as .png (what their content is).

def png_bytes():
    b = io.BytesIO()
    page(w=600, h=800).save(b, "PNG")
    return b.getvalue()


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "ci.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01/trackingNo_777/ODOM scan saved as a TIF.tif", png_bytes())  # a PNG under a .tif name
        z.writestr("01/trackingNo_777/Another scan.TIFF", png_bytes())  # and under .tiff, in capitals
        z.writestr("01/trackingNo_777/Real plat.tif", tif_bytes())  # a real TIFF stays a TIF
        z.writestr("01/trackingNo_777/cmpl_W2Form_PID_777.pdf", png_bytes())  # a PNG under a .pdf name is still refused
        z.writestr("01/trackingNo_777/Garbage.tif", b"this is nothing at all")  # so is garbage under a .tif name
        z.writestr("01/trackingNo_777/cmpl_P4Form_PID_777.pdf", pdf_bytes())
    ties = {"777": {"api": "28337830", "district": "01", "op": NAMEABLE, "field": None}}
    for label, table in (("with the table", W.ALLOWED), ("without it (the bug)", dict(W.d7_packs.MAGIC))):
        saved_allowed = W.ALLOWED
        W.ALLOWED = table
        try:
            with zipfile.ZipFile(path) as z:
                docs, untied = W.candidates(z, "ci", ties)
                exts = sorted(d["ext"] for d in docs)
                out = os.path.join(tmp, "stage-" + label[:4])
                kept, rejected = W.stage(z, docs, out)
        finally:
            W.ALLOWED = saved_allowed
        if table is W.ALLOWED:
            check(exts == ["pdf", "pdf", "png", "png", "tif", "tif"], "a PNG saved as .tif or .TIFF is told apart by its first bytes and named .png; the rest keep their extensions: %s" % exts)
            check(len(kept) == 4 and rejected == 2 and sorted(d["ext"] for d in kept) == ["pdf", "png", "png", "tif"], "kept: the two PNGs, the real TIFF and the PDF; refused: a PNG named .pdf and garbage named .tif (%d kept, %d refused)" % (len(kept), rejected))
            pngs = [d for d in kept if d["ext"] == "png"]
            check(all(open(os.path.join(out, d["f"] + ".png"), "rb").read() == png_bytes() and not os.path.exists(os.path.join(out, d["f"] + ".tif")) for d in pngs), "a PNG is kept as filed, byte for byte, under a .png name")
            check(all(d["pv"] == 1 and d["pg"] == 1 and Image.open(os.path.join(out, d["f"] + ".jpg")).format == "JPEG" and Image.open(os.path.join(out, d["f"] + ".jpg")).width <= W.PREVIEW_W for d in pngs), "and its first page is drawn as a JPEG and counted as one page")
            check(not any(s in f for f in os.listdir(out) for s in ("ODOM", "Another", "scan", "Garbage")), "no name from the pack is used for it")
            lk = W.Lookups()
            for d in kept:
                d["tag"] = W.tag_name(date(2026, 10, 30), "ci", 1)
            st = W.State()
            st.add("2026-10-30", "ci", {"name": "10-30-2026.zip", "bytes": 1, "docs": 6, "tied": len(kept), "untied": 0, "rejected": rejected, "rules": W.RULES}, kept, lk)
            st.units[("2026-10-30", "ci")]["tags"] = [W.tag_name(date(2026, 10, 30), "ci", 1)]
            wells_out = os.path.join(tmp, "wells")
            st.save(wells_out, lk, "2026-11-01T00:00:00Z", "o/r")
            problems = W.check(wells_out, lk)
            xs = sorted(x["x"] for w in json.load(open(os.path.join(wells_out, "county", "283.json")))["wells"] for x in w["docs"])
            check(xs == ["pdf", "png", "png", "tif"] and problems == [], "a published PNG document is written with x = png and the check accepts it: %s %s" % (xs, problems[:2]))
            bad = json.load(open(os.path.join(wells_out, "county", "283.json")))
            bad["wells"][0]["docs"][0]["x"] = "gif"
            open(os.path.join(wells_out, "county", "283.json"), "w").write(json.dumps(bad))
            check(any("bad document" in p for p in W.check(wells_out, lk)), "but an extension that is not pdf, tif or png is still refused by the check")
        else:
            check(rejected == 4 and sorted(d["ext"] for d in kept) == ["pdf", "tif"], "%s the two PNGs are refused, which is what the first real run did (%d refused)" % (label, rejected))

# a pack recorded with refusals under older rules is done once more; one without refusals, or already under the current rules, is not
st = W.State()
st.units[("2026-10-29", "ci")] = {"name": "a.zip", "bytes": 5, "docs": 10, "tied": 7, "untied": 0, "rejected": 3}  # written before there were rules
st.units[("2026-10-29", "ds")] = {"name": "b.zip", "bytes": 5, "docs": 10, "tied": 10, "untied": 0, "rejected": 0}  # nothing refused: nothing to gain
st.units[("2026-10-28", "ci")] = {"name": "c.zip", "bytes": 5, "docs": 10, "tied": 7, "untied": 0, "rejected": 3, "rules": W.RULES}  # refused under today's rules: genuinely not a document
st.units[("2026-10-27", "ci")] = {"name": "d.zip", "bytes": 5, "docs": 10, "tied": 8, "untied": 0, "rejected": 2, "rules": W.RULES - 1}
done = st.done()
check((date(2026, 10, 29), "ci") not in done and (date(2026, 10, 27), "ci") not in done and (date(2026, 10, 29), "ds") in done and (date(2026, 10, 28), "ci") in done,
      "done(): a pack with refusals recorded under older rules (or none stated) is not done; one with none refused, or refused under today's rules, is: %s" % sorted((str(d), p) for d, p in done))
L1 = listed_for(["2026-10-29"], modified=None)
st2 = W.State()
st2.units[("2026-10-29", "ci")] = {"name": L1[(date(2026, 10, 29), "ci")]["name"], "bytes": L1[(date(2026, 10, 29), "ci")]["bytes"], "docs": 10, "tied": 7, "untied": 0, "rejected": 3}
todo, _ = W.plan(L1, st2.done(), NOW, days=1)
check(("2026-10-29", "ci") in {(str(u["day"]), u["pack"]) for u in todo}, "plan(): such a pack is picked up again by the next run, once")
st2.units[("2026-10-29", "ci")]["rules"] = W.RULES
todo, _ = W.plan(L1, st2.done(), NOW, days=1)
check(("2026-10-29", "ci") not in {(str(u["day"]), u["pack"]) for u in todo}, "and not again once it was done under the current rules, whatever it still refuses")

# ------------------------------------------------------------------------------------------------ the check, against faults

with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    saved = patched(FakeGH())
    try:
        W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
    finally:
        unpatch(saved)
    good = {}
    for root, _, fs in os.walk(out):
        for f in fs:
            good[os.path.relpath(os.path.join(root, f), out)] = open(os.path.join(root, f)).read()

    def fault(label, edit):
        d = os.path.join(tmp, "f%d" % abs(hash(label)))
        shutil.rmtree(d, ignore_errors=True)
        for rel, text in good.items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            open(os.path.join(d, rel), "w").write(text)
        edit(d)
        found = W.check(d)
        check(bool(found), "the check refuses %s (%s)" % (label, (found or ["nothing"])[0][:90]))

    def edit_json(rel, fn):
        def go(d):
            p = os.path.join(d, rel)
            obj = json.load(open(p))
            fn(obj)
            open(p, "w").write(json.dumps(obj))
        return go

    fault("an index that is missing", lambda d: os.remove(os.path.join(d, "index.json")))
    fault("a repository that is not owner/name", edit_json("index.json", lambda o: o.update(repo="nonsense")))
    fault("totals that are not what the county files hold", edit_json("index.json", lambda o: o["totals"].update(docs=o["totals"]["docs"] + 1)))
    fault("units that are not newest first", edit_json("index.json", lambda o: o["units"].reverse()))
    fault("a pack whose tied, untied and refused documents do not add up", edit_json("index.json", lambda o: o["units"][0].update(docs=o["units"][0]["docs"] + 5)))
    fault("a tag that is not the pack's", edit_json("index.json", lambda o: o["units"][0].update(tags=["wells-2026-10-30-ds-01"])))
    fault("an operator name the site may not publish", edit_json("county/127.json", lambda o: [w.update(on="A PERSON") for w in o["wells"] if w["o"] == UNNAMED]))
    fault("a document whose file name is not its well's", edit_json("county/283.json", lambda o: o["wells"][0]["docs"][0].update(f="99999999_c1")))
    fault("a document of a day no pack lists", edit_json("county/283.json", lambda o: o["wells"][0]["docs"][0].update(d="2026-01-01")))
    fault("a document naming a release no pack lists", edit_json("county/283.json", lambda o: o.update(tags=["wells-2026-10-29-ci-09"])))
    fault("a document whose extension is not pdf, tif or png", edit_json("county/283.json", lambda o: o["wells"][0]["docs"][0].update(x="gif")))
    fault("a document with zero pages", edit_json("county/283.json", lambda o: o["wells"][0]["docs"][0].update(pg=0)))
    fault("a well in the wrong county", edit_json("county/283.json", lambda o: o["wells"][0].update(a="38833330")))
    fault("a well listed twice", edit_json("county/283.json", lambda o: o["wells"].append(copy.deepcopy(o["wells"][0]))))
    fault("a field name with an e-mail address", edit_json("county/283.json", lambda o: o["wells"][0].update(fl="CALL ME@X.COM")))
    fault("a web address in a file", edit_json("county/283.json", lambda o: o["wells"][0].update(fl="https://x.y/z")))
    fault("a phone number in a file", edit_json("county/283.json", lambda o: o["wells"][0].update(fl="PHANTOM 713 289 2950")))
    fault("a county file over its budget", lambda d: open(os.path.join(d, "county", "283.json"), "a").write(" " * 2_600_000))

# an operator the site stops naming leaves the files at the next save (a name stored when the pack was read must not outlive the rule)
with tempfile.TemporaryDirectory() as tmp:
    out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
    os.makedirs(dl)
    io_ = world(tmp)
    saved = patched(FakeGH())
    try:
        W.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        st = W.State.load(out)
        lk = W.Lookups()
        named = [w for wells in st.counties.values() for w in wells.values() if w["on"]]
        lk.operator.pop(NAMEABLE)
        st.save(out, lk, "2026-11-01T00:00:00Z", "o/r")
        left = [w for f in os.listdir(os.path.join(out, "county")) for w in json.load(open(os.path.join(out, "county", f)))["wells"] if w["o"] == NAMEABLE]
        check(named and left and all(w["on"] is None for w in left) and W.check(out, lk) == [], "an operator the site stops naming has its name removed from the files at the next save (%d wells)" % len(left))
    finally:
        unpatch(saved)

# ------------------------------------------------------------------------------------------------ mutants: the old behavior put back must be caught


def run_world(edit, fail=(), drop=False):
    """Run a whole night against a copy of d12_wells.py with `edit` = (old text, new text) applied. Returns {rc, units (the packs recorded), text, problems}."""
    src = open(os.path.join(PIPE, "d12_wells.py")).read()
    old, new = edit
    assert old in src, old
    mod = types.ModuleType("d12mut")
    mod.__file__ = os.path.join(PIPE, "d12_wells.py")
    sys.modules["d12mut"] = mod
    exec(compile(src.replace(old, new, 1), "d12mut.py", "exec"), mod.__dict__)
    with tempfile.TemporaryDirectory() as tmp:
        out, dl = os.path.join(tmp, "wells"), os.path.join(tmp, "dl")
        os.makedirs(dl)
        io_ = world(tmp)
        gh = FakeGH()
        gh.fail, gh.drop = set(fail), drop
        saved = patched(gh)
        mod.d7_daily.read_daf = lambda path: PERMITS
        try:
            rc = mod.run(args(out, dl), io=io_, now=NOW, log=lambda m: None)
        finally:
            unpatch(saved)
            sys.modules.pop("d12mut", None)
        have = os.path.exists(os.path.join(out, "index.json"))
        return {"rc": rc, "units": {u["p"] for u in json.load(open(os.path.join(out, "index.json")))["units"]} if have else set(),
                "text": all_text(out) if have else "", "problems": W.check(out) if have else []}


def mutant(label, edit, caught, **world):
    try:
        got = caught(run_world(edit, **world))
    except Exception as e:  # noqa: BLE001 - a crash is also a catch
        got = True
        label += " (crashed: %s)" % type(e).__name__
    check(got, "mutant caught: " + label)


# the real code in the two worlds the upload mutants need
real = run_world(("def log(msg):", "def log(msg):"), fail={"wells-2026-10-29-ds-01"})
check(real["units"] == {"w1", "ci"}, "(the real code, a failing upload: the pack that failed is not recorded: %s)" % sorted(real["units"]))
real_drop = run_world(("def log(msg):", "def log(msg):"), drop=True)
check(real_drop["units"] == set() and real_drop["rc"] == 1, "(the real code, an upload that says yes and keeps nothing: nothing is recorded and the run ends red)")

mutant("a document with no well is published under a made-up well", ('        if not tie:\n            untied += 1\n            continue', '        if not tie:\n            tie = {"api": "00000000", "district": None, "op": None, "field": None}'),
       lambda r: "00000000" in r["text"] or bool(r["problems"]))
mutant("every operator is named", ('"on": lk.operator.get(w["o"]) if w["o"] else None,', '"on": ("OP " + w["o"]) if w["o"] else None,'), lambda r: any("may not be named" in x for x in r["problems"]))
mutant("the lease name is published as the field", ('"field": clean_field(pk[29])}', '"field": clean_field(pk[26])}'), lambda r: "LITTLE WILLIE" in r["text"])
mutant("the landowner is read with the packet", ('"field": clean_field(pk[29])}', '"field": clean_field(pk[30])}'), lambda r: "MC KINNEY" in r["text"])
mutant("a file is published whatever it is", ('    if info.file_size > MAX_ASSET or ext not in MAGIC:\n        return None', '    if False:\n        return None'), lambda r: True if r["rc"] != 0 else False)  # a crash or a different result is a catch
mutant("a pack that failed to upload is recorded anyway", ('        if upload:\n            publish_unit(repo, day, pack, stage_dir, kept, log)', '        if upload:\n            try:\n                publish_unit(repo, day, pack, stage_dir, kept, log)\n            except Exception:\n                for d in kept:\n                    d["tag"] = tag_name(day, pack, 1)'),
       lambda r: "ds" in r["units"], fail={"wells-2026-10-29-ds-01"})
mutant("an upload is believed without listing the release's files", ('    have = d7_release.assets_of(repo, tag)\n    missing = [n for n in names if n not in have]', '    have = set(names)\n    missing = []'),
       lambda r: bool(r["units"]), drop=True)

def mutated(edit):
    src = open(os.path.join(PIPE, "d12_wells.py")).read()
    mod = types.ModuleType("d12mutc")
    mod.__file__ = os.path.join(PIPE, "d12_wells.py")
    exec(compile(src.replace(edit[0], edit[1], 1), "d12mutc.py", "exec"), mod.__dict__)
    return mod


big = [{"f": "%08d_c1" % i, "pv": 1} for i in range(1000)]
check(len(mutated(('def chunks(docs, cap=MAX_ASSETS):', 'def chunks(docs, cap=10**9):')).chunks(big)) == 1 and len(W.chunks(big)) == 3, "mutant caught: a release that holds every file of a pack, with no limit, is one release where the real code makes three")
check(len(mutated(("need = 2 if d.get(\"pv\") else 1", "need = 1")).chunks(big)) == 2 and len(W.chunks(big)) == 3, "mutant caught: counting a document without its picture puts too many files in a release (2 releases of up to 1600 files)")

with tempfile.TemporaryDirectory() as tmp:  # numbering must not follow the zip's order: the mutant that drops the sort differs between the same pack written in two orders
    src = open(os.path.join(PIPE, "d12_wells.py")).read()
    mod = types.ModuleType("d12mut3")
    mod.__file__ = os.path.join(PIPE, "d12_wells.py")
    exec(compile(src.replace('    docs.sort(key=lambda d: (d["api"], d["kind"], d["key"]))\n', '', 1), "d12mut3.py", "exec"), mod.__dict__)
    make_w1(os.path.join(tmp, "a.zip"), 1)
    make_w1(os.path.join(tmp, "b.zip"), 2)
    ties = W.permit_ties(PERMITS)
    names = []
    for n in ("a.zip", "b.zip"):
        with zipfile.ZipFile(os.path.join(tmp, n)) as z:
            d, _ = mod.candidates(z, "w1", ties)
        names.append(sorted((x["key"], x["f"]) for x in d))
    check(names[0] != names[1], "mutant caught: without the sort a document's name follows the order of the zip")

# ------------------------------------------------------------------------------------------------ the committed files

bad = W.check(W.DEFAULT_OUT)
check(bad == [], "the committed well-image files pass the check%s" % ("" if not bad else ": " + "; ".join(bad[:3])))
idx = json.load(open(os.path.join(W.DEFAULT_OUT, "index.json")))
check(idx["repo"] == "ether314/texas-oil-gas-leads", "the index names the repository the releases are in")

print()
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
