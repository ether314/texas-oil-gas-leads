#!/usr/bin/env python3
"""D11: Arkansas's drilling permits (Arkansas Oil and Gas Commission, AOGC), for the National report of the Oil tracker.

The Commission publishes one report every week, "Permit and Completion Reports" (https://dataexplorer.aogc.arkansas.gov/data/completion.aspx: a year to choose, a folder for each month, then one file a
week, named for the Friday the week ends). Each report lists, for North and for South Arkansas, the drilling permits (Form 2) the Commission issued that week, the well completions (Form 3), the
recompletions and workovers (Form 3), and the applications to plug and plugging reports (Forms 11 and 12), under the title "Permits Issued During Week Ending: <date>". The reports are Excel workbooks from
mid-2020 and PDFs before. The page is an ASP.NET form (choosing a year is a postback that returns the whole tree of months and files), but every file has a plain static address, so this reads the page,
asks for the years it needs, and fetches each report by its address. The Commission's well layer on GeoStor is NOT used: its newest permit is from 2025 and it carries no permit date.

What it counts, and what it cannot tell (NOTES_D11.md has the fuller account):

  - `measure` "permits", `basis` the week of issue: a report names the week, not the day, so each week is counted in the month that holds most of its days (its Wednesday), as West Virginia's is;
  - a Form 2 listing is `new` the first time a well is listed and `amend` every later time: the Commission re-lists a permit when it renews or amends it (the same well, the same permit, six months or a year on),
    and the list does not label which is which. A well is told by its API number (read, compared in memory, never kept). A renewal of a permit first listed before what a run reads is counted as new (a
    weekly run reads 8 months before the months it counts; the first read starts in January 2019). No other band can be told: the list has no well type, so disposal, brine-supply and carbon-storage wells
    (a few a year) are in `new`, and `inj`, `redrill`, `rework` and `other` are null, never zero; there is no fluid either (`fluid` is null);
  - a week with no permit says NONE in both Form 2 sections, so a quiet month is a real zero; a week the Commission did not post (5 of about 400 since 2019) is not a zero: the month it falls in may be short,
    and the note says which weeks;
  - Arkansas is small: about 30 to 50 first listings a year, so a month holds 0 to 8.

Nothing leaves a report but the county and the operator's name (published only if it is a corporation, LLC or partnership: the naming rule): no permit or API number, well or lease name, address, location or
contractor is kept. The reports are untrusted data: a workbook is read as XML after its sizes are checked, a PDF only through `pdftotext -layout` in a new folder; requests identify no person and are 3 seconds apart.

A full read is about 400 files (30 minutes). When a committed nat/AR.json exists, months older than the last 14 are taken from it and only the weeks since 22 months ago are read (about 95 files: 8 months
to tell a renewal, 14 to count, since a report may be corrected after release); delete the committed file to read everything.

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
LOOKBACK = 8  # months read before those, only to tell a listing that repeats a well already listed
MAX_PAGE = 3_000_000
MAX_REPORT = 3_000_000  # a weekly report is 25 to 200 KB
MAX_UNZIPPED = 20_000_000
MIN_FILES_ALL = 300  # reports since 2019 (about 400 in October 2026)
MIN_LISTINGS_ALL = 100  # a full read
MIN_LISTINGS_WINDOW = 8  # the months counted by a weekly run (about 40 a year)
STALE_DAYS = 45  # the newest report may not be older than this
MAX_MISSING = 10  # weeks without a report a run may meet (5 since 2019)
MAX_UNREAD = 3  # listings a run may count without a readable county (or 3 percent of them)
KNOWN_MISSING = frozenset({date(2019, 11, 29), date(2024, 1, 19), date(2024, 10, 4), date(2026, 1, 30), date(2026, 5, 8)})  # Fridays with no report in the archive when written
COUNTIES = frozenset(n.upper() for n in (
    "Arkansas", "Ashley", "Baxter", "Benton", "Boone", "Bradley", "Calhoun", "Carroll", "Chicot", "Clark", "Clay", "Cleburne", "Cleveland", "Columbia", "Conway", "Craighead",
    "Crawford", "Crittenden", "Cross", "Dallas", "Desha", "Drew", "Faulkner", "Franklin", "Fulton", "Garland", "Grant", "Greene", "Hempstead", "Hot Spring", "Howard",
    "Independence", "Izard", "Jackson", "Jefferson", "Johnson", "Lafayette", "Lawrence", "Lee", "Lincoln", "Little River", "Logan", "Lonoke", "Madison", "Marion", "Miller",
    "Mississippi", "Monroe", "Montgomery", "Nevada", "Newton", "Ouachita", "Perry", "Phillips", "Pike", "Poinsett", "Polk", "Pope", "Prairie", "Pulaski", "Randolph",
    "St. Francis", "Saline", "Scott", "Searcy", "Sebastian", "Sevier", "Sharp", "Stone", "Union", "Van Buren", "Washington", "White", "Woodruff", "Yell"))
HEADING = re.compile(r"^\s*(NORTH|SOUTH)\s+ARKANSAS\s+(DRILLING\s+PERMITS|WELL\s+COMPLETIONS|RECOMPLETIONS|APPLICATION\s+TO\s+PLUG)", re.I)
TITLE = re.compile(r"Week\s+Ending\s*:?\s*([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})")
LEAF = re.compile(r"\*\|\*WIPE\*\|\*(\d{4})\*\|\*(\d\d-[A-Za-z]+)\*\|\*([^'&\\*|]+\.(?:xlsx|xls|pdf))", re.I)
MONTHS = {m.lower(): i + 1 for i, m in enumerate(calendar.month_name[1:])}
PERMIT_NO = re.compile(r"^\d{3,6}(\.0)?$")
NAME_DAY = re.compile(r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{4}|\d{2})")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ------------------------------------------------------------------------------------------------ the page and its postback

def polite_post(url, fields, max_bytes=MAX_PAGE, timeout=90, tries=2, pause=PAUSE):
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
    if not m or m.group(1).lower() not in MONTHS:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def clean_operator(name):
    """The operator's name as one spelling: trailing periods gone, so "Quanico Oil & Gas, Inc." and "Quanico Oil & Gas, Inc" are one operator. A text with digits in it is an address, not a name."""
    n = " ".join((name or "").split())
    return "" if re.search(r"\d{3,}", n) else re.sub(r"[.\s]+$", "", n)


def county_of(text):
    """The county in title case when it is one of Arkansas's 75; None otherwise (a field's name, a typo, a cell that moved)."""
    c = " ".join((text or "").replace(".", ". ").split()).upper().replace(". ", ".").replace("ST.FRANCIS", "ST. FRANCIS")
    c = c.replace("ST.", "ST. ").replace("  ", " ").strip() if c.startswith("ST.") else c
    return C.place_title(c) if c in COUNTIES else None


def well_id(api, permit):
    """What tells one well from another, for this run only (never written): the API number's digits, the county code padded ("03 27 12164" is "03 027 12164"), else the permit number."""
    groups = re.findall(r"\d+", api or "")
    if len(groups) == 3 and len(groups[0]) == 2 and len(groups[1]) <= 3 and len(groups[2]) <= 5:
        return groups[0] + groups[1].zfill(3) + groups[2].zfill(5)
    digits = "".join(groups)
    return digits if len(digits) >= 8 else "permit" + (permit or "")


def check_sections(end, headings, none, found):
    """A report must have all eight section headings, and each of its two Form 2 sections must list permits or say NONE."""
    if len(headings) != 8 or len(set(headings)) != 8:
        raise RuntimeError("the weekly report for %s has %d of the 8 sections" % (end.isoformat(), len(set(headings))))
    for sec in ("NORTH", "SOUTH"):
        if not none.get(sec) and not found.get(sec):
            raise RuntimeError("the weekly report for %s has neither permits nor NONE in its %s Arkansas drilling permits" % (end.isoformat(), sec.lower()))


def week_from_rows(rows):
    """(week end, listings) from the cells of one weekly workbook. A listing is {'id', 'operator', 'county'}: the Form 2 drilling permits of North and South Arkansas, one for each permit number, in the
    order of the report. A permit is its first row (permit number, API number, well name, field) and the rows under it (operator and county are in the first of them)."""
    end = week_end_of(next((r[1] for r in rows if 1 in r and TITLE.search(r[1])), ""))
    if end is None:
        raise RuntimeError("a weekly report has no 'Week Ending' title")
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
        if a.upper() == "NONE":
            none[sec], cur = True, None
        elif PERMIT_NO.match(a):
            found[sec] = True
            cur = {"no": a.split(".")[0], "api": r.get(2, ""), "rows": []}
            blocks.append(cur)
        elif cur is not None:
            cur["rows"].append(r)
    check_sections(end, headings, none, found)
    out = []
    for b in blocks:
        first = b["rows"][0] if b["rows"] else {}
        out.append({"id": well_id(b["api"], b["no"]), "operator": clean_operator(first.get(2, "")), "county": county_of(first.get(4, ""))})
    return end, out


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
