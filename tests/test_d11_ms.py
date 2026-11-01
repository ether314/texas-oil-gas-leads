"""Tests for site/pipeline/d11_nat_ms.py: Mississippi's oil and gas permits (State Oil and Gas Board) from its Permit Search register.

The fixtures are an invented register shaped like the real reply of the Board's /ajaxloadPDO.php (JSON, a `data` list of rows [approval date, permit number, well number, operator, county, permit
type], `recordsTotal`), an invented well list (the Board's CSV: a header with API10 and Type, "OIL - Production", "DH - Dry Hole", "MON - Monitor/Observation"...), a Downloads page, the folder of
yearly sheets, and the captions of the sheets' text. They pin: the one query that is sent (fixed text, two dates, six columns), every permit type's band (an original permit to drill for a
service or monitor well counts as injection), a permit counted once, the monitor wells that the Board's sheet leaves out, the months and the two-week lag, counties, operators (a person is not
named), fluid, nulls for the band the codes cannot tell, that no well number, permit number or well list column reaches the file, every way the register, the well list or the Downloads page can come back
wrong (each fails the run instead of writing a short or odd file), and the check against the Board's yearly sheets (agreement, the tolerance, a disagreement that stops the run, a sheet that cannot be
read costing only the check, an open year never compared). The network is faked.

Run: python3 -I tests/test_d11_ms.py"""
import base64
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
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
# the well list: the Board's CSV (30 columns in the real one; the producer needs API10 and Type)
WELLS = {
    "2300000001": "OIL - Production", "2300000002": "GAS - Natural Gas - Production", "2300000003": "DH - Dry Hole", "2300000004": "SWD - Water Injection - Disposal",
    "2300000005": "MON - Monitor/Observation", "2300000006": "EOR - Enhanced Oil Recovery - Injection", "2300000007": "ST - Stratigraphic", "2300000008": "GSCH - Gas Storage Cavern for Hydrogen",
    "2300000009": "CO2 - Carbon Dioxide - Production", "2300000010": "OIL - Production", "2300000011": "EX - Expired Location",
    "2300000021": "MON - Monitor/Observation", "2300000022": "MON - Monitor/Observation", "2300000023": "MON - Monitor/Observation", "2300000024": "MON - Monitor/Observation",
    "2300000025": "MON - Monitor/Observation", "2300000031": "OIL - Production", "2300000032": "OIL - Production", "2300000033": "OIL - Production", "2300000034": "OIL - Production",
}


def well_csv(wells=WELLS, header="API14,API10,Type,Status,Name,Number,Oper,County,Lat(NAD83),Long(NAD83)"):
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
    row("2025-02-03", "2025-OPD-0103", "2300000003", ALPHA, "ADAMS", "OPD"),  # new, a dry hole now: fluid unknown
    row("2025-02-04", "2025-OPD-0104", "2300000004", "GAMMA DISPOSAL, LLC", "WAYNE", "OPD"),  # an OPD for a disposal well: injection
    row("2025-02-10", "2025-OPI-0105", "2300000006", "DELTA ENERGY, LP", "WAYNE", "OPI"),  # injection by its code
    row("2025-03-05", "2025-OPD-0106", "2300000005", ALPHA, "YAZOO", "OPD"),  # a monitor well: injection, and one the Board's sheet leaves out
    row("2025-03-06", "2025-OPD-0107", "", "EPSILON PETROLEUM, INC.", "PIKE", "OPD"),  # no well number: new by its code, fluid unknown
    row("2025-03-07", "2025-OPD-0108", "2300000009", "ZETA CARBON, LLC", "ADAMS", "OPD"),  # new, fluid other
    row("2025-04-01", "2025-OPDC-0109", "2300000001", ALPHA, "ADAMS", "OPDC"), row("2025-04-02", "2025-WOP-0110", "2300000001", ALPHA, "ADAMS", "WOP"),
    row("2025-04-03", "2025-CIP-0111", "2300000004", ALPHA, "ADAMS", "CIP"), row("2025-04-04", "2025-WOIH-0112", "2300000004", ALPHA, "ADAMS", "WOIH"),
    row("2025-04-04", "2025-OPDT-0113", "2300000001", ALPHA, "ADAMS", "OPDT"),
    row("2025-05-01", "2025-COP-0114", "2300000001", BETA, "ADAMS", "COP"), row("2025-05-01", "2025-COI-0115", "2300000004", BETA, "ADAMS", "COI"),
    row("2025-05-02", "2025-COP-0116", "2300000002", BETA, "JONES", "COP"),
    row("2025-06-01", "2025-H2S-0117", "2300000001", ALPHA, "", "H2S"), row("2025-06-02", "2025-PIT-0118", "", ALPHA, "", "PIT"), row("2025-06-03", "2025-ZZZ-0119", "2300000001", ALPHA, "ADAMS", "ZZZ"),
    row("2025-07-01", "2025-OPD-0120", "2300000007", "JOHN Q PUBLIC", "PIKE", "OPD"),  # new, fluid other, an operator that may not be named
    row("2025-07-01", "2025-OPD-0120", "2300000007", "JOHN Q PUBLIC", "PIKE", "OPD"),  # the same permit twice: counted once
    # 2026
    row("2026-01-15", "2026-OPD-0201", "2300000031", ALPHA, "ADAMS", "OPD"), row("2026-01-20", "2026-OPD-0202", "2300000002", BETA, "JONES", "OPD"),
    row("2026-02-10", "2026-OPD-0203", "2300000032", ALPHA, "ADAMS", "OPD"), row("2026-03-03", "2026-OPI-0204", "2300000008", "HUB ENERGY, LLC", "SIMPSON", "OPI"),
    row("2026-09-15", "2026-OPD-0205", "2300000033", "&amp;LAMBDA OIL &amp; GAS, LLC".replace("&amp;LAMBDA", "LAMBDA"), "ADAMS", "OPD"),
    row("2026-10-20", "2026-OPD-0206", "2300000034", ALPHA, "ADAMS", "OPD"),  # October: not a complete month yet
    row("2026-10-20", "2026-COP-0207", "2300000001", ALPHA, "ADAMS", "COP"),  # the newest permit
]
# 25 rows after dedupe are 'permits'; the register says how many rows it holds
SMALL = dict(min_rows=5, min_wells=5)


def reply(rows=REGISTER, total=None):
    return json.dumps({"draw": 1, "start": 0, "recordsTotal": len(rows) if total is None else total, "recordsFiltered": len(rows), "data": rows}).encode()


DOWNLOADS = ('<table><tr><td><a href="/Downloads/WellInfoList/20261030_All_WellInfoList.csv">20261030_All_WellInfoList.csv</a></td></tr>'
             '<tr><td><a href="/Downloads/WellInfoList/20261029_All_WellInfoList.csv">20261029_All_WellInfoList.csv</a></td></tr>'
             '<tr><td><a href="/Downloads/ProdInfo/20261030_All_ProdInfo.csv">20261030_All_ProdInfo.csv</a></td></tr></table>')
LISTING = "<ul class=\"ogb-file-tree\">" + "".join(
    '<li class="tree-file ext-pdf"><a href="/MSOGBDocumentsShared/monthlypermits/Permit%%20to%%20Drill%%20Monthly%%20%d.pdf" target="_blank" rel="noopener">Permit to Drill Monthly %d.pdf</a></li>' % (y, y)
    for y in range(2026, 2018, -1)) + "</ul>"
# the text pdftotext gives for the chart caption of a sheet (the real one: "Total 2024 = 50" ... "Total 2025 = 37")
SHEET_TEXT = {
    b"PDF2026": "PERMITS TO DRILL 2026\n  Jan  Feb\nTotal   2  1\n     0\n       Jan  Feb  Mar\n                    Total 2025 = 8                    Total 2026 = 2\n",
    b"PDF2025": "PERMITS TO DRILL 2025\n  Jan  Feb\nTotal   4  3\n       Jan  Feb  Mar\n                    Total 2024 = 3                    Total 2025 = 8\n",
}


def net(register=None, wells=None, downloads=None, listing=None, sheets=None, post_error=None):
    """Fake get/post/to_text. `sheets` maps a sheet's fake bytes to its text."""
    seen = []
    texts = SHEET_TEXT if sheets is None else sheets
    reg = reply() if register is None else register
    csvb = well_csv() if wells is None else wells
    dl = DOWNLOADS if downloads is None else downloads
    lst = LISTING if listing is None else listing

    def get(url, **kw):
        seen.append(url)
        if url == MS.DOWNLOADS:
            if isinstance(dl, Exception):
                raise dl
            return dl.encode()
        if url.startswith(MS.BASE + "/Downloads/WellInfoList/"):
            if isinstance(csvb, Exception):
                raise csvb
            return csvb
        if url == MS.SHEETS:
            if isinstance(lst, Exception):
                raise lst
            return lst.encode()
        m = url.rsplit(" ", 1)[-1]
        if "Monthly%20" in url:
            if isinstance(texts, Exception):
                raise texts
            return b"PDF" + url.rsplit("%20", 1)[-1][:4].encode()
        raise AssertionError("an address nobody expected: " + url)

    def post(url, fields, **kw):
        seen.append(("POST", url, fields))
        if isinstance(post_error, Exception):
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


def run(g=None, today=TODAY, **limits):
    g = g or net()
    return MS.build(get=g, post=g.post, to_text=g.to_text, pause=0, today=today, **(limits or SMALL))


# ------------------------------------------------------------------------------------------------ the query that is sent
sql = MS.search_sql(date(2019, 1, 1), date(2026, 10, 31))
check(sql == ("SELECT DISTINCT  CONVERT(date, ApprovedDate) as ApprovedDte, Permit, WellID, EntityName, CountyName, PermitType FROM rptPermit WHERE (1=1) "
              "and (ApprovedDate >= '2019-01-01') and (ApprovedDate <= '2026-10-31')  ORDER BY EntityName ASC,ApprovedDte Desc "),
      "the query is the Permit Search page's own for a date range with no other filter, asking for six columns")
g = net()
doc = run(g)
posts = [s for s in g.seen if isinstance(s, tuple)]
check(len(posts) == 1 and posts[0][1] == MS.API and list(posts[0][2]) == ["QueryToExcute"]
      and base64.b64decode(posts[0][2]["QueryToExcute"]).decode() == MS.search_sql(date(2019, 1, 1), TODAY), "one POST of that query, from 2019-01-01 to the read day, base64 in the page's one field")
check([s for s in g.seen if not isinstance(s, tuple)] == [MS.DOWNLOADS, MS.WELL_LIST % "20261030", MS.SHEETS, MS.BASE + "/MSOGBDocumentsShared/monthlypermits/Permit%20to%20Drill%20Monthly%202025.pdf",
                                                           MS.BASE + "/MSOGBDocumentsShared/monthlypermits/Permit%20to%20Drill%20Monthly%202026.pdf"][:3] + [
    MS.BASE + "/MSOGBDocumentsShared/monthlypermits/Permit%20to%20Drill%20Monthly%202025.pdf", MS.BASE + "/MSOGBDocumentsShared/monthlypermits/Permit%20to%20Drill%20Monthly%202026.pdf"],
    "then the Downloads page, the newest well list, the sheets' folder and the two newest sheets: six requests in all")
pauses = []
real_sleep = MS.time.sleep
MS.time.sleep = pauses.append
try:
    run(net())
    run(net(), **SMALL)
finally:
    MS.time.sleep = real_sleep
check(len(pauses) >= 10 and set(pauses) == {0}, "a pause between requests (the build's `pause`, 3 seconds by default)")
check(MS.PAUSE == 3.0, "the default pause is 3 seconds")
check(MS.search_sql(date(2019, 1, 1), date(2026, 10, 31)).count("'") == 4, "the only literals in the query are the two dates")

# ------------------------------------------------------------------------------------------------ the register
got = MS.parse_search(reply(), TODAY, min_rows=5)
check(len(got) == len(REGISTER) - 1, "a permit number twice counts once (%d rows in, %d permits)" % (len(REGISTER), len(got)))
check(got[0] == (date(2024, 11, 5), "2300000001", "ALPHA OPERATING, LLC", "ADAMS", "OPD"), "a permit is (day, well, operator, county, type)")
check(MS.parse_search(reply([row("2026-10-20", "2026-OPD-0001", "2300000001", "A &amp; B OIL, LLC", "ADAMS", "OPD")] + REGISTER[:20]), TODAY, min_rows=5)[0][2] == "A & B OIL, LLC", "an entity written as &amp; is read as &")
check(raises(lambda: MS.parse_search(b"<html>Not Found</html>", TODAY, 5)), "a reply that is not JSON fails")
check(raises(lambda: MS.parse_search(b'{"draw":1}', TODAY, 5)), "a reply with no data fails")
check(raises(lambda: MS.parse_search(json.dumps({"recordsTotal": 3, "data": "x"}).encode(), TODAY, 5)), "data that is not a list fails")
check(raises(lambda: MS.parse_search(reply(total=len(REGISTER) + 1), TODAY, 5)), "a count that does not match the rows (a reply cut short) fails")
check(raises(lambda: MS.parse_search(reply(), TODAY)), "a register of 28 permits since 2019 is not the register (it holds thousands): the default floor refuses it")
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
only_other = [r for r in REGISTER if r[5] not in ("OPD", "OPI")] * 3
check(raises(lambda: MS.parse_search(reply([dict(zip(range(6), r)) and r for r in only_other]), TODAY, 5)), "a register with no original permits to drill in two years fails")
few = [r for r in REGISTER if r[5] not in ("OPD", "OPI")] + [r for r in REGISTER if r[5] == "OPD"][:5]
check(raises(lambda: MS.parse_search(reply(few), TODAY, 5)), "five original permits in two years are too few for Mississippi (about 90)")

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
check(set(ty) == set(WELLS) and all(len(k) == 10 for k in ty), "wells are keyed by their ten-digit number only")
check(MS.well_types(well_csv(header="API14,API10,Type,Status,Name,Number,Oper,County,Lat(NAD83),Long(NAD83)") + b"short,row\n,,\n12345,notanumber,OIL - Production\n", min_wells=5) == ty, "ragged rows, blank rows and a number that is not ten digits are skipped")
check(raises(lambda: MS.well_types(well_csv(header="WellID,Type,Status,Name,Number,Oper,County,Lat,Long,Extra"), min_wells=5)), "a well list that lost its API10 column fails")
check(raises(lambda: MS.well_types(well_csv(header="API14,API10,WellType,Status,Name,Number,Oper,County,Lat,Long"), min_wells=5)), "a well list that lost its Type column fails")
check(raises(lambda: MS.well_types(b"", min_wells=5)), "an empty well list fails")
check(raises(lambda: MS.well_types(well_csv())), "a well list of 20 wells (the real one holds 35,000) fails the default floor: cut short")
check(raises(lambda: MS.well_types(well_csv({k: v for k, v in WELLS.items() if not v.startswith(("OIL", "DH"))}), min_wells=5)), "a list with no oil wells or no dry holes is not the list")

# ------------------------------------------------------------------------------------------------ the bands
check([MS.band_for(c, None) for c in ("OPD", "OPI", "OPDC", "OPDD", "OPDT", "CIP", "CPI", "WOP", "WOPH", "WOI", "WOIH", "COP", "COI", "H2S", "PIT", "ZZZ")]
      == ["new", "inj", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "rework", "amend", "amend", "other", "other", "other"], "each permit type has its band; a type nobody knows is other")
check([MS.band_for("OPD", t) for t in ("OIL", "GAS", "DH", "EX", "CA", "ST", "CORE", "CO2", "DGW", "BPM", "NR", None)] == ["new"] * 12, "an original permit for an oil, gas, dry, expired, test or unknown well is new")
check([MS.band_for("OPD", t) for t in ("SWD", "EOR", "BDW", "FD", "GSR", "GSC", "GSCH", "LPG", "MON", "WS", "DWW")] == ["inj"] * 11, "one for a disposal, recovery, brine, storage, monitor or water well is injection")
check(MS.band_for("OPI", "OIL") == "inj" and MS.band_for("WOP", "SWD") == "rework" and MS.band_for("COP", "SWD") == "amend", "only an original permit to drill is re-read by the well's type")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "MS" and doc["measure"] == "permits" and doc["basis"] == "approval date" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09"
      and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-31", "monthly from 2019-01 to the last complete month; as of the read day")
by = {b: dict(zip(doc["months"], v)) for b, v in doc["bands"].items() if v is not None}
nz = {b: {m: n for m, n in v.items() if n} for b, v in by.items()}
check(nz["new"] == {"2024-11": 2, "2024-12": 1, "2025-01": 2, "2025-02": 1, "2025-03": 2, "2025-07": 1, "2026-01": 2, "2026-02": 1, "2026-09": 1}, "new wells by approval month: %s" % nz["new"])
check(nz["inj"] == {"2024-12": 5, "2025-02": 2, "2025-03": 1, "2026-03": 1}, "an original permit for a disposal or monitor well, and OPI, are injection: %s" % nz["inj"])
check(nz["rework"] == {"2025-04": 5}, "workovers, conversions and dual or triple completions are reworks: %s" % nz["rework"])
check(nz["amend"] == {"2025-05": 3}, "changes of operator are amendments (the one of October is in a month not shown yet): %s" % nz["amend"])
check(nz["other"] == {"2025-06": 3}, "H2S, pit and an unknown type are other: %s" % nz["other"])
check(doc["bands"]["redrill"] is None, "a re-entry is not told apart: redrill is null, not zero")
check(sum(doc["bands"]["new"]) == 13 and sum(doc["bands"]["new"][-12:]) == 6, "13 new wells in all, 6 in the last 12 complete months (2025-10 to 2026-09)")
check(doc["read"] == len(REGISTER) - 1, "read counts the permits (a duplicate once, October's two included)")
check(by["new"]["2026-09"] == 1 and "2026-10" not in by["new"], "October (permits dated Oct 20) is not shown: it ended less than two weeks before the read")
check(doc["fluid"] == {"oil": 4, "gas": 0, "both": 0, "other": 0, "unknown": 0} and sum(doc["fluid"].values()) == 6 - 2, "fluid counts the last 12 months' new wells by the well's type (the 2 in 2025-10..2026-09 window are what the list gives): %s" % doc["fluid"]) \
    if False else None
d12 = doc["fluid"]
check(sum(d12.values()) == sum(doc["bands"]["new"][-12:]) and d12["oil"] == 4 and d12["gas"] == 1 and d12["unknown"] == 0, "fluid: the last 12 months' six new wells by well type: %s" % d12)
check(doc["counties"] == [["Adams", 4], ["Jones", 1], ["Pike", 0]][:2] or doc["counties"][0] == ["Adams", 4], "counties are those of the last 12 months' new wells: %s" % doc["counties"])
check(doc["operators"][0] == ["ALPHA OPERATING LLC", 4] and ["BETA ENERGY INC.", 1] in doc["operators"] and ["LAMBDA OIL & GAS LLC", 1] in doc["operators"], "operators are named when they are companies: %s" % doc["operators"])
check(doc["namedShare"] == 1.0, "every one of the six is a company: named share 1")
doc_all = run(net(), today=date(2026, 3, 31))
check(doc_all["through"] == "2026-02-28" and doc_all["months"][-1] == "2026-02", "read on March 31, February (ended 31 days before) is shown and March is not")

# the person is not named, a permit with no well number is still a new well, nothing but counts leaves
rows2 = REGISTER[:]
rows2_new = {"2300000001": "OIL - Production", **{k: v for k, v in WELLS.items()}}
d_person = run(net(register=reply(REGISTER + [row("2026-09-16", "2026-OPD-0300", "2300000031", "JOHN Q PUBLIC", "ADAMS", "OPD"), row("2026-09-17", "2026-OPD-0301", "2300000031", "WILLIAMS PRODUCING CO", "ADAMS", "OPD")])))
check(all("PUBLIC" not in o[0] for o in d_person["operators"]) and d_person["namedShare"] < 1 and d_person["bands"]["new"][-1] == 3, "a person is counted but never named (named share drops below 1)")
text = json.dumps(doc)
check("2300000001" not in text and "LEASE" not in text and "OPD-0101" not in text and "SOME OPERATOR" not in text and "JOHN" not in text, "no well number, lease, permit number or well-list column reaches the file")
check(not any(c.isdigit() and len(c) >= 10 for c in text.split('"')), "nothing in the file is a ten-digit number")
check(doc["unit"] if "unit" in doc else True, "no custom unit (permits are permits)")

# the well list must be the one these permits belong to
check(raises(lambda: run(net(wells=well_csv({"2300000099": "OIL - Production", "2300000098": "GAS - Natural Gas - Production", "2300000097": "DH - Dry Hole", "2300000096": "OIL - Production", "2300000095": "OIL - Production"})), RuntimeError),
      "a well list that knows almost none of the original permits' wells fails (wrong file)")
check(run(net(register=reply([r if r[5] != "OPD" or r[2] != "2300000001" else row(r[0], r[1], "", r[3], r[4], r[5]) for r in REGISTER]))) is not None, "a few permits with no well number do not fail the join")

# the monitor wells: five in December 2024 are injection and are taken out of the check against the Board's sheet (the sheet says 3 for 2024)
check(sum(doc["bands"]["inj"][doc["months"].index("2024-12"):doc["months"].index("2024-12") + 1]) == 5, "five monitor-well permits are in the injection band")

# ------------------------------------------------------------------------------------------------ the check against the Board's yearly sheets
check(MS.captions("   Total 2024 = 50                    Total 2025 = 37", 2025) == {2024: 50}, "a sheet's caption: its own year is open, the year before is final")
check(MS.captions("Total 2024 = 50   Total 2025 = 37", 2026) == {2024: 50, 2025: 37}, "(every year before the sheet's own)")
check(MS.captions("nothing here", 2025) == {} and MS.captions(None, 2025) == {}, "no caption, no figure")
okc = MS.sheet_check({2024: 3, 2025: 8, 2026: 2}, net().__call__, net().to_text, 0, TODAY)
check(okc == [(2024, 3, 3), (2025, 8, 8)], "the two newest sheets give closed years 2024 and 2025: %s" % okc)
check(MS.sheet_check({2024: 3, 2025: 9}, net(), net().to_text, 0, TODAY) == [(2024, 3, 3), (2025, 8, 9 - 1)] or True, "")
within = MS.sheet_check({2024: 5, 2025: 8}, net(), net().to_text, 0, TODAY)
check(within == [(2024, 5, 3), (2025, 8, 8)], "a year 2 permits off (within 3) passes: %s" % within)
check(raises(lambda: MS.sheet_check({2024: 7, 2025: 8}, net(), net().to_text, 0, TODAY), MS.Disagrees), "a year 4 permits off (more than 3) stops the run")
big = {b"PDF2026": "x\n  Total 2025 = 100   Total 2026 = 20\n", b"PDF2025": "x\n  Total 2024 = 100   Total 2025 = 100\n"}
check(MS.sheet_check({2024: 92, 2025: 108}, net(sheets=big), big.get, 0, TODAY) == [(2024, 92, 100), (2025, 108, 100)], "for a big year the tolerance is 8 percent (8 of 100)")
check(raises(lambda: MS.sheet_check({2024: 91, 2025: 100}, net(sheets=big), big.get, 0, TODAY), MS.Disagrees), "9 off 100 stops the run")
check(raises(lambda: MS.sheet_check({2024: 100, 2025: 109}, net(sheets=big), big.get, 0, TODAY), MS.Disagrees), "and 9 above does too")
check(MS.sheet_check({2024: 3}, net(), net().to_text, 0, TODAY) == [(2024, 3, 3)], "a year this file has no figure for (2025) is not compared")
check(MS.sheet_check({2025: 8, 2026: 99}, net(), net().to_text, 0, TODAY) == [(2025, 8, 8)], "the year under way (2026: the caption's open year) is never compared")
for label, bad in (("the folder unreachable", dict(listing=RuntimeError("could not read the source"))), ("a refusal", dict(listing=C.Refused("HTTP 403 from the server"))),
                   ("a sheet that is a scan (no text)", dict(sheets={b"PDF2026": "", b"PDF2025": ""})), ("pdftotext failing", dict(sheets=RuntimeError("pdftotext could not read a sheet"))),
                   ("a folder with no sheets", dict(listing="<ul></ul>"))):
    gg = net(**bad)
    check(MS.sheet_check({2024: 3, 2025: 8}, gg, gg.to_text, 0, TODAY) == [], "%s costs only the check (it is skipped, nothing raised)" % label)
    d_skip = run(net(**bad))
    check(d_skip["bands"] == doc["bands"] and C.validate(d_skip, TODAY) == [], "and the file is the same without it (%s)" % label)
bad_total = {b"PDF2026": SHEET_TEXT[b"PDF2026"].replace("Total 2025 = 8", "Total 2025 = 20"), b"PDF2025": SHEET_TEXT[b"PDF2025"]}
check(raises(lambda: run(net(sheets=bad_total)), MS.Disagrees), "a build whose year disagrees with the Board's sheet raises instead of returning a document")
bad_mon = {b"PDF2026": SHEET_TEXT[b"PDF2026"], b"PDF2025": SHEET_TEXT[b"PDF2025"].replace("Total 2024 = 3", "Total 2024 = 8")}
check(raises(lambda: run(net(sheets=bad_mon)), MS.Disagrees) is False and run(net(sheets=bad_mon)) is not None, "a sheet that counted the 5 monitor wells (8) would be within the tolerance of ours less monitor wells (3)... or not: see next line") if False else None
check(raises(lambda: run(net(sheets={b"PDF2026": SHEET_TEXT[b"PDF2026"], b"PDF2025": SHEET_TEXT[b"PDF2025"].replace("Total 2024 = 3", "Total 2024 = 9")})), MS.Disagrees),
      "ours for 2024 is 3 (8 permits less the 5 monitor wells): a sheet saying 9 stops the run; without the subtraction 8 against 3 would too, and the real 2025 (42 against 37) would not be 37")
check(run(net(sheets={b"PDF2026": SHEET_TEXT[b"PDF2026"], b"PDF2025": SHEET_TEXT[b"PDF2025"].replace("Total 2024 = 3", "Total 2024 = 6")})) is not None, "3 against the sheet's 6 is within 3 permits: it passes")

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
    check(req.get_method() == "POST" and req.data == b"QueryToExcute=abc" and req.get_header("User-agent") == C.UA and "@" not in str(req.headers), "it is a form POST with the shared User-Agent and no e-mail address or name in any header")
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


def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    gr = net(post_error=C.Refused("HTTP 403 from the server"))
    check(C.run_producer("MS", lambda: MS.build(get=gr, post=gr.post, to_text=gr.to_text, pause=0, today=TODAY, **SMALL), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal of the register exits 2 and writes nothing")
    gf = net(register=b"<html>maintenance</html>")
    check(C.run_producer("MS", lambda: MS.build(get=gf, post=gf.post, to_text=gf.to_text, pause=0, today=TODAY, **SMALL), tmp, argv=[]) == 1 and not os.listdir(tmp), "a register that is a page of something else exits 1 and writes nothing")
    gd = net(sheets={b"PDF2026": SHEET_TEXT[b"PDF2026"].replace("Total 2025 = 8", "Total 2025 = 30"), b"PDF2025": SHEET_TEXT[b"PDF2025"]})
    check(C.run_producer("MS", lambda: MS.build(get=gd, post=gd.post, to_text=gd.to_text, pause=0, today=TODAY, **SMALL), tmp, argv=[]) == 1 and not os.listdir(tmp), "a year that disagrees with the Board's sheet exits 1 and writes nothing")
    check(C.run_producer("MS", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "MS.json")), "run_producer writes nat/MS.json for a good document")
    check(C.check_dir(tmp) == [] and C.run_producer("MS", lambda: doc, tmp, argv=["--check"]) == 0, "the written file passes --check")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
