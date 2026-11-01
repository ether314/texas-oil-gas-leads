#!/usr/bin/env python3
"""D11: Utah's drilling permits (the Division of Oil, Gas and Mining's APDs), for the National report of the Oil tracker.

The Division (DOGM) publishes two free bulk files, refreshed daily, that need no login (https://oilgas.ogm.utah.gov/oilgasweb/data-center/dc-main.xhtml):

  WellHistory.zip  one row per well and piece of work: WorkType (DRILL, DEEPEN, REENTER, RECOMP, CONVERT, REPERF, PLUG), APDApprovedDate, the well's current type
  Wells.zip        one row per well: its county and current operator (joined on WellID, the first ten digits of the API number)

What is counted: an Application for Permit to Drill (APD) APPROVED by the Division, by the day it was approved (`measure="permits"`), 2019 to the newest complete month.
  new      a DRILL approval for an oil, gas or wildcat well (a dry hole is a well too)
  inj      a DRILL approval for a service well: water or gas injection, water disposal, gas storage, water source, test or monitor wells (Utah's own term is "service well")
  redrill  a DEEPEN or REENTER approval
  other    a DRILL approval for a potash, lithium, helium or carbon dioxide well
Together they equal the Division's own "APDs by year" page (statistics/apds-by-year.xhtml) for every year 2020 to 2025 (389, 388, 340, 799, 439, 525; 2019 is 264 here and 263 there).
Not counted, and published as not available (null, never zero): recompletions, conversions and re-perforations (a sundry notice of intent; the file records them only for work that was
done, a few dozen a year with no steady pattern) and amendments (an APD that is extended or re-approved keeps one row). Plugging is a sundry notice too and is not a permit to drill.

What the figures are NOT: the well's type, its county and its OPERATOR are the CURRENT values in the Well Data file, not those on the day of the permit (a well sold or converted since shows
its new operator and type). The file has no posting date, so a permit approved in the last days may appear a day or two late; October is only shown once November has its first approval.

Privacy: only a county name and a corporate operator name reach the tally. The files hold well names, lease numbers, API numbers and coordinates: none is read past the join.
The files are untrusted data: parsed as text, never run; the zips are size-checked before they are opened. Requests identify no person and are a few seconds apart.

  python3 -I site/pipeline/d11_nat_ut.py [--check]
"""
import csv
import io
import os
import re
import sys
import time
import zipfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "UT"
BASE = "https://oilgas.ogm.utah.gov/pub/Database/"
HISTORY_URL = BASE + "WellHistory.zip"
WELLS_URL = BASE + "Wells.zip"
PAUSE = 3.0
HIST_COLS = ("WellID", "SideTrack", "WorkType", "APDNumber", "APDApprovedDate", "CurrentWellType")
WELL_COLS = ("API", "Operator", "CountyName", "welltype")
MIN_HIST, MIN_WELLS, MIN_APPROVALS = 30000, 25000, 1500  # the files held 52,897 and 40,451 rows and 3,856 approvals since 2019 on 2026-10-31
MAX_ZIP, MAX_UNZIPPED = 25_000_000, 100_000_000  # 1.6 MB and 12.9 MB (history); 2.3 MB and 12.2 MB (wells)
MAX_AGE_DAYS = 60  # the newest approval is never older than this unless the file stopped being refreshed
BANDS = ("new", "inj", "redrill", "other")

# the Division's own codes (the ReadMe's tables), as words for the shared classifier
WORK_WORDS = {"DRILL": "drill a new well", "DEEPEN": "deepen an existing well", "REENTER": "re-enter a plugged well and drill"}
TYPE_WORDS = {
    "OW": "oil well", "GW": "gas well", "OGW": "oil and gas well", "D": "dry hole",
    "OWI": "oil well with water injection", "GWI": "gas well with water injection", "OGI": "oil well with gas injection", "GGI": "gas well with gas injection",
    "OWD": "oil well with water disposal", "GWD": "gas well with water disposal",
    "WI": "water injection service well", "GI": "gas injection service well", "WD": "water disposal service well", "WS": "water source service well",
    "GS": "gas storage service well", "TW": "test or monitor service well",
}
OTHER_MINERAL = frozenset({"PO", "LI", "HE", "CD"})  # potash, lithium, helium, carbon dioxide wells
DATE = re.compile(r"^\d{1,2}/\d{1,2}/(\d{4})$")


# ------------------------------------------------------------------------------------------------ reading the files

def read_table(data, name, needed):
    """The rows of the one CSV inside a zip, as dicts holding only the `needed` columns (NULL and blank become ''). Raises on a reply that is not a zip (an error page), a zip with
    anything but one CSV, a file too large to open, a missing column (the layout changed) or ragged rows."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("%s: the reply is not a zip file (an error page?)" % name)
    members = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError("%s: expected one CSV in the zip, found %d" % (name, len(members)))
    if members[0].file_size > MAX_UNZIPPED:
        raise ValueError("%s: the CSV is %d bytes unzipped, past the %d allowed" % (name, members[0].file_size, MAX_UNZIPPED))
    with z.open(members[0]) as f:
        raw = f.read(MAX_UNZIPPED + 1)  # the header can lie about the size: read at most the cap
    if len(raw) > MAX_UNZIPPED:
        raise ValueError("%s: the CSV is larger than the %d bytes allowed" % (name, MAX_UNZIPPED))
    rd = csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace"), newline=""))
    header = [h.strip() for h in next(rd, [])]
    missing = [c for c in needed if c not in header]
    if missing:
        raise ValueError("%s: column %s is missing: the layout changed" % (name, ", ".join(missing)))
    idx = [(c, header.index(c)) for c in needed]
    width = len(header)
    out, ragged = [], 0
    for row in rd:
        if not any(x.strip() for x in row):
            continue
        if len(row) != width:
            ragged += 1
            continue
        out.append({c: ("" if row[i].strip() in ("", "NULL") else row[i].strip()) for c, i in idx})
    if ragged > max(5, len(out) // 100):
        raise ValueError("%s: %d rows do not have the header's %d columns" % (name, ragged, width))
    return out


def well_index(wells):
    """{(ten digits, sidetrack): row} and {ten digits: row}: a well is found by its sidetrack first, by the ten digits otherwise."""
    exact, loose = {}, {}
    for w in wells:
        api = re.sub(r"\D", "", w["API"])
        if len(api) < 10:
            continue
        loose.setdefault(api[:10], w)
        if len(api) >= 12:
            exact.setdefault((api[:10], int(api[10:12])), w)
    return exact, loose


def find_well(index, well_id, sidetrack):
    exact, loose = index
    key = re.sub(r"\D", "", well_id)[:10]
    try:
        st = int(sidetrack)
    except ValueError:
        st = None
    return exact.get((key, st)) or loose.get(key)


def approved_day(text, today):
    """(date or None, stray): the approval day of one row. A blank is no approval; a date before 2000 is history this report does not show; anything else that is not a real day
    on or before today is `stray` (a typo in the file, counted so that a damaged file fails the run)."""
    if not text:
        return None, False
    m = DATE.match(text)
    if not m:
        return None, True
    if int(m.group(1)) < 2000:
        return None, False
    d = C.parse_day(text, today)
    return d, d is None


def classify(work, wtype):
    """(band, fluid) of one approval from the Division's work type and the well's type code."""
    if wtype in OTHER_MINERAL and work == "DRILL":
        return "other", None
    words = WORK_WORDS.get(work)
    if words is None:
        return "other", None  # a work type this producer does not know: counted, and never as a new well
    desc = TYPE_WORDS.get(wtype, "")
    return C.band_of(words, desc), C.fluid_of(desc)


def tally_approvals(hist, wells, today):
    """The Tally of the approvals in the history file. Raises when the dates are damaged, the wells cannot be joined, or too little was read."""
    index = well_index(wells)
    t = C.Tally(STATE, bands=BANDS, fluid=True)
    seen, stray, joined, recent = set(), 0, 0, 0
    first_day = date(int(C.FIRST_MONTH[:4]), int(C.FIRST_MONTH[5:]), 1)
    horizon = date(today.year - 3, today.month, 1)
    for r in hist:
        day, bad = approved_day(r["APDApprovedDate"], today)
        stray += bad
        if day is None or day < first_day:
            continue
        if r["WorkType"] in ("RECOMP", "CONVERT", "REPERF", "PLUG"):
            continue  # sundry notices, not permits to drill (the file gives them an approval date only by accident)
        key = (r["WellID"], r["SideTrack"], r["WorkType"], r["APDNumber"], day)
        if key in seen:  # the file repeats a row for a piece of work with two events
            continue
        seen.add(key)
        w = find_well(index, r["WellID"], r["SideTrack"])
        wtype = r["CurrentWellType"] or (w or {}).get("welltype", "")
        band, fluid = classify(r["WorkType"], wtype)
        if day >= horizon:
            recent += 1
            joined += w is not None
        t.add(day, band, county=(w or {}).get("CountyName"), operator=(w or {}).get("Operator", ""), fluid=fluid)
    if stray > max(10, len(seen) // 100):
        raise ValueError("%d approval dates are not real dates: the layout or the file is damaged" % stray)
    if t.read < MIN_APPROVALS:
        raise ValueError("only %d approvals since 2019 were read (expected about 3,800)" % t.read)
    if recent and joined < 0.9 * recent:
        raise ValueError("only %d of %d recent approvals could be matched to a well: the Well Data file's layout changed" % (joined, recent))
    return t


def build(get=C.polite_get, pause=PAUSE, today=None):
    today = today or date.today()
    hist = read_table(get(HISTORY_URL, max_bytes=MAX_ZIP), "WellHistory.csv", HIST_COLS)
    if len(hist) < MIN_HIST:
        raise ValueError("WellHistory.csv has %d rows (expected 50,000 or more)" % len(hist))
    time.sleep(pause)
    wells = read_table(get(WELLS_URL, max_bytes=MAX_ZIP), "Wells.csv", WELL_COLS)
    if len(wells) < MIN_WELLS:
        raise ValueError("Wells.csv has %d rows (expected 40,000 or more)" % len(wells))
    t = tally_approvals(hist, wells, today)
    if (today - t.newest).days > MAX_AGE_DAYS:
        raise ValueError("the newest approval is from %s: the Division's file has stopped being refreshed" % t.newest)
    return t.document(
        agency="Utah Division of Oil, Gas and Mining", source_name="Well History and Well Data download files (daily)", source_url=HISTORY_URL, basis="approval date (APD approved)",
        cadence="daily", measure="permits", unit="APDs approved",
        note="Applications for Permit to Drill approved by the Division, by approval date: new wells, service wells (injection, disposal, storage, test), re-entries and deepenings, and a few potash, "
             "lithium, helium and carbon dioxide wells. Well type, county and operator are the well's current values, not those on the day of the permit. Recompletions, conversions "
             "and amendments are not available: the Division's file records them only as completed work.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
