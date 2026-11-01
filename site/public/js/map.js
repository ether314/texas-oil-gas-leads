// The Map tab: toolbar, choropleth metrics, layer toggles, legend, side panel / bottom sheet, table twin, deep links.
import { el, svg, fmt, compactFmt, monthLabel, dayLabel, fmtDate, signed, clamp, halves, sum, load, loadOpt, toObjects, parseHash, replaceHash, queryText, reduced, sharePct } from './util.js';
import { getGeo, getPoints, getZips, getInfra, getBasins } from './geo.js';
import { createEngine } from './engine.js';
import { onTheme, isDark } from './theme.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { areaChart, spark, delta, histChart } from './charts.js';
import { icon } from './icons.js';
import { shareButton, absoluteLink } from './ui.js';
import { createTimelapse } from './timelapse.js';
import { stateOf, measureOf, sameMeasure, measureLabel, countWord, listAnd, activeStates, statesKey, statesIn, countyState, countyCode, pointState, pointCountyKey, inName, placeOf, placeTitle, placesOne, placesWord, placesOr, spudsNote, spudCaveat, yearStart, ucFirst, everyOf, dotName, chgMinOf, chgMinPhrase } from './states.js';
import { countyPermits, stateOperatorRows, operatorExtras } from './overview-data.js';

const NO_BLS = 'No data (suppressed by BLS)';
const NO_PROD = 'No production reported in the latest 12 months';
const bcf = (v) => (v >= 1e7 ? fmt.format(Math.round(v / 1e6)) : (v / 1e6).toFixed(1)) + ' Bcf';
const yoyf = (a, b) => (b > 0 ? a / b - 1 : null);
const RAMP = {
  light: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'],
  dark: ['#0d366b', '#184f95', '#1c5cab', '#2a78d6', '#3987e5', '#5598e7', '#6da7ec'],
};
const NODATA = { light: '#e3e2db', dark: '#252523' };
const CHG_EDGES = [-0.5, -0.25, -0.1, 0.1, 0.25, 0.5];
const LAYER_DEFS = [
  { id: 'permits', label: 'Permits', shape: 'dot', color: 'var(--s2)' },
  { id: 'refinery', label: 'Refineries', shape: 'diamond', color: 'var(--s3)' },
  { id: 'gasplant', label: 'Gas plants', shape: 'square', color: 'var(--s3)' },
  { id: 'lng', label: 'LNG terminals', shape: 'triangle', color: 'var(--s3)' },
  { id: 'zips', label: 'Companies by ZIP', shape: 'ring', color: 'var(--s7)' },
];
const FAC_NAME = { refinery: 'Refinery', gasplant: 'Gas processing plant', lng: 'LNG terminal' };
// Texas's own files: production, jobs, establishments, companies, mineral value. A county of another state has no figure for them (not zero).
const TEXAS_ONLY = new Set(['oil12', 'gas12', 'prodchg', 'oemp', 'semp', 'owage', 'e213', 'e211', 'co', 'mineral']);
const NOT_TEXAS = 'Not available: this figure is Texas only';
const opsLink = (name) => '#operators?' + new URLSearchParams({ q: name, band: 'all' });
const cap = (x) => x.charAt(0).toUpperCase() + x.slice(1);
const an = (x) => (/^[aeiou]/i.test(x) ? 'an ' : 'a ') + x; // "a county", "an area"

function mixHex(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const x = p(a); const y = p(b);
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
}
function divRamp(dark) {
  const mid = dark ? '#383835' : '#f0efec'; const blue = dark ? '#3987e5' : '#2a78d6'; const red = dark ? '#e66767' : '#e34948';
  const t = [1, 0.62, 0.3];
  return [...t.map((v) => mixHex(mid, red, v)), mid, ...t.slice().reverse().map((v) => mixHex(mid, blue, v))];
}
const SKINS = {
  dark: [null,
    { glow: [[0, 'rgba(176,160,255,0.9)'], [0.3, 'rgba(128,108,238,0.36)'], [1, 'rgba(110,90,226,0)']], dotNew: 'rgba(192,178,255,1)', dotOld: 'rgba(150,132,245,0.62)',
      tlGlow: [[0, 'rgba(226,218,255,0.95)'], [0.22, 'rgba(150,132,245,0.55)'], [1, 'rgba(110,90,226,0)']], tlHot: 'rgba(244,240,255,0.98)', tlRing: 'rgba(190,176,255,0.9)' },
    { glow: [[0, 'rgba(110,232,180,0.9)'], [0.3, 'rgba(30,178,126,0.36)'], [1, 'rgba(25,158,112,0)']], dotNew: 'rgba(120,232,186,1)', dotOld: 'rgba(40,196,140,0.62)',
      tlGlow: [[0, 'rgba(206,252,230,0.95)'], [0.22, 'rgba(60,200,150,0.55)'], [1, 'rgba(25,158,112,0)']], tlHot: 'rgba(238,255,247,0.98)', tlRing: 'rgba(130,236,192,0.9)' },
    { glow: [[0, 'rgba(250,150,210,0.9)'], [0.3, 'rgba(214,72,150,0.36)'], [1, 'rgba(201,59,143,0)']], dotNew: 'rgba(248,152,208,1)', dotOld: 'rgba(224,90,166,0.62)',
      tlGlow: [[0, 'rgba(255,226,242,0.95)'], [0.22, 'rgba(232,110,180,0.55)'], [1, 'rgba(201,59,143,0)']], tlHot: 'rgba(255,240,248,0.98)', tlRing: 'rgba(246,150,206,0.9)' },
  ],
  light: [null,
    { glow: null, dotNew: 'rgba(98,80,214,1)', dotOld: 'rgba(98,80,214,0.62)', tlGlow: [[0, 'rgba(98,80,214,0.55)'], [0.3, 'rgba(98,80,214,0.24)'], [1, 'rgba(98,80,214,0)']], tlHot: 'rgba(255,255,255,0.95)', tlRing: 'rgba(98,80,214,0.85)' },
    { glow: null, dotNew: 'rgba(22,150,104,1)', dotOld: 'rgba(27,175,122,0.62)', tlGlow: [[0, 'rgba(27,175,122,0.55)'], [0.3, 'rgba(27,175,122,0.24)'], [1, 'rgba(27,175,122,0)']], tlHot: 'rgba(255,255,255,0.95)', tlRing: 'rgba(22,150,104,0.85)' },
    { glow: null, dotNew: 'rgba(201,59,143,1)', dotOld: 'rgba(201,59,143,0.62)', tlGlow: [[0, 'rgba(201,59,143,0.55)'], [0.3, 'rgba(201,59,143,0.24)'], [1, 'rgba(201,59,143,0)']], tlHot: 'rgba(255,255,255,0.95)', tlRing: 'rgba(201,59,143,0.85)' },
  ],
};
function engineTheme() {
  return { ...engineBase(), st: SKINS[isDark() ? 'dark' : 'light'] };
}
function engineBase() {
  return isDark() ? {
    dark: true, grat: 'rgba(150,175,215,0.07)', line: 'rgba(255,255,255,0.13)', border: 'rgba(200,220,250,0.55)', halo2: 'rgba(60,130,230,0.16)',
    hover: 'rgba(255,255,255,0.14)', ink: '#f0efec', sel: '#ffffff', selHalo: 'rgba(8,9,11,0.7)', zipFill: 'rgba(144,133,233,0.3)', zipLine: 'rgba(168,158,248,0.92)',
    glow: [[0, 'rgba(255,152,84,0.9)'], [0.3, 'rgba(255,112,44,0.36)'], [1, 'rgba(255,100,40,0)']], additive: false, glowNew: 0.85, glowOld: 0.42,
    dotNew: 'rgba(255,168,98,1)', dotOld: 'rgba(255,132,64,0.62)', dotRing: 'rgba(255,255,255,0)', ring: '#0e0f10', aqua: '#199e70',
    label: '#e8e7e3', countyLabel: '#b3b2ab', halo: 'rgba(14,15,16,0.85)',
    dim: 'rgba(8,9,11,0.55)', basin: '#ff9a55', basinHalo: 'rgba(14,15,16,0.92)', tlHot: 'rgba(255,244,226,0.98)', tlRing: 'rgba(255,190,130,0.9)',
    tlGlow: [[0, 'rgba(255,226,190,0.95)'], [0.22, 'rgba(255,150,80,0.55)'], [1, 'rgba(255,110,40,0)']],
  } : {
    dark: false, grat: 'rgba(20,40,80,0.06)', line: 'rgba(11,11,11,0.17)', border: 'rgba(11,11,11,0.62)', halo2: 'rgba(42,120,214,0.1)',
    hover: 'rgba(255,255,255,0.4)', ink: '#0b0b0b', sel: '#0b0b0b', selHalo: 'rgba(255,255,255,0.92)', zipFill: 'rgba(98,80,214,0.26)', zipLine: 'rgba(98,80,214,0.88)',
    dotNew: 'rgba(238,100,44,1)', dotOld: 'rgba(238,100,44,0.62)', dotRing: 'rgba(255,255,255,0)', ring: '#fcfcfb', aqua: '#1baf7a',
    label: '#2a2a28', countyLabel: '#52514e', halo: 'rgba(252,252,251,0.88)',
    dim: 'rgba(249,249,247,0.62)', basin: '#d9501c', basinHalo: 'rgba(255,255,255,0.95)', tlHot: 'rgba(255,255,255,0.95)', tlRing: 'rgba(222,84,30,0.85)',
    tlGlow: [[0, 'rgba(238,100,44,0.55)'], [0.3, 'rgba(238,100,44,0.24)'], [1, 'rgba(238,100,44,0)']],
  };
}

const shapeIcon = (shape, color) => {
  const g = {
    dot: svg('circle', { cx: 8, cy: 8, r: 4.5 }), ring: svg('circle', { cx: 8, cy: 8, r: 5.5, 'fill-opacity': '0.28' }),
    diamond: svg('path', { d: 'M8 2 14 8 8 14 2 8Z' }), square: svg('rect', { x: 3, y: 3, width: 10, height: 10 }),
    triangle: svg('path', { d: 'M8 2.2 14.2 13H1.8Z' }),
  }[shape];
  g.setAttribute('fill', color); g.setAttribute('stroke', color);
  return svg('svg', { class: 'shape', width: 16, height: 16, viewBox: '0 0 16 16', 'aria-hidden': 'true' }, g);
};

export function createMapView({ root, meta }) {
  let S = null; let engine = null; let pending = null; let started = false; let current = null; let lastZoomState = '';
  // the map is built for the states shown (buildKey); a build still loading when the choice changes is dropped (gen)
  let buildKey = ''; let gen = 0;
  const state = { metric: 'p12', layers: new Set(['permits']), county: null, op: null, zip: null, detail: null, table: false, basin: null };
  const ui = {};
  const mq = matchMedia('(max-width: 880px)');
  const isMapActive = () => parseHash().view === 'map';

  /* ---------- data ---------- */
  // Everything the map draws for the states shown. Texas's own files (production, jobs, establishments, companies, mineral value, basins,
  // plants, ZIPs, operator production) cover Texas only: a county of another state gets no figure from them (null), never a zero.
  function prepare(d, states) {
    const { G, ptsRes, cp, lab, cc, zips, infra, ex, ops, cpr, cbp, minr, B, opProd } = d;
    const pm = ptsRes.pm; const P = ptsRes.P;
    const multi = states.length > 1; const tx = states.includes('TX');
    const opIdx = new Map(pm.opNums.map((n, i) => [n, i]));
    const exBy = new Map(ex ? toObjects(ex).map((r) => [r.num, r]) : []);
    const opBy = new Map(ops ? toObjects(ops).map((r) => [r.num, r]) : []);
    // each state's operators come from its own file, numbers prefixed with the state (OK:123), their monthly counts on that file's own months
    const exMonthsBy = ex ? { TX: ex.months } : {};
    d.others.forEach(({ id, doc }) => {
      if (!doc) return;
      exMonthsBy[id] = doc.months;
      for (const r of stateOperatorRows(id, doc)) { opBy.set(r.num, r); exBy.set(r.num, operatorExtras(r)); }
    });
    const cs = G.counties;
    const isTx = cs.map((c) => countyState(c.f) === 'TX');
    const halvesBy = cs.map((c) => halves((cp.counties[c.f] || {}).m));
    const word = sameMeasure(states) ? measureOf(states[0]).short : 'permits or spuds';
    const metrics = [
      { id: 'p12', group: 'Drilling', label: measureLabel(states) + ' (12 mo)', kind: 'seq', int: true, fmt: (v) => fmt.format(v), nodata: 'No data', unit: word, vals: cs.map((c) => (cp.counties[c.f] || { p12: 0 }).p12) },
      {
        id: 'chg', group: 'Drilling', label: 'Change vs prior 12 mo', kind: 'div', fmt: (v) => signed(v), nodata: 'Under 10 ' + word + ' in 24 months, too few to compare', unit: '',
        vals: cs.map((c, i) => { const h = halvesBy[i]; return h.a + h.b < 10 ? null : h.b === 0 ? 9.99 : h.f; }),
      },
      { id: 'depth', group: 'Drilling', label: 'Average well depth', kind: 'seq', fmt: (v) => fmt.format(Math.round(v)) + ' ft', nodata: multi || !tx ? 'No reported depth' : 'No permits with a reported depth', unit: 'ft', vals: cs.map((c) => { const dp = (cp.counties[c.f] || {}).depth; return dp || null; }) },
    ];
    const prodHalves = cs.map((c, i) => { const r = isTx[i] && cpr && cpr.counties[c.f]; return r ? { a: r.o12, b: r.o12p, f: r.o12p > 0 ? r.o12 / r.o12p - 1 : r.o12 > 0 ? Infinity : null } : { a: 0, b: 0, f: null }; });
    if (cpr) {
      const pv = (k) => cs.map((c, i) => { const r = isTx[i] ? cpr.counties[c.f] : null; return r ? r[k] : null; });
      metrics.push(
        { id: 'oil12', group: 'Production', label: 'Oil production (12 mo)', kind: 'seq', fmt: (v) => compactFmt.format(v) + ' bbl', nodata: NO_PROD, unit: '', vals: pv('o12') },
        { id: 'gas12', group: 'Production', label: 'Gas production (12 mo)', kind: 'seq', fmt: bcf, nodata: NO_PROD, unit: '', vals: pv('g12') },
        {
          id: 'prodchg', group: 'Production', label: 'Change in oil vs prior 12 mo', kind: 'div', fmt: (v) => signed(v), nodata: 'Under 100,000 barrels in 24 months, too little to compare', unit: '',
          vals: prodHalves.map((h) => (h.a + h.b < 100000 ? null : h.b === 0 ? 9.99 : h.f)),
        },
      );
    }
    if (lab) {
      const lv = (k, f) => cs.map((c) => { const r = lab.counties[c.f]; return r && r[k] ? r[k][f] : null; });
      metrics.push(
        { id: 'oemp', group: 'Jobs and industry', label: 'Oil & gas jobs', kind: 'seq', int: true, fmt: (v) => fmt.format(v), nodata: NO_BLS, unit: 'jobs', vals: lv('o', 'emp') },
        { id: 'semp', group: 'Jobs and industry', label: 'Oilfield-services jobs', kind: 'seq', int: true, fmt: (v) => fmt.format(v), nodata: NO_BLS, unit: 'jobs', vals: lv('s', 'emp') },
        { id: 'owage', group: 'Jobs and industry', label: 'Oil & gas average weekly wage', kind: 'seq', fmt: (v) => '$' + fmt.format(v), nodata: NO_BLS, unit: 'per week', vals: lv('o', 'wage') },
      );
    }
    if (cbp) {
      const ev = (code) => cs.map((c, i) => { if (!isTx[i]) return null; const r = cbp.counties[c.f]; return r && r[code] ? r[code].estab : 0; });
      metrics.push(
        { id: 'e213', group: 'Jobs and industry', label: 'Oilfield-service establishments', kind: 'seq', int: true, zero: true, fmt: (v) => fmt.format(v), nodata: 'None', unit: 'establishments', vals: ev('213') },
        { id: 'e211', group: 'Jobs and industry', label: 'Oil & gas extraction establishments', kind: 'seq', int: true, zero: true, fmt: (v) => fmt.format(v), nodata: 'None', unit: 'establishments', vals: ev('211') },
      );
    }
    if (cc) metrics.push({ id: 'co', group: 'Jobs and industry', label: 'Companies headquartered', kind: 'seq', int: true, fmt: (v) => fmt.format(v), nodata: 'No data', unit: 'companies', vals: cs.map((c, i) => (isTx[i] ? (cc.counties[c.f] || { total: 0 }).total : null)) });
    if (minr) metrics.push({ id: 'mineral', group: 'Value', label: 'Mineral property value', kind: 'seq', zero: true, fmt: (v) => '$' + compactFmt.format(v), nodata: 'No value listed', unit: '', vals: cs.map((c) => { const r = minr.counties[c.f]; return r ? r.v : null; }) });
    metrics.forEach((m) => { if (TEXAS_ONLY.has(m.id)) m.tx = true; });
    const prodBy = new Map(opProd && opProd.rows ? toObjects(opProd).map((r) => [r.num, r]) : []);
    const ptCount = new Map();
    for (let i = 0; i < P.n; i++) { const k = pointCountyKey(P.fips[i]); ptCount.set(k, (ptCount.get(k) || 0) + 1); }
    return { G, P, pm, cp, lab, cc, zips, infra, exBy, opBy, opIdx, halvesBy, metrics, exMonths: ex ? ex.months : [], exMonthsBy, byId: new Map(metrics.map((m) => [m.id, m])), ptCount, cpr, cbp, minr, B, opProd, prodBy, prodHalves, states, multi, tx, isTx, mLabel: measureLabel(states), word };
  }

  /* ---------- color scales ---------- */
  function scaleOf(m, dark) {
    if (m.kind === 'div') {
      const colors = divRamp(dark); const e = CHG_EDGES;
      const names = ['−50% or lower', '−50% to −25%', '−25% to −10%', '−10% to +10%', '+10% to +25%', '+25% to +50%', '+50% or higher'];
      return { colors, classOf: (v) => { let c = 0; while (c < e.length && v >= e[c]) c++; return c; }, names, minText: '−50% or lower', maxText: '+50% or higher' };
    }
    const ramp = RAMP[dark ? 'dark' : 'light'];
    const vs = m.vals.filter((v) => v != null).sort((a, b) => a - b);
    // no county has a value (New Mexico publishes no depth): there is no scale to draw, only the no-data line
    if (!vs.length) return { colors: [ramp[0]], classOf: () => 0, names: [''], minText: '', maxText: '', empty: true };
    const edges = []; const K = ramp.length;
    const zeros = vs.filter((v) => v === 0).length;
    const zeroClass = (m.int || m.zero) && zeros >= vs.length * 0.08;
    if (zeroClass) {
      // many counties sit at exactly zero: give them their own class, then split the rest into equal-count classes
      const pos = vs.slice(zeros); edges.push(pos[0]);
      for (let q = 1; q < K - 1; q++) { const e = pos[Math.floor((pos.length * q) / (K - 1))]; if (e > edges[edges.length - 1]) edges.push(e); }
    } else {
      for (let q = 1; q < K; q++) {
        const e = vs[Math.floor((vs.length * q) / K)];
        if (e != null && e > vs[0] && (!edges.length || e > edges[edges.length - 1])) edges.push(e);
      }
    }
    const n = edges.length + 1;
    const colors = Array.from({ length: n }, (_, i) => ramp[n === 1 ? 0 : Math.round((i * (ramp.length - 1)) / (n - 1))]);
    const f = (v) => m.fmt(m.int ? v : Math.round(v));
    const names = colors.map((_, i) => {
      const lo = i ? edges[i - 1] : vs[0]; const hi = i < edges.length ? edges[i] : null;
      if (zeroClass && i === 0) return f(0);
      if (hi == null) return f(lo) + ' or more';
      return m.int ? (hi - 1 <= lo ? f(lo) : f(lo) + ' to ' + f(hi - 1)) : f(lo) + ' to ' + f(hi);
    });
    return { colors, classOf: (v) => { let c = 0; while (c < edges.length && v >= edges[c]) c++; return c; }, names, minText: f(vs[0]), maxText: f(vs[vs.length - 1]) };
  }
  function recolor() {
    const m = S.byId.get(state.metric); const dark = isDark(); const sc = scaleOf(m, dark);
    engine.setCountyColors(m.vals.map((v) => (v == null ? null : sc.colors[sc.classOf(v)])), NODATA[dark ? 'dark' : 'light']);
    current = { m, sc, hasNone: m.vals.some((v) => v == null) };
    renderLegend();
  }
  function legendTitle(m) {
    const pw = S.prodWin;
    switch (m.id) {
      case 'p12': return S.mLabel + ', ' + S.win;
      case 'chg': return 'Change in ' + S.word + ', ' + S.chgWin;
      case 'oil12': return 'Oil production, ' + pw + ' (barrels)';
      case 'gas12': return 'Gas production, ' + pw + ' (Bcf)';
      case 'prodchg': return 'Change in oil production, ' + pw + ' vs the 12 months before';
      case 'e213': return 'Oilfield-service establishments (NAICS 213), ' + S.cbp.year;
      case 'e211': return 'Oil and gas extraction establishments (NAICS 211), ' + S.cbp.year;
      case 'mineral': return 'Mineral property value, ' + S.minr.year + ' (USD)';
      case 'oemp': case 'semp': case 'owage': return m.label + ', ' + S.lab.year;
      default: return m.label;
    }
  }
  function renderLegend() {
    const { m, sc, hasNone } = current; const dark = isDark();
    const title = legendTitle(m);
    const ramp = el('div', { class: 'lg-ramp' }, sc.colors.map((c, i) => {
      const sw = el('span', { class: 'lg-sw', title: sc.names[i] });
      sw.style.background = c; return sw;
    }));
    const nd = el('span', { class: 'lg-sw nodata' }); nd.style.background = NODATA[dark ? 'dark' : 'light'];
    const kids = [el('div', { class: 'lg-title', text: title })];
    if (!sc.empty) kids.push(ramp, el('div', { class: 'lg-ends' }, el('span', { text: sc.minText }), el('span', { text: sc.maxText })));
    if (hasNone) kids.push(el('div', { class: 'lg-nodata' }, nd, el('span', { text: m.nodata + (S.multi && m.tx ? '; not available outside Texas' : '') })));
    // with several states the dots take their state's color, so the legend says which is which
    if (S.multi && state.layers.has('permits')) {
      kids.push(el('div', { class: 'lg-states', role: 'group', 'aria-label': ucFirst(dotName(S.states)) + 's by state' }, S.states.map((id) => el('span', { class: 'lg-st st-' + id.toLowerCase() },
        el('i', { 'aria-hidden': 'true' }), stateOf(id).name + (measureOf(id).id === 'spuds' ? ' (spuds)' : '')))));
    }
    if (['oil12', 'gas12', 'prodchg'].includes(m.id)) kids.push(el('div', { class: 'lg-basin lg-note' }, el('span', { text: 'County volumes are the RRC’s allocation of multi-county leases: an estimate.' })));
    if (state.basin) { const b = S.B.byId.get(state.basin); kids.push(el('div', { class: 'lg-basin' }, el('i', { 'aria-hidden': 'true' }), el('span', { text: 'Outlined: ' + b.name + ', ' + b.fips.length + ' counties' }))); }
    ui.legend.replaceChildren(...kids);
  }

  /* ---------- text helpers ---------- */
  const countyName = (f) => { const c = S.G.byFips.get(f); return c ? c.n : ''; };
  // "Harmon County" ("Green Canyon area" offshore), and the state's letters after it when several states are shown (two states have a Harmon or a Jackson)
  const countyTitle = (f) => placeTitle(countyState(f), countyName(f)) + (S.multi ? ', ' + countyState(f) : '');
  function metricText(m, i) {
    const v = m.vals[i]; const cst = countyState(S.G.counties[i].f); const w = measureOf(cst).short;
    if (v == null) return m.tx && cst !== 'TX' ? NOT_TEXAS : m.nodata;
    if (m.id === 'chg') {
      const h = S.halvesBy[i];
      return h.b === 0 ? 'New activity (none in the prior 12 months)' : signed(h.f) + ' (' + fmt.format(h.a) + ' vs ' + fmt.format(h.b) + ' ' + w + ')';
    }
    if (m.id === 'prodchg') {
      const h = S.prodHalves[i];
      return h.b === 0 ? 'New production (none in the prior 12 months)' : signed(h.f) + ' (' + compactFmt.format(h.a) + ' vs ' + compactFmt.format(h.b) + ' bbl)';
    }
    return m.fmt(v) + (m.id === 'p12' ? ' ' + countWord(cst, v) : m.unit && m.id !== 'depth' && m.id !== 'owage' ? ' ' + m.unit : m.id === 'owage' ? ' a week' : '');
  }
  const permitDate = (i) => dayLabel(S.P.t0 + S.P.t[i] * 864e5);
  const facCap = (l, it) => (it.cap == null ? 'Capacity not published' : fmt.format(it.cap) + ' ' + l.unit);

  /* ---------- tooltips ---------- */
  function onHover(hit, cx, cy) {
    if (!hit) { hideTip(); return; }
    const m = current.m; let rows;
    if (hit.type === 'county') {
      const c = S.G.counties[hit.i]; const cst = countyState(c.f);
      rows = [tipRow(placeTitle(cst, c.n) + (S.multi ? ', ' + cst : '')), tipRow(metricText(m, hit.i), m.id === 'p12' ? '' : m.label)];
      if (['oil12', 'gas12', 'prodchg'].includes(m.id)) rows.push(el('div', { class: 'tip-head', text: S.prodWin + '. RRC allocation of multi-county leases (an estimate)' }));
      if (m.id !== 'p12') rows.push(tipRow(fmt.format(S.metrics[0].vals[hit.i]), measureOf(cst).noun + ', 12 mo to ' + S.endOf(cst)));
    } else if (hit.type === 'pt') {
      const i = hit.i; const o = S.P.op[i]; const spud = measureOf(pointState(S.P.fips[i])).id === 'spuds';
      rows = [tipRow(o >= 0 ? S.pm.ops[o] : 'Operator not listed'),
        tipRow((spud ? 'Spudded ' : 'Issued ') + permitDate(i), spud ? 'well spudded' : 'new-drill permit'),
        tipRow(S.P.depth[i] ? fmt.format(S.P.depth[i] * 100) + ' ft deep' : 'Depth not reported', countyTitle(pointCountyKey(S.P.fips[i])))];
    } else if (hit.type === 'fac') {
      const l = S.infra.layers.find((q) => q.id === hit.layer); const it = l.items[hit.j];
      rows = [tipRow(it.n), tipRow(it.c, FAC_NAME[l.id] || l.label), tipRow(facCap(l, it))];
    } else {
      const z = S.zips.list[hit.j];
      rows = [tipRow('ZIP ' + z.zip, fmt.format(z.total) + ' companies'), tipRow(fmt.format(z.likely) + ' likely', fmt.format(z.isNew) + ' new, ' + fmt.format(z.rrc) + ' matched to an RRC operator')];
    }
    showTip(rows, cx, cy);
  }

  /* ---------- selection ---------- */
  const announce = (t) => { ui.live.textContent = t; };
  function hashParams() {
    const p = new URLSearchParams();
    if (state.county) p.set('county', state.county);
    if (state.metric !== 'p12') p.set('metric', state.metric);
    if (state.basin) p.set('basin', state.basin);
    const ls = LAYER_DEFS.map((d) => d.id).filter((id) => state.layers.has(id));
    if (ls.join() !== 'permits') p.set('layers', ls.join());
    if (state.op) p.set('op', state.op);
    if (state.zip) p.set('zip', state.zip);
    return p;
  }
  function writeHash() { if (isMapActive()) replaceHash('map', hashParams()); }
  const shareUrl = () => { const q = queryText(hashParams()); return absoluteLink('#map' + (q ? '?' + q : '')); };
  function afterChange() { renderPanel(); writeHash(); }
  // On phone widths the sheet sits over the lower part of the map. This is the height it covers (plus a margin), measured from
  // layout so the slide-in transform does not matter; 0 on desktop and while the sheet is closed.
  function coverPx() {
    if (!mq.matches || !ui.panel.classList.contains('is-open')) return 0;
    const sr = ui.stage.getBoundingClientRect(); const cs = getComputedStyle(ui.panel);
    const h = ui.panel.offsetHeight; const gap = parseFloat(cs.bottom) || 0;
    const top = cs.position === 'fixed' ? window.innerHeight - gap - h : sr.bottom - gap - h;
    return Math.round(clamp(sr.bottom - top, 0, sr.height * 0.75)) + 12;
  }
  // fit a selection into the part of the map the sheet leaves uncovered
  const fitCounty = (i) => { engine.setPadBottom(coverPx()); engine.fitCounty(i); };
  const fitOp = (idx) => { engine.setPadBottom(coverPx()); return engine.fitOp(idx); };
  const fitBasin = (b) => { engine.setPadBottom(coverPx()); engine.fitBox(b.bb, { pad: 34, maxZoom: 7 }); };
  // frame a basin (or all of Texas) and outline its counties; unknown ids are ignored
  function setBasin(id, { fit = true, write = true } = {}) {
    const b = id && S.B ? S.B.byId.get(id) : null;
    state.basin = b ? b.id : null;
    if (ui.basinSel) ui.basinSel.value = state.basin || '';
    engine.setBasin(b);
    renderLegend(); renderNotes();
    if (!state.county && !state.op && !state.detail) renderPanel();
    if (fit) { if (b) { fitBasin(b); scrollSoon(); } else if (!state.county && !state.op) { engine.setPadBottom(coverPx()); engine.reset(); } }
    if (write) writeHash();
  }
  const focusAt = (x, y, zoom, keepZoom) => { engine.setPadBottom(coverPx()); engine.focusXY(x, y, zoom, keepZoom); };
  function focusDetail(d) {
    if (d.type === 'pt') focusAt(S.P.x[d.i], S.P.y[d.i], 3, true);
    else if (d.type === 'zip') { const z = S.zips.list[d.j]; focusAt(z.x, z.y, 4, true); }
    else { const it = S.infra.layers.find((q) => q.id === d.layer).items[d.j]; focusAt(it.x, it.y, 3, true); }
  }
  // bring the whole map on screen (below the sticky header) when it is partly scrolled out of view
  function bringMapIntoView() {
    if (!mq.matches || !isMapActive() || ui.stage.hidden) return;
    const top = document.querySelector('.top').offsetHeight + 8; const r = ui.stage.getBoundingClientRect();
    let dy = 0;
    if (r.top < top) dy = r.top - top;
    else if (r.bottom > window.innerHeight - 8) dy = Math.min(r.bottom - window.innerHeight + 8, r.top - top);
    if (Math.abs(dy) > 2) window.scrollBy({ top: dy, behavior: reduced() ? 'auto' : 'smooth' });
  }
  const scrollSoon = () => { if (mq.matches) setTimeout(bringMapIntoView, 90); }; // after the router's own scroll to top
  function setSel() {
    const c = state.county ? S.G.byFips.get(state.county).i : -1; const d = state.detail;
    engine.setSelection({ county: c, pt: d && d.type === 'pt' ? d.i : -1, zip: d && d.type === 'zip' ? d.j : -1, fac: d && d.type === 'fac' ? { layer: d.layer, j: d.j } : null });
  }
  function selectCounty(f, { fit = false } = {}) {
    state.county = f; state.detail = null; state.zip = null; setSel(); afterChange();
    if (f) {
      announce(placeTitle(countyState(f), countyName(f)) + ' selected. ' + metricText(current.m, S.G.byFips.get(f).i));
      if (fit) { fitCounty(S.G.byFips.get(f).i); scrollSoon(); }
    }
  }
  function selectDetail(d) {
    state.detail = d; state.zip = d.type === 'zip' ? S.zips.list[d.j].zip : null;
    if (d.type === 'pt') state.county = pointCountyKey(S.P.fips[d.i]);
    else if (d.type === 'fac') { const f = S.infra.layers.find((q) => q.id === d.layer).items[d.j].fips; if (f) state.county = f; }
    setSel(); afterChange();
    if (mq.matches) { focusDetail(d); scrollSoon(); }
  }
  function setOp(num, { fit = true } = {}) {
    state.op = num || null;
    const idx = num ? S.opIdx.get(num) : undefined;
    // -2 matches no point: an operator with no located permits shows an empty map layer, not everyone's dots
    engine.setOpFilter(!num ? -1 : idx == null ? -2 : idx);
    if (num && state.layers.has('permits') === false) { state.layers.add('permits'); syncLayers(); }
    afterChange();
    if (num && idx != null && fit) { fitOp(idx); scrollSoon(); }
  }
  function clearAll() {
    state.county = null; state.detail = null; state.zip = null;
    if (state.op) { state.op = null; engine.setOpFilter(-1); }
    setSel(); afterChange();
  }
  function onSelect(hit) {
    hideTip();
    if (!hit) { if (state.detail || state.county) { state.county = null; state.detail = null; state.zip = null; setSel(); afterChange(); } return; }
    if (hit.type === 'county') selectCounty(S.G.counties[hit.i].f, { fit: mq.matches });
    else selectDetail(hit);
  }

  /* ---------- panel ---------- */
  const kpi = (label, value, sub) => el('div', { class: 'kpi' }, el('span', { class: 'kpi-label', text: label }),
    el('strong', { class: 'kpi-value' }, value), sub ? el('span', { class: 'kpi-sub' }, sub) : null);
  const secHead = (title, sub, onClose) => el('div', { class: 'psec-h' }, el('div', {}, el('h2', { class: 'psec-title', text: title }), sub ? el('p', { class: 'psec-sub', text: sub }) : null),
    onClose ? el('button', { type: 'button', class: 'ibtn sm', 'aria-label': 'Close', title: 'Close', onclick: onClose }, '✕') : null);
  const btn = (text, fn, cls = 'btn sm') => el('button', { type: 'button', class: cls, onclick: fn, text });
  const noData = (text) => el('span', { class: 'nd', title: text }, '–', el('span', { class: 'sr-only', text }));
  function trendText(h) {
    if (h.f == null) return el('span', { class: 'muted', text: '–' });
    return h.f === Infinity ? el('span', { class: 'delta up' }, el('span', { class: 'arrow', 'aria-hidden': 'true', text: '▲' }), el('span', { text: 'new' })) : delta(h.f);
  }

  function countySection(i) {
    const c = S.G.counties[i]; const cst = countyState(c.f); const own = cst === 'TX'; const meas = measureOf(cst);
    const p = S.cp.counties[c.f]; const lb = own && S.lab ? S.lab.counties[c.f] : null; const co = own && S.cc ? S.cc.counties[c.f] : null;
    const h = S.halvesBy[i]; const m = p ? p.m : new Array(36).fill(0); const months = S.cp.monthsBy[cst];
    const cr = own && S.cpr ? S.cpr.counties[c.f] : null; const basin = own && S.B ? S.B.byFips.get(c.f) : null;
    const lab = (r, f, fm) => (r ? fm(r[f]) : noData(NO_BLS));
    const kp = [
      kpi((meas.id === 'spuds' ? 'Wells spudded' : 'New-drill permits') + ', 12 mo to ' + S.endOf(cst), fmt.format(p ? p.p12 : 0), h.a + h.b >= 5 ? [trendText(h), ' vs prior 12 full months'] : 'Too few to compare'),
      kpi('Average depth', p && p.depth ? fmt.format(p.depth) + ' ft' : noData(own ? 'No permits with a reported depth' : 'No reported depth')),
    ];
    // production, jobs, establishments, companies and mineral value are Texas records: another state's county says so once, below
    if (own && S.cpr) kp.push(
      kpi('Oil, 12 mo to ' + S.prodEnd, cr ? compactFmt.format(cr.o12) + ' bbl' : noData(NO_PROD), cr ? [delta(yoyf(cr.o12, cr.o12p)), ' vs the 12 before'] : null),
      kpi('Gas, 12 mo to ' + S.prodEnd, cr ? bcf(cr.g12) : noData(NO_PROD), cr ? [delta(yoyf(cr.g12, cr.g12p)), ' vs the 12 before'] : null));
    if (own && S.lab) kp.push(kpi('Oil & gas jobs', lab(lb && lb.o, 'emp', (v) => fmt.format(v)), lb && lb.o ? fmt.format(lb.o.estab) + ' establishments' : null),
      kpi('Services jobs', lab(lb && lb.s, 'emp', (v) => fmt.format(v)), lb && lb.s ? fmt.format(lb.s.estab) + ' establishments' : null),
      kpi('Oil & gas weekly wage', lab(lb && lb.o, 'wage', (v) => '$' + fmt.format(v))));
    if (own && S.cc) kp.push(kpi('Companies headquartered', fmt.format(co ? co.total : 0), co ? fmt.format(co.likely) + ' likely, ' + fmt.format(co.isNew) + ' new' : null));
    if (own && S.minr) { const mv = S.minr.counties[c.f]; kp.push(kpi('Mineral property value', mv && mv.v ? '$' + compactFmt.format(mv.v) : noData('No mineral value listed'), S.minr.year + ' tax year')); }
    const ops = ((p && p.ops) || []).slice(0, 6);
    const dots = S.ptCount.get(c.f) || 0;
    const est = own && S.cbp ? S.cbp.counties[c.f] : null;
    const prodRow = (label, vals, color, fmtVal) => el('div', { class: 'row' }, el('span', { class: 'kpi-label', text: label }), el('strong', { class: 'kpi-value', text: fmtVal(vals[vals.length - 1]) }),
      areaChart(vals, S.cpr.months, { w: 300, h: 58, color, unit: label, fmtVal, what: label }));
    const sizeRow = (code, label) => {
      const e = est && est[code]; if (!e) return null;
      return el('div', { class: 'row' }, el('span', { class: 'kpi-label', text: label + ': ' + fmt.format(e.estab) + (e.estab === 1 ? ' establishment' : ' establishments') }),
        histChart(e.sz, S.cbp.sizeClasses, { w: 300, h: 78, color: 'var(--s1)', what: label + ' by employees' }));
    };
    const code = placeOf(cst).code || 'FIPS ' + stateOf(cst).fips + countyCode(c.f); // the federal offshore's areas have no FIPS code
    return el('section', { class: 'psec' },
      secHead(placeTitle(cst, c.n), (S.multi ? stateOf(cst).name + ' · ' : '') + code, state.county ? clearAll : null),
      basin ? el('p', { class: 'psec-sub' }, el('button', { type: 'button', class: 'basin-chip', title: 'Outline this basin on the map', onclick: () => setBasin(basin.id) }, icon('layers', 14), basin.name)) : null,
      el('div', { class: 'kpis2' }, kp),
      own && S.lab && (!lb || !lb.o || !lb.s) ? el('p', { class: 'fine', text: 'Dashes mean the BLS withholds that county figure to protect individual employers.' }) : null,
      !own ? el('p', { class: 'fine', text: 'Production, jobs, establishments, companies and mineral value are Texas figures: not available for ' + inName(cst) + '.' }) : null,
      el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Monthly ' + (meas.id === 'spuds' ? 'wells spudded' : 'permits') + ', ' + monthLabel(months[0]) + ' to ' + monthLabel(months[35]) }),
        areaChart(m, months, { w: 300, h: 92 })),
      own && S.cpr ? el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Production, ' + monthLabel(S.cpr.months[0]) + ' to ' + monthLabel(S.cpr.months[S.cpr.months.length - 1]) }),
        cr ? el('div', { class: 'prod-rows' }, prodRow('Oil, barrels a month', cr.mo, 'var(--s3)', (v) => compactFmt.format(v)), prodRow('Gas, a month', cr.mg, 'var(--s3)', bcf))
          : el('p', { class: 'fine', text: 'No oil or gas production was reported here in these 36 months.' })) : null,
      est && (est['213'] || est['211']) ? el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Establishments by employees, ' + S.cbp.year }),
        el('div', { class: 'prod-rows' }, sizeRow('213', 'Oilfield services'), sizeRow('211', 'Oil and gas extraction')),
        el('p', { class: 'fine', text: 'Census County Business Patterns. Bars start at the smallest class (1 to 4 employees); the axis shows each class’s lower bound. Classes with fewer than 3 establishments are withheld.' })) : null,
      ops.length ? el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Top operators, last 12 months' }),
        el('ul', { class: 'plist' }, ops.map(([name, num, n]) => el('li', {},
          el('a', { class: 'plist-name', href: opsLink(name), text: name, title: name }),
          el('span', { class: 'plist-n', text: fmt.format(n) }),
          S.opIdx.has(num) ? el('a', { class: 'pill-link', href: '#map?op=' + num, 'aria-label': 'Show ' + name + ' on the map', text: 'Map' }) : null)))) : null,
      // no dot is either no location published for what happened here, or nothing happened here (most offshore areas have no well): say which, since only the first is a claim about the agency
      el('p', { class: 'fine', text: dots ? fmt.format(dots) + ' located ' + (meas.id === 'spuds' ? 'well' : 'permit') + ' dots in this ' + placeOf(cst).one + ' over 24 months. Counts above include every ' + meas.one + '.'
        : h.a + h.b === 0 ? 'No ' + (meas.id === 'spuds' ? 'wells were spudded' : 'new-drill permits were approved') + ' in this ' + placeOf(cst).one + ' in the last 24 months, so there is nothing to draw.'
          : 'No located ' + (meas.id === 'spuds' ? 'well' : 'permit') + ' dots here: ' + (own ? 'the RRC published no surface location for these permits.' : 'the ' + stateOf(cst).agency + ' published no location for these ' + meas.short + '.') }),
      el('div', { class: 'psec-actions' }, own ? el('a', { class: 'btn sm primary', href: '#companies?county=' + c.f, text: 'List companies' }) : null, btn('Zoom to ' + placeOf(cst).one, () => fitCounty(i))));
  }

  function operatorSection(num) {
    const colon = num.indexOf(':'); const ost = colon < 0 ? 'TX' : num.slice(0, colon); const raw = num.slice(colon + 1); const own = ost === 'TX';
    const meas = measureOf(ost); const spuds = meas.id === 'spuds';
    const o = S.opBy.get(num); const x = S.exBy.get(num); const idx = S.opIdx.get(num);
    const name = o ? o.name : idx != null ? S.pm.ops[idx] : 'Operator ' + raw;
    const h = x ? halves(x.m24) : null;
    const tc = x && x.fips ? S.G.byFips.get(x.fips) : null;
    const located = idx != null ? S.P.byOp.get(idx).length : 0;
    const total = x ? sum(x.m24) : 0;
    const pr = own ? S.prodBy.get(num) : null;
    const what = spuds ? 'wells spudded' : 'permits';
    const kp = x ? [
      kpi(spuds ? 'Wells spudded, 12 mo' : 'New wells, 12 mo', fmt.format(o ? o.new12 : 0), 'Prior 12 months: ' + fmt.format(x.prev12)),
      kpi('Trend', trendText(h), 'last 12 full months vs prior'),
      x.spud12 != null ? kpi('Spud, 12 mo', fmt.format(x.spud12), 'permits with a spud date') : null,
      kpi('Average depth', x.depth ? fmt.format(x.depth) + ' ft' : noData('Depth not reported')),
      kpi('Top ' + placeOf(ost).one, tc ? el('a', { href: '#map?county=' + tc.f, text: tc.n }) : 'n/a', x.counties ? fmt.format(x.counties) + ' ' + (x.counties === 1 ? placeOf(ost).one : placeOf(ost).many) + ' in 24 months' : null),
    ].filter(Boolean) : [kpi(spuds ? 'Wells spudded, 12 mo' : 'New wells, 12 mo', o ? fmt.format(o.new12) : noData('No data'))];
    if (pr) kp.push(kpi('Oil, 12 mo to ' + S.prodEnd, compactFmt.format(pr.o12) + ' bbl', pr.o12p > 0 ? [delta(pr.o12 / pr.o12p - 1), ' vs the 12 before'] : pr.o12 > 0 ? 'none in the 12 before' : null),
      kpi('Gas, 12 mo to ' + S.prodEnd, bcf(pr.g12), pr.g12p > 0 ? [delta(pr.g12 / pr.g12p - 1), ' vs the 12 before'] : null),
      kpi('Producing leases', fmt.format(pr.leases), 'in the latest 12 months'));
    return el('section', { class: 'psec psec-op' },
      secHead(name, (own ? 'Operator ' : stateOf(ost).name + ' operator ') + raw + (o ? ' · band ' + (o.band || 'none') : ''), null),
      el('div', { class: 'kpis2' }, kp),
      x ? el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Monthly ' + what + ', last 24 months' }), areaChart(x.m24, S.exMonthsBy[ost] || S.exMonths, { w: 300, h: 80 })) : null,
      pr ? el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Monthly oil, ' + monthLabel(S.opProd.months[0]) + ' to ' + monthLabel(S.opProd.months[S.opProd.months.length - 1]) }),
        areaChart(pr.mo, S.opProd.months, { w: 300, h: 80, color: 'var(--s3)', unit: 'barrels of oil', fmtVal: (v) => compactFmt.format(v), what: 'Monthly oil' })) : null,
      own && !pr && S.opProd ? el('p', { class: 'fine', text: 'No production figure for this operator in the RRC reports, so those cells are blank rather than zero.' }) : null,
      !own ? el('p', { class: 'fine', text: 'Oil and gas production by operator is a Texas record: not available for ' + inName(ost) + '.' }) : null,
      el('p', { class: 'fine', text: located
        ? 'Showing ' + fmt.format(located) + (total && located <= total ? ' of ' + fmt.format(total) + ' in 24 months' : '') + ' ' + what + ' that have a recorded ' + (own ? 'surface ' : '') + 'location. Other layers stay as set.'
        : 'None of this operator’s ' + what + ' has a recorded ' + (own ? 'surface ' : '') + 'location, so there is nothing to draw.' }),
      el('div', { class: 'psec-actions' }, el('a', { class: 'btn sm primary', href: opsLink(name), text: 'See in Operators' }),
        btn('Show all operators', () => { setOp(null); engine.setPadBottom(coverPx()); engine.reset(); })));
  }

  function detailSection(d) {
    if (d.type === 'pt') {
      const i = d.i; const o = S.P.op[i]; const f = pointCountyKey(S.P.fips[i]); const spud = measureOf(pointState(S.P.fips[i])).id === 'spuds';
      return el('section', { class: 'psec' }, secHead(spud ? 'Well spudded' : 'Drilling permit', permitDate(i), () => { state.detail = null; state.zip = null; setSel(); afterChange(); }),
        el('div', { class: 'kpis2' }, kpi('Operator', o >= 0 ? S.pm.ops[o] : 'Not listed'), kpi(cap(placeOf(countyState(f)).one), countyName(f) + (S.multi ? ', ' + countyState(f) : '')),
          kpi('Total depth', S.P.depth[i] ? fmt.format(S.P.depth[i] * 100) + ' ft' : noData('Depth not reported')), kpi('Type', spud ? 'New well, spudded' : 'New drill')),
        el('div', { class: 'psec-actions' }, o >= 0 ? btn('Show this operator', () => setOp(S.pm.opNums[o]), 'btn sm primary') : null));
    }
    if (d.type === 'fac') {
      const l = S.infra.layers.find((q) => q.id === d.layer); const it = l.items[d.j];
      return el('section', { class: 'psec' }, secHead(it.n, FAC_NAME[l.id] || l.label, () => { state.detail = null; setSel(); afterChange(); }),
        el('div', { class: 'kpis2' }, kpi('Company', it.c), kpi('Capacity', it.cap == null ? noData('Capacity not published') : fmt.format(it.cap), it.cap == null ? null : l.unit),
          kpi('County', it.fips ? countyName(it.fips) : 'n/a')));
    }
    const z = S.zips.list[d.j];
    return el('section', { class: 'psec' }, secHead('ZIP ' + z.zip, 'Companies in the pool', () => { state.detail = null; state.zip = null; setSel(); afterChange(); }),
      el('div', { class: 'kpis2' }, kpi('Companies', fmt.format(z.total)), kpi('Likely', fmt.format(z.likely)), kpi('New entities', fmt.format(z.isNew)), kpi('Matched to RRC', fmt.format(z.rrc))),
      el('p', { class: 'fine', text: 'Bubbles sit at the ZIP’s center. PO-box ZIPs with no Census center share their city’s point.' }),
      el('div', { class: 'psec-actions' }, el('a', { class: 'btn sm primary', href: '#companies?q=' + z.zip, text: 'List companies' })));
  }

  function glanceSection() {
    const m = current.m; const bs = state.basin ? S.B.byId.get(state.basin) : null;
    // a place is ranked on its change when it had enough in the last 12 months for a percentage to mean something: 20 permits or spuds, or 5 offshore, where 14 is the most any area has had
    const enough = (i) => S.halvesBy[i].a >= chgMinOf(countyState(S.G.counties[i].f));
    const order = m.vals.map((v, i) => [v, i]).filter((q) => q[0] != null && (m.kind !== 'seq' || q[0] !== 0) && (!bs || bs.set.has(q[1])) && (m.id !== 'chg' || (q[0] < 9 && enough(q[1])))
      && (m.id !== 'prodchg' || (q[0] < 9 && S.prodHalves[q[1]].a >= 1e6))).sort((a, b) => b[0] - a[0]).slice(0, 8);
    const max = order.length ? Math.max(1, order[0][0]) : 1;
    const where = ucFirst(statesIn(S.states));
    return el('section', { class: 'psec' }, secHead(bs ? bs.name + ' at a glance' : where + ' at a glance', bs ? bs.fips.length + ' counties, outlined on the map. Click one for details.' : 'Click ' + an(placesOr(S.states)) + ', a ' + dotName(S.states) + (S.tx ? ', a plant or a ZIP bubble' : '') + ' for details.'),
      bs ? el('div', { class: 'psec-actions' }, btn(S.multi ? 'Show every state' : 'Show all of Texas', () => setBasin(null))) : null,
      el('div', { class: 'psec-block' }, el('h3', { class: 'psec-h3', text: 'Top ' + placesWord(S.states) + (bs ? ' in the basin' : '') + ': ' + m.label.toLowerCase() + (m.id === 'chg' ? ' (' + chgMinPhrase(S.states) + ')' : m.id === 'prodchg' ? ' (1M+ barrels)' : '') }),
        el('ol', { class: 'mini-bars' }, order.map(([v, i]) => {
          const bar = el('span', { class: 'bar' }); bar.style.setProperty('--p', String(m.kind === 'seq' ? v / max : 0.001));
          return el('li', {}, el('button', { type: 'button', class: 'mini-row', onclick: () => selectCounty(S.G.counties[i].f, { fit: true }) },
            el('span', { class: 'bar-label', text: S.G.counties[i].n + (S.multi ? ', ' + countyState(S.G.counties[i].f) : '') }),
            m.kind === 'seq' ? el('span', { class: 'bar-track' }, bar) : null,
            el('span', { class: 'bar-value', text: m.kind === 'div' ? signed(v) : m.fmt(v) })));
        })),
        // nothing to rank because no county has the figure at all (New Mexico publishes no depth): say so, not an empty list
        m.vals.every((v) => v == null) ? el('p', { class: 'fine', text: 'No ' + placesOr(S.states) + ' has a figure for this: ' + m.nodata.charAt(0).toLowerCase() + m.nodata.slice(1) + '.' })
          // a list with nothing in it, said: no place had enough to be ranked on its change (an empty heading reads as a broken page)
          : !order.length && m.id === 'chg' ? el('p', { class: 'fine', text: 'No ' + placesOr(S.states) + (bs ? ' in the basin' : '') + ' had ' + chgMinPhrase(S.states) + ' in the last 12 months, so none is ranked on its change.' }) : null),
      el('p', { class: 'fine', text: 'Drag to pan, scroll or pinch to zoom, double-click to zoom in. Keyboard: focus the map, then use the arrow keys, plus, minus and 0.' }));
  }
  function renderPanel() {
    const secs = [];
    if (state.detail) secs.push(detailSection(state.detail));
    if (state.op) secs.push(operatorSection(state.op));
    if (state.county) secs.push(countySection(S.G.byFips.get(state.county).i));
    const open = secs.length > 0;
    if (!open) secs.push(glanceSection());
    ui.panelBody.replaceChildren(...secs);
    ui.panel.classList.toggle('is-open', open);
    ui.panelBody.scrollTop = 0;
    // keep the engine's idea of the covered strip current; closing the sheet only resets it, it never moves the view
    engine.setPadBottom(coverPx());
  }

  /* ---------- notes ---------- */
  function renderNotes() {
    const l = state.layers; const ids = S.states;
    // the share of each state's permits that have a location (each state's own file says; Texas's is the thin one)
    const per = ids.map((id) => {
      const cv = S.pm.coverageBy ? S.pm.coverageBy[id] : S.pm.coverage;
      return (S.multi ? stateOf(id).name + ': ' : '') + sharePct(cv.share24) + ' of the last 24 months and ' + sharePct(cv.share12) + ' of the last 12' + (id === 'TX' ? ', thinnest for 2026 and in the busiest counties' : '');
    });
    const items = [
      el('p', { class: 'map-note' }, el('strong', { text: 'Reading the map. ' }),
        ucFirst(placesOne(ids)) + ' shading, counts and trends use ' + everyOf(ids) + '. Dots show only ' + S.word + ' with a recorded ' + (ids.length === 1 && ids[0] === 'TX' ? 'surface ' : '') + 'location: '
        + per.join('; ') + '. Brighter dots are the last 12 months.'),
    ];
    // what each state counts, and how far its data runs (they end on different days)
    if (S.multi || ids.some((id) => measureOf(id).id === 'spuds')) {
      const spud = spudsNote(ids);
      items.push(el('p', { class: 'map-note' }, el('strong', { text: 'What is counted. ' }),
        (spud ? spud + '; spud dates are reported about two months late' + (S.multi ? ', and these counts are never added to permits' : '') + '. ' + (spudCaveat(ids) ? spudCaveat(ids) + ' ' : '') : '')
        + (S.multi ? 'Data runs to ' + listAnd(ids.map((id) => fmtDate(S.through[id]) + ' (' + stateOf(id).name + ')')) + '.' : '')));
    }
    const mTx = S.byId.get(state.metric);
    if (S.multi && mTx && mTx.tx) items.push(el('p', { class: 'map-note', text: 'This figure comes from Texas records, so the other states’ ' + placesWord(ids.filter((id) => id !== 'TX')) + ' are shown as not available, not as zero.' }));
    if (l.has('zips')) items.push(el('p', { class: 'map-note', text: 'Companies by ZIP: bubble area is the number of companies. 239 ZIPs with no Census center (PO boxes and the like) sit at their city’s center, so several ZIPs of one city can share a point.' }));
    const mid = state.metric;
    if (['oil12', 'gas12', 'prodchg'].includes(mid) && S.cpr) items.push(el('p', { class: 'map-note' }, el('strong', { text: 'Production. ' }),
      'Volumes operators reported to the Railroad Commission for the 12 complete months through ' + monthLabel(S.cpr.months[S.cpr.months.length - 1]) + ' (oil is crude plus condensate; gas is gas-well plus casinghead gas). The RRC splits leases that cross county lines, so county figures are estimates. Months still being filled in are not included. A county with no reported production is shown as no data, not zero.'));
    if (['e213', 'e211'].includes(mid) && S.cbp) items.push(el('p', { class: 'map-note' }, el('strong', { text: 'Establishments. ' }),
      'Count of establishments with payroll in March ' + S.cbp.year + ' (Census County Business Patterns), not jobs. A county with none is shaded as zero. For employment use the jobs views, which come from BLS.'));
    if (mid === 'mineral' && S.minr) items.push(el('p', { class: 'map-note' }, el('strong', { text: 'Mineral value. ' }),
      'Appraised value of oil, gas and other mineral reserves in the ' + S.minr.year + ' Texas Comptroller Property Value Study, before exemptions. It is a tax value, not production or reserves.'));
    if (state.basin) { const b = S.B.byId.get(state.basin); items.push(el('p', { class: 'map-note' }, el('strong', { text: b.name + '. ' }), b.fips.length + ' counties outlined; the rest of Texas is dimmed. ' + (b.note ? b.note.split(' RRC')[0] : ''))); }
    if (['refinery', 'gasplant', 'lng'].some((id) => l.has(id))) items.push(el('p', { class: 'map-note', text: 'Facilities: refineries and LNG from EIA reports, gas plants from EPA 2023 reporting (no capacity published). A few listed sites may have closed.' }));
    ui.notes.replaceChildren(...items);
  }

  /* ---------- table twin ---------- */
  let tSort = { key: 'p12', dir: -1 };
  function renderTable() {
    const ms = S.metrics; const cs = S.G.counties;
    const key = ms.some((m) => m.id === tSort.key) ? tSort.key : 'name';
    const mSort = S.byId.get(key);
    const rows = cs.map((c, i) => i).sort((a, b) => {
      if (key === 'name') return tSort.dir * cs[a].n.localeCompare(cs[b].n);
      const x = mSort.vals[a]; const y = mSort.vals[b];
      if (x == null && y == null) return cs[a].n.localeCompare(cs[b].n);
      if (x == null) return 1;
      if (y == null) return -1;
      return (x - y) * tSort.dir || cs[a].n.localeCompare(cs[b].n);
    });
    const th = (id, label, num) => {
      const b = el('button', { type: 'button', class: 'sort', text: label });
      b.addEventListener('click', () => { tSort = { key: id, dir: tSort.key === id ? -tSort.dir : id === 'name' ? 1 : -1 }; renderTable(); });
      return el('th', { scope: 'col', class: num ? 'num' : '', title: S.byId.has(id) ? legendTitle(S.byId.get(id)) : null, 'aria-sort': tSort.key === id ? (tSort.dir === 1 ? 'ascending' : 'descending') : 'none' }, b);
    };
    const cell = (m, i) => {
      const v = m.vals[i];
      if (v == null) return el('td', { class: 'num' }, noData(m.tx && countyState(cs[i].f) !== 'TX' ? NOT_TEXAS : m.nodata));
      const t = m.id === 'chg' ? (S.halvesBy[i].b === 0 ? 'new' : signed(v)) : m.id === 'prodchg' ? (S.prodHalves[i].b === 0 ? 'new' : signed(v)) : m.fmt(v);
      return el('td', { class: 'num' + (m.id === state.metric ? ' on' : ''), text: t });
    };
    const short = {
      p12: S.multi ? S.mLabel + ' (12 mo)' : S.word.replace(/^./, (ch) => ch.toUpperCase()) + ' (12 mo to ' + S.permitEnd + ')', chg: 'Change', depth: 'Avg depth', oil12: 'Oil (12 mo to ' + S.prodEnd + ')', gas12: 'Gas (12 mo to ' + S.prodEnd + ')', prodchg: 'Oil change to ' + S.prodEnd, oemp: 'Oil & gas jobs', semp: 'Services jobs',
      owage: 'O&G weekly wage', e213: 'Service estabs', e211: 'Extraction estabs', co: 'Companies', mineral: 'Mineral value',
    };
    const table = el('table', { class: 'grid' }, el('caption', { class: 'sr-only', text: ucFirst(placesWord(S.states)) + ' of ' + statesIn(S.states) + ' with the map metrics. Sorted by ' + (mSort ? mSort.label : placesOr(S.states) + ' name') + '.' }),
      el('thead', {}, el('tr', {}, th('name', cap(placesOr(S.states)), false), S.multi ? el('th', { scope: 'col', text: 'State' }) : null, ms.map((m) => th(m.id, short[m.id] || m.label, true)))),
      el('tbody', {}, rows.map((i) => el('tr', {},
        el('th', { scope: 'row' }, el('button', { type: 'button', class: 'link', text: cs[i].n, onclick: () => { setTable(false); selectCounty(cs[i].f, { fit: true }); } })),
        S.multi ? el('td', { text: countyState(cs[i].f) }) : null,
        ms.map((m) => cell(m, i))))));
    ui.tableWrap.replaceChildren(table);
  }
  function setTable(on) {
    state.table = on; hideTip();
    ui.stage.hidden = on; ui.tableWrap.hidden = !on; ui.notes.hidden = on;
    if (on && ui.tl.open) toggleReplay(false);
    ui.tlBtn.disabled = on;
    ui.tableBtn.setAttribute('aria-pressed', String(on)); ui.tableBtn.textContent = on ? 'Map view' : 'Table view';
    if (on) { tSort = { key: state.metric, dir: -1 }; renderTable(); } else { engine.resize(); engine.invalidate(); }
  }

  /* ---------- layers ---------- */
  function syncLayers() {
    const o = {}; for (const d of LAYER_DEFS) o[d.id] = state.layers.has(d.id);
    engine.setLayers(o);
    ui.chips.forEach((c, id) => { c.checked = state.layers.has(id); });
    renderNotes();
  }

  /* ---------- state from a link ---------- */
  function apply(params) {
    state.metric = 'p12'; state.layers = new Set(['permits']); state.county = null; state.op = null; state.zip = null; state.detail = null; state.basin = null;
    const mt = params.get('metric'); if (mt && S.byId.has(mt)) state.metric = mt;
    const bsn = params.get('basin'); if (bsn && S.B && S.B.byId.has(bsn)) state.basin = bsn;
    if (params.has('layers')) {
      const raw = params.get('layers');
      const ls = raw.split(',').map((x) => (x === 'zip' ? 'zips' : x)).filter((id) => LAYER_DEFS.some((d) => d.id === id) && layerAvailable(id));
      // an empty value means "no layers"; a value with nothing we know is ignored like any unknown parameter
      if (raw === '' || ls.length) state.layers = new Set(ls);
    }
    const cty = params.get('county'); if (cty && S.G.byFips.has(cty)) state.county = cty;
    const op = params.get('op'); const hasOp = op && (S.opIdx.has(op) || S.exBy.has(op) || S.opBy.has(op));
    if (hasOp) { state.op = op; state.layers.add('permits'); }
    const zip = params.get('zip');
    let zipHit = null;
    if (zip && S.zips && S.zips.byZip.has(zip)) { zipHit = S.zips.byZip.get(zip); state.zip = zip; state.layers.add('zips'); state.detail = { type: 'zip', j: zipHit }; }
    ui.metricSel.value = state.metric; if (ui.basinSel) ui.basinSel.value = state.basin || '';
    if (ui.tl.open) toggleReplay(false);
    engine.setOpFilter(!state.op ? -1 : S.opIdx.has(state.op) ? S.opIdx.get(state.op) : -2);
    engine.setBasin(state.basin ? S.B.byId.get(state.basin) : null);
    recolor(); setSel(); syncLayers(); renderPanel(); writeHash();
    if (zipHit != null) { const z = S.zips.list[zipHit]; focusAt(z.x, z.y, 7); }
    else if (state.op && S.opIdx.has(state.op)) fitOp(S.opIdx.get(state.op));
    else if (state.county) fitCounty(S.G.byFips.get(state.county).i);
    else if (state.basin) fitBasin(S.B.byId.get(state.basin));
    else engine.reset(false);
    if (state.detail || state.county || state.op || state.basin) scrollSoon();
    if (state.table) renderTable();
  }
  const layerAvailable = (id) => (id === 'permits' ? true : id === 'zips' ? Boolean(S.zips) : Boolean(S.infra && S.infra.layers.some((l) => l.id === id)));
  // what the dots are called, and the words for the replay
  const dotsLabel = () => (S.states.length === 1 && measureOf(S.states[0]).id === 'spuds' ? 'Wells spudded' : sameMeasure(S.states) ? 'Permits' : 'Permits and spuds');
  const drillLabel = () => (S.states.length === 1 ? stateOf(S.states[0]).drill || stateOf(S.states[0]).name + ' drill' : 'drilling');

  /* ---------- build ---------- */
  function buildUI() {
    const { G, P } = S;
    const groups = [...new Set(S.metrics.map((m) => m.group))];
    ui.metricSel = el('select', { class: 'input', id: 'map-metric' }, groups.map((g) => el('optgroup', { label: g }, S.metrics.filter((m) => m.group === g).map((m) => el('option', { value: m.id, text: m.label })))));
    ui.metricSel.addEventListener('change', () => { state.metric = ui.metricSel.value; recolor(); renderNotes(); if (!state.detail && !state.county && !state.op) renderPanel(); if (state.table) { tSort = { key: state.metric, dir: -1 }; renderTable(); } writeHash(); });
    ui.basinSel = S.B ? el('select', { class: 'input', id: 'map-basin' }, el('option', { value: '', text: S.multi ? 'All basins' : 'All of Texas' }), S.B.list.map((b) => el('option', { value: b.id, text: b.name }))) : null;
    if (ui.basinSel) ui.basinSel.addEventListener('change', () => setBasin(ui.basinSel.value || null));
    ui.chips = new Map();
    const defs = LAYER_DEFS.map((d) => (d.id !== 'permits' ? d : { ...d, label: dotsLabel(), color: S.multi ? 'var(--ink-2)' : 'var(--st-' + S.states[0].toLowerCase() + ')' }));
    const chips = defs.filter((d) => layerAvailable(d.id)).map((d) => {
      const box = el('input', { type: 'checkbox' });
      box.addEventListener('change', () => {
        if (box.checked) state.layers.add(d.id); else state.layers.delete(d.id);
        if (d.id === 'permits' && !box.checked && ui.tl.open) toggleReplay(false);
        syncLayers(); writeHash();
      });
      ui.chips.set(d.id, box);
      return el('label', { class: 'lchip' }, box, el('span', { class: 'lchip-body' }, shapeIcon(d.shape, d.color), d.label));
    });
    ui.tableBtn = el('button', { type: 'button', class: 'btn', 'aria-pressed': 'false', text: 'Table view' });
    ui.tableBtn.addEventListener('click', () => setTable(!state.table));
    ui.tlBtn = el('button', { type: 'button', class: 'btn', 'aria-pressed': 'false', title: 'Replay two years of located ' + S.word + ' by ' + (S.states.every((id) => measureOf(id).id === 'spuds') ? 'spud' : 'issue') + ' date' }, icon('play', 15), el('span', null, 'Watch', el('span', { class: 'hide-sm', text: ' ' + drillLabel() })));
    ui.tlBtn.addEventListener('click', () => toggleReplay());
    const bar = el('div', { class: 'map-bar' },
      el('label', { class: 'field' }, el('span', { class: 'field-label', text: 'Shade ' + placesWord(S.states) + ' by' }), ui.metricSel),
      ui.basinSel ? el('label', { class: 'field basin' }, el('span', { class: 'field-label', text: 'Basin' }), ui.basinSel) : null,
      el('div', { class: 'lchips', role: 'group', 'aria-label': 'Map layers' }, el('span', { class: 'field-label', 'aria-hidden': 'true', text: 'Layers' }), el('div', { class: 'lchips-row' }, chips)),
      el('div', { class: 'map-actions' }, ui.tlBtn, shareButton(shareUrl), ui.tableBtn));

    ui.canvas = el('canvas', { class: 'map-canvas' });
    ui.legend = el('div', { class: 'map-legend' });
    const zbtn = (label, text, fn) => el('button', { type: 'button', class: 'ibtn', 'aria-label': label, 'data-tip': label, onclick: fn }, text);
    ui.zin = zbtn('Zoom in', '+', () => engine.zoomBy(1.7)); ui.zout = zbtn('Zoom out', '−', () => engine.zoomBy(1 / 1.7));
    ui.zhome = zbtn('Reset view', '⌂', () => { engine.setPadBottom(coverPx()); engine.reset(); });
    ui.live = el('div', { class: 'sr-only', 'aria-live': 'polite' });
    ui.panelBody = el('div', { class: 'panel-body' });
    ui.panel = el('aside', { class: 'map-panel', 'aria-label': 'Map details' }, el('div', { class: 'sheet-grab', 'aria-hidden': 'true' }),
      el('button', { type: 'button', class: 'ibtn sheet-close', 'aria-label': 'Close details', onclick: clearAll }, '✕'), ui.panelBody);
    ui.stage = el('div', {
      class: 'map-stage', tabindex: '0', role: 'group', 'aria-roledescription': 'map',
      'aria-label': 'Map of the ' + placesWord(S.states) + ' of ' + statesIn(S.states) + ', ' + (S.tx ? 'permits and facilities' : S.word) + '. Arrow keys pan, plus and minus zoom, zero resets the view. Use Table view for a text version.',
    }, ui.canvas, el('div', { class: 'map-zoom' }, ui.zin, ui.zout, ui.zhome), ui.legend, ui.live);
    ui.tableWrap = el('div', { class: 'table-wrap map-table', hidden: true, tabindex: '0', role: 'region', 'aria-label': cap(placesOr(S.states)) + ' table, the text version of the map' });
    ui.notes = el('div', { class: 'map-notes' });
    ui.mainCard = el('div', { class: 'map-main card' }, ui.stage, ui.tableWrap, ui.notes);
    ui.shell = el('div', { class: 'map-shell' }, ui.mainCard);
    root.replaceChildren(bar, ui.shell);
    place();

    engine = createEngine(ui.canvas, ui.stage, G, P, S.zips, S.infra ? S.infra.layers : []);
    engine.setTheme(engineTheme());
    ui.tl = createTimelapse({ engine, t0: P.t0, label: 'Watch ' + drillLabel(), lead: 'Located ' + S.word.replace(' or ', ' and ') + ' only. ', thing: { one: 'located ' + (S.multi ? 'permit or spud' : S.word.replace(/s$/, '')), many: 'located ' + S.word }, note: replayNote() });
    ui.mainCard.insertBefore(ui.tl.bar, ui.notes);
    engine.on('hover', onHover); engine.on('select', onSelect);
    engine.on('view', (z) => { const k = z <= 1.01 ? 'min' : 'ok'; if (k !== lastZoomState) { lastZoomState = k; ui.zout.disabled = k === 'min'; } });
    if (new URLSearchParams(location.search).has('debug')) window.__map = { engine, state, S, tl: ui.tl, setBasin };
  }
  // the phone sheet sits in the stage, the desktop panel beside it
  const place = () => { if (ui.panel) (mq.matches ? ui.stage : ui.shell).append(ui.panel); };
  // what the replay says about the dots: how many permits have a location, state by state
  function replayNote() {
    const per = S.states.map((id) => {
      const cv = S.pm.coverageBy ? S.pm.coverageBy[id] : S.pm.coverage;
      return { id, a: sharePct(cv.share24), b: sharePct(cv.share12) };
    });
    if (S.states.length === 1) {
      const q = per[0];
      return 'Dots are the ' + q.a + ' of the last 24 months of ' + S.word + ' (' + q.b + ' of the last 12) with a recorded ' + (q.id === 'TX' ? 'surface ' : '')
        + 'location' + (q.id === 'TX' ? ', so the busiest counties look quiet' : '') + '. Read the shading for the full counts.';
    }
    return 'Dots are the ' + S.word + ' with a recorded location: ' + per.map((q) => stateOf(q.id).name + ' ' + q.a + ' of the last 24 months (' + q.b + ' of the last 12)').join(', ')
      + (S.tx ? '; the busiest Texas counties look quiet' : '') + '. Read the shading for the full counts.';
  }
  // the replay needs the permit layer; closing it hands the map back to the normal dots
  function toggleReplay(force) {
    const on = force == null ? !ui.tl.open : force;
    if (on) {
      if (state.table) setTable(false);
      if (!state.layers.has('permits')) { state.layers.add('permits'); syncLayers(); writeHash(); }
      ui.tl.show();
    } else ui.tl.hide();
    ui.tlBtn.setAttribute('aria-pressed', String(on));
    ui.tlBtn.replaceChildren(icon(on ? 'close' : 'play', 15), el('span', null, on ? 'Close' : 'Watch', el('span', { class: 'hide-sm', text: on ? ' replay' : ' ' + drillLabel() })));
    hideTip();
  }

  async function start() {
    if (started) return;
    started = true;
    const states = activeStates(); buildKey = statesKey(states); const mine = ++gen;
    root.replaceChildren(el('p', { class: 'map-loading', role: 'status', text: 'Loading the map…' }));
    let built;
    try {
      // Texas's own files only when Texas is shown; every other state's county file and operators (its shapes and dots come with getGeo and getPoints)
      const tx = states.includes('TX'); const others = states.filter((id) => id !== 'TX');
      const txOpt = (name) => (tx ? loadOpt(name) : null);
      const [G, ptsRes, cpTx, cpOthers, lab, cc, zips, infra, ex, ops, opDocs, cpr, cbp, minr, B, opProd] = await Promise.all([
        getGeo(states), getPoints(states), tx ? load('county-permits') : null, Promise.all(others.map((id) => load(stateOf(id).files.county))),
        txOpt('county-labor'), txOpt('county-companies'), tx ? getZips(states) : null, tx ? getInfra(states) : null,
        txOpt('operator-extras'), txOpt('operators'), Promise.all(others.map((id) => loadOpt(stateOf(id).files.operators))),
        txOpt('county-production'), txOpt('county-business'), txOpt('county-minerals'), tx ? getBasins(states).catch(() => null) : null, txOpt('operator-production')]);
      const docs = Object.fromEntries([...(tx ? [['TX', cpTx]] : []), ...others.map((id, i) => [id, cpOthers[i]])]);
      built = prepare({ G, ptsRes, cp: countyPermits(states, docs), lab, cc, zips, infra, ex, ops, cpr, cbp, minr, B, opProd, others: others.map((id, i) => ({ id, doc: opDocs[i] })) }, states);
    } catch (err) {
      if (mine === gen) {
        started = false; buildKey = '';
        root.replaceChildren(el('p', { class: 'empty', text: 'Could not load the map data. Reload the page to try again.' }));
      }
      return;
    }
    if (mine !== gen) return; // the states changed while this loaded: the newer build owns the page
    S = built;
    // how far each state's data runs (Texas's is the monthly permit master, the others' their own file), and the windows the legend names
    S.through = Object.fromEntries(states.map((id) => [id, id === 'TX' ? meta.sources.latest_permit : S.cp.asOfBy[id]]));
    S.endOf = (id) => monthLabel(S.through[id].slice(0, 7));
    if (states.length === 1) {
      const id = states[0]; const months = S.cp.monthsBy[id];
      S.win = dayLabel(yearStart(id, S.cp.asOfBy[id])) + ' to ' + fmtDate(S.through[id]);
      S.chgWin = monthLabel(months[24]) + ' to ' + monthLabel(months[35]) + ' vs the 12 months before';
      S.permitEnd = S.endOf(id);
    } else {
      S.win = 'the last 12 months'; S.chgWin = 'the last 12 full months vs the 12 months before'; S.permitEnd = 'each state’s latest month';
    }
    if (S.cpr) { const pm = S.cpr.months; S.prodEnd = monthLabel(pm[pm.length - 1]); S.prodWin = monthLabel(pm[pm.length - 12]) + ' to ' + S.prodEnd; }
    buildUI();
    apply(pending || new URLSearchParams());
    pending = null;
  }

  // another set of states: let go of the built map and build it again (a metric and the layers carry over when the new states have them)
  function rebuild() {
    hideTip();
    if (ui.tl) ui.tl.destroy();
    if (engine) engine.destroy();
    engine = null; S = null; started = false; buildKey = ''; state.table = false; ui.tl = null;
    if (!pending) {
      pending = new URLSearchParams();
      if (state.metric !== 'p12') pending.set('metric', state.metric);
      pending.set('layers', [...state.layers].join(','));
    }
    return start();
  }
  const forStates = () => statesKey(activeStates());

  // the listeners that outlive a build
  mq.addEventListener('change', () => { place(); if (engine) engine.setPadBottom(coverPx()); });
  onTheme(() => { if (engine && S) { engine.setTheme(engineTheme()); recolor(); } });
  document.addEventListener('keydown', (e) => {
    if (!engine || e.key !== 'Escape' || !isMapActive() || state.table) return;
    if (document.activeElement && /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    if (state.detail || state.county || state.op) { e.preventDefault(); clearAll(); }
  });

  return {
    activate() {
      const go = started && buildKey !== forStates() ? rebuild() : start();
      return Promise.resolve(go).then(() => { if (engine) { engine.resize(); engine.invalidate(); } });
    },
    deactivate() { hideTip(); if (ui.tl) ui.tl.pause(); },
    // the states shown changed while the map is on screen
    setStates() { return rebuild().then(() => { if (engine) { engine.resize(); engine.invalidate(); } }); },
    // a link with a query restarts the map from its defaults plus that query
    apply(params) {
      if (S && engine && buildKey === forStates()) apply(params);
      else { pending = params; if (started) rebuild(); else start(); }
    },
  };
}
