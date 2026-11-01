"""Tests for site/pipeline/ff_db.py and the --fracfocus options of build_db.py: the whole FracFocus registry in the owner's local SQLite database.

The fixtures are an invented FracFocusCSV.zip built the way the real one is (DisclosureList_1.csv, WaterSource_1.csv and two FracFocusRegistry_N.csv ingredient files, the registry's own
column names, dates like "5/1/1955 12:00:00 AM", 14-digit API numbers, "True"/"False" flags). They pin: every disclosure is kept, the ones with a typing error in their date or no location
included (nothing is dropped, only marked); `is_first` is the site's own definition of a new well (the first disclosure of a well, the well being the first ten digits of its API number, by the
job's date among the real dates, the file's order on a tie), checked against d13_newwells.Wells on the same rows; the registry's text is kept beside the parsed dates; water sources and
ingredients load whole (a container row too), and the ingredients only when asked; a cut-short list or a changed layout is refused; the tables are never written anywhere that could be published
(under site/, or to a name git would track), `.gitignore` covers the database, and a database built without --fracfocus holds none of it; `--check` notices a tampered count; the download
needs a new folder, resumes once, and treats a 403 as an answer; and the committed site data still holds no API number.

Run: python3 -I tests/test_build_db_fracfocus.py"""
import csv
import http.server
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import zipfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import build_db as B  # noqa: E402
import d11_nat_common as C  # noqa: E402
import d13_newwells as W  # noqa: E402
import ff_db as F  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
F.MIN_ROWS = 1  # the real list has 252,000 rows; the test lists have a dozen


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, kind=Exception):
    try:
        fn()
    except kind:
        return True
    return False


HEAD = ["DisclosureId", "JobStartDate", "JobEndDate", "APINumber", "StateName", "CountyName", "OperatorName", "WellName", "Latitude", "Longitude", "Projection", "TVD", "TotalBaseWaterVolume",
        "TotalBaseNonWaterVolume", "FFVersion", "FederalWell", "IndianWell"]
REG_HEAD = HEAD + ["PurposeId", "TradeName", "Supplier", "Purpose", "IngredientsId", "CASNumber", "IngredientName", "IngredientCommonName", "PercentHighAdditive", "PercentHFJob", "IngredientComment",
                   "IngredientMSDS", "MassIngredient", "ClaimantCompany"]
WATER_HEAD = ["WaterSourceId", "DisclosureId", "APINumber", "StateName", "CountyName", "OperatorName", "WellName", "Description", "Percent"]
N = iter(range(1, 10 ** 6))


def d(id_, start, api, state="Texas", op="Alpha Energy LLC", end=None, lat="31.95", lon="-102.0", well="LEASE ALPHA 7H", county="Martin", tvd="9500", water="21000000", fed="False", ind="False", datum="NAD83"):
    return {"DisclosureId": id_, "JobStartDate": start, "JobEndDate": end if end is not None else start, "APINumber": api, "StateName": state, "CountyName": county, "OperatorName": op, "WellName": well,
            "Latitude": lat, "Longitude": lon, "Projection": datum, "TVD": tvd, "TotalBaseWaterVolume": water, "TotalBaseNonWaterVolume": "", "FFVersion": "3", "FederalWell": fed, "IndianWell": ind}


ROWS = [
    d("d01", "3/10/2025 12:00:00 AM", "42317000010000"),                                     # a well's first job
    d("d02", "9/2/2025 12:00:00 AM", "42317000010000"),                                      # fractured again six months later: not first
    d("d03", "5/5/2025 12:00:00 AM", "42317000010101", well="LEASE ALPHA 7H ST"),             # a sidetrack: the same first ten digits, a later date
    d("d04", "7/7/2025 12:00:00 AM", "42317000020000", state="New Mexico", fed="True", ind="True"),
    d("d05", "2/2/2025 12:00:00 AM", "42888000010000", op="Clay Hamilton"),                  # a person: kept here, never on the site
    d("d06", "1/1/2025 12:00:00 AM", "42888000010000", op="Clay Hamilton"),                  # the earlier job arrives second: it is the first
    d("d07", "4/4/2025 12:00:00 AM", "42777000010000"), d("d08", "4/4/2025 12:00:00 AM", "42777000010000"),  # a tie: the file's first wins
    d("d09", "12/31/3012 12:00:00 AM", "42555000010000"),                                    # a typing error in the year
    d("d10", "5/1/1955 12:00:00 AM", "42555000020000"),                                      # before the registry began
    d("d11", "not a date", "42555000030000", lat="", lon=""),                                # no date, no point
    d("d12", "6/6/2025 12:00:00 AM", "123", state="Texas"),                                  # an API number of three digits: no well
    d("d13", "8/8/2025 12:00:00 AM", "60111000010000", state="Atlantis"),                    # a state the report does not know
    d("d14", "2/14/2026 12:00:00 AM", "35001000010000", state="Oklahoma", lat="35.5", lon="-98.0", tvd="", water=""),
    d("d15", "11/20/2026 12:00:00 AM", "42317000090000"),                                    # a job in the future
]
WATER = [["w1", "d01", "42317000010000", "Texas", "Martin", "Alpha Energy LLC", "LEASE ALPHA 7H", "Produced Water", "76.10"], ["w2", "d01", "42317000010000", "Texas", "Martin", "Alpha Energy LLC", "LEASE ALPHA 7H", "Surface Water", "23.90"],
         ["w3", "d04", "42317000020000", "New Mexico", "Eddy", "Alpha Energy LLC", "LEASE B", "Groundwater, < 1000TDS", ""]]
INGREDIENTS = [("d01", "p1", "Ingredient Container", "Ingredient Container", "Ingredient Container Purpose", "", "", "", "", "", "", "", "", "", ""),
               ("d01", "p2", "FR-9", "C&J Well Services", "Friction Reducer", "i1", "64742-47-8", "Distillates, petroleum", "Petroleum distillate", "30", "0.0153", "", "True", "412.5", ""),
               ("d01", "p2", "FR-9", "C&J Well Services", "Friction Reducer", "i2", "7732-18-5", "Water", "Water", "", "85.2", "", "False", "", ""),
               ("d04", "p3", "Sand", "Acme Proppants", "Proppant", "i3", "14808-60-7", "Crystalline silica", "Quartz", "100", "11.3", "a comment", "True", "9000000", "Secret Co")]


def csv_text(head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(head)
    for r in rows:
        w.writerow(r)
    return "﻿" + buf.getvalue()


def make_zip(rows=ROWS, water=WATER, chem=INGREDIENTS):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("DisclosureList_1.csv", csv_text(HEAD, [[r[c] for c in HEAD] for r in rows]))
        z.writestr("WaterSource_1.csv", csv_text(WATER_HEAD, water))
        by = {r["DisclosureId"]: r for r in rows}
        half = len(chem) // 2
        for k, part in ((1, chem[:half]), (2, chem[half:])):
            z.writestr("FracFocusRegistry_%d.csv" % k, csv_text(REG_HEAD, [[by[c[0]][h] for h in HEAD] + list(c[1:]) for c in part]))
        z.writestr("readme csv.txt", "dictionary")
    return out.getvalue()


tmp = tempfile.mkdtemp(prefix="ff-db-")
zpath = os.path.join(tmp, "FracFocusCSV.zip")
open(zpath, "wb").write(make_zip())


def fresh(chemicals=False, zip_path=zpath, name="t.sqlite"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
    counts = F.load(db, zip_path, chemicals, today=TODAY)
    db.commit()
    return db, counts


db, counts = fresh()
q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731

# ------------------------------------------------------------------------------------------------ every disclosure is kept
check(counts == {"ff_disclosures": len(ROWS), "ff_water_sources": 3} and one("SELECT COUNT(*) FROM ff_disclosures") == len(ROWS), "every disclosure is loaded, the ones with a typing error and no location included (%d)" % len(ROWS))
r = {x[0]: x for x in q("SELECT disclosure_id, job_start, job_start_text, job_end, api, api10, state, state_code, county, operator, well_name, latitude, longitude, datum, tvd_ft, water_gal, federal, tribal, date_ok, is_first FROM ff_disclosures")}
check(r["d01"][1:3] == ("2025-03-10", "3/10/2025 12:00:00 AM") and r["d01"][3] == "2025-03-10" and r["d01"][4] == "42317000010000" and r["d01"][5] == "4231700001", "a job date is parsed to ISO with the registry's own text beside it, and the API number gives its well (its first ten digits)")
check(r["d01"][6:10] == ("Texas", "TX", "Martin", "Alpha Energy LLC") and r["d01"][10] == "LEASE ALPHA 7H" and r["d01"][11:14] == (31.95, -102.0, "NAD83") and r["d01"][14:16] == (9500.0, 21000000.0), "state (name and code), county, operator, well name, position as filed, datum, depth and water")
check(isinstance(r["d01"][11], float) and r["d14"][14] is None and r["d14"][15] is None and r["d11"][11] is None and r["d11"][12] is None, "a missing number is NULL, not zero or an empty string")
check(r["d04"][16:18] == (1, 1) and r["d01"][16:18] == (0, 0), "federal and tribal land are 0 or 1")
check(r["d11"][1] is None and r["d11"][2] == "not a date" and r["d11"][18] == 0 and r["d09"][18] == 0 and r["d10"][18] == 0 and r["d15"][18] == 0 and r["d01"][18] == 1, "a date that is not a date, a year 3012, 1955 and a job in the future are marked not OK, and their text is kept")
check(r["d12"][4] == "123" and r["d12"][5] is None and r["d12"][19] == 0, "an API number of three digits gives no well and is never a first disclosure")
check(r["d13"][6:8] == ("Atlantis", None) and r["d05"][9] == "Clay Hamilton", "a state the report does not know has no code; an operator that is a person is kept as filed (this file is for the owner's machine only)")

# ------------------------------------------------------------------------------------------------ a well is counted once, on its first job
firsts = {x[0] for x in q("SELECT disclosure_id FROM ff_disclosures WHERE is_first = 1")}
check(firsts == {"d01", "d04", "d06", "d07", "d13", "d14"}, "the first disclosures are the first job of each well (six wells; d01 over its re-frac and its sidetrack, d06 the earlier job that came second, d07 the first of a tie): %s" % sorted(firsts))
check("d02" not in firsts and "d03" not in firsts and "d05" not in firsts and "d08" not in firsts, "a second job, a sidetrack's, the later of two and the second of a tie are not first")
check("d09" not in firsts and "d10" not in firsts and "d11" not in firsts and "d15" not in firsts, "a disclosure with no real date is never a first disclosure")
# the same answer as the producer of the site's map
wells = W.Wells(W.load_outlines(), TODAY)
for row in ROWS:
    wells.add(row)
mine = {(x[0], x[1]) for x in q("SELECT api10, job_start FROM ff_disclosures WHERE is_first = 1 AND state_code IS NOT NULL")}
theirs = {(a, v[0].isoformat()) for a, v in wells.first.items()}
check(mine == theirs and len(mine) == 5, "for the states the report knows the first disclosures are the very wells and days d13_newwells.py counts (%d of %d; it leaves out a state it does not know, the registry has none)" % (len(mine), len(theirs)))
check(one("SELECT COUNT(*) FROM v_ff_new_wells") == len(firsts) and sum(n for _, _, n in q("SELECT * FROM v_ff_new_wells_by_month")) == len(firsts)
      and q("SELECT wells FROM v_ff_new_wells_by_month WHERE state_code = 'TX' AND month = '2025-01'") == [(1,)], "the views give the new wells, and by state and month")

# ------------------------------------------------------------------------------------------------ water sources and ingredients
check(q("SELECT description, percent FROM ff_water_sources ORDER BY water_source_id") == [("Produced Water", 76.1), ("Surface Water", 23.9), ("Groundwater, < 1000TDS", None)], "every water source is loaded, an empty percent as NULL")
check(not q("SELECT 1 FROM sqlite_master WHERE name = 'ff_ingredients'") and "fracfocus_ingredients" in dict(q("SELECT key, value FROM meta")) and dict(q("SELECT key, value FROM meta"))["fracfocus_ingredients"] == "not loaded",
      "the ingredients are not loaded unless asked for, and the meta says so")
check(raises(lambda: F.load(sqlite3.connect(":memory:"), None, True), ValueError), "the ingredients without a local zip are refused: they are 3.5 GB of CSV, not a range request")
dbc, cc = fresh(chemicals=True, name="c.sqlite")
rows_c = dbc.execute("SELECT disclosure_id, purpose, trade_name, supplier, cas_number, ingredient_name, percent_high_additive, percent_hf_job, msds, mass_ingredient, claimant_company FROM ff_ingredients ORDER BY rowid").fetchall()
check(cc["ff_ingredients"] == len(INGREDIENTS) == len(rows_c) and rows_c[0][1] == "Ingredient Container Purpose" and rows_c[1][4:8] == ("64742-47-8", "Distillates, petroleum", 30.0, 0.0153) and rows_c[1][8] == 1 and rows_c[2][8] == 0 and rows_c[3][10] == "Secret Co",
      "with --chemicals every ingredient row of every registry file is loaded (a container row too), numbers as numbers, flags as 0 or 1")
check(dbc.execute("SELECT COUNT(*) FROM ff_ingredients WHERE disclosure_id NOT IN (SELECT disclosure_id FROM ff_disclosures)").fetchone()[0] == 0 and F.check(dbc) == [], "every ingredient belongs to a disclosure, and the tables pass their own check")

# ------------------------------------------------------------------------------------------------ what is refused
F.MIN_ROWS = 100000
check(raises(lambda: F.load(sqlite3.connect(":memory:"), zpath, False, today=TODAY), ValueError), "a list far shorter than the registry is refused as cut short")
F.MIN_ROWS = 1
bad = os.path.join(tmp, "bad.zip")
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("DisclosureList_1.csv", "DisclosureId,JobStartDate\r\nx,1/1/2025\r\n")
check(raises(lambda: F.load(sqlite3.connect(":memory:"), bad, False), ValueError), "a list without the registry's columns is refused (a changed layout must not load as nothing)")
none = os.path.join(tmp, "none.zip")
with zipfile.ZipFile(none, "w") as z:
    z.writestr("other.csv", "a\r\n")
check(raises(lambda: F.load(sqlite3.connect(":memory:"), none, False), ValueError), "a zip with no disclosure list is refused")

# ------------------------------------------------------------------------------------------------ never where it could be published
ok_paths = [os.path.join(REPO, "db", "oil-tracker.sqlite"), os.path.join(tmp, "x.sqlite"), os.path.join(REPO, "mine.sqlite")]
bad_paths = [os.path.join(REPO, "site", "public", "data", "x.sqlite"), os.path.join(REPO, "site", "public", "data", "ff.json"), os.path.join(REPO, "README.md"), os.path.join(REPO, "site", "pipeline", "y.sqlite"), os.path.join(REPO, "tests", "ff.db")]
check(all(not raises(lambda p=p: F.ensure_local_only(p)) for p in ok_paths), "the tables may go to db/, to any .sqlite or outside the repository")
check(all(raises(lambda p=p: F.ensure_local_only(p), ValueError) for p in bad_paths), "and are refused under site/ and to a name git would track")
gi = open(os.path.join(REPO, ".gitignore")).read().split()
check("db/" in gi and "*.sqlite" in gi, ".gitignore keeps db/ and *.sqlite out of git")
check(raises(lambda: B.build(os.path.join(REPO, "site", "public", "data", "leak.sqlite"), B.DATA, fracfocus=True, ff_zip=zpath), ValueError) and not os.path.exists(os.path.join(REPO, "site", "public", "data", "leak.sqlite")),
      "build_db refuses to put them in the published data folder and writes nothing there")
plain = os.path.join(tmp, "plain.sqlite")
B.build(plain, B.DATA)
names = [x[0] for x in sqlite3.connect(plain).execute("SELECT name FROM sqlite_master")]
check(not any(n.startswith(("ff_", "v_ff_")) for n in names) and "new_wells" in names, "a database built without --fracfocus holds none of the FracFocus tables, only what the site publishes")
text = "".join(open(p, encoding="utf-8").read() for p in (os.path.join(B.DATA, "newwells", "summary.json"), os.path.join(B.DATA, "newwells", "points.json")))
check(not re.search(r"\d{10}", text), "and the site's own FracFocus files still hold no API number")

# ------------------------------------------------------------------------------------------------ through build_db, and its own check
full = os.path.join(tmp, "full.sqlite")
counts_full = B.build(full, B.DATA, ff_zip=zpath, chemicals=True)
check(counts_full["ff_disclosures"] == len(ROWS) and counts_full["ff_ingredients"] == len(INGREDIENTS) and counts_full["new_wells"] > 15000 and B.check(full) == [], "build_db --fracfocus-zip --chemicals adds the tables beside the site's own, and --check is clean")
dbf = sqlite3.connect(full)
check(dict(dbf.execute("SELECT key, value FROM meta WHERE key LIKE 'fracfocus_%'").fetchall())["fracfocus_note"].startswith("Local only"), "the database says in its own meta that it is local only")
dbf.execute("DELETE FROM ff_disclosures WHERE disclosure_id = 'd02'")
dbf.commit()
check(any("ff_disclosures" in x for x in B.check(full)), "a tampered table is noticed by --check")
dbf.execute("UPDATE ff_disclosures SET is_first = 1 WHERE disclosure_id = 'd03'")
dbf.commit()
dbf.close()
check(any("first" in x for x in B.check(full)), "and so is a well with two first disclosures")

# ------------------------------------------------------------------------------------------------ the download: a new folder, resumed once, a refusal is an answer
blob = open(zpath, "rb").read()


class Handler(http.server.BaseHTTPRequestHandler):
    drops = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/forbidden.zip":
            self.send_response(403)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if self.path == "/cut.zip" and not rng:  # the connection drops half way through the first answer
            self.send_response(200)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob[:len(blob) // 2])
            self.wfile.flush()
            self.connection.close()
            return
        a = int(re.match(r"bytes=(\d+)-", rng).group(1)) if rng else 0
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, len(blob) - 1, len(blob)))
        self.send_header("Content-Length", str(len(blob) - a))
        self.end_headers()
        self.wfile.write(blob[a:])


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(k, None)
got = F.download_zip(os.path.join(tmp, "dl-ok"), base + "/ok.zip")
check(open(got, "rb").read() == blob and not os.path.exists(got + ".part"), "the whole zip is fetched into a new folder, byte for byte")
got2 = F.download_zip(os.path.join(tmp, "dl-cut"), base + "/cut.zip")
check(open(got2, "rb").read() == blob, "a connection dropped half way is resumed once from where it stopped, and the file is whole")
check(raises(lambda: F.download_zip(os.path.join(tmp, "dl-ok"), base + "/ok.zip"), ValueError), "a folder that is not empty is refused: each download has its own")
check(raises(lambda: F.download_zip(os.path.join(tmp, "dl-403"), base + "/forbidden.zip"), C.Refused), "a 403 is an answer (Refused), never retried")
srv.shutdown()

# ------------------------------------------------------------------------------------------------ mutants: each puts an old failure back
real_start = F.REGISTRY_START
F.REGISTRY_START = date(1900, 1, 1)
dbm, _ = fresh(name="m1.sqlite")
F.REGISTRY_START = real_start
check(dbm.execute("SELECT date_ok, is_first FROM ff_disclosures WHERE disclosure_id = 'd10'").fetchone() == (1, 1) and r["d10"][18] == 0 and r["d10"][19] == 0, "mutant (the registry's start date removed) counts a 1955 job as a real new well: the start date is what keeps it out")
orig_day = F.day_of
F.day_of = lambda text: None
dbn, _ = fresh(name="m2.sqlite")
F.day_of = orig_day
check(dbn.execute("SELECT COUNT(*) FROM ff_disclosures").fetchone()[0] == len(ROWS) and dbn.execute("SELECT COUNT(*) FROM ff_disclosures WHERE is_first = 1").fetchone()[0] == 0, "mutant (no date can be read) keeps every disclosure and finds no new well: the rows are never dropped for a date")
orig_local = F.ensure_local_only
F.ensure_local_only = lambda p: None
leaked = False
try:
    B.build(os.path.join(REPO, "site", "public", "data", "leak2.sqlite"), B.DATA, ff_zip=zpath)
    leaked = os.path.exists(os.path.join(REPO, "site", "public", "data", "leak2.sqlite"))
finally:
    F.ensure_local_only = orig_local
    try:
        os.remove(os.path.join(REPO, "site", "public", "data", "leak2.sqlite"))
    except OSError:
        pass
check(leaked, "mutant (no local-only guard) writes the FracFocus tables into the published data folder: the guard is what stops it")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
