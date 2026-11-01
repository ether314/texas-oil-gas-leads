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

# the committed files
committed = json.load(open(os.path.join(DATA, "permit-fields.json"), encoding="utf-8"))
check(F.validate(committed) == [], "the committed permit-fields.json validates: %s" % F.validate(committed)[:2])
check(F.build(F.SRC, date.fromisoformat(committed["generated"])) == committed, "permit-fields.json is what the builder makes from fields/ (rebuild it after changing a research file)")
nat = json.load(open(os.path.join(DATA, "national.json"), encoding="utf-8"))
check(nat["hasFields"] is True, "national.json knows the matrix file exists (so the national panels link to it)")
check(all(sid in F.C.NAME_OF for sid in committed["order"]), "every researched jurisdiction is one the national report carries")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
