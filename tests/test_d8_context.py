"""Tests for site/pipeline/d8_ok_context.py: the committed file passes; each deliberate fault is reported; the EIA page parser is checked on a synthetic page."""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import copy, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("ctx", _os.path.join(PIPE, "d8_ok_context.py"))
C = importlib.util.module_from_spec(spec); sys.path.insert(0, PIPE); spec.loader.exec_module(C)
FAILS = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: FAILS.append(msg)
doc = json.load(open(_os.path.join(REPO, "site", "public", "data", "series-ok.json")))
check(C.validate(doc) == [], "the committed series-ok.json is clean: %s" % C.validate(doc))
def faulty(label, fn, expect):
    d = copy.deepcopy(doc); fn(d); probs = C.validate(d)
    check(any(expect in p for p in probs), "validate catches %s (%s)" % (label, "; ".join(probs)[:90] or "NOTHING"))
faulty("a missing key", lambda d: d.pop("release"), "keys are not")
faulty("keys in another order", lambda d: d.update({"months": d.pop("months")}), "keys are not")
faulty("a gap in the months", lambda d: (d["months"].pop(10), d["okCrude"].pop(10)), "months have a gap")
faulty("months not starting at 2019-01", lambda d: (d["months"].pop(0), d["okCrude"].pop(0)), "do not start at 2019-01")
faulty("series and months of different lengths", lambda d: d["okCrude"].pop(), "different lengths")
faulty("a value in the wrong units (per day)", lambda d: d["okCrude"].__setitem__(5, 390), "outside the plausible range")
faulty("a value far too high", lambda d: d["okCrude"].__setitem__(5, 120000), "outside the plausible range")
faulty("no value for the newest month", lambda d: d["okCrude"].__setitem__(-1, None), "newest month has no value")
faulty("`latest` out of step", lambda d: d.update(latest="2026-07"), "newest month has no value or does not match")
faulty("a bad asOf", lambda d: d.update(asOf="yesterday"), "asOf is not a date")
faulty("other units", lambda d: d.update(units={"okCrude": "barrels per day"}), "units or src")
# the parser the Texas pipeline uses reads an Oklahoma page of the EIA's shape, and refuses another series' page
sys.path.insert(0, PIPE)
import d3_markets_infra as D3, tempfile, os
def page(title, rows):
    body = "".join("<tr><td>%s</td>%s</tr>" % (y, "".join("<td>%s</td>" % v for v in vals)) for y, vals in rows)
    hdr = "<tr><td>Year</td>%s</tr>" % "".join("<td>%s</td>" % m for m in D3.MONTHS)
    return "<html><head><title>%s</title></head><body><table>%s%s</table><p>Release Date: 10/30/2026</p></body></html>" % (title, hdr, body)
tmp = tempfile.mkdtemp()
good = os.path.join(tmp, "good.html"); open(good, "w").write(page("Oklahoma Field Production of Crude Oil (Thousand Barrels)", [(2026, ["12,291", "11,524", "11,967", "NA", "", "--", "", "", "", "", "", ""])]))
title, values, release = D3.parse_eia_monthly(good, C.SPEC)
check(values[(2026, 1)] == 12291.0 and values[(2026, 4)] is None and release == "2026-10-30", "the parser reads thousands separators, blanks and the release date")
bad = os.path.join(tmp, "bad.html"); open(bad, "w").write(page("Texas Field Production of Crude Oil (Thousand Barrels)", [(2026, ["1"] * 12)]))
try:
    D3.parse_eia_monthly(bad, C.SPEC); check(False, "a page for another series should be refused")
except SystemExit as e:
    check("unexpected series title" in str(e), "a page for another series (Texas) is refused: %s" % str(e)[:70])
bad2 = os.path.join(tmp, "bad2.html"); open(bad2, "w").write(page("Oklahoma Field Production of Crude Oil (Thousand Barrels per Day)", [(2026, ["1"] * 12)]))
try:
    D3.parse_eia_monthly(bad2, C.SPEC); check(False, "the per-day series should be refused")
except SystemExit as e:
    check("unexpected series title" in str(e), "the per-day series page is refused")
import shutil; shutil.rmtree(tmp)
print(); print("FAILED %d" % len(FAILS) if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
