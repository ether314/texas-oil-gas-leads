#!/usr/bin/env python3
"""D11: Wyoming's drilling permits (the Oil and Gas Conservation Commission's APDs), for the National report of the Oil tracker.

The Commission (WOGCC) has a "Download Approved" page under its Permits to Drill menu (https://pipeline.wyo.gov/DumpApds.cfm): a form that takes a range of dates and a kind of
well and answers with one row per APPROVED permit, as an HTML table that Excel opens (a file named APD<from>_<to>.xls). The form's own address takes the same fields in a plain
request, so one GET per calendar year reads the series (8 requests, 5 seconds apart). Per row this reads the day it was approved (`Approved`, yyyymmdd), the well class, the county and the company,
and nothing else but the API number (only to drop a row the export repeats). Wyoming's page says that scraping the site is not allowed and that its Down Load pages are the sanctioned route: this is one polite run a week
of that route.

What is counted: APDs approved, by the day of approval (`measure="permits"`, 2019 to the newest complete month).
  new      an approved permit for an oil or gas well (class O, G or both)
  inj      an approved permit for an injection or disposal well, or a monitor well (a service well)
  other    a test hole (stratigraphic or core test) or a class this producer does not know (the run fails if they are more than a few)
The file has NO work-type column, so a re-entry, a deepening or a renewal of an earlier permit cannot be told from a new well: they are inside `new`, and the unit says "APDs approved"
(as the BLM's line does). Redrills, reworks and amendments are therefore published as not available (null), never zero. The Commission's own page "Count of APDs Approved by County,
2010 forward" (rcountyapprvdcount.cfm: oil and gas classes only, to 2025) gives 1,198, 472, 537, 706, 612, 502 and 582 for 2019 to 2025; the new wells here are 1,197, 472, 537,
703, 609, 496 and 583 (within six a year: the export's class is the well's current one).

What the figures are NOT: the class and the company are the permit's CURRENT values (a permit transferred to a new operator shows the new one), and whether a renewed or revised permit
keeps its first approval date is not documented (in the export of 2026-11-01, 39 of 2,782 permits with a spud date were spudded before their approval date: the date is rarely rewritten).
Dates and counts are as of the export, which the Commission refreshes daily.

Privacy: only a county name, a corporate company name and a class code reach the tally. The export also holds well names, lease names, API numbers and coordinates: none of them
is kept (the API number lives in memory only, for the repeated-row check). The reply is untrusted data: parsed as text, never run; each reply is capped in size. Requests identify no person.

  python3 -I site/pipeline/d11_nat_wy.py [--check]
"""
import collections
import os
import re
import sys
import time
from datetime import date
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "WY"
PAGE = "https://pipeline.wyo.gov/DumpApds.cfm"
EXPORT = "https://pipeline.wyo.gov/DumpByApdA.cfm"
PAUSE = 5.0
MAX_BYTES = 40_000_000  # a year is about 600 to 1,500 rows of 3.6 KB (2 to 5 MB)
TIMEOUT = 120
NEEDED = ("Api_Number", "Company", "Approved", "County", "Well_Class")
MIN_ROWS_A_YEAR = 150  # the published counts for 2019 to 2025 are 472 at the least
MIN_ROWS = 2500
MAX_AGE_DAYS = 45
BANDS = ("new", "inj", "other")

# the Commission's class codes (it publishes no dictionary: the codes were read from the export and from its county count page, which uses O and G)
CLASS_WORDS = {"O": "oil well", "G": "gas well", "OG": "oil and gas well", "GO": "oil and gas well", "CB": "coal bed methane gas well", "CBM": "coal bed methane gas well",
               "I": "injection well", "IW": "injection well", "D": "disposal well", "DW": "disposal well", "SWD": "disposal well", "M": "monitor well", "MW": "monitor well",
               "GS": "gas storage service well", "WS": "water source service well"}
TEST_CLASSES = frozenset({"ST", "S", "CT", "T"})  # stratigraphic or core test holes


# ------------------------------------------------------------------------------------------------ reading the export

class TableParser(HTMLParser):
    """The cells of every row of the HTML table, as text. The header's cells come before the first <tr> in the real reply, so rows are split at <tr> and the header is found by its names."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = [[]]
        self.cell = None

    def _close(self):
        if self.cell is not None:
            self.rows[-1].append(" ".join("".join(self.cell).replace("\xa0", " ").split()))
            self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._close()
            self.rows.append([])
        elif tag == "td" or tag == "th":
            self._close()
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th", "tr"):
            self._close()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def parse_export(body, name="the export"):
    """The rows of one export reply as dicts holding only NEEDED. Raises when the reply is not the table (no header with the needed names: the page or its columns changed), is cut off
    (no closing </table>) or has rows of another width. A reply that is the table with no rows returns []."""
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body
    if "</table>" not in text[-400:].lower():
        raise ValueError("%s: the reply does not end with its table (cut off, or an error page)" % name)
    p = TableParser()
    p.feed(text)
    p.close()
    header = next((r for r in p.rows if all(c in r for c in NEEDED)), None)
    if header is None:
        raise ValueError("%s: no table with the columns %s: the page's layout changed" % (name, ", ".join(NEEDED)))
    at = p.rows.index(header)
    idx = [(c, header.index(c)) for c in NEEDED]
    out, ragged = [], 0
    for r in p.rows[at + 1:]:
        if not r:
            continue
        if len(r) != len(header):
            ragged += 1
            continue
        out.append({c: r[i] for c, i in idx})
    if ragged > max(2, len(out) // 100):
        raise ValueError("%s: %d rows do not have the header's %d cells" % (name, ragged, len(header)))
    return out


def export_url(first, last):
    """The address that asks for every permit approved from `first` to `last` (dates), of every well class (cType=1)."""
    return "%s?bmon=%02d&bday=%02d&byear=%d&emon=%02d&eday=%02d&eyear=%d&cType=1" % (EXPORT, first.month, first.day, first.year, last.month, last.day, last.year)


def classify(code):
    """(band, fluid, known) of one approval from the Commission's well class."""
    c = (code or "").strip().upper()
    if c in TEST_CLASSES:
        return "other", None, True
    if re.fullmatch(r"\d{1,2}", c):
        c = "CB"  # the old numeric classes of coal bed wells
    words = CLASS_WORDS.get(c)
    if words is None:
        return "other", None, False
    return C.band_of("", words), C.fluid_of(words), True


def build(get=C.polite_get, pause=PAUSE, today=None):
    today = today or date.today()
    first_year = int(C.FIRST_MONTH[:4])
    seen, unknown, strays = set(), collections.Counter(), 0
    t = C.Tally(STATE, bands=BANDS, fluid=True)
    per_year = collections.Counter()
    for year in range(first_year, today.year + 1):
        if year > first_year:
            time.sleep(pause)
        last = today if year == today.year else date(year, 12, 31)
        body = get(export_url(date(year, 1, 1), last), max_bytes=MAX_BYTES, timeout=TIMEOUT)
        try:
            rows = parse_export(body, "the %d export" % year)
        except ValueError:
            if year == today.year and today.month == 1 and today.day <= 20 and b"Approved" not in body:
                rows = []  # the first days of a year may hold no approval: nothing to read yet
            else:
                raise
        for r in rows:
            day = C.parse_day(r["Approved"], today)
            if day is None or day.year != year:
                strays += 1
                continue
            api = re.sub(r"\D", "", r["Api_Number"])
            key = (api, day) if api else None
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            band, fluid, known = classify(r["Well_Class"])
            if not known:
                unknown[r["Well_Class"].strip().upper()[:6] or "(blank)"] += 1
            per_year[year] += 1
            t.add(day, band, county=r["County"], operator=r["Company"], fluid=fluid)
    total = sum(per_year.values())
    if total < MIN_ROWS:
        raise ValueError("only %d approvals were read since %d (expected 5,000 or more)" % (total, first_year))
    short = [y for y in range(first_year, today.year) if per_year[y] < MIN_ROWS_A_YEAR]
    if short:
        raise ValueError("the export gave fewer than %d approvals for %s: a reply was short" % (MIN_ROWS_A_YEAR, ", ".join(map(str, short))))
    if strays > max(10, total // 100):
        raise ValueError("%d rows have an approval date outside the year asked: the export or its date format changed" % strays)
    if sum(unknown.values()) > max(10, total // 50):
        raise ValueError("well classes this producer does not know: %s" % ", ".join("%s (%d)" % kv for kv in unknown.most_common(5)))
    if (today - t.newest).days > MAX_AGE_DAYS:
        raise ValueError("the newest approval is from %s: the Commission's export has stopped being refreshed" % t.newest)
    if unknown:
        C.log("WY: %d approvals of classes not known (counted as other): %s" % (sum(unknown.values()), ", ".join("%s (%d)" % kv for kv in unknown.most_common(5))))
    return t.document(
        agency="Wyoming Oil and Gas Conservation Commission", source_name="Permits to Drill, Download Approved (one export a year)", source_url=PAGE, basis="approval date (APD approved)",
        cadence="daily", measure="permits", unit="APDs approved",
        note="Applications for Permit to Drill approved by the Commission, by approval date: oil and gas wells, injection, disposal and monitor wells, and a few test holes. The file has no work type, "
             "so a re-entry, deepening or renewal is counted inside new wells; recompletions and amendments are not available. Well class and company are the permit's current values.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
