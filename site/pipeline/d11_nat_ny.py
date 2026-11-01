#!/usr/bin/env python3
"""D11: New York's oil, gas and other regulated wells (NYSDEC, Division of Mineral Resources), for the National report of the Oil tracker.

The DEC publishes one free file, `wellDOS.zip` (3 MB; `wellspublic.csv`, about 47,000 rows and 55 columns, rewritten every weekday night), one row per well bore, 1953 to today. It carries the
day each permit was ISSUED (`Permit_Issued`), so the counts are permits by issue date. This reads that one file and writes nat/NY.json. What the file does and does not say:

  - the type on the application (`Original_well_type`: oil or gas development, extension or wildcat, brine, storage, monitoring, geothermal, stratigraphic...) tells new wells (`new`, with their
    fluid) from injection, storage, brine and other service wells (`inj`) from the rest (`other`); where the application's type was not listed (an old record's "NL"), the well's current type is
    used when it names one;
  - there is NO work-type column and a row is a well bore: a permit to deepen, plug back or convert an existing well is not a row of its own, so reworks and amendments are published as
    not available (null), never as zero. A row whose sidetrack code is not zero is a sidetrack bore, a permit of its own, and is counted as `redrill` ("re-entries and sidetracks": only sidetracks
    can be told, a re-entry or a deepening cannot); a row with a further completion code is not a new well either and falls under `other`;
  - stratigraphic test wells, a type nobody lists, and types the file adds later also fall under `other`;
  - a permit later expired, transferred or voided is still a permit issued, so it is counted; a well held confidential (its current type is redacted, its application type is not) is counted too;
  - New York is small (tens of permits a year), so a month is noisy; the file is rewritten nightly, so a past month can move by a permit.

The file's own freshness (the newest `Dt_Mod`, the day a record was last updated) is the `asOf` day, because a quiet month of permits is not a stale file; a file whose newest update is
over 60 days old, or whose newest permit is over 500 days old, is refused. Operators come from `Company_name` and are published only if the shared naming rule says they are a corporation, LLC or
partnership; the well's name (often a landowner's), its API number and its location are never read. The zip is untrusted data: one member is read in memory, size-checked, never extracted or run.

  python3 -I site/pipeline/d11_nat_ny.py [--check]
"""
import csv
import io
import os
import sys
import zipfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "NY"
URL = "https://www.dec.ny.gov/fs/data/wellDOS.zip"  # answers 301 to extapps.dec.ny.gov; urllib follows it
MEMBER = "wellspublic.csv"
MAX_ZIP = 40 * 1024 * 1024  # the real zip is 3 MB
MAX_CSV = 200 * 1024 * 1024  # the real file is 30 MB
# what the real file holds (2026-10-31: 47,486 rows, 18,327 with an issue date, 653 issued since 2019): a file far below is not this file
MIN_ROWS, MIN_DATED, MIN_SERIES = 30000, 15000, 400
MAX_BAD_SHARE = 0.01  # of the issue dates, those that are not a date
MAX_UNKNOWN_SHARE = 0.10  # of the permits in the series, those whose type code this file does not know
MAX_FILE_AGE, MAX_PERMIT_AGE = 60, 500  # days
NEEDED = ("Permit_Issued", "Original_well_type", "Well_Type", "SideTrck", "Completion", "Company_name", "County", "Dt_Mod")

# the DEC's own well type codes (OilandGasMetadata.html, "Well Type Codes"); the words are classified by the shared band_of and fluid_of
WORDS = {"OD": "Oil Development", "OE": "Oil Extension", "OW": "Oil Wildcat", "GD": "Gas Development", "GE": "Gas Extension", "GW": "Gas Wildcat",
         "DH": "Dry Hole", "DW": "Dry Wildcat", "BR": "Brine", "DS": "Disposal", "IW": "Enhanced Oil Recovery - Injection", "IG": "Gas Injection",
         "ST": "Storage", "LP": "Liquefied Petroleum Gas Storage", "MB": "Monitoring Brine", "MM": "Monitoring Miscellaneous", "MS": "Monitoring Storage",
         "TH": "Geothermal", "SG": "Stratigraphic"}
UNLISTED = ("", "NL", "UN", "CONFIDENTIAL")  # no type recorded (or redacted): not an unknown code


def to_int(text):
    try:
        return int(str(text).strip() or 0)
    except ValueError:
        return 0


def type_code(orig, cur):
    """The code of the permit's type: the one on the application, else the well's current one when that names a type; '' when neither does."""
    for c in (orig, cur):
        c = (c or "").strip().upper()
        if c not in UNLISTED:
            return c
    return ""


def classify(orig, cur, side="0", comp="0"):
    """(band, fluid, known) of one permit row. `known` is False for a type code this file's dictionary does not have (counted, under `other`, and watched)."""
    code = type_code(orig, cur)
    if to_int(side) > 0:
        return "redrill", None, True  # a sidetrack of an existing hole, filed as its own well bore (the dictionary: "2-digit sidetrack code")
    if to_int(comp) > 0:
        return "other", None, True  # a further completion of an existing hole: not a new well, and whether it is a rework is not told
    if not code:
        return "other", None, True
    word = WORDS.get(code)
    if word is None:
        return "other", None, False
    if code == "SG":
        return "other", None, True  # a stratigraphic test well is neither a producer nor a service well
    band = C.band_of("", word)
    return band, (C.fluid_of(word) if band == "new" else None), True


def csv_bytes(data):
    """The bytes of wellspublic.csv from the downloaded zip: found by name, size-checked before and while reading, held in memory only."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("the download is not a zip file")
    found = [i for i in z.infolist() if os.path.basename(i.filename).lower() == MEMBER]
    if len(found) != 1:
        raise RuntimeError("the zip does not hold exactly one %s (%d)" % (MEMBER, len(found)))
    if found[0].file_size > MAX_CSV:
        raise RuntimeError("%s is larger than %d bytes" % (MEMBER, MAX_CSV))
    with z.open(found[0]) as f:
        body = f.read(MAX_CSV + 1)
    if len(body) > MAX_CSV:
        raise RuntimeError("%s is larger than %d bytes" % (MEMBER, MAX_CSV))
    return body


def read_rows(body):
    """The needed columns of every row of the CSV, as dicts, one row at a time (the other 47 columns, among them the well's name, API number and location, are never kept).
    Columns are matched without regard to case (the file has mixed case, its dictionary upper case); a missing one raises."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("latin-1")
    rd = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(rd)]
    except StopIteration:
        raise RuntimeError("the permit file is empty")
    missing = [c for c in NEEDED if c.lower() not in header]
    if missing:
        raise RuntimeError("the permit file lost columns: " + ", ".join(missing))
    pick = [(c, header.index(c.lower())) for c in NEEDED]
    for row in rd:
        if row:
            yield {c: (row[i].strip() if i < len(row) else "") for c, i in pick}


def tally_rows(rows, today):
    """(Tally, stats) from the rows: every permit issued since January 2019 goes in by its issue date. Raises on a file that is not the file."""
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "other"), fluid=True)
    first = date(int(C.FIRST_MONTH[:4]), int(C.FIRST_MONTH[5:]), 1)
    n = dated = bad = series = unknown = 0
    newest = fresh = None
    for r in rows:
        n += 1
        mod = C.parse_day(r["Dt_Mod"], today)
        if mod and (fresh is None or mod > fresh):
            fresh = mod
        if not r["Permit_Issued"]:
            continue
        dated += 1
        day = C.parse_day(r["Permit_Issued"], today)
        if day is None:
            bad += 1
            continue
        if newest is None or day > newest:
            newest = day
        if day < first:
            continue
        band, fluid, known = classify(r["Original_well_type"], r["Well_Type"], r["SideTrck"], r["Completion"])
        series += 1
        unknown += not known
        t.add(day, band, county=r["County"], operator=r["Company_name"], fluid=fluid)
    if n < MIN_ROWS:
        raise RuntimeError("the permit file has %d rows (expected about 47,000)" % n)
    if dated < MIN_DATED or not newest:
        raise RuntimeError("only %d rows have a permit issue date (expected about 18,000)" % dated)
    if bad > MAX_BAD_SHARE * dated:
        raise RuntimeError("%d of %d issue dates are not dates: the file's layout may have changed" % (bad, dated))
    if series < MIN_SERIES:
        raise RuntimeError("only %d permits issued since 2019 (expected about 650)" % series)
    if unknown > MAX_UNKNOWN_SHARE * series:
        raise RuntimeError("%d of %d permits have a well type code the dictionary does not list" % (unknown, series))
    if (today - newest).days > MAX_PERMIT_AGE:
        raise RuntimeError("the newest permit was issued %s: the file looks stale" % newest.isoformat())
    asof = max(fresh or newest, newest)
    if (today - asof).days > MAX_FILE_AGE:
        raise RuntimeError("the newest update in the file is %s: it has not been refreshed" % asof.isoformat())
    return t, {"rows": n, "dated": dated, "series": series, "asof": asof}


def build(get=C.polite_get, today=None):
    today = today or date.today()
    t, st = tally_rows(read_rows(csv_bytes(get(URL, max_bytes=MAX_ZIP))), today)
    return t.document(
        agency="New York State Department of Environmental Conservation, Division of Mineral Resources",
        source_name="Oil and gas wells (wellDOS.zip: wellspublic.csv), updated every weekday night", source_url=URL,
        basis="issue date (the day the permit to drill was issued)", cadence="nightly, Monday to Friday", measure="permits", asof=st["asof"],
        note="Permits to drill by the day issued, one per well bore. The file has no work type: a sidetrack bore is told by its sidetrack code and counted under Re-entries and sidetracks, but a permit "
             "to deepen, re-enter, plug back or convert an existing well is not a row of its own, so those and amendments are not available. A further completion of an existing hole, stratigraphic test "
             "wells and permits with no type listed are under Other filings. Permits later expired, transferred or voided are counted. New York issues tens of permits a year, so a month is noisy; "
             "the file is rewritten nightly and a past month can move.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
