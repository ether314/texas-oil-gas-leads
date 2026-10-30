#!/usr/bin/env python3
"""Join the Texas RRC P-5 operator file and drilling permits to the lead pool.

Inputs are public RRC bulk files (fetch them with rrc_fetch.py) plus the output of leadpool.py:
  --p5       orf850.txt.gz  P-5 Organization, ASCII, 350-char records (A org, K officer, U activity, F specialty)
  --permits  daf802.txt.gz  Drilling Permit Master and Trailer, ASCII, 510-char records (02 = permit master)
  --pool     leadpool.csv

Outputs (written to --out-dir)
  rrc_operators.csv    every active P-5 organization: activity codes, officers (name and title), permit counts
  leadpool_ranked.csv  the lead pool matched to RRC operators by name, ranked by recent drilling activity

Activity bands: A = 10+ new-well permits in the last 12 months, B = 1-9, C = RRC operator with no new-well
permit in 12 months, D = no RRC match (leadpool_ranked.csv only). New-well types are 01 drill, 11 drill direct
sidetrack and 12 drill horizontal; amendments, recompletions and re-entries count only in all_permits.

Layouts come from the RRC manuals ora001 (P-5) and oga049 (permit master); positions below are 1-based as printed
there. Left out on purpose: officer addresses and ID numbers, and officers and phone for anything other than a
corporation, LLC or limited partnership (sole proprietors and the like are individuals).

  python3 rrc_operators.py --p5 orf850.txt.gz --permits daf802.txt.gz
"""
import argparse
import csv
import gzip
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher

NEW_WELL_TYPES = {"01", "11", "12"}
# H is missing from the 2014 manual, but 3,189 of 3,546 active H names end in LLC; I looks like institutions
ORG_TYPES = {"A": "corporation", "B": "limited partnership", "C": "sole proprietor", "D": "partnership",
             "E": "trust", "F": "joint venture", "G": "other", "H": "LLC", "I": "other (code I)"}
ENTITY_TYPES = {"corporation", "limited partnership", "LLC"}  # officers and phone are shown only for these
# the permit file stores districts as internal codes (oga049, DA-OPERATOR-NUMBER section)
DISTRICTS = {"01": "01", "02": "02", "03": "03", "04": "04", "05": "05", "06": "06", "07": "6E", "08": "7B",
             "09": "7C", "10": "08", "11": "8A", "12": "8B", "13": "09", "14": "10"}
LEGAL_SUFFIXES = {"LLC", "LP", "LLP", "LTD", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LC",
                  "PLLC", "LIMITED"}
BAND_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "": 4}
FIT_ORDER = {"likely": 0, "check": 1, "deprioritize": 2}
FUZZY_MIN = 0.88  # name similarity needed when only the ZIP agrees
ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
RRC_COLUMNS = ["rrc_operator_no", "rrc_match", "rrc_zip_agrees", "activity_band", "new_well_permits_12m",
               "all_permits_12m", "all_permits_24m", "first_permit_date", "last_permit_date", "new_to_drilling",
               "top_district_24m", "rrc_activities", "rrc_officers", "rrc_phone"]
OP_COLUMNS = ["activity_band", "operator_number", "name", "org_type", "is_operator", "activity_codes",
              "specialty_codes", "officers", "phone", "address", "city", "state", "zip", "mail_hold",
              "p5_registered", "new_p5_24m", "last_p5_received", "new_well_permits_12m", "all_permits_12m",
              "all_permits_24m", "first_permit_date", "last_permit_date", "new_to_drilling", "top_district_24m"]


def field(line, pos, length):
    return line[pos - 1:pos - 1 + length]


def to_date(text):
    try:
        d = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return d if 1900 <= d.year <= 2100 else None


def norm(name, strip_suffix=True):
    s = name.upper().replace("&", " AND ")
    s = re.sub(r"\bL\.? ?L\.? ?C\b\.?", " LLC ", s)
    s = re.sub(r"\bL\.? ?L\.? ?P\b\.?", " LLP ", s)
    s = re.sub(r"\bL\.? ?P\b\.?", " LP ", s)
    tokens = re.sub(r"[^A-Z0-9 ]", " ", s).split()
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    while strip_suffix and len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def numerals(key):
    return {t for t in key.split() if t.isdigit() or t in ROMAN}


def read_p5(path):
    orgs, officers, activities, specialties = {}, defaultdict(list), defaultdict(set), defaultdict(set)
    with gzip.open(path, "rb") as f:
        for raw in f:
            line = raw.decode("latin-1").rstrip("\r\n").ljust(350)
            kind, num = line[:2], field(line, 3, 6)
            if kind == "A ":
                orgs[num] = {
                    "number": num, "name": field(line, 9, 32).strip(), "status": field(line, 42, 1),
                    "mail_hold": field(line, 43, 1) == "H", "org_type": ORG_TYPES.get(field(line, 45, 1), ""),
                    "address": " ".join((field(line, 71, 31) + " " + field(line, 102, 31)).split()),
                    "city": field(line, 133, 13).strip(), "state": field(line, 146, 2).strip(),
                    "zip": field(line, 148, 5), "phone": field(line, 259, 10).strip(),
                    "registered": to_date(field(line, 243, 8)), "last_p5": to_date(field(line, 295, 8)),
                }
            elif kind == "K ":
                officers[num].append((field(line, 41, 32).strip(), field(line, 73, 32).strip()))
            elif kind == "U ":
                activities[num].add(field(line, 41, 6).strip())
            elif kind == "F ":
                specialties[num].add(field(line, 41, 6).strip())
    return orgs, officers, activities, specialties


def read_permits(path, today):
    cut12, cut24 = today - timedelta(days=365), today - timedelta(days=730)
    stats = defaultdict(lambda: {"new12": 0, "all12": 0, "all24": 0, "first": None, "last": None,
                                 "districts": Counter()})
    seen, counts = set(), Counter()
    with gzip.open(path, "rb") as f:
        for raw in f:
            if raw[:2] != b"02":
                continue
            line = raw.decode("latin-1").rstrip("\r\n")
            permit, op, kind = field(line, 3, 7), field(line, 60, 6), field(line, 66, 2)
            issued = to_date(field(line, 130, 8))
            if not (permit.isdigit() and op.isdigit() and issued):
                counts["skipped (no valid issue date)"] += 1
                continue
            if permit in seen:
                counts["repeat permit numbers"] += 1
                continue
            seen.add(permit)
            counts["permits read"] += 1
            s = stats[op]
            s["first"] = issued if s["first"] is None else min(s["first"], issued)
            s["last"] = issued if s["last"] is None else max(s["last"], issued)
            if issued >= cut24:
                s["all24"] += 1
                code = field(line, 47, 2)
                s["districts"][DISTRICTS.get(code, code)] += 1
                if issued >= cut12:
                    s["all12"] += 1
                    if kind in NEW_WELL_TYPES:
                        s["new12"] += 1
    return stats, counts


def band_for(new12, is_operator, all24):
    if new12 >= 10:
        return "A"
    if new12 >= 1:
        return "B"
    return "C" if is_operator or all24 else ""


def officer_text(people):
    seen, out = set(), []
    for name, title in people:
        key = (name, title)
        if name and key not in seen:
            seen.add(key)
            out.append("%s (%s)" % (name, title) if title else name)
    return "; ".join(out[:6])


def phone_text(org):
    digits = org["phone"]
    if org["org_type"] not in ENTITY_TYPES or len(digits) != 10 or not digits.isdigit() or digits == "0" * 10:
        return ""
    return "%s-%s-%s" % (digits[:3], digits[3:6], digits[6:])


def operator_rows(orgs, officers, activities, specialties, stats, today):
    cut24 = today - timedelta(days=730)
    rows = {}
    for num, o in orgs.items():
        if o["status"] != "A":
            continue
        s = stats.get(num)
        acts = sorted(activities.get(num, ()))
        is_op = any(a.startswith("OPRS") for a in acts)
        new12, all12, all24 = (s["new12"], s["all12"], s["all24"]) if s else (0, 0, 0)
        top = s["districts"].most_common(1)[0][0] if s and s["districts"] else ""
        rows[num] = {
            "activity_band": band_for(new12, is_op, all24), "operator_number": num, "name": o["name"],
            "org_type": o["org_type"], "is_operator": "Y" if is_op else "", "activity_codes": ",".join(acts),
            "specialty_codes": ",".join(sorted(specialties.get(num, ()))),
            "officers": officer_text(officers.get(num, [])) if o["org_type"] in ENTITY_TYPES else "",
            "phone": phone_text(o), "address": o["address"], "city": o["city"], "state": o["state"], "zip": o["zip"],
            "mail_hold": "Y" if o["mail_hold"] else "",
            "p5_registered": o["registered"].isoformat() if o["registered"] else "",
            "new_p5_24m": "Y" if o["registered"] and o["registered"] >= cut24 else "",
            "last_p5_received": o["last_p5"].isoformat() if o["last_p5"] else "",
            "new_well_permits_12m": new12, "all_permits_12m": all12, "all_permits_24m": all24,
            "first_permit_date": s["first"].isoformat() if s else "", "last_permit_date": s["last"].isoformat() if s else "",
            "new_to_drilling": "Y" if s and s["first"] >= cut24 else "", "top_district_24m": top,
        }
    return rows


def match_pool(pool, ops):
    by_exact, by_prefix, by_zip = defaultdict(list), defaultdict(list), defaultdict(list)
    for op in ops.values():
        key = norm(op["name"])
        by_exact[key].append(op)
        by_zip[op["zip"]].append((key, op))
        if len(op["name"]) >= 31:  # P-5 names are cut at 32 characters
            stem = norm(op["name"], strip_suffix=False)
            if len(stem) >= 20:
                by_prefix[stem[:12]].append((stem, op))

    def best(cands):
        return max(cands, key=lambda o: (o["is_operator"] == "Y", o["new_well_permits_12m"], o["all_permits_24m"]))

    found = []
    for r in pool:
        key, full = norm(r["name"]), norm(r["name"], strip_suffix=False)
        zip5 = r["zip"][:5]
        if by_exact.get(key):
            found.append((best(by_exact[key]), "exact"))
            continue
        pre = [o for stem, o in by_prefix.get(full[:12], ()) if full.startswith(stem)]
        if pre:
            found.append((best(pre), "prefix"))
            continue
        # similar names in one ZIP; the first five letters and any numerals (II vs III) must agree
        scored = [(SequenceMatcher(None, key, k).ratio(), o) for k, o in by_zip.get(zip5, ())
                  if zip5 and key.replace(" ", "")[:5] == k.replace(" ", "")[:5] and numerals(key) == numerals(k)]
        top = max(scored, key=lambda t: t[0], default=None)
        found.append((top[1], "fuzzy+zip") if top and top[0] >= FUZZY_MIN else (None, ""))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p5", required=True, help="orf850.txt.gz")
    ap.add_argument("--permits", required=True, help="daf802.txt.gz")
    ap.add_argument("--pool", default="leadpool.csv")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    today = date.today()

    orgs, officers, activities, specialties = read_p5(a.p5)
    stats, counts = read_permits(a.permits, today)
    ops = operator_rows(orgs, officers, activities, specialties, stats, today)
    print("P-5: %d organizations, %d active, %d officer records" % (len(orgs), len(ops), sum(map(len, officers.values()))))
    print("permits:", ", ".join("%s %d" % (k, v) for k, v in counts.items()), "| operators with permits:", len(stats))

    op_list = sorted(ops.values(), key=lambda o: (BAND_ORDER[o["activity_band"]], -o["new_well_permits_12m"],
                                                  -o["all_permits_24m"], o["name"]))
    with open(os.path.join(a.out_dir, "rrc_operators.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OP_COLUMNS)
        w.writeheader()
        w.writerows(op_list)
    print("rrc_operators.csv: %d rows | bands %s" % (len(op_list), dict(sorted(Counter(o["activity_band"] for o in op_list).items()))))

    with open(a.pool, encoding="utf-8") as f:
        pool = list(csv.DictReader(f))
    ranked, kinds = [], Counter()
    for r, (op, how) in zip(pool, match_pool(pool, ops)):
        kinds[how or "none"] += 1
        row = dict(r)
        row.update({c: "" for c in RRC_COLUMNS})
        row["activity_band"] = "D"
        if op:
            row.update({
                "rrc_operator_no": op["operator_number"], "rrc_match": how,
                "rrc_zip_agrees": "Y" if op["zip"] == r["zip"][:5] else "", "activity_band": op["activity_band"] or "C",
                "new_well_permits_12m": op["new_well_permits_12m"], "all_permits_12m": op["all_permits_12m"],
                "all_permits_24m": op["all_permits_24m"], "first_permit_date": op["first_permit_date"],
                "last_permit_date": op["last_permit_date"], "new_to_drilling": op["new_to_drilling"],
                "top_district_24m": op["top_district_24m"], "rrc_activities": op["activity_codes"],
                "rrc_officers": op["officers"], "rrc_phone": op["phone"],
            })
        ranked.append(row)
    ranked.sort(key=lambda r: (BAND_ORDER[r["activity_band"]], -int(r["new_well_permits_12m"] or 0),
                               -int(r["all_permits_12m"] or 0), FIT_ORDER[r["fit"]], r["name"]))
    with open(os.path.join(a.out_dir, "leadpool_ranked.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pool[0].keys()) + RRC_COLUMNS)
        w.writeheader()
        w.writerows(ranked)
    print("leadpool_ranked.csv: %d rows | match %s | bands %s" % (
        len(ranked), dict(kinds), dict(sorted(Counter(r["activity_band"] for r in ranked).items()))))
    print("top 8 matched by new-well permits (12 mo):", "; ".join(
        "%s %s" % (r["name"][:30], r["new_well_permits_12m"]) for r in ranked[:8]))


if __name__ == "__main__":
    main()
