# NOTES_UI: front end v2 (UI builder)

Static, no build step, no external requests. CSP meta tag unchanged. Old `app.js` is deleted (nothing references it).
Entry: `public/index.html` loads `js/boot.js` (classic, 300 bytes, sets the saved theme before first paint) and `js/main.js` (module).
JS is 128 KB unminified in 12 modules; `app.css` is 29 KB; `index.html` 19 KB. Names and labels only ever enter the DOM as text (no innerHTML).

## Modules (public/js)
- `util.js` DOM builders (`el`, `svg`), formatters, cached `load`/`loadOpt`, `halves()` trend helper, hash helpers, `countUp`.
- `theme.js` Auto/Light/Dark (fires `themechange`; canvases re-read tokens). `tip.js` the one shared tooltip.
- `geo.js` Albers projection (parallels 27.5/35, origin 31N 100W), county Path2Ds, state outline from edges seen once,
  point arrays + spatial grid, ZIP and infra builders, memoized loaders. World units: state is 1000 wide.
- `engine.js` canvas map engine: transform pan/zoom with smoothing, anchored wheel zoom, dblclick, pointer drag, two-pointer pinch,
  keyboard (arrows, +/-, 0), class-path choropleth (7 fills per frame), county lines, glowing state border, hub and county labels with halos and
  collision checks, point layers, grid hit-testing, selection rings. The permit layer is painted into an offscreen layer and reused while
  panning or zooming, then repainted crisp when motion settles.
- `map.js` Map tab UI: metric select, layer chips (shape plus color, double as legend), legend with "No data", side panel / bottom sheet
  (county, operator, permit, facility, ZIP, "Texas at a glance"), table twin, deep links, URL sync with `history.replaceState`.
- `hero.js` hero backdrop (offscreen base layer, ~90 pulsing dots, loop stops off-screen / tab hidden / reduced motion). The map is fitted
  beside the text and above the KPI strip so no chip covers part of the state.
- `charts.js` sparkline, area chart, three-panel market pulse (shared crosshair, one tooltip, arrow-key scrubbing), bar lists.
- `overview.js`, `tables.js` (explorer ported from v1 plus new columns/filters), `main.js` (boot, hash router).

## Data use and graceful degradation
Required: `meta`, `counties.geo`, `permits`, `county-permits`. Optional (feature hides, nothing breaks): `series-permits` (hero chip and pulse),
`series-markets` (WTI and crude panels), `county-labor` (3 labor metrics), `county-companies` (companies metric), `zip-companies` (ZIP layer,
Companies map links and County filter), `infra` (refinery/gas plant/LNG chips, only layers that exist), `operator-extras` (operator columns and panel).
`permits.json` and `companies.json` load lazily; the hero loads `counties.geo` + `permits`.

## Decisions worth knowing
1. **Trends use complete calendar months, not new12 vs prev12.** The RRC permit file ends 2026-10-07, so the day-window "last 12 months" covers
   343 days against 365 for the prior window (county p12 sums to 6,680 vs 6,716 prior: -0.5%, while the complete-month series is 7,141 vs 6,668: +7%).
   So: hero chip = last 12 complete months from `series-permits`; the map's "Change vs prior 12 mo", the county/operator YoY chips and the
   Operators Trend column compare the last 12 against the 12 before from `m` / `m24`. Counts shown as "12 mo" are still `p12` / `new12`
   (contract definition). CSV has both (`new_well_permits_prior_12m` and `permits_*_12_full_months`, `trend_pct_full_months`). Explained in Sources.
   If you want the literal new12/prev12 trend, it is one function (`halves` use in `tables.js`, `map.js`).
2. Dots are drawn as a located subset and said so in the hero note, the Map note and Sources (percentages come from `permits.coverage`).
   Hero and Permits layer draw all 9,404 points; last 12 months brighter. Nothing counts or charts from the dots.
3. County classes: quantiles (up to 7); when 8%+ of counties are exactly 0 (permits) zero gets its own class. Change uses fixed bands
   (+/-10, 25, 50%) with a neutral middle; counties with under 10 permits in 24 months are "No data". Dark ramp stops at step 300 so orange dots keep contrast.
4. Labor `null` is "No data (suppressed by BLS)" in the legend, tooltip, panel and table, never zero.
5. Companies County filter uses the county that holds each ZIP's center (company rows have no county). Versus the Comptroller county code it
   matches within ~2% for most counties (median, counties with 50+ companies; p90 11%), but Midland is -15% (980 vs 1,151); a footnote says so.
6. Map state is mirrored into the URL (`county`, `metric`, `layers`, `op`, `zip`; defaults omitted). An unknown value is ignored; `layers=` (empty) means none.
7. Sources text follows NOTES_D1 to D3 exactly: NAD27 coordinates, EPA GHGRP 2023 locations and gas plants (no capacity), two coordinates from NRCan's copy
   of the EIA Energy Atlas layer, EIA estimates for the newest Texas production months, TX crude null for 2026-08 and 09, offshore permits, 504 operator extras.

## Performance (engine.benchmark, DPR 2, canvas 782x648, dark theme with glow, forced raster flush per frame)
| points | zoom | pan frame avg / p95 / max | crisp repaint after motion |
|---|---|---|---|
| 9,404 (real) | 1 | 0.4 / 1.0 / 2 ms | 26 ms |
| 9,404 | 4 | 0.6 / 3.1 / 5 ms | 10 ms |
| 30,000 (synthetic) | 1 | 0.6 / 6.5 / 9 ms | 42 ms |
| 30,000 | 4 | 0.7 / 6.0 / 8.5 ms | 25 ms |
Before the cached layer the same dark frame cost 16 ms avg / 45 ms p95 (the glow sprites). Light theme has no glow and was cheaper.

## QA done (preview server, `leads-site`)
- Screenshots (light / dark): 1440x900 Overview, Map, Operators, Companies; 1024x768 Overview, Map; 375x812 Overview, Map (with bottom sheet),
  Operators, Sources. Other combinations were checked structurally only. No horizontal page scroll at 375 on any view
  (scrollWidth = 375 for overview, map with all layers and a county, operators, companies, about).
- Console: no errors, no CSP violations; every request same-origin. Static greps: no innerHTML, inline style, inline script, external URL in JS/CSS.
- Map: hover/click county, permit, ZIP, facility; wheel (anchor drift 0 px), drag, double-click, pinch (2.0x for a 2x spread), keyboard (+, -, 0, arrows),
  table twin (254 rows, sortable, county button returns to the map), bottom sheet on a phone width, all layers on, all 7 metrics' legends.
- Deep links: each map param alone and combined, unknown ignored; `#operators?q=NAME&band=all`, `?band=ab|abc`, `#companies?seg=`, `?isNew=1`, `?q=ZIP`, `?county=329`.
- Operators: new columns, null-last sorting, CSV (25 columns), `#map?op=` for an operator with no located permits (empty layer plus a plain message).
  Companies: county filter, CSV. Theme toggle persists (localStorage with try/catch).

## Known gaps and risks
- The Browser pane was often hidden during QA, which pauses requestAnimationFrame; animation-dependent checks used a synchronous `engine.settle()`
  and screenshots can lag a few seconds (count-up numbers and the hero fade-in look mid-way if captured early).
- Not exercised in a browser: prefers-reduced-motion (code paths reviewed: CSS rule, `reduced()` in engine, hero loop, count-up), real touch hardware
  (pinch tested with scripted pointer events), Safari and Firefox (uses `backdrop-filter` with prefix, `color-mix`, ResizeObserver, Path2D.addPath).
- Hash sync uses `replaceState`, so the Back button does not step through map selections.
- Phone bottom sheet (fixed): at widths up to 880px, every selection (tap on a county, dot, plant or ZIP, `county=`, `op=`, `zip=` links, operator links)
  is fitted into the part of the map the sheet does not cover. `map.js` measures the sheet from layout (`coverPx`, which also handles a fixed-position
  sheet), `engine.setPadBottom` shifts every fit, the engine's pan limit gives the covered strip back, and the page scrolls to show the whole map under the
  sticky header. Closing the sheet only clears the padding and never moves the view. Desktop is unchanged (cover is 0). Tested at 375x812 and 360x640,
  light and dark: small county, county at the map's bottom edge, Cameron/Nueces, permit, refinery, ZIP, three deep links, operator link; in every case the
  selection's bounds sit inside the map and above the sheet's top edge, and closing the sheet moved the view 0 px.
- `?debug` exposes `window.__map` (engine, state) for QA only; harmless without the query.
- Gas plant and ZIP layers are dense when all layers are on; the toggles are the control.

## Late fix (reviewer)
- A camera request made before the engine had a size (a deep link applied on a fresh page load) was overwritten by the first resize, which resets to the whole state, so shared #map?county=, op= and zip= links opened unzoomed. engine.js now queues such a request (pendingView in fitBox and focusXY) and replays it on the first resize, instant, no fly-in. Verified by sizing a fresh load: Midland fit, Pioneer extent and ZIP 77002 all land above the phone sheet.


# v3 (round 3): more data, more design

JS is now 229 KB unminified in 18 modules (`util`, `theme`, `tip`, `geo`, `engine`, `map`, `hero`, `charts`, `overview`, `tables`, `main`, plus the new
`icons`, `ui`, `pulse`, `basins`, `insights`, `timelapse`); `app.css` 55 KB; `index.html` 33 KB. Same rules as v2: no external requests, strict CSP meta, no inline
script or style, text-only DOM insertion (static greps clean), 375 px without horizontal scroll.

## What is new
- **Market ticker** (`pulse.js`, under the hero): 8 chips, only the ones whose data exists: WTI, Henry Hub, Texas crude (RRC, with the EIA estimate in the footer; EIA alone if the
  RRC file is missing), Texas rigs, Permian rigs (Texas counties; the basin-wide count incl. New Mexico is in the footer), new-drill permits (latest complete month), oil and gas
  jobs (extraction plus field services, split in the footer), production tax. Each chip shows its **own as-of date and source**, a change against the same time a year earlier
  (weekly rigs use the nearest week), a fluid sparkline and links to its pulse group. Static grid (4 across, 2 on phones, an odd last chip spans the row).
- **Market pulse v2** (`pulse.js`, `charts.js` `seriesGroup`): segmented tabs Prices, Activity, Production, Jobs, Taxes (ARIA tablist, arrow keys). One time axis and one shared
  crosshair per group, small multiples, never a dual axis, arrow keys / Home / End / PageUp/PageDown scrub, live region, "View as table" (one table per panel). Prices adds the EIA
  STEO as a shaded "EIA forecast" zone with a lighter continuation (solid hairlines, no dashes). Events labelled sparingly (COVID-19 2020-04 on WTI and permits, 2022 price spike on
  WTI); labels never overlap. Production draws RRC complete months with the EIA estimate as dots only where RRC has no complete month; the cross-check month is computed in the note.
- **Top producers** (`overview.js`): top 10 by oil, bar + 24-month sparkline + "vs 12 before" chip. **Names come from the production file** (it names every producing corporation, LLC
  or LP whatever its P-5 status); status other than A gets a "P-5 status X" tag; a row links to `#operators?q=NAME&band=all` only if the operator is in the Operators table, to
  `#map?op=NUM` if it has permit points, otherwise it is plain text (EOG, Anadarko and Burlington hold status X, so they show tagged and unlinked).
- **Basins** (`basins.js`, `geo.js` `buildBasins`): small county map (hover or focus a card, or hover the map, to light its counties; the map click opens it) and four cards (permits
  12 mo with change, oil and gas 12 mo to the latest complete month with change, rigs with the definition caveat, top three operators from the counties' top-8 lists, so a lower bound).
- **Map**: metrics Oil production (12 mo), Gas production (12 mo), Change in oil vs prior 12 mo (diverging, fixed bands, counties under 100,000 bbl in 24 months are "no data"),
  Oilfield-service establishments (CBP 213), Oil & gas extraction establishments (CBP 211), Mineral property value; Basin selector (fits the basin, outlines its outer boundary,
  dims everything else); "Watch Texas drill" replay; Share button. County panel adds basin chip, oil and gas KPIs, mineral value, 36-month oil and gas charts, establishments by
  employee size class (histogram, lower bound on the axis). Operator panel adds oil, gas, leases and a 24-month oil chart. Every production figure carries its window
  ("12 mo to Jan 2026"); permits say "to Oct 2026"; legends and tooltips say county volumes are the RRC's allocation of multi-county leases (an estimate).
- **Operators** (`tables.js`): Oil (12 mo to Jan 2026), Gas (12 mo to Jan 2026), Production trend (change chip + 24-month line), filter "Top producers (100 largest by oil)" (ranked among
  the listed operators), sortable, CSV +7 fields (`oil_bbl_12m`, `gas_mcf_12m`, `oil_bbl_prior_12m`, `gas_mcf_prior_12m`, `oil_trend_pct`, `producing_leases_12m`,
  `top_producer_rank_oil`); operators absent from the production file have blank cells. Both tables now mirror search, filters and sort into the URL and have **Share this view**.
- **Insights** (`insights.js`): five templated reads (fastest-growing counties, Permian share of permits and oil, operators ramping up, new entities, WTI move and the EIA outlook);
  thresholds in the text (40+ permits in the earlier period, 20+ in the later); every figure links to the map, a table or the chart.
- **Replay** (`timelapse.js` + `engine.js`): 12 s, play/pause, scrubber (native range, keyboard), date and "N located permits so far", located-subset caveat in the bar. Engine: settled dots
  (older than 21 days) live in the cached layer and are added incrementally; the newest 21 days are drawn each frame with a glow, a white-hot core and a 4-day ping that cool toward the
  normal dot. Reduced motion: no play button, no autoplay, scrubber only. Closing the replay or hiding the Permits layer restores the normal dots.
- **Design**: token layer at the top of `app.css` (spacing, radii, type scale, motion, elevation) with colors in `light-dark()` (one declaration per token; the theme toggle only sets
  `color-scheme`); hairline gradient card borders, inner highlight in dark, hover elevation, 23 inline-SVG icons (`icons.js`, 1.5 px stroke); gradient chart washes, halo end dots,
  value-first tooltips; sliding nav pill, segmented thumbs, reveal-on-scroll (IntersectionObserver, safety net, off with reduced motion), chart draw-in, KPI count-up; skeletons for the
  ticker, insights and pulse; a "Data freshness" strip at the end of the Overview; a sticky "On this page" list on Sources.

## New deep-link parameters (all optional, unknown values ignored)
- `#map?basin=permian|eagleford|haynesville|barnett` fits and outlines the basin (a `county=` in the same link takes the camera, the outline stays).
- `#map?metric=` adds `oil12`, `gas12`, `prodchg`, `e213`, `e211`, `mineral` (a metric whose file is missing is ignored). Existing `county`, `layers`, `op`, `zip` unchanged.
- `#operators?top=1` (Top producers), `sort=<column key>` with `dir=asc|desc`; column keys include `oil12`, `gas12`, `ptrend`, plus the existing ones. Every filter id, `q`,
  `sort` and `dir` are written back to the URL, so **Share this view** copies a link that reopens the same table. Companies likewise (`seg`, `fit`, `county`, `tx`, `isNew`, `match`, `q`).
- QA only: `?still` (no motion, no reveal, no count-up), `?debug` (adds `window.__map` with `engine`, `state`, `S`, `tl`, `setBasin`; `window.__app`).

## Data, windows and caveats worth knowing
- Production ends at `completeThrough` = **2026-01** in all three files (RRC reports lag); the statewide `partial` tail is never charted or ranked, only named in a note. Permits run to
  2026-10-07, rigs to 2026-08-28, tax receipts to 2026-08, jobs and prices to 2026-09, EIA Texas crude to 2026-07, the STEO outlook to 2027-12. Each chip, chart, legend and panel carries its
  own date; Sources lists the rig counts as Internet Archive copies of Baker Hughes' workbooks.
- `operator-production.json` names operators by P-5 organization type (amended contract); the Operators page still lists active registrants only.
- Rigs: "Permian, Texas counties" is `permianTx`; Haynesville includes Louisiana and Barnett is a wider label than the county list (both said on the cards). CBP uses establishments only.
- Mineral value is an appraised tax value (2025 PVS, before exemptions). Counties without production, or without a mineral value, say so instead of showing zero; counties with no CBP row are
  shaded as zero establishments (the Census lists only counties that have some).

## QA done (headless Chrome over CDP at exact sizes, plus the built-in pane; real D4 files)
- 42 screenshots: Overview (hero, pulse), Map (county selected, replay mid-way), Operators, Companies, Sources at 1440x900, 1024x768 and 375x812, light and dark: no console errors,
  CSP violations or failed requests, and `scrollWidth` equals the viewport at every size. Layout shift on load: 0.0025 (desktop), 0 (phone).
- Fresh-load deep links for every new parameter, unknown ones ignored; phone sheet: Midland's bounds sit above the sheet (525 to 674 px vs sheet top 722 at 375x812).
- Keyboard: 34 focus stops on the Overview all show a ring; pulse arrow-key scrubbing with live region; tablist arrows; replay scrubber, play/pause, End; Share toast.
- Reduced motion (media emulation): no draw-in, reveals visible, no play button, scrubber at the end. CSV: 100 rows x 32 columns with the new fields. Theme choice persists.
- Replay frame cadence 16.7 ms (60 fps, p95 16.8) over 5 s at DPR 2; pan frames with every layer on (permits, 1,560 ZIP bubbles, facilities): zoom 1 avg 1.7 / p95 8.7 ms, zoom 4 avg 0.7 /
  p95 1.3 ms, with the replay on 1.1 / 2.5 ms and 1.0 / 6.1 ms.

## Known gaps and risks
- Not exercised: Safari and Firefox (needs `light-dark()`, container queries, `color-mix`, `:focus-visible`), real touch hardware, screen readers beyond the ARIA structure, an automated contrast audit
  (token pairs were checked by calculation).
- Replay and dots use the located subset (about 40% of the last 12 months); the busiest counties look quiet by design and the note says so.
- Basin operators come from each county's top-8 list (a lower bound); Baker Hughes basins are not the county lists.
- The python `http.server` used by the `leads-site` preview has a listen backlog of 5: a cold load fires ~20 requests and can reset one (seen only in tests with it); Firebase is unaffected.
