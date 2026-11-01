#!/usr/bin/env python3
"""D11: Alaska's permits to drill (Alaska Oil and Gas Conservation Commission, AOGCC), for the National report of the Oil tracker.

The Commission's Data Miner (http://aogweb.state.ak.us/DataMiner4/) has a "ZIP (All Data)" button on each of its pages. Two of those zips are the whole record in one small file each (about
0.9 and 1.9 MB, one .xlsx inside), on the Commission's own storage (https://aogcccdnstorage.blob.core.windows.net/dataminerzip/): so a run is two requests, three seconds apart, and reads
everything again (a permit's date can be corrected; nothing is kept from an earlier run):

  wellhistory.zip   the Data Miner's "Well Work Dates": one row per dated event of every well, by permit number. The event "Dt Well Permit Approved" is the day the Commission
                    approved a Permit to Drill (every permit has one; "Dt Well Permit Issued" is the same day for 98% of them and is used only as a cross-check).
  wells.zip         the Data Miner's "Wells": the class the permit was issued for (Development, Exploratory, Service, Stratigraphic Test), the type (oil well, gas well, water
                    injection ...) and the area. One row per permit, plus one row for each plug-back (PB) or pilot hole (PH) that shares the permit and has no class: the row WITH a class is the well.

What is counted (measure `permits`, basis approval date): Permits to Drill approved, one per permit number, on the day of its first approval. The Commission gives every sidetrack and every
lateral leg of an existing well a permit of its own, so a year holds 90 to 190 permits, of which about half are for new holes. A permit is in one band:

  new      the original hole of a well (sidetrack code 00 in its well number) whose class is Development or Exploratory (fluid: the well type on the permit, oil or gas; unknown if blank)
  inj      the original hole of a Service well (injection, disposal, storage, water supply)
  redrill  a sidetrack or a lateral leg of an existing well (any sidetrack code but 00), of any class
  other    an original hole of a Stratigraphic Test (an information well, not drilled for oil or gas)
  rework, amend: null. The file dates no recompletion or plug-back permit, and a permit amended by sundry notice is not in it; "Dt Well Permit Re-Issued" (a few a year, mostly within
                 three months of the approval) is not read as an amendment because the Commission's meaning of it is not stated, and is not counted as a second approval.

The places are the Commission's AREAS (Arctic Slope, Cook Inlet Basin ...): the file has no borough. The operator is the company the permit file names (only corporations, LLCs and
partnerships are published: the shared rule). No well name, lease, permit number or API number leaves this script: the well number is read only for its two sidetrack digits.

Refused rather than written: a file that is not the file (columns gone, too few rows, no approvals, an unknown well class), a export more than 45 days old or no approval in 45 days (the
Commission approves about twelve a month), a join that loses the class of more than 2% of the approvals, approvals and issues that disagree by more than 40%, and a history that shrank
against the committed file (more than 10% fewer permits in the months both hold). The .xlsx is untrusted data: parsed as XML in memory, never run, entity declarations refused, sizes capped.

  python3 -I site/pipeline/d11_nat_ak.py [--check]
"""
import collections
import io
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "AK"
BASE = "https://aogcccdnstorage.blob.core.windows.net/dataminerzip/"
HISTORY_URL = BASE + "wellhistory.zip"
WELLS_URL = BASE + "wells.zip"
PAUSE = 3.0
MAX_ZIP = 25 * 1024 * 1024  # the real zips are 0.9 and 1.9 MB
MAX_SHEET = 400 * 1024 * 1024  # the real sheets are 28 and 26 MB unpacked
STALE_DAYS = 45
MIN_HISTORY_ROWS, MIN_WELLS_ROWS, MIN_APPROVALS = 50000, 8000, 800  # the real files hold 85,000, 12,000 and 1,070 (since 2019)
APPROVED = "Dt Well Permit Approved"
ISSUED = "Dt Well Permit Issued"
HISTORY_COLUMNS = ("Api", "Permit", "ActivityDate", "OperatorName", "TypeWork")
WELLS_COLUMNS = ("Api", "Permit", "AreaName", "PermittedClass", "PermittedStatus")
CLASSES = {"development": "new", "exploratory": "new", "service": "inj", "stratigraphic test": "other"}
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


# ------------------------------------------------------------------------------------------------ the workbook

def col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _safe_xml(raw):
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise RuntimeError("the workbook declares entities: refused")
    return raw


def sheet_path(z):
    """The member path of the first worksheet, from the workbook and its relationships (the writer uses a prefix on every tag and absolute targets)."""
    wb = ET.fromstring(_safe_xml(z.read("xl/workbook.xml")))
    sheets = wb.find(MAIN + "sheets")
    if sheets is None or not len(sheets):
        raise RuntimeError("the workbook has no sheet")
    rid = sheets[0].get(RELNS + "id")
    for r in ET.fromstring(_safe_xml(z.read("xl/_rels/workbook.xml.rels"))):
        if r.get("Id") == rid:
            t = r.get("Target") or ""
            return t.lstrip("/") if t.startswith("/") else "xl/" + t
    raise RuntimeError("the workbook's first sheet has no file")


def shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return None
    root = ET.fromstring(_safe_xml(z.read("xl/sharedStrings.xml")))
    return ["".join(t.text or "" for t in si.iter(MAIN + "t")) for si in root.iter(MAIN + "si")]


def xlsx_rows(data):
    """Rows of the first sheet of an .xlsx given as bytes: lists of text (None for an empty cell), the header first. Cells may carry a position (r="C7") or follow one another; a row with
    fewer cells than the header, when positions are not given, raises (a shifted column would be read as another column's value)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("the download is not a workbook")
    path = sheet_path(z)
    info = z.getinfo(path)
    if info.file_size > MAX_SHEET:
        raise RuntimeError("the sheet unpacks to more than %d bytes: refused" % MAX_SHEET)
    shared = shared_strings(z)
    with z.open(path) as f:
        head = f.read(4096)
        _safe_xml(head)
    width = None
    with z.open(path) as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag != MAIN + "row":
                continue
            cells, positioned = [], False
            for c in el.findall(MAIN + "c"):
                ref = c.get("r")
                idx = col_index(ref) if ref else len(cells)
                positioned = positioned or bool(ref)
                t = c.get("t")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(MAIN + "t"))
                else:
                    v = c.find(MAIN + "v")
                    val = v.text if v is not None else None
                    if t == "s" and val is not None:
                        if shared is None:
                            raise RuntimeError("the sheet uses shared strings that are not there")
                        val = shared[int(val)]
                if val is not None:
                    val = val.strip() or None
                while len(cells) < idx:
                    cells.append(None)
                cells.append(val)
            el.clear()
            if not any(c is not None for c in cells):
                continue  # a blank row
            if width is None:
                width = len(cells)
            elif len(cells) < width and not positioned:
                raise RuntimeError("a row has %d cells under a header of %d: the sheet's layout changed" % (len(cells), width))
            elif len(cells) < width:
                cells += [None] * (width - len(cells))
            yield cells


def table(data, want):
    """(header, iterator of dicts of the wanted columns) from an .xlsx; a missing wanted column raises."""
    it = xlsx_rows(data)
    try:
        header = next(it)
    except StopIteration:
        raise RuntimeError("the workbook is empty")
    names = [(h or "").strip() for h in header]
    missing = [w for w in want if w not in names]
    if missing:
        raise RuntimeError("columns not in the sheet: %s" % ", ".join(missing))
    pos = {w: names.index(w) for w in want}
    return names, ({w: (row[i] if i < len(row) else None) for w, i in pos.items()} for row in it)


def unzip_one(data, what):
    """The one .xlsx inside a Data Miner zip: (its bytes, the day it was made). Anything else raises."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("the %s download is not a zip" % what)
    names = [i for i in z.infolist() if not i.is_dir()]
    if len(names) != 1 or not names[0].filename.lower().endswith(".xlsx"):
        raise RuntimeError("the %s zip does not hold exactly one .xlsx" % what)
    info = names[0]
    if info.file_size > MAX_ZIP:
        raise RuntimeError("the %s workbook is larger than %d bytes: refused" % (what, MAX_ZIP))
    try:
        made = date(*info.date_time[:3])
    except ValueError:
        made = None
    return z.read(info), made


# ------------------------------------------------------------------------------------------------ reading the two files

def excel_or_text_day(text):
    """A day from '10/16/1963 12:00:00 AM' (what the file writes) or an Excel serial number; None for blank; ValueError for anything else."""
    if text is None:
        return None
    s = str(text).strip()
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        return (datetime(1899, 12, 30) + timedelta(days=float(s))).date()
    return datetime.strptime(s.split()[0], "%m/%d/%Y").date()


def read_history(data, first_year=int(C.FIRST_MONTH[:4])):
    """({permit: (first approval day, operator, sidetrack code)}, {permit: first issue day}, rows read). Only what the count needs is kept: the permit number (a key, never written), the
    day, the operator's name and two digits of the well number. Approvals before 2019 are not kept."""
    _names, rows = table(data, HISTORY_COLUMNS)
    approved, issued, code, ops = {}, {}, {}, {}
    n = 0
    for r in rows:
        n += 1
        p, tw = r["Permit"], r["TypeWork"]
        if not p:
            continue
        api = r["Api"] or ""
        if re.fullmatch(r"\d{14}", api):
            code[p] = min(code.get(p, "99"), api[10:12])  # the well's own hole is the lowest code of its rows (a pilot hole or plug-back carries 70 and up)
        elif api and re.fullmatch(r"\d+", api) is None:
            raise RuntimeError("a well number is not digits: the file's layout changed")
        if tw not in (APPROVED, ISSUED):
            continue
        try:
            day = excel_or_text_day(r["ActivityDate"])
        except ValueError:
            raise RuntimeError("an approval or issue date is not a date: the file's layout changed")
        if day is None:
            continue
        if tw == APPROVED:
            if p not in approved or day < approved[p][0]:
                approved[p] = (day, r["OperatorName"])
        elif p not in issued or day < issued[p]:
            issued[p] = day
    out = {}
    for p, (day, op) in approved.items():
        if day.year < first_year:
            continue
        api_code = code.get(p)
        if api_code is None:
            raise RuntimeError("an approval since %d has no 14-digit well number: the file's layout changed" % first_year)
        out[p] = (day, op, api_code)
    return out, issued, n


def read_wells(data):
    """{permit: (area, class, type)} from the Data Miner's Wells: the row of each permit that has a class (its plug-back and pilot-hole rows have none); if a permit has two such rows the one with
    the lowest well number wins, so a different order of the rows cannot change the result. Rows read, too."""
    _names, rows = table(data, WELLS_COLUMNS)
    best, n = {}, 0
    for r in rows:
        n += 1
        p = r["Permit"]
        if not p or not r["PermittedClass"]:
            continue
        key = r["Api"] or ""
        if p not in best or key < best[p][0]:
            best[p] = (key, (r["AreaName"], r["PermittedClass"], r["PermittedStatus"]))
    return {p: v[1] for p, v in best.items()}, n


def area_label(name):
    """The Commission's area as a place name: 'ARCTIC OCEAN, ST.' is 'Arctic Ocean (State)'; 'Unknown' and blank are no place."""
    n = " ".join(str(name or "").split())
    if not n or n.lower() == "unknown":
        return None
    m = re.fullmatch(r"(.*?),\s*(ST|FED)\.?", n, re.I)
    if m:
        n = "%s (%s)" % (m.group(1), "State" if m.group(2).upper() == "ST" else "Federal")
    return n


def classify(code, pclass):
    """The band of a permit: a sidetrack or lateral (any sidetrack code but 00) is a re-drill of any class; an original hole goes by the class the permit was issued for."""
    if code != "00":
        return "redrill"
    return CLASSES.get((pclass or "").strip().lower(), "other")


def previous_totals(path=None):
    """{month: all permits} from the committed nat/AK.json, for the shrink check; {} when there is none."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        return {ym: sum(v[i] for v in d["bands"].values() if v) for i, ym in enumerate(d["months"])}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


# ------------------------------------------------------------------------------------------------ the build

def build(get=C.polite_get, pause=PAUSE, today=None, old=None):
    today = today or date.today()
    hist_zip = get(HISTORY_URL, max_bytes=MAX_ZIP)
    if pause:
        time.sleep(pause)
    wells_zip = get(WELLS_URL, max_bytes=MAX_ZIP)
    hist_book, made = unzip_one(hist_zip, "Well Work Dates")
    wells_book, made_wells = unzip_one(wells_zip, "Wells")
    for what, day in (("Well Work Dates", made), ("Wells", made_wells)):
        if day is None or (today - day).days > STALE_DAYS:
            raise RuntimeError("the %s export was made %s: more than %d days ago" % (what, day, STALE_DAYS))
    approvals, issued, rows = read_history(hist_book)
    wells, wells_rows = read_wells(wells_book)
    if rows < MIN_HISTORY_ROWS or wells_rows < MIN_WELLS_ROWS:
        raise RuntimeError("the files are far smaller than they were (%d and %d rows): refusing" % (rows, wells_rows))
    if len(approvals) < MIN_APPROVALS:
        raise RuntimeError("only %d approvals since %s (the file has over 1,000): refusing" % (len(approvals), C.FIRST_MONTH))
    newest = max(d for d, _o, _c in approvals.values())
    if newest > today:
        raise RuntimeError("an approval is dated in the future")
    if (today - newest).days > STALE_DAYS:
        raise RuntimeError("the newest approval is %s: the export looks stalled" % newest)
    # every approval needs the class its permit was issued for; a permit with no row in the Wells file is counted (as a re-drill if it is one, else under `other`) but may not be many
    lost = [p for p in approvals if p not in wells]
    if len(lost) > 0.02 * len(approvals):
        raise RuntimeError("%d of %d approvals have no class in the Wells file: refusing" % (len(lost), len(approvals)))
    unknown = {w[1].strip().lower() for p, w in wells.items() if p in approvals} - set(CLASSES)
    if unknown:
        raise RuntimeError("the Commission has a well class this producer does not know: %s" % ", ".join(sorted(unknown)))
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "other"), fluid=True)
    month_all = collections.Counter()
    for p, (day, op, code) in sorted(approvals.items()):
        area, pclass, ptype = wells.get(p, (None, None, None))
        band = classify(code, pclass)
        t.add(day, band, county=area_label(area), operator=(op or ""), fluid=C.fluid_of(ptype))
        month_all[C.month_of(day)] += 1
    # the cross-check inside the file: permits issued by month against permits approved (the same day for 98% of them)
    through = max((ym for ym in C.month_list(C.FIRST_MONTH, C.month_of(newest)) if C.month_end(ym) <= newest), default=None)
    if through is None:
        raise RuntimeError("no complete month yet")
    last24 = C.month_list(C.add_months(through, -23), through)
    appr24 = sum(month_all.get(ym, 0) for ym in last24)
    iss24 = sum(1 for d in issued.values() if C.month_of(d) in set(last24))
    if appr24 < 20 or not 0.6 * appr24 <= iss24 <= 1.4 * appr24:
        raise RuntimeError("permits approved (%d) and permits issued (%d) in the last 24 months disagree: the file's event names may have changed" % (appr24, iss24))
    # a history that shrank is a file that lost rows
    old = previous_totals() if old is None else old
    both = [ym for ym in old if ym <= through]
    if both and sum(old[ym] for ym in both) >= 100:
        was, now = sum(old[ym] for ym in both), sum(month_all.get(ym, 0) for ym in both)
        if now < 0.9 * was:
            raise RuntimeError("the history shrank: %d permits in the months the committed file holds, against %d now" % (was, now))
    doc = t.document(agency="Alaska Oil and Gas Conservation Commission (AOGCC)", source_name="AOGCC Data Miner: Well Work Dates and Wells (the 'ZIP (All Data)' downloads)", source_url=HISTORY_URL,
                     basis="approval date", cadence="each weekday (the Data Miner is refreshed every weekday evening)", measure="permits", place="areas",
                     note="Permits to Drill approved by the Alaska Oil and Gas Conservation Commission, counted by the day each was approved. The Commission gives every sidetrack and every lateral leg of a well a permit of "
                          "its own, so these are permits, and many are for existing wells: new wells are the original holes of Development and Exploratory class, injection and disposal the original holes of Service "
                          "class, re-entries and sidetracks the sidetracks and laterals of existing wells, and other filings the stratigraphic test wells (drilled for information, not oil or gas). The file dates "
                          "no recompletion or amendment, so those kinds are not available. The places are the Commission's areas, not boroughs.")
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
