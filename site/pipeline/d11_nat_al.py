#!/usr/bin/env python3
"""D11: Alabama's oil and gas permits (State Oil and Gas Board of Alabama), for the National report of the Oil tracker.

The Board publishes its wells as a free ArcGIS layer (OGB Online Map, "Wells", MapServer layer 0): one row per permit entry with a `PermitDate` (the day the permit was
issued), the well type, the county and the operator. This asks the layer for every entry dated 2015 or later (about 400 rows, 90 KB, one request), keeps the permit number only
long enough to tell new wells from older ones, and writes nat/AL.json: permits counted by the day they were issued. What the layer can and cannot tell (NOTES_D11.md):

  - `new`: a permit whose number is the next one in the Board's sequence (permit numbers run 17140 in 2015 to about 17550 in 2026, in step with the date, so a number far
    behind the sequence is a permit on a well numbered years ago: a re-permit, deepening, re-entry or amendment, which the layer does not name). A number seen twice counts once.
    Alabama permits about 30 new wells a year, most of them coal bed methane in the Black Warrior Basin;
  - `inj`: the well type says injection, disposal, gas injection or storage, or water source (the layer's own codes WI, SWD, GI, WS); most are existing wells permitted to inject;
  - `other`: the older-numbered permits above (published as "other filings", never as new wells);
  - the layer holds permits that still exist: one cancelled or expired unspent drops out, so a year's count can be a little short of the permits issued;
  - the fluid is the layer's well type (oil, gas, coal bed methane counted as gas, undesignated as unknown), which can be the type as drilled, not as permitted.

An operator is named only if it is a corporation, LLC or partnership. No well, API number, lease or permit number leaves this file (the Tally keeps counts). A layer that changed (a
missing field, an error reply, too few rows, a numbering that no longer follows the date, a newest permit older than 5 months) fails the run and leaves the committed file alone.

  python3 -I site/pipeline/d11_nat_al.py [--check]
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

STATE = "AL"
LAYER = "https://gis.ogb.state.al.us/arcgis/rest/services/OGB/OGBOnlineMap/MapServer/0"
FIELDS = ("Permit", "PermitDate", "WellType", "TypeDesc", "CountyName", "Operator")  # nothing else is asked for: no well name, API number, comment or location
SINCE = "2015-01-01"  # read back this far so the permit numbering has a footing; the series shows from 2019
PAGE = 1000
MAX_PAGES = 8
PAUSE = 3.0
SERVICE_CODES = ("SWD", "WI", "GI", "WS")  # water disposal, water injection, gas injection, water source
TOL = 25  # a new permit's number is no more than this far behind the newest number seen (out-of-order issue happens by 20 or so)
JUMP = 100  # nor more than this far ahead (one mistyped number must not move the sequence)
MIN_ROWS = 200  # the layer gave 394 rows for 2015 onward
MIN_NEW_SHARE = 0.4  # of the permits that are not service wells, at least this many must follow the sequence (about 80% do)


def url_for(offset, since=SINCE):
    q = {"where": "PermitDate >= DATE '%s'" % since, "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "PermitDate,Permit",
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


def base_of(permit):
    """The number a permit starts with ('17436-CG' gives 17436, '5115-SWD-26-01' 5115), None when it starts with none."""
    m = re.match(r"\s*(\d{1,6})(?!\d)", str(permit or ""))
    return int(m.group(1)) if m else None


def is_service(row):
    """A disposal, injection, gas-injection, storage or water-source permit, by the layer's own type code or words."""
    return (row.get("WellType") or "").strip().upper() in SERVICE_CODES or C.band_of("", row.get("TypeDesc") or "") == "inj"


def parse(rows, today=None):
    """Permit entries as dicts {day, base, service, county, operator, fluid}, oldest first, exact repeats of one entry dropped. An entry with no PermitDate is left out (the layer has
    some); a date or number that cannot be read fails the run when more than 2% of the entries have one."""
    today = today or date.today()
    out, seen, bad = [], set(), 0
    for r in rows:
        if r.get("PermitDate") is None:
            continue
        day, base = C.parse_day(r["PermitDate"], today), base_of(r.get("Permit"))
        if day is None or base is None:
            bad += 1
            continue
        key = (str(r.get("Permit")), day, r.get("WellType"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"day": day, "base": base, "service": is_service(r), "county": r.get("CountyName"), "operator": (r.get("Operator") or "").strip(),
                    "fluid": C.fluid_of(r.get("TypeDesc") or r.get("WellType") or "")})
    if bad > 0.02 * max(1, len(rows)):
        raise RuntimeError("%d of %d permit entries have a date or a number that cannot be read" % (bad, len(rows)))
    out.sort(key=lambda r: (r["day"], r["base"]))
    return out


def classify(permits):
    """Sets permit['band'] on each: 'inj' for a service well, 'new' for a number that follows the Board's sequence and is seen for the first time, 'other' for the rest.
    The sequence starts at the middle number of the first twenty plain permits and moves up with every new one; it fails the run when too few permits follow it."""
    plain = [p for p in permits if not p["service"]]
    head = sorted(p["base"] for p in plain[:20])
    front = head[len(head) // 2] if head else 0
    seen = set()
    for p in permits:
        if p["service"]:
            p["band"] = "inj"
            continue
        fresh = p["base"] not in seen and front - TOL <= p["base"] <= front + JUMP
        p["band"] = "new" if fresh else "other"
        seen.add(p["base"])
        if fresh:
            front = max(front, p["base"])
    n_new = sum(1 for p in plain if p["band"] == "new")
    if not plain or n_new < MIN_NEW_SHARE * len(plain):
        raise RuntimeError("only %d of %d permits follow the Board's number sequence: the numbering may have changed" % (n_new, len(plain)))
    return permits


def build(get=C.polite_get, today=None, pause=PAUSE):
    today = today or date.today()
    rows = fetch(get, pause)
    if len(rows) < MIN_ROWS:
        raise RuntimeError("the layer gave %d permit entries since %s (expected 300 or more)" % (len(rows), SINCE))
    permits = classify(parse(rows, today))
    t = C.Tally(STATE, bands=("new", "inj", "other"), fluid=True)
    for p in permits:
        if p["day"] >= date(2019, 1, 1):  # the earlier years only gave the numbering its footing
            t.add(p["day"], p["band"], county=p["county"], operator=p["operator"], fluid=p["fluid"])
    if t.newest is None or t.newest < today - timedelta(days=150):
        raise RuntimeError("the newest permit is %s: the layer looks stale" % (t.newest,))
    return t.document(agency="State Oil and Gas Board of Alabama", source_name="OGB Online Map, Wells layer (permit date)", source_url=LAYER, basis="permit date (the day the permit was issued)",
                      cadence="as permits are issued (the Board states no schedule)", measure="permits", asof=t.newest,
                      note="Permits counted by their permit date. A new well is a permit that takes the next number in the Board's sequence, nearly all coal bed methane in the Black Warrior Basin "
                           "(about 30 a year, so a month is often zero); permits on wells numbered earlier (re-permits, deepenings, re-entries, amendments: the layer does not say which) are "
                           "'other filings', and injection, disposal and water-source permits are their own band. Cancelled permits drop out of the layer (about one number in seven was missing from 2023 to 2026), so a count can be a little short.")


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
