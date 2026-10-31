// Daily report visuals: inline-SVG charts built from the design tokens. Text nodes only; styles go through the CSSOM
// (the page's Content-Security-Policy has no 'unsafe-inline'), so every dynamic value is a custom property.
import { el, svg, fmt, reduced } from './util.js';
import { showTip, hideTip, tipRow } from './tip.js';

/* ---------- dates (all UTC noon so a day never slips) ---------- */
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const WDL = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MOL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const at = (iso) => new Date(iso + 'T12:00:00Z');
export const weekday = (iso) => at(iso).getUTCDay();
export const isWeekend = (iso) => { const d = weekday(iso); return d === 0 || d === 6; };
export const fmtMd = (iso) => MO[+iso.slice(5, 7) - 1] + ' ' + +iso.slice(8);
export const fmtDow = (iso) => WD[weekday(iso)] + ', ' + fmtMd(iso);
export const fmtLong = (iso) => WDL[weekday(iso)] + ', ' + MOL[+iso.slice(5, 7) - 1] + ' ' + +iso.slice(8) + ', ' + iso.slice(0, 4);
export const monthName = (iso) => MOL[+iso.slice(5, 7) - 1];
export const addDays = (iso, n) => new Date(at(iso).getTime() + n * 864e5).toISOString().slice(0, 10);
export const mb = (bytes) => (bytes >= 1 << 30 ? (bytes / (1 << 30)).toFixed(2) + ' GB' : bytes >= 1 << 20 ? (bytes / (1 << 20)).toFixed(1) + ' MB' : Math.round(bytes / 1024) + ' KB');

const nice = (v) => (v <= 10 ? 10 : v <= 60 ? Math.ceil(v / 10) * 10 : Math.ceil(v / 20) * 20);
const rise = (node, i) => { node.style.setProperty('--i', String(i)); return node; };

/* ---------- permits per business day: stacked bars (horizontal / other), average line, the selected day lit ---------- */
export function trendBars({ days, total, horiz, avg, label, unit = 'new-drill permits' }) {
  const W = 640; const H = 236; const L = 34; const R = 8; const T = 24; const B = 30;
  const n = days.length; const max = nice(Math.max(1, ...total, avg || 0));
  const cw = (W - L - R) / n; const bw = Math.max(3, cw * 0.68);
  const x = (i) => L + cw * i + (cw - bw) / 2; const y = (v) => T + (H - T - B) * (1 - v / max);
  const root = svg('svg', { class: 'dr-chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': label });
  for (let k = 0; k <= 4; k++) {
    const v = (max / 4) * k;
    root.append(svg('line', { class: 'dr-grid', x1: L, x2: W - R, y1: y(v), y2: y(v) }), svg('text', { class: 'dr-ax', x: L - 6, y: y(v) + 3.5, 'text-anchor': 'end', text: String(Math.round(v)) }));
  }
  const last = n - 1;
  days.forEach((d, i) => {
    const t = total[i]; const h = horiz[i] || 0;
    const g = svg('g', { class: 'dr-barg' + (i === last ? ' on' : '') });
    g.append(rise(svg('rect', { class: 'dr-bar rest', x: x(i), y: y(t), width: bw, height: Math.max(0, y(0) - y(t)), rx: Math.min(3, bw / 3) }), i));
    if (h) g.append(rise(svg('rect', { class: 'dr-bar horiz', x: x(i), y: y(h), width: bw, height: Math.max(0, y(0) - y(h)), rx: Math.min(3, bw / 3) }), i));
    const hit = svg('rect', { class: 'dr-hit', x: L + cw * i, y: T, width: cw, height: H - T - B });
    hit.addEventListener('pointermove', (e) => showTip([tipRow(fmtDow(d), ''), tipRow(fmt.format(t), unit), h ? tipRow(fmt.format(h), 'horizontal') : null], e.clientX, e.clientY));
    hit.addEventListener('pointerleave', hideTip);
    g.append(hit);
    root.append(g);
  });
  if (avg) {
    root.append(svg('line', { class: 'dr-avg', x1: L, x2: W - R, y1: y(avg), y2: y(avg) }),
      svg('text', { class: 'dr-ax avg', x: L + 5, y: y(avg) - 6, 'text-anchor': 'start', text: '20-day average ' + Math.round(avg) }));
  }
  root.append(svg('text', { class: 'dr-val', x: x(last) + bw / 2, y: y(total[last]) - 6, 'text-anchor': 'middle', text: fmt.format(total[last]) }));
  const marks = [0, Math.floor(last / 2), last];
  marks.forEach((i, k) => root.append(svg('text', { class: 'dr-ax', x: x(i) + bw / 2, y: H - 9, 'text-anchor': k === 0 ? 'start' : k === 2 ? 'end' : 'middle', text: fmtMd(days[i]) })));
  return root;
}

/* ---------- Texas by county: shaded counties, glowing bubbles, the leader pulsing ---------- */
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
export function countyMap(G, layers, first) {
  const root = svg('svg', { class: 'dr-map', viewBox: '0 0 ' + G.W + ' ' + Math.ceil(G.H), role: 'img', 'aria-label': '' });
  const base = svg('g', { class: 'dr-counties' });
  const paths = new Map();
  for (const c of G.counties) {
    const p = svg('path', { class: 'dr-county', d: countyPath(c), 'data-f': c.f });
    base.append(p); paths.set(c.f, p);
  }
  const bub = svg('g', { class: 'dr-bubbles' });
  root.append(base, bub);
  let cur = null;
  const unit = { permits: 'new-drill permits issued', pending: 'applications waiting', completions: 'completions approved' };
  function set(id) {
    cur = id;
    const L = layers[id] || { map: new Map(), label: '' };
    root.dataset.layer = id;
    const max = Math.max(1, ...L.map.values());
    paths.forEach((p, f) => p.style.setProperty('--k', String(L.map.has(f) ? 0.18 + 0.82 * Math.sqrt(L.map.get(f) / max) : 0)));
    bub.replaceChildren();
    const ranked = [...L.map.entries()].sort((a, b) => b[1] - a[1]);
    ranked.forEach(([f, v], i) => {
      const c = G.byFips.get(f);
      if (!c) return;
      const r = 6 + 17 * Math.sqrt(v / max);
      if (i === 0 && !reduced()) bub.append(svg('circle', { class: 'dr-pulse', cx: c.lx, cy: c.ly, r }));
      bub.append(rise(svg('circle', { class: 'dr-bubble', cx: c.lx, cy: c.ly, r }), i));
      if (i < 3) bub.append(svg('text', { class: 'dr-maplabel', x: c.lx, y: c.ly - r - 5, 'text-anchor': 'middle', text: c.n + ' · ' + v }));
    });
    root.setAttribute('aria-label', ranked.length ? 'Map of Texas counties. ' + ranked.slice(0, 3).map(([f, v]) => G.byFips.get(f).n + ' ' + v).join(', ') + ' ' + unit[id] + '.' : 'Map of Texas counties. No data for this layer.');
  }
  root.addEventListener('pointermove', (e) => {
    const f = e.target.dataset && e.target.dataset.f;
    const L = layers[cur];
    if (!f || !L) { hideTip(); return; }
    const c = G.byFips.get(f); const v = L.map.get(f) || 0;
    showTip([tipRow(c.n + ' County', ''), tipRow(fmt.format(v), unit[cur])], e.clientX, e.clientY);
  });
  root.addEventListener('pointerleave', hideTip);
  set(first);
  return { el: root, set };
}

/* ---------- the 92-day ribbon: one bar per report day, the selected day lit; arrow keys move a day ---------- */
export function ribbon({ days, selected, onPick }) {
  const n = days.length; const bw = 9; const gap = 3; const W = n * (bw + gap) + 6; const H = 84; const T = 8; const B = 18;
  const vals = days.map((r) => (r.pFresh ? r.pn || 0 : 0));
  const max = Math.max(10, ...vals);
  const root = svg('svg', { class: 'dr-ribbon', viewBox: '0 0 ' + W + ' ' + H, 'aria-hidden': 'true' });
  const bars = [];
  days.forEach((r, i) => {
    const h = r.pFresh ? 5 + (H - T - B - 5) * ((r.pn || 0) / max) : 4;
    const b = svg('rect', { class: 'dr-rb' + (r.pFresh ? '' : ' off') + (r.k === 'live' ? ' live' : ''), x: 3 + i * (bw + gap), y: H - B - h, width: bw, height: h, rx: 2.5, 'data-i': i });
    bars.push(b); root.append(b);
    const firstOfMonth = r.d.slice(8) === '01'; // the left edge only gets a label when a month does not start within a few bars
    if (firstOfMonth || (i === 0 && !days.slice(1, 6).some((x) => x.d.slice(8) === '01'))) root.append(svg('text', { class: 'dr-ax', x: 3 + i * (bw + gap), y: H - 4, text: fmtMd(r.d).split(' ')[0] }));
  });
  const wrap = el('div', { class: 'dr-ribbon-wrap', 'data-act': 'ribbon', role: 'slider', tabindex: '0', 'aria-label': 'Report day, 3-month archive. Arrow keys move one day.', 'aria-valuemin': '0', 'aria-valuemax': String(n - 1) }, root);
  let cur = -1;
  function mark(d) {
    cur = Math.max(0, days.findIndex((r) => r.d === d));
    bars.forEach((b, i) => b.classList.toggle('sel', i === cur));
    wrap.setAttribute('aria-valuenow', String(cur));
    wrap.setAttribute('aria-valuetext', fmtLong(days[cur].d));
    const bb = bars[cur]; const x = +bb.getAttribute('x');
    wrap.scrollLeft = Math.max(0, (x / W) * wrap.scrollWidth - wrap.clientWidth / 2);
  }
  root.addEventListener('click', (e) => { const i = e.target.dataset && e.target.dataset.i; if (i != null) onPick(days[+i].d); });
  root.addEventListener('pointermove', (e) => {
    const i = e.target.dataset && e.target.dataset.i;
    if (i == null) { hideTip(); return; }
    const r = days[+i];
    showTip([tipRow(fmtDow(r.d), r.k === 'live' ? 'captured live' : 'reconstructed'), r.pFresh && r.pn != null ? tipRow(fmt.format(r.pn), 'new-drill permits issued ' + fmtMd(r.dd)) : null,
      r.q != null ? tipRow(fmt.format(r.q), 'waiting for approval') : null, r.c != null ? tipRow(fmt.format(r.c), 'completions approved') : null], e.clientX, e.clientY);
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
    const bar = el('span', { class: 'bar' });
    bar.style.setProperty('--p', String(it.value / top));
    const label = it.href ? el('a', { class: 'bar-label', href: it.href, text: it.label, title: it.label }) : el('span', { class: 'bar-label', text: it.label, title: it.label });
    ul.append(el('li', {}, el('div', { class: 'bar-row dr-rr' }, label, el('span', { class: 'bar-track' }, bar, el('span', { class: 'bar-value', text: it.valueText || fmt.format(it.value) })))));
  });
  return ul;
}
