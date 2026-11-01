#!/usr/bin/env python3
"""D11: the matrix of what each agency's permit captures: site/pipeline/fields/<ST>.json (researched by hand, one file per jurisdiction) -> site/public/data/permit-fields.json.

The research asks, for every producing state (and the BLM and the federal offshore), the same 48 questions (`fields/metrics.json`): is this metric asked for on the permit
application, and is it published, as a downloadable data field, in a one-well-at-a-time lookup, or not at all? Each answer is a cell:

  s   data      a field in a downloadable open data file or API (bulk, machine-readable)
      query     on the agency's online lookup or record page, one well at a time, not in a bulk download
      form      asked for on the permit application (so on the filed paper or in the filing system) but not published as data or in a lookup
      none      the permit does not capture it (checked against the form)
      unknown   could not be verified. An honest answer: a wrong `data` is a defect, a wall of `unknown` is not.
  e   file      seen in a real data file's columns or an API schema      doc   the agency's data dictionary or documentation lists it
      form      read on the form                                           web   seen on an agency web page          none  (for `unknown`)
  n   a note of at most 120 characters

A state also carries its agency, its form (name, number, link), its sources (what is published, in what format, how often, how far back, whether this machine could reach it), a grade
(A: bulk, free, reachable, with a permit approval date, so monthly counts can be built; B: bulk but only spud, completion or filing dates; C: query forms, reports or aggregates;
D: nothing public, blocked or paid), a plain-words producer plan and what could not be determined.

  python3 -I site/pipeline/d11_fields_build.py            rebuild permit-fields.json from fields/
  python3 -I site/pipeline/d11_fields_build.py --check    reload and validate what is committed
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import privacy_check  # noqa: E402

SRC = os.path.join(HERE, "fields")
OUT = os.path.join(C.SITE, "public", "data", "permit-fields.json")
CODES = ("data", "query", "form", "none", "unknown")
EVIDENCE = ("file", "doc", "form", "web", "none")
GRADES = ("A", "B", "C", "D")
REACH = ("ok", "blocked-403", "blocked-proxy", "timeout", "not-tested")
KINDS = ("bulk", "api", "map", "query", "report", "none")
HAS = ("has_approval_date", "has_spud_date", "has_well_type", "has_work_type", "has_location")
log = C.log


def clip(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def trim_source(s):
    out = {k: s.get(k) for k in ("id", "name", "url", "kind", "format", "grain", "cadence", "history_from", "size_mb", "free", "login", "license", "reachable", "activity_types") if k in s}
    out["name"] = clip(out.get("name"), 200)
    out["columns"] = [clip(c, 80) for c in (s.get("columns") or [])[:60]]
    for k in HAS:
        out[k] = s.get(k)
    return out


def trim_state(d):
    cells = {k: [v["s"], v["e"], clip(v.get("n", ""), 120)] for k, v in d["cells"].items()}
    f = d.get("form") or {}
    return {
        "name": d["name"], "agency": {k: clip((d.get("agency") or {}).get(k), 200) for k in ("name", "short", "url")},
        "form": {"name": clip(f.get("name"), 240), "number": clip(f.get("number"), 160), "url": f.get("url") or "", "read": bool(f.get("read")), "notes": clip(f.get("notes"), 700)},
        "cells": cells, "sources": [trim_source(s) for s in d.get("sources") or []], "grade": d["grade"], "grade_reason": clip(d.get("grade_reason"), 900),
        "producer_plan": clip(d.get("producer_plan"), 1200), "bands": [b for b in d.get("activity_bands_possible") or [] if b in C.BANDS],
        "privacy": clip(d.get("privacy_notes"), 400), "unknowns": [clip(u, 200) for u in (d.get("unknowns") or [])[:10]], "researched": d.get("researched") or "",
    }


def problems_in(sid, d, keys):
    p = []
    ok = lambda c, m: p.append("%s: %s" % (sid, m)) if not c else None  # noqa: E731
    ok(d.get("state") == sid and sid in C.NAME_OF, "the file must name its own jurisdiction")
    ok(d.get("grade") in GRADES, "grade must be one of A to D")
    ag = d.get("agency") or {}
    ok(isinstance(ag.get("name"), str) and ag["name"] and str(ag.get("url", "")).startswith("https://"), "agency needs a name and an https address")
    f = d.get("form") or {}
    ok(isinstance(f.get("name"), str) and f["name"], "form needs a name")
    ok(not f.get("url") or str(f["url"]).startswith("https://"), "the form's address must be https")
    cells = d.get("cells") or {}
    ok(set(cells) == set(keys), "cells must hold exactly the %d metrics (missing %s, extra %s)" % (len(keys), sorted(set(keys) - set(cells))[:3], sorted(set(cells) - set(keys))[:3]))
    for k, v in cells.items():
        if not isinstance(v, dict) or v.get("s") not in CODES or v.get("e") not in EVIDENCE:
            p.append("%s: cell %s must have s in %s and e in %s" % (sid, k, CODES, EVIDENCE))
            continue
        ok(len(str(v.get("n", ""))) <= 120, "cell %s: the note is over 120 characters" % k)
        if v["s"] == "data":
            ok(v["e"] in ("file", "doc"), "cell %s: data needs evidence from a file or the agency's documentation" % k)
        elif v["s"] == "unknown":
            ok(v["e"] == "none", "cell %s: unknown has no evidence" % k)
        else:
            ok(v["e"] != "none", "cell %s: %s needs evidence" % (k, v["s"]))
    srcs = d.get("sources")
    ok(isinstance(srcs, list), "sources must be a list")
    for s in srcs or []:
        ok(str(s.get("url", "")).startswith("https://"), "source %s: an https address" % s.get("id"))
        ok(s.get("reachable") in REACH, "source %s: reachable must be one of %s" % (s.get("id"), REACH))
        ok(s.get("kind") in KINDS, "source %s: kind must be one of %s" % (s.get("id"), KINDS))
    if d.get("grade") == "A":
        ok(any(s.get("has_approval_date") is True and s.get("reachable") == "ok" and s.get("grain") in ("well", "permit") for s in srcs or []), "grade A needs a reachable per-well or per-permit source with an approval date")
    if d.get("grade") in ("A", "B"):
        ok(any(s.get("kind") in ("bulk", "api", "map") and s.get("reachable") == "ok" for s in srcs or []), "grade %s needs a reachable bulk, API or map source" % d.get("grade"))
    text = re.sub(r"https?://[^\s\"'<>)\]]+", "", json.dumps(d, ensure_ascii=False))
    for what in privacy_check.scan(text, digits=True):
        p.append("%s: the research holds %s" % (sid, what))
    return p


def load_sources(src=SRC):
    keys = [m["key"] for m in json.load(open(os.path.join(src, "metrics.json"), encoding="utf-8"))["metrics"]]
    docs = {}
    for name in sorted(os.listdir(src)):
        if name.endswith(".json") and name != "metrics.json":
            docs[name[:-5]] = json.load(open(os.path.join(src, name), encoding="utf-8"))
    return keys, docs


def build(src=SRC, today=None):
    cat = json.load(open(os.path.join(src, "metrics.json"), encoding="utf-8"))
    keys, docs = load_sources(src)
    bad = [x for sid, d in docs.items() for x in problems_in(sid, d, keys)]
    if bad:
        raise ValueError("; ".join(bad[:6]))
    order = [sid for sid, _ in C.JURISDICTIONS if sid in docs]
    return {"v": 1, "generated": (today or date.today()).isoformat(), "groups": cat["groups"], "metrics": cat["metrics"], "order": order, "states": {sid: trim_state(docs[sid]) for sid in order}}


def validate(doc):
    p = []
    if not (isinstance(doc, dict) and doc.get("v") == 1):
        return ["not a v1 permit-fields file"]
    keys = [m["key"] for m in doc["metrics"]]
    gids = {g["id"] for g in doc["groups"]}
    if any(m["group"] not in gids for m in doc["metrics"]):
        p.append("a metric is in no group")
    if len(set(keys)) != len(keys):
        p.append("duplicate metric keys")
    if doc["order"] != [sid for sid in doc["order"] if sid in doc["states"]] or set(doc["order"]) != set(doc["states"]):
        p.append("order and states disagree")
    for sid, s in doc["states"].items():
        if sid not in C.NAME_OF:
            p.append("%s: not a jurisdiction" % sid)
        if set(s["cells"]) != set(keys):
            p.append("%s: cells do not match the metrics" % sid)
        for k, v in s["cells"].items():
            if not (isinstance(v, list) and len(v) == 3 and v[0] in CODES and v[1] in EVIDENCE and len(v[2]) <= 121):
                p.append("%s: cell %s malformed" % (sid, k))
        if s["grade"] not in GRADES:
            p.append("%s: grade" % sid)
    text = re.sub(r"https?://[^\s\"'<>)\]]+", "", json.dumps(doc, ensure_ascii=False))
    p += ["the file holds " + w for w in privacy_check.scan(text, digits=True)]
    return p


def main(argv):
    if "--check" in argv:
        doc = json.load(open(OUT, encoding="utf-8"))
        bad = validate(doc)
        for x in bad:
            log(x)
        log("check: " + ("FAILED" if bad else "clean (%d states, %d metrics)" % (len(doc["states"]), len(doc["metrics"]))))
        return 1 if bad else 0
    try:
        doc = build()
    except ValueError as e:
        log("not written: %s" % privacy_check.clean_error(e, 900))
        return 1
    bad = validate(doc)
    if bad:
        log("not written: " + "; ".join(bad[:4]))
        return 1
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, OUT)
    log("wrote permit-fields.json: %d states, %d metrics, %d bytes" % (len(doc["states"]), len(doc["metrics"]), os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
