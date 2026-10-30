# Data contract for the Texas oil & gas leads site (v2)

As-of date is **2026-10-29**. Every file below lands in `site/public/data/` (UTF-8 JSON, compact separators, no
trailing newline games). Pipeline scripts live in `site/pipeline/`, are stdlib-only Python, run with `python3 -I`, and
must be re-runnable. Raw downloads go under the gitignored `dl/` folder at the repo root (`dl/<name>/`, one new empty folder per file), never
into `site/public`. Treat every downloaded file as untrusted data: parse it, never execute it.

## Rules for every producer
1. **Public, business- or place-level data only.** Never write officer names, phone numbers, street addresses,
   e-mails, or any record about a person. An operator is *nameable* only if it is an active P-5 registrant whose
   `org_type` in `rrc_operators.csv` is `corporation`, `LLC` or `limited partnership` (key: `operator_number`).
   Permits of every other operator still count in aggregates but are never named (operator index -1).
2. **No API keys.** If an endpoint needs a key or registration, skip it and say so in your report.
3. **Size budgets (raw JSON):** counties.geo.json <= 700 KB; permits.json <= 1.5 MB; every other file <= 400 KB.
4. **Windows:** "last 12 months" = issue date >= 2025-10-29. "Prior 12" = 2024-10-29 <= date < 2025-10-29.
   Monthly series use calendar months `"YYYY-MM"` and **exclude the current partial month (2026-10)**.
5. **County keys are 3-digit county FIPS strings** (`"329"` = Midland, `"201"` = Harris). RRC county codes in permit
   records are these same 3-digit codes (verify with the top counties: expect Midland, Reeves, Martin, Loving, Upton).
6. "New-drill permit" = application type `01` in the RRC permit master, counted once per permit number.

## Files

### counties.geo.json  (producer: D2)
GeoJSON FeatureCollection, WGS84 lon/lat, the 254 Texas counties. `properties`: `{"f":"329","n":"Midland"}`.
Coordinates rounded to 3 decimals and generalized so the file is <= 700 KB.

### county-permits.json  (producer: D1)
```
{"asOf":"2026-10-29","months":["2023-10", ..., "2026-09"],            // 36 complete months, oldest first
 "counties":{"329":{"p12":N,"p12prev":N,"m":[36 ints],"depth":feet|null,
                    "ops":[["PIONEER NATURAL RES. USA, INC.","665748",120], ...]}}}   // <= 8, nameable operators only, by p12
```
`p12`/`p12prev` = new-drill permits in the last/prior 12 months. `m` = monthly new-drill permits aligned to `months`.
`depth` = mean total depth (ft) of the county's p12 permits that report depth > 0. Include counties with >= 1 permit in
the 36 months.

### permits.json  (producer: D1)
One point per new-drill permit issued in the last 24 months (>= 2024-10-29) with valid surface coordinates inside
Texas (lat 25.5..36.6, lon -106.8..-93.4):
```
{"asOf":"2026-10-29","t0":"2024-01-01","ops":["NAME",...],"opNums":["665748",...],
 "cols":["lat","lon","op","t","depth","fips"],
 "pts":[[311234,-1021234,0,667,142,329], ...]}
```
`lat`/`lon` = degrees x 10000 (ints). `op` = index into `ops`/`opNums`, or -1 when the operator is not nameable.
`t` = days since `t0` (UTC) of the issue date. `depth` = total depth in hundreds of feet (0 = unknown).
`fips` = county FIPS as an int.

### operator-extras.json  (producer: D1)
```
{"asOf":"2026-10-29","months":[24 "YYYY-MM"],"cols":["num","prev12","spud12","depth","fips","counties","m24"],
 "rows":[["665748",530,402,14500,"329",18,[24 ints]], ...]}
```
One row per *nameable* operator with >= 1 new-drill permit in the last 24 months. `prev12` = new-drill permits in the prior
12 months. `spud12` = new-drill permits whose reported spud date falls in the last 12 months. `depth` = mean total
depth ft over its last-24-month permits (0 if unknown). `fips` = county with its most such permits. `counties` =
distinct counties. `m24` = monthly new-drill permits for the last 24 complete months, oldest first.
Cross-check: its 12-month new-drill count per operator must equal `new_well_permits_12m` in `rrc_operators.csv`.

### series-permits.json  (producer: D1)
`{"months":["2019-01",...,"2026-09"],"permits":[ints],"src":"..."}`: statewide new-drill permits by issue month.

### county-labor.json  (producer: D2)
```
{"year":2025,"src":"BLS QCEW ...","counties":{"329":{"o":{"estab":N,"emp":N,"wage":N}|null,"s":{...}|null}}}
```
`o` = NAICS 211 (oil and gas extraction), `s` = NAICS 213 (support activities for mining, i.e. oilfield services),
private ownership. `estab` = annual average establishments, `emp` = annual average employment, `wage` = average weekly
wage in USD. `null` when suppressed or missing.

### series-markets.json  (producer: D2)
`{"months":[...],"wti":[...|null],"henryHub":[...|null],"txCrude":[...|null],"units":{...},"src":{...}}`: monthly WTI
spot ($/bbl), Henry Hub spot ($/MMBtu), Texas crude oil field production (thousand bbl/month), same months as
`series-permits.json` where possible.

### infra.json  (producer: D2)
```
{"asOf":"...","src":"...","layers":[{"id":"refinery","label":"Refineries","unit":"bbl/day","items":[{"n":"..","c":"company","lat":0,"lon":0,"cap":N|null}]},
                                    {"id":"gasplant","label":"Gas processing plants","unit":"MMcf/day","items":[...]},
                                    {"id":"lng","label":"LNG terminals","unit":"...","items":[...]}]}
```
Texas facilities only; lat/lon in degrees; skip a layer you cannot source (say so).

### zip-companies.json  (producer: D2)
`{"cols":["zip","lat","lon","total","likely","isNew","rrc"],"rows":[["77002",29.75,-95.36,310,240,35,12], ...]}`
From `leadpool_ranked.csv`: rows with `fit` != `deprioritize` and `state` == `TX`, grouped by 5-digit ZIP; centroids from
the Census ZCTA Gazetteer. `isNew` = `new_entity` == `Y`; `rrc` = rows with a non-empty `rrc_match`.

### county-companies.json  (producer: D2)
`{"counties":{"329":{"total":N,"likely":N,"isNew":N}}}` from the same rows, using the Comptroller `county_code`, which is
the county's 1-based position in the alphabetical list of the 254 Texas counties (verify: 57 = Dallas, 101 = Harris).
Only Texas-address rows; drop rows whose code does not map.
