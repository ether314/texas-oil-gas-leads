// SVG and HTML charts: sparklines, area and histogram charts, bar lists, and the time-series group used by the market pulse.
// Marks follow the dataviz rules: 2px lines, 10-18% gradient wash, hairline solid grid, 2px surface ring on end dots, direct end labels.
import { el, svg, fmt, monthLabel, signed, clamp, nearest, lastIdx, yoy, fmtDate, reduced } from './util.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { icon } from './icons.js';

let gradN = 0;
const gid = () => 'cg' + (++gradN);
const grad = (id) => svg('linearGradient', { id, x1: 0, y1: 0, x2: 0, y2: 1 }, svg('stop', { offset: '0', class: 'g-top' }), svg('stop', { offset: '1', class: 'g-bot' }));
const pathOf = (pts) => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');

/* a change as arrow + percent; the arrow carries direction so color is never the only cue */
export function delta(f, { suffix = '' } = {}) {
  if (f == null || !isFinite(f)) return el('span', { class: 'delta flat', text: 'n/a' });
  const p = Math.round(Math.abs(f) * 100);
  const dir = p === 0 ? 'flat' : f > 0 ? 'up' : 'down';
  return el('span', { class: 'delta ' + dir },
    el('span', { class: 'arrow', 'aria-hidden': 'true', text: dir === 'up' ? '▲' : dir === 'down' ? '▼' : '▬' }),
    el('span', { text: signed(f) + suffix }));
}

/* fixed-size sparkline (tables, panels): line, wash, end dot with a halo */
export function spark(values, { w = 92, h = 26, label = '', color = 'var(--s2)', dot = true, base = 'zero' } = {}) {
  const n = values.length; const max = Math.max(1, ...values);
  let lo = 0; let hi = max;
  if (base === 'min') { lo = Math.min(...values); hi = max; const pad = (hi - lo) * 0.18 || 1; lo -= pad; hi += pad * 0.4; }
  const x = (i) => 3 + (w - 6) * (n < 2 ? 0.5 : i / (n - 1));
  const y = (v) => h - 3 - (h - 6) * ((v - lo) / (hi - lo || 1));
  const d = pathOf(values.map((v, i) => [x(i), y(v)]));
  const cx = x(n - 1).toFixed(1); const cy = y(values[n - 1]).toFixed(1);
  const node = svg('svg', { class: 'spark', viewBox: '0 0 ' + w + ' ' + h, width: w, height: h, role: label ? 'img' : null, 'aria-label': label || null, 'aria-hidden': label ? null : 'true' },
    svg('path', { class: 'spark-area', d: d + 'L' + cx + ' ' + (h - 1) + 'L' + x(0).toFixed(1) + ' ' + (h - 1) + 'Z' }),
    svg('path', { class: 'spark-line', d, pathLength: 1 }),
    dot ? svg('circle', { class: 'spark-halo', cx, cy, r: 5.5 }) : null,
    dot ? svg('circle', { class: 'spark-dot', cx, cy, r: 2.8 }) : null);
  node.style.setProperty('--c', color);
  return node;
}

/* responsive sparkline for the ticker: stretches to its box; the end dot is an element so it stays round */
export function fluidSpark(values, { color = 'var(--s1)', label = '', h = 30 } = {}) {
  const n = values.length; let lo = Math.min(...values); let hi = Math.max(...values);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.14; lo -= pad; hi += pad;
  const X = (i) => (n < 2 ? 50 : (i / (n - 1)) * 100); const Y = (v) => 3 + (h - 6) * (1 - (v - lo) / (hi - lo));
  const d = pathOf(values.map((v, i) => [X(i), Y(v)]));
  const id = gid();
  const dotEl = el('i', { class: 'fdot' });
  dotEl.style.top = ((Y(values[n - 1]) / h) * 100).toFixed(1) + '%';
  const box = el('span', { class: 'fspark', role: 'img', 'aria-label': label || null },
    svg('svg', { viewBox: '0 0 100 ' + h, preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
      svg('defs', {}, grad(id)),
      svg('path', { class: 'farea', d: d + 'L100 ' + h + 'L0 ' + h + 'Z', fill: 'url(#' + id + ')' }),
      svg('path', { class: 'fline', d })), dotEl);
  box.style.setProperty('--c', color);
  return box;
}

/* single-series area chart for the map panels: gradient wash, end dot with halo, hover readout (values also live in the table view) */
export function areaChart(values, months, { w = 300, h = 92, color = 'var(--s2)', unit = 'permits', fmtVal = (v) => fmt.format(v), what = 'Monthly values' } = {}) {
  const n = values.length; const max = Math.max(1, ...values);
  const ml = 4; const mr = 6; const mt = 14; const mb = 4;
  const x = (i) => ml + (w - ml - mr) * (i / (n - 1));
  const y = (v) => mt + (h - mt - mb) * (1 - v / max);
  const d = pathOf(values.map((v, i) => [x(i), y(v)]));
  const pk = values.indexOf(Math.max(...values)); const id = gid();
  const hair = svg('line', { class: 'xhair', x1: 0, x2: 0, y1: mt - 4, y2: h - mb, visibility: 'hidden' });
  const hdot = svg('circle', { class: 'pl-dot', r: 4, visibility: 'hidden' });
  const node = svg('svg', { class: 'area', viewBox: '0 0 ' + w + ' ' + h, width: '100%', height: h, role: 'img', 'aria-label': what + ', ' + monthLabel(months[0]) + ' to ' + monthLabel(months[n - 1]) + ', peak ' + fmtVal(max) },
    svg('defs', {}, grad(id)),
    svg('line', { class: 'grid', x1: ml, x2: w - mr, y1: h - mb, y2: h - mb }),
    svg('line', { class: 'grid', x1: ml, x2: w - mr, y1: y(max / 2), y2: y(max / 2) }),
    svg('path', { class: 'a-area', d: d + 'L' + x(n - 1) + ' ' + (h - mb) + 'L' + x(0) + ' ' + (h - mb) + 'Z', fill: 'url(#' + id + ')' }),
    svg('path', { class: 'pl-line', d, pathLength: 1 }),
    svg('circle', { class: 'pl-halo', cx: x(n - 1), cy: y(values[n - 1]), r: 8 }),
    svg('circle', { class: 'pl-end', cx: x(n - 1), cy: y(values[n - 1]), r: 4 }),
    max > 1 ? svg('text', { class: 'ax', x: clamp(x(pk), 16, w - 16), y: mt - 4, 'text-anchor': 'middle', text: fmtVal(max) }) : null, hair, hdot);
  node.style.setProperty('--c', color);
  const at = (e) => { const r = node.getBoundingClientRect(); return clamp(Math.round(((e.clientX - r.left) / r.width * w - ml) / (w - ml - mr) * (n - 1)), 0, n - 1); };
  node.addEventListener('pointermove', (e) => {
    const i = at(e);
    hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
    hdot.setAttribute('cx', x(i)); hdot.setAttribute('cy', y(values[i])); hdot.setAttribute('visibility', 'visible');
    showTip([el('div', { class: 'tip-head', text: monthLabel(months[i]) }), tipRow(fmtVal(values[i]), unit)], e.clientX, e.clientY);
  });
  node.addEventListener('pointerleave', () => { hair.setAttribute('visibility', 'hidden'); hdot.setAttribute('visibility', 'hidden'); hideTip(); });
  return node;
}

/* small column chart: establishments by employment size class (lower bound of each class on the axis) */
export function histChart(values, classes, { w = 300, h = 86, color = 'var(--s1)', unit = 'establishments', what = '' } = {}) {
  const n = values.length; const max = Math.max(1, ...values);
  const ml = 2; const mr = 2; const mt = 14; const mb = 16;
  const slot = (w - ml - mr) / n; const bw = Math.min(26, slot - 6); const base = h - mb;
  const lower = classes.map((c) => { const v = parseInt(c, 10); return v >= 1000 ? '1K' : String(v); });
  const summary = classes.map((c, i) => c + ' employees: ' + fmt.format(values[i])).join('; ');
  const node = svg('svg', { class: 'area hist', viewBox: '0 0 ' + w + ' ' + h, width: '100%', height: h, role: 'img', 'aria-label': (what ? what + ': ' : '') + summary });
  node.append(svg('line', { class: 'base', x1: ml, x2: w - mr, y1: base, y2: base }));
  values.forEach((v, i) => {
    const x0 = ml + slot * i + (slot - bw) / 2; const bh = v > 0 ? Math.max(3, (base - mt) * (v / max)) : 0; const y0 = base - bh; const r = Math.min(4, bh);
    if (bh) {
      const bar = svg('path', { class: 'hbar', d: 'M' + x0 + ' ' + base + 'V' + (y0 + r) + 'Q' + x0 + ' ' + y0 + ' ' + (x0 + r) + ' ' + y0 + 'H' + (x0 + bw - r) + 'Q' + (x0 + bw) + ' ' + y0 + ' ' + (x0 + bw) + ' ' + (y0 + r) + 'V' + base + 'Z' });
      node.append(bar);
      bar.addEventListener('pointermove', (e) => { bar.classList.add('on'); showTip([tipRow(fmt.format(v), unit), el('div', { class: 'tip-head', text: classes[i] + ' employees' })], e.clientX, e.clientY); });
      bar.addEventListener('pointerleave', () => { bar.classList.remove('on'); hideTip(); });
      if (v === max) node.append(svg('text', { class: 'ax', x: x0 + bw / 2, y: y0 - 4, 'text-anchor': 'middle', text: fmt.format(v) }));
    }
    node.append(svg('text', { class: 'ax', x: x0 + bw / 2, y: h - 3, 'text-anchor': 'middle', text: lower[i] }));
  });
  node.style.setProperty('--c', color);
  return node;
}

/* bar list: label, bar capped at 24px with a rounded data end, value at the tip; each row is a link */
export function barList(ul, items, { max, tipFor } = {}) {
  const top = max || Math.max(1, ...items.filter((i) => !i.heading).map((i) => i.value));
  ul.replaceChildren(...items.map((it) => {
    if (it.heading) return el('li', { class: 'bars-h' + (it.st && it.st !== 'TX' ? ' st-' + it.st.toLowerCase() : ''), text: it.heading });
    const bar = el('span', { class: 'bar' });
    bar.style.setProperty('--p', String(it.value / top));
    const row = el('a', { class: 'bar-row', href: it.href, 'aria-label': it.aria || null },
      el('span', { class: 'bar-label', text: it.label, title: it.label }),
      el('span', { class: 'bar-track' }, bar, el('span', { class: 'bar-value', text: it.valueText || fmt.format(it.value) })));
    const open = (e) => {
      const r = row.getBoundingClientRect();
      showTip(tipFor(it), e.clientX || r.left + 80, e.clientY || r.top);
    };
    row.addEventListener('pointermove', open);
    row.addEventListener('pointerleave', hideTip);
    row.addEventListener('focus', open);
    row.addEventListener('blur', hideTip);
    return el('li', { class: it.st && it.st !== 'TX' ? 'st-' + it.st.toLowerCase() : null }, row); // each other state's rows take its color wherever a list shows them (Texas's is the list's own)
  }));
}

/* ---------- time-series group: stacked small multiples on one time axis, one shared crosshair, never a dual axis ---------- */
const M0 = { l: 46, r: 58, t: 8, b: 6 };
function niceScale(lo, hi, n = 3) {
  const span = hi - lo || 1; const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = ([1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= raw)) || 10 * mag;
  const a = Math.floor(lo / step + 1e-9) * step; const b = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let v = a; v <= b + step / 2; v += step) ticks.push(+v.toFixed(8));
  return { lo: a, hi: b, ticks };
}

/* spec: { label, domain:[t0,t1], zone:{t,label}|null, headFmt(t), panels:[{ id, title, icon, color, zero, fmtTick, events, foot,
     series:[{ id, name, unit, color, t[], v[], fmtVal, fmtEnd, fc, ref, prelim:Set(t), dateFmt(t), tol }] }] } */
export function seriesGroup(root, spec) {
  const { panels, zone } = spec; const [t0, t1] = spec.domain;
  const live = el('span', { class: 'sr-only', 'aria-live': 'polite' });
  const axis = el('div', { class: 'pulse-axis' });
  const P = panels.map((p) => {
    const main = p.series.find((s) => !s.fc && !s.ref) || p.series[0];
    const last = lastIdx(main.v); const prevY = yoy(main.t, main.v, last);
    const legend = p.series.filter((s) => !s.fc).length > 1
      ? el('span', { class: 'pulse-legend' }, p.series.filter((s) => !s.fc).map((s) => { const k = el('span', { class: s.ref ? 'dots' : null }, el('i'), s.name); k.style.setProperty('--c', s.ref ? 'var(--ink-2)' : s.color || p.color); return k; })) : null;
    const box = el('div', { class: 'pulse-panel' },
      el('div', { class: 'pulse-head' },
        el('h3', { class: 'pulse-title' }, p.icon ? icon(p.icon, 17) : null, p.title, legend),
        last >= 0 ? el('div', { class: 'pulse-latest' }, legend ? el('span', { class: 'pulse-who', text: main.name.replace(/ \(.*\)$/, '') }) : null, el('strong', { class: 'pulse-value', text: main.fmtVal(main.v[last]) }), delta(prevY, { suffix: ' YoY' }),
          el('span', { class: 'pulse-asof', text: (main.dateFmt || monthLabelT)(main.t[last]) })) : null),
      el('div', { class: 'pulse-plot' }), p.foot ? el('p', { class: 'pulse-foot' }, p.foot) : null);
    box.style.setProperty('--c', p.color);
    return { p, main, last, box, plot: box.querySelector('.pulse-plot'), cross: null, dots: [], y: null };
  });
  const wrap = el('div', { class: 'pgroup', tabindex: '0', role: 'group', 'aria-label': spec.label + '. Use the left and right arrow keys to move through time; Home and End jump to the ends. A table view is available.' },
    P.map((q) => q.box), axis, live);
  root.replaceChildren(wrap);

  let width = 0; let curT = null;
  const xAt = (t) => M0.l + (width - M0.l - M0.r) * ((t - t0) / (t1 - t0));
  const H = () => (width < 520 ? 92 : 112);
  const snap = [...new Set(P[0].p.series.filter((s) => !s.ref).flatMap((s) => s.t))].sort((a, b) => a - b);

  function drawPanel(q) {
    const { p } = q; const h = H(); const top = M0.t + (p.events && p.events.length ? 15 : 0);
    const all = p.series.flatMap((s) => s.v.filter((v) => v != null));
    let lo = Math.min(...all); let hi = Math.max(...all);
    if (p.zero) lo = Math.min(0, lo);
    const pad = (hi - lo) * (p.zero && lo === 0 ? 0 : 0.06);
    const sc = niceScale(lo - pad, hi + (hi - lo) * 0.05, 3);
    const y = (v) => top + (h - top - M0.b) * (1 - (v - sc.lo) / (sc.hi - sc.lo));
    q.y = y;
    const id = gid();
    const g = svg('svg', { width, height: h, viewBox: '0 0 ' + width + ' ' + h, 'aria-hidden': 'true', focusable: 'false' }, svg('defs', {}, grad(id)));
    if (zone) {
      const zx = xAt(zone.t); const zw = Math.max(0, xAt(t1) - zx + 6);
      g.append(svg('rect', { class: 'zone', x: zx, y: top - 3, width: zw, height: h - top - M0.b + 3 }),
        svg('line', { class: 'zone-edge', x1: zx, x2: zx, y1: top - 3, y2: h - M0.b }),
        svg('text', { class: 'zone-label', x: zx + 7, y: top + 9, text: (zw < 104 ? zone.label.replace(/^EIA /i, '') : zone.label).toUpperCase() }));
    }
    for (let yr = new Date(t0).getUTCFullYear() + 1; yr <= new Date(t1).getUTCFullYear(); yr++) {
      const t = Date.UTC(yr, 0, 1);
      if (t > t0 && t < t1) g.append(svg('line', { class: 'vgrid', x1: xAt(t), x2: xAt(t), y1: top, y2: h - M0.b }));
    }
    for (const t of sc.ticks) {
      g.append(svg('line', { class: 'grid', x1: M0.l, x2: width - M0.r + 6, y1: y(t), y2: y(t) }),
        svg('text', { class: 'ax', x: M0.l - 8, y: y(t) + 4, 'text-anchor': 'end', text: p.fmtTick(t) }));
    }
    if (sc.lo < 0 && sc.hi > 0) g.append(svg('line', { class: 'base', x1: M0.l, x2: width - M0.r + 6, y1: y(0), y2: y(0) }));
    const refEnd = Math.max(0, ...p.series.filter((s) => s.ref).map((s) => { const i = lastIdx(s.v); return i < 0 ? 0 : s.t[i]; }));
    const hasFc = p.series.some((s) => s.fc) || (refEnd > 0 && q.last >= 0 && refEnd > q.main.t[q.last] + 40 * 864e5);
    const ends = [];
    // actual series first (main gets the wash), then reference lines, then forecasts joined to the main series' last actual point
    const ordered = [...p.series.filter((s) => !s.fc && !s.ref), ...p.series.filter((s) => s.ref), ...p.series.filter((s) => s.fc)];
    for (const s of ordered) {
      let d = ''; let pts = []; const segs = [];
      const push = () => { if (pts.length) segs.push(pts); pts = []; };
      if (s.fc && q.last >= 0 && s.join !== false) pts.push([xAt(q.main.t[q.last]), y(q.main.v[q.last])]);
      for (let i = 0; i < s.t.length; i++) {
        if (s.v[i] == null) { push(); continue; }
        pts.push([xAt(s.t[i]), y(s.v[i])]);
      }
      push();
      d = segs.map(pathOf).join('');
      if (!d) continue;
      if (s === q.main) {
        const last = segs[segs.length - 1]; const first = segs[0];
        g.append(svg('path', { class: 'a-area', d: pathOf(first) + segs.slice(1).map((sg) => pathOf(sg)).join('') + 'L' + last[last.length - 1][0].toFixed(1) + ' ' + y(sc.lo).toFixed(1) + 'L' + first[0][0].toFixed(1) + ' ' + y(sc.lo).toFixed(1) + 'Z', fill: 'url(#' + id + ')' }));
      }
      if (s.ref) {
        // a reference source (for example the EIA estimate) is drawn as small dots so it never muddies the main line
        const after = s.after && q.last >= 0 ? xAt(q.main.t[q.last]) + 1 : -1;
        segs.forEach((sg) => sg.forEach((pt) => { if (pt[0] > after) g.append(svg('circle', { class: 'pl-pt', cx: pt[0].toFixed(1), cy: pt[1].toFixed(1), r: 2 })); }));
      } else {
        const line = svg('path', { class: 'pl-line' + (s.fc ? ' fc' : ''), d, pathLength: 1 });
        if (s.color) line.style.setProperty('--c', s.color);
        g.append(line);
      }
      const lp = segs[segs.length - 1]; const end = lp[lp.length - 1];
      ends.push({ s, x: end[0], y: end[1], i: lastIdx(s.v) });
    }
    for (const e of ends) {
      if (e.s.ref) continue;
      const col = e.s.color || p.color; const prelim = e.s.prelim && e.s.prelim.has(e.s.t[e.i]);
      const halo = svg('circle', { class: 'pl-halo', cx: e.x, cy: e.y, r: 9 });
      const dot = svg('circle', { class: (prelim ? 'prelim' : 'pl-end') + (e.s.fc ? ' fc' : ''), cx: e.x, cy: e.y, r: 4.5 });
      const label = svg('text', {
        class: 'pl-label' + (e.s.fc ? ' sec' : ''), x: hasFc && !e.s.fc ? e.x - 9 : e.x + 11, y: hasFc && !e.s.fc ? e.y - 8 : e.y + 4,
        'text-anchor': hasFc && !e.s.fc ? 'end' : 'start', text: (e.s.fmtEnd || e.s.fmtVal)(e.s.v[e.i]),
      });
      [halo, dot, label].forEach((n) => { n.style.setProperty('--c', col); g.append(n); });
    }
    if (p.events) {
      let lastEnd = -1e9; // labels never overlap: a later one slides right of the earlier one, or is left out when there is no room
      for (const ev of [...p.events].sort((a, b) => a.t - b.t)) {
        const i = nearest(q.main.t, ev.t); if (i < 0 || q.main.v[i] == null) continue;
        const ex = xAt(q.main.t[i]); const ey = y(q.main.v[i]); const tw = ev.label.length * 6.3;
        let lx = clamp(ex, M0.l + tw / 2, width - M0.r - tw / 2);
        if (lx - tw / 2 < lastEnd + 8) lx = lastEnd + 8 + tw / 2;
        if (lx + tw / 2 > width - M0.r + 24) continue;
        lastEnd = lx + tw / 2;
        g.append(svg('line', { class: 'ev-line', x1: ex, x2: ex, y1: 13, y2: ey - 4 }), svg('circle', { class: 'ev-ring', cx: ex, cy: ey, r: 3.5 }),
          svg('text', { class: 'ev-label', x: lx, y: 9, 'text-anchor': 'middle', text: ev.label }));
      }
    }
    q.cross = svg('line', { class: 'xhair', x1: 0, x2: 0, y1: top - 3, y2: h - M0.b, visibility: 'hidden' });
    q.dots = p.series.map((s) => { const c = svg('circle', { class: 'pl-dot', r: 4.5, visibility: 'hidden' }); c.style.setProperty('--c', s.ref ? 'var(--ink-2)' : s.color || p.color); return c; });
    g.append(q.cross, ...q.dots);
    q.plot.replaceChildren(g);
  }
  function drawAxis() {
    const g = svg('svg', { width, height: 22, viewBox: '0 0 ' + width + ' 22', 'aria-hidden': 'true', focusable: 'false' });
    const y0 = new Date(t0).getUTCFullYear(); const span = new Date(t1).getUTCFullYear() - y0;
    const every = width < 520 && span > 5 ? 2 : 1;
    for (let yr = y0; yr <= y0 + span; yr++) {
      const x = xAt(Math.max(Date.UTC(yr, 0, 1), t0));
      if ((yr - y0) % every || x + 34 > width - M0.r + 12) continue;
      g.append(svg('text', { class: 'ax', x: x + 4, y: 15, text: String(yr) }));
    }
    axis.replaceChildren(g);
  }
  function render() {
    const w = wrap.clientWidth;
    if (!w || w === width) return;
    width = w;
    P.forEach(drawPanel); drawAxis();
    if (curT != null) mark(curT);
  }

  const pick = (s, t) => {
    const i = nearest(s.t, t); if (i < 0) return -1;
    const tol = s.tol || 17 * 864e5;
    return Math.abs(s.t[i] - t) <= tol ? i : -1;
  };
  function mark(t) {
    curT = t;
    P.forEach((q) => {
      q.cross.setAttribute('x1', xAt(t)); q.cross.setAttribute('x2', xAt(t)); q.cross.setAttribute('visibility', 'visible');
      q.p.series.forEach((s, k) => {
        const i = pick(s, t); const d = q.dots[k];
        if (i < 0 || s.v[i] == null) d.setAttribute('visibility', 'hidden');
        else { d.setAttribute('cx', xAt(s.t[i])); d.setAttribute('cy', q.y(s.v[i])); d.setAttribute('visibility', 'visible'); }
      });
    });
  }
  function rows(t) {
    const out = [el('div', { class: 'tip-head', text: (spec.headFmt || monthLabelT)(t) })];
    P.forEach((q) => q.p.series.forEach((s) => {
      const i = pick(s, t);
      if (i < 0) return;
      const key = el('i', { class: 'tip-key' }); key.style.setProperty('--c', s.ref ? 'var(--ink-2)' : s.color || q.p.color);
      const own = s.dateFmt && s.dateFmt(s.t[i]) !== (spec.headFmt || monthLabelT)(t) ? ' · ' + s.dateFmt(s.t[i]) : '';
      out.push(el('div', { class: 'tip-line' }, key, el('strong', { text: s.v[i] == null ? 'Not yet published' : s.fmtVal(s.v[i]) }),
        el('span', { text: ' ' + s.name + (s.unit ? ' · ' + s.unit : '') + own })));
    }));
    return out;
  }
  function spoken(t) {
    return (spec.headFmt || monthLabelT)(t) + ': ' + rows(t).slice(1).map((r) => r.textContent).join('; ');
  }
  function clear() {
    curT = null; hideTip();
    P.forEach((q) => { q.cross.setAttribute('visibility', 'hidden'); q.dots.forEach((d) => d.setAttribute('visibility', 'hidden')); });
  }
  const snapAt = (t) => snap[nearest(snap, t)];
  wrap.addEventListener('pointermove', (e) => {
    const r = P[0].plot.getBoundingClientRect();
    const t = t0 + ((e.clientX - r.left - M0.l) / (width - M0.l - M0.r)) * (t1 - t0);
    mark(snapAt(clamp(t, t0, t1)));
    showTip(rows(curT), e.clientX, e.clientY);
  });
  wrap.addEventListener('pointerleave', clear);
  wrap.addEventListener('blur', clear);
  wrap.addEventListener('keydown', (e) => {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown', 'Escape'];
    if (!keys.includes(e.key)) return;
    e.preventDefault();
    if (e.key === 'Escape') { clear(); return; }
    const mainLast = snap.findIndex((t) => t >= P[0].main.t[P[0].last]);
    const cur = curT == null ? (mainLast < 0 ? snap.length - 1 : mainLast) : nearest(snap, curT);
    const step = { ArrowLeft: -1, ArrowRight: 1, PageUp: -12, PageDown: 12 }[e.key];
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? snap.length - 1 : clamp(cur + step, 0, snap.length - 1);
    mark(snap[next]);
    const r = P[0].plot.getBoundingClientRect();
    showTip(rows(snap[next]), r.left + xAt(snap[next]), r.top + 28);
    live.textContent = spoken(snap[next]);
  });
  if ('ResizeObserver' in window) new ResizeObserver(render).observe(wrap);
  if (!reduced()) { wrap.classList.add('draw'); setTimeout(() => wrap.classList.remove('draw'), 2200); }
  render();
  return { render, wrap };
}
const monthLabelT = (t) => { const d = new Date(t); return monthLabel(d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0')); };
export const isoOf = (t) => new Date(t).toISOString().slice(0, 10);
export const dayLabelT = (t) => fmtDate(isoOf(t));

/* the accessible twin of a group: one table per panel, newest first; missing values read "not yet published", never zero */
export function seriesTables(spec) {
  const kids = [];
  for (const p of spec.panels) {
    const ts = [...new Set(p.series.flatMap((s) => s.t))].sort((a, b) => b - a);
    const dateOf = p.series[0].dateFmt || monthLabelT;
    const maps = p.series.map((s) => new Map(s.t.map((t, i) => [t, s.v[i]])));
    kids.push(el('h3', { class: 'psec-h3', text: p.title }),
      el('table', { class: 'grid' }, el('caption', { class: 'sr-only', text: p.title + ', newest first' }),
        el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: p.series[0].dateFmt ? 'Week of' : 'Month' }),
          p.series.map((s) => el('th', { scope: 'col', class: 'num', text: s.name + (s.unit ? ' (' + s.unit + ')' : '') })))),
        el('tbody', {}, ts.map((t) => el('tr', {}, el('th', { scope: 'row', text: dateOf(t) }),
          p.series.map((s, k) => el('td', { class: 'num', text: !maps[k].has(t) ? '' : maps[k].get(t) == null ? 'not yet published' : s.fmtVal(maps[k].get(t)) })))))));
  }
  return kids;
}
