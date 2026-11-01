#!/usr/bin/env python3
"""D10: the federal offshore (Gulf of America) drilling history, for the Overview, the Map and the Operators page of the Oil tracker.

The Bureau of Safety and Environmental Enforcement (BSEE) publishes every borehole drilled on the federal Outer Continental Shelf as a
weekly file on its Data Center (https://www.data.bsee.gov/Well/Files/5010delimit.zip, "All Releasable Borehole Information": one row per
borehole with its API well number, operator number, spud date, protraction area and block, water depth, surface location, type and
status), the operators' names as another (https://www.data.bsee.gov/Company/Files/compalldelimit.zip), and the official protraction
areas as shapes (https://www.data.bsee.gov/Mapping/Files/protclip.zip). This reads them and writes four files into site/public/data/,
shaped like New Mexico's (d9_nm_monthly.py), Oklahoma's and Texas's, so every view treats the states alike, and the outlines of the areas:

  series-permits-fo.json   wells spudded by month since 2019-01 (complete months only)
  county-permits-fo.json   per area: the last 12 months and the 12 before, 36 monthly counts, top operators
  operators-fo.json        the named operators that spudded a well in the last 24 months
  permits-fo.json          one point per well spudded in the last 24 months, at its surface location (rounded to about 100 m)
  counties-fo.geo.json     the 63 protraction areas (an "area" is this state's county: 001 to 063 in the order of the two-letter area codes)

What is counted is wells SPUDDED, like New Mexico's and for the same reason: the permit (APD) approvals BSEE publishes are an online query,
not a file, and the borehole file says when drilling began, not when the permit was approved (NOTES_D10.md has the numbers). A well is one
API number (its first ten digits: a sidetrack or bypass is another borehole of the same well and is not counted: the series' source text says how many boreholes
were spudded in the last 12 months against the wells counted), on the spud day of its earliest borehole.
Offshore drilling is small next to the land states (about 45 wells a year since 2024), and a spud is reported with some delay and the
file is made weekly, so a month is shown only when it ended at least LAG_DAYS days ago. The file carries a total depth for few recent wells
(it arrives after completion), so no depth is published; the water depth, which is always there, is not one either.

  python3 -I site/pipeline/d10_fo_monthly.py [--out DIR] [--dl DIR] [--asof YYYY-MM-DD] [--today YYYY-MM-DD]
  python3 -I site/pipeline/d10_fo_monthly.py --check [--out DIR]       only reload and check what is already there
  python3 -I site/pipeline/d10_fo_monthly.py --areas [--dl DIR]        rebuild counties-fo.geo.json from BSEE's protraction areas

Operators are named only by the corporate rule (d8_ok_daily.nameable: a corporation, LLC or partnership, never a person's dba). Nothing names a
well, a lease, a platform or an API number, and no address or contact in the company file is read (only its number, name and the dates of the name).
The files are parsed, never run; requests identify no person.

A weekly rebuild writes nothing when the file looks wrong (guard() below): a borehole file that lost wells (the older months of the committed series
may not shrink by more than a few percent), spud dates that are not dates, spud dates that come after the total-depth date, wells with no location
in the Gulf, wells whose operator is not named, an operator name that holds a street address, and an areas file that is not the 63 areas numbered
here. The next run starts again from the files as committed.
"""
import argparse
import collections
import csv
import io
import json
import math
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d1_permits_geo as D1  # noqa: E402,F401
import d8_ok_daily as D  # noqa: E402
import d8_ok_monthly as M  # noqa: E402
import privacy_check as P  # noqa: E402

FILES = "https://www.data.bsee.gov/"
BOREHOLE, COMPANY, AREAS_ZIP = "Well/Files/5010delimit.zip", "Company/Files/compalldelimit.zip", "Mapping/Files/protclip.zip"
UA = "Mozilla/5.0 (research script)"
OUT = os.path.join(SITE, "public", "data")
DL = os.path.join(os.path.dirname(SITE), "dl", "fo")
AREAS_GEO = os.path.join(OUT, "counties-fo.geo.json")
NAMES = ("series-permits-fo.json", "county-permits-fo.json", "operators-fo.json", "permits-fo.json")
LAG_DAYS = 60  # a month is shown once it ended this long ago (reports and the weekly file come in over weeks, and a month holds only about four wells)
BOX = (23.5, 31.0, -98.5, -80.5)  # the federal Gulf, as (lat min, lat max, lon min, lon max)
KEEP_FROM = 2018
MIN_ROWS, MIN_WELLS, MIN_RECENT = 40_000, 30_000, 20  # a borehole file with fewer rows, wells, or wells spudded in the last 24 months is not the file (55,575, 38,290 and 128 in 2026)
# the protraction areas, in the order that numbers them 001 to 063 (the order of their two-letter codes; --areas refuses shapes that are not exactly these)
AREA_ORDER = ("AC", "AM", "AP", "AT", "BA", "BM", "BS", "CA", "CC", "CE", "CH", "DC", "DD", "DT", "EB", "EC", "EI", "EL", "EW", "FM", "FP", "GA", "GB", "GC", "GI", "GV", "HE",
              "HH", "HI", "KC", "KW", "LL", "LS", "LU", "MA", "MC", "MI", "MO", "MP", "MU", "PB", "PE", "PI", "PL", "PN", "PR", "PS", "RK", "SA", "SE", "SM", "SP", "SS", "ST",
              "SX", "TP", "TV", "VK", "VN", "VR", "WC", "WD", "WR")
AREA_CODE = {a: "%03d" % (i + 1) for i, a in enumerate(AREA_ORDER)}
CODE_OF = {n: a for a, n in AREA_CODE.items()}
# what a rebuild must look like before it replaces the committed files (guard() below). The numbers in brackets are today's.
MAX_BAD_DATES = 10      # spud dates that are not dates (a typo in 55,000 rows is tolerated, a layout that moved is not) [0]
MIN_LOCATED = 0.9       # share of the last 24 months' wells with a location inside the Gulf [1.0]
MIN_NAMED = 0.9         # share of the last 12 months' wells whose operator is named [1.0]
MAX_SHRINK, SHRINK_SLACK = 0.03, 3   # the wells of the months before the last 12 may be fewer than the committed series' by this share, plus a few [0 lost]
MAX_BACKWARDS = 0.01    # share of the boreholes with a spud and a total-depth date whose spud comes later [0]
MAX_NO_AREA = 0.02      # share of the wells of the last 36 months that may belong to no area of the file (a few for a new area code) [0]
# a street address or a post-office box inside a company name is not a name (the company file has the addresses in other fields, which are never read)
ADDRESS = re.compile(r"\bP\.?\s?O\.?\s?BOX\b|\b(?:SUITE|STE\.?)\s+\w|\b\d{1,6}\s+(?:[A-Z0-9.]+\s+){1,3}(?:STREET|ST|AVENUE|AVE|ROAD|RD|BLVD|BOULEVARD|DRIVE|DR|LANE|LN|HIGHWAY|HWY|PARKWAY|PKWY)\b", re.I)
log = D.log


# ------------------------------------------------------------------------------------------------ the files

def zip_text(path, want=".txt"):
    """The text of the one data member of a BSEE zip, as ISO-8859-1 (the files are plain delimited text)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(want) and not n.endswith("/")]
        if len(names) != 1:
            raise ValueError("%s holds %d %s files, not the one expected" % (os.path.basename(path), len(names), want))
        return z.read(names[0]).decode("latin-1")


def read_boreholes(path):
    """The boreholes of the weekly file as dicts of what is used: api (12 digits), op (operator number), spud and td (the spud and total-depth dates,
    YYYYMMDD or ''), area (two letters), lat, lon. The file has 29 comma-delimited, quoted fields and no header; a file that is not that (an error page, another layout) raises."""
    rows, bad = [], 0
    for r in csv.reader(io.StringIO(zip_text(path))):
        if len(r) != 29 or not re.fullmatch(r"\d{12}", r[0].strip()):
            bad += 1
            continue
        lat, lon = r[21].strip(), r[20].strip()
        rows.append({"api": r[0].strip(), "op": r[3].strip(), "spud": r[5].strip(), "td": r[14].strip(), "area": r[11].strip()[:2], "type": r[16].strip(), "status": r[18].strip(),
                     "lat": float(lat) if re.fullmatch(r"-?\d+(\.\d+)?", lat) else None, "lon": float(lon) if re.fullmatch(r"-?\d+(\.\d+)?", lon) else None})
    if len(rows) < MIN_ROWS or bad > len(rows) * 0.01:
        raise ValueError("the borehole file holds %d usable rows and %d unusable ones: it is not the file this script reads (expected about 55,000)" % (len(rows), bad))
    return rows


def read_companies(path):
    """{operator number (no leading zeros): name} from the company file (19 comma-delimited fields; only the number, the start and end dates and the full name are read).
    The file has a row for each name and each address a company has had, sorted by name and not by date, so the last row is not the current name (a
    company that became "Array Petroleum, LLC" in 2016 follows "JSJ ENERGY, LLC" in the file). The name published is the current one (no end date),
    else the one that ended last."""
    best = {}
    for r in csv.reader(io.StringIO(zip_text(path))):
        if len(r) == 19 and re.fullmatch(r"[0-9]+", r[0].strip()):
            name = " ".join(r[2].split())
            if not name:
                continue
            end, start = r[4].strip(), r[1].strip()
            rank = (end == "", end, start, name)  # a row with no end date first, then the newest end, the newest start; the name only settles a tie the same way every time
            num = str(int(r[0].strip()))
            if num not in best or rank > best[num][0]:
                best[num] = (rank, name)
    out = {num: name for num, (_, name) in best.items()}
    if len(out) < 1000:
        raise ValueError("the company file holds %d companies: it is not the file this script reads (expected about 5,500)" % len(out))
    return out


def spud_kind(text):
    """'blank' (no spud date: a well canceled or not yet spudded), 'bad' (not a YYYYMMDD date: the file's layout may have moved), 'old' (a date before
    1940: a placeholder) or 'ok'."""
    text = (text or "").strip()
    if not text:
        return "blank"
    if not re.fullmatch(r"[0-9]{8}", text):
        return "bad"
    try:
        d = datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return "bad"
    return "ok" if d.year >= 1940 else "old"


def spud_day(text):
    return datetime.strptime(text.strip(), "%Y%m%d").date() if spud_kind(text) == "ok" else None


# ------------------------------------------------------------------------------------------------ the records

def clean_name(text):
    return " ".join((text or "").upper().split())


def collect(boreholes, companies, today=None):
    """Fold the boreholes into the record shape d8_ok_monthly.build reads. Returns {'permits', 'first_dr', 'stats'}; a record is a dict of api, kind ('SP': a
    spud), day, op, name, city, state, depth, lat, lon, county. A well is one record: its first ten API digits, on the spud day of its earliest borehole (a
    sidetrack or bypass is another borehole of the same well). first_dr is the day of each operator's first spud in the file, whenever."""
    today = today or date.today()
    lat_lo, lat_hi, lon_lo, lon_hi = BOX
    st = collections.Counter()
    first = {}  # api10 -> the earliest borehole with a real spud date
    spuds = []  # (day, api10) of every borehole with a real spud date: the wells counted and the sidetracks and bypasses that are not
    for b in boreholes:
        st["boreholes"] += 1
        kind = spud_kind(b["spud"])
        if kind == "bad":
            st["spud date that is not a date"] += 1
        td = spud_day(b.get("td", ""))
        d = spud_day(b["spud"])
        if d is not None and td is not None:
            st["boreholes with a spud and a total-depth date"] += 1
            if d > td:
                st["spud after the total-depth date"] += 1
        if d is None or d > today:
            st["no real spud date (or one after today)"] += 1
            continue
        k = b["api"][:10]
        spuds.append((d, k))
        if k not in first or d < first[k][0]:
            first[k] = (d, b)
    first_dr, permits = {}, {}
    for k, (d, b) in first.items():
        op = str(int(b["op"])) if re.fullmatch(r"[0-9]+", b["op"]) else ""
        if op and (op not in first_dr or d < first_dr[op]):
            first_dr[op] = d
        if d.year < KEEP_FROM:
            st["older than the series"] += 1
            continue
        lat, lon = b["lat"], b["lon"]
        located = lat is not None and lon is not None and lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi
        code = AREA_CODE.get(b["area"], "")
        if not code:
            st["an area with no shape"] += 1
        permits[(k, "SP", d)] = {"api": k, "kind": "SP", "day": d, "op": op, "name": clean_name(companies.get(op)), "city": "", "state": "", "depth": 0,
                                 "lat": lat if located else None, "lon": lon if located else None, "county": code}
        st["wells spudded since %d" % KEEP_FROM] += 1
    st["wells with a spud date, ever"] = len(first)
    return {"permits": permits, "first_dr": first_dr, "stats": st, "spuds": spuds}


def reliable_asof(today, lag=LAG_DAYS):
    """The last day of the newest month that ended at least `lag` days ago: where the files end."""
    cut = today - timedelta(days=lag)
    return cut if (cut + timedelta(days=1)).month != cut.month else cut.replace(day=1) - timedelta(days=1)


SPEC = {
    "api_state": ("60", "17", "42", "01", "23"), "names": NAMES,  # BSEE: 60 is the federal offshore; a borehole near the coast can carry its nearest Gulf state's code (2 of 90 in 2026: Louisiana's 17)
    "box": BOX, "new_kind": "SP", "county_of": lambda r: r["county"],
    "calendar_windows": True,  # the files end on a month end, so "the last 12 months" are 12 calendar months, as the monthly series counts them
    "src": lambda asof, modified: ("Bureau of Safety and Environmental Enforcement, borehole data (the weekly all-releasable-borehole file%s): wells by spud date, one per "
                                   "API well number, by month spudded. A spud is reported with some delay, so the series ends with the newest month that ended at least "
                                   "%d days before; spuds through %s" % (", made " + modified[:10] if modified else "", LAG_DAYS, asof.isoformat())),
}


# ------------------------------------------------------------------------------------------------ the areas

def simplify(ring, tol):
    """Douglas-Peucker on a closed ring (lon, lat pairs), keeping at least 4 points; tol in degrees."""
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    if len(pts) <= 4:
        return ring

    def far(a, b, p):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))

    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, at = 0.0, -1
        for k in range(i + 1, j):
            d = far(pts[i], pts[j], pts[k])
            if d > best:
                best, at = d, k
        if best > tol:
            keep.add(at)
            stack += [(i, at), (at, j)]
    out = [pts[i] for i in sorted(keep)]
    if len(out) < 3:
        out = pts[:3]
    return out + [out[0]]


def build_areas(zip_path, out_path):
    """The protraction areas from BSEE's clipped shapes, as one feature per two-letter area code (001 to 063), simplified to about a kilometer. The shapes
    must be exactly the 63 areas of AREA_ORDER: another set means the numbering above has to be looked at before anything is written."""
    import d2_layers as D2
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        pick = lambda ext: next(n for n in names if n.lower().endswith(ext))  # noqa: E731
        shp, dbf = z.read(pick(".shp")), z.read(pick(".dbf"))
    rows, shapes = D2.read_dbf(dbf), D2.read_shp(shp)
    by = collections.defaultdict(list)
    rows_number = {}  # id(rings) -> the diagram's own number (PROT_NUMBE), kept to tell two areas of one name apart
    for row, rings in zip(rows, shapes):
        if row and rings:
            by[row["AREA_CODE"].strip()].append((row["PROT_NAME"].strip(), rings))
            rows_number[id(rings)] = (row.get("PROT_NUMBE") or "").strip()
    if tuple(sorted(by)) != AREA_ORDER:
        raise ValueError("the shapes hold areas %s, not the 63 this script numbers (AREA_ORDER)" % sorted(set(by) ^ set(AREA_ORDER)))
    name_of = {code: re.sub(r" Area$", "", min((n for n, _ in parts), key=len)) for code, parts in by.items()}
    for name, n in collections.Counter(name_of.values()).items():
        if n > 1:  # two areas with one name (Sabine Pass, off Louisiana and off Texas): the diagram's own number tells them apart
            for code, parts in by.items():
                if name_of[code] == name:
                    number = min((rows_number[id(rings)] for _, rings in parts), default="")
                    name_of[code] = "%s (%s)" % (name, number) if number else name
    out = {}
    for code, parts in by.items():
        polys = []
        for _, rings in parts:
            for poly in D2.rings_to_polys(rings):
                polys.append([simplify(r, 0.01) for r in poly])
        out[AREA_CODE[code]] = {"n": name_of[code], "polys": D2.finalize(polys)}
    doc = D2.build_counties_doc(out)
    for ft in doc["features"]:
        ft["properties"]["c"] = CODE_OF[ft["properties"]["f"]]  # the two-letter code, so a rebuild can check that the numbering is still the one this script uses
    D.write_json(out_path, doc)
    return len(out)


def area_names():
    try:
        with open(AREAS_GEO, encoding="utf-8") as f:
            return {x["properties"]["f"]: x["properties"]["n"] for x in json.load(f)["features"]}
    except (OSError, ValueError):
        return {}


def area_problems(path=None):
    """What is wrong with counties-fo.geo.json for this script: not exactly the 63 areas, or a number that is not the one AREA_ORDER gives the area's code. A file with
    an area missing, shifted or renamed would put wells in the wrong area or in none, and publish it."""
    try:
        with open(path or AREAS_GEO, encoding="utf-8") as f:
            feats = json.load(f)["features"]
    except (OSError, ValueError, KeyError) as e:
        return ["the areas file cannot be read (%s)" % type(e).__name__]
    got = {x["properties"].get("f"): x["properties"] for x in feats}
    bad = []
    if len(feats) != 63 or sorted(got) != ["%03d" % i for i in range(1, 64)]:
        bad.append("the areas file holds %d features numbered %s, not the 63 areas 001 to 063" % (len(feats), sorted(got)[:3] + ["..."] if len(got) > 3 else sorted(got)))
    wrong = [f for f, pr in got.items() if CODE_OF.get(f) != pr.get("c") or not pr.get("n")]
    if wrong:
        bad.append("areas %s do not carry the two-letter code (and a name) that AREA_ORDER gives their number: rebuild the file with --areas" % wrong[:4])
    return bad


# ------------------------------------------------------------------------------------------------ what a rebuild must look like

def address_problems(names):
    """Names (operators, from the files built or committed) that hold a street address or a post-office box: the privacy gate's own scan misses a street."""
    return ["an operator name holds an address (its shape: %s)" % P.mask(n) for n in names if ADDRESS.search(n)]


def window_start(asof):
    """The first day of the 12 calendar months that end on asof (the day windows of a month-end file)."""
    return date.fromordinal(D1.windows(asof, True)["cut12"])


def boreholes_sentence(coll, asof):
    """What the wells counted leave out, for the series' source text: the boreholes spudded in the last 12 months against the wells counted (the rest are
    sidetracks and bypasses, which are drilling but not another well)."""
    lo = window_start(asof)
    boreholes = sum(1 for d, _ in coll["spuds"] if lo <= d <= asof)
    wells = sum(1 for k in coll["permits"] if lo <= k[2] <= asof)
    return (". In the 12 months from %s the file shows %d boreholes spudded: %d are the first borehole of a well (the wells counted here) and %d are sidetracks or "
            "bypasses of a well, which are not counted." % (lo.isoformat(), boreholes, wells, max(0, boreholes - wells)))


def guard(docs, rep, coll, old_series=None):
    """The reasons not to replace the committed files with what was just built (an empty list: go ahead). Each guards against a file that parses and is
    not the file: truncated, in another layout, or missing its companies."""
    bad = []
    st = coll["stats"]
    if st["spud date that is not a date"] > MAX_BAD_DATES:
        bad.append("%d spud dates are not YYYYMMDD dates (at most %d tolerated): the file's layout may have moved" % (st["spud date that is not a date"], MAX_BAD_DATES))
    both = st["boreholes with a spud and a total-depth date"]
    if both and st["spud after the total-depth date"] > both * MAX_BACKWARDS:
        bad.append("%d of %d boreholes with both dates spud after their total depth: the date columns may have moved" % (st["spud after the total-depth date"], both))
    cov = docs[NAMES[3]]["coverage"]
    if rep["t12"] and cov["share24"] < MIN_LOCATED:
        bad.append("only %.0f%% of the last 24 months' wells have a location in the Gulf (at least %.0f%% expected): the coordinates may have moved" % (100 * cov["share24"], 100 * MIN_LOCATED))
    if rep["named_share12"] is not None and rep["named_share12"] < MIN_NAMED:
        bad.append("only %.0f%% of the last 12 months' wells have a named operator (at least %.0f%% expected): the company file may be cut short or in another layout"
                   % (100 * rep["named_share12"], 100 * MIN_NAMED))
    wells36 = sum(1 for k in coll["permits"] if k[2] >= date.fromordinal(D1.windows(rep["asof"], True)["cut12"]) - timedelta(days=730))
    if rep["no_county"] > wells36 * MAX_NO_AREA + 2:
        bad.append("%d wells of the last 36 months belong to no area of counties-fo.geo.json: the areas file or the area codes have moved" % rep["no_county"])
    bad += address_problems(row[2] for row in docs[NAMES[2]]["rows"])
    if old_series:
        new, old = docs[NAMES[0]], old_series
        if len(new["months"]) >= 12 and old.get("months") and old.get("permits"):
            cut = new["months"][-12]  # the months before the last 12 are history: late spud dates may add to it, a rebuild must not lose a share of it
            new_by, old_by = dict(zip(new["months"], new["permits"])), dict(zip(old["months"], old["permits"]))
            common = [m for m in old_by if m in new_by and m < cut]
            was, now = sum(old_by[m] for m in common), sum(new_by[m] for m in common)
            if now < was * (1 - MAX_SHRINK) - SHRINK_SLACK:
                bad.append("the %d wells of the months before %s in the committed series are %d in this build: the file lost wells (at most %.0f%% and %d fewer expected)"
                           % (was, cut, now, 100 * MAX_SHRINK, SHRINK_SLACK))
    return bad


# ------------------------------------------------------------------------------------------------ run

def main():
    ap = argparse.ArgumentParser(description="D10: the federal offshore drilling history files (see the module docstring)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dl", default=DL)
    ap.add_argument("--today", help="treat this as today (default the real day)")
    ap.add_argument("--asof", help="end the windows on this day (default: the newest month that ended at least %d days ago)" % LAG_DAYS)
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    ap.add_argument("--areas", action="store_true", help="rebuild counties-fo.geo.json from BSEE's protraction areas")
    ap.add_argument("--borehole", help="a local copy of the borehole zip (default: download it)")
    ap.add_argument("--company", help="a local copy of the company zip (default: download it)")
    a = ap.parse_args()
    if a.areas:
        zp = os.path.join(a.dl, "protclip.zip")
        os.makedirs(a.dl, exist_ok=True)
        if not os.path.exists(zp):
            D.fetch(FILES + AREAS_ZIP, zp)
        log("wrote %s with %d areas" % (AREAS_GEO, build_areas(zp, AREAS_GEO)))
        return 0
    names = area_names()
    if not names:
        sys.exit("counties-fo.geo.json is missing: run with --areas first")
    bad_areas = area_problems()
    if bad_areas:
        sys.exit("counties-fo.geo.json: " + "; ".join(bad_areas))
    if a.check:
        problems = M.validate(a.out, names, SPEC)
        try:
            with open(os.path.join(a.out, NAMES[2]), encoding="utf-8") as f:
                problems += address_problems(row[2] for row in json.load(f)["rows"])
        except (OSError, ValueError, KeyError, IndexError):
            problems.append("operators-fo.json cannot be read for the address check")
        for p in problems:
            log("CHECK failed: " + p)
        log("checks ok (%s)" % a.out if not problems else "%d problem(s)" % len(problems))
        return 1 if problems else 0
    today = date.fromisoformat(a.today) if a.today else date.today()
    os.makedirs(a.dl, exist_ok=True)
    bz, cz = a.borehole, a.company
    info = None
    if not bz:
        bz = os.path.join(a.dl, "5010delimit.zip")
        info = D.fetch(FILES + BOREHOLE, bz)
        log("downloaded the borehole file: %.1f MB, made %s" % (info["bytes"] / 1e6, info["modified"]))
    if not cz:
        cz = os.path.join(a.dl, "compalldelimit.zip")
        D.fetch(FILES + COMPANY, cz)
    t = time.time()
    holes, companies = read_boreholes(bz), read_companies(cz)
    log("read %d boreholes and %d companies in %.0f s" % (len(holes), len(companies), time.time() - t))
    coll = collect(holes, companies, today)
    log("stats: %s" % dict(coll["stats"]))
    recent = sum(1 for k in coll["permits"] if k[2] >= today - timedelta(days=730))
    if coll["stats"]["wells with a spud date, ever"] < MIN_WELLS or recent < MIN_RECENT:
        sys.exit("the borehole file holds %d wells (%d spudded in the last 24 months): it is not the file this script reads" % (coll["stats"]["wells with a spud date, ever"], recent))
    asof = date.fromisoformat(a.asof) if a.asof else reliable_asof(today)
    sentence = boreholes_sentence(coll, asof)
    spec = dict(SPEC, src=lambda asof_, modified_: SPEC["src"](asof_, modified_) + sentence)
    docs, rep = M.build(coll, names, asof, (info or {}).get("modified") or today.isoformat(), spec)
    try:
        with open(os.path.join(a.out, NAMES[0]), encoding="utf-8") as f:
            old_series = json.load(f)
    except (OSError, ValueError):
        old_series = None  # no committed series yet (the first build): nothing to compare with
    refuse = guard(docs, rep, coll, old_series)
    if refuse:
        for p in refuse:
            log("REFUSED: " + p)
        log("nothing was written: the files in %s are as they were" % a.out)
        return 2
    os.makedirs(a.out, exist_ok=True)
    for name, doc in docs.items():
        log("wrote %s (%d bytes)" % (name, M.write_json(os.path.join(a.out, name), doc)))
    problems = M.validate(a.out, names, SPEC)
    for p in problems:
        log("CHECK failed: " + p)
    log("spuds through %s: %d wells (%d in the last 12 months, %d before; %d without an area), %d named operators, %d located points, %.0f%% of the last 12 months' wells by named operators"
        % (rep["asof"], rep["new"], rep["p12"], rep["p12prev"], rep["no_county"], rep["operators"], rep["points"], 100 * (rep["named_share12"] or 0)))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
