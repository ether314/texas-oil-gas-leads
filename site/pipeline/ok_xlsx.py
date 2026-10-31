#!/usr/bin/env python3
"""A small reader for the first worksheet of an .xlsx, standard library only (zipfile and regular expressions).

The Oklahoma Corporation Commission publishes its permit and completion files as .xlsx workbooks of up to 150 MB (about
130 columns by several hundred thousand rows). ElementTree builds an element for every cell and manages about 2,000 rows
a second there; this reader scans the sheet XML in chunks and only touches the columns asked for, which is several times
faster. It handles what those files use: shared strings, inline strings and plain numbers or text, in any attribute order, with
empty (self-closing) rows and cells. It does not evaluate formulas, merged cells or styles, and dates come back as the
numbers the workbook stores (see excel_date).

    for row in rows(path, want=("API_Number", "Approval_Date")):   # dicts of the wanted columns, strings or None
        ...

The workbook is untrusted data: it is only read, never run, and every cell value is returned as text.
"""
import html
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CHUNK = 1 << 20


def col_number(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def excel_date(value):
    """The number Excel stores for a date and time (days since 1899-12-30) as a datetime, or None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return datetime(1899, 12, 30) + timedelta(days=f) if 20000 < f < 80000 else None


def _shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    with z.open("xl/sharedStrings.xml") as f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag == MAIN + "si":
                out.append("".join(t.text or "" for t in el.iter(MAIN + "t")))
                el.clear()
    return out


def sheet_member(z, index=0):
    """The member path of the index-th worksheet in workbook order."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = wb.find(MAIN + "sheets")
    target = rels[sheets[index].get(REL + "id")]
    return target.lstrip("/") if target.startswith("/") else "xl/" + target


# row and cell attributes (r, s, t, spans, ht ...) never contain a slash, so the attribute run can be matched greedily, which is
# much faster than lazily; a row or cell with nothing in it is written <row .../> or <c .../>
ROW = re.compile(rb"<row\b[^>/]*(?:/>|>(.*?)</row>)", re.S)
CELL = re.compile(rb"<c\b([^>/]*)(?:/>|>(.*?)</c>)", re.S)
REF = re.compile(rb'\br="([A-Z]+\d+)"')  # for a cell whose r= is not its first attribute (the usual case is read with a slice)
COLNUM = {}
VALUE = re.compile(rb"<v>(.*?)</v>", re.S)
INLINE = re.compile(rb"<t[^>]*>(.*?)</t>", re.S)


def rows(path, want=None, sheet=0, optional=()):
    """Yield one dict per data row: {header: text or None} for the wanted columns (all of them when want is None). The first
    row is the header. Rows are yielded in file order. A wanted column that is not in the sheet is an error; an `optional` one
    that is not there is None in every row (a renamed column then costs a figure, not the whole file)."""
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        with z.open(sheet_member(z, sheet)) as f:
            buf, head, cols, absent = b"", None, None, ()
            while True:
                chunk = f.read(CHUNK)
                buf += chunk
                end = 0
                for m in ROW.finditer(buf):
                    end = m.end()
                    cells = {}
                    for c in CELL.finditer(m.group(1) or b""):
                        attrs, inner = c.group(1), c.group(2) or b""
                        if attrs.startswith(b' r="'):
                            ref = attrs[4:attrs.index(b'"', 4)]
                        else:
                            found = REF.search(attrs)
                            if not found:
                                continue
                            ref = found.group(1)
                        letters = ref.rstrip(b"0123456789")
                        n = COLNUM.get(letters)
                        if n is None:
                            n = COLNUM[letters] = col_number(letters.decode("ascii"))
                        if cols is not None and n not in cols:
                            continue
                        if b' t="s"' in attrs:
                            v = VALUE.search(inner)
                            val = shared[int(v.group(1))] if v else None
                        elif b' t="inlineStr"' in attrs:
                            val = html.unescape("".join(x.decode("utf-8", "replace") for x in INLINE.findall(inner)))
                        else:
                            v = VALUE.search(inner)
                            val = html.unescape(v.group(1).decode("utf-8", "replace")) if v else None
                        cells[n] = val
                    if head is None:
                        head = {n: (v or "").strip() for n, v in cells.items()}
                        cols = {n: h for n, h in head.items() if want is None or h in want or h in optional}
                        missing = set(want or ()) - set(cols.values())
                        if missing:
                            raise ValueError("columns not in the sheet: %s" % ", ".join(sorted(missing)))
                        absent = [h for h in optional if h not in cols.values()]
                        continue
                    yield {**{h: None for h in absent}, **{h: cells.get(n) for n, h in cols.items()}}
                buf = buf[end:]
                if not chunk:
                    break
