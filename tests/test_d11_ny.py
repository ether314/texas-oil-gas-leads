"""Tests for site/pipeline/d11_nat_ny.py: New York's permits (NYSDEC, Division of Mineral Resources) from the one free well file, wellDOS.zip.

Every row below is invented, written the way the real file has them: the DEC's 55 column names in its mixed case, dates as 'YYYY-MM-DD 00:00:00' (some with nine decimals), type codes from its own dictionary
(OD oil development, GW gas wildcat, BR brine, ST storage, NL not listed...), API numbers of 14 digits, latin-1 text. No real name, API number or lease is in it. The tests pin: what each type code is
(a new well with its fluid, a service well, other), that a sidetrack or a further completion of a hole is not a new well, that the application's type wins and "not listed" falls back to the current type,
dates, the privacy rule (a person's name is never published as an operator, a well's name and API number never reach the file), the zip handling (size checks), a damaged, short, renamed-column or stale file
failing loudly instead of writing a short file, the whole producer with the network faked, and that what it writes validates.

Run: python3 -I tests/test_d11_ny.py"""
import csv
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
import d11_nat_ny as NY  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# the real file's header, in its own case
HEADER = ["API_WellNo", "Cnty", "Hole", "SideTrck", "Completion", "Well_Name", "Company_name", "Operator_number", "Well_Type", "Map_Symbol", "Well_Status", "Date_Status", "Date_Permit_Application",
          "Permit_Issued", "Date_Spudded", "Date_Total_Depth", "Date_Well_Completed", "Date_well_plugged", "Date_well_confidential", "confid", "town", "quad", "quadsec", "Producing_name",
          "Producing_formation", "Financial_security", "Slant", "County", "Region", "State_lease", "Proposed_depth", "Surface_location", "Surface_Longitude", "Surface_latitude",
          "Bottom_hole_location", "Bottom_hole_longitude", "Bottom_hole_latitude", "True_vertical_depth", "Measured_depth", "Kickoff", "DrilledDepth", "Elevation", "Original_well_type",
          "Permit_Fee", "Objective_formation", "Depth_Fee", "Spacing", "Spacing_Acres", "Integration", "Dt_Hearing", "Dt_Mod", "LINK", "Location_Verified", "GeneralWellType", "GeneralWellStatus"]
check(len(HEADER) == 55, "the fixture's header has the real file's 55 columns")

SEQ = [0]
WELL_NAME = "Smithers J 1"  # invented, in the DEC's "last name first initial" style: must never reach the output
API_PREFIX = "3199"  # an API number in the fixture is 14 digits starting here: no real one


def row(issued="2024-03-05 00:00:00", orig="OD", cur=None, county="Cattaraugus", company="Acme Oil Inc.", side="0", comp="0", mod="2026-10-29 06:00:00.000000000", **kw):
    SEQ[0] += 1
    r = {h: "" for h in HEADER}
    r.update({"API_WellNo": "%s%010d" % (API_PREFIX, SEQ[0]), "Well_Name": WELL_NAME, "Company_name": company, "Original_well_type": orig, "Well_Type": orig if cur is None else cur,
             "Permit_Issued": issued, "Date_Permit_Application": "2024-02-01 00:00:00", "County": county, "SideTrck": side, "Completion": comp, "Dt_Mod": mod, "Slant": "Vertical"})
    r.update(kw)
    return r


def csv_of(rows, header=HEADER, encoding="latin-1"):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") for h in header])
    return buf.getvalue().encode(encoding)


def zip_of(body, name="wellspublic.csv", extra=True):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, body)
        if extra:
            z.writestr("OilandGasMetadata.html", "<html><body>documentation</body></html>")
    return out.getvalue()


def lowered(**kw):
    """Sets the module's floors for a small fixture; returns a function that puts them back."""
    old = {k: getattr(NY, k) for k in kw}
    for k, v in kw.items():
        setattr(NY, k, v)
    return lambda: [setattr(NY, k, v) for k, v in old.items()]


TODAY = date(2026, 10, 31)

# ------------------------------------------------------------------------------------------------ the type codes, in the DEC's own words
cl = NY.classify
check(cl("OD", "OD") == ("new", "oil", True) and cl("OE", "OE")[:2] == ("new", "oil") and cl("OW", "OW")[:2] == ("new", "oil"), "oil development, extension and wildcat are new wells that produce oil")
check(cl("GD", "GD")[:2] == ("new", "gas") and cl("GE", "GE")[:2] == ("new", "gas") and cl("GW", "GW")[:2] == ("new", "gas"), "gas development, extension and wildcat are new wells that produce gas")
check(all(cl(c, c)[0] == "inj" for c in ("BR", "DS", "IW", "IG", "ST", "LP", "MB", "MM", "MS", "TH")), "brine, disposal, injection, storage, monitoring and geothermal wells are injection and service wells")
check(cl("SG", "SG") == ("other", None, True), "a stratigraphic test well is neither a producer nor a service well: other")
check(cl("DH", "DH")[0] == "new" and cl("DW", "DW")[0] == "new", "a dry hole or dry wildcat (the application said it would drill) is a new well")
check(cl("NL", "OD") == ("new", "oil", True) and cl("", "GD")[:2] == ("new", "gas") and cl("UN", "BR")[0] == "inj", "'not listed' on the application falls back to the well's current type")
check(cl("OD", "BR")[0] == "new", "the type on the application wins over the current type")
check(cl("NL", "NL") == ("other", None, True) and cl("", "") == ("other", None, True) and cl("NL", "Confidential") == ("other", None, True), "no type anywhere (or a redacted one) is other, and not an unknown code")
check(cl("ZZ", "ZZ") == ("other", None, False), "a code the dictionary does not have is other and flagged unknown")
check(cl("OD", "OD", "1", "0")[0] == "redrill" and cl("BR", "BR", "2", "0")[0] == "redrill" and cl("OD", "OD", "1", "3")[0] == "redrill", "a sidetrack bore (its own permit) is a re-entry or sidetrack, whatever its type")
check(cl("OD", "OD", "0", "2")[0] == "other" and cl("MS", "MS", "0", "1")[0] == "other", "a further completion of an existing hole is not a new well, and is not claimed as a rework: other")
check(cl("OD", "OD", "", "") [0] == "new" and cl("OD", "OD", "x", "00")[0] == "new", "blank or junk sidetrack and completion codes mean none")

# ------------------------------------------------------------------------------------------------ reading the file
rows = [row(), row(orig="GW", company="Gasco Partners LP", county="Steuben", issued="2024-03-06"), row(company="Jane Q Example", issued="2024-03-07"),
        row(issued="2024-04-01 00:00:00.000000000", orig="BR"), row(issued="", orig="OD"), row(issued="1987-05-06 00:00:00"), row(issued="2026-10-27 00:00:00")]
body = csv_of(rows)
got = list(NY.read_rows(body))
check(len(got) == 7 and set(got[0]) == set(NY.NEEDED), "every row is read, and only the needed columns are kept (the well's name, API number and location are not)")
check("Well_Name" not in got[0] and "API_WellNo" not in got[0] and WELL_NAME not in json.dumps(got), "the well name and the API number are not in what the reader returns")
up = csv_of(rows, header=[h.upper() for h in HEADER])
check(len(list(NY.read_rows(up))) == 7, "columns are matched without regard to case (the file's names are mixed case, its dictionary's upper case)")
cafe = csv_of([row(company="Café Energy LLC")], encoding="latin-1")
check(list(NY.read_rows(cafe))[0]["Company_name"] == "Café Energy LLC" and list(NY.read_rows(cafe.decode("latin-1").encode("utf-8")))[0]["Company_name"] == "Café Energy LLC",
      "latin-1 text and UTF-8 text both read (a name with an accent)")
ragged = body + b"31990000000001,009\r\n"
check(len(list(NY.read_rows(ragged))) == 8, "a short row is read with blanks, not an error")


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:  # noqa: BLE001
        return e


def gen(fn, *a):
    return raises(lambda: list(fn(*a)))


e = gen(NY.read_rows, csv_of(rows, header=[h for h in HEADER if h != "Permit_Issued"]))
check(isinstance(e, RuntimeError) and "Permit_Issued" in str(e), "a renamed or missing column raises and names it")
check(isinstance(gen(NY.read_rows, b""), RuntimeError), "an empty file raises")
check(isinstance(gen(NY.read_rows, b"<html><body>Service unavailable</body></html>"), RuntimeError), "an error page instead of the file raises (no such columns)")

# ------------------------------------------------------------------------------------------------ the zip
check(NY.csv_bytes(zip_of(body)) == body, "the member is found by name in the zip and read in memory")
check(NY.csv_bytes(zip_of(body, name="data/WellsPublic.CSV")) == body, "a folder or a different case in the member's name does not matter")
check(isinstance(raises(NY.csv_bytes, b"<html>not a zip</html>"), RuntimeError), "a download that is not a zip raises")
check(isinstance(raises(NY.csv_bytes, zip_of(body, name="other.csv")), RuntimeError), "a zip without wellspublic.csv raises")
two = io.BytesIO()
with zipfile.ZipFile(two, "w") as z:
    z.writestr("a/wellspublic.csv", body)
    z.writestr("b/wellspublic.csv", body)
check(isinstance(raises(NY.csv_bytes, two.getvalue()), RuntimeError), "a zip with two of them raises (which one is the file?)")
restore = lowered(MAX_CSV=len(body) - 1)
e = raises(NY.csv_bytes, zip_of(body))
restore()
check(isinstance(e, RuntimeError) and "larger" in str(e), "a member larger than the cap is refused before it is read")

# ------------------------------------------------------------------------------------------------ the tally: counts, dates, bands, privacy
restore = lowered(MIN_ROWS=1, MIN_DATED=1, MIN_SERIES=1)
t, st = NY.tally_rows(NY.read_rows(body), TODAY)
restore()
check(st["rows"] == 7 and st["dated"] == 6 and st["series"] == 5, "7 rows, 6 with an issue date, 5 of them issued from 2019 on (a 1987 permit and a blank date are not in the series)")
check(C.parse_day("2999-01-01 00:00:00", TODAY) is None and C.parse_day("2024-03-05 00:00:00.000000000", TODAY) == date(2024, 3, 5), "a date in the future is not a date; nine decimals after the time are fine")
check(t.m["new"]["2024-03"] == 3 and t.m["inj"]["2024-04"] == 1 and t.m["new"]["2026-10"] == 1 and t.read == 5, "the permits are counted by the month of their issue date (a date with nine decimals reads)")
check(t.oper["2024-03"]["ACME OIL INC."] == 1 and t.oper["2024-03"]["GASCO PARTNERS LP"] == 1 and sum(t.unnamed.values()) == 1, "a corporation and a partnership are named; a person is counted but unnamed")
check(t.county["2024-03"]["CATTARAUGUS"] == 2 and t.county["2024-03"]["STEUBEN"] == 1, "counties are the file's county names")
check(t.fl["2024-03"]["oil"] == 2 and t.fl["2024-03"]["gas"] == 1, "the fluid is the application's: two oil permits and one gas")
check(st["asof"] == date(2026, 10, 29), "asOf is the newest update in the file (the day a record was last modified), not the newest permit")

# ------------------------------------------------------------------------------------------------ the whole producer, with the network faked
# 94 months, January 2019 to October 2026, with a known number of each kind every month
SEQ[0] = 0
big = []
exp_new, exp_inj, exp_other, exp_red = [], [], [], []
for i, ym in enumerate(C.month_list("2019-01", "2026-10")):
    k = 2 + i % 3  # oil permits for Acme this month
    day = "%s-%02d 00:00:00" % (ym, 1 + i % 25)
    big += [row(issued=day, orig="OD") for _ in range(k)]
    big.append(row(issued=day, orig="GD", company="Gasco Partners LP", county="Steuben"))
    big.append(row(issued=day, orig="OD", company="Jane Q Example", county="Wyoming"))
    n_new = k + 2
    n_inj = n_other = n_red = 0
    if i % 3 == 0:
        big.append(row(issued=day, orig="BR", company="Test Brine New York LLC"))
        n_inj += 1
    if i % 6 == 0:
        big.append(row(issued=day, orig="SG", company="Rock Survey LLC"))
        n_other += 1
    if i % 12 == 0:
        big.append(row(issued=day, orig="OD", side="1"))  # a sidetrack: a re-entry or sidetrack, not new
        n_red += 1
        big.append(row(issued=day, orig="OD", comp="1"))  # a further completion: other, not new
        n_other += 1
    exp_new.append(n_new)
    exp_inj.append(n_inj)
    exp_other.append(n_other)
    exp_red.append(n_red)
big += [row(issued="", orig="OD") for _ in range(5)] + [row(issued="1970-01-02 00:00:00", orig="OD") for _ in range(5)]
BIG_ZIP = zip_of(csv_of(big))
restore = lowered(MIN_ROWS=100, MIN_DATED=100, MIN_SERIES=100)
calls = []
doc = NY.build(get=lambda url, **kw: calls.append((url, kw)) or BIG_ZIP, today=TODAY)
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(len(calls) == 1 and calls[0][0] == NY.URL and calls[0][1]["max_bytes"] == NY.MAX_ZIP, "one request, to the DEC's file, with a size cap")
check(doc["state"] == "NY" and doc["measure"] == "permits", "measure is permits (counted by the issue date)")
check("issue date" in doc["basis"] and doc["cadence"].startswith("nightly"), "the basis says issue date and the cadence is nightly")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-29", "months run from 2019-01 to the last complete month; asOf is the file's freshness")
n = len(doc["months"])
check(doc["bands"]["new"] == exp_new[:n] and doc["bands"]["inj"] == exp_inj[:n] and doc["bands"]["redrill"] == exp_red[:n] and doc["bands"]["other"] == exp_other[:n], "new, injection, re-entries and sidetracks and other come out month by month as invented")
check(doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "the bands the file cannot tell (reworks, amendments) are null, never zero")
last = exp_new[n - 12:n]
check(sum(doc["fluid"].values()) == sum(last) and doc["fluid"]["oil"] == sum(last) - 12 and doc["fluid"]["gas"] == 12, "the fluid split covers the last 12 months of new wells exactly (oil with the person's, gas for the partnership)")
check([c[0] for c in doc["counties"]] == ["Cattaraugus", "Steuben", "Wyoming"] and doc["counties"][1][1] == 12 and doc["counties"][2][1] == 12, "counties are ranked")
names = [o[0] for o in doc["operators"]]
check(names == ["ACME OIL INC.", "GASCO PARTNERS LP"] and all(C.nameable(x) for x in names), "operators are corporations and partnerships only, and the person is not among them")
named = sum(o[1] for o in doc["operators"])
check(abs(doc["namedShare"] - round(named / sum(last), 3)) < 1e-9, "and it is exactly the named operators' count over the year's new permits (%s)" % doc["namedShare"])
text = json.dumps(doc)
check("Jane" not in text and "Smithers" not in text and API_PREFIX not in text, "no person's name, well name or API number is anywhere in the file")
check("not available" in doc["note"] and "work type" in doc["note"] and "Re-entries and sidetracks" in doc["note"] and "Other filings" in doc["note"], "the note says what is not available, what counts as a sidetrack and what is under Other filings")
check(doc["read"] == sum(exp_new) + sum(exp_inj) + sum(exp_other) + sum(exp_red), "read counts the permits of the series (%d)" % doc["read"])
with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("NY", lambda: NY.build(get=lambda url, **kw: BIG_ZIP, today=TODAY), tmp, argv=[])
    p = os.path.join(tmp, "NY.json")
    check(rc == 0 and os.path.exists(p) and C.check_dir(tmp) == [], "run_producer writes nat/NY.json and --check reads it clean")

# ------------------------------------------------------------------------------------------------ files that are not the file fail the run, they never write a short file
def build_with(csv_rows, **kw):
    return raises(NY.build, get=lambda url, **k: zip_of(csv_of(csv_rows)), today=kw.get("today", TODAY))


def msg(e):
    return str(e) if e else ""


check(isinstance(build_with(big[:50]), RuntimeError), "a file with a few rows (the floors are the real ones again below) fails")
restore()
e = build_with(big[:50])
check(isinstance(e, RuntimeError) and "rows" in msg(e), "with the real floors back, a small file fails on its row count: %s" % msg(e)[:50])
restore = lowered(MIN_ROWS=100, MIN_DATED=100, MIN_SERIES=100)
check(isinstance(build_with(big[:50]), RuntimeError), "and with the fixture's floors, 50 rows are still too few")
no_dates = [dict(r, Permit_Issued="") for r in big]
e = build_with(no_dates)
check(isinstance(e, RuntimeError) and "issue date" in msg(e), "a file where no row has an issue date fails: %s" % msg(e)[:50])
junk = [dict(r, Permit_Issued="05/Nov/yesterday") if i % 20 == 0 else r for i, r in enumerate(big)]
e = build_with(junk)
check(isinstance(e, RuntimeError) and "not dates" in msg(e), "issue dates that do not parse (a changed format) fail the run: %s" % msg(e)[:50])
few_junk = list(big)
few_junk[3] = dict(few_junk[3], Permit_Issued="not a date")
check(build_with(few_junk) is None, "one odd date among hundreds is tolerated")
weird = [dict(r, Original_well_type="ZZ", Well_Type="ZZ") if i % 3 == 0 else r for i, r in enumerate(big)]
e = build_with(weird)
check(isinstance(e, RuntimeError) and "dictionary" in msg(e), "a third of the permits in codes the dictionary lacks fails (the file's vocabulary changed): %s" % msg(e)[:50])
old_mod = [dict(r, Dt_Mod="2026-06-30 00:00:00") for r in big if r["Permit_Issued"][:7] <= "2026-06"]
e = build_with(old_mod)
check(isinstance(e, RuntimeError) and "refreshed" in msg(e), "a file whose newest update and newest permit are months old fails: %s" % msg(e)[:50])
old_permits = [r for r in big if r["Permit_Issued"][:4] < "2024" or not r["Permit_Issued"]]
e = build_with(old_permits)
check(isinstance(e, RuntimeError) and "stale" in msg(e), "a file whose newest permit is years old fails: %s" % msg(e)[:50])
quiet = [r for r in big if r["Permit_Issued"][:7] != "2026-10" and r["Permit_Issued"][:7] != "2026-09"]
doc_q = NY.build(get=lambda url, **k: zip_of(csv_of(quiet)), today=TODAY)
check(doc_q["through"] == "2026-09-30" and doc_q["bands"]["new"][-1] == 0 and C.validate(doc_q, TODAY) == [], "a quiet month is a real zero when the file itself is fresh (no permits in September, the file updated Oct 29)")
restore()

# the network: a refusal is an answer (exit 2), any other failure exits 1; neither writes or touches the committed file
def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


def dropped(url, **kw):
    raise RuntimeError("could not read the source: <urlopen error timed out>")


with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "NY.json")
    open(p, "w").write("committed\n")
    check(C.run_producer("NY", lambda: NY.build(get=refuse), tmp, argv=[]) == 2 and open(p).read() == "committed\n", "a refusing server exits 2 and leaves the committed file alone")
    check(C.run_producer("NY", lambda: NY.build(get=dropped), tmp, argv=[]) == 1 and open(p).read() == "committed\n", "a dropped connection exits 1 and leaves the committed file alone")
    check(C.run_producer("NY", lambda: NY.build(get=lambda url, **kw: b"<html>maintenance</html>"), tmp, argv=[]) == 1 and open(p).read() == "committed\n", "an error page instead of the zip exits 1 and leaves the committed file alone")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
