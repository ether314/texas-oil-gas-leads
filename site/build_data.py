#!/usr/bin/env python3
"""Build the website's JSON data from the lead CSVs, keeping business-level public-record fields only.

Reads rrc_operators.csv and leadpool_ranked.csv from the folder above this one and writes public/data/*.json.
Left out on purpose: street addresses, officer names, phone numbers, SOS and taxpayer numbers, and every row for a
sole proprietor or other non-entity registrant, a trust/family name or a deprioritized name.

  python3 build_data.py
"""
import csv
import json
import os
import re
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)  # the lead CSVs sit one folder up
OUT = os.path.join(HERE, "public", "data")
ENTITY_TYPES = {"corporation", "limited partnership", "LLC"}
# refresh dates read off the source pages on 2026-10-29; update them when the CSVs are rebuilt
SOURCE_DATES = {"p5": "2026-10-22", "permits": "2026-10-08", "comptroller": "2026-10-24"}

OP_COLS = ["band", "num", "name", "type", "city", "state", "zip", "new12", "all12", "all24", "last", "dist",
           "roles", "specialties", "newDrill", "newP5"]
CO_COLS = ["fit", "band", "seg", "name", "city", "state", "zip", "naics", "word", "isNew", "yrs", "new12", "all12",
           "match", "rrcNum", "reason"]


CITY_OK = re.compile(r"[A-Za-z][A-Za-z .'&-]{1,29}")  # a place name; the Comptroller's city field has held a street address (one row, found by a review)


def place(city):
    """The city as published: a place name, or blank when the source field holds anything else (a street, a number)."""
    c = " ".join((city or "").split())
    return c if CITY_OK.fullmatch(c) else ""


def count(text):
    return int(text) if text and text.isdigit() else 0


def read(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(name, payload):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)


def main():
    os.makedirs(OUT, exist_ok=True)
    op_src, co_src = read("rrc_operators.csv"), read("leadpool_ranked.csv")

    operators = [[r["activity_band"], r["operator_number"], r["name"], r["org_type"], place(r["city"]), r["state"], r["zip"],
                  count(r["new_well_permits_12m"]), count(r["all_permits_12m"]), count(r["all_permits_24m"]),
                  r["last_permit_date"], r["top_district_24m"], r["activity_codes"], r["specialty_codes"],
                  1 if r["new_to_drilling"] == "Y" else 0, 1 if r["new_p5_24m"] == "Y" else 0]
                 for r in op_src if r["org_type"] in ENTITY_TYPES]
    companies = [[r["fit"], r["activity_band"], r["segment"], r["name"], place(r["city"]), r["state"], r["zip"][:5],
                  r["naics"], r["name_match"], 1 if r["new_entity"] == "Y" else 0, r["years_since_charter"],
                  count(r["new_well_permits_12m"]), count(r["all_permits_12m"]), r["rrc_match"],
                  r["rrc_operator_no"], r["fit_reason"]]
                 for r in co_src if r["fit"] != "deprioritize"]

    meta = {
        "built": date.today().isoformat(),
        "sources": dict(SOURCE_DATES, latest_permit=max(r["last_permit_date"] for r in op_src if r["last_permit_date"])),
        "operators": {
            "registered": len(op_src), "shown": len(operators),
            "bands": dict(sorted(Counter(r[0] for r in operators if r[0]).items())),
            "newToDrilling": sum(r[14] for r in operators),
        },
        "companies": {
            "pool": len(co_src), "shown": len(companies),
            "bySegment": Counter(r[2] for r in companies).most_common(),
            "fit": dict(Counter(r[0] for r in companies)),
            "newEntities": sum(r[9] for r in companies),
            "texas": sum(1 for r in companies if r[5] == "TX"),
            "matched": sum(1 for r in companies if r[13]),
        },
    }
    write("operators.json", {"cols": OP_COLS, "rows": operators})
    write("companies.json", {"cols": CO_COLS, "rows": companies})
    write("meta.json", meta)
    for name in ("operators.json", "companies.json", "meta.json"):
        print("%-16s %6d KB" % (name, os.path.getsize(os.path.join(OUT, name)) // 1024))
    print("operators shown %d of %d | companies shown %d of %d" % (len(operators), len(op_src), len(companies), len(co_src)))
    print(json.dumps(meta["operators"]), json.dumps({k: v for k, v in meta["companies"].items() if k != "bySegment"}))


if __name__ == "__main__":
    main()
