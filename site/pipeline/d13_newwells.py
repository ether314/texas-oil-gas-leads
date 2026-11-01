#!/usr/bin/env python3
"""D13: every new well in the country that has a GPS point, from FracFocus (the national hydraulic-fracturing disclosure registry).

No state agency, and no single agency's permit file, gives the location of every new well in every state. FracFocus does for the wells that matter
most: an operator discloses each hydraulically fractured well (nearly every new horizontal oil well) with its wellhead's latitude and longitude, its
state and county, the day the job started, its true vertical depth and the water it used. The registry is national (17 states have wells in it in the
last two years, among them Colorado, Montana and Alaska, which the permit report cannot read yet), public, and refreshed five days a week.

What is read: `DisclosureList_1.csv` inside `FracFocusCSV.zip` (about 250,000 rows, one per disclosure, 16 MB compressed inside a 443 MB zip). The
zip is never downloaded whole: its directory and that one member are fetched with HTTP range requests (about 18 small ranges), so a weekly run costs
the registry 16 MB. Standard library only; run with `python3 -I`.

What a "new well" is: the first disclosure of a well, the well being the first ten digits of its API number (a sidetrack shares them). A well that was
fractured again later, or whose frac was disclosed twice, counts once, on the day of its first job. Counted by that day (`JobStartDate`). A disclosure
arrives weeks to months after the job (a month is about 94% complete after four months), so a month counts as settled only when it ended at least
LAG_DAYS before the newest job in the file; the newest weeks are still published, marked as filling in.

What is published (site/public/data/newwells/):
  summary.json  by state, new wells per month since 2019-01, the last 12 settled months against the 12 before, the top counties and operators, and
                how many wells have a usable point
  points.json   one row per well of the last 24 months that has a usable point, as columns: latitude and longitude in ten-thousandths of a degree,
                the day (days since t0), the state, county and operator (indexes into tables; -1 for an operator that may not be named), depth in
                hundreds of feet, water in hundreds of thousands of gallons, and whether the well is on federal or tribal land
  detail.json   the same wells in the same order (row i of the detail is row i of points.json), as columns of whole numbers: the API number of the well
                (its first ten digits), the job's last day (days after its first), the exact depth in feet, the exact water and the non-water base fluid in gallons,
                and the datum of the point (NAD27, NAD83, WGS84). By the owner's decision of 2026-11-02 (CLAUDE.md, Privacy, exception (d)) these two files, and no
                other file of this folder, carry an API number; the Daily report shows and offers them. `detail-history.json` is the same for points-history.json.
Never published: the well's name, the lease, a name that is not a corporation, LLC or partnership (the one naming rule, `d8_ok_daily.nameable`, plus
KNOWN_ORGANIZATIONS below), the registry's own ids; and no API number outside the two detail files.

A point is kept only if it lies in the state the registry gives for the well (checked against the committed outlines, `us-states.json`, with 0.1 degree
of tolerance for the coast and for the old datum: NAD27 positions are not shifted, the difference is under 100 m). A well with no usable point still
counts in the months and the rankings; its share is published (`located`).

Exit codes: 0 written (or unchanged), 1 failed, 2 refused by the server (an answer, not an error). `--file PATH` reads a local FracFocusCSV.zip or a
DisclosureList csv instead of the network (tests and rehearsals); `--check` reloads and validates what is committed; `--guard-floor 0` skips the check
that a run may not lose more than a tenth of the committed history.
"""
import collections
import csv
import io
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d11_nat_common as C  # noqa: E402  (dates, months, place names, the naming rule, Refused)
import privacy_check  # noqa: E402
import d13_arrivals as ARR  # noqa: E402  (what is new since the last download, and what a state's daily report already carried)

URL = "https://www.fracfocusdata.org/digitaldownload/FracFocusCSV.zip"
PAGE = "https://fracfocus.org/data-download"
OUT = os.environ.get("D13_DIR") or os.path.join(SITE, "public", "data", "newwells")
OUTLINES = os.path.join(SITE, "public", "data", "us-states.json")
DAILY = os.path.join(SITE, "public", "data", "daily")  # Texas's day files: the wells its daily reports carried
REGISTRY_START = date(2011, 1, 1)  # the registry began in 2011: an earlier job date is a typing error
LAG_DAYS = 120  # a month is settled when it ended this long before the newest job in the file
POINT_MONTHS = 24  # the points file holds the wells of this many months, the newest month included
SUMMARY_FIRST = "2011-01"  # the monthly series starts with the registry
HISTORY_MIN = 0.9  # the history holds at least this share of the wells the summary counts before its end (the real registry: 99.8% to 100% in every year)
TOLERANCE = 0.1  # degrees outside a state's outline that a point may lie (the coast, the old datum)
MAX_WATER = 150e6  # gallons of water in one job: the registry has typing errors of 400 million and more
MAX_MEMBER = 400 * 1024 * 1024  # a disclosure list is 61 MB today
BLOCK = 1 << 20
REQUIRED = ("DisclosureId", "JobStartDate", "APINumber", "StateName", "CountyName", "OperatorName", "Latitude", "Longitude", "Projection", "TVD", "TotalBaseWaterVolume", "FederalWell", "IndianWell")
STATE_OF = {name: code for code, name in C.JURISDICTIONS if code not in ("FO", "BL")}
# The first two digits of an API number are its state (read off the real registry on 2026-11-02 for the 27 states that have wells in it; Arizona, Florida,
# Missouri, Oregon, South Dakota and Tennessee follow the same alphabetical numbering and have none yet). The registry's own state name disagrees with
# its API number on a handful of rows (a Texas well with a California prefix), so the check that the detail file lines up with the points is a share, not every row.
API_STATE = {"AL": "01", "AZ": "02", "AR": "03", "CA": "04", "CO": "05", "FL": "09", "ID": "11", "IL": "12", "IN": "13", "KS": "15", "KY": "16", "LA": "17", "MI": "21", "MS": "23", "MO": "24",
             "MT": "25", "NE": "26", "NV": "27", "NM": "30", "NY": "31", "ND": "33", "OH": "34", "OK": "35", "OR": "36", "PA": "37", "SD": "40", "TN": "41", "TX": "42", "UT": "43", "VA": "45",
             "WV": "47", "WY": "49", "AK": "50"}
ALIGN_MIN = 0.99  # the share of detail rows whose API prefix is their point's state (real data: 99.99%); a file not aligned with its points scores about one in ten
DATUMS = {"NAD27": 1, "NAD83": 2, "WGS84": 3}  # 0 is "not given"; the registry also writes "Nad27"
MAX_JOB_DAYS = 365  # a job that ends before it starts, or more than a year later, is a typing error: its end is left out
log = C.log

# Operators FracFocus lists under a name the shared rule refuses because it has no "Inc" or "LLC" (the rule names an operator only when it ends like a
# corporation, LLC or partnership). Each of these is a company with its own filings, a public company or a well-known subsidiary of one, and is not
# a person. The list is reviewed by hand: a name is added only when it is certain, and every other name stays unnamed.
KNOWN_ORGANIZATIONS = frozenset(n.upper() for n in (
    "Pioneer Natural Resources", "Occidental Oil and Gas", "XTO Energy/ExxonMobil", "SM Energy", "Marathon Oil", "PDC Energy", "EQT Production",
    "Endeavor Energy Resources", "Oasis Petroleum", "Chord Energy", "Crestone Peak Resources", "Comstock Oil & Gas", "Vital Energy", "WPX Energy",
    "Southwestern Energy", "SilverBow Resources", "Whiting Petroleum", "Murphy Exploration and Production USA", "SandRidge Energy", "Mitsui E&P",
    "Wexpro Company", "Infinity Natural Resources", "EP Energy", "Blackbeard Operating", "Franklin Mountain Energy", "Lewis Energy Group", "Mach Resources",
    "Tap Rock Resources", "Triple Crown Resources", "Rosewood Resources", "Validus Energy II Midcon", "Pennsylvania General Energy", "Ultra Resources",
    "Cook Inlet Energy", "Unit Petroleum",
))


def key_of(name):
    """An operator's name as a comparison key: upper case, one space, no commas."""
    return " ".join((name or "").upper().replace(",", " ").split())


def may_name(name):
    k = key_of(name)
    return bool(k) and (C.nameable(name) or k in KNOWN_ORGANIZATIONS) and not C.D8.NOT_BUSINESS.search(k)


# ------------------------------------------------------------------------------------------------ reading the registry without downloading it

class RangeFile(io.RawIOBase):
    """A read-only, seekable file over a server that answers HTTP range requests, so `zipfile` can read one member of a zip that is 443 MB.
    `fetch(start, end)` returns the bytes of that inclusive range; the file is `size` bytes. Reads go through 1 MB blocks, a few kept."""

    def __init__(self, fetch, size, keep=4):
        self.fetch, self.size, self.pos, self.keep = fetch, size, 0, keep
        self.cache = collections.OrderedDict()
        self.requests = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = offset if whence == io.SEEK_SET else self.pos + offset if whence == io.SEEK_CUR else self.size + offset
        self.pos = max(0, min(self.pos, self.size))
        return self.pos

    def _block(self, i):
        if i in self.cache:
            self.cache.move_to_end(i)
            return self.cache[i]
        start = i * BLOCK
        data = self.fetch(start, min(self.size, start + BLOCK) - 1)
        self.requests += 1
        if len(data) != min(BLOCK, self.size - start):
            raise OSError("the server returned %d bytes of a range of %d" % (len(data), min(BLOCK, self.size - start)))
        self.cache[i] = data
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)
        return data

    def readinto(self, buf):
        want = min(len(buf), self.size - self.pos)
        got = 0
        while got < want:
            i, off = divmod(self.pos, BLOCK)
            block = self._block(i)
            n = min(want - got, len(block) - off)
            buf[got:got + n] = block[off:off + n]
            got += n
            self.pos += n
        return got


def http_range(url=URL, tries=2):
    """(fetch, size) for a URL: the size from a one-byte range, then ranges on demand. A server that does not answer ranges (200 with the whole body)
    is refused, never downloaded; 401, 403 and 429 are an answer (Refused)."""
    def fetch(start, end):
        last = None
        for i in range(tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": C.UA, "Range": "bytes=%d-%d" % (start, end), "Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    if r.status != 206:
                        raise ValueError("the server does not answer range requests (HTTP %d)" % r.status)
                    body = r.read(end - start + 2)
                    total = int((r.headers.get("Content-Range") or "").rsplit("/", 1)[-1] or 0)
                return body, total
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 407, 429):
                    raise C.Refused("HTTP %d from the server" % e.code)
                last = e
            except ValueError:
                raise
            except OSError as e:
                last = e
            if i + 1 < tries:
                time.sleep(3 * (i + 1))
        raise RuntimeError("could not read the registry: " + privacy_check.clean_error(last))
    _, size = fetch(0, 0)
    if not size or size > 2 * 1024 ** 3:
        raise ValueError("the registry's zip has an implausible size: %r" % (size,))
    return (lambda s, e: fetch(s, e)[0]), size


def disclosure_members(zf):
    names = [n for n in zf.namelist() if re.fullmatch(r"DisclosureList_\d+\.csv", n)]
    return sorted(names, key=lambda n: int(re.search(r"\d+", n).group()))


def rows_of_zip(zf):
    """The rows of every DisclosureList_N.csv in the zip, as dicts. Refuses a member that is too large or lacks a column the producer needs."""
    members = disclosure_members(zf)
    if not members:
        raise ValueError("the zip has no DisclosureList_N.csv")
    for name in members:
        if zf.getinfo(name).file_size > MAX_MEMBER:
            raise ValueError("%s is larger than %d MB" % (name, MAX_MEMBER >> 20))
        with zf.open(name) as f:
            rd = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
            missing = [c for c in REQUIRED if c not in (rd.fieldnames or [])]
            if missing:
                raise ValueError("%s lacks the columns %s" % (name, ", ".join(missing)))
            yield from rd


def rows_of_file(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            yield from rows_of_zip(zf)
        return
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (rd.fieldnames or [])]
        if missing:
            raise ValueError("the csv lacks the columns " + ", ".join(missing))
        yield from rd


def rows_from_network(url=URL):
    fetch, size = http_range(url)
    rf = RangeFile(fetch, size)
    with zipfile.ZipFile(rf) as zf:
        yield from rows_of_zip(zf)
    log("read the registry's disclosure list in %d range requests" % rf.requests)


# ------------------------------------------------------------------------------------------------ outlines: is a point in its state?

class Outlines:
    def __init__(self, doc):
        self.rings = {}
        for code, s in doc["states"].items():
            self.rings[code] = [(r, min(r[0::2]), min(r[1::2]), max(r[0::2]), max(r[1::2])) for r in s["rings"]]

    @staticmethod
    def _in(r, x, y):
        c = False
        n = len(r)
        j = n - 2
        for i in range(0, n, 2):
            xi, yi, xj, yj = r[i], r[i + 1], r[j], r[j + 1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c

    @staticmethod
    def _near(r, x, y, tol):
        for i in range(0, len(r) - 2, 2):
            x1, y1, x2, y2 = r[i], r[i + 1], r[i + 2], r[i + 3]
            dx, dy = x2 - x1, y2 - y1
            t = 0 if not (dx or dy) else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            if math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)) <= tol:
                return True
        return False

    def contains(self, code, lon, lat, tol=TOLERANCE):
        rings = self.rings.get(code)
        if not rings:
            return False
        for r, a, b, c, d in rings:
            if a <= lon <= c and b <= lat <= d and self._in(r, lon, lat):
                return True
        return any(a - tol <= lon <= c + tol and b - tol <= lat <= d + tol and self._near(r, lon, lat, tol) for r, a, b, c, d in rings)


def load_outlines(path=OUTLINES):
    with open(path, encoding="utf-8") as f:
        return Outlines(json.load(f))


# ------------------------------------------------------------------------------------------------ collecting wells

def number(text):
    try:
        v = float(str(text).replace(",", "").strip())
    except ValueError:
        return None
    return v if v == v and abs(v) != float("inf") else None


class Wells:
    """The first disclosure of every well. A row is folded into a record at once: its API number is only the key of a dict that never leaves the process."""

    def __init__(self, outlines, today=None):
        self.out = outlines
        self.today = today or date.today()
        self.first = {}  # api10 -> (day, state, county, operator, (lat, lon) or None, tvd_ft, water_gal, land, api10, last job day or None, non-water gal or None, datum 0 to 3)
        self.read = 0
        self.skipped = collections.Counter()

    def add(self, row):
        self.read += 1
        day = C.parse_day(row.get("JobStartDate"), self.today)
        if day is None or day < REGISTRY_START:
            self.skipped["date"] += 1
            return
        api = re.sub(r"\D", "", row.get("APINumber") or "")
        if len(api) < 10:
            self.skipped["api"] += 1
            return
        state = STATE_OF.get(" ".join((row.get("StateName") or "").split()))
        if not state:
            self.skipped["state"] += 1
            return
        have = self.first.get(api[:10])
        if have is not None and have[0] <= day:
            return
        lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
        if lat is not None and lon is not None and lon > 0:
            lon = -lon  # the registry says a longitude must carry its minus sign
        point = None
        if lat is not None and lon is not None and 15 <= lat <= 75 and -180 <= lon <= -60 and self.out.contains(state, lon, lat):
            point = (round(lat, 4), round(lon, 4))
        tvd, water = number(row.get("TVD")), number(row.get("TotalBaseWaterVolume"))
        county = " ".join((row.get("CountyName") or "").replace("_", " ").split())
        county = C.place_title(county) if county and C.PLACE.match(county) and not re.search(r"\d{3,}", county) else ""
        land = (1 if (row.get("FederalWell") or "").strip().lower() == "true" else 0) + (2 if (row.get("IndianWell") or "").strip().lower() == "true" else 0)
        end = C.parse_day(row.get("JobEndDate"), self.today)
        end = end if end is not None and day <= end <= day + timedelta(days=MAX_JOB_DAYS) else None
        nonwater = number(row.get("TotalBaseNonWaterVolume"))
        datum = DATUMS.get((row.get("Projection") or "").strip().upper(), 0)
        self.first[api[:10]] = (day, state, county, " ".join((row.get("OperatorName") or "").split()), point, tvd if tvd and 500 <= tvd <= 30000 else None,
                                water if water and 1000 <= water <= MAX_WATER else None, land, api[:10], end, nonwater if nonwater is not None and 0 <= nonwater <= MAX_WATER else None, datum)


def months_through(asof):
    """The months of the series: from the registry's first month (2011-01) to the newest job's month; and the last settled month (it ended LAG_DAYS or more before the newest job)."""
    months = C.month_list(SUMMARY_FIRST, C.month_of(asof))
    settled = max((m for m in months if C.month_end(m).toordinal() + LAG_DAYS <= asof.toordinal()), default=None)
    if settled is None:
        raise ValueError("no month has settled yet")
    return months, settled


def median(values, n=5):
    return statistics.median(values) if len(values) >= n else None


def points_rows(recs, t0):
    """The located wells of the last 24 months in the order of points.json. The detail file is built from this same list, so its row i is the points file's row i."""
    return sorted((r for r in recs if r[4] and r[0] >= t0), key=lambda r: (r[0], r[1], r[4]))


def history_rows(recs, until):
    """The located wells before `until` in the order of points-history.json (and detail-history.json)."""
    return sorted((r for r in recs if r[4] and r[0] < until), key=lambda r: (r[0], r[1], r[4]))


def build(wells, today=None):
    """(summary, points) from collected wells."""
    today = today or wells.today
    recs = list(wells.first.values())
    if not recs:
        raise ValueError("no well was read: refusing to write an empty registry")
    asof = max(r[0] for r in recs)
    months, settled = months_through(asof)
    idx = {m: i for i, m in enumerate(months)}
    last12 = months[months.index(settled) - 11:months.index(settled) + 1]
    prev12 = months[months.index(settled) - 23:months.index(settled) - 11]
    by = collections.defaultdict(list)
    for r in recs:
        by[r[1]].append(r)
    states = []
    for code, rs in by.items():
        new = [0] * len(months)
        cnt, ops, name_of = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
        named = unnamed = located = n12 = 0
        tvd, water = [], []
        for r in rs:
            ym = C.month_of(r[0])
            new[idx[ym]] += 1
            if ym in last12:
                n12 += 1
                located += 1 if r[4] else 0
                if r[2]:
                    cnt[r[2]] += 1
                if r[3]:
                    if may_name(r[3]):
                        ops[key_of(r[3])] += 1
                        name_of[key_of(r[3])][r[3]] += 1
                        named += 1
                    else:
                        unnamed += 1
                if r[5]:
                    tvd.append(r[5])
                if r[6]:
                    water.append(r[6])
        states.append({
            "id": code, "name": C.NAME_OF[code], "new": new,
            "p12": sum(new[idx[m]] for m in last12), "prev12": sum(new[idx[m]] for m in prev12),
            "latest": max(r[0] for r in rs).isoformat(),
            "located": round(located / n12, 3) if n12 else None,
            "counties": [[c, n] for c, n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:15]],
            "operators": [[name_of[k].most_common(1)[0][0], n] for k, n in sorted(ops.items(), key=lambda kv: (-kv[1], kv[0]))[:15]],
            "namedShare": round(named / (named + unnamed), 3) if named + unnamed else None,
            "tvd": round(median(tvd)) if median(tvd) else None, "water": round(median(water) / 1e6, 1) if median(water) else None,
        })
    states.sort(key=lambda s: (-s["p12"], s["name"]))
    first_pt = C.add_months(C.month_of(asof), -(POINT_MONTHS - 1)) + "-01"
    t0 = date.fromisoformat(first_pt)
    sids = [s["id"] for s in states]
    points = encode_points(points_rows(recs, t0), t0, sids, asof)
    summary = {
        "v": 1, "asOf": asof.isoformat(), "settled": C.month_end(settled).isoformat(), "lagDays": LAG_DAYS, "read": wells.read, "wells": len(recs),
        "source": {"name": "FracFocus Chemical Disclosure Registry", "url": PAGE}, "months": months, "states": states,
        "note": "A well is counted once, on the day of its first hydraulic-fracturing disclosure; disclosures arrive weeks to months after the job, so the newest months are still filling in.",
    }
    return summary, points


COLS = ("lat", "lon", "d", "s", "c", "o", "tvd", "h2o", "f")


def encode_points(rows, t0, sids, asof):
    """Located wells (already in day order) as the points file's columns of whole numbers, with the county and operator tables they index."""
    sidx = {sid: i for i, sid in enumerate(sids)}
    ctable, otable, cix, oix = [], [], {}, {}
    cols = {k: [] for k in COLS}
    for r in rows:
        ckey = (r[1], r[2])
        if r[2] and ckey not in cix:
            cix[ckey] = len(ctable)
            ctable.append([r[1], r[2]])
        okey = key_of(r[3])
        if may_name(r[3]) and okey not in oix:
            oix[okey] = len(otable)
            otable.append(r[3])
        cols["lat"].append(round(r[4][0] * 1e4))
        cols["lon"].append(round(r[4][1] * 1e4))
        cols["d"].append((r[0] - t0).days)
        cols["s"].append(sidx[r[1]])
        cols["c"].append(cix.get(ckey, -1))
        cols["o"].append(oix[okey] if may_name(r[3]) else -1)
        cols["tvd"].append(round(r[5] / 100) if r[5] else 0)
        cols["h2o"].append(round(r[6] / 1e5) if r[6] else 0)
        cols["f"].append(r[7])
    return {"v": 1, "t0": t0.isoformat(), "asOf": asof.isoformat(), "n": len(rows), "states": sids, "counties": ctable, "ops": otable, **cols}


def encode_detail(rows, base):
    """What the registry also says of the same wells, as columns of whole numbers in the same order as `base` (the points or history document made from these rows):
    the API number of the well (a number: Alabama's starts with a zero), the job's last day as days after its first, the exact depth (feet), water and non-water base fluid
    (gallons) and the datum. -1 is "not known" (a well really has no non-water fluid: that is 0)."""
    out = {"v": 1, "t0": base["t0"], "n": len(rows)}
    out["until" if "until" in base else "asOf"] = base["until"] if "until" in base else base["asOf"]
    out["api"] = [int(r[8]) for r in rows]
    out["end"] = [(r[9] - r[0]).days if r[9] else -1 for r in rows]
    out["tvd"] = [round(r[5]) if r[5] else -1 for r in rows]
    out["wg"] = [round(r[6]) if r[6] else -1 for r in rows]
    out["nw"] = [round(r[10]) if r[10] is not None else -1 for r in rows]
    out["dat"] = [r[11] for r in rows]
    return out


def build_detail(wells, points):
    """The detail of points.json's wells."""
    rows = points_rows(list(wells.first.values()), date.fromisoformat(points["t0"]))
    if len(rows) != points["n"]:
        raise ValueError("detail: %d wells against %d points" % (len(rows), points["n"]))
    return encode_detail(rows, points)


def build_history_detail(wells, history):
    """The detail of points-history.json's wells."""
    rows = history_rows(list(wells.first.values()), date.fromisoformat(history["until"]))
    if len(rows) != history["n"]:
        raise ValueError("detail-history: %d wells against %d points" % (len(rows), history["n"]))
    return encode_detail(rows, history)


def history_end(asof):
    """The history file holds the wells before January 1 of the year before the newest job's: it moves once a year, and it is never later than the points file's start (a gap would lose wells), only earlier (an overlap of up to 11 months, which the page drops)."""
    return date(asof.year - 1, 1, 1)


def build_history(wells, summary):
    """The wells with a usable point from the registry's start to history_end: the same columns and the same state order as the points file, with tables of their own. The page loads it only when asked."""
    asof = date.fromisoformat(summary["asOf"])
    until = history_end(asof)
    rows = history_rows(list(wells.first.values()), until)
    doc = encode_points(rows, REGISTRY_START, [s["id"] for s in summary["states"]], asof)
    doc["until"] = until.isoformat()
    del doc["asOf"]  # the history does not change with each week's read: its file changes only when an old well does, or once a year when its end moves
    return doc


# ------------------------------------------------------------------------------------------------ validation

def validate_summary(doc, today=None):
    p = []
    today = today or date.today()
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return ["summary: not a v1 document"]
    ok = all(isinstance(doc.get(k), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", doc[k]) for k in ("asOf", "settled"))
    if not ok:
        return ["summary: asOf and settled must be dates"]
    if doc["asOf"] > today.isoformat():
        p.append("summary: asOf is in the future")
    months = doc.get("months")
    if not (isinstance(months, list) and len(months) >= 36 and months == C.month_list(months[0], months[-1]) and months[0] == SUMMARY_FIRST):
        return p + ["summary: months must run from %s without a gap" % SUMMARY_FIRST]
    if months[-1] != doc["asOf"][:7]:
        p.append("summary: the months end where asOf is")
    if doc["settled"] != C.month_end(doc["settled"][:7]).isoformat() or doc["settled"][:7] not in months or C.month_end(doc["settled"][:7]).toordinal() + LAG_DAYS > date.fromisoformat(doc["asOf"]).toordinal():
        p.append("summary: settled must be a month end at least %d days before asOf" % LAG_DAYS)
    if not (isinstance(doc.get("read"), int) and doc["read"] > 0 and isinstance(doc.get("wells"), int) and 0 < doc["wells"] <= doc["read"]):
        p.append("summary: read and wells must be counts, wells not above read")
    src = doc.get("source") or {}
    if not (isinstance(src.get("name"), str) and re.match(r"https://[\w.\-]+/", str(src.get("url", "")))):
        p.append("summary: source needs a name and an https address")
    states = doc.get("states")
    if not (isinstance(states, list) and 5 <= len(states) <= 40):
        return p + ["summary: states must be a list of 5 to 40"]
    seen = set()
    for s in states:
        sid = s.get("id") if isinstance(s, dict) else None
        if sid not in STATE_OF.values() or sid in seen:
            p.append("summary: state %r is unknown or repeated" % (sid,))
            continue
        seen.add(sid)
        v = s.get("new")
        if not (isinstance(v, list) and len(v) == len(months) and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 20000 for x in v)):
            p.append("summary %s: new must be %d whole counts" % (sid, len(months)))
            continue
        if s.get("name") != C.NAME_OF[sid]:
            p.append("summary %s: wrong name" % sid)
        i = months.index(doc["settled"][:7])
        if s.get("p12") != sum(v[i - 11:i + 1]) or s.get("prev12") != sum(v[i - 23:i - 11]):
            p.append("summary %s: p12 or prev12 is not the sum of the months" % sid)
        for key in ("counties", "operators"):
            rows = s.get(key)
            if not (isinstance(rows, list) and len(rows) <= 15 and all(isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], int) and r[1] > 0 for r in rows)
                    and [r[1] for r in rows] == sorted((r[1] for r in rows), reverse=True)):
                p.append("summary %s: %s must be at most 15 ranked [name, count]" % (sid, key))
        for r in s.get("counties") or []:
            if not C.PLACE.match(r[0]) or re.search(r"\d{3,}", r[0]):
                p.append("summary %s: county name %r" % (sid, r[0]))
        for r in s.get("operators") or []:
            if not may_name(r[0]):
                p.append("summary %s: operator name the rule refuses: %s" % (sid, privacy_check.mask(r[0])))
        for key in ("located", "namedShare"):
            if s.get(key) is not None and not (isinstance(s[key], (int, float)) and 0 <= s[key] <= 1):
                p.append("summary %s: %s must be 0 to 1" % (sid, key))
        if not (isinstance(s.get("latest"), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", s["latest"]) and s["latest"] <= doc["asOf"]):
            p.append("summary %s: latest must be a date not after asOf" % sid)
    ranks = [s.get("p12") for s in states if isinstance(s, dict) and isinstance(s.get("p12"), int)]
    if ranks != sorted(ranks, reverse=True):
        p.append("summary: states must be ranked by p12")
    if sum(s.get("p12", 0) for s in states if isinstance(s, dict)) < 3000:
        p.append("summary: fewer than 3,000 new wells in the last 12 months: a read that lost most of the registry must not be written")
    for what in privacy_check.scan(re.sub(r"https://[\w./\-]+", "", json.dumps(doc, ensure_ascii=False)), digits=True):
        p.append("summary holds " + what)
    return p


def validate_points(doc, summary=None, history=False):
    """The points file (the last 24 months) or, with history=True, the history file (the registry's start to `until`): the same columns, the same checks."""
    p = []
    what = "history" if history else "points"
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return [what + ": not a v1 document"]
    cols = COLS
    n = doc.get("n")
    if not (isinstance(n, int) and n > 1000 and all(isinstance(doc.get(c), list) and len(doc[c]) == n for c in cols)):
        return [what + ": every column must hold n rows (n over 1,000)"]
    for k in ("t0", "until") if history else ("t0", "asOf"):
        if not (isinstance(doc.get(k), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", doc[k])):
            return [what + ": %s must be a date" % k]
    if history and (doc["t0"] != REGISTRY_START.isoformat() or (summary and doc["until"] != history_end(date.fromisoformat(summary["asOf"])).isoformat())):
        return [what + ": it must run from the registry's start to the January 1 before the newest job's year"]
    span = (date.fromisoformat(doc["until"] if history else doc["asOf"]) - date.fromisoformat(doc["t0"])).days - (1 if history else 0)
    states, ct, ot = doc.get("states"), doc.get("counties"), doc.get("ops")
    if not (isinstance(states, list) and all(isinstance(x, str) for x in states) and isinstance(ct, list) and isinstance(ot, list)):
        return ["points: states, counties and ops must be lists"]
    def ints(c, lo, hi):
        return all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in doc[c])
    for c, lo, hi in (("lat", 150000, 750000), ("lon", -1800000, -600000), ("d", 0, span), ("s", 0, len(states) - 1), ("c", -1, len(ct) - 1), ("o", -1, len(ot) - 1), ("tvd", 0, 300), ("h2o", 0, 2000), ("f", 0, 3)):
        if not ints(c, lo, hi):
            p.append("points: column %s must be whole numbers from %d to %d" % (c, lo, hi))
    if p:
        return p
    if doc["d"] != sorted(doc["d"]):
        p.append("points: rows must be in day order")
    if any(c >= 0 and ct[c][0] != states[st] for c, st in zip(doc["c"], doc["s"]) if isinstance(ct[c], list)):
        p.append("points: a point's county must belong to its state")
    for row in ct:
        if not (isinstance(row, list) and len(row) == 2 and row[0] in STATE_OF.values() and isinstance(row[1], str) and C.PLACE.match(row[1]) and not re.search(r"\d{3,}", row[1])):
            p.append(what + ": county table row %r" % (row,))
            break
    for name in ot:
        if not (isinstance(name, str) and may_name(name)):
            p.append(what + ": operator name the rule refuses: " + privacy_check.mask(name))
            break
    if summary and not p:
        ids = [s["id"] for s in summary["states"]]
        if states != ids:
            p.append(what + ": states differ from the summary's")
        elif not history and doc["asOf"] != summary["asOf"]:
            p.append(what + ": asOf differs from the summary's")
        else:
            lo = summary["months"].index(doc["t0"][:7])
            hi = summary["months"].index(doc["until"][:7]) if history else len(summary["months"])
            share = HISTORY_MIN if history else 0.8
            for i, s in enumerate(summary["states"]):
                have = doc["s"].count(i)
                total = sum(s["new"][lo:hi])
                if have > total or (total >= 50 and have < share * total):
                    p.append("%s %s: %d points against %d wells in the same months" % (what, s["id"], have, total))
    for hit in privacy_check.scan(json.dumps(doc, ensure_ascii=False), digits=True):
        p.append(what + " holds " + hit)
    return p


FILES = ("summary.json", "points.json", "points-history.json")
DETAIL_FILES = ("detail.json", "detail-history.json")


def validate_detail(doc, points, history=False):
    """The detail file of `points` (or, with history=True, of the history document): the same wells in the same order. Every column holds n whole numbers in its range, and it
    must line up with the points: the depth and the water agree with the points' rounded ones row by row, and the API number's state is the point's state for at least ALIGN_MIN of
    the rows. API numbers are allowed here (CLAUDE.md, exception (d)); an e-mail address, a web address or a phone number never are."""
    what = "detail-history" if history else "detail"
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return [what + ": not a v1 document"]
    n = points.get("n")
    cols = ("api", "end", "tvd", "wg", "nw", "dat")
    if doc.get("n") != n or not all(isinstance(doc.get(c), list) and len(doc[c]) == n for c in cols):
        return [what + ": every column must hold the %s rows of its points file" % n]
    key = "until" if history else "asOf"
    if doc.get("t0") != points.get("t0") or doc.get(key) != points.get(key):
        return [what + ": its t0 and %s must be its points file's" % key]
    if set(doc) != {"v", "t0", key, "n", *cols}:
        return [what + ": unexpected keys " + ", ".join(sorted(set(doc) ^ {"v", "t0", key, "n", *cols}))]
    def ints(c, lo, hi, none=None):
        return all(isinstance(x, int) and not isinstance(x, bool) and (lo <= x <= hi or x == none) for x in doc[c])
    p = []
    for c, lo, hi, none in (("api", 100_000_000, 9_999_999_999, None), ("end", 0, MAX_JOB_DAYS, -1), ("tvd", 500, 30000, -1), ("wg", 1000, int(MAX_WATER), -1), ("nw", 0, int(MAX_WATER), -1), ("dat", 0, 3, None)):
        if not ints(c, lo, hi, none):
            p.append("%s: column %s must be whole numbers from %d to %d%s" % (what, c, lo, hi, " (or -1)" if none is not None else ""))
    if p:
        return p
    states = points["states"]
    bad_tvd = bad_water = 0
    for i in range(n):
        pt, tvd, wg, h = points["tvd"][i], doc["tvd"][i], doc["wg"][i], points["h2o"][i]
        if (pt == 0) != (tvd == -1) or (tvd != -1 and abs(pt * 100 - tvd) > 51):  # points keep depth in hundreds of feet, 0 meaning unknown
            bad_tvd += 1
        if (wg == -1 and h != 0) or (wg != -1 and abs(h * 100000 - wg) > 50001):  # and water in hundreds of thousands of gallons (a small job rounds to 0)
            bad_water += 1
    matches = sum(1 for a, st in zip(doc["api"], points["s"]) if API_STATE.get(states[st]) == ("%010d" % a)[:2])
    if bad_tvd or bad_water:
        p.append("%s: %d rows whose depth and %d whose water disagree with the points file's: the two files are not the same wells" % (what, bad_tvd, bad_water))
    if n and matches < ALIGN_MIN * n:
        p.append("%s: only %d of %d API numbers belong to their point's state: the file does not line up with its points" % (what, matches, n))
    for hit in privacy_check.scan(json.dumps(doc, ensure_ascii=False), digits=False):
        p.append(what + " holds " + hit)
    return p


def validate_pair(points, history):
    """The two point files together: the history must reach the points file's first day (a gap would lose the wells in between)."""
    if history["until"] < points["t0"]:
        return ["history: it ends %s, before the points start (%s): wells in between would be lost" % (history["until"], points["t0"])]
    return []


def write(summary, points, out_dir=OUT, history=None, arrivals=None, detail=None, detail_history=None):
    """Validates, then writes the files (compact, deterministic). Nothing is written when any is bad."""
    bad = validate_summary(summary) + validate_points(points, summary)
    if history is not None:
        bad += validate_points(history, summary, history=True) or validate_pair(points, history)
    if detail is not None:
        bad += validate_detail(detail, points)
    if detail_history is not None:
        bad += validate_detail(detail_history, history, history=True) if history is not None else ["detail-history: there is no history to line it up with"]
    if arrivals is not None:
        bad += ARR.validate(arrivals, states={s["id"] for s in summary["states"]})
    if bad:
        raise ValueError("; ".join(bad[:6]))
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, doc in (("summary.json", summary), ("points.json", points), ("points-history.json", history), (DETAIL_FILES[0], detail), (DETAIL_FILES[1], detail_history), (ARR.NAME, arrivals)):
        if doc is None:
            continue
        path = os.path.join(out_dir, name)
        text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != text:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(path + ".tmp", path)
        paths.append((path, old != text))
    return paths


def load_committed(out_dir=OUT):
    """[summary, points] as committed (None for one that is missing or unreadable); the history file is load_history's."""
    out = []
    for name in FILES[:2]:
        try:
            with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            out.append(None)
    return out


def load_history(out_dir=OUT):
    try:
        with open(os.path.join(out_dir, FILES[2]), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_detail(out_dir=OUT):
    """[detail, detail-history] as committed (None for one that is missing or unreadable)."""
    out = []
    for name in DETAIL_FILES:
        try:
            with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            out.append(None)
    return out


def check(out_dir=OUT):
    summary, points = load_committed(out_dir)
    if summary is None or points is None:
        return ["the files are missing or unreadable"]
    history = load_history(out_dir)
    if history is None:
        return validate_summary(summary) + validate_points(points, summary) + ["history: the file is missing or unreadable"]
    bad = validate_summary(summary) + validate_points(points, summary) + (validate_points(history, summary, history=True) or validate_pair(points, history))
    detail, dhist = load_detail(out_dir)  # the detail files: optional for a folder made before they existed, validated against their points when there
    for doc, base, name, hist in ((detail, points, DETAIL_FILES[0], False), (dhist, history, DETAIL_FILES[1], True)):
        if doc is not None:
            bad += validate_detail(doc, base, history=hist)
        elif os.path.exists(os.path.join(out_dir, name)):
            bad.append("%s: the file is unreadable" % name)
    arrivals = ARR.read(os.path.join(out_dir, ARR.NAME))  # the daily comparison's log: optional for a folder made before it existed, validated when there
    if arrivals is not None:
        bad += ARR.validate(arrivals, states={s["id"] for s in summary["states"]})
    elif os.path.exists(os.path.join(out_dir, ARR.NAME)):
        bad.append("arrivals: the file is unreadable")
    return bad


def guard(summary, committed, floor=0.9):
    """A run may not lose history: the last 24 months' wells, and all the wells the summary counts, must be at least `floor` of the committed file's, and the rows read too."""
    if not committed or not floor:
        return []
    def window(doc):
        return sum(sum(s["new"][-24:]) for s in doc["states"])
    problems = []
    if window(summary) < floor * window(committed):
        problems.append("the last 24 months hold %d wells against the committed %d" % (window(summary), window(committed)))
    if summary["wells"] < floor * committed.get("wells", 0):
        problems.append("%d wells against the committed %d" % (summary["wells"], committed["wells"]))
    if summary["read"] < floor * committed.get("read", 0):
        problems.append("%d rows read against the committed %d" % (summary["read"], committed["read"]))
    return problems


def run(rows, out_dir=OUT, today=None, floor=0.9, outlines=None, seen_path=None, daily_dir=DAILY, min_seen=ARR.SEEN_MIN):
    """seen_path: the list of wells kept from the last download (see d13_arrivals.py). With it, the run also reports the wells new since then, writes arrivals.json and keeps today's list."""
    wells = Wells(outlines or load_outlines(), today)
    for row in rows:
        wells.add(row)
    summary, points = build(wells)
    history = build_history(wells, summary)
    detail, detail_history = build_detail(wells, points), build_history_detail(wells, history)
    bad = guard(summary, load_committed(out_dir)[0], floor)
    if bad:
        raise ValueError("refusing to write: " + "; ".join(bad))
    arrivals = None
    if seen_path:
        day = wells.today.isoformat()
        seen = ARR.load_seen(seen_path, min_seen)
        carried, since = ARR.read_texas(daily_dir)
        entry = ARR.find(wells.first, seen, carried, day)
        arrivals = ARR.update(ARR.read(os.path.join(out_dir, ARR.NAME)), entry, day, {"TX": {"wells": len(carried), "from": since}})
        log("arrivals: " + ("no list kept from the last download: this one is kept as the baseline" if entry is None else
            "%d new wells since the last download (%s), %d gone from it" % (entry["found"], ", ".join("%s %d" % (r[0], r[1]) for r in entry["states"][:6]) or "none", entry["removed"])))
    done = write(summary, points, out_dir, history, arrivals, detail, detail_history)
    if seen_path:
        ARR.write_seen(seen_path, wells.first.keys())  # only after the files were written: a run that failed leaves the last list as it was
    log("read %d rows: %d wells (%d without a usable date, %d without an API number, %d outside the states), %d points and %d earlier ones; newest job %s, settled to %s" % (
        wells.read, len(wells.first), wells.skipped["date"], wells.skipped["api"], wells.skipped["state"], points["n"], history["n"], summary["asOf"], summary["settled"]))
    return summary, points, done


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        bad = check()
        print("newwells: " + ("ok" if not bad else "; ".join(bad)))
        return 1 if bad else 0
    floor = 0.9
    if "--guard-floor" in args:
        floor = float(args[args.index("--guard-floor") + 1])
    seen_path = args[args.index("--seen") + 1] if "--seen" in args else None
    try:
        rows = rows_of_file(args[args.index("--file") + 1]) if "--file" in args else rows_from_network()
        summary, points, done = run(rows, floor=floor, seen_path=seen_path)
    except C.Refused as e:
        log("refused: %s (an answer, not an error; the committed files stay)" % e)
        return 2
    except Exception as e:  # noqa: BLE001  a failure of any kind leaves the committed files alone
        log("failed: " + privacy_check.clean_error(e, 300))
        return 1
    log("wrote " + ", ".join("%s (%s)" % (os.path.basename(p), "changed" if ch else "unchanged") for p, ch in done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
