// Merging the two states' Daily reports into one dataset. Pure functions: no DOM, no fetch, so they run under Node as well.
//
// The two reports are built by separate nightly jobs (Texas: d7_daily.py, Oklahoma: d8_ok_daily.py) and either can be missing
// for a day (the workflow lets the Oklahoma capture fail without stopping Texas), so nothing here assumes both are there.
// County FIPS codes repeat across the two states and so do 8 county names, so every county key carries its state (ck).
import { addDays, isWeekend } from './daily-dates.js';

export const STATES = [
  { id: 'TX', name: 'Texas', dir: 'daily', agency: 'Railroad Commission' },
  { id: 'OK', name: 'Oklahoma', dir: 'daily-ok', agency: 'Oklahoma Corporation Commission' },
];
export const stateOf = (id) => STATES.find((s) => s.id === id);
// ?st=tx or ?st=ok narrows the report to one state; anything else is both
export const parseStates = (v) => { const s = String(v || '').toUpperCase(); return s === 'TX' || s === 'OK' ? [s] : STATES.map((x) => x.id); };
export const stateParam = (active) => (active.length === STATES.length ? null : active[0].toLowerCase());
export const ck = (id, fips) => id + ':' + fips; // county key

const ZERO = Object.freeze({ n: 0, total: 0, h: 0 });

// Marks each report day whose permit day is new (Saturday to Monday reports all show Friday, so only one of them counts) and
// adds the total size of the three image packs (Texas rows only; Oklahoma rows have none, which gives null).
export function prepIndex(idx) {
  idx.days.forEach((r, i) => {
    r.pFresh = i === 0 || r.dd !== idx.days[i - 1].dd;
    r.vol = [r.w1, r.ds, r.cm].some((v) => v != null) ? (r.w1 || 0) + (r.ds || 0) + (r.cm || 0) : null;
  });
  return idx;
}

// One list of report days for the states shown. A day is there when any of them has a report for it. `r` holds each state's
// index row, `parts` the new-drill permits that day's report adds (0 when its permit day is the previous report's), `partial`
// says a state shown has no report that day, and `live` that every report there was captured live.
export function mergeDays(idxs, active) {
  const by = new Map();
  for (const id of active) {
    const idx = idxs[id];
    if (!idx) continue;
    for (const r of idx.days) {
      let e = by.get(r.d);
      if (!e) by.set(r.d, e = { d: r.d, r: {} });
      e.r[id] = r;
    }
  }
  const days = [...by.values()].sort((a, b) => (a.d < b.d ? -1 : 1));
  for (const e of days) {
    const have = active.filter((id) => e.r[id]);
    e.live = have.every((id) => e.r[id].k === 'live');
    e.partial = have.length < active.length;
    e.parts = {};
    for (const id of active) e.parts[id] = e.r[id] && e.r[id].pFresh ? e.r[id].pn || 0 : 0;
    e.fresh = have.some((id) => e.r[id].pFresh);
    e.total = active.reduce((a, id) => a + e.parts[id], 0);
  }
  return days;
}

// Permits by the day they were issued, for one state: get(day) is { n: new-drill, total: all kinds, h: horizontal (Texas) or
// planned 12,000 ft or deeper (Oklahoma) }, a zero for a day inside the state's window with none (a weekend or a holiday), and
// null for a day outside it, which is "no data", not "no permits".
export function permitSeries(id, idx, texas) {
  const m = new Map();
  let lo = null; let hi = null;
  if (id === 'TX' && texas && texas.days && texas.days.length) {
    texas.days.forEach((d, i) => m.set(d, { n: texas.newDrill[i], total: texas.total[i], h: texas.horizontal[i] }));
    lo = texas.days[0]; hi = texas.days[texas.days.length - 1];
  } else if (idx) {
    idx.days.forEach((r) => { if (r.dd && !m.has(r.dd)) m.set(r.dd, { n: r.pn || 0, total: r.p || 0, h: r.pd || 0 }); });
    const keys = [...m.keys()].sort();
    if (keys.length) { lo = keys[0]; hi = keys[keys.length - 1]; }
  }
  return { id, lo, hi, get: (d) => (lo == null || d < lo || d > hi ? null : m.get(d) || ZERO) };
}

const had = (v) => !!v && (v.n > 0 || v.total > 0);

// The last `count` business days up to and including `until`, per state: n[id][i] and h[id][i] (null where a state has no data
// that day), and total[i], the sum of what there is. A weekend day is in only when some state had permits on it (Texas has
// issued permits on a Sunday); a weekday with none, a holiday, is in as an empty day.
export function bizSeries(ss, until, count) {
  const out = { days: [], ids: ss.map((s) => s.id), n: {}, h: {}, total: [] };
  out.ids.forEach((id) => { out.n[id] = []; out.h[id] = []; });
  const starts = ss.map((s) => s.lo).filter(Boolean).sort();
  if (!starts.length) return out;
  for (let d = until; d >= starts[0] && out.days.length < count; d = addDays(d, -1)) {
    const vs = ss.map((s) => s.get(d));
    if (!vs.some(Boolean) || (isWeekend(d) && !vs.some(had))) continue;
    out.days.unshift(d);
    ss.forEach((s, k) => { out.n[s.id].unshift(vs[k] ? vs[k].n : null); out.h[s.id].unshift(vs[k] ? vs[k].h : null); });
    out.total.unshift(vs.reduce((a, v) => a + (v ? v.n : 0), 0));
  }
  return out;
}

// Average new-drill permits over the `n` business days before `day`, leaving out holidays (a weekday on which no state had a
// permit of any kind) and days some state has no data for. Null with fewer than 5 days to average.
export function avgBefore(ss, day, n = 20) {
  const starts = ss.map((s) => s.lo).filter(Boolean).sort();
  if (!starts.length) return null;
  const v = [];
  for (let d = addDays(day, -1); d >= starts[starts.length - 1] && v.length < n; d = addDays(d, -1)) {
    const vs = ss.map((s) => s.get(d));
    if (vs.some((x) => !x)) continue;
    const total = vs.reduce((a, x) => a + x.total, 0);
    if (!total || (isWeekend(d) && !vs.some(had))) continue;
    v.push(vs.reduce((a, x) => a + x.n, 0));
  }
  return v.length >= 5 ? v.reduce((a, x) => a + x, 0) / v.length : null;
}

// New-drill permits so far this month, and by the same date last month (null when the archive does not reach back to the first
// days of last month; a month can start on a weekend, so a few days of slack).
export function monthToDate(ss, day) {
  if (!ss.length || ss.some((s) => !s.lo)) return null;
  const ym = day.slice(0, 7); const dd = day.slice(8);
  const prevYm = addDays(ym + '-01', -1).slice(0, 7);
  let a = 0; let b = 0;
  for (const s of ss) {
    for (let d = s.lo; d <= s.hi; d = addDays(d, 1)) {
      const v = s.get(d);
      if (d.slice(0, 7) === ym && d <= day) a += v.n;
      if (d.slice(0, 7) === prevYm && d.slice(8) <= dd) b += v.n;
    }
  }
  return { a, b: ss.every((s) => s.lo <= addDays(prevYm + '-01', 3)) ? b : null };
}

// Ranked lists from both reports as one: parts is [{ id, rows: [[key, name, n], ...] }]. Each state's list holds its own top
// rows, so the top of the merged list is exact as long as `limit` is no larger than the shortest list that was cut.
export function mergeRank(parts, limit = Infinity) {
  const out = [];
  for (const { id, rows } of parts) for (const [key, name, n] of rows || []) out.push({ id, key, name, n });
  out.sort((a, b) => b.n - a.n || (a.name || '').localeCompare(b.name || '') || (a.id < b.id ? -1 : 1));
  return out.slice(0, limit);
}

// Both states' county outlines as one FeatureCollection, each county keyed by state + FIPS (see ck) and tagged with its state.
export function mergedCounties(parts) {
  const features = [];
  for (const { id, gj } of parts) {
    for (const f of gj.features) features.push({ type: 'Feature', properties: { f: ck(id, f.properties.f), n: f.properties.n, s: id }, geometry: f.geometry });
  }
  return { type: 'FeatureCollection', features };
}

// Summed over the states that have the number
export const sumOf = (xs) => xs.reduce((a, x) => a + (x || 0), 0);
