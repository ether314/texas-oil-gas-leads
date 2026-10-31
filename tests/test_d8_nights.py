"""Tests for whole nights of site/pipeline/d8_ok_daily.py: main() is run against scratch folders with the network faked (urlopen serves
synthetic workbooks and CSV files, or fails) and the clock fixed, and what it leaves behind is read back. The rules inside the producer are
in test_d8.py; this file is for what happens when the OCC's files are late, cut short, renamed, empty, or an error page, because those
nights decide whether the archive keeps telling the truth while nobody is watching (an independent review found each of them by trying it):

  - a permit whose API number gives no county did not crash the night; an inventory file that is an error page, empty, header-only or
    renamed is a failed dataset (partial report), a UTF-8 byte-order mark is read through, and an inventory under 90% of the last one is
    refused as cut short
  - a later capture of the same day that read fewer files does not replace a report that read more
  - a master file that could not be read makes the report partial (so the backup run tries again); a rebuilt day that was written partial
    is built again by a later night, a live one never is
  - no failure text carries a web address; the permit workbook's rows per formation are one permit; a completion workbook with a renamed
    figure column costs that figure, not the file

Mutants patch the producer back to the old behavior, one fix at a time, and require the checks to notice.

Run: python3 -I tests/test_d8_nights.py"""
import collections
import contextlib
import copy
import csv
import email.utils
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(os.path.dirname(HERE), "site", "pipeline")
sys.path.insert(0, PIPE)
spec = importlib.util.spec_from_file_location("d8n", os.path.join(PIPE, "d8_ok_daily.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
D = date
TMP = tempfile.mkdtemp()
ITD, COMP, TR, WELLS = (d["file"] for d in M.DATASETS)
ITD_BASE, COMP_BASE = M.BASES["itd"], M.BASES["completions"]
NOW = datetime(2026, 11, 1, 3, 15, tzinfo=timezone.utc)  # 22:15 on Oct 31 in Central: the nightly capture of Oct 31
EVENING = "2026-10-31T19:41:00"  # when the OCC made its daily files that evening (Central)


# ------------------------------------------------------------------------------------------------ synthetic workbooks
def serial(dt):
    return str((dt - datetime(1899, 12, 30)).total_seconds() / 86400)


def col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def xlsx(path, header, rows):
    """rows: lists of text, None or ('n', number text)."""
    def cell(i, j, v):
        ref = "%s%d" % (col(j + 1), i)
        if v is None:
            return ""
        if isinstance(v, tuple):
            return '<c r="%s"><v>%s</v></c>' % (ref, v[1])
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(str(v)))
    body = "".join('<row r="%d">%s</row>' % (i, "".join(cell(i, j, v) for j, v in enumerate(r))) for i, r in enumerate([header] + rows, 1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % body)


ITD_H = ["API_Number", "Operator_Number", "Entity_Name", "Well_Class", "Application_Type", "Permit_Status", "Total_Depth", "Depth", "Submit_Date", "Approval_Date"]
COMP_H = ["API_Number", "Operator_Number", "Operator_Name", "Well_Type", "Location_Type_Sub", "Drill_Type", "Amended", "Spud", "First_Prod", "Create_Date", "Test_Date",
          "Oil_BBL_Per_Day", "Gas_MCF_Per_Day", "Formation_Name", "Review_Status"]
TR_H = ["EventDate", "API Number", "Type", "FromOperatorNumber", "FromOperatorName", "ToOperatorNumber", "ToOperatorName"]


def itd_row(api, op, name, appr_utc, app="DR", depth="15000", status="WRA"):
    return [api, op, name, "O&G", app, status, ("n", depth), None, ("n", serial(appr_utc - timedelta(days=3))), ("n", serial(appr_utc))]


def comp_row(api, op, name, created_utc, oil="120"):
    return [api, op, name, "OIL", "HH", "HORIZONTAL", "No", ("n", serial(created_utc - timedelta(days=90))), ("n", serial(created_utc - timedelta(days=60))), ("n", serial(created_utc)),
            None, ("n", oil), ("n", "300"), "MISSISSIPPIAN", "ACCEPTED"]


def wells_csv(n, extra=""):
    """An inventory of n wells (every tenth plugged), as the OCC's export is: ISO-8859-1 text with a header."""
    kinds = ["AC"] * 9 + ["PA"]
    return "WELLSTATUS,WELLTYPE,API,OPERATOR\n" + "".join("%s,OIL,35%03d%05d0000,ACME OIL LLC\n" % (kinds[i % 10], 1 + 2 * (i % 77), i) for i in range(n)) + extra


def make_files(folder, itd=None, comp=None, tr=None, wells=None, comp_header=COMP_H):
    """The OCC's four daily files for one night, in folder. wells is text (or bytes) written as the file."""
    os.makedirs(folder, exist_ok=True)
    day = datetime(2026, 10, 30, 15)
    xlsx(os.path.join(folder, ITD), ITD_H, itd if itd is not None else [itd_row("3513700590", "100", "ACME OIL LLC", day), itd_row("3503900011", "100", "ACME OIL LLC", day)])
    xlsx(os.path.join(folder, COMP), comp_header, comp if comp is not None else [comp_row("3507300100", "100", "ACME OIL LLC", day)])
    xlsx(os.path.join(folder, TR), TR_H, tr if tr is not None else [])
    data = wells if wells is not None else wells_csv(20)
    with open(os.path.join(folder, WELLS), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("iso-8859-1"))


# ------------------------------------------------------------------------------------------------ one night, offline
class Reply:
    def __init__(self, path, modified):
        self.f = open(path, "rb")
        from zoneinfo import ZoneInfo
        utc = datetime.fromisoformat(modified).replace(tzinfo=ZoneInfo("America/Chicago")).astimezone(timezone.utc)
        self.headers = {"Last-Modified": email.utils.format_datetime(utc, usegmt=True), "Content-Length": str(os.path.getsize(path))}

    def read(self, n=-1):
        return self.f.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()


def night(out, src, argv=(), now=NOW, modified=EVENING, fail=(), masters=None):
    """Run the producer once as the workflow does, with the OCC's files taken from src (and the master files from masters, a folder), a file
    named in fail refused with an error that carries its address. Returns (exit code, log text)."""
    dl = tempfile.mkdtemp(dir=TMP)
    saved = (urllib.request.urlopen, M.central_now, M.time.sleep, sys.argv)

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        name = url.rsplit("/", 1)[-1]
        if name in fail or name == "oil-gas-data.html":  # the data page (the catalog) is always down here
            raise urllib.error.URLError("[Errno 111] Connection refused (%s)" % url)
        for folder in (src, masters):
            if folder and os.path.exists(os.path.join(folder, name)):
                return Reply(os.path.join(folder, name), modified)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    from zoneinfo import ZoneInfo
    urllib.request.urlopen = urlopen
    M.central_now = lambda: now.astimezone(ZoneInfo("America/Chicago"))
    M.time.sleep = lambda s: None
    sys.argv = ["d8_ok_daily.py", "--out", out, "--dl", dl] + list(argv)
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            try:
                M.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
                if isinstance(e.code, str):
                    buf.write("EXIT: %s\n" % e.code)
    except Exception as e:  # noqa: BLE001 - a crash is a result of its own here
        code = "CRASH %s: %s" % (type(e).__name__, e)
    finally:
        urllib.request.urlopen, M.central_now, M.time.sleep, sys.argv = saved
        shutil.rmtree(dl, ignore_errors=True)
    return code, buf.getvalue()


def fresh(name):
    p = os.path.join(TMP, name)
    shutil.rmtree(p, ignore_errors=True)
    return p


def report(out, day):
    try:
        with open(os.path.join(out, day + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def dataset(rep, ds):
    return [d for d in rep["datasets"] if d["id"] == ds][0]


def scenarios(quiet=False):
    """Every night below, checked. Returns the failure messages."""
    fails = []

    def check(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    # ------------------------------------------------------------------ a normal night, and what a permit with no county does to it
    day = datetime(2026, 10, 30, 15)
    src = fresh("src-normal")
    make_files(src, itd=[itd_row("3513700590", "100", "ACME OIL LLC", day), itd_row("3503900011", "100", "ACME OIL LLC", day),
                         itd_row("", "100", "ACME OIL LLC", day),                 # no API number: no county
                         itd_row("42137005900000", "100", "ACME OIL LLC", day),   # another state's number: no county
                         itd_row("3503900012", "200", "OTHER OIL LLC", day)])
    out = fresh("out-normal")
    code, text = night(out, src)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok", "a normal night: exit 0, every file read (%s; %s)" % (code, rep.get("status")))
    p = rep.get("permits") or {}
    check(p.get("total") == 5 and p.get("newDrill") == 5 and sum(c[2] for c in p.get("counties", [])) == 3 and all(c[0] for c in p.get("counties", [])),
          "permits whose API number gives no county are in the totals and in no county, and the night does not crash: %s" % p.get("counties"))
    check(not any(w in text for w in ("http", "oklahoma.gov")) and "catalog: SKIPPED" in text, "the log of a night with the data page down carries no web address")

    # ------------------------------------------------------------------ an inventory file that is not the inventory
    def with_wells(name, wells):
        s = fresh("src-" + name)
        make_files(s, wells=wells)
        o = fresh("out-" + name)
        c, t = night(o, s)
        return c, t, report(o, "2026-10-31") or {}

    cases = [("an error page", "<html><body>503 Service Unavailable</body></html>"), ("an empty file", ""), ("a header with no wells", "WELLSTATUS,WELLTYPE,API,OPERATOR\n"),
             ("renamed columns", "STATUS,TYPE,API_NO,OPERATOR\nAC,OIL,3513700590,X\n")]
    for label, wells in cases:
        c, t, rep = with_wells("wells-" + label.replace(" ", "-"), wells)
        w = dataset(rep, "wells") if rep else {}
        check(c == 0 and rep.get("status") == "partial" and w.get("error") and "wells" not in rep and "permits" in rep and "completions" in rep,
              "an inventory that is %s is a failed dataset (partial report, the other files kept, no inventory shown): %s / %s / %s" % (label, c, rep.get("status"), w.get("error")))
    c, t, rep = with_wells("wells-bom", b"\xef\xbb\xbf" + wells_csv(20).encode("iso-8859-1"))
    check(c == 0 and rep.get("status") == "ok" and (rep.get("wells") or {}).get("total") == 20,
          "an inventory that starts with a UTF-8 byte-order mark is read through, not taken for a renamed column: %s" % ((rep.get("wells") or {}).get("total"), ))

    # ------------------------------------------------------------------ a cut-short inventory against the last night's
    out = fresh("out-floor")
    s1 = fresh("src-floor1")
    make_files(s1, wells=wells_csv(20))
    night(out, s1, ["--date", "2026-10-30"], now=datetime(2026, 10, 31, 3, 15, tzinfo=timezone.utc), modified="2026-10-30T19:41:00")
    first = report(out, "2026-10-30") or {}
    check((first.get("wells") or {}).get("total") == 20, "the floor test starts from a night that counted 20 wells")
    s2 = fresh("src-floor2")
    make_files(s2, wells=wells_csv(17))
    code, text = night(out, s2)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "partial" and "wells" not in rep and "cut short" in (dataset(rep, "wells").get("error") or ""),
          "an inventory of 17 wells after one of 20 (under 90%%) is refused as cut short, not published as fewer wells: %s" % dataset(rep, "wells").get("error") if rep else "no report")
    s3 = fresh("src-floor3")
    make_files(s3, wells=wells_csv(18))
    code, text = night(out, s3)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and (rep.get("wells") or {}).get("total") == 18, "an inventory of 18 wells (exactly 90%%) is accepted: %s" % (rep.get("wells") or {}).get("total"))
    # the way out when the OCC really did shrink its inventory: a by-hand run with --wells-floor 0
    code, text = night(out, s2, ["--wells-floor", "0"])
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and (rep.get("wells") or {}).get("total") == 17, "--wells-floor 0 accepts the smaller inventory (a by-hand run after a real shrink): %s" % (rep.get("wells") or {}).get("total"))

    # ------------------------------------------------------------------ a later capture of the same day that read less
    out = fresh("out-sameday")
    src = fresh("src-sameday")
    make_files(src)
    night(out, src)
    before = report(out, "2026-10-31") or {}
    code, text = night(out, src, fail=(WELLS,))   # the backup run: the 121 MB inventory download fails
    after = report(out, "2026-10-31") or {}
    check(before.get("status") == "ok" and after.get("status") == "ok" and "wells" in after and "keeping it" in text and code == 0,
          "a later capture of the same day that read three files does not replace a report that read four (%s, %s, wells kept: %s)" % (before.get("status"), after.get("status"), "wells" in after))
    # the other way round, and an equal one, do replace
    out = fresh("out-sameday2")
    night(out, src, fail=(WELLS,))
    partial = report(out, "2026-10-31") or {}
    night(out, src)
    full = report(out, "2026-10-31") or {}
    check(partial.get("status") == "partial" and full.get("status") == "ok" and "wells" in full, "a later capture that read more replaces the one that read less (%s then %s)" % (partial.get("status"), full.get("status")))
    # the same failure on the same day, twice: the newer one is kept (it is the same, and newer)
    out = fresh("out-sameday3")
    night(out, src, fail=(WELLS,))
    night(out, src, fail=(WELLS,), now=NOW + timedelta(hours=1))
    check((report(out, "2026-10-31") or {}).get("status") == "partial", "two captures that read the same three files leave a partial report, no crash")

    # ------------------------------------------------------------------ a master file that cannot be read
    stale = "2026-10-29T19:41:00"  # the OCC's daily files are two days old: their last complete day is Oct 28, and the master holds Oct 29 and Oct 30
    src = fresh("src-stale")
    make_files(src)
    masters = fresh("masters")
    make_files(masters)
    for n in (TR, WELLS, ITD, COMP):
        os.remove(os.path.join(masters, n))
    xlsx(os.path.join(masters, ITD_BASE), ITD_H, [itd_row("3513700590", "100", "ACME OIL LLC", datetime(2026, 10, 30, 15)), itd_row("3503900011", "100", "ACME OIL LLC", datetime(2026, 10, 29, 15))])
    xlsx(os.path.join(masters, COMP_BASE), COMP_H, [comp_row("3507300100", "100", "ACME OIL LLC", datetime(2026, 10, 30, 15))])
    out = fresh("out-masters-ok")
    code, text = night(out, src, modified=stale, masters=masters)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "ok" and "history:" in text, "stale daily files and readable masters: the master's days are merged in and the report is complete (%s)" % rep.get("status"))
    out = fresh("out-masters-down")
    code, text = night(out, src, modified=stale, masters=None)
    rep = report(out, "2026-10-31") or {}
    check(code == 0 and rep.get("status") == "partial" and "history SKIPPED" in text and "http" not in text and "oklahoma.gov" not in text,
          "stale daily files and a master that cannot be read: all four files were read but the days after the daily files' last one are missing, so the report is partial (the backup run tries again), and the log has no address: %s" % rep.get("status"))
    check(not M.captured_for_the_night(out, D(2026, 10, 31)), "a partial report for that night is not 'captured for the night': the backup run goes ahead")

    # ------------------------------------------------------------------ a rebuilt day written without a file is built again; a live one is not
    out = fresh("out-rebuild")
    src = fresh("src-rebuild")
    make_files(src, itd=[itd_row("3513700590", "100", "ACME OIL LLC", datetime(2026, 10, d, 15)) for d in (28, 29, 30)],
               comp=[comp_row("3507300100", "100", "ACME OIL LLC", datetime(2026, 10, 29, 15))])
    night(out, src, ["--backfill", "2"], fail=(COMP,))
    r30 = report(out, "2026-10-30") or {}
    check(r30.get("kind") == "reconstructed" and r30.get("status") == "partial" and (report(out, "2026-10-31") or {}).get("kind") == "live",
          "a rebuilt day written while the completion file could not be read is partial (%s, %s)" % (r30.get("kind"), r30.get("status")))
    live31 = copy.deepcopy(report(out, "2026-10-31"))
    code, text = night(out, src, ["--backfill", "3"], now=datetime(2026, 11, 2, 3, 15, tzinfo=timezone.utc), modified="2026-11-01T19:41:00")
    r30 = report(out, "2026-10-30") or {}
    check(r30.get("kind") == "reconstructed" and r30.get("status") == "ok" and "completions" in r30,
          "the next night builds that day again, now with every file (%s, completions kept: %s)" % (r30.get("status"), "completions" in r30))
    check(report(out, "2026-10-31") == live31, "a live report is never rebuilt, whatever its status")

    # ------------------------------------------------------------------ failure text without an address
    src = fresh("src-fail")
    make_files(src)
    out = fresh("out-fail")
    code, text = night(out, src, fail=(ITD,))
    rep = report(out, "2026-10-31") or {}
    msg = dataset(rep, "itd").get("error") or ""
    check(code == 0 and rep.get("status") == "partial" and ITD in msg and "http" not in msg and "oklahoma.gov" not in msg and "\n" not in msg and "<address>" in msg,
          "the report's text for a file that could not be read names the file, not the address: %r" % msg)
    check(not any(w in json.dumps(rep) for w in ("http://", "https://", "oklahoma.gov")), "no web address anywhere in a report that had a failure")
    return fails


def workbook_checks(quiet=False):
    """The permit and completion readers, on small workbooks."""
    fails = []

    def check(cond, msg):
        if not quiet:
            print(("ok   " if cond else "FAIL ") + msg)
        if not cond:
            fails.append(msg)

    day = datetime(2026, 10, 30, 15)
    path = os.path.join(TMP, "itd-dups.xlsx")
    xlsx(path, ITD_H, [itd_row("3513700590", "100", "ACME OIL LLC", day)] * 3                       # one permit approved for three formations: three rows
         + [itd_row("3513700590", "100", "ACME OIL LLC", day, app="AM")]                           # the same well, another kind of filing
         + [itd_row("3513700590", "100", "ACME OIL LLC", day + timedelta(days=1))]                 # the same well approved again on another day
         + [itd_row("", "100", "ACME OIL LLC", day)] * 2)                                          # no API number: no identity to fold on
    got = M.read_itd(path)
    check(len(got) == 5 and sorted(r["app"] for r in got).count("DR") == 4 and [r["api"] for r in got].count("") == 2,
          "the permit file's rows per formation are one permit (a kind of filing and a day are each their own), blank API numbers are never folded: %d permits" % len(got))

    # a completion workbook without some figure columns still reads; without the day or the well it is not the file
    short = [h for h in COMP_H if h not in ("Oil_BBL_Per_Day", "Formation_Name", "Operator_Name")]
    path = os.path.join(TMP, "comp-short.xlsx")
    xlsx(path, short, [[v for h, v in zip(COMP_H, comp_row("3507300100", "100", "ACME", day)) if h in short]])
    try:
        ev = M.read_completions(path)
        check(len(ev) == 1 and ev[0]["oil"] == 0.0 and ev[0]["formation"] == "" and ev[0]["opname"] == "" and ev[0]["horizontal"] is True and ev[0]["gas"] == 300.0,
              "a completion workbook missing three figure columns still reads: its other figures are kept and the missing ones are blank: %s" % ev)
    except ValueError as e:
        check(False, "a completion workbook missing a figure column made the reader refuse the whole file (%s)" % e)
    for gone in ("Create_Date", "API_Number", "Review_Status"):
        path = os.path.join(TMP, "comp-no-%s.xlsx" % gone)
        keep = [h for h in COMP_H if h != gone]
        xlsx(path, keep, [[v for h, v in zip(COMP_H, comp_row("3507300100", "100", "ACME", day)) if h != gone]])
        try:
            M.read_completions(path)
            check(False, "a completion workbook without %s should be refused" % gone)
        except ValueError as e:
            check(gone in str(e), "a completion workbook without %s is refused, naming it: %s" % (gone, e))
    return fails


def mutants():
    """Put the old behavior back, one fix at a time; the checks must notice."""
    fails = []

    def expect_fail(name, patch):
        saved = {k: getattr(M, k) for k in patch}
        for k, v in patch.items():
            setattr(M, k, v)
        try:
            got = scenarios(quiet=True) + workbook_checks(quiet=True)
        except Exception as e:  # noqa: BLE001 - a mutant may break a night outright: that is noticed too
            got = ["crashed: %s" % e]
        finally:
            for k, v in saved.items():
                setattr(M, k, v)
        print(("ok   " if got else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)

    old_tally = lambda counter, lk: [[f, lk.county_name(f), n] for f, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])) if f]  # noqa: E731
    expect_fail("counties sorted with a missing code in them", {"tally_counties": old_tally})
    expect_fail("no floor on the inventory", {"previous_wells_total": lambda out_dir, before: None})
    expect_fail("an error carries its address", {"clean_error": lambda e, n=160: str(e)[:n]})

    def lax_wells(path):  # the old reader: any file is an inventory (an error page is one line, no wells: it never raised)
        with open(path, encoding="iso-8859-1", newline="") as f:
            total = sum(1 for _ in csv.DictReader(f))
        return {"total": total, "status": collections.Counter(), "type": collections.Counter(), "county": collections.Counter(), "operators": collections.Counter(),
                "active_type": collections.Counter()}

    expect_fail("any file is an inventory", {"read_wells": lax_wells})

    # the rules that live inside main() and the readers are put back by changing the producer's own text, one line at a time
    def source_mutant(name, old, new):
        path = os.path.join(PIPE, "d8_ok_daily.py")
        src = open(path).read()
        if old not in src:
            print("FAIL mutant cannot be made, the producer's text changed: %s" % name)
            fails.append("mutant not made: " + name)
            return
        mod = types.ModuleType("d8mut")
        mod.__file__ = path
        exec(compile(src.replace(old, new, 1), path, "exec"), mod.__dict__)
        saved = globals()["M"]
        globals()["M"] = mod
        try:
            got = scenarios(quiet=True) + workbook_checks(quiet=True)
        except Exception as e:  # noqa: BLE001
            got = ["crashed: %s" % e]
        finally:
            globals()["M"] = saved
        print(("ok   " if got else "FAIL ") + "mutant caught: %s (%d checks failed)" % (name, len(got)))
        if not got:
            fails.append("mutant survived: " + name)

    source_mutant("a rebuilt day written partial is never built again",
                  'if old.get("kind") == "reconstructed" and old.get("status") != "ok":', "if False:")
    source_mutant("a later capture that read less replaces the report",
                  'elif isinstance(earlier, dict) and earlier.get("kind") == "live" and sum(', 'elif False and sum(')
    source_mutant("a master that could not be read leaves the report ok",
                  '("ok" if got == len(DATASETS) and not history_failed else "partial")', '("ok" if got == len(DATASETS) else "partial")')
    source_mutant("a permit's rows per formation are each a permit", "if api and key in seen:", "if False:")
    source_mutant("a renamed figure column fails the whole completion file", "ok_xlsx.rows(path, want=COMP_COLS, optional=COMP_OPTIONAL)", "ok_xlsx.rows(path, want=COMP_COLS + COMP_OPTIONAL)")
    source_mutant("a byte-order mark stays on the first column's name",
                  r'reader.fieldnames = [(h or "").replace("\xef\xbb\xbf", "").replace("\ufeff", "").strip() for h in (reader.fieldnames or [])]', "pass")
    source_mutant("an inventory with no wells is accepted", 'if not total:\n        raise ValueError("the well file holds no wells")', "if False:\n        pass")
    return fails


if __name__ == "__main__":
    allf = []
    print("-- whole nights")
    allf += scenarios()
    print("\n-- workbooks")
    allf += workbook_checks()
    print("\n-- mutants")
    allf += mutants()
    shutil.rmtree(TMP, ignore_errors=True)
    print()
    print("FAILED %d: %s" % (len(allf), allf[:5]) if allf else "all passed")
    sys.exit(1 if allf else 0)
