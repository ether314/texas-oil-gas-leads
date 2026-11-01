#!/usr/bin/env python3
"""D11: Arkansas's drilling permits (Arkansas Oil and Gas Commission, AOGC), for the National report of the Oil tracker.

The Commission publishes one report every week, "Permit and Completion Reports" (https://dataexplorer.aogc.arkansas.gov/data/completion.aspx: a year to choose, then a folder for each month, then one file a
week, named for the Friday the week ends). Each report lists, for North and for South Arkansas, the drilling permits (Form 2) the Commission issued that week, the well completions (Form 3), the
recompletions and workovers (Form 3), and the applications to plug and plugging reports (Forms 11 and 12). Its title line says "Permits Issued During Week Ending: <date>". From 2020-07 the reports are
Excel workbooks, 2019 to mid-2020 PDFs. The page is an ASP.NET form (its year list is a postback that returns the whole tree of months and files), but every file has a plain static address, so this
reads the page, asks for the years it needs, and fetches each report by its address. The map layer of the Commission's wells (GeoStor) is NOT used: its newest permit is from 2025 and it carries no permit date.

What it counts, and what it cannot tell (NOTES_D11.md has the fuller account):

  - `measure` "permits", `basis` the week of issue: a report names only the week, not the day, so each week is counted in the month that holds most of its days (its Wednesday), as West Virginia's is;
  - `new` is every Form 2 drilling permit on the lists, which is what the Commission publishes and no more: the list has no purpose (original, amendment, renewal, re-entry) and no well type, so
    disposal, brine-supply and carbon-storage wells (a few a year) and a permit approved long after its number was assigned are in it, and no other band can be told: they are null, never zero;
    `unit` says "drilling permits". No fluid is recorded either (`fluid` is null);
  - a week with no permit says NONE in both sections, so a quiet month is a real zero; a week the Commission did not post (a few a year) is not a zero: the months it falls in may be short, and the note says
    which weeks are missing;
  - Arkansas is small: about 30 to 60 drilling permits a year, so a month holds 0 to 8.

Nothing leaves a report but the county and the operator's name (published only if it is a corporation, LLC or partnership: the naming rule): no permit or API number, well or lease name, address,
location or contractor is kept. The reports are untrusted data: a workbook is read as XML with its sizes checked, a PDF only through `pdftotext -layout` in a new folder; requests identify no person and
are 3 seconds apart.

A full read is about 350 files (about 25 minutes). When a committed nat/AR.json exists, months older than the last 14 are taken from it and only the weeks of the last 14 months (about 60 files) are read
again, as the other weekly producers do (a report can be corrected after release); delete the committed file to read everything.

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
FIRST = "2019-01"
PAUSE = 3.0
REREAD = 14  # months read again each run when a committed file exists
MAX_PAGE = 3_000_000
MAX_REPORT = 3_000_000  # a weekly report is 25 to 200 KB
MAX_UNZIPPED = 20_000_000
MIN_FILES_ALL = 300  # reports since 2019 (about 350 in October 2026)
MIN_PERMITS_ALL = 150  # a full read (about 250 permits since 2019 when written)
MIN_PERMITS_WINDOW = 10  # the REREAD window alone
STALE_DAYS = 45  # the newest report may not be older than this
MAX_MISSING = 12  # weeks without a report a run may meet (the archive skips a few each year)
MAX_UNREAD = 3  # permits a run may count without a readable county (or 2 percent of them)
COUNTIES = frozenset(c.upper() for c in (
    "Arkansas Ashley Baxter Benton Boone Bradley Calhoun Carroll Chicot Clark Clay Cleburne Cleveland Columbia Conway Craighead Crawford Crittenden Cross Dallas Desha Drew Faulkner Franklin Fulton Garland "
    "Grant Greene Hempstead|Hot_Spring Howard Independence Izard Jackson Jefferson Johnson Lafayette Lawrence Lee Lincoln Little_River Logan Lonoke Madison Marion Miller Mississippi Monroe Montgomery "
    "Nevada Newton Ouachita Perry Phillips Pike Poinsett Polk Pope Prairie Pulaski Randolph St._Francis Saline Scott Searcy Sebastian Sevier Sharp Stone Union Van_Buren Washington White Woodruff Yell"
).replace("|", " ").replace("_", "\x00").split())
COUNTIES = frozenset(c.replace("\x00", " ") for c in COUNTIES)
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


# ------------------------------------------------------------------------------------------------ one weekly report -> its Form 2 permits

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
    m = TITLE.search(text)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def clean_operator(name):
    """The operator's name as one spelling: trailing periods and a second comma gone, so "Quanico Oil & Gas, Inc." and "Quanico Oil & Gas, Inc" are one operator."""
    n = " ".join((name or "").replace(".,", ",").split())
    return re.sub(r"[.\s]+$", "", n)


def county_of(text):
    c = " ".join((text or "").replace(".", ". ").split()).upper().replace(". ", ".").replace("ST.FRANCIS", "ST. FRANCIS")
    return c.title() if c in COUNTIES else None


def week_from_rows(rows):
    """(week end, permits) from the cells of one weekly workbook. A permit is {'county': name or None, 'operator': name or '', 'no': permit number (used to count a permit once, never kept)}. The report must have all
    eight section headings, and each of its two Form 2 sections must list permits or say NONE: anything else is a layout this does not know."""
    title = next((r[1] for r in rows if 1 in r and TITLE.search(r[1])), None)
    end = week_end_of(title or "")
    if end is None:
        raise RuntimeError("a weekly report has no 'Week Ending' title")
    headings, sec, cur, saw_none, out = [], None, None, {}, []
    for r in rows:
        a = r.get(1, "")
        h = HEADING.match(a)
        if h:
            kind = re.sub(r"\s+", " ", h.group(2).upper())
            headings.append((h.group(1).upper(), kind))
            sec = h.group(1).upper() if kind == "DRILLING PERMITS" else None
            cur = None
            saw_none.setdefault(sec, False) if sec else None
            continue
        if sec is None or not r or a == "Permit Number":
            continue
        if a.upper() == "NONE":
            saw_none[sec] = True
            cur = None
        elif PERMIT_NO.match(a):
            cur = {"no": a.split(".")[0], "rows": []}
            out.append(cur)
        elif cur is not None:
            cur["rows"].append(r)
    if len(headings) != 8 or len(set(headings)) != 8:
        raise RuntimeError("a weekly report for %s has %d of the 8 sections" % (end.isoformat(), len(set(headings))))
    permits = []
    for blk in out:
        first = blk["rows"][0] if blk["rows"] else {}
        permits.append({"no": blk["no"], "operator": clean_operator(first.get(2, "")) if not re.search(r"\d{3,}", first.get(2, "")) else "", "county": county_of(first.get(4, ""))})
    for sec in ("NORTH", "SOUTH"):
        have = any(p for p in out) and False
    return end, permits


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
