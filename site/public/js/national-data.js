// The National view's data code: pure functions over national.json, so Node can test them. Nothing here touches the page.
//
// Honesty rules (the repo's CLAUDE.md): a state that cannot tell a figure says "not available", never zero; counts of different measures
// (permits approved, wells spudded) are never added together; the BLM's onshore permits cover wells on federal land that the states
// also permit, so they are shown on their own line and never added into the states' totals.

export const SPUD = 'spuds';
export const PERMIT = 'permits';
export const OVERLAP = new Set(['BL']); // jurisdictions that overlap the states: shown, never summed

// the bands a permit falls in (d11_nat_common.py), in the order they stack
export const BANDS = [
  { id: 'new', label: 'New wells', color: 'var(--b-new)' },
  { id: 'inj', label: 'Injection and disposal', color: 'var(--b-inj)' },
  { id: 'redrill', label: 'Re-entries and sidetracks', color: 'var(--b-redrill)' },
  { id: 'rework', label: 'Recompletions and reworks', color: 'var(--b-rework)' },
  { id: 'amend', label: 'Amendments and extensions', color: 'var(--b-amend)' },
  { id: 'other', label: 'Other filings', color: 'var(--b-other)' },
];

// a tile grid of the states: [column, row]; the federal offshore (FO) and the BLM (BL) sit beside it
export const TILES = {
  AK: [0, 0], ME: [10, 0], VT: [9, 1], NH: [10, 1],
  WA: [0, 2], ID: [1, 2], MT: [2, 2], ND: [3, 2], MN: [4, 2], IL: [5, 2], WI: [6, 2], MI: [7, 2], NY: [8, 2], RI: [9, 2], MA: [10, 2],
  OR: [0, 3], NV: [1, 3], WY: [2, 3], SD: [3, 3], IA: [4, 3], IN: [5, 3], OH: [6, 3], PA: [7, 3], NJ: [8, 3], CT: [9, 3],
  CA: [0, 4], UT: [1, 4], CO: [2, 4], NE: [3, 4], MO: [4, 4], KY: [5, 4], WV: [6, 4], VA: [7, 4], MD: [8, 4], DE: [9, 4],
  AZ: [1, 5], NM: [2, 5], KS: [3, 5], AR: [4, 5], TN: [5, 5], NC: [6, 5], SC: [7, 5], DC: [8, 5],
  TX: [2, 6], OK: [3, 6], LA: [4, 6], MS: [5, 6], AL: [6, 6], GA: [7, 6],
  HI: [0, 7], FO: [4, 7], FL: [8, 7], BL: [0, 6],
};
// names of the tiles that are not oil-producing jurisdictions in the data (they stay quiet on the map)
export const QUIET_NAMES = {
  ME: 'Maine', VT: 'Vermont', NH: 'New Hampshire', WA: 'Washington', MN: 'Minnesota', WI: 'Wisconsin', RI: 'Rhode Island', MA: 'Massachusetts', IA: 'Iowa',
  NJ: 'New Jersey', CT: 'Connecticut', DE: 'Delaware', MD: 'Maryland', NC: 'North Carolina', SC: 'South Carolina', GA: 'Georgia', HI: 'Hawaii', DC: 'District of Columbia',
};
export const COLS = 11;
export const ROWS = 8;

// the color of a state's own series wherever the national view draws one: the colors the rest of the site gives Texas, Oklahoma, New Mexico and the
// offshore, then the next free slots of the palette for the other big producers. A state without a color is folded into "Other states".
export const SERIES_COLOR = {
  TX: 'var(--st-tx)', OK: 'var(--st-ok)', NM: 'var(--st-nm)', FO: 'var(--st-fo)',
  ND: 'var(--s1)', CO: 'var(--n-yellow)', WY: 'var(--n-magenta)', LA: 'var(--n-green)', CA: 'var(--n-red)',
};

export const byId = (doc, id) => doc.states.find((s) => s.id === id) || null;
export const gapOf = (doc, id) => doc.gaps.find((g) => g.id === id) || null;
export const nameOf = (doc, id) => (byId(doc, id) || gapOf(doc, id) || { name: QUIET_NAMES[id] || id }).name;
export const jurisdictions = (doc) => doc.states.length + doc.gaps.length;

// the change of the last 12 complete months against the 12 before, as a fraction; null when the earlier 12 are zero or missing (never infinity)
export const change = (s) => (s.prev12 > 0 ? (s.p12 - s.prev12) / s.prev12 : null);
// the states that count this measure and may be added: not the overlapping ones
export const summable = (doc, measure) => doc.states.filter((s) => s.measure === measure && !OVERLAP.has(s.id));
export const total = (doc, measure) => summable(doc, measure).reduce((n, s) => n + s.p12, 0);
export const rankBy = (doc, measure) => doc.states.filter((s) => s.measure === measure).sort((a, b) => (b.p12 - a.p12) || a.name.localeCompare(b.name));
export const newest = (doc) => doc.states.reduce((m, s) => (s.asOf > m ? s.asOf : m), '');

// five classes of a state's size against the biggest in its measure: tile color and the legend agree because both use this
export const CLASS_EDGES = [0.5, 0.2, 0.08, 0.02]; // share of the maximum: >= 50%, >= 20%, >= 8%, >= 2%, the rest above zero
export function sizeClass(p12, max) {
  if (!(max > 0) || !(p12 > 0)) return 0;
  const r = p12 / max;
  return r >= CLASS_EDGES[0] ? 5 : r >= CLASS_EDGES[1] ? 4 : r >= CLASS_EDGES[2] ? 3 : r >= CLASS_EDGES[3] ? 2 : 1;
}
export const maxOf = (doc, measure) => Math.max(0, ...summable(doc, measure).map((s) => s.p12));

// what a tile is: a state with data (its size class), a producing state not read yet (a gap), a federal line, or a place with no oil production in the tables
export function tileKind(doc, id) {
  const s = byId(doc, id);
  if (s) return { kind: 'data', measure: s.measure, size: sizeClass(s.p12, maxOf(doc, s.measure)), s };
  const g = gapOf(doc, id);
  if (g) return { kind: 'gap', g };
  return { kind: 'quiet' };
}

// the months a stacked chart shows (the last `n`) and the series that stack: each plotted state in its own color, the rest folded into "Other states".
// The axis ends at the newest month every plotted state has, so a state that reports late does not read as a fall.
export function stack(doc, measure, n = 36, top = 8) {
  const group = summable(doc, measure);
  const plotted = group.filter((s) => SERIES_COLOR[s.id]).sort((a, b) => b.p12 - a.p12).slice(0, top);
  const rest = group.filter((s) => !plotted.includes(s));
  const lastIdx = (s) => { const v = s.bands.new; let i = v.length - 1; while (i >= 0 && v[i] == null) i--; return i; };
  const end = plotted.length ? Math.min(...plotted.map(lastIdx)) : Math.max(0, ...group.map(lastIdx));
  const from = Math.max(0, end - n + 1);
  const months = doc.months.slice(from, end + 1);
  const slice = (s) => s.bands.new.slice(from, end + 1);
  const series = plotted.map((s) => ({ id: s.id, name: s.name, color: SERIES_COLOR[s.id], values: slice(s).map((v) => v || 0) }));
  if (rest.length) {
    const other = months.map((_, i) => rest.reduce((t, s) => t + (slice(s)[i] || 0), 0));
    series.push({ id: 'other', name: rest.length === group.length ? 'States' : 'Other states', color: 'var(--n-other)', values: other, count: rest.length });
  }
  const totals = months.map((_, i) => series.reduce((t, s) => t + s.values[i], 0));
  // states of this count whose own figures end before the axis does (Illinois's layer runs about two months behind): their later months are left out of the bars, not counted as zero
  const lagging = group.filter((s) => lastIdx(s) < end).map((s) => s.name);
  return { months, series, totals, end: months[months.length - 1] || null, lagging };
}

// a state's band mix over its last 12 months: only the bands the state can tell; null when it can tell only `new` (nothing to mix)
export function mix(s) {
  const known = BANDS.filter((b) => s.mix12[b.id] != null);
  if (known.length < 2) return null;
  const sum = known.reduce((t, b) => t + s.mix12[b.id], 0);
  return sum > 0 ? known.map((b) => ({ ...b, n: s.mix12[b.id], share: s.mix12[b.id] / sum })) : null;
}
export const statesWithMix = (doc) => doc.states.filter((s) => mix(s));

// the share of 12 months' new wells by fluid, or null where the state records none
export function fluidMix(s) {
  if (!s.fluid) return null;
  const known = ['oil', 'gas', 'both', 'other'].map((k) => ({ id: k, n: s.fluid[k] }));
  const sum = known.reduce((t, x) => t + x.n, 0) + s.fluid.unknown;
  return sum > 0 ? { parts: known.filter((x) => x.n > 0), unknown: s.fluid.unknown, sum } : null;
}

// one row of the coverage table for every jurisdiction, data or not
export function coverage(doc, order) {
  return order.map((id) => {
    const s = byId(doc, id);
    if (s) return { id, name: s.name, status: s.measure === SPUD ? 'spuds' : 'permits', agency: s.agency, through: s.through, asOf: s.asOf, cadence: s.cadence, basis: s.basis, source: s.source };
    const g = gapOf(doc, id);
    return { id, name: g ? g.name : id, status: 'gap', agency: g && g.agency, grade: g && g.grade, why: g && g.why };
  });
}

// "Texas and Oklahoma", "Texas, Oklahoma and Kansas": the names of the states behind a figure
export const listAnd = (items) => (items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1]);

// a nice top for a y axis and its ticks
export function niceMax(v) {
  if (!(v > 0)) return { top: 1, ticks: [0, 1] };
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => v / m <= 4) || 10 * mag;
  const top = Math.ceil(v / step) * step;
  const ticks = []; for (let t = 0; t <= top + step / 2; t += step) ticks.push(t);
  return { top, ticks };
}
