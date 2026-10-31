# Texas oil & gas leads

An interactive dashboard and map of Texas oil and gas drilling activity, producing operators and the companies that
serve them, built only from public records. It is a static site (HTML, CSS and JavaScript modules, no build step, no
external requests) plus the Python scripts that build its data files.

## What is in it
- **Overview**: a permit map, a market ticker, price, activity, production, jobs and tax charts with the EIA outlook,
  top producers, basin cards and plain-English talking points.
- **Map**: county shading (permits, oil and gas production and change, well depth, oil and gas jobs and wages,
  establishments, mineral value, companies), permit dots, refineries, gas plants, LNG terminals, company ZIP bubbles,
  basin outlines and a time-lapse of permits.
- **Operators** and **Companies**: sortable, filterable tables with CSV export of the public fields.
- **Daily report**: what the Railroad Commission's nightly files held, one report a day for the last 92 days. A simple version
  for the daily look, and a verbose one with permits, the pending queue, completions, image packs and source health.

## Data
All public: Railroad Commission of Texas (drilling permits with coordinates, P-5 operators, Production Data Query dump),
Texas Comptroller (franchise taxpayers, severance-tax revenue, Property Value Study), U.S. EIA (prices, production,
outlook, refinery capacity), BLS (QCEW, state employment), Census (county boundaries, County Business Patterns, ZIP
centroids), EPA facility data and Baker Hughes rig counts (through Internet Archive copies of its public workbooks).
Exact files, vintages and caveats are in `site/DATA_CONTRACT.md`, `site/DATA_CONTRACT_V3.md` and
`site/pipeline/NOTES_*.md`. The Daily report reads the six datasets the RRC lists as nightly or twice daily (permits, pending
applications, completions and three image packs); see `site/pipeline/NOTES_D7.md`.

## Privacy
Only business-, place- and market-level data. No officer names, phone numbers, street addresses or anything about
individuals. Operators are named only when they are corporations, LLCs or limited partnerships.

## Run it
```
python3 -m http.server 8000 --directory site/public
```
Then open http://localhost:8000. Any static host works.

## Rebuild the data
The scripts in `site/pipeline/` (`d1` to `d6`) and `site/build_data.py` write the JSON files in `site/public/data/`
(Python 3, standard library only). Some downloads are large (the RRC production dump is 3.7 GB). `build_data.py` reads
the lead lists `leadpool.csv`, `leadpool_ranked.csv` and `rrc_operators.csv`, which `leadpool.py` and
`rrc_operators.py` generate; they are not committed because they carry contact details from public filings.

The Daily report is built by `site/pipeline/d7_daily.py` (Python 3, standard library only; no lead CSVs needed) into
`site/public/data/daily/`. `.github/workflows/daily-rrc-report.yml` runs it every night, commits the result to `main` and
publishes the site. To fill the archive from the RRC's file history the first time: `python3 -I site/pipeline/d7_daily.py --backfill 91`.

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
- BLS suppresses most small counties, and some series end earlier than others; each figure on the site carries its own date.

Not affiliated with any agency. Public records can be wrong or stale: verify before any outreach. No license has been
chosen yet.
