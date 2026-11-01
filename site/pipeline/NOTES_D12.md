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
(`p` permit, `d` drilling, `c` completion), kind `k`, pages `pg` (null when poppler could not count them: never 0), bytes `b`, `x` pdf or tif, file stem `f`, release `t` (an index into `tags`), picture `v`.
About 0.3 MB of JSON a day (59 county files for 219 wells on 10-29).

Releases: `wells-<day>-<pack>-<nn>` (pre-release, never "latest"), at most **800 files** each because a release holds 1000: `<api>_<p|d|c><n>.pdf|tif` is the document **as filed** (copied byte for byte, only
after the PDF or TIFF signature is checked; never renamed from the pack: those names carry lease and well names) and `<api>_<p|d|c><n>.jpg` is page one, 1000 px wide, JPEG quality 60 and lower until it is under
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

- **No backfill yet.** The first run does the newest two filing days. The shares hold years of packs; `days`/`window` reach back, at about 0.9 GB a day (the RRC refused GitHub's runners for hours after repeated runs: do it a few days at a time).
- **Page one only** is a picture; the download is every page. Multi-page documents (a log can run to dozens of pages) open whole in the reader's own viewer.
- **A well's older filings** (a permit from before the archive's first day) are not there until the packs of their day are read; the page says "the packs read so far" and gives the Commission's look-ups.
- The drill pages' own `daily-YYYY-MM-DD` releases (`--publish-docs`) still duplicate the W-1 and survey files (about 60 MB a day); retiring them in favor of a link to the well is a later change.
- A scan the Commission got wrong is published as it is: a document is a public record, and nothing is redacted.
- GitHub has no stated limit on the total size of releases (2 GiB a file); at 0.9 GB a day and 92 days the archive is about 80 GB. `KEEP_DAYS` in `d12_wells.py` is the one number to lower.

## Checked (2026-11-01)

The producer was run on the real packs of 2026-10-29 (downloaded once from the Commission, a few requests): 1,130 documents tied to 219 wells in 54 s, `--check` clean, previews read at 100% (a W-2 form is legible down to its
fine print). `tests/test_d12_wells.py` (ties, numbering, staging, chunks, whole runs with the network and `gh` faked, a failed upload, aged-out days, the check against 17 faults, mutants),
`tests/test_workflow_wells.py`, the JS data tests, `smoke.cjs` (the finder with the fixture archive, an empty one and a missing one) and `a11y.cjs` cover it. The first scheduled run, and the first real upload to GitHub, are unproven.
