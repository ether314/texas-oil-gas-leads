"""Tests for site/pipeline/d11_nat_oh.py: Ohio's permits (ODNR, Division of Oil and Gas Resources Management) from the Permit and Plug List's Excel export.

The fixtures are invented and written the way the real page answers (found by looking on 2026-11-01): an ASP.NET form with hidden state fields, a results grid with a pager ("Item 1 to 25 of N") and an
"Export To Excel" button whose answer is an old binary .xls of the whole result, 70 columns (with the operator's address, phones and contacts, which must never be read), dates as text (10/19/2026), a
search capped at 1,000 rows, every application of some rows listed twice, and a server that now and then redirects a request to its home page. The fake server checks what a browser would be checked on:
the posted view state, the two dates in three forms that agree, the Permit filter. They pin: the .xls reader (and that only seven columns leave it), the form the producer posts, the grid total, the
export checked against it, the cap (a capped window is split, a capped week fails), the repeats counted once, the band of every application type seen in 2019 to 2026, the well type on a new-well
permit, an unknown application type or well type failing the run, the privacy rule on a person-named operator, the committed file carrying the older months so that a weekly run reads one window, the
redirect and refusal handling of the client (pauses, tries, no retry after a refusal), and that a damaged export, a changed form, a stale list and too few permits fail instead of writing a short file.
The network is faked.

Run: python3 -I tests/test_d11_oh.py"""
import json
import os
import struct
import sys
import tempfile
import urllib.error
from datetime import date, timedelta
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d11_nat_common as C  # noqa: E402
import d11_nat_ky as KY  # noqa: E402
import d11_nat_oh as OH  # noqa: E402

FAILS = []
TODAY = date(2026, 11, 1)


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


def says(fn, text, kind=RuntimeError):
    """True when fn raises `kind` with `text` in its message: the right failure, not just any."""
    try:
        fn()
    except kind as e:
        return text in str(e)
    except Exception as e:  # noqa: BLE001
        print("     raised %s: %s" % (type(e).__name__, e))
        return False
    return False


COLUMNS = ["NAME", "WH_LOT", "WH_SEC", "WH_LAT83", "WH_LONG83", "WH_LAT", "WH_LONG", "QUAD_NAME", "CONAME", "ADDR1", "ADDR2", "CITY", "STATE", "ZIP1", "PHONE", "CNTY_APINO", "WH_CV_TWPNO", "CV_TWPNM",
           "DT_APP_ISSUED", "APP_TYP", "APPNO", "DT_APP_RECVD", "YN_RUSH_APP", "RUSH_CHKNO", "RUSH_AMT", "APP_CHKNO", "FEE_AMT", "REVISED_AMT", "REVISED_CHKNO", "VARIANCE", "POOL_AMT", "OPNO", "CO_REP",
           "PM_ADDROK", "PM_CONTACT", "PM_ADDR1", "PM_ADDR2", "PM_CITY", "PM_STATE", "PM_ZIP1", "PM_ZIP2", "PM_COUNTRY", "PM_PHONENO", "EXIST_WELL", "LOCATION_ID", "WELLNM", "WELLNO", "DU_ACRES", "RIG_TYP",
           "FIRE_PHNO", "MEDL_PHNO", "PROP_WLTYPE", "PROP_TD", "PROP_WELL_CLASS", "PROPOSEDFORMATIONS", "ELEV_GR", "ELEV_TGT", "API_WELLNO", "WH_FTCALLS", "BH_LOT", "BH_SEC", "BH_FTCALLS", "BH_ALLOTMENT",
           "BH_X", "BH_Y", "BH_OGS_QUADCODE", "BH_CV_TWPNO", "QUAD_NAME_T", "APP_TYP_Description", "BH_CV_TWPNM"]
assert len(COLUMNS) == 70
NUMERIC = {"WH_LAT83", "WH_LONG83", "OPNO", "PROP_TD", "DU_ACRES", "RUSH_AMT", "FEE_AMT", "ELEV_GR", "CNTY_APINO"}
# strings that must never reach an output: an operator's mailing address and phones, its representative, the contact, a well's name and API number
NEVER = ["1 INVENTED STREET", "+1 (304) 555-0100", "A. N. EXAMPLE", "B. PERSON", "+1 (740) 555-0133", "INVENTED LEASE 2H", "34999099990000", "2 INVENTED ROAD", "EXAMPLETOWN"]
JUNK = {"ADDR1": NEVER[0], "CITY": "EXAMPLETOWN", "STATE": "WV", "ZIP1": "26508", "PHONE": NEVER[1], "CO_REP": NEVER[2], "PM_CONTACT": NEVER[3], "PM_ADDR1": NEVER[7], "PM_PHONENO": "+1 (740) 555-0111",
        "FIRE_PHNO": "+1 (740) 555-0122", "MEDL_PHNO": NEVER[4], "WELLNM": NEVER[5], "API_WELLNO": NEVER[6], "WH_LAT83": 40.161479, "WH_LONG83": -81.470782, "OPNO": 10700, "PROP_TD": 11200,
        "DU_ACRES": 469.525, "PM_COUNTRY": "USA", "PROPOSEDFORMATIONS": "UTICASHALE, POINTPLEASANTFORMATION", "FEE_AMT": 0}


# ------------------------------------------------------------------------------------------------ writers for the fixtures (an .xls like the Division's: LABEL and NUMBER cells, 70 columns)

def rec(rid, data):
    return struct.pack("<HH", rid, len(data)) + data


def label(r, c, text):
    if text == "":
        return rec(0x0204, struct.pack("<HHHH", r, c, 15, 0))  # an empty text cell is eight bytes, with no flag byte (found in the real export)
    wide = any(ord(ch) > 255 for ch in text)
    return rec(0x0204, struct.pack("<HHHHB", r, c, 15, len(text), 1 if wide else 0) + (text.encode("utf-16-le") if wide else text.encode("latin-1")))


def xls_stream(table, header=COLUMNS):
    bof = lambda kind: rec(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 6))  # noqa: E731
    out = bof(5) + rec(0x000A, b"") + bof(0x10)
    for r, row in enumerate([header] + table):
        for c, v in enumerate(row):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out += rec(0x0203, struct.pack("<HHHd", r, c, 15, float(v)))
            else:
                out += label(r, c, "" if v is None else str(v))
    return out + rec(0x000A, b"")


def ole(stream):
    """An OLE2 compound file with one stream named Workbook in regular sectors (padded to 4096 bytes), with as many FAT sectors as it needs."""
    END, FREE, FATSEC = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
    data = stream.ljust(max(4096, -(-len(stream) // 512) * 512), b"\0")
    n = len(data) // 512
    f = 1
    while f * 128 < f + 1 + n:
        f += 1
    fat = [FATSEC] * f + [END] + [f + 2 + i for i in range(n - 1)] + [END]
    fat += [FREE] * (f * 128 - len(fat))

    def entry(t, kind, start, size):
        e = (t.encode("utf-16-le") + b"\0\0").ljust(64, b"\0") + struct.pack("<HBB", len(t) * 2 + 2, kind, 1) + struct.pack("<iii", -1, -1, -1)
        return e + b"\0" * 36 + struct.pack("<IQ", start, size)

    directory = entry("Root Entry", 5, END, 0) + entry("Workbook", 2, f + 1, len(data)) + b"\0" * 256
    head = KY.OLE_MAGIC + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
    head += struct.pack("<IIIIIIIII", 0, f, f, 0, 4096, END, 0, END, 0)
    head += struct.pack("<109I", *(list(range(f)) + [FREE] * (109 - f)))
    assert len(head) == 512
    return head + struct.pack("<%dI" % (f * 128), *fat) + directory + data


def permit(day, code="RINW", county="Guernsey", operator="ACME TEST OPERATING LLC", wl="OG_R", appno=None, dup=False, desc=None):
    return {"day": day, "code": code, "county": county, "operator": operator, "wl": wl, "appno": appno or "PR%s%05d" % (day.strftime("%Y%m%d"), hash((day, code, county, operator)) % 100000), "dup": dup,
            "desc": desc or OH.TYPES.get(code, ("", code))[1]}


def cells_of(p):
    row = dict(JUNK, NAME=p["county"].upper(), CONAME=p["operator"], DT_APP_ISSUED=p["day"].strftime("%m/%d/%Y"), DT_APP_RECVD=(p["day"] - timedelta(days=20)).strftime("%m/%d/%Y"), APP_TYP=p["code"],
               APPNO=p["appno"], PROP_WLTYPE=p["wl"], APP_TYP_Description=p["desc"])
    return [row.get(h, "") for h in COLUMNS]


def export_bytes(permits, header=COLUMNS):
    table = []
    for p in permits:
        table += [cells_of(p)] * (2 if p["dup"] else 1)
    return ole(xls_stream(table, header))


# ------------------------------------------------------------------------------------------------ the fake server: the form, the grid, the export, the cap, the checks a browser would meet

class Server:
    """Stands in for `OH.Client`: `fetch(url, fields)` answers like the Permit and Plug List. A POST must carry a view state the server issued and the two dates in three forms that agree;
    the Permit or Plug list filters (Permit leaves the plug permits out); the search and the export both stop at `cap` rows."""

    def __init__(self, permits, cap=1000, header=COLUMNS, mutate=None, grid_extra=0, button=True):
        self.permits, self.cap, self.header, self.mutate, self.grid_extra, self.button = permits, cap, header, mutate, grid_extra, button
        self.issued, self.log, self.n = set(), [], 0

    def token(self):
        self.n += 1
        t = "VS%06d/+=" % self.n
        self.issued.add(t)
        return t

    def hidden(self):
        return ('<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" /><input type="hidden" name="__EVENTARGUMENT" id="__EVENTARGUMENT" value="" />'
                '<input type="hidden" name="DES_LinkIDState" id="DES_LinkIDState" value="0|2|3" /><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="%s" />'
                '<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="52B14ADF" /><input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV%06d" />'
                '<input id="ctl00_RadMenu1_ClientState" name="ctl00_RadMenu1_ClientState" type="hidden" />' % (self.token(), self.n))

    def form(self, grid=""):
        p, i = OH.P, OH.I

        def picker(key, word):
            return ('<input style="visibility:hidden" name="%s%s" type="text" class="rdfd_" value="" /><input name="%s%s$dateInput" class="riTextBox riEmpty" value="%s" type="text" />'
                    '<input name="%s%s_dateInput_ClientState" type="hidden" /><input name="%s%s_calendar_SD" type="hidden" value="[]" />'
                    '<input name="%s%s_calendar_AD" type="hidden" value="[[1700,1,1],[2099,12,30],[2026,11,1]]" /><input name="%s%s_ClientState" type="hidden" />'
                    % (p, key, p, key, word, i, key, i, key, i, key, i, key))

        return ("<html><body><form name='aspnetForm' method='post'>" + self.hidden() + "<h1>Permit and Plug List</h1>" + picker(OH.START, "start") + picker(OH.END, "end")
                + '<input name="%sddlCounty_ClientState" type="hidden" /><input name="%sddlApplicationType_ClientState" type="hidden" /><input name="%sddlPermitOrPlug_ClientState" type="hidden" />' % (i, i, i)
                + '<input name="%sRN_SectionNumber" value="equals" type="text" /><input name="%sRN_SectionNumber_ClientState" type="hidden" />' % (p, i)
                + '<input name="%stxtLot" value="containing" type="text" /><input name="%stxtCompanyName" value="containing" type="text" />' % (p, p)
                + '<input type="submit" name="%sbtnSearch" value="View Report" /><input type="submit" name="%sbtnClear" value="Clear" />' % (p, p) + grid + "</form></body></html>").encode()

    def rows(self, start, end, filt):
        out = [x for x in self.permits if start <= x["day"] <= end and (filt != "Permit" or x["code"] not in OH.PLUG_TYPES)]
        out.sort(key=lambda x: (x["day"], x["appno"]))
        flat = []
        for x in out:
            flat += [x] * (2 if x["dup"] else 1)
        return flat[: self.cap]

    def fetch(self, url, fields=None, max_bytes=None):
        if fields is None:
            self.log.append(("GET",))
            return self.form()
        if fields.get("__VIEWSTATE") not in self.issued:
            return b"<html><body>Validation of viewstate MAC failed</body></html>"
        P, I = OH.P, OH.I
        days = []
        for key in (OH.START, OH.END):
            m, d, y = (int(x) for x in fields[P + key + "$dateInput"].split("/"))
            iso = date(y, m, d).isoformat()
            state = json.loads(fields[I + key + "_dateInput_ClientState"])
            assert fields[P + key] == iso and state["valueAsString"] == iso + "-00-00-00" and state["lastSetTextBoxValue"] == fields[P + key + "$dateInput"], "the three forms of the date disagree"
            days.append(date(y, m, d))
        filt = (json.loads(fields[I + "ddlPermitOrPlug_ClientState"] or "{}")).get("selectedValue")
        export = next((k for k in fields if k.endswith("$b_export")), None)
        rows = self.rows(days[0], days[1], filt)
        self.log.append(("EXPORT" if export else "SEARCH", days[0], days[1], filt, len(rows)))
        if export:
            body = export_bytes(self.rows_unique(rows), self.header)
            return self.mutate(body) if self.mutate else body
        if P + "btnSearch" not in fields:
            return self.form()
        shown = rows[:25]
        trs = "".join('<tr class="%s" id="ctl00_ContentPlaceholder1_RG_Results_ctl00__%d"><td>%s</td></tr>' % ("rgRow" if i % 2 == 0 else "rgAltRow", i, escape(x["county"])) for i, x in enumerate(shown))
        pager = ('<tr class="rgPager"><td>&nbsp;Item <strong>1</strong> to <strong>25</strong> of <strong>%d</strong></td></tr>' % (len(rows) + self.grid_extra)) if len(rows) > 25 else ""
        btn = '<input type="submit" name="ctl00$ContentPlaceholder1$RG_Results$ctl00$ctl03$ctl01$b_export" value="Export To Excel" />' if self.button else ""
        empty = '<tr class="rgNoRecords"><td colspan="70" style="text-align:left;"><div>No Records Available</div></td></tr>' if not rows else ""
        grid = '<table id="ctl00_ContentPlaceholder1_RG_Results_ctl00"><tfoot><tr class="rgCommandRow"><td>%s</td></tr>%s</tfoot><tbody>%s%s</tbody></table>' % (btn, pager, trs, empty)
        return self.form(grid)

    def rows_unique(self, flat):
        """The export is flat rows; export_bytes doubles the `dup` ones itself, so give it each permit once."""
        out, last = [], None
        for x in flat:
            if x is not last:
                out.append(x)
            last = x
        return out


# ------------------------------------------------------------------------------------------------ the .xls reader
P1 = permit(date(2026, 10, 19), "RINW", "Guernsey", "INR OHIO LLC", appno="PR2026042400194")
P2 = permit(date(2026, 10, 20), "RID", "", "OWS ACQUISITION CO LLC", appno="PR2026080500371")  # an empty county: an eight-byte text cell
P3 = permit(date(2026, 10, 21), "RIPL", "Muskingum", "CAFÉ – TEST OIL LLC", appno="PR2026090100002")  # an accent and a dash: a text cell in 16 bits
got = OH.read_export(export_bytes([P1, P2, P3]))
check([r["DT_APP_ISSUED"] for r in got] == ["10/19/2026", "10/20/2026", "10/21/2026"] and got[0]["APP_TYP"] == "RINW" and got[0]["CONAME"] == "INR OHIO LLC" and got[0]["NAME"] == "GUERNSEY" and got[0]["PROP_WLTYPE"] == "OG_R"
      and got[0]["APPNO"] == "PR2026042400194" and got[0]["APP_TYP_Description"] == "RICS Permit to Drill New Well", "the export reads: the seven columns of each row, in order, as text")
check(got[1]["NAME"] == "" and got[2]["CONAME"] == "CAFÉ – TEST OIL LLC", "an empty text cell reads as empty (eight bytes, no flag) and a 16-bit text cell reads whole")
check(all(set(r) == set(OH.WANT) for r in got) and not any(s in json.dumps(got) for s in NEVER), "only the seven wanted columns leave the reader: no address, phone, representative, contact, well name or API number")
check(OH.read_export(export_bytes([])) == [], "an export with a header and no row has no rows")
check(says(lambda: OH.read_export(export_bytes([P1], header=["DATE_ISSUED" if h == "DT_APP_ISSUED" else h for h in COLUMNS])), "no header row", ValueError), "a renamed issue-date column raises")
check(says(lambda: OH.read_export(export_bytes([P1], header=["OPERATOR" if h == "CONAME" else h for h in COLUMNS])), "CONAME", ValueError), "a renamed operator column raises, naming it")
check(says(lambda: OH.read_export(export_bytes([P1], header=[h for h in COLUMNS if h != "APPNO"])), "APPNO", ValueError), "a missing application-number column raises, naming it")
data = export_bytes([P1, P2, P3])
for what, bad in (("a page of HTML", b"<html><body>Home</body></html>"), ("nothing", b""), ("cut in half", data[:len(data) // 2]), ("the signature gone", b"\0" * 8 + data[8:]), ("cut to a header", data[:512])):
    check(raises(lambda: OH.read_export(bad), ValueError), "a damaged export (%s) raises ValueError" % what)
check(says(lambda: OH.read_export(b"<html><body>Home</body></html>"), "not an Excel file", ValueError), "a page of HTML is named as such")
half = xls_stream([cells_of(P1)])[:-4] + rec(0x0204, struct.pack("<HHHHB", 1, 3, 15, 10, 0) + b"abc") + rec(0x000A, b"")  # a text cell that says 10 characters and holds 3
check(raises(lambda: OH.read_export(ole(half)), ValueError), "a text cell cut short raises ValueError (not another kind of error)")

# ------------------------------------------------------------------------------------------------ the form a browser would send
srv = Server([])
form = srv.form().decode()
f = OH.form_fields(form, date(2026, 10, 19), date(2026, 10, 25), OH.SEARCH_BUTTON)
check(f["__VIEWSTATE"].startswith("VS") and f["__EVENTVALIDATION"].startswith("EV") and f["__EVENTTARGET"] == "" and f["DES_LinkIDState"] == "0|2|3", "every hidden field of the page goes back as it came (view state, validation, the rest)")
check(f[OH.P + OH.START + "$dateInput"] == "10/19/2026" and f[OH.P + OH.START] == "2026-10-19" and f[OH.P + OH.END + "$dateInput"] == "10/25/2026" and f[OH.P + OH.END] == "2026-10-25"
      and json.loads(f[OH.I + OH.START + "_dateInput_ClientState"])["valueAsString"] == "2026-10-19-00-00-00" and json.loads(f[OH.I + OH.END + "_dateInput_ClientState"])["lastSetTextBoxValue"] == "10/25/2026", "the two dates go in as the picker sends them: display text, ISO stamp and client state")
check(json.loads(f[OH.I + "ddlPermitOrPlug_ClientState"])["selectedValue"] == "Permit" and f[OH.P + "btnSearch"] == "View Report" and f[OH.P + "txtLot"] == "containing" and f[OH.P + "RN_SectionNumber"] == "equals", "the Permit list is chosen, the empty boxes carry their placeholders and the search button is pressed")
check(OH.P + "btnSearch" in f and not any(k.endswith("b_export") for k in f), "a search does not press the export button")
e = OH.form_fields(form, date(2026, 1, 1), date(2026, 11, 1), ("ctl00$X$b_export", "Export To Excel"))
check(e["ctl00$X$b_export"] == "Export To Excel" and OH.P + "btnSearch" not in e and e[OH.P + OH.START + "$dateInput"] == "1/1/2026", "an export presses the export button instead (and a date has no leading zero)")
check(raises(lambda: OH.form_fields(form.replace("__VIEWSTATE", "__VIEWSTATX"), date(2026, 1, 1), date(2026, 2, 1), OH.SEARCH_BUTTON)) and raises(lambda: OH.form_fields(form.replace("$dateInput", "$dateInpux"), date(2026, 1, 1), date(2026, 2, 1), OH.SEARCH_BUTTON)),
      "a form without its view state or its date boxes fails (the page changed)")
check([t for n, t, v in OH.inputs('<input type="hidden" name="a" value="x&amp;y"><INPUT name="b" value=3><input type=checkbox value=1>') if n == "a"] == ["hidden"] and dict((n, v) for n, t, v in OH.inputs('<input type="hidden" name="a" value="x&amp;y">'))["a"] == "x&y", "the form parser reads attributes and un-escapes values")

# ------------------------------------------------------------------------------------------------ the grid's total
def grid(n_shown, total=None, pager=True, cls=True):
    rows = "".join('<tr class="%s" id="x_%d"><td>x</td></tr>' % ("rgRow" if i % 2 == 0 else "rgAltRow", i) for i in range(n_shown))
    info = '<tr class="rgPager"><td>&nbsp;Item <strong>1</strong> to <strong>%d</strong> of <strong>%d</strong></td></tr>' % (n_shown, total) if pager and total is not None else ""
    return '<table %s><tfoot>%s</tfoot><tbody>%s</tbody></table>' % (OH.GRID, info, rows)


check(OH.grid_total(grid(25, 827)) == 827 and OH.grid_total(grid(25, 1000)) == 1000, "the total is the grid's own 'of N'")
check(OH.grid_total(grid(14, pager=False)) == 14 and OH.grid_total(grid(25, pager=False)) == 25 and OH.grid_total(grid(0, pager=False).replace("<tbody>", '<tbody><tr class="rgNoRecords"><td><div>No Records Available</div></td></tr>')) == 0,
      "with no pager the total is the rows shown (14, a full page of 25), and an empty grid that says 'No Records Available' is 0")
check(raises(lambda: OH.grid_total(grid(0, pager=False))), "an empty grid that does not say there are no records fails (a page that did not run the search)")
check(raises(lambda: OH.grid_total("<html>Welcome to ODNR</html>")) and raises(lambda: OH.grid_total(grid(25, 20))) and raises(lambda: OH.grid_total(grid(30, pager=False)))
      and raises(lambda: OH.grid_total(grid(25, 827).replace("to <strong>25</strong>", "to <strong>24</strong>"))) and raises(lambda: OH.grid_total(grid(25, 827).replace("Item <strong>1</strong>", "Item <strong>26</strong>"))),
      "a page with no grid, a total below the rows shown, 30 rows with no pager, and a pager that disagrees with the rows each fail")

# ------------------------------------------------------------------------------------------------ the client: pauses, redirects, refusals
class Resp:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    """A fake opener that answers from a script: bytes (a good answer) or an exception to raise; records each request."""

    def __init__(self, script):
        self.script, self.seen = list(script), []

    def open(self, req, timeout=None):
        self.seen.append(req)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return Resp(step)


class Time:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def moved():
    return urllib.error.HTTPError(OH.PAGE, 302, "Found", {"Location": "https://ohiodnr.gov/"}, None)


def client(script, **kw):
    tm = Time()
    op = Opener(script)
    return OH.Client(opener=op, sleep=tm.sleep, clock=tm.clock, **kw), op, tm


c, op, tm = client([b"page one", b"page two"])
check(c.fetch(OH.PAGE) == b"page one" and tm.slept == [] and c.fetch(OH.PAGE, {"a": "1"}) == b"page two" and len(tm.slept) == 1 and tm.slept[0] >= OH.PAUSE - 0.001,
      "a pause of at least %d seconds comes before every request but the first" % OH.PAUSE)
r1, r2 = op.seen
check(r1.get_method() == "GET" and r2.get_method() == "POST" and r2.data == b"a=1" and r2.headers["Content-type"] == "application/x-www-form-urlencoded" and r1.headers["User-agent"] == C.UA and r2.headers["User-agent"] == C.UA
      and r2.headers["Referer"] == OH.PAGE and "Cookie" not in r1.headers, "a GET is a GET, a form is a POST with its content type, and both send only the common agent (no cookie of ours)")
c, op, tm = client([moved(), moved(), b"ok"])
check(c.fetch(OH.PAGE) == b"ok" and len(op.seen) == 3 and tm.slept == [OH.RETRY_PAUSE, OH.RETRY_PAUSE], "a redirect to the home page is tried again after %d seconds, and an answer after two redirects is taken" % OH.RETRY_PAUSE)
c, op, tm = client([moved()] * OH.TRIES + [b"never"])
check(raises(lambda: c.fetch(OH.PAGE), C.Refused) and len(op.seen) == OH.TRIES, "a request redirected every one of its %d tries ends as a refusal and is not tried again" % OH.TRIES)
c, op, tm = client([urllib.error.HTTPError(OH.PAGE, 403, "Forbidden", {}, None), b"never"])
check(raises(lambda: c.fetch(OH.PAGE), C.Refused) and len(op.seen) == 1 and tm.slept == [], "a 403 is a refusal at once, with no second try")
for code in (401, 407, 429):
    c, op, tm = client([urllib.error.HTTPError(OH.PAGE, code, "x", {}, None), b"never"])
    check(raises(lambda: c.fetch(OH.PAGE), C.Refused) and len(op.seen) == 1, "HTTP %d is a refusal at once" % code)
c, op, tm = client([urllib.error.HTTPError(OH.PAGE, 500, "x", {}, None)] * OH.TRIES)
try:
    c.fetch(OH.PAGE)
    err = None
except Exception as e:  # noqa: BLE001
    err = e
check(isinstance(err, RuntimeError) and not isinstance(err, C.Refused) and len(op.seen) == OH.TRIES, "four server errors fail the run (exit 1), they are not called a refusal")
c, op, tm = client([urllib.error.URLError(OSError("x")), ConnectionResetError("x"), b"ok"])
check(c.fetch(OH.PAGE) == b"ok" and len(op.seen) == 3, "a dropped connection is tried again")
c, op, tm = client([b"x" * 50])
check(raises(lambda: c.fetch(OH.PAGE, max_bytes=10)), "a reply larger than the cap is refused")
check(OH._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://ohiodnr.gov/") is None, "the real opener does not follow a redirect")
check("@" not in json.dumps([dict(r.headers) for r in op.seen]) and OH.PAGE.startswith("https://"), "a request names no person (no address in any header) and goes over TLS")

# ------------------------------------------------------------------------------------------------ the band of every application type seen in 2019 to 2026
EXPECT = {"RINW": "new", "HX": "new", "NW": "new", "HX0": "new", "UC2": "new", "UX2": "new", "NX": "new", "UC0": "new", "SWIW": "inj", "RID": "redrill", "DDHX": "redrill", "DHX0": "redrill", "DD": "redrill",
          "DD0": "redrill", "OP": "redrill", "PBHX": "redrill", "PX": "redrill", "PX2": "redrill", "PB": "rework", "CO": "rework", "CS": "rework", "RIC": "rework", "RIPL": "amend", "RIRI": "amend", "RHX": "amend",
          "RN": "amend", "RRHX": "amend", "RSWI": "amend", "RNU0": "amend", "RHX0": "amend", "RX2": "amend", "RDHX": "amend", "RD": "amend", "RB": "amend", "SMP": "other"}
check(set(OH.TYPES) == set(EXPECT) and len(EXPECT) == 35, "the table holds the 35 application types seen on the Permit list from 2019 to 2026, no more and no fewer")
for code, band in EXPECT.items():
    row = {"APP_TYP": code, "APP_TYP_Description": OH.TYPES[code][1], "PROP_WLTYPE": "OG_R"}
    check(OH.classify(row) == band, "%s (%s) is %s" % (code, OH.TYPES[code][1], band))
check(all(b in C.BANDS for b, _d in OH.TYPES.values()), "every band in the table is one of the report's six")
for wl, band in (("OG_R", "new"), ("GS_R", "inj"), ("ST_R", "inj"), ("SW_R", "inj"), ("SWD", "inj"), ("ER_R", "inj"), ("SM_R", "other"), ("MN_R", "other"), ("", "new")):
    check(OH.classify({"APP_TYP": "RINW", "APP_TYP_Description": "x", "PROP_WLTYPE": wl}) == band, "a new-well permit for well type %r is %s" % (wl, band))
check(OH.classify({"APP_TYP": "RID", "APP_TYP_Description": "x", "PROP_WLTYPE": "GS_R"}) == "redrill" and OH.classify({"APP_TYP": "RN", "APP_TYP_Description": "x", "PROP_WLTYPE": "SM_R"}) == "amend",
      "the well type changes only a new-well permit: a deepening of a gas-storage well is still a re-entry")
check(says(lambda: OH.classify({"APP_TYP": "ZZ9", "APP_TYP_Description": "Something New", "PROP_WLTYPE": "OG_R"}), "does not know"), "an application type never seen before fails the run (it is not filed under other)")
check(says(lambda: OH.classify({"APP_TYP": "RINW", "APP_TYP_Description": "x", "PROP_WLTYPE": "XYZ_R"}), "well type"), "a well type never seen before, on a new-well permit, fails the run")
for code in sorted(OH.PLUG_TYPES):
    check(says(lambda: OH.classify({"APP_TYP": code, "APP_TYP_Description": "x", "PROP_WLTYPE": "OG_R"}), "filter was not applied"), "a plug permit (%s) on the Permit list fails the run (the filter was not applied)" % code)
check(not (OH.PLUG_TYPES & set(OH.TYPES)), "no plug code is also a permit code")


# ------------------------------------------------------------------------------------------------ one window
def world(first=date(2019, 1, 1), last=date(2026, 10, 28), per_month=18, plug_each=3):
    """Permits on a calendar: per month `per_month` Permit-list permits of mixed kinds, some of them listed twice, and `plug_each` plug permits (the Plug list), the last one on `last`."""
    kinds = [("RINW", "OG_R"), ("RINW", "OG_R"), ("HX", "OG_R"), ("RID", "OG_R"), ("RIPL", "OG_R"), ("RINW", "GS_R"), ("SWIW", "SW_R"), ("PB", "OG_R"), ("RIRI", "OG_R"), ("OP", "OG_R")]
    ops = ["ACME TEST OPERATING LLC", "BETA ENERGY CORP", "JOHN Q EXAMPLE DBA J Q OIL", "GAMMA PARTNERS LP", "J. EXAMPLE", "DELTA RESOURCES INC", "", "EPSILON OIL & GAS LLC"]
    counties = ["Guernsey", "Harrison", "Monroe", "Belmont", "Carroll", "Jefferson", "Noble"]
    out, k = [], 0
    ym = C.month_of(first)
    while ym <= C.month_of(last):
        y, m = int(ym[:4]), int(ym[5:])
        for i in range(per_month):
            code, wl = kinds[(k + i) % len(kinds)]
            day = date(y, m, 1 + (i * 3 + k) % 27)
            if day > last:
                day = last
            out.append(permit(day, code, counties[(k + i) % 7], ops[(k + 2 * i) % len(ops)], wl, appno="PR%d%02d%03d" % (y, m, i), dup=(k + i) % 5 == 0))
            k += 1
        for i in range(plug_each):
            out.append(permit(date(y, m, min(28, 2 + i * 7)) if date(y, m, min(28, 2 + i * 7)) <= last else last, "RIPW", "Stark", "PLUGGER LLC", "OG_R", appno="PL%d%02d%03d" % (y, m, i)))
        ym = C.add_months(ym, 1)
    return out


W = world()
srv = Server(W)
form = srv.fetch(OH.PAGE).decode()
rows = OH.read_window(srv, form, date(2026, 10, 1), date(2026, 10, 31))
inwin = [x for x in W if date(2026, 10, 1) <= x["day"] <= date(2026, 10, 31) and x["code"] not in OH.PLUG_TYPES]
check(len(rows) == len(inwin) + sum(1 for x in inwin if x["dup"]) and srv.log[-2][0] == "SEARCH" and srv.log[-1][0] == "EXPORT" and srv.log[-1][3] == "Permit", "a window is a search and an export, both on the Permit list; the export holds the grid's rows (repeats too)")
check(not any(r["APP_TYP"] in OH.PLUG_TYPES for r in rows), "the Permit filter leaves the plug permits out")
q = Server([])
check(OH.read_window(q, q.fetch(OH.PAGE).decode(), date(2026, 10, 1), date(2026, 10, 31)) == [] and [x[0] for x in q.log] == ["GET", "SEARCH"], "a window with no permit is empty and asks for no export")
YEAR = (date(2026, 1, 1), date(2026, 10, 31))  # about 200 rows: a pager


def window(server, a, b):
    """read_window on a server with a form of its own (a view state it issued)."""
    return OH.read_window(server, server.fetch(OH.PAGE).decode(), a, b)


check(len(window(Server(W), *YEAR)) > 100 and says(lambda: window(Server(W, grid_extra=3), *YEAR), "grid counted"), "an export with fewer rows than the grid counted fails (and a good one reads)")
check(says(lambda: window(Server(W, grid_extra=-3), *YEAR), "grid counted"), "an export with more rows than the grid counted fails")
check(says(lambda: window(Server(W, button=False), *YEAR), "Export To Excel"), "a results page with no Export To Excel button fails")
check(says(lambda: window(Server(W, mutate=lambda b: b"<html>Home</html>"), *YEAR), "not an Excel file"), "an export that is a page of HTML fails")
check(says(lambda: window(Server(W, mutate=lambda b: b[:len(b) // 2]), *YEAR), "2026-01-01 to 2026-10-31"), "a cut-short export fails, naming its window")
bad = Server(W)
bad.fetch = lambda url, fields=None, max_bytes=None: b"<html><body>Welcome to ODNR</body></html>"
check(says(lambda: OH.read_window(bad, form, date(2026, 10, 1), date(2026, 10, 31)), "no results grid"), "a reply that is not the results page (the home page) fails")
fb = Server(W)
fb.fetch(OH.PAGE)
check(says(lambda: OH.read_window(fb, form.replace("VS", "OLDVS"), date(2026, 10, 1), date(2026, 10, 31)), "no results grid"), "a view state the server did not issue gets an error page, and that fails")
out = []
OH.read_range(srv, form, date(2026, 10, 1), date(2026, 10, 31), out, TODAY)
check(len(out) == len(rows) and all(date(2026, 10, 1) <= d <= date(2026, 10, 31) for d, _r in out), "read_range returns each row with its day")
shifted = Server(W)
shifted_form = shifted.fetch(OH.PAGE).decode()
orig = shifted.rows
shifted.rows = lambda s, e, f: orig(s - timedelta(days=40), e, f)  # a server that ignores the dates and answers from another window
check(says(lambda: OH.read_range(shifted, shifted_form, date(2026, 10, 1), date(2026, 10, 31), [], TODAY), "outside the window"), "a permit dated outside the window fails the run")
for junk in ("", "soon", "13/45/2026", "2999-01-01"):
    jw = [permit(date(2026, 10, 20), "RINW")]
    s2 = Server(jw)
    f2 = s2.fetch(OH.PAGE).decode()
    real = OH.read_export
    OH.read_export = lambda b, j=junk: [dict(r, DT_APP_ISSUED=j) for r in real(b)]
    try:
        check(says(lambda: OH.read_range(s2, f2, date(2026, 10, 1), date(2026, 10, 31), [], TODAY), "issue date"), "an issue date of %r fails the run" % junk)
    finally:
        OH.read_export = real

# the cap: a search that reports 1,000 is not complete
OH_CAP = OH.CAP
OH.CAP = 40
try:
    cw = [permit(date(2026, 1, 1) + timedelta(days=i // 2), "RINW", appno="C%04d" % i) for i in range(150)]
    cs = Server(cw, cap=40)
    cf = cs.fetch(OH.PAGE).decode()
    got = []
    OH.read_range(cs, cf, date(2026, 1, 1), date(2026, 3, 31), got, TODAY)
    check(len(got) == 150 and len({r["APPNO"] for _d, r in got}) == 150, "a capped window is split in two (and again where needed) and every permit is read once: %d windows searched" % sum(1 for x in cs.log if x[0] == "SEARCH"))
    check(all(x[4] < 40 for x in cs.log if x[0] == "EXPORT"), "no export was taken from a capped window")
    dense = Server([permit(date(2026, 1, 1), "RINW", appno="D%04d" % i) for i in range(60)], cap=40)
    check(says(lambda: OH.read_range(dense, dense.fetch(OH.PAGE).decode(), date(2026, 1, 1), date(2026, 3, 31), [], TODAY), "still capped"), "a week that is still capped fails the run (it would count short)")
    exact = Server([permit(date(2026, 1, 1) + timedelta(days=i), "RINW", appno="E%04d" % i) for i in range(40)], cap=40)
    got = []
    OH.read_range(exact, exact.fetch(OH.PAGE).decode(), date(2026, 1, 1), date(2026, 2, 28), got, TODAY)
    check(len(got) == 40 and len(exact.log) > 4 and all(x[4] < 40 for x in exact.log if x[0] == "EXPORT"), "a window that reports exactly the cap counts as capped, not as complete (40 permits, cap 40: split, then all 40 read)")
finally:
    OH.CAP = OH_CAP
check(OH.plan(date(2025, 9, 1), date(2026, 11, 1)) == [(date(2025, 9, 1), date(2026, 11, 1))] and OH.plan(date(2019, 1, 1), date(2026, 11, 1))[0] == (date(2019, 1, 1), date(2019, 12, 31))
      and OH.plan(date(2019, 1, 1), date(2026, 11, 1))[-1] == (date(2026, 1, 1), date(2026, 11, 1)) and len(OH.plan(date(2019, 1, 1), date(2026, 11, 1))) == 8, "a weekly run reads one window of 15 months; a first run reads a calendar year at a time (8 windows)")


# ------------------------------------------------------------------------------------------------ the build
def expected(permits, first, last, today=TODAY):
    """The counts the build must give, worked out here from the permits: Permit-list only, each application once, the bands from EXPECT and the well-type rule."""
    n = {b: {} for b in C.BANDS}
    for x in permits:
        if x["code"] in OH.PLUG_TYPES or not first <= x["day"] <= last:
            continue
        band = EXPECT[x["code"]]
        if band == "new" and x["wl"] in ("GS_R", "ST_R", "SW_R", "SWD", "ER_R"):
            band = "inj"
        if band == "new" and x["wl"] in ("SM_R", "MN_R"):
            band = "other"
        ym = C.month_of(x["day"])
        n[band][ym] = n[band].get(ym, 0) + 1
    return n


def build_with(server, old=None, today=TODAY):
    return lambda: OH.build(client=server, old={} if old is None else old, today=today)


srv = Server(W)
doc = OH.build(client=srv, old={}, today=TODAY)
check(C.validate(doc, TODAY) == [], "a full read gives a file that passes the shared validator: %s" % C.validate(doc, TODAY)[:2])
exp = expected(W, date(2019, 1, 1), date(2026, 10, 28))
months = doc["months"]
check(months[0] == "2019-01" and months[-1] == "2026-09" and doc["through"] == "2026-09-30" and doc["asOf"] == max(x["day"] for x in W if x["code"] not in OH.PLUG_TYPES).isoformat() and doc["measure"] == "permits" and doc["state"] == "OH", "months run 2019-01 to the last complete month (2026-09), asOf the newest permit")
check(all(doc["bands"][b] == [exp[b].get(ym, 0) for ym in months] for b in C.BANDS), "every band, every month equals the count worked out from the permits (the repeats once, the plug permits out, the well types applied)")
check(all(doc["bands"][b] is not None for b in C.BANDS) and doc["fluid"] is None, "every band is told and the fluid is not available (null)")
reads = [x for x in srv.log if x[0] in ("SEARCH", "EXPORT")]
check([x[0] for x in srv.log].count("GET") == 1 and len(reads) == 16 and [x[0] for x in reads] == ["SEARCH", "EXPORT"] * 8 and reads[0][1] == date(2019, 1, 1) and reads[-1][2] == TODAY,
      "a first read is one GET and a search and an export for each of 8 year-long windows: 17 requests")
check(doc["read"] == sum(1 for x in W if x["code"] not in OH.PLUG_TYPES), "`read` counts the distinct permits, not the rows with their repeats")
last12 = months[-12:]
n12 = sum(doc["bands"]["new"][-12:])
check(n12 == sum(exp["new"].get(ym, 0) for ym in last12) and n12 > 0, "the last 12 months' new wells: %d" % n12)
names = [o for o, _n in doc["operators"]]
check("ACME TEST OPERATING LLC" in names and "BETA ENERGY CORP" in names and "GAMMA PARTNERS LP" in names and not any("EXAMPLE" in o or "DBA" in o for o in names), "corporations, LLCs and partnerships are named; a person trading as a dba and a person's own name are not")
check(0 < doc["namedShare"] < 1 and all(C.nameable(o) for o in names), "the named share is below 1 because some operators may not be named")
check(doc["counties"] and doc["counties"][0][0] in ("Guernsey", "Harrison", "Monroe", "Belmont", "Carroll", "Jefferson", "Noble") and all(c[0] != "Stark" for c in doc["counties"]), "counties come from the Permit list's county column (the plug permits' county is not in)")
text = json.dumps(doc)
check(not any(s in text for s in NEVER) and "PR20" not in text and "PL20" not in text, "no address, phone, contact, well name, API number or application number reaches the file")
check(all(x not in doc["note"] for x in ("null", "undefined", "NaN")) and len(doc["note"]) > 200 and doc["source"]["url"] == OH.PAGE and doc["agency"].startswith("Ohio Department of Natural Resources"), "the note says what is counted, and the source is the page")

# a weekly run with the committed file reads one window
old = {b: dict(zip(doc["months"], doc["bands"][b])) for b in C.BANDS}
old_stale = {b: {ym: (n + 50 if ym >= "2025-09" else n) for ym, n in old[b].items()} for b in C.BANDS}  # last week's counts in the window were different: they must be replaced
srv2 = Server(W)
doc2 = OH.build(client=srv2, old=old_stale, today=TODAY)
reads2 = [x for x in srv2.log if x[0] in ("SEARCH", "EXPORT")]
check([x[0] for x in srv2.log].count("GET") == 1 and len(reads2) == 2 and reads2[0][1] == date(2025, 9, 1) and reads2[0][2] == TODAY, "a weekly run is one GET and one search and export of the newest 15 months: 3 requests")
check(doc2 == doc, "the older months from the committed file and the window read again give the same file as a full read (and the committed counts inside the window are replaced)")
check(all(doc2["bands"][b][:56] == doc["bands"][b][:56] for b in C.BANDS), "months before the window are the committed ones")
srv3 = Server(W)
holes = {b: {ym: n for ym, n in old[b].items() if ym != "2021-03"} for b in C.BANDS}
OH.build(client=srv3, old=holes, today=TODAY)
check(len([x for x in srv3.log if x[0] == "SEARCH"]) == 8, "a committed file with a month missing before the window is not trusted: the whole history is read")
check(OH.build(client=Server(W), old={b: {ym: n for ym, n in old[b].items() if ym >= "2019-02"} for b in C.BANDS}, today=TODAY) == doc, "a committed file that does not start in 2019-01 is read again from the start")
check(OH.previous("/nonexistent/OH.json") == {} and OH.previous(os.path.join(HERE, "test_d11_oh.py")) == {}, "no committed file, or one that is not JSON, gives nothing to carry")

# what fails the run
check(says(build_with(Server(W + [permit(date(2026, 10, 20), "ZZ9", appno="NEWTYPE1")])), "does not know"), "an application type never seen before fails the build")
check(says(build_with(Server(W + [permit(date(2026, 10, 20), "RINW", wl="XX_R", appno="NEWWT1")])), "well type"), "a well type never seen before on a new-well permit fails the build")
check(says(build_with(Server([x for x in W if x["day"] < date(2026, 8, 1)])), "newest permit was issued"), "a list whose newest permit is older than 45 days fails the build (it stopped being updated)")
check(says(build_with(Server([x for x in W if x["day"] >= date(2026, 9, 1)])), "only"), "far too few permits (fresh ones, but 60 in all) fail the build")
check(OH.build(client=Server(W), old={}, today=TODAY)["state"] == "OH", "(control) the same world builds")
plug_leak = Server(W)
plug_leak.rows = lambda s, e, f: Server.rows(plug_leak, s, e, None)  # a server that ignores the Permit filter
check(says(build_with(plug_leak), "filter was not applied"), "a server that ignores the Permit filter (plug permits come back) fails the build")
check(says(build_with(Server([dict(x, appno="") for x in W])), "application number"), "rows with no application number fail the build (they cannot be counted once)")
nocounty = [dict(x, county="") for x in W]
check(says(build_with(Server(nocounty)), "no county"), "a county column that came back empty for every permit fails the build")
notype = [dict(x, wl="") for x in W]
check(says(build_with(Server(notype)), "no well type"), "a well type column that came back empty for every new-well permit fails the build")
check(says(build_with(Server(W, header=[("OPERATOR" if h == "CONAME" else h) for h in COLUMNS])), "CONAME"), "a renamed operator column fails the build, naming it")
two = [dict(x) for x in W]
for x in two:
    if x["code"] == "RINW" and x["day"] == date(2026, 9, 3):
        x["appno"] = "SAMEAPP"
d_same = OH.build(client=Server(two), old={}, today=TODAY)
check(sum(d_same["bands"]["new"]) <= sum(doc["bands"]["new"]) and d_same["read"] <= doc["read"], "applications with the same number, type, day, county and operator are one")
rep = Server(W)
check(OH.build(client=rep, old={}, today=TODAY)["read"] == doc["read"], "the build is deterministic")

# the refusal and failure exits
class Refusing:
    def fetch(self, *a, **k):
        raise C.Refused("the server redirected all 4 tries to another page")


with tempfile.TemporaryDirectory() as tmp:
    check(C.run_producer("OH", lambda: OH.build(client=Refusing(), old={}, today=TODAY), tmp, argv=[]) == 2 and not os.listdir(tmp), "a refusal exits 2 and writes nothing")
    check(C.run_producer("OH", build_with(Server([x for x in W if x["day"].month == 3])), tmp, argv=[]) == 1 and not os.listdir(tmp), "a failure exits 1 and writes nothing")
    check(C.run_producer("OH", lambda: doc, tmp, argv=[]) == 0 and os.path.exists(os.path.join(tmp, "OH.json")), "run_producer writes nat/OH.json for it")
    p = os.path.join(tmp, "OH.json")
    check(OH.previous(p)["new"] == dict(zip(doc["months"], doc["bands"]["new"])) and C.check_dir(tmp) == [], "the written file reloads as the committed counts and passes --check")
    first_bytes = open(p, "rb").read()
    check(C.run_producer("OH", lambda: OH.build(client=Server(W), old=OH.previous(p), today=TODAY), tmp, argv=[]) == 0 and open(p, "rb").read() == first_bytes, "a second run from the committed file writes the same bytes (unchanged)")

print()
print("FAILED %d: %s" % (len(FAILS), FAILS[:4]) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
