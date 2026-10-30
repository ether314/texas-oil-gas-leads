#!/usr/bin/env python3
"""D6 producer: rigs, taxes, minerals and basins for the Texas oil & gas leads site.

Writes into site/public/data/ (spec: site/DATA_CONTRACT_V3.md, section D6):

  series-rigs.json      Baker Hughes North America rig count, weekly, 2019 on
  series-tax.json       Texas oil and natural gas production tax collections, monthly, 2019 on
  county-minerals.json  School District Property Value Study, category G (oil, gas and other minerals), by county
  basins.json           county lists for the Permian, Eagle Ford, Haynesville and Barnett regions

Public data only: no keys, no registration, Python standard library only.  Run:

    python3 -I site/pipeline/d6_misc.py [--only rigs,tax,minerals,basins] [--as-of YYYY-MM-DD]
                                        [--dl-root DIR] [--out DIR]

Each item is independent: a blocked source skips that item (message "SKIPPED") and the others still run.  An existing
output file is replaced only by a successful run.  Raw downloads go to <dl-root>/<name>/<file>, every file in its own
new empty folder (a -N suffix is added on re-runs).  They are untrusted data: parsed with json / zipfile+ElementTree /
regex, never executed.  Requests are paced (about one per second per host) with the generic User-Agent
"Mozilla/5.0 (research script)"; no e-mail address is ever sent.

Rigs: rigcount.bakerhughes.com answers HTTP 403 ("Access Denied") to scripted access.  That is not worked around: the
script asks the site once (so a future run uses the live weekly workbook if the block is lifted) and otherwise reads the
Internet Archive's public copies of Baker Hughes' own workbooks (archive.org availability API + web.archive.org raw
captures).  The newest weekly workbook the archive holds fixes the last week of the series.
"""
import argparse
import collections
import datetime
import gzip
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

AS_OF = "2026-10-30"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(SITE, "public", "data")
DEFAULT_DL = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))
UA = "Mozilla/5.0 (research script)"
MAX_BYTES = 400 * 1000

DL_ROOT = DEFAULT_DL
DOWNLOADS = []          # (folder name, file name, bytes, url)
CHECKS = []             # (item, text)
BH_TX_COUNTIES = {}     # basin key -> set of county names with a Texas rig (filled by the rigs item, used by basins)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def log(msg):
    print(msg, flush=True)


def check(item, text):
    CHECKS.append((item, text))
    log("  check [%s] %s" % (item, text))


# --------------------------------------------------------------------------------------------- http and files
class Refused(Exception):
    """The server refused (401/403/404/410) or kept failing; refusals are never retried around."""

    def __init__(self, url, status, note=""):
        super().__init__("%s -> HTTP %s %s" % (url, status, note))
        self.url = url
        self.status = status


_last_hit = {}


def http_get(url, timeout=180, tries=3, gap=1.0):
    host = urllib.parse.urlsplit(url).netloc
    last = None
    for attempt in range(tries):
        wait = _last_hit.get(host, 0.0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    data = gzip.decompress(data)
                return data, r.headers, r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 410):
                raise Refused(url, e.code)
            last = e
            ra = e.headers.get("Retry-After") if e.headers else None
            time.sleep(min(60.0, float(ra)) if ra and ra.isdigit() else 3.0 * (attempt + 1))
        except OSError as e:  # URLError, timeouts, resets
            last = e
            time.sleep(3.0 * (attempt + 1))
    raise Refused(url, getattr(last, "code", "error"), str(last)[:80])


def new_dir(name):
    base = os.path.join(DL_ROOT, name)
    d, n = base, 0
    while os.path.isdir(d) and os.listdir(d):
        n += 1
        d = "%s-%d" % (base, n)
    os.makedirs(d, exist_ok=True)
    return d


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "file"


def download(url, name, filename=None, **kw):
    """GET url into its own new folder <dl-root>/<name>/; returns (path, headers)."""
    data, headers, _final = http_get(url, **kw)
    if filename is None:
        cd = headers.get("Content-Disposition") or ""
        m = re.search(r'filename="?([^";]+)"?', cd)
        filename = safe_name(m.group(1)) if m else safe_name(urllib.parse.urlsplit(url).path.split("/")[-1] or name)
    path = os.path.join(new_dir(name), filename)
    with open(path, "wb") as fh:
        fh.write(data)
    DOWNLOADS.append((os.path.basename(os.path.dirname(path)), filename, len(data), url))
    return path, headers


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_json(out_dir, name, obj):
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    size = len(raw.encode("utf-8"))
    if size > MAX_BYTES:
        raise RuntimeError("%s is %d bytes, over the %d byte budget" % (name, size, MAX_BYTES))
    path = os.path.join(out_dir, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(raw)
    os.replace(tmp, path)
    log("  wrote %s (%d bytes)" % (path, size))
    return size


# --------------------------------------------------------------------------------------------- xlsx (zipfile + ElementTree)
def xlsx_open(path):
    z = zipfile.ZipFile(path)
    shared = []
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    except KeyError:
        pass
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = {}
    for s in wb.iter(NS + "sheet"):
        t = rmap[s.get(RNS + "id")].lstrip("/")
        sheets[s.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return z, shared, sheets


def col_index(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + ord(ch.upper()) - 64
        else:
            break
    return n - 1


def iter_rows(z, path, shared, cols=None):
    """Yield (row number, {column index: value}); numbers are floats, strings str; streams the sheet."""
    sd, n = None, 0
    with z.open(path) as fh:
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            if ev == "start":
                if el.tag == NS + "sheetData":
                    sd = el
                continue
            if el.tag != NS + "row":
                continue
            vals = {}
            for c in el.findall(NS + "c"):
                i = col_index(c.get("r") or "")
                if cols is not None and i not in cols:
                    continue
                t = c.get("t")
                v = c.find(NS + "v")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(NS + "t"))
                elif v is None or v.text is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                elif t in ("str", "e"):
                    val = v.text
                elif t == "b":
                    val = v.text == "1"
                else:
                    try:
                        val = float(v.text)
                    except ValueError:
                        val = v.text
                vals[i] = val
            rn = int(el.get("r") or 0)
            el.clear()
            n += 1
            if sd is not None and n % 4000 == 0:
                sd.clear()
            yield rn, vals


def xl_iso(serial):
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(serial))).isoformat()


def iso_xl(iso):
    return (datetime.date.fromisoformat(iso) - datetime.date(1899, 12, 30)).days


def text_of(page_html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page_html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


# --------------------------------------------------------------------------------------------- counties
def load_counties(out_dir):
    g = json.load(open(os.path.join(out_dir, "counties.geo.json"), encoding="utf-8"))
    return {f["properties"]["f"]: f["properties"]["n"] for f in g["features"]}


def norm_name(s):
    return re.sub(r"[^a-z]", "", s.lower())


NAME_ALIASES = {"dimmitt": "dimmit", "shackleford": "shackelford"}   # spellings used by the RRC pages


def make_name_lookup(counties):
    by = {norm_name(n): f for f, n in counties.items()}

    def lookup(name):
        k = norm_name(re.sub(r"\bcounty\b", "", name, flags=re.I))
        return by.get(NAME_ALIASES.get(k, k))
    return lookup


# --------------------------------------------------------------------------------------------- item 1: rigs
BH_PAGE = "https://rigcount.bakerhughes.com/na-rig-count"
BH_FILE = "https://rigcount.bakerhughes.com/static-files/%s"
HIST_UUID_FALLBACK = "e98bcf83-c458-4a88-8f35-4ac4d77628bb"   # "North America Rig Count New Report (2013-Aug 2025)"
LINK_RE = re.compile(r'<a\s[^>]*href="[^"]*?/static-files/([0-9a-f-]{36})"[^>]*>(.*?)</a>', re.S | re.I)
METRICS = ("us", "txTotal", "txOil", "txGas", "permian", "permianTx", "eagleFord", "haynesville", "barnett")
BASIN_KEY = {"permian": "permian", "eagle ford": "eagleFord", "haynesville": "haynesville", "barnett": "barnett"}
ANCHOR_LABELS = {"united states total": "us", "texas": "txTotal", "permian": "permian", "eagle ford": "eagleFord",
                 "haynesville": "haynesville", "barnett": "barnett"}


def bh_links(page_html):
    """-> (weekly (uuid, label) or None, historical (uuid, label) or None) from a BH rig count page."""
    weekly = hist = None
    for uuid, label in LINK_RE.findall(page_html):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", label))).strip()
        if weekly is None and re.search(r"Rig Count Report\s*-\s*New Report", text, re.I):
            weekly = (uuid, text)
        elif hist is None and re.search(r"New Report\s*\(\s*2013\s*-", text, re.I):
            hist = (uuid, text)
    return weekly, hist


def wb_closest(orig_url, stamp):
    """Internet Archive availability API -> timestamp of the closest 200 capture, or None."""
    api = "https://archive.org/wayback/available?url=%s&timestamp=%s" % (urllib.parse.quote(orig_url, safe=":/"), stamp)
    data, _h, _f = http_get(api, gap=1.2)
    snap = (json.loads(data).get("archived_snapshots") or {}).get("closest")
    if snap and snap.get("available") and str(snap.get("status")) == "200":
        return snap["timestamp"]
    return None


def wb_raw(stamp, orig_url):
    return "https://web.archive.org/web/%sid_/%s" % (stamp, orig_url)


def fetch_bh_workbooks(as_of):
    """-> (list of (label, path, origin), how).  Newest weekly workbook last."""
    # 1) the live site, once, with the generic User-Agent
    try:
        data, _h, _f = http_get(BH_PAGE, tries=1)
        weekly, hist = bh_links(data.decode("utf-8", "replace"))
        if weekly:
            log("  rigs: Baker Hughes site reachable; using its workbooks directly")
            out = []
            if hist:
                p, _ = download(BH_FILE % hist[0], "bh_rigs_hist_" + hist[0][:8])
                out.append((hist[1], p, BH_FILE % hist[0]))
            p, _ = download(BH_FILE % weekly[0], "bh_rigs_weekly_" + weekly[0][:8])
            out.append((weekly[1], p, BH_FILE % weekly[0]))
            return out, "direct"
        log("  rigs: Baker Hughes page has no workbook links; using the Internet Archive")
    except Refused as e:
        log("  rigs: baker hughes site answered HTTP %s to scripted access (not worked around); "
            "using the Internet Archive's public copies" % e.status)
    # 2) Internet Archive: newest archived weekly workbook, plus the historical one
    page_orig = "https://rigcount.bakerhughes.com/na-rig-count"
    start = datetime.date.fromisoformat(as_of)
    seen, weekly_hit, hist_uuid = set(), None, None
    for k in range(0, 40):
        stamp = (start - datetime.timedelta(days=7 * k)).strftime("%Y%m%d")
        snap = wb_closest(page_orig, stamp)
        if not snap or snap in seen:
            continue
        seen.add(snap)
        data, _h, _f = http_get(wb_raw(snap, page_orig))
        weekly, hist = bh_links(data.decode("utf-8", "replace"))
        if hist and not hist_uuid:
            hist_uuid = hist
        if not weekly:
            continue
        fstamp = wb_closest(BH_FILE % weekly[0], snap)
        log("  rigs: page capture %s lists weekly file %s -> %s" % (snap, weekly[0][:8], fstamp or "not archived"))
        if fstamp:
            weekly_hit = (weekly, fstamp)
            break
    out = []
    hu = hist_uuid[0] if hist_uuid else HIST_UUID_FALLBACK
    hlabel = hist_uuid[1] if hist_uuid else "North America Rig Count New Report (2013-Aug 2025)"
    hstamp = wb_closest(BH_FILE % hu, as_of.replace("-", ""))
    if hstamp:
        p, _ = download(wb_raw(hstamp, BH_FILE % hu), "bh_rigs_hist_" + hu[:8])
        out.append((hlabel, p, "web.archive.org capture %s of %s" % (hstamp, BH_FILE % hu)))
    else:
        log("  rigs: historical workbook %s is not archived" % hu[:8])
    if weekly_hit:
        (uuid, label), fstamp = weekly_hit
        p, _ = download(wb_raw(fstamp, BH_FILE % uuid), "bh_rigs_weekly_" + uuid[:8])
        out.append((label, p, "web.archive.org capture %s of %s" % (fstamp, BH_FILE % uuid)))
    else:
        log("  rigs: no archived weekly workbook found")
    return out, "wayback"


def parse_bh(path):
    """-> (weekly {excel date: {metric: value}}, anchors {metric: value}, anchor ISO date, tx counties by basin)."""
    z, ss, sheets = xlsx_open(path)
    weekly = collections.defaultdict(lambda: dict.fromkeys(METRICS, 0.0))
    counties = collections.defaultdict(set)
    hdr = None
    for _r, v in iter_rows(z, sheets["NAM Weekly"], ss):
        if hdr is None:
            if str(v.get(0, "")).strip().lower() == "country":
                hdr = {str(x).strip().lower(): k for k, x in v.items() if isinstance(x, str)}
                c_ctry, c_cty, c_bas, c_for, c_st, c_dt, c_val = (
                    hdr[k] for k in ("country", "county", "basin", "drillfor", "state/province", "us_publishdate",
                                     "rig count value"))
            continue
        d, val = v.get(c_dt), v.get(c_val)
        if not isinstance(d, float) or not isinstance(val, float):
            continue
        if str(v.get(c_ctry, "")).strip().upper() != "UNITED STATES":
            continue
        m = weekly[int(d)]
        st = str(v.get(c_st, "")).strip().upper()
        basin = str(v.get(c_bas, "")).strip().lower()
        dfor = str(v.get(c_for, "")).strip().lower()
        m["us"] += val
        if st == "TEXAS":
            m["txTotal"] += val
            if dfor == "oil":
                m["txOil"] += val
            elif dfor == "gas":
                m["txGas"] += val
        bk = BASIN_KEY.get(basin)
        if bk:
            m[bk] += val
            if st == "TEXAS":
                if bk == "permian":
                    m["permianTx"] += val
                if val > 0:
                    counties[bk].add(str(v.get(c_cty, "")).strip())
    if hdr is None:
        raise RuntimeError("NAM Weekly header row not found in %s" % os.path.basename(path))
    anchors, adate = {}, None
    for _r, v in iter_rows(z, sheets["NAM Summary"], ss):
        strs = [x for _i, x in sorted(v.items()) if isinstance(x, str)]
        for x in strs:
            if adate is None and re.fullmatch(r"\d{2}/\d{2}/\d{4}", x.strip()):
                dd, mm, yy = x.strip().split("/")
                adate = "%s-%s-%s" % (yy, mm, dd)
        if strs:
            key = ANCHOR_LABELS.get(strs[0].strip().lower())
            nums = [x for _i, x in sorted(v.items()) if isinstance(x, float)]
            if key and key not in anchors and nums:
                anchors[key] = nums[0]
    return weekly, anchors, adate, counties


def eia_monthly_rigs():
    """EIA's monthly U.S. rotary rigs in operation (Baker Hughes data, 4- or 5-week periods) -> {YYYY-MM: rigs}."""
    path, _ = download("https://www.eia.gov/dnav/pet/pet_crd_drill_s1_m.htm", "eia_rotary_rigs_monthly", "rigs.htm")
    text = text_of(read_text(path))
    mh = re.search(r"Data Series\s+((?:[A-Z][a-z]{2}-\d{2}\s+)+)View History", text)
    mr = re.search(r"Rotary Rigs in Operation\s+((?:\d+\s+)+)\d{4}-\d{4}", text)
    if not (mh and mr):
        return {}
    months = mh.group(1).split()
    vals = [int(x) for x in mr.group(1).split()]
    mon = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
    out = {}
    for lab, val in zip(months, vals):
        out["20%s-%02d" % (lab[4:], mon[lab[:3]])] = val
    return out


def run_rigs(out_dir, as_of):
    files, how = fetch_bh_workbooks(as_of)
    if not files:
        raise RuntimeError("no Baker Hughes workbook could be fetched")
    parts, notes = [], []
    for label, path, origin in files:                     # historical first, weekly last: the newer file wins
        t0 = time.time()
        weekly, anchors, adate, counties = parse_bh(path)
        log("  rigs: parsed %s: %d weeks %s..%s in %.0fs" % (os.path.basename(path), len(weekly), xl_iso(min(weekly)),
                                                              xl_iso(max(weekly)), time.time() - t0))
        parts.append((label, weekly))
        notes.append((label, os.path.basename(path), origin, anchors, adate, weekly))
        for k, s in counties.items():
            BH_TX_COUNTIES.setdefault(k, set()).update(s)
    # merge: newest source wins; compare the overlap
    final, both, diffs, maxd = {}, 0, collections.Counter(), collections.Counter()
    for _label, weekly in parts:
        for d, m in weekly.items():
            if d in final:
                both += 1
                for k in METRICS:
                    dv = abs(final[d][k] - m[k])
                    if dv:
                        diffs[k] += 1
                        maxd[k] = max(maxd[k], dv)
            final[d] = m
    if len(parts) > 1:
        check("rigs", "overlap between the two workbooks: %d weeks; weeks that differ by metric: %s"
              % (both, dict(diffs) or "none"))
    first = iso_xl("2019-01-01")
    dates = sorted(d for d in final if d >= first)
    if not dates:
        raise RuntimeError("no weeks since 2019 in the Baker Hughes data")
    iso = [xl_iso(d) for d in dates]
    series = {k: [int(round(final[d][k])) for d in dates] for k in METRICS}
    wd = collections.Counter(datetime.date.fromisoformat(x).strftime("%a") for x in iso)
    expected = int(round((dates[-1] - dates[0]) / 7.0)) + 1
    check("rigs", "%d weeks %s..%s (%d expected at one publish date per week: %s); publish weekdays %s"
          % (len(dates), iso[0], iso[-1], expected, "none missing" if expected == len(dates) else "CHECK FOR GAPS",
             dict(wd)))
    # anchors: the summary sheet of each workbook against our sums for that week
    for label, fname, _origin, anchors, adate, weekly in notes:
        if not anchors:
            continue
        when = adate or xl_iso(max(weekly))
        d = iso_xl(when)
        if d in final:
            bad = {k: (anchors[k], final[d][k]) for k in anchors if abs(anchors[k] - final[d][k]) > 0.5}
            check("rigs", "BH summary sheet of %s (week %s): %s match our sums%s"
                  % (fname, when, ", ".join("%s=%d" % (k, anchors[k]) for k in anchors),
                     ("; MISMATCH " + str(bad)) if bad else ""))
    # EIA monthly series (same underlying Baker Hughes counts, a different publisher)
    try:
        eia = eia_monthly_rigs()
        by_month = collections.defaultdict(list)
        for d, v in zip(iso, series["us"]):
            by_month[d[:7]].append(v)
        cmp_ = ["%s EIA %d vs mean of weeks %.1f" % (m, eia[m], statistics.mean(by_month[m])) for m in sorted(eia) if m in by_month]
        check("rigs", "EIA monthly U.S. rotary rigs: " + "; ".join(cmp_))
    except Refused as e:
        check("rigs", "EIA monthly comparison skipped (%s)" % e)
    tx, pe, ptx = series["txTotal"][-1], series["permian"][-1], series["permianTx"][-1]
    check("rigs", "latest %s: US %d, Texas %d (oil %d, gas %d), Permian basin %d of which Texas %d (%.0f%% of Texas), "
                  "Eagle Ford %d, Haynesville %d, Barnett %d" % (iso[-1], series["us"][-1], tx, series["txOil"][-1],
                                                                   series["txGas"][-1], pe, ptx, 100.0 * ptx / tx,
                                                                   series["eagleFord"][-1], series["haynesville"][-1],
                                                                   series["barnett"][-1]))
    check("rigs", "Texas rigs over the series: min %d, max %d; US max %d" % (min(series["txTotal"]), max(series["txTotal"]),
                                                                           max(series["us"])))
    lo = min(range(len(iso)), key=lambda i: series["us"][i])
    check("rigs", "U.S. low of the series: %d rigs in the week of %s (Baker Hughes' record low is widely reported as 244, "
                  "mid-August 2020)" % (series["us"][lo], iso[lo]))
    srcs = []
    for label, fname, _o, _a, _d, weekly in notes:
        origin = [n for n in files if n[0] == label][0][2]
        srcs.append("'%s' (file %s; %s)" % (label, fname, origin))
    src = ("Baker Hughes North America Rotary Rig Count, workbooks from the page %s, sheet 'NAM Weekly' (one row per "
           "county/basin/drill-for/trajectory, summed per publish date; the dates are Fridays, or Tuesday to Thursday in holiday weeks): %s. %s Series end at the newest week held in "
           "the newest workbook (%s)%s. permian = Baker Hughes Permian basin including southeastern New Mexico; "
           "permianTx = its Texas part; haynesville = basin count including Louisiana; us = all U.S. rigs; txOil/txGas "
           "exclude 'Miscellaneous' rigs."
           % (BH_PAGE, "; ".join(srcs),
              ("The Baker Hughes site returned HTTP 403 to scripted access, so the workbooks were read from the "
               "Internet Archive's public copies.") if how == "wayback" else "Downloaded directly from the Baker Hughes site.",
              iso[-1], "; later weekly workbooks are not archived" if how == "wayback" else ""))
    obj = {"asOf": as_of, "through": iso[-1], "weeks": iso}
    for k in ("txTotal", "txOil", "txGas", "permian", "permianTx", "eagleFord", "haynesville", "barnett", "us"):
        obj[k] = series[k]
    obj["src"] = src
    obj["unit"] = "rigs"
    write_json(out_dir, "series-rigs.json", obj)


# --------------------------------------------------------------------------------------------- item 2: taxes
TAX_FILE = "https://comptroller.texas.gov/transparency/revenue/watch/all-funds/data/all-funds-historical.xlsx"
SEVERANCE_PAGE = "https://comptroller.texas.gov/transparency/revenue/severance.php"
KEI_API = "https://data.texas.gov/resource/karz-jr5v.json"
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december"]


def parse_tax(path, as_of):
    """-> (months, oil, gas in USD thousand, fiscal-year check lines) from the All Funds historical workbook."""
    z, ss, sheets = xlsx_open(path)
    cells = {}                                  # "YYYY-MM" -> (oil, gas)
    fy_lines = []
    fy_sum = collections.defaultdict(lambda: [0.0, 0.0])
    for name, p in sorted(sheets.items()):
        m = re.fullmatch(r"FY\s*(\d{4})", name.strip())
        if not m or int(m.group(1)) < 2019:
            continue
        fy = int(m.group(1))
        header = oil = gas = None
        for _r, v in iter_rows(z, p, ss):
            lab = v.get(0)
            if not isinstance(lab, str):
                continue
            low = lab.strip().lower()
            if header is None and low == "tax category":
                header = {i: str(x).strip().lower() for i, x in v.items() if isinstance(x, str)}
                continue
            if header is None:
                continue
            if oil is None and re.match(r"(crude )?oil production tax", low):
                oil = v
            elif gas is None and low.startswith("natural gas production tax"):
                gas = v
            if oil is not None and gas is not None:
                break
        if oil is None or gas is None:
            raise RuntimeError("%s: oil or gas production tax row not found" % name)
        total_col = [i for i, x in header.items() if x == "total"][0]
        fsum = [0.0, 0.0]
        for i, mname in header.items():
            if mname not in MONTH_NAMES:
                continue
            mon = MONTH_NAMES.index(mname) + 1
            year = fy - 1 if mon >= 9 else fy
            o, g = oil.get(i), gas.get(i)
            if isinstance(o, float) and isinstance(g, float):
                cells["%04d-%02d" % (year, mon)] = (o, g)
                fsum[0] += o
                fsum[1] += g
        to, tg = oil.get(total_col), gas.get(total_col)
        if isinstance(to, float) and isinstance(tg, float):
            fy_lines.append((fy, abs(fsum[0] - to), abs(fsum[1] - tg)))
        fy_sum[fy] = fsum
    cur = as_of[:7]
    months = sorted(k for k in cells if "2019-01" <= k < cur)
    return months, [cells[k][0] for k in months], [cells[k][1] for k in months], fy_lines, cells


def run_tax(out_dir, as_of):
    path, headers = download(TAX_FILE, "tx_comptroller_allfunds_hist", "all-funds-historical.xlsx")
    months, oil, gas, fy_lines, cells = parse_tax(path, as_of)
    if len(months) < 60:
        raise RuntimeError("only %d months parsed" % len(months))
    check("tax", "%d months %s..%s (workbook last modified %s); latest month oil %.1f, gas %.1f USD million"
          % (len(months), months[0], months[-1], headers.get("Last-Modified", "?"), oil[-1] / 1000.0, gas[-1] / 1000.0))
    worst = max((max(a, b) for _fy, a, b in fy_lines), default=0.0)
    check("tax", "fiscal-year totals in the workbook vs sum of monthly cells: largest gap %.2f USD thousand over %d years"
          % (worst, len(fy_lines)))
    recent = [(m, o / 1000.0, g / 1000.0) for m, o, g in zip(months, oil, gas)][-24:]
    check("tax", "last 24 months: oil %.0f..%.0f, gas %.0f..%.0f USD million per month"
          % (min(r[1] for r in recent), max(r[1] for r in recent), min(r[2] for r in recent), max(r[2] for r in recent)))
    neg = [(m, o / 1000.0, g / 1000.0) for m, o, g in zip(months, oil, gas) if o < 0 or g < 0]
    if neg:
        check("tax", "months with negative net collections (refunds exceeded receipts): "
              + "; ".join("%s oil %.1f gas %.1f" % x for x in neg))
    # independent anchor 1: the Comptroller's severance tax page states a fiscal-year total
    try:
        p2, _ = download(SEVERANCE_PAGE, "tx_comptroller_severance_page", "severance.html")
        t = text_of(read_text(p2))
        m = re.search(r"FY\s*(\d{4}) collections totaled \$([\d.]+) billion", t)
        if m:
            fy, stated = int(m.group(1)), float(m.group(2))
            ks = ["%04d-%02d" % (fy - 1, mm) for mm in (9, 10, 11, 12)] + ["%04d-%02d" % (fy, mm) for mm in range(1, 9)]
            mine = sum(cells[k][0] + cells[k][1] for k in ks if k in cells) / 1e6
            check("tax", "severance page says FY %d collections totaled $%.2f billion; oil+gas production tax in the "
                         "workbook for Sep %d..Aug %d = $%.2f billion" % (fy, stated, fy - 1, fy, mine))
    except Refused as e:
        check("tax", "severance page comparison skipped (%s)" % e)
    # independent anchor 2: tax versus the gross value of production (Key Economic Indicators, data.texas.gov)
    try:
        q = urllib.parse.urlencode({
            "$select": "year,month,gross_value_crude_oil_production", "$limit": "400",
            "$where": "gross_value_crude_oil_production IS NOT NULL", "$order": "year DESC, month DESC"})
        p3, _ = download(KEI_API + "?" + q, "tx_comptroller_kei_gross_value", "kei.json")
        gv = {}
        for r in json.load(open(p3, encoding="utf-8")):
            gv["%04d-%02d" % (int(r["year"]), int(r["month"]))] = float(r["gross_value_crude_oil_production"])  # USD million
        ratios = []
        for m, o in zip(months, oil):
            y, mo = int(m[:4]), int(m[5:])
            mo -= 2
            if mo < 1:
                mo += 12
                y -= 1
            k = "%04d-%02d" % (y, mo)
            if k in gv and m >= "2022-01":
                ratios.append(o / 1000.0 / gv[k])
        if ratios:
            check("tax", "oil production tax collected in month m / gross value of crude produced in month m-2 "
                         "(Key Economic Indicators): median %.2f%% over %d months, range %.2f%%..%.2f%% "
                         "(statutory rate 4.6%%)" % (100 * statistics.median(ratios), len(ratios), 100 * min(ratios),
                                                      100 * max(ratios)))
    except (Refused, ValueError, KeyError) as e:
        check("tax", "gross-value comparison skipped (%s)" % e)
    src = ("Texas Comptroller of Public Accounts, Monthly State Revenue Watch, 'All Funds Historical data (XLSX)' %s "
           "(sheets FY 2019 to FY 2026, rows 'Oil Production Tax' and 'Natural Gas Production Tax', amounts in USD "
           "thousand converted to USD million; file last modified %s). Cash basis by month of collection, net of "
           "refunds (production is taxed about two months after the production month). Latest month in the file: %s; "
           "later months are not published yet."
           % (TAX_FILE, headers.get("Last-Modified", "?"), months[-1]))
    obj = {"asOf": as_of, "months": months, "oilTax": [round(x / 1000.0, 3) for x in oil],
           "gasTax": [round(x / 1000.0, 3) for x in gas], "src": src, "unit": "USD millions"}
    write_json(out_dir, "series-tax.json", obj)


# --------------------------------------------------------------------------------------------- item 3: minerals
PVS_INDEX = "https://comptroller.texas.gov/taxes/property-tax/pvs/"
COMPTROLLER = "https://comptroller.texas.gov"


def run_minerals(out_dir, as_of, counties):
    lookup = make_name_lookup(counties)
    # Comptroller county code = 1-based position in the alphabetical list of the 254 names (Dallas 57, Harris 101,
    # Madison 154 ... McMullen 162: strictly alphabetical, so not 2*code-1 from FIPS order, which puts Mc* before Ma*)
    comp_code = {f: i + 1 for i, (f, _n) in enumerate(sorted(counties.items(), key=lambda kv: norm_name(kv[1])))}
    idx_path, _ = download(PVS_INDEX, "tx_pvs_index_page", "pvs.html")
    years = sorted({int(y) for y in re.findall(r"/taxes/property-tax/pvs/(\d{4})f/index\.php", read_text(idx_path))},
                   reverse=True)
    if not years:
        raise RuntimeError("no final PVS years listed on %s" % PVS_INDEX)
    year = detail_url = summary_url = state_url = None
    for y in years:
        pg, _ = download("%s%df/index.php" % (PVS_INDEX, y), "tx_pvs_%d_final_page" % y, "final.html")
        t = read_text(pg)
        d = re.search(r'href="([^"]*%d-final-isd-worksheet-export-detail\.xlsx)"' % y, t)
        if d:
            s = re.search(r'href="([^"]*%d-final-isd-worksheet-export-summary\.xlsx)"' % y, t)
            st = re.search(r'href="(/auto-data/PT2/PVS/%dF/ALL\w+\.php)"' % y, t, re.I)
            year, detail_url = y, urllib.parse.urljoin(COMPTROLLER, d.group(1))
            summary_url = urllib.parse.urljoin(COMPTROLLER, s.group(1)) if s else None
            state_url = urllib.parse.urljoin(COMPTROLLER, st.group(1)) if st else None
            break
    if not year:
        raise RuntimeError("no final PVS worksheet export found for %s" % years[:3])
    log("  minerals: latest final PVS year %d" % year)
    dpath, _ = download(detail_url, "tx_pvs_%d_final_worksheet_detail" % year)
    z, ss, sheets = xlsx_open(dpath)
    sheet = list(sheets.values())[0]
    hdr = None
    by_fips = collections.defaultdict(lambda: [0.0, 0.0, 0.0])    # local, ptad, assigned (category G)
    unmapped, code_mismatch, nrows, versions = set(), 0, 0, collections.Counter()
    for _r, v in iter_rows(z, sheet, ss):
        if hdr is None:
            if str(v.get(0, "")).strip().upper() == "CAD ID":
                hdr = {str(x).strip().upper(): k for k, x in v.items() if isinstance(x, str)}
            continue
        if not isinstance(v.get(0), float):
            continue
        cname = str(v.get(hdr["COUNTY NAME"], ""))
        f = lookup(cname)
        if f is None:
            unmapped.add(cname)
            continue
        versions[str(v.get(hdr["VERSION TYPE"], ""))] += 1
        nrows += 1
        a = by_fips[f]
        a[0] += v.get(hdr["LOCL G"], 0.0) or 0.0
        a[1] += v.get(hdr["PTAD G"], 0.0) or 0.0
        a[2] += v.get(hdr["ASGN G"], 0.0) or 0.0
        m = re.fullmatch(r"\d{3}-\d{3}-\d{2}-\d{3}-(\d{3})", str(v.get(hdr["SPLIT ID"], "")))
        if m and int(m.group(1)) != comp_code[f]:         # last group of SPLIT ID = Comptroller county code
            code_mismatch += 1
    if unmapped:
        raise RuntimeError("county names not matched to FIPS: %s" % sorted(unmapped))
    missing = sorted(set(counties) - set(by_fips))
    check("minerals", "%d ISD-by-county rows (%s) cover %d of 254 counties%s; county-code check (last group of SPLIT ID vs "
                      "alphabetical position of the county) mismatches: %d" % (nrows, dict(versions), len(by_fips),
                                                           (", missing " + str(missing)) if missing else "", code_mismatch))
    tot = [sum(a[i] for a in by_fips.values()) for i in range(3)]
    # state totals as printed by the Comptroller's summary worksheet
    if state_url:
        sp, _ = download(state_url, "tx_pvs_%d_final_state_summary" % year, "state_summary.html")
        m = re.search(r"G - ALL MINERALS</th>\s*<td>([\d,]+)</td>\s*<td>([\d,]+)</td>\s*<td>([\d,]+)</td>", read_text(sp))
        if m:
            printed = [float(x.replace(",", "")) for x in m.groups()]
            check("minerals", "state total, category G, local / PTAD / assigned: ours %s vs Comptroller summary worksheet %s"
                              " (differences %s)" % ([int(x) for x in tot], [int(x) for x in printed],
                                                     [int(a - b) for a, b in zip(tot, printed)]))
    # second aggregation from the ISD-level summary workbook
    if summary_url:
        spath, _ = download(summary_url, "tx_pvs_%d_final_worksheet_summary" % year)
        z2, ss2, sh2 = xlsx_open(spath)
        h2, s2, n2 = None, 0.0, 0
        for _r, v in iter_rows(z2, list(sh2.values())[0], ss2):
            if h2 is None:
                if str(v.get(0, "")).strip().upper() in ("TU ID", "CAD ID"):
                    h2 = {str(x).strip().upper(): k for k, x in v.items() if isinstance(x, str)}
                continue
            if isinstance(v.get(0), str) and v.get(0).strip() and "ASGN G" in h2 and isinstance(v.get(h2["ASGN G"]), float):
                s2 += v.get(h2["ASGN G"], 0.0) or 0.0
                n2 += 1
        check("minerals", "ISD summary workbook: %d districts, category G assigned %d vs county sum %d" % (n2, int(s2), int(tot[2])))
    ranked = sorted(by_fips.items(), key=lambda kv: -kv[1][2])
    rank = {counties[f]: i + 1 for i, (f, _a) in enumerate(ranked)}
    check("minerals", "top counties by category G assigned value: " + ", ".join(
        "%s $%.1fB" % (counties[f], a[2] / 1e9) for f, a in ranked[:10]))
    check("minerals", "ranks: Midland %d, Reeves %d, Loving %d, Karnes %d, Martin %d, Upton %d; counties with zero "
                      "category G value: %d" % (rank["Midland"], rank["Reeves"], rank["Loving"], rank["Karnes"],
                                               rank["Martin"], rank["Upton"], sum(1 for a in by_fips.values() if a[2] <= 0)))
    src = ("Texas Comptroller of Public Accounts, School District Property Value Study %d final findings (%s%df/index.php): "
           "'%d ISD Worksheet Export Detail' (%s), column 'ASGN G' = value assigned to category G (oil, gas and other "
           "mineral reserves) summed over the ISD-by-county rows of each county. The category is before exemptions; "
           "local roll value (LOCL G) and the Comptroller's own estimate (PTAD G) differ from it by less than 0.2%% "
           "statewide. Counties without category G value are listed with v 0."
           % (year, PVS_INDEX, year, year, detail_url))
    obj = {"year": year, "asOf": as_of, "src": src, "unit": "USD",
           "counties": {f: {"v": int(round(by_fips[f][2])) if f in by_fips else 0} for f in sorted(counties)}}
    write_json(out_dir, "county-minerals.json", obj)


# --------------------------------------------------------------------------------------------- item 4: basins
EIA_DPR_XLSX = "https://www.eia.gov/petroleum/drilling/xls/dpr-data.xlsx"
EIA_DPR_METHOD = "https://www.eia.gov/petroleum/drilling/pdf/dpr_methodology.pdf"
RRC_FORMATION = "https://www.rrc.texas.gov/oil-and-gas/major-oil-and-gas-formations/%s/"
BASIN_DEFS = [   # id, name, EIA DPR region (or None), RRC page slug
    ("permian", "Permian Basin", "Permian Region", "permian-basin"),
    ("eagleford", "Eagle Ford", "Eagle Ford Region", "eagle-ford-shale"),
    ("haynesville", "Haynesville (East Texas)", "Haynesville Region", "haynesville-bossier-shale"),
    ("barnett", "Barnett", None, "barnett-shale"),
]


def rrc_affected_counties(page_html, lookup):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page_html, flags=re.S | re.I)
    lines = [re.sub(r"\s+", " ", html.unescape(x)).strip() for x in re.sub(r"<[^>]+>", "\n", t).split("\n")]
    lines = [x for x in lines if x]
    i = lines.index("Affected Counties")
    j = lines.index("Commissioners", i)
    names = lines[i + 1:j]
    fips = [lookup(n) for n in names]
    bad = [n for n, f in zip(names, fips) if f is None]
    if bad or not names:
        raise RuntimeError("RRC county names not matched: %s" % bad)
    return names, sorted(set(fips))


def run_basins(out_dir, as_of, counties):
    lookup = make_name_lookup(counties)
    xpath, xh = download(EIA_DPR_XLSX, "eia_dpr_data", "dpr-data.xlsx")
    z, ss, sheets = xlsx_open(xpath)
    eia = collections.defaultdict(set)
    other = collections.Counter()
    for r, v in iter_rows(z, sheets["RegionCounties"], ss):
        if r == 1:
            continue
        if v.get(0) != "TX":
            other[(v.get(0), v.get(4))] += 1
            continue
        cid = v.get(3)
        fips = ("%03d" % int(cid)) if isinstance(cid, float) else str(cid).strip().zfill(3)
        if fips not in counties or norm_name(counties[fips]) != norm_name(str(v.get(1))):
            raise RuntimeError("EIA county %s (%s) does not match counties.geo.json" % (v.get(1), fips))
        eia[v.get(4)].add(fips)
    basins, rrc_all, eia_all = [], {}, {}
    notes_amb = {}
    for bid, name, region, slug in BASIN_DEFS:
        page, _ = download(RRC_FORMATION % slug, "rrc_formation_" + slug, "page.html")
        rnames, rfips = rrc_affected_counties(read_text(page), lookup)
        rrc_all[bid] = set(rfips)
        if region:
            if region not in eia:
                raise RuntimeError("EIA region %s has no Texas rows" % region)
            efips = sorted(eia[region])
            eia_all[bid] = set(efips)
            only_e = sorted(set(efips) - set(rfips))
            only_r = sorted(set(rfips) - set(efips))
            nm = lambda lst: ", ".join(counties[f] for f in lst) or "none"
            extra = ""
            if bid == "permian":
                extra = (" EIA delineates its regions along county lines, not geology, so fringe counties on the "
                         "shelves and plateau edges are included.")
            non_tx = ", ".join("%d %s" % (n, s) for s, n in sorted((k[0], n) for k, n in other.items() if k[1] == region))
            note = ("Primary list: EIA Drilling Productivity Report '%s' (%d Texas counties; %s). RRC's page lists %d "
                    "counties (field `rrc`). Counties in only one of the two lists are ambiguous (field `ambiguous`): "
                    "EIA only: %s; RRC only: %s.%s"
                    % (region, len(efips),
                       ("the region also has %s counties outside Texas, not shown" % non_tx) if non_tx
                       else "no counties outside Texas", len(rfips), nm(only_e), nm(only_r), extra))
            basins.append({"id": bid, "name": name, "fips": efips, "rrc": rfips, "ambiguous": sorted(only_e + only_r),
                           "note": note})
            notes_amb[bid] = (only_e, only_r)
        else:
            note = ("Primary list: RRC 'Barnett Shale Information & Statistics' page, Affected Counties (%d; the field is "
                    "Newark, East (Barnett Shale)). The page says the play covers 'at least 18 counties' but lists %d "
                    "without marking which are core, so treat the edge counties of the list as ambiguous. EIA's "
                    "Drilling Productivity Report has no Barnett region." % (len(rfips), len(rfips)))
            basins.append({"id": bid, "name": name, "fips": rfips, "note": note})
    for b in basins:
        bad = [f for f in b["fips"] + b.get("rrc", []) if f not in counties]
        if bad:
            raise RuntimeError("%s: FIPS not in counties.geo.json: %s" % (b["id"], bad))
        check("basins", "%s: %d counties (primary)%s, all in counties.geo.json" % (
            b["id"], len(b["fips"]), (", %d in RRC list" % len(b["rrc"])) if "rrc" in b else ""))
    overlap = collections.Counter(f for b in basins for f in b["fips"])
    multi = sorted(counties[f] for f, n in overlap.items() if n > 1)
    check("basins", "counties in more than one primary list: %s" % (", ".join(multi) or "none"))
    # coverage of the permit counties
    cp_path = os.path.join(out_dir, "county-permits.json")
    if os.path.exists(cp_path):
        cp = json.load(open(cp_path, encoding="utf-8"))["counties"]
        tot = sum(c["p12"] for c in cp.values())
        prim = set(f for b in basins for f in b["fips"])
        both = prim | set(f for b in basins for f in b.get("rrc", []))
        cov = sum(c["p12"] for f, c in cp.items() if f in prim)
        cov2 = sum(c["p12"] for f, c in cp.items() if f in both)
        check("basins", "new-drill permits, last 12 months (county-permits.json): %d of %d (%.1f%%) are in primary-list "
                        "counties, %d (%.1f%%) in primary or RRC lists" % (cov, tot, 100.0 * cov / tot, cov2, 100.0 * cov2 / tot))
        top = sorted(cp.items(), key=lambda kv: -kv[1]["p12"])
        bname = {}
        for b in basins:
            for f in b["fips"]:
                bname.setdefault(f, b["id"])
        check("basins", "top 15 permit counties: " + ", ".join(
            "%s %d [%s]" % (counties[f], c["p12"], bname.get(f, "-")) for f, c in top[:15]))
        unc = [(counties[f], c["p12"]) for f, c in top if f not in both][:8]
        check("basins", "largest permit counties in no list: " + ", ".join("%s %d" % u for u in unc))
        top25 = [f for f, _c in top[:25]]
        check("basins", "top 25 permit counties covered by a primary list: %d of 25" % sum(1 for f in top25 if f in prim))
    # Baker Hughes' own basin labels for Texas counties with rigs (only when the rigs item ran in this process)
    if BH_TX_COUNTIES:
        for b in basins:
            names = BH_TX_COUNTIES.get(b["id"] if b["id"] != "eagleford" else "eagleFord", set())
            fl = {lookup(n) for n in names}
            if None in fl:
                fl.discard(None)
            outside = sorted(counties[f] for f in fl if f not in set(b["fips"]))
            check("basins", "Baker Hughes labels %d Texas counties with rigs as %s; outside our primary list: %s"
                  % (len(fl), b["id"], ", ".join(outside) or "none"))
    src = ("EIA Drilling Productivity Report, 'RegionCounties' sheet of %s (Permian, Eagle Ford and Haynesville regions, "
           "Texas rows; regions are 'delineated along county lines', see %s; file last modified %s) and Railroad Commission "
           "of Texas 'Major Oil and Gas Formations' pages, section 'Affected Counties': %s. Barnett has no EIA region, so "
           "its list is the RRC's."
           % (EIA_DPR_XLSX, EIA_DPR_METHOD, xh.get("Last-Modified", "?"),
              "; ".join(RRC_FORMATION % d[3] for d in BASIN_DEFS)))
    write_json(out_dir, "basins.json", {"asOf": as_of, "src": src, "basins": basins})


# --------------------------------------------------------------------------------------------- main
def main():
    global DL_ROOT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default="rigs,tax,minerals,basins")
    ap.add_argument("--as-of", default=AS_OF)
    ap.add_argument("--dl-root", default=DEFAULT_DL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    DL_ROOT = a.dl_root
    os.makedirs(DL_ROOT, exist_ok=True)
    counties = load_counties(a.out)
    if len(counties) != 254:
        raise SystemExit("counties.geo.json has %d counties, expected 254" % len(counties))
    want = [x.strip() for x in a.only.split(",") if x.strip()]
    jobs = {"rigs": lambda: run_rigs(a.out, a.as_of), "tax": lambda: run_tax(a.out, a.as_of),
            "minerals": lambda: run_minerals(a.out, a.as_of, counties), "basins": lambda: run_basins(a.out, a.as_of, counties)}
    done, skipped = [], []
    for name in ("rigs", "tax", "minerals", "basins"):       # basins last so it can use the rigs item's county labels
        if name not in want:
            continue
        log("== %s" % name)
        t0 = time.time()
        try:
            jobs[name]()
            done.append(name)
        except Exception as e:  # each item is independent and best effort
            skipped.append(name)
            log("  SKIPPED %s: %s: %s" % (name, type(e).__name__, str(e)[:300]))
        log("  (%s took %.0fs)" % (name, time.time() - t0))
    log("== downloads (%d files under %s)" % (len(DOWNLOADS), DL_ROOT))
    for folder, fname, size, url in DOWNLOADS:
        log("  %-44s %-52s %10d  %s" % (folder, fname[:52], size, url))
    log("== done: %s; skipped: %s" % (", ".join(done) or "none", ", ".join(skipped) or "none"))
    return 0 if done else 2


if __name__ == "__main__":
    sys.exit(main())
