"""Tests for site/pipeline/d11_nat_nv.py: Nevada's oil and gas permits (Division of Minerals) from the links on its Permits page.

The fixtures are an invented page built the way the real one is (a heading, a sentence saying the current year and five before it are shown, one heading per year that has permits, a list of links into
the permits folder whose text is "Oil <number> <date> <company> <well>", dates with and without leading zeros, one link text with ".pdf" and one without, a menu and other links around them) and an
invented layer reply. They pin: the links' text and dates, a permit counted once, the years with no permit as real zeros, the months that dropped off the page kept from the committed file (and never
turned into zeros), the 30-day lag, the layer cross-check (permit numbers above the newest on the page, numbers missing between them) and that a layer that fails costs only a sentence, that nothing but
a count (no company, well name or permit number) reaches the output, and that a page that changed (no heading, a link that cannot be read, a date that is not a day or disagrees with its heading, a
count of PDFs that differs from the count of lists) fails the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_nv.py"""
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_nv as NV  # noqa: E402

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


MENU = '<ul><li class=" py-1"><a class="x" href="/programs/oil-gas/forms-and-reports/">Forms and Reports</a></li><li><a href="/programs/oil-gas/for-public/">For Public</a></li></ul>'
INTRO = '<h2>Permits and Permit Notices</h2><p>The current calendar year and previous five years are displayed.&nbsp; For older permits, please ask the program manager.</p>'


def link(text, name=None):
    name = name or text.lower().replace(" ", "-")
    return '<li><a title="%s.pdf" href="/siteassets/content/programs/og/ogpermits/%s.pdf">%s</a></li>' % (text, name, text)


def year(y, *texts):
    return '<div><h2>%d</h2><ul>%s</ul></div>' % (y, "".join(link(t) for t in texts))


def page(*years, intro=INTRO, extra=""):
    return "<html><body><nav>%s</nav>%s%s%s</body></html>" % (MENU, intro, "".join(years), extra)


PAGE = page(year(2026, "OIL 0907 04-29-2026 Invented Basin Operating LLC North Test Valley.pdf", "Oil 0906 2-26-2026 Sample Royalty Company LLC Trap Test 11-42"),
            year(2023, "Oil 0905 02-14-2023 Pat Q Roe Soda Test 1-22", "Oil 0904 02-14-2023 Pat Q Roe North Test Canyon 1-8"),
            year(2022, "Oil 0903 07-15-2022 Invented Basin Operating North Test Valley 1-27"),
            year(2021, "Oil 0902 07-20-2021 Test Canyon ThreeBar6R"))
FEATURES = [{"attributes": {"OBJECTID": i, "Permit": "    %04d" % (800 + i)}} for i in range(1, 100)] + [{"attributes": {"OBJECTID": 200, "Permit": "     GSR"}}] + [{"attributes": {"OBJECTID": 300 + n, "Permit": "    %04d" % n}} for n in (902, 903, 904, 906, 907)]
LAYER = json.dumps({"objectIdFieldName": "OBJECTID", "features": FEATURES}).encode()


def net(pg=PAGE, layer=LAYER):
    seen = []

    def get(url, **kw):
        seen.append(url)
        if url == NV.PAGE:
            return pg.encode() if isinstance(pg, str) else pg
        if isinstance(layer, Exception):
            raise layer
        return layer

    get.seen = seen
    return get


# ------------------------------------------------------------------------------------------------ the page
got = NV.parse_page(PAGE, TODAY)
check(got == [(902, date(2021, 7, 20)), (903, date(2022, 7, 15)), (904, date(2023, 2, 14)), (905, date(2023, 2, 14)), (906, date(2026, 2, 26)), (907, date(2026, 4, 29))],
      "every permit link is read: number and approval date (two-digit and one-digit months, with and without .pdf in the text): %s" % got)
check(NV.parse_page(page(year(2026, "Oil 0907 04-29-2026 Dupe Co LLC A", "Oil 0907 4/29/2026 Dupe Co LLC A again")), TODAY) == [(907, date(2026, 4, 29))], "a permit listed twice counts once (and a slash date reads)")
check(NV.parse_page(page(year(2026, "Geothermal 0908 03-01-2026 Invented Heat LLC Well 1", "Oil 0907 04-29-2026 Invented Basin Operating LLC A")), TODAY) == [(907, date(2026, 4, 29))], "a permit of another kind (geothermal) is read but not counted as an oil or gas permit")
check(NV.parse_page(page(intro=INTRO + "<p>No permits this year.</p>"), TODAY) == [], "a page that says what it shows and lists no permit is an empty list, not an error")
check(raises(lambda: NV.parse_page(page(year(2026, "Oil 0907 04-29-2026 A LLC B"), intro="<h2>Something else</h2>"), TODAY)), "a page that lost its heading fails")
check(raises(lambda: NV.parse_page(page(intro="<h2>Permits and Permit Notices</h2><p>Coming soon.</p>"), TODAY)), "a page with no permit and no statement of the years it shows fails (its layout may have changed)")
check(raises(lambda: NV.parse_page(page(year(2026, "Oil 0907 04-29-2026 A LLC B", "Permit 907 notice of intent")), TODAY)), "a permit link whose text cannot be read fails")
check(raises(lambda: NV.parse_page(page(year(2026, "Oil 0907 02-30-2026 A LLC B")), TODAY)), "a date that is not a day fails")
check(raises(lambda: NV.parse_page(page(year(2026, "Oil 0907 12-30-2026 A LLC B")), TODAY)), "a date in the future fails")
check(raises(lambda: NV.parse_page(page(year(2025, "Oil 0907 04-29-2026 A LLC B")), TODAY)), "a date that disagrees with its year's heading fails")
check(raises(lambda: NV.parse_page(page(extra=link("Oil 0907 04-29-2026 A LLC B")), TODAY)), "a permit link outside any year's heading fails")
tablepage = page(year(2026, "Oil 0907 04-29-2026 A LLC B")) + '<table><tr><td><a href="/siteassets/content/programs/og/ogpermits/oil-0910.pdf">Oil 0910 05-29-2026 C LLC D</a></td></tr></table>'
check(raises(lambda: NV.parse_page(tablepage, TODAY)), "a PDF link in the permits folder that is not in a list (the layout moved) fails: the count of PDFs differs from the count of lists")
check(NV.layer_numbers(LAYER)[-3:] == [904, 906, 907] and len(NV.layer_numbers(LAYER)) > 100 and NV.layer_numbers(b"<html>") is None and NV.layer_numbers(b'{"features": []}') is None
      and NV.layer_numbers(json.dumps({"features": FEATURES, "exceededTransferLimit": True}).encode()) is None, "the layer's permit numbers (a letter code is not one); a reply that is not the layer, is empty or was cut at its limit gives None")

# ------------------------------------------------------------------------------------------------ the producer, with the network faked
doc = NV.build(get=net(), old={}, today=TODAY)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "NV" and doc["measure"] == "permits" and doc["basis"] == "approval date" and doc["months"][0] == "2021-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-31",
      "the page's six years, to the last complete month before the 30-day lag")
by = dict(zip(doc["months"], doc["bands"]["new"]))
check({m: n for m, n in by.items() if n} == {"2021-07": 1, "2022-07": 1, "2023-02": 2, "2026-02": 1, "2026-04": 1} and sum(by.values()) == 6, "each permit is in its approval month, two in one month make 2, and every other month is a real zero")
check(by["2024-06"] == 0 and by["2025-10"] == 0 and sum(doc["bands"]["new"][-12:]) == 2, "the years with no permit are zeros, and the last 12 months hold 2")
check(all(doc["bands"][b] is None for b in ("inj", "redrill", "rework", "amend", "other")) and doc["fluid"] is None, "no other kind of permit and no fluid is claimed (null, not zero)")
check(doc["operators"] == [] and doc["counties"] == [] and doc["namedShare"] is None, "no operator and no county is read: the company is part of free text")
text = json.dumps(doc)
check("Invented" not in text and "Roe" not in text and "Royalty" not in text and "Valley" not in text and "0906" not in text and "ThreeBar" not in text, "nothing from a title (company, person, well, permit number) reaches the file")
check("zeroOk" not in doc and "above the newest" not in doc["note"] and "between the first and last" not in doc["note"], "with permits in the last 24 months there is no zeroOk, and the layer finds nothing to add")
check(len(NV.parse_page(PAGE, TODAY)) == doc["read"], "read counts the permits")

# the lag: a month is shown only when it ended 30 days before the read
d2 = NV.build(get=net(), old={}, today=date(2026, 10, 20))
check(d2["through"] == "2026-08-31" and d2["months"][-1] == "2026-08", "read on October 20, September is not shown yet (it ended less than 30 days before)")
d3 = NV.build(get=net(), old={}, today=date(2026, 10, 30))
check(d3["through"] == "2026-09-30", "read on October 30, September is shown")

# permit numbers: one missing between the first and last on the page, and one above the newest (in the layer)
holey = page(year(2026, "Oil 0910 04-29-2026 Invented Basin Operating LLC A", "Oil 0907 02-26-2026 Sample Royalty Company LLC B"))
dh = NV.build(get=net(holey), old={}, today=TODAY)
check("2 permit numbers between the first and last on the page are not listed there and are not counted" in dh["note"], "two numbers missing between the page's first and last are said, and not counted")
above = json.dumps({"features": FEATURES + [{"attributes": {"Permit": "    0908"}}, {"attributes": {"Permit": "    0909"}}]}).encode()
da = NV.build(get=net(layer=above), old={}, today=TODAY)
check("holds 2 permit numbers above the newest on the page; they have no date here and are not counted" in da["note"] and da["bands"]["new"] == doc["bands"]["new"], "two layer permits above the newest on the page are said in the note and not counted")
for label, bad in (("a failed request", RuntimeError("could not read the source")), ("a timeout", OSError("timed out"))):
    dl = NV.build(get=net(layer=bad), old={}, today=TODAY)
    check(dl["bands"] == doc["bands"] and C.validate(dl, TODAY) == [], "the layer's failure (%s) costs only the note's sentence" % label)
check(NV.build(get=net(layer=b"<html>not the layer</html>"), old={}, today=TODAY)["bands"] == doc["bands"], "a layer reply that is not the layer is ignored too")
check(raises(lambda: NV.build(get=net(layer=C.Refused("HTTP 403")), old={}, today=TODAY), C.Refused), "but a refusal is an answer: it still ends the run")

# six years later the first of them has left the page: its months come from the committed file
old = dict(zip(doc["months"], doc["bands"]["new"]))
page27 = page(year(2026, "OIL 0907 04-29-2026 Invented Basin Operating LLC North Test Valley", "Oil 0906 2-26-2026 Sample Royalty Company LLC Trap Test 11-42"), year(2023, "Oil 0905 02-14-2023 Pat Q Roe Soda Test 1-22", "Oil 0904 02-14-2023 Pat Q Roe North Test Canyon 1-8"),
              year(2022, "Oil 0903 07-15-2022 Invented Basin Operating North Test Valley 1-27"), year(2027, "Oil 0908 01-12-2027 Invented Basin Operating LLC New"))
d27 = NV.build(get=net(page27), old=old, today=date(2027, 3, 31))
b27 = dict(zip(d27["months"], d27["bands"]["new"]))
check(d27["months"][0] == "2021-01" and b27["2021-07"] == 1 and b27["2022-07"] == 1 and b27["2027-01"] == 1 and sum(b27.values()) == 7 and d27["through"] == "2027-02-28" and C.validate(d27, date(2027, 3, 31)) == [],
      "2021's permit is gone from the page but stays in the series (the committed month), and 2027's is added: 7 in all")
check(raises(lambda: NV.build(get=net(page27), old={}, today=date(2027, 3, 31))) is False and NV.build(get=net(page27), old={}, today=date(2027, 3, 31))["months"][0] == "2022-01",
      "with nothing committed the series starts at the first month the page can show (2022-01), not earlier: no zero is invented for 2021")
upto = {m: n for m, n in old.items() if m <= "2021-12"}
check(NV.build(get=net(page27), old=upto, today=date(2027, 3, 31))["months"][0] == "2021-01", "a committed file that reaches the month before the window (2021-12) is enough: its months are kept")
short = {m: n for m, n in old.items() if m <= "2021-10"}
check(NV.build(get=net(page27), old=short, today=date(2027, 3, 31))["months"][0] == "2022-01", "one that stops earlier would leave a gap, so it is not used: the series starts at the window")
gone = {m: n for m, n in old.items() if m >= "2023-01"}
check(NV.build(get=net(page27), old=gone, today=date(2027, 3, 31))["months"][0] == "2022-01", "a committed file with a hole before the window is not trusted")

# a state with no permit for two years says so (zeroOk) only then
quiet_page = page(year(2022, "Oil 0903 07-15-2022 Invented Basin Operating North Test Valley 1-27"))
dq = NV.build(get=net(quiet_page), old={}, today=date(2027, 8, 1))
check(sum(dq["bands"]["new"][-24:]) == 0 and dq.get("zeroOk") is True and C.validate(dq, date(2027, 8, 1)) == [] and dq["months"][0] == "2022-01", "two years with no permit are real zeros, and the file says zeroOk")
check(raises(lambda: NV.build(get=net(page(intro=INTRO)), old={}, today=TODAY)), "a page with no permit and nothing committed fails")
check(raises(lambda: NV.build(get=net(b"<html>Access denied</html>"), old={}, today=TODAY)), "a page of something else fails")

# the producer's exit codes and the committed file
def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("NV", lambda: NV.build(get=refuse, old={}, today=TODAY), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing")
    check(C.run_producer("NV", lambda: NV.build(get=net(b"<html>x</html>"), old={}, today=TODAY), tmp, argv=[]) == 1 and not os.listdir(tmp), "a failure exits 1 and writes nothing")
    check(C.run_producer("NV", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "NV.json")), "run_producer writes nat/NV.json for it")
    check(NV.previous(os.path.join(tmp, "NV.json")) == old and C.check_dir(tmp) == [], "the written file reloads as the committed counts and passes --check")
    check(NV.previous(os.path.join(tmp, "missing.json")) == {} and NV.previous(os.path.join(HERE, "test_d11_nv.py")) == {}, "no committed file, or one that is not JSON, gives nothing to carry")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
