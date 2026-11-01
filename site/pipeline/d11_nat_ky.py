#!/usr/bin/env python3
"""D11: Kentucky's drilling permits (Division of Oil and Gas, Department for Natural Resources), for the National report of the Oil tracker.

The Division publishes a workbook every week, "Permit List for Week Ending <Friday>", one row per permit issued (https://eec.ky.gov/Natural-Resources/Oil-and-Gas/Resources/Pages/Permit-Lists.aspx
for the current year, .../Archived-Permit-Lists.aspx for the years before). No login, a few KB each, back to 2017: .xlsx from the week ending 2022-08-19, .xls (the old binary format) before it.
There is no bulk file, so this reads one workbook per week. The columns it reads: DATE ISSUED, PERMIT FOR (Drilling, Deepening, Reopening, Conversion to Injection), PURPOSE (the well type: oil, gas, storage...), COUNTY
and COMPANY NAME, plus PERMIT # to count a permit once if two lists carry it. Nothing else in a row is read (the lists also hold lease names, API numbers, addresses and coordinates).
A list of confidential permits has only five columns (no COUNTY, no COMPANY NAME): those are read as blank. If most permits lack a county or a company the run fails (a column renamed).

What is counted: a permit by its DATE ISSUED (`measure="permits"`, basis "issue date"), 2019 to the newest complete month. The words seen in 2019 to October 2026 (1,026 permits):
PERMIT FOR is Drilling (93%), Reopening, Deepening, Conversion to Injection, Confidential or Unknown; PURPOSE is Oil (94%), Oil and Gas, Gas, Secondary or Enhanced Recovery Injection, Salt Water Disposal,
Gas Storage, Water Supply, Observation or Stratigraphic, spelled out in the older lists and as codes (OIL, O&G, GAS, SRI, GS, SWD) in the newer ones.
  new      a Drilling permit for an oil, gas or oil-and-gas well
  inj      a Drilling permit for an injection, disposal, storage, water supply, observation or stratigraphic-test well
  redrill  a Deepening or Reopening permit
  rework   a Conversion to Injection permit (the only kind of rework the lists carry)
  other    any other kind of permit the lists carry, or a drilling permit for a purpose not known here (one of each seen)
Published as not available (null, never zero): amendments, which the lists do not carry, and recompletions, which they do not either (a well is worked over without a permit).
The well type is the one given when the permit was issued, so the fluid split (oil, gas, other) is as of the permit. A permit whose date cannot be read, or is far from its list's Friday, is counted in the
week of its list (the note says how many, when there are any); more than a few of them fail the run.

How complete the lists are: the Kentucky Geological Survey's well file (kgs.uky.edu/ogdata/kyog_dd.zip) records 1,039 permit numbers between the first and the last on the lists; the lists carry 1,026 of
them, and the other 13 (six of them in November 2022) are on no list, so a month can be about 1% low. That is the Division's omission, not a parsing loss (checked once, October 2026).

A month counts as complete when a list that ends after it has been read. The lists are small and regular (a Friday each week); a week with no list, a list that cannot be read, a header that has
changed, too few permits or a listing that stopped being updated fails the run (nothing is written, the committed file stays). Months older than REREAD months are kept from the committed file,
so a weekly run reads about 60 workbooks, not 400; the first run, with no file, reads them all (about 17 minutes at 2 seconds apart).

The .xls reader below is the one new piece: a minimal reader of the old binary Excel format (an OLE2 compound file holding BIFF8 records: shared strings, text, number and RK cells), standard
library only. The workbooks are untrusted data: parsed, never run; sizes are checked before anything is unpacked. Requests identify no person.

  python3 -I site/pipeline/d11_nat_ky.py [--check]
"""
import io
import json
import os
import re
import struct
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402
import ok_xlsx  # noqa: E402  (the repository's standard-library reader for .xlsx)

STATE = "KY"
PAGES = ("https://eec.ky.gov/Natural-Resources/Oil-and-Gas/Resources/Pages/Permit-Lists.aspx", "https://eec.ky.gov/Natural-Resources/Oil-and-Gas/Resources/Pages/Archived-Permit-Lists.aspx")
SOURCE_URL = PAGES[0]
LINK = re.compile(r'href="(https://eec\.ky\.gov/[^"<>]*?Permit List for Week Ending (\d{4})-(\d\d)-(\d\d)\.(xlsx|xls))"', re.I)
WANT = ("PERMIT #", "DATE ISSUED", "PERMIT FOR", "PURPOSE")  # a list must have these columns
OPTIONAL = ("COUNTY", "COMPANY NAME")  # a list of confidential permits has neither (the week ending 2025-09-12 had five columns), so a missing one is blank, not an error
ALL_COLUMNS = WANT + OPTIONAL
PAUSE = 2.0  # seconds between requests to the agency's server
REREAD = 14  # months read again each run; older months come from the committed file
MAX_LIST = 2_000_000  # bytes: a weekly list is 20 to 40 KB
MAX_PAGE = 3_000_000
MIN_LISTS = 300  # lists linked since 2019 (about 410 in October 2026)
MIN_PERMITS_ALL = 400  # a full read, 2019 on (several hundred a year)
MIN_PERMITS_WINDOW = 15  # the REREAD window alone (about 60 a year in 2026)
STALE_DAYS = 45  # the newest list may not be older than this
BANDS = ("new", "inj", "redrill", "rework", "other")  # the bands the lists can tell; amendments are not on them
MAX_UNDATED = 3  # permits a run may count in their list's week for want of a readable date (or 2% of the permits read)


# ------------------------------------------------------------------------------------------------ the .xls reader (OLE2 + BIFF8)

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MARKER = 0xFFFFFFFA  # sector numbers from here up mean end of chain, free, FAT or DIFAT sector: never a sector


def ole_stream(data, names=("Workbook", "Book")):
    """The bytes of the Workbook stream of an OLE2 compound file. Raises ValueError for anything that is not one."""
    if data[:8] != OLE_MAGIC or len(data) < 512:
        raise ValueError("not an OLE2 compound document")
    shift, mshift = struct.unpack_from("<HH", data, 30)
    if shift not in (9, 12) or mshift != 6:
        raise ValueError("an unexpected sector size")
    ssz, msz = 1 << shift, 1 << mshift
    nfat, dir_start, _tx, cutoff, mfat_start, _nm, dif_start, ndif = struct.unpack_from("<IIIIIIII", data, 44)
    difat = list(struct.unpack_from("<109I", data, 76))
    sec = dif_start
    for _ in range(min(ndif, 64)):
        if sec >= MARKER:
            break
        vals = struct.unpack_from("<%dI" % (ssz // 4), data, (sec + 1) * ssz)
        difat += vals[:-1]
        sec = vals[-1]
    fat = []
    for s in [s for s in difat if s < MARKER][:nfat]:
        fat += struct.unpack_from("<%dI" % (ssz // 4), data, (s + 1) * ssz)

    def chain(start, table):
        out, s = [], start
        while s < MARKER and len(out) <= len(table):  # a loop in a damaged file ends at the table's length
            out.append(s)
            s = table[s]
        return out

    def sectors(start):
        return b"".join(data[(s + 1) * ssz:(s + 2) * ssz] for s in chain(start, fat))

    directory = sectors(dir_start)
    entries = []
    for i in range(0, len(directory) - 127, 128):
        e = directory[i:i + 128]
        n = struct.unpack_from("<H", e, 64)[0]
        entries.append((e[:max(n - 2, 0)].decode("utf-16-le", "replace"), e[66], struct.unpack_from("<I", e, 116)[0], struct.unpack_from("<I", e, 120)[0]))
    root = next((e for e in entries if e[1] == 5), None)
    found = next((e for e in entries if e[1] == 2 and e[0] in names), None)
    if not root or not found:
        raise ValueError("no Workbook stream in the file")
    _name, _kind, start, size = found
    if size > len(data):
        raise ValueError("a stream larger than the file")
    if size >= cutoff:
        return sectors(start)[:size]
    mini = sectors(root[2])[:root[3]]  # small streams live in the root's mini stream
    mfat = []
    for s in chain(mfat_start, fat):
        mfat += struct.unpack_from("<%dI" % (ssz // 4), data, (s + 1) * ssz)
    return b"".join(mini[s * msz:(s + 1) * msz] for s in chain(start, mfat))[:size]


def rk_value(v):
    """A BIFF RK number: bit 0 says divide by 100, bit 1 says a 30-bit integer, otherwise the top 30 bits of a double."""
    if v & 2:
        x = float(struct.unpack("<i", struct.pack("<I", v))[0] >> 2)
    else:
        x = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return x / 100 if v & 1 else x


def num_text(x):
    """A number as the text an .xlsx reader would give: 43900 for 43900.0."""
    return str(int(x)) if x == x and abs(x) < 1e15 and x == int(x) else repr(x)


def sst_strings(chunks):
    """The shared strings of a BIFF8 workbook from the SST record and its CONTINUE records (`chunks`). A string may run across a record boundary, and the new record then
    starts with a byte that restates whether the rest is 8 or 16 bits a character."""
    ci, p = 0, 8
    uniq = struct.unpack_from("<II", chunks[0], 0)[1]
    out = []
    for _ in range(uniq):
        while p >= len(chunks[ci]):
            ci, p = ci + 1, 0
        cch, flags = struct.unpack_from("<HB", chunks[ci], p)
        p += 3
        runs = ext = 0
        if flags & 8:
            runs = struct.unpack_from("<H", chunks[ci], p)[0]
            p += 2
        if flags & 4:
            ext = struct.unpack_from("<I", chunks[ci], p)[0]
            p += 4
        wide, left, parts = flags & 1, cch, []
        while left:
            if len(chunks[ci]) - p < (2 if wide else 1):  # this record is used up (or holds half a character): the string goes on in the next one
                ci, p = ci + 1, 0
                wide = chunks[ci][p] & 1
                p += 1
            w = 2 if wide else 1
            k = min((len(chunks[ci]) - p) // w, left)
            raw = chunks[ci][p:p + k * w]
            parts.append(raw.decode("utf-16-le" if wide else "latin-1"))
            p += len(raw)
            left -= k
        skip = 4 * runs + ext  # formatting runs and phonetic data: not needed
        while skip:
            if p >= len(chunks[ci]):
                ci, p = ci + 1, 0
            k = min(skip, len(chunks[ci]) - p)
            p += k
            skip -= k
        out.append("".join(parts))
    return out


def records(stream, pos=0):
    while pos + 4 <= len(stream):
        rid, ln = struct.unpack_from("<HH", stream, pos)
        yield rid, stream[pos + 4:pos + 4 + ln]
        pos += 4 + ln


def biff_cells(stream):
    """{(row, col): text} of the first worksheet of a BIFF8 workbook stream: text cells (shared and inline), numbers, RK numbers and the numeric result of a formula."""
    chunks, sheet_at, shared = None, None, []
    for rid, d in records(stream):
        if rid == 0x00FC:  # SST
            chunks = [d]
        elif rid == 0x003C and chunks is not None:  # CONTINUE of the SST
            chunks.append(d)
        else:
            if chunks is not None:
                shared, chunks = sst_strings(chunks), None
            if rid == 0x0085 and sheet_at is None and len(d) >= 6 and d[5] == 0:  # BOUNDSHEET of the first worksheet (not a chart or macro sheet)
                sheet_at = struct.unpack_from("<I", d, 0)[0]
            elif rid == 0x000A:  # EOF of the workbook globals
                break
    if sheet_at is None or sheet_at >= len(stream):
        raise ValueError("no worksheet in the workbook")
    cells, depth = {}, 0
    for rid, d in records(stream, sheet_at):
        if rid == 0x0809:  # BOF
            depth += 1
        elif rid == 0x000A:  # EOF
            depth -= 1
            if depth <= 0:
                break
        elif depth == 1:
            if rid == 0x00FD:  # LABELSST
                r, c, _xf, i = struct.unpack_from("<HHHI", d, 0)
                cells[(r, c)] = shared[i]
            elif rid == 0x0203:  # NUMBER
                r, c, _xf, x = struct.unpack_from("<HHHd", d, 0)
                cells[(r, c)] = num_text(x)
            elif rid == 0x027E:  # RK
                r, c, _xf, v = struct.unpack_from("<HHHI", d, 0)
                cells[(r, c)] = num_text(rk_value(v))
            elif rid == 0x00BD:  # MULRK: a run of RK cells in one row
                r, c0 = struct.unpack_from("<HH", d, 0)
                for k in range((len(d) - 6) // 6):
                    _xf, v = struct.unpack_from("<HI", d, 4 + 6 * k)
                    cells[(r, c0 + k)] = num_text(rk_value(v))
            elif rid == 0x0204:  # LABEL: text kept in the cell itself
                r, c, _xf, cch, fl = struct.unpack_from("<HHHHB", d, 0)
                cells[(r, c)] = d[9:9 + 2 * cch].decode("utf-16-le", "replace") if fl & 1 else d[9:9 + cch].decode("latin-1")
            elif rid == 0x0006:  # FORMULA: a number result only (a text result has 0xFFFF in its last two bytes)
                r, c, _xf = struct.unpack_from("<HHH", d, 0)
                if d[12:14] != b"\xff\xff":
                    cells[(r, c)] = num_text(struct.unpack_from("<d", d, 6)[0])
    return cells


# ------------------------------------------------------------------------------------------------ one weekly workbook -> its permit rows

def read_xlsx(data):
    """Rows (dicts of the wanted columns, text or None) of an .xlsx weekly list. The members are size-checked before they are unpacked."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 20_000_000 or any(i.file_size > 10_000_000 for i in z.infolist()):
                raise ValueError("the workbook unpacks to more than 20 MB")
        return list(ok_xlsx.rows(io.BytesIO(data), want=WANT, optional=OPTIONAL))
    except (zipfile.BadZipFile, zlib.error, EOFError, UnicodeError, NotImplementedError, RuntimeError, KeyError, IndexError, ET.ParseError) as e:
        raise ValueError("not a readable .xlsx workbook (%s)" % type(e).__name__)


def read_xls(data):
    """Rows (dicts of the wanted columns, text or None) of an .xls weekly list: the header is the first row that holds PERMIT # and DATE ISSUED."""
    try:
        cells = biff_cells(ole_stream(data))
    except (struct.error, IndexError, KeyError, UnicodeError, OverflowError) as e:
        raise ValueError("not a readable .xls workbook (%s)" % type(e).__name__)
    head_row = next((r for r in sorted({r for r, _c in cells}) if r < 20 and {"PERMIT #", "DATE ISSUED"} <= {(cells.get((r, c)) or "").strip().upper() for c in range(40)}), None)
    if head_row is None:
        raise ValueError("no header row with PERMIT # and DATE ISSUED")
    cols = {}
    for c in range(60):
        h = " ".join((cells.get((head_row, c)) or "").upper().split())
        if h in ALL_COLUMNS and h not in cols:
            cols[h] = c
    if set(WANT) - set(cols):
        raise ValueError("columns not in the sheet: %s" % ", ".join(sorted(set(WANT) - set(cols))))
    last = max((r for r, _c in cells), default=head_row)
    return [{h: (cells.get((r, cols[h])) if h in cols else None) for h in ALL_COLUMNS} for r in range(head_row + 1, last + 1)]


def read_workbook(data):
    """The weekly list's rows from its bytes, by what the file is (a zip or an OLE2 file), whatever its name says."""
    if data[:4] == b"PK\x03\x04":
        return read_xlsx(data)
    if data[:8] == OLE_MAGIC:
        return read_xls(data)
    raise ValueError("neither an .xlsx nor an .xls workbook (a page of HTML?)")


PERMIT_NO = re.compile(r"\d{4,7}(?:\.0+)?")


def issue_day(text, week_end):
    """The day a permit was issued: an Excel serial number (the usual cell), or text in a date shape. None when it is blank, junk or not within 45 days before (or 3 after) its list's Friday
    (the permits of a list are dated 0 to 4 days before it)."""
    t = str(text if text is not None else "").strip()
    d = None
    try:
        f = float(t)
        e = ok_xlsx.excel_date(f)
        d = e.date() if e else None
    except ValueError:
        d = C.parse_day(t, today=week_end + timedelta(days=7))
    if d is None or d < week_end - timedelta(days=45) or d > week_end + timedelta(days=3):
        return None
    return d


# the lists' own codes for a well type (the older lists spell them out, the newer ones abbreviate): 2023 on has OIL, O&G, GAS, SRI, GS and SWD
PURPOSE_CODES = {"SRI": "secondary recovery injection", "ERI": "enhanced recovery injection", "GS": "gas storage", "OBS": "observation", "STRAT": "stratigraphic", "CBM": "coalbed methane gas"}
PRODUCING = re.compile(r"\boil\b|\bgas\b|o&g|coal ?bed|\bcbm\b", re.I)


def band_and_fluid(work, purpose):
    """(band, fluid) of one permit from its PERMIT FOR and PURPOSE words. Reopening is a re-entry and a stratigraphic test a kind of observation well (band_of knows neither word); a drilling
    permit whose purpose is neither a producing well nor a service well it knows (a code not seen before) is not counted as a new well but as `other`, as is a band the lists cannot tell."""
    w = re.sub(r"re-?open\w*", "re-entry", work or "", flags=re.I)
    p = (purpose or "").strip()
    p = PURPOSE_CODES.get(p.upper(), p)
    band = C.band_of(w, p + " observation" if re.search(r"stratigraph", p, re.I) else p)
    if band == "new" and p and not PRODUCING.search(p):
        band = "other"
    return (band if band in BANDS else "other"), C.fluid_of(p)


def week_rows(data, week_end):
    """([(day, work, purpose, county, operator, permit number)], undated) of one weekly list. A row with no numeric PERMIT # is blank padding, a repeated header or a stray note. A permit whose
    DATE ISSUED is blank, unreadable or far from its Friday (`undated` counts them) is put on the list's Friday: it was on that week's list."""
    out, undated = [], 0
    for r in read_workbook(data):
        no = (r.get("PERMIT #") or "").strip()
        if not PERMIT_NO.fullmatch(no):
            continue
        day = issue_day(r.get("DATE ISSUED"), week_end)
        if day is None:
            day, undated = week_end, undated + 1
        out.append((day, r.get("PERMIT FOR") or "", r.get("PURPOSE") or "", r.get("COUNTY") or "", r.get("COMPANY NAME") or "", no.split(".")[0]))
    return out, undated


# ------------------------------------------------------------------------------------------------ the listing and the committed file

def list_weeks(get):
    """{Friday: address} of every weekly list the two pages link, 2019 on. The current page wins over the archive for a week both carry."""
    found = {}
    for url in reversed(PAGES):  # the archive first, so the current page overwrites it
        html = get(url, max_bytes=MAX_PAGE).decode("utf-8", "replace")
        for href, y, m, d, _ext in LINK.findall(html):
            try:
                week = date(int(y), int(m), int(d))
            except ValueError:
                continue
            if week >= date(2019, 1, 1):
                found[week] = urllib.parse.quote(href, safe=":/%")  # the page's addresses hold spaces
    if len(found) < MIN_LISTS:
        raise RuntimeError("the pages link %d weekly lists since 2019 (expected %d or more): their layout may have changed" % (len(found), MIN_LISTS))
    return found


def previous(path=None):
    """{band: {month: count}} from the committed nat/KY.json when it covers 2019-01 on and has the bands this producer writes; {} when there is none or it is not usable."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        if d["months"][0] != C.FIRST_MONTH or d["state"] != STATE:
            return {}
        return {b: dict(zip(d["months"], d["bands"][b])) for b in BANDS}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def build(get=C.polite_get, pause=PAUSE, old=None, today=None, sleep=time.sleep):
    today = today or date.today()
    weeks = list_weeks(get)
    newest = max(weeks)
    if (today - newest).days > STALE_DAYS:
        raise RuntimeError("the newest weekly list is for the week ending %s: the Division may have stopped publishing, or the pages changed" % newest.isoformat())
    old = previous() if old is None else old
    cut_month = C.add_months(C.month_of(today), -REREAD)
    carry = bool(old) and all(ym in old[b] for b in BANDS for ym in C.month_list(C.FIRST_MONTH, C.add_months(cut_month, -1)))  # the committed file has every month from 2019-01 to the one before the window
    start = date(int(cut_month[:4]), int(cut_month[5:]), 1) if carry else date(2019, 1, 1)
    todo = sorted(w for w in weeks if w >= start)
    if not todo or (todo[0] - start).days > 9:
        raise RuntimeError("no weekly list covers %s" % start.isoformat())
    for a, b in zip(todo, todo[1:]):
        if (b - a).days > 9:
            raise RuntimeError("no weekly list between the weeks ending %s and %s: months would count short" % (a.isoformat(), b.isoformat()))
    t = C.Tally(STATE, bands=BANDS, fluid=True)
    if carry:  # months before the window: the committed counts, at mid-month
        for b in BANDS:
            for ym, n in old[b].items():
                if ym < cut_month and n:
                    t.add(date(int(ym[:4]), int(ym[5:]), 15), b, n=n)
    seen, quiet, undated, no_county, no_company = set(), 0, 0, 0, 0
    for week in todo:
        sleep(pause)  # before every request to the server, the first list too
        try:
            rows, bad = week_rows(get(weeks[week], max_bytes=MAX_LIST), week)
        except ValueError as e:
            raise RuntimeError("the list for the week ending %s: %s" % (week.isoformat(), e))
        undated += bad
        quiet = 0 if rows else quiet + 1
        for day, work, purpose, county, operator, no in sorted(rows, key=lambda r: r[0]):
            if no in seen or day < start:
                continue  # a permit on two lists is counted once; a day before the window is the committed file's
            seen.add(no)
            band, fluid = band_and_fluid(work, purpose)
            hidden = county.strip().lower() in ("", "confidential")  # a confidential permit names no county and no company
            no_county += hidden
            no_company += operator.strip().lower() in ("", "confidential")
            t.add(day, band, county=None if hidden else county, operator=operator, fluid=fluid)
    if len(seen) < (MIN_PERMITS_WINDOW if carry else MIN_PERMITS_ALL):
        raise RuntimeError("only %d permits were read from %d weekly lists (expected %d or more)" % (len(seen), len(todo), MIN_PERMITS_WINDOW if carry else MIN_PERMITS_ALL))
    if max(no_county, no_company) > max(5, len(seen) // 10):
        raise RuntimeError("%d permits have no county and %d no company out of %d: a column may have been renamed" % (no_county, no_company, len(seen)))
    if undated > max(MAX_UNDATED, len(seen) // 50):
        raise RuntimeError("%d of %d permits have no date in reach of their list: the column may have changed" % (undated, len(seen)))
    if quiet >= 12:
        raise RuntimeError("the newest %d weekly lists hold no permit: the export may be broken" % quiet)
    note = ("Permits to drill, deepen, reopen or convert a well, by the day each was issued, from the Division's weekly lists (a workbook for each week ending on a Friday). A permit on two lists counts once. "
            "Injection, disposal, storage, water supply and test wells are told from the well type on the permit, and the fluid split is that type; reworks are conversions to injection, the only kind the "
            "lists carry; the lists have no amendments (shown as not available). The lists omit about 1% of permits (checked against the Geological Survey's well file in October 2026), so a month can be a little low. "
            "A month is shown once the lists reach its last day.")
    if undated:
        note += " %d permit%s with no readable issue date %s counted in the week of %s list." % (undated, "" if undated == 1 else "s", "is" if undated == 1 else "are", "its" if undated == 1 else "their")
    return t.document(agency="Kentucky Division of Oil and Gas", source_name="Weekly Permit Lists (one workbook a week)", source_url=SOURCE_URL, basis="issue date", cadence="weekly", measure="permits", asof=min(newest, today),
                      note=note)


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
