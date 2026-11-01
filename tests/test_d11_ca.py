"""Tests for site/pipeline/d11_nat_ca.py: California's permits (CalGEM) from the WellSTAR "Approved Notice of Intention/Permit" ArcGIS layer.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; `NoticeDateDetermination` in epoch milliseconds, UTC; kinds such as
"NOI - New Drill"; CalGEM's well types such as "Cyclic Steam" and "Waterflood"). It pins: that a UTC instant is read as a California day (an approval at 5 pm on the last day of a month stays
in that month, in daylight and in standard time), the band of every kind of notice and well type in CalGEM's own words (plugging of a disposal well is not a new injection well), the fluid,
that canceled notices are left out, the part month at the start of the layer and when it is dropped, the privacy rule on a person-named operator and that no column that was not asked for
reaches the file, paging by OBJECTID, and that a damaged layer (an error reply, a renamed column, too few rows, a status or kind never seen, unreadable dates, a stale newest approval, too
short a history) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_ca.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_ca as CA  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)  # California's day: the layer's newest approval below is Friday, Oct 30


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(y, m, d, hh=19, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)


def attrs(oid, kind, when, well="Oil & Gas", status="Approved", county="Kern", operator="Alpha Petroleum LLC"):
    return {"OBJECTID": oid, "NoticeType": kind, "NoticeStatus": status, "NoticeDateDetermination": when, "WellTypeLabel": well, "County": county, "OperatorName": operator}


def reply(rows, more=False, names=CA.FIELDS):
    return json.dumps({"fields": [{"name": n} for n in names], "features": [{"attributes": r} for r in rows], **({"exceededTransferLimit": True} if more else {})}).encode()


class Layer:
    """A fake of the layer: answers `OBJECTID > N` with the next rows by OBJECTID, `resultRecordCount` at a time, as the real service does."""

    def __init__(self, rows, names=CA.FIELDS):
        self.rows, self.names, self.urls = sorted(rows, key=lambda r: r["OBJECTID"]), names, []

    def get(self, url, **kw):
        self.urls.append(url)
        q = parse_qs(urlparse(url).query)
        last = int(q["where"][0].split(">")[1])
        n = int(q["resultRecordCount"][0])
        rest = [r for r in self.rows if r["OBJECTID"] > last]
        return reply(rest[:n], more=len(rest) > n, names=self.names)


def synthetic(first=(2024, 11, 14), last=(2026, 10, 30), extra=()):
    """About two years of invented notices: every month from `first` to `last` has plugging, reworks, a sidetrack, and New Drill notices of every well type, from three companies and one person."""
    rows, oid = [], 0
    y, m = first[0], first[1]
    while (y, m) <= (last[0], last[1]):
        day0 = first[2] if (y, m) == (first[0], first[1]) else 2
        day1 = last[2] if (y, m) == (last[0], last[1]) else 26
        spread = [day0 + round(k * (day1 - day0) / 9) for k in range(10)]  # ten days from day0 to day1, both included
        plan = ([("NOI - Abandon", "Oil & Gas", "Alpha Petroleum LLC", "Kern")] * 4 + [("NOI - Rework", "Cyclic Steam", "Beta Energy Corporation", "Kern")] * 2
                + [("NOI - Sidetrack", "Oil & Gas", "Beta Energy Corporation", "Fresno")] + [("NOI - Re-Abandon", "Water Disposal", "Alpha Petroleum LLC", "Kern")]
                + [("NOI - New Drill", "Oil & Gas", "Alpha Petroleum LLC", "Kern")] * 3 + [("NOI - New Drill", "Cyclic Steam", "Beta Energy Corporation", "Kern")] * 2
                + [("NOI - New Drill", "Dry Gas", "Gamma Oil Company", "Ventura"), ("NOI - New Drill", "Waterflood", "Alpha Petroleum LLC", "Kern"),
                   ("NOI - New Drill", "Oil & Gas", "Jane Q Rancher", "Fresno")])
        for i, (kind, well, op, county) in enumerate(plan):
            oid += 1
            rows.append(attrs(oid, kind, ms(y, m, spread[i % len(spread)]), well=well, county=county, operator=op))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for r in extra:
        oid += 1
        rows.append(dict(r, OBJECTID=oid))
    return rows


# ------------------------------------------------------------------------------------------------ California days
check(CA.nth_sunday(2026, 3, 2) == date(2026, 3, 8) and CA.nth_sunday(2026, 11, 1) == date(2026, 11, 1) and CA.nth_sunday(2025, 11, 1) == date(2025, 11, 2) and CA.nth_sunday(2025, 3, 2) == date(2025, 3, 9),
      "daylight time starts on the second Sunday of March and ends on the first Sunday of November")
check(CA.pacific_day(ms(2026, 5, 1, 5, 30)) == date(2026, 4, 30), "5:30 UTC on May 1 is 10:30 pm on April 30 in daylight time: the last day of April")
check(CA.pacific_day(ms(2026, 5, 1, 7, 30)) == date(2026, 5, 1) and CA.pacific_day(ms(2026, 5, 1, 6, 59)) == date(2026, 4, 30), "midnight in daylight time is 7:00 UTC")
check(CA.pacific_day(ms(2026, 12, 1, 7, 59)) == date(2026, 11, 30) and CA.pacific_day(ms(2026, 12, 1, 8, 0)) == date(2026, 12, 1), "midnight in standard time is 8:00 UTC")
check(CA.pacific_day(ms(2025, 11, 2, 8, 30)) == date(2025, 11, 2) and CA.pacific_day(ms(2025, 11, 2, 9, 30)) == date(2025, 11, 2) and CA.pacific_day(ms(2025, 11, 3, 7, 30)) == date(2025, 11, 2),
      "the night daylight time ends: 8:30 UTC is 1:30 am daylight, 9:30 UTC is 1:30 am standard, and 7:30 UTC the next day is still the 2nd")
check(CA.pacific_day(ms(2026, 3, 8, 9, 59)) == date(2026, 3, 8) and CA.pacific_day(ms(2026, 3, 9, 6, 59)) == date(2026, 3, 8) and CA.pacific_day(ms(2026, 3, 9, 7, 1)) == date(2026, 3, 9),
      "the night daylight time starts: 6:59 UTC on the 9th is 11:59 pm on the 8th, 7:01 UTC is the 9th")
check(all(CA.pacific_day(x) is None for x in (None, "", "2026-10-30", True, 0, 1792865363, -5, float("nan"))), "a missing, text, boolean, second-count or negative date is no day")
check(CA.pacific_today(datetime(2026, 11, 1, 0, 20, tzinfo=timezone.utc)) == date(2026, 10, 31) and CA.pacific_today(datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc)) == date(2026, 11, 1),
      "a run at 0:20 UTC on Nov 1 is still Oct 31 in California (daylight time); at 7:05 UTC it is Nov 1")

# ------------------------------------------------------------------------------------------------ the bands, in CalGEM's own words
B = CA.band_for
check(B("NOI - New Drill", "Oil & Gas") == "new" and B("NOI - New Drill", "Cyclic Steam") == "new" and B("NOI - New Drill", "Dry Gas") == "new" and B("NOI - New Drill", "Dry Hole") == "new"
      and B("NOI - New Drill", "Stratigraphic") == "new" and B("NOI - New Drill", "Unknown") == "new" and B("NOI - New Drill", "") == "new", "a New Drill for a well that produces or explores is a new well")
check(all(B("NOI - New Drill", w) == "inj" for w in ("Water Disposal", "Waterflood", "Steamflood", "Gas Disposal", "Injection", "Pressure Maintenance", "Gas Storage", "Observation", "Water Source", "Air Injector")),
      "a New Drill for an injection, disposal, steam or water flood, storage, observation or water-source well is `inj`")
check(B("NOI - Abandon", "Water Disposal") == "other" and B("NOI - Re-Abandon", "Steamflood") == "other" and B("NOI - Abandon", "Oil & Gas") == "other", "plugging is other filings, even of an injection well: it is not a new injection well")
check(B("NOI - Rework", "Water Disposal") == "rework" and B("NOI - Rework", "Oil & Gas") == "rework" and B("NOI - Sidetrack", "Cyclic Steam") == "redrill" and B("NOI - Deepen", "Oil & Gas") == "redrill",
      "reworks are `rework`, sidetracks and deepenings `redrill`, whatever the well type")
check(B("NOI - Supplementary", "Oil & Gas") is None and B("", "") is None and B(None, None) is None and B("NOI - Frac", "x") is None, "a kind of notice never seen has no band")
check(B("noi - new drill ", "oil & gas") == "new" and B("NOI: Rework", "") == "rework", "case and the dash are not part of the kind")
F = CA.fluid_for
check(F("Oil & Gas") == "both" and F("Dry Gas") == "gas" and F("Cyclic Steam") == "oil" and F("Stratigraphic") == "other" and F("Dry Hole") is None and F("") is None and F("Unknown") is None,
      "fluid: Oil & Gas is both, Dry Gas gas, Cyclic Steam oil, the rest other or not known")

# ------------------------------------------------------------------------------------------------ reading rows
rows = [attrs(1, "NOI - New Drill", ms(2026, 4, 1, 5, 30)), attrs(2, "NOI - New Drill", ms(2026, 4, 1, 19), status="Closed"), attrs(3, "NOI - Rework", ms(2026, 4, 2), status="Canceled"),
        attrs(4, "NOI - Abandon", ms(2026, 4, 3))]
p = CA.parse(rows, TODAY)
check([(x["day"].isoformat(), x["band"]) for x in p] == [("2026-03-31", "new"), ("2026-04-01", "new"), ("2026-04-03", "other")], "an approval at 5:30 UTC on April 1 is a March permit; Approved and Closed count; Canceled is left out")
check(p[0]["operator"] == "Alpha Petroleum LLC" and p[0]["county"] == "Kern" and p[0]["fluid"] == "both" and set(p[0]) == {"day", "band", "county", "operator", "fluid"}, "a permit keeps only a day, a band, a county, an operator and a fluid")


def refuses(rows_, today=TODAY):
    try:
        CA.parse(rows_, today)
        return False
    except RuntimeError:
        return True


base = [attrs(i, "NOI - Abandon", ms(2026, 4, 3)) for i in range(1, 201)]
check(not refuses(base[:196] + [attrs(i, "NOI - Abandon", None) for i in range(197, 201)]), "a few rows with no date (2%) are dropped, not fatal")
check(refuses(base[:190] + [attrs(i, "NOI - Abandon", None) for i in range(191, 201)]) and refuses(base[:190] + [attrs(i, "NOI - Abandon", ms(2031, 1, 1)) for i in range(191, 201)])
      and refuses(base[:190] + [attrs(i, "NOI - Abandon", ms(2001, 1, 1)) for i in range(191, 201)]), "5% of the rows with a missing, future or placeholder date fail the run")
check(refuses(base[:190] + [attrs(i, "NOI - Frobnicate", ms(2026, 4, 3)) for i in range(191, 201)]), "5% of the rows with a kind of notice never seen fail the run")
check(refuses(base[:190] + [attrs(i, "NOI - Abandon", ms(2026, 4, 3), status="Pending") for i in range(191, 201)]), "5% of the rows with a status never seen fail the run")
check(not refuses(base[:150] + [attrs(i, "NOI - Abandon", ms(2026, 4, 3), status="Canceled") for i in range(151, 201)]), "canceled rows, however many, are a known status")

# ------------------------------------------------------------------------------------------------ paging
rowsx = synthetic()
net = Layer(rowsx)
saved = CA.PAGE
CA.PAGE = 50
got = CA.fetch(net.get, pause=0)
CA.PAGE = saved
check(len(got) == len(rowsx) and len(net.urls) == -(-len(rowsx) // 50) and len({r["OBJECTID"] for r in got}) == len(rowsx), "every row comes back once, %d rows in %d requests of 50, paged by OBJECTID" % (len(got), len(net.urls)))
q = parse_qs(urlparse(net.urls[0]).query)
check(q["returnGeometry"] == ["false"] and set(q["outFields"][0].split(",")) == set(CA.FIELDS) and q["orderByFields"] == ["OBJECTID"] and q["where"] == ["OBJECTID > 0"], "the request asks for six columns and the row id, no geometry, in OBJECTID order")
check(not any(w in q["outFields"][0] for w in ("API", "Lease", "WellNumber", "WellDesignation", "Latitude", "Longitude", "FieldName", "Permit")), "no API number, lease, well name, permit number or location is asked for")
check(all(u.startswith("https://gis.conservation.ca.gov/") for u in net.urls), "it asks CalGEM's server only")


def fetch_fails(get):
    try:
        CA.fetch(get, pause=0)
        return False
    except RuntimeError:
        return True


check(fetch_fails(lambda url, **kw: json.dumps({"error": {"code": 400, "message": "Unable to complete operation. /secret/path"}}).encode()), "an error reply fails the run")
check(fetch_fails(Layer(rowsx, names=[n for n in CA.FIELDS if n != "NoticeDateDetermination"]).get) and fetch_fails(Layer(rowsx, names=[n for n in CA.FIELDS if n != "OperatorName"]).get), "a renamed or missing column fails the run")
check(fetch_fails(lambda url, **kw: b"[]") and fetch_fails(lambda url, **kw: json.dumps({"fields": [{"name": n} for n in CA.FIELDS]}).encode()), "a reply that is not a list of rows fails the run")
check(fetch_fails(lambda url, **kw: reply([attrs(5, "NOI - Abandon", ms(2026, 4, 3))], more=True)), "paging that does not advance fails the run, it does not loop")
n_calls = [0]


def endless(url, **kw):
    n_calls[0] += 1
    return reply([attrs(n_calls[0], "NOI - Abandon", ms(2026, 4, 3))], more=True)


check(fetch_fails(endless) and n_calls[0] == CA.MAX_PAGES, "a layer that always has more rows is read %d times and then fails" % CA.MAX_PAGES)

# ------------------------------------------------------------------------------------------------ the part month
check(CA.last_complete_month(date(2026, 10, 31)) == "2026-10" and CA.last_complete_month(date(2026, 10, 30)) == "2026-09", "a month is complete when its last day has passed")
check(CA.start_month(date(2024, 11, 14), date(2026, 10, 31)) == ("2024-11", date(2024, 11, 14)), "a layer that starts on Nov 14: with 24 months only by counting it, the part month is kept")
check(CA.start_month(date(2024, 11, 14), date(2026, 11, 30)) == ("2024-12", None) and CA.start_month(date(2024, 11, 14), date(2027, 3, 31)) == ("2024-12", None), "and left out as soon as 24 complete months follow it")
check(CA.start_month(date(2024, 11, 1), date(2026, 10, 31)) == ("2024-11", None) and CA.start_month(date(2024, 11, 4), date(2026, 10, 31)) == ("2024-11", None), "a layer that starts in the first business days of a month starts in it")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
def build_fails(rows_, today=TODAY):
    try:
        CA.build(get=Layer(rows_).get, today=today, pause=0)
        return False
    except RuntimeError:
        return True


check(CA.MIN_ROWS >= 3000 and build_fails(rowsx) and build_fails([]), "a layer of a few hundred rows (the real one has 8,500) fails the run: too few rows")
CA.MIN_ROWS = 200  # the invented layer is small; the floor is tested above
net = Layer(rowsx)
doc = CA.build(get=net.get, today=TODAY, pause=0)
problems = C.validate(doc, date(2026, 11, 2))
check(problems == [], "what it writes validates: %s" % problems[:2])
check(doc["state"] == "CA" and doc["measure"] == "permits" and doc["months"][0] == "2024-11" and doc["months"][-1] == "2026-10" and len(doc["months"]) == 24 and doc["through"] == "2026-10-31" and doc["asOf"] == "2026-10-31",
      "24 months from the layer's first month to October 2026; asOf is yesterday in California (the newest approval is Friday the 30th, and Saturday has passed)")
check(doc["bands"]["amend"] is None and all(isinstance(doc["bands"][b], list) for b in ("new", "inj", "redrill", "rework", "other")), "amendments are not told (null), every other band is")
# the plan above holds, every month: 4 abandon + 1 re-abandon = 5 other, 2 rework, 1 sidetrack, 3+2+1+1 = 7 new, 1 inj
mid = doc["months"].index("2026-03")
check([doc["bands"][b][mid] for b in ("new", "inj", "redrill", "rework", "other")] == [7, 1, 1, 2, 5], "a full month counts 7 new wells, 1 injection well, 1 sidetrack, 2 reworks and 5 plugging notices (got %s)" % [doc["bands"][b][mid] for b in ("new", "inj", "redrill", "rework", "other")])
check(doc["fluid"] == {"oil": 24, "gas": 12, "both": 48, "other": 0, "unknown": 0} and sum(doc["fluid"].values()) == sum(doc["bands"]["new"][-12:]), "the last 12 months of new wells by fluid: oil (cyclic steam), gas, both (Oil & Gas): %s" % doc["fluid"])
check(doc["counties"][0] == ["Kern", 60] and {c[0] for c in doc["counties"]} == {"Kern", "Ventura", "Fresno"}, "counties are ranked by new wells")
check([o[0] for o in doc["operators"]] == ["ALPHA PETROLEUM LLC", "BETA ENERGY CORPORATION", "GAMMA OIL COMPANY"] and doc["operators"][0][1] == 36, "operators are corporate names, ranked")
check(0 < doc["namedShare"] < 1 and abs(doc["namedShare"] - 6 / 7) < 0.001, "a person's name is counted as unnamed (6 of 7 new wells are named)")
text = json.dumps(doc)
check("Rancher" not in text and "RANCHER" not in text, "the person-named operator is nowhere in the file")
check("part month" in doc["note"] and "November 14, 2024" in doc["note"] and "Canceled" in doc["note"] and "Amendments are not told" in doc["note"], "the note says the layer starts on Nov 14 and its first month is a part month, that amendments are not told and canceled notices are left out")
check(doc["source"]["url"].startswith("https://gis.conservation.ca.gov/") and "approval" in doc["basis"], "the source and the basis are named")
check(doc["read"] == len(rowsx) and doc["bands"]["new"][0] == 7 * 1 and doc["bands"]["other"][0] == 5, "the first month is read as the layer has it (part month: notices from Nov 14)")

# a column that was not asked for cannot reach the file, even if the layer sends it
leaky = [dict(r, API="0400000000", WellDesignation="Invented Lease 12", LeaseName="Invented Lease", Latitude=35.5, Longitude=-119.5, NoticePermitNumber="7000000") for r in rowsx]
doc_l = CA.build(get=Layer(leaky).get, today=TODAY, pause=0)
tl = json.dumps(doc_l)
check(not any(s in tl for s in ("0400000000", "Invented", "7000000", "35.5", "119.5")) and doc_l == doc, "an API number, a lease, a well name, a permit number or a location the layer sends anyway never reaches the file")

# the day after: the part month is left out once 24 complete months follow it
later = CA.build(get=Layer(synthetic(last=(2026, 11, 30))).get, today=date(2026, 12, 2), pause=0)
check(later["months"][0] == "2024-12" and later["months"][-1] == "2026-11" and len(later["months"]) == 24 and "part month" not in later["note"] and C.validate(later, date(2026, 12, 3)) == [],
      "once 24 complete months follow the part month it is left out, and the note no longer mentions it")

# asOf: when the newest approval is older than yesterday, yesterday is the day the file is complete to; a layer a long weekend old is fine, a stale one is not
check(CA.build(get=Layer(rowsx).get, today=date(2026, 11, 3), pause=0)["asOf"] == "2026-11-02", "read on Tuesday Nov 3, asOf is Monday Nov 2: the days between are complete")


check(build_fails(rowsx, today=date(2026, 11, 12)) and not build_fails(rowsx, today=date(2026, 11, 9)), "a newest approval more than 10 days old fails the run (a stale layer): 10 days is fine, 13 is not")
check(build_fails(rowsx[:100]) and build_fails([]), "and with the floor lowered, 100 rows or none still fail")
check(build_fails([dict(r, NoticeStatus="Canceled") for r in rowsx]), "a layer of canceled notices only fails the run")

# too short a history: the shared validator wants 24 months, and the run fails rather than writing a short file
short = synthetic(first=(2025, 5, 5))
with tempfile.TemporaryDirectory() as tmp:
    doc_short = CA.build(get=Layer(short).get, today=TODAY, pause=0)
    check(len(doc_short["months"]) == 18 and any("24 or more" in x for x in C.validate(doc_short, date(2026, 11, 2))), "an 18-month history is built, and the shared validator refuses it for being under 24 months")
    rc = C.run_producer("CA", lambda: CA.build(get=Layer(short).get, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 1 and not os.path.exists(os.path.join(tmp, "CA.json")), "and so run_producer writes nothing (exit 1)")
    rc = C.run_producer("CA", lambda: CA.build(get=Layer(rowsx).get, today=TODAY, pause=0), tmp, argv=[])
    written = json.load(open(os.path.join(tmp, "CA.json"))) if rc == 0 else {}
    check(rc == 0 and written == doc, "run_producer writes nat/CA.json for it, as built")
    check(C.check_dir(tmp) == [], "and the written file reloads clean")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("CA", lambda: CA.build(get=refused, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 2 and not os.listdir(tmp), "a server that refuses this machine is an answer (exit 2), nothing is written")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
