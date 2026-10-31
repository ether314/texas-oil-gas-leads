"""Tests for the month-safe permit coverage of d7_daily.py (body month, month-end files, the ledger only goes up).

Run: python3 -I tests/test_d7_month_safe.py"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
REPO = _os.path.dirname(_HERE)
PIPE = _os.path.join(REPO, "site", "pipeline")

import importlib.util
import io
import sys
import types
from contextlib import redirect_stdout
from datetime import date, timedelta

spec = importlib.util.spec_from_file_location("d7", _os.path.join(PIPE, "d7_daily.py"))
d7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d7)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ---- synthetic Daily Files: {permit number: record}
def perm(n, d, typ="01", horizontal=False):
    return {"n": n, "issued": d, "type": typ, "horizontal": horizontal}


def business_days(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def month_file(first, last, per_day, start=1000):
    """Complete permits for each business day of [first, last], per_day each."""
    out, n = {}, start
    for d in business_days(first, last):
        for _ in range(per_day):
            out[str(n)] = perm(str(n), d)
            n += 1
    return out


def stragglers(spec_list, start=900000):
    """[(date, how many)] earlier permits that had activity this month."""
    out, n = {}, start
    for d, k in spec_list:
        for _ in range(k):
            out[str(n)] = perm(str(n), d)
            n += 1
    return out


OCT = month_file(date(2026, 10, 1), date(2026, 10, 30), 30)  # complete October (the month-end file)
SEP = month_file(date(2026, 9, 1), date(2026, 9, 30), 28, start=5000)
AUG = month_file(date(2026, 8, 3), date(2026, 8, 31), 27, start=7000)
JUL = month_file(date(2026, 7, 1), date(2026, 7, 31), 26, start=9000)


# ---- fake share layer
class World:
    def __init__(self, plain, eom):
        self.plain, self.eom = plain, eom  # plain: perms dict; eom: {'daf420.dat.10-31-2026': perms}
        self.eom_opened = 0
        self.logs = []


W = None


class FakeShare:
    def __init__(self, guid, sess=None):
        self.guid, self.total = guid, 1234
        self.s = types.SimpleNamespace(retries=0)

    def open(self):
        if self.guid == d7.EOM_GUID:
            W.eom_opened += 1

    def newest(self, n):
        if self.guid == d7.EOM_GUID:
            return [{"name": k, "modified": "2026-01-01T00:00:00", "bytes": 1} for k in W.eom]
        return [{"name": "daf420.dat", "modified": "2026-10-30T09:45:28", "bytes": 1}]

    def download(self, name, dest):
        return "EOM|" + name if self.guid == d7.EOM_GUID else "PLAIN|" + name


def fake_read_daf(path):
    kind, name = path.split("|", 1)
    return dict(W.plain if kind == "PLAIN" else W.eom[name])


d7.Share = FakeShare
d7.Session = lambda *a, **k: types.SimpleNamespace(retries=0)
d7.read_daf = fake_read_daf
d7.log = lambda m: W.logs.append(m)


def run(plain, eom, R, today, dates=None):
    global W
    W = World(plain, eom)
    ctx = {"R": R, "today": today, "dates": dates or [R], "dl": "/nowhere", "guid": {"permits": "PLAIN"}}
    return d7.permits_job(ctx)


def newest_day(pj, R):
    """What build_reports would pick as the permits day."""
    covered = lambda d: any(a <= d <= b for a, b in pj["covered"])  # noqa: E731
    days = sorted(d for d, n in pj["series"].items() if n[0] > 0 and d < R and covered(d))
    return days[-1] if days and (R - days[-1]).days <= 10 else None


def merged(*parts):
    out = {}
    for p in parts:
        out.update(p)
    return out


# T1 body_month
today = date(2026, 10, 31)
f = merged(month_file(date(2026, 10, 1), date(2026, 10, 29), 30), stragglers([(date(2026, 9, 14), 3), (date(2026, 8, 20), 2), (date(2015, 2, 24), 1)]))
f["99"] = perm("99", date(2062, 5, 1))  # a typo year must not become the body month
check(d7.body_month(f, today) == (2026, 10), "body_month: October body, stragglers and a typo year ignored")
check(d7.body_month(stragglers([(date(2026, 10, 27), 2), (date(2026, 9, 3), 4)]), date(2026, 11, 1)) == (2026, 10),
      "body_month: an empty new month shows the stragglers' month, which is why the report's own month must match")
check(d7.body_month({}, today) is None, "body_month: empty file")
check(d7.months_between((2026, 11), (2027, 2)) == [(2026, 11), (2026, 12), (2027, 1), (2027, 2)], "months_between crosses a year")

# T2 ordinary night, mid-month: the plain file covers the month, no month-end file is read
plain = merged(month_file(date(2026, 10, 1), date(2026, 10, 29), 30), stragglers([(date(2026, 9, 14), 3), (date(2026, 8, 20), 2)]))
pj = run(plain, {"daf420.dat.09-30-2026": SEP}, date(2026, 10, 31), date(2026, 10, 31))
check(pj["covered"] == [(date(2026, 10, 1), date(2026, 10, 29))], "S1 Oct 31 night: plain file covers Oct 1-29 %r" % pj["covered"])
check(W.eom_opened == 0, "S1 Oct 31 night: the End of Month share is not opened")
check(newest_day(pj, date(2026, 10, 31)) == date(2026, 10, 29), "S1 Oct 31 night: permits day is Oct 29")

# T3 first night of a month, the file already turned to the new month and holds only stragglers
plain = stragglers([(date(2026, 9, 3), 4)], start=777000)
for day in (date(2026, 10, 27), date(2026, 10, 28)):  # one October permit each, with the permit numbers the month-end file has
    k = next(k for k, v in OCT.items() if v["issued"] == day)
    plain[k] = OCT[k]
pj = run(plain, {"daf420.dat.10-31-2026": OCT}, date(2026, 11, 1), date(2026, 11, 1))
check(pj["covered"] == [(date(2026, 10, 1), date(2026, 10, 31))], "S2 Nov 1, empty new month: only the month-end file covers (Oct 1-31) %r" % pj["covered"])
check(newest_day(pj, date(2026, 11, 1)) == date(2026, 10, 30), "S2 Nov 1: permits day is Oct 30, from the month-end file")
check(pj["series"][date(2026, 10, 27)][0] == 30, "S2 Nov 1: Oct 27 counts 30 (month-end file), not the stragglers' %r" % pj["series"][date(2026, 10, 27)])
check(not any("not covered" in m for m in W.logs), "S2 Nov 1: November has no month-end file yet and that is not logged")

# T4 the file has turned and holds the first business day of the new month
nov2 = month_file(date(2026, 11, 2), date(2026, 11, 2), 35, start=40000)
plain = merged(nov2, stragglers([(date(2026, 10, 27), 1), (date(2026, 9, 3), 4)], start=777000))
pj = run(plain, {"daf420.dat.10-31-2026": OCT}, date(2026, 11, 3), date(2026, 11, 3))
check(sorted(pj["covered"]) == [(date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 2))], "S3 Nov 3: October from the month-end file, Nov 1-2 from the plain file %r" % sorted(pj["covered"]))
check(newest_day(pj, date(2026, 11, 3)) == date(2026, 11, 2), "S3 Nov 3: permits day is Nov 2")

# T5 the file is still on the old month on the first Monday
plain = month_file(date(2026, 10, 1), date(2026, 10, 30), 30)
pj = run(plain, {"daf420.dat.10-31-2026": OCT}, date(2026, 11, 2), date(2026, 11, 2))
check(pj["covered"] == [(date(2026, 10, 1), date(2026, 10, 31))], "S4 Nov 2, file still October: covered by the month-end file only (the plain file is not trusted for an ended month) %r" % pj["covered"])
check(newest_day(pj, date(2026, 11, 2)) == date(2026, 10, 30), "S4 Nov 2: permits day is Oct 30")

# T6 month-end file not out yet: no coverage, no section, and a log line
plain = stragglers([(date(2026, 10, 27), 1), (date(2026, 9, 3), 4)], start=777000)
pj = run(plain, {"daf420.dat.09-30-2026": SEP}, date(2026, 11, 1), date(2026, 11, 1))
check(pj["covered"] == [], "S5 Nov 1, no October month-end file: nothing covered")
check(newest_day(pj, date(2026, 11, 1)) is None, "S5 Nov 1: no permits section rather than one counted from stragglers")
check(any("daf420.dat.10-31-2026" in m and "not covered" in m for m in W.logs), "S5 Nov 1: the missing month-end file is logged")
ledger = {"2026-10-27": [30, 28, 20]}
d7.merge_series(ledger, pj["series"], pj["covered"], date(2026, 8, 1))
check(ledger == {"2026-10-27": [30, 28, 20]}, "S5: the ledger is untouched when nothing is covered")

# T7 repairing a day of an earlier month from today
plain = merged(month_file(date(2026, 10, 1), date(2026, 10, 29), 30), stragglers([(d, 2) for d in business_days(date(2026, 9, 1), date(2026, 9, 14))], start=555000))
plain.update({k: v for k, v in SEP.items() if v["issued"] <= date(2026, 9, 14) and int(k) % 14 == 0})  # a few September permits, same numbers as the month-end file
pj = run(plain, {"daf420.dat.09-30-2026": SEP, "daf420.dat.08-31-2026": AUG}, date(2026, 9, 15), date(2026, 10, 31))
check(pj["covered"] == [(date(2026, 9, 1), date(2026, 9, 30))], "S6 repair Sep 15 on Oct 31: September from the month-end file, not the October file %r" % pj["covered"])
check(newest_day(pj, date(2026, 9, 15)) == date(2026, 9, 14), "S6 repair Sep 15: permits day is Sep 14")
check(pj["series"][date(2026, 9, 14)][0] >= 28, "S6 repair Sep 15: Sep 14 counts the whole day (%d), not stragglers" % pj["series"][date(2026, 9, 14)][0])

# T8 repair at the start of a month reaches into the month before (Oct 2 looks back to Sep 30)
plain = month_file(date(2026, 10, 1), date(2026, 10, 1), 30, start=1000)
pj = run(plain, {"daf420.dat.09-30-2026": SEP}, date(2026, 10, 2), date(2026, 10, 31))
check(date(2026, 9, 1) <= pj["covered"][-1][0] <= date(2026, 10, 1) and any(c == (date(2026, 9, 1), date(2026, 9, 30)) for c in pj["covered"]), "S7 Oct 2: September from the month-end file as well")
check(newest_day(pj, date(2026, 10, 2)) == date(2026, 10, 1), "S7 Oct 2: permits day is Oct 1")

# T9 a rebuild of the whole archive reads the same month-end files as before
dates = [date(2026, 10, 31) - timedelta(days=i) for i in range(91, -1, -1)]
plain = month_file(date(2026, 10, 1), date(2026, 10, 29), 30)
eom = {"daf420.dat.07-31-2026": JUL, "daf420.dat.08-31-2026": AUG, "daf420.dat.09-30-2026": SEP}
pj = run(plain, eom, date(2026, 10, 31), date(2026, 10, 31), dates)
check(sorted(pj["covered"]) == [(date(2026, 7, 1), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 29))],
      "S8 rebuild of 92 days: July, August, September month-end files and the October plain file %r" % sorted(pj["covered"]))
check(newest_day(pj, date(2026, 8, 3)) == date(2026, 7, 31), "S8 Aug 3 reaches back to Jul 31")

# T10 an ended month that is missing from the share is logged
pj = run(plain, {"daf420.dat.08-31-2026": AUG, "daf420.dat.09-30-2026": SEP}, date(2026, 10, 31), date(2026, 10, 31), dates)
check(any("daf420.dat.07-31-2026" in m for m in W.logs), "S9 a missing month-end file for an ended month is logged")

# T11 the ledger only goes up
led = {"2026-10-27": [40, 36, 28], "2026-10-28": [3, 2, 1]}
series = {date(2026, 10, 27): [3, 2, 1], date(2026, 10, 28): [41, 35, 29], date(2026, 10, 29): [5, 4, 2]}
d7.merge_series(led, series, [(date(2026, 10, 26), date(2026, 10, 30))], date(2026, 8, 1))
check(led["2026-10-27"] == [40, 36, 28], "ledger: a smaller (partial) count does not replace a larger one")
check(led["2026-10-28"] == [41, 35, 29], "ledger: a larger count raises it, element by element")
check(led["2026-10-29"] == [5, 4, 2] and led["2026-10-26"] == [0, 0, 0] and led["2026-10-30"] == [0, 0, 0], "ledger: new days are written, days without permits as zeros")
check(all(0 <= h <= nd <= t for t, nd, h in led.values()), "ledger: every day still nests (horizontal <= new-drill <= all)")
led = {}
d7.merge_series(led, {date(2026, 7, 1): [9, 9, 9], date(2026, 10, 1): [1, 1, 1]}, [(date(2026, 6, 1), date(2026, 10, 1))], date(2026, 8, 1))
check("2026-07-01" not in led and led["2026-10-01"] == [1, 1, 1], "ledger: days before the window are not written")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
