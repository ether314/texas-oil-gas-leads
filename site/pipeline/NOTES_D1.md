# NOTES_D1: permit data layers (producer D1)

Script: `site/pipeline/d1_permits_geo.py` (stdlib only, about 6 s, deterministic; run `python3 -I site/pipeline/d1_permits_geo.py`).
Files in `site/public/data/`: `county-permits.json` 50 KB, `operator-extras.json` 40 KB, `series-permits.json` 2 KB,
`permits.json` 316 KB (budgets 400 / 400 / 400 / 1500 KB). Latest issue date in the permit file: 2026-10-07 (file
refreshed 2026-10-08); as-of 2026-10-29.

## Read this first (UI)

1. **`permits.json` is not a census of recent permits.** The RRC publishes surface coordinates for only part of the
   permits. Last 24 months: 9,404 of 13,403 new-drill permits located (70.2%); last 12 months: 2,698 of 6,686 (40.4%).
   Permits / located, by issue month:

   | 2024-10* 62/62 | 2024-11 562/562 | 2024-12 576/576 | 2025-01 592/592 | 2025-02 552/548 | 2025-03 603/601 |
   |---|---|---|---|---|---|
   | 2025-04 655/654 | 2025-05 492/492 | 2025-06 494/493 | 2025-07 576/575 | 2025-08 479/478 | 2025-09 508/507 |
   | 2025-10 642/641 | 2025-11 364/364 | 2025-12 463/463 | **2026-01 670/171** | 2026-02 500/497 | 2026-03 623/612 |
   | **2026-04 660/28** | **2026-05 651/50** | **2026-06 681/34** | **2026-07 611/99** | **2026-08 594/232** | **2026-09 682/67** |

   (*only 29-31 Oct 2024 are in the window; 2026-10, days 1-7: 111/6.) Coverage is 98-100% for Oct 2024 to Dec 2025
   and Feb-Mar 2026, but 4-39% for Jan 2026 and Apr-Oct 2026. The located recent subset is **biased**: it depends on the
   operator (since 2026-04-01: Pioneer 8 of 381, Diamondback 6 of 239, DE Central 0 of 112, Apache 0 of 88; 236 of 355
   operators have no located permit) and the busiest counties have almost none (Midland 0 of 365, Reeves 0 of 265,
   Upton 0 of 207, Martin 1 of 294). So: take every count, trend and ranking from `county-permits.json` and
   `series-permits.json`, never from the dots; do not animate or chart the points by month (recent months look
   artificially quiet); label the layer "permits with an RRC-published location" and show the coverage
   (`pts.length` against the sum of the monthly counts); a "last 12 months" hero of dots is thin for Apr-Oct 2026.
2. `operator-extras.json` rows for operators whose last-24-month permits are all offshore (2 rows) have `fips` "" and
   `counties` 0: show "n/a", do not look the code up.
3. `p12` is a day window (issued 2025-10-29 or later), `m` are calendar months through 2026-09, so the last 12 values
   of `m` do not add up to `p12` (Midland 659 vs 616). That follows the contract.
4. Points are sorted by issue day (the last 12 months are one contiguous tail), then south to north.
5. `permits.json` ends with a `coverage` block: `months` (the 24 of operator-extras), `total` (all new-drill permits per calendar month, any operator), `located` (those in `pts`), `share12` 0.404 and `share24` 0.702 (located/total over the day windows of the points, so they include 2026-10 so far); `located[0]` counts only 29-31 Oct 2024 (window start), so 2024-10 looks about 10% by construction.

## Sources and what was downloaded

- `daf802.txt.gz` (already in the project): counts, series, operators.
- Coordinates: "Drilling Permit Master and Trailer (Includes Latitudes and Longitudes)". **Neither RRC share holds a
  single `.gz`.** Both hold plain-text `daf420.dat*` snapshots of 2-4 MB: the End of Month share has 110 month-end
  files (2017-06 to 2026-09) and the daily share has 3,277 daily snapshots (they behave like month to date). Each file
  lists the permits touched that month (new and changed), with record 14 (surface location) and 15 (bottom hole). I took what the 24-month
  window needs: 23 month-end files (10-31-2024 to 09-30-2026; `05-31-2025` is not in the share), the daily
  `daf420.dat.06-02-2025` (holds the whole of May 2025; found via the share's AJAX paging) and the current daily
  `daf420.dat` (2026-10-29, month to date). 25 files, 61,686,395 bytes, far under the 400 MB cap. Sizes match the
  listings; they are plain text, so `gzip -t` does not apply (block count = 02-record count = 22,093 instead).
- Layout manual `oga049m` (fetched from the URL in the brief): type 14 is "longitude latitude" in decimal degrees,
  **NAD27**. Not converted to WGS84 (a shift of tens of meters, below the 0.0001 degree step used here). Type 14 comes
  in four spacing variants (`14-102.7..`, `14 -95.4..`, `14: -95.4..`); one regex reads them all.
- `rrc_operators.csv`: exact CSV name strings, and the nameable gate.

## Rules implemented

- New-drill permit = first `02` record per permit number among records with a valid issue date (identical to
  `rrc_operators.py`), application type 01. 2,896 of the 13,403 last-24-month permits are represented by an amendment
  record (sequence below 99); only 2 of those differ from the original in issue date, none would change a window, and 4
  type-01 originals are skipped because their first record has another type.
- Windows: last 12 months = issued >= 2025-10-29; prior 12 = 2024-10-29 up to 2025-10-29; no upper bound. `m`, `m24`
  and the series use calendar months and stop at 2026-09.
- `spud12` = the operator's type-01 permits, any issue date, with spud date in 2025-10-29..2026-10-29.
- Depth: county = mean of positive total depths of p12 permits (null if none); operator = same over the last 24 months
  (0 if none); points = round(ft/100), at least 1 when a depth is reported.
- County codes are FIPS: top 5 by p12 are Midland 616, Martin 460, Reeves 430, Upton 424, Loving 386; 99.5% of points
  fall inside their own county polygon in `counties.geo.json`. Seven last-24-month permits carry offshore area codes
  (600-713): counted in the series and operator totals, left out of counties and points (county p12 sum 6,680 vs 6,686
  statewide).
- Naming: only CSV operators with `org_type` corporation, LLC or limited partnership (5,150 of 5,938). Operators absent
  from the CSV (not active P-5) hold 1,258 of the 6,686 12-month permits (for example numbers 253162 and 109333, both
  large drillers); they are counted, never named (`op` -1).
- Coordinates: latest snapshot with a valid type-14 record inside lat 25.5..36.6, lon -106.8..-93.4 wins (275 permits
  changed between snapshots). `ops`/`opNums` list only named operators that have points, by point count.
- JSON is UTF-8, compact, no trailing newline, written atomically; a re-run gives identical bytes.

## Checks (all pass)

1. 12-month counts vs `rrc_operators.csv`: 5,938 operators, 0 mismatches, top 20 identical (665748 641, 217012 471).
2. Separate recount code: all 206 counties (p12, p12prev, 36 months), all 504 operator rows (prev12, spud12, m24,
   counties, depth) and the series: 0 mismatches. Points: bounds lat 26.09..36.36, lon -104.42..-93.58.
3. Reload and schema check of every file runs inside the script (CHECK 5).

Refresh: fetch new month-end files with `rrc_fetch.py` (GUID f5dfea9c-bb39-4a5e-a44e-fb522e088cba) into new
`<dl>/ll_*` folders, refresh daf802, then re-run (`--dl` points at the folder holding them).
