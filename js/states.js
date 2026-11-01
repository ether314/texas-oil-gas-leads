// The states that have files of their own. A leaf module: nothing here touches the page, so the pure data code and the tests can import it. A new state is one entry in STATES and
// its data files; the order here is fixed (it picks the colors of the four).
//
// Texas's files are the original ones, keyed by plain county codes and P-5 operator numbers. Every other state's carry the state in
// their county keys (OK:001) and operator numbers (OK:123), because the states reuse each other's codes, and are listed in `files`:
//   geo       county outlines (data/<geo>.json)               series    new-drill permits by month
//   county    permits per county                              operators the named operators
//   points    one point per recent permit                     crude     the EIA's monthly crude oil production (optional)
// What a state's counts are of: Texas and Oklahoma publish permits by approval date; New Mexico and the federal offshore publish none by well, so their
// files count wells spudded (NOTES_D9.md, NOTES_D10.md). Figures are only added across states that count the same thing.
// Optional fields: `in` (how a sentence says "in" the state), `caveat` (what its count leaves out, said wherever the counts are explained).
const PERMITS = { id: 'permits' };
const SPUDS = { id: 'spuds' };
export const STATES = [
  { id: 'TX', name: 'Texas', agency: 'Railroad Commission', files: null, measure: PERMITS },
  {
    id: 'OK', name: 'Oklahoma', agency: 'Oklahoma Corporation Commission', measure: PERMITS,
    files: { geo: 'counties-ok.geo', series: 'series-permits-ok', county: 'county-permits-ok', operators: 'operators-ok', points: 'permits-ok', crude: 'series-ok' },
  },
  {
    id: 'NM', name: 'New Mexico', agency: 'Oil Conservation Division', measure: SPUDS, // its Daily report counts permits approved; the other files count wells spudded
    files: { geo: 'counties-nm.geo', series: 'series-permits-nm', county: 'county-permits-nm', operators: 'operators-nm', points: 'permits-nm', crude: 'series-nm' },
  },
  {
    // the Gulf of America's federal waters (BSEE). Its "counties" are the 63 protraction areas; its file is weekly
    id: 'FO', name: 'Federal offshore', in: 'the federal offshore', agency: 'Bureau of Safety and Environmental Enforcement', measure: SPUDS,
    // a sidetrack or bypass is drilling, but not a new well (NOTES_D10.md): the well that was sidetracked ten times shows no new well, so a page that ranks operators says so
    caveat: 'a well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted',
    files: { geo: 'counties-fo.geo', series: 'series-permits-fo', county: 'county-permits-fo', operators: 'operators-fo', points: 'permits-fo', crude: 'series-fo' },
  },
];
export const stateOf = (id) => STATES.find((s) => s.id === id);
export const measureOf = (id) => stateOf(id).measure;
// how a sentence says "in" the state: "in New Mexico", "in the federal offshore"
export const inName = (id) => stateOf(id).in || stateOf(id).name;
// the first letter capitalized: a name that starts a sentence ("the federal offshore" → "The federal offshore")
export const ucFirst = (s) => s.charAt(0).toUpperCase() + s.slice(1);
// what the states named say their count leaves out: "In the federal offshore a well counts once, ..." (with the offshore alone: "A well counts once, ..."); '' when none of them has anything to say
export const spudCaveat = (ids) => ids.filter((id) => stateOf(id).caveat).map((id) => (ids.length === 1 ? ucFirst(stateOf(id).caveat) : 'In ' + inName(id) + ' ' + stateOf(id).caveat) + '.').join(' ');

// a county key: Texas keeps its plain FIPS county code, every other state's carries the state (OK:001)
export const countyKey = (id, fips) => (id === 'TX' ? fips : id + ':' + fips);
export const statesKey = (ids) => ids.join('+');
// "Texas", "Texas and Oklahoma", "Texas, Oklahoma and New Mexico"
export const listAnd = (items) => (items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1]);
