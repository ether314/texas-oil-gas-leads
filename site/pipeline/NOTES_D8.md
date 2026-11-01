# NOTES_D8: the daily Oklahoma Corporation Commission report (producer D8)

Scripts: `site/pipeline/d8_ok_daily.py` (the producer), `site/pipeline/ok_xlsx.py` (a small .xlsx reader),
`site/pipeline/d8_ok_context.py` (one monthly series for the card under the map) and `site/pipeline/d8_ok_monthly.py` (the permit history
for the Overview, Map and Operators: see "The permit history files" below), all standard library only; run with `python3 -I`. A live capture takes about 10 s (most of it the 121 MB well file); rebuilding all 92 days from the
master files takes about 2 minutes (2026-10-31). Page: the Daily report, `#daily` (`js/daily.js`, which
merges the two states, with `js/daily-ok.js` for the sections only Oklahoma has, `js/daily-data.js` for the merge rules and `js/daily-viz.js` /
`js/daily-kit.js`, which both states share); `#oklahoma` redirects to `#daily?st=ok`, the Daily report narrowed to Oklahoma. County shapes: `site/public/data/counties-ok.geo.json` (77 counties).

Files in `site/public/data/daily-ok/`: `YYYY-MM-DD.json` (3-6 KB each, 92 kept) and `index.json` (one row per day, 14 KB). Budgets
60 / 40 KB, enforced by `--check`. `site/public/data/series-ok.json` (2 KB) holds the monthly series.

## Read this first

1. **This is the Oklahoma counterpart of the Texas Daily report (`NOTES_D7.md`), not a copy of it.** The Oklahoma Corporation
   Commission (OCC) publishes different files, so the report has different sections: permits (intents to drill), completion
   filings, well transfers and the state's well inventory. There is no pending-approval queue and no image pack to read.
2. **Oklahoma is small next to Texas: about 3 new-drill permits a business day** (208 on the 64 approval days from July 31 to
   October 30; Texas averaged about 31 over its last 60 business days). Single days swing, so the page leans on the 20-day
   average and on the counts of other filings. It is a real picture of the files, not a thin capture.
3. Operators are named only when the name ends like a corporation, LLC or partnership, and never when it says a person trades under it
   ("... DBA ..."): a sole proprietor is a person (two reports named two of them until 2026-10-31; the rule now refuses them, and the
   two days were rebuilt from the master files). The files also carry operators' street
   addresses, the person who signed each application and their phone number: none of that is read. A name that fails the rule is
   written as an operator number only (the page shows "Operator #n"). Lease names, well names, well numbers and API numbers are
   never written, and the Daily report writes no locations. (The permit history files below hold the surface location of each
   new-drill permit, rounded to about 100 m, with no name of a lease or well.)

## What it reads

The OCC oil and gas data page (`PAGE`) lists every file with how often it is refreshed (`Daily`, `Nightly`, ...). Four rows
carry drilling and well activity; the page's other daily or nightly rows are listed in `NOT_READ` with the reason, and any new
one is logged and shown in the report.

| id | file (under `FILES`) | what is read |
|---|---|---|
| itd | `ITD-wells-formations-daily.xlsx` (about 21 KB) | intents to drill with an approval date: API, operator, well class, application type, planned depth, submit and approval times. The 7 complete Central days before the day it is made (made about 7:41 PM Central, so it ends the day before) |
| completions | `completions-wells-formations-daily.xlsx` (about 31 KB) | completion filings (Form 1002A), one row per casing string or test: API, operator, well type, horizontal flag, spud, first production and filing times, oil and gas rates, formation |
| transfers | `well-transfers-daily.xlsx` (about 120 KB) | wells that changed operator: API, event time, type, from and to operator. About a month, so about 800 rows |
| wells | `rbdms-wells.csv` (121 MB, 457,359 records) | the nightly well file, counted never listed: status, type, operator and the county in the API number. Made about 4:30 AM Central |
| history | `ITD-wells-formations-base.xlsx` (154 MB, 404,870 rows since 1999) and `completions-wells-formations-base.xlsx` (76 MB, since 2010) | with `--history`: the days before the first capture; otherwise only when a daily file stops short of the day before the report (below) |

Not read, and why (`NOT_READ`): the incident list (its newest incident is weeks older than the file), the GIS copy of the
well file, and the operator, purchaser and plugger lists (names, phone numbers and addresses of people and companies).

The files are untrusted data: they are parsed, never run.

## The workbooks (`ok_xlsx.py`)

The OCC workbooks are up to 150 MB with 117-138 columns. ElementTree builds an element for every cell and manages about 2,000
rows a second there; `ok_xlsx.rows()` scans the sheet XML in 1 MB chunks with regular expressions and touches only the columns
asked for: the 154 MB master, 404,870 rows, takes 66 s. It reads shared strings (including rich text), inline strings and plain
numbers or text, in any attribute order, with empty rows and cells, and returns every value as text. Dates are Excel serials
(UTC, days since 1899-12-30): `excel_date()`. Booleans come back as `0` or `1`.

## Which day a report shows

**One rule for live, rebuilt and repaired reports: a day shows the newest day before it, within 10 days, on which the OCC's files
hold something.** Monday's report shows Friday's approvals, filings and transfers; a holiday is skipped the same way.
- **The daily files end the day before they are made.** The intent-to-drill and completion files are made at about 7:41 PM Central
  and hold the 7 complete Central days before that day: the file made on the evening of Oct 30 ends with Oct 29 (measured on
  2026-10-31: its newest approval was Oct 29, 15:02 Central; the master file already held Oct 30). So the night's capture, taken after
  that evening's file, has everything through the day before the report, which is exactly what the one rule shows; and only whole days
  are shown, so a live night and a rebuild give the same report (`build_reports` is one code path for both, tested).
- **A capture whose daily file stops short fills the gap from the master.** A capture in the morning of the report day (a manual run,
  a repair) has last evening's files, a day short of the day before the report. `masters_to_read` compares each file's last day
  (`coverage_end`, from its Last-Modified in Central) with the day before the report and reads that dataset's master file for the days
  after it (about a minute and 230 MB, only then), so a morning, repaired or rebuilt report shows what the evening run will.
- Times in the files are UTC and are turned into Central days (`central_day`, `zoneinfo`; with a month-based fallback if tz data
  is missing). The listing's `Last-Modified` (GMT) is shown in Central.
- `datasets[].dataDay` says which day each card's data is from. The well inventory carries its file's date.
- The report date is the Central day the capture ran. A backup run an hour later does nothing when the night's capture is done
  (`--skip-if-captured`: live, complete and made at or after 03:00 UTC the next day, after the files are made).

`state` per dataset (live days only) is `new` when the file's name, time or size changed since the previous *live* report, `same`
when not, `first` when the previous report was rebuilt (nothing to compare), `error` when it could not be read.

## What is counted

- **New-drill permits**: application type `DR` with an approval date; rejected (`REJ`) and deleted (`DEL`) applications are left
  out. Other kinds (`RC` recompletion, `RE` re-entry, `DP` deepening, `AM` amendment) are in `total` and `types`; amendments are
  also counted as `amended`. The file has one row per application.
- **Depth, not horizontal**: the permit file does not say which permits are horizontal (its drill type and formation columns are
  empty), so the report counts a well planned to 12,000 feet or more as *deep* (`DEEP_FT`; 74% of the new-drill permits from July 31 to
  October 30) and shows depth bands. It does not claim they are horizontals.
- **Days to approval**: submit to approval, whole days, for new-drill permits.
- **Completions**: the file has a row for every casing string and test, so rows are folded to one event per well, filing day
  (the file's `Create_Date`, Central) and new or amended. Rejected filings are left out. Horizontal is the file's flag
  (`Location_Type_Sub` HH or a horizontal `Drill_Type`). "Filed after first production" and "spud to first production" are
  medians over the filings that carry both dates. Best tests are the largest oil rates, or the largest gas rates if none has oil.
- **Transfers**: one event per well and transfer, where the operator changed. `wells` counts distinct wells. One sale can move
  hundreds of wells in a day (193 on 2026-10-29), so transfers swing far more than permits.
- **Well inventory** (live days only): status codes that share a label are added together (plugged is `PA`, `PAFF`, `PASF`, `PASUR`,
  `PASURSF`) and shown as the five largest plus Other, which adds up to the total. Active wells are status `AC`, counted by the
  county in their API number and by operator; only named operators are listed, the rest are counted (`unnamed`, `unassigned`).
- **County**: digits 3-5 of the API number, which are the county's FIPS code (001 to 153, odd). 77 counties.
- **Named share**: the share of the day's new-drill permits (or completions) that went to named operators.

## The monthly figures card (`d8_ok_context.py`)

Under the map and story the page shows three monthly figures with a year-on-year change and a three-year sparkline: **Oklahoma crude
oil production** (EIA series MCRFPOK1, thousand barrels a month; 11,977 for August 2026, 1.7% below a year earlier) and the **WTI** and
**Henry Hub** prices, which the page reads from `series-markets.json` (the Texas pages' file) instead of repeating. They are not for
the report's day and change once a month, so each tile says which month it is. The card hides what is missing: without
`series-ok.json` it keeps the two prices, without both files it is gone and the rest of the page is unchanged.

`d8_ok_context.py` fetches the EIA page with the same code the Texas market series use (`d3_markets_infra.py`: the series title must
match, so another series or the per-day one is refused; values must be 5,000 to 30,000), and writes `series-ok.json` (months from
2019-01 to the newest month with a value, `okCrude`, units, source line with EIA's release date). It is run by hand when EIA
publishes (about the end of the month: the 2026-10-30 release carried August); `--check` revalidates the file. The newest months
are estimates that EIA revises.

**Not included: Oklahoma oil and gas jobs and rig counts.** BLS State and Area Employment (series `SMU40000001021100001`, NAICS 211)
is reachable through its keyless API (25 requests a day per address, the build host's allowance was used up) or its bulk files (which
refuse a request with no contact in the User-Agent); Baker Hughes blocks scripts and its workbook copies are on the Internet Archive,
which the build host could not reach (the connection is cut during the handshake). FRED was unreachable too. Both can be added from a
host with access, the jobs by the same call `d5_federal.py` makes for Texas with the Oklahoma ids.

## The permit history files (`d8_ok_monthly.py`)

The Daily report is one day at a time. The Overview, Map and Operators show a year and its trend, so `d8_ok_monthly.py` reads the
master intent-to-drill workbook (154 MB, every application since 1999, about 75 s) and the daily one beside it, and writes four files into
`site/public/data/`, shaped like the Texas files they sit beside (the same windows, from `d1_permits_geo.windows`):

| file | shape | Texas counterpart |
|---|---|---|
| `series-permits-ok.json` | new-drill permits by approval month, 2019-01 to the last complete month | `series-permits.json` |
| `county-permits-ok.json` | per county (77): `p12`, `p12prev`, 36 monthly counts, mean planned depth, top 8 named operators | `county-permits.json` |
| `operators-ok.json` | the named operators with a permit in the last 24 months: band, type read from the name, office city and state, `new12`, `prev12`, `all12`, `all24`, last approval, depth, top county, counties, new to drilling, 24 monthly counts | `operators.json` plus `operator-extras.json` |
| `permits-ok.json` | one point per new-drill permit of the last 24 months: latitude and longitude (rounded to about 100 m), operator, day, depth, county | `permits.json` |

- **What counts as a permit.** The master has one row per formation until mid-2025 (a permit naming ten formations is ten rows; since then
  the formation columns are empty and a permit is one row). Counting rows would double the earlier years, so rows are folded to one
  permit per API number (its first ten digits) and Central approval day: the Daily report's rule, so the two agree (August 2026: 54 in the
  report archive and in the series; September: 70 and 70). A well approved again after its permit lapsed counts again, on the new day.
  New-drill is application type `DR`; recompletions, re-entries and deepenings are permits too (they are in `all12` and `all24`);
  amendments change a permit already counted and are left out; rejected and deleted applications are left out. In the real files 404,897
  rows fold into 11,232 permits since 2018.
- **Windows.** The last 12 months run 365 days back from the newest approval day (the end of the files), the 12 before them 730 days
  back; a month is complete when it is over, so the current month is never in a series. Counts use every permit; only the named
  operators are named.
- **Bands.** A is 10 or more new-drill permits in the last 12 months, B is 1 to 9, C is none in the last 12 but some in the 12 before.
  Texas's band C is every registered operator with none; the OCC's registrant list holds names, phones and addresses and is not read, so
  Oklahoma has operators with a permit in the last 24 months only. New to drilling is a first drilling permit, ever, in the last 24 months.
- **Operator type** is read from the name (LLC, limited partnership or corporation): the OCC has no organization type.
- **Locations.** 99.5% of the last 24 months' permits carry a surface location (Texas: 70%), decimal degrees (the file does not name the datum; the common ones differ by less than a dot at map scale), rounded to 3 decimals. The
  last 12 months are 100% located. Points outside the state's box are dropped; the county always comes from the API number, never from the point.
- **Privacy.** Operators are named only by the corporate rule (`nameable`); 98% of the last 12 months' permits went to named operators and the
  rest are in every count and in no name. City and state are the operator's office on its newest permit: never a street, a signer or a phone (a value that is not a place name or two letters is published blank, `office_place`: it costs that operator its city, never the weekly refresh).
  `--check` fails a file that holds an API-like number, an e-mail address, a link or a phone number, or an operator whose city is not a place name or whose
  state is not two letters.
- **Checks.** `tests/test_d8_monthly.py`: synthetic rows for every rule above, the validator against twelve deliberate faults, six mutants
  (everyone or nobody named, UTC days, a window a month too long, formation rows counted, a re-approved well counted once); with
  `OK_REAL_FILES` the real workbooks too, which must agree with the Daily archive.
- **Run** by hand: `python3 -I site/pipeline/d8_ok_monthly.py` (downloads both files, writes the four, checks them); `--check` only validates.
  `.github/workflows/refresh-monthly.yml` runs it weekly (Mondays 05:40 UTC), isolated from New Mexico's the same way as the nightly's captures.

## The points' API number (2026-11-02)

`permits-ok.json`'s points have a seventh column, `api`: the permit's API number, its first ten digits as a number (`api_number()`; 0 if the source gave fewer), by the owner's decision of 2026-11-02 (CLAUDE.md, Privacy, exception (d)). `build()` and `validate()` are shared by New Mexico and the offshore, so their `permits-nm.json` and `permits-fo.json` have it too: each state's spec says which prefixes its numbers may begin with (`api_state`: Oklahoma 35, New Mexico 30, the offshore 60 and the Gulf states' 17, 42, 01 and 23). `validate()` holds the column to whole numbers of that kind and lets it, and only it, through the ten-digit scan. A well permitted twice has two points and one number. Run for real on 2026-11-02, Oklahoma's first six columns came out identical to the committed ones (1,446 points).

## Rebuilt days

`--history` downloads the two master files, keeps the rows from ten days before the oldest day wanted, adds those the daily files
do not already hold (by API and time) and builds every missing day by the one rule. Transfers only reach back as far as their file
(about a month, so 60 of the 92 days have none), and the well inventory cannot be rebuilt at all: those days are marked
`absent`, and the page says so. A plain `--backfill` rebuilds at most the last 3 missed days (`SAFE_BACKFILL`), because the daily
files hold only 7 days and an older day would be rebuilt from too little; older days need `--history`.

## Bad nights

The nightly runs unattended, so what it does with files that are late, cut short or not what they were is part of the design. A third
independent review (a fresh reader, offline, with repro scripts) tried each of these; `tests/test_d8_nights.py` runs them as whole nights
with the network faked, and a mutant puts each fix's old behavior back and must be noticed.

- **A file that is not the file.** The well inventory needs `WELLSTATUS` and `API` columns and at least one well: an error page, an empty
  export or a renamed column fails that dataset (the report is `partial`, the other three files are kept, the page shows no inventory).
  A UTF-8 byte-order mark is read through. A total under 90% of the newest earlier report's (`WELLS_FLOOR`, `previous_wells_total`) is refused
  as a cut-short download, not published as fewer wells (if the OCC ever really does shrink its inventory by more than that, the page keeps saying
  so every night: run it by hand once with `--wells-floor 0`). The completion workbook needs `API_Number`, `Create_Date` and `Review_Status`; a
  renamed figure column (`COMP_OPTIONAL`) costs that figure, not the file (`ok_xlsx.rows(..., optional=)`).
- **One permit, not one per formation.** The permit workbook holds a row per formation: rows with the same API number, approval time and
  application type are one permit (`read_itd`, as the monthly file does). Rows with no API number are never folded.
- **A permit with no county.** A blank, short or other state's API number is counted in every total and in no county (`tally_counties`),
  and is never sorted against a county code (that once crashed the night).
- **A later capture never makes the report worse.** A capture of a day that read fewer datasets than the report already stored for that day
  (the backup run when the 121 MB inventory is refused) keeps the stored one; one that read nothing keeps it too; one that read as many or more
  replaces it. A master file that could not be read when it was needed (the daily files were late) leaves the days after the daily files' last one
  out, so the report is `partial` and the backup run goes ahead. A rebuilt day that was written `partial` is built again by a later night
  (`--backfill`); a live report is never rebuilt.
- **Dates and numbers.** An ISO text keeps its time of day (the files' times are UTC; the Excel serials the OCC writes always did); a date with no
  time is noon UTC, which is the same Central day in summer and winter. NaN and infinity are blanks. In the monthly files an approval dated after
  today is a typo in the source and is skipped, because it would end every window on that day.
- **Text in the files.** A failure's text, in a report or in the log, is one line without a web address (`clean_error`): the data files never
  carry a link. The naming rule refuses every spelling of a person trading under a name (dba, d/b/a, d.b.a, d b a, db/a, doing business as, trading
  as, t/a, aka, a/k/a, a k a, also known as). The monthly validator refuses a phone number anywhere in a file and an operator's city or state that is not
  a place name or two letters.
- **A privacy gate before anything is committed** (`privacy_check.py`, in `--check`): every day file is scanned for an e-mail address, a web address, a phone number and a run of ten digits (no API numbers are published), and every operator name it publishes
  (`published_operator_names`) must pass `nameable`. A night that breaks it is dropped by the workflow, not published (the check read no text before; that is how the two sole proprietors reached the live site). `clean_error` is shared with the other producers and
  also strips an error page's markup and a path.
- **Time.** Each state's capture step has a time limit of its own in the workflow (Texas 25 minutes, Oklahoma 12, New Mexico 6, the job 60), so a
  download that hangs cannot use up the time the other states, the commit and the publish need (`tests/test_workflow.py`).

## Checks (all pass)

1. The reader against an independent one (the ElementTree reader in `d6_misc.py`) on the three daily workbooks: every cell equal
   (booleans compared as 0/1). Against the version before it was hardened, on all 404,870 rows of the ITD master: same rows, same
   order, same time (66 s).
2. Synthetic workbooks: an empty `<row/>`, cell attributes in another order, columns past Z, XML entities, rich text, an inline
   string, a missing wanted column, a second sheet, and the same output at chunk sizes of 7, 13 and 64 bytes and 1 MB.
3. The rules with synthetic rows: the Central day across both clock changes (2026-11-01, 2027-03-14), `newest_day`, permit, completion,
   transfer and inventory sections (types add up, DR only, deep, bands, wait, named share, individuals not named), `build_reports`
   (Saturday to Monday show Friday; a live and a rebuilt report of one day agree; only live carries the inventory; a failed
   dataset leaves its section out), `plan_dates`, `update_states`, `add_wells_change`, `captured_for_the_night`. Eight mutants
   (everyone named, nobody named, a day showing its own records, Central fixed at UTC-5 or UTC-6, an uncapped backfill, unmerged
   status codes, the wrong digits for the county) are each noticed.
4. `--check` passes on the committed archive and reports each of twelve deliberate faults (a missing day file, types that do not
   add up, permits from the report day, counts that do not nest, a dataset missing, bad JSON, an oversize file, an inventory that
   does not add up and others).
5. Privacy: no API number, e-mail, link or street address anywhere in the archive; no field name outside the schema; all 165
   operators it names pass the naming rule; 2,965 operator names in the real files fail the rule and none of them (nor its
   display form) appears in any report.
6. `series-ok.json`: `--check` accepts the committed file and reports each of eleven deliberate faults (a gap in the months, a value in
   per-day units, series of different lengths, a newest month with no value and others); the EIA page parser reads thousands
   separators, blanks and the release date and refuses the Texas series' page and the per-day page.
7. The page, in a real browser: tooltips, every map layer, ribbon click and arrow keys, the calendar, the verbose report, deep
   links (an unknown day falls back to the latest), phone width without sideways scroll (390 px), light and dark, and no
   console or CSP error. The Texas Daily page renders byte-identical DOM before and after the shared building blocks moved to
   `daily-kit.js`, and the Texas Map draws identically after Oklahoma has been opened. These scripts were scratch work and are
   not in the repository.
8. Whole nights, offline (`tests/test_d8_nights.py`): `main()` with `urlopen` faked and synthetic workbooks, for each case under *Bad nights*
   (a permit with no county, an inventory that is an error page, empty, header-only, renamed, with a byte-order mark, or cut short, a backup run
   that reads less, a master that cannot be read, a rebuilt day left partial, a failure with an address in its text), the permit and completion
   workbook readers, and eleven mutants that put the old behavior back. About 4 seconds.

## Run and schedule

```
python3 -I site/pipeline/d8_ok_daily.py                  # today (Central): writes the day and the index, then checks
python3 -I site/pipeline/d8_ok_daily.py --backfill 3     # also rebuild the last 3 missed days from the daily files
python3 -I site/pipeline/d8_ok_daily.py --history        # rebuild every missing day of the 92 from the master files (about 2 minutes)
python3 -I site/pipeline/d8_ok_daily.py --date 2026-10-30   # capture that report day live (replaces its file if there is one)
python3 -I site/pipeline/d8_ok_daily.py --skip-if-captured  # exit quietly when the night's capture is already done
python3 -I site/pipeline/d8_ok_daily.py --check          # only validate
python3 -I site/pipeline/d8_ok_daily.py --counties       # rebuild counties-ok.geo.json from the Census county file
python3 -I site/pipeline/d8_ok_context.py                # refresh series-ok.json from EIA (by hand, about the end of each month)
```
`.github/workflows/daily-rrc-report.yml` runs it in the same job as the Texas capture, after it, at 03:15 and 04:20 UTC (the files
are made at about 00:41 UTC in daylight time, so both runs are after). The two states' captures are isolated: each capture and its
check are `continue-on-error`, and if either of a state's failed, a step puts that state's folder back as it was committed, so a bad
capture never reaches `main` and the other state is still committed and published. The last step then fails the run, so a night
that lost a state shows red. The workflow's
`oklahoma_history` input (a checkbox) refills the whole archive from the master files; `date` repairs a day for both states.
Raw downloads go to `dl/daily-ok/` (gitignored with the rest of `dl/`).

Known limits: no Oklahoma jobs or rig counts (above); counts are small; permits carry depth but not direction; completion formations are mostly blank; transfers reach back
a month; rebuilt days have no inventory, catalog check or file states; the OCC does not publish a schedule, so the file times above
were seen on one night (2026-10-30) and the 03:00 UTC cutoff leaves room for a later one.
