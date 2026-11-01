// The Daily report: the new wells of one day, nationwide. Pick a day (the chart, the slider, the arrows or the date box) and see that day's wells on the map, which states they are in,
// how it compares with a typical day, and every well in a table; below, who reported lately. The chart and the slider show 150 days; "Earlier" and "Later" page through them, back to
// January 2011 (the earlier wells, about 2 MB, are fetched the first time a day before the last two years is asked for). Everything is drawn from data/newwells/ (FracFocus), the one source with the same facts for
// every state that reports to it, so nothing here is a figure only some states have. A well is dated by the day of its first fracturing job; operators disclose weeks to months later, so
// the newest days are still filling in and say so. The permits each agency approves, by its own count, are the National page.
import { $, el, svg, load, loadOpt, fmt, stat, fmtDate, monthLabel, dayLabel, reduced } from './util.js';
import { icon } from './icons.js';
import { showTip, hideTip, tipRow } from './tip.js';
import * as G from './usgeo.js';
import * as D from './newwells-data.js';
import { createUSMap } from './usmap.js';

const put = (node, ...kids) => node.append(...kids.filter((k) => k != null && k !== false));
const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const weekday = (ms) => new Date(ms).toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });
const CHART_DAYS = 150; // the days the chart and the slider show: the newest 150, or the 150 that hold the chosen day
const TABLE_ROWS = 80;
const DAY_MS = 864e5;
const MIN_BUSY = 10; // the day the report opens on: the newest with at least this many wells (the newest days have only a few so far)

export function createDailyView({ root }) {
  let dt = null; let raw = null; let started = false; let day = 0; let sel = null; let map = null; let seq = 0; let busy = false;
  const S = {};

  async function data() {
    if (dt) return dt;
    const [doc, pts, out, nat, arrivals, tx, ok, nm] = await Promise.all([load('newwells/summary'), load('newwells/points'), load('us-states'), loadOpt('national'), loadOpt('newwells/arrivals'), loadOpt('daily/index'), loadOpt('daily-ok/index'), loadOpt('daily-nm/index')]);
    raw = { doc, pts, nat, arrivals, reports: { TX: tx, OK: ok, NM: nm }, outlines: G.buildOutlines(out) };
    dt = makeDt(D.decode(pts), false);
    return dt;
  }
  // the days the report works on: the last two years (full false) or every day since 2011 (full true: the earlier wells merged in, day numbers counted from Jan 1, 2011)
  function makeDt(P, full) {
    const { doc, outlines, nat } = raw;
    return { doc, P, outlines, nat, full, settledDay: D.dayOfIso(P, doc.settled), T: D.totals(doc), start: D.lastBusyDay(P, MIN_BUSY) };
  }
  async function loadFull() {
    if (dt.full) return;
    dt = makeDt(D.decode(D.mergePoints(raw.pts, await load('newwells/points-history'))), true);
  }
  const firstMs = () => Date.parse(raw.doc.months[0] + '-01T00:00:00Z'); // the series' first day: the date box and the arrows go back this far
  const winMax = () => Math.max(0, dt.P.span - CHART_DAYS + 1);
  const clampWin = (f) => Math.min(winMax(), Math.max(0, Math.round(f)));
  const allowed = (id) => { const s = id && D.byId(dt.doc, id); return !!s && (dt.full ? D.drilled(s) : s.p12 > 0); };
  const ms = (d) => D.dayMs(dt.P, d);
  const iso = (d) => D.dayIso(ms(d));
  // wells of a day (indexes), the chosen state's only when one is chosen
  function wellsOf(d) {
    const { P } = dt; const si = sel ? P.states.indexOf(sel) : -1; const out = [];
    for (let i = D.firstAtOrAfter(P, d); i < P.n && P.day[i] === d; i++) if (si < 0 || P.s[i] === si) out.push(i);
    return out;
  }
  const typ = () => D.typicalDay(dt.doc, iso(day), sel); // wells a day in the 12 months the chosen day sits in, for all states or the chosen one

  /* ---------- the address: #daily?d=2026-08-12&s=TX ---------- */
  function writeHash() {
    const p = new URLSearchParams();
    p.set('d', iso(day)); if (sel) p.set('s', sel);
    const next = '#daily?' + p.toString();
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ---------- the four figures ---------- */
  function figures() {
    const { doc, P } = dt; const last30 = D.perState(P, P.span - 29, P.span); const n30 = last30.reduce((t, x) => t + x.n, 0);
    const newest = wellsOf(P.span).length;
    const tiles = [
      { label: 'Newest well', value: fmtDate(doc.asOf).replace(/, \d{4}$/, ''), note: newest + (newest === 1 ? ' well' : ' wells') + ' that day so far: operators disclose weeks late' },
      { label: 'A typical day', value: (dt.T.p12 / 365).toFixed(1), note: 'wells a day over the 12 settled months to ' + monthLabel(doc.settled.slice(0, 7)) },
      { label: 'Wells in the newest 30 days', value: fmt.format(n30), note: 'in ' + last30.length + ' states so far; this number grows as they are disclosed' },
      { label: 'Newest settled day', value: fmtDate(doc.settled).replace(/, \d{4}$/, ''), note: 'days after it are still filling in' },
    ];
    return el('dl', { class: 'dr-tiles nat-kpis' }, tiles.map((x) => el('div', { class: 'dr-tile' }, el('dt', { text: x.label }), el('dd', { text: x.value }), el('small', { text: x.note }))));
  }

  /* ---------- the day: the map, its summary and the controls ---------- */
  function summary() {
    const { doc, P } = dt; const box = el('div', { class: 'nat-panel', 'aria-live': 'polite' });
    const idx = wellsOf(day); const n = idx.length; const late = day > dt.settledDay;
    const sName = sel ? (D.byId(doc, sel) || {}).name : null;
    put(box, el('div', { class: 'nat-ph' }, el('h3', { text: weekday(ms(day)) + ', ' + dayLabel(ms(day)) }), el('span', { class: 'badge', text: late ? 'Still filling in' : 'Settled' })),
      el('p', { class: 'nat-agency', text: (sName || 'All states') + ' · counted by the day of the first job' }),
      el('div', { class: 'nat-big' }, el('strong', { text: fmt.format(n) }), el('span', { text: n === 1 ? ' new well' : ' new wells' })));
    const t = typ(); const tp = t.perDay; const then = n > tp * 1.5 ? '; this one is busier.' : n < tp * 0.5 ? '; this one is quieter.' : '; this one is about typical.';
    put(box, el('p', { class: 'fine', text: late
      ? 'A typical settled day has about ' + tp.toFixed(1) + '. This day is still being disclosed, so its count will rise: do not read it as a slow day.'
      : t.latest ? 'A typical day over the last 12 settled months has about ' + tp.toFixed(1) + then
        : 'A typical day in the 12 months ' + monthLabel(t.from) + ' to ' + monthLabel(t.to) + ' had about ' + tp.toFixed(1) + then }));
    if (!sel) {
      const rows = D.perState(P, day, day).slice(0, 8);
      if (rows.length) {
        const top = rows[0].n;
        put(box, el('div', { class: 'nat-list dd-by' }, el('h4', { text: 'By state' }), el('ul', {}, rows.map((r) => {
          const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(r.n / top)); bar.style.setProperty('--c', D.colorOf(r.id));
          const name = (D.byId(doc, r.id) || {}).name || r.id;
          return el('li', {}, el('button', { type: 'button', class: 'link nat-ln', text: name, title: 'Show only ' + name, onclick: () => choose(r.id) }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: fmt.format(r.n) }));
        }))));
      }
    }
    const land = idx.filter((i) => P.f[i]).length;
    if (n) put(box, el('p', { class: 'fine', text: fmt.format(land) + ' of the ' + fmt.format(n) + (n === 1 ? ' well is' : ' wells are') + ' on federal or tribal land. Hover a dot for its well.' }));
    else put(box, el('p', { class: 'nd', text: 'No well had its first job this day in the registry' + (late ? ' yet.' : '.') + ' It is shown as none, not as a figure the registry lacks.' }));
    return box;
  }
  function paintDay() {
    const lo = Math.max(0, day - 13);
    const moved = followDay();
    map.setRange(lo, day);
    S.summary.replaceChildren(summary());
    S.date.textContent = weekday(ms(day)) + ', ' + dayLabel(ms(day));
    if (moved) drawChart(); else drawMarker();
    syncSlider();
    S.dateInput.value = iso(day);
    S.prev.disabled = ms(day) <= firstMs(); S.next.disabled = day >= dt.P.span;
    drawTable(); S.chips.forEach((b, id) => b.setAttribute('aria-pressed', String(id === sel))); if (S.pick) S.pick.value = sel || '';
  }
  // the chart and the slider hold 150 days: they stay while the chosen day is inside them and move to the 150 around it when it is not
  function followDay() {
    if (day >= S.win && day <= S.win + CHART_DAYS - 1) return false;
    S.win = clampWin(day - Math.floor(CHART_DAYS / 2)); return true;
  }
  function syncSlider() {
    const hi = Math.min(dt.P.span, S.win + CHART_DAYS - 1);
    S.range.min = String(S.win); S.range.max = String(hi); S.range.value = String(day);
    S.range.style.setProperty('--p', (((day - S.win) / Math.max(1, hi - S.win)) * 100).toFixed(2) + '%');
  }
  function setDay(d, { fromHash = false } = {}) {
    day = Math.min(dt.P.span, Math.max(0, Math.round(d)));
    paintDay(); if (!fromHash) writeHash();
  }
  // a day given in milliseconds: a day before the last two years first fetches the earlier wells (and the page is built again over them, keeping the day, the state and the chart's place)
  async function goTo(target, focusKey = null, fromHash = false) {
    if (target < dt.P.t0 && !dt.full && !(await widen(focusKey))) return;
    setDay((target - dt.P.t0) / DAY_MS, { fromHash });
  }
  // a page of the chart: the chart and the day move 150 days together
  async function page(dir) {
    const step = dir * CHART_DAYS * DAY_MS; const winMs = ms(S.win) + step; const dayMs = ms(day) + step;
    if (dayMs < dt.P.t0 && !dt.full && !(await widen(dir < 0 ? 'earlier' : 'later'))) return;
    S.win = clampWin((winMs - dt.P.t0) / DAY_MS);
    setDay((dayMs - dt.P.t0) / DAY_MS); drawChart();
  }
  async function widen(focusKey) {
    if (dt.full) return true;
    if (busy) return false;
    busy = true;
    const keepDay = iso(day); const keepWin = iso(S.win);
    if (S.status) S.status.textContent = 'Loading the earlier wells (about 2 MB)…';
    try { await loadFull(); } catch (e) {
      if (S.status) S.status.textContent = 'Could not load the earlier wells. Check the connection and try again.';
      busy = false; return false;
    }
    if (map) map.destroy();
    day = D.dayOfIso(dt.P, keepDay);
    render(D.dayOfIso(dt.P, keepWin));
    if (sel) { const keep = sel; sel = null; choose(keep, { fromHash: true }); }
    setDay(day, { fromHash: true });
    if (focusKey && S[focusKey]) S[focusKey].focus({ preventScroll: true });
    busy = false; return true;
  }
  function choose(id, { fromHash = false } = {}) {
    sel = allowed(id) ? id : null;
    map.select(sel, true);
    drawChart(); paintDay(); if (!fromHash) writeHash();
  }
  function dayCard() {
    const { doc, P, outlines } = dt;
    const canvas = el('canvas', { class: 'nw-canvas', role: 'img', 'aria-label': 'Map of the new wells of the chosen day and the two weeks before it; the table below lists the day\'s wells' });
    const stage = el('div', { class: 'nw-stage' }, canvas);
    map = createUSMap({ canvas, host: stage, outlines, P, doc, interactive: true, glowDays: 1, onSelect: (id) => choose(id) });
    S.prev = el('button', { type: 'button', class: 'btn', 'aria-label': 'The day before', onclick: () => goTo(ms(day) - DAY_MS, 'prev') }, icon('arrow', 16, 'dd-back'));
    S.next = el('button', { type: 'button', class: 'btn', 'aria-label': 'The day after', onclick: () => setDay(day + 1) }, icon('arrow', 16));
    S.date = el('strong', { class: 'dd-date' });
    const dateInput = el('input', { type: 'date', class: 'nw-pick', min: raw.doc.months[0] + '-01', max: doc.asOf, 'aria-label': 'Choose a day' });
    S.dateInput = dateInput;
    dateInput.addEventListener('change', () => { if (dateInput.value) goTo(Date.parse(dateInput.value + 'T00:00:00Z'), 'dateInput'); });
    const newest = el('button', { type: 'button', class: 'btn', onclick: () => setDay(P.span) }, 'Newest day');
    S.pick = el('select', { class: 'nw-pick', 'aria-label': 'Show one state' }, el('option', { value: '', text: 'All states' }), doc.states.filter((s) => (dt.full ? D.drilled(s) : s.p12 > 0)).map((s) => el('option', { value: s.id, text: s.name })));
    S.pick.addEventListener('change', () => choose(S.pick.value || null));
    S.range = el('input', { type: 'range', class: 'tl-range', min: S.win, max: P.span, step: 1, value: P.span, 'aria-label': 'Day, over the ' + CHART_DAYS + ' days of the chart below' });
    S.range.addEventListener('input', () => setDay(+S.range.value));
    S.summary = el('div', { class: 'nat-panel-slot' }); S.status = el('p', { class: 'fine nw-status', role: 'status' });
    S.chips = new Map();
    const keys = el('ul', { class: 'nw-keys', 'aria-label': 'States on the map: choose one to show only it' }, D.stack(doc).series.filter((x) => x.id !== 'other').map((x) => {
      const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', x.color);
      const b = el('button', { type: 'button', class: 'nw-chip', 'aria-pressed': 'false', onclick: () => choose(sel === x.id ? null : x.id) }, sw, x.name);
      S.chips.set(x.id, b); return el('li', {}, b);
    }));
    const card = el('section', { class: 'card nw-explore reveal is-in', 'aria-labelledby': 'dd-h' });
    const head = hdr('The day', 'calendar', 'Where the wells of one day are', 'The chosen day’s wells glow; the two weeks before it are dimmer. Operators disclose weeks to months after a job, so the newest days are still filling in.', el('div', { class: 'card-tools' }, S.pick));
    head.querySelector('h2').id = 'dd-h';
    const nav = el('div', { class: 'dd-nav' }, S.prev, el('div', { class: 'dd-mid' }, S.date, S.range), S.next, dateInput, newest);
    put(card, head, nav, S.status, el('div', { class: 'nw-grid' }, el('div', { class: 'nw-mapcol' }, stage, keys), S.summary));
    return card;
  }

  /* ---------- the days, stacked by state, with the chosen day marked ---------- */
  function chartData() {
    const { doc, P } = dt; const n = Math.min(CHART_DAYS, P.span - S.win + 1); const byState = D.perDayByState(P, S.win, S.win + n - 1);
    const colored = D.stack(doc).series.filter((x) => x.id !== 'other').map((x) => x.id);
    const names = Object.fromEntries(doc.states.map((s) => [s.id, s.name]));
    if (sel) return { series: [{ id: sel, name: names[sel], color: D.colorOf(sel), values: byState.get(sel) || new Array(n).fill(0) }], n };
    const other = new Array(n).fill(0);
    for (const [id, v] of byState) if (!colored.includes(id)) v.forEach((x, i) => { other[i] += x; });
    return { series: [...colored.map((id) => ({ id, name: names[id], color: D.colorOf(id), values: byState.get(id) || new Array(n).fill(0) })), { id: 'other', name: 'Other states', color: D.OTHER_COLOR, values: other }], n };
  }
  function drawChart() {
    const { P } = dt; const cd = chartData(); const W = 720; const H = 230; const L = 40; const R = 6; const T = 10; const B = 26;
    const tot = new Array(cd.n).fill(0); cd.series.forEach((s) => s.values.forEach((v, i) => { tot[i] += v; }));
    const tp = typ(); const { top, ticks } = D.niceTop(Math.max(...tot, tp.perDay * 1.1, 1));
    const slot = (W - L - R) / cd.n; const bw = Math.max(1.5, slot * 0.78); const y = (v) => T + (H - T - B) * (1 - v / top);
    const g = svg('svg', { class: 'nat-chart dd-chart', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'New wells by day, ' + fmtDate(iso(S.win)) + ' to ' + fmtDate(iso(S.win + cd.n - 1)) + ', stacked by state; the days after ' + fmtDate(dt.doc.settled) + ' are still filling in. Use the day slider above, or the table below, to read a day.' });
    ticks.forEach((t) => g.append(svg('line', { class: t === 0 ? 'base' : 'grid', x1: L, x2: W - R, y1: y(t), y2: y(t) }), svg('text', { class: 'ax', x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: stat(t) })));
    const sx = (i) => L + slot * i;
    const settledI = dt.settledDay - S.win;
    if (settledI < cd.n - 1) { const x0 = sx(Math.max(-1, settledI) + 1); g.append(svg('rect', { class: 'nw-late', x: x0.toFixed(1), y: T, width: (W - R - x0).toFixed(1), height: H - T - B }), svg('text', { class: 'ax nw-late-t', x: (x0 + 6).toFixed(1), y: T + 12, text: 'still filling in' })); }
    S.marker = svg('rect', { class: 'dd-marker', y: T, width: Math.max(3, slot).toFixed(1), height: H - T - B });
    for (let i = 0; i < cd.n; i++) {
      let acc = 0; const late = i > settledI;
      cd.series.forEach((s) => { const v = s.values[i]; if (!v) return; const seg = svg('rect', { class: 'nat-bar-seg' + (late ? ' is-late' : ''), x: (sx(i) + (slot - bw) / 2).toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1) }); seg.style.setProperty('--c', s.color); g.append(seg); acc += v; });
      const d = S.win + i; const dm = ms(d);
      if (new Date(dm).getUTCDate() === 1) g.append(svg('text', { class: 'ax', x: sx(i) + slot / 2, y: H - 8, 'text-anchor': 'middle', text: monthLabel(iso(d).slice(0, 7)).replace(/(\w+) (\d{4})/, (a, mo, yr) => mo + ' ’' + yr.slice(2)) }));
      const hit = svg('rect', { class: 'nat-hit', x: sx(i).toFixed(1), y: T, width: slot.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: weekday(dm) + ', ' + dayLabel(dm) }), ...cd.series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name)), tipRow(fmt.format(tot[i]), 'in all'), late ? tipRow('Still filling in', '') : null, tipRow('Click to open this day', '')], e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('click', () => setDay(d));
      g.append(hit);
    }
    g.append(S.marker);
    g.append(svg('line', { class: 'dd-typ', x1: L, x2: W - R, y1: y(tp.perDay), y2: y(tp.perDay) }), svg('text', { class: 'ax', x: W - R - 2, y: y(tp.perDay) - 4, 'text-anchor': 'end', text: 'typical day, ' + tp.perDay.toFixed(0) }));
    const key = el('ul', { class: 'nat-keys nat-chart-keys', 'aria-label': 'States in the chart' }, cd.series.map((s) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', s.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: s.name })); }));
    S.chart.replaceChildren(key, g);
    S.chartData = { cd, slot, L };
    S.chartTitle.textContent = S.win >= winMax() ? 'The last ' + CHART_DAYS + ' days, stacked by state' : 'The ' + CHART_DAYS + ' days from ' + fmtDate(iso(S.win)) + ', stacked by state';
    S.chartNote.textContent = 'The dashed line is a typical day over ' + (tp.latest ? 'the 12 settled months' : 'the 12 months ' + monthLabel(tp.from) + ' to ' + monthLabel(tp.to)) + ' (all states, or the one chosen).';
    S.earlier.disabled = ms(S.win) <= firstMs(); S.later.disabled = S.win >= winMax();
    drawMarker();
  }
  function drawMarker() {
    if (!S.marker || !S.chartData) return;
    const i = day - S.win; const { slot, L } = S.chartData;
    S.marker.setAttribute('x', (L + slot * i - (Math.max(3, slot) - slot) / 2).toFixed(1)); S.marker.style.display = i >= 0 && i <= S.chartData.cd.n - 1 ? '' : 'none';
  }

  /* ---------- the wells of the day, as a table (the map's twin) ---------- */
  function drawTable() {
    const { P, doc } = dt; const idx = wellsOf(day);
    const name = (id) => (D.byId(doc, id) || {}).name || id;
    idx.sort((a, b) => name(D.stateOfPoint(P, a)).localeCompare(name(D.stateOfPoint(P, b))) || (D.countyOf(P, a) || '').localeCompare(D.countyOf(P, b) || ''));
    const shown = idx.slice(0, TABLE_ROWS);
    const body = shown.map((i) => el('tr', {}, el('td', { text: name(D.stateOfPoint(P, i)) }), el('td', { text: D.countyOf(P, i) || '—' }), el('td', { text: D.operatorOf(P, i) || 'Not named' }),
      el('td', { class: 'num', text: D.feet(P.tvd[i]) || '—' }), el('td', { class: 'num', text: D.gallons(P.h2o[i]) || '—' }), el('td', { text: P.f[i] ? D.LAND[P.f[i]].replace(/ land$/, '') : '—' })));
    S.tableHead.textContent = fmt.format(idx.length) + (idx.length === 1 ? ' well' : ' wells') + ' on ' + fmtDate(iso(day)) + (sel ? ' in ' + name(sel) : '');
    // replaceChildren writes the word "null" for a null child, so the empty ones are dropped first
    S.table.replaceChildren(...[idx.length ? el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'The wells of the chosen day' }, el('table', { class: 'grid' },
      el('thead', {}, el('tr', {}, ['State', 'County', 'Operator', 'Depth', 'Water', 'Land'].map((h, k) => el('th', { scope: 'col', class: k === 3 || k === 4 ? 'num' : null, text: h })))), el('tbody', {}, body)))
      : el('p', { class: 'nd', text: 'No well.' }),
    idx.length > TABLE_ROWS ? el('p', { class: 'fine', text: 'The first ' + TABLE_ROWS + ' of ' + fmt.format(idx.length) + ' are listed; choose a state to see its own.' }) : null,
    el('p', { class: 'fine', text: 'Operators are named only when they are corporations, LLCs or partnerships. No API number, well name or lease is published.' })].filter(Boolean));
  }

  /* ---------- who reported lately ---------- */
  /* ---------- fractured wells found and oil well permits approved, day by day: two different things, marked, never added ---------- */
  const mark = (kind) => el('i', { class: 'mk mk-' + kind, 'aria-hidden': 'true' });
  function arrivals() {
    const a = raw.arrivals; if (!a) return null;
    const rows = D.arrivalRows(a, raw.reports, 14); const nameOf = (id) => (D.byId(raw.doc, id) || {}).name || id;
    const against = (a.against || {}).TX;
    const states = (r) => r.byState.slice(0, 4).map((s) => nameOf(s.id) + ' ' + fmt.format(s.n)).join(', ') + (r.byState.length > 4 ? ' and ' + (r.byState.length - 4) + ' more' : '');
    const head = ['Day', [mark('frac'), 'Fractured wells found (FracFocus)'], [mark('oil'), 'Oil well permits approved (state agencies)'], [mark('both'), 'The same well in both']];
    const table = el('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Fractured wells found and oil well permits approved, by day' }, el('table', { class: 'grid dd-tbl dd-arr' },
      el('thead', {}, el('tr', {}, head.map((h, k) => el('th', { scope: 'col', class: k > 1 ? 'num' : null }, ...[].concat(h).map((x) => (typeof x === 'string' ? document.createTextNode(x) : x)))))),
      el('tbody', {}, rows.map((r) => el('tr', {},
        el('th', { scope: 'row', text: fmtDate(r.day).replace(/, \d{4}$/, '') }),
        el('td', { title: r.fractured == null ? 'Not compared yet: the comparison with the last download began on ' + (a.since ? fmtDate(a.since) : 'the next download') : null }, r.fractured == null ? '—' : [fmt.format(r.fractured), r.byState.length ? el('small', { class: 'dd-sub', text: ' ' + states(r) }) : null].filter(Boolean)),
        el('td', { class: 'num', title: r.oil.length ? r.oil.map((o) => nameOf(o[0]) + ': ' + o[1] + (o[2] ? ' approved ' + fmtDate(o[2]) : '')).join('; ') : 'No report kept for this day' }, r.oilTotal == null ? '—' : [fmt.format(r.oilTotal), el('small', { class: 'dd-sub', text: ' ' + r.oil.map((o) => o[0] + ' ' + o[1]).join(' · ') })]),
        el('td', { class: 'num', title: r.both == null ? 'Not compared yet' : 'Texas only: its daily report lists wells by API number' }, r.both == null ? '—' : fmt.format(r.both)))))));
    const note = [
      a.since ? 'Compared with the list of wells kept from the last download, from ' + fmtDate(a.since) + '. A well found here is a first disclosure that was not in that list, whatever its job date: a late disclosure counts on the day it arrives.'
        : 'The comparison begins with the next download: the first one was kept as the baseline, so no day is counted yet.',
      against ? 'Texas’s daily reports are matched by API number (' + fmt.format(against.wells) + ' wells' + (against.from ? ', from ' + fmtDate(against.from) : '') + '): days before the nightly captures were rebuilt without API numbers, and a well is usually fractured months after its permit, so few match at first.' : null,
      'Oklahoma’s and New Mexico’s daily reports give counts, not wells, so their wells cannot be checked against them, and the column says nothing about them. Fractured wells and oil well permits are different things (a permit is the right to drill; a fracturing job comes after) and are never added together.',
    ].filter(Boolean);
    const card = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'dd-arr-h' },
      hdr('New in the registry', 'layers', 'Fractured wells found each day, beside the oil well permits', 'The wells FracFocus’s download added since the day before, and the oil well permits each state agency approved in the report it published that day.'), table,
      el('p', { class: 'fine' }, el('span', { class: 'dd-key' }, mark('frac'), 'Fractured well (FracFocus)'), el('span', { class: 'dd-key' }, mark('oil'), 'Oil well permit (state agency)'), el('span', { class: 'dd-key' }, mark('both'), 'The same well, in both')),
      ...note.map((t) => el('p', { class: 'fine', text: t })));
    card.querySelector('h2').id = 'dd-arr-h';
    return card;
  }
  function lately() {
    const { doc, P } = dt;
    const rows = D.active(doc).map((s) => ({ s, n30: D.perState(P, P.span - 29, P.span).find((x) => x.id === s.id) })).sort((a, b) => b.s.latest.localeCompare(a.s.latest) || b.s.p12 - a.s.p12);
    const table = el('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'When each state last reported a well' }, el('table', { class: 'grid dd-tbl' },
      el('thead', {}, el('tr', {}, ['State', 'Newest well', 'Days behind the newest', 'Wells in the newest 30 days', 'Last 12 settled months'].map((h, k) => el('th', { scope: 'col', class: k > 1 ? 'num' : null, text: h })))),
      el('tbody', {}, rows.map(({ s, n30 }) => el('tr', {}, el('th', { scope: 'row' }, el('button', { type: 'button', class: 'link', text: s.name, onclick: () => { choose(s.id); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }); } })),
        el('td', { text: fmtDate(s.latest) }), el('td', { class: 'num', text: fmt.format(Math.round((Date.parse(doc.asOf) - Date.parse(s.latest)) / 864e5)) }), el('td', { class: 'num', text: fmt.format(n30 ? n30.n : 0) }), el('td', { class: 'num', text: fmt.format(s.p12) }))))));
    const quiet = D.quiet(doc, dt.nat ? [...dt.nat.states, ...dt.nat.gaps].filter((x) => !['FO', 'BL'].includes(x.id)).map((x) => ({ id: x.id, name: x.name })) : []);
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('Freshness', 'clock', 'Who reported lately', 'The newest well each state has in the registry. A state that is days behind has not necessarily stopped drilling: its operators disclose late.'), table,
      quiet.length ? el('p', { class: 'fine', text: 'No new well in the last 12 months: ' + D.listAnd(quiet.map((x) => x.name)) + '. They are not counted as zero.' }) : null);
  }

  // the page's markup over the days in `dt`; winFrom: the chart's first day (the newest 150 by default)
  function render(winFrom = null) {
    S.win = winFrom == null ? winMax() : clampWin(winFrom);
    S.chart = el('div', { class: 'dd-chartbox' }); S.table = el('div', {}); S.tableHead = el('h2', { id: 'dd-table-h' });
    S.chartNote = el('p', { class: 'fine' });
    const dayCardEl = dayCard();
    S.earlier = el('button', { type: 'button', class: 'btn', onclick: () => page(-1) }, icon('arrow', 16, 'dd-back'), 'Earlier');
    S.later = el('button', { type: 'button', class: 'btn', onclick: () => page(1) }, 'Later', icon('arrow', 16));
    const chartHead = hdr('Day by day', 'chart', 'The last ' + CHART_DAYS + ' days, stacked by state', 'Wells by the day of their first job. Click a day, or page through the days with Earlier and Later, back to ' + monthLabel(raw.doc.months[0]) + '. The newest days are lighter: they are still being disclosed and will rise.', el('div', { class: 'card-tools' }, S.earlier, S.later));
    S.chartTitle = chartHead.querySelector('h2');
    const chartCard = el('section', { class: 'card nat-card reveal is-in' }, chartHead, S.chart, S.chartNote);
    const tableCard = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'dd-table-h' }, el('p', { class: 'eyebrow' }, icon('layers', 15), 'The wells'), S.tableHead, S.table);
    root.replaceChildren(el('div', { class: 'stack' }, ...[figures(), dayCardEl, chartCard, arrivals(), tableCard, lately()].filter(Boolean), el('p', { class: 'fine', text: 'Public records only: place- and market-level counts, no individuals. Source: the FracFocus registry, read weekly; each well is dated by its first fracturing job.' })));
    drawChart();
  }
  // want: the day the address asks for, if any (a day before the last two years loads the earlier wells before the first paint)
  async function build(want = null) {
    root.replaceChildren(el('p', { class: 'status', text: 'Loading the new wells…' }));
    try {
      await data();
      if (want && Date.parse(want + 'T00:00:00Z') < dt.P.t0) { try { await loadFull(); } catch (e) { /* the last two years: the day is then the first of them */ } }
    } catch (e) { root.replaceChildren(el('div', { class: 'fail' }, el('p', { text: 'Could not load the new-wells data. Reload the page to try again.' }))); return false; }
    day = Math.min(day, dt.P.span);
    render();
    return true;
  }

  return {
    // the address: #daily?d=2026-08-12&s=TX
    async activate(params) {
      const mySeq = ++seq;
      const d = params && params.get('d'); const dated = !!d && /^\d{4}-\d\d-\d\d$/.test(d); const s = ((params && params.get('s')) || '').toUpperCase() || null;
      if (!started) { started = true; if (!(await build(dated ? d : null))) { started = false; return; } }
      if (mySeq !== seq) return;
      if (s !== sel) choose(s, { fromHash: true });
      if (dated) await goTo(Date.parse(d + 'T00:00:00Z'), null, true);
      else if (!S.shown) setDay(dt.start, { fromHash: true });
      else paintDay();
      S.shown = true;
    },
    deactivate() { hideTip(); },
  };
}
