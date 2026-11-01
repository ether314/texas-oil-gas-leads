"""Tests for site/pipeline/build_db.py: the whole site's data in one local SQLite file.

The database is built from the committed files, so what is checked is that nothing is lost or invented on the way: every data file is stored verbatim (size and SHA-256 match), every
relational table has exactly the rows its source file implies, a band a source cannot tell has no row (never a zero), measures stay apart, a build is repeatable, a failed build leaves the old
file alone, a file that is not SQLite is never overwritten, `--check` notices a tampered document, and the loader copes with the odd shapes in the real files (a day with no entry for an image
pack, a permit row shorter than the rest, a series with gaps, an optional file that does not exist yet).

Run: python3 -I tests/test_build_db.py"""
import glob
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
import build_db as B  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="build-db-")
out = os.path.join(tmp, "db", "oil.sqlite")
counts = B.build(out, DATA)
db = sqlite3.connect(out)
q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
J = lambda name: json.load(open(os.path.join(DATA, name + ".json"), encoding="utf-8"))  # noqa: E731

# ------------------------------------------------------------------------------------------------ the committed data, loaded
files = sorted(glob.glob(os.path.join(DATA, "**", "*.json"), recursive=True))
check(counts["documents"] == len(files) and one("SELECT COUNT(*) FROM documents") == len(files), "every data file is stored (%d)" % len(files))
bad = [p for p, n, sha, txt in q("SELECT path, bytes, sha256, json FROM documents") if hashlib.sha256(open(os.path.join(DATA, p), "rb").read()).hexdigest() != sha or txt.encode() != open(os.path.join(DATA, p), "rb").read()]
check(not bad, "each document is verbatim: size, SHA-256 and text equal the file's (%s)" % bad[:2])
check(B.check(out) == [] and one("PRAGMA integrity_check") == "ok", "the built file passes its own check and SQLite's integrity check")

nat = J("national")
check(one("SELECT COUNT(*) FROM jurisdictions") == len(nat["states"]) + len(nat["gaps"]) and one("SELECT COUNT(*) FROM jurisdictions WHERE status = 'data'") == len(nat["states"]), "every jurisdiction is a row, with data or as a gap")
check(one("SELECT COUNT(*) FROM jurisdictions WHERE status = 'gap' AND measure IS NOT NULL") == 0 and one("SELECT COUNT(*) FROM jurisdictions WHERE status = 'gap' AND gap_reason IS NULL") == 0, "a gap has no measure and always a reason: not read yet is never a figure")
expect = sum(1 for s in nat["states"] for v in s["bands"].values() if v is not None for x in v if x is not None)
check(one("SELECT COUNT(*) FROM national_months") == expect, "national_months holds one row per state, month and band that exists (%d)" % expect)
nullband = [(s["id"], b) for s in nat["states"] for b, v in s["bands"].items() if v is None]
check(nullband and all(one("SELECT COUNT(*) FROM national_months WHERE jurisdiction = ? AND band = ?", sid, b) == 0 for sid, b in nullband), "a band a source cannot tell has no rows, never zeros (%d such bands)" % len(nullband))
tx_new = sum(v for v in next(s for s in nat["states"] if s["id"] == "TX")["bands"]["new"] if v is not None)
check(one("SELECT SUM(count) FROM national_months WHERE jurisdiction = 'TX' AND band = 'new'") == tx_new, "Texas's new wells add up to the national file's")
meas = dict(q("SELECT id, measure FROM jurisdictions WHERE status = 'data'"))
check(meas["TX"] == "permits" and meas["OK"] == "permits" and meas["NM"] == "spuds" and meas["FO"] == "spuds", "measures are kept apart: Texas and Oklahoma permits, New Mexico and the offshore spuds")
lt = dict((r[0], r[4]) for r in q("SELECT * FROM v_latest_12_months"))
check(lt["TX"] == next(s for s in nat["states"] if s["id"] == "TX")["p12"] and lt["NM"] == next(s for s in nat["states"] if s["id"] == "NM")["p12"], "the 12-month view agrees with national.json")
check(one("SELECT COUNT(*) FROM national_operators") == sum(len(s["operators"]) for s in nat["states"]) and one("SELECT COUNT(*) FROM national_counties") == sum(len(s["counties"]) for s in nat["states"]), "top operators and places are loaded")

series_files = sorted(glob.glob(os.path.join(DATA, "series-*.json")))
expect = 0
for p in series_files:
    d = json.load(open(p))
    axis = "months" if "months" in d else "weeks" if "weeks" in d else None
    if axis:
        expect += sum(1 for k, v in d.items() if k != axis and isinstance(v, list) and len(v) == len(d[axis]) and all(x is None or isinstance(x, (int, float)) and not isinstance(x, bool) for x in v) for x in v if x is not None)
check(one("SELECT COUNT(*) FROM series") == expect and one("SELECT COUNT(DISTINCT file) FROM series") >= 10, "every numeric series is loaded, one row per point (%d)" % expect)
check(one("SELECT value FROM series WHERE file = 'series-markets' AND key = 'wti' ORDER BY t DESC LIMIT 1") == J("series-markets")["wti"][-1], "a series' newest value is the file's")

cp = J("county-permits")
check(one("SELECT COUNT(*) FROM county_permits WHERE state = 'TX'") == len(cp["counties"]) and one("SELECT p12 FROM county_permits WHERE state = 'TX' AND county = '329'") == cp["counties"]["329"]["p12"], "Texas's counties are loaded with the file's figures")
check(one("SELECT county_name FROM county_permits WHERE state = 'TX' AND county = '329'") == "Midland", "a county has its name from the geometry file")
check(one("SELECT COUNT(*) FROM county_permit_months") == sum(1 for st, (cf, _g) in B.STATE_FILES.items() for c in J(cf)["counties"].values() for v in c["m"] if v is not None), "every county's monthly counts are loaded")

nrows = sum(len(J(f)["rows"]) for f in ("operators", "operators-ok", "operators-nm", "operators-fo"))
check(one("SELECT COUNT(*) FROM operators") == nrows, "every state's operator table is loaded (%d rows)" % nrows)
check(one("SELECT prev12 FROM operators WHERE state = 'TX' AND prev12 IS NOT NULL LIMIT 1") is not None, "Texas's operators are joined with their extras")
check(one("SELECT COUNT(*) FROM operators WHERE state = 'TX' AND name IS NULL") == 0, "no operator without a name")
npts = sum(len(J(f)["pts"]) for f in ("permits", "permits-ok", "permits-nm", "permits-fo"))
check(one("SELECT COUNT(*) FROM permit_points") == npts, "every permit point is loaded (%d)" % npts)
check(one("SELECT COUNT(*) FROM permit_points WHERE lat NOT BETWEEN 24 AND 50 OR lon NOT BETWEEN -110 AND -80 OR day IS NULL") == 0, "points decode to places between New Mexico and the Gulf, and to real days")
check(one("SELECT COUNT(*) FROM companies") == len(J("companies")["rows"]), "the company pool is loaded")

if os.path.exists(os.path.join(DATA, "permit-fields.json")):
    pf = J("permit-fields")
    check(one("SELECT COUNT(*) FROM metrics") == len(pf["metrics"]) and one("SELECT COUNT(*) FROM field_states") == len(pf["states"]) and one("SELECT COUNT(*) FROM field_cells") == len(pf["metrics"]) * len(pf["states"]),
          "the matrix is loaded: every agency answers every metric (%d cells)" % one("SELECT COUNT(*) FROM field_cells"))
    check(one("SELECT COUNT(*) FROM field_cells WHERE status NOT IN ('data','query','form','none','unknown')") == 0 and one("SELECT COUNT(*) FROM field_cells WHERE status = 'data' AND evidence NOT IN ('file','doc')") == 0,
          "every cell has one of the five statuses, and 'data' always has a file or the documentation behind it")
    check(one("SELECT COUNT(*) FROM field_sources") == sum(len(s["sources"]) for s in pf["states"].values()), "every researched source is a row")
days = sum(len(glob.glob(os.path.join(DATA, d, "????-??-??.json"))) for d in ("daily", "daily-ok", "daily-nm"))
check(one("SELECT COUNT(*) FROM daily_reports") == days, "every Daily report is a row (%d)" % days)
rows = 0
for p in glob.glob(os.path.join(DATA, "daily", "????-??-??.json")):
    rows += len((json.load(open(p)).get("permits") or {}).get("rows") or [])
check(one("SELECT COUNT(*) FROM daily_permits WHERE state = 'TX'") == rows, "every Texas permit row of the Daily reports is loaded (%d)" % rows)
check(one("SELECT COUNT(*) FROM daily_permits WHERE state != 'TX'") == 0, "other states publish no permit rows in their Daily reports, so none are invented")
packs = sum(1 for p in glob.glob(os.path.join(DATA, "daily", "????-??-??.json")) for v in (json.load(open(p)).get("images") or {}).values() if isinstance(v, dict))
check(one("SELECT COUNT(*) FROM tx_image_packs") == packs, "every Texas image pack of every day is loaded (%d)" % packs)

# ------------------------------------------------------------------------------------------------ the build itself
out2 = os.path.join(tmp, "again.sqlite")
B.build(out2, DATA)
db2 = sqlite3.connect(out2)
tables = [r[0] for r in q("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'meta' ORDER BY name")]
same = all(db.execute('SELECT * FROM "%s" ORDER BY 1,2,3' % t).fetchall() == db2.execute('SELECT * FROM "%s" ORDER BY 1,2,3' % t).fetchall() for t in tables if t != "permit_points")
check(same, "a second build holds exactly the same rows (it is repeatable)")
db2.close()

# a failed build leaves the old file alone, a non-SQLite file is never overwritten
before = hashlib.sha256(open(out, "rb").read()).hexdigest()
broken = os.path.join(tmp, "broken-data")
shutil.copytree(DATA, broken)
open(os.path.join(broken, "series-markets.json"), "w").write("{not json")
try:
    B.build(out, broken)
    check(False, "a build from a damaged file fails")
except ValueError:
    check(True, "a build from a damaged file fails")
check(hashlib.sha256(open(out, "rb").read()).hexdigest() == before and not os.path.exists(out + ".building"), "a failed build leaves the earlier file untouched and no temporary file behind")
precious = os.path.join(tmp, "notes.sqlite")
open(precious, "w").write("my notes, not a database")
try:
    B.build(precious, DATA)
    check(False, "a file that is not SQLite is refused")
except ValueError:
    check(open(precious).read() == "my notes, not a database", "a file that is not SQLite is never overwritten")

# --check notices a tampered document
tampered = os.path.join(tmp, "tampered.sqlite")
shutil.copy(out, tampered)
t = sqlite3.connect(tampered)
t.execute("UPDATE documents SET json = replace(json, '2019', '2018') WHERE path = 'series-permits.json'")
t.commit()
t.close()
check(B.check(tampered) != [] and B.check(os.path.join(tmp, "none.sqlite")) != [], "--check notices a document that no longer matches its hash, and a file that is not there")
t = sqlite3.connect(tampered)
t.execute("DELETE FROM national_months WHERE jurisdiction = 'TX' AND month = '2026-09'")
t.commit()
t.close()
check(any("national_months" in x for x in B.check(tampered)), "--check notices a table that no longer matches national.json")

# ------------------------------------------------------------------------------------------------ odd shapes
mini = os.path.join(tmp, "mini-data")
os.makedirs(os.path.join(mini, "daily"))
json.dump({"v": 1, "state": "TX", "date": "2026-10-29", "kind": "live", "status": "ok", "permits": {"total": 2, "newDrill": 1, "rows": [["0919749", "301", "08", "020528", None, 12000, "H"], ["0919750", "301", "08", "1", "ACME LLC", 9000, "V", "4230100000", 31.0, -103.0, ["W1.pdf"]]]},
          "images": {"w1images": None, "dirsurveys": {"day": "2026-10-28", "bytes": 5, "modified": "2026-10-29T10:00:00", "empty": False, "docs": None}}}, open(os.path.join(mini, "daily", "2026-10-29.json"), "w"))
json.dump({"months": ["2026-01", "2026-02", "2026-03"], "wti": [70.0, None, 72.5], "label": ["a", "b", "c"]}, open(os.path.join(mini, "series-markets.json"), "w"))
os.makedirs(os.path.join(mini, "daily-cm"))
json.dump({"v": 1, "day": "2026-10-29", "packDay": "2026-10-28", "repo": "o/r", "per": 2, "parts": 2, "kinds": ["W-2 form", "Well log"], "docs": 3, "previews": 2, "builtAt": "2026-10-30T03:30Z",
           "packets": [["08", "111", [[0, 0, 1], [1, 1, 0]]], ["7C", "222", [[1, 0, 1]]]]}, open(os.path.join(mini, "daily-cm", "2026-10-29.json"), "w"))
json.dump({"v": 1, "days": ["2026-10-29"]}, open(os.path.join(mini, "daily-cm", "index.json"), "w"))
mdb = os.path.join(tmp, "mini.sqlite")
B.build(mdb, mini)
m = sqlite3.connect(mdb)
check(m.execute("SELECT COUNT(*) FROM daily_permits").fetchone()[0] == 2 and m.execute("SELECT permit, documents FROM daily_permits WHERE operator IS NULL").fetchone()[1] is None, "a permit row shorter than the rest is loaded with blanks, not dropped")
check(m.execute("SELECT COUNT(*) FROM tx_image_packs").fetchone()[0] == 1, "a pack with no entry for a day is skipped, one with no documents is kept")
check(m.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 2 and m.execute("SELECT COUNT(*) FROM jurisdictions").fetchone()[0] == 0, "a series with a gap loads only its real points; missing optional files load nothing")
rows = m.execute("SELECT district, tracking, seq, kind, folder, has_preview, release_tag, file FROM tx_completion_docs ORDER BY district, tracking, seq").fetchall()
check(rows == [("08", "111", 1, "W-2 form", "plain", 1, "daily-2026-10-29-cm1", "cm_08_111_1.jpg"), ("08", "111", 2, "Well log", "submitted", 0, None, None), ("7C", "222", 1, "Well log", "plain", 1, "daily-2026-10-29-cm2", "cm_7C_222_1.jpg")],
      "every completion document is a row, with its release by its place in the day's list and no file name where it has no preview: %s" % rows)
check(m.execute("SELECT COUNT(*) FROM documents WHERE path LIKE 'daily-cm/%'").fetchone()[0] == 2 and B.check(mdb) == [], "the completion files are documents too, and --check counts the Daily reports without them: %s" % B.check(mdb))
check(one("SELECT COUNT(*) FROM tx_completion_docs") == sum(len(pk[2]) for f in glob.glob(os.path.join(DATA, "daily-cm", "????-??-??.json")) for pk in json.load(open(f))["packets"]), "every document of the committed completion files is a row (none until the first nightly step has run)")
m.close()

# ------------------------------------------------------------------------------------------------ mutants
spec = importlib.util.spec_from_file_location("m_bdb", os.path.join(PIPE, "build_db.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
real_jload = mod.jload


def zeroed(p):
    d = real_jload(p)
    if isinstance(d, dict) and "states" in d and "gaps" in d:
        for st in d["states"]:
            st["bands"] = {b: ([0] * len(d["months"]) if v is None else v) for b, v in st["bands"].items()}
    return d


mod.jload = zeroed
mut = os.path.join(tmp, "mut.sqlite")
mod.build(mut, DATA)
mm = sqlite3.connect(mut)
check(mm.execute("SELECT COUNT(*) FROM national_months").fetchone()[0] != one("SELECT COUNT(*) FROM national_months"), "mutant 'a band a source cannot tell becomes zeros' is noticed")
mm.close()
db.close()
shutil.rmtree(tmp, ignore_errors=True)

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
