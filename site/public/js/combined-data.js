// The merged Overview's data code: the two national sources side by side, as pure functions so Node can test them. Nothing here touches the page.
//
//   oil permits    national.json (the state agencies' own counts: permits approved, or wells spudded where an agency publishes no approval dates), 33 jurisdictions
//   fracked wells  data/newwells/ (FracFocus: one GPS point per fractured well, every state that reports), 27 states
//
// Honesty rules (the repo's CLAUDE.md): the two are never added together (a permit is the right to drill, a fracturing job comes after); counts of different measures (permits
// approved, wells spudded, applications filed, wells drilled) are never added either; the BLM's onshore permits cover wells the states also permit, so they sit on a line of their own;
// a state with no well in the registry is "not in the registry" and a state with no agency file read is "not read yet", never a zero.
import * as N from './national-data.js';
import * as D from './newwells-data.js';

export const BLM = 'BL';
// the short word for what an agency counts, beside its number
export const COUNTS = { permits: 'permits', spuds: 'spuds', applications: 'applications', drilled: 'drilled' };
export const countWord = (measure) => COUNTS[measure] || 'permits';

// one list of every jurisdiction either source knows, in the national report's order (its states, then the ones it could not read), then any state only the registry has:
// { id, name, p: the agency's record or null, g: the unread gap or null, w: the registry's record or null }
export function jurisdictions(nat, doc) {
  const out = []; const seen = new Set();
  const add = (id, name, p, g) => { if (seen.has(id)) return; seen.add(id); out.push({ id, name, p, g, w: doc ? D.byId(doc, id) : null }); };
  for (const s of nat ? nat.states : []) add(s.id, s.name, s, null);
  for (const g of nat ? nat.gaps : []) add(g.id, g.name, null, g);
  for (const w of doc ? doc.states : []) add(w.id, w.name, null, null);
  return out;
}
export const find = (list, id) => list.find((j) => j.id === id) || null;

// an agency's figure as the page shows it: the count, the change on the year before (only from a base of 20), what it counts, and whether it may be added to the others
export function permitFigure(s) {
  if (!s) return null;
  const m = N.measureOf(s.measure);
  return { n: s.p12, prev: s.prev12, change: N.shownChange(s), measure: s.measure, word: countWord(s.measure), unit: N.unitFor(s.p12, s.unit || m.one), none: N.noneRecorded(s), sum: m.sum && !N.OVERLAP.has(s.id), through: s.through, overlap: N.OVERLAP.has(s.id) };
}
// the registry's figure for a state: null when the state has no well in it in the last 12 settled months (the page says "not in the registry", never 0)
export function wellFigure(w) {
  if (!w || !(w.p12 > 0)) return null;
  return { n: w.p12, prev: w.prev12, change: D.shownChange(w), latest: w.latest };
}

// the headline figures for the two layers, each within its own count
export function totals(nat, doc) {
  const wt = D.totals(doc);
  const perm = N.summable(nat, 'permits'); const spud = N.summable(nat, 'spuds');
  const sum = (a) => a.reduce((t, s) => t + s.p12, 0);
  const list = jurisdictions(nat, doc).filter((j) => j.id !== BLM);
  const withPermits = list.filter((j) => j.p && !N.noneRecorded(j.p)); // an agency read, with something dated in 24 months
  const withWells = list.filter((j) => wellFigure(j.w));
  const both = withPermits.filter((j) => wellFigure(j.w));
  return {
    permits: sum(perm), permitStates: perm.length, spuds: sum(spud), spudStates: spud.length,
    wells: wt.p12, wellsPrev: wt.prev12, wellsChange: wt.change, wellStates: wt.active,
    permitJurisdictions: withPermits.length, wellJurisdictions: withWells.length, both: both.length,
    permitsOnly: withPermits.length - both.length, wellsOnly: withWells.filter((j) => !withPermits.includes(j)).length,
    blm: (N.byId(nat, BLM) || {}).p12 ?? null,
  };
}

// every jurisdiction, ranked for the table: by the agency's count or by the registry's. A count the agency makes another way (spuds, applications) is ranked by its number and tagged in the table;
// a state with nothing to rank on comes after the ones that have it. The BLM is returned apart (it overlaps the states), and so are the jurisdictions with no figure in either source.
export function rankRows(nat, doc, by = 'permits') {
  const all = jurisdictions(nat, doc);
  const rows = all.filter((j) => j.id !== BLM);
  const key = (j) => (by === 'wells' ? (wellFigure(j.w) ? j.w.p12 : -1) : (j.p ? j.p.p12 : -1));
  const other = (j) => (by === 'wells' ? (j.p ? j.p.p12 : -1) : (wellFigure(j.w) ? j.w.p12 : -1));
  const has = (j) => !!j.p || !!wellFigure(j.w);
  const ranked = rows.filter(has).sort((a, b) => (key(b) - key(a)) || (other(b) - other(a)) || a.name.localeCompare(b.name));
  return { rows: ranked, none: rows.filter((j) => !has(j)), fed: find(all, BLM) };
}

// the common months of the two series (the agencies' start in 2019, the registry's in 2011), oldest first
export const axis = (nat, doc) => nat.months.filter((m) => doc.months.includes(m));

// one chart's data: fracked wells stacked by state, with the permit counts as lines. The wells run to the newest month with any job (the newest months are still filling in);
// each line runs to the newest month every agency it counts has, so a state that reports late does not read as a fall.
export function monthly(nat, doc) {
  const months = axis(nat, doc);
  const wells = D.stack(doc, months.length);
  const line = (measure) => { const st = N.stack(nat, measure, nat.months.length); return { end: st.end, lagging: st.lagging, values: wells.months.map((m) => { const i = st.months.indexOf(m); return i < 0 ? null : st.totals[i]; }) }; };
  return { months: wells.months, wells, permits: line('permits'), spuds: line('spuds') };
}
// one state's two lines over the last n months: the agency's count (null before it starts and after it ends) and the registry's wells
export function stateMonthly(nat, doc, id, n = 36) {
  const months = axis(nat, doc); const from = Math.max(0, months.length - n); const ms = months.slice(from);
  const p = N.byId(nat, id); const w = D.byId(doc, id);
  const pv = (m) => { if (!p) return null; const i = nat.months.indexOf(m); const v = i < 0 ? null : p.bands.new[i]; return v == null ? null : v; };
  const wv = (m) => { if (!w) return null; const i = doc.months.indexOf(m); return i < 0 ? null : w.new[i]; };
  return { months: ms, permits: p ? ms.map(pv) : null, wells: w && w.p12 > 0 ? ms.map(wv) : null, settledAt: ms.indexOf(doc.settled.slice(0, 7)) };
}

// the busiest counties or operators across the agencies that count permits approved (the BLM and the states that count another way are left out: not the same count). Each state's file lists its
// top 15, so a county of the national top ten is always on a list, and an operator that is below the top 15 in one state is counted from the states where it is above it.
export function permitLeaders(nat, by = 'counties', limit = 8) {
  const group = N.summable(nat, 'permits'); const map = new Map();
  for (const s of group) for (const [label, n] of s[by] || []) {
    const k = by === 'counties' ? s.id + '|' + label : String(label).toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim();
    const cur = map.get(k);
    if (cur) cur.n += n; else map.set(k, { label, state: by === 'counties' ? s.id : null, showState: by === 'counties', n });
  }
  const rows = [...map.values()].sort((a, b) => (b.n - a.n) || a.label.localeCompare(b.label));
  return { rows: rows.slice(0, limit), states: group.length };
}
// one agency's own top counties or operators, in the shape of the registry's leaders (so one list-drawing function serves both)
export const stateLeaders = (s, by = 'counties', limit = 6) => ((s && s[by]) || []).slice(0, limit).map(([label, n]) => ({ label, state: null, n }));

// the permit rings on the map: one per agency with something dated in the last 24 months, sized by its last 12 months. The BLM is not a place, so it has none.
export function rings(nat) {
  return nat.states.filter((s) => !N.OVERLAP.has(s.id) && s.p12 > 0).map((s) => ({ id: s.id, name: s.name, n: s.p12, measure: s.measure }));
}
// how far each source runs: the registry's newest job, and the month the agencies' files end in (their median, and the newest and oldest). Some agencies publish no update time, so their
// "as of" is the day this site read them; the month a file's data runs to is what is compared.
export function reach(nat, doc) {
  const ends = nat.states.filter((s) => !N.OVERLAP.has(s.id) && s.p12 > 0 && s.through).map((s) => s.through.slice(0, 7)).sort();
  return { wells: doc.asOf, settled: doc.settled, permitsMedian: ends.length ? ends[ends.length >> 1] : null, permitsFirst: ends[0] || null, permitsLast: ends[ends.length - 1] || null };
}
