"""Tests for site/pipeline/d11_nat_ut.py: Utah's approved APDs from the Division's WellHistory.zip and Wells.zip.

The fixtures are invented rows written the way the real files have them (the real header lines, MM/DD/YYYY dates, the text NULL for a missing value, a 14-digit API number in the well file and
its first ten digits in the history file); no real well, operator, lease or person is in them. The network is faked. What is pinned: the parser, the bands and fluids from the Division's own
codes (a service well is `inj`, a deepening or re-entry `redrill`, a potash well `other`), dates (a day before 2000 is history, a damaged one is counted and fails the run), the join to the well file
(by sidetrack first), a repeated row counted once, a month with no approvals inside the series a real zero, a person or a dba never named, nothing but counts in the output, and every way a damaged
or short file must fail the run instead of writing a short file.

Run: python3 -I tests/test_d11_ut.py"""
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_ut as UT  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, *exc):
    try:
        fn()
    except exc or (Exception,) as e:
        return str(e) or e.__class__.__name__
    return None


# ------------------------------------------------------------------------------------------------ fixtures (invented)
HIST_HEADER = ("WellID,SideTrack,WorkType,Slant,APDNumber,APDReceivedDate,APDReturnDate,APDApprovedDate,APDExtDate,APDRescindDate,DrySpud,RotarySpud,WCRCompletionDate,SundryIntentReceivedDate,"
               "SundryIntentAcceptedDate,SundryIntentApprovedDate,SundryIntentCancelledDate,SundrySubsequentReceivedDate,SundryCompletionDate,WellStatusReport,WellTypeReport,FirstProdDate,TestDate,"
               "ProductionMethod,Choke64th,TubingPressure,CasingPressure,OilRate,GasRate,WaterRate,OilGravity,BTU,Cored,DST,DirSurveyRun,CompletionType,MD,TVD,PBMD,PBTVD,CurrentWellStatus,"
               "CurrentWellType,Confidential").split(",")
WELL_HEADER = ("WellName,API,Operator,OperatorNo,FieldName,Ground_Elev,Kelly_Elev,Floor_Elev,FootageNS,NS,FootageEW,EW,UTM_Surf_N,UTM_Surf_E,Latitude,Longitude,QuarterQuarter,Sec,Township,"
               "TownshipDir,Range,RangeDir,PM,CountyName,Dir_Horiz,Dir_Vert,Dir_Direct,Confidential,ConfRelDate,LeaseNumber,LeaseType,SurfaceOwner,AbandonDate,wellstatus,welltype,TotCum_Oil,"
               "TotCum_Gas,TotCum_Water,Ind_Tribe,Multi_Lats,OriginalFieldType,UnitName,ProposedMD,ProposedTVD,FirstProdDate").split(",")
assert len(HIST_HEADER) == 43 and len(WELL_HEADER) == 45


def hist_row(well, work="DRILL", apd="NULL", approved="NULL", wtype="OW", side="0", **extra):
    r = {h: "NULL" for h in HIST_HEADER}
    r.update(WellID=well, SideTrack=side, WorkType=work, APDNumber=apd, APDApprovedDate=approved, CurrentWellType=wtype, Slant="VERTICAL", Confidential="")
    r.update(extra)
    return ",".join(r[h] for h in HIST_HEADER)


def well_row(api, operator, county, name="Sample Fed 1-1", wtype="OW"):
    r = {h: "NULL" for h in WELL_HEADER}
    r.update(WellName='"%s"' % name, API=api, Operator='"%s"' % operator, CountyName=county, welltype=wtype, LeaseNumber="UTU-00000", wellstatus="APD")
    return ",".join(r[h] for h in WELL_HEADER)


def make_zip(member, header, rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, ",".join(header) + "\n" + "\n".join(rows) + "\n")
    return buf.getvalue()


OPS = ["Acme Drilling LLC", "Example Energy Corporation", "Pat Q Sample", "Jane Roe dba Roe Oil"]
COUNTIES = ["UINTAH", "DUCHESNE", "SAN JUAN"]


def months_through(last):
    return C.month_list("2019-01", last)


def fixture(through="2026-10", last_day=20, skip=(), well_prefix="43", breaks=None):
    """History and well rows: three DRILL approvals every month, a few extras in 2026-05. Returns (history rows, well rows, the expected operator of each well)."""
    hist, wells = [], []
    k = 0
    for ym in months_through(through):
        if ym in skip:
            continue
        for j in range(3):
            well = "%s9%07d" % (well_prefix, k)
            day = min(1 + (k * 7) % 27, last_day if ym == through else 28)
            approved = "%02d/%02d/%s" % (int(ym[5:]), day, ym[:4])
            wtype = ("OW", "GW", "OGW")[j]
            hist.append(hist_row(well, "DRILL", apd="99%06d" % k, approved=approved, wtype=wtype))
            wells.append(well_row("43" + "9%07d" % k + "0000", OPS[k % 4], COUNTIES[k % 3], name="Sample Fed %d-1" % k, wtype=wtype))
            k += 1
    # the extras: a disposal well, a deepening, a potash well, all approved in May 2026
    for n, (work, wtype) in enumerate((("DRILL", "WD"), ("DEEPEN", "OW"), ("DRILL", "PO"))):
        well = "%s9%07d" % (well_prefix, k)
        hist.append(hist_row(well, work, apd="98%06d" % k, approved="05/1%d/2026" % n, wtype=wtype))
        wells.append(well_row("43" + "9%07d" % k + "0000", OPS[0], "UINTAH", wtype=wtype))
        k += 1
    # not permits to drill: a recompletion (a sundry notice) and a plugging, with an approval date by accident; an old approval; an APD never approved
    hist.append(hist_row("4399999901", "RECOMP", approved="06/01/2025", wtype="OW"))
    hist.append(hist_row("4399999902", "PLUG", approved="06/02/2025", wtype="OW"))
    hist.append(hist_row("4399999903", "DRILL", apd="97000001", approved="05/20/1965", wtype="OW"))
    hist.append(hist_row("4399999904", "DRILL", apd="97000002", approved="NULL", wtype="OW"))
    return hist, wells


def zips(hist, wells):
    return make_zip("WellHistory.csv", HIST_HEADER, hist), make_zip("Wells.csv", WELL_HEADER, wells)


class Net:
    def __init__(self, hist_zip, wells_zip):
        self.z = {UT.HISTORY_URL: hist_zip, UT.WELLS_URL: wells_zip}
        self.asked = []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_bytes")))
        return self.z[url]


# the floors are the real files' (50,000 rows); the fixture is small, so the happy-path tests lower them and the failure tests put them back
REAL = (UT.MIN_HIST, UT.MIN_WELLS, UT.MIN_APPROVALS)


def small_floors():
    UT.MIN_HIST, UT.MIN_WELLS, UT.MIN_APPROVALS = 100, 50, 100


def real_floors():
    UT.MIN_HIST, UT.MIN_WELLS, UT.MIN_APPROVALS = REAL


# ------------------------------------------------------------------------------------------------ the reader
hz, wz = zips(*fixture())
rows = UT.read_table(hz, "WellHistory.csv", UT.HIST_COLS)
check(set(rows[0]) == set(UT.HIST_COLS) and rows[0]["WorkType"] == "DRILL" and rows[0]["WellID"].startswith("43"), "the reader keeps only the columns it needs (no lease, name or coordinate is ever held)")
check(rows[0]["APDNumber"] != "NULL" and rows[-1]["APDApprovedDate"] == "" and rows[-1]["APDNumber"] == "97000002", "the text NULL becomes a blank")
check(raises(lambda: UT.read_table(b"<html>503 Service Unavailable</html>", "WellHistory.csv", UT.HIST_COLS), ValueError), "a reply that is not a zip (an error page) is refused")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("a.csv", "WellID\n1\n")
    z.writestr("b.csv", "WellID\n2\n")
check(raises(lambda: UT.read_table(buf.getvalue(), "x", ("WellID",)), ValueError), "a zip with two CSVs is refused, not guessed at")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("readme.txt", "hello")
check(raises(lambda: UT.read_table(buf.getvalue(), "x", ("WellID",)), ValueError), "a zip with no CSV is refused")
renamed = make_zip("WellHistory.csv", [("ApprovedDate" if h == "APDApprovedDate" else h) for h in HIST_HEADER], [])
msg = raises(lambda: UT.read_table(renamed, "WellHistory.csv", UT.HIST_COLS), ValueError)
check(msg and "APDApprovedDate" in msg and "layout" in msg, "a renamed column fails loudly and says which: %s" % msg)
ragged = make_zip("WellHistory.csv", HIST_HEADER, ["4399900001,0,DRILL"] * 20 + [hist_row("4399900002")] * 100)
check(raises(lambda: UT.read_table(ragged, "WellHistory.csv", UT.HIST_COLS), ValueError), "rows that do not have the header's width (a re-laid-out file) fail the run")
tail = make_zip("WellHistory.csv", HIST_HEADER, [hist_row("4399900002")] * 100 + ["4399900001,0"])
check(len(UT.read_table(tail, "WellHistory.csv", UT.HIST_COLS)) == 100, "one cut-off last row is dropped, not fatal")
was = UT.MAX_UNZIPPED
UT.MAX_UNZIPPED = 1000
check(raises(lambda: UT.read_table(hz, "WellHistory.csv", UT.HIST_COLS), ValueError), "a CSV larger than the cap is not opened")
UT.MAX_UNZIPPED = was
check(UT.read_table(make_zip("W.csv", HIST_HEADER, []), "WellHistory.csv", UT.HIST_COLS) == [], "a header-only file reads as no rows (the row floor then refuses it)")

# ------------------------------------------------------------------------------------------------ dates
check(UT.approved_day("", TODAY) == (None, False), "a blank is no approval")
check(UT.approved_day("05/20/1965", TODAY) == (None, False) and UT.approved_day("11/02/1999", TODAY) == (None, False), "a day before 2000 is history this report does not show, not a stray")
check(UT.approved_day("10/29/2026", TODAY) == (date(2026, 10, 29), False) and UT.approved_day("1/5/2019", TODAY) == (date(2019, 1, 5), False), "MM/DD/YYYY, with or without zeros")
check(UT.approved_day("11/05/2026", TODAY) == (None, True), "an approval after today is a stray")
check(UT.approved_day("10/04/2107", TODAY) == (None, True) and UT.approved_day("13/45/2026", TODAY) == (None, True) and UT.approved_day("2026-10-04", TODAY) == (None, True) and UT.approved_day("soon", TODAY) == (None, True),
      "a year 2107, an impossible day, an ISO date (another layout) and text are strays")

# ------------------------------------------------------------------------------------------------ the bands and fluids, in the Division's own words
CASES = [("DRILL", "OW", ("new", "oil")), ("DRILL", "GW", ("new", "gas")), ("DRILL", "OGW", ("new", "both")), ("DRILL", "D", ("new", None)), ("DRILL", "", ("new", None)), ("DRILL", "NA", ("new", None)),
         ("DRILL", "WD", ("inj", "other")), ("DRILL", "WI", ("inj", "other")), ("DRILL", "GI", ("inj", "other")), ("DRILL", "GS", ("inj", "other")), ("DRILL", "WS", ("inj", "other")),
         ("DRILL", "TW", ("inj", "other")), ("DRILL", "OWD", ("inj", "other")), ("DEEPEN", "OW", ("redrill", "oil")), ("REENTER", "GW", ("redrill", "gas")), ("DEEPEN", "WD", ("redrill", "other")),
         ("DRILL", "PO", ("other", None)), ("DRILL", "LI", ("other", None)), ("DRILL", "HE", ("other", None)), ("DRILL", "CD", ("other", None)), ("WHATEVER", "OW", ("other", None))]
for work, wt, want in CASES:
    check(UT.classify(work, wt) == want, "%s of a %r well is %s" % (work, wt, want))

# ------------------------------------------------------------------------------------------------ the join to the well file
wr = [{"API": "43999000010000", "Operator": "First LLC", "CountyName": "UINTAH", "welltype": "OW"}, {"API": "43999000010100", "Operator": "Second LLC", "CountyName": "UINTAH", "welltype": "OW"},
      {"API": "4399900002", "Operator": "Short Api Inc", "CountyName": "DUCHESNE", "welltype": "GW"}, {"API": "bad", "Operator": "X", "CountyName": "Y", "welltype": ""}]
ix = UT.well_index(wr)
check(UT.find_well(ix, "4399900001", "0")["Operator"] == "First LLC" and UT.find_well(ix, "4399900001", "1")["Operator"] == "Second LLC", "a well is found by its sidetrack first (the operator of sidetrack 1 is not sidetrack 0's)")
check(UT.find_well(ix, "4399900001", "7")["Operator"] == "First LLC" and UT.find_well(ix, "4399900002", "0")["Operator"] == "Short Api Inc" and UT.find_well(ix, "4399900003", "0") is None, "an unknown sidetrack falls back to the ten digits; a well not in the file is None")

# ------------------------------------------------------------------------------------------------ the whole run, network faked
small_floors()
hist, wells = fixture()
net = Net(*zips(hist, wells))
doc = UT.build(get=net.get, pause=0, today=TODAY)
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(doc["state"] == "UT" and doc["measure"] == "permits" and doc["basis"].startswith("approval date") and doc["cadence"] == "daily" and doc["unit"] == "APDs approved", "Utah counts APDs approved, by approval date")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-20", "2019 to the newest complete month; October (to the 20th) is not shown, and asOf is the newest approval")
check(all(v == 3 for i, v in enumerate(doc["bands"]["new"]) if doc["months"][i] != "2026-05"), "three new-well approvals every month")
mi = doc["months"].index("2026-05")
check(doc["bands"]["new"][mi] == 3 and doc["bands"]["inj"][mi] == 1 and doc["bands"]["redrill"][mi] == 1 and doc["bands"]["other"][mi] == 1, "May 2026: the disposal well is inj, the deepening redrill, the potash well other, none of them new")
check(sum(doc["bands"]["inj"]) == 1 and sum(doc["bands"]["redrill"]) == 1 and sum(doc["bands"]["other"]) == 1, "and nothing else is in those bands: the recompletion, the plugging, the 1965 approval and the APD never approved are not counted")
check(doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "recompletions and amendments are not available (null), never zero")
total = sum(sum(v) for v in doc["bands"].values() if v)
check(total == 3 * 93 + 3 and doc["read"] == 3 * 94 + 3, "every approval from 2019 on is read once (the October ones too): %d, %d" % (total, doc["read"]))
check(doc["fluid"] == {"oil": 12, "gas": 12, "both": 12, "other": 0, "unknown": 0}, "fluid of the last 12 months: oil, gas and both from the well type: %s" % doc["fluid"])
check({c[0] for c in doc["counties"]} == {"Uintah", "Duchesne", "San Juan"} and sum(c[1] for c in doc["counties"]) == 36, "the counties come from the well file")
names = [o[0] for o in doc["operators"]]
check(sorted(names) == ["ACME DRILLING LLC", "EXAMPLE ENERGY CORPORATION"], "only the corporation and the LLC are named: %s" % names)
check(doc["namedShare"] == 0.5, "half the permits' operators are a person or a dba and are not named: namedShare %s" % doc["namedShare"])
text = json.dumps(doc)
check("PAT Q" not in text.upper() and "ROE OIL" not in text.upper() and "JANE" not in text.upper(), "a person's name and a dba never reach the file")
check("Sample Fed" not in text and "UTU-" not in text and "439900" not in text and "9900000" not in text, "no well name, lease, API number or APD number reaches the file")
check([u for u, _ in net.asked] == [UT.HISTORY_URL, UT.WELLS_URL] and all(m and m <= 30_000_000 for _, m in net.asked), "two requests, each with a size cap")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("UT", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "UT.json")) and C.check_dir(tmp) == [], "run_producer writes nat/UT.json and it reloads clean")

# a month with no approvals inside the series is a real zero; a later newest day brings October in
d2 = UT.build(get=Net(*zips(*fixture(skip=("2020-03",)))).get, pause=0, today=TODAY)
check(d2["bands"]["new"][d2["months"].index("2020-03")] == 0 and d2["bands"]["new"][d2["months"].index("2020-02")] == 3, "a month with no approval inside the series is a zero (real), not a gap")
d3 = UT.build(get=Net(*zips(*fixture(last_day=28))).get, pause=0, today=TODAY)
check(d3["months"][-1] == "2026-09" and d3["through"] == "2026-09-30" and "2026-10-01" <= d3["asOf"] < "2026-10-31", "October is not shown while its newest approval is before the 31st (through %s, asOf %s)" % (d3["through"], d3["asOf"]))
hist4, wells4 = fixture(through="2026-10", last_day=28)
hist4.append(hist_row("4399999950", "DRILL", apd="96000001", approved="10/31/2026", wtype="GW"))
wells4.append(well_row("43999999500000", OPS[0], "UINTAH", wtype="GW"))
d4 = UT.build(get=Net(*zips(hist4, wells4)).get, pause=0, today=date(2026, 11, 2))
check(d4["months"][-1] == "2026-10" and d4["through"] == "2026-10-31" and d4["asOf"] == "2026-10-31", "an approval on the last day makes the month complete")

# a repeated row (the file has a row for each event of a piece of work) is one approval
h5, w5 = fixture()
h5.append(h5[-5])  # the same well, work type, APD number and day
h5.append(h5[len(h5) - 7])
d5 = UT.build(get=Net(*zips(h5, w5)).get, pause=0, today=TODAY)
check(d5["read"] == doc["read"] and d5["bands"]["new"] == doc["bands"]["new"], "a row repeated in the file is counted once")

# ------------------------------------------------------------------------------------------------ failures: the run fails, nothing short is written
def boom(**kw):
    h, w = kw.pop("fixture", None) or fixture()
    zh, zw = zips(h, w)
    zh, zw = kw.pop("hz", zh), kw.pop("wz", zw)
    return raises(lambda: UT.build(get=Net(zh, zw).get, pause=0, today=kw.pop("today", TODAY)), Exception)


check(boom(hz=b"<html>maintenance</html>"), "an error page in place of the history file fails the run")
check(boom(wz=b"<html>maintenance</html>"), "an error page in place of the well file fails the run")
renamed_w = make_zip("Wells.csv", [("County" if h == "CountyName" else h) for h in WELL_HEADER], ["x"])
msg = boom(wz=renamed_w)
check(msg and "CountyName" in msg, "a renamed county column fails the run and says which: %s" % msg)
check(boom(today=date(2027, 3, 1)), "a file whose newest approval is months old (it stopped being refreshed) fails the run")
h6, w6 = fixture()
h6 = [r.replace("/2026,", "/2026x,") if "/2026" in r else r for r in h6]
msg = boom(fixture=(h6, w6))
check(msg and "not real dates" in msg, "damaged approval dates fail the run: %s" % msg)
h7, w7 = fixture(well_prefix="43")
w7 = [r.replace('",439', '",449') for r in w7]  # the well file no longer matches the history's well ids
msg = boom(fixture=(h7, w7))
check(msg and "matched" in msg, "a well file that no longer joins (no county or operator for the new permits) fails the run: %s" % msg)
real_floors()
check("expected" in (boom() or ""), "with the real floors a 300-row file is refused as too short")
UT.MIN_HIST, UT.MIN_WELLS = 100, 50
msg = boom()
check(msg and "approvals since 2019" in msg, "too few approvals since 2019 fail the run: %s" % msg)
small_floors()
hf, wf = fixture()
hf = [r for r in hf if "/2025" not in r and "/2026" not in r]
check(boom(fixture=(hf, wf), today=TODAY), "a history that ends in 2024 fails the run")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("UT", lambda: UT.build(get=refused, pause=0), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing (an answer, not an error)")
    check(C.run_producer("UT", lambda: UT.build(get=Net(hz[:100], wz).get, pause=0, today=TODAY), tmp, argv=[]) == 1 and not os.listdir(tmp), "a cut-off download exits 1 and writes nothing")
real_floors()

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
