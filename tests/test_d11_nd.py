"""Tests for site/pipeline/d11_nat_nd.py: North Dakota's wells by spud date, from the Oil and Gas Division's ArcGIS Wells layer.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; `spud_date` in epoch milliseconds at local midnight, 05:00 UTC; the Division's own
well type codes OG, Confidential, SWD, ST; county and operator in capitals). It pins: the day of a stamp (midnight UTC or local midnight, never an afternoon stamp), the bands from the Division's
type codes (a confidential well is new, a disposal well is `inj`, a stratigraphic test or an unknown code is `other`), that the re-entry, rework and amendment bands and the fluid are null, the
privacy rule on a person-named operator, paging, that nothing but the four fields is asked for, the lag (the last two months are left off), a month with no wells inside the series a real zero,
and that a damaged layer (an error reply, a renamed field, too few rows, unreadable dates, unknown codes, spuds from the future, a stale newest spud, a layer that never ends) fails the run
instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_nd.py"""
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
import d11_nat_nd as ND  # noqa: E402

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


def ms(d, hour=5):
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def row(d, wtype="OG", county="EXAMPLE", operator="Example Energy, LLC", hour=5):
    return {"spud_date": ms(d, hour) if isinstance(d, date) else d, "well_type": wtype, "County": county, "operator": operator}


def reply(rows, more=False, fields=ND.FIELDS):
    d = {"objectIdFieldName": "OBJECTID", "geometryType": "esriGeometryPoint", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields],
         "features": [{"attributes": r} for r in rows]}
    if more:
        d["exceededTransferLimit"] = True
    return json.dumps(d).encode()


def fixture(first="2019-01", last="2026-10", skip=()):
    """Six wells a month: four oil and gas wells (two in EXAMPLE and two in SAMPLE; the operators are an LLC, a corporation, the LLC again and a person), one confidential well (EXAMPLE, the
    LLC), one disposal well; every twelfth month also a stratigraphic test. The last month stops on the 26th. Months in `skip` have no wells at all."""
    rows = []
    for k, ym in enumerate(C.month_list(first, last)):
        if ym in skip:
            continue
        y, m = int(ym[:4]), int(ym[5:])
        hour = 0 if y < 2021 else 5  # older stamps are midnight UTC, newer ones local midnight
        for day, wt, county, oper in ((3, "OG", "EXAMPLE", "Example Energy, LLC"), (9, "OG", "EXAMPLE", "Example Energy, LLC"), (15, "OG", "SAMPLE", "Sample Oil Corporation"),
                                      (21, "OG", "SAMPLE", "Pat Q Sample"), (12, "Confidential", "EXAMPLE", "Example Energy, LLC"), (18, "SWD", "SAMPLE", "Example Energy, LLC")):
            rows.append(row(date(y, m, day), wt, county, oper, hour))
        if k % 12 == 5:
            rows.append(row(date(y, m, 24), "ST", "SAMPLE", "Sample Oil Corporation", hour))
    rows.append(row(date(2026, 10, 26), "OG"))  # the newest spud
    return rows


class Net:
    """The layer: answers a query with the slice of its rows that resultOffset and resultRecordCount ask for, and records what was asked."""

    def __init__(self, rows, **kw):
        self.rows, self.kw, self.urls = rows, kw, []

    def get(self, url, **k):
        self.urls.append(url)
        q = {a: b[0] for a, b in parse_qs(urlparse(url).query).items()}
        off, n = int(q.get("resultOffset", 0)), int(q.get("resultRecordCount", 1000))
        return reply(self.rows[off:off + n], more=off + n < len(self.rows), **self.kw)


def build(rows, today=TODAY, strict=False):
    """ND.build over a fake layer. The fixture is a tenth of the real layer, so the floors (rows, new wells in a year) are lowered for the call unless `strict`."""
    saved = ND.MIN_ROWS, ND.MIN_YEAR_NEW
    if not strict:
        ND.MIN_ROWS, ND.MIN_YEAR_NEW = 400, 30
    try:
        return ND.build(get=Net(rows).get, today=today, pause=0)
    finally:
        ND.MIN_ROWS, ND.MIN_YEAR_NEW = saved


# ------------------------------------------------------------------------------------------------ a stamp is a day
d = date(2026, 6, 1)
check(all(ND.spud_day(ms(d, h)) == d for h in (0, 5, 6, 11)), "a stamp at midnight UTC, at local midnight (05:00 or 06:00 UTC) or before noon is that calendar day")
check(ND.spud_day(ms(d, 15)) is None and ND.spud_day(ms(d, 23)) is None, "an afternoon stamp is neither: not a day")
check(ND.spud_day(None) is None and ND.spud_day("") is None and ND.spud_day("2026-06-01") is None and ND.spud_day(True) is None and ND.spud_day(1e30) is None, "a missing, text, boolean or absurd stamp is not a day")
check(ND.spud_day(-1506470400000) == date(1922, 4, 7), "the oldest stamp the layer has (1922) is read, as a date before the series")

# ------------------------------------------------------------------------------------------------ the bands, from the Division's own codes
check(ND.band_of_type("OG") == ("new", True) and ND.band_of_type(" og ") == ("new", True) and ND.band_of_type("CBM") == ("new", True), "oil and gas (and coal bed methane) wells are new, in any case")
check(ND.band_of_type("Confidential") == ("new", True), "a well whose type the Division holds confidential is counted as a new well")
check(all(ND.band_of_type(t) == ("inj", True) for t in ("SWD", "WI", "GI", "AGD", "AI", "GASD", "GS", "CO2I", "CO2S", "WS", "INJP")), "disposal, injection, storage and water-supply wells are injection and disposal")
check(ND.band_of_type("ST") == ("other", True), "a stratigraphic test is other, and known")
check(ND.band_of_type("MWUI") == ("other", False) and ND.band_of_type("") == ("other", False) and ND.band_of_type(None) == ("other", False), "a code this file does not know (or none) is other and unknown, never new")

# ------------------------------------------------------------------------------------------------ parse
rows = [row(date(2025, 3, 3)), row(date(2025, 3, 4), "SWD"), row(date(2026, 12, 1)), row(date(2018, 5, 5)), row(date(2025, 3, 5), "XYZ", operator=""), row(date(2025, 3, 6), "Confidential")]
wells, counts = ND.parse(rows + [row(date(2025, 4, 1))] * 94, TODAY)  # padded to a hundred rows: the thresholds are shares
check([w["band"] for w in wells[:4]] == ["new", "inj", "other", "new"] and len(wells) == 98 and counts == {"bad": 0, "future": 1, "unknown": 1, "confidential": 1},
      "a spud after today is left out and counted, one before 2019 is skipped, an unknown code is other and counted: %s" % counts)
check(wells[2]["operator"] == "" and wells[0]["county"] == "EXAMPLE", "an empty operator stays empty (it is never named); the county is kept as given")
bad = [row("not a stamp")] * 3 + [row(date(2025, 3, 3))] * 97
check(raises(lambda: ND.parse(bad, TODAY), RuntimeError) is not None, "more than 2% of the dates unreadable fails the run")
check(raises(lambda: ND.parse([row("x")] * 2 + [row(date(2025, 3, 3))] * 98, TODAY), RuntimeError) is None, "two in a hundred is tolerated")
check(raises(lambda: ND.parse([row(date(2025, 3, 3), "QQ")] * 6 + [row(date(2025, 3, 3))] * 94, TODAY), RuntimeError) is not None, "more than 5% of codes unknown fails the run (the layer's codes may have changed)")
check(raises(lambda: ND.parse([row(date(2026, 12, 1))] * 3 + [row(date(2025, 3, 3))] * 97, TODAY), RuntimeError) is not None, "more than 2% of spuds after today fails the run")

# ------------------------------------------------------------------------------------------------ the query and the paging
net = Net(fixture())
saved = ND.PAGE
ND.PAGE = 250
try:
    got = ND.fetch(net.get, pause=0)
finally:
    ND.PAGE = saved
check(len(got) == len(net.rows) and len(net.urls) == 3, "the layer is read page by page until it stops saying there is more (%d rows in %d requests)" % (len(got), len(net.urls)))
q = {a: b[0] for a, b in parse_qs(urlparse(net.urls[0]).query).items()}
check(q["outFields"] == "spud_date,well_type,County,operator" and q["returnGeometry"] == "false" and q["where"] == "spud_date >= DATE '2019-01-01'" and q["f"] == "json",
      "only the four fields are asked for, with no geometry, from 2019 on: %s" % q["outFields"])
check(not any(x in net.urls[0].lower() for x in ("api_no", "well_name", "fileno", "latitude", "longitude")), "no well name, API number, file number or coordinate is asked for")
check(net.urls[0].startswith(ND.LAYER + "/query?") and ND.LAYER.startswith("https://"), "it asks the Division's own layer over https")

# ------------------------------------------------------------------------------------------------ the document
rows = fixture(skip=("2020-04",))
doc = build(rows)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "ND" and doc["measure"] == "spuds" and "spud" in doc["basis"] and doc["name"] == "North Dakota", "North Dakota, counted by spud date")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-07" and doc["through"] == "2026-07-31" and doc["asOf"] == "2026-10-26",
      "from January 2019 to the last month 60 days old: the last two months (August, September; October is not over) are left off: %s to %s, asOf %s" % (doc["months"][0], doc["months"][-1], doc["asOf"]))
check(len(doc["months"]) == 91, "no gap in the months")
new, inj, other = doc["bands"]["new"], doc["bands"]["inj"], doc["bands"]["other"]
i = doc["months"].index("2020-04")
check(new[0] == 5 and new[-1] == 5 and all(n == 5 for n in new if n) and new[i] == 0 and inj[i] == 0, "five new wells every month (four oil and gas and one confidential), and the month with no wells at all is a real zero")
check(all(n == 1 for k, n in enumerate(inj) if k != i) and inj[0] == 1, "one disposal well a month is the injection band")
check(sum(other) == 8 and other[5] == 1 and other[17] == 1, "a stratigraphic test every twelfth month is the other band (8 in 91 months)")
check(doc["bands"]["redrill"] is None and doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "re-entries, reworks and amendments are null (not told), never zero")
check(doc["fluid"] is None, "no fluid: the Division's type is 'oil and gas'")
check(sum(new[-12:]) == 60 and doc["counties"] == [["Example", 36], ["Sample", 24]], "the counties are ranked by the last 12 months' new wells: %s" % doc["counties"])
check(doc["operators"] == [["EXAMPLE ENERGY LLC", 36], ["SAMPLE OIL CORPORATION", 12]], "operators: the LLC and the corporation, no person: %s" % doc["operators"])
check(doc["namedShare"] == 0.8, "four in five new wells have an operator that may be named")
check(doc["read"] == len(rows), "read counts every well it took (%d)" % doc["read"])
check("PAT Q SAMPLE" not in json.dumps(doc).upper() and "Pat Q" not in json.dumps(doc), "the person-named operator is nowhere in the file")
check("not by permit approval" in doc["note"] and "left off" in doc["note"] and "Re-entries" in doc["note"], "the note says what is counted, that it is not approval, and what is left off")
check("(16% of the last 12 months' wells;" in doc["note"], "the note says what share of the year's wells are still confidential (the fixture's year has 12 of 73: 16%)")
check(doc["source"]["url"] == ND.LAYER and doc["cadence"], "the source and a cadence are named")

# the fixture's newest spud is Oct 26
check(raises(lambda: build(rows, today=date(2026, 12, 20)), RuntimeError) is not None, "a newest spud 45 days old or more means a stale layer: the run fails")
check(raises(lambda: build(rows, today=date(2026, 12, 9)), RuntimeError) is None, "a newest spud 44 days old is fine")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
def err_reply(url, **k):
    return json.dumps({"error": {"code": 500, "message": "Error performing query operation", "details": []}}).encode()


check("error" in (raises(lambda: ND.build(get=err_reply, today=TODAY, pause=0), RuntimeError) or ""), "an error reply (HTTP 200 with an error object) fails the run")
check("layout changed" in (raises(lambda: ND.build(get=lambda u, **k: reply(fixture(), fields=("spud_date", "well_type", "County")), today=TODAY, pause=0), RuntimeError) or ""),
      "a layer that lost the operator field fails the run: its layout changed")
check("layout changed" in (raises(lambda: ND.build(get=lambda u, **k: reply(fixture(), fields=("spud_date", "well_type", "county", "operator")), today=TODAY, pause=0), RuntimeError) or ""),
      "a renamed field (County to county) fails the run")
check(raises(lambda: ND.build(get=lambda u, **k: b"[]", today=TODAY, pause=0), RuntimeError) is not None, "a reply that is not an object fails the run")
check(raises(lambda: ND.build(get=lambda u, **k: b"<html>Service unavailable</html>", today=TODAY, pause=0), ValueError) is not None, "an error page instead of JSON fails the run")
check("expected" in (raises(lambda: build(fixture()[:300]), RuntimeError) or ""), "too few rows fail the run")
check("expected" in (raises(lambda: build(fixture(), strict=True), RuntimeError) or ""), "with the real floors (3,000 rows) a layer this small is refused")
check("stale" in (raises(lambda: build([r for r in fixture() if r["spud_date"] < ms(date(2026, 8, 1))]), RuntimeError) or ""), "a layer whose newest spud is old fails the run")
unreadable = fixture()
for r in unreadable[:200]:
    r["spud_date"] = None
check("cannot be read" in (raises(lambda: build(unreadable), RuntimeError) or ""), "a layer whose spud dates went missing fails the run")
renamed = fixture()
for r in renamed[:400]:
    r["well_type"] = "Z" + str(r["well_type"])
check("codes" in (raises(lambda: build(renamed), RuntimeError) or ""), "a layer whose type codes all changed fails the run")
thin = [r for r in fixture() if not (r["spud_date"] >= ms(date(2025, 6, 1)) and r["well_type"] in ("OG", "Confidential"))] + [row(date(2026, 10, 26))] * 3
check("last 12 months" in (raises(lambda: build(thin), RuntimeError) or ""), "a layer cut short in the last year fails the run")
forever = lambda url, **k: reply([row(date(2026, 1, 5))], more=True)  # noqa: E731
saved = ND.MAX_PAGES
ND.MAX_PAGES = 3
try:
    check("more pages" in (raises(lambda: ND.fetch(forever, pause=0), RuntimeError) or ""), "a layer that always says there is more stops after the page limit and fails the run")
finally:
    ND.MAX_PAGES = saved


def refuse(url, **k):
    raise C.Refused("HTTP 403 from the server")


check(raises(lambda: ND.build(get=refuse, today=TODAY, pause=0), C.Refused) is not None, "a refusal is passed up as a refusal (never retried here)")
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "ND.json")
    open(old, "w").write("committed\n")
    check(C.run_producer("ND", lambda: ND.build(get=refuse, today=TODAY, pause=0), tmp, argv=[]) == 2 and open(old).read() == "committed\n", "a refusing server ends the run with exit 2 and leaves the committed file alone")
    check(C.run_producer("ND", lambda: ND.build(get=err_reply, today=TODAY, pause=0), tmp, argv=[]) == 1 and open(old).read() == "committed\n", "a failed run exits 1 and leaves the committed file alone")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("ND", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "ND.json")), "run_producer writes nat/ND.json for it")
    check(C.check_dir(tmp) == [] and C.run_producer("ND", lambda: doc, tmp, argv=["--check"]) == 0, "the written file reloads and validates")
    written = json.load(open(os.path.join(tmp, "ND.json")))
    check(written["bands"]["new"] == doc["bands"]["new"] and written["operators"] == doc["operators"], "and holds what the document held")

# a document with a person-named operator forced in is refused by the validator (the Tally never lets one through)
t = C.Tally("ND", bands=("new", "inj", "other"))
for k in range(30):
    t.add(date(2026, 1, 1 + k % 28), "new", county="EXAMPLE", operator="Pat Q Sample")
    t.add(date(2026, 2, 1 + k % 28), "new", county="EXAMPLE", operator="Example Energy, LLC")
check(t.document(agency="x", source_name="x", source_url="https://example.com/x", basis="spud date", cadence="x", measure="spuds", lag_days=60, first="2026-01", asof=date(2026, 5, 20))["operators"] == [["EXAMPLE ENERGY LLC", 30]],
      "the Tally keeps a person's name out of the operators")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
