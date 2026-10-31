"""Tests for site/pipeline/d10_fo_monthly.py: the federal offshore (Gulf of America) drilling history, wells spudded, from BSEE's borehole file.

Synthetic boreholes, written the way BSEE's weekly file has them (29 quoted, comma-delimited fields, no header, one row per borehole), cover the
rules (one well is its first ten API digits on the spud day of its earliest borehole, which spud dates are real, the area number, locations inside
the Gulf, no depth, the naming rule, the lag that decides where the files end); the readers refuse a file that is not the file; the validator is run on
what they build and on deliberate faults; whole runs of the producer (main) on local copies of the files show what it refuses to publish (a truncated file, spud dates that are
not dates, coordinates or companies that moved, an address in a name, an areas file that is not the 63) and that it leaves the committed files as they were; mutants patch one rule
at a time and require the checks to notice. The committed files and the 63
protraction areas are checked too. With FO_REAL_FILES=<folder holding 5010delimit.zip, compalldelimit.zip and protclip.zip> the real files are read
as well.

Run: python3 -I tests/test_d10_fo.py
"""
import contextlib
import copy
import csv
import importlib.util
import io
import json
import os
import re
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
def row(api12, op, spud, area, lat=27.5, lon=-90.1, typ="D", status="COM", td=""):
    """One borehole as the weekly file has it: 29 fields (positions as in BSEE's layout: 0 API, 3 operator, 5 spud, 11 surface area and block, 16 type, 18 status, 20 and 21 surface
    longitude and latitude)."""
    f = [""] * 29
    f[0], f[1], f[2], f[3], f[4], f[5], f[11], f[16], f[18], f[19] = api12, "  001 ", "ST00BP00", op, "WILD    ", spud, area + " 0827 ", typ, status, "05000"
    f[14] = td  # the total-depth date: after the spud date, whenever both are there
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


def old_wells(n=200):
    """n wells of the series' history (2019 to mid 2025), Shell's, in area GC: enough that a file which lost some of them is noticed."""
    return [row(api(2000 + i), "00689", (date(2019, 1, 1) + timedelta(days=i * 12)).strftime("%Y%m%d"), "GC") for i in range(n)]


def night(bz, cz, out, geo=None):
    """One run of the producer's main() on local copies of the files (as the weekly workflow runs it, but with no network): (exit code, what it printed)."""
    saved_argv, saved_geo, buf = sys.argv, N.AREAS_GEO, io.StringIO()
    sys.argv = ["d10", "--out", out, "--dl", os.path.join(TMP, "dl"), "--borehole", bz, "--company", cz, "--today", TODAY.isoformat()]
    if geo:
        N.AREAS_GEO = geo
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                code = N.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                buf.write(str(e.code))
    finally:
        sys.argv, N.AREAS_GEO = saved_argv, saved_geo
    return code, buf.getvalue()


def snapshot(d):
    return {n: open(os.path.join(d, n), "rb").read() for n in sorted(os.listdir(d))}


def review_checks(chk):
    """What an independent review of the first version found: a company's current name, windows that agree, and a producer that refuses a file that is not the file."""
    # ---- the company file has a row for each name and address of a company, sorted by name: the current name is the one with no end date
    extra = [["03407", "20160726", "Array Petroleum, LLC", "ARRAY PETROLEUM LLC", ""] + [""] * 14, ["03407", "20160726", "Array Petroleum, LLC", "ARRAY PETROLEUM LLC", ""] + [""] * 14,
             ["03407", "20151016", "JSJ ENERGY, LLC", "JSJ ENERGY LLC", "20160726"] + [""] * 14,
             ["02970", "20081117", "Castex Offshore, Inc.", "CASTEX OFFSHORE INC", ""] + [""] * 14, ["02970", "20070706", "Castex Offshore, LLC", "CASTEX OFFSHORE LLC", "20081117"] + [""] * 14,
             ["04000", "20000101", "Earlier Name Inc.", "EARLIER", "20080101"] + [""] * 14, ["04000", "20050101", "Newest Name Inc.", "NEWEST", "20100101"] + [""] * 14]
    got = []
    for order in (1, -1):
        got.append(N.read_companies(zip_of(os.path.join(TMP, "names%d.zip" % order), "c.txt", company_rows() + extra[::order])))
    chk(all(c["3407"] == "Array Petroleum, LLC" and c["2970"] == "Castex Offshore, Inc." and c["4000"] == "Newest Name Inc." for c in got),
        "a company that changed its name publishes the current one (no end date), or the one that ended last, whatever the order of the rows: %s" % [(c["3407"], c["2970"], c["4000"]) for c in got])
    odd = N.read_companies(zip_of(os.path.join(TMP, "odd.zip"), "c.txt", company_rows() + [["\u00b2", "20000101", "Not A Number Inc.", "X", ""] + [""] * 14]))
    chk("\u00b2" not in odd and len(odd) == len(COMPANIES) + 1100, "a company number that is a superscript digit (str.isdigit says yes, int says no) is skipped, not a crash")
    odd_hole = N.collect([{"api": api(1), "op": "\u00b2", "spud": "20260105", "td": "", "area": "GC", "lat": 27.5, "lon": -90.1}], COMPANIES, TODAY)
    chk(len(odd_hole["permits"]) == 1 and next(iter(odd_hole["permits"].values()))["op"] == "", "an operator number that is a superscript digit is no operator, not a crash")

    # ---- one year is the same year everywhere: 12 calendar months from the first day, so a county's, an operator's and the series' 12 months add up
    D1 = N.D1
    w_cal, w_day = D1.windows(date(2026, 8, 31), True), D1.windows(date(2026, 8, 31))
    chk(w_cal["cut12"] == date(2025, 9, 1).toordinal() and w_cal["cut24"] == date(2024, 9, 1).toordinal() and w_day["cut12"] == date(2025, 8, 31).toordinal()
        and D1.windows(date(2026, 8, 15), True)["cut12"] == D1.windows(date(2026, 8, 15))["cut12"], "calendar windows start on the first day of the month 11 and 23 months back at a month end, and leave a mid-month asof as it was")
    edge = N.collect([{"api": api(i + 1), "op": "00689", "spud": d, "td": "", "area": "GC", "lat": 27.5, "lon": -90.1}
                      for i, d in enumerate(("20250831", "20250901", "20240831", "20240901", "20260831"))], COMPANIES, TODAY)
    edocs, erep = M.build(edge, NAMES, ASOF, None, N.SPEC)
    es, ec, eo = edocs["series-permits-fo.json"], edocs["county-permits-fo.json"]["counties"], edocs["operators-fo.json"]
    chk(sum(es["permits"][-12:]) == sum(c["p12"] for c in ec.values()) == 2 and sum(es["permits"][-24:-12]) == sum(c["p12prev"] for c in ec.values()) == 2
        and (lambda r: (r[eo["cols"].index("new12")], r[eo["cols"].index("prev12")]))(eo["rows"][0]) == (2, 2),
        "wells on the first and last days of the year windows (Aug 31 and Sep 1) are in the same year for the series, the areas and the operators: 12 months %d, the 12 before %d"
        % (sum(c["p12"] for c in ec.values()), sum(c["p12prev"] for c in ec.values())))
    sentence = N.boreholes_sentence({"spuds": [(date(2025, 8, 31), "a"), (date(2025, 9, 1), "b"), (date(2025, 9, 2), "b"), (date(2026, 8, 31), "c"), (date(2026, 9, 1), "d")],
                                     "permits": {("b", "SP", date(2025, 9, 1)): {}, ("c", "SP", date(2026, 8, 31)): {}}}, ASOF)
    chk(sentence.startswith(". In the 12 months from 2025-09-01") and " 3 boreholes spudded: 2 are the first borehole" in sentence and " 1 are sidetracks" in sentence,
        "the source text says how many boreholes were spudded in the 12 months against the wells counted (the sidetracks and bypasses): %s" % sentence[:160])

    # ---- the producer refuses a file that is not the file, and leaves the committed files as they were
    def files_of(tag, holes_list, comp_rows=None):
        return (zip_of(os.path.join(TMP, "b-%s.zip" % tag), "5010.txt", holes_list), zip_of(os.path.join(TMP, "c-%s.zip" % tag), "c.txt", comp_rows or company_rows()))
    recent = [row(api(3000 + i), "00689", "202604%02d" % (1 + i % 28), "GC") for i in range(40)]  # the real file's last 12 months are all named operators; the synthetic ones above are not
    base_rows = holes() + old_wells() + recent + [row(api(900 + i), "00689", "199001%02d" % (1 + i % 28), "GC") for i in range(30)]
    out = os.path.join(TMP, "night")
    shutil.rmtree(out, ignore_errors=True)
    code, text = night(*files_of("good", base_rows), out)
    chk(code == 0 and sorted(os.listdir(out)) == sorted(N.NAMES), "a whole run on a good file writes the four files and exits 0: exit %s %s" % (code, text[-120:].replace("\n", " | ")))
    committed = snapshot(out)
    code, text = night(*files_of("again", base_rows), out)
    chk(code == 0 and snapshot(out) == committed, "and a second run on the same file changes nothing")
    series0 = json.loads(committed["series-permits-fo.json"].decode())
    chk("12 months from 2025-09-01" in series0["src"] and "sidetracks or bypasses" in series0["src"], "the series' source text carries the sidetrack sentence")

    def refused(label, rows_, why, comp=None, geo=None):
        shutil.rmtree(os.path.join(TMP, "night2"), ignore_errors=True)
        shutil.copytree(out, os.path.join(TMP, "night2"))
        before = snapshot(os.path.join(TMP, "night2"))
        code2, text2 = night(*files_of(label.split()[0][:6], rows_, comp), os.path.join(TMP, "night2"), geo)
        chk(code2 not in (0, None) and why in text2 and snapshot(os.path.join(TMP, "night2")) == before,
            "a file with %s is refused (%r) and the committed files stay as they were: exit %s, %s" % (label, why, code2, text2.strip().replace("\n", " | ")[-110:]))

    refused("a third of its older wells gone (truncated)", base_rows[:len(holes()) + 130] + base_rows[len(holes()) + 200:], "the file lost wells")
    kept = base_rows[:len(holes()) + 197] + base_rows[len(holes()) + 200:]  # three old wells fewer is a correction, not a truncation
    shutil.rmtree(os.path.join(TMP, "night3b"), ignore_errors=True)
    shutil.copytree(out, os.path.join(TMP, "night3b"))
    code3, text3 = night(*files_of("three", kept), os.path.join(TMP, "night3b"))
    chk(code3 == 0, "three older wells fewer than the committed series is within what a rebuild may correct: exit %s %s" % (code3, text3[-100:].replace("\n", " | ")))
    iso = [list(r) for r in base_rows]
    for r in iso[:12]:
        r[5] = "2026-01-05"
    refused("12 spud dates in ISO form (a layout that moved)", iso, "spud dates are not YYYYMMDD")
    few = [list(r) for r in base_rows]
    for r in few[:5]:
        r[5] = "2026-01-05"
    code4, text4 = night(*files_of("fewbad", few), os.path.join(TMP, "night3b"))
    chk(code4 == 0, "five odd spud dates in 55,000 rows are tolerated: exit %s" % code4)
    swapped = [list(r) for r in base_rows]
    for r in swapped:
        r[20], r[21] = r[21], r[20]
    refused("latitude and longitude swapped", swapped, "have a location in the Gulf")
    refused("a company file with none of the operators in it", base_rows, "named operator", comp=[["%05d" % (7000 + i), "19900101", "Filler Company %d Inc." % i, "FILLER", "19900101"] + [""] * 14 for i in range(1100)])
    backwards = [list(r) for r in base_rows]
    for r in backwards:
        r[14] = "19500102" if r[5] else ""  # a real date (after 1940), long before any spud
    refused("every total-depth date before its spud date", backwards, "spud after their total depth")
    refused("a street address in an operator's name", base_rows, "holds an address",
            comp=[["00689", "19900101", "Shell Offshore Inc., 1234 Main Street, Suite 5", "SHELL", ""] + [""] * 14] + [r for r in company_rows() if r[0] != "00689"])
    # an areas file that is not the 63
    geo_doc = json.load(open(N.AREAS_GEO))
    broken = os.path.join(TMP, "geo62.json")
    json.dump(dict(geo_doc, features=[ft for ft in geo_doc["features"] if ft["properties"]["f"] != "024"]), open(broken, "w"))
    shifted = os.path.join(TMP, "geo-shift.json")
    json.dump(dict(geo_doc, features=[dict(ft, properties=dict(ft["properties"], c=N.AREA_ORDER[(N.AREA_ORDER.index(ft["properties"]["c"]) + 1) % 63])) for ft in geo_doc["features"]]), open(shifted, "w"))
    for label, path in (("a feature missing (62 areas)", broken), ("every number shifted by one", shifted)):
        shutil.rmtree(os.path.join(TMP, "night2"), ignore_errors=True)
        shutil.copytree(out, os.path.join(TMP, "night2"))
        code5, text5 = night(*files_of("geo", base_rows), os.path.join(TMP, "night2"), path)
        chk(code5 not in (0, None) and "counties-fo.geo.json" in text5 and snapshot(os.path.join(TMP, "night2")) == committed, "an areas file with %s stops the run before anything is written: %s" % (label, text5.strip()[-100:]))
    chk(N.area_problems() == [] and N.area_problems(broken) != [] and N.area_problems(shifted) != [] and N.area_problems(os.path.join(TMP, "nothing.json")) != [], "the areas file check passes the committed file and not the damaged ones")
    # --check reads the operators' names too
    d_addr = os.path.join(TMP, "addr")
    shutil.rmtree(d_addr, ignore_errors=True)
    shutil.copytree(out, d_addr)
    ops_doc = json.load(open(os.path.join(d_addr, "operators-fo.json")))
    ops_doc["rows"][0][2] = "SHELL OFFSHORE INC. P.O. BOX 4411"
    json.dump(ops_doc, open(os.path.join(d_addr, "operators-fo.json"), "w"))
    saved_argv = sys.argv
    try:
        sys.argv = ["d10", "--check", "--out", d_addr]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code6 = N.main()
    finally:
        sys.argv = saved_argv
    chk(code6 == 1 and "holds an address" in buf.getvalue() and "BOX" not in buf.getvalue(), "--check on files whose operator name holds a P.O. box fails, and the log shows the name's shape, not the name")
    names_ok = ["Shell Offshore Inc.", "BP Exploration & Production Inc.", "Main Street Energy LLC", "Fieldwood Energy III LLC", "1st Choice Offshore LLC", "W&T Offshore, Inc.", "Murphy Exploration & Production Company - USA"]
    names_bad = ["Shell Offshore Inc., 1234 Main Street, Suite 5", "ACME OIL PO BOX 4411", "Acme Energy LLC 500 Poydras St", "Acme P.O. Box 9", "Acme Energy, Ste 200"]
    chk(N.address_problems(names_ok) == [] and len(N.address_problems(names_bad)) == len(names_bad), "the address check passes real company names and stops a street, a suite and a post-office box")


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
    review_checks(chk)
    return fails


def mutants():
    fails = []
    real = {"nameable": D.nameable, "reliable": N.reliable_asof, "spud_day": N.spud_day, "AREA_CODE": N.AREA_CODE, "read_companies": N.read_companies, "guard": N.guard,
            "area_problems": N.area_problems, "ADDRESS": N.ADDRESS, "SPEC": dict(N.SPEC)}
    saved = with_small_minimums()

    def run(name, patch):
        patch()
        try:
            got = run_checks(quiet=True)
        except Exception as ex:  # noqa: BLE001 - a mutant may break the build outright: that is noticed too
            got = ["raised %r" % ex]
        finally:
            D.nameable, N.reliable_asof, N.spud_day, N.AREA_CODE = real["nameable"], real["reliable"], real["spud_day"], real["AREA_CODE"]
            N.read_companies, N.guard, N.area_problems, N.ADDRESS = real["read_companies"], real["guard"], real["area_problems"], real["ADDRESS"]
            N.SPEC.clear()
            N.SPEC.update(real["SPEC"])
        print(("ok   " if got else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)
    run("everyone is named", lambda: setattr(D, "nameable", lambda n: True))
    run("nobody is named", lambda: setattr(D, "nameable", lambda n: False))
    run("no lag: the files end the day before they are read", lambda: setattr(N, "reliable_asof", lambda today, lag=0: today - timedelta(days=1)))
    run("a spud date after today counts (read as a past one)", lambda: setattr(N, "spud_day", lambda text: date(2026, 1, 1) if text == "20261201" else real["spud_day"](text)))
    run("every area is the first area", lambda: setattr(N, "AREA_CODE", {k: "001" for k in real["AREA_CODE"]}))

    def last_row_wins(path):  # the first version: the last row of a company is its name, though the file is sorted by name and not by date
        out = {}
        for r in csv.reader(io.StringIO(N.zip_text(path))):
            if len(r) == 19 and r[0].strip().isdigit():
                out[str(int(r[0].strip()))] = " ".join(r[2].split())
        if len(out) < 1000:
            raise ValueError("not the file")
        return out
    run("the last row of a company is its name", lambda: setattr(N, "read_companies", last_row_wins))
    run("no guard: whatever parses is published", lambda: setattr(N, "guard", lambda docs, rep, coll, old_series=None: []))
    run("the areas file is not checked", lambda: setattr(N, "area_problems", lambda path=None: []))
    run("an address in a name is not noticed", lambda: setattr(N, "ADDRESS", re.compile(r"(?!x)x")))
    run("a year is the 365 days that end on the as-of day", lambda: N.SPEC.update(calendar_windows=False))
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
check(bad_ring == 0 and out_box == 0 and set(ft["properties"].keys()) == {"f", "n", "c"} and os.path.getsize(N.AREAS_GEO) < 60_000,
      "the areas' rings are closed, every point is inside the Gulf box, the properties are {f, n, c} and the file is small (%d bytes)" % os.path.getsize(N.AREAS_GEO))
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

# the EIA's monthly estimate of the federal offshore's crude oil (d8_ok_context.py --state FO), the offshore's one figure of production
sys.path.insert(0, PIPE)
ctx_spec = importlib.util.spec_from_file_location("ctx", os.path.join(PIPE, "d8_ok_context.py"))
C = importlib.util.module_from_spec(ctx_spec)
ctx_spec.loader.exec_module(C)
import d3_markets_infra as D3  # noqa: E402
fo_eia = json.load(open(os.path.join(DATA, "series-fo.json")))
check(C.validate(fo_eia, "FO") == [], "series-fo.json (the EIA's federal offshore crude) is clean: %s" % C.validate(fo_eia, "FO"))
check(any("plausible range" in x for x in C.validate(dict(fo_eia, foCrude=[v * 100 for v in fo_eia["foCrude"]]), "FO")) and any("plausible range" in x for x in C.validate(dict(fo_eia, foCrude=[v // 100 for v in fo_eia["foCrude"]]), "FO")),
      "a series in the wrong units (per day, or a hundred times too big) is caught")
nm_eia = json.load(open(os.path.join(DATA, "series-nm.json")))
check(C.validate(fo_eia, "NM") != [] and C.validate(nm_eia, "FO") != [] and C.validate(fo_eia, "OK") != [], "the offshore's file is not taken for another state's, nor theirs for it")
check(C.STATE_SPECS["FO"]["SPEC"]["sid"] == "MCRFP3FM1" and C.STATE_SPECS["FO"]["key"] == "foCrude" and C.STATE_SPECS["FO"]["out"].endswith("series-fo.json")
      and C.STATE_SPECS["FO"]["SPEC"]["lo"] < min(v for v in fo_eia["foCrude"]) and max(fo_eia["foCrude"]) < C.STATE_SPECS["FO"]["SPEC"]["hi"], "its series, key, file and plausible range (every month since 2019 inside it)")


def eia_page(title, rows):
    body = "".join("<tr><td>%s</td>%s</tr>" % (y, "".join("<td>%s</td>" % v for v in vals)) for y, vals in rows)
    hdr = "<tr><td>Year</td>%s</tr>" % "".join("<td>%s</td>" % m for m in D3.MONTHS)
    return "<html><head><title>%s</title></head><body><table>%s%s</table><p>Release Date: 10/30/2026</p></body></html>" % (title, hdr, body)


page_ok = os.path.join(TMP, "eia-ok.html")
open(page_ok, "w").write(eia_page("Federal Offshore--Gulf of America Field Production of Crude Oil (Thousand Barrels)", [(2026, ["63,853", "55,561", "61,684", "NA", "", "", "", "", "", "", "", ""])]))
title, values, release = D3.parse_eia_monthly(page_ok, C.STATE_SPECS["FO"]["SPEC"])
check(values[(2026, 1)] == 63853.0 and values[(2026, 4)] is None and release == "2026-10-30", "the parser reads an offshore page of the EIA's shape (thousands separators, a month with no value yet, the release date)")
for label, ttl in (("Texas", "Texas Field Production of Crude Oil (Thousand Barrels)"), ("the Pacific offshore", "Federal Offshore--Pacific Field Production of Crude Oil (Thousand Barrels)"),
                   ("the per-day series", "Federal Offshore--Gulf of America Field Production of Crude Oil (Thousand Barrels per Day)")):
    page_bad = os.path.join(TMP, "eia-bad.html")
    open(page_bad, "w").write(eia_page(ttl, [(2026, ["1"] * 12)]))
    try:
        D3.parse_eia_monthly(page_bad, C.STATE_SPECS["FO"]["SPEC"])
        refused = False
    except SystemExit as e:
        refused = "unexpected series title" in str(e)
    check(refused, "a page for %s is refused" % label)

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
