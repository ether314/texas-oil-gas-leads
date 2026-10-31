# Tests

Everything here runs without network access, on synthetic data and the committed files.

```
python3 -I tests/run_all.py            # every Python test, one process each (add a name fragment to run some: ... run_all.py d8)
node tests/test_js_data.mjs            # the pure JavaScript data code: which states are shown, what the Overview merges, the permit points merge
node tests/smoke.cjs                   # browser smoke test: every JS module imports, every view loads clean, no sideways scroll on a phone, the states bar
node tests/a11y.cjs                    # browser accessibility test: text contrast in both themes at both widths, nothing cut off and no control under 24 px at 360 px, keyboard focus, page language and titles
```

- `test_d7_*.py`: the Texas Daily report producer (`d7_daily.py`, `d7_packs.py`, `rrc_share.py`): the one rule (a report shows what landed
  on the shares that day), month-safe permit coverage, pack previews, download deadlines. The pack test needs Pillow and `pdftoppm`.
- `test_d8.py`, `test_d8_context.py`, `test_ok_xlsx.py`: the Oklahoma producer, its monthly series and its workbook reader: rules,
  Central-time days across both clock changes, validation of the committed archive (with deliberate faults), privacy checks.
- `test_d7_nights.py`: whole nights of the Texas producer with every socket blocked and the RRC's shares faked (synthetic permit file, pending sets, completions zip, pack names): the map service
  answering badly, a backup run that read less (or lost the document links), rebuilt days written partial, a damaged archive, the text of a failure, stray file names and dates, files that are
  delivered but are not the file (empty, an HTML page, a renamed column, a layout change), the real share client on listings that are not listings, the repair of an old day, the capture's time limit,
  and 25 mutants that put the old behavior back (about 20 s).
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
- `test_js_data.mjs`: `states.js` (parsing and keeping the choice, county and point keys, the federal offshore's place in them, how a sentence names the states that count spuds, counties and areas), `overview-data.js` (the permit series, county counts,
  operators and permit points of the states shown, merged; a state with no file is left out, never counted as zero) and, on the committed
  files, that every merged county and point falls on the map. Node only; CI runs it before the smoke test.
- `test_js_data.mjs` also covers `national-data.js` (totals within a measure and never the BLM's, size classes, the stack and where its axis ends, the mix, the tile map covering every jurisdiction in the committed file).
- `test_js_data.mjs` also covers `images-data.js` (a pack not listed is null and never zero, totals and the average over only the days that had a pack, a day file's packs and kinds, the permits whose files are published, the lifecycle, and that every kind in the committed live days is described).
- `smoke.cjs`: Playwright (Chromium). `node --check` does not catch syntax errors in ES modules; this does. Locally Playwright is
  preinstalled in the Claude sandbox; in CI it is installed by `.github/workflows/ci.yml`, which runs them all on every pull request and push to `main`.
  It also drives the states bar: choosing a state changes the Overview and the address, the Daily report and the Operators page follow (the State
  column, each state's own date, the Texas-only filters stepping aside), Companies say they are Texas only, and a view that does not follow it hides the bar.
  The Map is driven the same way: each state alone and all together (counties, legend, dot colors, the table twin, a hover and a click on a dot, the replay),
  and a county or an operator opened by its state-prefixed key. The Daily report is driven for New Mexico alone (three cards, its color, its 33 counties, no tile for what
  it does not publish) and with all three states that have one (one map of 364 counties); the states-bar block stubs New Mexico's index away so a state with no report is still exercised.
  The federal offshore has its own block: the bar's five choices fit a 360 px phone (TX, OK, NM, Offshore) and keep their full names for a screen reader, the Map names its 63 areas as areas (no FIPS code),
  the Daily report says it has none and why, Companies says there is nothing to list, and Operators shows its 16 operators with a "Top area" column.
  On a phone it also checks the tabs' edge fade, the browser bar's color in each theme and, in the Daily report with three states, one pill per state, notes and sparklines that fit their cards and no card alone in half a row.
  It checks that what a state does not publish is never a 0 (the Daily map's tooltips, New Mexico's "other filings", the amended-permits figure naming the states it adds), that an address naming two states lights no segment of the bar and says which are shown, that the Overview's chips name New Mexico's different measure, and that a Map operator panel never shows more dots than the operator has.
  It sweeps every map metric under New Mexico, Oklahoma and all three states for a NaN in the legend or panel, and says so when no county has a figure (New Mexico's depth).
  It drops the first request for a data file and checks the page still draws (one retry), and that a missing file is asked for once.
  Under print media it checks that a dark page prints light and that the header, states bar, controls and buttons stay off the paper.
  With the browser's clock set (Playwright's `page.clock`), it checks that the Daily report warns when its newest report is days behind today and not otherwise.
  With Texas's pending and completion files stubbed as unread it checks that the Daily cards say "could not be read" (and for which state) rather than "no pending set recorded" or "no completion filings".
  The National report is driven too: the panel opens on the biggest state, a tile opens its panel and the address, a producing state with no data says "Not read yet" and never a figure, the count toggle changes the stack and the address,
  a ranking row selects its tile, and the view shows no NaN, undefined, null or Infinity.
  The Texas images view is driven too: a column for each report day, the day list, choosing a day shows its packs and the address, any contact sheet loads from the site itself, and no NaN.
  It checks that every button draws its words as one piece (a label split into two flex items gets the icon's gap between its words, which read as a double space).
  It downloads the Operators CSV (a State column, blank not zero where a state publishes no figure, no number turned into text) and walks the archive's days (the newest, the oldest, every tenth and each day with an empty Texas queue) for rendered NaN, undefined, null or Infinity.
- `a11y.cjs`: Playwright (Chromium), the same server as the smoke test. Contrast: every visible piece of text on 11 views, light and dark, desktop and phone, is held to
  WCAG 4.5:1 (3:1 for large text), against what is behind it (a gradient counts at its worst stop; disabled controls are exempt). Keyboard: Tab through six views;
  every stop has a name and shows a focus ring and none sticks; one `main`, one visible `h1`, a language and a title per view. Reflow: at 360 px on 14 views and sets of
  states no content is cut off by an `overflow: hidden` box and nothing runs past the right edge outside a scroller (it found a Daily card's note and sparkline cut off). Target size: at the same width every button, field,
  tab and chip is at least 24 x 24 px (WCAG 2.2, 2.5.8; links in running text and table cells are left out). A state's own color (orange, purple, green) is
  under 4.5:1 on the page, so it is used for dots, bars and lines and never for words. Changing a color token means running this.

Optional: `OK_REAL_FILES=<folder holding the OCC daily .xlsx files and rbdms-wells.csv>` adds two checks against the real files (the two
workbook readers agree; no operator the naming rule refuses appears in the archive); with the master `ITD-wells-formations-base.xlsx` and
the daily `ITD-wells-formations-daily.xlsx` in the folder, `test_d8_monthly.py` also checks the monthly series against the Daily archive.
Those files carry contact details and are never committed.
