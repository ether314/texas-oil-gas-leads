// Small helpers the Overview and the Sources page share: a link into the Companies page's operators, the Sources page's filled-in figures, and the freshness list.
import { el, fmt, fmtDate } from './util.js';
import { icon } from './icons.js';

export const opsLink = (name) => '#companies?' + new URLSearchParams({ q: name, band: 'all' });
const hide = (node) => { const c = node.closest('[data-card]'); (c || node).hidden = true; };

export function fillMeta(m, extra = {}) {
  const values = {
    built: fmtDate(m.built), p5: fmtDate(m.sources.p5), permits: fmtDate(m.sources.permits), latest_permit: fmtDate(m.sources.latest_permit),
    comptroller: fmtDate(m.sources.comptroller), registered: fmt.format(m.operators.registered), opsShown: fmt.format(m.operators.shown), ...extra,
  };
  document.querySelectorAll('[data-fill]').forEach((n) => { n.textContent = values[n.dataset.fill] || ''; });
}

/* data freshness: every source with its own latest date and, where documented, how often its source publishes */
export function renderFreshness(ul, items) {
  const list = items.filter((x) => x && x.value);
  if (!list.length) { hide(ul); return; }
  ul.replaceChildren(...list.map((x) => el('li', {}, icon(x.icon || 'calendar', 16), el('div', {},
    el('b', { text: x.label }), el('span', { text: x.value }),
    x.cadence ? el('small', { class: 'fresh-cad', text: 'Publishes ' + x.cadence, title: 'The source publishes new data ' + x.cadence + '. This site is rebuilt by hand, so it can lag.' }) : null))));
}
