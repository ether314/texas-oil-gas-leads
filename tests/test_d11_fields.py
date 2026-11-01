"""Tests for the permit-data matrix: site/pipeline/d11_fields_build.py (fields/<ST>.json, researched by hand -> permit-fields.json).

The research answers 48 questions for every agency; this checks the rules that keep the answers honest: every metric answered, a cell is one of five statuses with evidence that
fits it (`data` only from a real file or the agency's documentation, `unknown` has none), a source is reachable or says why not, grade A needs a reachable per-well source with an
approval date, no e-mail, phone or API-like number, and no state this site does not carry. The validator is run on deliberate faults, the builder on a temporary folder, and mutants put
one rule back each; the committed fields/ and permit-fields.json are checked too.

Run: python3 -I tests/test_d11_fields.py"""
import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
import d11_fields_build as F  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


keys, docs = F.load_sources()
check(len(keys) == 48 and len(set(keys)) == 48, "the catalog holds 48 distinct metrics")
cat = json.load(open(os.path.join(F.SRC, "metrics.json"), encoding="utf-8"))
check({m["group"] for m in cat["metrics"]} <= {g["id"] for g in cat["groups"]}, "every metric is in a group")
check(all(m["label"] and m["help"] for m in cat["metrics"]), "every metric has a label and a help line")

# the baseline: the first researched state, which must itself be clean
sid0 = sorted(docs)[0]
base = docs[sid0]
check(F.problems_in(sid0, base, keys) == [], "%s's research passes the rules: %s" % (sid0, F.problems_in(sid0, base, keys)[:2]))


def broken(fn, sid=sid0):
    d = copy.deepcopy(base)
    fn(d)
    return F.problems_in(sid, d, keys)


def cell(d, k, **kw):
    d["cells"][k].update(kw)


k0 = keys[0]
faults = {
    "a missing metric": lambda d: d["cells"].pop(k0),
    "an extra metric": lambda d: d["cells"].__setitem__("invented", {"s": "data", "e": "file", "n": ""}),
    "a status that is not one": lambda d: cell(d, k0, s="maybe"),
    "evidence that is not one": lambda d: cell(d, k0, e="rumor"),
    "data with no file or documentation behind it": lambda d: cell(d, k0, s="data", e="form"),
    "unknown with evidence": lambda d: cell(d, k0, s="unknown", e="file"),
    "a cell with a status and no evidence": lambda d: cell(d, k0, s="form", e="none"),
    "a note over 120 characters": lambda d: cell(d, k0, n="x" * 121),
    "a grade that is not one": lambda d: d.__setitem__("grade", "E"),
    "grade A with nothing reachable": lambda d: (d.__setitem__("grade", "A"), [s.update(reachable="blocked-403") for s in d["sources"]]),
    "an agency with no address": lambda d: d["agency"].__setitem__("url", ""),
    "an http source": lambda d: d["sources"][0].__setitem__("url", "http://example.gov/x"),
    "a reachability that is not one": lambda d: d["sources"][0].__setitem__("reachable", "mostly"),
    "an e-mail address in the notes": lambda d: d["form"].__setitem__("notes", "write joe@example.com"),
    "a phone number in the plan": lambda d: d.__setitem__("producer_plan", "call 701-555-0100"),
    "an API number in a note": lambda d: cell(d, k0, n="well 33105012340000"),
}
for name, fn in faults.items():
    check(broken(fn), "the rules refuse " + name)
check(broken(lambda d: None, "ZZ"), "the rules refuse a jurisdiction this site does not carry")

# the builder, on a temporary folder
with tempfile.TemporaryDirectory() as tmp:
    shutil.copy(os.path.join(F.SRC, "metrics.json"), tmp)
    names = {"KS": "Kansas", "ND": "North Dakota", "BL": "Federal onshore (BLM)"}
    for sid in ("KS", "ND", "BL"):
        d = copy.deepcopy(base)
        d["state"], d["name"] = sid, names[sid]
        if sid == "KS":
            d["cells"][k0].update(s="data", e="file", n="a column of the bulk file")
        json.dump(d, open(os.path.join(tmp, sid + ".json"), "w"))
    out = F.build(tmp, date(2026, 10, 31))
    check(F.validate(out) == [] and out["order"] == ["BL", "KS", "ND"], "the builder orders jurisdictions as the site lists them (the BLM before the states): %s" % out["order"])
    check(set(out["states"]) == {"KS", "ND", "BL"} and all(len(s["cells"]) == 48 for s in out["states"].values()), "every state carries all 48 cells")
    check(out["states"]["KS"]["cells"][k0] == ["data", "file", "a column of the bulk file"], "a cell is [status, evidence, note]")
    check(all(len(s["producer_plan"]) <= 1200 and len(s["grade_reason"]) <= 900 for s in out["states"].values()), "long text is clipped")
    os.remove(os.path.join(tmp, "ND.json"))
    bad = copy.deepcopy(base)
    bad["state"] = "ND"
    bad["cells"].pop(k0)
    json.dump(bad, open(os.path.join(tmp, "ND.json"), "w"))
    try:
        F.build(tmp)
        check(False, "the builder refuses a state with a missing metric")
    except ValueError:
        check(True, "the builder refuses a state with a missing metric and writes nothing")

# the output's own validator
good = F.build(F.SRC, date(2026, 10, 31))
check(F.validate(good) == [], "the output validates: %s" % F.validate(good)[:2])
for name, fn in {
    "a cell with an unknown status": lambda o: o["states"][o["order"][0]]["cells"][k0].__setitem__(0, "maybe"),
    "a state missing from the order": lambda o: o["order"].pop(),
    "a metric in no group": lambda o: o["metrics"][0].__setitem__("group", "nowhere"),
    "an e-mail address": lambda o: o["states"][o["order"][0]].__setitem__("grade_reason", "mail me@x.org"),
}.items():
    o = copy.deepcopy(good)
    fn(o)
    check(F.validate(o), "the output validator refuses " + name)

# mutants


def mutant(name, patch, probe):
    spec = importlib.util.spec_from_file_location("m_" + name, os.path.join(PIPE, "d11_fields_build.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    patch(m)
    check(probe(m), "mutant '%s' is noticed" % name)


bad_data = copy.deepcopy(base)
bad_data["cells"][k0].update(s="data", e="form")
mutant("any evidence will do for data", lambda m: setattr(m, "EVIDENCE", ("file", "doc", "form", "web", "none")) or setattr(m, "CODES", ("data",)), lambda m: m.problems_in(sid0, bad_data, keys) != F.problems_in(sid0, bad_data, keys))
mutant("the privacy scan is blind", lambda m: setattr(m.privacy_check, "scan", lambda t, digits=False: []), lambda m: not m.problems_in(sid0, copy.deepcopy(dict(base, producer_plan="call 701-555-0100")), keys))

# the page's words: the researchers' voice is rewritten and a long string is cut at a sentence or a word, never in the middle of one
check(F.clip("short text", 100) == "short text" and F.clip("  spaced\n out  ", 100) == "spaced out", "clip: a string that fits is kept (whitespace made plain)")
long_text = "First sentence is here. Second sentence follows it and goes on for a good while longer than the room."
cut = F.clip(long_text, 40)
check(cut == "First sentence is here." and not cut.endswith("…"), "clip: when a sentence ends in the second half of the room the string ends there, whole: %r" % cut)
cut = F.clip("one two three four five six seven eight nine ten eleven twelve", 30)
check(cut.endswith("…") and cut[:-1] in "one two three four five six seven eight nine ten eleven twelve" and cut[:-1].split()[-1] in ("one two three four five six seven eight nine ten eleven twelve").split() and len(cut) <= 30, "clip: otherwise after a whole word, with an ellipsis, in the room (%r)" % cut)
check(all(len(F.clip("word " * 80, n)) <= n for n in (20, 57, 120, 200)) and F.clip("x" * 500, 40).endswith("…") and len(F.clip("x" * 500, 40)) <= 40, "clip: never over its room, even for a string with no space")
check(F.clip("I tried from this machine and the tracker answered 403 to a HEAD", 200) != "I tried from this machine and the tracker answered 403 to a HEAD" and "this site" in F.clip("the tracker names it", 99) and "This site" in F.clip("The tracker names it", 99), "clip: the researchers' words go through the visitor rewrites (the tracker becomes this site)")
check(F.vis("a free, reachable ArcGIS layer") == "a free and open ArcGIS layer" and F.vis("Reachable from here; its counts") == "Open to anyone; its counts" and F.vis("answered HTTP 403") == "answered 403", "vis: the common phrases are made plain")

# the committed files
committed = json.load(open(os.path.join(DATA, "permit-fields.json"), encoding="utf-8"))
check(F.validate(committed) == [], "the committed permit-fields.json validates: %s" % F.validate(committed)[:2])
check(F.build(F.SRC, date.fromisoformat(committed["generated"])) == committed, "permit-fields.json is what the builder makes from fields/ (rebuild it after changing a research file)")
import re  # noqa: E402
VOICE = re.compile(r"\b(I (?:read|saw|did|tried|made|found|looked|have|could|can|will|would|was|am|think|checked|used|ran|fetched|opened|asked|requested)\b|I'\w+|my\b|this machine|from here|here\b|sandbox|polite\w*|(?-i:HEAD)\b|HTTP \d{3}|reachable|answered \d+ (?:from|today)|the tracker|WebFetch|WebSearch|the brief|GitHub runner|CI runner|curl)", re.I)
left = []


def walk(o, path):
    if isinstance(o, str):
        m = VOICE.search(o)
        if m and not path.endswith("/producer_plan"):  # the plan is research notes for a producer, not shown on the page
            left.append((path, m.group(0)))
    elif isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + "/%d" % i)


walk(committed["states"], "")
check(not left, "no string the matrix page shows has the researchers' voice left in it (%d found: %s)" % (len(left), left[:3]))
check(committed["states"]["FO"]["name"] == F.C.NAME_OF["FO"] and all(st["name"] == F.C.NAME_OF.get(sid, F.REGISTRIES.get(sid)) for sid, st in committed["states"].items()), "each jurisdiction has one name, the National report's, in the matrix too (a registry its own)")
nat = json.load(open(os.path.join(DATA, "national.json"), encoding="utf-8"))
check(nat["hasFields"] is True, "national.json knows the matrix file exists (so the national panels link to it)")
check(all(sid in F.C.NAME_OF for sid in committed["order"]), "every researched jurisdiction is one the national report carries")

# the registry (FracFocus): the same 48 questions about what a disclosure captures, kept apart from the agencies, with the list of every field in its download
ff = docs["FF"]
check(F.problems_in("FF", ff, keys) == [], "FracFocus's research passes the rules: %s" % F.problems_in("FF", ff, keys)[:2])
check(committed["registries"] == ["FF"] and "FF" not in committed["order"] and "FF" in committed["states"] and committed["states"]["FF"]["kind"] == "registry", "FracFocus is a registry in the file: not one of the agencies in `order`, and its state says what it is")
check(len(committed["order"]) == 35 and all("kind" not in committed["states"][sid] for sid in committed["order"]), "the 35 agencies are still the agencies, and none of them is marked a registry")
real_cols = {c for src in ff["sources"] for c in src["columns"]}
check(len(real_cols) == 34 and {f["column"] for f in committed["states"]["FF"]["fields"]} == real_cols, "every column of the registry's three kinds of file is in the field list once, and nothing else (34 columns)")
check(set(real_cols) >= {"APINumber", "TVD", "TotalBaseWaterVolume", "CASNumber", "MassIngredient", "WaterSourceId"}, "the columns are the ones the registry's own data dictionary lists (read from the real files on 2026-11-01)")
ffc = committed["states"]["FF"]["cells"]
check(all(ffc[k][0] == "data" for k in ("api_number", "surface_latlon", "proposed_depth_tvd", "water", "county", "operator_name", "well_name")) and ffc["spud_date"][0] == "none" and ffc["completion_date"][0] == "none" and ffc["date_approved"][0] == "none" and ffc["permit_number"][0] == "none",
      "FracFocus: the job's dates are not a spud or completion date and a disclosure has no permit number or approval date, so those cells say not captured")
check(all(f["metric"] == "" or f["metric"] in keys for f in committed["states"]["FF"]["fields"]) and all(ffc[f["metric"]][0] == "data" for f in committed["states"]["FF"]["fields"] if f["metric"]), "a field matches a permit metric only where FracFocus's own cell for that metric says data")
check(ff["grade"] in ("A", "B", "C", "D") and ff["researched"] == "2026-11-01" and not ff["form"]["url"].startswith("http:"), "FracFocus carries a grade, the day it was researched and an https form address")


def broken_ff(fn):
    d = copy.deepcopy(ff)
    fn(d)
    return F.problems_in("FF", d, keys)


reg_faults = {
    "a registry with no field list": lambda d: d.pop("registry_fields"),
    "a field that is a column of no source": lambda d: d["registry_fields"].append({"column": "Invented", "label": "x", "group": "chem", "plain": "x", "metric": ""}),
    "a column of a source left out of the field list": lambda d: d["registry_fields"].pop(0),
    "a field listed twice": lambda d: d["registry_fields"].append(dict(d["registry_fields"][0])),
    "a field in no known group": lambda d: d["registry_fields"][0].__setitem__("group", "elsewhere"),
    "a field that matches a metric that does not exist": lambda d: d["registry_fields"][0].__setitem__("metric", "invented"),
    "a field with no plain description": lambda d: d["registry_fields"][0].__setitem__("plain", ""),
}
for name, fn in reg_faults.items():
    check(broken_ff(fn), "the rules refuse " + name)
check(not F.problems_in("OK", copy.deepcopy(docs["OK"]), keys), "an agency needs no field list")

with tempfile.TemporaryDirectory() as tmp:
    shutil.copy(os.path.join(F.SRC, "metrics.json"), tmp)
    for sid in ("KS", "FF"):
        d = copy.deepcopy(base if sid == "KS" else ff)
        if sid == "KS":
            d["state"], d["name"] = "KS", "Kansas"
        json.dump(d, open(os.path.join(tmp, sid + ".json"), "w"))
    out = F.build(tmp, date(2026, 11, 1))
    check(F.validate(out) == [] and out["order"] == ["KS"] and out["registries"] == ["FF"] and set(out["states"]) == {"KS", "FF"}, "the builder keeps a registry apart from the agencies: order %s, registries %s" % (out["order"], out["registries"]))
    check(out["states"]["FF"]["kind"] == "registry" and len(out["states"]["FF"]["fields"]) == 34 and "kind" not in out["states"]["KS"] and "fields" not in out["states"]["KS"], "only the registry carries `kind` and its field list")
good_reg = copy.deepcopy(committed)
for name, fn in {
    "a registry that is also in the order": lambda o: o["order"].append("FF"),
    "a registry this site does not carry": lambda o: (o["registries"].append("ZZ"), o["states"].__setitem__("ZZ", copy.deepcopy(o["states"]["FF"]))),
    "a registry with no field list": lambda o: o["states"]["FF"].__setitem__("fields", []),
    "a registry field in no known group": lambda o: o["states"]["FF"]["fields"][0].__setitem__("group", "elsewhere"),
    "a registry field that matches a metric that does not exist": lambda o: o["states"]["FF"]["fields"][0].__setitem__("metric", "invented"),
    "a state in neither the order nor the registries": lambda o: o["registries"].pop(),
}.items():
    o = copy.deepcopy(good_reg)
    fn(o)
    check(F.validate(o), "the output validator refuses " + name)
mutant("the field list is not checked against the sources", lambda m: setattr(m, "registry_problems", lambda sid, d, keys: []), lambda m: not m.problems_in("FF", copy.deepcopy(dict(ff, registry_fields=ff["registry_fields"][1:])), keys))

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
