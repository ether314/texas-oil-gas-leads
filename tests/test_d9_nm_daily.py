"""Tests for site/pipeline/d9_nm_daily.py: New Mexico's Daily report, from the wells in status New of the OCD's well layer.

Synthetic records, written the way the layer returns them, cover the rules (one well once, the real approval day, which day a report shows,
what is named, what is left out); the reports, the index and the series are built from them and validated; the whole run is driven with the
network faked (a normal night, a second run, a backup run, a failure that must write nothing); mutants patch one rule at a time and require
the checks to notice. The committed archive is validated too.

Run: python3 -I tests/test_d9_nm_daily.py
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
spec = importlib.util.spec_from_file_location("d9d", os.path.join(PIPE, "d9_nm_daily.py"))
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)
D = N.D

TMP = tempfile.mkdtemp()
FAILS = []
TODAY = date(2026, 10, 31)  # a Saturday


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def ms(day):
    """The layer stores an approval day as midnight UTC."""
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def rec(api, day, ogrid=7377, name="EOG RESOURCES INC", county=25, cname="Lea", kind="Oil", direction="H", district="Hobbs", eff=None):
    return {"id": api, "effective_date": ms(day) if eff is None else eff, "last_edited_on": ms(day), "county_code": county, "county": cname, "type": kind,
            "directional_status": direction, "ogrid": ogrid, "ogrid_name": name, "district": district}


def attrs():
    out, n = [], 0

    def add(day, **kw):
        nonlocal n
        n += 1
        out.append(rec("30-025-%05d" % (50000 + n), day, **kw))
    # Thursday Oct 22: 3 EOG horizontals, a Coterra gas well in Eddy, an individual's vertical, a dba's directional
    for _ in range(3):
        add(date(2026, 10, 22))
    add(date(2026, 10, 22), ogrid=215099, name="Coterra Energy Operating Co.", county=15, cname="Eddy", kind="Gas", district="Artesia")
    add(date(2026, 10, 22), ogrid=55555, name="JOHN Q PUBLIC", direction="V")
    add(date(2026, 10, 22), ogrid=66666, name="SMITH DBA SMITH OIL CO", direction="D")
    # Friday Oct 23: 2 Mewbourne in Lea
    add(date(2026, 10, 23), ogrid=14744, name="MEWBOURNE OIL CO")
    add(date(2026, 10, 23), ogrid=14744, name="MEWBOURNE OIL CO")
    # Monday Oct 26: nothing (a holiday for the test); Tuesday Oct 27: 1 saltwater disposal well, no direction
    add(date(2026, 10, 27), kind="Salt Water Disposal", direction="")
    # Wednesday Oct 28: two wells, one of them in the layer twice (a record per location)
    add(date(2026, 10, 28))
    out.append(dict(out[-1]))                      # the same well in the layer twice
    add(date(2026, 10, 28))
    # records that are not approvals
    out.append(rec("30-025-59001", date(1900, 1, 1)))                                       # a 1900 placeholder
    out.append(rec("30-025-59002", date(2026, 10, 20), eff=None) | {"effective_date": None})  # no approval day
    out.append(rec("30-025-59003", date(2026, 11, 20)))                                      # a day that has not happened
    out.append(rec("not an api", date(2026, 10, 21)))
    out.append(rec("30-025-59004", date(2026, 10, 21), county=0, cname=""))                  # no county: counted, never in a county
    return out


INV = {
    "status": {"Active": 100, "Plugged (site released)": 40, "Plugged (not released)": 10, "New": 25, "Cancelled": 20, "Temporary Abandonment": 3, "Never Drilled": 2},
    "types": {"Oil": 60, "Gas": 30, "Injection": 6, "Salt Water Disposal": 4},
    "counties": [(25, "Lea", 70), (15, "Eddy", 20), (45, "San Juan", 10)],
    "ops": [(7377, "EOG RESOURCES INC", 50), (14744, "MEWBOURNE OIL CO", 30), (55555, "JOHN Q PUBLIC", 12), (66666, "SMITH DBA SMITH OIL CO", 5), (None, "", 3)],
}


def run_checks(quiet=False):
    fails = []

    def chk(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    rows = N.to_rows(attrs(), TODAY)
    by = N.group_by_day(rows)
    chk(len(rows) == 12, "to_rows: one row per real approval, a well once (a repeat, a 1900 placeholder, no day, a future day and a bad API number are skipped): %d" % len(rows))
    chk(len(by[date(2026, 10, 22)]) == 6 and len(by[date(2026, 10, 28)]) == 2 and date(2026, 10, 21) in by, "by day: Oct 22 has 6, Oct 28 has its 2 wells counted once each")
    chk(all("api" not in r for r in rows), "an API number is read to count a well once and is not kept on the row")

    # ---- the day a report shows
    nd = N.newest_day
    chk(nd(by, date(2026, 10, 24)) == date(2026, 10, 23), "Saturday Oct 24's report shows Friday's approvals")
    chk(nd(by, date(2026, 10, 26)) == date(2026, 10, 23), "Monday Oct 26's report shows Friday's too")
    chk(nd(by, date(2026, 10, 28)) == date(2026, 10, 27), "Wednesday's report shows Tuesday's (Monday had none)")
    chk(nd(by, date(2026, 10, 23)) == date(2026, 10, 22), "a report never shows its own day: the day's approvals reach the layer later")
    chk(nd(by, date(2026, 11, 7)) == date(2026, 10, 28) and nd(by, date(2026, 11, 8)) is None, "a report reaches back at most 10 days for a day with approvals, and shows none after that")

    # ---- what a day says
    lk = N.Lookups()
    p = N.permits_section(date(2026, 10, 22), by[date(2026, 10, 22)], lk)
    chk((p["total"], p["newDrill"], p["horizontal"], p["vertical"], p["directional"]) == (6, 6, 4, 1, 1), "counts and direction: 4 horizontal, 1 vertical, 1 directional of 6: %s" % {k: p[k] for k in ("total", "horizontal", "vertical", "directional")})
    chk(p["types"] == [["Oil", 5], ["Gas", 1]] and sum(n for _, n in p["types"]) == p["total"], "kinds of well add up to the permits: %s" % p["types"])
    chk(p["counties"] == [["025", "Lea", 5], ["015", "Eddy", 1]] and p["countyCount"] == 2, "counties by their layer code, largest first, named from the shapes: %s" % p["counties"])
    chk(p["districts"] == [["Hobbs", 5], ["Artesia", 1]], "OCD districts: %s" % p["districts"])
    chk(p["operators"][0] == ["7377", "EOG Resources Inc", 3] and p["operatorCount"] == 4, "operators, largest first, the first named: %s" % p["operators"][:2])
    names = {o[0]: o[1] for o in p["operators"]}
    chk(names["55555"] is None and names["66666"] is None and names["215099"] == "Coterra Energy Operating Co.", "an individual and a person's dba are counted and never named; a corporation is")
    chk(p["namedShare"] == round(4 / 6, 3), "the share of permits that went to named operators: %s" % p["namedShare"])
    chk("amended" not in p and "depth" not in p and "wait" not in p, "what the OCD does not publish (amendments, planned depth, days to approval) is absent, not zero")
    none = N.permits_section(date(2026, 10, 26), [], lk)
    chk(none["total"] == 0 and none["namedShare"] is None and none["operators"] == [], "a day with no approvals has no share, rather than a division by zero")
    nocounty = N.permits_section(date(2026, 10, 21), by[date(2026, 10, 21)], lk)
    chk(nocounty["total"] == 1 and nocounty["counties"] == [] and nocounty["countyCount"] == 0, "a permit with no county is counted and in no county")

    # ---- reports, index rows, dataset states
    dates = [date(2026, 10, 24), date(2026, 10, 28), date(2026, 10, 31)]
    kinds = {d: ("live" if d == dates[-1] else "reconstructed") for d in dates}
    reps = N.build_reports(dates, by, kinds, lk, "2026-10-29T11:31:51")
    chk([reps[d]["permits"]["day"] for d in dates[:2]] == ["2026-10-23", "2026-10-27"] and reps[dates[2]]["permits"]["day"] == "2026-10-28", "each report holds the newest earlier day with approvals")
    chk(reps[dates[2]]["datasets"][0]["file"]["modified"] == "2026-10-29T11:31:51" and reps[dates[0]]["datasets"][0]["file"] is None, "a live report shows the layer's last edit as its file time; a rebuilt one has none")
    row = N.headline(reps[dates[0]])
    chk(row["dd"] == "2026-10-23" and row["pn"] == 2 and row["pd"] == 2 and row["k"] == "reconstructed", "the index row: permit day, new-drill and horizontal counts: %s" % row)
    out = os.path.join(TMP, "states")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    first = copy.deepcopy(reps[dates[2]])
    first["date"] = "2026-10-30"
    first["kind"] = "live"
    D.write_json(os.path.join(out, "2026-10-30.json"), first)
    same = copy.deepcopy(reps[dates[2]])
    N.update_states(same, out)
    chk(same["datasets"][0]["state"] == "same", "a layer last edited at the same time as in the previous live report is 'same' (nothing new overnight)")
    later = copy.deepcopy(reps[dates[2]])
    later["datasets"][0]["file"]["modified"] = "2026-10-30T09:00:00"
    N.update_states(later, out)
    chk(later["datasets"][0]["state"] == "new", "a later edit is 'new'")
    os.remove(os.path.join(out, "2026-10-30.json"))
    alone = copy.deepcopy(reps[dates[2]])
    N.update_states(alone, out)
    chk(alone["datasets"][0]["state"] == "first", "with no live report before it, 'first'")

    # ---- the series: the layer as it stands, absent past what it knows
    sdir = os.path.join(TMP, "series")
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir)
    doc = N.update_series(sdir, by, date(2026, 10, 20), date(2026, 10, 28), 92)
    cells = dict(zip(doc["days"], zip(doc["newDrill"], doc["horizontal"])))
    chk(doc["days"][0] == "2026-10-20" and doc["days"][-1] == "2026-10-28" and cells["2026-10-22"] == (6, 4) and cells["2026-10-26"] == (0, 0) and cells["2026-10-28"] == (2, 2),
        "the series has a count (a zero on a day with none) for every day to the last one the layer speaks for: %s" % cells)
    by2 = N.group_by_day(N.to_rows(attrs() + [rec("30-025-70001", date(2026, 10, 22))], TODAY))
    doc2 = N.update_series(sdir, by2, date(2026, 10, 22), date(2026, 10, 28), 92)
    cells2 = dict(zip(doc2["days"], doc2["newDrill"]))
    chk(cells2["2026-10-22"] == 7 and cells2["2026-10-20"] == cells["2026-10-20"][0], "a later run rewrites the days it read (the layer caught up: 7) and keeps the older days as they were")
    doc3 = N.update_series(sdir, by2, date(2026, 10, 29), date(2026, 10, 28), 92)
    chk(doc3["days"][-1] == "2026-10-28", "a day past the layer's last edit is absent, not zero")

    # ---- the inventory: counts, never a list
    w = N.wells_section(INV, "2026-10-29", lk)
    chk((w["total"], w["active"], w["plugged"]) == (200, 100, 50), "the inventory: 200 wells, 100 active, 50 plugged (both kinds of plugged): %s" % {k: w[k] for k in ("total", "active", "plugged")})
    chk(w["status"] == [["Active", 100], ["Plugged (site released)", 40], ["New", 25], ["Cancelled", 20], ["Plugged (not released)", 10], ["Other", 5]] and sum(n for _, n in w["status"]) == w["total"],
        "the status mix keeps the five largest and adds the rest as Other, so it adds up to the total: %s" % w["status"])
    chk(w["activeTypes"] == [["Oil", 60], ["Gas", 30], ["Injection, disposal and other", 10]], "kinds of active well: oil, gas, and the rest together: %s" % w["activeTypes"])
    chk(w["counties"] == [["025", "Lea", 70], ["015", "Eddy", 20], ["045", "San Juan", 10]] and w["countyCount"] == 3, "active wells by county code, named from the shapes: %s" % w["counties"])
    chk(w["operators"] == [["EOG Resources Inc", 50], ["Mewbourne Oil Co", 30]] and w["operatorCount"] == 4 and w["unnamed"] == 17 and w["unassigned"] == 3,
        "named operators only (an individual and a person's dba are counted apart, wells with no operator too): %s unnamed %s unassigned %s" % (w["operators"], w["unnamed"], w["unassigned"]))
    rep = N.build_reports([date(2026, 10, 31), date(2026, 10, 30)], by, {date(2026, 10, 31): "live", date(2026, 10, 30): "reconstructed"}, lk, "2026-10-29T11:31:51", INV)
    chk("wells" in rep[date(2026, 10, 31)] and "wells" not in rep[date(2026, 10, 30)], "a live report holds the inventory; a rebuilt one cannot (the layer holds only the current one)")
    chk([x["id"] for x in rep[date(2026, 10, 31)]["datasets"]] == ["permits", "wells"] and rep[date(2026, 10, 30)]["datasets"][1].get("absent") is True and rep[date(2026, 10, 30)]["datasets"][1]["file"] is None,
        "both datasets are listed; the rebuilt day's inventory is marked absent, not an error")
    miss = N.build_reports([date(2026, 10, 31)], by, {date(2026, 10, 31): "live"}, lk, "2026-10-29T11:31:51", None, "timeout")[date(2026, 10, 31)]
    chk("wells" not in miss and miss["datasets"][1]["error"] == "timeout" and miss["datasets"][0]["error"] is None, "when the inventory could not be read the permits are still a report and the dataset says why")
    chk(N.headline(rep[date(2026, 10, 31)])["w"] == 100 and N.headline(rep[date(2026, 10, 30)])["w"] is None, "the index row carries the active wells, none for a rebuilt day")
    cdir = os.path.join(TMP, "change")
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(cdir)
    prev = copy.deepcopy(rep[date(2026, 10, 31)])
    prev["date"] = "2026-10-29"
    prev["wells"]["active"], prev["wells"]["plugged"], prev["wells"]["total"] = 95, 48, 190
    D.write_json(os.path.join(cdir, "2026-10-29.json"), prev)
    nowrep = copy.deepcopy(rep[date(2026, 10, 31)])
    N.add_wells_change(nowrep, cdir)
    chk(nowrep["wells"]["change"] == {"since": "2026-10-29", "active": 5, "plugged": 2, "total": 10}, "the change since the previous report that had an inventory: %s" % nowrep["wells"].get("change"))

    # ---- planning
    have = {"2026-10-29"}
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 3, False, have)
    chk([d.isoformat() for d in dts] == ["2026-10-28", "2026-10-30", "2026-10-31"] and not capped, "plan_dates: the missing days of the last 3, then the report day")
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 30, False, set())
    chk(len(dts) == N.SAFE_BACKFILL + 1 and capped, "without --history a backfill reaches back at most %d days, and says it was capped" % N.SAFE_BACKFILL)
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 0, True, set())
    chk(len(dts) == 92 and dts[0] == date(2026, 8, 1) and not capped, "--history rebuilds the whole archive: 92 days from Aug 1")
    # a county code that is not one of the state's 33 (a typo in the layer) is no county: the well is counted, never placed in one
    typo = [rec("30-025-70001", date(2026, 10, 29), county=99, cname="Typo"), rec("30-025-70002", date(2026, 10, 29))]
    known = {"025", "015", "045"}
    chk([r["county"] for r in N.to_rows(typo, TODAY, known)] == ["", "025"], "a county code that is not one of the state's is no county, the well still counted")
    chk([r["county"] for r in N.to_rows(typo, TODAY)] == ["099", "025"], "and without a list of the state's counties every code passes (the rule is the caller's)")
    lk_ = N.Lookups()
    sec = N.permits_section(date(2026, 10, 29), N.to_rows(typo, TODAY, set(lk_.county)), lk_)
    chk(sec["total"] == 2 and sum(n for _, _, n in sec["counties"]) == 1 and sec["countyCount"] == 1, "so the day counts both permits and lists one county")
    inv_typo = dict(INV, counties=INV["counties"] + [(99, "Typo", 1)])
    w = N.wells_section(inv_typo, "2026-10-29", lk_)
    chk(all(c != "099" for c, _, _ in w["counties"]) and w["active"] == 100, "an inventory county that is not one of the state's is left out of the county list, not out of the totals")
    return fails


# ---- the inventory's four counts -------------------------------------------------------------------------------------------------------

def inventory_checks():
    def asked(table):
        def q(params, retries=4):
            return {"features": [{"attributes": a} for a in table[params["groupByFieldsForStatistics"]]]}
        return q

    def good(**over):
        t = {"status": [{"status": "Active", "n": 100}, {"status": "Plugged (site released)", "n": 40}],
             "type": [{"type": "Oil", "n": 60}, {"type": "Gas", "n": 40}],
             "county_code,county": [{"county_code": 25, "county": "Lea", "n": 70}, {"county_code": 15, "county": "Eddy", "n": 30}],
             "ogrid,ogrid_name": [{"ogrid": 7377, "ogrid_name": "EOG RESOURCES INC", "n": 80}, {"ogrid": None, "ogrid_name": None, "n": 20}]}
        t.update(over)
        return t

    def fetch(table):
        saved = N.query
        N.query = asked(table)
        try:
            return N.fetch_inventory(), None
        except RuntimeError as e:
            return None, str(e)
        finally:
            N.query = saved
    inv, err = fetch(good())
    check(inv and sum(inv["status"].values()) == 140 and sum(n for _, _, n in inv["counties"]) == 100, "an inventory whose parts add up to the active wells is accepted")
    # a county under two spellings is one county; a missing status and an empty one are one status
    inv, err = fetch(good(**{"county_code,county": [{"county_code": 25, "county": "Lea", "n": 30}, {"county_code": 25, "county": "LEA ", "n": 40}, {"county_code": 15, "county": "Eddy", "n": 30}],
                             "status": [{"status": None, "n": 3}, {"status": "", "n": 4}, {"status": "Active", "n": 100}]}))
    lea = [n for c, _, n in (inv or {"counties": []})["counties"] if c == 25]
    check(inv and lea == [70] and inv["status"].get("") == 7 and sum(inv["status"].values()) == 107, "groups are added, not overwritten: a county under two spellings reports 70 (not 40), an empty and a missing status 7 (not 4)")
    inv, err = fetch(good(type=[]))
    check(inv is None and err and "kind" in err, "an answer with no kinds at all (HTTP 200, no features) is refused, so the report is partial: %s" % err)
    inv, err = fetch(good(**{"county_code,county": [{"county_code": 25, "county": "Lea", "n": 60}]}))
    check(inv is None and err and "county" in err, "counties that add up to 60 of 100 active wells are refused: %s" % err)
    inv, err = fetch(good(**{"ogrid,ogrid_name": [{"ogrid": 7377, "ogrid_name": "EOG RESOURCES INC", "n": 80}]}))
    check(inv is None and err and "operator" in err, "operators that add up to 80 of 100 active wells are refused: %s" % err)
    inv, err = fetch(good(type=[{"type": "Oil", "n": 60}, {"type": "Gas", "n": 45}]))
    check(inv is not None, "a few wells of difference (an edit between two requests) are tolerated")


# ---- a whole run with the network faked ------------------------------------------------------------------------------------------------

def run_main(out, argv, records, edit=None, fail=False, no_inventory=False, now=None):
    """Drive main() against a scratch folder, with the two requests answered from `records` (or failing); returns (exit code, log text).
    `now` is the Central wall clock of the run (default: 22:15 on Saturday Oct 31)."""
    saved = (N.fetch_approvals, N.fetch_layer_edit, N.fetch_inventory, N.D.central_now, sys.argv)
    N.fetch_approvals = lambda since: list(records)
    N.fetch_layer_edit = lambda: edit
    N.fetch_inventory = (lambda: (_ for _ in ()).throw(RuntimeError("the layer returned no wells"))) if no_inventory else (lambda: INV)
    if fail:
        def boom(since):
            raise RuntimeError("could not read the New Mexico wells layer: timeout")
        N.fetch_approvals = boom
    N.D.central_now = lambda: now or datetime(2026, 10, 31, 22, 15, tzinfo=timezone(timedelta(hours=-5)))
    sys.argv = ["d9_nm_daily.py", "--out", out] + argv
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            try:
                N.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
    finally:
        N.fetch_approvals, N.fetch_layer_edit, N.fetch_inventory, N.D.central_now, sys.argv = saved
    return code, buf.getvalue()


def whole_run():
    out = os.path.join(TMP, "run")
    shutil.rmtree(out, ignore_errors=True)
    edit = datetime(2026, 10, 29, 16, 31, 51, tzinfo=timezone.utc)
    recs = attrs()
    code, text = run_main(out, ["--history", "--keep", "12", "--date", "2026-10-30"], recs, edit)
    check(code == 0, "a run with history writes the archive and checks it: exit %s" % code)
    names = sorted(f for f in os.listdir(out) if f[0].isdigit())
    check(len(names) == 12 and names[-1] == "2026-10-30.json" and names[0] == "2026-10-19.json", "12 day files ending on the report day: %s..%s" % (names[0], names[-1]))
    idx = D.read_json(os.path.join(out, "index.json"))
    check([r["d"] for r in idx["days"]] == [f[:-5] for f in names] and idx["days"][-1]["k"] == "live" and idx["days"][0]["k"] == "reconstructed", "the index lists them, the last one live and the rest rebuilt")
    live = D.read_json(os.path.join(out, "2026-10-30.json"))
    check(live["status"] == "ok" and live["capturedAt"].endswith("Z") and live["datasets"][0]["state"] == "first" and live["datasets"][0]["file"]["modified"] == "2026-10-29T11:31:51",
          "the live report: ok, a capture time, the first live capture, the layer's edit time in Central digits")
    check(live["wells"]["active"] == 100 and live["datasets"][1]["state"] == "first" and D.read_json(os.path.join(out, "2026-10-29.json")).get("wells") is None, "the live report holds the inventory (first capture); the rebuilt days do not")
    ser = D.read_json(os.path.join(out, "permits-series.json"))
    check(ser["asOf"] == "2026-10-29" and ser["days"][-1] == "2026-10-29", "the series ends on the day of the layer's last edit (Oct 29), not the day before the report (Oct 30)")
    all_text = "".join(open(os.path.join(out, f), encoding="utf-8").read() for f in os.listdir(out))
    check("30-025-" not in all_text and "JOHN Q PUBLIC" not in all_text.upper() and "SMITH" not in all_text.upper(), "nothing in the files names a well, an API number or a person")

    before = {f: open(os.path.join(out, f), "rb").read() for f in os.listdir(out) if f[0].isdigit()}
    code, text = run_main(out, ["--date", "2026-10-31"], recs, edit)
    after = {f: open(os.path.join(out, f), "rb").read() for f in before}
    check(code == 0 and before == after and os.path.exists(os.path.join(out, "2026-10-31.json")), "the next night adds its own day: the earlier reports are byte for byte as they were")
    live2 = D.read_json(os.path.join(out, "2026-10-31.json"))
    check(live2["datasets"][0]["state"] == "same" and live2["datasets"][1]["state"] == "same" and live2["wells"]["change"]["since"] == "2026-10-30" and live2["wells"]["change"]["active"] == 0,
          "and says the layer has not changed since the last live report, with the inventory's change since it")
    code, text = run_main(out, ["--date", "2026-10-31"], recs, datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc))
    check(code == 0 and D.read_json(os.path.join(out, "2026-10-31.json"))["datasets"][0]["state"] == "new", "a layer edited since the last live report is 'new'")

    live3 = D.read_json(os.path.join(out, "2026-10-31.json"))
    live3["capturedAt"] = "2026-10-31T22:16:00Z"
    D.write_json(os.path.join(out, "2026-10-31.json"), live3)
    code, text = run_main(out, ["--date", "2026-10-31", "--skip-if-captured"], recs, edit)
    check(code == 0 and "nothing to do" not in text, "--skip-if-captured does not skip a day captured before 03:00 UTC the next day (the backup run takes it over)")
    live3 = D.read_json(os.path.join(out, "2026-10-31.json"))
    live3["capturedAt"] = "2026-11-01T03:16:00Z"
    D.write_json(os.path.join(out, "2026-10-31.json"), live3)
    code, text = run_main(out, ["--date", "2026-10-31", "--skip-if-captured"], recs, edit)
    check(code == 0 and "nothing to do" in text, "--skip-if-captured does skip a day already captured live at or after 03:00 UTC the next day")

    # one permit with a county code that is not one of the 33 does not stop the night
    badc = os.path.join(TMP, "badcounty")
    shutil.rmtree(badc, ignore_errors=True)
    code, text = run_main(badc, ["--history", "--keep", "12", "--date", "2026-10-30"], recs + [rec("30-025-99999", date(2026, 10, 28), county=99, cname="Typo")], edit)
    bc = D.read_json(os.path.join(badc, "2026-10-30.json"))
    check(code == 0 and bc["permits"]["total"] == D.read_json(os.path.join(out, "2026-10-30.json"))["permits"]["total"] + 1 and all(c != "099" for c, _, _ in bc["permits"]["counties"]),
          "a permit with a county code that is not one of the 33 is counted, placed in no county, and does not fail the check: exit %s" % code)
    part = os.path.join(TMP, "partial")
    shutil.rmtree(part, ignore_errors=True)
    code, text = run_main(part, [], recs, edit, no_inventory=True)
    pr = D.read_json(os.path.join(part, "2026-10-31.json"))
    check(code == 0 and pr["status"] == "partial" and "wells" not in pr and pr["permits"] and pr["datasets"][1]["error"], "an inventory that cannot be read leaves the permits as a partial report (the backup run will try again); exit %s" % code)
    check(N.captured_for_the_night(part, date(2026, 10, 31)) is None, "and a partial report does not count as captured for the night")
    # a second capture of the same day that cannot read the inventory keeps the one the first captured
    code, text = run_main(part, [], recs, edit)
    first = D.read_json(os.path.join(part, "2026-10-31.json"))
    code2, text2 = run_main(part, [], recs, edit, no_inventory=True)
    again = D.read_json(os.path.join(part, "2026-10-31.json"))
    check(code == 0 and first["status"] == "ok" and code2 == 0 and again["status"] == "partial" and again["wells"] == first["wells"] and again["datasets"][1]["error"] is None and again["capturedAt"] >= first["capturedAt"],
          "a second capture of a day that cannot read the inventory keeps the first one's (the report is partial, so the backup run tries again)")
    check(D.read_json(os.path.join(part, "index.json"))["days"][-1]["w"] == 100 and not N.validate(part, 92), "the index still shows its active wells, and the files check")
    quiet = os.path.join(TMP, "quiet")
    shutil.rmtree(quiet, ignore_errors=True)
    code, text = run_main(quiet, [], recs, edit, fail=True)
    check(code == 1 and not [f for f in os.listdir(quiet) if f[0].isdigit()] and "SKIPPED" in text, "when the layer cannot be read nothing is written and the run fails (the workflow carries on without it)")
    code, text = run_main(quiet, [], [], edit)
    check(code == 1 and not [f for f in os.listdir(quiet) if f[0].isdigit()], "a layer that answers with no approvals at all writes nothing")
    code, text = run_main(quiet, ["--date", "2026-11-05"], recs, edit)
    check(code != 0, "a report day that has not started yet is refused")

    # ---- the validator on faults
    def fault(label, mutate, expect):
        d = os.path.join(TMP, "fault")
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(out, d)
        mutate(d)
        problems = N.validate(d, 92)
        check(any(expect in x for x in problems), "validate notices %s: %s" % (label, problems[:2]))

    def edit_day(d, fn):
        path = os.path.join(d, "2026-10-30.json")
        rep = D.read_json(path)
        fn(rep)
        D.write_json(path, rep)
    fault("an API number in a file", lambda d: edit_day(d, lambda r: r["datasets"][0].__setitem__("title", "30-025-12345")), "API number")
    fault("kinds that do not add up", lambda d: edit_day(d, lambda r: r["permits"]["types"].append(["Oil", 3])), "types do not add up")
    fault("more horizontal than permits", lambda d: edit_day(d, lambda r: r["permits"].__setitem__("horizontal", 99)), "do not nest")
    fault("a county that is not in the state", lambda d: edit_day(d, lambda r: r["permits"].__setitem__("counties", [["999", "Nowhere", 1]])), "one of the 33")
    fault("permits from the report day itself", lambda d: edit_day(d, lambda r: r["permits"].__setitem__("day", "2026-10-31")), "not from before")
    fault("an index that misses a day", lambda d: D.write_json(os.path.join(d, "index.json"), {"keep": 12, "days": D.read_json(os.path.join(d, "index.json"))["days"][1:]}), "exactly the day files")
    fault("an inventory that does not add up", lambda d: edit_day(d, lambda r: r["wells"]["status"].append(["Active", 7])), "does not add up")
    def inventory_on_rebuilt_day(d):
        wells = D.read_json(os.path.join(d, "2026-10-30.json"))["wells"]
        path = os.path.join(d, "2026-10-29.json")
        rep = D.read_json(path)
        rep["wells"] = wells
        D.write_json(path, rep)
    fault("an inventory on a rebuilt day", inventory_on_rebuilt_day, "rebuilt day cannot hold")
    fault("a missing series", lambda d: os.remove(os.path.join(d, "permits-series.json")), "permits-series.json")
    fault("a series with lists of different lengths", lambda d: D.write_json(os.path.join(d, "permits-series.json"), {"days": ["2026-10-20"], "newDrill": [], "total": [], "horizontal": []}), "differ in length")
    fault("a day file that is not JSON", lambda d: open(os.path.join(d, "2026-10-29.json"), "w").write("{"), "not JSON")


def settle_scenario(quiet=False):
    """Three nights against a layer that is entered late: the figures of the reports already written settle as it catches up (report, index and chart
    alike), the day a report shows and everything else in it stay as captured, and a report older than the window is left alone."""
    fails = []

    def chk(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    def layer(counts):
        out, n = [], 0
        for d, k in sorted(counts.items()):
            for _ in range(k):
                n += 1
                out.append(rec("30-025-%05d" % (80000 + n), d))
        return out
    base = {date(2026, 10, 19) + timedelta(days=i): 20 for i in (0, 1, 2, 3, 4, 7, 8, 9)}  # Oct 19 to 23 and 26 to 28: twenty approvals a business day
    out = os.path.join(TMP, "settle")
    shutil.rmtree(out, ignore_errors=True)
    utc = timezone.utc
    code1, _ = run_main(out, ["--history", "--keep", "20"], layer({**base, date(2026, 10, 29): 5}), datetime(2026, 10, 30, 16, 31, tzinfo=utc))
    first = D.read_json(os.path.join(out, "2026-10-31.json"))
    old_bytes = open(os.path.join(out, "2026-10-21.json"), "rb").read()
    chk(code1 == 0 and first["permits"]["day"] == "2026-10-29" and first["permits"]["total"] == 5, "night one: Saturday's report shows Thursday's approvals as the layer has them so far (5)")
    cst = timezone(timedelta(hours=-6))
    code2, text2 = run_main(out, ["--date", "2026-11-01", "--keep", "20"], layer({**base, date(2026, 10, 29): 12, date(2026, 10, 30): 3}), datetime(2026, 10, 31, 16, 31, tzinfo=utc), now=datetime(2026, 11, 1, 21, 15, tzinfo=cst))
    mid = D.read_json(os.path.join(out, "2026-10-31.json"))
    chk(code2 == 0 and mid["permits"]["total"] == 12 and "recounted" in text2, "night two: the layer has caught up to 12, and Saturday's report is recounted to 12")
    # the layer also loses the approvals of Oct 20 (they moved on): a report older than the window must not notice
    code3, text3 = run_main(out, ["--date", "2026-11-02", "--keep", "20"], layer({**base, date(2026, 10, 20): 7, date(2026, 10, 29): 20, date(2026, 10, 30): 14}), datetime(2026, 11, 1, 16, 31, tzinfo=utc), now=datetime(2026, 11, 2, 21, 15, tzinfo=cst))
    last = D.read_json(os.path.join(out, "2026-10-31.json"))
    chk(code3 == 0 and last["permits"]["day"] == "2026-10-29" and last["permits"]["total"] == 20 and last["permits"]["newDrill"] == 20, "night three: settled at 20, and the report still shows Thursday (the day does not move)")
    chk({k: v for k, v in last.items() if k != "permits"} == {k: v for k, v in first.items() if k != "permits"}, "everything else in that report is as captured on night one: its inventory, its file times, its capture time")
    idx = {r["d"]: r for r in D.read_json(os.path.join(out, "index.json"))["days"]}
    chk(idx["2026-10-31"]["pn"] == 20 and idx["2026-10-31"]["p"] == 20 and idx["2026-11-01"]["pn"] == 14 and idx["2026-10-30"]["pn"] == 20, "the index rows (the ribbon) follow: 20, 14 and the rebuilt day before it 20")
    ser = D.read_json(os.path.join(out, "permits-series.json"))
    cells = dict(zip(ser["days"], ser["newDrill"]))
    chk(cells["2026-10-29"] == 20 and cells["2026-10-30"] == 14, "and so does the pace chart's series, so the three agree")
    chk(open(os.path.join(out, "2026-10-21.json"), "rb").read() == old_bytes, "a report older than the window is byte for byte as it was, though the layer now says otherwise about its day")
    chk(not N.validate(out, 20), "all of it checks")
    return fails


def mutants():
    """Patch one rule at a time; the checks (quietly) must notice every one."""
    orig = (N.to_rows, D.nameable, N.newest_day)

    def no_dedupe(attrs_, today, known=None):  # every record on its own, so no well is seen twice
        out = []
        for a in attrs_:
            out += orig[0]([a], today, known)
        return out

    def own_day(by, day, lookback=None):
        days = [d for d in by if d <= day and by[d]]
        return max(days) if days else None

    def no_limit(by, day, lookback=None):
        days = [d for d in by if d < day and by[d]]
        return max(days) if days else None
    rules = [
        ("a well counted once per record", lambda: setattr(N, "to_rows", no_dedupe)),
        ("everyone named", lambda: setattr(D, "nameable", lambda name: True)),
        ("nobody named", lambda: setattr(D, "nameable", lambda name: False)),
        ("a report that shows its own day", lambda: setattr(N, "newest_day", own_day)),
        ("no lookback limit", lambda: setattr(N, "newest_day", no_limit)),
    ]
    fails = []
    for label, patch in rules:
        patch()
        try:
            got = run_checks(quiet=True)
        finally:
            N.to_rows, D.nameable, N.newest_day = orig
        if got:
            print("ok   a mutant is caught: %s" % label)
        else:
            print("FAIL a mutant survived: %s" % label)
            fails.append("a mutant survived: " + label)
    saved = N.settle_permits
    N.settle_permits = lambda *a, **k: []
    try:
        got = settle_scenario(quiet=True)
    finally:
        N.settle_permits = saved
    if got:
        print("ok   a mutant is caught: no recount of the earlier reports")
    else:
        print("FAIL a mutant survived: no recount of the earlier reports")
        fails.append("a mutant survived: no recount")
    return fails


print("-- the rules")
FAILS += run_checks()
print("\n-- the inventory's four counts")
inventory_checks()
print("\n-- a whole run, the network faked")
whole_run()
print("\n-- the layer fills in late")
FAILS += settle_scenario()

print("\n-- the committed archive")
arch = os.path.join(DATA, "daily-nm")
if os.path.isdir(arch) and os.path.exists(os.path.join(arch, "index.json")):
    problems = N.validate(arch)
    check(not problems, "validate accepts the committed archive" + ("" if not problems else ": %s" % problems[:3]))
    idx = D.read_json(os.path.join(arch, "index.json"))
    check(len(idx["days"]) >= 30 and idx["days"][-1]["k"] in ("live", "reconstructed"), "it holds at least 30 days (%d)" % len(idx["days"]))
    ops = [o for f in sorted(os.listdir(arch)) if f[0].isdigit() for o in (D.read_json(os.path.join(arch, f)).get("permits") or {}).get("operators", []) if o[1]]
    check(all(D.nameable(o[1]) for o in ops), "every operator it names passes the naming rule (%d names)" % len(ops))
else:
    print("skip  the archive is not committed yet")

print("\n-- mutants")
FAILS += mutants()

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
