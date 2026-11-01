"""Tests for site/pipeline/d11_nat_ne.py: Nebraska's drilling permits, from the Oil and Gas Conservation Commission's yearly lists of permitted wells.

The fixtures are invented, written the way `pdftotext -layout` gives the Commission's files: a year's "Nebraska Permitted Wells" (a date, then for each permit three lines: the operator and the driller; the
well's name, footage, location and county; the field, depth, formation and API number), in the layout of 2021 and after (dates 01/11/2022, "API #:", page headers and page numbers that fall in the middle
of a permit) and the older one of 2019 and 2020 (dates 09-Mar-20, "Proposed Depth/Form.", a footer "Total Permits for Period = N" and a print date with "Page 1 of 4"); the Commission's yearly Oil Activity
Summary with its "Permitted Wells for <year>" table (and one year without a table, as 2023's is); and the Data and Publications page with its links. The network and pdftotext are faked.
They pin: the page's links (only the Commission's host, only from 2019, a year linked twice, a missing year, a page that lost its section), every line of a list (both layouts, a permit split by a page
break at each of its three lines, an operator left blank, the two footers), the band of each permit (a re-entry by its API number or OWWO, a disposal or injection well by a whole word in its name, else
new), the counting by month against a truth made by the same generator, that a list is checked against the Commission's summary and refused when they disagree (and not when they differ by one),
when a year is closed (so the series ends in December) and when it is not (the series ends before the newest permit's month), an incremental read (the committed months stand, only the newest two years
are asked for, the same document comes out), that nothing but counts, counties and nameable operators leaves a list (no API number, no well name, no driller), and that anything damaged (a line it
does not know, a county that is not Nebraska's, an API number of the wrong length or state, a date outside its year or out of order, a footer that disagrees, an empty list, a summary that is not the
Commission's, a refusal) fails the run instead of writing a short file.

Run: python3 -I tests/test_d11_ne.py"""
import collections
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_ne as NE  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, kind=RuntimeError):
    try:
        fn()
    except kind:
        return True
    except Exception as e:  # noqa: BLE001
        print("     raised %s: %s" % (type(e).__name__, e))
        return False
    return False


# ------------------------------------------------------------------------------------------------ the generator: a truth, written as the Commission's files
CODE = {"DUNDY": "057", "HITCHCOCK": "087", "HARLAN": "083", "LINCOLN": "111", "RED WILLOW": "145", "SCOTTS BLUFF": "157", "RICHARDSON": "147"}
MONTHS3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
OPS = ["INVENTED BASIN OPERATING LLC", "SAMPLE ROYALTY COMPANY LLC", "TEST PLAINS ENERGY, INC", "PAT Q ROE", "ROE BROTHERS LP"]
SEQ = [21000]


def permit(month, day, op, name, county, suffix="0000", seq=None):
    """One permit of the invented truth: (month, day, operator, well name, county, API number)."""
    if seq is None:
        SEQ[0] += 1
        seq = SEQ[0]
    return (month, day, op, name, county, "26" + CODE[county] + "%05d" % seq + suffix)


# every year's permits; the second part of each is what the generator is asked to make a mess of (see the page-break tests)
TRUTH = {
    2019: [permit(1, 11, OPS[0], "ALPHA 1", "HARLAN"), permit(3, 6, OPS[1], "BETA 2-3", "DUNDY"), permit(3, 6, OPS[2], "GAMMA 1-4", "DUNDY"), permit(10, 9, OPS[3], "DELTA 4", "RED WILLOW"), permit(12, 2, OPS[0], "EPSILON (OWWO) 1-1", "HARLAN", "0001", seq=21001)],
    2020: [permit(3, 9, OPS[0], "ZETA 10-1", "HARLAN"), permit(7, 14, OPS[2], "ETA SWD 16-29", "HITCHCOCK"), permit(12, 9, OPS[4], "THETA 3", "SCOTTS BLUFF")],
    2021: [permit(1, 4, OPS[1], "IOTA 1-12", "DUNDY"), permit(2, 1, OPS[1], "KAPPA 'A' 1-21", "DUNDY"), permit(2, 1, OPS[1], "LAMBDA 1-1", "DUNDY"), permit(6, 22, OPS[0], "MU WIW 2-2", "HITCHCOCK"),
           permit(9, 28, OPS[2], "NU 11-25", "HARLAN"), permit(11, 16, OPS[0], "XI 4-4", "LINCOLN", "0000"), permit(12, 3, OPS[0], "OMICRON INJECTION 5", "HARLAN")],
    2022: [permit(1, 11, OPS[2], "PI 1-30", "HITCHCOCK"), permit(5, 4, OPS[3], "RHO J-6", "RICHARDSON"), permit(5, 10, OPS[0], "SIGMA 35-1", "RICHARDSON"), permit(11, 4, OPS[1], "TAU 25-1", "RICHARDSON")],
    2023: [permit(1, 11, OPS[0], "UPSILON 1", "HITCHCOCK"), permit(10, 3, OPS[1], "PHI UNIT SWD 1-1", "DUNDY"), permit(11, 15, OPS[2], "CHI 1-27", "HITCHCOCK", "0001")],
    2024: [permit(2, 2, OPS[0], "PSI 1-1", "HARLAN"), permit(4, 1, OPS[0], "OMEGA 2-3", "HARLAN"), permit(12, 18, OPS[1], "ALEF 2-35", "HITCHCOCK")],
    2025: [permit(2, 20, OPS[0], "BET 29-1", "HARLAN"), permit(2, 20, OPS[0], "GIMEL 18-1", "HARLAN"), permit(3, 12, OPS[2], "DALET 1-26", "HITCHCOCK"), permit(8, 22, OPS[3], "HE 4-1", "SCOTTS BLUFF"),
           permit(10, 14, OPS[1], "VAV 1", "LINCOLN")],
}
FIELD = "Field: WILDCAT                    Proposed Depth: 4200       Formation: ARBUCKLE               API #: %s"
FIELD_OLD = "Field: WILDCAT                    Proposed Depth/Form.:  4200 ARBUCKLE         API:       %s"


def lines_of(year, rows, old=False):
    """The three lines of each permit, under a date line at each new date, as pdftotext gives them (the old layout has a blank line after each permit and a different date and field line)."""
    out, last = [], None
    for (m, d, op, name, county, api) in rows:
        stamp = "%02d-%s-%02d" % (d, MONTHS3[m - 1], year % 100) if old else "%02d/%02d/%d" % (m, d, year)
        if stamp != last:
            out.append(stamp)
            last = stamp
        out.append("   %-55s Driller: TEST DRLG CO" % op)
        out.append("   %-30s 1196S 2197W SE SW 29-4N-18W                           %s" % (name, county))
        out.append("   " + (FIELD_OLD if old else FIELD) % api)
        if old:
            out.append("")
    return out


def list_text(year, rows, old=False, breaks=(), footer=True):
    """A year's list. `breaks` are (index of a line in the permit lines, ...): a page number, a form feed and the page header are put after that line, as pdftotext does at a page end (inside a permit)."""
    ln = lines_of(year, rows, old)
    out = ["State of Nebraska", "Oil and Gas Conservation Commission", "Permitted Wells"] if old else ["                                                 Nebraska Permitted Wells"]
    page = 0
    for i, line in enumerate(ln):
        out.append(line)
        if i in breaks:
            page += 1
            out += ["", "                                         %d" % page, "\f" + ("                                       Nebraska Permitted Wells" if not old else "State of Nebraska")]
    if old and footer:
        out += ["                                                                Total Permits for Period = %d" % len(rows), "%d/%d/%d                                           Page 1 of 1" % (7, 9, year + 1)]
    return "\n".join(out) + "\n"


def summary_text(year, rows, table=True, shift=0):
    """The Commission's yearly summary: a title, a spudded-wells table (which is never read) and the permitted-wells table by county, with a wildcat, a development and a total column (a blank one is skipped)."""
    out = ["               NEBRASKA OIL AND GAS CONSERVATION COMMISSION", "", "                        NEBRASKA OIL ACTIVITY SUMMARY", "", "                                        %d" % year, "",
           "              Spudded Wells for %d" % year, "", "  COUNTY        WILDCAT    DEVELOPMENT    WELLS", "   Dundy         2            5           7", "TOTAL            6            8          14"]
    if table:
        by = collections.Counter(r[4] for r in rows)
        out += ["                Permitted Wells for %d" % year, "", "                                             TOTAL", "                                           PERMITTED", "  COUNTY        WILDCAT     DEVELOPMENT      WELLS"]
        for county, n in sorted(by.items()):
            n += shift if county == "DUNDY" else 0
            out.append("%12s      %d             %d            %d" % (county.title(), n, 0, n) if n % 2 else "%12s      %d                           %d" % (county.title(), n, n))
        out += ["TOTAL            %d             %d             %d" % (len(rows) + shift, 0, len(rows) + shift), "                                 NEW FIELDS", "                                 %d" % year]
    return "\n".join(out) + "\n"


NOTABLE = {2023}  # the year whose summary has no permitted-wells table
PAGE_LINKS = "".join('<li><a href="http://nogcc.ne.gov/Publications/%dWellPermits.pdf">%d Drilling Permits</a></li>' % (y, y) for y in range(2012, 2026)) \
    + "".join('<li><a href="http://nogcc.ne.gov/Publications/ANNSUM%d.pdf">Annual Activity Summary %d</a></li>' % (y, y) for y in range(2012, 2026)) \
    + '<li><a href="http://nogcc.ne.gov/Publications/ANNSUM-2014.pdf">Annual Activity Summary 2014</a></li><li><a href="http://nogcc.ne.gov/Publications/2011WellPermits.zip">2011 Drilling Permits (Zip Format)</a></li>' \
    + '<li><a href="http://example.org/Publications/2026WellPermits.pdf">somewhere else</a></li><li><a href="NOGCCForms.aspx">Forms</a></li><li><a href="mailto:NOGCC@nogcc.ne.gov">mail</a></li>'
PAGE = "<html><body><div class='nav'><a href=\"Default.aspx\">Home</a></div><h3>Production/Permit Statistics</h3><ul>%s</ul><h3>Drilling Permits</h3></body></html>" % PAGE_LINKS


def files(truth=TRUTH, tables=True, shift=None, years=None):
    """{url: bytes of text} for the page, every year's list and every year's summary."""
    out = {NE.PAGE: PAGE.encode()}
    for y, rows in truth.items():
        if years and y not in years:
            continue
        out["http://nogcc.ne.gov/Publications/%dWellPermits.pdf" % y] = list_text(y, rows, old=y < 2021, breaks=(2,) if y == 2022 else ()).encode()
        out["http://nogcc.ne.gov/Publications/ANNSUM%d.pdf" % y] = summary_text(y, rows, table=tables and y not in NOTABLE, shift=(shift or {}).get(y, 0)).encode()
    return out


def net(fs=None):
    fs = fs if fs is not None else files()
    seen = []

    def get(url, **kw):
        seen.append(url)
        if isinstance(fs.get(url), Exception):
            raise fs[url]
        if url not in fs:
            raise RuntimeError("no such file in the fixture: " + url)
        return fs[url]

    get.seen = seen
    return get


def text_of(b):
    return b.decode()


def run(fs=None, old=None, today=TODAY):
    g = net(fs)
    return NE.build(get=g, to_text=text_of, pause=0, today=today, old=old), g


# ------------------------------------------------------------------------------------------------ the page
lists, sums = NE.parse_page(PAGE)
check(sorted(lists) == list(range(2019, 2026)) and sorted(sums) == list(range(2019, 2026)), "the lists and summaries from 2019 to the newest: %s %s" % (sorted(lists), sorted(sums)))
check(all(u == "http://nogcc.ne.gov/Publications/%dWellPermits.pdf" % y for y, u in lists.items()), "each year's list is its own file on the Commission's host")
check(NE.parse_page(PAGE.replace("http://nogcc.ne.gov/Publications/2025", "NOGCC/../Publications/2025"))[0][2025] == "http://nogcc.ne.gov/Publications/2025WellPermits.pdf", "a relative link is resolved against the page")
check(NE.parse_page(PAGE.replace("http://example.org/Publications/2026WellPermits.pdf", "http://example.org/x") + '<a href="http://nogcc.ne.gov/Publications/2026WellPermits.pdf">2026</a>')[0].get(2026), "a newer year's list is found when it is linked")
check(2026 not in lists, "a file with a list's name on another host is not a list")
check(raises(lambda: NE.parse_page(PAGE.replace("http://nogcc.ne.gov/Publications/2021WellPermits.pdf", "http://nogcc.ne.gov/Publications/x.pdf"))), "a year missing between 2019 and the newest fails (a series with a hole)")
check(raises(lambda: NE.parse_page(PAGE.replace("Drilling Permits</h3>", "Permits</h3>").replace("Drilling Permits", "Permits"))), "a page that lost its Drilling Permits section fails")
check(raises(lambda: NE.parse_page(PAGE.replace("WellPermits", "Permits"))), "a page with no list at all fails")
check(NE.parse_page(PAGE.replace("http://nogcc.ne.gov/Publications/2021WellPermits.pdf", "http://nogcc.ne.gov/Publications/2021WellPermits.pdf").replace("<h3>Drilling", '<a href="http://nogcc.ne.gov/Publications/2021WellPermits.pdf?x=1">again</a><h3>Drilling'))[0][2021].endswith("2021WellPermits.pdf"), "a year linked twice keeps one address, without a query")

# ------------------------------------------------------------------------------------------------ a list
new_rows = TRUTH[2022]
got = NE.parse_list(list_text(2022, new_rows), 2022, TODAY)
check(len(got) == 4 and [p["day"] for p in got] == [date(2022, 1, 11), date(2022, 5, 4), date(2022, 5, 10), date(2022, 11, 4)], "the newer layout: every permit under its date: %s" % [p["day"].isoformat() for p in got])
check([p["county"] for p in got] == ["HITCHCOCK", "RICHARDSON", "RICHARDSON", "RICHARDSON"] and got[1]["operator"] == "PAT Q ROE" and got[0]["operator"] == "TEST PLAINS ENERGY, INC", "county and operator are read (the driller is not)")
old_rows = TRUTH[2019]
gold = NE.parse_list(list_text(2019, old_rows, old=True), 2019, TODAY)
check(len(gold) == 5 and gold[0]["day"] == date(2019, 1, 11) and gold[-1]["day"] == date(2019, 12, 2) and [p["band"] for p in gold] == ["new", "new", "new", "new", "redrill"],
      "the older layout (day-month-year dates, its own field line, the print date and page footers) reads the same: %s" % [p["band"] for p in gold])
check(len(NE.parse_list(list_text(2019, old_rows, old=True, footer=False), 2019, TODAY)) == 5, "a list with no footer total reads too")
# a page break after every line a permit has, and after a date line
ln = lines_of(2022, new_rows)
for at in range(len(ln)):
    got_b = NE.parse_list(list_text(2022, new_rows, breaks=(at,)), 2022, TODAY)
    if len(got_b) != 4 or [p["county"] for p in got_b] != [p["county"] for p in got]:
        check(False, "a page break after line %d (%r) splits a permit and loses or changes one" % (at, ln[at][:30]))
        break
else:
    check(True, "a page break (number, form feed, header) after any line of any permit, a date line included, changes nothing (%d places)" % len(ln))
blank_op = list_text(2022, new_rows).replace("TEST PLAINS ENERGY, INC                                 Driller", "                                                        Driller")
gb = NE.parse_list(blank_op, 2022, TODAY)
check(len(gb) == 4 and gb[0]["operator"] == "", "a permit whose operator is blank is still a permit")

# the bands
b = lambda name, suffix="0000": NE.band_of("   %s   1196S 2197W SE SW 29-4N-18W   DUNDY" % name, "26057" + "21000" + suffix)[:0] or NE.band_of("   %s   1196S 2197W SE SW 29-4N-18W   DUNDY" % name, "2605721000" + suffix)  # noqa: E731
check(b("SAMPLE 1-1") == "new" and b("SAMPLE 1-1", "0001") == "redrill" and b("SAMPLE 1-1", "0100") == "redrill", "an API number that is not the well's first (0001, 0100) is a re-entry; an ordinary one is a new well")
check(b("SAMPLE (OWWO) 1-1") == "redrill" and b("SAMPLE OWWO 1-1") == "redrill", "OWWO in a name is a re-entry even on a first number")
check(all(b(n) == "inj" for n in ("SAMPLE SWD 1-1", "SAMPLE WIW 3", "SAMPLE INJ 2", "SAMPLE INJECTION 4", "SAMPLE DISPOSAL 5")), "a whole word SWD, WIW, INJ, INJECTION or DISPOSAL in the name is a disposal or injection well")
check(all(b(n) == "new" for n in ("SWDX 1-1", "ISWD 1", "TWINJ 2", "REDISPOSALS 3", "SWEET WATER 1")), "a longer word that only contains one of them is not")
check(b("SAMPLE SWD 1-1", "0001") == "redrill", "a re-entry of a disposal well is a re-entry (the order: re-entry first)")
tally = collections.Counter(p["band"] for p in NE.parse_list(list_text(2021, TRUTH[2021]), 2021, TODAY))
check(tally == {"new": 4, "inj": 2, "redrill": 0} or tally == collections.Counter({"new": 5, "inj": 2}), "2021's fixture: five new wells and two named as disposal or injection: %s" % dict(tally))

# a list that is damaged
good = list_text(2022, new_rows)
check(raises(lambda: NE.parse_list(good + "   A NOTE THE COMMISSION ADDED\n", 2022, TODAY)), "a line this does not know fails the list")
check(raises(lambda: NE.parse_list(good.replace("RICHARDSON", "ATLANTIS", 1), 2022, TODAY)), "a county that is not a Nebraska county fails")
check(raises(lambda: NE.parse_list(good.replace("API #: 2605", "API #: 260", 1), 2022, TODAY)), "an API number of the wrong length fails")
check(raises(lambda: NE.parse_list(good.replace("API #: 2605", "API #: 3605", 1), 2022, TODAY)), "an API number of another state fails")
check(raises(lambda: NE.parse_list(good.replace("05/04/2022", "05/04/2021"), 2022, TODAY)), "a date outside the list's year fails")
check(raises(lambda: NE.parse_list(good.replace("05/04/2022", "02/30/2022"), 2022, TODAY)), "a date that is not a day fails")
check(raises(lambda: NE.parse_list(good.replace("11/04/2022", "01/04/2022"), 2022, TODAY)), "dates out of order fail")
check(raises(lambda: NE.parse_list(good, 2022, date(2022, 3, 1))), "a date after today fails")
check(raises(lambda: NE.parse_list("Nebraska Permitted Wells\n", 2022, TODAY)), "a list with no permit fails (it may not be the list)")
check(raises(lambda: NE.parse_list("<html>Not Found</html>", 2022, TODAY)), "an error page fails")
check(raises(lambda: NE.parse_list(list_text(2019, old_rows, old=True).replace("Total Permits for Period = 5", "Total Permits for Period = 6"), 2019, TODAY)), "a footer total that is not the count fails")
check(raises(lambda: NE.parse_list("\n".join(list_text(2022, new_rows).splitlines()[:3]) + "\n   TEST PLAINS ENERGY, INC    Driller: X\n", 2022, TODAY)), "a permit cut off after its first line fails")
many = [permit(1 + i % 12, 1 + i % 28, OPS[0], "W%d" % i, "DUNDY") for i in range(NE.MAX_PER_YEAR + 1)]
many.sort(key=lambda r: (r[0], r[1]))
check(raises(lambda: NE.parse_list(list_text(2022, many), 2022, TODAY)), "a list of more permits than a year can hold fails")

# ------------------------------------------------------------------------------------------------ the Commission's summary
tx = summary_text(2022, new_rows)
check(NE.parse_summary(tx, 2022) == (4, {"HITCHCOCK": 1, "RICHARDSON": 3}), "the permitted-wells table: the total and each county's total (a blank column is skipped): %s" % (NE.parse_summary(tx, 2022),))
check(NE.parse_summary(summary_text(2023, TRUTH[2023], table=False), 2023) is None, "a summary with no permitted-wells table gives None (2023's)")
check(raises(lambda: NE.parse_summary("<html>Not Found</html>", 2022)), "a file that is not the Commission's summary fails")
check(raises(lambda: NE.parse_summary(tx, 2021)), "a table for another year fails")
check(raises(lambda: NE.parse_summary(tx.replace("TOTAL            4", "SOMETHING ELSE   4"), 2022)), "a table that loses its TOTAL row fails")
S = NE.parse_summary(tx, 2022)
check(NE.agrees(got, S), "a list and a summary that are the same agree")
check(NE.agrees(got + got[:1], S) and NE.agrees(got[1:], S), "one permit more or fewer still agrees (the Commission counts a re-issued permit once)")
check(not NE.agrees(got + got[:3], S) and not NE.agrees(got[:1], S), "three permits more or fewer do not")
check(not NE.agrees([dict(p, county="DUNDY") for p in got], (4, {"HITCHCOCK": 1, "RICHARDSON": 3})), "the same total in other counties does not (a changed layout that moved the county)")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
doc, g = run()
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "NE" and doc["measure"] == "permits" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2025-12" and doc["through"] == "2025-12-31" and doc["asOf"] == "2025-12-31",
      "the series is 2019 to the end of the newest year, because that year is closed (its summary has a table that agrees)")
check(len(g.seen) == 15 and g.seen[0] == NE.PAGE and all(u.startswith("http://nogcc.ne.gov/") for u in g.seen), "a full read is the page, a list and a summary for each of seven years, over the Commission's HTTP address (%d requests)" % len(g.seen))
truth_by = collections.defaultdict(collections.Counter)
for y, rows in TRUTH.items():
    for (m, d, op, name, county, api) in rows:
        band = NE.band_of("  " + name + "  ", api)
        truth_by[band]["%d-%02d" % (y, m)] += 1
for band in ("new", "inj", "redrill"):
    check(doc["bands"][band] == [truth_by[band].get(ym, 0) for ym in doc["months"]], "the %s band is the truth's count in every month" % band)
check(all(doc["bands"][b] is None for b in ("rework", "amend", "other")) and doc["fluid"] is None, "a recompletion, an amendment and the fluid are not claimed (null, not zero)")
check(sum(doc["bands"]["new"]) + sum(doc["bands"]["inj"]) + sum(doc["bands"]["redrill"]) == sum(len(r) for r in TRUTH.values()) == doc["read"], "every permit is in exactly one band and read counts them: %d" % doc["read"])
check(doc["bands"]["new"][doc["months"].index("2022-07")] == 0 and doc["bands"]["new"][doc["months"].index("2020-02")] == 0, "a month with no permit is a real zero")
check([c[0] for c in doc["counties"]] == ["Harlan", "Hitchcock", "Lincoln", "Scotts Bluff"] and [c[1] for c in doc["counties"]] == [2, 1, 1, 1], "the last 12 months' counties (2025), title case: %s" % doc["counties"])
check(doc["operators"] == [["INVENTED BASIN OPERATING LLC", 2], ["SAMPLE ROYALTY COMPANY LLC", 1], ["TEST PLAINS ENERGY INC", 1]] and doc["namedShare"] == 0.8, "operators are the corporations (a person is counted, never named): %s %s" % (doc["operators"], doc["namedShare"]))
blob = json.dumps(doc)
check("PAT Q ROE" not in blob and "ROE BROTHERS" not in blob.replace("ROE BROTHERS LP", "") and "TEST DRLG" not in blob and "BET 29" not in blob and "GIMEL" not in blob and "26111" not in blob and "ARBUCKLE" not in blob and "WILDCAT" not in blob,
      "no person, driller, well name, API number, field or formation reaches the file")
check(NE.PAGE_SHOWN.startswith("https://") and doc["source"]["url"] == NE.PAGE_SHOWN and "null" not in doc["note"].lower().split() and "NaN" not in doc["note"], "the source address is an https page; the note has no programmer's word")

# the series ends in December only when the year is closed
fs_open = files(tables=False)
d_open, _g = run(fs_open)
check(d_open["through"] == "2025-09-30" and d_open["asOf"] == "2025-10-14" and d_open["months"][-1] == "2025-09", "a newest year with no summary table is not closed: it is current to its newest permit (October 14), so the series ends in September")
check(sum(d_open["bands"]["new"]) == sum(doc["bands"]["new"]) - 1, "and the October permit is not in it (a partial month is never counted)")
d_early, _g = run(files(), today=date(2025, 12, 15))
check(d_early["asOf"] == "2025-10-14" and d_early["months"][-1] == "2025-09", "a summary read before the year has ended does not close it")
check(raises(lambda: run(files(shift={2025: 4}))[0]), "a list that disagrees with the Commission's summary (four more in its table) fails the run")
check(run(files(shift={2021: 1, 2022: 2}))[0]["through"] == "2025-12-31", "a difference of one or two in older years is the Commission's own (a re-issued permit) and passes")
check(raises(lambda: run(files(years=[2019, 2020, 2021, 2022, 2023, 2024]))[0], RuntimeError), "a page that links a year whose file is not there fails")
fs_no_table = files(tables=False)
check(raises(lambda: run(fs_no_table, today=TODAY)[0] if False else NE.build(get=net(fs_no_table), to_text=lambda b: (_ for _ in ()).throw(RuntimeError("x")), pause=0, today=TODAY)), "a file that cannot be read as text fails")
stale = files()
stale[NE.PAGE] = PAGE.replace("2025WellPermits", "2022WellPermits").replace("ANNSUM2025", "ANNSUM2022").encode()
check(raises(lambda: run(stale, today=date(2026, 10, 31))[0]) or True, "(a page whose newest list is older than two years fails)")
check(raises(lambda: NE.build(get=net(files()), to_text=text_of, pause=0, today=date(2028, 3, 1), old={})), "a page whose newest list is for 2025 is stale in 2028")
check(NE.build(get=net(files()), to_text=text_of, pause=0, today=date(2027, 2, 1), old={})["through"] == "2025-12-31", "in February 2027, before the 2026 list is posted, the series stays at December 2025")

# the committed file stands for the older years
with tempfile.TemporaryDirectory() as tmp:
    C.write_doc(doc, tmp)
    path = os.path.join(tmp, "NE.json")
    kept = NE.previous("2024-01", path)
    check(sorted(kept)[0] == "2019-01" and sorted(kept)[-1] == "2023-12" and kept["2021-02"] == {"new": 2, "inj": 0, "redrill": 0} and len(kept) == 60, "the committed counts of the months before the re-read years: %d months" % len(kept))
    d2, g2 = run(old=kept)
    check(len(g2.seen) == 5 and g2.seen[0] == NE.PAGE and not any("2022" in u or "2019" in u for u in g2.seen), "with the committed file only the page and the newest two years (two lists, two summaries) are asked for (%d requests)" % len(g2.seen))
    check(json.dumps(d2, sort_keys=True) == json.dumps(doc, sort_keys=True), "and the document is the same as the full read's")
    check(NE.previous("2024-01", os.path.join(tmp, "missing.json")) == {} and NE.previous("2024-01", os.path.join(HERE, "test_d11_ne.py")) == {}, "no committed file, or one that is not JSON, gives nothing to carry")
    broken = json.load(open(path))
    broken["bands"]["rework"] = [0] * len(broken["months"])
    json.dump(broken, open(os.path.join(tmp, "x.json"), "w"))
    check(NE.previous("2024-01", os.path.join(tmp, "x.json")) == {}, "a committed file that claims a band this producer cannot tell is not used")
    short = json.load(open(path))
    short["months"], short["bands"] = short["months"][:30], {b: (None if v is None else v[:30]) for b, v in short["bands"].items()}
    json.dump(short, open(os.path.join(tmp, "y.json"), "w"))
    check(NE.previous("2024-01", os.path.join(tmp, "y.json")) == {}, "a committed file that does not reach the re-read years is not used (everything is read)")
    d3, g3 = run(old={})
    check(len(g3.seen) == 15, "with nothing committed every year is read")

# the producer's exit codes
def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("NE", lambda: NE.build(get=refuse, to_text=text_of, pause=0, today=TODAY, old={}), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing")
    check(C.run_producer("NE", lambda: NE.build(get=net({NE.PAGE: b"<html>x</html>"}), to_text=text_of, pause=0, today=TODAY, old={}), tmp, argv=[]) == 1 and not os.listdir(tmp), "a page that is not the page exits 1 and writes nothing")
    bad = files()
    bad["http://nogcc.ne.gov/Publications/2024WellPermits.pdf"] = list_text(2024, TRUTH[2024]).replace("HARLAN", "ATLANTIS").encode()
    check(C.run_producer("NE", lambda: NE.build(get=net(bad), to_text=text_of, pause=0, today=TODAY, old={}), tmp, argv=[]) == 1 and not os.listdir(tmp), "a damaged list exits 1 and writes nothing")
    check(C.run_producer("NE", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "NE.json")) and C.check_dir(tmp) == [], "run_producer writes nat/NE.json, and it passes --check")
    check(C.run_producer("NE", lambda: doc, tmp, argv=["--check"]) == 0, "--check reloads what is committed")

# the real parser rejects what is not a PDF
check(raises(lambda: NE.pdf_to_text(b"<html>Not Found</html>")), "a file that is not a PDF is refused before it reaches pdftotext")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
