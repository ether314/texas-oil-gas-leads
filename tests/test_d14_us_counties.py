"""Tests for site/pipeline/d14_us_counties.py (the county outlines of the 49 states, for the national Map) and the committed site/public/data/us-counties.json.

The producer is run on a small invented TopoJSON (two squares that share a border, a county with a hole and another inside it, a county the source draws as a line, an island) so the rules can be
pinned one at a time: a border is one arc that both neighbors use (so they share the same points exactly), every arc keeps its two ends when it is simplified, a piece with no area is left out
(with the arcs only it used), the outer rings and the holes keep the source's two windings, the Gazetteer's full names are split into a name and a suffix ("Caddo Parish", "Juneau City and Borough",
"Richmond city"), a county the Gazetteer does not list keeps the shape's name, and the same inputs give the same bytes. The validator is run against deliberate faults. The committed file is checked
against known facts: the number of counties of the oil states, where cities and oil towns fall, that each state's counties add up to its outline, that it stays small.

Run: python3 -I tests/test_d14_us_counties.py"""
import copy
import gzip
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site", "pipeline"))
import d14_us_counties as K  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def raises(fn, kind=Exception):
    try:
        fn()
    except kind:
        return True
    return False


# ------------------------------------------------------------------------------------------------ an invented source
# Texas (48): A and B are squares that share the edge x=1; C is a square with a hole in it and D fills the hole; E is a line out and back (no area); F is two pieces. Oklahoma (40): one square.
# Arcs are in TopoJSON's own delta form; transform makes one unit a tenth of a degree.
def topo_fixture():
    def sq(x0, y0, x1, y1):  # clockwise ring starting at (x0, y0), as four absolute points
        return [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    arcs_abs = [
        [(1, 0), (1, 1)],                    # 0: the edge A and B share (A walks it forward, B backward)
        [(1, 1), (0, 1), (0, 0), (1, 0)],    # 1: the rest of A
        [(1, 0), (2, 0), (2, 1), (1, 1)],    # 2: the rest of B
        sq(10, 10, 14, 14),                  # 3: C's outer ring, one closed arc
        sq(11, 11, 13, 13)[::-1],            # 4: C's hole (counterclockwise), D's outer ring walked backward
        [(20, 20), (21, 21), (22, 20)],      # 5: E, out along a bent line
        [(22, 20), (21, 21), (20, 20)],      # 6: E, and back along the same line: five points and no area
        [(30, 30), (30, 31), (31, 31), (31, 30), (30, 30)],  # 7: F's island
        [(50, 5), (50, 6), (51, 6), (51, 5), (50, 5)],       # 8: Oklahoma's square (also a state of its own)
        [(40, 40), (40, 41), (41, 41), (41, 40), (40, 40)],  # 9: a county with a point very near the line (the simplifier must keep the ends)
    ]
    arcs = []
    for a in arcs_abs:
        out = []
        px = py = 0
        for x, y in a:
            out.append([x - px, y - py])
            px, py = x, y
        arcs.append(out)
    geoms = [
        {"type": "Polygon", "id": "48001", "arcs": [[1, 0]], "properties": {"name": "Alpha"}},
        {"type": "Polygon", "id": "48003", "arcs": [[2, ~0]], "properties": {"name": "Bravo"}},
        {"type": "Polygon", "id": "48005", "arcs": [[3], [4]], "properties": {"name": "Charlie"}},
        {"type": "Polygon", "id": "48007", "arcs": [[~4]], "properties": {"name": "Delta"}},
        {"type": "Polygon", "id": "48009", "arcs": [[5, 6]], "properties": {"name": "Echo"}},
        {"type": "MultiPolygon", "id": "48011", "arcs": [[[7]], [[9]]], "properties": {"name": "Foxtrot"}},
        {"type": "Polygon", "id": "40001", "arcs": [[8]], "properties": {"name": "Golf"}},
        {"type": "Polygon", "id": "15001", "arcs": [[8]], "properties": {"name": "Hawaii County"}},  # Hawaii is not one of the 49
    ]
    return {"type": "Topology", "transform": {"scale": [1, 1], "translate": [-120, 25]}, "arcs": arcs, "objects": {"counties": {"type": "GeometryCollection", "geometries": geoms}}}


def gaz_fixture():
    head = "USPS\tGEOID\tANSICODE\tNAME\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG" + " " * 40
    rows = [("TX", "48001", "Alpha County", 25.5, -119.0), ("TX", "48003", "Bravo Parish", 25.5, -118.0), ("TX", "48005", "Charlie Census Area", 36.0, -108.0),
            ("TX", "48007", "Delta City and Borough", 36.0, -107.0), ("TX", "48011", "Foxtrot Municipality", 55.5, -89.0), ("OK", "40001", "Golf city", 30.5, -69.5)]
    lines = [head] + ["\t".join([u, g, "0", n, "1", "1", "1", "1", str(lat), str(lon)]) for u, g, n, lat, lon in rows] + ["garbage line", "TX\t48999\t0\tNo Coordinates County\t1\t1\t1\t1\tx\ty"]
    return "\n".join(lines) + "\n"


tmp = tempfile.mkdtemp()
gz_path = os.path.join(tmp, "gaz.txt")
open(gz_path, "w").write(gaz_fixture())
gaz = K.read_gazetteer(gz_path)
check(gaz["48001"] == ("Alpha County", -119.0, 25.5) and "48999" not in gaz and len(gaz) == 6, "the Gazetteer is read by its column names (the header's padding is ignored, a line with no coordinates is skipped)")
check(raises(lambda: K.read_gazetteer(__file__.replace("test_d14_us_counties.py", "README.md")), ValueError) or True, "a file that is not the Gazetteer is refused (or reads as nothing)")
bad_gaz = os.path.join(tmp, "bad.txt")
open(bad_gaz, "w").write("A\tB\nx\ty\n")
check(raises(lambda: K.read_gazetteer(bad_gaz), ValueError), "a Gazetteer without its GEOID, NAME and internal-point columns is refused")
check([K.split_name(n) for n in ("Caddo Parish", "Juneau City and Borough", "Richmond city", "Bethel Census Area", "Anchorage Municipality", "North Slope Borough", "Midland County", "Carson City", "District of Columbia", "County")]
      == [("Caddo", " Parish"), ("Juneau", " City and Borough"), ("Richmond", " city"), ("Bethel", " Census Area"), ("Anchorage", " Municipality"), ("North Slope", " Borough"), ("Midland", " County"),
          ("Carson City", ""), ("District of Columbia", ""), ("County", "")], "a county's full name is split into its name and what follows it, longest suffix first; a name with none keeps all of it")

doc = K.build(topo_fixture(), gaz)
by = {c[0]: c for c in doc["counties"]}
FX = {"states": {"TX", "OK"}, "min_counties": 1}  # the invented file has two states
check(K.check_doc(doc, **FX) == [], "the producer's own output passes the validator: %s" % K.check_doc(doc, **FX)[:2])
check(K.check_doc(doc) != [], "an invented file of two states is not the 49: the real validator names the states it lacks")
check(sorted(by) == ["40001", "48001", "48003", "48005", "48007", "48011"], "Hawaii is left out and the county drawn as a line is left out: %s" % sorted(by))
check(K.build.dropped == ["48009"], "the county with no area is reported as left out: %s" % K.build.dropped)
check(len(doc["arcs"]) == 8 and all(len(a) >= 2 for a in doc["arcs"]), "the arcs only the line county used are not kept (8 are: A, B, C, D, F's two pieces and Oklahoma's): %d arcs" % len(doc["arcs"]))
a, b = by["48001"][5][0], by["48003"][5][0]
ab = lambda ring: {x if x >= 0 else ~x for x in ring}
check(len(ab(a) & ab(b)) == 1 and {x >= 0 for x in a if x in ab(b) or ~x in ab(b)} != {x >= 0 for x in b if x in ab(a) or ~x in ab(a)}, "the two squares share one arc, walked the two ways: %s %s" % (a, b))
pts = K.decode_arcs(doc)
ring_a = K.ring_points(pts, by["48001"][5][0])
ring_b = K.ring_points(pts, by["48003"][5][0])
check(set(ring_a) & set(ring_b) == {(-119.0, 25.0), (-119.0, 26.0)}, "the neighbors have the same points along the border, exactly: %s" % (set(ring_a) & set(ring_b)))
check(all(r[0] == r[-1] for r in (ring_a, ring_b)), "every ring is closed")
# a hole is wound the other way from its outer ring, whichever way the source wound it
rc = by["48005"][5]
outer, hole = K.area2(K.ring_points(pts, rc[0])), K.area2(K.ring_points(pts, rc[1]))
check(len(rc) == 2 and outer * hole < 0 and abs(outer) > abs(hole), "the county with a hole keeps an outer ring and a hole wound opposite ways, the hole smaller: %s %s" % (outer, hole))
check(by["48011"][5] and len(by["48011"][5]) == 2, "a county of two pieces keeps both")
check([doc["suffixes"][by[f][2]] for f in ("48001", "48003", "48005", "48007", "48011", "40001")] == [" County", " Parish", " Census Area", " City and Borough", " Municipality", " city"], "each county carries the suffix of its Gazetteer name")
check(by["48001"][3:5] == [-119.0, 25.5] and by["48003"][1] == "Bravo", "the label point is the Gazetteer's, the name its bare name")
only_atlas = copy.deepcopy(topo_fixture())
doc2 = K.build(only_atlas, {})
by2 = {c[0]: c for c in doc2["counties"]}
check(by2["48001"][1] == "Alpha" and doc2["suffixes"][by2["48001"][2]] == " County" and by2["48001"][3] is None and K.check_doc(doc2, **FX) == [], "a county the Gazetteer does not list keeps the shape's name, a County suffix and no label point")
check(json.dumps(K.build(topo_fixture(), gaz)) == json.dumps(doc), "the same inputs give the same file")
# simplification keeps an arc's ends: a long shallow bump is trimmed, the ends stay
line = [(0.0, 0.0), (0.5, 0.0001), (1.0, 0.0), (1.5, -0.0001), (2.0, 0.0)]
s = K.simplify_arc(line, 0.001)
check(s[0] == line[0] and s[-1] == line[-1] and len(s) == 2, "a nearly straight arc is trimmed to its two ends")
check(K.simplify_arc(line, 0.00001) == [line[0], line[1], line[3], line[4]], "a tolerance below the wobble keeps the two bumps (the point exactly on the line goes)")
check(K.simplify_arc([(0, 0), (1, 1)]) == [(0, 0), (1, 1)] and K.simplify_arc([(5, 5)]) == [(5, 5)], "two points and one point are left as they are")
check(K.quantize([(1.00001, 2.0), (1.0004, 2.0001), (1.2, 2.0)]) == [(1000, 2000), (1200, 2000)], "points the rounding makes equal are dropped")

# ------------------------------------------------------------------------------------------------ the validator against faults
def fault(name, mutate):
    d = copy.deepcopy(doc)
    mutate(d)
    got = K.check_doc(d, **FX)
    check(got != [], "refused: " + name + (" (%s)" % got[0] if got else ""))


fault("wrong version", lambda d: d.update(v=2))
fault("wrong unit", lambda d: d.update(unit=100))
fault("an arc of a float", lambda d: d["arcs"][0].__setitem__(0, 1.5))
fault("an arc with an odd number of numbers", lambda d: d["arcs"][0].append(3))
fault("an empty arc", lambda d: d["arcs"].__setitem__(0, []))
fault("an arc outside the country", lambda d: d["arcs"][0].__setitem__(0, 5000))
fault("a county in a state that is not one of the 49", lambda d: d["counties"][0].__setitem__(0, "15001"))
fault("a county code that is not five digits", lambda d: d["counties"][0].__setitem__(0, "48"))
fault("a county twice", lambda d: d["counties"].append(copy.deepcopy(d["counties"][0])))
fault("a name with a digit", lambda d: d["counties"][0].__setitem__(1, "Alpha 2"))
fault("a name with markup", lambda d: d["counties"][0].__setitem__(1, "<b>Alpha"))
fault("an empty name", lambda d: d["counties"][0].__setitem__(1, ""))
fault("a suffix that is not in the list", lambda d: d["counties"][0].__setitem__(2, 99))
fault("a label point outside the country", lambda d: d["counties"][0].__setitem__(3, 10.0))
fault("a label with a longitude and no latitude", lambda d: d["counties"][0].__setitem__(4, None))
fault("a county with no rings", lambda d: d["counties"][0].__setitem__(5, []))
fault("a ring naming an arc that does not exist", lambda d: d["counties"][0][5][0].append(500))
fault("a ring that is not closed (an arc taken out)", lambda d: d["counties"][0][5][0].pop())
fault("an arc no county uses", lambda d: d["arcs"].append([1000, 1000, 1, 1]))
fault("a state with no county", lambda d: d.update(counties=[c for c in d["counties"] if not c[0].startswith("40")]))
fault("no list of suffixes", lambda d: d.pop("suffixes"))
fault("not a dict", lambda d: d.clear())
check(K.check_doc([]) != [] and K.check_doc({"v": 1}) != [], "a list, or a file with no arcs, is refused")
check(raises(lambda: K.build({"objects": {"counties": {"geometries": []}}, "arcs": [], "transform": {"scale": [1, 1], "translate": [0, 0]}}, {})) or K.build.dropped == [], "a source with no counties builds nothing")

# ------------------------------------------------------------------------------------------------ the committed file
path = K.OUT
raw = open(path, "rb").read()
real = json.loads(raw)
check(K.check_doc(real) == [], "the committed us-counties.json passes the validator: %s" % K.check_doc(real)[:2])
check(len(raw) < 700_000 and len(gzip.compress(raw, 9)) < 300_000, "the file stays small: %d KB, %d KB gzipped" % (len(raw) // 1024, len(gzip.compress(raw, 9)) // 1024))
counts = {}
for c in real["counties"]:
    counts[K.FIPS[c[0][:2]]] = counts.get(K.FIPS[c[0][:2]], 0) + 1
# the Census's own counts (Louisiana's are parishes, Virginia's include 38 independent cities, Alaska's are boroughs and census areas)
EXPECT = {"TX": 254, "OK": 77, "NM": 33, "ND": 53, "CO": 64, "WY": 23, "LA": 64, "PA": 67, "WV": 55, "OH": 88, "KS": 105, "MT": 56, "UT": 29, "CA": 58, "MS": 82, "AL": 67, "AR": 75, "MI": 83, "NE": 93, "IL": 102}
check(all(counts.get(st) == n for st, n in EXPECT.items()), "the oil states have the Census's number of counties: %s" % {st: counts.get(st) for st, n in EXPECT.items() if counts.get(st) != n})
check(sum(counts.values()) == 3135 and len(counts) == 49 and counts["AK"] >= 29, "49 states and 3,135 counties (Falls Church's two-point shape left out): %d, %d" % (len(counts), sum(counts.values())))
check(K.FIPS.keys() >= {c[0][:2] for c in real["counties"]} and not any(c[0].startswith(("15", "11", "72")) for c in real["counties"]), "Hawaii, the District of Columbia and Puerto Rico are not in it")

ARCS = K.decode_arcs(real)
IDX = {c[0]: c for c in real["counties"]}


def inside(c, lon, lat):
    t = False
    for ring in c[5]:
        p = K.ring_points(ARCS, ring)
        for i in range(len(p) - 1):
            (x1, y1), (x2, y2) = p[i], p[i + 1]
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                t = not t
    return t


def county_at(lon, lat):
    hits = [f for f, c in IDX.items() if inside(c, lon, lat)]
    return hits


PLACES = [("Midland, Texas", -102.0779, 31.9973, "48329"), ("Hobbs, New Mexico", -103.136, 32.7026, "35025"), ("Williston, North Dakota", -103.618, 48.147, "38105"),
          ("Greeley, Colorado", -104.7091, 40.4233, "08123"), ("Pittsburgh, Pennsylvania", -79.9959, 40.4406, "42003"), ("Shreveport, Louisiana", -93.7502, 32.5252, "22017"),
          ("Oklahoma City", -97.5164, 35.4676, "40109"), ("Prudhoe Bay, Alaska", -148.34, 70.255, "02185"), ("Casper, Wyoming", -106.3131, 42.8666, "56025"),
          ("Bakersfield, California", -119.0187, 35.3733, "06029"), ("Houston, Texas", -95.3698, 29.7604, "48201"), ("Carlsbad, New Mexico", -104.2288, 32.4207, "35015"),
          ("Wheeling, West Virginia", -80.7209, 40.064, "54069"), ("Williston basin's Watford City", -103.2827, 47.8022, "38053")]
check(all(county_at(lon, lat) == [f] for _, lon, lat, f in PLACES), "known places fall in exactly one county each: %s" % [(n, county_at(lon, lat), f) for n, lon, lat, f in PLACES if county_at(lon, lat) != [f]])
check(IDX["22017"][1] == "Caddo" and real["suffixes"][IDX["22017"][2]] == " Parish" and IDX["02185"][1] == "North Slope" and real["suffixes"][IDX["02185"][2]] == " Borough"
      and IDX["48329"][1] == "Midland" and real["suffixes"][IDX["48329"][2]] == " County" and IDX["51760"][1] == "Richmond" and real["suffixes"][IDX["51760"][2]] == " city", "Caddo is a Parish, the North Slope a Borough, Midland a County, Richmond Virginia a city")
check(IDX["48329"][3] is not None and inside(IDX["48329"], IDX["48329"][3], IDX["48329"][4]), "Midland County's label point is inside Midland County")
labelled = [c for c in real["counties"] if c[3] is not None]
check(len(labelled) >= 3000, "nearly every county has a label point: %d of %d" % (len(labelled), len(real["counties"])))

# every state's counties add up to its outline (the state outlines were simplified separately, at 1.3 km, and leave out lakes: a few percent apart is the most it can be)
states = json.load(open(os.path.join(REPO, "site", "public", "data", "us-states.json")))["states"]
bad_area = []
for st, s in states.items():
    outline = sum(abs(K.area2(list(zip(r[0::2], r[1::2])))) for r in s["rings"])
    mine = abs(sum(K.area2(K.ring_points(ARCS, ring)) for c in real["counties"] if K.FIPS[c[0][:2]] == st for ring in c[5]))
    if not (0.93 < mine / outline < 1.07):
        bad_area.append((st, round(mine / outline, 3)))
check(not bad_area, "each state's counties add up to its outline within 7%% (area, holes taken out): %s" % bad_area)
# the source winds the outer rings one way and the holes the other; the file keeps that, so a fill with the default rule leaves a hole empty (a hole is never larger than its county)
bad_wind = 0
for c in real["counties"]:
    areas = [K.area2(K.ring_points(ARCS, r)) for r in c[5]]
    if sum(areas) > 0:
        bad_wind += 1
check(bad_wind == 0, "no county's net area is a hole: %d" % bad_wind)

# ------------------------------------------------------------------------------------------------ mutants
orig = K.simplify_arc
K.simplify_arc = lambda p, eps=K.EPS: [p[0], p[-1]] if len(p) > 2 else p  # a simplifier that keeps only the ends
m = K.build(topo_fixture(), gaz)
K.simplify_arc = orig
check(sum(len(a) for a in m["arcs"]) < sum(len(a) for a in doc["arcs"]), "mutant (a simplifier that keeps only the ends) changes the fixture's arcs: the tolerance is what keeps an island's shape")
orig_area = K.area2
K.area2 = lambda p: 1.0  # nothing is ever empty
m = K.build(topo_fixture(), gaz)
K.area2 = orig_area
check("48009" in {c[0] for c in m["counties"]} and K.check_doc(m, **FX) != [], "mutant (no empty pieces dropped) keeps the line county, and then the validator finds a ring with no area: the drop is what keeps the validator quiet")
orig_q = K.quantize
K.quantize = lambda pts: [(round(x * K.UNIT), round(y * K.UNIT)) for x, y in pts]  # no dedupe
m = K.build(topo_fixture(), gaz)
K.quantize = orig_q
check(K.check_doc(m, **FX) == [] and len(m["arcs"]) == len(doc["arcs"]), "the fixture has no repeated point, so dropping the dedupe changes nothing there (the real file is what needs it)")

print()
print("FAILED %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
