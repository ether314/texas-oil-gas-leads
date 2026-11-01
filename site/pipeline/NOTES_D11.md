# NOTES_D11: the national report (every state agency's permits, side by side)

Scripts: `site/pipeline/d11_nat_common.py` (what every state producer shares), `d11_nat_build.py` (the merge into `national.json`) and, per state,
`d11_nat_<st>.py` (added in waves). The page: since 2026-11-02 the report is part of the one Overview (`#overview`: `overview-view.js`, `overview-cards.js` and `combined-data.js`, which show it beside the FracFocus wells; `national-data.js` is the pure data code of this file, tested under Node). The old `national.js` and the `#national` address are gone (the address redirects to the Overview); the section "The view" below describes the page as it was and is kept for the reasoning behind each rule.
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
- `counties` (top 15 places), `operators` (top 15, **only corporations, LLCs and partnerships**: the one naming rule, `d8_ok_daily.nameable`, never a person's dba) and `operatorsAll` (added 2026-11-01:
  every such operator with a `new` permit in the last 12 months, same ranking, the first 15 being `operators`, at most `MAX_OPERATORS` = 1,000; the Companies page lists it, and `national.json` keeps only the 15 so the Overview and the National page stay light;
  `validate()` checks it is ranked, nameable, without repeats, begins with `operators`, holds no more permits than the year had and, when nothing is cut off, exactly `namedShare` of them; a file written before it existed has none and is still good),
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

## Ten more: Alaska, Arkansas, California, Colorado, Idaho, Mississippi, Montana, Nebraska, Ohio, Tennessee

All eleven jurisdictions that had no data on 2026-11-01 were looked at again that day, ten of them built, each by its own agent, run once for real, and checked against a count the agency publishes. **Missouri is the one that stays a gap, on evidence (below).**
Several of the researched "blocked" sources were not: the first research hit a 403 from a tool's agent string, a `https` address that resets while `http` answers, or a link that holds backslashes (curl sends `\` as `%5C`, a browser as `/`).
Each producer has a test (`tests/test_d11_<st>.py`, 80 to 150 checks, each rule with a mutant that fails without it). What each counts:

| State | Source | Counts | Tells | Last 12 months | Independent check |
|---|---|---|---|---|---|
| Alaska | the Data Miner's "ZIP (All Data)" files (`wellhistory` and `wells`, two requests, 9 s) | permits by approval date (a sidetrack and a lateral each have their own permit, so 90 to 190 a year) | new, inj, redrill, other; fluid | 54 new (52 before; 155 permits of every kind) | the AOGCC's 2020 chart: 89 permits and 36 Arctic Slope oil producers, exact; a 2018 figure read from a search snippet is 175 against 180 in the file, unexplained |
| Arkansas | the AOGC's weekly "Permit and Completion Reports" (Excel from mid-2020, PDF before; 403 files, a weekly run reads the newest 14 months: 62 requests, 227 s) | permits by week, in the month that holds most of its days | new, amend, redrill, other; no inj, rework or fluid (no well type) | 28 new (37 before) | the permit-number sequence runs one number per application: the lists hold 308 of the 312 numbers from 2019 to Oct 2025 (2024 and 2025 complete) |
| California | CalGEM's WellSTAR Notices layer (5 requests, 3 s apart) | permits by approval day (a California day); the layer starts 14 Nov 2024, so the series is 24 months | new, inj, redrill, rework, other; fluid | 372 new (2 before: almost no new-drill permit was approved in 2025) | the producer's own checks (rows, statuses, dates, a stale layer); no second count |
| Colorado | the ECMC "Wells (API Spots)" map layer (6 requests, 18 s) | **spuds**, by a well's first spud date (the Commission publishes no history of approval dates: its permit search shows 12 months and its files are snapshots of open permits) | new, inj, other; fluid is mostly unknown (71% of new wells have no class yet) | 667 new (680 before) | the Commission's "Annual Well Starts by County": 2025 707 here against 704, 2026 to Sep 492 against 491; 2019 to 2022 run 2.3 to 6% under (not explained); the same check runs inside every run |
| Idaho | the Commission's Well and Facilities Files (the index and one page per well: 35 requests, 2.5 min) | permits by approval date, from the Permit to Drill file's name | new only | 3 new (0 before; 8 since 2019) | the Commission's quarterly "APDs Approved", month by month from 2021 to mid-2025; one permit the Commission counted twice (Oct 2020) is counted once |
| Mississippi | the Board's Permit Search register (one request, 5,540 permits since 2019) and its Well info list (the well type, in memory only) | permits by approval date | new, inj, rework, amend (a change of operator), other; no redrill | 27 new (31 before) | the Board's yearly Permits-to-Drill sheets, read as a check on every run: 2024 (50) and 2025 (37) month by month, 2023 66 against 67, 2022 90 against 88 (two cancelled originals with replacements) |
| Montana | the Dataminer's Well History export (4 requests, 16 s) | permits by approval date | new, inj, redrill, amend; no rework (workovers are sundry notices) | 186 new (47 before: 185 permits to drill so far in 2026 against 62 in all of 2025, in both the history and the weekly letters) | the Board's annual reviews: "Wells Permitted" exact for 2019 to 2023 (79, 37, 41, 54, 58), 66 against 67 for 2024; re-issued permits match in all years; 218 of 225 entries in the 2026 weekly letters match |
| Nebraska | the Commission's yearly "Drilling Permits" PDFs, over plain `http` (5 requests a run) | permits by the date on the list; a year's list is posted after the year closes, so the series ends **Dec 2025** | new, inj and redrill (lower bounds: the lists print no well type) | 17 new (calendar 2025; 28 before) | the Commission's own yearly summary: 17, every county equal; 2021 54 against 53 and 2022 59 against 58 |
| Ohio | ODNR's Permit and Plug List: the search form and its Excel export (a weekly run re-reads the newest 15 months: 3 requests, 59 s; the first read is year by year, 232 s) | permits by issue date, plug permits left out | new, inj, redrill, rework, amend, other; fluid null | 269 new (281 before) | ODNR's annual reports: plug permits 325 of 325 (2019); permits 0.8% to 4.1% under (2019 to 2021: voided applications, a guess) |
| Tennessee | the Division's map layer of every oil and gas permit since 1968 (2 requests), the same table as its Data Viewer | permits by permit date, 60-day lag | new only (no type of permit; most permits are for wells recorded as dry holes) | 44 new (28 before) | the viewer's newest 500 permits and the layer give the same yearly counts; permit numbers are contiguous; no TDEC-published yearly count could be read |

Things to know:

- **Agent strings.** `polite_get` sends `Mozilla/5.0 (research script)`. The one honest alternative, `Mozilla/5.0 (compatible; oil-tracker research)` (no person, no browser claim), is used by Tennessee's producer only, because TDEC's hosts refuse the default; it is the only allowance, and a refusal that remains is an answer (exit 2, the committed file stays). Colorado's website refused the default too, but its producer reads two map hosts that answer it.
- **Mississippi's register is read through an endpoint that runs whatever SQL the page sends it** (`ajaxloadPDO.php`: the page posts its own query, base64, and gets JSON). The producer sends only the page's own fixed read-only `SELECT` (view `rptPermit`, six columns, two ISO dates) and nothing else. That the endpoint would run any SQL is the Board's exposure, not ours; do not send it anything else.
- **Idaho fails its weekly run on purpose** when a permit is marked revised, or its file name's date does not fit its page, and is not in `ORIGINAL_APPROVAL` (two amended permits whose first approvals are June 16 and Nov 17, 2021 are held there): a person must read the letter and add the date. A red Idaho run is not a server problem.
- **Ohio**: the search and the export cap at exactly 1,000 rows (a window that reports 1,000 is split; a capped week fails the run); the export lists many applications twice, identical in every column (353 rows for 275 in 2020), so they are counted once by application number (read for that only, never kept); the server redirects about one request in three to the agency's home page, so the client waits and tries four times, then exits 2. Ohio imports its `.xls` reader from `d11_nat_ky.py`.
- **Nebraska ends ten months before the daily states** (the Commission posts a year's list after the year closes; 2026's is expected in Jan to Apr 2027). Its 12-month figure is calendar 2025, so the report's totals add it beside windows that end in 2026; the page says each state's window. The plain-`http` address is the one that answered here; whether a GitHub runner reaches it is unverified (a reset ends that run red, the file stays).
- **Colorado is a spuds state**: it is added into the spud total, never the permit total, and never into the other states' permits.
- **First reads and the weekly run.** Alaska, Colorado, Idaho, Mississippi, Montana and Tennessee read their whole source each run (a few seconds to 2.5 minutes). Arkansas, Nebraska and Ohio read the newest weeks or years and keep older months from the committed file; Arkansas's first full read (about 30 minutes) and Ohio's (about 4 minutes) were done by hand once and committed. `TIMEOUTS` gives Arkansas and Ohio 900 seconds (Ohio's redirects, Arkansas's dropped connections: its server drops about one connection in ten, and the client tries a request up to four times).
- **Not verified from a GitHub runner:** every one of these hosts was reached from this project's sandbox only. A refusal (HTTP 401, 403, 407 or 429) exits 2 and keeps the committed file; a reset or an HTML block page exits 1 and shows red.

### Missouri: still a gap, on evidence

Missouri's wells layer has no permit dated after 2019-08-15, and its newest spud is 2021-06-04; the Geological Survey's wells list (updated 2024-08-30, the one the DNR still links) gives spud dates only, the newest 2023-08-06, and no permit date. Neither the State Oil and Gas Council's ten packets (Jan 2024 to Jul 2026), the DNR's open data (Socrata, ArcGIS), nor any other layer of the service holds a current dated list; the e-permitting services need a login. A spuds series ending in 2024 would be added into the other states' 2026 spud total as if it were current (`p12` is a state's own last 12 months), and the months after it are unread, so they cannot be filled with zeros. What would change the answer: the DNR posting a newer list or one with permit dates (its permits page), the REGROW-funded online application and dashboard going public, or a public-records request to the Survey in Rolla for permits by month (the owner's call).

## Four counts, two that add

A state's file says what it counts (`measure`). **Permits approved** (`permits`) and **wells spudded** (`spuds`) are each added within their own measure into the report's two totals and drawn in its two stacked charts. Two states count something else and are **shown, ranked on their own and added to nothing**:
Oregon counts **applications filed** (`applications`: DOGAMI's file has no approval date) and Virginia **wells drilled by the day drilling was completed** (`drilled`: Virginia Energy publishes no permit or spud date). Before 2026-11-01 they sat under permits and spuds, which put Virginia's 49 wells into the spud total and called Oregon's applications approvals.
On the page a tile of another kind is dotted, shaded against the biggest state counting something like it (permits for applications, spuds for wells drilled) so it is never the "largest" of its own group of one, and the top figures name them under "Counted another way". A state whose last **24 months** hold nothing (Arizona, Florida, Oregon, South Dakota) is shown as "None recorded", with a dash on its tile, never as a 0: the source dating nothing in two years is not the same as nothing happening.
A read zero (a year after a year with some) is outlined, apart from a state not read yet (dashed).

## FracFocus in the matrix (`#fields`)

`fields/FF.json` is a research file like a state's, for the one source that is not an agency's permit: FracFocus, the registry the operators file their fracturing jobs to (read on 2026-11-01 from the data dictionary inside `FracFocusCSV.zip`, `readme csv.txt`, last updated Nov 2023, and the real header lines of
the three kinds of file in it, by range requests: `DisclosureList_N.csv` 17 columns, `FracFocusRegistry_N.csv` 31, `WaterSource_N.csv` 9, 34 different columns in all; the download page for the cadence (5 days a week), the formats (1.0 to May 2013 has header data only, 2.0 to 4.0 add the chemicals, 4.0 adds
optional water sources from Dec 2023) and the terms of use (data may be combined, not altered)). The same 52 questions are answered about what a disclosure captures: 12 `data` (API number, well name, operator, county, latitude and longitude with the datum, true vertical depth, water, only a federal and a tribal yes/no for ownership, and the four fracturing rows below), 1 `query` (the disclosure PDF in Find a Well, named on the download page, not opened) and 39 `none`. Judgments worth knowing: the job's start and end are **not** a spud or completion date (said in those cells); TVD is "usually the current or final depth", not a planned one; a disclosure is the job as done, never "a plan at permit time", so `fracture_plan` is `none` for it and the chemicals are the four fracturing rows; the operator is the organization that filed, which can be an agent or a person.

It is built into `permit-fields.json` beside the agencies, never among them: `registries: ["FF"]` (`d11_fields_build.py` `REGISTRIES`), `order` holds only the 35 agencies, so every count of agencies ("31 of 35", the headline, the metric panel's lists) stays over agencies, and the state carries `kind: "registry"` and
`fields`, the plain-words list of its 34 columns (`registry_fields` in the research file: a label, what it holds, one of five groups, the permit metric it matches or none). `registry_problems()` refuses a field that is a column of none of the sources, a column of a source missing from the list, a repeated field, an unknown group
and a metric that does not exist, so the list cannot drift from the evidence. The page (`fields.js`, `fields-data.js` `registries`, `columns`, `registryGroups`, `registryAdds`) draws FracFocus as the first column (tinted, with a rule after it), a panel that speaks of a disclosure, a registry line in each metric's panel, a figure
"What FracFocus adds" (its data metrics that fewest agencies publish: the chemicals 0 of 35, water 1, true vertical depth 4) and a card of the 34 fields. A new registry is a research file, an entry in `REGISTRIES`, and a `fields` list.

### The fracturing job: four questions for every agency (2026-11-01)

What a disclosure holds that a permit does not, asked of every agency in a group of its own (`frac` in `fields/metrics.json`, after the safety group; 48 metrics became 52): `frac_dates` (the job's start and end as dates of their own), `frac_chemicals` (name or CAS number), `frac_additives` (trade name, supplier, purpose) and `frac_amounts` (percent or pounds of each ingredient). Judge the agency itself, never FracFocus:
`data` a field in a file the agency publishes (evidence a file's columns or its documentation), `query` the agency's own lookup or record page shows it per well (a posted scan counts; a link out to FracFocus does not), `form` the agency requires it, on its form or by sending the operator to FracFocus, but does not publish it (the legend now says "required by rule"),
`none` it asks for nothing of the kind, `unknown` not verified. Seven agents each took five jurisdictions, read the agency's rules, forms and data pages, and wrote one file each (a brief and a checker in the scratchpad); the merge added the four cells after `fracture_plan` in each `fields/<ST>.json`, a research source where a data cell rests on a file the file did not list
(Wyoming's Treatment Data Download, Virginia's Chemical Disclosure Report export; Alaska's Well Work Dates export was already there) and up to two of each agent's unknowns.

What came out (35 agencies, 140 answers): the dates are `data` in 3 (Alaska's well-history events, Wyoming's treatment day, month and year, Virginia's export columns), `query` in 7, `form` in 12, `none` in 5 and `unknown` in 8; the chemicals are `query` in 8, `form` in 21, `none` in 3 and `unknown` in 3, and **no agency publishes the chemicals, the additives or the amounts as data** (the additives are `query` in 7, the amounts in 6). 29 of 35 require or show the chemical list. 17 answers are `unknown` (a site that refused automated requests or a form that could not be read: Alabama, Oregon, most of Arizona, Michigan's form, the offshore's dates).
Judgments worth knowing: Illinois' three cells are `form`, not `query`, because only one withdrawn application of 2017 is posted (the agent's own suggestion, taken); Alaska's date is one date a "Well Fractured" event and says the file does not say whether it is the job day or the report day; California, Arkansas and Colorado `query` cells rest on the agency's own pages and statute rather than an opened record (the notes say so); Florida's `none` rests on the statute's section index and the workover forms (no section on fracturing; rules 62C-25 to 62C-30 not read in full);
Wyoming's and Ohio's scans were opened for one or two wells each. Two of the agents went past the brief's limits (about 12 requests an agency, 50 MB a download): Wyoming and Virginia need many requests because their sites are frame- and postback-based, and one Ohio download came to 99 MB because the server ignored a range request (deleted). No server was asked again after a refusal.

## The pages' words

The research files (`fields/<ST>.json`) are written in the researchers' own voice ("blocked from this machine", "I read", "the tracker"), and stay as researched. What reaches a page goes through `d11_fields_build.py`: `VOICE` is a list of the phrases to rewrite (each is one phrase the research uses; `tests/test_d11_fields.py` fails if a marker of the researchers' voice is left in the published
`permit-fields.json`), and `clip()` cuts a long string after a whole sentence, or a whole word with an ellipsis, never in the middle of one. The reasons a producing state is not read yet are written for visitors in `GAP_WHY` in `d11_nat_build.py` (a test fails for a gap without one, or with the researchers' words in it); the researched reason, with the account of what was tried, is in the matrix.
The page hides the research's producer plan (it is notes for whoever builds the producer), and the Sources page lists the state agencies behind the report from `national.json` itself, with a link to the agency's page when the source is a raw download or a map-service root (`sourceHref` in `national-data.js`). In a sentence the offshore is "the federal offshore" and the BLM "federal onshore (BLM)" (`inName`).

## Layout and keyboard (2026-11-01)

A panel's two lists (top counties, top operators) are one column unless each can have 300 px, and a name wraps to a second line instead of ending in an ellipsis (it was cut at 100 px). A chart is drawn at the width its container has (`chartWidth` in `util.js`, up to 1,200), because a fixed 720-wide drawing scaled to a phone made 11 px axis text 4.5 px; the National chart is drawn again when the window changes size or the view is shown.
`niceMax` picks the smallest whole step that needs at most five intervals, so the axis tops near the data (1,150 tops at 1,250, not 2,000). The matrix's 1,680 cell buttons are one tab stop (the selected cell, else the first): the arrow keys move between cells, Home and End go to a row's ends (with Ctrl, to the first and last row), and a visible line says so; its group strip wraps instead of scrolling out of sight (`segmented({ wrap: true })`).
An address decides what the pages show: `#national` without a count shows the permits and `#fields` without a group shows them all (both kept the last choice, so a link to a state drew wells spudded after a visit to that count).

## Known limits

- **`asOf` is the day a state's data is current to.** For most states that is the newest record's day. Nevada's page is edited by hand and Virginia's layers publish no update time, so for those two it is the day of the read (their `note` says so, and Nevada's `lag_days` keeps a month with no permit from reading as a real zero too early); the National page's top figure is therefore called "Latest update", not "newest record".

- Texas's monthly series is application type 01 only; it says nothing about the other bands (its Daily report holds only the last 92 days). Oklahoma's, New Mexico's and the offshore's the same.
- The 12-month figures are each state's own last 12 complete months, so a spud-counting state's window ends two months before a permit-counting state's.
- The tile map is a cartogram, not geography: no state outlines are loaded (no external requests).

## Run

```
python3 -I site/pipeline/d11_nat_build.py            # rebuild national.json from the committed files
python3 -I site/pipeline/d11_nat_build.py --check    # reload and validate it and every nat/<ST>.json
python3 -I tests/run_all.py d11                      # the tests
```
