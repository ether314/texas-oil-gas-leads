#!/usr/bin/env python3
"""D11: Colorado's wells spudded (Energy and Carbon Management Commission, ECMC; formerly COGCC), for the National report of the Oil tracker.

Colorado approves about 800 to 1,100 drilling permits (Form 2) a year, but it publishes NO file with the day each was approved. What the free downloads and services give:
  - the Commission's search of approved permits holds only the last 12 months (about 830 permits, each with its approval date and type), behind a web form with no export or history, so it cannot
    make the 24 months the National report needs;
  - the permits shapefile and map layer hold the permits still open (approved and not yet completed), with an expiry date, not the ones already drilled: a count of them by month would fall away
    with age, and a number that is short for old months reads as a fall;
  - the Operator Annual Activity Report gives a calendar year's permits approved by operator, with no month.
What is published for every well since 1999 is its spud date, in the layer behind the Commission's map ("Wells (API Spots)": one point per well, 124,000 rows, `spud_date` described as the "best
spud date available": the operator's notice of spud until the completion report replaces it with the actual date), so this counts WELLS SPUD: `measure` is "spuds", `basis` "spud date" (like
Arizona's, New Mexico's and the offshore's). The layer is read whole for 2019 onward (about 6,500 rows, 1 MB, four requests of 2,000 and one count). What it can and cannot tell:

  - `new`: a well whose class is oil (OW), gas (GW), coal bed methane (CBM), dry hole (DA: a new well found dry), a "permitted well location" (LO) or no class yet. COGIS sets the class when
    the completion is reported, so 7 wells in 10 spud in the last year have none yet: their fluid reads unknown, never oil by default;
  - `inj`: a disposal (DSPW, the two EPA classes), enhanced-recovery injection (ERIW) or gas-storage (STOW) well; `other`: helium, CO2, domestic, observation, stratigraphic and geologic-science wells,
    and a class the table here does not know (a run fails when more than a few rows have one);
  - the re-entry, rework and amendment bands are null: a well has one spud date and the layer has no type of work;
  - a well counts once, on its first spud date (three wells in the layer have two rows: a sidetrack spud again, one spud entered twice); a spud dated after today (two typing errors, in
    December 2026) is set aside;
  - the last month is left off (30 days): the Commission's own annual well-starts table stops a month short, and a spud entered late would move a month already shown;
  - the operator is the well's operator today (a transfer renames the wells already drilled); the day is the calendar day of the stamp (about 260 of 6,478 stamps carry a time of day, read as that same day).

It is checked against the Commission's own "Annual Well Starts by County" table (one more request, read in the same run): the last three full years must agree within 10 percent (the layer is
2 percent under the table in 2023, 1 under in 2024 and level in 2025). A table that cannot be read skips the check and says so in the log.

Nothing but five fields is asked for (no API number, well or lease name, coordinate, field or location column leaves the server); a well's internal facility number is used only to see a second
row of the same well, never kept. An operator is named only if it is a corporation, LLC or partnership (the naming rule). A layer that changed (an error reply, a missing field, too few rows,
a year with too few wells, unreadable dates, too many classes unknown, a newest spud older than a month, a total far from the Commission's table) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_co.py [--check]
"""
import collections
import html
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "CO"
LAYER = "https://gisdnr.state.co.us/arcgis/rest/services/ECMC_Public/Wells_Public_ECMC/MapServer/0"
STARTS = "https://ecmc.state.co.us/cogisdb/ReportTools/PermitActivity/annualWellStarts"  # the Commission's own yearly count of well starts, by county
FIELDS = ("OBJECTID", "facility_id", "spud_date", "County", "well_class", "Operator")  # OBJECTID only pages through the rows and facility_id only matches a second row of one well: neither is kept
SINCE = date(2019, 1, 1)
PAGE = 2000  # the layer's maxRecordCount
MAX_PAGES = 15  # about 6,500 rows when written
PAUSE = 3.0
LAG = 30  # a month is shown 30 days after it ends
MIN_ROWS = 4000  # 6,478 on 2026-11-01
MIN_YEAR = 300  # every full calendar year since 2019 holds at least this many wells (2021, the lowest, 638)
MIN_NEW12 = 100  # new wells in the last 12 complete months (665 when read)
STALE_DAYS = 30  # the newest spud is no older than this
MAX_BAD = 0.01  # rows whose date does not read (or is after today), more than this share fail the run
MAX_UNKNOWN = 0.03  # rows of a class in no table
MAX_OTHER = 0.10  # the share of other wells (0.4% now): a rise means the class codes changed
COUNT_SLACK = 0.01  # the layer is live: rows read may differ from the count a moment earlier by this share (and 5 rows)
CHECK_YEARS = 3  # full years held against the Commission's table
CHECK_TOLERANCE = 0.10

NEW = {"OW": "oil", "GW": "gas", "CBM": "gas", "DA": None, "LO": None, "": None}  # class -> fluid; None reads unknown (a dry hole, a location not yet classed, no class yet)
INJ = {"DSPW", "CLASS I EPA", "CLASS II EPA", "ERIW", "STOW"}  # Class II disposal, the two EPA disposal classes, enhanced-recovery injection, gas storage
OTHER = {"HE", "CO2", "DM", "OBW", "STRT", "GEO-SCI", "OTH"}  # helium, CO2, domestic, observation, stratigraphic, geologic science, other


def url_for(last_id=0, count=False):
    q = {"where": "spud_date >= DATE '%s'" % SINCE.isoformat() + ("" if count else " AND OBJECTID > %d" % last_id), "f": "json"}
    if count:
        q["returnCountOnly"] = "true"
    else:
        q.update({"outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID", "resultRecordCount": str(PAGE)})
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def _json(get, url):
    d = json.loads(get(url, max_bytes=20_000_000).decode("utf-8-sig"))
    if not isinstance(d, dict):
        raise RuntimeError("the layer's reply is not an object")
    if "error" in d:
        e = d["error"] if isinstance(d["error"], dict) else {}
        raise RuntimeError("the layer answered with an error (code %s)" % str(e.get("code", "?"))[:10])
    return d


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer with a spud date since 2019, page by page (by OBJECTID, so a well added between two requests cannot shift a page). The layer's own count is read
    first; the rows read must match it to within a percent (it is live). An error reply, a reply with no rows list or lacking a field asked for, too few rows, too many pages or a count
    that does not match fails the run."""
    total = _json(get, url_for(count=True)).get("count")
    if not isinstance(total, int) or total < MIN_ROWS:
        raise RuntimeError("the layer counts %r wells with a spud date since %d (expected %d or more)" % (total, SINCE.year, MIN_ROWS))
    rows, last = [], 0
    for page in range(MAX_PAGES):
        time.sleep(pause)
        d = _json(get, url_for(last))
        names = {f.get("name") for f in d.get("fields") or [] if isinstance(f, dict)}
        missing = [f for f in FIELDS if f not in names]
        feats = d.get("features")
        if missing or not isinstance(feats, list):
            raise RuntimeError("the layer no longer has the fields %s: its layout changed" % ", ".join(missing or ["features"]))
        got = [f["attributes"] for f in feats if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]
        rows += got
        if not d.get("exceededTransferLimit"):
            break
        ids = [r.get("OBJECTID") for r in got if isinstance(r.get("OBJECTID"), int) and not isinstance(r.get("OBJECTID"), bool)]
        if not ids or max(ids) <= last:
            raise RuntimeError("the layer has more rows but its paging does not advance")
        last = max(ids)
    else:
        raise RuntimeError("the layer kept answering with more pages than expected")
    if abs(len(rows) - total) > max(5, COUNT_SLACK * total):
        raise RuntimeError("the layer counted %d wells but %d were read: it changed while it was read" % (total, len(rows)))
    return rows


def class_of(code):
    """(band, fluid, known) for a well class code; `known` is False for a code in none of the tables (filed as other)."""
    c = (code or "").strip().upper()
    if c in NEW:
        return "new", NEW[c], True
    if c in INJ:
        return "inj", None, True
    if c in OTHER:
        return "other", None, True
    return "other", None, False


def parse(rows, today=None):
    """Wells as dicts {day, band, county, operator, fluid}, oldest first. A well counts once, on its first spud date (a row repeating a facility number is the same well). A date that does not
    read, or lies after today, is set aside; a row with no county or no operator is kept (it has no place or no name). More than 1% of the rows with a bad date, or 3% with a class in no table,
    fails the run (the layer changed); fewer are set aside."""
    today = today or date.today()
    first, seen_no_id, bad, unknown = {}, [], 0, 0
    for r in rows:
        day = C.parse_day(r.get("spud_date"), today)
        if day is None or day < SINCE:
            bad += 1
            continue
        band, fluid, known = class_of(r.get("well_class"))
        unknown += not known
        w = {"day": day, "band": band, "county": (r.get("County") or "").strip(), "operator": (r.get("Operator") or "").strip() or None, "fluid": fluid}
        fid = r.get("facility_id")
        if isinstance(fid, int) and not isinstance(fid, bool):
            if fid not in first or day < first[fid]["day"]:
                first[fid] = w
        else:
            seen_no_id.append(w)  # no facility number to match on: counted as it stands
    n = max(1, len(rows))
    if bad > MAX_BAD * n:
        raise RuntimeError("%d of %d rows have a spud date that cannot be read or lies after today" % (bad, len(rows)))
    if unknown > MAX_UNKNOWN * n:
        raise RuntimeError("%d of %d rows have a well class the table here does not explain: the codes may have changed" % (unknown, len(rows)))
    out = list(first.values()) + seen_no_id
    out.sort(key=lambda p: p["day"])
    return out


def starts_table(page):
    """{year: total} from the Commission's 'Annual Well Starts by County' page (the TOTAL row under the County header's years); {} when the page does not have that shape."""
    text = page.decode("utf-8", "replace") if isinstance(page, (bytes, bytearray)) else page
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        rows.append([html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)])
    head = next((r for r in rows if r and r[0].lower() == "county"), None)
    total = next((r for r in rows if r and r[0].upper() == "TOTAL"), None)
    if not head or not total or len(head) != len(total) or len(head) < 6:  # the real table has 24 years; one of fewer than five is not that table
        return {}
    out = {}
    for y, v in zip(head[1:], total[1:]):
        if re.fullmatch(r"20\d\d", y) and re.fullmatch(r"\d{1,6}", v):
            out[int(y)] = int(v)
    return out


def reconcile(permits, table, today=None):
    """Holds the last CHECK_YEARS full calendar years against the Commission's table. Returns the lines to log; raises when a year is more than 10 percent away. A year the table does not have is not held."""
    today = today or date.today()
    mine = collections.Counter(p["day"].year for p in permits)
    lines = []
    for y in range(today.year - CHECK_YEARS, today.year):
        if y not in table or table[y] <= 0:
            continue
        diff = (mine[y] - table[y]) / table[y]
        lines.append("%d: %d wells here, %d in the Commission's table (%+.1f%%)" % (y, mine[y], table[y], 100 * diff))
        if abs(diff) > CHECK_TOLERANCE:
            raise RuntimeError("%d: %d wells counted against %d in the Commission's own well-starts table (%+.0f%%): the layer or the table changed" % (y, mine[y], table[y], 100 * diff))
    return lines


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    permits = parse(rows, today)
    if not permits:
        raise RuntimeError("no well with a spud date could be read")
    newest = permits[-1]["day"]
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest spud is %s: the layer looks stale" % newest)
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=True)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    for y in range(SINCE.year, today.year):
        n = sum(t.m[b].get("%04d-%02d" % (y, mo), 0) for b in t.bands for mo in range(1, 13))
        if n < MIN_YEAR:
            raise RuntimeError("only %d wells spud in %d (expected %d or more): history may be missing" % (n, y, MIN_YEAR))
    other = sum(t.m["other"].values())
    if other > MAX_OTHER * t.read:
        raise RuntimeError("%d of %d wells are 'other': the well class codes may have changed" % (other, t.read))
    try:
        time.sleep(pause)
        table = starts_table(get(STARTS, max_bytes=5_000_000))
    except C.Refused as e:
        C.log("CO: the Commission's well-starts table was not read (%s): the yearly check is skipped" % e)
        table = {}
    except (RuntimeError, ValueError, OSError) as e:
        C.log("CO: the Commission's well-starts table was not read (%s): the yearly check is skipped" % C.privacy_check.clean_error(e, 80))
        table = {}
    if table:
        for line in reconcile(permits, table, today):
            C.log("CO: " + line)
    else:
        C.log("CO: no yearly table to check against")
    doc = t.document(agency="Colorado Energy and Carbon Management Commission (ECMC)", source_name="ECMC Wells (API Spots) map service, spud date",
                     source_url=LAYER, basis="spud date (the best spud date COGIS holds: the operator's notice of spud, then the date on the completion report)",
                     cadence="daily (the layer is rebuilt every day)", measure="spuds", lag_days=LAG, asof=newest,
                     note="Wells spudded, by the spud date COGIS holds for each well (the operator's notice of spud, replaced by the actual date once the completion report is filed). Colorado approves "
                          "roughly 800 to 1,100 drilling permits a year but publishes no file of the day each was approved: its search of approved permits holds only the last 12 months, so wells spudded "
                          "is the series that can be told back to 2019, and it is not a count of permits. A well counts once, on its first spud date; the last month is left off. New wells are oil, gas, "
                          "coal bed methane and dry-hole wells and wells not yet given a class; COGIS sets the class when the completion is reported, so most of the last year's wells read as fluid "
                          "unknown, not as oil. Injection is disposal, enhanced-recovery and gas-storage wells; other wells are helium, CO2, domestic, observation and stratigraphic wells. Re-entries, "
                          "recompletions and amendments are not told. The operator is the one on record today. Checked against the Commission's own well-starts table for 2023 to 2025.")
    if sum(doc["bands"]["new"][-12:]) < MIN_NEW12:
        raise RuntimeError("only %d new wells in the last 12 months (expected %d or more)" % (sum(doc["bands"]["new"][-12:]), MIN_NEW12))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
