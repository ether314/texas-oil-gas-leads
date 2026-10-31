# NOTES_D10: the federal offshore (Gulf of America) drilling history (producer D10)

Added 2026-10-31 at the owner's request ("federal offshore, if you can find it"). It is the third state-like source after Oklahoma (D8) and
New Mexico (D9), and it follows New Mexico's choice: it counts **wells spudded**, never permits approved, and the pages say so.

## What the Bureau of Safety and Environmental Enforcement (BSEE) publishes

All public, no key, on the BSEE Data Center (https://www.data.bsee.gov/); read once a week by `d10_fo_monthly.py`:

| file | size | made | what it holds |
|---|---|---|---|
| `Well/Files/5010delimit.zip` | 4 MB (18 MB unzipped) | weekly, Sundays | "All releasable borehole information": 55,575 rows, one per borehole, 29 quoted comma-delimited fields, no header (layout: `Main/HtmlPage.aspx?page=borehole`) |
| `Company/Files/compalldelimit.zip` | 0.2 MB | monthly | the companies BSEE knows, with their numbers and names (19 fields; only the number and the full name are read) |
| `Mapping/Files/protclip.zip` | 1.5 MB | rarely | the 85 official protraction diagrams of the Gulf, clipped to the federal waters, as an ESRI shapefile (NAD27 degrees) |

A borehole row carries its API well number (12 digits: the first ten are the well, the last two its sidetrack or bypass), operator number,
spud date (YYYYMMDD), surface area and block, type (D development, E exploratory, C core test), status, water depth, total measured depth
and surface and bottom locations. The surface latitude and longitude are always there; the total depth is not (below).

## Why wells spudded, and not permits

BSEE does publish its applications for permit to drill (APDs) with approval dates, but only as an online query on the Data Center (Well,
APD): not as a file, and the borehole file has a status "APD" for the 20 wells permitted and not yet spudded, with no approval date. Scraping a
query form is brittle and slow and would put a weekly job at the mercy of a page layout. The spud date, on the other hand, is a real, dated fact for every well
since the 1940s, and is in the weekly file. So, as for New Mexico, the series, the areas, the operators and the points count wells spudded, and the Overview, the Map and the
Operators page name the measure wherever they show it and never add it to the permits of Texas and Oklahoma.

## What is counted

- **A well** is the first ten digits of the API number, on the spud day of its earliest borehole that has one (a sidetrack or bypass is another borehole of
  the same well; one well in the file has a spud date only on a sidetrack). 37,509 wells have a spud date; 505 since 2018.
- **What is not counted: sidetracks and bypasses.** A well is the first ten API digits, so a sidetrack or bypass (another borehole of a well) is not another well, as a re-entry or a sidetrack
  is not a "new-drill permit" in Texas. It is drilling, though: in the 12 months to Aug 2026 the file shows 101 boreholes spudded, 47 of them the first borehole of a new well (counted) and 54 sidetracks or
  bypasses (13 of wells first spudded inside the window, 41 of older wells), and two operators account for 25 of the 41 (Arena Offshore, LP 15, Cantium, LLC 10). An operator that mostly sidetracks therefore
  shows few or no new wells and can sit in band C while its rig is busy. The series' source text (`src`) carries the two numbers for the window, rebuilt weekly, and the Overview, the Map's notes, the
  Operators page and the Sources page say that a sidetrack or bypass is not counted as a well.
- **How small it is.** About 45 wells a year since 2024 (2015: 87, 2021: 41, 2025: 43, 2026 through Oct 3: 36), from 16 operators, all corporations: Shell Offshore
  Inc. (37 since 2024), BP Exploration & Production Inc. (18), Anadarko Petroleum Corporation (15), LLOG Exploration Offshore, L.L.C. (11), Murphy Exploration & Production
  Company - USA (10), Chevron U.S.A. Inc. (10) and ten more. Texas has about 7,900 permits a year. A month holds about four wells, so one is a 25% swing; the pages
  lean on the 12-month counts.
- **An area** is this state's "county": the 63 protraction areas (Green Canyon, Mississippi Canyon, Eugene Island, ...), numbered 001 to 063 in the order of their two-letter codes
  (`AREA_ORDER` in the producer: AC 001 ... GC 024 ... MC 036 ... WR 063). A well's area is the area of its surface block. `--areas` refuses a shapefile that does not hold
  exactly those 63, because the numbering is part of the published points; each feature of `counties-fo.geo.json` carries its two-letter code (`c`) and every rebuild of the points refuses a file that is not the
  63 with the code `AREA_ORDER` gives each number. Two areas have one name in BSEE's shapes ("Sabine Pass", off Louisiana and off Texas): they are published as "Sabine Pass (LA12)" and "Sabine Pass (TX8)", the
  diagrams' own numbers. Many of the 63 have no wells (the Eastern Gulf is closed to leasing); they are drawn, with no figure. The outlines are simplified one ring at a time, so a border between two areas
  is not always the same line on both sides and the map draws some of them heavier than others (the raw shapes share only 3% of their edges, because a long border is two vertices on one side and several on the other;
  left as it is).
- **No depth is published**, as for New Mexico: the file has a total measured depth for 6 of the 46 wells spudded in the last 12 months (it arrives after the well
  is finished, months later); a mean of that few would describe the old wells. The water depth, always there (a median of about 6,000 ft for the recent wells), is not a well depth and is not published as one.
- **The year.** The files end on a month end, so "the last 12 months" are the 12 calendar months from the first day (`calendar_windows` in the spec, `d1_permits_geo.windows(calendar=True)`): the series, the
  areas and the operators add up to the same 47 and 43 (before, one well on Aug 31 of the year before was in the areas' year and not in the series': an independent review found 47 against 44 on one page).
  New Mexico, built the same way, has the same rule.
- **The company's name.** The company file has a row for each name and each address a company has had, sorted by name and not by date. The name published is the one with no end date (field 4), else the one
  that ended last: reading the last row would have named operator 3407 "JSJ ENERGY, LLC" (it has been "Array Petroleum, LLC" since 2016) and 2970 "Castex Offshore, LLC" (now "Inc."), which flips a name's type.
  71 of the 449 operators that ever spudded a well have more than one name in the file.
- **What a rebuild refuses.** `guard()` runs before anything is written; a refusal exits 2 with the reasons, the files stay as committed, and the weekly run ends red after the publish. It refuses a file whose
  months before the last 12 hold fewer wells than the committed series by more than 3% and 3 wells (a truncated file: cut at 95% of the rows it lost a third of the history), more than 10 spud dates that are not
  YYYYMMDD dates (a layout that moved: ISO dates made 36 wells vanish without a word), spud dates that come after the total-depth date on more than 1% of the boreholes that have both (it holds on all 54,496), fewer than 90% of the
  last 24 months' wells with a location in the Gulf, fewer than 90% of the last 12 months' wells with a named operator, more than 2% of the wells in no area of the areas file, an operator name that holds a street address, a suite or a
  post-office box, and an areas file that is not the 63 areas with the two-letter code that `AREA_ORDER` gives each number.
- **The lag.** A spud is reported with some delay and the file is made weekly, so a month is shown only when it ended at least 60 days ago (the files end Aug 31 today).
  60 days is New Mexico's measured figure, used here as a cautious one: this producer has no earlier snapshots of the file to measure BSEE's own. Compare the
  weekly builds over the coming weeks (a month's count should stop growing) and shorten it if it does. One hint that the real delay is shorter: the file made Oct 25, 2026 holds spuds to Oct 3 and 4 wells
  in September (a month holds about four), so reports may arrive within weeks; one file is not a measure (August holds 2), and the committed history of weekly builds will be.
- **Operators** are named only by the corporate rule (`d8_ok_daily.nameable`); the types (corporation, LLC, limited partnership) are read from the names. The company file's other fields (addresses, contacts) are never read
  (it holds a street, suite, city and ZIP for most companies; only the number, the two dates and the name are read, and a name that itself holds an address is refused).
- **Points** are surface locations rounded to 3 decimals (about 100 m), NAD27 degrees as BSEE has them (the difference from NAD83 is under 100 m, invisible at map scale).
- Nothing names an API number, a well, a lease, a platform or a block.

## The files

`series-permits-fo.json`, `county-permits-fo.json`, `operators-fo.json`, `permits-fo.json` (shaped exactly like New Mexico's, built by `d8_ok_monthly.build` with this producer's spec
and checked by its `validate`, privacy gate included) and `counties-fo.geo.json` (the 63 areas, simplified to about a kilometer with Douglas-Peucker, 27 KB; features `{f: "001", n: "Alaminos Canyon"}`).

## Run

```
python3 -I site/pipeline/d10_fo_monthly.py                 # downloads the borehole and company files, builds and checks the four (about 10 s)
python3 -I site/pipeline/d10_fo_monthly.py --check         # only validate what is there
python3 -I site/pipeline/d10_fo_monthly.py --areas         # rebuild counties-fo.geo.json from BSEE's protraction areas (by hand, rarely)
python3 -I site/pipeline/d10_fo_monthly.py --borehole 5010delimit.zip --company compalldelimit.zip   # from local copies
```

## Checks

`tests/test_d10_fo.py`: synthetic boreholes in the real layout for every rule above (a sidetrack is not another well, the earliest spud among a well's boreholes, blank and placeholder dates,
a spud after today, an area with no shape, a location outside the Gulf, an individual and an unknown operator number named by no one, no API number or lease in what is published), the readers
refusing an error page and a handful of companies, the validator on the built files and on five deliberate faults, five mutants, the committed files and the 63 areas (closed rings, inside the
Gulf box, small), and, with `FO_REAL_FILES` set to a folder of the three BSEE zips, the real files. Real run on 2026-10-31: 55,575 boreholes, 4,052 companies, 500 wells through Aug 31 (47 in the last 12 months, 44 before), 16 named operators, 91 points.

## In the site

`site/public/js/states.js` has the fourth entry (`FO`, "Federal offshore", `short: 'Offshore'`, measure SPUDS, no `dir`, so nothing asks it for a Daily report, and a `noDaily` reason that the states bar's note shows).
Its other fields are what makes the shared pages read right: `place` (a protraction area where the others have a county: "Green Canyon area", "Top areas", no FIPS code in the
panel), `in` ("in the federal offshore" inside a sentence), `drill` ("Watch the Gulf drill") and `cadence` (the freshness list says "Publishes weekly"). Its color is a rose (`--st-fo`: #c93b8f light,
#e05aa6 dark) chosen for distance from the other three in normal vision and the common color blindnesses (it is used for dots, bars and lines, never as the color of words). The bar shows
TX, OK, NM and Offshore on a phone below 440 px so all five fit; each button keeps its full name for a screen reader. The graticule extends east for the Gulf's shapes (`geo.js`).

## Crude oil, and the weekly refresh

The EIA publishes a monthly estimate of the federal offshore's crude oil production (series `MCRFP3FM1`, "Federal Offshore--Gulf of America Field Production of Crude Oil", thousand barrels a month: 64.3 million in
Aug 2026, 31.8 at its lowest since 2019, in a 2021 hurricane). It is the offshore's one figure of production here, built by the producer the other two states use (`python3 -I site/pipeline/d8_ok_context.py --state FO`
writes `series-fo.json`, key `foCrude`, one request to EIA's page; the page's title and units are checked, and a value outside 20 to 100 million barrels fails the build). It is refreshed by hand when EIA publishes, about the
end of each month. BSEE's own production files are not used.

`.github/workflows/refresh-monthly.yml` runs `d10_fo_monthly.py` every Monday at 05:40 UTC as a third isolated refresh (with its own check and drop steps; BSEE makes its file on Sundays): a failure puts back the four files
as committed, the other two refreshes go ahead, and the run ends red after the publish. It never rebuilds the map of areas (`--areas` is by hand). The workflow was dispatched once by hand on 2026-10-31 (21:27 UTC) to prove it on a GitHub runner: BSEE answered (the borehole file, 4.0 MB, made 2026-10-25), the checks passed, the twelve files
came out byte-identical to the committed ones and nothing was committed. A week in which BSEE makes a new file is the first that changes them.

## Not available

Permits by approval date (an online query only), depth, production by area or operator (the EIA's state-wide offshore series is all there is), jobs, rig counts, a Daily report (BSEE's file is weekly,
so there is no day to report). The pages say "not available", never zero.
