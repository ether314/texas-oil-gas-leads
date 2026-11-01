"""Tests for site/pipeline/d11_nat_az.py: Arizona's wells by spud date, from the Oil and Gas Conservation Commission's ArcGIS layer.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; dates in epoch milliseconds at midnight UTC; the Commission's own well types,
functions and commodities such as "Helium", "Oil and Gas Exploration", "Stratigraphic Test", "Oil, Gas"; four-digit permit numbers for permitted wells and county-and-well codes such as
"99-01" for the old ones, whose spud dates are keyed in the wrong century). It pins: the day of a stamp (a spud at midnight, an edit at any hour), the bands from the layer's words (helium is
a new well but not an oil well: the fluid says "other"; storage, disposal and geothermal wells are `inj`; a stratigraphic test or an unknown type is `other`), that the re-entry, rework and
amendment bands are null, that an older well's code and a spud after today are set aside, the privacy rule on a person-named operator, that nothing but ten fields is asked for, paging,
the lag, the quiet years after the newest spud as real zeros (and `zeroOk` only then), an active year, and that a damaged layer (an error reply, a renamed field, too few rows or spuds,
unreadable dates, spuds from the future, a layer nobody edits, one that never ends, a refusal) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_az.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_az as AZ  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)


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


def ms(d, hour=0):
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


_n = [8000]


def well(spud=None, wtype="Helium", func="Exploration", comm="Helium", oper="Mesa Helium LLC", county="Apache", permit=None, status=None, edited=None, created=None, hour=0):
    """One layer row. A permit number is made up (8001 to 8999, over and over) unless given."""
    _n[0] += 1
    return {"PERMIT_ID": permit or str(8000 + _n[0] % 1000), "WELL_TYPE": wtype, "WELL_FUNCTION": func, "COMMODITY": comm, "OPERATOR": oper, "COUNTY": county,
            "SPUD_DATE": (ms(spud, hour) if isinstance(spud, date) else spud), "STATUS_DATE": ms(status) if status else None,
            "LAST_EDITED_DATE": ms(edited, 14) if edited else None, "CREATED_DATE": ms(created, 9) if created else None}


def reply(rows, more=False, fields=AZ.FIELDS):
    d = {"objectIdFieldName": "OBJECTID", "geometryType": "esriGeometryPoint", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields],
         "features": [{"attributes": r} for r in rows]}
    if more:
        d["exceededTransferLimit"] = True
    return json.dumps(d).encode()


def quiet(extra=()):
    """The shape of the real layer: 400 old wells (spud in the 1970s), a few permitted wells spud from 2019 to June 2023 and none since, permits waiting (no spud) and edits to September 2026.
    The eleven spuds that count: new (6): helium 2020-04-09, 2020-04-20 and 2020-06-11 (a person's operator), oil and gas 2022-02-19, an oil, gas and helium wildcat 2023-06-25, a helium well
    with no function 2019-05-28; injection (3): geothermal 2021-03-02, storage 2021-09-01, disposal 2022-08-08; other (2): a stratigraphic test 2021-07-15, a well of unknown type 2022-10-10.
    Set aside: a 2018 spud, three older wells (a code) with a spud in 2022, 2023 and 2027 (the wrong century)."""
    rows = [well(date(1970 + k % 9, 1 + k % 12, 1 + k % 27), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Old Oil Co", "Navajo", permit="%04d" % (100 + k), status=date(2010, 11, 1)) for k in range(400)]
    rows += [
        well(date(2020, 4, 9)), well(date(2020, 4, 20)), well(date(2020, 6, 11), oper="Pat Q Sample"),
        well(date(2022, 2, 19), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Example Oil Corp", "Navajo"),
        well(date(2023, 6, 25), "Oil and Gas Helium - Wildcat", "Unknown", "Oil, Gas, Helium", "Mesa Helium LLC", "Navajo"),
        well(date(2019, 5, 28), "Oil and Gas Exploration", None, "Helium", "Example Oil Corp", "Navajo"),
        well(date(2021, 3, 2), "Geothermal", "Geothermal Gradient", "Geothermal Energy", "Example Mining Corp", "Greenlee"),
        well(date(2021, 9, 1), "Gas Storage", "Storage", "Liquified Gas", "Example Pipeline LLC", "Apache"),
        well(date(2022, 8, 8), "Oil and Gas Exploration", "Disposal", "Water", "Example Oil Corp", "Navajo"),
        well(date(2021, 7, 15), "Oil and Gas Exploration", "Stratigraphic Test", "Information", "Example Oil Corp", "Navajo"),
        well(date(2022, 10, 10), None, "Unknown", "Unknown", "Example Oil Corp", "Navajo"),
        well(date(2018, 3, 28)),
        well(date(2022, 11, 30), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Old Oil Co", "Navajo", permit="99-01", status=date(2010, 11, 1)),
        well(date(2023, 11, 18), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Old Oil Co", "Apache", permit="99-02", status=date(2010, 11, 1)),
        well(date(2027, 5, 5), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Old Oil Co", "Graham", permit="99-03", status=date(2010, 11, 1)),
        well(None, "Helium", "Unknown", "Helium", "Mesa Helium LLC", "Apache", status=date(2026, 5, 12), edited=date(2026, 6, 10)),  # a permit waiting: no spud
        well(None, "Geothermal", "Unknown", "Geothermal Energy", "Example Mining Corp", "Greenlee", status=date(2026, 7, 24), created=date(2026, 7, 29), edited=date(2026, 9, 24)),
    ]
    return rows + list(extra)


def active():
    """The quiet layer with ten months of drilling since: two wells a month from August 2025 to May 2026 (helium in Apache, oil and gas in Navajo), and two spuds in January 2026 by a person."""
    more = []
    for ym in C.month_list("2025-08", "2026-05"):
        y, m = int(ym[:4]), int(ym[5:])
        more.append(well(date(y, m, 6)))
        more.append(well(date(y, m, 16), "Oil and Gas Exploration", "Exploration", "Oil, Gas", "Example Oil Corp", "Navajo"))
    more += [well(date(2026, 1, 20), oper="Pat Q Sample"), well(date(2026, 1, 21), oper="Pat Q Sample")]
    return quiet(more)


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
    """AZ.build over a fake layer. The fixture is a third of the real layer, so the floors (rows, spuds) are lowered for the call unless `strict`."""
    saved = AZ.MIN_ROWS, AZ.MIN_SPUDS
    if not strict:
        AZ.MIN_ROWS, AZ.MIN_SPUDS = 300, 8
    try:
        return AZ.build(get=Net(rows).get, today=today, pause=0)
    finally:
        AZ.MIN_ROWS, AZ.MIN_SPUDS = saved


# ------------------------------------------------------------------------------------------------ a stamp is a day
d = date(2020, 4, 9)
check(all(AZ.stamp_day(ms(d, h)) == d for h in (0, 5, 7, 11)), "a spud stamp at midnight UTC, at local midnight (05:00 to 07:00 UTC) or before noon is that calendar day")
check(AZ.stamp_day(ms(d, 15)) is None and AZ.stamp_day(ms(d, 23)) is None, "an afternoon stamp is not a spud day")
check(AZ.stamp_day(ms(d, 15), anytime=True) == d and AZ.stamp_day(ms(d, 23), anytime=True) == d, "but an edit's time stamp may fall at any hour")
check(AZ.stamp_day(None) is None and AZ.stamp_day("") is None and AZ.stamp_day("2020-04-09") is None and AZ.stamp_day(True) is None and AZ.stamp_day(1e30) is None, "a missing, text, boolean or absurd stamp is not a day")
check(AZ.stamp_day(98582400000) == date(1973, 2, 15) and AZ.stamp_day(-1506470400000) == date(1922, 4, 7), "a stamp of 1973 and one before 1970 are read as dates before the series")

# ------------------------------------------------------------------------------------------------ the bands and the fluid, from the layer's own words
band = lambda t, f: AZ.band_of_row({"WELL_TYPE": t, "WELL_FUNCTION": f})  # noqa: E731
check(all(band(t, f) == "new" for t, f in (("Oil and Gas Exploration", "Exploration"), ("Oil and Gas Exploration", "Production"), ("Helium", "Exploration"), ("Helium", "Unknown"), ("Gas", "Exploration"),
                                            ("Oil", "Exploration"), ("Oil and Gas Helium", "Unknown"), ("Oil and Gas Helium - Wildcat", None), ("Carbon Dioxide (CO2)", "Exploration"), ("Oil and Gas Exploration", None))),
      "oil and gas, gas, oil, helium and CO2 wells are new wells, whatever their function")
check(all(band(t, f) == "inj" for t, f in (("Gas Storage", "Storage"), ("Oil and Gas Exploration", "Disposal"), ("Gas", "Injection"), ("Carbon Dioxide (CO2)", "Monitoring"), ("Geothermal", "Geothermal Gradient"),
                                            ("Geothermal", "Exploration"), ("Oil and Gas Exploration", "Storage"))), "storage, disposal, injection, monitoring and geothermal wells are injection and other service wells")
check(band("Oil and Gas Exploration", "Stratigraphic Test") == "other" and band("Gas Storage", "Stratigraphic Test") == "other", "a stratigraphic test is other, even on a storage field")
check(band(None, "Unknown") == "other" and band("", "") == "other" and band("Unknown", "Unknown") == "other", "a well whose type is blank or unknown is other, never new")
fl = lambda c: AZ.fluid_of_row({"COMMODITY": c})  # noqa: E731
check(fl("Oil, Gas") == "both" and fl("Oil") == "oil" and fl("Gas") == "gas" and fl("Oil, Gas, Helium") == "both" and fl("Gas, Helium") == "gas", "oil and gas, oil, gas: the fluid from the commodity")
check(fl("Helium") == "other" and fl("Carbon Dioxide (CO2)") == "other" and fl("Geothermal Energy") == "other", "helium, CO2 and geothermal are other: not oil")
check(fl("Information") is None and fl("Unknown") is None and fl(None) is None and fl("") is None, "a commodity that says nothing is unknown (None)")

# ------------------------------------------------------------------------------------------------ parse
rows = quiet()
wells, edited, counts = AZ.parse(rows, TODAY)
check(len(wells) == 11 and [w["band"] for w in sorted(wells, key=lambda w: w["day"])].count("new") == 6, "eleven spuds count (6 new, 3 injection, 2 other): %d" % len(wells))
check(counts["historic"] == 3 and counts["future"] == 0 and counts["bad"] == 0, "three older wells (a code, not a permit number) with a spud date after 2018 are set aside, one of them in 2027: %s" % dict(counts))
check(edited == date(2026, 9, 24), "the layer's newest edit is the newest of the edit, created and status dates (an edit at 14:00 UTC counts): %s" % edited)
check(min(w["day"] for w in wells) == date(2019, 5, 28), "a 2018 spud is before the series and not counted")
padded = [well(date(2020, 1, 1))] * 98
check(AZ.parse([well(date(2026, 12, 1))] * 2 + padded, TODAY)[2]["future"] == 2 and len(AZ.parse([well(date(2026, 12, 1))] * 2 + padded, TODAY)[0]) == 98, "a spud after today is left out and counted")
check(AZ.parse([well(date(2026, 12, 1), status=date(2026, 12, 2))] * 2 + padded + [well(None, status=date(2026, 10, 1))], TODAY)[1] == date(2026, 10, 1), "a status date after today is not an edit")
check(raises(lambda: AZ.parse([well(date(2026, 12, 1))] * 3 + padded, TODAY), RuntimeError) is not None, "more than 2% of the spuds after today fails the run")
check(raises(lambda: AZ.parse([well(date(2026, 12, 1))] * 2 + padded, TODAY), RuntimeError) is None, "two in a hundred is tolerated")
check(raises(lambda: AZ.parse([well(date(2020, 4, 9), hour=16)] * 3 + padded, TODAY), RuntimeError) is not None, "more than 2% of the spud stamps unreadable (an afternoon stamp) fails the run")
check(raises(lambda: AZ.parse([well("not a stamp")] * 3 + padded, TODAY), RuntimeError) is not None, "a spud stamp that is text fails the run")
w, e, c = AZ.parse([well(None, edited=None)] * 5, TODAY)
check(w == [] and e is None, "rows with no spud and no date give no wells and no edit day")

# ------------------------------------------------------------------------------------------------ the query and the paging
net = Net(quiet())
saved = AZ.PAGE
AZ.PAGE = 150
try:
    got = AZ.fetch(net.get, pause=0)
finally:
    AZ.PAGE = saved
check(len(got) == len(net.rows) and len(net.urls) == 3, "the layer is read page by page until it stops saying there is more (%d rows in %d requests)" % (len(got), len(net.urls)))
q = {a: b[0] for a, b in parse_qs(urlparse(net.urls[0]).query).items()}
check(q["outFields"] == ",".join(AZ.FIELDS) and q["returnGeometry"] == "false" and q["f"] == "json" and q["orderByFields"] == "OBJECTID" and q["where"] == "1=1",
      "only the ten fields are asked for, with no geometry, in a fixed order: %s" % q["outFields"])
asked = q["outFields"].upper()
check(not any(x in asked for x in ("API", "WELL_NAME", "LEASE", "LATITUDE", "LONGITUDE", "DRILLER", "MINERAL_OWNER", "EDITOR", "LAST_EDITED_USER", "NOTES", "PRIOR_OPERATOR", "WEBSITE")),
      "no API number, well or lease name, coordinate, driller, landowner, editor or note is asked for")
check(net.urls[0].startswith(AZ.LAYER + "/query?") and AZ.LAYER.startswith("https://"), "it asks the Commission's own layer over https")

# ------------------------------------------------------------------------------------------------ the quiet years
rows = quiet()
doc = build(rows)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "AZ" and doc["measure"] == "spuds" and "spud" in doc["basis"] and doc["name"] == "Arizona", "Arizona, counted by spud date")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-06" and doc["through"] == "2026-06-30" and doc["asOf"] == "2026-09-24" and len(doc["months"]) == 90,
      "from January 2019 to the last month 60 days old before the layer's last edit (July and August are left off): %s to %s, asOf %s" % (doc["months"][0], doc["months"][-1], doc["asOf"]))
by = dict(zip(doc["months"], zip(doc["bands"]["new"], doc["bands"]["inj"], doc["bands"]["other"])))
check(by["2019-05"] == (1, 0, 0) and by["2020-04"] == (2, 0, 0) and by["2020-06"] == (1, 0, 0) and by["2022-02"] == (1, 0, 0) and by["2023-06"] == (1, 0, 0), "new wells land in the month of their spud date")
check(by["2021-03"] == (0, 1, 0) and by["2021-09"] == (0, 1, 0) and by["2022-08"] == (0, 1, 0), "a geothermal, a storage and a disposal well are injection")
check(by["2021-07"] == (0, 0, 1) and by["2022-10"] == (0, 0, 1), "a stratigraphic test and a well of unknown type are other")
check(sum(doc["bands"]["new"]) == 6 and sum(doc["bands"]["inj"]) == 3 and sum(doc["bands"]["other"]) == 2 and doc["read"] == 11, "6 new, 3 injection, 2 other, 11 read (the older wells' wrong-century spuds are not in them)")
check(by["2020-05"] == (0, 0, 0) and by["2024-01"] == (0, 0, 0) and by["2026-06"] == (0, 0, 0), "a month with no spud is a real zero, also the months since the newest spud")
check(doc["bands"]["redrill"] is None and doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "re-entries, reworks and amendments are null (not told), never zero")
check(doc["fluid"] == {"oil": 0, "gas": 0, "both": 0, "other": 0, "unknown": 0}, "the fluid is recorded (the last 12 months of new wells, none)")
check(doc["counties"] == [] and doc["operators"] == [] and doc["namedShare"] is None, "no new well in the last 12 months: no county, no operator, no share")
check(doc.get("zeroOk") is True, "two years with no new well are published as real zeros, and the document says so (zeroOk)")
check("June 2023" in doc["note"] and "September 24, 2026" in doc["note"] and "helium, not oil" in doc["note"] and "not by permit" in doc["note"] and "left off" in doc["note"],
      "the note gives the newest spud, the layer's last edit, that the recent wells are helium, that this is not permits, and what is left off")
text = json.dumps(doc)
check("Pat Q" not in text and "PAT Q" not in text.upper(), "the person-named operator is nowhere in the file")
check(not any('"%s"' % r["PERMIT_ID"] in text for r in rows if r["PERMIT_ID"].startswith("8")), "no permit number is in the file")
check(doc["source"]["url"] == AZ.LAYER and doc["cadence"], "the source and a cadence are named")

# ------------------------------------------------------------------------------------------------ an active year
doc2 = build(active())
check(C.validate(doc2, TODAY) == [] and "zeroOk" not in doc2, "with drilling in the last year: valid, and no zeroOk: %s" % C.validate(doc2, TODAY)[:2])
check(sum(doc2["bands"]["new"][-12:]) == 22 and doc2["bands"]["new"][doc2["months"].index("2025-08")] == 2 and doc2["bands"]["new"][doc2["months"].index("2026-01")] == 4, "22 new wells in the last 12 months (two a month for ten months and two by a person)")
check(doc2["fluid"] == {"oil": 0, "gas": 0, "both": 10, "other": 12, "unknown": 0}, "the fluid: 10 oil and gas wells, 12 helium wells as other (never counted as oil): %s" % doc2["fluid"])
check(doc2["counties"] == [["Apache", 12], ["Navajo", 10]], "the counties are ranked by the last 12 months' new wells: %s" % doc2["counties"])
check(doc2["operators"] == [["EXAMPLE OIL CORP", 10], ["MESA HELIUM LLC", 10]], "operators: the corporation and the LLC, no person: %s" % doc2["operators"])
check(doc2["namedShare"] == round(20 / 22, 3), "the share of new wells whose operator may be named: 20 of 22")
check("Pat Q" not in json.dumps(doc2) and "PAT Q" not in json.dumps(doc2).upper(), "and the person is still nowhere in the file")
check(doc2["asOf"] == "2026-09-24" and "May 2026" in doc2["note"], "the newest spud in the note is May 2026")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
def err_reply(url, **k):
    return json.dumps({"error": {"code": 500, "message": "Error performing query operation", "details": []}}).encode()


check("error" in (raises(lambda: AZ.build(get=err_reply, today=TODAY, pause=0), RuntimeError) or ""), "an error reply (HTTP 200 with an error object) fails the run")
check("layout changed" in (raises(lambda: AZ.build(get=lambda u, **k: reply(quiet(), fields=AZ.FIELDS[:-1]), today=TODAY, pause=0), RuntimeError) or ""), "a layer that lost a field fails the run: its layout changed")
check("layout changed" in (raises(lambda: AZ.build(get=lambda u, **k: reply(quiet(), fields=[f.title() for f in AZ.FIELDS]), today=TODAY, pause=0), RuntimeError) or ""), "renamed fields fail the run")
check(raises(lambda: AZ.build(get=lambda u, **k: b"[]", today=TODAY, pause=0), RuntimeError) is not None, "a reply that is not an object fails the run")
check("not JSON" in (raises(lambda: AZ.build(get=lambda u, **k: b"<html>Just a moment...</html>", today=TODAY, pause=0), RuntimeError) or ""), "an error page instead of JSON (a Cloudflare check) fails the run")
check("expected" in (raises(lambda: build(quiet()[:200]), RuntimeError) or ""), "too few rows fail the run")
check("expected" in (raises(lambda: build(quiet(), strict=True), RuntimeError) or ""), "with the real floors (1,000 rows) a layer this small is refused")
check("expected" in (raises(lambda: build([r for r in quiet() if r["SPUD_DATE"] is None or r["PERMIT_ID"] < "0500"] + [well(date(2020, 4, 9))] * 2), RuntimeError) or ""),
      "a layer whose recent spud dates are gone (too few wells since 2019) fails the run")
check("stale" in (raises(lambda: build(quiet(), today=date(2028, 1, 1)), RuntimeError) or ""), "a layer nobody has edited for 450 days fails the run")
check(raises(lambda: build(quiet(), today=date(2027, 12, 1)), RuntimeError) is None, "one edited 433 days ago is fine")
check(raises(lambda: build([well(date(2026, 12, 1)) for _ in range(12)] + quiet()), RuntimeError) is not None, "a layer with many spuds from the future fails the run")
unreadable = quiet()
for r in unreadable[:20]:
    r["SPUD_DATE"] = "n/a"
check("cannot be read" in (raises(lambda: build(unreadable), RuntimeError) or ""), "a layer whose spud dates turned to text fails the run")
forever = lambda url, **k: reply([well(date(2020, 1, 5))], more=True)  # noqa: E731
saved = AZ.MAX_PAGES
AZ.MAX_PAGES = 3
try:
    check("more pages" in (raises(lambda: AZ.fetch(forever, pause=0), RuntimeError) or ""), "a layer that always says there is more stops after the page limit and fails the run")
finally:
    AZ.MAX_PAGES = saved


def refuse(url, **k):
    raise C.Refused("HTTP 403 from the server")


check(raises(lambda: AZ.build(get=refuse, today=TODAY, pause=0), C.Refused) is not None, "a refusal is passed up as a refusal (never retried here)")
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "AZ.json")
    open(old, "w").write("committed\n")
    check(C.run_producer("AZ", lambda: AZ.build(get=refuse, today=TODAY, pause=0), tmp, argv=[]) == 2 and open(old).read() == "committed\n", "a refusing server ends the run with exit 2 and leaves the committed file alone")
    check(C.run_producer("AZ", lambda: AZ.build(get=err_reply, today=TODAY, pause=0), tmp, argv=[]) == 1 and open(old).read() == "committed\n", "a failed run exits 1 and leaves the committed file alone")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("AZ", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "AZ.json")), "run_producer writes nat/AZ.json for it")
    check(C.check_dir(tmp) == [] and C.run_producer("AZ", lambda: doc, tmp, argv=["--check"]) == 0, "the written file reloads and validates (zeroOk and all)")
    written = json.load(open(os.path.join(tmp, "AZ.json")))
    check(written["bands"]["new"] == doc["bands"]["new"] and written["zeroOk"] is True, "and holds what the document held")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
