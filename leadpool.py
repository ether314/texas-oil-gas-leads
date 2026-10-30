#!/usr/bin/env python3
"""Texas oil & gas lead pool from the Comptroller's open franchise-taxpayer data.

Source: data.texas.gov dataset 9cir-efmm ("Active Franchise Taxpayers", Texas Comptroller).
Free Socrata API, no key needed. Set SOCRATA_APP_TOKEN to avoid throttling on big pulls.

  1. NAICS pass: every entity filed under an oil-and-gas NAICS code (self-reported on franchise tax).
  2. Name-match pass: about 80% of entities have no NAICS code at all, so it also pulls active entities with
     no code whose name holds an oil-and-gas word (OILFIELD, PETROLEUM, WIRELINE, ...). DRILLING, PIPELINE and
     WELL SERVICE are weak words (water-well drillers, shell rigs, big midstream subsidiaries), so those rows
     never rate better than `check`.
  3. Adds triage signals for a marketing-services firm: new entity, affiliate cluster at one address,
     trust/family, mineral/royalty and holding/program names.
  4. Writes one CSV (CRM / Apollo / Clay import-ready) and prints a summary.

It lists entities, not people: contact names, emails and phones come from a later enrichment step.
Signals are heuristics on names and addresses, so read `fit_reason` before discarding anything.
Operators with generic names (Diamondback E&P, ...) are in neither pass; rrc_operators.py covers them from RRC data.

  python3 leadpool.py                        # all states, active entities -> leadpool.csv
  python3 leadpool.py --tx-only              # Texas addresses only
  python3 leadpool.py --naics 213112,213111  # override the NAICS list
  python3 leadpool.py --no-name-match        # skip the name-match pass
  python3 leadpool.py --include-inactive     # keep rows whose right-to-transact code is not 'A'
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime

ENDPOINT = "https://data.texas.gov/resource/9cir-efmm.json"
NAICS_FIELD = "_621111"  # the dataset's "NAICS Code" column (odd API field name)
CLUSTER_AT_ADDRESS = 6   # this many pool entities at one address = affiliate group or accountant/agent address
ACTIVE_CODE = "A"        # right_to_transact_business_code; assumed "active" (Comptroller record layout defines it)
FUEL = "Fuel wholesale / terminals"
OFS = "Oilfield services (name match)"
EP = "E&P / oil & gas (name match)"

SEGMENTS = {
    "211120": "E&P (crude)",
    "211130": "E&P (gas)",
    "213111": "Drilling",
    "213112": "Oilfield services",
    "237120": "Pipeline construction",
    "333132": "Equipment manufacturing",
    "486110": "Midstream (crude pipeline)",
    "486210": "Midstream (gas pipeline)",
    "424710": FUEL,
    "424720": FUEL,
}
# name-match pass: (word, segment, weak). Weak words also hit water-well drillers, shell rigs and big midstream
# subsidiaries, so those rows never rate better than `check`.
NAME_WORDS = [
    ("OILFIELD", OFS, False), ("OIL FIELD", OFS, False), ("WIRELINE", OFS, False), ("ROUSTABOUT", OFS, False),
    ("PETROLEUM", EP, False), ("OIL & GAS", EP, False), ("OIL AND GAS", EP, False), ("OIL&GAS", EP, False),
    ("WELL SERVICE", OFS, True), ("DRILLING", "Drilling (name match)", True),
    ("PIPELINE", "Pipeline (name match)", True),
]

LEGAL_SUFFIXES = {"LLC", "LP", "LLP", "LTD", "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LC", "PLLC"}
FLAGS = {
    "flag_trust_family": re.compile(r"\b(TRUST|ESTATE|FAMILY|HEIRS|FOUNDATION)\b"),
    "flag_mineral_royalty": re.compile(r"\b(MINERALS?|ROYALT(?:Y|IES)|OVERRIDING)\b"),
    # holding/finance names, plus drilling-program vehicles ("2008-1", "Employee" funds)
    "flag_holding_spv": re.compile(r"\b(HOLDINGS?|HOLDCO|INTERMEDIATE|FINANCE|FUNDING|CAPITAL|INVESTMENTS?"
                                   r"|EMPLOYEES?|PROGRAM|FUNDS?)\b|\b(?:19|20)\d{2}-\d{1,2}\b"),
}
FIT_RANK = {"likely": 0, "check": 1, "deprioritize": 2}
COLUMNS = [
    "fit", "fit_reason", "new_entity", "segment", "name", "address", "city", "state", "zip",
    "county_code", "naics", "name_match", "org_type_code", "taxpayer_number", "sos_file_number",
    "sos_charter_date", "years_since_charter", "right_to_transact", "sos_status",
    "entities_at_address", "flag_trust_family", "flag_mineral_royalty", "flag_holding_spv",
]


def get_json(params, token, retries=4):
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "User-Agent": "leadpool/1.0"}
    if token:
        headers["X-App-Token"] = token
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def where_clauses(naics, name_match, tx_only, include_inactive):
    state = " AND taxpayer_state='TX'" if tx_only else ""
    out = ["%s in(%s)%s" % (NAICS_FIELD, ",".join('"%s"' % c for c in naics), state)]
    if name_match:
        likes = " OR ".join("upper(taxpayer_name) like '%%%s%%'" % w for w, _, _ in NAME_WORDS)
        active = "" if include_inactive else " AND right_to_transact_business_code='%s'" % ACTIVE_CODE
        out.append("%s IS NULL%s AND (%s)%s" % (NAICS_FIELD, active, likes, state))
    return out


def pull(where, page, cap, token):
    rows = []
    while cap is None or len(rows) < cap:
        take = page if cap is None else min(page, cap - len(rows))
        # a taxpayer can carry two SOS file numbers, so order by both to keep offset paging stable
        order = "taxpayer_number,secretary_of_state_sos_or_coa_file_number"
        batch = get_json({"$where": where, "$order": order, "$limit": take, "$offset": len(rows)}, token)
        rows.extend(batch)
        if len(batch) < take:
            break
    return rows


def norm(text):
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split())


def name_word(upper):
    return next((w for w in NAME_WORDS if w[0] in upper), None)


def parse_date(text):
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def address_key(r):
    addr = norm((r.get("taxpayer_address") or ""))
    return (addr, (r.get("taxpayer_zip") or "")[:5]) if addr else None


def build_row(r, today, new_months, clusters):
    g = lambda k: (r.get(k) or "").strip()
    name = g("taxpayer_name")
    upper = name.upper()
    flags = {k: bool(rx.search(upper)) for k, rx in FLAGS.items()}
    naics = g(NAICS_FIELD)
    word = None if naics else name_word(upper)  # no NAICS code: the row came from the name-match pass
    if naics:
        segment = SEGMENTS.get(naics, "Other (%s)" % naics)
    else:
        segment = word[1] if word else "Other (no NAICS)"
    charter = parse_date(g("sos_charter_date"))
    years = round((today - charter).days / 365.25, 1) if charter else ""
    new = bool(charter) and (today - charter).days <= new_months * 30.44
    key = address_key(r)
    cluster = clusters[key] if key else 1
    active = g("right_to_transact_business_code") == ACTIVE_CODE

    deprioritize, check = [], []
    if not active:
        deprioritize.append("right to transact not '%s'" % ACTIVE_CODE)
    if flags["flag_trust_family"]:
        deprioritize.append("trust/family name")
    if flags["flag_holding_spv"]:
        deprioritize.append("holding/finance/program name")
    if flags["flag_mineral_royalty"]:
        check.append("mineral/royalty name")
    if cluster >= CLUSTER_AT_ADDRESS:
        check.append("%d entities at this address" % cluster)
    if segment == FUEL:
        check.append("fuel wholesale, different buyer")
    if word and word[2]:
        check.append("weak name match: %s" % word[0])
    fit = "deprioritize" if deprioritize else ("check" if check else "likely")

    return {
        "fit": fit, "fit_reason": "; ".join(deprioritize + check), "new_entity": "Y" if new else "",
        "segment": segment, "name": name, "address": g("taxpayer_address"), "city": g("taxpayer_city"),
        "state": g("taxpayer_state"), "zip": g("taxpayer_zip"), "county_code": g("taxpayer_county_code"),
        "naics": naics, "name_match": word[0] if word else "", "org_type_code": g("taxpayer_organizational_type"),
        "taxpayer_number": g("taxpayer_number"),
        "sos_file_number": g("secretary_of_state_sos_or_coa_file_number"),
        "sos_charter_date": charter.isoformat() if charter else "", "years_since_charter": years,
        "right_to_transact": g("right_to_transact_business_code"), "sos_status": g("sos_status_code"),
        "entities_at_address": cluster,
        **{k: "Y" if v else "" for k, v in flags.items()},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="leadpool.csv")
    ap.add_argument("--tx-only", action="store_true", help="Texas taxpayer addresses only")
    ap.add_argument("--include-inactive", action="store_true", help="keep rows whose right-to-transact code is not 'A'")
    ap.add_argument("--no-name-match", action="store_true", help="skip the name-match pass")
    ap.add_argument("--naics", default=",".join(SEGMENTS), help="comma-separated 6-digit NAICS codes")
    ap.add_argument("--new-months", type=int, default=24, help="charter age that counts as a new entity")
    ap.add_argument("--page-size", type=int, default=5000)
    ap.add_argument("--limit", type=int, help="stop after this many rows in total (testing)")
    a = ap.parse_args()

    naics = [c.strip() for c in a.naics.split(",") if c.strip()]
    if not naics or not all(re.fullmatch(r"\d{6}", c) for c in naics):
        sys.exit("--naics takes 6-digit codes, e.g. 213112,213111")

    token = os.environ.get("SOCRATA_APP_TOKEN")
    rows = []
    for where in where_clauses(naics, not a.no_name_match, a.tx_only, a.include_inactive):
        cap = None if a.limit is None else a.limit - len(rows)
        if cap is not None and cap <= 0:
            break
        rows.extend(pull(where, a.page_size, cap, token))
    pulled = len(rows)
    unique = {}
    for r in rows:  # a taxpayer under two SOS file numbers is one company; keep the first
        unique.setdefault(r.get("taxpayer_number") or id(r), r)
    rows = list(unique.values())
    # cluster counts use every pulled row, so inactive affiliates still reveal a shared parent address
    clusters = Counter(k for k in map(address_key, rows) if k)
    today = date.today()
    built = [build_row(r, today, a.new_months, clusters) for r in rows]
    out = [r for r in built if a.include_inactive or r["right_to_transact"] == ACTIVE_CODE]
    out.sort(key=lambda r: (FIT_RANK[r["fit"]], r["new_entity"] != "Y", r["segment"], r["name"]))

    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)

    print("%d rows -> %s  (%d pulled, %d repeat taxpayers, %d dropped as inactive)"
          % (len(out), a.out, pulled, pulled - len(rows), len(rows) - len(out)))
    print("%-34s %7s %7s %7s %7s" % ("segment", "likely", "check", "deprio", "total"))
    for seg in sorted({r["segment"] for r in out}):
        mine = Counter(r["fit"] for r in out if r["segment"] == seg)
        print("%-34s %7d %7d %7d %7d" % (seg, mine["likely"], mine["check"], mine["deprioritize"], sum(mine.values())))
    print("new entities (<=%d months): %d" % (a.new_months, sum(r["new_entity"] == "Y" for r in out)))
    print("top cities:", ", ".join("%s %d" % c for c in Counter(r["city"] for r in out).most_common(8)))


if __name__ == "__main__":
    main()
