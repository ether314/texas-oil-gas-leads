#!/usr/bin/env python3
"""D8 monthly: Oklahoma's new-drill permit history, for the Overview, the Map and the Operators page of the Oil tracker.

The Daily report (d8_ok_daily.py) shows one day at a time. The other pages show a year and its trend, so this reads the Oklahoma
Corporation Commission's intent-to-drill master file once (ITD-wells-formations-base.xlsx, about 154 MB, every application since
1999) and the daily file beside it, and writes four files into site/public/data/, shaped like the Texas files they sit beside:

  series-permits-ok.json   new-drill permits by approval month since 2019-01 (complete months only)
  county-permits-ok.json   per county: the last 12 months and the 12 before, 36 monthly counts, mean planned depth, top operators
  operators-ok.json        the named operators with a permit in the last 24 months: counts, trend, depth, counties, 24 monthly counts
  permits-ok.json          one point per new-drill permit of the last 24 months, at the surface location the OCC records

Rules (NOTES_D8.md has the reasoning):
  * A permit is one API number approved on one day, the Daily report's rule. The master has one row per formation until mid-2025,
    so a permit appears as many times as it names formations; those rows are folded into one. A well whose permit lapsed and was
    approved again is counted again, on the new day. Recompletions, re-entries and deepenings are counted the same way;
    amendments change a permit that is already counted and are left out.
  * Days are Central days (the files store UTC). The windows are the Texas ones (d1_permits_geo.windows): the last 12 months run
    from the newest approval day back 365 days, the 12 before them back to 730 days, and a month is complete only when it is over.
  * Operators are named only when the name ends like a corporation, LLC or partnership (d8_ok_daily.nameable). The permits of every
    other operator are in every count and none of them is named. City and state are the operator's office, never a street or a person.
  * Locations are rounded to about 100 m, and nothing names a lease, a well or an API number.

  python3 -I site/pipeline/d8_ok_monthly.py [--master FILE] [--daily FILE] [--out DIR] [--dl DIR] [--asof YYYY-MM-DD]
  python3 -I site/pipeline/d8_ok_monthly.py --check [--out DIR]            only reload and check what is already there

The downloaded workbooks are untrusted data: they are parsed, never run, and each download goes into its own new folder.
"""
import argparse
import collections
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d1_permits_geo as D1  # noqa: E402  the Texas windows and month helpers, so both states count the same days
import d8_ok_daily as D  # noqa: E402
import ok_xlsx  # noqa: E402

OUT = os.path.join(SITE, "public", "data")
DL = os.path.join(os.path.dirname(SITE), "dl", "ok-monthly")
MASTER, DAILY = "ITD-wells-formations-base.xlsx", "ITD-wells-formations-daily.xlsx"
NAMES = ("series-permits-ok.json", "county-permits-ok.json", "operators-ok.json", "permits-ok.json")
BUDGET = {"series-permits-ok.json": 4_000, "county-permits-ok.json": 60_000, "operators-ok.json": 150_000, "permits-ok.json": 200_000}
COLS = ("API_Number", "Operator_Number", "Entity_Name", "City", "State", "Application_Type", "Permit_Status", "Total_Depth", "Depth",
        "Approval_Date", "Surf_Long_X", "Surf_Lat_Y")
KEEP_FROM = 2018  # permits older than the series start are only read for each operator's first drilling permit
T0 = date(2024, 1, 1)  # the day count of a point starts here, as in the Texas permits.json
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 33.5, 37.1, -103.1, -94.3  # Oklahoma
KINDS = ("DR", "RC", "RE", "DP")  # application types counted as permits; AM (amendment) changes one that is already counted
# What differs between states in build() and validate(): the file names, the box the points must fall in, which kind of record is a
# new-drill permit, how a record's county is found, and the source line. New Mexico passes its own (d9_nm_monthly.py).
OK_SPEC = {
    "names": NAMES, "box": (LAT_MIN, LAT_MAX, LON_MIN, LON_MAX), "new_kind": "DR", "county_of": lambda r: D.api_county(r["api"]),
    "src": lambda asof, modified: ("Oklahoma Corporation Commission, intents to drill (%s and the daily file%s): application type DR, one count per API number "
                                   "and approval day (Central), by approval month; approvals through %s" % (MASTER, ", made " + modified[:10] if modified else "", asof.isoformat())),
}
CITY_OK = re.compile(r"[A-Z][A-Z .'&-]{1,29}")  # an office city is a place name: no digits, no slash, no phone number or street (the validator holds every file to this)
STATE_OK = re.compile(r"[A-Z]{2}")


def office_place(city, state):
    """(city, state) as the operator table publishes them: upper case, and blank when the file's value is not a place name or a two-letter
    state. A stray value (N/A, a street, a phone number) costs the operator its city, never the whole refresh."""
    city, state = clean(city).upper(), clean(state).upper()
    return (city if CITY_OK.fullmatch(city) else "", state if STATE_OK.fullmatch(state) else "")


OP_COLS = ["band", "num", "name", "type", "city", "state", "new12", "prev12", "all12", "all24", "last", "depth", "county", "counties", "newDrill", "m24"]
PT_COLS = ["lat", "lon", "op", "t", "depth", "fips"]
ASOF_KEYS = ("series-permits-ok.json", "county-permits-ok.json", "operators-ok.json", "permits-ok.json")
log = D.log


# ------------------------------------------------------------------------------------------------ reading

def iter_rows(paths):
    for path in paths:
        yield from ok_xlsx.rows(path, want=COLS)


def clean(text):
    return " ".join((text or "").split())


def collect(rows, today=None):
    """Fold rows into permits. Returns {'permits': {(api10, kind, day): record}, 'first_dr': {operator: first drilling day ever},
    'stats': Counter}. A record is a dict of api, kind, day, op, name, city, state, depth, lat, lon (the first non-blank of each).
    An approval dated after `today` (Central; default: today) is a typo in the file, not a permit: it would move every window."""
    permits, first_dr, st = {}, {}, collections.Counter()
    today = today or D.central_now().date()
    for r in rows:
        st["rows"] += 1
        approved = D.when(r["Approval_Date"])
        if not approved:
            st["no approval date"] += 1
            continue
        if r["Permit_Status"] in ("REJ", "DEL"):
            st["rejected or deleted"] += 1
            continue
        api = clean(r["API_Number"])
        if not (api.isdigit() and len(api) >= 10 and api.startswith("35")):
            st["no usable API number"] += 1
            continue
        kind = clean(r["Application_Type"])
        day = D.central_day(approved)
        if day > today:
            st["dated in the future"] += 1
            continue
        op = clean(r["Operator_Number"])
        if kind == "DR" and op:
            if op not in first_dr or day < first_dr[op]:
                first_dr[op] = day
        if day.year < KEEP_FROM or kind not in KINDS:
            st["older or not a permit kind"] += 1
            continue
        depth = int(D.number(r["Total_Depth"]) or D.number(r["Depth"]) or 0)
        lon, lat = D.number(r["Surf_Long_X"]), D.number(r["Surf_Lat_Y"])
        located = lon is not None and lat is not None and LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX
        key = (api[:10], kind, day)
        rec = permits.get(key)
        if rec is None:
            permits[key] = {"api": api[:10], "kind": kind, "day": day, "op": op, "name": clean(r["Entity_Name"]), "city": clean(r["City"]),
                            "state": clean(r["State"]), "depth": depth, "lat": lat if located else None, "lon": lon if located else None}
            st["permits"] += 1
        else:
            st["formation rows folded into a permit"] += 1
            rec["depth"] = max(rec["depth"], depth)
            if rec["lat"] is None and located:
                rec["lat"], rec["lon"] = lat, lon
            for k, v in (("name", clean(r["Entity_Name"])), ("city", clean(r["City"])), ("state", clean(r["State"]))):
                rec[k] = rec[k] or v
    return {"permits": permits, "first_dr": first_dr, "stats": st}


# ------------------------------------------------------------------------------------------------ building

def org_type(name):
    """What the name says it is (the OCC has no organization type): LLC, limited partnership, otherwise corporation."""
    n = " ".join(name.upper().replace(",", " ").split())
    if re.search(r"(?<![A-Z0-9])(L\.?L\.?C|PLLC)\.?(?![A-Z0-9])", n):
        return "LLC"
    if re.search(r"(?<![A-Z0-9])(L\.?P|LLP|LLLP|LTD)\.?(?![A-Z0-9])|\bPARTNERS(HIP)?\b|\bLIMITED\b", n):
        return "limited partnership"
    return "corporation"


def window_of(asof, calendar=False):
    return D1.windows(asof, calendar)


def name_of(permits_of_op):
    """The operator's name on its newest permit (operators rename themselves; the number stays)."""
    return max(permits_of_op, key=lambda r: (r["day"], r["name"]))["name"]


def build(coll, county_names, asof=None, modified=None, spec=None):
    """The four documents, built from collect()'s result. county_names: {fips: name} of the state's counties."""
    spec = spec or OK_SPEC
    new_kind, county_of, (lat_lo, lat_hi, lon_lo, lon_hi) = spec["new_kind"], spec["county_of"], spec["box"]  # noqa: F841
    permits, first_dr = coll["permits"], coll["first_dr"]
    through = max((r["day"] for r in permits.values()), default=None)
    if through is None:
        raise SystemExit("no approved permit in the files")
    asof = asof or through
    w = window_of(asof, spec.get("calendar_windows", False))
    asofo = asof.toordinal()
    by_op = collections.defaultdict(list)
    for r in permits.values():
        if r["op"]:
            by_op[r["op"]].append(r)
    named = {op: name_of(rs) for op, rs in by_op.items() if D.nameable(name_of(rs))}
    news = [r for r in permits.values() if r["kind"] == new_kind and r["day"].toordinal() <= asofo]
    valid = set(county_names)

    # ---- the statewide series
    n_all = w["last"] - w["series0"] + 1
    counts = [0] * n_all
    for r in news:
        k = D1.month_index(r["day"]) - w["series0"]
        if 0 <= k < n_all:
            counts[k] += 1
    src = spec["src"](asof, modified)
    series = {"asOf": asof.isoformat(), "through": asof.isoformat(), "months": [D1.month_label(w["series0"] + i) for i in range(n_all)], "permits": counts, "src": src}

    # ---- the counties
    n36 = w["last"] - w["first36"] + 1
    monthly = collections.defaultdict(lambda: [0] * n36)
    p12, prev, depth, ops12 = collections.Counter(), collections.Counter(), collections.defaultdict(lambda: [0, 0]), collections.defaultdict(collections.Counter)
    no_county = 0
    for r in news:
        iso = r["day"].toordinal()
        fips = county_of(r)
        mi = D1.month_index(r["day"])
        if fips not in valid:
            no_county += 1 if 0 <= mi - w["first36"] < n36 else 0
            continue
        k = mi - w["first36"]
        if 0 <= k < n36:
            monthly[fips][k] += 1
        if iso >= w["cut12"]:
            p12[fips] += 1
            if r["depth"] > 0:
                depth[fips][0] += r["depth"]
                depth[fips][1] += 1
            if r["op"] in named:
                ops12[fips][r["op"]] += 1
        elif iso >= w["cut24"]:
            prev[fips] += 1
    counties = {}
    for fips in sorted(set(monthly) | set(p12) | set(prev)):
        m = monthly[fips] if fips in monthly else [0] * n36
        if sum(m) + p12[fips] + prev[fips] == 0:
            continue
        dsum, dn = depth[fips] if fips in depth else (0, 0)
        top = sorted(ops12[fips].items(), key=lambda kv: (-kv[1], kv[0]))[:8] if fips in ops12 else []
        counties[fips] = {"p12": p12[fips], "p12prev": prev[fips], "m": m, "depth": int(dsum / dn + 0.5) if dn else None,
                          "ops": [[named[op], op, c] for op, c in top]}
    county_doc = {"asOf": asof.isoformat(), "months": [D1.month_label(w["first36"] + i) for i in range(n36)], "noCounty": no_county, "counties": counties}

    # ---- the operators (named ones with a permit in the last 24 months)
    n24 = w["last"] - w["first24"] + 1
    rows = []
    for op, name in named.items():
        mine = [r for r in by_op[op] if r["day"].toordinal() <= asofo]
        drills = [r for r in mine if r["kind"] == new_kind]
        new24 = [r for r in drills if r["day"].toordinal() >= w["cut24"]]
        others = [r for r in mine if r["kind"] != new_kind and r["day"].toordinal() >= w["cut24"]]
        allp = new24 + others
        if not allp:
            continue
        n12 = sum(1 for r in new24 if r["day"].toordinal() >= w["cut12"])
        pv = len(new24) - n12
        a12 = n12 + sum(1 for r in others if r["day"].toordinal() >= w["cut12"])
        ds = [r["depth"] for r in new24 if r["depth"] > 0]
        cty = collections.Counter(county_of(r) for r in new24 if county_of(r) in valid)
        m24 = [0] * n24
        for r in new24:
            k = D1.month_index(r["day"]) - w["first24"]
            if 0 <= k < n24:
                m24[k] += 1
        latest = max(allp, key=lambda r: (r["day"], r["name"]))
        top_c = max(cty.items(), key=lambda kv: (kv[1], -int(kv[0])))[0] if cty else ""
        fd = first_dr.get(op)
        rows.append(["A" if n12 >= 10 else "B" if n12 >= 1 else "C", op, name, org_type(name), *office_place(latest["city"], latest["state"]),
                     n12, pv, a12, len(allp), max(r["day"] for r in allp).isoformat(), int(sum(ds) / len(ds) + 0.5) if ds else 0, top_c, len(cty),
                     1 if fd is not None and fd.toordinal() >= w["cut24"] else 0, m24])
    rows.sort(key=lambda x: (-x[6], -x[9], x[1]))
    ops_doc = {"asOf": asof.isoformat(), "months": [D1.month_label(w["first24"] + i) for i in range(n24)], "cols": OP_COLS, "rows": rows}

    # ---- the points: new-drill permits of the last 24 months with a surface location (about 100 m)
    month_total, month_located = [0] * n24, [0] * n24
    chosen, cov12, cov24 = [], [0, 0], [0, 0]
    for r in news:
        iso = r["day"].toordinal()
        k = D1.month_index(r["day"]) - w["first24"]
        if 0 <= k < n24:
            month_total[k] += 1
        if iso < w["cut24"]:
            continue
        fips = county_of(r)
        cov24[0] += 1
        cov12[0] += iso >= w["cut12"]
        if r["lat"] is None or fips not in valid:
            continue
        cov24[1] += 1
        cov12[1] += iso >= w["cut12"]
        if 0 <= k < n24:
            month_located[k] += 1
        chosen.append((iso, int(round(r["lat"] * 1000)) * 10, int(round(r["lon"] * 1000)) * 10, r["op"], r["depth"], int(fips)))
    per_op = collections.Counter(c[3] for c in chosen if c[3] in named)
    order = [op for op, _n in sorted(per_op.items(), key=lambda kv: (-kv[1], kv[0]))]
    index = {op: i for i, op in enumerate(order)}
    t0 = T0.toordinal()
    pts = sorted(([lat, lon, index.get(op, -1), iso - t0, 0 if td <= 0 else max(1, int(td / 100 + 0.5)), fips] for iso, lat, lon, op, td, fips in chosen),
                 key=lambda p: (p[3], p[0], p[1], p[2], p[4], p[5]))
    coverage = {"months": [D1.month_label(w["first24"] + i) for i in range(n24)], "total": month_total, "located": month_located,
                "share12": round(cov12[1] / cov12[0], 3) if cov12[0] else 0.0, "share24": round(cov24[1] / cov24[0], 3) if cov24[0] else 0.0}
    points_doc = {"asOf": asof.isoformat(), "t0": T0.isoformat(), "ops": [named[op] for op in order], "opNums": order, "cols": PT_COLS, "pts": pts, "coverage": coverage}

    docs = dict(zip(spec["names"], (series, county_doc, ops_doc, points_doc)))
    report = {"asof": asof, "through": through, "new": len(news), "p12": sum(p12.values()), "p12prev": sum(prev.values()), "no_county": no_county,
              "operators": len(rows), "named_share12": None, "points": len(pts), "stats": coll["stats"]}
    t12 = sum(1 for r in news if r["day"].toordinal() >= w["cut12"])
    report["t12"] = t12
    report["named_share12"] = round(sum(1 for r in news if r["day"].toordinal() >= w["cut12"] and r["op"] in named) / t12, 3) if t12 else None
    return docs, report


# ------------------------------------------------------------------------------------------------ checking

def write_json(path, obj):
    D.write_json(path, obj)
    return os.path.getsize(path)


def validate(out, county_names=None, spec=None):
    """Reload the four files from `out` and return the problems found (empty when all is well)."""
    spec = spec or OK_SPEC
    NAMES = spec["names"]  # noqa: N806 - this state's four files
    LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = spec["box"]  # noqa: N806
    bad = []
    if county_names is None:
        county_names = D.Lookups().county
    valid = set(county_names)
    docs = {}
    for name in NAMES:
        path = os.path.join(out, name)
        try:
            size = os.path.getsize(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            docs[name] = json.loads(text)
        except (OSError, ValueError) as e:
            bad.append("%s: cannot be read (%s)" % (name, e))
            continue
        if size > BUDGET[OK_SPEC["names"][NAMES.index(name)]]:
            bad.append("%s is over its budget: %d bytes" % (name, size))
        if re.search(r"\d{10,}|@|https?:|\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", text):
            bad.append("%s holds something like an API number, an e-mail address, a link or a phone number" % name)
    if len(docs) < len(NAMES):
        return bad
    series, cp, ops, pts = (docs[n] for n in NAMES)
    is_int = lambda v: type(v) is int  # noqa: E731

    def months_ok(ms, label):
        if not (isinstance(ms, list) and ms and all(re.fullmatch(r"\d{4}-\d\d", m) for m in ms)):
            bad.append("%s months are not year-months" % label)
            return False
        want, (y, m) = [], (int(ms[0][:4]), int(ms[0][5:]))
        for _ in ms:
            want.append("%04d-%02d" % (y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if ms != want:
            bad.append("%s months have a gap or are out of order" % label)
            return False
        return True

    asof = series.get("asOf")
    try:
        w = window_of(date.fromisoformat(asof))
    except (TypeError, ValueError):
        bad.append("series asOf is not a date")
        return bad
    if any(d.get("asOf") != asof for d in (series, cp, ops, pts)):
        bad.append("the four files do not share one asOf")

    # series
    if list(series) != ["asOf", "through", "months", "permits", "src"]:
        bad.append("series keys")
    elif months_ok(series["months"], "series"):
        if series["months"][0] != "2019-01" or series["months"][-1] != D1.month_label(w["last"]):
            bad.append("series runs from %s to %s, not 2019-01 to %s" % (series["months"][0], series["months"][-1], D1.month_label(w["last"])))
        if len(series["permits"]) != len(series["months"]) or not all(is_int(v) and v >= 0 for v in series["permits"]):
            bad.append("series permits are not counts, one a month")
        elif sum(series["permits"][-12:]) == 0:
            bad.append("series has no permit in its last 12 months")

    # counties
    if list(cp) != ["asOf", "months", "noCounty", "counties"]:
        bad.append("county-permits keys")
    elif months_ok(cp["months"], "county") and len(cp["months"]) == 36:
        if cp["months"][-1] != D1.month_label(w["last"]):
            bad.append("county months do not end at the last complete month")
        tot = 0
        for fips, c in cp["counties"].items():
            ok = fips in valid and list(c) == ["p12", "p12prev", "m", "depth", "ops"]
            ok = ok and is_int(c["p12"]) and is_int(c["p12prev"]) and c["p12"] >= 0 and c["p12prev"] >= 0
            ok = ok and isinstance(c["m"], list) and len(c["m"]) == 36 and all(is_int(v) and v >= 0 for v in c["m"])
            ok = ok and (c["depth"] is None or (is_int(c["depth"]) and c["depth"] > 0))
            ok = ok and all(isinstance(o, list) and len(o) == 3 and D.nameable(o[0]) and is_int(o[2]) and o[2] >= 1 for o in c["ops"])
            ok = ok and len(c["ops"]) <= 8 and sum(o[2] for o in c["ops"]) <= c["p12"]
            if not ok:
                bad.append("county %s is malformed" % fips)
                continue
            tot += sum(c["m"])
        if series.get("permits") and len(series["permits"]) >= 36 and sum(series["permits"][-36:]) != tot + cp["noCounty"]:
            bad.append("the county months add up to %d (and %s without a county), the series to %d" % (tot, cp["noCounty"], sum(series["permits"][-36:])))

    # operators
    if ops.get("cols") != OP_COLS or not isinstance(ops.get("rows"), list):
        bad.append("operators cols")
    elif months_ok(ops["months"], "operator") and len(ops["months"]) == 24:
        seen, prev_key = set(), None
        for row in ops["rows"]:
            if not (isinstance(row, list) and len(row) == len(OP_COLS)):
                bad.append("an operator row is the wrong length")
                continue
            r = dict(zip(OP_COLS, row))
            band_ok = r["band"] == ("A" if r["new12"] >= 10 else "B" if r["new12"] >= 1 else "C")
            ok = band_ok and D.nameable(r["name"]) and r["num"] not in seen and r["type"] in ("corporation", "LLC", "limited partnership")
            ok = ok and all(is_int(r[k]) and r[k] >= 0 for k in ("new12", "prev12", "all12", "all24", "depth", "counties", "newDrill"))
            ok = ok and r["new12"] + r["prev12"] <= r["all24"] and r["new12"] <= r["all12"] <= r["all24"]
            ok = ok and isinstance(r["m24"], list) and len(r["m24"]) == 24 and sum(r["m24"]) <= r["new12"] + r["prev12"]
            ok = ok and re.fullmatch(r"\d{4}-\d\d-\d\d", r["last"] or "") and (r["county"] == "" or r["county"] in valid)
            # the office city and state come straight from the file: a city is a place name and a state two letters, never an address, a phone number or a person
            ok = ok and (not r["city"] or CITY_OK.fullmatch(r["city"])) and (not r["state"] or STATE_OK.fullmatch(r["state"]))
            key = (-r["new12"], -r["all24"], r["num"])
            ok = ok and (prev_key is None or key >= prev_key)
            prev_key = key
            seen.add(r["num"])
            if not ok:
                bad.append("operator %s is malformed" % row[1])
    # points
    if pts.get("cols") != PT_COLS or list(pts) != ["asOf", "t0", "ops", "opNums", "cols", "pts", "coverage"] or pts.get("t0") != T0.isoformat():
        bad.append("permits keys")
    else:
        if len(pts["ops"]) != len(pts["opNums"]) or not all(D.nameable(n) for n in pts["ops"]):
            bad.append("permit operators: lengths differ or a name fails the rule")
        lo, hi = w["cut24"] - T0.toordinal(), w["asofo"] - T0.toordinal()
        wrong = 0
        for p in pts["pts"]:
            ok = isinstance(p, list) and len(p) == 6 and all(is_int(v) for v in p)
            ok = ok and LAT_MIN * 1e4 <= p[0] <= LAT_MAX * 1e4 and LON_MIN * 1e4 <= p[1] <= LON_MAX * 1e4 and p[0] % 10 == 0 and p[1] % 10 == 0
            ok = ok and -1 <= p[2] < len(pts["ops"]) and lo <= p[3] <= hi and p[4] >= 0 and "%03d" % p[5] in valid
            wrong += not ok
        if wrong:
            bad.append("%d permit points are malformed" % wrong)
        cv = pts["coverage"]
        if (list(cv) != ["months", "total", "located", "share12", "share24"] or len(cv["months"]) != 24 or len(cv["total"]) != 24 or len(cv["located"]) != 24
                or any(l > t for t, l in zip(cv["total"], cv["located"]))):
            bad.append("permits coverage block")
        elif months_ok(cv["months"], "coverage") and series.get("permits") and cv["total"] != series["permits"][-24:]:
            bad.append("the coverage totals are not the series' last 24 months")
    return bad


# ------------------------------------------------------------------------------------------------ run

def main():
    ap = argparse.ArgumentParser(description="D8 monthly: Oklahoma's permit history files (see the module docstring)")
    ap.add_argument("--master", help="a local copy of the master workbook (default: download it)")
    ap.add_argument("--daily", help="a local copy of the daily workbook (default: download it)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dl", default=DL)
    ap.add_argument("--asof", help="end the windows on this day (default: the newest approval day in the files)")
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    a = ap.parse_args()
    if a.check:
        problems = validate(a.out)
        for p in problems:
            log("CHECK failed: " + p)
        log("checks ok (%s)" % a.out if not problems else "%d problem(s)" % len(problems))
        return 1 if problems else 0
    paths, modified = [], None
    folder = None
    for given, name in ((a.master, MASTER), (a.daily, DAILY)):
        if given:
            paths.append(given)
            continue
        if folder is None:
            os.makedirs(a.dl, exist_ok=True)
            folder = tempfile.mkdtemp(prefix="run-", dir=a.dl)  # a new folder for every download
        dest = os.path.join(folder, name)
        t = time.time()
        got = D.fetch(D.FILES + name, dest)
        log("downloaded %s: %.1f MB in %.0f s, made %s" % (name, got["bytes"] / 1e6, time.time() - t, got["modified"]))
        paths.append(dest)
        modified = modified or got["modified"]
    t = time.time()
    coll = collect(iter_rows(paths))
    log("read %d rows in %.0f s: %s" % (coll["stats"]["rows"], time.time() - t, dict(coll["stats"])))
    names = D.Lookups().county
    docs, rep = build(coll, names, date.fromisoformat(a.asof) if a.asof else None, modified)
    os.makedirs(a.out, exist_ok=True)
    for name, doc in docs.items():
        log("wrote %s (%d bytes)" % (name, write_json(os.path.join(a.out, name), doc)))
    problems = validate(a.out, names)
    for p in problems:
        log("CHECK failed: " + p)
    log("approvals through %s: %d new-drill permits (%d in the last 12 months, %d before; %d without a county), %d named operators, %d located points, "
        "%.0f%% of the last 12 months' permits went to named operators"
        % (rep["asof"], rep["new"], rep["p12"], rep["p12prev"], rep["no_county"], rep["operators"], rep["points"], 100 * (rep["named_share12"] or 0)))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
