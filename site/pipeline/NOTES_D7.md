# NOTES_D7: the daily Railroad Commission report (producer D7)

Scripts: `site/pipeline/d7_daily.py` and its share client `site/pipeline/rrc_share.py` (stdlib only; run with `python3 -I`).
About 20 s for one day; rebuilding all 92 days took 88 s (2026-10-31). Page: `#daily` (`js/daily.js`, `js/daily-viz.js`).

Files in `site/public/data/daily/`: `YYYY-MM-DD.json` (3-13 KB each, 92 kept), `index.json` (one row per day, 13 KB),
`permits-series.json` (permits issued per calendar day, 2 KB). Budgets 60 / 40 / 20 KB, enforced by `--check`.

## Read this first

1. **The existing permit tables cannot go daily, so the daily permits live here instead.** `d1_permits_geo.py` counts from
   `daf802` (Drilling Permit Master and Trailer), which the RRC lists as *monthly* ("available by the 7th working day"). Only
   the Daily File (`daf420.dat`) is nightly, and `d1` uses it for coordinates only. Re-running `d1` each day would change
   nothing, and refreshing part of it would break the invariants between files: `operators.json` and `companies.json` carry
   permit counts from the (uncommitted) lead CSVs and must agree with `county-permits.json` and `operator-extras.json`.
   So the daily job leaves them alone and reads the nightly file into the report. `meta.json` is untouched.
2. The report tells you when a monthly rebuild is due: it compares the RRC's `daf802.txt.gz` and `orf850.txt.gz` times with
   `meta.json` `sources.permits` / `sources.p5` and shows "Newer file waiting" (live days only).
3. Operators are named only through `operators.json` (corporations, LLCs, limited partnerships). Lease names, well numbers
   and anything about individuals are never written. A permit file operator that is not in that list shows as "Operator #n".

## What it reads

The RRC data sets page (`DATA_PAGE`) is parsed for every row whose Updated column says nightly, twice daily or daily
(`Nightly`, `Twice Daily, 11:30 am and 5:30 pm`): six datasets on 2026-10-30 (68 rows on the page). The share GUID comes
from the page; the constants in `DATASETS` are the fallback. A new nightly dataset is logged and listed in the report.

| id | RRC dataset | what is read |
|---|---|---|
| permits | Drilling Permit Master and Trailer - Daily File | `daf420.dat`, the current month, parsed (below). Rebuilt days also read the End of Month files (`f5dfea9c-...`) |
| pending | Drilling Permits Pending Approval | the newest 11 AM and 5 PM sets: `dp_drilling_permit_pending_*` and `dp_wellbore_pending_*` |
| completions | Completion Information in Data Format | `<MM-DD-YYYY>.zip`, one `packetData_<n>_(Approved\|Submitted).dat` per packet, by district |
| w1images, dirsurveys, complimages | the three image packs | the share listing only (size, time); the zips are hundreds of MB and are never downloaded |

Not daily, so not read: Digital Map Data (twice a week) and everything weekly or monthly.

## The shares (`rrc_share.py`)

`https://mft.rrc.texas.gov/link/<guid>` is a PrimeFaces file table (250 rows a page).
- **The host drops about two in three new TLS handshakes** (reset during the handshake, no pattern by file; the agent proxy
  logs nothing). One keep-alive connection per share, and every request reconnects and retries (18 tries, 1-8 s apart).
  A typical run absorbs 5-30 resets.
- Sort by date: POST `fileTable_sorting=true, fileTable_sortKey=fileTable:date, fileTable_sortDir=-1` (numeric; the word
  DESCENDING is a server error). **A sort request always restarts at page one**, so later pages are plain
  `fileTable_pagination=true, _first=N, _page=N/250` requests that continue the sort. Sending the sort with every page
  returns page one again (seen: 2,300 rows that were 250 rows repeated).
- A file link (`fileTable:<row>:j_id_2f`) resolves only while the server's table shows the page that holds the row, so
  `download()` repositions the table first.
- Listing times are shown as the share prints them. Their zone is not stated (the pending set names carry Central time and
  their listing times are 5 hours later, which suggests UTC, but other shares do not fit one story), so the report shows
  them as listed and never converts them.

## Layouts

- **Permit file** (`daf420.dat`): CRLF, blocks of record 01 (212 chars) then 02 (510), 03-13, 14/15 (coordinates). Record 02
  offsets (0-based, the manual's positions minus 3): permit 2:9, county 11:14, district 46:48, depth 54:59, operator 59:65,
  type 65:67, received 121:129, issued 129:137, amended 137:145, spud 153:161, directional 481, horizontal 493.
  **District is an internal code** (Midland shows `10`): 07=6E, 08=7B, 09=7C, 10=08, 11=8A, 13=09, 14=10.
  New-drill = type `01`, first 02 record per permit number, the same rule as `d1`.
- **The plain `daf420.dat` is the current file; the dated snapshots lag.** On 2026-10-30 the plain file ran to issue date
  10-29, the snapshot named 10-30 only to 10-28. The file holds the current month (it can still be last month for a day or two
  after rollover). No permits are issued on weekends, so Saturday-Monday reports show Friday's permits.
- **Pending sets** are `}`-delimited with quoted values. The header wraps mid-word at 750 characters and may or may not be
  followed by a blank line; a data row is complete when it holds as many `}` as the header. One set per run, 11 files; the
  copy to the share takes about 100 minutes, so a set is used only when both files it needs are listed. Each set holds the
  applications submitted since the previous run that are *still pending*, not a running queue. The share keeps every set
  (41,048 files on 2026-10-30), so history can be rebuilt.
- **Completion packets**: header line, then `PACKET{...}` with `{`-separated columns (OPERATOR_NO 5, PURPOSE_OF_FILING 11,
  COMPLETION_TYPE 12, DISTRICT 27, COUNTY 28, CMPL_PACKET_TYPE 32 (1 = G-1 gas, 2 = W-2 oil), WELLBORE_PROFILE 40), and
  `W-2{...}` whose column 14 is the calculated 24-hour oil rate. The G-1 gas test has no unit in the manual, so gas tests are
  not reported. "First tests of new wells" = approved packets with purpose 1 (initial potential).

## Which day a report shows

Each dataset keeps its own day (`datasets[].dataDay`): permits = newest issue date before the report day; pending = the
report day's sets; completions and completion images = the newest zip on or before the report day; W-1 images and surveys
= the newest pack out the day before. Rebuilt days use the same rule on the listings' times. The report date is the Central
day the capture ran (`zoneinfo`, with a US daylight-saving fallback).

`state` per dataset (live days only): `new` when the newest file's name, time or size changed since the previous *live*
report, `same` when not, `first` when the previous report was rebuilt (nothing to compare), `error` when it could not be read.

## Checks (all pass)

1. Rebuilt monthly new-drill totals against `series-permits.json` (from `daf802`): August 594 = 594, September 681 vs 682.
2. Counts on 2026-10-29 by hand from the file: 40 permits issued, 36 new-drill, 28 horizontal; completions that day 66
   approved and 57 submitted packets (123 files in the zip).
3. A full 92-day rebuild into an empty folder matches the committed archive: 92 of 94 files byte-identical, the other two differ
   only in `capturedAt`/`retries`/`generated`. Rebuilding two deleted days gave byte-identical files too, and a run on the
   next night marks every unchanged file `same`.
4. The publish step was run against a throwaway remote: with nothing new it makes no commit; with a new day file it commits
   only that file and keeps `.nojekyll`; a failed Pages-build request is a warning, not a failure.
5. `--check` reloads every file and verifies: index rows = day files, six datasets in order, counts nest, pending total =
   sum of its sets, series arrays aligned and in order, size budgets. It was run against a deliberately corrupted copy
   (five faults, all reported).

## Run and schedule

```
python3 -I site/pipeline/d7_daily.py                  # today (Central), writes the day, index and series, then checks
python3 -I site/pipeline/d7_daily.py --backfill 91    # also rebuild every missing day of the last 91 (the whole archive: about 90 s)
python3 -I site/pipeline/d7_daily.py --check          # only validate
```
`.github/workflows/daily-rrc-report.yml` runs it at 03:15 UTC (10:15 PM CDT / 9:15 PM CST, after the evening files are
out) with `--backfill 7`, so a missed night is filled from the RRC's history on the next one, then `--check`, then commits
`site/public/data/daily/` to `main` and publishes `site/public` to the `gh-pages` branch that GitHub Pages serves (a copy plus
`.nojekyll`; an ordinary push, never a force push; it refuses to publish a copy without `index.html`, `js/main.js` and
`data/meta.json`). A push made with the workflow's own token may not start a Pages build, so the step also requests one and
only warns if that request fails. Raw downloads go to `dl/daily/` (gitignored).

Known limits: a rebuilt day has no catalog check, file states or monthly watch; the pending queue is only as old as the
share keeps it; image packs are measured by size only; permit coordinates are ignored here (only part of recent permits have
them).
