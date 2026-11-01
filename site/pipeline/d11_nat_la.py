#!/usr/bin/env python3
"""D11: Louisiana's well permits (Department of Conservation and Energy, Office of Conservation), for the National report of the Oil tracker.

The Office publishes its wells as a free ArcGIS layer in SONRIS GIS (DNRSvc/OC "Oil/Gas Wells", MapServer layer 0: one row per well serial number, 247,000 rows) with a `PERMIT_DATE` (the day the
permit was issued), the parish, the operator and a product code. This asks the layer for every row dated 2019 or later (about 5,000 rows, six requests) and writes nat/LA.json: permits counted by
the day they were issued. Do not confuse it with the "Oil/Gas Wells" layer of the OMR service (Office of Mineral Resources: wells on state leases only, about a quarter of the permits): the serial
numbers prove which is complete (below). What the layer can and cannot tell (NOTES_D11.md):

  - `new`: a permit in the oil and gas series (serial numbers 251,497 in January 2019 to 255,905 in October 2026, consecutive: 4,408 of the 4,409 numbers are in the layer). The layer cannot
    tell a new drill from a re-permit or a redrill (one operation code, "01", on every row), and a permit that later expired unspent stays counted (the layer keeps it);
  - `inj`: an injection or disposal permit: a row with an injection (UIC) well class, or in the Office's own series for them (serial 970,000 to 979,999), or whose status says injection or
    disposal. Most are aquifer-remediation and salt-water wells;
  - `other`: the Office's orphan-well entries (serial 980,000 and up: plugging, not drilling);
  - the re-entry, rework and amendment bands are null: the layer has one row per well and no type of work;
  - `fluid` is the product recorded for the well now (10 oil, 20 gas): a permit not yet drilled, dry or expired has none (not recorded).

Before anything is written the oil and gas serial numbers of the last 24 months must be nearly consecutive: a layer that lost permits (a subset, a cut-short reply) fails the run. Dates are
stamps at local midnight (05:00 or 06:00 UTC), so the UTC date is the day; a row dated after today (one 2031 row exists) is left out and counted. Nothing but seven fields is asked for: no well
name, API number, location or comment. The serial number is read only to sort permits into series and is never kept. An operator is named only if it is a corporation, LLC or partnership.

  python3 -I site/pipeline/d11_nat_la.py [--check]
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "LA"
LAYER = "https://sonris-gis.dnr.la.gov/arcgis/rest/services/DNRSvc/OC/MapServer/0"
FIELDS = ("PERMIT_DATE", "WELL_SERIAL_NUM", "WELL_CLASS_TYPE_CODE", "PRODUCT_TYPE_CODE", "LEGEND_DESC", "PARISH_NAME", "ORG_OPER_NAME")
SINCE = "2019-01-01"
FIRST = date(2019, 1, 1)
PAGE = 1000  # the service's own limit
MAX_PAGES = 15  # 5,000 rows since 2019 today: six pages
PAUSE = 3.0
MIN_ROWS = 2500  # the layer gave 5,045 rows dated 2019 or later
MIN_YEAR_NEW = 150  # a year has about 500 oil and gas permits
STALE_DAYS = 45
UIC_SERIALS = (970000, 980000)  # the Office's series for injection (UIC) wells
ORPHAN_FROM = 980000  # its orphan-well entries
MIN_COVERAGE = 0.8  # of the numbers between the lowest and highest oil and gas serial of the last 24 months, this share must be in the layer (it is 99.9%)
FLUID_OF = {"10": "oil", "20": "gas"}  # PRODUCT_TYPE_CODE; "00" is none specified
NAME_LENGTH = 40  # the operator field's length: a longer name is cut ("... COMPANY, LL")
CUT_LLC = re.compile(r"(\s)(?:LL?|L\.L\.?)$")


def url_for(offset, since=SINCE):
    q = {"where": "PERMIT_DATE >= DATE '%s'" % since, "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "PERMIT_DATE,WELL_SERIAL_NUM",
         "resultOffset": str(offset), "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer dated SINCE or later, page by page. A reply that is an error, has no rows list or lacks one of the fields asked for fails the run."""
    rows = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        d = json.loads(get(url_for(page * PAGE), max_bytes=20_000_000).decode("utf-8-sig"))
        if not isinstance(d, dict):
            raise RuntimeError("the layer's reply is not an object")
        if "error" in d:
            e = d["error"] if isinstance(d["error"], dict) else {}
            raise RuntimeError("the layer answered with an error (code %s)" % str(e.get("code", "?"))[:10])
        names = {f.get("name") for f in d.get("fields") or [] if isinstance(f, dict)}
        missing = [f for f in FIELDS if f not in names]
        if missing or not isinstance(d.get("features"), list):
            raise RuntimeError("the layer no longer has the fields %s: its layout changed" % ", ".join(missing or ["features"]))
        rows += [f["attributes"] for f in d["features"] if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]
        if not d.get("exceededTransferLimit"):
            return rows
    raise RuntimeError("the layer kept answering with more pages than expected")


def permit_day(stamp):
    """The calendar day of an ArcGIS date stamp (milliseconds since 1970): the UTC date of a stamp before noon UTC (local midnight is 05:00 or 06:00 UTC); None for anything else."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    try:
        dt = datetime.fromtimestamp(stamp / 1000.0, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.date() if dt.hour < 12 else None


def serial_of(value):
    """The well serial number as a whole number, None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def operator_name(raw):
    """The operator's name from the layer, trimmed. The field holds 40 characters, so a long name arrives cut; a cut-off LLC ("COMPANY, LL") is completed, any other cut name is left as it is."""
    name = (raw or "").strip()
    return CUT_LLC.sub(lambda m: m.group(1) + "LLC", name) if len(raw or "") >= NAME_LENGTH else name


def band_of_row(row, serial):
    """'other' for an orphan-well entry, 'inj' for an injection or disposal permit (a UIC class, the Office's series for them, or a status that says so), else 'new'."""
    if serial >= ORPHAN_FROM:
        return "other"
    if (row.get("WELL_CLASS_TYPE_CODE") or "").strip() or UIC_SERIALS[0] <= serial < UIC_SERIALS[1] or re.search(r"INJECT|DISPOS", (row.get("LEGEND_DESC") or "").upper()):
        return "inj"
    return "new"


def parse(rows, today=None):
    """(permits, counts): permits as dicts {day, serial, band, county, operator, fluid}, oldest first, a serial number seen twice counted once (a page that overlapped). A date or serial that
    cannot be read fails the run when more than 2% of the rows have one; a row dated after today is left out and counted (more than 2% fail the run)."""
    today = today or date.today()
    out, seen, bad, future, dup = [], set(), 0, 0, 0
    for r in rows:
        day, serial = permit_day(r.get("PERMIT_DATE")), serial_of(r.get("WELL_SERIAL_NUM"))
        if day is None or serial is None:
            bad += 1
            continue
        if day > today:
            future += 1
            continue
        if day < FIRST:
            continue
        if serial in seen:
            dup += 1
            continue
        seen.add(serial)
        out.append({"day": day, "serial": serial, "band": band_of_row(r, serial), "county": r.get("PARISH_NAME"), "operator": operator_name(r.get("ORG_OPER_NAME")),
                    "fluid": FLUID_OF.get((r.get("PRODUCT_TYPE_CODE") or "").strip())})
    n = max(1, len(rows))
    if bad > 0.02 * n:
        raise RuntimeError("%d of %d rows have a permit date or serial number that cannot be read" % (bad, len(rows)))
    if future > 0.02 * n:
        raise RuntimeError("%d of %d rows are dated after today" % (future, len(rows)))
    out.sort(key=lambda p: (p["day"], p["serial"]))
    return out, {"bad": bad, "future": future, "dup": dup}


def coverage(permits, asof):
    """The share of the numbers between the lowest and highest oil and gas serial of the last 24 months that are in the layer (strays more than 5,000 from the median, an old well given
    a new date, are set aside); 0.0 when there are no such permits. The Office numbers permits in order, so a layer with all of them has nearly every number."""
    since = asof - timedelta(days=730)
    nums = sorted(p["serial"] for p in permits if p["band"] == "new" and p["day"] >= since)
    if len(nums) < 20:
        return 0.0
    mid = nums[len(nums) // 2]
    near = [s for s in nums if abs(s - mid) <= 5000]
    return len(near) / float(near[-1] - near[0] + 1)


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d permits since %s (expected %d or more)" % (len(rows), SINCE, MIN_ROWS))
    permits, counts = parse(rows, today)
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=True)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    if t.newest is None or t.newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest permit is %s: the layer looks stale" % (t.newest,))
    cov = coverage(permits, t.newest)
    if cov < MIN_COVERAGE:
        raise RuntimeError("only %.0f%% of the oil and gas serial numbers of the last 24 months are in the layer (expected 80%% or more): permits may be missing, or the numbering changed" % (100 * cov))
    doc = t.document(agency="Louisiana Department of Conservation and Energy, Office of Conservation", source_name="SONRIS GIS, Oil/Gas Wells layer of the Office of Conservation (permit date)",
                     source_url=LAYER, basis="permit date (the day the permit was issued)", cadence="as permits are entered (the Office states no schedule)", measure="permits", asof=t.newest,
                     place="parishes",
                     note="Permits counted by their permit date, one per well serial number. New wells are every permit in the oil and gas series: the layer cannot tell a new drill from a re-permit "
                          "or a redrill, and a permit that later expired unspent stays counted. Injection and disposal permits (mostly aquifer-remediation and salt-water wells, numbered in "
                          "the Office's own series) are their own band; its numbered orphan-well entries are 'other filings'. Re-entries, reworks and amendments are not told. Oil or gas is "
                          "the product recorded for the well now, so a permit not yet drilled, dry or expired shows as not recorded.")
    if sum(doc["bands"]["new"][-12:]) < MIN_YEAR_NEW:
        raise RuntimeError("only %d new permits in the last 12 months (expected %d or more): the layer may be cut short" % (sum(doc["bands"]["new"][-12:]), MIN_YEAR_NEW))
    C.log("%s: %d permits read, serial numbers %.1f%% complete, %d dated after today left out, %d repeated serials" % (STATE, len(permits), 100 * cov, counts["future"], counts["dup"]))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
