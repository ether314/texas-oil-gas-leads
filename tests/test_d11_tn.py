"""Tests for site/pipeline/d11_nat_tn.py: Tennessee's permits (TDEC, Division of Mineral and Geologic Resources) from the "Oil and Gas Wells" ArcGIS layer behind its Data Viewer.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; PERMIT_DATE in epoch milliseconds at midnight UTC; PERMIT_NO a zero-padded
number; PURPOSE_OF_WELL in the layer's own words: Dry & Abandoned, Well Location, Abandoned Loc, Oil, Oil And Gas, Gas, Shut-in Gas, NCG - Domestic, and the service and test kinds Disposal, UIC...).
It pins: that a date must be a calendar day (a moment that is not midnight UTC would move a permit across a month end), that every oil or gas purpose is a new-well permit and a service or test purpose
is not (and is told in the note), a purpose never seen, one count per permit number, that holes in the numbering and a cut-short layer fail the run, the fluid from the purpose, the 60-day lag
and the read day as asOf, that only the columns asked for are requested (no API number, well name, location or elevation), that the honest agent string is sent on every request, the privacy rule
on a person-named operator, paging by OBJECTID, and that a damaged layer (an error reply, a renamed column, too few rows, a stale newest permit) fails the run instead of writing a short file.
The network is faked.

Run: python3 -I tests/test_d11_tn.py"""
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
import d11_nat_tn as TN  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)  # the layer's newest permit below is Aug 6, as on the real layer that day


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)


def attrs(oid, number, when, purpose="Dry & Abandoned", county="Overton", operator="Alpha Oil Corporation"):
    return {"OBJECTID": oid, "PERMIT_DATE": when, "PERMIT_NO": "%07d" % number if isinstance(number, int) else number, "COUNTY": county, "OPERATOR_NAME": operator, "PURPOSE_OF_WELL": purpose}


def reply(rows, more=False, names=TN.FIELDS):
    return json.dumps({"fields": [{"name": n} for n in names], "features": [{"attributes": r} for r in rows], **({"exceededTransferLimit": True} if more else {})}).encode()


class Layer:
    """A fake of the layer: answers `OBJECTID > N` with the next rows by OBJECTID, `resultRecordCount` at a time, and returnCountOnly with `total`. Remembers every address and header."""

    def __init__(self, rows, total=16614, names=TN.FIELDS):
        self.rows, self.total, self.names, self.urls, self.headers = sorted(rows, key=lambda r: r["OBJECTID"]), total, names, [], []

    def get(self, url, **kw):
        self.urls.append(url)
        self.headers.append(kw.get("headers"))
        q = parse_qs(urlparse(url).query)
        if q.get("returnCountOnly") == ["true"]:
            return json.dumps({"count": self.total}).encode()
        last = int(q["where"][0].split(">")[1].split()[0])
        n = int(q["resultRecordCount"][0])
        rest = [r for r in self.rows if r["OBJECTID"] > last]
        return reply(rest[:n], more=len(rest) > n, names=self.names)


PURPOSES = ["Dry & Abandoned"] * 5 + ["Well Location", "Oil", "Oil And Gas", "Gas", "Shut-in Gas", "Abandoned Loc", "NCG - Domestic"]


def synthetic(first=(2019, 1), last=(2026, 8), last_day=6, per_month=4, extra=()):
    """Invented permits, `per_month` a month from `first` to `last` (the last month ends on `last_day`), numbered in order from 12000 with no gap. Every purpose of the layer's oil and gas
    vocabulary comes round; three counties; two corporations, an LLC and one person."""
    rows, oid, number = [], 0, 12000
    ops = ["Alpha Oil Corporation", "Beta Energy, LLC", "Gamma Drilling Co.", "Rader, Richard A. Jr."]
    y, m = first
    while (y, m) <= last:
        for k in range(per_month):
            day = min(2 + 7 * k, last_day if (y, m) == last else 28)
            oid += 1
            number += 1
            rows.append(attrs(oid, number, ms(y, m, day), purpose=PURPOSES[(oid * 5) % len(PURPOSES)], county=["Overton", "Clay", "Pickett"][oid % 3], operator=ops[oid % 4]))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for r in extra:
        oid += 1
        number += 1
        rows.append(dict({"OBJECTID": oid, "PERMIT_NO": "%07d" % number}, **r))
    return rows


def build(rows, today=TODAY, total=16614, **kw):
    return TN.build(get=Layer(rows, total, **kw).get, today=today, pause=0)


def fails(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False
    except RuntimeError:
        return True


# ------------------------------------------------------------------------------------------------ a date is a calendar day
D = TN.calendar_day
check(D(ms(2026, 8, 6)) == date(2026, 8, 6) and D(ms(2019, 1, 1)) == date(2019, 1, 1) and D(float(ms(2026, 3, 25))) == date(2026, 3, 25), "midnight UTC is that calendar day")
check(D(ms(2026, 8, 6, 5)) is None and D(ms(2026, 8, 6, 0, 1)) is None and D(ms(2026, 8, 5, 19)) is None, "a moment that is not midnight UTC is no day (a layer stored in local time would move permits across a month end)")
check(all(D(x) is None for x in (None, "", "2026-08-06", True, 0, 1792865363, -86400000, float("nan"), 5e12)), "a missing, text, boolean, second-count, negative or far-future date is no day")
check(TN.number_of("0013409") == 13409 and TN.number_of(" 13409 ") == 13409 and TN.number_of("129-36") is None and TN.number_of("") is None and TN.number_of(None) is None and TN.number_of("12x") is None,
      "a permit number is a plain number; the old style (129-36) and anything else is not")

# ------------------------------------------------------------------------------------------------ the purposes, in the layer's own words
rows = [attrs(1, 100, ms(2026, 4, 1), "Dry & Abandoned"), attrs(2, 101, ms(2026, 4, 2), "Well Location"), attrs(3, 102, ms(2026, 4, 3), "Abandoned Loc"), attrs(4, 103, ms(2026, 4, 4), "Oil"),
        attrs(5, 104, ms(2026, 4, 5), "Oil And Gas"), attrs(6, 105, ms(2026, 4, 6), "Gas"), attrs(7, 106, ms(2026, 4, 7), "Shut-in Gas"), attrs(8, 107, ms(2026, 4, 8), "NCG - Domestic"),
        attrs(9, 108, ms(2026, 4, 9), ""), attrs(10, 109, ms(2026, 4, 10), None)]
p, facts = TN.parse(rows, TODAY)
check(len(p) == 10 and facts["service"] == 0, "every oil or gas purpose of the layer, and a blank one, is a permit to drill a well: all ten are counted as new")
check([x["fluid"] for x in p] == [None, None, None, "oil", "both", "gas", "gas", None, None, None], "fluid: Oil is oil, Oil And Gas both, Gas and Shut-in Gas gas; a dry hole, a location, an abandoned location, NCG - Domestic and a blank say nothing")
svc_rows = [attrs(i + 1, 200 + i, ms(2026, 4, 1 + i), x) for i, x in enumerate(["Disposal", "Salt Water Disp", "UIC", "Monitor", "Water", "Test", "Min Core Test"])] + [attrs(8, 207, ms(2026, 4, 9), "Oil")]
p, facts = TN.parse(svc_rows, TODAY)
check(len(p) == 1 and facts["service"] == 7 and facts["holes"] == 0, "a disposal, injection, monitoring, water or test well is not a new oil or gas well: left out, counted for the note, and its number is not a hole in the numbering")
check(set(p[0]) == {"day", "county", "operator", "fluid"}, "a permit keeps only a day, a county, an operator and a fluid (no number)")
check(fails(TN.parse, [attrs(1, 100, ms(2026, 4, 1), "Gas Storage")], TODAY) and fails(TN.parse, [attrs(1, 100, ms(2026, 4, 1), "Frobnicate 1234")], TODAY), "a purpose never seen fails the run")
check(not fails(TN.parse, [attrs(1, 100, ms(2026, 4, 1), "  dry &   ABANDONED ")], TODAY), "case and spacing are not part of a purpose")

# ------------------------------------------------------------------------------------------------ one permit once; the numbering
dup = [attrs(1, 100, ms(2026, 4, 1)), attrs(2, 100, ms(2026, 4, 1)), attrs(3, 101, ms(2026, 4, 2))]
p, facts = TN.parse(dup, TODAY)
check(len(p) == 2 and facts["repeats"] == 1, "a permit number that comes twice is one permit")
hole = [attrs(i, 100 + i, ms(2026, 4, 1 + i % 25)) for i in range(0, 100) if i != 50]
p, facts = TN.parse(hole, TODAY)
check(facts["holes"] == 1 and len(p) == 99, "one number missing from the series is told (1 in 100 is fine)")
check(fails(TN.parse, [attrs(i, 100 + i, ms(2026, 4, 1 + i % 25)) for i in range(0, 100) if i % 10 != 5], TODAY), "10 percent of the numbers missing fails the run: the layer is cut short")
undated = [attrs(1, 100, ms(2026, 4, 1)), attrs(2, 101, None), attrs(3, "129-36", None), attrs(4, 102, ms(2026, 4, 3)), attrs(5, 50, None)]
p, facts = TN.parse(undated, TODAY)
check(len(p) == 2 and facts["undated"] == 1, "a row with no date and a plain number inside the series is told and never counted; a number below the series or in the old style is not the series")
check(fails(TN.parse, [attrs(i, 100 + i, None) for i in range(TN.MAX_UNDATED + 1)] + [attrs(999, 1, ms(2026, 4, 1))], TODAY), "more undated numbered rows than the handful there could be fail the run")

# ------------------------------------------------------------------------------------------------ dates that cannot be read
base = [attrs(i, 1000 + i, ms(2026, 4, 3)) for i in range(1, 201)]
check(not fails(TN.parse, base[:197] + [attrs(i, 1000 + i, ms(2026, 4, 3, 7)) for i in range(198, 201)], TODAY), "a few rows (under 2 percent) with a date that is not a day are dropped, not fatal")
check(fails(TN.parse, base[:190] + [attrs(i, 1000 + i, ms(2026, 4, 3, 7)) for i in range(191, 201)], TODAY), "5 percent of the rows with a moment that is not midnight UTC fail the run")
check(fails(TN.parse, base[:190] + [attrs(i, 1000 + i, ms(2031, 1, 1)) for i in range(191, 201)], TODAY) and fails(TN.parse, base[:190] + [attrs(i, 1000 + i, ms(2005, 1, 3)) for i in range(191, 201)], TODAY),
      "5 percent of the rows dated in the future, or before 2019 (a filter the layer ignored), fail the run")
check(fails(TN.parse, base[:190] + [attrs(i, "x%d" % i, ms(2026, 4, 3)) for i in range(191, 201)], TODAY), "5 percent of the rows with a permit number that is not a number fail the run")

# ------------------------------------------------------------------------------------------------ reading the layer
rowsx = synthetic()
net = Layer(rowsx)
saved = TN.PAGE
TN.PAGE = 50
got = TN.fetch(net.get, pause=0)
TN.PAGE = saved
check(len(got) == len(rowsx) and len(net.urls) == -(-len(rowsx) // 50) and len({r["OBJECTID"] for r in got}) == len(rowsx), "every row comes back once, %d rows in %d requests of 50, paged by OBJECTID" % (len(got), len(net.urls)))
q = parse_qs(urlparse(net.urls[0]).query)
check(q["returnGeometry"] == ["false"] and set(q["outFields"][0].split(",")) == {"OBJECTID", "PERMIT_DATE", "PERMIT_NO", "COUNTY", "OPERATOR_NAME", "PURPOSE_OF_WELL"} and q["orderByFields"] == ["OBJECTID"], "the request asks for five columns and the row id, no geometry, in OBJECTID order")
check(not any(w in q["outFields"][0] for w in ("API", "WELL_NAME", "LATITUDE", "LONGITUDE", "ELEVATION", "FORMATION")), "no API number, well name, location, elevation or formation is asked for")
check("2019-01-01" in q["where"][0] and "NOT LIKE '%-%'" in q["where"][0] and q["where"][0].startswith("OBJECTID > 0 AND ("), "only permits dated from 2019 on, and undated rows with a plain number, are asked for (the 3,190 old ones are not)")
check(all(u.startswith("https://tdeconline.tn.gov/arcgis/") for u in net.urls), "it asks TDEC's map server only")
net2 = Layer(rowsx)
doc = TN.build(get=net2.get, today=TODAY, pause=0)
check(len(net2.urls) == 2 and "returnCountOnly" in net2.urls[1] and all(h == {"User-Agent": "Mozilla/5.0 (compatible; oil-tracker research)"} for h in net2.headers), "two requests (the rows, then a count of the whole table), each with the honest agent string and no other header")
check("User-Agent" in TN.HEADERS and "@" not in TN.HEADERS["User-Agent"] and "research" in TN.HEADERS["User-Agent"], "the agent string identifies no person")


def fetch_fails(get):
    try:
        TN.fetch(get, pause=0)
        return False
    except RuntimeError:
        return True


check(fetch_fails(lambda url, **kw: json.dumps({"error": {"code": 400, "message": "Unable to complete operation. /secret/path"}}).encode()), "an error reply fails the run")
check(fetch_fails(Layer(rowsx, names=[n for n in TN.FIELDS if n != "PERMIT_DATE"]).get) and fetch_fails(Layer(rowsx, names=[n for n in TN.FIELDS if n != "PURPOSE_OF_WELL"]).get), "a renamed or missing column fails the run")
check(fetch_fails(lambda url, **kw: b"[]") and fetch_fails(lambda url, **kw: json.dumps({"fields": [{"name": n} for n in TN.FIELDS]}).encode()), "a reply that is not a list of rows fails the run")
check(fetch_fails(lambda url, **kw: reply([attrs(5, 100, ms(2026, 4, 3))], more=True)), "paging that does not advance fails the run, it does not loop")
n_calls = [0]


def endless(url, **kw):
    n_calls[0] += 1
    return reply([attrs(n_calls[0], 100 + n_calls[0], ms(2026, 4, 3))], more=True)


check(fetch_fails(endless) and n_calls[0] == TN.MAX_PAGES, "a layer that always has more rows is read %d times and then fails" % TN.MAX_PAGES)
check(fails(TN.fetch_total, lambda url, **kw: json.dumps({"count": "many"}).encode()) and fails(TN.fetch_total, lambda url, **kw: json.dumps({"error": {"code": 500}}).encode()), "a count that is not a number, or an error, fails the run")

# ------------------------------------------------------------------------------------------------ the document
problems = C.validate(doc, date(2026, 11, 2))
check(problems == [], "what it writes validates: %s" % problems[:2])
check(doc["state"] == "TN" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-08" and len(doc["months"]) == 92 and doc["through"] == "2026-08-31" and doc["asOf"] == "2026-11-01",
      "92 months from January 2019 to August 2026 (60 days before the read are not shown: Sep 30 + 60 days is past Nov 1); asOf is the day of the read")
check(all(doc["bands"][b] is None for b in ("inj", "redrill", "rework", "amend", "other")) and isinstance(doc["bands"]["new"], list) and len(doc["bands"]["new"]) == 92,
      "only new wells are told: every other band is null, never zero")
check(doc["bands"]["new"][doc["months"].index("2024-03")] == 4 and doc["bands"]["new"][-1] == 4 and sum(doc["bands"]["new"]) == len(rowsx) and doc["read"] == len(rowsx), "four a month, every permit counted once (%d)" % sum(doc["bands"]["new"]))
check(set(doc["fluid"]) == set(C.FLUIDS) and sum(doc["fluid"].values()) == sum(doc["bands"]["new"][-12:]) and doc["fluid"]["oil"] > 0 and doc["fluid"]["gas"] > 0 and doc["fluid"]["both"] > 0 and doc["fluid"]["unknown"] > doc["fluid"]["oil"],
      "the last 12 months by fluid add up to the year's new wells, most unknown (dry holes and locations): %s" % doc["fluid"])
check({c[0] for c in doc["counties"]} == {"Overton", "Clay", "Pickett"} and [c[1] for c in doc["counties"]] == sorted((c[1] for c in doc["counties"]), reverse=True), "counties are ranked by new wells")
check({o[0] for o in doc["operators"]} == {"ALPHA OIL CORPORATION", "BETA ENERGY LLC", "GAMMA DRILLING CO."}, "operators are corporate names (a corporation, an LLC and a company), ranked")
check(abs(doc["namedShare"] - 0.75) < 0.01, "a person's name is counted as unnamed (3 of 4 permits are named): %s" % doc["namedShare"])
text = json.dumps(doc)
check("Rader" not in text and "RADER" not in text, "the person-named operator is nowhere in the file")
check(not any("%07d" % n in text or str(n) in text for n in (12001, 12100, 12300)), "no permit number is in the file")
check("monthly" in doc["cadence"] and "permit date" in doc["basis"] and doc["source"]["url"].startswith("https://tdeconline.tn.gov/") and "Division" in doc["agency"], "the source, the cadence and the basis are named")
check("August 6, 2026" in doc["note"] and "60 days" in doc["note"] and "monthly" in doc["note"] and "without a gap" in doc["note"] and "percent" in doc["note"], "the note says the newest permit's day, the 60-day lag, that the Division updates monthly, the numbering and the dry-hole share")
check("disposal" not in doc["note"] and "No permit has been recorded" not in doc["note"], "and says nothing about service wells or a quiet spell when there is none to tell")

# a column that was not asked for cannot reach the file, even if the layer sends it
leaky = [dict(r, API_NO="12345678900", WELL_NAME_AND_NO="Invented Lease 12", LATITUDE=36.4, LONGITUDE=-85.2, ELEVATION=890.5, FORMATION_AT_TOTAL_DEPTH="Knox Group") for r in rowsx]
doc_l = build(leaky)
tl = json.dumps(doc_l)
check(not any(s in tl for s in ("12345678900", "Invented", "36.4", "85.2", "890.5", "Knox")) and doc_l == doc, "an API number, a well name, a location, an elevation or a formation the layer sends anyway never reaches the file")

# service wells, a quiet spell, a hole in the numbering, an undated numbered row: each is told in the note
with_service = synthetic(extra=[{"PERMIT_DATE": ms(2026, 7, 20), "PURPOSE_OF_WELL": "Disposal", "COUNTY": "Overton", "OPERATOR_NAME": "Delta SWD LLC"}])
d_s = build(with_service)
check("1 permit for disposal, monitoring, water or test wells since 2019 is not counted" in d_s["note"] and sum(d_s["bands"]["new"]) == sum(doc["bands"]["new"]) and "DELTA" not in json.dumps(d_s), "a disposal well permit is told in the note and is not a new well (and its operator is not named)")
d_q = build(synthetic(last=(2026, 8)), today=date(2026, 11, 1))
check("No permit has been recorded" not in d_q["note"], "a quiet spell is told only past 100 days: the 87 days of the real read of Nov 1 are not")
d_q2 = build(synthetic(last=(2026, 8)), today=date(2026, 12, 20))
check("No permit has been recorded for 136 days" in d_q2["note"] and C.validate(d_q2, date(2026, 12, 21)) == [], "read on Dec 20: 136 days since Aug 6 are told, with the longest earlier gap (98 days)")
holed = [r for r in synthetic() if r["OBJECTID"] != 200]
check("1 permit number between the first and the last is not in the table" in build(holed)["note"] and "without a gap" not in build(holed)["note"], "one hole in the numbering is told in the note and the 'without a gap' claim is dropped")
d_u = build(synthetic(extra=[{"PERMIT_DATE": None, "PURPOSE_OF_WELL": "Oil", "COUNTY": "Overton", "OPERATOR_NAME": "Delta Oil LLC"}, {"PERMIT_DATE": None, "PERMIT_NO": "129-36", "PURPOSE_OF_WELL": "Oil"}]))
check("no permit date" in d_u["note"] and sum(d_u["bands"]["new"]) == sum(doc["bands"]["new"]), "a row with no date and a plain number is told in the note and never counted (the old-style number is not asked about)")

# the lag: 60 days after the month's end, from the read day
check(build(rowsx, today=date(2026, 11, 28))["through"] == "2026-08-31" and build(rowsx, today=date(2026, 11, 29))["through"] == "2026-09-30" and build(rowsx, today=date(2026, 11, 29))["bands"]["new"][-1] == 0,
      "September is shown from Nov 29 (Sep 30 + 60 days), and with no permit in it is a real zero")
check(C.validate(build(rowsx, today=date(2026, 11, 29)), date(2026, 11, 30)) == [], "and that file validates")

# ------------------------------------------------------------------------------------------------ a damaged layer fails the run
check(fails(build, rowsx, total=900) and not fails(build, rowsx, total=TN.MIN_TOTAL), "a table of under 15,000 permits in all (the real one has 16,614) fails the run")
check(fails(build, rowsx[:100]) and fails(build, []), "100 permits from 2019 on, or none, fail the run (the real layer has 405)")
check(fails(build, rowsx, today=date(2027, 8, 7)) and not fails(build, rowsx, today=date(2027, 8, 5)), "a newest permit over a year old fails the run (a stale layer): 364 days is fine, 366 is not")
check(fails(build, [dict(r, PERMIT_DATE=ms(2019, 1, 2, 5) + (r["OBJECTID"] % 2) * 3600000) for r in rowsx]), "a layer that stores its dates as local-time moments instead of days fails the run")
check(fails(build, [dict(r, PURPOSE_OF_WELL="Underground Storage") if r["OBJECTID"] == 30 else r for r in rowsx]), "a purpose never seen in one row fails the run")
check(fails(build, [r for r in rowsx if r["OBJECTID"] % 4 != 0]), "a layer with a quarter of the permits missing (holes in the numbering) fails the run")

# the written file reloads; a server that refuses is an answer
with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("TN", lambda: TN.build(get=Layer(rowsx[:100]).get, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 1 and not os.path.exists(os.path.join(tmp, "TN.json")), "a short layer writes nothing (exit 1)")
    rc = C.run_producer("TN", lambda: TN.build(get=Layer(rowsx).get, today=TODAY, pause=0), tmp, argv=[])
    written = json.load(open(os.path.join(tmp, "TN.json"))) if rc == 0 else {}
    check(rc == 0 and written == doc, "run_producer writes nat/TN.json for it, as built")
    check(C.check_dir(tmp) == [] and C.run_producer("TN", None, tmp, argv=["--check"]) == 0, "and the written file reloads clean (--check)")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("TN", lambda: TN.build(get=refused, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 2 and not os.listdir(tmp), "a server that refuses this machine is an answer (exit 2), nothing is written")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
