#!/usr/bin/env python3
"""D2 producer for the Texas oil & gas leads site (contract: site/DATA_CONTRACT.md).

Writes four files into site/public/data/ (re-runnable, stdlib only):
  counties.geo.json     the 254 Texas counties, WGS84, 3-decimal coordinates
  county-labor.json     BLS QCEW annual averages, private ownership, NAICS 211 (o) and 213 (s), per county
  zip-companies.json    lead-pool companies (Texas, fit != deprioritize) grouped by ZIP, with ZIP centroids
  county-companies.json the same companies grouped by county (Comptroller county_code -> FIPS)

Run:  python3 -I site/pipeline/d2_layers.py [--dl DIR] [--out DIR] [--refresh] [--strict-zip]
                                            [--counties-source cb|tigerweb]

Sources, all public with no key (see NOTES_D2.md):
  counties  Census cartographic boundary file cb_<year>_us_county_5m (GENZ2025, then GENZ2024), clipped to the
            shoreline; last resort TIGERweb State_County layer 11 (adds offshore water). Counties source is parsed
            straight from the zip held in memory.
  labor     https://data.bls.gov/cew/data/api/<year>/a/industry/{211,213}.csv  (2025, then 2024 if not yet published)
  zip       Census ZCTA Gazetteer (2025, then 2024, 2023)
  leads     <workspace root>/leadpool_ranked.csv. Only fit, state, zip, county_code, city, new_entity and rrc_match are
            read; city is used only to place PO-box ZIPs that have no ZCTA and is never written out.
Downloads go to <dl>/<name>/<file>, one folder per file, and are only parsed, never executed. A file already present is
reused unless --refresh is given.
"""
import argparse
import collections
import csv
import http.client
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

UA = "Mozilla/5.0 (research script)"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
DEFAULT_OUT = os.path.join(SITE, "public", "data")
LEADS = os.path.join(ROOT, "leadpool_ranked.csv")
# the gitignored dl/ folder at the repo root; override with --dl or the D2_DL_DIR environment variable
DEFAULT_DL = os.environ.get("D2_DL_DIR") or (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))

BUDGET = {"counties.geo.json": 700_000, "county-labor.json": 400_000,
          "zip-companies.json": 400_000, "county-companies.json": 400_000}
LAT_RANGE, LON_RANGE = (25.5, 36.6), (-106.8, -93.4)  # Texas box from the contract
HOUSTON_BOX = (29.3, 30.4, -96.0, -94.8)  # lat0, lat1, lon0, lon1 (spot check only)

CB_URL = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_county_5m.zip"
TIGERWEB_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/11/query?"
                + urllib.parse.urlencode({"where": "STATE='48'", "outFields": "COUNTY,BASENAME",
                                          "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "3",
                                          "maxAllowableOffset": "0.002", "f": "geojson"}))
QCEW_URL = "https://data.bls.gov/cew/data/api/{y}/a/industry/{i}.csv"
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_zcta_national.zip"


class NotFound(Exception):
    pass


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------------------------------- checks
FAILED = []


def check(name, ok, detail=""):
    """Hard contract check: any failure blocks writing the output files."""
    log("  [%s] %s%s" % ("ok" if ok else "FAIL", name, (" - " + detail) if detail else ""))
    if not ok:
        FAILED.append(name)
    return ok


# ---------------------------------------------------------------------------------------------------- download
def fetch(dl, name, url, fname, refresh=False, max_bytes=60_000_000):
    folder = os.path.join(dl, name)
    path = os.path.join(folder, fname)
    if not refresh and os.path.isfile(path) and os.path.getsize(path) > 0:
        log("  cached  %s (%d KB)" % (path, os.path.getsize(path) // 1024))
        return path
    os.makedirs(folder, exist_ok=True)
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("download larger than %d bytes" % max_bytes)
            if not data:
                raise ValueError("empty download")
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            log("  fetched %s (%d KB)" % (url.split("?")[0], len(data) // 1024))
            return path
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url)
            last = e
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            last = e
        time.sleep(2 * attempt)
    raise RuntimeError("download failed: %s (%s)" % (url.split("?")[0], last))


# ---------------------------------------------------------------------------------------------------- geometry
def ring_area(r):
    """Signed shoelace area of a closed ring (degrees^2): > 0 means counter-clockwise (x east, y north)."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(r, r[1:]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def in_ring(x, y, r):
    inside = False
    x1, y1 = r[-1]
    for x2, y2 in r:
        if (y2 > y) != (y1 > y) and x < (x1 - x2) * (y - y2) / (y1 - y2) + x2:
            inside = not inside
        x1, y1 = x2, y2
    return inside


def clean_ring(ring, want_ccw):
    """Round to 3 decimals, drop repeated points, close the ring, set winding. None if it degenerates."""
    pts = []
    for p in ring:
        q = (round(p[0], 3), round(p[1], 3))
        if not pts or q != pts[-1]:
            pts.append(q)
    if len(pts) > 1 and pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 4:
        return None
    a = ring_area(pts)
    if a == 0:
        return None
    if (a > 0) != want_ccw:
        pts.reverse()
    return pts


def finalize(polys):
    """polys: list of [exterior, hole, ...]. RFC 7946 winding (exterior counter-clockwise), largest polygon first."""
    out = []
    for p in polys:
        ext = clean_ring(p[0], True)
        if ext is None:
            continue
        out.append([ext] + [h for h in (clean_ring(r, False) for r in p[1:]) if h])
    out.sort(key=lambda p: -abs(ring_area(p[0])))
    return out


def rings_to_polys(rings):
    """Shapefile rings -> polygons. ESRI winding: exterior rings run clockwise, holes counter-clockwise."""
    ext, holes = [], []
    for r in rings:
        a = ring_area(r)
        if a != 0:
            (ext if a < 0 else holes).append(r)
    polys = [[e] for e in ext]
    for h in holes:
        best = None
        for p in polys:
            if sum(in_ring(x, y, p[0]) for x, y in h[:5]) * 2 > len(h[:5]):
                if best is None or abs(ring_area(p[0])) < abs(ring_area(best[0])):
                    best = p
        if best is None:
            raise ValueError("a hole ring lies outside every exterior ring")
        best.append(h)
    return polys


def build_locator(counties):
    boxes = []
    for f, c in counties.items():
        for poly in c["polys"]:
            xs = [p[0] for p in poly[0]]
            ys = [p[1] for p in poly[0]]
            boxes.append((min(xs), min(ys), max(xs), max(ys), f, poly))

    def locate(lon, lat):
        for x0, y0, x1, y1, f, poly in boxes:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and in_ring(lon, lat, poly[0]) \
                    and not any(in_ring(lon, lat, h) for h in poly[1:]):
                return f
        return None
    return locate


# ---------------------------------------------------------------------------------------------------- counties
def read_dbf(data):
    nrec, hlen, rlen = struct.unpack("<xxxxIHH", data[:12])
    fields, off = [], 32
    while data[off] != 0x0D:
        fields.append((data[off:off + 11].split(b"\0")[0].decode("ascii"), data[off + 16]))
        off += 32
    rows = []
    for i in range(nrec):
        rec = data[hlen + i * rlen: hlen + (i + 1) * rlen]
        if rec[:1] == b"*":
            rows.append(None)
            continue
        pos, row = 1, {}
        for name, ln in fields:
            row[name] = rec[pos:pos + ln].decode("utf-8", "replace").strip()
            pos += ln
        rows.append(row)
    return rows


def read_shp(data):
    if struct.unpack(">i", data[:4])[0] != 9994:
        raise ValueError("not a shapefile")
    out, pos = [], 100
    while pos + 8 <= len(data):
        clen = struct.unpack(">i", data[pos + 4:pos + 8])[0]
        pos += 8
        c = data[pos:pos + clen * 2]
        pos += clen * 2
        st = struct.unpack("<i", c[:4])[0]
        if st == 0:
            out.append(None)
            continue
        if st not in (5, 15, 25):
            raise ValueError("unexpected shape type %d" % st)
        nparts, npts = struct.unpack("<ii", c[36:44])
        parts = list(struct.unpack("<%di" % nparts, c[44:44 + 4 * nparts])) + [npts]
        base = 44 + 4 * nparts
        xy = struct.unpack("<%dd" % (2 * npts), c[base:base + 16 * npts])
        pts = list(zip(xy[0::2], xy[1::2]))
        out.append([pts[parts[i]:parts[i + 1]] for i in range(nparts)])
    return out


def counties_from_cb(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        pick = lambda ext: next(n for n in names if n.lower().endswith(ext))  # noqa: E731
        shp_n, dbf_n, prj_n = pick(".shp"), pick(".dbf"), pick(".prj")
        for n in (shp_n, dbf_n):
            if z.getinfo(n).file_size > 100_000_000:
                raise ValueError("%s is unreasonably large" % n)
        shp, dbf, prj = z.read(shp_n), z.read(dbf_n), z.read(prj_n).decode("ascii", "replace")
    if "GEOGCS" not in prj:
        raise ValueError("shapefile is not in geographic coordinates")
    rows, shapes = read_dbf(dbf), read_shp(shp)
    if len(rows) != len(shapes):
        raise ValueError("dbf and shp record counts differ")
    out = {}
    for row, rings in zip(rows, shapes):
        if row and rings and row.get("STATEFP") == "48":
            out[row["COUNTYFP"]] = {"n": row["NAME"], "polys": finalize(rings_to_polys(rings))}
    return out


def counties_from_tigerweb(path):
    with open(path, "rb") as f:
        doc = json.load(f)
    if doc.get("error") or doc.get("exceededTransferLimit"):
        raise ValueError("TIGERweb returned an error or a capped result")
    out = {}
    for ft in doc["features"]:
        g = ft["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out[ft["properties"]["COUNTY"]] = {
            "n": ft["properties"]["BASENAME"],
            "polys": finalize([[[(p[0], p[1]) for p in ring] for ring in poly] for poly in polys])}
    return out


def load_counties(args, dl):
    sources = []
    if args.counties_source == "cb":
        for y in (2025, 2024):
            sources.append(("cb_%d_us_county_5m (shoreline-clipped)" % y, "counties_cb%d_5m" % y,
                            CB_URL.format(y=y), "cb_%d_us_county_5m.zip" % y, counties_from_cb))
    sources.append(("TIGERweb State_County layer 11 (includes offshore water)", "counties_tigerweb",
                    TIGERWEB_URL, "tigerweb_counties_tx.json", counties_from_tigerweb))
    for label, name, url, fname, parse in sources:
        try:
            counties = parse(fetch(dl, name, url, fname, args.refresh))
            if len(counties) != 254:
                raise ValueError("expected 254 Texas counties, found %d" % len(counties))
            return label, url.split("?")[0], counties
        except (NotFound, RuntimeError, ValueError, KeyError, StopIteration, struct.error,
                zipfile.BadZipFile, json.JSONDecodeError) as e:
            log("  counties source %s failed: %s" % (label, e))
    sys.exit("ERROR: no county source worked")


def build_counties_doc(counties):
    feats = []
    for f in sorted(counties):
        polys = counties[f]["polys"]
        geom = {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 \
            else {"type": "MultiPolygon", "coordinates": polys}
        feats.append({"type": "Feature", "properties": {"f": f, "n": counties[f]["n"]}, "geometry": geom})
    return {"type": "FeatureCollection", "features": feats}


def check_counties(doc):
    feats = doc["features"]
    fips = [ft["properties"]["f"] for ft in feats]
    check("254 county features", len(feats) == 254, str(len(feats)))
    check("FIPS are the 254 odd codes 001..507", fips == ["%03d" % i for i in range(1, 508, 2)])
    check("properties are exactly {f, n}", all(set(ft["properties"]) == {"f", "n"} and ft["properties"]["n"]
                                               for ft in feats))
    bad_ring = out_box = 0
    for ft in feats:
        g = ft["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for i, ring in enumerate(poly):
                if len(ring) < 4 or ring[0] != ring[-1] or (ring_area(ring) > 0) != (i == 0):
                    bad_ring += 1
                for x, y in ring:
                    if not (LON_RANGE[0] <= x <= LON_RANGE[1] and LAT_RANGE[0] <= y <= LAT_RANGE[1]):
                        out_box += 1
    check("rings closed, >= 4 points, exterior ccw / holes cw", bad_ring == 0, "%d bad" % bad_ring)
    check("all coordinates inside the Texas box", out_box == 0, "%d outside" % out_box)


# ---------------------------------------------------------------------------------------------------- labor
def qcew_rows(path, ind, year):
    counties, state = {}, None
    agglvl = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        need = {"area_fips", "own_code", "industry_code", "agglvl_code", "size_code", "year", "disclosure_code",
                "annual_avg_estabs", "annual_avg_emplvl", "total_annual_wages", "annual_avg_wkly_wage"}
        if not need <= set(rd.fieldnames or []):
            raise ValueError("unexpected QCEW header in %s" % path)
        for r in rd:
            a = r["area_fips"].strip()
            if r["own_code"] != "5" or not (len(a) == 5 and a.isdigit() and a.startswith("48")):
                continue
            if r["industry_code"] != ind or r["year"] != str(year):
                raise ValueError("row %s is %s/%s, expected %s/%s" % (a, r["industry_code"], r["year"], ind, year))
            if a == "48000":
                state = r
                continue
            if a == "48999" or r["size_code"] not in ("", "0"):
                continue
            agglvl.add(r["agglvl_code"])
            if a[2:] in counties:
                raise ValueError("duplicate QCEW row for %s" % a)
            counties[a[2:]] = r
    if agglvl != {"75"}:
        raise ValueError("county rows are not all agglvl 75 (county, NAICS 3-digit, by ownership): %s" % agglvl)
    return counties, state


def labor_entry(r):
    """{"estab","emp","wage"} or None when suppressed (disclosure_code N) or unusable."""
    if r["disclosure_code"].strip() == "N":
        return None
    estab = int(float(r["annual_avg_estabs"] or 0))
    emp = int(float(r["annual_avg_emplvl"] or 0))
    wages = float(r["total_annual_wages"] or 0)
    wk = float(r["annual_avg_wkly_wage"] or 0)
    if estab <= 0 or emp <= 0:
        return None
    if wk <= 0:
        wk = wages / emp / 52.0
    return {"estab": estab, "emp": emp, "wage": int(round(wk))} if wk > 0 else None


def build_labor(args, dl, fips_list):
    for year in (2025, 2024):
        try:
            paths = {i: fetch(dl, "qcew_%d_%s" % (year, i), QCEW_URL.format(y=year, i=i), "%s.csv" % i, args.refresh)
                     for i in ("211", "213")}
            break
        except NotFound as e:
            log("  QCEW %d not published yet (%s)" % (year, e))
    else:
        sys.exit("ERROR: no QCEW year available")
    parsed = {i: qcew_rows(p, i, year) for i, p in paths.items()}
    ent = {i: {f: labor_entry(r) for f, r in parsed[i][0].items()} for i in parsed}
    unknown = [f for i in ent for f in ent[i] if f not in fips_list]
    check("QCEW county FIPS all exist in the county layer", not unknown, str(unknown[:5]))
    doc = {"year": year,
           "src": ("BLS QCEW open data, annual averages %d, private ownership; o = NAICS 211 oil and gas extraction, "
                   "s = NAICS 213 support activities for mining; wage = average weekly wage in USD; null = suppressed "
                   "(disclosure_code N) or no establishments. Files: https://data.bls.gov/cew/data/api/%d/a/industry/"
                   "211.csv and .../213.csv" % (year, year)),
           "counties": {f: {"o": ent["211"].get(f), "s": ent["213"].get(f)} for f in sorted(fips_list)}}
    stats = {"year": year, "rows": {i: len(parsed[i][0]) for i in parsed},
             "o": sum(1 for f in doc["counties"] if doc["counties"][f]["o"]),
             "s": sum(1 for f in doc["counties"] if doc["counties"][f]["s"]),
             "state": {i: parsed[i][1] for i in parsed}}
    return doc, stats


def check_labor(doc, stats):
    cs = doc["counties"]
    check("labor has 254 county keys with o and s", len(cs) == 254 and all(set(v) == {"o", "s"} for v in cs.values()))
    good = all(v is None or (set(v) == {"estab", "emp", "wage"} and all(isinstance(x, int) and x > 0
                                                                       for x in v.values()))
               for c in cs.values() for v in c.values())
    check("labor entries are null or positive ints {estab, emp, wage}", good)
    check("labor year is an int", isinstance(doc["year"], int), str(doc["year"]))


# ---------------------------------------------------------------------------------------------------- companies
def load_gazetteer(args, dl):
    for year in (2025, 2024, 2023):
        try:
            path = fetch(dl, "zcta_gaz_%d" % year, GAZ_URL.format(y=year), "%d_Gaz_zcta_national.zip" % year,
                         args.refresh)
            break
        except NotFound:
            continue
    else:
        sys.exit("ERROR: no ZCTA Gazetteer found")
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        if z.getinfo(name).file_size > 100_000_000:
            raise ValueError("gazetteer text is unreasonably large")
        lines = z.read(name).decode("utf-8-sig").splitlines()
    delim = "|" if "|" in lines[0] else "\t"  # 2025 vintage is pipe-delimited, older ones tab-delimited
    hdr = [h.strip() for h in lines[0].split(delim)]
    i_id, i_lat, i_lon = hdr.index("GEOID"), hdr.index("INTPTLAT"), hdr.index("INTPTLONG")
    cent = {}
    for ln in lines[1:]:
        p = [x.strip() for x in ln.split(delim)]
        if len(p) > max(i_id, i_lat, i_lon):
            cent[p[i_id]] = (float(p[i_lat]), float(p[i_lon]))
    return year, cent


def comptroller_codes(counties):
    """Comptroller county_code = 1-based position in the alphabetical list of the 254 county names (letters only,
    so 'McCulloch' sorts after 'Maverick', and 'La Salle' as 'LaSalle'). Verified against the data, see check below."""
    order = sorted(counties, key=lambda f: re.sub(r"[^a-z]", "", counties[f]["n"].lower()))
    return {i + 1: f for i, f in enumerate(order)}


def read_leads():
    L = {"rows": 0, "tx": 0, "zips": {}, "zcity": collections.defaultdict(collections.Counter),
         "zcc": collections.defaultdict(collections.Counter), "codes": {}, "bad_zip": 0}
    with open(LEADS, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            L["rows"] += 1
            fit = r["fit"].strip()
            if r["state"].strip() != "TX" or fit == "deprioritize":
                continue
            L["tx"] += 1
            likely = 1 if fit == "likely" else 0
            new = 1 if r["new_entity"].strip() == "Y" else 0
            rrc = 1 if r["rrc_match"].strip() else 0
            z = r["zip"].strip()[:5]
            code = r["county_code"].strip()
            code = int(code) if code.isdigit() else -1
            if re.fullmatch(r"\d{5}", z):
                a = L["zips"].setdefault(z, [0, 0, 0, 0])
                a[0] += 1
                a[1] += likely
                a[2] += new
                a[3] += rrc
                L["zcity"][z][r["city"].strip().upper()] += 1
                L["zcc"][z][code] += 1
            else:
                L["bad_zip"] += 1
            c = L["codes"].setdefault(code, [0, 0, 0])
            c[0] += 1
            c[1] += likely
            c[2] += new
    return L


def build_zip_layer(L, cent, valid_codes, strict):
    """ZIP -> (lat, lon, tier). Tier 1: ZCTA centroid. Tier 2: company-weighted mean of the tier-1 ZIP centroids of
    the same city and county (PO-box and unique ZIPs have no ZCTA; city alone when the ZIP's own county_code is
    unknown). Tier 3: same county only. Else unplaced."""
    placed = {z: (cent[z][0], cent[z][1], 1) for z in L["zips"] if z in cent}
    if not strict:
        modal = lambda c: c.most_common(1)[0][0]  # noqa: E731
        city = {z: modal(L["zcity"][z]) for z in L["zips"]}
        cty = {z: modal(L["zcc"][z]) for z in L["zips"]}
        direct = list(placed)

        def same(k, z, tier):
            if tier == 2:
                return city[k] == city[z] and (cty[k] == cty[z] or cty[z] not in valid_codes)
            return cty[k] == cty[z]

        for z in L["zips"]:
            if z in placed:
                continue
            for tier in (2, 3):
                if tier == 3 and cty[z] not in valid_codes:
                    break
                pts = [(cent[k], L["zips"][k][0]) for k in direct if same(k, z, tier)]
                if pts:
                    w = sum(n for _, n in pts)
                    placed[z] = (sum(c[0] * n for c, n in pts) / w, sum(c[1] * n for c, n in pts) / w, tier)
                    break
    return placed


def check_code_mapping(L, cent, locate, code_to_fips):
    """Independent test of the county_code -> FIPS mapping: the county that contains each ZIP centroid, per code."""
    by = collections.defaultdict(collections.Counter)
    for z, codes in L["zcc"].items():
        if z in cent:
            f = locate(cent[z][1], cent[z][0])
            if f:
                for code, n in codes.items():
                    by[code][f] += n
    tested = agree = w_tested = w_agree = 0
    for code, c in by.items():
        if code in code_to_fips:
            tested += 1
            n = sum(c.values())
            w_tested += n
            if c.most_common(1)[0][0] == code_to_fips[code]:
                agree += 1
            w_agree += c.get(code_to_fips[code], 0)
    return tested, agree, w_tested, w_agree


# ---------------------------------------------------------------------------------------------------- output
def serialize(doc):
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_bytes(out_dir, name, data):
    path = os.path.join(out_dir, name)
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dl", default=DEFAULT_DL, help="download cache root (default: dl/ at the repo root)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output folder (default: site/public/data)")
    ap.add_argument("--refresh", action="store_true", help="download again even if a cached copy exists")
    ap.add_argument("--strict-zip", action="store_true",
                    help="drop ZIPs without a ZCTA centroid instead of placing them at their city centroid")
    ap.add_argument("--counties-source", choices=("cb", "tigerweb"), default="cb")
    args = ap.parse_args()
    if not os.path.isfile(LEADS):
        sys.exit("ERROR: %s not found" % LEADS)

    # ---- counties
    log("== counties")
    label, curl, counties = load_counties(args, args.dl)
    log("  source: %s" % label)
    cdoc = build_counties_doc(counties)
    check_counties(cdoc)
    locate = build_locator(counties)
    code_to_fips = comptroller_codes(counties)
    name = {f: c["n"] for f, c in counties.items()}
    check("code 57 = Dallas (113), 101 = Harris (201), 165 = Midland (329), 195 = Reeves (389)",
          [code_to_fips[k] for k in (57, 101, 165, 195)] == ["113", "201", "329", "389"],
          str([name[code_to_fips[k]] for k in (57, 101, 165, 195)]))

    # ---- labor
    log("== labor")
    ldoc, lstats = build_labor(args, args.dl, set(counties))
    check_labor(ldoc, lstats)

    # ---- companies
    log("== companies")
    gyear, cent = load_gazetteer(args, args.dl)
    log("  ZCTA Gazetteer %d: %d ZCTAs" % (gyear, len(cent)))
    L = read_leads()
    log("  lead pool rows %d, Texas with fit != deprioritize: %d, bad ZIP: %d" % (L["rows"], L["tx"], L["bad_zip"]))
    tested, agree, wt, wa = check_code_mapping(L, cent, locate, code_to_fips)
    check("county_code mapping agrees with ZIP centroids", tested > 0 and agree / tested >= 0.9,
          "modal county matches for %d of %d codes; %.1f%% of companies sit in the mapped county" %
          (agree, tested, 100.0 * wa / max(wt, 1)))
    placed = build_zip_layer(L, cent, set(code_to_fips), args.strict_zip)
    rows = []
    tiers = collections.Counter()
    tier_cos = collections.Counter()
    for z, (lat, lon, tier) in placed.items():
        t, lk, nw, rc = L["zips"][z]
        rows.append([z, round(lat, 3), round(lon, 3), t, lk, nw, rc])
        tiers[tier] += 1
        tier_cos[tier] += t
    rows.sort(key=lambda r: (-r[3], r[0]))
    zdoc = {"cols": ["zip", "lat", "lon", "total", "likely", "isNew", "rrc"], "rows": rows}
    unplaced = {z: v[0] for z, v in L["zips"].items() if z not in placed}

    out_c, dropped = {}, 0
    for code, (t, lk, nw) in L["codes"].items():
        f = code_to_fips.get(code)
        if f is None:
            dropped += t
        else:
            out_c[f] = {"total": t, "likely": lk, "isNew": nw}
    codoc = {"counties": dict(sorted(out_c.items()))}

    check("ZIP rows: unique 5-digit zips, valid ranges, counts consistent",
          len({r[0] for r in rows}) == len(rows) and all(
              re.fullmatch(r"\d{5}", r[0]) and LAT_RANGE[0] <= r[1] <= LAT_RANGE[1] and LON_RANGE[0] <= r[2] <= LON_RANGE[1]
              and r[3] >= 1 and r[4] <= r[3] and r[5] <= r[3] and r[6] <= r[3] for r in rows))
    check("every Texas row is in a ZIP row or the unplaced list",
          sum(r[3] for r in rows) + sum(unplaced.values()) + L["bad_zip"] == L["tx"],
          "%d placed + %d unplaced + %d bad ZIP vs %d" % (sum(r[3] for r in rows), sum(unplaced.values()),
                                                        L["bad_zip"], L["tx"]))
    check("county rows: FIPS exist, likely/isNew <= total, totals add up",
          all(f in counties and v["likely"] <= v["total"] and v["isNew"] <= v["total"] for f, v in out_c.items())
          and sum(v["total"] for v in out_c.values()) + dropped == L["tx"])

    # ---- sizes, then write
    blobs = {"counties.geo.json": serialize(cdoc), "county-labor.json": serialize(ldoc),
             "zip-companies.json": serialize(zdoc), "county-companies.json": serialize(codoc)}
    for n, b in blobs.items():
        check("%s size within budget" % n, len(b) <= BUDGET[n], "%d KB of %d KB" % (len(b) // 1000, BUDGET[n] // 1000))
    if FAILED:
        sys.exit("ERROR: %d check(s) failed, nothing written: %s" % (len(FAILED), "; ".join(FAILED)))
    os.makedirs(args.out, exist_ok=True)
    for n, b in blobs.items():
        write_bytes(args.out, n, b)
    for n in blobs:  # read back from disk and re-parse
        with open(os.path.join(args.out, n), "rb") as f:
            json.loads(f.read().decode("utf-8"))

    # ---- summary and spot checks (informational)
    log("== summary")
    for n, b in blobs.items():
        log("  %-22s %7d bytes (budget %d)" % (n, len(b), BUDGET[n]))
    log("  counties: %d features from %s" % (len(cdoc["features"]), label))
    log("  labor %d: counties with o = %d, with s = %d, with either = %d (of 254); QCEW private county rows 211/213 = %d/%d"
        % (lstats["year"], lstats["o"], lstats["s"],
           sum(1 for v in ldoc["counties"].values() if v["o"] or v["s"]), lstats["rows"]["211"], lstats["rows"]["213"]))
    log("  zip rows %d (tier1 ZCTA %d / tier2 city %d / tier3 county %d), companies in them %d of %d; unplaced %d zips, %d "
        "companies; strict=%s" % (len(rows), tiers[1], tiers[2], tiers[3], sum(r[3] for r in rows), L["tx"],
                                  len(unplaced), sum(unplaced.values()), args.strict_zip))
    log("  zip companies by tier: tier1 %d, tier2 %d, tier3 %d" % (tier_cos[1], tier_cos[2], tier_cos[3]))
    log("  unplaced ZIPs: %s" % (", ".join("%s(%d)" % kv for kv in sorted(unplaced.items())[:12]) or "none"))
    log("  largest fallback-placed ZIPs: " + ", ".join(
        "%s=%d@%.3f,%.3f" % (r[0], r[3], r[1], r[2]) for r in [r for r in rows if placed[r[0]][2] > 1][:6]))
    log("  county rows %d, companies in them %d; dropped (county_code 0 / unmapped) %d" %
        (len(out_c), sum(v["total"] for v in out_c.values()), dropped))
    ho = lambda r: HOUSTON_BOX[0] <= r[1] <= HOUSTON_BOX[1] and HOUSTON_BOX[2] <= r[2] <= HOUSTON_BOX[3]  # noqa: E731
    log("  top 10 ZIPs by companies: " + ", ".join("%s=%d%s" % (r[0], r[3], "H" if ho(r) else "") for r in rows[:10]) +
        "  (H = Houston-area box); Houston-box share of all placed companies %.1f%%, of the top 20 ZIPs %d/20" %
        (100.0 * sum(r[3] for r in rows if ho(r)) / max(sum(r[3] for r in rows), 1), sum(1 for r in rows[:20] if ho(r))))
    top = sorted(out_c.items(), key=lambda kv: -kv[1]["total"])[:6]
    log("  top counties by companies: " + ", ".join("%s %s=%d" % (f, name[f], v["total"]) for f, v in top))
    for f in ("329", "389", "135", "317", "301", "461"):
        v = ldoc["counties"][f]
        log("  labor %s %-8s o=%s s=%s" % (f, name[f], json.dumps(v["o"], separators=(",", ":")),
                                         json.dumps(v["s"], separators=(",", ":"))))
    for i, tag in (("211", "o"), ("213", "s")):
        st = lstats["state"][i]
        if st:
            disclosed = sum(v[tag]["emp"] for v in ldoc["counties"].values() if v[tag])
            log("  Texas statewide %s: %s estabs, %s employees; disclosed counties hold %d (%.0f%%)" %
                (tag, st["annual_avg_estabs"], st["annual_avg_emplvl"], disclosed,
                 100.0 * disclosed / max(int(float(st["annual_avg_emplvl"])), 1)))
    log("done: all hard checks passed")


if __name__ == "__main__":
    main()
