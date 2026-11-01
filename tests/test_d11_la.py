"""Tests for site/pipeline/d11_nat_la.py: Louisiana's well permits (Office of Conservation) from the ArcGIS Oil/Gas Wells layer in SONRIS GIS.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; `PERMIT_DATE` in epoch milliseconds at local midnight, 05:00 UTC; well serial numbers
that run in order for oil and gas permits and in a series of their own for injection wells; the Office's own words in LEGEND_DESC; product codes 10 oil, 20 gas, 00 none; operator and parish in
capitals). It pins: the day of a stamp, the series a permit belongs to (new, injection by class, by series or by words, orphan-well entries as other), that the re-entry, rework and amendment
bands are null and the fluid is the product code, a cut-off LLC in an operator name completed, the privacy rule on a person-named operator, paging, that nothing but seven fields is asked for,
the serial-number completeness check (a layer that lost a third of its permits fails the run), a repeated serial and a row dated after today counted once or left out, and that a damaged layer
(an error reply, a renamed field, too few rows, unreadable dates, a stale newest permit, a layer that never ends) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_la.py"""
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
import d11_nat_la as LA  # noqa: E402

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


def row(d, serial, legend="ACTIVE - PRODUCING  GAS", product="20", parish="EXAMPLE", operator="Example Gas, LLC", cls=None):
    return {"PERMIT_DATE": ms(d) if isinstance(d, date) else d, "WELL_SERIAL_NUM": serial, "WELL_CLASS_TYPE_CODE": cls, "PRODUCT_TYPE_CODE": product, "LEGEND_DESC": legend,
            "PARISH_NAME": parish, "ORG_OPER_NAME": operator}


def reply(rows, more=False, fields=LA.FIELDS):
    d = {"displayFieldName": "WELL_NAME", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields], "features": [{"attributes": r} for r in rows]}
    if more:
        d["exceededTransferLimit"] = True
    return json.dumps(d).encode()


GAS = ("ACTIVE - PRODUCING  GAS", "20")
OIL = ("ACTIVE - PRODUCING  OIL", "10")
NOT_DRILLED = ("PERMITTED", "00")
EXPIRED = ("PERMIT EXPIRED", "00")


def fixture(first="2019-01", last="2026-10"):
    """Five oil and gas permits a month with consecutive serial numbers from 250000 (day 3 and 9: gas, EXAMPLE, an LLC; day 15: oil, SAMPLE, a corporation; day 21: not yet drilled, SAMPLE, a
    person; day 25: expired, EXAMPLE, the LLC) and one injection permit in the injection series (976000 up, class 5, day 18); every twelfth month an orphan-well entry (990000 up). In
    February 2026 three more injection permits: one in the oil and gas series with a class, one there with only the words, one in the injection series with no class. Then one permit on October
    29, 2026 (the newest), and one dated 2031 on an old serial."""
    rows, n, k = [], 250000, 0
    for i, ym in enumerate(C.month_list(first, last)):
        y, m = int(ym[:4]), int(ym[5:])
        if ym == "2026-10":
            break
        for day, (legend, prod), parish, oper in ((3, GAS, "EXAMPLE", "Example Gas, LLC"), (9, GAS, "EXAMPLE", "Example Gas, LLC"), (15, OIL, "SAMPLE", "Sample Oil Corporation"),
                                                  (21, NOT_DRILLED, "SAMPLE", "Pat Q Sample"), (25, EXPIRED, "EXAMPLE", "Example Gas, LLC")):
            rows.append(row(date(y, m, day), n, legend, prod, parish, oper))
            n += 1
        rows.append(row(date(y, m, 18), 976000 + k, "ACTIVE- INJECTION  PRODUCED SALT WATER", "00", "SAMPLE", "Example Gas, LLC", cls="5"))
        k += 1
        if i % 12 == 5:
            rows.append(row(date(y, m, 27), 990000 + i, "PLUGGED AND ABANDONED  NO PRODUCT SPECIFIED", "00", "SAMPLE", "Sample Oil Corporation"))
        if ym == "2026-02":
            rows.append(row(date(y, m, 28), n, "ACTIVE- INJECTION  PRODUCED SALT WATER", "00", cls="5"))
            rows.append(row(date(y, m, 28), n + 1, "APPROVAL TO CONSTRUCT INJECTION WELL", "00"))
            rows.append(row(date(y, m, 28), 976900, "PERMITTED", "00"))
            n += 2
    rows.append(row(date(2026, 10, 29), n, *GAS))  # the newest permit
    rows.append(row(ms(date(2031, 2, 15)), 14523, "PLUGGED AND ABANDONED  NO PRODUCT SPECIFIED", "00"))
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
    """LA.build over a fake layer. The fixture is a tenth of the real layer, so the floors (rows, new permits in a year) are lowered for the call unless `strict`."""
    saved = LA.MIN_ROWS, LA.MIN_YEAR_NEW
    if not strict:
        LA.MIN_ROWS, LA.MIN_YEAR_NEW = 400, 30
    try:
        return LA.build(get=Net(rows).get, today=today, pause=0)
    finally:
        LA.MIN_ROWS, LA.MIN_YEAR_NEW = saved


# ------------------------------------------------------------------------------------------------ a stamp is a day, a serial is a number
d = date(2026, 6, 1)
check(all(LA.permit_day(ms(d, h)) == d for h in (0, 5, 6, 11)), "a stamp at midnight UTC or at local midnight (05:00 or 06:00 UTC) is that calendar day")
check(LA.permit_day(ms(d, 15)) is None and LA.permit_day(None) is None and LA.permit_day("2026-06-01") is None and LA.permit_day(True) is None and LA.permit_day(1e30) is None, "an afternoon, missing, text, boolean or absurd stamp is not a day")
check(LA.serial_of(255905) == 255905 and LA.serial_of(255905.0) == 255905 and LA.serial_of("255905") is None and LA.serial_of(None) is None and LA.serial_of(-4) is None and LA.serial_of(True) is None and LA.serial_of(1.5) is None,
      "a serial number is a positive whole number (a float with no fraction is read; text, a boolean or a fraction is not)")

# ------------------------------------------------------------------------------------------------ operator names the layer cut at 40 characters
cut = "GRAYROCK ENERGY IV OPERATING COMPANY, LL"
check(len(cut) == 40 and LA.operator_name(cut) == "GRAYROCK ENERGY IV OPERATING COMPANY, LLC", "a name cut at 40 characters inside its LLC is completed")
check(LA.operator_name("ABCDEFGHIJKLMNOPQRSTUVWXYZ ABCDEFGHIJK L") == "ABCDEFGHIJKLMNOPQRSTUVWXYZ ABCDEFGHIJK LLC" and LA.operator_name("ABCDEFGHIJKLMNOPQRSTUVWXYZ ABCDEFGHIJK LL.") == "ABCDEFGHIJKLMNOPQRSTUVWXYZ ABCDEFGHIJK LL.",
      "a name cut after the L is completed; a name that does not end in the cut is left alone")
check(LA.operator_name("ACME LL") == "ACME LL" and LA.operator_name("EXXONMOBIL LOW CARBON SOLUTIONS ONSHORE ") == "EXXONMOBIL LOW CARBON SOLUTIONS ONSHORE" and LA.operator_name(None) == "" and LA.operator_name("MAGNOLIA MEASUREMENT AND COMPRESSION LLC") == "MAGNOLIA MEASUREMENT AND COMPRESSION LLC",
      "a short name is not touched (it was not cut), another cut name is only trimmed, a missing one is empty")

# ------------------------------------------------------------------------------------------------ the series of a permit
r0 = row(d, 255000)
check(LA.band_of_row(r0, 255000) == "new", "a permit in the oil and gas series with no class is a new-well permit")
check(LA.band_of_row(row(d, 255000, cls="5"), 255000) == "inj" and LA.band_of_row(row(d, 255000, cls="17"), 255000) == "inj", "a UIC well class makes it an injection permit, even in the oil and gas series")
check(LA.band_of_row(row(d, 255000, cls="  "), 255000) == "new", "a blank class is no class")
check(LA.band_of_row(row(d, 976396, "PERMITTED", "00"), 976396) == "inj" and LA.band_of_row(row(d, 976370, "APPROVAL TO CONSTRUCT INJECTION WELL", "00"), 976370) == "inj", "the Office's injection series is injection")
check(LA.band_of_row(row(d, 255001, "APPROVAL TO CONSTRUCT INJECTION WELL", "00"), 255001) == "inj" and LA.band_of_row(row(d, 255002, "Commercial disposal well", "00"), 255002) == "inj", "its words (injection, disposal) make it injection in any series")
check(LA.band_of_row(row(d, 990504, "PLUGGED AND ABANDONED  NO PRODUCT SPECIFIED", "00"), 990504) == "other" and LA.band_of_row(row(d, 980000, cls="5"), 980000) == "other", "an orphan-well entry (serial 980,000 and up) is other, not a new well")
check(LA.band_of_row(row(d, 255003, "ACT 404 ORPHAN WELL-ENG  OIL", "10"), 255003) == "new" and LA.band_of_row(row(d, 255004, "PERMIT EXPIRED", "00"), 255004) == "new", "an expired permit, or a well orphaned later, is still the permit that was issued: new")

# ------------------------------------------------------------------------------------------------ parse
rows = [row(date(2025, 3, 3), 255000), row(date(2025, 3, 4), 255001, *OIL), row(date(2025, 3, 5), 255001, *OIL), row(date(2026, 12, 1), 255002), row(date(2018, 5, 5), 251000),
        row(date(2025, 3, 6), 976000, "ACTIVE- INJECTION  PRODUCED SALT WATER", "00", cls="5"), row(date(2025, 3, 7), 255003, *NOT_DRILLED)]
permits, counts = LA.parse(rows + [row(date(2025, 4, 1), 256000 + k) for k in range(93)], TODAY)
check([p["serial"] for p in permits[:5]] == [255000, 255001, 976000, 255003, 256000] and len(permits) == 97 and counts == {"bad": 0, "future": 1, "dup": 1},
      "oldest first; a serial seen twice counts once, a permit dated after today is left out, one before 2019 is skipped: %s" % counts)
check([p["fluid"] for p in permits[:4]] == ["gas", "oil", None, None] and permits[2]["band"] == "inj", "the product code is the fluid (10 oil, 20 gas); 00 is none, not recorded")
bad = [row("not a stamp", 255000 + k) for k in range(3)] + [row(date(2025, 3, 3), 256000 + k) for k in range(97)]
check(raises(lambda: LA.parse(bad, TODAY), RuntimeError) is not None, "more than 2% of the dates unreadable fails the run")
check(raises(lambda: LA.parse([row(date(2025, 3, 3), None)] * 3 + [row(date(2025, 3, 3), 256000 + k) for k in range(97)], TODAY), RuntimeError) is not None, "so does more than 2% of serial numbers unreadable")
check(raises(lambda: LA.parse([row(date(2025, 3, 3), 255000 + k) for k in range(98)] + [row(date(2026, 12, 1), 256000 + k) for k in range(3)], TODAY), RuntimeError) is not None, "more than 2% of the rows dated after today fails the run")
check(raises(lambda: LA.parse([row("x", 255000)] + [row(date(2025, 3, 3), 256000 + k) for k in range(99)], TODAY), RuntimeError) is None, "one in a hundred is tolerated")

# ------------------------------------------------------------------------------------------------ the completeness check
def new_permits(nums, day=date(2026, 9, 1)):
    return [{"day": day, "serial": s, "band": "new"} for s in nums]


check(LA.coverage(new_permits(range(255000, 255100)), date(2026, 10, 1)) == 1.0, "a hundred consecutive serial numbers are complete")
check(abs(LA.coverage(new_permits([s for s in range(255000, 255300) if s % 3]), date(2026, 10, 1)) - 0.667) < 0.01, "a layer with a third of its permits missing is two-thirds complete")
check(LA.coverage(new_permits(list(range(255000, 255100)) + [14523]), date(2026, 10, 1)) == 1.0, "an old serial with a new date (a stray) is set aside")
check(LA.coverage(new_permits(range(255000, 255010)), date(2026, 10, 1)) == 0.0 and LA.coverage([], date(2026, 10, 1)) == 0.0, "too few permits to tell is 0, which fails the run")
check(LA.coverage(new_permits(range(255000, 255100), day=date(2020, 1, 1)), date(2026, 10, 1)) == 0.0, "only the last 24 months are looked at")
inj_only = [{"day": date(2026, 9, 1), "serial": 976000 + k, "band": "inj"} for k in range(100)]
check(LA.coverage(inj_only, date(2026, 10, 1)) == 0.0, "only oil and gas permits count toward it")

# ------------------------------------------------------------------------------------------------ the query and the paging
net = Net(fixture())
saved = LA.PAGE
LA.PAGE = 250
try:
    got = LA.fetch(net.get, pause=0)
finally:
    LA.PAGE = saved
check(len(got) == len(net.rows) and len(net.urls) == 3, "the layer is read page by page until it stops saying there is more (%d rows in %d requests)" % (len(got), len(net.urls)))
q = {a: b[0] for a, b in parse_qs(urlparse(net.urls[0]).query).items()}
check(q["outFields"] == ",".join(LA.FIELDS) and q["returnGeometry"] == "false" and q["where"] == "PERMIT_DATE >= DATE '2019-01-01'" and q["f"] == "json" and q["orderByFields"] == "PERMIT_DATE,WELL_SERIAL_NUM",
      "only seven fields are asked for, no geometry, from 2019 on, in a stable order: %s" % q["outFields"])
check(not any(x in net.urls[0].upper() for x in ("API_NUM", "WELL_NAME", "COMMENTS", "SCOUT_DETAIL", "LOCATION", "LATITUDE", "LONG_DEC")), "no API number, well name, free text, location or coordinate is asked for")
check(net.urls[0].startswith(LA.LAYER + "/query?") and LA.LAYER.startswith("https://") and "/DNRSvc/OC/" in LA.LAYER, "it asks the Office of Conservation's layer (OC), not the OMR subset, over https")

# ------------------------------------------------------------------------------------------------ the document
rows = fixture()
doc = build(rows)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "LA" and doc["measure"] == "permits" and "permit date" in doc["basis"] and doc["name"] == "Louisiana" and doc["place"] == "parishes", "Louisiana, counted by permit date, its places called parishes")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-29" and len(doc["months"]) == 93,
      "from January 2019 to the last complete month (October is not over): %s to %s, asOf %s" % (doc["months"][0], doc["months"][-1], doc["asOf"]))
new, inj, other = doc["bands"]["new"], doc["bands"]["inj"], doc["bands"]["other"]
check(all(n == 5 for n in new), "five oil and gas permits every month")
check(inj[doc["months"].index("2026-02")] == 4 and all(n == 1 for ym, n in zip(doc["months"], inj) if ym != "2026-02"), "one injection permit a month, four in the month with three more (by class, by words, by series)")
check(sum(other) == 8 and other[5] == 1 and other[17] == 1, "an orphan-well entry every twelfth month is the other band (8 in 93 months)")
check(doc["bands"]["redrill"] is None and doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "re-entries, reworks and amendments are null (not told), never zero")
check(doc["fluid"] == {"oil": 12, "gas": 24, "both": 0, "other": 0, "unknown": 24}, "the last 12 months' new permits by product: %s" % doc["fluid"])
check(sum(new[-12:]) == 60 and doc["counties"] == [["Example", 36], ["Sample", 24]], "the parishes are ranked by the last 12 months' new permits: %s" % doc["counties"])
check(doc["operators"] == [["EXAMPLE GAS LLC", 36], ["SAMPLE OIL CORPORATION", 12]] and doc["namedShare"] == 0.8, "operators: the LLC and the corporation, no person; four in five permits may be named: %s" % doc["operators"])
check(doc["read"] == len(rows) - 1, "read counts every permit it took (all but the one dated 2031): %d" % doc["read"])
check("pat q" not in json.dumps(doc).lower() and "976" not in json.dumps(doc) and "250" not in json.dumps(doc).replace("2025", ""), "the person-named operator and the serial numbers are nowhere in the file")
check("one per well serial number" in doc["note"] and "re-permit" in doc["note"] and "Re-entries" in doc["note"] and "not recorded" in doc["note"], "the note says what is counted and what is not told")
check(doc["source"]["url"] == LA.LAYER and doc["cadence"] and "Conservation" in doc["agency"], "the source and the agency are named")
check(build(rows, today=date(2026, 12, 13))["asOf"] == "2026-10-29" and raises(lambda: build(rows, today=date(2026, 12, 14)), RuntimeError) is not None, "a newest permit 45 days old or more means a stale layer: the run fails (44 days is fine)")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
def err_reply(url, **k):
    return json.dumps({"error": {"code": 400, "message": "Unable to complete operation.", "details": []}}).encode()


check("error" in (raises(lambda: LA.build(get=err_reply, today=TODAY, pause=0), RuntimeError) or ""), "an error reply (HTTP 200 with an error object) fails the run")
check("layout changed" in (raises(lambda: LA.build(get=lambda u, **k: reply(fixture(), fields=LA.FIELDS[:-1]), today=TODAY, pause=0), RuntimeError) or ""), "a layer that lost the operator field fails the run: its layout changed")
check("layout changed" in (raises(lambda: LA.build(get=lambda u, **k: reply(fixture(), fields=("permit_date",) + LA.FIELDS[1:]), today=TODAY, pause=0), RuntimeError) or ""), "a renamed field fails the run")
check(raises(lambda: LA.build(get=lambda u, **k: b"[]", today=TODAY, pause=0), RuntimeError) is not None, "a reply that is not an object fails the run")
check(raises(lambda: LA.build(get=lambda u, **k: b"<html>Service unavailable</html>", today=TODAY, pause=0), ValueError) is not None, "an error page instead of JSON fails the run")
check("expected" in (raises(lambda: build(fixture()[:300]), RuntimeError) or ""), "too few rows fail the run")
check("expected" in (raises(lambda: build(fixture(), strict=True), RuntimeError) or ""), "with the real floors (2,500 rows) a layer this small is refused")
check("stale" in (raises(lambda: build([r for r in fixture() if r["PERMIT_DATE"] < ms(date(2026, 8, 1))]), RuntimeError) or ""), "a layer whose newest permit is old fails the run")
unreadable = fixture()
for r in unreadable[:200]:
    r["PERMIT_DATE"] = None
check("cannot be read" in (raises(lambda: build(unreadable), RuntimeError) or ""), "a layer whose permit dates went missing fails the run")
future = fixture()
for r in future[:100]:
    r["PERMIT_DATE"] = ms(date(2031, 1, 1))
check("after today" in (raises(lambda: build(future), RuntimeError) or ""), "a layer whose dates run into the future fails the run")
thirds = [r for i, r in enumerate(fixture()) if not (r["WELL_SERIAL_NUM"] < 970000 and r["WELL_SERIAL_NUM"] % 3 == 0)]
check("serial numbers" in (raises(lambda: build(thirds), RuntimeError) or ""), "a layer that lost a third of its oil and gas permits (a subset, like the OMR layer) fails the run, whatever its other figures")
saved_rows, saved_year = LA.MIN_ROWS, LA.MIN_YEAR_NEW
LA.MIN_ROWS, LA.MIN_YEAR_NEW = 400, 100
try:
    check("last 12 months" in (raises(lambda: LA.build(get=Net(fixture()).get, today=TODAY, pause=0), RuntimeError) or ""), "fewer new permits in the last 12 months than the floor fails the run (the layer may be cut short)")
finally:
    LA.MIN_ROWS, LA.MIN_YEAR_NEW = saved_rows, saved_year
forever = lambda url, **k: reply([row(date(2026, 1, 5), 255000)], more=True)  # noqa: E731
saved = LA.MAX_PAGES
LA.MAX_PAGES = 3
try:
    check("more pages" in (raises(lambda: LA.fetch(forever, pause=0), RuntimeError) or ""), "a layer that always says there is more stops after the page limit and fails the run")
finally:
    LA.MAX_PAGES = saved


def refuse(url, **k):
    raise C.Refused("HTTP 403 from the server")


check(raises(lambda: LA.build(get=refuse, today=TODAY, pause=0), C.Refused) is not None, "a refusal is passed up as a refusal (never retried here)")
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "LA.json")
    open(old, "w").write("committed\n")
    check(C.run_producer("LA", lambda: LA.build(get=refuse, today=TODAY, pause=0), tmp, argv=[]) == 2 and open(old).read() == "committed\n", "a refusing server ends the run with exit 2 and leaves the committed file alone")
    check(C.run_producer("LA", lambda: LA.build(get=err_reply, today=TODAY, pause=0), tmp, argv=[]) == 1 and open(old).read() == "committed\n", "a failed run exits 1 and leaves the committed file alone")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("LA", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "LA.json")), "run_producer writes nat/LA.json for it")
    check(C.check_dir(tmp) == [] and C.run_producer("LA", lambda: doc, tmp, argv=["--check"]) == 0, "the written file reloads and validates")
    written = json.load(open(os.path.join(tmp, "LA.json")))
    check(written["bands"]["new"] == doc["bands"]["new"] and written["operators"] == doc["operators"] and written["fluid"] == doc["fluid"], "and holds what the document held")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
