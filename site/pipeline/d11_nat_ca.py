#!/usr/bin/env python3
"""D11: California's oil and gas permits (CalGEM, the Geologic Energy Management Division), for the National report of the Oil tracker.

CalGEM approves a "Notice of Intention" (NOI) before an operator drills, reworks or plugs a well, and publishes the approved ones as a free ArcGIS layer (WellSTAR, Notices
service, layer 1, "Approved Notice of Intention/Permit"): one row per notice with the day CalGEM made its determination, the kind of notice, the well type, the county and the
operator. This reads every row (about 8,500, 2,000 to a request, 1.8 MB in all) and writes nat/CA.json: permits counted by the day CalGEM approved them. What the layer can and
cannot tell (NOTES_D11.md):

  - `new`: "NOI - New Drill" for a well that produces or explores (oil and gas, cyclic steam, gas, dry hole, stratigraphic);
  - `inj`: a New Drill for an injection, disposal, steamflood, waterflood, gas-storage, observation or water-source well (CalGEM's own well types);
  - `redrill`: sidetracks and deepenings; `rework`: reworks (CalGEM files recompletions, conversions and other work on an existing well as one "Rework");
  - `other`: plugging (Abandon, Re-Abandon), about two thirds of all notices: published as other filings, never as new wells;
  - amendments are not told: the layer has no supplementary-permit flag, so `amend` is null (never zero);
  - the layer holds approved and closed notices; canceled ones (about 0.6%) are left out because their date may be the cancellation, not an approval;
  - dates are UTC instants and are read as California (Pacific) days, so an approval at 5 pm on the last day of a month stays in that month;
  - the layer starts on 14 November 2024 (its first months are thin), so the series begins there, not in 2019.

An operator is named only if it is a corporation, LLC or partnership. Only the six columns above are requested: no API number, well name, lease or location is asked for, so none can
reach the file. A layer that changed (a missing column, an error reply, too few rows, a status or kind never seen, dates that do not read, a newest permit more than 10 days old)
fails the run and leaves the committed file alone. Requests identify no person and are 3 seconds apart.

  python3 -I site/pipeline/d11_nat_ca.py [--check]
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

STATE = "CA"
LAYER = "https://gis.conservation.ca.gov/server/rest/services/WellSTAR/Notices/MapServer/1"
FIELDS = ("OBJECTID", "NoticeType", "NoticeStatus", "NoticeDateDetermination", "WellTypeLabel", "County", "OperatorName")  # OBJECTID only pages through the rows; it is never kept
PAGE = 2000  # the layer's maxRecordCount
MAX_PAGES = 12  # the layer holds about 8,500 rows
PAUSE = 3.0
MIN_ROWS = 3000  # 8,519 on 2026-11-01
STALE_DAYS = 10  # a layer whose newest approval is older than this is not current (CalGEM approves on weekdays, so a long weekend is 4 days)
MIN_MONTHS = 24  # the shared validator's floor
COUNTED = ("Approved", "Closed")  # an approved notice, and one whose work has been reported; "Canceled" is left out
SKIPPED = ("Canceled",)
KINDS = {"abandon": "other", "re-abandon": "other", "new drill": "new", "rework": "rework", "sidetrack": "redrill", "deepen": "redrill"}
# CalGEM's well types of a service well: injectors (Water Disposal, Waterflood, Steamflood, Gas Disposal, Air Injector, Pressure Maintenance), storage, observation, water source
SERVICE = re.compile(r"inject|dispos|flood|storage|water source|observation|pressure maint", re.I)
BAD_SHARE = 0.02  # more than this share of rows that cannot be read fails the run


# ------------------------------------------------------------------------------------------------ Pacific days

def nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def pacific_offset(utc):
    """-7 hours while US daylight time is in force (2:00 am on the second Sunday of March to 2:00 am on the first Sunday of November), else -8; `utc` is a timezone-aware datetime."""
    start = datetime.combine(nth_sunday(utc.year, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=10)  # 2:00 am PST
    end = datetime.combine(nth_sunday(utc.year, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=9)  # 2:00 am PDT
    return timedelta(hours=-7 if start <= utc < end else -8)


def pacific_day(ms):
    """The California calendar day of an ArcGIS date (milliseconds since 1970, UTC); None for anything that is not a plausible instant."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 1e11 < ms < 4e12:
        return None
    utc = datetime.fromtimestamp(ms / 1000.0, timezone.utc)
    return (utc + pacific_offset(utc)).date()


def pacific_today(now=None):
    utc = now or datetime.now(timezone.utc)
    return (utc + pacific_offset(utc)).date()


# ------------------------------------------------------------------------------------------------ reading the layer

def url_for(last_id):
    q = {"where": "OBJECTID > %d" % last_id, "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID", "resultRecordCount": str(PAGE), "f": "json"}
    return LAYER + "/query?" + urllib.parse.urlencode(q)


def fetch(get=C.polite_get, pause=PAUSE):
    """Every attribute row of the layer, page by page (by OBJECTID, so a row added or removed between requests cannot shift a page). A reply that is an error, has no rows list or lacks
    one of the columns asked for fails the run."""
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


# ------------------------------------------------------------------------------------------------ reading a notice

def work_of(notice_type):
    """'new drill', 'rework'... from 'NOI - New Drill'."""
    return re.sub(r"^\s*noi\s*[-:]\s*", "", str(notice_type or ""), flags=re.I).strip().lower()


def band_for(notice_type, well_type):
    """The band of one approved notice, from CalGEM's own words; None for a kind of notice never seen (the run counts those and fails when there are many). Plugging is `other`; a New Drill
    for a service well (injection, disposal, steam or water flood, storage, observation, water source) is `inj`; sidetracks and deepenings are `redrill`; reworks are `rework`."""
    work = work_of(notice_type)
    if work not in KINDS:
        return None
    if work == "new drill":
        return "inj" if SERVICE.search(well_type or "") else "new"
    return KINDS[work]


def fluid_for(well_type):
    """oil, gas, both, other or None from CalGEM's well type. CalGEM files oil and gas wells as one type ('Oil & Gas': shown as both) and cyclic steam wells, which are steamed heavy-oil producers, as oil."""
    t = (well_type or "").strip().lower()
    return "oil" if t == "cyclic steam" else C.fluid_of(well_type)


def parse(rows, today=None):
    """Counted notices as dicts {day, band, county, operator, fluid}, oldest first. Canceled notices are left out. More than 2% of the rows with a status never seen, a kind of notice never
    seen or a date that does not read fails the run (the layer changed); fewer is dropped."""
    today = today or pacific_today()
    out, bad, unknown_status, unknown_kind = [], 0, 0, 0
    for r in rows:
        status = (r.get("NoticeStatus") or "").strip()
        if status in SKIPPED:
            continue
        if status not in COUNTED:
            unknown_status += 1
            continue
        day = pacific_day(r.get("NoticeDateDetermination"))
        if day is None or day > today or day.year < 2020:
            bad += 1
            continue
        well = (r.get("WellTypeLabel") or "").strip()
        band = band_for(r.get("NoticeType"), well)
        if band is None:
            unknown_kind += 1
            continue
        out.append({"day": day, "band": band, "county": r.get("County"), "operator": (r.get("OperatorName") or "").strip() or None, "fluid": fluid_for(well)})
    n = max(1, len(rows))
    for what, k in (("a status never seen", unknown_status), ("a kind of notice never seen", unknown_kind), ("a date that does not read", bad)):
        if k > BAD_SHARE * n:
            raise RuntimeError("%d of %d rows have %s: the layer may have changed" % (k, len(rows), what))
    out.sort(key=lambda p: p["day"])
    return out


def last_complete_month(asof):
    """The newest month that ends on or before `asof`."""
    ym = C.month_of(asof)
    return ym if C.month_end(ym) <= asof else C.add_months(ym, -1)


def start_month(earliest, asof):
    """The first month of the series. The layer starts part-way through a month (14 November 2024); that month is left out as soon as the complete months after it reach the shared
    validator's floor of 24, and until then it is kept and the note says it is a part month. Returns (month, part month or None)."""
    part = earliest.day > 4  # the first business day of a month is the 1st to the 4th, so a layer that starts later in the month starts part-way through it
    full = C.add_months(C.month_of(earliest), 1) if part else C.month_of(earliest)
    through = last_complete_month(asof)
    if not part or len(C.month_list(full, through)) >= MIN_MONTHS:
        return full, None
    return C.month_of(earliest), earliest


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or pacific_today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d notices (expected 8,000 or more)" % len(rows))
    permits = parse(rows, today)
    if not permits:
        raise RuntimeError("no approved notice could be read")
    newest, earliest = permits[-1]["day"], permits[0]["day"]
    if newest < today - timedelta(days=STALE_DAYS):
        raise RuntimeError("the newest approval is %s: the layer looks stale" % newest)
    # the layer is current to the day and CalGEM approves on weekdays, so the days after the newest approval up to yesterday are complete too: asOf is that day
    asof = max(newest, today - timedelta(days=1))
    first, part = start_month(earliest, asof)
    t = C.Tally(STATE, bands=("new", "inj", "redrill", "rework", "other"), fluid=True)
    for p in permits:
        t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    since = "%s %d, %d" % (earliest.strftime("%B"), earliest.day, earliest.year)
    return t.document(agency="California Geologic Energy Management Division (CalGEM)", source_name="WellSTAR Notices map service, Approved Notice of Intention/Permit layer",
                      source_url=LAYER, basis="approval date (CalGEM's determination on the notice of intention, as a California day)", cadence="daily (the layer is current to the day)",
                      measure="permits", asof=asof, first=first,
                      note="Approved notices of intention (permits to drill, rework or plug), by the day CalGEM approved them. The layer starts on %s%s, so the series begins there, not in 2019. "
                           "New wells are New Drill notices; those for injection, disposal, steam or water flood, storage, observation and water-source wells are their own band. Reworks (recompletions "
                           "and conversions together) and sidetracks and deepenings have their own bands; plugging, about two thirds of all notices, is 'other filings'. Amendments are not told. "
                           "Canceled notices are left out. Almost no new-drill permit was approved in 2025 and several hundred in 2026, so the change from the year before reflects what "
                           "CalGEM approved, not necessarily what was drilled. 'Oil & Gas' is one CalGEM well type (shown as both); cyclic steam wells count as oil."
                           % (since, " (the first month is a part month)" if part else ""))


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
