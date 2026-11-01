#!/usr/bin/env python3
"""D11: Ohio's permits (Division of Oil and Gas Resources Management, ODNR), for the National report of the Oil tracker.

The Division's Oil & Gas Well Database has a "Permit and Plug List" (https://apps.ohiodnr.gov/oilgas/rbdmsreports/Downloads_PermitAndPlug.aspx): an ASP.NET search form (free, no login) that
lists the permit applications issued in a window of dates, with an "Export To Excel" button that gives the WHOLE result, not the 25 rows of a page, as an old binary .xls (BIFF8: the OLE2
reader of `d11_nat_ky.py` opens it). This producer submits the form the way a browser does and reads that export:

  1. GET the page (its hidden ASP.NET fields and the server's own session cookie);
  2. POST the search for a window of issue dates with "Permit or Plug" set to Permit (the Division's own split: permits to plug a well are the other list and are not counted here);
  3. check the grid's own total ("Item 1 to 25 of N");
  4. POST the same window with the Export To Excel button, and check the file holds exactly N rows, every issue date inside the window and every application type known here.

What was found by looking (2026-11-01), each guarded below:
  - the grid and the export CAP a search at 1,000 rows (all of 2019 to 2026 reported exactly 1,000): a window that reports 1,000 or more is split in two and read as two, and a one-week window
    that is still capped fails the run. A year is 350 to 550 rows, so the normal windows (a year, or 15 months for the weekly run) never come near the cap;
  - the export lists some applications TWICE, row for row the same in all 70 columns (68 of 540 rows in 2019, 27 of 429 in 2025: a join in the Division's query): the rows are counted once by their
    application number (APPNO, read only for that and never kept), and the grid's own total, which counts the repeats, is what the export is checked against;
  - the server now and then answers a request with a redirect to the agency's home page instead of the page (one request in three or four from this machine, at every pace tried; the same request
    made again after a pause is answered): it is made again after 45 seconds, four tries at most, and if every try is redirected the run ends as a refusal (exit 2: the committed file stays);
  - the export holds the same 70 columns as the grid, among them the operator's mailing address, phone numbers, a company representative and the PM_* contact: the reader keeps seven columns
    (issue date, application type and its words, county, operator, proposed well type, application number) and nothing else leaves the function that reads the file.

What is counted: a permit APPLICATION ISSUED, once, by DT_APP_ISSUED (`measure="permits"`, basis "issue date"), the Permit list only, 2019 to the newest complete month. The bands are written out in
TYPES below, one line for each application type (APP_TYP) the list has used since 2019 (35 of them); a type that is not in the table fails the run, it is never filed as `other` quietly. A new-well permit
for a gas-storage, test, salt-water or solution-mining well is told from the well type on the permit (WELL_TYPES). What the list cannot tell: the fluid of a well (its well type is "OG", oil and gas, for
nearly every well), so `fluid` is null. Every band is told, so none is null.

A weekly run reads the newest REREAD months again (permits are entered late and a month's count can move) and keeps the older months from the committed file; with no committed file it reads the whole
history in year-long windows (17 requests, 6 seconds apart: about 3 minutes, more when the server redirects). Requests identify no person; the file is parsed as data, never opened by anything else.

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
PAUSE = 6.0  # seconds between two requests to the agency's server
RETRY_PAUSE = 45.0  # seconds before a redirected request is made again
TRIES = 4  # attempts at one request
CAP = 1000  # the grid and the export stop at 1,000 rows: a window that reports this many (or more) is not complete and is split
PAGE_SIZE = 25  # rows the grid shows on a page
REREAD = 14  # months read again each weekly run; older months come from the committed file
FIRST = date(2019, 1, 1)
ONE_WINDOW_DAYS = 460  # a span up to this is read as one window (the weekly run's 15 months); longer ones in calendar years
MIN_ALL = 1500  # permits a full read must hold (2019 to 2026 holds about 2,950)
MIN_WINDOW = 200  # permits the weekly window (14 months, about 450) must hold
STALE_DAYS = 45  # the newest permit may not be older than this
MAX_PAGE = 3_000_000  # bytes: a results page is 180 KB
MAX_EXPORT = 20_000_000  # bytes: a year of permits is about 1 MB

P = "ctl00$ContentPlaceholder1$"  # the form's control names
I = "ctl00_ContentPlaceholder1_"  # and the ids its client-state fields are named after
START, END = "rdp_ApplicationIssuedStart", "rdp_ApplicationIssuedEnd"
SEARCH_BUTTON = (P + "btnSearch", "View Report")
EXPORT_BUTTON = re.compile(r'name="([^"]*\$b_export)"')
INFO = re.compile(r"Item <strong>(\d+)</strong> to <strong>(\d+)</strong> of <strong>(\d+)</strong>")
ROW = re.compile(r'<tr class="rg(?:Row|AltRow)"')
GRID = 'id="ctl00_ContentPlaceholder1_RG_Results_ctl00"'
# what a browser sends for the three boxes left empty (their placeholder text and client state), and for "Permit" in the Permit or Plug list (captured from a real submit, 2026-11-01)
PLACEHOLDER = {"RN_SectionNumber": ("equals", {"enabled": True, "emptyMessage": "equals", "validationText": "", "valueAsString": "", "minValue": -70368744177664, "maxValue": 1000, "lastSetTextBoxValue": "equals"}),
               "txtLot": ("containing", {"enabled": True, "emptyMessage": "containing", "validationText": "", "valueAsString": "", "lastSetTextBoxValue": "containing"}),
               "txtCompanyName": ("containing", {"enabled": True, "emptyMessage": "containing", "validationText": "", "valueAsString": "", "lastSetTextBoxValue": "containing"})}
PERMIT_ONLY = {"enabled": True, "logEntries": [], "selectedIndex": 1, "selectedText": "Permit", "selectedValue": "Permit"}
RANGE = {"minDateStr": "1700-01-01-00-00-00", "maxDateStr": "2099-12-31-00-00-00"}
WANT = ("DT_APP_ISSUED", "APP_TYP", "APP_TYP_Description", "NAME", "CONAME", "PROP_WLTYPE", "APPNO")  # the only columns the reader keeps (the other 63 hold addresses, phones and contacts)
BANDS = C.BANDS  # every band is told

# ------------------------------------------------------------------------------------------------ the bands: one line per application type (APP_TYP) the list has used, 2019 to 2026
# code: (band, the words the grid prints for it). `new` a permit to drill a new well; `inj` a new well for salt-water injection; `redrill` a re-entry, a deepening, or a plug-back to drill a
# new hole from an existing well (the common definition: re-entry, deepening, sidetrack, re-drill); `rework` a plug-back or a conversion of an existing well; `amend` a re-issue of a permit already
# issued (the same well counted again) or a revised location; `other` anything else. The legacy codes ended in July 2021, when the Division's RICS system began (the RIxx codes).
TYPES = {
    "RINW": ("new", "RICS Permit to Drill New Well"),
    "HX": ("new", "Drill New Well, horizontally"),
    "NW": ("new", "Drill New Well"),
    "HX0": ("new", "Drill New Well, horizontally Urban 5000"),
    "UC2": ("new", "Drill New Well Urban 15000"),
    "UX2": ("new", "Drill New Well, Directionally Urban UX2"),
    "NX": ("new", "Drill New Well, directionally"),
    "UC0": ("new", "Drill New Well Urban 5000"),
    "SWIW": ("inj", "Salt Water Injection Well New Well"),
    "RID": ("redrill", "RICS Permit to Deepen"),
    "DDHX": ("redrill", "Deepen to horizontally drill"),
    "DHX0": ("redrill", "Deepen to horizontally drill Urban 5000"),
    "DD": ("redrill", "Drill Deeper"),
    "DD0": ("redrill", "Drill Deeper Urban 5000"),
    "OP": ("redrill", "Reopen"),
    "PBHX": ("redrill", "Plug back to horizontally drill"),
    "PX": ("redrill", "Plug back to directionally drill"),
    "PX2": ("redrill", "Plug back to directionally drill Urban 15000"),
    "PB": ("rework", "Plug Back"),
    "CO": ("rework", "Convert"),
    "CS": ("rework", "Convert SWIW"),
    "RIC": ("rework", "RICS Permit to Convert"),
    "RIPL": ("amend", "RICS Permit to Revise Location"),
    "RIRI": ("amend", "RICS Reissue a Previously Issued Permit"),
    "RHX": ("amend", "Reissue new well, horizontally"),
    "RN": ("amend", "Reissue New Well"),
    "RRHX": ("amend", "Reissue revise location new well, horizontally"),
    "RSWI": ("amend", "Reissue Salt Water Injection Well"),
    "RNU0": ("amend", "Reissue New Well Urban 5000"),
    "RHX0": ("amend", "Reissue new well, horizontally Urban 5000"),
    "RX2": ("amend", "Reissue new well, directionally Urban 15000"),
    "RDHX": ("amend", "Reissue deepen to horizontally drill"),  # the Division's own spelling in the list is "hoizontally"
    "RD": ("amend", "Reissue drill deeper"),
    "RB": ("amend", "Reissue plug back"),
    "SMP": ("other", "Solution Mining Well"),
}
# the well type on a permit (PROP_WLTYPE) decides what a NEW-well permit is: oil and gas stays `new`; gas storage, a test hole, salt water and enhanced recovery are service wells (`inj`, as in the common
# definition: injection, disposal, storage or other service well); solution mining and mineral wells are `other`. A blank type leaves a new-well permit `new` (a few are blank; more than 5% fails the run).
WELL_TYPES = {"OG_R": "new", "GS_R": "inj", "ST_R": "inj", "SW_R": "inj", "SWD": "inj", "ER_R": "inj", "SM_R": "other", "MN_R": "other"}
# the codes of the other list, the one this filter leaves out: seeing one means the filter was not applied (it would count about 800 plug permits a year as permits)
PLUG_TYPES = frozenset({"RIPW", "PA", "PR", "RP", "RA", "OWPA"})


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
        moved, last = 0, ""
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
                    last = "redirected to %s" % re.sub(r"[?#].*", "", e.headers.get("Location", "") or "another page")[:60]
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


def form_fields(html, start, end, button):
    """The fields a browser posts for this page with `start` and `end` typed into the two date boxes, "Permit" chosen and `button` ((name, value)) clicked: every hidden field of the page as it is,
    then the two date pickers (the display text, the ISO stamp and the picker's client state), the three empty boxes with their placeholders, the Permit or Plug list, and the button."""
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
    fields[I + "ddlPermitOrPlug_ClientState"] = json.dumps(PERMIT_ONLY, separators=(",", ":"))
    fields[button[0]] = button[1]
    return fields


def grid_total(html):
    """N, the number of rows the search found, from a results page: the grid's own "Item 1 to 25 of N", or, when there is no pager (25 rows or fewer), the rows themselves.
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


# ------------------------------------------------------------------------------------------------ the export (.xls) -> the seven columns

def read_export(data):
    """Rows (dicts of the WANT columns, as text) of the Excel export, and nothing else. The file is the old binary format with its cells as inline text (LABEL) and numbers (NUMBER); the header is the
    first row that names DT_APP_ISSUED and APP_TYP. Raises ValueError for anything that is not that (a page of HTML, a cut-short file, a layout that changed)."""
    if data[:8] != KY.OLE_MAGIC:
        raise ValueError("the export is not an Excel file (a page of HTML?)")
    try:
        stream = KY.ole_stream(data)
        labels, numbers = {}, {}
        for rid, d in KY.records(stream):
            if rid == 0x0204:  # LABEL: row, column, format, length, then (unless the text is empty) a flag byte and the characters
                r, c, _xf, cch = struct.unpack_from("<HHHH", d, 0)
                wide = bool(cch) and len(d) > 8 and d[8] & 1
                text = "" if not cch else d[9:9 + 2 * cch].decode("utf-16-le", "replace") if wide else d[9:9 + cch].decode("latin-1")
                if len(text) < cch:
                    raise ValueError("a text cell is cut short")
                labels[(r, c)] = text
            elif rid == 0x0203:  # NUMBER
                r, c, _xf, x = struct.unpack_from("<HHHd", d, 0)
                numbers[(r, c)] = KY.num_text(x)
    except (struct.error, IndexError, KeyError, UnicodeError, OverflowError) as e:
        raise ValueError("the export is not a readable .xls workbook (%s)" % type(e).__name__)
    head = next((r for r in sorted({r for r, _c in labels}) if r < 20 and {"DT_APP_ISSUED", "APP_TYP"} <= {v.strip() for (rr, _c), v in labels.items() if rr == r}), None)
    if head is None:
        raise ValueError("the export has no header row with DT_APP_ISSUED and APP_TYP")
    cols = {}
    for (r, c), v in sorted(labels.items()):
        if r == head and v.strip() in WANT and v.strip() not in cols:
            cols[v.strip()] = c
    if set(WANT) - set(cols):
        raise ValueError("columns not in the export: %s" % ", ".join(sorted(set(WANT) - set(cols))))
    keep = {c: h for h, c in cols.items()}
    rows = {}
    for cells in (labels, numbers):
        for (r, c), v in cells.items():
            if r > head and c in keep:
                rows.setdefault(r, {})[keep[c]] = v.strip()
    labels = numbers = None  # the addresses and phone numbers the file also held are dropped here
    return [{h: rows[r].get(h, "") for h in WANT} for r in sorted(rows)]


# ------------------------------------------------------------------------------------------------ one window of issue dates

class Overfull(RuntimeError):
    """The search reports as many rows as the server's cap: the window is not complete and must be split."""


def read_window(client, form, start, end):
    """The rows (dicts of the WANT columns, repeats included) of every application issued from `start` to `end` inclusive. Two requests: the search (whose total and page are checked) and the export,
    whose rows must be exactly the total. Raises Overfull when the total reaches the cap."""
    page = client.fetch(PAGE, form_fields(form, start, end, SEARCH_BUTTON)).decode("utf-8", "replace")
    n = grid_total(page)
    if n >= CAP:
        raise Overfull("%d rows from %s to %s: the search is capped at %d rows" % (n, start, end, CAP))
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
        raise RuntimeError("the export from %s to %s holds %d rows but the grid counted %d" % (start, end, len(rows), n))
    return rows


def read_range(client, form, start, end, out, today, depth=0):
    """Reads [start, end] into `out` as (day, row): one window, or, when the search is capped, its two halves (down to a single week: a week that is still capped is an error)."""
    try:
        rows = read_window(client, form, start, end)
    except Overfull as e:
        if (end - start).days < 7 or depth > 8:
            raise RuntimeError("a window of %d days is still capped (%s)" % ((end - start).days + 1, e))
        mid = start + timedelta(days=(end - start).days // 2)
        read_range(client, form, start, mid, out, today, depth + 1)
        read_range(client, form, mid + timedelta(days=1), end, out, today, depth + 1)
        return
    for row in rows:
        day = C.parse_day(row["DT_APP_ISSUED"], today + timedelta(days=1))
        if day is None or not start <= day <= end:
            raise RuntimeError("an issue date (%r) is unreadable or outside the window %s to %s" % (row["DT_APP_ISSUED"][:12], start, end))
        out.append((day, row))


def plan(first, last):
    """The windows to read: one for a span of 15 months or less (the weekly run), else a calendar year each."""
    if (last - first).days <= ONE_WINDOW_DAYS:
        return [(first, last)]
    return [(max(first, date(y, 1, 1)), min(last, date(y, 12, 31))) for y in range(first.year, last.year + 1)]


# ------------------------------------------------------------------------------------------------ the committed file, the bands, the build

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
    """The band of one permit row. Raises RuntimeError for an application type or (on a new-well permit) a well type this table does not know, and for a plug permit."""
    code = row["APP_TYP"]
    if code in PLUG_TYPES:
        raise RuntimeError("the Permit list returned a plug permit (%s): the Permit or Plug filter was not applied" % code)
    if code not in TYPES:
        raise RuntimeError("an application type this producer does not know: %r (%s): add it to TYPES" % (code, row["APP_TYP_Description"][:50]))
    band = TYPES[code][0]
    if band == "new" and row["PROP_WLTYPE"]:
        if row["PROP_WLTYPE"] not in WELL_TYPES:
            raise RuntimeError("a well type this producer does not know: %r: add it to WELL_TYPES" % row["PROP_WLTYPE"][:20])
        band = WELL_TYPES[row["PROP_WLTYPE"]]
    return band


def build(client=None, old=None, today=None):
    today = today or date.today()
    client = client or Client()
    old = previous() if old is None else old
    cut_month = C.add_months(C.month_of(today), -REREAD)
    carry = bool(old) and all(ym in old[b] for b in BANDS for ym in C.month_list(C.FIRST_MONTH, C.add_months(cut_month, -1)))  # the committed file has every month from 2019-01 to the one before the window
    first = date(int(cut_month[:4]), int(cut_month[5:]), 1) if carry else FIRST
    form = client.fetch(PAGE).decode("utf-8", "replace")
    if "Permit and Plug List" not in form or GRID in form:
        raise RuntimeError("the page is not the Permit and Plug List search form (the server may have sent its home page)")
    form_fields(form, first, today, SEARCH_BUTTON)  # fails here, before any search, if the form has changed
    got = []
    for a, b in plan(first, today):
        read_range(client, form, a, b, got, today)
    seen, permits = set(), []
    for day, row in got:
        if not row["APPNO"]:
            raise RuntimeError("a row has no application number: the column may have changed")
        key = (row["APPNO"], day, row["APP_TYP"], row["NAME"], row["CONAME"], row["PROP_WLTYPE"])
        if key not in seen:  # the export lists some applications twice
            seen.add(key)
            permits.append((day, row))
    repeats = len(got) - len(permits)
    if len(permits) < (MIN_WINDOW if carry else MIN_ALL):
        raise RuntimeError("only %d permits were read (expected %d or more): the list may have changed" % (len(permits), MIN_WINDOW if carry else MIN_ALL))
    newest = max(d for d, _r in permits)
    if (today - newest).days > STALE_DAYS:
        raise RuntimeError("the newest permit was issued on %s: the list may have stopped being updated" % newest.isoformat())
    t = C.Tally(STATE, bands=BANDS, fluid=False)
    if carry:  # months before the window: the committed counts, at mid-month
        for b in BANDS:
            for ym, n in old[b].items():
                if ym < cut_month and n:
                    t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    no_county = no_type = new_wells = 0
    for day, row in sorted(permits, key=lambda x: (x[0], x[1]["APPNO"])):
        band = classify(row)
        no_county += not row["NAME"]
        if TYPES[row["APP_TYP"]][0] == "new":
            new_wells += 1
            no_type += not row["PROP_WLTYPE"]
        t.add(day, band, county=row["NAME"] or None, operator=row["CONAME"] or None)
    if no_county > max(5, len(permits) // 10):
        raise RuntimeError("%d of %d permits have no county: a column may have been renamed" % (no_county, len(permits)))
    if no_type > max(5, new_wells // 20):
        raise RuntimeError("%d of %d new-well permits have no well type: a column may have been renamed" % (no_type, new_wells))
    note = ("Permits issued, by the day each was issued, from the Division's Permit and Plug List (Oil & Gas Well Database), the Permit list, which leaves out permits to plug a well. "
            "A permit to drill a new well (horizontal or vertical) is a new well, unless its well type is gas storage, a test hole, salt water or solution mining; permits to deepen a well, to reopen one and to plug back "
            "and drill again are re-entries; plain plug-backs and conversions are reworks; a re-issued permit, a revised location and a revised unit are amendments (the same well counted again). "
            "The Division's own count of permits to drill includes the deepenings and re-issues, so it is higher than the new wells here. "
            "The list does not say whether a well is oil or gas (its well type is oil and gas for nearly every well), so the fluid split is not available. "
            "The export lists some applications twice; each is counted once. A month is shown once a permit has been issued after it.")
    return t.document(agency="Ohio Department of Natural Resources, Division of Oil and Gas Resources Management", source_name="Permit and Plug List (Oil & Gas Well Database, Excel export of the Permit list)", source_url=PAGE,
                      basis="issue date (the day the permit was issued)", cadence="live database, current to the day each permit is issued (read weekly here)", measure="permits", asof=newest, note=note)


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
