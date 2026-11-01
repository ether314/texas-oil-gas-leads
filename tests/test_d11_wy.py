"""Tests for site/pipeline/d11_nat_wy.py: Wyoming's approved APDs from the Commission's "Download Approved" export.

The fixtures are invented rows written the way the real export has them (an HTML table, the 48 real column names with the header's cells before the first <tr>, `&nbsp;` in cells, a padded API
number, `Approved` as yyyymmdd, a reply that ends with </Table>); no real well, lease, operator or person is in them. The network and the clock are faked. What is pinned: the parser, the
request (one per calendar year, from 2019), the well classes in the Commission's own codes (O and G are new wells, injection, disposal, monitor, storage and source wells are `inj`, a test hole
is `other`), the repeated-row rule, a person or a dba never named, nothing but counts in the output, the pauses between requests, and every way a short, cut-off, renamed or
mis-dated reply must fail the run instead of writing a short file.

Run: python3 -I tests/test_d11_wy.py"""
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_wy as WY  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
PM = 8  # approvals a month in the fixtures


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


# ------------------------------------------------------------------------------------------------ fixtures (invented)
COLUMNS = ("Api_Number,Confid,Company,Approved,Well_NO,Unit_Lease,Qtr1,Qtr2,Section,Lot_Tract,Township,Range,Foot1,Foot2,Elevation,Elev_KB,Latitude,Longitude,Lease_No,Field,County,Status,Status_Dte,"
           "Form2_Stat,Form2_Date,Well_Class,TD,PB,Bot_Form,Spud_Date,Comp_Date,Oil,Gas,Water,BFoot1,BFoot2,BSec,BQtr1,BQtr2,BTwp,BT_Dir,BRge,BR_Dir,Dir/Hor,Blat,Blon,Rcvd.Date,MineralCode").split(",")
assert len(COLUMNS) == 48
# the build tests use the five columns that are read and five that must never reach the output (the real export has all 48: the parser tests below use them); fewer cells make the tests fast
SLIM = ["Api_Number", "Company", "Approved", "County", "Well_Class", "Well_NO", "Unit_Lease", "Lease_No", "Latitude", "Longitude"]
OPS = ["Acme Drilling LLC", "Example Energy Corporation", "Pat Q Sample", "Jane Roe dba Roe Oil"]
COUNTIES = ["Converse", "Campbell", "Sublette"]


def header_cells(columns=SLIM):
    return "".join('<td valign="Middle" align="center" nowrap >%s</td> \n' % c for c in columns)


def row_html(api, approved, company, county, wclass, columns=SLIM):
    vals = {c: "&nbsp;" for c in columns}
    vals.update({"Api_Number": api + " ", "Confid": "N", "Company": company, "Approved": approved, "Well_NO": "99-99H&nbsp;", "Unit_Lease": "Sample Fed", "Section": "12", "Township": "42N",
                 "Range": " 73W", "Latitude": "43.123456", "Longitude": "-105.123456", "Lease_No": "WYW999999", "County": county, "Status": "AP", "Status_Dte": "10/12/2026", "Well_Class": wclass,
                 "Rcvd.Date": "20260318", "Dir/Hor": "H"})
    return "<tr>\n" + "".join('<td valign="Middle" align="left" nowrap bgcolor=FBFCA2 >%s</td>\n\n' % vals[c] for c in columns) + "\n\n</tr>\n"


def table(rows, columns=SLIM):
    return ('\n<Table width = "150%">\n' + header_cells(columns) + "\n\n" + "".join(rows) + "\n</Table>\n").encode("utf-8")


def year_rows(year, per_month=PM, last_month=12, last_day=28, extras=(), start=0):
    """per_month approvals every month of `year` (up to last_month, whose days stop at last_day): classes O, O, G, then O ..., plus any extras (wclass, month)."""
    rows, k = [], start
    for m in range(1, last_month + 1):
        for j in range(per_month):
            day = min(1 + (k * 5) % 27, last_day if m == last_month else 28)
            rows.append(row_html("49-999-%05d" % (year * 10 + k % 10 + 1000 * (k // 10)), "%04d%02d%02d" % (year, m, day), OPS[k % 4], COUNTIES[k % 3], ("O", "O", "G")[j % 3]))
            k += 1
    for n, (wclass, m) in enumerate(extras):
        rows.append(row_html("49-998-%05d" % (year * 10 + n), "%04d%02d10" % (year, m), OPS[0], "Converse", wclass))
    return rows


def years(today=TODAY, per_month=PM, extras_2026=(), **kw):
    """{year: reply bytes} for 2019 to today's year; the current year stops in the month before today's... on the 20th of today's month."""
    out = {}
    for y in range(2019, today.year + 1):
        if y == today.year:
            out[y] = table(year_rows(y, per_month, last_month=today.month, last_day=20, extras=extras_2026, **kw))
        else:
            out[y] = table(year_rows(y, per_month, **kw))
    return out


class Net:
    def __init__(self, replies):
        self.replies = replies
        self.asked = []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_bytes"), kw.get("timeout")))
        year = int(url.split("byear=")[1][:4])
        return self.replies[year]


REAL = (WY.MIN_ROWS, WY.MIN_ROWS_A_YEAR)


def small_floors():
    WY.MIN_ROWS, WY.MIN_ROWS_A_YEAR = 100, 10


def real_floors():
    WY.MIN_ROWS, WY.MIN_ROWS_A_YEAR = REAL


# ------------------------------------------------------------------------------------------------ the parser
rows = WY.parse_export(table([row_html("49-999-00001", "20260903", "Acme Drilling LLC", "Niobrara", "O", COLUMNS), row_html("49-999-00002", "20260904", "Example Energy Corporation", "Converse", "G", COLUMNS)], COLUMNS))
check(len(rows) == 2 and set(rows[0]) == set(WY.NEEDED), "the real export's 48 columns: the parser keeps only the columns it needs, so no well name, lease, coordinate or footage is held")
check(rows[0] == {"Api_Number": "49-999-00001", "Company": "Acme Drilling LLC", "Approved": "20260903", "County": "Niobrara", "Well_Class": "O"}, "a row's cells are trimmed (the padded API number, nbsp)")
check(WY.parse_export(table([])) == [], "the table with no rows reads as no rows")
check(WY.parse_export(table([row_html("49-999-00001", "20260903", "Acme LLC", "Converse", "O")]).replace(b"</Table>", b"</TABLE>\r\n\r\n")) != [], "the closing tag may be in any case, with trailing blanks")
cut = table([row_html("49-999-00001", "20260903", "Acme LLC", "Converse", "O")])
check(raises(lambda: WY.parse_export(cut[:-60]), ValueError), "a reply cut off before its closing </Table> is refused")
check(raises(lambda: WY.parse_export(b"<html><body>The server is busy, try again later.</body></html>"), ValueError), "an error page is refused")
check(raises(lambda: WY.parse_export(b"<html><body>No records found</Table></body></html>"), ValueError), "a page with no table of the needed columns is refused")
renamed = table([row_html("49-999-00001", "20260903", "Acme LLC", "Converse", "O")], [("Date_Approved" if c == "Approved" else c) for c in SLIM])
msg = raises(lambda: WY.parse_export(renamed), ValueError)
check(msg and "Approved" in msg and "layout" in msg, "a renamed column fails loudly and says which: %s" % msg)
short = [row_html("49-999-%05d" % i, "20260903", "Acme LLC", "Converse", "O") for i in range(200)] + ["<tr><td>a</td><td>b</td></tr>"] * 30
check(raises(lambda: WY.parse_export(table(short)), ValueError), "rows that do not have the header's width (the layout changed) fail the run")
check(len(WY.parse_export(table(short[:200] + ["<tr><td>a</td></tr>"]))) == 200, "one stray short row is dropped, not fatal")
check(WY.export_url(date(2019, 1, 1), date(2019, 12, 31)) == "https://pipeline.wyo.gov/DumpByApdA.cfm?bmon=01&bday=01&byear=2019&emon=12&eday=31&eyear=2019&cType=1",
      "the request asks for a calendar year of every well class")

# ------------------------------------------------------------------------------------------------ the classes, in the Commission's own codes
CASES = [("O", ("new", "oil")), ("G", ("new", "gas")), ("OG", ("new", "both")), ("GO", ("new", "both")), ("05", ("new", "gas")), ("o", ("new", "oil")), ("I", ("inj", "other")), ("D", ("inj", "other")),
         ("M", ("inj", "other")), ("MW", ("inj", "other")), ("GS", ("inj", "other")), ("WS", ("inj", "other")), ("ST", ("other", None))]
for code, want in CASES:
    got = WY.classify(code)
    check(got == want + (True,), "class %r is %s, known" % (code, want))
check(WY.classify("") == ("other", None, False) and WY.classify("ZZ") == ("other", None, False), "a blank or new class is `other` and flagged as not known (never a new well)")

# ------------------------------------------------------------------------------------------------ the whole run, network faked
small_floors()
sleeps = []
real_sleep = WY.time.sleep
WY.time.sleep = sleeps.append
net = Net(years(extras_2026=(("D", 5), ("I", 5), ("M", 5), ("ST", 5), ("GS", 6))))
doc = WY.build(get=net.get, pause=5.0, today=TODAY)
WY.time.sleep = real_sleep
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(doc["state"] == "WY" and doc["measure"] == "permits" and doc["basis"].startswith("approval date") and doc["cadence"] == "daily" and doc["unit"] == "APDs approved", "Wyoming counts APDs approved, by approval date")
check([u.split("byear=")[1][:4] for u, _, _ in net.asked] == [str(y) for y in range(2019, 2027)], "one request per calendar year from 2019 to this year")
check(net.asked[-1][0].endswith("emon=10&eday=31&eyear=2026&cType=1") and net.asked[0][0].startswith(WY.EXPORT + "?bmon=01&bday=01&byear=2019&emon=12&eday=31"), "the current year's request ends today, the earlier ones on December 31")
check(all(m == WY.MAX_BYTES and t == WY.TIMEOUT for _, m, t in net.asked) and WY.MAX_BYTES <= 60_000_000, "each request has a size cap and a timeout")
check(sleeps == [5.0] * 7, "a pause between requests, none before the first: %s" % sleeps)
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] <= "2026-10-20", "2019 to the newest complete month; October (to the 20th) is not shown")
check(doc["bands"]["new"][0] == PM and doc["bands"]["new"][1] == PM and all(v == PM for i, v in enumerate(doc["bands"]["new"]) if doc["months"][i] not in ("2026-05", "2026-06")), "%d new-well approvals a month" % PM)
i5, i6 = doc["months"].index("2026-05"), doc["months"].index("2026-06")
check(doc["bands"]["inj"][i5] == 3 and doc["bands"]["inj"][i6] == 1 and doc["bands"]["other"][i5] == 1 and sum(doc["bands"]["other"]) == 1 and sum(doc["bands"]["inj"]) == 4,
      "May 2026: a disposal, an injection and a monitor well are inj, the test hole is other; June's storage well is inj")
check(doc["bands"]["redrill"] is None and doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "re-entries, reworks and amendments cannot be told: null, never zero")
check(doc["read"] == PM * 12 * 7 + PM * 10 + 5, "every approval is read once, October's included: %d" % doc["read"])
check(doc["fluid"] is not None and doc["fluid"]["oil"] + doc["fluid"]["gas"] == sum(doc["bands"]["new"][-12:]) and doc["fluid"]["both"] == 0 and doc["fluid"]["unknown"] == 0, "fluid of the last 12 months from the class: %s" % doc["fluid"])
check({c[0] for c in doc["counties"]} == set(COUNTIES), "the counties come from the export")
names = [o[0] for o in doc["operators"]]
check(sorted(names) == ["ACME DRILLING LLC", "EXAMPLE ENERGY CORPORATION"], "only the corporation and the LLC are named: %s" % names)
check(0.45 < doc["namedShare"] < 0.55, "half of the permits' companies are a person or a dba and are not named: %s" % doc["namedShare"])
text = json.dumps(doc)
check("PAT Q" not in text.upper() and "ROE OIL" not in text.upper() and "JANE" not in text.upper(), "a person's name and a dba never reach the file")
check(all(x not in text for x in ("Sample Fed", "WYW999999", "49-99", "99-99H", "43.1234", "105.1234", "42N")), "no well, unit, lease, API number or coordinate reaches the file")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("WY", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "WY.json")) and C.check_dir(tmp) == [], "run_producer writes nat/WY.json and it reloads clean")

# a repeated row is one approval; the same well approved again on another day is another
rep = years()
extra = row_html("49-997-00001", "20250210", "Acme Drilling LLC", "Converse", "O")
rep[2025] = table(year_rows(2025) + [extra, extra])
base = WY.build(get=Net(years()).get, pause=0, today=TODAY)
d2 = WY.build(get=Net(rep).get, pause=0, today=TODAY)
check(d2["read"] == base["read"] + 1 and d2["bands"]["new"][d2["months"].index("2025-02")] == base["bands"]["new"][base["months"].index("2025-02")] + 1, "a row the export repeats is counted once")
rep[2025] = table(year_rows(2025) + [extra, row_html("49-997-00001", "20250310", "Acme Drilling LLC", "Converse", "O")])
d3 = WY.build(get=Net(rep).get, pause=0, today=TODAY)
check(d3["read"] == base["read"] + 2, "the same API number approved on another day (a renewal) is counted again, as the Commission counts it")

# a month with no approval inside the series is a real zero
rep = years()
rep[2021] = table([r for r in year_rows(2021) if "202103" not in r])
d4 = WY.build(get=Net(rep).get, pause=0, today=TODAY)
check(d4["bands"]["new"][d4["months"].index("2021-03")] == 0 and d4["bands"]["new"][d4["months"].index("2021-02")] == PM, "a month with no approval inside the series is a zero, not a gap")

# the first days of a year: the new year's export may hold nothing yet
rep = years(today=date(2026, 12, 31))
rep[2027] = table([])
d5 = WY.build(get=Net(rep).get, pause=0, today=date(2027, 1, 8))
check(d5["through"] == "2026-11-30" and C.validate(d5, date(2027, 1, 8)) == [], "on January 8 an empty new-year reply is not an error (the series ends with the newest complete month)")
rep[2027] = b"<html><body>No records found.</body></html>"
d6 = WY.build(get=Net(rep).get, pause=0, today=date(2027, 1, 8))
check(d6["through"] == "2026-11-30", "nor is a plain 'no records' page in those days")
check(raises(lambda: WY.build(get=Net(rep).get, pause=0, today=date(2027, 3, 8)), ValueError), "but in March the same page is refused")

# ------------------------------------------------------------------------------------------------ failures: the run fails, nothing short is written
def boom(replies=None, today=TODAY, **swap):
    r = dict(replies or years())
    r.update(swap)
    return raises(lambda: WY.build(get=Net(r).get, pause=0, today=today), Exception)


msg = boom(replies={**years(), 2022: b"<html>maintenance</html>"})
check(msg, "an error page in place of one year fails the run: %s" % msg)
msg = boom(replies={**years(), 2023: years()[2023][:-80]})
check(msg and "cut off" in msg, "a year cut off in the middle fails the run: %s" % msg)
msg = boom(replies={**years(), 2024: table(year_rows(2024, per_month=0))})
check(msg and "fewer than" in msg and "2024" in msg, "a year with too few approvals (a short reply) fails the run and names the year: %s" % msg)
r = years()
r[2020] = table([(x.replace(">2020", ">2021") if i < 40 else x) for i, x in enumerate(year_rows(2020))])
msg = boom(replies=r)
check(msg and "outside the year asked" in msg, "approval dates outside the year asked (a changed date format or range) fail the run: %s" % msg)
r = years()
r[2020] = table([x.replace(">2020", ">20-20-") for x in year_rows(2020)])
check(boom(replies=r), "dates that do not parse fail the run")
r = years(extras_2026=tuple(("ZZ", 4) for _ in range(40)))
msg = boom(replies=r)
check(msg and "does not know" in msg and "ZZ" in msg, "more than a few unknown well classes fail the run (a renamed class must not become `other` quietly): %s" % msg)
r = years(extras_2026=(("ZZ", 4),) * 3)
d7 = WY.build(get=Net(r).get, pause=0, today=TODAY)
check(sum(d7["bands"]["other"]) == 3 and sum(d7["bands"]["new"][-12:]) == sum(base["bands"]["new"][-12:]), "a few unknown classes are counted as other, never as new wells")
check(boom(replies=years(today=date(2026, 4, 30)), today=date(2026, 10, 31)), "an export whose newest approval is months old (it stopped being refreshed) fails the run")
real_floors()
msg = boom()
check(msg and ("expected" in msg or "fewer than" in msg), "with the real floors a small export is refused as too short: %s" % msg)
small_floors()


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("WY", lambda: WY.build(get=refused, pause=0), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing (an answer, not an error)")
    check(C.run_producer("WY", lambda: WY.build(get=Net({**years(), 2021: b"<html>x"}).get, pause=0, today=TODAY), tmp, argv=[]) == 1 and not os.listdir(tmp), "a bad reply exits 1 and writes nothing")
real_floors()

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
