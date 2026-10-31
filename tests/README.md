# Tests

Everything here runs without network access, on synthetic data and the committed files.

```
python3 -I tests/run_all.py            # every Python test, one process each (add a name fragment to run some: ... run_all.py d8)
node tests/test_js_data.mjs            # the pure JavaScript data code: which states are shown, what the Overview merges, the permit points merge
node tests/smoke.cjs                   # browser smoke test: every JS module imports, every view loads clean, no sideways scroll on a phone, the states bar
```

- `test_d7_*.py`: the Texas Daily report producer (`d7_daily.py`, `d7_packs.py`, `rrc_share.py`): the one rule (a report shows what landed
  on the shares that day), month-safe permit coverage, pack previews, download deadlines. The pack test needs Pillow and `pdftoppm`.
- `test_d8.py`, `test_d8_context.py`, `test_ok_xlsx.py`: the Oklahoma producer, its monthly series and its workbook reader: rules,
  Central-time days across both clock changes, validation of the committed archive (with deliberate faults), privacy checks.
- `test_d9_nm.py`: New Mexico's files (`d9_nm_monthly.py`): the lag that decides where they end, what a well becomes, the naming rule, no depth, the
  validator against faults, mutants, the committed files and the EIA series for New Mexico.
- `test_d8_monthly.py`: the Oklahoma permit history files (`d8_ok_monthly.py`): one permit per API number and day, formation rows folded,
  the windows, the naming rule, rounded locations, the validator against deliberate faults, mutants, and the committed files.
- `test_workflow.py`: `.github/workflows/daily-rrc-report.yml`: the structure that isolates the two captures, the `if:` conditions for every
  combination of outcomes, and the workflow's own `run:` scripts executed against a throwaway clone with a local bare `origin`
  (needs git and PyYAML).
- `test_publish.py`: `.github/workflows/publish.yml` (what it follows, its `if:` for every kind of trigger, that it cannot reach the agencies)
  and `.github/scripts/publish_pages.sh`, which the nightly capture shares: run against a throwaway clone with a local bare `origin` that has
  a gh-pages branch (publishes exactly the site, never rewrites history, says so when current, refuses an incomplete copy, retries a refused
  push and gives up after four; needs git and PyYAML).
- `test_js_data.mjs`: `states.js` (parsing and keeping the choice, county and point keys), `overview-data.js` (the permit series, county counts,
  operators and permit points of the states shown, merged; a state with no file is left out, never counted as zero) and, on the committed
  files, that every merged county and point falls on the map. Node only; CI runs it before the smoke test.
- `smoke.cjs`: Playwright (Chromium). `node --check` does not catch syntax errors in ES modules; this does. Locally Playwright is
  preinstalled in the Claude sandbox; in CI it is installed by `.github/workflows/ci.yml`, which runs them all on every pull request and push to `main`.
  It also drives the states bar: choosing a state changes the Overview and the address, the Daily report follows, and a view that does not follow it hides the bar.

Optional: `OK_REAL_FILES=<folder holding the OCC daily .xlsx files and rbdms-wells.csv>` adds two checks against the real files (the two
workbook readers agree; no operator the naming rule refuses appears in the archive); with the master `ITD-wells-formations-base.xlsx` and
the daily `ITD-wells-formations-daily.xlsx` in the folder, `test_d8_monthly.py` also checks the monthly series against the Daily archive.
Those files carry contact details and are never committed.
