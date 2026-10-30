#!/usr/bin/env python3
"""D5 producer: county-business.json, series-jobs.json and series-outlook.json (site/public/data).

Public federal data only (no keys, no registration), Python standard library only.  Run:

    python3 -I site/pipeline/d5_federal.py [--only cbp|jobs|outlook] [--as-of YYYY-MM-DD] [--dl-root DIR] [--out DIR]
                                           [--reuse] [--fetch-only]

Raw downloads go to <dl-root>/<name>/<file>, every file in its own new empty folder (a -N suffix is added on re-runs).
With --reuse the newest earlier copy of each file is parsed instead of downloading again (handy while developing, and it
spares the BLS API its small daily allowance).  Downloads are untrusted data: parsed with csv, json, zipfile and
ElementTree, never executed.  One request per second at most, generic User-Agent, no e-mail address anywhere.
Each document is validated before it replaces a file; afterwards the files are re-read and cross-checked (see NOTES_D5.md).

county-business.json  Census County Business Patterns: the bulk county file cbpYYco.zip of the newest vintage that exists
                      (tries the as-of year downwards to 2023; 2024 is not published yet), Texas rows (FIPS state 48)
                      for six NAICS codes.  Size-class cells with fewer than 3 establishments are printed as N by the
                      Census and become 0; county code 999 (county not identified) goes to "unassigned".
series-jobs.json      BLS State and Area Employment (CES), Texas, all employees, NAICS 211 and 213, public API v1
                      (series SMU48000001021100001 and SMU48000001021300001, not seasonally adjusted: no SA series).
series-outlook.json   EIA Short-Term Energy Outlook, public data workbook STEO_m.xlsx, Table 1 (sheet 1tab): WTI, Henry
                      Hub, U.S. crude oil and dry gas production; 12 months of history then the forecast horizon.
Cross-check inputs (read only): county-labor.json, counties.geo.json and series-markets.json from the other producers, and
the Texas rows of the BLS QCEW industry files 211.csv and 213.csv (the keyless files behind county-labor.json).
"""
import argparse
import csv
import datetime
import io
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

CONTRACT_AS_OF = "2026-10-30"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(SITE, "public", "data")
DEFAULT_DL = os.environ.get("D5_DL_ROOT") or (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))
UA = "Mozilla/5.0 (research script)"
PAUSE = 1.0  # seconds between HTTP requests
MAX_BYTES = 400 * 1024  # size budget per file (DATA_CONTRACT_V3 rule 4)

CBP_BASE = "https://www2.census.gov/programs-surveys/cbp/datasets/%d/cbp%02dco.zip"
CBP_FIRST_YEAR = 2023
UNASSIGNED_FIPS = "999"  # CBP county code for establishments whose county is not identified
CBP_CODES = {
    "211": "Oil and gas extraction",
    "213": "Support activities for mining",
    "237120": "Oil and gas pipeline construction",
    "486": "Pipeline transportation",
    "4247": "Petroleum merchant wholesalers",
    "333132": "Oil and gas field machinery manufacturing",
}
SIZE_CLASSES = ["1-4", "5-9", "10-19", "20-49", "50-99", "100-249", "250-499", "500-999", "1000+"]
# column names of the nine size classes in the county file (the first one was called n<5 before 2017)
SIZE_COLS = [("n1_4", "n<5"), ("n5_9",), ("n10_19",), ("n20_49",), ("n50_99",), ("n100_249",), ("n250_499",),
             ("n500_999",), ("n1000",)]

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_FIRST_YEAR = 2019
BLS_MAX_YEARS = 10  # API v1: ten years per query
# State and Area Employment (SM) series id: SM + U|S (not|seasonally adjusted) + state 48 + area 00000 +
# supersector/industry 8 digits + data type 01 (all employees, thousands)
BLS_IDS = {
    "oilGas": "48000001021100001",    # 10211000 = NAICS 211 Oil and gas extraction
    "support": "48000001021300001",   # 10213000 = NAICS 213 Support activities for mining
    "mining": "48000001000000001",    # 10000000 = Mining and logging (context only)
}

STEO_URL = "https://www.eia.gov/outlooks/steo/xls/STEO_m.xlsx"


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


def newest_copy(root, name, filename):
    """Path of the newest earlier download <root>/<name>[-N]/<filename>, or None."""
    best, best_n = None, -1
    try:
        entries = os.listdir(root)
    except OSError:
        return None
    for e in entries:
        m = re.fullmatch(re.escape(name) + r"(?:-(\d+))?", e)
        if not m:
            continue
        p = os.path.join(root, e, filename)
        n = int(m.group(1) or 0)
        if os.path.isfile(p) and os.path.getsize(p) > 0 and n > best_n:
            best, best_n = p, n
    return best


_last_request = [0.0]


def http(url, data=None, headers=None, method=None, timeout=180, retries=3, max_mb=64):
    """One polite HTTP request; returns (status, headers, body).  404 and friends raise HTTPError at once."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    last = None
    for attempt in range(1, retries + 1):
        wait = PAUSE - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, rh = r.status, dict(r.headers)
                body = b"" if method == "HEAD" else r.read(max_mb * 1024 * 1024 + 1)
            if len(body) > max_mb * 1024 * 1024:
                raise RuntimeError("response larger than %d MB" % max_mb)
            return status, rh, body
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 404, 410):
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001 - report and retry
            last = exc
        time.sleep(2 * attempt + random.random())
    raise SystemExit("request failed: %s (%s)" % (url, last))


def fetch(dl_root, name, filename, url, reuse=False, data=None, headers=None, check=None):
    """Download one file into its own new folder (or reuse the newest copy); returns the path."""
    if reuse:
        p = newest_copy(dl_root, name, filename)
        if p:
            log("  reusing  %-24s %10d bytes  %s" % (name, os.path.getsize(p), os.path.relpath(p, dl_root)))
            return p
    status, _, body = http(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    if not body:
        raise SystemExit("empty body from %s" % url)
    if check and not check(body):
        raise SystemExit("unexpected content from %s: %r" % (url, body[:200]))
    path = os.path.join(new_dir(dl_root, name), filename)
    with open(path, "wb") as f:
        f.write(body)
    log("  fetched  %-24s %10d bytes  %s" % (name, len(body), url))
    return path


def is_zip(body):
    return body.startswith(b"PK\x03\x04")


def write_json(path, doc, max_bytes=None):
    """Compact UTF-8 JSON, written atomically; returns the size in bytes."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(tmp)
    if max_bytes is not None and size > max_bytes:
        os.remove(tmp)
        raise SystemExit("%s would be %d bytes, over the %d byte budget" % (os.path.basename(path), size, max_bytes))
    os.replace(tmp, path)
    return size


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- Census County Business Patterns

def fetch_cbp(dl_root, as_of, reuse):
    """The newest bulk county file that exists (2023 or newer); returns (year, zip path, url)."""
    years = list(range(as_of.year, CBP_FIRST_YEAR - 1, -1))
    if reuse:
        for y in years:
            p = newest_copy(dl_root, "cbp%02dco" % (y % 100), "cbp%02dco.zip" % (y % 100))
            if p:
                log("  reusing  %-24s %10d bytes  %s" % ("cbp%02dco" % (y % 100), os.path.getsize(p), os.path.relpath(p, dl_root)))
                return y, p, CBP_BASE % (y, y % 100)
    for y in years:
        url = CBP_BASE % (y, y % 100)
        try:
            http(url, method="HEAD")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                log("  CBP %d county file not published (404): %s" % (y, url))
                continue
            raise
        path = fetch(dl_root, "cbp%02dco" % (y % 100), "cbp%02dco.zip" % (y % 100), url, check=is_zip)
        return y, path, url
    raise SystemExit("no CBP county file for %d..%d" % (CBP_FIRST_YEAR, as_of.year))


def county_keys(out_dir):
    """The 254 Texas county FIPS keys (3-digit strings) from D2's counties.geo.json."""
    geo = read_json(os.path.join(out_dir, "counties.geo.json"))
    keys = {f["properties"]["f"] for f in geo["features"]}
    if len(keys) != 254:
        raise SystemExit("counties.geo.json has %d counties, expected 254" % len(keys))
    return keys


def size_cell(v):
    """One establishment size-class cell -> (count, withheld).  The file prints N for every cell with fewer than 3
    establishments (0, 1 or 2 are indistinguishable), so N becomes 0 here."""
    v = v.strip()
    if v == "N":
        return 0, True
    if v.isdigit():
        return int(v), False
    raise SystemExit("unexpected size-class cell %r in the CBP county file" % v)


def build_cbp(year, zip_path, url, size_bytes, as_of, keys):
    """County Business Patterns -> county-business.json document plus a stats dict for the cross-checks."""
    want = {}
    for code in CBP_CODES:
        want[code + "/" * (6 - len(code))] = code
    counties, unassigned = {}, {}
    stats = {"rows": 0, "tx_rows": 0, "kept": 0, "bad_sz_sum": 0, "unknown_fips": 0, "small_cells": 0,
             "emp_combos": {}, "withheld_cells": 0}
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if re.fullmatch(r"cbp\d\dco\.txt", os.path.basename(n).lower())]
        if len(members) != 1:
            raise SystemExit("expected one cbpYYco.txt in %s, found %s" % (zip_path, zf.namelist()))
        with zf.open(members[0]) as raw:
            rd = csv.reader(io.TextIOWrapper(raw, encoding="latin-1", newline=""))
            header = [h.strip().lower() for h in next(rd)]
            col = {h: i for i, h in enumerate(header)}
            for need in ("fipstate", "fipscty", "naics", "emp_nf", "emp", "est"):
                if need not in col:
                    raise SystemExit("CBP header lacks %r: %s" % (need, header))
            size_idx = []
            for names in SIZE_COLS:
                hit = [n for n in names if n in col]
                if not hit:
                    raise SystemExit("CBP header lacks size column %s: %s" % (names, header))
                size_idx.append(col[hit[0]])
            i_st, i_cty, i_na = col["fipstate"], col["fipscty"], col["naics"]
            i_flag, i_nf, i_emp, i_est = col.get("empflag"), col["emp_nf"], col["emp"], col["est"]  # empflag: not in 2023
            for row in rd:
                stats["rows"] += 1
                if row[i_st].strip() != "48":
                    continue
                stats["tx_rows"] += 1
                code = want.get(row[i_na].strip())
                if code is None:
                    continue
                fips = row[i_cty].strip()
                if fips != UNASSIGNED_FIPS and fips not in keys:
                    stats["unknown_fips"] += 1
                    continue
                est = int(row[i_est])
                cells = [size_cell(row[i]) for i in size_idx]
                sz = [c[0] for c in cells]
                if sum(sz) > est:
                    stats["bad_sz_sum"] += 1
                stats["small_cells"] += sum(1 for c in sz if 0 < c < 3)
                stats["withheld_cells"] += sum(1 for c in cells if c[1])
                nf, flag = row[i_nf].strip(), (row[i_flag].strip() if i_flag is not None else "")
                combo = "%s/%s" % (nf or "-", flag or "-")
                stats["emp_combos"][combo] = stats["emp_combos"].get(combo, 0) + 1
                if nf in ("D", "S") or flag:
                    emp = None
                else:
                    emp = int(row[i_emp])
                entry = {"estab": est, "emp": emp, "sz": sz}
                if fips == UNASSIGNED_FIPS:
                    unassigned[code] = entry
                else:
                    counties.setdefault(fips, {})[code] = entry
                stats["kept"] += 1
    doc = {
        "year": year,
        "asOf": as_of,
        "src": ("U.S. Census Bureau, County Business Patterns %d, bulk county file %s (member cbp%02dco.txt, "
                "comma-delimited, %.1f MB zip; layout https://www2.census.gov/programs-surveys/cbp/technical-"
                "documentation/records-layouts/noise-layout/county_layout.txt), Texas rows (FIPS state 48), "
                "NAICS codes as listed in codes; estab is the exact number of establishments with payroll in mid-March "
                "%d; sz counts them by employment size class, but the Census prints N for every size class with "
                "fewer than 3 establishments, shown here as 0, so sum(sz) can be below estab; emp is mid-March "
                "employment with the Census noise infusion (flags G, H, J), null where the Census withholds it "
                "(flags D and S). Rows with county code 999 (county not identified) are not in counties; they are "
                "kept apart under unassigned, so statewide totals are counties plus unassigned."
                % (year, url, year % 100, size_bytes / 1e6, year)),
        "codes": dict(CBP_CODES),
        "sizeClasses": list(SIZE_CLASSES),
        "unit": {"estab": "establishments", "emp": "employees, mid-March pay period",
                 "sz": "establishments per size class (0 = none or fewer than 3, withheld)"},
        "counties": {k: counties[k] for k in sorted(counties)},
        "unassigned": {k: unassigned[k] for k in CBP_CODES if k in unassigned},
    }
    return doc, stats


# ---------------------------------------------------------------- BLS State and Area Employment (CES), public API v1

def month_range(first, last):
    """['YYYY-MM', ...] from first to last inclusive."""
    y, m = int(first[:4]), int(first[5:])
    out = []
    while "%04d-%02d" % (y, m) <= last:
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def last_complete_month(as_of):
    y, m = (as_of.year - 1, 12) if as_of.month == 1 else (as_of.year, as_of.month - 1)
    return "%04d-%02d" % (y, m)


def bls_ids():
    ids = []
    for tail in BLS_IDS.values():
        ids += ["SMU" + tail, "SMS" + tail]
    return ids


def fetch_bls(dl_root, as_of, reuse):
    """One POST per ten-year window (API v1 limit); returns the saved response paths."""
    paths = []
    for y0 in range(BLS_FIRST_YEAR, as_of.year + 1, BLS_MAX_YEARS):
        y1 = min(y0 + BLS_MAX_YEARS - 1, as_of.year)
        body = json.dumps({"seriesid": bls_ids(), "startyear": str(y0), "endyear": str(y1)}).encode()
        paths.append(fetch(dl_root, "bls_ces_tx_%d_%d" % (y0, y1), "response.json", BLS_API, reuse=reuse, data=body,
                           headers={"Content-Type": "application/json"},
                           check=lambda b: b'"REQUEST_SUCCEEDED"' in b[:300]))
    return paths


def parse_bls(paths):
    """-> ({series id: {'YYYY-MM': (value or None, preliminary)}}, [API messages])."""
    out, messages = {}, []
    for p in paths:
        doc = read_json(p)
        if doc.get("status") != "REQUEST_SUCCEEDED":
            raise SystemExit("BLS API: %s %s" % (doc.get("status"), doc.get("message")))
        messages += doc.get("message") or []
        for s in doc["Results"]["series"]:
            d = out.setdefault(s["seriesID"], {})
            for r in s["data"]:
                if not re.fullmatch(r"M(0[1-9]|1[0-2])", r["period"]):
                    continue
                try:
                    v = float(r["value"])
                except ValueError:
                    v = None
                prelim = any((f or {}).get("code") == "P" for f in r.get("footnotes") or [])
                d["%s-%s" % (r["year"], r["period"][1:])] = (v, prelim)
    return out, messages


def usable(d, last):
    """Latest month (<= last) of a series that starts at BLS_FIRST_YEAR-01, else None.  A gap inside the run is
    allowed: build_jobs writes null for that month."""
    got = sorted(m for m, (v, _) in (d or {}).items() if v is not None and m <= last)
    return got[-1] if got and got[0] == "%d-01" % BLS_FIRST_YEAR else None


def build_jobs(series, messages, as_of):
    last = last_complete_month(as_of)
    chosen, notes = None, []
    for adj, label in (("SMS", "SA"), ("SMU", "NSA")):
        ends = {k: usable(series.get(adj + BLS_IDS[k]), last) for k in ("oilGas", "support")}
        notes.append("%s: %s" % (label, ", ".join("%s latest %s" % (k, v) for k, v in ends.items())))
        if all(ends.values()):
            chosen = (adj, label, ends)
            break
    if not chosen:
        raise SystemExit("no complete Texas CES series for NAICS 211 and 213 (%s); API messages: %s"
                         % ("; ".join(notes), messages[:6]))
    adj, label, ends = chosen
    log("  BLS series with data from %d-01 (SA tried first): %s" % (BLS_FIRST_YEAR, "; ".join(notes)))
    latest = max(ends.values())
    months = month_range("%d-01" % BLS_FIRST_YEAR, latest)
    doc = {"asOf": as_of.isoformat(), "latest": latest, "months": months}
    prelim = set()
    for k in ("oilGas", "support"):
        d = series[adj + BLS_IDS[k]]
        doc[k] = [d[m][0] if m in d else None for m in months]
        prelim |= {m for m in months if m in d and d[m][1]}
        gaps = [m for m, v in zip(months, doc[k]) if v is None]
        if gaps:
            log("  BLS %s has no value for %s (written as null)" % (k, ", ".join(gaps)))
    doc["prelim"] = sorted(prelim)
    word = "seasonally adjusted" if label == "SA" else "not seasonally adjusted (the seasonally adjusted SMS ids " \
                                                       "for these two industries do not exist)"
    doc["src"] = ("BLS State and Area Employment (CES/SAE), Texas, All Employees (data type 01), %s: %s%s = NAICS 211 "
                  "Oil and gas extraction, %s%s = NAICS 213 Support activities for mining; public API v1 "
                  "%s (no key; POST, startyear %d, endyear %d), retrieved %s. Months in prelim are first-print "
                  "estimates that BLS revises (monthly, then at the annual benchmark)."
                  % (word, adj, BLS_IDS["oilGas"], adj, BLS_IDS["support"], BLS_API, BLS_FIRST_YEAR, as_of.year,
                     as_of.isoformat()))
    doc["unit"] = "thousand jobs"
    doc["seasonal"] = label
    return doc, adj


# ---------------------------------------------------------------- EIA Short-Term Energy Outlook (xlsx, stdlib reader)

XNS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


class Xlsx:
    """Minimal .xlsx reader: sheet names and cell values (str, float or None) via zipfile + ElementTree."""

    def __init__(self, path):
        self.zf = zipfile.ZipFile(path)
        self.strings = []
        if "xl/sharedStrings.xml" in self.zf.namelist():
            root = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", XNS):
                self.strings.append("".join(t.text or "" for t in si.iter("{%s}t" % XNS["m"])))
        wb = ET.fromstring(self.zf.read("xl/workbook.xml"))
        rels = ET.fromstring(self.zf.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        self.sheets = {}
        for s in wb.find("m:sheets", XNS):
            t = target[s.get("{%s}id" % XNS["r"])]
            self.sheets[s.get("name")] = t.lstrip("/") if t.startswith("/") else "xl/" + t

    def rows(self, name):
        """{row number: {column number (1 = A): value}} for one sheet."""
        root = ET.fromstring(self.zf.read(self.sheets[name]))
        out = {}
        for c in root.iter("{%s}c" % XNS["m"]):
            m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r"))
            col = 0
            for ch in m.group(1):
                col = col * 26 + ord(ch) - 64
            t = c.get("t")
            v = c.find("m:v", XNS)
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % XNS["m"]))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = self.strings[int(v.text)]
            elif t in ("str", "e"):
                val = v.text
            elif t == "b":
                val = float(v.text)
            else:
                val = float(v.text)
            out.setdefault(int(m.group(2)), {})[col] = val
        return out


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# key, sheet, STEO series id, text the description cell must contain, unit
STEO_SERIES = [
    ("wti", "1tab", "WTIPUUS", "dollars per barrel", "USD per barrel"),
    ("henryHub", "1tab", "NGHHUUS", "dollars per million btu", "USD per MMBtu"),
    ("usCrude", "1tab", "COPRPUS", "million barrels per day", "million barrels per day"),
    ("usGas", "1tab", "NGPRPUS", "billion cubic feet per day", "billion cubic feet per day"),
]
STEO_PRIOR_MONTHS = 12  # months of actuals kept before the first forecast month


def ym_str(n):
    """Month number (year * 12 + month - 1) -> 'YYYY-MM'."""
    return "%04d-%02d" % (n // 12, n % 12 + 1)


def ym_num(yyyymm):
    """202609 -> month number."""
    v = int(yyyymm)
    return (v // 100) * 12 + v % 100 - 1


def build_outlook(path, size_bytes, as_of):
    """STEO_m.xlsx -> series-outlook.json document."""
    x = Xlsx(path)
    dates = x.rows("Dates")

    def labelled(prefix):
        for row in dates.values():
            v = row.get(1)
            if isinstance(v, str) and v.strip().lower().startswith(prefix):
                return row.get(4)
        raise SystemExit("STEO 'Dates' sheet lacks a %r row" % prefix)

    issued_dt = datetime.datetime.strptime(str(labelled("forecast month")).strip(), "%B %Y")
    issued = ym_str(issued_dt.year * 12 + issued_dt.month - 1)
    last_hist = ym_num(labelled("last historical month"))
    completed = (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(labelled("modeling and analysis")))).isoformat()
    actual_through = ym_str(last_hist)
    first_fc = last_hist + 1
    if ym_str(first_fc) != issued:
        raise SystemExit("STEO forecast month %s is not the month after the last historical month %s"
                         % (issued, actual_through))
    # column -> month, from the 'AAAA_DATEX' row of the Dates sheet; its 'Historical' flags must agree
    colmonth, hist = {}, {}
    for row in dates.values():
        if str(row.get(2, "")).startswith("AAAA_DATEX") and not colmonth:
            colmonth = {c: ym_num(v) for c, v in row.items() if c >= 3}
        if str(row.get(2, "")).strip() == "Historical" and not hist:
            hist = {c: v for c, v in row.items() if c >= 3}
    if not colmonth:
        raise SystemExit("STEO 'Dates' sheet has no AAAA_DATEX row")
    for c, n in colmonth.items():
        if (hist.get(c) == 1.0) != (n <= last_hist):
            raise SystemExit("STEO Historical flag disagrees with Last Historical Month at column %d" % c)
    first_m, end_m = first_fc - STEO_PRIOR_MONTHS, max(colmonth.values())
    if first_m < min(colmonth.values()):
        raise SystemExit("STEO table starts after %s" % ym_str(first_m))
    months_n = list(range(first_m, end_m + 1))
    doc = {"asOf": as_of.isoformat(), "issued": issued, "actualThrough": actual_through, "completed": completed,
           "months": [ym_str(n) for n in months_n]}
    unit, rows_used, history = {}, {}, {}
    for key, sheet, sid, desc, u in STEO_SERIES:
        t = x.rows(sheet)
        # header check: the month abbreviations in the sheet must match the Dates mapping
        hdr = [r for r in sorted(t)[:10] if t[r].get(3) in MONTH_ABBR and t[r].get(4) in MONTH_ABBR]
        if not hdr:
            raise SystemExit("STEO %s: no month header row" % sheet)
        for c, n in colmonth.items():
            if t[hdr[0]].get(c) != MONTH_ABBR[n % 12]:
                raise SystemExit("STEO %s: column %d header %r is not %s" % (sheet, c, t[hdr[0]].get(c), ym_str(n)))
        hits = [r for r in sorted(t) if str(t[r].get(1, "")).strip().upper() == sid
                and desc in str(t[r].get(2, "")).lower()]
        if len(hits) != 1:
            raise SystemExit("STEO %s: expected one %s row (%s), found %d" % (sheet, sid, desc, len(hits)))
        row = t[hits[0]]
        by_month = {n: row.get(c) for c, n in colmonth.items()}
        doc[key] = [round(by_month[n], 3) if isinstance(by_month.get(n), float) else None for n in months_n]
        history[key] = {ym_str(n): v for n, v in by_month.items() if isinstance(v, float) and n <= last_hist}
        unit[key] = u
        rows_used[key] = "%s!%s row %d" % (sheet, sid, hits[0])
    doc["src"] = ("U.S. Energy Information Administration, Short-Term Energy Outlook, %s edition (modeling completed %s), "
                  "public data workbook %s (%d bytes), Table 1 U.S. Energy Markets Summary (sheet 1tab): WTIPUUS WTI "
                  "spot price, NGHHUUS Henry Hub spot price, COPRPUS U.S. crude oil production, NGPRPUS U.S. dry "
                  "natural gas production. Months through %s are STEO history (the workbook's Last Historical Month; "
                  "survey-based production data lag about two months, so the newest usCrude and usGas history months "
                  "are typically EIA estimates), %s onward are forecasts."
                  % (issued, completed, STEO_URL, size_bytes, actual_through, issued))
    doc["unit"] = unit
    return doc, history, rows_used


# ---------------------------------------------------------------- validation and cross-checks (read the written files)

OUT_FILES = {"cbp": "county-business.json", "jobs": "series-jobs.json", "outlook": "series-outlook.json"}


def fail(msg):
    raise SystemExit("VALIDATION FAILED: " + msg)


def validate_doc(stage, doc, out_dir, as_of):
    """Schema checks on one document (before it replaces the file on disk, and again after it was written)."""
    fn = OUT_FILES[stage]
    for k in ("asOf", "src"):
        if not doc.get(k):
            fail("%s lacks %s" % (fn, k))
    if stage == "cbp":
        keys = county_keys(out_dir)
        if list(doc["codes"]) != list(CBP_CODES) or len(doc["sizeClasses"]) != 9:
            fail("county-business codes or sizeClasses changed")
        if not doc["counties"]:
            fail("county-business has no counties")
        groups = list(doc["counties"].items()) + [("unassigned", doc["unassigned"])]
        for fips, ents in groups:
            if fips != "unassigned" and fips not in keys:
                fail("county %s is not one of the 254 Texas counties" % fips)
            for code, e in ents.items():
                if code not in CBP_CODES:
                    fail("county %s has unknown code %s" % (fips, code))
                if len(e["sz"]) != 9 or sum(e["sz"]) > e["estab"] or e["estab"] < 1:
                    fail("county %s code %s: size classes %s exceed estab %s" % (fips, code, e["sz"], e["estab"]))
                if e["emp"] is not None and (not isinstance(e["emp"], int) or e["emp"] < 0):
                    fail("county %s code %s: bad emp %r" % (fips, code, e["emp"]))
    elif stage == "jobs":
        n = len(doc["months"])
        if (doc["months"] != month_range("%d-01" % BLS_FIRST_YEAR, doc["months"][-1])
                or doc["months"][-1] > last_complete_month(as_of)):
            fail("series-jobs months are not a clean run from %d-01 up to %s" % (BLS_FIRST_YEAR,
                                                                                   last_complete_month(as_of)))
        for k in ("oilGas", "support"):
            if len(doc[k]) != n or any(v is not None and not isinstance(v, (int, float)) for v in doc[k]):
                fail("series-jobs %s is malformed" % k)
            if any(v is not None and not 1.0 <= v <= 1000.0 for v in doc[k]):
                fail("series-jobs %s has a value outside 1..1000 thousand jobs" % k)
        if doc["seasonal"] not in ("NSA", "SA") or doc["unit"] != "thousand jobs":
            fail("series-jobs seasonal or unit")
    else:
        months = doc["months"]
        if months != month_range(months[0], months[-1]):
            fail("series-outlook months are not consecutive")
        at = months.index(doc["actualThrough"])
        if at != STEO_PRIOR_MONTHS - 1 or months[at + 1] != doc["issued"]:
            fail("series-outlook: expected %d actual months, then the issue month" % STEO_PRIOR_MONTHS)
        for k in ("wti", "henryHub", "usCrude", "usGas"):
            if len(doc[k]) != len(months) or any(v is None for v in doc[k]):
                fail("series-outlook %s has gaps" % k)


def write_checked(stage, doc, out_dir, as_of):
    """Validate, then write; a document that fails never replaces the file on disk."""
    validate_doc(stage, doc, out_dir, as_of)
    return write_json(os.path.join(out_dir, OUT_FILES[stage]), doc, max_bytes=MAX_BYTES)


def validate(out_dir, as_of, stages):
    """Re-read what was written: it must parse, pass the schema checks and stay inside the size budget."""
    for stage in stages:
        fn = OUT_FILES[stage]
        size = os.path.getsize(os.path.join(out_dir, fn))
        if size > MAX_BYTES:
            fail("%s is %d bytes, over the 400 KB budget" % (fn, size))
        validate_doc(stage, read_json(os.path.join(out_dir, fn)), out_dir, as_of)
        log("  valid    %-22s %8d bytes" % (fn, size))


QCEW_URL = "https://data.bls.gov/cew/data/api/%d/a/industry/%s.csv"


def fetch_qcew_state(dl_root, year, reuse):
    """Texas statewide QCEW annual averages (private ownership) for NAICS 211 and 213, used only as a cross-check
    (the same keyless files D2 used for the county labor file); None when they cannot be fetched or read."""
    out = {}
    try:
        for code in ("211", "213"):
            path = fetch(dl_root, "qcew_%d_%s" % (year, code), "%s.csv" % code, QCEW_URL % (year, code), reuse=reuse,
                         check=lambda b: b"area_fips" in b[:300].lower())
            with open(path, encoding="utf-8", errors="replace", newline="") as f:
                for r in csv.DictReader(f):
                    if (r["area_fips"] == "48000" and r["own_code"] == "5" and r["industry_code"] == code
                            and r["size_code"] in ("0", "")):
                        out[code] = {"estab": int(r["annual_avg_estabs"]), "emp": int(r["annual_avg_emplvl"]),
                                     "disclosure": r.get("disclosure_code", "")}
    except (SystemExit, OSError, ValueError, KeyError) as exc:
        log("  QCEW statewide cross-check data unavailable: %s" % exc)
        return None
    return out if len(out) == 2 else None


def labor_and_names(out_dir):
    """QCEW (D2's county-labor.json) as {code: {fips: estab}} and {code: total emp}, plus county names."""
    labor = read_json(os.path.join(out_dir, "county-labor.json"))
    est, emp = {"211": {}, "213": {}}, {"211": 0, "213": 0}
    for fips, v in labor["counties"].items():
        for code, key in (("211", "o"), ("213", "s")):
            if v.get(key):
                est[code][fips] = v[key]["estab"]
                emp[code] += v[key]["emp"] or 0
    names = {f["properties"]["f"]: f["properties"]["n"]
             for f in read_json(os.path.join(out_dir, "counties.geo.json"))["features"]}
    return labor["year"], est, emp, names


def cbp_state_totals(cbp, code):
    """(establishments, employment) for Texas: counties plus the unassigned (county 999) row."""
    cells = [c[code] for c in cbp["counties"].values() if code in c]
    if code in cbp["unassigned"]:
        cells.append(cbp["unassigned"][code])
    return sum(e["estab"] for e in cells), sum(e["emp"] or 0 for e in cells)


def check_cbp(out_dir, stats, qcew):
    year_q, qest, _, names = labor_and_names(out_dir)
    cbp = read_json(os.path.join(out_dir, OUT_FILES["cbp"]))
    log("CHECK CBP %d: %d Texas rows read of %d, %d kept; rows with an unknown county code: %d; rows whose size classes "
        "exceed estab: %d; printed size cells of 1 or 2: %d; withheld (N) cells set to 0: %d"
        % (cbp["year"], stats["tx_rows"], stats["rows"], stats["kept"], stats["unknown_fips"], stats["bad_sz_sum"],
           stats["small_cells"], stats["withheld_cells"]))
    log("  employment noise flags (flag/size flag -> rows; D and S would mean withheld): %s"
        % json.dumps(stats["emp_combos"], sort_keys=True))
    for code in CBP_CODES:
        cs = [c[code] for c in cbp["counties"].values() if code in c]
        un = cbp["unassigned"].get(code)
        log("  %-6s %-42s counties %3d  estab %5d (+%d unassigned)  in withheld size classes %3d  emp %6d (+%s unassigned)"
            % (code, CBP_CODES[code], len(cs), sum(e["estab"] for e in cs), un["estab"] if un else 0,
               sum(e["estab"] - sum(e["sz"]) for e in cs), sum(e["emp"] or 0 for e in cs), un["emp"] if un else 0))
    for code in ("213", "211"):
        top = sorted(((c[code]["estab"], f) for f, c in cbp["counties"].items() if code in c), reverse=True)[:8]
        log("  top 8 counties by NAICS %s establishments, CBP %d | QCEW %d: %s"
            % (code, cbp["year"], year_q, "; ".join("%s %d|%s" % (names[f], n, qest[code].get(f, "-")) for n, f in top)))
    for fips in ("329", "389", "227"):
        e = cbp["counties"].get(fips, {}).get("213")
        log("  NAICS 213 in %s (%s): %s; QCEW %d: %s"
            % (names[fips], fips, e and "%d establishments, emp %s, size classes %s" % (e["estab"], e["emp"], e["sz"]),
               year_q, qest["213"].get(fips)))
    for code in ("211", "213"):
        both = [(c[code]["estab"], qest[code][f]) for f, c in cbp["counties"].items()
                if code in c and f in qest[code]]
        ratios = sorted(a / b for a, b in both)
        log("  CBP/QCEW county establishments, NAICS %s: %d counties in both, sums %d vs %d, median county ratio %.2f"
            % (code, len(both), sum(a for a, _ in both), sum(b for _, b in both), ratios[len(ratios) // 2]))
    if qcew:
        for code in ("211", "213"):
            est, emp = cbp_state_totals(cbp, code)
            log("  Texas statewide NAICS %s: CBP %d %d establishments, %d employees vs QCEW %d (private) %d establishments, "
                "%d employees (CBP/QCEW %.2f establishments, %.2f employees)"
                % (code, cbp["year"], est, emp, year_q, qcew[code]["estab"], qcew[code]["emp"],
                   est / qcew[code]["estab"], emp / qcew[code]["emp"]))


def check_jobs(out_dir, qcew):
    year_q, _, qemp, _ = labor_and_names(out_dir)
    jobs = read_json(os.path.join(out_dir, OUT_FILES["jobs"]))
    j = jobs["months"]
    log("CHECK BLS CES Texas (%s, latest %s, preliminary months: %s)"
        % (jobs["seasonal"], jobs["latest"], ", ".join(jobs["prelim"]) or "none"))
    log("  %s: oil and gas extraction %s, support activities for mining %s thousand jobs; %s: %s and %s"
        % (jobs["latest"], jobs["oilGas"][-1], jobs["support"][-1], j[0], jobs["oilGas"][0], jobs["support"][0]))
    yr = [i for i, m in enumerate(j) if m.startswith(str(year_q))]
    for key, code in (("oilGas", "211"), ("support", "213")):
        if len(yr) == 12 and all(jobs[key][i] is not None for i in yr):
            avg = sum(jobs[key][i] for i in yr) / 12 * 1000
            line = ("  %d average, NAICS %s: BLS CES %.0f vs QCEW county file (sum of disclosed counties) %d (ratio %.2f)"
                    % (year_q, code, avg, qemp[code], avg / qemp[code]))
            if qcew:
                line += "; vs QCEW Texas statewide %d (ratio %.2f)" % (qcew[code]["emp"], avg / qcew[code]["emp"])
            log(line)
    cbp_path = os.path.join(out_dir, OUT_FILES["cbp"])
    if os.path.exists(cbp_path):
        cbp = read_json(cbp_path)
        mar = "%d-03" % cbp["year"]
        if mar in j:
            for key, code in (("oilGas", "211"), ("support", "213")):
                tot = cbp_state_totals(cbp, code)[1]
                ces = jobs[key][j.index(mar)] * 1000
                log("  %s, NAICS %s: BLS CES %.0f vs CBP statewide (counties + unassigned) %d (ratio %.2f)"
                    % (mar, code, ces, tot, tot / ces))


def check_outlook(out_dir, history):
    out = read_json(os.path.join(out_dir, OUT_FILES["outlook"]))
    markets = read_json(os.path.join(out_dir, "series-markets.json"))
    mm = {m: i for i, m in enumerate(markets["months"])}
    log("CHECK STEO %s: months %s..%s, actual through %s, first forecast month %s"
        % (out["issued"], out["months"][0], out["months"][-1], out["actualThrough"], out["issued"]))
    for key, mkey in (("wti", "wti"), ("henryHub", "henryHub")):
        diffs = [(abs(v - markets[mkey][mm[m]]), m, v, markets[mkey][mm[m]]) for m, v in sorted(history[key].items())
                 if m in mm and markets[mkey][mm[m]] is not None]
        worst = max(diffs)
        log("  %s: %d STEO history months (%s..%s) vs series-markets.json: max abs difference %.3f (at %s: %s vs %s); "
            "exact matches %d" % (key, len(diffs), diffs[0][1], diffs[-1][1], worst[0], worst[1], worst[2], worst[3],
                                  sum(1 for d in diffs if d[0] < 0.005)))
    i = out["months"].index(out["actualThrough"])
    log("  latest actuals %s: WTI %s, Henry Hub %s, U.S. crude %s million b/d, U.S. dry gas %s Bcf/d"
        % (out["actualThrough"], out["wti"][i], out["henryHub"][i], out["usCrude"][i], out["usGas"][i]))
    for m in [m for m in out["months"][:i + 1] if m in mm and markets["txCrude"][mm[m]] is not None][-3:]:
        y, mo = int(m[:4]), int(m[5:])
        days = (datetime.date(y + (mo == 12), mo % 12 + 1, 1) - datetime.date(y, mo, 1)).days
        tx = markets["txCrude"][mm[m]] / 1000.0 / days
        us = out["usCrude"][out["months"].index(m)]
        log("  Texas share of U.S. crude, %s: EIA Texas %.2f of STEO U.S. %.2f million b/d = %.0f%%"
            % (m, tx, us, 100 * tx / us))
    log("  forecast: WTI %s..%s, Henry Hub %s..%s over %s..%s"
        % (min(out["wti"][i + 1:]), max(out["wti"][i + 1:]), min(out["henryHub"][i + 1:]),
           max(out["henryHub"][i + 1:]), out["months"][i + 1], out["months"][-1]))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=["cbp", "jobs", "outlook"], help="run one stage only")
    ap.add_argument("--as-of", default=CONTRACT_AS_OF, help="YYYY-MM-DD (default %s)" % CONTRACT_AS_OF)
    ap.add_argument("--dl-root", default=DEFAULT_DL, help="raw download root (default: dl/ at the repo root)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output folder (default: site/public/data)")
    ap.add_argument("--reuse", action="store_true", help="parse the newest earlier download instead of fetching")
    ap.add_argument("--fetch-only", action="store_true", help="download (or locate) the raw files and stop")
    args = ap.parse_args()
    as_of = datetime.date.fromisoformat(args.as_of)
    stages = [args.only] if args.only else ["cbp", "jobs", "outlook"]
    out = args.out
    os.makedirs(out, exist_ok=True)
    log("D5 federal layers, as of %s; downloads under %s" % (as_of, args.dl_root))

    raw = {}
    if "cbp" in stages:
        raw["cbp"] = fetch_cbp(args.dl_root, as_of, args.reuse)
    if "jobs" in stages:
        raw["jobs"] = fetch_bls(args.dl_root, as_of, args.reuse)
    if "outlook" in stages:
        raw["outlook"] = fetch(args.dl_root, "steo_m", "STEO_m.xlsx", STEO_URL, reuse=args.reuse, check=is_zip)
    if args.fetch_only:
        return 0

    log("Building")
    stats = history = None
    if "cbp" in stages:
        year, zpath, url = raw["cbp"]
        doc, stats = build_cbp(year, zpath, url, os.path.getsize(zpath), as_of.isoformat(), county_keys(out))
        log("  %-22s %8d bytes, %d counties" % (OUT_FILES["cbp"], write_checked("cbp", doc, out, as_of),
                                                len(doc["counties"])))
    if "jobs" in stages:
        series, messages = parse_bls(raw["jobs"])
        doc, adj = build_jobs(series, messages, as_of)
        log("  BLS API messages: %s" % (messages or "none"))
        log("  %-22s %8d bytes, %d months %s..%s" % (OUT_FILES["jobs"], write_checked("jobs", doc, out, as_of),
                                                    len(doc["months"]), doc["months"][0], doc["months"][-1]))
        mining = series.get(adj + BLS_IDS["mining"], {}).get(doc["latest"])
        if mining and mining[0]:
            both = doc["oilGas"][-1] + doc["support"][-1]
            log("  context: %s 211 + 213 = %.1f vs all Mining and logging %.1f thousand jobs (%.0f%%)"
                % (doc["latest"], both, mining[0], 100 * both / mining[0]))
    if "outlook" in stages:
        doc, history, rows_used = build_outlook(raw["outlook"], os.path.getsize(raw["outlook"]), as_of)
        log("  %-22s %8d bytes, %d months %s..%s; rows %s"
            % (OUT_FILES["outlook"], write_checked("outlook", doc, out, as_of), len(doc["months"]),
               doc["months"][0], doc["months"][-1], rows_used))

    log("Validating")
    validate(out, as_of, stages)
    log("Cross-checks")
    qcew = None
    if "cbp" in stages or "jobs" in stages:
        qcew = fetch_qcew_state(args.dl_root, read_json(os.path.join(out, "county-labor.json"))["year"], args.reuse)
    if "cbp" in stages:
        check_cbp(out, stats, qcew)
    if "jobs" in stages:
        check_jobs(out, qcew)
    if "outlook" in stages:
        check_outlook(out, history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
