"""Tests for site/pipeline/ok_xlsx.py, the reader for the OCC's workbooks.

Synthetic workbooks cover the edge cases (an empty <row/>, cell attributes in another order, columns past Z, XML entities, rich text,
a second sheet, tiny chunk sizes) and are cross-checked against an independent reader, the ElementTree one in d6_misc.py. With
OK_REAL_FILES=<folder holding the OCC daily .xlsx files> the two readers are also compared on the real workbooks (those files carry
contact details and are never committed).

Run: python3 -I tests/test_ok_xlsx.py
"""
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(os.path.dirname(HERE), "site", "pipeline")
sys.path.insert(0, PIPE)
import d6_misc as D6  # noqa: E402
import ok_xlsx as X  # noqa: E402

FAILS = []
TMP = tempfile.mkdtemp()


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def workbook(sheet_xml_list, shared=None, names=("Sheet1",)):
    path = os.path.join(TMP, "synthetic.xlsx")
    with zipfile.ZipFile(path, "w") as z:
        sheets = "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i + 1, i + 1) for i, n in enumerate(names))
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>%s</sheets></workbook>' % sheets)
        rels = "".join('<Relationship Id="rId%d" Type="x" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(names)))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % rels)
        if shared is not None:
            z.writestr("xl/sharedStrings.xml", '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">%s</sst>' % "".join(shared))
        for i, body in enumerate(sheet_xml_list):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % body)
    return path


SHARED = ["<si><t>API</t></si>", "<si><t>Name</t></si>", "<si><t>Date</t></si>", "<si><t>X</t></si>",
          "<si><r><t>Rich </t></r><r><t>text</t></r></si>", "<si><t>A &amp; B &lt;ok&gt;</t></si>"]
ROWS = (
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="AA1" t="s"><v>3</v></c></row>'
    '<row r="2"><c r="A2"><v>3500100002</v></c><c r="B2" t="s"><v>4</v></c><c r="C2"><v>46323.5</v></c><c r="AA2" t="inlineStr"><is><t>Tom &amp; Jerry</t></is></c></row>'
    '<row r="3" spans="1:27" ht="15" customHeight="1"/>'                                                  # an empty row must not eat the next one
    '<row r="4"><c t="s" s="2" r="A4"><v>5</v></c><c r="B4" s="1"/><c r="C4" t="str"><v>2026-10-30</v></c></row>'   # other attribute order, an empty cell
    '<row r="5"><c r="AA5"><v>7</v></c></row>'                                                              # sparse row: only a far column
)

path = workbook([ROWS], SHARED)
got = list(X.rows(path))
check(len(got) == 4, "an empty <row/> is a row with no cells, not a swallowed neighbor: %d data rows" % len(got))
check(got[0] == {"API": "3500100002", "Name": "Rich text", "Date": "46323.5", "X": "Tom & Jerry"}, "shared, rich-text, numeric and inline cells read: %r" % got[0])
check(got[1] == {"API": None, "Name": None, "Date": None, "X": None}, "the empty row yields all-None: %r" % got[1])
check(got[2] == {"API": "A & B <ok>", "Name": None, "Date": "2026-10-30", "X": None}, "attributes in another order and an empty cell: %r" % got[2])
check(got[3] == {"API": None, "Name": None, "Date": None, "X": "7"}, "column AA (past Z) in a sparse row: %r" % got[3])
want = list(X.rows(path, want=("API", "X")))
check(all(set(r) == {"API", "X"} for r in want) and want[0]["X"] == "Tom & Jerry", "want= limits the columns")
try:
    list(X.rows(path, want=("API", "Nope")))
    check(False, "a missing wanted column should raise")
except ValueError as e:
    check("Nope" in str(e), "a missing wanted column names itself: %s" % e)
# an optional column that is not in the sheet is None in every row (a renamed figure then costs that figure, not the file); a wanted one is still an error
opt = list(X.rows(path, want=("API",), optional=("X", "Gone", "AlsoGone")))
check(len(opt) == 4 and all(set(r) == {"API", "X", "Gone", "AlsoGone"} for r in opt) and all(r["Gone"] is None and r["AlsoGone"] is None for r in opt) and opt[0]["X"] == "Tom & Jerry",
      "optional= reads the columns that are there and gives None for the ones that are not: %r" % opt[0])
try:
    list(X.rows(path, want=("API", "Nope"), optional=("X", "Gone")))
    check(False, "a missing wanted column should still raise when optional ones are given")
except ValueError as e:
    check("Nope" in str(e) and "Gone" not in str(e), "a missing wanted column still raises, naming only itself: %s" % e)
check(list(X.rows(path, want=("API",))) == [{"API": r["API"]} for r in opt], "without optional= nothing else is read: want= keeps its meaning")
check(X.col_number("A") == 1 and X.col_number("Z") == 26 and X.col_number("AA") == 27 and X.col_number("AZ") == 52 and X.col_number("ZZ") == 702, "col_number")
check(X.excel_date("46323.84444444445").isoformat().startswith("2026-10-28T20:16"), "excel_date: %s" % X.excel_date("46323.84444444445"))
check(X.excel_date("1") is None and X.excel_date("") is None and X.excel_date(None) is None and X.excel_date("abc") is None and X.excel_date("90000") is None, "excel_date refuses placeholders and junk")

path2 = workbook([ROWS, '<row r="1"><c r="A1" t="inlineStr"><is><t>H</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>second</t></is></c></row>'], SHARED, ("One", "Two"))
check(list(X.rows(path2, sheet=1)) == [{"H": "second"}], "sheet=1 reads the second worksheet")

# chunk boundaries: the same output when the sheet arrives a few bytes at a time
path = workbook([ROWS], SHARED)
saved = X.CHUNK
try:
    outs = set()
    for ch in (7, 13, 64, 1 << 20):
        X.CHUNK = ch
        outs.add(repr(list(X.rows(path))))
    check(len(outs) == 1, "output does not depend on the chunk size (7, 13, 64 bytes, 1 MB)")
finally:
    X.CHUNK = saved

# an independent reader (ElementTree, d6_misc) gives the same cells
z, shared, sheets = D6.xlsx_open(path)
it = D6.iter_rows(z, list(sheets.values())[0], shared)
_rn, hdr = next(it)
head = {i: str(v).strip() for i, v in hdr.items()}
indep = [{head[i]: v for i, v in vals.items() if i in head} for _rn, vals in it]
mine = list(X.rows(path))
bad = 0
for a, b in zip(mine, indep):
    for col, v in a.items():
        t = b.get(col)
        if v is None or v == "":
            bad += t not in (None, "")
        elif isinstance(t, float):
            bad += abs(float(v) - t) > 1e-9
        else:
            bad += str(t) != v
check(len(mine) == len(indep) and bad == 0, "the synthetic workbook reads the same with the ElementTree reader (%d rows, %d mismatches)" % (len(indep), bad))

# real workbooks, when a folder of them is given
real = os.environ.get("OK_REAL_FILES", "")
if real and os.path.isdir(real):
    for name in ("ITD-wells-formations-daily.xlsx", "completions-wells-formations-daily.xlsx", "well-transfers-daily.xlsx"):
        p = os.path.join(real, name)
        if not os.path.exists(p):
            continue
        new = list(X.rows(p))
        z, shared, sheets = D6.xlsx_open(p)
        it = D6.iter_rows(z, list(sheets.values())[0], shared)
        _rn, hdr = next(it)
        head = {i: str(v).strip() for i, v in hdr.items()}
        indep = [{head[i]: v for i, v in vals.items() if i in head} for _rn, vals in it]
        bad = 0
        for a, b in zip(new, indep):
            for col, v in a.items():
                t = b.get(col)
                if v is None or v == "":
                    bad += t not in (None, "")
                elif isinstance(t, bool):
                    bad += str(int(t)) != v
                elif isinstance(t, float):
                    try:
                        bad += abs(float(v) - t) > 1e-9
                    except ValueError:
                        bad += 1
                else:
                    bad += str(t) != v
        check(len(new) == len(indep) and bad == 0, "%s: %d rows, every cell equals the ElementTree reader's (%d mismatches)" % (name, len(new), bad))
else:
    print("skip  real workbooks: set OK_REAL_FILES to a folder of the OCC daily files to compare the readers on them")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
