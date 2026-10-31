# Texas oil & gas leads

An interactive dashboard and map of Texas oil and gas drilling activity, producing operators and the companies that
serve them, built only from public records, with a daily report for Oklahoma too. It is a static site (HTML, CSS and
JavaScript modules, no build step, no external requests) plus the Python scripts that build its data files.

## What is in it
- **Overview**: a permit map, a market ticker, price, activity, production, jobs and tax charts with the EIA outlook,
  top producers, basin cards and plain-English talking points.
- **Map**: county shading (permits, oil and gas production and change, well depth, oil and gas jobs and wages,
  establishments, mineral value, companies), permit dots, refineries, gas plants, LNG terminals, company ZIP bubbles,
  basin outlines and a time-lapse of permits.
- **Operators** and **Companies**: sortable, filterable tables with CSV export of the public fields.
- **Daily report**: what the Railroad Commission of Texas and the Oklahoma Corporation Commission published overnight, the two states as
  one dataset, one report a day for the last 92 days. A simple version for the daily look, and a verbose one. The permits and
  completions of both states are added into one set of figures, one pace chart (the bars stacked by state), one county map, one
  3-month ribbon and calendar and one plain-English summary, and also shown side by side by state wherever the two files measure
  different things (Texas knows which wells are horizontal, Oklahoma only the planned depth). **Show** narrows the whole report to one
  state (`#daily?st=tx` or `st=ok`); an old `#oklahoma` link opens it that way. A day one state has no report for says so and is left out
  of every total, never counted as zero. Texas alone adds the pending queue, the image packs (sizes, and for days captured live a count
  of their documents by kind with a sheet of first pages shrunk and blurred so nothing can be read) and a **GPS map** of each day's
  new-drill permits and directional surveys; every point opens a **page with its own URL** (`#daily?d=DAY&drill=PERMIT`) holding the
  well's facts, its coordinates and links to the Railroad Commission's W-1 letter, plat and survey, which the nightly job stores as the
  files of one GitHub release a day. Oklahoma alone adds the wells that changed operator and, for days captured live, the state's well
  inventory. The monthly figures card shows crude production for the states shown beside the WTI and Henry Hub prices. Source health
  covers every file of both states.

## Data
All public: Railroad Commission of Texas (drilling permits with coordinates, P-5 operators, Production Data Query dump),
Texas Comptroller (franchise taxpayers, severance-tax revenue, Property Value Study), U.S. EIA (prices, production,
outlook, refinery capacity), BLS (QCEW, state employment), Census (county boundaries, County Business Patterns, ZIP
centroids), EPA facility data and Baker Hughes rig counts (through Internet Archive copies of its public workbooks).
Exact files, vintages and caveats are in `site/DATA_CONTRACT.md`, `site/DATA_CONTRACT_V3.md` and
`site/pipeline/NOTES_*.md`. The Daily report reads the six datasets the RRC lists as nightly or twice daily (permits, pending
applications, completions and three image packs); see `site/pipeline/NOTES_D7.md`. Oklahoma's half of the Daily report reads four files from the
Oklahoma Corporation Commission (intents to drill, completions and well transfers daily; the well inventory nightly), the
Census outlines of Oklahoma's 77 counties and, for its monthly card, EIA's Oklahoma crude oil production beside the oil and gas
prices above; see `site/pipeline/NOTES_D8.md`.

## Privacy
Only business-, place- and market-level data. No officer names, phone numbers, street addresses or anything about
individuals. Operators are named only when they are corporations, LLCs or limited partnerships.

**One deliberate exception (decided 2026-10-31).** The Daily report's drill pages link to the Railroad Commission's scanned
W-1 permit letters, permit plats and directional surveys, published readable and unmodified as GitHub release files. They are
public records, but they can carry the names, phone numbers and street addresses of individuals, and nothing is redacted. This
repository and its site are public. Completion images stay blurred and unpublished. To go back, remove `--publish-docs` from
`.github/workflows/daily-rrc-report.yml` and delete the `daily-*` releases; details are in `site/pipeline/NOTES_D7.md`.

## Run it
```
python3 -m http.server 8000 --directory site/public
```
Then open http://localhost:8000. Any static host works.

## Tests
`python3 -I tests/run_all.py` runs the Python tests (pipeline rules, validators, the nightly workflow's own steps) and `node tests/smoke.cjs`
loads every view in a real browser at desktop and phone width; `.github/workflows/ci.yml` runs both on every pull request. See `tests/README.md`.

## Rebuild the data
The scripts in `site/pipeline/` (`d1` to `d6`) and `site/build_data.py` write the JSON files in `site/public/data/`
(Python 3, standard library only). Some downloads are large (the RRC production dump is 3.7 GB). `build_data.py` reads
the lead lists `leadpool.csv`, `leadpool_ranked.csv` and `rrc_operators.csv`, which `leadpool.py` and
`rrc_operators.py` generate; they are not committed because they carry contact details from public filings.

The Daily report is built by `site/pipeline/d7_daily.py` (Python 3, standard library only; no lead CSVs needed) into
`site/public/data/daily/`. `.github/workflows/daily-rrc-report.yml` runs it every night, commits the result to `main` and
publishes the site. A second schedule an hour later is a backup for a run GitHub skips: it does nothing when the first one
already captured the day. To repair a day that was missed or captured too early, run the workflow by hand (Actions, Daily
reports, Run workflow) and give the day in the `date` box. The Texas workflow step runs with `--publish-docs`, which needs `contents: write` (it has it) for the release files; without that flag
the job publishes only counts and blurred sheets. To fill the archive from the RRC's file history the first time:
`python3 -I site/pipeline/d7_daily.py --backfill 91`.

Oklahoma's reports are built the same way by `site/pipeline/d8_ok_daily.py` into `site/public/data/daily-ok/`, in the same
workflow run, after the Texas capture. The two captures are isolated from each other: if one fails (the RRC has refused GitHub's
runners for hours at a time, and the OCC can have outages of its own), that state's changes are dropped before the commit, the other
state is committed, the site is published, and the run then ends red so the failure shows. To fill its archive from the OCC's master
files (230 MB, about 2 minutes): `python3 -I site/pipeline/d8_ok_daily.py --history`, or tick `oklahoma_history` when running the
workflow by hand. Its monthly card (Oklahoma crude production) is refreshed by hand with `python3 -I site/pipeline/d8_ok_context.py`.

## Publishing
The live site is GitHub Pages serving the `gh-pages` branch: a copy of the committed `site/public` plus an empty `.nojekyll`
file. The nightly workflow refreshes it after each capture with an ordinary push. **A change on `main` alone does not reach
the live site.** To publish by hand, replace the branch's contents with `git archive main site/public` (extracted without
the two leading folders), add `.nojekyll`, commit and push.

## Known limits
- Permit dots show only permits with a recorded surface location (about 40% of the last 12 months); counts and trends
  use every permit.
- RRC production is complete only through January 2026 because reports lag.
- The Daily report reads nightly files, but the county, operator and company tables are built from the RRC's monthly files, so the
  two can show permits through different dates. The report's source-health section says when a monthly rebuild is due.
- Oklahoma's part of the Daily report is only the OCC's daily files: about 3 new-drill permits a business day (Texas: about 31), no pending queue or
  image packs, planned depth instead of horizontal (the permit file does not say), transfers for about the last month and the well
  inventory only for days captured live. It has no Oklahoma jobs or rig counts (sources not reachable from the build host) and does
  not rebuild the monthly tables, operator pages or company lists for Oklahoma.
- BLS suppresses most small counties, and some series end earlier than others; each figure on the site carries its own date.

Not affiliated with any agency. Public records can be wrong or stale: verify before any outreach. No license has been
chosen yet.
