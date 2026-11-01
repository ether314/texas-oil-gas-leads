"""Tests for site/pipeline/d13_arrivals.py: the wells that appeared in FracFocus's download since the last one, and which of them a state agency's daily report had already carried.

They pin: a well is new when its API number was not in the list kept from the last download (and a well gone from it is counted apart, never as new); a Texas arrival whose API number is in the
archive's permit or survey rows is counted as already reported, matched on the ten digits (the day files hold eight, without the state's 42); a state whose daily report carries no wells (Oklahoma, New
Mexico, every other) is never matched and says `null`, not a zero; no list from the last download means no arrivals (a baseline, said so), and a list that is too short, damaged or empty is no list; a
second run on one day finds only what the first did not and adds to its entry; a day with nothing new only moves `checked`; the file keeps its newest 60 days; the list kept is deterministic bytes;
the validator refuses a count that does not add up, a reported count for a state that cannot have one, and anything shaped like an API number; and a mutant (no match against the state reports) fails a check.

Run: python3 -I tests/test_d13_arrivals.py"""
import copy
import gzip
import json
import os
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d13_arrivals as A  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 2)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def well(state, day="2026-10-20"):
    """A record in the shape d13_newwells.Wells keeps: (day, state, county, operator, point, depth, water, land)."""
    return (date.fromisoformat(day), state, "Martin", "Alpha Energy LLC", (31.9, -102.0), 9500, 21000000, 0)


# ------------------------------------------------------------------------------------------------ the comparison
seen = {"4231700001", "4231700002", "3501500003", "3002500004", "4231700005"}
first = {  # today's download: 2 of the 5 old wells are still there (4231700001, 3501500003); three Texas and an Oklahoma, a New Mexico and an Ohio well are new
    "4231700001": well("TX"), "3501500003": well("OK"),
    "4231700010": well("TX"), "4231700011": well("TX"), "4231700012": well("TX"), "3501500020": well("OK"), "3002500021": well("NM"), "3400700030": well("OH"),
}
reported = {"4231700010", "4231700012", "4231700099"}  # Texas's daily reports carried two of the three new Texas wells (and one that is not in the download)
e = A.find(first, seen, reported, "2026-11-02")
by = {r[0]: r for r in e["states"]}
check(e["day"] == "2026-11-02" and e["found"] == 6 and e["removed"] == 3, "six wells are new (not in the last download) and three of the last download's are gone: %s" % e)
check(by["TX"] == ["TX", 3, 2], "Texas: three new, two of them already in a Texas daily report: %s" % by["TX"])
check(by["OK"] == ["OK", 1, None] and by["NM"] == ["NM", 1, None] and by["OH"] == ["OH", 1, None], "Oklahoma, New Mexico and Ohio: their daily reports carry no wells, so 'already reported' is null, never zero")
check([r[1] for r in e["states"]] == sorted((r[1] for r in e["states"]), reverse=True) and sum(r[1] for r in e["states"]) == e["found"], "the states are ranked by wells found and add up to the total")
check(A.find(first, None, reported, "2026-11-02") is None, "with no list from the last download there is nothing to compare: no arrivals, not 'every well is new'")
same = A.find({k: v for k, v in first.items() if k in seen}, seen, reported, "2026-11-02")
check(same["found"] == 0 and same["states"] == [] and same["removed"] == 3, "the same wells again: nothing new")
check("4231700010" not in json.dumps(e) and not any(len(str(x)) >= 10 and str(x).isdigit() for r in e["states"] for x in r), "the entry holds counts only: no API number")

# ------------------------------------------------------------------------------------------------ what Texas's daily reports carried
tmp = tempfile.mkdtemp()
daily = os.path.join(tmp, "daily")
os.makedirs(daily)


def put(name, doc, raw=None):
    with open(os.path.join(daily, name), "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps(doc))


put("2026-10-28.json", {"permits": {"rows": [["0919600", "317", "08", "1", "X", 9000, "H", None, None, None, None]]}, "surveys": {"rows": []}})  # a day rebuilt from the monthly master: permit rows with no API number
put("2026-10-30.json", {"permits": {"rows": [["0919696", "317", "08", "102009", "HIGH NOON RESOURCES, LLC", 8500, "H", "31747601", None, None, None], ["0919697", "329", "08", "1", "X", 9000, "H", "32900123", 1, 2, None]]},
                         "surveys": {"rows": [["00349385", "003", "M", None, 20182, "2026-09-06", "2026-10-13", "1", "9936440", None, None]]}})
put("2026-10-31.json", {"permits": {"rows": [["0919698", "003", "08", "1", "X", 9000, "H", "00311111", None, None, None], ["short"], "not a row", ["a", "b", "c", "d", "e", "f", "g", "123", None, None]]}, "surveys": None})
put("2026-10-29.json", None, raw="{ this is not json")
put("index.json", {"days": []})  # not a day file
put("notes.txt", None, raw="x")
rep = A.reported_texas(daily)
check(rep == {"4231747601", "4232900123", "4200349385", "4200311111"}, "Texas's reported wells are the approved-permit rows' and the survey rows' API numbers, with the state's 42 put back: %s" % sorted(rep))
check(A.reported_texas(os.path.join(tmp, "missing")) == set() and A.reported_texas(None) == set() and A.read_texas(None) == (set(), None), "no archive reports nothing (and does not fail)")
check(A.read_texas(daily) == (rep, "2026-10-30"), "the match says from which day the archive carries API numbers: a day rebuilt from the monthly master (rows without one) does not count: %s" % (A.read_texas(daily)[1],))
check(all(len(x) == 10 and x.startswith("42") for x in rep), "every one is ten digits starting with Texas's 42, the key the registry's wells use")

# ------------------------------------------------------------------------------------------------ the list kept from the last download
path = os.path.join(tmp, "keep", "ff-seen.txt.gz")
apis = {"%010d" % (4231700000 + i) for i in range(500)}
A.write_seen(path, apis)
b1 = open(path, "rb").read()
A.write_seen(path, set(reversed(sorted(apis))))
check(A.load_seen(path, min_rows=100) == apis and open(path, "rb").read() == b1 and not os.path.exists(path + ".tmp"), "the list reads back whole, and the same wells give the same bytes (no timestamp, sorted)")
check(A.load_seen(path) is None, "a list shorter than a registry (under %d wells) is not a previous download: no baseline" % A.SEEN_MIN)
check(A.load_seen(os.path.join(tmp, "nope.gz")) is None and A.load_seen(None) is None, "a missing list is no list")
open(path, "wb").write(b"not gzip at all")
check(A.load_seen(path, min_rows=1) is None, "a damaged list is no list (the run keeps today's as the baseline, and does not fail)")
with gzip.open(path, "wt", encoding="ascii") as f:
    f.write("4231700001\nnot an api\n\n123\n4231700002\n")
check(A.load_seen(path, min_rows=1) == {"4231700001", "4231700002"}, "a line that is not ten digits is ignored")
open(path, "wb").write(gzip.compress(b"4231700001\n")[:-8])  # cut short
check(A.load_seen(path, min_rows=1) is None, "a list cut short is no list")

# ------------------------------------------------------------------------------------------------ the log
doc0 = A.update(None, None, "2026-11-02")
check(doc0 == {"v": 1, "checked": None, "since": None, "against": {}, "days": []} and A.validate(doc0, TODAY) == [], "a first run with no baseline writes an empty log that says nothing was compared")
cover = {"TX": {"wells": 83, "from": "2026-10-30"}}
doc_c = A.update(doc0, None, "2026-11-02", cover)
check(doc_c["against"] == cover and A.update(doc_c, None, "2026-11-03")["against"] == cover and A.validate(doc_c, TODAY) == [], "what the Texas match covered (83 wells, from the first night captured live) is kept in the log, and stays when a run does not say")
quiet = A.update(doc0, {"day": "2026-11-02", "found": 0, "removed": 0, "states": []}, "2026-11-02")
check(quiet["checked"] == "2026-11-02" and quiet["since"] == "2026-11-02" and quiet["days"] == [], "a comparison that found nothing moves `checked` and adds no day")
d1 = A.update(quiet, e, "2026-11-02")
check(len(d1["days"]) == 1 and d1["days"][0] == e and A.validate(d1, TODAY, states={"TX", "OK", "NM", "OH"}) == [], "a day with arrivals gets an entry, and the log validates")
more = {"day": "2026-11-02", "found": 2, "removed": 0, "states": [["TX", 1, 1], ["OK", 1, None]]}
d2 = A.update(d1, more, "2026-11-02")
t2 = {r[0]: r for r in d2["days"][0]["states"]}
check(len(d2["days"]) == 1 and d2["days"][0]["found"] == 8 and t2["TX"] == ["TX", 4, 3] and t2["OK"] == ["OK", 2, None] and d2["days"][0]["removed"] == 3, "a second run the same day adds what it found to the day's entry (it finds only what the first did not)")
rerun = A.update(d2, {"day": "2026-11-02", "found": 0, "removed": 0, "states": []}, "2026-11-02")
check(rerun == d2, "a second run that finds nothing leaves the log as it was")
d3 = A.update(d2, {"day": "2026-11-03", "found": 1, "removed": 0, "states": [["NM", 1, None]]}, "2026-11-03")
check([d["day"] for d in d3["days"]] == ["2026-11-03", "2026-11-02"] and d3["checked"] == "2026-11-03" and d3["since"] == "2026-11-02", "days are newest first; `since` stays the first day compared")
log = copy.deepcopy(d3)
for i in range(80):
    log = A.update(log, {"day": (date(2026, 11, 3) + timedelta(days=i + 1)).isoformat(), "found": 1, "removed": 0, "states": [["TX", 1, 0]]}, (date(2026, 11, 3) + timedelta(days=i + 1)).isoformat())
check(len(log["days"]) == A.KEEP_DAYS and log["days"][0]["day"] == "2027-01-22" and log["days"][-1]["day"] > "2026-11-03", "the log keeps the newest %d days and drops the oldest" % A.KEEP_DAYS)
check(A.update(d3, None, "2026-11-09") == d3 and A.update(d3, None, "2026-11-09") is not d3, "no baseline today leaves the log as it was (a copy, not the same object)")

# ------------------------------------------------------------------------------------------------ the validator against deliberate faults
good = copy.deepcopy(d2)
good["against"] = copy.deepcopy(cover)


def mut(fn):
    d = copy.deepcopy(good)
    fn(d)
    return d


faults = {
    "version": lambda d: d.update(v=2), "a day in the future": lambda d: d["days"][0].update(day="2027-01-01"), "checked in the future": lambda d: d.update(checked="2027-01-01"),
    "states that do not add up": lambda d: d["days"][0].update(found=99), "a count that is text": lambda d: d["days"][0]["states"][0].__setitem__(1, "3"),
    "reported above found": lambda d: d["days"][0]["states"][0].__setitem__(2, 99), "a reported count for Oklahoma": lambda d: [r.__setitem__(2, 1) for r in d["days"][0]["states"] if r[0] == "OK"],
    "Texas not checked": lambda d: [r.__setitem__(2, None) for r in d["days"][0]["states"] if r[0] == "TX"], "a state that is not one": lambda d: d["days"][0]["states"].append(["ZZ", 1, None]),
    "a zero row": lambda d: d["days"][0]["states"].append(["NM", 0, None]), "days out of order": lambda d: d["days"].append({"day": "2026-12-25", "found": 0, "removed": 0, "states": []}),
    "a day twice": lambda d: d["days"].append(copy.deepcopy(d["days"][0])), "too many days": lambda d: d.update(days=[{"day": "2026-10-%02d" % (i % 28 + 1), "found": 0, "removed": 0, "states": []} for i in range(61)]),
    "a match recorded for Oklahoma": lambda d: d["against"].update(OK={"wells": 5, "from": None}), "a match of minus wells": lambda d: d["against"].update(TX={"wells": -1, "from": None}),
    "a match from a day in the future": lambda d: d["against"].update(TX={"wells": 1, "from": "2027-01-01"}), "a match with no count": lambda d: d.update(against={"TX": {"from": None}}),
    "an API number": lambda d: d["days"][0].update(note="well 4231700010"), "a web address": lambda d: d.update(note="see https://x.example/y"),
}
for name, fn in faults.items():
    check(A.validate(mut(fn), TODAY, states={"TX", "OK", "NM", "OH"}) != [], "arrivals fault refused: " + name)

# ------------------------------------------------------------------------------------------------ mutants: each puts an old failure back
real_reported = A.reported_texas
A.reported_texas = lambda *a, **k: set()
e_nomatch = A.find(first, seen, A.reported_texas(daily), "2026-11-02")
A.reported_texas = real_reported
check(e_nomatch["states"][0][2] == 0 and e["states"][0][2] == 2, "mutant (no match against the state reports) counts nothing as already reported: the match is what keeps a well from being reported twice")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
