#!/usr/bin/env python3
"""D11: Virginia's wells drilled (Virginia Energy, Division of Gas and Oil), for the National report of the Oil tracker.

Virginia drills a few dozen wells a year, almost all coalbed methane in Buchanan and Dickenson counties (a little oil and conventional gas). Virginia Energy publishes NO permit issue date by well in
any open file: the permit reports of its Gas and Oil Data Information System ("DGO Inquiry") are ASP.NET form postbacks, not files, and the status date on its map layers is the date of the well's
latest status, not of its permit. What the public map service (ArcGIS, no login) does give for every well is the date its drilling was completed (`FiDrComp`), so this counts WELLS DRILLED by that
date, and says so: `measure` is `spuds` (the National report's name for counts of drilled wells, never added to permits), `basis` is "date drilling was completed", and the months end 60 days
before the read, because a well's date arrives after the work. Permits issued and not yet drilled, and permits that were never drilled, are not in this count.

Three layers of https://energy.virginia.gov/gis/rest/services/DGO/DGO_wells/MapServer are read, each one request (a page of up to 2,000 wells since 2019, no geometry, five fields):
  0 Active Wells, 5 Plugged Wells (a coalbed well drilled in 2019 and plugged since is still a well drilled in 2019), 6 Waste Disposal Wells (none drilled since 2007 when last read).
The Active Wells layer is the one that grows; a well sits in one layer at a time (the layers share no well in the data read), and a well file number seen twice would count once. The file number is
read only to do that and is never kept, nor is any well name, farm or location. The bands, from the well type Virginia records (`TblOpDesc`):
  new    gas, coalbed, coalbed/pipeline, horizontal, oil and "carbon credit" wells        inj    waste disposal and service wells        other   a "conversion" or anything not named
and the fluid for `new`: coalbed and gas wells are gas, oil is oil, "carbon credit" says nothing (unknown). Operators are named only where they are companies; places are counties.
The layers are live and publish no update time, so `asOf` is the day of the read; each run reads the whole of 2019 on, so a late-reported or corrected date moves a well to its right month.

  python3 -I site/pipeline/d11_nat_va.py [--check]
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "VA"
SERVICE = "https://energy.virginia.gov/gis/rest/services/DGO/DGO_wells/MapServer"
LAYERS = ((0, "Active Wells"), (5, "Plugged Wells"), (6, "Waste Disposal Wells"))
FIELDS = "FiNo,CoName,TblCnName,TblOpDesc,FiDrComp"  # the four read and the file number used only to count a well once
PAGE_ROWS = 2000
MAX_PAGES = 10
PAUSE = 3.0
MIN_ROWS = 150  # wells drilled since 2019 across the layers (483 when written)
MIN_ACTIVE = 100
MAX_AGE_DAYS = 400  # the newest drilling date may not be older than this: a live layer that shows nothing recent is a broken read
LAG_DAYS = 60


def query_url(layer, offset=0):
    q = {"where": "FiDrComp >= DATE '%s-01'" % C.FIRST_MONTH, "outFields": FIELDS, "returnGeometry": "false", "orderByFields": "OBJECTID", "resultRecordCount": PAGE_ROWS, "f": "json"}
    if offset:
        q["resultOffset"] = offset
    return "%s/%d/query?%s" % (SERVICE, layer, urllib.parse.urlencode(q))


def read_layer(layer, get, pause):
    """The attribute dicts of every well of one layer drilled since 2019, paged when the server says there are more. An error answer, a layer with no feature list or too many pages raise."""
    rows, offset = [], 0
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        try:
            d = json.loads(get(query_url(layer, offset), max_bytes=8_000_000).decode("utf-8-sig"))
        except ValueError:
            raise RuntimeError("layer %d did not answer with JSON (an error page?)" % layer)
        if not isinstance(d, dict) or d.get("error") or not isinstance(d.get("features"), list):
            raise RuntimeError("layer %d did not answer with wells (%s)" % (layer, "an error" if isinstance(d, dict) and d.get("error") else "no feature list"))
        rows += [f.get("attributes") or {} for f in d["features"]]
        if not d.get("exceededTransferLimit"):
            return rows
        if not d["features"]:
            raise RuntimeError("layer %d says there is more but sent nothing" % layer)
        offset += len(d["features"])
    raise RuntimeError("layer %d has more than %d pages: the filter may have stopped working" % (layer, MAX_PAGES))


def well_band(opdesc):
    """new, inj or other from the well type Virginia Energy records (Coalbed/Pipeline, Gas, Gas/Pipeline, Oil, Horizontal Gas, Carbon Credit, Conversion, Waste Disposal, Service Well...)."""
    t = (opdesc or "").lower()
    if re.search(r"dispos|inject|service|storage|monitor|observation", t):
        return "inj"
    if "conver" in t:
        return "other"
    if re.search(r"\boil\b|\bgas\b|coal ?bed|methane|carbon credit|horizontal", t):
        return "new"
    return "other"


def wells(layer_rows):
    """[(day, band, county, operator, fluid)] for the wells of the layers in order, a file number seen twice (in two layers) counted once; also the number of rows whose date did not read."""
    seen, out, bad = set(), [], 0
    for rows in layer_rows:
        for a in rows:
            fino = (a.get("FiNo") or "").strip()
            if fino:
                if fino in seen:
                    continue
                seen.add(fino)
            day = C.parse_day(a.get("FiDrComp"))
            if day is None:
                bad += 1
                continue
            opdesc = (a.get("TblOpDesc") or "").strip()
            band = well_band(opdesc)
            out.append((day, band, (a.get("TblCnName") or "").strip() or None, (a.get("CoName") or "").strip() or None, C.fluid_of(opdesc) if band == "new" else None))
    return out, bad


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or datetime.date.today()
    layer_rows = []
    for i, (layer, _name) in enumerate(LAYERS):
        if i:
            time.sleep(pause)
        layer_rows.append(read_layer(layer, get, pause))
    if len(layer_rows[0]) < MIN_ACTIVE:
        raise RuntimeError("the Active Wells layer gave %d wells drilled since %s (expected %d or more)" % (len(layer_rows[0]), C.FIRST_MONTH, MIN_ACTIVE))
    got, bad = wells(layer_rows)
    if len(got) < MIN_ROWS:
        raise RuntimeError("only %d wells drilled since %s were read (expected %d or more)" % (len(got), C.FIRST_MONTH, MIN_ROWS))
    if bad > 0.05 * (len(got) + bad):
        raise RuntimeError("%d of %d drilling dates could not be read: the date format may have changed" % (bad, len(got) + bad))
    newest = max(w[0] for w in got)
    if (today - newest).days > MAX_AGE_DAYS:
        raise RuntimeError("the newest well drilled is dated %s: the layer is not what it was" % newest)
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=True)
    for day, band, county, operator, fluid in got:
        t.add(day, band, county=county, operator=operator, fluid=fluid)
    doc = t.document(agency="Virginia Department of Energy (Virginia Energy), Division of Gas and Oil", source_name="DGO wells map service: Active, Plugged and Waste Disposal Wells (drilling completed date)", source_url=SERVICE,
                     basis="date drilling was completed (wells drilled; Virginia publishes no permit date)", cadence="live map layer (no update time published)", measure="spuds", lag_days=LAG_DAYS, asof=today, unit="wells drilled",
                     note="Virginia Energy publishes no permit issue date by well, so this counts wells drilled, by the date their drilling was completed, never added to permits. Most are coalbed methane "
                          "wells, most of them in Buchanan County. Wells drilled and since plugged are included; permits issued and not yet drilled are not. The newest well drilled in the layers is dated %s; months run to 60 days "
                          "before the read because a well's date arrives after the work. Operators are named only where they are companies." % newest.isoformat())
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # a real zero: the layers were read in full (the floors above) and no well was drilled in two years
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
