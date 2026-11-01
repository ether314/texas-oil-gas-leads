#!/usr/bin/env python3
"""D11: run every state's producer (d11_nat_<st>.py), each isolated, then rebuild national.json. What the weekly workflow calls.

A producer reads one agency's public files and writes site/public/data/nat/<ST>.json. Agencies have outages, change their files and sometimes refuse a runner, so each producer
runs in its own process (python3 -I), under a time limit, and can only ever affect its own file:

  - a producer that exits non-zero, runs out of time, or leaves a file that does not validate has its file put back exactly as it was (or removed, if it did not exist);
  - a producer the server refused (exit 2, `Refused`: a 401, 403 or 429, or a blocked network) is not retried and is not an error: its file stays as committed and the summary says so;
  - the others go ahead, then national.json is rebuilt from whatever files are there; if that fails, national.json is put back too.

The whole run has a budget: a producer that cannot start with its own limit left is skipped (and listed), so a slow agency cannot starve the rest or the commit and publish after.
Exit code: 0 when every producer that ran either wrote a good file, changed nothing, or was refused; 1 when any failed, timed out or was skipped for want of time, or national.json could not be rebuilt.

  python3 -I site/pipeline/d11_nat_run.py                     every producer
  python3 -I site/pipeline/d11_nat_run.py --only ND KS        some
  python3 -I site/pipeline/d11_nat_run.py --budget 2400       seconds in all (default 2400)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_build as B  # noqa: E402
import d11_nat_common as C  # noqa: E402

PRODUCER = re.compile(r"d11_nat_([a-z]{2})\.py")
DEFAULT_TIMEOUT = 600  # seconds one producer may take; a big download gets more in TIMEOUTS
# Kentucky, Indiana and West Virginia read one file per week: the first read of their history (17, 9 and 30 minutes) was done by hand and is committed, so a weekly run
# reads only the newest weeks (about 3, 2 and 3 minutes). Their limit leaves room for a slow server and no more: without the committed file they fail here, by design.
TIMEOUTS = {"KY": 900, "IN": 900, "WV": 900}
log = C.log


def producers(folder=HERE):
    """{ST: path} of the producers in `folder`, in jurisdiction order."""
    found = {}
    for name in os.listdir(folder):
        m = PRODUCER.fullmatch(name)
        if m and m.group(1).upper() in C.NAME_OF:
            found[m.group(1).upper()] = os.path.join(folder, name)
    order = [sid for sid, _ in C.JURISDICTIONS]
    return {sid: found[sid] for sid in order if sid in found}


def read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def restore(path, before):
    if before is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "wb") as f:
            f.write(before)


def run_one(sid, script, nat_dir, timeout, python=sys.executable):
    """Runs one producer and returns {state, status, seconds, note}: status is 'wrote', 'unchanged', 'refused', 'failed', 'invalid' or 'timeout'. The state's file is restored in every
    status but 'wrote' and 'unchanged'. The producer is given the folder it must write to through D11_NAT_DIR, so a test (or a dry run) never touches the real one."""
    path = os.path.join(nat_dir, sid + ".json")
    before = read(path)
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}  # a producer parses downloaded files: it holds no token
    env["D11_NAT_DIR"] = nat_dir
    t0 = time.time()
    try:
        r = subprocess.run([python, "-I", script], capture_output=True, text=True, timeout=timeout, env=env, cwd=os.path.dirname(script))
    except subprocess.TimeoutExpired:
        restore(path, before)
        return {"state": sid, "status": "timeout", "seconds": time.time() - t0, "note": "ran out of its %d seconds" % timeout}
    secs = time.time() - t0
    tail = C.privacy_check.clean_error((r.stdout.strip().splitlines() or [""])[-1], 200)
    if r.returncode == 2:
        restore(path, before)
        return {"state": sid, "status": "refused", "seconds": secs, "note": tail or "the source refused this machine"}
    if r.returncode != 0:
        restore(path, before)
        return {"state": sid, "status": "failed", "seconds": secs, "note": "exit %d: %s" % (r.returncode, tail)}
    after = read(path)
    if after is None:
        return {"state": sid, "status": "failed", "seconds": secs, "note": "exit 0 but no file was written"}
    bad = [x for x in C.check_dir(nat_dir) if x.startswith(sid + ":")]
    if bad:
        restore(path, before)
        return {"state": sid, "status": "invalid", "seconds": secs, "note": "; ".join(bad[:2])}
    return {"state": sid, "status": "unchanged" if after == before else "wrote", "seconds": secs, "note": tail}


def rebuild(nat_dir, out):
    """Rebuilds national.json from the files in `nat_dir` (and the four earlier jurisdictions' files); returns None on success, else a reason. The old file is put back on failure."""
    before = read(out)
    saved = B.NAT
    try:
        B.NAT = nat_dir
        doc = B.build()
        bad = B.validate(doc)
        if bad:
            return "; ".join(bad[:3])
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp, out)
        return None
    except Exception as e:  # noqa: BLE001
        restore(out, before)
        return C.privacy_check.clean_error(e)
    finally:
        B.NAT = saved


def main(argv=None, folder=HERE, nat_dir=C.OUT, out=B.OUT):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--budget", type=int, default=2400)
    a = ap.parse_args(argv)
    found = producers(folder)
    if a.only:
        want = {x.upper() for x in a.only}
        found = {k: v for k, v in found.items() if k in want}
    start = time.time()
    results = []
    for sid, script in found.items():
        left = a.budget - (time.time() - start)
        limit = min(TIMEOUTS.get(sid, DEFAULT_TIMEOUT), left)
        if limit < 20:
            results.append({"state": sid, "status": "skipped", "seconds": 0, "note": "no time left in the run's budget"})
            continue
        res = run_one(sid, script, nat_dir, limit)
        results.append(res)
        log("%s: %s (%.0f s)%s" % (sid, res["status"], res["seconds"], " - " + res["note"] if res["note"] else ""))
    why = rebuild(nat_dir, out)
    if why:
        log("national.json: could not be rebuilt (%s); left as committed" % why)
    bad = [r for r in results if r["status"] in ("failed", "invalid", "timeout", "skipped")]
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    log("producers: %d (%s)%s" % (len(results), ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) or "none", "; national.json rebuilt" if not why else ""))
    for r in bad:
        log("::warning title=%s::%s %s" % (r["state"], r["status"], r["note"]))
    return 1 if bad or why else 0


if __name__ == "__main__":
    sys.exit(main())
