"""Tests for whole nights of site/pipeline/d7_daily.py, the Texas Daily-report producer: main() is run against scratch folders with the
network blocked (every socket refuses to connect), the RRC's file shares replaced by a fake that serves synthetic listings and files
(a Daily Permit File, pending-permit sets, a completions zip, image-pack names) and the clock fixed, and what it leaves behind is
read back. The rules inside the producer are in the test_d7_* files beside this one; this file is for the nights when the RRC's
servers or files are not what the notes describe, because those decide whether the archive keeps telling the truth while nobody is
watching. An independent review (a fresh agent, offline, with repro scripts) found each of these by trying it:

  - the map service answering badly (a body cut short, a garbage status line, JSON that is not a result) ended the night after
    every download had finished, and a refusing service was asked again for every report day
  - a later capture of a day that read fewer files (the backup run when the RRC is flaky) or lost its document links replaced the
    better report; a rebuilt day written partial was never built again
  - one damaged file in the archive (a truncated day file, one with another shape, a series file of another shape) crashed every
    night after it
  - the text of a failure (a server's error page, a path on the runner) was published into the day files

Mutants put the old behavior back, one fix at a time, and require the checks to notice.

Run: python3 -I tests/test_d7_nights.py"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)


# ---------------------------------------------------------------- no network, whatever happens
class NetworkForbidden(Exception):
    pass


def _no_connect(*a, **k):
    raise NetworkForbidden("a real network connection was attempted")


socket.socket.connect = _no_connect
socket.create_connection = _no_connect

import rrc_share  # noqa: E402

spec = importlib.util.spec_from_file_location("d7", os.path.join(PIPE, "d7_daily.py"))
d7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d7)
import d7_locate  # noqa: E402
import d7_release  # noqa: E402
import d7_packs  # noqa: E402

D = date
TMP = tempfile.mkdtemp(prefix="d7-nights-")
NOW = datetime(2026, 11, 1, 3, 15, tzinfo=timezone.utc)  # 22:15 CDT on Sat Oct 31: tonight's first scheduled capture (report day Oct 31)

OPERATORS = json.load(open(os.path.join(REPO, "site/public/data/operators.json")))["rows"]
NAMED = [r[1] for r in OPERATORS[:6]]  # six operator numbers the report may name


# ---------------------------------------------------------------- synthetic RRC files
def rec01(n):
    s = "01%07d" % n
    return s + " " * (212 - len(s))


def rec02(n, county="317", dist="10", depth=9800, op=None, typ="01", received="20261026", issued="20261029", amended="00000000",
          horiz=False, direc=False, api=None):
    op = op or NAMED[0]
    L = [" "] * 510

    def put(a, b, s):
        s = str(s)
        assert len(s) == b - a, (a, b, s)
        L[a:b] = list(s)
    put(0, 2, "02")
    put(2, 9, "%07d" % n)
    put(11, 14, county)
    put(46, 48, dist)
    put(54, 59, "%05d" % depth)
    put(59, 65, op)
    put(65, 67, typ)
    put(121, 129, received)
    put(129, 137, issued)
    put(137, 145, amended)
    L[481] = "Y" if direc else "N"
    L[493] = "Y" if horiz else "N"
    put(502, 510, api or (county + "%05d" % (n % 100000)))
    return "".join(L)


def daf_bytes(perms):
    """perms: list of dicts for rec02 (n required). Returns a CRLF daf420.dat image."""
    lines = []
    for p in perms:
        lines.append(rec01(p["n"]))
        kw = {k: v for k, v in p.items() if k != "xy"}
        lines.append(rec02(**kw))
        if p.get("xy"):
            lines.append("14:  %.5f %.5f" % (p["xy"][1], p["xy"][0]))  # "longitude latitude"
    return ("\r\n".join(lines) + "\r\n").encode("latin-1")


def business_days(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def month_perms(first, last, per_day=30, start=1000, counties=("317", "329", "461", "475")):
    out, n = [], start
    for d in business_days(first, last):
        for i in range(per_day):
            out.append({"n": n, "county": counties[i % len(counties)], "issued": d.strftime("%Y%m%d"),
                        "received": (d - timedelta(days=3)).strftime("%Y%m%d"), "horiz": i % 3 == 0,
                        "op": NAMED[i % len(NAMED)], "depth": 8000 + i * 100})
            n += 1
    return out


PEND_H = ["UNIVERSAL_DOC_NO", "OPERATOR_NUMBER", "DISTRICT", "TOTAL_DEPTH", "DEFAULT_HORIZANTAL", "DEFAULT_DIRECTIONAL", "EXPEDITE_FLAG",
          "IS_AMENDMENT", "FILING_PURPOSE_CODE", "SUBMIT_DATE"]
WB_H = ["UNIVERSAL_DOC_NO", "COUNTY_CODE", "WELL_NUMBER"]


def delimited(header, rows, blank=True):
    text = "}".join(header) + "}\r\n" + ("\r\n" if blank else "")
    for r in rows:
        text += '"' + '"}"'.join(r) + '"}\r\n'
    return text.encode("latin-1")


def pending_pair(stamp, n=3, submit="29-OCT-26 04.15.00.000000 PM", header=PEND_H):
    docs = ["%s%02d" % (stamp, i) for i in range(n)]
    prm = delimited(header, [[d, NAMED[i % 3], "08", "9000", "Y", "N", "Y" if i == 0 else "N", "N", "01", submit] for i, d in enumerate(docs)])
    wb = delimited(WB_H, [[d, "329", "1H"] for d in docs])
    return prm, wb


def packet_text(op=None, purpose="1", ctype="1", district="08", county="329", gas=False, profile="1", approved="10/30/2026", ip=120.0):
    cols = [""] * 41
    cols[0] = "PACKET"
    cols[4], cols[5], cols[11], cols[12], cols[27], cols[28], cols[32], cols[40] = approved, op or NAMED[0], purpose, ctype, district, county, "1" if gas else "2", profile
    return ("H{W-2 Data,P-4 Data{x\r\n" + "{".join(cols) + "\r\nW-2{" + "{".join(["a"] * 13 + [str(ip)]) + "\r\n").encode("latin-1")


def completions_zip(path_or_none=None, n_approved=4, n_submitted=2, bad_members=False):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        t = 100
        for i in range(n_approved):
            z.writestr("08/trackingNo_%d/packetData_%d_Approved.dat" % (t, t), packet_text(purpose="1" if i % 2 == 0 else "7"))
            t += 1
        for i in range(n_submitted):
            z.writestr("08/trackingNo_%d/packetData_%d_Submitted.dat" % (t, t), packet_text())
            t += 1
        if bad_members:
            z.writestr("08/trackingNo_999/packetData_999_Approved.dat", b"not a packet\r\n")
    return bio.getvalue()


def row(name, modified, size=1000, content=None):
    return {"name": name, "modified": modified, "bytes": size, "size": "%d B" % size, "link": "fileTable:0:" + name, "content": content}


# ---------------------------------------------------------------- the world the fake shares serve
class World:
    def __init__(self):
        self.shares = {}      # guid -> list of rows (dicts from row())
        self.fail_open = {}   # guid -> message
        self.fail_dl = {}     # (guid, name) -> exception instance
        self.hooks = {}       # ("open"|"download", guid) -> callable run first (to block or fail)
        self.unsorted = set()  # guids whose listing comes back in name order, not date order
        self.catalog_html = None  # None: the data sets page is down
        self.gis = "ok"       # "ok" | callable(req) | exception instance raised by urlopen
        self.events = []      # ("open", guid), ("download", guid, name), ("http", url)
        self.gis_calls = 0

    def listing(self, guid):
        rows = list(self.shares.get(guid, []))
        if guid in self.unsorted:
            return sorted(rows, key=lambda r: r["name"])
        return sorted(rows, key=lambda r: r["modified"] or "", reverse=True)


class FakeShare:
    world = None

    def __init__(self, guid, sess=None):
        if not isinstance(guid, str) or not guid:
            raise ValueError("bad share guid")
        self.guid = guid
        self.s = sess or types.SimpleNamespace(retries=0, attempts=18, timeout=120, deadline=None)
        self.total, self.links = 0, {}

    def open(self):
        W = FakeShare.world
        W.events.append(("open", self.guid))
        if "open" in {k[0] for k in W.hooks if k[1] == self.guid}:
            W.hooks[("open", self.guid)]()
        if self.guid in W.fail_open:
            raise rrc_share.ShareError(W.fail_open[self.guid])
        self.total = len(W.shares.get(self.guid, []))
        return []

    def newest(self, n):
        rows = FakeShare.world.listing(self.guid)[:n]
        self.links = {r["name"]: r["link"] for r in rows}
        return [{k: v for k, v in r.items() if k != "content"} for r in rows]

    def download(self, name, dest):
        W = FakeShare.world
        W.events.append(("download", self.guid, name))
        if ("download", self.guid) in W.hooks:
            W.hooks[("download", self.guid)](name)
        if (self.guid, name) in W.fail_dl:
            raise W.fail_dl[(self.guid, name)]
        src = next((r for r in W.shares.get(self.guid, []) if r["name"] == name), None)
        if src is None or name not in self.links:
            raise rrc_share.ShareError("%s is not in the last listing of share %s" % (name, self.guid))
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, name)
        with open(path, "wb") as f:
            f.write(src["content"] if src["content"] is not None else b"")
        return path


class Reply:
    def __init__(self, data, headers=None):
        self.data, self.headers = data, headers or {}

    def read(self, n=-1):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen_factory(W):
    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        W.events.append(("http", url))
        if url == d7.DATA_PAGE:
            if W.catalog_html is None:
                raise urllib.error.URLError("[Errno 111] Connection refused")
            return Reply(W.catalog_html.encode())
        if url.startswith(d7_locate.LAYER):
            W.gis_calls += 1
            if isinstance(W.gis, BaseException):
                raise W.gis
            if callable(W.gis):
                return W.gis(req)
            body = urllib.parse.parse_qs(req.data.decode())["where"][0]
            apis = [a for a in body[body.index("(") + 1:-1].replace("'", "").split(",") if a]
            feats = [{"attributes": {"API": a, "GIS_LAT83": 31.0 + int(a[3:]) % 1000 / 1000.0, "GIS_LONG83": -101.5, "GIS_SYMBOL_DESCRIPTION": "Permitted Location"}} for a in apis]
            return Reply(json.dumps({"features": feats}).encode())
        raise NetworkForbidden("unexpected URL " + url)
    return urlopen


# ---------------------------------------------------------------- a healthy world for the night of Oct 31
G = {s["id"]: s["guid"] for s in d7.DATASETS}


def healthy_world(daf=None, with_packs=False, since=D(2026, 10, 20), pend_since=D(2026, 10, 26)):
    """Everything the RRC lists on the night of Sat Oct 31 (Central), the way the notes describe it."""
    W = World()
    daf = daf if daf is not None else daf_bytes(month_perms(D(2026, 10, 1), D(2026, 10, 29)))
    W.shares[G["permits"]] = [row("daf420.dat", "2026-10-30T09:45:28", len(daf), daf), row("daf420.dat.10-29-2026", "2026-10-30T07:50:12", 1000, b"")]
    pend = []
    for d in business_days(pend_since, D(2026, 10, 30)):  # 11 AM sets land that afternoon
        stamp = d.strftime("%Y%m%d") + "110808"
        prm, wb = pending_pair(stamp)
        t0 = datetime.combine(d, datetime.min.time()) + timedelta(hours=16, minutes=7)
        pend += [row("dp_drilling_permit_pending_%s.txt" % stamp, t0.isoformat(), len(prm), prm),
                 row("dp_wellbore_pending_%s.txt" % stamp, (t0 + timedelta(minutes=90)).isoformat(), len(wb), wb)]
        pend += [row("dp_filler%02d_pending_%s.txt" % (k, stamp), (t0 + timedelta(minutes=10 * k)).isoformat(), 10, b"") for k in (1, 2, 3, 4, 5, 6, 7, 8, 10)]
    d = pend_since
    while d <= D(2026, 10, 30):  # 5 PM sets land after midnight
        stamp = d.strftime("%Y%m%d") + "170807"
        prm, wb = pending_pair(stamp)
        t0 = datetime.combine(d + timedelta(days=1), datetime.min.time()) + timedelta(minutes=6)
        pend += [row("dp_drilling_permit_pending_%s.txt" % stamp, t0.isoformat(), len(prm), prm),
                 row("dp_wellbore_pending_%s.txt" % stamp, (t0 + timedelta(minutes=90)).isoformat(), len(wb), wb)]
        pend += [row("dp_filler%02d_pending_%s.txt" % (k, stamp), (t0 + timedelta(minutes=10 * k)).isoformat(), 10, b"") for k in (1, 2, 3, 4, 5, 6, 7, 8, 10)]
        d += timedelta(days=1)
    W.shares[G["pending"]] = pend
    comp, d = [], since
    while d <= D(2026, 10, 30):
        z = completions_zip()
        comp.append(row(d.strftime("%m-%d-%Y.zip"), (d + timedelta(days=1)).isoformat() + "T02:16:00", len(z), z))
        d += timedelta(days=1)
    W.shares[G["completions"]] = comp
    for ds, hhmm in (("dirsurveys", "07:55:00"), ("complimages", "02:20:00")):
        rows, d = [], since
        while d <= D(2026, 10, 30):
            rows.append(row(d.strftime("%m-%d-%Y.zip"), (d + timedelta(days=1)).isoformat() + "T" + hhmm, 5_000_000, b"PK"))
            d += timedelta(days=1)
        W.shares[G[ds]] = rows
    rows = []
    for d in business_days(since, D(2026, 10, 30)):
        rows.append(row("subscriptions_%s.zip" % d.isoformat(), (d + timedelta(days=1)).isoformat() + "T10:18:07", 30_000_000, b"PK"))
        rows += [row("subscriptions_%s_district%02d.zip" % (d.isoformat(), k), (d + timedelta(days=1)).isoformat() + "T10:%02d:07" % (6 + k), 3_000_000, b"PK") for k in range(1, 12)]
    W.shares[G["w1images"]] = rows
    W.shares[d7.EOM_GUID] = [row("daf420.dat.09-30-2026", "2026-10-01T07:51:00", 1000, daf_bytes(month_perms(D(2026, 9, 1), D(2026, 9, 30), start=500000)))]
    for m in d7.MONTHLY:
        W.shares[m["guid"]] = [row(m["file"], "2026-10-08T06:01:23", 1000, b"x")]
    return W


# ---------------------------------------------------------------- run one night, offline, read it back
def central(now):
    from zoneinfo import ZoneInfo
    return now.astimezone(ZoneInfo("America/Chicago"))


def fresh(name):
    p = os.path.join(TMP, name)
    shutil.rmtree(p, ignore_errors=True)
    os.makedirs(p)
    return p


def make_fake_dt(now):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    return FakeDT


def run_night(W, out, argv=(), now=NOW, dl=None, patch=None):
    """main() once, as the workflow runs it. Returns (exit code or 'CRASH ...', log text, exception or None)."""
    dl = dl or tempfile.mkdtemp(dir=TMP)
    FakeShare.world = W
    saved = (d7.Share, d7.Session, d7.central_now, urllib.request.urlopen, d7.time.sleep, sys.argv, d7.datetime)
    d7.datetime = make_fake_dt(now)
    d7.Share = FakeShare
    d7.Session = lambda *a, **k: types.SimpleNamespace(retries=0, attempts=18, timeout=120, deadline=None)
    d7.central_now = lambda: central(now)
    urllib.request.urlopen = fake_urlopen_factory(W)
    d7.time.sleep = lambda s: None
    sys.argv = ["d7_daily.py", "--out", out, "--dl", dl] + list(argv)
    buf, code, exc = io.StringIO(), 0, None
    try:
        with contextlib.redirect_stdout(buf):
            try:
                if patch:
                    patch()
                d7.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
                if isinstance(e.code, str):
                    buf.write("EXIT: %s\n" % e.code)
    except Exception as e:  # noqa: BLE001 - a crash is a result of its own
        import traceback
        code, exc = "CRASH %s: %s" % (type(e).__name__, e), e
        buf.write(traceback.format_exc())
    finally:
        d7.Share, d7.Session, d7.central_now, urllib.request.urlopen, d7.time.sleep, sys.argv, d7.datetime = saved
    return code, buf.getvalue(), exc


def report(out, day):
    try:
        with open(os.path.join(out, day + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def index(out):
    try:
        with open(os.path.join(out, "index.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def dataset(rep, ds):
    return [d for d in rep["datasets"] if d["id"] == ds][0]


def show(title):
    print("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


# ================================================================================================ the checks
ARGS = ["--backfill", "7", "--skip-if-captured"]  # what the scheduled runs pass (the workflow adds --packs and --publish-docs)
GAP_CASES = []


def n_read(rep):
    return sum(1 for d in (rep or {}).get("datasets", []) if not d.get("error"))


def mk_check(fails, quiet):
    def check(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)
    return check


def s_healthy(check):
    out = fresh("healthy")
    code, text, _ = run_night(healthy_world(), out, ARGS)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and n_read(rep) == 6 and (rep.get("permits") or {}).get("newDrill") == 30 and (rep.get("completions") or {}).get("approved") == 4,
          "a healthy night: exit 0, all six files read, 30 new-drill permits and 4 approved completions in the report (%s, %s, %s)" % (code, rep.get("status"), n_read(rep)))


def s_locator(check):
    import http.client

    class Cut(Reply):
        """a reply whose body is cut short: urlopen worked, read() raises IncompleteRead"""
        def read(self, n=-1):
            raise http.client.IncompleteRead(b'{"features":[{"attributes":', 4096)

    cases = [("a body cut short (IncompleteRead)", lambda req: Cut(b"")),
             ("a garbage status line (BadStatusLine)", lambda req: (_ for _ in ()).throw(http.client.BadStatusLine("<html>"))),
             ("JSON that is null", lambda req: Reply(b"null")),
             ("JSON that is a list", lambda req: Reply(b"[]")),
             ("a feature that is not an object", lambda req: Reply(b'{"features":[null]}')),
             ("an error object", lambda req: Reply(b'{"error":{"code":500,"message":"boom"}}')),
             ("a refused connection", urllib.error.URLError("refused"))]
    for i, (label, gis) in enumerate(cases):
        W = healthy_world()
        W.gis = gis
        out = fresh("gis-%d" % i)
        code, text, _ = run_night(W, out, ARGS)
        rep = report(out, "2026-10-31") or {}
        check(code == 0 and rep.get("status") == "ok" and os.path.exists(os.path.join(out, "index.json")) and (rep.get("permits") or {}).get("newDrill") == 30,
              "the map service answering with %s does not cost the night, after every download is done (exit %s, status %s)" % (label, code, rep.get("status")))
    W = healthy_world()
    W.gis = urllib.error.URLError("refused")
    code, text, _ = run_night(W, fresh("gis-days"), ["--backfill", "7"])
    check(code == 0 and 1 <= W.gis_calls <= 3, "a refusing map service is asked 3 times in all, not 3 times for each of the 8 report days (%d requests)" % W.gis_calls)


def s_sameday(check):
    out = fresh("sameday")
    W1 = healthy_world()
    W1.fail_open[G["pending"]] = "share %s: no file table (HTTP 403)" % G["pending"]
    run_night(W1, out, ARGS)
    r1 = report(out, "2026-10-31") or {}
    W2 = healthy_world()  # the backup run an hour later: the RRC answers differently, and reads less
    W2.fail_open[G["permits"]] = "share %s: no file table (HTTP 403)" % G["permits"]
    W2.fail_open[G["completions"]] = "share %s: no file table (HTTP 403)" % G["completions"]
    code2, text2, _ = run_night(W2, out, ARGS, now=NOW + timedelta(minutes=65))
    r2 = report(out, "2026-10-31") or {}
    check(n_read(r1) == 5 and code2 == 0 and n_read(r2) == 5 and "permits" in r2 and "completions" in r2 and "pending" not in r2 and "keeping that one" in text2,
          "a backup run that read 4 files does not replace the report that read 5: still %d read, its completions kept (%s)" % (n_read(r2), "completions" in r2))
    code3, text3, _ = run_night(healthy_world(), out, ARGS, now=NOW + timedelta(minutes=80))  # 23:35 Central: still the same report day
    r3 = report(out, "2026-10-31") or {}
    check(code3 == 0 and n_read(r3) == 6 and r3.get("status") == "ok" and "pending" in r3, "a later capture that read all six replaces it (%d read, status %s)" % (n_read(r3), r3.get("status")))
    # nothing captured at all never replaces a report either (the rule that was already there)
    W4 = healthy_world()
    for ds in ("permits", "pending", "completions", "w1images", "dirsurveys", "complimages"):
        W4.fail_open[G[ds]] = "share %s: HTTP 403" % G[ds]
    code4, _, _ = run_night(W4, out, ["--backfill", "7"], now=NOW + timedelta(minutes=95))
    check(code4 == 1 and report(out, "2026-10-31") == r3, "a capture that read nothing leaves the report as it was (exit %s)" % code4)


def s_links(check):
    import subprocess
    permits = [p for p in month_perms(D(2026, 10, 1), D(2026, 10, 29)) if p["issued"] == "20261029"]
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        for p in permits[:12]:
            z.writestr("%07d_W1_letter.pdf" % p["n"], b"%PDF-1.4\n" + b"x" * 500)
            z.writestr("%07d_Plat_1.pdf" % p["n"], b"%PDF-1.4\n" + b"y" * 500)
    uploaded = set()

    def make_gh(works):
        def fake_run(cmd, capture_output=True, text=True, timeout=None):
            sub = " ".join(cmd[1:3])
            if sub == "release view" and "tagName" in cmd:
                return subprocess.CompletedProcess(cmd, 0 if uploaded else 1, "{}", "")
            if sub == "release create":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if sub == "release upload":
                if not works:
                    return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502: Bad Gateway")
                uploaded.update(os.path.basename(a) for a in cmd if a.endswith(".pdf"))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if sub == "release view":
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"assets": [{"name": n} for n in sorted(uploaded)]}), "")
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return fake_run

    saved = (d7_release.subprocess.run, d7_release.ready, d7_release.time.sleep)

    def night_with_docs(works, out, now):
        W = healthy_world()
        for r_ in W.shares[G["w1images"]]:
            if r_["modified"][:10] == "2026-10-31":
                r_["content"] = bio.getvalue()

        def patch():
            d7_release.subprocess.run = make_gh(works)
            d7_release.ready = lambda: None
        try:
            return run_night(W, out, ["--backfill", "0", "--packs", "--publish-docs", "--repo", "o/r"], now=now, patch=patch)
        finally:
            d7_release.subprocess.run, d7_release.ready, d7_release.time.sleep = saved

    out = fresh("links")
    code, text, _ = night_with_docs(True, out, NOW)
    r1 = report(out, "2026-10-31") or {}
    links = lambda r: sum(1 for x in (r.get("permits") or {}).get("rows", []) if len(x) > 10)  # noqa: E731
    code2, text2, _ = night_with_docs(False, out, NOW + timedelta(minutes=60))  # a by-hand repair of the same day while GitHub answers 502
    r2 = report(out, "2026-10-31") or {}
    check(code == 0 and r1.get("release") and links(r1) == 12 and code2 == 0 and r2.get("release") and links(r2) == 12 and "keeping that one" in text2,
          "a repair run whose document upload failed does not replace the report that has the links (%d links, release block %s)" % (links(r2), bool(r2.get("release"))))


def s_rebuilt(check):
    out = fresh("rebuilt")
    W = healthy_world()
    W.fail_open[G["pending"]] = "share %s: no file table (HTTP 403)" % G["pending"]
    run_night(W, out, ["--backfill", "3", "--skip-if-captured"], now=NOW)  # a night with the pending share down: three rebuilt days and the live one, all partial
    first = {d: report(out, d) or {} for d in ("2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31")}
    check(all(r.get("status") == "partial" and "pending" not in r for r in first.values()) and first["2026-10-30"].get("kind") == "reconstructed",
          "a night with the pending share down writes the rebuilt days partial, without their pending section")
    run_night(healthy_world(), out, ["--backfill", "3", "--skip-if-captured"], now=NOW + timedelta(minutes=65))  # the 04:20 backup, the RRC answers again
    after = {d: report(out, d) or {} for d in first}
    check(all(r.get("status") == "ok" and "pending" in r for r in after.values()), "the next run builds the rebuilt days again, and the live day, with every file: %s" % {d[5:]: r.get("status") for d, r in after.items()})
    live31 = json.dumps(after["2026-10-31"], sort_keys=True)
    run_night(healthy_world(), out, ["--backfill", "7"], now=NOW + timedelta(days=1))
    check(json.dumps(report(out, "2026-10-31"), sort_keys=True) == live31, "a live report is not rebuilt by a later night, whatever its status")


def s_damaged(check):
    base = fresh("damaged-base")
    run_night(healthy_world(), base, ["--backfill", "7"])
    nxt = NOW + timedelta(days=1)

    def case(label, damage, removed=None):
        out = fresh("damaged-" + str(abs(hash(label)) % 100000))
        shutil.rmtree(out)
        shutil.copytree(base, out)
        damage(out)
        code, text, exc = run_night(healthy_world(), out, ["--backfill", "7", "--skip-if-captured"], now=nxt)
        idx = index(out) or {}
        listed = [r["d"] for r in idx.get("days", [])]
        check(code == 0 and "2026-11-01" in listed and listed == sorted(f[:-5] for f in os.listdir(out) if f.endswith(".json") and f[0] == "2" and len(f) == 15),
              "%s: the night goes through (exit %s) and index.json lists exactly the day files, Nov 1 among them" % (label, str(code)[:60]))

    case("an old day file that is truncated JSON", lambda out: open(os.path.join(out, "2026-10-26.json"), "w").write('{"v":1,"date":"2026-10-26","kind":"live","da'))
    case("an old day file that is empty", lambda out: open(os.path.join(out, "2026-10-26.json"), "w").close())
    case("an old day file that is JSON but not an object", lambda out: open(os.path.join(out, "2026-10-26.json"), "w").write("[]"))

    def no_datasets(out):
        p = os.path.join(out, "2026-10-31.json")
        r = json.load(open(p))
        del r["datasets"]
        json.dump(r, open(p, "w"))
    case("the previous live report without its dataset list", no_datasets)
    case("permits-series.json of another shape", lambda out: open(os.path.join(out, "permits-series.json"), "w").write("{}"))
    case("permits-series.json with arrays of different lengths", lambda out: open(os.path.join(out, "permits-series.json"), "w").write('{"days":["2026-10-01"],"total":[],"newDrill":[],"horizontal":[]}'))
    d = fresh("states")  # the guard in update_states on its own (the night removes a damaged previous report before it gets there)
    json.dump({"date": "2026-10-30", "kind": "live"}, open(os.path.join(d, "2026-10-30.json"), "w"))
    live = {"date": "2026-10-31", "datasets": [{"id": "permits", "error": None, "file": {"name": "x"}}]}
    try:
        d7.update_states(live, d)
        ok_ = live["datasets"][0].get("state") == "first"
    except Exception as e:  # noqa: BLE001
        ok_ = False
    check(ok_, "update_states: a previous report without its dataset list is no reference ('first'), not a crash")
    out = fresh("damaged-gap")
    shutil.rmtree(out)
    shutil.copytree(base, out)
    open(os.path.join(out, "2026-10-29.json"), "w").write("{")
    code, text, _ = run_night(healthy_world(), out, ["--backfill", "7", "--skip-if-captured"], now=nxt)
    r29 = report(out, "2026-10-29") or {}
    check(code == 0 and r29.get("kind") == "reconstructed" and n_read(r29) == 6 and "removed" in text, "a damaged day inside the backfill window is removed and built again (%s)" % r29.get("kind"))
    check(not [f for f in os.listdir(out) if f.endswith(".tmp")], "no half-written file is left behind")


def s_errors(check):
    page = ("<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1> You don't have permission to access "
            "\"http&#58;&#47;&#47;mft.rrc.texas.gov&#47;link&#47;0ad92a65\" on this server.<P>Reference&#32;&#35;18</BODY></HTML>")
    W = healthy_world()
    W.fail_open[G["pending"]] = "share %s: table request failed: %s" % (G["pending"], page)
    W.fail_dl[(G["permits"], "daf420.dat")] = OSError(28, "No space left on device: '/home/runner/work/texas-oil-gas-leads/texas-oil-gas-leads/dl/daily/permits-2026-10-31/daf420.dat'")
    out = fresh("errors")
    code, text, _ = run_night(W, out, ["--backfill", "0"])
    rep = report(out, "2026-10-31") or {}
    raw = open(os.path.join(out, "2026-10-31.json")).read() if rep else ""
    pend, perm = dataset(rep, "pending")["error"], dataset(rep, "permits")["error"]
    check(rep and "http" not in raw and "mft.rrc" not in raw and not re.search(r"<(?!address>|path>)", "".join(str(d["error"]) for d in rep["datasets"])) and "/home/runner" not in raw and "Access Denied" in pend and "No space left" in perm,
          "the text of a failure in a day file carries no web address, server markup or path on the runner: %r / %r" % (pend[:90], perm[:80]))
    check(len(pend) <= 200 and "\n" not in pend, "and is one short line")
    ce = d7.clean_error
    check(ce(RuntimeError("x" * 500), 160) == "x" * 160 and ce("a   b\n c") == "a b c" and ce("see http://a.b/c?d=1 now") == "see <address> now" and ce("open /tmp/x/y.dat failed") == "open <path> failed"
          and ce("application/json is fine") == "application/json is fine", "clean_error: one line, cut to length, no address, no path, a media type left alone")


def s_names(check):
    def night_with(label, edit, expect_ok=True):
        W = healthy_world()
        edit(W)
        out = fresh("names-" + str(abs(hash(label)) % 100000))
        code, text, _ = run_night(W, out, ARGS)
        rep = report(out, "2026-10-31") or {}
        return code, rep, text

    z = completions_zip()
    stray = [("completions: a stray 13-45-2026.zip", lambda W: W.shares[G["completions"]].append(row("13-45-2026.zip", "2026-10-31T02:16:00", len(z), z))),
             ("completions: a day-first 31-10-2026.zip", lambda W: W.shares[G["completions"]].append(row("31-10-2026.zip", "2026-10-31T02:16:00", len(z), z))),
             ("w1images: subscriptions_2026-13-45.zip", lambda W: W.shares[G["w1images"]].append(row("subscriptions_2026-13-45.zip", "2026-10-31T10:18:07", 1000, b"PK"))),
             ("dirsurveys: a stray 00-00-0000.zip", lambda W: W.shares[G["dirsurveys"]].append(row("00-00-0000.zip", "2026-10-31T07:55:00", 1000, b"PK"))),
             ("pending: a set named ..._20261345120000", lambda W: W.shares[G["pending"]].append(row("dp_drilling_permit_pending_20261345120000.txt", "2026-10-31T10:00:00", 10, b""))),
             ("pending: a set with the hour 99", lambda W: W.shares[G["pending"]].append(row("dp_wellbore_pending_20261030990000.txt", "2026-10-31T10:00:00", 10, b"")))]
    for label, edit in stray:
        code, rep, _ = night_with(label, edit)
        check(code == 0 and rep.get("status") == "ok" and n_read(rep) == 6 and (rep.get("completions") or {}).get("approved") == 4 and "pending" in rep,
              "%s: skipped, and the dataset is read as on any other night (exit %s, status %s, %d read)" % (label, code, rep.get("status"), n_read(rep)))

    def bad_submit(W):  # one application whose submit date is a day that does not exist
        for r_ in W.shares[G["pending"]]:
            if r_["name"].startswith("dp_drilling_permit_pending_20261030"):
                stamp = r_["name"][-18:-4]
                r_["content"] = pending_pair(stamp, submit="31-NOV-26 10.44.57.000000 AM")[0]
    code, rep, _ = night_with("a bad submit date", bad_submit)
    check(code == 0 and rep.get("status") == "ok" and "pending" in rep, "a pending row whose submit date is not a day is read without it (exit %s, status %s)" % (code, rep.get("status")))

    def future_zip(W):  # a zip named for a day that has not come, listed on Oct 31 at the same time as the real one
        W.shares[G["completions"]].append(row("11-05-2026.zip", "2026-10-31T02:17:00", len(z), completions_zip(n_approved=9)))
    code, rep, _ = night_with("a future-named zip", future_zip)
    comp = rep.get("completions") or {}
    check(code == 0 and comp.get("approved") == 4 and comp.get("day") == "2026-10-30" and dataset(rep, "completions").get("dataDay") == "2026-10-30",
          "a zip named for a day after the one it landed on does not win: the report shows the real zip's day %s with %s approved" % (comp.get("day"), comp.get("approved")))
    check(d7.landed_on({D(2026, 11, 5): row("x", "2026-10-31T02:17:00"), D(2026, 10, 30): row("y", "2026-10-31T02:16:00")}, D(2026, 10, 31)) == D(2026, 10, 30)
          and d7.landed_on({D(2026, 10, 31): row("x", "2026-10-31T02:17:00")}, D(2026, 10, 31)) == D(2026, 10, 31), "landed_on: names after the day are skipped, the day's own is not")
    check(d7.oracle_date("31-NOV-26 10.44.57.1 AM") is None and d7.oracle_date("30-OCT-26 10.44.57.128000 AM") == datetime(2026, 10, 30, 10, 44, 57) and d7.named_date("2026", "13", "45") is None
          and d7.named_date("2026", "10", "30") == D(2026, 10, 30), "oracle_date and named_date: a day that does not exist is None, a real one is read")


def s_unusable(check):
    def case(label, edit, dataset_id, words):
        W = healthy_world()
        edit(W)
        out = fresh("unusable-" + str(abs(hash(label)) % 100000))
        code, text, _ = run_night(W, out, ARGS)
        rep = report(out, "2026-10-31") or {}
        err = (dataset(rep, dataset_id)["error"] or "") if rep else ""
        check(code == 0 and rep.get("status") == "partial" and words in err and n_read(rep) == 5 and d7.captured_for_the_night(out, D(2026, 10, 31)) is None,
              "%s is a failed dataset (partial, the other five read, the backup run goes ahead): %r" % (label, err[:90]))

    def set_content(guid, match, content):
        def edit(W):
            for r_ in W.shares[G[guid]]:
                if match(r_["name"]):
                    r_["content"] = content(r_) if callable(content) else content
        return edit

    daf = lambda n: n == "daf420.dat"  # noqa: E731
    case("a Daily Permit File that is empty", set_content("permits", daf, b""), "permits", "no permit records")
    case("a Daily Permit File that is an HTML page", set_content("permits", daf, b"<html><body>Service unavailable</body></html>"), "permits", "no permit records")
    pend = lambda n: n.startswith("dp_") and n.endswith(".txt") and "pending" in n and "filler" not in n  # noqa: E731
    case("pending files that are empty", set_content("pending", pend, b""), "pending", "column")
    case("pending files that are an HTML page", set_content("pending", pend, b"<html>503</html>"), "pending", "column")

    def renamed(r_):
        return r_["content"].replace(b"UNIVERSAL_DOC_NO", b"DOC_NO") if r_["content"] else r_["content"]
    case("pending files with UNIVERSAL_DOC_NO renamed", set_content("pending", pend, renamed), "pending", "UNIVERSAL_DOC_NO")

    def junk_zip():
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as z:
            z.writestr("readme/notes.txt", b"the layout changed")
            z.writestr("08/other.dat", b"x")
        return bio.getvalue()
    case("a completions zip whose members are not packets", set_content("completions", lambda n: n.endswith(".zip"), junk_zip()), "completions", "not one completion packet")

    # what must NOT be refused: a byte-order mark is read through, and a zip with nothing in it is a day with no completions
    W = healthy_world()
    set_content("pending", pend, lambda r_: b"\xef\xbb\xbf" + r_["content"] if r_["content"] else r_["content"])(W)
    out = fresh("unusable-bom")
    code, _, _ = run_night(W, out, ARGS)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and (rep.get("pending") or {}).get("total", 0) > 0, "pending files that start with a UTF-8 byte-order mark are read (exit %s, status %s, %s queued)" % (code, rep.get("status"), (rep.get("pending") or {}).get("total")))
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w"):
        pass
    W = healthy_world()
    set_content("completions", lambda n: n.endswith(".zip"), empty.getvalue())(W)
    out = fresh("unusable-emptyzip")
    code, _, _ = run_night(W, out, ARGS)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and (rep.get("completions") or {}).get("approved") == 0, "a completions zip with nothing in it is a day with no completions, not a failure (%s)" % (rep.get("completions") or {}).get("approved"))
    # a Daily Permit File with a few records and nothing else is still a file (the first days of a month are mostly stragglers)
    W = healthy_world(daf=daf_bytes([{"n": 1000, "county": "317", "issued": "20261029", "received": "20261026"}]))
    out = fresh("unusable-fewpermits")
    code, _, _ = run_night(W, out, ARGS)
    check(code == 0 and (report(out, "2026-10-31") or {}).get("status") == "ok", "a Daily Permit File with a single record is read as it is")


def s_listing(check):
    """The real share client against a fake connection: a listing that is not a listing is an error."""
    def page(rows, count=None):
        trs = "".join('<tr data-ri="%d"><td class="NameColumn"><a id="fileTable:%d:j_id_2f" href="#">%s</a></td><td class="ModifiedOnColumn">%s</td><td class="SizeColumn">1 KB</td></tr>'
                      % (i, i, n, m) for i, (n, m) in enumerate(rows))
        return ('<form id="fileList" action="/link/x;jsessionid=AB"><input type="hidden" name="javax.faces.ViewState" value="vs1"/><table>%s</table>rowCount:%d</form>'
                % (trs, len(rows) if count is None else count)).encode()

    def ajax(rows):
        body = "".join('<tr data-ri="%d"><td class="NameColumn"><a id="fileTable:%d:j_id_2f" href="#">%s</a></td><td class="ModifiedOnColumn">%s</td><td class="SizeColumn">1 KB</td></tr>'
                       % (i, i, n, m) for i, (n, m) in enumerate(rows))
        return ('<?xml version="1.0"?><partial-response><changes><update id="fileList"><![CDATA[%s]]></update></changes></partial-response>' % body).encode()

    class Conn:
        host = "mft.rrc.texas.gov"

        def __init__(self, rows, count=None):
            self.rows, self.count = rows, count
            self.retries, self.attempts, self.timeout, self.deadline = 0, 18, 120, None

        def request(self, method, path, data=None, headers=None, sink=None):
            return (200, {}, page(self.rows, self.count) if method == "GET" else ajax(self.rows))

    guid = G["permits"]

    def listed(rows, count=None):
        sh = rrc_share.Share(guid, Conn(rows, count))
        sh.open()
        return sh.newest(10)

    good = [("a.zip", "10/30/26 9:45:28 AM"), ("b.zip", "10/29/26 9:45:28 AM")]
    check([r["name"] for r in listed(good)] == ["a.zip", "b.zip"], "the real share client reads a proper listing, newest first")
    try:
        listed([], 0)
        check(False, "a share that lists no files should be an error")
    except rrc_share.ShareError as e:
        check("lists no files" in str(e), "a table with no files is an error, not a share that has nothing: %s" % e)
    try:
        listed([("a.zip", "2026-10-30 09:45"), ("b.zip", "2026-10-29 09:45")])
        check(False, "a listing whose times cannot be read should be an error")
    except rrc_share.ShareError as e:
        check("time this script can read" in str(e), "a listing in which no time can be read is an error: %s" % e)
    try:
        listed(list(reversed(good)))
        check(False, "a listing that came back oldest first should be an error")
    except rrc_share.ShareError as e:
        check("newest first" in str(e), "a listing that came back oldest first is an error, not the newest files: %s" % e)
    check(len(listed([("a.zip", "10/30/26 9:45:28 AM"), ("b.zip", "n/a"), ("c.zip", "10/29/26 9:45:28 AM")])) == 3, "one row with no readable time among readable ones is kept (it is skipped where days are picked)")


def s_repair(check):
    BIG = dict(since=D(2026, 10, 1), pend_since=D(2026, 10, 1))
    base = fresh("repair-base")
    code, text, _ = run_night(healthy_world(**BIG), base, ["--backfill", "30"])
    sections = lambda r: tuple(k for k in ("permits", "pending", "completions", "w1images", "dirsurveys", "complimages") if k in r or (r.get("images") or {}).get(k))  # noqa: E731
    check(code == 0 and len([f for f in os.listdir(base) if f[:2] == "20" and len(f) == 15]) >= 31, "the repair test starts from an archive of a month of days")
    for back in (4, 5, 10):
        day = D(2026, 10, 31) - timedelta(days=back)
        out = fresh("repair-%d" % back)
        shutil.rmtree(out)
        shutil.copytree(base, out)
        before = sections(report(out, day.isoformat()) or {})
        code, text, _ = run_night(healthy_world(**BIG), out, ["--date", day.isoformat(), "--backfill", "7"])
        after = report(out, day.isoformat()) or {}
        check(code == 0 and len(before) >= 5 and sections(after) == before and after.get("kind") == "live" and after.get("status") == "ok",
              "repairing a day %d days back keeps everything it had (%d sections before, %d after)" % (back, len(before), len(sections(after))))


def s_budget(check):
    import time as _time
    saved = (rrc_share.DEADLINE, d7_release.DEADLINE)
    try:
        run_night(healthy_world(), fresh("budget"), ["--backfill", "0", "--time-limit", "7"])
        now = _time.time()
        check(rrc_share.DEADLINE is not None and abs(rrc_share.DEADLINE - (now + 7 * 60)) < 120 and d7_release.DEADLINE is not None and abs(d7_release.DEADLINE - (now + 10 * 60)) < 120,
              "a capture sets a time limit for the share requests (7 minutes here) and gives the uploads 3 minutes more")
        calls = []
        sess = rrc_share.Session(attempts=3)
        sess._once = lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(OSError("never answers"))
        rrc_share.DEADLINE = _time.time() - 1
        try:
            sess.request("GET", "/link/x")
            check(False, "a request after the deadline should fail")
        except rrc_share.ShareError as e:
            check(not calls and "ran out of time" in str(e), "after the time limit no share request is started: %s" % e)
        rrc_share.DEADLINE = _time.time() + 600
        saved_sleep = rrc_share.time.sleep
        rrc_share.time.sleep = lambda s_: None
        try:
            sess.request("GET", "/link/x")
        except rrc_share.ShareError as e:
            check(len(calls) == 3 and "failed after 3 tries" in str(e), "before the time limit a request still has all its tries (%d)" % len(calls))
        finally:
            rrc_share.time.sleep = saved_sleep
        # a pack download is cut off at the capture's time limit when that comes before its own 8 minutes
        seen = []
        fake = types.SimpleNamespace(s=types.SimpleNamespace(attempts=0, timeout=0, deadline=None))

        def fake_download(name, dest):
            seen.append(fake.s.deadline)
            raise rrc_share.TooSlow("went past its time budget")
        fake.download = fake_download
        rrc_share.DEADLINE = _time.time() + 120
        d7.pack_preview(fake, {"dl": fresh("budget-pack"), "R": D(2026, 10, 31), "img_out": fresh("budget-img")}, "w1images", "x.zip")
        check(len(seen) == 1 and seen[0] is not None and seen[0] <= rrc_share.DEADLINE + 0.001 and fake.s.deadline is None,
              "a pack download is cut off at the capture's time limit when that is sooner than its own 8 minutes (%.0f s left of 120)" % (seen[0] - _time.time() if seen else -1))
        d7_release.DEADLINE = _time.time() - 1
        ran = []
        saved_run = d7_release.subprocess.run
        d7_release.subprocess.run = lambda *a, **k: ran.append(1)
        try:
            d7_release._gh(["release", "view", "x"])
            check(False, "a gh call after the deadline should fail")
        except d7_release.ReleaseError as e:
            check(not ran and "ran out of time" in str(e), "after the time limit no upload is started: %s" % e)
        finally:
            d7_release.subprocess.run = saved_run
    finally:
        rrc_share.DEADLINE, d7_release.DEADLINE = saved


SCENARIOS = {"healthy": s_healthy, "locator": s_locator, "sameday": s_sameday, "links": s_links, "rebuilt": s_rebuilt, "damaged": s_damaged, "errors": s_errors,
             "names": s_names, "unusable": s_unusable, "listing": s_listing, "repair": s_repair, "budget": s_budget}


def run_scenarios(names=None, quiet=False):
    fails = []
    for name, fn in SCENARIOS.items():
        if names is None or name in names:
            try:
                fn(mk_check(fails, quiet))
            except Exception as e:  # noqa: BLE001 - a scenario that cannot run is a failure, and a mutant may break one outright
                fails.append("%s: raised %s: %s" % (name, type(e).__name__, e))
                if not quiet:
                    print("FAIL %s raised %s: %s" % (name, type(e).__name__, e))
    return fails


# ================================================================================================ mutants
def mutants():
    """Put the old behavior back, one fix at a time, by changing the producer's own text; the scenario that guards it must notice."""
    fails = []

    def load(path, name, edits):
        src = open(path).read()
        for old, new in edits:
            if old not in src:
                return None
            src = src.replace(old, new, 1)
        mod = types.ModuleType(name)
        mod.__file__ = path
        exec(compile(src, path, "exec"), mod.__dict__)
        return mod

    FILES = {"daily": ("d7_daily.py", "d7mut"), "locate": ("d7_locate.py", "d7_locate"), "share": ("rrc_share.py", "rrc_share"), "release": ("d7_release.py", "d7_release")}

    def mutant(name, scenario, **edits):
        """edits: daily=, locate=, share= or release= is a list of (old text, new text) for that file; the scenario runs against the changed code."""
        global d7, d7_locate, d7_release, rrc_share
        saved = (d7, d7_locate, d7_release, rrc_share, {k: sys.modules.get(k) for k in ("d7_locate", "d7_release", "rrc_share")}, (d7.d7_locate, d7.d7_release, d7.rrc_share))
        mods = {}
        for key, patch in edits.items():
            mods[key] = load(os.path.join(PIPE, FILES[key][0]), FILES[key][1], patch)
            if mods[key] is None:
                print("FAIL mutant cannot be made, the producer's text changed: %s" % name)
                fails.append("mutant not made: " + name)
                return
        try:
            loc, rel, shr, mod = mods.get("locate", d7_locate), mods.get("release", d7_release), mods.get("share", rrc_share), mods.get("daily", d7)
            sys.modules["d7_locate"], sys.modules["d7_release"], sys.modules["rrc_share"] = loc, rel, shr
            mod.d7_locate, mod.d7_release, mod.rrc_share = loc, rel, shr
            d7, d7_locate, d7_release, rrc_share = mod, loc, rel, shr
            try:
                got = run_scenarios({scenario}, quiet=True)
            except Exception as e:  # noqa: BLE001
                got = ["crashed: %s" % e]
        finally:
            d7, d7_locate, d7_release, rrc_share = saved[:4]
            for k, v in saved[4].items():
                if v is not None:
                    sys.modules[k] = v
            d7.d7_locate, d7.d7_release, d7.rrc_share = saved[5]
        print(("ok   " if got else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)

    mutant("the map service's errors are only OSError and ValueError", "locator", locate=[
        ("        except Exception as e:  # noqa: BLE001 - IncompleteRead and BadStatusLine are HTTPExceptions: any failure is one failed attempt", "        except (OSError, ValueError, urllib.error.URLError) as e:"),
        ("            except Exception as e:  # noqa: BLE001 - nothing the service says may cost the night", "            except RuntimeError as e:"),
        ("            if not isinstance(out, dict):\n                raise ValueError(\"the service answered with %s, not a result\" % type(out).__name__)\n", "")])
    mutant("a failed lookup is retried for every report day", "locator", locate=[("            if self.failed:\n                break\n", "")])
    mutant("a rebuilt day written partial is never built again", "rebuilt", daily=[('if old["kind"] == "reconstructed" and old.get("status") != "ok":', "if False:")])
    mutant("a capture that read less replaces the report", "sameday", daily=[("if usable_day(old) and worth(reports[d]) < worth(old):", "if False:")])
    mutant("a capture that lost the document links replaces the report", "links", daily=[("return (sum(1 for d in rep.get(\"datasets\", []) if not d.get(\"error\")), 1 if rep.get(\"release\") else 0)", "return (sum(1 for d in rep.get(\"datasets\", []) if not d.get(\"error\")), 0)")])
    mutant("a damaged day file is trusted", "damaged", daily=[("        if not usable_day(old):\n            log(", "        if False:\n            log(")])
    mutant("a series file of another shape is trusted", "damaged", daily=[("    if not (isinstance(old, dict) and all(isinstance(old.get(k), list)", "    if False and not (isinstance(old, dict) and all(isinstance(old.get(k), list)")])
    mutant("the previous report is trusted when it has no dataset list", "damaged", daily=[("if usable_day(prev) and prev.get(\"kind\") == \"live\" else None", "if prev and prev.get(\"kind\") == \"live\" else None")])
    mutant("an error is published as it came", "errors", daily=[("entry.update({\"error\": clean_error(job, 200) if job else \"not captured\", \"file\": None})", "entry.update({\"error\": str(job)[:200] if job else \"not captured\", \"file\": None})")])
    mutant("a stray completions zip name fails the dataset", "names", daily=[("        d = named_date(m.group(3), m.group(1), m.group(2)) if m else None\n        if d:\n            zips[d] = r",
                                                                                "        d = date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None\n        if d:\n            zips[d] = r")])
    mutant("a stray image pack name fails the dataset", "names", daily=[("d, dist = named_date(m.group(1), m.group(2), m.group(3)), m.group(4)", "d, dist = date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)")])
    mutant("a stray pending name fails the dataset", "names", daily=[("        try:\n            stamp = datetime.strptime(m.group(2), \"%Y%m%d%H%M%S\")\n        except ValueError:\n            continue  # a name with a day or a time that does not exist: skipped, not a reason to fail the dataset\n",
                                                                     "        stamp = datetime.strptime(m.group(2), \"%Y%m%d%H%M%S\")\n")])
    mutant("a submit date that does not exist fails the dataset", "names", daily=[("    try:\n        return datetime(2000 + int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), h, int(m.group(5)), int(m.group(6)))\n    except ValueError:\n        return None",
                                                                                "    return datetime(2000 + int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), h, int(m.group(5)), int(m.group(6)))")])
    mutant("a zip named for a later day wins", "names", daily=[(" and d <= day), default=None)", "), default=None)")])
    mutant("an empty Daily Permit File is read as no permits", "unusable", daily=[("    if not out:  # an empty file", "    if False:  # an empty file")])
    mutant("a pending export without its columns is read as an empty queue", "unusable", daily=[("    if missing:\n        raise ValueError(\"%s has no %s column", "    if False:\n        raise ValueError(\"%s has no %s column")])
    mutant("a zip of files that are not packets is read as no completions", "unusable", daily=[("    if members and not packets:", "    if False:")])
    mutant("a share table of nothing is a share with nothing", "listing", share=[("        if self.total == 0 and not rows:", "        if False:")])
    mutant("a listing with no readable time is accepted", "listing", share=[("        if rows and not times:", "        if False:")])
    mutant("a listing that is not newest first is accepted", "listing", share=[("        if len(times) >= 2 and times[0] < times[-1]:", "        if False:")])
    mutant("a repair reaches back only as far as the number of days in the run", "repair", daily=[
        ("24 * (ctx.get(\"span\", len(ctx[\"dates\"])) + 2)", "24 * (len(ctx[\"dates\"]) + 2)"),
        ("sh.newest(ctx.get(\"span\", len(ctx[\"dates\"])) + 8)", "sh.newest(len(ctx[\"dates\"]) + 8)"),
        ("* (ctx.get(\"span\", len(ctx[\"dates\"])) + 4)", "* (len(ctx[\"dates\"]) + 4)")])
    mutant("the capture sets no time limit", "budget", daily=[("    rrc_share.DEADLINE = started + a.time_limit * 60\n", "    pass\n")])
    mutant("a pack download may run past the capture's time limit", "budget", daily=[("        limit = min(limit, rrc_share.DEADLINE)  # never past", "        limit = limit  # never past")])
    mutant("a share request is started after the time limit", "budget", share=[("                if DEADLINE is not None and time.time() > DEADLINE:", "                if False:")])
    mutant("an upload is started after the time limit", "budget", release=[("        if left is not None and left < 20:", "        if False:")])
    return fails


if __name__ == "__main__":
    allf = []
    print("-- whole nights")
    allf += run_scenarios()
    print("\n-- mutants")
    allf += mutants()
    shutil.rmtree(TMP, ignore_errors=True)
    print()
    print("FAILED %d: %s" % (len(allf), allf[:5]) if allf else "all passed")
    sys.exit(1 if allf else 0)
