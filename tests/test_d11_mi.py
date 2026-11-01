"""Tests for site/pipeline/d11_nat_mi.py: Michigan's well permits (EGLE, Oil, Gas, and Minerals Division) from its open-data map service.

michigan.gov itself refuses this kind of caller, but EGLE's ArcGIS service (GrmdOpenData layer 10, one record per well bore, PermitDate in milliseconds since 1970) answers. Every record below is invented,
shaped the way the service sends them: attributes in a `features` list, dates as epoch milliseconds, well type codes LOC (permitted, not drilled), OIL, GAS, DH (dry hole), GS (gas storage), BDW (brine
disposal), GIW/WIW/COI/OTI (injection), MDW/MTW (Part 625 mineral wells), LHL (lost hole), a sidetrack number (0 for the original hole; 1 to 6 are sidetracks; 70 marks a mineral well) and a completion number
(90 on a lost hole). No real name, permit number or API number is in them. The tests pin: what each code is, that a sidetrack is not a new well and the mineral well's 70 is not a sidetrack, that a permit on two
records is counted once, the query (what is asked for, and what is not), paging, an error inside a 200 reply, a login or refusal, a lost field, a short or stale or odd answer failing loudly instead of writing a short
file, the privacy rule, and the whole producer with the network faked.

Run: python3 -I tests/test_d11_mi.py"""
import json
import os
import sys
import tempfile
import urllib.parse
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_mi as MI  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


TODAY = date(2026, 10, 31)
SEQ = [0]


def ms(day):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def rec(day="2024-03-05", code="OIL", side=0, comp=0, bore="WELLBORE", county="CALHOUN", company="Acme Oil Inc.", number=None):
    SEQ[0] += 1
    return {"OBJECTID": SEQ[0], "PermitNumber": number or "X%05d" % SEQ[0], "PermitDate": ms(day) if day else None, "well_type": code, "WellboreType": bore, "Sidetrack": side, "Completion": comp,
            "CountyName": county, "CompanyName": company}


def reply(recs, exceeded=False, fields=MI.FIELDS):
    return json.dumps({"displayFieldName": "CountyName", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields], "features": [{"attributes": r} for r in recs],
                       **({"exceededTransferLimit": True} if exceeded else {})}).encode()


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:  # noqa: BLE001
        return e


def lowered(**kw):
    old = {k: getattr(MI, k) for k in kw}
    for k, v in kw.items():
        setattr(MI, k, v)
    return lambda: [setattr(MI, k, v) for k, v in old.items()]


# ------------------------------------------------------------------------------------------------ what each record is
cl = MI.classify
check(cl(rec(code="OIL")) == ("new", "oil", True) and cl(rec(code="GAS")) == ("new", "gas", True), "an oil well and a gas well are new wells, with the fluid they produce")
check(cl(rec(code="LOC")) == ("new", None, True) and cl(rec(code="DH")) == ("new", None, True), "a location (permitted, not drilled) and a dry hole are new wells whose fluid is not known")
check(all(cl(rec(code=c))[0] == "inj" for c in ("BDW", "GIW", "WIW", "COI", "OTI", "GS", "MDW", "MTW")), "brine disposal, injection, gas storage and Part 625 wells are injection and service wells")
check(cl(rec(code="LHL", comp=90)) == ("other", None, True) and cl(rec(code="LHL"))[0] == "other", "a lost hole is other")
check(cl(rec(code="OIL", comp=1))[0] == "other", "a record with a completion number is a further completion, not a new well")
check(cl(rec(code="LOC", side=1))[0] == "redrill" and cl(rec(code="OIL", side=6))[0] == "redrill" and cl(rec(code="DH", side=2))[0] == "redrill", "a sidetrack bore (number 1 to 6) is a re-entry or sidetrack, whatever its type")
check(cl(rec(code="MDW", side=70, bore="MINERAL"))[0] == "inj" and cl(rec(code="MTW", side=70, bore="MINERAL"))[0] == "inj", "the mineral wells' code 70 is not a sidetrack")
check(cl(rec(code="LOC", bore="BRINE"))[0] == "inj" and cl(rec(code="LOC", bore="MINERAL"))[0] == "inj", "a location on a brine or mineral well bore is a service well")
check(cl(rec(code="ZZ")) == ("other", None, False) and cl(rec(code="")) == ("other", None, False) and cl(rec(code=None))[2] is False, "a code this producer does not have (or a blank one) is other and flagged unknown")
check(cl(rec(code="oil "))[0] == "new" and cl({"well_type": "OIL", "Sidetrack": None, "Completion": None})[0] == "new" and cl({"well_type": "OIL", "Sidetrack": "x"})[0] == "new", "case, blanks and junk numbers do not break it")
check(C.parse_day(ms("2026-10-07"), TODAY) == date(2026, 10, 7) and C.parse_day(1791331200000, TODAY) == date(2026, 10, 7), "the service's milliseconds are the permit's day")

# ------------------------------------------------------------------------------------------------ one permit once
a, b = rec(day="2026-07-17", code="LOC", side=1, number="P1"), rec(day="2026-07-17", code="LOC", side=2, number="P1")
c, d = rec(day="2025-04-10", code="DH", number="P2"), rec(day="2025-04-10", code="DH", number="P2")
e = rec(day="2024-01-01", code="OIL", number="")
f = rec(day="2024-01-01", code="OIL", number="")
g = rec(day="2024-05-01", code="OIL", number="P3")
h = rec(day="2024-06-01", code="OIL", number="P3")  # the same number on another day: two permits
once = MI.one_per_permit([a, b, c, d, e, f, g, h])
check(len(once) == 6, "two records with one permit number and day are one permit; records with no number each count; one number on two days is two permits (%d)" % len(once))
check(next(r for r in once if r["PermitNumber"] == "P1")["Sidetrack"] == 1, "the lowest sidetrack stands for a permit on two records")

# ------------------------------------------------------------------------------------------------ the query and paging
q = urllib.parse.parse_qs(urllib.parse.urlparse(MI.layer_url(4000)).query)
check(q["where"] == ["PermitDate >= DATE '2019-01-01'"] and q["returnGeometry"] == ["false"] and q["resultOffset"] == ["4000"] and q["orderByFields"] == ["OBJECTID"] and q["f"] == ["json"], "the query asks for permits since 2019, no geometry, in a stable order, from an offset")
asked = set(q["outFields"][0].split(","))
check(asked == set(MI.FIELDS) and not asked & {"api_num", "WellName", "WellNumber", "WellNameFull", "WellID", "CompanyNo", "X", "Y", "mgr_x", "mgr_y", "Shape", "TownshipName", "TRS"}, "it asks for no API number, well name, company number or location")
check(MI.layer_url(0).startswith("https://gisagoegle.state.mi.us/arcgis/rest/services/EGLE/GrmdOpenData/MapServer/10/query?"), "the service is EGLE's layer 10")

store = [rec(day="2024-%02d-%02d" % (1 + i % 12, 1 + i % 27)) for i in range(12)]
seen = []


def paged(url, **kw):
    seen.append(url)
    off = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["resultOffset"][0])
    chunk = store[off:off + MI.PAGE]
    return reply(chunk, exceeded=off + MI.PAGE < len(store))


restore = lowered(PAGE=5)
got = MI.fetch(paged, pause=0)
restore()
check(len(got) == 12 and len(seen) == 3 and got[0]["OBJECTID"] == store[0]["OBJECTID"] and got[-1]["OBJECTID"] == store[-1]["OBJECTID"], "records come back page by page until the service says there are no more (3 requests for 12 records of 5)")
seen.clear()
restore = lowered(PAGE=6)
got = MI.fetch(paged, pause=0)
restore()
check(len(got) == 12 and len(seen) == 3, "a last page that is exactly full still ends the run (an empty page after it)")
restore = lowered(PAGE=5, MAX_PAGES=2)
err = raises(MI.fetch, paged, 0)
restore()
check(isinstance(err, RuntimeError) and "pages" in str(err), "a service that never says it is done fails the run (the query may have lost its filter)")
check(MI.fetch(lambda url, **kw: reply([]), pause=0) == [], "an answer with no feature is an empty list, not an error")

# ------------------------------------------------------------------------------------------------ the service's failures
err = raises(MI.fetch, lambda url, **kw: json.dumps({"error": {"code": 400, "message": "Unable to complete operation.", "details": ["http://example.test/secret"]}}).encode(), 0)
check(isinstance(err, RuntimeError) and not isinstance(err, C.Refused) and "400" in str(err) and "example.test" not in str(err), "an error inside a 200 reply fails the run, without the service's text")
for code in (403, 499, 498):
    err = raises(MI.fetch, lambda url, code=code, **kw: json.dumps({"error": {"code": code, "message": "Token Required"}}).encode(), 0)
    check(isinstance(err, C.Refused), "a login or refusal inside a 200 reply (code %d) is a refusal, an answer, not an error" % code)
check(isinstance(raises(MI.fetch, lambda url, **kw: b"<html><body>Service unavailable</body></html>", 0), RuntimeError), "an error page instead of JSON fails the run")
check(isinstance(raises(MI.fetch, lambda url, **kw: b"[1, 2]", 0), RuntimeError) and isinstance(raises(MI.fetch, lambda url, **kw: b'{"features": "no"}', 0), RuntimeError), "an answer of the wrong shape fails the run")
err = raises(MI.fetch, lambda url, **kw: reply([rec()], fields=[f for f in MI.FIELDS if f != "PermitDate"]), 0)
check(isinstance(err, RuntimeError) and "PermitDate" in str(err), "a layer that lost a field fails the run and names it")

# ------------------------------------------------------------------------------------------------ the whole producer, with the network faked
# 94 months, January 2019 to October 2026, a known number of each kind every month
SEQ[0] = 0
recs, exp = [], {k: [] for k in ("new", "inj", "redrill", "other")}
for i, ym in enumerate(C.month_list("2019-01", "2026-10")):
    day = "%s-%02d" % (ym, 1 + i % 25)
    k = 1 + i % 3
    new = inj = red = oth = 0
    recs += [rec(day=day, code="OIL", company="Acme Oil Inc.", county="CALHOUN") for _ in range(k)]
    recs.append(rec(day=day, code="DH", company="Test Drilling LLC", county="KALAMAZOO"))
    recs.append(rec(day=day, code="LOC", company="Jane Q Example", county="CLARE"))
    new += k + 2
    if i % 2 == 0:
        recs.append(rec(day=day, code="LOC", side=1, company="Acme Oil Inc.", county="CALHOUN"))
        red += 1
    if i % 4 == 0:
        recs.append(rec(day=day, code="GS", company="Test Storage LLC", county="MACOMB"))
        inj += 1
    if i % 5 == 0:
        recs.append(rec(day=day, code="MDW", side=70, bore="MINERAL", company="Test Brine LLC", county="MANISTEE"))
        inj += 1
    if i % 6 == 0:
        recs.append(rec(day=day, code="LHL", comp=90, company="Acme Oil Inc."))
        oth += 1
    if i % 7 == 0:
        first = rec(day=day, code="OIL", company="Acme Oil Inc.", county="CALHOUN", number="DUP%d" % i)
        recs += [first, dict(first, OBJECTID=first["OBJECTID"] + 5000)]  # one permit on two records
        new += 1
    exp["new"].append(new), exp["inj"].append(inj), exp["redrill"].append(red), exp["other"].append(oth)
calls = []


def service(url, **kw):
    calls.append((url, kw))
    off = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["resultOffset"][0])
    return reply(recs[off:off + MI.PAGE], exceeded=off + MI.PAGE < len(recs))


restore = lowered(MIN_RECORDS=100)
doc = MI.build(get=service, today=TODAY, pause=0)
restore()
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(len(calls) == 1 and calls[0][1]["max_bytes"] == MI.MAX_BYTES and calls[0][0].startswith(MI.LAYER + "/query?"), "one request (the records fit one page) to the layer, with a size cap")
check(doc["state"] == "MI" and doc["measure"] == "permits" and "permit date" in doc["basis"], "measure is permits, counted by the permit date")
n = len(doc["months"])
newest = max(datetime.fromtimestamp(r["PermitDate"] / 1000, timezone.utc).date() for r in recs).isoformat()
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == newest, "months run from 2019-01 to the last complete month; asOf is the newest permit's day")
check(doc["bands"]["new"] == exp["new"][:n] and doc["bands"]["inj"] == exp["inj"][:n] and doc["bands"]["redrill"] == exp["redrill"][:n] and doc["bands"]["other"] == exp["other"][:n],
      "new, injection, re-entries and sidetracks and other come out month by month as invented (a duplicated permit once, a mineral well's 70 not a sidetrack)")
check(doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "reworks and amendments are null, never zero")
last = exp["new"][n - 12:n]
dups12 = sum(1 for i in range(n - 12, n) if i % 7 == 0)
oil12 = sum(1 + i % 3 for i in range(n - 12, n)) + dups12
check(sum(doc["fluid"].values()) == sum(last) and doc["fluid"]["oil"] == oil12 and doc["fluid"]["unknown"] == sum(last) - oil12, "the fluid is known for the oil wells; dry holes and locations are unknown (%s)" % doc["fluid"])
check([c[0] for c in doc["counties"]][:3] == ["Calhoun", "Clare", "Kalamazoo"] and doc["counties"][0][1] == oil12, "counties are the service's county names, ranked (Michigan's are upper case there)")
names = [o[0] for o in doc["operators"]]
check(names == ["ACME OIL INC.", "TEST DRILLING LLC"] and all(C.nameable(x) for x in names), "operators are corporations and LLCs only, and the person is not among them")
named = sum(o[1] for o in doc["operators"])
check(abs(doc["namedShare"] - round(named / sum(last), 3)) < 1e-9 and 0 < doc["namedShare"] < 1, "the named share is the named operators' count over the year's new permits (%s)" % doc["namedShare"])
text = json.dumps(doc)
check("Jane" not in text and "X0" not in text and "DUP" not in text and "Example" not in text, "no person's name and no permit number is in the file")
check("not available" in doc["note"] and "work type" in doc["note"] and "Re-entries and sidetracks" in doc["note"] and "not confirmed" in doc["note"], "the note says what cannot be told and that the permit date's meaning is not confirmed")
check(doc["read"] == sum(sum(v) for v in exp.values()), "read counts the permits of the series (%d)" % doc["read"])
with tempfile.TemporaryDirectory() as tmp:
    restore = lowered(MIN_RECORDS=100)
    rc = C.run_producer("MI", lambda: MI.build(get=service, today=TODAY, pause=0), tmp, argv=[])
    restore()
    check(rc == 0 and os.path.exists(os.path.join(tmp, "MI.json")) and C.check_dir(tmp) == [], "run_producer writes nat/MI.json and --check reads it clean")

# ------------------------------------------------------------------------------------------------ an answer that is not the answer fails the run, it never writes a short file
def build_with(records, **kw):
    return raises(MI.build, get=lambda url, **k: reply(records), today=kw.get("today", TODAY), pause=0)


def msg(e):
    return str(e) if e else ""


e = build_with(recs[:40])
check(isinstance(e, RuntimeError) and "expected about 420" in msg(e), "with the real floor, a short answer fails: %s" % msg(e)[:55])
restore = lowered(MIN_RECORDS=100)
junk = [dict(r, PermitDate="05/Nov/yesterday") if i % 20 == 0 else r for i, r in enumerate(recs)]
e = build_with(junk)
check(isinstance(e, RuntimeError) and "not dates" in msg(e), "permit dates that are not dates (a changed format) fail the run: %s" % msg(e)[:55])
fut = list(recs)
fut[5] = dict(fut[5], PermitDate=ms("2999-01-01"))
check(build_with(fut) is None, "one date in the future among hundreds is tolerated")
weird = [dict(r, well_type="ZZ", Sidetrack=0) if i % 3 == 0 else r for i, r in enumerate(recs)]
e = build_with(weird)
check(isinstance(e, RuntimeError) and "does not know" in msg(e), "a third of the records in codes unknown to it fails (the layer's vocabulary changed): %s" % msg(e)[:55])
old = [r for r in recs if datetime.fromtimestamp(r["PermitDate"] / 1000, timezone.utc).year < 2024]
e = build_with(old)
check(isinstance(e, RuntimeError) and "stale" in msg(e), "a layer whose newest permit is years old fails: %s" % msg(e)[:55])
nodate = [dict(r, PermitDate=None) for r in recs]
e = build_with(nodate)
check(isinstance(e, RuntimeError), "records with no date at all fail the run")
restore()

# the network: a refusal is an answer (exit 2), any other failure exits 1; neither writes or touches the committed file
def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


def dropped(url, **kw):
    raise RuntimeError("could not read the source: <urlopen error timed out>")


with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "MI.json")
    open(p, "w").write("committed\n")
    check(C.run_producer("MI", lambda: MI.build(get=refuse, pause=0), tmp, argv=[]) == 2 and open(p).read() == "committed\n", "a refusing server exits 2 and leaves the committed file alone")
    check(C.run_producer("MI", lambda: MI.build(get=dropped, pause=0), tmp, argv=[]) == 1 and open(p).read() == "committed\n", "a dropped connection exits 1 and leaves the committed file alone")
    check(C.run_producer("MI", lambda: MI.build(get=lambda url, **kw: b"<html>maintenance</html>", pause=0), tmp, argv=[]) == 1 and open(p).read() == "committed\n", "an error page exits 1 and leaves the committed file alone")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
