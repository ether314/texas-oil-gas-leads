# D5 notes: county-business.json, series-jobs.json, series-outlook.json (as of 2026-10-30)

Producer: `site/pipeline/d5_federal.py`, stdlib only, no keys, re-runnable:
`python3 -I site/pipeline/d5_federal.py [--only cbp|jobs|outlook] [--reuse] [--fetch-only] [--dl-root DIR] [--out DIR]`.
Downloads land in `<SP>/dl/<name>[-N]/<file>`, one file per new empty folder, parsed with csv / json / zipfile + ElementTree
only. Each document is validated before it replaces a file; the files are then re-read and cross-checked against
independent data (results below). One BLS API request per run (API v1 allows 25 a day); `--reuse` makes none.

## Sources (keyless, User-Agent `Mozilla/5.0 (research script)`, at most 1 request per second)
- CBP 2023 bulk county file `https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23co.zip`, 12,919,520 bytes
  (member `cbp23co.txt`, 1,100,961 rows, 74,769 for Texas). **2023 is the newest vintage:** `cbp24co.zip`, `cbp25co.zip`,
  `cbp26co.zip` and the 2024 folder answer 404, the datasets index stops at 2023, and `api.census.gov/data/2024/cbp` is 404.
  The 2023 API answers data queries "Missing Key", so the API was skipped. Layouts:
  `.../records-layouts/noise-layout/county_layout.txt` and `.../2020_record_layouts/county-layout-2020.txt` (flag meanings).
- BLS public API v1: POST `https://api.bls.gov/publicAPI/v1/timeseries/data/` (startyear 2019, endyear 2026, 6 series ids),
  response 32,597 bytes. The LABSTAT flat files (`download.bls.gov/pub/time.series/sm/`) answer 403 to a generic
  User-Agent, so the API was used. Series id format: `https://www.bls.gov/help/hlpforma.htm` (SM section).
- EIA STEO `https://www.eia.gov/outlooks/steo/xls/STEO_m.xlsx`, 1,098,385 bytes (Last-Modified 2026-10-01).
- Cross-check only: BLS QCEW `https://data.bls.gov/cew/data/api/2025/a/industry/211.csv` (123,063 B) and `.../213.csv`
  (214,767 B), the files behind D2's county-labor.json (Texas statewide private row, area 48000).

## county-business.json (29,111 bytes, 179 counties)
- Codes as in the contract. In the file NAICS is padded with `/` to 6 characters (`211///`, `4247//`, `237120`). Counties with
  a row for each code: 211 106, 213 161, 237120 55, 486 88, 4247 53, 333132 20. Statewide establishments (counties +
  unassigned): 1,898 / 4,608 / 492 / 666 / 646 / 280.
- `estab` is exact. `emp` is mid-March employment **with Census noise infusion** (flags G under 2%: 153 cells, H 2 to 5%: 124,
  J 5% or more: 210). No cell is withheld (no D or S flag among the 487 rows), so `emp` is never null in this vintage.
- `sz`: the Census prints `N` (not available) for a size class with fewer than 3 establishments. No printed Texas cell is
  below 3, and in all 1,100,961 national rows the establishments hidden behind N never exceed 2 per N cell. N is stored as
  0, so sum(sz) can be below `estab` (county cells: 211 hides 265 of 1,872 establishments, 213 hides 443 of 4,579).
- `unassigned` (extra key): county code 999 = county not identified, kept out of `counties` (211: 26 establishments,
  6,027 employees; 213: 29, 25,130; 486: 4, 76; 4247: 7, 120). Statewide total = counties + unassigned.
- Checks: Midland 213 has 583 establishments (QCEW 2025: 646), Reeves 28 (31), Howard 45 (38); top 213 counties Midland,
  Harris, Ector, Montgomery. Over 98 counties in both, CBP/QCEW 213 establishments = 0.94 (median); 211 0.90 (47 counties).
  Statewide establishments are 0.79 of QCEW 2025 for both codes (QCEW is two years newer and counts differently).
- **Caveat, NAICS 211 employment:** CBP statewide 40,697 is 64% of BLS CES March 2023 (63,700) and 62% of QCEW 2025
  statewide (65,524); Harris is 13,226 vs QCEW 33,022. Cause not verified (likely company offices filed under other NAICS
  codes). NAICS 213 agrees (CBP 144,240 vs CES 138,400, QCEW 130,445). Use county-labor.json for employment levels and
  CBP for establishment counts and size mix.

## series-jobs.json (2,616 bytes, 93 months 2019-01 to 2026-09, thousand jobs, NSA)
- `SMU48000001021100001` (NAICS 211) and `SMU48000001021300001` (NAICS 213): SM + U + state 48 + area 00000 + industry
  10211000 / 10213000 + data type 01 (All Employees, thousands). **Not seasonally adjusted:** the SA twins (`SMS...`) return
  "Series does not exist"; BLS publishes SA only for Mining and logging. Extra keys: `asOf`, `latest`, `prelim` (2026-09
  carries BLS footnote P, first print; BLS revises it).
- Checks: 2025 average 65,883 (211) and 130,958 (213) vs QCEW Texas statewide 65,524 and 130,445 (ratios 1.01, 1.00); vs the
  sum of disclosed counties in county-labor.json 55,723 and 110,743 (ratio 1.18, the rest sits in suppressed counties).
  2026-09: 62.6 + 133.8 = 196.4 thousand, 92% of Mining and logging (212.8). Latest values: 62.6 and 133.8.

## series-outlook.json (1,872 bytes, 27 months 2025-10 to 2027-12)
- STEO October 2026, modeling completed 2026-10-01 (`Dates` sheet: Forecast Month, Last Historical Month 202609, per-column
  Historical flags; they agree). `issued` 2026-10, `actualThrough` 2026-09, forecasts 2026-10 to 2027-12 (12 history + 15 forecast
  months). Sheet `1tab` (Table 1), rows found by series id and unit text: WTIPUUS (row 39), NGHHUUS (42), COPRPUS (8),
  NGPRPUS (11). Extra keys: `asOf`, `completed`.
- STEO flags every row as history through 2026-09; survey-based production lags about two months, so the newest
  `usCrude` / `usGas` history months are probably EIA estimates (the workbook does not say which).
- Checks: WTI and Henry Hub for all 57 STEO history months (2022-01 to 2026-09) equal series-markets.json exactly (max
  difference 0.000). Texas field production (series-markets.json) is 41 to 42% of STEO U.S. crude for 2026-05 to 2026-07.
  Forecast: WTI 100.0 in 2026-10 falling to 68.0 in 2027-12; Henry Hub 2.59 to 4.01.

## Skipped or estimated
Nothing is estimated. Skipped: the Census API (key required), the LABSTAT flat files (403), seasonally adjusted BLS series
(not published), CBP 2024 (not yet released; the script tries the as-of year downward, so a re-run picks it up).
