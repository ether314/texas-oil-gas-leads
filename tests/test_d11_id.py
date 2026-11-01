"""Tests for site/pipeline/d11_nat_id.py: Idaho's permits to drill (Department of Lands, Oil and Gas Conservation Commission), read from the Well and Facilities Files index and one page per well.

The fixtures are an invented index and invented well pages built the way the real ones are (a WordPress page with a list of wells, and per well a content block of "Well Status:", "County:" and
"Operator:" lines, a "Permit to Drill" link whose file name starts with the approval day, sundry notices and other documents around it, DCTERMS meta tags that give the day the page was made), with
invented wells, operators and numbers. They pin: that the day at the start of the permit file's name is the approval day (in two layouts, 2026.02.04_ and 20211002_) and that an API number
or a lease path is not one; that the two permits whose posted file is an AMENDED version are counted at their first approval (and that without that rule they would land three months late); that an
amended or oddly dated permit that is not in the table fails the run instead of being guessed; that the older wells (their pages were all made in one import in June 2019) stay out of the series and
may have no date; that months with no permit are real zeros, that the last 30 days are not shown, that only the permit to drill is counted (the other bands are null), the counties, the
operator rule (the page's "O&G" short form is counted under the company's name; a person is never named) and that nothing but counts (no well, lease, API number or person) reaches the output; one
request per page, 3 seconds apart, only to the Commission's own site and never to a PDF; and that a changed index, a cut-short index, a changed page, fewer permits than the committed file, a refusal
and a failing request each leave the committed file as it was. With ID_REAL_PAGES=<folder with index.html and pages/*.html> it also replays pages read from the real site.

Run: python3 -I tests/test_d11_id.py"""
import json
import os
import re
import sys
import tempfile
import types
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_id as ID  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, needle=""):
    try:
        fn()
    except RuntimeError as e:
        return needle in str(e)
    except Exception as e:  # noqa: BLE001
        print("     raised %s: %s" % (type(e).__name__, e))
        return False
    return False


# ------------------------------------------------------------------------------------------------ invented pages shaped like the real ones
UP = "https://ogcc.idaho.gov/wp-content/uploads/"
PAGE_T = """<!DOCTYPE html><html lang="en-US"><head><meta charset="UTF-8"><meta name="DCTERMS.title" content="USWN invented">
<meta name="DCTERMS.created" content="%(created)sT10:11:18"><meta name="DCTERMS.modified" content="%(modified)sT11:56:42"><title>USWN invented | Oil &amp; Gas Conservation Commission</title></head>
<body><header><a href="https://ogcc.idaho.gov/">Home</a> <a href="https://ogcc.idaho.gov/well-files/">Well &#038; Facilities Files</a></header>
<section><header class="entry-header"><h1 class="entry-title mb-0">USWN invented</h1></header><div class="entry-content"><div class="elementor"><div class="elementor-widget-container">
%(paras)s<ul>%(links)s</ul></div></div><figure><img src="https://ogcc.idaho.gov/wp-content/uploads/Invented-welloperations-1024x768.jpg"></figure></div><footer class="entry-footer"></footer></section>
<footer id="colophon"><p>Idaho Department of Lands<br>300 N. 6th St, Suite 103<br>Boise, Idaho 83702<br>(208) 334-0200</p><a href="mailto:comments@idl.idaho.gov">mail</a></footer></body></html>"""


def well_page(permit=None, text="Permit to Drill", county="Payette", operator="Snake River O&amp;G", created="2026-02-06", status="Producing", more=(), paras=None):
    links = ""
    if permit:
        links += '<li><a href="%s%s">%s</a></li>' % (UP, permit, text)
    for name, label in more:
        links += '<li><a href="%s%s">%s</a></li>' % (UP, name, label)
    if paras is None:
        paras = "<p>Well Status: %s</p><p>County: %s</p><p>Operator: %s</p><p>Total Depth: 5,000&#8242;</p><p>Document Links:</p>" % (status, county, operator)
    return PAGE_T % {"created": created, "modified": "2026-08-07", "paras": paras, "links": links}


DECOYS = (("2026.06.22_1199900041_SUND01_prsigned_PTS.pdf", "Sundry Notice 1"), ("2025.05.28_1199900022_WellTreatmentGasInject_permitconditions_PTS.pdf", "Well Treatment Permit"),
          ("20210306_Kf134_ActiveStatusExtension_granted_Final_PTS.pdf", "Active Permit Extension"), ("2025.04.24_1199900022_WellTreatment_signed_PTS.pdf", "Well Treatment Application"))


def slug(n, name):
    return "uswn-11-999-%05d-%s" % (n, name)


def build_site():
    """{slug: page} for 36 invented wells: 26 older ones (pages made in the June 2019 import), 2 whose permit file has no date, and the 8 permits of the series."""
    pages = {}
    for i in range(26):
        pages[slug(20001 + i, "old-%d" % i)] = well_page("20%02d%02d%02d_11999%05d_Old%d_APD-posted2018_PTS.pdf" % (9 + i % 9, 1 + i % 12, 1 + i % 27, 20001 + i, i), created="2019-06-12", status="Plugged",
                                                           operator="AM Invented, LLC (Bridge)" if i % 3 else "Bridge Energy", more=DECOYS[:2])
    pages[slug(20011, "undated-a")] = well_page("1199900011_Invented17_1_APDandAmendment_PTS.pdf", created="2019-06-12", status="Dry Hole / Plugged and Abandoned", county="Bonneville", operator="Invented Mineral")
    pages[slug(20014, "undated-b")] = well_page("2017/07/11-199-20014-invented-federal-20-3.pdf", created="2019-06-12", status="Plugged", county="Bonneville", operator="Invented Mineral, LLC",
                                                more=(("20171002_1199900014_SUND01_PTS.pdf", "Sundry Notice"),))
    specs = [  # (slug number, permit file, link text, created, county, operator)
        (20036, "20210913_1199900036-Invented2-14_APD-Approved-revised-PTS.pdf", "Permit to Drill &#8211; revised", "2021-06-17", "Payette", "Snake River O&amp;G"),
        (20037, "20211002_1199900037-APPROVED-Invented1-11_PTS.pdf", "Permit to Drill", "2021-10-05", "Payette", "Snake River O&amp;G"),
        (20038, "2021.12.24_1199900038_APPROVED-Revised_Invented1_13_PTS.pdf", "Permit to Drill &#8211; revised", "2021-11-18", "Payette", "Snake River O&amp;G"),
        (20039, "2022.09.10_1199900039_Invented1-19_CombinedPermitApproved_PTS.pdf", "Permit to Drill", "2022-09-12", "Payette", "Snake River O&amp;G"),
        (20040, "2022.09.27_1199900040_Invented3-14_CombinedPermitApproved_PTS.pdf", "Permit to Drill", "2022-09-27", "Payette", "Snake River O&amp;G"),
        (20004, "2025.11.07_1199900004_InventedPeaks1W_APD_approved_PTS.pdf", "Permit to Drill", "2025-11-07", " Canyon", " Invented Exploration LLC"),
        (20041, "2026.02.04_1199900041_Invented1-10_APDApproved_Combined_PTS.pdf", "Permit to Drill", "2026-02-06", "Payette", "Snake River O&amp;G"),
        (20042, "2026.05.22_Invented1-15_APD_no35_Final_Redactedsigned_PTS.pdf", "Permit to Drill", "2026-06-04", "Payette", "Snake River O&amp;G"),
    ]
    for n, f, text, created, county, op in specs:
        pages[slug(n, "invented-%d" % n)] = well_page(f, text, county=county, operator=op, created=created, status="Drilled/Confidential", more=DECOYS)
    return pages


def index_page(slugs, extra="", relative=False):
    items = ""
    for s in slugs:
        href = ("/well-files/%s/" if relative else "https://ogcc.idaho.gov/well-files/%s/") % s
        items += '<li><a href="%s" rel="noreferrer noopener" aria-label=" (opens in a new tab)">USWN %s Invented #1</a></li>' % (href, s[5:19])
    return ('<!DOCTYPE html><html><head><meta name="DCTERMS.modified" content="2026-06-04T13:19:05"><title>Well &#038; Facilities Files</title></head><body>'
            '<nav><a href="https://ogcc.idaho.gov/well-files/">Well &#038; Facilities Files</a> <a href="https://ogcc.idaho.gov/data-explorer/">Data Explorer</a></nav>'
            '<h1 class="entry-title mb-0">Well &#038; Facilities Files</h1><h2>Payette County</h2><ul>%s</ul>'
            '<p><a href="https://ogcc.idaho.gov/well-files/highway-30-gas-processing/">Highway 30 Gas Processing</a> <a href="https://ogcc.idaho.gov/well-files/little-willow-gathering/">Little Willow Gathering</a> '
            '<a href="https://gis1.idl.idaho.gov/FileServer/oilgas/welldata/LASFiles.zip">compressed zip file.</a></p>%s</body></html>') % (items, extra)


class Net:
    """The network, faked: the index and the well pages. Every request is kept (address and options); an address that is not served raises."""

    def __init__(self, pages, index=None, fail=None):
        self.pages, self.fail, self.urls = pages, fail, []
        self.index = index if index is not None else index_page(list(pages))

    def get(self, url, **kw):
        self.urls.append((url, kw))
        if self.fail and self.fail(url):
            raise RuntimeError("could not read the source")
        if url == ID.INDEX:
            return self.index.encode()
        m = re.fullmatch(r"https://ogcc\.idaho\.gov/well-files/([a-z0-9\-]+)/", url)
        if m and m.group(1) in self.pages:
            return self.pages[m.group(1)].encode()
        raise RuntimeError("not served: " + url)


NOTHING = os.path.join(tempfile.mkdtemp(prefix="id-none-"), "ID.json")  # a committed file that does not exist: the tests never read the repository's own nat/ID.json
SLEEPS = []
ID.time = types.SimpleNamespace(sleep=lambda s: SLEEPS.append(s))


def run(net, **kw):
    return ID.build(get=net.get, today=kw.pop("today", TODAY), committed=kw.pop("committed", NOTHING), **kw)


def fails(pages=None, index=None, needle="", **kw):
    net = Net(pages if pages is not None else build_site(), index=index)
    return raises(lambda: run(net, **kw), needle)


# ------------------------------------------------------------------------------------------------ the file name's date
D = lambda s: ID.file_day(UP + s, TODAY)  # noqa: E731
check(D("2026.02.04_1107520041_Invented1-10_APDApproved_Combined_PTS.pdf") == date(2026, 2, 4), "2026.02.04_... is February 4, 2026")
check(D("20211002_1107520037-APPROVED-Invented1-11_PTS.pdf") == date(2021, 10, 2), "20211002_... is October 2, 2021")
check(D("2022-09-27_x.pdf") == date(2022, 9, 27) and D("2022.09.27 x.pdf") == date(2022, 9, 27), "dashes and a space after the day read as well")
check(D("1101920011_CPC17_1_APDandAmendment_PTS.pdf") is None and D("11-019-20014-federal-20-3.pdf") is None and D("2017/07/11-019-20014-federal-20-3.pdf") is None,
      "an API number at the start of a file name (10 digits) or a path ending in 11-019-... is not a date")
check(D("2025.05_LittleWillowGathFacility_inspection_JAT_PTS.pdf") is None and D("Application-for-Well-Treatment-2020.pdf") is None, "a year and month only, or no date, is not a day")
check(D("2026.02.04_1107520041.pdf?x=1") == date(2026, 2, 4), "a query string is ignored")
check(raises(lambda: D("2026.13.45_x.pdf"), "not a day") and raises(lambda: D("2027.01.15_x.pdf"), "cannot be right"), "a date that is not a day, or after today, fails the run")

# ------------------------------------------------------------------------------------------------ one well page
w = ID.parse_well(well_page("2026.02.04_1107520041_x_PTS.pdf", county="Payette", operator="Snake River O&amp;G", created="2026-02-06", more=DECOYS), TODAY)
check(w == {"county": "Payette", "operator": "Snake River O&G", "created": date(2026, 2, 6), "permit": (date(2026, 2, 4), False)}, "a well page gives county, operator, creation day and the permit's day: %s" % w)
w = ID.parse_well(well_page("2021.12.24_x_APPROVED-Revised_PTS.pdf", "Permit to Drill &#8211; revised", county=" Canyon", operator=" Cascade  Exploration LLC", created="2021-11-18"), TODAY)
check(w["county"] == "Canyon" and w["operator"] == "Cascade Exploration LLC" and w["permit"] == (date(2021, 12, 24), True), "a double space after the colon and inside a name is one space; the link text says revised")
w = ID.parse_well(well_page("20210913_x_APD-Approved-revised-PTS.pdf"), TODAY)
check(w["permit"][1] is True, "a file name that says revised counts as revised although the link text does not")
w = ID.parse_well(well_page("2026.02.04_x_PTS.pdf", more=DECOYS), TODAY)
check(w["permit"][0] == date(2026, 2, 4), "sundry notices, well treatments and extensions are not the permit to drill")
check(ID.parse_well(well_page(None, more=DECOYS), TODAY)["permit"] is None, "a page with no Permit to Drill link has no permit")
check(raises(lambda: ID.parse_well(well_page("2026.02.04_x.pdf", more=(("2026.02.05_y.pdf", "Permit to Drill - copy"),)), TODAY), "2 permits"), "two permits to drill on one page fail the run")
check(raises(lambda: ID.parse_well("<html><body><p>County: Payette</p></body></html>", TODAY), "content block"), "a page without its content block fails the run")
check(raises(lambda: ID.parse_well(well_page("2026.02.04_x.pdf", paras="<p>Nothing here</p>"), TODAY), "neither a status nor a county"), "a page that states no status and no county fails the run")

# ------------------------------------------------------------------------------------------------ which day a permit is counted on
check(ID.approval_day(date(2026, 2, 4), False, date(2026, 2, 6)) == date(2026, 2, 4), "a plain permit is counted on its file's day (page made 2 days later)")
check(ID.approval_day(date(2026, 5, 22), False, date(2026, 6, 4)) == date(2026, 5, 22), "13 days between the permit and its page is fine (a page may be posted late)")
check(ID.approval_day(date(2026, 2, 6), False, date(2026, 2, 4)) == date(2026, 2, 6), "a permit dated 2 days after its page was made is fine")
check(ID.approval_day(date(2018, 10, 18), True, date(2019, 6, 12)) is None and ID.approval_day(date(2017, 10, 19), False, None) is None, "a permit before 2019 is outside the series, whatever its page says")
check(ID.approval_day(date(2021, 9, 13), True, date(2021, 6, 17)) == date(2021, 6, 16), "the amended file of September 13, 2021 is counted at its first approval, June 16")
check(ID.approval_day(date(2021, 12, 24), True, date(2021, 11, 18)) == date(2021, 11, 17), "the amended file of December 24, 2021 is counted at its first approval, November 17")
check(raises(lambda: ID.approval_day(date(2027, 3, 3), True, date(2027, 1, 5)), "ORIGINAL_APPROVAL"), "a new amended permit is not in the table: the run fails and says what to add")
check(raises(lambda: ID.approval_day(date(2026, 9, 1), False, date(2026, 3, 1)), "does not fit its page"), "a file dated 6 months after its page was made is a later version: fails the run, never guessed")
check(raises(lambda: ID.approval_day(date(2026, 2, 20), False, date(2026, 2, 6)), "does not fit its page"), "a file dated 14 days after its page was made does not fit either")
check(raises(lambda: ID.approval_day(date(2025, 1, 1), False, date(2026, 6, 1)), "does not fit its page"), "a file dated 17 months before its page was made does not fit")
check(raises(lambda: ID.approval_day(date(2026, 2, 4), False, None), "no creation date"), "a page with no creation date cannot be checked")
check(raises(lambda: ID.approval_day(date(2021, 9, 13), True, date(2021, 12, 1)), "ORIGINAL_APPROVAL"), "the table's date is held to the page: June 16 for a page made in December fails")
check(raises(lambda: ID.approval_day(date(2021, 10, 2), True, date(2021, 10, 5)), "ORIGINAL_APPROVAL"), "a permit that says revised, not in the table, fails even when its dates fit")

# ------------------------------------------------------------------------------------------------ the index
idx = index_page(list(build_site()))
urls = ID.parse_index(idx)
check(len(urls) == 36 and all(u.startswith("https://ogcc.idaho.gov/well-files/uswn-") and u.endswith("/") for u in urls), "the index gives the 36 well pages (not the two facility pages, the menu or the zip): %d" % len(urls))
check(ID.parse_index(index_page(list(build_site()), relative=True)) == urls, "root-relative links read the same")
check(ID.parse_index(index_page(list(build_site()) + list(build_site())[:5])) == urls, "a well linked twice counts once")
check(raises(lambda: ID.parse_index(index_page(list(build_site())[:12])), "cut short"), "an index of 12 wells fails the run")
check(raises(lambda: ID.parse_index(idx.replace("Facilities Files", "Things")), "heading is gone"), "an index that lost its heading fails the run")
check(raises(lambda: ID.parse_index(index_page(["uswn-11-999-%05d-x" % i for i in range(300)])), "cut short or changed"), "an index linking 300 wells fails the run (a changed layout)")

# ------------------------------------------------------------------------------------------------ the whole build
SLEEPS.clear()
net = Net(build_site())
doc = run(net)
bad = C.validate(doc, TODAY)
check(bad == [], "what it writes validates: %s" % bad[:2])
check(len(net.urls) == 37 and net.urls[0][0] == ID.INDEX and len({u for u, _ in net.urls}) == 37, "one request for the index and one for each of the 36 well pages, none twice")
check(all(u.startswith("https://ogcc.idaho.gov/well-files/") for u, _ in net.urls) and not any(u.lower().endswith(".pdf") for u, _ in net.urls), "only the Commission's own list and well pages are asked for: no PDF is ever opened")
check(all(kw.get("max_bytes") for _, kw in net.urls), "every download has a size cap")
check(SLEEPS == [ID.PAUSE] * 36 and ID.PAUSE >= 3, "a pause of 3 seconds before each of the 36 well pages: %s" % sorted(set(SLEEPS)))
check(doc["state"] == "ID" and doc["measure"] == "permits" and doc["basis"] == "approval date" and doc["cadence"].startswith("irregular"), "permits by approval date, irregular")
check(doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-11-01",
      "the series runs from 2019-01 to the last month ending 30 days before the read (September 2026), as of the day it was read")
new = doc["bands"]["new"]
at = {m: n for m, n in zip(doc["months"], new) if n}
check(at == {"2021-06": 1, "2021-10": 1, "2021-11": 1, "2022-09": 2, "2025-11": 1, "2026-02": 1, "2026-05": 1}, "permits by month: the two amended permits at their first approval (June and November 2021): %s" % at)
check(sum(new) == 8 and doc["read"] == 8, "eight permits since 2019 (the older wells are outside the series)")
by_year = {y: sum(n for m, n in zip(doc["months"], new) if m.startswith(str(y))) for y in range(2019, 2027)}
check(by_year == {2019: 0, 2020: 0, 2021: 3, 2022: 2, 2023: 0, 2024: 0, 2025: 1, 2026: 2}, "by year: 0, 0, 3, 2, 0, 0, 1, 2: %s" % by_year)
check(all(doc["bands"][b] is None for b in ("inj", "redrill", "rework", "amend", "other")) and doc["fluid"] is None, "every band but the permit to drill is null, never zero; the fluid is not recorded")
check(sum(new[-24:]) == 3 and "zeroOk" not in doc, "three permits in the last 24 months: an ordinary file, no zeroOk")
check(doc["counties"] == [["Payette", 2], ["Canyon", 1]], "counties of the last 12 months, ranked: %s" % doc["counties"])
check(doc["operators"] == [["SNAKE RIVER OIL AND GAS LLC", 2], ["INVENTED EXPLORATION LLC", 1]] and doc["namedShare"] == 1.0, "the page's 'Snake River O&G' is counted under the company's name; both operators are named: %s" % doc["operators"])
check("8 permits to drill from January 2019 to September 2026, the newest on May 22, 2026" in doc["note"] and "real zero" in doc["note"] and "last 30 days" in doc["note"] and "last edited June 4, 2026" in doc["note"], "the note says how many permits, when the newest was approved, that zeros are real, the lag and when the list was edited")
text = json.dumps(doc)
scrubbed = text.replace("INVENTED EXPLORATION LLC", "")
check(not re.search(r"(?i)invented|old-|bridge|mineral|11-999|1199900|uswn|\(208\)|idl\.idaho|boise", scrubbed), "no well name, lease, API number, address or phone reaches the output (only the operator's company name)")
check(not re.search(r"\d{10}|\d{3}-\d{3}-\d{4}|@", re.sub(r"https://[\w./\-]+", "", text)), "no ten-digit number, phone number or e-mail in the file")
check(not re.search(r"\b(null|undefined|NaN|Infinity)\b", doc["note"]), "the note has no programmer's word")
check(C.validate(run(Net(build_site())), TODAY) == [] and json.dumps(run(Net(build_site())), sort_keys=True) == json.dumps(doc, sort_keys=True), "a second read of the same pages gives the same file")

# the operator rule
check(ID.operator_name("Snake River O&G") == "Snake River Oil and Gas, LLC" and ID.operator_name(" snake  river o&g ") == "Snake River Oil and Gas, LLC" and ID.operator_name("Cascade Exploration LLC") == "Cascade Exploration LLC",
      "only the one short form is expanded; other names are untouched")
person = build_site()
person[slug(20041, "invented-20041")] = well_page("2026.02.04_1199900041_x_PTS.pdf", created="2026-02-06", operator="Pat Q. Roe", more=DECOYS)
d2 = run(Net(person))
check(d2["operators"] == [["INVENTED EXPLORATION LLC", 1], ["SNAKE RIVER OIL AND GAS LLC", 1]] and d2["namedShare"] == round(2 / 3, 3) and "ROE" not in json.dumps(d2).upper(), "a person's name is never published; the permit still counts, and the named share falls to 2 of 3")
other = build_site()
other[slug(20042, "invented-20042")] = well_page("2026.05.22_x.pdf", created="2026-06-04", operator="Bridge Energy", more=DECOYS)
d3 = run(Net(other))
check(d3["operators"] == [["INVENTED EXPLORATION LLC", 1], ["SNAKE RIVER OIL AND GAS LLC", 1]] and sum(d3["bands"]["new"]) == 8, "a company name the rule cannot confirm (no LLC, Inc. or LP) is counted but not named")

# the 30-day lag: the last month is shown only 30 days after it ends
d4 = run(Net(build_site()), today=date(2026, 10, 29))
d5 = run(Net(build_site()), today=date(2026, 10, 30))
check(d4["months"][-1] == "2026-08" and d5["months"][-1] == "2026-09", "September is shown from October 30 (30 days after it ends), not before")

# ------------------------------------------------------------------------------------------------ a quiet two years: None recorded (zeroOk), only when the whole list was read
quiet = build_site()
for k in ("invented-20004", "invented-20041", "invented-20042"):
    n = int(k.split("-")[1])
    quiet.pop(slug(n, k))
dq = run(Net(quiet), today=date(2025, 10, 15))
check(C.validate(dq, date(2025, 10, 15)) == [] and sum(dq["bands"]["new"][-24:]) == 0 and dq.get("zeroOk") is True, "two years with no permit (to September 2025) are real zeros and the document says so (zeroOk)")
check(dq["counties"] == [] and dq["operators"] == [] and dq["namedShare"] is None and "the newest on September 27, 2022" in dq["note"], "no county or operator in the quiet window; the note names the newest permit's day")
check(raises(lambda: run(Net({k: v for k, v in list(quiet.items())[:20]})), "cut short"), "but a list cut to 20 wells never gets that far: it fails the run")

# ------------------------------------------------------------------------------------------------ the older wells: no date, no permit, a later page
check(sum(run(Net(build_site()))["bands"]["new"]) == 8, "two older wells whose permit file has no date, on pages made in June 2019, are accepted and left out")
late = build_site()
late[slug(20011, "undated-a")] = well_page("1199900011_Invented17_1_APDandAmendment_PTS.pdf", created="2026-03-01")
check(fails(late, needle="no date"), "an undated permit on a page made after the import fails the run (it could be a permit of the series)")
nopermit = build_site()
nopermit[slug(20011, "undated-a")] = well_page(None, created="2019-06-12")
check(sum(run(Net(nopermit))["bands"]["new"]) == 8, "an older well with no permit link is left out")
nopermit[slug(20011, "undated-a")] = well_page(None, created="2026-03-01")
check(fails(nopermit, needle="no Permit to Drill"), "a new well page with no permit link fails the run")
future = build_site()
future[slug(20042, "invented-20042")] = well_page("2026.12.25_x_PTS.pdf", created="2026-06-04")
check(fails(future, needle="cannot be right"), "a permit dated after the day of the read fails the run")
oddly = build_site()
oddly[slug(20042, "invented-20042")] = well_page("2026.05.22_x_PTS.pdf", created="2026-11-01")
check(fails(oddly, needle="does not fit its page"), "a permit dated five months before its page was made fails the run")
newrev = build_site()
newrev[slug(20042, "invented-20042")] = well_page("2026.05.22_x_APPROVED-Revised_PTS.pdf", "Permit to Drill &#8211; revised", created="2026-06-04")
check(fails(newrev, needle="ORIGINAL_APPROVAL"), "a new amended permit fails the run until its first approval is looked up")

# ------------------------------------------------------------------------------------------------ changed or damaged sources fail the run
check(fails(index=index_page(list(build_site())[:12]), needle="cut short"), "an index cut to 12 wells fails the run")
check(fails(index="<html>Service unavailable</html>", needle="heading is gone"), "an error page in place of the index fails the run")
STRIP = lambda v: re.sub(r"(uploads/)(?:\d{4}\.\d\d\.\d\d|\d{8})_", r"\1Permit_", v)  # noqa: E731  (the dates in every file name are gone)
check(fails({k: STRIP(v) for k, v in build_site().items()}, needle="no date"), "permit files that lost their dates fail the run on the first new page, not a quiet zero")
check(fails({k: (STRIP(v) if "2019-06-12" in v else v) for k, v in build_site().items()}, needle="naming changed"), "if only the older wells lost their dates, too few dates are left to trust: the run fails")
damaged = build_site()
damaged[list(damaged)[3]] = "<html><body>Maintenance</body></html>"
check(fails(damaged, needle="content block"), "one well page that is an error page fails the whole run")
check(raises(lambda: run(Net(build_site(), fail=lambda u: u.endswith("old-5/"))), "could not read"), "a request that fails fails the whole run")


def refusing(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    committed = os.path.join(tmp, "ID.json")
    check(C.run_producer("ID", lambda: ID.build(get=Net(build_site()).get, today=TODAY, committed=NOTHING), tmp, argv=[]) == 0 and os.path.exists(committed), "run_producer writes nat/ID.json for a good run")
    before = open(committed, "rb").read()
    check(C.check_dir(tmp) == [] and C.run_producer("ID", lambda: None, tmp, argv=["--check"]) == 0, "the written file reloads and passes --check")
    check(C.run_producer("ID", lambda: ID.build(get=refusing, today=TODAY, committed=NOTHING), tmp, argv=[]) == 2, "a refusal by the server exits 2 (an answer, not an error)")
    check(C.run_producer("ID", lambda: ID.build(get=Net(build_site(), index="<html>").get, today=TODAY, committed=NOTHING), tmp, argv=[]) == 1, "a failure exits 1")
    check(open(committed, "rb").read() == before and os.listdir(tmp) == ["ID.json"], "and the committed file is exactly as it was, with nothing else written")
    check(ID.previous(committed) == 8 and ID.previous(os.path.join(tmp, "nothing.json")) is None, "the committed file's total is read (8); no file is none")
    fewer = build_site()
    fewer.pop(slug(20042, "invented-20042"))
    check(raises(lambda: ID.build(get=Net(fewer).get, today=TODAY, committed=committed), "does not go away"), "an index with fewer permits than the committed file (a well page gone) fails the run")
    check(sum(ID.build(get=Net(fewer).get, today=TODAY, committed=NOTHING)["bands"]["new"]) == 7, "with no committed file the same index is accepted (7 permits)")
    more = build_site()
    more[slug(20043, "invented-20043")] = well_page("2026.09.10_1199900043_x_PTS.pdf", created="2026-09-12", operator="Invented Operating, Inc.", more=DECOYS)
    d6 = ID.build(get=Net(more).get, today=TODAY, committed=committed)
    check(sum(d6["bands"]["new"]) == 9 and d6["bands"]["new"][d6["months"].index("2026-09")] == 1, "a new permit is added, in its month")

# ------------------------------------------------------------------------------------------------ pages read from the real site, when given
real = os.environ.get("ID_REAL_PAGES")
if real:
    pages = {}
    for f in sorted(os.listdir(os.path.join(real, "pages"))):
        pages[f[:-5]] = open(os.path.join(real, "pages", f), encoding="utf-8").read()
    net = Net(pages, index=open(os.path.join(real, "index.html"), encoding="utf-8").read())
    d = ID.build(get=net.get, today=TODAY, committed=NOTHING)
    yrs = {y: sum(n for m, n in zip(d["months"], d["bands"]["new"]) if m.startswith(str(y))) for y in range(2019, 2027)}
    check(C.validate(d, TODAY) == [] and yrs == {2019: 0, 2020: 0, 2021: 3, 2022: 2, 2023: 0, 2024: 0, 2025: 1, 2026: 2}, "the real pages: 3 permits in 2021, 2 in 2022, 1 in 2025, 2 in 2026 (2021 and 2022 month by month as the Commission's quarterly APDs-approved counts have them): %s" % yrs)
    check(d["counties"] == [["Payette", 2], ["Canyon", 1]] and d["operators"][0] == ["SNAKE RIVER OIL AND GAS LLC", 2], "the real pages' last 12 months: Payette 2, Canyon 1; Snake River twice")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
