// The Daily report: the new wells of one day, nationwide. Pick a day (the chart, the slider, the arrows or the date box) and see that day's wells on the map, which states they are in,
// how it compares with a typical day, and every well in a table; below, who reported lately. The chart and the slider show 150 days; "Earlier" and "Later" page through them, back to
// January 2011 (the earlier wells, about 2 MB, are fetched the first time a day before the last two years is asked for); a strip of every month since 2011 above the chart marks those 150 days and opens any month with a click. Everything is drawn from data/newwells/ (FracFocus), the one source with the same facts for
// every state that reports to it, so nothing here is a figure only some states have. A well is dated by the day of its first fracturing job; operators disclose weeks to months later, so
// the newest days are still filling in and say so. The oil permits and spuds that the agencies publish with a location (Texas, Oklahoma, New Mexico and the federal offshore: the files the Map reads) ride on the
// same map as hollow rings, so a filled dot is a fracked well and a ring is an oil permit; a switch shows both, the wells or the permits. Every other state's permits, by its own count, are the National page.
import { $, el, svg, load, loadOpt, fmt, stat, fmtDate, monthLabel, dayLabel, reduced, chartWidth } from './util.js';
import { icon } from './icons.js';
import { showTip, hideTip, tipRow } from './tip.js';
import * as G from './usgeo.js';
import * as D from './newwells-data.js';
import { createUSMap } from './usmap.js';
import { renderStats } from './daily-stats.js';
import * as Oil from './oil-day-data.js';
import { segmented } from './ui.js';

const put = (node, ...kids) => node.append(...kids.filter((k) => k != null && k !== false));
const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const plural = (n, one, many) => fmt.format(n) + ' ' + (n === 1 ? one : many);
const weekday = (ms) => new Date(ms).toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });
const CHART_DAYS = 150; // the days the chart and the slider show: the newest 150, or the 150 that hold the chosen day
const TABLE_ROWS = 80;
const DAY_MS = 864e5;
const MIN_BUSY = 10; // the day the report opens on: the newest with at least this many wells (the newest days have only a few so far)

export function createDailyView({ root }) {
  let dt = null; let raw = null; let started = false; let day = 0; let sel = null; let map = null; let seq = 0; let busy = false;
  let kinds = 'both'; // what the map shows: 'both', 'wells' (fracked wells only) or 'permits' (oil permits and spuds only); without permit files it is always the wells
  const flags = () => ({ wells: !dt.Q || kinds !== 'permits', permits: !!dt.Q && kinds !== 'wells' });
  const S = {};

  async function data() {
    if (dt) return dt;
    const [doc, pts, out, nat, ...pm] = await Promise.all([load('newwells/summary'), load('newwells/points'), load('us-states'), loadOpt('national'), ...D.PERMIT_SOURCES.map((x) => loadOpt(x.file))]);
    // the oil permit files are optional: a page without one still draws the wells
    raw = { doc, pts, nat, outlines: G.buildOutlines(out), permits: D.PERMIT_SOURCES.map((x, k) => ({ id: x.id, pm: pm[k] })).filter((x) => x.pm && Array.isArray(x.pm.pts) && x.pm.pts.length) };
    // how many permits Texas, Oklahoma and New Mexico approved each day (the nightly captures' series; Oklahoma's from its permit points): optional, the page is whole without them
    raw.oil = null;
    try {
      const ok = raw.permits.find((x) => x.id === 'OK');
      const [tx, nm] = await Promise.all([loadOpt('daily/permits-series'), loadOpt('daily-nm/permits-series')]);
      if (ok && tx && nm) raw.oil = Oil.counts({ tx, nm, okPoints: ok.pm });
    } catch (e) { raw.oil = null; }
    dt = makeDt(D.decode(pts), false);
    return dt;
  }
  // the days the report works on: the last two years (full false) or every day since 2011 (full true: the earlier wells merged in, day numbers counted from Jan 1, 2011)
  function makeDt(P, full) {
    const { doc, outlines, nat } = raw;
    return { doc, P, outlines, nat, full, settledDay: D.dayOfIso(P, doc.settled), T: D.totals(doc), start: D.lastBusyDay(P, MIN_BUSY), Q: raw.permits.length ? D.decodePermits(raw.permits, D.dayIso(P.t0)) : null };
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
    p.set('d', iso(day)); if (sel) p.set('s', sel); if (dt.Q && kinds !== 'both') p.set('k', kinds);
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
  // a ranked list of states with a bar each: the fracked wells by state, or the oil permits and spuds by state (a ring beside the title)
  function stateList(title, rows, ring) {
    const top = rows[0].n;
    return el('div', { class: 'nat-list dd-by' }, el('h4', {}, ring ? el('i', { class: 'dd-ringkey', 'aria-hidden': 'true' }) : null, title), el('ul', {}, rows.map((r) => {
      const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(r.n / top)); bar.style.setProperty('--c', D.colorOf(r.id));
      const name = ring ? D.permitStateName(r.id) : (D.byId(dt.doc, r.id) || {}).name || r.id;
      const pick = allowed(r.id) ? el('button', { type: 'button', class: 'link nat-ln', text: name, title: 'Show only ' + name, onclick: () => choose(r.id) }) : el('span', { class: 'nat-ln', text: name });
      return el('li', {}, pick, el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: fmt.format(r.n) }));
    })));
  }
  // whether oil permits can be counted for the day and state shown: before the records' first day, and for a state that publishes no location, a count of none would be a claim; it is "not available"
  const permitsAvail = () => !!dt.Q && day >= dt.Q.day[0] && (!sel || dt.Q.states.includes(sel));
  // what the permit rings can and cannot say about a day, in words
  function permitNote(pn) {
    const { Q } = dt; const f = Q.states.map((id, k) => ({ id, last: Q.last[k] })).filter((x) => x.last >= 0);
    if (day < Q.day[0]) return 'Oil permit and spud locations start on ' + fmtDate(iso(Q.day[0])) + ': before it the map shows fracked wells only.';
    if (sel && !Q.states.includes(sel)) return ((D.byId(dt.doc, sel) || {}).name || sel) + ' publishes no oil permit locations, so it has no ring here. Texas, Oklahoma and New Mexico do.';
    const tx = raw.permits.find((x) => x.id === 'TX'); const share = tx && tx.pm.coverage ? Math.round(tx.pm.coverage.share12 * 100) : null;
    return (pn ? '' : 'No oil permit or spud with a location this day. ') + 'A ring is an agency\u2019s own record with a map location: a permit approved (Texas, Oklahoma) or a well spudded (New Mexico, the federal offshore). '
      + (share != null ? 'About ' + share + '% of Texas\u2019s permits of the last year have one. ' : '') + 'Other states publish none. Records run to: '
      + f.map((x) => D.permitStateName(x.id) + ' ' + fmtDate(iso(x.last)).replace(/, \d{4}$/, '')).join(', ') + '.';
  }
  function summary() {
    const { doc, P, Q } = dt; const box = el('div', { class: 'nat-panel', 'aria-live': 'polite' });
    const f = flags(); const idx = f.wells ? wellsOf(day) : []; const n = idx.length; const late = day > dt.settledDay;
    const pAvail = f.permits && permitsAvail(); const pidx = pAvail ? D.permitsOfDay(Q, day, sel) : []; const pn = pidx.length;
    const sName = sel ? (D.byId(doc, sel) || {}).name : null;
    const what = [f.wells ? (Q ? 'fracked wells by the day of the first job' : 'counted by the day of the first job') : null, pAvail ? 'oil permits and spuds by their day' : null].filter(Boolean).join(' · ') || 'oil permits and spuds';
    put(box, el('div', { class: 'nat-ph' }, el('h3', { text: weekday(ms(day)) + ', ' + dayLabel(ms(day)) }), f.wells ? el('span', { class: 'badge', text: late ? 'Still filling in' : 'Settled' }) : null),
      el('p', { class: 'nat-agency', text: (sName || 'All states') + ' · ' + what }));
    if (f.wells) put(box, el('div', { class: 'nat-big' }, el('strong', { text: fmt.format(n) }), el('span', { text: Q ? (n === 1 ? ' new fracked well' : ' new fracked wells') : (n === 1 ? ' new well' : ' new wells') })));
    if (pAvail) put(box, el('div', { class: 'nat-big dd-bigq' }, el('i', { class: 'dd-ringkey', 'aria-hidden': 'true' }), el('strong', { text: fmt.format(pn) }), el('span', { text: pn === 1 ? ' oil permit or spud with a location' : ' oil permits and spuds with a location' })));
    if (f.permits && raw.oil) { // every permit approved that day, whether or not it has a map location (the ring count above is only the ones that do)
      const rows = Oil.permitsOn(raw.oil, iso(day)); const one = sel && Oil.OIL_IDS.includes(sel); const total = rows ? (sel ? (one ? (rows.find((r) => r.id === sel) || {}).n : null) : rows.reduce((t, r) => t + r.n, 0)) : null; // a state that publishes no daily list has none, however many the three approved
      if (total != null) put(box, el('p', { class: 'fine dd-approved' }, 'Approved that day' + (one ? ' in ' + (rows.find((r) => r.id === sel) || {}).name : '') + ': ', el('strong', { text: plural(total, 'new-drill permit', 'new-drill permits') }),
        one ? '' : ' (' + rows.map((r) => r.name + ' ' + fmt.format(r.n)).join(', ') + ')', '. The rings show the ones with a map location.'));
      else if (!sel || Oil.OIL_IDS.includes(sel)) put(box, el('p', { class: 'fine dd-approved', text: 'The count of every permit approved each day starts on ' + fmtDate(raw.oil.first) + '.' }));
    }
    if (f.wells) {
      const t = typ(); const tp = t.perDay; const rg = D.typicalRange(P, doc, iso(day)); const rk = rg && !late ? D.dayRank(P, day, rg.d0, rg.d1, sel) : null;
      const then = (n > tp * 1.5 ? '; this one is busier' : n < tp * 0.5 ? '; this one is quieter' : '; this one is about typical') + (rk ? ', busier than ' + Math.round(rk.share * 100) + '% of those ' + fmt.format(rk.days) + ' days.' : '.');
      put(box, el('p', { class: 'fine', text: late
        ? 'A typical settled day has about ' + tp.toFixed(1) + '. This day is still being disclosed, so its count will rise: do not read it as a slow day.'
        : t.latest ? 'A typical day over the last 12 settled months has about ' + tp.toFixed(1) + then
          : 'A typical day in the 12 months ' + monthLabel(t.from) + ' to ' + monthLabel(t.to) + ' had about ' + tp.toFixed(1) + then }));
    }
    if (!sel) {
      const rows = f.wells ? D.perState(P, day, day).slice(0, 8) : [];
      if (rows.length) put(box, stateList(f.permits ? 'Fracked wells by state' : 'By state', rows, false));
      const prows = pAvail ? D.permitsPerState(Q, day, day) : [];
      if (prows.length) put(box, stateList(f.wells ? 'Oil permits and spuds by state' : 'By state', prows, true));
    }
    if (n) put(box, el('p', { class: 'fine', text: 'Hover a dot for its well' + (f.permits ? ', a ring for its permit' : '') + '. The numbers below describe the wells.' }));
    else if (pAvail && pn) put(box, el('p', { class: 'fine', text: 'Hover a ring for its permit.' }));
    if (f.wells && !n) put(box, el('p', { class: 'nd', text: 'No well had its first fracturing job this day in the registry' + (late ? ' yet.' : '.') + ' It is shown as none, not as a figure the registry lacks.' }));
    if (f.permits) put(box, el('p', { class: 'fine', text: permitNote(pn) }));
    return box;
  }
  function paintDay() {
    const lo = Math.max(0, day - 13);
    const moved = followDay();
    map.setRange(lo, day);
    S.summary.replaceChildren(summary());
    paintStats();
    S.date.textContent = weekday(ms(day)) + ', ' + dayLabel(ms(day));
    if (moved) drawChart(); else drawMarker();
    syncSlider();
    S.dateInput.value = iso(day);
    S.prev.disabled = ms(day) <= firstMs(); S.next.disabled = day >= dt.P.span;
    drawTable(); S.chips.forEach((b, id) => b.setAttribute('aria-pressed', String(id === sel))); if (S.pick) S.pick.value = sel || '';
  }
  // the numbers card: what the day's wells look like (daily-stats.js), for the chosen day and state
  function paintStats() {
    const r = renderStats({ P: dt.P, doc: dt.doc, day, sel, late: day > dt.settledDay });
    S.statsSub.textContent = r.sub; S.statsSub.hidden = !r.sub;
    S.stats.className = r.nodes.length > 1 ? 'dd-stats' : 'dd-stats is-empty'; S.stats.replaceChildren(...r.nodes);
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
  // the message goes to both places a click can come from: the day card and the strip above the chart (the card may be off the screen)
  const say = (text) => { for (const n of [S.status, S.yStatus]) if (n) n.textContent = text; };
  async function widen(focusKey) {
    if (dt.full) return true;
    if (busy) return false;
    busy = true;
    const keepDay = iso(day); const keepWin = iso(S.win);
    say('Loading the earlier wells (about 2 MB)…');
    try { await loadFull(); } catch (e) {
      say('Could not load the earlier wells. Check the connection and try again.');
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
  // 'both', 'wells' or 'permits': the map's layers, the panel and the table follow
  function setKinds(id, { fromHash = false } = {}) {
    kinds = id === 'wells' || id === 'permits' ? id : 'both';
    if (!dt.Q) return;
    map.setKinds(flags()); if (S.kinds) S.kinds.set(kinds, false);
    drawChart(); paintDay(); if (!fromHash) writeHash();
  }
  function choose(id, { fromHash = false } = {}) {
    sel = allowed(id) ? id : null;
    map.select(sel, true);
    drawChart(); paintDay(); if (!fromHash) writeHash();
  }
  function dayCard() {
    const { doc, P, outlines, Q } = dt;
    const canvas = el('canvas', { class: 'nw-canvas', role: 'img', 'aria-label': 'Map of the new fracked wells' + (Q ? ' (dots) and the oil permits and spuds (rings)' : '') + ' of the chosen day and the two weeks before it; the table below lists the day\'s records' });
    const stage = el('div', { class: 'nw-stage' }, canvas);
    map = createUSMap({ canvas, host: stage, outlines, P, doc, Q, interactive: true, glowDays: 1, onSelect: (id) => choose(id) });
    if (Q) map.setKinds(flags());
    // what the map shows: a filled glowing dot is a fracked well, a hollow ring is an oil permit or spud (the legend says so; the switch shows both or either)
    S.kinds = Q ? segmented({ label: 'What the map shows', tabs: false, prefix: 'ddk', value: kinds, options: [{ id: 'both', label: 'Both' }, { id: 'wells', label: 'Fracked wells' }, { id: 'permits', label: 'Oil permits' }], onChange: (id) => setKinds(id) }) : null;
    const marks = Q ? el('ul', { class: 'nw-marks', 'aria-label': 'What the marks on the map are' },
      el('li', {}, el('i', { class: 'dd-dotkey', 'aria-hidden': 'true' }), 'Fracked well: the first fracturing job, every state that reports'),
      el('li', {}, el('i', { class: 'dd-ringkey', 'aria-hidden': 'true' }), 'Oil permit or spud: an agency\u2019s record with a location')) : null;
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
    const head = hdr('The day', 'calendar', Q ? 'Where the wells and permits of one day are' : 'Where the wells of one day are', Q ? 'The chosen day\u2019s dots and rings glow; the two weeks before it are dimmer. Operators disclose fracturing jobs weeks to months afterwards, so the newest days are still filling in.' : 'The chosen day’s wells glow; the two weeks before it are dimmer. Operators disclose weeks to months after a job, so the newest days are still filling in.', el('div', { class: 'card-tools' }, S.kinds ? S.kinds.el : null, S.pick));
    head.querySelector('h2').id = 'dd-h';
    const nav = el('div', { class: 'dd-nav' }, S.prev, el('div', { class: 'dd-mid' }, S.date, S.range), S.next, dateInput, newest);
    put(card, head, nav, S.status, el('div', { class: 'nw-grid' }, el('div', { class: 'nw-mapcol' }, stage, marks, keys), S.summary));
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
    drawYears();
    const { P } = dt; const cd = chartData(); const W = 720; const H = 230; const L = 40; const R = 6; const T = 10; const B = 26;
    const tot = new Array(cd.n).fill(0); cd.series.forEach((s) => s.values.forEach((v, i) => { tot[i] += v; }));
    const tp = typ();
    const ov = flags().permits && raw.oil ? Oil.valuesOver(raw.oil, iso(S.win), cd.n, sel) : null; // the permits approved each day of the chart (null: no count that day), a line of rings beside the bars
    const { top, ticks } = D.niceTop(Math.max(...tot, tp.perDay * 1.1, ov ? Math.max(0, ...ov.filter((v) => v != null)) : 0, 1));
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
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: weekday(dm) + ', ' + dayLabel(dm) }), ...cd.series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name)), tipRow(fmt.format(tot[i]), 'in all'), ov && ov[i] != null ? tipRow(fmt.format(ov[i]), 'new-drill permits approved') : null, late ? tipRow('Still filling in', '') : null, tipRow('Click to open this day', '')], e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('click', () => setDay(d));
      g.append(hit);
    }
    if (ov && ov.some((v) => v != null)) { // a thin line with a ring for each day that has a count; a day without one is a gap, not a zero
      let d = ''; let pen = false;
      ov.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + (sx(i) + slot / 2).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; });
      g.append(svg('path', { class: 'dd-oil-line', d }));
      ov.forEach((v, i) => { if (v != null) g.append(svg('circle', { class: 'dd-oil-dot', cx: (sx(i) + slot / 2).toFixed(1), cy: y(v).toFixed(1), r: slot >= 4 ? 2.6 : 1.8 })); });
    }
    g.append(S.marker);
    g.append(svg('line', { class: 'dd-typ', x1: L, x2: W - R, y1: y(tp.perDay), y2: y(tp.perDay) }), svg('text', { class: 'ax', x: W - R - 2, y: y(tp.perDay) - 4, 'text-anchor': 'end', text: 'typical day, ' + tp.perDay.toFixed(0) }));
    const key = el('ul', { class: 'nat-keys nat-chart-keys', 'aria-label': 'States in the chart' }, cd.series.map((s) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', s.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: s.name })); }));
    const oilKey = ov === null ? null : el('ul', { class: 'nat-keys nat-chart-keys dd-oilkey', 'aria-label': 'The oil permits in the chart' }, el('li', { class: 'nat-key' }, el('i', { class: 'dd-ringkey', 'aria-hidden': 'true' }),
      el('span', { text: 'Oil permits approved each day: the line of rings' + (sel && !Oil.OIL_IDS.includes(sel) ? ' (not published by day for this state)' : ov.some((v) => v != null) ? (sel ? '' : ' (Texas, Oklahoma and New Mexico)') : ' (none by day for these days)') })));
    S.chart.replaceChildren(key, oilKey, g);
    S.chartData = { cd, slot, L };
    S.chartTitle.textContent = S.win >= winMax() ? 'The last ' + CHART_DAYS + ' days, stacked by state' : 'The ' + CHART_DAYS + ' days from ' + fmtDate(iso(S.win)) + ', stacked by state';
    S.chartNote.textContent = (ov && ov.some((v) => v != null) ? 'The line of rings is the new-drill permits approved each day in ' + (sel ? 'the chosen state' : 'Texas, Oklahoma and New Mexico, which publish them daily') + ' (read since ' + fmtDate(raw.oil.first) + '), on the same scale as the bars: a permit and a fracked well are different events, weeks to months apart, and are not added. ' : '') + 'The dashed line is a typical day of fracked wells over ' + (tp.latest ? 'the 12 settled months' : 'the 12 months ' + monthLabel(tp.from) + ' to ' + monthLabel(tp.to)) + ' (all states, or the one chosen).';
    S.earlier.disabled = ms(S.win) <= firstMs(); S.later.disabled = S.win >= winMax();
    drawMarker();
  }
  function drawMarker() {
    if (!S.marker || !S.chartData) return;
    const i = day - S.win; const { slot, L } = S.chartData;
    S.marker.setAttribute('x', (L + slot * i - (Math.max(3, slot) - slot) / 2).toFixed(1)); S.marker.style.display = i >= 0 && i <= S.chartData.cd.n - 1 ? '' : 'none';
    markYears();
  }

  /* ---------- every month since 2011: one bar a month, the chart's 150 days marked, a click opens the month ---------- */
  // Drawn from summary.json, which holds every month from the start, so the strip costs no download; a click on a month before the last two years fetches the earlier wells like the date box does.
  // It is drawn at the width the page has and again when the state or the width changes (`yKey`, `yW`); the band and the day line move without redrawing (`markYears`).
  function drawYears() {
    const { doc } = dt; const W = chartWidth(S.years, 1200);
    if (S.yKey === (sel || '') && Math.abs(W - S.yW) <= 24) return;
    S.yKey = sel || ''; S.yW = W;
    S.yCap.textContent = 'Every month since ' + monthLabel(doc.months[0]) + (sel ? ' in ' + (D.byId(doc, sel) || {}).name : ', all states') + '. The band is the ' + CHART_DAYS + ' days below; click a month to open it.' + (dt.Q ? ' Fracked wells only.' : '');
    const months = doc.months; const n = months.length; const names = Object.fromEntries(doc.states.map((s) => [s.id, s.name]));
    const series = sel ? [{ id: sel, name: names[sel], color: D.colorOf(sel), values: D.byId(doc, sel).new }] : D.stack(doc, n).series;
    const totals = months.map((_, i) => series.reduce((t, s) => t + s.values[i], 0));
    const { top } = D.niceTop(Math.max(...totals, 1));
    const H = W < 500 ? 78 : 92; const L = 40; const R = 6; const T = 8; const B = 20;
    const slot = (W - L - R) / n; const bw = Math.max(1, slot * 0.8); const y = (v) => T + (H - T - B) * (1 - v / top);
    const settledAt = months.indexOf(doc.settled.slice(0, 7));
    const g = svg('svg', { class: 'nat-chart dd-ychart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': 'New wells by month, ' + monthLabel(months[0]) + ' to ' + monthLabel(months[n - 1]) + (sel ? ' in ' + names[sel] : ', all states') + '. The band marks the days of the chart below. Click a month to open it, or use the date box, the arrows, Earlier and Later.' });
    g.append(svg('line', { class: 'grid', x1: L, x2: W - R, y1: y(top), y2: y(top) }), svg('text', { class: 'ax', x: L - 6, y: y(top) + 4, 'text-anchor': 'end', text: stat(top) }),
      svg('line', { class: 'base', x1: L, x2: W - R, y1: y(0), y2: y(0) }), svg('text', { class: 'ax', x: L - 6, y: y(0) + 4, 'text-anchor': 'end', text: '0' }));
    const every = Math.max(1, Math.ceil(36 / (slot * 12))); const y0 = +months[0].slice(0, 4); // a year label every `every` years: as many as fit
    months.forEach((ym, i) => {
      const x = L + slot * i; let acc = 0; const late = i > settledAt;
      series.forEach((s) => { const v = s.values[i]; if (!v) return; const seg = svg('rect', { class: 'dd-yseg' + (late ? ' is-late' : ''), x: (x + (slot - bw) / 2).toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1) }); seg.style.setProperty('--c', s.color); g.append(seg); acc += v; });
      if (ym.slice(5) === '01' && (+ym.slice(0, 4) - y0) % every === 0) g.append(svg('text', { class: 'ax', x: x + slot / 2, y: H - 5, 'text-anchor': 'middle', text: ym.slice(0, 4) }));
      const hit = svg('rect', { class: 'nat-hit', x: x.toFixed(1), y: T, width: slot.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: monthLabel(ym) }), ...series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name)), series.length > 1 ? tipRow(fmt.format(totals[i]), 'in all') : null, late ? tipRow('Still filling in', 'disclosures arrive late') : null, tipRow('Click to open ' + monthLabel(ym), '')].filter(Boolean), e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('click', () => { hideTip(); goTo(Date.parse(ym + '-01T00:00:00Z')); });
      g.append(hit);
    });
    S.yWin = svg('rect', { class: 'dd-ywin', y: T - 3, height: H - T - B + 3 }); S.yDay = svg('line', { class: 'dd-yday', y1: T - 3, y2: H - B });
    g.append(S.yWin, S.yDay);
    S.yAxis = { L, slot };
    S.years.replaceChildren(g);
  }
  function markYears() {
    if (!S.yWin || !S.yAxis || !S.yWin.isConnected) return;
    const { L, slot } = S.yAxis; const { doc } = dt; const nWin = Math.min(CHART_DAYS, dt.P.span - S.win + 1);
    const x0 = L + slot * D.monthPos(doc, iso(S.win)); const x1 = L + slot * D.monthPos(doc, D.dayIso(ms(S.win) + nWin * DAY_MS)); const w = Math.max(3, x1 - x0);
    S.yWin.setAttribute('x', (x0 - (w - (x1 - x0)) / 2).toFixed(1)); S.yWin.setAttribute('width', w.toFixed(1));
    const xd = (L + slot * D.monthPos(doc, iso(day))).toFixed(1); S.yDay.setAttribute('x1', xd); S.yDay.setAttribute('x2', xd);
  }

  /* ---------- the wells of the day, as a table (the map's twin) ---------- */
  function drawTable() {
    const { P, doc, Q } = dt; const f = flags();
    const widx = f.wells ? wellsOf(day) : []; const pAvail = f.permits && permitsAvail(); const pidx = pAvail ? D.permitsOfDay(Q, day, sel) : [];
    const name = (id) => (D.byId(doc, id) || {}).name || D.permitStateName(id);
    const dash = '—';
    // one row per well and per permit; with the permit layer the first column says which is which
    const rows = [
      ...widx.map((i) => ({ st: name(D.stateOfPoint(P, i)), kind: 0, county: D.countyOf(P, i) || '',
        cells: ['Fracked well', name(D.stateOfPoint(P, i)), D.countyOf(P, i) || dash, D.operatorOf(P, i) || 'Not named', D.feet(P.tvd[i]) || dash, D.gallons(P.h2o[i]) || dash, P.f[i] ? D.LAND[P.f[i]].replace(/ land$/, '') : dash] })),
      ...pidx.map((j) => ({ st: name(D.permitState(Q, j)), kind: 1, county: '',
        cells: [D.permitWord(Q, j), name(D.permitState(Q, j)), dash, D.permitOperator(Q, j) || 'Not named', D.feet(Q.tvd[j]) || dash, dash, dash] })),
    ];
    rows.sort((x, y) => x.st.localeCompare(y.st) || x.kind - y.kind || x.county.localeCompare(y.county));
    const shown = rows.slice(0, TABLE_ROWS); const first = Q ? 0 : 1; // without the permit layer the Kind column is left out
    const body = shown.map((r) => el('tr', {}, r.cells.slice(first).map((c, k) => el('td', { class: k + first === 4 || k + first === 5 ? 'num' : null, text: c }))));
    const w = f.wells ? fmt.format(widx.length) + (Q ? (widx.length === 1 ? ' fracked well' : ' fracked wells') : (widx.length === 1 ? ' well' : ' wells')) : null;
    const q = pAvail ? fmt.format(pidx.length) + (pidx.length === 1 ? ' oil permit or spud' : ' oil permits and spuds') : null;
    S.tableHead.textContent = ([w, q].filter(Boolean).join(' and ') || 'No oil permit locations') + ' on ' + fmtDate(iso(day)) + (sel ? ' in ' + name(sel) : '');
    const heads = ['Kind', 'State', 'County', 'Operator', 'Depth', 'Water', 'Land'].slice(first);
    // replaceChildren writes the word "null" for a null child, so the empty ones are dropped first
    S.table.replaceChildren(...[rows.length ? el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'The records of the chosen day' }, el('table', { class: 'grid' },
      el('thead', {}, el('tr', {}, heads.map((h, k) => el('th', { scope: 'col', class: k + first === 4 || k + first === 5 ? 'num' : null, text: h })))), el('tbody', {}, body)))
      : el('p', { class: 'nd', text: !Q ? 'No well.' : !f.wells ? (pAvail ? 'No oil permit or spud with a location.' : 'No oil permit locations for this day or state.') : pAvail ? 'No fracked well or oil permit with a location.' : 'No fracked well.' }),
    rows.length > TABLE_ROWS ? el('p', { class: 'fine', text: 'The first ' + TABLE_ROWS + ' of ' + fmt.format(rows.length) + ' are listed; choose a state to see its own.' }) : null,
    el('p', { class: 'fine', text: 'Operators are named only when they are corporations, LLCs or partnerships. No API number, well name or lease is published.' })].filter(Boolean));
  }

  /* ---------- who reported lately ---------- */
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
    const chartHead = hdr('Day by day', 'chart', 'The last ' + CHART_DAYS + ' days, stacked by state', (dt.Q ? 'Fracked wells' : 'Wells') + ' by the day of their first job. Click a month on the strip to go straight there, a day to open it, or page with Earlier and Later, back to ' + monthLabel(raw.doc.months[0]) + '. The newest days are lighter: they are still being disclosed and will rise.', el('div', { class: 'card-tools' }, S.earlier, S.later));
    S.chartTitle = chartHead.querySelector('h2');
    S.years = el('div', { class: 'dd-years' }); S.yStatus = el('p', { class: 'fine nw-status', role: 'status' }); S.yKey = null;
    S.yCap = el('p', { class: 'fine dd-ycap' });
    const yearsBox = el('div', { class: 'dd-yearsbox' }, S.yCap, S.yStatus, S.years);
    const chartCard = el('section', { class: 'card nat-card reveal is-in' }, chartHead, yearsBox, S.chart, S.chartNote);
    S.statsSub = el('p', { class: 'sub' }); S.stats = el('div', { class: 'dd-stats' });
    const statsHead = hdr('The day in numbers', 'layers', 'What the day’s wells look like', null); statsHead.querySelector('h2').id = 'dd-stats-h'; statsHead.firstChild.append(S.statsSub);
    const statsCard = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'dd-stats-h' }, statsHead, S.stats);
    const tableCard = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'dd-table-h' }, el('p', { class: 'eyebrow' }, icon('layers', 15), 'The wells'), S.tableHead, S.table);
    root.replaceChildren(el('div', { class: 'stack' }, figures(), dayCardEl, statsCard, chartCard, tableCard, lately(), el('p', { class: 'fine', text: 'Public records only: place- and market-level counts, no individuals. Source: the FracFocus registry, read weekly; each well is dated by its first fracturing job. A few wells in a thousand have no usable GPS point: they are in the months and the typical day, but not on the map or in a day\'s count.' })));
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

  if (/[?&]debug\b/.test(location.search)) window.__dd = { get map() { return map; }, get dt() { return dt; }, D };
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (dt && S.years && S.years.isConnected && S.years.clientWidth) { drawYears(); markYears(); } }, 150);
  });

  return {
    // the address: #daily?d=2026-08-12&s=TX
    async activate(params) {
      const mySeq = ++seq;
      const d = params && params.get('d'); const dated = !!d && /^\d{4}-\d\d-\d\d$/.test(d); const s = ((params && params.get('s')) || '').toUpperCase() || null;
      const k = params && params.get('k'); const wantKinds = k === 'wells' || k === 'permits' ? k : 'both';
      if (!started) { started = true; if (!(await build(dated ? d : null))) { started = false; return; } }
      if (mySeq !== seq) return;
      if (s !== sel) choose(s, { fromHash: true });
      if (dt.Q && wantKinds !== kinds) setKinds(wantKinds, { fromHash: true });
      if (dated) await goTo(Date.parse(d + 'T00:00:00Z'), null, true);
      else if (!S.shown) setDay(dt.start, { fromHash: true });
      else paintDay();
      S.shown = true;
      if (S.years && S.years.isConnected) { drawYears(); markYears(); } // the strip is drawn at the width the page has now (the view may have been hidden when it was first drawn)
    },
    deactivate() { hideTip(); },
  };
}
