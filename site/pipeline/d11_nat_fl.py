#!/usr/bin/env python3
"""D11: Florida's oil and gas permits (Department of Environmental Protection, Oil and Gas Program), for the National report of the Oil tracker.

The Department publishes one workbook, "Oil and Gas Permit Database" (OG_WELLS_WEBSITE_<n>.xlsx, 0.7 MB), updated "quarterly or as needed": its WELLS tab has a row per permit since 1945 with the
county, the operator of record and an ISSUE_DATE, which the workbook's own legend defines as the "date of final agency action drilling permit (date final authority signed the permit)". This reads the
workbook (the address is taken from the Department's page each run, because the file's name carries a version number) and writes nat/FL.json: permits counted by that issue date. What it can and cannot tell:

  - `new`: a permit number that is a plain number (1374) or one marked horizontal (1347H, 1340HL);
  - `amend`: a number with a letter after it (553A, 904B, 1335D), which the legend says marks "subsequent permit modifications" (a modification is its own permit, with its own issue date);
  - no other band: Form 3 has no well type and no work type, so an injection or disposal permit cannot be told from the permit (the status column says what a well later became, which is not what
    was approved) and the fluid is not recorded either;
  - a permit with no ISSUE_DATE (pending, denied, withdrawn, never issued) is not a permit that was issued and is not counted;
  - Florida issues almost no permits: the newest ISSUE_DATE in the workbook is March 4, 2020, and the Department's list since then holds only a pending and a denied application. The months after the
    newest permit are zeros as the Department records it, up to the day the workbook was last saved (its own metadata, September 8, 2026 when this was written), which is the file's `asOf`.
    That is why the file says `zeroOk`: the validator otherwise refuses a state with no new permit in 24 months.

An operator is named only if it is a corporation, LLC or partnership. No permit number, API number, well name or comment leaves this file (the Tally keeps counts). The workbook is untrusted data: it is
only read (sizes checked first, never run). A page without the workbook's link, a file that is not a workbook or lacks the WELLS tab or a column, too few rows, dates that do not read, or a file
saved before its own newest permit fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_fl.py [--check]
"""
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import ok_xlsx  # noqa: E402  (the repository's standard-library reader for .xlsx)

STATE = "FL"
PAGE = "https://floridadep.gov/water/oil-gas/documents/oil-and-gas-permit-database"
HOST = "https://floridadep.gov"
LINK = re.compile(r'href="((?:https://floridadep\.gov)?/sites/default/files/OG_WELLS[^"]*\.xlsx)"', re.I)
SHEET = "WELLS"
WANT = ("PERMITNO", "COUNTY", "COMPANY", "ISSUE_DATE")  # nothing else is read: no API number, well name, location or comment
PAUSE = 2.0
MAX_BOOK = 15 * 1024 * 1024  # the workbook is 0.7 MB
MAX_MEMBER = 40 * 1024 * 1024  # uncompressed, per part of the workbook (the WELLS sheet is 3.4 MB)
MAX_TOTAL = 120 * 1024 * 1024
MIN_ROWS = 1000  # the WELLS tab holds about 1,480 rows, about 1,430 of them with an issue date
MIN_SINCE_2019 = 10  # the workbook lists 19 permits issued in 2019 alone
NUMBER = re.compile(r"^\s*(\d{1,5})\s*([A-Za-z]{0,3})\s*$")
MODIFIED = re.compile(r"<dcterms:modified[^>]*>\s*(\d{4}-\d\d-\d\d)", re.I)


def workbook_link(html):
    """The absolute address of the permit database workbook on the Department's page, None when the page does not link one."""
    m = LINK.search(html)
    if not m:
        return None
    h = m.group(1)
    return h if h.startswith("http") else HOST + h


def band_of(permitno):
    """'new' for a plain permit number or one marked horizontal (H, HL), 'amend' for a number with a modification letter (A, B, AH); None when the text is not a permit number."""
    m = NUMBER.match(str(permitno or ""))
    if not m:
        return None
    letters = m.group(2).upper()
    for mark in ("HL", "H"):  # a horizontal well's marker is not a modification
        if letters.endswith(mark):
            letters = letters[: -len(mark)]
            break
    return "amend" if letters else "new"


def serial_day(value, today=None):
    """A date from an Excel serial number (how the workbook stores ISSUE_DATE) or from text such as 4/1/2020; None for blank, junk, or a day after today."""
    today = today or date.today()
    try:
        f = float(value)
    except (TypeError, ValueError):
        return C.parse_day(value, today)
    if not 1 <= f < 100000:
        return None
    d = (datetime(1899, 12, 30) + timedelta(days=f)).date()
    return d if d <= today else None


def long_day(d):
    """September 8, 2026 (strftime's day without a leading zero is not portable)."""
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def read_book(data):
    """(rows, saved) from the workbook bytes: the WELLS tab's wanted columns as dicts, and the day the workbook was last saved (its own metadata). The file is written to a new temporary folder,
    its parts' sizes are checked before anything is unpacked, and it is only ever read."""
    with tempfile.TemporaryDirectory(prefix="fl-") as tmp:
        path = os.path.join(tmp, "book.xlsx")
        with open(path, "wb") as f:
            f.write(data)
        with zipfile.ZipFile(path) as z:
            sizes = {i.filename: i.file_size for i in z.infolist()}
            if sum(sizes.values()) > MAX_TOTAL or any(s > MAX_MEMBER for s in sizes.values()):
                raise RuntimeError("the workbook unpacks to more than expected")
            if "xl/workbook.xml" not in sizes:
                raise RuntimeError("the file is not a workbook")
            names = re.findall(r'<sheet\b[^>]*?\bname="([^"]*)"', z.read("xl/workbook.xml").decode("utf-8", "replace"))
            core = z.read("docProps/core.xml").decode("utf-8", "replace") if "docProps/core.xml" in sizes else ""
        if SHEET not in names:
            raise RuntimeError("the workbook has no %s tab (tabs: %s)" % (SHEET, ", ".join(n[:30] for n in names[:8])))
        m = MODIFIED.search(core)
        saved = C.parse_day(m.group(1)) if m else None
        return list(ok_xlsx.rows(path, want=WANT, sheet=names.index(SHEET))), saved


def parse(rows, today=None):
    """Issued permits as dicts {day, band, county, operator}, oldest first. A row with no permit number or no ISSUE_DATE is not an issued permit and is left out; a number or a date that cannot be read
    fails the run when more than 2% of the dated rows have one."""
    today = today or date.today()
    out, dated, bad = [], 0, 0
    for r in rows:
        if not (r.get("PERMITNO") or "").strip() or not (r.get("ISSUE_DATE") or "").strip():
            continue
        dated += 1
        day, band = serial_day(r["ISSUE_DATE"], today), band_of(r["PERMITNO"])
        if day is None or band is None:
            bad += 1
            continue
        out.append({"day": day, "band": band, "county": r.get("COUNTY"), "operator": (r.get("COMPANY") or "").strip()})
    if bad > 0.02 * max(1, dated):
        raise RuntimeError("%d of %d permits have an issue date or a permit number that cannot be read" % (bad, dated))
    out.sort(key=lambda p: p["day"])
    return out, dated


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    link = workbook_link(get(PAGE, max_bytes=3_000_000).decode("utf-8", "replace"))
    if not link:
        raise RuntimeError("the Department's page no longer links the permit database workbook: its layout may have changed")
    time.sleep(pause)
    rows, saved = read_book(get(link, max_bytes=MAX_BOOK))
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the WELLS tab gave %d rows (expected about 1,480)" % len(rows))
    permits, dated = parse(rows, today)
    if dated < MIN_ROWS:
        raise RuntimeError("only %d rows have an issue date (expected about 1,430)" % dated)
    recent = [p for p in permits if p["day"] >= date(2019, 1, 1)]
    if len(recent) < MIN_SINCE_2019:
        raise RuntimeError("only %d permits issued since 2019 (the workbook lists about 19 for 2019 alone): the file is cut short" % len(recent))
    newest = max(p["day"] for p in permits)
    if saved is None or saved < newest or saved > today or saved < today - timedelta(days=800):
        raise RuntimeError("the workbook says it was saved on %s, which cannot be right (its newest permit is %s)" % (saved, newest))
    t = C.Tally(STATE, bands=("new", "amend"), fluid=False)
    for p in recent:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"])
    doc = t.document(agency="Florida Department of Environmental Protection, Oil and Gas Program", source_name="Oil and Gas Permit Database (workbook, WELLS tab, issue date)", source_url=PAGE,
                     basis="issue date (the day the final permit was signed)", cadence="quarterly or as needed (the Department's words)", measure="permits", asof=saved,
                     note="Permits counted by the date the Department signed them, from its own database, last saved %s. Florida issues very few: the newest permit in the database was signed %s, "
                          "and months after it are zeros as the Department records them (applications still pending or denied carry no issue date and are not counted). A permit number with a letter "
                          "(553A) is a modification of an earlier permit and counts as an amendment; the permit form records no well type, so injection and disposal permits cannot be told apart." % (long_day(saved), long_day(newest)))
    if not any(doc["bands"]["new"][-24:]):
        doc["zeroOk"] = True  # a state with no new permit in two years is a finding here, not a failed read: the checks above are what prove the file was read
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
