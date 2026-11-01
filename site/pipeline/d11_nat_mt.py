#!/usr/bin/env python3
"""D11: Montana's well permits (Board of Oil and Gas Conservation, MBOGC), for the National report of the Oil tracker.

Where the dates are. The Board's weekly activity letters (one PDF a week) are the public notice of each approval, but the folder that serves them holds only the current year (2026: 42 letters; its
2025 and 2024 folders are empty), and the monthly well zips carry only the date a well was permitted for the wells that still exist (an expired or never-drilled permit is gone from them: 27, 34, 45
permits a year against the Board's 37, 41, 53). The Board's Dataminer (https://bogapps.dnrc.mt.gov/dataminer/) is the full record. Its "Permits" page shows only the last 24 months and misses some
approvals, but its "Well History" page lists every event on every well with the day it was approved (`Dt_Effect`, "Date Approved") and a type of work, back to the start of the file, and offers the
result as a CSV export. This asks that page for everything approved after 12/31/2018, the way the page's own form does (four requests, three seconds apart: the page, the choice of the date field, the
search, the export), and counts the permit events by the day they were approved: `measure` "permits", `basis` "approval date". What it counts (the Board's own words for the type of work):

  - `new`:     "Permit to Drill" and "Permit to Drill, Horizontal" (a vertical or a horizontal new well), `fluid` from the well's type (oil, gas, coal bed methane as gas; a well that came in dry is unknown);
  - `inj`:     the same two permit types where the well's type is injection, disposal, gas storage, monitor or a water well;
  - `redrill`: "Permit, Re-enter Abandoned Well", "Permit, Redrill or Deepen", "Permit, Horizontally Re-drill Existing Well" and "New Horiz. Laterals or Extensions";
  - `amend`:   "Re-permit (To Drill or Re-enter)" (a permit that lapsed and was approved again for the same location: the Board's "re-issued permits"), "Permit Modification" and "Correction or
               Modification to Permit";
  - `rework` and `other` are not available (null): workovers, recompletions, plugbacks and conversions are filed on sundry notices ("Intent, Recomplete", "Intent, Plugback"...), which are not permits
               and are not counted, and every other kind of permit the Board files is named above.
Everything else in the history (notices of intent and subsequent reports, completions, spuds, plugging, changes of bonded operator, expiry dates...) is not a permit and is skipped. A permit type this
file does not know fails the run (a silent drop would read as a fall). A re-drill the Board files under an ordinary horizontal permit type is counted as new (the type of work cannot tell).

The Board's annual reviews give the check: its "Wells Permitted" (new vertical, new horizontal and re-entry of abandoned wells together) is 79, 37, 41, 54 and 58 for 2019 to 2023, with these exact
splits, and 67 for 2024; and its "Re-issued Permits" are 37, 50, 79, 52, 48 and 47 for 2019 to 2024. The history has the same figures for every one of them but 2024's wells permitted (66 against 67:
one horizontal permit); of the twenty quarters of the review's own five-year table (2020 to 2024) eighteen are equal and two (2022 Q3, 2023 Q2) are one below the history, as the table is one below the
review's own headline in those years. Against the 42 weekly letters of 2026, 218 of 225 permit entries match an event of this file by API number, date and type (the letters list six permits
twice, and the history has 14 approvals no letter lists). The totals above are of the permit types the review counts: this file's bands add the other re-drill types and the modifications.

Montana is small and, in 2026, busy: 37 to 66 permits to drill a year from 2020 to 2024 and 62 in 2025, then 186 in the first ten months of 2026 (two Williston Basin counties, Richland and Roosevelt,
hold most of them). The Board's database is updated as approvals are entered, its letter follows each Friday, and the newest month is shown only a week after it ends (`lag_days`).

Nothing leaves the export but the day, the type of work, the well's type, the county and the operator (published only if it is a corporation, LLC or partnership); the API number, well name, location,
status, field and the free-text comment are never read into a record, and the export is parsed in memory and never written. A well's type and an operator are the Board's record today. Requests
identify no person; the search is a read-only query; the session cookie the Dataminer sets is held in memory for the four requests.

  python3 -I site/pipeline/d11_nat_mt.py [--check]
"""
import collections
import csv
import html as htmllib
import http.cookiejar
import io
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import privacy_check  # noqa: E402

STATE = "MT"
BASE = "https://bogapps.dnrc.mt.gov/dataminer/"
PAGE = BASE + "Wells/WellHistory.aspx"
EXPORT = BASE + "Export.aspx?type=csv"
FORM = "ctl00$SiteContentPlaceHolder$FormFilterNoNav1$"  # the prefix of the page's form controls
FIELD = "Dt_Effect|date"  # "Date Approved"
SINCE = "12/31/2018"  # the search is "Date Approved after" this day: January 2019 on
PAUSE = 3.0
LAG_DAYS = 7  # the newest month is complete a week after it ends (the weekly letter follows each Friday)
MIN_ROWS = 5000  # about 19,800 events since 2019 when written (all kinds of work)
MIN_PERMITS = 300  # about 1,000 permit events since 2019 when written
MAX_AGE_DAYS = 90  # the newest permit event must be this recent
MIN_YEAR_PERMITS = 15  # a whole year with fewer permits to drill than this is a source that lost its history (37 in the quietest year, 2020)
MAX_UNDATED = 3  # permit events whose date is blank, junk or in the future (none when written)
NEEDED = ("Dt_Effect", "Typ_Work", "Well_Type", "County", "CoName")
MAX_PAGE = 3_000_000  # a page of the Dataminer is about 50 KB
MAX_EXPORT = 60_000_000  # the export is about 4.4 MB

# the Board's own words for a type of work, lower case with the spaces squeezed
NEW_TYPES = frozenset({"permit to drill", "permit to drill, horizontal"})
REDRILL_TYPES = frozenset({"permit, re-enter abandoned well", "permit, redrill or deepen", "permit, horizontally re-drill existing well", "new horiz. laterals or extensions"})
AMEND_TYPES = frozenset({"re-permit (to drill or re-enter)", "permit modification", "correction or modification to permit"})
KNOWN = NEW_TYPES | REDRILL_TYPES | AMEND_TYPES
SERVICE = re.compile(r"inject|dispos|storage|monitor|observ|water|brine|geothermal", re.I)  # a service well: the well's type (Injection - Disposal, Gas Storage, Monitor/Observation, Water Source...)
PERMITISH = re.compile(r"permit|\bapd\b", re.I)  # a type of work that names a permit
EXPIRY = re.compile(r"expire", re.I)  # "Expired Permit" and "Date Well Permit Expires" are not permits


def norm(text):
    return " ".join((text or "").lower().split())


def band_of_event(work, well_type):
    """The band of one event in the well history from its type of work and the well's type; None when the event is not a permit."""
    w = norm(work)
    if w in AMEND_TYPES:
        return "amend"
    if w in REDRILL_TYPES:
        return "redrill"
    if w in NEW_TYPES:
        return "inj" if SERVICE.search(well_type or "") else "new"
    return None


def is_unknown_permit(work):
    """True for a type of work that names a permit but is none of the kinds this file counts (the Board added one: look before counting or dropping it)."""
    w = norm(work)
    return w not in KNOWN and bool(PERMITISH.search(w)) and not EXPIRY.search(w)


# ------------------------------------------------------------------------------------------------ the Dataminer, the way its form is used

class Dataminer:
    """One session with the Board's Dataminer: the cookie it sets is kept for the few requests, each one three seconds after the last. `__call__(url, fields=None, max_bytes=...)` returns the
    body (a POST when `fields` is given). A refusal (401, 403, 407, 429) raises C.Refused at once; a 5xx or a dropped connection is tried once more; TLS is verified and the proxy variables honored."""

    def __init__(self, pause=PAUSE, timeout=120, tries=2):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.pause, self.timeout, self.tries, self.n = pause, timeout, tries, 0

    def __call__(self, url, fields=None, max_bytes=MAX_PAGE):
        if self.n:
            time.sleep(self.pause)
        self.n += 1
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None
        headers = {"User-Agent": C.UA}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if self.n > 1:
            headers["Referer"] = PAGE
        last = None
        for i in range(self.tries):
            try:
                with self.opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=self.timeout) as r:
                    body = r.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ValueError("the reply is larger than %d bytes" % max_bytes)
                return body
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 407, 429):
                    raise C.Refused("HTTP %d from the server" % e.code)
                last = e
            except urllib.error.URLError as e:
                last = e
            except ValueError:
                raise
            except OSError as e:  # a dropped connection or a cut-off read
                last = e
            if i + 1 < self.tries:
                time.sleep(self.pause * (i + 1))
        raise RuntimeError("could not read the source: " + privacy_check.clean_error(last))


def attr(tag, name):
    m = re.search(r'\b%s\s*=\s*"([^"]*)"' % name, tag, re.I)
    return htmllib.unescape(m.group(1)) if m else None


def hidden_fields(page):
    """{name: value} of the page's hidden inputs (the view state and the event validation an ASP.NET page wants back)."""
    out = {}
    for tag in re.findall(r"<input\b[^>]*>", page, re.I):
        if (attr(tag, "type") or "").lower() == "hidden" and attr(tag, "name"):
            out[attr(tag, "name")] = attr(tag, "value") or ""
    return out


def select_values(page, name):
    """The option values of one <select> on the page, or None when it is not there."""
    m = re.search(r'<select\b[^>]*\bname="%s"[^>]*>([\s\S]*?)</select>' % re.escape(name), page, re.I)
    return [htmllib.unescape(v) for v in re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', m.group(1), re.I)] if m else None


def read_export(fetch):
    """The CSV export (bytes) of the well history for every event approved after SINCE: the page, the choice of the date field (the page posts back to offer 'after'), the search, the export.
    Each step is checked, so a page that changed shape fails here and not later as a short file."""
    page = fetch(PAGE).decode("utf-8", "replace")
    f = hidden_fields(page)
    if not f.get("__VIEWSTATE") or not f.get("__EVENTVALIDATION") or FIELD not in (select_values(page, FORM + "cboFilterOption") or []) or "Export.aspx?type=csv" not in page:
        raise RuntimeError("the Dataminer's Well History page is not the page this expects: its layout may have changed")
    f.update({FORM + "cboFilterOption": FIELD, FORM + "cboFilterType": "=", FORM + "txtFilter": "", FORM + "txtFilterString": "", "__EVENTTARGET": FORM + "cboFilterOption"})
    page = fetch(PAGE, fields=f).decode("utf-8", "replace")  # choosing a date field makes the page offer 'Prior To / Equal To / After'
    if ">" not in (select_values(page, FORM + "cboFilterType") or []):
        raise RuntimeError("the Dataminer's date filter no longer offers 'After': its layout may have changed")
    f = hidden_fields(page)
    f.update({FORM + "cboFilterOption": FIELD, FORM + "cboFilterType": ">", FORM + "txtFilter": SINCE, FORM + "txtFilterString": "", FORM + "btnSearch": "Search"})
    page = fetch(PAGE, fields=f).decode("utf-8", "replace")
    shown = re.search(r'name="%stxtFilterString"[^>]*\bvalue="([^"]*)"' % re.escape(FORM), page)
    shown = htmllib.unescape(shown.group(1)) if shown else ""
    if "Date Approved" not in shown or SINCE not in shown:
        raise RuntimeError("the Dataminer did not take the search (its filter reads %r)" % shown[:60])
    err = re.search(r'lblError"[^>]*>([^<]+)<', page)
    if err and err.group(1).strip():
        raise RuntimeError("the Dataminer answered the search with an error: " + privacy_check.clean_error(err.group(1), 80))
    return fetch(EXPORT, max_bytes=MAX_EXPORT)


def parse_export(data, today=None):
    """(events, stats) from the export. `events` are dicts {day, band, county, operator, fluid}, one for each permit event; nothing else of a row is read into one. `stats` counts what was skipped.
    Raises when the file is not the well history (an error page, a missing column), or names a kind of permit this does not know."""
    today = today or date.today()
    text = data.decode("utf-8-sig", "replace")
    head = text[:600].lower()
    if "content must be selected" in head or "<html" in head:
        raise RuntimeError("the Dataminer's export is not the CSV (it answered: %s)" % privacy_check.clean_error(text[:60]))
    rd = csv.reader(io.StringIO(text))
    try:
        header = [h.strip() for h in next(rd)]
    except StopIteration:
        raise RuntimeError("the Dataminer's export is empty")
    missing = [c for c in NEEDED if c not in header]
    if missing:
        raise RuntimeError("the Dataminer's export has no %s column: its layout may have changed" % ", ".join(missing))
    ix = {c: header.index(c) for c in NEEDED}
    width = max(ix.values())
    events, rows, unknown, undated, short = [], 0, collections.Counter(), 0, 0
    for row in rd:
        if not any(c.strip() for c in row):
            continue
        rows += 1
        if len(row) <= width:
            short += 1
            continue
        work, well_type = row[ix["Typ_Work"]], row[ix["Well_Type"]]
        band = band_of_event(work, well_type)
        if band is None:
            if is_unknown_permit(work):
                unknown[norm(work)[:50]] += 1
            continue
        day = C.parse_day(row[ix["Dt_Effect"]], today=today)
        if day is None or day < date(2019, 1, 1):
            undated += 1
            continue
        events.append({"day": day, "band": band, "county": row[ix["County"]].strip(), "operator": row[ix["CoName"]].strip(), "fluid": C.fluid_of(well_type) if band == "new" else None})
    if unknown:
        raise RuntimeError("a kind of permit this does not know is in the history: %s" % ", ".join("%r (%d)" % kv for kv in unknown.most_common(3)))
    if short > 0.01 * max(rows, 1):
        raise RuntimeError("%d of %d rows are shorter than the header: the export's layout may have changed" % (short, rows))
    return events, {"rows": rows, "undated": undated, "short": short}


def guard(events, stats, today):
    """Refuses an export that is not the whole history: too few rows or permits, a newest permit that is old, a year with almost none, a work type that vanished."""
    if stats["rows"] < MIN_ROWS:
        raise RuntimeError("the export has %d events (expected %d or more): the search may have been cut short" % (stats["rows"], MIN_ROWS))
    if stats["undated"] > MAX_UNDATED:
        raise RuntimeError("%d permit events have no usable date: the export's layout may have changed" % stats["undated"])
    if not events:
        raise RuntimeError("no permit in the export: the type of work may have been renamed")
    newest, oldest = max(e["day"] for e in events), min(e["day"] for e in events)
    if newest < today - timedelta(days=MAX_AGE_DAYS):
        raise RuntimeError("the newest permit is dated %s: the history looks stale" % newest.isoformat())
    if oldest > date(2019, 6, 30):
        raise RuntimeError("the history starts only in %s: it no longer reaches back to 2019 (the Permits page shows 24 months only)" % oldest.isoformat())
    if len(events) < MIN_PERMITS:
        raise RuntimeError("only %d permit events in all (expected %d or more): the history may be cut short" % (len(events), MIN_PERMITS))
    drills = collections.Counter(e["day"].year for e in events if e["band"] in ("new", "inj"))
    for y in range(2019, newest.year):
        if drills[y] < MIN_YEAR_PERMITS:
            raise RuntimeError("only %d permits to drill in %d (expected %d or more): the history may be cut short" % (drills[y], y, MIN_YEAR_PERMITS))
    recent = [e for e in events if e["day"] >= newest - timedelta(days=730)]
    for band in ("new", "amend"):
        if not any(e["band"] == band for e in recent):
            raise RuntimeError("no %s permit in the last two years: a type of work may have been renamed" % band)


# ------------------------------------------------------------------------------------------------ the run

def build(fetch=None, today=None, pause=PAUSE):
    today = today or date.today()
    fetch = fetch or Dataminer(pause)
    events, stats = parse_export(read_export(fetch), today)
    guard(events, stats, today)
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "amend"), fluid=True)
    for e in events:
        t.add(e["day"], e["band"], county=e["county"], operator=e["operator"], fluid=e["fluid"])
    doc = t.document(
        agency="Montana Board of Oil and Gas Conservation (Department of Natural Resources and Conservation)", source_name="Dataminer, Well History (every event on every well, with the day it was approved)", source_url=PAGE,
        basis="approval date (the day the Board approved the permit)", cadence="as the Board enters approvals (its weekly activity letter follows each Friday)", measure="permits", lag_days=LAG_DAYS,
        note="Every permit the Board's well history shows, by the day it was approved: permits to drill (vertical and horizontal), injection, disposal and storage wells, re-entries and re-drills of existing wells, "
             "and, as amendments, re-issued permits (a lapsed permit approved again for the same location) and permit modifications. Workovers and recompletions are filed on notices, not permits, so those bands "
             "are not available. Checked against the Board's annual reviews: their counts of wells permitted (new vertical and horizontal wells and re-entries of abandoned wells) and of re-issued permits match this "
             "file for 2019 to 2023, and for 2024 the review counts one more well permitted. A well's type and its operator are the Board's record today. The newest month is shown a week after it ends.")
    C.log("%s: %d events read, %d permit events (%d new, %d injection, %d re-entry, %d amendment), newest %s, %d permit events undated"
          % (STATE, stats["rows"], len(events), *(sum(1 for e in events if e["band"] == b) for b in ("new", "inj", "redrill", "amend")), max(e["day"] for e in events).isoformat(), stats["undated"]))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
