# NOTES_D11: the national report (every state agency's permits, side by side)

Scripts: `site/pipeline/d11_nat_common.py` (what every state producer shares), `d11_nat_build.py` (the merge into `national.json`) and, per state,
`d11_nat_<st>.py` (added in waves). The page: `site/public/js/national.js` (the view) and `national-data.js` (pure data code, tested under Node).
Owner's brief (2026-10-31): a national report from each state-level agency's permits, unified visuals, all data together; every oil-producing state;
all permit activity (not only new drills); onshore federal land (BLM) too.

## What a state file is

`site/public/data/nat/<ST>.json`, one per state, written by that state's producer through a `Tally` (shape documented at the top of `d11_nat_common.py`):

- `measure`: `permits` (counted by the day the agency approved or issued the permit) or `spuds` (counted by spud date, for agencies that publish no approval
  dates by well, as New Mexico and the federal offshore already do). Counts of the two measures are **never added together**.
- `bands`: monthly counts by kind of permit: `new` (a new well to produce or explore), `inj` (a new injection, disposal or service well), `redrill` (re-entry,
  deepening, sidetrack), `rework` (recompletion, plug-back, workover, conversion), `amend` (amendment, revision, extension, transfer), `other`. A permit is in exactly
  one. **A band the source cannot tell is `null`, never zero**; `new` is always there. `band_of(work, purpose)` is the shared classifier (amendments are recognized
  first, so an amendment of a new-drill permit is an amendment).
- `fluid`: the last 12 months of new wells by recorded fluid (oil, gas, both, other, unknown), or `null` where the state records none. This is how "oil wells" is answered
  without pretending every agency knows the fluid at approval time.
- `counties` (top 15 places) and `operators` (top 15, **only corporations, LLCs and partnerships**: the one naming rule, `d8_ok_daily.nameable`, never a person's dba),
  with `namedShare`, the share of the year's new wells whose operator may be named. No API number, lease or well name leaves a producer.
- `months` run from 2019-01 to the last **complete** month (a spud-counting state ends by its lag, 60 days by default), `through` is that month's last day, `asOf` the newest record.

`validate()` refuses a file that breaks the shape, names an operator the rule refuses, holds an e-mail, phone or ten-digit number (outside the source address), has one wildly
large month (a parse error) or no new permit in 24 months (a producer that read nothing must not write a file). `write_doc` validates before writing, so a bad night leaves the
committed file alone; `run_producer` is the one `main` every producer uses (exit 0 written, 1 failed, 2 refused by the server; `--check` reloads what is committed).

## national.json

`d11_nat_build.py` merges the state files and adapts the four earlier jurisdictions (Texas, Oklahoma, New Mexico, the federal offshore: their series, operator and county files
become `new` only, the other bands are null) onto one axis (2019-01 to the newest month any state reaches; a state that ends earlier is padded with `null`, not zero). Each state
gets `p12` and `prev12` (its own last 12 complete months and the 12 before), `mix12`, `fluid`, counties and operators. A jurisdiction with no data is a **gap** (with the research's agency,
grade and reason once `permit-fields.json` exists), never a zero. `totals` add within a measure only, and **never include the BLM** (`OVERLAP`): the BLM approves permits for
wells on federal land that the states also permit, so adding them would count the same wells twice. The BLM is a line of its own.

## The view

`#national` (it does not follow the states bar: the bar picks among four jurisdictions, this view is all of them). A tile map of the states (shaded by each state's size against the
biggest state counting the same thing; underlined tiles count spuds; dashed tiles are producing states not read yet; plain tiles produce no oil), a panel for the chosen state (agency,
12-month figure and change, 36-month sparkline, kinds of permits where the state can tell them, top counties and operators, source and, for Texas, Oklahoma, New Mexico and the offshore,
a link to the full Overview), the months stacked by state (a toggle between permits and spuds; the axis ends at the newest month every plotted state has, so a late reporter does not read as
a fall; the BLM is not stacked), a ranking, the mix of kinds of permits (only drawn once a state has one) and a coverage table of every jurisdiction. Colors follow the entity, not its rank:
Texas, Oklahoma, New Mexico and the offshore keep their colors from the rest of the site; the other big producers take the next palette slots; the rest fold into "Other states".
Addresses: `#national?s=ND&m=spuds` (state, count). Every chart has its table twin.

## The weekly run

`.github/workflows/refresh-national.yml` (Mondays 06:20 UTC, after `refresh-monthly.yml`, in the nightly capture's concurrency group) runs `d11_nat_run.py`, which finds every `d11_nat_<st>.py`, runs each in its own process
(`python3 -I`, no token in its environment, `D11_NAT_DIR` pointing at the folder it may write) under its own time limit (10 minutes by default; `TIMEOUTS` for a big download) and a 40-minute budget for the whole run. Per producer:
`wrote` or `unchanged` (a good file), `refused` (exit 2: the server said no, or the network is blocked: **an answer, not an error**; the earlier file stays and the summary says so), or `failed` / `invalid` / `timeout` / `skipped`
(the producer's file is put back exactly as committed, or removed if it is new; the run exits 1 so the workflow shows red after the commit and publish). Then `national.json` is rebuilt from whatever files survived (and put back if the rebuild
fails). A state whose producer fails keeps last week's file; its `asOf` and `through` say how old it is. `refresh-monthly.yml` rebuilds `national.json` too (it refreshes the Oklahoma, New Mexico and offshore files the report reads).

## The BLM (onshore federal land): `d11_nat_bl.py`

The BLM's per-permit system (AFMSS) is login-only, so the producer reads what the BLM publishes free: a monthly "Application for Permit to Drill Status Report" PDF with APDs received, pending, processed and **approved** by BLM state
office, monthly from April 2021 (the earlier years are annual and the October and November 2022 reports were never linked, so the series that is shown starts in December 2022). It reads them with `pdftotext -layout` (poppler-utils),
by heading because the columns moved between 2022 and 2023, and the period line because from 2024 its second date sits on the next line (found by the first real run, which refused to write until the parser read all 64 months).
What the line is: **APDs approved** (new drills and re-entries together), **by BLM state office, not by state** (New Mexico's covers Oklahoma, Kansas and Texas; Montana's covers the Dakotas; every office counts federal and tribal lands),
so it is a line of its own and **never added into the states' totals** (`OVERLAP` in `d11_nat_common.py`: the states permit most of the same wells). Last 12 months (to Sep 2026): 5,599 APDs approved against the BLM's own fiscal-year
total of 5,602. Each week the last 14 months are read again (a month's report can be revised); older months are kept from the committed file. Nothing here names an operator.

## Six more states: Arizona, Indiana, Kansas, Kentucky, Nevada, West Virginia

Each is one file, `d11_nat_<st>.py`, with a test (`tests/test_d11_<st>.py`), and was run once for real from this project and checked against a count the agency publishes itself. What each counts:

| State | Source | Counts | Tells | Last 12 months | Independent check |
|---|---|---|---|---|---|
| Arizona | the ArcGIS layer behind the Commission's map (one request) | **spuds** (the layer has no approval date), 60-day lag | new, inj, other; fluid | 0 new (none spud since June 2023: `zeroOk`) | the layer's DRILL_END_DATE gives the same yearly counts for 2020 to 2023 |
| Indiana | the Division's weekly "Permits Issued" PDFs (`pdftotext`), 353 lists from Jan 2020 | permits by issue date | all six bands; fluid | 48 new wells | the Division's own monthly reports match the weekly sums for five months checked |
| Kansas | the KGS "Oil and Gas Wells" layer (the KCC's own site refuses scripts) | permits by notice-of-intent date | new, inj, redrill, other; fluid | 586 new | the layer's yearly rows equal the KGS well-statistics table; month by month equal to a second snapshot |
| Kentucky | the Division's weekly permit lists (.xls and .xlsx, a small .xls reader is inside the producer) | permits by issue date | new, inj, redrill, rework, other; fluid | 64 new | 13 of 1,039 permit numbers are on no list (the Division's omission, in the note) |
| Nevada | the Division of Minerals' Permits page (six years of PDFs, hand-updated), 30-day lag | permits by approval date | new only | 2 new | the Division's well layer's highest permit number equals the page's newest |
| West Virginia | the Weekly Permit Report zips (404 weeks), not the TAGIS layer (one New Drill row in nine is repeated there) | permits by issue date, by week | new, rework, redrill, amend, other; no inj, no fluid | 265 new | de-duplicated, the layer agrees within 2% (265 against 265 in the last 12 months) |

Things to know:

- **First reads are by hand, and committed.** Kentucky (17 minutes), Indiana (9) and West Virginia (30) read one file a week, two to three seconds apart; the history was read once and `nat/KY.json`, `IN.json` and `WV.json` are committed. A weekly run
  re-reads only the newest 14 months of weeks (about 3 minutes each, checked identical to a full read), under a 900-second limit in `TIMEOUTS`. Without a committed file they time out here, by design: a bootstrap is run by hand
  (`D11_NAT_DIR=<an empty folder> python3 -I site/pipeline/d11_nat_<st>.py`, then the file is committed).
- **A run fails, and the committed file stays,** when a layout changes, a list is missing (Kentucky: a skipped Friday or a newest list over 45 days old; West Virginia: more than 8 weeks missing), or the count is implausible.
- **Defects in the agencies' files are told in each file's `note`** (Indiana's two index weeks that point to one PDF and one page that prints three permits on top of each other; West Virginia's three weeks never posted; Kentucky's omitted permit numbers;
  Nevada's early-2021 numbers with no date), never smoothed over.
- Nevada publishes no company in a form that can be read (free text inside a link title), so it names no operator and no county (`namedShare` is null); Arizona names none because there were no new wells to name.

## Mississippi (withheld)

`d11_nat_ms.py` was written and tested (the Board's shapefile and well list, joined by API number in memory) but is **not** in the repository's producers, because its count is lower than the Board's own yearly "Permits to Drill" report
(59, 48, 22 and 29 wells for 2022 to 2025 against the Board's 88, 67, 50 and 37): the shapefile holds only located wells, and expired and cancelled permits are not in it. A figure that is 30 to 55 percent short, published beside agencies' full counts,
would read as a fall. Mississippi stays a gap in the report ("not read yet", with its researched grade) until a file with every permit is found (the yearly PDF report is one candidate: a table of county by month, which a producer could read).

## Known limits

- Texas's monthly series is application type 01 only; it says nothing about the other bands (its Daily report holds only the last 92 days). Oklahoma's, New Mexico's and the offshore's the same.
- The 12-month figures are each state's own last 12 complete months, so a spud-counting state's window ends two months before a permit-counting state's.
- The tile map is a cartogram, not geography: no state outlines are loaded (no external requests).

## Run

```
python3 -I site/pipeline/d11_nat_build.py            # rebuild national.json from the committed files
python3 -I site/pipeline/d11_nat_build.py --check    # reload and validate it and every nat/<ST>.json
python3 -I tests/run_all.py d11                      # the tests
```
