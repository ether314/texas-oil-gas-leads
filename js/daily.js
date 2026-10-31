// Daily report: what the Railroad Commission of Texas, the Oklahoma Corporation Commission and New Mexico's Oil Conservation Division
// published overnight, one report per day for the last 92 days, the states as one dataset. A simple version for the daily look and a
// verbose one with everything. The states bar narrows it to some of them. Each block hides itself if its data is missing, and a day
// one state has no report for is said so, never counted as zero. The merging itself is in daily-data.js; the parts only one state has
// are in daily-tx.js (pending queue, image packs, GPS map), daily-ok.js (transfers, well inventory) and daily-nm.js (its one dataset).
// A report holds only what its state publishes: a figure a state does not have is a key it does not carry, and is left out here.
import { el, loadOpt, reduced, monthLabel } from './util.js';
import { getGeo, buildGeoIsolated } from './geo.js';
import { icon } from './icons.js';
import { segmented, shareButton, absoluteLink } from './ui.js';
import { delta } from './charts.js';
import { tipRow } from './tip.js';
import { opsLink } from './overview.js';
import { trendBars, countyMap, ribbon, ring, calendar, stack, histogram, rankList, fmtMd, fmtDow, fmtLong, addDays, mb } from './daily-viz.js';
import { num, strong, listed, central, compare, rel, card, head, tiles, table, chip, kpi, pl, signed, pctOf } from './daily-kit.js';
import { STATES, stateOf, stateParam, ck, prepIndex, mergeDays, permitSeries, bizSeries, avgBefore, monthToDate, mergeRank, mergedCounties, sumOf } from './daily-data.js';
import { activeStates, setStates as setGlobalStates } from './states.js';
import { texasParts, TX_TITLES, TX_ICONS, TX_WHAT, PERMIT_TYPE } from './daily-tx.js';
import { transfersSection, wellsSection, OK_TITLES, OK_ICONS, OK_WHAT } from './daily-ok.js';
import { NM_TITLES, NM_ICONS, NM_WHAT } from './daily-nm.js';
import { listAnd } from './states.js';

const TITLES = { TX: TX_TITLES, OK: OK_TITLES, NM: NM_TITLES };
const ICONS = { TX: TX_ICONS, OK: OK_ICONS, NM: NM_ICONS };
const WHAT = { TX: TX_WHAT, OK: OK_WHAT, NM: NM_WHAT };
const FILES = { TX: 'nightly', OK: 'daily', NM: 'daily' }; // what each commission calls the files the report reads
const HISTORY = { TX: 'RRC file history', OK: 'Commission file history', NM: 'OCD well layer' };
const WORDS = { TX: { permits: 'new-drill permits issued', completions: 'completions approved' }, OK: { permits: 'new-drill permits approved', completions: 'completion filings' },
  NM: { permits: 'new-drill permits approved', completions: 'completions' } };
const THEM = { TX: 'the Railroad Commission of Texas', OK: 'the Oklahoma Corporation Commission', NM: 'the New Mexico Oil Conservation Division' };
// where a state's permits come from (the sentence under the permits section)
const PERMIT_FROM = { TX: 'the nightly Drilling Permit Master and Trailer file', OK: 'the Commission\'s daily intent-to-drill file', NM: 'the Oil Conservation Division\'s well layer (permits to drill)' };
const HORIZ = new Set(['TX', 'NM']); // the states whose permits say which wells are horizontal; the other only has a planned depth
const SERIES = { TX: 'daily/permits-series', NM: 'daily-nm/permits-series' }; // the states that keep a file of permits by day, rewritten each night
const DEEP = 'Deep, 12,000 ft or more';

export function createDailyView({ root }) {
  const S = {
    idx: {}, series: {}, gj: {}, gCache: {}, avail: [], states: STATES.filter((s) => s.dir).map((s) => s.id), days: [], G: null, gTx: null, sok: null, snm: null, mk: null,
    reps: {}, miss: {}, day: null, mode: 'simple', layer: 'permits', metric: 'permits', seq: 0, ready: false, sel: null, open: null, gpsEl: null, rb: null,
  };
  const h1 = el('h1', { id: 'dr-h1', class: 'dr-title', tabindex: '-1' });
  root.replaceChildren(h1, el('p', { class: 'empty', text: 'Loading the daily report…' }));

  const multi = () => S.states.length > 1;
  const only = () => (multi() ? null : S.states[0]);
  const sname = (id) => stateOf(id).name;
  const place = () => listAnd(S.states.map(sname));
  const issued = () => (only() === 'OK' || only() === 'NM' ? 'approved' : 'issued');
  // a county's name from the shapes (every county is keyed by state and FIPS), and as a label: "Martin, TX" when both states show
  const cname = (id, f) => { const c = S.G && S.G.byFips.get(ck(id, f)); return c ? c.n : f || 'Unknown'; };
  const clabel = (id, name) => name + (multi() ? ', ' + id : '');
  const R = () => S.reps;
  // the states whose report for the day has a section; the totals, the average and the chart are over these, so a state with no report is out of all of them
  const have = (key) => S.states.filter((id) => S.reps[id] && S.reps[id][key]);
  const onlyNote = (ids) => (multi() && ids.length < S.states.length ? ' · ' + ids.map(sname).join(' and ') + ' only' : '');
  const avgTxt = (a) => (a >= 10 ? String(Math.round(a)) : a.toFixed(1));

  const ctx = { S, cname: (f) => cname('TX', f), multi, hashFor };
  const tx = texasParts(ctx);

  /* ---------- data ---------- */
  async function boot() {
    const have = STATES.filter((s) => s.dir); // a state with no Daily report is not asked for one
    const raw = await Promise.all(have.map((s) => loadOpt(s.dir + '/index')));
    S.avail = have.map((s) => s.id).filter((id, i) => raw[i] && raw[i].days && raw[i].days.length);
    if (!S.avail.length) throw new Error('no daily data');
    S.avail.forEach((id) => { S.idx[id] = prepIndex(raw[have.findIndex((s) => s.id === id)]); });
    const withShapes = have.filter((s) => S.avail.includes(s.id));
    const [gTx, gjs, sers, sok, snm, mk] = await Promise.all([getGeo().catch(() => null), Promise.all(withShapes.map((s) => loadOpt(s.files ? s.files.geo : 'counties.geo'))),
      Promise.all(withShapes.map((s) => (SERIES[s.id] ? loadOpt(SERIES[s.id]) : null))), loadOpt('series-ok'), loadOpt('series-nm'), loadOpt('series-markets')]);
    withShapes.forEach((s, i) => { S.series[s.id] = permitSeries(s.id, S.idx[s.id], sers[i]); S.gj[s.id] = gjs[i]; });
    S.gTx = gTx; S.sok = sok; S.snm = snm; S.mk = mk;
    S.ready = true;
  }
  // The counties of the states shown in one set of shapes, built against their own box so the Texas map (hero, Map view, GPS map) keeps its
  // projection. Texas and Oklahoma keep the shapes of both whichever of the two is shown, as the page always drew them; New Mexico's are
  // drawn with the states shown when it is one of them.
  function useShapes() {
    const ids = S.states.includes('NM') ? S.states : S.avail.filter((id) => id !== 'NM');
    const key = ids.join('+');
    if (!(key in S.gCache)) {
      const parts = ids.map((id) => S.gj[id] && { id, gj: S.gj[id] }).filter(Boolean);
      try { S.gCache[key] = parts.length ? buildGeoIsolated(mergedCounties(parts)) : null; } catch (e) { S.gCache[key] = null; }
    }
    S.G = S.gCache[key];
  }
  const setDays = () => { S.days = mergeDays(S.idx, S.states); };
  // the day a report opens on: the newest one every state shown has a report for, so a night when one state's capture failed does
  // not open on a half-empty page (the newer day is still one step Later). Falls back to the newest day there is.
  const latest = () => { const full = S.days.filter((e) => !e.partial); return (full.length ? full : S.days)[(full.length ? full : S.days).length - 1].d; };
  const hist = (fn) => { const cut = S.days.findIndex((e) => e.d === S.day); return S.days.slice(Math.max(0, cut - 29), cut + 1).map(fn).filter((v) => v != null); };
  // completions that day's report adds, summed over the states shown (null when none has the figure)
  const completionsOf = (e) => { const v = S.states.map((id) => (e.r[id] ? e.r[id].c : null)).filter((x) => x != null); return v.length ? sumOf(v) : null; };
  const tally = (rows, i) => { const m = new Map(); rows.forEach((r) => { if (r[i]) m.set(r[i], (m.get(r[i]) || 0) + 1); }); return m; };

  /* ---------- address of a view: day, version, states shown, and a Texas well ---------- */
  function hashFor(day, mode, sel) {
    const q = new URLSearchParams();
    if (day !== latest()) q.set('d', day);
    if (mode === 'full') q.set('v', 'full');
    const sp = stateParam(activeStates()); // the site-wide choice, whichever of its states have a report
    if (sp) q.set('st', sp);
    if (sel) q.set(sel.t === 'p' ? 'drill' : 'survey', sel.id);
    return '#daily' + (q.toString() ? '?' + q : '');
  }

  /* ---------- header, ribbon, KPIs ---------- */
  function hero() {
    const days = S.days; const i = days.findIndex((r) => r.d === S.day);
    const pills = [];
    for (const id of S.states) {
      const rep = S.reps[id]; const name = sname(id); const pre = multi() ? name + ': ' : '';
      if (!rep) { pills.push(chip(S.miss[id] === 'error' ? 'bad' : 'warn', pre + (S.miss[id] === 'error' ? 'this report could not be loaded' : 'no report for this day'))); continue; }
      const live = rep.kind === 'live'; const ds = rep.datasets.filter((d) => !d.absent);
      const read = ds.filter((d) => !d.error).length; const cmp = compare(rep);
      const status = live ? (rep.status === 'ok' ? 'good' : rep.status === 'partial' ? 'warn' : 'bad') : 'info';
      pills.push(chip(status, pre + (live ? read + ' of ' + ds.length + ' ' + FILES[id] + ' files read' : 'reconstructed from ' + HISTORY[id])));
      if (live && rep.capturedAt) pills.push(chip('quiet', (multi() ? name + ' captured ' : 'Captured ') + central(rep.capturedAt)));
      if (!multi() && live && cmp.ok && cmp.fresh) pills.push(chip('quiet', cmp.fresh + ' updated since the last report'));
      if (!multi() && live && !cmp.ok) pills.push(chip('quiet', 'First live capture'));
    }
    const step = (n) => go(days[i + n].d, S.mode);
    const nav = el('div', { class: 'dr-nav' },
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'earlier', disabled: i === 0, 'aria-label': 'Earlier day', onclick: () => step(-1) }, icon('arrow', 14, 'flip'), 'Earlier'),
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'later', disabled: i === days.length - 1, 'aria-label': 'Later day', onclick: () => step(1) }, 'Later', icon('arrow', 14)),
      S.day === latest() ? null : el('button', { type: 'button', class: 'btn sm primary', 'data-act': 'latest', onclick: () => go(latest(), S.mode) }, 'Latest'),
      shareButton(() => absoluteLink(location.hash || '#daily'), 'Copy link'));
    const seg = segmented({ label: 'Report version', options: [{ id: 'simple', label: 'Simple' }, { id: 'full', label: 'Verbose' }], value: S.mode, tabs: false, prefix: 'drv', onChange: (id) => go(S.day, id) });
    h1.textContent = fmtLong(S.day).replace(/, \d{4}$/, '');
    const eyebrow = multi() ? 'Daily ' + listAnd(S.states.map(sname)) + ' report' : 'Daily ' + stateOf(only()).agency + ' report';
    const them = multi() ? listAnd(S.states.map((id) => THEM[id])) : only() === 'TX' ? 'the Railroad Commission' : THEM[only()];
    return el('header', { class: 'dr-hero' },
      el('div', { class: 'dr-radar', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')),
      el('div', { class: 'dr-hero-in' },
        el('p', { class: 'eyebrow' }, el('span', { class: 'live-dot', 'aria-hidden': 'true' }), eyebrow + ' · ', el('span', { text: S.day.slice(0, 4) })),
        h1,
        el('p', { class: 'dr-lede', text: S.mode === 'simple' ? 'The daily look: what ' + them + ' published overnight, in a minute.' : 'Everything ' + them + ' list' + (multi() ? '' : 's') + ' as nightly, twice daily or daily, captured and read.' }),
        el('div', { class: 'dr-pills' }, pills)),
      el('div', { class: 'dr-controls' }, seg.el, nav));
  }

  function ribbonTip(e) {
    const rows = [tipRow(fmtDow(e.d), e.live ? 'captured live' : 'reconstructed')];
    for (const id of S.states) {
      const r = e.r[id]; const pre = multi() ? id + ' ' : '';
      if (!r) { rows.push(tipRow(sname(id), 'no report')); continue; }
      if (r.pFresh && r.pn != null) rows.push(tipRow(num(r.pn), pre + WORDS[id].permits + ' ' + fmtMd(r.dd)));
      if (id === 'TX' && r.q != null) rows.push(tipRow(num(r.q), pre + 'waiting for approval'));
      if (r.c != null) rows.push(tipRow(num(r.c), pre + WORDS[id].completions));
      if (id === 'OK' && r.t != null) rows.push(tipRow(num(r.t), pre + 'wells changed operator'));
    }
    return rows;
  }

  const stateKey = () => el('span', { class: 'dr-legend-inline' }, S.states.flatMap((id) => [el('i', { class: 'dr-dot ' + id.toLowerCase() }), el('span', { text: sname(id) })]));

  function ribbonCard() {
    const rb = ribbon({ days: S.days, ids: S.states, selected: S.day, onPick: (d) => go(d, S.mode), tip: ribbonTip });
    S.rb = rb; // positioned again once it is in the page, so a phone opens on the selected day
    return card('dr-ribbon-card', el('div', { class: 'dr-ribbon-head' }, el('p', { class: 'eyebrow' }, icon('calendar', 15), 'Last 3 months'),
      el('small', { text: 'One bar per report day. Height is the new-drill permits ' + issued() + ' that business day' + (multi() ? ', ' + (S.states.length === 2 ? 'both' : 'all') + ' states stacked' : '') + '; weekends have none.' }), multi() ? stateKey() : null), rb.el);
  }

  // New Mexico's layer is entered some days after an approval, so its newest days run low and are not a fair comparison with an average of days that
  // have filled in: a permit day within 3 days of the last one the series speaks for is "still filling in"
  const filling = (id) => id === 'NM' && S.reps[id] && S.reps[id].permits && S.series[id] && S.series[id].hi && S.reps[id].permits.day > addDays(S.series[id].hi, -3);
  function permitKpi() {
    const label = 'New-drill permits ' + issued();
    const ids = have('permits');
    if (!ids.length) return kpi({ ic: 'pin', label, value: null, hero: true, color: 'var(--s2)', vals: [], note: 'No permit file was read for this day' });
    const ps = ids.map((id) => ({ id, p: S.reps[id].permits }));
    const until = ps.map((x) => x.p.day).sort().pop(); const sers = ids.map((id) => S.series[id]);
    const value = sumOf(ps.map((x) => x.p.newDrill)); const total = sumOf(ps.map((x) => x.p.total));
    const avg = avgBefore(sers, until); const bs = bizSeries(sers, until, 20);
    const days = [...new Set(ps.map((x) => x.p.day))];
    const split = ps.length > 1 ? ps.map((x) => x.id + ' ' + num(x.p.newDrill) + (days.length > 1 ? ' on ' + fmtDow(x.p.day) : '')).join(' · ') : null;
    return kpi({ ic: 'pin', label, value, hero: true, color: 'var(--s2)', vals: bs.total,
      note: [days.length === 1 ? fmtDow(days[0]) : null, split, num(total) + (total === 1 ? ' permit' : ' permits') + ' of all ' + (ps.length === 1 && ids[0] === 'TX' ? 'types' : 'kinds') + onlyNote(ids)].filter(Boolean).join(' · '),
      extra: ids.length === 1 && filling(ids[0]) ? 'The newest days are still filling in'
        : avg ? [delta((value - avg) / avg), ' vs the 20-day average of ' + avgTxt(avg), ids.some(filling) ? ' · New Mexico is still filling in' : ''] : null });
  }
  function completionsKpi() {
    const items = have('completions').map((id) => ({ id, c: S.reps[id].completions }));
    const nOf = ({ id, c }) => (id === 'TX' ? c.approved : c.filed);
    const label = only() === 'TX' ? 'Completions approved' : only() === 'OK' ? 'Completions filed' : 'Completions';
    let note = 'No completion filings for this day';
    if (items.length === 1 && !multi()) {
      const { id, c } = items[0];
      note = id === 'TX' ? num(c.initial) + ' first tests of new wells · ' + fmtDow(c.day) : pl(c.amended, 'amended filing') + ' · ' + fmtDow(c.day);
    } else if (items.length) note = items.map((x) => x.id + ' ' + num(nOf(x)) + (x.id === 'TX' ? ' approved' : ' filed')).join(' · ') + onlyNote(items.map((x) => x.id));
    return kpi({ ic: 'drop', label, value: items.length ? sumOf(items.map(nOf)) : null, color: 'var(--s3)', vals: hist(completionsOf), note });
  }
  function waitingKpi() {
    const q = S.reps.TX && S.reps.TX.pending;
    return kpi({ ic: 'clock', label: multi() ? 'Waiting for approval · Texas' : 'Waiting for approval', value: q && q.total, color: 'var(--s1)', vals: hist((e) => (e.r.TX ? e.r.TX.q : null)),
      note: q ? num(q.expedite) + ' expedited · ' + num(q.horizontal) + ' horizontal' : 'No pending set recorded for this day' });
  }
  function filesKpi() {
    const reps = S.states.filter((id) => S.reps[id]).map((id) => S.reps[id]);
    const live = reps.length > 0 && reps.every((r) => r.kind === 'live');
    const cmps = reps.map(compare); const cmpOk = live && cmps.every((c) => c.ok);
    const total = sumOf(reps.map((r) => r.datasets.filter((d) => !d.absent).length));
    const read = sumOf(reps.map((r) => r.datasets.filter((d) => !d.absent && !d.error).length));
    const fresh = sumOf(cmps.map((c) => c.fresh)); const same = sumOf(cmps.map((c) => c.same.length));
    return kpi({ ic: 'check', label: cmpOk ? 'Files updated' : 'Files read', value: cmpOk ? fresh : read, color: 'var(--accent)', gauge: ring(cmpOk ? fresh : read, total),
      note: cmpOk ? (fresh === total ? 'Every dataset changed since the last report' : num(same) + ' unchanged since the last report')
        : live ? 'First live capture: changes show from the next report' : (multi() ? 'Rebuilt from the commissions\' file history' : 'Rebuilt from the Commission file history') });
  }
  function transfersKpi() {
    const t = S.reps.OK && S.reps.OK.transfers;
    return kpi({ ic: 'building', label: 'Wells changing operator', value: t && t.wells, color: 'var(--s1)', vals: hist((e) => (e.r.OK ? e.r.OK.t : null)),
      note: t ? t.buyerCount + (t.buyerCount === 1 ? ' buyer' : ' buyers') + ' · ' + fmtDow(t.day) : 'No transfers on file for this day' });
  }
  function wellsKpi(id = 'OK') {
    const w = S.reps[id] && S.reps[id].wells;
    return kpi({ ic: 'rig', label: 'Active wells in the state', value: w && w.active, color: 'var(--accent)',
      note: w ? (w.change ? signed(w.change.active) + ' since ' + fmtMd(w.change.since) : 'As of ' + fmtMd(w.asOf)) : 'The inventory is counted on the night of each live capture' });
  }
  // New Mexico's permits say which wells are horizontal: that is what is added to its permit count and its files
  function horizontalKpi() {
    const p = S.reps.NM && S.reps.NM.permits;
    return kpi({ ic: 'rig', label: 'Horizontal wells', value: p && p.newDrill ? Math.round((p.horizontal / p.newDrill) * 100) : null, format: (v) => v + '%', color: 'var(--s3)',
      note: p ? num(p.horizontal) + ' of ' + num(p.newDrill) + ' permits' + (p.vertical || p.directional ? ' · ' + num(p.vertical + p.directional) + ' vertical or directional' : '') : 'No permit file was read for this day' });
  }
  function kpiRow() {
    const o = only();
    const cards = o === 'OK' ? [permitKpi(), completionsKpi(), transfersKpi(), wellsKpi()] : o === 'NM' ? [permitKpi(), horizontalKpi(), wellsKpi('NM'), filesKpi()]
      : [permitKpi(), S.states.includes('TX') ? waitingKpi() : null, completionsKpi(), filesKpi()].filter(Boolean);
    return el('div', { class: 'dr-kpis' + (cards.length === 3 ? ' three' : '') }, cards);
  }

  /* ---------- permits per day and the map ---------- */
  function trendCard() {
    const ids = have('permits');
    if (!ids.length) return null;
    const until = ids.map((id) => S.reps[id].permits.day).sort().pop(); const sers = ids.map((id) => S.series[id]);
    const bs = bizSeries(sers, until, 30);
    if (bs.days.length < 5) return null;
    const avg = avgBefore(sers, until); const value = sumOf(ids.map((id) => S.reps[id].permits.newDrill));
    let series; let legend;
    if (ids.length > 1) {
      series = ids.map((id) => ({ label: sname(id), cls: id.toLowerCase(), values: bs.n[id] }));
      legend = ids.map((id) => [id.toLowerCase(), sname(id)]);
    } else { // one state: its own split, horizontal against the rest in Texas and New Mexico, planned depth in Oklahoma
      const id = ids[0]; const n = bs.n[id]; const h = bs.h[id]; const hz = HORIZ.has(id);
      const [c1, c2] = id === 'TX' ? ['horiz', 'rest'] : [id.toLowerCase(), id.toLowerCase() + 'rest']; // the state's own colour, solid for the first part and pale for the rest
      series = [{ label: hz ? 'horizontal' : 'planned 12,000 ft or deeper', cls: c1, values: h }, { label: hz ? 'other' : 'shallower', cls: c2, values: n.map((v, i) => (v == null ? null : v - (h[i] || 0))) }];
      legend = [[c1, hz ? 'Horizontal' : DEEP], [c2, hz ? 'Other' : 'Shallower']];
    }
    return card('dr-trend', head('trend', 'Pace', 'New-drill permits per business day', 'Last 30 business days to ' + fmtMd(until) + '. Holidays show as empty days.'),
      el('div', { class: 'dr-legend-inline' }, legend.flatMap(([cls, text]) => [el('i', { class: 'dr-dot ' + cls }), el('span', { text })])),
      trendBars({ days: bs.days, series, total: bs.total, avg, avgText: avg ? avgTxt(avg) : null,
        label: 'Bar chart of new-drill permits per business day from ' + fmtMd(bs.days[0]) + ' to ' + fmtMd(until) + '. ' + fmtDow(until) + ' had ' + value + (avg ? ', against an average of ' + avgTxt(avg) : '') + '.' }));
  }

  function mapCard() {
    const layers = {}; const defs = []; const names = {};
    const lay = (id, label, parts) => {
      const ps = parts.filter((x) => x && x.rows && x.rows.length);
      if (!ps.length) return;
      const map = new Map(); const nm = new Map();
      for (const { id: s, rows } of ps) for (const [f, name, n] of rows) { map.set(ck(s, f), n); nm.set(ck(s, f), clabel(s, name)); }
      layers[id] = { map }; names[id] = nm;
      // when only some of the states shown have the layer, the tab says which ("Waiting · TX", "Active wells · OK and NM")
      const has = ps.map((x) => x.id);
      defs.push({ id, label: label + (multi() && has.length < S.states.length ? ' · ' + has.join(' and ') : '') });
    };
    const txR = S.reps.TX; const okR = S.reps.OK; const nmR = S.reps.NM;
    const txCounties = (m) => [...m.entries()].map(([f, n]) => [f, cname('TX', f), n]);
    lay('permits', 'Permits', [txR && txR.permits && { id: 'TX', rows: txCounties(tally(txR.permits.rows, 1)) }, okR && okR.permits && { id: 'OK', rows: okR.permits.counties }, nmR && nmR.permits && { id: 'NM', rows: nmR.permits.counties }]);
    lay('pending', 'Waiting', [txR && txR.pending && { id: 'TX', rows: txCounties(tally(txR.pending.rows, 2)) }]);
    lay('completions', 'Completions', [txR && txR.completions && { id: 'TX', rows: txR.completions.counties }, okR && okR.completions && { id: 'OK', rows: okR.completions.counties }]);
    lay('transfers', 'Transfers', [okR && okR.transfers && { id: 'OK', rows: okR.transfers.counties }]);
    lay('wells', 'Active wells', [okR && okR.wells && { id: 'OK', rows: okR.wells.counties }, nmR && nmR.wells && { id: 'NM', rows: nmR.wells.counties }]);
    if (!defs.length) return null;
    if (!layers[S.layer]) S.layer = defs[0].id;
    const colors = { permits: 'var(--s2)', pending: 'var(--s1)', completions: 'var(--s3)', transfers: 'var(--s1)', wells: 'var(--s7)' };
    const unit = { permits: 'new-drill permits ' + issued(), pending: 'applications waiting for approval', completions: only() === 'TX' ? 'completions approved' : only() === 'OK' ? 'completion filings' : 'completions approved or filed', transfers: 'wells that changed operator', wells: 'active wells' };
    const list = el('div', { class: 'dr-maplist' });
    const wrap = el('div', { class: 'dr-mapwrap' });
    const map = S.G ? countyMap(S.G, layers, S.layer, { place: place(), only: multi() ? null : S.states, showState: multi(), unit }) : null;
    if (map) wrap.append(map.el);
    const paint = () => {
      wrap.style.setProperty('--lc', colors[S.layer]);
      const top = [...layers[S.layer].map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
      list.replaceChildren(el('p', { class: 'dr-maplist-h', text: 'Top counties · ' + unit[S.layer] }),
        rankList(top.map(([f, n]) => ({ label: names[S.layer].get(f) || f, value: n })), { color: colors[S.layer], empty: 'No county detail for this layer.' }));
    };
    const seg = segmented({ label: 'Map layer', options: defs, value: S.layer, tabs: false, prefix: 'drm', onChange: (id) => { S.layer = id; if (map) map.set(id); paint(); } });
    paint();
    return card('dr-mapcard', head('pin', 'Where', place() + ', by county', 'Bubbles grow with the count; hover a county for its number.'), el('div', { class: 'dr-maptools' + (defs.length > 3 ? ' tight' : '') }, seg.el), wrap, list);
  }

  // monthly figures: crude production in the states shown (series-markets.json holds Texas, series-ok.json Oklahoma) and the two prices.
  // They change once a month and are not for the report's day, so each one says which month it is
  function contextCard() {
    const items = [];
    const add = ({ ic, label, months, vals, color, format, unit }) => {
      if (!months || !vals) return;
      let i = vals.length - 1;
      while (i >= 0 && vals[i] == null) i--;
      if (i < 12 || vals[i - 12] == null) return; // a year behind is the comparison
      items.push(kpi({ ic, label, value: vals[i], format, color, vals: vals.slice(Math.max(0, i - 35), i + 1).filter((v) => v != null),
        note: unit + ' in ' + monthLabel(months[i]) + ' · EIA', extra: [delta(vals[i] / vals[i - 12] - 1), ' vs ' + monthLabel(months[i - 12])] }));
    };
    const million = (v) => (v / 1000).toFixed(1) + ' million bbl';
    const mk = S.mk; const ok = S.sok; const nm = S.snm;
    if (mk && S.states.includes('TX')) add({ ic: 'drop', label: 'Texas crude oil production', months: mk.months, vals: mk.txCrude, color: 'var(--s2)', format: million, unit: 'a month' });
    if (ok && S.states.includes('OK')) add({ ic: 'drop', label: 'Oklahoma crude oil production', months: ok.months, vals: ok.okCrude, color: 'var(--s3)', format: million, unit: 'a month' });
    if (nm && S.states.includes('NM')) add({ ic: 'drop', label: 'New Mexico crude oil production', months: nm.months, vals: nm.nmCrude, color: 'var(--s3)', format: million, unit: 'a month' });
    if (mk) {
      add({ ic: 'dollar', label: 'WTI crude oil price', months: mk.months, vals: mk.wti, color: 'var(--s2)', format: (v) => '$' + v.toFixed(2), unit: 'a barrel' });
      add({ ic: 'flame', label: 'Henry Hub natural gas price', months: mk.months, vals: mk.henryHub, color: 'var(--s1)', format: (v) => '$' + v.toFixed(2), unit: 'per MMBtu' });
    }
    if (!items.length) return null;
    return card('dr-ctx-card', head('chart', 'Monthly figures', 'Oil and gas around ' + (multi() ? 'the ' + (S.states.length === 2 ? 'two' : 'three') + ' states' : 'the state'), 'The latest monthly figures EIA has published. They are not for the day above, and they change once a month.'), el('div', { class: 'dr-ctx' }, items));
  }

  /* ---------- what changed: plain-English bullets ---------- */
  function storyCard() {
    const out = [];
    const add = (ic, color, ...kids) => { const li = el('li', { class: 'insight' }, el('span', { class: 'insight-ic' }, icon(ic, 18)), el('div', {}, el('p', {}, ...kids))); li.firstChild.style.setProperty('--c', color); out.push(li); };
    const pre = (id) => (multi() ? [strong(sname(id) + ': ')] : []);
    const pids = have('permits'); const ps = pids.map((id) => ({ id, p: R()[id].permits }));
    // a state with no report is said so, and what follows is without it
    for (const id of S.states) if (!R()[id]) add('close', 'var(--down)', strong(sname(id) + ': ' + (S.miss[id] === 'error' ? 'this day\'s report could not be loaded. ' : 'no report was captured for this day. ')), 'Its numbers are not in anything below.');

    if (ps.length) {
      const nd = sumOf(ps.map((x) => x.p.newDrill)); const total = sumOf(ps.map((x) => x.p.total));
      const days = [...new Set(ps.map((x) => x.p.day))]; const until = days.slice().sort().pop();
      const avg = avgBefore(pids.map((id) => S.series[id]), until);
      const when = days.length === 1 ? [' on ', strong(fmtDow(days[0]))] : [];
      const where = ps.length > 1 ? [' across ' + place(), ...when, ' (' + ps.map((x) => sname(x.id) + ' ' + num(x.p.newDrill) + (days.length > 1 ? ' on ' + fmtDow(x.p.day) : '')).join(', ') + ')'] : when;
      if (nd) {
        add('pin', 'var(--s2)', strong(num(nd)), nd === 1 ? ' new-drill permit was ' + issued() : ' new-drill permits were ' + issued(), ...where,
          avg && !(pids.length === 1 && filling(pids[0])) ? [', ', strong(rel(nd, avg)), ' the 20-business-day average of ' + avgTxt(avg) + '.'] : '.',
          total - nd ? ' Another ' + (total - nd === 1 ? '1 was an amendment, re-entry, recompletion or other filing.' : (total - nd) + ' were amendments, re-entries, recompletions or other filings.') : '');
        const top = mergeRank(ps.map(({ id, p }) => ({ id, rows: p.counties })), 3);
        if (top.length) {
          add('layers', 'var(--s2)', strong(clabel(top[0].id, top[0].name)), ' led with ', strong(num(top[0].n)), top.length > 1 ? [', then ' + top.slice(1).map((x) => clabel(x.id, x.name) + ' (' + x.n + ')').join(' and ')] : '', '. ',
            sumOf(ps.map((x) => x.p.countyCount)) + (sumOf(ps.map((x) => x.p.countyCount)) === 1 ? ' county had' : ' counties had') + ' at least one.');
        }
        const named = mergeRank(ps.map(({ id, p }) => ({ id, rows: p.operators.filter((o) => o[1]) })), 1)[0];
        if (named) {
          const share = sumOf(ps.map((x) => (x.p.namedShare == null ? 0 : x.p.namedShare * x.p.newDrill))) / nd;
          add('building', 'var(--s2)', named.id === 'TX' ? el('a', { href: opsLink(named.name), text: named.name }) : strong(named.name), ' filed the most among operators that can be named (', strong(num(named.n)), '). ', Math.round(share * 100) + '% of the day\'s new-drill permits went to named operators.');
        }
        for (const { id, p } of ps) {
          if (!p.newDrill) continue;
          if (HORIZ.has(id)) add('rig', 'var(--s2)', ...pre(id), strong(Math.round((p.horizontal / p.newDrill) * 100) + '% horizontal'), p.depth ? [' · median planned depth ', strong(num(p.depth.median) + ' ft'), ', deepest ' + num(p.depth.max) + ' ft'] : '', p.wait ? ' · median ' + p.wait.median + ' days from receipt to approval.' : '.');
          else add('rig', 'var(--s2)', ...pre(id), strong(pctOf(p.deep, p.newDrill) + ' planned 12,000 ft or deeper'), p.depth ? [' · median planned depth ', strong(num(p.depth.median) + ' ft'), ', deepest ' + num(p.depth.max) + ' ft'] : '', p.wait ? ' · median ' + p.wait.median + (p.wait.median === 1 ? ' day' : ' days') + ' from filing to approval.' : '.');
        }
      } else {
        add('pin', 'var(--s2)', 'No new-drill permits were ' + issued() + ' on ', strong(days.map(fmtDow).join(' or ')), '.');
      }
    }
    // the Division's layer is entered some days after an approval: the newest days run low, and the line says so where the number is read
    if (R().NM && R().NM.permits) add('clock', 'var(--s1)', ...pre('NM'), strong('The newest days fill in later. '), 'The Division\'s well layer is entered some days after an approval, so the last two or three days run low; the pace chart is rewritten from the layer each night.');
    const q = R().TX && R().TX.pending;
    if (q) {
      const d = q.districts[0];
      add('clock', 'var(--s1)', ...pre('TX'), strong(num(q.total)), ' applications are waiting for approval, ', strong(num(q.expedite)), ' flagged to expedite', d ? [', most of them in District ' + d[0] + ' (' + d[1] + ').'] : '.');
    }
    const cs = have('completions').map((id) => ({ id, c: R()[id].completions }));
    if (cs.length) {
      const nOf = ({ id, c }) => (id === 'TX' ? c.approved : c.filed);
      // the best first test across the states shown: the largest oil rate, or Oklahoma's best gas test when nothing has oil
      const cand = [];
      cs.forEach(({ id, c }) => { if (id === 'TX' && c.topTests[0]) cand.push({ id, oil: c.topTests[0].rate, county: c.topTests[0].county, operator: c.topTests[0].operator }); if (id === 'OK' && c.tests[0]) cand.push({ id, oil: c.tests[0].oil || 0, gas: c.tests[0].gas, county: c.tests[0].county, operator: c.tests[0].operator }); });
      cand.sort((a, b) => (b.oil || 0) - (a.oil || 0) || (b.gas || 0) - (a.gas || 0));
      const best = cand[0];
      const days = [...new Set(cs.map((x) => x.c.day))];
      const bestText = best ? [' Best first test: ', strong(num(best.oil || best.gas) + (best.oil ? ' bbl of oil a day' : ' mcf of gas a day')), ' in ' + best.county + ' County' + (multi() ? ', ' + best.id : '') + (best.operator ? ' (' + best.operator + ')' : '') + '.'] : '';
      if (cs.length === 1 && !multi()) {
        const { id, c } = cs[0];
        if (id === 'TX') add('drop', 'var(--s3)', strong(num(c.approved)), ' completions were approved on ', strong(fmtDow(c.day)), '; ', strong(num(c.initial)), ' were first tests of new wells (' + c.oil + ' oil, ' + c.gas + ' gas).', bestText);
        else add('drop', 'var(--s3)', strong(num(c.filed)), c.filed === 1 ? ' completion was filed on ' : ' completions were filed on ', strong(fmtDow(c.day)), c.amended ? ', and ' + (c.amended === 1 ? '1 earlier filing was' : num(c.amended) + ' earlier filings were') + ' amended' : '', '.', bestText);
      } else {
        add('drop', 'var(--s3)', strong(num(sumOf(cs.map(nOf)))), days.length === 1 ? [' completions on ', strong(fmtDow(days[0]))] : ' completions',
          ' (' + cs.map((x) => sname(x.id) + ' ' + num(nOf(x)) + (x.id === 'TX' ? ' approved, ' + num(x.c.initial) + ' of them first tests of new wells' : ' filed') + (days.length > 1 ? ' on ' + fmtDow(x.c.day) : '')).join('; ') + ').', bestText);
      }
    }
    const t = R().OK && R().OK.transfers;
    if (t) {
      const b = t.buyers.find((x) => x[1]); const sb = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
      add('building', 'var(--s1)', ...pre('OK'), strong(num(t.wells)), t.wells === 1 ? ' well changed operator on ' : ' wells changed operator on ', strong(fmtDow(t.day)),
        b ? [': ', strong(b[1]), ' took ' + num(b[2])] : '', ' (' + sb(t.sellerCount, 'seller') + ', ' + sb(t.buyerCount, 'buyer') + ').');
    }
    for (const id of ['OK', 'NM']) {
      const w = R()[id] && R()[id].wells;
      if (w) add('rig', 'var(--accent)', ...pre(id), strong(num(w.active)), ' active wells in the state inventory', w.change ? [' (', strong(signed(w.change.active)), ' since ' + fmtMd(w.change.since) + ')'] : '', ', ', num(w.plugged) + ' plugged, of ' + num(w.total) + ' records.');
    }
    for (const id of S.states) {
      const rep = R()[id];
      if (!rep || rep.kind !== 'live') continue;
      const cmp = compare(rep); const same = cmp.same; const err = rep.datasets.filter((d) => d.error); const T = TITLES[id];
      if (!cmp.ok && !err.length) add('check', 'var(--accent)', ...pre(id), strong('First live capture. '), 'From the next report this line says which files changed overnight.');
      else if (err.length) add('close', 'var(--down)', ...pre(id), strong(err.length + ' of ' + rep.datasets.length + ' files could not be read: '), err.map((d) => T[d.id]).join(', ') + '.');
      else if (same.length) add('clock', 'var(--accent)', ...pre(id), strong(same.length + ' file' + (same.length > 1 ? 's' : '') + ' did not change'), ' since the last report: ' + same.map((d) => T[d.id]).join(', ') + '.');
      else add('check', 'var(--up)', ...pre(id), strong('Every ' + FILES[id] + ' file changed'), ' since the last report.');
      const newer = (rep.monthly || []).filter((m) => m.newer);
      if (newer.length) add('calendar', 'var(--down)', ...pre(id), strong('A newer monthly file is waiting: '), newer.map((m) => m.title).join(', ') + '. The site\'s monthly tables were built from the older one and are due for a rebuild.');
    }
    if (!out.length) return null;
    return card('dr-story', head('bulb', 'In short', 'What the files say'), el('ul', { class: 'dr-bullets' }, out));
  }

  function statusStrips() {
    const blocks = S.states.map((id) => {
      const rep = S.reps[id]; const s = stateOf(id);
      const heading = el('p', { class: 'dr-strip-h' }, el('i', { class: 'dr-dot ' + id.toLowerCase() }), s.name + ' · ' + s.agency, el('small', { text: rep ? FILES[id] + ' files' : 'no report for this day' }));
      if (!rep) return [heading];
      const live = rep.kind === 'live';
      const strip = el('div', { class: 'dr-strip' + (id === 'OK' ? ' four' : ''), role: 'list', 'aria-label': s.name + ' datasets' }, rep.datasets.map((d) => {
        const st = d.error ? 'bad' : d.absent ? 'quiet' : d.state === 'new' ? 'good' : d.state === 'same' ? 'warn' : 'quiet';
        const c = el('div', { class: 'dr-ds ' + st, role: 'listitem' }, el('span', { class: 'dr-ds-ic' }, icon(ICONS[id][d.id], 17)),
          el('div', {}, el('b', { text: TITLES[id][d.id] }),
            el('small', { text: d.error ? 'Could not be read' : d.absent ? 'Only the current inventory is published' : d.dataDay ? 'Data for ' + fmtMd(d.dataDay) : 'Nothing for this day' }),
            el('small', { class: 'dr-ds-st', text: d.error ? 'Error' : d.absent ? 'Live days only' : live ? (d.state === 'new' ? 'Updated · ' + listed(d.file && d.file.modified) : d.state === 'same' ? 'No change since the last report' : 'Read · ' + listed(d.file && d.file.modified)) : 'Reconstructed' })));
        c.title = WHAT[id][d.id];
        return c;
      }));
      return [heading, strip];
    });
    return el('div', { class: 'dr-strips' }, blocks.flat());
  }

  /* ---------- verbose sections ---------- */
  // each state's own breakdown in a column of its own when both show, side by side in blocks when one does
  function byState(items, blocks) {
    if (multi()) return el('div', { class: 'dr-cols' }, items.map((it) => el('div', {}, el('p', { class: 'dr-state-h' }, el('i', { class: 'dr-dot ' + it.id.toLowerCase() }), sname(it.id)), ...blocks(it).map((b) => el('div', { class: 'dr-blk' }, ...b)))));
    return el('div', { class: 'dr-cols' }, items.flatMap((it) => blocks(it)).map((b) => el('div', {}, ...b)));
  }
  const pair = (items) => items.filter(Boolean);
  const counties = (parts, color) => rankList(mergeRank(parts, 12).map((x) => ({ label: clabel(x.id, x.name), value: x.n })), { color });
  const operators = (parts, color) => rankList(mergeRank(parts, 12).map((x) => ({ label: x.name || 'Operator #' + x.key + (multi() ? ' (' + x.id + ')' : ''), value: x.n, href: x.id === 'TX' && x.name ? opsLink(x.name) : null })), { color });
  const colsOf = (label, a, b) => el('div', { class: 'dr-cols' }, el('div', {}, el('h3', { text: label[0] }), a), el('div', {}, el('h3', { text: label[1] }), b));

  function permitsSection() {
    const ids = have('permits');
    if (!ids.length) return card('dr-sec', head('pin', 'Permits', 'Drilling permits'), el('p', { class: 'empty', text: 'No permit file was read for this day.' }));
    const ps = ids.map((id) => ({ id, p: R()[id].permits }));
    const until = ps.map((x) => x.p.day).sort().pop();
    const m = monthToDate(ids.map((id) => S.series[id]), until);
    const nd = sumOf(ps.map((x) => x.p.newDrill)); const total = sumOf(ps.map((x) => x.p.total));
    const top = mergeRank(ps.map(({ id, p }) => ({ id, rows: p.counties })), 1)[0];
    const share = nd ? sumOf(ps.map((x) => (x.p.namedShare == null ? 0 : x.p.namedShare * x.p.newDrill))) / nd : null;
    const stateTiles = [];
    if (ps.length === 1) {
      const { id, p } = ps[0];
      stateTiles.push(HORIZ.has(id)
        ? { label: 'Horizontal', value: p.newDrill ? Math.round((p.horizontal / p.newDrill) * 100) + '%' : '—', note: num(p.horizontal) + ' of ' + num(p.newDrill) + (p.directional ? ' · ' + p.directional + ' directional' : '') }
        : { label: 'Planned 12,000 ft or deeper', value: pctOf(p.deep, p.newDrill), note: num(p.deep) + ' of ' + num(p.newDrill) });
      // a state that publishes no planned depth or filing date has no such key, and no tile (never a dash that looks like a value)
      if (p.depth !== undefined) stateTiles.push({ label: 'Median planned depth', value: p.depth ? num(p.depth.median) + ' ft' : '—', note: p.depth ? 'deepest ' + num(p.depth.max) + ' ft' : '' });
      if (p.wait !== undefined) stateTiles.push({ label: 'Days to approval', value: p.wait ? String(p.wait.median) : '—', note: p.wait ? 'median · longest ' + p.wait.max : id === 'TX' ? 'receipt to issue' : 'filing to approval' });
    }
    const kids = [tiles([
      { label: 'New-drill permits', value: num(nd), note: (ps.length > 1 ? ps.map((x) => x.id + ' ' + num(x.p.newDrill)).join(' · ') + ' · ' : '') + 'of ' + num(total) + ' ' + (only() === 'OK' ? 'approved' : 'issued') + onlyNote(ids) },
      ...stateTiles,
      { label: 'Operators', value: num(sumOf(ps.map((x) => x.p.operatorCount))), note: share != null ? Math.round(share * 100) + '% can be named' : '' },
      { label: 'Counties', value: num(sumOf(ps.map((x) => x.p.countyCount))), note: top ? clabel(top.id, top.name) + ' led' : '' },
      ps.some((x) => x.p.amended !== undefined) ? { label: 'Amended that day', value: num(sumOf(ps.map((x) => x.p.amended))), note: 'earlier permits changed' } : null,
      m ? { label: 'Month to date', value: num(m.a), note: m.b != null ? 'vs ' + num(m.b) + ' by the same date last month' : 'new-drill permits' } : null])];
    if (ps.length > 1) {
      // the two files do not measure the same things (Texas knows which wells are horizontal, Oklahoma only the planned depth), so side by side, not summed
      const cell = (id, fn) => { const x = ps.find((q) => q.id === id); return x ? fn(x.p) : '—'; };
      const rows = [
        ['Permit day', (p) => fmtDow(p.day)], ['New-drill permits', (p) => num(p.newDrill)], ['Other filings that day', (p) => num(p.total - p.newDrill)],
        ['Horizontal, or planned 12,000 ft or deeper', (p) => (p.horizontal != null ? pctOf(p.horizontal, p.newDrill) + ' horizontal' : p.deep != null ? pctOf(p.deep, p.newDrill) + ' deep' : '—')],
        ['Median planned depth', (p) => (p.depth ? num(p.depth.median) + ' ft' : '—')], ['Days to approval, median', (p) => (p.wait ? String(p.wait.median) : '—')],
        ['Operators', (p) => num(p.operatorCount) + (p.namedShare != null ? ' · ' + Math.round(p.namedShare * 100) + '% named' : '')], ['Counties', (p) => num(p.countyCount)], ['Amended that day', (p) => (p.amended != null ? num(p.amended) : '—')]];
      kids.push(table([{ t: 'By state' }, ...S.states.map((id) => ({ t: sname(id) }))], rows.map(([label, fn]) => [label, ...S.states.map((id) => cell(id, (p) => fn(p, id)))]), { cap: 'dr-table flat' }));
    }
    kids.push(byState(ps, ({ id, p }) => (id === 'TX'
      ? [[el('h3', { text: 'Application types' }), stack(p.types.map(([k, n]) => ({ label: PERMIT_TYPE[k] || 'Type ' + k, value: n })))],
        [el('h3', { text: 'Planned depth' }), histogram(p.rows.map((r) => r[5]).filter((v) => v > 0), [0, 5000, 7500, 10000, 12500, 15000], ['<5k', '5–7.5k', '7.5–10k', '10–12.5k', '12.5–15k', '15k+'], { unit: 'new-drill permits' })],
        [el('h3', { text: 'RRC districts' }), rankList(p.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s2)' })]]
      : id === 'NM'
        ? [[el('h3', { text: 'Kinds of well' }), stack(p.types.map(([k, n]) => ({ label: k, value: n })))],
          [el('h3', { text: 'Direction' }), stack([['Horizontal', p.horizontal], ['Vertical', p.vertical], ['Directional', p.directional]].filter((x) => x[1]).map(([k, n]) => ({ label: k, value: n })))],
          [el('h3', { text: 'OCD districts' }), rankList(p.districts.map(([d, n]) => ({ label: d, value: n })), { color: 'var(--s2)' })]]
      : pair([[el('h3', { text: 'Kinds of filing' }), stack(p.types.map(([k, n]) => ({ label: k, value: n })))],
        [el('h3', { text: 'Planned depth' }), p.newDrill ? rankList(p.bands.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s2)', max: Math.max(1, ...p.bands.map((b) => b[1])) }) : el('p', { class: 'fine', text: 'No new-drill permits.' })],
        p.classes.length ? [el('h3', { text: 'Kinds of well' }), stack(p.classes.map(([k, n]) => ({ label: k, value: n })))] : null]))));
    kids.push(colsOf(['Counties', 'Operators'], counties(ps.map(({ id, p }) => ({ id, rows: p.counties })), 'var(--s2)'), operators(ps.map(({ id, p }) => ({ id, rows: p.operators })), 'var(--s2)')));
    if (R().TX && R().TX.permits && ids.includes('TX')) kids.push(tx.permitRows(R().TX));
    const sub = 'From ' + (multi() ? listAnd(S.states.map((id) => PERMIT_FROM[id] + ' (' + sname(id) + ')')) : PERMIT_FROM[S.states[0]]) + '. No permits are issued on weekends, so Saturday, Sunday and Monday reports show Friday.';
    return card('dr-sec', head('pin', 'Permits', 'New-drill permits ' + issued() + ' ' + [...new Set(ps.map((x) => fmtDow(x.p.day)))].join(' and '), sub), ...kids);
  }

  function completionsSection() {
    const items = have('completions').map((id) => ({ id, c: R()[id].completions }));
    if (!items.length) return card('dr-sec', head('drop', 'Completions', 'Completion data'), el('p', { class: 'empty', text: 'No completion data landed for this day.' }));
    const nOf = ({ id, c }) => (id === 'TX' ? c.approved : c.filed);
    const kids = [];
    const total = sumOf(items.map(nOf));
    const lead = { label: 'Completions', value: num(total), note: multi() ? items.map((x) => x.id + ' ' + num(nOf(x)) + (x.id === 'TX' ? ' approved' : ' filed')).join(' · ') + onlyNote(items.map((x) => x.id))
      : items[0].id === 'TX' ? num(items[0].c.submitted) + ' more submitted' : items[0].c.amended ? 'plus ' + num(items[0].c.amended) + ' amended' : 'none amended' };
    const opCount = { label: 'Operators', value: num(sumOf(items.map((x) => x.c.operatorCount))), note: 'filed completions' };
    if (items.length === 1) {
      const { id, c } = items[0];
      kids.push(tiles(id === 'TX'
        ? [{ ...lead, label: 'Approved' }, { label: 'First tests of new wells', value: num(c.initial), note: 'initial potential filings' }, { label: 'Oil · gas', value: c.oil + ' · ' + c.gas, note: 'among first tests' },
          { label: 'Horizontal', value: num(c.horizontal), note: c.initial ? Math.round((c.horizontal / c.initial) * 100) + '% of first tests' : '' }, opCount]
        : [{ ...lead, label: 'Filed' }, { label: 'Horizontal', value: num(c.horizontal), note: c.filed ? pctOf(c.horizontal, c.filed) + ' of filings' : '' },
          { label: 'Filed after first production', value: c.lag ? pl(c.lag.median, 'day') : '—', note: c.lag ? 'median · longest ' + c.lag.max : 'where a first-production date is on file' },
          { label: 'Spud to first production', value: c.spudToProd ? pl(c.spudToProd.median, 'day') : '—', note: 'median, where both dates are on file' },
          { ...opCount, note: c.namedShare != null ? Math.round(c.namedShare * 100) + '% can be named' : '' }, { label: 'Counties', value: num(c.countyCount), note: c.counties[0] ? c.counties[0][1] + ' led' : '' }]));
    } else {
      kids.push(tiles([lead, opCount, { label: 'Counties', value: num(sumOf(items.map((x) => (x.c.countyCount != null ? x.c.countyCount : x.c.counties.length)))), note: 'with a completion' }]));
      const cell = (id, fn) => { const x = items.find((q) => q.id === id); return x ? fn(x.c) : '—'; };
      const rows = [
        ['Completion day', (c) => fmtDow(c.day)],
        ['Completions', (c, id) => (id === 'TX' ? num(c.approved) + ' approved · ' + num(c.submitted) + ' more submitted' : num(c.filed) + ' filed' + (c.amended ? ' · ' + num(c.amended) + ' amended' : ''))],
        ['First tests of new wells', (c, id) => (id === 'TX' ? num(c.initial) : '—')], ['Oil · gas, among first tests', (c, id) => (id === 'TX' ? c.oil + ' · ' + c.gas : '—')],
        ['Horizontal', (c, id) => num(c.horizontal) + (id === 'TX' ? (c.initial ? ' · ' + Math.round((c.horizontal / c.initial) * 100) + '% of first tests' : '') : (c.filed ? ' · ' + pctOf(c.horizontal, c.filed) + ' of filings' : ''))],
        ['Filed after first production, median', (c, id) => (id === 'OK' && c.lag ? pl(c.lag.median, 'day') : '—')], ['Operators', (c) => num(c.operatorCount)]];
      kids.push(table([{ t: 'By state' }, ...S.states.map((id) => ({ t: sname(id) }))], rows.map(([label, fn]) => [label, ...S.states.map((id) => cell(id, (c) => fn(c, id)))]), { cap: 'dr-table flat' }));
    }
    // the best first tests of the states shown, largest oil rate first
    const tests = [];
    items.forEach(({ id, c }) => {
      if (id === 'TX') c.topTests.forEach((t) => tests.push({ id, oil: t.rate, county: t.county, horizontal: t.horizontal, operator: t.operator, extra: 'District ' + t.district }));
      else c.tests.forEach((t) => tests.push({ id, oil: t.oil || 0, gas: t.gas, county: t.county, horizontal: t.horizontal, operator: t.operator }));
    });
    tests.sort((a, b) => (b.oil || 0) - (a.oil || 0) || (b.gas || 0) - (a.gas || 0));
    if (tests.length) {
      kids.push(el('div', { class: 'dr-tests' }, tests.slice(0, 4).map((t, i) => el('div', { class: 'dr-test' },
        el('small', { text: i === 0 ? 'Best first test' : 'Test #' + (i + 1) }), el('b', { text: num(t.oil || t.gas) }), el('span', { text: t.oil ? 'bbl of oil a day' : 'mcf of gas a day' }),
        el('small', { text: t.county + ' County' + (multi() ? ', ' + t.id : '') + (t.extra ? ' · ' + t.extra : '') + (t.horizontal ? ' · horizontal' : '') + (t.oil && t.gas ? ' · ' + num(t.gas) + ' mcf of gas' : '') + (t.operator ? ' · ' + t.operator : '') })))));
    }
    kids.push(byState(items, ({ id, c }) => (id === 'TX'
      ? [[el('h3', { text: 'Why they were filed' }), stack(c.purpose.map(([k, n]) => ({ label: k, value: n })))], [el('h3', { text: 'Kinds of first test' }), stack(c.ctype.map(([k, n]) => ({ label: k, value: n })))],
        [el('h3', { text: 'Forms in approved packets' }), rankList(c.forms.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s3)' })],
        [el('h3', { text: 'RRC districts' }), rankList(c.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s3)' })]]
      : [[el('h3', { text: 'Kinds of well' }), stack(c.types.map(([k, n]) => ({ label: k, value: n })))],
        [el('h3', { text: 'Formations' }), c.formations.length ? rankList(c.formations.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s3)' }) : el('p', { class: 'fine', text: 'No formation is named on these filings.' })]])));
    kids.push(colsOf(['Counties', 'Operators'], counties(items.map(({ id, c }) => ({ id, rows: c.counties })), 'var(--s3)'), operators(items.map(({ id, c }) => ({ id, rows: c.operators })), 'var(--s3)')));
    const sub = items.length > 1 ? 'Texas: forms (W-2, G-1, P-4, L-1, G-5, G-10, P-15, W-12) submitted or approved that day. Oklahoma: completion forms (1002A) filed that day, each well counted once per filing day. The two are counted differently, so they are shown side by side as well as added.'
      : items[0].id === 'TX' ? 'Forms submitted or approved that day: W-2 (oil), G-1 (gas), P-4, L-1, G-5, G-10, P-15 and W-12.' : 'Completion forms (1002A) filed that day. The file holds a row for every casing string and test, so each well is counted once per filing day; amended filings are counted apart.';
    return card('dr-sec', head('drop', 'Completions', 'Completions ' + [...new Set(items.map((x) => fmtDow(x.c.day)))].join(' and '), sub), ...kids);
  }

  function healthSection() {
    const reps = S.states.filter((id) => S.reps[id]);
    const chipFor = (d) => (d.error ? chip('bad', 'Error') : d.absent ? chip('quiet', 'Live days only') : d.state === 'new' ? chip('good', 'Updated') : d.state === 'same' ? chip('warn', 'No change') : d.state === 'first' ? chip('quiet', 'First capture') : chip('quiet', 'Reconstructed'));
    const rows = reps.flatMap((id) => S.reps[id].datasets.map((d) => [el('span', { class: 'dr-dsname' }, icon(ICONS[id][d.id], 15), (multi() ? sname(id) + ' · ' : '') + TITLES[id][d.id]), d.cadence ? el('span', { title: d.cadence, text: d.cadence.replace(/,.*$/, '') }) : '—',
      d.dataDay ? fmtMd(d.dataDay) : '—', d.file ? el('code', { text: d.file.name }) : '—', d.file ? listed(d.file.modified) : '—', d.file && d.file.bytes != null ? mb(d.file.bytes) : '—', d.files != null ? num(d.files) : '—', chipFor(d)]));
    const kids = [];
    if (rows.length) kids.push(table([{ t: 'Dataset' }, { t: 'Commission says' }, { t: 'Data day' }, { t: 'Newest file' }, { t: 'Listed' }, { t: 'Size', num: true }, { t: 'Files on share', num: true }, { t: 'Status' }], rows, { cap: 'dr-table flat' }));
    else kids.push(el('p', { class: 'empty', text: 'No report was loaded for this day.' }));
    const tag = (id) => (multi() ? sname(id) + ': ' : '');
    for (const id of reps) {
      const rep = S.reps[id]; const c = rep.catalog;
      if (rep.kind !== 'live' || !c) continue;
      kids.push(el('p', { class: 'fine', text: id === 'TX'
        ? tag(id) + 'The RRC page lists ' + c.datasets + ' data sets; ' + c.nightly.length + ' are nightly or twice daily' + (c.unknown.length ? '. New nightly sets this report does not read: ' + c.unknown.join('; ') + '.' : ', the same ones this report reads.')
        : tag(id) + 'The Commission\'s data page lists ' + c.nightly.length + ' files it refreshes daily or nightly; this report reads the ' + rep.datasets.length + ' that carry drilling and well activity' +
          (c.unknown.length ? '. New ones it does not read: ' + c.unknown.join('; ') + '.' : '. The rest are master copies of the same records, a map copy of the well file, an incident list that runs weeks behind and contact lists this site does not use.') }));
    }
    const tm = S.reps.TX;
    if (tm && tm.kind === 'live' && tm.monthly) {
      kids.push(el('h3', { class: 'dr-h3-gap', text: 'Monthly files the site is built from (Texas)' }),
        table([{ t: 'File' }, { t: 'Newest on the RRC share' }, { t: 'Listed' }, { t: 'Site built from' }, { t: 'Status' }],
          tm.monthly.map((m) => [m.title, m.file ? el('code', { text: m.file }) : '—', listed(m.modified), m.siteBuilt || '—', m.error ? chip('bad', 'Not read') : m.newer ? chip('bad', 'Newer file waiting') : m.siteBuilt ? chip('good', 'Current') : chip('quiet', 'Not tracked')]), { cap: 'dr-table flat' }),
        el('p', { class: 'fine', text: 'The site\'s county, operator and company tables come from these monthly files. When a newer one appears, those tables are due for a rebuild; the daily report above does not depend on it.' }));
    }
    const allLive = reps.length > 0 && reps.every((id) => S.reps[id].kind === 'live');
    return card('dr-sec', head('check', 'Source health', 'Is everything arriving?', allLive ? 'What each file looked like when it was read.' : 'Days not captured live were rebuilt from the commissions\' file history, so file times are not available for them.'), ...kids);
  }

  // one cell per calendar day. Permits sit on the day they were issued and open the next report, which shows them; every other
  // figure sits on the report day that shows it.
  const METRICS = {
    permits: { label: 'New-drill permits issued', fmt: (v) => num(v) + ' new-drill permits issued', none: 'No permits issued (weekend or holiday)' },
    pending: { label: 'Waiting for approval · Texas', need: 'TX', get: (e) => (e.r.TX ? e.r.TX.q : null), fmt: (v) => num(v) + ' applications waiting', none: 'No pending set recorded' },
    completions: { label: 'Completions', get: completionsOf, fmt: (v) => num(v) + ' completions', none: 'No completion data' },
    transfers: { label: 'Wells changing operator · Oklahoma', need: 'OK', get: (e) => (e.r.OK ? e.r.OK.t : null), fmt: (v) => num(v) + ' wells changed operator', none: 'No transfers on file for this day' },
    volume: { label: 'Image pack volume · Texas', need: 'TX', get: (e) => (e.r.TX ? e.r.TX.vol : null), fmt: (v) => Math.round(v) + ' MB of image packs', none: 'No pack sizes read' },
  };
  const metrics = () => Object.entries(METRICS).filter(([, m]) => !m.need || S.states.includes(m.need));
  function calCells(id) {
    const byDay = new Map(S.days.map((e) => [e.d, e]));
    if (id === 'permits') {
      const ss = S.states.map((s) => S.series[s]).filter((s) => s && s.lo);
      if (!ss.length) return [];
      const lo = ss.map((s) => s.lo).sort()[0]; const hi = ss.map((s) => s.hi).sort().pop(); const cells = [];
      for (let d = lo; d <= hi; d = addDays(d, 1)) {
        const vs = ss.map((s) => s.get(d)).filter(Boolean); const v = sumOf(vs.map((x) => x.n));
        const next = addDays(d, 1); const e = byDay.get(next);
        cells.push({ d, v: v > 0 ? v : null, open: e ? next : null, live: !!e && e.live });
      }
      return cells;
    }
    return S.days.map((e) => ({ d: e.d, v: METRICS[id].get(e), open: e.d, live: e.live }));
  }

  function archiveSection() {
    const days = S.days;
    const host = el('div', { class: 'dr-cal-host' });
    if (!metrics().some(([id]) => id === S.metric)) S.metric = 'permits';
    const paint = () => {
      const m = METRICS[S.metric]; const cells = calCells(S.metric);
      host.replaceChildren(cells.length > 1 ? calendar({ cells, selected: S.day, label: m.label + ' by day', format: m.fmt, none: m.none, onPick: (d) => { go(d, S.mode); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }); } }) : el('p', { class: 'empty', text: 'Nothing to show yet.' }),
        el('p', { class: 'fine', text: 'Paler is lower, deeper is higher. Select a day to open its report. Permits sit on the day they were issued and open the next day\'s report; every other figure sits on the report that shows it. Bordered days were captured live; the rest were rebuilt from the commissions\' file history.' }));
    };
    const seg = segmented({ label: 'Calendar figure', options: metrics().map(([id, m]) => ({ id, label: m.label })), value: S.metric, tabs: false, prefix: 'drc', onChange: (id) => { S.metric = id; paint(); } });
    paint();
    return card('dr-sec', head('calendar', 'Archive', 'Every day, three months', 'Pick a figure and a day. ' + days.length + ' reports from ' + fmtMd(days[0].d) + ' to ' + fmtMd(days[days.length - 1].d) + '.'), el('div', { class: 'dr-maptools' }, seg.el), host);
  }

  function notesSection() {
    const li = (...k) => el('li', {}, ...k);
    const T = S.states.includes('TX'); const O = S.states.includes('OK'); const N = S.states.includes('NM');
    const items = [];
    items.push(li(strong('What a day shows. '), 'A report holds what each commission published, and each card says which day its data is from. ' + (T ? 'Texas: what landed on the RRC file share that day, Central time, judged by the time the share lists. Pending sets: the previous evening\'s 5 PM set, which is copied after midnight, and the day\'s 11 AM set. Completions and the image packs are posted the next morning (about 2:20 AM for completions and completion images, 7:55 for surveys, 10:20 for W-1 images), so a report shows the day before\'s, and a day on which nothing landed shows nothing (there is no W-1 pack for a weekend, so Sunday and Monday have none). Permits are the newest issue date before the day. ' : '') + (O ? 'Oklahoma: the newest day before the report on which the Commission\'s files hold anything, so Monday\'s report shows Friday\'s approvals, filings and transfers. Only whole days are shown: the Commission\'s daily files are made around 7:40 PM Central and end the day before, and a report captured before that evening\'s files exist fills the gap from the Commission\'s master files.' : '')
      + (N ? (T || O ? ' ' : '') + 'New Mexico: the newest day before the report on which the Oil Conservation Division\'s well layer holds a permit approval, so Monday\'s report shows Friday\'s. The layer is entered some days after an approval, so the newest days run low and fill in.' : '')));
    if (multi()) {
      const pair2 = S.states.length === 2 && T && O;
      items.push(li(strong(S.states.length === 2 ? 'Both states together. ' : 'The states together. '), pair2
        ? 'Permits and completions are added across the states; everything is also shown by state, because the files differ. Texas says which permits are horizontal and Oklahoma only gives planned depth, so those two are never added. Texas counts completion forms approved that day, Oklahoma counts completion filings (one per well and day), so the total is a count of completion paperwork, not of wells. Two states can show different permit days on the same report (a state with no approvals on a day shows the one before). A county is always named with its state, because the two states share county names. If a state has no report for a day, that is said at the top and it is left out of every total, chart and average on the page, not counted as zero.'
        : 'Permits are added across the states' + (T || O ? ' and so are completions, where a state has them' : '') + '; everything is also shown by state, because the files differ. Texas and New Mexico say which permits are horizontal and Oklahoma only gives planned depth, so those are never added. '
          + (T && O ? 'Texas counts completion forms approved that day, Oklahoma counts completion filings (one per well and day), so the total is a count of completion paperwork, not of wells. ' : '')
          + 'The states can show different permit days on the same report (a state with no approvals on a day shows the one before). A county is always named with its state, because the states share county names. If a state has no report for a day, that is said at the top and it is left out of every total, chart and average on the page, not counted as zero.'));
    }
    items.push(li(strong('Rebuilt days. '), 'Days marked reconstructed were rebuilt by the same rule from the commissions\' file history' + (T ? ' (Texas: permits from the month-end and nightly files, completions, image packs and pending sets from what had landed on the share that day' + (O ? '; ' : ')') : '') + (O ? (T ? '' : ' (') + 'Oklahoma: the master files of intents to drill and completions, and the transfer file for as far back as it goes, about a month. Its well inventory cannot be rebuilt: only days captured live have it)' : '') + '.' + (N ? ' New Mexico\'s rebuilt days count the approvals still in status New, so an older day can have lost a few that were cancelled or moved on.' : '') + ' The catalog check and file states only exist for days captured live.'));
    if (T) {
      items.push(li(strong('Texas permits. '), 'New-drill means application type 01, counted once per permit number, the same rule as the rest of this site. Monthly totals here match the site\'s own monthly series to within one permit. GPS points come from the Railroad Commission\'s public map service (its Well Locations layer, matched by API number), so a permit can have none until the RRC maps it.'));
      items.push(li(strong('Texas pending queue. '), 'Each set holds W-1s submitted since the previous run that were still waiting; it is not a running total, and a permit leaves it when approved.'));
    }
    if (N) {
      items.push(li(strong('New Mexico permits. '), 'A permit to drill is a well in status New in the Oil Conservation Division\'s well layer, counted once on the day it was approved (the layer\'s effective date); every one is for a new well. The Division publishes no filing date, planned depth, amendment, completion or transfer by day, so the report shows none of them rather than a zero. The layer is entered some days after an approval: the newest two or three days run low (against 17 to 22 a business day in the weeks before) and fill in, which is why the pace chart is rewritten from the layer each night. A well leaves status New when it is cancelled or moves on, so a rebuilt day can have lost a few.'));
      items.push(li(strong('New Mexico well inventory. '), 'The Division\'s well layer has a record for every well, about 142,000, most of them plugged, cancelled or never drilled. The server counts them by status and, for the wells with status Active, by kind, county and operator; nothing is listed. Only days captured live have it: the layer holds the current inventory only.'));
    }
    if (O) {
      items.push(li(strong('Oklahoma permits. '), 'New-drill means application type DR with an approval date; rejected and deleted applications are left out. Times in the files are UTC and are turned into Central days. The file does not say which permits are horizontal, so the report shows planned depth instead and calls a well planned to 12,000 feet or more deep (about three in four of the new-drill permits in this archive). Oklahoma approves far fewer permits a day than Texas (about 3 against 31), so single days swing a lot; read the averages.'));
      items.push(li(strong('Oklahoma completions and transfers. '), 'The completion file holds a row for every casing string and test. Rows are folded to one filing per well and day, and amended filings are counted apart. A filing is dated by the day it was created. A transfer counts a well whose operator changed; one sale can move hundreds of wells in a day.'));
      items.push(li(strong('Oklahoma well inventory. '), 'The nightly well file has a record for every well ever drilled in the state, about 457,000, most of them plugged. Active wells are the ones with status AC. It is counted, never listed.'));
    }
    items.push(li(strong('Times. '), 'File times are shown as the share lists them (Central). The report date is the Central-time day the capture ran.'));
    items.push(li(strong('Privacy. '), 'Operators are named only when they are corporations, LLCs or limited partnerships, and this site\'s own pages leave out lease names, well numbers, API numbers and anything about individuals' + (O ? '; the Oklahoma Commission\'s operator, purchaser and plugger contact lists are not read' : '') + '.' + (T ? ' One deliberate exception: each Texas drill\'s page links to the Railroad Commission\'s scanned W-1 letter, plat and directional survey, published unmodified as GitHub release files. They are public records and can carry the names, phone numbers and addresses of individuals; nothing is redacted. Completion images stay blurred and unpublished.' : '')));
    return card('dr-sec dr-notes', head('bulb', 'How to read this', 'Notes and limits'), el('ul', { class: 'plain' }, items));
  }

  /* ---------- page ---------- */
  function render() {
    const ae = document.activeElement;
    const keep = ae && root.contains(ae) ? (ae.id || (ae.dataset && ae.dataset.act) || null) : null;
    const rtx = S.reps.TX;
    S.open = null; S.gpsEl = null; // set again by the GPS card when it is on the page
    const gps = rtx ? tx.gpsCard(rtx) : null;
    const kids = [hero(), ribbonCard(), kpiRow(), el('div', { class: 'dr-grid2' }, el('div', { class: 'dr-col' }, trendCard(), storyCard()), mapCard()), gps, contextCard(), statusStrips()];
    if (S.mode === 'simple') {
      kids.push(el('p', { class: 'dr-more' }, el('button', { type: 'button', class: 'btn', onclick: () => go(S.day, 'full') }, 'Open the verbose report', icon('arrow', 15))));
    } else {
      // a state that publishes no completions (New Mexico) has no completions card of its own: when it is the only one shown there is nothing to say
      kids.push(permitsSection(), rtx ? tx.pendingSection(rtx) : null, S.states.some((id) => id !== 'NM') ? completionsSection() : null, S.reps.OK ? transfersSection(S.reps.OK) : null, S.reps.OK ? wellsSection(S.reps.OK) : null, S.reps.NM ? wellsSection(S.reps.NM) : null,
        rtx ? tx.imagesSection(rtx) : null, rtx ? tx.packPagesSection(rtx) : null, healthSection(), archiveSection(), notesSection());
    }
    const nodes = kids.filter(Boolean);
    nodes.forEach((n, i) => n.style.setProperty('--d', String(Math.min(i, 9))));
    root.replaceChildren(...nodes);
    if (S.rb) S.rb.mark(S.day);
    if (keep) { const t = root.querySelector('[data-act="' + keep + '"]') || document.getElementById(keep); if (t && !t.disabled) t.focus({ preventScroll: true }); }
  }

  async function show(day) {
    const seq = ++S.seq;
    S.day = day;
    // a state is asked for the report only when its index lists the day; undefined means it has none, null that loading it failed
    const got = await Promise.all(S.states.map((id) => (S.idx[id].days.some((r) => r.d === day) ? loadOpt(stateOf(id).dir + '/' + day) : Promise.resolve(undefined))));
    if (seq !== S.seq) return;
    S.reps = {}; S.miss = {};
    S.states.forEach((id, i) => { if (got[i]) S.reps[id] = got[i]; else S.miss[id] = got[i] === undefined ? 'none' : 'error'; });
    if (!Object.keys(S.reps).length) { root.replaceChildren(h1, el('p', { class: 'empty', text: 'That day\'s report could not be loaded. Reload the page to try again.' })); return; }
    render();
    if (S.sel && S.gpsEl) requestAnimationFrame(() => S.gpsEl.scrollIntoView({ block: 'start', behavior: 'auto' })); // a shared drill link opens on its page
    document.title = fmtLong(day).replace(/, \d{4}$/, '') + ' · Daily report · Oil tracker';
    const i = S.days.findIndex((e) => e.d === day);
    [i - 1, i + 1].forEach((k) => { if (S.days[k]) S.states.forEach((id) => { if (S.days[k].r[id]) loadOpt(stateOf(id).dir + '/' + S.days[k].d); }); });
  }

  function go(day, mode) {
    S.mode = mode;
    if (day !== S.day) S.sel = null; // a drill belongs to its day; switching between the simple and verbose report keeps it
    const hash = hashFor(day, mode, S.sel);
    if (location.hash !== hash) history.pushState(null, '', hash);
    return show(day);
  }

  // the states shown (the site-wide choice in the bar above the page): both states, or one. The days listed are the days those states
  // have, so the selected day stays when it is still there
  function applyStates(ids) {
    const next = S.avail.filter((id) => ids.includes(id));
    if (!S.ready || !next.length || next.join() === S.states.join()) return Promise.resolve();
    S.states = next; setDays(); useShapes();
    if (!S.states.includes('TX')) S.sel = null;
    const day = S.days.some((e) => e.d === S.day) ? S.day : latest();
    const hash = hashFor(day, S.mode, S.sel);
    if (location.hash !== hash) history.replaceState(null, '', hash);
    return show(day);
  }

  return {
    setStates: applyStates,
    available: () => S.avail.slice(), // the states that have a Daily report
    async activate(params) {
      if (!S.ready) {
        try { await boot(); } catch (e) {
          h1.textContent = 'Daily report';
          root.replaceChildren(h1, el('p', { class: 'empty', text: 'The daily report has no data yet. It appears after the first nightly capture.' }));
          return;
        }
      }
      const dr = params.get('drill'); const sv = params.get('survey');
      S.sel = dr && /^\d{7}$/.test(dr) ? { t: 'p', id: dr } : sv && /^\d{1,12}$/.test(sv) ? { t: 's', id: sv } : null;
      let want = activeStates().filter((id) => S.avail.includes(id)); // the router has set the choice from the address
      if (!want.length) want = S.avail.slice(); // none of the states chosen has a Daily report: show those that have (the bar says so)
      else if (S.sel && S.avail.includes('TX') && !want.includes('TX')) { // a well is a Texas one: show Texas with it
        want = S.avail.slice(); setGlobalStates(activeStates().includes('NM') ? STATES.map((x) => x.id) : want, true);
      }
      S.states = want; setDays(); useShapes();
      const d = params.get('d');
      S.mode = params.get('v') === 'full' ? 'full' : 'simple';
      await show(S.days.some((e) => e.d === d) ? d : latest());
    },
  };
}
