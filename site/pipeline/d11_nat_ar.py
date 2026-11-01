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
        if len(r) == 1 and next(iter(r.values())).upper() in QUIET:
            none[sec], cur = True, None
        elif PERMIT_NO.match(a):
            found[sec] = True
            cur = {"no": a.split(".")[0], "api": r.get(2, ""), "top": r.get(4, ""), "rows": []}
            blocks.append(cur)
        elif cur is not None:
            cur["rows"].append(r)
    check_sections(end, headings, none, found)
    out = []
    for b in blocks:
        first = b["rows"][0] if b["rows"] else {}
        out.append({"id": well_id(b["api"], b["no"]), "operator": clean_operator(first.get(2, "")), "county": county_of(first.get(4, "")) or county_of(b["top"])})  # the field and the county sit one above the other, and once in the other order
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


def read_report(data, to_text=pdf_to_text):
    """(week end, listings) of one report by what the file is (a workbook is a zip, a PDF starts with %PDF), whatever its name says."""
    if data[:4] == b"PK\x03\x04":
        return week_from_rows(sheet_rows(data))
    if data[:5] == b"%PDF-":
        return week_from_text(to_text(data))
    raise RuntimeError("a weekly report is neither a workbook nor a PDF")


# ------------------------------------------------------------------------------------------------ the run

def previous(keep_from, path=None):
    """The committed nat/AR.json when it can stand for the months before `keep_from` ({month: {band: count}}); {} when there is none or it does not cover them."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        ok = d.get("state") == STATE and months[0] == FIRST and months == C.month_list(months[0], months[-1]) and months[-1] >= C.add_months(keep_from, -1)
        ok = ok and all(isinstance(bands[b], list) and len(bands[b]) == len(months) for b in ("new", "amend"))
        return {ym: {b: bands[b][i] for b in ("new", "amend")} for i, ym in enumerate(months) if ym < keep_from} if ok else {}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def nearest_friday(d):
    """The Friday a report's date stands for: the date itself when it is a Friday, else the nearest one (a title was once a Monday, three days after the Friday its file is named for)."""
    return min((d + timedelta(days=k) for k in range(-3, 4) if (d + timedelta(days=k)).weekday() == 4), key=lambda x: (abs((x - d).days), x))


def week_month(end):
    """The month a week is counted in: the one that holds most of its days (its Wednesday)."""
    return C.month_of(end - timedelta(days=2))


def build(get=C.polite_get, post=polite_post, to_text=pdf_to_text, pause=PAUSE, today=None, old=None):
    today = today or date.today()
    page = get(PAGE, max_bytes=MAX_PAGE).decode("utf-8", "replace")
    years, state = year_options(page), hidden_fields(page)
    if not state.get("__VIEWSTATE") or not state.get("__EVENTVALIDATION") or today.year not in years or 2019 not in years:
        raise RuntimeError("the reports page has no year list or form state it needs (years %s): its layout may have changed" % (years,))
    keep_from = C.add_months(C.month_of(today), -REREAD)
    kept = (previous(keep_from) if old is None else old) if keep_from > FIRST else {}
    if not kept:
        keep_from = FIRST
    read_from = max(FIRST, C.add_months(keep_from, -LOOKBACK))
    first_day = date(int(read_from[:4]), int(read_from[5:]), 1) - timedelta(days=8)  # a week counted in `read_from` may end a few days after its first
    files = []
    for y in range(first_day.year, today.year + 1):
        time.sleep(pause)
        fields = dict(state)
        fields["__EVENTTARGET"], fields[YEAR_FIELD] = YEAR_FIELD, str(y)
        got = parse_tree(post(PAGE, fields).decode("utf-8", "replace"))
        if not got and y < today.year:
            raise RuntimeError("the page listed no reports for %d: its layout may have changed" % y)
        files += [g for g in got if g[0] == str(y)]
    todo = sorted(((name_day(n), (y, f, n)) for y, f, n in files), key=lambda t: (t[0] or date.min, t[1]))
    todo = [t for t in todo if t[0] is None or t[0] >= first_day]
    if not todo or (kept == {} and len(todo) < MIN_FILES_ALL):
        raise RuntimeError("the page lists %d weekly reports (expected %s): its layout may have changed" % (len(todo), "%d or more" % MIN_FILES_ALL if not kept else "some"))
    weeks, repeats = {}, []
    for i, (nd, (y, f, n)) in enumerate(todo):
        if i:
            time.sleep(pause)
        end, listings = read_report(get(file_url(y, f, n), max_bytes=MAX_REPORT), to_text)
        if end in weeks:
            repeats.append(end)  # two files for one week: the first stands
            continue
        weeks[end] = listings
    ends = sorted(weeks)
    newest = ends[-1]
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest weekly report is for the week ending %s: the archive looks stale" % newest.isoformat())
    # weeks with no report: every Friday between the first and the newest that no report claims (a report's title may be a day or two off a Friday: it claims the Friday nearest to it)
    claimed = {nearest_friday(end) for end in ends}
    missing, d = [], ends[0]
    d += timedelta(days=(4 - d.weekday()) % 7)
    while d <= newest:
        if d not in claimed:
            missing.append(d)
        d += timedelta(days=7)
    if len(missing) > MAX_MISSING or len(repeats) > MAX_MISSING:
        raise RuntimeError("%d weeks have no report and %d have two: the archive's layout may have changed" % (len(missing), len(repeats)))
    seen, new_n, amend_n, unread, rows = set(), 0, 0, 0, []
    for end in ends:
        ym = week_month(end)
        counted = ym >= keep_from
        here = set()
        for L in weeks[end]:
            if L["id"] in here:
                continue  # a well listed twice in one report counts once
            here.add(L["id"])
            band = "amend" if L["id"] in seen else "new"
            if counted and ym >= FIRST:
                rows.append((end - timedelta(days=2), band, L["county"], L["operator"]))
                unread += L["county"] is None
        seen |= here
    if len(rows) < (MIN_LISTINGS_WINDOW if kept else MIN_LISTINGS_ALL):
        raise RuntimeError("only %d listings in all (expected %d or more): the reports may be cut short" % (len(rows), MIN_LISTINGS_WINDOW if kept else MIN_LISTINGS_ALL))
    if unread > max(MAX_UNREAD, 0.03 * len(rows)):
        raise RuntimeError("%d of %d listings have no readable county: the layout may have changed" % (unread, len(rows)))
    t = C.Tally(STATE, bands=("new", "amend"))
    for ym, counts in sorted(kept.items()):
        for b, n in counts.items():
            if isinstance(n, int) and n > 0:
                t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    for day, band, county, operator in rows:
        t.add(day, band, county=county, operator=operator)
    note = ("Every Form 2 drilling permit on the Commission's weekly reports (North and South Arkansas). A report names a week, not a day, so each week is counted in the month that holds most of its days. "
            "The Commission lists a permit again when it renews or amends it, without saying which: the first listing of a well is counted as new and every later one as an amendment or renewal. "
            "The list gives no well type, so disposal, brine-supply and carbon-storage wells are among the new ones, and no other kind of permit and no fluid can be told. "
            "The permit-by-permit record starts with the report for the week ending January 4, 2019. "
            "A renewal of a permit first listed before the months a run reads (8 months before the 14 it counts) is counted as new.")
    known = [d for d in missing if d in KNOWN_MISSING]
    other = [d for d in missing if d not in KNOWN_MISSING]
    if known or other:
        note += " Weeks with no report in the Commission's archive, so a month that holds one may be short: %s." % ", ".join("%s %d, %d" % (calendar.month_name[d.month], d.day, d.year) for d in sorted(set(known + other)))
    if repeats:
        note += " The archive holds two files for the week ending %s: the first is read." % ", ".join("%s %d, %d" % (calendar.month_name[d.month], d.day, d.year) for d in sorted(set(repeats)))
    doc = t.document(agency="Arkansas Oil and Gas Commission", source_name="Permit and Completion Reports (one workbook a week)", source_url=PAGE, basis="week of issue (the weekly report of Form 2 permits)",
                     cadence="weekly (a report for each week ending Friday)", measure="permits", asof=newest, first=FIRST, unit="drilling permits", note=note)
    C.log("%s: %d weekly reports read%s, %d listings counted (%d new, %d renewals or amendments), %d with no readable county, %d weeks with no report"
          % (STATE, len(weeks), " (months before %s are the committed file's)" % keep_from if kept else " (all of them)", len(rows), sum(1 for r in rows if r[1] == "new"), sum(1 for r in rows if r[1] == "amend"), unread, len(missing)))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
