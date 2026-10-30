# D3 notes: series-markets.json and infra.json (as of 2026-10-29)

Producer: `site/pipeline/d3_markets_infra.py`, stdlib only, no keys, re-runnable:
`python3 -I site/pipeline/d3_markets_infra.py [--only markets|infra] [--as-of YYYY-MM-DD] [--dl-root DIR] [--out DIR]`.
Downloads land in `<dl-root>/<name>[-N]/<file>`, one file per new empty folder (default dl-root is `dl/` at the repo root,
override with `--dl-root` or env `D3_DL_ROOT`). Everything is parsed (json, html.parser, zipfile+ElementTree), never run.

## series-markets.json (3,645 bytes)
- Months 2019-01 to 2026-09 (93), identical to `series-permits.json`. Null counts: WTI 0, Henry Hub 0, Texas crude 2
  (2026-08, 2026-09; EIA has published Texas through 2026-07, next release 2026-11-30).
- FRED was unreachable: curl gets an HTTP/2 INTERNAL_ERROR, and HTTP/1.1 curl and Python urllib time out with 0 bytes for
  `fredgraph.csv?id=WTISPLC`, `/data/WTISPLC.txt` and the series page. So the original source is used: EIA public data pages.
  - WTI: `https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=M` (Cushing WTI spot FOB, monthly average, $/bbl).
  - Henry Hub: `https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm` (RNGWHHD, monthly average, $/MMBtu). The LeafHandler form 404s.
  - Texas crude: `...LeafHandler.ashx?n=PET&s=MCRFPTX1&f=M`, thousand barrels per month.
- **`MCRFPTX2` (the id in the brief) is thousand barrels per DAY (about 5,800).** The monthly total is `MCRFPTX1` (150,000 to
  180,000, as expected); the script asserts the page title says "Thousand Barrels" and not "per Day".
- Checks: anchors match known history (WTI 2019-01 51.38, 2020-04 16.55, 2022-06 114.84; Henry Hub 2021-02 5.35, 2022-08
  8.81; Texas dips to 105,545 in 2021-02, winter storm Uri). WTI monthly vs the average of EIA's daily table: max gap 0.063
  over all 93 months, 2025-2026 exact. Latest: WTI 97.31 (2026-09), Henry Hub 2.95 (2026-09), Texas 178,815 (2026-07).
- Caveats: the newest Texas months are EIA estimates and get revised. The 2026 prices (WTI above 90 from March, Henry Hub
  7.72 in January) are as EIA publishes them; only cross-checked against EIA's own daily table.

## infra.json (24,934 bytes: 29 refineries, 208 gas plants, 3 LNG terminals)
- **EIA Energy Atlas layers are not usable.** `services7.arcgis.com/FGr1D95XCGALKXqM/arcgis/rest/services/`
  `Petroleum_Refineries_US_EIA`, `NaturalGas_ProcessingPlants_US_EIA` and `LNG_ImportExportTerminals_US_EIA` all return
  499 "Token Required" (so do the FEMA-hosted copies); the public catalog lists 56 services, none of them facility layers.
  geo.dot.gov mirrors only EIA's pipeline layers. Copies owned by universities or individuals exist but their vintage and
  provenance are unknown, so they were not used. EPA ECHO ignores its NAICS filter (SIC works) and has no capacity.
- **Refineries (cap = bbl/day):** list and capacity from EIA's Refinery Capacity Report `refcap26.xlsx` (EIA-820, operable
  atmospheric crude distillation, per calendar day, as of 2026-01-01): 29 Texas sites, total 6,134,650 bbl/d (the file
  sums to the same). Coordinates from the EPA GHGRP facility table (Envirofacts `PUB_DIM_FACILITY`, Texas, year 2023;
  28 sites matched by city, owner words and the Subpart Y flag). Petromax (not in GHGRP) comes from the EIA Atlas refinery
  layer as republished by NRCan's NACEI service (2017 vintage). `c` is EIA's operating company; the owner label in `n` is
  added only where a city has several refineries.
- **Gas processing plants (cap = null, unit MMcf/day kept for the schema):** EPA GHGRP year 2023 facilities flagged
  Subpart W onshore natural gas processing (`W-PROC`), inside Texas by state, county FIPS 48 and bounding box; `c` is the
  largest owner, shares stripped. No current keyless plant-level capacity exists: EIA's NGQS report RP9
  (`https://www.eia.gov/naturalgas/ngqs/data/report/RP9/data/2017/2017/Name`, 172 Texas plants, no coordinates) stops at
  2017 and NACEI's EIA-757 layer is 2014 (181 Texas plants). A name-plus-county match of the 2017 capacities onto the 2023
  plants worked for about half the plants and showed false positives, so mixed-vintage capacities were not added.
  Some `W-PROC` records are compressor, fractionation or delivery-point sites inside processing complexes.
- **LNG (cap = Bcf/day):** EIA U.S. Liquefaction Capacity File, 3Q 2026 (released 2026-10-01), baseload nameplate capacity of
  trains in service (commercial operation or commissioning): Corpus Christi 3.12 (Cheniere, coordinates GHGRP), Freeport
  1.98 (GHGRP), Golden Pass 0.68 (Train 1 commissioning since 2026-04; coordinates from the NACEI copy of EIA's layer).
  Port Arthur LNG and Rio Grande LNG are under construction with nothing in service and no coordinate source, so skipped.
- NACEI (`geoappext.nrcan.gc.ca`, a Canadian federal service) supplies only 2 coordinates plus a cross-check; drop the
  `nacei_texas` calls to remove it. The cross-check flags Beaumont and Channelview (about 6 km apart) and Premcor (12.6 km:
  the 2017 Atlas point sits at the TotalEnergies site); GHGRP coordinates were kept in every case.
- QA: all 240 items fall inside D2's Texas county polygons; refinery counties match their cities; no contact-like strings;
  owners are all business entities. GHGRP is reporting year 2023 (2024 not yet in Envirofacts), so plants built since are
  missing and a few listed ones may have closed.
