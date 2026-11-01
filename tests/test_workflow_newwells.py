"""Tests for .github/workflows/refresh-newwells.yml: the weekly run that reads FracFocus (site/pipeline/d13_newwells.py), commits the new-wells files and publishes.

The structure (a weekday and hour of its own, in the nightly capture's concurrency group so the two never run at once, only on main, the read and the check isolated so the commit and the publish
still happen, only the two data files ever committed), the `if:` conditions for every outcome, and the workflow's own `run:` scripts executed against a throwaway clone with a local bare repo
as `origin`: the read step treats exit 2 (the server refused) as an answer and anything else as a failure, the drop step puts both files back, the commit step commits the two files and nothing
else, says so when nothing changed, and the last step fails the run. The producer is not run here (it reads a public server); test_d13_newwells.py covers it.

Needs git and PyYAML. Run: python3 -I tests/test_workflow_newwells.py
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
wf = yaml.safe_load(open(os.path.join(WF, "refresh-newwells.yml")))
others = {n: yaml.safe_load(open(os.path.join(WF, n))) for n in os.listdir(WF) if n.endswith(".yml") and n != "refresh-newwells.yml"}
nightly = others["daily-rrc-report.yml"]
job = wf["jobs"]["refresh"]
steps = {s.get("name"): s for s in job["steps"] if s.get("name")}
by_id = {s["id"]: s for s in job["steps"] if s.get("id")}
names = [s.get("name") or s.get("uses") for s in job["steps"]]
RESTORE, SAVE = "Restore the last download's list of wells", "Keep this download's list of wells for the next run"
READ, CHECK, DROP, COMMIT, PUBLISH, LAST = ("Read the new wells from FracFocus", "Check the new wells files", "Drop the new wells files if their check failed", "Commit the new files",
                                            "Publish the site to GitHub Pages", "Fail the run if the read or the check failed")
DIR = "site/public/data/newwells"


def minutes(cron):
    m, h = cron.split()[:2]
    return int(h) * 60 + int(m)


# ---- structure
check(wf[True]["schedule"] == [{"cron": "35 10 * * *"}] and "workflow_dispatch" in wf[True], "it runs every day at 10:35 UTC and by hand")
mine = wf[True]["schedule"][0]["cron"]
clash = []
for n, o in others.items():
    for sch in (o.get(True) or {}).get("schedule", []) or []:
        c = sch["cron"]
        same_day = c.split()[-1] in ("*", mine.split()[-1]) or mine.split()[-1] == "*"
        if same_day and abs(minutes(c) - minutes(mine)) < 180 and c.split()[2:4] == ["*", "*"]:
            clash.append((n, c))
check(not clash, "no other workflow runs within three hours of it on the same day: %s" % clash)
check(wf["concurrency"]["group"] == nightly["concurrency"]["group"] and wf["concurrency"]["cancel-in-progress"] is False, "it shares the nightly capture's concurrency group: the two never run at once, neither cancels the other")
check(wf["permissions"] == {"contents": "write"}, "it can commit and nothing else")
check(job.get("if") == "github.ref == 'refs/heads/main'", "the job only runs on main: a dispatch from another branch would commit to it and publish its site")
check(job["timeout-minutes"] <= 30 and by_id["read"].get("timeout-minutes", 99) <= 20, "the job and the read are bounded: %s %s" % (job["timeout-minutes"], by_id["read"].get("timeout-minutes")))
check(by_id["read"].get("continue-on-error") is True and by_id["check"].get("continue-on-error") is True, "the read and the check are continue-on-error: the commit and publish still happen")
check(names.index(RESTORE) < names.index(READ) < names.index(CHECK) < names.index(DROP) < names.index(COMMIT) < names.index(SAVE) < names.index(PUBLISH) < names.index(LAST), "restore the kept list, read, check, drop, commit, keep the list, publish, and the failing step last")
runs = {k: steps[k]["run"] for k in steps if "run" in steps[k]}
check("d13_newwells.py" in runs[READ] and "d13_newwells.py --check" in runs[CHECK] and all("python3 -I " in runs[k] for k in (READ, CHECK)), "each step runs the producer isolated (python3 -I)")
adds = re.findall(r"git add (.+)", runs[COMMIT])
check(adds == [DIR + "/summary.json " + DIR + "/points.json " + DIR + "/points-history.json " + DIR + "/arrivals.json"], "the commit adds the four files and nothing else: %s" % adds)
check(not re.search(r"git add (-A|\.|--all)", runs[COMMIT]), "it never adds everything")
check(all(os.path.exists(os.path.join(REPO, DIR, f)) for f in ("summary.json", "points.json", "points-history.json", "arrivals.json")), "the files it commits are the ones the site reads")
check("secrets." not in open(os.path.join(WF, "refresh-newwells.yml")).read() and "GITHUB_TOKEN" not in open(os.path.join(WF, "refresh-newwells.yml")).read(), "it names no secret: the producer needs none (FracFocus is public)")


def cond(name, outcomes, cancelled=False, outputs=None):
    expr = steps[name]["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ").replace("!cancelled()", "(not cancelled)")
    py = re.sub(r"steps\.(\w+)\.outputs\.(\w+)", r"outputs.get('\1.\2', '')", py)
    py = re.sub(r"steps\.(\w+)\.outcome", r"outcomes['\1']", py)
    return eval(py, {"outcomes": outcomes, "cancelled": cancelled, "outputs": outputs or {}})


good = True
for r, c in itertools.product(["success", "failure"], repeat=2):
    o = {"read": r, "check": c}
    good &= (cond(DROP, o) == (c == "failure") and cond(LAST, o) == ("failure" in (r, c)) and cond(LAST, o, True) is False and cond(CHECK, o, True) is False and cond(CHECK, o) is True)
check(good, "all 4 outcome combinations: the drop runs exactly when the check failed; the last step runs when anything failed and never when cancelled; the check runs unless cancelled")
keep_ok = True
for wrote, c in itertools.product(["true", ""], ["success", "failure"]):
    keep_ok &= cond(SAVE, {"read": "success", "check": c}, outputs={"read.wrote": wrote}) == (wrote == "true" and c == "success")
check(keep_ok, "the list is kept for tomorrow exactly when the producer moved it on and the files passed their check (a refusal, or a failed check, keeps yesterday's)")
restore, save = steps[RESTORE], steps[SAVE]
check(restore["uses"].startswith("actions/cache/restore@") and save["uses"].startswith("actions/cache/save@") and restore["with"]["path"] == save["with"]["path"] == ".ff-cache/ff-seen.txt.gz", "the list is restored and saved through Actions' cache, at one path")
check(restore["with"]["restore-keys"].strip() == "ff-seen-" and save["with"]["key"].startswith("ff-seen-") and not restore["with"]["key"].startswith(save["with"]["key"].split("$")[0] + "x") and restore["with"]["key"] == "ff-seen-restore-only" and "run_id" in save["with"]["key"],
      "the restore always falls back to the newest ff-seen-* (its own key is never saved), and each day's save has a key of its own: a cache entry is never overwritten")
check(not restore["with"]["path"].startswith(("site/", "/")) and ".ff-cache/" in open(os.path.join(REPO, ".gitignore")).read().split(), "the list (API numbers) is kept outside site/ and ignored by git: it can never be published or committed")
check("--seen .ff-cache/ff-seen.txt.gz" in runs[READ] and "--seen" not in runs[CHECK] and "wrote=true" in runs[READ] and "GITHUB_OUTPUT" in runs[READ], "the read passes the list to the producer and says when it was moved on")

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
# files this branch added and has not committed yet are part of "as they are now"
for f in (DIR + "/summary.json", DIR + "/points.json", DIR + "/points-history.json", DIR + "/arrivals.json"):
    os.makedirs(os.path.dirname(os.path.join(W, f)), exist_ok=True)
    shutil.copy2(os.path.join(REPO, f), os.path.join(W, f))
git("init", "-q", "-b", "main")
git("add", "-A")
git("commit", "-q", "-m", "base")
subprocess.run(["git", "clone", "-q", "--bare", W, ORIGIN], check=True)
git("remote", "add", "origin", ORIGIN)
git("fetch", "-q", "origin")
git("branch", "--set-upstream-to=origin/main", "main")
check(git("status", "--short") == "", "the clone starts clean, as an Actions checkout does")

# the read step: the producer is replaced by a stand-in that exits with the code we choose (the real one reads a public server)
os.makedirs(os.path.join(W, "stub"), exist_ok=True)
for exit_code, expect_code, expect_text, wrote in ((0, 0, "", True), (2, 0, "::warning title=New wells::FracFocus refused the runner", False), (1, 1, "", False), (3, 3, "", False)):
    stub = os.path.join(W, "site", "pipeline", "d13_newwells.py")
    saved = open(stub).read()
    open(stub, "w").write("import sys\nsys.exit(%d)\n" % exit_code)
    gh_out = os.path.join(TMP, "gh-output-%d" % exit_code)
    code, out = sh(steps[READ]["run"], env={"GITHUB_OUTPUT": gh_out})
    open(stub, "w").write(saved)
    said = os.path.exists(gh_out) and "wrote=true" in open(gh_out).read()
    check(code == expect_code and expect_text in out and said == wrote, "the read step with the producer exiting %d: exit %d%s, and it %s the list was moved on (got %d)" % (exit_code, expect_code, ", and a warning that says the files stay" if expect_text else "", "says" if wrote else "does not say", code))
check(git("status", "--short") == "", "the stand-in left the clone as it was")

# a good day: the four files changed
for f in ("summary.json", "points.json", "points-history.json", "arrivals.json"):
    open(os.path.join(W, DIR, f), "a").write(" ")
check(len(git("status", "--short").splitlines()) == 4, "the clone now has the four files changed")
code, out = sh(steps[DROP]["run"])
check(code == 0 and git("status", "--short") == "" and "::warning title=New wells::" in out, "the drop step puts all four files back, and says so as a warning (exit %d)" % code)

for f in ("summary.json", "points.json", "points-history.json", "arrivals.json"):
    open(os.path.join(W, DIR, f), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
msg = git("log", "-1", "--format=%s")
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and re.fullmatch(r"New wells map \d{4}-\d\d-\d\d", msg) and files == sorted([DIR + "/summary.json", DIR + "/points.json", DIR + "/points-history.json", DIR + "/arrivals.json"]), "a good day commits the four files: %r %s" % (msg, files))
check(git("rev-parse", "main", cwd=ORIGIN) == git("rev-parse", "HEAD"), "and pushes them to origin")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
check(code == 0 and "nothing changed" in out, "with nothing to commit the step says so and succeeds")

# a stray file is never committed
open(os.path.join(W, "site", "public", "data", "stray.json"), "w").write("{}")
open(os.path.join(W, DIR, "points.json"), "a").write(" ")
code, out = sh(steps[COMMIT]["run"], env={"GITHUB_REF_NAME": "main"})
files = sorted(l.split("|")[0].strip() for l in git("show", "--stat", "--format=", "HEAD").splitlines() if "|" in l)
check(code == 0 and files == [DIR + "/points.json"] and "stray.json" in git("status", "--short"), "it commits only its own files, whatever else is lying about: %s" % files)

# the last step, rendered as GitHub renders it
outs = {"read": "failure", "check": "success"}
rendered = re.sub(r"\$\{\{ steps\.(\w+)\.outcome \}\}", lambda m: outs[m.group(1)], steps[LAST]["run"])
code, out = sh(rendered)
check(code == 1 and "::error title=New wells::read failure, check success." in out, "the last step fails the run and says which part failed (exit %d)" % code)
check("${{" not in rendered, "every expression in it is one GitHub fills in")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
