"""Tests for the one rule of d7_daily.py: a report shows what landed on each RRC share that day, live, rebuilt or repaired; with mutants.

Run: python3 -I tests/test_d7_one_rule.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import importlib.util
import os
import sys
import types
from datetime import date, datetime, timedelta

spec = importlib.util.spec_from_file_location("d7", os.environ.get("D7_PATH", _os.path.join(PIPE, "d7_daily.py")))
d7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d7)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def row(name, modified, size=1000):
    return {"name": name, "modified": modified, "bytes": size, "size": "%d B" % size, "link": "x:" + name}


# ------------------------------------------------------------------ synthetic share contents (Central listing times)
def pending_files(named, hhmmss, first_listed, step_min=10, n_files=11):
    """The two files the report reads for one set: drilling_permit is the first file of the set, wellbore the tenth."""
    stamp = named.strftime("%Y%m%d") + hhmmss
    t0 = datetime.strptime(first_listed, "%Y-%m-%dT%H:%M:%S")
    return [row("dp_drilling_permit_pending_%s.txt" % stamp, t0.isoformat()),
            row("dp_wellbore_pending_%s.txt" % stamp, (t0 + timedelta(minutes=step_min * 9)).isoformat())]


def listing_for_sets():
    rows = []
    d = date(2026, 10, 27)  # Tue
    while d <= date(2026, 11, 1):
        wk = d.weekday() < 5
        nxt = d + timedelta(days=1)
        if wk:  # an 11 AM set lands that afternoon
            rows += pending_files(d, "110808", d.isoformat() + "T16:07:00")
        # a 5 PM set lands after midnight, every day including weekends
        rows += pending_files(d, "170807", nxt.isoformat() + "T00:06:00")
        d = nxt
    return rows


ALL_SETS = listing_for_sets()


def zip_rows(first, last, size=100000):
    out, d = [], first
    while d <= last:
        listed = (d + timedelta(days=1)).isoformat() + "T02:16:00"
        out.append(row(d.strftime("%m-%d-%Y.zip"), listed, size + d.day))
        d += timedelta(days=1)
    return out


class World:
    def __init__(self, listing):
        self.listing = sorted(listing, key=lambda r: r["modified"], reverse=True)


W = None


class FakeShare:
    def __init__(self, guid, sess=None):
        self.guid, self.total = guid, len(W.listing)

    def open(self):
        pass

    def newest(self, n):
        return W.listing[:n]

    def download(self, name, dest):
        return "PATH|" + name


class LK:
    operator = {}

    def county_name(self, f):
        return f or "Unknown"

    def op(self, n):
        return [n, None]


def fake_read_delimited(path, delim, need=()):
    name = path.split("|", 1)[1]
    stamp = name[-18:-4]
    if name.startswith("dp_drilling_permit"):
        return [{"UNIVERSAL_DOC_NO": "%s-%d" % (stamp, i), "OPERATOR_NUMBER": "100", "DISTRICT": "08", "TOTAL_DEPTH": "9000",
                 "SUBMIT_DATE": "", "FILING_PURPOSE_CODE": "01"} for i in range(3)]
    return [{"UNIVERSAL_DOC_NO": "%s-%d" % (stamp, i), "COUNTY_CODE": "001"} for i in range(3)]


def fake_read_completions(path):
    name = path.split("|", 1)[1]
    n = int(name[3:5])  # the zip's day of month, so a section says which zip it came from
    return [{"state": "Approved", "forms": ["W-2"], "district": "08", "county": "001", "op": "100", "purpose": "1", "ctype": "1",
             "gas": False, "profile": "1", "approved": None, "ip_oil": 100.0} for _ in range(n)]


d7.Share = FakeShare
d7.Session = lambda *a, **k: types.SimpleNamespace(retries=0)
d7.read_delimited = fake_read_delimited
d7.read_completions = fake_read_completions
d7.log = lambda m: None


def ctx_for(days, R=None):
    return {"R": R or days[-1], "today": days[-1], "dates": days, "dl": "/nowhere", "guid": {"pending": "P", "completions": "C"}, "lk": LK()}


# ------------------------------------------------------------------ helpers
check(d7.listed_day(row("a", "2026-10-31T02:16:10")) == "2026-10-31", "listed_day reads the Last Modified date")
check(d7.listed_day(row("a", None)) is None and d7.listed_day(None) is None, "listed_day: no time, no day")
zips = {date(2026, 10, 28): row("a", "2026-10-29T02:23:00"), date(2026, 10, 29): row("b", "2026-10-30T02:21:00"), date(2026, 10, 30): row("c", "2026-10-31T02:16:00")}
check(d7.landed_on(zips, date(2026, 10, 30)) == date(2026, 10, 29), "landed_on: Oct 30 sees the zip named Oct 29 (listed 02:21 on Oct 30), not Oct 30's")
check(d7.landed_on(zips, date(2026, 10, 31)) == date(2026, 10, 30), "landed_on: Oct 31 sees the zip named Oct 30")
check(d7.landed_on(zips, date(2026, 10, 28)) is None, "landed_on: no zip of these landed on Oct 28")
check(d7.landed_on({date(2026, 10, 1): row("x", None)}, date(2026, 10, 31)) is None, "landed_on: a file with no listing time is not used")

# ------------------------------------------------------------------ pending
ready = d7.pending_ready(sorted(ALL_SETS, key=lambda r: r["modified"], reverse=True))
check(all(len(s[3]) == 2 for s in ready), "pending_ready: every set holds both files")
by_listed = {}
for listed, named, half, _ in ready:
    by_listed.setdefault(listed, []).append((named.isoformat(), half))
check(by_listed["2026-10-30"] == [("2026-10-29", "pm"), ("2026-10-30", "am")], "Thursday Oct 29's 5 PM set and Friday's 11 AM set land on Friday Oct 30 %r" % by_listed["2026-10-30"])
check(by_listed["2026-10-31"] == [("2026-10-30", "pm")], "Saturday Oct 31: only Friday's 5 PM set (no weekend 11 AM set) %r" % by_listed["2026-10-31"])
check(by_listed["2026-11-01"] == [("2026-10-31", "pm")], "Sunday Nov 1: only Saturday's 5 PM set %r" % by_listed["2026-11-01"])

# a set that is still being copied, and one whose copy crosses midnight
partial = [row("dp_drilling_permit_pending_20261101170807.txt", "2026-11-02T00:06:00")]
check(d7.pending_ready(partial) == [], "pending_ready: a set with only its permit file is not complete")
late = pending_files(date(2026, 11, 1), "170807", "2026-11-01T23:55:00")
check(d7.pending_ready(late)[0][0] == "2026-11-02", "pending_ready: a copy that crosses midnight is listed on the day its last needed file appeared")
check(d7.pending_ready([row("dp_drilling_permit_pending_20261101170807.txt", None), row("dp_wellbore_pending_20261101170807.txt", "2026-11-02T00:06:00")]) == [],
      "pending_ready: a file without a listing time leaves its set out")

days = [date(2026, 10, 29) + timedelta(days=i) for i in range(4)]  # Oct 29 .. Nov 1
W = World(ALL_SETS)
pj = d7.pending_job(ctx_for(days))
got = {d.isoformat(): [(s["label"], s["at"][:10]) for s in sec["sets"]] for d, sec in pj["sections"].items()}
check(got["2026-10-30"] == [("5 PM", "2026-10-29"), ("11 AM", "2026-10-30")], "pending_job Oct 30: 5 PM of Oct 29, then 11 AM of Oct 30 %r" % got.get("2026-10-30"))
check(got["2026-10-31"] == [("5 PM", "2026-10-30")] and got["2026-11-01"] == [("5 PM", "2026-10-31")], "pending_job weekend days: one 5 PM set each")
check(pj["sections"][date(2026, 10, 30)]["day"] == "2026-10-30" and pj["sections"][date(2026, 10, 31)]["day"] == "2026-10-30", "pending_job: a section's day is the newest set's named day")
check(pj["sections"][date(2026, 10, 30)]["total"] == 6, "pending_job Oct 30: two sets of three applications")
check(pj["picked"][date(2026, 10, 30)]["name"] == "dp_drilling_permit_pending_20261030110808.txt", "pending_job: the file a day is dated by is its newest set's permit file")
check(date(2026, 10, 29) in pj["sections"], "pending_job Oct 29 has its own sets")

# the same day captured later gives the same report: drop everything listed after the end of the day
for d in days:
    cut = [r for r in ALL_SETS if r["modified"][:10] <= d.isoformat()]
    W = World(cut)
    evening = d7.pending_job(ctx_for([d]))
    W = World(ALL_SETS)
    later = d7.pending_job(ctx_for([d]))
    check(evening["sections"] == later["sections"] and evening["picked"] == later["picked"], "pending: %s captured that evening equals the same day captured after more files landed" % d)

# a day with no set listed has no section (and no file)
W = World([r for r in ALL_SETS if r["modified"][:10] != "2026-10-31"])
pj2 = d7.pending_job(ctx_for([date(2026, 10, 31)]))
check(pj2["sections"] == {} and pj2["picked"] == {}, "pending: a day on which nothing landed has no pending section")

# ------------------------------------------------------------------ completions
W = World(zip_rows(date(2026, 10, 20), date(2026, 10, 30)))
days = [date(2026, 10, 28) + timedelta(days=i) for i in range(4)]  # Oct 28 .. Oct 31
cj = d7.completions_job(ctx_for(days))
check({d.isoformat(): s["day"] for d, s in cj["sections"].items()} == {"2026-10-28": "2026-10-27", "2026-10-29": "2026-10-28", "2026-10-30": "2026-10-29", "2026-10-31": "2026-10-30"},
      "completions: each report day shows the zip named for the day before %r" % {d.isoformat(): s["day"] for d, s in cj["sections"].items()})
check(cj["picked"][date(2026, 10, 30)]["name"] == "10-29-2026.zip", "completions: the file a day is dated by is the zip it shows")
for d in days:
    cut = [r for r in W.listing if r["modified"][:10] <= d.isoformat()]
    saved, W = W, World(cut)
    evening = d7.completions_job(ctx_for([d]))
    W = saved
    later = d7.completions_job(ctx_for([d]))
    check(evening["sections"] == later["sections"] and evening["picked"] == later["picked"], "completions: %s captured that evening equals the same day captured later" % d)

# a zip listed late (day 10-26 listed at 10:24 on 10-27) and a missing day
rows = [r for r in zip_rows(date(2026, 10, 20), date(2026, 10, 30)) if r["name"] != "10-24-2026.zip"]
for r in rows:
    if r["name"] == "10-26-2026.zip":
        r["modified"] = "2026-10-27T10:24:40"
W = World(rows)
cj = d7.completions_job(ctx_for([date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 25), date(2026, 10, 26)]))
check(cj["sections"][date(2026, 10, 26)]["day"] == "2026-10-25" and cj["sections"][date(2026, 10, 27)]["day"] == "2026-10-26", "completions: a zip listed late is shown on the day it was listed")
check(date(2026, 10, 25) not in cj["sections"] and date(2026, 10, 25) not in cj["picked"], "completions: a day on which no zip landed shows none, not the previous zip again (Oct 25, zip 10-24 is missing)")
W = World([row("10-20-2026.zip", "2026-10-21T02:16:00")])
cj = d7.completions_job(ctx_for([date(2026, 10, 30)]))
check(cj["sections"] == {} and cj["picked"] == {}, "completions: nothing landed that day, no section")

# ------------------------------------------------------------------ image packs
def pack_rows(days_back, lag_h):
    out = []
    for i in range(days_back):
        d = date(2026, 10, 30) - timedelta(days=i)
        out.append(row(d.strftime("%m-%d-%Y.zip"), (datetime(d.year, d.month, d.day) + timedelta(days=1, hours=lag_h)).isoformat(), 5_000_000 + i))
    return out


# completion images land about 02:20 the next morning, directional surveys about 07:55
for ds, hh, expect in (("complimages", 2.3, "2026-10-29"), ("dirsurveys", 7.9, "2026-10-29")):
    W = World(pack_rows(12, hh))
    ctx = dict(ctx_for([date(2026, 10, 30), date(2026, 10, 31)]), guid={ds: "G"})
    ij = d7.images_job(ctx, ds)
    use30, use31 = d7.landed_on(ij["days"], date(2026, 10, 30)), d7.landed_on(ij["days"], date(2026, 10, 31))
    check(use30.isoformat() == expect and use31.isoformat() == "2026-10-30", "%s: Oct 30 shows pack %s, Oct 31 shows pack Oct 30 (%s, %s)" % (ds, expect, use30, use31))
    check(ij["picked"][date(2026, 10, 30)]["name"] == "10-29-2026.zip" and ij["picked"][date(2026, 10, 31)]["name"] == "10-30-2026.zip", "%s: the file a day is dated by is its pack" % ds)
    sec = d7.image_section(ij["days"], use30)
    check(sec["day"] == "2026-10-29" and sec["bytes"] == 5_000_001 and sec["empty"] is False, "%s: image_section reads the pack's size and day" % ds)
check(d7.image_section({}, None) is None, "image_section: no pack, no block")

# W-1 images: district packs listed with the whole-day pack
w1 = []
for i in range(3):
    d = date(2026, 10, 30) - timedelta(days=i)
    when = (datetime(d.year, d.month, d.day) + timedelta(days=1, hours=10.3)).isoformat()
    w1.append(row("subscriptions_%s.zip" % d.isoformat(), when, 30_000_000))
    for dist, size in (("8A", 400_000), ("7C", 1_600_000), ("03", 1_000)):
        w1.append(row("subscriptions_%s_district%s.zip" % (d.isoformat(), dist), when, size))
W = World(w1)
ij = d7.images_job(dict(ctx_for([date(2026, 10, 30)]), guid={"w1images": "G"}), "w1images")
use = d7.landed_on(ij["days"], date(2026, 10, 30))
sec = d7.image_section(ij["days"], use)
check(sec["day"] == "2026-10-29" and [k for k, v in sec["districts"]] == ["7C", "8A"], "w1images: Oct 30 shows the Oct 29 pack with its districts largest first, tiny packs left out %r" % sec["districts"])
check(ij["picked"][date(2026, 10, 30)]["name"] == "subscriptions_2026-10-29.zip", "w1images: the file is the whole-day pack")


# W-1 images are not produced on weekends: the Friday pack lands Saturday, Sunday and Monday have none, Tuesday has Monday's
w1g = [row("subscriptions_2026-10-30.zip", "2026-10-31T10:18:00", 30_000_000), row("subscriptions_2026-10-26.zip", "2026-10-27T10:18:00", 30_000_000),
       row("subscriptions_2026-10-27.zip", "2026-10-28T10:18:00", 30_000_000), row("subscriptions_2026-11-02.zip", "2026-11-03T10:18:00", 30_000_000)]
W = World(w1g)
ijg = d7.images_job(dict(ctx_for([date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]), guid={"w1images": "G"}), "w1images")
got = {d.isoformat(): (d7.landed_on(ijg["days"], d).isoformat() if d7.landed_on(ijg["days"], d) else None) for d in (date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3))}
check(got == {"2026-10-31": "2026-10-30", "2026-11-01": None, "2026-11-02": None, "2026-11-03": "2026-11-02"}, "w1images: Saturday shows Friday's pack, Sunday and Monday show none, Tuesday shows Monday's %r" % got)
check(date(2026, 11, 1) not in ijg["picked"] and date(2026, 11, 2) not in ijg["picked"], "w1images: a day with no pack has no file")

# ------------------------------------------------------------------ build_reports and update_states
cat = {}
live_day = date(2026, 10, 31)
W = World(ALL_SETS)
pend = d7.pending_job(ctx_for([date(2026, 10, 30), live_day]))
W = World(zip_rows(date(2026, 10, 20), date(2026, 10, 30)))
comp = d7.completions_job(ctx_for([date(2026, 10, 30), live_day]))
W = World(pack_rows(12, 2.3))
imgs = {ds: d7.images_job(dict(ctx_for([date(2026, 10, 30), live_day]), guid={ds: "G"}), ds) for ds in ("w1images", "dirsurveys", "complimages")}
jobs = dict(pending=pend, completions=comp, **imgs)
ctx = ctx_for([date(2026, 10, 30), live_day])
reps = d7.build_reports(ctx, jobs, cat, {date(2026, 10, 30): "reconstructed", live_day: "live"})
live, past = reps[live_day], reps[date(2026, 10, 30)]
ds_by = {x["id"]: x for x in live["datasets"]}
check(ds_by["completions"]["dataDay"] == "2026-10-30" and ds_by["complimages"]["dataDay"] == "2026-10-30", "build_reports: Oct 31 shows the Oct 30 zips")
check(ds_by["completions"]["file"]["name"] == "10-30-2026.zip" and ds_by["complimages"]["file"]["name"] == "10-30-2026.zip", "build_reports: a live day's file is the one it shows")
check(ds_by["pending"]["file"]["name"] == "dp_drilling_permit_pending_20261030170807.txt" and ds_by["pending"]["dataDay"] == "2026-10-30", "build_reports: Oct 31's pending file is Friday's 5 PM set")
check(all(x["file"] is None for x in past["datasets"]), "build_reports: a rebuilt day carries no file info")
check(past["completions"]["day"] == "2026-10-29" and past["images"]["complimages"]["day"] == "2026-10-29", "build_reports: a rebuilt Oct 30 shows the same Oct 29 zips a live one would")

# update_states: a live day with nothing landed is 'same', a changed file is 'new', no earlier live report is 'first'
import json
import tempfile
with tempfile.TemporaryDirectory() as out:
    prior = {"date": "2026-10-30", "kind": "live", "datasets": [{"id": "pending", "file": {"name": "a", "modified": "m", "bytes": 1}}, {"id": "completions", "file": {"name": "c", "modified": "m", "bytes": 1}},
                                                                {"id": "permits", "file": {"name": "p", "modified": "m", "bytes": 1}}]}
    json.dump(prior, open(os.path.join(out, "2026-10-30.json"), "w"))
    cur = {"date": "2026-10-31", "datasets": [{"id": "pending", "file": None, "error": None}, {"id": "completions", "file": {"name": "d", "modified": "m", "bytes": 1}, "error": None},
                                             {"id": "permits", "file": {"name": "p", "modified": "m", "bytes": 1}, "error": None}, {"id": "dirsurveys", "file": {"name": "z"}, "error": "x"}]}
    d7.update_states(cur, out)
    st = {x["id"]: x["state"] for x in cur["datasets"]}
    check(st == {"pending": "same", "completions": "new", "permits": "same", "dirsurveys": "error"}, "update_states: nothing landed = same, changed file = new, unchanged = same, error = error %r" % st)
    json.dump(dict(prior, kind="reconstructed"), open(os.path.join(out, "2026-10-30.json"), "w"))
    cur2 = {"date": "2026-10-31", "datasets": [{"id": "pending", "file": None, "error": None}]}
    d7.update_states(cur2, out)
    check(cur2["datasets"][0]["state"] == "first", "update_states: after a rebuilt day everything is 'first'")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
