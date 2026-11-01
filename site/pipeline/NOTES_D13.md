# NOTES_D13: the national new-wells map (a GPS point for every new well, from FracFocus)

Scripts: `site/pipeline/d13_newwells.py` (the producer), `site/pipeline/d13_us_outline.py` (the state outlines, run once by hand), `.github/workflows/refresh-newwells.yml` (weekly).
Files: `site/public/data/newwells/summary.json` and `points.json`, `site/public/data/us-states.json`. Tests: `tests/test_d13_newwells.py`, `tests/test_workflow_newwells.py`.
Owner's brief (2026-11-01): "find a place that has the GPS coordinate of every new well and make it super visual", for a national Overview and Daily report that show only what is true for every state.

## Why FracFocus

No agency's permit file gives the location of every new well in every state (the producers read each agency's own file and keep counts only; Texas, Oklahoma, New Mexico and the offshore have their own located-permit files for the Map tab).
FracFocus, the national hydraulic-fracturing disclosure registry, is the one public place that does for the wells that matter: an operator discloses each fractured well with its wellhead's latitude and longitude, its state and county, the day the job
started, the true vertical depth and the water used, and **nearly every new horizontal oil well is fractured**. It is national (17 states have wells in it in the last two years, including Colorado, Montana and Alaska, which the permit report cannot read
yet), public, and refreshed five days a week. The CSV download is one zip (`FracFocusCSV.zip`, 443 MB) whose `DisclosureList_1.csv` has one row per disclosure (252,000 rows, 16 MB compressed); the 15 `FracFocusRegistry_N.csv` files repeat every
ingredient of every job and are never read.

What it is not: not every permit (a permit is the right to drill; a disclosure comes after the well is fractured, weeks to months after the permit), not wells that were never fractured (vertical, conventional, injection and service wells), and not
dated by approval. The National page counts permits by the agencies' approval dates; this counts wells by the day their first frac job started. The two are never added or compared as one figure (Texas: about 5,400 wells in the 12 months to May 2026 against 7,100
permits in the 12 months to September).

## What is read, and how politely

`DisclosureList_1.csv` only, by HTTP range requests (`RangeFile` over `http_range`): the zip's directory at its end, then the member's 16 MB in 17 blocks of 1 MB. The zip is never downloaded whole; a server that answers 200 with the whole body instead of
206 is refused. A 401, 403, 407 or 429 is an answer (`Refused`, exit 2). Run once a week (Tuesdays 07:35 UTC); first real read on 2026-11-01 took 24 seconds and gave files identical to those made from a local copy of the zip. If the registry splits its list into
`DisclosureList_2.csv` and so on, every `DisclosureList_N.csv` is read in order; a list that lacks a column the producer needs is refused (a changed layout must not read as no wells).

## What a "new well" is

The first disclosure of a well, the well being the first ten digits of its API number (a sidetrack shares them; 239,133 wells in 251,953 rows). A re-frac, a second disclosure of the same job, and a sidetrack count once, on the day of the first job (`JobStartDate`). A job dated
before 2011 (the registry began in 2011) or after today is a typing error and is left out (274 rows).

**Disclosures arrive late.** Measured on 2026-11-01: for the busiest states a month is about 94% complete four months later (Texas: May 2026 414 wells against about 440 in a full month, June 366, July 361, August 279, September 186, October 17). So a month is
**settled** only when it ended at least `LAG_DAYS` (120) before the newest job in the file, and the last-12-months figures (and their change on the 12 before) use settled months only: today they end in May 2026. The months after it are published and the pages draw
them lighter, "still filling in", never as a fall.

## What is published

`summary.json` (17 KB): by state, new wells per month from 2011-01 (the registry's start) to the newest job's month, the last 12 settled months and the 12 before, the state's newest job day, the share of wells with a usable point (`located`), the top 15 counties and the top 15 operators
(only those that may be named), `namedShare`, and the median depth (feet) and water (million gallons) of the year's wells; the file's `asOf` (newest job), `settled` (the last settled month's end), `read` (rows) and `wells`.

`points.json` (777 KB, 183 KB gzipped): one row per well of the last 24 months that has a usable point (20,636 on 2026-11-01), as columns of whole numbers: `lat`, `lon` (ten-thousandths of a degree, about 11 m), `d` (days since `t0`, sorted), `s` (index of
the state in `states`, ranked), `c` (index into `counties`, -1 none), `o` (index into `ops`, -1 an operator that may not be named), `tvd` (hundreds of feet), `h2o` (hundreds of thousands of gallons), `f` (1 federal land or minerals, 2 tribal, 3 both). The decoded
rows are the `new_wells` table of the local database.

`points-history.json` (8.2 MB, 2.0 MB gzipped; 220,110 wells on 2026-11-01): the same columns for every located well from 2011-01-01 up to `until`, the January 1 of the year before the newest job's (2025-01-01 today), with county and operator tables of its own and the same state order as `points.json` (so an index means the same state in both). It is **not** loaded with the page: the Overview's "Since 2011" switch fetches it, `newwells-data.js` `mergePoints` joins it to `points.json` (the history's rows from the points file's first day on are dropped: up to 11 months overlap, never a gap, because `until` is never before `points.json`'s `t0`; `validate_pair` refuses a history that ends early) and the explorer is built again over the merged wells. `until` moves once a year and the file has no `asOf`, so it changes only when an old well is corrected (a weekly run that finds none leaves it byte for byte, and git stores a small delta when one changes). Measured on the real registry: 99.8% to 100% of each year's wells have a usable point (2011 to 2024), so the validator holds the history to 90% of the summary's wells before `until` (`HISTORY_MIN`). The same privacy rule and the same validators (no API number, well name, lease, e-mail, web address or phone number; a county of the right state; an operator only if it may be named) apply. `summary.json` now carries 27 states (11 of them with no well in the last 12 months: they stay out of the ranking and the map's selector and are named under "Who is drilling" with their last job).

A point is kept only if it lies in the state the registry gives (`us-states.json`, 0.1 degree of tolerance for the coast and the old datum): on the first real read every one of the 20,636 wells of the last 24 months had a usable point (48 of the 91,758 wells since 2019 did not: a point outside its state), and 17 of them sat just over an edge and were kept by the tolerance. NAD27 positions are
not shifted to NAD83 (the difference is under 100 m, under a pixel at any scale the page draws). A longitude with no minus sign is read as west. A depth outside 500 to 30,000 feet and a water volume outside 1,000 gallons to 150 million are typing errors in the registry
(the extremes there are 1.2 billion feet and 472 million gallons) and are left out of the point, not of the count.

## Privacy

Never read into the output: the API number (it is only the key of a dictionary that lives in the process), the well's name and the lease, the registry's ids. An operator is named only if the shared rule (`d8_ok_daily.nameable`: a corporation, LLC or partnership) says so, or its
name is on `KNOWN_ORGANIZATIONS`, a short reviewed list of companies the rule cannot read because their registered names carry no "Inc" (Pioneer Natural Resources, Occidental Oil and Gas, XTO Energy/ExxonMobil and 32 more, among them the three biggest drillers: without
the list 8,451 of the 32,700 wells since November 2023 would have no operator). A name is added only when it is certain, by hand, and `tests/test_d13_newwells.py` checks that none is a trust, an estate or a dba. The registry does list people ("Clay Hamilton",
"Gregory W. Stone"): they are never named. A well's point is a place (the position of an industrial site, 11 m) published to the same precision as the Map tab's permit dots. A county is a place. The validators refuse an e-mail address, a web address, a phone
number and a run of ten digits in either file.

## The outlines

`us-states.json` (152 KB, 45 KB gzipped): the 49 states that can hold oil (the lower 48 and Alaska), the outer ring of each piece, simplified to about 1.3 km and rounded to two decimals, from the U.S. Census Bureau's cartographic boundary files (1:10m, public domain) as packaged in
`us-atlas` 3.0.1. Made once by `d13_us_outline.py` from that package's `states-10m.json` (`npm pack us-atlas@3.0.1`); not part of any workflow. The producer uses it to check points; the pages draw it.

## The run

```
python3 -I site/pipeline/d13_newwells.py              # read FracFocus (range requests), validate, write both files
python3 -I site/pipeline/d13_newwells.py --file PATH  # a local FracFocusCSV.zip or DisclosureList csv instead of the network
python3 -I site/pipeline/d13_newwells.py --check      # reload and validate what is committed
python3 -I tests/run_all.py d13                       # the tests
```

A run refuses to write (exit 1, the committed files stay) when the registry looks cut short: under 90% of the committed file's wells in the last 24 months or rows read (`--guard-floor 0` for a deliberate reset), fewer than 3,000 wells in the last 12 months, any validator fault.
A refusal by the server is exit 2, an answer. The same registry read again writes nothing, so a weekly run commits only when the registry has changed.

## Known limits

- Only fractured wells. A state whose wells are mostly not fractured (Alabama, Mississippi, Kansas, Illinois, Michigan, California, New York) has few or none in the registry (Alabama's last job is November 2023): the pages list the producing states with no new well in the last 12 months, as "none in the registry", not as zero permits.
- Wells fractured before a state required disclosure, or whose first disclosure was filed under another API number, can read as new once.
- FracFocus operator names are the names operators submit: one company can appear under two spellings (the summary groups by upper-case text; a merger changes the name).
- `LAG_DAYS` is one number for every state; Texas is about 94% complete at four months, some small states less. The newest months of a small state are noisy by nature.

## The whole registry in the local database (2026-11-01)

The site publishes every well with a point since 2011 (the last 24 months in `points.json`, the rest in `points-history.json`) and monthly counts since 2011, but no API number, well name or lease; the owner's local SQLite database (`build_db.py`) can hold the whole registry, through `ff_db.py`: `python3 -I site/pipeline/build_db.py --fracfocus [--chemicals] [--fracfocus-zip PATH | --fracfocus-download DIR]`. Tables: `ff_disclosures` (all 251,953 rows of the disclosure list,
23 columns, nothing dropped: 274 rows have no usable job date and are marked `date_ok = 0`, their text kept), `ff_water_sources` (25,878), and with `--chemicals` `ff_ingredients` (about 7 million rows from the 15 `FracFocusRegistry_N.csv` files; the header columns they repeat live in `ff_disclosures`). `is_first` is the definition above, so on the same registry `v_ff_new_wells` has
the same 239,133 wells as `summary.json` and `v_ff_new_wells_by_month` agrees with every one of its 2,068 state-months (checked on 2026-11-01). The disclosure list and water sources come by range requests (19 MB), or from a local copy of the zip; the ingredients need the whole zip, which `--fracfocus-download` fetches once into a new folder (one request, resumed once, never
retried in a loop). Built on 2026-11-01: 12 seconds without ingredients (121 MB file), a few minutes with them (about 2.5 GB).

**What is committed, by the owner's decision (2026-11-01).** These tables carry API numbers, well names and operators that are people ("Clay Hamilton"), which the site never publishes. The owner chose, over a cleaned copy and over keeping it local, to commit the full file: `db/oil-tracker.sqlite.gz` (42.6 MiB: gzip level 9 with no timestamp, so the same database gives the same bytes), the database as `build_db.py --fracfocus` makes it, without the ingredients (2.45 GB).
It is outside `site/public` (the publish copies only that folder), `.gitignore` has one exception for it and still ignores the uncompressed file and the rest of `db/`, and the site's own files still hold no API number (tested). It is public and permanent in git history; each new version adds about 43 MB, so it is a snapshot to refresh by hand. `ff_db.ensure_local_only` still refuses to write the tables under `site/` or to a name git would track; `tests/test_build_db_fracfocus.py` pins the guard, the `.gitignore` exception and the committed file.
