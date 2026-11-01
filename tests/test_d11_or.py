"""Tests for site/pipeline/d11_nat_or.py: Oregon's oil and gas permit applications (DOGAMI's spreadsheet, a legacy .xls).

There is no real file in the tests: a small writer builds synthetic Excel 97-2003 workbooks (an OLE2 compound file holding BIFF records) in the two flavors the reader accepts, BIFF5 (what
DOGAMI's file really is: 8-bit text cells, no shared string table) and BIFF8 (a shared string table that is split in two by a CONTINUE record in the middle of a string, the format's one
subtle rule). The rows are invented (permit numbers 36-999-..., made-up companies and a made-up person). They pin the reader (strings, numbers, RK and MULRK cells, dates by number format or
as text, a second sheet), the bands from DOGAMI's own words (a number seen again on a later date is an amendment, a -NN suffix or an RD name a re-drill, a blank well type is "other"), the
privacy rule on a person's name, the file's own date as the day the counts are good to, and the failures that must stop the run (no link, a missing column, a short file, unreadable dates,
an old file, bytes that are not a workbook). The reader was also compared cell by cell with the real file (741 rows, 16 columns, no difference) when it was written.

Run: python3 -I tests/test_d11_or.py"""
import datetime
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "site", "pipeline")
sys.path.insert(0, PIPE)
import d11_nat_common as C  # noqa: E402
import d11_nat_or as OR  # noqa: E402

FAILS = []
D = datetime.date


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ a writer for synthetic workbooks

def rec(rid, data=b""):
    return struct.pack("<HH", rid, len(data)) + data


def ole(stream):
    """An OLE2 compound file (version 3, 512-byte sectors) holding one stream named Workbook: sector 0 the FAT, 1 the directory, 2.. the stream."""
    ss = 512
    stream += b"\0" * (-len(stream) % ss)
    stream += b"\0" * max(0, 4096 - len(stream))
    n = len(stream) // ss
    assert n + 2 <= 128
    fat = [0xFFFFFFFD, 0xFFFFFFFE] + [i + 3 for i in range(n - 1)] + [0xFFFFFFFE]
    fat += [0xFFFFFFFF] * (128 - len(fat))
    head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
    head += struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    head += struct.pack("<109I", 0, *([0xFFFFFFFF] * 108))
    assert len(head) == 512

    def entry(name, kind, child, start, size):
        raw = name.encode("utf-16-le")
        return raw.ljust(64, b"\0") + struct.pack("<HBBIII", len(raw) + 2 if raw else 0, kind, 1, 0xFFFFFFFF, 0xFFFFFFFF, child) + b"\0" * 16 + struct.pack("<I", 0) + b"\0" * 16 + struct.pack("<III", start, size, 0)

    d = entry("Root Entry", 5, 1, 0xFFFFFFFE, 0) + entry("Workbook", 2, 0xFFFFFFFF, 2, len(stream)) + entry("", 0, 0xFFFFFFFF, 0, 0) * 2
    return head + struct.pack("<128I", *fat) + d + stream


def xf(ifmt, v8):
    return rec(0x00E0, struct.pack("<HH", 0, ifmt) + b"\0" * (16 if v8 else 8))


def number(r, c, x, xfi=0):
    return rec(0x0203, struct.pack("<HHHd", r, c, xfi, float(x)))


def rk_int(r, c, n):
    return rec(0x027E, struct.pack("<HHHI", r, c, 0, ((n << 2) | 2) & 0xFFFFFFFF))


def workbook(rows, v8, sheets_before=(), serial_dates=True, split=False):
    """rows: lists of str / int / float / datetime.date / None. A date is a number with a date format (xf 1) or, with serial_dates False, text. Returns the .xls bytes."""
    strings = []

    def sidx(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    def sheet_body(rws):
        out = rec(0x0809, struct.pack("<HHHH", 0x0600 if v8 else 0x0500, 0x0010, 0x0DBB, 0x07CC))
        for r, row in enumerate(rws):
            for c, v in enumerate(row):
                if v is None or v == "":
                    continue
                if isinstance(v, D):
                    if serial_dates:
                        out += number(r, c, (v - D(1899, 12, 30)).days, 1 if (r + c) % 2 else 2)  # alternate the builtin and the custom date format
                        continue
                    v = v.strftime("%m/%d/%Y")
                if isinstance(v, str):
                    if v8:
                        out += rec(0x00FD, struct.pack("<HHHI", r, c, 0, sidx(v)))
                    else:
                        raw = v.encode("cp1252")
                        out += rec(0x0204, struct.pack("<HHHH", r, c, 0, len(raw)) + raw)
                elif isinstance(v, int) and r % 2 == 0:
                    out += rk_int(r, c, v)
                else:
                    out += number(r, c, v)
        # a MULRK record: four RK cells after the last row
        # (a whole number, a negative one, a hundredths-scaled whole number, a floating-point RK: 0.25 is the top 30 bits of its double)
        rks = [(7 << 2) | 2, ((-3 << 2) | 2) & 0xFFFFFFFF, (150 << 2) | 3, (struct.unpack("<Q", struct.pack("<d", 0.25))[0] >> 32) & 0xFFFFFFFC]
        out += rec(0x00BD, struct.pack("<HH", len(rws), 40) + b"".join(struct.pack("<HI", 0, v) for v in rks) + struct.pack("<H", 43))
        return out + rec(0x000A)

    bodies = [sheet_body(r) for r in list(sheets_before) + [rows]]
    names = ["Notes"] * len(sheets_before) + ["prmqry_E_OG_Permits_Online"]
    fmt = "mm/dd/yyyy"
    fmt_rec = rec(0x041E, struct.pack("<HHB", 164, len(fmt), 0) + fmt.encode("latin-1")) if v8 else rec(0x041E, struct.pack("<HB", 164, len(fmt)) + fmt.encode("latin-1"))

    def globals_(offsets):
        g = rec(0x0809, struct.pack("<HHHH", 0x0600 if v8 else 0x0500, 0x0005, 0x0DBB, 0x07CC)) + rec(0x0022, struct.pack("<H", 0)) + fmt_rec
        g += xf(0, v8) + xf(14, v8) + xf(164, v8)
        for nm, off in zip(names, offsets):
            g += rec(0x0085, struct.pack("<IBB", off, 0, 0) + (struct.pack("<BB", len(nm), 0) + nm.encode("latin-1") if v8 else struct.pack("<B", len(nm)) + nm.encode("latin-1")))
        if v8:
            body = b"".join((struct.pack("<HB", len(s), 1) + s.encode("utf-16-le")) if any(ord(ch) > 255 for ch in s) else (struct.pack("<HB", len(s), 0) + s.encode("latin-1")) for s in strings)
            head = struct.pack("<II", len(strings), len(strings))
            if split:
                # cut inside the characters of one string (the first long one, or the one holding `split`): the continuation starts with that string's flag byte
                pos, cut = 0, None
                for s in strings:
                    wide = any(ord(ch) > 255 for ch in s)
                    raw = struct.pack("<HB", len(s), 1 if wide else 0) + (s.encode("utf-16-le") if wide else s.encode("latin-1"))
                    if (split in s) if isinstance(split, str) else (len(s) >= 6 and pos >= 20):
                        cut = pos + 3 + (2 if wide else 1) * (len(s) // 2)
                        flag = 1 if wide else 0
                        break
                    pos += len(raw)
                assert cut is not None
                g += rec(0x00FC, head + body[:cut]) + rec(0x003C, bytes([flag]) + body[cut:])
            else:
                g += rec(0x00FC, head + body)
        return g + rec(0x000A)

    # a first pass to learn the globals' length (the offsets do not change it), then the real one
    size = len(globals_([0] * len(bodies)))
    offs, o = [], size
    for b in bodies:
        offs.append(o)
        o += len(b)
    return ole(globals_(offs) + b"".join(bodies))


# ------------------------------------------------------------------------------------------------ invented rows, written as the real sheet has them
HEAD = ["PermitID", "WellName", "SiteName", "Permittee", "PermitType", "WellType", "Status", "County", "ApplicationDate", "Depth", "Township", "Range", "Section", "QrtSection", "Latitude", "Longitude"]


def row(pid, permittee, wtype, status, county, day, well="", site=""):
    return [pid, well, site, permittee, "Oil and Gas Well", wtype, status, county, day, 1200, "6N", "5W", "12", "NE", 45.9, -123.2]


ALDER, WILLOW, CEDAR, DUNE = "Alder Gas Storage LLC", "Willow Ridge Partners LP", "Cedar Energy Company Inc", "Dune Renewables LLC"
PERSON = "Marsh, Lee R"
ROWS = [
    HEAD,
    row("36-999-00001", ALDER, "Producer", "Permitted", "Columbia", D(2019, 3, 12)),
    row("36-999-00001", ALDER, "Producer", "Permitted", "Columbia", D(2019, 3, 12)),  # the same number and day twice: one
    row("36-999-00001", ALDER, "Producer", "Permitted", "Columbia", D(2020, 4, 2)),  # filed again: a renewal
    row("36-999-00002", "Brandt, Pat", "Exploration", "Admin", "Malheur", D(2023, 9, 15)),
    row("36-999-00003", ALDER, "Producer", "Permitted", "Columbia", D(2024, 2, 20), site="TEST 3 RD 1"),  # an RD name: a re-drill
    row("36-999-00004-01", CEDAR, "Producer", "Permitted", "Columbia", D(2024, 5, 5)),  # a -01 suffix: a re-drill
    row("36-999-00005", ALDER, "Observation", "Application", "Columbia", D(2025, 10, 9)),
    row("36-999-00006", ALDER, "Gas Injection/Withdrawl", "Application", "Columbia", D(2025, 10, 9)),
    row("36-999-00007", DUNE, "", "Withdrawn", "Gilliam", D(2023, 4, 26)),  # no well type: other
    row("36-999-00008", WILLOW, "Exploration", "Permitted", "Malheur", D(2025, 6, 11)),
    row("36-999-00009", ALDER, "Producer", "Permitted", "Columbia", D(2025, 8, 1)),
    row("36-999-00012", PERSON, "Producer", "Permitted", "Columbia", D(2025, 7, 7)),  # a person: counted, never named
    row("36-999-00010", ALDER, "", "Application", "Columbia", None),  # waiting, no date: not counted, said in the note
    row("36-999-00011", ALDER, "Producer", "Closed", "Columbia", D(1987, 2, 2)),  # before the series starts
]
URL = "https://www.oregon.gov/dogami/mlrr/spreadsheets/OG_Permits_20260126.xls"
PAGE_HTML = '<html><a href="/dogami/mlrr/spreadsheets/OG_Permits_01-29-2021.xls">old</a><a href="/dogami/mlrr/spreadsheets/OG_Permits_20260126.xls">new</a></html>'
TODAY = D(2026, 11, 1)


class Net:
    def __init__(self, xls, page=PAGE_HTML):
        self.xls, self.page, self.asked = xls, page, []

    def get(self, url, **kw):
        self.asked.append(url)
        return self.page.encode() if url == OR.PAGE else self.xls


# ------------------------------------------------------------------------------------------------ the reader
for v8 in (False, True):
    flavor = "BIFF8" if v8 else "BIFF5"
    data = workbook(ROWS, v8, sheets_before=([["nothing", "here"]],), split=v8)
    sheets = OR.xls_sheets(data)
    check([n for n, _ in sheets] == ["Notes", "prmqry_E_OG_Permits_Online"], "%s: both sheets are found by name" % flavor)
    got = sheets[1][1]
    check(got[0][:16] == HEAD and got[1][0] == "36-999-00001" and got[1][3] == ALDER and got[1][8] == D(2019, 3, 12), "%s: text and a date (a number under a date format) come back as the cells hold them" % flavor)
    check(got[4][8] == D(2023, 9, 15) and got[5][8] == D(2024, 2, 20) and got[7][8] == D(2025, 10, 9), "%s: dates under the builtin and the custom date format both read" % flavor)
    check(got[1][9] == 1200.0 and got[2][9] == 1200.0 and got[1][14] == 45.9 and got[1][15] == -123.2, "%s: whole numbers (RK cells) and decimals read, negative too" % flavor)
    check(got[len(ROWS)][40:44] == [7.0, -3.0, 1.5, 0.25], "%s: a MULRK record gives its cells (an integer, a negative one, a scaled one, a float)" % flavor)
    check(got[14][8] == D(1987, 2, 2) and got[13][8] is None, "%s: an empty cell is None" % flavor)
    text_dates = OR.xls_sheets(workbook(ROWS, v8, serial_dates=False))[0][1]
    check(text_dates[1][8] == "03/12/2019", "%s: a date written as text stays text (the producer reads both)" % flavor)
wide = OR.xls_sheets(workbook([HEAD, row("36-999-00001", "Café 中文 Energy LLC", "Producer", "Permitted", "Columbia", D(2024, 1, 5))], True, split=True))[0][1]
check(wide[1][3] == "Café 中文 Energy LLC", "BIFF8: a string with two-byte characters, cut by a CONTINUE record, is whole again")
for bad in (b"", b"not an excel file" * 100, ole(rec(0x0809, struct.pack("<HHHH", 0x0200, 0x0010, 1, 1)) + rec(0x000A))):
    try:
        OR.xls_sheets(bad)
        ok = False
    except ValueError:
        ok = True
    check(ok, "bytes that are not a BIFF5 or BIFF8 workbook (%d bytes) are refused" % len(bad))
good = workbook(ROWS, False)
try:
    OR.xls_sheets(good[:2500])
    ok = False
except ValueError:
    ok = True
check(ok, "a workbook cut short is refused, not read short")

# ------------------------------------------------------------------------------------------------ the page, the file's day, the sheet
check(OR.find_link(PAGE_HTML) == URL, "the newest spreadsheet on the page is the one read (the file name carries its date)")
check(OR.find_link("<html>nothing</html>") is None and OR.find_link('<a href="https://evil.example/spreadsheets/OG_Permits_20260126.xls">x</a>') is None, "no link, or a link to another site, finds nothing")
check(OR.file_day(URL) == D(2026, 1, 26) and OR.file_day("https://x/OG_Permits_01-29-2021.xls") == D(2021, 1, 29) and OR.file_day("https://x/OG_Permits.xls") is None, "the file's date comes from its name, in either spelling")
try:
    OR.permit_rows([("a", [["PermitID", "Permittee"], ["x", "y"]])])
    ok = False
except ValueError:
    ok = True
check(ok, "a sheet without the expected columns is refused (the layout changed)")

# ------------------------------------------------------------------------------------------------ the bands, from DOGAMI's own words
check([OR.well_band(x) for x in ("Producer", "Exploration", "Dry Hole", "Not drilled", "Former producer - plugged")] == ["new"] * 5, "producer, exploration and the later words of a drilled or planned well are new wells")
check([OR.well_band(x) for x in ("Gas Injection/Withdrawal", "Gas Injection/Withdrawl", "Gas Withdrawal", "Observation", "Pressure Observation", "Monitoring", "Water Disposal")] == ["inj"] * 7, "injection, withdrawal, observation, monitoring and disposal wells are service wells (inj)")
check([OR.well_band(x) for x in ("", None, "Information", "test")] == ["other"] * 4, "a blank well type, or one that says nothing about drilling, is other")
permits, undated = OR.classify(OR.permit_rows([("s", ROWS)]), TODAY)
by = {(p[0], p[1]): p for p in permits}
check(len(permits) == 12 and undated == 1, "the repeated row is dropped and the undated one is counted aside: 12 dated applications (%d), 1 waiting without a date (%d)" % (len(permits), undated))
check((D(2019, 3, 12), "new") in by and (D(2020, 4, 2), "amend") in by, "a permit number is new on its first date and an amendment on a later one")
check((D(2024, 2, 20), "redrill") in by and (D(2024, 5, 5), "redrill") in by, "an RD name and a -01 number suffix are re-drills")
check((D(2025, 10, 9), "inj") in by and (D(2023, 4, 26), "other") in by and (D(2023, 9, 15), "new") in by, "observation and withdrawal wells are inj, a blank type other, an exploration well new")
check(OR.day_of(D(2026, 12, 1), TODAY) is None and OR.day_of("03/12/2019", TODAY) == D(2019, 3, 12) and OR.day_of(45000.0, TODAY) is None and OR.day_of(None, TODAY) is None, "dates: text and date cells parse, a future day, a bare number and nothing do not")

# ------------------------------------------------------------------------------------------------ the producer, end to end with the network faked
OR.MIN_ROWS, OR.MIN_DATED = 8, 8  # the fixture is a handful of rows, the real floors are 500 and 400
net = Net(workbook(ROWS, False))
doc = OR.build(get=net.get, today=TODAY)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(net.asked == [OR.PAGE, URL], "two requests: the report page, then the spreadsheet (%s)" % net.asked)
check(doc["state"] == "OR" and doc["measure"] == "applications" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2025-12" and doc["asOf"] == "2026-01-26" and doc["through"] == "2025-12-31",
      "from 2019-01 to the file's own last complete month: counts are good to the file's date (2026-01-26), not to the newest application")
m = dict(zip(doc["months"], range(len(doc["months"]))))
new, inj, redrill, amend, other = (doc["bands"][b] for b in ("new", "inj", "redrill", "amend", "other"))
check(new[m["2019-03"]] == 1 and new[m["2023-09"]] == 1 and new[m["2025-06"]] == 1 and new[m["2025-07"]] == 1 and new[m["2025-08"]] == 1 and sum(new) == 5, "new wells by the day of application: 5 in all")
check(inj[m["2025-10"]] == 2 and sum(inj) == 2 and amend[m["2020-04"]] == 1 and sum(amend) == 1 and sum(redrill) == 2 and sum(other) == 1 and doc["bands"]["rework"] is None, "service wells, amendments, re-drills and other are counted, and a band the source cannot tell (rework) is null")
check(doc["fluid"] is None and doc["basis"].startswith("application date") and doc["unit"] == "applications filed", "no fluid is claimed, and the basis says these are applications, not approvals")
check([o[0] for o in doc["operators"]] == ["ALDER GAS STORAGE LLC", "WILLOW RIDGE PARTNERS LP"] and doc["counties"][0] == ["Columbia", 2] and doc["counties"][1] == ["Malheur", 1], "the last 12 months' companies and counties are ranked")
check(abs(doc["namedShare"] - 2 / 3) < 0.001, "a person's permit counts in the year but is not named: 2 of 3 are named")
blob = json.dumps(doc)
check("Marsh" not in blob and "MARSH" not in blob and "Brandt" not in blob and "36-999" not in blob and "TEST 3" not in blob, "no person's name, permit number or site name is in the file")
check("1 application still waiting" in doc["note"] and "2025-10-09" in doc["note"] and "2026-01-26" in doc["note"] and "zeroOk" not in doc, "the note says what is not counted and gives the two dates; there is new activity, so no zeroOk")

# a file dated before its newest application falls back to the newest application; a quiet two years are a real zero
quiet = [r for r in ROWS if not (isinstance(r[8], D) and r[8] >= D(2024, 1, 1) and r[5] in ("Producer", "Exploration"))]
quiet = quiet + [row("36-999-00020", ALDER, "Observation", "Application", "Columbia", D(2025, 11, 20))]
dq = OR.build(get=Net(workbook(quiet, True)).get, today=TODAY)
check(sum(dq["bands"]["new"][-24:]) == 0 and dq.get("zeroOk") is True and C.validate(dq, TODAY) == [], "no new application in two years (read in full) is a real zero: zeroOk, and it validates")
early = OR.build(get=Net(workbook(ROWS, False), PAGE_HTML.replace("20260126", "20250101")).get, today=TODAY)
check(early["asOf"] == "2025-10-09" and early["through"] == "2025-09-30", "a file named for a day before its newest application is not believed: the newest application is the day")
nodate = OR.build(get=Net(workbook(ROWS, False), PAGE_HTML.replace("OG_Permits_20260126", "OG_Permits_latest")).get, today=TODAY)
check(nodate["asOf"] == "2025-10-09", "a file name with no date falls back to the newest application")

# ------------------------------------------------------------------------------------------------ failures stop the run


def boom(xls, page=PAGE_HTML, **kw):
    try:
        OR.build(get=Net(xls, page).get, today=kw.get("today", TODAY))
        return False
    except RuntimeError:
        return True


check(boom(workbook(ROWS, False), page="<html>no spreadsheet</html>"), "a page that links no spreadsheet fails the run")
check(boom(b"<html>an error page</html>" * 200), "an error page where the spreadsheet should be fails the run")
check(boom(workbook([[h for h in HEAD if h != "WellType"]] + [[v for v, h in zip(r, HEAD) if h != "WellType"] for r in ROWS[1:]], False)), "a missing column fails the run")
OR.MIN_DATED = 2
check(boom(workbook([HEAD] + [r for r in ROWS[1:] if r[0] in ("36-999-00008", "36-999-00009", "36-999-00012")], False)), "a short file (3 recent rows, the floor in this test is 8) fails the run, by the row floor alone")
OR.MIN_DATED = 8
smudged = ROWS + [row("36-999-%05d" % (30 + i), ALDER, "Producer", "Permitted", "Columbia", "13/45/2020") for i in range(3)]
check(boom(workbook(smudged, False)), "enough good dates but 3 of 15 unreadable (past 5%) fails the run: the date format may have changed")
junk = [HEAD] + [row("36-999-%05d" % i, ALDER, "Producer", "Permitted", "Columbia", "sometime in spring") for i in range(12)]
check(boom(workbook(junk, False)), "dates that cannot be read fail the run")
check(boom(workbook(ROWS, False), today=D(2030, 1, 1)), "a newest application years old fails the run (a read that found nothing recent is a broken read)")
OR.MIN_ROWS, OR.MIN_DATED = 500, 400
check(boom(workbook(ROWS, False)), "with the real floors (500 rows, 400 dated) this small file is refused")
OR.MIN_ROWS, OR.MIN_DATED = 8, 8

with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("OR", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "OR.json")), "run_producer writes nat/OR.json for it")
    check(C.run_producer("OR", lambda: OR.build(get=Net(b"x" * 5000, "<html></html>").get, today=TODAY), tmp, argv=[]) == 1, "a failed read exits 1 and writes nothing new")


def refused(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("OR", lambda: OR.build(get=refused, today=TODAY), tmp, argv=[]) == 2 and not os.listdir(tmp), "a server that refuses this machine is an answer: exit 2, nothing written")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
