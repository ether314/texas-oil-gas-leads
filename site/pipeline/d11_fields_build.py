#!/usr/bin/env python3
"""D11: the matrix of what each agency's permit captures: site/pipeline/fields/<ST>.json (researched by hand, one file per jurisdiction) -> site/public/data/permit-fields.json.

The research asks, for every producing state (and the BLM and the federal offshore), the same questions (52 today, `fields/metrics.json`): is this metric asked for on the permit
application, and is it published, as a downloadable data field, in a one-well-at-a-time lookup, or not at all? Each answer is a cell:

  s   data      a field in a downloadable open data file or API (bulk, machine-readable)
      query     on the agency's online lookup or record page, one well at a time, not in a bulk download
      form      asked for on the permit application (so on the filed paper or in the filing system) but not published as data or in a lookup
      none      the permit does not capture it (checked against the form)
      unknown   could not be verified. An honest answer: a wrong `data` is a defect, a wall of `unknown` is not.
  e   file      seen in a real data file's columns or an API schema      doc   the agency's data dictionary or documentation lists it
      form      read on the form                                           web   seen on an agency web page          none  (for `unknown`)
  n   a note of at most 120 characters

Besides the agencies there is one registry, FracFocus (`fields/FF.json`): the national record of fracturing jobs, filed after the job, not a permit. It answers the same 48 questions
about what a disclosure captures, is built into the output beside the agencies (`registries`, never counted as one of them, and shown first in the matrix) and carries a plain-words list of
every field in its download (`registry_fields`, each tied to a permit metric where there is one, each checked against the columns of the real files it lists).

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
REGISTRIES = {"FF": "FracFocus"}  # sources that are not an agency's permit: the same questions, asked of what a disclosure captures (see the module's text)
FIELD_GROUPS = ("well", "where", "job", "water", "chem")  # the groups of a registry's field list, in the order the page shows them
log = C.log


# The research was written by the people (and agents) who did it, in their own voice: "from this machine", "I read", "the tracker", "answered 403 to a HEAD". The page shows
# what was found in a visitor's words, so every string passes through these rewrites on its way into permit-fields.json (the researched files stay as researched).
# Each pair is one phrase the research uses; `tests/test_d11_fields.py` fails if any of the researcher's markers is left in what the page shows.
VOICE = [
    # a whole passage reworded
    ("but every host I tried is blocked from this machine: commerce.alaska.gov answered 403 (HEAD, and the fetch tool) and aogweb.state.ak.us reset the TLS connection. No file, column or approval date was seen, so the brief's 'blocked from here' rule gives D. It would become A or B if one request from the GitHub runner reaches the Data Miner and the Well History export has an approval date.",
     "but its sites refused automated requests when this was researched (commerce.alaska.gov answered 403, and aogweb.state.ak.us reset the secure connection). No file, column or approval date was seen, so it is graded D. It would become A or B if the Data Miner can be reached and its Well History export has an approval date."),
    ("commerce.alaska.gov answered 403 to this machine's HEAD and to the fetch tool, and I did not retry or look for a mirror of the PDF.", "the agency's site (commerce.alaska.gov) refused automated requests (403)."),
    ("Whether aogweb.state.ak.us answers over plain http from this machine (agency links use http://; not tried)", "Whether aogweb.state.ak.us answers over plain http (agency links use http://; not tried)"),
    ("Blocked from here: the agency's site refused this machine (HTTP 403 on a HEAD and on a page fetch), so no data file could be read", "The agency's site refused automated requests when this was researched (HTTP 403), so no data file could be read"),
    ("and answers from a runner.", "and can be fetched automatically."),
    ("Whether the agency host is blocked for the GitHub runner or only for this machine (it answered 403 here to both a HEAD and a page fetch)", "Whether the agency's site refuses GitHub's servers as well (it answered 403 to two kinds of automated request)"),
    ("The agency site answered 403 (a HEAD earlier from this machine, a WebFetch of the downloads page in this pass); no retry and no way round.", "The agency's site answered 403 to automated requests."),
    (", which surfaced in search but was deliberately not fetched; the caller can authorize one fetch.", ", which surfaced in search and was deliberately not requested."),
    ("But the host eec.ky.gov answered this machine's one curl request with 403 (the files only came through WebFetch), and the lists", "But the host eec.ky.gov refused one plain automated request (403) although the files can be fetched another way, and the lists"),
    ("Upgrade to A if a GitHub runner can fetch the xlsx files.", "Upgrade to A if GitHub's servers can fetch the xlsx files."),
    ("NOT READ: michigan.gov answered 403 to the caller's HEAD and to WebFetch GET (no retry, no workaround).", "NOT READ: michigan.gov answered 403 to automated requests."),
    ("the DNR and Secretary of State pages answered 403 from here.", "the DNR and Secretary of State pages answered 403 to automated requests."),
    ("NOT READ. dnr.mo.gov answered HTTP 403 to the one request made to the permit page (not retried), and", "NOT READ. dnr.mo.gov answered 403 to the one request made to the permit page, and"),
    ("(403 on HEAD, not retried)", "(the host answered 403 and was not asked again)"),
    ("(fetched with WebFetch, text extracted with pdftotext; file last modified", "(text extracted; file last modified"),
    ("is blocked by the sandbox proxy.", "could not be reached when this was researched."),
    ("The reachable fragments are", "What could be read is"),
    ("reset every connection from here", "reset every connection when this was researched"),
    ("and a GitHub runner can reach them.", "and GitHub's servers can reach them."),
    ("Whether the commission's site answers from a GitHub runner (it reset the connection from here).", "Whether the commission's site answers GitHub's servers (it reset the connection when asked from elsewhere)."),
    ("reset every connection from this machine, so", "reset every connection, so"),
    ("Every TDEC data host answered 403 to one polite request from this machine (data viewer, map layer, form PDF)", "Every TDEC data site (data viewer, map layer, form PDF) answered 403 to an automated request"),
    ("if a runner can reach them.", "if they can be read automatically."),
    ("The form PDF answered 403 from this machine (one request, not repeated).", "The form PDF answered 403 to an automated request."),
    ("one GET of the form came back HTTP 403 with a Cloudflare 'Just a moment, enable JavaScript and cookies' page; a filed APD on ogviewer.azdeq.gov answered the same way. Not retried and no other route tried, per the brief.", "an automated request for the form came back 403 with a Cloudflare 'Just a moment' page; a filed APD on ogviewer.azdeq.gov answered the same way."),
    ("The KCC's own intents search was blocked (HTTP 403) from here.", "The KCC's own intents search refused automated requests (HTTP 403)."),
    ("since the page returned HTTP 403", "since the page refused automated requests (HTTP 403)"),
    # a phrase
    (", answered 200 from here, hold", ", hold"), ("answered 200 from here, ", ""), ("answered HTTP 200 from here, ", ""), ("answered HTTP 200 today, ", ""), (" and answered from here, ", ", "), ("answered from here, ", ""),
    ("Reachable from here; ", "Open to anyone; "), ("reachable from here", "open to anyone"), ("(the agency's main site answers 404 from here)", "(the agency's main site answers 404)"),
    ("agency file not reachable", "agency file not available"), ("Reachable, free", "Open and free"), ("free, reachable", "free and open"), ("Free, reachable", "Free and open"),
    ("reachable (200)", "open to anyone"), ("reachable", "open to anyone"), ("Reachable", "Open to anyone"),
    (", HTTP 200, same size on a fresh HEAD", ""), ("(HTTP 200, ", "("), ("on my one try", "when tried"), ("I did not re-download it", "it was not downloaded again"),
    ("I read two filed applications", "Two filed applications were read"), ("; I saw no individual's name", "; no individual's name was seen"), ("in what I read", "in what was read"), ("(not read here)", "(not read)"),
    ("so I did not test the KCC site again", "so the KCC site was not tested again"), ("a rename no source I saw confirms", "a rename no source confirms"), ("in the layers or reports I read", "in the layers or reports read"),
    ("could not be driven here", "could not be run automatically"), ("was not scripted here", "was not automated"), ("(it reset the connection from here)", "(it reset the connection when asked from elsewhere)"),
    ("answers 404 here", "answers 404"), ("not openable here", "not openable"), ("unknown here;", "unknown;"), ("(page not readable from here)", "(page not readable)"), ("not copied here", "not copied"), ("copied here", "copied"),
    ("so nothing here is read from the paper form", "so nothing is read from the paper form"), (" (HTTP 200)", ""),
    ("the PDF host answers curl with 403", "the PDF host answers automated requests with 403"), ("Curl got 403 from eec.ky.gov; the PDF came through WebFetch (not retried).", "eec.ky.gov refused one plain automated request (403); the PDF could be fetched another way."),
    ("whether eec.ky.gov serves the xlsx to a runner", "whether eec.ky.gov serves the xlsx to GitHub's servers"), ("come from WebSearch result summaries", "come from web-search result summaries"),
    ("(NOGCC); the brief calls it the Energy and Carbon Management Commission, a rename no source confirms", "(NOGCC); an Energy and Carbon Management Commission is mentioned, a rename no source confirms"),
    ("answers from a CI runner", "answers GitHub's servers"),
    ("the tracker", "this site"), ("The tracker", "This site"),
]
HTTP = re.compile(r"\bHTTP (\d{3})\b")


def vis(text):
    """The research's own words made fit for a visitor (VOICE, in order)."""
    for old, new in VOICE:
        text = text.replace(old, new)
    return HTTP.sub(r"\1", text)


def deep_vis(o):
    """vis() on every string inside a value (the sources' own fields, which are not clipped)."""
    if isinstance(o, str):
        return vis(o)
    if isinstance(o, list):
        return [deep_vis(x) for x in o]
    if isinstance(o, dict):
        return {k: deep_vis(v) for k, v in o.items()}
    return o


def clip(text, n):
    """A string made fit for the page and at most n characters: in a visitor's words (vis), and, when it is too long, cut after a whole sentence if one ends in the
    second half of the room, else after a whole word with an ellipsis. It is never cut in the middle of a word."""
    text = vis(" ".join(str(text or "").split()))
    if len(text) <= n:
        return text
    cut = text[:n - 1]
    end = cut.rfind(". ")
    if end >= n * 0.5:
        return cut[: end + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:") + "…"


def trim_source(s):
    out = {k: s.get(k) for k in ("id", "name", "url", "kind", "format", "grain", "cadence", "history_from", "size_mb", "free", "login", "license", "reachable", "activity_types") if k in s}
    out["name"] = clip(out.get("name"), 200)
    out["columns"] = [clip(c, 80) for c in (s.get("columns") or [])[:60]]
    for k in HAS:
        out[k] = s.get(k)
    return out


def trim_fields(rows):
    return [{"column": r["column"], "label": clip(r["label"], 60), "group": r["group"], "plain": clip(r["plain"], 160), "metric": r.get("metric") or ""} for r in rows]


def trim_state(d):
    cells = {k: [v["s"], v["e"], clip(v.get("n", ""), 120)] for k, v in d["cells"].items()}
    f = d.get("form") or {}
    out = {
        "name": C.NAME_OF.get(d.get("state")) or d["name"], "agency": {k: (clip((d.get("agency") or {}).get(k), 200) if k != "url" else (d.get("agency") or {}).get(k)) for k in ("name", "short", "url")},
        "form": {"name": clip(f.get("name"), 240), "number": clip(f.get("number"), 160), "url": f.get("url") or "", "read": bool(f.get("read")), "notes": clip(f.get("notes"), 700)},
        "cells": cells, "sources": [deep_vis(trim_source(s)) for s in d.get("sources") or []], "grade": d["grade"], "grade_reason": clip(d.get("grade_reason"), 900),
        "producer_plan": clip(d.get("producer_plan"), 1200), "bands": [b for b in d.get("activity_bands_possible") or [] if b in C.BANDS],
        "privacy": clip(d.get("privacy_notes"), 400), "unknowns": [clip(u, 200) for u in (d.get("unknowns") or [])[:10]], "researched": d.get("researched") or "",
    }
    if d.get("state") in REGISTRIES:
        out["kind"] = "registry"
        out["fields"] = trim_fields(d.get("registry_fields") or [])
    return out


def registry_problems(sid, d, keys):
    """A registry's list of fields: each one a real column of a source it lists, every column of those sources in the list once, in a known group, a metric that exists or none."""
    p = []
    rows = d.get("registry_fields")
    if not isinstance(rows, list) or not rows:
        return ["%s: a registry needs registry_fields" % sid]
    cols = [c for s in d.get("sources") or [] for c in s.get("columns") or []]
    seen = set()
    for r in rows:
        c = r.get("column") if isinstance(r, dict) else None
        if not (isinstance(c, str) and c):
            p.append("%s: a field with no column" % sid)
            continue
        if c in seen:
            p.append("%s: field %s is listed twice" % (sid, c))
        seen.add(c)
        if c not in cols:
            p.append("%s: field %s is a column of none of the sources" % (sid, c))
        if r.get("group") not in FIELD_GROUPS:
            p.append("%s: field %s is in no known group" % (sid, c))
        if not (isinstance(r.get("label"), str) and r["label"] and isinstance(r.get("plain"), str) and r["plain"]):
            p.append("%s: field %s needs a label and a plain description" % (sid, c))
        if r.get("metric") and r["metric"] not in keys:
            p.append("%s: field %s names a metric that does not exist" % (sid, c))
    p += ["%s: the column %s of a source is not in the field list" % (sid, c) for c in sorted(set(cols) - seen)]
    return p


def problems_in(sid, d, keys):
    p = []
    ok = lambda c, m: p.append("%s: %s" % (sid, m)) if not c else None  # noqa: E731
    ok(d.get("state") == sid and (sid in C.NAME_OF or sid in REGISTRIES), "the file must name its own jurisdiction")
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
    if sid in REGISTRIES:
        p += registry_problems(sid, d, keys)
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
    registries = [sid for sid in REGISTRIES if sid in docs]
    return {"v": 1, "generated": (today or date.today()).isoformat(), "groups": cat["groups"], "metrics": cat["metrics"], "order": order, "registries": registries,
            "states": {sid: trim_state(docs[sid]) for sid in order + registries}}


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
    regs = doc.get("registries") or []
    if doc["order"] != [sid for sid in doc["order"] if sid in doc["states"]] or set(doc["order"]) | set(regs) != set(doc["states"]) or set(doc["order"]) & set(regs):
        p.append("order, registries and states disagree")
    if any(sid not in REGISTRIES for sid in regs):
        p.append("a registry this site does not carry")
    for sid, s in doc["states"].items():
        if sid not in C.NAME_OF and sid not in REGISTRIES:
            p.append("%s: not a jurisdiction" % sid)
        if sid in regs:
            fs = s.get("fields") or []
            if s.get("kind") != "registry" or not fs:
                p.append("%s: a registry carries its field list" % sid)
            for f in fs:
                if f.get("group") not in FIELD_GROUPS or (f.get("metric") and f["metric"] not in keys):
                    p.append("%s: field %s malformed" % (sid, f.get("column")))
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
