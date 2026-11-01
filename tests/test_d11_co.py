"""Tests for site/pipeline/d11_nat_co.py: Colorado's wells spudded (ECMC) from the Wells (API Spots) ArcGIS layer, held against the Commission's own well-starts table.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; `spud_date` in epoch milliseconds, mostly at midnight UTC and a few with a time of day;
`well_class` codes padded with spaces to 25 characters as the real ones are; county names in capitals; a blank class for a well not yet classed) and the way the yearly table answers (an HTML table with
a County header of years and a TOTAL row). It pins: the band and fluid of every well class (a blank class is a new well of unknown fluid, never oil), that a well counts once on its first spud date (a
repeated facility number, within a month and across years), that a spud dated after today is set aside, that a stamp is read as its UTC calendar day, the lag (the last month is left off), the privacy rule
on a person-named operator and that no column that was not needed is requested, paging by OBJECTID, the yearly table's reading and the 10 percent hold against it (a table that cannot be read skips the
check; a table far from the layer fails the run), and that a damaged layer (an error reply, a renamed field, too few rows, a count that does not match, unreadable dates, classes that no longer fit,
a stale newest spud, a year with too few wells, endless paging) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_co.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_co as CO  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# the shipped floors suit what the real layer holds (6,478 rows; 638 wells in the lowest full year; 667 new wells in the last 12 months); the small fixture needs lower ones
check(CO.MIN_ROWS < 6478 and CO.MIN_YEAR < 638 and CO.MIN_NEW12 < 667 and CO.MIN_ROWS >= 1000 and CO.MIN_YEAR >= 100, "the shipped floors sit below what the real layer holds")
CO.MIN_ROWS, CO.MIN_YEAR, CO.MIN_NEW12 = 500, 100, 20

EXAMPLE, SAMPLE = "EXAMPLE OIL & GAS LLC", "SAMPLE ENERGY INC"


def ms(d, hour=0):
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def row(oid, d, cls, county="WELD", oper=EXAMPLE, fid="auto", hour=0):
    return {"OBJECTID": oid, "facility_id": 400000 + oid if fid == "auto" else fid, "spud_date": ms(d, hour) if isinstance(d, date) else d,
            "County": county, "well_class": cls.ljust(25) if cls is not None else None, "Operator": oper}


MONTHLY = ((3, "OW", "WELD", EXAMPLE), (5, "OW", "WELD", EXAMPLE), (7, "OW", "ADAMS", SAMPLE), (9, "GW", "GARFIELD", SAMPLE), (11, "CBM", "LA PLATA", SAMPLE), (13, "DA", "WELD", EXAMPLE),
           (15, "LO", "WELD", EXAMPLE), (17, None, "WELD", EXAMPLE), (19, "DSPW", "WELD", EXAMPLE), (21, "ERIW", "ADAMS", SAMPLE))
QUARTERLY = ((23, "HE", "GARFIELD", SAMPLE), (25, "OBW", "WELD", EXAMPLE))  # in April, August and December only


def fixture():
    """Every month from 2019-01 to 2026-10: three oil, a gas, a coal bed methane, a dry hole, a permitted location and a well with no class (8 new), a disposal and an injection well (2 inj): 10 a month;
    in April, August and December also a helium and an observation well (2 other). Then the odd rows (Feb to Apr 2026, one in Oct 2020, one on Oct 31 so the newest spud is that day)."""
    rows, n = [], 1
    for ym in C.month_list("2019-01", "2026-10"):
        y, m = int(ym[:4]), int(ym[5:])
        for day, cls, county, oper in MONTHLY + (QUARTERLY if m % 4 == 0 else ()):
            rows.append(row(n, date(y, m, day), cls, county, oper))
            n += 1
    mar = date(2026, 3, 10)
    odd = [
        row(n + 1, mar, "OW", oper="DOE JANE DBA JANE OIL CO"),  # a person trading under a name: counted, never named
        row(n + 2, mar, "OW", oper="ROE RICHARD"),  # a person with no company word: counted, never named
        row(n + 3, mar, "OW", oper=""),  # no operator: counted
        row(n + 4, mar, "OW", county=""),  # no county: counted, no place
        row(n + 5, mar, "ow  "),  # a code in lower case with stray spaces: oil
        row(n + 6, date(2026, 3, 12), "OW", fid=999001), row(n + 7, date(2026, 3, 14), "OW", fid=999001),  # one well entered twice: March, once
        row(n + 8, date(2026, 3, 20), "OW", fid=999002), row(n + 9, date(2026, 2, 20), "OW", fid=999002),  # one well, two dates in two months: February (the first), once
        row(n + 10, date(2020, 10, 16), "OW", fid=999003), row(n + 11, date(2024, 3, 30), "OW", fid=999003),  # a sidetrack spud again years later: the first spud only
        row(n + 12, mar, "OW", fid=None), row(n + 13, mar, "OW", fid=None),  # no facility number to match on: each counted
        row(n + 14, date(2026, 3, 31), "OW", hour=23),  # the last evening of March (UTC): March
        row(n + 15, date(2026, 4, 1), "OW", hour=2),  # 2 am UTC on April 1: April (the stamp's calendar day)
        row(n + 16, mar, "XYZ"),  # a class in no table: other, flagged
        row(n + 17, date(2026, 12, 21), "OW"),  # a spud dated after today: set aside
        row(n + 18, date(2026, 10, 31), "OW"),  # the newest spud
    ]
    return rows + odd


GOOD = fixture()
MI = C.month_list("2019-01", "2026-09").index


def starts_html(table, counties=(("WELD", 1), ("ADAMS", 2))):
    """The Commission's yearly page, shaped like the real one: header row of years, county rows with blanks, a bold TOTAL row."""
    years = sorted(table)
    head = "<tr class=\"header\"><th scope=\"col\">County</th>" + "".join("<th>%d</th>" % y for y in years) + "</tr>"
    body = "".join("<tr class=\"rows\"><td>%s</td>" % c + "".join("<td align=\"center\">%s</td>" % (n if i == 0 else "&nbsp;") for i, y in enumerate(years)) + "</tr>" for c, n in counties)
    tot = "<tr class=\"rows\"><td style=\"font-weight:bold;\">TOTAL</td>" + "".join("<td style=\"font-weight:bold;\">%d</td>" % table[y] for y in years) + "</tr>"
    return ("<html><body><span>Annual Well Starts by County as of 11/1/2026</span><table class=\"mygrdContent\">" + head + body + tot + "</table></body></html>").encode()


TABLE_OK = {y: 126 for y in range(2019, 2027)}  # the fixture holds 126 wells a year
TABLE_OK.update({2023: 128, 2024: 125, 2025: 130})


class Net:
    """The layer and the yearly page: a count, pages of rows by `OBJECTID > N` the way ArcGIS does, and the Commission's table. `page` is how many rows a page really gives."""

    def __init__(self, rows, page=2000, fields=CO.FIELDS, count=None, table=TABLE_OK, table_raises=None):
        self.rows, self.page, self.fields, self.count, self.table, self.table_raises = sorted(rows, key=lambda r: r["OBJECTID"]), page, fields, count, table, table_raises
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        if url.startswith(CO.STARTS):
            if self.table_raises:
                raise self.table_raises
            return starts_html(self.table) if self.table is not None else b"<html>maintenance</html>"
        q = parse_qs(urlparse(url).query)
        if "returnCountOnly" in q:
            return json.dumps({"count": len(self.rows) if self.count is None else self.count}).encode()
        last = int(q["where"][0].rsplit("OBJECTID >", 1)[1])
        rest = [r for r in self.rows if r["OBJECTID"] > last]
        part = rest[:min(self.page, int(q["resultRecordCount"][0]))]
        d = {"objectIdFieldName": "OBJECTID", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in self.fields], "features": [{"attributes": r} for r in part]}
        if len(part) < len(rest):
            d["exceededTransferLimit"] = True
        return json.dumps(d).encode()


def build(rows=None, today=TODAY, **kw):
    net = Net(rows if rows is not None else GOOD, **kw)
    return CO.build(get=net.get, today=today, pause=0), net


def fails(fn, text=None):
    try:
        fn()
        return False
    except RuntimeError as e:
        return text is None or text in str(e)
    except Exception as e:  # noqa: BLE001
        print("     unexpected %s: %s" % (type(e).__name__, str(e)[:80]))
        return False


# ------------------------------------------------------------------------------------------------ small parts
k = CO.class_of
check(all(k(c) == ("new", "oil", True) for c in ("OW", "ow", " OW                      ")), "an oil well class is a new oil well, whatever its case or padding")
check(k("GW") == ("new", "gas", True) and k("CBM") == ("new", "gas", True), "a methane gas well and a coal bed methane well are new gas wells")
check(all(k(c) == ("new", None, True) for c in ("DA", "LO", "", None, "   ")), "a dry hole, a permitted location and a well with no class yet are new wells of unknown fluid (never oil by default)")
check(all(k(c) == ("inj", None, True) for c in ("DSPW", "CLASS I EPA", "CLASS II EPA", "ERIW", "STOW")), "disposal, the two EPA classes, enhanced recovery and gas storage are injection wells")
check(all(k(c) == ("other", None, True) for c in ("HE", "CO2", "DM", "OBW", "STRT", "GEO-SCI", "OTH")), "helium, CO2, domestic, observation, stratigraphic, geologic-science and other wells are other")
check(k("XYZ") == ("other", None, False) and k("OIL") == ("other", None, False), "a class in no table is other and flagged unknown (never a new well by default)")
u = urlparse(CO.url_for(4000))
q = parse_qs(u.query)
check(u.netloc == "gisdnr.state.co.us" and q["where"] == ["spud_date >= DATE '2019-01-01' AND OBJECTID > 4000"] and q["returnGeometry"] == ["false"] and q["orderByFields"] == ["OBJECTID"] and q["f"] == ["json"],
      "the request is the layer's query by OBJECTID from the last id, no geometry (%s)" % q["where"])
check(parse_qs(urlparse(CO.url_for(count=True)).query).get("returnCountOnly") == ["true"] and "OBJECTID" not in parse_qs(urlparse(CO.url_for(count=True)).query)["where"][0], "the count request asks for the count only")
check(set(CO.FIELDS) == {"OBJECTID", "facility_id", "spud_date", "County", "well_class", "Operator"}, "five fields and the row id are asked for: no API number, well or lease name, coordinate, field or location column")
p = CO.parse(GOOD, TODAY)
check(len(p) == 1000 and p == sorted(p, key=lambda x: x["day"]), "1,004 rows are 1,000 wells (three repeats and one date after today set aside), oldest first (%d)" % len(p))
check(sum(1 for x in CO.parse([row(1, date(2026, 3, 12), "OW", fid=7), row(2, date(2026, 3, 14), "OW", fid=7)], TODAY)) == 1
      and CO.parse([row(2, date(2026, 3, 14), "OW", fid=7), row(1, date(2026, 3, 12), "OW", fid=7)], TODAY)[0]["day"] == date(2026, 3, 12), "a repeated facility number is one well, on the earlier date, whatever the row order")
check(len(CO.parse([row(1, date(2026, 3, 12), "OW", fid=None), row(2, date(2026, 3, 12), "OW", fid=None)], TODAY)) == 2, "rows with no facility number are two wells")
check(CO.parse([row(1, date(2026, 3, 31), "OW", hour=23)], TODAY)[0]["day"] == date(2026, 3, 31) and CO.parse([row(1, date(2026, 4, 1), "OW", hour=2)], TODAY)[0]["day"] == date(2026, 4, 1),
      "a stamp is read as its UTC calendar day")
many = [row(i + 1, date(2026, 3, 1), "OW") for i in range(200)]
check(len(CO.parse(many + [row(999, date(2026, 12, 25), "OW")], TODAY)) == 200, "a spud dated after today is set aside, not counted")
check(len(CO.parse(many + [row(999, "n/a", "OW")], TODAY)) == 200 and len(CO.parse(many + [row(998, None, "OW")], TODAY)) == 200, "one date that does not read (under 1%) is set aside")
check(len(CO.parse(many + [row(999, date(2018, 12, 31), "OW")], TODAY)) == 200, "a spud before 2019 (the layer asks for none) is set aside")


# ------------------------------------------------------------------------------------------------ the yearly table
t = CO.starts_table(starts_html({2019: 1488, 2020: 742, 2021: 679, 2022: 934, 2023: 810, 2024: 650}))
check(t == {2019: 1488, 2020: 742, 2021: 679, 2022: 934, 2023: 810, 2024: 650}, "the TOTAL row is read under the years of the County header: %s" % t)
check(CO.starts_table(starts_html({2023: 810, 2024: 650})) == {}, "a table of only two years is not the table (the real one holds 24)")
check(CO.starts_table(b"<html>maintenance</html>") == {} and CO.starts_table(b"") == {} and CO.starts_table("<table><tr><td>County</td><td>2024</td></tr><tr><td>TOTAL</td></tr></table>") == {},
      "a page without that table, an empty page and a TOTAL row of another length read as nothing")
check(CO.starts_table("<table><tr><th>County</th><th>2023</th><th>2024</th><th>x</th><th>y</th></tr><tr><td>TOTAL</td><td>12,3</td><td>abc</td><td>5</td><td>6</td></tr></table>") == {},
      "a total that is not a whole number is not read")
mine = CO.parse(GOOD, TODAY)
check(CO.reconcile(mine, TABLE_OK, TODAY)[0].startswith("2023: 126 wells here, 128"), "the last three full years are held against the table and logged")
check(len(CO.reconcile(mine, TABLE_OK, TODAY)) == 3, "three years are held (2023, 2024, 2025), not the year in progress or older ones")
check(fails(lambda: CO.reconcile(mine, {**TABLE_OK, 2024: 150}, TODAY), "2024"), "a year 16% under the table fails the run and names the year")
check(fails(lambda: CO.reconcile(mine, {**TABLE_OK, 2025: 100}, TODAY), "2025"), "a year 26% over the table fails the run")
check(CO.reconcile(mine, {**TABLE_OK, 2024: 138}, TODAY) is not None, "9% under the table passes (the real layer is within 2%)")
check(CO.reconcile(mine, {2024: 125}, TODAY) == ["2024: 126 wells here, 125 in the Commission's table (+0.8%)"], "a year the table does not have is not held")
check(CO.reconcile(mine, {2019: 5000}, TODAY) == [], "a year older than the last three is not held")

# ------------------------------------------------------------------------------------------------ the document
doc, net = build()
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "CO" and doc["measure"] == "spuds" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-31",
      "measure spuds, 2019-01 to 2026-09 (the last month, whose 30 days are not up, is left off), asOf the newest spud: %s %s %s" % (doc["months"][-1], doc["through"], doc["asOf"]))
bands = doc["bands"]
check(bands["new"][0] == 8 and bands["inj"][0] == 2 and bands["other"][0] == 0 and bands["other"][MI("2019-04")] == 2, "an ordinary month: 8 new, 2 injection, no other; April, August and December add 2 other")
check(bands["redrill"] is None and bands["rework"] is None and bands["amend"] is None, "re-entries, reworks and amendments are not told by the layer: null, never zero")
feb, mar, apr = MI("2026-02"), MI("2026-03"), MI("2026-04")
check(bands["new"][feb] == 9 and bands["new"][mar] == 17 and bands["other"][mar] == 1 and bands["inj"][mar] == 2, "March 2026 holds the odd rows: 17 new, 1 other (the class in no table), 2 injection; got %s" % ((bands["new"][mar], bands["other"][mar], bands["inj"][mar]),))
check(bands["new"][feb] == 9, "the well with two dates in two months is in February, once (9 new)")
check(bands["new"][apr] == 9, "2 am UTC on April 1 is April (9 new)")
check(bands["new"][MI("2020-10")] == 9 and bands["new"][MI("2024-03")] == 8, "a sidetrack spud again years later counts in the first month only (October 2020, not March 2024)")
check(doc["read"] == 1000, "read counts the wells it kept, including the month left off (%d)" % doc["read"])
check(sum(bands["new"][-12:]) == 107, "107 new wells in the last 12 months (%d)" % sum(bands["new"][-12:]))
check(doc["fluid"] == {"oil": 47, "gas": 24, "both": 0, "other": 0, "unknown": 36} and sum(doc["fluid"].values()) == 107,
      "fluid: oil and gas where the class says it; a dry hole, a permitted location and a blank class are unknown, never oil: %s" % doc["fluid"])
check(doc["counties"] == [["Weld", 70], ["Adams", 12], ["Garfield", 12], ["La Plata", 12]], "places are county names in title case, ranked (a well with no county has none): %s" % doc["counties"])
check(doc["operators"] == [["EXAMPLE OIL & GAS LLC", 68], ["SAMPLE ENERGY INC", 36]], "operators are companies only: %s" % doc["operators"])
check(doc["namedShare"] == round(104 / 107, 3), "104 of 107 new wells have a nameable operator (a dba and a surname do not, and a blank has none): %s" % doc["namedShare"])
blob = json.dumps(doc)
check(not any(s in blob for s in ("DOE", "JANE", "ROE", "RICHARD", "DBA")), "no person-named operator reaches the file")
check(all(C.nameable(o[0]) for o in doc["operators"]), "every operator listed passes the naming rule")
check(not any(ch.isdigit() for ch in "".join(o[0] for o in doc["operators"]) + "".join(c[0] for c in doc["counties"])), "no number in a place or operator name")
check("12 months" in doc["note"] and "not a count of permits" in doc["note"] and "first spud date" in doc["note"] and "unknown" in doc["note"] and "left off" in doc["note"], "the note says what is counted, why not permits, and what is unknown")
check(doc["cadence"].startswith("daily") and doc["source"]["url"] == CO.LAYER and "spud date" in doc["basis"], "cadence, source and basis are stated")
check(len(net.urls) == 1 + 1 + 1 and net.urls[0].endswith("returnCountOnly=true") or "returnCountOnly=true" in net.urls[0], "the layer's count is read first")
check(len(net.urls) == 3 and urlparse(net.urls[-1]).netloc == "ecmc.state.co.us" and all(urlparse(x).netloc == "gisdnr.state.co.us" for x in net.urls[:-1]),
      "1,004 rows come in one page: the count, the page and the yearly table (%d requests)" % len(net.urls))
doc2, net2 = build(page=300)
check(doc2 == doc and len(net2.urls) == 1 + 4 + 1, "a layer that gives 300 rows a page, whatever was asked, is followed by OBJECTID page by page and gives the same file (%d requests)" % len(net2.urls))
check(len(set(net2.urls)) == len(net2.urls), "no page is asked for twice")
docr, _ = build(rows=list(reversed(GOOD)))
check(docr == doc, "the order the rows come in changes nothing")

# the table cannot be read: the yearly check is skipped, the file is still written
d_skip, _ = build(table=None)
check(d_skip == doc, "a yearly page that is not the table skips the check and writes the same file")
d_ref, _ = build(table_raises=C.Refused("HTTP 403 from the server"))
check(d_ref == doc, "a yearly page that refuses the runner skips the check and writes the same file")
d_err, _ = build(table_raises=RuntimeError("could not read the source"))
check(d_err == doc, "a yearly page that cannot be read skips the check and writes the same file")
check(fails(lambda: build(table={**TABLE_OK, 2024: 300}), "2024"), "a yearly page far from the layer's count fails the run: the layer or the table changed")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
def mod(rows, pred, **changes):
    """The rows with `changes` made to those `pred` picks (copies: the fixture is not touched)."""
    return [dict(r, **changes) if pred(r) else r for r in rows]


def year_of(r):
    return datetime.fromtimestamp(r["spud_date"] / 1000, timezone.utc).year


check(fails(lambda: CO.build(get=lambda url, **kw: json.dumps({"error": {"code": 499, "message": "Token Required"}}).encode(), today=TODAY, pause=0), "error (code 499)"), "an error reply fails the run, with its code and no address")
check(fails(lambda: build(fields=tuple(f for f in CO.FIELDS if f != "spud_date")), "spud_date"), "a layer that lost a field fails the run and names it")
check(fails(lambda: build(fields=tuple(f for f in CO.FIELDS if f != "well_class")), "well_class"), "a layer that lost the class field fails the run")
check(fails(lambda: build(count=len(GOOD) + 80), "changed while it was read"), "a count that says far more than was read fails the run")
check(fails(lambda: build(count=len(GOOD) - 80), "changed while it was read"), "a count that says far less than was read fails the run")
check(build(count=len(GOOD) + 5)[0] == doc, "a few rows more or less than the count (the layer is live) are allowed")
few = Net(GOOD[:50])
check(fails(lambda: CO.build(get=few.get, today=TODAY, pause=0), "expected 500 or more") and len(few.urls) == 1, "too few rows fail the run at the count, before any page is read")
check(fails(lambda: build(mod(GOOD, lambda r: r["well_class"] and r["well_class"].strip() == "OW", spud_date="n/a")), "cannot be read"), "dates that no longer read fail the run")
check(fails(lambda: build(mod(GOOD, lambda r: r["well_class"] and r["well_class"].strip() == "GW", spud_date=ms(date(2030, 1, 1)))), "after today"), "spud dates after today, more than 1% of the rows, fail the run")
check(fails(lambda: build(mod(GOOD, lambda r: r["well_class"] and r["well_class"].strip() == "OW", well_class="PETROLEUM")), "does not explain"), "classes the table does not explain fail the run (by that rule, not by the share of other wells)")
check(fails(lambda: build(mod(GOOD, lambda r: r["well_class"] and r["well_class"].strip() in ("GW", "CBM", "DA", "LO", "ERIW", "DSPW"), well_class="OBW".ljust(25))), "other"), "a layer where most wells turn into other wells fails the run")
check(fails(lambda: build(today=date(2026, 12, 15)), "stale"), "a newest spud older than a month fails the run (a layer that stopped rebuilding)")
check(fails(lambda: build([r for r in GOOD if year_of(r) != 2021]), "2021"), "a year with no wells fails the run and names the year")
check(fails(lambda: build([r for r in GOOD if year_of(r) >= 2021 or r["OBJECTID"] % 4 == 0]), "history may be missing"), "a layer that lost three quarters of its early history fails the run")
CO.MIN_NEW12 = 200  # more than the fixture's 107 new wells in its last 12 months
check(fails(lambda: build(), "new wells in the last 12 months"), "fewer new wells in the last 12 months than the floor fails the run")
CO.MIN_NEW12 = 20


def endless(url, **kw):
    """A layer that says there is always more (and gives 100 rows with ever higher ids every time)."""
    if "returnCountOnly" in url:
        return json.dumps({"count": 100 * CO.MAX_PAGES}).encode()
    last = int(parse_qs(urlparse(url).query)["where"][0].rsplit("OBJECTID >", 1)[1])
    return json.dumps({"fields": [{"name": f} for f in CO.FIELDS], "features": [{"attributes": dict(r, OBJECTID=last + 1 + i)} for i, r in enumerate(GOOD[:100])], "exceededTransferLimit": True}).encode()


check(fails(lambda: CO.build(get=endless, today=TODAY, pause=0), "more pages than expected"), "a layer that never stops giving pages fails the run (it never wanders)")


def stuck(url, **kw):
    """A layer that says there is more but repeats the same ids."""
    if "returnCountOnly" in url:
        return json.dumps({"count": 5000}).encode()
    return json.dumps({"fields": [{"name": f} for f in CO.FIELDS], "features": [{"attributes": r} for r in GOOD[:100]], "exceededTransferLimit": True}).encode()


check(fails(lambda: CO.build(get=stuck, today=TODAY, pause=0), "does not advance"), "a layer whose paging does not advance fails the run")
check(CO.MAX_PAGES * CO.PAGE >= 3 * 6478, "the page limit leaves room for the layer to triple in size")


def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("CO", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "CO.json")), "run_producer writes nat/CO.json for it")
    check(C.check_dir(tmp) == [], "and the file reloads clean")
    check(C.run_producer("CO", lambda: doc, tmp, argv=["--check"]) == 0, "--check reloads what is committed")
with tempfile.TemporaryDirectory() as tmp:
    code = C.run_producer("CO", lambda: CO.build(get=refuse, today=TODAY, pause=0), tmp, argv=[])
    check(code == 2 and not os.listdir(tmp), "a refusal (HTTP 403) exits 2 and writes nothing")
with tempfile.TemporaryDirectory() as tmp:
    code = C.run_producer("CO", lambda: build(fields=("X",))[0], tmp, argv=[])
    check(code == 1 and not os.listdir(tmp), "a failed run exits 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
