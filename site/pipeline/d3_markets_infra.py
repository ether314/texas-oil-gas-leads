#!/usr/bin/env python3
"""D3 producer: site/public/data/series-markets.json and site/public/data/infra.json.

Public federal data only, no API keys, Python standard library only.  Run:

    python3 -I site/pipeline/d3_markets_infra.py [--as-of YYYY-MM-DD] [--dl-root DIR] [--out DIR] [--only markets|infra]

Raw downloads go to <dl-root>/<name>/<file>, every file in its own new empty folder (a -N suffix is added on re-runs).
They are untrusted data: parsed with json / html.parser / zipfile+ElementTree, never executed.

series-markets.json  (EIA public data pages; FRED could not be reached from the build host)
    WTI spot ($/bbl, RWTC), Henry Hub spot ($/MMBtu, RNGWHHD), Texas field crude production (thousand bbl/month,
    MCRFPTX1; the *2 series is per DAY), months 2019-01 .. last complete month before --as-of, null where missing.

infra.json  (EIA's Energy Atlas ArcGIS layers now answer "Token Required", so other public federal files are combined)
    refinery : EIA-820 Refinery Capacity Report (operable atmospheric distillation, bbl/calendar day) for the list and
               capacity; coordinates from the EPA GHGRP facility table, EIA Atlas layer (NACEI mirror) as fallback.
    gasplant : EPA GHGRP Subpart W onshore natural gas processing facilities (industry type W-PROC); no current keyless
               plant-level capacity exists (EIA-757 plant capacities stop at 2017), so cap is null.
    lng      : EIA U.S. Liquefaction Capacity File (latest quarter), in-service baseload capacity (Bcf/d); coordinates
               from GHGRP, EIA Atlas LNG layer (NACEI mirror) as fallback.
"""
import argparse
import datetime
import html.parser
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

CONTRACT_AS_OF = "2026-10-29"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(SITE, "public", "data")
DEFAULT_DL = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))
UA = "Mozilla/5.0 (research script)"
TX_LAT = (25.5, 36.6)
TX_LON = (-106.8, -93.4)
MARKET_START = (2019, 1)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

EIA_SERIES = {
    "wti": dict(name="eia_wti_monthly", sid="RWTC", fred="WTISPLC",
                url="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=M",
                must=("WTI Spot Price", "Dollars per Barrel"), never=(), lo=0.0, hi=400.0,
                label="EIA, Cushing OK WTI spot price FOB, monthly average, USD per barrel"),
    "henryHub": dict(name="eia_henryhub_monthly", sid="RNGWHHD", fred="MHHNGSP",
                     url="https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm",
                     must=("Henry Hub", "Dollars per Million Btu"), never=(), lo=0.0, hi=100.0,
                     label="EIA, Henry Hub natural gas spot price, monthly average, USD per MMBtu"),
    "txCrude": dict(name="eia_txcrude_monthly", sid="MCRFPTX1", fred=None,
                    url="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=MCRFPTX1&f=M",
                    must=("Texas Field Production of Crude Oil", "Thousand Barrels"), never=("per Day",),
                    lo=50000.0, hi=400000.0,
                    label="EIA, Texas field production of crude oil, thousand barrels per month"),
}
UNITS = {"wti": "USD per barrel", "henryHub": "USD per MMBtu", "txCrude": "thousand barrels per month"}

REFCAP_PAGE = "https://www.eia.gov/petroleum/refinerycapacity/"
NG_DATA_PAGE = "https://www.eia.gov/naturalgas/data.php"
GHG_BASE = "https://data.epa.gov/efservice/PUB_DIM_FACILITY/STATE/TX/YEAR/%d/"
NACEI = "https://geoappext.nrcan.gc.ca/arcgis/rest/services/NACEI/energy_infrastructure_of_north_america_en/MapServer"


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- downloads (untrusted data, parse only)

def new_dir(root, name):
    """A new, empty folder <root>/<name> (or <name>-N when it already exists)."""
    os.makedirs(root, exist_ok=True)
    n = 0
    while True:
        path = os.path.join(root, name if n == 0 else "%s-%d" % (name, n))
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            n += 1


def http_get(url, params=None, retries=3, timeout=120, max_mb=32):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise RuntimeError("HTTP %s" % r.status)
                data = r.read(max_mb * 1024 * 1024 + 1)
            if len(data) > max_mb * 1024 * 1024:
                raise RuntimeError("response larger than %d MB" % max_mb)
            if not data:
                raise RuntimeError("empty body")
            return data
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
            time.sleep(2 * attempt)
    raise SystemExit("download failed: %s (%s)" % (url, last))


def fetch(root, name, filename, url, params=None):
    """Download one file into its own new folder; returns the path."""
    data = http_get(url, params)
    path = os.path.join(new_dir(root, name), filename)
    with open(path, "wb") as f:
        f.write(data)
    log("  downloaded %-26s %9d bytes  %s" % (name, len(data), url.split("?")[0][:90]))
    return path


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, doc):
    """Compact UTF-8 JSON, written atomically."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return os.path.getsize(path)


# ---------------------------------------------------------------- markets

class EiaPage(html.parser.HTMLParser):
    """Collects <title>, the cell texts of every <tr>, and all page text (for the release date)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.rows = []
        self.text = []
        self._row = None
        self._cell = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell).replace("\xa0", " ")).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._cell is not None:
            self._cell.append(data)
        self.text.append(data)


def to_number(cell):
    try:
        return float(cell.replace(",", "").strip())
    except ValueError:
        return None  # "", "NA", "--", "W", ...


def parse_eia_monthly(path, spec):
    page = EiaPage()
    page.feed(read_text(path))
    title = re.sub(r"\s+", " ", page.title).strip()
    for needle in spec["must"]:
        if needle not in title:
            raise SystemExit("%s: unexpected series title %r (missing %r)" % (spec["sid"], title, needle))
    for needle in spec["never"]:
        if needle in title:
            raise SystemExit("%s: unexpected series title %r (contains %r)" % (spec["sid"], title, needle))
    values, header_seen = {}, False
    for row in page.rows:
        if len(row) >= 13 and [c[:3] for c in row[1:13]] == MONTHS:
            header_seen = True
            continue
        if len(row) >= 2 and re.fullmatch(r"\d{4}", row[0]):
            for m, cell in enumerate(row[1:13], start=1):
                values[(int(row[0]), m)] = to_number(cell)
    if not header_seen or not values:
        raise SystemExit("%s: monthly table not found in the page" % spec["sid"])
    text = " ".join(page.text)
    rel = re.search(r"(?<!Next )Release Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    release = "%s-%02d-%02d" % (rel.group(3), int(rel.group(1)), int(rel.group(2))) if rel else None
    return title, values, release


def month_range(start, end):
    y, m = start
    out = []
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def last_complete_month(as_of):
    return (as_of.year - 1, 12) if as_of.month == 1 else (as_of.year, as_of.month - 1)


def build_markets(dl_root, as_of):
    log("markets: EIA monthly spot prices and Texas crude production")
    months = month_range(MARKET_START, last_complete_month(as_of))
    doc = {"months": ["%04d-%02d" % ym for ym in months]}
    src = {}
    for key in ("wti", "henryHub", "txCrude"):
        spec = EIA_SERIES[key]
        path = fetch(dl_root, spec["name"], "page.html", spec["url"])
        title, values, release = parse_eia_monthly(path, spec)
        series = []
        for ym in months:
            v = values.get(ym)
            if v is not None and not (spec["lo"] < v < spec["hi"]):
                raise SystemExit("%s %04d-%02d value %s outside %s..%s (wrong series or units?)"
                                 % (spec["sid"], ym[0], ym[1], v, spec["lo"], spec["hi"]))
            series.append(int(v) if v is not None and v == int(v) and key == "txCrude" else v)
        doc[key] = series
        have = [i for i, v in enumerate(series) if v is not None]
        last = doc["months"][have[-1]] if have else None
        fred = (" FRED %s is EIA-sourced but fred.stlouisfed.org was unreachable from the build host." % spec["fred"]
                if spec["fred"] else "")
        src[key] = "%s (series %s, %s), EIA release %s; latest month with data %s.%s" % (
            spec["label"], spec["sid"], spec["url"], release or "date n/a", last, fred)
        if key == "txCrude":
            src[key] += " MCRFPTX2 is the per-day series (about 5,800 thousand bbl/day), not used."
    doc["units"] = UNITS
    doc["src"] = src
    return doc


def validate_markets(doc):
    n = len(doc["months"])
    assert doc["months"][0] == "2019-01" and n >= 93, "months range"
    assert list(doc.keys()) == ["months", "wti", "henryHub", "txCrude", "units", "src"], "key order"
    for key in ("wti", "henryHub", "txCrude"):
        assert len(doc[key]) == n, key + " length"
        assert all(v is None or isinstance(v, (int, float)) for v in doc[key]), key + " types"
        assert any(v is not None for v in doc[key]), key + " all null"
    assert set(doc["units"]) == set(doc["src"]) == {"wti", "henryHub", "txCrude"}


# ---------------------------------------------------------------- xlsx (zip + XML, parse only)

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(path):
    """{sheet name: [row lists]}; strings and numbers come back as text."""
    z = zipfile.ZipFile(path)
    for info in z.infolist():
        if info.file_size > 64 * 1024 * 1024:
            raise SystemExit("xlsx member too large: %s" % info.filename)
    sst = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_M + "si"):
            sst.append("".join(t.text or "" for t in si.iter(_M + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sheet in wb.iter(_M + "sheet"):
        target = rels[sheet.get(_R + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter(_M + "row"):
            cells = {}
            for c in row.findall(_M + "c"):
                t, v = c.get("t"), c.find(_M + "v")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_M + "t"))
                elif v is None:
                    continue
                elif t == "s":
                    val = sst[int(v.text)]
                else:
                    val = v.text
                cells[_col(c.get("r"))] = val
            if cells:
                rows.append([cells.get(i) for i in range(max(cells) + 1)])
        out[sheet.get("name")] = rows
    return out


# ---------------------------------------------------------------- text helpers

STOP = set("""INC LLC LP LTD CO CORP CORPORATION COMPANY THE OF AND LIMITED PARTNERSHIP PARTNERS REFINING REFINERY REFG
PLANT PROCESSING SUPPLY MARKETING ENERGY ENTERPRISES RESOURCES PETROLEUM PETROCHEM PETROCHEMICAL PETROCHEMICALS
CHEMICAL CHEMICALS USA US AMERICA HOLDINGS GROUP INDUSTRIES SYSTEM SYSTEMS TEXAS TX FACILITY UNIT SITE INCORPORATED
SERVICES OIL PRODUCTS CRUDE CONDENSATE SPLITTER""".split())
BRAND_STOP = STOP - {"TEXAS"} | {"CRUDE"}
LNG_STOP = set("LNG LIQUEFACTION TERMINAL TERMINALS IMPORT EXPORT PROJECT PHASE STAGE MIDSCALE INC LLC LP CO CORP THE OF "
               "AND FACILITY PLANT".split())
UPPER_KEEP = set("""LP LLC LLP USA US II III IV LNG NGL TX CO2 WRB CITGO PDV ETC DCP XTO OXY HF BP EOG GP CGP NGTC SCM TGG
M6 MPLX IACX NHIP BKV""".split())
SPECIAL = {"EXXONMOBIL": "ExxonMobil", "TOTALENERGIES": "TotalEnergies", "ENLINK": "EnLink", "ONEOK": "ONEOK",
           "LTD": "Ltd", "INC": "Inc", "CORP": "Corp", "CO": "Co", "NUSTAR": "NuStar"}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", (s or "").upper())).strip()


def toks(s, stop=STOP):
    return {w for w in norm(s).split() if w not in stop and (len(w) > 1 or w.isdigit())}


def _fix_word(word):
    m = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", word)
    pre, core, post = m.group(1), m.group(2), m.group(3)
    if core in SPECIAL:
        core = SPECIAL[core]
    elif core in UPPER_KEEP or re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?", core):
        pass
    elif re.fullmatch(r"[A-Z]{1,4}", core) and not re.search(r"[AEIOUY]", core):
        pass
    elif re.search(r"\d", core):
        pass
    else:
        core = "-".join(p.capitalize() for p in core.split("-"))
    return pre + core + post


def pretty(s):
    """Title-case an ALL-CAPS name (acronyms and legal suffixes kept); mixed-case names are left alone."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    letters = [ch for ch in s if ch.isalpha()]
    if not letters or sum(ch.isupper() for ch in letters) / len(letters) < 0.8:
        return s
    return " ".join(_fix_word(w) for w in s.split(" "))


def top_owner(parent):
    """'TARGA RESOURCES CORP (73%); PIONEER NATURAL RESOURCES CO (27%)' -> the largest owner, share stripped."""
    best = None
    for part in (parent or "").split(";"):
        m = re.match(r"^\s*(.*?)\s*\(\s*([\d.]*)\s*%\s*\)\s*$", part)
        name, pct = (m.group(1), float(m.group(2) or 0)) if m else (part.strip(), 0.0)
        if name and (best is None or pct > best[1]):
            best = (name, pct)
    return best[0] if best else ""


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def in_texas(lat, lon):
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and TX_LAT[0] <= lat <= TX_LAT[1] and TX_LON[0] <= lon <= TX_LON[1])


# ---------------------------------------------------------------- infra sources

def eia_refineries(dl_root):
    page = read_text(fetch(dl_root, "eia_refcap_page", "index.html", REFCAP_PAGE))
    found = re.findall(r'href="([^"]*refcap(\d\d)\.xlsx)"', page)
    if not found:
        raise SystemExit("EIA refinery capacity workbook link not found")
    href, yy = max(found, key=lambda t: int(t[1]))
    url = urllib.parse.urljoin(REFCAP_PAGE, href)
    path = fetch(dl_root, "eia_refcap_xlsx", "refcap%s.xlsx" % yy, url)
    rows = next(iter(read_xlsx(path).values()))
    hdr = [(h or "").strip().upper() for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}
    for need in ("COMPANY_NAME", "CORPORATION", "STATE_NAME", "SITE", "PRODUCT", "SUPPLY", "QUANTITY", "PERIOD"):
        if need not in ix:
            raise SystemExit("refinery workbook column missing: " + need)
    sites = {}
    for r in rows[1:]:
        r = r + [None] * (len(hdr) - len(r))
        if r[ix["STATE_NAME"]] != "Texas" or r[ix["PRODUCT"]] != "TOTAL OPERABLE CAPACITY":
            continue
        if not re.search(r"atmospheric crude distillation.*calendar day", r[ix["SUPPLY"]] or "", re.I):
            continue
        cap = int(round(float(r[ix["QUANTITY"]])))
        if cap > 0:
            sites[(r[ix["COMPANY_NAME"]], r[ix["SITE"]])] = dict(
                company=r[ix["COMPANY_NAME"]], corp=r[ix["CORPORATION"]] or "", site=r[ix["SITE"]], cap=cap)
    year = 2000 + int(yy)
    return list(sites.values()), "refcap%s.xlsx" % yy, "%d-01-01" % year


def ghg_facilities(dl_root, as_of):
    year = None
    for y in range(as_of.year, as_of.year - 6, -1):
        body = json.loads(http_get(GHG_BASE % y + "count/JSON").decode("utf-8"))
        if body and body[0].get("TOTALQUERYRESULTS", 0) > 0:
            year = y
            break
    if year is None:
        raise SystemExit("no GHGRP year with Texas facilities")
    rows = read_json(fetch(dl_root, "epa_ghgrp_tx_%d" % year, "facilities.json", GHG_BASE % year + "JSON"))
    out = []
    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        fips = str(r.get("county_fips") or "")
        if r.get("state") != "TX" or not in_texas(lat, lon) or (fips and not fips.startswith("48")):
            continue  # some records carry a TX state but an out-of-state county or location
        types = {t.strip() for t in (r.get("reported_industry_types") or "").split(",")}
        out.append(dict(id=r["facility_id"], name=(r.get("facility_name") or "").strip(), city=r.get("city") or "",
                        parent=r.get("parent_company") or "", types=types, naics=r.get("naics_code") or "",
                        lat=float(lat), lon=float(lon)))
    return out, year


def nacei_texas(dl_root, layer, fields, name):
    params = {"where": "StateProv='Texas'", "outFields": ",".join(fields), "returnGeometry": "false", "f": "json"}
    try:
        d = read_json(fetch(dl_root, name, "layer.json", "%s/%d/query" % (NACEI, layer), params))
    except SystemExit as exc:
        log("  WARN NACEI layer %d unavailable (%s); continuing without it" % (layer, exc))
        return []
    if "error" in d or d.get("exceededTransferLimit"):
        log("  WARN NACEI layer %d returned an error or a partial page; ignoring it" % layer)
        return []
    return [f["attributes"] for f in d.get("features", [])]


def eia_liquefaction(dl_root):
    page = read_text(fetch(dl_root, "eia_ng_data_page", "data.html", NG_DATA_PAGE))
    pat = r'href="(/naturalgas/importsexports/liquefactioncapacity/U\.S\.liquefactioncapacity_(\d{4})_(?:Q(\d)|(\d)Q)\.xlsx)"'
    found = re.findall(pat, page)
    if not found:
        raise SystemExit("EIA liquefaction capacity workbook link not found")
    href, yr, q1, q2 = max(found, key=lambda t: (int(t[1]), int(t[2] or t[3])))
    label = re.search(re.escape(href) + r'"[^>]*>\s*([^<]*?)\s*<', page)
    label = label.group(1) if label else "%s Q%s" % (yr, q1 or q2)
    path = fetch(dl_root, "eia_liquefaction_xlsx", "liquefaction.xlsx", urllib.parse.urljoin(NG_DATA_PAGE, href))
    sheets = read_xlsx(path)
    name = next(n for n in sheets if n.lower().startswith("existing"))
    rows = sheets[name]
    h = next(i for i, r in enumerate(rows) if r and (r[0] or "").strip().lower().startswith("project name"))
    hdr = [re.sub(r"\s+", " ", (c or "")).strip().lower() for c in rows[h]]

    def col(prefix):
        return next(i for i, c in enumerate(hdr) if c.startswith(prefix))

    c_base, c_stat, c_loc, c_op = col("baseload nameplate"), col("project status"), col("location"), col("operator")
    sites, proj = {}, None
    for r in rows[h + 2:]:
        r = r + [None] * (len(hdr) - len(r))
        if r[0]:
            proj = r[0].strip()
        loc = (r[c_loc] or "").strip().upper()
        if loc not in ("TX", "TEXAS") or not proj:
            continue
        site = re.sub(r"\s+Liquefaction(\s+(Stage\s+\d+|Midscale))?$", "",
                      re.sub(r"\s+(Phase|Stage)\s+\w+$", "", proj, flags=re.I), flags=re.I)
        m = re.match(r"\s*([\d.]+)", r[c_base] or "")
        status = (r[c_stat] or "").lower()
        in_service = any(k in status for k in ("commercial operation", "commissioning", "operating"))
        s = sites.setdefault(site, dict(site=site, company="", cap=0.0))
        if in_service and m:
            s["cap"] += float(m.group(1))
            s["company"] = s["company"] or (r[c_op] or "").strip()
    items = [dict(site=s["site"], company=s["company"], cap=round(s["cap"], 2)) for s in sites.values() if s["cap"] > 0]
    return items, label


# ---------------------------------------------------------------- matching sources to the EIA lists

def pick(site_core, site_full, brand, cands, used, only_site_here, prefer=None):
    """Best candidate for an EIA site: same city (or site name inside the facility name) and shared brand words.

    Ties on (shared words, Subpart Y reporter) go to the candidate nearest `prefer` (a lat/lon from another source)
    when given, else to the one with the shortest name, then the lowest id.
    """
    here = []
    for c in cands:
        if c["key"] in used:
            continue
        name_n, city_n = " %s " % norm(c["name"]), norm(c["city"])
        if city_n == site_core or (" %s " % site_core) in name_n or (" %s " % site_full) in name_n:
            here.append(c)
    scored = []
    for c in here:
        score = len(brand & (toks(c["name"]) | toks(c["parent"])))
        scored.append((score, 1 if c.get("isy") else 0, -len(toks(c["name"])), -c["order"], c))
    if not scored:
        return None
    top = max(t[:2] for t in scored)
    tied = [t for t in scored if t[:2] == top]
    if prefer and len(tied) > 1:
        best = min(tied, key=lambda t: km((t[4]["lat"], t[4]["lon"]), prefer))
    else:
        best = max(tied, key=lambda t: t[2:4])
    if best[0] >= 1 or (only_site_here and len(here) == 1):
        return best[4]
    return None


def site_core(site):
    """EIA site label without a trailing compass word: 'CORPUS CHRISTI EAST' -> 'CORPUS CHRISTI'."""
    return re.sub(r"\s+(EAST|WEST|NORTH|SOUTH)$", "", norm(site))


def refinery_coords(eia_sites, ghg, nacei_rows):
    g_cands = [dict(key=("g", f["id"]), name=f["name"], city=f["city"], parent=f["parent"], lat=f["lat"], lon=f["lon"],
                    isy=("Y" in f["types"]), order=f["id"])
               for f in ghg if "Y" in f["types"] or f["naics"] == "324110"]
    n_cands = [dict(key=("n", i), name=a.get("Owner") or "", city=a.get("City") or "", parent=a.get("Owner") or "",
                    lat=a["Latitude"], lon=a["Longitude"], isy=False, order=i)
               for i, a in enumerate(nacei_rows) if in_texas(a.get("Latitude"), a.get("Longitude"))]
    per_city = {}
    for s in eia_sites:
        per_city[site_core(s["site"])] = per_city.get(site_core(s["site"]), 0) + 1
    used_g, used_n, out, notes = set(), set(), {}, []
    for s in sorted(eia_sites, key=lambda s: -s["cap"]):
        full = norm(s["site"])
        core = site_core(s["site"])
        brand = toks(s["company"]) | toks(s["corp"]) | ({full.split()[-1]} if core != full else set())
        solo = per_city[core] == 1
        n = pick(core, full, brand, n_cands, used_n, solo)
        g = pick(core, full, brand, g_cands, used_g, solo, prefer=(n["lat"], n["lon"]) if n else None)
        if g:
            used_g.add(g["key"])
        if n:
            used_n.add(n["key"])
        chosen = g or n
        if not chosen:
            notes.append("UNMATCHED refinery (no coordinates, skipped): %s / %s" % (s["company"], s["site"]))
            continue
        out[(s["company"], s["site"])] = (chosen["lat"], chosen["lon"], "GHGRP" if g else "EIA Atlas (NACEI)")
        if g and n and km((g["lat"], g["lon"]), (n["lat"], n["lon"])) > 6:
            notes.append("coordinate sources differ by %.1f km for %s / %s (GHGRP kept)"
                         % (km((g["lat"], g["lon"]), (n["lat"], n["lon"])), s["company"], s["site"]))
    return out, notes


def brand_label(company, site):
    words = norm(company).split()
    head = []
    for w in words:
        if w in BRAND_STOP:
            break
        head.append(w)
    if not head:
        head = [w for w in words if w not in BRAND_STOP]
    site_words = set(norm(site).split())
    if not head or set(head) <= site_words:
        return ""
    return pretty(" ".join(head))


def build_refineries(dl_root, ghg, nacei_ref):
    eia, workbook, as_of = eia_refineries(dl_root)
    coords, notes = refinery_coords(eia, ghg, nacei_ref)
    per_city = {}
    for s in eia:
        per_city[site_core(s["site"])] = per_city.get(site_core(s["site"]), 0) + 1
    items = []
    for s in sorted(eia, key=lambda s: -s["cap"]):
        if (s["company"], s["site"]) not in coords:
            continue
        lat, lon, _src = coords[(s["company"], s["site"])]
        name = pretty(s["site"]) + " refinery"
        brand = brand_label(s["company"], s["site"]) if per_city[site_core(s["site"])] > 1 else ""
        items.append({"n": "%s (%s)" % (name, brand) if brand else name, "c": pretty(s["company"]),
                      "lat": round(lat, 4), "lon": round(lon, 4), "cap": s["cap"]})
    via = {}
    for v in coords.values():
        via[v[2]] = via.get(v[2], 0) + 1
    return items, workbook, as_of, notes, via, len(eia)


def build_gas_plants(ghg):
    items, seen = [], set()
    for f in ghg:
        if "W-PROC" not in f["types"]:
            continue
        name = pretty(f["name"])
        key = (norm(name), round(f["lat"], 4), round(f["lon"], 4))
        if not name or key in seen:
            continue
        seen.add(key)
        items.append({"n": name, "c": pretty(top_owner(f["parent"])), "lat": round(f["lat"], 4),
                      "lon": round(f["lon"], 4), "cap": None})
    items.sort(key=lambda i: (i["n"].lower(), i["lat"], i["lon"]))
    return items


def build_lng(dl_root, ghg, nacei_lng):
    sites, label = eia_liquefaction(dl_root)
    g_cands = [dict(name=f["name"], city=f["city"], lat=f["lat"], lon=f["lon"])
               for f in ghg if "W-LNGIE" in f["types"] or "W-LNGSTO" in f["types"]]
    n_cands = [dict(name=a.get("Facility") or "", city=a.get("City") or "", lat=a["Latitude"], lon=a["Longitude"])
               for a in nacei_lng if in_texas(a.get("Latitude"), a.get("Longitude"))]
    items, notes = [], []
    for s in sorted(sites, key=lambda s: -s["cap"]):
        need = toks(s["site"], LNG_STOP)
        hit, via = None, ""
        for pool, tag in ((g_cands, "GHGRP"), (n_cands, "EIA Atlas (NACEI)")):
            for c in pool:
                if need and need <= (toks(c["name"], LNG_STOP) | toks(c["city"], LNG_STOP)):
                    hit, via = c, tag
                    break
            if hit:
                break
        if not hit:
            notes.append("UNMATCHED LNG terminal (no coordinates, skipped): %s" % s["site"])
            continue
        name = s["site"] if "LNG" in s["site"].upper() else s["site"] + " LNG"
        items.append({"n": name, "c": s["company"], "lat": round(hit["lat"], 4), "lon": round(hit["lon"], 4),
                      "cap": s["cap"]})
        notes.append("%s coordinates from %s" % (name, via))
    return items, label, notes


def validate_infra(doc):
    assert list(doc.keys()) == ["asOf", "src", "layers"]
    assert [l["id"] for l in doc["layers"]] == ["refinery", "gasplant", "lng"]
    bad = re.compile(r"@|https?://|\b\d{3}[-.)\s]+\d{3}[-.\s]+\d{4}\b")
    for layer in doc["layers"]:
        assert set(layer.keys()) == {"id", "label", "unit", "items"}
        seen = set()
        for it in layer["items"]:
            assert list(it.keys()) == ["n", "c", "lat", "lon", "cap"], it
            assert it["n"] and isinstance(it["n"], str) and isinstance(it["c"], str), it
            assert in_texas(it["lat"], it["lon"]), it
            assert it["cap"] is None or (isinstance(it["cap"], (int, float)) and it["cap"] > 0), it
            assert not bad.search(it["n"] + " " + it["c"]), "contact-like text in " + repr(it)
            key = (it["n"], it["lat"], it["lon"])
            assert key not in seen, "duplicate " + repr(key)
            seen.add(key)


def build_infra(dl_root, as_of):
    log("infra: refineries, gas processing plants, LNG terminals")
    ghg, ghg_year = ghg_facilities(dl_root, as_of)
    nacei_ref = nacei_texas(dl_root, 10, ["Facility", "Owner", "City", "Latitude", "Longitude", "StateProv", "Period"],
                            "nrcan_nacei_refineries_tx")
    nacei_lng = nacei_texas(dl_root, 5, ["Facility", "Owner", "City", "Latitude", "Longitude", "StateProv", "Period"],
                            "nrcan_nacei_lng_tx")
    refineries, workbook, ref_date, ref_notes, via, n_eia = build_refineries(dl_root, ghg, nacei_ref)
    plants = build_gas_plants(ghg)
    lng, lng_label, lng_notes = build_lng(dl_root, ghg, nacei_lng)
    for line in ref_notes + lng_notes:
        log("  note: " + line)
    log("  refineries: %d of %d EIA sites placed (coordinates via %s)" % (len(refineries), n_eia, via))
    src = ("Refineries: EIA Refinery Capacity Report (%s), operable atmospheric crude distillation capacity per "
           "calendar day at %s; coordinates from the EPA GHGRP facility table (reporting year %d), EIA Atlas layer "
           "(NACEI mirror) for sites GHGRP lacks. Gas processing plants: EPA GHGRP reporting year %d, Subpart W "
           "onshore natural gas processing facilities; capacity is null because no current keyless plant-level "
           "capacity exists. LNG terminals: EIA U.S. Liquefaction Capacity File, %s, baseload nameplate capacity of "
           "trains in service (commercial operation or commissioning); coordinates from GHGRP and the EIA Atlas LNG "
           "layer (NACEI mirror). EIA Energy Atlas ArcGIS services answer Token Required and were not used."
           % (workbook, ref_date, ghg_year, ghg_year, lng_label))
    doc = {"asOf": as_of.isoformat(), "src": src, "layers": [
        {"id": "refinery", "label": "Refineries", "unit": "bbl/day", "items": refineries},
        {"id": "gasplant", "label": "Gas processing plants", "unit": "MMcf/day", "items": plants},
        {"id": "lng", "label": "LNG terminals", "unit": "Bcf/day", "items": lng}]}
    validate_infra(doc)
    return doc


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--as-of", default=CONTRACT_AS_OF, help="as-of date (default: the contract date %s)" % CONTRACT_AS_OF)
    ap.add_argument("--dl-root", default=os.environ.get("D3_DL_ROOT", DEFAULT_DL))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--only", choices=("markets", "infra"))
    args = ap.parse_args()
    as_of = datetime.date.fromisoformat(args.as_of)
    os.makedirs(args.out, exist_ok=True)
    if args.only in (None, "markets"):
        doc = build_markets(args.dl_root, as_of)
        validate_markets(doc)
        size = write_json(os.path.join(args.out, "series-markets.json"), doc)
        log("wrote series-markets.json (%d bytes), %d months" % (size, len(doc["months"])))
    if args.only in (None, "infra"):
        doc = build_infra(args.dl_root, as_of)
        size = write_json(os.path.join(args.out, "infra.json"), doc)
        log("wrote infra.json (%d bytes): %s" % (size, ", ".join(
            "%s=%d" % (l["id"], len(l["items"])) for l in doc["layers"])))


if __name__ == "__main__":
    sys.exit(main())
