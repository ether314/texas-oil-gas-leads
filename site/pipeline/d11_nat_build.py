#!/usr/bin/env python3
"""D11: merge every state's permit file into site/public/data/national.json, which the National view of the Oil tracker reads.

Inputs, all already committed:
  data/nat/<ST>.json      the normalized files the d11_nat_<st>.py producers write (see d11_nat_common.py for their shape)
  data/series-permits*.json, operators*.json, county-permits*.json, counties*.geo.json
                          Texas, Oklahoma, New Mexico and the federal offshore, built by their own producers (D1, D8, D9, D10) and adapted here:
                          they count `new` only (Texas and Oklahoma by approval date, New Mexico and the offshore by spud date) and say nothing
                          about the other bands, which are published as null
  data/permit-fields.json the research on every agency's permit and open data (optional): a state with no file here still appears, as a gap, with
                          the reason the research found

Output: national.json
  months   one axis, 2019-01 to the newest month any state reaches
  states   one entry per jurisdiction that has data: its own `through`, band arrays padded with null after it, `p12` and `prev12` (its last 12 months
           of `new` against the 12 before: each state's own newest 12 complete months), `mix12` (the last 12 months by band, for the bands it can tell),
           fluid, counties, operators
  gaps     the jurisdictions with no data yet and why (never zero)
  totals   permits and spuds in the last 12 months, added only within a measure

  python3 -I site/pipeline/d11_nat_build.py            rebuild national.json
  python3 -I site/pipeline/d11_nat_build.py --check    reload and validate what is committed
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

DATA = os.path.join(C.SITE, "public", "data")
NAT = os.path.join(DATA, "nat")
OUT = os.path.join(DATA, "national.json")
log = C.log

# the four built earlier: id -> (series, operators, county permits, county names, agency, measure, basis, cadence, source name, source address)
BUILT = {
    "TX": dict(series="series-permits", operators="operators", county="county-permits", geo="counties.geo", agency="Railroad Commission of Texas", measure="permits",
               basis="issue date", cadence="rebuilt by hand", source="Drilling Permit Master and Trailer (application type 01, new drill)", url="https://www.rrc.texas.gov/"),
    "OK": dict(series="series-permits-ok", operators="operators-ok", county="county-permits-ok", geo="counties-ok.geo", agency="Oklahoma Corporation Commission", measure="permits",
               basis="approval date", cadence="weekly", source="Intents to drill (master workbook and the daily file)", url="https://oklahoma.gov/occ.html"),
    "NM": dict(series="series-permits-nm", operators="operators-nm", county="county-permits-nm", geo="counties-nm.geo", agency="Oil Conservation Division", measure="spuds",
               basis="spud date", cadence="weekly", source="Public well layer (Wells_Public)", url="https://www.emnrd.nm.gov/ocd/"),
    "FO": dict(series="series-permits-fo", operators="operators-fo", county="county-permits-fo", geo="counties-fo.geo", agency="Bureau of Safety and Environmental Enforcement", measure="spuds",
               basis="spud date", cadence="weekly", source="Borehole data (the weekly all-releasable file)", url="https://www.bsee.gov/"),
}


def load(name, default=None):
    path = os.path.join(DATA, name + ".json")
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def short_reason(text, n=240):
    """The research's reason for a state's grade, as one or two sentences that fit a table cell (the whole reason is in the permit-fields matrix)."""
    text = " ".join(str(text or "").split())
    out = ""
    for part in re.split(r"(?<=[.!?])\s+", text):
        if len(out) >= 60 and len(out) + len(part) + 1 > n:  # at least a real sentence: "Provisional." alone says nothing
            break
        out = (out + " " + part).strip()
    return out if len(out) <= n + 60 else out[:n].rstrip() + "…"


def adapt(sid, spec):
    """One of the four earlier jurisdictions in the normalized shape (new only; the other bands are not available)."""
    ser = load(spec["series"])
    months = ser["months"]
    new = [int(v) for v in ser["permits"]]
    # series start: the national axis starts at 2019-01
    i0 = months.index(C.FIRST_MONTH) if C.FIRST_MONTH in months else 0
    months, new = months[i0:], new[i0:]
    src = ser.get("src") or ""
    m = re.search(r"through (\d{4}-\d\d-\d\d)", src)
    asof = (m.group(1) if m else None) or ser.get("through") or ser.get("asOf")
    through = C.month_end(months[-1]).isoformat()
    # operators: the files' own 12-month counts, named by the rule already
    ops = load(spec["operators"])
    cols = ops["cols"]
    ni, ci = cols.index("name"), cols.index("new12")
    rows = sorted(((r[ni], r[ci]) for r in ops["rows"] if r[ci] and C.nameable(r[ni])), key=lambda kv: (-kv[1], kv[0]))[:15]
    # counties: the files hold the last 12 months by county code; the geometry file gives the names
    cp, geo = load(spec["county"]), load(spec["geo"])
    names = {f["properties"]["f"]: f["properties"]["n"] for f in geo["features"]}
    cs = sorted(((names.get(k, k), v["p12"]) for k, v in cp["counties"].items() if v.get("p12")), key=lambda kv: (-kv[1], kv[0]))[:15]
    total12 = sum(new[-12:])
    named = sum(n for _, n in rows)
    return {
        "v": 1, "state": sid, "name": C.NAME_OF[sid], "agency": spec["agency"], "measure": spec["measure"], "basis": spec["basis"],
        "source": {"name": spec["source"], "url": spec["url"]}, "asOf": asof, "through": through, "cadence": spec["cadence"],
        "months": months, "bands": {b: (new if b == "new" else None) for b in C.BANDS}, "fluid": None,
        "counties": [[n, c] for n, c in cs], "operators": [[n, c] for n, c in rows],
        "namedShare": round(min(1.0, named / total12), 3) if total12 else None, "read": sum(new),
        "note": {"TX": "The monthly files are rebuilt by hand; the Daily report holds the newest days.", "OK": "", "NM": "Spud dates arrive about two months late, so the series ends two months back.",
                 "FO": "About 45 wells a year; spud dates arrive late."}[sid],
    }


def collect():
    docs = {}
    for sid, spec in BUILT.items():
        try:
            docs[sid] = adapt(sid, spec)
        except (OSError, KeyError, ValueError) as e:
            log("%s: could not adapt (%s); left out" % (sid, e))
    if os.path.isdir(NAT):
        for name in sorted(os.listdir(NAT)):
            if name.endswith(".json"):
                try:
                    doc = json.load(open(os.path.join(NAT, name), encoding="utf-8"))
                except (OSError, ValueError) as e:
                    log("%s: unreadable (%s); left out" % (name, C.privacy_check.clean_error(e, 80)))
                    continue
                bad = C.validate(doc)
                if bad:
                    log("%s: %s; left out" % (name, "; ".join(bad[:2])))
                    continue
                docs[doc["state"]] = doc
    return docs


def build(docs=None, fields=None, today=None):
    docs = docs if docs is not None else collect()
    fields = fields if fields is not None else load("permit-fields", {})
    axis_last = max(d["months"][-1] for d in docs.values())
    months = C.month_list(C.FIRST_MONTH, axis_last)
    states = []
    for sid, _name in C.JURISDICTIONS:
        d = docs.get(sid)
        if not d:
            continue
        pad = len(months) - len(d["months"])
        first_pad = months.index(d["months"][0])  # a state that starts later is padded in front too
        bands = {}
        for b, v in d["bands"].items():
            bands[b] = None if v is None else [None] * first_pad + v + [None] * (pad - first_pad)
        new = d["bands"]["new"]
        p12, prev = sum(new[-12:]), sum(new[-24:-12])
        mix = {b: sum(v[-12:]) for b, v in d["bands"].items() if v is not None}
        states.append({
            "id": sid, "name": d["name"], "agency": d["agency"], "measure": d["measure"], "basis": d["basis"], "source": d["source"], "asOf": d["asOf"],
            "through": d["through"], "cadence": d["cadence"], "bands": bands, "p12": p12, "prev12": prev, "mix12": mix, "fluid": d.get("fluid"),
            "counties": d["counties"], "operators": d["operators"], "namedShare": d.get("namedShare"), "note": d.get("note", ""), "read": d["read"],
            **{k: d[k] for k in ("unit", "place") if d.get(k)},
        })
    have = {s["id"] for s in states}
    fstates = fields.get("states", {}) if isinstance(fields, dict) else {}
    gaps = []
    for sid, name in C.JURISDICTIONS:
        if sid in have:
            continue
        f = fstates.get(sid) or {}
        gaps.append({"id": sid, "name": name, "agency": (f.get("agency") or {}).get("name"), "grade": f.get("grade"),
                     "why": short_reason(f.get("grade_reason")) or "Not read yet: no producer for this agency has been built."})
    addable = [s for s in states if s["id"] not in C.OVERLAP]  # the BLM's onshore permits overlap the states' own: never in a total
    tot = {"permits12": sum(s["p12"] for s in addable if s["measure"] == "permits"), "spuds12": sum(s["p12"] for s in addable if s["measure"] == "spuds"),
           "permitStates": sum(1 for s in addable if s["measure"] == "permits"), "spudStates": sum(1 for s in addable if s["measure"] == "spuds")}
    asof = max(s["asOf"] for s in states) if states else None
    return {"v": 1, "generated": (today or date.today()).isoformat(), "asOf": asof, "hasFields": bool(fstates), "months": months, "states": states, "gaps": gaps, "totals": tot}


def validate(doc):
    p = []
    ok = lambda c, m: p.append(m) if not c else None  # noqa: E731
    ok(isinstance(doc, dict) and doc.get("v") == 1, "not a v1 national file")
    if p:
        return p
    months = doc["months"]
    ok(months == C.month_list(months[0], months[-1]) and months[0] == C.FIRST_MONTH, "months must run without a gap from %s" % C.FIRST_MONTH)
    ids = [s["id"] for s in doc["states"]] + [g["id"] for g in doc["gaps"]]
    ok(sorted(ids) == sorted(i for i, _ in C.JURISDICTIONS), "every jurisdiction must appear once, as a state or a gap")
    for s in doc["states"]:
        for b, v in s["bands"].items():
            ok(v is None or len(v) == len(months), "%s band %s must span the axis" % (s["id"], b))
        new = s["bands"]["new"]
        real = [v for v in new if v is not None]
        ok(s["p12"] == sum(real[-12:]) and s["prev12"] == sum(real[-24:-12]), "%s p12 must be the last 12 real months" % s["id"])
        ok(s["measure"] in C.MEASURES, "%s measure" % s["id"])
        have = [i for i, v in enumerate(new) if v is not None]
        ok(bool(have) and have == list(range(have[0], have[-1] + 1)), "%s: the months with figures must be one unbroken run, with nulls only before it (a state that starts later) and after it (one that ends earlier)" % s["id"])
        for o in s["operators"]:
            ok(C.nameable(o[0]), "%s operator the rule refuses: %s" % (s["id"], C.privacy_check.mask(o[0])))
    t = doc["totals"]
    add = [s for s in doc["states"] if s["id"] not in C.OVERLAP]
    ok(t["permits12"] == sum(s["p12"] for s in add if s["measure"] == "permits") and t["spuds12"] == sum(s["p12"] for s in add if s["measure"] == "spuds"), "totals must add within a measure, never the overlapping lines")
    return p


def main(argv):
    if "--check" in argv:
        doc = json.load(open(OUT, encoding="utf-8"))
        bad = validate(doc) + C.check_dir(NAT)
        for x in bad:
            log(x)
        log("check: " + ("FAILED" if bad else "clean (%d states, %d gaps)" % (len(doc["states"]), len(doc["gaps"]))))
        return 1 if bad else 0
    doc = build()
    bad = validate(doc)
    if bad:
        for x in bad:
            log(x)
        log("not written")
        return 1
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, OUT)
    log("wrote national.json: %d states, %d gaps, %d months, %d bytes" % (len(doc["states"]), len(doc["gaps"]), len(doc["months"]), os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
