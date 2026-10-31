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
API number (its first ten digits: a sidetrack or bypass is another borehole of the same well), on the spud day of its earliest borehole.
Offshore drilling is small next to the land states (about 45 wells a year since 2024), and a spud is reported with some delay and the
file is made weekly, so a month is shown only when it ended at least LAG_DAYS days ago. The file carries a total depth for few recent wells
(it arrives after completion), so no depth is published; the water depth, which is always there, is not one either.

  python3 -I site/pipeline/d10_fo_monthly.py [--out DIR] [--dl DIR] [--asof YYYY-MM-DD] [--today YYYY-MM-DD]
  python3 -I site/pipeline/d10_fo_monthly.py --check [--out DIR]       only reload and check what is already there
  python3 -I site/pipeline/d10_fo_monthly.py --areas [--dl DIR]        rebuild counties-fo.geo.json from BSEE's protraction areas

Operators are named only by the corporate rule (d8_ok_daily.nameable: a corporation, LLC or partnership, never a person's dba). Nothing names a
well, a lease, a platform or an API number, and no address or contact in the company file is read (only its number and name). The files are
parsed, never run; requests identify no person.
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
    """The boreholes of the weekly file as dicts of what is used: api (12 digits), op (operator number), spud (YYYYMMDD or ''), area (two letters),
    lat, lon. The file has 29 comma-delimited, quoted fields and no header; a file that is not that (an error page, another layout) raises."""
    rows, bad = [], 0
    for r in csv.reader(io.StringIO(zip_text(path))):
        if len(r) != 29 or not re.fullmatch(r"\d{12}", r[0].strip()):
            bad += 1
            continue
        lat, lon = r[21].strip(), r[20].strip()
        rows.append({"api": r[0].strip(), "op": r[3].strip(), "spud": r[5].strip(), "area": r[11].strip()[:2], "type": r[16].strip(), "status": r[18].strip(),
                     "lat": float(lat) if re.fullmatch(r"-?\d+(\.\d+)?", lat) else None, "lon": float(lon) if re.fullmatch(r"-?\d+(\.\d+)?", lon) else None})
    if len(rows) < MIN_ROWS or bad > len(rows) * 0.01:
        raise ValueError("the borehole file holds %d usable rows and %d unusable ones: it is not the file this script reads (expected about 55,000)" % (len(rows), bad))
    return rows


def read_companies(path):
    """{operator number (no leading zeros): name} from the company file (19 comma-delimited fields; only the number and the full name are read)."""
    out = {}
    for r in csv.reader(io.StringIO(zip_text(path))):
        if len(r) == 19 and r[0].strip().isdigit():
            out[str(int(r[0].strip()))] = " ".join(r[2].split())
    if len(out) < 1000:
        raise ValueError("the company file holds %d companies: it is not the file this script reads (expected about 5,500)" % len(out))
    return out


def spud_day(text):
    try:
        d = datetime.strptime(text, "%Y%m%d").date() if re.fullmatch(r"\d{8}", text or "") else None
    except ValueError:
        return None
    return d if d and d.year >= 1940 else None


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
    for b in boreholes:
        st["boreholes"] += 1
        d = spud_day(b["spud"])
        if d is None or d > today:
            st["no real spud date (or one after today)"] += 1
            continue
        k = b["api"][:10]
        if k not in first or d < first[k][0]:
            first[k] = (d, b)
    first_dr, permits = {}, {}
    for k, (d, b) in first.items():
        op = str(int(b["op"])) if b["op"].isdigit() else ""
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
    return {"permits": permits, "first_dr": first_dr, "stats": st}


def reliable_asof(today, lag=LAG_DAYS):
    """The last day of the newest month that ended at least `lag` days ago: where the files end."""
    cut = today - timedelta(days=lag)
    return cut if (cut + timedelta(days=1)).month != cut.month else cut.replace(day=1) - timedelta(days=1)


SPEC = {
    "names": NAMES, "box": BOX, "new_kind": "SP", "county_of": lambda r: r["county"],
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
    for row, rings in zip(rows, shapes):
        if row and rings:
            by[row["AREA_CODE"].strip()].append((row["PROT_NAME"].strip(), rings))
    if tuple(sorted(by)) != AREA_ORDER:
        raise ValueError("the shapes hold areas %s, not the 63 this script numbers (AREA_ORDER)" % sorted(set(by) ^ set(AREA_ORDER)))
    out = {}
    for code, parts in by.items():
        name = re.sub(r" Area$", "", min((n for n, _ in parts), key=len))
        polys = []
        for _, rings in parts:
            for poly in D2.rings_to_polys(rings):
                polys.append([simplify(r, 0.01) for r in poly])
        out[AREA_CODE[code]] = {"n": name, "polys": D2.finalize(polys)}
    D.write_json(out_path, D2.build_counties_doc(out))
    return len(out)


def area_names():
    try:
        with open(AREAS_GEO, encoding="utf-8") as f:
            return {x["properties"]["f"]: x["properties"]["n"] for x in json.load(f)["features"]}
    except (OSError, ValueError):
        return {}


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
    if a.check:
        problems = M.validate(a.out, names, SPEC)
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
    docs, rep = M.build(coll, names, asof, (info or {}).get("modified") or today.isoformat(), SPEC)
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
