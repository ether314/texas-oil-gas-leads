"""Tests for site/pipeline/d11_nat_ms.py: Mississippi's oil and gas permits (State Oil and Gas Board) from its Permit Search register.

The fixtures are an invented register shaped like the real reply of the Board's /ajaxloadPDO.php (JSON, a `data` list of rows [approval date, permit number, well number, operator, county, permit
type], `recordsTotal`), an invented well list (the Board's CSV: a header with API10 and Type, "OIL - Production", "DH - Dry Hole", "MON - Monitor/Observation"...), a Downloads page, the folder of
yearly sheets and the text of the sheets' chart captions. They pin: the one query that is sent (fixed text, two dates, six columns), every permit type's band (an original permit to drill for a
service or monitor well counts as injection), a permit counted once, the monitor wells that the Board's sheet leaves out, the months and the two-week lag, counties, operators (a person is not
named), fluid, nulls for the band the codes cannot tell, that no well number, permit number or well-list column reaches the file, every way the register, the well list or the Downloads page can come
back wrong (each fails the run instead of writing a short or odd file), and the check against the Board's yearly sheets (agreement, the tolerance, a disagreement that stops the run, a sheet that
cannot be read costing only the check, the year under way never compared). The network is faked.

Run: python3 -I tests/test_d11_ms.py"""
import base64
import io
import json
import os
import sys
import tempfile
import urllib.error
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_ms as MS  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


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


# ------------------------------------------------------------------------------------------------ fixtures
# the well list: the Board's CSV has 30 columns; the producer needs API10 and Type
WELLS = {
    "2300000001": "OIL - Production", "2300000002": "GAS - Natural Gas - Production", "2300000003": "DH - Dry Hole", "2300000004": "SWD - Water Injection - Disposal",
    "2300000005": "MON - Monitor/Observation", "2300000006": "EOR - Enhanced Oil Recovery - Injection", "2300000007": "ST - Stratigraphic", "2300000008": "GSCH - Gas Storage Cavern for Hydrogen",
    "2300000009": "CO2 - Carbon Dioxide - Production", "2300000010": "OIL - Production", "2300000011": "EX - Expired Location",
    "2300000021": "MON - Monitor/Observation", "2300000022": "MON - Monitor/Observation", "2300000023": "MON - Monitor/Observation", "2300000024": "MON - Monitor/Observation",
    "2300000025": "MON - Monitor/Observation", "2300000031": "OIL - Production", "2300000032": "OIL - Production", "2300000033": "OIL - Production", "2300000034": "OIL - Production",
}
HEADER = "API14,API10,Type,Status,Name,Number,Oper,County,Lat(NAD83),Long(NAD83)"


def well_csv(wells=WELLS, header=HEADER):
    lines = [header]
    for api, typ in wells.items():
        lines.append("%s0000,%s,%s,PR - Producing,LEASE %s,# 1,SOME OPERATOR INC.,ADAMS,31.45,-91.32" % (api, api, typ, api[-3:]))
    return ("\n".join(lines) + "\n").encode()


def row(day, number, well, operator, county, code):
    return [day, number, well, operator, county, code]


ALPHA, BETA = "ALPHA OPERATING, LLC", "BETA ENERGY, INC."
REGISTER = [
    # 2024: three new wells and five original permits for monitor wells (the Board's sheet counts the three)
    row("2024-11-05", "2025-OPD-0001", "2300000001", ALPHA, "ADAMS", "OPD"),
    row("2024-11-20", "2025-OPD-0002", "2300000002", BETA, "JONES", "OPD"),
    row("2024-12-02", "2025-OPD-0003", "2300000010", ALPHA, "ADAMS", "OPD"),
] + [row("2024-12-10", "2025-OPD-00%d" % (10 + i), "23000000%d" % (21 + i), ALPHA, "YAZOO", "OPD") for i in range(5)] + [
    # 2025
    row("2025-01-10", "2025-OPD-0101", "2300000001", ALPHA, "ADAMS", "OPD"),  # new, oil
    row("2025-01-12", "2025-OPD-0102", "2300000002", BETA, "JONES", "OPD"),  # new, gas
    row("2025-02-03", "2025-OPD-0103", "2300000003", ALPHA, "ADAMS", "OPD"),  # new; a dry hole now: fluid unknown
    row("2025-02-04", "2025-OPD-0104", "2300000004", "GAMMA DISPOSAL, LLC", "WAYNE", "OPD"),  # an OPD for a disposal well: injection
    row("2025-02-10", "2025-OPI-0105", "2300000006", "DELTA ENERGY, LP", "WAYNE", "OPI"),  # injection by its code
    row("2025-03-05", "2025-OPD-0106", "2300000005", ALPHA, "YAZOO", "OPD"),  # a monitor well: injection, and one the Board's sheet leaves out
    row("2025-03-06", "2025-OPD-0107", "", "EPSILON PETROLEUM, INC.", "PIKE", "OPD"),  # no well number: new by its code
    row("2025-03-07", "2025-OPD-0108", "2300000009", "ZETA CARBON, LLC", "ADAMS", "OPD"),  # new
    row("2025-04-01", "2025-OPDC-0109", "2300000001", ALPHA, "ADAMS", "OPDC"), row("2025-04-02", "2025-WOP-0110", "2300000001", ALPHA, "ADAMS", "WOP"),
    row("2025-04-03", "2025-CIP-0111", "2300000004", ALPHA, "ADAMS", "CIP"), row("2025-04-04", "2025-WOIH-0112", "2300000004", ALPHA, "ADAMS", "WOIH"),
    row("2025-04-04", "2025-OPDT-0113", "2300000001", ALPHA, "ADAMS", "OPDT"),
    row("2025-05-01", "2025-COP-0114", "2300000001", BETA, "ADAMS", "COP"), row("2025-05-01", "2025-COI-0115", "2300000004", BETA, "ADAMS", "COI"),
    row("2025-05-02", "2025-COP-0116", "2300000002", BETA, "JONES", "COP"),
    row("2025-06-01", "2025-H2S-0117", "2300000001", ALPHA, "", "H2S"), row("2025-06-02", "2025-PIT-0118", "", ALPHA, "", "PIT"), row("2025-06-03", "2025-ZZZ-0119", "2300000001", ALPHA, "ADAMS", "ZZZ"),
    row("2025-07-01", "2025-OPD-0120", "2300000007", "EPSILON PETROLEUM, INC.", "PIKE", "OPD"),
    row("2025-07-01", "2025-OPD-0120", "2300000007", "EPSILON PETROLEUM, INC.", "PIKE", "OPD"),  # the same permit twice: counted once
    # 2026
    row("2026-01-15", "2026-OPD-0201", "2300000031", ALPHA, "ADAMS", "OPD"), row("2026-01-20", "2026-OPD-0202", "2300000002", BETA, "JONES", "OPD"),
    row("2026-02-10", "2026-OPD-0203", "2300000032", ALPHA, "ADAMS", "OPD"), row("2026-03-03", "2026-OPI-0204", "2300000008", "HUB ENERGY, LLC", "SIMPSON", "OPI"),
    row("2026-09-15", "2026-OPD-0205", "2300000033", "LAMBDA OIL &amp; GAS, LLC", "ADAMS", "OPD"),
    row("2026-10-20", "2026-OPD-0206", "2300000034", ALPHA, "ADAMS", "OPD"),  # October: not a complete month yet
    row("2026-10-20", "2026-COP-0207", "2300000001", ALPHA, "ADAMS", "COP"),  # the newest permit
]
UNIQUE = len(REGISTER) - 1  # one permit is listed twice
EXTRA = [  # the last 12 months with every kind of well type, and two operators that may not be named
    row("2026-08-05", "2026-OPD-0301", "2300000003", ALPHA, "ADAMS", "OPD"), row("2026-08-06", "2026-OPD-0302", "2300000007", ALPHA, "ADAMS", "OPD"),
    row("2026-08-07", "2026-OPD-0303", "2300000009", ALPHA, "ADAMS", "OPD"), row("2026-08-08", "2026-OPD-0304", "", ALPHA, "ADAMS", "OPD"),
    row("2026-08-09", "2026-OPD-0305", "2300000011", ALPHA, "ADAMS", "OPD"),
    row("2026-09-16", "2026-OPD-0306", "2300000031", "JOHN Q PUBLIC", "ADAMS", "OPD"), row("2026-09-17", "2026-OPD-0307", "2300000031", "WILLIAMS PRODUCING CO", "ADAMS", "OPD"),
]
SMALL = dict(min_rows=5, min_wells=5)


def reply(rows=REGISTER, total=None):
    return json.dumps({"draw": 1, "start": 0, "recordsTotal": len(rows) if total is None else total, "recordsFiltered": len(rows), "data": rows}).encode()


DOWNLOADS = ('<table><tr><td><a href="/Downloads/WellInfoList/20261030_All_WellInfoList.csv">20261030_All_WellInfoList.csv</a></td></tr>'
             '<tr><td><a href="/Downloads/WellInfoList/20261029_All_WellInfoList.csv">20261029_All_WellInfoList.csv</a></td></tr>'
             '<tr><td><a href="/Downloads/ProdInfo/20261031_All_ProdInfo.csv">20261031_All_ProdInfo.csv</a></td></tr></table>')
LISTING = '<ul class="ogb-file-tree">' + "".join(
    '<li class="tree-file ext-pdf"><a href="/MSOGBDocumentsShared/monthlypermits/Permit%%20to%%20Drill%%20Monthly%%20%d.pdf" target="_blank" rel="noopener">Permit to Drill Monthly %d.pdf</a></li>' % (y, y)
    for y in range(2026, 2018, -1)) + "</ul>"
SHEET_URL = MS.BASE + "/MSOGBDocumentsShared/monthlypermits/Permit%%20to%%20Drill%%20Monthly%%20%d.pdf"
# what pdftotext gives for a sheet (the real caption: "Total 2024 = 50 ... Total 2025 = 37"); the fake fetch returns b"PDF<year>"
SHEET_TEXT = {
    b"PDF2026": "PERMITS TO DRILL 2026\n  Jan  Feb\nTotal   2  1\n     0\n       Jan  Feb  Mar\n                    Total 2025 = 8                    Total 2026 = 2\n",
    b"PDF2025": "PERMITS TO DRILL 2025\n  Jan  Feb\nTotal   4  3\n       Jan  Feb  Mar\n                    Total 2024 = 3                    Total 2025 = 8\n",
}


def net(register=None, wells=None, downloads=None, listing=None, sheets=None, post_error=None):
    """Fake get / post / to_text. A value that is an Exception is raised in place of the reply."""
    seen = []
    texts = SHEET_TEXT if sheets is None else sheets
    reg = reply() if register is None else register
    csvb = well_csv() if wells is None else wells
    dl = DOWNLOADS if downloads is None else downloads
    lst = LISTING if listing is None else listing

    def pick(value):
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, bytes) else value.encode()

    def get(url, **kw):
        seen.append(url)
        if url == MS.DOWNLOADS:
            return pick(dl)
        if url.startswith(MS.BASE + "/Downloads/WellInfoList/"):
            return pick(csvb)
        if url == MS.SHEETS:
            return pick(lst)
        if "Monthly%20" in url:
            if isinstance(texts, Exception):
                raise texts
            return b"PDF" + url.rsplit("%20", 1)[-1][:4].encode()
        raise AssertionError("an address nobody expected: " + url)

    def post(url, fields, **kw):
        seen.append(("POST", url, fields))
        if post_error is not None:
            raise post_error
        return reg

    def to_text(data):
        if isinstance(texts, Exception):
            raise texts
        if data not in texts:
            raise RuntimeError("pdftotext could not read a sheet")
        return texts[data]

    get.seen, get.post, get.to_text = seen, post, to_text
    return get


def run(g=None, today=TODAY, pause=0, **limits):
    g = g or net()
    return MS.build(get=g, post=g.post, to_text=g.to_text, pause=pause, today=today, **(limits or SMALL))


# ------------------------------------------------------------------------------------------------ the query that is sent, and the requests
sql = MS.search_sql(date(2019, 1, 1), date(2026, 10, 31))
check(sql == ("SELECT DISTINCT  CONVERT(date, ApprovedDate) as ApprovedDte, Permit, WellID, EntityName, CountyName, PermitType FROM rptPermit WHERE (1=1) "
              "and (ApprovedDate >= '2019-01-01') and (ApprovedDate <= '2026-10-31')  ORDER BY EntityName ASC,ApprovedDte Desc "),
      "the query is the Permit Search page's own for a date range with no other filter, asking for six columns")
check(sql.count("'") == 4, "the only literals in the query are the two dates")
g = net()
pauses = []
real_sleep = MS.time.sleep
MS.time.sleep = pauses.append
try:
    doc = run(g, pause=3.0)
finally:
    MS.time.sleep = real_sleep
posts = [s for s in g.seen if isinstance(s, tuple)]
check(len(posts) == 1 and posts[0][1] == MS.API and list(posts[0][2]) == ["QueryToExcute"]
      and base64.b64decode(posts[0][2]["QueryToExcute"]).decode() == MS.search_sql(date(2019, 1, 1), TODAY), "one POST of that query, from 2019-01-01 to the read day, base64 in the page's one field")
check([s for s in g.seen if not isinstance(s, tuple)] == [MS.DOWNLOADS, MS.WELL_LIST % "20261030", MS.SHEETS, SHEET_URL % 2025, SHEET_URL % 2026],
      "then the Downloads page, the newest well list (not the production file), the sheets' folder and the two newest sheets: six requests in all")
check(pauses == [3.0] * 5, "a pause of 3 seconds between the six requests: %s" % pauses)
check(MS.PAUSE == 3.0, "3 seconds is the default pause")

# ------------------------------------------------------------------------------------------------ the register
got = MS.parse_search(reply(), TODAY, min_rows=5)
check(len(got) == UNIQUE, "a permit number twice counts once (%d rows in, %d permits)" % (len(REGISTER), len(got)))
check(got[0] == (date(2024, 11, 5), "2300000001", "ALPHA OPERATING, LLC", "ADAMS", "OPD"), "a permit is (day, well, operator, county, type)")
check(any(g_[2] == "LAMBDA OIL & GAS, LLC" for g_ in got), "an entity written as &amp; is read as &")
check(raises(lambda: MS.parse_search(b"<html>Not Found</html>", TODAY, 5)), "a reply that is not JSON fails")
check(raises(lambda: MS.parse_search(b'{"draw":1}', TODAY, 5)), "a reply with no data fails")
check(raises(lambda: MS.parse_search(json.dumps({"recordsTotal": 3, "data": "x"}).encode(), TODAY, 5)), "data that is not a list fails")
check(raises(lambda: MS.parse_search(reply(total=len(REGISTER) + 1), TODAY, 5)), "a count that does not match the rows (a reply cut short) fails")
check(raises(lambda: MS.parse_search(reply(), TODAY)), "a register of %d permits since 2019 is not the register (it holds thousands): the default floor refuses it" % UNIQUE)
check(raises(lambda: MS.parse_search(reply([r[:5] for r in REGISTER]), TODAY, 5)), "a row of five fields (a changed query or layout) fails")
check(raises(lambda: MS.parse_search(reply([row("2026-10-20", "2026-OPD-0001", "2300000001", None, "ADAMS", "OPD")] + REGISTER), TODAY, 5)), "a field that is not text fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("2026-02-30", "2026-OPD-0999", "2300000001", ALPHA, "ADAMS", "OPD")]), TODAY, 5)), "a date that is not a day fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("10/20/2026", "2026-OPD-0999", "2300000001", ALPHA, "ADAMS", "OPD")]), TODAY, 5)), "a date in another shape fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("2026-11-20", "2026-OPD-0999", "2300000001", ALPHA, "ADAMS", "OPD")]), TODAY, 5)), "an approval date in the future fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("2018-12-31", "2019-OPD-0999", "2300000001", ALPHA, "ADAMS", "OPD")]), TODAY, 5)), "a date before the series starts fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("2026-10-20", "OPD 999", "2300000001", ALPHA, "ADAMS", "OPD")]), TODAY, 5)), "a permit number of another shape fails")
check(raises(lambda: MS.parse_search(reply(REGISTER + [row("2026-10-20", "2026-OPD-0999", "2300000001", ALPHA, "ADAMS", "Original Permit")]), TODAY, 5)), "a permit type that is words, not a code, fails")
check(raises(lambda: MS.parse_search(reply(REGISTER), date(2027, 1, 15), 5)), "a newest permit 87 days old is not a live register")
check(MS.parse_search(reply(REGISTER), date(2026, 12, 15), 5) != [], "one 56 days old is")
few = [r for r in REGISTER if r[5] not in ("OPD", "OPI")] + [r for r in REGISTER if r[5] == "OPD"][:5]
check(raises(lambda: MS.parse_search(reply(few), TODAY, 5)), "five original permits to drill in two years are too few for Mississippi (about 90 a year): not the register")
none_orig = [r for r in REGISTER if r[5] not in ("OPD", "OPI")] * 2
check(raises(lambda: MS.parse_search(reply(none_orig), TODAY, 5)), "a register with none fails")

# ------------------------------------------------------------------------------------------------ the Downloads page and the well list
check(MS.well_list_url(DOWNLOADS, TODAY) == MS.WELL_LIST % "20261030", "the newest dated well list (the production file is not it)")
check(MS.well_list_url(DOWNLOADS.replace("20261030_All_WellInfoList", "20261101_All_WellInfoList"), date(2026, 11, 1)) == MS.WELL_LIST % "20261101", "a newer one wins")
check(raises(lambda: MS.well_list_url("<html>no files</html>", TODAY)), "a Downloads page with no well list fails")
check(raises(lambda: MS.well_list_url(DOWNLOADS, date(2026, 12, 1))), "a newest well list 32 days old fails")
check(raises(lambda: MS.well_list_url(DOWNLOADS, date(2026, 10, 20))), "a well list dated after the read day fails")
check(raises(lambda: MS.well_list_url("/Downloads/WellInfoList/20261399_All_WellInfoList.csv", TODAY)), "a list whose name has no real date fails")
ty = MS.well_types(well_csv(), min_wells=5)
check(ty["2300000001"] == "OIL" and ty["2300000005"] == "MON" and ty["2300000003"] == "DH" and ty["2300000011"] == "EX" and len(ty) == len(WELLS), "the type code is the first word of the Board's Type (OIL, MON, DH...)")
check(MS.well_types(well_csv({**WELLS, "2300000040": "SWD - AG - Water Injection Disposal (Acid Gas)"}), min_wells=5)["2300000040"] == "SWD", "'SWD - AG - ...' is SWD")
check(all(len(k) == 10 and k.isdigit() for k in ty) and all(v.isalnum() for v in ty.values()), "wells are keyed by their ten-digit number and carry only a code")
check(MS.well_types(well_csv() + b"short,row\n,,\n12345,notanumber,OIL - Production\n,2300000050,,PR\n", min_wells=5) == ty, "ragged rows, blank rows, a number that is not ten digits and a blank type are skipped")
check(raises(lambda: MS.well_types(well_csv(header="WellID,Type,Status,Name,Number,Oper,County,Lat,Long,Extra"), min_wells=5)), "a well list that lost its API10 column fails")
check(raises(lambda: MS.well_types(well_csv(header=HEADER.replace(",Type,", ",WellType,")), min_wells=5)), "a well list that lost its Type column fails")
check(raises(lambda: MS.well_types(b"", min_wells=5)), "an empty well list fails")
check(raises(lambda: MS.well_types(well_csv())), "a well list of %d wells (the real one holds 35,000) fails the default floor: cut short" % len(WELLS))
check(raises(lambda: MS.well_types(well_csv({k: v for k, v in WELLS.items() if not v.startswith(("OIL", "DH"))}), min_wells=5)), "a list with no oil wells or no dry holes is not the list")

# ------------------------------------------------------------------------------------------------ the bands
check([MS.band_for(c, None) for c in ("OPD", "OPI", "OPDC", "OPDD", "OPDT", "CIP", "CPI", "WOP", "WOPH", "WOI", "WOIH", "COP", "COI", "H2S", "PIT", "ZZZ")]
      == ["new", "inj", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "amend", "amend", "other", "other", "other"],
      "each permit type has its band; a type nobody knows is other")
check([MS.band_for("OPD", t) for t in ("OIL", "GAS", "DH", "EX", "CA", "ST", "CORE", "CO2", "DGW", "BPM", "NR", None)] == ["new"] * 12, "an original permit for an oil, gas, dry, expired, test or unknown well is new")
check([MS.band_for("OPD", t) for t in ("SWD", "EOR", "BDW", "FD", "GSR", "GSC", "GSCH", "LPG", "MON", "WS", "DWW")] == ["inj"] * 11, "one for a disposal, recovery, brine, storage, monitor or water well is injection")
check(MS.band_for("OPI", "OIL") == "inj" and MS.band_for("WOP", "SWD") == "rework" and MS.band_for("COP", "SWD") == "amend" and MS.band_for("H2S", "SWD") == "other",
      "only an original permit to drill is re-read by the well's type")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "MS" and doc["measure"] == "permits" and doc["basis"] == "approval date" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09"
      and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-31", "monthly from 2019-01 to the last complete month; as of the read day")
nz = {b: {m: n for m, n in zip(doc["months"], v) if n} for b, v in doc["bands"].items() if v is not None}
check(nz["new"] == {"2024-11": 2, "2024-12": 1, "2025-01": 2, "2025-02": 1, "2025-03": 2, "2025-07": 1, "2026-01": 2, "2026-02": 1, "2026-09": 1}, "new wells by approval month: %s" % nz["new"])
check(nz["inj"] == {"2024-12": 5, "2025-02": 2, "2025-03": 1, "2026-03": 1}, "an original permit for a disposal or monitor well, and OPI, are injection: %s" % nz["inj"])
check(nz["rework"] == {"2025-04": 5}, "workovers, conversions and dual or triple completions are reworks: %s" % nz["rework"])
check(nz["amend"] == {"2025-05": 3}, "changes of operator are amendments (October's is in a month not shown yet): %s" % nz["amend"])
check(nz["other"] == {"2025-06": 3}, "H2S, pit and an unknown type are other: %s" % nz["other"])
check(doc["bands"]["redrill"] is None and set(doc["bands"]) == set(C.BANDS), "a re-entry is not told apart: redrill is null, not zero")
check(sum(doc["bands"]["new"]) == 13 and sum(doc["bands"]["new"][-12:]) == 4, "13 new wells in all, 4 in the last 12 complete months (2025-10 to 2026-09)")
check(doc["read"] == UNIQUE, "read counts the permits (a duplicate once, October's two included)")
check("2026-10" not in doc["months"], "October (permits of Oct 20) is not shown: it ended less than two weeks before the read")
check(doc["fluid"] == {"oil": 3, "gas": 1, "both": 0, "other": 0, "unknown": 0}, "fluid: the last 12 months' four new wells by the well's type: %s" % doc["fluid"])
check(doc["counties"] == [["Adams", 3], ["Jones", 1]], "counties are those of the last 12 months' new wells only (not Simpson's injection permit): %s" % doc["counties"])
check(doc["operators"] == [["ALPHA OPERATING LLC", 2], ["BETA ENERGY INC.", 1], ["LAMBDA OIL & GAS LLC", 1]] and doc["namedShare"] == 1.0, "operators are the new wells' companies, ranked: %s" % doc["operators"])
check(doc.get("unit") is None and doc.get("place") is None, "permits are permits and the places are counties: no unit or place override")

# the lag: a month is shown two weeks after it ended
def on(today):
    """The same world read on another day: the register up to that day and a well list dated the day before."""
    day = date(today.year, today.month, today.day).toordinal() - 1
    stamp = date.fromordinal(day).strftime("%Y%m%d")
    page = '<a href="/Downloads/WellInfoList/%s_All_WellInfoList.csv">list</a>' % stamp
    return net(register=reply([r for r in REGISTER if r[0] <= today.isoformat()]), downloads=page)


for today, last in ((date(2026, 11, 13), "2026-09"), (date(2026, 11, 14), "2026-10"), (date(2026, 3, 31), "2026-02")):
    d = run(on(today), today=today)
    check(d["months"][-1] == last and d["asOf"] == today.isoformat(), "read on %s the last month shown is %s" % (today, last))

# every kind of well in the last 12 months, and operators that may not be named
more = run(net(register=reply(REGISTER + EXTRA)))
check(sum(more["bands"]["new"][-12:]) == 11 and more["fluid"] == {"oil": 5, "gas": 1, "both": 0, "other": 2, "unknown": 3}, "fluid by the well's type: oil and gas as they are, a stratigraphic or CO2 well other, a dry or expired well or none unknown: %s" % more["fluid"])
check(all("PUBLIC" not in o[0] and "WILLIAMS" not in o[0] for o in more["operators"]) and more["namedShare"] == round(9 / 11, 3), "an operator that may not be named is counted but never named (9 of 11 named: %s)" % more["namedShare"])
check(more["operators"][0] == ["ALPHA OPERATING LLC", 7], "and the rest are ranked: %s" % more["operators"][:2])
check(C.validate(more, TODAY) == [], "that file validates too")

# nothing from the register or the well list but counts
text = json.dumps(more) + json.dumps(doc)
check("2300000001" not in text and "LEASE" not in text and "OPD-0101" not in text and "SOME OPERATOR" not in text and "JOHN" not in text and "EPSILON" not in text, "no well number, lease, permit number, well-list column or person's name reaches the file")

# the well list must be the one these permits belong to
other_wells = {"2300000099": "OIL - Production", "2300000098": "GAS - Natural Gas - Production", "2300000097": "DH - Dry Hole", "2300000096": "OIL - Production", "2300000095": "OIL - Production"}
check(raises(lambda: run(net(wells=well_csv(other_wells), listing="<ul></ul>"))), "a well list that knows almost none of the original permits' wells fails (not the list these permits belong to), with no sheet check to catch it instead")
blank = [r if not (r[5] == "OPD" and r[2] == "2300000001") else row(r[0], r[1], "", r[3], r[4], r[5]) for r in REGISTER]
check(run(net(register=reply(blank))) is not None, "a few permits with no well number do not fail the join")

# the sources fail loudly
check(raises(lambda: run(net(register=b"<html>maintenance</html>"))), "a register that is a page of something else fails the run")
check(raises(lambda: run(net(downloads="<html>moved</html>"))), "a Downloads page with no well list fails the run")
check(raises(lambda: run(net(wells=RuntimeError("could not read the source")))), "a well list that cannot be read fails the run")
check(raises(lambda: run(net(wells=well_csv(header=HEADER.replace("API10", "Well")))), RuntimeError), "a well list with another header fails the run")
check(raises(lambda: run(net(post_error=C.Refused("HTTP 403 from the server"))), C.Refused), "a refusal is an answer: it still ends the run")

# ------------------------------------------------------------------------------------------------ the check against the Board's yearly sheets
check(MS.captions("   Total 2024 = 50                    Total 2025 = 37", 2025) == {2024: 50}, "a sheet's caption: its own year is open, the year before is final")
check(MS.captions("Total 2024 = 50   Total 2025 = 37", 2026) == {2024: 50, 2025: 37}, "(every year before the sheet's own)")
check(MS.captions("nothing here", 2025) == {} and MS.captions(None, 2025) == {}, "no caption, no figure")
gs = net()
check(MS.sheet_check({2024: 3, 2025: 8, 2026: 2}, gs, gs.to_text, 0, TODAY) == [(2024, 3, 3), (2025, 8, 8)], "the two newest sheets give closed years 2024 and 2025, compared with this file's counts")
check(MS.sheet_check({2024: 5, 2025: 8}, gs, gs.to_text, 0, TODAY) == [(2024, 5, 3), (2025, 8, 8)], "a year 2 permits off (within 3) passes")
check(raises(lambda: MS.sheet_check({2024: 7, 2025: 8}, gs, gs.to_text, 0, TODAY), MS.Disagrees), "a year 4 permits off (more than 3) stops the run")
check(raises(lambda: MS.sheet_check({2024: 3, 2025: 3}, gs, gs.to_text, 0, TODAY), MS.Disagrees), "(5 under stops it too)")
big = {b"PDF2026": "x\n  Total 2025 = 100   Total 2026 = 20\n", b"PDF2025": "x\n  Total 2024 = 100   Total 2025 = 100\n"}
gb = net(sheets=big)
check(MS.sheet_check({2024: 92, 2025: 108}, gb, gb.to_text, 0, TODAY) == [(2024, 92, 100), (2025, 108, 100)], "for a big year the tolerance is 8 percent (8 of 100)")
check(raises(lambda: MS.sheet_check({2024: 91, 2025: 100}, gb, gb.to_text, 0, TODAY), MS.Disagrees), "9 under 100 stops the run")
check(raises(lambda: MS.sheet_check({2024: 100, 2025: 109}, gb, gb.to_text, 0, TODAY), MS.Disagrees), "and 9 over does too")
check(MS.sheet_check({2024: 3}, gs, gs.to_text, 0, TODAY) == [(2024, 3, 3)], "a year this file has no figure for (2025) is not compared")
check(MS.sheet_check({2025: 8, 2026: 99}, gs, gs.to_text, 0, TODAY) == [(2025, 8, 8)], "the year under way (2026) is never compared")
check(MS.sheet_check({2025: 99}, gs, gs.to_text, 0, date(2025, 6, 30)) == [], "nor is a year that is the current one by the clock")
for label, bad in (("the folder unreachable", dict(listing=RuntimeError("could not read the source"))), ("a refusal", dict(listing=C.Refused("HTTP 403 from the server"))),
                   ("sheets that are scans (no text)", dict(sheets={b"PDF2026": "", b"PDF2025": ""})), ("pdftotext failing", dict(sheets=RuntimeError("pdftotext could not read a sheet"))),
                   ("a folder with no sheets", dict(listing="<ul></ul>"))):
    gg = net(**bad)
    check(MS.sheet_check({2024: 3, 2025: 8}, gg, gg.to_text, 0, TODAY) == [], "%s costs only the check (skipped, nothing raised)" % label)
    d_skip = run(net(**bad))
    check(d_skip["bands"] == doc["bands"] and C.validate(d_skip, TODAY) == [], "and the file is the same without it (%s)" % label)
swap = lambda a, b: {b"PDF2026": SHEET_TEXT[b"PDF2026"].replace("Total 2025 = 8", "Total 2025 = %d" % a), b"PDF2025": SHEET_TEXT[b"PDF2025"].replace("Total 2024 = 3", "Total 2024 = %d" % b)}  # noqa: E731
check(raises(lambda: run(net(sheets=swap(20, 3))), MS.Disagrees), "a build whose 2025 disagrees with the Board's sheet (8 against 20) raises instead of returning a document")
check(raises(lambda: run(net(sheets=swap(8, 9))), MS.Disagrees), "ours for 2024 is 3 (eight permits less the five monitor wells): a sheet saying 9 stops the run, and without the subtraction (8) a sheet saying 3 would")
check(run(net(sheets=swap(8, 6))) is not None and run(net(sheets=swap(10, 3))) is not None, "3 against 6 and 8 against 10 are within 3 permits: they pass")

# ------------------------------------------------------------------------------------------------ the request, a refusal, a failure


class FakeResp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


calls = []
real_open = MS.urllib.request.urlopen


def fake_open(code=None, body=b"{}"):
    def op(req, timeout=None):
        calls.append(req)
        if code:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
        return FakeResp(body)
    return op


try:
    MS.urllib.request.urlopen = fake_open(None, b'{"data":[]}')
    check(MS.polite_post(MS.API, {"QueryToExcute": "abc"}, pause=0) == b'{"data":[]}', "a POST returns the body")
    req = calls[-1]
    check(req.get_method() == "POST" and req.data == b"QueryToExcute=abc" and req.get_header("User-agent") == C.UA and "@" not in str(req.headers),
          "it is a form POST with the shared User-Agent and no e-mail address or name in any header")
    for code in (401, 403, 407, 429):
        MS.urllib.request.urlopen = fake_open(code)
        n = len(calls)
        check(raises(lambda: MS.polite_post(MS.API, {"a": "b"}, pause=0), C.Refused) and len(calls) == n + 1, "HTTP %d is a refusal, asked once and never again" % code)
    MS.urllib.request.urlopen = fake_open(500)
    n = len(calls)
    check(raises(lambda: MS.polite_post(MS.API, {"a": "b"}, pause=0)) and len(calls) == n + 2, "a 500 is tried once more and then fails (two requests, never a loop)")
    MS.urllib.request.urlopen = fake_open(None, b"x" * 100)
    check(raises(lambda: MS.polite_post(MS.API, {"a": "b"}, max_bytes=50, pause=0), ValueError), "a reply past the size limit raises")
finally:
    MS.urllib.request.urlopen = real_open

with tempfile.TemporaryDirectory() as tmp:
    def attempt(**kw):
        gx = net(**kw)
        return C.run_producer("MS", lambda: MS.build(get=gx, post=gx.post, to_text=gx.to_text, pause=0, today=TODAY, **SMALL), tmp, argv=[])
    check(attempt(post_error=C.Refused("HTTP 403 from the server")) == 2 and not os.listdir(tmp), "a refusal of the register exits 2 and writes nothing")
    check(attempt(register=b"<html>maintenance</html>") == 1 and not os.listdir(tmp), "a register that is a page of something else exits 1 and writes nothing")
    check(attempt(sheets=swap(30, 3)) == 1 and not os.listdir(tmp), "a year that disagrees with the Board's sheet exits 1 and writes nothing")
    check(attempt() == 0 and os.path.exists(os.path.join(tmp, "MS.json")), "a good run writes nat/MS.json")
    check(C.check_dir(tmp) == [] and C.run_producer("MS", lambda: doc, tmp, argv=["--check"]) == 0, "the written file passes --check")
    before = open(os.path.join(tmp, "MS.json"), "rb").read()
    check(attempt(register=b"<html>maintenance</html>") == 1 and open(os.path.join(tmp, "MS.json"), "rb").read() == before, "a later failed run leaves the committed file as it was")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
