"""Tests for site/pipeline/d11_nat_ak.py: Alaska's permits to drill (AOGCC) from the Data Miner's two downloads, wellhistory.zip (Well Work Dates) and wells.zip (Wells).

The fixtures are .xlsx workbooks written the way the Commission's are (every tag with an x: prefix, no cell positions, text as t="str" and numbers as t="n", an empty cell as an empty
<x:v>, an absolute target in the relationships file behind a byte-order mark) inside a zip whose single member carries the day the export was made. An invented population of permits
(about four a month for 93 months: original holes of Development, Exploratory, Service and Stratigraphic Test class, sidetracks, a lateral, a pilot hole that shares its parent's permit, one
permit approved twice, one re-issued, one approved before 2019, an operator who is a person) is written to both files, and an oracle that never calls the module says what must come out.

They pin: the workbook reader (prefix, positions, shared and inline strings, a shifted row refused, a blank row skipped, entity declarations refused, a zip that is not the zip), the count (one
permit once, on its first approval; nothing before 2019; the open month left out), the bands (original hole by class, any sidetrack code a re-drill whatever the class, the pilot hole's code
never turning a new well into a re-drill, no band claimed that the file cannot tell: rework and amend are null), the Wells join (the row with a class, the same whichever order the rows come
in), the fluid, the places, the operators (a person is never named), that nothing but counts reaches the file, and every refusal (a stale export, no recent approval, too few rows, lost
classes, an unknown class, approvals and issues that disagree, a history that shrank, a refusal by the server). The network is faked.

Run: python3 -I tests/test_d11_ak.py"""
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_ak as AK  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
MADE = (2026, 10, 30, 6, 0, 36)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, kind=RuntimeError):
    try:
        fn()
    except kind:
        return True
    except Exception as e:  # noqa: BLE001
        print("     raised %s: %s" % (type(e).__name__, e))
        return False
    return False


# ------------------------------------------------------------------------------------------------ writing the Commission's files

def cell(v):
    if v is None:
        return '<x:c t="str"><x:v></x:v></x:c>'
    if isinstance(v, int):
        return '<x:c t="n"><x:v>%d</x:v></x:c>' % v
    return '<x:c t="str"><x:v>%s</x:v></x:c>' % escape(v)


def sheet_xml(rows):
    return ('<?xml version="1.0" encoding="utf-8"?><x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheetData>'
            + "".join("<x:row>%s</x:row>" % "".join(cell(v) for v in r) for r in rows) + "</x:sheetData></x:worksheet>")


def xlsx(rows, sheet=None, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" />')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="utf-8"?><x:workbook xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheets>'
                   '<x:sheet name="WellHistory" sheetId="1" r:id="R5b9c" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" /></x:sheets></x:workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '﻿<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="/xl/worksheets/sheet1.xml" Id="R5b9c" /></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet if sheet is not None else sheet_xml(rows))
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return buf.getvalue()


def export_zip(book, name="export.xlsx", when=MADE):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo(name, date_time=when), book)
    return buf.getvalue()


def stamp(d):
    return "%d/%d/%d 12:00:00 AM" % (d.month, d.day, d.year)


HIST_HEAD = ["Api", "Permit", "ActivityDate", "WellName", "WellConfidential", "OperatorName", "TypeWork"]
WELLS_HEAD = ["Api", "Permit", "WellName", "WellConfidential", "OperatorName", "AreaName", "FieldName", "PoolNames", "CurrentClass", "CurrentStatus", "SpudDate", "CompletionDate", "ReleaseDate",
              "Offshore", "PermittedClass", "PermittedStatus", "LastStatusChange", "Leases", "Pad"]
HILCORP, CONOCO, SEARCH = "Hilcorp Alaska, LLC", "ConocoPhillips Alaska, Inc.", "Oil Search (Alaska), LLC"
PERSON = "John Smith dba Acme Oil"


class Population:
    """Permits as (permit, code, class, status, area, operator, approved day), written to both files, with an oracle of what each one is."""

    def __init__(self):
        self.permits = []
        self.hist = [HIST_HEAD]
        self.wells = [WELLS_HEAD]
        self.n = 0

    def api(self, well, code):
        return "50029%05d%s00" % (well, code)

    def add(self, day, code, cls, status, area, op, pilot=False, issued=True, reissue=None, second=None, band=None, fluid=None):
        self.n += 1
        pid = str(200000 + self.n)
        well = 20000 + self.n
        name = "PRUDHOE BAY UNIT Z-%02d%s" % (self.n % 100, "" if code == "00" else "A")
        api = self.api(well, code)
        for kind, d in (("Dt Application Received (10-401)", day - timedelta(days=20)), ("Dt Well Permit Approved", day), ("Dt Well Permit Issued", day if issued else None), ("Dt Well Spudded", day + timedelta(days=30)),
                        ("Dt Well Permit Re-Issued", reissue), ("Dt Well Permit Approved", second)):
            if d is not None:
                self.hist.append([int(api), int(pid), stamp(d), name, "No", op, kind])
        if pilot:  # a pilot hole shares the permit: its own well number (code 70) and no class in the Wells file
            self.hist.append([int(self.api(well, "70")), int(pid), stamp(day + timedelta(days=40)), name + "PH", "No", op, "Dt Well Spudded"])
            self.wells.append([self.api(well, "70"), pid, name + "PH", "No", op, area, "*DEVELOPMENT", "Unknown", "Unknown", "Plugged & Abandoned", stamp(day), None, None, "No", None, None, stamp(day), None, None])
        self.wells.append([api, pid, name, "No", op, area, "PRUDHOE BAY, PRUDHOE OIL", "Unknown", cls, "Oil well, single completion", stamp(day), None, None, "No", cls, status, stamp(day), "ADL0025650", "Z"])
        self.permits.append({"id": pid, "day": min(d for d in (day, second) if d), "band": band, "area": area, "op": op, "fluid": fluid})
        return pid


def population():
    p = Population()
    months = C.month_list("2019-01", "2026-09")
    for i, ym in enumerate(months):
        y, m = int(ym[:4]), int(ym[5:])
        day = lambda k: date(y, m, k)  # noqa: E731
        p.add(day(5), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, pilot=(i % 3 == 0), band="new", fluid="oil")
        p.add(day(12), "00", "Service", "Water injection, single completion", "COOK INLET BASIN", CONOCO, band="inj")
        p.add(day(20), "01", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, band="redrill")
        if i % 6 == 0:
            p.add(day(8), "00", "Stratigraphic Test", "Information well", "COOK INLET BASIN", SEARCH, band="other")
        if i % 4 == 0:
            p.add(day(15), "00", "Exploratory", None, "ARCTIC OCEAN, ST.", PERSON, band="new", fluid=None)
        if i % 5 == 0:
            p.add(day(25), "00", "Development", "Gas well, single completion", "COOK INLET BASIN", HILCORP, band="new", fluid="gas")
        if i % 7 == 0:
            p.add(day(18), "60", "Service", "Water injection, single completion", "ARCTIC SLOPE", CONOCO, band="redrill")  # a lateral leg: a re-drill whatever the class
    p.add(date(2026, 10, 5), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, band="new", fluid="oil")
    p.add(date(2026, 10, 20), "01", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, band="redrill")
    p.add(date(2026, 10, 27), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, band="new", fluid="oil")  # the newest approval: the month stays open
    # a permit approved twice (counted once, in its first month), one re-issued (not a second approval), one approved before 2019 (not counted)
    p.add(date(2022, 3, 10), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, second=date(2022, 5, 2), band="new", fluid="oil")
    p.add(date(2022, 3, 5), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, reissue=date(2022, 4, 1), band="new", fluid="oil")
    p.add(date(2018, 12, 31), "00", "Development", "Oil well, single completion", "ARCTIC SLOPE", HILCORP, band="new", fluid="oil")
    p.add(date(1977, 5, 1), "00", "Exploratory", "Geothermal", "ARCTIC SLOPE", "US Navy", band="new")
    return p


POP = population()
HIST_ZIP = export_zip(xlsx(POP.hist), "wellhistory.xlsx")
WELLS_ZIP = export_zip(xlsx(POP.wells), "wells.xlsx")


class Net:
    def __init__(self, hist=HIST_ZIP, wells=WELLS_ZIP):
        self.files = {AK.HISTORY_URL: hist, AK.WELLS_URL: wells}
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        return self.files[url]


def build(net=None, old=None, today=TODAY):
    net = net or Net()
    return AK.build(get=net.get, pause=0, today=today, old={} if old is None else old)


# ------------------------------------------------------------------------------------------------ the workbook reader
rows = list(AK.xlsx_rows(xlsx([["Api", "Permit", "Date"], [50029200010000, 170001, "10/16/1963 12:00:00 AM"], [None, 170002, "Q & A <x>"]])))
check(rows == [["Api", "Permit", "Date"], ["50029200010000", "170001", "10/16/1963 12:00:00 AM"], [None, "170002", "Q & A <x>"]], "the Commission's layout (x: prefix, no positions, an absolute relationship target behind a byte-order mark, an empty cell, an escaped & and <) is read: %s" % rows[:2])
positioned = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
              '<row r="1"><c r="A1" t="inlineStr"><is><t>Api</t></is></c><c r="C1" t="inlineStr"><is><t>Date</t></is></c></row>'
              '<row r="2"><c r="A2" t="s"><v>0</v></c><c r="C2"><v>44000</v></c></row><row r="3"/><row r="4"><c r="C4"><v>7</v></c></row></sheetData></worksheet>')
got = list(AK.xlsx_rows(xlsx(None, sheet=positioned, extra={"xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>shared</t></si></sst>'})))
check(got == [["Api", None, "Date"], ["shared", None, "44000"], [None, None, "7"]], "with positions (r=), inline and shared strings, a skipped column is None, a blank row is skipped, a short positioned row is padded: %s" % got)
shifted = [["Api", "Permit", "Date"], ["1", "2", "3"], ["4", "5"]]
check(raises(lambda: list(AK.xlsx_rows(xlsx(shifted)))), "a row shorter than the header, with no positions, is refused (its cells would be read under the wrong columns)")
check(raises(lambda: list(AK.xlsx_rows(xlsx(None, sheet='<!DOCTYPE x [<!ENTITY a "aaaa">]>' + sheet_xml([["a"]]))))), "a sheet that declares entities is refused")
check(raises(lambda: list(AK.xlsx_rows(b"<html>not a workbook</html>"))), "bytes that are not a workbook are refused")
check(raises(lambda: AK.unzip_one(b"<html>an error page</html>", "x")), "a download that is not a zip is refused")
two = io.BytesIO()
with zipfile.ZipFile(two, "w") as z:
    z.writestr("a.xlsx", b"x")
    z.writestr("b.xlsx", b"y")
check(raises(lambda: AK.unzip_one(two.getvalue(), "x")), "a zip of two files is not the export")
txt = io.BytesIO()
with zipfile.ZipFile(txt, "w") as z:
    z.writestr("a.csv", b"x")
check(raises(lambda: AK.unzip_one(txt.getvalue(), "x")), "a zip whose file is not an .xlsx is not the export")
book, made = AK.unzip_one(HIST_ZIP, "x")
check(made == date(2026, 10, 30) and book[:2] == b"PK", "the export's day is the zip member's date (2026-10-30)")
check(raises(lambda: AK.table(xlsx([["Api", "Permit"], ["1", "2"]]), AK.HISTORY_COLUMNS)), "a missing wanted column raises")
check(AK.excel_or_text_day("10/16/1963 12:00:00 AM") == date(1963, 10, 16) and AK.excel_or_text_day("44000") == date(2020, 6, 18) and AK.excel_or_text_day(None) is None
      and raises(lambda: AK.excel_or_text_day("sometime"), ValueError), "a date is the file's text, an Excel serial number, or nothing; anything else raises")

# ------------------------------------------------------------------------------------------------ the two readers
appr, issued, n = AK.read_history(book)
by_id = {x["id"]: x for x in POP.permits}
check(n == len(POP.hist) - 1, "every history row is counted (%d)" % n)
check(all(by_id[pid]["day"] == appr[pid][0] for pid in appr) and len(appr) == len(POP.permits) - 2, "one entry per permit approved since 2019 (the 1977 permit and the one of December 2018 are left out)")
two_ap = [x for x in POP.permits if x["day"] == date(2022, 3, 10)][0]["id"]
check(appr[two_ap][0] == date(2022, 3, 10), "a permit approved twice counts once, on its first approval")
check(not any(day.year < 2019 for day, _o, _c in appr.values()), "nothing approved before 2019 is kept")
pilot = [pid for pid, (d, o, c) in appr.items() if d == date(2019, 1, 5)][0]
check(appr[pilot][2] == "00", "a pilot hole's code (70) does not change the well's own code (the lowest of its rows is kept)")
check(len(issued) >= len(appr), "issue dates are read for the cross-check")
bad_api = [HIST_HEAD] + [[5002920001] + r[1:] for r in POP.hist[1:6]]
check(raises(lambda: AK.read_history(xlsx(bad_api))), "an approval since 2019 whose well number is not 14 digits means the layout changed")
bad_date = [r[:] for r in POP.hist[:6]]
bad_date[2][2] = "2026-W44"
check(raises(lambda: AK.read_history(xlsx(bad_date))), "an approval whose date is not a date means the layout changed")
bad_api2 = [r[:] for r in POP.hist[:6]]
bad_api2[1][0] = "5.0029E+13"
check(raises(lambda: AK.read_history(xlsx(bad_api2))), "a well number written as a float is refused")

ws, wn = AK.read_wells(xlsx(POP.wells))
check(wn == len(POP.wells) - 1 and len(ws) == len(POP.permits), "the Wells file has one entry per permit (%d rows read)" % wn)
check(ws[pilot][1] == "Development", "the pilot hole's row (no class) never replaces the well's row")
twice = [WELLS_HEAD, ["50223200357000", "220076", "T A PH", "No", HILCORP, "ARCTIC SLOPE", "", "", "", "", None, None, None, "No", "Exploratory", "Oil well, single completion", None, None, None],
         ["50223200350000", "220076", "T A", "No", HILCORP, "COOK INLET BASIN", "", "", "", "", None, None, None, "No", "Development", "Gas well, single completion", None, None, None]]
a1 = AK.read_wells(xlsx(twice))[0]["220076"]
a2 = AK.read_wells(xlsx([twice[0], twice[2], twice[1]]))[0]["220076"]
check(a1 == a2 == ("COOK INLET BASIN", "Development", "Gas well, single completion"), "a permit with two classed rows takes the lowest well number's, whatever order they come in")

# ------------------------------------------------------------------------------------------------ the bands, the places
check([AK.classify("00", c) for c in ("Development", "Exploratory", "Service", "Stratigraphic Test", "development ", None)] == ["new", "new", "inj", "other", "new", "other"], "original holes: Development and Exploratory are new wells, Service is injection, a stratigraphic test is other")
check([AK.classify(c, "Development") for c in ("01", "02", "60", "61", "95")] == ["redrill"] * 5 and AK.classify("60", "Service") == "redrill", "any sidetrack code but 00 is a re-drill, whatever the class")
check(AK.area_label("ARCTIC OCEAN, ST.") == "ARCTIC OCEAN (State)" and AK.area_label("PACIFIC OC., FED.") == "PACIFIC OC. (Federal)" and AK.area_label("Unknown") is None and AK.area_label(None) is None
      and AK.area_label("COOK INLET BASIN") == "COOK INLET BASIN", "areas: a comma is turned into a (State) or (Federal), 'Unknown' is no place")

# ------------------------------------------------------------------------------------------------ the whole build, against the oracle
AK.MIN_HISTORY_ROWS, AK.MIN_WELLS_ROWS, AK.MIN_APPROVALS = 100, 100, 100
net = Net()
doc = build(net)
check(net.asked == [AK.HISTORY_URL, AK.WELLS_URL] and all(u.startswith("https://aogcccdnstorage.blob.core.windows.net/dataminerzip/") for u in net.asked), "a run asks twice, history then wells, both over https from the Commission's storage")
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "AK" and doc["measure"] == "permits" and doc["basis"] == "approval date" and doc["place"] == "areas" and "unit" not in doc, "Alaska counts permits by approval date, its places are areas")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-27", "months run to the last complete month; October is open until a November approval exists")
exp = {b: {ym: 0 for ym in doc["months"]} for b in ("new", "inj", "redrill", "other")}
for x in POP.permits:
    ym = C.month_of(x["day"])
    if ym in doc["months"]:
        exp[x["band"]][ym] += 1
for b in exp:
    check(doc["bands"][b] == [exp[b][ym] for ym in doc["months"]], "band %s equals the oracle month by month (%d permits)" % (b, sum(doc["bands"][b])))
check(doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "recompletions and amendments are null: the file dates neither, never zero")
ix = {ym: i for i, ym in enumerate(doc["months"])}
check(exp["new"]["2022-03"] == 3 and exp["new"]["2022-05"] == 3 and doc["bands"]["new"][ix["2022-03"]] == 3 and doc["bands"]["new"][ix["2022-05"]] == 3, "the permit approved twice (March 10 and May 2) counts once, in March, and the permit re-issued in April counts once, in March: March 3, April and May unchanged")
check(sum(doc["bands"]["new"]) + sum(doc["bands"]["inj"]) + sum(doc["bands"]["redrill"]) + sum(doc["bands"]["other"]) == doc["read"] - 3, "every approval is in exactly one band (the 3 of October are read but their month is not shown)")
last12 = doc["months"][-12:]
fl = {"oil": 0, "gas": 0, "both": 0, "other": 0, "unknown": 0}
areas, ops, named = {}, {}, 0
total = 0
for x in POP.permits:
    if x["band"] == "new" and C.month_of(x["day"]) in last12:
        total += 1
        fl[x["fluid"] or "unknown"] += 1
        areas[AK.area_label(x["area"]).upper()] = areas.get(AK.area_label(x["area"]).upper(), 0) + 1
        if C.nameable(x["op"]):
            o = " ".join(x["op"].upper().replace(",", " ").split())
            ops[o] = ops.get(o, 0) + 1
            named += 1
check(doc["fluid"] == fl and fl["oil"] > 0 and fl["gas"] > 0 and fl["unknown"] > 0, "fluid is the well type on the permit (oil, gas, unknown when blank): %s" % doc["fluid"])
check({a: n for a, n in doc["counties"]} == {C.place_title(a): n for a, n in areas.items()} and doc["counties"][0][1] == max(areas.values()), "places are the areas of the last 12 months' new wells, ranked: %s" % doc["counties"])
check({a: n for a, n in doc["operators"]} == ops and [o for o, _n in doc["operators"]] == [o for o, _n in sorted(ops.items(), key=lambda kv: (-kv[1], kv[0]))], "operators are the companies of the last 12 months' new wells, ranked: %s" % doc["operators"])
check(PERSON.upper() not in json.dumps(doc).upper() and "SMITH" not in json.dumps(doc).upper() and "ACME" not in json.dumps(doc).upper(), "a person trading under a name is never named")
check(abs(doc["namedShare"] - round(named / total, 3)) < 1e-9 and 0 < doc["namedShare"] < 1, "namedShare is the share of new wells whose operator may be named (%s)" % doc["namedShare"])
text = json.dumps(doc)
check(not re.search(r"PRUDHOE|\b20\d{4}\b|\b50029\d+|ADL0|PH\b", text), "no well name, permit number, API number or lease reaches the file")
check(all(isinstance(v, int) for b in doc["bands"].values() if b for v in b), "every band holds whole counts")

# ------------------------------------------------------------------------------------------------ refusals: a file that is not the file
AK.MIN_HISTORY_ROWS, AK.MIN_WELLS_ROWS, AK.MIN_APPROVALS = 50000, 8000, 800
check(raises(lambda: build()), "with the real size floors a small file is refused (too few rows, too few approvals)")
AK.MIN_HISTORY_ROWS, AK.MIN_WELLS_ROWS, AK.MIN_APPROVALS = 50000, 100, 100
check(raises(lambda: build()), "a history of far fewer rows than the real one is refused on its own")
AK.MIN_HISTORY_ROWS, AK.MIN_WELLS_ROWS, AK.MIN_APPROVALS = 100, 50000, 100
check(raises(lambda: build()), "a Wells file of far fewer rows than the real one is refused on its own")
AK.MIN_HISTORY_ROWS, AK.MIN_WELLS_ROWS, AK.MIN_APPROVALS = 100, 100, 100
check(raises(lambda: build(Net(hist=export_zip(xlsx(POP.hist), when=(2026, 8, 1, 6, 0, 0))))), "a history export made more than 45 days ago is refused")
check(raises(lambda: build(Net(wells=export_zip(xlsx(POP.wells), when=(2026, 8, 1, 6, 0, 0))))), "a wells export made more than 45 days ago is refused")
check(raises(lambda: build(Net(hist=export_zip(xlsx(POP.hist), when=(2026, 12, 19, 6, 0, 0)), wells=export_zip(xlsx(POP.wells), when=(2026, 12, 19, 6, 0, 0))), today=date(2026, 12, 20))),
      "an export that is fresh but has no approval in 45 days (the newest is October 27) is refused as stalled")
check(build(Net(hist=export_zip(xlsx(POP.hist), when=(2026, 12, 3, 6, 0, 0)), wells=export_zip(xlsx(POP.wells), when=(2026, 12, 3, 6, 0, 0))), today=date(2026, 12, 4))["through"] == "2026-09-30",
      "an export made in December with the newest approval 38 days old is still read (a quiet spell is not an error)")
check(raises(lambda: build(today=date(2026, 10, 20))), "an approval dated after today is refused")
renamed = [HIST_HEAD[:6] + ["TypeOfWork"]] + [r[:] for r in POP.hist[1:5]]
check(raises(lambda: build(Net(hist=export_zip(xlsx(renamed))))), "a renamed column is refused")
renamed_event = [HIST_HEAD] + [r[:6] + [r[6].replace("Approved", "Granted")] for r in POP.hist[1:]]
check(raises(lambda: build(Net(hist=export_zip(xlsx(renamed_event))))), "a renamed approval event (no approvals found) is refused")
no_issue = [HIST_HEAD] + [r for r in POP.hist[1:] if r[6] != "Dt Well Permit Issued"]
check(raises(lambda: build(Net(hist=export_zip(xlsx(no_issue))))), "approvals with no issues to match (the event names changed) are refused")
class_col = WELLS_HEAD.index("PermittedClass")
no_class = [WELLS_HEAD] + [r[:class_col] + [None] + r[class_col + 1:] if i % 10 == 0 else r for i, r in enumerate(POP.wells[1:])]
check(raises(lambda: build(Net(wells=export_zip(xlsx(no_class))))), "more than 2% of the approvals losing their class is refused")
few_lost = [WELLS_HEAD] + [r for i, r in enumerate(POP.wells[1:]) if i != 1]
d2 = build(Net(wells=export_zip(xlsx(few_lost))))
check(C.validate(d2, TODAY) == [] and sum(d2["bands"]["other"]) == sum(doc["bands"]["other"]) + 1 and sum(d2["bands"]["new"]) == sum(doc["bands"]["new"]) - 1, "one approval with no class is read as other, not dropped (a few are tolerated)")
new_class = [WELLS_HEAD] + [r[:class_col] + ["Geothermal"] + r[class_col + 1:] if i == 3 else r for i, r in enumerate(POP.wells[1:])]
check(raises(lambda: build(Net(wells=export_zip(xlsx(new_class))))), "a well class the producer does not know is refused (it must be placed in a band on purpose)")
check(raises(lambda: build(Net(hist=HIST_ZIP[:200]))) and raises(lambda: build(Net(hist=b"<html>503</html>"))), "a cut-off or error-page download is refused")

# the history must not shrink against the committed file
now_totals = {ym: sum(doc["bands"][b][i] for b in ("new", "inj", "redrill", "other")) for i, ym in enumerate(doc["months"])}
check(build(old=now_totals)["bands"]["new"] == doc["bands"]["new"], "a run that matches the committed file passes the shrink check")
bigger = {ym: n * 3 for ym, n in now_totals.items()}
check(raises(lambda: build(old=bigger)), "a history that lost more than 10% of the permits the committed file holds is refused")
check(build(old={})["bands"] == doc["bands"], "with nothing committed there is nothing to compare")

# a refusal by the server is an answer
def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("AK", lambda: AK.build(get=refuse, pause=0, today=TODAY, old={}), tmp, argv=[]) == 2 and not os.path.exists(os.path.join(tmp, "AK.json")), "a refusal exits 2 and writes nothing")
    check(C.run_producer("AK", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "AK.json")), "run_producer writes nat/AK.json")
    check(C.run_producer("AK", lambda: doc, tmp, argv=["--check"]) == 0, "--check reloads and validates what is committed")
    before = open(os.path.join(tmp, "AK.json"), "rb").read()
    check(C.run_producer("AK", lambda: AK.build(get=Net(hist=b"junk").get, pause=0, today=TODAY, old={}), tmp, argv=[]) == 1 and open(os.path.join(tmp, "AK.json"), "rb").read() == before, "a failed run leaves the committed file as it was")
    again = build()
    check(json.dumps(again, sort_keys=True) == json.dumps(doc, sort_keys=True), "a second run over the same files gives the same document (deterministic)")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
