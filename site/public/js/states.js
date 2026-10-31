// Which states the site shows. One choice for every view, kept in the address as st=tx, st=ok or a list (st=tx,nm); no st means all of
// them. A leaf module: nothing here touches the page, so the pure data code and the tests can import it. A new state is one entry in
// STATES and its data files; the order here is fixed (it numbers the states in the permit points and picks their colors).
//
// Texas's files are the original ones, keyed by plain county codes and P-5 operator numbers. Every other state's carry the state in
// their county keys (OK:001) and operator numbers (OK:123), because the states reuse each other's codes, and are listed in `files`:
//   geo       county outlines (data/<geo>.json)               series    new-drill permits by month
//   county    permits per county                              operators the named operators
//   points    one point per recent permit                     crude     the EIA's monthly crude oil production (optional)
// What a state's counts are of: Texas and Oklahoma publish permits by approval date; New Mexico and the federal offshore publish none by well, so their
// files count wells spudded (NOTES_D9.md, NOTES_D10.md). Figures are only added across states that count the same thing.
// Optional fields: `short` (the label in the states bar), `in` (how a sentence says "in" the state), `place` (what its counties are called: the
// federal offshore is divided into protraction areas), `drill` (the name of its time-lapse: "Watch the Gulf drill"), `noDaily` (why there is no
// Daily report: a state with a `dir` has one), `cadence` (how often its source publishes, when the series file does not say: the Overview's freshness list).
const PERMITS = { id: 'permits', noun: 'new-drill permits', short: 'permits', one: 'permit', verb: 'Approved' };
const SPUDS = { id: 'spuds', noun: 'wells spudded', short: 'spuds', one: 'spud', verb: 'Spuds counted' };
const COUNTY = { one: 'county', many: 'counties', suffix: ' County' };
const AREA = { one: 'area', many: 'areas', suffix: ' area', code: 'Protraction area' };
export const STATES = [
  { id: 'TX', name: 'Texas', fips: '48', dir: 'daily', agency: 'Railroad Commission', files: null, measure: PERMITS },
  {
    id: 'OK', name: 'Oklahoma', fips: '40', dir: 'daily-ok', agency: 'Oklahoma Corporation Commission', measure: PERMITS,
    files: { geo: 'counties-ok.geo', series: 'series-permits-ok', county: 'county-permits-ok', operators: 'operators-ok', points: 'permits-ok', crude: 'series-ok' },
  },
  {
    id: 'NM', name: 'New Mexico', fips: '35', dir: 'daily-nm', agency: 'Oil Conservation Division', measure: SPUDS, // its Daily report counts permits approved; the other files count wells spudded
    files: { geo: 'counties-nm.geo', series: 'series-permits-nm', county: 'county-permits-nm', operators: 'operators-nm', points: 'permits-nm', crude: 'series-nm' },
  },
  {
    // the Gulf of America's federal waters (BSEE). Its "counties" are the 63 protraction areas; its file is weekly, so it has no Daily report
    id: 'FO', name: 'Federal offshore', short: 'Offshore', in: 'the federal offshore', fips: null, agency: 'Bureau of Safety and Environmental Enforcement', measure: SPUDS, place: AREA, drill: 'the Gulf drill',
    noDaily: 'BSEE’s file is weekly', cadence: 'weekly',
    files: { geo: 'counties-fo.geo', series: 'series-permits-fo', county: 'county-permits-fo', operators: 'operators-fo', points: 'permits-fo' },
  },
];
export const measureOf = (id) => stateOf(id).measure;
// true when every state in the list counts the same thing (so their numbers can be added and ranked together)
export const sameMeasure = (ids) => new Set(ids.map((id) => measureOf(id).id)).size <= 1;
// what a figure of permits is labelled on a map or a table: "New-drill permits", "Wells spudded", or "Permits and spuds" when the states differ
export const measureLabel = (ids) => (sameMeasure(ids) ? measureOf(ids[0]).noun.replace(/^./, (c) => c.toUpperCase()) : 'Permits and spuds');
// what to call the counts of these states: "new-drill permits", or "new-drill permits (wells spudded in New Mexico and the federal offshore)" when they differ
export function measurePhrase(ids) {
  if (sameMeasure(ids)) return measureOf(ids[0]).noun;
  const lead = ids.filter((id) => measureOf(id).id === 'permits');
  const rest = ids.filter((id) => measureOf(id).id !== 'permits');
  const by = new Map();
  for (const id of rest) { const n = measureOf(id).noun; by.set(n, (by.get(n) || []).concat(id)); }
  return (lead.length ? 'new-drill permits' : 'wells spudded') + ' (' + [...by].map(([noun, list]) => noun + ' in ' + listAnd(list.map(inName))).join(', ') + ')';
}
export const stateOf = (id) => STATES.find((s) => s.id === id);
// the label in the states bar, and how a sentence says "in" the state: "in New Mexico", "in the federal offshore"
export const shortName = (id) => stateOf(id).short || stateOf(id).name;
export const inName = (id) => stateOf(id).in || stateOf(id).name;
// what a state's counties are called: "Midland County" and "counties", but "Green Canyon area" and "areas" offshore. For several states: "counties and areas"
export const placeOf = (id) => stateOf(id).place || COUNTY;
export const placeTitle = (id, name) => name + placeOf(id).suffix;
export const placesWord = (ids) => listAnd([...new Set(ids.map((id) => placeOf(id).many))]);
export const placesOne = (ids) => listAnd([...new Set(ids.map((id) => placeOf(id).one))]);
export const placesOr = (ids) => listOr([...new Set(ids.map((id) => placeOf(id).one))]);
// the states shown that count wells spudded and not permits, said once: "New Mexico and the federal offshore count wells spudded, not permits (their regulators
// publish no approval dates by well)"; '' when none of them does. The caller adds what follows (that their lines end two months back, for instance)
export const spudStates = (ids) => ids.filter((id) => measureOf(id).id === 'spuds');
export function spudsNote(ids) {
  const sp = spudStates(ids);
  if (!sp.length) return '';
  const who = statesIn(sp); const many = sp.length > 1;
  return who.charAt(0).toUpperCase() + who.slice(1) + (many ? ' count' : ' counts') + ' wells spudded, not permits (' + (many ? 'their regulators publish' : 'its regulator publishes') + ' no approval dates by well)';
}
export const stateIndex = (id) => STATES.findIndex((s) => s.id === id);
export const otherStates = STATES.filter((s) => s.files);
export const dailyStates = STATES.filter((s) => s.dir); // the states that have a Daily report

// ?st=ok or ?st=tx,nm narrows to those states; nothing, or nothing that is a state, is all of them
export function parseStates(v) {
  const want = String(v || '').toUpperCase().split(/[,\s]+/).filter(Boolean);
  const got = STATES.map((s) => s.id).filter((id) => want.includes(id));
  return got.length ? got : STATES.map((s) => s.id);
}
export const stateParam = (active) => (active.length === STATES.length ? null : active.map((id) => id.toLowerCase()).join(','));

// a county key: Texas keeps its plain FIPS county code, every other state's carries the state (OK:001)
export const countyKey = (id, fips) => (id === 'TX' ? fips : id + ':' + fips);
export const countyState = (key) => { const i = String(key).indexOf(':'); return i < 0 ? 'TX' : String(key).slice(0, i); };
export const countyCode = (key) => String(key).slice(String(key).indexOf(':') + 1);
// a permit point stores its county as one number: the state's number times 1000 plus its three-digit code, so no two states' codes meet
export const POINT_BLOCK = 1000;
export const pointState = (n) => STATES[Math.floor(n / POINT_BLOCK)].id;
export const pointCountyKey = (n) => countyKey(pointState(n), String(n % POINT_BLOCK).padStart(3, '0'));

let active = STATES.map((s) => s.id);
const subs = new Set();
export const activeStates = () => active.slice();
export const hasState = (id) => active.includes(id);
export const statesKey = (ids = active) => ids.join('+');
// "Texas", "Texas and Oklahoma", "Texas, Oklahoma and New Mexico"
export const listAnd = (items) => (items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1]);
export const statesName = (ids = active) => listAnd(ids.map((id) => stateOf(id).name));
// the same inside a sentence: "across Texas, Oklahoma, New Mexico and the federal offshore"; and with "or"
export const statesIn = (ids = active) => listAnd(ids.map(inName));
export const listOr = (items) => (items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' or ' + items[items.length - 1]);

// true when the selection changed; subscribers hear about it once, with the new list (unless quiet: the router sets the choice an address
// names while it is already drawing the view, so nothing needs telling)
export function setStates(ids, quiet = false) {
  const next = STATES.map((s) => s.id).filter((id) => ids.includes(id));
  if (!next.length || next.join() === active.join()) return false;
  active = next;
  if (!quiet) subs.forEach((fn) => fn(active.slice()));
  return true;
}
export function onStates(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}
