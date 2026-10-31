#!/usr/bin/env python3
"""D7 helper: where are these wells? Looks API numbers up in the Railroad Commission's public map service.

The nightly permit file (daf420.dat) carries a surface location (record 14) for only a few of each day's permits (3-12 of
40-80 in the last weeks, none on 2026-10-29), but the RRC's public viewer service has a point for nearly every permitted
well, keyed by the 8-digit API number (3-digit county code and 5-digit unique number):

  https://gis.rrc.texas.gov/server/rest/services/rrc_public/RRC_Public_Viewer_Srvs/MapServer/1   "Well Locations"

Fields used: API, GIS_LAT83, GIS_LONG83 (NAD83 degrees, within a metre or two of WGS84) and GIS_SYMBOL_DESCRIPTION.
On 2026-10-29 all 36 new-drill permits had a point there ("Permitted Location").

A failed or slow lookup returns what it did get: callers fall back to the permit file's own coordinates and the report
simply shows fewer points. Nothing here can cost a dataset, whatever the service answers (a body cut short, a garbage status
line, JSON that is not a result: http.client's own errors are neither OSError nor ValueError, and an earlier version let one of
them end the night after every download had finished). After the first failed lookup of a run no other is tried: a service that
is refusing is not asked once more for every report day. Standard library only.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

LAYER = "https://gis.rrc.texas.gov/server/rest/services/rrc_public/RRC_Public_Viewer_Srvs/MapServer/1/query"
UA = "Mozilla/5.0 (research script)"
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 25.5, 36.6, -106.8, -93.4
BATCH = 100  # APIs per request: the service answers up to 1000 features, and a well can appear more than once
API = re.compile(r"\d{8}")


def valid_point(lat, lon):
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def _query(apis, timeout=45, attempts=3):
    body = urllib.parse.urlencode({
        "where": "API IN (%s)" % ",".join("'%s'" % a for a in apis),
        "outFields": "API,GIS_LAT83,GIS_LONG83,GIS_SYMBOL_DESCRIPTION",
        "returnGeometry": "false", "f": "json",
    }).encode()
    err = None
    for k in range(attempts):
        try:
            req = urllib.request.Request(LAYER, data=body, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode("utf-8", "replace"))
            if not isinstance(out, dict):
                raise ValueError("the service answered with %s, not a result" % type(out).__name__)
            if "error" in out:
                raise ValueError(str(out["error"])[:120])
            feats = out.get("features") or []
            if not isinstance(feats, list):
                raise ValueError("the service's features are not a list")
            return feats
        except Exception as e:  # noqa: BLE001 - IncompleteRead and BadStatusLine are HTTPExceptions: any failure is one failed attempt
            err = e
            if k < attempts - 1:
                time.sleep(2 * (k + 1))
    raise RuntimeError("the RRC map service did not answer (%s)" % err)


class Locator:
    """{API: (lat, lon)} for the wells asked about, cached for the run."""

    def __init__(self, log=print):
        self.log, self.cache, self.failed = log, {}, False

    def locate(self, apis):
        """{API: (lat, lon)} for the wells the service has a point for. Never raises, and asks nothing once a lookup has failed."""
        want = sorted({a for a in apis if isinstance(a, str) and API.fullmatch(a) and a not in self.cache})
        for i in range(0, len(want), BATCH):
            if self.failed:
                break
            chunk = want[i:i + BATCH]
            found = {}
            try:
                for f in _query(chunk):
                    a = f.get("attributes") if isinstance(f, dict) else None
                    if not isinstance(a, dict):
                        continue
                    api, lat, lon = a.get("API"), a.get("GIS_LAT83"), a.get("GIS_LONG83")
                    if isinstance(api, str) and api in chunk and valid_point(lat, lon) and api not in found:
                        found[api] = (round(lat, 5), round(lon, 5))
            except Exception as e:  # noqa: BLE001 - nothing the service says may cost the night
                if not self.failed:
                    self.log("locate: SKIPPED (%s); the report falls back to the permit file's own coordinates" % e)
                self.failed = True
                break
            for api in chunk:
                self.cache[api] = found.get(api)  # None: the service has no point for it, and is not asked again
        return {a: self.cache[a] for a in apis if self.cache.get(a)}


if __name__ == "__main__":
    import sys
    pts = Locator().locate(sys.argv[1:])
    for api in sys.argv[1:]:
        print(api, pts.get(api))
