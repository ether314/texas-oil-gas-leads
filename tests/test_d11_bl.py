"""Tests for site/pipeline/d11_nat_bl.py: the BLM's onshore permits (APDs approved, by BLM state office) from its monthly status-report PDFs.

Real report text from three eras of the BLM's layout (April 2021, September 2023, September 2026: kept in tests/fixtures/bl, the output of pdftotext -layout) pins the parser: which column is
"approved" in each layout, that the first table (the month) is read and not the fiscal-year table below it, and that a fiscal-year or two-month report is not a month. The producer runs end to
end with the network and pdftotext faked: a gap in the months ends the series that is shown, a missing month is never a zero, months older than the window are not downloaded again, a page whose
layout changed or reports that cannot be read fail the run instead of writing a short file, and what is written validates.

Run: python3 -I tests/test_d11_bl.py"""
import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_bl as BL  # noqa: E402
import d11_nat_common as C  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


fx = lambda n: open(os.path.join(HERE, "fixtures", "bl", n + ".txt"), encoding="utf-8").read()  # noqa: E731

# ------------------------------------------------------------------------------------------------ the parser, on real report text
m, rows = BL.parse_report(fx("apd_apr2021"))
check(m == "2021-04" and rows == {"Alaska": 0, "California": 7, "Colorado": 0, "Eastern States": 7, "Montana": 45, "Nevada": 0, "New Mexico": 456, "Utah": 28, "Wyoming": 128} and sum(rows.values()) == 671,
      "April 2021 (the old layout: Received, Approved, Processed...): the approved column, and the sum is the report's own total, 671")
m, rows = BL.parse_report(fx("apd_sep2023"))
check(m == "2023-09" and rows["New Mexico"] == 163 and rows["Montana"] == 40 and rows["Wyoming"] == 117 and sum(rows.values()) == 364, "September 2023 (Received, Pending, Processed, Approved): the approved column, the sum is the report's own 364")
m, rows = BL.parse_report(fx("apd_sep2026"))
check(m == "2026-09" and rows["Utah"] == 148 and rows["Wyoming"] == 38 and rows["Colorado"] == 3 and sum(rows.values()) == 369, "September 2026: the approved column, the sum is the report's own 369")
fy = fx("apd_apr2021").replace("4/1/2021 to 4/30/2021", "10/1/2020 to 4/30/2021")
check(BL.parse_report(fy) is None and BL.parse_report("nothing to see here") is None and BL.parse_report("") is None, "a fiscal-year report, a text with no period and an empty text are not months")
check(BL.parse_report(fx("apd_sep2023").replace("9/1/2023 to 9/30/2023", "8/1/2023 to 9/30/2023")) is None, "a two-month report is not a month")
few = "\n".join(l for l in fx("apd_sep2026").splitlines() if not l.strip().startswith(("Alaska", "California", "Colorado", "Eastern", "Montana", "Nevada")))
check(BL.parse_report(few) is None, "a table with fewer than six offices is refused, not read short")
check(BL.last_run(["2022-08", "2022-09", "2022-12", "2023-01"]) == "2022-12" and BL.last_run(["2021-04", "2021-05"]) == "2021-04" and BL.last_run(["2026-09"]) == "2026-09", "the shown series starts after the last gap")

# ------------------------------------------------------------------------------------------------ the producer, with the network and pdftotext faked
MONTHS = C.month_list("2021-04", "2026-09")


def report_text(ym, k=1):
    y, mo = int(ym[:4]), int(ym[5:])
    last = C.month_end(ym).day
    rowsx = "\n".join("%-16s %6d %6d %6d %6d %6d" % (o, 5, 10, 5, (i + 1) * k, 99) for i, o in enumerate(BL.OFFICES))
    return "FY %d Application for Permit to Drill Status Report:\n  %d/1/%d to %d/%d/%d\n State Office  APDs Received (A)  APDs Pending (B)  APDs Processed (C)  APDs Approved (D)  (E)\n%s\nTotal 1 2 3 4 5\n" % (y, mo, y, mo, last, y, rowsx)


def page(months, extra=()):
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    hrefs = ['<a href="/sites/default/files/docs/%s/BLM-Application-for-Permit-to-Drill-Status-Report-%s-%s.pdf">r</a>' % (ym, names[int(ym[5:]) - 1], ym[:4]) for ym in months]
    return "<html>" + "".join(hrefs) + "".join(extra) + "</html>"


class Net:
    def __init__(self, months):
        self.months = months
        self.fetched = []

    def get(self, url, **kw):
        if url == BL.PAGE:
            return page(self.months).encode()
        self.fetched.append(url)
        return url.encode()  # the "pdf": its own address, which the fake pdftotext turns back into a report

    def to_text(self, data):
        u = data.decode()
        names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        mo = next(i for i, n in enumerate(names) if "-%s-" % n in u) + 1
        yr = int(u.split("-")[-1][:4])
        return report_text("%04d-%02d" % (yr, mo))


net = Net(MONTHS)
doc = BL.build(get=net.get, to_text=net.to_text, pause=0, old={}, today=date(2026, 10, 20))
check(C.validate(doc, date(2026, 10, 31)) == [], "what it writes validates: %s" % C.validate(doc, date(2026, 10, 31))[:2])
check(doc["state"] == "BL" and doc["measure"] == "permits" and doc["months"][0] == "2021-04" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30", "from April 2021 to the newest month, complete months only")
check(all(v == sum(range(1, 10)) for v in doc["bands"]["new"]) and doc["bands"]["inj"] is None and doc["bands"]["amend"] is None, "the series is APDs approved by month (45 a month in the fake), and no other kind is claimed")
check(doc["operators"] == [] and doc["namedShare"] is None, "it names no operator, and says nothing about a share")
check(doc["counties"][0][0] == "Wyoming" and {c[0] for c in doc["counties"]} == {o for o in BL.OFFICES}, "the places are the BLM state offices, ranked")
check("never added to the states" in doc["note"] and "not a state" in doc["note"], "the note says an office is not a state and that the line is never added to the states")
check(len(net.fetched) == len(MONTHS), "with nothing committed every month's report is fetched once (%d)" % len(net.fetched))

# months older than the window are not downloaded again
net2 = Net(MONTHS)
old = dict(zip(doc["months"], doc["bands"]["new"]))
doc2 = BL.build(get=net2.get, to_text=net2.to_text, pause=0, old=old, today=date(2026, 10, 20))
check(len(net2.fetched) <= BL.REREAD + 2 and doc2["bands"]["new"] == doc["bands"]["new"], "with the earlier months committed only the last %d are fetched again (%d), and the series is the same" % (BL.REREAD, len(net2.fetched)))

# a gap ends the series that is shown: the BLM did not link October and November 2022
gappy = [ym for ym in MONTHS if ym not in ("2022-10", "2022-11")]
net3 = Net(gappy)
doc3 = BL.build(get=net3.get, to_text=net3.to_text, pause=0, old={}, today=date(2026, 10, 20))
check(doc3["months"][0] == "2022-12" and len(doc3["months"]) == len(C.month_list("2022-12", "2026-09")) and C.validate(doc3, date(2026, 10, 31)) == [], "a gap in the published months starts the shown series after it: no zero is invented for a month with no report")
check("2022-12" in doc3["note"], "and the note says where the series starts")

# failures fail the run; they never write a short file
def boom(kind):
    n = Net(MONTHS)
    try:
        if kind == "page":
            BL.build(get=lambda url, **kw: b"<html>no reports here</html>" if url == BL.PAGE else n.get(url), to_text=n.to_text, pause=0, old={})
        elif kind == "pdfs":
            BL.build(get=n.get, to_text=lambda data: "garbage", pause=0, old={})
        elif kind == "late":
            BL.build(get=Net(C.month_list("2025-01", "2026-09")).get, to_text=n.to_text, pause=0, old={})
        elif kind == "tool":
            def nope(data):
                raise RuntimeError("pdftotext (poppler-utils) is not installed")
            BL.build(get=n.get, to_text=nope, pause=0, old={})
        return False
    except RuntimeError:
        return True


check(boom("page"), "a page that lists no reports fails the run (its layout may have changed)")
check(boom("pdfs"), "reports that cannot be read fail the run")
check(boom("late"), "too few months fail the run")
check(boom("tool"), "a missing pdftotext fails the run, loudly")
with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("BL", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "BL.json")), "run_producer writes nat/BL.json for it")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
