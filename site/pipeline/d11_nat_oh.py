#!/usr/bin/env python3
"""D11: Ohio's permits (Division of Oil and Gas Resources Management, ODNR), for the National report of the Oil tracker.

The Division's Oil & Gas Well Database has a "Permit and Plug List" (https://apps.ohiodnr.gov/oilgas/rbdmsreports/Downloads_PermitAndPlug.aspx): an ASP.NET search form (free, no login) that
lists every permit application by the day it was ISSUED, with a button "Export To Excel" that gives the whole result, not just the 25 rows of a page, as an old binary .xls (BIFF8, which
KY's reader in `d11_nat_ky.py` already opens). This producer submits the form the way a browser does and reads that export:

  1. GET the page (the hidden ASP.NET fields and the server's own session cookie);
  2. POST the search for a window of issue dates with "Permit or Plug" set to Permit (the Division's own split: plug permits are a different list and are not counted here);
  3. check the grid's own total ("Item 1 to 25 of N");
  4. POST the same window with the Export To Excel button, and check the file holds exactly N rows, every issue date inside the window, and every application type known here.

Three facts found by looking (2026-11-01), each of which the producer guards:
  - the grid and the export CAP a search at 1,000 rows (all of 2019 to 2026 reported exactly 1,000): a window that reports 1,000 or more is split in two and read as two, and a one-week window
    that still reports 1,000 fails the run; a full year is about 430 permits, so the normal windows are a year and never come near the cap;
  - the server now and then answers a request with a redirect to the agency's home page instead of the page (about one request in four from this machine, at every pace tried): the request is
    made again after a pause, three times at most, and if every try is redirected the run ends as a refusal (exit 2: the committed file stays), never as a loop;
  - the export holds the same 70 columns as the grid, including the operator's mailing address, phone numbers, a company representative and the PM_* contact: the reader keeps six columns
    (issue date, application type, its words, county, operator, proposed well type) and nothing else leaves the function that reads the file.

What is counted: a permit APPLICATION ISSUED, by DT_APP_ISSUED (`measure="permits"`, basis "issue date"), Permit list only, 2019 to the newest complete month. A re-issued permit for a well is a
second permit (in `amend`). The bands are written out in BAND below, one line per application type (APP_TYP) the list uses; a type that is not in the table fails the run (it is never
filed as `other` quietly). What the list cannot tell: the fluid of a well (its well type is "OG", oil and gas, for nearly every well), so `fluid` is null. Every band is told, so none is null.

A weekly run reads the newest REREAD months again (permits are issued late in the week and a month's count can move) and keeps the older months from the committed file; with no committed file
it reads the whole history in year-long windows (about 17 requests, 6 seconds apart). Requests identify no person; the file is parsed as data, never opened by anything else.

  python3 -I site/pipeline/d11_nat_oh.py [--check]
"""
import http.cookiejar
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import d11_nat_ky as KY  # noqa: E402  (its OLE2 reader: the export is the same old Excel format)

STATE = "OH"
PAGE = "https://apps.ohiodnr.gov/oilgas/rbdmsreports/Downloads_PermitAndPlug.aspx"
HOST = "https://apps.ohiodnr.gov/"
PAUSE = 6.0  # seconds between two requests to the agency's server
RETRY_PAUSE = 45.0  # seconds before a redirected request is made again
TRIES = 3  # attempts at one request
CAP = 1000  # the grid and the export stop at 1,000 rows: a window that reports this many (or more) is not complete and is split
PAGE_SIZE = 25  # rows the grid shows on a page
REREAD = 14  # months read again each weekly run; older months come from the committed file
FIRST = date(2019, 1, 1)
MIN_ALL = 1500  # permits a full read must hold (about 430 a year: 2019 to 2026 holds about 3,000)
MIN_WINDOW = 200  # permits the weekly window (14 months, about 500) must hold
STALE_DAYS = 45  # the newest permit may not be older than this
MAX_PAGE = 3_000_000  # bytes: a results page is 180 KB
MAX_EXPORT = 20_000_000  # bytes: a year of permits is about 0.8 MB

P = "ctl00$ContentPlaceholder1$"  # the form's control names
I = "ctl00_ContentPlaceholder1_"  # and the ids its client-state fields are named after
START, END = "rdp_ApplicationIssuedStart", "rdp_ApplicationIssuedEnd"
SEARCH_BUTTON = (P + "btnSearch", "View Report")
EXPORT_BUTTON = re.compile(r'name="([^"]*\$b_export)"')
INFO = re.compile(r"Item <strong>(\d+)</strong> to <strong>(\d+)</strong> of <strong>(\d+)</strong>")
ROW = re.compile(r'<tr class="rg(?:Row|AltRow)"')
GRID = 'id="ctl00_ContentPlaceholder1_RG_Results_ctl00"'
# what the browser sends for the three boxes left empty (their placeholder text and its client state), and for "Permit" in the Permit or Plug list (captured from a real submit, 2026-11-01)
PLACEHOLDER = {"RN_SectionNumber": ("equals", {"enabled": True, "emptyMessage": "equals", "validationText": "", "valueAsString": "", "minValue": -70368744177664, "maxValue": 1000, "lastSetTextBoxValue": "equals"}),
               "txtLot": ("containing", {"enabled": True, "emptyMessage": "containing", "validationText": "", "valueAsString": "", "lastSetTextBoxValue": "containing"}),
               "txtCompanyName": ("containing", {"enabled": True, "emptyMessage": "containing", "validationText": "", "valueAsString": "", "lastSetTextBoxValue": "containing"})}
PERMIT_ONLY = {"enabled": True, "logEntries": [], "selectedIndex": 1, "selectedText": "Permit", "selectedValue": "Permit"}
RANGE = {"minDateStr": "1700-01-01-00-00-00", "maxDateStr": "2099-12-31-00-00-00"}
WANT = ("DT_APP_ISSUED", "APP_TYP", "APP_TYP_Description", "NAME", "CONAME", "PROP_WLTYPE")  # the only columns the reader keeps (the other 64 hold addresses, phones and contacts)
BANDS = C.BANDS  # every band is told


# ------------------------------------------------------------------------------------------------ the bands: one line per application type (APP_TYP) the list uses
# The code is APP_TYP, the words are APP_TYP_Description as the grid prints them (2019 to 2026; the drop-down on the page has a few more, never issued as permits). A type not in this
# table fails the run. `new` a permit to drill a new well; `inj` a new well for injection, disposal or enhanced recovery; `redrill` a re-entry or a deepening or a sidetrack of an existing
# well (the common definition: re-entry, deepening, sidetrack, re-drill); `rework` a conversion or a plug-back of an existing well; `amend` a re-issue or a revision of a permit already
# issued (revised location or unit, change of acreage): the same well counted again; `other` anything else.
BAND = {}  # filled below from TYPES


# ------------------------------------------------------------------------------------------------ one conversation with the server

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a redirect is an answer to look at, not a page to follow
        return None


class Client:
    """One session with the Permit and Plug List: the server's own cookies (kept in memory), a pause before every request, TLS always verified, the proxy variables honored.
    A redirect (the server's habit of sending a request to its home page now and then) is tried again after a pause, TRIES times in all; if every try is redirected the run is refused
    (`C.Refused`), and a 401, 403, 407 or 429 is refused at once and never repeated."""

    def __init__(self, opener=None, sleep=time.sleep, clock=time.monotonic, pause=PAUSE, retry_pause=RETRY_PAUSE):
        self.opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect)
        self.sleep, self.clock, self.pause, self.retry_pause = sleep, clock, pause, retry_pause
        self.last = None
        self.requests = 0

    def fetch(self, url, fields=None, max_bytes=MAX_PAGE):
        """The body of one request (a POST of `fields`, as a form, when given). Raises C.Refused or RuntimeError."""
        body = urllib.parse.urlencode(fields).encode("ascii") if fields is not None else None
        headers = {"User-Agent": C.UA}
        if body is not None:
            headers.update({"Content-Type": "application/x-www-form-urlencoded", "Referer": PAGE})
        moved = 0
        last = None
        for attempt in range(TRIES):
            if self.last is not None:
                wait = (self.retry_pause if attempt else self.pause) - (self.clock() - self.last)
                if wait > 0:
                    self.sleep(wait)
            self.last = self.clock()
            self.requests += 1
            try:
                with self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=180) as r:
                    data = r.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise RuntimeError("the reply is larger than %d bytes" % max_bytes)
                return data
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 407, 429):
                    raise C.Refused("HTTP %d from the server" % e.code)
                if 300 <= e.code < 400:
                    moved += 1
                    last = "redirected to %s" % re.sub(r"[?#].*", "", e.headers.get("Location", "somewhere") or "somewhere")[:60]
                else:
                    last = "HTTP %d" % e.code
            except urllib.error.URLError as e:
                last = "could not connect (%s)" % type(getattr(e, "reason", e)).__name__
            except OSError as e:  # a dropped connection or a cut-off read
                last = "the connection failed (%s)" % type(e).__name__
        if moved == TRIES:
            raise C.Refused("the server redirected all %d tries to another page (%s)" % (TRIES, last))
        raise RuntimeError("could not read the source: " + last)


# ------------------------------------------------------------------------------------------------ the form

class _Inputs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inputs = []  # (name, type, value)

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            a = dict(attrs)
            if a.get("name"):
                self.inputs.append((a["name"], (a.get("type") or "text").lower(), a.get("value") or ""))

    handle_startendtag = handle_starttag


def inputs(html):
    p = _Inputs()
    p.feed(html)
    return p.inputs


def form_fields(html, start, end, button, filter_permits=True):
    """The fields a browser posts for this page with `start` and `end` typed into the two date boxes and `button` ((name, value)) clicked: every hidden field of the page as it is, then the two
    date pickers (the display text, the ISO stamp and the picker's client state), the three empty boxes with their placeholders, the Permit or Plug list on Permit, and the button."""
    found = inputs(html)
    names = {n for n, _t, _v in found}
    fields = {n: v for n, t, v in found if t == "hidden"}
    for need in ("__VIEWSTATE", "__EVENTVALIDATION", P + START + "$dateInput", P + END + "$dateInput", SEARCH_BUTTON[0]):
        if need not in names:
            raise RuntimeError("the search form has changed: no field %s" % need.split("$")[-1])
    for key, day, word in ((START, start, "start"), (END, end, "end")):
        iso, mdy = day.isoformat(), "%d/%d/%d" % (day.month, day.day, day.year)
        fields.update({P + key: iso, P + key + "$dateInput": mdy, I + key + "_calendar_SD": "[]", I + key + "_ClientState": json.dumps(RANGE, separators=(",", ":")),
                       I + key + "_dateInput_ClientState": json.dumps({"enabled": True, "emptyMessage": word, "validationText": iso + "-00-00-00", "valueAsString": iso + "-00-00-00",
                                                                        "minDateStr": RANGE["minDateStr"], "maxDateStr": RANGE["maxDateStr"], "lastSetTextBoxValue": mdy}, separators=(",", ":"))})
    for key, (text, state) in PLACEHOLDER.items():
        fields[P + key] = text
        fields[I + key + "_ClientState"] = json.dumps(state, separators=(",", ":"))
    if filter_permits:
        fields[I + "ddlPermitOrPlug_ClientState"] = json.dumps(PERMIT_ONLY, separators=(",", ":"))
    fields[button[0]] = button[1]
    return fields


def grid_total(html):
    """N, the number of permits the search found, from a results page: the grid's own "Item 1 to 25 of N", or, when there is no pager (25 rows or fewer), the rows themselves.
    A page with no grid, a pager that does not start at 1 or a count that does not match the rows shown raises RuntimeError."""
    if GRID not in html:
        raise RuntimeError("the reply is not the Permit and Plug List (no results grid): the server may have sent its home page or an error")
    shown = len(ROW.findall(html))
    m = INFO.search(html)
    if m:
        a, b, n = (int(x) for x in m.groups())
        if a != 1 or b - a + 1 != shown or n < shown:
            raise RuntimeError("the grid's count does not match its rows (items %d to %d of %d, %d rows shown)" % (a, b, n, shown))
        return n
    if shown > PAGE_SIZE:
        raise RuntimeError("the grid shows %d rows with no pager" % shown)
    return shown


# ------------------------------------------------------------------------------------------------ the export (.xls) -> the six columns

def read_export(data):
    """Rows (dicts of the WANT columns, text) of the Excel export, and nothing else. The file is the old binary format with its cells as inline text (LABEL) and numbers (NUMBER); the header is the
    first row that names DT_APP_ISSUED and APP_TYP. Raises ValueError for anything that is not that (a page of HTML, a cut-short file, a layout that changed)."""
    if data[:8] != KY.OLE_MAGIC:
        raise ValueError("the export is not an Excel file (a page of HTML?)")
    try:
        stream = KY.ole_stream(data)
        labels, numbers = {}, {}
        for rid, d in KY.records(stream):
            if rid == 0x0204:  # LABEL: row, column, format, length, then (unless the text is empty) a flag byte and the characters
                r, c, _xf, cch = struct.unpack_from("<HHHH", d, 0)
                if cch and len(d) < 9:
                    raise ValueError("a text cell is cut short")
                wide = cch and d[8] & 1
                text = "" if not cch else d[9:9 + 2 * cch].decode("utf-16-le", "replace") if wide else d[9:9 + cch].decode("latin-1")
                if cch and len(text) < cch:
                    raise ValueError("a text cell is cut short")
                labels[(r, c)] = text
            elif rid == 0x0203:  # NUMBER
                r, c, _xf, x = struct.unpack_from("<HHHd", d, 0)
                numbers[(r, c)] = KY.num_text(x)
    except (struct.error, IndexError, KeyError, UnicodeError, OverflowError) as e:
        raise ValueError("the export is not a readable .xls workbook (%s)" % type(e).__name__)
    head = next((r for r in sorted({r for r, _c in labels} ) if r < 20 and {"DT_APP_ISSUED", "APP_TYP"} <= {v.strip() for (rr, _c), v in labels.items() if rr == r}), None)
    if head is None:
        raise ValueError("the export has no header row with DT_APP_ISSUED and APP_TYP")
    cols = {}
    for (r, c), v in labels.items():
        if r == head and v.strip() in WANT and v.strip() not in cols:
            cols[v.strip()] = c
    if set(WANT) - set(cols):
        raise ValueError("columns not in the export: %s" % ", ".join(sorted(set(WANT) - set(cols))))
    keep = {c: h for h, c in cols.items()}
    rows = {}
    for cells in (labels, numbers):
        for (r, c), v in cells.items():
            if r > head and c in keep:
                rows.setdefault(r, {})[keep[c]] = v
    labels = numbers = None  # the addresses and phone numbers the file also held are dropped here
    return [{h: rows[r].get(h, "") for h in WANT} for r in sorted(rows)]


# ------------------------------------------------------------------------------------------------ one window of issue dates

class Overfull(RuntimeError):
    """The search reports as many rows as the server's cap: the window is not complete and must be split."""


def read_window(client, form, start, end):
    """The rows (dicts of the WANT columns) of every permit issued from `start` to `end` inclusive. Two requests: the search (whose total and result page are checked) and the export, whose rows must
    be exactly the total and every date inside the window. Raises Overfull when the total reaches the cap."""
    page = client.fetch(PAGE, form_fields(form, start, end, SEARCH_BUTTON)).decode("utf-8", "replace")
    n = grid_total(page)
    if n >= CAP:
        raise Overfull("%d permits from %s to %s: the search is capped at %d rows" % (n, start, end, CAP))
    if n == 0:
        return []
    button = EXPORT_BUTTON.search(page)
    if not button:
        raise RuntimeError("the results page has no Export To Excel button: the form has changed")
    body = client.fetch(PAGE, form_fields(page, start, end, (button.group(1), "Export To Excel")), max_bytes=MAX_EXPORT)
    try:
        rows = read_export(body)
    except ValueError as e:
        raise RuntimeError("%s to %s: %s" % (start, end, e))
    if len(rows) != n:
        raise RuntimeError("the export from %s to %s holds %d permits but the grid counted %d" % (start, end, len(rows), n))
    return rows


def read_range(client, form, start, end, out, depth=0):
    """Reads [start, end] into `out` (a list of (day, row)): one window, or, when the search is capped, its two halves (down to a single week: a week that is capped is an error)."""
    try:
        rows = read_window(client, form, start, end)
    except Overfull as e:
        if (end - start).days < 7 or depth > 8:
            raise RuntimeError("a window of %d days is still capped (%s)" % ((end - start).days + 1, e))
        mid = start + timedelta(days=(end - start).days // 2)
        read_range(client, form, start, mid, out, depth + 1)
        read_range(client, form, mid + timedelta(days=1), end, out, depth + 1)
        return
    for row in rows:
        day = C.parse_day(row["DT_APP_ISSUED"], date.today() + timedelta(days=1))
        if day is None or not start <= day <= end:
            raise RuntimeError("a permit's issue date (%r) is unreadable or outside the window %s to %s" % (row["DT_APP_ISSUED"][:12], start, end))
        out.append((day, row))


def year_windows(first, last):
    """Windows of a calendar year (the first and last may be part of one)."""
    out, y = [], first.year
    while y <= last.year:
        out.append((max(first, date(y, 1, 1)), min(last, date(y, 12, 31))))
        y += 1
    return out


# ------------------------------------------------------------------------------------------------ the committed file, and the build

def previous(path=None):
    """{band: {month: count}} from the committed nat/OH.json when it is a complete one from 2019-01 (every band told), else {}."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        if months[0] != C.FIRST_MONTH or any(not isinstance(bands.get(b), list) or len(bands[b]) != len(months) for b in BANDS):
            return {}
        return {b: dict(zip(months, bands[b])) for b in BANDS}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def classify(row):
    """(band, 'new' or other, the county, the operator) of one permit row; raises RuntimeError for an application type this table does not know."""
    code = row["APP_TYP"].strip()
    if code in PLUG_TYPES:
        raise RuntimeError("the Permit list returned a plug permit (%s): the Permit or Plug filter was not applied" % code)
    if code not in BAND:
        raise RuntimeError("an application type this producer does not know: %r (%s): add it to BAND" % (code, row["APP_TYP_Description"].strip()[:50]))
    band = BAND[code]
    if band == "new" and re.search(r"inject|dispos|storage|\bswd\b|\bgs\b|\beor\b", row["PROP_WLTYPE"], re.I):  # a new-well permit for a service well (injection, disposal, gas storage)
        band = "inj"
    return band


def build(client=None, old=None, today=None, windows=None):
    today = today or date.today()
    client = client or Client()
    old = previous() if old is None else old
    cut_month = C.add_months(C.month_of(today), -REREAD)
    last_old = max(old["new"]) if old else None
    carry = bool(old) and all(ym in old[b] for b in BANDS for ym in C.month_list(C.FIRST_MONTH, C.add_months(cut_month, -1))) and last_old is not None and last_old >= C.add_months(cut_month, -1)
    first = date(int(cut_month[:4]), int(cut_month[5:]), 1) if carry else FIRST
    form = client.fetch(PAGE).decode("utf-8", "replace")
    if "Permit and Plug List" not in form or GRID in form:
        raise RuntimeError("the page is not the Permit and Plug List search form (the server may have sent its home page)")
    form_fields(form, first, today, SEARCH_BUTTON)  # fails here, before any search, if the form has changed
    got = []
    for a, b in (windows or year_windows(first, today)):
        read_range(client, form, a, b, got)
    if len(got) < (MIN_WINDOW if carry else MIN_ALL):
        raise RuntimeError("only %d permits were read (expected %d or more): the list may have changed" % (len(got), MIN_WINDOW if carry else MIN_ALL))
    newest = max(d for d, _r in got)
    if (today - newest).days > STALE_DAYS:
        raise RuntimeError("the newest permit was issued on %s: the list may have stopped being updated" % newest.isoformat())
    t = C.Tally(STATE, bands=BANDS, fluid=False)
    if carry:  # months before the window: the committed counts, at mid-month
        for b in BANDS:
            for ym, n in old[b].items():
                if ym < cut_month and n:
                    t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    no_county = 0
    for day, row in sorted(got, key=lambda x: x[0]):
        band = classify(row)
        county = row["NAME"].strip()
        no_county += not county
        t.add(day, band, county=county or None, operator=row["CONAME"].strip() or None)
    if no_county > max(5, len(got) // 10):
        raise RuntimeError("%d of %d permits have no county: a column may have been renamed" % (no_county, len(got)))
    note = ("Permits issued, by the day each was issued, from the Division's Permit and Plug List (Oil & Gas Well Database): the Permit list, which leaves out permits to plug a well. "
            "A new-well permit is a new well (a horizontal or a vertical one; a well type of injection, disposal or gas storage makes it an injection and disposal well); re-entries and deepenings are re-entries; "
            "plug-backs and conversions are reworks; a re-issued permit, a revised location or unit and a change of acreage are amendments (the same well counted again). "
            "The list does not say whether a well is oil or gas (its well type is oil and gas for nearly every well), so the fluid split is not available. "
            "A month is shown once a permit has been issued after it.")
    return t.document(agency="Ohio Department of Natural Resources, Division of Oil and Gas Resources Management", source_name="Permit and Plug List (Oil & Gas Well Database, Excel export of the Permit list)", source_url=PAGE,
                      basis="issue date (the day the permit was issued)", cadence="a live database, current to the day each permit is issued (read weekly here)", measure="permits", asof=newest, note=note)


# the table itself (below the code that uses it so that the bands read as one list)
TYPES = ()
PLUG_TYPES = frozenset()

if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
