#!/usr/bin/env python3
"""D11: Nebraska's drilling permits (Oil and Gas Conservation Commission, NOGCC), for the National report of the Oil tracker.

Nebraska is a small producer (17 permits in 2025, 28 in 2024, 52 in 2023). The Commission's Data and Publications page (http://nogcc.ne.gov/NOGCCPublications.aspx) links one PDF for every year under
"Drilling Permits" (http://nogcc.ne.gov/Publications/<year>WellPermits.pdf, 2005 to 2025 when written): "Nebraska Permitted Wells", a list under one date per day, each permit three lines (the
operator and the driller; the well's name, its footage and quarter-section location and its county; the field, the proposed depth, the formation and the well's API number). The date is the day the
permit was issued (the API numbers run in order with it), so this is `measure="permits"`, basis "permit date". The Commission's yearly "Nebraska Oil Activity Summary" (ANNSUM<year>.pdf, same page)
has a "Permitted Wells for <year>" table by county, which this reads as a check on every list it reads and never as data.

The Commission's HTTPS address resets every connection from the machines this was written on (a relay failure, no HTTP status); its plain HTTP address answers, and it is the address the Commission
links its own files by, so the files are read over HTTP. The downloads are untrusted data twice over: parsed as text, never opened by anything else, and checked against the Commission's own summary.

What it counts, and what it cannot tell:
  - every permit on a year's list is one permit in the month of its date. A well whose permit lapsed and was issued again appears on two lists with one API number and counts twice (three wells in
    2019 to 2025); the Commission's own summary counts it under its newest date only, so its table for 2021 is one permit short of the list (and 2022's, by one in Richardson County);
  - the lists carry no type of well or of work, so the bands are told only by what is printed: `redrill` when the API number's last four digits are not 0000 (the Commission gives a re-entry of an
    old well the old well's number with a new event, and prints "(OWWO)", old well worked over, in its name) or the name says OWWO; `inj` when the well's name has the word SWD (salt water disposal),
    WIW, INJ, INJECTION or DISPOSAL; every other permit is `new`. A disposal or injection well not named so is counted as new, and two test wells for carbon storage (stratigraphic wells under
    the same permit form) are counted as new, as the Commission's own wildcat and development totals count them. `rework`, `amend` and `other` are null: an amendment or a recompletion is not on a
    list of permits to drill. The fluid is not printed (null);
  - the counties (top 15 of the last 12 months) and the operators (only corporations, LLCs and partnerships: `nameable()`; a person's or a trade name is counted but never named) are read from the
    list. The well's name, the API number, the footage, the driller, the field and the formation are never kept;
  - a month with no permit is a real zero: the list for a closed year is the whole year. But the Commission posts a year's list only after the year closes (the 2025 list in March 2026, 2024's in
    February 2025, 2023's in April 2024), so the series ends in December of the newest year it has posted, however old that is. A year counts as closed when the Commission's summary for it has a
    "Permitted Wells" table that agrees with the list (the total within 2 and the counties within 4 in all): the file's `asOf` is then December 31 of that year. With no such table the newest list is
    taken as current only to its newest permit's day, so a quiet end of a year is not read as a zero. The summary for 2023 has no permitted-wells table at all (the state energy office's statistics say "NA"
    for that year too), so 2023 is checked by nothing but the list's own shape.

A full read is the page, one list and one summary for each year from 2019 (15 requests, 3 seconds apart, about 2.5 MB). When a committed nat/NE.json exists, years before the newest two are taken from it
(a closed year's list does not change) and only the page and the newest two years' lists and summaries are read (5 requests); delete the committed file to read everything. A list that is not a PDF,
that has a line it does not know, a county that is not a Nebraska county, an API number that is not Nebraska's 14 digits, dates out of order, outside its year or in the future, a footer total that
disagrees with the count, no permit at all, or that disagrees with the Commission's summary, a missing year, or a page that lost its links fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_ne.py [--check]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "NE"
HOST = "nogcc.ne.gov"
PAGE = "http://nogcc.ne.gov/NOGCCPublications.aspx"  # read over HTTP: the HTTPS address resets every connection from the machines this was written on
PAGE_SHOWN = "https://nogcc.ne.gov/NOGCCPublications.aspx"  # the address a visitor is sent to (the file format wants an https address)
FIRST_YEAR = int(C.FIRST_MONTH[:4])
PAUSE = 3.0
REREAD_YEARS = 2  # the newest this many years are read again each run when a committed file exists
MAX_PAGE, MAX_LIST, MAX_SUMMARY = 2_000_000, 2_000_000, 4_000_000  # the real ones are 36 KB, 0.1 MB and 0.33 MB
MAX_PER_YEAR = 400  # the most in a year since 2005 is about 330 (2008); a list past this was not read right
MIN_TOTAL = 100  # permits 2019 to 2025: 283 when written
MAX_STALE_YEARS = 2  # the newest list posted must be for this year or one of the two before it (a year's list comes out in the first months after it)
SUMMARY_TOTAL_SLACK = 2  # permits by which a list and the Commission's summary may differ in a year (one when written: a re-issued permit is counted once by the summary)
SUMMARY_COUNTY_SLACK = 4  # permits in all, over the counties


def _counties():
    """The 93 Nebraska counties, upper case (the Commission prints them so)."""
    two = ("Box Butte", "Keya Paha", "Red Willow", "Scotts Bluff")
    one = ("Adams Antelope Arthur Banner Blaine Boone Boyd Brown Buffalo Burt Butler Cass Cedar Chase Cherry Cheyenne Clay Colfax Cuming Custer Dakota Dawes Dawson Deuel Dixon Dodge Douglas Dundy "
           "Fillmore Franklin Frontier Furnas Gage Garden Garfield Gosper Grant Greeley Hall Hamilton Harlan Hayes Hitchcock Holt Hooker Howard Jefferson Johnson Kearney Keith Kimball Knox Lancaster "
           "Lincoln Logan Loup Madison McPherson Merrick Morrill Nance Nemaha Nuckolls Otoe Pawnee Perkins Phelps Pierce Platte Polk Richardson Rock Saline Sarpy Saunders Seward Sheridan Sherman Sioux "
           "Stanton Thayer Thomas Thurston Valley Washington Wayne Webster Wheeler York").split()
    return frozenset(n.upper() for n in list(one) + list(two))


COUNTIES = _counties()

LINK = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
LIST_PATH = re.compile(r"^/Publications/(\d{4})WellPermits\.pdf$", re.I)
SUMMARY_PATH = re.compile(r"^/Publications/ANNSUM-?(\d{4})\.pdf$", re.I)
DATE_LINE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}|\d{2}-[A-Za-z]{3}-\d{2})\s*$")
NOISE = re.compile(r"^\s*(Nebraska Permitted Wells|State of Nebraska|Oil and Gas Conservation Commission|Permitted Wells|\d{1,3}|\d{1,2}/\d{1,2}/\d{4}\s+Page \d+ of \d+)\s*$")
FOOTER_TOTAL = re.compile(r"^\s*Total Permits for Period\s*=\s*(\d+)\s*$")
OPERATOR_LINE = re.compile(r"^\s*(.*?)\s*\bDriller:")
LOCATION = re.compile(r"\d{1,2}-\d{1,3}[NS]-\d{1,3}[EW]\s+([A-Z][A-Z .]*?)\s*$")
FIELD_LINE = re.compile(r"^\s*Field:.*\bAPI\s*#?:\s*(\d{14})\s*$")
SERVICE_WORD = re.compile(r"\b(SWD|WIW|INJ|INJECTION|DISPOSAL)\b")
REENTRY_WORD = re.compile(r"\bOWWO\b")


# ------------------------------------------------------------------------------------------------ the page and the PDFs

def parse_page(page):
    """({year: address of its list of permitted wells}, {year: address of its activity summary}) from the Data and Publications page. Only files on the Commission's own host count (a link to the same
    file name elsewhere is not read); a year linked twice keeps its first link. The page must say 'Drilling Permits' and link a list for every year from 2019 to the newest, and the newest must be recent."""
    if "Drilling Permits" not in page:
        raise RuntimeError("the Data and Publications page no longer has its Drilling Permits section: its layout may have changed")
    lists, summaries = {}, {}
    for href in LINK.findall(page):
        u = urllib.parse.urlsplit(urllib.parse.urljoin(PAGE, href.strip()))
        if u.scheme not in ("http", "https") or (u.hostname or "").lower() != HOST:
            continue
        for rx, bag in ((LIST_PATH, lists), (SUMMARY_PATH, summaries)):
            m = rx.match(u.path)
            if m:
                bag.setdefault(int(m.group(1)), urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", "")))
    lists = {y: u for y, u in lists.items() if y >= FIRST_YEAR}
    summaries = {y: u for y, u in summaries.items() if y >= FIRST_YEAR}
    if not lists:
        raise RuntimeError("the page links no list of permitted wells from %d on: its layout may have changed" % FIRST_YEAR)
    newest = max(lists)
    missing = [y for y in range(FIRST_YEAR, newest + 1) if y not in lists]
    if missing:
        raise RuntimeError("the page links no list of permitted wells for %s: its layout may have changed" % ", ".join(map(str, missing)))
    return lists, summaries


def pdf_to_text(data):
    """The text of a PDF through `pdftotext -layout` (poppler-utils), in a new folder, under a timeout. The PDF is data: nothing else opens it."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    if not data.startswith(b"%PDF"):
        raise RuntimeError("a file that should be a PDF is not one")
    with tempfile.TemporaryDirectory(prefix="ne-") as tmp:
        src = os.path.join(tmp, "file.pdf")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-layout", src, "-"], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")}, cwd=tmp)
        if r.returncode != 0:
            raise RuntimeError("pdftotext could not read a file")
        return r.stdout


# ------------------------------------------------------------------------------------------------ one year's list

def band_of(line, api):
    """A permit's band from what the list prints: a re-entry (an API number that is not the well's first, or OWWO in its name), a disposal or injection well (named so), else a new well. The line is the
    well's name, footage, location and county; the API number is read for its last four digits and never kept."""
    if api[10:] != "0000" or REENTRY_WORD.search(line):
        return "redrill"
    if SERVICE_WORD.search(line):
        return "inj"
    return "new"


def parse_list(text, year, today):
    """[{day, operator, county, band}] of a year's 'Nebraska Permitted Wells' text, in list order. Every line must be known (a date, a permit's three lines, or a header, a page number or a footer):
    a line that is not, a county that is not a Nebraska county, an API number that is not 14 digits starting 26, a date outside the year, in the future or before the one above it, a footer total that is not
    the count, or no permit at all raises, so a changed list can never quietly lose permits."""
    lines = [ln for ln in text.replace("\f", "\n").splitlines() if ln.strip()]
    footer, body = None, []
    for ln in lines:
        m = FOOTER_TOTAL.match(ln)
        if m:
            footer = int(m.group(1))
        elif not NOISE.match(ln):
            body.append(ln)
    out, cur, i = [], None, 0
    while i < len(body):
        ln = body[i]
        m = DATE_LINE.match(ln)
        if m:
            cur = C.parse_day(m.group(1), today)
            if cur is None or cur.year != year:
                raise RuntimeError("the %d list has a date that is not a day of %d (or is in the future): %r" % (year, year, m.group(1)))
            if out and cur < out[-1]["day"]:
                raise RuntimeError("the %d list's dates are out of order at %s" % (year, cur.isoformat()))
            i += 1
            continue
        o = OPERATOR_LINE.match(ln)
        if not o or cur is None or i + 2 >= len(body):
            raise RuntimeError("the %d list has a line this does not know (%d characters, after %d permits)" % (year, len(ln.strip()), len(out)))
        place, field = LOCATION.search(body[i + 1]), FIELD_LINE.match(body[i + 2])
        if not place or not field or place.group(1).strip() not in COUNTIES or not field.group(1).startswith("26"):
            raise RuntimeError("permit %d of the %d list is not in the shape this reads (its location line, its county or its API number)" % (len(out) + 1, year))
        out.append({"day": cur, "operator": " ".join(o.group(1).split()), "county": place.group(1).strip(), "band": band_of(body[i + 1], field.group(1))})
        i += 3
    if not out:
        raise RuntimeError("the %d list holds no permit: it may not be the list, or its layout has changed" % year)
    if len(out) > MAX_PER_YEAR:
        raise RuntimeError("the %d list holds %d permits (more than %d)" % (year, len(out), MAX_PER_YEAR))
    if footer is not None and footer != len(out):
        raise RuntimeError("the %d list's own total says %d permits and %d were read" % (year, footer, len(out)))
    return out


# ------------------------------------------------------------------------------------------------ the Commission's own summary of a year

def parse_summary(text, year):
    """(total, {COUNTY: permits}) from the 'Permitted Wells for <year>' table of the Commission's yearly Nebraska Oil Activity Summary; None when the summary has no such table (2023's has none). The
    summary must be the Commission's (its title is checked) and the table must end in a TOTAL row."""
    if "OIL ACTIVITY SUMMARY" not in text.upper():
        raise RuntimeError("the %d summary is not the Commission's Oil Activity Summary" % year)
    rows = [ln for ln in text.splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(rows) if re.search(r"Permitted Wells for\s+\d{4}", ln)), None)
    if start is None:
        return None
    if int(re.search(r"Permitted Wells for\s+(\d{4})", rows[start]).group(1)) != year:
        raise RuntimeError("the %d summary's permitted-wells table is for another year" % year)
    counties = {}
    for ln in rows[start + 1:]:
        t = re.match(r"^\s*TOTAL\s+(\d+(?:\s+\d+){0,2})\s*$", ln)
        if t:
            return int(t.group(1).split()[-1]), counties
        r = re.match(r"^\s*([A-Za-z][A-Za-z .]*?)\s+(\d+(?:\s+\d+){0,2})\s*$", ln)
        if r and r.group(1).strip().upper() in COUNTIES:
            counties[r.group(1).strip().upper()] = int(r.group(2).split()[-1])
        elif re.search(r"\d", ln):
            break  # a line with numbers that is neither a county nor the total: the table has ended or changed
    raise RuntimeError("the %d summary's permitted-wells table has no TOTAL row" % year)


def agrees(permits, summary):
    """True when a year's list and the Commission's table for it are the same count (the total within SUMMARY_TOTAL_SLACK, the counties within SUMMARY_COUNTY_SLACK in all)."""
    total, by = summary
    mine = {}
    for p in permits:
        mine[p["county"].upper()] = mine.get(p["county"].upper(), 0) + 1
    gap = sum(abs(mine.get(c, 0) - by.get(c, 0)) for c in set(mine) | set(by))
    return abs(len(permits) - total) <= SUMMARY_TOTAL_SLACK and gap <= SUMMARY_COUNTY_SLACK


# ------------------------------------------------------------------------------------------------ the run

def previous(keep_from, path=None):
    """The committed nat/NE.json when it can stand for the months before `keep_from` ({month: {band: count}}); {} when there is none or it does not cover them."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        ok = d.get("state") == STATE and months[0] == C.FIRST_MONTH and months == C.month_list(months[0], months[-1]) and months[-1] >= C.add_months(keep_from, -1)
        ok = ok and all(isinstance(bands[b], list) and len(bands[b]) == len(months) for b in ("new", "inj", "redrill")) and all(bands[b] is None for b in ("rework", "amend", "other"))
        return {ym: {b: bands[b][i] for b in ("new", "inj", "redrill")} for i, ym in enumerate(months) if ym < keep_from} if ok else {}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def build(get=C.polite_get, to_text=pdf_to_text, pause=PAUSE, today=None, old=None):
    today = today or date.today()
    lists, summaries = parse_page(get(PAGE, max_bytes=MAX_PAGE).decode("utf-8", "replace"))
    newest_year = max(lists)
    if newest_year < today.year - MAX_STALE_YEARS:
        raise RuntimeError("the newest list of permitted wells is for %d: the page looks stale" % newest_year)
    reread_from = max(FIRST_YEAR, newest_year - REREAD_YEARS + 1)
    kept = (previous("%04d-01" % reread_from) if old is None else old) if reread_from > FIRST_YEAR else {}
    if not kept:
        reread_from = FIRST_YEAR
    permits, closed, n_req, n_checked = [], False, 1, 0
    for year in range(reread_from, newest_year + 1):
        time.sleep(pause)
        got = parse_list(to_text(get(lists[year], max_bytes=MAX_LIST)), year, today)
        n_req += 1
        table = None
        if year in summaries:
            time.sleep(pause)
            table = parse_summary(to_text(get(summaries[year], max_bytes=MAX_SUMMARY)), year)
            n_req += 1
        if table is not None:
            if not agrees(got, table):
                raise RuntimeError("the %d list holds %d permits and the Commission's summary for the year %d: they do not agree" % (year, len(got), table[0]))
            n_checked += 1
            if year == newest_year and today > date(year, 12, 31):
                closed = True
        permits += got
    if not n_checked and not kept:
        raise RuntimeError("no year's list could be checked against the Commission's summary")
    total = len(permits) + sum(sum(v for v in c.values() if isinstance(v, int)) for c in kept.values())
    if total < MIN_TOTAL:
        raise RuntimeError("only %d permits in all (expected %d or more): the lists may be cut short" % (total, MIN_TOTAL))
    t = C.Tally(STATE, bands=("new", "inj", "redrill"), fluid=False)
    for ym, counts in sorted(kept.items()):
        for b, n in counts.items():
            if isinstance(n, int) and n > 0:
                t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"])
    newest = max(p["day"] for p in permits)
    asof = date(newest_year, 12, 31) if closed else newest
    doc = t.document(agency="Nebraska Oil and Gas Conservation Commission", source_name="Drilling Permits (a list of permitted wells for each year), Data and Publications page", source_url=PAGE_SHOWN,
                     basis="permit date (as listed by the Commission)", cadence="yearly (a year's list is posted after the year closes)", measure="permits", asof=asof, first=C.FIRST_MONTH,
                     note="Every permit on the Commission's yearly lists of permitted wells, by the date it is listed under. The Commission posts a year's list after the year closes (2025's in March 2026), "
                          "so these figures end with the newest closed year and a month with no permit is a real zero. The lists name no type of well: a permit is a re-entry when its API number says "
                          "the well is an old one (the Commission prints OWWO), a disposal or injection well when the well is named SWD, WIW or the like, and a new well otherwise (two test wells "
                          "for carbon storage are among them, as in the Commission's own totals). A well whose permit lapsed and was issued again counts each time. Amendments and recompletions "
                          "are not on the lists, and the lists do not say oil from gas.")
    C.log("%s: %d requests (%s), %d years checked against the Commission's summary, %d permits read%s, newest %s%s"
          % (STATE, n_req, "years %d to %d" % (reread_from, newest_year), n_checked, len(permits), " (months before %s are the committed file's)" % ("%04d-01" % reread_from) if kept else "", newest.isoformat(),
             ", year %d closed" % newest_year if closed else ", the newest year is not closed"))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
