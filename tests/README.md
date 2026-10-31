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
- `test_d9_nm.py`: New Mexico's files (`d9_nm_monthly.py`): the lag that decides where they end, what a well becomes, the naming rule, no depth, the
  validator against faults, mutants, the committed files and the EIA series for New Mexico.
- `test_d8_monthly.py`: the Oklahoma permit history files (`d8_ok_monthly.py`): one permit per API number and day, formation rows folded,
  the windows, the naming rule, rounded locations, the validator against deliberate faults, mutants, and the committed files.
- `test_workflow.py`: `.github/workflows/daily-rrc-report.yml`: the structure that isolates the three captures, the `if:` conditions for every
  combination of outcomes (64), and the workflow's own `run:` scripts executed against a throwaway clone with a local bare `origin`
  (needs git and PyYAML).
- `test_workflow_monthly.py`: `.github/workflows/refresh-monthly.yml` the same way (isolation, the 16 outcome combinations, the drop, commit and last
  steps run against a clone; only the eight files it names are ever committed, and it shares the nightly's concurrency group).
- `test_publish.py`: `.github/workflows/publish.yml` (what it follows, its `if:` for every kind of trigger, that it cannot reach the agencies)
  and `.github/scripts/publish_pages.sh`, which the nightly capture shares: run against a throwaway clone with a local bare `origin` that has
  a gh-pages branch (publishes exactly the site, never rewrites history, says so when current, refuses an incomplete copy, retries a refused
  push and gives up after four; needs git and PyYAML).
- `test_d9_nm_daily.py`: the New Mexico Daily report's producer: a well counted once, which day a report shows, what is named and left out, the series rewritten each night, a whole run with the network faked, the validator on faults, mutants and the committed archive.
- `test_js_data.mjs`: `states.js` (parsing and keeping the choice, county and point keys), `overview-data.js` (the permit series, county counts,
  operators and permit points of the states shown, merged; a state with no file is left out, never counted as zero) and, on the committed
  files, that every merged county and point falls on the map. Node only; CI runs it before the smoke test.
- `smoke.cjs`: Playwright (Chromium). `node --check` does not catch syntax errors in ES modules; this does. Locally Playwright is
  preinstalled in the Claude sandbox; in CI it is installed by `.github/workflows/ci.yml`, which runs them all on every pull request and push to `main`.
  It also drives the states bar: choosing a state changes the Overview and the address, the Daily report and the Operators page follow (the State
  column, each state's own date, the Texas-only filters stepping aside), Companies say they are Texas only, and a view that does not follow it hides the bar.
  The Map is driven the same way: each state alone and all together (counties, legend, dot colors, the table twin, a hover and a click on a dot, the replay),
  and a county or an operator opened by its state-prefixed key. The Daily report is driven for New Mexico alone (three cards, its color, its 33 counties, no tile for what
  it does not publish) and with all three states (one map of 364 counties); the states-bar block stubs New Mexico's index away so a state with no report is still exercised.
  On a phone it also checks the tabs' edge fade, the browser bar's color in each theme and, in the Daily report with three states, one pill per state, notes and sparklines that fit their cards and no card alone in half a row.
  It sweeps every map metric under New Mexico, Oklahoma and all three states for a NaN in the legend or panel, and says so when no county has a figure (New Mexico's depth).
  With the browser's clock set (Playwright's `page.clock`), it checks that the Daily report warns when its newest report is days behind today and not otherwise.
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
