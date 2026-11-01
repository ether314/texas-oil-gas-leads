// The new-wells data code: pure functions over data/newwells/summary.json (new wells by state and month, from 2011), points.json (one row per well of the last 24
// months with its GPS point) and points-history.json (every earlier well with a point, loaded only when asked), so Node can test them. Nothing here touches the page.
//
// Honesty rules (the repo's CLAUDE.md): a well counts once, on the day of its first fracturing job (FracFocus), so these are wells with a disclosure and not permits;
// a month counts as settled only 120 days after the newest job, because disclosures arrive weeks to months late, and every figure that says "last 12 months" uses settled
// months only; a state with no well in the registry is "not in the registry", never a zero permit count; nothing here adds wells to the permit counts of the National page.

export const DAY = 864e5;
// the colors of the states the stacked chart and the map name; every other state is one quiet slate. Texas, Oklahoma and New Mexico keep the colors the rest of the site gives them.
export const COLORS = {
  TX: 'var(--st-tx)', NM: 'var(--st-nm)', OK: 'var(--st-ok)', ND: 'var(--s1)', CO: 'var(--n-yellow)', PA: 'var(--n-magenta)', LA: 'var(--n-green)', OH: 'var(--n-red)',
};
export const OTHER_COLOR = 'var(--n-other)';
export const colorOf = (id) => COLORS[id] || OTHER_COLOR;
export const LAND = ['private or state land', 'federal land', 'tribal land', 'federal and tribal land'];

export const byId = (doc, id) => doc.states.find((s) => s.id === id) || null;
export const change = (s) => (s.prev12 > 0 ? (s.p12 - s.prev12) / s.prev12 : null);
export const monthsOf = (doc) => doc.months;
export const settledIndex = (doc) => doc.months.indexOf(doc.settled.slice(0, 7));
const isoMs = (iso) => Date.parse(iso + 'T00:00:00Z');
export const dayIso = (ms) => new Date(ms).toISOString().slice(0, 10);

// the 12 settled months the "last 12 months" figures are over: first day, last day, and the 12 months before
export function windowOf(doc) {
  const i = settledIndex(doc);
  return { first: doc.months[i - 11] + '-01', last: doc.settled, months: doc.months.slice(i - 11, i + 1), prevFirst: doc.months[i - 23] + '-01', prevMonths: doc.months.slice(i - 23, i - 11) };
}

export function totals(doc) {
  const p12 = doc.states.reduce((t, s) => t + s.p12, 0);
  const prev12 = doc.states.reduce((t, s) => t + s.prev12, 0);
  return { p12, prev12, change: prev12 > 0 ? (p12 - prev12) / prev12 : null, active: doc.states.filter((s) => s.p12 > 0).length, listed: doc.states.length };
}
export const active = (doc) => doc.states.filter((s) => s.p12 > 0);

// producing states (the national report's list) with no new well in the registry in the last 12 months, as [{ id, name, latest }]: "not in the registry", never a zero.
// `names` maps a state's id to its name; `latest` is the newest job the registry holds for it, or null
export function quiet(doc, producing) {
  const have = new Set(active(doc).map((s) => s.id));
  return producing.filter((p) => !have.has(p.id)).map((p) => ({ id: p.id, name: p.name, latest: (byId(doc, p.id) || {}).latest || null }));
}

// the months a stacked chart shows (the last `n`), the series that stack (the colored states in rank order, the rest as "Other states"), and where the settled months end
export function stack(doc, n = 36, top = 8) {
  const colored = doc.states.filter((s) => COLORS[s.id]).slice(0, top);
  const rest = doc.states.filter((s) => !colored.includes(s));
  const from = Math.max(0, doc.months.length - n);
  const months = doc.months.slice(from);
  const slice = (s) => s.new.slice(from);
  const series = colored.map((s) => ({ id: s.id, name: s.name, color: COLORS[s.id], values: slice(s) }));
  if (rest.length) series.push({ id: 'other', name: 'Other states', color: OTHER_COLOR, count: rest.length, values: months.map((_, i) => rest.reduce((t, s) => t + slice(s)[i], 0)) });
  const totalsByMonth = months.map((_, i) => series.reduce((t, s) => t + s.values[i], 0));
  return { months, series, totals: totalsByMonth, settledAt: months.indexOf(doc.settled.slice(0, 7)) };
}

// ------------------------------------------------------------------------------------------------ the points
// mergePoints(recent, hist): the history (points-history.json: every well with a point from 2011 up to `until`, with county and operator tables of its own) joined to the points file
// as one document for decode(). The history may reach up to 11 months into the points file's days: its rows from the points' first day on are dropped, the points file's own are kept.
// Throws when the two are not from one read (a different set of states).
export function mergePoints(recent, hist) {
  if (hist.states.length !== recent.states.length || hist.states.some((id, i) => id !== recent.states[i])) throw new Error('the history is not from the same read as the points');
  const off = Math.round((isoMs(recent.t0) - isoMs(hist.t0)) / DAY); // days from the history's first day to the points file's
  let k = 0; while (k < hist.n && hist.d[k] < off) k++;
  const counties = recent.counties.slice(); const cix = new Map(counties.map((c, i) => [c[0] + '|' + c[1], i]));
  const cmap = hist.counties.map((c) => { const key = c[0] + '|' + c[1]; if (!cix.has(key)) { cix.set(key, counties.length); counties.push(c); } return cix.get(key); });
  const ops = recent.ops.slice(); const oix = new Map(ops.map((o, i) => [o, i]));
  const omap = hist.ops.map((o) => { if (!oix.has(o)) { oix.set(o, ops.length); ops.push(o); } return oix.get(o); });
  const out = { v: 1, t0: hist.t0, asOf: recent.asOf, n: k + recent.n, states: recent.states, counties, ops };
  for (const col of ['lat', 'lon', 's', 'tvd', 'h2o', 'f']) out[col] = hist[col].slice(0, k).concat(recent[col]);
  out.d = hist.d.slice(0, k).concat(recent.d.map((d) => d + off));
  out.c = hist.c.slice(0, k).map((c) => (c < 0 ? -1 : cmap[c])).concat(recent.c);
  out.o = hist.o.slice(0, k).map((o) => (o < 0 ? -1 : omap[o])).concat(recent.o);
  return out;
}
// decode(points): typed columns, and what the other functions need. day[i] is days since t0 (sorted); lat and lon are degrees.
export function decode(points) {
  const n = points.n;
  const P = {
    n, t0: isoMs(points.t0), asOf: points.asOf, states: points.states, counties: points.counties, ops: points.ops,
    lat: new Float32Array(n), lon: new Float32Array(n), day: new Uint16Array(n), s: new Uint8Array(n), c: new Int16Array(n), o: new Int16Array(n), tvd: new Uint16Array(n), h2o: new Uint16Array(n), f: new Uint8Array(n),
  };
  for (let i = 0; i < n; i++) {
    P.lat[i] = points.lat[i] / 1e4; P.lon[i] = points.lon[i] / 1e4; P.day[i] = points.d[i]; P.s[i] = points.s[i]; P.c[i] = points.c[i]; P.o[i] = points.o[i];
    P.tvd[i] = points.tvd[i]; P.h2o[i] = points.h2o[i]; P.f[i] = points.f[i];
  }
  P.span = n ? P.day[n - 1] : 0;
  return P;
}
export const dayMs = (P, d) => P.t0 + d * DAY;
// whole years the points cover (about 16 from 2011)
export const yearsOf = (P) => Math.round(P.span / 365.25);
export const dayOfIso = (P, iso) => Math.round((isoMs(iso) - P.t0) / DAY);
export const stateOfPoint = (P, i) => P.states[P.s[i]];
export const countyOf = (P, i) => (P.c[i] >= 0 ? P.counties[P.c[i]][1] : null);
export const operatorOf = (P, i) => (P.o[i] >= 0 ? P.ops[P.o[i]] : null);
// the first index whose day is at least d (the days are sorted)
export function firstAtOrAfter(P, d) {
  let lo = 0; let hi = P.n;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (P.day[mid] < d) lo = mid + 1; else hi = mid; }
  return lo;
}
// the range of day numbers the settled 12 months cover, clamped to the points
export function settledRange(P, doc) {
  const w = windowOf(doc);
  return [Math.max(0, dayOfIso(P, w.first)), Math.min(P.span, dayOfIso(P, w.last))];
}

// wells per day over [d0, d1] (inclusive), optionally for one state id; an array of d1 - d0 + 1 counts
export function perDay(P, d0, d1, state = null) {
  const out = new Array(Math.max(0, d1 - d0 + 1)).fill(0);
  const si = state ? P.states.indexOf(state) : -1;
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) if (si < 0 || P.s[i] === si) out[P.day[i] - d0]++;
  return out;
}
// wells per day over [d0, d1] for every state at once: a Map of state id -> array of d1 - d0 + 1 counts (one pass over the points)
export function perDayByState(P, d0, d1) {
  const out = new Map(); const n = Math.max(0, d1 - d0 + 1);
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) {
    const id = P.states[P.s[i]]; let a = out.get(id);
    if (!a) { a = new Array(n).fill(0); out.set(id, a); }
    a[P.day[i] - d0]++;
  }
  return out;
}
// the newest day that has at least `min` wells (the newest days have only a few so far, because operators disclose late); the last day when no day has that many
export function lastBusyDay(P, min = 10) {
  const per = perDay(P, 0, P.span);
  for (let d = per.length - 1; d >= 0; d--) if (per[d] >= min) return d;
  return P.span;
}
// wells per state over [d0, d1]: [{ id, n }] ranked, only states with a well
export function perState(P, d0, d1) {
  const n = new Array(P.states.length).fill(0);
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) n[P.s[i]]++;
  return P.states.map((id, k) => ({ id, n: n[k] })).filter((x) => x.n > 0).sort((a, b) => (b.n - a.n) || a.id.localeCompare(b.id));
}

// the top counties or operators of the wells in [d0, d1], optionally one state's: [{ label, state, n }] and how many wells have none to name.
// A county is named with its state when the list is national; an operator only when it may be named (the rest are counted, never named).
export function leaders(P, d0, d1, { state = null, by = 'c', limit = 8 } = {}) {
  const si = state ? P.states.indexOf(state) : -1;
  const counts = new Map(); let unnamed = 0; let total = 0;
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) {
    if (si >= 0 && P.s[i] !== si) continue;
    total++;
    const k = by === 'c' ? P.c[i] : P.o[i];
    if (k < 0) { unnamed++; continue; }
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  const rows = [...counts].map(([key, n]) => (by === 'c' ? { label: P.counties[key][1], state: P.counties[key][0], n } : { label: P.ops[key], state: null, n }));
  rows.sort((a, b) => (b.n - a.n) || a.label.localeCompare(b.label));
  return { rows: rows.slice(0, limit), unnamed, total };
}

// the share of the wells in [d0, d1] (one state's, or all) that sit on federal or tribal land, as { n, of }
export function landShare(P, d0, d1, state = null) {
  const si = state ? P.states.indexOf(state) : -1;
  let n = 0; let of = 0;
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) { if (si >= 0 && P.s[i] !== si) continue; of++; if (P.f[i]) n++; }
  return { n, of };
}

// the newest `limit` wells (by day, then by file order) as indexes, newest first, optionally one state's
export function newest(P, limit = 12, state = null) {
  const si = state ? P.states.indexOf(state) : -1;
  const out = [];
  for (let i = P.n - 1; i >= 0 && out.length < limit; i--) if (si < 0 || P.s[i] === si) out.push(i);
  return out;
}

// "Texas", "Texas and Ohio", "Texas, Ohio and Utah": the names behind a figure
export const listAnd = (items) => (items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1]);
// a depth in feet and a water volume in gallons as the pages say them
export const feet = (v) => (v ? new Intl.NumberFormat('en-US').format(v * 100) + ' ft' : null);
export const gallons = (v) => (v ? (v / 10).toFixed(1) + ' million gal' : null); // v is in hundreds of thousands of gallons

// a top for a y axis and its ticks: about four to five steps, from 1, 2, 2.5 and 5 times a power of ten (the National page's version rounds a 1,060 up to 2,000)
export function niceTop(v) {
  if (!(v > 0)) return { top: 1, ticks: [0, 1] };
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const step = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => v / m <= 5) || 10 * mag;
  const top = Math.ceil(v / step) * step; const ticks = [];
  for (let t = 0; t <= top + step / 2; t += step) ticks.push(t);
  return { top, ticks };
}
// a change worth showing as a percentage: from a base of at least 20 wells (a drop from 7 to 3 is not "-57%")
export const MIN_BASE = 20;
export const shownChange = (s) => (s.prev12 >= MIN_BASE ? change(s) : null);
