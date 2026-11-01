"""Runs every Python test in this folder, each in its own process (python3 -I), and fails if any does.

Run: python3 -I tests/run_all.py [name-fragment ...]      (a fragment limits the run to the files whose name contains it)
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
        fails = [l for l in lines if l.lstrip().startswith("FAIL ")]  # the failing checks themselves: a long test prints them well before its last 25 lines (a CI run of 2026-11-01 failed and the log did not say which check)
        print("\n".join("    " + l for l in fails[:40] + [l for l in lines[-25:] if l not in fails]))
print()
print("FAILED: " + ", ".join(failed) if failed else "all %d test files passed" % len(names))
sys.exit(1 if failed else 0)
