// Which states the site shows. One choice for every view, kept in the address as st=tx, st=ok or a list (st=tx,nm); no st means all of
// them. A leaf module: nothing here touches the page, so the pure data code and the tests can import it. A new state is one entry in
// STATES and its data files; the order here is fixed (it numbers the states in the permit points and picks their colors).
//
// Texas's files are the original ones, keyed by plain county codes and P-5 operator numbers. Every other state's carry the state in
// their county keys (OK:001) and operator numbers (OK:123), because the states reuse each other's codes, and are listed in `files`:
//   geo       county outlines (data/<geo>.json)               series    new-drill permits by month
//   county    permits per county                              operators the named operators
//   points    one point per recent permit                     crude     the EIA's monthly crude oil production (optional)
export const STATES = [
  { id: 'TX', name: 'Texas', dir: 'daily', agency: 'Railroad Commission', files: null },
  {
    id: 'OK', name: 'Oklahoma', dir: 'daily-ok', agency: 'Oklahoma Corporation Commission',
    files: { geo: 'counties-ok.geo', series: 'series-permits-ok', county: 'county-permits-ok', operators: 'operators-ok', points: 'permits-ok', crude: 'series-ok' },
  },
];
export const stateOf = (id) => STATES.find((s) => s.id === id);
export const stateIndex = (id) => STATES.findIndex((s) => s.id === id);
export const otherStates = STATES.filter((s) => s.files);

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
export const statesName = (ids = active) => ids.map((id) => stateOf(id).name).join(' and ');

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
