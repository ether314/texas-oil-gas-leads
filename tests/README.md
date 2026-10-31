# Tests

Everything here runs without network access, on synthetic data and the committed files.

```
python3 -I tests/run_all.py            # every Python test, one process each (add a name fragment to run some: ... run_all.py d8)
node tests/smoke.cjs                   # browser smoke test: every JS module imports, every view loads clean, no sideways scroll on a phone
```

- `test_d7_*.py`: the Texas Daily report producer (`d7_daily.py`, `d7_packs.py`, `rrc_share.py`): the one rule (a report shows what landed
  on the shares that day), month-safe permit coverage, pack previews, download deadlines. The pack test needs Pillow and `pdftoppm`.
- `test_d8.py`, `test_d8_context.py`, `test_ok_xlsx.py`: the Oklahoma producer, its monthly series and its workbook reader: rules,
  Central-time days across both clock changes, validation of the committed archive (with deliberate faults), privacy checks.
- `test_workflow.py`: `.github/workflows/daily-rrc-report.yml`: the structure that isolates the two captures, the `if:` conditions for every
  combination of outcomes, and the workflow's own `run:` scripts executed against a throwaway clone with a local bare `origin`
  (needs git and PyYAML).
- `smoke.cjs`: Playwright (Chromium). `node --check` does not catch syntax errors in ES modules; this does. Locally Playwright is
  preinstalled in the Claude sandbox; in CI it is installed by `.github/workflows/ci.yml`, which runs both on every pull request and push to `main`.

Optional: `OK_REAL_FILES=<folder holding the OCC daily .xlsx files and rbdms-wells.csv>` adds two checks against the real files (the two
workbook readers agree; no operator the naming rule refuses appears in the archive). Those files carry contact details and are never committed.
