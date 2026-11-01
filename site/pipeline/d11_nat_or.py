#!/usr/bin/env python3
"""D11: Oregon's oil and gas permit applications (DOGAMI, Mineral Land Regulation and Reclamation), for the National report of the Oil tracker.

Oregon has almost no oil and gas drilling: its permits are a few a year, nearly all in the Mist gas field (Columbia County), for gas wells, gas-storage and observation wells.
DOGAMI publishes one spreadsheet, "Oil & Gas Permits Spreadsheet" (a legacy .xls, linked from the page below, updated by hand a few times a year; the file name carries its date),
with one row per application: the permit number, the permittee, the county, the kind of well (WellType, filled for the recent rows), the status and the ApplicationDate.
It has NO approval or issue date, so this counts applications by the day they were filed, and says so. What each row is:

  - a permit number seen for the first time with a producer or exploration well       -> `new`;
  - an injection, withdrawal, storage, observation or monitoring well                  -> `inj`;
  - a permit number with a "-01", "-02" suffix, or an RD / deepening name              -> `redrill`;
  - a permit number filed again on a LATER date (a renewal or re-application: a permit
    lasts a year and is renewed; the file repeats the number with each new date)       -> `amend`;
  - a row with no well type (or one that says nothing about drilling)                  -> `other`.
A row repeated with the same number and the same date counts once. A row with no ApplicationDate cannot be placed in a month and is not counted: the note says how many
applications still waiting have no date. The number, name and site of a well are read here to decide the band and are never kept.

The file is a Microsoft Excel 97-2003 workbook (OLE2 compound file, BIFF8): the standard library has no reader for it, so a small one is here (`xls_sheets`, below). It reads strings,
numbers and dates, enough for this sheet, and refuses anything it does not understand instead of guessing. The spreadsheet is untrusted data: parsed, never opened by anything else.

  python3 -I site/pipeline/d11_nat_or.py [--check]
"""
import collections
import datetime
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "OR"
HOST = "https://www.oregon.gov"
PAGE = HOST + "/dogami/mlrr/Pages/oilgas-report.aspx"
LINK = re.compile(r'href="([^"]*?/spreadsheets/OG_Permits[^"]*?\.xls)"', re.I)
NEED = ("PermitID", "Permittee", "WellType", "Status", "County", "ApplicationDate")
MIN_ROWS = 500  # the file has 741 rows; it only grows
MIN_DATED = 400  # rows with an ApplicationDate (625 now)
MAX_BAD_DATES = 0.05  # at most 5% of the dates written in the file may be unreadable
MAX_AGE_DAYS = 3 * 366  # the newest application may be old (a state with a few a year), but not older than this: a read that finds nothing recent is a broken read
MAX_XLS = 5_000_000
MAX_STREAM = 40_000_000


# ------------------------------------------------------------------------------------------------ a small reader for .xls (BIFF8 in an OLE2 compound file)

ENDOFCHAIN, FREESECT = 0xFFFFFFFE, 0xFFFFFFFF
DATE_IDS = frozenset(list(range(14, 23)) + list(range(27, 37)) + [45, 46, 47] + list(range(50, 59)))


def ole_stream(data, want=("Workbook", "Book")):
    """The bytes of the workbook stream of an OLE2 compound file (version 3 or 4). Only an ordinary (not mini) stream is read: a real sheet is always larger than 4 KB."""
    if len(data) < 1024 or data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("not an Excel 97-2003 (.xls) file")
    shift = struct.unpack_from("<H", data, 30)[0]
    if shift not in (9, 12):
        raise ValueError("unsupported sector size")
    size = 1 << shift
    nfat, first_dir, cutoff, first_difat, ndifat = struct.unpack_from("<I", data, 44)[0], struct.unpack_from("<I", data, 48)[0], struct.unpack_from("<I", data, 56)[0], struct.unpack_from("<I", data, 68)[0], struct.unpack_from("<I", data, 72)[0]
    nsect = (len(data) - size) // size + 1

    def sector(n):
        if n >= nsect:
            raise ValueError("a sector number is outside the file")
        return data[(n + 1) * size:(n + 2) * size]

    fat_ids = [x for x in struct.unpack_from("<109I", data, 76) if x != FREESECT]
    nxt, seen = first_difat, 0
    while nxt not in (ENDOFCHAIN, FREESECT) and seen < ndifat + 1:
        ids = struct.unpack("<%dI" % (size // 4), sector(nxt))
        fat_ids += [x for x in ids[:-1] if x != FREESECT]
        nxt, seen = ids[-1], seen + 1
    fat_ids = fat_ids[:nfat]
    fat = []
    for s in fat_ids:
        fat += struct.unpack("<%dI" % (size // 4), sector(s))

    def chain(start, limit=MAX_STREAM):
        out, n, hops = [], start, 0
        while n not in (ENDOFCHAIN, FREESECT):
            hops += 1
            if hops > len(fat) or n >= len(fat) or hops * size > limit:
                raise ValueError("a sector chain is broken or too long")
            out.append(sector(n))
            n = fat[n]
        return b"".join(out)

    directory = chain(first_dir, 4_000_000)
    for i in range(0, len(directory) - 127, 128):
        ent = directory[i:i + 128]
        nlen = struct.unpack_from("<H", ent, 64)[0]
        name = ent[:max(0, nlen - 2)].decode("utf-16-le", "replace")
        kind, start = ent[66], struct.unpack_from("<I", ent, 116)[0]
        length = struct.unpack_from("<Q", ent, 120)[0] if size == 4096 else struct.unpack_from("<I", ent, 120)[0]
        if kind == 2 and name in want:
            if length < cutoff:
                raise ValueError("the workbook stream is too small to be a permit sheet")
            if length > MAX_STREAM:
                raise ValueError("the workbook stream is too large")
            return chain(start)[:length]
    raise ValueError("no workbook stream in the file")


class _Strings:
    """The shared string table (SST) of a workbook. A record longer than 8224 bytes goes on in CONTINUE records, and a string cut by that boundary starts its next part with a new
    'wide or narrow' flag byte: that is the one subtle rule of the format."""

    def __init__(self, chunks):
        self.chunks, self.ci, self.pos = chunks, 0, 8

    def _left(self):
        return len(self.chunks[self.ci]) - self.pos

    def _skip(self, n):
        while n > 0:
            if self._left() <= 0:
                self.ci, self.pos = self.ci + 1, 0
                if self.ci >= len(self.chunks):
                    raise ValueError("the string table ends early")
                continue
            k = min(n, self._left())
            self.pos, n = self.pos + k, n - k

    def read_all(self):
        uniq = struct.unpack_from("<I", self.chunks[0], 4)[0]
        out = []
        while len(out) < uniq:
            if self._left() <= 0:
                self.ci, self.pos = self.ci + 1, 0
                if self.ci >= len(self.chunks):
                    raise ValueError("the string table ends early")
            c = self.chunks[self.ci]
            cch, flags = struct.unpack_from("<HB", c, self.pos)
            self.pos += 3
            runs = ext = 0
            if flags & 8:
                runs = struct.unpack_from("<H", c, self.pos)[0]
                self.pos += 2
            if flags & 4:
                ext = struct.unpack_from("<I", c, self.pos)[0]
                self.pos += 4
            wide, need, parts = flags & 1, cch, []
            while need > 0:
                if self._left() <= 0:
                    self.ci += 1
                    if self.ci >= len(self.chunks):
                        raise ValueError("the string table ends early")
                    wide, self.pos = self.chunks[self.ci][0] & 1, 1
                c = self.chunks[self.ci]
                k = min(need, self._left() // (2 if wide else 1))
                if k <= 0:
                    raise ValueError("the string table is malformed")
                nb = k * (2 if wide else 1)
                parts.append(c[self.pos:self.pos + nb].decode("utf-16-le" if wide else "latin-1", "replace"))
                self.pos, need = self.pos + nb, need - k
            self._skip(runs * 4 + ext)
            out.append("".join(parts))
        return out


def _rk(v):
    if v & 2:
        n = float(struct.unpack("<i", struct.pack("<I", v))[0] >> 2)
    else:
        n = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return n / 100.0 if v & 1 else n


def _is_date_format(code):
    stripped = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code.lower())
    return bool(re.search(r"[dmyhs]", stripped)) and "general" not in stripped


def _short_string(b, off, v8):
    """A sheet name: BIFF8 has a length byte, a flag byte and the characters (one or two bytes each); BIFF5 a length byte and the characters in the code page."""
    n = b[off]
    if not v8:
        return b[off + 1:off + 1 + n].decode("cp1252", "replace")
    w = 2 if b[off + 1] & 1 else 1
    return b[off + 2:off + 2 + n * w].decode("utf-16-le" if w == 2 else "latin-1", "replace")


def _records(stream, pos=0):
    """(id, data, chunks): each record at `pos` on, with the data of its CONTINUE records joined only where a reader asks (chunks). Stops at the end of the substream that starts at `pos`."""
    depth, n = 0, len(stream)
    while pos + 4 <= n:
        rid, ln = struct.unpack_from("<HH", stream, pos)
        data = stream[pos + 4:pos + 4 + ln]
        pos += 4 + ln
        chunks = [data]
        while pos + 4 <= n and struct.unpack_from("<H", stream, pos)[0] == 0x003C:
            ln2 = struct.unpack_from("<H", stream, pos + 2)[0]
            chunks.append(stream[pos + 4:pos + 4 + ln2])
            pos += 4 + ln2
        yield rid, data, chunks
        if rid == 0x0809:
            depth += 1
        elif rid == 0x000A:
            depth -= 1
            if depth <= 0:
                return


def xls_sheets(data, max_cells=3_000_000):
    """[(sheet name, rows)] for the worksheets of an .xls file (BIFF5 or BIFF8): rows are lists of cell values (text, float, or datetime.date for a cell formatted as a date; None for an empty cell).
    Raises ValueError for a file it cannot read."""
    stream = ole_stream(data)
    if len(stream) < 8 or struct.unpack_from("<H", stream, 0)[0] != 0x0809 or struct.unpack_from("<H", stream, 4)[0] not in (0x0500, 0x0600):
        raise ValueError("not an Excel 5 to 2003 workbook (BIFF5 or BIFF8)")
    v8 = struct.unpack_from("<H", stream, 4)[0] == 0x0600  # DOGAMI's file is the older BIFF5 (8-bit text, no shared string table); BIFF8 is read too
    sheets, strings, xf_fmt, formats, base = [], [], [], {}, datetime.date(1899, 12, 30)
    for rid, d, chunks in _records(stream):
        if rid == 0x0085:  # BOUNDSHEET
            off = struct.unpack_from("<I", d, 0)[0]
            sheets.append((_short_string(d, 6, v8), off, d[5]))
        elif rid == 0x00FC:  # SST
            strings = _Strings(chunks).read_all()
        elif rid == 0x00E0 and len(d) >= 4:  # XF: the number format index
            xf_fmt.append(struct.unpack_from("<H", d, 2)[0])
        elif rid == 0x041E and len(d) >= 4:  # FORMAT: index, then the code (BIFF8: two-byte length and flags; BIFF5: one-byte length)
            idx = struct.unpack_from("<H", d, 0)[0]
            if v8:
                cch, flags = struct.unpack_from("<HB", d, 2)
                formats[idx] = d[5:5 + cch * (2 if flags & 1 else 1)].decode("utf-16-le" if flags & 1 else "latin-1", "replace")
            else:
                formats[idx] = d[3:3 + d[2]].decode("cp1252", "replace")
        elif rid == 0x0022 and len(d) >= 2 and struct.unpack_from("<H", d, 0)[0] == 1:  # DATEMODE: the 1904 system
            base = datetime.date(1904, 1, 1)
    is_date = [(f in DATE_IDS) if f < 164 else _is_date_format(formats.get(f, "")) for f in xf_fmt]

    def value(xf, num):
        if xf < len(is_date) and is_date[xf] and 0 < num < 2958466:
            return base + datetime.timedelta(days=int(num))
        return num

    out, cells = [], 0
    for name, off, kind in sheets:
        if kind != 0 or off >= len(stream) - 4:  # worksheets only (not charts, macros or hidden-very sheets of other kinds)
            continue
        grid = {}
        for rid, d, chunks in _records(stream, off):
            if rid in (0x00FD, 0x0203, 0x027E, 0x0204, 0x00BD) and len(d) >= 6:
                r, c, xf = struct.unpack_from("<HHH", d, 0)
                cells += 1
                if cells > max_cells:
                    raise ValueError("the sheet holds too many cells")
                if rid == 0x00FD:  # LABELSST
                    i = struct.unpack_from("<I", d, 6)[0]
                    grid[(r, c)] = strings[i] if i < len(strings) else None
                elif rid == 0x0203:  # NUMBER
                    grid[(r, c)] = value(xf, struct.unpack_from("<d", d, 6)[0])
                elif rid == 0x027E:  # RK
                    grid[(r, c)] = value(xf, _rk(struct.unpack_from("<I", d, 6)[0]))
                elif rid == 0x0204:  # LABEL: the text of a cell (every text cell in BIFF5; older writers in BIFF8)
                    if v8:
                        cch, flags = struct.unpack_from("<HB", d, 6)
                        grid[(r, c)] = d[9:9 + cch * (2 if flags & 1 else 1)].decode("utf-16-le" if flags & 1 else "latin-1", "replace")
                    else:
                        cch = struct.unpack_from("<H", d, 6)[0]
                        grid[(r, c)] = d[8:8 + cch].decode("cp1252", "replace")
                else:  # MULRK: first column, then (xf, rk) pairs, then the last column
                    k = (len(d) - 6) // 6
                    for j in range(k):
                        xfj, rkj = struct.unpack_from("<HI", d, 4 + 6 * j)
                        grid[(r, c + j)] = value(xfj, _rk(rkj))
        if not grid:
            out.append((name, []))
            continue
        nrow, ncol = max(r for r, _ in grid) + 1, max(c for _, c in grid) + 1
        out.append((name, [[grid.get((r, c)) for c in range(ncol)] for r in range(nrow)]))
    if not out:
        raise ValueError("the workbook has no worksheet")
    return out


# ------------------------------------------------------------------------------------------------ the permit sheet

def find_link(html):
    """The absolute address of the newest permit spreadsheet linked on the report page (the file name carries its date: OG_Permits_20260126.xls, OG_Permits_01-29-2021.xls)."""
    best = None
    for h in LINK.findall(html):
        url = h if h.startswith("http") else HOST + (h if h.startswith("/") else "/" + h)
        if not url.startswith(HOST + "/"):
            continue
        day = file_day(url)
        key = (day or datetime.date.min, url)
        if best is None or key > best[0]:
            best = (key, url)
    return best[1] if best else None


def file_day(url):
    """The date in the spreadsheet's file name (20260126 or 01-29-2021), or None."""
    name = url.rsplit("/", 1)[-1]
    m = re.search(r"(\d{4})(\d{2})(\d{2})", name) or None
    try:
        if m:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", name)
        return datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def permit_rows(sheets):
    """The dict rows of the first worksheet whose header holds every column in NEED; ValueError when none does (the layout changed)."""
    for name, rows in sheets:
        for hi, head in enumerate(rows[:10]):
            names = {str(h).strip().lower(): i for i, h in enumerate(head) if h is not None}
            if all(k.lower() in names for k in NEED):
                idx = {k: names[k.lower()] for k in NEED}
                for extra in ("WellName", "SiteName"):
                    if extra.lower() in names:
                        idx[extra] = names[extra.lower()]
                out = []
                for row in rows[hi + 1:]:
                    rec = {k: (row[i] if i < len(row) else None) for k, i in idx.items()}
                    if any(v not in (None, "") for v in rec.values()):
                        out.append(rec)
                return out
    raise ValueError("no sheet has the columns %s: the layout of the spreadsheet may have changed" % ", ".join(NEED))


def text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return " ".join(str(v).split())


def day_of(v, today):
    if isinstance(v, datetime.date):
        return C.parse_day(v.isoformat(), today)
    return C.parse_day(text(v), today)


def well_band(well_type):
    """new, inj or other from DOGAMI's own well-type words (Producer, Exploration, Gas Injection/Withdrawal, Observation, Monitoring, Water Disposal, Dry Hole...)."""
    t = text(well_type).lower()
    if not t:
        return "other"
    if C.band_of("", t) == "inj" or re.search(r"withdraw", t):
        return "inj"
    if re.search(r"producer|explor|dry hole|plugged|not drilled|wildcat|development", t):
        return "new"
    return "other"


REDRILL_NAME = re.compile(r"\bRD\b|\bRD\s*\d|deepen|re-?entry|side-?track", re.I)


def classify(rows, today):
    """[(day, band, county, operator)] for every dated application, oldest first, and the number of waiting applications with no date. A permit number is `new` (or inj, other) on its
    first date and `amend` on every later date; a number with a -NN suffix or an RD / deepening name is `redrill`; the same number and date twice counts once."""
    seen_dates = collections.defaultdict(set)
    dated, undated = [], 0
    for r in rows:
        pid, day = text(r.get("PermitID")), day_of(r.get("ApplicationDate"), today)
        if day is None:
            if text(r.get("Status")).lower() == "application" and not text(r.get("ApplicationDate")):
                undated += 1
            continue
        if day in seen_dates[pid]:
            continue
        seen_dates[pid].add(day)
        dated.append((day, pid, r))
    dated.sort(key=lambda x: (x[0], x[1]))
    first, out = {}, []
    for day, pid, r in dated:
        if pid in first and first[pid] != day:
            band = "amend"
        else:
            first[pid] = day
            names = " ".join((text(r.get("WellName")), text(r.get("SiteName"))))
            if re.search(r"-\d\d$", pid) or REDRILL_NAME.search(names):
                band = "redrill"
            else:
                band = well_band(r.get("WellType"))
        out.append((day, band, text(r.get("County")), text(r.get("Permittee"))))
    return out, undated


def build(get=C.polite_get, today=None, to_sheets=xls_sheets):
    today = today or datetime.date.today()
    html = get(PAGE, max_bytes=3_000_000).decode("utf-8", "replace")
    url = find_link(html)
    if not url:
        raise RuntimeError("the oil and gas report page links no permit spreadsheet: its layout may have changed")
    try:
        rows = permit_rows(to_sheets(get(url, max_bytes=MAX_XLS)))
    except ValueError as e:
        raise RuntimeError("the permit spreadsheet could not be read: %s" % e)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the permit spreadsheet has %d rows (expected %d or more): it may be cut short" % (len(rows), MIN_ROWS))
    written = [r for r in rows if text(r.get("ApplicationDate"))]
    permits, undated = classify(rows, today)
    if len(written) < MIN_DATED or len(permits) < MIN_DATED * 0.9:
        raise RuntimeError("only %d rows have an application date (expected %d or more)" % (len(written), MIN_DATED))
    bad = len(written) - len([r for r in written if day_of(r.get("ApplicationDate"), today)])
    if bad > MAX_BAD_DATES * len(written):
        raise RuntimeError("%d of %d application dates could not be read: the date format may have changed" % (bad, len(written)))
    newest = max(p[0] for p in permits)
    if (today - newest).days > MAX_AGE_DAYS:
        raise RuntimeError("the newest application is dated %s: the file is not what it was" % newest)
    asof = file_day(url) or newest  # the file's own date: a quiet state's newest application can be months older than the file
    if asof < newest or asof > today:
        asof = newest
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "amend", "other"), fluid=False)
    for day, band, county, operator in permits:
        t.add(day, band, county=county or None, operator=operator or None)
    wait = ""
    if undated:
        wait = " %d application%s still waiting (status Application) %s no date in the file and %s not counted." % (undated, "" if undated == 1 else "s", "has" if undated == 1 else "have", "is" if undated == 1 else "are")
    doc = t.document(agency="Oregon Department of Geology and Mineral Industries (DOGAMI)", source_name="Oil & Gas Permits Spreadsheet (DOGAMI, .xls, updated by hand)", source_url=PAGE,
                     basis="application date (the file has no approval date)", cadence="irregular (a few times a year)", measure="applications", asof=asof, unit="applications filed",
                     note="Oregon permits only a few oil and gas wells a year, almost all gas, gas-storage and observation wells in the Mist field (Columbia County). Counted by the day an application was filed: "
                          "DOGAMI's file has no approval date, no work type and no fluid. A permit number filed again on a later date is an amendment (a renewal: a permit lasts a year). "
                          "The newest application in the file is dated %s; the file is dated %s and DOGAMI updates it by hand.%s" % (newest.isoformat(), asof.isoformat(), wait))
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # a real zero: the sheet was read in full (the floors above), and Oregon files no new-well application in some years
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
