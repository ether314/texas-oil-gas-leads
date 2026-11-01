"""Tests for .github/workflows/well-images.yml: the daily run that ties the Railroad Commission's scanned filings to wells (site/pipeline/d12_wells.py), publishes them as GitHub releases, commits
site/public/data/wells/ and publishes the site.

The structure (a time after the last pack of the day has landed and settled, away from every other workflow, in the nightly capture's concurrency group, a job that only runs on main, the repository token
given to the one step that publishes releases, every step bounded, only the well files ever committed), the `if:` conditions for every outcome, the inputs refused before anything runs, and the workflow's
own `run:` scripts executed against a throwaway clone with a local bare repo as `origin`: the capture step passes the right arguments (with a stand-in python3), the drop step puts the folder back, the commit
step commits the well files and nothing else and pushes them, and the last step fails the run. The producer itself is not run here (it reads the RRC); test_d12_wells.py covers it.

Needs git and PyYAML. Run: python3 -I tests/test_workflow_wells.py
"""
import itertools
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d12_wells as D12  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


WF = os.path.join(REPO, ".github", "workflows")
wf = yaml.safe_load(open(os.path.join(WF, "well-images.yml")))
others = {n: yaml.safe_load(open(os.path.join(WF, n))) for n in ("daily-rrc-report.yml", "refresh-monthly.yml", "refresh-national.yml")}
job = wf["jobs"]["wells"]
steps = {s.get("name"): s for s in job["steps"] if s.get("name")}
by_id = {s["id"]: s for s in job["steps"] if s.get("id")}
names = [s.get("name") or s.get("uses") for s in job["steps"]]
TOOLS, RUN, CHECK = "Install the tools that draw page previews", "Read the packs, tie the documents to wells, publish them", "Check the well-image files"
DROP, COMMIT, PUBLISH, LAST = "Drop the well-image files if their check failed", "Commit the new files", "Publish the site to GitHub Pages", "Fail the run if a pack or the check failed"
WELLS = "site/public/data/wells"


def minutes(cron):
    m, h = cron.split()[:2]
    return int(h) * 60 + int(m)


# ---- structure
cron = wf[True]["schedule"][0]["cron"]
check(len(wf[True]["schedule"]) == 1 and cron.split()[2:] == ["*", "*", "*"] and "workflow_dispatch" in wf[True], "it runs once a day, and by hand (%s)" % cron)
check(minutes(cron) >= 16 * 60 + 20 + D12.SETTLE_MINUTES, "it runs after the W-1 pack (listed about 10:20 AM Central, 16:20 UTC in winter) has been listed for the %d minutes a pack is left alone: %s UTC" % (D12.SETTLE_MINUTES, cron))
away = []
for n, o in others.items():
    for s in o[True]["schedule"]:
        away.append(abs(minutes(s["cron"]) - minutes(cron)) >= 180)
check(all(away), "it is at least three hours from every other workflow's schedule, so none of them waits for it")
check(wf["concurrency"]["group"] == others["daily-rrc-report.yml"]["concurrency"]["group"] and wf["concurrency"]["cancel-in-progress"] is False, "it shares the nightly capture's concurrency group: the two never push at once, neither cancels the other")
check(wf["permissions"] == {"contents": "write"}, "it can create releases and commit, and nothing else")
check(job.get("if") == "github.ref == 'refs/heads/main'", "the job only runs on main: a manual run from another branch would publish releases and commit to that branch")
check(set(wf[True]["workflow_dispatch"]["inputs"]) == {"days", "window", "day"}, "by hand it takes days, window and a single day")
check("continue-on-error" not in steps[TOOLS] and steps[TOOLS].get("timeout-minutes", 99) <= 6 and "poppler-utils" in steps[TOOLS]["run"] and "pillow" in steps[TOOLS]["run"] and names.index(TOOLS) < names.index(RUN),
      "poppler and Pillow are installed first, with a short limit, and a failed install fails the run (without them there is nothing to publish)")
budget = int(re.search(r"--budget (\d+)", steps[RUN]["run"]).group(1))
check(by_id["wells_run"].get("continue-on-error") is True and budget < by_id["wells_run"]["timeout-minutes"] and by_id["wells_run"]["timeout-minutes"] + 15 <= job["timeout-minutes"],
      "the run has a limit (%d minutes) after the producer's own budget (%d) and leaves the job room to check, commit and publish; it is continue-on-error, so what was published and recorded is committed" % (by_id["wells_run"]["timeout-minutes"], budget))
check(names.index(RUN) < names.index(CHECK) < names.index(DROP) < names.index(COMMIT) < names.index(PUBLISH) < names.index(LAST), "run, check, drop, commit, publish, and the failing step last")
runs = {k: steps[k]["run"] for k in steps if "run" in steps[k]}
check("d12_wells.py" in runs[RUN] and "d12_wells.py --check" in runs[CHECK] and all(re.search(r"python3 -I ", runs[k]) for k in (RUN, CHECK)), "each step runs its own script, isolated (python3 -I)")
adds = re.findall(r"git add (.+)", runs[COMMIT])
check(adds == [WELLS] and not re.search(r"git add (-A|\.|--all)", runs[COMMIT]), "the commit adds the well files and nothing else: %s" % adds)
tokens = [s.get("name") or s.get("uses") for s in job["steps"] if "GH_TOKEN" in (s.get("env") or {})]
check(tokens == [RUN] and steps[RUN]["env"]["GH_TOKEN"] == "${{ github.token }}", "the repository token is given to the one step that creates releases: %s" % tokens)
check(os.path.isfile(os.path.join(REPO, WELLS, "index.json")), "the folder it commits has its index in the tree, so a first run has something to read and the page something to load")
check(job["steps"][0].get("uses", "").startswith("actions/checkout@") and job["steps"][0]["with"]["fetch-depth"] == 0, "it checks out the whole history, as the other publishing workflows do (the publish script needs it)")


def cond(name, outcomes, cancelled=False):
    expr = steps[name]["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ").replace("!cancelled()", "(not cancelled)")
    py = re.sub(r"steps\.(\w+)\.outcome", r"outcomes['\1']", py)
    return eval(py, {"outcomes": outcomes, "cancelled": cancelled})


good = True
for r, c in itertools.product(["success", "failure"], repeat=2):
    o = {"wells_run": r, "wells_check": c}
    good &= (cond(DROP, o) == (c == "failure") and cond(LAST, o) == ("failure" in (r, c)) and cond(LAST, o, True) is False and cond(CHECK, o) is True and cond(CHECK, o, True) is False
             and all(cond(n, o) is True and cond(n, o, True) is False for n in (COMMIT, PUBLISH)))
check(good, "all 4 outcome combinations: the drop runs exactly when the check failed; commit, publish and the check run unless cancelled; the last step runs when anything failed and never when cancelled")

# ---- the capture step, with a stand-in python3 that records what it was asked to run
TMP = tempfile.mkdtemp()
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
LOG = os.path.join(TMP, "calls.txt")
with open(os.path.join(BIN, "python3"), "w") as f:
    f.write('#!/bin/bash\necho "$@" >> "%s"\n' % LOG)
os.chmod(os.path.join(BIN, "python3"), os.stat(os.path.join(BIN, "python3")).st_mode | stat.S_IEXEC)
W, ORIGIN = os.path.join(TMP, "work"), os.path.join(TMP, "origin.git")
os.makedirs(W)


def sh(script, env=None, cwd=W, path_first=None):
    e = {"PATH": (path_first + ":" if path_first else "") + os.environ["PATH"], "HOME": os.environ.get("HOME", TMP)}
    e.update(env or {})
    r = subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=e, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def asked(env):
    if os.path.exists(LOG):
        os.remove(LOG)
    code, out = sh(runs[RUN], env=env, path_first=BIN)
    return code, (open(LOG).read().strip() if os.path.exists(LOG) else ""), out


base = {"DAYS": "2", "WINDOW": "14", "FILING_DAY": ""}
code, called, _ = asked(base)
check(code == 0 and called == "-I site/pipeline/d12_wells.py --days 2 --window 14 --budget 40", "a scheduled run asks for the newest two days of the last 14, with a budget: %s" % called)
code, called, _ = asked({**base, "FILING_DAY": "2026-10-29", "DAYS": "5", "WINDOW": "30"})
check(code == 0 and called == "-I site/pipeline/d12_wells.py --days 5 --window 30 --budget 40 --day 2026-10-29", "a run by hand can ask for a day and reach back: %s" % called)
for label, env in (("days that is not a number", {**base, "DAYS": "two"}), ("an empty window", {**base, "WINDOW": ""}), ("a window with a command in it", {**base, "WINDOW": "14; rm -rf /"}),
                   ("a day that is not a date", {**base, "FILING_DAY": "yesterday"}), ("a date with shell characters", {**base, "FILING_DAY": "2026-10-29$(id)"})):
    code, called, out = asked(env)
    check(code == 1 and called == "", "it refuses %s and runs nothing (exit %d)" % (label, code))
# the arguments are accepted by the producer, and its own limits refuse the rest
check(D12.main(["--check", "--out", os.path.join(REPO, WELLS)]) == 0, "the producer's --check passes on the committed folder")
for argv in (["--days", "99"], ["--window", "0"], ["--budget", "1"], ["--day", "soon"], ["--no-upload"]):
    try:
        D12.main(argv)
        refused = False
    except SystemExit as e:
        refused = e.code not in (0, None)
    check(refused, "the producer refuses %s" % " ".join(argv))

# ---- a throwaway clone with a local bare origin, made from the tracked files as they are now
tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True).stdout.decode().split("\0")
for f in tracked:
    if f and os.path.isfile(os.path.join(REPO, f)):
        os.makedirs(os.path.dirname(os.path.join(W, f)) or W, exist_ok=True)
        shutil.copy2(os.path.join(REPO, f), os.path.join(W, f))
for f in os.listdir(os.path.join(REPO, WELLS)):  # the placeholder index may not be tracked yet when this runs before the commit
    p = os.path.join(REPO, WELLS, f)
    if os.path.isfile(p):
        os.makedirs(os.path.join(W, WELLS), exist_ok=True)
        shutil.copy2(p, os.path.join(W, WELLS, f))


def git(*a, cwd=W):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *a], cwd=cwd, capture_output=True, text=True).stdout.strip()


git("init", "-q", "-b", "main")
git("add", "-A")
git("commit", "-q", "-m", "base")
subprocess.run(["git", "clone", "-q", "--bare", W, ORIGIN], check=True)
git("remote", "add", "origin", ORIGIN)
git("fetch", "-q", "origin")
git("branch", "--set-upstream-to=origin/main", "main")
check(git("status", "--short") == "", "the clone starts clean, as an Actions checkout does")

# a good day: a county file and a changed index
os.makedirs(os.path.join(W, WELLS, "county"), exist_ok=True)
open(os.path.join(W, WELLS, "county", "991.json"), "w").write("{}")
open(os.path.join(W, WELLS, "index.json"), "a").write(" ")
check(len(git("status", "--short").splitlines()) == 2, "the clone now has a new county file and a changed index")
code, out = sh(steps[DROP]["run"])
check(code == 0 and git("status", "--short") == "" and not os.path.exists(os.path.join(W, WELLS, "county", "991.json")) and "::warning title=Well images::" in out,
      "the drop step puts the index back, removes the new county file, and says so as a warning (exit %d)" % code)

os.makedirs(os.path.join(W, WELLS, "county"), exist_ok=True)
open(os.path.join(W, WELLS, "county", "991.json"), "w").write("{}")
open(os.path.join(W, WELLS, "index.json"), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and re.fullmatch(r"Well images \d{4}-\d\d-\d\d", msg) and files == sorted([WELLS + "/county/991.json", WELLS + "/index.json"]), "a good day commits the county file and the index: %r %s" % (msg, files))
check(git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"), "and pushes them to origin")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
check(code == 0 and "nothing changed" in out, "with nothing to commit the step says so and succeeds")

# a stray file is never committed; a push that races another commit is rebased, not refused
os.makedirs(os.path.join(W, "dl"), exist_ok=True)
open(os.path.join(W, "dl", "pack.zip"), "w").write("not a pack")
open(os.path.join(W, "site", "public", "data", "stray.json"), "w").write("{}")
open(os.path.join(W, WELLS, "county", "993.json"), "w").write("{}")
other = os.path.join(TMP, "other")
subprocess.run(["git", "clone", "-q", ORIGIN, other], check=True)
open(os.path.join(other, "NOTE.txt"), "w").write("another workflow pushed first")
git("add", "NOTE.txt", cwd=other)
git("commit", "-q", "-m", "someone else", cwd=other)
git("push", "-q", "origin", "HEAD:main", cwd=other)
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and files == [WELLS + "/county/993.json"] and "stray.json" in git("status", "--short") and git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"),
      "it commits only the well files whatever else is lying about, and rebases onto what another run pushed first: %s (exit %d)" % (files, code))

# the last step, rendered as GitHub renders it
outs = {"wells_run": "failure", "wells_check": "success"}
rendered = re.sub(r"\$\{\{ steps\.(\w+)\.outcome \}\}", lambda m: outs[m.group(1)], steps[LAST]["run"])
code, out = sh(rendered)
check(code == 1 and "::error title=Well images::run failure, check success." in out, "the last step fails the run and says which part failed (exit %d)" % code)
check("${{" not in rendered, "every expression in it is one GitHub fills in")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
