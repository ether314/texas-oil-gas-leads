"""Tests for .github/workflows/refresh-monthly.yml: the weekly refresh of Oklahoma's, New Mexico's and the federal offshore's permit history files.

The structure that isolates the three refreshes from each other and from the nightly captures (same concurrency group, so they never run
at once), the `if:` conditions for every combination of outcomes, and the workflow's own `run:` scripts executed against a throwaway
clone with a local bare repo as `origin` (the three drop steps, the commit and push, the no-change case, the last step that fails the run).
The producers themselves are not run here (they read public servers); their own tests cover them.

Needs git and PyYAML. Run: python3 -I tests/test_workflow_monthly.py
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


wf = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "refresh-monthly.yml")))
nightly = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "daily-rrc-report.yml")))
job = wf["jobs"]["refresh"]
steps = {s.get("name"): s for s in job["steps"] if s.get("name")}
by_id = {s["id"]: s for s in job["steps"] if s.get("id")}
NM_DROP = "Drop the New Mexico files if the refresh or its check failed"
OK_DROP = "Drop the Oklahoma files if the refresh or its check failed"
FO_DROP = "Drop the federal offshore files if the refresh or its check failed"
LAST = "Fail the run if a refresh or a check failed"
COMMIT = "Commit the new files"
PUBLISH = "Publish the site to GitHub Pages"
IDS = ("nm_refresh", "ok_refresh", "fo_refresh", "nm_check", "ok_check", "fo_check", "nat_build")
DATA = "site/public/data"
NM_FILES = [DATA + "/" + n + "-nm.json" for n in ("series-permits", "county-permits", "operators", "permits")]
OK_FILES = [DATA + "/" + n + "-ok.json" for n in ("series-permits", "county-permits", "operators", "permits")]
FO_FILES = [DATA + "/" + n + "-fo.json" for n in ("series-permits", "county-permits", "operators", "permits")]

# ---- structure
check(wf[True]["schedule"] == [{"cron": "40 5 * * 1"}] and "workflow_dispatch" in wf[True], "it runs on Mondays at 05:40 UTC, after the nightly capture and its backup, and by hand")
check(wf["concurrency"]["group"] == nightly["concurrency"]["group"] and wf["concurrency"]["cancel-in-progress"] is False, "it shares the nightly capture's concurrency group, so the two never run at once and neither cancels the other")
check(wf["permissions"] == {"contents": "write"}, "it can commit and nothing else")

# ---- the job commits and publishes, so it runs from the default branch only: a manual run chosen from another branch would commit to that branch and publish its site
def runs_for(job, ref):
    expr = job["if"].replace("${{", "").replace("}}", "").strip()
    return eval(expr.replace("github.ref", "ref"), {}, {"ref": ref})


check(all(runs_for(job, r) is True for r in ("refs/heads/main",)) and not any(runs_for(job, r) for r in ("refs/heads/claude/some-branch", "refs/heads/main-2", "refs/tags/v1", "refs/pull/5/merge", "")),
      "the job runs for refs/heads/main (a schedule, or a run chosen from main) and for no other ref (a branch, a tag, a pull request)")

check(all(by_id[i].get("continue-on-error") is True for i in IDS), "all three refreshes and all three checks are continue-on-error: one failing cannot stop the others")
check(by_id["ok_refresh"].get("timeout-minutes", 0) >= 15 and by_id["nm_refresh"].get("timeout-minutes", 0) <= 10 and by_id["fo_refresh"].get("timeout-minutes", 0) <= 10, "the 154 MB Oklahoma download has room, and no step can hang the job")
check(sum(by_id[i]["timeout-minutes"] for i in ("nm_refresh", "ok_refresh", "fo_refresh")) + 10 <= job["timeout-minutes"], "the refreshes' limits together leave the job room to check, commit and publish")
names = [s.get("name") or s.get("uses") for s in job["steps"]]
pos = {n: names.index(n) for n in (NM_DROP, OK_DROP, FO_DROP, COMMIT, PUBLISH, LAST)}
check(names.index("Refresh New Mexico's permit history") < names.index("Check New Mexico's files") < pos[NM_DROP] < pos[COMMIT] < pos[PUBLISH] < pos[LAST]
      and names.index("Refresh Oklahoma's permit history") < names.index("Check Oklahoma's files") < pos[OK_DROP] < pos[COMMIT]
      and names.index("Refresh the federal offshore's drilling history") < names.index("Check the federal offshore's files") < pos[FO_DROP] < pos[COMMIT], "refresh, then check, then drop, then commit, then publish, the failing step last")
runs = {k: steps[k]["run"] for k in steps if "run" in steps[k]}
check("d9_nm_monthly.py" in runs["Refresh New Mexico's permit history"] and "d8_ok_monthly.py" in runs["Refresh Oklahoma's permit history"] and "d10_fo_monthly.py" in runs["Refresh the federal offshore's drilling history"]
      and "d9_nm_monthly.py --check" in runs["Check New Mexico's files"] and "d8_ok_monthly.py --check" in runs["Check Oklahoma's files"] and "d10_fo_monthly.py --check" in runs["Check the federal offshore's files"],
      "each refresh and each check runs its own producer (python3 -I)")
check(all(re.search(r"python3 -I ", runs[k]) for k in runs if "site/pipeline" in runs[k]), "producers run isolated: python3 -I")
check(all(os.path.exists(os.path.join(REPO, f)) for f in NM_FILES + OK_FILES + FO_FILES), "the twelve files the workflow names are the twelve committed ones (and national.json is the thirteenth)")
ALL = {"nm": (NM_FILES, NM_DROP), "ok": (OK_FILES, OK_DROP), "fo": (FO_FILES, FO_DROP)}
NAT = "Rebuild the national report's file"
check(names.index(FO_DROP) < names.index(NAT) < pos[COMMIT] and "d11_nat_build.py" in steps[NAT]["run"] and "python3 -I " in steps[NAT]["run"] and by_id["nat_build"].get("continue-on-error") is True,
      "the national report's file is rebuilt after the drops and before the commit, isolated, and a failed rebuild cannot stop the commit")
check("site/public/data/national.json" in steps[COMMIT]["run"] and not any("national" in steps[d]["run"] for d in (NM_DROP, OK_DROP, FO_DROP)), "the commit adds national.json, which no drop step restores (it is rebuilt from whatever survived)")
check(all(f in steps[COMMIT]["run"] for f in NM_FILES + OK_FILES + FO_FILES) and all(f in steps[drop]["run"] for files, drop in ALL.values() for f in files)
      and not any(f in steps[drop]["run"] for st, (files, drop) in ALL.items() for other, (fs, _) in ALL.items() if other != st for f in fs),
      "the commit adds the twelve; each drop step restores its own state's four and none of the others'")
check(not any("geo" in f for f in re.findall(r"site/public/data/\S+", steps[COMMIT]["run"])), "the offshore's map of areas (counties-fo.geo.json) is rebuilt by hand and is never committed by this workflow")


def cond(name, outcomes, cancelled=False):
    expr = steps[name]["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ").replace("!cancelled()", "(not cancelled)")
    py = re.sub(r"steps\.(\w+)\.outcome", r"outcomes['\1']", py)
    return eval(py, {"outcomes": outcomes, "cancelled": cancelled})


good = True
for nr, orf, fr, nc, oc, fc, nb in itertools.product(["success", "failure"], repeat=7):
    o = dict(zip(IDS, (nr, orf, fr, nc, oc, fc, nb)))
    nm_bad, ok_bad, fo_bad = "failure" in (nr, nc), "failure" in (orf, oc), "failure" in (fr, fc)
    good &= (cond(NM_DROP, o) == nm_bad and cond(OK_DROP, o) == ok_bad and cond(FO_DROP, o) == fo_bad
             and cond(LAST, o) == (nm_bad or ok_bad or fo_bad or nb == "failure") and cond(LAST, o, True) is False)
check(good, "all 128 outcome combinations: each drop step runs exactly when its state failed; the last step runs when any step (the national rebuild too) failed and never when cancelled")

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

# each drop step puts back its own state's files and leaves the others' alone
for f in NM_FILES + OK_FILES + FO_FILES:
    open(os.path.join(W, f), "a").write(" ")
code, out = sh(steps[NM_DROP]["run"])
dirty = git("status", "--short").splitlines()
check(code == 0 and len(dirty) == 8 and not any("-nm.json" in l for l in dirty) and "::warning title=New Mexico files::" in out, "the New Mexico drop step restores New Mexico's four files, says so as a warning, and leaves the other eight (exit %d)" % code)
code, out = sh(steps[FO_DROP]["run"])
dirty = git("status", "--short").splitlines()
check(code == 0 and len(dirty) == 4 and all("-ok.json" in l for l in dirty) and "::warning title=Federal offshore files::" in out, "the federal offshore drop step restores its four and leaves Oklahoma's four (exit %d)" % code)
code, out = sh(steps[OK_DROP]["run"])
check(code == 0 and git("status", "--short") == "" and "::warning title=Oklahoma files::" in out, "the Oklahoma drop step restores the rest; the clone is exactly as committed")

# the commit step: one state refreshed
open(os.path.join(W, NM_FILES[0]), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
files = [l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l]
check(code == 0 and re.fullmatch(r"Monthly Oklahoma, New Mexico and federal offshore files \d{4}-\d\d-\d\d", msg) and files == [NM_FILES[0]], "a week when only New Mexico changed commits that file alone: %r %s" % (msg, files))
check(git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"), "and pushes it to origin")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
check(code == 0 and "nothing changed" in out, "with nothing to commit the step says so and succeeds")
# a file outside the twelve (a download folder, a stray file) is never committed by it
os.makedirs(os.path.join(W, "dl", "ok-monthly"), exist_ok=True)
open(os.path.join(W, "dl", "ok-monthly", "ITD-wells-formations-base.xlsx"), "w").write("not a workbook")
open(os.path.join(W, DATA, "stray.json"), "w").write("{}")
open(os.path.join(W, OK_FILES[1]), "a").write(" ")
open(os.path.join(W, FO_FILES[3]), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
left = git("status", "--short")
check(code == 0 and files == sorted([OK_FILES[1], FO_FILES[3]]) and "stray.json" in left, "it commits only the files it names (twelve and national.json), whatever else is lying about (the download folder is ignored by git): %s" % files)

# the last step, rendered as GitHub renders it
outs = {"nm_refresh": "success", "ok_refresh": "failure", "fo_refresh": "success", "nm_check": "success", "ok_check": "success", "fo_check": "failure", "nat_build": "success"}
rendered = re.sub(r"\$\{\{ steps\.(\w+)\.outcome \}\}", lambda m: outs[m.group(1)], steps[LAST]["run"])
code, out = sh(rendered)
check(code == 1 and "::error title=Monthly files::New Mexico refresh success, New Mexico check success, Oklahoma refresh failure, Oklahoma check success, federal offshore refresh success, federal offshore check failure, national report file success" in out, "the last step fails the run, naming each outcome (exit %d)" % code)
check("${{" not in rendered, "every expression in it is one GitHub fills in")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
