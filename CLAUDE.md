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

## Standing instruction from the owner, evening of 2026-10-31 (new brief, same permissions)

The owner asked for, and answered the questions about (so they are decided, not open): a **national report** from each state-level agency for oil well permits with unified visuals and all the data together (`#national`);
**every oil-producing state** (EIA's tables: the 30 states in `d11_nat_common.JURISDICTIONS`), **all permit activity** (new wells, injection and disposal, re-entries, reworks, amendments: the bands), and **onshore federal land
(BLM's oil and gas permits)** as its own line, never added into the states; a report of **what metrics each state's permit captures** (form and open data: a matrix, `#fields`); a **separate Texas well-images visual**
with click-downs (`#images`); and **a local database** (a SQLite file built by a script from the committed data, kept out of git, sent to the owner as a file). They are new tabs in the Oil tracker, shipped as separate PRs, national report and matrix first.
Two owner decisions change guardrails below, and are made: (1) the privacy exception is widened for **Texas** images: every document in the RRC's image packs, completion images included, may be published readable
(not Oklahoma's, and no contact list); (2) the Content-Security-Policy may allow GitHub's image hosts for `img-src` so the readable previews load inline. Neither is done until the PR that does it says so and updates README, Privacy.

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
  use the browser. A color, token or layout change also needs `node tests/a11y.cjs` (text contrast in both themes, keyboard focus, nothing cut off and no control under 24 px at 360 px): a state's own color is
  under 4.5:1 as text, so it colors dots, bars and lines and never words.
- **Any `site/pipeline` change:** `python3 -I tests/run_all.py` (add a name fragment such as `d8` to run some), the producer's `--check`;
  a producer change that alters data needs the data regenerated and validated, and the page checked.
- **Any `.github/workflows` change:** extract the `run:` scripts and execute them against a throwaway clone with a local bare repo as
  `origin`; evaluate the `if:` conditions; remember a bad workflow breaks the nightly capture and publish while nobody is watching.
- **Always:** `node tests/smoke.cjs` (browser: every module imports, every view loads clean at desktop and phone width),
  `node tests/a11y.cjs` (browser: contrast, keyboard, nothing cut off and no control under 24 px at 360 px) and `python3 -I tests/run_all.py` must pass locally, and CI (`.github/workflows/ci.yml`, the same commands) must be green on the PR
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
for Texas, Oklahoma, New Mexico and the federal offshore (the Gulf of America), built only from public records (README has the full description and the known limits).

- `site/public/`: the site (`index.html`, `app.css`, `js/*.js` modules, `data/*.json`). `main.js` is the hash router
  (`#overview`, `#national`, `#fields`, `#images`, `#map`, `#operators`, `#companies`, `#daily`, `#about`) and owns the states bar; `states.js` lists the states (a new state is
  one entry there plus its data files, a color token `--st-xx` in `app.css`, a dot skin in `hero.js` and `map.js`, and wording fields where it differs: `short`, `in`, `place`, `drill`,
  `noDaily`, `cadence`, `caveat`, `chgMin`) and keeps the choice (`st=ok` or a list in the address, none is all); `overview-view.js` draws the Overview
  for the states shown from `overview-data.js` (pure merging, tested under Node); `daily*.js` are the Daily report; `geo.js` holds the
  projection (module state, Texas-fitted; each set of shapes carries its own `G.toWorld`, `buildGeoIsolated` builds the others) and the
  shapes and permit points for any set of states; `util.js` has `el()`/`svg()`/`load()`. County keys: Texas plain (`001`), others `OK:001` (the federal offshore's areas `FO:024`).
- `site/pipeline/d11_*`: the national report (`NOTES_D11.md`): `d11_nat_common.py` (the shape of a state's file, the shared tally, validator and `run_producer`), `d11_nat_<st>.py` one producer per state, `d11_nat_build.py` (merges them and the four earlier jurisdictions into
  `data/national.json`). The view is `national.js` + `national-data.js` (`#national`). `fields.js` + `fields-data.js` are the permit-data matrix (`#fields`, from `permit-fields.json`, built by `d11_fields_build.py` from the researched `site/pipeline/fields/<ST>.json`). `images.js` + `images-data.js` are the Texas images view (`#images`, read from the Daily archive).
- `site/pipeline/build_db.py`: the local SQLite database of everything the site publishes (`db/oil-tracker.sqlite`, not in git; `README.md`, "A local database"). Rebuild it with the script; add a table there when a new data file arrives, with a check in `tests/test_build_db.py`.
- `site/pipeline/`: Python producers, standard library only, run with `python3 -I`. `d1`-`d6` build the monthly Texas data,
  `d7_*` the Texas Daily report (RRC), `d8_*` Oklahoma (OCC: `d8_ok_daily.py` the Daily report, `d8_ok_monthly.py` the permit history, `d8_ok_context.py`
  the monthly EIA series, also for New Mexico with `--state NM`), `d9_*` New Mexico (OCD: `d9_nm_monthly.py` the permit history as wells spudded, `d9_nm_daily.py` the Daily report from approvals), `d10_fo_monthly.py` the federal offshore (BSEE, Gulf of America: wells spudded, 63 protraction areas as its "counties", no Daily report: the source is weekly) plus `ok_xlsx.py`. Each has a `NOTES_*.md`: read it before changing it.
- `.github/workflows/daily-rrc-report.yml`: captures the three states nightly (03:15 UTC, backup 04:20), commits the data to `main`, publishes
  `site/public` to `gh-pages`. Each state's capture is isolated (and has a time limit of its own: 25, 12 and 6 minutes in a 60-minute job): if one fails or hangs the others are committed and published and the run ends red.
- `.github/workflows/refresh-monthly.yml`: weekly (Mondays 05:40 UTC) refresh of Oklahoma's, New Mexico's and the federal offshore's permit history files, isolated the same way
  (three refreshes, 64 outcome combinations tested), in the nightly's concurrency group; it commits and publishes by itself. The EIA crude series (`d8_ok_context.py --state OK|NM|FO`) and the offshore's
  map of areas are refreshed by hand.
- `.github/workflows/refresh-national.yml`: weekly (Mondays 06:20 UTC, after the monthly one) run of every `d11_nat_<st>.py` through `d11_nat_run.py` (each isolated, bounded, a failed one restored; a refusal is an answer), then `national.json` is rebuilt and committed. `refresh-monthly.yml` also rebuilds `national.json`
  after its refreshes, because the report reads the Oklahoma, New Mexico and offshore files it refreshes (a test fails if `national.json` is not what the builder makes from the committed files).
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

1. **Watch the first scheduled runs.** The first nightly capture of all three states (03:15 UTC, backup 04:20) and the first weekly `refresh-monthly.yml`
   (Mondays 05:40 UTC) have not run on their schedules yet; each was dispatched once by hand and was green (the federal offshore's refresh step was added later and dispatched once by hand on 2026-10-31 at 21:27 UTC: green in 1 m 43 s, BSEE answered the runner, and the twelve files came out byte-identical to the committed ones, so there was nothing to commit). The three captures (and the three weekly refreshes) are isolated,
   so a failure in one leaves the others committed and published and ends the run red. Look at Actions, at the committed data and at the live site; fix forward at once.
   What is new since those hand runs, and so unproven on the real servers: four independent reviews' fixes. Texas now fails a dataset on a file that is not the file (an empty or HTML permit file, a pending export
   without its columns, a table of no files, a listing not newest first): the status is `partial`, the run stays green (exit 0) and the Daily page says "N of 6 files read" and "could not be read", so read the Daily page and the
   `Capture the report` log, not only the run's color. The six RRC share listings and the End of Month share were read once from this machine on 2026-10-31 and pass the new listing checks; the real Oklahoma inventory, and the Oklahoma and
   New Mexico monthly files rebuilt from the live master and layer, matched the committed ones byte for byte. If the OCC ever really shrinks its inventory by more than 10%, run `d8_ok_daily.py --wells-floor 0` once by hand.
1b. **Watch the first run of `refresh-national.yml`** (Mondays 06:20 UTC, the first on Nov 2) and of the producers it runs (`d11_nat_<st>.py`; the BLM's was run once for real on 2026-11-01, 64 reports, 4 s apart). Each producer is isolated and a failed one keeps last week's file, so a red run
   names what to look at in its log; a server that refuses the runner (exit 2) is an answer, not an error. Fix forward at once.
2. **One state choice across the site: done** (the bar, the Overview, the Map, Operators, Companies (Texas only, and say so), the Daily report (New Mexico's is permits to drill from the
   OCD layer and its well inventory: `d9_nm_daily.py`, `daily-nm/`, `daily-nm.js`; `daily.js` asks what a report holds, `HORIZ`, `PERMIT_FROM`, `SERIES`, not which state it is) and Sources).
   Views still describe themselves as Texas where they are Texas only; each loses that wording when the others reach it. Never add New Mexico's or the offshore's spuds to the other states'
   permits (`states.js` measures: `sameMeasure`).
3. **Not available yet** (the pages say "not available", never zero): Oklahoma, New Mexico and offshore jobs (BLS), rig counts (Baker Hughes), production by county, companies (no public bulk source like the
   Texas Comptroller's), New Mexico's and the offshore's depth, New Mexico's filing dates, completions and transfers, any Daily report for the offshore (BSEE's file is weekly), the offshore's production by area or operator (the EIA's statewide offshore crude series is all there is).
   Counted but not shown by county or operator: the Oklahoma and New Mexico well inventories.
4. **Texas's monthly files are rebuilt by hand** (`d1` to `d6`, `build_data.py`: a 3.7 GB production dump and lead lists with contact details make it unfit for a workflow). The Overview says how old they
   are. Refreshing Texas's permit master the way Oklahoma's is (a weekly workflow) would be the next freshness win; the production and company files would stay by hand.
5. **Visual polish and simplification.** Done: contrast, keyboard, phone reflow and target size (`tests/a11y.cjs`, in CI), the tabs' edge fade, Operators and Companies, the Daily report's first screen and
   cards on a phone, print. Looked at again in the evening of 2026-10-31: every view in both themes at both widths (nothing found but the button labels below). To do: more phone passes on the Daily report's long cards; look at every view again in dark mode after any color change.
6. **Known and left alone** (each written where it matters): a cron start more than 1 h 45 min late (past Central midnight) writes the next day's report and does not refresh the evening of the day before (`NOTES_D7.md`; the 04:20 backup covers a late start);
   the Map shows only "Could not load the map data" if one state's file is really gone (drawing the other states is a possible next step; a dropped request is already retried once); the Sources page fetches the production files for one sentence
   (they are the Map's and Operators' files, so they are cached); Texas's `read_daf` treats a Daily Permit File with no record as unread, which is right except possibly on the first hour of a month (the 04:20 backup retries).
7. **Hardening not done on purpose before the first unattended nights** (found by the fifth review, a security pass; each changes how the workflows authenticate, so each wants its own checked PR): `persist-credentials: false` on every checkout with the token given only to the steps that
   push or upload (the capture steps parse downloaded files and hold a write token today); the actions pinned to commit SHAs and `pillow` installed with `--require-hashes`; a job-level `if: github.ref == 'refs/heads/main'` on both publishing workflows (a manual dispatch from another branch
   would commit to it and publish its site). The names of two sole proprietors remain in git history (README, Privacy): only the owner can decide on a history rewrite.

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
- 2026-10-31: polish: each state's color in the states bar (and in its operator sparklines), the Overview's dates and hero note shortened for several states.
- 2026-10-31: honesty and phone polish: New Mexico's newest permit days (which the layer fills in over a few days) are not set against an average of complete days, and a ticker card's label wraps on a phone instead of ending in an ellipsis.
- 2026-10-31: New Mexico's Daily report gets the well inventory (counted by the server, live days only), so it has the same four cards as Oklahoma's.
- 2026-10-31: accessibility: `tests/a11y.cjs` (text contrast in both themes at both widths, keyboard focus, titles; in CI) found and fixed the primary button's white text (3.5 to 4.6:1),
  a state's own color used as words in the Overview's lists (now ink with a colored dot), the grey "Publishes monthly" tags, the light theme's red for falls and the search placeholders;
  the tabs fade at the edge that has more on a phone; the Companies note under the heading is a quiet line; an operator's Map chip stays with its name.
- 2026-10-31: the Daily report on a phone: one pill per state (the time its files were read is inside it), sparklines and notes that fit a half-width card (a note was cut off, a sparkline ran past the card), and a card never left alone in half a row.
- 2026-10-31: the Operators CSV no longer turns a negative number into text (a fall of -14.4 had a spreadsheet guard's apostrophe), and `a11y.cjs` gained a reflow check at 360 px that found the Daily cards' clipped notes.
- 2026-10-31: a walk through the archive's days found "NaN%" in the verbose report on a day with an empty Texas queue (Aug 9, Sep 7), and a random-click run found "NaN ft" in the Map's legend for New Mexico's depth (it publishes none: the legend and the list now say so); fixed, and smoke now walks the archive and every map metric under three state sets for NaN, undefined, null and Infinity. The browser's own bar takes the page's color (`theme-color`, kept in step with the theme).
- 2026-10-31: touch targets: the Map chips, the column sort buttons and the "Open the map" links were 20 to 22 px high on a phone; all controls are 24 px or more (WCAG 2.2) and `a11y.cjs` checks it.
- 2026-10-31: the Sources page's 28 external links were fetched once by hand: 22 answered, 5 are bot-blocked pages that answer a browser (Baker Hughes, BLS CEW, FERC, PHMSA, SEC), and one was dead (the Secretary of State's bulk-orders help page): repointed. No test does this (the tests use no network).
- 2026-10-31: the Daily report warns when its newest report is two or more days behind today's date in Central ("the nightly capture may have failed"), so an unattended failure shows to a visitor instead of an old day passing for today's.
- 2026-10-31: print: a Daily report (or the Overview) saves as a PDF in light colors without the header, the states bar, the controls or the buttons, each card kept whole (`@media print` at the end of `app.css`).
- 2026-10-31: a data file whose request is dropped (a phone between towers, a server hiccup) is tried once more after 0.7 s (`util.js` `load`); a missing file (HTTP 4xx) is not retried, since the optional files are meant to be missing sometimes. Found by aborting each file in turn: no view threw, but the Map showed only "Could not load the map data" for any one of Oklahoma's or New Mexico's files (it still does if one is really gone: drawing the other states is a possible next step).
- 2026-10-31: an independent review of New Mexico's nightly producer (a fresh agent, offline, with repro scripts) found four real defects, each confirmed and fixed with a test that fails without it: every live report kept its first,
  low permit count for good (the layer is entered late: 5 to 15 stored against 20 settled; each night now recounts the permits of the reports it can still see), a second capture of a day could replace a complete inventory with
  none, one county code outside the 33 failed the whole night's check, and the inventory's groups were overwritten instead of added with nothing checking that they add up.
- 2026-10-31: `publish.yml` steps aside when main's tip is no longer the commit CI passed (the nightly's data commit, a weekly refresh, a later merge), because that newer commit's publish includes it and this one would put an older tree over the newer data until the next publish (the review's fifth finding; a guard that cannot read main's tip publishes as before).
- 2026-10-31: a second independent review (a fresh agent driving the pages in a browser against the honesty rules) confirmed and we fixed: the Daily county map's tooltips said "0" for a state with no such layer (New Mexico's completions, Oklahoma's queue, Texas's inventory: now "Not available"); "Other filings" read 0 for New Mexico and the amended-permits figure added two states without saying so; the pace chart's spoken summary put one day on a sum of three states' different days; the archive calendar summed fewer states than shown without saying which; the Overview's chips and aria-labels called New Mexico's spuds permits and the Active wells chip printed one state's date for all; a Map operator panel said "Showing 621 of 618"; an address naming two states left "All" lit with no note; a degraded Overview named a state's date it had no series for. Left as designed, because each is labeled: the Operators page ranks the states in one list (New Mexico rows are spuds, tagged and named in the lede), the Map's "Permits and spuds" metric and its replay counter, and the Overview insights that name each measure.
- 2026-10-31: a third independent review (a fresh agent, offline, with repro scripts) of Oklahoma's producers and the workflows confirmed and we fixed, each with a test that fails without it (`tests/test_d8_nights.py` runs whole nights with the network faked): a permit whose API number gives no county (blank, short, another state's) crashed the whole night; an inventory file that was an error page, empty, header-only, renamed or cut short (under 90% of the last count) was published as the inventory; a later capture of a day that read fewer files replaced the report that read more; a master file that could not be read still left the report `ok`; a rebuilt day written partial was never built again; a failure's text carried the web address into the data files; the permit workbook's rows per formation were counted as permits; one renamed figure column failed the whole completion file; spellings of a person trading under a name the rule missed (`d b a`, `db/a`, `doing business as`, `aka`...); an approval dated in the future would have ended every window of the monthly files; the monthly validator did not look at a city, a state or a phone number; and no capture step had a time limit.
- 2026-10-31: a page-weight audit (Chromium, each view at desktop and phone width): 204 to 765 KB gzipped per view and quiet in about a second on localhost, so nothing was changed (the Sources page fetches the production files for one sentence, but they are the Map's and Operators' files and are cached); a visual pass found one small defect, a button label split into two flex items ("Share  this view", "Watch  drilling", "Copy  link" had the icon's gap between the words), fixed, with a smoke check that fails without it; and a smoke check that flaked once (a hash change is not a new page) now reloads.
- 2026-10-31: a fourth independent review (a fresh agent, offline, with repro scripts) of the Texas producer and its workflow steps confirmed and we fixed, each with a test that fails without it (`tests/test_d7_nights.py`, built on the reviewer's harness): a cut-short or odd reply from the RRC map service ended the whole night after every download was done (and a refusing service was asked again for every report day); a backup run that read fewer files, or lost the document links, replaced the better report; a rebuilt day written partial was never built again; one damaged file in the archive crashed every later night; and a server's error page and a runner path were published in the day files. Part 2 of the same review: a stray file name or an impossible date failed a whole dataset, and a zip named for a later day won; files delivered but not the file (an empty or HTML permit file, a pending export without its columns, a zip of non-packets, a table of no files, a listing that is not newest first) were read as a quiet zero with status ok; repairing a day more than 3 days old wrote it without its pending queue and image packs (status ok); and a hung request could hold the night until the step was killed with nothing written (the capture now has a 19-minute limit).
- 2026-10-31: following the Texas review: a Daily card now says "The pending files could not be read for this day" (and "Texas: the completion files could not be read") when a file failed, instead of "No pending set recorded" or "No completion filings", which are claims about the commission; with the Texas producer now failing a dataset on a file that is not the file, a partial day is more likely to show. Smoke block 16 stubs the files as unread and fails on the old wording.
- 2026-10-31: the monthly builder (`d8_ok_monthly.py`) publishes an operator's office city or state blank when the file's value is not a place name or two letters (`office_place`), so a stray `N/A` or an address costs that operator its city and never the Monday refresh (the validator added after the third review would have failed the whole refresh on it; the real daily workbook's cities all pass); Oklahoma's transfers card says "could not be read" like the others.
- 2026-10-31: rehearsals against the real servers from this machine, a few polite requests each: the real Oklahoma well inventory (121 MB) read by the new reader gives the committed totals; Oklahoma's and New Mexico's monthly files rebuilt from the live master workbook and the OCD layer are byte-identical to the committed ones and pass `--check`; the six nightly RRC share listings and the End of Month share come back newest first with every time readable (the new listing checks pass; one dropped TLS handshake on the End of Month share was not repeated on the next try); the 156 real pending files, the real permit file and the real completions zip pass the new header and record checks. Every combination of missing or unread sections of each state's newest day draws in the Daily report (288 loads, simple and verbose, one state and all three) with no error, NaN or undefined; the smoke and accessibility tests pass three at a time (no timing flakes left).
- 2026-10-31: a fifth independent review (a fresh agent, offline: secrets and personal data in the tree and the whole git history, the workflows, the pipelines, the static site's XSS and CSP, the CSV export, every published data file) found no secret, no XSS, no injection and no live personal data, and these, fixed here with tests that fail without them (`tests/test_privacy_gate.py`): the nightly's own `--check` read no text for Texas or Oklahoma and only an address for New Mexico, so a night that named a sole proprietor or held an e-mail address or a phone number would have been committed and published (now `privacy_check.py`: every day file is scanned and every published operator name held to the state's rule, in all three); one company's `city` held a street address (blanked, and `build_data.py` now publishes only place names); New Mexico published a server's raw error text (now `clean_error`, shared, which also strips an error page's markup and a path); the PDF parser's child process inherited the repository token (now scrubbed); and the About page's privacy sentence did not mention the drill pages' linked documents. Left for the owner or a checked PR (backlog 7): the two sole proprietors' names in git history, the workflow token and credential scoping, action pinning, and a main-only guard on the publishing workflows.
- 2026-10-31, 20:30 UTC: the 10-hour mandate ended and its hourly trigger was deleted (the standing permission at the top stays). State at the end: PRs #12 to #43 merged with CI green, no open PR, the live site equal to `main`, 16 Python test files, the JS data tests, the smoke test and the accessibility test green on a clean clone, five independent reviews fixed. Ahead and unattended: the first scheduled nightly (03:15 UTC, backup 04:20) and the Monday refresh (Nov 2, 05:40 UTC); backlog 1 says what to read, backlog 6 and 7 what was left alone on purpose.
- 2026-10-31, after the mandate, at the owner's request ("also add in federal offshore if you can find it"): the federal offshore (Gulf of America, BSEE) as a fourth source, staged in three PRs. Stage 1: the producer `d10_fo_monthly.py` (`NOTES_D10.md`, `tests/test_d10_fo.py`) builds `series-permits-fo.json`, `county-permits-fo.json`, `operators-fo.json`, `permits-fo.json` and `counties-fo.geo.json` from BSEE's weekly borehole file, its company file and its 63 protraction areas: wells spudded (about 45 a year, 16 operators, no depth, a 60-day lag), because the approvals are only an online query; a Daily report is not possible (the file is weekly). The privacy gate covers its files. Stage 2: the site. `states.js` has the fourth entry (with `short`, `in`, `place`, `drill`, `noDaily`, `cadence`, so every page says "areas", "the federal offshore", "Watch the Gulf drill" and "Publishes weekly" where it should), a rose `--st-fo` picked by distance from the other three colors, the states bar reading TX, OK, NM and Offshore below 440 px so all five fit a phone, Gulf city labels on the map, the Sources page, and smoke block 17 and the a11y views for it. The Daily report is untouched (it shows the three states that have one and says why the offshore has none). Stage 3: the offshore's files join the weekly refresh (a third isolated refresh, check and drop step in `refresh-monthly.yml`, 64 outcome combinations in `tests/test_workflow_monthly.py`), and the EIA's offshore crude series (`MCRFP3FM1`, `series-fo.json`, 64.3 million barrels in Aug 2026) gives the offshore a crude chip, an insight, a Production panel and a freshness line, like Oklahoma and New Mexico. The workflow was dispatched once by hand to prove it (2026-10-31, 21:27 UTC: BSEE answered the GitHub runner, the offshore's, Oklahoma's and New Mexico's twelve files came out byte-identical to the committed ones, nothing was committed). The first scheduled Monday run is Nov 2 at 05:40 UTC; a week that BSEE makes a new file is the first that changes them.
- 2026-10-31: an independent review of the offshore (a fresh agent, offline: the data recounted from the raw BSEE file, the producer fed damaged copies, the pages driven in a browser against the honesty rules) found, and PR A fixes with tests that fail without them (`tests/test_d10_fo.py`, `test_d9_nm.py`): the company file's last row for an operator is not its current name (71 of 449 operators changed name; 2 recent ones would have been published under an old name); a truncated, re-laid-out or company-less file was accepted (95% of the rows: exit 0, a third of the history gone), so `guard()` now refuses before writing (`NOTES_D10.md` lists what); the areas file was trusted (now each feature carries its two-letter code and a run refuses one that is not the 63); two areas had one name ("Sabine Pass"); a street or a P.O. box in a name passed the privacy gate (offshore names only); `isdigit()` crashed on a superscript digit; and a year was 365 days for the counties and the operators but 12 calendar months for the series, so one page said 47 against 44 (New Mexico had the same, its files rebuilt): a month-end file now counts calendar months (`calendar_windows`). The source text now says how many boreholes were spudded against the wells counted (sidetracks and bypasses are drilling, not new wells: Cantium sidetracked 10 times and shows no new wells). Left alone: the areas' shared borders are not one line on both sides (cosmetic; the raw shapes share only 3% of their edges), and the review's suspicion that a step killed by `timeout-minutes` reports `cancelled` (the runner reports a step timeout as a failure; not seen on a real timeout). PR B, the pages (`states.js` helpers `measureAnd`, `everyOf`, `dotName`, `countWord`, `ucFirst`, `spudCaveat`, `chgMinOf`; each state names what it counts): the offshore's spuds were called permits and its areas counties (the map's lede and notes, "a permit dot", every band tooltip, "Last permit", the hero's eyebrow); the map's change list ranked areas on 20 permits that no area has (a `chgMin` per state: 5 offshore) and showed an empty heading; an area with no wells said the Bureau published no location (it now says none was spudded); "Eugene Island area 1 spuds"; "Federal offshore" inside sentences is "the federal offshore"; the Production note ran two states' sentences together; the states bar clipped its last button between 441 and 459 px and below 330 px (a fixed breakpoint passed here and clipped in CI, whose system font is 8% wider, so the bar now measures itself: `ui.js` `data-fit` full, short, tight; smoke sweeps 320 to 1280 px); the Sources page's offshore figures (the date, the year's wells, the operators, the EIA's month) are filled from the files (`fillOffshore`) and its Texas Gulf-permits sentence no longer reads as the federal offshore's; what a sidetrack is (the state's `caveat`) is said on the Overview, the Map, the Operators page, the Activity chart's note and Sources. Left alone: the Operators CSV's column names (each row says what it counts in `counts_are_of`).
- 2026-11-01, found by looking at the whole site at 761 to 1100 px after the National and Texas images tabs were added (eight tabs where the header was built for six): between 761 and about 1000 px the tabs and the theme toggle ran off the page (the page scrolled sideways, the brand's column shrank to nothing) and the brand's tagline was cut off ("Oil and gas drilling permits, st...") at every desktop width. The header now measures itself like the states bar (`ui.js` `headerLayout`, `data-fit` on `.top-row`: full, with the tagline; row; compact, tighter tabs; stack, the tabs on a row of their own, scrolling when they must), so it also survives the next tab and a wider font (the tabs need 788 px in one font, 874 in another); the tagline is "Oil and gas permits by state". Smoke block 16b sweeps 13 widths from 360 to 1920 px. Checked at 761, 900, 1100 and 1280 px with Inter, DejaVu Sans and DejaVu Sans made wider (CI's own font stacked the header at every width until `compact` was added, so the smoke test asserts only what holds in every font).
- 2026-11-01: the tabs bring the current tab into view only when it is not already (they moved for every tab, so on a phone the first tabs were hidden as soon as one of them was chosen: now they stay put while they fit); the header ignores height-only resize notifications (stacking changes its height, which must not ask for another layout). Smoke block 6 asserts both for all nine views at 390 px.
