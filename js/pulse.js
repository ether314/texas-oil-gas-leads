// Market ticker and market pulse. One registry of normalized series (times in ms) feeds the chips and the grouped charts.
// Every series keeps its own as-of date: sources publish on different schedules and nothing here implies they are all current.
import { $, el, fmt, compactFmt, monthLabel, fmtDate, monthMs, dayMs, lastIdx, nearest, loadOpt, reduced } from './util.js';
import { delta, fluidSpark, seriesGroup, seriesTables, dayLabelT } from './charts.js';
import { icon } from './icons.js';
import { segmented } from './ui.js';
import { hideTip } from './tip.js';
import { permitSeries } from './overview-data.js';
import { otherStates, stateOf } from './states.js';

// Texas's own files, and each other state's permit series and (where it has one) the EIA's crude oil production for it
const FILES = ['series-permits', 'series-markets', 'series-rigs', 'series-jobs', 'series-tax', 'series-outlook', 'series-production',
  ...otherStates.flatMap((s) => [s.files.series, s.files.crude].filter(Boolean))];
const stColor = (id) => 'var(--st-' + id.toLowerCase() + ')';
const stName = (id) => stateOf(id).name;
export async function loadMarketData() {
  const got = await Promise.all(FILES.map((n) => loadOpt(n)));
  return Object.fromEntries(FILES.map((n, i) => [n, got[i]]));
}

const WEEK = 864e5 * 6;
const usd = (d) => (v) => (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(d);
const usdM = (v) => (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(1) + 'M';
const tickK = (v) => (v >= 1000 ? v / 1000 + 'K' : String(v));
const ymOf = (t) => { const d = new Date(t); return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'); };
const monthT = (t) => monthLabel(ymOf(t));
const mser = (months, values) => ({ t: months.map(monthMs), v: values });
const pctText = (a, b) => (b ? (a >= b ? '+' : '−') + Math.abs(((a - b) / b) * 100).toFixed(1) + '%' : '');

// the sample a year before index i, for the "vs" caption and the change
function yoyInfo(ser, i) {
  if (i < 1 || ser.v[i] == null) return null;
  const want = ser.t[i] - 365 * 864e5; const j = nearest(ser.t, want, i - 1);
  if (j < 0 || ser.v[j] == null || ser.v[j] === 0 || Math.abs(ser.t[j] - want) > 20 * 864e5) return null;
  return { f: ser.v[i] / ser.v[j] - 1, j };
}

/* ---------- registry ---------- */
function registry(raw, states = ['TX']) {
  const R = { states };
  const T = states.includes('TX');
  // Texas's rigs, jobs, taxes and production series are Texas's: with Oklahoma alone they are not drawn (Oklahoma has none of them)
  const sm = raw['series-markets']; const rg = T && raw['series-rigs'];
  const jb = T && raw['series-jobs']; const tx = T && raw['series-tax']; const ol = raw['series-outlook']; const pr = T && raw['series-production'];
  const sp = permitSeries(states, { TX: raw['series-permits'], ...Object.fromEntries(otherStates.map((q) => [q.id, raw[q.files.series]])) });
  if (sp) {
    R.permits = mser(sp.months, sp.permits);
    R.permitsBy = sp.ids.length > 1 ? Object.fromEntries(sp.ids.map((id) => [id, mser(sp.months, sp.by[id])])) : null;
    R.permitIds = sp.ids;
  }
  if (sm) {
    if (sm.wti) R.wti = mser(sm.months, sm.wti);
    if (sm.henryHub) R.hh = mser(sm.months, sm.henryHub);
    if (T && sm.txCrude) R.eia = mser(sm.months, sm.txCrude.map((v) => (v == null ? null : v * 1000)));
  }
  // the EIA's monthly crude oil production for each other state shown (it gives thousand barrels; the file's key is okCrude, nmCrude ...)
  R.crude = {};
  for (const q of otherStates) {
    const f = states.includes(q.id) && q.files.crude && raw[q.files.crude]; const v = f && f[q.id.toLowerCase() + 'Crude'];
    if (v) R.crude[q.id] = mser(f.months, v.map((x) => (x == null ? null : x * 1000)));
  }
  if (rg) {
    const t = rg.weeks.map(dayMs);
    R.rigTx = { t, v: rg.txTotal }; R.rigPermian = { t, v: rg.permianTx || rg.permian }; R.rigPermianAll = rg.permian ? { t, v: rg.permian } : null;
    R.rigAsOf = rg.through || rg.weeks[rg.weeks.length - 1];
    R.rigEF = rg.eagleFord ? { t, v: rg.eagleFord } : null; R.rigHay = rg.haynesville ? { t, v: rg.haynesville } : null; R.rigBarnett = rg.barnett ? { t, v: rg.barnett } : null;
  }
  if (jb) {
    R.jobsOil = mser(jb.months, jb.oilGas); R.jobsSup = mser(jb.months, jb.support);
    R.jobsAll = mser(jb.months, jb.months.map((_, i) => (jb.oilGas[i] != null && jb.support[i] != null ? jb.oilGas[i] + jb.support[i] : null)));
    R.prelim = new Set((jb.prelim || []).map(monthMs)); PRELIM = R.prelim;
  }
  if (tx) { R.taxOil = mser(tx.months, tx.oilTax); R.taxGas = mser(tx.months, tx.gasTax); R.taxAll = mser(tx.months, tx.months.map((_, i) => tx.oilTax[i] + tx.gasTax[i])); }
  if (pr && pr.months && pr.oil) {
    R.prodOil = mser(pr.months, pr.oil); R.prodGas = pr.gas ? mser(pr.months, pr.gas) : null;
    R.prodMeta = { through: pr.completeThrough || pr.months[pr.months.length - 1], newest: pr.newest || null, partial: pr.partial && pr.partial.months ? pr.partial.months : [] };
  }
  if (ol) {
    const k = ol.months.findIndex((m) => m > ol.actualThrough);
    if (k > 0) {
      const sl = (a) => ({ t: ol.months.slice(k).map(monthMs), v: a.slice(k) });
      R.fcWti = ol.wti ? sl(ol.wti) : null; R.fcHh = ol.henryHub ? sl(ol.henryHub) : null;
      R.fcMeta = { issued: ol.issued, through: ol.actualThrough, end: ol.months[ol.months.length - 1], first: ol.months[k] };
    }
  }
  return R;
}

/* ---------- ticker ---------- */
function chipDefs(R, raw) {
  const out = [];
  const add = (c) => { if (c.ser && lastIdx(c.ser.v) >= 0) out.push({ ...c, i: lastIdx(c.ser.v) }); };
  add({ id: 'wti', group: 'prices', icon: 'drop', color: 'var(--s1)', label: 'WTI crude', ser: R.wti, fmt: usd(2), unit: 'per barrel', src: 'EIA' });
  add({ id: 'hh', group: 'prices', icon: 'flame', color: 'var(--s1)', label: 'Henry Hub gas', ser: R.hh, fmt: usd(2), unit: 'per MMBtu', src: 'EIA' });
  if (R.prodOil) add({ id: 'crude', group: 'production', icon: 'pipe', color: 'var(--s3)', label: 'Texas crude', ser: R.prodOil, fmt: (v) => compactFmt.format(v), unit: 'barrels a month', src: 'RRC',
    note: R.eia ? 'EIA estimates ' + compactFmt.format(R.eia.v[lastIdx(R.eia.v)]) + ' for ' + monthT(R.eia.t[lastIdx(R.eia.v)]) : '' });
  else add({ id: 'crude', group: 'production', icon: 'pipe', color: 'var(--s3)', label: 'Texas crude', ser: R.eia, fmt: (v) => compactFmt.format(v), unit: 'barrels a month', src: 'EIA est.' });
  add({ id: 'rig', group: 'activity', icon: 'rig', color: 'var(--s2)', label: 'Texas rigs', ser: R.rigTx, fmt: (v) => fmt.format(v), unit: 'rigs', src: 'Baker Hughes', weekly: true });
  add({
    id: 'prm', group: 'activity', icon: 'rig', color: 'var(--s2)', label: 'Permian rigs', ser: R.rigPermian, fmt: (v) => fmt.format(v), unit: 'rigs in Texas counties', src: 'Baker Hughes', weekly: true,
    note: R.rigPermianAll ? fmt.format(R.rigPermianAll.v[lastIdx(R.rigPermianAll.v)]) + ' basin-wide, incl. New Mexico' : '',
  });
  const ids = R.permitIds || [];
  const AGENCY = { TX: 'RRC', OK: 'OCC', NM: 'OCD' };
  add({ id: 'permits', group: 'activity', icon: 'pin', color: ids.length === 1 ? stColor(ids[0]) : 'var(--st-tx)', label: 'New permits', ser: R.permits, fmt: (v) => fmt.format(v),
    unit: 'new-drill, in the month' + (ids.length > 1 ? ', ' + ids.map(stName).join(' and ') : ''), src: ids.map((id) => AGENCY[id]).join(' and ') });
  for (const [id, ser] of Object.entries(R.crude)) add({ id: id.toLowerCase() + 'crude', group: 'production', icon: 'pipe', color: stColor(id), label: stName(id) + ' crude', ser, fmt: (v) => compactFmt.format(v), unit: 'barrels a month', src: 'EIA est.' });
  add({
    id: 'jobs', group: 'jobs', icon: 'jobs', color: 'var(--s7)', label: 'Oil & gas jobs', ser: R.jobsAll, fmt: (v) => compactFmt.format(v * 1000), unit: 'jobs', src: 'BLS',
    note: R.jobsOil ? compactFmt.format(R.jobsOil.v[lastIdx(R.jobsOil.v)] * 1000) + ' extraction, ' + compactFmt.format(R.jobsSup.v[lastIdx(R.jobsSup.v)] * 1000) + ' field services' : '', prelim: true,
  });
  add({ id: 'tax', group: 'taxes', icon: 'dollar', color: 'var(--s1)', label: 'Production tax', ser: R.taxAll, fmt: (v) => '$' + Math.round(v) + 'M', unit: 'oil and gas, a month', src: 'Comptroller' });
  return out;
}

function chipNode(c, groupLabel, onPick) {
  const info = yoyInfo(c.ser, c.i);
  const when = (t) => (c.weekly ? fmtDate(new Date(t).toISOString().slice(0, 10)) : monthT(t));
  const asof = when(c.ser.t[c.i]); const cmp = info ? 'vs ' + monthT(c.ser.t[info.j]) : '';
  const N = c.weekly ? 105 : 25;
  const vals = c.ser.v.slice(Math.max(0, c.i - N + 1), c.i + 1).filter((v) => v != null);
  const first = vals.length > 1 ? vals : [0, 0];
  const dir = info ? (Math.round(Math.abs(info.f) * 100) === 0 ? 'unchanged' : info.f > 0 ? 'up ' + Math.round(info.f * 100) + '%' : 'down ' + Math.round(-info.f * 100) + '%') : 'no year-earlier comparison';
  const prelim = c.prelim && PRELIM.has(c.ser.t[c.i]);
  const btn = el('button', {
    type: 'button', class: 'tchip', 'data-group': c.group,
    'aria-label': c.label + ': ' + c.fmt(c.ser.v[c.i]) + ' ' + c.unit + ', as of ' + asof + (prelim ? ' (first print)' : '') + ', ' + dir + (cmp ? ' ' + cmp : '') + (c.note ? '. ' + c.note : '') + '. Source: ' + c.src + '. Show the ' + groupLabel + ' chart.',
    onclick: () => onPick(c.group),
  }, el('span', { class: 'tchip-in' },
    el('span', { class: 'tchip-top' }, icon(c.icon, 15), el('span', { text: c.label })),
    el('span', { class: 'tchip-val' }, el('strong', { text: c.fmt(c.ser.v[c.i]) })),
    el('span', { class: 'tchip-delta' }, delta(info ? info.f : null), cmp ? el('span', { text: cmp }) : null),
    el('span', { class: 'tchip-spark' }, fluidSpark(first, { color: c.color })),
    el('span', { class: 'tchip-foot' },
      el('span', { class: 'tchip-asof' }, icon('calendar', 13), el('span', { text: asof + ' · ' + c.src + (prelim ? ' · prelim.' : '') })),
      el('span', { class: 'tchip-unit', text: c.unit + (c.note ? ' · ' + c.note : '') }))));
  btn.style.setProperty('--c', c.color);
  return btn;
}
let PRELIM = new Set();

/* ---------- groups ---------- */
function makeGroups(R, raw) {
  const groups = [];
  const S = (o) => o;
  const fc = R.fcMeta;

  if (R.wti || R.hh) {
    const panels = [];
    const mk = (id, title, ic, hist, fcSer, name, fmtVal, fmtTick, fmtEnd, events) => hist && panels.push({
      id, title, icon: ic, color: 'var(--s1)', zero: true, fmtTick, events,
      series: [S({ id, name, unit: name === 'WTI' ? 'per barrel' : 'per MMBtu', color: 'var(--s1)', ...hist, fmtVal, fmtEnd }),
        ...(fcSer ? [S({ id: id + 'fc', name: name + ', EIA forecast', unit: name === 'WTI' ? 'per barrel' : 'per MMBtu', color: 'var(--s1)', fc: true, ...fcSer, fmtVal, fmtEnd })] : [])],
    });
    mk('wti', 'WTI crude oil', 'drop', R.wti, R.fcWti, 'WTI', usd(2), (v) => '$' + v, usd(0), [{ t: monthMs('2020-04'), label: 'COVID-19' }, { t: monthMs('2022-06'), label: '2022 price spike' }]);
    mk('hh', 'Henry Hub natural gas', 'flame', R.hh, R.fcHh, 'Henry Hub', usd(2), (v) => '$' + v, usd(2), []);
    const end = fc ? monthMs(fc.end) : Math.max(...panels.map((p) => p.series[0].t[p.series[0].t.length - 1]));
    groups.push({
      id: 'prices', label: 'Prices', icon: 'chart',
      spec: () => ({ label: 'Oil and gas prices', domain: [monthMs('2019-01'), end], zone: fc ? { t: monthMs(fc.first), label: 'EIA forecast' } : null, panels }),
      notes: ['WTI and Henry Hub are monthly averages of daily spot prices (EIA), through ' + monthLabel((R.wti || R.hh) && ymOf((R.wti || R.hh).t[lastIdx((R.wti || R.hh).v)])) + '.'
        + (fc ? ' The shaded zone is the EIA Short-Term Energy Outlook, ' + monthLabel(fc.issued) + ' edition: a forecast to ' + monthLabel(fc.end) + ', not data.' : '')],
    });
  }

  if (R.permits || R.rigTx) {
    const panels = [];
    const ids = R.permitIds || []; const one = ids.length === 1 ? ids[0] : null;
    if (R.permits) panels.push({
      id: 'permits', title: 'New-drill permits a month' + (one && one !== 'TX' ? ', ' + stName(one) : ''), icon: 'pin', color: one ? stColor(one) : 'var(--st-tx)', zero: true, fmtTick: tickK, events: [{ t: monthMs('2020-04'), label: 'COVID-19' }],
      // several states: one line each (the sum is mostly Texas), so every state's own course shows
      series: R.permitsBy ? ids.map((id) => S({ id: 'permits' + id, name: stName(id), unit: 'a month', color: stColor(id), ...R.permitsBy[id], fmtVal: (v) => fmt.format(v) }))
        : [S({ id: 'permits', name: 'Permits', unit: 'a month', color: one ? stColor(one) : 'var(--st-tx)', ...R.permits, fmtVal: (v) => fmt.format(v) })],
    });
    if (R.rigTx) {
      const series = [S({ id: 'rigTx', name: 'Texas', unit: 'rigs', color: 'var(--s2)', ...R.rigTx, fmtVal: (v) => fmt.format(v), dateFmt: dayLabelT, tol: WEEK })];
      if (R.rigPermian) series.push(S({ id: 'rigPm', name: 'Permian, Texas counties', unit: 'rigs', color: 'var(--ink-2)', ...R.rigPermian, fmtVal: (v) => fmt.format(v), dateFmt: dayLabelT, tol: WEEK }));
      panels.push({ id: 'rigs', title: 'Rigs drilling, weekly', icon: 'rig', color: 'var(--s2)', zero: true, fmtTick: String, series });
    }
    const ends = panels.map((p) => Math.max(...p.series.map((s) => s.t[s.t.length - 1])));
    groups.push({
      id: 'activity', label: 'Activity', icon: 'rig',
      spec: () => ({ label: 'Drilling activity', domain: [monthMs('2019-01'), Math.max(...ends)], panels }),
      notes: [(R.rigTx ? 'Rig counts are Baker Hughes weekly counts through ' + fmtDate(R.rigAsOf) + ' (the workbooks come from Internet Archive copies of Baker Hughes’ public files). "Permian, Texas counties" is the Texas part of Baker Hughes’ Permian basin; the basin-wide count also includes southeastern New Mexico.' : '')
        + (R.permits ? (ids.includes('TX') ? ' Texas permits are Railroad Commission new-drill permits by issue month.' : '')
          + (ids.includes('OK') ? ' Oklahoma permits are Oklahoma Corporation Commission new-drill permits by approval month, one per well and day.' : '')
          + (ids.includes('NM') ? ' New Mexico’s are wells added to the Oil Conservation Division’s well layer when an application to drill is approved, by month added.' : '') : '')],
    });
  }

  if (R.prodOil || R.eia || Object.keys(R.crude).length) {
    const panels = []; let cross = '';
    const oilSer = [];
    const unitO = 'barrels a month';
    if (R.prodOil || R.eia) {
      if (R.prodOil) {
        oilSer.push(S({ id: 'rrcO', name: 'RRC reports', unit: unitO, color: 'var(--s3)', ...R.prodOil, fmtVal: (v) => compactFmt.format(v), fmtEnd: (v) => compactFmt.format(v) }));
        if (R.eia) oilSer.push(S({ id: 'eia', name: 'EIA estimate, newer months', unit: unitO, color: 'var(--ink-2)', ref: true, after: true, ...R.eia, fmtVal: (v) => compactFmt.format(v) }));
        // cross-check: the newest month both sources report
        if (R.eia) {
          for (let i = R.eia.v.length - 1; i >= 0; i--) {
            const j = R.prodOil.t.indexOf(R.eia.t[i]);
            if (R.eia.v[i] != null && j >= 0 && R.prodOil.v[j] != null) { cross = monthT(R.eia.t[i]) + ': RRC reports ' + compactFmt.format(R.prodOil.v[j]) + ' barrels, EIA estimates ' + compactFmt.format(R.eia.v[i]) + ' (' + pctText(R.prodOil.v[j], R.eia.v[i]) + ').'; break; }
          }
        }
      } else oilSer.push(S({ id: 'eia', name: 'EIA estimate', unit: unitO, color: 'var(--s3)', ...R.eia, fmtVal: (v) => compactFmt.format(v), fmtEnd: (v) => compactFmt.format(v), prelim: null }));
      panels.push({
        id: 'oil', title: R.prodOil ? 'Texas crude oil and condensate' : 'Texas crude oil (EIA)', icon: 'drop', color: 'var(--s3)', zero: false,
        fmtTick: (v) => compactFmt.format(v), series: oilSer,
      });
      if (R.prodGas) panels.push({
        id: 'gas', title: 'Texas natural gas', icon: 'flame', color: 'var(--s3)', zero: false, fmtTick: (v) => String(Math.round(v / 1e6)),
        series: [S({ id: 'gas', name: 'RRC reports', unit: 'Bcf a month (gas well plus casinghead)', color: 'var(--s3)', ...R.prodGas, fmtVal: (v) => fmt.format(Math.round(v / 1e6)) + ' Bcf', fmtEnd: (v) => fmt.format(Math.round(v / 1e6)) })],
      });
    }
    for (const [id, ser] of Object.entries(R.crude)) panels.push({
      id: id.toLowerCase() + 'Oil', title: stName(id) + ' crude oil (EIA)', icon: 'drop', color: stColor(id), zero: false, fmtTick: (v) => compactFmt.format(v),
      series: [S({ id: id.toLowerCase() + 'O', name: 'EIA estimate', unit: unitO, color: stColor(id), ...ser, fmtVal: (v) => compactFmt.format(v), fmtEnd: (v) => compactFmt.format(v) })],
    });
    const ends = panels.map((p) => Math.max(...p.series.map((s) => s.t[s.t.length - 1])));
    const first = Math.min(...panels.flatMap((p) => p.series.map((s) => s.t[0])));
    groups.push({
      id: 'production', label: 'Production', icon: 'drop',
      spec: () => ({ label: R.states.map(stName).join(' and ') + ' production', domain: [first, Math.max(...ends)], panels }),
      notes: [(R.prodOil || R.eia ? (R.prodOil ? 'Statewide totals from the Railroad Commission’s production reports (oil is crude plus condensate; gas is gas-well plus casinghead gas), shown through ' + monthLabel(R.prodMeta.through) + ', the newest month that is complete. '
        + (R.prodMeta.partial.length ? 'Reports for ' + monthLabel(R.prodMeta.partial[0]) + ' to ' + monthLabel(R.prodMeta.partial[R.prodMeta.partial.length - 1]) + ' are still being filled in and run below the EIA estimate, so they are left out. ' : '')
        + (cross ? 'Cross-check against the EIA’s own estimate, ' + cross : '')
        : 'The Railroad Commission production file is not loaded, so this shows the EIA’s monthly estimate of Texas crude production only; the newest months are not yet published.') : '')
        + Object.entries(R.crude).map(([id, ser]) => (R.prodOil || R.eia ? ' ' : '') + stName(id) + ' is the EIA’s monthly estimate of field production of crude oil, through ' + monthLabel(ymOf(ser.t[lastIdx(ser.v)])) + '; its newest months are estimates that the EIA revises. ' + stName(id) + ' has no county or operator production file here.').join('')],
    });
  }

  if (R.jobsOil) {
    const mk = (id, title, ser, ic) => ({ id, title, icon: ic, color: 'var(--s7)', zero: false, fmtTick: (v) => v + 'K', series: [S({ id, name: title, unit: 'jobs', color: 'var(--s7)', ...ser, prelim: R.prelim, fmtVal: (v) => v.toFixed(1) + 'K', fmtEnd: (v) => v.toFixed(1) + 'K' })] });
    const panels = [mk('jobsOil', 'Oil and gas extraction', R.jobsOil, 'jobs'), mk('jobsSup', 'Support activities for mining (oilfield services)', R.jobsSup, 'building')];
    groups.push({
      id: 'jobs', label: 'Jobs', icon: 'jobs',
      spec: () => ({ label: 'Texas oil and gas employment', domain: [R.jobsOil.t[0], R.jobsOil.t[R.jobsOil.t.length - 1]], panels }),
      notes: ['Texas employees on payroll, thousands, not seasonally adjusted (BLS state and area employment). A hollow end dot marks a first print that BLS revises.'],
    });
  }

  if (R.taxOil) {
    const mk = (id, title, ser) => ({ id, title, icon: 'dollar', color: 'var(--s1)', zero: true, fmtTick: (v) => '$' + v, series: [S({ id, name: title, unit: 'USD collected', color: 'var(--s1)', ...ser, fmtVal: usdM, fmtEnd: (v) => '$' + Math.round(v) + 'M' })] });
    const panels = [mk('taxOil', 'Oil production tax', R.taxOil), mk('taxGas', 'Natural gas production tax', R.taxGas)];
    groups.push({
      id: 'taxes', label: 'Taxes', icon: 'dollar',
      spec: () => ({ label: 'Texas production tax receipts', domain: [R.taxOil.t[0], R.taxOil.t[R.taxOil.t.length - 1]], panels }),
      notes: ['USD millions collected by the Texas Comptroller in each month, net of refunds. Production is taxed about two months after it happens, so these trail prices and output. Gas collections for August 2020 were negative because refunds exceeded receipts.'],
    });
  }
  return groups;
}

/* ---------- wiring ---------- */
let live = null; // the pulse card on the page: called again when the states shown change, it replaces its tabs and chart
export function initMarkets({ ticker, card, raw, states = ['TX'] }) {
  if (live) { live.tabs.el.remove(); live.cleanup(); live = null; }
  const R = registry(raw, states);
  const groups = makeGroups(R, raw);
  const gl = new Map(groups.map((g) => [g.id, g.label]));
  const defs = chipDefs(R, raw);
  let api = { select() {} };
  if (!defs.length) ticker.closest('section').hidden = true;
  else ticker.replaceChildren(...defs.map((c) => chipNode(c, (gl.get(c.group) || 'market').toLowerCase(), (g) => api.select(g, true))));
  if (!groups.length) { card.hidden = true; return api; }
  card.hidden = false;

  const root = $('#pulse-root'); const tableWrap = $('#pulse-table-wrap'); const toggle = $('#pulse-toggle'); const src = $('#pulse-src');
  let current = null; let tableOn = false; let chart = null;
  toggle.setAttribute('aria-pressed', 'false'); toggle.textContent = 'View as table';
  const tabs = segmented({
    label: 'Market pulse group', value: groups[0].id, prefix: 'pg', options: groups.map((g) => ({ id: g.id, label: g.label, icon: g.icon, controls: 'pulse-root' })),
    onChange: (id) => show(id),
  });
  $('#pulse-tools').prepend(tabs.el);
  function show(id) {
    const g = groups.find((x) => x.id === id) || groups[0];
    current = g; hideTip();
    if (!g.built) g.built = g.spec();
    root.setAttribute('role', 'tabpanel'); root.setAttribute('aria-labelledby', 'pg-' + g.id);
    const host = el('div', { class: 'pulse-chart' });
    root.replaceChildren(host, ...g.notes.filter(Boolean).map((n) => el('p', { class: 'pulse-foot', text: n })));
    chart = seriesGroup(host, g.built);
    tableWrap.replaceChildren(...seriesTables(g.built));
    tableWrap.setAttribute('aria-label', g.label + ' values by date, newest first');
    root.hidden = tableOn; tableWrap.hidden = !tableOn;
  }
  const flip = () => {
    tableOn = toggle.getAttribute('aria-pressed') !== 'true';
    toggle.setAttribute('aria-pressed', String(tableOn)); toggle.textContent = tableOn ? 'Chart view' : 'View as table';
    root.hidden = tableOn; tableWrap.hidden = !tableOn; hideTip();
    if (!tableOn && chart) chart.render();
  };
  toggle.addEventListener('click', flip);
  live = { tabs, cleanup: () => toggle.removeEventListener('click', flip) };
  show(groups[0].id);
  src.textContent = 'Each group has its own latest date; see "Data freshness" below and Sources and method for what each series is.'
    + (!states.includes('TX') ? ' ' + states.map(stName).join(' and ') + ' ' + (states.length > 1 ? 'have' : 'has') + ' no rig count, jobs or tax series here: their sources could not be read when the site was built.'
      : states.length > 1 ? ' Rigs, jobs and taxes are Texas’s: ' + states.filter((id) => id !== 'TX').map(stName).join(' and ') + ' ' + (states.length > 2 ? 'have' : 'has') + ' none of them here.' : '');
  api = {
    select(id, scroll) {
      if (!groups.some((g) => g.id === id)) return;
      tabs.set(id, false); show(id);
      if (tableOn) toggle.click();
      if (scroll) card.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
    },
    registry: R,
  };
  return api;
}
