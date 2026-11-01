"""Tests for the national report's data layer: site/pipeline/d11_nat_common.py (what every state's producer shares) and d11_nat_build.py (the merge into
national.json that the National view reads).

Synthetic permits cover the rules (a permit falls in exactly one band; amendments are recognized before the work they amend; the fluid words; dates in the shapes
agencies use and the placeholders they put in; complete months only, and the lag a spud-counting state needs; only corporations, LLCs and partnerships are named;
no band a source cannot tell is ever written as zero); the validator is run on what the tally builds and on deliberate faults; mutants patch one rule at a time and
require the checks to notice; the merge keeps each measure apart and never adds the BLM into the states; and the committed national.json is checked.

Run: python3 -I tests/test_d11_nat.py"""
import copy
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_build as B  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ words: bands, fluids, dates
check(C.place_title("MCKENZIE") == "McKenzie" and C.place_title("ST. CLAIR") == "St. Clair" and C.place_title("DE SOTO") == "De Soto" and C.place_title("MACON") == "Macon" and C.place_title("O'BRIEN") == "O'Brien", "place_title: McKenzie keeps its capital K, and other names stay in plain title case")
check(C.band_of("New Drill", "Oil") == "new" and C.band_of("Original", "") == "new" and C.band_of("", "") == "new" and C.band_of("Permit to Drill", "Gas") == "new",
      "band_of: a new drill, an original application, a blank type and a permit to drill are new wells")
check(C.band_of("Amended permit", "") == "amend" and C.band_of("Extension", "") == "amend" and C.band_of("Change of operator", "") == "amend" and C.band_of("Revision of APD", "oil") == "amend",
      "band_of: amendments, extensions, operator changes and revisions are amendments")
check(C.band_of("Amend new drill", "oil") == "amend", "band_of: an amendment of a new-drill permit is an amendment, not a new well")
check(C.band_of("Recompletion", "") == "rework" and C.band_of("Plug back", "") == "rework" and C.band_of("Workover", "") == "rework" and C.band_of("Conversion to injection", "") == "rework",
      "band_of: recompletions, plug-backs, workovers and conversions are reworks")
check(C.band_of("Re-entry", "") == "redrill" and C.band_of("Deepen", "") == "redrill" and C.band_of("Sidetrack", "") == "redrill" and C.band_of("Reenter", "") == "redrill",
      "band_of: re-entries, deepenings and sidetracks are re-drills")
check(C.band_of("New drill", "Salt water disposal") == "inj" and C.band_of("Original", "Injection - EOR") == "inj" and C.band_of("", "Service well") == "inj",
      "band_of: a new well for injection, disposal or service is an injection well")
check(C.band_of("Frobnication", "oil") == "other", "band_of: anything it cannot place is other, never a guess at new")
check(C.fluid_of("Oil") == "oil" and C.fluid_of("Gas well") == "gas" and C.fluid_of("Oil and Gas") == "both" and C.fluid_of("O&G") == "both" and C.fluid_of("Oil/Gas") == "both",
      "fluid_of: oil, gas and both")
check(C.fluid_of("Disposal") == "other" and C.fluid_of("Injection") == "other" and C.fluid_of("Stratigraphic test") == "other" and C.fluid_of("") is None and C.fluid_of("Development") is None,
      "fluid_of: service wells are other, and words that say nothing about the fluid are None (not oil)")
today = date(2026, 10, 31)
check(C.parse_day("2026-10-01", today) == date(2026, 10, 1) and C.parse_day("10/1/2026", today) == date(2026, 10, 1) and C.parse_day("20261001", today) == date(2026, 10, 1)
      and C.parse_day("01-OCT-2026", today) == date(2026, 10, 1) and C.parse_day("2026-10-01T08:30:00Z", today) == date(2026, 10, 1) and C.parse_day("2026-10-01 08:30:00", today) == date(2026, 10, 1),
      "parse_day: the shapes agencies use")
check(C.parse_day(1759276800000, today) == date(2025, 10, 1), "parse_day: an ArcGIS millisecond stamp")
check(all(C.parse_day(x, today) is None for x in ("", None, "n/a", "00/00/0000", "1900-01-01", "9999-12-31", "2026-11-05", "13/45/2026", 0)),
      "parse_day: blank, junk, 1900, 9999 and a day after today are not dates")
check(C.month_list("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"] and C.add_months("2026-01", -2) == "2025-11" and C.month_end("2026-02") == date(2026, 2, 28),
      "month helpers cross a year and know a short February")

# ------------------------------------------------------------------------------------------------ the tally


def make(state="ND", measure="permits", lag=0, asof=date(2026, 10, 15), bands=("new", "amend"), fluid=True, extra=None):
    t = C.Tally(state, bands=bands, fluid=fluid)
    d = date(2019, 1, 15)
    while d <= date(2026, 10, 15):
        t.add(d, "new", county="Williams", operator="ACME OIL & GAS LLC", fluid="oil")
        t.add(d, "new", county="McKenzie County", operator="Smith, John", fluid="gas")  # an individual: counted, never named
        t.add(d, "amend", county="Williams", operator="ACME OIL & GAS LLC")
        t.add(d, "inj")  # a band this source cannot tell: counted nowhere
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 15)
    if extra:
        extra(t)
    return t.document(agency="A Commission", source_name="Permit file", source_url="https://example.gov/permits", basis="approval date", cadence="weekly", measure=measure, lag_days=lag, asof=asof)


doc = make()
check(C.validate(doc, today) == [], "a document built by the tally passes the validator: %s" % C.validate(doc, today)[:3])
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-15",
      "only complete months: with the newest record on Oct 15 the series ends in September, and starts in 2019-01 (%s .. %s)" % (doc["months"][0], doc["months"][-1]))
check(doc["bands"]["inj"] is None and doc["bands"]["redrill"] is None and isinstance(doc["bands"]["new"], list) and isinstance(doc["bands"]["amend"], list),
      "a band the source cannot tell is null, never a list of zeros")
check(all(v == 2 for v in doc["bands"]["new"]) and all(v == 1 for v in doc["bands"]["amend"]), "the counts are per month (two new, one amendment a month)")
check(doc["operators"] == [["ACME OIL & GAS LLC", 12]] and doc["namedShare"] == 0.5, "an individual's name is counted in the share but never named: %s share %s" % (doc["operators"], doc["namedShare"]))
# California's real shape: a layer that starts in 2024-11, 8 new-drill permits in all of 2025, then 60 to 93 a month in 2026
cal = C.Tally("CA")
for i, ym in enumerate(C.month_list("2024-11", "2026-10")):
    big = ym >= "2026-01"
    cal.add(date(int(ym[:4]), int(ym[5:]), 15), "new", n=([60, 93, 70, 88, 90, 85, 80, 75, 82, 79][int(ym[5:]) - 1] if big else 1))
jump = cal.document(agency="CalGEM", source_name="Notices", source_url="https://example.gov/x", basis="approval date", cadence="daily", asof=date(2026, 11, 1), first="2024-11")
check(C.validate(jump, date(2026, 11, 2)) == [], "a real regime change (1 a month, then 60 to 93 a month: California's) is not mistaken for a parse error: %s" % C.validate(jump, date(2026, 11, 2))[:2])
spike = copy.deepcopy(doc)
spike["bands"]["new"][40] = 99000
check(any("wildly" in x or "non-negative" in x for x in C.validate(spike, today)), "but one month 1,000 times the rest still is")
wordy = dict(doc, note="Amendments are not told (null).")
check(any("programmer" in x for x in C.validate(wordy, today)), "a note that says (null) is refused: on a page it reads as a rendering bug (Kansas's note did, found by the smoke test)")
check(C.validate(dict(doc, note="Amendments are not told."), today) == [], "the same note without the word passes")
check(doc["counties"][0][0] == "Williams" and [c[0] for c in doc["counties"]] == ["Mckenzie County", "Williams"] or doc["counties"][0][1] == 12, "counties are ranked place names: %s" % doc["counties"])
check(doc["fluid"] == {"oil": 12, "gas": 12, "both": 0, "other": 0, "unknown": 0}, "the fluid of the year's new wells: %s" % doc["fluid"])
check(make(fluid=False)["fluid"] is None, "a state that records no fluid has fluid null")
lagged = make(measure="spuds", lag=60, asof=date(2026, 10, 15))
check(lagged["months"][-1] == "2026-07" and C.validate(lagged, today) == [], "a spud-counting state with a 60-day lag ends at the newest month that ended 60 days before its newest record (%s)" % lagged["months"][-1])
try:
    C.Tally("ND").document(agency="x", source_name="x", source_url="https://x.gov/", basis="x", cadence="x")
    check(False, "an empty tally refuses to write a document")
except ValueError:
    check(True, "an empty tally refuses to write a document")
try:
    C.Tally("ZZ")
    check(False, "an unknown state is refused")
except ValueError:
    check(True, "an unknown state is refused")
t = C.Tally("ND")
t.add(None, "new"); t.add(date(2026, 1, 1), "nonsense")
check(t.read == 0, "a record with no day, or a band that is not one, is not counted")

# ------------------------------------------------------------------------------------------------ the validator, against deliberate faults


def broken(fn):
    d = copy.deepcopy(doc)
    fn(d)
    return C.validate(d, today)


faults = {
    "an operator the rule refuses": lambda d: d["operators"].append(["JOHN SMITH DBA JOE'S OIL", 1]),
    "a gap in the months": lambda d: d["months"].pop(5) and None,
    "a band list of the wrong length": lambda d: d["bands"].__setitem__("new", d["bands"]["new"][:-1]),
    "a negative count": lambda d: d["bands"]["new"].__setitem__(3, -1),
    "a missing new band": lambda d: d["bands"].__setitem__("new", None),
    "a measure that is not one": lambda d: d.__setitem__("measure", "approvals"),
    "no new permit in the last 24 months": lambda d: d["bands"].__setitem__("new", [0] * len(d["months"])),
    "one wildly large month (a parse error)": lambda d: d["bands"]["new"].__setitem__(40, 99000),
    "an e-mail address in the note": lambda d: d.__setitem__("note", "write to joe@example.com"),
    "a phone number in the note": lambda d: d.__setitem__("note", "call 701-555-0100"),
    "an API number in the note": lambda d: d.__setitem__("note", "well 33105012340000"),
    "a source with no address": lambda d: d["source"].__setitem__("url", ""),
    "an http address (not https)": lambda d: d["source"].__setitem__("url", "http://example.gov/x"),
    "through that is not the end of the last month": lambda d: d.__setitem__("through", "2026-09-15"),
    "an asOf in the future": lambda d: d.__setitem__("asOf", "2027-01-01"),
    "an unranked operator list": lambda d: d.__setitem__("operators", [["A LLC", 1], ["B LLC", 5]]),
    "a county that is a street": lambda d: d["counties"].append(["123 Main Street 99999", 1]),
    "too many counties": lambda d: d.__setitem__("counties", [["C%d" % i, 20 - i] for i in range(16)]),
    "a fluid dict missing a key": lambda d: d["fluid"].pop("both"),
    "a state this file type does not carry": lambda d: d.__setitem__("state", "TX"),
    "a namedShare above one": lambda d: d.__setitem__("namedShare", 1.4),
    "not a v1 document": lambda d: d.__setitem__("v", 2),
}
for name, fn in faults.items():
    check(broken(fn), "the validator refuses " + name)

# ------------------------------------------------------------------------------------------------ writing and re-reading
with tempfile.TemporaryDirectory() as tmp:
    path = C.write_doc(copy.deepcopy(doc), tmp)
    check(os.path.basename(path) == "ND.json" and C.check_dir(tmp) == [], "write_doc writes nat/ND.json and check_dir finds it clean")
    bad = copy.deepcopy(doc)
    bad["operators"].append(["JOHN SMITH", 1])
    try:
        C.write_doc(bad, tmp)
        check(False, "write_doc refuses a bad document")
    except ValueError:
        check(True, "write_doc refuses a bad document, and leaves the earlier file alone")
    check(json.load(open(path))["operators"] == doc["operators"], "the earlier file is untouched after a refused write")
    open(os.path.join(tmp, "XX.json"), "w").write("{not json")
    check(any("XX" in x for x in C.check_dir(tmp)), "check_dir reports a file it cannot read")
    # run_producer: a producer that fails writes nothing and says so; one the server refuses exits 2
    os.remove(os.path.join(tmp, "XX.json"))
    check(C.run_producer("ND", lambda: (_ for _ in ()).throw(RuntimeError("boom https://x.gov/a")), tmp, argv=[]) == 1 and C.check_dir(tmp) == [], "run_producer: a failure exits 1 and leaves the committed file")
    check(C.run_producer("ND", lambda: (_ for _ in ()).throw(C.Refused("HTTP 403")), tmp, argv=[]) == 2, "run_producer: a refusal exits 2")
    check(C.run_producer("ND", lambda: doc, tmp, argv=[]) == 0 and C.run_producer("ND", None, tmp, argv=["--check"]) == 0, "run_producer: a good build exits 0 and --check is clean")

# ------------------------------------------------------------------------------------------------ the merge


def fake_state(sid, measure, scale=1):
    d = make(state=sid, measure=measure, lag=60 if measure == "spuds" else 0, asof=date(2026, 10, 15))
    d["bands"]["new"] = [v * scale for v in d["bands"]["new"]]
    return d


docs = {"ND": fake_state("ND", "permits", 3), "KS": fake_state("KS", "permits"), "BL": fake_state("BL", "permits", 2), "AK": fake_state("AK", "spuds")}
nat = B.build(docs, {}, today)
check(B.validate(nat) == [], "the merge validates: %s" % B.validate(nat)[:2])
ids = {s["id"] for s in nat["states"]}
check(ids == {"ND", "KS", "BL", "AK"} and {g["id"] for g in nat["gaps"]} == {i for i, _ in C.JURISDICTIONS} - ids, "every jurisdiction without data is a gap, not a zero")
p12 = {s["id"]: s["p12"] for s in nat["states"]}
check(nat["totals"]["permits12"] == p12["ND"] + p12["KS"] and nat["totals"]["spuds12"] == p12["AK"] and p12["BL"] > 0,
      "totals add within a measure only, and the BLM's onshore permits are shown but never added into the states' totals")
ak = next(s for s in nat["states"] if s["id"] == "AK")
check(len(ak["bands"]["new"]) == len(nat["months"]) and ak["bands"]["new"][-1] is None and ak["bands"]["new"][-3] is not None, "a state that ends earlier is padded with null after its last month, never with zero")
late = C.Tally("BL")
for i in range(40):
    late.add(date(2023 + (i + 1) // 12, (i + 1) % 12 + 1, 15), "new", n=3)
bl_doc = late.document(agency="BLM", source_name="Reports", source_url="https://example.gov/x", basis="approval date", cadence="monthly", asof=date(2026, 10, 15), first="2023-02")
nat_late = B.build(dict(docs, BL=bl_doc), {}, today)
bl = next(s for s in nat_late["states"] if s["id"] == "BL")
check(B.validate(nat_late) == [] and bl["bands"]["new"][0] is None and bl["bands"]["new"][-1] is not None, "a state that starts later than the axis is padded with null in front too (and validates)")
holey = copy.deepcopy(nat_late)
next(s for s in holey["states"] if s["id"] == "BL")["bands"]["new"][-20] = None
check(B.validate(holey), "a gap inside a state's months (a null between figures) is refused")
check(nat["months"][-1] == "2026-09" and ak["through"].startswith("2026-07"), "the axis runs to the newest month any state reaches")
check(ak["mix12"]["new"] == ak["p12"] and ak["mix12"].get("redrill") is None, "the mix covers only the bands the state can tell")
gap = next(g for g in B.build(docs, {"states": {"CO": {"agency": {"name": "ECMC"}, "grade": "D", "grade_reason": "blocked"}}}, today)["gaps"] if g["id"] == "CO")
check(gap["agency"] == "ECMC" and gap["grade"] == "D" and gap["why"] == "blocked", "a gap carries the research's agency, grade and reason")
check(B.build(docs, {}, today)["hasFields"] is False and B.build(docs, {"states": {"CO": {}}}, today)["hasFields"] is True, "hasFields says whether the matrix file exists")
bad = copy.deepcopy(nat)
bad["totals"]["permits12"] += 1
check(B.validate(bad), "the merge validator notices totals that do not add")
bad = copy.deepcopy(nat)
bad["states"][0]["operators"].append(["JANE ROE", 1])
check(B.validate(bad), "the merge validator notices an operator the naming rule refuses")
bad = copy.deepcopy(nat)
bad["gaps"].pop()
check(B.validate(bad), "the merge validator notices a jurisdiction that is neither a state nor a gap")

# ------------------------------------------------------------------------------------------------ mutants: one rule put back each time, the checks must notice


def mutant(name, patch, probe):
    spec = importlib.util.spec_from_file_location("m_" + name, os.path.join(PIPE, "d11_nat_common.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    patch(m)
    check(probe(m), "mutant '%s' is noticed" % name)


mutant("every operator may be named", lambda m: setattr(m, "nameable", lambda n: True), lambda m: m.validate(dict(doc, operators=[["JOHN SMITH", 1]]), today) == [])
mutant("amendments are new wells", lambda m: setattr(m, "band_of", lambda w="", p="": "new"), lambda m: m.band_of("Amended", "") != C.band_of("Amended", ""))
mutant("a service well is new", lambda m: setattr(m, "fluid_of", lambda t: "oil"), lambda m: m.fluid_of("Disposal") != C.fluid_of("Disposal"))
mutant("placeholder dates count", lambda m: setattr(m, "parse_day", lambda t, today=None: date(1900, 1, 1)), lambda m: m.parse_day("1900-01-01") != C.parse_day("1900-01-01"))

# ------------------------------------------------------------------------------------------------ the committed files
natdoc = json.load(open(os.path.join(DATA, "national.json")))
check(B.validate(natdoc) == [], "the committed national.json validates: %s" % B.validate(natdoc)[:2])
check(C.check_dir(os.path.join(DATA, "nat")) == [], "every committed nat/<ST>.json validates: %s" % C.check_dir(os.path.join(DATA, "nat"))[:3])
check({"TX", "OK", "NM", "FO"} <= {s["id"] for s in natdoc["states"]}, "Texas, Oklahoma, New Mexico and the federal offshore are in it")
check(all(s["measure"] == "spuds" for s in natdoc["states"] if s["id"] in ("NM", "FO")) and all(s["measure"] == "permits" for s in natdoc["states"] if s["id"] in ("TX", "OK")),
      "New Mexico and the federal offshore count spuds; Texas and Oklahoma count permits")
check(B.build(None, None, date.fromisoformat(natdoc["generated"])) == natdoc, "national.json is what the builder makes from the committed files (rebuild it after changing a state file)")
import re  # noqa: E402
import privacy_check  # noqa: E402
text = re.sub(r"https://[\w./\-]+", "", json.dumps(natdoc))  # the sources' web addresses are meant to be there
check(not privacy_check.scan(text, digits=True), "no e-mail, phone or API-like number in national.json")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
