// The Overview's numbers for the states shown. Pure functions (no DOM, no fetch), so they run under Node as well: they merge Texas's
// and Oklahoma's files into the shapes the Overview already draws, and a figure only ever covers the states that have it.
//
// Texas's files are keyed by plain county codes and P-5 operator numbers; Oklahoma's by codes that repeat Texas's and by the OCC's own
// operator numbers, so Oklahoma's counties are keyed OK:001 and its operators OK:123 (states.js).
import { countyKey, stateIndex, POINT_BLOCK } from './states.js';

const sum = (a, from = 0, to = a.length) => { let s = 0; for (let i = from; i < to; i++) s += a[i] || 0; return s; };

// docs is { TX: file, OK: file ... }: one kind of file for each state. A state with no file (not built, or not loaded) is left out, and the
// figures say so by covering fewer states rather than counting it as zero.
const usable = (states, docs) => states.filter((id) => docs && docs[id]).map((id) => ({ id, f: docs[id] }));

// Monthly new-drill permits for the states shown: one series on the months every state shown has (they end on the same last
// complete month; if one file lags, the series stops where all have data rather than counting the missing month as zero).
export function permitSeries(states, docs) {
  const use = usable(states, docs);
  if (!use.length) return null;
  const maps = use.map((u) => new Map(u.f.months.map((m, i) => [m, u.f.permits[i]])));
  const months = use[0].f.months.filter((m) => maps.every((mp) => mp.has(m)));
  const by = {};
  use.forEach((u, k) => { by[u.id] = months.map((m) => maps[k].get(m)); });
  return { months, permits: months.map((_, i) => use.reduce((t, u) => t + by[u.id][i], 0)), by, ids: use.map((u) => u.id) };
}
// last 12 and the 12 before, in complete months
export function permitTotals(sp) {
  const n = sp.permits.length;
  return { last: sum(sp.permits, n - 12, n), prior: sum(sp.permits, n - 24, n - 12), from: sp.months[n - 12], to: sp.months[n - 1] };
}

// County permit counts for the states shown, every state but Texas keyed OK:001 and its operators OK:123. asOf is the latest file's last day.
export function countyPermits(states, docs) {
  const use = usable(states, docs);
  if (!use.length) return null;
  const counties = {};
  for (const u of use) {
    for (const [f, c] of Object.entries(u.f.counties)) counties[countyKey(u.id, f)] = u.id === 'TX' ? c : { ...c, ops: c.ops.map(([n, num, k]) => [n, u.id + ':' + num, k]) };
  }
  return { asOf: use.map((u) => u.f.asOf).sort().pop(), months: use[0].f.months, counties, ids: use.map((u) => u.id) };
}

// Another state's operators as the objects the Texas table gives (toObjects), numbers and county keyed by state.
export function stateOperatorRows(id, doc) {
  if (!doc) return [];
  return doc.rows.map((row, i) => {
    const o = { _i: i, st: id };
    doc.cols.forEach((c, j) => { o[c] = row[j]; });
    o.rawNum = o.num; o.num = id + ':' + o.num; o.county = o.county ? countyKey(id, o.county) : '';
    return o;
  });
}
// Every operator of the states shown: Texas's rows (a table with cols and rows) and the others', each tagged with its state
export function operatorRows(states, txTable, docs) {
  const out = [];
  for (const id of states) {
    if (id === 'TX') {
      if (txTable) txTable.rows.forEach((row, i) => { const o = { _i: i, st: 'TX' }; txTable.cols.forEach((c, j) => { o[c] = row[j]; }); out.push(o); });
    } else out.push(...stateOperatorRows(id, docs && docs[id]));
  }
  return out;
}
// A and B are the operators with a new-well permit in the last 12 months
export const drillingNow = (rows) => rows.filter((r) => r.band === 'A' || r.band === 'B').length;
// the first n of the rows by a number, biggest first; ties keep the file's order
export const topBy = (rows, key, n) => rows.slice().sort((a, b) => (b[key] - a[key]) || (a._i - b._i)).slice(0, n);

// Oklahoma's active wells: the OCC's well inventory, counted on the days a report was captured live; the newest such day
export function activeWells(index) {
  if (!index || !index.days) return null;
  for (let i = index.days.length - 1; i >= 0; i--) {
    const d = index.days[i];
    if (d.k === 'live' && d.w) return { n: d.w, day: d.d };
  }
  return null;
}
// Oklahoma operators new to drilling in the last 24 months (a first drilling permit, ever)
export const newToDrilling = (rows) => rows.filter((r) => r.newDrill === 1).length;

// County key and a label: "Midland" alone, "Midland, TX" when both states are shown
export const countyLabel = (name, id, multi) => (multi ? name + ', ' + id : name);

const DAY = 864e5;
// The states' permit files (the Texas file's shape: permits.json, permits-ok.json ...) as one: parts is [{ id, pm }]. A point gets a seventh
// value, whether it is recent (in the last 365 days of its own state's file), because the files end on different days.
export function mergePoints(parts) {
  if (parts.length === 1 && parts[0].id === 'TX') return parts[0].pm;
  if (new Set(parts.map((q) => q.pm.t0)).size > 1) throw new Error('the permit files count days from different starts');
  const t0 = Date.parse(parts[0].pm.t0 + 'T00:00:00Z');
  const out = { asOf: parts.map((q) => q.pm.asOf).sort().pop(), t0: parts[0].pm.t0, ops: [], opNums: [], cols: parts[0].pm.cols, pts: [], coverageBy: {} };
  for (const { id, pm } of parts) {
    const off = out.ops.length; const base = stateIndex(id) * POINT_BLOCK;
    const cut = Math.round((Date.parse(pm.asOf + 'T00:00:00Z') - t0) / DAY) - 365;
    out.ops.push(...pm.ops); out.opNums.push(...pm.opNums.map((n) => (id === 'TX' ? n : id + ':' + n))); out.coverageBy[id] = pm.coverage;
    for (const p of pm.pts) out.pts.push([p[0], p[1], p[2] < 0 ? -1 : p[2] + off, p[3], p[4], p[5] + base, p[3] >= cut ? 1 : 0]);
  }
  if (parts.length === 1) out.coverage = parts[0].pm.coverage;
  return out;
}
