#!/usr/bin/env python3
"""D13: the outlines of the 49 states that can hold oil (the lower 48 and Alaska), as one small committed file, for the national wells map.

Source: the U.S. Census Bureau's cartographic boundary files (1:10,000,000, public domain), as packaged by the `us-atlas` npm package
(version 3.0.1, `states-10m.json`, a quantized TopoJSON in longitude and latitude). This script is not part of any workflow: the outlines do not
change, so it was run once by hand and its output, `site/public/data/us-states.json`, is committed. The site draws it as a picture and the wells
producer (d13_ff_wells.py) uses it to check that a well's point lies in the state that the registry says it is in.

  python3 -I site/pipeline/d13_us_outline.py PATH/TO/states-10m.json            # writes site/public/data/us-states.json
  python3 -I site/pipeline/d13_us_outline.py PATH/TO/states-10m.json --check    # recomputes and compares with the committed file

The file: {"v":1, "source": "...", "states": {"TX": {"name": "Texas", "rings": [[lon, lat, lon, lat, ...], ...]}, ...}}. Rings are the outer
boundary of each piece of a state (islands included; lakes and holes are left out), coordinates rounded to two decimals (about a kilometer) after
Douglas-Peucker simplification, which is far below one pixel on a map of the whole country. Standard library only.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "public", "data", "us-states.json")
SOURCE = "U.S. Census Bureau cartographic boundary files, 1:10m (public domain), as packaged in us-atlas 3.0.1"
EPS = 0.012  # degrees: simplification tolerance (about 1.3 km)
FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "12": "FL", "13": "GA", "16": "ID", "17": "IL", "18": "IN",
        "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
        "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA",
        "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def ring_points(arcs, indexes):
    pts = []
    for i in indexes:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts += a if not pts else a[1:]
    return pts


def simplify(pts, eps=EPS):
    """Douglas-Peucker on a closed ring (kept closed), iterative so a long coastline cannot overflow the stack."""
    if len(pts) < 5:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, at = -1.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm if norm else math.hypot(x - x1, y - y1)
            if d > best:
                best, at = d, i
        if best > eps:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(pts, keep) if k]


def build(topo):
    arcs = decode_arcs(topo)
    states = {}
    for g in topo["objects"]["states"]["geometries"]:
        code = FIPS.get(g["id"])
        if not code:
            continue  # Hawaii, the District of Columbia and the territories hold no oil in the EIA's tables
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        rings = []
        for poly in polys:
            r = simplify(ring_points(arcs, poly[0]))
            if len(r) < 4:
                continue
            flat = []
            for lon, lat in r:
                flat += [round(lon, 2), round(lat, 2)]
            rings.append(flat)
        rings.sort(key=lambda r: -len(r))
        states[code] = {"name": g["properties"]["name"], "rings": rings}
    return {"v": 1, "source": SOURCE, "states": dict(sorted(states.items()))}


def check_doc(doc):
    """Problems with an outline file ([] when good): every state present, rings closed and in range."""
    p = []
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("states"), dict):
        return ["not a v1 outline file"]
    if set(doc["states"]) != set(FIPS.values()):
        p.append("the states are not the 49 expected")
    for code, s in doc["states"].items():
        rings = s.get("rings") if isinstance(s, dict) else None
        if not rings or not isinstance(s.get("name"), str):
            p.append(code + ": no name or rings")
            continue
        for r in rings:
            if len(r) % 2 or len(r) < 8 or r[:2] != r[-2:]:
                p.append(code + ": a ring is not closed")
                break
            lons, lats = r[0::2], r[1::2]
            if not (all(-180 <= x <= -60 or 170 <= x <= 180 for x in lons) and all(15 <= y <= 75 for y in lats)):
                p.append(code + ": a ring is outside the country")
                break
    return p


def write(doc, path=OUT):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if "--check" in argv and not args:
        doc = json.load(open(OUT, encoding="utf-8"))
        bad = check_doc(doc)
        print("us-states.json: " + ("ok" if not bad else "; ".join(bad)))
        return 1 if bad else 0
    if len(args) != 1:
        print(__doc__)
        return 2
    with open(args[0], encoding="utf-8") as f:
        doc = build(json.load(f))
    bad = check_doc(doc)
    if bad:
        print("refusing to write: " + "; ".join(bad))
        return 1
    if "--check" in argv:
        same = json.load(open(OUT, encoding="utf-8")) == doc
        print("us-states.json " + ("matches" if same else "differs from") + " what the source gives")
        return 0 if same else 1
    write(doc)
    print("wrote", OUT, os.path.getsize(OUT), "bytes,", sum(len(s["rings"]) for s in doc["states"].values()), "rings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
