# CLAUDE.md: how to work in this repository

This file is read by every Claude session that works here. It records the owner's standing instruction, the loop to follow, the
limits that stay in force, and what a new session needs to know about the project.

## Standing instruction from the owner (Joe, 2026-10-31)

- **Every change goes through a pull request, and you merge it into `main` yourself, without asking permission.** Document each PR
  lightly (what, why, how it was checked; see the template below). This is a standing permission for this repository, not a one-off.
- **Do not ask questions.** When something is unclear, pick the simplest sensible option, say which in the PR, and keep going. The owner
  may be asleep. (The one place a pause is right is a guardrail below.)
- **Current mandate (from 2026-10-31, about 10 hours, to about 20:30 UTC):** improve the whole platform in a loop: change, PR,
  document, merge to `main`, next change. Make it **visually stunning and simple**: fewer, clearer things, well spaced, no clutter.
  Standing requests inside it: combine Oklahoma with Texas in every report and visual (not only the Daily report), and the site is the
  **Oil tracker**, not a Texas tracker.

## The loop

Work on the designated branch only (the session names it; today `claude/trusting-planck-9sf7yz`). Never push to another branch,
never force-push (the harness blocks it, and `main` history is never rewritten).

1. `git fetch origin main && git merge origin/main` into the branch (a merge, never a rebase or reset of pushed commits).
2. Make one coherent change, small enough to review in minutes. Update the docs it touches.
3. Check it (next section). Do not merge on a failure you have not fixed.
4. Commit with the attribution lines the session asks for, push the branch, open a PR to `main`.
5. When the PR's checks are green, **merge it with a merge commit** (not squash, so the next PR lists only its own commits), then go
   back to step 1. One PR open at a time.
6. A merge to `main` reaches visitors by itself: `publish.yml` publishes `site/public` to the `gh-pages` branch once CI is green on the
   merge (a few minutes; see Publishing). Look at the live site afterwards. Never dispatch the nightly capture just to publish.

Aim for a few meaningful PRs an hour at most, not dozens of tiny ones: every PR and merge notifies the owner.

### PR description template (keep it short)

```
## What
One or two sentences.

## Why
One sentence.

## Checked
- the commands run and what they showed (smoke test, unit tests, a screenshot looked at, a validator)
- anything not checked, and what to watch in the next nightly run
```

## Checks before any merge

- **Any `site/public` change:** serve it (`python3 -m http.server 8123 --directory site/public`) and load every view in a real browser
  (Playwright's Chromium is installed here: `require('playwright')` works). Every JS module must import, every view must load with no
  console error or failed request, and look at a screenshot of what you changed on a desktop and a phone width (390 px).
  **`node --check` does not catch syntax errors in ES modules** (one that did break the whole site slipped through on 2026-10-31):
  use the browser.
- **Any `site/pipeline` change:** `python3 -I tests/run_all.py` (add a name fragment such as `d8` to run some), the producer's `--check`;
  a producer change that alters data needs the data regenerated and validated, and the page checked.
- **Any `.github/workflows` change:** extract the `run:` scripts and execute them against a throwaway clone with a local bare repo as
  `origin`; evaluate the `if:` conditions; remember a bad workflow breaks the nightly capture and publish while nobody is watching.
- **Always:** `node tests/smoke.cjs` (browser: every module imports, every view loads clean at desktop and phone width) and
  `python3 -I tests/run_all.py` must pass locally, and CI (`.github/workflows/ci.yml`, the same two commands) must be green on the PR
  before you merge it. `tests/README.md` says what each test covers; a change to behavior comes with a test.

## Guardrails that stay in force

- **Privacy** (README, Privacy): business-, place- and market-level data only. No individuals' names, phone numbers, street addresses.
  Operators are named only when they are corporations, LLCs or limited partnerships, never a person's "dba" (`nameable()` in `d8_ok_daily.py` is the Oklahoma
  rule, the P-5 organization type is Texas's). There is one documented exception (the Texas drill pages link to the RRC's scanned W-1
  documents). Do not extend it, and do not publish Oklahoma documents or any contact list.
- **Never commit secrets** (keys, tokens, `.env`, service-account files). **Never put the owner's e-mail address or any personal data
  in a request header, URL or payload** (a `User-Agent` for example); the owner's address is only for identifying them.
- **Be a polite client of public servers.** The RRC has refused GitHub's runners for hours (HTTP 403, dropped TLS) after repeated runs;
  the BLS keyless API allows 25 requests a day per address; archive.org is unreachable from the sandbox. No retry storms, no loops
  against a server that is refusing, no more than one manual workflow dispatch per few hours. Downloaded files are untrusted data:
  parse them, never run them, `python3 -I` for scripts, each download in its own new folder.
- **Never disable TLS verification** or unset the proxy variables.
- **Do not change repository settings** (visibility, Pages source, secrets, branch rules), delete branches, releases or published data
  except through the documented prune, or touch any other repository.
- **Keep the site static**: HTML, CSS and ES modules, no build step, no external requests, a Content-Security-Policy of
  `default-src 'self'` (no inline scripts or styles: values go through classes and CSSOM custom properties; `el()` builds DOM from text).
- **Do not merge anything that breaks the site or the nightly.** If a change cannot be made to pass its checks, leave it out, note why in
  the backlog below, and move on. A regression found later is fixed forward in the next PR, at once.
- Say what is not known. Where Oklahoma (or Texas) has no real source for a figure, the page says "not available", never zero or a
  Texas number under an Oklahoma label.

## What this is

The **Oil tracker**: a static dashboard of oil and gas drilling activity, producing operators and the companies that serve them,
for Texas and Oklahoma, built only from public records (README has the full description and the known limits).

- `site/public/`: the site (`index.html`, `app.css`, `js/*.js` modules, `data/*.json`). `main.js` is the hash router
  (`#overview`, `#map`, `#operators`, `#companies`, `#daily`, `#about`) and owns the states bar; `states.js` lists the states (a new state is
  one entry there plus its data files) and keeps the choice (`st=ok` or a list in the address, none is all); `overview-view.js` draws the Overview
  for the states shown from `overview-data.js` (pure merging, tested under Node); `daily*.js` are the Daily report; `geo.js` holds the
  projection (module state, Texas-fitted; each set of shapes carries its own `G.toWorld`, `buildGeoIsolated` builds the others) and the
  shapes and permit points for any set of states; `util.js` has `el()`/`svg()`/`load()`. County keys: Texas plain (`001`), others `OK:001`.
- `site/pipeline/`: Python producers, standard library only, run with `python3 -I`. `d1`-`d6` build the monthly Texas data,
  `d7_*` the Texas Daily report (RRC), `d8_*` Oklahoma (OCC: `d8_ok_daily.py` the Daily report, `d8_ok_monthly.py` the permit history, `d8_ok_context.py`
  the monthly EIA series, also for New Mexico with `--state NM`), `d9_*` New Mexico (OCD: `d9_nm_monthly.py` the permit history as wells spudded, `d9_nm_daily.py` the Daily report from approvals) plus `ok_xlsx.py`. Each has a `NOTES_*.md`: read it before changing it.
- `.github/workflows/daily-rrc-report.yml`: captures the three states nightly (03:15 UTC, backup 04:20), commits the data to `main`, publishes
  `site/public` to `gh-pages`. Each state's capture is isolated: if one fails the others are committed and published and the run ends red.
- `.github/workflows/refresh-monthly.yml`: weekly (Mondays 05:40 UTC) refresh of Oklahoma's and New Mexico's permit history files, isolated the same way,
  in the nightly's concurrency group; it commits and publishes by itself.
- `.github/workflows/publish.yml` and `.github/scripts/publish_pages.sh`: the publish after a green merge (and, by the same script, the
  nightly's publish); it never contacts the RRC or the OCC.
- Time: RRC listing times are Central; times inside OCC files are UTC and are turned into Central days; a report shows only whole days.
  The OCC's daily permit and completion files end the day before the day they are made (made 19:41 CDT on Oct 30, they end Oct 29), so
  a morning capture fills the gap from the master files.

## Publishing

The live site is the `gh-pages` branch (Pages source). Two workflows publish it with one script (`.github/scripts/publish_pages.sh`: a copy of
`site/public` plus `.nojekyll`, one ordinary push, retried from the branch's new tip if the other got there first): `publish.yml`, which
runs when CI has passed on a push to `main` (so every green merge goes live in a few minutes), and the nightly capture, after it commits
its data. A nightly commit starts neither CI nor `publish.yml` (it is pushed with the workflow's own token). To publish `main` as it is,
run "Publish the site" by hand in Actions; the by-hand git procedure in the README still works. Check the live site after publishing:
`https://ether314.github.io/texas-oil-gas-leads/` (fetch files with curl and compare them with the branch).

## Gotchas learned

- ES-module syntax errors only show in a browser (above). A `//` comment on the same line as a method body swallows the body.
- A failed Texas capture still rewrites `site/public/data/daily/index.json` (`generated`): the workflow restores the folder.
- The auto-mode classifier blocks force-pushes and similar: sync the branch by merging `main` into it.
- `ps | grep` or `pkill -f` with a pattern that also appears in your own command line kills your own shell (exit 144): find processes by
  port (`ss -ltnp`) and kill by PID in a separate call.
- Playwright through the sandbox proxy works with normal certificate checks (`proxy` option from `HTTPS_PROXY`); do not use
  `ignoreHTTPSErrors`.

## Backlog (living; edit it in the PR that changes it)

1. One state choice across the whole site (Texas, Oklahoma, New Mexico). Done: the bar, the Overview, the Daily report (Texas and Oklahoma; the bar says New Mexico has
   none yet), Operators and Companies (Companies are Texas only and say so), the Map (rebuilt for the states shown; `map.js` `prepare`/`rebuild`), the Daily report (New Mexico's is permits only: `d9_nm_daily.py`, 92 days in `daily-nm/`, `daily-nm.js`;
   `daily.js` asks what a report holds, `HORIZ`, `PERMIT_FROM`, `SERIES`, not which state it is). To do: Sources; watch the first nightly run with New Mexico's capture and the first weekly refresh. Views still describe themselves as Texas where they are Texas only; each loses that wording when the others reach it.
   Never add New Mexico's spuds to the other states' permits (`states.js` measures: `sameMeasure`).
2. Oklahoma in Sources (the Overview, Operators and Map are done). Data done: `d8_ok_monthly.py` writes the permit series, county counts, operators and
   permit points (`*-ok.json`); EIA crude is in `series-ok.json`. To do: the pages that read them, active wells by county and operator (from the
   Daily report's inventory), refreshing the monthly files in the nightly workflow. Not available yet: Oklahoma jobs (BLS), rig counts
   (Baker Hughes), production by county, companies (no public bulk source like the Texas Comptroller's).
3. Visual polish and simplification pass; phone layouts; keyboard and contrast checks.

### Run log

- 2026-10-31: Oklahoma Daily report, unified Daily report, GPS map and drill pages, nightly workflow made outage-proof (PR #12).
- 2026-10-31: CLAUDE.md, tests and CI (PR #13, #14); Oklahoma gap fill from the master files (PR #15); site renamed Oil tracker (PR #16).
- 2026-10-31: Oklahoma permit history files (`d8_ok_monthly.py`). Privacy fix found while reading the operator list: two reports had named two
  sole proprietors ("... DBA ..."); the rule now refuses a dba and the two days were rebuilt (live within the hour of PR #18).
- 2026-10-31: `publish.yml`: a green merge to `main` is published to `gh-pages` without a capture run (first use: the privacy fix above).
- 2026-10-31: New Mexico's data (`d9_nm_monthly.py`, `NOTES_D9.md`): wells spudded, because the OCD publishes no approval dates by well; its files end 60 days back
  (spud dates arrive late). The Overview shows it (PR #21).
- 2026-10-31: the states bar (All, Texas, Oklahoma) and Oklahoma in the Overview (`states.js`, `overview-data.js`, `overview-view.js`); the owner then asked
  for New Mexico in every view too, so the state layer is built for any number of states (a new state is an entry in `states.js` plus its files).
- 2026-10-31: Operators and Companies follow the states bar (a State column, one ranking, each state's own date; the Texas-only columns and filters step aside).
- 2026-10-31: the Map follows the states bar (one map for any set of states: shapes, dots colored per state, per-state legend, panels and links keyed by state; the Texas-only figures stay Texas only).
- 2026-10-31: New Mexico's Daily report data (`d9_nm_daily.py`, `daily-nm/`): permits approved by day from the OCD layer, 92 days rebuilt (PR #24). Then the view: the states bar's three states in the Daily report (Texas and Oklahoma proved identical to `main` by comparing their DOM); the nightly step is next.
- 2026-10-31: the nightly workflow captures New Mexico's report too (isolated like the others, 64 outcome combinations tested), and `refresh-monthly.yml` refreshes Oklahoma's and New Mexico's permit history weekly. The first runs of both are the ones to watch.
