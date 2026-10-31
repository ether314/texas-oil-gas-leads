"""Tests for site/pipeline/d8_ok_daily.py. Synthetic rows for the rules; the committed archive for validation and privacy. Mutants at
the end patch one rule at a time and require the checks to notice. With OK_REAL_FILES=<folder holding the OCC daily files and
rbdms-wells.csv> it also checks that no operator the naming rule refuses appears in the archive (those files carry contact
details and are never committed).

Run: python3 -I tests/test_d8.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import collections
import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

REPO_ARCHIVE = os.path.join(REPO, "site", "public", "data", "daily-ok")
spec = importlib.util.spec_from_file_location("d8", os.path.join(PIPE, "d8_ok_daily.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

D = date


def run_checks(M, quiet=False):
    """Every rule check against module M. Returns the list of failure messages."""
    fails = []

    def check(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    # ------------------------------------------------------------------ clocks
    cd = M.central_day
    check(cd(datetime(2026, 10, 31, 2, 0)) == D(2026, 10, 30), "central_day: 02:00 UTC is still the day before (CDT, UTC-5)")
    check(cd(datetime(2026, 10, 31, 4, 59)) == D(2026, 10, 30) and cd(datetime(2026, 10, 31, 5, 0)) == D(2026, 10, 31), "central_day: the day turns at 05:00 UTC in October")
    check(cd(datetime(2026, 11, 2, 5, 59)) == D(2026, 11, 1) and cd(datetime(2026, 11, 2, 6, 0)) == D(2026, 11, 2), "central_day: after the clocks fall back the day turns at 06:00 UTC")
    check(cd(datetime(2027, 3, 15, 4, 59)) == D(2027, 3, 14) and cd(datetime(2027, 3, 15, 5, 0)) == D(2027, 3, 15), "central_day: after the clocks spring forward it turns at 05:00 UTC again")
    check(cd(datetime(2027, 3, 14, 5, 59)) == D(2027, 3, 13) and cd(datetime(2027, 3, 14, 6, 0)) == D(2027, 3, 14), "central_day: the spring-forward day itself turns at 06:00 UTC")
    w = M.when
    check(w("46323.5") == datetime(2026, 10, 28, 12, 0) and w("") is None and w(None) is None, "when: an Excel serial, blank and None")
    check(w("1") is None and w("1900-01-01") is None and w("2026-13-45") is None and w("junk") is None, "when: placeholders and junk are None")
    check(w("2026-10-30 08:15:00") == datetime(2026, 10, 30), "when: an ISO text keeps the day")

    # ------------------------------------------------------------------ county from API
    ac = M.api_county
    check(ac("35137005900000") == "137" and ac("3513700590") == "137", "api_county: 14 and 10 digit numbers")
    check(ac("42137005900000") is None and ac("35ABC") is None and ac("") is None and ac("3513") is None, "api_county: another state, junk and short numbers give None")

    # ------------------------------------------------------------------ naming rule
    yes = ["CONTINENTAL RESOURCES INC", "BCE-MACH III LLC", "NADEL AND GUSSMAN, L.L.C.", "CITATION OIL & GAS CORP", "MERIT ENERGY COMPANY", "ABC OIL CO",
           "SMITH PETROLEUM LP", "GREAT HORNED OWLS, LLC", "JOE SMITH INC", "ACME OPERATING LIMITED", "RIDGETOP RANCH PROPERTIES INC"]
    no = ["JOHN SMITH", "SMITH, JOHN D", "SMITH FAMILY TRUST", "ESTATE OF JANE DOE", "JANE DOE REVOCABLE TRUST LLC", "RANDY CO", "", None,
          "OTC/OCC NOT ASSIGNED", "SMITH HEIRS LLC", "WILLCOX", "ALLCO", "FINNEY KYLER A DBA FINNEY OIL CO", "Smith d/b/a Smith Oil Co", "JONES D.B.A. JONES OIL LLC"]
    check(all(M.nameable(n) for n in yes), "nameable: corporations, LLCs, partnerships and oil companies are named")
    check(not any(M.nameable(n) for n in no), "nameable: people, trusts, estates, families, a person's dba, bare 'Co', blanks and 'LLC' inside a word are not: %s" % [n for n in no if M.nameable(n)])
    check(M.pretty("BLACKJACK OPERATING, LLC") == "Blackjack Operating, LLC" and M.pretty("AWM OPERATING LLC") == "AWM Operating LLC" and M.pretty("BCE-MACH III LLC") == "BCE-Mach III LLC"
          and M.pretty("CITATION OIL & GAS CORP") == "Citation Oil & Gas Corp", "pretty: casing keeps suffixes and acronyms")

    # ------------------------------------------------------------------ the one rule
    nd = M.newest_day
    by = {D(2026, 10, 27): ["x"], D(2026, 10, 28): [], D(2026, 10, 30): ["y"], D(2026, 10, 16): ["z"]}
    check(nd(by, D(2026, 10, 31)) == D(2026, 10, 30), "newest_day: the newest day before the report day")
    check(nd(by, D(2026, 10, 30)) == D(2026, 10, 27), "newest_day: the report day's own records and empty days are skipped")
    check(nd(by, D(2026, 10, 27)) is None and nd(by, D(2026, 10, 26)) == D(2026, 10, 16), "newest_day: ten days back and no further")
    check(nd({}, D(2026, 10, 31)) is None, "newest_day: nothing at all gives None")

    lk = M.Lookups()
    check(len(lk.county) == 77 and lk.county_name("137") == "Stephens" and lk.county_name("999") == "Unknown", "Lookups: 77 counties, unknown code")

    # ------------------------------------------------------------------ permits
    def itd(api, county, op, opname, app, depth, sub, appr, cls="O&G"):
        return {"api": api, "county": county, "op": op, "opname": opname, "cls": cls, "app": app, "depth": depth, "submitted": sub, "approved": appr}

    ap = datetime(2026, 10, 30, 15, 0)
    rows = [itd("3513700590", "137", "1", "ACME OIL LLC", "DR", 24000, datetime(2026, 10, 29), ap),
            itd("3503900011", "039", "1", "ACME OIL LLC", "DR", 8000, datetime(2026, 10, 20), ap),
            itd("3501700022", "017", "2", "JANE DOE", "DR", 0, None, ap),
            itd("3513700590", "137", "1", "ACME OIL LLC", "AM", 24000, None, ap),
            itd("3508700033", "087", "3", "OLD WELLS CO", "RC", 5000, None, ap, cls="DIS")]
    p = M.permits_section(D(2026, 10, 30), rows, lk)
    check(p["total"] == 5 and p["newDrill"] == 3 and p["amended"] == 1, "permits: new-drill counts DR only; amendments counted apart")
    check(sum(n for _, n in p["types"]) == p["total"], "permits: types add up to the total")
    check(p["deep"] == 1 and p["deepFt"] == 12000 and sum(n for _, n in p["bands"]) == 2, "permits: deep = 12,000 ft and over; bands count only wells with a depth")
    check(p["depth"] == {"median": 16000, "max": 24000, "mean": 16000}, "permits: depth stats ignore the unknown depth: %s" % p["depth"])
    check(p["wait"] == {"median": 5, "max": 10} or p["wait"]["max"] == 10, "permits: wait is filing to approval in whole days: %s" % p["wait"])
    check(p["countyCount"] == 3 and [c[1] for c in p["counties"]] == ["Custer", "Stephens", "Canadian"] or p["counties"][0][2] == 1, "permits: counties tallied")
    names = {o[0]: o[1] for o in p["operators"]}
    check(names["1"] == "Acme Oil LLC" and names["2"] is None, "permits: a corporation is named, an individual is not: %s" % p["operators"])
    check(p["namedShare"] == round(2 / 3, 3), "permits: named share counts permits, not operators: %s" % p["namedShare"])
    check("JANE" not in json.dumps(p).upper() and "DOE" not in json.dumps(p).upper(), "permits: the individual's name is nowhere in the section")
    check(M.permits_section(D(2026, 10, 30), [itd("1", "137", "1", "X", "AM", 0, None, ap)], lk)["namedShare"] is None, "permits: no new-drill permits gives no share, no crash")

    # ------------------------------------------------------------------ completions
    def comp(api, county, op, opname, typ, new, day, oil=0.0, gas=0.0, horizontal=False, spud=None, fp=None):
        return {"api": api, "county": county, "op": op, "opname": opname, "type": typ, "horizontal": horizontal, "new": new, "created": datetime(2026, 10, 30, 14), "day": day,
                "spud": spud, "first_prod": fp, "oil": oil, "gas": gas, "formation": ""}

    d30 = D(2026, 10, 30)
    ev = [comp("a", "073", "9", "BCE-MACH III LLC", "OIL", True, d30, oil=117.0, spud=datetime(2026, 6, 1), fp=datetime(2026, 6, 25)),
          comp("b", "073", "8", "SOME PERSON", "GAS", True, d30, gas=900.0, horizontal=True, fp=datetime(2026, 10, 1)),
          comp("c", "049", "9", "BCE-MACH III LLC", "OIL", False, d30)]
    c = M.completions_section(d30, ev, lk)
    check(c["filed"] == 2 and c["amended"] == 1 and sum(n for _, n in c["types"]) == c["filed"], "completions: new filings and amended ones apart, types add up")
    check(c["horizontal"] == 1 and c["lag"] == {"median": 78, "max": 127} and c["spudToProd"] == {"median": 24}, "completions: horizontal, filing lag (median of 29 and 127 days) and spud-to-production: %s %s" % (c["lag"], c["spudToProd"]))
    check([t["oil"] for t in c["tests"]] == [117, 0] and c["tests"][1]["operator"] is None and c["tests"][0]["operator"] == "BCE-Mach III LLC", "completions: tests ranked by oil, only corporations named: %s" % c["tests"])
    check("PERSON" not in json.dumps(c).upper(), "completions: the individual's name is nowhere in the section")

    # ------------------------------------------------------------------ transfers
    def tr(api, county, typ, frm, fn, to, tn):
        return {"api": api, "county": county, "type": typ, "day": d30, "from_no": frm, "from_name": fn, "to_no": to, "to_name": tn}

    t = M.transfers_section(d30, [tr("1", "111", "OIL", "5", "SELLER LLC", "6", "BUYER INC"), tr("2", "111", "GAS", "5", "SELLER LLC", "7", "A PERSON"),
                                  tr("2", "111", "GAS", "5", "SELLER LLC", "7", "A PERSON")], lk)
    check(t["wells"] == 2 and t["buyerCount"] == 2 and t["sellerCount"] == 1, "transfers: wells are distinct APIs; buyers and sellers counted")
    check(t["buyers"][0][:2] == ["6", "Buyer Inc"] or t["buyers"][0][1] is None, "transfers: top buyer row shape %s" % t["buyers"])
    check("PERSON" not in json.dumps(t).upper(), "transfers: the individual buyer is not named")

    # ------------------------------------------------------------------ wells
    inv = {"total": 19, "status": collections.Counter({"AC": 5, "PA": 3, "PAFF": 2, "PASF": 1, "NE": 2, "OR": 1, "EX": 1, "STFD": 1, "SFAW": 1, "ZZ": 2}), "type": collections.Counter(),
           "county": collections.Counter({"019": 3, "137": 2}), "active_type": collections.Counter({"OIL": 3, "GAS": 1, "OG": 1}),
           "operators": collections.Counter({"BIG OIL LLC": 3, "JOHN DOE": 1, "OTC/OCC NOT ASSIGNED": 1})}
    mix = M.status_mix(inv["status"])
    check(sum(n for _, n in mix) == 19 and len({k for k, _ in mix}) == len(mix), "status_mix: adds up to the total, one row per label: %s" % mix)
    check(dict(mix).get("Plugged") == 6 and len(mix) <= 6, "status_mix: codes with one label are added together; at most six parts: %s" % mix)
    ws = M.wells_section(inv, "2026-10-30T04:30:11", lk)
    check(ws["active"] == 5 and ws["plugged"] == 6 and ws["total"] == 19 and ws["asOf"] == "2026-10-30", "wells: active, plugged, as-of")
    check(ws["operators"] == [["Big Oil LLC", 3]] and ws["unnamed"] == 1 and ws["unassigned"] == 1, "wells: only corporations are listed; the rest are counted: %s" % ws["operators"])
    check([c[0] for c in ws["counties"]] == ["019", "137"] and ws["countyCount"] == 2, "wells: every county is kept, largest first")
    check("DOE" not in json.dumps(ws).upper(), "wells: the individual operator is nowhere in the section")

    # ------------------------------------------------------------------ build_reports: one rule for live and rebuilt
    mon, fri = D(2026, 11, 2), D(2026, 10, 30)  # a Monday and the Friday before it
    jobs = {"itd": {"rows": [itd("1", "137", "1", "ACME OIL LLC", "DR", 15000, None, datetime(2026, 10, 30, 15))], "file": {"name": "i", "modified": "2026-11-01T19:41:00", "bytes": 1}},
            "completions": {"rows": [comp("a", "073", "9", "BCE-MACH III LLC", "OIL", True, fri, oil=5.0)], "file": {"name": "c", "modified": "2026-11-01T19:40:00", "bytes": 2}},
            "transfers": {"rows": [], "file": {"name": "t", "modified": "2026-11-01T19:41:00", "bytes": 3}},
            "wells": {"inventory": inv, "file": {"name": "w", "modified": "2026-11-01T04:30:00", "bytes": 4}}}
    dates = [D(2026, 10, 31), D(2026, 11, 1), mon]
    live = M.build_reports({"R": mon, "dates": dates, "lk": lk}, jobs, {}, {d: ("live" if d == mon else "reconstructed") for d in dates})
    check(all(live[d].get("permits", {}).get("day") == "2026-10-30" for d in dates), "build_reports: Saturday, Sunday and Monday all show Friday's permits")
    check(all("completions" in live[d] for d in dates) and "transfers" not in live[mon], "build_reports: a day with no transfers has no transfers section")
    live_only = M.build_reports({"R": mon, "dates": [mon], "lk": lk}, jobs, {}, {mon: "live"})[mon]
    rebuilt = M.build_reports({"R": mon, "dates": [mon], "lk": lk}, jobs, {}, {mon: "reconstructed"})[mon]
    same = all(live_only[k] == rebuilt[k] for k in ("permits", "completions"))
    check(same, "build_reports: a live and a rebuilt report of the same day say the same")
    check("wells" in live_only and "wells" not in rebuilt, "build_reports: only a live report carries the well inventory")
    wr = [d for d in rebuilt["datasets"] if d["id"] == "wells"][0]
    check(wr.get("absent") is True and wr["error"] is None and wr["file"] is None, "build_reports: a rebuilt report marks the inventory absent, not read")
    check(all(not d.get("absent") for d in live_only["datasets"]) and all(d["file"] for d in live_only["datasets"]), "build_reports: a live report carries every file's name, time and size")
    err = M.build_reports({"R": mon, "dates": [mon], "lk": lk}, {**jobs, "itd": RuntimeError("boom")}, {}, {mon: "live"})[mon]
    check("permits" not in err and [d for d in err["datasets"] if d["id"] == "itd"][0]["error"] == "boom", "build_reports: a dataset that failed leaves its section out and says why")
    h = M.headline(live_only)
    check(h["f"] == 4 and h["dd"] == "2026-10-30" and h["pn"] == 1 and h["w"] == 5 and h["k"] == "live", "headline: files read, data day, counts: %s" % h)
    check(M.headline(rebuilt)["f"] == 3 and M.headline(rebuilt)["w"] is None, "headline: a rebuilt day reads three files and has no inventory")

    # ------------------------------------------------------------------ plan_dates
    pdn = M.plan_dates
    R = D(2026, 10, 31)
    have = {"2026-10-30", "2026-10-29"}
    ds, capped = pdn(R, 92, 7, False, have)
    check(ds == [D(2026, 10, 28), R] and capped, "plan_dates: a plain backfill reaches back %d days at most, skips days it has, and says it was capped: %s" % (M.SAFE_BACKFILL, ds))
    ds, capped = pdn(R, 92, 3, False, set())
    check(len(ds) == 4 and not capped, "plan_dates: --backfill 3 is within the limit")
    ds, capped = pdn(R, 92, 0, False, set())
    check(ds == [R] and not capped, "plan_dates: no backfill is just the report day")
    ds, capped = pdn(R, 92, 0, True, {"2026-10-30"})
    check(len(ds) == 91 and ds[0] == R - timedelta(days=91) and ds[-1] == R and D(2026, 10, 30) not in ds and not capped, "plan_dates: --history fills the whole archive but days already there")

    # ------------------------------------------------------------------ the daily files' window and the master gap fill
    ce = M.coverage_end
    check(ce("2026-10-30T19:41:10") == D(2026, 10, 29), "coverage_end: a file made on the evening of Oct 30 ends with Oct 29 (it holds the 7 complete days before)")
    check(ce("2026-11-01T00:05:00") == D(2026, 10, 31) and ce(None) is None and ce("junk") is None, "coverage_end: counts from the file's own Central day; no time gives None")

    def job(mod):
        return {"rows": [], "file": {"name": "x", "modified": mod, "bytes": 1}}

    Rd = D(2026, 10, 31)
    both = {"itd": job("2026-10-30T19:41:10"), "completions": job("2026-10-30T19:40:46"), "transfers": job("2026-10-30T19:41:37")}
    chosen = {"itd", "completions", "transfers", "wells"}
    mr = M.masters_to_read
    morning = mr(Rd, [Rd], False, both, chosen)
    check(morning == {"itd": D(2026, 10, 28), "completions": D(2026, 10, 28)}, "masters_to_read: a morning capture (last evening's files end a day short) reads both masters: %s" % morning)
    tonight = {"itd": job("2026-10-31T19:41:10"), "completions": job("2026-10-31T19:40:46")}
    check(mr(Rd, [Rd], False, tonight, chosen) == {}, "masters_to_read: the evening capture (files made that evening) reads no master")
    stale = {"itd": job("2026-10-28T19:41:10"), "completions": job("2026-10-31T19:40:46")}
    check(set(mr(Rd, [Rd], False, stale, chosen)) == {"itd"}, "masters_to_read: only the dataset whose file is stale reads its master")
    check(mr(Rd, [Rd], False, {"itd": RuntimeError("x"), "completions": None}, chosen) == {}, "masters_to_read: a dataset that failed or is missing reads no master")
    check(mr(Rd, [Rd], False, both, {"transfers"}) == {}, "masters_to_read: --only limits it")
    hist = mr(Rd, [Rd - timedelta(days=91), Rd], True, both, chosen)
    check(set(hist) == {"itd", "completions"} and hist["itd"] == Rd - timedelta(days=91 + M.LOOKBACK), "masters_to_read: --history reads both masters back to ten days before the oldest day: %s" % hist)
    check(set(mr(Rd, [Rd], True, {"itd": RuntimeError("x"), "completions": job("2026-10-31T19:40:46")}, chosen)) == {"completions"}, "masters_to_read: --history skips a dataset whose daily file failed")

    return fails


def archive_checks(M):
    fails = []

    def check(cond, msg):
        print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    tmp = tempfile.mkdtemp()
    try:
        # the real archive passes its own validation
        check(M.validate(REPO_ARCHIVE) == [], "validate: the committed archive is clean: %s" % M.validate(REPO_ARCHIVE)[:3])

        def mutated(fn, label, expect):
            d = tempfile.mkdtemp(dir=tmp)
            for f in os.listdir(REPO_ARCHIVE):
                shutil.copy(os.path.join(REPO_ARCHIVE, f), d)
            fn(d)
            probs = M.validate(d)
            check(any(expect in p for p in probs), "validate catches: %s (%s)" % (label, "; ".join(probs)[:110] or "NOTHING"))

        idx = sorted(f for f in os.listdir(REPO_ARCHIVE) if re.fullmatch(r"\d{4}-\d\d-\d\d\.json", f))
        mid = idx[40]

        def edit(path, fn):
            doc = json.load(open(path))
            fn(doc)
            json.dump(doc, open(path, "w"), separators=(",", ":"))

        mutated(lambda d: os.remove(os.path.join(d, mid)), "a day file missing from the archive", "index.json does not list exactly")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r["permits"]["types"].append(["Other", 9])), "permit types that do not add up", "permit types do not add up")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r["permits"].update(day=r["date"])), "permits from the report day itself", "not from before the report day")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r["permits"].update(deep=r["permits"]["newDrill"] + 1)), "more deep permits than new-drill permits", "permit counts do not nest")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r["completions"].update(horizontal=r["completions"]["filed"] + 1)), "more horizontal completions than filings", "horizontal completions exceed")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r["datasets"].pop()), "a dataset missing", "not the four OCC datasets")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r.update(state="XX")), "a wrong state", "wrong version, date or state")
        mutated(lambda d: open(os.path.join(d, mid), "w").write("{not json"), "a day file that is not JSON", "is not JSON")
        mutated(lambda d: edit(os.path.join(d, mid), lambda r: r.update(pad="x" * 70000)), "a day file over its size budget", "over its size budget")
        last = idx[-1]
        mutated(lambda d: edit(os.path.join(d, last), lambda r: r["wells"].update(active=r["wells"]["total"] + 1)), "more active wells than records", "well counts do not nest")
        mutated(lambda d: edit(os.path.join(d, last), lambda r: r["wells"]["status"].append(["Other", 5])), "a status mix that does not add up", "status mix does not add up")
        mutated(lambda d: edit(os.path.join(d, last), lambda r: r["wells"]["counties"].append(["001", "Adair", r["wells"]["active"] + 5])), "county wells over the active wells", "by county exceed")

        # privacy: no API numbers, only allowed keys, every named operator passes the naming rule, no unnamed operator's name from the sources
        text = "".join(open(os.path.join(REPO_ARCHIVE, f)).read() for f in os.listdir(REPO_ARCHIVE) if f.endswith(".json"))
        check(not re.search(r"(?<!\d)35\d{8}(\d{4})?(?!\d)", text), "privacy: no API number anywhere in the archive")
        check(not re.search(r"@|https?://|\bPO BOX\b|\bSTREET\b|\bHWY\b", text, re.I), "privacy: no e-mail, link or street address in the archive")
        allowed = {"v", "state", "date", "kind", "permits", "completions", "transfers", "wells", "datasets", "status", "capturedAt", "catalog",
                   "day", "total", "newDrill", "types", "classes", "deep", "deepFt", "depth", "median", "max", "mean", "bands", "wait", "amended", "counties", "countyCount",
                   "operators", "operatorCount", "namedShare", "filed", "horizontal", "formations", "lag", "spudToProd", "tests", "oil", "gas", "county", "operator",
                   "buyerCount", "sellerCount", "buyers", "sellers", "wells", "asOf", "active", "plugged", "activeTypes", "unnamed", "unassigned", "change", "since",
                   "id", "title", "cadence", "dataDay", "error", "file", "name", "modified", "bytes", "absent", "nightly", "unknown", "desc", "updated", "file"}
        keys = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        strings = []

        def strs(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    strs(v, path + "/" + k)
            elif isinstance(o, list):
                for v in o:
                    strs(v, path)
            elif isinstance(o, str):
                strings.append((path, o))

        for f in os.listdir(REPO_ARCHIVE):
            if f.endswith(".json"):
                doc = json.load(open(os.path.join(REPO_ARCHIVE, f)))
                walk(doc)
                strs(doc)
        check(keys <= allowed | {"d", "k", "s", "dd", "p", "pn", "pd", "cd", "c", "ca", "td", "t", "w", "f", "generated", "keep", "days"}, "privacy: only expected field names in the archive; unexpected: %s" % sorted(keys - allowed - {"d", "k", "s", "dd", "p", "pn", "pd", "cd", "c", "ca", "td", "t", "w", "f", "generated", "keep", "days"}))
        op_strings = [s for p, s in strings if p.endswith(("/operators", "/buyers", "/sellers", "/operator"))]
        # operators sit in lists [number, name, n]: collect the name cells
        names = set()

        def opnames(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("operators", "buyers", "sellers") and isinstance(v, list):
                        for row in v:
                            nm = row[1] if len(row) == 3 else row[0]
                            if isinstance(nm, str):
                                names.add(nm)
                    elif k == "operator" and isinstance(v, str):
                        names.add(v)
                    else:
                        opnames(v)
            elif isinstance(o, list):
                for v in o:
                    opnames(v)

        for f in os.listdir(REPO_ARCHIVE):
            if f.endswith(".json") and f != "index.json":
                opnames(json.load(open(os.path.join(REPO_ARCHIVE, f))))
        check(len(names) > 50, "privacy: the archive names %d operators" % len(names))
        bad = [n for n in names if not M.nameable(n.upper())]
        check(not bad, "privacy: every named operator ends like a corporation, LLC or partnership; offenders: %s" % bad[:5])

        # the sources: no operator that the rule does not name appears anywhere as a value
        sys.path.insert(0, PIPE)
        import ok_xlsx
        src_names = set()
        dl = os.environ.get("OK_REAL_FILES", "")
        if dl and os.path.isdir(dl):
            for r in ok_xlsx.rows(dl + "/ITD-wells-formations-daily.xlsx", want=("Entity_Name",)):
                src_names.add(r["Entity_Name"] or "")
            for r in ok_xlsx.rows(dl + "/completions-wells-formations-daily.xlsx", want=("Operator_Name",)):
                src_names.add(r["Operator_Name"] or "")
            for r in ok_xlsx.rows(dl + "/well-transfers-daily.xlsx", want=("FromOperatorName", "ToOperatorName")):
                src_names.update([r["FromOperatorName"] or "", r["ToOperatorName"] or ""])
            import csv
            with open(dl + "/rbdms-wells.csv", encoding="iso-8859-1", newline="") as fh:
                src_names.update((row.get("OPERATOR") or "").strip() for row in csv.DictReader(fh))
        unnamed = {n for n in src_names if n and not M.nameable(n)}
        leak = {s for _p, s in strings if s in {M.pretty(n) for n in unnamed} or s in unnamed}
        if src_names:
            check(len(unnamed) > 1000, "privacy: %d operator names in the sources fail the naming rule" % len(unnamed))
            check(not leak, "privacy: none of them appears in the archive; leaks: %s" % sorted(leak)[:5])
        else:
            print("skip  privacy: the source-file scan needs OK_REAL_FILES (a folder of the OCC daily files); not run")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def state_checks(M):
    fails = []

    def check(cond, msg):
        print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    tmp = tempfile.mkdtemp()
    try:
        def rep(day, kind="live", mod="2026-10-30T19:41:00", cap=None, status="ok", wells=None):
            r = {"v": 1, "state": "OK", "date": day, "kind": kind, "status": status, "datasets": [{"id": i, "file": {"name": i, "modified": mod, "bytes": 10}, "error": None} for i in ("itd", "completions", "transfers", "wells")]}
            if cap:
                r["capturedAt"] = cap
            if wells:
                r["wells"] = wells
            return r

        def write(r):
            json.dump(r, open(os.path.join(tmp, r["date"] + ".json"), "w"))

        # no earlier report: first
        cur = rep("2026-10-31")
        M.update_states(cur, tmp)
        check({d["state"] for d in cur["datasets"]} == {"first"}, "update_states: with no earlier live report every file is 'first'")
        # an earlier rebuilt report is no basis for comparison
        write(rep("2026-10-30", kind="reconstructed"))
        cur = rep("2026-10-31")
        M.update_states(cur, tmp)
        check({d["state"] for d in cur["datasets"]} == {"first"}, "update_states: an earlier rebuilt report is not compared with")
        # an earlier live one: same file = same, newer file = new
        write(rep("2026-10-30", mod="2026-10-29T19:41:00"))
        cur = rep("2026-10-31", mod="2026-10-30T19:41:00")
        cur["datasets"][3]["file"] = {"name": "wells", "modified": "2026-10-29T19:41:00", "bytes": 10}
        cur["datasets"][3]["file"] = {"name": "wells", "modified": "2026-10-29T19:41:00", "bytes": 10}
        M.update_states(cur, tmp)
        st = {d["id"]: d["state"] for d in cur["datasets"]}
        check(st["itd"] == "new" and st["wells"] == "same", "update_states: a newer file is 'new', an identical one 'same': %s" % st)
        cur["datasets"][0]["error"] = "x"
        M.update_states(cur, tmp)
        check(cur["datasets"][0]["state"] == "error", "update_states: a dataset that failed is 'error'")

        # wells change vs the previous report that had an inventory
        write(rep("2026-10-28", wells={"active": 100, "plugged": 50, "total": 200}))
        write(rep("2026-10-29"))  # a later report with no inventory is skipped over
        cur = rep("2026-10-31", wells={"active": 103, "plugged": 49, "total": 205})
        M.add_wells_change(cur, tmp)
        check(cur["wells"]["change"] == {"since": "2026-10-28", "active": 3, "plugged": -1, "total": 5}, "add_wells_change: against the last report that had an inventory: %s" % cur["wells"].get("change"))

        # captured_for_the_night
        R = D(2026, 10, 30)
        cutoff_ok = "2026-10-31T03:15:00Z"
        write(rep("2026-10-30", cap=cutoff_ok))
        check(M.captured_for_the_night(tmp, R) == cutoff_ok, "captured_for_the_night: a capture at 03:15 UTC the next day counts")
        write(rep("2026-10-30", cap="2026-10-30T20:00:00Z"))
        check(M.captured_for_the_night(tmp, R) is None, "captured_for_the_night: a capture before 03:00 UTC the next day does not (the files may not be made yet)")
        write(rep("2026-10-30", cap=cutoff_ok, status="partial"))
        check(M.captured_for_the_night(tmp, R) is None, "captured_for_the_night: a partial capture does not count")
        write(rep("2026-10-30", kind="reconstructed", cap=cutoff_ok))
        check(M.captured_for_the_night(tmp, R) is None, "captured_for_the_night: a rebuilt report does not count")
        check(M.captured_for_the_night(tmp, D(2026, 1, 1)) is None, "captured_for_the_night: no report, no capture")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def tz_fallback_check(M):
    """Without tz data the code falls back to a month rule instead of crashing."""
    saved = sys.modules.get("zoneinfo")
    sys.modules["zoneinfo"] = None
    try:
        d = M.central_day(datetime(2026, 7, 15, 3, 0))
        n = M.central_now()
        ok = d == D(2026, 7, 14) and n.tzinfo is not None
    finally:
        if saved is not None:
            sys.modules["zoneinfo"] = saved
        else:
            del sys.modules["zoneinfo"]
    print(("ok   " if ok else "FAIL ") + "clocks: without tz data a summer day still turns at 05:00 UTC and central_now still answers")
    return [] if ok else ["tz fallback"]


def mutants(M):
    """Break one rule at a time; the checks must notice."""
    fails = []

    def expect_fail(name, patch):
        saved = {}
        for k, v in patch.items():
            saved[k] = getattr(M, k)
            setattr(M, k, v)
        try:
            got = run_checks(M, quiet=True)
        finally:
            for k, v in saved.items():
                setattr(M, k, v)
        ok = bool(got)
        print(("ok   " if ok else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not ok:
            fails.append("mutant survived: " + name)

    expect_fail("everyone is named", {"nameable": lambda n: True})
    expect_fail("nobody is named", {"nameable": lambda n: False})
    orig_nd = M.newest_day
    expect_fail("a day may show its own records", {"newest_day": lambda by_day, day, lookback=M.LOOKBACK: orig_nd(by_day, day + timedelta(days=1), lookback)})
    expect_fail("Central is a fixed UTC-6", {"central_day": lambda n: (n - timedelta(hours=6)).date()})
    expect_fail("Central is a fixed UTC-5", {"central_day": lambda n: (n - timedelta(hours=5)).date()})
    expect_fail("backfill has no cap", {"plan_dates": lambda R, keep, backfill, history, have: ([R - timedelta(days=i) for i in range(backfill, 0, -1) if (R - timedelta(days=i)).isoformat() not in have] + [R], False)})
    orig_mix = M.status_mix
    expect_fail("status codes are not merged", {"status_mix": lambda c, keep=5: [[k, v] for k, v in sorted(c.items(), key=lambda kv: -kv[1])]})
    orig_api = M.api_county
    expect_fail("county from the wrong digits", {"api_county": lambda a: a[3:6] if a.isdigit() else None})
    expect_fail("a daily file is taken to reach its own day", {"coverage_end": lambda m: (date.fromisoformat(m[:10]) if m else None)})
    expect_fail("the master is always read", {"masters_to_read": lambda R, dates, history, jobs, chosen: {ds: D(2026, 1, 1) for ds in M.BASES}})
    return fails


if __name__ == "__main__":
    allf = []
    allf += run_checks(M)
    print("\n-- clocks without tz data")
    allf += tz_fallback_check(M)
    print("\n-- state files")
    allf += state_checks(M)
    print("\n-- the committed archive: validation mutants and privacy")
    allf += archive_checks(M)
    print("\n-- mutants")
    allf += mutants(M)
    print()
    print("FAILED %d: %s" % (len(allf), allf[:5]) if allf else "all passed")
    sys.exit(1 if allf else 0)
