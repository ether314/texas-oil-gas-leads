"""Tests for .github/workflows/publish.yml and .github/scripts/publish_pages.sh: the publish after a green merge, and the script the
nightly capture shares with it.

The workflow's structure and its `if:` for every kind of trigger are checked, then the script is run against a throwaway clone with a
local bare repository as `origin` that has a gh-pages branch holding an old site: it publishes the committed site/public and the
.nojekyll marker, removes what is no longer in the site, adds one commit and never rewrites history, says so when nothing changed,
refuses to publish a copy that is not a site, and starts again from the branch's new tip when another publish got there first (and
gives up, red, if that keeps happening).

Needs git and PyYAML. Run: python3 -I tests/test_publish.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, ".github", "scripts", "publish_pages.sh")
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def load(name):
    with open(os.path.join(REPO, ".github", "workflows", name), encoding="utf-8") as f:
        text = f.read()
    doc = yaml.safe_load(text)
    doc["_on"] = doc.get("on", doc.get(True))  # YAML reads a bare `on` as the boolean True
    return doc, text


wf, text = load("publish.yml")
ci, _ = load("ci.yml")
nightly, _ = load("daily-rrc-report.yml")

# ---- structure
on = wf["_on"]
run = on["workflow_run"]
check(run["workflows"] == [ci["name"]] and run["types"] == ["completed"] and run["branches"] == ["main"], "it follows the workflow named %r finishing on main" % ci["name"])
check("push" in ci["_on"] and ci["_on"]["push"]["branches"] == ["main"], "and CI does run on every push to main, so there is always a CI run to follow")
ci_runs = " ".join(st.get("run", "") for j in ci["jobs"].values() for st in j["steps"])
check(all(c in ci_runs for c in ("tests/run_all.py", "tests/test_js_data.mjs", "tests/smoke.cjs", "tests/a11y.cjs")), "and CI runs every test the docs list: the Python tests, the JavaScript data tests, the smoke test and the accessibility test")
check(set(on) == {"workflow_run", "workflow_dispatch"}, "the only triggers are that and a manual run (no schedule, no push of its own): %s" % sorted(on))
check(wf["concurrency"]["group"] == "publish-site" and wf["concurrency"]["cancel-in-progress"] is False and nightly["concurrency"]["group"] != "publish-site",
      "publishes queue behind each other, apart from the nightly capture's group (a publish never cancels a capture)")
check(wf["permissions"] == {"contents": "write"}, "it may write contents (the gh-pages push) and nothing else")
job = wf["jobs"]["publish"]
steps = job["steps"]
check(steps[0]["uses"].startswith("actions/checkout@") and "workflow_run.head_sha" in steps[0]["with"]["ref"] and "'main'" in steps[0]["with"]["ref"],
      "it checks out the commit CI passed, or main for a manual run")
check("publish_pages.sh" in steps[1]["run"], "and runs the shared publish script")
check(not re.search(r"d7_|d8_|python|rrc\.texas|oklahoma\.gov|curl|wget", text + open(SCRIPT).read(), re.I), "nothing in it can reach the Railroad Commission or the OCC")
nightly_publish = [s for s in nightly["jobs"]["capture"]["steps"] if s.get("name") == "Publish the site to GitHub Pages"]
check(len(nightly_publish) == 1 and "publish_pages.sh" in nightly_publish[0]["run"], "the nightly capture publishes with the same script")


def cond(event, conclusion=None, source=None):
    expr = job["if"].replace("${{", "").replace("}}", "").strip()
    py = expr.replace("&&", " and ").replace("||", " or ")
    py = re.sub(r"github\.event\.workflow_run\.(\w+)", r"wr['\1']", py)
    py = py.replace("github.event_name", "event")
    return eval(py, {"event": event, "wr": {"conclusion": conclusion, "event": source}})


check(cond("workflow_dispatch") is True, "a manual run always goes ahead")
check(cond("workflow_run", "success", "push") is True, "a green CI run for a push to main publishes")
check(cond("workflow_run", "failure", "push") is False and cond("workflow_run", "cancelled", "push") is False and cond("workflow_run", "skipped", "push") is False,
      "a failed, cancelled or skipped CI run does not")
check(cond("workflow_run", "success", "pull_request") is False and cond("workflow_run", "success", "workflow_dispatch") is False, "nor does a green CI run that was not a push to main")

# ---- the script, against a throwaway clone with a local bare origin
REAL_GIT = shutil.which("git")
TMP = tempfile.mkdtemp()
ORIGIN = os.path.join(TMP, "origin.git")


def git(*a, cwd, env=None):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
    e.update(env or {})
    r = subprocess.run([REAL_GIT, *a], cwd=cwd, capture_output=True, text=True, env=e)
    return r.stdout.strip()


def tree(root):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = open(p, "rb").read()
    return out


def make_origin():
    """A main branch holding the site (copied from the committed site/public) and a gh-pages branch holding an old one."""
    shutil.rmtree(ORIGIN, ignore_errors=True)
    seed = os.path.join(TMP, "seed")
    shutil.rmtree(seed, ignore_errors=True)
    os.makedirs(seed)
    git("init", "-q", "-b", "main", cwd=seed)
    files = subprocess.run([REAL_GIT, "ls-files", "-z", "site/public"], cwd=REPO, capture_output=True).stdout.decode().split("\0")
    for f in files:
        if f and os.path.isfile(os.path.join(REPO, f)):
            os.makedirs(os.path.dirname(os.path.join(seed, f)), exist_ok=True)
            shutil.copy2(os.path.join(REPO, f), os.path.join(seed, f))
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "the site", cwd=seed)
    git("checkout", "-q", "--orphan", "gh-pages", cwd=seed)
    git("rm", "-rfq", ".", cwd=seed)
    for f, body in {"index.html": "old", "js/main.js": "old", "data/meta.json": "{}", "stale.txt": "removed in the next publish", ".nojekyll": ""}.items():
        os.makedirs(os.path.dirname(os.path.join(seed, f)) or seed, exist_ok=True)
        open(os.path.join(seed, f), "w").write(body)
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "an old site", cwd=seed)
    subprocess.run([REAL_GIT, "clone", "-q", "--bare", seed, ORIGIN], check=True, capture_output=True)


def clone(name):
    w = os.path.join(TMP, name)
    shutil.rmtree(w, ignore_errors=True)
    subprocess.run([REAL_GIT, "clone", "-q", "--branch", "main", ORIGIN, w], check=True, capture_output=True)
    git("config", "user.name", "publish-site", cwd=w)
    git("config", "user.email", "actions@users.noreply.github.com", cwd=w)
    return w


def run_script(w, extra_env=None, path=None):
    env = {"PATH": path or os.environ["PATH"], "HOME": TMP, "RUNNER_TEMP": os.path.join(TMP, "runner-" + os.path.basename(w)), "PUBLISH_RETRY_PAUSE": "0"}
    env.update(extra_env or {})
    os.makedirs(env["RUNNER_TEMP"], exist_ok=True)
    r = subprocess.run(["bash", SCRIPT], cwd=w, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def site_of(w):
    expect = {}
    root = os.path.join(w, "site", "public")
    for rel, body in tree(root).items():
        expect[rel] = body
    expect[".nojekyll"] = b""
    return expect


def pages_tip():
    return git("rev-parse", "gh-pages", cwd=ORIGIN)


def pages_files():
    out = os.path.join(TMP, "check-pages")
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run([REAL_GIT, "clone", "-q", "--branch", "gh-pages", ORIGIN, out], check=True, capture_output=True)
    return tree(out), out


make_origin()
w = clone("work")
before = pages_tip()
head = git("rev-parse", "--short", "HEAD", cwd=w)
code, out = run_script(w)
files, pages = pages_files()
check(code == 0 and "published the site from " + head in out, "it publishes (exit %d): %s" % (code, out.strip()[-80:]))
check(files == site_of(w), "gh-pages now holds exactly the committed site/public and .nojekyll (%d files; the old index.html and stale.txt are gone)" % len(files))
check(git("log", "-1", "--format=%s", cwd=pages) == "Publish the site (from %s)" % head and git("rev-list", "--count", "gh-pages", cwd=ORIGIN) == "2" and git("merge-base", "--is-ancestor", before, "gh-pages", cwd=ORIGIN) == "",
      "as one new commit on top of the old ones, titled with the source commit (nothing rewritten)")

tip = pages_tip()
code, out = run_script(w)
check(code == 0 and "already current" in out and pages_tip() == tip, "run again with nothing new it says so, succeeds and adds no commit (exit %d)" % code)

# a copy that is not a site is refused
make_origin()
w = clone("work-broken")
git("rm", "-q", "site/public/data/meta.json", cwd=w)
git("commit", "-q", "-m", "oops", cwd=w)
tip = pages_tip()
code, out = run_script(w)
check(code == 1 and "incomplete" in out and pages_tip() == tip, "a copy without data/meta.json is not published and the run fails (exit %d)" % code)

# another publish got there first: the push is refused once, the copy is rebuilt from the new tip and goes out
shim_dir = os.path.join(TMP, "shim")
os.makedirs(shim_dir, exist_ok=True)
shim = os.path.join(shim_dir, "git")
open(shim, "w").write("""#!/bin/bash
# a git that lets another publisher push to gh-pages just before this one's push (once, or every time with RACE_ALWAYS)
case " $* " in
  *" push "*)
    if [ -n "${RACE_ALWAYS:-}" ] || [ ! -e "$RACE_MARK" ]; then
      touch "$RACE_MARK"
      n=$(( $(cat "$RACE_COUNT" 2>/dev/null || echo 0) + 1 )); echo $n > "$RACE_COUNT"
      (
        tmp="$(mktemp -d)"
        "$REAL_GIT" clone -q --branch gh-pages "$ORIGIN" "$tmp/o" && cd "$tmp/o" \\
          && echo "raced $n" > "raced-$n.txt" && "$REAL_GIT" add -A \\
          && "$REAL_GIT" -c user.name=x -c user.email=x@example.com commit -q -m "race $n" && "$REAL_GIT" push -q origin HEAD:gh-pages
      ) >/dev/null 2>&1
    fi;;
esac
exec "$REAL_GIT" "$@"
""")
os.chmod(shim, 0o755)
race_env = {"REAL_GIT": REAL_GIT, "ORIGIN": ORIGIN, "RACE_MARK": os.path.join(TMP, "race-mark"), "RACE_COUNT": os.path.join(TMP, "race-count")}
shim_path = shim_dir + os.pathsep + os.environ["PATH"]

make_origin()
w = clone("work-race")
for f in (race_env["RACE_MARK"], race_env["RACE_COUNT"]):
    if os.path.exists(f):
        os.remove(f)
code, out = run_script(w, race_env, shim_path)
files, pages = pages_files()
subjects = git("log", "--format=%s", cwd=pages).splitlines()
check(code == 0 and "starting again" in out and "published the site from" in out, "a refused push is retried from the branch's new tip and goes out (exit %d)" % code)
check(files == site_of(w) and "race 1" in subjects and subjects[0].startswith("Publish the site"), "the other publisher's commit stays in the history and the site on top of it is complete: %s" % subjects[:3])

make_origin()
w = clone("work-always")
for f in (race_env["RACE_MARK"], race_env["RACE_COUNT"]):
    if os.path.exists(f):
        os.remove(f)
code, out = run_script(w, dict(race_env, RACE_ALWAYS="1"), shim_path)
check(code == 1 and "giving up" in out and open(race_env["RACE_COUNT"]).read().strip() == "4", "if the push is refused four times in a row it gives up and the run fails (exit %d, %s tries)" % (code, open(race_env["RACE_COUNT"]).read().strip()))

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
