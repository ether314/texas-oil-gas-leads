// Daily report visuals: inline-SVG charts built from the design tokens. Text nodes only; styles go through the CSSOM
// (the page's Content-Security-Policy has no 'unsafe-inline'), so every dynamic value is a custom property.
import { el, svg, fmt, reduced, clamp } from './util.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { toWorld } from './geo.js';

/* ---------- dates: the pure helpers live in daily-dates.js (Node-testable); re-exported so the views import them from here ---------- */
import { at, weekday, fmtMd, fmtDow, fmtLong, monthName, addDays } from './daily-dates.js';
export { fmtMd, fmtDow, fmtLong, addDays };
export const mb = (bytes) => (bytes >= 1 << 30 ? (bytes / (1 << 30)).toFixed(2) + ' GB' : bytes >= 1 << 20 ? (bytes / (1 << 20)).toFixed(1) + ' MB' : Math.round(bytes / 1024) + ' KB');

const nice = (v) => (v <= 10 ? 10 : v <= 60 ? Math.ceil(v / 10) * 10 : Math.ceil(v / 20) * 20);
const rise = (node, i) => { node.style.setProperty('--i', String(i)); return node; };

/* ---------- permits per business day: stacked bars, average line, the last day lit ---------- */
// series: [{ label, cls, values }], bottom segment first; a value is null for a day that state has no data for. total[i] is the
// sum shown over the day; avgText names the average line (default: the average rounded to a whole number). A top of 12 or less
// is rounded up to a multiple of 4 so every axis tick is a whole number (Oklahoma alone has counts that small).
const topRound = (x, y, w, h, r) => (r > 0 && h > r
  ? 'M' + x + ' ' + (y + h) + 'V' + (y + r) + 'Q' + x + ' ' + y + ' ' + (x + r) + ' ' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ' ' + y + ' ' + (x + w) + ' ' + (y + r) + 'V' + (y + h) + 'Z'
  : 'M' + x + ' ' + (y + h) + 'V' + y + 'H' + (x + w) + 'V' + (y + h) + 'Z');
export function trendBars({ days, series, total, avg, label, unit = 'new-drill permits', avgText = null }) {
  const W = 640; const H = 236; const L = 34; const R = 8; const T = 24; const B = 30;
  const top = Math.max(1, ...total, avg || 0);
  const n = days.length; const max = top <= 12 ? Math.ceil(top / 4) * 4 : nice(top);
  const cw = (W - L - R) / n; const bw = Math.max(3, cw * 0.68);
  const x = (i) => L + cw * i + (cw - bw) / 2; const y = (v) => T + (H - T - B) * (1 - v / max);
  const root = svg('svg', { class: 'dr-chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': label });
  for (let k = 0; k <= 4; k++) {
    const v = (max / 4) * k;
    root.append(svg('line', { class: 'dr-grid', x1: L, x2: W - R, y1: y(v), y2: y(v) }), svg('text', { class: 'dr-ax', x: L - 6, y: y(v) + 3.5, 'text-anchor': 'end', text: String(Math.round(v)) }));
  }
  const last = n - 1;
  days.forEach((d, i) => {
    const g = svg('g', { class: 'dr-barg' + (i === last ? ' on' : '') });
    const live = series.filter((s) => s.values[i] > 0);
    let acc = 0;
    live.forEach((s, k) => {
      const v = s.values[i]; const y1 = y(acc + v); const h = Math.max(0, y(acc) - y1);
      g.append(rise(svg('path', { class: 'dr-bar ' + s.cls, d: topRound(+x(i).toFixed(2), +y1.toFixed(2), +bw.toFixed(2), +h.toFixed(2), k === live.length - 1 ? Math.min(3, bw / 3) : 0) }), i));
      acc += v;
    });
    const hit = svg('rect', { class: 'dr-hit', x: L + cw * i, y: T, width: cw, height: H - T - B });
    hit.addEventListener('pointermove', (e) => showTip([tipRow(fmtDow(d), ''), tipRow(fmt.format(total[i]), unit),
      ...series.map((s) => (s.values[i] == null ? tipRow(s.label, 'no data this day') : s.values[i] ? tipRow(fmt.format(s.values[i]), s.label) : null))], e.clientX, e.clientY));
    hit.addEventListener('pointerleave', hideTip);
    g.append(hit);
    root.append(g);
  });
  if (avg) {
    root.append(svg('line', { class: 'dr-avg', x1: L, x2: W - R, y1: y(avg), y2: y(avg) }),
      svg('text', { class: 'dr-ax avg', x: L + 5, y: y(avg) - 6, 'text-anchor': 'start', text: '20-day average ' + (avgText || Math.round(avg)) }));
  }
  root.append(svg('text', { class: 'dr-val', x: x(last) + bw / 2, y: y(total[last]) - 6, 'text-anchor': 'middle', text: fmt.format(total[last]) }));
  const marks = [0, Math.floor(last / 2), last];
  marks.forEach((i, k) => root.append(svg('text', { class: 'dr-ax', x: x(i) + bw / 2, y: H - 9, 'text-anchor': k === 0 ? 'start' : k === 2 ? 'end' : 'middle', text: fmtMd(days[i]) })));
  return root;
}

/* ---------- the states by county: shaded counties, glowing bubbles, the leader pulsing ----------
   G holds the counties of every state shown, each keyed by state + FIPS (daily-data.js ck) and carrying its state in c.s.
   opts.only: the state ids to draw (the map is cropped to them); opts.place names the area in the label; opts.showState adds
   ", TX" to county names, for when the map holds more than one state. Bubbles and labels are scaled with the crop so a map of
   one state looks like the map of the whole area. */
const dCache = new WeakMap();
function countyPath(c) {
  if (!dCache.has(c)) {
    dCache.set(c, c.rings.map((xy) => {
      let d = 'M' + xy[0].toFixed(1) + ' ' + xy[1].toFixed(1);
      for (let i = 2; i < xy.length; i += 2) d += 'L' + xy[i].toFixed(1) + ' ' + xy[i + 1].toFixed(1);
      return d + 'Z';
    }).join(''));
  }
  return dCache.get(c);
}
export function countyMap(G, layers, first, opts = {}) {
  const place = opts.place || 'Texas';
  const only = opts.only ? new Set(opts.only) : null;
  const shown = G.counties.filter((c) => !only || only.has(c.s));
  const nm = (c) => c.n + (opts.showState ? ', ' + c.s : '');
  let vb = [0, 0, G.W, Math.ceil(G.H)];
  if (only && shown.length) {
    const x0 = Math.min(...shown.map((c) => c.bb[0])) - 10; const y0 = Math.min(...shown.map((c) => c.bb[1])) - 10;
    vb = [x0, y0, Math.max(...shown.map((c) => c.bb[2])) + 10 - x0, Math.max(...shown.map((c) => c.bb[3])) + 10 - y0];
  }
  const k = vb[2] / G.W; // world units per 1000: the crop's scale against the whole area
  const root = svg('svg', { class: 'dr-map', viewBox: vb.map((v) => v.toFixed(1)).join(' '), role: 'img', 'aria-label': '' });
  root.style.setProperty('--ml', (15 * k).toFixed(2) + 'px');
  const base = svg('g', { class: 'dr-counties' });
  const paths = new Map();
  for (const c of shown) {
    const p = svg('path', { class: 'dr-county', d: countyPath(c), 'data-f': c.f });
    base.append(p); paths.set(c.f, p);
  }
  const bub = svg('g', { class: 'dr-bubbles' });
  root.append(base, bub);
  let cur = null;
  const unit = opts.unit || { permits: 'new-drill permits issued', pending: 'applications waiting', completions: 'completions approved' };
  function set(id) {
    cur = id;
    const L = layers[id] || { map: new Map(), label: '' };
    root.dataset.layer = id;
    const max = Math.max(1, ...L.map.values());
    paths.forEach((p, f) => p.style.setProperty('--k', String(L.map.has(f) ? 0.18 + 0.82 * Math.sqrt(L.map.get(f) / max) : 0)));
    bub.replaceChildren();
    const ranked = [...L.map.entries()].filter(([f]) => paths.has(f)).sort((a, b) => b[1] - a[1]);
    ranked.forEach(([f, v], i) => {
      const c = G.byFips.get(f);
      const r = (6 + 17 * Math.sqrt(v / max)) * k;
      if (i === 0 && !reduced()) bub.append(svg('circle', { class: 'dr-pulse', cx: c.lx, cy: c.ly, r }));
      bub.append(rise(svg('circle', { class: 'dr-bubble', cx: c.lx, cy: c.ly, r }), i));
      if (i < 3) bub.append(svg('text', { class: 'dr-maplabel', x: c.lx, y: c.ly - r - 5 * k, 'text-anchor': 'middle', text: nm(c) + ' · ' + fmt.format(v) }));
    });
    root.setAttribute('aria-label', ranked.length ? 'Map of ' + place + ' counties. ' + ranked.slice(0, 3).map(([f, v]) => nm(G.byFips.get(f)) + ' ' + fmt.format(v)).join(', ') + ' ' + unit[id] + '.' : 'Map of ' + place + ' counties. No data for this layer.');
  }
  root.addEventListener('pointermove', (e) => {
    const f = e.target.dataset && e.target.dataset.f;
    const L = layers[cur];
    if (!f || !L) { hideTip(); return; }
    const c = G.byFips.get(f); const v = L.map.get(f) || 0;
    showTip([tipRow(nm(c) + ' County', ''), tipRow(fmt.format(v), unit[cur])], e.clientX, e.clientY);
  });
  root.addEventListener('pointerleave', hideTip);
  set(first);
  return { el: root, set };
}

/* ---------- GPS map: one day's wells as points on the county map, with pan and zoom ----------
   pts: [{ key, layer, f (county FIPS), lat, lon, aria, tip: [[strong, rest], ...] }]. Layers: 'permits' (dots) and 'surveys' (diamonds).
   Wheel zoom needs Ctrl or Cmd (a trackpad pinch sends that), so the page still scrolls; the buttons and + / - do the same. */
const GPS_AR = 3 / 2; // frame width over height; the CSS gives the frame aspect-ratio 3 / 2, so the viewBox never letterboxes
export function gpsMap(G, pts, { onPick }) {
  const W = G.W; const H = Math.ceil(G.H);
  const full = { cx: W / 2, cy: H / 2, w: Math.max(W, H * GPS_AR) * 1.02 };
  const view = { ...full };
  const root = svg('svg', { class: 'dr-map dr-gps', viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'xMidYMid meet', role: 'group', 'aria-label': 'Map of Texas counties with the day\'s wells as points. Each point is also listed in the table below the map.' });
  const base = svg('g', { class: 'dr-counties' });
  for (const c of G.counties) base.append(svg('path', { class: 'dr-county', d: countyPath(c), 'data-f': c.f }));
  const labels = svg('g', { class: 'dr-gps-labels', 'aria-hidden': 'true' });
  const counties = new Set(pts.map((p) => p.f));
  for (const c of G.counties) if (counties.has(c.f)) labels.append(svg('text', { class: 'cl', x: c.lx, y: c.ly, 'text-anchor': 'middle', text: c.n }));
  const ring = svg('circle', { class: 'dr-ring', r: 0, cx: -50, cy: -50 });
  const dots = svg('g', { class: 'dr-pts' });
  root.append(base, labels, dots, ring);

  const nodes = pts.map((p) => {
    const [x, y] = toWorld(p.lon, p.lat);
    const diamond = p.layer === 'surveys';
    const node = svg(diamond ? 'rect' : 'circle', { class: 'dr-pt ' + p.layer, tabindex: '-1', role: 'button', 'data-k': p.key, 'aria-label': p.aria });
    if (diamond) node.setAttribute('transform', 'rotate(45 ' + x.toFixed(2) + ' ' + y.toFixed(2) + ')');
    return { p, x, y, node, diamond, on: true };
  });
  nodes.sort((a, b) => (a.diamond ? 1 : 0) - (b.diamond ? 1 : 0)); // diamonds sit on top of dots
  nodes.forEach((n) => dots.append(n.node));
  const byKey = new Map(nodes.map((n) => [n.p.key, n]));
  let selKey = null;

  const clampView = () => { view.w = clamp(view.w, 12, full.w); view.cx = clamp(view.cx, 0, W); view.cy = clamp(view.cy, 0, H); };
  function size(n, r) {
    if (n.diamond) { const a = r * 0.88; n.node.setAttribute('x', (n.x - a).toFixed(2)); n.node.setAttribute('y', (n.y - a).toFixed(2)); n.node.setAttribute('width', (2 * a).toFixed(2)); n.node.setAttribute('height', (2 * a).toFixed(2)); } else { n.node.setAttribute('cx', n.x.toFixed(2)); n.node.setAttribute('cy', n.y.toFixed(2)); n.node.setAttribute('r', r.toFixed(2)); }
  }
  function apply() {
    const h = view.w / GPS_AR;
    root.setAttribute('viewBox', [view.cx - view.w / 2, view.cy - h / 2, view.w, h].map((v) => v.toFixed(2)).join(' '));
    const px = root.getBoundingClientRect().width || 640;
    const k = px / view.w; // screen pixels per world unit: points and labels keep their screen size at every zoom
    root.style.setProperty('--lf', (12 / k).toFixed(3) + 'px');
    nodes.forEach((n) => size(n, (n.p.key === selKey ? 8 : 5.6) / k));
    const s = byKey.get(selKey);
    if (s) { ring.setAttribute('cx', s.x.toFixed(2)); ring.setAttribute('cy', s.y.toFixed(2)); ring.setAttribute('r', (15 / k).toFixed(2)); } else ring.setAttribute('r', '0');
    labels.style.display = view.w < 420 ? '' : 'none';
    root.classList.toggle('zoomed', view.w < full.w * 0.9); // CSS: a zoomed map takes one-finger drags, an unzoomed one lets the page scroll
  }
  function fit() {
    const v = nodes.filter((n) => n.on);
    if (!v.length) Object.assign(view, full);
    else {
      const xs = v.map((n) => n.x); const ys = v.map((n) => n.y);
      const x0 = Math.min(...xs); const x1 = Math.max(...xs); const y0 = Math.min(...ys); const y1 = Math.max(...ys);
      view.cx = (x0 + x1) / 2; view.cy = (y0 + y1) / 2;
      view.w = Math.max((x1 - x0) * 1.3, (y1 - y0) * 1.3 * GPS_AR, 80);
    }
    clampView(); apply();
  }
  function zoomBy(f, cxp, cyp) {
    const r = root.getBoundingClientRect();
    const fx = cxp == null ? 0.5 : (cxp - r.left) / r.width; const fy = cyp == null ? 0.5 : (cyp - r.top) / r.height;
    const nw = clamp(view.w / f, 12, full.w);
    const wx = view.cx + (fx - 0.5) * view.w; const wy = view.cy + (fy - 0.5) * view.w / GPS_AR;
    view.cx = wx - (fx - 0.5) * nw; view.cy = wy - (fy - 0.5) * nw / GPS_AR; view.w = nw;
    clampView(); apply();
  }
  function setTab(n) { nodes.forEach((x) => x.node.setAttribute('tabindex', x === n ? '0' : '-1')); }
  const tipFor = (n, x, y) => showTip(n.p.tip.map(([a, b]) => tipRow(a, b)), x, y);

  /* pan, tooltip, pick */
  let drag = null;
  root.addEventListener('pointerdown', (e) => {
    if (e.button > 0 || (e.target.closest && e.target.closest('.dr-pt'))) return;
    drag = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, id: e.pointerId };
    try { root.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic pointer */ }
    hideTip();
  });
  root.addEventListener('pointermove', (e) => {
    if (drag && e.pointerId === drag.id) {
      const k = view.w / root.getBoundingClientRect().width;
      view.cx = drag.cx - (e.clientX - drag.x) * k; view.cy = drag.cy - (e.clientY - drag.y) * k;
      clampView(); apply(); return;
    }
    const t = e.target.closest && e.target.closest('.dr-pt');
    if (t && byKey.has(t.dataset.k)) tipFor(byKey.get(t.dataset.k), e.clientX, e.clientY); else hideTip();
  });
  const endDrag = (e) => { if (drag && e.pointerId === drag.id) drag = null; };
  root.addEventListener('pointerup', endDrag); root.addEventListener('pointercancel', endDrag);
  root.addEventListener('pointerleave', hideTip);
  root.addEventListener('click', (e) => { const t = e.target.closest && e.target.closest('.dr-pt'); if (t) onPick(t.dataset.k); });
  root.addEventListener('wheel', (e) => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); zoomBy(Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0022)), e.clientX, e.clientY); }, { passive: false });
  root.addEventListener('focusin', (e) => { const t = e.target.closest && e.target.closest('.dr-pt'); if (t && byKey.has(t.dataset.k)) { const r = t.getBoundingClientRect(); tipFor(byKey.get(t.dataset.k), r.left + r.width / 2, r.bottom); } });
  root.addEventListener('focusout', hideTip);
  root.addEventListener('keydown', (e) => {
    const t = e.target.closest && e.target.closest('.dr-pt');
    if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onPick(t.dataset.k); return; }
    if (t && ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
      e.preventDefault();
      const v = nodes.filter((n) => n.on); const i = v.indexOf(byKey.get(t.dataset.k));
      const j = e.key === 'Home' ? 0 : e.key === 'End' ? v.length - 1 : (i + (e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1) + v.length) % v.length;
      setTab(v[j]); v[j].node.focus({ preventScroll: true }); return;
    }
    if (e.key === '+' || e.key === '=') zoomBy(1.5); else if (e.key === '-' || e.key === '_') zoomBy(1 / 1.5); else if (e.key === '0') fit();
  });

  const wrap = el('div', { class: 'dr-gpswrap' }, root);
  if ('ResizeObserver' in window) new ResizeObserver(() => apply()).observe(wrap);
  fit();
  const first = nodes[0];
  if (first) setTab(first);

  return {
    el: wrap, fit, zoomIn: () => zoomBy(1.5), zoomOut: () => zoomBy(1 / 1.5),
    all: () => { Object.assign(view, full); apply(); },
    mark(key) {
      selKey = byKey.has(key) ? key : null;
      nodes.forEach((n) => n.node.classList.toggle('sel', n.p.key === selKey));
      const s = byKey.get(selKey);
      if (s) { dots.append(s.node); setTab(s); ring.classList.add('pulse'); }
      apply();
    },
    // w: world units across, about a county and its neighbors (a county is 25-45 units wide)
    focusOn(key, w = 110) { const n = byKey.get(key); if (!n) return; view.cx = n.x; view.cy = n.y; view.w = w; clampView(); apply(); },
    setLayer(id, on) {
      nodes.forEach((n) => { if (n.p.layer === id) { n.on = on; n.node.classList.toggle('off', !on); } });
      const v = nodes.find((n) => n.on); if (v) setTab(v);
    },
  };
}

/* ---------- the 92-day ribbon: one bar per report day, stacked by state, the selected day lit; arrow keys move a day ----------
   days: merged report days (daily-data.js mergeDays), ids: the states shown, bottom first, tip(day): the tooltip rows.
   A day whose permit day is the previous report's is a grey stub; a day some state has no report for is dashed. */
export function ribbon({ days, ids, selected, onPick, tip }) {
  const n = days.length; const bw = 9; const gap = 3; const W = n * (bw + gap) + 6; const H = 84; const T = 8; const B = 18;
  const room = H - T - B - 5;
  const max = Math.max(10, ...days.map((r) => r.total));
  const root = svg('svg', { class: 'dr-ribbon', viewBox: '0 0 ' + W + ' ' + H, 'aria-hidden': 'true' });
  const groups = []; const xs = [];
  days.forEach((r, i) => {
    const x = 3 + i * (bw + gap); xs.push(x);
    const g = svg('g', { class: 'dr-rbg' + (r.fresh ? '' : ' off') + (r.live ? ' live' : '') + (r.partial ? ' partial' : '') });
    let tall = 4;
    if (!r.fresh) g.append(svg('rect', { class: 'dr-rb off', x, y: H - B - 4, width: bw, height: 4, rx: 2 }));
    else {
      const live = ids.filter((id) => r.parts[id] > 0);
      const segs = live.length ? live : [ids[0]]; let y = H - B;
      segs.forEach((id, k) => {
        const h = (k === 0 ? 5 : 0) + room * ((r.parts[id] || 0) / max);
        y -= h;
        g.append(svg('path', { class: 'dr-rb ' + id.toLowerCase(), d: topRound(x, +y.toFixed(2), bw, +h.toFixed(2), k === segs.length - 1 ? 2.5 : 0) }));
      });
      tall = H - B - y;
    }
    g.append(svg('rect', { class: 'dr-rbsel', x, y: +(H - B - tall).toFixed(2), width: bw, height: +tall.toFixed(2), rx: 2.5 }));
    g.append(svg('rect', { class: 'dr-rbhit', x: x - gap / 2, y: 0, width: bw + gap, height: H - B + 2, 'data-i': i }));
    groups.push(g); root.append(g);
    const firstOfMonth = r.d.slice(8) === '01'; // the left edge only gets a label when a month does not start within a few bars
    if (firstOfMonth || (i === 0 && !days.slice(1, 6).some((q) => q.d.slice(8) === '01'))) root.append(svg('text', { class: 'dr-ax', x, y: H - 4, text: fmtMd(r.d).split(' ')[0] }));
  });
  const wrap = el('div', { class: 'dr-ribbon-wrap', 'data-act': 'ribbon', role: 'slider', tabindex: '0', 'aria-label': 'Report day, 3-month archive. Arrow keys move one day.', 'aria-valuemin': '0', 'aria-valuemax': String(n - 1) }, root);
  let cur = -1;
  function mark(d) {
    cur = Math.max(0, days.findIndex((r) => r.d === d));
    groups.forEach((g, i) => g.classList.toggle('sel', i === cur));
    wrap.setAttribute('aria-valuenow', String(cur));
    wrap.setAttribute('aria-valuetext', fmtLong(days[cur].d));
    wrap.scrollLeft = Math.max(0, (xs[cur] / W) * wrap.scrollWidth - wrap.clientWidth / 2);
  }
  root.addEventListener('click', (e) => { const i = e.target.dataset && e.target.dataset.i; if (i != null) onPick(days[+i].d); });
  root.addEventListener('pointermove', (e) => {
    const i = e.target.dataset && e.target.dataset.i;
    if (i == null) { hideTip(); return; }
    showTip(tip(days[+i]), e.clientX, e.clientY);
  });
  root.addEventListener('pointerleave', hideTip);
  wrap.addEventListener('keydown', (e) => {
    const to = e.key === 'ArrowLeft' ? cur - 1 : e.key === 'ArrowRight' ? cur + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : null;
    if (to == null) return;
    e.preventDefault();
    if (to >= 0 && to < n) onPick(days[to].d);
  });
  mark(selected);
  return { el: wrap, mark };
}

/* ---------- calendar heat map: 7 rows (Mon to Sun), one column a week, a button per day ----------
   cells: [{ d, v, open, live }] in date order. d is the day the figure belongs to, open the report day a click opens. */
export function calendar({ cells, selected, label, format, none, onPick }) {
  const byDate = new Map(cells.map((c) => [c.d, c]));
  const first = cells[0].d; const last = cells[cells.length - 1].d;
  const span = Math.round((at(last) - at(first)) / 864e5) + 1;
  const max = Math.max(1, ...cells.map((c) => c.v).filter((v) => v != null));
  const monOffset = (weekday(first) + 6) % 7;
  const grid = el('div', { class: 'dr-cal', role: 'group', 'aria-label': label });
  for (let i = 0; i < monOffset; i++) grid.append(el('span', { class: 'dr-cell void', 'aria-hidden': 'true' }));
  const dates = [];
  for (let i = 0; i < span; i++) {
    const d = addDays(first, i); dates.push(d);
    const c = byDate.get(d); const v = c ? c.v : null; const sel = !!c && c.open === selected;
    const b = el('button', { type: 'button', class: 'dr-cell' + (v == null ? ' none' : '') + (sel ? ' sel' : '') + (c && c.live ? ' live' : ''), 'data-d': d, 'data-act': 'cal-' + d,
      disabled: !(c && c.open), 'aria-label': fmtDow(d) + ': ' + (v == null ? none : format(v)), 'aria-pressed': sel ? 'true' : 'false' });
    b.style.setProperty('--k', v == null ? '0' : String(0.14 + 0.86 * Math.sqrt(v / max)));
    if (c && c.open) b.addEventListener('click', () => onPick(c.open));
    b.addEventListener('pointermove', (e) => showTip([tipRow(fmtDow(d), ''), tipRow(v == null ? none : format(v), ''), c && c.open && c.open !== d ? tipRow('Opens', 'the ' + fmtMd(c.open) + ' report') : null], e.clientX, e.clientY));
    b.addEventListener('pointerleave', hideTip);
    grid.append(b);
  }
  const cols = Math.ceil((monOffset + span) / 7);
  grid.style.setProperty('--cols', String(cols));
  // a month name sits over the week that holds its 1st; the first week is named only when no month starts in the next one
  const months = el('div', { class: 'dr-cal-months', 'aria-hidden': 'true' });
  const starts = [];
  for (let c = 0; c < cols; c++) {
    let name = '';
    for (let k = 0; k < 7; k++) { const d = dates[c * 7 + k - monOffset]; if (d && d.slice(8) === '01') { name = monthName(d).slice(0, 3); break; } }
    starts.push(name);
  }
  if (!starts[0] && !starts[1]) starts[0] = monthName(first).slice(0, 3);
  starts.forEach((name) => months.append(el('span', { text: name })));
  months.style.setProperty('--cols', String(cols));
  return el('div', { class: 'dr-cal-wrap' }, months, grid);
}

/* ---------- small pieces ---------- */
export function ring(value, total, { size = 74 } = {}) {
  const r = 30; const c = 2 * Math.PI * r;
  const node = svg('svg', { class: 'dr-ring', viewBox: '0 0 76 76', width: size, height: size, role: 'img', 'aria-label': value + ' of ' + total + ' files' },
    svg('circle', { class: 'dr-ring-bg', cx: 38, cy: 38, r }),
    svg('circle', { class: 'dr-ring-fg', cx: 38, cy: 38, r, 'stroke-dasharray': c.toFixed(1), 'stroke-dashoffset': (c * (1 - value / total)).toFixed(1), transform: 'rotate(-90 38 38)' }),
    svg('text', { class: 'dr-ring-t', x: 38, y: 43, 'text-anchor': 'middle', text: value + '/' + total }));
  return node;
}

// a single stacked bar: parts [{label, value, cls}] and its legend
export function stack(parts, { total, format = (v) => fmt.format(v) } = {}) {
  const sum = total || parts.reduce((a, p) => a + p.value, 0) || 1;
  const bar = el('div', { class: 'dr-stack', role: 'img', 'aria-label': parts.map((p) => p.label + ' ' + format(p.value)).join(', ') });
  parts.forEach((p, i) => {
    const seg = el('span', { class: 'dr-seg c' + (i % 6), title: p.label + ': ' + format(p.value) });
    seg.style.setProperty('--w', String(p.value / sum));
    bar.append(seg);
  });
  const legend = el('ul', { class: 'dr-legend' }, parts.map((p, i) => el('li', {}, el('i', { class: 'dr-dot c' + (i % 6) }), el('span', { text: p.label }), el('b', { text: format(p.value) }))));
  return el('div', { class: 'dr-stackbox' }, bar, legend);
}

// column histogram: values bucketed by edges ([0,5000,...]) with labels
export function histogram(values, edges, labels, { unit = 'wells' } = {}) {
  const counts = labels.map(() => 0);
  values.forEach((v) => { let k = edges.findIndex((e) => v < e); if (k < 0) k = labels.length; counts[Math.max(0, k - 1)]++; });
  const max = Math.max(1, ...counts);
  const wrap = el('div', { class: 'dr-hist', role: 'img', 'aria-label': labels.map((l, i) => l + ': ' + counts[i]).join(', ') });
  counts.forEach((c, i) => {
    const col = el('div', { class: 'dr-hcol' }, el('b', { text: c ? String(c) : '' }), el('span', { class: 'dr-hbar' }), el('small', { text: labels[i] }));
    col.querySelector('.dr-hbar').style.setProperty('--h', String(c / max));
    col.addEventListener('pointermove', (e) => showTip([tipRow(labels[i], ''), tipRow(fmt.format(c), unit)], e.clientX, e.clientY));
    col.addEventListener('pointerleave', hideTip);
    wrap.append(col);
  });
  return wrap;
}

// ranked list with a bar behind each value; rows are links when they carry an href
export function rankList(items, { color = 'var(--s2)', max, empty = 'Nothing to show.' } = {}) {
  const ul = el('ul', { class: 'bars dr-rank' });
  ul.style.setProperty('--bar', color);
  if (!items.length) return el('p', { class: 'fine', text: empty });
  const top = max || Math.max(1, ...items.map((i) => i.value));
  items.forEach((it) => {
    const bar = el('span', { class: 'bar' + (it.value > 0 ? '' : ' zero') });
    bar.style.setProperty('--p', String(it.value / top));
    const label = it.href ? el('a', { class: 'bar-label', href: it.href, text: it.label, title: it.label }) : el('span', { class: 'bar-label', text: it.label, title: it.label });
    ul.append(el('li', {}, el('div', { class: 'bar-row dr-rr' }, label, el('span', { class: 'bar-track' }, bar, el('span', { class: 'bar-value', text: it.valueText || fmt.format(it.value) })))));
  });
  return ul;
}
