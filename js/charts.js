// SVG charts: the change arrow and the sparkline.
// Marks follow the dataviz rules: 2px lines, 10-18% gradient wash, 2px surface ring on end dots.
import { el, svg, signed } from './util.js';

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
