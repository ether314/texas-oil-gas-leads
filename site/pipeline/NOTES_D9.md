# NOTES_D9: New Mexico (producer D9)

Script: `site/pipeline/d9_nm_monthly.py` (standard library only, run with `python3 -I`; about 4 s and 3 requests). It reuses the builder and
validator of `d8_ok_monthly.py` (given New Mexico's own spec) and, for the EIA crude series, `d8_ok_context.py --state NM`. The county outlines
are `site/public/data/counties-nm.geo.json` (33 counties, from the Census file the other two states use: `d9_nm_monthly.py --counties`).

## What the OCD publishes, and what was found (2026-10-31)

New Mexico's regulator is the Oil Conservation Division (OCD) of the Energy, Minerals and Natural Resources Department. Its permitting site
(`wwwapps.emnrd.nm.gov/OCD/OCDPermitting`) sits behind a verification page, which is a person-check and is not scripted here. What is open:

- **The well layer** (ArcGIS feature service `gis.emnrd.nm.gov/arcgis/rest/services/OCDView/Wells_Public/FeatureServer/0`, the "New Mexico OCD Oil and
  Gas Wells" dataset of the OCD Geospatial Hub, "updated daily"). 142,463 wells: API number, well type and status, operator (OGRID and name), OCD district,
  county FIPS code and name, PLSS location, latitude and longitude (NAD83), spud date, measured and true vertical depth, last production date, plug
  date. "A well point is added to this database when an Application Permit to Drill (APD) is submitted and approved."
  The server's directory listing refuses a plain request (403) but the service answers `?f=json` queries, so it is used through those.
- `OCDPUB/OG_Statistics` tables: statewide monthly production by product through the month before last (45-day lag), and yearly counts of
  applications processed (APD "EP Application for Permit to Drill": 711 in 2023, 785 in 2024, 596 in 2025, 592 so far in 2026; these are the ePermitting
  applications only, federal APDs are approved by the BLM).
- An anonymous FTP server (needs FTP, not reachable through this host's HTTPS proxy; not tried) and yearly well statistics workbooks (to 2024).

## Why the files count wells spudded, not permits approved

The three states' other files count permits by approval date. For New Mexico that is not available by date and well:
- The layer has no approval date. Its MapServer copy (`OCDView/API_Export`) has `effective_date`, which for a well still in status New is its original APD
  approval date (a spudded well of 2025 shows 2021), but a well drops out of status New when it is completed or cancelled, so the older the month,
  the more of its approvals are gone (approvals still open: 4,733 in the last 12 months, 3,678 in the 12 before, against 3,591 and 3,495 wells added).
- The layer is archived: a count query with `historicMoment` gives its size at a past date (0 wells on 2022-01-01, 68,432 on 2023-01-01, 81,540 on 2023-10-01 and
  132,797 on 2024-01-01: it was loaded in bulk late in 2023, and grows by about 3,500 a year since). That counts additions per month but cannot say which wells: edits give a well a new object id (3,585 of
  Sept 1's wells have another id now), so ids cannot be compared across dates, and the field statistics ignore the archive.
- **Spud dates are real, dated and complete once they are in** (every well since the 1900s), so wells spudded by month, county and operator is a
  true record of where drilling happens, with its own caveat: **spud dates are reported late**. August 2026 stood at 4 of its 108 on Aug 15, 91 on
  Sep 15, 107 on Oct 15; April 2026 at 33 of 146 on Jun 15, 119 on Jul 15, 146 at the end. A month is therefore in the files only when it ended at least
  `LAG_DAYS` = 60 days ago (about 95% of its dates are in by then), which is why New Mexico ends on 2026-08-31 while Texas and Oklahoma end in September
  and October. The page names the measure and the end date wherever it shows them.
- The Daily report for New Mexico (later) uses the other date: the approval date of wells in status New, which is exact for the last days and weeks.

## What is counted

- A well is one API number (`NN-NNN-NNNNN`) on its spud day; a repeat of the same well and day is skipped; the layer's placeholders for not spudded (year 9999
  and 1900) are not spuds. 13,942 wells since 2018; 1,759 in the 12 months to 2026-08-31 and 1,958 in the 12 before (the 12 months to Aug 2025). Recent months run about 110 to 200 wells.
- **Windows** are the Texas ones (`d1_permits_geo.windows`) ending on 2026-08-31. **Bands** and "new to drilling" as in `NOTES_D8.md` (the first spud ever comes from a server-side
  minimum over the layer, per OGRID).
- **County** is the layer's county code (the FIPS code). **Locations** are the layer's latitude and longitude, rounded to 3 decimals (about 100 m); all of them fall in the state's box.
- **Depth is not published.** The layer carries a depth for 3% of the wells spudded since 2024 (the rest are 0 until completion), so any mean would describe old verticals and
  say nothing of the horizontals that are most of the drilling. County and operator depth are blank, never zero.
- **Operators** are named only by the corporate rule (`d8_ok_daily.nameable`: a corporation, LLC or partnership, never a person's dba), written upper case like the other states'
  rows. 57 operators spudded a well in the last 24 months, all of the last 12 months' wells went to named ones. The layer has no office city or state, so those cells are blank.
  Nothing names a well, a lease or an API number (`--check` fails a file with a long number, an e-mail address or a link).
- Crude oil production: the EIA's New Mexico series (MCRFPNM1, thousand barrels a month; 75,717 for August 2026), refreshed by hand with
  `python3 -I site/pipeline/d8_ok_context.py --state NM`. The OCD's own monthly totals (73.5 million barrels for August) agree within 3%.

## Checks

`tests/test_d9_nm.py`: the lag rule (a month enters on the 60th day after it ended, across a year end), what a well becomes (placeholders, repeats, county, box, no depth,
names), the files built from synthetic wells and the validator on them and on faults, the committed files, the EIA series with its validator, and four mutants (everyone or
nobody named, no lag, a lag of 30 days). Run the producer: `python3 -I site/pipeline/d9_nm_monthly.py` (then `--check`). It is not in the nightly workflow yet.

## Not available

Permit approvals by date for older months, depth, office city and state, Baker Hughes rig counts and BLS jobs for New Mexico (sources not reached from the build host), a company
list, production by county or operator (the OCD publishes C-115 production by operator and county; not read yet).
