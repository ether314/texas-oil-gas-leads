#!/usr/bin/env python3
"""D4 producer: Texas oil and gas production layers from the RRC Production Data Query (PDQ) dump.

Writes three compact UTF-8 JSON files into <site>/public/data/ (schemas: site/DATA_CONTRACT_V3.md, section D4):
  county-production.json    per county: oil and gas for the latest 12 months and the 12 before, 36 monthly values, leases
  operator-production.json  per nameable operator (P-5 type corporation, LLC or limited partnership, any P-5 status):
                            the same for 24 months, plus its name, P-5 status and type (rows trimmed to the 500 KB budget)
  series-production.json    statewide monthly oil and gas since 2019-01, the incomplete tail, and the EIA comparison

Input: PDQ_DSV.zip, the Railroad Commission's "Production Data Query Dump" (delimiter '}', header line, one table per
zip member; manual: pdq-dump-user-manual.pdf). The zip is only read and parsed, never extracted or executed: run with
`python3 -I`. The members are streamed straight out of the zip. Tables used:
  GP_DATE_RANGE_CYCLE       newest production cycle in the dump and the extract date
  GP_COUNTY                 county number -> FIPS (identical for the 254 onshore counties; offshore areas are 600-715)
  OG_COUNTY_CYCLE           oil and gas by county, district and month: the county and statewide figures
  OG_COUNTY_LEASE_CYCLE     the same by lease and county (12.8 GB of text): lease counts, per-operator volumes, and an
                            independent re-sum of the county table
  OG_OPERATOR_CYCLE         by operator and month: cross-check of the per-operator volumes and of the statewide totals
  orf850.txt.gz             P-5 Organization file (fetched with rrc_fetch.py): name, status and organization type of
                            every operator; the type gates which operators may be named
  rrc_operators.csv         active P-5 registrants: only a cross-check of the P-5 file and of the operator coverage

Units (manual): OIL_PROD_VOL and COND_PROD_VOL are barrels, GAS_PROD_VOL and CSGD_PROD_VOL are mcf.
  oil = crude oil (OIL_PROD_VOL) + condensate (COND_PROD_VOL); gas = gas-well gas (GAS_PROD_VOL) + casinghead gas
  (CSGD_PROD_VOL), summed over oil leases ('O') and gas wells ('G').

Complete months: the dump's newest cycle is only partly reported (operators file late). A month is complete when RRC
statewide crude + condensate is at least 98% of EIA's Texas field production (series-markets.json `txCrude`) and every
earlier month since 2024-01 also is; months EIA has not published cannot be verified and are left out. The three files
end at that month (override: --complete-through YYYY-MM); the statewide tail after it is kept in series-production.json
under `partial`. See site/pipeline/NOTES_D4.md.

  python3 -I site/pipeline/d4_production.py [--zip PDQ_DSV.zip] [--p5 orf850.txt.gz] [--dl DIR] [--out DIR]
                                            [--asof YYYY-MM-DD] [--complete-through YYYY-MM] [--min-eia-ratio 0.98]
Fetching the dump: python3 -I rrc_fetch.py 1f5ddb8d-329a-4459-b7f8-177b4f5ee60d PDQ_DSV.zip <new empty folder>
(about 3.45 GB, roughly an hour; it refreshes monthly on the last Saturday). The P-5 file: rrc_fetch.py
04652169-eed6-4396-9019-2e270e790f6c orf850.txt.gz <new empty folder>.
"""
import argparse
import csv
import gzip
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
# raw downloads go in the gitignored dl/ folder at the repo root, one new folder per file (DATA_CONTRACT.md); override with --dl / --zip
DEFAULT_DL = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dl"))

ASOF = "2026-10-30"
SERIES_START = "2019-01"
CHECK_START = "2024-01"            # the EIA completeness test starts here (earlier months are long settled)
MIN_EIA_RATIO = 0.98
ENTITY_TYPES = {"corporation", "limited partnership", "LLC"}  # the only org types that may be named
# P-5 organization code (orf850 position 45) -> type, as in rrc_operators.py
P5_ORG_TYPES = {"A": "corporation", "B": "limited partnership", "C": "sole proprietor", "D": "partnership",
                "E": "trust", "F": "joint venture", "G": "other", "H": "LLC", "I": "other (code I)"}
P5_GUID = "04652169-eed6-4396-9019-2e270e790f6c"
BUDGET_DEFAULT = 400_000           # bytes per file (DATA_CONTRACT_V3.md rule 4: 400 KB)
BUDGET_OPERATORS = 500_000         # operator-production.json
GUID = "1f5ddb8d-329a-4459-b7f8-177b4f5ee60d"
PAGE = "https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/"
UNIT = {"oil": "barrels (crude oil + condensate)", "gas": "mcf (gas well + casinghead)"}


# ---------------------------------------------------------------------------------------------------- small helpers
def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def add_months(m, k):
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def month_list(first, last):
    out, m = [], first
    while m <= last:
        out.append(m)
        m = add_months(m, 1)
    return out


def to_ym(m):                      # "2026-01" -> "202601"
    return m[:4] + m[5:7]


def from_ym(s):                    # "202601" -> "2026-01"
    return s[:4] + "-" + s[4:6]


def norm_op(s):
    """Operator number as the CSV writes it: six digits, zero padded."""
    s = s.strip()
    return s.zfill(6) if s.isdigit() else s


def norm_name(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)
    return os.path.getsize(path)


# ---------------------------------------------------------------------------------------------------- zip tables
def find_member(zf, table):
    want = table.upper() + "_DATA_TABLE.DSV"
    for n in zf.namelist():
        if os.path.basename(n).upper() == want:
            return n
    raise SystemExit("table %s not found in the zip (members: %s)" % (table, ", ".join(zf.namelist())[:300]))


def open_table(zf, table, required):
    """(column name -> index, binary stream positioned after the header line). Fails loudly on missing columns."""
    f = zf.open(find_member(zf, table))
    head = f.readline().lstrip(b"\xef\xbb\xbf").decode("latin-1").rstrip("\r\n")
    ix = {c.strip(): i for i, c in enumerate(head.split("}"))}
    missing = [c for c in required if c not in ix]
    if missing:
        raise SystemExit("%s: columns %s not in the header %s" % (table, missing, head[:300]))
    return ix, f


def iter_chunks(f, size=1 << 24):
    """Yield lists of complete lines (bytes, newline removed) from a binary stream, 16 MB at a time."""
    rest = b""
    while True:
        buf = f.read(size)
        if not buf:
            break
        lines = (rest + buf).split(b"\n")
        rest = lines.pop()
        yield lines
    if rest.strip():
        yield [rest]


def read_small(zf, table, required):
    ix, f = open_table(zf, table, required)
    rows = []
    with f:
        for lines in iter_chunks(f):
            for ln in lines:
                ln = ln.rstrip(b"\r")
                if ln:
                    rows.append(ln.decode("latin-1").split("}"))
    return ix, rows


# ---------------------------------------------------------------------------------------------------- other inputs
def read_operators(path):
    """(nameable operator number -> CSV name, every operator number in the CSV -> org_type). Reads only number, name,
    type. The CSV is the active P-5 registrants only: it is a cross-check, no longer the naming gate."""
    names, every = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            num = norm_op(r["operator_number"])
            every[num] = r["org_type"]
            if r["org_type"] in ENTITY_TYPES:
                names[num] = r["name"]
    return names, every


def read_p5(path):
    """P-5 Organization file (orf850.txt.gz: ASCII, CRLF, 'A ' records; 1-based positions: operator number 3-8,
    organization name 9-40, P-5 status 42, organization code 45) -> {number: (name, status, organization code)}.
    The name is kept only for the types that may be named (corporation, LLC, limited partnership); nothing else in
    the file (officers, addresses, phones, other record kinds) is read."""
    out = {}
    with gzip.open(path, "rb") as f:
        for raw in f:
            if raw[:2] != b"A ":
                continue
            line = raw.decode("latin-1").rstrip("\r\n").ljust(45)
            num, code = line[2:8], line[44:45]
            if not (len(num) == 6 and num.isdigit()):
                continue
            name = line[8:40].strip() if P5_ORG_TYPES.get(code) in ENTITY_TYPES else ""
            out[num] = (name, line[41:42].strip(), code)
    return out


def read_geo(path):
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    return {x["properties"]["f"]: x["properties"]["n"] for x in feats}


def read_eia(path):
    """month -> EIA Texas crude oil field production in thousand barrels (months without a value are left out)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {m: v for m, v in zip(d["months"], d["txCrude"]) if v is not None}
    except (OSError, ValueError, KeyError):
        return {}


# ---------------------------------------------------------------------------------------------------- PDQ tables
def read_date_range(zf):
    ix, rows = read_small(zf, "GP_DATE_RANGE_CYCLE",
                          ["OLDEST_PROD_CYCLE_YEAR_MONTH", "NEWEST_PROD_CYCLE_YEAR_MONTH", "OIL_EXTRACT_DATE"])
    r = rows[0]
    return (from_ym(r[ix["OLDEST_PROD_CYCLE_YEAR_MONTH"]]), from_ym(r[ix["NEWEST_PROD_CYCLE_YEAR_MONTH"]]),
            r[ix["OIL_EXTRACT_DATE"]].strip())


def read_gp_county(zf):
    """county number -> (FIPS, name, onshore flag)."""
    ix, rows = read_small(zf, "GP_COUNTY", ["COUNTY_NO", "COUNTY_FIPS_CODE", "COUNTY_NAME", "ON_SHORE_FLAG"])
    return {r[ix["COUNTY_NO"]]: (r[ix["COUNTY_FIPS_CODE"]], r[ix["COUNTY_NAME"]], r[ix["ON_SHORE_FLAG"]]) for r in rows}


def read_county_cycle(zf):
    """OG_COUNTY_CYCLE -> ({(county, 'YYYYMM'): [oil, gas]}, {'YYYYMM': [oil, gas]}); oil = crude + condensate,
    gas = gas-well gas + casinghead gas, summed over districts and the O/G codes."""
    need = ["COUNTY_NO", "CYCLE_YEAR_MONTH", "CNTY_OIL_PROD_VOL", "CNTY_COND_PROD_VOL", "CNTY_GAS_PROD_VOL",
            "CNTY_CSGD_PROD_VOL"]
    ix, f = open_table(zf, "OG_COUNTY_CYCLE", need)
    i_c, i_m, i_o, i_k, i_g, i_s = (ix[c] for c in need)
    mx = max(i_c, i_m, i_o, i_k, i_g, i_s)
    cm, st = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    rows = bad = 0
    with f:
        for lines in iter_chunks(f):
            for ln in lines:
                p = ln.rstrip(b"\r").split(b"}", mx + 1)
                if len(p) <= mx:
                    bad += ln.strip() != b""
                    continue
                try:
                    o = int(p[i_o] or 0) + int(p[i_k] or 0)
                    g = int(p[i_g] or 0) + int(p[i_s] or 0)
                except ValueError:
                    bad += 1
                    continue
                rows += 1
                ym = p[i_m].decode()
                a = cm[(p[i_c].decode(), ym)]
                a[0] += o
                a[1] += g
                b = st[ym]
                b[0] += o
                b[1] += g
    return cm, st, rows, bad


def read_district_cycle(zf):
    """OG_DISTRICT_CYCLE -> {'YYYYMM': [oil, gas]} summed over the districts (a third statewide total)."""
    need = ["CYCLE_YEAR_MONTH", "DIST_OIL_PROD_VOL", "DIST_COND_PROD_VOL", "DIST_GAS_PROD_VOL", "DIST_CSGD_PROD_VOL"]
    ix, rows = read_small(zf, "OG_DISTRICT_CYCLE", need)
    st = defaultdict(lambda: [0, 0])
    for r in rows:
        a = st[r[ix["CYCLE_YEAR_MONTH"]].strip()]
        a[0] += int(r[ix["DIST_OIL_PROD_VOL"]] or 0) + int(r[ix["DIST_COND_PROD_VOL"]] or 0)
        a[1] += int(r[ix["DIST_GAS_PROD_VOL"]] or 0) + int(r[ix["DIST_CSGD_PROD_VOL"]] or 0)
    return st


def scan_county_lease(zf, lo, hi, lo24, lo12, hi12):
    """One pass over OG_COUNTY_LEASE_CYCLE (county x lease x month rows). Months lo..hi (bytes 'YYYYMM', inclusive):
    per (county, month) and per month sums, per (operator, month) sums for months >= lo24, the sets of leases
    ('O|district|lease') with production in months lo12..hi12 (the latest 12 complete months) per county and per
    operator, and reporting diagnostics. The months after hi12 up to hi are the incomplete tail: they feed only the
    diagnostics."""
    need = ["OIL_GAS_CODE", "DISTRICT_NO", "LEASE_NO", "COUNTY_NO", "OPERATOR_NO", "CYCLE_YEAR_MONTH",
            "PROD_REPORT_FILED_FLAG", "CNTY_LSE_OIL_PROD_VOL", "CNTY_LSE_GAS_PROD_VOL", "CNTY_LSE_COND_PROD_VOL",
            "CNTY_LSE_CSGD_PROD_VOL"]
    ix, f = open_table(zf, "OG_COUNTY_LEASE_CYCLE", need)
    (i_code, i_dist, i_lse, i_cty, i_op, i_ym, i_flag, i_oil, i_gas, i_cond, i_csgd) = (ix[c] for c in need)
    mx = max(ix[c] for c in need)
    cm_o, cm_g = defaultdict(int), defaultdict(int)          # (county, ym)
    om_o, om_g = defaultdict(int), defaultdict(int)          # (operator, ym), ym >= lo24
    c_leases, o_leases = defaultdict(set), defaultdict(set)  # months lo12..hi12, production > 0
    flags, pos = Counter(), Counter()                        # (ym, flag) rows; ym rows with production
    n_rows = n_win = n_bad = n_neg = 0
    t0 = time.time()
    with f:
        for lines in iter_chunks(f):
            for ln in lines:
                n_rows += 1
                p = ln.split(b"}", mx + 1)
                if len(p) <= mx:
                    n_bad += ln.strip() != b""
                    continue
                ym = p[i_ym]
                if ym < lo or ym > hi:
                    continue
                try:
                    o = int(p[i_oil] or 0) + int(p[i_cond] or 0)
                    g = int(p[i_gas] or 0) + int(p[i_csgd] or 0)
                except ValueError:
                    n_bad += 1
                    continue
                n_win += 1
                cty = p[i_cty]
                cm_o[(cty, ym)] += o
                cm_g[(cty, ym)] += g
                flags[(ym, p[i_flag])] += 1
                if o < 0 or g < 0:
                    n_neg += 1
                op = p[i_op]
                if ym >= lo24:
                    om_o[(op, ym)] += o
                    om_g[(op, ym)] += g
                if o > 0 or g > 0:
                    pos[ym] += 1
                    if lo12 <= ym <= hi12:
                        key = p[i_code] + b"|" + p[i_dist] + b"|" + p[i_lse]
                        c_leases[cty].add(key)
                        o_leases[op].add(key)
            if n_rows % 4_000_000 < len(lines):
                log("  county-lease: %.1f M rows read, %.1f M in window, %.0f s" % (n_rows / 1e6, n_win / 1e6, time.time() - t0))
    return dict(cm_o=cm_o, cm_g=cm_g, om_o=om_o, om_g=om_g, c_leases=c_leases, o_leases=o_leases, flags=flags, pos=pos,
                n_rows=n_rows, n_win=n_win, n_bad=n_bad, n_neg=n_neg)


def scan_operator_cycle(zf, lo, hi, keep):
    """OG_OPERATOR_CYCLE -> per month sums for months lo..hi, per (operator, month) sums for the months in `keep`
    (bytes 'YYYYMM'), plus the latest name per operator (cross-check of the operator numbers against the CSV)."""
    need = ["OPERATOR_NO", "CYCLE_YEAR_MONTH", "OPERATOR_NAME", "OPER_OIL_PROD_VOL", "OPER_GAS_PROD_VOL",
            "OPER_COND_PROD_VOL", "OPER_CSGD_PROD_VOL"]
    ix, f = open_table(zf, "OG_OPERATOR_CYCLE", need)
    i_op, i_ym, i_nm, i_o, i_g, i_k, i_s = (ix[c] for c in need)
    mx = max(ix[c] for c in need)
    om, st = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    name_at = {}
    rows = bad = 0
    with f:
        for lines in iter_chunks(f):
            for ln in lines:
                p = ln.rstrip(b"\r").split(b"}", mx + 1)
                if len(p) <= mx:
                    bad += ln.strip() != b""
                    continue
                ym = p[i_ym]
                if ym < lo or ym > hi:
                    continue
                try:
                    o = int(p[i_o] or 0) + int(p[i_k] or 0)
                    g = int(p[i_g] or 0) + int(p[i_s] or 0)
                except ValueError:
                    bad += 1
                    continue
                rows += 1
                if ym in keep:
                    a = om[(p[i_op], ym)]
                    a[0] += o
                    a[1] += g
                b = st[ym]
                b[0] += o
                b[1] += g
                if o or g:
                    prev = name_at.get(p[i_op])
                    if prev is None or ym >= prev[0]:
                        name_at[p[i_op]] = (ym, p[i_nm].decode("latin-1").strip())
    return om, st, name_at, rows, bad


# ---------------------------------------------------------------------------------------------------- the window
def pick_complete_through(state, eia, newest, min_ratio):
    """Last complete month (see the module docstring) and the RRC / EIA ratio of every month checked."""
    ratios, last_ok = {}, None
    for m in month_list(CHECK_START, newest):
        if m not in eia or to_ym(m) not in state:
            break                                              # EIA has not published it: cannot be verified
        ratio = state[to_ym(m)][0] / 1000.0 / eia[m]
        ratios[m] = ratio
        if ratio < min_ratio:
            break
        last_ok = m
    return last_ok, ratios


# ---------------------------------------------------------------------------------------------------- the run
def run(zf, args):
    t_start = time.time()
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    geo = read_geo(os.path.join(SITE, "public", "data", "counties.geo.json"))
    names, csv_nums = read_operators(os.path.join(ROOT, "rrc_operators.csv"))
    log("counties in counties.geo.json: %d; operators in rrc_operators.csv: %d (nameable %d)"
        % (len(geo), len(csv_nums), len(names)))
    if not os.path.isfile(args.p5):
        raise SystemExit("%s not found: fetch it with rrc_fetch.py %s orf850.txt.gz <new empty folder>" % (args.p5, P5_GUID))
    p5 = read_p5(args.p5)
    entity = {n: (v[0], v[1], P5_ORG_TYPES[v[2]]) for n, v in p5.items() if P5_ORG_TYPES.get(v[2]) in ENTITY_TYPES}
    n_missing = sum(1 for n in csv_nums if n not in p5)
    n_type = sum(1 for n, t in csv_nums.items() if n in p5 and P5_ORG_TYPES.get(p5[n][2], "") != t)
    n_name = sum(1 for n, nm in names.items() if n in entity and entity[n][0] != nm)
    old_only = [n for n in names if n not in entity]
    log("P-5 file: %d organizations, %d corporation / LLC / limited partnership (nameable, by status: %s)"
        % (len(p5), len(entity), ", ".join("%s %d" % kv for kv in sorted(Counter(v[1] for v in entity.values()).items()))))
    log("CHECK P-5 file vs rrc_operators.csv: %d of %d CSV operators missing from the P-5 file, %d type differences, "
        "%d name differences among the %d CSV-nameable, %d of those not nameable by the P-5 rule"
        % (n_missing, len(csv_nums), n_type, n_name, len(names), len(old_only)))
    if old_only or n_missing:
        raise SystemExit("the P-5 file and rrc_operators.csv disagree: refresh one of them")

    oldest, newest, extract = read_date_range(zf)
    gp = read_gp_county(zf)
    odd = [(k, v) for k, v in gp.items() if v[0] != k]
    onshore_bad = [k for k in geo if k not in gp or gp[k][0] != k or gp[k][2] != "Y"]
    log("PDQ production months %s .. %s, extracted %s; GP_COUNTY: %d rows, county number != FIPS for %d, "
        "geo counties not onshore/identical in GP_COUNTY: %d" % (oldest, newest, extract, len(gp), len(odd), len(onshore_bad)))
    name_mismatch = [k for k in geo if k in gp and norm_name(gp[k][1]) != norm_name(geo[k])]
    if name_mismatch:
        log("  county name differences (PDQ vs counties.geo.json): %s"
            % ", ".join("%s %s/%s" % (k, gp[k][1], geo[k]) for k in name_mismatch[:8]))

    log("reading OG_COUNTY_CYCLE")
    cc, cstate, n_cc, bad_cc = read_county_cycle(zf)
    log("  %d rows (%d unreadable); statewide months %s .. %s" % (n_cc, bad_cc, from_ym(min(cstate)), from_ym(max(cstate))))
    state = {ym: v for ym, v in cstate.items() if ym <= to_ym(newest)}

    # ---- which months are complete
    eia = read_eia(args.eia or os.path.join(SITE, "public", "data", "series-markets.json"))
    ratios = {}
    if args.complete_through:
        through = args.complete_through
        how = "set on the command line"
    else:
        through, ratios = pick_complete_through(state, eia, newest, args.min_eia_ratio)
        how = "RRC crude + condensate >= %.0f%% of EIA Texas field production" % (args.min_eia_ratio * 100)
        if through is None:
            through = add_months(newest, -6)
            how = "EIA series unavailable: newest cycle minus 6 months"
    if through > newest:
        raise SystemExit("--complete-through %s is after the newest cycle %s" % (through, newest))
    months36 = month_list(add_months(through, -35), through)
    months24, months12 = months36[12:], months36[24:]
    tail_months = month_list(add_months(through, 1), newest) if newest > through else []
    log("complete through %s (%s); newest cycle %s; %d months left out: %s"
        % (through, how, newest, len(tail_months), ", ".join(tail_months)))

    # ---- county volumes (OG_COUNTY_CYCLE)
    ymset = {m: to_ym(m) for m in months36}
    county_ids = sorted(geo)
    cmo = {c: [cc.get((c, ymset[m]), [0, 0])[0] for m in months36] for c in county_ids}
    cmg = {c: [cc.get((c, ymset[m]), [0, 0])[1] for m in months36] for c in county_ids}
    off_o = [sum(v[0] for (c, ym), v in cc.items() if ym == ymset[m] and c not in geo) for m in months36]
    off_g = [sum(v[1] for (c, ym), v in cc.items() if ym == ymset[m] and c not in geo) for m in months36]

    # ---- the big pass
    lo, hi = to_ym(months36[0]).encode(), to_ym(newest).encode()
    lo24, lo12, hi12 = to_ym(months24[0]).encode(), to_ym(months12[0]).encode(), to_ym(through).encode()
    log("reading OG_COUNTY_LEASE_CYCLE (months %s .. %s)" % (from_ym(lo.decode()), newest))
    cl = scan_county_lease(zf, lo, hi, lo24, lo12, hi12)
    log("  %d rows read, %d in the window, %d unreadable, %d with a negative volume"
        % (cl["n_rows"], cl["n_win"], cl["n_bad"], cl["n_neg"]))

    # ---- cross-check 1: county table vs the lease-level re-sum, every county and month of the window
    win = set(ymset.values())
    a_map = {k: v for k, v in cc.items() if k[1] in win}
    b_map = {}
    for (c, ym), o in cl["cm_o"].items():
        if ym.decode() in win:
            b_map.setdefault((c.decode(), ym.decode()), [0, 0])[0] = o
    for (c, ym), g in cl["cm_g"].items():
        if ym.decode() in win:
            b_map.setdefault((c.decode(), ym.decode()), [0, 0])[1] = g
    diff_cells = diff_o = diff_g = 0
    for k in set(a_map) | set(b_map):
        a, b = a_map.get(k, [0, 0]), b_map.get(k, [0, 0])
        if a != b:
            diff_cells += 1
            diff_o += abs(a[0] - b[0])
            diff_g += abs(a[1] - b[1])
    log("CHECK county table vs county-lease re-sum: %d of %d (county, month) cells differ, abs diff %d bbl, %d mcf"
        % (diff_cells, len(set(a_map) | set(b_map)), diff_o, diff_g))

    # ---- county leases
    leases = {c: len(cl["c_leases"].get(c.encode(), ())) for c in county_ids}

    # ---- operators
    om24 = {}
    for (op, ym), o in cl["om_o"].items():
        om24.setdefault(norm_op(op.decode("latin-1")), {})[ym.decode()] = o
    og24 = {}
    for (op, ym), g in cl["om_g"].items():
        og24.setdefault(norm_op(op.decode("latin-1")), {})[ym.decode()] = g
    op_leases = defaultdict(set)
    for op, s in cl["o_leases"].items():
        op_leases[norm_op(op.decode("latin-1"))] |= s
    log("reading OG_OPERATOR_CYCLE")
    win24 = {ymset[m].encode() for m in months24}
    ocm, ostate, name_at, n_oc, bad_oc = scan_operator_cycle(zf, to_ym(SERIES_START).encode(), hi, win24)
    log("  %d rows in range (%d unreadable); %d operators with a name" % (n_oc, bad_oc, len(name_at)))
    dstate = read_district_cycle(zf)
    oc_by_op = {}
    for (op, ym), v in ocm.items():
        oc_by_op.setdefault(norm_op(op.decode("latin-1")), {})[ym.decode()] = v

    rows_all = []
    for num in sorted(set(om24) | set(og24)):
        mo = [om24.get(num, {}).get(ymset[m], 0) for m in months24]
        mg = [og24.get(num, {}).get(ymset[m], 0) for m in months24]
        rows_all.append((num, mo, mg, len(op_leases.get(num, ()))))

    # cross-check 2: per-operator volumes, county-lease re-sum vs OG_OPERATOR_CYCLE (all operators, 24 months)
    n_op_cmp = n_op_diff = 0
    max_op_diff = 0
    op_diffs = []
    for num, mo, mg, _ in rows_all:
        oc = oc_by_op.get(num, {})
        a_o = sum(mo)
        a_g = sum(mg)
        b_o = sum(oc.get(ymset[m], [0, 0])[0] for m in months24)
        b_g = sum(oc.get(ymset[m], [0, 0])[1] for m in months24)
        n_op_cmp += 1
        if a_o != b_o or a_g != b_g:
            n_op_diff += 1
            max_op_diff = max(max_op_diff, abs(a_o - b_o), abs(a_g - b_g))
            op_diffs.append("%s oil %+d gas %+d (lease-level minus operator table)" % (num, a_o - b_o, a_g - b_g))
    only_oc = [n for n in oc_by_op if n not in om24 and any(v[0] or v[1] for v in oc_by_op[n].values())]
    log("CHECK per-operator volumes, county-lease re-sum vs OG_OPERATOR_CYCLE: %d operators compared, %d differ "
        "(max abs diff %d), %d operators with production only in OG_OPERATOR_CYCLE"
        % (n_op_cmp, n_op_diff, max_op_diff, len(only_oc)))
    for d in op_diffs[:5]:
        log("  differs: " + d)

    named = []
    for num, mo, mg, nl in rows_all:
        ent = entity.get(num)
        if ent is None:
            continue
        o12, o12p, g12, g12p = sum(mo[12:]), sum(mo[:12]), sum(mg[12:]), sum(mg[:12])
        if o12 + g12 <= 0:
            continue
        named.append([num, o12, g12, o12p, g12p, nl, mo, ent[0], ent[1], ent[2]])
    named.sort(key=lambda r: (-r[1], -r[2], r[0]))

    # ---- operator coverage and cross-checks
    producing = [r for r in rows_all if sum(r[1][12:]) + sum(r[2][12:]) > 0]
    prod_in_csv = [r for r in producing if r[0] in csv_nums]
    prod_in_p5 = [r for r in producing if r[0] in p5]
    tot_o12 = sum(sum(r[1][12:]) for r in producing)
    tot_g12 = sum(sum(r[2][12:]) for r in producing)
    named_o12 = sum(r[1] for r in named)
    named_g12 = sum(r[2] for r in named)
    old_o12 = sum(r[1] for r in named if r[0] in names)
    log("CHECK operators with production in the latest 12 months: %d in the dump, %d in rrc_operators.csv (active P-5), "
        "%d in the P-5 file, %d nameable (type rule; by status %s)"
        % (len(producing), len(prod_in_csv), len(prod_in_p5), len(named),
           ", ".join("%s %d" % kv for kv in sorted(Counter(r[8] for r in named).items()))))
    log("  named share of statewide oil %.1f%%, gas %.1f%% (the old rule, active P-5 only: oil %.1f%%)"
        % (100.0 * named_o12 / tot_o12 if tot_o12 else 0, 100.0 * named_g12 / tot_g12 if tot_g12 else 0,
           100.0 * old_o12 / tot_o12 if tot_o12 else 0))
    cmp_names = [(r[0], norm_name(r[7]), norm_name(name_at[r[0].encode()][1])) for r in named if r[0].encode() in name_at]
    same = sum(1 for _, a, b in cmp_names if a == b)
    log("CHECK operator number mapping (dump name vs P-5 name, producing named operators): %d of %d identical after "
        "removing punctuation and case" % (same, len(cmp_names)))
    for n, a, b in [c for c in cmp_names if c[1] != c[2]][:3]:
        log("  differs: %s P-5 %s | dump %s" % (n, a, b))

    # ---- build county-production.json
    counties = {}
    for c in county_ids:
        mo, mg = cmo[c], cmg[c]
        if not any(mo) and not any(mg):
            continue
        counties[c] = {"o12": sum(mo[24:]), "g12": sum(mg[24:]), "o12p": sum(mo[12:24]), "g12p": sum(mg[12:24]),
                       "mo": mo, "mg": mg, "leases": leases[c]}
    src_common = ("Railroad Commission of Texas, Production Data Query Dump (file PDQ_DSV.zip, share "
                  "https://mft.rrc.texas.gov/link/%s, listed at %s, extracted %s, production months %s to %s). "
                  % (GUID, PAGE, extract, oldest, newest))
    meth = ("oil = crude oil (OIL_PROD_VOL) + condensate (COND_PROD_VOL), barrels; gas = gas-well gas (GAS_PROD_VOL) + "
            "casinghead gas (CSGD_PROD_VOL), mcf; leases and gas wells both count as leases. ")
    if args.complete_through:
        window = "Months end at %s (set by the producer)." % through
    else:
        window = ("Months end at %s, the last month in which RRC statewide crude + condensate is at least %.0f%% of "
                  "EIA's Texas field production; later months in the dump are still being reported and are left out "
                  "(statewide figures for them: series-production.json, partial)." % (through, args.min_eia_ratio * 100))
    county_doc = {
        "asOf": args.asof,
        "src": src_common + "Tables OG_COUNTY_CYCLE (monthly volumes by county; RRC allocates multi-county leases to "
               "counties, an estimate per the PDQ manual) and OG_COUNTY_LEASE_CYCLE (distinct leases with production "
               "in the latest 12 months). Counties with no production in the 36 months are omitted; offshore areas "
               "(codes 600-715, no polygon) are in `offshore` (monthly oil and gas) and the statewide series, so "
               "counties + offshore = series-production.json. " + meth + window,
        "unit": UNIT, "completeThrough": through, "newest": newest, "months": months36, "counties": counties,
        "offshore": {"mo": off_o, "mg": off_g}}

    # ---- build operator-production.json (cap to the size budget)
    months_op = months24
    op_doc = {
        "asOf": args.asof,
        "src": src_common + "Tables OG_COUNTY_LEASE_CYCLE (per operator and month, summed over leases and counties; "
               "the operator on each lease-month row) checked against OG_OPERATOR_CYCLE. Named operators: those whose "
               "P-5 organization type is corporation, LLC or limited partnership, whatever their P-5 status "
               "(P-5 Organization file orf850.txt.gz, share https://mft.rrc.texas.gov/link/%s, 'A ' records: "
               "operator number, organization name, status letter, organization code A / H / B); the PDQ "
               "OPERATOR_NO is the same six-digit number. Individuals, sole proprietors, partnerships, trusts, joint "
               "ventures and other types are not listed (their volumes stay in the county and statewide totals). "
               "Columns name, status and type come from that file. Operators with o12 + g12 > 0, by oil descending, "
               "rows beyond the size budget dropped (smallest by oil + gas first). leases = distinct leases with "
               "production in the latest 12 months. producers = all operators with production in the latest 12 "
               "months, nameableShare = the share of statewide oil and gas the nameable ones hold. An operator's "
               "series follows the operator of record month by month, so a step up can be an acquisition, not "
               "drilling. " % P5_GUID + meth + window,
        "unit": UNIT, "completeThrough": through, "months": months_op, "nameableTotal": len(named),
        "producers": len(producing),
        "nameableShare": {"oil": round(named_o12 / tot_o12, 4) if tot_o12 else 0,
                          "gas": round(named_g12 / tot_g12, 4) if tot_g12 else 0},
        "cols": ["num", "o12", "g12", "o12p", "g12p", "leases", "mo", "name", "status", "type"], "rows": []}
    base = len(json.dumps(dict(op_doc, rows=[]), separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + 128
    sizes = [len(json.dumps(r, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + 1 for r in named]
    keep = set(range(len(named)))
    if base + sum(sizes) > BUDGET_OPERATORS:                    # keep the top by oil + gas, list them by oil
        keep, used = set(), base
        for i in sorted(range(len(named)), key=lambda i: (-(named[i][1] + named[i][2]), named[i][0])):
            if used + sizes[i] > BUDGET_OPERATORS:
                break
            used += sizes[i]
            keep.add(i)
    kept = [r for i, r in enumerate(named) if i in keep]
    dropped = [r for i, r in enumerate(named) if i not in keep]
    op_doc["rows"] = kept
    if dropped:
        op_doc["src"] += (" %d further nameable operators (the smallest by oil + gas, at most %d bbl oil and %d mcf "
                          "gas in 12 months) are not listed." % (len(dropped), max(r[1] for r in dropped),
                                                                  max(r[2] for r in dropped)))
    log("operators: %d nameable with production, %d rows kept (%d bytes estimated), %d dropped for size (their oil %d bbl "
        "of %d)" % (len(named), len(kept), base + sum(sizes[i] for i in keep), len(dropped), sum(r[1] for r in dropped),
                    named_o12))

    # ---- build series-production.json
    s_months = month_list(SERIES_START, through)
    eia_pct = []
    for m in month_list(SERIES_START, newest):
        e = eia.get(m)
        eia_pct.append(round(100.0 * (state[to_ym(m)][0] / 1000.0 - e) / e, 2) if e and to_ym(m) in state else None)
    n_main = len(s_months)
    series_doc = {
        "asOf": args.asof,
        "months": s_months,
        "oil": [state[to_ym(m)][0] for m in s_months],
        "gas": [state[to_ym(m)][1] for m in s_months],
        "src": src_common + "Table OG_COUNTY_CYCLE summed over all counties, districts and the O/G codes (offshore "
               "areas included). " + meth + ("Months after %s are in `partial`: reported so far and still being "
                                             "filled in (RRC is below EIA there). `vsEia` = percent difference of "
                                             "oil against EIA's Texas crude field production (series-markets.json "
                                             "txCrude, thousand barrels), null where EIA has no value." % through),
        "unit": UNIT, "completeThrough": through, "newest": newest,
        "vsEia": eia_pct[:n_main],
        "partial": {"months": tail_months, "oil": [state[to_ym(m)][0] for m in tail_months],
                    "gas": [state[to_ym(m)][1] for m in tail_months], "vsEia": eia_pct[n_main:]}}

    # ---- write and verify
    files = {"county-production.json": (county_doc, BUDGET_DEFAULT), "operator-production.json": (op_doc, BUDGET_OPERATORS),
             "series-production.json": (series_doc, BUDGET_DEFAULT)}
    sizes = {}
    for name, (doc, budget) in files.items():
        sizes[name] = write_json(os.path.join(out_dir, name), doc)
        if sizes[name] > budget:
            raise SystemExit("%s is %d bytes, over its %d byte budget" % (name, sizes[name], budget))
    log("wrote: " + ", ".join("%s %d bytes" % (k, v) for k, v in sizes.items()))
    verify(out_dir, args, months36, months24)

    # ---- report
    report(state, eia, newest, through, cl, ostate, dstate, months36, tail_months, counties, named, geo,
           off_o, off_g, ymset)
    log("done in %.0f s" % (time.time() - t_start))


def verify(out_dir, args, months36, months24):
    """CHECK: reload the three files and test the contract (shapes, alignment, sums)."""
    def load(n):
        with open(os.path.join(out_dir, n), encoding="utf-8") as f:
            return json.load(f)
    cd, od, sd = load("county-production.json"), load("operator-production.json"), load("series-production.json")
    assert cd["asOf"] == od["asOf"] == sd["asOf"] == args.asof
    assert cd["months"] == months36 and od["months"] == months24 and len(cd["months"]) == 36 and len(od["months"]) == 24
    for k, c in cd["counties"].items():
        assert re.fullmatch(r"\d{3}", k) and len(c["mo"]) == len(c["mg"]) == 36
        assert c["o12"] == sum(c["mo"][24:]) and c["o12p"] == sum(c["mo"][12:24])
        assert c["g12"] == sum(c["mg"][24:]) and c["g12p"] == sum(c["mg"][12:24]) and c["leases"] >= 0
    assert od["cols"] == ["num", "o12", "g12", "o12p", "g12p", "leases", "mo", "name", "status", "type"]
    prev = None
    for r in od["rows"]:
        assert len(r) == 10 and re.fullmatch(r"\d{6}", r[0]) and len(r[6]) == 24 and r[1] + r[2] > 0
        assert r[1] == sum(r[6][12:]) and r[3] == sum(r[6][:12])
        assert isinstance(r[7], str) and r[7] == r[7].strip() and r[7] and re.fullmatch(r"[A-Z]", r[8])
        assert r[9] in ENTITY_TYPES
        assert prev is None or r[1] <= prev
        prev = r[1]
    assert len({r[0] for r in od["rows"]}) == len(od["rows"])
    assert len(sd["months"]) == len(sd["oil"]) == len(sd["gas"]) == len(sd["vsEia"]) and sd["months"][0] == SERIES_START
    # counties + offshore areas = statewide, month by month
    for i, m in enumerate(months36):
        j = sd["months"].index(m)
        assert sum(c["mo"][i] for c in cd["counties"].values()) + cd["offshore"]["mo"][i] == sd["oil"][j], m
        assert sum(c["mg"][i] for c in cd["counties"].values()) + cd["offshore"]["mg"][i] == sd["gas"][j], m
    assert sd["months"][-1] == sd["completeThrough"] == cd["completeThrough"] == od["completeThrough"]
    log("CHECK files reload and satisfy the contract: counties + offshore areas = statewide for all 36 months")


def report(state, eia, newest, through, cl, ostate, dstate, months36, tail_months, counties, named, geo,
           off_o, off_g, ymset):
    log("---- statewide crude + condensate vs EIA txCrude (million bbl)")
    for m in month_list(add_months(newest, -13), newest):
        ym = to_ym(m)
        if ym not in state:
            continue
        e = eia.get(m)
        log("  %s RRC %7.1f  EIA %s  %s%s" % (m, state[ym][0] / 1e6, ("%7.1f" % (e / 1e3)) if e else "    n/a",
                                              ("%+6.2f%%" % (100.0 * (state[ym][0] / 1e3 - e) / e)) if e else "       ",
                                              "   <- complete" if m == through else ""))
    for first in (SERIES_START, "2024-01"):
        base = [m for m in month_list(first, "2025-06") if m in eia and to_ym(m) in state]
        if base:
            d = [abs(state[to_ym(m)][0] / 1e3 - eia[m]) / eia[m] for m in base]
            log("  %s..2025-06 (%d months): mean |difference| %.2f%%, max %.2f%%"
                % (first, len(base), 100 * sum(d) / len(d), 100 * max(d)))
    log("---- statewide totals: OG_COUNTY_CYCLE vs OG_OPERATOR_CYCLE vs OG_DISTRICT_CYCLE vs county-lease re-sum, "
        "months where they differ")
    nd = 0
    cl_state = defaultdict(lambda: [0, 0])
    for (cty, y), v in cl["cm_o"].items():
        cl_state[y.decode()][0] += v
    for (cty, y), v in cl["cm_g"].items():
        cl_state[y.decode()][1] += v
    for m in month_list(SERIES_START, newest):
        ym = to_ym(m)
        a = state[ym]
        b = ostate.get(ym.encode(), [0, 0])
        d = dstate.get(ym, [0, 0])
        c = cl_state[ym] if m >= months36[0] else None
        if a != b or a != d or (c is not None and a != c):
            nd += 1
            if nd <= 6:
                log("  %s county %s | operator %s | district %s | county-lease %s" % (m, a, b, d, c))
    log("  %d of %d months differ" % (nd, len(month_list(SERIES_START, newest))))
    log("---- reporting diagnostics by month (county-lease rows: filed flag Y / N, rows with production)")
    for m in months36[-14:] + tail_months:
        ym = ymset.get(m, to_ym(m)).encode()
        y, n = cl["flags"].get((ym, b"Y"), 0), cl["flags"].get((ym, b"N"), 0)
        log("  %s rows Y %d N %d (%.1f%% filed), rows with production %d" % (m, y, n, 100.0 * y / (y + n) if y + n else 0,
                                                                          cl["pos"].get(ym, 0)))
    top = sorted(counties.items(), key=lambda kv: -kv[1]["o12"])[:8]
    log("---- top counties by oil, latest 12 months: " + ", ".join("%s %s %.1f M bbl (%d leases)" % (k, geo[k], v["o12"] / 1e6, v["leases"]) for k, v in top))
    topg = sorted(counties.items(), key=lambda kv: -kv[1]["g12"])[:5]
    log("---- top counties by gas: " + ", ".join("%s %s %.0f Bcf" % (k, geo[k], v["g12"] / 1e6) for k, v in topg))
    log("---- top 10 operators by oil (number, name, P-5 status, type, o12 M bbl, g12 Bcf, leases):")
    for r in named[:10]:
        log("  %s | %s | %s | %s | %.1f | %.0f | %d" % (r[0], r[7], r[8], r[9], r[1] / 1e6, r[2] / 1e6, r[5]))
    log("---- offshore areas, complete window: %d bbl oil, %d mcf gas" % (sum(off_o), sum(off_g)))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="D4: RRC production data layers (see the module docstring)")
    ap.add_argument("--dl", default=DEFAULT_DL, help="folder holding the downloads (pdq_dsv/PDQ_DSV.zip)")
    ap.add_argument("--zip", help="path of PDQ_DSV.zip (default <dl>/pdq_dsv/PDQ_DSV.zip)")
    ap.add_argument("--p5", help="P-5 Organization file (default <dl>/p5_orf850/orf850.txt.gz)")
    ap.add_argument("--out", default=os.path.join(SITE, "public", "data"))
    ap.add_argument("--eia", help="series-markets.json (default site/public/data/series-markets.json)")
    ap.add_argument("--asof", default=ASOF)
    ap.add_argument("--complete-through", metavar="YYYY-MM", help="last complete month (default: decided from EIA)")
    ap.add_argument("--min-eia-ratio", type=float, default=MIN_EIA_RATIO)
    ap.add_argument("--testzip", action="store_true", help="first read every member to the end to check its CRC-32")
    args = ap.parse_args(argv)
    if not args.zip:
        args.zip = os.path.join(args.dl, "pdq_dsv", "PDQ_DSV.zip")
    if not args.p5:
        args.p5 = os.path.join(args.dl, "p5_orf850", "orf850.txt.gz")
    return args


def main():
    args = parse_args()
    if not os.path.isfile(args.zip):
        sys.exit("%s not found: fetch it with rrc_fetch.py (see the module docstring)" % args.zip)
    with zipfile.ZipFile(args.zip) as zf:
        if args.testzip:
            t = time.time()
            bad = zf.testzip()
            log("zip CRC test: %s (%.0f s)" % ("all %d members read cleanly" % len(zf.namelist()) if bad is None
                                              else "BAD MEMBER " + bad, time.time() - t))
            if bad is not None:
                sys.exit(1)
        run(zf, args)


if __name__ == "__main__":
    main()
