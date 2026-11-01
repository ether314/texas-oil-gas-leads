"""Tests for site/pipeline/d11_nat_ky.py: Kentucky's permits (Division of Oil and Gas) from its weekly "Permit List for Week Ending <Friday>" workbooks.

The fixtures are invented workbooks written the way the real ones are: the same 23 columns (with the lease, API number, address and coordinates the producer must never read), DATE ISSUED as an
Excel serial number, blank padding rows, .xlsx from the week ending 2022-08-19 and .xls (the old binary format, written here by a small OLE2 + BIFF8 writer) before it, and the two pages that link them
(addresses with spaces in them, the current year on one page and the archive on the other). They pin: the .xls reader (compound file with a big stream and with a mini stream, shared strings across a
CONTINUE record and in 16 bits, text, NUMBER and RK cells), the issue date in all its forms, how the lists' own words (Drilling, Deepening, Reopening; oil, gas, storage, water...) become bands and fluids,
a permit on two lists counted once, the privacy rule on a person-named operator, that no lease, API number, address or coordinate reaches the output, the committed file carrying the older months so
that a weekly run reads only the window, and that a page whose layout changed, a missing week, a stale listing, a renamed column, a page of HTML for a workbook, a cut-short workbook, a date out of
reach and too few permits fail the run instead of writing a short file. The network is faked.

Run: python3 -I tests/test_d11_ky.py"""
import io
import json
import os
import struct
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_ky as KY  # noqa: E402

FAILS = []
TODAY = date(2026, 10, 31)
HEADER = ["SAMPLES", "PERMIT #", "API #", "LEASE NAME", "WELL #", "DATE ISSUED", "PERMIT FOR", "PURPOSE", "COUNTY", "CARTER COORDINATE LOCATION", "Latitude (NAD 27)", "Longitude (NAD 27)", "FORMATION", "ELEVATION",
          "PROJECTED DEPTH", "SLANT", "MULTILATERAL", "COMPANY NAME", "ADDRESS", "ADDRESS", "CITY", "STATE", "ZIP"]
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
LEASE, API, STREET = "INVENTED LEASE OF A. N. EXAMPLE", "16999099990000", "1 INVENTED STREET"  # strings that must never reach an output


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


def serial(d):
    return (d - date(1899, 12, 30)).days


def line(no, d, work="Drilling", purpose="Oil", county="Adair", company="ACME TEST OPERATING LLC", header=HEADER):
    """One permit as a row of cells in the real column order (text, or a number for the serial and the permit number)."""
    row = {"PERMIT #": no, "API #": API, "LEASE NAME": LEASE, "WELL #": "7", "DATE ISSUED": serial(d) if isinstance(d, date) else d, "PERMIT FOR": work, "PURPOSE": purpose, "COUNTY": county,
           "CARTER COORDINATE LOCATION": "7 M 34 900FNL 146FEL", "Latitude (NAD 27)": "37.5642", "Longitude (NAD 27)": " \t-86.7172", "FORMATION": "Test Ls", "ELEVATION": 448, "PROJECTED DEPTH": 850,
           "SLANT": "Vertical", "MULTILATERAL": "No", "COMPANY NAME": company, "ADDRESS": STREET, "CITY": "EXAMPLETOWN", "STATE": "KY", "ZIP": "40000"}
    return [row.get(h) for h in header]


# ------------------------------------------------------------------------------------------------ writers for the fixtures

def xlsx(rows, header=HEADER):
    """An .xlsx as bytes (shared strings, numbers as numbers, None for an empty cell, blank padding rows kept)."""
    strings = []

    def s(t):
        if t not in strings:
            strings.append(t)
        return strings.index(t)

    out = []
    for r, row in enumerate([header] + rows, 1):
        cells = []
        for c, v in enumerate(row):
            if v is None:
                continue
            ref = "%s%d" % (chr(65 + c), r)
            cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, s(v)) if isinstance(v, str) else '<c r="%s"><v>%s</v></c>' % (ref, v))
        out.append('<row r="%d">%s</row>' % (r, "".join(cells)) if cells else '<row r="%d"/>' % r)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (MAIN, REL))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % REL)
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (MAIN, "".join(out)))
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="%s">%s</sst>' % (MAIN, "".join("<si><t>%s</t></si>" % escape(x) for x in strings)))
    return buf.getvalue()


def rec(rid, data):
    return struct.pack("<HH", rid, len(data)) + data


RICH = {"RICH TEST LLC": (2, 5)}  # a string with formatting runs and phonetic data: (runs, bytes of phonetic data)


def sst_records(strings, split=None):
    """The SST record (and a CONTINUE record when `split` = (index, characters kept in the first record) cuts a string in two: the new record restates the encoding in its first byte)."""
    def enc(t):
        wide = any(ord(ch) > 255 for ch in t)
        runs, ext = RICH.get(t, (0, 0))
        flags = (1 if wide else 0) | (8 if runs else 0) | (4 if ext else 0)
        head = struct.pack("<HB", len(t), flags) + (struct.pack("<H", runs) if runs else b"") + (struct.pack("<I", ext) if ext else b"")
        tail = b"\x01\x02\x03\x04" * runs + b"\x05" * ext
        return head, (t.encode("utf-16-le") if wide else t.encode("latin-1")), tail, wide

    def whole(t):
        h, body, tail, _w = enc(t)
        return h + body + tail

    head = struct.pack("<II", len(strings), len(strings))
    if split is None:
        return rec(0x00FC, head + b"".join(whole(t) for t in strings))
    i, k = split
    first = head + b"".join(whole(t) for t in strings[:i])
    h, body, tail, wide = enc(strings[i])
    w = 2 if wide else 1
    first += h + body[:k * w]
    rest = bytes([1 if wide else 0]) + body[k * w:] + tail + b"".join(whole(t) for t in strings[i + 1:])
    return rec(0x00FC, first) + rec(0x003C, rest)


def xls_stream(rows, header=HEADER, split=None):
    """A BIFF8 workbook stream: text cells as shared strings, the permit number as an RK cell, the issue date and elevation as NUMBER cells, the rest as text."""
    table = [header] + rows
    strings = []
    for row in table:
        for v in row:
            if isinstance(v, str) and v not in strings:
                strings.append(v)
    if split:  # make the string to cut the first one that is long enough
        split = (strings.index(split[0]), split[1])
    bof = lambda kind: rec(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 6))  # noqa: E731
    sst = sst_records(strings, split)
    sheet_name = bytes([6, 0]) + b"Sheet1"
    boundsheet_len = 4 + 6 + len(sheet_name)
    glob_len = len(bof(5)) + boundsheet_len + len(sst) + 4  # + the EOF record
    boundsheet = rec(0x0085, struct.pack("<I", glob_len) + bytes([0, 0]) + sheet_name)
    globals_ = bof(5) + boundsheet + sst + rec(0x000A, b"")
    assert len(globals_) == glob_len
    cells = b""
    for r, row in enumerate(table):
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, str):
                cells += rec(0x00FD, struct.pack("<HHHI", r, c, 15, strings.index(v)))
            elif header[c] == "PERMIT #":
                cells += rec(0x027E, struct.pack("<HHHI", r, c, 15, (int(v) << 2) | 2))
            else:
                cells += rec(0x0203, struct.pack("<HHHd", r, c, 15, float(v)))
    return globals_ + bof(0x10) + cells + rec(0x000A, b"")


def ole(stream, mini=False):
    """An OLE2 compound file holding one stream named Workbook: in regular sectors (padded to 4096 bytes, as Excel does), or, with mini=True, in the mini stream (a stream under 4096 bytes)."""
    END, FREE, FATSEC = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
    def name(t, kind, start, size):  # one 128-byte directory entry
        entry = (t.encode("utf-16-le") + b"\0\0").ljust(64, b"\0") + struct.pack("<HBB", len(t) * 2 + 2, kind, 1) + struct.pack("<iii", -1, -1, -1)
        return entry + b"\0" * 36 + struct.pack("<IQ", start, size)

    if not mini:
        data = stream.ljust(max(4096, -(-len(stream) // 512) * 512), b"\0")
        n = len(data) // 512
        fat = [FATSEC, END] + [i + 3 for i in range(n - 1)] + [END]
        directory = name("Root Entry", 5, END, 0) + name("Workbook", 2, 2, len(data)) + b"\0" * 256
        sectors = [None, directory] + [data[i * 512:(i + 1) * 512] for i in range(n)]
        mini_start, n_mini = END, 0
    else:
        assert len(stream) < 4096
        m = -(-len(stream) // 64)
        data = stream.ljust(m * 64, b"\0")
        container = data.ljust(-(-len(data) // 512) * 512, b"\0")
        nc = len(container) // 512
        minifat = [i + 1 for i in range(m - 1)] + [END]
        minifat_sector = struct.pack("<128I", *(minifat + [FREE] * (128 - len(minifat))))
        fat = [FATSEC, END, END] + [i + 4 for i in range(nc - 1)] + [END]
        directory = name("Root Entry", 5, 3, len(data)) + name("Workbook", 2, 0, len(stream)) + b"\0" * 256
        sectors = [None, directory, minifat_sector] + [container[i * 512:(i + 1) * 512] for i in range(nc)]
        mini_start, n_mini = 2, 1
    sectors[0] = struct.pack("<128I", *(fat + [FREE] * (128 - len(fat))))
    head = KY.OLE_MAGIC + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
    head += struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, mini_start, n_mini, END, 0)  # dirs (0 for v3), FAT sectors, first directory sector, transaction no., mini cutoff, mini FAT, DIFAT
    head += struct.pack("<109I", 0, *([FREE] * 108))
    assert len(head) == 512
    return head + b"".join(sectors)


# ------------------------------------------------------------------------------------------------ the .xls reader
check(KY.rk_value((43900 << 2) | 2) == 43900.0 and KY.rk_value((12345 << 2) | 3) == 123.45 and KY.rk_value(((-5) & 0x3FFFFFFF) << 2 | 2) == -5.0, "RK numbers: an integer, an integer divided by 100, a negative integer")
dbl = struct.unpack("<Q", struct.pack("<d", 2.5))[0] >> 32
check(KY.rk_value(dbl & 0xFFFFFFFC) == 2.5, "an RK number that is the top 30 bits of a double")
check(KY.num_text(43900.0) == "43900" and KY.num_text(2.5) == "2.5" and KY.num_text(113697.0) == "113697", "a whole number reads as the text an .xlsx reader gives")

D1, D2, D3 = date(2020, 3, 10), date(2020, 3, 12), date(2020, 3, 13)
ROWS = [line(112840, D1), line(112841, D2, "Deepening", "Oil", "Warren"), line(112842, D3, "Drilling", "Gas Storage", "Barren", "Beta Pipeline, Inc."), [None] * len(HEADER), [None] * len(HEADER)]
WANTED = {"PERMIT #": "112840", "DATE ISSUED": str(serial(D1)), "PERMIT FOR": "Drilling", "PURPOSE": "Oil", "COUNTY": "Adair", "COMPANY NAME": "ACME TEST OPERATING LLC"}
for label, data in (("a compound file with the stream in regular sectors", ole(xls_stream(ROWS))), ("a stream cut by a CONTINUE record in 8 bits", ole(xls_stream(ROWS, split=("Deepening", 4)))),
                    ("a stream in the mini stream", ole(xls_stream(ROWS[:1], header=HEADER), mini=True))):
    got = KY.read_workbook(data)
    check(got[0] == WANTED and set(got[0]) == set(KY.ALL_COLUMNS), "%s: the first row reads, and only the six wanted columns are returned" % label)
got = KY.read_workbook(ole(xls_stream(ROWS, split=("Deepening", 4))))
check([r["PERMIT FOR"] for r in got[:3]] == ["Drilling", "Deepening", "Drilling"] and got[1]["COUNTY"] == "Warren" and got[2]["COMPANY NAME"] == "Beta Pipeline, Inc.", "a string split across a CONTINUE record reads whole, and the rows after it are in place")
wide_rows = [line(112843, D1, "Drilling", "Oil", "Barren", "CAF\u00c9 \u2013 TEST OIL LLC")]
check(KY.read_workbook(ole(xls_stream(wide_rows)))[0]["COMPANY NAME"] == "CAF\u00c9 \u2013 TEST OIL LLC", "a string in 16 bits reads (an accent and a dash)")
check(KY.read_workbook(ole(xls_stream(wide_rows, split=("CAF\u00c9 \u2013 TEST OIL LLC", 5))))[0]["COMPANY NAME"] == "CAF\u00c9 \u2013 TEST OIL LLC", "a 16-bit string cut by a CONTINUE record reads whole")
rich_rows = [line(112844, D1, "Drilling", "Oil", "Barren", "RICH TEST LLC"), line(112845, D2, "Drilling", "Gas", "Warren", "AFTER RICH CO LLC")]
for label, data in (("whole", ole(xls_stream(rich_rows))), ("cut by a CONTINUE record inside the string that follows", ole(xls_stream(rich_rows, split=("AFTER RICH CO LLC", 5)))), ("cut inside the string with runs", ole(xls_stream(rich_rows, split=("RICH TEST LLC", 4))))):
    got = KY.read_workbook(data)
    check([r["COMPANY NAME"] for r in got[:2]] == ["RICH TEST LLC", "AFTER RICH CO LLC"] and got[1]["PURPOSE"] == "Gas", "a string with formatting runs and phonetic data is skipped correctly (%s)" % label)
H5 = ["PERMIT #", "API #", "DATE ISSUED", "PERMIT FOR", "PURPOSE"]  # a week with only a confidential permit: five columns, no county, no company (the real week ending 2025-09-12)
conf = [line(112846, D3, "Drilling", "Stratigraphic", header=H5)]
for label, data in (("an .xls", ole(xls_stream(conf, header=H5))), ("an .xlsx", xlsx(conf, header=H5))):
    got = [r for r in KY.read_workbook(data) if r["PERMIT #"]]
    check(len(got) == 1 and got[0]["PURPOSE"] == "Stratigraphic" and got[0]["COUNTY"] is None and got[0]["COMPANY NAME"] is None and got[0]["DATE ISSUED"] == str(serial(D3)), "a list of confidential permits (%s, five columns) reads, with no county and no company" % label)
# a damaged shared-string table must end, not loop: found by fuzzing (a 16-bit string with one byte left in its record looped for ever)
import signal  # noqa: E402


def within(seconds, fn):
    def late(*_a):
        raise TimeoutError("did not end")
    signal.signal(signal.SIGALRM, late)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)


half = struct.pack("<II", 1, 1) + struct.pack("<HB", 4, 1) + b"A"
check(raises(lambda: within(5, lambda: KY.sst_strings([half])), IndexError) and raises(lambda: within(5, lambda: KY.sst_strings([half, b"\x01AB"])), IndexError), "a shared string cut mid-character, with no more records to finish it, ends in an error and does not loop")
check(len(KY.read_workbook(ole(xls_stream([])))) == 0, "a list with a header and no permit has no rows (a quiet week is real)")
swapped = [h for h in HEADER]
swapped[5] = "DATE_ISSUED"
check(raises(lambda: KY.read_workbook(ole(xls_stream(ROWS, header=swapped))), ValueError), "an .xls with a renamed column raises")
data = ole(xls_stream(ROWS))
for label, bad in (("cut in half", data[:len(data) // 2]), ("cut to a header", data[:512]), ("the signature gone", b"\0" * 8 + data[8:]), ("a page of HTML", b"<html><body>Access denied</body></html>"),
                   ("a zip that is not a workbook", b"PK\x03\x04" + b"\0" * 200), ("nothing", b"")):
    check(raises(lambda: KY.read_workbook(bad), ValueError), "a damaged workbook (%s) raises ValueError, not a crash of another kind" % label)

# ------------------------------------------------------------------------------------------------ the .xlsx reader, and the two agree
xr = KY.read_workbook(xlsx(ROWS))
check(xr[0] == WANTED and xr[2]["COMPANY NAME"] == "Beta Pipeline, Inc.", "an .xlsx gives the same row, with the same six columns")
check([r for r in KY.read_workbook(xlsx(ROWS)) if r["PERMIT #"]] == [r for r in KY.read_workbook(ole(xls_stream(ROWS))) if r["PERMIT #"]], "the .xlsx and .xls readers agree, row for row, on the same list")
check(raises(lambda: KY.read_workbook(xlsx(ROWS, header=swapped)), ValueError), "an .xlsx with a renamed column raises")
check(raises(lambda: KY.read_workbook(xlsx(ROWS)[:300]), ValueError), "an .xlsx cut short raises ValueError")
check(len(KY.read_workbook(xlsx([]))) == 0, "an .xlsx with a header and no permit has no rows")
bomb = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(xlsx(ROWS))) as src, zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:  # a good workbook with one extra member that unpacks to 12 MB
    for n in src.namelist():
        z.writestr(n, src.read(n))
    z.writestr("xl/media/padding.bin", b"0" * 12_000_000)
check(len(KY.read_workbook(xlsx(ROWS))) == 5 and raises(lambda: KY.read_workbook(bomb.getvalue()), ValueError), "a workbook with a member that unpacks to 12 MB is refused before anything is unpacked")

# ------------------------------------------------------------------------------------------------ the issue day, the band and the fluid
FRI = date(2026, 10, 23)
check(KY.issue_day(serial(date(2026, 10, 22)), FRI) == date(2026, 10, 22) and KY.issue_day("46317", FRI) == date(2026, 10, 22) and KY.issue_day("46317.0", FRI) == date(2026, 10, 22), "a serial number (as a number or as text) is the day")
check(KY.issue_day("03/10/2026", date(2026, 3, 13)) == date(2026, 3, 10) and KY.issue_day("2026-03-10", date(2026, 3, 13)) == date(2026, 3, 10), "text dates read too")
check(KY.issue_day(serial(date(2026, 10, 24)), FRI) == date(2026, 10, 24) and KY.issue_day(serial(date(2026, 10, 31)), FRI) is None, "a day a week after its Friday is out of reach")
check(KY.issue_day(serial(date(2026, 7, 1)), FRI) is None and KY.issue_day("", FRI) is None and KY.issue_day(None, FRI) is None and KY.issue_day("soon", FRI) is None and KY.issue_day("0", FRI) is None, "a day months before its list, blank, junk and zero are not days")
tell = {("Drilling", "Oil"): ("new", "oil"), ("Drilling", "OIL"): ("new", "oil"), ("Drilling", "Gas"): ("new", "gas"), ("Drilling", "Oil and Gas"): ("new", "both"),
        ("Drilling", "Gas Storage"): ("inj", "other"), ("Drilling", "Secondary Recovery Injection"): ("inj", "other"), ("Drilling", "Enhanced Recovery Injection"): ("inj", "other"),
        ("Drilling", "Salt Water Disposal"): ("inj", "other"), ("Drilling", "Water Supply"): ("inj", "other"), ("Drilling", "Observation"): ("inj", "other"), ("Drilling", "Stratigraphic"): ("inj", "other"),
        ("Confidential", "Stratigraphic"): ("inj", "other"), ("Deepening", "Oil"): ("redrill", "oil"), ("Reopening", "Gas"): ("redrill", "gas"), ("Reopen", "Oil"): ("redrill", "oil"),
        ("Conversion to Injection", "Secondary Recovery Injection"): ("rework", "other"), ("Conversion to Injection", "Enhanced Recovery Injection"): ("rework", "other"), ("Drilling", ""): ("new", None),
        ("Amended permit", "Oil"): ("other", "oil"), ("Plugging", "Oil"): ("other", "oil"), ("Confidential", "Oil"): ("other", "oil"),
        # the newer lists' codes
        ("Drilling", "SRI"): ("inj", "other"), ("Drilling", "GS"): ("inj", "other"), ("Drilling", "SWD"): ("inj", "other"), ("Drilling", "O&G"): ("new", "both"), ("Drilling", "GAS"): ("new", "gas"),
        ("Conversion to Injection", "SRI"): ("rework", "other"), ("Drilling", "ERI"): ("inj", "other"), ("Drilling", "STRAT"): ("inj", "other"), ("Drilling", "CBM"): ("new", "gas"),
        # a purpose not known here is not a new well; the unknown word costs a band, not the run
        ("Drilling", "Unknown"): ("other", None), ("Unknown", "Unknown"): ("other", None), ("Drilling", "XYZ"): ("other", None), ("Deepening", "XYZ"): ("redrill", None)}
check(all(KY.band_and_fluid(w, p) == v for (w, p), v in tell.items()), "the lists' own words become bands and fluids: %s" % {k: KY.band_and_fluid(*k) for k, v in tell.items() if KY.band_and_fluid(*k) != v})

# ------------------------------------------------------------------------------------------------ one list's rows
rows, undated = KY.week_rows(xlsx(ROWS), D3)
check(len(rows) == 3 and undated == 0 and rows[0][0] == D1 and rows[1][1] == "Deepening" and rows[2][4] == "Beta Pipeline, Inc." and rows[0][5] == "112840", "blank padding rows are skipped; each permit is its day, kind, purpose, county, company and number")
check(all(len(r) == 6 and LEASE not in repr(r) and API not in repr(r) and STREET not in repr(r) for r in rows), "a row holds nothing but those six: no lease, API number or address")
check(KY.week_rows(xlsx([line("note", D1), line("", D1), line(None, D1), line("x1234", D1), line("PERMIT", "DateIssued")]), D3) == ([], 0), "a row with no numeric permit number is not a permit (padding, a stray note, a repeated header)")
odd, n_odd = KY.week_rows(xlsx([line(112840, D1), line(112841, "soon"), line(112842, date(2019, 1, 2)), line(112843, None)]), D3)
check(n_odd == 3 and [r[0] for r in odd] == [D1, D3, D3, D3], "a permit whose date is unreadable, blank or years before its list is put on the list's Friday, and counted")

# ------------------------------------------------------------------------------------------------ the pages
def page(weeks, folder, ext_of, host="https://eec.ky.gov", extra=""):
    links = "".join('<tr><td><a id="x" href="%s/Natural-Resources/Oil-and-Gas/%s/Permit List for Week Ending %s.%s" title="t">Permit List for Week Ending %s.%s</a></td></tr>' % (host, folder, w.isoformat(), ext_of(w), w.isoformat(), ext_of(w))
                    for w in sorted(weeks, reverse=True))
    return "<html><body><table><caption>Permit Lists</caption>%s</table>%s</body></html>" % (links, extra)


def fridays(first, last):
    d = first
    while d.weekday() != 4:
        d += timedelta(days=1)
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=7)
    return out


SWITCH = date(2022, 8, 19)  # the first .xlsx list
ALL = fridays(date(2018, 12, 28), date(2026, 10, 23))
CURRENT = [w for w in ALL if w >= date(2026, 1, 1)]
ARCHIVE = [w for w in ALL if w < date(2026, 1, 1)]
ext = lambda w: "xlsx" if w >= SWITCH else "xls"  # noqa: E731
PAGE_NOW = page(CURRENT, "Product ReportsNEW", ext)
PAGE_OLD = page(ARCHIVE, "Permit Lists Library", ext)
found = KY.list_weeks(lambda url, **kw: (PAGE_NOW if url == KY.PAGES[0] else PAGE_OLD).encode())
check(min(found) == date(2019, 1, 4) and max(found) == date(2026, 10, 23) and len(found) == len([w for w in ALL if w >= date(2019, 1, 1)]), "every list since 2019 is found (%d), the older ones are left" % len(found))
u = found[date(2026, 10, 23)]
check(" " not in u and "%20" in u and u.endswith("Week%20Ending%202026-10-23.xlsx") and u.startswith("https://eec.ky.gov/"), "an address with spaces is percent-encoded for the request: " + u)
dup = page([date(2026, 10, 23)], "Elsewhere", ext)
both = KY.list_weeks(lambda url, **kw: (PAGE_NOW if url == KY.PAGES[0] else PAGE_OLD + dup).encode())
check("Product%20ReportsNEW" in both[date(2026, 10, 23)], "a week on both pages is read from the current page")
foreign = KY.list_weeks(lambda url, **kw: (PAGE_NOW if url == KY.PAGES[0] else PAGE_OLD + page([date(2027, 1, 1)], "x", ext, host="https://evil.example")).encode())
check(date(2027, 1, 1) not in foreign, "a link to another host is ignored")
check(raises(lambda: KY.list_weeks(lambda url, **kw: b"<html>no lists here</html>")), "pages with no lists fail the run (their layout may have changed)")
check(raises(lambda: KY.list_weeks(lambda url, **kw: (PAGE_NOW if url == KY.PAGES[0] else page(ARCHIVE[-60:], "x", ext)).encode())), "an archive that lost most of its lists fails the run")


# ------------------------------------------------------------------------------------------------ the producer, with the network faked
def week_lines(w, number):
    """What one week's list holds in the fake world: two to four permits issued on the days before that Friday. Returns (lines, next permit number)."""
    out = []
    k = 2 + (w.toordinal() % 3)
    for i in range(k):
        d = w - timedelta(days=i % 5)
        n = (w.toordinal() // 7) % 7
        work, purpose = ("Drilling", "Oil")
        if n == 0 and i == 0:
            purpose = "Gas Storage"
        elif n == 1 and i == 0:
            work = "Deepening"
        elif n == 2 and i == 0:
            purpose = "Gas"
        elif n == 3 and i == 0:
            work, purpose = "Conversion to Injection", "Secondary Recovery Injection"
        company = ["ACME TEST OPERATING LLC", "SAMPLE ENERGY, INC.", "DOE, JANE", "EXAMPLE PARTNERS LP"][(number + i) % 4]
        out.append(line(number, d, work, purpose, ["Adair", "Warren", "Barren", "Ohio"][(number + i) % 4], company))
        number += 1
    return out, number


class Net:
    """The two pages and a list for every Friday (.xlsx from 2022-08-19, .xls before), as the Division serves them. `weeks` is what exists; `change` can replace one list."""

    def __init__(self, weeks=ALL, change=None, newest=None):
        self.fetched, self.lists = [], {}
        number = 100000
        for w in sorted(weeks):
            rows, number = week_lines(w, number)
            self.lists[w] = rows
        self.pages = (page([w for w in weeks if w >= date(2026, 1, 1)], "Product ReportsNEW", ext), page([w for w in weeks if w < date(2026, 1, 1)], "Permit Lists Library", ext))
        self.change = change or {}

    def get(self, url, **kw):
        if url == KY.PAGES[0]:
            return self.pages[0].encode()
        if url == KY.PAGES[1]:
            return self.pages[1].encode()
        self.fetched.append(url)
        w = date.fromisoformat(url.rsplit("Ending%20", 1)[1][:10])
        if w in self.change:
            return self.change[w]
        return xlsx(self.lists[w]) if w >= SWITCH else ole(xls_stream(self.lists[w]))


def expected(net, first, last):
    """{band: {month: count}} of the fake world, counted from its own rows (a permit once)."""
    out = {b: {} for b in KY.BANDS}
    for w, rows in net.lists.items():
        for r in rows:
            d = date(1899, 12, 30) + timedelta(days=r[5])
            if first <= d <= last:
                b, _f = KY.band_and_fluid(r[6], r[7])
                out[b][C.month_of(d)] = out[b].get(C.month_of(d), 0) + 1
    return out


net = Net()
doc = KY.build(get=net.get, pause=0, old={}, today=TODAY, sleep=lambda s: None)
check(C.validate(doc, TODAY) == [], "what it writes validates: %s" % C.validate(doc, TODAY)[:2])
check(doc["state"] == "KY" and doc["measure"] == "permits" and doc["basis"] == "issue date" and doc["months"][0] == "2019-01" and doc["months"][-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == "2026-10-23",
      "2019-01 to the last complete month, as of the newest list's Friday")
want = expected(net, date(2019, 1, 1), date(2026, 9, 30))
check(all(doc["bands"][b] == [want[b].get(ym, 0) for ym in doc["months"]] for b in KY.BANDS), "every band's monthly counts equal the fake world's own rows (an .xls week and an .xlsx week alike)")
check(sum(doc["bands"]["inj"]) > 0 and sum(doc["bands"]["redrill"]) > 0 and sum(doc["bands"]["rework"]) > 0 and sum(doc["bands"]["new"]) > sum(doc["bands"]["inj"]), "storage wells are injection, deepenings are re-entries and conversions are reworks, apart from new wells")
check(doc["bands"]["amend"] is None and doc["fluid"] is not None and "Conversion" not in json.dumps(doc), "amendments are not available (null, not zero); the fluid is told")
check(sum(doc["fluid"].values()) == sum(doc["bands"]["new"][-12:]) and doc["fluid"]["oil"] > 0 and doc["fluid"]["gas"] > 0 and doc["fluid"]["other"] == 0, "the fluid split covers exactly the last 12 months of new wells (storage is not new)")
check(len(net.fetched) == len([w for w in ALL if w >= date(2019, 1, 1)]), "with nothing committed every weekly list since 2019 is fetched once (%d)" % len(net.fetched))
check({o for o, _n in doc["operators"]} == {"ACME TEST OPERATING LLC", "SAMPLE ENERGY INC.", "EXAMPLE PARTNERS LP"} and not any("DOE" in o for o, _n in doc["operators"]), "a person's name is never an operator, the companies are")
check(0 < doc["namedShare"] < 1 and {c for c, _n in doc["counties"]} == {"Adair", "Warren", "Barren", "Ohio"}, "the share of permits whose operator may be named is below 1; the counties are place names")
text = json.dumps(doc)
check(LEASE not in text and API not in text and STREET not in text and "EXAMPLETOWN" not in text and "evil" not in text, "no lease, API number, address or city from the lists reaches the file")

# a confidential permit names no county and no operator that could be shown
secret = Net()
wk = date(2026, 5, 15)
secret.lists[wk] = secret.lists[wk] + [line(777777, wk, "Drilling", "Oil", "Confidential", "Confidential")]
d_secret = KY.build(get=secret.get, pause=0, old={}, today=TODAY, sleep=lambda s: None)
check(sum(d_secret["bands"]["new"]) == sum(doc["bands"]["new"]) + 1 and "Confidential" not in json.dumps(d_secret) and d_secret["namedShare"] < doc["namedShare"], "a confidential permit is counted, but 'Confidential' is neither a county nor an operator in the file")

# a permit on two lists is counted once
twice = Net()
w0 = date(2026, 5, 15)
twice.lists[w0 + timedelta(days=7)] = twice.lists[w0 + timedelta(days=7)] + [twice.lists[w0][0]]
doc_dup = KY.build(get=twice.get, pause=0, old={}, today=TODAY, sleep=lambda s: None)
check(doc_dup["bands"] == doc["bands"], "a permit that two lists carry is counted once")

# with the committed file, only the window is read; the older months are the committed ones
net2 = Net()
old = {b: dict(zip(doc["months"], doc["bands"][b])) for b in KY.BANDS}
doc2 = KY.build(get=net2.get, pause=0, old=old, today=TODAY, sleep=lambda s: None)
cut = C.add_months(C.month_of(TODAY), -KY.REREAD)
check(len(net2.fetched) <= 4.5 * KY.REREAD + 3 and len(net2.fetched) >= 4 * KY.REREAD and doc2["bands"] == doc["bands"] and doc2["operators"] == doc["operators"] and doc2["counties"] == doc["counties"] and doc2["fluid"] == doc["fluid"],
      "with the committed months only the last %d months' lists are fetched (%d of %d) and the file is the same" % (KY.REREAD, len(net2.fetched), len(net.fetched)))
check(all(date.fromisoformat(u.rsplit("Ending%20", 1)[1][:10]) >= date(int(cut[:4]), int(cut[5:]), 1) for u in net2.fetched), "and none is older than the window")
old_short = {b: {m: n for m, n in v.items() if m > "2020-01"} for b, v in old.items()}
net2b = Net()
KY.build(get=net2b.get, pause=0, old=old_short, today=TODAY, sleep=lambda s: None)
check(len(net2b.fetched) == len(net.fetched), "a committed file that does not run from 2019-01 is not trusted: everything is read")

# failures fail the run; they never write a short file
def build_with(net_, **kw):
    kw.setdefault("old", {})
    return lambda: KY.build(get=net_.get, pause=0, today=kw.pop("today", TODAY), sleep=lambda s: None, **kw)


mid = date(2024, 5, 17)
check(raises(build_with(Net(change={mid: b"<html>Access denied</html>"}))), "a page of HTML in place of a list fails the run")
check(raises(build_with(Net(change={mid: ole(xls_stream([line(1, mid)], header=swapped)) if mid < SWITCH else xlsx([line(1, mid)], header=swapped)}))), "a list with a renamed column fails the run")
one_bad = Net(change={mid: xlsx(Net().lists[mid] + [line(999990, "soon")]) if mid >= SWITCH else ole(xls_stream(Net().lists[mid] + [line(999990, "soon")]))})
d_bad = KY.build(get=one_bad.get, pause=0, old={}, today=TODAY, sleep=lambda s: None)
check("1 permit with no readable issue date is counted in the week of its list" in d_bad["note"] and sum(d_bad["bands"]["new"]) == sum(doc["bands"]["new"]) + 1, "one permit with an unreadable date is counted in its list's week, and the note says so")
many = Net(change={mid: xlsx(Net().lists[mid] + [line(999900 + i, "soon") for i in range(40)])})
check(raises(build_with(many)), "40 permits of 1,260 with unreadable dates fail the run (the column may have changed)")
only_conf = Net(change={mid: (xlsx([line(888880, mid, "Drilling", "Stratigraphic", header=H5)], header=H5) if mid >= SWITCH else ole(xls_stream([line(888880, mid, "Drilling", "Stratigraphic", header=H5)], header=H5)))})
d_conf = KY.build(get=only_conf.get, pause=0, old={}, today=TODAY, sleep=lambda s: None)
check(C.validate(d_conf, TODAY) == [], "a week whose list is only a confidential permit does not stop the run (found in the real lists: the week ending 2025-09-12)")
renamed = [h if h != "COUNTY" else "COUNTY NAME" for h in HEADER]
class Renamed(Net):
    def get(self, url, **kw):
        data = super().get(url, **kw)
        if url in (KY.PAGES[0], KY.PAGES[1]):
            return data
        w = date.fromisoformat(url.rsplit("Ending%20", 1)[1][:10])
        rows = [[r[i] for i in range(len(HEADER))] for r in self.lists[w]]
        return xlsx(rows, header=renamed) if w >= SWITCH else ole(xls_stream(rows, header=renamed))
check(raises(build_with(Renamed())), "every list with its COUNTY column renamed fails the run (no county would be shown, and nothing would say so)")
check(raises(build_with(Net(change={date(2020, 8, 14): ole(xls_stream(Net().lists[date(2020, 8, 14)]))[:3000]}))), "a cut-short .xls fails the run")
gap = [w for w in ALL if w not in (date(2025, 3, 7), date(2025, 3, 14))]
check(raises(build_with(Net(weeks=gap))), "two weeks with no list make a hole, and the run fails (months would count short)")
check(raises(build_with(Net(weeks=[w for w in ALL if w != date(2025, 3, 7)]))), "one week with no list is a hole too: its permits would be missing (the lists have never skipped a Friday since 2017)")
shifted = [w if w != date(2019, 3, 29) else date(2019, 3, 28) for w in ALL]
check(KY.build(get=Net(weeks=shifted).get, pause=0, old={}, today=TODAY, sleep=lambda s: None)["state"] == "KY", "a list a day early (the week ending Thursday 2019-03-28) is not a hole")
check(raises(build_with(Net(weeks=[w for w in ALL if w <= date(2026, 8, 28)]))), "a listing that stopped two months ago fails the run (stale)")
check(raises(build_with(Net(weeks=[w for w in ALL if w >= date(2019, 6, 1) and w < date(2019, 8, 1) or w >= date(2023, 1, 1)]))), "a listing with only part of the years fails the run")
quiet = Net()
for w in fridays(date(2026, 8, 1), date(2026, 10, 23)):
    quiet.lists[w] = []
check(raises(build_with(quiet)), "twelve lists in a row with no permit fail the run (the export may be broken)")
empty = Net()
for w in empty.lists:
    empty.lists[w] = empty.lists[w][:1] if w.toordinal() % 9 == 0 else []
check(raises(build_with(empty)), "far too few permits fail the run")
check(raises(build_with(Net(), today=date(2026, 12, 31))), "a listing 69 days old fails the run")


def refuse(url, **kw):
    raise C.Refused("HTTP 403 from the server")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("KY", lambda: KY.build(get=refuse, pause=0, old={}, today=TODAY), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing")
    check(C.run_producer("KY", build_with(Net(weeks=gap)), tmp, argv=[]) == 1 and not os.listdir(tmp), "a failure exits 1 and writes nothing")
    check(C.run_producer("KY", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "KY.json")), "run_producer writes nat/KY.json for it")
    written = json.load(open(os.path.join(tmp, "KY.json"), encoding="utf-8"))
    check(KY.previous(os.path.join(tmp, "KY.json"))["new"] == dict(zip(doc["months"], doc["bands"]["new"])) and C.check_dir(tmp) == [], "the written file reloads as the committed counts and passes --check")
    check(KY.previous(os.path.join(tmp, "missing.json")) == {} and KY.previous(os.path.join(HERE, "test_d11_ky.py")) == {}, "no committed file, or one that is not JSON, gives nothing to carry")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
