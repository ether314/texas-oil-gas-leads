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
- The Daily report for New Mexico uses the other date: the approval date of wells in status New (see the next section), which is exact for the last days and weeks.

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

## The Daily report: `d9_nm_daily.py`

Script: `site/pipeline/d9_nm_daily.py` (standard library only, `python3 -I`; two requests a run). Output: `site/public/data/daily-nm/` (`index.json`, one `YYYY-MM-DD.json` per
report day, 92 kept, and `permits-series.json`), the same shapes as Oklahoma's so the Daily report reads them alike.

- **Source:** the MapServer copy of the well layer, `OCDView/API_Export/MapServer/0` (fields `status`, `effective_date`, `last_edited_on`, `county_code`, `type`, `directional_status`,
  `ogrid_name`, `district`). A well in status **New** with `effective_date` on a day is a permit to drill (APD) approved that day. `Wells_Public` has no `effective_date`.
- **One rule, live or rebuilt:** a report shows the newest day before it (within 10 days) on which wells were approved; Monday's report shows Friday's. A report never shows its own day.
- **What a day holds** (`permits`): permits (all are permits for new wells, so `total` = `newDrill`), kinds of well (Oil, Gas, Salt Water Disposal), horizontal / vertical / directional,
  OCD districts, counties (the layer's county code), operators (named by the corporate rule only) and the share of permits that went to named ones. **Not published, so left out
  and never a zero:** filing dates and days to approval, planned depth, amendments, completions, transfers, a pending queue.
- **The inventory** (`wells`, live days only, like Oklahoma's): the server counts the whole layer by status (142,463 records, 54,223 Active on 2026-10-31) and, for the active wells,
  by kind, county code and operator, in four group-by requests (a count the server would cut short is an error, not a smaller number). Only counts are kept: plugged (both kinds), the
  status mix (five largest plus Other, so it adds up), active wells by kind (Oil, Gas, the rest together), by county, the 12 largest named operators, how many operators have an active well,
  and the active wells of unnamed operators and of none. `change` is against the previous live report that had one. If the inventory cannot be read the permits are still a report, marked
  partial (so the backup run takes the night over), and the dataset says why. The groups the server returns are **added, never overwritten** (a county under two spellings is one county; a
  missing status and an empty one are one status), and the four answers must agree: the active wells counted by kind, by county and by operator each have to add up to the active wells (within
  `max(10, 0.5%)`, for an edit between two requests), or one answer was cut short or empty and the inventory is refused, so the report is partial. A county code that is not one of the state's 33 is
  no county (the well is counted, never placed in one), in the permits and in the inventory, so one typo in the layer cannot fail the night's check. A second capture of the same day (a run by hand
  in the morning, the night's run in the evening) that cannot read the inventory keeps the one the first captured, and stays partial so that the backup run tries again.
- **A well is counted once.** The layer holds some wells twice (a record per location: 10 records for 5 wells on 2026-10-29), so the API number is read to count a well once and is
  never kept or published (`validate` fails a file that holds one).
- **The layer is entered late.** The newest two or three days run well under the 17 to 22 permits a business day of the weeks before (5, 5 and 8 on 2026-10-29, -28 and -27 when this was
  written) and fill in later; the layer's newest edit was 2026-10-29 16:31 UTC on Saturday 2026-10-31. A report names the day its permits are from and the layer's newest edit as its
  file time (the page shows "No change since the last report" when the layer has not been edited). The pace chart reads `permits-series.json`, which every run **rewrites from the layer as it
  stands** for the days it read (about 11 days back; older days stay as they were), over the last 122 days, with a day the layer has not caught up with **absent, not zero**.
  The Texas file of the same name has the same shape, so the view's series code takes both. The reports already written settle the same way: each night's run **recounts the permits of every
  earlier report whose permit day it can still see** (`settle_permits`: the day a report shows never moves, only its figures for that day; the inventory, file times and capture time are not
  touched), so the report, the index row (the ribbon) and the chart agree once the layer has caught up, and a report older than the window keeps what it settled at. (Found by an independent
  review: before, every live report kept its first, low count for good, 5 to 15 against 20, and the page compared it with settled days.)
- **Rebuilt days** (`--history`, or `--backfill N` up to 7 missed nights) count only the approvals still in status New, so an old day can have lost a few that were cancelled or moved on;
  they are marked reconstructed. Nothing rebuilt ever overwrites a live report (a rebuilt day's permits are recounted like any other's while it is inside the window).
- `--check` reloads and validates the folder; `--skip-if-captured` is for the backup schedule (exit quietly when the report day was captured live at or after 03:00 UTC the next day).
  If the layer cannot be read (or answers with no approvals) nothing is written and the run exits 1, so the workflow can carry on without it.
- Archive built 2026-10-31 with `--history`: 92 days, 1,338 approvals read.

## Checks

`tests/test_d9_nm.py`: the lag rule (a month enters on the 60th day after it ended, across a year end), what a well becomes (placeholders, repeats, county, box, no depth,
names), the files built from synthetic wells and the validator on them and on faults, the committed files, the EIA series with its validator, and four mutants (everyone or
nobody named, no lag, a lag of 30 days). Run the producer: `python3 -I site/pipeline/d9_nm_monthly.py` (then `--check`). It is not in the nightly workflow yet.

`tests/test_d9_nm_daily.py`: the rules (a well once, the real approval day, which day a report shows, what is named, what is left out), the reports, index rows and dataset states, the
series (rewritten days, kept days, a day past the layer's last edit absent), planning, a county code that is not one of the 33, the inventory's four counts (added not overwritten, refused
when they do not add up), a whole run with the network faked (a first night with history, the next night leaving earlier reports byte for byte as they were when the layer has not changed,
'same' and 'new', the backup guard, a failure writing nothing, a second capture that keeps the first one's inventory), three nights against a layer that is entered late (the earlier reports'
permits settle, the rest of them and a report older than the window do not change), the validator on faults, six mutants and the committed archive.

The nightly `--check` also holds every day file to the privacy gate shared with the other two states (`privacy_check.py`: no e-mail address, web address, phone number or ten-digit number in a day file, and every operator name it publishes passes
`d8_ok_daily.nameable`; `tests/test_privacy_gate.py`), and an error text from the OCD's server reaches a report only through `clean_error` (one short line, no address, markup or path).

## Not available

Permit approvals by date for older months, depth, office city and state, Baker Hughes rig counts and BLS jobs for New Mexico (sources not reached from the build host), a company
list, production by county or operator (the OCD publishes C-115 production by operator and county; not read yet).
