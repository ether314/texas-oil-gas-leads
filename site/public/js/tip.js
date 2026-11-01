// One shared tooltip for charts, bars and the map. Content is text nodes only.
import { $, el } from './util.js';

let node = null;
const get = () => (node ||= $('#tip'));

export const tipRow = (strong, rest, cls) => el('div', { class: 'tip-row' + (cls ? ' ' + cls : '') },
  el('strong', { text: strong }), rest ? el('span', { text: ' ' + rest }) : null);

export function showTip(kids, x, y) {
  const t = get();
  t.replaceChildren(...[].concat(kids).filter(Boolean));
  t.hidden = false;
  const r = t.getBoundingClientRect();
  const left = Math.min(Math.max(8, x + 14), window.innerWidth - r.width - 8);
  const below = y + 20 + r.height <= window.innerHeight - 8;
  t.style.left = left + 'px';
  t.style.top = (below ? y + 20 : Math.max(8, y - r.height - 14)) + 'px';
}
export const hideTip = () => { get().hidden = true; };
// what appears on hover or focus can be dismissed without moving the pointer or the focus (WCAG 1.4.13): Escape hides the tooltip
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && node && !node.hidden) hideTip(); });
