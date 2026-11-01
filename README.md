# Oil tracker

An interactive dashboard and map of oil and gas drilling activity, producing operators and the companies that serve
them, for Texas, Oklahoma, New Mexico and the federal offshore (the Gulf of America), built only from public records. It is a static site (HTML, CSS and JavaScript modules, no
build step, no external requests apart from the document previews described under Privacy) plus the Python scripts that build its data files. (The repository and the live
address keep their first name, `texas-oil-gas-leads`.)

## What is in it
- **States**: there is no states bar any more (the Overview is national, and Operators and Companies are one page with a State filter of their own). The four jurisdictions with files of their own differ:
  Texas and Oklahoma count permits by approval date; New Mexico and the federal offshore publish no approval dates by well, so their figures are wells spudded, named as
  such wherever they show, never added to the permits, and ending two months back because spud dates arrive late (`site/pipeline/NOTES_D9.md`, `NOTES_D10.md`).
  The federal offshore (BSEE, the Gulf's federal waters) is small (about 45 wells a year from 16 operators), is divided into 63 protraction areas where the others have
  counties and publishes no depth.
- **Permit data**: what each agency's drilling permit captures (`#fields`): the same 52 questions asked of every producing state's permit (and the BLM's and the offshore's): who the operator is, where the well is, how deep and how, the casing,
  cement, H2S, water and pit plans, spacing and ownership, which dates and documents the agency keeps. Each answer says whether the metric is published as data (a field in a downloadable file or API), shown only in a one-well lookup, asked for only on
  the form, not captured, or **not verified** (said so, never guessed), with the evidence named (a real data file, the agency's documentation, the form, a web page). Click a cell, an agency (its form, its open data, a grade from A, bulk data with
  approval dates, to D, nothing public or blocked, and how a monthly count could be built) or a metric. Researched by hand, one file per agency in `site/pipeline/fields/`, built by `d11_fields_build.py`; see `NOTES_D11.md`.
  **FracFocus** (the national registry of fracturing jobs) is the matrix's first column, answered the same way about what a *disclosure* captures (a disclosure is filed after the job, so it is not a permit and is never counted as one of the 35 agencies), and a card below
  lists every field in its download (34 columns of three kinds of file: the well, the job's dates and depth, the water and every chemical) in plain words, each tied to the permit metric it matches and how many agencies publish that metric as data. The registry's water, depth and
  chemicals are what almost no agency publishes as data: a group of four questions ("The fracturing job": the job's dates, the chemicals, the additives, the amount of each ingredient) asks all 35 agencies, and **29 of 35 require or show the chemical list but none publishes it as data** (8 show it per well, 21 only require it, mostly by sending operators to FracFocus; 17 of the 140 answers are not verified). The site shows none of its API numbers, well names or chemical lists (Privacy).
- **Texas images**: **find a well by its API number** (or choose a county) and read every scanned document the Railroad Commission filed about it: the permit letter and plat, the directional survey, the completion forms and logs,
  each tied to its well, shown as a readable picture of page one and downloadable whole, exactly as filed (`#images?well=28337830`, `#images?c=283`; built by `site/pipeline/d12_wells.py`, `NOTES_D12.md`). Below it, what a Texas well leaves behind as scanned filings, from the Commission's three packs a business day: a well's life in three stages (the permit letter and plat, the directional survey,
  the completion forms and logs) with each kind of document explained and counted, how much arrives each day over the 92-day archive (a day with no pack listed is a gap, never zero), and for any day what its packs hold
  (size, size by RRC district, documents by kind for days captured live, the blurred contact sheets, and the permits whose filings are published, each linking to its drill page). It reads only the Daily archive's own files.
- **Overview** (`#overview`): oil permits and fractured wells, side by side, for the whole country, on one page. It is the old Overview, National report and Map in one tab, and it uses only what exists for every state: each state agency's own count of its oil permits (`data/national.json`, 33 jurisdictions) and the FracFocus registry's one GPS point for every fractured well in every state that reports to it (`data/newwells/`). Every visual carries both, marked the same way: a **hollow ring** (an outlined bar, a line) is a state agency's oil permits, a **filled dot** (a filled bar) is a fractured well. The two are never added: a permit is the right to drill and a fracturing job comes after it.
  - **The map**: every well fractured in the last 24 months as a glowing dot where it sits (the hero and the explorer), and one ring for each state agency, its area the agency's count of oil permits in its last 12 months (a dashed ring counts wells spudded, for the agencies that publish no approval dates; a dotted one something counted another way). A switch shows both layers or either (`#overview?k=wells`, `#overview?k=permits`); hover a dot for its county, first job, operator (only a corporation, LLC or partnership), depth and water, hover a state or ring for both counts; click a state (or choose it in the key, the selector, the ranking or the coverage table) to zoom in. Its panel gives the agency's figures and the registry's one block each (the last 12 months, the change on the 12 before from a base of 20 or more, a two-line chart of both over 36 months, the kinds of permits where the agency tells them apart, oil or gas where it records the fluid, depth, water and federal or tribal land, and links to the agency's source, the permit-data matrix and FracFocus). "Since 2011" (or `#overview?y=all`) draws every well in the registry that has a point (about 239,000 in 16 years: the earlier ones, 2 MB, are fetched only then) with its own replay of the fractured wells; the rings stay the agencies' last 12 months. `#overview?s=TX` opens it zoomed to a state.
  - **Below it**: the states ranked (one row each with both counts, sortable by either), every month since 2019 with the agencies' permit counts as lines over the registry's wells as bars stacked by state (the newest months of wells are drawn lighter: wells are disclosed weeks late, so a month settles only 120 days after the newest job and the 12-month figures use settled months only), the busiest counties and the top operators (both sources in each, for the country or the state chosen), a table of who is covered and who is not yet (the agency behind each count, how far it runs, how often it updates, and the registry's wells), and when each source was current.
  - **Honesty**: each agency counts what it publishes, permits by approval or issue date or, where no approval dates by well exist, wells by spud date, and the two are never added; a state not read yet is "not available", a state with no well in the registry is "not in the registry" and one that dates nothing in two years is "none recorded", never zero; the BLM's onshore permits (federal land, which the states also permit) are a line of their own and never added into the states or drawn as a ring. Each state is read by its own small producer from the agency's public file or service (all 29 state producers and the BLM's, run every Monday; Missouri has no current public permit list and says so), `site/pipeline/NOTES_D11.md`; the registry is read daily, `NOTES_D13.md`. It does not follow the states bar. The old `#national` and `#map` addresses open it (on the state they named); the Map's Texas-only layers (county shading by production, jobs and establishments, refineries, plants, company ZIPs, basins) are not on the site any more, and the Daily report keeps the oil permits and spuds one by one, with their locations, as rings on its own map.
- **Companies** (`#companies`): one page, national, with a switch between two sortable, filterable lists with CSV export of the public fields (`companies.js`, `tables.js`,
  the pure data code in `companies-data.js`). **Operators** is every operator the state agencies name, ranked as one list (by activity band, then new wells in the last 12 months),
  each row tagged with its state, with a State filter inside the table (`#companies?s=ND`) instead of the states bar. Texas, Oklahoma, New Mexico and the federal offshore list every
  operator with a recent permit or spud, with the columns only a full file can fill (trend, 24 months, depth, top county, and for Texas RRC districts, registrations and production); for
  the other states it is the 15 busiest operators the agencies' files name (`national.json`), with those columns blank, never zero. A state that counts wells spudded (New Mexico,
  North Dakota, Colorado, the federal offshore) or drilled (Virginia) says so beside the number and is never added to the permit counts; a state that names no operator (Arizona, Florida,
  Nevada, Oregon, South Dakota) is named in the page's note. **Texas directory** is the Comptroller's oil and gas companies with RRC activity where a name matched: Texas only, and says
  so, because no other state publishes a bulk list like it. The address is `#companies` or `#companies?kind=directory`; the old `#operators` and `#companies` addresses are translated
  (`#operators?st=ok` opens `#companies?s=OK`; an old `#companies?county=` opens the directory).
- **Daily report**: the new wells of one day, nationwide (`#daily`, `#daily?d=2026-08-12&s=TX`), from the same FracFocus data as the Overview and with only what every state can give. Choose a day (the arrows, a slider over the 150 days of the chart, a date box or an address back to January 2011, or a bar of the
  chart, or a month on the strip above the chart, one bar for every month since 2011 with the chart's days marked as a band: one click opens the month; "Earlier" and "Later" page the chart and the day 150 days at a time, and the first day before the last two years fetches the earlier wells, 2 MB) and see that day's wells glow on the map with the two weeks before it dimmer, how many there were against a typical day, which states they are in, **what the day's wells look like** (a card of six panels, each a fact every state's disclosures carry for every well, set against the typical well of the twelve months the day sits in: the counties with the most wells, the wells a pad (wells fractured the same day within 150 m of each other count as one pad, and the busiest spot, 10 miles across), the depth (median, deepest, wells by depth band), the water (the day's total, in Olympic swimming pools, and the median well), the share on federal or tribal land and the operators that may be named; a depth or water volume a well does not report is counted over the wells that do and says how many, never as zero) and every well in a table (state, county, operator when it may be named, depth, water, land): the table is the map's twin. **Oil permits ride on the same map** (2026-11-01): the agencies' dated records that have a point, the files the Map tab reads (`permits.json` for Texas, `permits-ok`, `permits-nm`, `permits-fo`), are drawn as hollow rings in the state's color beside the filled glowing dots of the fracked wells, with a legend and a switch (Both, Fracked wells, Oil permits, `k=wells` or `k=permits` in the address); the panel counts both, the table gets a Kind column, and a ring's hover names what it is, its state, day and operator (only when it may be named). Texas and Oklahoma count permits approved, New Mexico and the federal offshore wells spudded (their regulators publish no approval date by well), and the page says which; only about 40% of Texas's permits of the last year have a point, and no other state publishes one, so a day before the records start (Sep 2024) or a state with none reads "not available", never none. The rings are only the records that have a map location, so the summary also says how many new-drill permits Texas, Oklahoma and New Mexico approved that day in all (the only three that publish a list every day; the nightly captures' permit series for Texas and New Mexico since August 1, 2026, and Oklahoma's from its permit points, which hold every Oklahoma permit: `oil-day-data.js`), and the chart draws them as a line of rings beside the bars, on the same scale, following the same switch. They are never added to the fracked wells; a day before August 1, 2026 says the count of every permit starts then and draws no line (never zeros), and a state that publishes no daily list has none. The month strip counts fracked wells only. The chart stacks 150 days by state (the newest 150, or the 150 that hold the chosen day) with a
  dashed line for a typical day (over the 12 months the day sits in: a day in 2014 is set against 2014, not against last year); the newest days are drawn lighter and called "still filling in", because operators disclose weeks to months after a job, and a day still filling in is never called slow. The page opens on the newest day with ten or more wells, a state can be chosen (the map zooms, the table and chart follow),
  a day with no well says none, and a freshness table gives each state's newest well and how far it is behind. It does not follow the states bar. The Texas, Oklahoma and New Mexico nightly captures (`d7_*`, `d8_*`, `d9_*`) keep running as the archive behind the Texas images page and the well finder, and their day files stay published,
  but their pages (the permit queue, completions, transfers, well inventories, pace charts and the drill pages that linked each Texas permit's W-1 documents) are no longer in the Daily report: only those states publish them. A permit's documents are on the Texas images page, found by API number.

## Data
All public: Railroad Commission of Texas (drilling permits with coordinates, P-5 operators, Production Data Query dump),
Texas Comptroller (franchise taxpayers, severance-tax revenue, Property Value Study), U.S. EIA (prices, production,
outlook, refinery capacity), BLS (QCEW, state employment), Census (county boundaries, County Business Patterns, ZIP
centroids), EPA facility data and Baker Hughes rig counts (through Internet Archive copies of its public workbooks).
Exact files, vintages and caveats are in `site/DATA_CONTRACT.md`, `site/DATA_CONTRACT_V3.md` and
`site/pipeline/NOTES_*.md`. The nightly Texas capture (the archive behind the Texas images page) reads the six datasets the RRC lists as nightly or twice daily (permits, pending
applications, completions and three image packs); see `site/pipeline/NOTES_D7.md`; the packs' documents themselves, tied to wells, are `site/pipeline/NOTES_D12.md`. Oklahoma's nightly capture reads four files from the
Oklahoma Corporation Commission (intents to drill, completions and well transfers daily; the well inventory nightly), the
Census outlines of Oklahoma's 77 counties and, for its monthly card, EIA's Oklahoma crude oil production beside the oil and gas
prices above; see `site/pipeline/NOTES_D8.md`.

The national new-wells map reads the FracFocus registry (the national hydraulic-fracturing disclosure list, public, refreshed five days a week): one disclosure per fractured well, with its wellhead's latitude and longitude, state, county, the day the job started, depth, water
and operator. It is the one public place with a GPS point for every new (fractured) well in every state that reports to it, 17 of them in the last two years. `site/pipeline/d13_newwells.py` fetches only the registry's disclosure list (16 MB of a 443 MB zip, by range requests) every day
(`.github/workflows/refresh-newwells.yml`) and writes `site/public/data/newwells/`, comparing each download with the list of wells kept from the last one (in GitHub's Actions cache, never committed) to log the wells that are new, apart from those a Texas daily report had already carried (`arrivals.json`, counts only; Oklahoma's and New Mexico's daily reports list no wells, so they cannot be matched); a well counts once, on the day of its first job, and a month counts as settled only 120 days after the newest job because disclosures arrive late. The outlines of the states
(`site/public/data/us-states.json`) are the Census Bureau's 1:10m cartographic boundary files (public domain). See `site/pipeline/NOTES_D13.md`.

## Privacy
Only business-, place- and market-level data. No officer names, phone numbers, street addresses or anything about
individuals. Operators are named only when they are corporations, LLCs or limited partnerships.

**Deliberate exceptions (decided by the owner on 2026-10-31 and 2026-11-01).** The Railroad Commission's scanned filings are public records, but they can carry the names, phone numbers and street addresses of individuals (a landowner on a plat,
an operator's contact on a completion form). This repository and its site are public, and two things publish those scans **readable and unmodified, nothing redacted**, as files of GitHub releases:
1. the nightly capture publishes the day's W-1 permit letters, plats and directional surveys, which the Texas images page shows (`--publish-docs` in `.github/workflows/daily-rrc-report.yml`, releases `daily-YYYY-MM-DD`);
2. **every document of the Commission's three image packs, completion images included, is published under the well (API number) it is about** on the Texas images page, each with a picture of its first page
   (`.github/workflows/well-images.yml`, `site/pipeline/d12_wells.py`, releases `wells-YYYY-MM-DD-<pack>-NN`; about 0.9 GB a day, kept for 92 days). The page loads those pictures from GitHub's image hosts, which the
   Content-Security-Policy allows for `img-src` and nothing else.

The data files beside them stay at the business and place level: a well is its API number, county, district, field and operator (named only when it is a corporation, LLC or limited partnership); **lease names, well numbers and landowner names are not
read into any data file and no file name from a pack is used** (names are made up). Oklahoma's documents and any contact list are never published. To go back: remove `--publish-docs` and delete the `daily-*` releases, and disable `well-images.yml` and delete
the `wells-*` releases; details are in `site/pipeline/NOTES_D7.md` and `NOTES_D12.md`. To take one document down, delete its release file and its entry in `site/public/data/wells/county/<fips>.json`.
The Commission has no address that opens a single document (its look-up pages need a session and an internal document number), which is why the files are kept here; each well page links its look-up forms.

**A third exception (the owner's decision of 2026-11-01): the whole FracFocus registry is committed, with its identifiers.** `db/oil-tracker.sqlite.gz` (a snapshot of the local database, 42.6 MiB) holds every FracFocus disclosure with the API number, the well's name, and the operator exactly as FracFocus publishes them, which includes operators that are people, and
the registry's water sources. The data is public (the registry's own download), but this repository and its site are public too, so the snapshot is public and permanent: git history is not rewritten without the owner's decision, and a copy or fork cannot be recalled. It is not on the site (`site/public` holds none of it and still carries no API number, well name or lease; a test pins that). The site's own FracFocus files stay as
described above (`data/newwells/`: positions to 11 m, operators named only when they may be). To go back: delete `db/oil-tracker.sqlite.gz`, restore `db/` in `.gitignore`, and ask GitHub Support to purge cached views; the file stays readable in earlier commits.

**Widened on 2026-11-01 (the owner's decision): the same Texas documents are now shown, not only linked.** Page one of each W-1 permit letter, permit plat and directional survey is drawn to a readable JPEG
(about 900 px wide, at most about 200 KB; `render_preview` in `site/pipeline/d7_packs.py`) and published beside the document as a file of the same release (`<document>.jpg`, for example `0919696_W1.pdf.jpg`). The Texas images view and each drill page
show these previews inline, with a link to the original. A preview is page one of a document the Commission publishes, readable, and unmodified apart from being rendered to a JPEG: nothing is cropped, blurred or redacted, so it can carry the same names, phone numbers and street addresses
as the document. Oklahoma's documents stay unpublished and there is no contact list (the completion images are published, under their wells: see 2. above). To go back, run the capture with `--no-previews` (the documents stay linked) or remove `--publish-docs`, and delete the release's `.jpg` files.

**The Content-Security-Policy changed with it (2026-11-01).** `img-src` now also allows `https://github.com` and `https://*.githubusercontent.com` (a release download is a redirect to a githubusercontent host), so that those previews load inline. Only `img-src` changed: `default-src 'self'` stays, so
scripts, styles, fonts and data still come from the site itself, and the policy still has no `unsafe-inline`. A visitor's browser asks GitHub for the previews on the page it is looking at (sent with no referrer), and for nothing else.

**A gate before anything is published.** Each Daily producer's `--check` runs in the nightly before the commit: every day file is scanned for an e-mail address, a web address and a phone number (and, for Oklahoma and New Mexico, a run of ten digits, since they publish
no API numbers), and every operator name it publishes must pass the state's rule. A night that fails is dropped, not published (`site/pipeline/privacy_check.py`, `tests/test_privacy_gate.py`, which also scans every published data file).

**What the gate cannot undo.** Before the dba rule existed (fixed 2026-10-31, PR #18) two Oklahoma day files named two sole proprietors ("... DBA ..."). The current files are clean, but the two earlier versions are still readable in the git history of `main` and of `gh-pages`
(`site/public/data/daily-ok/2026-08-26.json` and `2026-10-27.json` as first committed). Removing them needs a rewrite of history, which the rules for this repository forbid without the owner's decision, and a request to GitHub Support to purge cached views and pull-request refs.

**The new-wells map's points (2026-11-01, history added the same day).** `newwells/points.json` publishes the position of every well fractured in the last 24 months, and `newwells/points-history.json` that of every earlier one back to 2011 (about 220,000, loaded by the page only when "Since 2011" is chosen), to 11 m (four decimals), with its state, county, day, depth, water, whether it is on federal or tribal land and, only when it is a corporation, LLC or partnership
(or on a short reviewed list of companies whose registered names carry no "Inc"), its operator. It never holds an API number, a well name, a lease or a person's name. A well's surface position is a place, and the Daily report already publishes permit dots at the same precision; a person who is the operator of record
("Clay Hamilton") is in the registry and is never named here. To go back, delete `site/public/data/newwells/` and disable `refresh-newwells.yml`.

## Run it
```
python3 -m http.server 8000 --directory site/public
```
Then open http://localhost:8000. Any static host works.

## Tests
`python3 -I tests/run_all.py` runs the Python tests (pipeline rules, validators, the nightly workflow's own steps), `node tests/smoke.cjs`
loads every view in a real browser at desktop and phone width and `node tests/a11y.cjs` checks text contrast in both themes, keyboard focus and that nothing is cut off at 360 px;
`.github/workflows/ci.yml` runs them on every pull request. See `tests/README.md`.

Every day at 18:07 UTC `.github/workflows/well-images.yml` runs `site/pipeline/d12_wells.py`: it reads the newest packs the Commission has listed (W-1 images, directional surveys and completion images, with the completion data zip that says which
well each completion document belongs to), ties every document to its well, publishes it as files of GitHub releases, commits `site/public/data/wells/` (an index and one file per county) and publishes the site. It is separate from the nightly capture, shares its
concurrency group, and a pack that fails is simply done again the next day; by hand, `days` and `window` reach further back (about 0.9 GB per day).

Every Monday at 06:20 UTC `.github/workflows/refresh-national.yml` runs each state's producer isolated (`site/pipeline/d11_nat_run.py`: a failed producer's file is put back as committed, a server's refusal is an answer and not an error) and rebuilds
`national.json`; `refresh-monthly.yml` rebuilds it too after refreshing Oklahoma's, New Mexico's and the offshore's files.

The national report's files are `site/public/data/nat/<ST>.json` (one per state, written by `site/pipeline/d11_nat_<st>.py`) merged into `national.json` by
`python3 -I site/pipeline/d11_nat_build.py`; `NOTES_D11.md` has the shape and the rules every producer follows.

## A local database
Everything the site publishes can be loaded into one SQLite file you keep on your own machine (standard library only, a few seconds, built from the committed files and never fetched):
`python3 -I site/pipeline/build_db.py` writes `db/oil-tracker.sqlite` (about 13 MB; `db/*` and `*.sqlite` are kept out of git, with one exception: the compressed FracFocus snapshot below), `--check` verifies an existing file. Every data file is stored verbatim in
`documents`, and the main entities are tables you can query and join: jurisdictions, national_months (permits or spuds by state, month and kind of permit), series (prices, crude production, rigs, jobs,
tax), county_permits, operators, permit_points, companies, daily_reports and daily_permits, tx_image_packs, wells, well_documents (every scanned document tied to its well, with the address of the file and of its picture) well_packs, new_wells (one row per well since 2011 with its published GPS point, from FracFocus: the last 24 months and the history file), new_wells_months and new_wells_operators and, once the matrix exists, metrics, field_states, field_cells, field_sources (FracFocus is a row of the matrix, like an agency) and field_registry_fields (each field of its download). Permits approved
and wells spudded are different measures (`jurisdictions.measure` says which) and nothing in the database adds them. See the top of `site/pipeline/build_db.py`.

**The whole FracFocus registry (2026-11-01).** The site publishes every FracFocus well since 2011 with its point (no API number or name); the database can hold all of the registry. `python3 -I site/pipeline/build_db.py --fracfocus` adds `ff_disclosures` (every one of the registry's
252,000 disclosures since 2011: its id, the job's start and end as ISO dates with the registry's own text beside them, API number and the well it gives, state and code, county, operator, well name, latitude and longitude as filed, datum, depth, water and non-water volumes, form version, federal and tribal flags;
`is_first` marks the first disclosure of each well, the site's own definition of a new well, so `v_ff_new_wells` gives the same 239,133 wells and `v_ff_new_wells_by_month` the same monthly counts the Overview draws) and `ff_water_sources` (25,878 water sources of those jobs), read by range requests (about
19 MB; the file is then about 120 MB). Add `--chemicals` for `ff_ingredients`, every ingredient of every job (about 7 million rows: purpose, trade name, supplier, CAS number, chemical name, percent of the job, mass; the file is then about 2.5 GB), which needs the whole 443 MB zip: `--fracfocus-zip PATH` for a copy you have, or
`--fracfocus-download DIR` to fetch it once into a new folder. `--check` verifies these tables too (counts against `meta`, one first disclosure a well). **These tables hold what the registry publishes and the site never does: API numbers, well names, and operators that are people.** One snapshot of the database with the disclosures and water sources (not the ingredients: 2.45 GB) is committed as **`db/oil-tracker.sqlite.gz`** (42.6 MiB, made 2026-11-01; `gunzip -k db/oil-tracker.sqlite.gz`), by the owner's decision of 2026-11-01 (see Privacy). It is outside `site/public`, so the live site does not serve it,
and it is a snapshot: rebuild with the command above, and commit a new one only when it is worth it, because every version stays in git history at about 43 MB. `.gitignore` still ignores the uncompressed file and anything else in `db/`; a database built without `--fracfocus` holds none of this; `ff_db.ensure_local_only` refuses to write these tables under `site/` or to a name git would track
(`db/oil-tracker.sqlite.gz` is made from the file, not written by the loader); nothing from it is copied into `site/public/data`. See `site/pipeline/ff_db.py`.

## Rebuild the data
The scripts in `site/pipeline/` (`d1` to `d6`) and `site/build_data.py` write the JSON files in `site/public/data/`
(Python 3, standard library only). Some downloads are large (the RRC production dump is 3.7 GB). `build_data.py` reads
the lead lists `leadpool.csv`, `leadpool_ranked.csv` and `rrc_operators.csv`, which `leadpool.py` and
`rrc_operators.py` generate; they are not committed because they carry contact details from public filings.

The Texas nightly report is built by `site/pipeline/d7_daily.py` (Python 3, standard library only; no lead CSVs needed) into
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

The permit history of Oklahoma, New Mexico and the federal offshore (the four `*-ok.json`, four `*-nm.json` and four `*-fo.json` files that the Overview, the Daily report and the Operators
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
- The nightly Texas report reads nightly files, but the county, operator and company tables are built from the RRC's monthly files, so the
  two can show permits through different dates. The report's source-health section says when a monthly rebuild is due.
- Oklahoma's nightly capture is only the OCC's daily files: about 3 new-drill permits a business day (Texas: about 31), no pending queue or
  image packs, planned depth instead of horizontal (the permit file does not say), transfers for about the last month and the well
  inventory only for days captured live. It has no Oklahoma jobs or rig counts (sources not reachable from the build host), no company
  list and no production by county. Its permit history (series, counties, operators, permit points) is in the Overview, the Operators
  page and the Daily report.
- New Mexico's nightly capture is read from the Division's well layer, which is entered some days after an approval: the newest two or three days
  run low and fill in (the pace chart is rewritten from the layer each night and the earlier reports' permits are recounted), a rebuilt day counts only the approvals still in status New, and the Division
  publishes no planned depth, filing date, completion or transfer by day (`site/pipeline/NOTES_D9.md`).
- The federal offshore is read from BSEE's weekly borehole file: wells spudded (BSEE publishes approvals to drill only as an online query), about 45 a year from 16 operators, so a
  month holds about four wells and the pages lean on the 12-month counts. The series ends 60 days back, a cautious guess: there are no earlier copies of the file to measure how late BSEE's spud
  dates arrive (compare the weekly builds and shorten it if a month keeps growing). It publishes no depth (a total depth exists for a handful of wells), has no nightly capture, and its
  areas are BSEE protraction areas, not counties (`site/pipeline/NOTES_D10.md`).
- BLS suppresses most small counties, and some series end earlier than others; each figure on the site carries its own date.

Not affiliated with any agency. Public records can be wrong or stale: verify before any outreach. No license has been
chosen yet.
