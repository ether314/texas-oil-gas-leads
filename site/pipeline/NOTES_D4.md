# NOTES_D4: RRC production layers (producer D4)

Script: `site/pipeline/d4_production.py` (stdlib only, run with `python3 -I`; 55 s on the zip, plus 17 s with `--testzip`;
a re-run gives identical bytes). Files in `site/public/data/`, as-of 2026-10-30: `county-production.json` 119,975 B
(budget 400 KB), `operator-production.json` 466,212 B (500 KB), `series-production.json` 4,380 B (400 KB).

## Read this first (UI)

1. **The three files end at 2026-01, not at the dump's newest month (2026-08).** The RRC counts only the reports it has
   received, and the newest months are far from complete. Statewide crude + condensate, RRC against EIA's Texas field
   production (`series-markets.json` `txCrude`), million bbl: 2025-08 179.1 / 180.9 (-1.0%), 2025-12 177.1 / 179.8 (-1.5%),
   **2026-01 170.6 / 172.4 (-1.1%)**, 2026-02 158.9 / 162.8 (-2.4%), 2026-03 -3.2%, 2026-04 -4.3%, 2026-05 -6.6%,
   2026-06 -8.0%, **2026-07 159.5 / 178.8 (-10.8%)**, 2026-08 147.4 (EIA has no value yet). Through 2025-06 the two agree
   to 0.03% on average (78 months since 2019-01, worst 0.33%), so the gap is a property of the youngest data. Rule used:
   a month is complete when RRC is at least 98% of EIA and every earlier month since 2024-01 is too; the first miss
   (2026-02) ends the window. `completeThrough` in each file says where it ends; `months` follow it (36 for counties,
   24 for operators). Run to 2026-08, the statewide 12-month oil would read 2,003 M bbl against 2,100 M a year earlier
   (-4.6%); to 2026-01 it reads 2,091 M against 2,085 M (+0.3%). Counties and operators carry the same bias.
2. Why it is probably lag, not a real drop (the dump cannot prove it): the gap widens smoothly toward the present, D3 reports
   WTI above 90 USD from March 2026, and D1 shows new-drill permits steady near 600 a month. Reports on file are not the
   cause for the old leases: of the 99,149 leases that produced in H1 2025, 98.9% or more have a filed report through
   2026-06 (97.3% in 2026-07, 88.3% in 2026-08; ad hoc study, not in the script). Row-level filed flags in the script log
   show the same break only in the last two months. The shortfall sits in volumes reported low or not yet reported
   (new wells, late and amended reports). Do not chart or rank on the months after `completeThrough`.
3. The statewide tail is kept: `series-production.json` has `partial` (months 2026-02..2026-08 with oil, gas and
   `vsEia`), and `vsEia` (percent RRC against EIA oil, null where EIA has no value) for every month.
   Draw `partial` dashed or with a note, never as a trend.
4. To use the newest months anyway: `python3 -I site/pipeline/d4_production.py --complete-through 2026-08` (about a minute).
5. **Operators are named by P-5 organization type, whatever the P-5 status (rule changed on the coordinator's request).**
   Before, only active P-5 registrants in `rrc_operators.csv` were named (2,010 operators, 74.3% of oil), which hid large
   producers such as 253162 and 020528. Now an operator is named when its P-5 organization type is corporation, LLC or
   limited partnership, read from `orf850.txt.gz` (`'A '` records: number 3-8, name 9-40, status 42, organization code 45;
   A corporation, H LLC, B limited partnership). Individuals, sole proprietors, partnerships, trusts, joint ventures and other
   types stay unnamed; their volumes stay in the county and statewide totals. **2,753 of the 3,247 operators that produced in
   the latest 12 months are named and hold 99.2% of statewide oil and 99.7% of gas** (`nameableShare`; the 494 unnamed hold
   0.8% of oil); by P-5 status A 2,010, X 352, D 253, I 129, H 8, S 1 (the 2014 P-5 manual defines A active, I inactive,
   D delinquent, S see remarks, and does not list X, H or R). Three columns are added at the end of `cols`: `name` (organization
   name as filed, trimmed, at most 32 characters), `status` (the letter), `type` (corporation, LLC or limited partnership).
   The first seven columns and all 2,010 earlier rows are unchanged; the file is 466,212 B, so no row was dropped. UI: show
   `status` (a name with status X, D or I is not a current registrant) and rank by `o12`. Top 10 by `o12` (12 months to 2026-01):

   | # | num | name | P-5 status | oil M bbl | gas Bcf |
   |---|---|---|---|---|---|
   | 1 | 217012 | DIAMONDBACK E&P LLC | A | 216.6 | 811 |
   | 2 | 665748 | PIONEER NATURAL RES. USA, INC. | A | 216.2 | 785 |
   | 3 | 020528 | ANADARKO E&P ONSHORE LLC | X | 92.6 | 349 |
   | 4 | 253162 | EOG RESOURCES, INC. | X | 87.2 | 603 |
   | 5 | 945936 | XTO ENERGY INC. | A | 65.1 | 353 |
   | 6 | 109333 | BURLINGTON RESOURCES O & G CO LP | X | 64.9 | 249 |
   | 7 | 027200 | APACHE CORPORATION | A | 61.9 | 335 |
   | 8 | 166150 | COG OPERATING LLC | A | 56.6 | 200 |
   | 9 | 628658 | OVINTIV USA INC. | A | 50.3 | 179 |
   | 10 | 148113 | CHEVRON U. S. A. INC. | A | 46.0 | 305 |

6. An operator's series follows the operator of record month by month: a step is often an acquisition, not drilling
   (number 217012 goes from 10.7 M bbl in 2024-12 to 17.3 M in 2025-01). Compare `o12` with `o12p` with that in mind.
7. County oil is the RRC's allocation of multi-county leases (the manual: "an estimate only based on allowables and
   potentials"). Offshore areas (codes 600-715) have no polygon: they are in `offshore` and the statewide series
   (292,610 bbl and 3.0 M mcf over the 36 months), so counties + offshore = statewide for every month in the file.

## Source and download

- `PDQ_DSV.zip`, 3,705,468,067 bytes (3.45 GiB, the size on the page), share
  https://mft.rrc.texas.gov/link/1f5ddb8d-329a-4459-b7f8-177b4f5ee60d (page
  https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/, "Production Data Query Dump"),
  fetched with `rrc_fetch.py` in 56 min 9 s (1.1 MB/s) into `<SP>/dl/pdq_dsv/` (kept there for re-runs). No size mismatch,
  and the zip CRC test reads all 16 members cleanly. Manual: https://www.rrc.texas.gov/media/50ypu2cg/pdq-dump-user-manual.pdf
  (`<SP>/dl/pdq_manual/`, pdftotext). Extract date 20-OCT-26; production months 1993-01..2026-08 (the scheduled cycles
  2026-09..11 hold only zero rows).
- Format: `}`-delimited tables with a header line, one zip member each (`<TABLE>_DATA_TABLE.dsv`); read with `zipfile`
  in 16 MB blocks, never extracted. Used: GP_DATE_RANGE_CYCLE, GP_COUNTY (county number equals FIPS for all 277 rows;
  the 254 onshore ones match `counties.geo.json`), OG_COUNTY_CYCLE (245,786 rows), OG_COUNTY_LEASE_CYCLE (12.8 GB,
  77.2 M rows, sorted by year, newest first), OG_OPERATOR_CYCLE (765,588 rows since 2019-01), OG_DISTRICT_CYCLE (check).
  Units from the manual: oil and condensate barrels, gas and casinghead gas mcf.

## Definitions

- oil = OIL_PROD_VOL + COND_PROD_VOL (crude + condensate); gas = GAS_PROD_VOL + CSGD_PROD_VOL (gas well + casinghead),
  summed over oil leases and gas wells. No volume is adjusted, imputed or scaled. No negative volumes exist in the window.
- `leases` = distinct (O/G code, district, lease number) with oil or gas above zero in the latest 12 months; gas wells
  count as leases. A lease on two counties counts once in each, once per operator.
- `o12`/`g12` = last 12 values of `mo`/`mg`; `o12p`/`g12p` = the 12 before. Counties with no production in the 36 months
  are omitted (36 of 254); three included counties (061, 333, 379) have zeros in the latest 12 months.
- Operators: `num` is the six-digit number as in `rrc_operators.csv` and the P-5 file; the dump uses the same numbers (zero
  padded). `name`, `status` and `type` come from the P-5 file (`--p5`, default `<dl>/p5_orf850/orf850.txt.gz`, 19,532,184
  bytes, share 04652169-eed6-4396-9019-2e270e790f6c, 78,403 organizations of which 44,664 are corporation, LLC or LP).
- Extra fields (the contract's fields are all present): `completeThrough`, `newest`, `offshore` (county file);
  `completeThrough`, `nameableTotal`, `producers`, `nameableShare` (operator file); `completeThrough`, `newest`, `vsEia`,
  `partial` (series file).

## Checks

1. Statewide oil against EIA: see item 1 above (script log; 0.03% mean difference through 2025-06).
2. Gas, ad hoc (not in the script): RRC gas well + casinghead against EIA Texas natural gas gross withdrawals
   (https://www.eia.gov/dnav/ng/hist/n9010tx2m.htm, release 2026-10-30): 2023-01..2024-12 mean +0.4%, worst 1.6%; every month
   through 2026-03 within 2.4% (39 months, mean +0.25%); then -2.4%, -2.1%, -3.3%, -5.9% (2026-04..07), the same lag,
   milder than for oil.
3. Three RRC totals agree: OG_COUNTY_CYCLE, OG_DISTRICT_CYCLE and OG_OPERATOR_CYCLE statewide monthly oil and gas are equal
   in all 92 months since 2019-01 except gas in 2022-01 (county table 922,690,810 mcf, the other two 924,359,733, -0.18%;
   the series keeps the county table). Re-summing OG_COUNTY_LEASE_CYCLE reproduces the county table in all 8,718
   county-month cells of 2023-02..2026-01 (0 differences) and the statewide total through 2026-08.
4. Operators: 24-month oil and gas of 5,888 operators re-summed from the lease rows equal OG_OPERATOR_CYCLE for all but two
   (102445 and 429550: +-2 bbl, +-187 mcf, one lease-month under a different operator). All 2,753 named operators have the
   same name (punctuation and case aside) in OG_OPERATOR_CYCLE as in the P-5 file. The P-5 file and `rrc_operators.csv` agree
   for all 5,938 CSV operators (none missing, no type or name differences), so the new rule only adds operators.
5. Independent recount with separate code (full column-name split) of 6 counties (001, 255, 317, 329, 389, 479) and 3
   operators (217012, 665748, 945936): o12, g12, o12p, g12p and leases identical (9 of 9). It caught a bug that is fixed:
   lease counts had included the months after `completeThrough`.
6. Top counties by oil (12 months to 2026-01): Martin 262 M bbl, Midland 244, Reeves 180, Loving 177, Upton 109, Karnes 98,
   Howard 96, Reagan 70; the same top 5 as D1's permits. Top operators by oil: 217012 and 665748 about 216 M bbl each.
7. The script reloads the three files and asserts shapes, month alignment, sums (`o12 = sum(mo[24:])` and so on) and the
   operator sort order, the three added columns and that every row's type is corporation, LLC or limited partnership; sizes are
   asserted against the budgets. Files are ASCII, compact, no trailing newline. Text is limited to months, FIPS keys,
   operator numbers, the `src` and `unit` texts and, in the operator file only, the names, status letters and types of
   corporations, LLCs and limited partnerships. County and series files are byte-identical to before the rule change.

## Missing or estimated

- Counties and operators have no value after 2026-01 (see above); statewide has `partial`. The "complete" cut rests on
  EIA's own estimates for 2025-07 onward, which are themselves revised; pin the month with `--complete-through` if needed.
- 0.8% of oil and 0.3% of gas belong to unnamed operators (individuals, sole proprietors, partnerships, trusts, joint
  ventures, other types). Named operators include inactive, delinquent and expired registrants (status I, D, X, S, H).
- County figures are RRC allocations, not per-county measurements. EIA gross withdrawals is the only independent gas check.

## Refresh

Fetch the new dump (last Saturday of the month) with `python3 -I rrc_fetch.py 1f5ddb8d-329a-4459-b7f8-177b4f5ee60d
PDQ_DSV.zip <new empty folder under dl/>` (about an hour) and the P-5 file with `python3 -I rrc_fetch.py
04652169-eed6-4396-9019-2e270e790f6c orf850.txt.gz <new empty folder>`, then
`python3 -I site/pipeline/d4_production.py --zip <that file> --p5 <that file> --testzip`. `completeThrough` moves on its own when
`series-markets.json` and the dump advance.
