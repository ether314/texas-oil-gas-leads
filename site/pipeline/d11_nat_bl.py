#!/usr/bin/env python3
"""D11: the Bureau of Land Management's onshore permits (Applications for Permit to Drill on federal land), for the National report of the Oil tracker.

The BLM publishes no per-well permit file that this machine can read (its Automated Fluid Minerals Support System is login-only). What it does publish, free, is a monthly
"Application for Permit to Drill Status Report" PDF (https://www.blm.gov/programs/energy-and-minerals/oil-and-gas/operations-and-production/permitting/applications-permits-drill):
a small table of APDs received, pending, processed and APPROVED by BLM state office (Alaska, California, Colorado, Eastern States, Montana, Nevada, New Mexico, Utah, Wyoming),
monthly from April 2021 (NOTES_D11.md has the research). This reads those PDFs with `pdftotext` (poppler-utils) and writes nat/BL.json: APDs approved by month, with the BLM state
offices as the places. What that count is, and is not:

  - APDs approved, new drills and re-entries together (the public count does not split them), so the `new` band here is "APDs approved", not new wells;
  - by BLM STATE OFFICE, not by state: the New Mexico office also covers Oklahoma, Kansas and Texas, the Montana office North Dakota and South Dakota, the Eastern States office
    everything east, and each office's count covers federal AND tribal lands (the report says so); the BLM line is therefore shown on its own and never added to the states', which permit
    most of the same wells;
  - the series starts after the last month the BLM did not link (October and November 2022 are missing), because a missing month is not a zero;
  - a month's report may be revised after release, so the last 14 months are read again every week and older months are kept from the committed file.

No operator is named (the table has none). The PDFs are untrusted data: parsed as text, never run; requests identify no person and are 4 seconds apart.

  python3 -I site/pipeline/d11_nat_bl.py [--check]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "BL"
PAGE = "https://www.blm.gov/programs/energy-and-minerals/oil-and-gas/operations-and-production/permitting/applications-permits-drill"
HOST = "https://www.blm.gov"
OFFICES = ("Alaska", "California", "Colorado", "Eastern States", "Montana", "Nevada", "New Mexico", "Utah", "Wyoming")
PAUSE = 4.0
REREAD = 14  # months read again each run
NUM = r"-?\d[\d,]*"
ROW = re.compile(r"^\s*(%s)\s+((?:%s\s+){4}%s)\s*$" % ("|".join(OFFICES), NUM, NUM), re.M)
# the second date can sit on the next line, with a heading of the next column between ("08/01/2024 to ... Permits ... 08/31/2024" in 2024)
SPAN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+to\b[^0-9]{0,200}?(\d{1,2})/(\d{1,2})/(\d{4})")
LINK = re.compile(r'href="([^"]*?(?:APD|Application)[^"]*?Status[^"]*?\.pdf)"', re.I)


def links(html):
    """The absolute addresses of the status-report PDFs listed on the APD page (newest first as listed), without repeats."""
    seen, out = set(), []
    for h in LINK.findall(html):
        url = h if h.startswith("http") else HOST + h
        if url.startswith(HOST + "/") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def to_int(text):
    return int(text.replace(",", ""))


def parse_report(text):
    """(month 'YYYY-MM', {office: approved}) from the text of one monthly report; None when it is not a one-month report (a fiscal-year summary, a two-month report) or no office row is found.
    Two layouts: through 2022 the columns run Received, Approved, Processed, Approved-and-available, Pending; from 2023, Received, Pending, Processed, Approved, Approved-and-available.
    Which one is told by where the headings say Pending and Processed."""
    m = SPAN.search(text)
    if not m:
        return None
    m1, d1, y1, m2, d2, y2 = (int(x) for x in m.groups())
    if (y1, m1) != (y2, m2) or d1 != 1:
        return None
    head = text[: text.find("State Office") + 400] if "State Office" in text else text[:1500]
    pend, proc = head.find("Pending"), head.find("Processed")
    idx = 3 if (pend != -1 and proc != -1 and pend < proc) else 1  # the column holding APDs approved (D)
    rows = {}
    for office, nums in ROW.findall(text):
        vals = [to_int(x) for x in nums.split()]
        if office not in rows:  # the first table is the month; a second one, further down, is the fiscal year to date
            rows[office] = vals[idx]
    if len(rows) < 6:
        return None
    return "%04d-%02d" % (y1, m1), rows


def pdf_to_text(data):
    """The text of a PDF through `pdftotext -layout` (poppler-utils), in a new folder, under a timeout. The PDF is data: it is never opened by anything else."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    with tempfile.TemporaryDirectory(prefix="bl-") as tmp:
        src = os.path.join(tmp, "report.pdf")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-layout", src, "-"], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")}, cwd=tmp)
        if r.returncode != 0:
            raise RuntimeError("pdftotext could not read a report")
        return r.stdout


def previous_totals(path=None):
    """{month: total approved} from the committed nat/BL.json, so months that will not change are not downloaded again; {} when there is none."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        return dict(zip(d["months"], d["bands"]["new"]))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def last_run(months):
    """The newest unbroken run of months (a gap, such as October and November 2022, ends the series that is shown: a missing month is not a zero)."""
    months = sorted(months)
    start = months[-1]
    for ym in reversed(months[:-1]):
        if C.add_months(ym, 1) != start:
            break
        start = ym
    return start


def build(get=C.polite_get, to_text=pdf_to_text, pause=PAUSE, old=None, today=None):
    today = today or date.today()
    html = get(PAGE, max_bytes=3_000_000).decode("utf-8", "replace")
    urls = links(html)
    if len(urls) < 20:
        raise RuntimeError("the APD page listed %d status reports (expected 40 or more): its layout may have changed" % len(urls))
    old = previous_totals() if old is None else old
    keep_from = C.add_months(C.month_of(today), -REREAD)
    got = {}  # month -> {office: approved}
    totals = {}  # month -> total approved
    first = True
    for url in urls:
        # a month already known and older than the window is not fetched again; its name tells the month only after reading, so the cheap test is the file name's month
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)[-_ ]+(\d{4})", url.replace("%20", " "))
        name_month = None
        if m:
            name_month = "%04d-%02d" % (int(m.group(2)), ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].index(m.group(1)) + 1)
            if name_month in old and name_month < keep_from:
                totals[name_month] = old[name_month]
                continue
        if not first:
            time.sleep(pause)
        first = False
        parsed = parse_report(to_text(get(url, max_bytes=5_000_000)))
        if parsed:
            got[parsed[0]] = parsed[1]
            totals[parsed[0]] = sum(parsed[1].values())
    if len(totals) < 24:
        raise RuntimeError("only %d monthly reports could be read (expected 40 or more)" % len(totals))
    start = last_run(totals)
    if start > "2023-01":
        raise RuntimeError("the unbroken run of months starts only in %s: reports are missing" % start)
    t = C.Tally(STATE, bands=("new",))
    newest = max(totals)
    for ym, n in sorted(totals.items()):
        if ym < start or n < 1:
            continue
        offices = got.get(ym)
        day = date(int(ym[:4]), int(ym[5:]), 15)
        if offices:
            for office, k in offices.items():
                if k > 0:
                    t.add(day, "new", county=office, n=k)
        else:
            t.add(day, "new", n=n)  # a month kept from the committed file: its total only
    # zero-approval months inside the run still need to exist on the axis: the tally fills them with zeros between the first month and `through`
    asof = C.month_end(newest)
    return t.document(agency="Bureau of Land Management", source_name="Application for Permit to Drill Status Report (monthly PDF, by BLM state office)", source_url=PAGE, basis="approval date (APDs approved)",
                      cadence="monthly", measure="permits", asof=asof, first=start, unit="APDs approved", place="state offices",
                      note="APDs (applications for permit to drill) approved by BLM state office, new drills and re-entries together, federal and tribal lands together; an office is not a state (New Mexico's covers Oklahoma, Kansas and Texas). "
                           "Shown on its own and never added to the states, which permit most of the same wells. The series starts in %s: the BLM's monthly reports run from April 2021, but the October and November 2022 reports were never linked on its page, so the unbroken run starts there." % start)


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
