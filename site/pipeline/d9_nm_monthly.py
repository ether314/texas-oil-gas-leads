#!/usr/bin/env python3
"""D9: New Mexico's drilling history, for the Overview, the Map and the Operators page of the Oil tracker.

The New Mexico Oil Conservation Division (OCD) publishes its well records as an ArcGIS feature layer that it refreshes daily
(https://gis.emnrd.nm.gov/arcgis/rest/services/OCDView/Wells_Public/FeatureServer/0, listed on the OCD Geospatial Hub): one point per
well, with its API number, operator (OGRID and name), county, surface location, depths, status and spud date. This reads it and writes
four files into site/public/data/, shaped like Oklahoma's (d8_ok_monthly.py) and Texas's, so every view treats the three states alike:

  series-permits-nm.json   wells spudded by month since 2019-01 (complete months only)
  county-permits-nm.json   per county: the last 12 months and the 12 before, 36 monthly counts, mean depth, top operators
  operators-nm.json        the named operators that spudded a well in the last 24 months
  permits-nm.json          one point per well spudded in the last 24 months, at its surface location (rounded to about 100 m)

What is counted is wells SPUDDED, not permits approved, and that is a choice forced by the data (NOTES_D9.md has the numbers): the layer
does not carry a permit (APD) approval date for a well once it has moved on, the approval counts the OCD publishes are yearly and cover
only the permits it processes itself, and the layer's history (queryable back to 2024) can say how many wells were added in a month but
not which. A spud date is a real, dated fact for every well since the 1900s. It is reported late, though: a month's spuds arrive over
about two months (August 2026 stood at 4 of 108 on Aug 15, 91 on Sep 15, 107 on Oct 15), so a month is shown only when it ended at least
LAG_DAYS days ago, and the files end there. Beside the permits of Texas and Oklahoma the Overview names this measure wherever it shows it.

  python3 -I site/pipeline/d9_nm_monthly.py [--out DIR] [--asof YYYY-MM-DD] [--today YYYY-MM-DD]
  python3 -I site/pipeline/d9_nm_monthly.py --check [--out DIR]          only reload and check what is already there
  python3 -I site/pipeline/d9_nm_monthly.py --counties [--dl DIR]        rebuild counties-nm.geo.json from the Census county file

Operators are named only by the corporate rule (d8_ok_daily.nameable: a corporation, LLC or partnership, never a person's dba). Nothing names a
well, a lease or an API number, and no street, signer or phone is read. The layer's data is parsed, never run; requests identify no person.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d1_permits_geo as D1  # noqa: E402
import d8_ok_daily as D  # noqa: E402
import d8_ok_monthly as M  # noqa: E402

LAYER = "https://gis.emnrd.nm.gov/arcgis/rest/services/OCDView/Wells_Public/FeatureServer/0"
UA = "Mozilla/5.0 (research script)"
OUT = os.path.join(SITE, "public", "data")
DL = os.path.join(os.path.dirname(SITE), "dl", "nm")
COUNTIES_GEO = os.path.join(OUT, "counties-nm.geo.json")
NAMES = ("series-permits-nm.json", "county-permits-nm.json", "operators-nm.json", "permits-nm.json")
LAG_DAYS = 60  # a month is shown once it ended this long ago: about 95% of its spud dates are in by then
BOX = (31.3, 37.1, -109.2, -102.9)  # New Mexico, as (lat min, lat max, lon min, lon max)
KEEP_FROM = 2018
FIELDS = "id,type,status,ogrid,ogrid_name,county_code,latitude,longitude,spud_date,measured_vertical_depth,true_vertical_depth"
log = D.log


# ------------------------------------------------------------------------------------------------ the layer

def query(params, retries=4):
    """One request to the layer's query endpoint, as parsed JSON; retried with a pause if the server hiccups."""
    url = LAYER + "/query?" + urllib.parse.urlencode(dict(params, f="json"))
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                doc = json.loads(r.read().decode("utf-8"))
            if "error" in doc:
                raise OSError(str(doc["error"])[:160])
            return doc
        except Exception as e:  # noqa: BLE001 - network hiccups, 5xx, an ArcGIS error page
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError("could not read the New Mexico wells layer: %r" % last)


def fetch_spuds(since=KEEP_FROM):
    """Every well with a real spud date since `since` (the layer marks 'not spudded' with the year 9999 and some with 1900), as attribute dicts."""
    where = "spud_date >= timestamp '%d-01-01 00:00:00' AND spud_date < timestamp '3000-01-01 00:00:00'" % since
    rows, offset = [], 0
    while True:
        doc = query({"where": where, "outFields": FIELDS, "returnGeometry": "false", "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 6000})
        got = [f["attributes"] for f in doc.get("features", [])]
        rows += got
        if not doc.get("exceededTransferLimit") or not got:
            return rows
        offset += len(got)


def fetch_first_spuds():
    """{OGRID: the day of the operator's first spud ever}, worked out by the server (the layer holds wells back to 1900-odd)."""
    stat = json.dumps([{"statisticType": "min", "onStatisticField": "spud_date", "outStatisticFieldName": "first"}])
    doc = query({"where": "spud_date >= timestamp '1930-01-01 00:00:00' AND spud_date < timestamp '3000-01-01 00:00:00'", "groupByFieldsForStatistics": "ogrid", "outStatistics": stat})
    out = {}
    for f in doc.get("features", []):
        a = f["attributes"]
        if a.get("ogrid") is not None and a.get("first") is not None:
            out[str(a["ogrid"])] = to_day(a["first"])
    return out


def to_day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


# ------------------------------------------------------------------------------------------------ the records

def county_of(r):
    return r["county"]


def clean_name(text):
    return " ".join((text or "").upper().split())


def collect(wells, first_spud, today=None):
    """Fold the layer's wells into the record shape d8_ok_monthly.build reads. Returns {'permits', 'first_dr', 'stats'}; a record is a dict of
    api, kind ('SP': a spud), day, op, name, city, state, depth, lat, lon, county. A well is one record: its API number, on its spud day."""
    today = today or date.today()
    permits, st = {}, collections.Counter()
    lat_lo, lat_hi, lon_lo, lon_hi = BOX
    for w in wells:
        st["wells"] += 1
        ms = w.get("spud_date")
        day = to_day(ms) if isinstance(ms, (int, float)) and abs(ms) < 9e12 else None
        if day is None or day.year < KEEP_FROM or day > today:
            st["no real spud date"] += 1
            continue
        api = (w.get("id") or "").strip()
        if not re.fullmatch(r"\d\d-\d\d\d-\d{5}", api):
            st["no usable API number"] += 1
            continue
        op = str(w["ogrid"]) if w.get("ogrid") is not None else ""
        # the layer carries a depth for about 3% of the wells spudded since 2024 (the rest are 0 until completion), so no depth is published: a mean
        # of that few would describe the old verticals and say nothing about the horizontals that are most of the drilling
        st["with a depth in the layer (not published)"] += 1 if (w.get("measured_vertical_depth") or w.get("true_vertical_depth") or 0) > 0 else 0
        depth = 0
        lat, lon = w.get("latitude"), w.get("longitude")
        located = isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi
        code = w.get("county_code")
        key = (api, "SP", day)
        if key in permits:
            st["a well in the layer twice"] += 1
            continue
        permits[key] = {"api": api, "kind": "SP", "day": day, "op": op, "name": clean_name(w.get("ogrid_name")), "city": "", "state": "",
                        "depth": max(depth, 0), "lat": lat if located else None, "lon": lon if located else None,
                        "county": "%03d" % code if isinstance(code, int) and 0 < code < 1000 else ""}
        st["spudded wells"] += 1
    return {"permits": permits, "first_dr": {op: d for op, d in first_spud.items()}, "stats": st}


def reliable_asof(today, lag=LAG_DAYS):
    """The last day of the newest month that ended at least `lag` days ago: where the files end, because spud dates arrive about two months late."""
    cut = today - timedelta(days=lag)
    return cut if (cut + timedelta(days=1)).month != cut.month else cut.replace(day=1) - timedelta(days=1)


SPEC = {
    "names": NAMES, "box": BOX, "new_kind": "SP", "county_of": county_of,
    "src": lambda asof, modified: ("New Mexico Oil Conservation Division, public well layer (Wells_Public, refreshed daily): wells by spud date, one per API number, "
                                   "by month spudded. Spud dates are reported about two months late, so the series ends with the newest month that ended at least %d days "
                                   "before the layer was read; spuds through %s" % (LAG_DAYS, asof.isoformat())),
}


# ------------------------------------------------------------------------------------------------ county outlines

def build_counties(zip_path, out_path):
    """The 33 New Mexico counties from the Census cartographic boundary file (the same source and readers as the Texas and Oklahoma maps)."""
    import d2_layers as D2
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        pick = lambda ext: next(n for n in names if n.lower().endswith(ext))  # noqa: E731
        shp, dbf = z.read(pick(".shp")), z.read(pick(".dbf"))
    rows, shapes = D2.read_dbf(dbf), D2.read_shp(shp)
    out = {}
    for row, rings in zip(rows, shapes):
        if row and rings and row.get("STATEFP") == "35":
            out[row["COUNTYFP"]] = {"n": row["NAME"], "polys": D2.finalize(D2.rings_to_polys(rings))}
    if len(out) != 33 or not all("001" <= c <= "061" for c in out):
        raise ValueError("expected the 33 New Mexico counties 001..061, found %d" % len(out))
    D.write_json(out_path, D2.build_counties_doc(out))
    return len(out)


def county_names():
    try:
        with open(COUNTIES_GEO, encoding="utf-8") as f:
            return {x["properties"]["f"]: x["properties"]["n"] for x in json.load(f)["features"]}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------------------------------------ run

def main():
    ap = argparse.ArgumentParser(description="D9: New Mexico's drilling history files (see the module docstring)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dl", default=DL)
    ap.add_argument("--today", help="treat this as today (default the real day)")
    ap.add_argument("--asof", help="end the windows on this day (default: the newest month that ended at least %d days ago)" % LAG_DAYS)
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    ap.add_argument("--counties", action="store_true", help="rebuild counties-nm.geo.json from the Census county file")
    a = ap.parse_args()
    if a.counties:
        zp = os.path.join(a.dl, "cb_2025_us_county_5m.zip")
        os.makedirs(a.dl, exist_ok=True)
        if not os.path.exists(zp):
            D.fetch("https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip", zp)
        log("wrote %s with %d counties" % (COUNTIES_GEO, build_counties(zp, COUNTIES_GEO)))
        return 0
    names = county_names()
    if not names:
        sys.exit("counties-nm.geo.json is missing: run with --counties first")
    if a.check:
        problems = M.validate(a.out, names, SPEC)
        for p in problems:
            log("CHECK failed: " + p)
        log("checks ok (%s)" % a.out if not problems else "%d problem(s)" % len(problems))
        return 1 if problems else 0
    today = date.fromisoformat(a.today) if a.today else date.today()
    t = time.time()
    wells = fetch_spuds()
    first = fetch_first_spuds()
    log("read %d wells with a spud date since %d and %d operators' first spuds in %.0f s" % (len(wells), KEEP_FROM, len(first), time.time() - t))
    coll = collect(wells, first, today)
    log("stats: %s" % dict(coll["stats"]))
    asof = date.fromisoformat(a.asof) if a.asof else reliable_asof(today)
    docs, rep = M.build(coll, names, asof, today.isoformat(), SPEC)
    os.makedirs(a.out, exist_ok=True)
    for name, doc in docs.items():
        log("wrote %s (%d bytes)" % (name, M.write_json(os.path.join(a.out, name), doc)))
    problems = M.validate(a.out, names, SPEC)
    for p in problems:
        log("CHECK failed: " + p)
    log("spuds through %s: %d wells (%d in the last 12 months, %d before; %d without a county), %d named operators, %d located points, %.0f%% of the last 12 months' wells by named operators"
        % (rep["asof"], rep["new"], rep["p12"], rep["p12prev"], rep["no_county"], rep["operators"], rep["points"], 100 * (rep["named_share12"] or 0)))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
