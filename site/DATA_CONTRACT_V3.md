# Data contract v3: new market layers for the Texas oil & gas leads site

Adds to `DATA_CONTRACT.md` (read that first: its rules still apply to everything here). Today is **2026-10-30**; use it as
`asOf`. Files land in `site/public/data/`; scripts in `site/pipeline/` (stdlib-only Python, `python3 -I`, re-runnable).
Raw downloads go under the gitignored `dl/` folder at the repo root (`dl/<name>/`, one new empty folder per file), never into `site/public`.
The user approved pulling more public federal, state and local datasets for this task; no keys, no registration, no
accounts: skip any source that needs one and say so. Be a polite client: generic User-Agent
(`Mozilla/5.0 (research script)`), never an e-mail address, no hammering (a few requests per second at most).

## Rules (all producers)
1. Business-, place- or market-level data only: never officer names, phones, street addresses, e-mails, or anything about
   a person. Operators are named **only** if nameable (active P-5 registrant, `org_type` corporation / LLC / limited
   partnership in `rrc_operators.csv`, key `operator_number`); everything else folds into county or statewide totals.
2. County keys are 3-digit county FIPS strings ("329" = Midland). Months are "YYYY-MM". Series exclude any partial month.
3. Every file carries `src` (where the data came from, with the exact page/file names), `asOf`, and units. Say plainly in
   `NOTES_D#.md` what is estimated, suppressed or missing.
4. Size budgets (raw JSON): each file <= 400 KB, except `operator-production.json` <= 500 KB.
5. Never edit files you do not own; do not touch `site/public/*.html|css|js`; no `firebase` commands; no deployment.
6. Cross-check against something independent whenever you can (a total against an EIA figure, a spot value against a
   known anchor) and report the result.

## D4: RRC production (owner: D4)
Source: the RRC Production Data Query dump. Page: https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/
(row "Production Data Query Dump", CSV format, monthly, last Saturday of each month); share GUID
`1f5ddb8d-329a-4459-b7f8-177b4f5ee60d` (file `PDQ_DSV.zip`, about 3.45 GB; fetch with
`python3 -I "<ROOT>/rrc_fetch.py" <GUID> PDQ_DSV.zip <outdir>`); user manual PDF:
https://www.rrc.texas.gov/media/50ypu2cg/pdq-dump-user-manual.pdf (convert with `/opt/homebrew/bin/pdftotext -layout`).
It is a zip of delimiter-separated tables; read the manual for table names, delimiter, keys and units, and stream the big
table straight out of the zip (do not extract it all). Check free disk space first; if the transfer would take more than
about 60 minutes, stop and report. The existing RRC permit and operator files are under `<SP>/dl/` for reference.

### county-production.json
```
{"asOf":"2026-10-30","src":"...","unit":{"oil":"barrels (crude oil + condensate)","gas":"mcf (gas well + casinghead)"},
 "months":[36 "YYYY-MM", oldest first, the latest 36 complete months in the source],
 "counties":{"329":{"o12":N,"g12":N,"o12p":N,"g12p":N,"mo":[36 ints],"mg":[36 ints],"leases":N}}}
```
`o12`/`g12` = the latest 12 months, `o12p`/`g12p` = the 12 before. `mo`/`mg` = monthly oil and gas aligned to `months`.
`leases` = distinct leases with production in the latest 12 months. Counties with no production are omitted.

### operator-production.json
```
{"asOf":"2026-10-30","src":"...","unit":{...},"months":[24 "YYYY-MM"],
 "cols":["num","o12","g12","o12p","g12p","leases","mo"],
 "rows":[["665748",N,N,N,N,N,[24 monthly oil ints]], ...]}
```
Nameable operators only, with o12+g12 > 0, sorted by oil descending, cap the rows to fit the size budget. `num` is the
operator number as in `rrc_operators.csv` (the PDQ may use a different id format: map it and say how).

### series-production.json
`{"months":["2019-01",...],"oil":[...],"gas":[...],"src":"...","unit":{...}}`: statewide monthly totals from the same
data (since 2019-01).
Cross-check: statewide oil per month versus EIA's Texas crude field production (about 178.8 million barrels in 2026-07,
in `site/public/data/series-markets.json` field `txCrude`, thousand barrels): report the percent difference.

## D5: federal county and jobs layers (owner: D5)
### county-business.json  (Census County Business Patterns)
Latest vintage available keylessly (2023 or newer; try the bulk file or the keyless API). Establishments by county for the
oil and gas industries:
```
{"year":2023,"src":"...","codes":{"211":"Oil and gas extraction","213":"Support activities for mining","237120":"Oil and gas pipeline construction","486":"Pipeline transportation","4247":"Petroleum merchant wholesalers","333132":"Oil and gas field machinery manufacturing"},
 "sizeClasses":["1-4","5-9","10-19","20-49","50-99","100-249","250-499","500-999","1000+"],
 "counties":{"329":{"211":{"estab":N,"emp":N|null,"sz":[9 ints]}, "213":{...}}}}
```
Use the codes above (or the closest NAICS level the source offers, and say so). `emp` null when suppressed. Texas counties only.

### series-jobs.json  (BLS)
Texas monthly employment in oil and gas extraction (NAICS 211) and support activities for mining (NAICS 213), thousands of
jobs, 2019-01 to the latest month: `{"months":[...],"oilGas":[...|null],"support":[...|null],"src":"...","unit":"thousand jobs","seasonal":"NSA|SA"}`.
Use the BLS public API v1 (no key, small request limits) or the keyless LABSTAT flat files, whichever works; say which.

### series-outlook.json  (EIA Short-Term Energy Outlook)
Monthly forecast from the latest STEO (public files, e.g. the STEO data tables / xlsx): WTI spot price, Henry Hub spot
price, U.S. crude oil production (million b/d) and U.S. dry gas production (Bcf/d):
`{"issued":"2026-10","actualThrough":"2026-09","months":[...],"wti":[...],"henryHub":[...],"usCrude":[...],"usGas":[...],"src":"...","unit":{...}}`.
Months start at the first forecast month (include 12 months of recent actuals before it, flagged by `actualThrough`) and run
to the end of the horizon. An .xlsx can be read with stdlib `zipfile` + `xml.etree`.

## D6: rigs, taxes, minerals, basins (owner: D6; best effort, each item independent)
### series-rigs.json  (Baker Hughes North America rig count)
Weekly rig counts, since 2019: `{"weeks":["YYYY-MM-DD",...],"txTotal":[...],"permian":[...],"eagleFord":[...],"us":[...],"src":"...","unit":"rigs"}`
(add `txOil`/`txGas` if the source splits them). The public rig count page offers downloadable spreadsheets
(https://rigcount.bakerhughes.com/na-rig-count); if the site blocks scripted access, find another keyless public route
(for example EIA's weekly data) or skip and say so.

### series-tax.json  (Texas Comptroller)
Monthly Texas oil production tax and natural gas production tax revenue (USD millions), 2019 to the latest month:
`{"months":[...],"oilTax":[...],"gasTax":[...],"src":"...","unit":"USD millions"}`. Try data.texas.gov (Socrata, keyless)
and the Comptroller's published monthly revenue tables.

### county-minerals.json  (Texas Comptroller Property Value Study)
Oil, gas and other mineral property value by county (the PVS category for minerals), latest final year available:
`{"year":2024,"src":"...","unit":"USD","counties":{"329":{"v":N}}}`. Keyless downloads only; skip if it needs a form.

### basins.json
Texas counties for the main producing regions, from an authoritative cited source (for example EIA's Drilling
Productivity Report methodology county lists, or RRC district/field documentation); verify every county FIPS exists in
`site/public/data/counties.geo.json`:
`{"src":"...","basins":[{"id":"permian","name":"Permian Basin","fips":["329",...],"note":"..."},{"id":"eagleford","name":"Eagle Ford"...},{"id":"haynesville","name":"Haynesville (East Texas)"...},{"id":"barnett","name":"Barnett"...}]}`.
Only include a basin if you can cite the county list; do not guess.

## What to report (every producer, under 2 KB)
Files written with sizes; each source with the exact page/file/endpoint and download size; the cross-checks and results;
anything skipped and why; anything estimated. Write a short `site/pipeline/NOTES_D#.md` with the same details.

## Amendment (2026-10-30, reviewer): operator-production.json naming rule
For operator-production.json only, an operator is nameable if its P-5 organization type (any P-5 status) is corporation, LLC or limited partnership, because the privacy rule exists to keep individuals out, and the active-status test hid 25.7% of oil. Columns `name`, `status` (P-5 status letter) and `type` are appended after the original cols; read columns by name. Operators with status other than A are not in operators.json, so the Operators table cannot show them: the UI tags them and does not link to a table row that does not exist. All other files keep the original rule. Production files end at `completeThrough` (2026-01): never chart or rank on the statewide `partial` tail.
