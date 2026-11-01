# Tests

Everything here runs without network access, on synthetic data and the committed files.

```
python3 -I tests/run_all.py            # every Python test, one process each (add a name fragment to run some: ... run_all.py d8)
node tests/test_js_data.mjs            # the pure JavaScript data code: which states are shown, what the Overview merges, the permit points merge
node tests/smoke.cjs                   # browser smoke test: every JS module imports, every view loads clean, no sideways scroll on a phone, the states bar
node tests/a11y.cjs                    # browser accessibility test: text contrast in both themes at both widths, nothing cut off and no control under 24 px at 360 px, keyboard focus, page language and titles
```

- `test_d7_*.py`: the Texas Daily report producer (`d7_daily.py`, `d7_packs.py`, `rrc_share.py`): the one rule (a report shows what landed
  on the shares that day), month-safe permit coverage, pack previews, download deadlines. The pack test needs Pillow and `pdftoppm`. It also covers the readable page-one previews of the published documents (2026-11-01):
  a JPEG about 900 px wide, at most 200 KB, gray unless the page has color, page one only, readable and not blurred, a damaged PDF or a hung `pdftoppm` leaving no preview and no failure, staging with and without previews,
  the tools missing, a run of failures, a spent budget, `attach_documents` recording `previews` and `noPreview` only for what the release listing confirmed, the validator on those fields, and `d7_release.publish` uploading
  previews after the documents as optional files (a failed upload costs nothing but itself, the asset limit trims them).
- `test_d12_wells.py`: the well-image archive's producer (`d12_wells.py`) on synthetic packs built with Pillow (needs Pillow and poppler): which packs a run does (the newest two filing days with a pack not done, a pack left alone for 90 minutes, an empty day,
  completion images with no completion data zip, a stray name), how a document finds its well (permit number, the survey CSV, the completion packet's tracking number; the approved packet wins; lease and landowner never read), names that do not follow the zip's order and
  never come from the pack, a file that is not a PDF refused, a broken PDF published without a picture or a page count, releases of at most 800 files, whole runs with `gh` and the RRC faked (uploads verified, a failed upload recorded as nothing while the other packs stay,
  a second run that has nothing to do, a replaced pack, aged-out days removed with their releases, a refusing share is an answer), no lease, landowner, file name, address or phone number in any published file, the check against 17 deliberate faults, ten mutants, and the committed files.
- `test_workflow_wells.py`: `.github/workflows/well-images.yml` the way the other workflows are tested: a run time after the day's last pack has landed and settled and three hours from every other schedule, the nightly's concurrency group, a job that only runs on main,
  the repository token given to one step, every step bounded, the inputs refused before anything runs, the capture step's arguments (with a stand-in python3), and the drop, commit (only the well files, rebased onto what another run pushed first) and last steps run against a throwaway clone.
- `test_d8.py`, `test_d8_context.py`, `test_ok_xlsx.py`: the Oklahoma producer, its monthly series and its workbook reader: rules,
  Central-time days across both clock changes, validation of the committed archive (with deliberate faults), privacy checks.
- `test_d7_nights.py`: whole nights of the Texas producer with every socket blocked and the RRC's shares faked (synthetic permit file, pending sets, completions zip, pack names): the map service
  answering badly, a backup run that read less (or lost the document links), rebuilt days written partial, a damaged archive, the text of a failure, stray file names and dates, files that are
  delivered but are not the file (empty, an HTML page, a renamed column, a layout change), the real share client on listings that are not listings, the repair of an old day, the capture's time limit,
  a night with previews (the documents go up first, each preview a real JPEG, one that cannot be drawn named in `noPreview`, previews that cannot be uploaded costing nothing, `--no-previews`, no poppler),
  and 28 mutants that put the old behavior back (about 45 s).
- `test_d8_nights.py`: whole nights of the Oklahoma producer with the network faked: a permit with no county, an inventory that is an error page, empty,
  header-only, renamed, cut short or starts with a byte-order mark, a backup run that read less than the report it would replace, a master file that
  cannot be read, a rebuilt day left partial, no web address in a failure's text, and eleven mutants that put the old behavior back.
- `test_privacy_gate.py`: the privacy gate the nightly runs before it commits (`privacy_check.py` and the three producers' `--check`: no e-mail address, web address or phone number in a day file, no ten-digit number in Oklahoma's or New Mexico's, every
  operator name it publishes held to the state's rule), against a copy of each committed archive with a violation put in; the child that parses a downloaded PDF has no repository token; and the 321 published data files hold no e-mail, phone or API-like
  number and every city is a place name.
- `test_d10_fo.py`: the federal offshore's files (`d10_fo_monthly.py`, from BSEE's borehole and company files): a well is the first ten digits of the API number on its earliest spud, a sidetrack is not another well, the 63 areas and their numbering,
  the 60-day lag, blank and placeholder dates, a spud after today, a location outside the Gulf, an individual or an unknown operator number named by no one, no API number, lease or platform published, the readers refusing an error page or a handful of companies, a company's current name whatever the order of its rows, the validator
  against five faults, whole runs of the producer on local copies of the files (a good file written and a second run changing nothing; a truncated file, spud dates that are not dates, swapped coordinates, a company file
  with none of the operators, total-depth dates before the spuds, an address in a name and a damaged areas file each refused with the committed files left as they were; a few odd rows tolerated), a year's wells agreeing across
  the series, the areas and the operators, ten mutants and the committed files, and the EIA's offshore crude series (`series-fo.json`: its plausible range, units, the page parser refusing Texas's, the Pacific offshore's and a per-day page); with `FO_REAL_FILES` set to a folder holding BSEE's three zips it reads the real ones.
- `test_d11_nat.py`: the national report's data layer (`d11_nat_common.py`, `d11_nat_build.py`): a permit falls in exactly one band (amendments first, then reworks, re-entries, service wells), the fluid words, dates in the shapes
  agencies use and the placeholders they put in, complete months only and the lag a spud-counting state needs, only corporations, LLCs and partnerships named, a band a source cannot tell published as null and never zero, the validator against 22 deliberate
  faults, a refused write leaving the committed file alone, the merge keeping measures apart (a state that ends earlier is padded with null) and never adding the BLM into the states, four mutants, and the committed `national.json` and `nat/*.json`.
- `test_d11_run.py`: the runner that runs every state's producer (`d11_nat_run.py`): fake producers run as the workflow runs real ones, covering a good file, the same data again, a file written and then a failure (restored exactly, or removed), a hang (stopped at its limit), a refusal (an
  answer, exit 0), a file that does not validate, exit 0 with no file, a token that must not be visible, the run's budget, a rebuild that fails (national.json put back) and two mutants.
- `test_workflow_national.py`: `.github/workflows/refresh-national.yml` the same way as the monthly one: after the monthly files, in the nightly's concurrency group, every step bounded and isolated, the `if:` conditions for all 8 outcomes, and the drop, commit (new state files included, only the national files ever added) and last steps run against a throwaway clone.
- `test_d11_fields.py`: the permit-data matrix (`d11_fields_build.py`, the researched `fields/<ST>.json`): the catalog of 48 metrics, 16 deliberate faults the rules must refuse (a missing metric, `data` with only a form or a web page behind it, `unknown` with evidence, a note over 120 characters,
  grade A with nothing reachable, an http link, an e-mail address, phone or API number), the builder on a temporary folder, the output validator, a mutant, and the committed files.
- `test_build_db.py`: the local SQLite database (`build_db.py`): every data file stored verbatim (size and SHA-256), every table with exactly the rows its source implies (a band a source cannot tell has no row, never a zero; measures
  kept apart), a build that is repeatable, a failed build that leaves the old file alone, a file that is not SQLite never overwritten, `--check` noticing a tampered document or table, the odd shapes in the real files, and a mutant.
- `test_d9_nm.py`: New Mexico's files (`d9_nm_monthly.py`): the lag that decides where they end, what a well becomes, the naming rule, no depth, a year's wells agreeing across the series, the counties and the operators,
  the validator against faults, mutants, the committed files and the EIA series for New Mexico.
- `test_d8_monthly.py`: the Oklahoma permit history files (`d8_ok_monthly.py`): one permit per API number and day, formation rows folded,
  the windows, the naming rule, rounded locations, the validator against deliberate faults, mutants, and the committed files.
- `test_workflow.py`: `.github/workflows/daily-rrc-report.yml`: the structure that isolates the three captures, the `if:` conditions for every
  combination of outcomes (64), a time limit on each capture that leaves the job room to commit and publish, and the workflow's own `run:` scripts
  executed against a throwaway clone with a local bare `origin` (needs git and PyYAML).
- `test_workflow_monthly.py`: `.github/workflows/refresh-monthly.yml` the same way (isolation of the three refreshes, the 64 outcome combinations, the drop, commit and last
  steps run against a clone; only the eight files it names are ever committed, and it shares the nightly's concurrency group).
- `test_publish.py`: `.github/workflows/publish.yml` (what it follows, its `if:` for every kind of trigger, that it steps aside when main has moved on since the commit CI passed, that it cannot reach the agencies)
  and `.github/scripts/publish_pages.sh`, which the nightly capture shares: run against a throwaway clone with a local bare `origin` that has
  a gh-pages branch (publishes exactly the site, never rewrites history, says so when current, refuses an incomplete copy, retries a refused
  push and gives up after four; needs git and PyYAML).
- `test_d9_nm_daily.py`: the New Mexico Daily report's producer: a well counted once, which day a report shows, what is named and left out, the series rewritten each night, a whole run with the network faked, the validator on faults, mutants and the committed archive.
- `test_js_data.mjs`: `states.js` (parsing and keeping the choice, county and point keys, the federal offshore's place in them, how a sentence names the states that count spuds, counties and areas, and the wording helpers: "the federal offshore"
  inside a sentence, "1 spud", a well dot against a permit dot, what a sidetrack is, the least an area needs to be ranked on its change), `overview-data.js` (the permit series, county counts,
  operators and permit points of the states shown, merged; a state with no file is left out, never counted as zero) and, on the committed
  files, that every merged county and point falls on the map. Node only; CI runs it before the smoke test.
- `test_js_data.mjs` also covers `national-data.js` (totals within a measure and never the BLM's, size classes, the stack and where its axis ends, the mix, the tile map covering every jurisdiction in the committed file).
- `test_js_data.mjs` also covers `images-data.js` (a pack not listed is null and never zero, totals and the average over only the days that had a pack, a day file's packs and kinds, the permits whose files are published, the lifecycle, and that every kind in the committed live days is described).
- `test_js_data.mjs` also covers `wells-data.js` (an API number read with or without the 42, dashes and sidetrack digits, the start of a number giving a county and no well, addresses built only from what the producer writes, a well's documents by stage with an empty stage never missing, a file whose pages could not be counted saying no page count, search by number, field, operator or district, the tie counts of a pack read from the index and null for a pack not in the archive, the Commission's look-ups carrying no API number, and the committed index and county files).
- `test_js_data.mjs` also covers `fields-data.js` (a state's and a metric's score, the order of the columns, the headline, the agencies of each status, that every committed agency answers all 48 metrics).
- `test_js_data.mjs` also covers `images-data.js` (a pack not listed is null and never zero, totals and the average over only the days that had a pack, a day file's packs and kinds, the permits whose files are published, the lifecycle, and that every kind in the committed live days is described) and the readable previews: a release address is made only from a plain file name on a release named as a repository
  and a daily tag, a preview is linked only when the day's release says it holds one (`previews`, `noPreview`), the files and previews of a permit and of a survey.
- `smoke.cjs`: Playwright (Chromium). `node --check` does not catch syntax errors in ES modules; this does. Locally Playwright is
  preinstalled in the Claude sandbox; in CI it is installed by `.github/workflows/ci.yml`, which runs them all on every pull request and push to `main`.
  It also drives the states bar: choosing a state changes the Overview and the address, the Daily report and the Operators page follow (the State
  column, each state's own date, the Texas-only filters stepping aside), Companies say they are Texas only, and a view that does not follow it hides the bar.
  The Map is driven the same way: each state alone and all together (counties, legend, dot colors, the table twin, a hover and a click on a dot, the replay),
  and a county or an operator opened by its state-prefixed key. The Daily report is driven for New Mexico alone (three cards, its color, its 33 counties, no tile for what
  it does not publish) and with all three states that have one (one map of 364 counties); the states-bar block stubs New Mexico's index away so a state with no report is still exercised.
  The federal offshore has its own block: the bar's five choices fit a 360 px phone (TX, OK, NM, Offshore) and keep their full names for a screen reader, the Map names its 63 areas as areas (no FIPS code),
  the Daily report says it has none and why, Companies says there is nothing to list, and Operators shows its 16 operators with a "Top area" column. The bar (which measures itself, since the same words are wider in some fonts) is swept from 320 to 1280 px for a clipped button. The pages say what the offshore counts: the Map's lede
  and notes say spud locations, areas and what a sidetrack is, its change list ranks areas from 5 spuds (not the 20 permits no area has) and is not empty, an area with no wells says none were spudded (never that the Bureau published no location), the Operators
  bands are described in wells spudded (in permits for Texas rows of a mixed list) and the date column is "Last spud" (or "Last permit or spud"), the Production note keeps its space between two states' sentences, and a state inside a sentence is "the federal offshore".
  On a phone it also checks the tabs' edge fade, that the current tab is whole in the tabs' window for every view and the tabs move only for a tab that is out of it, the browser bar's color in each theme and, in the Daily report with three states, one pill per state, notes and sparklines that fit their cards and no card alone in half a row.
  It checks that what a state does not publish is never a 0 (the Daily map's tooltips, New Mexico's "other filings", the amended-permits figure naming the states it adds), that an address naming two states lights no segment of the bar and says which are shown, that the Overview's chips name New Mexico's different measure, and that a Map operator panel never shows more dots than the operator has.
  It sweeps every map metric under New Mexico, Oklahoma and all three states for a NaN in the legend or panel, and says so when no county has a figure (New Mexico's depth).
  It drops the first request for a data file and checks the page still draws (one retry), and that a missing file is asked for once.
  Under print media it checks that a dark page prints light and that the header, states bar, controls and buttons stay off the paper.
  With the browser's clock set (Playwright's `page.clock`), it checks that the Daily report warns when its newest report is days behind today and not otherwise.
  With Texas's pending and completion files stubbed as unread it checks that the Daily cards say "could not be read" (and for which state) rather than "no pending set recorded" or "no completion filings".
  The well finder (the archive is the fixture `tests/fixtures/wells.json`, served by both browser tests; the pictures are GitHub release files answered by a stub that sends them as GitHub does) is driven on a desktop and a phone: an API number opens its well and the address, three stages and six documents, five pictures loaded from the repository's releases (the page's policy allows nothing else), a document with no picture saying so, a picture opening large and Escape closing it, a county listing its wells, the start of a number narrowing it, back, deep links, a well with no document and a county with no file saying so without a 404, no 0 pages or NaN; an empty or missing archive says so and the rest of the page draws.
  The National report is driven too: the panel opens on the biggest state, a tile opens its panel and the address, a producing state with no data says "Not read yet" and never a figure, the count toggle changes the stack and the address,
  a ranking row selects its tile, and the view shows no NaN, undefined, null or Infinity.
  The Texas images view is driven too: a column for each report day, the day list, choosing a day shows its packs and the address, any contact sheet loads from the site itself, and no NaN.
  The permit-data matrix is driven too: a cell, an agency's code and a metric each open their panel and the address, a group tab filters the rows, no NaN, and the page says what it could not verify.
  The previews are driven with a stubbed day (`tests/preview-stub.cjs`: the newest real day given three permits' filings, fourteen surveys and a release with `previews` and `noPreview`; GitHub's hosts are answered by the test with a one-pixel PNG, so nothing
  touches the network): the Content-Security-Policy is exactly `default-src 'self'` with `img-src` also allowing `github.com` and `*.githubusercontent.com`; a lazy thumbnail for each preview the release holds and none for a document it does not; one preview answered
  404 says "Preview unavailable" and keeps its link to the original; Enter opens the page in a dialog named for its permit with a link to the original, Tab never reaches the page behind it, Escape, the Close button and a click on the backdrop close it and focus goes back to the
  thumbnail; an enlarged page that does not load says so; the drill page shows the same previews above its download buttons; no inline style, no sideways scroll on a phone, thumbnails of at least 24 px, no dialog animation with reduced motion; and a real day
  with no previews makes no tile, no dialog and no request to GitHub.
  It checks that every button draws its words as one piece (a label split into two flex items gets the icon's gap between its words, which read as a double space).
  It downloads the Operators CSV (a State column, blank not zero where a state publishes no figure, no number turned into text) and walks the archive's days (the newest, the oldest, every tenth and each day with an empty Texas queue) for rendered NaN, undefined, null or Infinity.
- `smoke.cjs` (block 16b) also sweeps the header over 13 widths from 360 to 1920 px: the theme toggle stays on the page, the page never scrolls sideways, the tabs stay on one line and reachable (held, or scrolled), the tagline is never cut, a phone gets the tabs on a row of their own, and a wider page never gets a smaller layout than a narrower one (the width at which the one row fits depends on the font). The header measures itself (`headerLayout` in `ui.js`), since the tabs grow with every view and are wider in some fonts.
- `a11y.cjs`: Playwright (Chromium), the same server as the smoke test. Contrast: every visible piece of text on 11 views, light and dark, desktop and phone, is held to
  WCAG 4.5:1 (3:1 for large text), against what is behind it (a gradient counts at its worst stop; disabled controls are exempt); the Texas images view is also audited with previews and with a page enlarged in its dialog (a stubbed day). Keyboard: Tab through seven views;
  every stop has a name and shows a focus ring and none sticks; one `main`, one visible `h1`, a language and a title per view. Reflow: at 360 px on 14 views and sets of
  states no content is cut off by an `overflow: hidden` box and nothing runs past the right edge outside a scroller (it found a Daily card's note and sparkline cut off). Target size: at the same width every button, field,
  tab and chip is at least 24 x 24 px (WCAG 2.2, 2.5.8; links in running text and table cells are left out). A state's own color (orange, purple, green) is
  under 4.5:1 on the page, so it is used for dots, bars and lines and never for words. Changing a color token means running this.

Optional: `OK_REAL_FILES=<folder holding the OCC daily .xlsx files and rbdms-wells.csv>` adds two checks against the real files (the two
workbook readers agree; no operator the naming rule refuses appears in the archive); with the master `ITD-wells-formations-base.xlsx` and
the daily `ITD-wells-formations-daily.xlsx` in the folder, `test_d8_monthly.py` also checks the monthly series against the Daily archive.
Those files carry contact details and are never committed.
