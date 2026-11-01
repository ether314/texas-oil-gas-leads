"""Tests for site/pipeline/d11_nat_pa.py: Pennsylvania's permits (DEP, Office of Oil and Gas Management) from its ArcGIS "Oil and Gas Wells All" layer.

The fixture is invented, written the way the layer answers (a `fields` list and `features` with `attributes`; `PERMIT_DATE` in epoch milliseconds at midnight UTC, which is the permit's own
date; DEP's well types such as "COMB. OIL&GAS" and "STORAGE WELL" and its statuses such as "Operator Reported Not Drilled"). It pins: how a date is read (a placeholder or a future day is no
day), the band and fluid of every well type in DEP's own words, that permits which expired unused or were never drilled are still permits while a duplicate record and a permit awaiting its decision
are not, that a month with no permit is a real zero and a band the layer cannot tell (re-drills, alterations) is null and never zero, the privacy rule on a person-named operator and that no column
that was not asked for reaches the file, paging by OBJECTID, and that a damaged layer (an error reply, a renamed column, too few rows, unreadable dates, a stale newest permit) fails the run
instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_pa.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_pa as PA  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)  # the invented layer's newest permit is Friday, Oct 30


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def attrs(oid, when, well="OIL", status="Active", county="Greene", operator="Alpha Gas LLC"):
    return {"OBJECTID": oid, "PERMIT_DATE": when, "WELL_TYPE": well, "WELL_STATUS": status, "COUNTY": county, "OPERATOR": operator}


def reply(rows, more=False, names=PA.FIELDS):
    return json.dumps({"fields": [{"name": n} for n in names], "features": [{"attributes": r} for r in rows], **({"exceededTransferLimit": True} if more else {})}).encode()


class Layer:
    """A fake of the layer: answers `... AND OBJECTID > N` with the next rows by OBJECTID, `resultRecordCount` at a time, as the real service does."""

    def __init__(self, rows, names=PA.FIELDS):
        self.rows, self.names, self.urls = sorted(rows, key=lambda r: r["OBJECTID"]), names, []

    def get(self, url, **kw):
        self.urls.append(url)
        q = parse_qs(urlparse(url).query)
        last = int(q["where"][0].split("OBJECTID >")[1])
        n = int(q["resultRecordCount"][0])
        rest = [r for r in self.rows if r["OBJECTID"] > last]
        return reply(rest[:n], more=len(rest) > n, names=self.names)


PLAN = [("OIL", "Greene", "Alpha Gas LLC"), ("OIL", "Greene", "Alpha Gas LLC"), ("GAS", "Bradford", "Beta Resources Inc"), ("GAS", "Bradford", "Jane Q Farmer"),
        ("COMB. OIL&GAS", "Warren", "Gamma Energy Corporation"), ("UNDETERMINED", "Warren", "Beta Resources Inc")]


def synthetic(first=(2019, 1), last=(2026, 10), last_day=30, skip=(), extra=()):
    """Invented permits, 6 a month (every month but those in `skip`, which have none), plus a storage well every January and a permit that was never drilled every month."""
    rows, oid = [], 0
    y, m = first
    while (y, m) <= last:
        if (y, m) not in skip:
            top = last_day if (y, m) == last else 27
            for i, (well, county, op) in enumerate(PLAN):
                oid += 1
                day = top if (i == len(PLAN) - 1 and (y, m) == last) else min(top, 3 + 4 * i)  # the newest permit of the invented layer falls on `last_day`
                rows.append(attrs(oid, ms(y, m, day), well, "Active" if i % 2 else "Plugged OG Well", county, op))
            oid += 1
            rows.append(attrs(oid, ms(y, m, min(top, 20)), "OIL", "Operator Reported Not Drilled", "Greene", "Alpha Gas LLC"))
            if m == 1:
                oid += 1
                rows.append(attrs(oid, ms(y, m, 12), "STORAGE WELL", "Active", "Greene", "Alpha Gas LLC"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for r in extra:
        oid += 1
        rows.append(dict(r, OBJECTID=oid))
    return rows


# ------------------------------------------------------------------------------------------------ dates
check(PA.permit_day(ms(2026, 10, 30), TODAY) == date(2026, 10, 30) and PA.permit_day(ms(2019, 1, 2), TODAY) == date(2019, 1, 2), "a permit date is the UTC date of its midnight stamp")
check(all(PA.permit_day(x, TODAY) is None for x in (-2177452800000, 0, None, "", "2026-10-30", True, ms(2026, 11, 2), ms(2031, 1, 1), 1793318400, float("nan"))),
      "the 1901 and 1970 placeholders, a missing, text, boolean, second-count or future date are no day")
check(PA.permit_day(ms(2026, 11, 1), TODAY) == date(2026, 11, 1), "today is a day")

# ------------------------------------------------------------------------------------------------ the bands and fluid, in DEP's own words
P = PA.parse([attrs(i, ms(2024, 3, 4), well=w) for i, w in enumerate(["OIL", "GAS", "COMB. OIL&GAS", "COALBED METHANE", "DRY HOLE", "UNDETERMINED", "MULTIPLE WELL BORE TYPE", None, "STORAGE WELL", "INJECTION",
                                                                      "WASTE DISPOSAL", "OBSERVATION"])], TODAY)
check([p["band"] for p in P] == ["new"] * 8 + ["inj"] * 4, "oil, gas, combined, coalbed methane, dry hole, undetermined, multiple well bore and a blank type are new wells; storage, injection, waste disposal and observation are `inj`")
check([p["fluid"] for p in P[:8]] == ["oil", "gas", "both", "gas", None, None, None, None], "fluid: oil, gas, both (combined), gas (coalbed methane), the rest not known")

# ------------------------------------------------------------------------------------------------ reading rows
rows = [attrs(1, ms(2025, 5, 5), status="Operator Reported Not Drilled"), attrs(2, ms(2025, 5, 6), status="Proposed But Never Materialized"), attrs(3, ms(2025, 5, 7), status="Duplicate"),
        attrs(4, ms(2025, 5, 8), status="Proposed Awaiting Auth Decision"), attrs(5, ms(2025, 5, 9), status="DEP Orphan List"), attrs(6, ms(2025, 5, 12), status="Regulatory Inactive Status")]
p = PA.parse(rows, TODAY)
check([x["day"].day for x in p] == [5, 6, 9, 12], "a permit that expired unused or was never drilled is still a permit; a duplicate record and a permit awaiting its decision are not")
check(set(p[0]) == {"day", "band", "county", "operator", "fluid"} and p[0]["county"] == "Greene" and p[0]["operator"] == "Alpha Gas LLC", "a permit keeps only a day, a band, a county, an operator and a fluid")


def refuses(rows_, today=TODAY):
    try:
        PA.parse(rows_, today)
        return False
    except RuntimeError:
        return True


base = [attrs(i, ms(2025, 5, 5)) for i in range(1, 201)]
check(not refuses(base[:197] + [attrs(i, None) for i in range(198, 201)]), "a few rows with no date (1.5%) are dropped, not fatal")
check(refuses(base[:190] + [attrs(i, None) for i in range(191, 201)]) and refuses(base[:190] + [attrs(i, ms(2031, 1, 1)) for i in range(191, 201)])
      and refuses(base[:190] + [attrs(i, -2177452800000) for i in range(191, 201)]) and refuses(base[:190] + [attrs(i, ms(2015, 1, 1)) for i in range(191, 201)]),
      "5% of the rows with a missing, future, placeholder or pre-2019 date fail the run")
check(not refuses(base[:100] + [attrs(i, None, status="Duplicate") for i in range(101, 201)]), "duplicates are left out before their dates are looked at")

# ------------------------------------------------------------------------------------------------ paging
rowsx = synthetic()
net = Layer(rowsx)
saved = PA.PAGE
PA.PAGE = 50
got = PA.fetch(net.get, pause=0)
PA.PAGE = saved
check(len(got) == len(rowsx) and len(net.urls) == -(-len(rowsx) // 50) and len({r["OBJECTID"] for r in got}) == len(rowsx), "every row comes back once, %d rows in %d requests of 50, paged by OBJECTID" % (len(got), len(net.urls)))
q = parse_qs(urlparse(net.urls[0]).query)
check(q["returnGeometry"] == ["false"] and set(q["outFields"][0].split(",")) == set(PA.FIELDS) and q["orderByFields"] == ["OBJECTID"] and q["where"] == ["PERMIT_DATE >= DATE '2019-01-01' AND OBJECTID > 0"],
      "the request asks for five columns and the row id, no geometry, permitted since 2019, in OBJECTID order")
check(not any(w in q["outFields"][0] for w in ("PERMIT_NUMBER", "WELL_NAME", "LATITUDE", "LONGITUDE", "MUNICIPALITY", "SITE", "WELL_PAD", "UIC", "SPUD", "API")), "no permit number, well name, location, pad or site is asked for")
check(all(u.startswith("https://gis.dep.pa.gov/") for u in net.urls), "it asks DEP's server only")


def fetch_fails(get):
    try:
        PA.fetch(get, pause=0)
        return False
    except RuntimeError:
        return True


check(fetch_fails(lambda url, **kw: json.dumps({"error": {"code": 400, "message": "Unable to complete operation. /secret/path"}}).encode()), "an error reply fails the run")
check(fetch_fails(Layer(rowsx, names=[n for n in PA.FIELDS if n != "PERMIT_DATE"]).get) and fetch_fails(Layer(rowsx, names=[n for n in PA.FIELDS if n != "OPERATOR"]).get), "a renamed or missing column fails the run")
check(fetch_fails(lambda url, **kw: b"[]") and fetch_fails(lambda url, **kw: json.dumps({"fields": [{"name": n} for n in PA.FIELDS]}).encode()), "a reply that is not a list of rows fails the run")
check(fetch_fails(lambda url, **kw: reply([attrs(5, ms(2026, 4, 3))], more=True)), "paging that does not advance fails the run, it does not loop")
n_calls = [0]


def endless(url, **kw):
    n_calls[0] += 1
    return reply([attrs(n_calls[0], ms(2026, 4, 3))], more=True)


check(fetch_fails(endless) and n_calls[0] == PA.MAX_PAGES, "a layer that always has more rows is read %d times and then fails" % PA.MAX_PAGES)

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
def build_fails(rows_, today=TODAY):
    try:
        PA.build(get=Layer(rows_).get, today=today, pause=0)
        return False
    except RuntimeError:
        return True


check(PA.MIN_ROWS >= 4000 and build_fails(rowsx) and build_fails([]), "a layer of a few hundred rows (the real one has 6,500) fails the run: too few rows")
PA.MIN_ROWS = 100  # the invented layer is small; the floor is tested above
doc = PA.build(get=Layer(rowsx).get, today=TODAY, pause=0)
problems = C.validate(doc, date(2026, 11, 2))
check(problems == [], "what it writes validates: %s" % problems[:2])
check(doc["state"] == "PA" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and len(doc["months"]) == 93 and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-30",
      "93 months from January 2019 to the last complete month (September 2026); asOf is the newest permit, Friday Oct 30")
check(all(doc["bands"][b] is None for b in ("redrill", "rework", "amend", "other")) and isinstance(doc["bands"]["new"], list) and isinstance(doc["bands"]["inj"], list),
      "re-drills, reworks, amendments and other filings are not told (null, never zero); new wells and injection wells are")
check(all(n == 7 for n in doc["bands"]["new"]) and sum(doc["bands"]["inj"]) == 8 and doc["bands"]["inj"][0] == 1 and doc["bands"]["inj"][1] == 0,
      "7 new wells every month (6 planned and 1 never drilled), and a storage well each January (8 in all), zero in the other months")
check(doc["fluid"] == {"oil": 36, "gas": 24, "both": 12, "other": 0, "unknown": 12} and sum(doc["fluid"].values()) == sum(doc["bands"]["new"][-12:]),
      "the last 12 months of new wells by fluid: oil, gas, both, unknown (undetermined): %s" % doc["fluid"])
check(doc["counties"][0] == ["Greene", 36] and {c[0] for c in doc["counties"]} == {"Greene", "Bradford", "Warren"}, "counties are ranked by new wells")
check([o[0] for o in doc["operators"]] == ["ALPHA GAS LLC", "BETA RESOURCES INC", "GAMMA ENERGY CORPORATION"] and doc["operators"][0][1] == 36, "operators are corporate names, ranked")
check(0 < doc["namedShare"] < 1 and abs(doc["namedShare"] - 6 / 7) < 0.001, "a person's name is counted as unnamed (6 of 7 new wells are named)")
check("Farmer" not in json.dumps(doc) and "FARMER" not in json.dumps(doc), "the person-named operator is nowhere in the file")
check("expired unused" in doc["note"] and "not told" in doc["note"] and "555 against 576" in doc["note"], "the note says unused permits stay in, that re-drills and alterations are not told, and how the layer compares with DEP's own count")
check(doc["source"]["url"].startswith("https://gis.dep.pa.gov/") and "permit date" in doc["basis"] and doc["read"] == len(rowsx), "the source and the basis are named; read counts every record")

# a column that was not asked for cannot reach the file, even if the layer sends it
leaky = [dict(r, PERMIT_NUMBER="999-99999", WELL_NAME="Invented Farm 1H", LATITUDE=40.123456, LONGITUDE=-80.123456, MUNICIPALITY="Invented Township", SITE_NAME="Invented Pad") for r in rowsx]
doc_l = PA.build(get=Layer(leaky).get, today=TODAY, pause=0)
tl = json.dumps(doc_l)
check(not any(s in tl for s in ("999-99999", "Invented", "40.123", "80.123")) and doc_l == doc, "a permit number, a well name, a location or a municipality the layer sends anyway never reaches the file")

# a month with no permit is a real zero, not a gap
gap = PA.build(get=Layer(synthetic(skip=((2022, 3),))).get, today=TODAY, pause=0)
i = gap["months"].index("2022-03")
check(len(gap["months"]) == 93 and gap["bands"]["new"][i] == 0 and gap["bands"]["new"][i - 1] == 7 and C.validate(gap, date(2026, 11, 2)) == [], "a month with no permit stays on the axis as a real zero")

# the newest permit decides asOf and the stale test
check(PA.build(get=Layer(synthetic(last_day=31)).get, today=date(2026, 11, 2), pause=0)["through"] == "2026-10-31", "a permit on the last day of the month makes that month complete")
check(build_fails(rowsx, today=date(2026, 11, 12)) and not build_fails(rowsx, today=date(2026, 11, 9)), "a newest permit more than 10 days old fails the run (a stale layer): 10 days is fine, 13 is not")
check(build_fails(rowsx[:60]) and build_fails([]), "and with the floor lowered, 60 rows or none still fail")
check(build_fails([dict(r, WELL_STATUS="Duplicate") for r in rowsx]), "a layer of duplicates only fails the run")

# a layer whose history was cut (no permit before 2025) must not be shown as zeros for 2019 to 2024: the run fails and nothing is written
short = synthetic(first=(2025, 1))
check(build_fails(short) and not build_fails(synthetic(first=(2019, 1))) and build_fails(synthetic(first=(2019, 3))), "a layer whose first permit is after January 2019 fails the run: the months before it would be zeros")
with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("PA", lambda: PA.build(get=Layer(short).get, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 1 and not os.path.exists(os.path.join(tmp, "PA.json")), "and so run_producer writes nothing (exit 1)")
    rc = C.run_producer("PA", lambda: PA.build(get=Layer(rowsx).get, today=TODAY, pause=0), tmp, argv=[])
    written = json.load(open(os.path.join(tmp, "PA.json"))) if rc == 0 else {}
    check(rc == 0 and written == doc, "run_producer writes nat/PA.json for it, as built")
    check(C.check_dir(tmp) == [], "and the written file reloads clean")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    rc = C.run_producer("PA", lambda: PA.build(get=refused, today=TODAY, pause=0), tmp, argv=[])
    check(rc == 2 and not os.listdir(tmp), "a server that refuses this machine is an answer (exit 2), nothing is written")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
