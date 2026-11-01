"""Tests for site/pipeline/d11_nat_il.py: Illinois's well permits, read from the Illinois State Geological Survey's ILOIL Wells layer (ArcGIS), for the National report.

A synthetic layer (invented companies, invented API numbers, dates at 06:00 UTC like the real ones) pins what a count is: one well per permit date, every kind of well under `new` (the layer cannot
tell kinds), the county from the API number's county code, the operator only if it is a corporation, LLC or partnership, the series ending at the last complete month the layer reaches. The network is
faked: paging (repeats dropped, a runaway stopped), and every way the layer can change or go stale (an error reply, a renamed column, too few rows, dates that stop parsing, API numbers of another
shape, a layer that stopped being refreshed, a refusal) fails the run instead of writing a short file, and a failed run leaves the committed file as it was.

Run: python3 -I tests/test_d11_il.py"""
import collections
import json
import os
import re
import sys
import tempfile
import urllib.parse
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_il as IL  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(d):
    return int(datetime(d.year, d.month, d.day, 6, tzinfo=timezone.utc).timestamp() * 1000)  # the layer stores midnight Central as 06:00 UTC


# ------------------------------------------------------------------------------------------------ a synthetic layer
CODES = ["193", "033", "055", "065", "101", "185", "165"]
COMPANIES = ["Prairie Test Energy, LLC", "Sample Basin Oil Co., Inc.", "Fixture Drilling Partners LP", "Doe, Jane Q.", "Roe, Richard", "Example Family Farm", "Test Pump & Service"]
NAMEABLE_UPPER = {"PRAIRIE TEST ENERGY LLC", "SAMPLE BASIN OIL CO. INC.", "FIXTURE DRILLING PARTNERS LP"}


def make_rows(last=date(2026, 8, 27), per_month=lambda i: 14 + i % 5):
    """Permits from 2019-01 to `last`: `per_month(i)` a month, spread over days 1 to 27, every kind of status (the layer's status is ignored by the producer)."""
    rows, oid = [], 0
    months = C.month_list("2019-01", C.month_of(last))
    for i, ym in enumerate(months):
        for j in range(per_month(i)):
            day = date(int(ym[:4]), int(ym[5:]), 1 + (j * 2) % 27)
            if day > last:
                day = last
            oid += 1
            rows.append({"OBJECTID": oid, "API_NUMBER": "12%s%05d00" % (CODES[(i + j) % len(CODES)], 90000 + oid), "PERMIT_DATE": ms(day), "COMPANY_NAME": COMPANIES[(i * 3 + j) % len(COMPANIES)]})
    return rows


class Layer:
    """The service, faked: answers the query by its resultOffset and resultRecordCount, and keeps the URLs it was asked."""

    def __init__(self, rows, fields=IL.FIELDS, exceeded_always=False, error=None):
        self.rows, self.fields, self.urls, self.exceeded_always, self.error = rows, fields, [], exceeded_always, error

    def get(self, url):
        self.urls.append(url)
        if self.error:
            return self.error
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        off, n = int(q["resultOffset"]), int(q["resultRecordCount"])
        chunk = self.rows[off:off + n]
        return {"fields": [{"name": f, "type": "esriFieldTypeString"} for f in self.fields], "features": [{"attributes": r} for r in chunk],
                "exceededTransferLimit": True if self.exceeded_always else (off + n < len(self.rows) or None)}


def fails(get, **kw):
    """True when the run raises RuntimeError (never writes), and what it said."""
    try:
        IL.build(get=get, today=kw.get("today", TODAY))
        return False, ""
    except RuntimeError as e:
        return True, str(e)


# ------------------------------------------------------------------------------------------------ the county table
check(len(IL.COUNTIES) == 102 and sorted(int(k) for k in IL.COUNTIES) == list(range(1, 204, 2)), "102 counties, codes 001 to 203, odd (the FIPS codes)")
check(IL.COUNTIES["193"] == "White" and IL.COUNTIES["055"] == "Franklin" and IL.COUNTIES["033"] == "Crawford" and IL.COUNTIES["163"] == "St. Clair" and IL.COUNTIES["031"] == "Cook",
      "the codes the real weekly log confirmed (White, Franklin, Crawford) and the big ones are right")
check(all(C.PLACE.match(n) for n in IL.COUNTIES.values()), "every county name passes the place rule the tally applies")
check(IL.county_of("120552533900") == "Franklin" and IL.county_of("12-193-25400-00") == "White" and IL.county_of("1205525339") == "Franklin", "an API number gives its county (12, 10 or 14 digits, with or without dashes)")
check(IL.county_of(None) is None and IL.county_of("") is None and IL.county_of("1205") is None and IL.county_of("420552533900") is None and IL.county_of("120002533900") is None,
      "a blank, a short number, another state's (42) and an unknown county code give no county, not a guess")

# ------------------------------------------------------------------------------------------------ the request and the reply
url = IL.query_url(2000)
q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
check(url.startswith("https://maps.isgs.illinois.edu/") and q["outFields"] == "OBJECTID,API_NUMBER,PERMIT_DATE,COMPANY_NAME" and q["returnGeometry"] == "false" and q["resultOffset"] == "2000",
      "the query asks for four columns and no geometry, from an https address")
check(not re.search(r"FARM|WELL_?NAME|PERMIT_NUMBER|LATITUDE|LONGITUDE|LOCATION|LEASE", url, re.I), "no farm or well name, permit number or coordinate is asked for")
good = Layer(make_rows()[:3]).get(IL.query_url(0))
rows, more = IL.parse_page(good)
check(len(rows) == 3 and set(rows[0]) == set(IL.FIELDS) and more is False, "a good page gives rows of the four columns and no further page")
check(IL.parse_page(Layer(make_rows()[:5]).get(IL.query_url(0)) | {"exceededTransferLimit": True})[1] is True, "the service's exceededTransferLimit says another page follows")


def raises(doc):
    try:
        IL.parse_page(doc)
        return False
    except RuntimeError:
        return True


check(raises({"error": {"code": 400, "message": "Unable to complete operation."}}) and raises([]) and raises("<html>busy</html>") and raises({"fields": [], "features": []}),
      "an error reply, a list, a web page and a reply with no columns are refused")
check(raises({"fields": [{"name": "API_NUMBER"}, {"name": "PERMIT_DATE"}, {"name": "COMPANY_NAME"}], "features": []}), "a layer that lost a column (OBJECTID here) is refused: its layout changed")
check(raises({"fields": [{"name": f} for f in IL.FIELDS]}) and raises({"fields": [{"name": f} for f in IL.FIELDS], "features": "none"}), "a reply with no list of rows is refused")
odd = IL.parse_page({"fields": [{"name": f} for f in IL.FIELDS], "features": [{"attributes": {"OBJECTID": 1, "PERMIT_DATE": 5}}, "junk", {"nope": 1}]})[0]
check(len(odd) == 1 and odd[0]["API_NUMBER"] is None, "a feature without attributes is skipped; a missing value is None, not an error")

# ------------------------------------------------------------------------------------------------ paging
rows = make_rows()
lay = Layer(rows)
got = IL.fetch(lay.get)
check(len(got) == len(rows) and len(lay.urls) == -(-len(rows) // IL.PAGE), "every row is read, %d rows in %d pages of %d" % (len(rows), len(lay.urls), IL.PAGE))
check(len({r["OBJECTID"] for r in got}) == len(got), "no row twice")
dup = rows[:1000] + rows[990:]  # a page shifted by ten rows (a refresh between two requests): ten repeats
check(len(IL.fetch(Layer(dup).get)) == len(rows), "rows repeated across pages are dropped by their row id")
check(fails(Layer(rows, exceeded_always=True).get)[0], "a service that always says there is more stops at the page limit and fails the run")
check(fails(Layer([], exceeded_always=True).get)[0], "a service that says there is more but gives nothing fails the run")
calls = []


def endless(url):
    calls.append(url)
    off = int(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["resultOffset"])
    return {"fields": [{"name": f} for f in IL.FIELDS], "features": [{"attributes": dict(rows[i % len(rows)], OBJECTID=off + i + 1)} for i in range(IL.PAGE)], "exceededTransferLimit": True}


ok, msg = fails(endless)
check(ok and len(calls) == IL.MAX_PAGES and "pages" in msg, "a service that never stops giving new rows is asked %d times, then the run fails: %s" % (len(calls), msg[:50]))

# ------------------------------------------------------------------------------------------------ a whole run
lay = Layer(rows)
doc = IL.build(get=lay.get, today=TODAY)
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(doc["state"] == "IL" and doc["measure"] == "permits" and doc["unit"] == "wells permitted" and "permit date" in doc["basis"], "permits by permit date, and the unit says what a count is: wells permitted")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-07" and doc["through"] == "2026-07-31" and doc["asOf"] == "2026-08-27",
      "the series runs from 2019-01 to the last complete month the layer reaches (July; August is not finished at Aug 27), asOf is the newest permit")
expect = collections.Counter()
for r in rows:
    d = datetime.fromtimestamp(r["PERMIT_DATE"] / 1000, timezone.utc).date()
    expect[C.month_of(d)] += 1
check(doc["bands"]["new"] == [expect[m] for m in doc["months"]], "each month's `new` is the number of rows dated in it")
check(all(doc["bands"][b] is None for b in ("inj", "redrill", "rework", "amend", "other")) and isinstance(doc["bands"]["new"], list), "no other kind is claimed: the layer cannot tell it, so null, never zero")
check(doc["fluid"] is None, "no fluid is claimed")
check(doc["read"] == len(rows), "`read` is the number of rows the layer gave")
names = [o[0] for o in doc["operators"]]
check(names and all(n in NAMEABLE_UPPER for n in names) and all(C.nameable(n) for n in names), "only corporations, LLCs and partnerships are named: %s" % names)
share = doc["namedShare"]
last12 = doc["months"][-12:]
n12 = sum(1 for r in rows if C.month_of(datetime.fromtimestamp(r["PERMIT_DATE"] / 1000, timezone.utc).date()) in last12)
n12n = sum(1 for r in rows if C.month_of(datetime.fromtimestamp(r["PERMIT_DATE"] / 1000, timezone.utc).date()) in last12 and r["COMPANY_NAME"].upper().replace(",", "") in NAMEABLE_UPPER)
check(share is not None and abs(share - round(n12n / n12, 3)) < 1e-9 and 0 < share < 1, "namedShare is the share of the last 12 months' permits whose operator may be named (%s)" % share)
cn = [c[0] for c in doc["counties"]]
check(cn and set(cn) <= {IL.COUNTIES[c] for c in CODES} and [c[1] for c in doc["counties"]] == sorted((c[1] for c in doc["counties"]), reverse=True), "counties are place names from the code table, ranked: %s" % cn[:4])
text = json.dumps(doc)
check(not re.search(r"Doe|Roe|Example Family|Pump & Service|DOE|ROE", text) and not re.search(r"\b12\d{10}\b", text) and not re.search(r"\b\d{9,}\b", text), "no person, no unnamed company and no API number reaches the file")
check("unit" in doc and "kinds of permits are not available" in doc["note"] and "two months behind" in doc["note"], "the note says the kinds are not available and that the layer runs behind the weekly log")
check(all("PERMIT_NUMBER" not in u and "FARM" not in u for u in lay.urls), "the requests never ask for a permit number or farm name")

# a permit dated after today (a typo) is not counted; a placeholder year and a missing date are tolerated in small numbers
more_rows = rows + [{"OBJECTID": 90001, "API_NUMBER": "121930900100", "PERMIT_DATE": ms(date(2026, 12, 25)), "COMPANY_NAME": "Prairie Test Energy, LLC"},
                    {"OBJECTID": 90002, "API_NUMBER": "121930900200", "PERMIT_DATE": None, "COMPANY_NAME": "Prairie Test Energy, LLC"},
                    {"OBJECTID": 90003, "API_NUMBER": "121930900300", "PERMIT_DATE": -5333126400000, "COMPANY_NAME": "Prairie Test Energy, LLC"}]
doc2 = IL.build(get=Layer(more_rows).get, today=TODAY)
check(doc2["bands"]["new"] == doc["bands"]["new"] and doc2["asOf"] == doc["asOf"], "a future date, a missing date and a 1800s placeholder are left out, and the series is the same")

# ------------------------------------------------------------------------------------------------ failures fail the run
ok, msg = fails(Layer(rows[:300]).get)
check(ok and "300" in msg, "too few rows fail the run: " + msg[:60])
ok, msg = fails(Layer(rows, fields=("OBJECTID", "API_NUMBER", "PERMIT_DT", "COMPANY_NAME")).get)
check(ok and "PERMIT_DATE" in msg, "a renamed date column fails the run: " + msg[:60])
ok, msg = fails(Layer(rows, error={"error": {"code": 500, "message": "busy"}, "fields": [{"name": f} for f in IL.FIELDS], "features": []}).get)
check(ok and "error" in msg and "500" in msg and "busy" not in msg, "an error reply fails the run, with its code and not its text: " + msg[:60])
unreadable = [dict(r, PERMIT_DATE="soon" if i % 20 == 0 else r["PERMIT_DATE"]) for i, r in enumerate(rows)]
ok, msg = fails(Layer(unreadable).get)
check(ok and "dates" in msg, "one permit in twenty with a date that does not read fails the run: " + msg[:60])
other_api = [dict(r, API_NUMBER="42" + r["API_NUMBER"][2:]) for r in rows]
ok, msg = fails(Layer(other_api).get)
check(ok and "county" in msg, "API numbers that stop giving a known county fail the run: " + msg[:60])
short_api = [dict(r, API_NUMBER=None) for r in rows]
check(fails(Layer(short_api).get)[0], "API numbers that are missing fail the run")
check(fails(Layer(make_rows(last=date(2026, 4, 20))).get)[0] and not fails(Layer(make_rows(last=date(2026, 8, 27))).get)[0],
      "a layer whose newest permit is more than %d days old (stopped being refreshed) fails the run; two months behind, as it is, does not" % IL.MAX_STALE_DAYS)
check(fails(Layer(make_rows(), exceeded_always=False).get, today=date(2027, 6, 1))[0], "the same layer, a year later with no new permit, fails: nothing implausibly old is published")

# the library's runner: a refusal exits 2 and a failure exits 1, neither writes, and a committed file is left as it was
with tempfile.TemporaryDirectory() as tmp:
    committed = os.path.join(tmp, "IL.json")
    check(C.run_producer("IL", lambda: IL.build(get=Layer(rows).get, today=TODAY), tmp, argv=[]) == 0 and os.path.exists(committed), "run_producer writes nat/IL.json for a good run")
    before = open(committed, "rb").read()
    check(C.check_dir(tmp) == [] and C.run_producer("IL", lambda: None, tmp, argv=["--check"]) == 0, "the written file reloads and passes --check")

    def refused(url):
        raise C.Refused("HTTP 403 from the server")

    check(C.run_producer("IL", lambda: IL.build(get=refused, today=TODAY), tmp, argv=[]) == 2, "a refusal by the server exits 2 (an answer, not an error)")
    check(C.run_producer("IL", lambda: IL.build(get=Layer(rows[:10]).get, today=TODAY), tmp, argv=[]) == 1, "a failure exits 1")
    check(open(committed, "rb").read() == before and not os.path.exists(committed + ".tmp"), "and the committed file is exactly as it was")
    check(len(os.listdir(tmp)) == 1, "nothing else is written")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
