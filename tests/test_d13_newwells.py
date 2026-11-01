"""Tests for site/pipeline/d13_newwells.py (the national new-wells map, from FracFocus) and d13_us_outline.py (the state outlines it checks points against).

The fixtures are invented disclosure lists built the way the real one is (the registry's column names, dates like "5/1/1955 12:00:00 AM", 14-digit API numbers, "True"/"False" land flags),
packed in a zip. They pin: a well is counted once, on the day of its first disclosure (a second job on it, a sidetrack's API number, the same disclosure twice); the registry's typing errors
(a job in 3012, in 1955, a longitude without its minus sign, a point in another state, a depth of ten feet, 400 million gallons of water) never reach a count or a point wrongly; a month settles
only 120 days after the newest job, so the newest weeks are published but never in the last-12-months figure; only corporations, LLCs and partnerships (and the reviewed list of companies the shared
rule cannot read) are named, and no API number, well name, lease or person's name is in either file; the zip is read by HTTP range requests and never downloaded whole (a server that does not
answer ranges is refused, a 403 is an answer); the validator against deliberate faults; a run that would lose history is refused and writes nothing; and the committed files.

Run: python3 -I tests/test_d13_newwells.py"""
import copy
import csv
import http.server
import io
import json
import os
import random
import re
import sys
import tempfile
import threading
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d13_newwells as W  # noqa: E402
import d13_us_outline as O  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
OUTLINES = W.load_outlines()


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, kind=Exception):
    try:
        fn()
    except kind:
        return True
    return False


HEAD = ["DisclosureId", "JobStartDate", "JobEndDate", "APINumber", "StateName", "CountyName", "OperatorName", "WellName", "Latitude", "Longitude", "Projection", "TVD", "TotalBaseWaterVolume",
        "TotalBaseNonWaterVolume", "FFVersion", "FederalWell", "IndianWell"]
# a point well inside each state's outline, an API state code and a busy county
PLACES = {"Texas": ("42", 31.95, -102.0, "Martin"), "New Mexico": ("30", 32.4, -104.2, "Eddy"), "North Dakota": ("33", 47.9, -103.5, "McKenzie"), "Colorado": ("05", 40.1, -104.6, "Weld"),
          "Oklahoma": ("35", 35.5, -98.0, "Canadian"), "Pennsylvania": ("37", 40.4, -80.1, "Washington"), "Louisiana": ("17", 32.5, -93.5, "De Soto")}
OPS = ["Alpha Energy LLC", "Bravo Operating, Inc.", "Pioneer Natural Resources", "Charlie Petroleum Corporation", "John Q Smith", "Delta Oil and Gas LP", "W.T. Hargrove Estate"]
NAMED = {"ALPHA ENERGY LLC", "BRAVO OPERATING INC", "PIONEER NATURAL RESOURCES", "CHARLIE PETROLEUM CORPORATION", "DELTA OIL AND GAS LP"}
SERIAL = iter(range(1, 10 ** 7))


def mdy(d):
    return "%d/%d/%d 12:00:00 AM" % (d.month, d.day, d.year)


def row(day, state="Texas", op=None, lat=None, lon=None, api=None, county=None, tvd="9500", water="21000000", fed="False", ind="False", proj="NAD83", well="LEASE ALPHA 7H"):
    code, la, lo, cty = PLACES[state]
    n = next(SERIAL)
    return {"DisclosureId": "id-%d" % n, "JobStartDate": mdy(day) if isinstance(day, date) else day, "JobEndDate": mdy(day) if isinstance(day, date) else day,
            "APINumber": api or "%s%03d%05d0000" % (code, 1 + n % 400, n % 100000), "StateName": state, "CountyName": county or cty, "OperatorName": op or OPS[n % len(OPS)], "WellName": well,
            "Latitude": "%.6f" % (la + random.uniform(-0.04, 0.04) if lat is None else lat), "Longitude": "%.6f" % (lo + random.uniform(-0.04, 0.04) if lon is None else lon), "Projection": proj,
            "TVD": tvd, "TotalBaseWaterVolume": water, "TotalBaseNonWaterVolume": "", "FFVersion": "3", "FederalWell": fed, "IndianWell": ind}


def months(first, last):
    return C.month_list(first, last)


def population(per=None, first="2023-01", last="2026-10", newest=date(2026, 10, 20)):
    """Wells in 7 states, every month from `first` to `last`, the newest job on `newest`: enough for the validator's floors (3,000 wells in a year, 1,000 points)."""
    random.seed(13)
    per = per or {"Texas": 150, "New Mexico": 70, "North Dakota": 40, "Colorado": 40, "Oklahoma": 30, "Pennsylvania": 30, "Louisiana": 20}
    rows = []
    for ym in months(first, last):
        y, m = int(ym[:4]), int(ym[5:])
        for state, n in per.items():
            for k in range(n):
                d = date(y, m, 1 + (k * 7) % 27)
                if d > newest:
                    d = newest
                rows.append(row(d, state))
    return rows


def build(rows, today=TODAY):
    w = W.Wells(OUTLINES, today)
    for r in rows:
        w.add(r)
    return w, *W.build(w, today)


def zip_of(rows, name="DisclosureList_1.csv", extra=None):
    buf = io.StringIO()
    wr = csv.DictWriter(buf, HEAD, lineterminator="\r\n")
    wr.writeheader()
    for r in rows:
        wr.writerow(r)
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, "﻿" + buf.getvalue())
        z.writestr("FracFocusRegistry_1.csv", "x" * 2000)  # the 235 MB ingredient files are never read
        z.writestr("readme csv.txt", "dictionary")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return zb.getvalue()


def by_state(summary):
    return {s["id"]: s for s in summary["states"]}


# ------------------------------------------------------------------------------------------------ a well is counted once, on its first job
random.seed(1)
base = [row(date(2025, 3, 10), "Texas", api="42317000010000", op="Alpha Energy LLC")]
w, s, p = build(base + population())
check(len(w.first) == len(base + population()) - 0, "setup: every invented disclosure is its own well")
many = [row(date(2025, 3, 10), "Texas", api="42999000010000"), row(date(2025, 9, 2), "Texas", api="42999000010000"),  # fractured again six months later
        row(date(2025, 3, 10), "Texas", api="42999000010000"),  # the same disclosure filed twice
        row(date(2025, 5, 5), "Texas", api="42999000010101"),  # a sidetrack: same first ten digits
        row(date(2025, 7, 7), "Texas", api="42999000020000"),  # a different well
        row(date(2025, 2, 2), "Texas", api="42888000010000"), row(date(2025, 1, 1), "Texas", api="42888000010000")]  # the earlier job arrives second
w2 = W.Wells(OUTLINES, TODAY)
for r in many:
    w2.add(r)
check(sorted(v[0].isoformat() for v in w2.first.values()) == ["2025-01-01", "2025-03-10", "2025-07-07"], "a well is the first ten digits of its API number, counted once, on the day of its first job, whatever order the rows come in: %s" % sorted(v[0].isoformat() for v in w2.first.values()))
check(w2.read == 7, "every row read is counted in `read`")

# ------------------------------------------------------------------------------------------------ the registry's typing errors
w3 = W.Wells(OUTLINES, TODAY)
bad = [row("12/31/3012 12:00:00 AM"), row("5/1/1955 12:00:00 AM"), row("not a date"), row(""), row(date(2026, 11, 20).strftime("%m/%d/%Y")),  # a job in the future
       row(date(2025, 1, 5), api="123"), row(date(2025, 1, 5), state="Texas", op="Alpha Energy LLC"), ]
bad[-1]["StateName"] = "Atlantis"
for r in bad:
    w3.add(r)
check(len(w3.first) == 0 and w3.skipped["date"] == 5 and w3.skipped["api"] == 1 and w3.skipped["state"] == 1, "a job dated 3012, 1955, in the future, blank or not a date, an API number of three digits and a state that is not one are all left out: %s" % dict(w3.skipped))
w4 = W.Wells(OUTLINES, TODAY)
cases = [row(date(2025, 4, 1), lat=31.95, lon=102.0),  # no minus sign
         row(date(2025, 4, 2), lat=40.7, lon=-74.0),  # Texas well, point in New York
         row(date(2025, 4, 3), lat=0.0, lon=0.0), row(date(2025, 4, 4), lat=None, lon=None),
         row(date(2025, 4, 5), tvd="10", water="400000000"), row(date(2025, 4, 6), tvd="9500", water="21000000", fed="True", ind="True"),
         row(date(2025, 4, 7), lat=31.7, lon=-106.55)]  # El Paso, Texas: inside; right by the New Mexico line
cases[3]["Latitude"] = cases[3]["Longitude"] = ""
for r in cases:
    w4.add(r)
pts = {v[0].isoformat(): v for v in w4.first.values()}
check(pts["2025-04-01"][4] == (31.95, -102.0), "a longitude with no minus sign is read as west (the registry says it must carry one)")
check(pts["2025-04-02"][4] is None and pts["2025-04-03"][4] is None and pts["2025-04-04"][4] is None, "a point in another state, at 0,0 or missing is no point: the well still counts, it is just not on the map")
check(pts["2025-04-05"][5] is None and pts["2025-04-05"][6] is None, "ten feet of depth and 400 million gallons of water are typing errors: not reported, never published")
check(pts["2025-04-06"][7] == 3 and pts["2025-04-01"][7] == 0, "federal and tribal land are two bits: 3 is both, 0 neither")
check(pts["2025-04-07"][4] is not None, "a well on the state's own border is inside it")
check(OUTLINES.contains("TX", -102.0, 31.95) and not OUTLINES.contains("TX", -74.0, 40.7) and not OUTLINES.contains("ZZ", -100, 40),
      "the outline check: Texas holds Midland and not New York; an unknown state holds nothing")
check(not OUTLINES.contains("LA", -89.0, 27.0) and not OUTLINES.contains("TX", -94.0, 28.5), "a point in the open Gulf of America belongs to no state")

# ------------------------------------------------------------------------------------------------ the numbers
rows = population()
w, s, p = build(rows)
S = by_state(s)
check(s["asOf"] == "2026-10-20" and s["settled"] == "2026-05-31" and s["lagDays"] == 120, "the newest job is the as-of day and the last settled month ended 120 or more days before it: %s %s" % (s["asOf"], s["settled"]))
check(s["months"][0] == "2011-01" and s["months"][-1] == "2026-10" and s["months"] == C.month_list("2011-01", "2026-10"), "the months run from the registry's first month, 2011-01, to the newest job's month, no gap")
i = s["months"].index("2026-05")
check(S["TX"]["p12"] == sum(S["TX"]["new"][i - 11:i + 1]) == 150 * 12 and S["TX"]["prev12"] == 150 * 12, "the last 12 months are the 12 settled months to May 2026 (not the newer ones still filling in): %d %d" % (S["TX"]["p12"], S["TX"]["prev12"]))
check(S["TX"]["new"][-1] > 0 and S["TX"]["new"][-2] > 0, "the newest months are in the series (published, to be drawn as filling in)")
check([x["id"] for x in s["states"]] == sorted((x["id"] for x in s["states"]), key=lambda k: (-S[k]["p12"], S[k]["name"])), "the states are ranked by their last 12 months")
check(S["TX"]["latest"] == "2026-10-20", "each state carries its own newest job day")
check(S["TX"]["located"] == 1.0, "the share of the year's wells with a usable point is published")
check(s["wells"] == len(w.first) and s["read"] == len(rows), "wells and rows read are published")
check(S["TX"]["counties"][0][0] == "Martin" and S["ND"]["counties"][0][0] == "McKenzie", "a county keeps its capital after Mc (McKenzie)")
ops = {o for st in s["states"] for o, n in st["operators"]}
check(ops and {C.D8.nameable(o) or W.key_of(o) in W.KNOWN_ORGANIZATIONS for o in ops} == {True}, "every operator named is a corporation, LLC or partnership by the one rule or on the reviewed list: %s" % sorted(ops))
check("John Q Smith" not in json.dumps(s) and "Hargrove" not in json.dumps(s) and "John Q Smith" not in json.dumps(p) and "Hargrove" not in json.dumps(p), "a person's name and an estate are in neither file")
tot = S["TX"]["namedShare"]
check(tot is not None and abs(tot - 5 / 7) < 0.03, "namedShare is the share of the year's wells whose operator may be named: %s (5 of 7 invented operators)" % tot)
check(S["TX"]["tvd"] == 9500 and S["TX"]["water"] == 21.0, "median depth (feet) and water (million gallons) of the year's wells")

# ------------------------------------------------------------------------------------------------ the points
check(p["n"] == len(p["lat"]) == len(p["d"]) and p["t0"] == "2024-11-01" and p["asOf"] == s["asOf"], "points start at the first day of the 24th month back from the newest job: %s" % p["t0"])
check(p["d"] == sorted(p["d"]) and max(p["d"]) == (date(2026, 10, 20) - date(2024, 11, 1)).days, "points are in day order and the newest is the as-of day")
k = 0
d0 = date.fromisoformat(p["t0"])
check(all(150000 <= la <= 750000 and -1800000 <= lo <= -600000 for la, lo in zip(p["lat"], p["lon"])) and all(isinstance(x, int) for x in p["lat"] + p["lon"]), "latitude and longitude are whole ten-thousandths of a degree")
check(all(OUTLINES.contains(p["states"][st], lo / 1e4, la / 1e4) for la, lo, st in zip(p["lat"][:400], p["lon"][:400], p["s"][:400])), "every point lies in the state it is filed under")
check(p["states"] == [x["id"] for x in s["states"]], "a point's state is an index into the summary's ranked states")
check(all(p["counties"][c][0] == p["states"][st] for c, st in zip(p["c"], p["s"]) if c >= 0), "a point's county belongs to its state")
check(all(p["ops"][o].upper().replace(",", " ").replace("  ", " ") and W.may_name(p["ops"][o]) for o in p["o"] if o >= 0) and -1 in p["o"], "the operator table holds only names that may be named, and an operator that may not be is -1")
check(set(p["tvd"]) == {95} and set(p["h2o"]) == {210}, "depth is in hundreds of feet and water in hundreds of thousands of gallons")
text = json.dumps(s) + json.dumps(p)
check(not re.search(r"\d{10,}", text) and "LEASE ALPHA" not in text and "id-" not in text, "no API number, well name, lease or registry id is in either file")
check(all(k in p for k in ("lat", "lon", "d", "s", "c", "o", "tvd", "h2o", "f")) and "v" in p and p["v"] == 1, "the columns are all there, and the document's version is not a column")
check(W.validate_summary(s, TODAY) == [] and W.validate_points(p, s) == [], "the document and its points pass their validators: %s" % (W.validate_summary(s, TODAY) + W.validate_points(p, s))[:3])

# ------------------------------------------------------------------------------------------------ the history: every located well from the registry's start
hist = W.build_history(w, s)
d0h = date.fromisoformat(hist["t0"])
located_before = [r for r in w.first.values() if r[4] and r[0] < date(2025, 1, 1)]
check(hist["t0"] == "2011-01-01" and hist["until"] == "2025-01-01" and "asOf" not in hist and hist["n"] == len(located_before) > 1000, "the history runs from 2011-01-01 to the January 1 before the newest job's year, and holds every located well in it: %d" % hist["n"])
check(hist["states"] == p["states"] and hist["d"] == sorted(hist["d"]) and max(hist["d"]) < (date(2025, 1, 1) - d0h).days and all(k in hist for k in W.COLS) and hist["v"] == 1,
      "it uses the points file's columns and state order, in day order, and nothing on or after its end")
check(hist["until"] >= p["t0"] and hist["until"] > p["t0"] and (date.fromisoformat(hist["until"]) - date.fromisoformat(p["t0"])).days < 366, "it reaches the points file's first day, overlapping it by under a year (the page drops the overlap): %s over %s" % (hist["until"], p["t0"]))
check(all(OUTLINES.contains(hist["states"][st], lo / 1e4, la / 1e4) for la, lo, st in zip(hist["lat"][:400], hist["lon"][:400], hist["s"][:400])) and all(hist["counties"][c][0] == hist["states"][st] for c, st in zip(hist["c"], hist["s"]) if c >= 0),
      "its points lie in their states and its counties belong to them")
check(W.validate_points(hist, s, history=True) == [] and W.validate_pair(p, hist) == [], "it passes its validator, and the pair passes: %s" % (W.validate_points(hist, s, history=True) + W.validate_pair(p, hist))[:3])
check(not re.search(r"\d{10,}", json.dumps(hist)) and "LEASE ALPHA" not in json.dumps(hist) and "John Q Smith" not in json.dumps(hist) and "Hargrove" not in json.dumps(hist), "no API number, well name, lease or person is in it either")
check(W.history_end(date(2026, 10, 20)) == date(2025, 1, 1) and W.history_end(date(2027, 1, 3)) == date(2026, 1, 1) and W.history_end(date(2026, 12, 31)) == date(2025, 1, 1), "the end moves once a year, on January 1")
for asof in (date(2026, 1, 2), date(2026, 6, 30), date(2026, 12, 31), date(2027, 1, 1)):  # the history always reaches the points' first day: no gap, in any month
    first_pt = date.fromisoformat(C.add_months(C.month_of(asof), -(W.POINT_MONTHS - 1)) + "-01")
    check(W.history_end(asof) >= first_pt, "no gap between the history and the points for a newest job on %s (%s, %s)" % (asof, W.history_end(asof), first_pt))
gh = copy.deepcopy(hist)
faults_h = {
    "an end that is not the year's start": lambda d: d.update(until="2024-12-31"), "a start that is not the registry's": lambda d: d.update(t0="2012-01-01"), "a day past its end": lambda d: d["d"].__setitem__(len(d["d"]) - 1, 99999),
    "states unlike the summary's": lambda d: d["states"].reverse(), "a column too short": lambda d: d["lat"].pop(), "a well of a person": lambda d: d["ops"].append("Clay Hamilton"),
    "most wells missing": lambda d: [d.update(n=len(d["lat"]) // 2)] and [d[k].__delitem__(slice(len(d[k]) // 2, None)) for k in W.COLS],
}
for name, fn in faults_h.items():
    d = copy.deepcopy(gh)
    fn(d)
    check(W.validate_points(d, s, history=True) != [], "history fault refused: " + name)
gap = copy.deepcopy(gh)
gap["until"] = "2024-01-01"
check(W.validate_pair(p, gap) != [], "a history that ends before the points start is refused: wells in between would be lost")

# ------------------------------------------------------------------------------------------------ the list of companies the shared rule cannot read
check(all(C.D8.nameable(n) is False for n in ("Pioneer Natural Resources", "Occidental Oil and Gas", "XTO Energy/ExxonMobil")), "setup: the shared rule alone would leave the three biggest drillers unnamed")
check(all(W.may_name(n) for n in ("Pioneer Natural Resources", "Occidental Oil and Gas", "XTO Energy/ExxonMobil", "pioneer natural resources")) and not W.may_name("Pioneer Natural Resources Estate") and not W.may_name("") and not W.may_name("Clay Hamilton"),
      "a reviewed company is named whatever its case; a person is not; an estate is not even if the rest of the name matches")
check(not any(C.D8.NOT_BUSINESS.search(n) for n in W.KNOWN_ORGANIZATIONS) and all(n == n.upper() and "," not in n for n in W.KNOWN_ORGANIZATIONS), "no name on the list is a trust, an estate or a dba, and each is in the normal form")

# ------------------------------------------------------------------------------------------------ reading the zip without downloading it
zb = zip_of(population(first="2025-01", last="2025-03"))
calls = []


def fetch(a, b):
    calls.append((a, b))
    return zb[a:b + 1]


rf = W.RangeFile(fetch, len(zb), keep=2)
with zipfile.ZipFile(rf) as z:
    rows_back = list(W.rows_of_zip(z))
check(len(rows_back) == len(population(first="2025-01", last="2025-03")) and rows_back[0]["OperatorName"] and rows_back[0]["DisclosureId"].startswith("id-"), "the disclosure list is read through ranges, a byte-order mark and CRLF line ends and all")
check(rf.requests == len(calls) and all(b - a + 1 <= W.BLOCK for a, b in calls) and sum(b - a + 1 for a, b in calls) < len(zb) * 1.0 + W.BLOCK, "it asked for blocks of at most 1 MB: %d requests for a zip of %d bytes" % (len(calls), len(zb)))
rf2 = W.RangeFile(lambda a, b: zb[a:b + 1], len(zb))
rf2.seek(-22, 2)
tail = rf2.read(22)
check(tail == zb[-22:] and rf2.tell() == len(zb) and rf2.read(5) == b"" and rf2.seek(0) == 0 and rf2.read(2) == b"PK", "seek from the end, read past the end, back to the start")
check(raises(lambda: W.RangeFile(lambda a, b: b"short", 5000).read(100), OSError), "a server that returns fewer bytes than the range is an error, not a silent hole")
only_big = zip_of([], name="DisclosureList_1.csv")
check(raises(lambda: list(W.rows_of_zip(zipfile.ZipFile(io.BytesIO(zip_of(population(first="2025-01", last="2025-01"), name="Other.csv")))))), "a zip with no DisclosureList_N.csv is refused")
cut = io.BytesIO()
with zipfile.ZipFile(cut, "w") as z:
    z.writestr("DisclosureList_1.csv", "DisclosureId,JobStartDate\r\n1,1/1/2025\r\n")
check(raises(lambda: list(W.rows_of_zip(zipfile.ZipFile(io.BytesIO(cut.getvalue()))))), "a list without the columns the producer needs is refused (a changed layout must not read as no wells)")
two = zip_of(population(first="2025-01", last="2025-01"), extra={"DisclosureList_2.csv": "﻿" + ",".join(HEAD) + "\r\n"})
with zipfile.ZipFile(io.BytesIO(two)) as z:
    check(W.disclosure_members(z) == ["DisclosureList_1.csv", "DisclosureList_2.csv"], "when the registry splits its list into two files, both are read, in order")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/forbidden.zip":
            self.send_response(403)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if self.path == "/norange.zip" or not rng:
            self.send_response(200)
            self.send_header("Content-Length", str(len(zb)))
            self.end_headers()
            self.wfile.write(zb)
            return
        a, b = (int(x) for x in re.match(r"bytes=(\d+)-(\d+)", rng).groups())
        b = min(b, len(zb) - 1)
        self.send_response(206)
        self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(zb)))
        self.send_header("Content-Length", str(b - a + 1))
        self.end_headers()
        self.wfile.write(zb[a:b + 1])


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base_url = "http://127.0.0.1:%d" % srv.server_address[1]
for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(k, None)
got = list(W.rows_of_zip(zipfile.ZipFile(W.RangeFile(*(lambda f_s: (f_s[0], f_s[1]))(W.http_range(base_url + "/ok.zip"))))))
check(len(got) == len(rows_back), "over HTTP: the size from a one-byte range, then the member by ranges (%d rows)" % len(got))
check(raises(lambda: W.http_range(base_url + "/norange.zip"), ValueError), "a server that does not answer ranges is refused: the zip is never downloaded whole")
check(raises(lambda: W.http_range(base_url + "/forbidden.zip"), C.Refused), "a 403 is an answer (Refused), never retried")
srv.shutdown()

# ------------------------------------------------------------------------------------------------ whole runs
tmp = tempfile.mkdtemp()
out = os.path.join(tmp, "out")
rows = population()
summary, points, done = W.run(rows, out_dir=out, today=TODAY, outlines=OUTLINES)
check(all(ch for _, ch in done) and len(done) == 5 and W.check(out) == [] and sorted(os.listdir(out)) == sorted(W.FILES + W.DETAIL_FILES), "a first run writes the three files and the two detail files and they pass the check")
before = {f: open(os.path.join(out, f), "rb").read() for f in W.FILES + W.DETAIL_FILES}
summary2, points2, done2 = W.run(list(rows), out_dir=out, today=TODAY, outlines=OUTLINES)
check(not any(ch for _, ch in done2) and before == {f: open(os.path.join(out, f), "rb").read() for f in before}, "the same registry again changes nothing (so a weekly run commits nothing)")
shrunk = [r for r in rows if not r["JobStartDate"].startswith(("1/", "2/", "3/", "4/", "5/", "6/", "7/"))]
check(raises(lambda: W.run(shrunk, out_dir=out, today=TODAY, outlines=OUTLINES), ValueError) and before == {f: open(os.path.join(out, f), "rb").read() for f in before}, "a run that lost history (a truncated read) is refused and the committed files stay exactly as they were")
more = rows + [row(date(2026, 10, 25), "Texas") for _ in range(5)]
summary3, points3, done3 = W.run(more, out_dir=out, today=TODAY, outlines=OUTLINES)
check(summary3["asOf"] == "2026-10-25" and points3["n"] == points["n"] + 5 and any(ch for _, ch in done3), "a registry with five newer wells is written and its as-of day moves")
check(open(os.path.join(out, "points-history.json"), "rb").read() == before["points-history.json"], "five newer wells change the summary and the points, not the history (it moves once a year)")
check(raises(lambda: W.run([], out_dir=out, today=TODAY, outlines=OUTLINES), ValueError), "an empty registry is refused")
zpath = os.path.join(tmp, "FracFocusCSV.zip")
open(zpath, "wb").write(zip_of(rows))
os.environ["D13_DIR"] = out
check(len(list(W.rows_of_file(zpath))) == len(rows) and len(list(W.rows_of_file(zpath))) == len(rows), "--file reads a local zip")
csvpath = os.path.join(tmp, "list.csv")
open(csvpath, "w", encoding="utf-8-sig", newline="").write(zip_of(rows) and "")  # an empty file has no header: refused
check(raises(lambda: list(W.rows_of_file(csvpath))), "an empty csv is refused")


# ------------------------------------------------------------------------------------------------ the detail files: the same wells, and what else the registry says of them
detail, dhist = W.load_detail(out)
committed_points, history_doc = W.load_committed(out)[1], W.load_history(out)  # the folder holds the last of the runs above
check(detail is not None and dhist is not None and detail["n"] == committed_points["n"] and dhist["n"] == history_doc["n"] and detail["asOf"] == committed_points["asOf"] and dhist["until"] == history_doc["until"],
      "a run writes the detail of the points and of the history, the same number of rows as each")
check(all(isinstance(x, int) and not isinstance(x, bool) for c in ("api", "end", "tvd", "wg", "nw", "dat") for x in detail[c]) and W.validate_detail(detail, committed_points) == [], "the detail holds whole numbers only (no name, no text) and passes its validator")


def special(day, api, lat, lon, state="Texas", end="same", nonwater="", proj="NAD83", tvd="12345", water="21000000"):
    r = row(day, state, op="Alpha Energy LLC", lat=lat, lon=lon, api=api, tvd=tvd, water=water, proj=proj)
    r["JobEndDate"] = mdy(day + timedelta(days=end)) if isinstance(end, int) else ("" if end == "blank" else r["JobEndDate"])
    r["TotalBaseNonWaterVolume"] = nonwater
    return r


random.seed(9)
SP = [special(date(2026, 3, 3), "42317000010000", 31.9001, -102.0001, end=6, nonwater="250000", proj="Nad27"),
      special(date(2026, 3, 4), "42317000020000", 31.9002, -102.0002, end=-2, nonwater="0", proj="WGS84"),
      special(date(2026, 3, 5), "42317000030000", 31.9003, -102.0003, end=400, nonwater="", proj=""),
      special(date(2026, 3, 6), "42317000040000", 31.9004, -102.0004, end="blank", nonwater="4000000000", proj="NAD27"),
      special(date(2026, 3, 7), "05123000050000", 40.1005, -104.6005, "Colorado", end=0, nonwater="1500000", tvd="", water="600"),
      special(date(2023, 6, 6), "42317000060000", 31.9006, -102.0006, end=3, nonwater="75000", proj="NAD83")]
wd = W.Wells(OUTLINES, TODAY)
for r in population() + SP:
    wd.add(r)
sm, pt = W.build(wd)
hs = W.build_history(wd, sm)
dt = W.build_detail(wd, pt)
dh = W.build_history_detail(wd, hs)


def of(doc, base, api):
    i = doc["api"].index(int(api[:10]))
    return i, {c: doc[c][i] for c in ("api", "end", "tvd", "wg", "nw", "dat")}


i1, d1 = of(dt, pt, "42317000010000")
check(d1 == {"api": 4231700001, "end": 6, "tvd": 12345, "wg": 21000000, "nw": 250000, "dat": 1}, "a well's detail: its API number (first ten digits), the job's last day 6 days after its first, the exact depth and water, the non-water fluid and the datum (Nad27 in the registry's own spelling): %s" % d1)
i2, d2 = of(dt, pt, "42317000020000")
check(d2["end"] == -1 and d2["nw"] == 0 and d2["dat"] == 3, "a job that ends before it starts has no end; no non-water fluid is a real 0, not unknown; WGS84 is 3: %s" % d2)
i3, d3 = of(dt, pt, "42317000030000")
check(d3["end"] == -1 and d3["nw"] == -1 and d3["dat"] == 0, "a job that ends 400 days after it starts has no end; a blank non-water volume is unknown, and a blank datum is 0: %s" % d3)
i4, d4 = of(dt, pt, "42317000040000")
check(d4["end"] == -1 and d4["nw"] == -1 and d4["dat"] == 1, "a blank end is unknown; four billion gallons of non-water fluid is a typing error and is left out: %s" % d4)
i5, d5 = of(dt, pt, "05123000050000")
check(d5["api"] == 512300005 and "%010d" % d5["api"] == "0512300005", "an API number that starts with zero (a state code below 10) is a number the page pads back to ten digits: %s" % d5["api"])
check(d5["tvd"] == -1 and d5["wg"] == -1 and d5["nw"] == 1500000, "an unusable depth and water are unknown (-1), a usable non-water volume is kept: %s" % d5)
# row i of the detail is row i of the points: the point of a well is the point it was given
for api, la, lo in (("42317000010000", 31.9001, -102.0001), ("42317000040000", 31.9004, -102.0004), ("05123000050000", 40.1005, -104.6005)):
    i, _ = of(dt, pt, api)
    check(pt["lat"][i] == round(la * 1e4) and pt["lon"][i] == round(lo * 1e4), "row of API %s in the detail is the same well's row in the points (%.4f, %.4f)" % (api[:10], la, lo))
j6, d6 = of(dh, hs, "42317000060000")
check(hs["lat"][j6] == round(31.9006 * 1e4) and d6["end"] == 3 and d6["nw"] == 75000 and dh["until"] == hs["until"], "the history's detail lines up with the history's points the same way")
check(W.validate_detail(dt, pt) == [] and W.validate_detail(dh, hs, history=True) == [], "the detail files of the invented registry pass their validator: %s" % (W.validate_detail(dt, pt) + W.validate_detail(dh, hs, history=True))[:2])

bad_detail = {
    "a column shorter than the points": lambda d: d["api"].pop(),
    "a different number of rows": lambda d: d.__setitem__("n", d["n"] - 1),
    "an API number that is too short to be one": lambda d: d["api"].__setitem__(0, 12345),
    "an API number with more than ten digits": lambda d: d["api"].__setitem__(0, 12345678901),
    "a job end over a year after its start": lambda d: d["end"].__setitem__(0, 400),
    "a depth under 500 feet": lambda d: d["tvd"].__setitem__(0, 300),
    "more than 150 million gallons of water": lambda d: d["wg"].__setitem__(0, 400_000_000),
    "a datum that is not one of the four": lambda d: d["dat"].__setitem__(0, 4),
    "an API number that is text": lambda d: d["api"].__setitem__(0, "4231700001"),
    "a key it should not have": lambda d: d.__setitem__("well", ["x"] * d["n"]),
    "a different first day than its points": lambda d: d.__setitem__("t0", "2020-01-01"),
    "a different asOf than its points": lambda d: d.__setitem__("asOf", "2020-01-01"),
    "rows in another order than the points": lambda d: [d.__setitem__(c, d[c][::-1]) for c in ("api", "end", "tvd", "wg", "nw", "dat")],
}
for name, fn in bad_detail.items():
    d = copy.deepcopy(dt)
    fn(d)
    check(W.validate_detail(d, pt) != [], "the detail validator refuses " + name)
d = copy.deepcopy(dt)
d["api"] = [4231700001 + k for k in range(d["n"])]
check(any("belong to their point's state" in x for x in W.validate_detail(d, pt)), "a detail whose API numbers do not belong to its points' states is refused for that reason, not only for its shape")
d = copy.deepcopy(dt)
d["tvd"][i1] = 20000  # a depth that is not the points' (12,300 ft) for that well
check(any("depth" in x for x in W.validate_detail(d, pt)), "a depth that does not match the points' rounded one is refused (the two files must be the same wells)")
d = copy.deepcopy(dt)
d["wg"][i1] = 90_000_000
check(any("water" in x for x in W.validate_detail(d, pt)), "a water volume that does not match the points' rounded one is refused (the two files must be the same wells)")
nowhere = tempfile.mkdtemp()
check(raises(lambda: W.write(sm, pt, nowhere, hs, None, {**dt, "n": dt["n"] - 1}, dh), ValueError) and os.listdir(nowhere) == [], "a run whose detail does not match its points writes nothing")


def aligned(detail_doc, points_doc, wells):
    """Row by row, against the wells themselves: the well whose API number the detail gives at row i has the point, the day and the state of the points' row i."""
    t0 = date.fromisoformat(points_doc["t0"])
    for i in range(points_doc["n"]):
        r = wells.first.get("%010d" % detail_doc["api"][i])
        if r is None or round(r[4][0] * 1e4) != points_doc["lat"][i] or round(r[4][1] * 1e4) != points_doc["lon"][i] or (r[0] - t0).days != points_doc["d"][i] or r[1] != points_doc["states"][points_doc["s"][i]]:
            return False
    return True


check(aligned(dt, pt, wd) and aligned(dh, hs, wd), "every row of both detail files is the same well as the points' row (checked against the wells themselves, %d + %d rows)" % (dt["n"], dh["n"]))


def other_order(wells, points_doc):
    """A detail built by a different sort: the same wells, but wells of one day and state in another order."""
    rows = sorted((r for r in wells.first.values() if r[4] and r[0] >= date.fromisoformat(points_doc["t0"])), key=lambda r: (r[0], r[1], r[4][1], r[4][0]))
    return W.encode_detail(rows, points_doc)


check(not aligned(other_order(wd, pt), pt, wd), "mutant (a detail built in another tie order) is noticed by the row-by-row check: this is why both files are built from one function, points_rows")
# no API number, and no run of ten digits, anywhere but the two detail files
loose = [f for f in W.FILES if re.search(r"\d{10,}", open(os.path.join(out, f), encoding="utf-8").read())]
check(loose == [] and W.validate_points(points, summary) == [], "no file but the two detail files holds an API number or a run of ten digits (%s)" % loose)
check(any("10 or more digits" in x for x in W.validate_points({**points, "ops": points["ops"] + ["Alpha Energy 4231700001 LLC"]}, summary)), "the points file still refuses a ten-digit run: the exception is for the two detail files alone")

# ------------------------------------------------------------------------------------------------ the daily comparison: wells new since the last download, and what Texas's daily reports carried
import d13_arrivals as ARR  # noqa: E402
arr_out = os.path.join(tmp, "arrivals")
seen_file = os.path.join(tmp, "kept", "ff-seen.txt.gz")
daily_dir = os.path.join(tmp, "daily-fixture")
os.makedirs(daily_dir)
open(os.path.join(daily_dir, "2026-10-28.json"), "w").write(json.dumps({"permits": {"rows": [["0919696", "317", "08", "1", "X", 9000, "H", "31799999", None, None, None]]}, "surveys": {"rows": []}}))
base_rows = population()
S0, P0, done0 = W.run(base_rows, out_dir=arr_out, today=TODAY, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1)
log0 = ARR.read(os.path.join(arr_out, ARR.NAME))
check(os.path.exists(seen_file) and len(ARR.load_seen(seen_file, 1)) == len(base_rows) and log0 == {"v": 1, "checked": None, "since": None, "against": {"TX": {"wells": 1, "from": "2026-10-28"}}, "days": []},
      "a first run with no list from the last download keeps this one as the baseline and reports no arrivals (it does not call every well new)")
new_rows = base_rows + [row(date(2026, 10, 25), "Texas", api="42317999990000"), row(date(2026, 10, 26), "Texas", api="42317888880000"), row(date(2026, 10, 26), "Texas", api="42317777770000"),
                        row(date(2026, 10, 27), "Oklahoma"), row(date(2026, 10, 27), "Oklahoma"), row(date(2026, 8, 3), "New Mexico")]  # one of them was in a Texas daily report; the last is a late disclosure of an August job
S1, P1, done1 = W.run(new_rows, out_dir=arr_out, today=TODAY, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1)
log1 = ARR.read(os.path.join(arr_out, ARR.NAME))
day1 = log1["days"][0]
t1 = {r[0]: r for r in day1["states"]}
check(log1["checked"] == "2026-10-31" and log1["since"] == "2026-10-31" and len(log1["days"]) == 1 and day1["day"] == "2026-10-31" and day1["found"] == 6 and day1["removed"] == 0, "the second download finds the six wells that were not in the first, on the day they arrived: %s" % day1)
check(t1["TX"] == ["TX", 3, 1] and t1["OK"] == ["OK", 2, None] and t1["NM"] == ["NM", 1, None], "one of the three Texas wells was already in a Texas daily report and is counted so; Oklahoma's and New Mexico's cannot be checked and say null: %s" % day1["states"])
check(log1["against"] == {"TX": {"wells": 1, "from": "2026-10-28"}}, "the log says what the Texas match covered: one well, from the first day that carried API numbers: %s" % log1["against"])
check(ARR.load_seen(seen_file, 1) == {re.sub(r"\D", "", r["APINumber"])[:10] for r in new_rows} and W.check(arr_out) == [], "the list kept moves on to this download, and the committed folder passes its check with the log")
text = json.dumps(log1)
check(not re.search(r"\d{10,}", text) and "317999999" not in text and "LEASE" not in text, "the log holds counts only: no API number, well name or lease")
before = {f: open(os.path.join(arr_out, f), "rb").read() for f in (*W.FILES, ARR.NAME)}
W.run(new_rows, out_dir=arr_out, today=TODAY, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1)
check(before == {f: open(os.path.join(arr_out, f), "rb").read() for f in before}, "the same download again the same day finds nothing new and changes nothing (no file, no log)")
nxt = date(2026, 11, 1)
W.run(new_rows, out_dir=arr_out, today=nxt, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1)
log2 = ARR.read(os.path.join(arr_out, ARR.NAME))
check(log2["checked"] == "2026-11-01" and log2["days"] == log1["days"], "the next day, with nothing new, only moves `checked`: the log has no empty day")
gone = [r for r in new_rows if r is not new_rows[-1]]
W.run(gone, out_dir=arr_out, today=nxt, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1)
log3 = ARR.read(os.path.join(arr_out, ARR.NAME))
check(log3["days"][0]["day"] == "2026-11-01" and log3["days"][0]["found"] == 0 and log3["days"][0]["removed"] == 1 and log3["days"][1] == day1, "a well gone from the download (a correction or a deletion) is counted apart, never as a new well")
before_fail = {f: open(os.path.join(arr_out, f), "rb").read() for f in (*W.FILES, ARR.NAME)}
kept_before = open(seen_file, "rb").read()
check(raises(lambda: W.run(shrunk, out_dir=arr_out, today=nxt, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir, min_seen=1), ValueError)
      and before_fail == {f: open(os.path.join(arr_out, f), "rb").read() for f in before_fail} and open(seen_file, "rb").read() == kept_before, "a refused run (a truncated read) leaves the files, the log and the list kept exactly as they were")
plain = os.path.join(tmp, "no-arrivals")
W.run(base_rows, out_dir=plain, today=TODAY, outlines=OUTLINES)
check(not os.path.exists(os.path.join(plain, ARR.NAME)) and W.check(plain) == [], "a run without a kept list (the producer's weekly use, or by hand) writes no log and still passes its check")
os.makedirs(os.path.dirname(seen_file), exist_ok=True)
ARR.write_seen(seen_file, {"4200000001"})
W.run(base_rows, out_dir=os.path.join(tmp, "short"), today=TODAY, outlines=OUTLINES, seen_path=seen_file, daily_dir=daily_dir)
check(ARR.read(os.path.join(tmp, "short", ARR.NAME))["days"] == [] and len(ARR.load_seen(seen_file, 1)) == len(base_rows), "a list from the last download that is far too short is no baseline: nothing is called new, and today's replaces it")
real_rep = ARR.read_texas
ARR.read_texas = lambda *a, **k: (set(), None)
mut_out = os.path.join(tmp, "mut")
W.run(base_rows, out_dir=mut_out, today=TODAY, outlines=OUTLINES, seen_path=os.path.join(tmp, "mutkept", "s.gz"), daily_dir=daily_dir, min_seen=1)
S_m = os.path.join(tmp, "mutkept", "s.gz")
W.run(new_rows, out_dir=mut_out, today=TODAY, outlines=OUTLINES, seen_path=S_m, daily_dir=daily_dir, min_seen=1)
ARR.read_texas = real_rep
check({r[0]: r for r in ARR.read(os.path.join(mut_out, ARR.NAME))["days"][0]["states"]}["TX"] == ["TX", 3, 0], "mutant (the Texas reports not read) reports none as already carried: the match is what keeps a well from being reported twice")

# ------------------------------------------------------------------------------------------------ the validators against deliberate faults
good_s, good_p = copy.deepcopy(summary), copy.deepcopy(points)


def mut_s(fn):
    d = copy.deepcopy(good_s)
    fn(d)
    return d


def mut_p(fn):
    d = copy.deepcopy(good_p)
    fn(d)
    return d


faults_s = {
    "version": lambda d: d.update(v=2), "as-of in the future": lambda d: d.update(asOf="2027-01-01"), "settled not a month end": lambda d: d.update(settled="2026-05-30"),
    "settled too late for the lag": lambda d: d.update(settled="2026-09-30"), "months with a gap": lambda d: d["months"].pop(5), "a count that is text": lambda d: d["states"][0]["new"].__setitem__(3, "9"),
    "p12 that is not the sum": lambda d: d["states"][0].update(p12=1), "an operator that may not be named": lambda d: d["states"][0]["operators"].insert(0, ["John Q Smith", 99999]),
    "operators out of order": lambda d: d["states"][0]["operators"].reverse(), "a county with a number in it": lambda d: d["states"][0]["counties"].insert(0, ["Unit 12345", 99999]),
    "a state that is not one": lambda d: d["states"][0].update(id="ZZ"), "states out of rank order": lambda d: d["states"].reverse(), "a web address in the data": lambda d: d.update(note="see https://x.example/y or write a@b.co"),
    "a phone number": lambda d: d["states"][0]["counties"].insert(0, ["Call 432-555-1234", 99999]), "a read that lost the registry": lambda d: [s.update(p12=1, prev12=1, new=[0] * (len(d["months"]) - 24) + [1] * 24) for s in d["states"]],
    "wells above rows read": lambda d: d.update(wells=d["read"] + 1), "a share above one": lambda d: d["states"][0].update(located=1.5), "latest after as-of": lambda d: d["states"][0].update(latest="2030-01-01"),
}
for name, fn in faults_s.items():
    check(W.validate_summary(mut_s(fn), TODAY) != [], "summary fault refused: " + name)
faults_p = {
    "a column too short": lambda d: d["lat"].pop(), "a latitude in the ocean": lambda d: d["lat"].__setitem__(5, 5000), "a longitude in China": lambda d: d["lon"].__setitem__(5, 1000000),
    "a day before t0": lambda d: d["d"].__setitem__(0, -1), "days out of order": lambda d: d["d"].__setitem__(len(d["d"]) // 2, 0), "a state index past the table": lambda d: d["s"].__setitem__(1, 99),
    "a county of another state": lambda d: d["c"].__setitem__(0, next(i for i, c in enumerate(d["counties"]) if c[0] != d["states"][d["s"][0]])), "an operator that may not be named": lambda d: d["ops"].append("Clay Hamilton"),
    "depth of a mile of feet": lambda d: d["tvd"].__setitem__(2, 9999), "a land flag of 7": lambda d: d["f"].__setitem__(3, 7), "states unlike the summary's": lambda d: d["states"].reverse(),
    "as-of unlike the summary's": lambda d: d.update(asOf="2026-10-19"), "an API-like number": lambda d: d["ops"].append("Alpha 4231700001 Energy LLC"), "fewer points than the registry holds": lambda d: [d.update(n=len(d["lat"]) // 3)] and [d[k].__delitem__(slice(len(d[k]) // 3, None)) for k in ("lat", "lon", "d", "s", "c", "o", "tvd", "h2o", "f")],
}
for name, fn in faults_p.items():
    check(W.validate_points(mut_p(fn), good_s) != [], "points fault refused: " + name)
check(not raises(lambda: W.write(good_s, good_p, os.path.join(tmp, "w")), ValueError) and raises(lambda: W.write(mut_s(faults_s["p12 that is not the sum"]), good_p, os.path.join(tmp, "w2")), ValueError) and not os.path.exists(os.path.join(tmp, "w2")),
      "a bad document is never written: the folder is not even made")

# ------------------------------------------------------------------------------------------------ mutants: each puts an old failure back
orig_add = W.Wells.add


def every_disclosure(self, row):  # counts a second job on a well as another new well
    n = len(self.first)
    orig_add(self, row)
    api = re.sub(r"\D", "", row.get("APINumber") or "")
    if len(self.first) == n and len(api) >= 10 and C.parse_day(row.get("JobStartDate"), self.today):
        self.first[api + str(self.read)] = self.first[api[:10]]


W.Wells.add = every_disclosure
wm, sm, pm = build(many)
W.Wells.add = orig_add
check(len(wm.first) > 3, "mutant (every disclosure is a new well) is visible: %d wells instead of 3" % len(wm.first))
orig_may = W.may_name
named_rows = population()
for r in named_rows:
    if r["JobStartDate"].startswith(("2/", "3/", "4/")) and r["JobStartDate"].endswith("/2026 12:00:00 AM") and r["StateName"] == "Texas":
        r["OperatorName"] = "Jane Roe"
with_rule = build(named_rows)
W.may_name = lambda n: True
without_rule = build(named_rows)
W.may_name = orig_may
check("Jane Roe" not in json.dumps(with_rule[1]) + json.dumps(with_rule[2]), "with the naming rule a person trading under her own name is in neither file")
check("Jane Roe" in json.dumps(without_rule[1]) + json.dumps(without_rule[2]), "mutant (no naming rule) names her: the rule is what keeps a name out")
orig_in = W.Outlines.contains
W.Outlines.contains = lambda self, *a, **k: True
wo = W.Wells(OUTLINES, TODAY)
wo.add(row(date(2025, 4, 2), lat=40.7, lon=-74.0))
W.Outlines.contains = orig_in
check(list(wo.first.values())[0][4] is not None, "mutant (no outline check) keeps a Texas well in New York: the check is what drops it")
orig_lag = W.LAG_DAYS
W.LAG_DAYS = 0
sl, _ = W.build(w, TODAY)
W.LAG_DAYS = orig_lag
check(sl["settled"] != s["settled"], "mutant (no lag) settles the newest months: the lag is what keeps the last 12 months to complete ones")

# ------------------------------------------------------------------------------------------------ the committed files
if os.environ.get("D13_DIR"):
    del os.environ["D13_DIR"]
cs, cp = W.load_committed(W.OUT)
ch = W.load_history(W.OUT)
check(cs is not None and cp is not None and ch is not None and W.check(W.OUT) == [], "the committed summary.json, points.json and points-history.json pass the validator: %s" % W.check(W.OUT)[:2])
if cs:
    check(cs["states"][0]["id"] == "TX" and sum(x["p12"] for x in cs["states"]) > 8000 and len(cs["states"]) >= 15, "the committed file is the real registry: Texas first, over 8,000 wells in a year, 15 or more states: %d" % sum(x["p12"] for x in cs["states"]))
    check(cp["n"] > 15000 and cp["n"] <= sum(sum(x["new"][cs["months"].index(cp["t0"][:7]):]) for x in cs["states"]), "the committed points are fewer than the wells in the same months and more than 15,000: %d" % cp["n"])
    check(set(x["id"] for x in cs["states"]) <= set(c for c, _ in C.JURISDICTIONS), "every state in it is a jurisdiction the national report knows")
    check(os.path.getsize(os.path.join(W.OUT, "points.json")) < 1_500_000, "the points file stays under 1.5 MB (it is the one the map's first paint waits for)")
    check(cs["months"][0] == "2011-01" and ch and ch["n"] > 150000 and os.path.getsize(os.path.join(W.OUT, "points-history.json")) < 14_000_000, "the committed history holds the registry's earlier wells (over 150,000) and stays under 14 MB; the page loads it only when asked: %d" % (ch or {}).get("n", 0))
od = json.load(open(W.OUTLINES))
check(O.check_doc(od) == [] and set(od["states"]) == set(O.FIPS.values()), "the committed outlines hold the 49 states, closed rings, in range")
check(OUTLINES.contains("TX", -97.74, 30.27) and OUTLINES.contains("ND", -103.5, 47.9) and OUTLINES.contains("AK", -149.0, 70.2) and not OUTLINES.contains("TX", -105.0, 40.0), "Austin is in Texas, the Bakken in North Dakota, Prudhoe Bay in Alaska; Denver is not in Texas")
check(O.check_doc({"v": 1, "states": {}}) != [] and O.check_doc({"v": 2}) != [], "an outline file with no states, or the wrong version, is refused")
check(sum(len(r) for s_ in od["states"].values() for r in s_["rings"]) // 2 < 14000 and os.path.getsize(os.path.join(os.path.dirname(W.OUTLINES), "us-states.json")) < 200_000, "the outlines stay small (under 200 KB)")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
