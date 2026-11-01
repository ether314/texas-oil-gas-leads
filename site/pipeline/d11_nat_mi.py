#!/usr/bin/env python3
"""D11: Michigan's oil, gas and mineral well permits (EGLE, Oil, Gas, and Minerals Division), for the National report of the Oil tracker.

michigan.gov refuses this kind of caller (HTTP 403 on its pages and forms: not retried, not worked round), but EGLE's open-data map service answers: the "Oil, Gas, and Mineral Well Surface Hole Locations"
layer of the GrmdOpenData MapServer (gisagoegle.state.mi.us, ArcGIS 11.3, no login, 2,000 records a page). One record per well bore, 1927 to today, with `PermitDate`. This asks the service for
the records permitted since January 2019 (about 420, one page; it pages if there are more) and writes nat/MI.json. What the layer does and does not say:

  - `PermitDate` is read as the day the permit was issued. EGLE's own documentation of the layer could not be read, so that reading is not confirmed; the note says so;
  - there is NO work-type field. A sidetrack is told by its sidetrack number (1 to 6 in the data; the code 70 marks the nine Part 625 mineral wells and is not a sidetrack) and counted as `redrill`
    ("re-entries and sidetracks": only sidetracks can be told, a re-entry or a deepening cannot); reworks and amendments are published as not available (null), never zero;
  - the well type is the well's CURRENT type: a permit for a well since drilled is an oil well, a gas well or a dry hole, a permit not yet drilled is a "location". Oil, gas, location and dry hole
    are counted as new wells (the fluid is known only for the oil and gas ones, the rest are `unknown`); brine, disposal, injection, gas-storage and Part 625 mineral wells are `inj`; a lost hole, and
    a record with a completion number, are `other`;
  - a permit that covers two records (the same permit number and day, for a well and its sidetrack, or twice) is counted once, as its lowest sidetrack; terminated permits were issued and are counted;
  - Michigan issues 30 to 70 permits a year, so a month is noisy.

The newest permit's day is `asOf` (the layer carries no update date). Operators come from `CompanyName` and are published only if the shared naming rule says they are a corporation, LLC or partnership;
the well's name, API number and location, and the permit number (used only to count a permit once), are never published.

  python3 -I site/pipeline/d11_nat_mi.py [--check]
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "MI"
LAYER = "https://gisagoegle.state.mi.us/arcgis/rest/services/EGLE/GrmdOpenData/MapServer/10"
PAGE = 2000  # the service's maxRecordCount
MAX_PAGES = 15
PAUSE = 4.0
MAX_BYTES = 25 * 1024 * 1024
# the only columns asked for: no API number, well name, company number or location (the permit number is held in memory to count a permit once)
FIELDS = ("OBJECTID", "PermitNumber", "PermitDate", "well_type", "WellboreType", "Sidetrack", "Completion", "CountyName", "CompanyName")
# what the real layer held on 2026-10-31: 422 records permitted since 2019-01-01 (417 permits), 30 to 70 a year
MIN_RECORDS = 250
MAX_BAD = 3  # records whose date is not a date (or lies in the future), at most this many or 1%
MAX_UNKNOWN_SHARE = 0.10  # of the records, those whose well type code this producer does not know
MAX_PERMIT_AGE = 400  # days: the newest permit is older than this, the layer looks stale
SIDETRACK_MAX = 49  # real sidetrack numbers run 1 to 6; the file marks Part 625 mineral wells with 70

NEW = {"LOC": None, "DH": None, "OIL": "oil", "GAS": "gas"}  # location (permitted, not drilled), dry hole, oil well, gas well -> the fluid they are known to produce
SERVICE = {"BDW", "GIW", "WIW", "COI", "OTI", "GS", "MDW", "MTW"}  # brine disposal, gas injection, water injection, CO2 injection (EOR), other injection, gas storage, Part 625 disposal and test wells
OTHER = {"LHL"}  # lost hole
SERVICE_BORES = {"BRINE", "MINERAL"}  # the layer's own wellbore classes for brine and Part 625 mineral wells


def to_int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def classify(rec):
    """(band, fluid, known) of one record. `known` is False for a well type code this producer does not have (counted under `other`, and watched)."""
    code = str(rec.get("well_type") or "").strip().upper()
    bore = str(rec.get("WellboreType") or "").strip().upper()
    side, comp = to_int(rec.get("Sidetrack")), to_int(rec.get("Completion"))
    if comp > 0 or code in OTHER:
        return "other", None, True  # a lost hole (completion 90) or a further completion of a hole
    if 0 < side <= SIDETRACK_MAX:
        return "redrill", None, True  # a sidetrack bore is its own permit
    if bore in SERVICE_BORES or code in SERVICE:
        return "inj", None, True
    if code in NEW:
        return "new", NEW[code], True
    return "other", None, False


def layer_url(offset, since="2019-01-01"):
    q = {"where": "PermitDate >= DATE '%s'" % since, "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID",
         "resultOffset": str(offset), "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get, pause=PAUSE):
    """Every record permitted since 2019, page by page. An error the service returns inside a 200 reply is a failure (or, for a token or a refusal, a refusal)."""
    out = []
    for page in range(MAX_PAGES):
        if page:
            time.sleep(pause)
        try:
            d = json.loads(get(layer_url(page * PAGE), max_bytes=MAX_BYTES).decode("utf-8-sig"))
        except ValueError:
            raise RuntimeError("the service did not answer with JSON (an error page?)")
        if not isinstance(d, dict):
            raise RuntimeError("the service's answer is not an object")
        err = d.get("error")
        if err:
            code = err.get("code") if isinstance(err, dict) else None
            if code in (401, 403, 498, 499):
                raise C.Refused("the service asked for a login or refused (code %s)" % code)
            raise RuntimeError("the service returned an error (code %s)" % code)
        feats = d.get("features")
        if not isinstance(feats, list):
            raise RuntimeError("the service's answer has no features")
        if page == 0:
            names = {str(f.get("name", "")).lower() for f in (d.get("fields") or []) if isinstance(f, dict)}
            lost = [c for c in FIELDS if c.lower() not in names]
            if lost:
                raise RuntimeError("the layer lost fields: " + ", ".join(lost))
        out += [f["attributes"] for f in feats if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]
        if not d.get("exceededTransferLimit") and len(feats) < PAGE:
            return out
    raise RuntimeError("more than %d pages of permits: the query may have lost its date filter" % MAX_PAGES)


def one_per_permit(recs):
    """The records with a permit counted once: records with the same permit number and day are one permit, kept as the lowest sidetrack and completion; a record with no number is its own."""
    best = {}
    for r in recs:
        num = str(r.get("PermitNumber") or "").strip()
        key = (num, r.get("PermitDate")) if num else ("", r.get("OBJECTID"), id(r))
        rank = (to_int(r.get("Sidetrack")), to_int(r.get("Completion")), to_int(r.get("OBJECTID")))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, r)
    return [v[1] for v in best.values()]


def tally_records(recs, today):
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "other"), fluid=True)
    if len(recs) < MIN_RECORDS:
        raise RuntimeError("only %d permits since 2019 came back (expected about 420)" % len(recs))
    bad = unknown = 0
    newest = None
    for r in one_per_permit(recs):
        day = C.parse_day(r.get("PermitDate"), today)
        if day is None:
            bad += 1
            continue
        if newest is None or day > newest:
            newest = day
        band, fluid, known = classify(r)
        unknown += not known
        t.add(day, band, county=r.get("CountyName"), operator=r.get("CompanyName") or "", fluid=fluid)
    if bad > max(MAX_BAD, 0.01 * len(recs)):
        raise RuntimeError("%d of %d permit dates are not dates: the layer's format may have changed" % (bad, len(recs)))
    if unknown > MAX_UNKNOWN_SHARE * len(recs):
        raise RuntimeError("%d of %d records have a well type this producer does not know" % (unknown, len(recs)))
    if newest is None or (today - newest).days > MAX_PERMIT_AGE:
        raise RuntimeError("the newest permit is %s: the layer looks stale" % (newest.isoformat() if newest else "missing"))
    return t, newest


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    t, newest = tally_records(fetch(get, pause), today)
    return t.document(
        agency="Michigan Department of Environment, Great Lakes, and Energy (EGLE), Oil, Gas, and Minerals Division",
        source_name="Oil, Gas, and Mineral Well Surface Hole Locations (EGLE open data map service, GrmdOpenData layer 10)", source_url=LAYER,
        basis="permit date (the layer's PermitDate, read as the day the permit was issued)", cadence="not stated by EGLE", measure="permits", asof=newest,
        note="Permits by the layer's PermitDate, read as the issue date (EGLE's documentation of the layer could not be read, so that is not confirmed). One record per well bore; a permit on two records "
             "is counted once. The layer has no work type: a sidetrack bore is told by its sidetrack number and counted under Re-entries and sidetracks, but re-entries, deepenings and reworks "
             "cannot be told, and amendments are not records, so they are not available. New wells are locations, oil and gas wells and dry holes (the well's current type): their fluid is "
             "known only for the producers, the rest are unknown. Lost holes are under Other filings; terminated permits are counted. Michigan issues about 30 to 70 permits a year, so a month is noisy.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
