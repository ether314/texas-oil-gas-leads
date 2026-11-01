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

# ------------------------------------------------------------------------------------------------ the well-image archive
wi = J("wells/index")
n_w = sum(len(json.load(open(f))["wells"]) for f in glob.glob(os.path.join(DATA, "wells", "county", "*.json")))
check(one("SELECT COUNT(*) FROM wells") == n_w == wi["totals"]["wells"] and one("SELECT COUNT(*) FROM well_documents") == wi["totals"]["docs"] and one("SELECT COUNT(*) FROM well_packs") == len(wi["units"]),
      "the committed well archive is loaded: %d wells, %d documents, %d packs" % (n_w, wi["totals"]["docs"], len(wi["units"])))
fx = json.load(open(os.path.join(HERE, "fixtures", "wells.json")))
wd = os.path.join(tmp, "wells-data")
os.makedirs(os.path.join(wd, "wells", "county"))
json.dump(fx["index"], open(os.path.join(wd, "wells", "index.json"), "w"))
for fips, c in fx["counties"].items():
    json.dump(c, open(os.path.join(wd, "wells", "county", fips + ".json"), "w"))
wdb = os.path.join(tmp, "wells.sqlite")
B.build(wdb, wd)
w = sqlite3.connect(wdb)
wq = lambda sql, *a: w.execute(sql, a).fetchall()  # noqa: E731
check(wq("SELECT COUNT(*) FROM wells")[0][0] == 3 and wq("SELECT COUNT(*) FROM well_documents")[0][0] == 8 and wq("SELECT COUNT(*) FROM well_packs")[0][0] == 3 and B.check(wdb) == [], "the fixture archive loads as 3 wells, 8 documents and 3 packs, and passes the check")
check(wq("SELECT documents FROM wells WHERE api = '28337830'")[0][0] == 6 and wq("SELECT COUNT(*) FROM well_documents WHERE api = '28337830'")[0][0] == 6, "a well's document count is the documents tied to it")
check(wq("SELECT operator, operator_num FROM wells WHERE api = '28300001'")[0] == (None, "999999") and wq("SELECT operator FROM wells WHERE api = '28337830'")[0][0] == "VERDUN OIL EF II LLC", "an operator that may not be named has its number and no name")
row = wq("SELECT stage, kind, pages, ext, release_tag, has_preview, url, preview_url FROM well_documents WHERE file = '28337830_c3'")[0]
check(row == ("completion", "W-2 form", 3, "pdf", "wells-2026-10-29-ci-01", 1, "https://github.com/o/r/releases/download/wells-2026-10-29-ci-01/28337830_c3.pdf", "https://github.com/o/r/releases/download/wells-2026-10-29-ci-01/28337830_c3.jpg"), "a document carries its stage, kind, pages, release and the addresses of the file and its picture")
none = wq("SELECT pages, has_preview, preview_url FROM well_documents WHERE file = '28337830_c2'")[0]
check(none == (None, 0, None), "a document whose pages could not be counted and that has no picture says so with nulls, never 0 pages or a dead address")
check(wq("SELECT COUNT(*) FROM well_documents d JOIN wells w ON w.api = d.api")[0][0] == 8, "every document joins to its well")
w.close()
# a tampered county file is noticed
tampered = os.path.join(tmp, "tampered.sqlite")
B.build(tampered, wd)
tdb = sqlite3.connect(tampered)
tdb.execute("DELETE FROM well_documents WHERE file = '28337830_c1'")
tdb.commit()
check(any("well_documents" in x for x in B.check(tampered)), "a missing well document is noticed by --check")
tdb.close()

# ------------------------------------------------------------------------------------------------ odd shapes
mini = os.path.join(tmp, "mini-data")
os.makedirs(os.path.join(mini, "daily"))
json.dump({"v": 1, "state": "TX", "date": "2026-10-29", "kind": "live", "status": "ok", "permits": {"total": 2, "newDrill": 1, "rows": [["0919749", "301", "08", "020528", None, 12000, "H"], ["0919750", "301", "08", "1", "ACME LLC", 9000, "V", "4230100000", 31.0, -103.0, ["W1.pdf"]]]},
          "images": {"w1images": None, "dirsurveys": {"day": "2026-10-28", "bytes": 5, "modified": "2026-10-29T10:00:00", "empty": False, "docs": None}}}, open(os.path.join(mini, "daily", "2026-10-29.json"), "w"))
json.dump({"months": ["2026-01", "2026-02", "2026-03"], "wti": [70.0, None, 72.5], "label": ["a", "b", "c"]}, open(os.path.join(mini, "series-markets.json"), "w"))
mdb = os.path.join(tmp, "mini.sqlite")
B.build(mdb, mini)
m = sqlite3.connect(mdb)
check(m.execute("SELECT COUNT(*) FROM daily_permits").fetchone()[0] == 2 and m.execute("SELECT permit, documents FROM daily_permits WHERE operator IS NULL").fetchone()[1] is None, "a permit row shorter than the rest is loaded with blanks, not dropped")
check(m.execute("SELECT COUNT(*) FROM tx_image_packs").fetchone()[0] == 1, "a pack with no entry for a day is skipped, one with no documents is kept")
check(m.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 2 and m.execute("SELECT COUNT(*) FROM jurisdictions").fetchone()[0] == 0, "a series with a gap loads only its real points; missing optional files load nothing")
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
