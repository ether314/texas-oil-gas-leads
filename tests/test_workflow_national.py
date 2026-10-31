"""Tests for .github/workflows/refresh-national.yml: the weekly run that reads every state agency's permits (site/pipeline/d11_nat_run.py), rebuilds national.json, commits and publishes.

The structure (after the monthly files, in the nightly capture's concurrency group so the two never run at once, every step isolated and bounded, only the national files ever committed),
the `if:` conditions for every outcome, and the workflow's own `run:` scripts executed against a throwaway clone with a local bare repo as `origin`: the drop step restores
national.json and removes new state files, the commit step commits the national files (new ones included) and nothing else, pushes them, says so when nothing changed, and the last step
fails the run. The producers are not run here (they read public servers); test_d11_run.py covers the runner and test_d11_nat.py the files.

Needs git and PyYAML. Run: python3 -I tests/test_workflow_national.py
"""
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


WF = os.path.join(REPO, ".github", "workflows")
wf = yaml.safe_load(open(os.path.join(WF, "refresh-national.yml")))
monthly = yaml.safe_load(open(os.path.join(WF, "refresh-monthly.yml")))
nightly = yaml.safe_load(open(os.path.join(WF, "daily-rrc-report.yml")))
job = wf["jobs"]["refresh"]
steps = {s.get("name"): s for s in job["steps"] if s.get("name")}
by_id = {s["id"]: s for s in job["steps"] if s.get("id")}
names = [s.get("name") or s.get("uses") for s in job["steps"]]
RUN, BUILD, CHECK = "Read every state agency's permits", "Rebuild the national report's file", "Check the national files"
DROP, COMMIT, PUBLISH, LAST = "Drop the national files if their check failed", "Commit the new files", "Publish the site to GitHub Pages", "Fail the run if a producer or a check failed"
NAT = "site/public/data/nat"
NATIONAL = "site/public/data/national.json"


def hm(cron):
    m, h = cron.split()[:2]
    return int(h) * 60 + int(m)


# ---- structure
check(wf[True]["schedule"] == [{"cron": "20 6 * * 1"}] and "workflow_dispatch" in wf[True], "it runs on Mondays at 06:20 UTC and by hand")
check(hm(wf[True]["schedule"][0]["cron"]) > hm(monthly[True]["schedule"][0]["cron"]) + 20 and wf[True]["schedule"][0]["cron"].split()[-1] == monthly[True]["schedule"][0]["cron"].split()[-1],
      "it runs after the monthly files (same day, at least 20 minutes later), because national.json reads them")
check(wf["concurrency"]["group"] == nightly["concurrency"]["group"] and wf["concurrency"]["cancel-in-progress"] is False, "it shares the nightly capture's concurrency group: the two never run at once, neither cancels the other")
check(wf["permissions"] == {"contents": "write"}, "it can commit and nothing else")
check(all(by_id[i].get("continue-on-error") is True for i in ("nat_run", "nat_build", "nat_check")), "the producers, the rebuild and the check are continue-on-error: the commit and publish still happen for what succeeded")
check(by_id["tools"].get("continue-on-error") is True and by_id["tools"].get("timeout-minutes", 99) <= 6 and "poppler-utils" in steps["Install the tool that reads PDF reports"]["run"] and names.index("Install the tool that reads PDF reports") < names.index(RUN),
      "poppler (for the BLM's PDF reports) is installed first, with its own short limit, and a failed install cannot stop the run")
check(by_id["nat_run"].get("timeout-minutes", 0) >= 30 and by_id["nat_run"]["timeout-minutes"] + 10 <= job["timeout-minutes"], "the producers have a limit that leaves the job room to check, commit and publish")
budget = int(re.search(r"--budget (\d+)", steps[RUN]["run"]).group(1))
check(budget / 60 < by_id["nat_run"]["timeout-minutes"], "the runner's own budget (%d s) ends before the step's limit, so it stops cleanly and does not get cut off" % budget)
check(names.index(RUN) < names.index(BUILD) < names.index(CHECK) < names.index(DROP) < names.index(COMMIT) < names.index(PUBLISH) < names.index(LAST), "run, rebuild, check, drop, commit, publish, and the failing step last")
runs = {k: steps[k]["run"] for k in steps if "run" in steps[k]}
check("d11_nat_run.py" in runs[RUN] and "d11_nat_build.py" in runs[BUILD] and "d11_nat_build.py --check" in runs[CHECK] and all(re.search(r"python3 -I ", runs[k]) for k in (RUN, BUILD, CHECK)), "each step runs its own script, isolated (python3 -I)")
adds = re.findall(r"git add (.+)", runs[COMMIT])
check(adds == [NAT + " " + NATIONAL], "the commit adds the national files and nothing else: %s" % adds)
check(not re.search(r"git add (-A|\.|--all)", runs[COMMIT]), "it never adds everything")
check(os.path.exists(os.path.join(REPO, NATIONAL)), "national.json, which it commits, is the file the National view reads")


def cond(name, outcomes, cancelled=False):
    expr = steps[name]["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ").replace("!cancelled()", "(not cancelled)")
    py = re.sub(r"steps\.(\w+)\.outcome", r"outcomes['\1']", py)
    return eval(py, {"outcomes": outcomes, "cancelled": cancelled})


good = True
for r, b, c in itertools.product(["success", "failure"], repeat=3):
    o = {"nat_run": r, "nat_build": b, "nat_check": c}
    good &= (cond(DROP, o) == (c == "failure") and cond(LAST, o) == ("failure" in (r, b, c)) and cond(LAST, o, True) is False and cond(BUILD, o, True) is False and cond(CHECK, o, True) is False
             and cond(BUILD, o) is True and cond(CHECK, o) is True)
check(good, "all 8 outcome combinations: the drop runs exactly when the check failed; the last step runs when anything failed and never when cancelled; rebuild and check run unless cancelled")

# ---- a throwaway clone with a local bare origin, made from the tracked files as they are now
TMP = tempfile.mkdtemp()
W, ORIGIN = os.path.join(TMP, "work"), os.path.join(TMP, "origin.git")


def git(*a, cwd=W):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *a], cwd=cwd, capture_output=True, text=True).stdout.strip()


def sh(script, env=None, cwd=W):
    e = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", TMP)}
    e.update(env or {})
    r = subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=e, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


os.makedirs(W)
tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True).stdout.decode().split("\0")
for f in tracked:
    if f and os.path.isfile(os.path.join(REPO, f)):
        os.makedirs(os.path.dirname(os.path.join(W, f)) or W, exist_ok=True)
        shutil.copy2(os.path.join(REPO, f), os.path.join(W, f))
git("init", "-q", "-b", "main")
git("add", "-A")
git("commit", "-q", "-m", "base")
subprocess.run(["git", "clone", "-q", "--bare", W, ORIGIN], check=True)
git("remote", "add", "origin", ORIGIN)
git("fetch", "-q", "origin")
git("branch", "--set-upstream-to=origin/main", "main")
check(git("status", "--short") == "", "the clone starts clean, as an Actions checkout does")

# a good week: a new state file and a rebuilt national.json
os.makedirs(os.path.join(W, NAT), exist_ok=True)
open(os.path.join(W, NAT, "AK.json"), "w").write("{}")
open(os.path.join(W, NATIONAL), "a").write(" ")
check(len(git("status", "--short").splitlines()) == 2, "the clone now has a new state file and a changed national.json")
code, out = sh(steps[DROP]["run"])
check(code == 0 and git("status", "--short") == "" and not os.path.exists(os.path.join(W, NAT, "AK.json")) and "::warning title=National files::" in out, "the drop step puts national.json back, removes the new state file, and says so as a warning (exit %d)" % code)

os.makedirs(os.path.join(W, NAT), exist_ok=True)  # the drop step's git clean took the empty folder with it
open(os.path.join(W, NAT, "AK.json"), "w").write("{}")
open(os.path.join(W, NATIONAL), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and re.fullmatch(r"National permit files \d{4}-\d\d-\d\d", msg) and files == sorted([NAT + "/AK.json", NATIONAL]), "a good week commits the new state file and national.json: %r %s" % (msg, files))
check(git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"), "and pushes them to origin")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
check(code == 0 and "nothing changed" in out, "with nothing to commit the step says so and succeeds")

# a stray file is never committed
os.makedirs(os.path.join(W, "dl", "ks"), exist_ok=True)
open(os.path.join(W, "dl", "ks", "download.xlsx"), "w").write("not a workbook")
open(os.path.join(W, "site", "public", "data", "stray.json"), "w").write("{}")
os.makedirs(os.path.join(W, NAT), exist_ok=True)
open(os.path.join(W, NAT, "KS.json"), "w").write("{}")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and files == [NAT + "/KS.json"] and "stray.json" in git("status", "--short"), "it commits only the national files, whatever else is lying about: %s" % files)

# the last step, rendered as GitHub renders it
outs = {"nat_run": "failure", "nat_build": "success", "nat_check": "success"}
rendered = re.sub(r"\$\{\{ steps\.(\w+)\.outcome \}\}", lambda m: outs[m.group(1)], steps[LAST]["run"])
code, out = sh(rendered)
check(code == 1 and "::error title=National files::producers failure, rebuild success, check success." in out, "the last step fails the run and says which part failed (exit %d)" % code)
check("${{" not in rendered, "every expression in it is one GitHub fills in")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
