"""Tests that a download past its time budget stops (TooSlow, no retry) and that a pack preview that hits it is skipped cleanly.

Run: python3 -I tests/test_d7_deadline.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import importlib.util
import io
import os
import sys
import tempfile
import time
import types
from datetime import date

sys.path.insert(0, PIPE)
import rrc_share as R  # noqa: E402

spec = importlib.util.spec_from_file_location("d7", _os.path.join(PIPE, "d7_daily.py"))
d7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d7)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class Headers:
    def __init__(self, d):
        self.d = d

    def get_all(self, k):
        return []

    def get(self, k, default=None):
        return self.d.get(k, default)


class Resp:
    status = 200

    def __init__(self, chunks, delay):
        self.chunks, self.delay, self.n = chunks, delay, 0
        self.headers = Headers({"Content-Type": "application/force-download", "Content-Length": str(chunks * (1 << 20))})

    def read(self, n=None):
        if self.n >= self.chunks:
            return b""
        time.sleep(self.delay)
        self.n += 1
        return b"x" * (1 << 20)


class Conn:
    def __init__(self, resp):
        self.resp, self.requests = resp, 0

    def request(self, *a, **k):
        self.requests += 1

    def getresponse(self):
        return self.resp

    def close(self):
        pass


# a slow stream with a one-second budget stops after about a second and is not retried
s = R.Session(attempts=5)
s.conn = Conn(Resp(chunks=60, delay=0.3))
s.deadline = time.time() + 1.0
t = time.time()
try:
    s.request("POST", "/link/x?y=1", b"", {}, sink=io.BytesIO())
    check(False, "the slow download should raise")
except R.TooSlow as e:
    took = time.time() - t
    check(took < 3.0 and s.retries == 0 and s.conn.requests == 1, "a slow download past its budget raises TooSlow in %.1f s without a retry" % took)
    check("time budget" in str(e) and "y=1" not in str(e), "TooSlow says what happened without the query string")
check(not issubclass(R.TooSlow, OSError), "TooSlow is not an OSError, so the retry loop cannot swallow it")

# no deadline: the same stream, short, completes
s = R.Session(attempts=5)
s.conn = Conn(Resp(chunks=3, delay=0.01))
sink = io.BytesIO()
status, _h, body = s.request("POST", "/x", b"", {}, sink=sink)
check(status == 200 and len(sink.getvalue()) == 3 << 20 and body == b"", "without a deadline the download completes")
# a deadline in the future does not interfere
s = R.Session(attempts=5)
s.conn = Conn(Resp(chunks=3, delay=0.01))
s.deadline = time.time() + 30
sink = io.BytesIO()
s.request("POST", "/x", b"", {}, sink=sink)
check(len(sink.getvalue()) == 3 << 20, "a deadline that is not reached does not interfere")


# pack_preview: a download that gives up is skipped, the partial file is removed, the dataset stays
class FakeShare:
    def __init__(self):
        self.s = R.Session(attempts=18)

    def download(self, name, dest):
        os.makedirs(dest, exist_ok=True)
        open(os.path.join(dest, name), "wb").write(b"half a zip")
        raise R.TooSlow("download of x went past its time budget")


logged = []
d7.log = logged.append
tmp = tempfile.mkdtemp()
ctx = {"R": date(2026, 10, 30), "dl": os.path.join(tmp, "dl"), "img_out": os.path.join(tmp, "img"), "stage": None}
sh = FakeShare()
res = d7.pack_preview(sh, ctx, "complimages", "10-29-2026.zip")
dest = os.path.join(ctx["dl"], "pack-complimages-2026-10-30")
check(res == (None, None) and any("SKIPPED" in m and "time budget" in m for m in logged), "pack_preview: a download over its budget gives no preview and nothing staged, with a log line")
check(os.path.isdir(dest) and os.listdir(dest) == [], "pack_preview: the half-downloaded file is deleted")
check(sh.s.deadline is None and sh.s.attempts == 3 and sh.s.timeout == 60, "pack_preview: three tries, 60 s reads, and the deadline is cleared afterwards (attempts=%d timeout=%d)" % (sh.s.attempts, sh.s.timeout))

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
