# D12: the well-image archive (`d12_wells.py`, `well-images.yml`)

Every scanned document in the Railroad Commission's three image packs, tied to the **well** it is about, published readable and unmodified as files of GitHub releases,
with a readable picture of its first page. The page is `#images` ("Find a well"; `wells.js`, `wells-data.js`). Decided by the owner on 2026-10-31 (the privacy exception for Texas
images, completion images included, and the Content-Security-Policy's `img-src` for GitHub's image hosts) and asked for on 2026-11-01 ("take the images, download to GitHub and tie
the images to a well at the most granular level"). README, Privacy has the decision and how to undo it.

## Why GitHub holds the files (checked 2026-11-01)

The Commission has **no address that opens one document**. Its W-1 query (`webapps2.rrc.texas.gov/EWA/drillingPermitsQueryAction.do`) and completions query are session-driven pages; a
result's "View Current W-1" is a JavaScript popup that calls `drillingPermitDetailAction.do?methodToCall=generateW1Pdf&docNo=<internal id>&rrcActionMan=<a long encoded navigation token>`.
The internal document number is in none of the bulk files, the token encodes the search that led there, and a link without it answers "Application Error". The imaged-records tools
(`rrcsearch3.neubus.com/esd3-rrc/...&profile=17` for well records and logs) open at an entry page; the Commission's own page for them lists no address that carries an API or permit
number. The only file-level access it offers is the bulk zips this project already reads (`mft.rrc.texas.gov`). So the pages link the Commission's look-up forms (`RRC_LOOKUPS` in
`wells-data.js`: they take the API number) and keep the documents here.

## How a document finds its well

A well is its **8-digit API number**: the county code and the well's own number (`28337830`; written `42-283-37830` with Texas's state code). Checked on the packs of 2026-10-29: 165 of 168
W-1 documents, 57 of 57 surveys and 908 of 908 completion documents tied; what does not tie is counted in the index (`untied`), never guessed, and not published.

| pack | member | the tie |
|---|---|---|
| W-1 images (`subscriptions_<day>.zip`) | `<permit>_W1_*.pdf`, `<permit>_Plat_*.pdf` | the permit number, 7 digits, in the Drilling Permit Daily File (`d7_daily.read_daf`): its API number. A permit not in the file (an old amendment) does not tie: 1 of 74 on 10-29 |
| directional surveys (`MM-DD-YYYY.zip`) | `dir_survey_<id>.pdf` | the pack's CSV: `EXTERNAL_ATTACHMENT_ID` -> `API_NO` |
| completion images (`MM-DD-YYYY.zip`) | `<district>/trackingNo_<n>/<file>` | the **completion data zip of the same day** (`packetData_<n>_Approved\|Submitted.dat`): the PACKET line carries the tracking number (1), operator number (5), **API number (6)**, district folder, county (28) and field name (29). The approved packet wins over the submitted one |

The packet also holds the lease name (26) and an owner's name (30): neither is ever read. Documents are told apart by kind with `d7_packs.KINDS` (the same name patterns as the Daily
report's counts: W-2, G-1, L-1, P-4, well log, W-15, P-16, plat, survey, other).

Sidetracks are not told apart: the API number of the first ten digits (`42-283-37830`) is the well, as everywhere on this site.

## What is published

`site/public/data/wells/index.json`: the packs done (`units`: day, pack `w1|ds|ci`, name and size of the zip, documents held, `tied`, `untied`, `rejected`, wells, release tags), the counties
(`[fips, name, wells, documents]`), the totals and `repo` (which the page builds addresses from). `county/<fips>.json`: `tags` (the releases this county's documents are in) and `wells`: API number
`a`, field `fl`, district `di`, operator number `o` and name `on` (only a corporation, LLC or limited partnership: `operators.json`'s rule, as everywhere), and `docs`: day `d`, stage `s`
(`p` permit, `d` drilling, `c` completion), kind `k`, pages `pg` (null when poppler could not count them: never 0), bytes `b`, `x` pdf, tif or png, file stem `f`, release `t` (an index into `tags`), picture `v`.
About 0.3 MB of JSON a day (59 county files for 219 wells on 10-29).

Releases: `wells-<day>-<pack>-<nn>` (pre-release, never "latest"), at most **800 files** each because a release holds 1000: `<api>_<p|d|c><n>.pdf|tif|png` is the document **as filed** (copied byte for byte, only
after the PDF or TIFF signature is checked; never renamed from the pack: those names carry lease and well names; a scan the Commission saved as `.tif` that is really a PNG is kept as `.png`, see below) and `<api>_<p|d|c><n>.jpg` is page one, 1000 px wide, JPEG quality 60 and lower until it is under
330 KB, no EXIF. A day of 1,134 documents is 3 releases and about 0.9 GB (the 10-29 packs: 31 MB W-1, 28 MB surveys, 306 MB completions zipped; 450 MB of documents and about 160 MB of pictures once opened).
A file GitHub serves from `releases/download/` is `application/octet-stream` with `nosniff` and a download disposition; an `<img>` still draws it (checked in Chromium with those headers on another origin: the `smoke.cjs` stub
sends them the same way), and a link to the document downloads it.

## How a run goes

`python3 -I site/pipeline/d12_wells.py` (the workflow passes `--days 2 --window 14 --budget 40`):

1. read the four share listings (W-1, surveys, completion images, completion data) newest first; `plan()` picks the **newest two filing days that have a pack not done yet**. A pack is left out when it is empty (a 0.3 KB zip),
   was listed less than 90 minutes ago, is done under the same name and size, or (completion images) has no completion data zip. So a pack that landed late, or a night that failed, is done the next day, and a pack the
   Commission replaces is done again and replaces its entries. By hand `--days` (up to 10), `--window` (up to 120) and `--day` reach further back; each filing day is about 0.9 GB.
2. per pack: download the zip (3 tries, 10 minutes, never past the run's own budget), tie, copy each document, draw page one (four at a time: `pdftoppm` under a timeout and, where `prlimit` exists, a memory limit, without the
   repository token; Pillow for TIFF), count pages (`pdfinfo`).
3. upload in releases of at most 800 files (batches of 40, patient retries, every file required to be listed afterwards); only then is the pack recorded and the files written. **A pack that fails to upload is recorded as
   nothing** (no entry ever points at a missing file), the run ends red and the next run does it again. The state is saved after each pack.
4. days older than 92 are removed with their entries and their releases (only tags that are exactly `wells-YYYY-MM-DD-<pack>-NN`).

The RRC refusing the runner is an answer (exit 0, "nothing to do tonight"), as in the other producers; missing poppler or Pillow, or no token, exits 2 before anything is published. `--check` validates the files (every document is where its
county and the index say, totals add up, only nameable operators, no e-mail, web address or phone number, a county file under 2.5 MB). `--no-upload` stages and writes to another `--out` for a trial and refuses the site's own folder.

## Not done, and why

- **Two preview drawers.** The drill pages' previews (`d7_packs.render_preview`, 900 px, gray unless the page has color, at most 200 KB, files of the `daily-YYYY-MM-DD` releases) and this archive's (`render_pdf` / `render_tif` here, 1000 px, at most 330 KB, files of the `wells-*` releases) were written the same day by two sessions. They should become one; the pictures differ only in size.
- **No backfill yet.** The first run does the newest two filing days. The shares hold years of packs; `days`/`window` reach back, at about 0.9 GB a day (the RRC refused GitHub's runners for hours after repeated runs: do it a few days at a time).
- **Page one only** is a picture; the download is every page. Multi-page documents (a log can run to dozens of pages) open whole in the reader's own viewer.
- **A well's older filings** (a permit from before the archive's first day) are not there until the packs of their day are read; the page says "the packs read so far" and gives the Commission's look-ups.
- The drill pages' own `daily-YYYY-MM-DD` releases (`--publish-docs`) still duplicate the W-1 and survey files (about 60 MB a day); retiring them in favor of a link to the well is a later change.
- A scan the Commission got wrong is published as it is: a document is a public record, and nothing is redacted.
- GitHub has no stated limit on the total size of releases (2 GiB a file); at 0.9 GB a day and 92 days the archive is about 80 GB. `KEEP_DAYS` in `d12_wells.py` is the one number to lower.

## The first real run (2026-11-01, dispatched by hand: run 1 of `well-images.yml`)

Proved against GitHub: the completion pack of 2026-10-30 (1,060 documents: 1,057 tied to 152 wells, 3 refused as not a PDF or TIFF: they were PNG files named .tif, kept since 2026-11-01, see the end) was uploaded in three releases of 800, 800 and 514 files in about 7 minutes, every file confirmed, the county files
committed and the site published; on the live site an `<img>` of those release files draws (1000 px wide, the large view too) under the page's Content-Security-Policy, with no console error.
Found: **every download after the first failed** (`HTTP 500`, `ViewExpiredException`): a share's page expires after a few minutes idle and the sessions had been opened before the 7-minute upload. `Shares` now opens a new session and
reads the listing again before every download (`tests/test_d12_wells.py` replays the expiry, and a mutant that reuses the listing's session is caught). The run ended red, as designed: what was uploaded and recorded was committed, and the failed packs
(that day's surveys and W-1 pack, and all of 10-29's) were left for the next run.

The second run (after that fix) did four more packs (the 10-30 surveys and W-1 pack, the 10-29 completion images and surveys: 1,229 documents, 2,458 files, about 10 minutes) and then **GitHub refused the fifth pack's upload**
(`gh release upload failed ... Please wait a few minutes ... scraping GitHub ...`): its secondary rate limit, reached after about 4,500 uploads in 35 minutes across the two runs. `gh()` retried for 2.5 minutes and gave up, so that pack (10-29's W-1) was left for the next run.
Now a failure that reads as a rate limit waits 75, 150, then 180 s (up to 8 tries, never past the run's budget) and `gh` makes one attempt at a time (asking again during a limit extends it); any other failure waits seconds.
A normal night is one new day, about 2,300 files and 10 minutes, well under what triggered it; a catch-up of several days in a row will wait, and stops cleanly at the run's budget.

Then the **site's own deploy was refused**: run 2's `pages build and deployment` failed with `API rate limit exceeded for installation` (HTTP 403) at 02:39:42, a minute after the last upload, so the site stayed on the older build although `gh-pages` held the new files.
The repository's token has one quota, shared with GitHub's own Pages deployment; two runs had used about 4,500 uploads of it in 35 minutes. The next successful publish (any workflow) puts the data live, and nothing is lost. To keep a run from spending it all,
**a run stops starting packs once it has uploaded 3,400 files** (`MAX_FILES_PER_RUN`, `--max-files`): each pack's size is estimated before it is downloaded (`EST_FILES`: 400 W-1, 250 survey, 2,400 completion files, from the four real days seen), the first pack of a run always goes up, a pack that
would pass the cap is left for the next run (a smaller one of an older day may still fit), and the log says so. One ordinary day (about 2,300 files) fits and a second does not, so **a catch-up does about one day per run**: dispatch it again an hour later.

The third run (dispatched after those two fixes, 02:50 UTC) found the limit still on: its first pack (10-29's W-1) waited 22 minutes and failed, and **it then went on** to download 10-28's completion pack and wait another 20 minutes
until its budget ended, recording nothing. A refusal that reads as a rate limit now **stops the run** (`no further pack is started`): asking again does not clear it, and each pack after it only costs 300 MB of the RRC's bandwidth. The run also logs GitHub's
quota before the first pack and after the last (`quota_line()`: `gh api rate_limit` is free), so the next report can say what the limit is instead of guessing. At that point the live site served 407 wells and 2,286 documents (the Pages deploy of run 2's
data succeeded after the limit eased); 10-29's W-1 pack and the 10-28 packs were still to do.

## Checked before the first run (2026-11-01)

The producer was run on the real packs of 2026-10-29 (downloaded once from the Commission, a few requests): 1,130 documents tied to 219 wells in 54 s, `--check` clean, previews read at 100% (a W-2 form is legible down to its
fine print). `tests/test_d12_wells.py` (ties, numbering, staging, chunks, whole runs with the network and `gh` faked, a failed upload, aged-out days, the check against 17 faults, mutants),
`tests/test_workflow_wells.py`, the JS data tests, `smoke.cjs` (the finder with the fixture archive, an empty one and a missing one) and `a11y.cjs` cover it. The first scheduled run, and the first real upload to GitHub, are unproven.

## A PNG saved as .tif (fixed 2026-11-01)

The first real run refused 3 of the 1,060 completion documents of 2026-10-30 (`rejected: 3`): files named `.tif` whose first bytes are a PNG's (the Commission's system saved them under the wrong name). The PDF-or-TIFF signature check is right to refuse a name that does not
match its content, so the fix keeps the check and teaches it this one case: a `.tif` or `.tiff` member that starts with the PNG signature is kept byte for byte under a `.png` name (`ALLOWED`, `sniff` in `d12_wells.py`; a PNG under a `.pdf` name, or anything else that is not what its name says, is still refused),
its page one is drawn by Pillow like a TIFF's, and its entry says `x: png` (the check, the page's address builder and the label all accept it). No other member's handling changed, and `d7_packs.copy_member` only gained an optional table of signatures (the drill pages' staging passes none).
Staged on the real 10-30 pack with the completion ties faked (no download of the data zip): 1,060 kept, 0 refused, 3 PNGs (113,614, 108,654 and 269,120 bytes), every preview drawn, in 76 s.

Packs recorded before the fix with refusals (`rejected > 0`) have no `rules` in their unit, and a unit is `done` only if it refused nothing or was recorded under the current `RULES` (now 2): so the next daily run reads the 10-30 completion pack once more (about 0.5 GB down and the same up, like any pack the Commission replaces) and publishes the three. A pack that still refuses something after that (a document that is genuinely not a document) is
recorded with `rules: 2` and is not read again. Bump `RULES` when a rule starts accepting something it refused, never otherwise.
