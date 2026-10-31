"""Tests for site/pipeline/d9_nm_monthly.py: New Mexico's drilling history (wells spudded) from the OCD's well layer.

Synthetic wells, written the way the layer returns them, cover the rules (which spud dates are real, one well once, the county from the
layer's code, locations inside the state, no depth, the naming rule, the lag that decides where the files end); the validator is run on what
they build; mutants patch one rule at a time and require the checks to notice. The committed files are validated too, and the EIA crude series
for New Mexico with the Oklahoma producer's validator.

Run: python3 -I tests/test_d9_nm.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
spec = importlib.util.spec_from_file_location("d9", os.path.join(PIPE, "d9_nm_monthly.py"))
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)
M, D = N.M, N.D

TMP = tempfile.mkdtemp()
NAMES = {"015": "Eddy", "025": "Lea", "045": "San Juan"}
FAILS = []


def ms(day, hour=7):
    """The layer stores a spud date as local midnight in Mountain standard time, 07:00 UTC."""
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def well(api, ogrid, name, day, county=25, lat=32.3, lon=-103.5, tvd=0, md=0, spud=None):
    return {"id": api, "type": "Oil", "status": "New", "ogrid": ogrid, "ogrid_name": name, "county_code": county, "latitude": lat, "longitude": lon,
            "spud_date": ms(day) if spud is None else spud, "measured_vertical_depth": md, "true_vertical_depth": tvd}


def wells():
    out = []
    for i in range(12):
        out.append(well("30-025-%05d" % (50000 + i), 7377, "EOG Resources Inc", date(2026, 1, 5) + timedelta(days=i), lat=32.31234, lon=-103.51234, tvd=9500, md=19000))
    out.append(well("30-025-60001", 7377, "EOG Resources Inc", date(2025, 3, 3)))                                    # in the 12 before
    out.append(well("30-015-60002", 14744, "MEWBOURNE OIL CO", date(2026, 8, 31), county=15))                          # the last day of the files
    out.append(well("30-015-60003", 14744, "MEWBOURNE OIL CO", date(2026, 9, 2), county=15))                           # after the files end: left out
    out.append(well("30-025-60004", 55555, "JOHN Q PUBLIC", date(2026, 2, 10)))                                        # an individual: counted, never named
    out.append(well("30-025-60005", 66666, "SMITH DBA SMITH OIL CO", date(2026, 2, 11)))                               # a person's dba: counted, never named
    out.append(well("30-045-60006", 372171, "Hilcorp Energy Company", date(2026, 3, 3), county=45, lat=36.7, lon=-108.1))
    out.append(well("30-025-60007", 7377, "EOG Resources Inc", date(2026, 3, 4), lat=40.0, lon=-103.5))                 # a location outside the state: counted, no point
    out.append(well("30-025-60008", 7377, "EOG Resources Inc", date(2026, 3, 5), county=0))                            # no county: counted apart
    out.append(well("30-025-60009", 7377, "EOG Resources Inc", None or date(2026, 3, 6), spud=ms(date(9999, 12, 31))))  # not spudded (the layer says 9999)
    out.append(well("30-025-60010", 7377, "EOG Resources Inc", date(1900, 1, 1)))                                      # a 1900 placeholder
    out.append(well("not an api", 7377, "EOG Resources Inc", date(2026, 3, 7)))
    out.append(dict(well("30-025-60011", 7377, "EOG Resources Inc", date(2026, 3, 8)), spud_date=None))
    out.append(well("30-025-50000", 7377, "EOG Resources Inc", date(2026, 1, 5)))                                      # the same well in the layer twice
    return out


FIRST = {"7377": date(1995, 6, 1), "14744": date(1990, 1, 1), "372171": date(2025, 2, 2)}
ASOF = date(2026, 8, 31)
FAIL_KEY = "FAIL "


def check(cond, msg):
    print(("ok   " if cond else FAIL_KEY) + msg)
    if not cond:
        FAILS.append(msg)


def run_checks(quiet=False):
    fails = []

    def chk(cond, msg):
        if not quiet:
            print(("ok   " if cond else FAIL_KEY) + msg)
        if not cond:
            fails.append(msg)

    # ---- the lag decides where the files end
    r = N.reliable_asof
    chk(r(date(2026, 10, 31)) == date(2026, 8, 31), "today Oct 31 (August ended 61 days ago): the files end Aug 31")
    chk(r(date(2026, 10, 30)) == date(2026, 8, 31) and r(date(2026, 10, 29)) == date(2026, 7, 31), "August enters on Oct 30, the 60th day after it ended; the day before it is not in yet")
    chk(r(date(2026, 11, 29)) == date(2026, 9, 30) and r(date(2026, 11, 28)) == date(2026, 8, 31), "a month enters on the 60th day after it ended (Sep 30 + 60 = Nov 29)")
    chk(r(date(2027, 3, 1)) == date(2026, 12, 31), "across a year end")

    # ---- what a well becomes
    coll = N.collect(wells(), FIRST, date(2026, 10, 31))
    st = coll["stats"]
    chk(st["spudded wells"] == 20 and st["no real spud date"] == 3 and st["no usable API number"] == 1 and st["a well in the layer twice"] == 1,
        "real spud dates become wells; 9999, 1900 and a missing date are not spudded; a bad API number and a repeat are skipped: %s" % dict(st))
    p = {k[0]: v for k, v in coll["permits"].items()}
    chk(p["30-025-50000"]["depth"] == 0 and p["30-025-50001"]["depth"] == 0, "no depth is published (the layer has one for about 3% of new wells)")
    chk(p["30-025-60008"]["county"] == "" and p["30-025-50000"]["county"] == "025" and p["30-045-60006"]["county"] == "045", "the county is the layer's code as three digits, blank when it has none")
    chk(p["30-025-60007"]["lat"] is None and p["30-025-50000"]["lat"] == 32.31234, "a location outside the state is dropped, one inside kept")
    chk(p["30-025-50000"]["day"] == date(2026, 1, 5) and p["30-025-50000"]["name"] == "EOG RESOURCES INC", "the day is the spud date (07:00 UTC is the same day) and the name is upper case")

    # ---- the files
    docs, rep = M.build(coll, NAMES, ASOF, None, N.SPEC)
    series, cp, ops, pts = (docs[n] for n in N.NAMES)
    got = {m: v for m, v in zip(series["months"], series["permits"]) if v}
    chk(series["months"][0] == "2019-01" and series["months"][-1] == "2026-08" and series["through"] == "2026-08-31", "the series runs 2019-01 to the last month the files cover, 2026-08")
    chk(got == {"2025-03": 1, "2026-01": 12, "2026-02": 2, "2026-03": 3, "2026-08": 1}, "monthly counts: a well once, the 9999 and 1900 rows not spudded, the Sept 2 spud after the files end: %s" % got)
    c = cp["counties"]
    chk(sorted(c) == ["015", "025", "045"] and cp["noCounty"] == 1, "counties, and the well with no county counted apart: %s noCounty %s" % (sorted(c), cp["noCounty"]))
    chk((c["025"]["p12"], c["025"]["p12prev"], c["025"]["depth"]) == (15, 1, None) and c["015"]["p12"] == 1 and c["045"]["p12"] == 1, "county 025: 15 in the last 12 months (EOG's 12 and 1, the individual's and the dba's), 1 before, no depth: %s" % c["025"])
    chk(c["025"]["ops"][0] == ["EOG RESOURCES INC", "7377", 13], "its top operator is named with its count; the individual and the dba are in the county's count and not in the names: %s" % c["025"]["ops"])
    r_ = {x[2]: dict(zip(ops["cols"], x)) for x in ops["rows"]}
    chk(sorted(r_) == ["EOG RESOURCES INC", "HILCORP ENERGY COMPANY", "MEWBOURNE OIL CO"], "only named operators: the individual and the dba are not in the operators file: %s" % sorted(r_))
    e = r_["EOG RESOURCES INC"]
    chk((e["band"], e["type"], e["new12"], e["prev12"], e["all24"], e["newDrill"], e["city"], e["state"]) == ("A", "corporation", 14, 1, 15, 0, "", ""), "EOG: band A, 14 and 1 (one has no county, one no location), not new to drilling, no office city or state: %s" % e)
    chk(r_["HILCORP ENERGY COMPANY"]["newDrill"] == 1 and r_["HILCORP ENERGY COMPANY"]["band"] == "B", "an operator whose first spud ever is in the last 24 months is new to drilling")
    chk(len(pts["pts"]) == 17 and pts["pts"][0][0] % 10 == 0, "points: the located wells of the last 24 months with a county (not the one outside the state, not the one with no county), rounded to about 100 m: %d" % len(pts["pts"]))
    chk((32312, ) == (round(32.31234 * 1000),) and any(q[0] == 323120 and q[1] == -1035120 for q in pts["pts"]), "a location is rounded to 3 decimals")
    chk(pts["coverage"]["share12"] < 1.0 and pts["coverage"]["share24"] < 1.0, "coverage counts the well outside the state as not located")

    # ---- one year is the same year in the series, the counties and the operators: 12 calendar months, because the files end on a month end (found by an independent
    # review of the federal offshore, which is built the same way: a well on Aug 31 of the year before was in the counties' 12 months and not in the series')
    edge = N.collect([well("30-025-7%04d" % i, 7377, "EOG Resources Inc", d) for i, d in enumerate((date(2025, 8, 31), date(2025, 9, 1), date(2024, 8, 31), date(2024, 9, 1), date(2026, 8, 31)))],
                     FIRST, date(2026, 10, 31))
    edocs, _ = M.build(edge, NAMES, ASOF, None, N.SPEC)
    es, ec, eo = edocs["series-permits-nm.json"], edocs["county-permits-nm.json"]["counties"], edocs["operators-nm.json"]
    erow = dict(zip(eo["cols"], eo["rows"][0]))
    chk(sum(es["permits"][-12:]) == 2 == sum(c["p12"] for c in ec.values()) == erow["new12"] and sum(es["permits"][-24:-12]) == 2 == sum(c["p12prev"] for c in ec.values()) == erow["prev12"],
        "wells on Aug 31 and Sep 1 of the year windows are in the same year for the series, the counties and the operators: 12 months %d, the 12 before %d"
        % (sum(c["p12"] for c in ec.values()), sum(c["p12prev"] for c in ec.values())))

    # ---- the validator, on what was built and on faults
    out = os.path.join(TMP, "good")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for name, doc in docs.items():
        M.write_json(os.path.join(out, name), doc)
    good = M.validate(out, NAMES, N.SPEC)
    chk(good == [], "validate accepts what build wrote: %s" % good)

    def fault(label, mutate, expect):
        d = os.path.join(TMP, "fault")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        import copy
        cur = copy.deepcopy(docs)
        mutate(cur)
        for name, doc in cur.items():
            M.write_json(os.path.join(d, name), doc)
        problems = M.validate(d, NAMES, N.SPEC)
        chk(any(expect in x for x in problems), "validate notices %s (%s): %s" % (label, expect, problems[:2]))
    fault("an unnamed operator", lambda cur: cur["operators-nm.json"]["rows"][0].__setitem__(2, "JOHN Q PUBLIC"), "malformed")
    fault("a point outside the state", lambda cur: cur["permits-nm.json"]["pts"].append([400000, -1035000, -1, 100, 0, 25]), "points are malformed")
    fault("a gap in the months", lambda cur: cur["series-permits-nm.json"]["months"].pop(40), "gap")
    fault("a Texas county", lambda cur: cur["permits-nm.json"]["pts"].append([323000, -1035000, -1, 100, 0, 1001]), "points are malformed")
    return fails


def mutants():
    fails = []
    real = {"nameable": D.nameable, "reliable": N.reliable_asof, "SPEC": dict(N.SPEC)}

    def run(name, patch):
        patch()
        try:
            got = run_checks(quiet=True)
        except Exception as ex:  # noqa: BLE001 - a mutant may break the build outright: that is noticed too
            got = ["raised %r" % ex]
        finally:
            D.nameable, N.reliable_asof = real["nameable"], real["reliable"]
            N.SPEC.clear()
            N.SPEC.update(real["SPEC"])
        print(("ok   " if got else FAIL_KEY) + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)
    run("everyone is named", lambda: setattr(D, "nameable", lambda n: True))
    run("nobody is named", lambda: setattr(D, "nameable", lambda n: False))
    run("the files end the day before the layer is read (no lag)", lambda: setattr(N, "reliable_asof", lambda today, lag=0: today - timedelta(days=1)))
    run("a lag of 30 days", lambda: setattr(N, "reliable_asof", lambda today, lag=30: real["reliable"](today, 30)))
    run("a year is the 365 days that end on the as-of day", lambda: N.SPEC.update(calendar_windows=False))
    return fails


print("-- the rules")
FAILS += run_checks()

print("\n-- the committed files")
names = N.county_names()
check(len(names) == 33 and all("001" <= k <= "061" for k in names), "counties-nm.geo.json holds the 33 New Mexico counties: %d" % len(names))
if all(os.path.exists(os.path.join(DATA, n)) for n in N.NAMES):
    problems = M.validate(DATA, names, N.SPEC)
    check(not problems, "validate accepts the committed files" + ("" if not problems else ": %s" % problems[:3]))
    FAILS += problems
    ops = json.load(open(os.path.join(DATA, "operators-nm.json")))
    check(all(D.nameable(x[2]) for x in ops["rows"]), "every operator in them passes the naming rule (%d operators)" % len(ops["rows"]))
    cp = json.load(open(os.path.join(DATA, "county-permits-nm.json")))
    check(all(c["depth"] is None for c in cp["counties"].values()), "no county shows a depth")
else:
    print("skip  the files are not committed yet")
ctx_spec = importlib.util.spec_from_file_location("ctx", os.path.join(PIPE, "d8_ok_context.py"))
C = importlib.util.module_from_spec(ctx_spec)
ctx_spec.loader.exec_module(C)
nm = json.load(open(os.path.join(DATA, "series-nm.json")))
check(C.validate(nm, "NM") == [], "series-nm.json (the EIA's New Mexico crude) is clean: %s" % C.validate(nm, "NM"))
bad = dict(nm, nmCrude=[v * 100 for v in nm["nmCrude"]])
check(any("plausible range" in x for x in C.validate(bad, "NM")), "a series in the wrong units is caught")
check(C.validate(nm, "OK") != [], "New Mexico's file is not taken for Oklahoma's")

print("\n-- mutants")
FAILS += mutants()

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
