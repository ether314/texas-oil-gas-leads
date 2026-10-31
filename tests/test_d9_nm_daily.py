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

    # ---- planning
    have = {"2026-10-29"}
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 3, False, have)
    chk([d.isoformat() for d in dts] == ["2026-10-28", "2026-10-30", "2026-10-31"] and not capped, "plan_dates: the missing days of the last 3, then the report day")
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 30, False, set())
    chk(len(dts) == N.SAFE_BACKFILL + 1 and capped, "without --history a backfill reaches back at most %d days, and says it was capped" % N.SAFE_BACKFILL)
    dts, capped = N.plan_dates(date(2026, 10, 31), 92, 0, True, set())
    chk(len(dts) == 92 and dts[0] == date(2026, 8, 1) and not capped, "--history rebuilds the whole archive: 92 days from Aug 1")
    return fails


# ---- a whole run with the network faked ------------------------------------------------------------------------------------------------

def run_main(out, argv, records, edit=None, fail=False):
    """Drive main() against a scratch folder, with the two requests answered from `records` (or failing); returns (exit code, log text)."""
    saved = (N.fetch_approvals, N.fetch_layer_edit, N.D.central_now, sys.argv)
    N.fetch_approvals = lambda since: list(records)
    N.fetch_layer_edit = lambda: edit
    if fail:
        def boom(since):
            raise RuntimeError("could not read the New Mexico wells layer: timeout")
        N.fetch_approvals = boom
    N.D.central_now = lambda: datetime(2026, 10, 31, 22, 15, tzinfo=timezone(timedelta(hours=-5)))
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
        N.fetch_approvals, N.fetch_layer_edit, N.D.central_now, sys.argv = saved
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
    ser = D.read_json(os.path.join(out, "permits-series.json"))
    check(ser["asOf"] == "2026-10-29" and ser["days"][-1] == "2026-10-29", "the series ends on the day of the layer's last edit (Oct 29), not the day before the report (Oct 30)")
    all_text = "".join(open(os.path.join(out, f), encoding="utf-8").read() for f in os.listdir(out))
    check("30-025-" not in all_text and "JOHN Q PUBLIC" not in all_text.upper() and "SMITH" not in all_text.upper(), "nothing in the files names a well, an API number or a person")

    before = {f: open(os.path.join(out, f), "rb").read() for f in os.listdir(out) if f[0].isdigit()}
    code, text = run_main(out, ["--date", "2026-10-31"], recs, edit)
    after = {f: open(os.path.join(out, f), "rb").read() for f in before}
    check(code == 0 and before == after and os.path.exists(os.path.join(out, "2026-10-31.json")), "the next night adds its own day: the earlier reports are byte for byte as they were")
    live2 = D.read_json(os.path.join(out, "2026-10-31.json"))
    check(live2["datasets"][0]["state"] == "same", "and says the layer has not changed since the last live report")
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
    fault("a missing series", lambda d: os.remove(os.path.join(d, "permits-series.json")), "permits-series.json")
    fault("a series with lists of different lengths", lambda d: D.write_json(os.path.join(d, "permits-series.json"), {"days": ["2026-10-20"], "newDrill": [], "total": [], "horizontal": []}), "differ in length")
    fault("a day file that is not JSON", lambda d: open(os.path.join(d, "2026-10-29.json"), "w").write("{"), "not JSON")


def mutants():
    """Patch one rule at a time; the checks (quietly) must notice every one."""
    orig = (N.to_rows, D.nameable, N.newest_day)

    def no_dedupe(attrs_, today):  # every record on its own, so no well is seen twice
        out = []
        for a in attrs_:
            out += orig[0]([a], today)
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
    return fails


print("-- the rules")
FAILS += run_checks()
print("\n-- a whole run, the network faked")
whole_run()

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
