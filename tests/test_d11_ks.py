"""Tests for site/pipeline/d11_nat_ks.py: Kansas's drilling permits (KCC notices of intent to drill) from the Kansas Geological Survey's ArcGIS wells layer.

The fixture is invented, written the way the layer answers (`fields` and `features` with `attributes`, `PERMIT_DATE` in epoch milliseconds, API numbers with or without a four-digit
workover suffix, well-type codes such as OIL, D&A, EOR, SWD, CATH). It pins: the kinds (new, injection, re-entry, other) from the well type and the API suffix, what is left out (a cancelled API
number, a denied injection application), that an expired permit still counts, the fluid, the privacy rule on a person-named operator (a dba, a surname with no company word, a blank), paging that
follows what each page gave, and that a damaged layer (an error reply, a renamed field, rows lost between pages, too few rows, unreadable dates, an API number or type code that no longer
fits, a year with too few permits, too many other filings, a stale newest permit, endless paging) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_ks.py"""
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
import d11_nat_ks as KS  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# the shipped floors suit what the real layer holds (8,878 rows; 548 permits in the lowest year; 586 new wells in the last 12 months); the small fixture needs lower ones
check(KS.MIN_ROWS < 8878 and KS.MIN_YEAR < 548 and KS.MIN_NEW12 < 586 and KS.MIN_ROWS >= 1000, "the shipped floors sit below what the real layer holds")
KS.MIN_ROWS, KS.MIN_YEAR, KS.MIN_NEW12 = 500, 50, 20

EXAMPLE, SAMPLE = "Example Oil Company, LLC", "Sample Energy, Inc."


def ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def row(n, d, wtype="OIL", cls="Producing", county="Exampleton", oper=EXAMPLE, suffix=""):
    api = "15-901-%05d%s" % (n, "-" + suffix if suffix else "")
    return {"API_NUMBER": api, "PERMIT_DATE": ms(d) if isinstance(d, date) else d, "WELL_TYPE": wtype, "WELL_CLASS": cls, "COUNTY": county, "OPERATOR_NAME": oper}


def fixture():
    """Every month from 2019-01 to 2026-10: two oil, one gas and one dry-hole permit (new), an EOR and a SWD (injection), one oil permit on an API with suffix 0001 (re-entry), one
    cathodic-protection hole (other): 8 a month. March 2026 also holds the odd ones."""
    rows, n = [], 1
    for ym in C.month_list("2019-01", "2026-10"):
        y, m = int(ym[:4]), int(ym[5:])
        for day, wtype, county, oper, suffix in ((3, "OIL", "Exampleton", EXAMPLE, ""), (5, "OIL", "Exampleton", EXAMPLE, ""), (9, "GAS", "Sampleville", SAMPLE, ""), (12, "D&A", "Sampleville", SAMPLE, ""),
                                                  (15, "EOR", "Exampleton", EXAMPLE, ""), (18, "SWD", "Sampleville", SAMPLE, ""), (20, "OIL", "Exampleton", EXAMPLE, "0001"), (20, "CATH", "Sampleville", SAMPLE, "")):
            rows.append(row(n, date(y, m, day), wtype, "Producing", county, oper, suffix))
            n += 1
    d = date(2026, 3, 10)
    rows += [
        row(n + 1, d, "CBM", county="Sampleville", oper=SAMPLE),  # new, gas
        row(n + 2, d, "O&G"),  # new, both
        row(n + 3, d, "LH", county="Sampleville", oper=SAMPLE),  # a lost hole: new, fluid unknown
        row(n + 4, d, "OIL", suffix="0100"),  # a horizontal on a new API number: new
        row(n + 5, d, "OIL", suffix="0101"),  # a horizontal re-entry: re-entry
        row(n + 6, d, "SWD", suffix="0001"),  # an old well re-entered to dispose: re-entry, not injection
        row(n + 7, d, "CATH", suffix="0001", county="Sampleville", oper=SAMPLE),  # other
        row(n + 8, d, "W-INJ", oper=SAMPLE, county="Sampleville"),  # injection
        row(n + 9, d, "OBS"), row(n + 10, d, "STRAT"), row(n + 11, d, "WATER"), row(n + 12, d, "HY"),  # four kinds that are not oil, gas or injection wells: other
        row(n + 13, d, "OIL", cls="Cancelled API Number"),  # left out
        row(n + 14, d, "SWD", cls="UIC Application Denied"),  # left out
        row(n + 15, d, "OIL", cls="Expired Intent to Drill (C-1)"),  # issued and unspent: still a permit
        row(n + 16, d, "OIL", oper="Doe, Jane dba Jane Oil Co"),  # a person trading under a name: counted, never named
        row(n + 17, d, "OIL", oper="Roe, Richard"),  # a person with no company word: counted, never named
        row(n + 18, d, "OIL", oper=""),  # no operator: counted
        row(n + 19, d, "OIL", county=""),  # no county: counted, no place
    ]
    return rows


NEW_IDX = C.month_list("2019-01", "2026-09").index("2026-03")


class Net:
    """The layer: answers a count and pages of rows the way ArcGIS does. `page` is how many rows a page really gives (the layer's own limit may be lower than asked)."""

    def __init__(self, rows, page=2000, fields=KS.FIELDS, count=None):
        self.rows, self.page, self.fields, self.count = rows, page, fields, count
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        q = parse_qs(urlparse(url).query)
        if "returnCountOnly" in q:
            return json.dumps({"count": len(self.rows) if self.count is None else self.count}).encode()
        off = int(q["resultOffset"][0])
        part = self.rows[off:off + min(self.page, int(q["resultRecordCount"][0]))]
        d = {"objectIdFieldName": "OBJECTID", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in self.fields], "features": [{"attributes": r} for r in part]}
        if off + len(part) < len(self.rows):
            d["exceededTransferLimit"] = True
        return json.dumps(d).encode()


def build(rows=None, today=TODAY, **kw):
    net = Net(rows if rows is not None else fixture(), **kw)
    return KS.build(get=net.get, today=today, pause=0), net


# ------------------------------------------------------------------------------------------------ small parts
b = KS.band_of
check(b("OIL", 0) == ("new", True) and b("gas", 0) == ("new", True) and b("O&G", 0) == ("new", True) and b("CBM", 0) == ("new", True) and b("D&A", 0) == ("new", True) and b("LH", 0) == ("new", True),
      "oil, gas, oil and gas, coal bed methane, dry hole and lost hole on a new API number are new wells")
check(all(b(t, 0) == ("inj", True) for t in ("EOR", "SWD", "INJ", "W-INJ", "CO2-INJ", "GSW", "CLASS1", "NHDW", "OIL&GAS-INJ")), "enhanced recovery, disposal, injection, storage and class I types are injection wells")
check(b("OIL", 1) == ("redrill", True) and b("GAS", 3) == ("redrill", True) and b("D&A", 1) == ("redrill", True), "a workover code above zero is a re-entry")
check(b("EOR", 1) == ("redrill", True) and b("SWD", 2) == ("redrill", True), "an old well re-entered to inject or dispose is a re-entry, not a new injection well")
check(all(b(t, 0) == ("other", True) and b(t, 1) == ("other", True) for t in ("CATH", "WATER", "STRAT", "OBS", "HELIUM", "HY")), "cathodic-protection, water, stratigraphic and observation holes are other filings, with or without a suffix")
check(b("PETROLEUM", 0) == ("other", False) and b("", 0) == ("other", False) and b(None, 0) == ("other", False), "a type in no table is other and flagged unknown (never a new well by default)")
check(KS.API.match("15-901-00001") and KS.API.match("15-901-00001-0001").group(2) == "01" and KS.API.match("15-901-00001-0100").group(2) == "00" and KS.API.match("15-901-00001-0100").group(1) == "01"
      and not KS.API.match("1590100001") and not KS.API.match("15-901-0001") and not KS.API.match(""), "an API number is 10 digits with dashes and an optional four-digit suffix whose last two digits are the workover code")
u = urlparse(KS.url_for(4000))
q = parse_qs(u.query)
check(u.netloc == "services2.arcgis.com" and q["where"] == ["PERMIT_DATE >= DATE '2019-01-01'"] and q["returnGeometry"] == ["false"] and q["resultOffset"] == ["4000"] and q["f"] == ["json"]
      and q["outFields"] == [",".join(KS.FIELDS)] and "OPERATOR_NAME" in KS.FIELDS, "the request asks for the six fields only, no geometry, from 2019")
check(not (set(KS.FIELDS) & {"LEASE_NAME", "WELL_NAME", "KGS_ID", "KID", "NAD27_LATITUDE", "NAD27_LONGITUDE", "COMMENTS", "FIELD_NAME", "CURR_OPERATOR"}), "no lease, well name, coordinate, comment or other column is requested")
check(parse_qs(urlparse(KS.url_for(count=True)).query).get("returnCountOnly") == ["true"], "the count request asks for the count only")

# ------------------------------------------------------------------------------------------------ parse
p = KS.parse(fixture(), TODAY)
check(len(p) == 769 and p == sorted(p, key=lambda x: x["day"]), "two voided rows are left out (771 rows, 769 permits), oldest first")
check(not any(x["band"] == "other" and x["fluid"] for x in p) and {x["fluid"] for x in p if x["band"] == "new"} == {"oil", "gas", "both", None}, "a fluid is kept for new wells only; a dry or lost hole has none")
check(sum(1 for x in KS.parse([row(1, date(2026, 3, 1), cls="  cancelled api number ")], TODAY)) == 0, "the status is read without regard to case or spaces")
check(len(KS.parse([row(1, date(2026, 3, 1), cls="Expired Intent to Drill (C-1)"), row(2, date(2026, 3, 1), cls="Plugged and Abandoned"), row(3, date(2026, 3, 1), cls="Approved Intent to Drill")], TODAY)) == 3,
      "expired, plugged and approved permits all count: a permit is counted by its date, never by what became of it")


def fails(fn, text=None):
    try:
        fn()
        return False
    except RuntimeError as e:
        return text is None or text in str(e)
    except Exception as e:  # noqa: BLE001
        print("     unexpected %s: %s" % (type(e).__name__, str(e)[:80]))
        return False


many = [row(i + 1, date(2026, 3, 1)) for i in range(100)]
check(fails(lambda: KS.parse(many[:90] + [row(i, "not a date") for i in range(10)], TODAY), "cannot be read"), "10% of the dates not reading fails the run")
check(len(KS.parse(many + [row(999, "not a date")], TODAY)) == 100, "one date that does not read (under 2%) is skipped")
check(len(KS.parse(many + [row(999, date(2026, 12, 25))], TODAY)) == 100, "a date after today is skipped, not counted")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
doc, net = build()
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "KS" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-20",
      "permits by month from 2019-01 to the last complete month; asOf is the newest permit")
bands = doc["bands"]
check(bands["new"][0] == 4 and bands["inj"][0] == 2 and bands["redrill"][0] == 1 and bands["other"][0] == 1, "an ordinary month: 4 new, 2 injection, 1 re-entry, 1 other")
i = NEW_IDX
check((bands["new"][i], bands["inj"][i], bands["redrill"][i], bands["other"][i]) == (13, 3, 3, 6), "March 2026 with the odd rows: 13 new, 3 injection, 3 re-entries, 6 other (two voided rows not counted): %s"
      % ((bands["new"][i], bands["inj"][i], bands["redrill"][i], bands["other"][i]),))
check(bands["rework"] is None and bands["amend"] is None, "recompletions and amendments are not told by the layer: null, never zero")
check(doc["read"] == 769, "read counts the permits it kept")
check(doc["fluid"] == {"oil": 30, "gas": 13, "both": 1, "other": 0, "unknown": 13} and sum(doc["fluid"].values()) == sum(bands["new"][-12:]) == 57,
      "the last 12 months' new wells by fluid add up to the new total (57): %s" % doc["fluid"])
check(doc["counties"] == [["Exampleton", 30], ["Sampleville", 26]], "places are county names, ranked (a permit with no county has none): %s" % doc["counties"])
check(doc["operators"] == [["EXAMPLE OIL COMPANY LLC", 28], ["SAMPLE ENERGY INC.", 26]], "operators are companies only: %s" % doc["operators"])
check(doc["namedShare"] == round(54 / 57, 3), "54 of 57 new wells have a nameable operator (a dba, a surname and a blank do not): %s" % doc["namedShare"])
blob = json.dumps(doc)
check(not any(s in blob for s in ("Jane", "Doe", "Roe", "Richard", "15-901", "dba")), "no person-named operator and no API number reaches the file")
check(all(o[0] != "" and C.nameable(o[0]) for o in doc["operators"]), "every operator listed passes the naming rule")
check("workover" in doc["note"] and "cancelled" in doc["note"] and "one permit date" in doc["note"] and "approval" in doc["note"] and "cathodic" in doc["note"], "the note says what the kinds are, what is left out and the one-date limit")
check(net.urls[0].endswith("returnCountOnly=true") or "returnCountOnly=true" in net.urls[0], "the layer's count is read first")
check(len(net.urls) == 1 + 1 and all(urlparse(x).netloc == "services2.arcgis.com" for x in net.urls), "771 rows come in one page: two requests, one host (%d)" % len(net.urls))
doc2, net2 = build(page=300)
check(doc2 == doc and len(net2.urls) == 1 + 3, "a layer that gives 300 rows a page, whatever was asked, is followed page by page and gives the same file (%d requests)" % len(net2.urls))

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
good = fixture()


def mod(rows, pred, **changes):
    """The rows with `changes` made to those `pred` picks (copies: the fixture is not touched)."""
    return [dict(r, **changes) if pred(r) else r for r in rows]


def year_of(r):
    return datetime.fromtimestamp(r["PERMIT_DATE"] / 1000, timezone.utc).year


check(fails(lambda: KS.build(get=lambda url, **kw: json.dumps({"error": {"code": 499, "message": "Token Required"}}).encode(), today=TODAY, pause=0), "error (code 499)"), "an error reply fails the run, with its code and no address")
check(fails(lambda: build(fields=tuple(f for f in KS.FIELDS if f != "WELL_TYPE")), "WELL_TYPE"), "a layer that lost a field fails the run and names it")
check(fails(lambda: build(count=len(good) + 5), "changed while it was read"), "rows lost between pages (the count says more than was read) fail the run")
n_calls = Net(good[:50])
check(fails(lambda: KS.build(get=n_calls.get, today=TODAY, pause=0), "expected 500 or more") and len(n_calls.urls) == 1, "too few rows fail the run at the count, before any page is read")
check(fails(lambda: build(mod(good, lambda r: r["WELL_TYPE"] == "OIL", PERMIT_DATE="n/a")), "cannot be read"), "dates that no longer read fail the run")
check(fails(lambda: build([dict(r, API_NUMBER=r["API_NUMBER"].replace("-", "")) for r in good]), "cannot be read"), "an API number of another shape fails the run")
check(fails(lambda: build(mod(good, lambda r: r["WELL_TYPE"] == "OIL", WELL_TYPE="PETROLEUM")), "codes"), "well-type codes the KGS list does not explain fail the run")
check(fails(lambda: build(mod(good, lambda r: r["WELL_TYPE"] in ("GAS", "D&A", "EOR"), WELL_TYPE="WATER")), "other filings"), "a layer where half the permits turn into other filings fails the run")
check(fails(lambda: build(today=date(2026, 12, 15)), "stale"), "a newest permit older than three weeks fails the run (a layer that stopped rebuilding)")
check(fails(lambda: build([r for r in good if year_of(r) != 2021]), "2021"), "a year with no permits fails the run and names the year")


def endless(url, **kw):
    """A layer that says there is always more (and gives 100 rows every time)."""
    if "returnCountOnly" in url:
        return json.dumps({"count": 100 * KS.MAX_PAGES}).encode()
    return json.dumps({"fields": [{"name": f} for f in KS.FIELDS], "features": [{"attributes": r} for r in good[:100]], "exceededTransferLimit": True}).encode()


check(fails(lambda: KS.build(get=endless, today=TODAY, pause=0), "more pages than expected"), "a layer that never stops giving pages fails the run (it never wanders)")
check(KS.MAX_PAGES * 2000 >= 3 * 8878, "the page limit leaves room for the layer to triple in size")


def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("KS", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "KS.json")), "run_producer writes nat/KS.json for it")
    check(C.check_dir(tmp) == [], "and the file reloads clean")
with tempfile.TemporaryDirectory() as tmp:
    code = C.run_producer("KS", lambda: KS.build(get=refuse, today=TODAY, pause=0), tmp, argv=[])
    check(code == 2 and not os.listdir(tmp), "a refusal (HTTP 403) exits 2 and writes nothing")
with tempfile.TemporaryDirectory() as tmp:
    code = C.run_producer("KS", lambda: build(fields=("X",))[0], tmp, argv=[])
    check(code == 1 and not os.listdir(tmp), "a failed run exits 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
