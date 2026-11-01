#!/usr/bin/env python3
"""D11: Kansas's drilling permits (Kansas Corporation Commission notices of intent to drill), for the National report of the Oil tracker.

The KCC's own intent search refuses scripts (HTTP 403), but the Kansas Geological Survey (University of Kansas) builds a public well database from the KCC's filings and
publishes it as a free ArcGIS layer ("Oil and Gas Wells", rebuilt every night): one row per well with a PERMIT_DATE, the well type, the county and the operator. This asks the layer
for every row dated 2019 or later (about 9,000 rows, 2.7 MB, five requests of 2,000 and one count), and writes nat/KS.json: permits counted by their permit date. What the layer can
and cannot tell (NOTES_D11.md has the research):

  - the date: rows dated in the last days already read "Approved Intent to Drill", so PERMIT_DATE behaves as the approval date (the KGS does not say so itself);
  - the layer has NO work-type column. Kinds come from the well type (a code: OIL, GAS, O&G, CBM, D&A, EOR, SWD, CATH...) and from the API number's suffix, which the KGS calls a workover code:
      `redrill`  an API number with a suffix above zero in its last two digits (-0001: a well that already exists, re-entered or reworked under a new permit), whatever the well becomes;
      `inj`      a new API number whose type is an injection, disposal, enhanced-recovery or storage well (EOR is the Kansas waterflood injector, 1 in 7 of all permits);
      `new`      a new API number whose type is oil, gas, oil and gas, coal bed methane, dry hole (a new well found dry) or lost hole (including the horizontals, suffix -0100);
      `other`    cathodic-protection boreholes (about 100 a year), water, stratigraphic and observation holes and a type the KGS does not explain (HY): permits, but not oil or gas wells;
    recompletions and amendments are not told by the layer (rework and amend are null);
  - left out: permits whose API number the KCC cancelled and denied injection applications (68 of 8,900 rows since 2019); an expired, unspent permit still counts (it was issued);
  - a well has ONE permit date, so a permit renewed on the same API number replaces the earlier date (the old permit disappears); statuses change over time, so rows are counted by date, never by status;
  - the fluid is the well type the KGS holds today: a new permit shows the type applied for, a hole found dry shows as dry (counted unknown).

An operator is named only if it is a corporation, LLC or partnership (the ORIGINAL operator, which for a permit is the filer; a "dba" is never named). The API number is read only for its
suffix and dropped; no well, lease, API number or person leaves this file (the Tally keeps counts). A layer that changed (a missing field, an error reply, too few rows, rows lost between
pages, an API number or type code that no longer fits, a year with too few permits, a newest permit older than 3 weeks) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_ks.py [--check]
"""
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

STATE = "KS"
LAYER = "https://services2.arcgis.com/ZOdjAzAQ2B0f85zi/ArcGIS/rest/services/Oil_and_Gas_Wells/FeatureServer/0"
FIELDS = ("API_NUMBER", "WELL_TYPE", "WELL_CLASS", "PERMIT_DATE", "COUNTY", "OPERATOR_NAME")  # nothing else is asked for: no well, lease, field, location or contact column
SINCE = date(2019, 1, 1)
PAGE = 2000  # the layer's own limit; a page of fewer rows with more to come is followed by what it gave, not by this
MAX_PAGES = 15
PAUSE = 3.0
MIN_ROWS = 5000  # the layer gave 8,878 rows for 2019 onward (about 1,000 a year in 2023 and 2024, 750 in 2025)
MIN_YEAR = 200  # every full calendar year since 2019 holds at least this many permits (2020, the lowest, had 548)
MIN_NEW12 = 100  # new wells in the last 12 complete months (586 when read)
STALE_DAYS = 21  # the newest permit is no older than this (permits are issued every working day)
MAX_ODD = 0.02  # API numbers of a shape not understood, or dates that do not read, in more than this share of the rows fail the run
MAX_UNKNOWN = 0.03  # well-type codes in no table, in more than this share of the rows
MAX_OTHER = 0.35  # the share of other filings (it is 12% now: a rise means the type codes changed)

VOID_STATUS = ("cancelled api number", "uic application denied")  # a permit that does not stand
NEW_TYPES = {"OIL", "GAS", "O&G", "CBM", "D&A", "LH"}
INJ_TYPES = {"EOR", "SWD", "INJ", "W-INJ", "CO2-INJ", "GSW", "CLASS1", "CLASS ONE (OLD)", "NHDW"}  # enhanced recovery, disposal, injection, storage, class I
NONWELL_TYPES = {"CATH", "WATER", "STRAT", "OBS", "HELIUM", "HY"}  # known, and not oil, gas or injection wells (HY is in no KGS list: 6 rows, 2 a year lately)
API = re.compile(r"\d{2}-\d{3}-\d{5}(?:-(\d{2})(\d{2}))?$")  # 15-077-21980 or 15-077-21980-0001: the last two digits are the workover code, the pair before them the hole's direction


def url_for(offset=0, count=False):
    q = {"where": "PERMIT_DATE >= DATE '%s'" % SINCE.isoformat(), "f": "json"}
    if count:
        q["returnCountOnly"] = "true"
    else:
        q.update({"outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "PERMIT_DATE,OBJECTID", "resultOffset": str(offset), "resultRecordCount": str(PAGE)})
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
    """Every attribute row of the layer dated SINCE or later, page by page. The layer's own count is read first and must equal the rows read (a layer rebuilt between two pages shows
    a row twice and misses another). An error reply, a reply with no rows list or lacking a field asked for, too many pages or a different number of rows fails the run."""
    total = _json(get, url_for(count=True)).get("count")
    if not isinstance(total, int) or total < MIN_ROWS:
        raise RuntimeError("the layer counts %r permits since %s (expected %d or more)" % (total, SINCE.year, MIN_ROWS))
    rows = []
    for page in range(MAX_PAGES):
        time.sleep(pause)
        d = _json(get, url_for(len(rows)))
        names = {f.get("name") for f in d.get("fields") or [] if isinstance(f, dict)}
        missing = [f for f in FIELDS if f not in names]
        feats = d.get("features")
        if missing or not isinstance(feats, list):
            raise RuntimeError("the layer no longer has the fields %s: its layout changed" % ", ".join(missing or ["features"]))
        got = [f["attributes"] for f in feats if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]
        rows += got
        if not d.get("exceededTransferLimit") or not got:
            break
    else:
        raise RuntimeError("the layer kept answering with more pages than expected")
    if len(rows) != total:
        raise RuntimeError("the layer counted %d permits but %d were read: it changed while it was read" % (total, len(rows)))
    return rows


def band_of(wtype, suffix):
    """(band, known) for a well-type code and the workover code at the end of the API number (0 for none). `known` is False for a code in none of the tables (it is filed as other)."""
    t = (wtype or "").strip().upper()
    if t in NONWELL_TYPES:
        return "other", True
    if t not in NEW_TYPES and t not in INJ_TYPES and "INJ" not in t:
        return "other", False
    if suffix > 0:
        return "redrill", True
    return ("inj" if (t in INJ_TYPES or "INJ" in t) else "new"), True


def parse(rows, today=None):
    """Permits as dicts {day, band, county, operator, fluid}, oldest first. A row whose status says the permit does not stand is left out. A row whose date does not read, whose API number
    has no known shape or whose well type is in no table fails the run when more than a few percent of the rows are such."""
    today = today or date.today()
    out, odd, unknown = [], 0, 0
    for r in rows:
        day = C.parse_day(r.get("PERMIT_DATE"), today)
        m = API.match((r.get("API_NUMBER") or "").strip())
        if day is None or day < SINCE or not m:
            odd += 1
            continue
        if (r.get("WELL_CLASS") or "").strip().lower() in VOID_STATUS:
            continue
        band, known = band_of(r.get("WELL_TYPE"), int(m.group(2) or 0))
        unknown += not known
        t = (r.get("WELL_TYPE") or "").strip().upper()
        out.append({"day": day, "band": band, "county": (r.get("COUNTY") or "").strip(), "operator": (r.get("OPERATOR_NAME") or "").strip() or None, "fluid": C.fluid_of(t) if band == "new" else None})
    if odd > MAX_ODD * max(1, len(rows)):
        raise RuntimeError("%d of %d rows have a date or an API number that cannot be read" % (odd, len(rows)))
    if unknown > MAX_UNKNOWN * max(1, len(rows)):
        raise RuntimeError("%d of %d rows have a well-type code the KGS list does not explain: the codes may have changed" % (unknown, len(rows)))
    out.sort(key=lambda p: p["day"])
    return out


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    permits = parse(fetch(get, pause), today)
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "other"), fluid=True)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    if t.newest is None or t.newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest permit is %s: the layer looks stale" % (t.newest,))
    for y in range(SINCE.year, today.year):
        n = sum(t.m[b].get("%04d-%02d" % (y, mo), 0) for b in t.bands for mo in range(1, 13))
        if n < MIN_YEAR:
            raise RuntimeError("only %d permits in %d (expected %d or more): history may be missing" % (n, y, MIN_YEAR))
    other = sum(t.m["other"].values())
    if other > MAX_OTHER * t.read:
        raise RuntimeError("%d of %d permits are 'other filings': the well-type codes may have changed" % (other, t.read))
    doc = t.document(agency="Kansas Corporation Commission, Conservation Division (through the Kansas Geological Survey's well database)", source_name="KGS Oil and Gas Wells layer (permit date)",
                     source_url=LAYER, basis="permit date (approved notice of intent to drill)", cadence="nightly (the KGS rebuilds the layer each night)", measure="permits", asof=t.newest,
                     note="Notices of intent to drill the KCC approved, counted by the permit date in the KGS well layer (rows of the last days already read 'Approved Intent to Drill', so it is the approval "
                          "date; the KGS does not say so). The layer has no work type: kinds come from the well type and the API number's suffix. New wells are oil, gas, coal bed methane, dry-hole and "
                          "lost-hole permits on a new API number (a dry hole is a new well found dry); injection is enhanced-recovery (waterflood), saltwater-disposal and other injection or storage wells; "
                          "re-entries are permits on an existing well's API number (a suffix such as -0001, which the KGS calls a workover code, also when the well is re-entered to inject); other filings are "
                          "cathodic-protection boreholes (about 100 a year), water, stratigraphic and observation holes. Recompletions and amendments are not told. Permits whose API number was "
                          "cancelled are left out. A well keeps one permit date, so a permit renewed on the same API number replaces the earlier date. The fluid is the well type the KGS holds today (a "
                          "hole found dry reads unknown).")
    if sum(doc["bands"]["new"][-12:]) < MIN_NEW12:
        raise RuntimeError("only %d new wells in the last 12 months (expected %d or more)" % (sum(doc["bands"]["new"][-12:]), MIN_NEW12))
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
