#!/usr/bin/env python3
"""D11: Arizona's wells by spud date (Oil and Gas Conservation Commission), for the National report of the Oil tracker.

The Commission publishes no list of permits. What it does publish, free, is the ArcGIS layer behind its map (OIL_AND_GAS_WELLS_AGOL, layer 0: one point per well the state has a record of,
1,288 when written, from the 1920s on): permit number, well type and function, commodity, operator, county, spud date, a status and the date of that status. It has NO approval or filing date
(the dates of the APD and the approval letter sit only in file names on each permit's own web page, behind a Cloudflare check that refused the research machine), so this counts WELLS SPUD:
`measure` is "spuds", `basis` "spud date", and the last two months are left off because spud dates arrive late (NOTES_D11.md). What the layer can and cannot tell:

  - Arizona drills almost nothing. Since 2019 the layer records 26 wells with a Commission permit number and a spud date (1, 13, 1, 5 and 6 a year in 2019 to 2023, every one a helium
    well by its commodity) and none since June 2023: the permits issued since (to 1324, July 2026) are listed as permitted, planned, extended or expired. The months after the newest spud are therefore REAL
    zeros, which is why the document says `zeroOk` (the library refuses a file with no new well in 24 months otherwise). That claim stands on guards: the layer must have been edited within
    450 days (a layer the Commission stopped maintaining fails the run), must still hold the state's whole record (1,000 rows or more), and must still hold the 2019 to 2023 spuds (15 or more);
  - `new`: a well whose type is oil and gas, gas, helium or CO2 exploration or production (helium is most of Arizona's recent drilling, so `fluid` says "other" for it: the page must not read
    them as oil wells); `inj`: a storage, disposal, injection, monitoring or geothermal well; `other`: a stratigraphic test, or a well whose type the layer does not know;
    the re-entry, rework and amendment bands are null (a row has one spud date per well and no type of work);
  - only a well with a Commission permit number (four digits) counts. The layer's 321 older wells carry a county-and-well code ("09-07") and no permit, and their spud dates are keyed with the wrong
    century (a well of the 1920s dated 2025, one dated 2027): they are set aside and counted in the log;
  - `asOf` is the layer's newest edit (its last-edited, created and status dates), not a spud: the layer is edited irregularly and a spud may be entered months late.

Nothing but ten fields is asked for (no well name, API number, lease, mineral owner, driller, coordinate or editor's name leaves the server), and the permit number is used only to see that it has
four digits, never kept. An operator is named only if it is a corporation, LLC or partnership. A layer that changed (an error reply, a missing field, too few rows or spuds, unreadable dates, a layer
that stopped being edited) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_az.py [--check]
"""
import collections
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

STATE = "AZ"
LAYER = "https://utility.arcgis.com/usrsvcs/servers/6c01eae404a44e95a9aad050effe93cd/rest/services/OIL_AND_GAS_WELLS_AGOL/FeatureServer/0"
FIELDS = ("PERMIT_ID", "WELL_TYPE", "WELL_FUNCTION", "COMMODITY", "OPERATOR", "COUNTY", "SPUD_DATE", "STATUS_DATE", "LAST_EDITED_DATE", "CREATED_DATE")
FIRST = date(2019, 1, 1)
PAGE = 2000  # the layer's own limit; the whole layer is 1,288 rows
MAX_PAGES = 5
PAUSE = 3.0
LAG = 60  # spud dates arrive late: a month is shown 60 days after it ends
MIN_ROWS = 1000  # 1,288 when written
MIN_SPUDS = 15  # 26 permitted wells spud since 2019 when written
STALE_DAYS = 450  # the layer was edited every few months in 2025 and 2026
PERMIT_NO = re.compile(r"\d{4}")  # a Commission permit number; the older wells' codes are "09-07"


def url_for(offset):
    q = {"where": "1=1", "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID",
         "resultOffset": str(offset), "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer, page by page. A reply that is not JSON, is an error, has no rows list or lacks one of the fields asked for fails the run."""
    rows = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        try:
            d = json.loads(get(url_for(page * PAGE), max_bytes=20_000_000).decode("utf-8-sig"))
        except ValueError:
            raise RuntimeError("the layer's reply is not JSON")
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


def stamp_day(stamp, anytime=False):
    """The calendar day of an ArcGIS date stamp (milliseconds since 1970). A spud date is a day kept at midnight (UTC, or local midnight at 05:00 to 07:00 UTC), so a stamp from the afternoon
    is not one: None. `anytime` is for an edit's time stamp, which may fall at any hour. None too for a missing or non-numeric stamp."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    try:
        dt = datetime.fromtimestamp(stamp / 1000.0, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.date() if (anytime or dt.hour < 12) else None


def clean(text):
    return " ".join(str(text or "").split())


def band_of_row(r):
    """'new', 'inj' or 'other' from the layer's well type and function (the shared words for a service well: storage, disposal, injection, monitoring, geothermal). A stratigraphic test, and a
    well whose type is blank or 'Unknown', is 'other': it is not claimed as a new well."""
    wt, wf = clean(r.get("WELL_TYPE")), clean(r.get("WELL_FUNCTION"))
    text = (wt + " " + wf).strip()
    if re.search(r"stratigraph|test hole", text, re.I) or wt.lower() in ("", "unknown", "none"):
        return "other"
    return C.band_of("new", text)


def fluid_of_row(r):
    """'oil', 'gas', 'both' or 'other' from the commodity ('Oil, Gas' is both: the Commission does not separate them; helium and CO2 are other); None (unknown) when it says nothing."""
    c = clean(r.get("COMMODITY"))
    f = C.fluid_of(c)
    if f:
        return f
    return "other" if re.search(r"helium|carbon dioxide|co2|geotherm|brine|salt", c, re.I) else None


def parse(rows, today=None):
    """(wells, edited, counts). `wells` are dicts {day, band, fluid, county, operator}, one per spud since 2019 of a well with a Commission permit number; `edited` the layer's newest edit day
    (the newest of the last-edited, created and status dates that are not in the future), None when there is none; `counts` what was set aside. A spud stamp that cannot be read fails the run when
    more than 2% of the rows have one, a spud after today (a typo) when more than 2% do."""
    today = today or date.today()
    out, edited, c = [], None, collections.Counter()
    for r in rows:
        for k in ("LAST_EDITED_DATE", "CREATED_DATE", "STATUS_DATE"):
            d = stamp_day(r.get(k), anytime=True)
            if d and d <= today and (edited is None or d > edited):
                edited = d
        stamp = r.get("SPUD_DATE")
        if stamp is None:
            continue
        day = stamp_day(stamp)
        if day is None:
            c["bad"] += 1
            continue
        if not PERMIT_NO.fullmatch(clean(r.get("PERMIT_ID"))):
            if day >= FIRST:
                c["historic"] += 1  # an older well's code and a spud date in the wrong century
            continue
        if day > today:
            c["future"] += 1
            continue
        if day < FIRST:
            continue
        out.append({"day": day, "band": band_of_row(r), "fluid": fluid_of_row(r), "county": r.get("COUNTY"), "operator": clean(r.get("OPERATOR"))})
    n = max(1, len(rows))
    if c["bad"] > 0.02 * n:
        raise RuntimeError("%d of %d rows have a spud date that cannot be read" % (c["bad"], len(rows)))
    if c["future"] > 0.02 * n:
        raise RuntimeError("%d of %d rows are spud after today" % (c["future"], len(rows)))
    return out, edited, c


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d wells (expected %d or more)" % (len(rows), MIN_ROWS))
    wells, edited, counts = parse(rows, today)
    if edited is None or edited < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the layer's newest edit is %s: it looks stale" % (edited,))
    if len(wells) < MIN_SPUDS:
        raise RuntimeError("only %d wells spud since %d (expected %d or more): the layer may be cut short" % (len(wells), FIRST.year, MIN_SPUDS))
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=True)
    for w in wells:
        t.add(w["day"], w["band"], county=w["county"], operator=w["operator"], fluid=w["fluid"])
    asof = max(edited, t.newest)
    doc = t.document(agency="Arizona Oil and Gas Conservation Commission", source_name="Oil and Gas Wells layer (ArcGIS, the Commission's well map)", source_url=LAYER,
                     basis="spud date (the day drilling began)", cadence="irregular (the Commission edits the layer as it updates its records; it states no schedule)", measure="spuds",
                     lag_days=LAG, asof=asof, note="")
    last = t.newest.strftime("%B %Y")
    doc["note"] = ("Wells counted by their spud date, not by permit: the Commission's layer has no approval or filing date. Arizona drills very few wells, and the recent ones are helium, not oil "
                   "(the fluid split says so). Only wells with a Commission permit number count. The newest spud the layer records is %s; the months since are zeros because none is recorded "
                   "(the permits issued since then are listed as permitted, planned, extended or expired), up to the layer's last edit on %s. Re-entries, reworks and amendments are not told. "
                   "Spud dates arrive late, so the last two months are left off." % (last, asof.strftime("%B %d, %Y").replace(" 0", " ")))
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # the guards above are why a quiet two years may be published (see the module's docstring)
    C.log("%s: %d rows read, %d wells spud since %d counted (newest %s), %d older wells with a spud date in the wrong century and %d spud after today left out"
          % (STATE, len(rows), len(wells), FIRST.year, t.newest.isoformat(), counts["historic"], counts["future"]))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
