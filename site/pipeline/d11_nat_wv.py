#!/usr/bin/env python3
"""D11: West Virginia's drilling permits (Department of Environmental Protection, Office of Oil and Gas), for the National report of the Oil tracker.

The Office posts a "Weekly Permit Report" for every Monday-to-Friday week (a zip holding a PDF and an Excel list, a few days after the week ends; the archive runs from the week of January 7, 2019,
one folder a year at https://apps.dep.wv.gov/Documents/OOG/WeeklyReports/). Each row is one permit ACTION on one well: Issued, Modification, Cancelled, or WR-35 or WR-38 approved (a completion or
plugging report), with the permit type, the well type, the operator and the county. There is no date column: the week is the date. This reads every report and writes nat/WV.json. How a permit is counted (NOTES_D11.md):

  - WHY THIS SOURCE: the Office's TAGIS map service ("All DEP Wells") has exact issue dates, but one row per well holding only its LATEST permit (a later rework or plugging permit would replace a
    new-drill one), about one New Drill row in nine is a repeat of another, and it holds no modifications and no completion reports. Counted by permit number, its New Drill permits agree with the reports
    (checked 2026-11-01, Feb 2019 to Sep 2026: 2,072 against 2,049, and 265 against 265 in the last 12 months; the layer has 34 more, mostly permits issued on a Monday or a Friday that no report lists,
    and the reports have 1 it lacks). So the two agree within 2% on new wells, and the reports, which add every other action, are the count;
  - `new`      Issued, permit type New Drill (and the older labels of a new well: Vertical Well, Horizontal 6A Well...);
    `redrill`  Issued, Re-Drill, Partial Plug Re-drill or Drilling Deeper;
    `rework`   Issued, Re-Work, Fracture or Convert;
    `amend`    every Modification (of a permit of any type: the row repeats a well that was counted when it was issued);
    `other`    Issued, Plugging, Partial Plug and the general, emergency and pit-only permits (plugging is about half of all issued permits), and the few brine-disposal and secondary-recovery ones;
  - NO injection band (null): the Office's UIC (injection) permits are not in the weekly reports (one brine-disposal permit in 2019 to 2022 against 90 UIC permits the map layer holds, issued in
    batches of 30 to 110 on one day); a few permits in the reports that would be injection are filed under other;
  - left out: Cancelled (the permit was counted in the week it was issued) and WR-35 or WR-38 approved (a report on a well, not a permit);
  - the columns are not reliable: in the 400 reports read, one week (2019-12-02, 43 rows) has the action and the permit type exchanged and three weeks have 96 rows with the permit type and the
    well type exchanged, so a row's action and permit type are found by what the values ARE (an action is one of five words; a permit type is in the Office's list), never by their column; a
    report whose action column is headed "Permit Action", one with a repeated heading row and one with Word's lock file in its zip are read too;
  - a week is put in the month that holds most of its days (its Wednesday), so a week at a month's edge can be a few days off; the series starts in February 2019 because the first report is the
    week of January 7, so January 2019 would be short; a week the Office did not post (3 of 400: Christmas week 2023 and two others) is listed in the note and not counted;
  - the permit records no fluid (oil or gas), so no fluid split is made; the county and the operator of the new-well permits are kept as counts (a company only; a person's name is never published).

The permit rows' API number and well number are never read (only the five columns above are taken from the workbook; the action's heading is spelled two ways). A run reads the last 14 months of reports again, and keeps the older months' counts
from the committed file; with no committed file it reads all of them (about 400 small files, 2.5 seconds apart). Files are untrusted data: parsed, never run, sizes checked before anything is unpacked.

  python3 -I site/pipeline/d11_nat_wv.py [--check]
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import zipfile
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import ok_xlsx  # noqa: E402  (the repository's standard-library reader for .xlsx)

STATE = "WV"
TOLD = ("new", "redrill", "rework", "amend", "other")  # the bands the reports can tell; injection is null
ARCHIVE = "https://apps.dep.wv.gov/Documents/OOG/WeeklyReports/"
PAGE = "https://dep.wv.gov/OIL-AND-GAS/GI/Pages/WeeklyReports.aspx"  # the Office's page about the reports (the source link on the report)
FIRST = "2019-02"  # the archive starts with the week of 2019-01-07, so January 2019 would miss its first week
FIRST_YEAR = 2019
PAUSE = 2.5
REREAD_MONTHS = 13  # reports of this many months back, and the month now, are read again every run (the last 12 complete months' counties and operators need them)
MAX_ZIP = 5_000_000  # a report is 0.1 to 0.2 MB
MAX_MEMBER = 5_000_000
MAX_UNPACKED = 20_000_000
MAX_MISSING = 8  # weeks the Office did not post (or whose file cannot be read) before the run fails (3 in 400 so far)
MIN_WEEKS = 40  # reports found in the archive's folders (about 400)
STALE_DAYS = 35  # the newest report is no older than this
MAX_ODD = 0.02  # actions or well records not understood, in more than this share of the rows
MAX_UNKNOWN = 0.05  # permit types in no table, in more than this share of the issued rows
MIN_YEAR = 150  # permit actions in each full calendar year since 2019 (the lowest year had about 400)
MIN_NEW12 = 40  # new-well permits in the last 12 complete months
WANT = ("Permit_Action", "Permit Type", "Well Type", "Operator", "County Name")  # what a row of a report holds here: nothing else is read, no API number, no well number
REQUIRED = WANT[1:]
ACTION_HEADERS = ("Permit_Action", "Permit Action")  # one real report (2022-08-15) spells the first with a space

NAME = re.compile(r"Weekly (?:Permit )?Report (\d{1,2})-(\d{1,2})-(\d{2}|\d{4})\b", re.I)
ENTRY = re.compile(r'<a href="([^"?#]+\.zip)"[^>]*>[^<]*</a>\s*(?:(\d{1,2}-[A-Za-z]{3}-\d{4} \d{1,2}:\d{2}))?', re.I)  # one line of the folder's index

# the permit types of the Office's own words (lower case) and the band of an ISSUED permit; modifications are all amendments
TYPE_BAND = {
    "new drill": "new", "horizontal 6a well": "new", "vertical well": "new", "horizontal well": "new", "horizontal deep well": "new", "coalbed methane / horizontal": "new", "replacement": "new",
    "uic permit": "other", "brine disposal": "other", "secondary recovery well": "other", "storage": "other",  # injection permits: the weekly reports hold almost none (see the docstring), so no injection band
    "re-drill": "redrill", "partial plug re-drill": "redrill", "drilling deeper": "redrill",
    "re-work": "rework", "fracture": "rework", "convert": "rework", "fracture / horizontal well": "rework", "fracture / coalbed methane": "rework", "rework - coalbed methane": "rework",
    "rework-secondary recovery": "rework", "rework/solution mining": "rework", "rework/horizontal 6a well": "rework",
    "plugging": "other", "partial plug": "other", "general permit": "other", "emergency permit": "other", "pit only permit": "other", "other well": "other",
    "field assigned number": "other", "not available": "other", "replacement borehole h6a": "other", "assigned permit number": "other",
}
ACTION = re.compile(r"issued|modification|cancel+ed|wr-\d+_approved")  # the five actions seen (the last two kinds are a report on a well, not a permit)
PERMIT_WORDS = frozenset(k for k in TYPE_BAND if k != "not available")  # "Not Available" is also a well type
WELL_WORDS = frozenset({"horizontal 6a", "vertical", "horizontal", "coal bed methane well", "not available"})  # what the Well Type column holds


def entries(html, year):
    """[(monday, href, modified)] for the reports a folder's index lists. The week is read from the file name, which has typos (a wrong year, a Sunday or a Tuesday for the Monday, two-digit years):
    the stated year first, then the folder's, whichever gives a Monday; otherwise the nearest Monday (Thursday and before go back, Friday and after go forward)."""
    out = []
    for href, mod in ENTRY.findall(html):
        m = NAME.search(urllib.parse.unquote(href))
        if not m:
            continue
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        days = []
        for yy in (y, year):
            try:
                days.append(date(yy, mo, d))
            except ValueError:
                pass
        if not days:
            continue
        day = next((x for x in days if x.weekday() == 0), None)
        if day is None:
            day = days[-1]
            day = day - timedelta(days=day.weekday()) if day.weekday() <= 3 else day + timedelta(days=7 - day.weekday())
        if abs(day.year - year) > 1:
            continue
        try:
            when = datetime.strptime(mod, "%d-%b-%Y %H:%M") if mod else None
        except ValueError:
            when = None
        out.append((day, href, when))
    return out


def to_month(monday):
    """The month a week is counted in: the one that holds most of its days, found by its Wednesday."""
    return C.month_of(monday + timedelta(days=2))


def action_and_type(r):
    """(action, permit type) of a row, told apart by what the values are, not by their column (the Office's lists swap them in some weeks); (None, None) when the row does not hold exactly one action.
    The action is the one value that is an action; the permit type is the one of the other two that is in the Office's permit list (else the one that is not a well type; else the column's own)."""
    vals = [" ".join((r.get(k) or "").split()) for k in ("Permit_Action", "Permit Type", "Well Type")]
    found = [i for i, v in enumerate(vals) if ACTION.fullmatch(v.lower())]
    if len(found) != 1:
        return None, None
    rest = [v for i, v in enumerate(vals) if i != found[0]]  # in column order
    perm = [v.lower() in PERMIT_WORDS for v in rest]
    if perm[0] != perm[1]:
        return vals[found[0]].lower(), rest[0] if perm[0] else rest[1]
    well = [v.lower() in WELL_WORDS for v in rest]
    return vals[found[0]].lower(), rest[1] if (well[0] and not well[1]) else rest[0]


def band_of(action, ptype):
    """(band or None, known): the band of one permit action (`action` as action_and_type gives it): None for an action that is not a permit (cancelled, a report approved), `known` False for a permit
    type in no table (it is read with the shared words, and the run fails if too many are)."""
    if action == "modification":
        return "amend", True
    if action != "issued":
        return None, True
    t = " ".join((ptype or "").lower().split())
    if t in TYPE_BAND:
        return TYPE_BAND[t], True
    return C.band_of(ptype, ""), False


def read_week(data):
    """The rows of one weekly report as dicts of WANT. The zip's sizes are checked before anything is unpacked, only its Excel list is read, and a workbook that lacks a wanted column fails."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("a weekly report is not a zip file")
    with z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED or any(i.file_size > MAX_MEMBER for i in infos):
            raise RuntimeError("a weekly report unpacks to more than expected")
        books = [i for i in infos if i.filename.lower().endswith(".xlsx") and not os.path.basename(i.filename).startswith(("~", "."))]
        if len(books) != 1:
            raise RuntimeError("a weekly report holds %d Excel lists (expected 1)" % len(books))
        with tempfile.TemporaryDirectory(prefix="wv-") as tmp:
            path = os.path.join(tmp, "week.xlsx")
            with z.open(books[0]) as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            try:
                return [dict({"Permit_Action": r.get(ACTION_HEADERS[0]) or r.get(ACTION_HEADERS[1])}, **{k: r[k] for k in REQUIRED}) for r in ok_xlsx.rows(path, want=REQUIRED, optional=ACTION_HEADERS)]
            except (ValueError, KeyError, zipfile.BadZipFile) as e:
                raise RuntimeError("a weekly report's Excel list cannot be read (%s)" % str(e)[:80])


def previous(path=None):
    """{month: {band: count}} from the committed nat/WV.json, so months that will not change are not read again; {} when there is none or it is not a file this producer wrote."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        if d.get("v") != 1 or d.get("state") != STATE or d.get("measure") != "permits" or not months or bands.get("inj") is not None \
                or any(not isinstance(bands.get(b), list) or len(bands[b]) != len(months) for b in TOLD):
            return {}
        return {ym: {b: bands[b][i] for b in TOLD} for i, ym in enumerate(months)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def fetch_index(get, today, pause):
    """{monday: (href, year)} for every report in the archive's yearly folders (the current year's folder may not exist yet in the first days of January)."""
    weeks, dups = {}, 0
    for year in range(FIRST_YEAR, today.year + 1):
        if year > FIRST_YEAR:
            time.sleep(pause)
        try:
            html = get("%s%d/" % (ARCHIVE, year), max_bytes=2_000_000).decode("utf-8", "replace")
        except C.Refused:
            raise
        except RuntimeError:
            if year == today.year:
                continue
            raise
        for monday, href, when in sorted(entries(html, year), key=lambda e: e[2] or datetime.min):
            url = urllib.parse.urljoin("%s%d/" % (ARCHIVE, year), href)
            if not url.startswith(ARCHIVE):  # a listing is data: it cannot send the run to another place
                continue
            dups += monday in weeks  # a second file for one week: the later-posted one is kept
            weeks[monday] = (url, year)
    return weeks, dups


def build(get=C.polite_get, today=None, pause=PAUSE, old=None):
    today = today or date.today()
    old = previous() if old is None else old
    keep_from = C.add_months(C.month_of(today), -REREAD_MONTHS)
    weeks, _dups = fetch_index(get, today, pause)
    weeks = {m: v for m, v in weeks.items() if to_month(m) >= FIRST}
    if len(weeks) < MIN_WEEKS:
        raise RuntimeError("the archive lists %d weekly reports (expected 400 or so): its layout may have changed" % len(weeks))
    newest = max(weeks)
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest weekly report is for the week of %s: the archive looks stale" % newest.isoformat())
    missing, d = [], min(weeks)
    while d < newest:
        if d not in weeks:
            missing.append(d)
        d += timedelta(days=7)
    t = C.Tally(STATE, bands=TOLD, fluid=False)
    for ym, counts in sorted(old.items()):  # the months already known and older than the window
        if FIRST <= ym < keep_from:
            for b, n in counts.items():
                if isinstance(n, int) and n > 0:
                    t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    rows_n, odd, unknown, issued, skipped = 0, 0, 0, 0, []
    todo = [m for m in sorted(weeks) if to_month(m) >= keep_from or to_month(m) not in old]
    for monday in todo:
        time.sleep(pause)
        try:
            rows = read_week(get(weeks[monday][0], max_bytes=MAX_ZIP))
        except C.Refused:
            raise
        except (RuntimeError, zipfile.BadZipFile, NotImplementedError, OSError):
            skipped.append(monday)  # a report that cannot be read is a missing week, not a quiet zero
            continue
        day = monday + timedelta(days=2)
        for r in rows:
            rows_n += 1
            action, ptype = action_and_type(r)
            if action is None:
                odd += 1
                continue
            band, known = band_of(action, ptype)
            if band is None:
                continue
            issued += action == "issued"
            unknown += not known
            t.add(day, band, county=(r.get("County Name") or "").strip() or None, operator=(r.get("Operator") or "").strip() or None)
    if odd > MAX_ODD * max(1, rows_n):
        raise RuntimeError("%d of %d permit rows have an action that is not understood: the reports may have changed" % (odd, rows_n))
    if unknown > MAX_UNKNOWN * max(1, issued):
        raise RuntimeError("%d of %d issued permits have a type the Office's list does not explain: the types may have changed" % (unknown, issued))
    gaps = sorted(set(missing) | set(skipped))
    if len(gaps) > MAX_MISSING:
        raise RuntimeError("%d weekly reports are missing or cannot be read (expected %d or fewer)" % (len(gaps), MAX_MISSING))
    asof = min(newest + timedelta(days=6), today)
    doc = t.document(agency="West Virginia Department of Environmental Protection, Office of Oil and Gas", source_name="Weekly Permit Report (one list a week of the permit actions)", source_url=PAGE,
                     basis="issue date, by week (Monday to Friday)", cadence="weekly (a report a few days after each week ends)", measure="permits", asof=asof, first=FIRST,
                     note=_note(gaps))
    for y in range(FIRST_YEAR, today.year):
        n = sum(sum(v[i] for v in doc["bands"].values() if v) for i, ym in enumerate(doc["months"]) if ym.startswith(str(y)))
        if n and n < MIN_YEAR:
            raise RuntimeError("only %d permit actions in %d (expected %d or more): reports may be missing" % (n, y, MIN_YEAR))
    if sum(doc["bands"]["new"][-12:]) < MIN_NEW12:
        raise RuntimeError("only %d new-well permits in the last 12 months (expected %d or more)" % (sum(doc["bands"]["new"][-12:]), MIN_NEW12))
    return doc


def _note(gaps):
    when = ", ".join(d.strftime("%b %d, %Y").replace(" 0", " ") for d in gaps)
    return ("Permit actions from the Office's Weekly Permit Report: one list for each Monday-to-Friday week with no day by permit, so a week is counted in the month that holds most of its days. "
            "Issued permits are counted by type: new wells (New Drill, mostly horizontal 6A wells), re-entries (re-drill, drilling deeper), reworks (re-work, fracture, convert) and other (plugging "
            "permits, about half, and general or emergency permits). A modification of an issued permit is an amendment. Cancelled permits (counted when issued) and approved completion "
            "or plugging reports are left out. The reports hold no injection (UIC) permits, so no injection count is shown. The permit records no oil or gas, so no fluid is shown. "
            "The Office's map layer has exact dates but one row per well's latest permit, some of them twice, and no modifications; counted by permit number it agreed with these reports on new "
            "wells to within 2% when checked (Nov 2026), so the reports are the count. The series starts in February 2019, after the first report (the week of January 7)."
            + (" Weeks with no report (not counted): %s." % when if gaps else ""))


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
