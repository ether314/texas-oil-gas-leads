"""Tests for site/pipeline/d11_nat_al.py: Alabama's permits (State Oil and Gas Board) from its ArcGIS wells layer.

The fixture is invented, written the way the layer answers (an `fields` list and `features` with `attributes`, `PermitDate` in epoch milliseconds, permit numbers with a suffix such as
-CG or -SWD-24-01). It pins: how a number is read, which permits follow the Board's number sequence (new), which are service wells (inj) and which are older-numbered (other), that a repeated
number counts once and a mistyped one does not move the sequence, the fluid, the privacy rule on a person-named operator, paging, and that a damaged layer (an error reply, a renamed field,
too few rows, unreadable dates, a numbering that no longer follows the date, a stale newest permit) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_al.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_al as AL  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(d, hour=14):
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def row(permit, d, wtype="CM", desc="Coal Bed Methane", county="Exampleton", operator="Example Gas Company, LLC"):
    return {"Permit": permit, "PermitDate": ms(d) if isinstance(d, date) else d, "WellType": wtype, "TypeDesc": desc, "CountyName": county, "Operator": operator}


def reply(rows, more=False, fields=AL.FIELDS):
    d = {"displayFieldName": "WellName", "fields": [{"name": f, "type": "esriFieldTypeString"} for f in fields], "features": [{"attributes": r} for r in rows]}
    if more:
        d["exceededTransferLimit"] = True
    return json.dumps(d).encode()


def fixture():
    """Three new permits a month from 2018-01 to 2026-09 (numbers 50000 and up, in step with the date; two coal bed methane and one oil), one on October 3, 2026 (so September is
    complete), and in 2025 and 2026 a few of every other kind."""
    rows, n = [], 50000
    for y in range(2018, 2027):
        for m in range(1, 13):
            if (y, m) > (2026, 10):
                break
            for k, county, oper in ((3, "Exampleton", "Example Gas Company, LLC"), (11, "Sampleville", "Sample Oil Corporation"), (19, "Exampleton", "Example Gas Company, LLC")):
                if (y, m) == (2026, 10) and k > 3:
                    break
                wt, desc = ("OIL", "Oil") if k == 11 else ("CM", "Coal Bed Methane")
                rows.append(row("%d-CG" % n if wt == "CM" else str(n), date(y, m, k), wt, desc, county, oper))
                n += 1
    rows += [
        row("4417-A", date(2025, 3, 5), "GAS", "Gas"),  # a well numbered long ago, permitted again
        row("50265-CG", date(2025, 5, 20)),  # the number of the permit of May 11 again (a re-permit with a new suffix): not a second new well
        row("48000-SWD-25-01", date(2025, 6, 9), "SWD", "Water Disposal", "Sampleville", "Sample Oil Corporation"),
        row("47000-WI-25-02", date(2025, 7, 9), "WI", "Water Injection", "Sampleville", "Sample Oil Corporation"),
        row("46000-WS", date(2025, 8, 9), "WS", "Water Source", "Sampleville", "Sample Oil Corporation"),
        row("999999", date(2025, 9, 9), "OIL", "Oil", "Sampleville", "Sample Oil Corporation"),  # a mistyped number moves nothing
        row("4417-A", date(2025, 3, 5), "GAS", "Gas"),  # an exact repeat of an entry
        row("", None),  # no number and no date: left out
        row("50300-CG", None),  # no PermitDate: left out
    ]
    return rows


# ------------------------------------------------------------------------------------------------ small parts
check(AL.base_of("17436-CG") == 17436 and AL.base_of("5115-SWD-26-01") == 5115 and AL.base_of("  17207-WS-B") == 17207 and AL.base_of("4055-A") == 4055, "a permit number's base is the digits it starts with")
check(AL.base_of("") is None and AL.base_of(None) is None and AL.base_of("A-12") is None and AL.base_of("1234567-X") is None, "no leading number, no base (and seven digits is not a permit number)")
check(AL.is_service({"WellType": "SWD"}) and AL.is_service({"WellType": "wi "}) and AL.is_service({"WellType": "GI"}) and AL.is_service({"WellType": "WS"}), "the layer's own codes for disposal, injection, gas injection and water source are service wells")
check(AL.is_service({"WellType": "XX", "TypeDesc": "Brine Disposal"}) and not AL.is_service({"WellType": "CM", "TypeDesc": "Coal Bed Methane"}) and not AL.is_service({"WellType": "UN", "TypeDesc": "Undesignated"}), "an unknown code with a disposal word is still a service well; coal bed methane and undesignated are not")
u = urlparse(AL.url_for(0))
q = parse_qs(u.query)
check(u.scheme == "https" and u.netloc == "gis.ogb.state.al.us" and q["returnGeometry"] == ["false"] and q["outFields"] == [",".join(AL.FIELDS)] and "DATE '2015-01-01'" in q["where"][0], "the request is one https query for the permit date since 2015, with no geometry")
check(not {"Comment", "WellName", "API", "HistoricWellName", "Latitude", "Longitude"} & set(q["outFields"][0].split(",")), "it asks for no well name, API number, comment or location")

# ------------------------------------------------------------------------------------------------ dates and entries
rows = [row("50001-CG", date(2024, 3, 3)), row("50001-CG", date(2024, 3, 3)), row("50003", None), row("50004-CG", ms(date(2024, 3, 3), 0)), row("50005-CG", date(2024, 3, 4), "OIL", "Oil")]
got = AL.parse(rows, TODAY)
check([p["base"] for p in got] == [50001, 50004, 50005], "an exact repeat is dropped and an entry with no date is left out")
check({p["day"] for p in got} == {date(2024, 3, 3), date(2024, 3, 4)}, "milliseconds become the permit's day (a stamp at midnight UTC and one at 14:00 are the same day)")
check(AL.parse([row("50001-CG", date(2024, 3, 3))], TODAY)[0]["fluid"] == "gas" and AL.parse([row("50001", date(2024, 3, 3), "OIL", "Oil")], TODAY)[0]["fluid"] == "oil"
      and AL.parse([row("50001", date(2024, 3, 3), "UN", "Undesignated")], TODAY)[0]["fluid"] is None and AL.parse([row("50001", date(2024, 3, 3), "GC", "Gas Condensate")], TODAY)[0]["fluid"] == "gas",
      "the fluid is the layer's type: coal bed methane and gas are gas, oil is oil, undesignated says nothing")
good = [row("5%04d" % i, date(2024, 1, 1 + i % 20)) for i in range(60)]
check(51111 not in [p["base"] for p in AL.parse(good + [row("51111", ms(date(2030, 1, 1)))], TODAY)], "a date in the future is not read as a permit")
try:
    AL.parse([row("50001", "not a date")] * 3 + good[:40], TODAY)
    bad_dates = False
except RuntimeError:
    bad_dates = True
check(bad_dates, "more than 2% of the entries with a date that cannot be read fails the run")

# ------------------------------------------------------------------------------------------------ the number sequence
seq = [row("%d-CG" % n, date(2023, 10, 1) + timedelta(days=3 * i)) for i, n in enumerate(m for m in range(60000, 60030) if m != 60018)]  # 29 numbers, 60018 skipped
extra = [row("1200-A", date(2024, 2, 1), "GAS", "Gas"),  # long ago numbered
         row("59900", date(2024, 2, 1), "OIL", "Oil"),  # numbered a few months before the sequence's start, 130 behind: a re-permit
         row("60005-CG", date(2024, 2, 2)),  # the number of an earlier permit again
         row("60500", date(2024, 2, 3), "OIL", "Oil"),  # more than 100 ahead: a typo
         row("60999-SWD-24-01", date(2024, 2, 4), "SWD", "Water Disposal"),
         row("60031-CG", date(2024, 2, 5)),  # the next number still follows
         row("60018", date(2024, 2, 6), "OIL", "Oil")]  # 13 behind the newest: issued out of order, still new
P = {(p["base"], p["day"]): p["band"] for p in AL.classify(AL.parse(seq + extra, TODAY))}
check(P[(1200, date(2024, 2, 1))] == "other" and P[(59900, date(2024, 2, 1))] == "other" and P[(60005, date(2024, 2, 2))] == "other" and P[(60500, date(2024, 2, 3))] == "other", "an old number, a repeated number and a mistyped number are other filings, not new wells")
check(P[(60999, date(2024, 2, 4))] == "inj" and P[(60031, date(2024, 2, 5))] == "new" and P[(60018, date(2024, 2, 6))] == "new", "a service well is inj and moves nothing; the next number and a slightly late one are new")
check(sum(1 for v in P.values() if v == "new") == 31, "the 29 numbers in order, the next one and the late one are all new (31)")
try:
    AL.classify(AL.parse([row("%d" % ((i * 7919) % 90000 + 100), date(2024, 1, 1 + i % 28)) for i in range(60)], TODAY))
    scrambled = False
except RuntimeError:
    scrambled = True
check(scrambled, "numbers that do not follow the date (a layer that changed what the number means) fail the run")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
doc = AL.build(get=lambda url, **kw: reply(fixture()), today=TODAY, pause=0)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "AL" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] <= TODAY.isoformat(),
      "from January 2019 to the last complete month, counted by permit date")
b = doc["bands"]
check(b["inj"] is not None and b["other"] is not None and b["redrill"] is None and b["rework"] is None and b["amend"] is None, "it tells new, inj and other, and claims no other band")
i25 = doc["months"].index("2025-01")
check(sum(b["new"][i25:i25 + 12]) == 36, "2025: three new permits a month, 36 in the year (the re-permits, service wells and the typo are not among them)")
check(b["new"][doc["months"].index("2025-03")] == 3 and b["other"][doc["months"].index("2025-03")] == 1, "March 2025: three new wells and the re-permit of an old number as one other filing (its repeat is not counted twice)")
check(b["new"][doc["months"].index("2025-05")] == 3 and b["other"][doc["months"].index("2025-05")] == 1, "a number used twice counts once as new: the second entry is an other filing")
check(b["inj"][doc["months"].index("2025-06")] == 1 and b["inj"][doc["months"].index("2025-07")] == 1 and b["inj"][doc["months"].index("2025-08")] == 1, "disposal, injection and water-source permits are inj")
check(b["new"][doc["months"].index("2025-09")] == 3 and b["other"][doc["months"].index("2025-09")] == 1, "the mistyped number is an other filing and the real permits after it still count")
check(sum(b["new"]) + sum(b["inj"]) + sum(b["other"]) + 1 == doc["read"] and doc["asOf"] == "2026-10-03", "every entry from 2019 on is in exactly one band (the one of October 3 is past the last complete month): %d read" % doc["read"])
check(doc["fluid"] == {"oil": 12, "gas": 24, "both": 0, "other": 0, "unknown": 0}, "the fluid counts the last 12 months of new wells: 12 oil, 24 gas (coal bed methane)")
names = [o[0] for o in doc["operators"]]
check(names[0] == "EXAMPLE GAS COMPANY LLC" and "SAMPLE OIL CORPORATION" in names and all(C.nameable(n) for n in names), "operators are the corporate names, ranked")
check([c[0] for c in doc["counties"]] == ["Exampleton", "Sampleville"], "the places are the counties, ranked")
text = json.dumps(doc)
check("-CG" not in text and "50012" not in text and "4417" not in text and "SWD-25" not in text, "no permit number reaches the file")
# a person as operator on a new well
p_rows = fixture() + [row("50316-CG", date(2026, 9, 21), "OIL", "Oil", "Sampleville", "Pat Q Roe"), row("50317-CG", date(2026, 9, 22), "OIL", "Oil", "Sampleville", "Roe Oil Company dba Pat Roe")]
d2 = AL.build(get=lambda url, **kw: reply(p_rows), today=TODAY, pause=0)
check(d2["bands"]["new"][-1] == doc["bands"]["new"][-1] + 2 and not any("ROE" in o[0] for o in d2["operators"]) and "ROE" not in json.dumps(d2).upper() and d2["namedShare"] < doc["namedShare"] == 1.0
      and C.validate(d2, TODAY) == [], "two new wells whose operator is a person, or a person's dba, are counted but never named, and the named share falls")

# paging: the layer says there is more
old_page = AL.PAGE
AL.PAGE = 100
allrows = fixture()
seen_offsets = []


def paged(url, **kw):
    off = int(parse_qs(urlparse(url).query)["resultOffset"][0])
    seen_offsets.append(off)
    return reply(allrows[off:off + 100], more=off + 100 < len(allrows))


d3 = AL.build(get=paged, today=TODAY, pause=0)
AL.PAGE = old_page
check(seen_offsets == list(range(0, len(allrows), 100)) and d3["bands"] == doc["bands"], "a layer that pages is read page by page (%d requests) and gives the same series" % len(seen_offsets))


# failures fail the run; they never write a short file
def fails(get, **kw):
    try:
        AL.build(get=get, today=kw.get("today", TODAY), pause=0)
        return False
    except RuntimeError:
        return True


check(fails(lambda url, **k: json.dumps({"error": {"code": 400, "message": "Unable to complete operation."}}).encode()), "an error reply fails the run")
check(fails(lambda url, **k: reply(fixture(), fields=[f for f in AL.FIELDS if f != "PermitDate"])), "a layer without PermitDate fails the run (a renamed field)")
check(fails(lambda url, **k: reply(fixture(), fields=[f for f in AL.FIELDS if f != "Permit"])), "a layer without Permit fails the run")
check(fails(lambda url, **k: json.dumps({"fields": [{"name": f} for f in AL.FIELDS], "features": "none"}).encode()), "a reply with no list of rows fails the run")
check(fails(lambda url, **k: reply(fixture()[:120])), "too few rows fail the run")
check(fails(lambda url, **k: reply(fixture()), today=date(2027, 6, 1)), "a newest permit more than 150 days old fails the run (the layer looks stale)")
try:
    AL.build(get=lambda url, **k: b"<html>maintenance</html>", today=TODAY, pause=0)
    html_ok = True
except (ValueError, RuntimeError):
    html_ok = False
check(not html_ok, "an HTML page instead of the layer fails the run")

# the one main every producer uses
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("AL", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "AL.json")), "run_producer writes nat/AL.json for it")
    check(C.check_dir(tmp) == [], "and the written file reloads clean")


def refuse():
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("AL", refuse, tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusing server ends with exit 2 and writes nothing")
    check(C.run_producer("AL", lambda: AL.build(get=lambda url, **k: b"{}", today=TODAY, pause=0), tmp, argv=[]) == 1 and not os.listdir(tmp), "a damaged layer ends with exit 1 and writes nothing")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
