"""Tests for site/pipeline/d11_nat_va.py: Virginia's wells drilled (Virginia Energy's DGO wells map service, by the date drilling was completed).

Virginia publishes no permit date by well in open data, so the producer counts wells by `FiDrComp` from three ArcGIS layers (Active, Plugged, Waste Disposal) and says so (`measure` spuds, a basis in words, the months
ending 60 days before the read). The service is faked here with invented wells (file numbers T-0001..., made-up companies and a made-up person). The tests pin the query (since 2019, no geometry, no farm or well-name field),
the bands and fluid from the well type, a well in two layers counted once, paging, the privacy rule on a person-named operator, the document's honest labels, and the failures that must stop the run (an error answer,
a page that is not JSON, too few wells, unreadable dates, a stale layer, paging that never ends, a server that refuses this machine).

Run: python3 -I tests/test_d11_va.py"""
import datetime
import json
import os
import re
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_va as VA  # noqa: E402

FAILS = []
D = datetime.date
TODAY = D(2026, 11, 1)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(d):
    return None if d is None else int((d - D(1970, 1, 1)).days * 86400 * 1000)


def well(fino, co, county, typ, day):
    return {"FiNo": fino, "CoName": co, "TblCnName": county, "TblOpDesc": typ, "FiDrComp": ms(day)}


RIDGE, APP, CARBON, WASTE = "Ridge Methane Company LLC", "Appalachian Gas Partners LP", "Carbon Co Inc", "Waste Water LLC"
L0 = [
    well("T-0001", RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2025, 9, 10)),
    well("T-0002", RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2025, 10, 2)),
    well("T-0003", APP, "DICKENSON", "Gas/Pipeline", D(2026, 2, 14)),
    well("T-0004", RIDGE, "BUCHANAN", "Oil", D(2026, 3, 3)),
    well("T-0005", CARBON, "WISE", "Carbon Credit", D(2026, 4, 20)),
    well("T-0006", "Doe, Jane", "BUCHANAN", "Coalbed/Pipeline", D(2026, 5, 5)),  # a person: counted, never named
    well("T-0007", RIDGE, "BUCHANAN", "Conversion", D(2024, 6, 27)),
    well("T-0008", RIDGE, "BUCHANAN", "Service Well", D(2023, 7, 1)),
    well("T-0009", RIDGE, "BUCHANAN", "Horizontal Gas", D(2022, 1, 15)),
]
L5 = [well("T-0010", RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2025, 11, 11)), well("T-0001", RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2025, 9, 10))]  # the second is in two layers
L6 = [well("T-0011", WASTE, "BUCHANAN", "Waste Disposal w/ PL", D(2019, 5, 1))]
LAYERS = {0: L0, 5: L5, 6: L6}
VA.MIN_ROWS, VA.MIN_ACTIVE = 8, 4  # the fixture is a handful of wells; the real floors are 150 and 100


class Svc:
    """The ArcGIS service: answers a layer's query from its rows, `page` rows at a time, and remembers what was asked."""

    def __init__(self, layers=LAYERS, page=None, raw=None):
        self.layers, self.page, self.raw, self.asked = layers, page, raw or {}, []

    def get(self, url, **kw):
        self.asked.append(url)
        layer = int(re.search(r"MapServer/(\d+)/query", url).group(1))
        if layer in self.raw:
            return self.raw[layer]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        rows = self.layers[layer]
        off = int(q.get("resultOffset", ["0"])[0])
        chunk = rows[off:off + self.page] if self.page else rows
        body = {"features": [{"attributes": a} for a in chunk]}
        if self.page and off + self.page < len(rows):
            body["exceededTransferLimit"] = True
        return json.dumps(body).encode()


svc = Svc()
doc = VA.build(get=svc.get, today=TODAY, pause=0)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(len(svc.asked) == 3 and [int(re.search(r"MapServer/(\d+)/", u).group(1)) for u in svc.asked] == [0, 5, 6], "three requests, one per layer (Active, Plugged, Waste Disposal)")
q = urllib.parse.parse_qs(urllib.parse.urlparse(svc.asked[0]).query)
check("2019-01-01" in q["where"][0] and q["returnGeometry"] == ["false"] and set(q["outFields"][0].split(",")) == {"FiNo", "CoName", "TblCnName", "TblOpDesc", "FiDrComp"}, "the query asks for wells drilled since 2019, with no geometry and five fields")
check(not any(f in u for u in svc.asked for f in ("FiFarm", "FiOperation", "FiStPlane", "FiElev")), "no farm, well-name or location field is ever requested")
check(doc["state"] == "VA" and doc["measure"] == "spuds" and doc["basis"].startswith("date drilling was completed") and doc["unit"] == "wells drilled", "it says what it counts: wells drilled by the date drilling was completed, measure spuds")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-08" and doc["through"] == "2026-08-31" and doc["asOf"] == "2026-11-01", "months run to 60 days before the read (August for a November 1 read); asOf is the read")
m = {ym: i for i, ym in enumerate(doc["months"])}
new, inj, other = doc["bands"]["new"], doc["bands"]["inj"], doc["bands"]["other"]
check(sum(new) == 8 and new[m["2025-09"]] == 1 and new[m["2025-11"]] == 1 and new[m["2022-01"]] == 1 and new[m["2026-05"]] == 1, "new wells by month: a plugged well counts, a well in two layers once (8 in all)")
check(sum(inj) == 2 and inj[m["2023-07"]] == 1 and inj[m["2019-05"]] == 1 and sum(other) == 1 and other[m["2024-06"]] == 1, "a service well and a waste disposal well are inj, a conversion is other")
check(doc["bands"]["redrill"] is None and doc["bands"]["rework"] is None and doc["bands"]["amend"] is None, "bands the source cannot tell are null")
check(doc["fluid"] == {"oil": 1, "gas": 5, "both": 0, "other": 0, "unknown": 1}, "the last year's new wells by fluid: coalbed and gas are gas, oil is oil, carbon credit is unknown: %s" % doc["fluid"])
check(doc["counties"][0] == ["Buchanan", 5] and ["Dickenson", 1] in doc["counties"] and ["Wise", 1] in doc["counties"], "counties are the places, ranked")
check([o[0] for o in doc["operators"]] == ["RIDGE METHANE COMPANY LLC", "APPALACHIAN GAS PARTNERS LP", "CARBON CO INC"] and [o[1] for o in doc["operators"]] == [4, 1, 1], "operators are the companies of the last year, ranked")
check(abs(doc["namedShare"] - 6 / 7) < 0.001, "a person's well counts in the year but is not named: 6 of 7 named")
blob = json.dumps(doc)
check("Doe" not in blob and "DOE" not in blob and "T-00" not in blob, "no person's name and no well file number is in the file")
check("no permit issue date" in doc["note"] and "never added to permits" in doc["note"] and "2026-05-05" in doc["note"] and "zeroOk" not in doc, "the note says it is not permits and gives the newest well's day")

# a layer paged by the server is read to the end, and the wells that straddle pages are not lost
sp = Svc(page=3)
dp = VA.build(get=sp.get, today=TODAY, pause=0)
check(dp["bands"] == doc["bands"] and dp["read"] == doc["read"] and len(sp.asked) > 3, "paging 3 wells at a time gives the same counts (%d requests)" % len(sp.asked))
check(any("resultOffset=3" in u for u in sp.asked) and any("resultOffset=6" in u for u in sp.asked), "the next page is asked for by resultOffset")

# a quiet two years (read in full) is a real zero
quiet = {0: [well("T-%04d" % i, RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2022, 3, 3)) for i in range(1, 9)] + [well("T-0100", RIDGE, "BUCHANAN", "Service Well", D(2026, 6, 6))], 5: [], 6: []}
dq = VA.build(get=Svc(quiet).get, today=TODAY, pause=0)
check(sum(dq["bands"]["new"][-24:]) == 0 and dq.get("zeroOk") is True and C.validate(dq, TODAY) == [], "no new well in two years, read in full: a real zero, zeroOk, and it validates")

# the bands from Virginia's own well types
check([VA.well_band(x) for x in ("Coalbed/Pipeline", "Coal Bed", "Gas", "Gas/Pipeline", "Horizontal Gas", "Horizontal Coalbed", "Oil", "Carbon Credit", "Carbon Credit w/Pipeline")] == ["new"] * 9, "gas, coalbed, horizontal, oil and carbon credit wells are new wells")
check([VA.well_band(x) for x in ("Waste Disposal", "Waste Disposal w/ PL", "Service Well")] == ["inj"] * 3 and [VA.well_band(x) for x in ("Conversion", "Conversion/Pipeline", "", None, "Something else")] == ["other"] * 5, "disposal and service wells are inj; a conversion, a blank and an unknown word are other")

# failures stop the run


def boom(svc_, today=TODAY):
    try:
        VA.build(get=svc_.get, today=today, pause=0)
        return False
    except RuntimeError:
        return True


check(boom(Svc(raw={5: json.dumps({"error": {"code": 400, "message": "Failed to execute query."}}).encode()})), "an error answer from a layer fails the run")
check(boom(Svc(raw={0: b"<html>Service unavailable</html>"})), "a page that is not JSON fails the run")
check(boom(Svc(raw={6: json.dumps({"count": 3}).encode()})), "an answer with no feature list fails the run")
plugged = [well("T-02%02d" % i, RIDGE, "BUCHANAN", "Coalbed/Pipeline", D(2025, 1, 10)) for i in range(8)]
check(boom(Svc({0: L0[:3], 5: plugged, 6: []})), "the Active Wells layer giving 3 wells (floor in this test is 4) fails the run, though 11 wells were read in all")
VA.MIN_ACTIVE = 1
check(boom(Svc({0: L0[:3], 5: L5[:1], 6: []})), "too few wells in all (floor in this test is 8) fails the run, by that floor alone")
VA.MIN_ACTIVE = 4
smudged = {0: L0 + [dict(L0[0], FiNo="T-0300", FiDrComp="not a date"), dict(L0[0], FiNo="T-0301", FiDrComp=None)], 5: L5, 6: L6}
check(boom(Svc(smudged)), "11 good wells but 2 of 13 dates unreadable (past 5%) fails the run: the date format may have changed")
junk = {0: [dict(w, FiDrComp="not a date") for w in L0], 5: L5, 6: L6}
check(boom(Svc(junk)), "drilling dates that cannot be read fail the run")
check(boom(Svc(), today=D(2029, 1, 1)), "a newest well years old fails the run (a live layer showing nothing recent is a broken read)")
endless = Svc()
endless.get = lambda url, **kw: json.dumps({"features": [{"attributes": L0[0]}], "exceededTransferLimit": True}).encode()
check(boom(endless), "paging that never ends fails the run")
empty_more = Svc()
empty_more.get = lambda url, **kw: json.dumps({"features": [], "exceededTransferLimit": True}).encode()
check(boom(empty_more), "a server that says there is more and sends nothing fails the run")
VA.MIN_ROWS, VA.MIN_ACTIVE = 150, 100
check(boom(Svc()), "with the real floors (150 wells, 100 in the Active layer) this small fixture is refused")
VA.MIN_ROWS, VA.MIN_ACTIVE = 8, 4

with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("VA", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "VA.json")), "run_producer writes nat/VA.json for it")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("VA", lambda: VA.build(get=refused, today=TODAY, pause=0), tmp, argv=[]) == 2 and not os.listdir(tmp), "a server that refuses this machine is an answer: exit 2, nothing written")
    check(C.run_producer("VA", lambda: VA.build(get=Svc(raw={0: b"x"}).get, today=TODAY, pause=0), tmp, argv=[]) == 1 and not os.listdir(tmp), "a failed read exits 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
