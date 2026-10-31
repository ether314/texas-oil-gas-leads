// Building blocks shared by the Daily reports (Texas in daily.js, Oklahoma in ok-daily.js): cards, tiles, tables, status chips,
// KPI cards and a few small formatters. Text nodes only; every style is a class or a custom property set through the CSSOM
// (the page's Content-Security-Policy has no 'unsafe-inline').
import { el, fmt, countUp } from './util.js';
import { icon } from './icons.js';
import { spark } from './charts.js';

export const num = (v) => fmt.format(v);
export const strong = (t) => el('strong', { text: t });
// a file time as the share lists it (already Central, stored without a zone) and a UTC capture time shown in Central
export const listed = (iso) => (iso ? new Date(iso + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }) : '—');
export const central = (utc) => new Date(utc).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' }) + ' Central';
// 'first' means the previous report was not captured live, so there is nothing to compare a file with
export const compare = (rep) => { const ds = rep.datasets; return { ok: ds.some((d) => d.state === 'new' || d.state === 'same'), fresh: ds.filter((d) => d.state === 'new').length, same: ds.filter((d) => d.state === 'same') }; };
export const rel = (v, avg) => { const p = Math.round(Math.abs(v / avg - 1) * 100); return p < 3 ? 'in line with' : p + '% ' + (v > avg ? 'above' : 'below'); };

export const card = (cls, ...kids) => el('section', { class: 'card dr-card ' + cls }, ...kids);
export const head = (ic, eyebrow, title, sub) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null));
export const tiles = (items) => el('dl', { class: 'dr-tiles' }, items.filter(Boolean).map((t) => el('div', { class: 'dr-tile' }, el('dt', { text: t.label }), el('dd', { text: t.value }), t.note ? el('small', { text: t.note }) : null)));
export const table = (cols, rows, { cap = 'dr-table' } = {}) => el('div', { class: 'table-wrap ' + cap },
  el('table', { class: 'grid' }, el('thead', {}, el('tr', {}, cols.map((c) => el('th', { scope: 'col', class: c.num ? 'num' : null, text: c.t })))),
    el('tbody', {}, rows.map((r) => el('tr', {}, r.map((v, i) => el('td', { class: cols[i].num ? 'num' : null }, v == null ? '—' : v)))))));
export const chip = (cls, text) => el('span', { class: 'dr-pill ' + cls }, el('i', { class: 'dr-led' }), text);

export function kpi({ ic, label, value, note, extra, vals, color, hero: big, gauge }) {
  const n = el('strong', { class: 'dr-kpi-num' });
  const c = el('div', { class: 'dr-kpi' + (big ? ' lead' : '') },
    el('div', { class: 'dr-kpi-top' }, icon(ic, 16), el('span', { text: label })),
    gauge ? el('div', { class: 'dr-kpi-gauge' }, gauge) : n,
    note ? el('div', { class: 'dr-kpi-note' }, note) : null,
    extra ? el('div', { class: 'dr-kpi-extra' }, extra) : null,
    vals && vals.length > 3 ? el('div', { class: 'dr-kpi-spark' }, spark(vals, { w: 160, h: 34, color, label: label + ', recent days' })) : null);
  c.style.setProperty('--kc', color);
  if (value == null) n.textContent = '—'; else countUp(n, value);
  return c;
}
