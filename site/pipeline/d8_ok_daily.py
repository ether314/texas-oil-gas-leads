#!/usr/bin/env python3
"""D8 producer: the daily Oklahoma Corporation Commission (OCC) report for the leads site.

The OCC publishes its oil and gas records as plain files at https://oklahoma.gov/occ/divisions/oil-gas/oil-gas-data.html.
This reads the ones it refreshes every day and writes into site/public/data/daily-ok/ (spec: site/pipeline/NOTES_D8.md):

  YYYY-MM-DD.json   one report per day (Central time): the permits (intents to drill), completion filings and well transfers
                    the OCC's files held for that day, and, for days captured live, the state's well inventory. 92 days kept.
  index.json        one small row per report day: the numbers the calendar and the trend charts draw

Inputs are public OCC files, only parsed, never run (run with `python3 -I`):
  itd          ITD-wells-formations-daily.xlsx     Intent to Drill, the 7 complete Central days before the day the file is made (it is made about
                                                   7:40 PM Central, so it ends the day before: the file of the evening of Oct 30 ends Oct 29)
  completions  completions-wells-formations-daily.xlsx   1002A completion filings of the same 7 days, one row per casing or test
  transfers    well-transfers-daily.xlsx           wells that changed operator over about a month
  wells        rbdms-wells.csv                     every well in the state, nightly (457,000 rows): counted, never listed
  history      ITD-wells-formations-base.xlsx and completions-wells-formations-base.xlsx (154 MB and 76 MB, back to 1999 and
               2010): read with --history, to rebuild the days before the first nightly capture, and by a capture whose daily file
               stops short of the day before the report (taken in the morning, before that evening's file exists)

One rule for every report, live or rebuilt: a day shows the newest day before it (within 10 days) on which the OCC holds
permits, completion filings or transfers: Monday's report shows Friday's. Permit and filing times in the files are UTC and are
turned into Central days. Nothing names a lease, a well number, an API number or a person: operators are named only when
the name ends like a corporation, LLC or partnership.

  python3 -I site/pipeline/d8_ok_daily.py [--date YYYY-MM-DD] [--backfill N] [--history] [--out DIR] [--dl DIR] [--keep 92]
  python3 -I site/pipeline/d8_ok_daily.py --check [--out DIR]       only reload and check what is already there
  python3 -I site/pipeline/d8_ok_daily.py --skip-if-captured         for a backup schedule: exit quietly if the day is done
  python3 -I site/pipeline/d8_ok_daily.py --counties                 rebuild site/public/data/counties-ok.geo.json (Census file)
"""
import argparse
import collections
import concurrent.futures
import csv
import html
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
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import ok_xlsx  # noqa: E402

PAGE = "https://oklahoma.gov/occ/divisions/oil-gas/oil-gas-data.html"
FILES = "https://oklahoma.gov/content/dam/ok/en/occ/documents/og/ogdatafiles/"
UA = "Mozilla/5.0 (research script)"
KEEP_DAYS = 92
LOOKBACK = 10  # days a section may reach back for its newest day (weekends, holidays)
SAFE_BACKFILL = 3  # the daily files hold 7 days: a missed night is rebuilt from them, anything older only with --history
DEEP_FT = 12000  # planned depth from which a new well is counted as deep: almost all of them are horizontals
DEFAULT_OUT = os.path.join(SITE, "public", "data", "daily-ok")
COUNTIES_GEO = os.path.join(SITE, "public", "data", "counties-ok.geo.json")
BUDGET_BYTES = {"index.json": 40_000, "day": 60_000}
DAY_FILE = re.compile(r"\d{4}-\d\d-\d\d\.json")

DATASETS = [
    {"id": "itd", "title": "Intent to drill", "file": "ITD-wells-formations-daily.xlsx"},
    {"id": "completions", "title": "Well completions", "file": "completions-wells-formations-daily.xlsx"},
    {"id": "transfers", "title": "Well transfers", "file": "well-transfers-daily.xlsx"},
    {"id": "wells", "title": "Well inventory", "file": "rbdms-wells.csv"},
]
BASES = {"itd": "ITD-wells-formations-base.xlsx", "completions": "completions-wells-formations-base.xlsx"}
# the page's other daily or nightly rows that are deliberately not read, and why
NOT_READ = {
    "ITD-wells-formations-base.xlsx": "master file, read only for history",
    "completions-wells-formations-base.xlsx": "master file, read only for history",
    "ogcd-incidents.csv": "its newest incident is weeks older than the file",
    "RBDMS_WELLS.zip": "GIS shapefile of the same wells",
    "operator-list.xlsx": "names, phone numbers and addresses of operators and their contacts: nothing in it is published",
    "purchaser-list.xlsx": "names, phone numbers and addresses of purchasers and their contacts: nothing in it is published",
    "plugger-list.xlsx": "names, phone numbers and addresses of pluggers and their contacts: nothing in it is published",
}
APP_TYPE = {"DR": "New drill", "RC": "Recompletion", "RE": "Re-entry", "DP": "Deepening", "AM": "Amendment"}
WELL_CLASS = {"O&G": "Oil and gas", "OG": "Oil and gas", "DIS": "Disposal or injection", "SWD": "Disposal or injection", "INJ": "Disposal or injection",
              "DNC": "Disposal or injection", "WSW": "Water supply"}
WELL_TYPE = {"OIL": "Oil", "GAS": "Gas", "OG": "Oil and gas", "DRY": "Dry hole", "2RIn": "Injection", "2DNC": "Disposal", "2DCm": "Disposal", "2D": "Disposal",
             "SWD": "Disposal", "INJ": "Injection", "WIW": "Injection", "2R": "Injection", "2RSI": "Injection", "WSW": "Water supply", "TM": "Terminated injection",
             "NT": "No type on file", "DUC": "Drilled, not completed"}
WELL_STATUS = {"AC": "Active", "PA": "Plugged", "PAFF": "Plugged", "PASF": "Plugged", "PASUR": "Plugged", "PASURSF": "Plugged", "NE": "No evidence of well",
               "OR": "Orphaned", "EX": "Expired permit", "STFD": "State funds, to plug", "SFAW": "State funds, to plug", "SFFO": "State funds, to plug",
               "SIFORDER": "Shut in by order", "TA": "Temporarily abandoned", "TM": "Terminated injection", "ND": "New drill", "SP": "Spudded",
               "DUC": "Drilled, not completed", "SCO": "Surface casing only", "ACRT": "Active, red-tagged"}
PLUGGED = {"PA", "PAFF", "PASF", "PASUR", "PASURSF"}
CORPORATE = re.compile(r"(?<![A-Z0-9])(INC|INCORPORATED|CORP|CORPORATION|LLC|L\.L\.C|LP|L\.P|LLP|LLLP|LTD|LIMITED|PLLC|PARTNERS|PARTNERSHIP)\.?(?![A-Z0-9])")
COMPANY = re.compile(r"(?<![A-Z0-9])(CO|COMPANY)\.?(?![A-Z0-9])")
BUSINESS_WORDS = re.compile(r"\b(OIL|GAS|ENERGY|PETROLEUM|RESOURCES|OPERATING|PRODUCTION|EXPLORATION|DRILLING|MINERALS|ROYALTY|MIDSTREAM|PARTNERS)\b")
NOT_BUSINESS = re.compile(r"\b(TRUST|ESTATE|REVOCABLE|FAMILY|HEIRS|ET AL|DBA|D/B/A|D\.B\.A|D B A|DB/A|DOING BUSINESS AS|TRADING AS|T/A|AKA|A/K/A|A K A|ALSO KNOWN AS)\b", re.I)  # a "dba" is a person trading under a name


def log(msg):
    print(msg, flush=True)


def clean_error(e, n=160):
    """An error as short text for a report: no address (the data files and the page's text never carry a link), no line breaks."""
    return re.sub(r"https?://\S+", "<address>", " ".join(str(e).split()))[:n]


# ------------------------------------------------------------------------------------------------ small helpers

def central_now():
    utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/Chicago"))
    except Exception:  # noqa: BLE001 - any failure to load tz data: the US daylight-saving rule
        mar = date(utc.year, 3, 8)
        mar += timedelta(days=(6 - mar.weekday()) % 7)
        nov = date(utc.year, 11, 1)
        nov += timedelta(days=(6 - nov.weekday()) % 7)
        start = datetime(mar.year, mar.month, mar.day, 8, tzinfo=timezone.utc)
        end = datetime(nov.year, nov.month, nov.day, 7, tzinfo=timezone.utc)
        return utc.astimezone(timezone(timedelta(hours=-5 if start <= utc < end else -6)))


def central_day(naive_utc):
    """The Central-time day of a UTC time the OCC files store without a zone."""
    utc = naive_utc.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        return (naive_utc - timedelta(hours=5 if 3 < naive_utc.month < 11 else 6)).date()


def when(value):
    """A UTC datetime from what the OCC files store: an Excel number or 'YYYY-MM-DD[ HH:MM:SS]'. None for blanks and the
    1900-01-01 placeholders."""
    if value in (None, ""):
        return None
    d = ok_xlsx.excel_date(value)
    if d is None and isinstance(value, str) and re.match(r"\d{4}-\d\d-\d\d", value):
        try:
            if re.match(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d", value):
                d = datetime.strptime(value[:10] + " " + value[11:19], "%Y-%m-%d %H:%M:%S")  # the files' times are UTC: keep the time of day
            else:
                d = datetime.strptime(value[:10], "%Y-%m-%d") + timedelta(hours=12)  # a date with no time: noon UTC is the same Central day
        except ValueError:
            return None
    return d if d and d.year >= 1990 else None


def number(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


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


def nameable(name):
    """True when an operator's name ends like a corporation, LLC or partnership: only those are named on the site."""
    n = " ".join((name or "").upper().replace(",", " ").split())
    if not n or NOT_BUSINESS.search(n):
        return False
    return bool(CORPORATE.search(n)) or bool(COMPANY.search(n) and BUSINESS_WORDS.search(n))


COMMON_SHORT = {"OIL", "GAS", "AND", "THE", "OF", "FOR", "INC", "CO", "LLC", "LP", "LLP", "LTD", "RED", "OLD", "NEW", "BIG", "TOP", "SUN", "ONE", "TWO", "SKY",
                "BAY", "ACE", "ARC", "BOW", "CAT", "DOG", "FOX", "OWL", "OAK", "ELM", "SEA", "SKY", "ART", "AIR", "ALL", "ANY", "BEE", "BOX", "CAP", "DAY", "EAGLE",
                "FAR", "FIR", "FLY", "GOLD", "HAT", "ICE", "JET", "KEY", "LAW", "MAN", "MAP", "MUD", "NET", "OX", "PAN", "PEN", "PIN", "RAM", "RAY", "ROY",
                "SAN", "TEN", "TIN", "TOP", "TOW", "WAR", "WAY", "WEST", "WIN", "ZIP", "OK"}
KEEP_CASE = {"LLC": "LLC", "LP": "LP", "LLP": "LLP", "LLLP": "LLLP", "PLLC": "PLLC", "II": "II", "III": "III", "IV": "IV", "USA": "USA", "OK": "OK", "OKC": "OKC", "LTD": "Ltd"}


def pretty(name):
    """'BLACKJACK OPERATING, LLC' -> 'Blackjack Operating, LLC'. Words of three letters or fewer that are not common words are
    taken for acronyms and stay in capitals (AWM, BCE); suffixes and joining words keep their usual form."""
    def word(tok, first):
        core = re.sub(r"[^A-Za-z0-9&]", "", tok).upper()
        if not core:
            return tok
        if core in KEEP_CASE:
            return re.sub(re.escape(core), KEEP_CASE[core], tok, flags=re.I)
        if core in ("AND", "OF", "THE", "FOR", "DE", "AT") and not first:
            return tok.lower()
        if len(core) <= 3 and core.isalpha() and core not in COMMON_SHORT:
            return tok.upper()
        return "-".join(p.capitalize() if len(p) > 3 or p.upper() in COMMON_SHORT else p.upper() for p in tok.split("-")) if "-" in tok else tok.capitalize()
    parts = re.split(r"(\s+)", " ".join(name.strip().split()))
    out, first = [], True
    for p in parts:
        if not p.strip():
            out.append(p)
        else:
            out.append(word(p, first))
            first = False
    return "".join(out)


class Lookups:
    """County names (from the committed Oklahoma county shapes) and the operator naming rule."""

    def __init__(self):
        geo = read_json(COUNTIES_GEO, {"features": []})
        self.county = {f["properties"]["f"]: f["properties"]["n"] for f in geo["features"]}

    def county_name(self, fips):
        return self.county.get(fips) or "Unknown"

    def op(self, number_, name):
        """[operator number, display name or None]: a name only for a corporation, LLC or partnership."""
        return [number_, pretty(name) if nameable(name) else None]


def api_county(api):
    """County FIPS from a 10 or 14 digit API number: state 35, then the county's code (the same as its FIPS code)."""
    return api[2:5] if len(api) >= 5 and api.isdigit() and api.startswith("35") else None


# ------------------------------------------------------------------------------------------------ downloads

def fetch(url, dest):
    """Download url to dest; return {'name', 'modified' (Central, ISO), 'bytes'} from what the server says."""
    last = None
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                size = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                stamp = r.headers.get("Last-Modified")
            want = r.headers.get("Content-Length")
            if want and size != int(want):
                raise OSError("short read: %d of %s bytes" % (size, want))
            mod = None
            if stamp:
                from email.utils import parsedate_to_datetime
                try:
                    from zoneinfo import ZoneInfo
                    mod = parsedate_to_datetime(stamp).astimezone(ZoneInfo("America/Chicago")).replace(tzinfo=None).isoformat(timespec="seconds")
                except Exception:  # noqa: BLE001
                    mod = parsedate_to_datetime(stamp).replace(tzinfo=None).isoformat(timespec="seconds")
            return {"name": url.rsplit("/", 1)[-1], "modified": mod, "bytes": size}
        except Exception as e:  # noqa: BLE001 - network hiccups, 5xx
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError("could not read %s: %s" % (url.rsplit("/", 1)[-1], clean_error(last)))


def read_catalog():
    """The OCC data page's table rows: {file name: {'desc', 'updated'}} for every file link, and the daily or nightly ones."""
    req = urllib.request.Request(PAGE, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        text = r.read().decode("utf-8", "replace")
    rows = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        link = re.search(r'href="[^"]*/ogdatafiles/([^"/?]+)"', tr)
        if link and len(cells) >= 3:
            rows.setdefault(link.group(1), {"desc": cells[1], "updated": cells[2]})
    return rows


# ------------------------------------------------------------------------------------------------ readers

def read_itd(path):
    """Approved intents to drill: [{api, county, op, opname, cls, app, depth, submitted, approved (UTC)}]."""
    out, seen = [], set()
    for r in ok_xlsx.rows(path, want=("API_Number", "Operator_Number", "Entity_Name", "Well_Class", "Application_Type", "Permit_Status", "Total_Depth", "Depth",
                                       "Submit_Date", "Approval_Date")):
        approved = when(r["Approval_Date"])
        if not approved or r["Permit_Status"] in ("REJ", "DEL"):
            continue
        api = (r["API_Number"] or "").strip()
        key = (api, approved, (r["Application_Type"] or "").strip())
        if api and key in seen:  # the file has a row per formation: a permit is counted once (the monthly file does the same)
            continue
        seen.add(key)
        depth = number(r["Total_Depth"]) or number(r["Depth"]) or 0
        out.append({"api": api, "county": api_county(api), "op": (r["Operator_Number"] or "").strip(), "opname": (r["Entity_Name"] or "").strip(),
                    "cls": (r["Well_Class"] or "").strip(), "app": (r["Application_Type"] or "").strip(), "depth": int(depth),
                    "submitted": when(r["Submit_Date"]), "approved": approved})
    return out


COMP_COLS = ("API_Number", "Create_Date", "Review_Status")  # a filing without these has no day or no well: the file is not the one expected
COMP_OPTIONAL = ("Operator_Number", "Operator_Name", "Well_Type", "Location_Type_Sub", "Drill_Type", "Amended", "Spud", "First_Prod", "Oil_BBL_Per_Day", "Gas_MCF_Per_Day",
                 "Formation_Name")  # a renamed one costs its figure, not the whole file


def read_completions(path):
    """Completion filings, one event per well and filing day: [{api, county, op, opname, type, horizontal, new, day (Central),
    created (UTC), spud, first_prod, oil, gas, formation}]. The file has a row per casing string or test, so rows are folded."""
    ev = {}
    for r in ok_xlsx.rows(path, want=COMP_COLS, optional=COMP_OPTIONAL):
        created = when(r["Create_Date"])
        api = (r["API_Number"] or "").strip()
        if not created or not api or r["Review_Status"] in ("REJECTED",):
            continue
        key = (api, created.date().isoformat(), (r["Amended"] or "").strip() == "No")
        e = ev.get(key)
        if e is None:
            e = ev[key] = {"api": api, "county": api_county(api), "op": (r["Operator_Number"] or "").strip(), "opname": (r["Operator_Name"] or "").strip(),
                           "type": (r["Well_Type"] or "").strip(), "horizontal": False, "new": key[2], "created": created, "day": central_day(created),
                           "spud": None, "first_prod": None, "oil": 0.0, "gas": 0.0, "formation": ""}
        if r["Location_Type_Sub"] == "HH" or (r["Drill_Type"] or "").strip().upper().startswith("HORIZONTAL"):
            e["horizontal"] = True
        e["spud"] = e["spud"] or when(r["Spud"])
        e["first_prod"] = e["first_prod"] or when(r["First_Prod"])
        e["oil"] = max(e["oil"], number(r["Oil_BBL_Per_Day"]) or 0.0)
        e["gas"] = max(e["gas"], number(r["Gas_MCF_Per_Day"]) or 0.0)
        e["formation"] = e["formation"] or (r["Formation_Name"] or "").strip()
    return list(ev.values())


def read_transfers(path):
    """Well transfers: [{api, county, type, day (Central), from_no, from_name, to_no, to_name}] (one per well and event)."""
    out = []
    for r in ok_xlsx.rows(path, want=("EventDate", "API Number", "Type", "FromOperatorNumber", "FromOperatorName", "ToOperatorNumber", "ToOperatorName")):
        ev = when(r["EventDate"])
        api = (r["API Number"] or "").strip()
        if not ev or not api or r["FromOperatorNumber"] == r["ToOperatorNumber"]:
            continue
        out.append({"api": api, "county": api_county(api), "type": (r["Type"] or "").strip(), "day": central_day(ev),
                    "from_no": (r["FromOperatorNumber"] or "").strip(), "from_name": (r["FromOperatorName"] or "").strip(),
                    "to_no": (r["ToOperatorNumber"] or "").strip(), "to_name": (r["ToOperatorName"] or "").strip()})
    return out


def read_wells(path):
    """The well inventory counted, never listed: totals by status and type, and for active wells by county and operator."""
    status, wtype, county, ops = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    active_type = collections.Counter()
    names = {}
    total = 0
    with open(path, encoding="iso-8859-1", newline="") as f:
        reader = csv.DictReader(f)
        # a UTF-8 byte-order mark read as ISO-8859-1 is three characters glued to the first name, which would make that column vanish
        reader.fieldnames = [(h or "").replace("\xef\xbb\xbf", "").replace("\ufeff", "").strip() for h in (reader.fieldnames or [])]
        if not {"WELLSTATUS", "API"} <= set(reader.fieldnames):  # an error page, an empty export or a renamed column is not the inventory
            raise ValueError("the well file has no WELLSTATUS and API columns: it is not the inventory")
        for row in reader:
            total += 1
            s = (row.get("WELLSTATUS") or "").strip()
            status[s] += 1
            wtype[(row.get("WELLTYPE") or "").strip()] += 1
            if s == "AC":
                api = (row.get("API") or "").strip()
                c = api_county(api)
                if c:
                    county[c] += 1
                op = (row.get("OPERATOR") or "").strip()
                if op:
                    ops[op] += 1
                active_type[(row.get("WELLTYPE") or "").strip()] += 1
    if not total:
        raise ValueError("the well file holds no wells")
    return {"total": total, "status": status, "type": wtype, "county": county, "operators": ops, "active_type": active_type}


WELLS_FLOOR = 0.9  # a night's inventory under 90% of the last capture's is a cut-short download, not fewer wells


def previous_wells_total(out_dir, before):
    """The well total of the newest report before `before` that holds an inventory; None when there is none."""
    for f in sorted((f for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f) and f[:-5] < before.isoformat()), reverse=True):
        w = (read_json(os.path.join(out_dir, f)) or {}).get("wells")
        if w and w.get("total"):
            return w["total"]
    return None


# ------------------------------------------------------------------------------------------------ sections

def median_int(values):
    return int(statistics.median(values)) if values else None


def median_days(values):
    """The median of a sorted list of day counts: a whole number when it is one, else one decimal (4 and 5 give 4.5)."""
    m = statistics.median(values)
    return int(m) if m == int(m) else round(m, 1)


def named_ops(counter_by_op, names, lk, n=12):
    """[[operator number, name or None, count]] largest first."""
    ranked = sorted(counter_by_op.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [lk.op(op, names.get(op, "")) + [c] for op, c in ranked]


def tally_counties(counter, lk):
    """[[fips, name, n]] largest first; a record whose API number gives no county is counted in the totals, never placed in one (and never sorted: None
    does not compare with a code)."""
    return [[f, lk.county_name(f), n] for f, n in sorted(((f, n) for f, n in counter.items() if f), key=lambda kv: (-kv[1], kv[0]))]


def permits_section(day, rows, lk):
    """Everything the report says about the intents to drill approved on `day` (a list of read_itd rows)."""
    new = [r for r in rows if r["app"] == "DR"]
    depths = [r["depth"] for r in new if r["depth"] > 0]
    wait = sorted((r["approved"] - r["submitted"]).days for r in new if r["submitted"] and r["submitted"] <= r["approved"])
    ops = collections.Counter(r["op"] for r in new if r["op"])
    names = {r["op"]: r["opname"] for r in new}
    cls = collections.Counter(WELL_CLASS.get(r["cls"], "Other") for r in new)
    bands = [("Under 5,000 ft", 0, 5000), ("5,000 to 10,000 ft", 5000, 10000), ("10,000 to 15,000 ft", 10000, 15000), ("15,000 to 20,000 ft", 15000, 20000),
             ("20,000 ft or more", 20000, 10 ** 9)]
    deep = [d for d in depths if d >= DEEP_FT]
    named = sum(n for k, n in ops.items() if nameable(names.get(k, "")))
    return {
        "day": day.isoformat(), "total": len(rows), "newDrill": len(new),
        "types": top(collections.Counter(APP_TYPE.get(r["app"], "Other") for r in rows), 8),
        "classes": top(cls, 5), "deep": len(deep), "deepFt": DEEP_FT,
        "depth": {"median": median_int(depths), "max": max(depths), "mean": int(sum(depths) / len(depths))} if depths else None,
        "bands": [[label, sum(1 for d in depths if lo <= d < hi)] for label, lo, hi in bands],
        "wait": {"median": median_days(wait), "max": wait[-1]} if wait else None,
        "amended": sum(1 for r in rows if r["app"] == "AM"),
        "counties": tally_counties(collections.Counter(r["county"] for r in new), lk), "countyCount": len({r["county"] for r in new if r["county"]}),
        "operators": named_ops(ops, names, lk), "operatorCount": len(ops),
        "namedShare": round(named / len(new), 3) if new else None,
    }


def completions_section(day, events, lk):
    """Completion filings made on `day` (read_completions events): new filings and amended ones, by well type and place."""
    new = [e for e in events if e["new"]]
    amended = [e for e in events if not e["new"]]
    ops = collections.Counter(e["op"] for e in new if e["op"])
    names = {e["op"]: e["opname"] for e in events}
    tests = sorted((e for e in new if e["oil"] > 0 or e["gas"] > 0), key=lambda e: (-e["oil"], -e["gas"]))
    lag = sorted((e["day"] - e["first_prod"].date()).days for e in new if e["first_prod"] and e["first_prod"].date() <= e["day"])
    drill = sorted((e["first_prod"].date() - e["spud"].date()).days for e in new if e["spud"] and e["first_prod"] and e["spud"] <= e["first_prod"])
    named = sum(n for k, n in ops.items() if nameable(names.get(k, "")))
    return {
        "day": day.isoformat(), "filed": len(new), "amended": len(amended),
        "types": top(collections.Counter(WELL_TYPE.get(e["type"], "Other") for e in new), 12),
        "horizontal": sum(e["horizontal"] for e in new),
        "formations": top(collections.Counter(e["formation"].title() for e in new if e["formation"]), 6),
        "counties": tally_counties(collections.Counter(e["county"] for e in new), lk), "countyCount": len({e["county"] for e in new if e["county"]}),
        "operators": named_ops(ops, names, lk), "operatorCount": len(ops),
        "namedShare": round(named / len(new), 3) if new else None,
        "lag": {"median": median_int(lag), "max": lag[-1]} if lag else None,
        "spudToProd": {"median": median_int(drill)} if drill else None,
        "tests": [{"oil": round(e["oil"]), "gas": round(e["gas"]), "county": lk.county_name(e["county"]), "operator": lk.op(e["op"], e["opname"])[1], "horizontal": e["horizontal"]}
                  for e in tests[:6]],
    }


def transfers_section(day, rows, lk):
    """Wells that changed operator on `day`: how many, between how many operators, and the biggest buyers and sellers."""
    wells = {r["api"] for r in rows}
    to, frm = collections.Counter(r["to_no"] for r in rows), collections.Counter(r["from_no"] for r in rows)
    names = {}
    for r in rows:
        names[r["to_no"]] = r["to_name"]
        names[r["from_no"]] = r["from_name"]
    return {
        "day": day.isoformat(), "wells": len(wells), "types": top(collections.Counter(WELL_TYPE.get(r["type"], "Other") for r in rows), 12),
        "buyerCount": len(to), "sellerCount": len(frm),
        "buyers": named_ops(to, names, lk, 8), "sellers": named_ops(frm, names, lk, 8),
        "counties": tally_counties(collections.Counter(r["county"] for r in rows), lk)[:14],
    }


def status_mix(counter, keep=5):
    """[[label, wells]] with the codes that share a label added together, the largest `keep`, and the rest as Other: adds up to the total.
    Five plus Other is six parts, the most the page's stacked bar can tell apart by color."""
    by_label = collections.Counter()
    for code, n in counter.items():
        by_label[WELL_STATUS.get(code, "Other")] += n
    ranked = sorted(((k, v) for k, v in by_label.items() if k != "Other"), key=lambda kv: (-kv[1], kv[0]))
    head, rest = ranked[:keep], ranked[keep:]
    other = by_label.get("Other", 0) + sum(v for _, v in rest)
    return [[k, v] for k, v in head] + ([["Other", other]] if other else [])


def wells_section(inv, modified, lk):
    active = inv["status"].get("AC", 0)
    plugged = sum(n for k, n in inv["status"].items() if k in PLUGGED)
    kinds = collections.Counter()
    for k, n in inv["active_type"].items():
        kinds[{"OIL": "Oil", "GAS": "Gas", "OG": "Oil and gas"}.get(k, "Injection, disposal and other")] += n
    ops = sorted(inv["operators"].items(), key=lambda kv: (-kv[1], kv[0]))
    shown = [[pretty(name), n] for name, n in ops if nameable(name)][:12]
    unassigned = inv["operators"].get("OTC/OCC NOT ASSIGNED", 0)
    unnamed = sum(n for name, n in inv["operators"].items() if not nameable(name) and name != "OTC/OCC NOT ASSIGNED")
    return {
        "asOf": (modified or "")[:10], "total": inv["total"], "active": active, "plugged": plugged,
        "status": status_mix(inv["status"]),
        "activeTypes": top(kinds, 4),
        "counties": tally_counties(inv["county"], lk), "countyCount": len(inv["county"]),
        "operators": shown, "operatorCount": len(inv["operators"]), "unnamed": unnamed, "unassigned": unassigned,
    }


# ------------------------------------------------------------------------------------------------ assembling

def newest_day(by_day, day, lookback=LOOKBACK):
    """The newest day before `day`, within `lookback` days, that has records; None when there is none."""
    days = [d for d in by_day if d < day and (day - d).days <= lookback and by_day[d]]
    return max(days) if days else None


def group_by_day(rows, key):
    out = collections.defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def file_info(r):
    return {"name": r["name"], "modified": r["modified"], "bytes": r["bytes"]} if r else None


def build_reports(ctx, jobs, cat, kind_by_date):
    """One report dict per date in ctx['dates'], from the parsed files."""
    lk = ctx["lk"]
    ok = {k: v for k, v in jobs.items() if not isinstance(v, Exception)}
    permits = group_by_day(ok["itd"]["rows"], lambda r: central_day(r["approved"])) if "itd" in ok else {}
    comps = group_by_day(ok["completions"]["rows"], lambda r: r["day"]) if "completions" in ok else {}
    trans = group_by_day(ok["transfers"]["rows"], lambda r: r["day"]) if "transfers" in ok else {}
    reports = {}
    for day in ctx["dates"]:
        live = kind_by_date[day] == "live"
        rep = {"v": 1, "state": "OK", "date": day.isoformat(), "kind": kind_by_date[day]}
        if "itd" in ok:
            d = newest_day(permits, day)
            if d:
                rep["permits"] = permits_section(d, permits[d], lk)
        if "completions" in ok:
            d = newest_day(comps, day)
            if d:
                rep["completions"] = completions_section(d, comps[d], lk)
        if "transfers" in ok:
            d = newest_day(trans, day)
            if d:
                rep["transfers"] = transfers_section(d, trans[d], lk)
        if live and "wells" in ok:
            rep["wells"] = wells_section(ok["wells"]["inventory"], ok["wells"]["file"]["modified"], lk)
        entries = []
        for spec in DATASETS:
            did = spec["id"]
            sec = rep.get({"itd": "permits"}.get(did, did))
            job = jobs.get(did)
            entry = {"id": did, "title": spec["title"], "cadence": (cat.get(spec["file"]) or {}).get("updated"),
                     "dataDay": (sec.get("day") or sec.get("asOf")) if sec else None}
            if not live and did == "wells":
                entry.update({"error": None, "file": None, "absent": True})  # the OCC keeps only today's inventory
            elif job is None or isinstance(job, Exception):
                entry.update({"error": clean_error(job, 200) if job else "not captured", "file": None})
            else:
                entry.update({"error": None, "file": file_info(job["file"]) if live else None})
            entries.append(entry)
        rep["datasets"] = entries
        reports[day] = rep
    return reports


def headline(rep):
    """The index row for one report."""
    p, c, t, w = rep.get("permits"), rep.get("completions"), rep.get("transfers"), rep.get("wells")
    return {"d": rep["date"], "k": rep["kind"], "s": rep.get("status", "ok"), "dd": p["day"] if p else None, "p": p["total"] if p else None,
            "pn": p["newDrill"] if p else None, "pd": p["deep"] if p else None, "cd": c["day"] if c else None, "c": c["filed"] if c else None,
            "ca": c["amended"] if c else None, "td": t["day"] if t else None, "t": t["wells"] if t else None, "w": w["active"] if w else None,
            "f": sum(1 for d in rep["datasets"] if not d.get("error") and not d.get("absent"))}


def update_states(live, out_dir):
    """Mark each dataset 'new' when its file changed since the previous live report, 'same' when it did not and 'first' when
    there is no live report to compare with."""
    prev_days = sorted(f[:-5] for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f) and f[:-5] < live["date"])
    prev = read_json(os.path.join(out_dir, prev_days[-1] + ".json")) if prev_days else None
    before = {d["id"]: d.get("file") for d in prev["datasets"]} if prev and prev.get("kind") == "live" else None
    for d in live["datasets"]:
        if d.get("error"):
            d["state"] = "error"
        elif before is None:
            d["state"] = "first"
        elif before.get(d["id"]):
            d["state"] = "same" if before[d["id"]] == d["file"] else "new"
        else:
            d["state"] = "new"


def add_wells_change(live, out_dir):
    """Active, plugged and total wells against the previous live report that had an inventory."""
    w = live.get("wells")
    if not w:
        return
    for f in sorted((f for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f) and f[:-5] < live["date"]), reverse=True):
        prev = (read_json(os.path.join(out_dir, f)) or {}).get("wells")
        if prev:
            w["change"] = {"since": f[:-5], "active": w["active"] - prev["active"], "plugged": w["plugged"] - prev["plugged"], "total": w["total"] - prev["total"]}
            return


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
        check(rep.get("v") == 1 and rep.get("date") == f[:-5] and rep.get("state") == "OK", "%s: wrong version, date or state" % f)
        check(rep.get("kind") in ("live", "reconstructed"), "%s: unknown kind" % f)
        check([d.get("id") for d in rep.get("datasets", [])] == ids, "%s: the dataset list is not the four OCC datasets" % f)
        check(os.path.getsize(path) <= BUDGET_BYTES["day"], "%s is over its size budget" % f)
        p, c, t, w = rep.get("permits"), rep.get("completions"), rep.get("transfers"), rep.get("wells")
        if p:
            check(0 <= p["deep"] <= p["newDrill"] <= p["total"], "%s: permit counts do not nest" % f)
            check(sum(n for _, n in p["types"]) == p["total"], "%s: permit types do not add up" % f)
            check(sum(n for _, n in p["bands"]) <= p["newDrill"], "%s: depth bands exceed the new-drill permits" % f)
            check(p["day"] < f[:-5], "%s: permits are not from before the report day" % f)
        if c:
            check(c["horizontal"] <= c["filed"], "%s: horizontal completions exceed the filings" % f)
            check(sum(n for _, n in c["types"]) == c["filed"], "%s: completion types do not add up" % f)
            check(c["day"] < f[:-5], "%s: completions are not from before the report day" % f)
        if t:
            check(t["wells"] > 0 and sum(n for _, n in t["types"]) >= t["wells"] - 0, "%s: transfer types do not cover the wells" % f)
            check(t["day"] < f[:-5], "%s: transfers are not from before the report day" % f)
        if w:
            check(w["active"] + w["plugged"] <= w["total"], "%s: well counts do not nest" % f)
            check(sum(n for _, n in w["status"]) == w["total"], "%s: the well status mix does not add up to the total" % f)
            check(sum(n for _, _, n in w["counties"]) <= w["active"], "%s: active wells by county exceed the active wells" % f)
    return bad


def plan_dates(R, keep, backfill, history, have):
    """The days to build, oldest first, ending with the report day R: the missing days before it that the files can still tell.
    With history that is the whole archive (the master files go back years); otherwise at most SAFE_BACKFILL days, because the
    daily files hold only 7 and an older day would be rebuilt from too little. Returns (dates, capped): capped says the
    request reached further back than that."""
    window = keep - 1 if history else min(backfill, SAFE_BACKFILL)
    todo = [R - timedelta(days=i) for i in range(window, 0, -1) if (R - timedelta(days=i)).isoformat() not in have]
    return todo + [R], (not history and backfill > SAFE_BACKFILL)


def coverage_end(modified):
    """The last complete Central day an OCC daily file holds. The daily intent-to-drill and completion files hold the 7 complete Central
    days before the day they are made, so a file made at 19:41 on day G (its Last-Modified, in Central) ends with day G-1: the file made
    on the evening of Oct 30 has nothing from Oct 30. None when the file's time is not known."""
    try:
        return date.fromisoformat(modified[:10]) - timedelta(days=1)
    except (TypeError, ValueError):
        return None


def masters_to_read(R, dates, history, jobs, chosen):
    """{dataset: oldest day to keep} for the master files that must be read. With history, every master, back to the oldest day wanted.
    Otherwise only the master of a dataset whose daily file stops short of the day before R (a capture in the morning, before that
    evening's file exists, or after the OCC missed a night): the master has the days after the daily file's last one, so such a report
    shows the same as the evening run and as a rebuild. A capture in the evening needs no master."""
    if history:
        lo = min(dates) - timedelta(days=LOOKBACK)
        return {ds: lo for ds in BASES if ds in chosen and not isinstance(jobs.get(ds), Exception)}
    out = {}
    for ds in BASES:
        job = jobs.get(ds)
        if ds not in chosen or job is None or isinstance(job, Exception):
            continue
        end = coverage_end((job.get("file") or {}).get("modified"))
        if end is not None and end < R - timedelta(days=1):
            out[ds] = end - timedelta(days=1)
    return out


def captured_for_the_night(out_dir, R):
    """When R's report was captured live, with every dataset read, at or after 03:00 UTC the next day; None otherwise."""
    prior = read_json(os.path.join(out_dir, R.isoformat() + ".json"))
    if not isinstance(prior, dict):
        return None
    cutoff = (datetime(R.year, R.month, R.day, tzinfo=timezone.utc) + timedelta(days=1, hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    at = prior.get("capturedAt")
    ok = prior.get("kind") == "live" and prior.get("status") == "ok" and isinstance(at, str) and at >= cutoff
    return at if ok else None


# ------------------------------------------------------------------------------------------------ counties

def build_counties(zip_path, out_path):
    """The 77 Oklahoma counties from the Census cartographic boundary file (the same source and readers as the Texas map)."""
    import d2_layers as D2
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        pick = lambda ext: next(n for n in names if n.lower().endswith(ext))  # noqa: E731
        shp, dbf = z.read(pick(".shp")), z.read(pick(".dbf"))
    rows, shapes = D2.read_dbf(dbf), D2.read_shp(shp)
    out = {}
    for row, rings in zip(rows, shapes):
        if row and rings and row.get("STATEFP") == "40":
            out[row["COUNTYFP"]] = {"n": row["NAME"], "polys": D2.finalize(D2.rings_to_polys(rings))}
    if len(out) != 77 or sorted(out) != ["%03d" % i for i in range(1, 154, 2)]:
        raise ValueError("expected the 77 Oklahoma counties 001..153, found %d" % len(out))
    write_json(out_path, D2.build_counties_doc(out))
    return len(out)


# ------------------------------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="D8: the daily Oklahoma Corporation Commission report (see the module docstring)")
    ap.add_argument("--date", help="report date, default today in Central time")
    ap.add_argument("--backfill", type=int, default=0, help="also rebuild missing days of the last N from the files' windows")
    ap.add_argument("--history", action="store_true", help="read the permit and completion master files (230 MB) to rebuild every missing day")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dl", default=os.path.join(ROOT_DL := os.path.join(os.path.dirname(SITE), "dl"), "daily-ok"))
    ap.add_argument("--keep", type=int, default=KEEP_DAYS)
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    ap.add_argument("--skip-if-captured", action="store_true", help="do nothing when the report day was already captured live, reading every dataset, at or after 03:00 UTC the next day")
    ap.add_argument("--counties", action="store_true", help="rebuild counties-ok.geo.json from the Census county file")
    ap.add_argument("--only", help="testing: comma list of datasets to read (needs --out somewhere else)")
    ap.add_argument("--wells-floor", type=float, default=WELLS_FLOOR, help="refuse a well inventory under this share of the last capture's total as cut short "
                    "(default %(default)s; 0 accepts any, for a by-hand run after the OCC really did shrink its inventory)")
    a = ap.parse_args()
    if a.counties:
        zp = os.path.join(a.dl, "cb_2025_us_county_5m.zip")
        os.makedirs(a.dl, exist_ok=True)
        fetch("https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip", zp)
        log("wrote %s with %d counties" % (COUNTIES_GEO, build_counties(zp, COUNTIES_GEO)))
        return
    if a.check:
        problems = validate(a.out, a.keep)
        for pr in problems:
            log("CHECK failed: " + pr)
        log("checks ok (%s)" % a.out if not problems else "%d problem(s)" % len(problems))
        sys.exit(1 if problems else 0)
    if a.only and os.path.abspath(a.out) == DEFAULT_OUT:
        sys.exit("--only is for testing: give --out a scratch folder")
    today = central_now().date()
    try:
        R = date.fromisoformat(a.date) if a.date else today
    except ValueError:
        sys.exit("--date must be a real day like 2026-10-30")
    if R > today:
        sys.exit("--date cannot be a day that has not started yet in Central time (today is %s)" % today)
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.dl, exist_ok=True)
    if a.skip_if_captured:
        got = captured_for_the_night(a.out, R)
        if got:
            log("report %s was already captured live at %s; nothing to do" % (R, got))
            sys.exit(0)
    lk = Lookups()
    if not lk.county:
        sys.exit("counties-ok.geo.json is missing: run with --counties first")
    have = set()
    for f in os.listdir(a.out):
        if DAY_FILE.fullmatch(f):
            old = read_json(os.path.join(a.out, f)) or {}
            # a rebuilt day written while a file could not be read stays missing its figures for good unless it is built again; a live report is never rebuilt
            if old.get("kind") == "reconstructed" and old.get("status") != "ok":
                continue
            have.add(f[:-5])
    dates, capped = plan_dates(R, a.keep, a.backfill, a.history, have)
    if capped:
        log("backfill: the daily files hold 7 days, so only the last %d missed days are rebuilt (older days need --history)" % SAFE_BACKFILL)
    kind_by_date = {d: ("live" if d == R else "reconstructed") for d in dates}

    cat_rows = {}
    try:
        cat_rows = read_catalog()
    except Exception as e:  # noqa: BLE001
        log("catalog: SKIPPED (%s)" % clean_error(e))
    cat = {s["file"]: cat_rows.get(s["file"]) or {} for s in DATASETS}
    unknown = sorted(f for f, r in cat_rows.items() if re.search(r"daily|nightly", r["updated"], re.I) and f not in {s["file"] for s in DATASETS} and f not in NOT_READ)
    for u in unknown:
        log("catalog: the OCC page lists a daily or nightly file this script does not read: %s (%s)" % (u, cat_rows[u]["desc"]))

    readers = {"itd": read_itd, "completions": read_completions, "transfers": read_transfers, "wells": read_wells}
    chosen = set(a.only.split(",")) if a.only else set(readers)
    jobs, retries = {}, 0

    def run(spec):
        dest = os.path.join(a.dl, spec["file"])
        info = fetch(FILES + spec["file"], dest)
        parsed = readers[spec["id"]](dest)
        if spec["id"] == "wells":
            prev = previous_wells_total(a.out, R)
            if prev and parsed["total"] < prev * a.wells_floor:
                raise RuntimeError("the well file holds %d wells, under %d%% of the %d the last capture counted: refused as cut short" % (parsed["total"], round(a.wells_floor * 100), prev))
        return ({"inventory": parsed} if spec["id"] == "wells" else {"rows": parsed}) | {"file": info}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(run, s): s["id"] for s in DATASETS if s["id"] in chosen}
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                jobs[name] = fut.result()
                log("%-12s ok (%s)" % (name, jobs[name]["file"]["modified"]))
            except Exception as e:  # noqa: BLE001 - one dataset failing must not stop the others
                jobs[name] = e
                log("%-12s SKIPPED (%s)" % (name, e))

    # the master files hold the days before the first capture (--history) and the days after a daily file's last one; the daily files'
    # rows are merged in on top
    history_failed = []
    since = masters_to_read(R, dates, a.history, jobs, chosen)
    for ds, lo in since.items():
        if not a.history:
            log("%-12s its daily file ends %s, short of the %s this report needs: reading the master for the days after it" % (
                ds, coverage_end(jobs[ds]["file"]["modified"]), R - timedelta(days=1)))
    if since:
        for ds, fname in BASES.items():
            if ds not in since:
                continue
            lo = since[ds]
            try:
                dest = os.path.join(a.dl, fname)
                fetch(FILES + fname, dest)
                rows = readers[ds](dest)
                keep_rows = [r for r in rows if (central_day(r["approved"]) if ds == "itd" else r["day"]) >= lo]
                have_keys = {(r["api"], r.get("approved") or r.get("created")) for r in jobs[ds]["rows"]}
                jobs[ds]["rows"] += [r for r in keep_rows if (r["api"], r.get("approved") or r.get("created")) not in have_keys]
                log("%-12s history: %d rows from the master since %s" % (ds, len(keep_rows), lo))
                os.remove(dest)
            except Exception as e:  # noqa: BLE001
                history_failed.append(ds)
                log("%-12s history SKIPPED (%s)" % (ds, clean_error(e)))

    ctx = {"R": R, "dates": dates, "lk": lk}
    reports = build_reports(ctx, jobs, cat, kind_by_date)
    live = reports[R]
    got = sum(1 for d in live["datasets"] if not d.get("error"))
    # a master file that could not be read leaves the days after a daily file's last one out: the report is stale though every file was read, so it
    # is partial and the backup run tries again
    live["status"] = ("ok" if got == len(DATASETS) and not history_failed else "partial") if got else "failed"
    live["capturedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    live["catalog"] = {"nightly": [{"file": f, "desc": r["desc"], "updated": r["updated"]} for f, r in sorted(cat_rows.items()) if re.search(r"daily|nightly", r["updated"], re.I)],
                       "unknown": unknown} if cat_rows else None
    for d, rep in reports.items():
        if d != R:
            rep["status"] = "ok" if all(not x.get("error") for x in rep["datasets"]) else "partial"
    update_states(live, a.out)
    add_wells_change(live, a.out)
    earlier = read_json(os.path.join(a.out, R.isoformat() + ".json"))
    if live["status"] == "failed" and isinstance(earlier, dict):
        log("nothing captured; keeping the existing report for %s" % R)
        del reports[R]
    elif isinstance(earlier, dict) and earlier.get("kind") == "live" and sum(1 for d in earlier.get("datasets", []) if not d.get("error")) > got:
        # a later capture of the same day that read fewer files (the 121 MB inventory refused) must not replace a report that read more
        log("this run read %d of %d datasets, the existing report for %s read more: keeping it" % (got, len(DATASETS), R))
        del reports[R]

    keep_from = R - timedelta(days=a.keep - 1)
    for d, rep in sorted(reports.items()):
        write_json(os.path.join(a.out, d.isoformat() + ".json"), rep)
    for f in os.listdir(a.out):
        if DAY_FILE.fullmatch(f) and f[:-5] < keep_from.isoformat():
            os.remove(os.path.join(a.out, f))
    rows = [headline(read_json(os.path.join(a.out, f))) for f in sorted(os.listdir(a.out)) if DAY_FILE.fullmatch(f)]
    write_json(os.path.join(a.out, "index.json"), {"generated": live["capturedAt"], "keep": a.keep, "days": rows})
    log("report %s: %s | %d of %d datasets | %d day files" % (R, live["status"], got, len(DATASETS), len(rows)))
    problems = [] if a.only else validate(a.out, a.keep)
    for pr in problems:
        log("CHECK failed: " + pr)
    sys.exit(2 if problems else 0 if live["status"] != "failed" else 1)


if __name__ == "__main__":
    main()
