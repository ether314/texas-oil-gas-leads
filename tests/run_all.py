"""Runs every Python test in this folder, each in its own process (python3 -I), and fails if any does.

Run: python3 -I tests/run_all.py [name-fragment ...]      (a fragment limits the run to the files whose name contains it)
A file that fails prints every failing check, then the last lines of its output.
The browser smoke test is separate: node tests/smoke.cjs (see tests/README.md).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
wanted = sys.argv[1:]
names = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py") and (not wanted or any(w in f for w in wanted)))
failed = []
for name in names:
    t = time.time()
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, name)], capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    ok = r.returncode == 0
    print("%-28s %-4s %5.1fs  %s" % (name, "ok" if ok else "FAIL", time.time() - t, tail[:90]))
    if not ok:
        failed.append(name)
        lines = (r.stdout + r.stderr).strip().splitlines()
        # every check that failed, wherever it is in the output (the last lines alone can be a run of passing checks: a failure in CI once left no trace but "FAILED: 1"), then the end
        bad = [l.strip() for l in lines if l.lstrip().startswith("FAIL") and not l.lstrip().startswith("FAILED")]
        if bad:
            print("    the failing checks:")
            print("\n".join("      " + l[:300] for l in bad[:40]))
        print("\n".join("    " + l for l in lines[-25:]))
print()
print("FAILED: " + ", ".join(failed) if failed else "all %d test files passed" % len(names))
sys.exit(1 if failed else 0)
