#!/usr/bin/env python3
"""D11: South Dakota's well permits (Department of Agriculture and Natural Resources, Minerals, Mining and Superfund Program: Oil and Gas), for the National report of the Oil tracker.

Read: the program's monthly export, https://sddenr.net/pubs/og/SDOILexport.zip (about 18 MB), and in it only Wells.xlsx (about 0.6 MB, one row per well ever permitted in the state, 2,137 when
written). The rest of the zip (the production sheet is 14 MB) is never opened. Five columns are read: Date Permit Issued, Permitted Well Type, County, Operator and Export Date. NOTES_D11.md has the research.

What a count is, and is not:
  - one count is a well that received a permit to drill, on the day the permit was issued (`measure` permits, `basis` issue date). The file has one permit date per well; a re-entry or an extension
    adds no row, so the kinds `redrill`, `rework` and `amend` are not told (null). "Permitted Well Type" tells a new injection well (`inj`) from an oil, gas or exploratory one (`new`), and the fluid;
  - South Dakota is nearly dormant: 24 permits since 2019 (4, 0, 4, 11, 4 and 1 in 2019 to 2024), the newest issued July 16, 2024, and no well has been spudded since October 2024. The program's own
    "permits issued" tables on its permit page give the same yearly counts (4, 4, 11, 4, 1). The series therefore runs to the month before the file's export date and the months after July 2024
    are REAL zeros, which is why the document says `zeroOk` (the library refuses a file with no new permit in 24 months otherwise). That claim stands on three guards: the export date must be fresh
    (a file the program stopped refreshing fails the run), the file must still hold the state's whole history (a shrunken or damaged file fails), and the years since 2019 must still be found;
  - the file is replaced whole each month, so earlier months can be revised.

The operator is the file's name for it, named only if it is a corporation, LLC or partnership (the shared rule: the older rows are full of individuals' names, which never leave this file). No API
number, well name, permit number, location, coordinate or link is read.

  python3 -I site/pipeline/d11_nat_sd.py [--check]
"""
import io
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import ok_xlsx  # noqa: E402  (the repo's own standard-library .xlsx reader)

STATE = "SD"
ZIP_URL = "https://sddenr.net/pubs/og/SDOILexport.zip"
PAGE = "https://danr.sd.gov/Environment/MineralsMining/OilGas/OilGasForms.aspx"
MEMBER = "wells.xlsx"  # the one member read, matched by its name in any case
WANT = ("Date Permit Issued", "Permitted Well Type", "County", "Operator", "Export Date")
MAX_ZIP = 40 * 1024 * 1024  # 18 MB when written
MAX_MEMBER = 25 * 1024 * 1024  # 0.6 MB when written
MIN_ROWS = 1500  # 2,137 wells when written, and the file only grows
MIN_DATED = 1500  # 2,065 with a permit date
MIN_SINCE_2019 = 10  # 24 when written
MAX_STALE_DAYS = 150  # the export is monthly; one older than this has stopped being refreshed
MAX_BAD = 0.02  # most dated cells that may fail to read as a date
FIRST_SERIAL = 18264  # Excel's day number for 1950-01-01: earlier numbers are the file's placeholders and its oldest permits


def serial_day(value, today):
    """(day, state) for a permit-date cell: the day from an Excel day number (or from text such as 7/16/2024), and the state 'ok', 'blank', 'old' (before 1950: a placeholder or a very old
    permit, ignored without complaint) or 'bad' (text that is not a date, a number out of range, a day after today)."""
    text = (value or "").strip() if isinstance(value, str) else value
    if text in (None, ""):
        return None, "blank"
    try:
        f = float(text)
    except (TypeError, ValueError):
        d = C.parse_day(text, today)
        if d:
            return d, "ok"
        year = re.search(r"\b(\d{4})\b", str(text))
        return (None, "old") if year and int(year.group(1)) < 1950 else (None, "bad")
    if f < FIRST_SERIAL:
        return None, "old"
    if f > 80000:
        return None, "bad"
    d = date(1899, 12, 30) + timedelta(days=int(f))
    return (d, "ok") if d <= today else (None, "bad")


def read_wells(zip_bytes):
    """The rows of Wells.xlsx (dicts of the five columns) out of the export's zip bytes. Only that member is opened, and only if its declared size is sane; a damaged zip or workbook, a
    missing member or a renamed column raises RuntimeError."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            found = [i for i in z.infolist() if not i.is_dir() and i.filename.rsplit("/", 1)[-1].lower() == MEMBER]
            if len(found) != 1:
                raise RuntimeError("the export holds %d files named Wells.xlsx (expected 1): its layout changed" % len(found))
            if found[0].file_size > MAX_MEMBER:
                raise RuntimeError("Wells.xlsx is %d bytes, more than the %d allowed" % (found[0].file_size, MAX_MEMBER))
            data = z.read(found[0])
        return list(ok_xlsx.rows(io.BytesIO(data), want=WANT))
    except (zipfile.BadZipFile, KeyError, IndexError, ValueError, ET.ParseError) as e:
        raise RuntimeError("the export or its Wells.xlsx could not be read (%s)" % str(e)[:100])


def build(get=C.polite_get, today=None):
    today = today or date.today()
    rows = read_wells(get(ZIP_URL, max_bytes=MAX_ZIP, timeout=180))
    if len(rows) < MIN_ROWS:
        raise RuntimeError("Wells.xlsx has %d wells (expected %d or more): the file is cut short or changed" % (len(rows), MIN_ROWS))
    exports = [serial_day(r["Export Date"], today) for r in rows]
    export = max((d for d, s in exports if d), default=None)
    if export is None or (today - export).days > MAX_STALE_DAYS:
        raise RuntimeError("the export is dated %s: the program has stopped refreshing it" % (export.isoformat() if export else "nowhere"))
    t = C.Tally(STATE, bands=("new", "inj"), fluid=True)
    dated = since = bad = 0
    for r in rows:
        day, state = serial_day(r["Date Permit Issued"], today)
        if state == "bad":
            bad += 1
        if day is None:
            dated += state == "old"
            continue
        dated += 1
        if day.year < 2019:
            continue
        since += 1
        kind = r["Permitted Well Type"] or ""
        county = r["County"] or None
        t.add(day, C.band_of("", kind), county=county, operator=r["Operator"] if isinstance(r["Operator"], str) else None, fluid=C.fluid_of(kind))
    if dated < MIN_DATED:
        raise RuntimeError("only %d wells have a readable permit date (expected %d or more): the date column changed" % (dated, MIN_DATED))
    if bad > MAX_BAD * dated:
        raise RuntimeError("%d permit dates could not be read as dates: the date column changed" % bad)
    if since < MIN_SINCE_2019:
        raise RuntimeError("only %d permits since 2019 were found (expected %d or more)" % (since, MIN_SINCE_2019))
    newest = t.newest
    doc = t.document(
        agency="South Dakota Department of Agriculture and Natural Resources, Oil and Gas Program",
        source_name="Oil and gas wells export (Wells.xlsx in SDOILexport.zip, monthly)", source_url=ZIP_URL, basis="issue date (the day the permit to drill was issued)",
        cadence="monthly", measure="permits", asof=export,
        note="Wells that received a permit to drill, by the day it was issued. Re-entries, reworks and extensions add no row (not available); the file is replaced whole each month, so earlier months can be revised.")
    if C.month_of(newest) < doc["through"][:7]:
        doc["note"] = ("South Dakota has issued very few permits: the newest in the program's export of %s is dated %s, so every month since is a real zero, not a gap. " % (export.isoformat(), newest.isoformat())) + doc["note"]
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # the guards above are why a quiet two years may be published (see the module's docstring)
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
