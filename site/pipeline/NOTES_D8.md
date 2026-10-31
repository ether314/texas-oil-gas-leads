# NOTES_D8: the daily Oklahoma Corporation Commission report (producer D8)

Scripts: `site/pipeline/d8_ok_daily.py` (the producer) and `site/pipeline/ok_xlsx.py` (a small .xlsx reader), both standard library
only; run with `python3 -I`. A live capture takes about 10 s (most of it the 121 MB well file); rebuilding all 92 days from the
master files takes about 2 minutes (2026-10-31). Page: `#oklahoma` (`js/ok-daily.js`, with `js/daily-viz.js` and `js/daily-kit.js`, which the
Texas report shares). County shapes: `site/public/data/counties-ok.geo.json` (77 counties).

Files in `site/public/data/daily-ok/`: `YYYY-MM-DD.json` (3-6 KB each, 92 kept) and `index.json` (one row per day, 14 KB). Budgets
60 / 40 KB, enforced by `--check`.

## Read this first

1. **This is the Oklahoma counterpart of the Texas Daily report (`NOTES_D7.md`), not a copy of it.** The Oklahoma Corporation
   Commission (OCC) publishes different files, so the report has different sections: permits (intents to drill), completion
   filings, well transfers and the state's well inventory. There is no pending-approval queue and no image pack to read.
2. **Oklahoma is small next to Texas: about 3 new-drill permits a business day** (208 on the 64 approval days from July 31 to
   October 30; Texas averaged about 31 over its last 60 business days). Single days swing, so the page leans on the 20-day
   average and on the counts of other filings. It is a real picture of the files, not a thin capture.
3. Operators are named only when the name ends like a corporation, LLC or partnership. The files also carry operators' street
   addresses, the person who signed each application and their phone number: none of that is read. A name that fails the rule is
   written as an operator number only (the page shows "Operator #n"). Lease names, well names, well numbers, API numbers and
   locations are never written.

## What it reads

The OCC oil and gas data page (`PAGE`) lists every file with how often it is refreshed (`Daily`, `Nightly`, ...). Four rows
carry drilling and well activity; the page's other daily or nightly rows are listed in `NOT_READ` with the reason, and any new
one is logged and shown in the report.

| id | file (under `FILES`) | what is read |
|---|---|---|
| itd | `ITD-wells-formations-daily.xlsx` (about 21 KB) | intents to drill with an approval date: API, operator, well class, application type, planned depth, submit and approval times. 7 complete days (UTC), made about 7:41 PM Central |
| completions | `completions-wells-formations-daily.xlsx` (about 31 KB) | completion filings (Form 1002A), one row per casing string or test: API, operator, well type, horizontal flag, spud, first production and filing times, oil and gas rates, formation |
| transfers | `well-transfers-daily.xlsx` (about 120 KB) | wells that changed operator: API, event time, type, from and to operator. About a month, so about 800 rows |
| wells | `rbdms-wells.csv` (121 MB, 457,359 records) | the nightly well file, counted never listed: status, type, operator and the county in the API number. Made about 4:30 AM Central |
| history | `ITD-wells-formations-base.xlsx` (154 MB, 404,870 rows since 1999) and `completions-wells-formations-base.xlsx` (76 MB, since 2010) | only with `--history`: the days before the first capture |

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
- **Only whole days are shown.** The daily files are made at about 7:41 PM Central and hold UTC days, so they reach 7 PM Central
  on the day they are made. Approvals made after 7 PM arrive with the next file. A report that showed its own day could be short
  of what a rebuild finds later; a report that shows only days before it cannot, so a live night and a rebuild give the same
  report (`build_reports` is one code path for both, tested).
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

## Rebuilt days

`--history` downloads the two master files, keeps the rows from ten days before the oldest day wanted, adds those the daily files
do not already hold (by API and time) and builds every missing day by the one rule. Transfers only reach back as far as their file
(about a month, so 60 of the 92 days have none), and the well inventory cannot be rebuilt at all: those days are marked
`absent`, and the page says so. A plain `--backfill` rebuilds at most the last 3 missed days (`SAFE_BACKFILL`), because the daily
files hold only 7 days and an older day would be rebuilt from too little; older days need `--history`.

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
6. The page, in a real browser: tooltips, every map layer, ribbon click and arrow keys, the calendar, the verbose report, deep
   links (an unknown day falls back to the latest), phone width without sideways scroll (390 px), light and dark, and no
   console or CSP error. The Texas Daily page renders byte-identical DOM before and after the shared building blocks moved to
   `daily-kit.js`, and the Texas Map draws identically after Oklahoma has been opened. These scripts were scratch work and are
   not in the repository.

## Run and schedule

```
python3 -I site/pipeline/d8_ok_daily.py                  # today (Central): writes the day and the index, then checks
python3 -I site/pipeline/d8_ok_daily.py --backfill 3     # also rebuild the last 3 missed days from the daily files
python3 -I site/pipeline/d8_ok_daily.py --history        # rebuild every missing day of the 92 from the master files (about 2 minutes)
python3 -I site/pipeline/d8_ok_daily.py --date 2026-10-30   # capture that report day live (replaces its file if there is one)
python3 -I site/pipeline/d8_ok_daily.py --skip-if-captured  # exit quietly when the night's capture is already done
python3 -I site/pipeline/d8_ok_daily.py --check          # only validate
python3 -I site/pipeline/d8_ok_daily.py --counties       # rebuild counties-ok.geo.json from the Census county file
```
`.github/workflows/daily-rrc-report.yml` runs it in the same job as the Texas capture, after it, at 03:15 and 04:20 UTC (the files
are made at about 00:41 UTC in daylight time, so both runs are after). The Oklahoma steps cannot stop the job: the capture and its
check are `continue-on-error`, and if either failed the step after them puts `site/public/data/daily-ok/` back as it was
committed, so a bad Oklahoma capture never reaches `main` and the Texas report is still committed and published. The workflow's
`oklahoma_history` input (a checkbox) refills the whole archive from the master files; `date` repairs a day for both states.
Raw downloads go to `dl/daily-ok/` (gitignored with the rest of `dl/`).

Known limits: counts are small; permits carry depth but not direction; completion formations are mostly blank; transfers reach back
a month; rebuilt days have no inventory, catalog check or file states; the OCC does not publish a schedule, so the file times above
were seen on one night (2026-10-30) and the 03:00 UTC cutoff leaves room for a later one.
