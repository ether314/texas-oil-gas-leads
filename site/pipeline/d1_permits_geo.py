#!/usr/bin/env python3
"""D1 producer: Texas new-drill permit data layers for the leads site.

Writes four compact UTF-8 JSON files into <site>/public/data/ (schemas: site/DATA_CONTRACT.md):
  county-permits.json   per county: 12-month and prior-12 counts, 36 monthly counts, mean depth, top named operators
  operator-extras.json  per named operator: prior-12 count, spud count, depth, top county, 24 monthly counts
  series-permits.json   statewide new-drill permits by issue month since 2019-01
  permits.json          one point per new-drill permit of the last 24 months that has RRC surface coordinates,
                        plus a `coverage` block (permits vs located per month, share12, share24)

Inputs are public Railroad Commission of Texas files. They are only parsed, never executed: run with `python3 -I`.
  daf802.txt.gz      Drilling Permit Master and Trailer: CRLF text, 510-char permit-master records (record id '02').
  daf420.dat*        Drilling Permit Master plus Latitudes and Longitudes (month-end and daily files): permit blocks
                     of records 01 (root) ... 14 (surface location: longitude, latitude, NAD27) and 15 (bottom hole).
                     One file per folder: <dl>/ll_*/daf420.dat[.MM-DD-YYYY]; the latest snapshot wins per permit.
  rrc_operators.csv  active P-5 registrants: `org_type` gates which operators may be named, `new_well_permits_12m`
                     is the cross-check for the 12-month counts.

  python3 -I site/pipeline/d1_permits_geo.py [--dl DIR] [--out DIR] [--asof YYYY-MM-DD]

Counting rules (identical to rrc_operators.py, which produced the CSV): the first '02' record per permit number
among records with a valid issue date is the permit; it is a new-drill permit when its application type is '01'.
Fetching the lat/long files: python3 -I rrc_fetch.py <guid> <file name> <new empty folder> with guid
f5dfea9c-bb39-4a5e-a44e-fb522e088cba (End of Month files) or 5f07cc72-2e79-4df8-ade1-9aeb792e03fc (daily files).
"""
import argparse
import csv
import glob
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
# raw downloads go in the gitignored dl/ folder at the repo root, one new folder per file (DATA_CONTRACT.md); override with --dl
DEFAULT_DL = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))

ASOF = "2026-10-29"
T0 = date(2024, 1, 1)
SERIES_START = (2019, 1)
ENTITY_TYPES = {"corporation", "limited partnership", "LLC"}  # the only org types that may be named
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 25.5, 36.6, -106.8, -93.4
VALID_FIPS = {"%03d" % n for n in range(1, 508, 2)}  # the 254 Texas counties; RRC county codes are these FIPS codes
BUDGET_BYTES = {"permits.json": 1500000}
DEFAULT_BUDGET = 400000
RX14 = re.compile(rb"^14:?\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")  # '14', optional ':', longitude, latitude

# sanity list only (names for the report and the "expected counties" verdict); not written to any output
PERMIAN = {"329": "Midland", "317": "Martin", "389": "Reeves", "301": "Loving", "461": "Upton", "383": "Reagan",
           "135": "Ector", "475": "Ward", "495": "Winkler", "003": "Andrews", "109": "Culberson", "371": "Pecos",
           "227": "Howard", "173": "Glasscock", "103": "Crane", "165": "Gaines", "115": "Dawson", "033": "Borden",
           "235": "Irion", "105": "Crockett", "431": "Sterling", "443": "Terrell", "335": "Mitchell", "415": "Scurry",
           "501": "Yoakum", "445": "Terry"}
EAGLE_FORD = {"479": "Webb", "283": "La Salle", "311": "McMullen", "255": "Karnes", "123": "DeWitt",
              "177": "Gonzales", "013": "Atascosa", "163": "Frio", "127": "Dimmit", "507": "Zavala",
              "323": "Maverick", "493": "Wilson", "297": "Live Oak", "285": "Lavaca", "149": "Fayette",
              "287": "Lee", "051": "Burleson", "041": "Brazos", "477": "Washington", "185": "Grimes",
              "313": "Madison", "289": "Leon", "395": "Robertson", "505": "Zapata", "131": "Duval", "025": "Bee",
              "175": "Goliad", "469": "Victoria", "247": "Jim Hogg", "427": "Starr", "215": "Hidalgo"}


def to_date(text):
    try:
        d = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return d if 1900 <= d.year <= 2100 else None


def digits(text):
    return text.isascii() and text.isdigit()


def month_index(d):
    return d.year * 12 + d.month - 1


def month_label(idx):
    year, m0 = divmod(idx, 12)
    return "%04d-%02d" % (year, m0 + 1)


def windows(asof, calendar=False):
    """Day-window cuts as ordinals and month indexes. The current partial month is never part of a monthly series.
    calendar=True is for the files that end on a month end (New Mexico's and the federal offshore's, whose newest month is always a whole one): their 12 months
    are 12 calendar months from the first day of the month, so a county's or an operator's 12 months add up to the months of the monthly series. Without it
    (Texas, Oklahoma: the day of the newest permit) a year is the 365 days that end on asof, which at a month end takes in one day of the month before."""
    month_is_over = (asof + timedelta(days=1)).month != asof.month
    last = month_index(asof) - (0 if month_is_over else 1)
    first_of = lambda idx: date(idx // 12, idx % 12 + 1, 1).toordinal()  # noqa: E731
    cut12, cut24 = (first_of(last - 11), first_of(last - 23)) if calendar and month_is_over else ((asof - timedelta(days=365)).toordinal(), (asof - timedelta(days=730)).toordinal())
    return {"asof": asof, "asofo": asof.toordinal(),
            "cut12": cut12,   # last 12 months: issue date >= cut12
            "cut24": cut24,   # prior 12: cut24 <= date < cut12
            "last": last, "first36": last - 35, "first24": last - 23,
            "series0": SERIES_START[0] * 12 + SERIES_START[1] - 1,
            "keep_from": date(SERIES_START[0], SERIES_START[1], 1).toordinal()}


# ---------------------------------------------------------------------------------------------------- readers

def read_master(path, w):
    """One pass over daf802. Returns (new-drill tuples, counters, latest issue-date ordinal).

    Tuple: (permit, operator, county code, total depth ft, issue ordinal, issue month index, spud ordinal or 0,
    first record is an amendment). Kept for permits issued since the series start or spudded in the last 12 months.
    """
    seen, st, news, through = set(), Counter(), [], 0
    with gzip.open(path, "rb") as f:
        for raw in f:
            if raw[:2] != b"02":
                continue
            rec = raw.rstrip(b"\r\n")
            if len(rec) != 510:
                st["02 lines not 510 chars (skipped)"] += 1
                continue
            line = rec.decode("latin-1")
            permit, op, kind = line[2:9], line[59:65], line[65:67]
            issued = to_date(line[129:137])
            if not (digits(permit) and digits(op) and issued):
                st["no valid issue date (skipped)"] += 1
                continue
            if permit in seen:
                st["repeat permit numbers (skipped)"] += 1
                continue
            seen.add(permit)
            st["permits read"] += 1
            iss = issued.toordinal()
            through = max(through, iss)
            if kind != "01":
                continue
            st["new-drill (01)"] += 1
            spud = to_date(line[153:161])
            spud_o = spud.toordinal() if spud else 0
            if iss < w["keep_from"] and spud_o < w["cut12"]:
                continue
            td = line[54:59]
            news.append((permit, op, line[11:14], int(td) if digits(td) else 0, iss, month_index(issued), spud_o,
                         line[9:11] != "99"))
    return news, st, through


def read_operators(path):
    """(nameable operator number -> exact CSV name, operator number -> new_well_permits_12m for every operator)."""
    names, csv12 = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            num = r["operator_number"].strip()
            csv12[num] = int(r["new_well_permits_12m"] or 0)
            if r["org_type"] in ENTITY_TYPES:
                names[num] = r["name"]
    return names, csv12


def snapshot_key(path):
    m = re.search(r"\.(\d\d)-(\d\d)-(\d{4})$", path)
    if m:
        return (m.group(3), m.group(1), m.group(2))
    d = date.fromtimestamp(os.path.getmtime(path))  # the plain daf420.dat is today's file
    return ("%04d" % d.year, "%02d" % d.month, "%02d" % d.day)


def read_geo(paths):
    """permit number -> (lat*1e4, lon*1e4) from the type-14 surface-location records; later snapshots win."""
    coords, st = {}, Counter()
    for path in sorted(paths, key=lambda p: (snapshot_key(p), p)):
        with open(path, "rb") as f:
            data = f.read()
        st["files"] += 1
        st["bytes"] += len(data)
        cur = None
        for rec in data.split(b"\r\n"):
            kind = rec[:2]
            if kind == b"01":
                if len(rec) == 212 and rec[2:9].isdigit():
                    cur = rec[2:9].decode("ascii")
                    st["permit blocks"] += 1
                else:
                    cur = None
                    st["01-prefixed lines not a root record"] += 1
            elif kind == b"02" and len(rec) == 510:
                st["02 records"] += 1
            elif kind == b"14":
                m = RX14.match(rec)
                if not m:
                    st["14-prefixed lines not parsed"] += 1
                    continue
                st["14 records"] += 1
                if cur is None:
                    st["14 records without a block"] += 1
                    continue
                lon, lat = float(m.group(1)), float(m.group(2))
                if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
                    st["14 outside the Texas box (dropped)"] += 1
                    continue
                xy = (int(round(lat * 10000)), int(round(lon * 10000)))
                if coords.get(cur, xy) != xy:
                    st["permits whose coordinates differ between snapshots"] += 1
                coords[cur] = xy
    return coords, st


# ---------------------------------------------------------------------------------------------------- builders

def build_series(news, w, through):
    n = w["last"] - w["series0"] + 1
    counts = [0] * n
    for rec in news:
        k = rec[5] - w["series0"]
        if 0 <= k < n:
            counts[k] += 1
    src = ("Railroad Commission of Texas, Drilling Permit Master and Trailer (daf802): application type 01 (new "
           "drill), one count per permit number, by permit issue month; issue dates through %s"
           % date.fromordinal(through).isoformat())
    return {"months": [month_label(w["series0"] + i) for i in range(n)], "permits": counts, "src": src}


def build_counties(news, w, names):
    n36 = w["last"] - w["first36"] + 1
    months = [month_label(w["first36"] + i) for i in range(n36)]
    monthly = defaultdict(lambda: [0] * n36)
    p12, prev, depth, ops = Counter(), Counter(), defaultdict(lambda: [0, 0]), defaultdict(Counter)
    bad_code = 0
    for _permit, op, fips, td, iss, mi, _spud, _amd in news:
        if fips not in VALID_FIPS:
            bad_code += iss >= w["cut24"]
            continue
        k = mi - w["first36"]
        if 0 <= k < n36:
            monthly[fips][k] += 1
        if iss >= w["cut12"]:
            p12[fips] += 1
            if td > 0:
                depth[fips][0] += td
                depth[fips][1] += 1
            if op in names:
                ops[fips][op] += 1
        elif iss >= w["cut24"]:
            prev[fips] += 1
    counties = {}
    for fips in sorted(set(monthly) | set(p12) | set(prev)):
        m = monthly[fips] if fips in monthly else [0] * n36
        if sum(m) + p12[fips] + prev[fips] == 0:
            continue
        dsum, dn = depth[fips] if fips in depth else (0, 0)
        top = sorted(ops[fips].items(), key=lambda kv: (-kv[1], kv[0]))[:8] if fips in ops else []
        counties[fips] = {"p12": p12[fips], "p12prev": prev[fips], "m": m,
                          "depth": int(dsum / dn + 0.5) if dn else None,
                          "ops": [[names[op], op, c] for op, c in top]}
    return {"asOf": w["asof"].isoformat(), "months": months, "counties": counties}, bad_code


def build_operator_rows(news, w, names):
    n24 = w["last"] - w["first24"] + 1
    st = {}
    for _permit, op, fips, td, iss, mi, spud, _amd in news:
        if op not in names:
            continue
        s = st.get(op)
        if s is None:
            s = st[op] = {"n24": 0, "prev": 0, "spud": 0, "dsum": 0, "dn": 0, "cty": Counter(), "m": [0] * n24}
        if 0 <= mi - w["first24"] < n24:
            s["m"][mi - w["first24"]] += 1
        if w["cut12"] <= spud <= w["asofo"]:
            s["spud"] += 1
        if iss >= w["cut24"]:
            s["n24"] += 1
            s["prev"] += iss < w["cut12"]
            if td > 0:
                s["dsum"] += td
                s["dn"] += 1
            if fips in VALID_FIPS:
                s["cty"][fips] += 1
    rows = []
    for op, s in sorted(st.items(), key=lambda kv: (-kv[1]["n24"], kv[0])):
        if s["n24"] < 1:
            continue
        top = max(s["cty"].items(), key=lambda kv: (kv[1], -int(kv[0])))[0] if s["cty"] else ""
        rows.append([op, s["prev"], s["spud"], int(s["dsum"] / s["dn"] + 0.5) if s["dn"] else 0, top,
                     len(s["cty"]), s["m"]])
    return {"asOf": w["asof"].isoformat(), "months": [month_label(w["first24"] + i) for i in range(n24)],
            "cols": ["num", "prev12", "spud12", "depth", "fips", "counties", "m24"], "rows": rows}


def build_points(news, w, names, coords):
    """Returns (permits.json payload, coverage by issue month index -> [new-drill permits, with coordinates],
    the same pair for the last 12 months)."""
    cov, cov12 = defaultdict(lambda: [0, 0]), [0, 0]
    n24 = w["last"] - w["first24"] + 1
    month_total, month_located = [0] * n24, [0] * n24  # whole calendar months of the 24 complete months
    chosen = []
    for permit, op, fips, td, iss, mi, _spud, _amd in news:
        k = mi - w["first24"]
        if 0 <= k < n24:
            month_total[k] += 1
        if iss < w["cut24"]:
            continue
        cov[mi][0] += 1
        cov12[0] += iss >= w["cut12"]
        xy = coords.get(permit)
        if xy is None or fips not in VALID_FIPS:
            continue
        cov[mi][1] += 1
        cov12[1] += iss >= w["cut12"]
        if 0 <= k < n24:
            month_located[k] += 1
        chosen.append((iss, xy[0], xy[1], op, td, fips))
    per_op = Counter(c[3] for c in chosen if c[3] in names)
    order = [op for op, _n in sorted(per_op.items(), key=lambda kv: (-kv[1], kv[0]))]
    index = {op: i for i, op in enumerate(order)}
    t0 = T0.toordinal()
    # oldest issue day first (the last 12 months are one contiguous tail), then south to north
    pts = sorted(([lat, lon, index.get(op, -1), iss - t0, 0 if td <= 0 else max(1, int(td / 100 + 0.5)), int(fips)]
                  for iss, lat, lon, op, td, fips in chosen), key=lambda p: (p[3], p[0], p[1], p[2], p[4], p[5]))
    n_all, n_xy = sum(v[0] for v in cov.values()), sum(v[1] for v in cov.values())
    # monthly arrays are whole calendar months (2024-10 is located only from 29 Oct, the window start); the two
    # shares use the day windows of the points (issued >= cut12 / >= cut24), so they include 2026-10 so far
    coverage = {"months": [month_label(w["first24"] + i) for i in range(n24)], "total": month_total,
                "located": month_located,
                "share12": round(cov12[1] / cov12[0], 3) if cov12[0] else 0.0,
                "share24": round(n_xy / n_all, 3) if n_all else 0.0}
    return {"asOf": w["asof"].isoformat(), "t0": T0.isoformat(), "ops": [names[op] for op in order],
            "opNums": order, "cols": ["lat", "lon", "op", "t", "depth", "fips"], "pts": pts,
            "coverage": coverage}, cov, cov12


# ---------------------------------------------------------------------------------------------------- output

def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)
    return os.path.getsize(path)


def validate(out, w, names, expect_points, totals=None):
    """Reload every written file, check schema, ranges and size budgets. Returns a list of problems.
    totals = (new-drill permits of the last 12 months, of the last 24 months) from the permit master."""
    bad = []

    def load(name):
        path = os.path.join(out, name)
        if os.path.getsize(path) > BUDGET_BYTES.get(name, DEFAULT_BUDGET):
            bad.append("%s over budget: %d bytes" % (name, os.path.getsize(path)))
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def is_int(v):
        return type(v) is int

    asof = w["asof"].isoformat()
    last_label = month_label(w["last"])

    d = load("county-permits.json")
    if list(d) != ["asOf", "months", "counties"] or d["asOf"] != asof:
        bad.append("county-permits top-level keys")
    if len(d["months"]) != 36 or d["months"][-1] != last_label or d["months"][0] != month_label(w["first36"]):
        bad.append("county-permits months")
    for fips, c in d["counties"].items():
        ok = fips in VALID_FIPS and list(c) == ["p12", "p12prev", "m", "depth", "ops"]
        ok = ok and is_int(c["p12"]) and is_int(c["p12prev"]) and c["p12"] >= 0 and c["p12prev"] >= 0
        ok = ok and len(c["m"]) == 36 and all(is_int(v) and v >= 0 for v in c["m"])
        ok = ok and (c["depth"] is None or (is_int(c["depth"]) and c["depth"] > 0))
        ok = ok and len(c["ops"]) <= 8 and sum(x[2] for x in c["ops"]) <= c["p12"]
        ok = ok and all(len(x) == 3 and names.get(x[1]) == x[0] and is_int(x[2]) and x[2] > 0 for x in c["ops"])
        ok = ok and [x[2] for x in c["ops"]] == sorted((x[2] for x in c["ops"]), reverse=True)
        if not ok:
            bad.append("county-permits county %s" % fips)
            break

    d = load("operator-extras.json")
    if (list(d) != ["asOf", "months", "cols", "rows"] or len(d["months"]) != 24 or d["months"][-1] != last_label
            or d["cols"] != ["num", "prev12", "spud12", "depth", "fips", "counties", "m24"]):
        bad.append("operator-extras top level")
    extras_months = d["months"]
    nums = set()
    for r in d["rows"]:
        # fips "" with 0 counties = every last-24-month permit of the operator is offshore (RRC area codes 600-713)
        ok = len(r) == 7 and r[0] in names and r[0] not in nums
        ok = ok and ((r[4] in VALID_FIPS and r[5] >= 1) or (r[4] == "" and r[5] == 0))
        ok = ok and all(is_int(v) and v >= 0 for v in r[1:4]) and is_int(r[5])
        ok = ok and len(r[6]) == 24 and all(is_int(v) and v >= 0 for v in r[6])
        nums.add(r[0])
        if not ok:
            bad.append("operator-extras row %s" % r[0])
            break

    d = load("series-permits.json")
    n = w["last"] - w["series0"] + 1
    if (list(d) != ["months", "permits", "src"] or len(d["months"]) != n or len(d["permits"]) != n
            or d["months"][0] != month_label(w["series0"]) or d["months"][-1] != last_label
            or not all(is_int(v) and v >= 0 for v in d["permits"]) or not isinstance(d["src"], str)):
        bad.append("series-permits")

    if expect_points:
        d = load("permits.json")
        if (list(d) != ["asOf", "t0", "ops", "opNums", "cols", "pts", "coverage"] or d["t0"] != T0.isoformat()
                or d["cols"] != ["lat", "lon", "op", "t", "depth", "fips"] or len(d["ops"]) != len(d["opNums"])
                or any(names.get(num) != nm for nm, num in zip(d["ops"], d["opNums"]))):
            bad.append("permits top level")
        tmin, tmax = w["cut24"] - T0.toordinal(), w["asofo"] - T0.toordinal()
        no = len(d["ops"])
        for p in d["pts"]:
            ok = len(p) == 6 and all(is_int(v) for v in p)
            ok = ok and round(LAT_MIN * 10000) <= p[0] <= round(LAT_MAX * 10000)
            ok = ok and round(LON_MIN * 10000) <= p[1] <= round(LON_MAX * 10000)
            ok = ok and -1 <= p[2] < no and tmin <= p[3] <= tmax and p[4] >= 0 and ("%03d" % p[5]) in VALID_FIPS
            if not ok:
                bad.append("permits point %s" % p)
                break
        # the coverage block must agree with the points actually in the file and with the master-file totals
        cv, k24, t12 = d["coverage"], w["last"] - w["first24"] + 1, w["cut12"] - T0.toordinal()
        by_month, in12 = Counter(), 0
        for p in d["pts"]:
            by_month[month_index(date.fromordinal(T0.toordinal() + p[3])) - w["first24"]] += 1
            in12 += p[3] >= t12
        ok = list(cv) == ["months", "total", "located", "share12", "share24"] and cv["months"] == extras_months
        ok = ok and len(cv["total"]) == k24 and len(cv["located"]) == k24
        ok = ok and all(is_int(v) and v >= 0 for v in cv["total"] + cv["located"])
        ok = ok and all(a <= b for a, b in zip(cv["located"], cv["total"]))
        ok = ok and cv["located"] == [by_month[i] for i in range(k24)]
        ok = ok and type(cv["share12"]) is float and type(cv["share24"]) is float and totals is not None
        ok = ok and cv["share12"] == round(in12 / totals[0], 3) and cv["share24"] == round(len(d["pts"]) / totals[1], 3)
        if not ok:
            bad.append("permits coverage block")
    return bad


# ---------------------------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="D1: permit data layers (see the module docstring)")
    ap.add_argument("--dl", default=DEFAULT_DL, help="folder holding the downloads (permits_daf802/, ll_*/)")
    ap.add_argument("--daf802", help="default: <dl>/permits_daf802/daf802.txt.gz")
    ap.add_argument("--operators", default=os.path.join(ROOT, "rrc_operators.csv"))
    ap.add_argument("--out", default=os.path.join(SITE, "public", "data"))
    ap.add_argument("--asof", default=ASOF)
    a = ap.parse_args()
    asof = date.fromisoformat(a.asof)
    w = windows(asof)
    master = a.daf802 or os.path.join(a.dl, "permits_daf802", "daf802.txt.gz")
    geo_paths = sorted(p for p in glob.glob(os.path.join(a.dl, "ll_*", "daf420.dat*")) if os.path.isfile(p))
    for path in (master, a.operators):
        if not os.path.isfile(path):
            sys.exit("missing input: %s" % path)
    os.makedirs(a.out, exist_ok=True)

    names, csv12 = read_operators(a.operators)
    news, mst, through = read_master(master, w)
    print("daf802: %s | issue dates through %s | kept %d new-drill tuples"
          % (", ".join("%s %d" % kv for kv in mst.items()), date.fromordinal(through).isoformat(), len(news)))
    print("nameable operators in the CSV: %d of %d" % (len(names), len(csv12)))

    # cross-check 1: 12-month new-drill counts per operator against rrc_operators.csv
    op12 = Counter(rec[1] for rec in news if rec[4] >= w["cut12"])
    mismatch = [(n, csv12[n], op12.get(n, 0)) for n in sorted(csv12) if csv12[n] != op12.get(n, 0)]
    top20 = sorted(csv12.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    top20_bad = [(n, c, op12.get(n, 0)) for n, c in top20 if c != op12.get(n, 0)]
    print("CHECK 1 operators: %d compared, %d mismatches; top 20: %s; top 3 = %s"
          % (len(csv12), len(mismatch), "all match" if not top20_bad else "MISMATCH %s" % top20_bad[:5],
             ", ".join("%s %d/%d" % (n, c, op12.get(n, 0)) for n, c in top20[:3])))
    if mismatch:
        print("  first mismatches (operator, csv, mine):", mismatch[:8])
    outside = sum(v for k, v in op12.items() if k not in csv12)
    named = sum(v for k, v in op12.items() if k in names)
    print("12-month new-drill permits: %d statewide | %d by nameable operators | %d by operators not in the CSV"
          % (sum(op12.values()), named, outside))

    series = build_series(news, w, through)
    county_doc, bad_code = build_counties(news, w, names)
    counties = county_doc["counties"]
    extras = build_operator_rows(news, w, names)
    print("series %s..%s, last 3 months %s | county codes not a Texas county (last 24 mo): %d"
          % (series["months"][0], series["months"][-1], series["permits"][-3:], bad_code))
    amended = sum(1 for rec in news if rec[4] >= w["cut24"] and rec[7])
    print("last-24-month permits whose first record is an amendment (sequence != 99): %d" % amended)

    sizes = {"county-permits.json": write_json(os.path.join(a.out, "county-permits.json"), county_doc),
             "operator-extras.json": write_json(os.path.join(a.out, "operator-extras.json"), extras),
             "series-permits.json": write_json(os.path.join(a.out, "series-permits.json"), series)}

    # cross-check 2: the busiest counties should be Permian / Eagle Ford counties
    ranked = sorted(counties.items(), key=lambda kv: (-kv[1]["p12"], kv[0]))
    labels = ["%s (%s) %d" % (f, PERMIAN.get(f) or EAGLE_FORD.get(f) or "?", c["p12"]) for f, c in ranked[:5]]
    expected = all(f in PERMIAN or f in EAGLE_FORD for f, _c in ranked[:5])
    print("CHECK 2 top 5 counties by p12: %s -> %s" % ("; ".join(labels),
          "expected Permian/Eagle Ford counties" if expected else "UNEXPECTED, investigate the county-code assumption"))
    print("counties written: %d | p12 sum %d | p12prev sum %d | operator rows: %d (%d without a Texas county)" % (
        len(counties), sum(c["p12"] for c in counties.values()), sum(c["p12prev"] for c in counties.values()),
        len(extras["rows"]), sum(1 for r in extras["rows"] if not r[4])))

    points, totals = None, None
    if geo_paths:
        coords, gst = read_geo(geo_paths)
        print("geo: %s | permits with valid coordinates: %d"
              % (", ".join("%s %d" % kv for kv in gst.items()), len(coords)))
        points, cov, cov12 = build_points(news, w, names, coords)
        sizes["permits.json"] = write_json(os.path.join(a.out, "permits.json"), points)
        n_all = sum(v[0] for v in cov.values())
        n_xy = sum(v[1] for v in cov.values())
        totals = (cov12[0], n_all)
        cv = points["coverage"]
        print("coverage block: share12 %s share24 %s | months %s..%s | total %s..%s | located %s..%s"
              % (cv["share12"], cv["share24"], cv["months"][0], cv["months"][-1], cv["total"][0], cv["total"][-1],
                 cv["located"][0], cv["located"][-1]))
        print("CHECK 3 points: %d | share of last-24-month new-drill permits with valid coordinates: %d of %d = %.1f%%"
              " | last 12 months: %d of %d = %.1f%%"
              % (len(points["pts"]), n_xy, n_all, 100.0 * n_xy / max(n_all, 1), cov12[1], cov12[0],
                 100.0 * cov12[1] / max(cov12[0], 1)))
        pts = points["pts"]
        if pts:
            print("  bounds lat %.4f..%.4f lon %.4f..%.4f | named operators in points: %d | points of unnamed operators: %d"
                  % (min(p[0] for p in pts) / 1e4, max(p[0] for p in pts) / 1e4, min(p[1] for p in pts) / 1e4,
                     max(p[1] for p in pts) / 1e4, len(points["ops"]), sum(1 for p in pts if p[2] < 0)))
        cent = defaultdict(lambda: [0, 0, 0])
        for p in pts:
            c = cent["%03d" % p[5]]
            c[0] += p[0]
            c[1] += p[1]
            c[2] += 1
        print("  centroids of the top 5 counties (lat, lon, points): " + "; ".join(
            "%s %.2f,%.2f n=%d" % (f, cent[f][0] / cent[f][2] / 1e4, cent[f][1] / cent[f][2] / 1e4, cent[f][2])
            for f, _c in ranked[:5] if cent[f][2]))
        print("  coverage by issue month (new-drill permits / with coordinates):")
        line = []
        for mi in sorted(cov):
            line.append("%s %d/%d" % (month_label(mi), cov[mi][0], cov[mi][1]))
        for i in range(0, len(line), 5):
            print("   " + " | ".join(line[i:i + 5]))
    else:
        print("WARNING: no lat/long files under %s/ll_*; permits.json skipped" % a.dl)

    problems = validate(a.out, w, names, points is not None, totals)
    print("sizes: " + ", ".join("%s %d KB (budget %d)" % (n, round(s / 1000.0), BUDGET_BYTES.get(n, DEFAULT_BUDGET) // 1000)
                                for n, s in sorted(sizes.items())))
    print("CHECK 5 schema: %s" % ("all files load and match the contract" if not problems else "PROBLEMS %s" % problems))
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
