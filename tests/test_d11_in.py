"""Tests for site/pipeline/d11_nat_in.py: Indiana's well permits, from the Division of Reclamation's weekly "Permits Issued" PDFs.

The fixture is invented, written the way `pdftotext -layout` gives a weekly list: a header, then for each permit a line with the operator (its name, then its address, city, state, zip and phone in
columns), "was issued a(n) <well type> permit on <date> . The # <n> <lease> permit no.", a line with the permit number and "is located in <County> County, Section.. ", a line with
"This <direction> <application type> well, located in the <pool>", and the formation and depth. The index page is a table for each year (months, then the Friday of each week, linked to a PDF).
It pins: the index (every shape of link, a week linked twice, a blank cell, a week not yet published, a link off the site), the band of each application type the Division uses and of each well
type (a waterflood well is `inj`, a blank application type is never `new`), the fluid, that only the operator's name, the county, the dates and the types leave a list (no address, phone, lease or
permit number), the privacy rule on a person-named operator, a list that says there were none, the count of every permit by the day it was issued against a truth made by the same generator, the
lag-free `through`, the series starting where the lists start, an incremental read (the committed months stand and only the last 14 months are read again, giving the same document), and that
anything damaged (an index that lost its table or its newest weeks, a list that cannot be fetched or read, one whose paragraphs do not parse, a refusal) fails the run instead of writing a short file.
The network and pdftotext are faked.

Run: python3 -I tests/test_d11_in.py"""
import calendar
import collections
import json
import os
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_in as IN  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


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


# ------------------------------------------------------------------------------------------------ the weekly list, as pdftotext -layout gives it
def paragraph(operator, kind, day, county, app, direction="Vertical", n=7, band=None, fluid=None):
    d = "%d/%d/%d" % (day.month, day.day, day.year)
    return "\n".join([
        "%-46s%-38s%-26s%-5s%-15s%s" % (operator, "100 Example Road", "Springfield", "IN", "46000-", "(555) 555-0100"),
        "was issued a(n)      %-25s permit on      %s . The # %d            Sample Lease                            permit no." % (kind, d, n),
        "  99001 is located in %-20s County,         Section 17    T5     S ,     R 14 W            0S         366 W            NE    NE" % county,
        ",surface elevation         362 feet. This %-12s %-22s well, located in the Sample Consolidated" % (direction, app),
        "pool is permitted to the      Fort Payne             at an estimated depth of   4200      feet.", "", ""])


def week_text(friday, permits):
    mon = friday - timedelta(days=4)
    head = ("        State Of Indiana\n        Department of Natural Resources\n%sPermits Issued\n        Division Of Oil and Gas%sFrom        %d/%d/%d To     %d/%d/%d\n\n\n"
            % (" " * 107, " " * 72, mon.month, mon.day, mon.year, friday.month, friday.day, friday.year))
    if not permits:
        return "Indiana Department of Natural Resources, Division of Oil and Gas\n\n\n\nThere were no permits issued for this reporting period.\n"
    return head + "\n".join(paragraph(**p) for p in permits)


def fridays(first=date(2020, 1, 3), last=date(2026, 10, 23)):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=7)


def week_permits(k, friday):
    """What the fake Division issues in week k: the permits as dicts for `paragraph`, with the band each is truly in."""
    P = []
    if k % 10 == 3 or date(2022, 2, 4) <= friday <= date(2022, 3, 4):
        return P  # a quiet week (and all of February 2022): the list says there were none
    P.append(dict(operator="Example Oil Corporation", kind="Oil", day=friday - timedelta(days=2), county="Posey", app="New", band="new", fluid="oil"))
    if k % 4 == 0:
        P.append(dict(operator="Pat Q Sample", kind="Oil", day=friday - timedelta(days=3), county="Gibson", app="New", band="new", fluid="oil"))
    if k % 5 == 0:
        P.append(dict(operator="Sample Energy, LLC", kind="Enhanced Recovery", day=friday - timedelta(days=1), county="Gibson", app="New", band="inj", fluid=None))
    if k % 7 == 0:
        P.append(dict(operator="Example Oil Corporation", kind="Oil", day=friday - timedelta(days=4), county="Posey", app="Deepening", band="redrill", fluid=None))
    if k % 9 == 0:
        P.append(dict(operator="Example Oil Corporation", kind="Oil", day=friday, county="Posey", app="Conversion", band="rework", fluid=None))
    if k % 6 == 0:
        P.append(dict(operator="Sample Energy, LLC", kind="Enhanced Recovery", day=friday, county="Gibson", app="Modification", band="amend", fluid=None))
    if k % 11 == 0:
        P.append(dict(operator="Mesa Partners, LP", kind="Gas", day=friday - timedelta(days=2), county="Sullivan", app="New", band="new", fluid="gas"))
    if k % 13 == 0:
        P.append(dict(operator="Example Oil Corporation", kind="Oil", day=friday - timedelta(days=1), county="Posey", app="", band="other", fluid=None))
    return P


def index_html(weeks, link=None, extra_year_rows=""):
    """The weekly-list page: a table for each year (newest first), a row of months (five columns each) and a row of weeks. `weeks` are (friday, url) pairs; a blank cell pads a short month."""
    link = link or (lambda d, u: u)
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for d, u in weeks:
        by[d.year][d.month].append((d, u))
    out = ["<html><body><h1>Weekly Permits Listing</h1>"]
    for y in sorted(by, reverse=True):
        out.append('<table id="dnrtable"><tbody><tr><th colspan="15"><div align="left">%d Week Ending</div></th></tr>' % y)
        months = sorted(by[y])
        for g in range(0, len(months), 3):
            grp = months[g:g + 3]
            out.append('<tr align="center">' + "".join('<td colspan="5" headers="x" scope="col">%s</td>' % calendar.month_name[m] for m in grp) + "</tr>")
            cells = []
            for m in grp:
                row = ['<td headers="x"><a href="%s">%d</a></td>' % (link(d, u), d.day) for d, u in by[y][m]]
                cells += row + ['<td headers="x">&nbsp;</td>'] * (5 - len(row))
            out.append('<tr align="center">' + "".join(cells) + "</tr>")
        out.append("</tbody></table>")
    return "".join(out) + extra_year_rows + "</body></html>"


ALL = list(fridays())
URL = {d: "/dA/%08x/og-week%02d%02d.pdf?language_id=1" % (i, d.year % 100, i % 53 + 1) for i, d in enumerate(ALL)}
TRUTH = {d: week_permits(i, d) for i, d in enumerate(ALL)}
TEXT = {IN.HOST + URL[d]: week_text(d, TRUTH[d]) for d in ALL}
INDEX_HTML = index_html([(d, URL[d]) for d in ALL])


class Net:
    def __init__(self, index=INDEX_HTML, texts=TEXT, fail=None):
        self.index, self.texts, self.fail, self.urls = index, texts, fail, []

    def get(self, url, **k):
        self.urls.append(url)
        if url == IN.INDEX:
            return self.index.encode()
        if self.fail and self.fail(url):
            raise RuntimeError("could not read the source: HTTP 500")
        return self.texts[url].encode()


def build(net=None, today=TODAY, old=None, **kw):
    net = net or Net()
    saved = IN.MIN_WEEKS, IN.MIN_PERMITS
    IN.MIN_WEEKS, IN.MIN_PERMITS = kw.pop("min_weeks", 250), kw.pop("min_permits", 400)
    try:
        return IN.build(get=net.get, to_text=lambda b: b.decode(), pause=0, today=today, old={} if old is None else old, **kw)
    finally:
        IN.MIN_WEEKS, IN.MIN_PERMITS = saved


# ------------------------------------------------------------------------------------------------ the index
idx, rep = IN.parse_index(INDEX_HTML)
check(len(idx) == len(ALL) and [d for d, u in idx] == ALL, "every week on the index is found, oldest first (%d weeks, %s to %s)" % (len(idx), idx[0][0], idx[-1][0]))
check(all(u.startswith("https://www.in.gov/dA/") and u.endswith("?language_id=1") for d, u in idx), "a root-relative link becomes an address on www.in.gov, query kept")
shapes = [("/dA/x1/og-week2510.pdf?language_id=1", "https://www.in.gov/dA/x1/og-week2510.pdf?language_id=1"), ("/dnr/oil-and-gas/files/og-2601.pdf", "https://www.in.gov/dnr/oil-and-gas/files/og-2601.pdf"),
          ("/dnr/files/og-week2614.pdf", "https://www.in.gov/dnr/files/og-week2614.pdf"), ("https://www.in.gov/dnr/oil-and-gas/files/og-week-2605.pdf", "https://www.in.gov/dnr/oil-and-gas/files/og-week-2605.pdf"),
          ("/dA/x2/or-week2310.pdf?language_id=1", "https://www.in.gov/dA/x2/or-week2310.pdf?language_id=1"), ("/dnr/oil-and-gas/files/og-week2602.PDF", "https://www.in.gov/dnr/oil-and-gas/files/og-week2602.PDF")]
html = index_html([(date(2026, 1, 2) + timedelta(days=7 * i), s[0]) for i, s in enumerate(shapes)])
check([u for d, u in IN.parse_index(html)[0]] == [s[1] for s in shapes], "every shape of link the real page has is read: the table, not the file name, says which week a file is")
html = index_html([(date(2026, 1, 2), "/dnr/oil-and-gas/files/a.pdf"), (date(2026, 1, 9), "https://example.com/og-week2602.pdf"), (date(2026, 1, 16), "/dnr/oil-and-gas/files/notes.html"),
                   (date(2026, 1, 23), "https://www.in.gov.evil.example/og.pdf"), (date(2026, 1, 30), "/dnr/oil-and-gas/files/a.pdf")])
check([d for d, u in IN.parse_index(html)[0]] == [date(2026, 1, 2)] and IN.parse_index(html)[1] == [date(2026, 1, 30)], "a link to another site, to a page that is not a PDF, or to a look-alike host is ignored; a file linked for two weeks is one file, not counted twice, and the second week is reported as repeated")
html = index_html([(date(2026, 1, 2), "/a/og-week2601.pdf")]).replace("</tbody>", '<tr><td headers="x">9</td><td headers="x">16</td><td headers="x">&nbsp;</td></tr></tbody>')
check([d for d, u in IN.parse_index(html)[0]] == [date(2026, 1, 2)], "a week with no link yet (a plain day) or a blank cell is not a list")
check(IN.parse_index("<html>nothing here</html>") == ([], []) and IN.parse_index(INDEX_HTML.replace("Week Ending", "Weeks")) == ([], []), "a page with no tables, or tables that lost their year heading, gives no weeks")
check([d for d, u in IN.parse_index(index_html([(date(2026, 2, 27), "/a/og-week2609.pdf")]).replace(">27<", ">31<"))[0]] == [date(2026, 2, 28)], "a day that does not exist in its month (a typo on the page) is the month's last day, not an error")

# ------------------------------------------------------------------------------------------------ the bands, from the Division's own words
bf = IN.band_of_permit
check(bf("New", "Oil") == ("new", "oil") and bf("New", "Gas") == ("new", "gas") and bf("New", "Coal Bed Methane") == ("new", "gas") and bf("New", "Non-Commercial Gas") == ("new", "gas"),
      "a new oil well is new with fluid oil; gas, coal bed methane and non-commercial gas wells are new with fluid gas")
check(bf("New", "Oil and Gas")[1] == "both" and bf("New", "Oil")[0] == "new", "an oil and gas well is both")
check(bf("New", "Enhanced Recovery") == ("inj", None) and bf("New", "Class II")[0] == "inj" and bf("New", "Saltwater Disposal")[0] == "inj" and bf("New", "Gas Storage")[0] == "inj",
      "a new enhanced recovery (waterflood), Class II, disposal or storage well is injection and disposal, with no fluid")
check(bf("Deepening", "Oil")[0] == "redrill" and bf("Re-entry", "Oil")[0] == "redrill", "a deepening or a re-entry is a re-entry and sidetrack")
check(bf("Conversion", "Oil")[0] == "rework" and bf("Conversion", "Enhanced Recovery")[0] == "rework" and bf("Workover", "Oil")[0] == "rework" and bf("Plug Back", "Oil")[0] == "rework", "a conversion, workover or plug-back is a rework, whatever the well type")
check(all(bf(a, "Oil")[0] == "amend" for a in ("Modification", "Renewal", "Change of Operator", "Transfer", "Extension")) and bf("Modification", "Enhanced Recovery")[0] == "amend", "a modification, renewal, change of operator, transfer or extension is an amendment")
check(bf("", "Oil") == ("other", None) and bf("  ", "Gas")[0] == "other", "a blank application type on an oil or gas well is other: never taken for a new well")
check(bf("", "Enhanced Recovery") == ("inj", None), "a blank application type on a service well is injection")
check(bf("Frobnicate", "Oil")[0] == "other", "an application type the file does not know is other")
check(all(bf("New", k) == ("other", None) for k in ("Geologic/ Structure Test", "Geologic/ Structure T", "County Test", "Individual Test", "Investigatory Carbon Dioxide")), "a test well (structure, county, individual, investigatory) is other: drilled for information, not a new well")
check(bf("New", "Water Supply")[0] == "inj" and bf("New", "Gas Storage/ Observ")[0] == "inj" and bf("Change of Location", "Oil")[0] == "amend" and bf("Existing Well", "Oil")[0] == "other", "water supply and storage/observation wells are service wells; a change of location is an amendment; 'Existing Well' is other")
check(bf("New", "Non-Commercial Ga") == ("new", "gas") and bf("New", "Non-Commercial Gas") == ("new", "gas"), "the Division's field cuts a long well type short (Non-Commercial Ga): still a gas well")

# ------------------------------------------------------------------------------------------------ one list
ps, unread = IN.parse_week(week_text(date(2025, 3, 7), [dict(operator="Example Oil Corporation", kind="Oil", day=date(2025, 3, 6), county="Posey", app="Deepening"),
                                                 dict(operator="Pat Q Sample", kind="Oil", day=date(2025, 3, 6), county="St. Joseph", app="New"),
                                                 dict(operator="Sample Energy, LLC", kind="Enhanced Recovery", day=date(2025, 3, 3), county="Gibson", app="")]), TODAY)
check([(p["day"], p["band"], p["county"], p["operator"], p["blank"]) for p in ps] == [(date(2025, 3, 6), "redrill", "Posey", "Example Oil Corporation", False), (date(2025, 3, 6), "new", "St. Joseph", "Pat Q Sample", False),
                                                                                       (date(2025, 3, 3), "inj", "Gibson", "Sample Energy, LLC", True)], "a list is read paragraph by paragraph: the day, the band, the county, the operator's name, whether the application type was blank")
check(all(set(p) == {"day", "band", "fluid", "county", "operator", "blank"} for p in ps), "a permit leaves the list as six fields and no more")
dump = json.dumps(ps, default=str)
check(not any(x in dump for x in ("Example Road", "Springfield", "555", "99001", "Sample Lease", "Fort Payne", "Consolidated", "46000")), "no address, city, phone, permit number, lease, formation or pool is kept")
check(IN.parse_week(week_text(date(2025, 3, 7), []), TODAY) == ([], 0) and unread == 0, "a list that says there were no permits gives none, and a list read whole leaves nothing unread")
check(IN.parse_week(week_text(date(2025, 3, 7), [dict(operator="Example Oil Corporation", kind="Oil", day=date(2025, 3, 6), county="Posey", app="New")]).replace("Posey", "Posey ").replace("  County,", " County,"), TODAY)[0][0]["county"] == "Posey", "a county is read through the spacing")
page2 = week_text(date(2025, 3, 7), [dict(operator="Example Oil Corporation", kind="Oil", day=date(2025, 3, 6), county="Posey", app="New")])
two = page2.replace("was issued", "Indiana Department\nof Natural Resources\n\n\n        State Of Indiana\n        Department of Natural Resources\n%sPermits Issued\n\nwas issued" % (" " * 60), 1)
check(IN.parse_week(two, TODAY)[0][0]["operator"] == "", "a paragraph whose operator line was left on the page before (a page header is the line above) has no operator, not the header")
check(raises(lambda: IN.parse_week("Some other document\n", TODAY), ValueError) is not None, "a text that is neither a list of permits nor a statement of none fails the list")
check(raises(lambda: IN.parse_week("There were no permits issued.\nthe well is located in Posey County, somewhere\n", TODAY), ValueError) is not None, "a statement of none beside a permit's wording is not trusted")
for what, text in (("a stray paragraph with no first line", page2 + "\nthe well is located in a place no one wrote down\n"), ("a county that cannot be read", page2.replace("County,", "Parish,")),
                   ("an application that cannot be read", page2.replace("well, located in the", "well located at the")), ("a permit date that is not a date", page2.replace("3/6/2025", "13/45/2025")),
                   ("a permit dated after today", page2.replace("3/6/2025", "3/6/2027")), ("a permit dated far from its week", page2.replace("3/6/2025", "3/6/2023"))):
    got, bad = IN.parse_week(text, TODAY)
    check(bad == 1 and len(got) == (1 if what.startswith("a stray") else 0), "%s: the paragraph is counted as unread, not guessed at (%d read, %d unread)" % (what, len(got), bad))
garbled = "\n".join(["Example Oil Corporation                        100 Example Road                       Springfield               IN   46000-         (555) 555-0100",
                     "was issued a(n)      Oil Storage", "Gas                  permit on      9/1/2025 . The # SEK-S-2", "  99001 is located in Clark", "  99002   Knox   County,   Section 93",
                     ",surface elevation   470 feet. This Vertical", "   529   Renewal", "   New   well, located in the Wildcat", "pool is permitted to the   Devonian   3200   feet.", "", ""])
got, bad = IN.parse_week(garbled + "\n" + page2.split("\n\n", 1)[1], TODAY)
check(len(got) == 1 and bad == 1 and got[0]["band"] == "new", "two permits printed on top of each other (as one real PDF does) are one unread paragraph, and the clean paragraph after them is still read")
check(raises(lambda: IN.parse_week("", TODAY), ValueError) is not None, "an empty text is not a list")

# ------------------------------------------------------------------------------------------------ the document: every permit by the day it was issued
net = Net()
doc = build(net)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "IN" and doc["measure"] == "permits" and "issue" in doc["basis"] and doc["name"] == "Indiana", "Indiana, counted by the day each permit was issued")
check(doc["months"][0] == "2020-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-23" and len(doc["months"]) == 81,
      "from January 2020 (where the lists start) to the last complete month: %s to %s, asOf %s" % (doc["months"][0], doc["months"][-1], doc["asOf"]))
truth = collections.Counter()
for d in ALL:
    for p in TRUTH[d]:
        truth[(C.month_of(p["day"]), p["band"])] += 1
ok = all(doc["bands"][b][i] == truth[(ym, b)] for b in C.BANDS for i, ym in enumerate(doc["months"]))
check(ok, "every band of every month is exactly what the fake Division issued (counted by the permit's own date, not the list's week)")
check(all(doc["bands"][b] is not None for b in C.BANDS), "the source tells every band: each is counted, none is null")
check(sum(doc["bands"]["new"]) == sum(v for (ym, b), v in truth.items() if b == "new" and "2020-01" <= ym <= "2026-09") and doc["read"] == sum(sum(doc["bands"][b]) for b in C.BANDS) + sum(v for (ym, b), v in truth.items() if ym > "2026-09"),
      "read counts every permit it took, the months after `through` included")
feb = doc["months"].index("2022-02")
check(all(doc["bands"][b][feb] == 0 for b in C.BANDS) and doc["bands"]["new"][feb - 1] > 0 and doc["bands"]["new"][feb + 1] > 0, "a month whose every list says there were none is a real zero in every band, inside the series")
last12 = doc["months"][-12:]
want_new = {ym: truth[(ym, "new")] for ym in last12}
check(sum(doc["bands"]["new"][-12:]) == sum(want_new.values()), "the last 12 months' new wells are the truth's")
check(doc["fluid"] is not None and doc["fluid"]["gas"] + doc["fluid"]["oil"] == sum(want_new.values()) and doc["fluid"]["other"] == 0 and doc["fluid"]["unknown"] == 0 and doc["fluid"]["gas"] > 0, "the fluid of the new wells comes from the well type: %s" % doc["fluid"])
check(doc["counties"] and doc["counties"][0][0] == "Posey" and {c[0] for c in doc["counties"]} == {"Posey", "Gibson", "Sullivan"}, "the counties are ranked by the last 12 months' new wells: %s" % doc["counties"])
names = [o[0] for o in doc["operators"]]
check(names == ["EXAMPLE OIL CORPORATION", "MESA PARTNERS LP"] and "PAT Q SAMPLE" not in json.dumps(doc).upper(), "operators: the corporation and the partnership, no person: %s" % doc["operators"])
share = doc["namedShare"]
check(share is not None and 0.6 < share < 1, "the named share counts the person's new wells as unnamed: %s" % share)
check("weekly" in doc["cadence"] and doc["source"]["url"] == IN.INDEX and "January 2020" in doc["note"] and "real zero" in doc["note"], "the cadence, the source and a note on where the lists start and that a quiet month is a real zero")
check(len(net.urls) == 1 + len(ALL) and len(set(net.urls)) == len(net.urls), "a full read asks the index once and every list once (%d requests)" % len(net.urls))
text = json.dumps(doc)
check(not any(x in text for x in ("Example Road", "555", "99001", "Pat Q", "Springfield")), "no address, phone, permit number or person is anywhere in the file")

# ------------------------------------------------------------------------------------------------ an incremental read
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "IN.json")
    json.dump(doc, open(path, "w"))
    kf = "2025-08"
    kept = IN.previous(kf, path)
    check(sorted(kept) == C.month_list("2020-01", "2025-07") and kept["2020-01"]["new"] == doc["bands"]["new"][0] and set(kept["2025-07"]) == set(C.BANDS), "the committed months before the window are taken, with every band")
    check(IN.previous(kf, os.path.join(tmp, "none.json")) == {}, "no committed file: nothing is taken")
    open(path, "w").write("{not json")
    check(IN.previous(kf, path) == {}, "a damaged committed file: nothing is taken")
    for what, mut in (("a file that starts later", lambda d: d.update(months=d["months"][1:], bands={b: v[1:] for b, v in d["bands"].items()})), ("a file for another state", lambda d: d.update(state="OH")),
                      ("a file that stops before the window", lambda d: d.update(months=d["months"][:60], bands={b: v[:60] for b, v in d["bands"].items()})),
                      ("a file with a band that is not told", lambda d: d["bands"].update(amend=None))):
        d2 = json.loads(json.dumps(doc))
        mut(d2)
        json.dump(d2, open(path, "w"))
        check(IN.previous(kf, path) == {}, "%s is not trusted: everything is read again" % what)
net2 = Net()
doc2 = build(net2, old=kept)
n_week = len(net2.urls) - 1
check(doc2 == doc, "with the earlier months committed the document is the same as a full read")
check(0 < n_week <= 68 and n_week < len(ALL) / 4, "and only the last 14 months' lists are read again (%d of %d lists)" % (n_week, len(ALL)))
check(all(IN.HOST + URL[d] in net2.urls for d in ALL if d >= date(2025, 8, 1)), "every list from the window's first month on is among them")

# ------------------------------------------------------------------------------------------------ failures fail the run; they never write a short file
check("layout" in (raises(lambda: build(Net(index="<html>Server busy</html>")), RuntimeError) or ""), "an index that lost its tables fails the run: its layout may have changed")
few = index_html([(d, URL[d]) for d in ALL[:120]])
check("expected" in (raises(lambda: build(Net(index=few)), RuntimeError) or ""), "an index with too few weeks fails the run")
late = index_html([(d, URL[d]) for d in ALL if d >= date(2021, 6, 1)])
check("January 2020" in (raises(lambda: build(Net(index=late)), RuntimeError) or ""), "an index that no longer reaches back to January 2020 fails the run")
check("stale" in (raises(lambda: build(Net(), today=date(2027, 1, 20)), RuntimeError) or ""), "an index whose newest list is two months old fails the run")
check(raises(lambda: build(Net(), today=date(2026, 12, 20)), RuntimeError) is None, "one 58 days old is fine")
bad_week = ALL[200]
damaged = dict(TEXT)
damaged[IN.HOST + URL[bad_week]] = "Some page that is not a weekly list"
check(bad_week.isoformat() in (raises(lambda: build(Net(texts=damaged)), RuntimeError) or ""), "a list that cannot be read fails the run, naming its week")
damaged = dict(TEXT)
damaged[IN.HOST + URL[ALL[150]]] = TEXT[IN.HOST + URL[ALL[150]]].replace("County,", "Parish,")
one = build(Net(texts=damaged))
check(sum(one["bands"]["new"]) == sum(doc["bands"]["new"]) - 1 and C.validate(one, TODAY) == [], "one paragraph that cannot be read is left out (and counted as unread), not guessed at: the run still succeeds, one permit short")
for k in range(150, 175):
    damaged[IN.HOST + URL[ALL[k]]] = TEXT[IN.HOST + URL[ALL[k]]].replace("County,", "Parish,")
check("could not be read" in (raises(lambda: build(Net(texts=damaged)), RuntimeError) or ""), "many paragraphs that cannot be read fail the run: the lists' layout may have changed")
repeat = index_html([(d, URL[d]) for d in ALL[:100]] + [(d, URL[ALL[99]]) for d in ALL[100:112]] + [(d, URL[d]) for d in ALL[112:]])
check("another week already uses" in (raises(lambda: build(Net(index=repeat)), RuntimeError) or ""), "an index that points many weeks at files other weeks use fails the run")
known = index_html([(d, URL[d]) for d in ALL if d != date(2023, 7, 28)] + [(date(2023, 7, 28), URL[date(2023, 7, 21)])])
dk = build(Net(index=known))
check("two permits more" in dk["note"] and "also points" not in dk["note"], "the index's known defect (July 2023) is in the note, and needs no further words")
fresh = index_html([(d, URL[d]) for d in ALL if d != date(2025, 11, 7)] + [(date(2025, 11, 7), URL[date(2025, 10, 31)])]) if date(2025, 11, 7) in ALL else None
dn = build(Net(index=fresh))
check("also points the weeks ending November 7, 2025" in dn["note"], "a week newly pointed at another week's file is named in the note: its permits are not counted")
check(raises(lambda: build(Net(fail=lambda u: u == IN.HOST + URL[ALL[100]])), RuntimeError) is not None, "a list that cannot be fetched fails the run")
check("expected" in (raises(lambda: build(Net(), min_permits=100000), RuntimeError) or ""), "too few permits in all fail the run (the lists may be cut short)")


def refuse(url, **k):
    raise C.Refused("HTTP 403 from the server")


check(raises(lambda: IN.build(get=refuse, to_text=lambda b: "", pause=0, today=TODAY, old={}), C.Refused) is not None, "a refusal is passed up as a refusal (never retried here)")


class Half(Net):
    def get(self, url, **k):
        if len(self.urls) > 30:
            raise C.Refused("HTTP 429 from the server")
        return Net.get(self, url, **k)


check(raises(lambda: build(Half()), C.Refused) is not None, "a refusal in the middle of the read is a refusal, not a short file")


def no_tool(b):
    raise RuntimeError("pdftotext (poppler-utils) is not installed")


check("pdftotext" in (raises(lambda: IN.build(get=Net().get, to_text=no_tool, pause=0, today=TODAY, old={}), RuntimeError) or ""), "a missing pdftotext fails the run, loudly")
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "IN.json")
    open(old, "w").write("committed\n")
    check(C.run_producer("IN", lambda: IN.build(get=refuse, to_text=lambda b: "", pause=0, today=TODAY, old={}), tmp, argv=[]) == 2 and open(old).read() == "committed\n", "a refusing server ends the run with exit 2 and leaves the committed file alone")
    check(C.run_producer("IN", lambda: build(Net(index="<html></html>")), tmp, argv=[]) == 1 and open(old).read() == "committed\n", "a failed run exits 1 and leaves the committed file alone")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("IN", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "IN.json")), "run_producer writes nat/IN.json for it")
    check(C.check_dir(tmp) == [] and C.run_producer("IN", lambda: doc, tmp, argv=["--check"]) == 0, "the written file reloads and validates")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
