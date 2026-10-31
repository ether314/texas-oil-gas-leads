#!/usr/bin/env python3
"""D7 producer: the daily Railroad Commission report for the leads site.

Reads the RRC data sets page, finds every dataset it lists as nightly or twice daily, and captures what each one
published. Writes into site/public/data/daily/ (spec: site/pipeline/NOTES_D7.md):

  YYYY-MM-DD.json     one report per day (Central time): what each nightly dataset held, plus parsed figures for the
                      three text datasets (permits, pending applications, completions) and the size of the three
                      image packs. At most 92 days are kept.
  index.json          one small row per report day: the numbers the calendar and the trend charts draw
  permits-series.json permits issued per calendar day (all types, new-drill, new-drill horizontal), 92 days

Inputs are public RRC files, only parsed, never executed (run with `python3 -I`):
  permits      Drilling Permit Master and Trailer, daily file (daf420.dat): the current month's permits, 510-char
               record 02 per permit, layout manual OGA049M. Month-end files (End of Month share) rebuild earlier days.
  pending      Drilling Permits Pending Approval: dp_*_pending_<yyyymmddhhmmss>.txt, `}`-delimited, two sets a day.
  completions  Completion Information in Data Format: <MM-DD-YYYY>.zip of packetData_*.dat, `{`-delimited.
  images       W-1 images, directional surveys, completion images: only the share listing is read (names, sizes).

  python3 -I site/pipeline/d7_daily.py [--date YYYY-MM-DD] [--backfill N] [--out DIR] [--dl DIR] [--keep 92]
  python3 -I site/pipeline/d7_daily.py --check [--out DIR]     only reload and check what is already there

With no options: capture today's report (Central time). --backfill N also rebuilds any missing day of the last N days
from the RRC file history (a rebuilt day says so: kind "reconstructed"). The pending queue and the page's catalog check
have no history, so a rebuilt day has no catalog check. Each dataset is independent: a failure marks that dataset and
the rest still run; an existing day file is replaced only by a run that captured something.

Privacy: operators are named only when they are corporations, LLCs or limited partnerships (the list in
operators.json). Lease names, well numbers and everything about individuals are left out.
"""
import argparse
import collections
import concurrent.futures
import html.parser
import json
import os
import re
import statistics
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path; rrc_share.py sits next to this file
from rrc_share import Session, Share, ShareError  # noqa: E402

DATA_PAGE = "https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/"
UA = "Mozilla/5.0 (research script)"
KEEP_DAYS = 92
EOM_GUID = "f5dfea9c-bb39-4a5e-a44e-fb522e088cba"  # Drilling Permit Master and Trailer, End of Month files
DEFAULT_OUT = os.path.join(SITE, "public", "data", "daily")
BUDGET_BYTES = {"index.json": 40_000, "permits-series.json": 20_000, "day": 60_000}

# the six datasets the RRC page lists as nightly or twice daily (matched by description, GUID read from the page)
DATASETS = [
    {"id": "permits", "title": "Drilling permits", "match": "Drilling Permit Master and Trailer - Daily File",
     "guid": "5f07cc72-2e79-4df8-ade1-9aeb792e03fc"},
    {"id": "pending", "title": "Permits pending approval", "match": "Drilling Permits Pending Approval",
     "guid": "0ad92a65-4212-49a1-98a7-d667a55fb497"},
    {"id": "completions", "title": "Completion data", "match": "Completion Information in Data Format",
     "guid": "ed7ab066-879f-40b6-8144-2ae4b6810c04"},
    {"id": "w1images", "title": "W-1 permit images", "match": "Drilling Permit (W1) Imaged Files",
     "guid": "f11363bb-8120-4e8c-bbc0-a253ec0a85d4"},
    {"id": "dirsurveys", "title": "Directional surveys", "match": "Directional Survey Applications",
     "guid": "01769aa7-dee8-4121-bb25-e7557307f6bd"},
    {"id": "complimages", "title": "Completion images", "match": "Imaged Completion Files",
     "guid": "8e91acb8-69cc-4d57-ad72-c7f7d5a7675e"},
]
IMAGE_LAG = {"w1images": 1, "dirsurveys": 1, "complimages": 0}  # days between a pack's day and the day its file is out
# monthly files the site is built from: read for context only (is a newer file waiting?)
MONTHLY = [
    {"id": "permit-master", "title": "Drilling Permit Master and Trailer", "guid": "beeeab0c-7d07-4111-af88-783c93677b2c",
     "file": "daf802.txt.gz", "site": "permits"},
    {"id": "p5", "title": "P-5 Organization", "guid": "04652169-eed6-4396-9019-2e270e790f6c", "file": "orf850.txt.gz", "site": "p5"},
    {"id": "pdq", "title": "Production Data Query dump", "guid": "1f5ddb8d-329a-4459-b7f8-177b4f5ee60d", "file": "PDQ_DSV.zip", "site": None},
]

DISTRICT = {"01": "01", "02": "02", "03": "03", "04": "04", "05": "05", "06": "06", "07": "6E", "08": "7B", "09": "7C",
            "10": "08", "11": "8A", "12": "8B", "13": "09", "14": "10"}  # OGA049M: the permit file stores internal codes
VALID_FIPS = {"%03d" % n for n in range(1, 508, 2)}
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 25.5, 36.6, -106.8, -93.4
RX14 = re.compile(rb"^14:?\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")
PURPOSE = {"1": "Initial potential", "2": "Retest", "3": "Reclass oil to gas", "4": "Reclass gas to oil",
           "5": "Reclass injection to producing", "6": "Reclass producing to injection", "7": "Well record only"}
COMPLETION_TYPE = {"1": "New well", "2": "Deepening", "3": "Plug back", "4": "Sidetrack", "5": "Horizontal", "6": "Reentry", "7": "Other"}
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
DAY_FILE = re.compile(r"\d{4}-\d\d-\d\d\.json")


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------------------------------------ small helpers

def central_now():
    """Now in America/Chicago. Falls back to the US daylight-saving rule when the tz database is missing."""
    utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/Chicago"))
    except Exception:  # noqa: BLE001 - any failure to load tz data
        mar = date(utc.year, 3, 8)
        mar += timedelta(days=(6 - mar.weekday()) % 7)  # second Sunday of March
        nov = date(utc.year, 11, 1)
        nov += timedelta(days=(6 - nov.weekday()) % 7)  # first Sunday of November
        start = datetime(mar.year, mar.month, mar.day, 8, tzinfo=timezone.utc)  # 2:00 CST
        end = datetime(nov.year, nov.month, nov.day, 7, tzinfo=timezone.utc)  # 2:00 CDT
        return utc.astimezone(timezone(timedelta(hours=-5 if start <= utc < end else -6)))


def pdate(text):
    """YYYYMMDD -> date, or None (the permit file carries zeros and typo years)."""
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        return None
    try:
        d = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return d if 1990 <= d.year <= 2100 else None


def mdy(text):
    """MM/DD/YYYY -> date or None."""
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def oracle_date(text):
    """'30-OCT-26 10.44.57.128000 AM' -> datetime or None."""
    m = re.match(r"(\d\d)-([A-Z]{3})-(\d\d) (\d\d)\.(\d\d)\.(\d\d)", text.strip())
    if not m or m.group(2) not in MONTHS:
        return None
    h = int(m.group(4)) % 12 + (12 if text.strip().upper().endswith("PM") else 0)
    return datetime(2000 + int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), h, int(m.group(5)), int(m.group(6)))


def top(counter, n):
    return [[k, v] for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]]


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class Lookups:
    """County names and the operators that may be named, both from the committed site data."""

    def __init__(self):
        data = os.path.join(SITE, "public", "data")
        geo = read_json(os.path.join(data, "counties.geo.json"), {"features": []})
        self.county = {f["properties"]["f"]: f["properties"]["n"] for f in geo["features"]}
        ops = read_json(os.path.join(data, "operators.json"), {"rows": []})
        self.operator = {r[1]: r[2] for r in ops["rows"]}
        self.meta = read_json(os.path.join(data, "meta.json"), {})

    def county_name(self, fips):
        return self.county.get(fips) or ("Offshore" if fips and fips not in VALID_FIPS else "Unknown")

    def op(self, num):
        return [num, self.operator.get(num)]


# ------------------------------------------------------------------------------------------------ the page

class CatalogParser(html.parser.HTMLParser):
    """Rows of the RRC data sets tables: description, the Updated text and the download links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.caption, self.in_caption, self.row, self.cell = [], "", False, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "caption":
            self.in_caption, self.caption = True, ""
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"label": a.get("data-label", ""), "text": "", "links": []}
        elif tag == "a" and self.cell is not None and a.get("href"):
            self.cell["links"].append(a["href"])

    def handle_endtag(self, tag):
        if tag == "caption":
            self.in_caption = False
        elif tag in ("td", "th") and self.cell is not None:
            self.cell["text"] = " ".join(self.cell["text"].split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            by = {c["label"]: c for c in self.row}
            if "Updated" in by and by.get("Data Set Description", {}).get("text") not in (None, "Data Set Description"):
                self.rows.append({"section": " ".join(self.caption.split()), "desc": by["Data Set Description"]["text"],
                                  "updated": by["Updated"]["text"], "links": by.get("Download", {}).get("links", [])})
            self.row = None

    def handle_data(self, data):
        if self.in_caption:
            self.caption += data
        if self.cell is not None:
            self.cell["text"] += data


def fetch_page(url):
    last = None
    for i in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 2 * i)
    raise RuntimeError("could not read %s: %r" % (url, last))


def read_catalog():
    """Every row of the RRC data sets page, and the ones it lists as nightly or twice daily."""
    p = CatalogParser()
    p.feed(fetch_page(DATA_PAGE))
    nightly = [r for r in p.rows if re.search(r"nightly|twice daily|\bdaily\b", r["updated"], re.I)]
    return p.rows, nightly


def guid_of(links):
    for href in links:
        m = re.search(r"/link/([0-9a-f-]{36})", href)
        if m:
            return m.group(1)
    return None


# ------------------------------------------------------------------------------------------------ permits

def read_daf(path):
    """permit number -> first 02 record's fields (+ amendment days, record count, surface coordinates)."""
    with open(path, "rb") as f:
        data = f.read()
    out, cur = {}, None
    for rec in data.split(b"\r\n"):
        kind = rec[:2]
        if kind == b"01":
            cur = rec[2:9].decode("ascii") if len(rec) == 212 and rec[2:9].isdigit() else None
        elif kind == b"02" and len(rec) == 510:
            L = rec.decode("latin-1")
            num = L[2:9]
            if not num.isdigit():
                continue
            amended, p = pdate(L[137:145]), out.get(num)
            if p is None:
                issued = pdate(L[129:137])
                if issued is None:
                    continue
                td = L[54:59]
                p = out[num] = {"n": num, "county": L[11:14], "district": DISTRICT.get(L[46:48], L[46:48]), "depth": int(td) if td.isdigit() else 0,
                                "op": L[59:65], "type": L[65:67], "received": pdate(L[121:129]), "issued": issued,
                                "horizontal": L[493] == "Y", "directional": L[481] == "Y", "amended": set(), "located": False}
            if amended:
                p["amended"].add(amended)
        elif kind == b"14" and cur in out:
            m = RX14.match(rec)
            if m and LON_MIN <= float(m.group(1)) <= LON_MAX and LAT_MIN <= float(m.group(2)) <= LAT_MAX:
                out[cur]["located"] = True
    return out


def kind_of(p):
    return "H" if p["horizontal"] else "D" if p["directional"] else "V"


def day_series(perms):
    """{day: [all types, new-drill, new-drill horizontal]} over the permits' issue dates."""
    out = collections.defaultdict(lambda: [0, 0, 0])
    for p in perms.values():
        row = out[p["issued"]]
        row[0] += 1
        if p["type"] == "01":
            row[1] += 1
            row[2] += 1 if p["horizontal"] else 0
    return out


def permits_section(perms, day, lk):
    """Everything the report says about the permits issued on `day`."""
    issued = [p for p in perms.values() if p["issued"] == day]
    new = [p for p in issued if p["type"] == "01"]
    depths = [p["depth"] for p in new if p["depth"] > 0]
    wait = sorted((p["issued"] - p["received"]).days for p in new if p["received"] and p["received"] <= p["issued"])
    ops = collections.Counter(p["op"] for p in new)
    cnt = collections.Counter(p["county"] for p in new)
    rows = sorted(new, key=lambda p: (-ops[p["op"]], p["op"], p["n"]))[:200]
    return {
        "day": day.isoformat(), "total": len(issued), "newDrill": len(new),
        "types": top(collections.Counter(p["type"] for p in issued), 8),
        "horizontal": sum(p["horizontal"] for p in new), "directional": sum(p["directional"] and not p["horizontal"] for p in new),
        "located": sum(p["located"] for p in new),
        "depth": {"median": int(statistics.median(depths)), "max": max(depths), "mean": int(sum(depths) / len(depths))} if depths else None,
        "wait": {"median": statistics.median(wait), "max": wait[-1]} if wait else None,
        "amended": sum(1 for p in perms.values() if day in p["amended"] and p["issued"] != day),
        "counties": [[k, lk.county_name(k), n] for k, n in top(cnt, 14)], "countyCount": len(cnt),
        "districts": top(collections.Counter(p["district"] for p in new), 14),
        "operators": [lk.op(k) + [n] for k, n in top(ops, 12)], "operatorCount": len(ops),
        "namedShare": round(sum(n for k, n in ops.items() if k in lk.operator) / len(new), 3) if new else None,
        "rows": [[p["n"], p["county"], p["district"], p["op"], lk.operator.get(p["op"]), p["depth"], kind_of(p)] for p in rows],
    }


def permits_job(ctx):
    """Download the current daf420.dat (and month-end files when past days are rebuilt); return the permits and the
    day ranges the files cover."""
    sess = Session()
    sh = Share(ctx["guid"]["permits"], sess)
    sh.open()
    cur = next((r for r in sh.newest(8) if r["name"] == "daf420.dat"), None)
    if not cur:
        raise ShareError("daf420.dat is not on the share")
    perms = read_daf(sh.download("daf420.dat", os.path.join(ctx["dl"], "permits-%s" % ctx["R"])))
    latest = max((p["issued"] for p in perms.values() if p["issued"] <= ctx["R"]), default=None)
    covered = [(latest.replace(day=1), latest)] if latest else []
    retries = 0
    if len(ctx["dates"]) > 1 and latest:  # rebuilding past days: the month-end files hold each earlier month
        eom = Share(EOM_GUID, Session())
        eom.open()
        listing = {r["name"]: r for r in eom.newest(30)}
        lo = ctx["dates"][0] - timedelta(days=1)
        y, m = lo.year, lo.month
        while (y, m) < (latest.year, latest.month):
            last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            name = "daf420.dat.%02d-%02d-%04d" % (last.month, last.day, last.year)
            if name in listing:
                more = read_daf(eom.download(name, os.path.join(ctx["dl"], "permits-eom-%04d-%02d" % (y, m))))
                for k, v in more.items():
                    perms.setdefault(k, v)  # the newer file wins
                covered.append((date(y, m, 1), last))
            else:
                log("permits: %s is not in the End of Month share, so that month is not rebuilt" % name)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        retries += eom.s.retries
    return {"perms": perms, "series": day_series(perms), "file": cur, "files": sh.total, "covered": covered, "retries": retries + sess.retries}


# ------------------------------------------------------------------------------------------------ pending

def read_delimited(path, delim):
    """Rows (dicts) of an RRC `}`-delimited export. The header may wrap mid-word at 750 characters; it ends at a blank
    line or at the first line that starts with a quote (data rows do). A data row is complete once it holds as many
    delimiters as the header."""
    with open(path, "rb") as f:
        lines = f.read().decode("latin-1").split("\n")
    i, header = 0, ""
    while i < len(lines) and lines[i].strip() and not lines[i].startswith('"'):
        header += lines[i].rstrip("\r")
        i += 1
    cols = [c.strip() for c in header.rstrip(delim).split(delim)]
    rows, buf = [], ""
    for line in lines[i:]:
        buf += line.rstrip("\r")
        if buf and buf.count(delim) >= len(cols) - 1:
            rows.append(dict(zip(cols, [x.strip().strip('"').strip() for x in buf.split(delim)])))
            buf = ""
    return rows


def pending_sets(rows):
    """Group a share listing into report sets: {(date, 'am'|'pm'): {kind: row}}. The time in the name is Central."""
    sets = collections.defaultdict(dict)
    for r in rows:
        m = re.fullmatch(r"dp_(drilling_permit|wellbore)_pending_(\d{8})(\d{2})\d{4}\.txt", r["name"])
        if m:
            sets[(datetime.strptime(m.group(2), "%Y%m%d").date(), "am" if int(m.group(3)) < 14 else "pm")][m.group(1)] = r
    return sets


def pending_section(day, parts, lk):
    """parts: [(label, set time, permit rows, wellbore rows)] for one day. Each set holds the W-1s submitted since the
    previous run that are still waiting for approval."""
    seen, apps, sets = set(), [], []
    for label, at, prm, wb in parts:
        county = {w.get("UNIVERSAL_DOC_NO"): w.get("COUNTY_CODE", "") for w in wb}
        n = 0
        for p in prm:
            uid = p.get("UNIVERSAL_DOC_NO")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            n += 1
            td = p.get("TOTAL_DEPTH", "")
            apps.append({"op": p.get("OPERATOR_NUMBER", ""), "district": p.get("DISTRICT", ""), "county": county.get(uid, ""),
                         "depth": int(td) if td.isdigit() else 0,
                         "kind": "H" if p.get("DEFAULT_HORIZANTAL") == "Y" else "D" if p.get("DEFAULT_DIRECTIONAL") == "Y" else "V",
                         "expedite": p.get("EXPEDITE_FLAG") == "Y", "amend": p.get("IS_AMENDMENT") == "Y",
                         "purpose": p.get("FILING_PURPOSE_CODE", ""), "submitted": oracle_date(p.get("SUBMIT_DATE", ""))})
        sets.append({"label": label, "at": at, "n": n})
    ops = collections.Counter(a["op"] for a in apps)
    depths = [a["depth"] for a in apps if a["depth"] > 0]
    subs = collections.Counter(a["submitted"].date().isoformat() for a in apps if a["submitted"])
    rows = sorted(apps, key=lambda a: (not a["expedite"], -ops[a["op"]], a["op"]))[:120]
    return {
        "day": day.isoformat(), "total": len(apps), "sets": sets, "expedite": sum(a["expedite"] for a in apps),
        "horizontal": sum(a["kind"] == "H" for a in apps), "directional": sum(a["kind"] == "D" for a in apps),
        "amendments": sum(a["amend"] for a in apps),
        "types": top(collections.Counter(a["purpose"] for a in apps), 6),
        "depth": {"median": int(statistics.median(depths)), "max": max(depths)} if depths else None,
        "districts": top(collections.Counter(a["district"] for a in apps), 14),
        "counties": [[k, lk.county_name(k), n] for k, n in top(collections.Counter(a["county"] for a in apps if a["county"]), 12)],
        "operators": [lk.op(k) + [n] for k, n in top(ops, 12)], "operatorCount": len(ops),
        "submitted": sorted(subs.items()),
        "rows": [[a["op"], lk.operator.get(a["op"]), a["county"], a["district"], a["depth"], a["kind"], 1 if a["expedite"] else 0] for a in rows],
    }


def pending_job(ctx):
    sess = Session()
    sh = Share(ctx["guid"]["pending"], sess)
    sh.open()
    listing = sh.newest(24 * (len(ctx["dates"]) + 2))
    by_day = collections.defaultdict(list)
    for (d, half), files in sorted(pending_sets(listing).items(), key=lambda kv: kv[0]):
        if len(files) == 2:  # a set still being copied has only some of its files: wait for the next run
            by_day[d].append((half, files))
    out = {}
    for day in ctx["dates"]:
        # a rebuilt day needs its own sets; today's report falls back to the newest complete set
        use = day if by_day.get(day) else (max((d for d in by_day if d <= day), default=None) if len(ctx["dates"]) == 1 else None)
        parts = []
        for half, files in by_day.get(use, []):
            stamp = files["drilling_permit"]["name"][-18:-4]
            dest = os.path.join(ctx["dl"], "pending-%s" % stamp)
            prm = read_delimited(sh.download(files["drilling_permit"]["name"], dest), "}")
            wb = read_delimited(sh.download(files["wellbore"]["name"], dest), "}")
            parts.append(("11 AM" if half == "am" else "5 PM", datetime.strptime(stamp, "%Y%m%d%H%M%S").isoformat(), prm, wb))
        if parts:
            out[day] = pending_section(use, parts, ctx["lk"])
    newest = next((r for r in listing if r["name"].startswith("dp_drilling_permit_pending_")), listing[0] if listing else None)
    return {"sections": out, "file": newest, "files": sh.total, "retries": sess.retries}


# ------------------------------------------------------------------------------------------------ completions

def parse_packet(text, district, state):
    lines = text.replace("\r", "").split("\n")
    head = lines[0].split("{")
    forms = [re.sub(r" Data$", "", f.strip()) for f in (head[1].split(",") if len(head) > 1 else []) if f.strip()]
    pk = next((l.split("{") for l in lines if l.startswith("PACKET{")), None)
    if not pk or len(pk) < 41:
        return None
    ip_oil = None  # W-2 CALC_24HR_RATE_OIL, barrels a day (the G-1 gas test has no unit in the manual, so it is left out)
    for l in lines:
        if l.startswith("W-2{"):
            f = l.split("{")
            if len(f) > 14 and re.fullmatch(r"\d+(\.\d+)?", f[14]):
                ip_oil = float(f[14])
    return {"state": state, "forms": forms, "district": district or pk[27], "county": pk[28].strip(), "op": pk[5].strip(),
            "purpose": pk[11].strip(), "ctype": pk[12].strip(), "gas": pk[32].strip() == "1", "profile": pk[40].strip(),
            "approved": mdy(pk[4]), "ip_oil": ip_oil}


def read_completions(path):
    packets = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            m = re.fullmatch(r"([0-9A-Za-z]+)/trackingNo_\d+/packetData_\d+_(Approved|Submitted)\.dat", info.filename)
            if not m or info.file_size > 5_000_000:
                continue
            p = parse_packet(z.read(info).decode("latin-1"), m.group(1), m.group(2))
            if p:
                packets.append(p)
    return packets


def completions_section(day, packets, size, lk):
    app = [p for p in packets if p["state"] == "Approved"]
    sub = [p for p in packets if p["state"] == "Submitted"]
    init = [p for p in app if p["purpose"] == "1"]
    ops = collections.Counter(p["op"] for p in app)
    tops = sorted(((p["ip_oil"], p) for p in init if p["ip_oil"] is not None and not p["gas"]), key=lambda t: -t[0])
    return {
        "day": day.isoformat(), "approved": len(app), "submitted": len(sub), "initial": len(init),
        "oil": sum(not p["gas"] for p in init), "gas": sum(p["gas"] for p in init),
        "horizontal": sum(p["profile"] == "1" for p in init),
        "forms": top(collections.Counter(f for p in app for f in p["forms"]), 10),
        "purpose": [[PURPOSE.get(k, "Other"), n] for k, n in top(collections.Counter(p["purpose"] for p in app), 7)],
        "ctype": [[COMPLETION_TYPE.get(k, "Other"), n] for k, n in top(collections.Counter(p["ctype"] for p in init), 7)],
        "districts": top(collections.Counter(p["district"] for p in app), 14),
        "counties": [[k, lk.county_name(k), n] for k, n in top(collections.Counter(p["county"] for p in app if p["county"]), 12)],
        "operators": [lk.op(k) + [n] for k, n in top(ops, 12)], "operatorCount": len(ops),
        "topTests": [{"rate": round(v), "county": lk.county_name(p["county"]), "district": p["district"],
                      "operator": lk.operator.get(p["op"]), "horizontal": p["profile"] == "1"} for v, p in tops[:6]],
        "zipBytes": size,
    }


def completions_job(ctx):
    sess = Session()
    sh = Share(ctx["guid"]["completions"], sess)
    sh.open()
    listing = sh.newest(len(ctx["dates"]) + 8)
    days = {}
    for r in listing:
        m = re.fullmatch(r"(\d\d)-(\d\d)-(\d{4})\.zip", r["name"])
        if m:
            days[date(int(m.group(3)), int(m.group(1)), int(m.group(2)))] = r
    out = {}
    for day in ctx["dates"]:
        use = max((d for d in days if d <= day), default=None)
        if use is not None and (day - use).days <= 3:
            r = days[use]
            packets = read_completions(sh.download(r["name"], os.path.join(ctx["dl"], "completions-%s" % use.isoformat())))
            out[day] = completions_section(use, packets, r["bytes"], ctx["lk"])
    return {"sections": out, "file": listing[0] if listing else None, "files": sh.total, "retries": sess.retries}


# ------------------------------------------------------------------------------------------------ image packs

def images_job(ctx, ds):
    sess = Session()
    sh = Share(ctx["guid"][ds], sess)
    sh.open()
    listing = sh.newest((14 if ds == "w1images" else 1) * (len(ctx["dates"]) + 4))
    days = collections.defaultdict(lambda: {"bytes": 0, "districts": {}, "modified": None})
    for r in listing:
        m = re.fullmatch(r"subscriptions_(\d{4})-(\d\d)-(\d\d)(?:_district(\w+))?\.zip", r["name"]) if ds == "w1images" else None
        if m:
            d, dist = date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)
        else:
            m = re.fullmatch(r"(\d\d)-(\d\d)-(\d{4})\.zip", r["name"])
            if not m:
                continue
            d, dist = date(int(m.group(3)), int(m.group(1)), int(m.group(2))), None
        if dist:
            days[d]["districts"][dist] = r["bytes"] or 0
        else:
            days[d]["bytes"], days[d]["modified"] = r["bytes"] or 0, r["modified"]
    whole = [r for r in listing if "_district" not in r["name"]]
    return {"days": dict(days), "file": whole[0] if whole else None, "files": sh.total, "retries": sess.retries}


def image_section(days, report_day, lag):
    """The newest day of an image pack whose file was out `lag` days before the report day."""
    use = max((d for d in days if d <= report_day - timedelta(days=lag) and days[d]["modified"]), default=None)
    if use is None:
        return None
    row = days[use]
    return {"day": use.isoformat(), "bytes": row["bytes"], "modified": row["modified"], "empty": row["bytes"] < 2048,
            "districts": sorted(([k, v] for k, v in row["districts"].items() if v > 2048), key=lambda kv: -kv[1])}


# ------------------------------------------------------------------------------------------------ monthly watch

def monthly_job(ctx):
    out = []
    for spec in MONTHLY:
        try:
            sh = Share(spec["guid"], Session())
            sh.open()
            rows = sh.newest(6)
            r = next((x for x in rows if x["name"] == spec["file"]), rows[0] if rows else None)
            built = ctx["lk"].meta.get("sources", {}).get(spec["site"]) if spec["site"] else None
            out.append({"id": spec["id"], "title": spec["title"], "file": r["name"] if r else None, "modified": r["modified"] if r else None,
                        "bytes": r["bytes"] if r else None, "siteBuilt": built,
                        "newer": bool(r and built and r["modified"] and r["modified"][:10] > built)})
        except (ShareError, OSError) as e:
            log("monthly %s: SKIPPED (%s)" % (spec["id"], e))
            out.append({"id": spec["id"], "title": spec["title"], "error": str(e)[:160]})
    return out


# ------------------------------------------------------------------------------------------------ assembling

def file_info(r):
    return {"name": r["name"], "modified": r["modified"], "bytes": r["bytes"]} if r else None


def build_reports(ctx, jobs, cat, kind_by_date):
    """One report dict per date in ctx['dates'], from the finished jobs."""
    lk = ctx["lk"]
    reports = {}
    ok = {k: v for k, v in jobs.items() if not isinstance(v, Exception)}
    pj = ok.get("permits")
    for day in ctx["dates"]:
        rep = {"v": 1, "date": day.isoformat(), "kind": kind_by_date[day]}
        if pj:
            covered = lambda d: any(a <= d <= b for a, b in pj["covered"])  # noqa: E731
            days = sorted(d for d, n in pj["series"].items() if n[0] > 0 and d < day and covered(d))
            if days and (day - days[-1]).days <= 10:
                rep["permits"] = permits_section(pj["perms"], days[-1], lk)
        for did in ("pending", "completions"):
            if did in ok and ok[did]["sections"].get(day):
                rep[did] = ok[did]["sections"][day]
        rep["images"] = {did: image_section(ok[did]["days"], day, lag) for did, lag in IMAGE_LAG.items() if did in ok}
        entries = []
        for spec in DATASETS:
            did = spec["id"]
            sec = rep.get(did) or rep["images"].get(did)
            job = jobs.get(did)
            entry = {"id": did, "title": spec["title"], "cadence": (cat.get(did) or {}).get("updated"), "dataDay": sec["day"] if sec else None}
            if job is None or isinstance(job, Exception):
                entry.update({"error": str(job)[:200] if job else "not captured", "file": None})
            else:
                live = kind_by_date[day] == "live"
                entry.update({"error": None, "file": file_info(job["file"]) if live else None, "files": job["files"] if live else None})
            entries.append(entry)
        rep["datasets"] = entries
        reports[day] = rep
    return reports


def headline(rep):
    """The index row for one report."""
    p, q, c, im = rep.get("permits"), rep.get("pending"), rep.get("completions"), rep.get("images") or {}
    mb = lambda k: round(im[k]["bytes"] / 1048576, 1) if im.get(k) else None  # noqa: E731
    return {"d": rep["date"], "k": rep["kind"], "s": rep.get("status", "ok"), "dd": p["day"] if p else None, "p": p["total"] if p else None,
            "pn": p["newDrill"] if p else None, "q": q["total"] if q else None, "c": c["approved"] if c else None,
            "ci": c["initial"] if c else None, "w1": mb("w1images"), "ds": mb("dirsurveys"), "cm": mb("complimages"),
            "f": sum(1 for d in rep["datasets"] if not d.get("error"))}


def update_states(live, out_dir):
    """Mark each dataset 'new' when its file changed since the previous live report, 'same' when it did not and
    'first' when there is no live report to compare with."""
    prev_days = sorted(f[:-5] for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f) and f[:-5] < live["date"])
    prev = read_json(os.path.join(out_dir, prev_days[-1] + ".json")) if prev_days else None
    before = {d["id"]: d.get("file") for d in prev["datasets"]} if prev and prev.get("kind") == "live" else None
    for d in live["datasets"]:
        if d.get("error"):
            d["state"] = "error"
        elif before is None:
            d["state"] = "first"  # the previous report was rebuilt, not captured live: nothing to compare against
        elif before.get(d["id"]):
            d["state"] = "same" if before[d["id"]] == d["file"] else "new"
        else:
            d["state"] = "new"


def validate(out_dir, keep=KEEP_DAYS):
    """Reload everything this producer writes and check it. Returns the problems found (empty when all is well)."""
    bad = []

    def check(cond, msg):
        if not cond:
            bad.append(msg)

    names = sorted(f for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f))
    check(names, "no day files")
    idx = read_json(os.path.join(out_dir, "index.json"))
    if isinstance(idx, dict) and isinstance(idx.get("days"), list):
        check([r.get("d") for r in idx["days"]] == [f[:-5] for f in names], "index.json does not list exactly the day files")
        check(len(idx["days"]) <= keep, "index.json holds more than %d days" % keep)
        check(os.path.getsize(os.path.join(out_dir, "index.json")) <= BUDGET_BYTES["index.json"], "index.json is over its size budget")
    else:
        bad.append("index.json is missing or malformed")
    ids = [d["id"] for d in DATASETS]
    for f in names:
        path = os.path.join(out_dir, f)
        rep = read_json(path)
        if not isinstance(rep, dict):
            bad.append("%s is not JSON" % f)
            continue
        check(rep.get("v") == 1 and rep.get("date") == f[:-5], "%s: wrong version or date" % f)
        check(rep.get("kind") in ("live", "reconstructed"), "%s: unknown kind" % f)
        check([d.get("id") for d in rep.get("datasets", [])] == ids, "%s: the dataset list is not the six nightly datasets" % f)
        check(os.path.getsize(path) <= BUDGET_BYTES["day"], "%s is over its size budget" % f)
        p, q, c = rep.get("permits"), rep.get("pending"), rep.get("completions")
        if p:
            check(0 <= p["horizontal"] <= p["newDrill"] <= p["total"], "%s: permit counts do not nest" % f)
            check(len(p["rows"]) == min(p["newDrill"], 200), "%s: permit rows do not match the new-drill count" % f)
            check(p["day"] < f[:-5], "%s: permits are not from before the report day" % f)
        if q:
            check(q["total"] == sum(x["n"] for x in q["sets"]), "%s: pending total is not the sum of its sets" % f)
        if c:
            check(0 <= c["initial"] <= c["approved"], "%s: completion counts do not nest" % f)
    ser = read_json(os.path.join(out_dir, "permits-series.json"))
    if isinstance(ser, dict):
        n = len(ser.get("days", []))
        check(all(len(ser.get(k, [])) == n for k in ("total", "newDrill", "horizontal")), "permits-series.json arrays differ in length")
        check(ser.get("days") == sorted(set(ser.get("days", []))), "permits-series.json days are not in order")
        check(all(0 <= h <= nd <= t for t, nd, h in zip(ser.get("total", []), ser.get("newDrill", []), ser.get("horizontal", []))), "permits-series.json counts do not nest")
        check(os.path.getsize(os.path.join(out_dir, "permits-series.json")) <= BUDGET_BYTES["permits-series.json"], "permits-series.json is over its size budget")
    else:
        bad.append("permits-series.json is missing or malformed")
    return bad


def main():
    ap = argparse.ArgumentParser(description="D7: the daily RRC report (see the module docstring)")
    ap.add_argument("--date", help="report date, default today in Central time")
    ap.add_argument("--backfill", type=int, default=0, help="also rebuild missing days of the last N days")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dl", default=os.path.join(ROOT, "dl", "daily"), help="folder for raw downloads (gitignored)")
    ap.add_argument("--keep", type=int, default=KEEP_DAYS)
    ap.add_argument("--only", help="testing: comma list of datasets to read (needs --out somewhere else)")
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    a = ap.parse_args()
    if a.check:
        problems = validate(a.out, a.keep)
        for pr in problems:
            log("CHECK failed: " + pr)
        log("checks %s (%s)" % ("failed" if problems else "ok", a.out))
        sys.exit(1 if problems else 0)
    if a.only and os.path.abspath(a.out) == DEFAULT_OUT:
        sys.exit("--only is for testing: give --out a scratch folder")
    R = date.fromisoformat(a.date) if a.date else central_now().date()
    os.makedirs(a.out, exist_ok=True)
    lk = Lookups()

    have = {f[:-5] for f in os.listdir(a.out) if DAY_FILE.fullmatch(f)}
    todo = [R - timedelta(days=i) for i in range(a.backfill, 0, -1) if (R - timedelta(days=i)).isoformat() not in have]
    dates = todo + [R]
    kind_by_date = {d: ("live" if d == R else "reconstructed") for d in dates}

    cat_rows, nightly = [], []
    try:
        cat_rows, nightly = read_catalog()
    except Exception as e:  # noqa: BLE001
        log("catalog: SKIPPED (%s)" % e)
    cat = {}
    for spec in DATASETS:
        row = next((r for r in nightly if r["desc"].startswith(spec["match"])), None)
        cat[spec["id"]] = {"updated": row["updated"] if row else None, "guid": guid_of(row["links"]) if row else None}
        if cat[spec["id"]]["guid"] and cat[spec["id"]]["guid"] != spec["guid"]:
            log("catalog: %s now lives at share %s (this script has %s)" % (spec["id"], cat[spec["id"]]["guid"], spec["guid"]))
    guid = {s["id"]: cat[s["id"]]["guid"] or s["guid"] for s in DATASETS}
    unknown = [r["desc"] for r in nightly if not any(r["desc"].startswith(s["match"]) for s in DATASETS)]
    for u in unknown:
        log("catalog: the RRC page lists a nightly dataset this script does not read: %s" % u)

    ctx = {"R": R, "dates": dates, "dl": a.dl, "lk": lk, "guid": guid}
    work = {"permits": permits_job, "pending": pending_job, "completions": completions_job,
            "w1images": lambda c: images_job(c, "w1images"), "dirsurveys": lambda c: images_job(c, "dirsurveys"),
            "complimages": lambda c: images_job(c, "complimages")}
    chosen = set(a.only.split(",")) if a.only else set(work)
    jobs, monthly, retries = {}, None, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fn, ctx): name for name, fn in work.items() if name in chosen}
        mfut = None if a.only else pool.submit(monthly_job, ctx)
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                jobs[name] = fut.result()
                retries += jobs[name].get("retries", 0)
                log("%-12s ok (%d connection resets absorbed)" % (name, jobs[name].get("retries", 0)))
            except Exception as e:  # noqa: BLE001 - one dataset failing must not stop the others
                jobs[name] = e
                log("%-12s SKIPPED (%s)" % (name, e))
        if mfut:
            try:
                monthly = mfut.result()
            except Exception as e:  # noqa: BLE001
                log("monthly: SKIPPED (%s)" % e)

    reports = build_reports(ctx, jobs, cat, kind_by_date)
    live = reports[R]
    got = sum(1 for d in live["datasets"] if not d.get("error"))
    live["status"] = "ok" if got == len(DATASETS) else "partial" if got else "failed"
    live["capturedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    live["retries"] = retries
    live["catalog"] = {"datasets": len(cat_rows), "nightly": [{"desc": r["desc"], "updated": r["updated"]} for r in nightly], "unknown": unknown} if cat_rows else None
    live["monthly"] = monthly
    for d, rep in reports.items():
        if d != R:
            rep["status"] = "ok" if all(not x.get("error") for x in rep["datasets"]) else "partial"
    update_states(live, a.out)
    if live["status"] == "failed" and os.path.exists(os.path.join(a.out, R.isoformat() + ".json")):
        log("nothing captured; keeping the existing report for %s" % R)
        del reports[R]

    # permits series: keep earlier days, replace the days the permit files cover
    keep_from = R - timedelta(days=a.keep - 1)
    ser_path = os.path.join(a.out, "permits-series.json")
    old = read_json(ser_path, {"days": [], "total": [], "newDrill": [], "horizontal": []})
    ledger = {d: [t, n, h] for d, t, n, h in zip(old["days"], old["total"], old["newDrill"], old["horizontal"])}
    pj = jobs.get("permits")
    if pj and not isinstance(pj, Exception):
        for c0, c1 in pj["covered"]:
            d = max(c0, keep_from)
            while d <= c1:
                ledger[d.isoformat()] = pj["series"].get(d, [0, 0, 0])
                d += timedelta(days=1)
    days = sorted(d for d in ledger if d >= keep_from.isoformat())
    write_json(ser_path, {"days": days, "total": [ledger[d][0] for d in days], "newDrill": [ledger[d][1] for d in days],
                          "horizontal": [ledger[d][2] for d in days],
                          "src": "RRC Drilling Permit Master and Trailer daily and month-end files; new-drill = application type 01"})

    for d, rep in sorted(reports.items()):
        write_json(os.path.join(a.out, d.isoformat() + ".json"), rep)
    for f in os.listdir(a.out):  # prune, then rebuild the index from the files that remain
        if DAY_FILE.fullmatch(f) and f[:-5] < keep_from.isoformat():
            os.remove(os.path.join(a.out, f))
    rows = [headline(read_json(os.path.join(a.out, f))) for f in sorted(os.listdir(a.out)) if DAY_FILE.fullmatch(f)]
    write_json(os.path.join(a.out, "index.json"), {"generated": live["capturedAt"], "keep": a.keep, "days": rows})
    log("report %s: %s | %d of %d datasets | %d day files | %d connection resets absorbed" % (R, live["status"], got, len(DATASETS), len(rows), retries))
    problems = [] if a.only else validate(a.out, a.keep)
    for pr in problems:
        log("CHECK failed: " + pr)
    sys.exit(2 if problems else 0 if live["status"] != "failed" else 1)


if __name__ == "__main__":
    main()
