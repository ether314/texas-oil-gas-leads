"""Tests for site/pipeline/d11_nat_sd.py: South Dakota's well permits, read from Wells.xlsx inside the program's monthly export (SDOILexport.zip), for the National report.

A synthetic export (invented companies and people, invented well names, API numbers and links in columns the producer must ignore) is built here as a real zip holding a real .xlsx. It pins what
a count is (one well on its permit date, the type of well from "Permitted Well Type", fluid from the same words), the quiet case South Dakota is in (the newest permit is two years old, the file is fresh:
the months since are real zeros and the document says `zeroOk`), and an active year; that only Wells.xlsx is opened (the decoy members are junk); the date cell in all its forms; and that a stale export,
a cut-short file, a renamed column, dates that stop reading, a damaged zip and a refusal each fail the run and leave a committed file as it was. With SD_REAL_FILES=<SDOILexport.zip> it also reads the
real export and checks the program's own yearly counts (4, 0, 4, 11, 4, 1 for 2019 to 2024).

Run: python3 -I tests/test_d11_sd.py"""
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import date
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_sd as SD  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def serial(d):
    return (d - date(1899, 12, 30)).days


# ------------------------------------------------------------------------------------------------ a synthetic export
HEADER = ["API Number", "Permit", "Operator", "Well Name", "Administrative Status", "County", "Permitted Well Type", "Date Permit Issued", "Spud Date",
          "Latitude (GCS NAD 83)", "Longitude (GCS NAD 83)", "Permit file URL", "Export Date"]
COMPANIES = ["Gulf Test Exploration, LLC", "Sample Prairie Resources, Inc.", "Fixture Gas Partners LP"]
PEOPLE = ["Doe, Jane Q.", "R. Roe", "John Q. Example"]
COUNTIES = ["Harding", "Fall River", "Butte", "Custer", "Perkins"]
TYPES = ["Oil", "Oil and Gas Exploration", "Gas", "Oil-Horizontal", "Injection", ""]


def col(i):
    return chr(65 + i)


def sheet_xml(header, rows, text_dates=False):
    def cell(r, c, v):
        ref = "%s%d" % (col(c), r)
        if v is None or v == "":
            return ""
        if isinstance(v, (int, float)) and not (text_dates and header[c] == "Date Permit Issued"):
            return '<c r="%s"><v>%s</v></c>' % (ref, v)
        if isinstance(v, (int, float)):
            v = serial_to_text(v)
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(str(v)))
    out = ['<row r="1">%s</row>' % "".join(cell(1, c, h) for c, h in enumerate(header))]
    for n, row in enumerate(rows, start=2):
        out.append('<row r="%d">%s</row>' % (n, "".join(cell(n, c, v) for c, v in enumerate(row))))
    return "".join(out)


def serial_to_text(v):
    d = date.fromordinal(date(1899, 12, 30).toordinal() + int(v))
    return d.strftime("%m/%d/%Y")


def workbook_bytes(header, rows, text_dates=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Export" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'
                   % sheet_xml(header, rows, text_dates))
    return buf.getvalue()


def zip_bytes(wells, extra=None, name="SDOILexport/Wells.xlsx"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SDOILexport/", b"")
        z.writestr("SDOILexport/Formation_Tops.xlsx", b"not a workbook: it must never be opened")
        z.writestr(name, wells)
        z.writestr("SDOILexport/Well_Completions.xlsx", b"not a workbook either")
        z.writestr("SDOILexport/Old_Wells.xlsx.bak", b"a backup copy: its name only contains Wells.xlsx")
        z.writestr("SDOILexport/Oil_Gas_Production_All_Years.xlsx", b"junk " * 1000)
        for n, b in (extra or {}).items():
            z.writestr(n, b)
    return buf.getvalue()


def row(day, kind="Oil", county="Harding", operator=None, export=date(2026, 10, 1), n=0):
    """One well. A permit day may be a date, a raw serial or None; everything the producer must ignore is filled with invented values."""
    s = serial(day) if isinstance(day, date) else day
    return ["40 999 %05d" % (90000 + n), "T-%d" % n, operator if operator is not None else COMPANIES[n % 3], "Invented Test Well No. %d" % n, "Plugged and Abandoned", county, kind, s, None,
            "44.123456", "-103.123456", "https://example.invalid/permit/%d.pdf" % n, serial(export)]


def history():
    """The state's old permits, 2005 to 2014 (the file is full of them), with people among the operators; blank and placeholder dates; 1,800 rows in all."""
    rows = []
    for i in range(1700):
        day = date(2005, 1, 1).toordinal() + (i * 5) % 3500
        rows.append(row(date.fromordinal(day), TYPES[i % 6], COUNTIES[i % 5], (COMPANIES + PEOPLE)[i % 6], n=i))
    rows += [row(None, "Oil and Gas Exploration", n=2000 + i) for i in range(60)]  # no permit date: the oldest wells
    rows += [row(3348 + i, "Oil", n=2100 + i) for i in range(40)]  # 1909 and after: placeholders and very old permits
    return rows


QUIET = [row(date(2019, 7, 9), "Oil", "Fall River", COMPANIES[0], n=5001), row(date(2019, 9, 20), "Oil", "Fall River", COMPANIES[0], n=5002), row(date(2019, 9, 20), "Oil", "Fall River", COMPANIES[0], n=5003),
         row(date(2019, 9, 21), "Oil", "Fall River", COMPANIES[0], n=5004)]
QUIET += [row(date(2022, 2, 11), "Gas", "Harding", COMPANIES[1], n=5100 + i) for i in range(11)]
QUIET += [row(date(2024, 7, 16), "Oil", "Fall River", PEOPLE[0], n=5200)]
ACTIVE = [row(date(2026, 2, 3), "Oil", "Harding", COMPANIES[0], n=5300), row(date(2026, 2, 17), "Oil-Horizontal", "Harding", COMPANIES[0], n=5301),
          row(date(2026, 4, 10), "Oil and Gas Exploration", "Fall River", PEOPLE[1], n=5302), row(date(2026, 5, 5), "Injection", "Harding", COMPANIES[1], n=5303),
          row(date(2026, 6, 2), "Gas", "Butte", COMPANIES[2], n=5304)]


def export_of(recent, **kw):
    return zip_bytes(workbook_bytes(HEADER, history() + recent, **kw))


class Net:
    def __init__(self, body):
        self.body, self.urls = body, []

    def get(self, url, **kw):
        self.urls.append((url, kw))
        return self.body


def run(body, today=TODAY):
    return SD.build(get=Net(body).get, today=today)


def fails(body, today=TODAY):
    try:
        SD.build(get=Net(body).get, today=today)
        return False, ""
    except RuntimeError as e:
        return True, str(e)


# ------------------------------------------------------------------------------------------------ the date cell
check(SD.serial_day("46296", TODAY) == (date(2026, 10, 1), "ok"), "Excel day 46296 is Oct 1, 2026 (the real export's own date)")
check(SD.serial_day(str(serial(date(2024, 7, 16))), TODAY) == (date(2024, 7, 16), "ok") and SD.serial_day(46296.0, TODAY)[0] == date(2026, 10, 1) and SD.serial_day("45489.0", TODAY)[1] == "ok",
      "a day number reads as a date, as text, a float or a number")
check(SD.serial_day(None, TODAY) == (None, "blank") and SD.serial_day("", TODAY) == (None, "blank") and SD.serial_day("  ", TODAY) == (None, "blank"), "blank is blank")
check(SD.serial_day("3348", TODAY) == (None, "old") and SD.serial_day("18263", TODAY) == (None, "old") and SD.serial_day("18264", TODAY) == (date(1950, 1, 1), "ok"), "a number before 1950 is the file's old or placeholder date, ignored without complaint")
check(SD.serial_day("7/16/2024", TODAY) == (date(2024, 7, 16), "ok") and SD.serial_day("2024-07-16", TODAY) == (date(2024, 7, 16), "ok"), "a date written as text still reads")
check(SD.serial_day("soon", TODAY)[1] == "bad" and SD.serial_day("99999", TODAY)[1] == "bad" and SD.serial_day(str(serial(date(2026, 12, 25))), TODAY)[1] == "bad", "text that is not a date, a number out of range and a day after today are bad")

# ------------------------------------------------------------------------------------------------ reading the export
good = export_of(QUIET)
rows = SD.read_wells(good)
check(len(rows) == 1800 + len(QUIET) and set(rows[0]) == set(SD.WANT), "Wells.xlsx is read and only the five wanted columns come out (%d rows)" % len(rows))
check(not any(k in rows[0] for k in ("API Number", "Well Name", "Permit file URL", "Latitude (GCS NAD 83)", "Permit")), "no API number, well name, permit number, link or coordinate is read")


def raises(body):
    try:
        SD.read_wells(body)
        return ""
    except RuntimeError as e:
        return str(e)


check("2 files" in raises(zip_bytes(workbook_bytes(HEADER, [row(date(2024, 1, 1))]), extra={"SDOILexport/old/Wells.xlsx": b"x"})), "two Wells.xlsx in the export fail the run")
check("0 files" in raises(zip_bytes(workbook_bytes(HEADER, [row(date(2024, 1, 1))]), name="SDOILexport/Wellz.xlsx")), "no Wells.xlsx fails the run")
check(raises(b"<html><body>Service unavailable</body></html>") != "" and raises(b"") != "", "a web page, or nothing, in place of the zip fails the run")
check(raises(zip_bytes(b"this is not a workbook")) != "", "a Wells.xlsx that is not a workbook fails the run")
renamed = zip_bytes(workbook_bytes([("Permit Date" if h == "Date Permit Issued" else h) for h in HEADER], history()))
check("Date Permit Issued" in raises(renamed), "a renamed date column fails the run, and says which: " + raises(renamed)[:80])
old_max = SD.MAX_MEMBER
SD.MAX_MEMBER = 1000
check("more than" in raises(good), "a Wells.xlsx larger than the cap is not opened")
SD.MAX_MEMBER = old_max
with_case = zip_bytes(workbook_bytes(HEADER, history()), name="SDOILexport/WELLS.XLSX")
check(raises(with_case) == "", "the member is found whatever the case of its name")

# ------------------------------------------------------------------------------------------------ the quiet case South Dakota is in
net = Net(good)
doc = SD.build(get=net.get, today=TODAY)
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(net.urls[0][0] == SD.ZIP_URL and net.urls[0][1].get("max_bytes") == SD.MAX_ZIP and len(net.urls) == 1, "one download of the export, from an https address, with a size cap")
check(doc["state"] == "SD" and doc["measure"] == "permits" and "issue date" in doc["basis"] and doc["cadence"] == "monthly", "permits by issue date, monthly")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-01",
      "the series runs to the month before the export date, which is asOf (not to the newest permit, two years back)")
by_year = {y: sum(v for m, v in zip(doc["months"], doc["bands"]["new"]) if m.startswith(str(y))) for y in range(2019, 2027)}
check(by_year == {2019: 4, 2020: 0, 2021: 0, 2022: 11, 2023: 0, 2024: 1, 2025: 0, 2026: 0}, "permits by year are the rows' own (4, 0, 0, 11, 0, 1): %s" % by_year)
check(sum(doc["bands"]["new"][-24:]) == 0 and doc.get("zeroOk") is True, "two years with no permit are published as real zeros, and the document says so (zeroOk)")
check(doc["bands"]["inj"] == [0] * len(doc["months"]) and all(doc["bands"][b] is None for b in ("redrill", "rework", "amend", "other")), "injection is told (zero); the kinds the file cannot tell are null, never zero")
check(doc["fluid"] == {"oil": 0, "gas": 0, "both": 0, "other": 0, "unknown": 0} and doc["counties"] == [] and doc["operators"] == [] and doc["namedShare"] is None, "nothing in the last 12 months: no county, no operator, no share")
check("real zero" in doc["note"] and "2024-07-16" in doc["note"], "the note says the months since July 16, 2024 are real zeros")
check(doc["read"] == 16, "`read` counts the permits since 2019 (16 here)")
text = json.dumps(doc)
check(not re.search(r"Doe|Roe|Example|Invented|invalid|40 999|T-\d", text), "no person, well name, API number or link reaches the file")

# an active year: kinds, fluid, counties, named operators only
doc2 = run(export_of(QUIET + ACTIVE))
check(C.validate(doc2, TODAY) == [] and "zeroOk" not in doc2, "an active file validates, and has no zeroOk")
i = {m: k for k, m in enumerate(doc2["months"])}
check([doc2["bands"]["new"][i[m]] for m in ("2026-02", "2026-04", "2026-05", "2026-06")] == [2, 1, 0, 1] and doc2["bands"]["inj"][i["2026-05"]] == 1,
      "a new well is `new`, an injection well is `inj` on its permit month")
check(doc2["fluid"] == {"oil": 2, "gas": 1, "both": 1, "other": 0, "unknown": 0}, "fluid of the last 12 months' new wells: oil 2, gas 1, oil-and-gas exploration 1 (as both): %s" % doc2["fluid"])
check(doc2["counties"] == [["Harding", 2], ["Butte", 1], ["Fall River", 1]], "counties of the last 12 months, ranked: %s" % doc2["counties"])
check(doc2["operators"] == [["GULF TEST EXPLORATION LLC", 2], ["FIXTURE GAS PARTNERS LP", 1]] and doc2["namedShare"] == 0.75, "a person is never named (3 of 4 permits have a nameable operator): %s %s" % (doc2["operators"], doc2["namedShare"]))
check("2026-06-02" in doc2["note"] and "real zero" in doc2["note"], "the note names the newest permit's day (June 2) when months with none follow it")
busy = run(export_of(QUIET + ACTIVE + [row(date(2026, 9, 15), "Oil", "Butte", COMPANIES[0], n=5350)]))
check("real zero" not in busy["note"] and busy["bands"]["new"][-1] == 1, "no 'real zero' sentence when the newest permit is in the newest month")
check(not re.search(r"Doe|Roe|Example", json.dumps(doc2)), "and still no person")

# the same permits with the date column stored as text give the same series
doc3 = run(export_of(QUIET + ACTIVE, text_dates=True))
check(doc3["bands"] == doc2["bands"] and doc3["asOf"] == doc2["asOf"], "dates stored as text (7/16/2024) give the same counts as day numbers")

# a permit dated after today or with a bad date is not counted
future = run(export_of(QUIET + [row(date(2026, 12, 25), "Oil", n=5400)]))
check(future["bands"] == doc["bands"], "a permit dated after today is left out")

# ------------------------------------------------------------------------------------------------ failures fail the run
ok, msg = fails(export_of(QUIET), today=date(2027, 4, 1))
check(ok and "stopped refreshing" in msg, "an export dated 6 months back fails the run: " + msg[:70])
no_export = [h for h in HEADER if h != "Export Date"]
ok, msg = fails(zip_bytes(workbook_bytes(no_export, [r[:-1] for r in history() + QUIET])))
check(ok and "Export Date" in msg, "no Export Date column fails the run: " + msg[:70])
ok, msg = fails(zip_bytes(workbook_bytes(HEADER, (history() + QUIET)[:700])))
check(ok and "cut short" in msg, "a file cut to 700 wells fails the run: " + msg[:70])
junk_dates = [r[:7] + ["when?" if i % 15 == 0 else r[7]] + r[8:] for i, r in enumerate(history() + QUIET)]
ok, msg = fails(zip_bytes(workbook_bytes(HEADER, junk_dates)))
check(ok and "date" in msg, "one permit date in fifteen that is not a date fails the run: " + msg[:70])
no_dates = [r[:7] + [None] + r[8:] for r in history() + QUIET]
ok, msg = fails(zip_bytes(workbook_bytes(HEADER, no_dates)))
check(ok and "readable permit date" in msg, "a date column that is empty fails the run: " + msg[:70])
only_old = [r for r in history()]
ok, msg = fails(zip_bytes(workbook_bytes(HEADER, only_old)))
check(ok and "since 2019" in msg, "a file with no permit since 2019 (the years are missing) fails the run: " + msg[:70])
check(fails(b"<html>maintenance</html>")[0] and fails(b"")[0], "a web page or nothing in place of the zip fails the run")

with tempfile.TemporaryDirectory() as tmp:
    committed = os.path.join(tmp, "SD.json")
    check(C.run_producer("SD", lambda: SD.build(get=Net(good).get, today=TODAY), tmp, argv=[]) == 0 and os.path.exists(committed), "run_producer writes nat/SD.json for a good run")
    before = open(committed, "rb").read()
    check(C.check_dir(tmp) == [] and C.run_producer("SD", lambda: None, tmp, argv=["--check"]) == 0, "the written file reloads and passes --check (zeroOk and all)")

    def refused(url, **kw):
        raise C.Refused("HTTP 403 from the server")

    check(C.run_producer("SD", lambda: SD.build(get=refused, today=TODAY), tmp, argv=[]) == 2, "a refusal by the server exits 2 (an answer, not an error)")
    check(C.run_producer("SD", lambda: SD.build(get=Net(b"<html>").get, today=TODAY), tmp, argv=[]) == 1, "a failure exits 1")
    check(open(committed, "rb").read() == before and os.listdir(tmp) == ["SD.json"], "and the committed file is exactly as it was, with nothing else written")

# ------------------------------------------------------------------------------------------------ the real export, when given
real = os.environ.get("SD_REAL_FILES")
if real:
    d = SD.build(get=Net(open(real, "rb").read()).get, today=TODAY)
    yrs = {y: sum(v for m, v in zip(d["months"], d["bands"]["new"]) if m.startswith(str(y))) for y in range(2019, 2025)}
    check(C.validate(d, TODAY) == [] and yrs == {2019: 4, 2020: 0, 2021: 4, 2022: 11, 2023: 4, 2024: 1}, "the real export: the program's own yearly counts (4, 0, 4, 11, 4, 1): %s" % yrs)

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
