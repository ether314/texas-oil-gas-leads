"""Tests for site/pipeline/d8_ok_monthly.py: Oklahoma's permit history files (series, counties, operators, points).

Synthetic permit rows, written the way the workbook reader returns them, cover the rules (one permit per API number and approval day,
formation rows folded, rejected and deleted left out, the Central day, the windows, the naming rule, the rounding of locations); the
validator is run on what they build and on deliberate faults; mutants patch one rule at a time and require the checks to notice.
The committed files are validated too. With OK_REAL_FILES=<folder holding ITD-wells-formations-base.xlsx and the daily file> the
real workbooks are read as well and the months the Daily archive also covers must agree with it (about 80 s).

Run: python3 -I tests/test_d8_monthly.py
"""
import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
spec = importlib.util.spec_from_file_location("d8m", os.path.join(PIPE, "d8_ok_monthly.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

COUNTIES = M.D.Lookups().county
TMP = tempfile.mkdtemp()


def serial(day, hour=15):
    """The number Excel stores for a UTC time on a day."""
    return str((datetime(day.year, day.month, day.day, hour) - datetime(1899, 12, 30)).total_seconds() / 86400)


def api(county, n):
    return "35%s%05d0000" % (county, n)


def row(a, op, name, day, kind="DR", status="WRA", depth="10000", lon="-98.5", lat="35.5", city="OKLAHOMA CITY", state="OK", hour=15):
    return {"API_Number": a, "Operator_Number": op, "Entity_Name": name, "City": city, "State": state, "Application_Type": kind, "Permit_Status": status,
            "Total_Depth": depth, "Depth": depth, "Approval_Date": serial(day, hour), "Surf_Long_X": lon, "Surf_Lat_Y": lat}


def rows():
    out = []
    add = lambda *a, **k: out.append(row(*a, **k))  # noqa: E731
    for i in range(12):                                    # ACME: 12 new wells in January 2026, each named in three formations
        for _ in range(3):
            add(api("017", 10 + i), "100", "ACME OIL LLC", date(2026, 1, 5) + timedelta(days=i), depth="20000", city="TULSA")
    add(api("017", 10), "100", "ACME OIL LLC", date(2025, 2, 10), depth="20000")   # the first of them was approved a year earlier too
    add(api("017", 50), "100", "ACME OIL LLC", date(2025, 3, 1), depth="20000")
    add(api("017", 51), "100", "ACME OIL LLC", date(2025, 3, 2), depth="20000")
    add(api("017", 60), "100", "ACME OIL LLC", date(2026, 5, 4), kind="RC")          # a recompletion: a permit, not a new drill
    add(api("017", 61), "100", "ACME OIL LLC", date(2026, 5, 4), kind="AM")          # an amendment: not counted at all
    add(api("017", 62), "100", "ACME OIL LLC", date(2026, 5, 5), status="REJ")
    add(api("017", 63), "100", "ACME OIL LLC", date(2026, 5, 6), status="DEL")
    add(api("051", 1), "200", "BIG CORP INC", date(2005, 6, 1))                       # long ago: only its first drilling permit is kept
    add(api("051", 9), "200", "BIG CORP INC", date(2025, 10, 15))                    # a month before the 12-month window starts: it is in the 12 before
    add(api("051", 10), "200", "BIG CORP INC", date(2026, 3, 2), lat="35.51234", lon="-98.51234")
    add(api("051", 11), "200", "BIG CORP INC", date(2026, 3, 3), lat="35.51234", lon="-98.51234")
    add(api("051", 12), "200", "BIG CORP INC", date(2026, 3, 9), lat="40.0")          # a location outside the state: counted, no point
    add(api("051", 13), "200", "BIG CORP INC", date(2026, 10, 31), hour=3)           # 03:00 UTC on Oct 31 is 22:00 on Oct 30 in Central
    add(api("129", 20), "300", "JOHN Q PUBLIC", date(2026, 2, 10), depth="9000")      # an individual: counted, never named
    add(api("129", 21), "300", "JOHN Q PUBLIC", date(2026, 2, 11), depth="9000")
    add(api("999", 20), "300", "JOHN Q PUBLIC", date(2026, 2, 12))                    # a county code the state does not have
    add("42017000990000", "100", "ACME OIL LLC", date(2026, 6, 1))                    # a Texas API number
    add("123", "100", "ACME OIL LLC", date(2026, 6, 1))                               # junk
    nodate = row(api("017", 70), "100", "ACME OIL LLC", date(2026, 6, 1))
    nodate["Approval_Date"] = None
    out.append(nodate)
    return out


FAILS = []


def run_checks(M, quiet=False):
    fails = []

    def check(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    coll = M.collect(rows())
    st = coll["stats"]
    check(st["no usable API number"] == 2 and st["no approval date"] == 1 and st["rejected or deleted"] == 2, "bad API numbers, a missing date, REJ and DEL are skipped: %s" % dict(st))
    check(st["formation rows folded into a permit"] == 24, "the formation rows of one permit are folded into it (24 extra rows): %d" % st["formation rows folded into a permit"])
    docs, rep = M.build(coll, COUNTIES)
    series, cp, ops, pts = (docs[n] for n in M.NAMES)
    check(rep["asof"] == date(2026, 10, 30) and series["through"] == "2026-10-30", "the newest approval is the end of the windows, and 03:00 UTC on Oct 31 is still Oct 30: %s" % rep["asof"])

    # ---- an approval dated after today is a typo in the file: it must not move the windows (it would end every window at that day)
    future = row(api("017", 80), "100", "ACME OIL LLC", date(2026, 12, 1))
    cf = M.collect(rows() + [future], today=date(2026, 10, 31))
    check(cf["stats"]["dated in the future"] == 1 and M.build(cf, COUNTIES)[1]["asof"] == date(2026, 10, 30),
          "an approval dated after today is skipped and counted, and the windows still end on the newest real day: %s" % dict(cf["stats"]))
    check(M.build(M.collect(rows() + [future], today=date(2027, 1, 1)), COUNTIES)[1]["asof"] == date(2026, 12, 1) and "dated in the future" not in M.collect(rows() + [future], today=date(2027, 1, 1))["stats"],
          "the same row is a permit once its day has come (the rule is about today, not about the row)")

    # ---- the series: complete months only, one count per API number and approval day
    got = dict(zip(series["months"], series["permits"]))
    want = {"2025-02": 1, "2025-03": 2, "2025-10": 1, "2026-01": 12, "2026-02": 3, "2026-03": 3}
    check(series["months"][0] == "2019-01" and series["months"][-1] == "2026-09" and len(series["months"]) == 93, "the series runs 2019-01 to the last complete month, 2026-09")
    check({k: v for k, v in got.items() if v} == want, "monthly counts: formations folded once, the reapproved well counted again, RC/AM/REJ/DEL left out: %s" % {k: v for k, v in got.items() if v})
    check("2026-10" not in got, "the current partial month is not in the series")
    check(M.build(coll, COUNTIES, date(2026, 10, 31))[0]["series-permits-ok.json"]["months"][-1] == "2026-10", "windows ending on the last day of a month include it")

    # ---- the counties
    c = cp["counties"]
    check(sorted(c) == ["017", "051", "129"] and cp["noCounty"] == 1, "counties with permits, and the one permit with no county is counted apart: %s noCounty %s" % (sorted(c), cp["noCounty"]))
    check((c["017"]["p12"], c["017"]["p12prev"], c["017"]["depth"]) == (12, 3, 20000), "county 017: 12 in the last 12 months, 3 before, mean depth 20,000: %s" % [c["017"][k] for k in ("p12", "p12prev", "depth")])
    check(c["017"]["m"][16] == 1 and c["017"]["m"][17] == 2 and c["017"]["m"][27] == 12 and sum(c["017"]["m"]) == 15 and len(c["017"]["m"]) == 36, "county 017: 36 monthly counts in the right months")
    check((c["051"]["p12"], c["051"]["p12prev"], c["051"]["depth"]) == (4, 1, 10000) and sum(c["051"]["m"]) == 4,
          "county 051: the Oct 30 permit is in the 12-month count, not in a month (October is not over); the Oct 15, 2025 one is in the 12 before")
    check(c["129"]["p12"] == 2 and c["129"]["ops"] == [], "an individual's permits count in the county and are never named: %s" % c["129"]["ops"])
    check(c["017"]["ops"] == [["ACME OIL LLC", "100", 12]] and c["051"]["ops"] == [["BIG CORP INC", "200", 4]], "top operators are the named ones, with their counts")
    check(cp["months"][0] == "2023-10" and cp["months"][-1] == "2026-09" and len(cp["months"]) == 36, "36 complete months, 2023-10 to 2026-09")

    # ---- the operators
    r = [dict(zip(ops["cols"], x)) for x in ops["rows"]]
    check([x["name"] for x in r] == ["ACME OIL LLC", "BIG CORP INC"], "only the two named operators, the busier first: %s" % [x["name"] for x in r])
    a, b = r
    check((a["band"], a["type"], a["city"], a["state"], a["new12"], a["prev12"], a["all12"], a["all24"], a["last"], a["depth"], a["county"], a["counties"], a["newDrill"])
          == ("A", "LLC", "OKLAHOMA CITY", "OK", 12, 3, 13, 16, "2026-05-04", 20000, "017", 1, 1),
          "ACME: band A, LLC, the office on its newest permit (it moved from Tulsa), 12 + 3 new wells, 13 and 16 permits of every kind, new to drilling: %s" % a)
    check((b["band"], b["type"], b["new12"], b["prev12"], b["all24"], b["last"], b["newDrill"]) == ("B", "corporation", 4, 1, 5, "2026-10-30", 0) and sum(a["m24"]) == 15, "BIG: band B, not new to drilling (a permit in 2005), 24 monthly counts add up")
    check(M.org_type("DEVON ENERGY PRODUCTION COMPANY LP") == "limited partnership" and M.org_type("NADEL AND GUSSMAN, L.L.C.") == "LLC"
          and M.org_type("FASKEN OIL AND RANCH, LTD.") == "limited partnership" and M.org_type("CONTINENTAL RESOURCES INC") == "corporation", "organization type is read from the name")

    # ---- the points
    p = pts["pts"]
    check(len(p) == 21 and pts["ops"] == ["ACME OIL LLC", "BIG CORP INC"] and pts["opNums"] == ["100", "200"], "21 located permits; operators indexed by how many they have: %d" % len(p))
    check(sorted(x[2] for x in p).count(-1) == 2, "an individual's permits are points with no operator (-1)")
    big = [x for x in p if x[5] == 51]
    check(sorted((x[0], x[1]) for x in big)[:2] == [(355000, -985000), (355120, -985120)] or (355120, -985120) in [(x[0], x[1]) for x in big], "locations are rounded to about 100 m: %s" % sorted((x[0], x[1]) for x in big))
    first = min(p, key=lambda x: x[3])
    check(first[3] == (date(2025, 2, 10) - date(2024, 1, 1)).days and first[4] == 200, "a point's day count starts at 2024-01-01 and depth is in hundreds of feet: %s" % first)
    cv = pts["coverage"]
    check(sum(cv["total"]) == 22 and sum(cv["located"]) == 20 and (cv["share12"], cv["share24"]) == (0.895, 0.913), "coverage: located shares %s %s" % (cv["share12"], cv["share24"]))

    # ---- the files check out, and the checker notices faults
    out = os.path.join(TMP, "good")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for name, doc in docs.items():
        M.write_json(os.path.join(out, name), doc)
    good = M.validate(out, COUNTIES)
    check(good == [], "validate accepts what build wrote: %s" % good)

    def fault(label, mutate, expect):
        d = os.path.join(TMP, "fault")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        cur = copy.deepcopy(docs)
        extra = mutate(cur, d)
        for name, doc in cur.items():
            if extra == name:
                continue
            M.write_json(os.path.join(d, name), doc)
        problems = M.validate(d, COUNTIES)
        check(any(expect in x for x in problems), "validate notices %s (%s): %s" % (label, expect, problems[:2]))

    def months_gap(cur, d):
        del cur["series-permits-ok.json"]["months"][40]
    fault("a gap in the months", months_gap, "gap")
    fault("an unnamed operator in a county", lambda cur, d: cur["county-permits-ok.json"]["counties"]["017"]["ops"].append(["JOHN Q PUBLIC", "300", 1]), "county 017")
    fault("an API-like number", lambda cur, d: cur["series-permits-ok.json"].update(src="made from 35017000100000"), "API number")
    fault("a point outside the state", lambda cur, d: cur["permits-ok.json"]["pts"].append([400000, -985000, -1, 100, 100, 17]), "points are malformed")
    fault("a point at full precision", lambda cur, d: cur["permits-ok.json"]["pts"][0].__setitem__(0, cur["permits-ok.json"]["pts"][0][0] + 3), "points are malformed")
    fault("a wrong band", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(0, "A"), "operator 200")
    fault("an unnamed operator row", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(2, "JOHN Q PUBLIC"), "operator 200")
    # the office city and state come straight from the file and are published: a place name and two letters, nothing else
    col = lambda cur, c: cur["operators-ok.json"]["cols"].index(c)  # noqa: E731
    fault("a street address in an operator's city", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(col(cur, "city"), "123 MAIN STREET"), "operator 200")
    fault("a phone number in an operator's city", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(col(cur, "city"), "TULSA 918 555 0100"), "operator 200")
    fault("an e-mail address in an operator's city", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(col(cur, "city"), "JOE@X.COM"), "operator 200")
    fault("a long text in an operator's state", lambda cur, d: cur["operators-ok.json"]["rows"][1].__setitem__(col(cur, "state"), "OKLAHOMA"), "operator 200")
    fault("a phone number anywhere in a file", lambda cur, d: cur["series-permits-ok.json"].update(src="call 918-555-0100 for the list"), "phone number")
    fault("a phone number in brackets anywhere in a file", lambda cur, d: cur["series-permits-ok.json"].update(src="call (918) 555 0100"), "phone number")
    fault("county months that do not add up", lambda cur, d: cur["county-permits-ok.json"]["counties"]["017"]["m"].__setitem__(5, 4), "add up")
    fault("one file with another asOf", lambda cur, d: cur["operators-ok.json"].update(asOf="2026-10-29"), "asOf")
    fault("an oversize file", lambda cur, d: cur["series-permits-ok.json"].update(src="x" * 5000), "budget")
    fault("a missing file", lambda cur, d: "operators-ok.json", "cannot be read")
    fault("coverage that is not the series", lambda cur, d: cur["permits-ok.json"]["coverage"]["total"].__setitem__(5, 99), "coverage")
    return fails


def mutants():
    fails = []
    real = {"nameable": M.D.nameable, "central_day": M.D.central_day, "window_of": M.window_of, "collect": M.collect, "validate": M.validate}

    def run(name, patch):
        patch()
        try:
            got = run_checks(M, quiet=True)
        except Exception as e:  # noqa: BLE001 - a mutant may break the build outright: that is noticed too
            got = ["raised %r" % e]
        finally:
            M.D.nameable, M.D.central_day, M.window_of, M.collect, M.validate = real["nameable"], real["central_day"], real["window_of"], real["collect"], real["validate"]
        ok = bool(got)
        print(("ok   " if ok else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not ok:
            fails.append("mutant survived: " + name)

    run("everyone is named", lambda: setattr(M.D, "nameable", lambda n: True))
    run("nobody is named", lambda: setattr(M.D, "nameable", lambda n: False))
    run("days are UTC days, not Central", lambda: setattr(M.D, "central_day", lambda d: d.date()))
    run("the last 12 months start a month too early", lambda: setattr(M, "window_of", lambda asof: dict(real["window_of"](asof), cut12=real["window_of"](asof)["cut12"] - 31)))

    def formations_count():  # every formation row is a permit of its own
        def collect(rows_, today=None):
            n = [0]

            def spread(rs):
                for r in rs:
                    n[0] += 1
                    yield dict(r, API_Number=r["API_Number"][:5] + "%05d" % n[0] + r["API_Number"][10:])
            return real["collect"](spread(rows_), today)
        M.collect = collect
    run("formation rows each count as a permit", formations_count)

    def once_per_api():  # a well approved a second time is not counted again
        def collect(rows_, today=None):
            seen, kept = set(), []
            for r in rows_:
                k = (r["API_Number"][:10], r["Application_Type"])
                if r["Application_Type"] == "DR" and k in seen:
                    continue
                seen.add(k)
                kept.append(r)
            return real["collect"](kept, today)
        M.collect = collect
    run("a well approved twice is counted once", once_per_api)
    run("an approval dated in the future is a permit", lambda: setattr(M, "collect", lambda rows_, today=None: real["collect"](rows_, date(2100, 1, 1))))

    def lax_validate(out, county_names=None, spec=None):  # the validator before: no phone numbers, no shape for a city or a state
        return [p for p in real["validate"](out, county_names, spec) if "phone number" not in p and not (p.startswith("operator ") and p.endswith("is malformed"))]
    run("the validator does not look at a city, a state or a phone number", lambda: setattr(M, "validate", lax_validate))
    return fails


print("-- the rules")
FAILS += run_checks(M)

print("\n-- the committed files")
if all(os.path.exists(os.path.join(DATA, n)) for n in M.NAMES):
    problems = M.validate(DATA, COUNTIES)
    print(("ok   " if not problems else "FAIL ") + "validate accepts the committed files" + ("" if not problems else ": %s" % problems[:3]))
    FAILS += problems
    ops = json.load(open(os.path.join(DATA, "operators-ok.json")))
    unnamed = [x[2] for x in ops["rows"] if not M.D.nameable(x[2])]
    print(("ok   " if not unnamed else "FAIL ") + "every operator in them passes the naming rule (%d operators)" % len(ops["rows"]))
    FAILS += unnamed
else:
    print("skip  the files are not committed yet")

print("\n-- mutants")
FAILS += mutants()

real = os.environ.get("OK_REAL_FILES", "")
if real and os.path.exists(os.path.join(real, M.MASTER)) and os.path.exists(os.path.join(real, M.DAILY)):
    print("\n-- the real workbooks")
    coll = M.collect(M.iter_rows([os.path.join(real, M.MASTER), os.path.join(real, M.DAILY)]))
    docs, rep = M.build(coll, COUNTIES)
    got = dict(zip(docs["series-permits-ok.json"]["months"], docs["series-permits-ok.json"]["permits"]))
    idx = json.load(open(os.path.join(DATA, "daily-ok", "index.json")))
    seen = {}
    for d in idx["days"]:
        if d.get("dd") and d["dd"] not in seen:
            seen[d["dd"]] = d.get("pn", 0)
    full = {}
    for dd, n in seen.items():
        full[dd[:7]] = full.get(dd[:7], 0) + n
    months = [m for m in sorted(full) if m in got and m != min(full)]  # the archive's first month is partial, the current one is not in the series
    bad = [(m, got[m], full[m]) for m in months if got[m] != full[m]]
    print(("ok   " if months and not bad else "FAIL ") + "the Daily archive and the monthly series agree on %s: %s" % (months, bad or "all equal"))
    FAILS += bad
    print("      real rows: %s" % dict(coll["stats"]))
else:
    print("\nskip  real workbooks: set OK_REAL_FILES to a folder holding %s and %s to compare them with the Daily archive" % (M.MASTER, M.DAILY))

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
