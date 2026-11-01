"""Tests for .github/workflows/daily-rrc-report.yml: the structure that isolates the three captures, the `if:` conditions for every
combination of outcomes, and the workflow's own `run:` scripts executed against a throwaway clone with a local bare repo as `origin`
(the three drop steps, the commit title and push, the no-change case, the last step that fails the run).

Needs git and PyYAML. Run: python3 -I tests/test_workflow.py
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


wf = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "daily-rrc-report.yml")))
steps = {s.get("name"): s for s in wf["jobs"]["capture"]["steps"] if s.get("name")}
by_id = {s["id"]: s for s in wf["jobs"]["capture"]["steps"] if s.get("id")}
TX_DROP = "Drop the Texas changes if the capture or its check failed"
OK_DROP = "Drop the Oklahoma changes if the capture or its check failed"
NM_DROP = "Drop the New Mexico changes if the capture or its check failed"
LAST = "Fail the run if a capture or a check failed"
COMMIT = "Commit the new files"

# ---- structure: each state's capture and check carry on after an error, and everything else is ordered around them
IDS = ("tx_capture", "tx_check", "ok_capture", "ok_check", "nm_capture", "nm_check")
check(all(by_id[i].get("continue-on-error") is True for i in IDS), "all three captures and all three checks are continue-on-error")
caps = [by_id[i] for i in ("tx_capture", "ok_capture", "nm_capture")]
check(all(c.get("timeout-minutes") for c in caps) and sum(c["timeout-minutes"] for c in caps) + 10 <= wf["jobs"]["capture"]["timeout-minutes"],
      "each capture has a time limit of its own and the three together leave the job room to commit and publish (%s of %s minutes): a download that trickles cannot use up the job" % ([c.get("timeout-minutes") for c in caps], wf["jobs"]["capture"]["timeout-minutes"]))
names = [s.get("name") or s.get("uses") for s in wf["jobs"]["capture"]["steps"]]
pos = {n: names.index(n) for n in (TX_DROP, OK_DROP, NM_DROP, COMMIT, "Publish the site to GitHub Pages", LAST)}
check(pos[TX_DROP] < pos[COMMIT] and pos[OK_DROP] < pos[COMMIT] and pos[NM_DROP] < pos[COMMIT] < pos["Publish the site to GitHub Pages"] < pos[LAST], "the drops come before the commit, the commit before the publish, the failing step last")
check(names.index("Capture the report") < names.index("Capture the Oklahoma report") < names.index("Capture the New Mexico report") < names.index("Check the archive"), "Texas capture, then Oklahoma, then New Mexico, then the checks")
check(names.index("Check the New Mexico archive") < names.index(NM_DROP) and names.index("Check the Oklahoma archive") < names.index(OK_DROP), "each state's check comes before the step that drops its changes")
check("new_mexico_history" in wf[True]["workflow_dispatch"]["inputs"], "a by-hand run can refill New Mexico's archive")

# ---- the job commits and publishes, so it runs from the default branch only: a manual run chosen from another branch would commit to that branch and publish its site
def runs_for(job, ref):
    expr = job["if"].replace("${{", "").replace("}}", "").strip()
    return eval(expr.replace("github.ref", "ref"), {}, {"ref": ref})


check(all(runs_for(wf["jobs"]["capture"], r) is True for r in ("refs/heads/main",)) and not any(runs_for(wf["jobs"]["capture"], r) for r in ("refs/heads/claude/some-branch", "refs/heads/main-2", "refs/tags/v1", "refs/pull/5/merge", "")),
      "the job runs for refs/heads/main (a schedule, or a run chosen from main) and for no other ref (a branch, a tag, a pull request)")



def cond(name, outcomes, cancelled=False):
    expr = steps[name]["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ").replace("!cancelled()", "(not cancelled)")
    py = re.sub(r"steps\.(\w+)\.outcome", r"outcomes['\1']", py)
    return eval(py, {"outcomes": outcomes, "cancelled": cancelled})


ok_all = True
for tc, tk, oc, ok, nc, nk in itertools.product(["success", "failure"], repeat=6):
    o = dict(zip(IDS, (tc, tk, oc, ok, nc, nk)))
    tx_bad, ok_bad, nm_bad = "failure" in (tc, tk), "failure" in (oc, ok), "failure" in (nc, nk)
    ok_all &= (cond(TX_DROP, o) == tx_bad and cond(OK_DROP, o) == ok_bad and cond(NM_DROP, o) == nm_bad
               and cond(LAST, o) == (tx_bad or ok_bad or nm_bad) and cond(LAST, o, True) is False)
check(ok_all, "all 64 outcome combinations: each drop step runs exactly when its state failed; the last step runs when any did and never when cancelled")

# ---- a throwaway clone with a local bare origin, made from the tracked files as they are now (a shallow CI checkout is fine)
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

# Texas drop step on a dirty Texas folder; the other states' edits must survive it
tx, okd, nmd = "site/public/data/daily", "site/public/data/daily-ok", "site/public/data/daily-nm"
open(os.path.join(W, tx, "index.json"), "a").write(" ")
open(os.path.join(W, tx, "2099-01-01.json"), "w").write("{}")
os.makedirs(os.path.join(W, tx, "img"), exist_ok=True)
open(os.path.join(W, tx, "img", "new.jpg"), "w").write("x")
open(os.path.join(W, okd, "index.json"), "a").write(" ")
open(os.path.join(W, nmd, "index.json"), "a").write(" ")
open(os.path.join(W, nmd, "2099-01-03.json"), "w").write("{}")
code, out = sh(steps[TX_DROP]["run"])
check(code == 0 and not git("status", "--short", "--", tx + "/"), "the Texas drop step restores the folder, edits and new files alike (exit %d)" % code)
check("::warning title=Texas report::" in out, "and says so as a warning annotation")
check(git("status", "--short", "--", okd + "/").startswith("M") and "daily-nm" in git("status", "--short"), "Oklahoma's and New Mexico's changes are left alone by it")
code, out = sh(steps[OK_DROP]["run"])
check(code == 0 and not git("status", "--short", "--", okd + "/") and "daily-nm" in git("status", "--short"), "the Oklahoma drop step restores its folder and leaves New Mexico's")
code, out = sh(steps[NM_DROP]["run"])
check(code == 0 and git("status", "--short") == "" and "::warning title=New Mexico report::" in out, "the New Mexico drop step restores its folder, new files too; after all three the clone is exactly as committed")

# the commit step: only Oklahoma changed (the others dropped), with a day newer than any Texas day
days = sorted(f for f in os.listdir(os.path.join(W, okd)) if re.fullmatch(r"\d{4}-\d\d-\d\d\.json", f))
shutil.copy(os.path.join(W, okd, days[-1]), os.path.join(W, okd, "2099-01-02.json"))
open(os.path.join(W, okd, "index.json"), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
check(code == 0 and msg == "Daily RRC, OCC and OCD reports 2099-01-02", "the commit is titled with the newest day of any state: %r (exit %d)" % (msg, code))
check(git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"), "and was pushed to origin")
files = [l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l]
check(files and all(f.startswith(okd + "/") for f in files), "and holds Oklahoma files only: %s" % files)
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
check(code == 0 and "nothing changed" in out, "with nothing to commit the step says so and succeeds")
# only New Mexico changed, with the newest day of all
shutil.copy(os.path.join(W, okd, days[-1]), os.path.join(W, nmd, "2099-01-03.json"))
open(os.path.join(W, nmd, "index.json"), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
files = [l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l]
check(code == 0 and msg == "Daily RRC, OCC and OCD reports 2099-01-03" and files and all(f.startswith(nmd + "/") for f in files), "a night when only New Mexico changed commits its folder alone, titled with its day: %r %s" % (msg, files))

# the last step, rendered as GitHub renders it
outs = {"tx_capture": "failure", "tx_check": "success", "ok_capture": "success", "ok_check": "success", "nm_capture": "success", "nm_check": "failure"}
rendered = re.sub(r"\$\{\{ steps\.(\w+)\.outcome \}\}", lambda m: outs[m.group(1)], steps[LAST]["run"])
code, out = sh(rendered)
check(code == 1 and "::error title=Daily reports::Texas capture failure, Texas check success, Oklahoma capture success, Oklahoma check success, New Mexico capture success, New Mexico check failure" in out, "the last step fails the run, naming each outcome (exit %d)" % code)
check("${{" not in rendered, "every expression in it is one GitHub fills in")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
