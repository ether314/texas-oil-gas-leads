#!/usr/bin/env python3
"""D11: Arkansas's drilling permits (Arkansas Oil and Gas Commission, AOGC), for the National report of the Oil tracker.

The Commission publishes one report every week, "Permit and Completion Reports" (https://dataexplorer.aogc.arkansas.gov/data/completion.aspx: a year to choose, a folder for each month, then one file a
week, named for the Friday the week ends). Each report lists, for North and for South Arkansas, the drilling permits (Form 2) the Commission issued that week, the well completions (Form 3), the
recompletions and workovers (Form 3), and the applications to plug and plugging reports (Forms 11 and 12), under the title "Permits Issued During Week Ending: <date>". The reports are Excel workbooks from
mid-2020 and PDFs before (403 of them from January 4, 2019 to October 23, 2026 when written). The page is an ASP.NET form (choosing a year is a postback that returns the whole tree of months and files), but
every file has a plain static address, so this reads the page, asks for the years it needs, and fetches each report by its address. The Commission's well layer on GeoStor is NOT used: its newest permit is
from 2025 and it carries no permit date.

What it counts, and what it cannot tell (NOTES_D11.md has the fuller account):

  - `measure` "permits", `basis` the week of issue: a report names the week, not the day, so each week is counted in the month that holds most of its days (its Wednesday), as West Virginia's is;
  - the purpose: the report prints a purpose word under the permit number of a permit that is not an original application. No word is a new well (`new`); "renewal" and "amend" are `amend` (a permit on
    which both are printed, as one in 2020 was, is one amendment); "re-entry" is `redrill`; a word this does not know is `other`. A few permits (7 of 274 in the workbooks) are listed a second time with no
    word printed and are counted as listed;
  - what the list cannot tell: its columns hold no well type, so disposal, brine-supply and carbon-storage wells (a few a year) are among the `new`, and `inj` and `rework` are null, never zero (a rework is
    on the Commission's Form 3 list, which is not a permit); there is no fluid either (`fluid` is null); `unit` says "drilling permits";
  - the county is the one the API number's county place names (083 is Logan: the code of Arkansas's counties in alphabetical order, odd numbers), because the printed county cell moves between rows (and is
    once a typo); it is taken from the printed cell only when the API number is malformed;
  - a week with no permit says NONE in both Form 2 sections, so a quiet month is a real zero; a week the Commission did not post (5 of about 400 since 2019) is not a zero: the month it falls in may be short,
    and the note says which weeks (`KNOWN_MISSING` carries the ones before a weekly run's window);
  - Arkansas is small: 25 to 65 original permits a year (40 to 80 listings in all), so a month holds 0 to 12.

Nothing leaves a report but the purpose's band, the county and the operator's name (published only if it is a corporation, LLC or partnership: the naming rule): no permit or API number (the API number is
read only to find the county and never kept), well or field or lease name, address, location or contractor. The reports are untrusted data: a workbook is read as XML after its sizes are checked, a PDF only
through `pdftotext -layout` in a new folder; requests identify no person and are 3 seconds apart.

A full read is about 400 files and takes about 25 minutes (done by hand once, and committed). When a committed nat/AR.json exists, months older than the last 14 are taken from it and only the weeks of the last
14 months (about 60 files, 3 to 4 minutes) are read again, since a report may be corrected after release; delete the committed file to read everything.

  python3 -I site/pipeline/d11_nat_ar.py [--check]
"""
import calendar
import html
import io
import json
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
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "AR"
HOST = "https://dataexplorer.aogc.arkansas.gov"
PAGE = HOST + "/data/completion.aspx"
FILES = HOST + "/Data/Wipe/"  # the static home of each report: <year>/<mm-Month>/<file>
YEAR_FIELD = "ctl00$ctl00$cpMainContent$ChildContent2$ddlYear"
FIRST = "2019-01"  # the first report (the week ending 2019-01-04) is the oldest in the archive
PAUSE = 3.0
REREAD = 14  # months counted again each run when a committed file exists
MAX_PAGE = 3_000_000
MAX_REPORT = 3_000_000  # a weekly report is 25 to 200 KB
MAX_UNZIPPED = 20_000_000
MIN_FILES_ALL = 300  # reports since 2019 (about 400 in October 2026)
MIN_LISTINGS_ALL = 100  # a full read
MIN_LISTINGS_WINDOW = 8  # the months counted by a weekly run (about 40 a year)
STALE_DAYS = 45  # the newest report may not be older than this
MAX_MISSING = 10  # weeks without a report a run may meet (5 since 2019)
MAX_UNREAD = 3  # listings a run may count without a readable county (or 3 percent of them)
KNOWN_MISSING = frozenset({date(2019, 11, 29), date(2024, 1, 19), date(2024, 10, 4), date(2026, 1, 30), date(2026, 5, 8)})  # the Fridays with no report when the archive was first read in full (2026-11-01)
COUNTY_NAMES = (  # in the order of the county places of an API number (alphabetical, with "St. Francis" spelled out as Saint)
    "Arkansas", "Ashley", "Baxter", "Benton", "Boone", "Bradley", "Calhoun", "Carroll", "Chicot", "Clark", "Clay", "Cleburne", "Cleveland", "Columbia", "Conway", "Craighead",
    "Crawford", "Crittenden", "Cross", "Dallas", "Desha", "Drew", "Faulkner", "Franklin", "Fulton", "Garland", "Grant", "Greene", "Hempstead", "Hot Spring", "Howard",
    "Independence", "Izard", "Jackson", "Jefferson", "Johnson", "Lafayette", "Lawrence", "Lee", "Lincoln", "Little River", "Logan", "Lonoke", "Madison", "Marion", "Miller",
    "Mississippi", "Monroe", "Montgomery", "Nevada", "Newton", "Ouachita", "Perry", "Phillips", "Pike", "Poinsett", "Polk", "Pope", "Prairie", "Pulaski", "Randolph",
    "St. Francis", "Saline", "Scott", "Searcy", "Sebastian", "Sevier", "Sharp", "Stone", "Union", "Van Buren", "Washington", "White", "Woodruff", "Yell")
COUNTIES = frozenset(n.upper() for n in COUNTY_NAMES)
HEADING = re.compile(r"^\s*(NORTH|SOUTH)\s+ARKANSAS\s+(DRILLING\s+PERMITS|WELL\s+COMPLETIONS|RECOMPLETIONS|APPLICATION\s+TO\s+PLUG)", re.I)
TITLE = re.compile(r"Week\s+Ending\s*:?\s*([A-Za-z]{3,})\s*(\d{1,2})\s*,?\s*(\d{4})")  # typed by hand: "May13, 2022", "Februarey 3, 2023"
LEAF = re.compile(r"\*\|\*WIPE\*\|\*(\d{4})\*\|\*(\d\d-[A-Za-z]+)\*\|\*([^'&\\*|]+\.(?:xlsx|xls|pdf))", re.I)
MONTHS = {m.lower()[:3]: i + 1 for i, m in enumerate(calendar.month_name[1:])}  # a month is told by its first three letters
PERMIT_NO = re.compile(r"^\d{3,6}(\.0)?$")
NAME_DAY = re.compile(r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{4}|\d{2})")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ------------------------------------------------------------------------------------------------ the page and its postback

TRIES = 4  # attempts for one request: the Commission's server drops about one connection in ten, and sometimes two in a row; a refusal is never tried again


def polite_post(url, fields, max_bytes=MAX_PAGE, timeout=90, tries=TRIES, pause=PAUSE):
    """The body of one form post as bytes, with the rules of C.polite_get: a refusal raises Refused at once, a dropped connection or a 5xx is tried once more after a pause, TLS is verified."""
    body = urllib.parse.urlencode(fields).encode("ascii")
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": C.UA, "Content-Type": "application/x-www-form-urlencoded", "Referer": PAGE})
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


def hidden_fields(page):
    """The ASP.NET state of the form ({name: value} of its hidden inputs): the page posts it back with the year chosen."""
    out = {}
    for tag in re.findall(r"<input\b[^>]*>", page, re.I):
        if not re.search(r'type="hidden"', tag, re.I):
            continue
        name, value = re.search(r'name="([^"]*)"', tag), re.search(r'value="([^"]*)"', tag)
        if name:
            out[html.unescape(name.group(1))] = html.unescape(value.group(1)) if value else ""
    return out


def year_options(page):
    """The years the page's year list offers, newest first."""
    sel = re.search(r'<select[^>]*id="cpMainContent_ChildContent2_ddlYear"[^>]*>([\s\S]*?)</select>', page)
    return sorted({int(y) for y in re.findall(r'<option[^>]*value="(\d{4})"', sel.group(1))} if sel else (), reverse=True)


def parse_tree(page):
    """[(year, month folder, file name)] of every report the tree lists (each file once). A leaf is a postback whose argument ends with ...|WIPE|<year>|<mm-Month>|<file>."""
    out, seen = [], set()
    for arg in re.findall(r"__doPostBack\(&#39;ctl00\$ctl00\$cpMainContent\$ChildContent2\$TreeView1&#39;,&#39;([^&]*)&#39;\)", page):
        m = LEAF.search(html.unescape(arg).split("\\")[-1])
        if m and m.groups() not in seen:
            seen.add(m.groups())
            out.append(m.groups())
    return out


def file_url(year, folder, name):
    return FILES + "/".join(urllib.parse.quote(x) for x in (year, folder, name))


def name_day(name):
    """The Friday a file's name gives ("WklyRep 10.23.26.xlsx", "WklyRep 2.6.2026.xlsx", "WklyRep 1-11-19.pdf"); None when it gives none. Names have typos: only the report's own title is trusted."""
    m = NAME_DAY.search(name)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------ one weekly report -> its Form 2 listings

def sheet_rows(data):
    """The cells of a workbook's first sheet as a list of {column number: text}, empty rows kept as {}. Sizes are checked before anything is unpacked; the workbook is only read, never run."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("a weekly report is not a workbook")
    sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets or sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
        raise RuntimeError("a weekly report's workbook is not the one expected")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si"):
            shared.append("".join(t.text or "" for t in si.iter(M + "t")))
    rows = []
    for r in ET.fromstring(z.read(sheets[0])).iter(M + "row"):
        cells = {}
        for c in r.iter(M + "c"):
            letters = re.match(r"[A-Z]+", c.get("r") or "")
            if not letters:
                continue
            n = 0
            for ch in letters.group(0):
                n = n * 26 + ord(ch) - 64
            t, v = c.get("t"), c.find(M + "v")
            if t == "s" and v is not None and v.text and v.text.isdigit() and int(v.text) < len(shared):
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            else:
                val = v.text if v is not None else None
            if val is not None and val.strip():
                cells[n] = " ".join(val.split())
        rows.append(cells)
    return rows


def week_end_of(text):
    """The Friday named in the report's title line ("Permits Issued During Week Ending: October 23, 2026"); None when there is no such line."""
    m = TITLE.search(text or "")
    if not m or m.group(1).lower()[:3] not in MONTHS:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
    except ValueError:
        return None


def resolve_end(title, named):
    """The Friday a report is for, from the date in its title and the date in its file's name. Both are typed by hand (a title was once a Monday, three days after the Friday its file is named for;
    others are misspelled), so: the title's nearest Friday when it is a Friday or agrees with the name, else the name's; both missing, or two dates more than a week apart, is a layout this does not know."""
    t = nearest_friday(title) if title else None
    n = nearest_friday(named) if named else None
    if t and n and t != n:
        if title.weekday() == 4:
            return t  # an exact Friday in the report's own title outranks a file name
        if abs((title - named).days) > 7:
            raise RuntimeError("a weekly report is titled %s and named for %s" % (title.isoformat(), named.isoformat()))
        return n
    if t or n:
        return t or n
    raise RuntimeError("a weekly report has no readable week ending date")


def clean_operator(name):
    """The operator's name as one spelling: trailing periods gone, so "Quanico Oil & Gas, Inc." and "Quanico Oil & Gas, Inc" are one operator. A text with digits in it is an address, not a name."""
    n = " ".join((name or "").split())
    return "" if re.search(r"\d{3,}", n) or not re.search(r"[A-Za-z]{3}", n) else re.sub(r"[.\s]+$", "", n)


def county_of(text):
    """The county in title case when the text is one of Arkansas's 75; None otherwise (a field's name, a typo, a cell that moved)."""
    c = " ".join((text or "").replace(".", ". ").split()).upper().replace(". ", ".")
    c = re.sub(r"^ST\.?\s*", "ST. ", c)
    return C.place_title(c) if c in COUNTIES else None


# the county place in an API number: Arkansas's counties in alphabetical order, the odd numbers 001 to 149 (the same code the federal FIPS list uses)
COUNTY_CODE = {"%03d" % (2 * i + 1): n.upper() for i, n in enumerate(COUNTY_NAMES)}


def county_from_api(api):
    """The county an API number's county place names ("03 083 11459" is Logan), None when the number is not of that shape (the Commission once printed "03 1319 13613", once "03 27 12164" for 027)."""
    g = re.findall(r"\d+", api or "")
    if len(g) == 3 and g[0] == "03" and len(g[1]) <= 3 and len(g[2]) <= 5:
        return county_of(COUNTY_CODE.get(g[1].zfill(3), ""))
    return None


def purpose_band(labels):
    """The band of the purpose words a report prints under a permit number. An original application prints none (a new well, disposal well or brine well: the list says no more); the others print renewal,
    amend or re-entry (once "reneral"). Several words can be on one permit ("renewal" and "amend"): an amendment or renewal wins over a re-entry. A word this does not know is `other`."""
    bands = set()
    for label in labels:
        t = re.sub(r"[^a-z]", "", (label or "").lower())
        if t:
            bands.add("amend" if t[:3] == "ren" or t[:4] in ("amen", "revi", "exte") else "redrill" if t[:4] in ("reen", "rent") else "other")
    return "amend" if "amend" in bands else "redrill" if "redrill" in bands else "other" if bands else "new"


def listing(api, labels, operator, cells):
    """One Form 2 permit as {'band', 'county', 'operator'}: the county from the API number's county place, else from a cell that names one (`cells`, the block's text cells)."""
    county = county_from_api(api) or next((c for c in (county_of(x) for x in cells) if c), None)
    return {"band": purpose_band(labels), "county": county, "operator": clean_operator(operator)}


QUIET = frozenset({"NONE", "DONE"})  # what a section with no permit says: NONE (the Commission once typed DONE, for a whole week's south sections)


def check_sections(end, headings, none, found):
    """A report must be the whole weekly report: both Form 2 headings and both well-completion headings (which close the Form 2 sections), and at least 6 of the 8 headings (the Commission once left out one
    heading of a long list). Each Form 2 section must list permits or say NONE."""
    names = set(headings)
    need = {("NORTH", "DRILLING PERMITS"), ("SOUTH", "DRILLING PERMITS"), ("NORTH", "WELL COMPLETIONS"), ("SOUTH", "WELL COMPLETIONS")}
    if len(names) != len(headings) or not need <= names or len(names) < 6:
        raise RuntimeError("the weekly report for %s has %d of the 8 sections (or one twice)" % (end.isoformat(), len(names)))
    for sec in ("NORTH", "SOUTH"):
        if not none.get(sec) and not found.get(sec):
            raise RuntimeError("the weekly report for %s has neither permits nor NONE in its %s Arkansas drilling permits" % (end.isoformat(), sec.lower()))


def week_from_rows(rows):
    """(title date, listings) from the cells of one weekly workbook: the Form 2 drilling permits of North and South Arkansas, in the order of the report. A permit is its first row (permit number, API number,
    well name, field) and the rows under it: the operator is the first column-2 text in them, and the purpose words (renewal, amend, re-entry) are the column-1 texts."""
    title = week_end_of(next((r[1] for r in rows if 1 in r and TITLE.search(r[1])), ""))
    headings, sec, cur, none, found, blocks = [], None, None, {}, {}, []
    for r in rows:
        a = r.get(1, "")
        h = HEADING.match(a)
        if h:
            headings.append((h.group(1).upper(), re.sub(r"\s+", " ", h.group(2).upper())))
            sec = h.group(1).upper() if headings[-1][1] == "DRILLING PERMITS" else None
            cur = None
            continue
        if sec is None or not r or a == "Permit Number":
            continue
        if len(r) == 1 and next(iter(r.values())).upper() in QUIET:
            none[sec], cur = True, None
        elif PERMIT_NO.match(a):
            found[sec] = True
            cur = {"api": r.get(2, ""), "cells": [r.get(4, "")], "labels": [], "operator": "", "rows": 0}
            blocks.append(cur)
        elif cur is not None:
            cur["rows"] += 1
            if a:
                cur["labels"].append(a)
            if not cur["operator"] and clean_operator(r.get(2, "")):
                cur["operator"] = r.get(2, "")
            if cur["rows"] <= 4:
                cur["cells"] += [r.get(k, "") for k in (3, 4, 5)]
    check_sections((title or date.min), headings, none, found)
    return title, [listing(b["api"], b["labels"], b["operator"], b["cells"]) for b in blocks]


PDF_PERMIT = re.compile(r"^\s{0,3}(\d{3,6})\s+(\d{2}[\s\-]+\d{1,3}[\s\-]+\d{4,5})(?=\s|$)")  # the API number is spaced, once hyphenated (2019)
PDF_NOISE = re.compile(r"^(Permit\s+API|Number\s+Operator|Address\b|Contractor\b|Start\s+Date\b|Form\s+1[12]\b|Latitude\b|Longitude\b)", re.I)
PDF_LABEL = re.compile(r"^([A-Za-z][A-Za-z\-]{2,})(?:\s+(\S.*))?$")  # a purpose word at the very start of a line, then (often) the operator


def week_from_text(text):
    """(title date, listings) from the text `pdftotext -layout` gives for a weekly PDF (2019 to mid-2020): the same sections and permits as the workbook, as lines. A permit starts with a line of permit
    number and API number; the lines under it hold the operator (the first text, after any purpose word at the line's start) and the county, and purpose words begin a line."""
    title = week_end_of(text)
    headings, sec, none, found, blocks, cur = [], None, {}, {}, [], None
    for line in text.splitlines():
        h = HEADING.match(line)
        if h:
            headings.append((h.group(1).upper(), re.sub(r"\s+", " ", h.group(2).upper())))
            sec = h.group(1).upper() if headings[-1][1] == "DRILLING PERMITS" else None
            cur = None
            continue
        s = line.strip()
        if sec is None or not s:
            continue
        if s.upper() in QUIET:
            none[sec], cur = True, None
            continue
        m = PDF_PERMIT.match(line)
        if m:
            found[sec] = True
            cur = {"api": m.group(2), "cells": [], "labels": [], "operator": "", "rows": 0}
            blocks.append(cur)
        elif cur is not None and not PDF_NOISE.match(s) and not s.isdigit():
            cur["rows"] += 1
            body = s
            lab = PDF_LABEL.match(line) if line[:1].isalpha() else None
            if lab:  # a word at column 0 is a purpose word; what follows it is the line's own text
                cur["labels"].append(lab.group(1))
                body = (lab.group(2) or "").strip()
            cells = [c for c in re.split(r"\s{2,}", body) if c]
            if cells and not cur["operator"] and clean_operator(cells[0]):
                cur["operator"] = cells[0]
            if cur["rows"] <= 4:
                cur["cells"] += cells
    check_sections((title or date.min), headings, none, found)
    return title, [listing(b["api"], b["labels"], b["operator"], b["cells"]) for b in blocks]


def pdf_to_text(data):
    """The text of a PDF through `pdftotext -layout` (poppler-utils), in a new folder, under a timeout. The PDF is data: nothing else opens it."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    with tempfile.TemporaryDirectory(prefix="ar-") as tmp:
        src = os.path.join(tmp, "report.pdf")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-layout", src, "-"], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")}, cwd=tmp)
        if r.returncode != 0:
            raise RuntimeError("pdftotext could not read a report")
        return r.stdout


def read_report(data, to_text=pdf_to_text):
    """(title date, listings) of one report by what the file is (a workbook is a zip, a PDF starts with %PDF), whatever its name says."""
    if data[:4] == b"PK\x03\x04":
        return week_from_rows(sheet_rows(data))
    if data[:5] == b"%PDF-":
        return week_from_text(to_text(data))
    raise RuntimeError("a weekly report is neither a workbook nor a PDF")


# ------------------------------------------------------------------------------------------------ the run

BANDS_TOLD = ("new", "amend", "redrill", "other")  # the bands a report's purpose words can tell; `inj` and `rework` are not on a Form 2 list


def previous(keep_from, path=None):
    """The committed nat/AR.json when it can stand for the months before `keep_from` ({month: {band: count}}); {} when there is none or it does not cover them."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        ok = d.get("state") == STATE and months[0] == FIRST and months == C.month_list(months[0], months[-1]) and months[-1] >= C.add_months(keep_from, -1)
        ok = ok and all(isinstance(bands[b], list) and len(bands[b]) == len(months) for b in BANDS_TOLD)
        return {ym: {b: bands[b][i] for b in BANDS_TOLD} for i, ym in enumerate(months) if ym < keep_from} if ok else {}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def nearest_friday(d):
    """The Friday a report's date stands for: the date itself when it is a Friday, else the nearest one."""
    return min((d + timedelta(days=k) for k in range(-3, 4) if (d + timedelta(days=k)).weekday() == 4), key=lambda x: (abs((x - d).days), x))


def week_day(end):
    """The day a week is counted on: its Wednesday, so the week lands in the month that holds most of its days."""
    return end - timedelta(days=2)


def dates_text(days):
    return ", ".join("%s %d, %d" % (calendar.month_name[d.month], d.day, d.year) for d in sorted(set(days)))


def build(get=C.polite_get, post=polite_post, to_text=pdf_to_text, pause=PAUSE, today=None, old=None):
    today = today or date.today()
    page = get(PAGE, max_bytes=MAX_PAGE, tries=TRIES, pause=pause).decode("utf-8", "replace")
    years, state = year_options(page), hidden_fields(page)
    keep_from = C.add_months(C.month_of(today), -REREAD)
    kept = (previous(keep_from) if old is None else old) if keep_from > FIRST else {}
    if not kept:
        keep_from = FIRST
    if not state.get("__VIEWSTATE") or not state.get("__EVENTVALIDATION") or today.year not in years or (not kept and 2019 not in years):
        raise RuntimeError("the reports page has no year list or form state it needs (years %s): its layout may have changed" % (years,))
    first_day = date(int(keep_from[:4]), int(keep_from[5:]), 1) - timedelta(days=8)  # a week counted in `keep_from` may end a few days after its first
    files = []
    for y in sorted(y for y in years if first_day.year <= y <= today.year):  # the years the page offers (the archive starts in 2019)
        time.sleep(pause)
        fields = dict(state)
        fields["__EVENTTARGET"], fields[YEAR_FIELD] = YEAR_FIELD, str(y)
        got = [g for g in parse_tree(post(PAGE, fields, tries=TRIES, pause=pause).decode("utf-8", "replace")) if g[0] == str(y)]
        if not got and (y < today.year or today.month > 2):
            raise RuntimeError("the page listed no reports for %d: its layout may have changed" % y)
        files += got
    todo = sorted(((name_day(n), (y, f, n)) for y, f, n in files), key=lambda t: (t[0] or date.min, t[1]))
    todo = [t for t in todo if t[0] is None or t[0] >= first_day]
    if not todo or (not kept and len(todo) < MIN_FILES_ALL):
        raise RuntimeError("the page lists %d weekly reports (expected %s): its layout may have changed" % (len(todo), "%d or more" % MIN_FILES_ALL if not kept else "some"))
    weeks, repeats = {}, []
    for i, (nd, (y, f, n)) in enumerate(todo):
        if i:
            time.sleep(pause)
        title, listings = read_report(get(file_url(y, f, n), max_bytes=MAX_REPORT, tries=TRIES, pause=pause), to_text)
        end = resolve_end(title, nd)
        if end in weeks:
            repeats.append(end)  # two files for one week: the first stands
            continue
        weeks[end] = listings
    ends = sorted(weeks)
    newest = ends[-1]
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest weekly report is for the week ending %s: the archive looks stale" % newest.isoformat())
    missing, d = [], ends[0]  # the Fridays between the first report and the newest that no report is for
    while d <= newest:
        if d not in weeks:
            missing.append(d)
        d += timedelta(days=7)
    if len(missing) > MAX_MISSING or len(repeats) > MAX_MISSING:
        raise RuntimeError("%d weeks have no report and %d have two: the archive's layout may have changed" % (len(missing), len(repeats)))
    rows = [(week_day(end), L) for end in ends if C.month_of(week_day(end)) >= keep_from for L in weeks[end]]
    if len(rows) < (MIN_LISTINGS_WINDOW if kept else MIN_LISTINGS_ALL):
        raise RuntimeError("only %d listings in all (expected %d or more): the reports may be cut short" % (len(rows), MIN_LISTINGS_WINDOW if kept else MIN_LISTINGS_ALL))
    unread = sum(1 for _, L in rows if L["county"] is None)
    if unread > max(MAX_UNREAD, 0.03 * len(rows)):
        raise RuntimeError("%d of %d listings have no readable county: the layout may have changed" % (unread, len(rows)))
    t = C.Tally(STATE, bands=BANDS_TOLD)
    for ym, counts in sorted(kept.items()):
        for b, n in counts.items():
            if isinstance(n, int) and n > 0:
                t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    for day, L in rows:
        t.add(day, L["band"], county=L["county"], operator=L["operator"])
    note = ("Every Form 2 drilling permit on the Commission's weekly reports (North and South Arkansas). A report names a week, not a day, so each week is counted in the month that holds most of its days. "
            "A report prints a purpose under a permit that is not an original application (renewal, amend or re-entry): a permit with none is counted as new, a renewal or amendment as an amendment, a re-entry as a re-entry. "
            "The list gives no well type, so disposal, brine-supply and carbon-storage wells are among the new ones, and no injection or rework band and no fluid can be told. "
            "A few permits are listed again with no purpose printed and are counted as listed. The permit-by-permit record starts with the report for the week ending January 4, 2019.")
    # the months before the window are not read again, so the weeks the first full read found missing there are carried (the note must not change as weeks leave the window)
    missing = sorted(set(missing) | {d for d in KNOWN_MISSING if kept and d < first_day})
    if missing:
        note += " Weeks with no report in the Commission's archive, so a month that holds one may be short: %s." % dates_text(missing)
    if repeats:
        note += " The archive holds two files for the week ending %s: the first is read." % dates_text(repeats)
    doc = t.document(agency="Arkansas Oil and Gas Commission", source_name="Permit and Completion Reports (one workbook a week)", source_url=PAGE, basis="week of issue (the weekly report of Form 2 permits)",
                     cadence="weekly (a report for each week ending Friday)", measure="permits", asof=newest, first=FIRST, unit="drilling permits", note=note)
    C.log("%s: %d weekly reports read%s, %d listings counted (%s), %d with no readable county, %d weeks with no report"
          % (STATE, len(weeks), " (months before %s are the committed file's)" % keep_from if kept else " (all of them)", len(rows),
             ", ".join("%d %s" % (sum(1 for _, L in rows if L["band"] == b), b) for b in BANDS_TOLD), unread, len(missing)))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
