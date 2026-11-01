"""Tests for site/pipeline/d11_nat_wv.py: West Virginia's permits (DEP Office of Oil and Gas) from its Weekly Permit Reports.

The fixture is invented, written the way the archive is: one folder a year with an index of zips named "Weekly Permit Report MM-DD-YYYY.zip" (some with the typos the real names have: a wrong
year, a Sunday or a Tuesday for the Monday, two-digit years, "Weekly Report"), each zip holding a PDF and an Excel list of eight columns (API numbers, permit action, permit type, well type, well
number, operator, county) with one row per permit action. It pins: how a week's date is read from a messy name, the month a week is counted in, the band of each action and permit type (and that
Re-Work is a rework, a Modification an amendment, Cancelled and WR-35 left out), that the API number and well number are never read, the privacy rule on a person-named operator, a bootstrap
from nothing against a run that keeps the older months from the committed file (same document, far fewer requests), and that a damaged archive (too few reports, a stale newest report, many
missing or unreadable weeks, a renamed column, actions or types that no longer fit, a zip bomb, a year with too few permits) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_wv.py"""
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_wv as WV  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)
EXAMPLE, SAMPLE = "EXAMPLE GAS COMPANY LLC", "SAMPLE ENERGY LLC"
HEADER = ["API Number - 10 Digit", "API Number - 14 Digit", "Permit_Action", "Permit Type", "Well Type", "Well Number", "Operator", "County Name"]
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ the fixture
def xlsx(table):
    """An .xlsx as bytes (one sheet, inline strings): `table` is a list of rows of text."""
    out = []
    for r, row in enumerate(table, 1):
        cells = "".join('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (chr(65 + c), r, escape(v)) for c, v in enumerate(row) if v != "")
        out.append('<row r="%d">%s</row>' % (r, cells))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (MAIN, REL))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % REL)
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (MAIN, "".join(out)))
    return buf.getvalue()


def report_zip(rows, header=HEADER, extra=()):
    """A weekly report: the PDF (a stand-in) and the Excel list, in a zip. `rows` are dicts of the eight columns."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Weekly Permit Report.pdf", b"%PDF-1.4 stand-in")
        z.writestr("Weekly Permit Report.xlsx", xlsx([header] + [[r.get(h, "") for h in HEADER] for r in rows]))
        for name, data in extra:
            z.writestr(name, data)
    return buf.getvalue()


def row(action, ptype, wtype="Horizontal 6A", oper=EXAMPLE, county="Exampleton", n=0):
    return {"API Number - 10 Digit": "47901%05d" % n, "API Number - 14 Digit": "47901%05d0000" % n, "Permit_Action": action, "Permit Type": ptype, "Well Type": wtype, "Well Number": "EX %dH" % n, "Operator": oper,
            "County Name": county}


def week_rows(k):
    """What week number k (counted from the week of 2019-01-07) holds."""
    rows = [row("Issued", "New Drill", n=k)]  # one new well every week
    if k % 4 == 0:
        rows.append(row("Issued", "New Drill", oper=SAMPLE, county="Sampleville", n=k))
    if k % 6 == 0:
        rows.append(row("Issued", "New Drill", oper="SMITH, RICHARD", n=k))  # a person: counted, never named
    if k % 9 == 0:
        rows.append(row("Issued", "New Drill", oper="ROE, JANE DBA ROE OIL", n=k))
    rows += [row("Issued", "Plugging", "Vertical", SAMPLE, "Sampleville", n=k) for _ in range(3)]
    for every, ptype, wtype in ((8, "UIC Permit", "Vertical"), (13, "Drilling Deeper", "Horizontal"), (17, "Re-Drill", "Vertical"), (11, "Re-Work", "Vertical"), (19, "Fracture", "Vertical")):
        if k % every == 0:
            rows.append(row("Issued", ptype, wtype, n=k))
    if k % 2 == 0:
        rows.append(row("Modification", "New Drill", n=k))
    if k % 10 == 0:
        rows.append(row("Cancelled", "New Drill", n=k))  # left out
    if k % 5 == 0:
        rows.append(row("WR-35_approved", "Re-Work", "Vertical", n=k))  # left out
    return rows


FIRST_MONDAY = date(2019, 1, 7)
LAST_MONDAY = date(2026, 10, 19)
NOT_POSTED = (date(2023, 12, 25), date(2025, 5, 5), date(2025, 12, 15))  # three weeks the Office did not post (as in the real archive)
MESSY = {  # the real archive's kinds of typo in a name: the Monday and the name it carries
    date(2019, 4, 8): "Weekly Permit Report 04-08-2018.zip", date(2020, 10, 19): "Weekly Permit Report 10-18-2020.zip", date(2022, 10, 24): "Weekly Permit Report 10-25-2022.zip",
    date(2023, 8, 28): "Weekly Permit Report 08-25-2023.zip", date(2023, 9, 4): "Weekly Permit Report 09-04-23.zip", date(2020, 2, 17): "Weekly Report 02-17-2020.zip",
    date(2025, 9, 29): "Weekly Permit Report 09-27-2025.zip",
}


def mondays(first=FIRST_MONDAY, last=LAST_MONDAY):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=7)


def k_of(monday):
    return (monday - FIRST_MONDAY).days // 7


def name_of(monday):
    return MESSY.get(monday) or "Weekly Permit Report %02d-%02d-%d.zip" % (monday.month, monday.day, monday.year)


SPELT = {date(2022, 8, 15)}  # a week whose action column is headed "Permit Action", as one real report is
LOCKED = {date(2021, 11, 22)}  # a week whose zip also holds Word's lock file for the list, as one real report does
SWAPPED = {date(2019, 12, 2): "AT", date(2024, 3, 11): "TW", date(2025, 7, 7): "AT"}  # weeks served with two columns holding each other's values, as the real archive does sometimes


def swap_columns(rows, kind):
    one, two = ("Permit_Action", "Permit Type") if kind == "AT" else ("Permit Type", "Well Type")
    return [dict(r, **{one: r[two], two: r[one]}) for r in rows]


class Net:
    """The archive: a folder index for each year and a zip for each posted week. `bad` maps a Monday to the bytes served instead of its report; `rows` to other rows."""

    def __init__(self, gone=NOT_POSTED, last=LAST_MONDAY, bad=None, rows=None, header=HEADER, extra_entries=""):
        self.weeks = [m for m in mondays(last=last) if m not in gone]
        self.bad, self.rows, self.header, self.extra = bad or {}, rows or {}, header, extra_entries
        self.urls, self.cache = [], {}

    def index(self, year):
        lines = ['<a href="%s">%s</a>                02-Mar-2026 14:08              117502' % (name_of(m).replace(" ", "%20"), name_of(m)) for m in self.weeks if m.year == year]
        return '<html><head><title>Index of /Documents/OOG/WeeklyReports/%d/</title></head><body><pre><a href="../">../</a>\n%s\n%s</pre></body></html>' % (year, "\n".join(lines), self.extra)

    def get(self, url, **kw):
        self.urls.append(url)
        base = WV.ARCHIVE
        assert url.startswith(base), url
        rest = url[len(base):]
        if rest.endswith("/"):
            year = int(rest.strip("/"))
            if year > max(m.year for m in self.weeks):
                raise RuntimeError("could not read the source: HTTP Error 404")
            return self.index(year).encode()
        name = rest.split("/", 1)[1].replace("%20", " ")
        monday = next(m for m in self.weeks if name_of(m) == name)
        if monday in self.bad:
            return self.bad[monday]
        if monday not in self.cache:
            made = self.rows.get(monday) or week_rows(k_of(monday))
            head = [h if (h != "Permit_Action" or monday not in SPELT) else "Permit Action" for h in self.header]
            self.cache[monday] = report_zip(swap_columns(made, SWAPPED[monday]) if monday in SWAPPED else made, head, extra=[("~$Weekly Permit Report.xlsx", b"\x00lock")] if monday in LOCKED else ())
        return self.cache[monday]

    def zips(self):
        return [u for u in self.urls if not u.endswith("/")]


def build(net=None, today=TODAY, old=None, **kw):
    net = net or Net(**kw)
    return WV.build(get=net.get, today=today, pause=0, old={} if old is None else old), net


def expected(band, first="2019-02", through="2026-09"):
    """Month by month, what the fixture holds for a band, worked out from the fixture's own rules: a week counts in the month of its Wednesday."""
    count = {ym: 0 for ym in C.month_list(first, through)}
    for m in mondays():
        if m in NOT_POSTED:
            continue
        ym = C.month_of(m + timedelta(days=2))
        if ym not in count:
            continue
        k = k_of(m)
        count[ym] += {"new": 1 + (k % 4 == 0) + (k % 6 == 0) + (k % 9 == 0), "other": 3 + (k % 8 == 0), "redrill": (k % 13 == 0) + (k % 17 == 0), "rework": (k % 11 == 0) + (k % 19 == 0), "amend": k % 2 == 0}[band]
    return list(count.values())


# ------------------------------------------------------------------------------------------------ a week's date, from a messy name
def week_names(names, year):
    return [(d.isoformat()) for d, _h, _w in WV.entries("".join('<a href="%s">x</a> 02-Mar-2026 14:08 1\n' % n.replace(" ", "%20") for n in names), year)]


check(week_names(["Weekly Permit Report 01-07-2019.zip"], 2019) == ["2019-01-07"], "a Monday in the folder's year is the week")
check(week_names(["Weekly Permit Report 04-08-2018.zip"], 2019) == ["2019-04-08"], "a wrong year in the name (2018 in the 2019 folder) is corrected by the folder when that gives a Monday")
check(week_names(["Weekly Permit Report 01-06-2019.zip"], 2020) == ["2020-01-06"], "the same for a name that carries last year's date in January")
check(week_names(["Weekly Permit Report 10-18-2020.zip"], 2020) == ["2020-10-19"], "a Sunday is the Monday after it")
check(week_names(["Weekly Permit Report 10-25-2022.zip"], 2022) == ["2022-10-24"], "a Tuesday is the Monday before it")
check(week_names(["Weekly Permit Report 08-25-2023.zip"], 2023) == ["2023-08-28"] and week_names(["Weekly Permit Report 09-27-2025.zip"], 2025) == ["2025-09-29"], "a Friday or a Saturday is the Monday after it")
check(week_names(["Weekly Permit Report 09-04-23.zip"], 2023) == ["2023-09-04"] and week_names(["Weekly Report 02-17-2020.zip"], 2020) == ["2020-02-17"], "a two-digit year and the 'Weekly Report' name are read")
check(week_names(["Transfer Circular.zip", "Instruction for APPX Lookup.pdf", "Weekly Permit Report 02-30-2020.zip", "Weekly Permit Report 13-01-2020.zip"], 2020) == [], "other files and impossible dates are not weeks")
check(week_names(["Weekly Permit Report 01-02-2012.zip"], 2019) == [] and week_names(["Weekly Permit Report 01-07-2012.zip"], 2019) == ["2019-01-07"], "a name whose year is far from the folder's cannot put a week years away: it is dropped, or the folder's year is used when that gives a Monday")
e = WV.entries('<a href="Weekly%20Permit%20Report%2001-07-2019.zip">x</a>                02-Mar-2026 14:08              117502', 2019)
check(e[0][2].year == 2026 and e[0][1] == "Weekly%20Permit%20Report%2001-07-2019.zip", "the posting time is read, and the link kept as written")
check(WV.to_month(date(2024, 9, 30)) == "2024-10" and WV.to_month(date(2024, 10, 28)) == "2024-10" and WV.to_month(date(2024, 12, 30)) == "2025-01" and WV.to_month(date(2024, 12, 23)) == "2024-12",
      "a week is counted in the month that holds most of its days: Sep 30 to Oct 4 is October, Dec 30 to Jan 3 is January")

# ------------------------------------------------------------------------------------------------ the band of an action
b = WV.band_of
check(b("issued", "New Drill") == ("new", True) and b("issued", "  NEW   DRILL ") == ("new", True) and b("issued", "Vertical Well") == ("new", True) and b("issued", "Horizontal Well") == ("new", True),
      "a new-drill permit is a new well, in any case and spacing; so are the older labels of a new well")
check(b("issued", "UIC Permit") == ("other", True) and b("issued", "Brine Disposal") == ("other", True) and b("issued", "Secondary Recovery Well") == ("other", True), "UIC, disposal and secondary-recovery permits are other filings (the reports hold no injection band)")
check(b("issued", "Drilling Deeper") == ("redrill", True) and b("issued", "Re-Drill") == ("redrill", True) and b("issued", "Partial Plug Re-drill") == ("redrill", True), "deepening and re-drilling are re-entries")
check(b("issued", "Re-Work") == ("rework", True) and b("issued", "Fracture") == ("rework", True) and b("issued", "Convert") == ("rework", True), "Re-Work, Fracture and Convert are reworks (the shared words would call Re-Work a re-drill)")
check(b("issued", "Plugging") == ("other", True) and b("issued", "Partial Plug") == ("other", True) and b("issued", "General Permit") == ("other", True), "plugging and general permits are other filings")
check(b("modification", "New Drill") == ("amend", True) and b("modification", "Plugging") == ("amend", True) and b("modification", "Zebra") == ("amend", True), "a Modification is an amendment, whatever the permit's type")
check(b("cancelled", "New Drill") == (None, True) and b("wr-35_approved", "Re-Work") == (None, True) and b("wr-38_approved", "Plugging") == (None, True), "a cancelled permit and an approved completion or plugging report are left out")
check(b("issued", "Zebra Permit")[1] is False and b("issued", "Wildcat New Drill")[0] == "new", "a permit type in no table is read with the shared words and flagged")

# the columns of a row, told apart by what the values are
at = WV.action_and_type
R = lambda a, t, w: {"Permit_Action": a, "Permit Type": t, "Well Type": w}  # noqa: E731
check(at(R("Issued", "New Drill", "Horizontal 6A")) == ("issued", "New Drill") and at(R("WR-38_approved", "Plugging", "Vertical")) == ("wr-38_approved", "Plugging") and at(R("Cancelled", "Horizontal 6A Well", "Horizontal 6A")) == ("cancelled", "Horizontal 6A Well"),
      "a row in the columns' own order: the action, the permit type")
check(at(R("Horizontal 6A Well", "Cancelled", "Horizontal 6A")) == ("cancelled", "Horizontal 6A Well") and at(R("New Drill", "Issued", "Horizontal 6A")) == ("issued", "New Drill"), "the action and the permit type swapped (the real week of 2019-12-02 is all like this)")
check(at(R("Issued", "Horizontal 6A", "New Drill")) == ("issued", "New Drill") and at(R("Issued", "Vertical", "Plugging")) == ("issued", "Plugging") and at(R("WR-38_approved", "Not Available", "Plugging")) == ("wr-38_approved", "Plugging"),
      "the permit type and the well type swapped (a hundred real rows): the permit type is the one in the Office's list ('Not Available' is a well type here)")
check(at(R("Issued", "Zebra Permit", "Vertical")) == ("issued", "Zebra Permit") and at(R("Issued", "Vertical", "Zebra Permit")) == ("issued", "Zebra Permit"), "an unknown permit type is told from a well type either way round")
check(at(R("Transferred", "New Drill", "Vertical")) == (None, None) and at(R("Issued", "Cancelled", "Vertical")) == (None, None) and at(R("", "", "")) == (None, None) and at({}) == (None, None), "a row with no action, or two, is not understood")

# ------------------------------------------------------------------------------------------------ one report
rows = WV.read_week(report_zip([row("Issued", "New Drill", n=7), row("Issued", "Plugging", "Vertical", n=8)]))
check(len(rows) == 2 and set(rows[0]) == set(WV.WANT) and rows[0]["Permit Type"] == "New Drill" and rows[0]["County Name"] == "Exampleton", "a report gives its rows, with the five wanted columns")
check("API Number - 10 Digit" not in rows[0] and "Well Number" not in rows[0] and not any("47901" in str(v) or "EX 7H" in str(v) for r in rows for v in r.values()), "the API number and the well number are never read")


check(WV.read_week(report_zip([row("Issued", "New Drill")], header=[h if h != "Permit_Action" else "Permit Action" for h in HEADER]))[0]["Permit_Action"] == "Issued", "an action column headed 'Permit Action' (one real report) is read too")
check(len(WV.read_week(report_zip([row("Issued", "New Drill")], extra=[("~$Weekly Permit Report.xlsx", b"lock")]))) == 1, "Word's lock file beside the list (in one real report) is not taken for a second list")
no_action = WV.read_week(report_zip([row("Issued", "New Drill")], header=[h if h != "Permit_Action" else "Action" for h in HEADER]))
check(no_action[0]["Permit_Action"] is None, "with no action column at all a row has no action (and the run counts it as not understood)")


def fails(fn, text=None):
    try:
        fn()
        return False
    except RuntimeError as e:
        return text is None or text in str(e)
    except Exception as e:  # noqa: BLE001
        print("     unexpected %s: %s" % (type(e).__name__, str(e)[:80]))
        return False


check(fails(lambda: WV.read_week(b"<html>an error page</html>"), "not a zip"), "a reply that is not a zip fails")
check(fails(lambda: WV.read_week(report_zip([row("Issued", "New Drill")], extra=[("Second.xlsx", xlsx([HEADER]))]))), "a report with two Excel lists fails")
check(fails(lambda: WV.read_week(report_zip([row("Issued", "New Drill")], header=[h if h != "Operator" else "Company" for h in HEADER]), ), "cannot be read"), "a list that lost a wanted column (Operator renamed) fails")
bomb = io.BytesIO()
with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("big.xlsx", b"\0" * (WV.MAX_MEMBER + 1000))
check(fails(lambda: WV.read_week(bomb.getvalue()), "more than expected"), "a report that unpacks to more than the limit is refused before anything is unpacked")

# ------------------------------------------------------------------------------------------------ the committed file
with tempfile.TemporaryDirectory() as tmp:
    good = {"v": 1, "state": "WV", "measure": "permits", "months": ["2019-02", "2019-03"], "bands": {b_: ([1, 2] if b_ != "inj" else None) for b_ in C.BANDS}}
    p = os.path.join(tmp, "WV.json")
    json.dump(good, open(p, "w"))
    check(WV.previous(p) == {"2019-02": {b_: 1 for b_ in WV.TOLD}, "2019-03": {b_: 2 for b_ in WV.TOLD}}, "the committed file's months and bands are read (injection is null in it)")
    json.dump(dict(good, bands=dict(good["bands"], rework=None)), open(p, "w"))
    check(WV.previous(p) == {}, "a file with a band that is null where this producer writes numbers is not trusted")
    json.dump(dict(good, bands=dict(good["bands"], inj=[1, 2])), open(p, "w"))
    check(WV.previous(p) == {}, "nor one with an injection series (this producer never writes one)")
    json.dump(dict(good, state="KS"), open(p, "w"))
    open(os.path.join(tmp, "x.json"), "w").write("not json")
    check(WV.previous(p) == {} and WV.previous(os.path.join(tmp, "x.json")) == {} and WV.previous(os.path.join(tmp, "none.json")) == {}, "another state's file, a damaged file and no file give nothing")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked: from nothing
doc, net = build()
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "WV" and doc["measure"] == "permits" and doc["months"][0] == "2019-02" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-25",
      "permits by month from 2019-02 (the first report is the week of January 7) to the last complete month; asOf is the Sunday after the newest report's Monday")
for band in ("new", "redrill", "rework", "amend", "other"):
    check(doc["bands"][band] == expected(band), "%s: every month equals what the fixture holds (%d in the last 12)" % (band, sum(doc["bands"][band][-12:])))
check(doc["fluid"] is None and doc["bands"]["inj"] is None, "the reports record no fluid and hold no injection permits, so neither is shown (null, not zero)")
last12 = [m for m in mondays() if C.month_of(m + timedelta(days=2)) in C.month_list("2025-10", "2026-09") and m not in NOT_POSTED]
new_example = len(last12)
named = sum(1 for m in last12) + sum(1 for m in last12 if k_of(m) % 4 == 0)
total_new12 = sum(1 + (k_of(m) % 4 == 0) + (k_of(m) % 6 == 0) + (k_of(m) % 9 == 0) for m in last12)
check(doc["operators"] == [[EXAMPLE, new_example], [SAMPLE, sum(1 for m in last12 if k_of(m) % 4 == 0)]], "operators are companies only (a surname and a dba are not named): %s" % doc["operators"])
check(doc["namedShare"] == round(named / total_new12, 3), "the named share counts the person-named permits as new but not nameable: %s" % doc["namedShare"])
check(doc["counties"][0][0] == "Exampleton" and {c[0] for c in doc["counties"]} == {"Exampleton", "Sampleville"} and sum(c[1] for c in doc["counties"]) == total_new12, "the counties are those of the new-well permits only (plugging permits do not add places)")
blob = json.dumps(doc)
check(not any(s in blob for s in ("47901", "EX 1H", "SMITH", "ROE", "JANE", "RICHARD", "dba", "DBA")), "no API number, well number or person-named operator reaches the file")
check("Dec 25, 2023" in doc["note"] and "May 5, 2025" in doc["note"] and "Dec 15, 2025" in doc["note"], "the note lists the three weeks the Office did not post: %s" % doc["note"][-90:])
check("latest permit" in doc["note"] and "amendment" in doc["note"] and "Cancelled" in doc["note"] and "February 2019" in doc["note"] and "injection" in doc["note"], "the note says why the map layer is not the count, what an amendment is, what is left out, the missing injection band and where the series starts")
check(len(net.urls) == 8 + len(net.weeks) - sum(1 for m in net.weeks if C.month_of(m + timedelta(days=2)) < "2019-02") and net.urls[0] == WV.ARCHIVE + "2019/",
      "a bootstrap reads the eight folders' indexes and every report (%d requests)" % len(net.urls))

# ------------------------------------------------------------------------------------------------ with the committed file: only the window
old = {ym: {b_: doc["bands"][b_][i] for b_ in WV.TOLD} for i, ym in enumerate(doc["months"])}  # what WV.previous reads back from the committed file
doc2, net2 = build(old=old)
check(doc2 == doc, "with the older months kept from the committed file the document is identical")
keep_from = C.add_months(C.month_of(TODAY), -WV.REREAD_MONTHS)
check(len(net2.zips()) == sum(1 for m in net2.weeks if C.month_of(m + timedelta(days=2)) >= keep_from) and len(net2.zips()) < 70 and len(net2.urls) - len(net2.zips()) == 8,
      "and only the weeks of the last %d months are read again (%d reports, 8 indexes)" % (WV.REREAD_MONTHS + 1, len(net2.zips())))
doc3, net3 = build(old={ym: v for ym, v in old.items() if ym != "2024-06"})
check(doc3 == doc and len(net3.zips()) == len(net2.zips()) + sum(1 for m in net3.weeks if C.month_of(m + timedelta(days=2)) == "2024-06"),
      "a month missing from the committed file is read again from its reports, and nothing is counted twice")

# ------------------------------------------------------------------------------------------------ the archive's quirks
dd, nn = build(extra_entries='<a href="https://elsewhere.example/Weekly%20Permit%20Report%2001-14-2019.zip">x</a> 02-Mar-2026 14:08 1')
check(all(u.startswith(WV.ARCHIVE) for u in nn.urls) and dd == doc, "a link to another site in a listing is ignored (a listing is data, not instructions)")
two_gone = tuple(NOT_POSTED) + (date(2024, 3, 4),)
d4, n4 = build(gone=two_gone)
check("Mar 4, 2024" in d4["note"] and d4["bands"]["new"] != doc["bands"]["new"], "a further week the Office did not post is listed in the note and not counted")
jan, nj = build(net=Net(last=date(2026, 12, 28)), today=date(2027, 1, 10))
check(jan["through"] == "2026-12-31" and jan["asOf"] == "2027-01-03", "in the first days of January, when the new year's folder does not exist yet, the run still works")
check(fails(lambda: build(net=Net(last=date(2026, 12, 28)), today=date(2027, 3, 1)), "stale"), "but a newest report 9 weeks old fails the run (the archive stopped)")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
check(fails(lambda: build(net=Net(last=date(2019, 10, 28), gone=()), today=date(2019, 11, 5)), "layout may have changed"), "an archive that lists too few reports (39) fails the run")
many_gone = tuple(NOT_POSTED) + tuple(date(2022, 3, 7) + timedelta(days=7 * i) for i in range(6))
check(fails(lambda: build(gone=many_gone), "missing or cannot be read"), "more than %d weeks missing fails the run" % WV.MAX_MISSING)
two_bad = {date(2024, 5, 6): b"<html>error</html>", date(2024, 5, 13): b"\0\0"}
d5, n5 = build(bad=two_bad)
check("May 6, 2024" in d5["note"] and "May 13, 2024" in d5["note"], "two reports that cannot be read are skipped and listed like weeks not posted (a missing week, never a quiet zero)")
check(fails(lambda: build(bad={date(2024, 5, 6) + timedelta(days=7 * i): b"junk" for i in range(7)}), "missing or cannot be read"), "seven unreadable reports on top of the missing ones fail the run")
check(fails(lambda: build(header=[h if h != "County Name" else "County" for h in HEADER]), "missing or cannot be read"), "a column renamed in every report makes every report unreadable and fails the run")
odd_rows = {m: [row("Approved", "New Drill", n=1) for _ in range(5)] + week_rows(1) for m in mondays(date(2023, 1, 2), date(2023, 12, 18))}
check(fails(lambda: build(rows=odd_rows), "not understood"), "a new kind of action in more than 2% of the rows fails the run")
new_types = {m: [row("Issued", "Zebra Permit", n=1) for _ in range(5)] + week_rows(1) for m in mondays(date(2023, 1, 2), date(2023, 12, 18))}
check(fails(lambda: build(rows=new_types), "types"), "permit types in no table, in more than 5% of the issued permits, fail the run")
thin = {m: [row("Issued", "New Drill", n=1)] for m in mondays(date(2021, 1, 4), date(2021, 12, 27))}
check(fails(lambda: build(rows=thin), "2021"), "a year with a handful of permits fails the run and names the year")


def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


check(fails(lambda: WV.build(get=refuse, today=TODAY, pause=0, old={}), "403"), "a refusal is not swallowed by the 'folder may not exist' or 'unreadable report' handling")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("WV", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "WV.json")) and C.check_dir(tmp) == [], "run_producer writes nat/WV.json for it, and it reloads clean")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("WV", lambda: WV.build(get=refuse, today=TODAY, pause=0, old={}), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal (HTTP 403) exits 2 and writes nothing")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("WV", lambda: build(net=Net(last=date(2019, 10, 28), gone=()), today=date(2019, 11, 5))[0], tmp, argv=[]) == 1 and not os.listdir(tmp), "a failed run exits 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
