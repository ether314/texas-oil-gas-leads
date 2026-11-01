#!/usr/bin/env python3
"""D11: Idaho's oil and gas permits to drill (Department of Lands, Oil and Gas Conservation Commission), for the National report of the Oil tracker.

Idaho has about 34 wells on file since 2007 and approves roughly one permit to drill a year (none dated 2019, 2020, 2023 or 2024 here). The Commission publishes no table of permits, but it does publish
a page for every well (https://ogcc.idaho.gov/well-files/ lists them, one WordPress page each) with the county, the operator and a link to the signed "Permit to Drill" PDF, whose FILE NAME starts with
the day the permit was approved (2026.02.04_... or 20211002_...). This reads the index and opens each well page once (one request every 3 seconds, about 35 in all) and counts those days by month:
`measure="permits"`, basis "approval date".

What was checked before relying on the file-name date (2026-11-01, by reading the signed permits themselves, and against the Commission's own quarterly reports):
  - for six of the eight permits since 2019 the name's date is the approval letter's date (or the form's own "Approval Date"), to the day or within two days;
  - for two it is NOT: the posted file is the permit as AMENDED (its first pages are the amendment's approval letter, dated Sept 13 and Dec 24, 2021), and the original approval is earlier in the same
    PDF (June 16 and Nov 17, 2021; the first amendment letter itself says "permitted ... on June 16, 2021"). The Commission's quarterly "APDs approved" counts agree with the originals (June 2021: 1,
    Nov 2021: 1). A script cannot read those letters, so the two dates are written down here (`ORIGINAL_APPROVAL`, keyed by the amended file's date), each held to the page's own creation date
    (WordPress makes a well's page the day it posts its permit);
  - a posted file that is a later version (its name or link says revised or amended, or its date is more than 5 days after its page was made or more than 60 before it) with no entry in that
    table FAILS the run, naming the date to look up: a new amended permit must be read by a person, never guessed.

What is counted, and what is not:
  - `new` only: a permit to drill. The index lists no amendment, well treatment, seismic or injection permit as a dated record (well-treatment and seismic applications are posted on another page
    and are not drilling permits), so no other band is claimed (null, never zero). The fluid is not on the page (null);
  - a well whose permit expired unused has no page and is not counted (the Commission's Data Explorer lists three such permits, with no dates); an application still under review is not a permit;
  - the permit PDFs are never opened here. The county and the operator are read from the page's own text; the operator is named only if the shared rule accepts it. The pages abbreviate one
    operator as "Snake River O&G"; the Commission's own reports and the signed permits call it "Snake River Oil and Gas, LLC", which is the name counted (`OPERATOR_FULL`);
  - a month with no permit is a real zero: every approved permit has a page, posted within days (up to two weeks) of its approval, so the last 30 days before the read are not shown (`lag_days`);
  - a permit file with no date in its name is accepted only on a page made before July 2019 (the Commission's one-time import of its older well files): both are wells of 2007 and 2017.
A page that lost its layout, an index that is cut short, fewer permits than the committed file already holds, or a date that cannot be placed fails the run (nothing is written).

  python3 -I site/pipeline/d11_nat_id.py [--check]
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "ID"
HOST = "https://ogcc.idaho.gov"
INDEX = HOST + "/well-files/"
PAUSE = 3.0
LAG_DAYS = 30
MIN_WELLS, MAX_WELLS = 30, 200  # 34 wells when written; the index only grows
MIN_DATED = 20  # 32 of the 34 permits have a date in their file name
SERIES_START = date(int(C.FIRST_MONTH[:4]), int(C.FIRST_MONTH[5:]), 1)
IMPORT_END = date(2019, 7, 1)  # the Commission made the pages of its older wells in June 2019
LINK = re.compile(r'href="(?:' + re.escape(HOST) + r')?(/well-files/uswn-[a-z0-9\-]+/)"', re.I)
NAME_DATE = re.compile(r"^(\d{4})([.\-]?)(\d{2})\2(\d{2})(?=[_\-. ])")  # 2026.02.04_..., 20211002_...; not 1101920011_... (an API number) nor 11-019-20014-... (the same)
ENTRY = re.compile(r'<div class="entry-content">(.*?)<footer class="entry-footer">', re.S)
PARA = re.compile(r"<p>(.*?)</p>", re.S | re.I)
ANCHOR = re.compile(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
META = r'<meta name="DCTERMS\.%s" content="(\d{4}-\d\d-\d\d)'
# the later version of a permit is posted over the first one: the date in the file name is then the amendment's, not the approval's. {the amended file's date: the first approval's day}, each read
# from the signed permit in the same PDF (the approval letter; the Data Explorer's issue date and the Commission's quarterly count agree: June 2021 and November 2021 each hold one approval).
ORIGINAL_APPROVAL = {date(2021, 9, 13): date(2021, 6, 16), date(2021, 12, 24): date(2021, 11, 17)}
OPERATOR_FULL = {"SNAKE RIVER O&G": "Snake River Oil and Gas, LLC"}  # the page's short form; the Commission's reports and the signed permits give the company's name


def plain(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def long_day(d):
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def parse_index(page):
    """The well pages the index links, as absolute addresses in page order (a page twice counts once). The index must still be the Commission's well-file list and hold a sane number of wells."""
    if "Facilities Files" not in page:
        raise RuntimeError("the index has changed: its heading is gone")
    urls = list(dict.fromkeys(HOST + m.group(1) for m in LINK.finditer(page)))
    if not MIN_WELLS <= len(urls) <= MAX_WELLS:
        raise RuntimeError("the index links %d well pages (expected %d to %d): it is cut short or changed" % (len(urls), MIN_WELLS, MAX_WELLS))
    return urls


def file_day(href, today):
    """The day a permit file's name starts with, or None when it starts with no date. A date that is not a day, or one after today, raises: the name's convention changed."""
    name = urllib.parse.unquote(href.split("?")[0].rsplit("/", 1)[-1])
    m = NAME_DATE.match(name)
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(3)), int(m.group(4)))
    except ValueError:
        raise RuntimeError("a permit file's name starts with %s, which is not a day" % name[:10])
    if d > today or d.year < 1990:
        raise RuntimeError("a permit file is dated %s: that cannot be right" % d.isoformat())
    return d


def parse_well(page, today):
    """{county, operator, created, permit: None or (file day, the link says revised)} from one well page. Only the page's own text is read: no PDF is opened, no name or number is kept."""
    m = ENTRY.search(page)
    if not m:
        raise RuntimeError("a well page has changed: its content block is gone")
    body = m.group(1)
    fields = {}
    for p in PARA.findall(body):
        t = plain(p)
        key, colon, value = t.partition(":")
        if colon and key.strip() in ("Well Status", "County", "Operator"):
            fields.setdefault(key.strip(), value.strip())
    if "Well Status" not in fields and "County" not in fields:
        raise RuntimeError("a well page has changed: it states neither a status nor a county")
    links = [(h, plain(t)) for h, t in ANCHOR.findall(body) if "/wp-content/uploads/" in h]
    permits = [(h, t) for h, t in links if re.match(r"permit to drill", t, re.I)]
    if len(permits) > 1:
        raise RuntimeError("a well page links %d permits to drill (expected at most one): its layout changed" % len(permits))
    c = re.search(META % "created", page)
    created = C.parse_day(c.group(1), today) if c else None
    permit = None
    if permits:
        h, t = permits[0]
        permit = (file_day(h, today), bool(re.search(r"revis|amend", t + " " + urllib.parse.unquote(h.rsplit("/", 1)[-1]), re.I)))
    return {"county": fields.get("County") or None, "operator": fields.get("Operator") or None, "created": created, "permit": permit}


def approval_day(fday, revised, created):
    """The day to count a permit on, or None when it falls before the series (whatever its exact day). A file dated 5 days or less after its page was made, and no more than 60 before it, that does not say
    revised is the approval's own date; anything else is a later version and needs its first approval written down in ORIGINAL_APPROVAL, held to the page's creation date."""
    if fday < SERIES_START:
        return None
    if created is None:
        raise RuntimeError("a well page has no creation date: the permit dated %s cannot be checked" % fday.isoformat())
    if not revised and -60 <= (fday - created).days <= 5:
        return fday
    first = ORIGINAL_APPROVAL.get(fday)
    if first is None or not -5 <= (created - first).days <= 60:
        raise RuntimeError("the permit file dated %s is a later version of a permit (or its date does not fit its page, made %s): read the first approval's date from the signed permit and add it to "
                           "ORIGINAL_APPROVAL" % (fday.isoformat(), created.isoformat()))
    return first


def previous(path=None):
    """The committed file's total of new permits, or None when there is none or it is not usable."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        if d["state"] != STATE:
            return None
        return sum(d["bands"]["new"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def operator_name(raw):
    n = " ".join((raw or "").split())
    return OPERATOR_FULL.get(n.upper(), n)


def build(get=C.polite_get, today=None, pause=PAUSE, old_total=None):
    today = today or date.today()
    index = get(INDEX, max_bytes=2_000_000).decode("utf-8", "replace")
    urls = parse_index(index)
    edited = re.search(META % "modified", index)
    permits, dated = [], 0
    for url in urls:
        time.sleep(pause)
        w = parse_well(get(url, max_bytes=1_000_000).decode("utf-8", "replace"), today)
        if w["permit"] is None:
            if w["created"] is None or w["created"] >= IMPORT_END:
                raise RuntimeError("a well page made after the older files were imported has no Permit to Drill link")
            continue
        fday, revised = w["permit"]
        if fday is None:
            if w["created"] is None or w["created"] >= IMPORT_END:
                raise RuntimeError("a new well page links a permit to drill whose file name has no date: it cannot be placed in a month")
            continue
        dated += 1
        day = approval_day(fday, revised, w["created"])
        if day is not None:
            permits.append((day, w["county"], w["operator"]))
    if dated < MIN_DATED:
        raise RuntimeError("only %d of %d well pages give a permit date in the file name (expected %d or more): the naming changed" % (dated, len(urls), MIN_DATED))
    if not permits:
        raise RuntimeError("no permit approved since %s was found" % C.FIRST_MONTH)
    old_total = previous() if old_total is None else old_total
    if old_total is not None and len(permits) < old_total:
        raise RuntimeError("the index lists %d permits since %s but the committed file holds %d: a permit does not go away, so the index is cut short or changed" % (len(permits), C.FIRST_MONTH, old_total))
    t = C.Tally(STATE, bands=("new",), fluid=False)
    for day, county, operator in permits:
        t.add(day, "new", county=county, operator=operator_name(operator))
    newest = max(d for d, _c, _o in permits)
    note = ("Permits to drill, by the day the Commission approved each one: the date at the start of the Permit to Drill file linked from each well's page on its Well and Facilities Files list, "
            "checked against the signed permits and the Commission's quarterly counts. Two permits whose posted file is an amended version are counted at their first approval. Amendments, well "
            "treatments, seismic and injection permits are not available as dated records, and a permit that expired before a well was drilled has no page. Pages are posted within days to "
            "two weeks of approval, so the last 30 days are not shown.")
    doc = t.document(agency="Idaho Department of Lands, Oil and Gas Conservation Commission", source_name="Well and Facilities Files (one page per well, with its Permit to Drill)", source_url=INDEX,
                     basis="approval date", cadence="irregular (a permit is posted within days of its approval)", measure="permits", lag_days=LAG_DAYS, asof=today, note=note)
    last = C.month_end(doc["months"][-1])
    lead = "Idaho approves very few: %d permits to drill from January 2019 to %s%s, so a month with none is a real zero. " % (
        sum(doc["bands"]["new"]), "%s %d" % (last.strftime("%B"), last.year), (", the newest on " + long_day(newest)) if C.month_of(newest) <= doc["through"][:7] else "")
    doc["note"] = lead + doc["note"]
    if edited:
        e = C.parse_day(edited.group(1), today)
        if e:
            doc["note"] += " The list page was last edited %s." % long_day(e)
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # Idaho has gone years with none; the checks above (every page read, dates found on 20 or more) are why two quiet years may be published
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
