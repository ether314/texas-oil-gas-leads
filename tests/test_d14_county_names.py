"""Tests for site/pipeline/d14_county_names.py: the county names of Texas, Oklahoma and New Mexico that the Daily report puts on its permit rows.

The permit points carry a county only as a three-digit code. This pins that the file is what the committed county outlines give (364 counties: 254, 77 and 33), that known codes
read as the names the registry uses ("Loving", "Canadian", "Eddy", "Doña Ana"), that every county code in the committed permit points has a name for its state, and that the
validator refuses a wrong count, a bad code, a name with a digit in it, a missing state and an extra key.

Run: python3 -I tests/test_d14_county_names.py"""
import copy
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d14_county_names as N  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


committed = json.load(open(N.OUT, encoding="utf-8"))
check(committed == N.build() and N.validate(committed) == [], "the committed file is what the county outlines give, and it validates: %s" % N.validate(committed)[:2])
check({k: len(v) for k, v in committed["states"].items()} == {"TX": 254, "OK": 77, "NM": 33}, "Texas has 254 counties, Oklahoma 77 and New Mexico 33")
s = committed["states"]
check(s["TX"]["301"] == "Loving" and s["TX"]["329"] == "Midland" and s["TX"]["389"] == "Reeves" and s["OK"]["017"] == "Canadian" and s["NM"]["015"] == "Eddy" and s["NM"]["013"] == "Doña Ana",
      "known codes read as the names the registry uses, without their suffix (Loving, Midland, Reeves, Canadian, Eddy, Doña Ana)")
check(os.path.getsize(N.OUT) < 8000, "the file is small enough to fetch for a name (%d bytes)" % os.path.getsize(N.OUT))

# every permit point's county has a name for its state: the codes in the committed files are the three-digit FIPS codes of the state
for st, f in (("TX", "permits.json"), ("OK", "permits-ok.json"), ("NM", "permits-nm.json")):
    pts = json.load(open(os.path.join(DATA, f), encoding="utf-8"))["pts"]
    gone = sorted({p[5] for p in pts if "%03d" % p[5] not in s[st]})
    check(len(pts) > 1000 and not gone, "every county code of the %d %s permit points is a county of %s (no code without a name: %s)" % (len(pts), f, st, gone))

# the validator against deliberate faults
faults = {
    "a county missing": lambda d: d["states"]["TX"].pop("301"),
    "a code that is not three digits": lambda d: d["states"]["OK"].__setitem__("17", "Canadian"),
    "a name with a digit in it": lambda d: d["states"]["NM"].__setitem__("015", "Eddy 15"),
    "a name that is a street": lambda d: d["states"]["NM"].__setitem__("015", "100 Main Street"),
    "a missing state": lambda d: d["states"].pop("NM"),
    "an extra state": lambda d: d["states"].__setitem__("ND", {}),
    "an extra key": lambda d: d.__setitem__("api", 1),
    "another version": lambda d: d.__setitem__("v", 2),
}
for name, fn in faults.items():
    d = copy.deepcopy(committed)
    fn(d)
    check(N.validate(d) != [], "the validator refuses " + name)

# the builder refuses an outlines file that lacks a county
with tempfile.TemporaryDirectory() as tmp:
    src = json.load(open(N.SRC, encoding="utf-8"))
    src["counties"] = [c for c in src["counties"] if c[0] != "48301"]
    path = os.path.join(tmp, "us-counties.json")
    json.dump(src, open(path, "w"))
    check(raises(lambda: N.build(path)), "a build from outlines that lack Loving County is refused, not written short")
    out = os.path.join(tmp, "county-names.json")
    N.write(committed, out)
    check(json.load(open(out, encoding="utf-8")) == committed and not os.path.exists(out + ".tmp"), "write puts the file in place whole and leaves no temporary file")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
