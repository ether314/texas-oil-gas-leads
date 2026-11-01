#!/usr/bin/env python3
"""D11: Indiana's well permits (Department of Natural Resources, Division of Reclamation: Oil and Gas), for the National report of the Oil tracker.

The Division publishes its permits as a PDF for every week ("Weekly Permits Listing", https://www.in.gov/dnr/oil-and-gas/publications/weekly-permits-listing: one list per week ending Friday, every week
from January 2020, 355 links when written; a week with no permit has a list that says so). Its ArcGIS well layer has no permit date and its monthly report has no index, so the weekly lists are the one
source of permit dates. Each permit is a short paragraph in a fixed wording: the operator (with its address and phone, which are never read), "was issued a(n) <well type> permit on <date>", the county,
and "This <direction> <application type> well". This reads the lists with `pdftotext -layout` (poppler-utils) and counts every permit by the day it was issued: `measure` "permits", `basis` "issue date".
What it can tell:

  - `new`: a new ("New") oil, gas, non-commercial gas or coal bed methane well, with `fluid` from the well type; `inj`: an enhanced recovery (a waterflood well), disposal, storage, water supply or other
    service well; `redrill`: a deepening or re-entry; `rework`: a conversion, workover or plug-back; `amend`: a modification, renewal, change of operator or of location, or transfer; `other`: a test
    well (geologic structure, county or individual test, investigatory), an application type this file does not know, or a blank one on a well that is not a service well (counted, never taken for a
    new well). Every permit is in exactly one band;
  - the lists start in January 2020, so the series does too (a month the source does not cover is not a zero). A list exists for every week, so a month with no permit is a real zero;
  - Indiana is small: 853 permits from January 2020 to October 2026 when written, 40 to 100 of them new wells a year (48 in the last 12 months), almost all in the Illinois Basin counties of the south-west (Posey, Gibson, Knox,
    Sullivan). The Division's monthly report lists the same permits, and for June 2021 (12), October 2021 (21), January 2022 (31) and May 2026 (5) the weekly lists add up to its counts exactly;
  - the Division's own files have two defects, so the count is a little low: its index links two weeks of July 2023 to one file (its monthly report counts 9 permits for the month, the lists 7; August
    2020 has the same defect and its counts agree), and one PDF (the week ending September 2, 2022) prints three permits on top of each other, so two cannot be read (one is counted as unread). Its chart of
    permits by year (2013 to 2022: 155, 149 and 148 for 2020 to 2022) is on another basis it does not state: the lists give 154, 110 and 170 for the calendar years, so it is not used.

A full read is 353 PDFs (about 75 MB, one request a second: about nine minutes). So when a committed nat/IN.json exists, months older than the last 14 are taken from it and only the weeks of the last 14
months (about 65 files) are read again, as the BLM's producer does (a list may be corrected after release); delete the committed file to read everything. An index that lost its table or its newest weeks, a
list that cannot be fetched or has no paragraph and no statement of none, more than a few paragraphs that do not parse, or a refusal fails the run and leaves the committed file alone.

Nothing leaves a list but the well type, the dates, the county, the application type and the operator's name (published only if it is a corporation, LLC or partnership: many Indiana operators are
individuals): no address, phone, lease, well number, permit number, pool or location is kept. The PDFs are untrusted data, parsed as text and never opened by anything else; requests identify no person.

  python3 -I site/pipeline/d11_nat_in.py [--check]
"""
import calendar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "IN"
HOST = "https://www.in.gov"
INDEX = HOST + "/dnr/oil-and-gas/publications/weekly-permits-listing"
FIRST = "2020-01"  # the first month the weekly lists cover
PAUSE = 1.0
REREAD = 14  # months read again each run when a committed file exists
MIN_WEEKS = 250  # 355 lists when written (52 a year since 2020)
MIN_PERMITS = 400  # about 800 permits since 2020 when written
STALE_DAYS = 60  # the newest list on the index must be this recent
MAX_PDF = 3_000_000  # the largest list seen is 0.7 MB
KNOWN_REPEATED = frozenset({date(2020, 8, 28), date(2023, 7, 28)})  # weeks the index links to the previous week's file (the second of each pair)
MAX_REPEATED = 6  # weeks linked to another week's file (2 when written)
MAX_UNREAD = 5  # paragraphs a run may leave out (2 in the whole history when written)
MONTHS = {m: i + 1 for i, m in enumerate(calendar.month_name[1:])}
SERVICE = re.compile(r"enhanced recovery|class ii|water ?flood|dispos|inject|storage|brine|service|observation|monitor", re.I)
PAGE_NOISE = re.compile(r"permits issued|department of natural|division of|state of indiana|pool is permitted|surface elevation", re.I)  # lines that are not an operator line
START = re.compile(r"^\s*was\s+issued\s+a\(\s*n\s*\)")  # the older lists were scanned and read by OCR: "a(n )", "11/30/2020. The#" and the like
PARA = re.compile(r"^\s*was\s+issued\s+a\(\s*n\s*\)\s+(?P<kind>.+?)\s+permit\s+on\s+(?P<day>\d{1,2}/\d{1,2}/\d{4})\s*\.")
COUNTY = re.compile(r"is\s+located\s+(?:in\s+)?(?P<county>[A-Za-z][A-Za-z.'\-]*(?: [A-Za-z][A-Za-z.'\-]*){0,2})\s+County\s*,")  # the "in" sometimes wraps to the next line
APPLIC = re.compile(r"This\s+(?P<dir>\S+)(?:\s+(?P<app>.*?))?\s+well\s*,?\s+located\s+in\s+the")
PERIOD = re.compile(r"From\s+(\d{1,2}/\d{1,2}/\d{4})\s+To\s+(\d{1,2}/\d{1,2}/\d{4})")
NONE = re.compile(r"no permits?\s+(were\s+)?issued", re.I)


# ------------------------------------------------------------------------------------------------ the index of weekly lists

def parse_index(html):
    """([(week_end, url)] oldest first, [week_end of every week whose link repeats another week's file]): one entry for each list on the index. Its tables (one for each year, headed "2026 Week
    Ending", a row of months and a row of weeks, five columns to a month) hold the day of each week's Friday, linked to the PDF; a day with no link is a week not yet published (or a blank cell). The
    links are of many shapes (/dA/<hash>/og-week2510.pdf?language_id=1, /dnr/oil-and-gas/files/og-2601.pdf, week2505.pdf), so the table, not a file name, says which week a file is. Two weeks
    on the real page share one file (a typo): the second is in the repeated list, and is never counted twice. Only PDFs on www.in.gov are taken."""
    out, seen, repeated = [], set(), []
    for table in re.findall(r"<table[\s\S]*?</table>", html, re.I):
        year = re.search(r"(\d{4})\s+Week Ending", table)
        if not year:
            continue
        cols = []  # the month of each column
        for row in re.findall(r"<tr[\s\S]*?</tr>", table, re.I):
            cells = re.findall(r"<t[dh]\b([^>]*)>([\s\S]*?)</t[dh]>", row, re.I)
            texts = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ")).strip() for _, c in cells]
            if texts and all(t in MONTHS for t in texts):
                cols = []
                for (attrs, _), t in zip(cells, texts):
                    span = re.search(r'colspan="(\d+)"', attrs)
                    cols += [t] * (int(span.group(1)) if span else 1)
                continue
            if not cols:
                continue
            for i, (_, c) in enumerate(cells):
                link = re.search(r'href="([^"]+)"', c)
                label = re.sub(r"<[^>]+>", "", c).strip()
                if not link or not label.isdigit() or i >= len(cols):
                    continue
                url = urllib.parse.urljoin(INDEX, link.group(1).replace("&amp;", "&"))
                if not url.startswith(HOST + "/") or not urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
                    continue
                y, m = int(year.group(1)), MONTHS[cols[i]]
                day = date(y, m, min(int(label), calendar.monthrange(y, m)[1]))
                if url in seen:
                    repeated.append(day)
                    continue
                seen.add(url)
                out.append((day, url))
    return sorted(out), sorted(repeated)


# ------------------------------------------------------------------------------------------------ one weekly list

def band_of_permit(app, kind):
    """(band, fluid) from the application type ("New", "Deepening", "Conversion", "Modification", "Renewal", "Change of Operator", "Change of Location") and the well type ("Oil", "Enhanced Recovery",
    "Geologic/ Structure Test"...; the Division's field cuts a long type short: "Non-Commercial Ga"). The shared words do the work; a service well (enhanced recovery is a waterflood injection well,
    "Water Supply" and "Gas Storage/ Observ" are service wells too) is `inj`; a test well (a geologic structure, county or individual test, an investigatory well) that would be new is `other`: it is
    drilled for information, not to produce; a blank application type is `inj` on a service well and `other` on any other, never a new well."""
    service = bool(SERVICE.search(kind))
    if not app.strip():
        band = "inj" if service else "other"
    elif re.search(r"change of location", app, re.I):
        band = "amend"
    else:
        band = C.band_of(app, kind + (" injection" if service else ""))
    if band == "new" and re.search(r"test|structure|investigat", kind, re.I):
        band = "other"
    if band != "new":
        return band, None
    return band, "gas" if re.match(r"non-?commercial", kind, re.I) else C.fluid_of(kind)


def parse_week(text, today=None):
    """(permits, unread) from the text of one weekly list (pdftotext -layout). `permits` are dicts {day, band, fluid, county, operator, blank}; `unread` counts the paragraphs that could not be read (the
    PDF renders a few so that three permits overlap on the page, or a field is garbled: the paragraph is left out and counted, and the run fails if they are more than a few). A list that says there were
    no permits gives ([], 0); a text that is neither a list of permits nor that statement raises ValueError."""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if START.match(l)]
    located = len(re.findall(r"is\s+located\b", text))
    if not starts:
        if NONE.search(text) and not located:
            return [], 0
        raise ValueError("a weekly list with no permits and no statement that there were none")
    period = PERIOD.search(text)
    window = [C.parse_day(x) for x in period.groups()] if period else []
    out, unread = [], max(0, located - len(starts))  # a paragraph that lost its first line is counted, not read
    for k, i in enumerate(starts):
        end = min(starts[k + 1] - 1 if k + 1 < len(starts) else len(lines), i + 8)  # this paragraph's lines: not the next one's operator line
        block = re.sub(r"\s+", " ", " ".join(l for l in lines[i:end] if l.strip()))
        m, c, a = PARA.match(lines[i]), COUNTY.search(block), APPLIC.search(block)
        day = C.parse_day(m.group("day"), today=today) if m else None
        if not (m and c and a and day) or (len(window) == 2 and all(window) and not (window[0] - timedelta(days=45) <= day <= window[1] + timedelta(days=45))):
            unread += 1
            continue
        prev = next((lines[j] for j in range(i - 1, max(i - 4, -1), -1) if lines[j].strip()), "")
        operator = "" if PAGE_NOISE.search(prev) else re.split(r"\s{2,}", prev.strip())[0][:80]  # the first column of the line above: the name; the address and phone after it are never read
        kind, app = re.sub(r"\s+", " ", m.group("kind")).strip(), re.sub(r"\s+", " ", a.group("app") or "").strip()
        band, fluid = band_of_permit(app, kind)
        out.append({"day": day, "band": band, "fluid": fluid, "county": c.group("county").strip(), "operator": operator, "blank": not app})
    return out, unread


def pdf_to_text(data):
    """The text of a PDF through `pdftotext -layout` (poppler-utils), in a new folder, under a timeout. The PDF is data: nothing else opens it."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    with tempfile.TemporaryDirectory(prefix="in-") as tmp:
        src = os.path.join(tmp, "list.pdf")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-layout", src, "-"], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")}, cwd=tmp)
        if r.returncode != 0:
            raise RuntimeError("pdftotext could not read a list")
        return r.stdout


# ------------------------------------------------------------------------------------------------ the run

def previous(keep_from, path=None):
    """The committed nat/IN.json when it can stand for the months before `keep_from` ({month: {band: count}}); {} when there is none or it does not cover them."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        months, bands = d["months"], d["bands"]
        ok = d.get("state") == STATE and months[0] == FIRST and months == C.month_list(months[0], months[-1]) and months[-1] >= C.add_months(keep_from, -1)
        ok = ok and all(isinstance(bands[b], list) and len(bands[b]) == len(months) for b in C.BANDS)
        return {ym: {b: bands[b][i] for b in C.BANDS} for i, ym in enumerate(months) if ym < keep_from} if ok else {}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def build(get=C.polite_get, to_text=pdf_to_text, pause=PAUSE, today=None, old=None):
    today = today or date.today()
    weeks, repeated = parse_index(get(INDEX, max_bytes=3_000_000).decode("utf-8", "replace"))
    if len(weeks) < MIN_WEEKS:
        raise RuntimeError("the index lists %d weekly lists (expected %d or more): its layout may have changed" % (len(weeks), MIN_WEEKS))
    if len(repeated) > MAX_REPEATED:
        raise RuntimeError("the index links %d weeks to a file another week already uses: its layout may have changed" % len(repeated))
    if weeks[0][0] > date(2020, 2, 15):
        raise RuntimeError("the index no longer reaches back to January 2020")
    newest = min(weeks[-1][0], today)
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest weekly list is for the week ending %s: the index looks stale" % weeks[-1][0].isoformat())
    keep_from = max(FIRST, C.add_months(C.month_of(today), -REREAD))
    kept = (previous(keep_from) if old is None else old) if keep_from > FIRST else {}
    if not kept:
        keep_from = FIRST
    # the list for a Friday in the first days of a month also holds the Monday to Thursday before it (the month before's last days), so lists are read from a week before the month starts
    first_day = date(int(keep_from[:4]), int(keep_from[5:]), 1) - timedelta(days=8)
    permits, unread, n_files = [], 0, 0
    for end, url in weeks:
        if end < first_day:
            continue
        if n_files:
            time.sleep(pause)
        n_files += 1
        try:
            got, bad = parse_week(to_text(get(url, max_bytes=MAX_PDF)), today)
        except C.Refused:
            raise
        except ValueError as e:
            raise RuntimeError("the list for the week ending %s: %s" % (end.isoformat(), e))
        permits += got
        unread += bad
    if unread > MAX_UNREAD or unread > 0.02 * (len(permits) + unread):
        raise RuntimeError("%d paragraphs of %d could not be read: the lists' layout may have changed" % (unread, len(permits) + unread))
    t = C.Tally(STATE, bands=C.BANDS, fluid=True)
    for ym, counts in sorted(kept.items()):
        for b, n in counts.items():
            if isinstance(n, int) and n > 0:
                t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    used = [p for p in permits if C.month_of(p["day"]) >= keep_from and C.month_of(p["day"]) >= FIRST]
    if len(used) + sum(sum(v.values()) for v in kept.values()) < MIN_PERMITS:
        raise RuntimeError("only %d permits in all (expected %d or more): the lists may be cut short" % (len(used) + sum(sum(v.values()) for v in kept.values()), MIN_PERMITS))
    for p in used:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    doc = t.document(agency="Indiana Department of Natural Resources, Division of Reclamation (Oil and Gas)", source_name="Weekly Permits Listing (one PDF a week)", source_url=INDEX,
                     basis="issue date (the day the permit was issued)", cadence="weekly (a list for each week ending Friday)", measure="permits", asof=newest, first=FIRST,
                     note="Every permit on the Division's weekly lists, by the day it was issued: new wells (oil, gas and coal bed methane), enhanced recovery and other service wells, deepenings, "
                          "conversions, and modifications, renewals and changes of operator; test wells are other filings. The lists start in January 2020; a week with no permit has a list that says so, "
                          "so a quiet month is a real zero. Two defects in the Division's own files leave a few permits out: its index points two weeks of July 2023 at one file (its monthly report counts "
                          "two permits more than the lists for that month), and one PDF (the week ending September 2, 2022) prints three permits on top of each other, so two are not read. "
                          "The last 14 months are read again each week, since a list may be corrected after release.")
    new_repeats = [d for d in repeated if d not in KNOWN_REPEATED]
    if new_repeats:
        doc["note"] += " The index also points the weeks ending %s at a file another week uses: any permits in them are not counted." % ", ".join("%s %d, %d" % (calendar.month_name[d.month], d.day, d.year) for d in new_repeats)
    blank = sum(1 for p in used if p["blank"])
    C.log("%s: %d weekly lists read%s, %d permits in them, %d with no application type, %d paragraphs left out as unreadable"
          % (STATE, n_files, " (months before %s are the committed file's)" % keep_from if kept else " (all of them)", len(used), blank, unread))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
