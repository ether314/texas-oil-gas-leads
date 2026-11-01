#!/usr/bin/env python3
"""D14b: the county names of Texas, Oklahoma and New Mexico, for the Daily report's permit rows (2026-11-02).

The permit points (`permits.json`, `permits-ok.json`, `permits-nm.json`) carry a county only as its three-digit FIPS code. The report names the county of every row, and the
names are already in the committed county outlines (`us-counties.json`, 3,135 counties, mostly shapes). This writes the 364 names of the three states into a file of their
own, `site/public/data/county-names.json` (about 6 KB), so the page does not fetch 242 KB of shapes to read a name:

  {"v": 1, "source": "...", "states": {"TX": {"001": "Anderson", ...}, "OK": {...}, "NM": {...}}}

The names come without their suffix ("Loving", not "Loving County"), as the FracFocus registry's county names do. The federal offshore has no counties (its permits are in protraction
areas) and is not here.

  python3 -I site/pipeline/d14_county_names.py           writes site/public/data/county-names.json from us-counties.json
  python3 -I site/pipeline/d14_county_names.py --check   reloads what is committed and compares it with what us-counties.json gives
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DATA = os.path.join(SITE, "public", "data")
SRC = os.path.join(DATA, "us-counties.json")
OUT = os.path.join(DATA, "county-names.json")
STATES = {"TX": "48", "OK": "40", "NM": "35"}  # the states whose permit points the Daily report names counties for: id -> the state's FIPS code
EXPECT = {"TX": 254, "OK": 77, "NM": 33}


def build(src=SRC):
    """The document from the county outlines: every county of the three states, keyed by its three-digit code."""
    with open(src, encoding="utf-8") as f:
        counties = json.load(f)["counties"]
    states = {}
    for sid, fips in STATES.items():
        names = {c[0][2:]: c[1] for c in counties if c[0][:2] == fips}
        if len(names) != EXPECT[sid]:
            raise ValueError("%s has %d counties in the outlines, not %d" % (sid, len(names), EXPECT[sid]))
        states[sid] = dict(sorted(names.items()))
    return {"v": 1, "source": "Names of the county outlines in us-counties.json (U.S. Census Bureau, 2023 Gazetteer), without their suffix", "states": states}


def validate(doc):
    p = []
    if not (isinstance(doc, dict) and doc.get("v") == 1 and set(doc) == {"v", "source", "states"} and set(doc["states"]) == set(STATES)):
        return ["not a v1 county-names document for %s" % ", ".join(STATES)]
    for sid, names in doc["states"].items():
        if len(names) != EXPECT[sid]:
            p.append("%s: %d names, not %d" % (sid, len(names), EXPECT[sid]))
        for code, name in names.items():
            if not (re.fullmatch(r"\d{3}", code) and isinstance(name, str) and re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'&-]{1,40}", name)):
                p.append("%s: county %r is not a code and a place name" % (sid, code))
                break
    return p


def write(doc, path=OUT):
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return len(text)


def main(argv):
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as f:
            doc = json.load(f)
        bad = validate(doc) + ([] if doc == build() else ["it is not what us-counties.json gives: run the script again"])
        print("county names: " + ("ok (%d counties)" % sum(len(v) for v in doc["states"].values()) if not bad else "; ".join(bad)))
        return 1 if bad else 0
    doc = build()
    bad = validate(doc)
    if bad:
        print("not written: " + "; ".join(bad))
        return 1
    print("wrote county-names.json (%d bytes, %d counties)" % (write(doc), sum(len(v) for v in doc["states"].values())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
