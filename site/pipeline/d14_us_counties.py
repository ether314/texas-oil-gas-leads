#!/usr/bin/env python3
"""D14: the outlines of every county of the 49 states that can hold oil (the lower 48 and Alaska) as one committed file, for the national Map.

Sources (both from the U.S. Census Bureau, public domain): the cartographic boundary shapes at 1:10,000,000, as packaged by the `us-atlas` npm package (version 3.0.1,
`counties-10m.json`, a quantized TopoJSON in longitude and latitude: the same package and version as the state outlines of `d13_us_outline.py`), and the 2023 Gazetteer of
counties (`2023_Gaz_counties_national.txt`), which gives each county's full name ("Caddo Parish", "North Slope Borough", "Richmond city") and an internal point to put its label on.
This script is not part of any workflow: county lines do not change, so it was run once by hand and its output, `site/public/data/us-counties.json`, is committed.

  python3 -I site/pipeline/d14_us_counties.py PATH/TO/counties-10m.json PATH/TO/2023_Gaz_counties_national.txt          # writes site/public/data/us-counties.json
  python3 -I site/pipeline/d14_us_counties.py PATH/TO/counties-10m.json PATH/TO/2023_Gaz_counties_national.txt --check  # recomputes and compares with the committed file
  python3 -I site/pipeline/d14_us_counties.py --check                                                                    # validates the committed file

The file is topology-preserving, like the TopoJSON it comes from: every border is stored once, as an arc, and each county lists its rings as signed arc numbers (`~n` is arc `n` walked
backwards, as in TopoJSON). Two neighbors therefore share the same points exactly (no sliver between them at any zoom), and the page can draw a border between two counties of one state,
a border between two states and the coast as three different lines by counting the counties (and states) that use each arc.

  {"v": 1, "source": "...", "unit": 1000, "suffixes": [" County", " Parish", ...],
   "arcs": [[x0, y0, dx, dy, ...], ...],                       # whole numbers of 1/unit degree; the first pair is absolute, the rest are steps
   "counties": [["48329", "Midland", 0, -102.03, 31.93, [[arc, arc, ...], ...]], ...]}   # fips, name, suffix, label lon, label lat, rings

A county's rings are all its pieces (islands too) and the holes in them, outer rings wound one way and holes the other (as the source does), so a fill with the default rule leaves a hole empty. Standard library only.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d13_us_outline as O  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "public", "data", "us-counties.json")
SOURCE = ("U.S. Census Bureau cartographic boundary files, 1:10m (public domain), as packaged in us-atlas 3.0.1, with the names and internal points of the 2023 Census Gazetteer of counties")
UNIT = 1000  # a coordinate is a whole number of thousandths of a degree (about 100 m, far below a pixel on a map of the whole country)
EPS = 0.0003  # degrees: the source is already generalized for 1:10m (45,000 points for 3,100 counties), so this trims only points within about 30 m of a straight line; a coarser tolerance
#               collapses the smallest counties (Falls Church, Virginia, is two arcs of two points at 0.002) and saves under 3%
# what a county is called after its name, longest first so "City and Borough" is not read as "Borough"
SUFFIXES = [" City and Borough", " Census Area", " Municipality", " Planning Region", " County", " Parish", " Borough", " city"]
FIPS = O.FIPS


def simplify_arc(pts, eps=EPS):
    """Douglas-Peucker on an open arc (iterative); both ends are kept, so two counties that share the arc cannot come apart."""
    if len(pts) < 3:
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


def quantize(pts):
    """Whole thousandths of a degree, a point repeated by the rounding dropped."""
    out = []
    for x, y in pts:
        q = (round(x * UNIT), round(y * UNIT))
        if not out or q != out[-1]:
            out.append(q)
    return out


def read_gazetteer(path):
    """{geoid: (full name, lon, lat)} from the Census Gazetteer file (tab separated; the header's last column is padded with spaces)."""
    got = {}
    with open(path, encoding="utf-8") as f:
        head = [h.strip() for h in f.readline().rstrip("\n").split("\t")]
        ix = {h: i for i, h in enumerate(head)}
        for col in ("GEOID", "NAME", "INTPTLAT", "INTPTLONG"):
            if col not in ix:
                raise ValueError("the Gazetteer file has no %s column" % col)
        for line in f:
            c = [x.strip() for x in line.rstrip("\n").split("\t")]
            if len(c) < len(head):
                continue
            try:
                got[c[ix["GEOID"]]] = (c[ix["NAME"]], float(c[ix["INTPTLONG"]]), float(c[ix["INTPTLAT"]]))
            except ValueError:
                continue
    return got


def split_name(full):
    """("Caddo Parish") -> ("Caddo", " Parish"); a name that carries none of the suffixes ("Carson City", "District of Columbia") keeps it all and has no suffix."""
    for s in SUFFIXES:
        if full.endswith(s) and len(full) > len(s):
            return full[: -len(s)], s
    return full, ""


def area2(pts):
    """Twice the signed area of a ring (shoelace, planar longitude and latitude); positive is counterclockwise."""
    t = 0.0
    for i in range(len(pts) - 1):
        t += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return t


def build(topo, gaz):
    raw = O.decode_arcs(topo)
    geoms = [g for g in topo["objects"]["counties"]["geometries"] if str(g["id"])[:2] in FIPS]
    # every arc a kept county uses, simplified once and quantized once, so both sides of a border get the same points
    cache = {}

    def arc_points(i):
        if i not in cache:
            cache[i] = quantize(simplify_arc(raw[i]))
        return cache[i]

    def walk(ring):
        out = []
        for a in ring:
            p = arc_points(a) if a >= 0 else arc_points(~a)[::-1]
            out += p if not out else p[1:]
        return out

    kept = []  # (fips, atlas name, rings as the source's signed arc numbers)
    dropped = []
    for g in sorted(geoms, key=lambda x: str(x["id"])):
        rings = []
        for poly in (g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]):
            for ring in poly:
                pts = walk(ring)
                # a piece the source draws as a line, or the rounding has collapsed into one, has no area to fill or to point at: left out (its arcs too, if no one else uses them).
                # The source winds outer rings one way and holes the other and the file keeps that, so a fill leaves a hole empty
                if len(pts) >= 4 and abs(area2(pts)) >= 1e-3:
                    rings.append(ring)
        if rings:
            kept.append((str(g["id"]).zfill(5), g.get("properties", {}).get("name", ""), rings))
        else:
            dropped.append(str(g["id"]).zfill(5))  # Falls Church, Virginia, is two arcs of two points in the source
    # the arcs the kept rings use, numbered in the order of the source
    used = sorted({a if a >= 0 else ~a for _, _, rings in kept for ring in rings for a in ring})
    new = {old: n for n, old in enumerate(used)}
    suffixes = []
    counties = []
    for fips, atlas, rings in kept:
        full, lon, lat = gaz.get(fips, (None, None, None))
        if full is None:
            name, suffix = atlas, " County"  # a county the Gazetteer does not list (it moved to planning regions, or was renamed): the shape's own name
            lon = lat = None
        else:
            name, suffix = split_name(full)
        if suffix not in suffixes:
            suffixes.append(suffix)
        counties.append([fips, name, suffixes.index(suffix), None if lon is None else round(lon, 2), None if lat is None else round(lat, 2),
                         [[new[a] if a >= 0 else ~new[~a] for a in ring] for ring in rings]])
    arcs = []
    for old in used:
        flat = []
        px = py = 0
        for j, (x, y) in enumerate(arc_points(old)):
            flat += [x, y] if j == 0 else [x - px, y - py]
            px, py = x, y
        arcs.append(flat)
    build.dropped = dropped
    return {"v": 1, "source": SOURCE, "unit": UNIT, "suffixes": suffixes, "arcs": arcs, "counties": counties}


def decode_arcs(doc):
    """The arcs as lists of (lon, lat) floats (what a reader needs to walk a ring)."""
    out = []
    for flat in doc["arcs"]:
        pts = []
        x = y = 0
        for j in range(0, len(flat), 2):
            x = flat[j] if j == 0 else x + flat[j]
            y = flat[j + 1] if j == 0 else y + flat[j + 1]
            pts.append((x / doc["unit"], y / doc["unit"]))
        out.append(pts)
    return out


def ring_points(arcs, ring):
    out = []
    for a in ring:
        p = arcs[a] if a >= 0 else arcs[~a][::-1]
        out += p if not out else p[1:]
    return out


def check_doc(doc, states=None, min_counties=3):
    """Problems with a county file ([] when good): the shape of it, every state present (Delaware has the fewest counties, three), every ring closed and in range, every arc used by some county (a border is used by the two counties on its sides; the source has 44 two-point
    arcs that a few more share, at the corners where counties meet), no arc left over, a label point that is a place."""
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("arcs"), list) or not isinstance(doc.get("counties"), list) or doc.get("unit") != UNIT:
        return ["not a v1 county file"]
    p = []
    arcs = doc["arcs"]
    n = len(arcs)
    for i, flat in enumerate(arcs):
        if not isinstance(flat, list) or len(flat) % 2 or len(flat) < 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in flat):
            p.append("arc %d is not a list of whole-number points" % i)  # an arc of one point is a border shorter than the rounding: harmless
            break
    if p:
        return p
    pts = decode_arcs(doc)
    for i, a in enumerate(pts):
        if not all(-180 <= x <= -60 or 170 <= x <= 180 for x, _ in a) or not all(15 <= y <= 75 for _, y in a):
            p.append("arc %d is outside the country" % i)
            break
    use = [[0, 0] for _ in range(n)]  # forward, backward
    per_state = {}
    seen = set()
    sfx = doc.get("suffixes")
    if not isinstance(sfx, list) or not all(isinstance(s, str) for s in sfx):
        return p + ["no list of name suffixes"]
    for c in doc["counties"]:
        if not isinstance(c, list) or len(c) != 6:
            p.append("a county row is not [fips, name, suffix, lon, lat, rings]")
            break
        fips, name, sx, lon, lat, rings = c
        if not (isinstance(fips, str) and len(fips) == 5 and fips.isdigit() and fips[:2] in FIPS):
            p.append("county %r is not a five-digit FIPS code of one of the 49 states" % (fips,))
            continue
        if fips in seen:
            p.append("county %s twice" % fips)
        seen.add(fips)
        per_state[FIPS[fips[:2]]] = per_state.get(FIPS[fips[:2]], 0) + 1
        if not (isinstance(name, str) and name and not any(ch.isdigit() for ch in name) and "<" not in name and "http" not in name.lower()):
            p.append("county %s has no usable name: %r" % (fips, name))
        if not (isinstance(sx, int) and 0 <= sx < len(sfx)):
            p.append("county %s: a suffix that is not in the list" % fips)
        if (lon is None) != (lat is None) or (lon is not None and not ((-180 <= lon <= -60 or 170 <= lon <= 180) and 15 <= lat <= 75)):
            p.append("county %s: its label point is not a place in the country" % fips)
        if not isinstance(rings, list) or not rings:
            p.append("county %s has no rings" % fips)
            continue
        for r in rings:
            if not isinstance(r, list) or not r or not all(isinstance(a, int) and not isinstance(a, bool) and -n <= a < n for a in r):
                p.append("county %s: a ring names an arc that does not exist" % fips)
                break
            for a in r:
                use[a if a >= 0 else ~a][0 if a >= 0 else 1] += 1
            # a ring is closed: each arc starts where the one before it ended, and the last ends where the first began
            ends = [(pts[a][0], pts[a][-1]) if a >= 0 else (pts[~a][-1], pts[~a][0]) for a in r]
            if any(ends[k][1] != ends[(k + 1) % len(ends)][0] for k in range(len(ends))):
                p.append("county %s: a ring is not closed" % fips)
                break
            rp = ring_points(pts, r)
            if len(rp) < 4 or abs(area2(rp)) < 1e-9:
                p.append("county %s: a ring of fewer than three points, or with no area" % fips)
                break
    for i, (f, b) in enumerate(use):
        if f + b == 0:
            p.append("arc %d is used by no county" % i)
            break
    missing = set(states or FIPS.values()) - set(per_state)  # (a test's invented file names the states it has)
    if missing:
        p.append("no county for " + ", ".join(sorted(missing)))
    for st, k in per_state.items():
        if k < min_counties:
            p.append(st + ": fewer than %d counties" % min_counties)
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
        print("us-counties.json: " + ("ok, %d counties" % len(doc["counties"]) if not bad else "; ".join(bad[:5])))
        return 1 if bad else 0
    if len(args) != 2:
        print(__doc__)
        return 2
    topo = json.load(open(args[0], encoding="utf-8"))
    doc = build(topo, read_gazetteer(args[1]))
    bad = check_doc(doc)
    if bad:
        print("refused to write: " + "; ".join(bad[:5]))
        return 1
    if "--check" in argv:
        have = json.load(open(OUT, encoding="utf-8"))
        same = have == doc
        print("us-counties.json " + ("matches" if same else "DIFFERS from") + " what these inputs make")
        return 0 if same else 1
    write(doc)
    print("wrote %s: %d counties, %d arcs, %d KB" % (OUT, len(doc["counties"]), len(doc["arcs"]), os.path.getsize(OUT) // 1024))
    if build.dropped:
        print("left out (no area in the source): " + ", ".join(build.dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
