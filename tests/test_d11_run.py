"""Tests for site/pipeline/d11_nat_run.py: the runner that runs every state's producer (d11_nat_<st>.py), each isolated, then rebuilds national.json.

Fake producers (small scripts written to a temporary folder, run exactly as the weekly workflow runs real ones: python3 -I, in their own process) cover what an agency can do: give
good data, give the same data again, write a file and then fail, hang, refuse the runner, leave a file that does not validate, or see a token it must not have. The runner must restore
a failed producer's file exactly (or remove it), leave the others alone, stay within its budget, rebuild national.json from what survived, and exit non-zero only for a real failure
(a refusal is an answer, not an error). Mutants put the old behavior back.

Run: python3 -I tests/test_d11_run.py"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_build as B  # noqa: E402
import d11_nat_common as C  # noqa: E402
import d11_nat_run as R  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


TEMPLATE = '''import os, sys, time
sys.path.insert(0, %(pipe)r)
import d11_nat_common as C
from datetime import date

ST, MODE = %(st)r, %(mode)r


def build():
    t = C.Tally(ST, bands=("new",), fluid=False)
    d = date(2019, 1, 15)
    while d <= date(2026, 10, 15):
        t.add(d, "new", county="Williams", operator="ACME OIL LLC")
        if %(scale)d > 1:
            for _ in range(%(scale)d - 1):
                t.add(d, "new", county="Williams", operator="ACME OIL LLC")
        d = date(d.year + (d.month == 12), d.month %% 12 + 1, 15)
    return t.document(agency="A Commission", source_name="Permit file", source_url="https://example.gov/x", basis="approval date", cadence="weekly", asof=date(2026, 10, 15))


if MODE == "good":
    sys.exit(C.run_producer(ST, build))
if MODE == "write_then_fail":
    C.run_producer(ST, build)
    print("the second half of the run broke")
    sys.exit(1)
if MODE == "hang":
    time.sleep(120)
if MODE == "refused":
    sys.exit(C.run_producer(ST, lambda: (_ for _ in ()).throw(C.Refused("HTTP 403"))))
if MODE == "garbage":
    open(os.path.join(C.OUT, ST + ".json"), "w").write("{not a state file")
    sys.exit(0)
if MODE == "nothing":
    sys.exit(0)
if MODE == "token":
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        print("I can see a token")
        sys.exit(1)
    sys.exit(C.run_producer(ST, build))
'''


def make_producer(folder, st, mode, scale=1):
    with open(os.path.join(folder, "d11_nat_%s.py" % st.lower()), "w") as f:
        f.write(TEMPLATE % {"pipe": PIPE, "st": st, "mode": mode, "scale": scale})


tmp = tempfile.mkdtemp(prefix="d11-run-")
prod, nat, out = os.path.join(tmp, "producers"), os.path.join(tmp, "nat"), os.path.join(tmp, "national.json")
os.makedirs(prod)
os.makedirs(nat)

# ------------------------------------------------------------------------------------------------ discovery
for name in ("d11_nat_common.py", "d11_nat_build.py", "d11_nat_run.py", "d11_nat_zz.py", "d11_nat_ak.txt", "d9_nm_monthly.py", "d11_nat_ND.py"):
    open(os.path.join(prod, name), "w").write("# not a producer\n")
for st in ("KS", "AK", "ND"):
    make_producer(prod, st, "good")
found = R.producers(prod)
check(list(found) == ["AK", "KS", "ND"] or list(found) == [sid for sid, _ in C.JURISDICTIONS if sid in ("AK", "KS", "ND")],
      "producers are found by file name, in the order the site lists jurisdictions, and the common, build and run modules and odd names are not producers: %s" % list(found))
os.remove(os.path.join(prod, "d11_nat_ak.py"))
os.remove(os.path.join(prod, "d11_nat_ks.py"))
os.remove(os.path.join(prod, "d11_nat_nd.py"))
for name in list(os.listdir(prod)):
    os.remove(os.path.join(prod, name))

# ------------------------------------------------------------------------------------------------ one producer at a time
env_nat = {"D11_NAT_DIR": nat}


def one(st, mode, timeout=60, scale=1):
    make_producer(prod, st, mode, scale)
    return R.run_one(st, os.path.join(prod, "d11_nat_%s.py" % st.lower()), nat, timeout)


r = one("AK", "good")
check(r["status"] == "wrote" and os.path.exists(os.path.join(nat, "AK.json")) and C.check_dir(nat) == [], "a good producer writes its file, and the file validates: %s" % r)
first = open(os.path.join(nat, "AK.json"), "rb").read()
r = one("AK", "good")
check(r["status"] == "unchanged", "the same data again changes nothing: %s" % r["status"])
r = one("AK", "write_then_fail", scale=3)
check(r["status"] == "failed" and open(os.path.join(nat, "AK.json"), "rb").read() == first and "exit 1" in r["note"], "a producer that writes a file and then fails has its file put back exactly as it was: %s" % r)
r = one("AL", "write_then_fail")
check(r["status"] == "failed" and not os.path.exists(os.path.join(nat, "AL.json")), "a producer that fails before it ever had a file leaves no file behind")
r = one("AZ", "hang", timeout=3)
check(r["status"] == "timeout" and r["seconds"] < 30 and not os.path.exists(os.path.join(nat, "AZ.json")), "a producer that hangs is stopped at its limit and leaves nothing: %.1f s" % r["seconds"])
r = one("AK", "refused")
check(r["status"] == "refused" and open(os.path.join(nat, "AK.json"), "rb").read() == first, "a refused producer is not an error and its committed file stays: %s" % r["status"])
r = one("AR", "garbage")
check(r["status"] == "invalid" and not os.path.exists(os.path.join(nat, "AR.json")), "a producer that leaves a file that does not validate has it removed: %s" % r["status"])
open(os.path.join(nat, "CA.json"), "wb").write(first.replace(b'"state":"AK"', b'"state":"CA"'))
before_ca = open(os.path.join(nat, "CA.json"), "rb").read()
r = one("CA", "garbage")
check(r["status"] == "invalid" and open(os.path.join(nat, "CA.json"), "rb").read() == before_ca, "an invalid file replaces nothing: the earlier CA file is back")
r = one("CO", "nothing")
check(r["status"] == "failed" and "no file" in r["note"], "exit 0 with no file written is a failure, not a success")
os.environ["GH_TOKEN"] = "secret-token"
os.environ["GITHUB_TOKEN"] = "secret-token"
r = one("CO", "token")
check(r["status"] == "wrote", "a producer holds no repository token (it parses downloaded files): %s" % r)
del os.environ["GH_TOKEN"], os.environ["GITHUB_TOKEN"]

# ------------------------------------------------------------------------------------------------ a whole run
shutil.rmtree(nat)
os.makedirs(nat)
for name in os.listdir(prod):
    os.remove(os.path.join(prod, name))
for st, mode in (("AK", "good"), ("AL", "write_then_fail"), ("AZ", "refused"), ("CA", "garbage"), ("KS", "good")):
    make_producer(prod, st, mode)
code = R.main([], folder=prod, nat_dir=nat, out=out)
check(code == 1, "a run in which a producer failed exits 1 (so the workflow shows red)")
check(sorted(os.listdir(nat)) == ["AK.json", "KS.json"], "only the producers that succeeded left files: %s" % sorted(os.listdir(nat)))
doc = json.load(open(out))
check({s["id"] for s in doc["states"]} >= {"AK", "KS", "TX", "OK", "NM", "FO"} and B.validate(doc) == [], "national.json was rebuilt from what survived, with the four earlier jurisdictions")
check(next(g for g in doc["gaps"] if g["id"] == "AL")["id"] == "AL" and "AL" not in {s["id"] for s in doc["states"]}, "a state whose producer failed is a gap, not a zero")

# a run where nothing failed, including a refusal, exits 0
for name in os.listdir(prod):
    os.remove(os.path.join(prod, name))
for st, mode in (("AK", "good"), ("AZ", "refused")):
    make_producer(prod, st, mode)
check(R.main([], folder=prod, nat_dir=nat, out=out) == 0, "good and refused producers exit 0: a refusal is an answer, not an error")
check(R.main(["--only", "ak"], folder=prod, nat_dir=nat, out=out) == 0, "--only runs the named producers")

# the budget
for name in os.listdir(prod):
    os.remove(os.path.join(prod, name))
make_producer(prod, "AK", "good")
make_producer(prod, "KS", "hang")
code = R.main(["--budget", "10"], folder=prod, nat_dir=nat, out=out)
check(code == 1, "producers that cannot start with time left are skipped, and the run exits 1")

# rebuild failure: national.json is put back
good_out = open(out, "rb").read()
real_validate = B.validate
B.validate = lambda d: ["boom"]
why = R.rebuild(nat, out)
B.validate = real_validate
check(why and "boom" in why and open(out, "rb").read() == good_out, "a national.json that cannot be rebuilt is left as it was, and the reason is returned")
check(R.rebuild(nat, out) is None, "and rebuilds when it can")

# ------------------------------------------------------------------------------------------------ mutants
spec = importlib.util.spec_from_file_location("m_run", os.path.join(PIPE, "d11_nat_run.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.restore = lambda path, before: None
shutil.rmtree(nat)
os.makedirs(nat)
make_producer(prod, "AK", "good")
m.run_one("AK", os.path.join(prod, "d11_nat_ak.py"), nat, 60)
good_bytes = open(os.path.join(nat, "AK.json"), "rb").read()
make_producer(prod, "AK", "write_then_fail", 3)
m.run_one("AK", os.path.join(prod, "d11_nat_ak.py"), nat, 60)
check(open(os.path.join(nat, "AK.json"), "rb").read() != good_bytes, "mutant 'a failed producer's file is not restored' is noticed")
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)
os.environ["GH_TOKEN"] = "secret-token"
orig_run = m2.subprocess.run
seen = {}
m2.subprocess.run = lambda *a, **k: (seen.update(env=k.get("env")), orig_run(*a, **k))[1]
make_producer(prod, "KS", "good")
m2.run_one("KS", os.path.join(prod, "d11_nat_ks.py"), nat, 60)
del os.environ["GH_TOKEN"]
check("GH_TOKEN" not in (seen.get("env") or {}), "the producer's environment has no token (checked on the real runner)")

shutil.rmtree(tmp, ignore_errors=True)
print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
