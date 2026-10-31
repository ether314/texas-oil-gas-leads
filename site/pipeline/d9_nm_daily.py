#!/usr/bin/env python3
"""D9 (daily): New Mexico's Daily report for the Oil tracker, from the Oil Conservation Division's well layer.

The OCD publishes no daily permit file. What it does publish is the layer of every well (ArcGIS, "refreshed daily"), and its MapServer
copy (OCDView/API_Export) carries `effective_date`, which for a well still in status New is the day its application for a permit to
drill (APD) was approved. So a day's report is the wells in status New that were approved on the newest day before the report: the
same rule as Oklahoma's (Monday's report shows Friday's approvals), counted by county, operator, kind of well and direction (the layer
says horizontal, vertical or directional) and the OCD district. No filing dates, planned depths, completions, transfers or pending queue
are published, and the report says so by leaving them out, never by showing a zero.

  - A day's count is the approvals that are still open: a well drops out of status New once it is cancelled or has moved on, so a day
    rebuilt later can lose a few. A day captured live the night after is complete to that night. Rebuilt days are marked so.
  - The layer is entered some days after an approval (the newest two or three days run well under the 17 to 22 a business day of the weeks
    before and fill in later), so a report names the day its permits are from and the time of the layer's newest edit, and the pace chart
    reads permits-series.json, which every night's run rewrites from the layer as it stands, so a day's bar settles as the layer catches up.
  - Nothing names a well, a lease or an API number (an API number is used only to count a well once). Operators are named only when the
    corporate rule says so (d8_ok_daily.nameable), never a person's dba.

  python3 -I site/pipeline/d9_nm_daily.py [--date YYYY-MM-DD] [--backfill N] [--history] [--out DIR] [--keep 92]
  python3 -I site/pipeline/d9_nm_daily.py --check [--out DIR]        only reload and check what is already there
  python3 -I site/pipeline/d9_nm_daily.py --skip-if-captured          for a backup schedule: exit quietly if the day is done
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d8_ok_daily as D  # noqa: E402

LAYER = "https://gis.emnrd.nm.gov/arcgis/rest/services/OCDView/API_Export/MapServer/0"
UA = "Mozilla/5.0 (research script)"
KEEP_DAYS = 92
LOOKBACK = 10        # days a report may reach back for its newest day with approvals (weekends, holidays, a lagging layer)
SAFE_BACKFILL = 7    # missed nights rebuilt without --history (the layer holds every approval still open, so this is a courtesy limit)
OUT = os.path.join(SITE, "public", "data", "daily-nm")
COUNTIES_GEO = os.path.join(SITE, "public", "data", "counties-nm.geo.json")
FIELDS = "id,effective_date,last_edited_on,county,county_code,type,directional_status,ogrid,ogrid_name,district"
DAY_FILE = re.compile(r"\d{4}-\d\d-\d\d\.json")
SERIES = "permits-series.json"  # approvals by day, from the layer as it stands (the Texas file of the same name has the same shape)
BUDGET_BYTES = {"index.json": 40_000, "day": 30_000}
DATASETS = [{"id": "permits", "title": "Permits to drill"}]
FILE_NAME = "OCD well layer (Wells, MapServer)"
log = D.log


# ------------------------------------------------------------------------------------------------ the layer

def query(params, retries=4):
    """One request to the layer's query endpoint, as parsed JSON; retried with a pause if the server hiccups."""
    url = LAYER + "/query?" + urllib.parse.urlencode(dict(params, f="json"))
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                doc = json.loads(r.read().decode("utf-8"))
            if "error" in doc:
                raise OSError(str(doc["error"])[:160])
            return doc
        except Exception as e:  # noqa: BLE001 - network hiccups, 5xx, an ArcGIS error page
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError("could not read the New Mexico wells layer: %r" % last)


def fetch_approvals(since):
    """Every well in status New approved on or after `since`, as attribute dicts (the layer's page limit is 3,000 records)."""
    where = "status = 'New' AND effective_date >= timestamp '%s 00:00:00'" % since.isoformat()
    rows, offset = [], 0
    while True:
        doc = query({"where": where, "outFields": FIELDS, "returnGeometry": "false", "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 2000})
        got = [f["attributes"] for f in doc.get("features", [])]
        rows += got
        if not doc.get("exceededTransferLimit") or not got:
            return rows
        offset += len(got)


def fetch_layer_edit():
    """When the layer was last edited (UTC), the newest `last_edited_on` over every well; None if the server will not say."""
    stat = json.dumps([{"statisticType": "max", "onStatisticField": "last_edited_on", "outStatisticFieldName": "newest"}])
    doc = query({"where": "1=1", "outStatistics": stat})
    ms = ((doc.get("features") or [{}])[0].get("attributes") or {}).get("newest")
    return datetime.fromtimestamp(ms / 1000, timezone.utc) if isinstance(ms, (int, float)) else None


def central_digits(utc):
    """A UTC time as the Central wall-clock digits the report files show for a file time ('2026-10-29T11:31:51')."""
    try:
        from zoneinfo import ZoneInfo
        local = utc.astimezone(ZoneInfo("America/Chicago"))
    except Exception:  # noqa: BLE001 - no tz data: the US daylight-saving rule, as d8_ok_daily.central_now
        local = utc - timedelta(hours=5 if 3 < utc.month < 11 else 6)
    return local.strftime("%Y-%m-%dT%H:%M:%S")


# ------------------------------------------------------------------------------------------------ the records

def to_rows(attrs, today):
    """The layer's records as one row per well: its approval day, operator, county, kind, direction and district. A well is counted once
    (by API number, which is read for that and never kept); a record with no real approval day or no usable API number is left out."""
    rows, seen = [], set()
    for a in attrs:
        eff = a.get("effective_date")
        api = (a.get("id") or "").strip()
        if not isinstance(eff, (int, float)) or abs(eff) > 9e12 or not re.fullmatch(r"\d\d-\d\d\d-\d{5}", api) or api in seen:
            continue
        day = datetime.fromtimestamp(eff / 1000, timezone.utc).date()
        if day.year < 2000 or day > today:
            continue
        seen.add(api)
        code = a.get("county_code")
        rows.append({
            "day": day, "op": str(a["ogrid"]) if a.get("ogrid") is not None else "", "opname": " ".join((a.get("ogrid_name") or "").split()),
            "county": "%03d" % code if isinstance(code, int) and 0 < code < 1000 else "", "cname": " ".join((a.get("county") or "").split()),
            "type": " ".join((a.get("type") or "").split()) or "Other", "dir": (a.get("directional_status") or "").strip().upper(),
            "district": " ".join((a.get("district") or "").split()),
        })
    return rows


class Lookups:
    """County names (from the committed New Mexico county shapes, else the layer's own) and the operator naming rule."""

    def __init__(self):
        geo = D.read_json(COUNTIES_GEO, {"features": []})
        self.county = {f["properties"]["f"]: f["properties"]["n"] for f in geo["features"]}

    def county_name(self, fips, fallback=""):
        return self.county.get(fips) or fallback.title() or "Unknown"

    def op(self, number, name):
        """[operator number, display name or None]: a name only for a corporation, LLC or partnership."""
        return [number, D.pretty(name) if D.nameable(name) else None]


def permits_section(day, rows, lk):
    """Everything the report says about the permits approved on `day` (a list of rows from to_rows). Every one is a permit for a new well."""
    ops = collections.Counter(r["op"] for r in rows if r["op"])
    names = {r["op"]: r["opname"] for r in rows}
    cnames = {r["county"]: r["cname"] for r in rows}
    dirs = collections.Counter(r["dir"] for r in rows)
    counties = collections.Counter(r["county"] for r in rows if r["county"])
    named = sum(n for k, n in ops.items() if D.nameable(names.get(k, "")))
    return {
        "day": day.isoformat(), "total": len(rows), "newDrill": len(rows),
        "types": D.top(collections.Counter(r["type"] for r in rows), 8),
        "horizontal": dirs["H"], "directional": dirs["D"], "vertical": dirs["V"],
        "districts": D.top(collections.Counter(r["district"] for r in rows if r["district"]), 6),
        "counties": [[f, lk.county_name(f, cnames.get(f, "")), n] for f, n in sorted(counties.items(), key=lambda kv: (-kv[1], kv[0]))], "countyCount": len(counties),
        "operators": [lk.op(op, names.get(op, "")) + [n] for op, n in sorted(ops.items(), key=lambda kv: (-kv[1], kv[0]))[:12]], "operatorCount": len(ops),
        "namedShare": round(named / len(rows), 3) if rows else None,
    }


def group_by_day(rows):
    out = collections.defaultdict(list)
    for r in rows:
        out[r["day"]].append(r)
    return out


def newest_day(by_day, day, lookback=LOOKBACK):
    """The newest day before `day`, within `lookback` days, that has approvals; None when there is none."""
    days = [d for d in by_day if d < day and (day - d).days <= lookback and by_day[d]]
    return max(days) if days else None


def build_reports(dates, by_day, kind_by_date, lk, edit_digits):
    """One report dict per date. Live days carry the layer's last-edit time as their file time; rebuilt days have no file to show."""
    reports = {}
    for day in dates:
        live = kind_by_date[day] == "live"
        rep = {"v": 1, "state": "NM", "date": day.isoformat(), "kind": kind_by_date[day]}
        d = newest_day(by_day, day)
        if d:
            rep["permits"] = permits_section(d, by_day[d], lk)
        rep["datasets"] = [{"id": "permits", "title": DATASETS[0]["title"], "cadence": "Daily", "dataDay": d.isoformat() if d else None, "error": None,
                            "file": {"name": FILE_NAME, "modified": edit_digits, "bytes": None} if live and edit_digits else None}]
        reports[day] = rep
    return reports


def headline(rep):
    """The index row for one report (the same keys Oklahoma's rows use; pd is the horizontal permits here)."""
    p = rep.get("permits")
    return {"d": rep["date"], "k": rep["kind"], "s": rep.get("status", "ok"), "dd": p["day"] if p else None, "p": p["total"] if p else None,
            "pn": p["newDrill"] if p else None, "pd": p["horizontal"] if p else None,
            "f": sum(1 for d in rep["datasets"] if not d.get("error") and not d.get("absent"))}


def update_states(live, out_dir):
    """Mark the dataset 'new' when the layer's last edit changed since the previous live report, 'same' when it did not and 'first' when
    there is no live report to compare with."""
    prev_days = sorted(f[:-5] for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f) and f[:-5] < live["date"])
    prev = D.read_json(os.path.join(out_dir, prev_days[-1] + ".json")) if prev_days else None
    before = {d["id"]: d.get("file") for d in prev["datasets"]} if prev and prev.get("kind") == "live" else None
    for d in live["datasets"]:
        if d.get("error"):
            d["state"] = "error"
        elif before is None:
            d["state"] = "first"
        elif before.get(d["id"]):
            d["state"] = "same" if before[d["id"]] == d["file"] else "new"
        else:
            d["state"] = "new"


def update_series(out_dir, by_day, since, last, keep=KEEP_DAYS):
    """Approvals by day, rewritten from the layer as it stands for the days from `since` to `last` and kept as they were before that, over the
    last `keep` + 30 days. `last` is the newest day the layer can speak for (the day before the report, or the day of its last edit when that
    is earlier), so a day it has not caught up with is absent rather than zero. Returns the document written."""
    path = os.path.join(out_dir, SERIES)
    prior = D.read_json(path, {}) or {}
    cells = {d: [n, t, h] for d, n, t, h in zip(prior.get("days", []), prior.get("newDrill", []), prior.get("total", []), prior.get("horizontal", []))}
    d = since
    while d <= last:
        rows = by_day.get(d, [])
        cells[d.isoformat()] = [len(rows), len(rows), sum(1 for r in rows if r["dir"] == "H")]
        d += timedelta(days=1)
    days = sorted(cells)[-(keep + 30):]
    doc = {"asOf": last.isoformat(), "days": days, "newDrill": [cells[x][0] for x in days], "total": [cells[x][1] for x in days], "horizontal": [cells[x][2] for x in days]}
    D.write_json(path, doc)
    return doc


def validate(out_dir, keep=KEEP_DAYS):
    """Reload everything this producer writes and check it. Returns the problems found (empty when all is well)."""
    bad = []

    def check(cond, msg):
        if not cond:
            bad.append(msg)

    ser = D.read_json(os.path.join(out_dir, SERIES))
    if isinstance(ser, dict):
        n = len(ser.get("days", []))
        check(n > 0 and all(len(ser.get(k, [])) == n for k in ("newDrill", "total", "horizontal")), "%s: its lists differ in length" % SERIES)
        check(ser.get("days", []) == sorted(set(ser.get("days", []))), "%s: the days are not in order" % SERIES)
        check(all(0 <= h <= nd <= t for h, nd, t in zip(ser.get("horizontal", []), ser.get("newDrill", []), ser.get("total", []))), "%s: the counts do not nest" % SERIES)
    else:
        bad.append("%s is missing or malformed" % SERIES)
    names = sorted(f for f in os.listdir(out_dir) if DAY_FILE.fullmatch(f))
    check(names, "no day files")
    idx = D.read_json(os.path.join(out_dir, "index.json"))
    if isinstance(idx, dict) and isinstance(idx.get("days"), list):
        check([r.get("d") for r in idx["days"]] == [f[:-5] for f in names], "index.json does not list exactly the day files")
        check(len(idx["days"]) <= keep, "index.json holds more than %d days" % keep)
        check(os.path.getsize(os.path.join(out_dir, "index.json")) <= BUDGET_BYTES["index.json"], "index.json is over its size budget")
    else:
        bad.append("index.json is missing or malformed")
    county_codes = {f["properties"]["f"] for f in D.read_json(COUNTIES_GEO, {"features": []})["features"]}
    for f in names:
        path = os.path.join(out_dir, f)
        text = open(path, encoding="utf-8").read()
        rep = D.read_json(path)
        if not isinstance(rep, dict):
            bad.append("%s is not JSON" % f)
            continue
        check(rep.get("v") == 1 and rep.get("date") == f[:-5] and rep.get("state") == "NM", "%s: wrong version, date or state" % f)
        check(rep.get("kind") in ("live", "reconstructed"), "%s: unknown kind" % f)
        check([d.get("id") for d in rep.get("datasets", [])] == [s["id"] for s in DATASETS], "%s: the dataset list is not the one OCD dataset" % f)
        check(os.path.getsize(path) <= BUDGET_BYTES["day"], "%s is over its size budget" % f)
        check(not re.search(r"\b\d\d-\d\d\d-\d{5}\b|@|https?://", text), "%s: holds an API number, an address or a link" % f)
        p = rep.get("permits")
        if p:
            check(0 <= p["horizontal"] + p["directional"] + p["vertical"] <= p["newDrill"] <= p["total"], "%s: permit counts do not nest" % f)
            check(sum(n for _, n in p["types"]) == p["total"], "%s: permit types do not add up" % f)
            check(sum(n for _, _, n in p["counties"]) <= p["newDrill"], "%s: the counties exceed the permits" % f)
            check(not county_codes or all(c in county_codes for c, _, _ in p["counties"]), "%s: a county that is not one of the 33" % f)
            check(p["day"] < f[:-5], "%s: permits are not from before the report day" % f)
    return bad


def plan_dates(R, keep, backfill, history, have):
    """The days to build, oldest first, ending with the report day R: the missing days before it. With history that is the whole archive;
    otherwise at most SAFE_BACKFILL days. Returns (dates, capped)."""
    window = keep - 1 if history else min(backfill, SAFE_BACKFILL)
    todo = [R - timedelta(days=i) for i in range(window, 0, -1) if (R - timedelta(days=i)).isoformat() not in have]
    return todo + [R], (not history and backfill > SAFE_BACKFILL)


def captured_for_the_night(out_dir, R):
    """When R's report was captured live, with the layer read, at or after 03:00 UTC the next day; None otherwise."""
    prior = D.read_json(os.path.join(out_dir, R.isoformat() + ".json"))
    if not isinstance(prior, dict):
        return None
    cutoff = (datetime(R.year, R.month, R.day, tzinfo=timezone.utc) + timedelta(days=1, hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    at = prior.get("capturedAt")
    ok = prior.get("kind") == "live" and prior.get("status") == "ok" and isinstance(at, str) and at >= cutoff
    return at if ok else None


# ------------------------------------------------------------------------------------------------ run

def main():
    ap = argparse.ArgumentParser(description="D9 (daily): the daily New Mexico report (see the module docstring)")
    ap.add_argument("--date", help="report date, default today in Central time")
    ap.add_argument("--backfill", type=int, default=0, help="also rebuild the missing days of the last N")
    ap.add_argument("--history", action="store_true", help="rebuild every missing day of the archive (the layer holds the approvals still open)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--keep", type=int, default=KEEP_DAYS)
    ap.add_argument("--check", action="store_true", help="only reload and check the files already in --out")
    ap.add_argument("--skip-if-captured", action="store_true", help="do nothing when the report day was already captured live at or after 03:00 UTC the next day")
    a = ap.parse_args()
    if a.check:
        problems = validate(a.out, a.keep)
        for pr in problems:
            log("CHECK failed: " + pr)
        log("checks ok (%s)" % a.out if not problems else "%d problem(s)" % len(problems))
        sys.exit(1 if problems else 0)
    today = D.central_now().date()
    try:
        R = date.fromisoformat(a.date) if a.date else today
    except ValueError:
        sys.exit("--date must be a real day like 2026-10-30")
    if R > today:
        sys.exit("--date cannot be a day that has not started yet in Central time (today is %s)" % today)
    os.makedirs(a.out, exist_ok=True)
    if a.skip_if_captured:
        got = captured_for_the_night(a.out, R)
        if got:
            log("report %s was already captured live at %s; nothing to do" % (R, got))
            sys.exit(0)
    lk = Lookups()
    if not lk.county:
        sys.exit("counties-nm.geo.json is missing: run d9_nm_monthly.py --counties first")
    have = {f[:-5] for f in os.listdir(a.out) if DAY_FILE.fullmatch(f)}
    dates, capped = plan_dates(R, a.keep, a.backfill, a.history, have)
    if capped:
        log("backfill: only the last %d missed days are rebuilt (older days need --history)" % SAFE_BACKFILL)
    kind_by_date = {d: ("live" if d == R else "reconstructed") for d in dates}
    try:
        attrs = fetch_approvals(min(dates) - timedelta(days=LOOKBACK + 1))
        edit = fetch_layer_edit()
    except Exception as e:  # noqa: BLE001
        log("permits       SKIPPED (%s)" % e)
        sys.exit(1)
    rows = to_rows(attrs, today)
    log("permits       ok (%d approvals read, the layer last edited %s UTC)" % (len(rows), edit.strftime("%Y-%m-%d %H:%M") if edit else "at a time it does not say"))
    if not rows:
        log("the layer returned no approvals in the window: nothing written")
        sys.exit(1)
    reports = build_reports(dates, group_by_day(rows), kind_by_date, lk, central_digits(edit) if edit else None)
    live = reports[R]
    live["status"] = "ok"
    live["capturedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for d, rep in reports.items():
        if d != R:
            rep["status"] = "ok"
    update_states(live, a.out)
    fetched_from = min(dates) - timedelta(days=LOOKBACK + 1)
    last_day = min(R - timedelta(days=1), (D.central_day(edit.replace(tzinfo=None)) if edit else R - timedelta(days=1)))
    update_series(a.out, group_by_day(rows), fetched_from, last_day, a.keep)
    keep_from = R - timedelta(days=a.keep - 1)
    for d, rep in sorted(reports.items()):
        D.write_json(os.path.join(a.out, d.isoformat() + ".json"), rep)
    for f in os.listdir(a.out):
        if DAY_FILE.fullmatch(f) and f[:-5] < keep_from.isoformat():
            os.remove(os.path.join(a.out, f))
    index = [headline(D.read_json(os.path.join(a.out, f))) for f in sorted(os.listdir(a.out)) if DAY_FILE.fullmatch(f)]
    D.write_json(os.path.join(a.out, "index.json"), {"generated": live["capturedAt"], "keep": a.keep, "days": index})
    log("report %s: ok | %d day files" % (R, len(index)))
    problems = validate(a.out, a.keep)
    for pr in problems:
        log("CHECK failed: " + pr)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
