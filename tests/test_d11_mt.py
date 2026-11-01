"""Tests for site/pipeline/d11_nat_mt.py: Montana's well permits, from the Board of Oil and Gas Conservation's Dataminer ("Well History", a CSV export of every event on every well).

The fixture is invented but shaped like the real thing: an ASP.NET page that wants its view state back at every step (a postback to choose the date field, which makes the page offer "After", then the
search, then an export that works only in a session that has searched), and an export of 14 columns (API #, Dt_Effect, CoName, Well_Nm, Typ_Work, Wl_Status, Well_Type, County, Field, Wh_Sec, Wh_TR, Wh_Qtr,
Cmmnt and an empty one), one row for every kind of event on a well: permits to drill, re-permits, modifications, notices of intent, completions, spuds, plugging approvals, expiry dates, changes of
bonded operator. A truth is made by the generator (each permit is born with its band), so the counts are compared with what was put in, not with the producer's own rules.

It pins: the steps and their order (the view state of the last reply is sent back; the date postback comes before the search; a producer that skips a step meets the page's own refusal), every layout
failure (a page without the date field, a date filter that does not offer "After", a search the server did not take, an error under the search, an export that is the page's "content must be selected"
or an HTML page, a missing column, short rows), the bands (each permit type in the Board's words, service wells to injection, re-issues and modifications to amendments, re-entries to re-entries; notices
of intent, plugging approvals, expiry dates and every other event are not permits), the month of a permit is the day it was approved, `rework` and `other` are null, the fluid, the counties, the naming
rule (a person and a dba are not named), the lag before the newest month is shown, that no API number, well name, field or comment leaves the export, every guard that refuses a cut-short history (the
24-month window of the Permits page is the one the real source has), an unknown permit type, and the polite client (a refusal is exit 2 and never retried, a 5xx is tried once more, the pauses, no
person in a request). The network is faked: the producer is given a fetch function, and the session class is tried against a fake opener.

Run: python3 -I tests/test_d11_mt.py"""
import collections
import csv
import io
import json
import os
import sys
import tempfile
import urllib.error
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_mt as MT  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
F = MT.FORM


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, *exc):
    try:
        fn()
    except exc or (Exception,) as e:
        return str(e) or e.__class__.__name__
    return None


# ------------------------------------------------------------------------------------------------ an invented well history, with a truth
HEADER = ["API #", "Dt_Effect", "CoName", "Well_Nm", "Typ_Work", "Wl_Status", "Well_Type", "County", "Field", "Wh_Sec", "Wh_TR", "Wh_Qtr", "Cmmnt", ""]
SECRETS = ("25-085-", "Secret Lease", "Wildcat Secret", "Called John Q Landowner", "406-555-0123", "Pat Q Sample", "Sam Jones")


def stamp(d):
    return "%d/%d/%d 12:00:00 AM" % (d.month, d.day, d.year)  # the Board's own shape: no zero padding, a midnight time


class Event:
    def __init__(self, day, work, wtype="Oil", county="Richland", op="Kraken Test LLC", band=None, fluid=None, n=0):
        self.day, self.work, self.wtype, self.county, self.op, self.band, self.fluid, self.n = day, work, wtype, county, op, band, fluid, n

    def row(self):
        return ["25-085-%d-00-00" % (22000 + self.n), stamp(self.day), self.op, "  Secret Lease %d-22H" % self.n, self.work, "Permit to Drill", self.wtype, self.county, "Wildcat Secret",
                "26", "28N-55E", " NW NW", "Called John Q Landowner at 406-555-0123 about the surface use" if self.n % 4 == 0 else "", ""]


def gen_permits():
    """Invented permits, each with the band it truly is in. Months 2019-01 to 2026-10; the newest is a re-permit on 2026-10-30."""
    out, seq = [], [0]

    def add(day, work, wtype="Oil", county="Richland", op="Kraken Test LLC", band="new", fluid="oil"):
        seq[0] += 1
        out.append(Event(day, work, wtype, county, op, band, fluid, seq[0]))

    for i, ym in enumerate(C.month_list("2019-01", "2026-10")):
        y, m = int(ym[:4]), int(ym[5:])

        def d(k, i=i, y=y, m=m):
            return date(y, m, 1 + (k * 5 + i) % 27)

        for k in range(i % 3):
            add(d(k), "Permit to Drill", "Oil", "Powder River", "Example Oil Corporation")
        for k in range(2 + i % 4):
            add(d(k + 3), "Permit to Drill, Horizontal")
        if i % 5 == 0:
            add(d(9), "Permit to Drill, Horizontal", "Oil", "Roosevelt", "Pat Q Sample")  # a person: counted, never named
        if i % 10 == 3:
            add(d(9), "Permit to Drill", "Oil", "Roosevelt", "Sam Jones dba Big Sky Oil")  # a person trading under a name
        if i % 7 == 1:
            add(d(10), "Permit to Drill", "Coal Bed Methane", "Big Horn", "Mesa Gas, LP", fluid="gas")
        if i % 9 == 2:
            add(d(11), "Permit to Drill", "Dry Hole", "Fallon", "Example Oil Corporation", fluid=None)
        if i % 7 == 0:
            add(d(12), "Permit to Drill", "Injection - Disposal", "Fallon", "Disposal Partners LLC", band="inj", fluid=None)
        if i % 11 == 3:
            add(d(13), "Permit to Drill, Horizontal", "Gas Storage", "Fallon", "Storage Company Inc", band="inj", fluid=None)
        if i % 13 == 4:
            add(d(14), "Permit, Re-enter Abandoned Well", "Oil", "Toole", "Example Oil Corporation", band="redrill", fluid=None)
        if i % 17 == 5:
            add(d(15), "Permit, Redrill or Deepen", "Oil", "Toole", "Example Oil Corporation", band="redrill", fluid=None)
        if i % 19 == 6:
            add(d(16), "Permit, Horizontally Re-drill Existing Well", "Oil", "Richland", "Kraken Test LLC", band="redrill", fluid=None)
        if i % 23 == 7:
            add(d(16), "New Horiz. Laterals or Extensions", "Oil", "Richland", "Kraken Test LLC", band="redrill", fluid=None)
        for k in range(1 + i % 3):
            add(d(17 + k), "Re-permit (To Drill or Re-enter)", "Oil", "Richland", "Kraken Test LLC", band="amend", fluid=None)
        if i % 6 == 0:
            add(d(21), "Correction or Modification to Permit", "Oil", "Richland", "Kraken Test LLC", band="amend", fluid=None)
        if i % 8 == 0:
            add(d(22), "Permit Modification", "Oil", "Richland", "Kraken Test LLC", band="amend", fluid=None)
    add(date(2026, 10, 30), "Re-permit (To Drill or Re-enter)", "Oil", "Richland", "Kraken Test LLC", band="amend", fluid=None)
    return out


PERMITS = gen_permits()


def gen_noise(extra_rows=5300):
    """Events that are not permits: plenty of them (a real export has 19,800 rows), several with an approval date (plugging, notices of intent), some dated in the future (expiry)."""
    out, n = [], 100000
    kinds = ["Intent, Recomplete", "Intent, Plugback", "Intent, Convert to Injection", "Subsequent, Recompletion", "Intent, Redrill or Repair", "Intent, Horizontal Lateral Extension",
             "Subsequent, Redrill or Deepen", "Intent, Abandon", "Date Well Plugged and Abandoned", "Orphan Well  Well Plugging", "Expired Permit", "Date Well Spudded", "Date Well Completed",
             "Horizontal Certification", "Sage Grouse Stipulations", "Pre-Frac Filing", "Subsequent, Mechanical Integrity Test", "Intent, Pull or Alter Casing", "Other", "Supplementary Well History"]
    months = C.month_list("2019-01", "2026-10")
    for i in range(extra_rows):
        ym = months[i % len(months)]
        day = date(int(ym[:4]), int(ym[5:]), 1 + (i * 7) % 27)
        n += 1
        out.append(Event(day, "Change of Bonded Operator" if i % 3 else kinds[i % len(kinds)], "Oil", "Richland", "Kraken Test LLC", n=n))
    for k in range(40):
        out.append(Event(date(2027, 1 + k % 12, 5), "Date Well Permit Expires", "Oil", "Richland", "Kraken Test LLC", n=n + k))  # the day a permit would expire: a future date, not a permit
    return out


NOISE = gen_noise()


def export_bytes(permits=None, noise=None, header=None, since=date(2019, 1, 1), bom=False, mutate=None):
    """The export the Dataminer would give: every event dated after `since`, a header, quoted fields and a trailing comma."""
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    head = header or HEADER
    w.writerow(head)
    for e in (PERMITS if permits is None else permits) + (NOISE if noise is None else noise):
        if e.day >= since or e.day.year >= 2027:
            r = e.row()
            w.writerow(mutate(r) if mutate else r)
    return (("﻿" if bom else "") + buf.getvalue()).encode("utf-8")


# ------------------------------------------------------------------------------------------------ the page, as ASP.NET serves it
def page_html(token, types=("Begin", "=", "End"), flt="", error="", date_option=True, export_link=True):
    esc = {"<": "&lt;", ">": ">"}  # the real page escapes "<" and leaves ">" as it is
    opts = ['<option selected="selected" value="API_WellNo|text">API #</option>', '<option value="CoName|text">Operator</option>']
    if date_option:
        opts.append('<option value="Dt_Effect|date">Date Approved</option>')
    typ = "".join('<option value="%s">x</option>' % esc.get(t, t) for t in types)
    return ("<html><body><form method=\"post\" action=\"./WellHistory.aspx\"><div>"
            '<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" /><input type="hidden" name="__EVENTARGUMENT" id="__EVENTARGUMENT" value="" />'
            '<input type="hidden" name="__LASTFOCUS" id="__LASTFOCUS" value="" /><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEPD%s+A/b=" />'
            '<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="8CAD6A21" /><input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="/wEdA%s+Q/z=" />'
            '</div><select name="%scboFilterOption" onchange="javascript:setTimeout(&#39;__doPostBack(\\&#39;x\\&#39;,\\&#39;\\&#39;)&#39;, 0)" class="ComboBox">%s</select>'
            '<select name="%scboFilterType" class="ComboBox">%s</select><input name="%stxtFilter" type="text" value="" />%s'
            '<input name="%stxtFilterString" type="text" value="%s" readonly="readonly" /><span id="x_lblError" class="Error">%s</span>'
            "</form></body></html>") % (token, token, F, "".join(opts), F, typ, F,
                                        '<a href="../Export.aspx?type=csv">Csv (Excel)</a>' if export_link else "", F, flt, error)


class Dataminer:
    """A fake of the Dataminer, with the page's own rules: a POST must carry the view state of the last reply; 'After' is accepted only once the date field has been chosen (the event validation);
    the export is the content selected by the last search, and says so when there is none."""

    def __init__(self, export=None, types1=("<", "=", ">"), **page):
        self.export = export_bytes() if export is None else export
        self.types1, self.page, self.log = types1, page, []
        self.token, self.stage = 0, 0

    def reply(self, **kw):
        self.token += 1
        p = dict(self.page)
        p.update(kw)
        return page_html(self.token, **p).encode()

    def __call__(self, url, fields=None, max_bytes=3_000_000):
        self.log.append((url, None if fields is None else dict(fields)))
        if url == MT.PAGE and fields is None:
            self.stage = 0
            return self.reply(date_option=self.page.get("date_option", True))
        if url == MT.PAGE:
            if ("/wEPD%s+A/b=" % self.token) != fields.get("__VIEWSTATE") or ("/wEdA%s+Q/z=" % self.token) != fields.get("__EVENTVALIDATION"):
                return b"<html>Validation of viewstate MAC failed.</html>"  # a stale view state: the page's own refusal
            if fields.get("__EVENTTARGET") == F + "cboFilterOption":
                self.stage = 1
                return self.reply(types=self.types1)
            if F + "btnSearch" in fields:
                if self.stage != 1 or fields.get(F + "cboFilterType") not in ("<", "=", ">") or fields.get(F + "cboFilterOption") != "Dt_Effect|date":
                    return b"<html>Invalid postback or callback argument.</html>"
                self.stage = 2
                if "flt" in self.page:
                    return self.reply()
                return self.reply(types=("<", "=", ">"), flt="Date Approved &gt; &#39;%s&#39; " % fields[F + "txtFilter"])
            return b"<html>unknown postback</html>"
        if url == MT.EXPORT:
            return self.export if self.stage == 2 else b"Content must be selected to export data"
        raise AssertionError("an address the Dataminer does not have: " + url)


def build(fetch=None, today=TODAY, **kw):
    fetch = fetch or Dataminer()
    return MT.build(fetch=fetch, today=today, **kw)


def truth_counts(permits=None):
    t = collections.Counter()
    for e in (PERMITS if permits is None else permits):
        t[(C.month_of(e.day), e.band)] += 1
    return t


# ------------------------------------------------------------------------------------------------ the helpers
html = page_html(7, types=("<", "=", ">"))
hf = MT.hidden_fields(html)
check(hf["__VIEWSTATE"] == "/wEPD7+A/b=" and hf["__EVENTVALIDATION"] == "/wEdA7+Q/z=" and hf["__EVENTTARGET"] == "" and "ctl00$SiteContentPlaceHolder$FormFilterNoNav1$txtFilterString" not in hf,
      "the hidden fields of the page are read (the view state and the event validation), not the text boxes")
check(MT.select_values(html, F + "cboFilterType") == ["<", "=", ">"] and "Dt_Effect|date" in MT.select_values(html, F + "cboFilterOption") and MT.select_values(html, F + "nothing") is None,
      "a select's option values are read, entity-decoded (&lt; is <), and a select that is not there is None")
check(MT.attr('<input type="hidden" name="a&amp;b" value="x&#39;y">', "name") == "a&b" and MT.attr("<input>", "name") is None, "an attribute is read and decoded")

# ------------------------------------------------------------------------------------------------ the bands, in the Board's own words
bf = MT.band_of_event
check(bf("Permit to Drill", "Oil") == "new" and bf("Permit to Drill, Horizontal", "Oil") == "new" and bf("Permit to Drill", "Coal Bed Methane") == "new" and bf("Permit to Drill", "Dry Hole") == "new",
      "a permit to drill (vertical or horizontal) is a new well, whatever the well came in as, a dry hole too")
check(all(bf(w, t) == "inj" for w in ("Permit to Drill", "Permit to Drill, Horizontal") for t in ("Injection - Disposal", "Injection, EOR", "Injection, Indian Lands", "Gas Storage", "Monitor/Observation", "Water Source", "Domestic Water")),
      "a permit to drill for a disposal, injection, storage, monitor or water well is injection and disposal")
check(all(bf(w, "Oil") == "redrill" for w in ("Permit, Re-enter Abandoned Well", "Permit, Redrill or Deepen", "Permit, Horizontally Re-drill Existing Well", "New Horiz. Laterals or Extensions")) and bf("Permit, Re-enter Abandoned Well", "Injection - Disposal") == "redrill",
      "a re-entry, a re-drill, a deepening or a new lateral is a re-entry (even of a disposal well)")
check(all(bf(w, "Oil") == "amend" for w in ("Re-permit (To Drill or Re-enter)", "Permit Modification", "Correction or Modification to Permit")) and bf("  RE-PERMIT   (To Drill or Re-enter) ", "Oil") == "amend" and bf("Re-permit (To Drill or Re-enter)", "Injection - Disposal") == "amend",
      "a re-issued permit and a modification are amendments (a re-issue is the same well approved again, never a new well), whatever the spelling or well")
check(all(bf(w, "Oil") is None for w in ("Intent, Recomplete", "Intent, Plugback", "Intent, Abandon", "Date Well Plugged and Abandoned", "Orphan Well  Well Plugging", "Expired Permit", "Date Well Permit Expires",
                                         "Date Well Spudded", "Date Well Completed", "Change of Bonded Operator", "Subsequent, Redrill or Deepen", "Intent, Horizontal Lateral Extension", "Pre-Frac Filing", "Horizontal Certification", "", None)),
      "notices of intent, plugging and abandonment approvals, expiry, spud, completion, operator changes and the rest are not permits")
check(MT.is_unknown_permit("Permit, Sidetrack Existing Well") and MT.is_unknown_permit("Permit to Drill, Offshore") and MT.is_unknown_permit("APD Extension")
      and not MT.is_unknown_permit("Expired Permit") and not MT.is_unknown_permit("Date Well Permit Expires") and not MT.is_unknown_permit("Intent, Recomplete") and not MT.is_unknown_permit("Permit to Drill")
      and not MT.is_unknown_permit("Re-permit (To Drill or Re-enter)"), "a type of work that names a permit and is none this counts is unknown; expiry and known types and sundries are not")

# ------------------------------------------------------------------------------------------------ the export
ev, st = MT.parse_export(export_bytes(), TODAY)
check(len(ev) == len(PERMITS) and st["rows"] == len(PERMITS) + len(NOISE) and st["undated"] == 0 and st["short"] == 0,
      "every permit of the export is an event and nothing else is (%d permits among %d rows; the expiry dates of 2027 and the other kinds are skipped)" % (len(ev), st["rows"]))
check(all(set(e) == {"day", "band", "county", "operator", "fluid"} for e in ev), "an event leaves the export as five fields: the day, the band, the county, the operator and the fluid")
check(MT.parse_export(export_bytes(bom=True), TODAY)[0] == ev, "a byte-order mark at the start of the file is no problem")
check(len(MT.parse_export(export_bytes(permits=PERMITS[:20], noise=[]), TODAY)[0]) == 20, "a small export is read")
dated = MT.parse_export(export_bytes(permits=PERMITS[:10], noise=[], mutate=lambda r: r[:1] + ["13/45/2025 12:00:00 AM"] + r[2:] if r[0] == "25-085-22001-00-00" else r), TODAY)
check(dated[1]["undated"] == 1 and len(dated[0]) == 9, "a permit with a date that is not a date is counted as undated, never given a day")
check(MT.parse_export(export_bytes(permits=PERMITS[:10], noise=[], mutate=lambda r: r[:1] + ["12/31/2018 12:00:00 AM"] + r[2:]), TODAY)[1]["undated"] == 10, "a permit dated before 2019 is not in the series (counted aside)")
check("column" in (raises(lambda: MT.parse_export(export_bytes(header=[h for h in HEADER if h != "County"]), TODAY), RuntimeError) or ""), "a missing column fails the export: its layout may have changed")
check("column" in (raises(lambda: MT.parse_export(export_bytes(header=[("Typ_Work2" if h == "Typ_Work" else h) for h in HEADER]), TODAY), RuntimeError) or ""), "a renamed work-type column fails")
check("selected" in (raises(lambda: MT.parse_export(b"Content must be selected to export data", TODAY), RuntimeError) or ""), "the page's 'content must be selected' is not a CSV")
check("not the CSV" in (raises(lambda: MT.parse_export(b"<html><body>Server Error</body></html>", TODAY), RuntimeError) or ""), "an HTML page is not a CSV")
check(raises(lambda: MT.parse_export(b"", TODAY), RuntimeError) is not None, "an empty export fails")
check("shorter" in (raises(lambda: MT.parse_export(export_bytes(mutate=lambda r: r[:5]), TODAY), RuntimeError) or ""), "rows shorter than the header (a re-laid-out file) fail the export")
check("does not know" in (raises(lambda: MT.parse_export(export_bytes(permits=PERMITS + [Event(date(2026, 5, 5), "Permit, Sidetrack Existing Well", n=1)]), TODAY), RuntimeError) or ""), "a kind of permit this does not know fails the run: a silent drop would read as a fall")
check(len(MT.parse_export(export_bytes(permits=PERMITS + [Event(date(2026, 5, 5), "Permit to Drill, Horizontal", band="new", n=1)]), TODAY)[0]) == len(PERMITS) + 1, "...but a known one is counted")

# ------------------------------------------------------------------------------------------------ the steps of the form
dm = Dataminer()
data = MT.read_export(dm)
check(data == export_bytes() and [u for u, f in dm.log] == [MT.PAGE, MT.PAGE, MT.PAGE, MT.EXPORT], "four requests: the page, the choice of the date field, the search, the export")
f1, f2 = dm.log[1][1], dm.log[2][1]
check(dm.log[0][1] is None and dm.log[3][1] is None and f1["__EVENTTARGET"] == F + "cboFilterOption" and f1[F + "cboFilterOption"] == "Dt_Effect|date",
      "the page and the export are GETs; the second request is the postback the page's own date select makes")
check(f2[F + "btnSearch"] == "Search" and f2[F + "cboFilterType"] == ">" and f2[F + "txtFilter"] == "12/31/2018" and f2.get("__EVENTTARGET", "") == "", "the search is 'Date Approved After 12/31/2018', pressed with the Search button")
check(f1["__VIEWSTATE"] != f2["__VIEWSTATE"] and all(f2[k] for k in ("__VIEWSTATE", "__EVENTVALIDATION")), "each step sends back the view state of the reply before it")
check(not any("Cmmnt" in str(f) or "Secret" in str(f) for u, f in dm.log), "nothing from the data is sent anywhere")


def stale_view(url, fields=None, max_bytes=3_000_000):
    """A client that sends back the view state of the FIRST page for every post (it never uses the newest reply): the page refuses it."""
    if fields is not None:
        fields = dict(fields, __VIEWSTATE="/wEPD1+A/b=", __EVENTVALIDATION="/wEdA1+Q/z=")
    return dm2(url, fields, max_bytes)


dm2 = Dataminer()
check(raises(lambda: MT.read_export(stale_view), RuntimeError) is not None, "a view state that is not the last reply's is refused by the page, and is a failure here, never a short file")
check("layout" in (raises(lambda: MT.read_export(Dataminer(date_option=False)), RuntimeError) or ""), "a page with no 'Date Approved' field fails: its layout may have changed")
check("layout" in (raises(lambda: MT.read_export(Dataminer(export_link=False)), RuntimeError) or ""), "a page with no export link fails")
check("After" in (raises(lambda: MT.read_export(Dataminer(types1=("<", "="))), RuntimeError) or ""), "a date filter that no longer offers 'After' fails")
check("did not take" in (raises(lambda: MT.read_export(Dataminer(flt="")), RuntimeError) or ""), "a search the server did not take (its filter reads nothing) fails")
check("did not take" in (raises(lambda: MT.read_export(Dataminer(flt="Date Approved &gt; &#39;01/01/2024&#39; ")), RuntimeError) or ""), "a search with another date fails: this is not the whole history")
check("error" in (raises(lambda: MT.read_export(Dataminer(flt="Date Approved &gt; &#39;12/31/2018&#39; ", error="Invalid date")), RuntimeError) or ""), "an error under the search fails")


def stale_state(url, fields=None, max_bytes=3_000_000):
    """The first page is fetched again before the export (a lost session): the export has nothing selected."""
    if url == MT.EXPORT:
        dm3.stage = 0
    return dm3(url, fields, max_bytes)


dm3 = Dataminer()
check("selected" in (raises(lambda: MT.parse_export(MT.read_export(stale_state), TODAY), RuntimeError) or ""), "an export from a session that has no search is caught as not the CSV")

# ------------------------------------------------------------------------------------------------ the document
doc = build()
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "MT" and doc["name"] == "Montana" and doc["measure"] == "permits" and "approv" in doc["basis"] and doc["source"]["url"] == MT.PAGE, "Montana, counted by the day each permit was approved")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-30" and len(doc["months"]) == 93,
      "from January 2019 to the last complete month (October's newest permit is on the 30th: a week has not passed): %s to %s, asOf %s" % (doc["months"][0], doc["months"][-1], doc["asOf"]))
truth = truth_counts()
ok = all(doc["bands"][b][i] == truth[(ym, b)] for b in ("new", "inj", "redrill", "amend") for i, ym in enumerate(doc["months"]))
check(ok, "every band of every month is exactly what the invented Board approved (counted by the day of approval, not by anything else)")
check(doc["bands"]["rework"] is None and doc["bands"]["other"] is None, "rework and other are not available: null, never zero (workovers are sundry notices, not permits)")
check(all(isinstance(doc["bands"][b], list) and sum(doc["bands"][b]) > 0 for b in ("new", "inj", "redrill", "amend")), "the four bands the source tells are all counted")
check(0 in doc["bands"]["redrill"] and max(doc["bands"]["redrill"]) > 0, "a month with no re-entry is a real zero inside the series, not a gap")
check(doc["read"] == len(PERMITS), "read counts every permit event it took, the newest month included (%d)" % doc["read"])
last12 = doc["months"][-12:]
want = collections.Counter(e.fluid or "unknown" for e in PERMITS if e.band == "new" and C.month_of(e.day) in last12)
check(doc["fluid"] == {f: want.get(f, 0) for f in C.FLUIDS} and doc["fluid"]["gas"] > 0 and doc["fluid"]["unknown"] > 0 and doc["fluid"]["oil"] > doc["fluid"]["gas"], "the fluid of the last year's new wells comes from the well's type (dry holes are unknown): %s" % doc["fluid"])
wc = collections.Counter(C.place_title(e.county.upper()) for e in PERMITS if e.band == "new" and C.month_of(e.day) in last12)
check({c[0]: c[1] for c in doc["counties"]} == dict(wc) and doc["counties"][0][0] == "Richland" and [c[1] for c in doc["counties"]] == sorted((c[1] for c in doc["counties"]), reverse=True),
      "the counties are the last 12 months' new wells, ranked: %s" % doc["counties"])
names = [o[0] for o in doc["operators"]]
check("KRAKEN TEST LLC" in names and "EXAMPLE OIL CORPORATION" in names and "MESA GAS LP" in names and not any("PAT Q" in n or "SAM JONES" in n or "BIG SKY" in n for n in names), "operators: the LLC, the corporation and the partnership; not the person, not the dba: %s" % names)
tot = sum(o[1] for o in doc["operators"])
tw = sum(1 for e in PERMITS if e.band == "new" and C.month_of(e.day) in last12)
check(0 < doc["namedShare"] < 1 and abs(doc["namedShare"] - round(tot / tw, 3)) < 0.002, "the named share counts the person's and the dba's new wells as unnamed: %s" % doc["namedShare"])
text = json.dumps(doc)
check(not any(x in text for x in SECRETS), "no API number, well name, field, comment, phone or person is anywhere in the file")
check(build() == doc, "the same export gives the same document, byte for byte")
check("rework" not in doc["note"].lower() or "not available" in doc["note"], "the note says what is not available")

# the lag: a permit on the 3rd of November does not yet make October complete; one on the 9th does
late = PERMITS + [Event(date(2026, 11, 3), "Permit to Drill, Horizontal", band="new", n=7777)]
check(build(Dataminer(export_bytes(permits=late)), today=date(2026, 11, 20))["through"] == "2026-09-30", "a newest permit on November 3 leaves October as the newest month not yet shown (a week's lag)")
late = PERMITS + [Event(date(2026, 11, 9), "Permit to Drill, Horizontal", band="new", n=7777)]
d2 = build(Dataminer(export_bytes(permits=late)), today=date(2026, 11, 20))
check(d2["through"] == "2026-10-31" and d2["months"][-1] == "2026-10" and d2["bands"]["new"][-1] == truth_counts(late)[("2026-10", "new")], "one on November 9 makes October complete, with its own count")

# ------------------------------------------------------------------------------------------------ rules that a mutant would break (each is compared with the invented truth above)
noisy = [Event(date(2024, 3, 4), w, "Oil", "Richland", "Kraken Test LLC", n=900 + i) for i, w in enumerate(("Intent, Recomplete", "Intent, Abandon", "Date Well Plugged and Abandoned", "Orphan Well  Well Plugging", "Expired Permit", "Date Well Spudded"))]
dn = build(Dataminer(export_bytes(permits=PERMITS, noise=NOISE + noisy)))
check(dn == doc, "plugging approvals, notices of intent, expiry and spud events dated in a month do not change a single count (abandoned wells print an approval too, and are not permits)")
check(sum(doc["bands"]["amend"]) == sum(1 for e in PERMITS if e.band == "amend" and C.month_of(e.day) <= "2026-09") and sum(doc["bands"]["new"]) == sum(1 for e in PERMITS if e.band == "new" and C.month_of(e.day) <= "2026-09"),
      "a re-issued permit is an amendment, never a second new well (new + amend are counted apart)")
spud = [Event(date(2024, 3, 4), "Date Well Spudded", "Oil", "Richland", "Kraken Test LLC", n=1)]
check(build(Dataminer(export_bytes(permits=PERMITS + spud)))["bands"] == doc["bands"], "a spud event is not a permit: the month is the day of approval and nothing else")

# ------------------------------------------------------------------------------------------------ the guards
check("events" in (raises(lambda: build(Dataminer(export_bytes(noise=[]))), RuntimeError) or ""), "an export with a few hundred events (a search cut short) fails: too few rows")
saved = MT.MIN_PERMITS
MT.MIN_PERMITS = 100000
check("permit events" in (raises(lambda: build(), RuntimeError) or ""), "too few permits in all fail the run")
MT.MIN_PERMITS = saved
check("stale" in (raises(lambda: build(today=date(2027, 3, 1)), RuntimeError) or ""), "a newest permit more than 90 days old fails: the history looks stale")
check(raises(lambda: build(today=date(2027, 1, 20)), RuntimeError) is None, "one 82 days old is fine")
window = [e for e in PERMITS if e.day >= date(2024, 11, 1)]
check("2019" in (raises(lambda: build(Dataminer(export_bytes(permits=window, noise=NOISE))), RuntimeError) or ""), "an export of the last 24 months only (the Permits page's window, the real source's trap) fails: the history must reach back to 2019")
no21 = [e for e in PERMITS if e.day.year != 2021 or e.band not in ("new", "inj")]
check("2021" in (raises(lambda: build(Dataminer(export_bytes(permits=no21))), RuntimeError) or ""), "a whole year with no permit to drill fails: the history lost a year")
no_amend = [e for e in PERMITS if not (e.band == "amend" and e.day >= date(2024, 10, 1))]
check("amend" in (raises(lambda: build(Dataminer(export_bytes(permits=no_amend))), RuntimeError) or ""), "no re-issued permit or modification in two years fails: a type of work was renamed")
bad = [Event(date(2026, 5, 5), "Permit to Drill", n=50000 + k) for k in range(4)]
check("usable date" in (raises(lambda: build(Dataminer(export_bytes(permits=PERMITS + bad, mutate=lambda r: r[:1] + ["13/45/2026 12:00:00 AM"] + r[2:] if r[0] in [b.row()[0] for b in bad] else r))), RuntimeError) or ""), "four permits with no usable date fail the run")
three = bad[:3]
check(raises(lambda: build(Dataminer(export_bytes(permits=PERMITS + three, mutate=lambda r: r[:1] + ["13/45/2026 12:00:00 AM"] + r[2:] if r[0] in [b.row()[0] for b in three] else r))), RuntimeError) is None, "three are tolerated (and left out)")
check("does not know" in (raises(lambda: build(Dataminer(export_bytes(permits=PERMITS + [Event(date(2026, 5, 5), "Permit, Frobnicate", n=5)]))), RuntimeError) or ""), "an unknown kind of permit fails the whole run")

# ------------------------------------------------------------------------------------------------ the polite client
class Resp:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, script):
        self.script, self.requests = list(script), []

    def open(self, req, timeout=None):
        self.requests.append(req)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return Resp(item)


def http_error(code):
    return urllib.error.HTTPError(MT.PAGE, code, "x", {}, None)


slept = []
real_sleep = MT.time.sleep
MT.time.sleep = lambda s: slept.append(s)
try:
    d = MT.Dataminer(pause=3.0)
    d.opener = Opener([b"page", b"posted", b"csv"])
    a, b, c = d(MT.PAGE), d(MT.PAGE, fields={"a": "1"}), d(MT.EXPORT, max_bytes=100)
    r = d.opener.requests
    check((a, b, c) == (b"page", b"posted", b"csv") and r[0].get_method() == "GET" and r[1].get_method() == "POST" and r[1].data == b"a=1" and r[1].get_header("Content-type") == "application/x-www-form-urlencoded" and r[0].get_header("Content-type") is None,
          "a page is a GET, a form is a POST with its fields")
    check(slept == [3.0, 3.0] and r[0].get_header("Referer") is None and r[1].get_header("Referer") == MT.PAGE, "each request waits three seconds after the last; the later ones say which page they come from")
    ua = r[0].get_header("User-agent")
    check(ua == C.UA and "@" not in ua and "joe" not in ua.lower() and "fleetstream" not in ua.lower(), "the request identifies no person: %s" % ua)
    slept.clear()
    d = MT.Dataminer(pause=3.0)
    d.opener = Opener([http_error(403), b"never read"])
    check(raises(lambda: d(MT.PAGE), C.Refused) is not None and len(d.opener.requests) == 1, "a 403 is a refusal at once and is never asked again")
    for code in (401, 407, 429):
        d = MT.Dataminer(pause=3.0)
        d.opener = Opener([http_error(code), b"x"])
        check(raises(lambda: d(MT.PAGE), C.Refused) is not None and len(d.opener.requests) == 1, "HTTP %d is a refusal too" % code)
    slept.clear()
    d = MT.Dataminer(pause=3.0)
    d.opener = Opener([http_error(500), b"fine"])
    check(d(MT.PAGE) == b"fine" and len(d.opener.requests) == 2 and slept == [3.0], "a 500 is tried once more, after a pause")
    d = MT.Dataminer(pause=3.0)
    d.opener = Opener([OSError("connection reset"), urllib.error.URLError("dropped"), b"never"])
    check("could not read" in (raises(lambda: d(MT.PAGE), RuntimeError) or "") and len(d.opener.requests) == 2, "a connection dropped twice fails the request (two tries, no loop)")
    d = MT.Dataminer(pause=3.0)
    d.opener = Opener([b"x" * 500])
    check("larger" in (raises(lambda: d(MT.PAGE, max_bytes=100), ValueError) or "") and len(d.opener.requests) == 1, "a reply past the size cap fails at once (the cap protects the runner)")
finally:
    MT.time.sleep = real_sleep

src = open(os.path.join(REPO, "site", "pipeline", "d11_nat_mt.py"), encoding="utf-8").read()
code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
check("CERT_NONE" not in code and "_create_unverified_context" not in code and "check_hostname" not in code and "ProxyHandler" not in code and "environ" not in code.replace("os.environ.get", ""),
      "TLS verification is never switched off and the proxy variables are not touched")
check("@" not in "".join(l for l in code.splitlines() if "headers" in l) and "joe" not in code.lower(), "no e-mail address or person in the producer's requests")

# ------------------------------------------------------------------------------------------------ the run
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "MT.json")
    open(old, "w").write("committed\n")

    def refuse(*a, **k):
        raise C.Refused("HTTP 403 from the server")

    check(C.run_producer("MT", lambda: MT.build(fetch=refuse, today=TODAY), tmp, argv=[]) == 2 and open(old).read() == "committed\n", "a refusing server ends the run with exit 2 and leaves the committed file alone")
    check(C.run_producer("MT", lambda: build(Dataminer(export_bytes(noise=[]))), tmp, argv=[]) == 1 and open(old).read() == "committed\n", "a failed run exits 1 and leaves the committed file alone")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("MT", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "MT.json")), "run_producer writes nat/MT.json for it")
    check(C.check_dir(tmp) == [] and C.run_producer("MT", lambda: doc, tmp, argv=["--check"]) == 0, "the written file reloads and validates")
    p = os.path.join(tmp, "MT.json")
    first = open(p, "rb").read()
    C.run_producer("MT", lambda: build(), tmp, argv=[])
    check(open(p, "rb").read() == first, "a second run from the same export leaves the file byte for byte the same")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
