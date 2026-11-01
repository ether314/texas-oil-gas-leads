# Oil tracker

An interactive dashboard and map of oil and gas drilling activity, producing operators and the companies that serve
them, for Texas, Oklahoma, New Mexico and the federal offshore (the Gulf of America), built only from public records. It is a static site (HTML, CSS and JavaScript modules, no
build step, no external requests apart from the document previews described under Privacy) plus the Python scripts that build its data files. (The repository and the live
address keep their first name, `texas-oil-gas-leads`.)

## What is in it
- **States**: a bar above every view but Sources chooses what is shown: all the states (Texas, Oklahoma, New Mexico and the federal offshore), or one
  (on a narrow phone the bar reads TX, OK, NM, Offshore). The choice is kept in the address (`st=ok`; nothing means all) and follows you between those
  views. A view says so when a state cannot give a figure (the others have no company pool, rig counts, jobs, taxes or production by county here).
  Texas and Oklahoma count permits by approval date; New Mexico and the federal offshore publish no approval dates by well, so their figures are wells spudded, named as
  such wherever they show, never added to the permits, and ending two months back because spud dates arrive late (`site/pipeline/NOTES_D9.md`, `NOTES_D10.md`).
  The federal offshore (BSEE, the Gulf's federal waters) is small (about 45 wells a year from 16 operators), is divided into 63 protraction areas where the others have
  counties, publishes no depth, and has no Daily report because its file is weekly.
- **National**: every state agency's drilling permits side by side (`#national`): a tile map of the states you click into, the months stacked by state, a ranking, the kinds of permits
  (new wells, injection and disposal, re-entries, reworks, amendments) where an agency tells them apart, and a table of who is covered and who is not yet. Each agency counts what it
  publishes, permits by approval or issue date or, where no approval dates by well exist, wells by spud date; the two are never added together, a state not read yet is "not available" and never zero,
  and the BLM's onshore permits (federal land, which the states also permit) are a line of their own and never added into the states. Each state is read by its own small producer from the agency's public file or service (Alabama, Arizona, California, Florida, Illinois, Indiana, Kansas, Kentucky, Louisiana, Michigan, Nevada, New York, North Dakota, Oregon, Pennsylvania, South Dakota, Utah, Virginia, West Virginia and Wyoming so far, plus Texas, Oklahoma, New Mexico, the offshore and the BLM; more are added as their sources are checked), run every Monday; a state not read yet says so and why, with the researched grade of its source. See `site/pipeline/NOTES_D11.md`.
- **Permit data**: what each agency's drilling permit captures (`#fields`): the same 48 questions asked of every producing state's permit (and the BLM's and the offshore's): who the operator is, where the well is, how deep and how, the casing,
  cement, H2S, water and pit plans, spacing and ownership, which dates and documents the agency keeps. Each answer says whether the metric is published as data (a field in a downloadable file or API), shown only in a one-well lookup, asked for only on
  the form, not captured, or **not verified** (said so, never guessed), with the evidence named (a real data file, the agency's documentation, the form, a web page). Click a cell, an agency (its form, its open data, a grade from A, bulk data with
  approval dates, to D, nothing public or blocked, and how a monthly count could be built) or a metric. Researched by hand, one file per agency in `site/pipeline/fields/`, built by `d11_fields_build.py`; see `NOTES_D11.md`.
- **Texas images**: what a Texas well leaves behind as scanned filings (`#images`), from the Railroad Commission's three packs a business day: a well's life in three stages (the permit letter and plat, the directional survey,
  the completion forms and logs) with each kind of document explained and counted, how much arrives each day over the 92-day archive (a day with no pack listed is a gap, never zero), and for any day what its packs hold
  (size, size by RRC district, documents by kind for days captured live, the blurred contact sheets, and the permits whose filings are published, each linking to its drill page). It reads only the Daily archive's own files.
- **Overview**: a permit map, a market ticker, price, activity, production, jobs and tax charts with the EIA outlook,
  top producers, basin cards and plain-English talking points. With Oklahoma in, the map, the headline figures, the hot counties, the top
  operators, the insights and the permit and crude charts cover it too, each state in its own color (Texas orange, Oklahoma purple, New Mexico green, the federal offshore rose).
- **Map**: county shading (permits, oil and gas production and change, well depth, oil and gas jobs and wages,
  establishments, mineral value, companies), permit dots, refineries, gas plants, LNG terminals, company ZIP bubbles,
  basin outlines and a time-lapse of permits. It follows the states bar: the shapes, dots (Texas orange, Oklahoma purple, New Mexico green, the offshore rose),
  legend, tooltips and panels are those of the states shown, with each state's county and operator keys in a link (`county=OK:039`,
  `op=NM:7377`). The figures only Texas has (production, jobs, establishments, companies, mineral value, plants, ZIPs, basins) are
  Texas counties only: another state's county (or an offshore area) says "not available", never zero; New Mexico's and the offshore's counts are wells spudded and say so.
- **Operators** and **Companies**: sortable, filterable tables with CSV export of the public fields. Operators follow the states bar: the
  states shown are ranked as one list (by activity band, then new wells), each row tagged with its state, and a state's operators come from
  its own file with the columns only Texas can fill (RRC districts and registrations, production) left out. Companies are the Texas
  Comptroller's records, so they stay Texas only and say so for the other states.
- **Daily report**: what the Railroad Commission of Texas, the Oklahoma Corporation Commission and New Mexico's Oil Conservation Division published overnight, the
  states as one dataset, one report a day for the last 92 days. A simple version for the daily look, and a verbose one. The permits and
  completions of the states are added into one set of figures, one pace chart (the bars stacked by state), one county map, one
  3-month ribbon and calendar and one plain-English summary, and also shown side by side by state wherever the files measure
  different things (Texas and New Mexico know which wells are horizontal, Oklahoma only the planned depth). The states bar narrows the whole
  report to some of them (`#daily?st=tx`, `st=ok`, `st=nm`); an old `#oklahoma` link opens it that way. A day one state has no report for says so and is left out
  of every total, never counted as zero; when the newest report is two or more days behind today's date (Central) the page says so, in case the nightly capture failed. Texas alone adds the pending queue, the image packs (sizes, and for days captured live a count
  of their documents by kind with a sheet of first pages shrunk and blurred so nothing can be read) and a **GPS map** of each day's
  new-drill permits and directional surveys; every point opens a **page with its own URL** (`#daily?d=DAY&drill=PERMIT`) holding the
  well's facts, its coordinates and links to the Railroad Commission's W-1 letter, plat and survey, which the nightly job stores as the
  files of one GitHub release a day. Oklahoma alone adds the wells that changed operator and, for days captured live, the state's well
  inventory. New Mexico's report is its permits to drill, read from the Division's well layer (the Division publishes no daily file): permits by county,
  operator, kind of well, direction and district, and, for days captured live, the state's well inventory (counted by the server, never listed), with no depth,
  filing date, completion or transfer, which it does not publish. A day's report prints (or saves as a PDF) on its own: light, without the header, the controls or the buttons, each card kept whole. The monthly figures card
  shows crude production for the states shown beside the WTI and Henry Hub prices. Source health covers every file of every state.

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

**Widened on 2026-11-01 (the owner's decision): the same Texas documents are now shown, not only linked.** Page one of each W-1 permit letter, permit plat and directional survey is drawn to a readable JPEG
(about 900 px wide, at most about 200 KB; `render_preview` in `site/pipeline/d7_packs.py`) and published beside the document as a file of the same release (`<document>.jpg`, for example `0919696_W1.pdf.jpg`). The Texas images view and each drill page
show these previews inline, with a link to the original. A preview is page one of a document the Commission publishes, readable, and unmodified apart from being rendered to a JPEG: nothing is cropped, blurred or redacted, so it can carry the same names, phone numbers and street addresses
as the document. Completion images and Oklahoma's documents stay unpublished, and there is no contact list. To go back, run the capture with `--no-previews` (the documents stay linked) or remove `--publish-docs`, and delete the release's `.jpg` files.

**The Content-Security-Policy changed with it (2026-11-01).** `img-src` now also allows `https://github.com` and `https://*.githubusercontent.com` (a release download is a redirect to a githubusercontent host), so that those previews load inline. Only `img-src` changed: `default-src 'self'` stays, so
scripts, styles, fonts and data still come from the site itself, and the policy still has no `unsafe-inline`. A visitor's browser asks GitHub for the previews on the page it is looking at (sent with no referrer), and for nothing else.

**A gate before anything is published.** Each Daily producer's `--check` runs in the nightly before the commit: every day file is scanned for an e-mail address, a web address and a phone number (and, for Oklahoma and New Mexico, a run of ten digits, since they publish
no API numbers), and every operator name it publishes must pass the state's rule. A night that fails is dropped, not published (`site/pipeline/privacy_check.py`, `tests/test_privacy_gate.py`, which also scans every published data file).

**What the gate cannot undo.** Before the dba rule existed (fixed 2026-10-31, PR #18) two Oklahoma day files named two sole proprietors ("... DBA ..."). The current files are clean, but the two earlier versions are still readable in the git history of `main` and of `gh-pages`
(`site/public/data/daily-ok/2026-08-26.json` and `2026-10-27.json` as first committed). Removing them needs a rewrite of history, which the rules for this repository forbid without the owner's decision, and a request to GitHub Support to purge cached views and pull-request refs.

## Run it
```
python3 -m http.server 8000 --directory site/public
```
Then open http://localhost:8000. Any static host works.

## Tests
`python3 -I tests/run_all.py` runs the Python tests (pipeline rules, validators, the nightly workflow's own steps), `node tests/smoke.cjs`
loads every view in a real browser at desktop and phone width and `node tests/a11y.cjs` checks text contrast in both themes, keyboard focus and that nothing is cut off at 360 px;
`.github/workflows/ci.yml` runs them on every pull request. See `tests/README.md`.

Every Monday at 06:20 UTC `.github/workflows/refresh-national.yml` runs each state's producer isolated (`site/pipeline/d11_nat_run.py`: a failed producer's file is put back as committed, a server's refusal is an answer and not an error) and rebuilds
`national.json`; `refresh-monthly.yml` rebuilds it too after refreshing Oklahoma's, New Mexico's and the offshore's files.

The national report's files are `site/public/data/nat/<ST>.json` (one per state, written by `site/pipeline/d11_nat_<st>.py`) merged into `national.json` by
`python3 -I site/pipeline/d11_nat_build.py`; `NOTES_D11.md` has the shape and the rules every producer follows.

## A local database
Everything the site publishes can be loaded into one SQLite file you keep on your own machine (standard library only, a few seconds, built from the committed files and never fetched):
`python3 -I site/pipeline/build_db.py` writes `db/oil-tracker.sqlite` (about 13 MB; `db/` and `*.sqlite` are kept out of git), `--check` verifies an existing file. Every data file is stored verbatim in
`documents`, and the main entities are tables you can query and join: jurisdictions, national_months (permits or spuds by state, month and kind of permit), series (prices, crude production, rigs, jobs,
tax), county_permits, operators, permit_points, companies, daily_reports and daily_permits, tx_image_packs and, once the matrix exists, metrics, field_states, field_cells and field_sources. Permits approved
and wells spudded are different measures (`jurisdictions.measure` says which) and nothing in the database adds them. See the top of `site/pipeline/build_db.py`.

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

New Mexico's drilling history (wells spudded by month, county counts, operators and spud points, in the same shapes) is built by
`site/pipeline/d9_nm_monthly.py` from the Oil Conservation Division's public well layer (about 4 s): `python3 -I site/pipeline/d9_nm_monthly.py`; see
`site/pipeline/NOTES_D9.md` for why it counts spuds and not permits.

The federal offshore's drilling history (the Gulf of America's federal waters: wells spudded by month, counts by protraction area, operators and spud points, again in the
same shapes) is built by `site/pipeline/d10_fo_monthly.py` from the Bureau of Safety and Environmental Enforcement's public borehole and company files (4 MB, about 10 s):
`python3 -I site/pipeline/d10_fo_monthly.py`; see `site/pipeline/NOTES_D10.md` (it counts spuds, about 45 wells a year, and publishes no depth).

Oklahoma's permit history (monthly series, county counts, operators and permit points, in the Texas files' shapes) is built by
`site/pipeline/d8_ok_monthly.py` from the OCC's master permit workbook (154 MB, about 75 s): `python3 -I site/pipeline/d8_ok_monthly.py`.

Oklahoma's reports are built the same way by `site/pipeline/d8_ok_daily.py` into `site/public/data/daily-ok/`, and New Mexico's by
`site/pipeline/d9_nm_daily.py` into `site/public/data/daily-nm/` (two requests to the Division's well layer), in the same workflow run,
after the Texas capture. The three captures are isolated from each other: if one fails (the RRC has refused GitHub's runners for hours
at a time, and the OCC and the OCD can have outages of their own), that state's changes are dropped before the commit, the others are
committed, the site is published, and the run then ends red so the failure shows. Each capture also has a time limit of its own (25, 12 and 6 minutes), so
a download that hangs cannot starve the others. A later capture of a day never replaces a report that read more files, and a file that is not the one
expected (an error page, an empty or cut-short inventory) fails its dataset instead of being published. To fill Oklahoma's archive from the OCC's master
files (230 MB, about 2 minutes): `python3 -I site/pipeline/d8_ok_daily.py --history`, or tick `oklahoma_history` when running the
workflow by hand; for New Mexico's, `python3 -I site/pipeline/d9_nm_daily.py --history` or `new_mexico_history`. The monthly cards (Oklahoma
, New Mexico and federal offshore crude production) are refreshed by hand with `python3 -I site/pipeline/d8_ok_context.py [--state NM|FO]` (the EIA's monthly series; one request each).

The permit history of Oklahoma, New Mexico and the federal offshore (the four `*-ok.json`, four `*-nm.json` and four `*-fo.json` files that the Overview, the Map and the Operators
page read) is refreshed once a week by `.github/workflows/refresh-monthly.yml` (Mondays 05:40 UTC, or by hand): New Mexico's in a few seconds, the offshore's from
BSEE's two small zips (BSEE makes its borehole file on Sundays) in about ten, Oklahoma's from the 154 MB master workbook. The three refreshes are isolated like the captures (a failed
one's files are put back as committed, the others go ahead), and the workflow shares the nightly capture's concurrency group, so the two never run at once. The offshore's map of its
63 areas (`counties-fo.geo.json`) is rebuilt by hand, rarely (`d10_fo_monthly.py --areas`). Texas's monthly files are rebuilt by hand.

## Publishing
The live site is GitHub Pages serving the `gh-pages` branch: a copy of the committed `site/public` plus an empty `.nojekyll`
file. Two workflows publish it, with one script (`.github/scripts/publish_pages.sh`: an ordinary push, retried if the other workflow
pushed first): `.github/workflows/publish.yml` runs after CI has passed on a push to `main`, so a merged change goes live in a few
minutes without touching the Railroad Commission or the OCC (it steps aside when main has moved on since the commit CI passed, as the nightly's data commit does: that commit's own publish includes it), and the nightly capture publishes after it commits its data. To publish
`main` as it is now, run "Publish the site" by hand (Actions). To publish without a workflow, replace the branch's contents with
`git archive main site/public` (extracted without the two leading folders), add `.nojekyll`, commit and push.

## Known limits
- Permit dots show only permits with a recorded surface location (about 40% of the last 12 months); counts and trends
  use every permit.
- RRC production is complete only through January 2026 because reports lag.
- The Daily report reads nightly files, but the county, operator and company tables are built from the RRC's monthly files, so the
  two can show permits through different dates. The report's source-health section says when a monthly rebuild is due.
- Oklahoma's part of the Daily report is only the OCC's daily files: about 3 new-drill permits a business day (Texas: about 31), no pending queue or
  image packs, planned depth instead of horizontal (the permit file does not say), transfers for about the last month and the well
  inventory only for days captured live. It has no Oklahoma jobs or rig counts (sources not reachable from the build host), no company
  list and no production by county. Its permit history (series, counties, operators, permit points) is in the Overview, the Operators
  page and the Map.
- New Mexico's part of the Daily report is read from the Division's well layer, which is entered some days after an approval: the newest two or three days
  run low and fill in (the pace chart is rewritten from the layer each night and the earlier reports' permits are recounted), a rebuilt day counts only the approvals still in status New, and the Division
  publishes no planned depth, filing date, completion or transfer by day (`site/pipeline/NOTES_D9.md`).
- The federal offshore is read from BSEE's weekly borehole file: wells spudded (BSEE publishes approvals to drill only as an online query), about 45 a year from 16 operators, so a
  month holds about four wells and the pages lean on the 12-month counts. The series ends 60 days back, a cautious guess: there are no earlier copies of the file to measure how late BSEE's spud
  dates arrive (compare the weekly builds and shorten it if a month keeps growing). It publishes no depth (a total depth exists for a handful of wells), has no Daily report, and its
  areas are BSEE protraction areas, not counties (`site/pipeline/NOTES_D10.md`).
- BLS suppresses most small counties, and some series end earlier than others; each figure on the site carries its own date.

Not affiliated with any agency. Public records can be wrong or stale: verify before any outreach. No license has been
chosen yet.
