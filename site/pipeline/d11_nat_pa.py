#!/usr/bin/env python3
"""D11: Pennsylvania's oil and gas well permits (Department of Environmental Protection, Office of Oil and Gas Management), for the National report of the Oil tracker.

DEP publishes its wells as a free ArcGIS layer (the Oil and Gas Mapping Application, "Oil and Gas Wells All", MapServer layer 3): one row per well with the day DEP issued its
drilling permit (`PERMIT_DATE`), the well type, the status, the county and the operator. This asks for every well permitted since 2019 (about 6,600 rows, 1,000 to a request, 1.3 MB
in all) and writes nat/PA.json: permits counted by the day DEP issued them. What the layer can and cannot tell (NOTES_D11.md):

  - `new`: a permit to drill a well that produces or explores (oil, gas, combined, coalbed methane, dry hole, undetermined). The layer keeps a permit after it is spent: wells whose
    permit expired unused ("Proposed But Never Materialized") or that the operator reported not drilled stay in it (14% of the permits since 2019), and they are counted, because DEP issued
    the permit; a duplicate record and a permit still awaiting its decision are not;
  - `inj`: a permit for a storage, injection, waste-disposal or observation well (DEP's own well types), a handful in six years;
  - re-drills, deepenings, alterations and changes of use are DEP "authorizations" on wells that already have a row, so the layer does not show them (DEP's weekly Workload Report counts
    them, in the hundreds a year, without a month): `redrill`, `rework`, `amend` and `other` are null, never zero;
  - the fluid is the well type (oil, gas, combined oil and gas, coalbed methane counted as gas); an undetermined type or a dry hole is unknown (about three in four of the permits
    are gas wells, most of them Marcellus and Utica shale wells);
  - the layer holds a few percent fewer wells than DEP's own weekly Workload Report counts as permitted (555 against 576 for 1 January to 23 October 2026), for a reason the layer
    does not give; the note says so.

An operator is named only if it is a corporation, LLC or partnership. Only the columns above are requested: no permit or API number, well name, lease, municipality or location is asked
for, so none can reach the file. A layer that changed (a missing column, an error reply, too few rows, dates that do not read, a newest permit more than 10 days old) fails the run and
leaves the committed file alone, as does a history that no longer reaches back to early 2019. Requests identify no person and are 3 seconds apart.

  python3 -I site/pipeline/d11_nat_pa.py [--check]
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

STATE = "PA"
LAYER = "https://gis.dep.pa.gov/depgisprd/rest/services/OilGas/OilGasAllStrayGas/MapServer/3"
FIELDS = ("OBJECTID", "PERMIT_DATE", "WELL_TYPE", "WELL_STATUS", "COUNTY", "OPERATOR")  # OBJECTID only pages through the rows; it is never kept
SINCE = "2019-01-01"
PAGE = 1000  # the layer's maxRecordCount
MAX_PAGES = 25  # the layer gave about 6,600 rows (7 pages)
PAUSE = 3.0
MIN_ROWS = 4000  # 6,568 on 2026-11-01
STALE_DAYS = 10  # DEP issues permits on weekdays: a long weekend is 4 days
NOT_ISSUED = re.compile(r"duplicate|awaiting", re.I)  # a repeated record; a permit whose decision is still pending
BAD_SHARE = 0.02  # more than this share of rows with a date that does not read fails the run


def url_for(last_id, since=SINCE):
    q = {"where": "PERMIT_DATE >= DATE '%s' AND OBJECTID > %d" % (since, last_id), "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID",
         "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer permitted since SINCE, page by page (by OBJECTID, so a row added or removed between requests cannot shift a page). A reply that is an error,
    has no rows list or lacks one of the columns asked for fails the run."""
    rows, last = [], 0
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        d = json.loads(get(url_for(last), max_bytes=20_000_000).decode("utf-8-sig"))
        if not isinstance(d, dict):
            raise RuntimeError("the layer's reply is not an object")
        if "error" in d:
            e = d["error"] if isinstance(d["error"], dict) else {}
            raise RuntimeError("the layer answered with an error (code %s)" % str(e.get("code", "?"))[:10])
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


def permit_day(ms, today):
    """The day of a PERMIT_DATE (an ArcGIS date: milliseconds since 1970 at midnight UTC, which is the permit's own date); None for a placeholder (1901, 1970), junk or a day after `today`."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 1e11 < ms < 4e12:
        return None
    d = datetime.fromtimestamp(ms / 1000.0, timezone.utc).date()
    return d if date(2000, 1, 1) <= d <= today else None


def parse(rows, today=None, since=SINCE):
    """Permits as dicts {day, band, county, operator, fluid}, oldest first. A duplicate record and a permit awaiting its decision are left out. A row with no date is dropped; more
    than 2% of the rows with a date that does not read fails the run (the layer changed)."""
    today = today or date.today()
    first = date.fromisoformat(since)
    out, bad = [], 0
    for r in rows:
        if NOT_ISSUED.search(r.get("WELL_STATUS") or ""):
            continue
        day = permit_day(r.get("PERMIT_DATE"), today)
        if day is None or day < first:
            bad += 1
            continue
        well = (r.get("WELL_TYPE") or "").strip()
        out.append({"day": day, "band": C.band_of("", well), "county": r.get("COUNTY"), "operator": (r.get("OPERATOR") or "").strip() or None, "fluid": C.fluid_of(well)})
    if bad > BAD_SHARE * max(1, len(rows)):
        raise RuntimeError("%d of %d rows have a permit date that does not read: the layer may have changed" % (bad, len(rows)))
    out.sort(key=lambda p: p["day"])
    return out


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d permitted wells since %s (expected 6,000 or more)" % (len(rows), SINCE))
    permits = parse(rows, today)
    if not permits:
        raise RuntimeError("no permit could be read")
    earliest, newest = permits[0]["day"], permits[-1]["day"]
    if earliest > date.fromisoformat(SINCE) + timedelta(days=31):
        raise RuntimeError("the layer's permits begin only on %s (expected January 2019): its history was cut" % earliest)  # the series starts in 2019, so earlier months must not be zeros
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest permit is %s: the layer looks stale" % newest)
    t = C.Tally(STATE, bands=("new", "inj"), fluid=True)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    return t.document(agency="Pennsylvania Department of Environmental Protection, Office of Oil and Gas Management", source_name="DEP Oil and Gas Mapping Application, Oil and Gas Wells All layer (permit date)",
                      source_url=LAYER, basis="permit date (the day DEP issued the well's drilling permit)", cadence="daily (the layer is current to a day or two)", measure="permits", asof=newest,
                      note="Permits to drill a well, by the day DEP issued them (the layer has one row per well). Permits that expired unused or whose well the operator reported not drilled "
                           "stay in the count: DEP issued them. Most are gas wells, many of them shale wells. Storage, injection, disposal and observation wells are their own band, a handful in "
                           "six years. Re-drills, deepenings, alterations and changes of use are authorizations on existing wells that the layer does not show, so those bands are not told. "
                           "The layer holds a few percent fewer wells than DEP's weekly Workload Report counts as permitted (555 against 576 for January 1 to October 23, 2026). "
                           "The fluid is DEP's well type; an undetermined type or a dry hole is unknown.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
