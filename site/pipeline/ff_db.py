#!/usr/bin/env python3
"""The whole FracFocus registry in the local SQLite database (standard library only; used by build_db.py).

The site publishes only what is safe on a public page: a well's position, county, day, depth and water, and an operator only when it may be named
(`data/newwells/`, 24 months of points). The owner's local database can hold more: every disclosure the registry has ever received, with every column
FracFocus publishes, so it can be queried and joined on one machine. This module reads the registry's own download, `FracFocusCSV.zip`, and writes:

  ff_disclosures    one row per disclosure (251,953 on 2026-11-01): the registry's id, the job's start and end (parsed to ISO dates, the registry's own text kept
                    beside them), the API number (`api`, and `api10` its first ten digits: the well), state (name and code), county, operator, well name,
                    latitude and longitude as filed, datum, depth, water and non-water volumes, form version, federal and tribal flags, and two columns this
                    project adds: `date_ok` (the job date is a real one, from 2011 to today) and `is_first` (this disclosure is the first of its well: the site's
                    definition of a new well, so `SELECT ... WHERE is_first` gives the same wells as the Overview)
  ff_water_sources  every water source of every job (`WaterSource_1.csv`: produced water, surface water, recycled...)
  ff_ingredients    with --chemicals only: every ingredient of every job (the 15 `FracFocusRegistry_N.csv` files, about 7 million rows): purpose, trade name,
                    supplier, CAS number, chemical name, percent of the job, mass; the header columns they repeat are not repeated here, they are in ff_disclosures
  views             v_ff_new_wells (the first disclosure of each well) and v_ff_new_wells_by_month (by state and month)

This is the registry as FracFocus publishes it, and it names things the site never does: API numbers, well names, and operators that are people. It is for
the owner's machine only. The database file is kept out of git (`db/`, `*.sqlite`), `ensure_local_only` refuses to write these tables anywhere that could be
published, and nothing here is ever copied into `site/public/data`.

Sources: the disclosure list and the water sources are read by HTTP range requests (about 19 MB of the 443 MB zip, as `d13_newwells.py` does), or from a local
copy of the zip (`--fracfocus-zip`). The ingredients need the whole zip, so --chemicals needs a local copy too: `--fracfocus-download DIR` fetches it once into a new
folder (443 MB, one request, resumed at most once; never retried in a loop).
"""
import csv
import http.client
import io
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
REPO = os.path.dirname(SITE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d13_newwells as W  # noqa: E402  (the range reader, the state names)

URL = W.URL
REGISTRY_START = W.REGISTRY_START
BATCH = 50000
MIN_ROWS = 100000  # a registry list shorter than this looks cut short (it has 252,000): refused; the tests set it lower

SCHEMA_DISCLOSURES = """
CREATE TABLE ff_disclosures(disclosure_id TEXT PRIMARY KEY, job_start TEXT, job_start_text TEXT, job_end TEXT, job_end_text TEXT, api TEXT, api10 TEXT, state TEXT, state_code TEXT,
  county TEXT, operator TEXT, well_name TEXT, latitude REAL, longitude REAL, datum TEXT, tvd_ft REAL, water_gal REAL, non_water_gal REAL, ff_version TEXT, federal INTEGER, tribal INTEGER,
  date_ok INTEGER, is_first INTEGER);
CREATE INDEX i_ffd_api10 ON ff_disclosures(api10);
CREATE INDEX i_ffd_state ON ff_disclosures(state_code, job_start);
CREATE INDEX i_ffd_operator ON ff_disclosures(operator);
CREATE VIEW v_ff_new_wells AS SELECT * FROM ff_disclosures WHERE is_first = 1;
CREATE VIEW v_ff_new_wells_by_month AS SELECT state_code, substr(job_start, 1, 7) AS month, COUNT(*) AS wells FROM ff_disclosures WHERE is_first = 1 GROUP BY 1, 2;
"""
SCHEMA_WATER = """
CREATE TABLE ff_water_sources(water_source_id TEXT PRIMARY KEY, disclosure_id TEXT, api TEXT, state TEXT, county TEXT, operator TEXT, well_name TEXT, description TEXT, percent REAL);
CREATE INDEX i_ffw_disclosure ON ff_water_sources(disclosure_id);
"""
SCHEMA_INGREDIENTS = """
CREATE TABLE ff_ingredients(disclosure_id TEXT, purpose_id TEXT, trade_name TEXT, supplier TEXT, purpose TEXT, ingredients_id TEXT, cas_number TEXT, ingredient_name TEXT, common_name TEXT,
  percent_high_additive REAL, percent_hf_job REAL, comment TEXT, msds INTEGER, mass_ingredient REAL, claimant_company TEXT);
CREATE INDEX i_ffi_disclosure ON ff_ingredients(disclosure_id);
CREATE INDEX i_ffi_cas ON ff_ingredients(cas_number);
"""
DISCLOSURE_COLUMNS = ("DisclosureId", "JobStartDate", "JobEndDate", "APINumber", "StateName", "CountyName", "OperatorName", "WellName", "Latitude", "Longitude", "Projection", "TVD",
                      "TotalBaseWaterVolume", "TotalBaseNonWaterVolume", "FFVersion", "FederalWell", "IndianWell")
WATER_COLUMNS = ("WaterSourceId", "DisclosureId", "APINumber", "StateName", "CountyName", "OperatorName", "WellName", "Description", "Percent")
INGREDIENT_COLUMNS = ("DisclosureId", "PurposeId", "TradeName", "Supplier", "Purpose", "IngredientsId", "CASNumber", "IngredientName", "IngredientCommonName", "PercentHighAdditive",
                      "PercentHFJob", "IngredientComment", "IngredientMSDS", "MassIngredient", "ClaimantCompany")


def ensure_local_only(path):
    """These tables hold what the registry publishes and the site does not (API numbers, well names, operators that are people): the file may only be written where git
    ignores it (`db/`, `*.sqlite`) or outside the repository, never under `site/`, never to a name git would track."""
    real = os.path.realpath(path)
    repo = os.path.realpath(REPO)
    inside = real == repo or real.startswith(repo + os.sep)
    if inside:
        rel = os.path.relpath(real, repo).replace(os.sep, "/")
        if rel.startswith("site/") or not (rel.startswith("db/") or rel.endswith((".sqlite", ".sqlite3"))):
            raise ValueError("refusing to write the FracFocus tables to %s: they hold API numbers, well names and operators that the site never publishes; use db/oil-tracker.sqlite or a place outside the repository" % rel)


def day_of(text):
    """The ISO date of the registry's '5/1/1955 12:00:00 AM', or None."""
    try:
        return datetime.strptime((text or "").strip().split(" ")[0], "%m/%d/%Y").date()
    except ValueError:
        return None


def flag(text):
    t = (text or "").strip().lower()
    return 1 if t == "true" else 0 if t == "false" else None


def text_or_none(v):
    v = (v or "").strip()
    return v or None


def disclosure_rows(rows, today=None):
    """The rows of ff_disclosures from the registry's disclosure list (dicts), in file order, with `is_first` set: the first disclosure of each well (the first ten digits of
    its API number), by job date, among the disclosures whose date is a real one; on a tie the one that comes first in the file (d13_newwells.Wells does the same)."""
    today = today or date.today()
    recs = []
    first = {}
    for n, r in enumerate(rows):
        start, end = day_of(r.get("JobStartDate")), day_of(r.get("JobEndDate"))
        api = re.sub(r"\D", "", r.get("APINumber") or "")
        api10 = api[:10] if len(api) >= 10 else None
        ok = 1 if start is not None and REGISTRY_START <= start <= today else 0
        if ok and api10 and (api10 not in first or start < first[api10][0]):
            first[api10] = (start, n)
        state = " ".join((r.get("StateName") or "").split()) or None
        recs.append((r.get("DisclosureId"), start.isoformat() if start else None, text_or_none(r.get("JobStartDate")), end.isoformat() if end else None, text_or_none(r.get("JobEndDate")),
                     api or None, api10, state, W.STATE_OF.get(state), text_or_none(r.get("CountyName")), text_or_none(r.get("OperatorName")), text_or_none(r.get("WellName")),
                     W.number(r.get("Latitude")), W.number(r.get("Longitude")), text_or_none(r.get("Projection")), W.number(r.get("TVD")), W.number(r.get("TotalBaseWaterVolume")),
                     W.number(r.get("TotalBaseNonWaterVolume")), text_or_none(r.get("FFVersion")), flag(r.get("FederalWell")), flag(r.get("IndianWell")), ok))
    firsts = {n for _, n in first.values()}
    return [rec + (1 if n in firsts else 0,) for n, rec in enumerate(recs)]


def _members(zf, pattern):
    names = [n for n in zf.namelist() if re.fullmatch(pattern, n)]
    return sorted(names, key=lambda n: int(re.search(r"\d+", n).group()))


def _dict_rows(zf, name, needed):
    with zf.open(name) as f:
        rd = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
        missing = [c for c in needed if c not in (rd.fieldnames or [])]
        if missing:
            raise ValueError("%s lacks the columns %s" % (name, ", ".join(missing)))
        yield from rd


def _insert(db, sql, rows):
    batch = []
    n = 0
    for row in rows:
        batch.append(row)
        if len(batch) >= BATCH:
            db.executemany(sql, batch)
            n += len(batch)
            batch = []
    if batch:
        db.executemany(sql, batch)
        n += len(batch)
    return n


def open_zip(zip_path=None):
    """(ZipFile, RangeFile or None): a local copy, or the registry's own zip read by range requests (never downloaded whole)."""
    if zip_path:
        return zipfile.ZipFile(zip_path), None
    fetch, size = W.http_range(URL)
    rf = W.RangeFile(fetch, size)
    return zipfile.ZipFile(rf), rf


def load(db, zip_path=None, chemicals=False, today=None, log=lambda m: None):
    """Adds the FracFocus tables to an open database. `zip_path` a local FracFocusCSV.zip (None: the disclosure list and water sources by range requests; --chemicals needs a
    local zip). Returns {table: rows}; the `meta` table gets what was read."""
    if chemicals and not zip_path:
        raise ValueError("the ingredients (about 7 million rows) need the whole zip: give a local copy (--fracfocus-zip) or fetch one (--fracfocus-download DIR)")
    zf, rf = open_zip(zip_path)
    counts = {}
    with zf:
        lists = _members(zf, r"DisclosureList_\d+\.csv")
        if not lists:
            raise ValueError("the zip has no DisclosureList_N.csv")
        rows = [r for name in lists for r in _dict_rows(zf, name, DISCLOSURE_COLUMNS)]
        if len(rows) < MIN_ROWS:
            raise ValueError("only %d disclosures read: refusing to load a registry that looks cut short" % len(rows))
        db.executescript(SCHEMA_DISCLOSURES)
        counts["ff_disclosures"] = _insert(db, "INSERT INTO ff_disclosures VALUES (%s)" % ",".join("?" * 23), disclosure_rows(rows, today))
        log("loaded %d disclosures" % counts["ff_disclosures"])
        del rows
        db.executescript(SCHEMA_WATER)
        counts["ff_water_sources"] = 0
        for name in _members(zf, r"WaterSource_\d+\.csv"):
            counts["ff_water_sources"] += _insert(db, "INSERT INTO ff_water_sources VALUES (?,?,?,?,?,?,?,?,?)",
                                                   ((r["WaterSourceId"], r["DisclosureId"], text_or_none(re.sub(r"\D", "", r["APINumber"] or "")), text_or_none(r["StateName"]), text_or_none(r["CountyName"]),
                                                     text_or_none(r["OperatorName"]), text_or_none(r["WellName"]), text_or_none(r["Description"]), W.number(r["Percent"]))
                                                    for r in _dict_rows(zf, name, WATER_COLUMNS)))
        log("loaded %d water sources" % counts["ff_water_sources"])
        if chemicals:
            db.executescript(SCHEMA_INGREDIENTS)
            counts["ff_ingredients"] = 0
            for name in _members(zf, r"FracFocusRegistry_\d+\.csv"):
                counts["ff_ingredients"] += _insert(db, "INSERT INTO ff_ingredients VALUES (%s)" % ",".join("?" * 15),
                                                     ((r["DisclosureId"], text_or_none(r["PurposeId"]), text_or_none(r["TradeName"]), text_or_none(r["Supplier"]), text_or_none(r["Purpose"]),
                                                       text_or_none(r["IngredientsId"]), text_or_none(r["CASNumber"]), text_or_none(r["IngredientName"]), text_or_none(r["IngredientCommonName"]),
                                                       W.number(r["PercentHighAdditive"]), W.number(r["PercentHFJob"]), text_or_none(r["IngredientComment"]), flag(r["IngredientMSDS"]),
                                                       W.number(r["MassIngredient"]), text_or_none(r["ClaimantCompany"])) for r in _dict_rows(zf, name, INGREDIENT_COLUMNS)))
                log("  %s: %d ingredient rows so far" % (name, counts["ff_ingredients"]))
    meta = [("fracfocus_source", ("a local copy of " if zip_path else "range requests to ") + "FracFocusCSV.zip (fracfocus.org/data-download)"), ("fracfocus_disclosures", str(counts["ff_disclosures"])),
            ("fracfocus_water_sources", str(counts["ff_water_sources"])), ("fracfocus_ingredients", str(counts.get("ff_ingredients", "not loaded"))),
            ("fracfocus_note", "Local only: holds API numbers, well names and operators that are people, which the site never publishes. Never commit or publish this file.")]
    db.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", meta)
    return counts


def download_zip(folder, url=URL):
    """Fetches the whole FracFocusCSV.zip once into `folder`, which must be new or empty (each download has its own folder). One request, resumed at most once after a
    dropped connection; a refusal is an answer. Returns the file's path."""
    if os.path.exists(folder) and os.listdir(folder):
        raise ValueError("%s is not empty: each download goes in a new folder" % folder)
    os.makedirs(folder, exist_ok=True)
    path, part = os.path.join(folder, "FracFocusCSV.zip"), os.path.join(folder, "FracFocusCSV.zip.part")
    total = None
    for attempt in range(2):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(url, headers={"User-Agent": W.C.UA, "Accept-Encoding": "identity", **({"Range": "bytes=%d-" % have} if have else {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "ab") as f:
                if have and r.status != 206:
                    raise ValueError("the server does not resume a download (HTTP %d)" % r.status)
                total = (have + int(r.headers.get("Content-Length") or 0)) if total is None else total
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 407, 429):
                raise W.C.Refused("HTTP %d from the server" % e.code)
            raise
        except (OSError, http.client.HTTPException):
            if attempt:
                raise
        # a connection that closes early ends the read quietly: only the size says whether the file is whole, and then it is resumed (once)
        if total and os.path.getsize(part) == total:
            break
    if not total or os.path.getsize(part) != total:
        raise OSError("the download is %d bytes of %s: not complete" % (os.path.getsize(part), total))
    os.replace(part, path)
    return path


def check(db):
    """Problems with the FracFocus tables of an open database ([] when good, or when they are not there): counts against `meta`, one first disclosure a well, a first disclosure
    always has a real date."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'ff_disclosures'").fetchone():
        return []
    p = []
    meta = dict(db.execute("SELECT key, value FROM meta WHERE key LIKE 'fracfocus_%'").fetchall())
    n = db.execute("SELECT COUNT(*) FROM ff_disclosures").fetchone()[0]
    if str(n) != meta.get("fracfocus_disclosures"):
        p.append("ff_disclosures has %d rows, its meta says %s" % (n, meta.get("fracfocus_disclosures")))
    if db.execute("SELECT COUNT(*) FROM ff_water_sources").fetchone()[0] != int(meta.get("fracfocus_water_sources", -1)):
        p.append("ff_water_sources does not match its meta")
    if db.execute("SELECT COUNT(*) FROM (SELECT api10 FROM ff_disclosures WHERE is_first = 1 GROUP BY api10 HAVING COUNT(*) > 1)").fetchone()[0]:
        p.append("a well has more than one first disclosure")
    if db.execute("SELECT COUNT(*) FROM ff_disclosures WHERE is_first = 1 AND (date_ok != 1 OR api10 IS NULL)").fetchone()[0]:
        p.append("a first disclosure has no real date or no API number")
    if db.execute("SELECT COUNT(DISTINCT api10) FROM ff_disclosures WHERE date_ok = 1 AND api10 IS NOT NULL").fetchone()[0] != db.execute("SELECT COUNT(*) FROM ff_disclosures WHERE is_first = 1").fetchone()[0]:
        p.append("the wells with a real date and the first disclosures differ")
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'ff_ingredients'").fetchone() and str(db.execute("SELECT COUNT(*) FROM ff_ingredients").fetchone()[0]) != meta.get("fracfocus_ingredients"):
        p.append("ff_ingredients does not match its meta")
    return p
