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
// how many of the history's wells come before the points file's first day: the history's rows from there on are the points file's again (the two overlap by up to 11 months)
export function historyCut(recent, hist) {
  const off = Math.round((isoMs(recent.t0) - isoMs(hist.t0)) / DAY); // days from the history's first day to the points file's
  let k = 0; while (k < hist.n && hist.d[k] < off) k++;
  return k;
}
export function mergePoints(recent, hist) {
  if (hist.states.length !== recent.states.length || hist.states.some((id, i) => id !== recent.states[i])) throw new Error('the history is not from the same read as the points');
  const off = Math.round((isoMs(recent.t0) - isoMs(hist.t0)) / DAY);
  const k = historyCut(recent, hist);
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

/* ---------- the detail files (detail.json, detail-history.json; d13_newwells.py): what the registry also says of the same wells, row i being the points file's row i ---------- */
export const DATUM = ['', 'NAD27', 'NAD83', 'WGS84']; // the code 0 is "not given"
// a detail document goes with a points (or history) document when it is the same read: the same rows, the same first day and the same end
export const detailFits = (detail, pts, history = false) => !!detail && !!pts && detail.v === 1 && detail.n === pts.n && detail.t0 === pts.t0 && (history ? detail.until === pts.until : detail.asOf === pts.asOf);
// the history's detail up to `cut` rows (historyCut), then the recent one: the columns of mergePoints, for the same merged wells
export function mergeDetail(recent, hist, cut) {
  const out = { v: 1, n: cut + recent.n };
  for (const col of ['api', 'end', 'tvd', 'wg', 'nw', 'dat']) out[col] = hist[col].slice(0, cut).concat(recent[col]);
  return out;
}
// typed columns: api (a number: Alabama's starts with a zero), end (days after the first job day), tvd (feet), wg and nw (gallons of water and of other base fluid), dat (a DATUM index); -1 is not known
export function decodeDetail(d) {
  const n = d.n; const out = { n, api: new Float64Array(n), end: new Int16Array(n), tvd: new Int32Array(n), wg: new Int32Array(n), nw: new Int32Array(n), dat: new Uint8Array(n) };
  for (let i = 0; i < n; i++) { out.api[i] = d.api[i]; out.end[i] = d.end[i]; out.tvd[i] = d.tvd[i]; out.wg[i] = d.wg[i]; out.nw[i] = d.nw[i]; out.dat[i] = d.dat[i]; }
  return out;
}
// 42-317-00001: state, county, well (the first ten digits of the API number, as the registry gives them)
export const apiText = (v) => { const s = String(Math.round(v)).padStart(10, '0'); return s.slice(0, 2) + '-' + s.slice(2, 5) + '-' + s.slice(5); };
// every fact the report has about well i: the points' own, and the detail's where P.det is there (null for what is not known: never a zero standing for it)
export function wellFacts(P, i) {
  const det = P.det; const start = dayIso(dayMs(P, P.day[i]));
  return {
    state: stateOfPoint(P, i), county: countyOf(P, i), operator: operatorOf(P, i), lat: P.lat[i], lon: P.lon[i], start, land: P.f[i],
    end: det && det.end[i] >= 0 ? dayIso(dayMs(P, P.day[i] + det.end[i])) : null,
    api: det ? det.api[i] : null,
    tvd: det && det.tvd[i] >= 0 ? det.tvd[i] : (P.tvd[i] ? P.tvd[i] * 100 : null),
    water: det && det.wg[i] >= 0 ? det.wg[i] : (P.h2o[i] ? P.h2o[i] * 1e5 : null),
    nonWater: det && det.nw[i] >= 0 ? det.nw[i] : null,
    datum: det ? (DATUM[det.dat[i]] || null) : null,
  };
}
export const feetText = (v) => (v == null ? null : new Intl.NumberFormat('en-US').format(v) + ' ft');
export const gallonsText = (v) => (v == null ? null : v >= 1e6 ? (v / 1e6).toFixed(1) + ' million gal' : new Intl.NumberFormat('en-US').format(v) + ' gal');
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

// wells a day in the twelve months a day sits in, for all states or one: { perDay, from, to, latest }. The twelve months are centered on the day's month and kept inside the series
// and the settled months; a day in the newest months (or after them) gets the last 12 settled months, with `latest` true. A day in 2014 is set against 2014, not against last year.
export function typicalDay(doc, iso, state = null) {
  const si = settledIndex(doc); let m = doc.months.indexOf(iso.slice(0, 7));
  if (m < 0) m = iso.slice(0, 7) < doc.months[0] ? 0 : si; // outside the series: the nearest end of it
  const start = Math.min(si - 11, Math.max(0, m - 5));
  const months = doc.months.slice(start, start + 12); const rows = state ? [byId(doc, state)].filter(Boolean) : doc.states;
  const wells = rows.reduce((t, s) => t + s.new.slice(start, start + 12).reduce((a, b) => a + b, 0), 0);
  const days = months.reduce((t, ym) => t + new Date(Date.UTC(+ym.slice(0, 4), +ym.slice(5), 0)).getUTCDate(), 0);
  return { perDay: wells / days, from: months[0], to: months[11], latest: start === si - 11 };
}
// ------------------------------------------------------------------------------------------------ what a set of wells looks like
// The facts every state's disclosures carry for every well: where (a GPS point, a county), how deep (true vertical depth), how much water, whose land (federal or tribal), who drilled
// (an operator that may be named). profile() reads them for any range of days and one state or all; the Daily report sets a day's profile against the twelve months around it.
export const PAD_M = 150; // wells fractured the same day this close count as one pad (a point is rounded to about 11 m, and a pad's wellheads are a few meters apart)
export const HOT_MILES = 10; // the "busiest spot" is the circle of this radius that holds the most of a day's wells
export const POOL_GAL = 660430; // an Olympic swimming pool, 2,500 cubic meters, in U.S. gallons
export const DEPTH_BANDS = [[0, 6000, 'Under 6,000'], [6000, 8000, '6,000 to 8,000'], [8000, 10000, '8,000 to 10,000'], [10000, 12000, '10,000 to 12,000'], [12000, Infinity, '12,000 and over']]; // feet, true vertical depth
const DEG_M = 111320; // meters in a degree of latitude
const median = (a) => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
// the wells' indexes over [d0, d1] for one state or all
export function indexesOf(P, d0, d1, state = null) {
  const si = state ? P.states.indexOf(state) : -1; const out = [];
  for (let i = firstAtOrAfter(P, d0); i < P.n && P.day[i] <= d1; i++) if (si < 0 || P.s[i] === si) out.push(i);
  return out;
}
// pads among the wells of ONE day (indexes): wells within PAD_M of each other, through any chain of neighbors, are one pad. Returns the number of pads.
function padsOfDay(P, idx) {
  const n = idx.length; if (n < 2) return n;
  const root = idx.map((_, k) => k); const find = (k) => { while (root[k] !== k) { root[k] = root[root[k]]; k = root[k]; } return k; };
  const lim = PAD_M * PAD_M; let pads = n;
  for (let a = 0; a < n; a++) {
    const ia = idx[a]; const cos = Math.cos((P.lat[ia] * Math.PI) / 180);
    for (let b = a + 1; b < n; b++) {
      const ib = idx[b]; const dy = (P.lat[ib] - P.lat[ia]) * DEG_M; const dx = (P.lon[ib] - P.lon[ia]) * DEG_M * cos;
      if (dx * dx + dy * dy <= lim) { const ra = find(a); const rb = find(b); if (ra !== rb) { root[ra] = rb; pads--; } }
    }
  }
  return pads;
}
// pads over any range: each day on its own (a pad fractured over several days is a pad each day)
export function padsOf(P, idx) {
  let pads = 0; let from = 0;
  for (let k = 1; k <= idx.length; k++) if (k === idx.length || P.day[idx[k]] !== P.day[idx[from]]) { pads += padsOfDay(P, idx.slice(from, k)); from = k; }
  return pads;
}
// the busiest spot of a set of wells (one day's): the well with the most others within HOT_MILES, as { n, of, county, state } (the county most of those wells are in), or null with under 3 wells
export function hotSpot(P, idx, miles = HOT_MILES) {
  const n = idx.length; if (n < 3) return null;
  const lim = miles * 1609.344; const lim2 = lim * lim; let best = -1; let bestAt = -1;
  const near = (a) => { const out = []; const cos = Math.cos((P.lat[a] * Math.PI) / 180); for (const b of idx) { const dy = (P.lat[b] - P.lat[a]) * DEG_M; const dx = (P.lon[b] - P.lon[a]) * DEG_M * cos; if (dx * dx + dy * dy <= lim2) out.push(b); } return out; };
  for (let k = 0; k < n; k++) { const c = near(idx[k]).length; if (c > best) { best = c; bestAt = idx[k]; } }
  if (best < 2) return null;
  const counts = new Map(); for (const b of near(bestAt)) if (P.c[b] >= 0) counts.set(P.c[b], (counts.get(P.c[b]) || 0) + 1);
  const top = [...counts].sort((a, b) => b[1] - a[1] || P.counties[a[0]][1].localeCompare(P.counties[b[0]][1]))[0];
  return { n: best, of: n, county: top ? P.counties[top[0]][1] : null, state: top ? P.counties[top[0]][0] : stateOfPoint(P, bestAt) };
}
// profile(P, d0, d1, { state, hot }): everything the Daily report's numbers card shows, for the wells of the range. Depth and water are counted only over the wells that have one (`n` of each says how many),
// an operator is named only when it may be (`unnamed` wells have none to name), nothing is a zero where the registry has no figure.
export function profile(P, d0, d1, { state = null, hot = false } = {}) {
  const idx = indexesOf(P, d0, d1, state); const n = idx.length;
  const depths = []; const waters = []; const land = [0, 0, 0, 0]; const ops = new Map(); const cos = new Map(); const sts = new Set(); const band = DEPTH_BANDS.map(() => 0);
  const weekday = new Array(7).fill(0); let unnamed = 0; let deepest = -1; let wettest = -1;
  for (const i of idx) {
    sts.add(P.s[i]); land[P.f[i] & 3]++;
    if (P.c[i] >= 0) cos.set(P.c[i], (cos.get(P.c[i]) || 0) + 1);
    if (P.o[i] >= 0) ops.set(P.o[i], (ops.get(P.o[i]) || 0) + 1); else unnamed++;
    if (P.tvd[i]) { const ft = P.tvd[i] * 100; depths.push(ft); band[DEPTH_BANDS.findIndex(([lo, hi]) => ft >= lo && ft < hi)]++; if (deepest < 0 || P.tvd[i] > P.tvd[deepest]) deepest = i; }
    if (P.h2o[i]) { waters.push(P.h2o[i] / 10); if (wettest < 0 || P.h2o[i] > P.h2o[wettest]) wettest = i; }
    weekday[new Date(dayMs(P, P.day[i])).getUTCDay()]++;
  }
  const rank = (m, key) => [...m].map(([k, c]) => ({ key: k, n: c })).sort((a, b) => b.n - a.n || key(a.key).localeCompare(key(b.key)));
  const where = (i) => (i < 0 ? null : { county: countyOf(P, i), state: stateOfPoint(P, i) });
  const total = waters.reduce((a, b) => a + b, 0);
  return {
    n, states: sts.size, counties: cos.size, pads: padsOf(P, idx), hot: hot ? hotSpot(P, idx) : null,
    depth: { n: depths.length, median: median(depths), max: deepest < 0 ? null : { ft: P.tvd[deepest] * 100, ...where(deepest) }, bands: band },
    water: { n: waters.length, total, median: median(waters), max: wettest < 0 ? null : { mgal: P.h2o[wettest] / 10, ...where(wettest) }, pools: total * 1e6 / POOL_GAL },
    land: { counts: land, federalOrTribal: n - land[0] },
    operators: { named: ops.size, unnamed, top: rank(ops, (k) => P.ops[k]).slice(0, 5).map((r) => ({ label: P.ops[r.key], n: r.n })) },
    topCounties: rank(cos, (k) => P.counties[k][1]).slice(0, 5).map((r) => ({ label: P.counties[r.key][1], state: P.counties[r.key][0], n: r.n })),
    weekday,
  };
}
// the months a day is set against, as day numbers inside the points: { d0, d1, from, to (ISO days), clipped } or null when the points hold none of them. `typicalDay` (the counts) names the
// months; the points may hold fewer (the last two years only), so the range is cut to them and `clipped` says so.
export function typicalRange(P, doc, iso) {
  const t = typicalDay(doc, iso); const first = t.from + '-01'; const lastDay = dayIso(Date.UTC(+t.to.slice(0, 4), +t.to.slice(5), 0));
  const d0 = Math.max(0, dayOfIso(P, first)); const d1 = Math.min(P.span, dayOfIso(P, lastDay));
  if (d1 < d0) return null;
  return { d0, d1, from: dayIso(dayMs(P, d0)), to: dayIso(dayMs(P, d1)), clipped: d0 > dayOfIso(P, first) || d1 < dayOfIso(P, lastDay) };
}
// how a day's count ranks among the days of a range: the share of those days that had fewer wells (0 to 1), for all states or one
export function dayRank(P, d, d0, d1, state = null) {
  const per = perDay(P, d0, d1, state); if (!per.length) return null;
  const n = perDay(P, d, d, state)[0];
  return { share: per.filter((v) => v < n).length / per.length, days: per.length, n };
}

// ------------------------------------------------------------------------------------------------ oil permits, on the wells' days
// The state agencies' records that have a published point and a date (the files the Map tab reads: permits.json for Texas, permits-ok, permits-nm, permits-fo). Texas and Oklahoma count permits
// approved; New Mexico and the federal offshore count wells spudded, because their regulators publish no approval date by well. Each row is [lat, lon, operator, t, depth, county]: degrees times
// 10,000, an index into the file's operators or -1 (only a corporation, LLC or partnership is named), days since the file's own t0, hundreds of feet, a county code. Texas's points are partial
// (the Commission adds a surface location late: about 40% of the last 12 months' permits have one), so a count made from them is "with a location", never "all".
export const PERMIT_SOURCES = [
  { id: 'TX', file: 'permits', name: 'Texas', spud: false }, { id: 'OK', file: 'permits-ok', name: 'Oklahoma', spud: false },
  { id: 'NM', file: 'permits-nm', name: 'New Mexico', spud: true }, { id: 'FO', file: 'permits-fo', name: 'Federal offshore', spud: true },
];
export const permitStateName = (id) => (PERMIT_SOURCES.find((x) => x.id === id) || {}).name || id;
// decodePermits(docs, t0): docs is [{ id, pm }] (a state's id and its parsed file, the states in the order given), t0 the ISO date the wells' day numbers count from. The result has the wells' shape:
// n, day (days since t0, sorted), lat, lon, s (index into states), op (index into ops, or -1), tvd; rows before t0 are left out. spud[k] is 1 when state k counts wells spudded.
export function decodePermits(docs, t0) {
  const base = isoMs(t0); const rows = []; const ops = []; const oix = new Map();
  docs.forEach((d, k) => {
    const off = Math.round((isoMs(d.pm.t0) - base) / DAY);
    for (const p of d.pm.pts) {
      const day = p[3] + off; if (day < 0) continue;
      let o = -1;
      if (p[2] >= 0 && d.pm.ops[p[2]]) { const nm = d.pm.ops[p[2]]; if (!oix.has(nm)) { oix.set(nm, ops.length); ops.push(nm); } o = oix.get(nm); }
      rows.push([day, k, p[0], p[1], o, p[4]]);
    }
  });
  rows.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const n = rows.length; const Q = { n, t0: base, states: docs.map((d) => d.id), ops, spud: Uint8Array.from(docs.map((d) => (PERMIT_SOURCES.find((x) => x.id === d.id) || {}).spud ? 1 : 0)),
    day: new Int32Array(n), s: new Uint8Array(n), lat: new Float32Array(n), lon: new Float32Array(n), op: new Int16Array(n), tvd: new Uint16Array(n), last: new Int32Array(docs.length).fill(-1) };
  rows.forEach((r, i) => { Q.day[i] = r[0]; Q.s[i] = r[1]; Q.lat[i] = r[2] / 1e4; Q.lon[i] = r[3] / 1e4; Q.op[i] = r[4]; Q.tvd[i] = r[5]; if (r[0] > Q.last[r[1]]) Q.last[r[1]] = r[0]; });
  return Q; // last[k]: the newest day state k has a point on, or -1
}
export const permitState = (Q, i) => Q.states[Q.s[i]];
export const permitOperator = (Q, i) => (Q.op[i] >= 0 ? Q.ops[Q.op[i]] : null);
export const permitWord = (Q, i) => (Q.spud[Q.s[i]] ? 'Well spudded' : 'Permit approved');
// the first index whose day is at least d
export function firstPermitAtOrAfter(Q, d) {
  let lo = 0; let hi = Q.n;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (Q.day[mid] < d) lo = mid + 1; else hi = mid; }
  return lo;
}
// the permits (indexes) of one day, for one state when `state` is given
export function permitsOfDay(Q, d, state = null) {
  const si = state ? Q.states.indexOf(state) : -1; const out = [];
  if (state && si < 0) return out; // a state with no permit source has none, not "every one"
  for (let i = firstPermitAtOrAfter(Q, d); i < Q.n && Q.day[i] === d; i++) if (si < 0 || Q.s[i] === si) out.push(i);
  return out;
}
// permits and spuds per state over [d0, d1]: [{ id, n, spud }] ranked, only states with a point in the range
export function permitsPerState(Q, d0, d1) {
  const n = new Array(Q.states.length).fill(0);
  for (let i = firstPermitAtOrAfter(Q, d0); i < Q.n && Q.day[i] <= d1; i++) n[Q.s[i]]++;
  return Q.states.map((id, k) => ({ id, n: n[k], spud: Q.spud[k] === 1 })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n);
}

// where a day sits on the series' month axis, in months from the first month's first day: Jan 1, 2011 is 0, Feb 1, 2011 is 1, Jan 16, 2011 is about 0.5. The Daily report's overview strip
// uses it to mark the days of its chart on a bar a month. The day is an ISO date; a day before the series gives a negative number and one after it a number past the last month.
export function monthPos(doc, iso) {
  const [y0, m0] = doc.months[0].split('-').map(Number); const [y, m, d] = iso.split('-').map(Number);
  return (y - y0) * 12 + (m - m0) + (d - 1) / new Date(Date.UTC(y, m, 0)).getUTCDate();
}
// a state that has had a well since the series began, even if none in the last year (the Daily report can show it for an older day)
export const drilled = (s) => s.new.some((v) => v > 0);
// ------------------------------------------------------------------------------------------------ fractured wells found, and the state agencies' oil well permits, day by day
// The states whose daily reports are kept (a state agency's report of the permits it approved): the oil side of the Daily report.
export const OIL_STATES = ['TX', 'OK', 'NM'];
// arrivalRows(arr, reports, n): the last n days, newest first, of the two things side by side, never added: `fractured`, the wells FracFocus's download added that day (arrivals.json: null for a day before
// the comparison began, never a zero for a day that was not compared), and `oil`, each state's new-drill permits in the report it published that day ([id, count, the day they were approved]).
// `both` is the wells that are in both (Texas, matched by API number), or null when the day was not compared. `reports` maps a state to its per-day index (daily/index.json and the like), or null.
export function arrivalRows(arr, reports, n = 14) {
  const found = new Map(((arr && arr.days) || []).map((d) => [d.day, d]));
  const oil = new Map();
  for (const id of OIL_STATES) {
    for (const r of ((reports && reports[id]) || {}).days || []) {
      if (r.s !== 'ok' || typeof r.pn !== 'number') continue;
      if (!oil.has(r.d)) oil.set(r.d, []);
      oil.get(r.d).push([id, r.pn, r.dd || null]);
    }
  }
  const days = [...new Set([...found.keys(), ...oil.keys()])].sort().reverse().slice(0, n);
  return days.map((day) => {
    const e = found.get(day); const compared = !!(arr && arr.since && day >= arr.since);
    const o = (oil.get(day) || []).sort((a, b) => OIL_STATES.indexOf(a[0]) - OIL_STATES.indexOf(b[0]));
    const tx = e ? e.states.find((x) => x[0] === 'TX') : null;
    return { day, fractured: compared ? (e ? e.found : 0) : null, byState: e ? e.states.map((x) => ({ id: x[0], n: x[1], carried: x[2] })) : [], oil: o, oilTotal: o.length ? o.reduce((t, x) => t + x[1], 0) : null, both: compared ? (tx ? tx[2] : 0) : null };
  });
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
