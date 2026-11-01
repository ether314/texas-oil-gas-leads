#!/usr/bin/env python3
"""D11: Mississippi's oil and gas permits (State Oil and Gas Board), for the National report of the Oil tracker.

The Board's open files do not hold every permit. Its daily well shapefile has only wells with a location (30 to 55 percent short of the Board's own yearly totals: that earlier producer was
withheld), and the well list has no date at all. Two things the Board does publish are complete:
  - the Permit Search report (https://www.ogb.state.ms.us/permitsearchnomenu.php): one row for every permit the Board issues, with the day it was approved and a permit type, county and
    operator. Its table is filled by the page's own script, which posts the page's query to /ajaxloadPDO.php and gets JSON back. This reads that table with the one query the page builds
    when a visitor sets a date range and leaves every other filter empty (the same view, the same date filter, the same order), asking for only the six columns it needs: the fixed text in
    `search_sql` with two dates in it, never anything taken from a downloaded file;
  - the Board's yearly "Permits to Drill" sheets (a PDF a year, county by month, `pdftotext -layout` reads the last four years; older ones are scans). They are not the source, they are the
    check: a year's total is the Board's own count, and a run refuses to write when this file's count for a closed year differs from the Board's by more than 3 permits or 8 percent.

What is counted, by the day the Board approved the permit (`measure` "permits", basis "approval date"), one permit once (its permit number is the key):
  new      OPD, "Original Permit to Drill", for an oil, gas, test or dry hole
  inj      OPI, "Original Permit to Drill (Injection)", and an OPD for a well that is a service well: disposal, enhanced recovery, brine, fluid disposal, gas, LPG or hydrogen storage, water
           source or monitor/observation (the well's type in the Board's well list, the type it has now, decides: the permit type does not say)
  rework   OPDC, OPDD, OPDT (commingled, dual and triple completions), CIP and CPI (conversions), WOP, WOPH, WOI, WOIH (workovers)
  amend    COP and COI, a change of operator (one permit per well: one sale of many wells is a spike, 574 in April 2019)
  other    anything else (H2S and PIT, which the Board's code list does not define, and any code it adds)
  redrill  null: the Board's codes do not separate a re-entry from a new drill
The Board's own yearly sheet counts new and injection permits to drill (88, 67, 50 and 37 for 2022 to 2025). This file's `new` plus `inj`, less the monitor wells, gives 90, 66, 50 and 37 (the
sheet is two lower in April 2022, where two wells have a cancelled original permit and a replacement under the same name, one higher in 2023, and does not count the five Denbury monitor wells
of May 2025). `new` alone is the Board's figure without its injection permits, which is why it reads lower. County and operator are those of the `new` permits (only a corporation, LLC or partnership is named: `nameable`); fluid is the well's type in the well list
(OIL, GAS, and the test types as other; a well that came up dry is DH there and counts as unknown). The well list (about 35,000 wells, 13 MB) is joined to the permits in memory by the Board's
well number, which is used for nothing else and kept nowhere: no well, lease, permit number or API number reaches the output.

The register is read live, so `asOf` is the day of the read and a month counts as complete two weeks after it ended (an entry may come late; the newest permit was three days old when it was
first read). A reply that is not the register (not JSON, a count that does not match its rows, fewer than 2,000 permits since 2019, a date that is not a day or lies in the future, a row that is not the six
fields, no original permit to drill in two years, a newest permit more than 60 days old), a well list that is cut short or lost its columns or does not know the wells the permits are for, or a
Downloads page with no recent well list, fails the run (nothing is written).

  python3 -I site/pipeline/d11_nat_ms.py [--check]
Six requests, 3 seconds apart: the register (one POST, 2.5 MB), the Downloads page, the well list (13 MB), the sheets' folder and two sheets (65 KB each).
"""
import base64
import csv
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "MS"
BASE = "https://www.ogb.state.ms.us"
PAGE = BASE + "/permitsearchnomenu.php"
API = BASE + "/ajaxloadPDO.php"
DOWNLOADS = BASE + "/downloadsnomenu.php"
WELL_LIST = BASE + "/Downloads/WellInfoList/%s_All_WellInfoList.csv"
SHEETS = BASE + "/treebrowsermodalnested.php?directory=monthlypermits&order=desc"
PAUSE = 3.0
LAG_DAYS = 14  # a month counts once it ended this many days before the read
MIN_ROWS = 2000  # permits since 2019-01 in the register (5,540 on 2026-11-01)
MIN_WELLS = 20000  # wells in the well list (35,218 on 2026-10-30)
MAX_REGISTER_AGE = 60  # days: the newest permit of a live register is never older
MAX_LIST_AGE = 14  # days: the newest dated well list on the Downloads page
JOIN_SHARE = 0.9  # of the original permits to drill, the share whose well must be in the well list
TOLERANCE = (3, 0.08)  # a closed year may differ from the Board's own count by this many permits or this share, whichever is larger
BANDS = ("new", "inj", "rework", "amend", "other")  # redrill is null: the codes do not tell a re-entry

PERMIT_BAND = {"OPD": "new", "OPI": "inj",
               "OPDC": "rework", "OPDD": "rework", "OPDT": "rework", "CIP": "rework", "CPI": "rework", "WOP": "rework", "WOPH": "rework", "WOI": "rework", "WOIH": "rework",
               "COP": "amend", "COI": "amend"}
SERVICE = frozenset({"SWD", "EOR", "BDW", "FD", "GSR", "GSC", "GSCH", "LPG", "MON", "WS", "DWW"})  # well types of a service well; an OPD for one counts as injection
FLUID = {"OIL": "oil", "GAS": "gas", "DGW": "gas", "CO2": "other", "BPM": "other", "ST": "other", "CORE": "other"}  # DH (dry hole), EX, CA, NR and a well not in the list are unknown
NUMBER = re.compile(r"\d{4}-[A-Z][A-Z0-9]{1,5}-\d{1,5}")
CODE = re.compile(r"[A-Z][A-Z0-9]{1,5}")
SHEET_LINK = re.compile(r'href="(/MSOGBDocumentsShared/monthlypermits/Permit%20to%20Drill%20Monthly%20(\d{4})\.pdf)"')
CAPTION = re.compile(r"Total\s+(\d{4})\s*=\s*(\d+)")
log = C.log


class Disagrees(RuntimeError):
    """This file's count for a closed year is not the Board's: nothing is written."""


# ------------------------------------------------------------------------------------------------ the network

def polite_post(url, fields, max_bytes=20 * 1024 * 1024, timeout=180, tries=2, pause=3.0):
    """The body of one POST (form fields) as bytes, with polite_get's rules: a refusal raises Refused at once, only a dropped connection or a 5xx is tried again (once), TLS is verified and
    the proxy variables are honored, a body past max_bytes raises."""
    body = urllib.parse.urlencode(fields).encode("ascii")
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": C.UA, "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = r.read(max_bytes + 1)
            if len(out) > max_bytes:
                raise ValueError("the reply is larger than %d bytes" % max_bytes)
            return out
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 407, 429):
                raise C.Refused("HTTP %d from the server" % e.code)
            last = e
        except urllib.error.URLError as e:
            last = e
        except (OSError, ValueError) as e:
            if isinstance(e, ValueError):
                raise
            last = e
        if i + 1 < tries:
            time.sleep(pause * (i + 1))
    raise RuntimeError("could not read the source: " + C.privacy_check.clean_error(last))


def pdf_to_text(data):
    """The text of a PDF through `pdftotext -layout` (poppler-utils), in a new folder, under a timeout. The PDF is data: nothing else opens it."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    with tempfile.TemporaryDirectory(prefix="ms-") as tmp:
        src = os.path.join(tmp, "sheet.pdf")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-layout", src, "-"], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")}, cwd=tmp)
        if r.returncode != 0:
            raise RuntimeError("pdftotext could not read a sheet")
        return r.stdout


# ------------------------------------------------------------------------------------------------ the register (Permit Search)

def search_sql(first, last):
    """The Permit Search page's own query for a date range with no other filter (its makeQuery() builds exactly this, with all its columns; only the six needed are asked for). The only
    variable parts are two dates, written by date.isoformat(): digits and dashes."""
    return ("SELECT DISTINCT  CONVERT(date, ApprovedDate) as ApprovedDte, Permit, WellID, EntityName, CountyName, PermitType FROM rptPermit WHERE (1=1) "
            "and (ApprovedDate >= '%s') and (ApprovedDate <= '%s')  ORDER BY EntityName ASC,ApprovedDte Desc " % (first.isoformat(), last.isoformat()))


def parse_search(raw, today, min_rows=None):
    """[(day, well, operator, county, code)] of the register's reply, one per permit number, or RuntimeError when the reply is not the register. `well` is the Board's well number, used
    only to look the well's type up (and never kept)."""
    min_rows = MIN_ROWS if min_rows is None else min_rows
    first = date(int(C.FIRST_MONTH[:4]), int(C.FIRST_MONTH[5:]), 1)
    try:
        reply = json.loads(raw.decode("utf-8-sig"))
        data = reply["data"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("the Permit Search did not answer with its table (the reply is not the report's JSON)")
    if not isinstance(data, list):
        raise RuntimeError("the Permit Search reply has no list of rows")
    if reply.get("recordsTotal") != len(data):
        raise RuntimeError("the Permit Search reply holds %d rows but says %s: it was cut short" % (len(data), reply.get("recordsTotal")))
    if len(data) < min_rows:
        raise RuntimeError("the Permit Search holds %d permits since %s (thousands expected): not the register" % (len(data), C.FIRST_MONTH))
    out, seen = [], set()
    for row in data:
        if not (isinstance(row, list) and len(row) == 6 and all(isinstance(x, str) for x in row)):
            raise RuntimeError("a row of the Permit Search is not the six fields that were asked for")
        stamp, number, well, operator, county, code = [x.strip() for x in row]
        m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", stamp)
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except (AttributeError, ValueError):
            raise RuntimeError("an approval date in the Permit Search is not a day")
        if day > today or day < first:
            raise RuntimeError("an approval date in the Permit Search lies outside %s to today: %s" % (C.FIRST_MONTH, day.isoformat()))
        if not NUMBER.fullmatch(number) or not CODE.fullmatch(code):
            raise RuntimeError("a permit number or type in the Permit Search is not the shape it had")
        if number in seen:
            continue  # one permit counts once
        seen.add(number)
        out.append((day, well, html.unescape(operator), html.unescape(county), code))
    newest = max(d for d, *_ in out)
    if (today - newest).days > MAX_REGISTER_AGE:
        raise RuntimeError("the Permit Search's newest permit is %d days old: not a live register" % (today - newest).days)
    window = C.month_end(C.add_months(C.month_of(today), -25)) + timedelta(days=1)  # the 24 complete months before the current one, and a little more
    if sum(1 for d, _w, _o, _c, code in out if code in ("OPD", "OPI") and d >= window) < 10:
        raise RuntimeError("the Permit Search holds almost no original permits to drill in two years: not the register")
    return out


# ------------------------------------------------------------------------------------------------ the well list

def well_list_url(page, today):
    """The address of the newest dated Well info list on the Downloads page."""
    days = sorted(set(re.findall(r"/Downloads/WellInfoList/(\d{8})_All_WellInfoList\.csv", page)))
    if not days:
        raise RuntimeError("the Downloads page lists no Well info list: its layout may have changed")
    try:
        d = date(int(days[-1][:4]), int(days[-1][4:6]), int(days[-1][6:]))
    except ValueError:
        raise RuntimeError("the newest Well info list has no valid date in its name")
    if (today - d).days > MAX_LIST_AGE or d > today:
        raise RuntimeError("the newest Well info list on the Downloads page is dated %s: not current" % d.isoformat())
    return WELL_LIST % days[-1]


def well_types(raw, min_wells=None):
    """{well number: type code} (OIL, GAS, DH, SWD, MON...) of the well list. Only the number and the type are read; every other column is dropped on the spot."""
    min_wells = MIN_WELLS if min_wells is None else min_wells
    rd = csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace")))
    try:
        header = [h.strip() for h in next(rd)]
    except StopIteration:
        raise RuntimeError("the well list is empty")
    if "API10" not in header or "Type" not in header:
        raise RuntimeError("the well list's columns changed (API10 and Type are needed)")
    ia, it = header.index("API10"), header.index("Type")
    out = {}
    for row in rd:
        if len(row) <= max(ia, it):
            continue
        api, code = row[ia].strip(), row[it].split(" - ")[0].strip().upper()
        if re.fullmatch(r"\d{10}", api) and re.fullmatch(r"[A-Z0-9]{1,6}", code):
            out.setdefault(api, code)
    if len(out) < min_wells:
        raise RuntimeError("the well list holds %d wells (about 35,000 expected): cut short, or not the list" % len(out))
    if not {"OIL", "GAS", "DH"} <= set(out.values()):
        raise RuntimeError("the well list has no oil, gas or dry-hole wells: not the list")
    return out


def band_for(code, well_type):
    """A permit's band from its type code and (for an original permit to drill) the type of its well."""
    if code == "OPD":
        return "inj" if well_type in SERVICE else "new"
    return PERMIT_BAND.get(code, "other")


# ------------------------------------------------------------------------------------------------ the check against the Board's sheets

def captions(text, sheet_year):
    """{closed year: the Board's total} from a sheet's chart caption ("Total 2024 = 50 ... Total 2025 = 37"): every year before the sheet's own, which is final (the sheet's own year is open)."""
    return {int(y): int(n) for y, n in CAPTION.findall(text or "") if int(y) < sheet_year}


def sheet_check(ours, get, to_text, pause, today):
    """[(year, ours, the Board's)] for the closed years the Board's two newest sheets give a final total for. Raises Disagrees when one differs by more than the tolerance. A sheet that cannot be
    read (a scan, a new layout, a refusal) costs only the check: the register is the source, the sheets are a second opinion."""
    found = []
    try:
        listing = get(SHEETS, max_bytes=1_000_000).decode("utf-8", "replace")
        urls = {int(y): BASE + p for p, y in SHEET_LINK.findall(listing)}
        for y in sorted(urls)[-2:]:
            time.sleep(pause)
            for yr, n in captions(to_text(get(urls[y], max_bytes=3_000_000)), y).items():
                found.append((yr, n))
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        log("MS: the Board's yearly sheets could not be read (%s); the cross-check is skipped" % C.privacy_check.clean_error(e, 80))
    out = []
    for yr, n in sorted(set(found)):
        if yr in ours and yr < today.year:
            out.append((yr, ours[yr], n))
    for yr, mine, board in out:
        if abs(mine - board) > max(TOLERANCE[0], math.ceil(TOLERANCE[1] * board)):
            raise Disagrees("%d: this file counts %d new and injection permits (less monitor wells) and the Board's own yearly sheet says %d" % (yr, mine, board))
    if not out:
        log("MS: no closed year could be checked against the Board's yearly sheets")
    return out


# ------------------------------------------------------------------------------------------------ the producer

def build(get=C.polite_get, post=polite_post, to_text=pdf_to_text, pause=PAUSE, today=None, min_rows=None, min_wells=None):
    today = today or date.today()
    first = date(int(C.FIRST_MONTH[:4]), int(C.FIRST_MONTH[5:]), 1)
    raw = post(API, {"QueryToExcute": base64.b64encode(search_sql(first, today).encode("ascii")).decode("ascii")})
    permits = parse_search(raw, today, min_rows)
    time.sleep(pause)
    url = well_list_url(get(DOWNLOADS, max_bytes=2_000_000).decode("utf-8", "replace"), today)
    time.sleep(pause)
    types = well_types(get(url, max_bytes=60 * 1024 * 1024, timeout=240), min_wells)
    originals = [w for _d, w, _o, _c, code in permits if code == "OPD" and w]
    if originals and sum(1 for w in originals if w in types) < JOIN_SHARE * len(originals):
        raise RuntimeError("the well list knows only %d of %d wells with an original permit to drill: not the list these permits belong to" % (sum(1 for w in originals if w in types), len(originals)))
    t = C.Tally(STATE, bands=BANDS, fluid=True)
    monitor = {}  # year -> original permits for a monitor well (the Board's sheet does not count the five of May 2025)
    for day, well, operator, county, code in permits:
        wt = types.get(well) if code == "OPD" else None
        band = band_for(code, wt)
        if code == "OPD" and wt == "MON":
            monitor[day.year] = monitor.get(day.year, 0) + 1
        if band == "new":
            t.add(day, "new", county=county or None, operator=operator, fluid=FLUID.get(types.get(well), "unknown"))
        else:
            t.add(day, band)
    unknown = sorted({code for _d, _w, _o, _c, code in permits if code not in PERMIT_BAND and code not in ("H2S", "PIT")})
    if unknown:
        log("MS: permit types the Board's code list or this producer does not know, counted as other: " + ", ".join(unknown))
    ours = {}
    for ym in C.month_list(C.FIRST_MONTH, C.month_of(today)):
        ours[int(ym[:4])] = ours.get(int(ym[:4]), 0) + t.m["new"].get(ym, 0) + t.m["inj"].get(ym, 0)
    for y in ours:
        ours[y] -= monitor.get(y, 0)
    time.sleep(pause)
    for yr, mine, board in sheet_check(ours, get, to_text, pause, today):
        log("MS: %d: %d new and injection permits (less monitor wells) against the Board's own yearly sheet: %d" % (yr, mine, board))
    note = ("Permits to drill, by the day the Board approved them, from its Permit Search report (the register of every permit it issues). New wells are original permits to drill an oil, gas, test or "
            "dry hole. Original permits for injection, disposal, gas or hydrogen storage and monitor wells count as injection (the well's type in the Board's well list decides). A re-entry is not told "
            "apart from a new drill. Reworks are workover, conversion and dual or triple completion permits; amendments are changes of operator, one permit per well, so one sale of many wells is a "
            "spike; other filings are H2S and pit permits. Counties and operators are those of the new wells. Fluid is the well's type in the well list: a well that came up dry is a dry hole there and "
            "counts as unknown. For each closed year the new and injection permits, less monitor wells, agree with the Board's own yearly Permits to Drill sheet to within a few permits (a run refuses to "
            "write if they differ by more). A month counts once it ended two weeks ago.")
    return t.document(agency="Mississippi State Oil and Gas Board", source_name="Permit Search report", source_url=PAGE, basis="approval date",
                      cadence="as permits are approved (the Board states no schedule)", measure="permits", lag_days=LAG_DAYS, asof=today, note=note)


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
