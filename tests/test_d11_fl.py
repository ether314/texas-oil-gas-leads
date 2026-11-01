"""Tests for site/pipeline/d11_nat_fl.py: Florida's permits (Department of Environmental Protection) from its Oil and Gas Permit Database workbook.

The fixture is an invented workbook written the way the real one is (several tabs with WELLS second, shared strings, dates as Excel serial numbers, permit numbers with a letter for a modification or
an H for a horizontal well, the saved date in docProps/core.xml) and a page that links it. It pins: how a permit number becomes new or amend, that a row with no issue date is not an issued permit,
that months after the newest permit are real zeros up to the day the workbook was saved (and the file says `zeroOk` only then), the privacy rule on a person-named operator, that no number, name or
comment from the workbook reaches the output, and that a damaged download (no link on the page, not a workbook, no WELLS tab or a column missing, too few rows, a file cut short, unreadable dates, a
save date that cannot be right, parts that unpack too large) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_fl.py"""
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import date
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_fl as FL  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
SAVED = "2026-09-08T13:51:14Z"
HEADER = ["PERMIT_SORT", "PERMITNO", "COUNTY", "COMPANY", "CURRENT_STATUS", "ISSUE_DATE", "SPUD_DATE", "API_NO", "WELL_NAME", "COMMENTS"]
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def serial(d):
    return (d - date(1899, 12, 30)).days


def col(n):
    return chr(65 + n)


def book(rows, saved=SAVED, tabs=("Facility Information", "WELLS", "TOTALS"), header=HEADER):
    """An .xlsx as bytes: `rows` are lists of cell values for the WELLS tab (text as str, dates as int serials, None for an empty cell)."""
    strings = []

    def s(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def sheet(table):
        out = []
        for r, row in enumerate(table, 1):
            cells = []
            for c, v in enumerate(row):
                if v is None:
                    continue
                ref = "%s%d" % (col(c), r)
                cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, s(v)) if isinstance(v, str) else '<c r="%s"><v>%s</v></c>' % (ref, v))
            out.append('<row r="%d">%s</row>' % (r, "".join(cells)) if cells else '<row r="%d"/>' % r)
        return '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (MAIN, "".join(out))

    sheets = {t: sheet([header] + rows) if t == "WELLS" else sheet([["Lookup"], ["nothing here"]]) for t in tabs}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>' % (
            MAIN, REL, "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(t), i, i) for i, t in enumerate(tabs, 1))))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(
            '<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, REL, i) for i in range(1, len(tabs) + 1)))
        for i, t in enumerate(tabs, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, sheets[t])
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="%s">%s</sst>' % (MAIN, "".join("<si><t>%s</t></si>" % escape(x) for x in strings)))
        if saved:
            z.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="x" xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="y">%s</dcterms:modified></cp:coreProperties>' % saved)
    return buf.getvalue()


def well(no, d, county="BETA", company="Sample Energy, LLC", status="PROD", spud=None):
    sort = no
    return [str(sort), no, county, company, status, serial(d) if d else None, serial(spud) if spud else None, "12-345-67890-00-00", "Example 1-A Invented Well", "intra-office note: call the landowner"]


def old_rows(n=1100):
    rows = [well(str(i), date(1960 + i % 30, 1 + i % 12, 1 + i % 27), "ALPHA", "OLD EXAMPLE OIL CO", "P&A") for i in range(1, n + 1)]
    return rows + [well("%dA" % (n + 50 + i), None, "ALPHA", "OLD EXAMPLE OIL CO", "DENIED") for i in range(40)]  # applications with no issue date


PERMITS_2019 = [
    well("5001", date(2019, 3, 5)), well("5002H", date(2019, 4, 10), "GAMMA"), well("5003HL", date(2019, 4, 10), "GAMMA"), well("5001A", date(2019, 6, 1)), well("5002AH", date(2019, 6, 2), "GAMMA"),
    well("5004B", date(2019, 7, 7)), well("5005", date(2019, 9, 9), "GAMMA", "Pat Q Roe"), well("5006", date(2019, 10, 1), "BETA", "Roe Oil Company dba Pat Roe"), well("5008", date(2019, 11, 2)),
    well("5009", date(2019, 12, 12), "DELTA", "Another Example Corporation"), well("5010", date(2019, 12, 30)), well("5011", date(2020, 2, 11), "DELTA", "Another Example Corporation"),
    well("5012", None, "DELTA", "Another Example Corporation", "PENDING"),  # pending: no issue date
]
PAGE_HTML = '<html><a href="https://floridadep.gov/sites/default/files/OG_WELLS_WEBSITE_7.xlsx">Oil and Gas Permit Database</a> last updated on September 8, 2026</html>'
BOOK = book(old_rows() + PERMITS_2019)


def net(html=PAGE_HTML, data=BOOK):
    seen = []

    def get(url, **kw):
        seen.append(url)
        return html.encode() if url == FL.PAGE else data

    get.seen = seen
    return get


# ------------------------------------------------------------------------------------------------ small parts
bands = {"1374": "new", "1347H": "new", "1340HL": "new", "1347h": "new", "553A": "amend", "904B": "amend", "904AH": "amend", "1004BH": "amend", "1335D": "amend", " 1371 ": "new"}
check(all(FL.band_of(k) == v for k, v in bands.items()), "a plain number or a horizontal marker is new; a modification letter (also before an H) is an amendment: %s" % {k: FL.band_of(k) for k, v in bands.items() if FL.band_of(k) != v})
check(FL.band_of("") is None and FL.band_of(None) is None and FL.band_of("ABC") is None and FL.band_of("12345678") is None and FL.band_of("12-3") is None and FL.band_of("1234ABCD") is None, "text that is not a permit number is None")
check(FL.serial_day(serial(date(2019, 8, 9)), TODAY) == date(2019, 8, 9) and FL.serial_day(str(serial(date(2019, 8, 9))), TODAY) == date(2019, 8, 9) and FL.serial_day("43686.0", TODAY) == date(2019, 8, 9),
      "an Excel serial number (number or text) is a date")
check(FL.serial_day("3/4/2020", TODAY) == date(2020, 3, 4) and FL.serial_day(serial(date(1945, 6, 26)), TODAY) == date(1945, 6, 26), "text dates and a 1945 serial read too")
check(FL.serial_day(serial(date(2030, 1, 1)), TODAY) is None and FL.serial_day("0", TODAY) is None and FL.serial_day("soon", TODAY) is None and FL.serial_day("", TODAY) is None, "a future day, zero, junk and blank are not dates")
check(FL.workbook_link(PAGE_HTML) == "https://floridadep.gov/sites/default/files/OG_WELLS_WEBSITE_7.xlsx", "the workbook's address comes from the page (its version number can change)")
check(FL.workbook_link('<a href="/sites/default/files/OG_WELLS_WEBSITE_5.xlsx">x</a>') == "https://floridadep.gov/sites/default/files/OG_WELLS_WEBSITE_5.xlsx", "a relative link is made absolute")
check(FL.workbook_link("<html>no link</html>") is None and FL.workbook_link('<a href="https://elsewhere.example/sites/default/files/OG_WELLS_WEBSITE_4.xlsx">x</a>') is None, "no link, or a link to another site, is None")

# ------------------------------------------------------------------------------------------------ the workbook reader
rows, saved = FL.read_book(BOOK)
check(len(rows) == len(old_rows()) + len(PERMITS_2019) and saved == date(2026, 9, 8) and set(rows[0]) == set(FL.WANT), "the WELLS tab (the second one) is read, with only the wanted columns, and the save date is the file's metadata")
check(rows[-1]["PERMITNO"] == "5012" and rows[-1]["ISSUE_DATE"] is None, "an empty cell is None")
check(FL.read_book(book(old_rows(5), tabs=("WELLS",)))[0][0]["PERMITNO"] == "1", "the WELLS tab is found by its name, wherever it is")
check(FL.read_book(book(old_rows(5), saved=None))[1] is None, "a workbook with no save date gives None (the producer then refuses)")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
get = net()
doc = FL.build(get=get, today=TODAY, pause=0)
check(get.seen == [FL.PAGE, "https://floridadep.gov/sites/default/files/OG_WELLS_WEBSITE_7.xlsx"], "two requests: the page, then the workbook it links")
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "FL" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-08" and doc["through"] == "2026-08-31" and doc["asOf"] == "2026-09-08",
      "from January 2019 to the last complete month before the day the workbook was saved")
b = doc["bands"]
check(b["new"] is not None and b["amend"] is not None and all(b[k] is None for k in ("inj", "redrill", "rework", "other")) and doc["fluid"] is None, "it tells new and amend only, and no fluid")
mi = {ym: i for i, ym in enumerate(doc["months"])}
check(b["new"][mi["2019-04"]] == 2 and b["amend"][mi["2019-06"]] == 2 and b["amend"][mi["2019-07"]] == 1 and b["new"][mi["2019-12"]] == 2 and b["new"][mi["2020-02"]] == 1, "permits are counted by issue date: horizontal wells are new, lettered numbers are amendments")
check(sum(b["new"]) == 9 and sum(b["amend"]) == 3 and doc["read"] == 12, "9 new, 3 amendments; the pending application and every permit before 2019 are not in the series (%d new, %d amend, %d read)" % (sum(b["new"]), sum(b["amend"]), doc["read"]))
check(not any(b["new"][mi["2020-03"]:]) and not any(b["amend"][mi["2020-03"]:]) and len(b["new"][mi["2020-03"]:]) == 78, "the months after the newest permit are zeros up to the save date")
check(doc.get("zeroOk") is True and "February 11, 2020" in doc["note"] and "September 8, 2026" in doc["note"], "no new permit in two years: the file says zeroOk, and its note gives the newest permit's day and the save date")
check(doc["operators"] == [] and doc["counties"] == [] and doc["namedShare"] is None, "nothing in the last 12 months, so no operators, no places and no share")
# a state that issues permits again: counts, places and operators, and no zeroOk
more = [well("5020", date(2025, 11, 4), "OMEGA", "Sample Energy, LLC"), well("5021", date(2025, 12, 4), "OMEGA", "Sample Energy, LLC"), well("5022H", date(2026, 3, 4), "SIGMA", "Another Example Corporation"),
        well("5023", date(2026, 5, 4), "SIGMA", "Pat Q Roe"), well("5024", date(2026, 6, 4), "SIGMA", "Roe Oil Company dba Pat Roe"), well("5020A", date(2026, 7, 4), "OMEGA", "Sample Energy, LLC")]
d2 = FL.build(get=net(data=book(old_rows() + PERMITS_2019 + more)), today=TODAY, pause=0)
check(C.validate(d2, TODAY) == [] and "zeroOk" not in d2 and sum(d2["bands"]["new"][-12:]) == 5 and sum(d2["bands"]["amend"][-12:]) == 1, "with permits in the last year: 5 new, 1 amendment, valid, no zeroOk")
check(d2["counties"] == [["Sigma", 3], ["Omega", 2]] and d2["operators"][0] == ["SAMPLE ENERGY LLC", 2] and [o[0] for o in d2["operators"]] == ["SAMPLE ENERGY LLC", "ANOTHER EXAMPLE CORPORATION"], "places and corporate operators are ranked")
check(d2["namedShare"] == 0.6 and "ROE" not in json.dumps(d2).upper(), "a person, or a person's dba, is counted but never named: 3 of 5 new permits have a name that may be published")
for d in (doc, d2):
    text = json.dumps(d)
    check(not any(x in text for x in ("12-345-67890", "Invented", "landowner", "5001", "5002", "5020", "5003")), "no API number, well name, comment or permit number reaches the file")

# ------------------------------------------------------------------------------------------------ failures fail the run


def fails(**kw):
    html, data = kw.pop("html", PAGE_HTML), kw.pop("data", BOOK)
    try:
        FL.build(get=net(html, data), today=kw.pop("today", TODAY), pause=0)
        return False
    except Exception:  # noqa: BLE001 - any exception ends the run without a file
        return True


check(fails(html="<html>moved</html>"), "a page with no link to the workbook fails the run")
check(fails(data=b"<html>Service unavailable</html>"), "an HTML page instead of the workbook fails the run")
check(fails(data=book(old_rows() + PERMITS_2019, tabs=("Facility Information", "TOTALS"))), "a workbook with no WELLS tab fails the run")
no_issue = [[v for i, v in enumerate(r) if HEADER[i] != "ISSUE_DATE"] for r in old_rows() + PERMITS_2019]
check(fails(data=book(no_issue, header=[h for h in HEADER if h != "ISSUE_DATE"])), "a workbook whose ISSUE_DATE column is gone or renamed fails the run")
check(fails(data=book(old_rows(300) + PERMITS_2019)), "too few rows fail the run")
check(fails(data=book(old_rows())), "a file with none of the permits since 2019 (cut short) fails the run")


def bad_dates(k):
    """k permits whose ISSUE_DATE cell holds text that is not a date."""
    return [r[:5] + ["not a date"] + r[6:] for r in (well("%d" % (7000 + i), date(2019, 5, 5)) for i in range(k))]


check(fails(data=book(old_rows() + PERMITS_2019 + bad_dates(30))), "dates that cannot be read in more than 2% of the dated rows fail the run")
check(not fails(data=book(old_rows() + PERMITS_2019 + bad_dates(5))), "a few stray unreadable dates (under 2%) are left out, not fatal")
check(fails(data=book(old_rows() + PERMITS_2019, saved="2019-05-01T00:00:00Z")), "a workbook saved before its own newest permit fails the run")
check(fails(data=book(old_rows() + PERMITS_2019, saved="2026-12-25T00:00:00Z")), "a save date in the future fails the run")
check(fails(data=book(old_rows() + PERMITS_2019, saved="2020-04-01T00:00:00Z"), today=TODAY), "a save date more than 800 days old fails the run")
check(fails(data=book(old_rows() + PERMITS_2019, saved=None)), "a workbook that does not say when it was saved fails the run")
old_member = FL.MAX_MEMBER
FL.MAX_MEMBER = 2000
check(fails(), "a part of the workbook that unpacks larger than the cap fails the run before anything is read")
FL.MAX_MEMBER = old_member
check(not fails(), "and the same file passes with the real cap")

# the one main every producer uses
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("FL", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "FL.json")), "run_producer writes nat/FL.json for it")
    check(C.check_dir(tmp) == [], "and the written file reloads clean")


def refuse():
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("FL", refuse, tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusing server ends with exit 2 and writes nothing")
    check(C.run_producer("FL", lambda: FL.build(get=net(html="<html/>"), today=TODAY, pause=0), tmp, argv=[]) == 1 and not os.listdir(tmp), "a changed page ends with exit 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
