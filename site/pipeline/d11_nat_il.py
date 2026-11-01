#!/usr/bin/env python3
"""D11: Illinois's well permits (Department of Natural Resources, Office of Oil and Gas Resource Management; the data sit with the Illinois State Geological Survey), for the National report of the Oil tracker.

Read: the ISGS "ILOIL Wells" map service, layer 8 (https://maps.isgs.illinois.edu/arcgis/rest/services/ILOIL/Wells/MapServer/8), an ArcGIS layer with one row per well that the survey
refreshes weekly. Four columns are asked for, no geometry: the row id (to drop a page's repeats), API_NUMBER (only its county digits are used, then it is forgotten), PERMIT_DATE and
COMPANY_NAME. The query is paged (1,000 rows a page; about 2 requests for the 1,800 permits since 2019). NOTES_D11.md has the research.

What a count is, and is not (checked against the agency's own weekly permit log: 52 permits of six weekly PDFs from June to August 2026 were matched by permit number):
  - one count is a well that received a permit to drill, on the day the permit was issued (`measure` permits, `basis` permit date). The layer has one date per well, so a permit to convert, deepen or
    renew an existing well adds no row: of 14 water-injection permits in those logs only 4 were in the layer, while every oil, gas, coal-mine-methane and disposal permit was;
  - the kind of well is NOT told. The layer's status is the well's status today, and a permit that has not been drilled yet (three in four of the last year's) has none, so a split into new,
    injection and other would shrink with the age of the permit. Every row is counted under `new` and the unit says "wells permitted" (oil, gas, coal-mine methane and injection wells together);
    the other bands and the fluid are published as null;
  - the layer is about two months behind the agency's weekly log (its newest permit was issued Aug 28 when this was written; the log was at Oct 19), so the series ends two or three months
    before the other states'. A permit issued in a month the layer has not reached is not a zero: the series simply ends before it;
  - the county is the API number's county code (digits 3 to 5), which for Illinois is the county's FIPS code; it matched the weekly log's county for all 42 permits compared (14 counties).

The operator is the layer's company name, named only if it is a corporation, LLC or partnership (the shared rule); a person's name never leaves this file. No API number, farm or well name,
permit number, address or coordinate is read into the output.

  python3 -I site/pipeline/d11_nat_il.py [--check]
"""
import os
import re
import sys
import urllib.parse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "IL"
LAYER = "https://maps.isgs.illinois.edu/arcgis/rest/services/ILOIL/Wells/MapServer/8"
QUERY = LAYER + "/query"
FIELDS = ("OBJECTID", "API_NUMBER", "PERMIT_DATE", "COMPANY_NAME")  # nothing else is asked for
PAGE = 1000  # the service allows 2,000
MAX_PAGES = 25  # about 13 times what is there; more means something is wrong
MIN_ROWS = 1200  # 1,821 permits dated 2019 and later when written; a layer that shrinks below this is not the layer
MAX_STALE_DAYS = 150  # the layer ran about 65 days behind when written; past this it has stopped being refreshed
MAX_BAD = 0.02  # most rows that may fail to give a date, a county code we know or a plausible shape

# Illinois's counties by the county code in digits 3 to 5 of the API number (the FIPS code: odd numbers 001 to 203)
COUNTIES = {
    "001": "Adams", "003": "Alexander", "005": "Bond", "007": "Boone", "009": "Brown", "011": "Bureau", "013": "Calhoun", "015": "Carroll", "017": "Cass",
    "019": "Champaign", "021": "Christian", "023": "Clark", "025": "Clay", "027": "Clinton", "029": "Coles", "031": "Cook", "033": "Crawford", "035": "Cumberland",
    "037": "DeKalb", "039": "De Witt", "041": "Douglas", "043": "DuPage", "045": "Edgar", "047": "Edwards", "049": "Effingham", "051": "Fayette", "053": "Ford",
    "055": "Franklin", "057": "Fulton", "059": "Gallatin", "061": "Greene", "063": "Grundy", "065": "Hamilton", "067": "Hancock", "069": "Hardin", "071": "Henderson",
    "073": "Henry", "075": "Iroquois", "077": "Jackson", "079": "Jasper", "081": "Jefferson", "083": "Jersey", "085": "Jo Daviess", "087": "Johnson", "089": "Kane",
    "091": "Kankakee", "093": "Kendall", "095": "Knox", "097": "Lake", "099": "LaSalle", "101": "Lawrence", "103": "Lee", "105": "Livingston", "107": "Logan",
    "109": "McDonough", "111": "McHenry", "113": "McLean", "115": "Macon", "117": "Macoupin", "119": "Madison", "121": "Marion", "123": "Marshall", "125": "Mason",
    "127": "Massac", "129": "Menard", "131": "Mercer", "133": "Monroe", "135": "Montgomery", "137": "Morgan", "139": "Moultrie", "141": "Ogle", "143": "Peoria",
    "145": "Perry", "147": "Piatt", "149": "Pike", "151": "Pope", "153": "Pulaski", "155": "Putnam", "157": "Randolph", "159": "Richland", "161": "Rock Island",
    "163": "St. Clair", "165": "Saline", "167": "Sangamon", "169": "Schuyler", "171": "Scott", "173": "Shelby", "175": "Stark", "177": "Stephenson", "179": "Tazewell",
    "181": "Union", "183": "Vermilion", "185": "Wabash", "187": "Warren", "189": "Washington", "191": "Wayne", "193": "White", "195": "Whiteside", "197": "Will",
    "199": "Williamson", "201": "Winnebago", "203": "Woodford",
}


def county_of(api):
    """The county's name from an Illinois API number (state code 12, county code, then the well's own digits), or None for a blank, a short one or another state's. Nothing else of the number is kept."""
    digits = re.sub(r"\D", "", str(api or ""))
    if len(digits) not in (10, 12, 14) or not digits.startswith("12"):
        return None
    return COUNTIES.get(digits[2:5])


def query_url(offset):
    """One page of the query: permits dated 2019 or later, the four columns, no geometry, in row-id order (so paging does not skip or repeat)."""
    return QUERY + "?" + urllib.parse.urlencode({
        "f": "json", "where": "PERMIT_DATE >= DATE '2019-01-01'", "outFields": ",".join(FIELDS), "returnGeometry": "false",
        "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": PAGE})


def parse_page(doc):
    """(rows, more) from one decoded reply: rows as dicts of the four columns, `more` true when the service says there is another page. A reply that is an error, or that is missing a column
    or the list of rows, raises: the layer's shape changed, or the service is not answering."""
    if not isinstance(doc, dict):
        raise RuntimeError("the layer answered with something that is not a result")
    if doc.get("error"):
        raise RuntimeError("the layer answered with an error (code %s)" % str((doc["error"] or {}).get("code"))[:10])
    names = {f.get("name") for f in doc.get("fields") or [] if isinstance(f, dict)}
    missing = [f for f in FIELDS if f not in names]
    if missing:
        raise RuntimeError("the layer no longer has the column(s) %s: its layout changed" % ", ".join(missing))
    feats = doc.get("features")
    if not isinstance(feats, list):
        raise RuntimeError("the layer's reply has no list of rows")
    rows = []
    for f in feats:
        a = f.get("attributes") if isinstance(f, dict) else None
        if isinstance(a, dict):
            rows.append({k: a.get(k) for k in FIELDS})
    return rows, bool(doc.get("exceededTransferLimit"))


def fetch(get=C.polite_json):
    """Every row since 2019, page by page, repeats (by row id) dropped. `get` takes a URL and returns the decoded reply."""
    rows, seen, offset = [], set(), 0
    for _ in range(MAX_PAGES):
        page, more = parse_page(get(query_url(offset)))
        fresh = [r for r in page if r["OBJECTID"] not in seen]
        seen.update(r["OBJECTID"] for r in fresh)
        rows += fresh
        offset += len(page)
        if not more:
            return rows
        if not page:
            raise RuntimeError("the layer says there are more rows but gave none")
    raise RuntimeError("the layer gave more than %d pages: something is wrong" % MAX_PAGES)


def build(get=None, today=None):
    today = today or date.today()
    if get is None:
        get = lambda url: C.polite_json(url, max_bytes=8 * 1024 * 1024, timeout=90)  # noqa: E731
    rows = fetch(get)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("only %d permits came back (expected %d or more): the layer or the query changed" % (len(rows), MIN_ROWS))
    t = C.Tally(STATE, bands=("new",), fluid=False)
    no_day = no_county = 0
    for r in rows:
        day = C.parse_day(r["PERMIT_DATE"], today)
        if day is None or day.year < 2019:
            no_day += 1
            continue
        county = county_of(r["API_NUMBER"])
        no_county += county is None
        name = r["COMPANY_NAME"] if isinstance(r["COMPANY_NAME"], str) else None
        t.add(day, "new", county=county, operator=name)
    if no_day > MAX_BAD * len(rows):
        raise RuntimeError("%d of %d permit dates could not be read: the date column changed" % (no_day, len(rows)))
    if no_county > MAX_BAD * len(rows):
        raise RuntimeError("%d of %d API numbers gave no known county: the numbering changed" % (no_county, len(rows)))
    if t.newest is None or (today - t.newest).days > MAX_STALE_DAYS:
        raise RuntimeError("the newest permit is dated %s: the layer has stopped being refreshed" % (t.newest.isoformat() if t.newest else "never"))
    return t.document(
        agency="Illinois Department of Natural Resources, Oil and Gas Resource Management (data from the Illinois State Geological Survey)",
        source_name="ILOIL Wells layer of the Illinois State Geological Survey (a permit date for every well)",
        source_url=LAYER, basis="permit date (the day the permit to drill was issued)", cadence="weekly", measure="permits", unit="wells permitted",
        note="Wells that received a permit to drill, by the day the permit was issued: oil, gas, coal-mine methane and injection wells together, because the survey's layer records the kind of well only once it is "
             "drilled (kinds of permits are not available). A permit to convert, deepen or renew an existing well adds no row (a conversion to injection was mostly missing in a check against the "
             "agency's weekly log). The layer runs about two months behind the agency's weekly permit log, so the series ends before the other states'.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
