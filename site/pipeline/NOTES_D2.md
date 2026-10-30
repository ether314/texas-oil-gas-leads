# D2 notes: counties, labor, ZIP and county company layers

Producer: `site/pipeline/d2_layers.py` (`python3 -I`, stdlib only, re-runnable, deterministic). Writes only
`counties.geo.json`, `county-labor.json`, `zip-companies.json`, `county-companies.json` in `site/public/data/`, and only after
every hard check passes. Flags: `--dl DIR` (download cache, default `dl/` at the repo root, or env `D2_DL_DIR`),
`--out DIR`, `--refresh`, `--strict-zip`, `--counties-source cb|tigerweb`. Downloads are only parsed (zip members are read in
memory, never extracted or run); each file sits in its own folder: `dl/counties_cb2025_5m`, `dl/qcew_2025_211`,
`dl/qcew_2025_213`, `dl/zcta_gaz_2025` (`counties_tigerweb` = fallback test). Folders `counties_cb5m`, `gazetteer_*`,
`qcew_211`, `qcew_213` are early probe copies the script no longer uses.

## Output (bytes / budget)
counties.geo.json 229,260 / 700,000 | county-labor.json 11,469 / 400,000 | zip-companies.json 52,152 / 400,000 |
county-companies.json 9,925 / 400,000. Compact JSON, UTF-8, no trailing newline, schemas exactly as in the contract.

## Sources (all public, no key)
- **Counties**: Census cartographic boundary file GENZ2025 `cb_2025_us_county_5m.zip`
  (https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip, 2.9 MB). Chosen over the TIGERweb layer from the
  lead because TIGER county polygons include coastal water (Galveston is 57% water by area) while this file is clipped to the
  shoreline; it is already generalized (12,110 raw Texas points, 11,933 after 3-decimal rounding), so no extra simplification
  is needed and neighbors keep identical shared borders (sampled 30,000 points: no overlaps). Unsimplified TIGERweb layer 11
  is 10.3 MB (605,010 points). Fallbacks coded and tested: GENZ2024, then TIGERweb State_County layer 11 (Jan 1 2026 vintage,
  `maxAllowableOffset=0.002`, 311 KB, same FIPS and names). NAD83 is treated as WGS84 (about 1 m, below the rounding).
  Winding is RFC 7946 (exterior counter-clockwise); d3-geo wants the opposite, so reverse rings there. There are no holes;
  9 counties are MultiPolygons (coastal islands); the largest polygon comes first.
- **Labor**: BLS QCEW open data, annual averages **2025**, `https://data.bls.gov/cew/data/api/2025/a/industry/211.csv` and
  `.../213.csv` (120 and 209 KB). Rows: own_code 5, area_fips `48xxx` (not 48000, 48999); every county row is agglvl 75. Wage
  is the file's `annual_avg_wkly_wage` (recomputing total wages / employment / 52 differs by up to $75 in small counties
  because employment is rounded); the computed value is the coded fallback. The script falls back to 2024 only on HTTP 404.
- **ZIP centroids**: Census ZCTA Gazetteer 2025 (pipe-delimited, 33,791 ZCTAs; the lead's 2023 file has the same ZCTAs and
  centroids within 0.02 degrees for Texas; the parser handles both delimiters).
- **Companies**: `leadpool_ranked.csv`, Texas rows with fit != deprioritize = 16,508 (matches the site). Only fit, state, zip,
  county_code, city, new_entity and rrc_match are read; `city` only places PO-box ZIPs and is never written.

## Decisions and caveats
1. **county_code is letter-by-letter alphabetical, not FIPS order.** `fips = 2*code - 1` is right for 245 counties but wrong
   for codes 154-162 (Madison, Marion, Martin, Mason, Matagorda, Maverick, McCulloch, McLennan, McMullen: FIPS sorts "Mc" as
   "Mac"). The script sorts the 254 names (letters only, so "La Salle" = "LaSalle") and checks 57 = Dallas, 101 = Harris,
   165 = Midland, 195 = Reeves. Independent test: the county holding each ZIP centroid equals the mapped county for 236 of 245
   codes and for 93.6% of companies (the other 9 codes are tiny samples or ZIPs whose centroid sits across a county line).
2. **county_code 0** (107 Texas rows) does not map and is dropped from `county-companies.json` (they remain in the ZIP
   layer). The file has 245 counties and 16,401 companies; the 9 counties with no companies are absent (absent = 0).
3. **239 ZIPs (1,896 companies, 11.5%) have no ZCTA** (PO-box and unique ZIPs: Midland 79702 = 228 companies, 79710 = 105,
   79708 = 64; Houston 77210 = 76). Following the contract strictly drops them (`--strict-zip`: 1,321 rows, 14,612 companies,
   and Midland County loses 37%: 429 of 1,151). Instead they are placed at the company-weighted mean of the ZCTA centroids of lead-pool
   ZIPs in the same city and county (tier 2: 223 ZIPs, 1,872 companies; city alone when the ZIP's own county_code is 0), or
   the same county (tier 3: 16 ZIPs, 24 companies). Check: 99.9% of the 1,894 companies with a valid county land inside their
   county. Result: 1,560 ZIP rows covering all 16,508 companies. Caveat: the schema has no flag, and ZIPs of one city share a
   point (Midland's PO-box ZIPs all sit at 32.011, -102.078).
4. **Labor is thin because BLS suppresses it**: 129 of 181 NAICS 211 county rows and 111 of 212 NAICS 213 rows carry
   disclosure_code N (null, per contract, although BLS still publishes the establishment count). Counties with data: o = 52,
   s = 101, either = 114 of 254 (all 254 keys are present, nulls inside). Disclosed counties hold 85% of statewide employment
   (o 55,723 of 65,524; s 110,743 of 130,445). Midland: o 265 estabs / 7,612 jobs / $4,531 a week, s 646 / 24,452 / $2,321.
   Reeves: o suppressed (17 establishments), s 31 / 664 / $2,340. Loving: both suppressed; Martin: s only.
5. ZIP rows are sorted by total (then ZIP) with centroids at 3 decimals (more than the contract example, so adjacent
   central-city ZIPs separate). `likely` = fit "likely"; `isNew` = new_entity "Y"; `rrc` = non-empty rrc_match (1,271).
6. Spot check: the biggest ZIP is Houston 77002 (369 companies) and Harris is the top county (3,330, then Dallas 1,747,
   Midland 1,151, Tarrant 926, Travis 786); the Houston-area box holds 26.4% of companies but the top 10 ZIPs are a mix
   (3 Houston, 3 Dallas, 3 Midland, 1 Austin).
7. No person-level data is written: outputs are counts by ZIP and county and BLS aggregates.
