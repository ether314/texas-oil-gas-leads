"""Tests for site/pipeline/d11_nat_ar.py: Arkansas's drilling permits, from the Oil and Gas Commission's weekly "Permit and Completion Reports".

The fixtures are invented, shaped like the real source: a report page with a year list and the ASP.NET state of its form, a tree of months and files for a chosen year (postback links whose argument ends
with `WIPE|<year>|<month folder>|<file>`, folders, "No documents available"), and one report for every Friday from 2019-01-04 to 2026-10-23: a workbook from mid-2020 (cells in columns, a permit being a
first row of permit number, API number, well name and field, then rows with the purpose words in column 1, the operator and county in column 2 and 4, an address, a latitude, a contractor and a start
date) and, before that, a PDF whose text is what `pdftotext -layout` gives. Both are written from one generator that also keeps the truth. They pin: the tree and the static address of each file; the week
(a title typed with mistakes, a title a Monday, a file name for another Friday); the Form 2 sections only (decoy permits in the recompletion and plugging sections are never counted); NONE, and the
Commission's typed DONE; a report missing one heading, and one missing a Form 2 section's NONE; the purpose words (none is a new well, renewal and amend are amendments, re-entry is a re-entry, a word it
does not know is `other`, two words on a permit); the county from the API number's county place (a hyphenated number, a county code without its zero, a malformed number falling back to the printed
county, the field and county cells swapped); that only the county, the operator (named only if the rule allows) and the purpose leave a report; the month of a week by its Wednesday; the series
counts, the last 12 months' counties and operators against the truth; the null bands and fluid; an incremental read (the committed months stand and only the last 14 months are fetched, giving the same
document); and that anything damaged (a refusal, a stale archive, a page without its year list, a year with no files, an HTML page for a report, too many weeks missing, unreadable counties) fails the run
instead of writing a short file. The network and pdftotext are faked.

Run: python3 -I tests/test_d11_ar.py"""
import calendar
import collections
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_ar as AR  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, *exc):
    try:
        fn()
    except exc or (Exception,) as e:
        return str(e) or e.__class__.__name__
    return None


# ------------------------------------------------------------------------------------------------ the workbook, as the Commission writes it
def col_letter(n):
    return chr(64 + n)


def xlsx_bytes(rows, numbers=()):
    """A real .xlsx (a zip of XML) holding `rows`, a list of {column number: text}; shared strings, and the texts listed in `numbers` as numeric cells (a permit number is one in some reports)."""
    shared, out = [], []
    for i, r in enumerate(rows, 1):
        cells = []
        for c in sorted(r):
            ref = "%s%d" % (col_letter(c), i)
            if r[c] in numbers:
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, r[c]))
            else:
                if r[c] not in shared:
                    shared.append(r[c])
                cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, shared.index(r[c])))
        out.append('<row r="%d">%s</row>' % (i, "".join(cells)) if cells else '<row r="%d"/>' % i)
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    sheet = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(out)
    sst = '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">%s</sst>' % "".join("<si><t>%s</t></si>" % esc(t) for t in shared)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Weekly Permits &amp; Completions" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


NO_ADDR = ["PO Box 1356", "Fort Smith, AR 72902"]
HEAD_ROW = {1: "Permit Number", 2: "API Number", 3: "Well Name and Number", 4: "Field", 5: "Proposed Depth", 6: "Anticipated Zone of Completion"}


def title_text(friday, style=0):
    mon = calendar.month_name[friday.month]
    return ["Permits Issued During Week Ending: %s %d, %d" % (mon, friday.day, friday.year),
            "Permits Issued During Week Ending: %s%d, %d" % (mon, friday.day, friday.year),           # May13, 2022
            "Permits Issued During Week Ending: %sey %d, %d" % (mon[:-1], friday.day, friday.year)][style % 3]  # a misspelled month


def block_rows(p, layout="std"):
    """The rows of one permit in a workbook. `p`: no, api, name, field, county, operator, labels."""
    labels = list(p.get("labels", []))
    first = {1: p["no"], 2: p["api"], 3: p["name"], 4: p["field"], 5: "TVD: 4600'", 6: "Lower Carpenter"}
    op = {1: labels.pop(0)} if labels else {}
    op.update({2: p["operator"], 3: "SHL: 2425' FNL & 660' FEL", 4: p["county"], 5: "MD: 4600'"})
    rows = [first, op]
    if layout == "shifted":  # the first row holds only the permit number and the API number; the rest is one row lower
        first = {1: p["no"], 2: p["api"]}
        op = {1: labels.pop(0)} if p.get("labels") and False else {}
        rows = [first, {2: p["operator"], 3: p["name"], 4: p["field"], 5: "TVD: 4600'"}, {3: "SHL: 100' FNL & 660' FEL", 4: p["county"]}]
        if p.get("labels"):
            rows[1][1] = p["labels"][0]
            for lab in p["labels"][1:]:
                rows.append({1: lab})
        labels = []
    if layout == "swapped":  # the field and the county sit the other way round
        op[4] = p["field"]
        first[4] = p["county"]
    for lab in labels:
        rows.append({1: lab})
    rows += [{2: NO_ADDR[0], 3: "20-7N-27W"}, {2: NO_ADDR[1], 3: "Latitude: N 35.264931º"}, {2: "Sewell Drilling", 3: "Longitude: W -93.886068º"}, {2: "5/1/2026"}, {}]
    return rows


def week_rows(friday, permits, style=0, none_word="NONE", drop=(), decoy=True, layout=None):
    """All the rows of one weekly workbook. `permits`: dicts with sec ('NORTH' or 'SOUTH') and the fields of block_rows; `drop` names headings to leave out (as ('NORTH', 'APPLICATION TO PLUG'))."""
    rows = [{1: " ARKANSAS OIL AND GAS COMMISSION"}, {2: "P. O. BOX 11510", 5: "3309 PHOENIX AVENUE"}, {2: "EL DORADO, ARKANSAS", 5: "FORT SMITH, ARKANSAS"}, {2: "71730", 5: "72903"}, {}, {}, {},
            {1: title_text(friday, style)}, {}]
    for side in ("NORTH", "SOUTH"):
        for kind in ("DRILLING PERMITS (FORM 2)", "WELL COMPLETIONS (FORM 3)", "RECOMPLETIONS  and  WORKOVERS (FORM 3)", "APPLICATION TO PLUG (AOGC FORM 11) AND PLUGGING REPORT (AOGC FORM 12)"):
            key = kind.split(" (")[0].split("  ")[0]
            if (side, key) in drop:
                continue
            rows.append({1: "%s ARKANSAS %s" % (side, kind)})
            rows.append(dict(HEAD_ROW))
            rows.append({})
            mine = [p for p in permits if p["sec"] == side] if kind.startswith("DRILLING") else []
            if mine:
                for p in mine:
                    rows += block_rows(p, layout or p.get("layout", "std"))
            elif kind.startswith("RECOMPLETIONS") and decoy:
                # a recompletion that looks like a permit: it must never be counted as one
                rows += [{1: "40861", 2: "03 145 10409", 3: "Decoy 1", 4: "B-43", 5: "TD: 7570'", 6: "Fayetteville", 8: "46262"}, {1: "renewal", 2: "Decoy Oil Corporation", 4: "White", 8: "Workover"}, {}]
            else:
                rows.append({2: none_word} if none_word == "DONE" else {1: none_word})
            rows.append({})
    return rows


# ------------------------------------------------------------------------------------------------ the PDF, as pdftotext -layout gives it
def week_text(friday, permits, drop=(), noise=True):
    mon = calendar.month_name[friday.month]
    out = ["                                            ARKANSAS OIL AND GAS COMMISSION", "", "                    P. O. BOX 11510                              3309 PHOENIX AVENUE", "",
           "                                    Permits Issued During Week Ending: %s %d, %d" % (mon, friday.day, friday.year), ""]
    for side in ("NORTH", "SOUTH"):
        for kind in ("DRILLING PERMITS (FORM 2)", "WELL COMPLETIONS (FORM 3)", "RECOMPLETIONS and WORKOVERS (FORM 3)", "APPLICATION TO PLUG (AOGC FORM 11) AND PLUGGING REPORT (AOGC FORM 12)"):
            if (side, kind.split(" (")[0].split(" and ")[0]) in drop:
                continue
            out += ["                                       %s ARKANSAS %s" % (side, kind), "Permit API Number                    Well Name and Number      Field      Proposed    Anticipated Zone",
                    "Number Operator                      Location                  County     Depth       of Completion", "       Address                       Latitude", "       Contractor                    Longitude",
                    "       Start Date", ""]
            mine = [p for p in permits if p["sec"] == side] if kind.startswith("DRILLING") else []
            if mine:
                for k, p in enumerate(mine):
                    labs = list(p.get("labels", []))
                    l1 = "%-7s %-31s %-25s %-10s %s" % (p["no"], p["api"].replace(" ", "-") if p.get("hyphen") else p["api"], p["name"], p["field"], "TVD: 3734'  Fayetteville")
                    if labs:
                        l2 = "%-7s %-31s %-25s %-10s %s" % (labs.pop(0), p["operator"], "SHL: 1913' FNL & 2458' FEL", p["county"], "MD: 11,753'")
                    else:
                        l2 = "        %-31s %-25s %-10s %s" % (p["operator"], "SHL: 1913' FNL & 2458' FEL", p["county"], "MD: 11,753'")
                    lines = [l1, l2]
                    for lab in labs:
                        lines.append("%-7s %-31s %s" % (lab, NO_ADDR[0], "11-9N-7W"))
                    lines += ["        %-31s %s" % (NO_ADDR[1], "Latitude: N 35.424187º"), "        %-31s %s" % ("Sewell Drilling", "Longitude: W -91.718477º"), "        TBD", ""]
                    out += lines
                    if noise and k == 0 and len(mine) > 1:  # a page break inside the section: a page number and the column heads again
                        out += ["                                                    1", "Permit API Number                    Well Name and Number      Field      Proposed    Anticipated Zone",
                                "Number Operator                      Location                  County     Depth       of Completion", ""]
            elif kind.startswith("RECOMPLETIONS"):
                out += ["40861   03 145 10409                    Decoy 1                   B-43       TD: 7570'   Fayetteville   194   6/25/2019", "renewal Decoy Oil Corporation           SHL: 555' FSL & 245' FEL  White", ""]
            else:
                out += ["NONE", ""]
    return "\n".join(out)


def pdf_bytes(text):
    return b"%PDF-1.5\n%fake\n" + text.encode("utf-8")


def fake_to_text(data):
    if not data.startswith(b"%PDF-1.5\n%fake\n"):
        raise RuntimeError("pdftotext could not read a report")
    return data[len(b"%PDF-1.5\n%fake\n"):].decode("utf-8")


# ------------------------------------------------------------------------------------------------ the world: a permit generator with its own truth
CODES = {"Union": "139", "Columbia": "027", "Logan": "083", "Ouachita": "103", "Lafayette": "073", "White": "145", "Cleburne": "023", "Sevier": "133", "Van Buren": "141", "Miller": "091"}
OPERATORS = ["Quanico Oil & Gas, Inc.", "Flywheel Energy Development, LLC", "Betsy Production Company, Inc.", "Hanna Oil and Gas Company", "Lapis Carbon Solutions (AR Development) LP",
             "Smith, Jerry Production", "Dan Reynolds Company"]  # the last two are a person's business: counted, never named
MISSING = set(AR.KNOWN_MISSING)  # the five Fridays the real archive lacks: a full read must find exactly them, and a weekly run carries the ones before its window
FRIDAYS = []
d = date(2019, 1, 4)
while d <= date(2026, 10, 23):
    FRIDAYS.append(d)
    d += timedelta(days=7)


def world_permits(k, friday):
    """What the fake Commission issues in week k (the truth): dicts with sec, no, api, name, field, county, operator, labels, band, layout."""
    P = []
    if k % 3 == 1 or date(2022, 2, 4) <= friday <= date(2022, 3, 4):
        return P  # a quiet week (and all of February 2022): both Form 2 sections say NONE
    n = 0
    for j in range(1 + (k % 4 == 0) + (k % 9 == 0)):
        county = ["Union", "Columbia", "Logan", "Ouachita", "Lafayette", "White", "Cleburne", "Sevier"][(k + j) % 8]
        labels = [] if (k + j) % 5 else (["renewal"] if (k + j) % 2 else ["renewal", "amend"])
        band = "amend" if labels else "new"
        if (k + j) % 11 == 3:
            labels, band = ["re-entry"], "redrill"
        if (k + j) % 23 == 5:
            labels, band = ["workover pending"], "other"
        P.append({"sec": "NORTH" if county in ("Logan", "White", "Cleburne") else "SOUTH", "no": str(48000 + k * 3 + j), "api": "03 %s %05d" % (CODES[county], 10000 + k * 7 + j), "name": "Well %d-%d" % (k, j),
                  "field": "Field %d" % (k % 5), "county": county, "operator": OPERATORS[(k * 5 + j) % len(OPERATORS)], "labels": labels, "band": band,
                  "layout": "shifted" if (k + j) % 17 == 0 else "swapped" if (k + j) % 19 == 0 else "std", "hyphen": (k + j) % 13 == 0})
        n += 1
    return P


WORLD = {f: world_permits(k, f) for k, f in enumerate(FRIDAYS) if f not in MISSING}
XLSX_FROM = date(2020, 7, 10)


def report_bytes(friday, permits, **kw):
    if friday >= XLSX_FROM:
        return xlsx_bytes(week_rows(friday, permits, style=(friday.toordinal() // 7) % 7 if (friday.toordinal() // 7) % 7 < 3 else 0, **kw), numbers=tuple(p["no"] for p in permits if int(p["no"]) % 2))
    return pdf_bytes(week_text(friday, permits, **{k: v for k, v in kw.items() if k in ("drop",)}))


def file_name(friday):
    ext = "xlsx" if friday >= XLSX_FROM else "pdf"
    return ("WklyRep %d.%d.%s.%s" % (friday.month, friday.day, str(friday.year)[2:], ext)) if friday.day % 2 else ("WklyRep %d-%d-%s.%s" % (friday.month, friday.day, str(friday.year)[2:], ext))


def folder_of(friday):
    return "%02d-%s" % (friday.month, calendar.month_name[friday.month])


PAGE_HTML = """<html><body><form method="post" action="./completion.aspx" id="form1">
<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" /><input type="hidden" name="__EVENTARGUMENT" id="__EVENTARGUMENT" value="" />
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEPDwUKLTU%d" /><input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="/wEdAAd&amp;x" />
<input name="ctl00$ctl00$screenwidth" type="hidden" id="screenwidth" />
<select name="ctl00$ctl00$cpMainContent$ChildContent2$ddlYear" id="cpMainContent_ChildContent2_ddlYear"><option selected="selected" value=""></option>%s</select>
</form></body></html>"""
LEAF = ("<a href=\"javascript:__doPostBack(&#39;ctl00$ctl00$cpMainContent$ChildContent2$TreeView1&#39;,&#39;sF:*|*inetpub*|*wwwroot*|*AOGC*|*Data*|*WIPE*|*%(y)s*|*%(f)s\\\\F:*|*inetpub*|*wwwroot*|*AOGC*|*Data*|*WIPE*|*%(y)s*|*%(f)s*|*%(n)s&#39;)\" "
        "onclick=\"TreeView_SelectNode(x, this,&#39;t1&#39;);\">%(n)s</a>")
FOLDER = "<a href=\"javascript:__doPostBack(&#39;ctl00$ctl00$cpMainContent$ChildContent2$TreeView1&#39;,&#39;sF:*|*inetpub*|*wwwroot*|*AOGC*|*Data*|*WIPE*|*%s*|*%s&#39;)\">%s</a>"
EMPTY = "<a href=\"javascript:__doPostBack(&#39;ctl00$ctl00$cpMainContent$ChildContent2$TreeView1&#39;,&#39;sF:*|*inetpub*|*wwwroot*|*AOGC*|*Data*|*WIPE*|*%s*|*%s\\\\No documents available&#39;)\">No documents available</a>"


def tree_html(year, files):
    """The tree for a year: every month folder, its files (or 'No documents available'). `files`: [(folder, name)]."""
    out = ["<html><body>"]
    for m in range(1, 13):
        folder = "%02d-%s" % (m, calendar.month_name[m])
        out.append(FOLDER % (year, folder, folder))
        mine = [n for f, n in files if f == folder]
        out += [LEAF % {"y": year, "f": folder, "n": n} for n in mine] or [EMPTY % (year, folder)]
    return "".join(out) + "</body></html>"


class Site:
    """The fake server: the page, the postback for a year, and each report by its static address. Counts requests."""

    def __init__(self, world=None, today=TODAY, years=None, page=None, override=None, drop_year=None, extra_files=None):
        self.world = WORLD if world is None else world
        self.today = today
        self.override = override or {}  # friday -> bytes served instead
        self.requests = []
        self.drop_year = drop_year
        self.page = page
        self.years = years
        self.extra = extra_files or {}  # (year, folder, name) -> bytes: more files in the tree
        self.by_url = {}
        self.listing = collections.defaultdict(list)
        for f in self.world:
            if f <= today:
                self.listing[f.year].append((folder_of(f), file_name(f)))
                self.by_url[AR.file_url(str(f.year), folder_of(f), file_name(f))] = f
        for (y, folder, name), data in self.extra.items():
            self.listing[int(y)].append((folder, name))
            self.by_url[AR.file_url(y, folder, name)] = (y, folder, name)

    def get(self, url, max_bytes=0, **kw):
        self.requests.append(url)
        if url == AR.PAGE:
            ys = self.years if self.years is not None else sorted({f.year for f in self.world}, reverse=True)
            return (self.page or PAGE_HTML % (7, "".join('<option value="%d">%d</option>' % (y, y) for y in ys))).encode()
        key = self.by_url.get(url)
        if key is None:
            raise RuntimeError("could not read the source: HTTP 404")
        if isinstance(key, tuple):
            return self.extra[key]
        if key in self.override:
            return self.override[key]
        return report_bytes(key, self.world[key])

    def post(self, url, fields, **kw):
        self.requests.append(url + "#" + fields.get(AR.YEAR_FIELD, ""))
        assert fields.get("__VIEWSTATE") and fields.get("__EVENTVALIDATION") and fields["__EVENTTARGET"] == AR.YEAR_FIELD
        y = int(fields[AR.YEAR_FIELD])
        if y == self.drop_year:
            return tree_html(str(y), []).encode()
        return tree_html(str(y), self.listing.get(y, [])).encode()


def build(site, today=TODAY, old={}, **kw):  # noqa: B006 - {} means "no committed file": the tests never read the repository's nat/AR.json
    return AR.build(get=site.get, post=site.post, to_text=fake_to_text, pause=0, today=today, old=old, **kw)


# ------------------------------------------------------------------------------------------------ the truth, by its own arithmetic
def truth(world, first="2019-01"):
    """{band: {month: count}} with every week put in the month of its Wednesday, and the counties and operators of new permits by month."""
    m = {b: collections.Counter() for b in ("new", "amend", "redrill", "other")}
    cty, ops, unn = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter), collections.Counter()
    for f, ps in world.items():
        wed = f - timedelta(days=2)
        ym = "%04d-%02d" % (wed.year, wed.month)
        for p in ps:
            m[p["band"]][ym] += 1
            if p["band"] == "new":
                cty[ym][p["county"].upper()] += 1
                if C.nameable(p["operator"]):
                    ops[ym][" ".join(p["operator"].upper().replace(",", " ").split()).rstrip(".")] += 1
                else:
                    unn[ym] += 1
    return m, cty, ops, unn


# ================================================================================================ the tests
print("-- the page, the tree and the names")
PAGE = PAGE_HTML % (7, "".join('<option value="%d">%d</option>' % (y, y) for y in (2026, 2025, 2019)))
check(AR.year_options(PAGE) == [2026, 2025, 2019], "the year list gives the years, newest first, without the blank")
check(AR.year_options("<html></html>") == [], "a page with no year list gives none")
hf = AR.hidden_fields(PAGE)
check(hf["__VIEWSTATE"] == "/wEPDwUKLTU7" and hf["__EVENTVALIDATION"] == "/wEdAAd&x" and hf["ctl00$ctl00$screenwidth"] == "" and "ctl00$ctl00$cpMainContent$ChildContent2$ddlYear" not in hf,
      "the hidden inputs are read, with their entities decoded, and the year list is not one of them")
T = tree_html("2026", [("10-October", "WklyRep 10.23.26.xlsx"), ("10-October", "WklyRepo 5.15.26.xlsx"), ("02-February", "WklyRep 2.6.2026.xlsx"), ("01-January", "WklyRep 1-9-26.pdf")])
got = AR.parse_tree(T)
check(("2026", "10-October", "WklyRep 10.23.26.xlsx") in got and ("2026", "02-February", "WklyRep 2.6.2026.xlsx") in got and ("2026", "01-January", "WklyRep 1-9-26.pdf") in got and len(got) == 4,
      "the tree gives each file with its year and month folder (name typos, a pdf, a four-digit year), and no folder or 'No documents available' leaf")
check(AR.parse_tree(T + T) == got, "a file listed twice is one")
check(AR.file_url("2026", "10-October", "WklyRep 10.23.26.xlsx") == "https://dataexplorer.aogc.arkansas.gov/Data/Wipe/2026/10-October/WklyRep%2010.23.26.xlsx", "a file's static address is built from the tree, spaces encoded")
check(AR.parse_tree("<html>nothing</html>") == [], "a page with no tree lists nothing")
check(AR.name_day("WklyRep 10.23.26.xlsx") == date(2026, 10, 23) and AR.name_day("WklyRep 2.6.2026.xlsx") == date(2026, 2, 6) and AR.name_day("WklyRep 1-11-19.pdf") == date(2019, 1, 11)
      and AR.name_day("WklyRepo 5.15.26.xlsx") == date(2026, 5, 15) and AR.name_day("WklyRep 13.45.26.xlsx") is None and AR.name_day("Abbreviations.pdf") is None, "a file name gives its date in every shape it has, and None when it gives none")

print("-- the week")
check(AR.week_end_of("Permits Issued During Week Ending: October 23, 2026") == date(2026, 10, 23), "the title gives the date")
check(AR.week_end_of("Permits Issued During Week Ending: May13, 2022") == date(2022, 5, 13), "a title with no space after the month is read")
check(AR.week_end_of("Permits Issued During Week Ending: Februarey 3, 2023") == date(2023, 2, 3) and AR.week_end_of("Permits Issued During Week Ending: Febua 3, 2023") == date(2023, 2, 3),
      "a misspelled month is told by its first three letters")
check(AR.week_end_of("Permits Issued During Week Ending: Smarch 3, 2023") is None and AR.week_end_of("no title") is None and AR.week_end_of("Week Ending: June 31, 2023") is None, "no date, an impossible date or an unknown month is None")
check(AR.nearest_friday(date(2025, 4, 14)) == date(2025, 4, 11) and AR.nearest_friday(date(2025, 4, 11)) == date(2025, 4, 11) and AR.nearest_friday(date(2025, 4, 16)) == date(2025, 4, 18), "the nearest Friday")
check(AR.resolve_end(date(2025, 4, 14), date(2025, 4, 11)) == date(2025, 4, 11), "a title that is a Monday, three days after the Friday its file is named for, is that Friday")
check(AR.resolve_end(None, date(2019, 1, 25)) == date(2019, 1, 25) and AR.resolve_end(date(2024, 8, 9), None) == date(2024, 8, 9), "the name stands in for a missing title and the title for a missing name")
check(AR.resolve_end(date(2024, 8, 9), date(2024, 8, 16)) == date(2024, 8, 9), "an exact Friday in the title outranks a file name for another Friday")
check(raises(lambda: AR.resolve_end(date(2024, 8, 7), date(2024, 8, 30)), RuntimeError) and raises(lambda: AR.resolve_end(None, None), RuntimeError), "a title and a name more than a week apart, or neither, fail")
check(AR.week_day(date(2026, 4, 3)) == date(2026, 4, 1) and AR.week_day(date(2026, 1, 2)) == date(2025, 12, 31), "a week is counted on its Wednesday (the week ending Jan 2 is December's)")

print("-- the county, the purpose and the operator")
check(len(AR.COUNTIES) == 75 and len(AR.COUNTY_CODE) == 75, "75 counties, 75 codes")
check(all(AR.COUNTY_CODE[c] == n.upper() for c, n in {"083": "Logan", "139": "Union", "027": "Columbia", "145": "White", "141": "Van Buren", "023": "Cleburne", "103": "Ouachita", "073": "Lafayette", "091": "Miller", "123": "St. Francis", "149": "Yell", "001": "Arkansas"}.items()),
      "the county places of an API number match the Commission's wells (083 is Logan, 139 Union, 027 Columbia...)")
check(AR.county_from_api("03 083 11459") == "Logan" and AR.county_from_api("03-145-11575") == "White" and AR.county_from_api("03 27 12164") == "Columbia", "the county from an API number: spaced, hyphenated, and a code without its zero")
check(AR.county_from_api("03 1319 13613") is None and AR.county_from_api("05 083 11459") is None and AR.county_from_api("") is None and AR.county_from_api(None) is None and AR.county_from_api("03 150 00001") is None,
      "a malformed API number, another state's, a code that is no county: no county")
check(AR.county_of("Hot Spring") == "Hot Spring" and AR.county_of("st. francis") == "St. Francis" and AR.county_of("ST FRANCIS") == "St. Francis" and AR.county_of("Wildcat") is None and AR.county_of("Lafaytte") is None and AR.county_of(None) is None,
      "a printed county is known only when it is one of the 75 (a field's name or a misspelling is not)")
check([AR.purpose_band(x) for x in ([], [""], ["renewal"], ["amend"], ["re-entry"], ["reneral"], ["Renewal", "amend"], ["re-entry", "amend"], ["workover pending"], ["amendment"])]
      == ["new", "new", "amend", "amend", "redrill", "amend", "amend", "amend", "other", "amend"], "no purpose is a new well; renewal, amend (and a misspelled renewal) are amendments; re-entry a re-entry; an amendment outranks a re-entry; an unknown word is other")
check(AR.clean_operator("Quanico Oil & Gas, Inc.") == "Quanico Oil & Gas, Inc" and AR.clean_operator("PO Box 10519") == "" and AR.clean_operator("  Flywheel   Energy, LLC ") == "Flywheel Energy, LLC" and AR.clean_operator("5/1/2026") == ""
      and AR.clean_operator("") == "" and AR.clean_operator(None) == "", "an operator is one spelling; an address or a date is not an operator")

print("-- a workbook")
P1 = {"sec": "SOUTH", "no": "48450", "api": "03 139 13684", "name": "Clair  C-3", "field": "Olin Forest North", "county": "Union", "operator": "Quanico Oil & Gas, Inc.", "labels": []}
P2 = {"sec": "NORTH", "no": "48454", "api": "03 083 11459", "name": "Watson, Leslie  1", "field": "B-44", "county": "Logan", "operator": "Hanna Oil and Gas Company", "labels": ["renewal", "amend"]}
P3 = {"sec": "NORTH", "no": "48455", "api": "03 083 11460", "name": "Riley  3-2", "field": "Caulksville", "county": "Logan", "operator": "Smith, Jerry Production", "labels": ["re-entry"]}
fri = date(2026, 4, 3)
title, L = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1, P2, P3]))))
check(title == fri, "the title's date comes back")
check([(l["band"], l["county"], l["operator"]) for l in L] == [("amend", "Logan", "Hanna Oil and Gas Company"), ("redrill", "Logan", "Smith, Jerry Production"), ("new", "Union", "Quanico Oil & Gas, Inc")],
      "each Form 2 permit gives its purpose's band, county and operator, North's before South's, and the decoy in the recompletions is not a permit: %s" % [(l["band"], l["county"]) for l in L])
check(all(set(l) == {"band", "county", "operator"} for l in L), "nothing but band, county and operator leaves a report")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, []))))
check(L2 == [] and t2 == fri, "a week with NONE in both sections has no permits")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1], none_word="DONE"))))
check(len(L2) == 1, "the Commission's typed DONE for NONE is read as none")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [dict(P2, layout="shifted")]))))
check(L2 == [{"band": "amend", "county": "Logan", "operator": "Hanna Oil and Gas Company"}], "a permit whose first row holds only its numbers (everything one row lower) is read the same: %s" % L2)
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [dict(P2, api="03 1319 11459", layout="swapped")]))))
check(L2[0]["county"] == "Logan", "with no county in the API number, the printed county is found even where the field and the county cells are swapped: %s" % L2)
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [dict(P2, api="03 1319 11459", county="Logn", field="Wildcat")]))))
check(L2[0]["county"] is None, "no readable county is None, never a guess")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [dict(P2, api="03 139 11459", county="Ouachita")]))))
check(L2[0]["county"] == "Union", "the API number's county place outranks the printed county when they differ")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [dict(P1, labels=["workover pending"])]))))
check(L2[0]["band"] == "other", "a purpose word it does not know is `other`, not new")
t2, L2 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1], drop=[("NORTH", "APPLICATION TO PLUG")]))))
check(len(L2) == 1, "a report that leaves out one heading of the long lists (as one did in 2024) is still read")
check(raises(lambda: AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1], drop=[("SOUTH", "WELL COMPLETIONS")])))), RuntimeError), "a report without the heading that closes a Form 2 section is refused")
check(raises(lambda: AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1], drop=[("NORTH", "DRILLING PERMITS")])))), RuntimeError), "a report without a Form 2 heading is refused")
check(raises(lambda: AR.week_from_rows(AR.sheet_rows(xlsx_bytes(week_rows(fri, [P1], none_word="n/a")))), RuntimeError), "a Form 2 section that lists no permit and says no NONE is refused (not read as a quiet week)")
rows = week_rows(fri, [P1])
rows = [r for r in rows if not (1 in r and r[1].startswith("Permits Issued"))]
t3, L3 = AR.week_from_rows(AR.sheet_rows(xlsx_bytes(rows)))
check(t3 is None and len(L3) == 1, "a report with no readable title gives no date (the file's name is then the week)")
check(raises(lambda: AR.sheet_rows(b"not a zip at all"), RuntimeError) and raises(lambda: AR.sheet_rows(b"<html>error</html>"), RuntimeError), "something that is not a workbook is refused")
big = io.BytesIO()
with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("xl/worksheets/sheet1.xml", "<worksheet/>" + " " * (AR.MAX_UNZIPPED + 10))
check(raises(lambda: AR.sheet_rows(big.getvalue()), RuntimeError), "a workbook that unpacks to more than expected is refused before it is read")

print("-- a PDF")
for hy in (False, True):
    title, L = AR.week_from_text(week_text(date(2019, 7, 26), [dict(P2, hyphen=hy), dict(P1, hyphen=hy)]))
    check(title == date(2019, 7, 26) and [(l["band"], l["county"], l["operator"]) for l in L] == [("amend", "Logan", "Hanna Oil and Gas Company"), ("new", "Union", "Quanico Oil & Gas, Inc")],
          "a PDF's permits are read%s: the purpose words at the start of a line, the operator after them, the county from the API number, the page break inside the section ignored: %s" % (" (hyphenated API numbers)" if hy else "", L))
title, L = AR.week_from_text(week_text(date(2019, 7, 26), []))
check(L == [], "a PDF with NONE in both sections has no permits, and the recompletion decoy is not a permit")
title, L = AR.week_from_text(week_text(date(2019, 7, 26), [P1, P3, P2], noise=True))
check([l["band"] for l in L] == ["redrill", "amend", "new"], "three permits across a page break (two North, one South): all three, North's first, in the report's order: %s" % [l["band"] for l in L])
title, L = AR.week_from_text(week_text(date(2019, 7, 26), [dict(P2, labels=["renewal", "amend", "re-entry"])]))
check(L[0]["band"] == "amend", "three purpose words on one permit: an amendment")
check(raises(lambda: AR.week_from_text(week_text(date(2019, 7, 26), [P1]).replace("NONE", "nothing")), RuntimeError), "a PDF with a Form 2 section that is neither permits nor NONE is refused")
check(raises(lambda: AR.week_from_text("a page of something else\nNONE\n"), RuntimeError), "a text that is not a weekly report is refused")
check(AR.read_report(xlsx_bytes(week_rows(fri, [P1])), fake_to_text)[1][0]["band"] == "new" and AR.read_report(pdf_bytes(week_text(date(2019, 7, 26), [P1])), fake_to_text)[1][0]["band"] == "new",
      "a report is a workbook or a PDF by what the file is, not by its name")
check(raises(lambda: AR.read_report(b"<html><body>Server error</body></html>", fake_to_text), RuntimeError), "an HTML page where a report should be is refused")

print("-- the whole run, against the truth")
site = Site()
doc = build(site)
check(C.validate(doc, today=TODAY) == [], "the document passes the shared validator: %s" % C.validate(doc, today=TODAY)[:3])
T_m, T_cty, T_ops, T_unn = truth(WORLD)
months = doc["months"]
check(months[0] == "2019-01" and months[-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-23", "the series runs from January 2019 to the last complete month: %s to %s, asOf %s" % (months[0], months[-1], doc["asOf"]))
for b in ("new", "amend", "redrill", "other"):
    check(doc["bands"][b] == [T_m[b].get(ym, 0) for ym in months], "the %s band is the truth in every month (%d permits)" % (b, sum(doc["bands"][b])))
check(doc["bands"]["inj"] is None and doc["bands"]["rework"] is None and doc["fluid"] is None, "the bands a Form 2 list cannot tell (injection, rework) and the fluid are null, never zero")
check(sum(doc["bands"]["amend"]) > 0 and sum(doc["bands"]["redrill"]) > 0 and sum(doc["bands"]["other"]) > 0, "the fixture exercises amendments, re-entries and other words")
last12 = months[-12:]
want_c = collections.Counter()
for ym in last12:
    want_c.update(T_cty.get(ym, {}))
check({n.upper(): k for n, k in doc["counties"]} == dict(want_c), "the last 12 months' counties are the truth: %s" % doc["counties"][:4])
want_o = collections.Counter()
for ym in last12:
    want_o.update(T_ops.get(ym, {}))
check({n: k for n, k in doc["operators"]} == dict(want_o), "the last 12 months' operators are the truth (corporations only): %s" % doc["operators"][:3])
check(all(C.nameable(n) for n, _ in doc["operators"]) and not any("SMITH" in n or "REYNOLDS" in n for n, _ in doc["operators"]), "no person's business is named")
named, tot = sum(k for _, k in doc["operators"]), sum(doc["bands"]["new"][-12:])
check(0 < doc["namedShare"] < 1 and abs(doc["namedShare"] - round(sum(want_o.values()) / tot, 3)) < 1e-9, "the named share counts the person's permits as unnamed: %s" % doc["namedShare"])
check(doc["read"] == sum(len(p) for f, p in WORLD.items() if (f - timedelta(days=2)) < date(2026, 11, 1) and C.month_of(f - timedelta(days=2)) <= "2026-10") and doc["measure"] == "permits" and doc["unit"] == "drilling permits",
      "every permit counted is read, the measure is permits and the unit drilling permits (%d)" % doc["read"])
check("DONE" not in doc["note"] and all(d.strftime("%B %-d, %Y") in doc["note"] for d in MISSING) and len(MISSING) == 5, "the note names every week with no report (a full read finds the five the constant lists)")
text = json.dumps(doc)
check(not any(w in text for w in ("PO Box", "Fort Smith", "Sewell", "Latitude", "Longitude", "Decoy", "03 139", "03 083", "Well ", "Field ", "SHL")), "no API number, address, contractor, coordinate, well or field name or decoy is in the document")
import re as _re  # noqa: E402
check(not _re.search(r"\b4[0-9]{4}\b", _re.sub(r"https://\S+", "", text)), "no five-digit permit number is in the document")

print("-- a week at the edge of a month, and the first and last weeks")
edge = {date(2026, 4, 3): [dict(P1, no="48001", band="new")], date(2026, 1, 2): [dict(P1, no="48002", band="new")], date(2026, 5, 29): [dict(P1, no="48003", band="new")], date(2026, 6, 5): [dict(P1, no="48004", band="new")]}
w = dict(WORLD)
for f in list(w):
    if date(2025, 12, 1) <= f <= date(2026, 7, 1):
        w[f] = []
w.update(edge)
doc_e = build(Site(world=w))
by = dict(zip(doc_e["months"], doc_e["bands"]["new"]))
check(by["2026-04"] == 1 and by["2026-03"] == 0 and by["2025-12"] == 1 and by["2026-01"] == 0 and by["2026-05"] == 1 and by["2026-06"] == 1,
      "a week goes to the month that holds most of its days: April 3 (Mar 30 to Apr 3) is April, January 2 is December, May 29 is May, June 5 is June: %s" % {k: by[k] for k in ("2025-12", "2026-01", "2026-03", "2026-04", "2026-05", "2026-06")})
check(doc["bands"]["new"][0] == T_m["new"].get("2019-01", 0) and doc["bands"]["new"][0] > 0, "the first month, January 2019, counts the report for the week ending January 4")

print("-- an incremental read")
old_doc = doc
Cdir = tempfile.mkdtemp(prefix="d11ar-")
C.write_doc(old_doc, Cdir)
keep_from = C.add_months(C.month_of(TODAY), -AR.REREAD)
kept = AR.previous(keep_from, os.path.join(Cdir, "AR.json"))
check(sorted(kept)[0] == "2019-01" and max(kept) < keep_from and all(set(v) == {"new", "amend", "redrill", "other"} for v in kept.values()), "the committed file gives the months before the last 14, band by band")
poison = {f: report_bytes(f, [dict(P1, no="48999", band="new")] * 3) for f in WORLD if f < date(2024, 8, 1)}  # old reports that a full read would count differently
s2 = Site(override=poison)
doc2 = build(s2, old=kept)
check(doc2 == old_doc, "the incremental read gives the same document as the full read, with the old months from the committed file")
files = [u for u in s2.requests if "/Data/Wipe/" in u]
check(60 <= len(files) <= 66 and all(("/2025/" in u or "/2026/" in u) for u in files), "only the weeks of the last 14 months are fetched (%d reports)" % len(files))
check(sum(1 for u in s2.requests if "#" in u) == 2 and s2.requests[0] == AR.PAGE, "one page and one postback for each year needed (2025 and 2026), not for all eight")
s3 = Site(override=poison)
doc3 = build(s3, old={})
check(doc3["bands"]["new"] != old_doc["bands"]["new"] and len([u for u in s3.requests if "/Data/Wipe/" in u]) > 380, "with no committed file everything is read again (and the poisoned old reports show)")
check(AR.previous(keep_from, os.path.join(Cdir, "nothing.json")) == {}, "no committed file, no kept months")
bad = json.load(open(os.path.join(Cdir, "AR.json")))
bad["bands"]["amend"] = None
json.dump(bad, open(os.path.join(Cdir, "bad.json"), "w"))
check(AR.previous(keep_from, os.path.join(Cdir, "bad.json")) == {}, "a committed file with a band missing is not trusted for old months")
short = json.load(open(os.path.join(Cdir, "AR.json")))
short["months"], short["bands"] = short["months"][:30], {b: (v[:30] if v else v) for b, v in short["bands"].items()}
json.dump(short, open(os.path.join(Cdir, "short.json"), "w"))
check(AR.previous(keep_from, os.path.join(Cdir, "short.json")) == {}, "a committed file that stops before the last 14 months is not trusted either")

print("-- what damaged input does")
check(raises(lambda: build(Site(years=[2026, 2025])), RuntimeError), "a full read of a page that no longer offers 2019 fails")
check(build(Site(years=[2026, 2025]), old=kept) == old_doc, "a weekly run does not need 2019 on the page (the old years may be taken down)")
check(raises(lambda: build(Site(years=[2025, 2024]), old=kept), RuntimeError), "a page whose year list lacks the current year fails")
check(raises(lambda: build(Site(page="<html>maintenance</html>")), RuntimeError), "a page without its year list and form state fails")
check(raises(lambda: build(Site(drop_year=2023)), RuntimeError), "a past year with no files fails")
check(raises(lambda: build(Site(world={f: p for f, p in list(WORLD.items())[:200]})), RuntimeError), "a full read that finds far fewer reports than there should be fails")
site_stale = Site(world={f: p for f, p in WORLD.items() if f < date(2026, 7, 1)})
check(raises(lambda: build(site_stale, old=kept), RuntimeError), "an archive whose newest report is months old fails")
check(raises(lambda: build(Site(override={date(2026, 3, 6): b"<html><body>Server Error</body></html>"}), old=kept), RuntimeError), "an HTML error page where one report should be fails the run")
check(raises(lambda: build(Site(override={date(2026, 3, 6): xlsx_bytes(week_rows(date(2026, 3, 6), [P1], none_word="n/a"))}), old=kept), RuntimeError), "a report whose Form 2 section is neither permits nor NONE fails the run")
sparse = {f: p for f, p in WORLD.items() if not (date(2026, 1, 1) <= f <= date(2026, 6, 1) and f.day % 2 == 0)}
check(raises(lambda: build(Site(world=sparse), old=kept), RuntimeError), "more than a few weeks with no report fails the run")
nocounty = {f: [dict(p, api="03 1319 1", county="Nowhere", field="Wildcat") for p in ps] for f, ps in WORLD.items() if f >= date(2025, 8, 1)}
check(raises(lambda: build(Site(world={**WORLD, **nocounty}), old=kept), RuntimeError), "permits whose county cannot be read (more than 3 percent) fail the run")
quiet = {f: [] for f in WORLD if f >= date(2025, 8, 1)}
check(raises(lambda: build(Site(world={**WORLD, **quiet}), old=kept), RuntimeError), "a run that finds no permit in 14 months fails (a layout that lost its permits is not a quiet year)")
dup = Site(extra_files={("2026", "09-September", "WklyRep 9.25.26b.xlsx"): xlsx_bytes(week_rows(date(2026, 9, 25), [P1]))})
doc_d = build(dup, old=kept)
check("two files for the week ending September 25, 2026" in doc_d["note"] and doc_d["bands"]["new"] == old_doc["bands"]["new"], "two files for one week: the first is read, and the note says so")
future = Site(world={**WORLD, date(2026, 10, 30): [P1]}, today=date(2026, 10, 31))
check(build(future, old=kept)["asOf"] == "2026-10-30", "a report for the Friday before today is the newest")

print("-- the network")
class Resp:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


calls = []
real_urlopen = AR.urllib.request.urlopen
try:
    def refuse(req, timeout=0):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    AR.urllib.request.urlopen = refuse
    check(raises(lambda: AR.polite_post(AR.PAGE, {"a": "b"}), C.Refused) and len(calls) == 1, "a 403 on the postback is a refusal, asked once")
    seq = [OSError("Connection reset by peer"), Resp(b"<html>ok</html>")]

    def flaky(req, timeout=0):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    AR.urllib.request.urlopen = flaky
    check(AR.polite_post(AR.PAGE, {"a": "b"}, pause=0) == b"<html>ok</html>", "a dropped connection on the postback is tried again")
    seq = [OSError("Connection reset by peer")] * 3 + [Resp(b"<html>ok</html>")]
    check(AR.polite_post(AR.PAGE, {"a": "b"}, pause=0) == b"<html>ok</html>", "the Commission's server drops connections, sometimes twice or three times in a row: up to four attempts")
    seq = [OSError("Connection reset by peer")] * 4 + [Resp(b"never")]
    check(raises(lambda: AR.polite_post(AR.PAGE, {"a": "b"}, pause=0), RuntimeError), "but a fifth drop is a failure, not a loop")
    AR.urllib.request.urlopen = lambda req, timeout=0: Resp(b"x" * 100)
    check(raises(lambda: AR.polite_post(AR.PAGE, {"a": "b"}, max_bytes=10), ValueError), "a reply past the size cap is refused")
    sent = []
    AR.urllib.request.urlopen = lambda req, timeout=0: (sent.append(req), Resp(b"ok"))[1]
    AR.polite_post(AR.PAGE, {"a": "b"})
    hdr = {k.lower(): v for k, v in sent[0].header_items()}
    check(hdr["user-agent"] == C.UA and "@" not in json.dumps(hdr) and sent[0].data == b"a=b", "the postback identifies no person and sends only the form's fields")
finally:
    AR.urllib.request.urlopen = real_urlopen


class Refusing(Site):
    def __init__(self, where, **kw):
        super().__init__(**kw)
        self.where = where

    def get(self, url, **kw):
        if self.where == "page" and url == AR.PAGE or self.where == "file" and "/Data/Wipe/" in url:
            raise C.Refused("HTTP 403 from the server")
        return super().get(url, **kw)

    def post(self, url, fields, **kw):
        if self.where == "post":
            raise C.Refused("HTTP 403 from the server")
        return super().post(url, fields, **kw)


for where in ("page", "post", "file"):
    rc = []
    out = tempfile.mkdtemp(prefix="d11ar-")
    C.write_doc(old_doc, out)
    before = open(os.path.join(out, "AR.json"), "rb").read()
    rc = C.run_producer("AR", lambda w=where: build(Refusing(w), old=kept), out_dir=out, argv=[])
    check(rc == 2 and open(os.path.join(out, "AR.json"), "rb").read() == before, "a refusal at the %s is exit 2 and the committed file stays" % where)
out = tempfile.mkdtemp(prefix="d11ar-")
rc = C.run_producer("AR", lambda: build(Site(drop_year=2023), old={}), out_dir=out, argv=[])
check(rc == 1 and not os.path.exists(os.path.join(out, "AR.json")), "a failed run writes nothing")
rc = C.run_producer("AR", lambda: build(Site(), old={}), out_dir=out, argv=[])
check(rc == 0 and C.check_dir(out) == [] and C.run_producer("AR", None, out_dir=out, argv=["--check"]) == 0, "a good run writes a file that passes --check")

print("all passed" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
