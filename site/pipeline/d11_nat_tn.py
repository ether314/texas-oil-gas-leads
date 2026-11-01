#!/usr/bin/env python3
"""D11: Tennessee's oil and gas well permits (Department of Environment and Conservation, Division of Mineral and Geologic Resources, Oil and Gas Program), for the National report of the Oil tracker.

The Division keeps one table of every oil and gas well permit it has ever issued (16,614 rows when this was written, from 1968), and shows it two ways: the "Oil and Gas Well Permits" report of its
Data Viewer (an Oracle APEX page: a guest session, 50 rows a page) and the "Oil and Gas Wells" map layer behind its Map Viewer (an ArcGIS service, one JSON reply). Both hold the same eleven columns
and, read on 2026-11-01, the same rows (same total, same count for every year from 2019, same newest permit). This reads the layer, which needs no session, in two requests, and writes nat/TN.json:
permits counted by their PERMIT_DATE. What the table can and cannot tell (NOTES_D11.md):

  - one row is one permit to drill, numbered in order (the numbers from 2019 on run without a gap); an amendment, a transfer or a re-entry is not a row of its own, so `new` is every permit in the
    table and no other band is told (null, never zero);
  - the table's date is called "Permit Date" and is the only date in it; permits are valid for a year from issuance (rule 0400-52-02), and that date is read as the day the permit was issued. It is
    stored as a calendar day (midnight UTC), which is checked: a layer that stores anything else fails the run rather than shifting a permit across a month end;
  - "Purpose of Well" is what the well turned out to be, not what was applied for: Dry & Abandoned (about three permits in four), Well Location (permitted, not drilled yet), Abandoned Loc (permitted,
    never drilled), Oil, Oil And Gas, Gas, Shut-in Gas, NCG - Domestic. Every one of those is a permit to drill an oil or gas well and counts as `new`. A permit whose purpose is a service or test well
    (Disposal, Salt Water Disp, UIC, Monitor, Water, Test, Min Core Test: none issued since 2014) is NOT counted as a new well; the note says how many there are, if any. A purpose never seen
    fails the run;
  - the fluid is that purpose: Oil is oil, Oil And Gas both, Gas and Shut-in Gas gas; a dry hole, a location not drilled and a location abandoned say nothing about a fluid (unknown), and so does
    NCG - Domestic (the layer does not say what NCG means). A permit's purpose changes as the well is drilled, so the newest months show more unknown than they will;
  - the Division says its oil and gas data is updated monthly, and it issues 26 to 83 permits a year with gaps of up to three months between them, so the last 60 days before the read are not shown
    (`lag_days`): a month with no permit near the end could be a month the update has not reached. `asOf` is the day of the read.

An operator is named only if it is a corporation, LLC or partnership (the shared rule: some permits are in a person's name, which never leaves this file). Only the permit date, the permit number
(to count a permit once and to check the numbering; never written), the county, the operator and the purpose are requested: no API number, well name, location or elevation is asked for.
The Division's servers answer 403 to the default agent string of this project and 200 to an honest bot-style one, so the two requests send `Mozilla/5.0 (compatible; oil-tracker research)`, which
identifies no person (the one allowance, for this host). A layer that changed (an error, a renamed column, too few rows, a dated row that is not a calendar day, a purpose never seen, holes in the
permit numbers, a newest permit over a year old) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_tn.py [--check]
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

STATE = "TN"
LAYER = "https://tdeconline.tn.gov/arcgis/rest/services/Oil_and_Gas2/MapServer/0"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; oil-tracker research)"}  # the host answers 403 to the default agent; this one identifies no person
FIELDS = ("OBJECTID", "PERMIT_DATE", "PERMIT_NO", "COUNTY", "OPERATOR_NAME", "PURPOSE_OF_WELL")  # OBJECTID only pages through the rows and PERMIT_NO is only counted; neither is written
# about 410 rows. 3,190 of the 16,614 rows have no date; all of them are old permits numbered like 129-36 (a county code and a count: the Division's numbering before the plain numbers), and none of those
# is asked for. A row with no date and a plain number would be a permit of the series without its day, so those (none on 2026-11-01) are asked for, to be told in the note and never counted.
WHERE = "PERMIT_DATE >= timestamp '2019-01-01 00:00:00' OR (PERMIT_DATE IS NULL AND PERMIT_NO NOT LIKE '%-%')"
PAGE = 2000  # the layer's maxRecordCount is 17,000
MAX_PAGES = 6
PAUSE = 3.0
MIN_TOTAL = 15000  # the whole table: 16,614 on 2026-11-01, and it only grows
MIN_ROWS = 150  # permits from 2019 on: 406 on 2026-11-01 (26 to 83 a year)
MAX_UNDATED = 20  # rows with no date and a plain permit number: none on 2026-11-01
STALE_DAYS = 365  # the longest gap between permits since 2019 is 98 days; a newest permit over a year old means the layer is not current
LAG_DAYS = 60  # the Division updates its oil and gas data monthly
BAD_SHARE = 0.02
HOLE_SHARE = 0.05  # permit numbers missing between the first and last of the series: none on 2026-11-01
DAY_MS = 86400000

# the layer's own vocabulary for "Purpose of Well" (the 15 classes of its renderer), in lower case
NEW_PURPOSE = {"", "dry & abandoned", "well location", "abandoned loc", "oil", "oil and gas", "gas", "shut-in gas", "ncg - domestic"}
SERVICE_PURPOSE = {"disposal", "salt water disp", "uic", "monitor", "water", "test", "min core test"}
FLUID = {"oil": "oil", "oil and gas": "both", "gas": "gas", "shut-in gas": "gas"}


# ------------------------------------------------------------------------------------------------ reading the layer

def url_for(last_id):
    q = {"where": "OBJECTID > %d AND (%s)" % (last_id, WHERE), "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID", "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def count_url():
    return LAYER + "/query?" + urllib.parse.urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})


def _object(raw):
    d = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(d, dict):
        raise RuntimeError("the layer's reply is not an object")
    if "error" in d:
        e = d["error"] if isinstance(d["error"], dict) else {}
        raise RuntimeError("the layer answered with an error (code %s)" % str(e.get("code", "?"))[:10])
    return d


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the permit window, page by page (by OBJECTID). A reply that is an error, has no rows list or lacks one of the columns asked for fails the run."""
    rows, last = [], 0
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        d = _object(get(url_for(last), max_bytes=20_000_000, headers=HEADERS))
        names = {f.get("name") for f in d.get("fields") or [] if isinstance(f, dict)}
        missing = [f for f in FIELDS if f not in names]
        if missing or not isinstance(d.get("features"), list):
            raise RuntimeError("the layer no longer has the columns %s: its layout changed" % ", ".join(missing or ["features"]))
        got = [f["attributes"] for f in d["features"] if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]
        rows += got
        if not d.get("exceededTransferLimit"):
            return rows
        ids = [r.get("OBJECTID") for r in got if isinstance(r.get("OBJECTID"), int)]
        if not ids or max(ids) <= last:
            raise RuntimeError("the layer has more rows but its paging does not advance")
        last = max(ids)
    raise RuntimeError("the layer kept answering with more pages than expected")


def fetch_total(get=C.polite_get):
    """How many permits the whole table holds (a count only: no row is asked for)."""
    n = _object(get(count_url(), max_bytes=100_000, headers=HEADERS)).get("count")
    if isinstance(n, bool) or not isinstance(n, int):
        raise RuntimeError("the layer gave no count of its rows")
    return n


# ------------------------------------------------------------------------------------------------ reading a permit

def calendar_day(ms):
    """The day of a PERMIT_DATE (epoch milliseconds that must be exactly midnight UTC: a day, not a moment); None for anything else."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 1e11 < ms < 4e12 or ms % DAY_MS:
        return None
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).date()


def number_of(text):
    t = str(text if text is not None else "").strip()
    return int(t) if re.fullmatch(r"\d{1,9}", t) else None


def purpose_key(text):
    return " ".join(str(text or "").lower().split())


def parse(rows, today=None):
    """(permits, facts) from the layer's rows. `permits` are dicts {day, county, operator, fluid}, oldest first, one per permit number, for the permits to drill an oil or gas well dated 2019 or later.
    `facts` says what was left out or odd: service (service and test wells), undated (rows with no date and a plain number inside the series), holes (numbers missing from the series),
    repeats, dry (permits whose well is recorded as a dry hole). A purpose never seen, a date that is not a day, a permit number that is not a number (more than 2% of the dated rows) or holes in the numbering (more than 5%) fail the run."""
    today = today or date.today()
    seen, out, bad, service, repeats, undated, dry = set(), [], 0, 0, 0, [], 0
    dated = 0
    for r in rows:
        key = purpose_key(r.get("PURPOSE_OF_WELL"))
        if key not in NEW_PURPOSE and key not in SERVICE_PURPOSE:
            raise RuntimeError("a purpose of well never seen (%s): the layer may have changed" % re.sub(r"[^A-Za-z &/\-]", "?", key)[:30])
        number = number_of(r.get("PERMIT_NO"))
        if r.get("PERMIT_DATE") is None:
            undated.append(number)
            continue
        dated += 1
        day = calendar_day(r.get("PERMIT_DATE"))
        if day is None or number is None or day > today or day.year < 2019:
            bad += 1
            continue
        if number in seen:
            repeats += 1
            continue
        seen.add(number)  # every permit of the series, service and test wells too: they hold numbers, so they are not holes
        if key in SERVICE_PURPOSE:
            service += 1
            continue
        dry += key == "dry & abandoned"
        operator = r.get("OPERATOR_NAME")
        out.append({"day": day, "county": r.get("COUNTY"), "operator": str(operator).strip() if operator is not None else "", "fluid": FLUID.get(key)})
    if bad > BAD_SHARE * max(1, dated):
        raise RuntimeError("%d of %d dated rows have a date that is not a calendar day or a permit number that is not a number: the layer may have changed" % (bad, dated))
    if len(undated) > MAX_UNDATED:
        raise RuntimeError("%d rows with a plain permit number have no permit date (expected none)" % len(undated))
    out.sort(key=lambda p: p["day"])
    holes = above = 0
    if seen:
        lo, hi = min(seen), max(seen)
        present = seen | {n for n in undated if n is not None}  # a number with no date is in the table: it is told as undated, not as a hole
        holes = sum(1 for n in range(lo, hi + 1) if n not in present)
        if holes > HOLE_SHARE * (hi - lo + 1):
            raise RuntimeError("%d permit numbers between the first and the last are missing from the layer: it is cut short" % holes)
        above = sum(1 for n in undated if n is not None and n >= lo)  # a row with no date whose number is inside the series could be a permit of it
    return out, {"service": service, "undated": above, "holes": holes, "repeats": repeats, "dry": dry}


def long_day(d):
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    time.sleep(pause)
    total = fetch_total(get)
    if total < MIN_TOTAL:
        raise RuntimeError("the layer holds %d permits in all (expected 16,000 or more)" % total)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d permits from 2019 on (expected about 400)" % len(rows))
    permits, facts = parse(rows, today)
    if len(permits) < MIN_ROWS:
        raise RuntimeError("only %d permits from 2019 on could be read (expected about 400)" % len(permits))
    newest = permits[-1]["day"]
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest permit is dated %s: the layer looks stale" % newest.isoformat())
    t = C.Tally(STATE, bands=("new",), fluid=True)
    for p in permits:
        t.add(p["day"], "new", county=p["county"], operator=p["operator"], fluid=p["fluid"])
    quiet = (today - newest).days
    dry_share = facts["dry"] / len(permits)
    note = ("Permits to drill an oil or gas well, by the permit date in the Division's table of every oil and gas well permit it has issued (its Oil and Gas Data Viewer and Map Viewer show the same table). "
            "The table has no type of permit, so only new wells are told. "
            + ("No permit number appears twice, so it reads as one row per permit to drill and amendments and transfers do not appear as rows. " if not facts["repeats"]
               else "%d permit number%s appear%s twice and %s counted once. " % (facts["repeats"], "" if facts["repeats"] == 1 else "s", "s" if facts["repeats"] == 1 else "", "is" if facts["repeats"] == 1 else "are"))
            + ("Permit numbers run in order without a gap. " if not facts["holes"] else "")
            + "%d percent of the permits since 2019 are for wells recorded as drilled and plugged dry. The fluid is the well's recorded purpose, which changes as it is drilled: a dry hole, a location not yet "
              "drilled and one abandoned have no fluid (unknown), so the newest months show more unknown than they will. Tennessee issues a few dozen permits a year, so a month with none is a real zero. "
              "The Division says it updates this data monthly, so the last 60 days before the read are not shown. The newest permit in the table is dated %s." % (round(dry_share * 100), long_day(newest)))
    if facts["service"]:
        note += " %d permit%s for disposal, monitoring, water or test wells since 2019 %s not counted as new wells." % (facts["service"], "" if facts["service"] == 1 else "s", "is" if facts["service"] == 1 else "are")
    if facts["undated"]:
        note += " %d row%s with no permit date and a number inside the series %s not counted." % (facts["undated"], "" if facts["undated"] == 1 else "s", "is" if facts["undated"] == 1 else "are")
    if facts["holes"]:
        note += " %d permit number%s between the first and the last %s not in the table." % (facts["holes"], "" if facts["holes"] == 1 else "s", "is" if facts["holes"] == 1 else "are")
    if quiet > 100:
        note += " No permit has been recorded for %d days; the longest earlier gap since 2019 is 98 days." % quiet
    return t.document(agency="Tennessee Department of Environment and Conservation, Division of Mineral and Geologic Resources (Oil and Gas Program)",
                      source_name="Oil and Gas Wells map layer (Oil_and_Gas2 MapServer, layer 0), the permit table behind the Oil and Gas Data Viewer",
                      source_url=LAYER, basis="permit date (the date the table records on each permit)", cadence="monthly (the Division's words for its oil and gas data)",
                      measure="permits", lag_days=LAG_DAYS, asof=today, note=note)


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
