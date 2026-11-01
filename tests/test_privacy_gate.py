"""Tests for the privacy gate the nightly runs before it commits anything (site/pipeline/privacy_check.py and the three producers' --check),
and for the published data itself.

An independent security review found that the Texas and Oklahoma checks looked at no text at all and New Mexico's only for an address, so
a night's output that named a sole proprietor, or held an e-mail address or a phone number, would have been committed and published (the
nightly's commit starts no CI, so the tests never saw it: that is how two reports once named two sole proprietors). Now each producer's
--check scans every day file for an e-mail address, a web address and a phone number (and, for Oklahoma and New Mexico, a run of ten digits:
they publish no API numbers) and holds the operator names it publishes to the state's rule; a failed check drops that state's night.

Checked here: the scan itself; each producer's check against a copy of the committed archive with a violation put into it (and the control
passing); a mutant that blinds the scan is noticed; the child process that parses a downloaded PDF no longer inherits the repository token;
and the committed data under site/public/data holds no e-mail, phone or API-like number and no city that is not a place name.

Run: python3 -I tests/test_privacy_gate.py"""
import copy
import glob
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
DATA = os.path.join(REPO, "site", "public", "data")
sys.path.insert(0, PIPE)
sys.path.insert(0, os.path.join(REPO, "site"))
import privacy_check as P  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PIPE, file))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


d7, d8, d9 = load("d7", "d7_daily.py"), load("d8", "d8_ok_daily.py"), load("d9", "d9_nm_daily.py")
FAILS = []
TMP = tempfile.mkdtemp(prefix="privacy-gate-")


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ the scan
check(P.scan("nothing here, 2026-10-31, 12,345 wells, 3513700590 is an API number") == [] and P.scan("a 14-digit file name 20261030110808", digits=False) == [],
      "scan: ordinary text, dates and numbers are clean (and a long number only counts where it is asked for)")
check(P.scan("write to joe@example.com") == ["an e-mail address"], "scan: an e-mail address")
check(P.scan("see http://x.y/z") == ["a web address"] and P.scan("see https://x.y/z") == ["a web address"], "scan: a web address")
check(all(P.scan("call " + n) == ["a phone number"] for n in ("918-555-0100", "(918) 555-0100", "918.555.0100", "918 555 0100")), "scan: a phone number in the usual shapes")
check(P.scan("API 35137005900000", digits=True) == ["a run of 10 or more digits (an API number?)"] and P.scan("API 3513700590", digits=True) != [] and P.scan("API 351370059", digits=True) == [],
      "scan: ten digits or more is an API number where asked for")
check(P.mask("Joe Smith 918-555-0100") == "AAA AAAAA 999-999-9999" and len(P.mask("x" * 200)) == 60, "mask: letters and digits become shapes, and it is short")
check(P.clean_error(RuntimeError("could not read x: <urlopen error [Errno 111] refused (https://a.b/c.xlsx)>")) == "could not read x: <urlopen error [Errno 111] refused (<address>)>"
      and "Access Denied" in P.clean_error("<HTML><BODY><H1>Access Denied</H1></BODY></HTML>") and "<" not in P.clean_error("<HTML><BODY><H1>Access Denied</H1></BODY></HTML>")
      and P.clean_error("open /home/runner/work/x/y.dat failed") == "open <path> failed" and d7.clean_error is P.clean_error and d8.clean_error is P.clean_error,
      "clean_error: the reason stays, a web address, an error page's markup and a path do not (one function for all three producers)")


# ------------------------------------------------------------------------------------------------ each producer's check, on a copy of its archive
def archive_copy(sub):
    out = os.path.join(TMP, sub + "-" + str(len(os.listdir(TMP))))
    shutil.copytree(os.path.join(DATA, sub), out)
    return out


def newest(out, section=None):
    """The newest day file, or the newest that holds a section: a day can have none of a dataset (Texas on the first day of a month, when the Daily Permit File has no record yet:
    2026-11-01 has no permits section), and an edit that puts a name into that section needs a day that has it."""
    days = sorted(f for f in os.listdir(out) if re.fullmatch(r"\d{4}-\d\d-\d\d\.json", f))
    if section:
        days = [f for f in days if section in json.load(open(os.path.join(out, f)))]
    return days[-1]


def edit(out, name, fn):
    path = os.path.join(out, name)
    doc = json.load(open(path))
    fn(doc)
    json.dump(doc, open(path, "w"), separators=(",", ":"), ensure_ascii=False)


def put_name(sec_key, name):
    """Put an operator name where the state's day reports have them (the first row of the section's operators list)."""
    def go(doc):
        sec, key = sec_key
        rows = doc[sec][key]
        rows[0][1] = name
    return go


STATES = [("Texas", "daily", d7.validate, True, ("permits", "operators"), "JOHN Q SMITH"),
          ("Oklahoma", "daily-ok", d8.validate, False, ("permits", "operators"), "FINNEY KYLER A DBA FINNEY OIL CO"),
          ("New Mexico", "daily-nm", d9.validate, False, ("permits", "operators"), "JOHN Q SMITH")]
for state, sub, validate, texas, where, bad_name in STATES:
    control = validate(archive_copy(sub))
    check(control == [], "%s: the committed archive passes its own check, privacy gate included: %s" % (state, control[:2]))
    for label, put in (("an e-mail address", lambda doc: doc.update(note="mail joe@example.com")), ("a phone number", lambda doc: doc.update(note="call 918-555-0100")),
                       ("a web address", lambda doc: doc.update(note="see https://example.com/x"))):
        out = archive_copy(sub)
        edit(out, newest(out), put)
        got = validate(out)
        check(any(label.split(" ", 1)[1] in g or label in g for g in got), "%s: a day file that holds %s fails the check: %s" % (state, label, got[:1]))
    out = archive_copy(sub)
    edit(out, newest(out, where[0]), put_name(where, bad_name))
    got = validate(out)
    check(any("operator" in g and "AAAA" in g for g in got) and bad_name.split()[0] not in " ".join(got),
          "%s: an operator name the state's rule refuses fails the check, and the log shows its shape, not the name: %s" % (state, got[:1]))
    if not texas:
        out = archive_copy(sub)
        edit(out, newest(out), lambda doc: doc.update(note="API 35137005900000"))
        check(any("10 or more digits" in g for g in validate(out)), "%s: a run of ten digits (an API number) fails the check" % state)
    else:
        out = archive_copy(sub)  # an old day may name an operator that a later rebuild of the list dropped: only the newest three days are held to the list
        first = sorted(f for f in os.listdir(out) if re.fullmatch(r"\d{4}-\d\d-\d\d\.json", f))[0]
        edit(out, first, put_name(where, "A FORMER OPERATOR LLC"))
        check(validate(out) == [], "Texas: an older day's operator name that is no longer on the list does not fail a night")

# a mutant: with the scan blinded nothing is reported
saved = P.scan
P.scan = lambda text, digits=False: []
try:
    out = archive_copy("daily-ok")
    edit(out, newest(out), lambda doc: doc.update(note="mail joe@example.com"))
    blind = d8.validate(out)
finally:
    P.scan = saved
check(blind == [], "mutant: with the scan blinded an e-mail address in a day file is not noticed (so the checks above are what notice it)")

# ------------------------------------------------------------------------------------------------ the token stays out of the PDF parser
sys.path.insert(0, PIPE)
import d7_packs  # noqa: E402

os.environ["GH_TOKEN"], os.environ["GITHUB_TOKEN"], os.environ["ACTIONS_RUNTIME_TOKEN"] = "x" * 39, "y" * 39, "z" * 39
seen = {}


def fake_run(cmd, **kw):
    seen.update(kw.get("env") or {"inherited": True})
    raise RuntimeError("stop here: the environment is what is being looked at")


saved_run = d7_packs.subprocess.run
d7_packs.subprocess.run = fake_run
try:
    try:
        d7_packs.render_first_page(types.SimpleNamespace(read=lambda info: b"%PDF-1.4"), types.SimpleNamespace(filename="x.pdf"), tempfile.mkdtemp(dir=TMP), None)
    except RuntimeError:
        pass
finally:
    d7_packs.subprocess.run = saved_run
check("inherited" not in seen and not {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN"} & set(seen) and "PATH" in seen,
      "the child that parses a downloaded PDF gets the environment without the repository token (and still has its PATH)")

# ------------------------------------------------------------------------------------------------ the published data
files = sorted(glob.glob(os.path.join(DATA, "**", "*.json"), recursive=True))
phone, mail, digits, urls = [], [], [], []
no_api = re.compile(r"(^|/)(daily-ok|daily-nm)/|-(ok|nm|fo)\.json$|(^|/)(operators|permits|county-permits|series-permits)-(ok|nm|fo)\.json$")
for f in files:
    rel = os.path.relpath(f, DATA)
    text = open(f, encoding="utf-8").read()
    hit = P.scan(text, digits=bool(no_api.search(rel)))
    for h in hit:
        if "web" in h:
            if rel.startswith("daily"):  # the monthly files carry source links ("src"); a Daily day file never does
                urls.append(rel)
        else:
            (phone if "phone" in h else mail if "e-mail" in h else digits).append(rel)
check(not phone and not mail and not digits, "no e-mail address, phone number or API-like number in any of the %d published data files (%s)" % (len(files), (phone + mail + digits)[:3]))
check(not urls, "no web address in any Daily day file or index (%s)" % urls[:3])

# the FracFocus wells' files (CLAUDE.md, Privacy, exception (d), the owner's decision of 2026-11-02): an API number is allowed in the two detail files and in no other file of the folder
nw_dir = os.path.join(DATA, "newwells")
loose = [n for n in sorted(os.listdir(nw_dir)) if n.endswith(".json") and not n.startswith("detail") and [h for h in P.scan(open(os.path.join(nw_dir, n), encoding="utf-8").read(), digits=True) if "web" not in h]]  # summary.json links its source
check(not loose, "no file of newwells/ but the two detail files holds an API-like number, an e-mail address or a phone number (%s)" % loose)
for n in ("detail.json", "detail-history.json"):
    d = json.load(open(os.path.join(nw_dir, n), encoding="utf-8"))
    cols = ("api", "end", "tvd", "wg", "nw", "dat")
    check(P.scan(json.dumps(d), digits=False) == [] and all(isinstance(x, int) and not isinstance(x, bool) for c in cols for x in d[c]) and set(d) == {"v", "t0", "n", "asOf" if n == "detail.json" else "until", *cols},
          "newwells/%s holds only whole numbers in its six columns: an API number, a day count, depth, water, other fluid and a datum code, and no name, lease or text" % n)

import build_data  # noqa: E402

odd = []
for name, col in (("companies.json", "city"), ("operators.json", "city"), ("operators-ok.json", "city"), ("operators-nm.json", "city"), ("operators-fo.json", "city")):
    doc = json.load(open(os.path.join(DATA, name)))
    ci = doc["cols"].index(col)
    odd += [(name, i) for i, r in enumerate(doc["rows"]) if r[ci] and not (build_data.CITY_OK.fullmatch(r[ci]))]
check(not odd, "every city in the company and operator files is a place name (not a street or a number): %s" % odd[:3])
check(build_data.place("999 MAIN STREET") == "" and build_data.place("  Fort   Worth ") == "Fort Worth" and build_data.place("ST. LOUIS") == "ST. LOUIS" and build_data.place(None) == "",
      "build_data.place: a place name is kept, a street or a number becomes blank")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
