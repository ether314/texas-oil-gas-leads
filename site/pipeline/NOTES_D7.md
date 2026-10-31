# NOTES_D7: the daily Railroad Commission report (producer D7)

Scripts: `site/pipeline/d7_daily.py`, its share client `site/pipeline/rrc_share.py` and `site/pipeline/d7_packs.py`, which opens the image
packs (standard library; Pillow and `pdftoppm` only to draw the contact sheets). Run with `python3 -I`.
About 20 s for one day; rebuilding all 92 days took 88 s (2026-10-31). Page: `#daily` (`js/daily.js`, `js/daily-viz.js`).

Files in `site/public/data/daily/`: `YYYY-MM-DD.json` (3-13 KB each, 92 kept), `index.json` (one row per day, 13 KB),
`permits-series.json` (permits issued per calendar day, 2 KB), and with `--packs` `img/<day>-<pack>.jpg` (contact sheets, 22-29 KB).
Budgets 60 / 40 / 20 / 150 KB, enforced by `--check`.

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
| pending | Drilling Permits Pending Approval | the sets that landed that day: `dp_drilling_permit_pending_*` and `dp_wellbore_pending_*` |
| completions | Completion Information in Data Format | the newest `<MM-DD-YYYY>.zip` listed, one `packetData_<n>_(Approved\|Submitted).dat` per packet, by district |
| w1images, dirsurveys, complimages | the three image packs | the share listing every day (size, time); with `--packs` the live day's zips are also downloaded and opened (see "Inside the image packs") |

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
- **Listing times are Central** (the RRC server's clock; daylight time until 2026-11-01). Measured on 2026-10-31: the last
  file of the evening pending set was listed `01:43:44`, was not in the listing at 06:43:56 UTC and was there at 06:44:51
  UTC, so the listing runs five hours behind UTC. (An earlier version of this note guessed UTC; that was wrong.) The report
  shows the times as listed and never converts them.

## When the files land (Central, as listed)

Seen on 2026-10-24 to 10-31 (pending sets: since August). This is why the rule above goes by the time a file was listed, and why a report captured at 22:15 holds everything its day can have.

| file | lands |
|---|---|
| `daf420.dat.<MM-DD-YYYY>` snapshot, then the plain `daf420.dat` | about 07:50, then about 09:45, the same day (the snapshot runs to two days before, the plain file to the previous business day) |
| pending set named 11:08 (11 AM) | 16:07-17:47, the same day (11 files, one every 10 minutes) |
| pending set named 17:08 (5 PM) | 00:06-01:48, **the next day** |
| completions zip and completion images zip for day D | about 02:20 on D+1 (late once: day 10-26 was listed at 10:24 on 10-27) |
| directional surveys zip for day D | about 07:55 on D+1 |
| W-1 images `subscriptions_<D>_*.zip` | about 10:18 on D+1 |

## Inside the image packs (`d7_packs.py`, `--packs`)

The three packs are zips of scanned filings (PDF and TIFF). The listing gives a size for every day, which was all the report
showed. With `--packs` the **live** day's three packs (the ones that landed that day) are also downloaded, opened and deleted;
rebuilt days get no previews (92 packs a rebuild, 30-450 MB each). The RRC server ignores byte ranges (checked: a `Range`
request returns the whole file with status 200), so a pack can only be read whole. What the packs of 2026-10-29 held:

| pack | contents | kinds counted (by name pattern) |
|---|---|---|
| W-1 images (31 MB) | 168 files: the approved W-1 letter and the plats, `<permit>_W1_...` and `<permit>_Plat_...` | approved W-1 74, permit plat 94 |
| directional surveys (28 MB) | 57 PDFs `dir_survey_<id>.pdf` and one CSV | directional survey 57 |
| completion images (306 MB) | 908 files in 123 `<district>/trackingNo_<n>_Images_Submitted/` folders: the forms the system makes (`cmpl_<Form>Form_PID_<n>.pdf`) and whatever the operator attached | W-2 87, P-4 71, L-1 63, G-1 36, other forms 43; well logs 87, W-15 cementing reports 89, plats 49, P-16 43, surveys 60, other attachments 274 |

**What is published, and what is not.** `images[<pack>].docs` is the document count, the counts by kind (`types`, largest
first, `Other` last, adding up to `n`) and, for completions, the number of packets. `images[<pack>].sheet` names one JPEG,
`img/<day>-<pack>.jpg`: page one of up to 16 documents, one kind after another (chosen by a hash of the name, so the same
whatever the zip's order), each tile **112 px wide and blurred (Gaussian radius 1.2)**, 22-29 KB, 1-3 s to draw. The layout
shows (forms, plats, logs, logos), the text does not read. The blur is not decoration: at 128 px without it the largest print
on a cover page (an operator, a county) could still be read after a zoom, which a look at the first sheets showed, and a
blur makes that impossible whatever the page holds. **No page is published legibly and no file name leaves the module**: the
filings carry lease names, well numbers and the names, phone numbers and addresses of individuals, which the README's privacy
rule excludes, and the file names alone carry lease and well names. Showing readable pages would be a decision about that
rule, not a setting. Pillow and `pdftoppm` (poppler-utils) draw the sheet; without them the counts still come and the sheet
is skipped with a log line. A pack that cannot be downloaded or opened is skipped the same way and never costs the dataset.

Safety: the pack is untrusted. Members are read one at a time, over 12 MB are never opened, `pdftoppm` runs under a 25 s
timeout, a sheet gets 100 s in all, Pillow refuses a TIFF past 120 million pixels, and the zip is deleted afterwards.

Cost: the three packs are 360-510 MB a night (306 MB took 39 s through the agent proxy here; a whole run with the packs took
under two minutes). The workflow installs poppler-utils and Pillow first (about 15 s, `continue-on-error`). Three sheets are
about 80 KB a day, committed to `main` with the day file and again to `gh-pages`: about 30 MB a year of history on each, and
92 days (7 MB) in the tree, because `prune_images` deletes the sheets no day file refers to.

## Layouts

- **Permit file** (`daf420.dat`): CRLF, blocks of record 01 (212 chars) then 02 (510), 03-13, 14/15 (coordinates). Record 02
  offsets (0-based, the manual's positions minus 3): permit 2:9, county 11:14, district 46:48, depth 54:59, operator 59:65,
  type 65:67, received 121:129, issued 129:137, amended 137:145, spud 153:161, directional 481, horizontal 493.
  **District is an internal code** (Midland shows `10`): 07=6E, 08=7B, 09=7C, 10=08, 11=8A, 13=09, 14=10.
  New-drill = type `01`, first 02 record per permit number, the same rule as `d1`.
- **The plain `daf420.dat` is the current file; the dated snapshots lag.** On 2026-10-30 the plain file ran to issue date
  10-29, the snapshot named 10-30 only to 10-28. No permits are issued on weekends, so Saturday-Monday reports show Friday's
  permits.
- **The file is one month in full plus stragglers.** The body is every permit issued in the current month; on top of that it
  carries earlier permits that had activity this month (on 2026-10-30: 764 issued in October, 50 in September, 57 in August,
  34 in June, a few from 2015). A day counted from the stragglers alone is a few permits instead of 30-40. The dated
  snapshots turn to the new month on the **3rd** (`daf420.dat.10-02-2026` is 2.7 MB with a September body, `10-03-2026` is
  135 KB with an October one), and the first days after a turn hold only the first business days. This is a hazard, not a
  curiosity: see "Which months a file covers".
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

**One rule for live, rebuilt and repaired reports: a day shows what landed on each share that day (Central), judged by each
file's Last Modified time.** Because the rule reads only the listing, a past day captured later (a rebuild, or `--date` a
week afterwards) gives the same report as the evening run, and the report is a function of the day and the share.
- completions and completion images: the dated zip listed that day. A zip named for a day lands at about 02:20 the next
  morning, so a day shows the zip named for the day before. A day on which none landed (the RRC skipped 2026-08-30,
  10-10 and 10-18) shows none, instead of repeating the last one.
- W-1 images and directional surveys: the pack listed that day (surveys about 07:55 and W-1 images about 10:20 the next
  morning, so also the day before's). There is no W-1 pack for a weekend, so Sunday and Monday have none (26 days of the
  92); Saturday shows Friday's.
- pending: the complete sets that landed that day, in order: the previous evening's 5 PM set (copied after midnight) and the
  day's 11 AM set. Weekends have only the 5 PM set (no weekend 11 AM sets), so Saturday and Sunday show one set each; the day
  after a holiday with no sets can show just one, and a day on which nothing landed has no pending section (the page says
  so). A set belongs to the day its last needed file was listed, so a copy that crosses midnight lands on the next day.
- permits: the newest issue date before the day (a different kind of file: a month's cumulative list, see below).

`datasets[].dataDay` says which day each card's data is from (pending: the newest set's named day). For a live report
`datasets[].file` is the file that dates the card (the zip, the pack, the newest set's permit file, `daf420.dat`), chosen by
the same rule, so a repair does not show a newer file than its data. The report date is the Central day the capture ran
(`zoneinfo`, with a US daylight-saving fallback).

Before 2026-10-31 live days held the day's 11 AM set only and the previous day's completions, while rebuilt days held both
named sets and the day's own zip (a day apart on completions). The archive was regenerated under this rule.

`state` per dataset (live days only): `new` when the newest file's name, time or size changed since the previous *live*
report, `same` when not, `first` when the previous report was rebuilt (nothing to compare), `error` when it could not be read.

## Which months a file covers

`permits_job` reads the plain `daf420.dat` and, for every month the plain file does not hold in full, the month-end file
from the End of Month share (`daf420.dat.<last day>`, listed at 07:51 on the 1st of the next month). The plain file covers
only the report's own month, and only when that is its body month (`body_month`: the month of its newest issue date, not
counting dates after today, which are typos). Everything else is left to the month-end files, and a month neither covers is
left out: the report then has no permits section, and the ledger is not touched. The ledger (`permits-series.json`) takes
the larger of the old and the new count for a day (`merge_series`), so a partial file can never undo a full one.

Why: before this, a capture counted the newest issue date in the whole file, so in the first nights of a month, or when an
earlier day was repaired, it would have built the section from stragglers ("3 permits on Sep 14", really 53) and written
those counts over the month in the ledger. Seen by running `--date 2026-09-15` against the October file.

Which month the plain file turns to, and when, is not known for the plain file itself (only for the dated snapshots: the
3rd), so nothing here depends on it. A day's section looks back up to 10 days, so reports in the first days of a month read
the previous month's file too (one extra 2.4 MB download).

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
6. The listing clock was measured, not guessed: the last file of the 2026-10-30 evening pending set was listed at `01:43:44`
   and first appeared in a listing polled every minute at 06:44:51 UTC (it was not there at 06:43:56).
7. Month safety, with the shares and the file parser faked and synthetic month changes: an ordinary night reads no month-end
   file; the first night after a month turns (the file holds only stragglers) is covered by the month-end file alone and
   shows its counts, not the stragglers'; the night the file has turned and
   holds one business day; the first Monday with the file still on the old month; the month-end file missing (no section,
   a log line, ledger untouched); repairing an earlier month; a 92-day rebuild reads the same July-September files as
   before; the ledger keeps the larger count and still nests. Against the real shares: `--date 2026-09-15` into a scratch
   folder gives the permits day Sep 14 with 53 permits (43 new-drill, 35 horizontal), the committed values; before the
   change it gave 3, and the ledger came out identical to the committed one.
8. `--skip-if-captured` (nine cases): a live, complete capture at or after 03:00 UTC the next day counts; one made earlier
   that evening does not, nor a partial, failed, rebuilt, corrupt or missing report. The workflow's capture step, run with a
   stand-in `python3`, passes the right arguments for a manual run, a manual run with a date, a backfill of 91 and a
   scheduled run, and rejects a bad date, shell metacharacters in either input and a non-numeric backfill without creating
   a file. On the real shares `--date 2026-10-30 --backfill 7 --skip-if-captured` captured the day, and a second run exited
   0 with "already captured live".

9. One rule (2026-10-31). `landed_on` and `pending_ready` with fake shares (51 checks): each day picks the pending sets, the
   zip and the packs listed that day; weekends show one 5 PM set; a set whose copy crosses midnight lands on the next day;
   a late zip is shown the day it was listed; a day with no zip or no W-1 pack shows none; and every day captured in the
   evening equals the same day captured after more files landed. Three deliberately wrong versions of the rule (zips and
   packs by the day in their name, pending sets by the day in their name, "listed by the end of the day") fail 23, 15 and 5
   of the checks. On the real shares the whole archive was regenerated (`--date 2026-10-30 --backfill 91` over the archive
   with its rebuilt days removed; `--check` clean): pending differs on all 92 days, completions and completion images on
   89 (a day earlier); the W-1 pack is empty on 26 days (Sundays and Mondays), completions on 3 (the zips the RRC skipped
   for Aug 30, Oct 10 and Oct 18). The ledger changed on one day (2026-08-21, horizontal 20 to 23) and permit cards on 50
   days (`amended` on 45, `rows` 10, `located` 8, `depth` 4, `directional` 3, `horizontal` 3, `wait` 2), all from letting
   the newest month-end file's record win for a permit that is in several files (an amendment can change a flag or the
   depth). The page was opened in a browser at desktop and phone width on a weekday with two pending sets, a Sunday and
   the Monday after a skipped zip day: no horizontal overflow, no console errors.

10. Image packs. `d7_packs.py` on the three real packs of 2026-10-29: 168, 57 and 908 documents, kinds adding up, sheets of 29,
    22 and 28 KB in about 2 s each (112 px tiles, blurred). With synthetic packs built with Pillow (40 checks): kinds counted by pattern (a text
    file and a CSV are not documents), kinds beyond the limit fold into Other and still add up, the pick is the same
    whatever the order in the zip and shows every kind before repeating, a broken scan and a member over the size cap are
    skipped, the sheet is a JPEG of the stated size with no metadata, an empty pack has no sheet, a missing pdftoppm or
    Pillow gives counts and no sheet and says why, a file that is not a zip raises and is caught by `pack_preview`, and
    **no file name, lease name or permit number appears in the counts, the sheet record or the log**. `images_job` with
    `--packs` opens only the live day and deletes the zip; a failed download skips the preview and keeps the dataset;
    `validate` reports a missing or oversized sheet and kinds that do not add up; `prune_images` deletes unreferenced
    sheets. A real run (`--date 2026-10-30 --packs`, 365 MB of packs, 6 connection resets absorbed) wrote the three sheets and
    passed `--check`; the verbose page showed them at desktop and phone width with no overflow and no console errors.

## Run and schedule

```
python3 -I site/pipeline/d7_daily.py                  # today (Central), writes the day, index and series, then checks
python3 -I site/pipeline/d7_daily.py --backfill 91    # also rebuild every missing day of the last 91 (the whole archive: about 90 s)
python3 -I site/pipeline/d7_daily.py --date 2026-10-30   # capture that report day live (replaces its file if there is one)
python3 -I site/pipeline/d7_daily.py --skip-if-captured  # exit quietly when today's report was already captured live that night
python3 -I site/pipeline/d7_daily.py --packs             # also open the live day's image packs: counts and a contact sheet (needs Pillow, pdftoppm)
python3 -I site/pipeline/d7_daily.py --check          # only validate
```
`.github/workflows/daily-rrc-report.yml` runs it at 03:15 UTC (10:15 PM CDT / 9:15 PM CST, after the last file the RRC posts
that day) with `--backfill 7`, so a missed night is filled from the RRC's history on the next one, then `--check`, then commits
`site/public/data/daily/` to `main` (titled with the report day, the newest day file, a Central-time date; the run's own UTC date is
already tomorrow at 03:15) and publishes `site/public` to the `gh-pages` branch that GitHub Pages serves (a copy plus
`.nojekyll`; an ordinary push, never a force push; it refuses to publish a copy without `index.html`, `js/main.js` and
`data/meta.json`). The step used to request a Pages build through the API as well as pushing; on its first run GitHub started
two builds for the published commit and cancelled the first, so the request was dropped and the push alone is relied on.
Raw downloads go to `dl/daily/` (gitignored).

**A backup run at 04:20 UTC** (11:20 PM CDT / 10:20 PM CST, still the same Central day) covers a trigger GitHub skips:
scheduled runs can be delayed or dropped, and the first 03:15 UTC run (2026-10-31, the evening of Oct 30) never started.
Scheduled runs pass `--skip-if-captured`: the script exits 0 and changes nothing when the day's file is `live`, `ok` and
was captured at or after 03:00 UTC the next day. On a normal night the backup is a short no-op; when the first run failed
or never ran, it captures the day. (That missed run lost no data: none of the nightly files lands between 20:33, when the
Oct 30 report was captured by hand, and 22:15 Central.)

### Repairing a day

`--backfill` fills days that have no file and never replaces one that exists, so a report that is partial, or was captured
too early, stays as it is until a run names that day. To repair one: Actions, Daily RRC report, Run workflow, put the day
in `date` (YYYY-MM-DD, Central), leave `backfill` at 7. The run captures that day live (`kind` live, `capturedAt` the
repair time) and, since a day shows what the shares had listed by its end, it gives the same report the evening run would
have given, however late it runs (the day's own completions zip, listed the next morning, belongs to the next day's report).
It then commits and publishes like a night's run. Good to know:
- `state` (new / same / first) compares with the previous *live* report; next to rebuilt days it reads `first`.
- A day of an earlier month works (its permits come from the month-end file) as long as that file is on the share.
- The date is checked twice, as a shape in the workflow and as a real day that is not in the future in the script.

Known limits: a rebuilt day has no catalog check, file states or monthly watch; the pending queue is only as old as the
share keeps it; rebuilt days show image pack sizes only (the previews are for days captured live); permit coordinates are ignored here (only part of recent permits have
them).
