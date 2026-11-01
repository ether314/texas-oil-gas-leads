# NOTES_D14: the county outlines (for the national Map)

Script: `site/pipeline/d14_us_counties.py` (run once by hand, not part of any workflow). File: `site/public/data/us-counties.json`. Test: `tests/test_d14_us_counties.py`.
Why: the national Map shades every county by the new wells in it (FracFocus, NOTES_D13.md), so it needs the outline of every county in the country, drawn on the same Albers projection with an Alaska inset as the Overview (`usgeo.js`).

## Sources

- The U.S. Census Bureau's cartographic boundary shapes at 1:10,000,000 (public domain), as packaged in `us-atlas` 3.0.1 (`counties-10m.json`, a quantized TopoJSON): the same package and version as the state outlines (`d13_us_outline.py`), so a county line meets its state's line.
  `npm pack us-atlas@3.0.1`, then unpack. Put the download in a new folder and read it with `python3 -I`.
- The 2023 Census Gazetteer of counties (`2023_Gaz_counties_national.txt` from `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_counties_national.zip`): each county's full name ("Caddo Parish", "North Slope Borough", "Richmond city", which the shapes do not carry) and an internal point for its label.

```
python3 -I site/pipeline/d14_us_counties.py PATH/counties-10m.json PATH/2023_Gaz_counties_national.txt          # writes the file
python3 -I site/pipeline/d14_us_counties.py PATH/counties-10m.json PATH/2023_Gaz_counties_national.txt --check  # the file is what these inputs make
python3 -I site/pipeline/d14_us_counties.py --check                                                              # the committed file passes the validator
python3 -I tests/run_all.py d14
```

## The file

3,135 counties of the 49 states that can hold oil (the lower 48 and Alaska; not Hawaii, the District of Columbia or the territories), 612 KB, 242 KB gzipped. Topology-preserving, like the TopoJSON it comes from: every border is one **arc** (whole thousandths of a degree, the first point absolute and the rest steps),
and a county lists its rings as signed arc numbers (`~n` is arc `n` walked backwards). Two neighbors therefore have the same points exactly, with no sliver between them at any zoom, and a page can draw three lines, a thin one between counties of one state, a thicker one between two states and the coast, by counting which counties
(and which states) use an arc. Outer rings and holes keep the source's two windings, so a fill with the default rule leaves a hole empty.
A county is `[fips, name, suffix, label lon, label lat, rings]`: the Census's bare name ("Caddo") with its suffix from the file's list (" Parish"), so a page can say "Caddo Parish" and match the registry's "Caddo". A county the Gazetteer does not list keeps the shape's name, " County" and no label point.

## What it leaves out, and why

- **Falls Church, Virginia** (51610): the source draws it as two arcs of two points, a line with no area, so there is nothing to fill or to point at. It holds no oil.
- **No further simplification.** The source is already generalized for 1:10m (45,000 points for the 3,100 counties), and a coarser tolerance than 30 m collapses the smallest counties and saves under 3%.
- Lakes inside counties are not holes (the Census's cartographic shapes are clipped to the shoreline, not to the lakes), so a county on the Great Lakes ends at the shore.
- 44 two-point arcs in the source are used by more than two rings or twice in the same direction (the corners where counties meet, and a few places where the 1:10m generalization leaves a sliver). The validator accepts them: it asks only that every arc is used by some county.

## Known limits

- A county line is as accurate as 1:10,000,000: about 1 to 2 km. A well on a county line can sit on the wrong side of it, which is why the Map counts a well in the county the registry names and uses its point only for a county name it cannot read (`counties-data.js`).
- Names are the Census's. A name the registry spells another way is matched by `counties-data.js`, not here.

## The county names (2026-11-02)

`d14_county_names.py` writes `site/public/data/county-names.json` (5.9 KB): the 364 counties of Texas (254), Oklahoma (77) and New Mexico (33), keyed by their three-digit code, names without the suffix ("Loving", "Doña Ana"), from `us-counties.json`. The Daily report reads it to name the county of a permit (the permit points carry only the code); the offshore has none. `tests/test_d14_county_names.py` checks it against the outlines and that every county code of the 14,559 committed permit points has a name.
