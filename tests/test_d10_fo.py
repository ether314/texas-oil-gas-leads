"""Tests for site/pipeline/d10_fo_monthly.py: the federal offshore (Gulf of America) drilling history, wells spudded, from BSEE's borehole file.

Synthetic boreholes, written the way BSEE's weekly file has them (29 quoted, comma-delimited fields, no header, one row per borehole), cover the
rules (one well is its first ten API digits on the spud day of its earliest borehole, which spud dates are real, the area number, locations inside
the Gulf, no depth, the naming rule, the lag that decides where the files end); the readers refuse a file that is not the file; the validator is run on
what they build and on deliberate faults; mutants patch one rule at a time and require the checks to notice. The committed files and the 63
protraction areas are checked too. With FO_REAL_FILES=<folder holding 5010delimit.zip, compalldelimit.zip and protclip.zip> the real files are read
as well.

Run: python3 -I tests/test_d10_fo.py
"""
import copy
import csv
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
spec = importlib.util.spec_from_file_location("d10", os.path.join(PIPE, "d10_fo_monthly.py"))
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)
M, D = N.M, N.D
import privacy_check as P  # noqa: E402

TMP = tempfile.mkdtemp()
FAILS = []
NAMES = {"024": "Green Canyon", "036": "Mississippi Canyon", "017": "Eugene Island"}  # the numbers of GC, MC and EI in AREA_ORDER (checked below)
ASOF = date(2026, 8, 31)
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ synthetic files
def row(api12, op, spud, area, lat=27.5, lon=-90.1, typ="D", status="COM"):
    """One borehole as the weekly file has it: 29 fields (positions as in BSEE's layout: 0 API, 3 operator, 5 spud, 11 surface area and block, 16 type, 18 status, 20 and 21 surface
    longitude and latitude)."""
    f = [""] * 29
    f[0], f[1], f[2], f[3], f[4], f[5], f[11], f[16], f[18], f[19] = api12, "  001 ", "ST00BP00", op, "WILD    ", spud, area + " 0827 ", typ, status, "05000"
    f[20], f[21] = "%16.6f" % lon, "%16.6f" % lat
    return f


def zip_of(path, member, rows):
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerows(rows)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, buf.getvalue().encode("latin-1"))
    return path


def api(n, side="00"):
    return "6081%06d%s" % (n, side)


def holes():
    out = []
    for i in range(12):                       # Shell: 12 wells in January 2026, area GC
        out.append(row(api(100 + i), "00689", "202601%02d" % (5 + i), "GC", lat=27.51234, lon=-90.11234))
    out.append(row(api(100, "01"), "00689", "20260301", "GC"))                     # a sidetrack of the first well: not another well
    out.append(row(api(500), "00689", "20250310", "GC"))                           # in the 12 before
    out.append(row(api(501), "02481", "20260831", "MC", lat=28.2, lon=-89.0))      # the last day of the files
    out.append(row(api(502), "02481", "20260902", "MC"))                           # after the files end: left out
    out.append(row(api(503), "02481", "20261201", "MC"))                           # after today: not a spud yet
    out.append(row(api(504), "05555", "20260210", "EI"))                           # an individual: counted, never named
    out.append(row(api(505), "09999", "20260211", "EI"))                           # an operator number the company file does not have: counted, unnamed
    out.append(row(api(506), "00689", "20260303", "GC", lat=45.0, lon=-90.0))      # a location outside the Gulf: counted, no point
    out.append(row(api(507), "00689", "20260304", "ZZ"))                           # an area with no shape: counted apart
    out.append(row(api(508), "00689", "", "GC"))                                   # not spudded
    out.append(row(api(509), "00689", "00000000", "GC"))                           # a placeholder
    out.append(row(api(510), "00689", "18990101", "GC"))                           # a year before there was an offshore
    out.append(row(api(511), "00689", "20050607", "GC"))                           # older than the series: only the operator's first spud
    out.append(row(api(512, "00"), "00689", "", "GC"))                             # a well whose original hole has no spud date ...
    out.append(row(api(512, "01"), "00689", "20260305", "GC"))                     # ... but a sidetrack does: its date is the well's
    out.append(row(api(513), "03672", "20260306", "MC"))                           # an operator new to drilling in the last 24 months
    return out


COMPANIES = {"689": "Shell Offshore Inc.", "2481": "BP Exploration & Production Inc.", "5555": "JOHN Q PUBLIC", "3672": "Talos QN Exploration LLC"}
FIRST = None


def company_rows():
    out = [["%05d" % int(n), "19900101", name, name.upper(), "19900101"] + [""] * 14 for n, name in COMPANIES.items()]
    out += [["%05d" % (7000 + i), "19900101", "Filler Company %d Inc." % i, "FILLER", "19900101"] + [""] * 14 for i in range(1100)]
    return out


def files():
    bz = zip_of(os.path.join(TMP, "5010delimit.zip"), "5010.txt", holes() + [row(api(900 + i), "00689", "199001%02d" % (1 + i % 28), "GC") for i in range(30)])
    cz = zip_of(os.path.join(TMP, "compalldelimit.zip"), "compalldelimit.txt", company_rows())
    return bz, cz


def with_small_minimums():
    """The real thresholds describe the real file (55,000 rows); the synthetic one is small."""
    saved = (N.MIN_ROWS, N.MIN_WELLS, N.MIN_RECENT)
    N.MIN_ROWS, N.MIN_WELLS, N.MIN_RECENT = 10, 10, 1
    return saved


def run_checks(quiet=False):
    fails = []

    def chk(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    # ---- the areas, and the lag that decides where the files end
    chk(len(N.AREA_ORDER) == 63 and list(N.AREA_ORDER) == sorted(set(N.AREA_ORDER)) and N.AREA_CODE["AC"] == "001" and N.AREA_CODE["WR"] == "063" and N.AREA_CODE["GC"] == "024"
        and N.AREA_CODE["MC"] == "036" and N.AREA_CODE["EI"] == "017", "63 areas numbered 001 to 063 in the order of their codes (GC 024, MC 036, EI 017)")
    r = N.reliable_asof
    chk(r(date(2026, 10, 31)) == date(2026, 8, 31) and r(date(2026, 10, 29)) == date(2026, 7, 31) and r(date(2026, 10, 30)) == date(2026, 8, 31), "the files end with the newest month that ended 60 or more days ago")
    chk(r(date(2027, 3, 1)) == date(2026, 12, 31), "across a year end")

    # ---- the readers refuse a file that is not the file
    saved = with_small_minimums()
    try:
        bz, cz = files()
        holes_ = N.read_boreholes(bz)
        comp = N.read_companies(cz) if len(COMPANIES) + 1100 >= 1000 else None
    finally:
        N.MIN_ROWS, N.MIN_WELLS, N.MIN_RECENT = saved
    chk(len(holes_) == len(holes()) + 30 and holes_[0]["api"] == api(100) and holes_[0]["op"] == "00689" and holes_[0]["area"] == "GC" and holes_[0]["lat"] == 27.51234, "the borehole file's 29 fields are read: api, operator, spud, area, location")
    chk(comp["689"] == "Shell Offshore Inc." and comp["5555"] == "JOHN Q PUBLIC" and len(comp) == len(COMPANIES) + 1100, "the company file gives {number without zeros: name}, and nothing else of the row is read")
    html = zip_of(os.path.join(TMP, "html.zip"), "5010.txt", [["<html><body>Service unavailable</body></html>"]])
    try:
        N.read_boreholes(html)
        chk(False, "a borehole file that is an error page should raise")
    except ValueError as e:
        chk("not the file" in str(e), "a borehole file that is an error page or of another layout raises: %s" % str(e)[:70])
    try:
        N.read_companies(zip_of(os.path.join(TMP, "tiny.zip"), "c.txt", company_rows()[:10]))
        chk(False, "a company file of ten companies should raise")
    except ValueError as e:
        chk("not the file" in str(e), "a company file with a handful of companies raises")
    try:
        with zipfile.ZipFile(os.path.join(TMP, "two.zip"), "w") as z:
            z.writestr("a.txt", b"x")
            z.writestr("b.txt", b"y")
        N.zip_text(os.path.join(TMP, "two.zip"))
        chk(False, "a zip with two data files should raise")
    except ValueError:
        chk(True, "a zip that holds two data files, not the one expected, raises")

    # ---- what a borehole becomes
    coll = N.collect(holes_, comp, TODAY)
    st = coll["stats"]
    p = {k[0]: v for k, v in coll["permits"].items()}
    chk(st["wells spudded since 2018"] == 21 and st["no real spud date (or one after today)"] == 5 and st["an area with no shape"] == 1, "real spud dates become wells; blank, 0000, 1899 and a date after today are not spud dates: %s" % dict(st))
    chk(p[api(100)[:10]]["day"] == date(2026, 1, 5) and len([k for k in coll["permits"] if k[0] == api(100)[:10]]) == 1,
        "a sidetrack is another borehole of the same well, not another well (the first ten API digits), and the well keeps the earlier spud date")
    chk(p[api(512)[:10]]["day"] == date(2026, 3, 5), "a well whose original hole has no spud date takes the earliest spud date among its boreholes")
    chk(p[api(100)[:10]]["depth"] == 0, "no depth is published (the file has a total depth for few recent wells)")
    chk(p[api(507)[:10]]["county"] == "" and p[api(100)[:10]]["county"] == "024" and p[api(501)[:10]]["county"] == "036", "the area is the number of its code, blank for an area with no shape")
    chk(p[api(506)[:10]]["lat"] is None and p[api(100)[:10]]["lat"] == 27.51234, "a location outside the Gulf is dropped, one inside kept")
    chk(p[api(505)[:10]]["name"] == "" and p[api(100)[:10]]["name"] == "SHELL OFFSHORE INC.", "the name comes from the company file, upper case; an unknown operator number has none")
    chk(coll["first_dr"]["689"] == date(1990, 1, 1) or coll["first_dr"]["689"] <= date(2005, 6, 7), "an operator's first spud is read from every row, whenever it was")
    chk(date(2005, 6, 7) not in {k[2] for k in coll["permits"]}, "a spud before 2018 is only an operator's first, not a well of the series")

    # ---- the files
    docs, rep = M.build(coll, NAMES, ASOF, None, N.SPEC)
    series, cp, ops, pts = (docs[n] for n in N.NAMES)
    got = {m: v for m, v in zip(series["months"], series["permits"]) if v}
    chk(series["months"][0] == "2019-01" and series["months"][-1] == "2026-08" and series["through"] == "2026-08-31", "the series runs 2019-01 to the last month the files cover, 2026-08")
    chk(got == {"2025-03": 1, "2026-01": 12, "2026-02": 2, "2026-03": 4, "2026-08": 1}, "monthly counts: a well once, the sidetrack not counted, Sept 2 after the files end, December after today: %s" % got)
    c = cp["counties"]
    chk(sorted(c) == ["017", "024", "036"] and cp["noCounty"] == 1, "areas with wells, and the well with no area counted apart: %s noCounty %s" % (sorted(c), cp["noCounty"]))
    chk(c["024"]["p12"] == 14 and c["024"]["p12prev"] == 1 and c["024"]["depth"] is None, "area 024 (Green Canyon): Shell's 12, the well outside the box and the sidetrack-dated one in the last 12 months, 1 before, no depth")
    r_ = {x[2]: dict(zip(ops["cols"], x)) for x in ops["rows"]}
    chk(sorted(r_) == ["BP EXPLORATION & PRODUCTION INC.", "SHELL OFFSHORE INC.", "TALOS QN EXPLORATION LLC"], "only named operators: the individual and the unknown number are not in the operators file: %s" % sorted(r_))
    chk(r_["SHELL OFFSHORE INC."]["type"] == "corporation" and r_["TALOS QN EXPLORATION LLC"]["type"] == "LLC" and r_["TALOS QN EXPLORATION LLC"]["newDrill"] in (0, 1)
        and r_["SHELL OFFSHORE INC."]["city"] == "" and r_["SHELL OFFSHORE INC."]["state"] == "", "the type is read from the name; no office is published")
    chk(len(pts["pts"]) > 15 and all(q[0] % 10 == 0 and q[1] % 10 == 0 for q in pts["pts"]), "points: located wells of the last 24 months, rounded to about 100 m")
    text = "".join(json.dumps(d) for d in docs.values())
    chk(P.scan(text, digits=True) == [] and "6081" not in text and "ST00BP00" not in text and "JOHN" not in text, "nothing names an API number, a well, a lease, an individual or an address in what is published")

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
        cur = copy.deepcopy(docs)
        mutate(cur)
        for name, doc in cur.items():
            M.write_json(os.path.join(d, name), doc)
        problems = M.validate(d, NAMES, N.SPEC)
        chk(any(expect in x for x in problems), "validate notices %s (%s): %s" % (label, expect, problems[:2]))
    fault("an unnamed operator", lambda cur: cur["operators-fo.json"]["rows"][0].__setitem__(2, "JOHN Q PUBLIC"), "malformed")
    fault("a point on land far from the Gulf", lambda cur: cur["permits-fo.json"]["pts"].append([450000, -900000, -1, 100, 0, 24]), "points are malformed")
    fault("a Texas county code", lambda cur: cur["permits-fo.json"]["pts"].append([275000, -901000, -1, 100, 0, 1001]), "points are malformed")
    fault("a gap in the months", lambda cur: cur["series-permits-fo.json"]["months"].pop(40), "gap")
    fault("an API-like number", lambda cur: cur["series-permits-fo.json"].update(src="made from 608100000100"), "API number")
    return fails


def mutants():
    fails = []
    real = {"nameable": D.nameable, "reliable": N.reliable_asof, "spud_day": N.spud_day, "AREA_CODE": N.AREA_CODE}
    saved = with_small_minimums()

    def run(name, patch):
        patch()
        try:
            got = run_checks(quiet=True)
        except Exception as ex:  # noqa: BLE001 - a mutant may break the build outright: that is noticed too
            got = ["raised %r" % ex]
        finally:
            D.nameable, N.reliable_asof, N.spud_day, N.AREA_CODE = real["nameable"], real["reliable"], real["spud_day"], real["AREA_CODE"]
        print(("ok   " if got else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)
    run("everyone is named", lambda: setattr(D, "nameable", lambda n: True))
    run("nobody is named", lambda: setattr(D, "nameable", lambda n: False))
    run("no lag: the files end the day before they are read", lambda: setattr(N, "reliable_asof", lambda today, lag=0: today - timedelta(days=1)))
    run("a spud date after today counts (read as a past one)", lambda: setattr(N, "spud_day", lambda text: date(2026, 1, 1) if text == "20261201" else real["spud_day"](text)))
    run("every area is the first area", lambda: setattr(N, "AREA_CODE", {k: "001" for k in real["AREA_CODE"]}))
    N.MIN_ROWS, N.MIN_WELLS, N.MIN_RECENT = saved
    return fails


print("-- the rules")
saved_mins = with_small_minimums()
try:
    FAILS += run_checks()
finally:
    N.MIN_ROWS, N.MIN_WELLS, N.MIN_RECENT = saved_mins

print("\n-- the committed files")
names = N.area_names()
check(len(names) == 63 and sorted(names) == ["%03d" % i for i in range(1, 64)] and names["024"] == "Green Canyon" and names["036"] == "Mississippi Canyon" and names["017"] == "Eugene Island",
      "counties-fo.geo.json holds the 63 protraction areas, numbered as AREA_ORDER numbers them: %d" % len(names))
geo = json.load(open(N.AREAS_GEO))
bad_ring = out_box = 0
for ft in geo["features"]:
    g = ft["geometry"]
    for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        for i, ring in enumerate(poly):
            if len(ring) < 4 or ring[0] != ring[-1]:
                bad_ring += 1
            for x, y in ring:
                out_box += not (N.BOX[2] <= x <= N.BOX[3] and N.BOX[0] <= y <= N.BOX[1])
check(bad_ring == 0 and out_box == 0 and set(ft["properties"].keys()) == {"f", "n"} and os.path.getsize(N.AREAS_GEO) < 60_000,
      "the areas' rings are closed, every point is inside the Gulf box, the properties are {f, n} and the file is small (%d bytes)" % os.path.getsize(N.AREAS_GEO))
sq = [(0, 0), (0.5, 0.001), (1, 0), (1, 1), (0, 1), (0, 0)]
check(len(N.simplify(sq, 0.01)) == 5 and N.simplify(sq, 0.01)[0] == N.simplify(sq, 0.01)[-1] and N.simplify([(0, 0), (1, 0), (0, 1), (0, 0)], 0.5) == [(0, 0), (1, 0), (0, 1), (0, 0)],
      "simplify drops a point within the tolerance and keeps a closed ring")
if all(os.path.exists(os.path.join(DATA, n)) for n in N.NAMES):
    problems = M.validate(DATA, names, N.SPEC)
    check(not problems, "validate accepts the committed files" + ("" if not problems else ": %s" % problems[:3]))
    FAILS += problems
    ops = json.load(open(os.path.join(DATA, "operators-fo.json")))
    check(ops["rows"] and all(D.nameable(x[2]) for x in ops["rows"]), "every operator in them passes the naming rule (%d operators)" % len(ops["rows"]))
    cp = json.load(open(os.path.join(DATA, "county-permits-fo.json")))
    check(all(c["depth"] is None for c in cp["counties"].values()) and set(cp["counties"]) <= set(names), "no area shows a depth, and every area is one of the 63")
    text = "".join(open(os.path.join(DATA, n)).read() for n in N.NAMES)
    check(P.scan(text, digits=True) == [], "no e-mail, address, phone number or API-like number in the committed files")
else:
    print("skip  the files are not committed yet")

real = os.environ.get("FO_REAL_FILES", "")
if real and all(os.path.exists(os.path.join(real, f)) for f in ("5010delimit.zip", "compalldelimit.zip")):
    print("\n-- the real files")
    h, c = N.read_boreholes(os.path.join(real, "5010delimit.zip")), N.read_companies(os.path.join(real, "compalldelimit.zip"))
    k = N.collect(h, c, date.today())
    check(len(h) > 50_000 and len(c) > 3_000 and k["stats"]["wells with a spud date, ever"] > 35_000 and all(a in N.AREA_CODE for a in {x["area"] for x in h if x["area"]}),
          "the real borehole and company files read (%d boreholes, %d companies), and every area code in them is one of the 63" % (len(h), len(c)))

print("\n-- mutants")
FAILS += mutants()

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:3]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
