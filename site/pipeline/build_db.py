#!/usr/bin/env python3
"""The Oil tracker's data in one local SQLite file (standard library only).

Everything the site publishes (every JSON file under site/public/data, the Daily reports of the three states, the national report's files, the matrix of what each permit
captures and the Texas image index) is loaded into one database you can open in any SQLite tool, so it can be queried, joined and kept on your own machine. It is built from the
committed files in a few seconds, never fetched, so it holds exactly what the site holds; rebuild it after pulling. The file is kept out of git (`db/*`, `*.sqlite`), except one compressed snapshot with the FracFocus registry, `db/oil-tracker.sqlite.gz` (the owner's decision of 2026-11-01).

  python3 -I site/pipeline/build_db.py [--out FILE] [--data DIR]       build (default: db/oil-tracker.sqlite)
  python3 -I site/pipeline/build_db.py --check [--out FILE]            open an existing file and verify it (integrity, row counts against its own documents)
  python3 -I site/pipeline/build_db.py --fracfocus [--chemicals]        also load the whole FracFocus registry (ff_disclosures, ff_water_sources and, with --chemicals, ff_ingredients), see ff_db.py
      --fracfocus-zip PATH       from a local copy of FracFocusCSV.zip (443 MB) instead of range requests to fracfocus.org (about 19 MB)
      --fracfocus-download DIR   fetch that zip once into a new folder DIR first (--chemicals needs a local zip: the ingredients are 3.5 GB of CSV)

Two layers, so nothing is lost and common questions are easy:
  documents                 every data file, verbatim (path, size, SHA-256 and the JSON text): the complete record, and what the relational tables are built from
  relational tables         the entities most questions are about:
    jurisdictions           each state, the federal offshore and the BLM: measure, agency, source, dates, and, for those not read yet, the research's grade and reason
    national_months         permits (or spuds) by jurisdiction, month and kind of permit (a kind a source cannot tell has no row: never zero)
    national_operators, national_counties     each jurisdiction's top operators and places, last 12 months
    series                  every monthly or weekly series file, one row per (file, key, time): prices, crude production, rigs, jobs, tax, the EIA outlook, permit series
    county_permits, county_permit_months      per state and county: last 12 months, the 12 before, mean depth, and the 36 monthly counts
    operators               every state's published operator table (Texas's joined with its extras); the full row of each in `extra`
    permit_points           one row per permit with a published location (latitude, longitude, day, depth)
    new_wells_arrivals      the wells each daily FracFocus download added (by arrival day and state), and how many a state's daily report had already carried (null: that report lists no wells)
    new_wells_months, new_wells, new_wells_operators     the national new-wells map (d13_newwells.py, from FracFocus): new wells by state and month, one row per well since 2011 (the last 24 months and the history file) with its
                            published GPS point (latitude, longitude, day, county, operator when it may be named, depth, water, land), and each state's top operators
    companies               the Texas Comptroller's company pool as published here
    daily_reports, daily_permits      the Daily reports by state and day, and each Texas permit row of those days
    tx_image_packs          the three Texas image packs by day: size, documents and kinds
    wells, well_documents, well_packs     the Texas well-image archive (d12_wells.py): each well (API number) with its county, district, field and operator, every scanned document tied to a
                            well (stage, kind, pages, bytes, the GitHub release it is a file of, and the address of the document and of its page-one picture), and the packs read (documents held, tied, not tied)
    metrics, field_states, field_cells, field_sources     the matrix of what each agency's permit captures (when permit-fields.json exists)
  views                     v_permits_by_month (permits and spuds kept apart), v_latest_12_months

The FracFocus tables are optional: they hold what the registry publishes and the site does not (API numbers, well names, operators that are people), so the loader only writes them to a file git
ignores or outside the repository (`ff_db.ensure_local_only`); the one committed snapshot is the compressed `db/oil-tracker.sqlite.gz`. Without --fracfocus the database holds only what the site publishes.

Counts of different measures (permits approved, wells spudded) are different columns of meaning: `jurisdictions.measure` says which, and nothing here adds them.
"""
import argparse
import bisect
import datetime
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path (ff_db is imported only when FracFocus is asked for)
SITE = os.path.dirname(HERE)
REPO = os.path.dirname(SITE)
DATA = os.path.join(SITE, "public", "data")
DEFAULT_OUT = os.path.join(REPO, "db", "oil-tracker.sqlite")
log = lambda m: print(m, flush=True)  # noqa: E731

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE documents(path TEXT PRIMARY KEY, bytes INTEGER, sha256 TEXT, json TEXT);
CREATE TABLE jurisdictions(id TEXT PRIMARY KEY, name TEXT, status TEXT, measure TEXT, basis TEXT, agency TEXT, source_name TEXT, source_url TEXT, as_of TEXT, through TEXT,
  cadence TEXT, grade TEXT, note TEXT, gap_reason TEXT);
CREATE TABLE national_months(jurisdiction TEXT, month TEXT, band TEXT, count INTEGER, PRIMARY KEY(jurisdiction, month, band));
CREATE TABLE national_operators(jurisdiction TEXT, rank INTEGER, operator TEXT, new12 INTEGER, PRIMARY KEY(jurisdiction, rank));
CREATE TABLE national_counties(jurisdiction TEXT, rank INTEGER, place TEXT, new12 INTEGER, PRIMARY KEY(jurisdiction, rank));
CREATE TABLE series(file TEXT, key TEXT, t TEXT, value REAL, PRIMARY KEY(file, key, t));
CREATE TABLE county_permits(state TEXT, county TEXT, county_name TEXT, p12 INTEGER, p12_prev INTEGER, mean_depth_ft REAL, PRIMARY KEY(state, county));
CREATE TABLE county_permit_months(state TEXT, county TEXT, month TEXT, n INTEGER, PRIMARY KEY(state, county, month));
CREATE TABLE operators(state TEXT, num TEXT, name TEXT, band TEXT, type TEXT, city TEXT, addr_state TEXT, new12 INTEGER, prev12 INTEGER, all12 INTEGER, all24 INTEGER,
  last_permit TEXT, extra TEXT, PRIMARY KEY(state, num));
CREATE TABLE permit_points(state TEXT, day TEXT, lat REAL, lon REAL, operator TEXT, operator_num TEXT, depth_ft INTEGER, county_code INTEGER);
CREATE TABLE new_wells_months(state TEXT, month TEXT, wells INTEGER, PRIMARY KEY(state, month));
CREATE TABLE new_wells(state TEXT, day TEXT, lat REAL, lon REAL, county TEXT, operator TEXT, depth_ft INTEGER, water_gal INTEGER, land TEXT);
CREATE TABLE new_wells_operators(state TEXT, rank INTEGER, operator TEXT, wells12 INTEGER, PRIMARY KEY(state, rank));
CREATE TABLE new_wells_arrivals(day TEXT, state TEXT, found INTEGER, reported INTEGER, PRIMARY KEY(day, state));
CREATE TABLE companies(fit TEXT, band TEXT, segment TEXT, name TEXT, city TEXT, state TEXT, zip TEXT, naics TEXT, word TEXT, is_new INTEGER, years TEXT, new12 INTEGER,
  all12 INTEGER, match TEXT, rrc_num TEXT, reason TEXT);
CREATE TABLE daily_reports(state TEXT, day TEXT, kind TEXT, status TEXT, permits_total INTEGER, permits_new_drill INTEGER, completions_filed INTEGER, transfers_wells INTEGER,
  json TEXT, PRIMARY KEY(state, day));
CREATE TABLE daily_permits(state TEXT, day TEXT, permit TEXT, county TEXT, district TEXT, operator_num TEXT, operator TEXT, depth_ft INTEGER, direction TEXT, api TEXT,
  lat REAL, lon REAL, documents TEXT);
CREATE TABLE tx_image_packs(day TEXT, pack TEXT, pack_day TEXT, bytes INTEGER, modified TEXT, is_empty INTEGER, documents INTEGER, kinds TEXT, PRIMARY KEY(day, pack));
CREATE TABLE wells(api TEXT PRIMARY KEY, county TEXT, county_name TEXT, district TEXT, field TEXT, operator_num TEXT, operator TEXT, documents INTEGER);
CREATE TABLE well_documents(api TEXT, stage TEXT, kind TEXT, day TEXT, pages INTEGER, bytes INTEGER, ext TEXT, file TEXT, release_tag TEXT, has_preview INTEGER, url TEXT, preview_url TEXT, PRIMARY KEY(release_tag, file));
CREATE TABLE well_packs(day TEXT, pack TEXT, name TEXT, bytes INTEGER, documents INTEGER, tied INTEGER, untied INTEGER, rejected INTEGER, wells INTEGER, PRIMARY KEY(day, pack));
CREATE INDEX i_wd ON well_documents(api);
CREATE TABLE metrics(key TEXT PRIMARY KEY, grp TEXT, label TEXT, help TEXT);
CREATE TABLE field_states(state TEXT PRIMARY KEY, name TEXT, agency TEXT, agency_url TEXT, grade TEXT, grade_reason TEXT, form_name TEXT, form_number TEXT, form_url TEXT,
  form_read INTEGER, producer_plan TEXT, researched TEXT);
CREATE TABLE field_cells(state TEXT, metric TEXT, status TEXT, evidence TEXT, note TEXT, PRIMARY KEY(state, metric));
CREATE TABLE field_sources(state TEXT, id TEXT, name TEXT, url TEXT, kind TEXT, format TEXT, grain TEXT, cadence TEXT, history_from TEXT, reachable TEXT, has_approval_date INTEGER,
  has_spud_date INTEGER, columns TEXT);
CREATE INDEX i_nm ON national_months(month);
CREATE INDEX i_series ON series(file, key);
CREATE INDEX i_dp ON daily_permits(state, day);
CREATE INDEX i_pp ON permit_points(state, day);
CREATE INDEX i_op ON operators(state, new12);
CREATE VIEW v_permits_by_month AS
  SELECT n.jurisdiction, j.name, j.measure, n.month, n.count AS new_wells FROM national_months n JOIN jurisdictions j ON j.id = n.jurisdiction WHERE n.band = 'new';
CREATE VIEW v_latest_12_months AS
  SELECT j.id, j.name, j.measure, j.through, (SELECT SUM(count) FROM (SELECT count FROM national_months m WHERE m.jurisdiction = j.id AND m.band = 'new' ORDER BY month DESC LIMIT 12)) AS new_12_months
  FROM jurisdictions j WHERE j.status = 'data';
"""


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def decode_day(t0, t):
    try:
        return (datetime.date.fromisoformat(t0) + datetime.timedelta(days=int(t))).isoformat()
    except (TypeError, ValueError):
        return None


def load_documents(db, data):
    n = 0
    for path in sorted(glob.glob(os.path.join(data, "**", "*.json"), recursive=True)):
        raw = open(path, "rb").read()
        db.execute("INSERT INTO documents VALUES (?,?,?,?)", (os.path.relpath(path, data).replace(os.sep, "/"), len(raw), hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")))
        n += 1
    return n


def load_national(db, data):
    p = os.path.join(data, "national.json")
    if not os.path.exists(p):
        return
    d = jload(p)
    months = d["months"]
    for s in d["states"]:
        db.execute("INSERT INTO jurisdictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (s["id"], s["name"], "data", s["measure"], s["basis"], s["agency"], s["source"]["name"], s["source"]["url"],
                                                                                      s["asOf"], s["through"], s["cadence"], None, s.get("note", ""), None))
        for band, vals in s["bands"].items():
            if vals is None:
                continue  # a band the source cannot tell has no rows: never zero
            db.executemany("INSERT INTO national_months VALUES (?,?,?,?)", [(s["id"], m, band, v) for m, v in zip(months, vals) if v is not None])
        db.executemany("INSERT INTO national_operators VALUES (?,?,?,?)", [(s["id"], i + 1, name, n) for i, (name, n) in enumerate(s["operators"])])
        db.executemany("INSERT INTO national_counties VALUES (?,?,?,?)", [(s["id"], i + 1, name, n) for i, (name, n) in enumerate(s["counties"])])
    for g in d["gaps"]:
        db.execute("INSERT INTO jurisdictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (g["id"], g["name"], "gap", None, None, g.get("agency"), None, None, None, None, None, g.get("grade"), None, g.get("why")))


def load_series(db, data):
    n = 0
    for path in sorted(glob.glob(os.path.join(data, "series-*.json"))):
        d = jload(path)
        axis = "months" if "months" in d else "weeks" if "weeks" in d else None
        if not axis:
            continue
        name = os.path.basename(path)[:-5]
        for key, vals in d.items():
            if key != axis and isinstance(vals, list) and len(vals) == len(d[axis]) and all(v is None or num(v) is not None for v in vals):
                rows = [(name, key, t, v) for t, v in zip(d[axis], vals) if v is not None]
                db.executemany("INSERT INTO series VALUES (?,?,?,?)", rows)
                n += len(rows)
    return n


STATE_FILES = {"TX": ("county-permits", "counties.geo"), "OK": ("county-permits-ok", "counties-ok.geo"), "NM": ("county-permits-nm", "counties-nm.geo"), "FO": ("county-permits-fo", "counties-fo.geo")}


def load_counties(db, data):
    for st, (cf, gf) in STATE_FILES.items():
        p = os.path.join(data, cf + ".json")
        if not os.path.exists(p):
            continue
        d = jload(p)
        names = {}
        if os.path.exists(os.path.join(data, gf + ".json")):
            names = {f["properties"]["f"]: f["properties"]["n"] for f in jload(os.path.join(data, gf + ".json"))["features"]}
        for code, c in d["counties"].items():
            db.execute("INSERT INTO county_permits VALUES (?,?,?,?,?,?)", (st, code, names.get(code), c.get("p12"), c.get("p12prev"), c.get("depth")))
            db.executemany("INSERT INTO county_permit_months VALUES (?,?,?,?)", [(st, code, m, v) for m, v in zip(d["months"], c.get("m") or []) if v is not None])


def load_operators(db, data):
    extras = {}
    p = os.path.join(data, "operator-extras.json")
    if os.path.exists(p):
        e = jload(p)
        extras = {r[0]: dict(zip(e["cols"], r)) for r in e["rows"]}
    for st, f in (("TX", "operators"), ("OK", "operators-ok"), ("NM", "operators-nm"), ("FO", "operators-fo")):
        p = os.path.join(data, f + ".json")
        if not os.path.exists(p):
            continue
        d = jload(p)
        for r in d["rows"]:
            row = dict(zip(d["cols"], r))
            if st == "TX":
                row.update({k: v for k, v in extras.get(row["num"], {}).items() if k != "num"})
            key = row["num"]
            known = ("band", "num", "name", "type", "city", "state", "new12", "prev12", "all12", "all24", "last")
            db.execute("INSERT OR REPLACE INTO operators VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (st, key, row.get("name"), row.get("band"), row.get("type"), row.get("city"), row.get("state"), row.get("new12"),
                                                                                           row.get("prev12"), row.get("all12"), row.get("all24"), row.get("last"),
                                                                                           json.dumps({k: v for k, v in row.items() if k not in known}, separators=(",", ":"))))


def load_points(db, data):
    for st, f in (("TX", "permits"), ("OK", "permits-ok"), ("NM", "permits-nm"), ("FO", "permits-fo")):
        p = os.path.join(data, f + ".json")
        if not os.path.exists(p):
            continue
        d = jload(p)
        i = {c: k for k, c in enumerate(d["cols"])}
        rows = []
        for pt in d["pts"]:
            op = pt[i["op"]]
            rows.append((st, decode_day(d["t0"], pt[i["t"]]), pt[i["lat"]] / 1e4, pt[i["lon"]] / 1e4, d["ops"][op] if 0 <= op < len(d["ops"]) else None,
                         d["opNums"][op] if 0 <= op < len(d["opNums"]) else None, pt[i["depth"]] * 100 if pt[i["depth"]] else None, pt[i["fips"]]))
        db.executemany("INSERT INTO permit_points VALUES (?,?,?,?,?,?,?,?)", rows)


LAND = {0: "private or state", 1: "federal", 2: "tribal", 3: "federal and tribal"}


def newwell_rows(pt, below=None):
    """The rows of a points file (the last 24 months or the history): state, day, place, county, operator, depth, water, land. `below`: only the days before that day number (the history's overlap with the points file is dropped)."""
    rows = []
    for i in range(pt["n"]):
        if below is not None and pt["d"][i] >= below:
            break  # the days are in order
        c, o = pt["c"][i], pt["o"][i]
        rows.append((pt["states"][pt["s"][i]], decode_day(pt["t0"], pt["d"][i]), pt["lat"][i] / 1e4, pt["lon"][i] / 1e4, pt["counties"][c][1] if c >= 0 else None,
                     pt["ops"][o] if o >= 0 else None, pt["tvd"][i] * 100 or None, pt["h2o"][i] * 100000 or None, LAND[pt["f"][i]]))
    return rows


def history_below(pt, hist):
    """How many days of the history lie before the points file starts: the rows the points file does not already hold."""
    return (datetime.date.fromisoformat(pt["t0"]) - datetime.date.fromisoformat(hist["t0"])).days


def load_newwells(db, data):
    ps, pp, ph = (os.path.join(data, "newwells", f) for f in ("summary.json", "points.json", "points-history.json"))
    if not (os.path.exists(ps) and os.path.exists(pp)):
        return 0
    sm, pt = jload(ps), jload(pp)
    for s in sm["states"]:
        db.executemany("INSERT INTO new_wells_months VALUES (?,?,?)", [(s["id"], m, v) for m, v in zip(sm["months"], s["new"])])
        db.executemany("INSERT INTO new_wells_operators VALUES (?,?,?,?)", [(s["id"], i + 1, name, n) for i, (name, n) in enumerate(s["operators"])])
    rows = newwell_rows(pt)
    if os.path.exists(ph):  # every earlier well with a point, back to 2011 (the page loads these only on request; here they are rows like the others)
        hist = jload(ph)
        rows = newwell_rows(hist, history_below(pt, hist)) + rows
    db.executemany("INSERT INTO new_wells VALUES (?,?,?,?,?,?,?,?,?)", rows)
    pa = os.path.join(data, "newwells", "arrivals.json")
    if os.path.exists(pa):
        arr = jload(pa)
        db.executemany("INSERT INTO new_wells_arrivals VALUES (?,?,?,?)", [(d["day"], st, n, rep) for d in arr.get("days", []) for st, n, rep in d["states"]])
    return len(rows)


def load_companies(db, data):
    p = os.path.join(data, "companies.json")
    if os.path.exists(p):
        d = jload(p)
        db.executemany("INSERT INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [tuple(r) for r in d["rows"]])


def load_daily(db, data):
    nrep = nrows = 0
    for st, sub in (("TX", "daily"), ("OK", "daily-ok"), ("NM", "daily-nm")):
        for path in sorted(glob.glob(os.path.join(data, sub, "????-??-??.json"))):
            d = jload(path)
            day = d.get("date") or os.path.basename(path)[:-5]
            p, c, t = d.get("permits") or {}, d.get("completions") or {}, d.get("transfers") or {}
            db.execute("INSERT INTO daily_reports VALUES (?,?,?,?,?,?,?,?,?)", (st, day, d.get("kind"), d.get("status"), p.get("total"), p.get("newDrill"), c.get("filed"), t.get("wells"),
                                                                                json.dumps(d, ensure_ascii=False, separators=(",", ":"))))
            nrep += 1
            for r in p.get("rows") or []:
                r = list(r) + [None] * (11 - len(r))
                db.execute("INSERT INTO daily_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (st, day, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], num(r[8]), num(r[9]), json.dumps(r[10]) if r[10] else None))
                nrows += 1
            if st == "TX":
                for pack, im in (d.get("images") or {}).items():
                    if not isinstance(im, dict):
                        continue  # a day with no entry for that pack
                    docs = im.get("docs") or {}
                    db.execute("INSERT INTO tx_image_packs VALUES (?,?,?,?,?,?,?,?)", (day, pack, im.get("day"), im.get("bytes"), im.get("modified"), 1 if im.get("empty") else 0,
                                                                                      docs.get("n") if isinstance(docs, dict) else None, json.dumps(docs.get("types")) if isinstance(docs, dict) and docs.get("types") else None))
    return nrep, nrows


def load_wells(db, data):
    """The well-image archive: wells, the documents tied to them (with their addresses on GitHub) and the packs they came from. Nothing when the index does not exist yet."""
    p = os.path.join(data, "wells", "index.json")
    if not os.path.exists(p):
        return 0, 0
    idx = jload(p)
    repo = idx.get("repo")
    stage = {"p": "permit", "d": "drilling", "c": "completion"}
    db.executemany("INSERT INTO well_packs VALUES (?,?,?,?,?,?,?,?,?)", [(u["d"], u["p"], u.get("name"), u.get("bytes"), u.get("docs"), u.get("tied"), u.get("untied"), u.get("rejected"), u.get("wells")) for u in idx.get("units", [])])
    nw = nd = 0
    for path in sorted(glob.glob(os.path.join(data, "wells", "county", "*.json"))):
        sh = jload(path)
        for w in sh["wells"]:
            db.execute("INSERT INTO wells VALUES (?,?,?,?,?,?,?,?)", (w["a"], sh["county"], sh.get("name"), w.get("di"), w.get("fl"), w.get("o"), w.get("on"), len(w["docs"])))
            nw += 1
            for x in w["docs"]:
                tag = sh["tags"][x["t"]]
                base = "https://github.com/%s/releases/download/%s/%s." % (repo, tag, x["f"])
                db.execute("INSERT INTO well_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (w["a"], stage.get(x["s"], x["s"]), x["k"], x["d"], num(x.get("pg")), x["b"], x["x"], x["f"], tag, 1 if x.get("v") else 0,
                                                                                         base + x["x"], base + "jpg" if x.get("v") else None))
                nd += 1
    return nw, nd


def load_fields(db, data):
    p = os.path.join(data, "permit-fields.json")
    if not os.path.exists(p):
        return 0
    d = jload(p)
    db.executemany("INSERT INTO metrics VALUES (?,?,?,?)", [(m["key"], m["group"], m["label"], m["help"]) for m in d["metrics"]])
    for sid, s in d["states"].items():
        f, a = s["form"], s["agency"]
        db.execute("INSERT INTO field_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (sid, s["name"], a.get("name"), a.get("url"), s["grade"], s["grade_reason"], f.get("name"), f.get("number"), f.get("url"),
                                                                                  1 if f.get("read") else 0, s.get("producer_plan"), s.get("researched")))
        db.executemany("INSERT INTO field_cells VALUES (?,?,?,?,?)", [(sid, k, v[0], v[1], v[2]) for k, v in s["cells"].items()])
        db.executemany("INSERT INTO field_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [(sid, x.get("id"), x.get("name"), x.get("url"), x.get("kind"), x.get("format"), x.get("grain"), x.get("cadence"), x.get("history_from"),
                                                                                         x.get("reachable"), None if x.get("has_approval_date") is None else int(bool(x["has_approval_date"])),
                                                                                         None if x.get("has_spud_date") is None else int(bool(x["has_spud_date"])), json.dumps(x.get("columns") or [])) for x in s["sources"]])
    return len(d["states"])


def build(out=DEFAULT_OUT, data=DATA, now=None, fracfocus=False, ff_zip=None, chemicals=False):
    """Builds the database at `out` (written to a temporary name and moved into place, so a failed build leaves the old file alone). Returns the table row counts.
    `fracfocus` (or `ff_zip`, a local FracFocusCSV.zip) adds the whole FracFocus registry, `chemicals` its ingredients too (ff_db.py)."""
    with_ff = bool(fracfocus or ff_zip or chemicals)
    if with_ff:
        import ff_db
        ff_db.ensure_local_only(out)
    if os.path.exists(out):
        with open(out, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise ValueError("%s exists and is not a SQLite file: refusing to overwrite it" % out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        ndocs = load_documents(db, data)
        load_national(db, data)
        nseries = load_series(db, data)
        load_counties(db, data)
        load_operators(db, data)
        load_points(db, data)
        nnew = load_newwells(db, data)
        load_companies(db, data)
        nrep, nrows = load_daily(db, data)
        nwells, nwdocs = load_wells(db, data)
        nfields = load_fields(db, data)
        if with_ff:
            ff_db.load(db, ff_zip, chemicals, log=log)
        stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.executemany("INSERT INTO meta VALUES (?,?)", [("built", stamp), ("source", "site/public/data (committed files)"), ("documents", str(ndocs)), ("series_rows", str(nseries)),
                                                          ("new_wells", str(nnew)), ("daily_reports", str(nrep)), ("daily_permit_rows", str(nrows)), ("wells", str(nwells)), ("well_documents", str(nwdocs)), ("field_states", str(nfields)),
                                                          ("note", "Counts of different measures (permits approved, wells spudded) are never added: see jurisdictions.measure.")])
        db.commit()
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError("integrity check failed: " + ok)
        counts = counts_of(db)
    except Exception:
        db.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    db.close()
    os.replace(tmp, out)
    return counts


def counts_of(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {n: db.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0] for n in names}


def check(out):
    """Opens an existing file and verifies it: integrity, every document's SHA-256, and the tables against the documents they came from. Returns problems."""
    if not os.path.exists(out):
        return ["%s does not exist" % out]
    db = sqlite3.connect("file:%s?mode=ro" % out, uri=True)
    p = []
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            p.append("integrity check failed")
        for path, nbytes, sha, text in db.execute("SELECT path, bytes, sha256, json FROM documents"):
            raw = text.encode("utf-8")
            if len(raw) != nbytes or hashlib.sha256(raw).hexdigest() != sha:
                p.append("document %s does not match its size or hash" % path)
        nat = db.execute("SELECT json FROM documents WHERE path = 'national.json'").fetchone()
        if nat:
            d = json.loads(nat[0])
            if db.execute("SELECT COUNT(*) FROM jurisdictions").fetchone()[0] != len(d["states"]) + len(d["gaps"]):
                p.append("jurisdictions do not match national.json")
            want = sum(1 for s in d["states"] for v in s["bands"].values() if v is not None for x in v if x is not None)
            if db.execute("SELECT COUNT(*) FROM national_months").fetchone()[0] != want:
                p.append("national_months does not match national.json")
        nw = db.execute("SELECT json FROM documents WHERE path = 'newwells/points.json'").fetchone()
        nh = db.execute("SELECT json FROM documents WHERE path = 'newwells/points-history.json'").fetchone()  # absent in a file made before the history existed
        if nw:
            pts = json.loads(nw[0])
            want = pts["n"]
            if nh:
                hist = json.loads(nh[0])
                want += bisect.bisect_left(hist["d"], history_below(pts, hist))
            if db.execute("SELECT COUNT(*) FROM new_wells").fetchone()[0] != want:
                p.append("new_wells does not match newwells/points.json and points-history.json")
        na = db.execute("SELECT json FROM documents WHERE path = 'newwells/arrivals.json'").fetchone()
        if na and db.execute("SELECT COUNT(*) FROM new_wells_arrivals").fetchone()[0] != sum(len(d["states"]) for d in json.loads(na[0]).get("days", [])):
            p.append("new_wells_arrivals does not match newwells/arrivals.json")
        wdocs = sum(sum(len(w["docs"]) for w in json.loads(t)["wells"]) for (t,) in db.execute("SELECT json FROM documents WHERE path GLOB 'wells/county/*.json'"))
        if db.execute("SELECT COUNT(*) FROM well_documents").fetchone()[0] != wdocs:
            p.append("well_documents does not match the county files")
        ndaily = db.execute("SELECT COUNT(*) FROM documents WHERE path GLOB 'daily*/????-??-??.json'").fetchone()[0]
        if db.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0] != ndaily:
            p.append("daily_reports does not match the day files")
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'ff_disclosures'").fetchone():
            import ff_db
            p += ff_db.check(db)
    finally:
        db.close()
    return p


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fracfocus", action="store_true", help="also load the whole FracFocus registry (local only)")
    ap.add_argument("--fracfocus-zip", metavar="PATH", help="a local copy of FracFocusCSV.zip")
    ap.add_argument("--fracfocus-download", metavar="DIR", help="fetch FracFocusCSV.zip once into a new folder first")
    ap.add_argument("--chemicals", action="store_true", help="with FracFocus: the ingredients too (about 7 million rows; needs the whole zip)")
    a = ap.parse_args(argv)
    if a.check:
        bad = check(a.out)
        for x in bad:
            log(x)
        log("check: " + ("FAILED" if bad else "clean"))
        return 1 if bad else 0
    zip_path = a.fracfocus_zip
    if a.fracfocus_download:
        import ff_db
        ff_db.ensure_local_only(a.out)
        zip_path = ff_db.download_zip(a.fracfocus_download)
        log("downloaded " + zip_path)
    counts = build(a.out, a.data, fracfocus=a.fracfocus, ff_zip=zip_path, chemicals=a.chemicals)
    log("wrote %s (%d bytes)" % (os.path.relpath(a.out, REPO) if a.out.startswith(REPO) else a.out, os.path.getsize(a.out)))
    for name, n in counts.items():
        log("  %-22s %8d" % (name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
