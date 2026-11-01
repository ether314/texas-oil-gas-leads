// SVG charts: sparklines, the area chart and the histogram.
// Marks follow the dataviz rules: 2px lines, 10-18% gradient wash, hairline solid grid, 2px surface ring on end dots, direct end labels.
import { el, svg, fmt, monthLabel, signed, clamp } from './util.js';
import { showTip, hideTip, tipRow } from './tip.js';

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
