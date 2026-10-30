# D6 notes: series-rigs, series-tax, county-minerals, basins (as of 2026-10-30)

Producer: `site/pipeline/d6_misc.py`, stdlib only, no keys, re-runnable:
`python3 -I site/pipeline/d6_misc.py [--only rigs,tax,minerals,basins] [--as-of YYYY-MM-DD] [--dl-root DIR] [--out DIR]`.
Downloads land in `<dl-root>/<name>[-N]/<file>` (one file per new empty folder; default dl-root is `dl/` at the repo root).
Everything is parsed (zipfile+ElementTree, json, regex), never run. About one request per second per host, generic
User-Agent, no e-mail. An item that fails prints `SKIPPED` and the others still run; an old output is replaced only by a
successful run. All four items were delivered; a full run takes about 100 s and prints every check below.

## series-rigs.json (18,938 bytes)
- 400 weekly Baker Hughes publish dates, 2019-01-04 to 2026-08-28 (`through`). Series: `txTotal`, `txOil`, `txGas`,
  `permian`, `permianTx`, `eagleFord`, `haynesville`, `barnett`, `us`. Dates are 370 Fridays plus 19 Thursdays, 10 Wednesdays
  and 1 Tuesday (holiday weeks); 400 is exactly the number expected for one publish per week, so no week is missing.
- **Baker Hughes blocks scripted access**: `https://rigcount.bakerhughes.com/na-rig-count` answers HTTP 403 "Access Denied"
  (394 bytes), as does the old host `https://bakerhughesrigcount.gcs-web.com/na-rig-count`. Not worked around (no browser
  headers); the script asks the live site once per run and uses it if the block is ever lifted.
- Route used: the Internet Archive's public copies of Baker Hughes' own workbooks (availability API
  `https://archive.org/wayback/available?url=...&timestamp=...`; the CDX API answered 503 and is not used):
  - `https://web.archive.org/web/20260829000213id_/https://rigcount.bakerhughes.com/static-files/e98bcf83-c458-4a88-8f35-4ac4d77628bb`,
    11,790,192 bytes, `08-29-2025 North America Rig Count Report.xlsx` ("New Report (2013-Aug 2025)", weeks 2013-01-04 to 2025-08-29).
  - `https://web.archive.org/web/20260829000213id_/https://rigcount.bakerhughes.com/static-files/3acfe9c4-cdbf-4e4d-b8b2-71535396f8b1`,
    8,034,351 bytes, `08-28-2026 North_America Rig_Count Report.xlsx` (weeks 2024-01-05 to 2026-08-28).
  - Sheet `NAM Weekly` (one row per county/basin/drill-for/trajectory) is summed per publish date.
- **Missing: every week after 2026-08-28 (about 9 weeks).** Baker Hughes' weekly link changes each week; the files behind the
  2026-09-29 and 2026-10-03 page captures (`f686dcd4`, `07b97f18`) are not archived. The UI should show `through`.
- Definitions: `permian` is Baker Hughes' Permian basin **including southeastern New Mexico**, so it exceeds `txTotal` in 263
  of the 400 weeks (use `permianTx`, the Texas part, for a Texas share: 61% to 76% of Texas); `haynesville` includes
  Louisiana; `txOil`/`txGas` leave out "Miscellaneous" rigs (at most 2); `us` is all U.S. rigs.
- Checks: both workbooks' own summary sheets match our sums for their week (2025-08-29: US 536, Texas 241, Permian 255,
  Eagle Ford 39, Haynesville 39, Barnett 2; 2026-08-28: US 588, Texas 282, Permian 267, Eagle Ford 50, Haynesville 57,
  Barnett 1); the two workbooks agree on all 87 overlapping weeks; EIA's monthly U.S. rotary rigs
  (`https://www.eia.gov/dnav/pet/pet_crd_drill_s1_m.htm`, 12,479 bytes) for 2026-03..08 (550, 545, 553, 565, 585, 589) equal
  the monthly means of our U.S weeks (549.8, 545.0, 553.2, 565.2, 584.8, 589.2); U.S. low 244 in the week of 2020-08-14 (the
  widely reported record low). Latest: Texas 282 (oil 225, gas 57), Permian basin 267 of which Texas 177 (63% of Texas);
  Texas ranges 100 (2020-08-14) to 534 (2019-01-04).

## series-tax.json (3,020 bytes)
- 92 months, 2019-01 to 2026-08; `oilTax`, `gasTax` in USD millions (source amounts are USD thousand). Cash basis by month
  of collection, net of refunds, all funds; production is taxed about two months after the production month.
- Source: Comptroller Revenue Watch, `https://comptroller.texas.gov/transparency/revenue/watch/all-funds/data/all-funds-historical.xlsx`
  (128,799 bytes, last modified 2026-10-01; sheets FY 2019 to FY 2026, rows "Oil Production Tax" and "Natural Gas Production
  Tax"). data.texas.gov (Socrata catalog) has no production tax revenue dataset; its "Key Economic Indicators" (`karz-jr5v`)
  carries only gross production values and is used for a cross-check.
- Missing: 2026-09 and later (the file has no FY 2027 sheet yet).
- Checks: fiscal-year totals in the workbook equal the sum of its months (largest gap 2 USD thousand, rounding); the severance
  page (`https://comptroller.texas.gov/transparency/revenue/severance.php`, 80,219 bytes) says FY 2022 collections totaled
  $10.83 billion and oil plus gas production tax for Sep 2021 to Aug 2022 here is $10.83 billion; oil tax collected in month m
  over the gross value of crude produced in m-2 (`https://data.texas.gov/resource/karz-jr5v.json`, 17,112 bytes) has median
  4.45% (3.80% to 6.37%) against the 4.6% statutory rate; last 24 months run 378 to 736 (oil) and 157 to 288 (gas) USD million.
- Odd values are real: 2020-05/06 oil 90.3 and 82.7; **2020-08 gas is negative (-15.0), refunds exceeded receipts**.

## county-minerals.json (5,889 bytes)
- `year` 2025 (latest final School District Property Value Study), all 254 counties, `v` in USD = value assigned to category
  G (oil, gas and other mineral reserves), column `ASGN G`, summed over the ISD-by-county rows. 31 counties have v 0. The value
  is before exemptions; local roll (`LOCL G`) and the Comptroller's own estimate (`PTAD G`) are within 0.2% statewide.
- Sources: `https://comptroller.texas.gov/taxes/property-tax/pvs/` (90,353 bytes) and `.../pvs/2025f/index.php` (97,849 bytes,
  final findings certified 2026-08-27) lead to `https://comptroller.texas.gov/taxes/property-tax/docs/2025-final-isd-worksheet-export-detail.xlsx`
  (1,687,453 bytes). Cross-check files: `.../docs/2025-final-isd-worksheet-export-summary.xlsx` (1,168,065 bytes) and
  `https://comptroller.texas.gov/auto-data/PT2/PVS/2025F/ALL0000001Y.php` (88,229 bytes).
- Checks: 1,549 ISD-by-county rows cover 254 of 254 counties; our statewide category G totals equal the Comptroller's summary
  worksheet to the dollar (local 242,208,930,993; PTAD 241,736,179,808; assigned 242,192,201,495); the ISD summary workbook
  (832 districts) sums to the same assigned total; ranking Midland $32.0B, Martin $25.5B, Reeves $23.6B, Loving $17.0B,
  Upton $12.2B, Karnes $9.5B, Webb, DeWitt, La Salle, Andrews.
- The Comptroller's county code is the strictly alphabetical position (Madison 154 to McMullen 162), so FIPS is not 2*code-1;
  the script maps by county name and checks each split id's code (0 mismatches). Potter and Randall are separate in this export.

## basins.json (4,018 bytes)
- Permian 51 counties, Eagle Ford 23, Haynesville 13, Barnett 25. `fips` is the primary list; `rrc` is the Railroad Commission
  list (Permian 61, Eagle Ford 27, Haynesville 10); `ambiguous` = counties in only one of the two lists; `note` explains.
- Primary: EIA Drilling Productivity Report, sheet `RegionCounties` of `https://www.eia.gov/petroleum/drilling/xls/dpr-data.xlsx`
  (156,163 bytes, last modified 2024-05-13, the final DPR; regions are "delineated along county lines", see
  `https://www.eia.gov/petroleum/drilling/pdf/dpr_methodology.pdf`). EIA has no Barnett region, so Barnett is the RRC list.
  RRC "Affected Counties" on `https://www.rrc.texas.gov/oil-and-gas/major-oil-and-gas-formations/{permian-basin,eagle-ford-shale,
  haynesville-bossier-shale,barnett-shale}/` (57,470 / 53,668 / 53,609 / 53,314 bytes). RRC spellings Dimmitt and Shackleford
  are mapped to Dimmit and Shackelford.
- Checks: every FIPS is in `counties.geo.json` and EIA's county names match the geometry names; no county is in two primary
  lists; 25 of the 25 busiest permit counties are in a primary list; 6,183 of 6,680 last-12-month permits (92.6%) fall in
  primary-list counties (93.9% with the RRC lists); largest permit counties in no list: Baylor 32, Taylor 25, Refugio 17,
  Wichita 17, Brazoria 15.
- Ambiguous: Permian, RRC only: Brewster, Cottle, El Paso, Hudspeth, Jeff Davis, King, McCulloch, Presidio, Runnels, Stonewall.
  Eagle Ford, RRC only: Grimes, Robertson, Walker, Washington. Haynesville, EIA only: Cherokee, Smith, Upshur. Barnett: the RRC
  says "at least 18 counties" but lists 25 without marking the core.
- Baker Hughes' own basin labels (Texas counties with a rig since 2013, from the rig workbooks) are wider than these lists for
  two basins: Permian adds Brewster, Cottle, Hudspeth, Jeff Davis, King, Presidio, Stonewall (all in the RRC list); "Barnett"
  covers 31 Texas counties, 14 outside the RRC list (Baylor, Callahan, Coleman, Concho, Haskell, Jones, Knox, McCulloch, Mills,
  Runnels, San Saba, Taylor, Throckmorton, Wichita; mostly the Bend Arch). Eagle Ford (14) and Haynesville (7) labels sit inside
  the primary lists. So the `barnett` rig series is a broader definition than the Barnett county list.
