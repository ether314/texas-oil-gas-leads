#!/usr/bin/env python3
"""D11: North Dakota's wells by spud date (Industrial Commission, Oil and Gas Division), for the National report of the Oil tracker.

The Division publishes its permit APPROVALS only as one text PDF per business day (the Daily Activity Report) and, in aggregate, as a yearly statistics PDF; the one free bulk source that
can be read as data is its Wells layer (ArcGIS FeatureServer "Wells", layer 0: one point per well file, 44,000 wells), which carries a spud date, the well type, the county and the operator but no
approval date and no type of work. So this counts WELLS SPUD: `measure` is "spuds", `basis` "spud date", and the last two months are left off because spud dates arrive late (NOTES_D11.md).
What the layer can and cannot tell:

  - `new`: a well whose type is OG (the Division's "oil and gas": the Division does not separate oil from gas, so `fluid` is null) or CBM, plus a well whose type the Division still holds
    confidential (its type reads "Confidential": 6% of the wells since 2019 but about a third of the newest year's, all of them in the Bakken counties and from Bakken operators in the rows read;
    a disposal well could be among them, which would make `new` a little high and `inj` a little low: the note says what share they are);
  - `inj`: a disposal, injection, storage or water-supply well (SWD, WI, GI, AGD, AI, GASD, GS, CO2I, CO2S, WS, INJP);
  - `other`: a stratigraphic test (ST) or a type this file does not know (counted, and the run fails when they are many);
  - the re-entry, rework and amendment bands are null: a layer row holds one spud date per well file, and no type of work.

The layer's dates are midnight UTC (older rows) or local midnight (05:00 or 06:00 UTC), so the UTC date is the day either way; a stamp from the afternoon, a missing one, or one after today is not a spud.
Nothing but the four fields above is asked for: no well name, API number, file number, location or elevation leaves the server. An operator is named only if it is a corporation, LLC or
partnership. A layer that changed (an error reply, a missing field, too few rows, many unreadable dates or unknown types, a newest spud older than 45 days) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_nd.py [--check]
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "ND"
LAYER = "https://gis.dmr.nd.gov/dmrpublicservices/rest/services/Wells/FeatureServer/0"
FIELDS = ("spud_date", "well_type", "County", "operator")
SINCE = "2019-01-01"
FIRST = date(2019, 1, 1)
PAGE = 2000  # the layer's own limit
MAX_PAGES = 8  # 6,600 rows since 2019 today: four pages
PAUSE = 3.0
LAG = 60  # spud dates arrive late: a month is shown 60 days after it ends
MIN_ROWS = 3000  # the layer gave 6,625 wells spud since 2019
MIN_YEAR_NEW = 200  # the last 12 months showed about 700
STALE_DAYS = 45
NEW_TYPES = frozenset({"OG", "CBM", "CONFIDENTIAL"})  # the Division's oil and gas well type; a well still confidential shows no type
SERVICE_TYPES = frozenset({"SWD", "WI", "GI", "AGD", "AI", "GASD", "GS", "CO2I", "CO2S", "WS", "INJP"})  # disposal, injection, storage and water-supply wells
OTHER_TYPES = frozenset({"ST"})  # stratigraphic tests; any other code is unknown and also filed under other


def url_for(offset, since=SINCE):
    q = {"where": "spud_date >= DATE '%s'" % since, "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID",
         "resultOffset": str(offset), "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer with a spud date since SINCE, page by page. A reply that is an error, has no rows list or lacks one of the fields asked for fails the run."""
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


def spud_day(stamp):
    """The calendar day of an ArcGIS date stamp (milliseconds since 1970): the UTC date of a stamp before noon UTC (midnight UTC, or local midnight at 05:00 or 06:00); None for
    anything else, a missing stamp included."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    try:
        dt = datetime.fromtimestamp(stamp / 1000.0, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.date() if dt.hour < 12 else None


def band_of_type(well_type):
    """(band, known) from the Division's well type code: 'new' for oil and gas (or a type still confidential), 'inj' for a service well, 'other' for a test or a code not known."""
    t = (well_type or "").strip().upper()
    if t in NEW_TYPES:
        return "new", True
    if t in SERVICE_TYPES:
        return "inj", True
    return "other", t in OTHER_TYPES


def type_of(row):
    """The Division's well type code of a layer row, trimmed and in capitals ('' when missing)."""
    return (row.get("well_type") or "").strip().upper()


def parse(rows, today=None):
    """(wells, counts): wells as dicts {day, band, county, operator, type}, one per spud; counts say what was set aside. A stamp that cannot be read fails the run when more than 2% of the rows
    have one, a code not known when more than 5% have one; a spud dated after today (a typo, a plan) is left out and counted."""
    today = today or date.today()
    out, bad, future, unknown, confidential = [], 0, 0, 0, 0
    for r in rows:
        day = spud_day(r.get("spud_date"))
        if day is None:
            bad += 1
            continue
        if day > today:
            future += 1
            continue
        if day < FIRST:
            continue
        band, known = band_of_type(r.get("well_type"))
        unknown += 0 if known else 1
        confidential += 1 if type_of(r) == "CONFIDENTIAL" else 0
        out.append({"day": day, "band": band, "county": r.get("County"), "operator": (r.get("operator") or "").strip(), "type": type_of(r)})
    n = max(1, len(rows))
    if bad > 0.02 * n:
        raise RuntimeError("%d of %d rows have a spud date that cannot be read" % (bad, len(rows)))
    if unknown > 0.05 * n:
        raise RuntimeError("%d of %d rows have a well type this file does not know: the layer's codes may have changed" % (unknown, len(rows)))
    if future > 0.02 * n:
        raise RuntimeError("%d of %d rows are spud after today" % (future, len(rows)))
    return out, {"bad": bad, "future": future, "unknown": unknown, "confidential": confidential}


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d wells spud since %s (expected %d or more)" % (len(rows), SINCE, MIN_ROWS))
    wells, counts = parse(rows, today)
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=False)
    for w in wells:
        t.add(w["day"], w["band"], county=w["county"], operator=w["operator"])
    if t.newest is None or t.newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest spud is %s: the layer looks stale" % (t.newest,))
    doc = t.document(agency="North Dakota Industrial Commission, Oil and Gas Division", source_name="Oil and Gas Division GIS, Wells layer (spud date)", source_url=LAYER,
                     basis="spud date (the day drilling began)", cadence="as wells are reported (the Division's 2022 notice says hourly; not verified)", measure="spuds", lag_days=LAG, asof=t.newest,
                     note="")
    year = set(doc["months"][-12:])
    shown = [w for w in wells if C.month_of(w["day"]) in year]
    share = round(100.0 * sum(1 for w in shown if w["type"] == "CONFIDENTIAL") / max(1, len(shown)))
    doc["note"] = ("Wells counted by their spud date, not by permit approval: the Division publishes approval dates only in daily PDF reports. New wells are the Division's oil and gas wells "
                   "(it does not separate oil from gas) and the wells it still holds confidential, whose type is not shown (%d%% of the last 12 months' wells; they are in the oil counties and "
                   "are counted as new, so a disposal well among them would make new a little high and injection a little low); injection and disposal wells are their own band; stratigraphic tests are "
                   "'other filings'. Re-entries, reworks and amendments are not told. Spud dates arrive late, so the last two months are left off." % share)
    if sum(doc["bands"]["new"][-12:]) < MIN_YEAR_NEW:
        raise RuntimeError("only %d new wells in the last 12 months (expected %d or more): the layer may be cut short" % (sum(doc["bands"]["new"][-12:]), MIN_YEAR_NEW))
    C.log("%s: %d wells read, %d confidential, %d spud after today left out, %d of unknown type" % (STATE, len(wells), counts["confidential"], counts["future"], counts["unknown"]))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
