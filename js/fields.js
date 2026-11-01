// The permit-data view: what each agency's permit captures. A matrix of agencies by metric, each cell saying whether the metric is published as data, only in a
// one-well lookup, only on the form, not captured, or not verified; click a cell, an agency or a metric to see why. Data: permit-fields.json (d11_fields_build.py).
import { el, load } from './util.js';
import { icon } from './icons.js';
import { segmented } from './ui.js';
import { showTip, hideTip, tipRow } from './tip.js';
import * as F from './fields-data.js';

const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const dot = (s) => el('span', { class: 'fx-dot s-' + s, 'aria-hidden': 'true', text: s === 'unknown' ? '?' : null });
const code = (id) => F.CODES.find((c) => c.id === id);
const ext = (href, text) => el('a', { class: 'more-link', href, target: '_blank', rel: 'noopener noreferrer' }, text, icon('arrow', 16));

export function createFieldsView({ root }) {
  let doc = null; let started = false;
  let sel = { s: null, m: null }; let group = 'all'; let sort = 'coverage';
  const slots = {};
  const cellBtns = new Map(); const colHeads = new Map(); const rowHeads = new Map();

  function writeHash() {
    const p = new URLSearchParams();
    if (sel.s) p.set('s', sel.s);
    if (sel.m) p.set('m', sel.m);
    if (group !== 'all') p.set('g', group);
    const next = '#fields' + (p.toString() ? '?' + p.toString() : '');
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ---------- the top ---------- */
  function figures() {
    const h = F.headline(doc);
    return el('dl', { class: 'dr-tiles nat-kpis' }, [
      { label: 'Agencies compared', value: String(h.agencies), note: 'every producing state, the BLM and the offshore, as researched' },
      { label: 'Metrics compared', value: String(h.metrics), note: 'seven groups, from the operator to the well logs' },
      h.best ? { label: 'Most published as data', value: doc.states[h.best.id].name, note: h.best.n + ' of ' + h.metrics + ' metrics in downloadable data' } : null,
      h.topMetric ? { label: 'Published by the most agencies', value: h.topMetric.m.label, note: h.topMetric.n + ' of ' + h.agencies + ' agencies as data' } : null,
      { label: 'Not verified', value: F.percent(h.unknownShare, 1) + '%', note: 'of cells: marked so, never guessed' },
    ].filter(Boolean).map((x) => el('div', { class: 'dr-tile' }, el('dt', { text: x.label }), el('dd', { text: x.value }), el('small', { text: x.note }))));
  }
  function legend() {
    return el('ul', { class: 'nat-keys fx-legend', 'aria-label': 'What a cell means' }, F.CODES.map((c) => el('li', { class: 'nat-key' }, dot(c.id), el('span', {}, el('strong', { text: c.label }), ' ' + c.def))));
  }

  /* ---------- the matrix ---------- */
  function matrix() {
    cellBtns.clear(); colHeads.clear(); rowHeads.clear();
    const cols = F.columns(doc, sort);
    const metrics = F.metricsIn(doc, group);
    const head = el('tr', {}, el('th', { scope: 'col', class: 'fx-corner', text: 'Metric' }), cols.map((id) => {
      const b = el('button', { type: 'button', class: 'fx-h', 'aria-label': doc.states[id].name + ': what its permit captures', 'aria-pressed': 'false', title: doc.states[id].name, text: F.shortCode(id) });
      b.addEventListener('click', () => choose({ s: id, m: null })); colHeads.set(id, b);
      return el('th', { scope: 'col', class: 'fx-col' }, b);
    }), el('th', { scope: 'col', class: 'fx-tot', text: 'Agencies as data' }));
    const score = el('tr', { class: 'fx-score' }, el('th', { scope: 'row', class: 'fx-corner', text: 'Metrics as data' }), cols.map((id) => el('td', { class: 'fx-n', title: doc.states[id].name + ': ' + F.stateScore(doc, id).data + ' of ' + doc.metrics.length + ' metrics are published as data', text: String(F.stateScore(doc, id).data) })), el('td', { class: 'fx-n' }));
    const body = [];
    let lastGroup = null;
    metrics.forEach((m) => {
      if (m.group !== lastGroup) {
        lastGroup = m.group;
        body.push(el('tr', { class: 'fx-group' }, el('th', { scope: 'colgroup', colspan: cols.length + 2, text: doc.groups.find((g) => g.id === m.group).label })));
      }
      const ms = F.metricScore(doc, m.key);
      const rb = el('button', { type: 'button', class: 'link fx-m', 'aria-pressed': 'false', text: m.label, title: m.help });
      rb.addEventListener('click', () => choose({ s: null, m: m.key })); rowHeads.set(m.key, rb);
      body.push(el('tr', { 'data-m': m.key }, el('th', { scope: 'row', class: 'fx-rh' }, rb), cols.map((id) => {
        const c = F.cellOf(doc, id, m.key);
        const b = el('button', { type: 'button', class: 'fx-c', 'aria-pressed': 'false', 'aria-label': doc.states[id].name + ', ' + m.label + ': ' + code(c.s).label.toLowerCase() }, dot(c.s));
        b.addEventListener('click', () => choose({ s: id, m: m.key }));
        const tip = (e) => { const r = b.getBoundingClientRect(); showTip([el('div', { class: 'tip-head', text: doc.states[id].name }), tipRow(m.label, ''), tipRow(code(c.s).label, c.n ? '· ' + c.n : '')], e.clientX || r.left, e.clientY || r.top); };
        b.addEventListener('pointermove', tip); b.addEventListener('pointerleave', hideTip); b.addEventListener('focus', tip); b.addEventListener('blur', hideTip);
        cellBtns.set(id + '|' + m.key, b);
        return el('td', { class: 'fx-cell' }, b);
      }), el('td', { class: 'fx-n', text: ms.data + ' of ' + ms.total })));
    });
    return el('div', { class: 'table-wrap tall fx-wrap', role: 'region', tabindex: '0', 'aria-label': 'Matrix of what each permit captures, agencies across and metrics down' },
      el('table', { class: 'fx' }, el('thead', {}, head, score), el('tbody', {}, body)));
  }
  function redraw() { slots.matrix.replaceChildren(matrix()); mark(); }
  function mark() {
    cellBtns.forEach((b, k) => { const [s, m] = k.split('|'); b.setAttribute('aria-pressed', String(s === sel.s && m === sel.m)); b.classList.toggle('in-line', (s === sel.s && !sel.m) || (m === sel.m && !sel.s)); });
    colHeads.forEach((b, id) => b.setAttribute('aria-pressed', String(id === sel.s && !sel.m)));
    rowHeads.forEach((b, k) => b.setAttribute('aria-pressed', String(k === sel.m && !sel.s)));
  }

  /* ---------- the panel ---------- */
  function statusBar(counts, total) {
    const bar = el('div', { class: 'nat-mix fx-bar', role: 'img', 'aria-label': F.CODES.map((c) => counts[c.id] + ' ' + c.label.toLowerCase()).join(', ') }, F.CODES.filter((c) => counts[c.id]).map((c) => { const seg = el('i', { class: 'nat-seg fx-seg s-' + c.id }); seg.style.setProperty('--p', String(counts[c.id] / total)); return seg; }));
    return el('div', {}, bar, el('ul', { class: 'nat-mixkeys' }, F.CODES.map((c) => el('li', {}, dot(c.id), c.label + ' ' + counts[c.id]))));
  }
  function cellPanel(sid, key) {
    const s = doc.states[sid]; const m = doc.metrics.find((x) => x.key === key); const c = F.cellOf(doc, sid, key); const st = code(c.s);
    return el('div', { class: 'nat-panel' },
      el('div', { class: 'nat-ph' }, dot(c.s), el('h3', { text: s.name + ': ' + m.label }), el('span', { class: 'badge', text: st.label })),
      el('p', { class: 'nat-agency', text: m.help }),
      el('p', {}, el('strong', { text: st.label + '. ' }), st.def),
      c.n ? el('p', { text: c.n }) : null,
      el('p', { class: 'fine', text: 'Evidence: ' + F.EVIDENCE[c.e] + '.' }),
      el('p', { class: 'nat-links' }, el('button', { type: 'button', class: 'link', text: 'All of ' + s.name, onclick: () => choose({ s: sid, m: null }) }), el('button', { type: 'button', class: 'link', text: 'Every agency on “' + m.label + '”', onclick: () => choose({ s: null, m: key }) })));
  }
  function statePanel(sid) {
    const s = doc.states[sid]; const sc = F.stateScore(doc, sid);
    const srcs = s.sources.length ? el('ul', { class: 'fx-sources' }, s.sources.map((x) => el('li', {},
      el('strong', { text: x.name }), el('small', { text: [x.format, x.grain === 'aggregate' ? 'totals only' : x.grain === 'well' ? 'one row a well' : x.grain === 'permit' ? 'one row a permit' : '', x.cadence, x.history_from && x.history_from !== 'unknown' ? 'from ' + x.history_from : '', F.REACH[x.reachable]].filter(Boolean).join(' · ') }),
      x.url ? ext(x.url, 'Open') : null))) : el('p', { class: 'nd', text: 'No open data source found.' });
    return el('div', { class: 'nat-panel' },
      el('div', { class: 'nat-ph' }, el('h3', { text: s.name }), el('span', { class: 'badge', text: 'Grade ' + s.grade })),
      el('p', { class: 'nat-agency', text: s.agency.name }),
      el('p', { text: F.GRADES[s.grade] + '. ' + s.grade_reason }),
      el('div', { class: 'nat-sub' }, el('h4', { text: 'What its permit captures' }), statusBar(sc, sc.total)),
      el('div', { class: 'nat-sub' }, el('h4', { text: 'The permit form' }), el('p', { text: s.form.name + (s.form.number ? ' (' + s.form.number + ')' : '') + (s.form.read ? '' : '. Not read: the cells are unverified.') }), s.form.url ? ext(s.form.url, 'Open the form') : null),
      el('div', { class: 'nat-sub' }, el('h4', { text: 'What it publishes' }), srcs),
      s.producer_plan ? el('div', { class: 'nat-sub' }, el('h4', { text: 'How a monthly count could be built' }), el('p', { class: 'fine', text: s.producer_plan })) : null,
      s.unknowns.length ? el('div', { class: 'nat-sub' }, el('h4', { text: 'Not determined' }), el('ul', { class: 'fx-unk' }, s.unknowns.map((u) => el('li', { text: u })))) : null,
      el('p', { class: 'nat-links' }, el('a', { class: 'more-link', href: '#national?s=' + sid }, 'See its permits in the national report', icon('arrow', 16)), s.agency.url ? ext(s.agency.url, 'The agency') : null));
  }
  function metricPanel(key) {
    const m = doc.metrics.find((x) => x.key === key); const ms = F.metricScore(doc, key); const by = F.byStatus(doc, key);
    return el('div', { class: 'nat-panel' },
      el('div', { class: 'nat-ph' }, el('h3', { text: m.label }), el('span', { class: 'badge', text: ms.data + ' of ' + ms.total + ' as data' })),
      el('p', { class: 'nat-agency', text: m.help }),
      statusBar(ms, ms.total),
      F.CODES.filter((c) => by[c.id].length).map((c) => el('div', { class: 'nat-sub', key: c.id }, el('h4', { text: c.label + ' (' + by[c.id].length + ')' }),
        el('ul', { class: 'fx-chips' }, by[c.id].map((id) => el('li', {}, el('button', { type: 'button', class: 'link', text: doc.states[id].name, onclick: () => choose({ s: id, m: key }) })))))));
  }
  function showPanel() {
    slots.panel.replaceChildren(sel.s && sel.m ? cellPanel(sel.s, sel.m) : sel.s ? statePanel(sel.s) : sel.m ? metricPanel(sel.m)
      : el('div', { class: 'nat-panel' }, el('h3', { text: 'Choose a cell, an agency or a metric' }), el('p', { class: 'nd', text: 'Click a symbol for what that agency does with that metric and how we know. Click an agency’s code for its form, its open data and how its permits could be counted; click a metric for every agency at once.' })));
  }
  function choose(next, { fromHash = false } = {}) {
    sel = { s: next.s && doc.states[next.s] ? next.s : null, m: next.m && doc.metrics.some((m) => m.key === next.m) ? next.m : null };
    mark(); showPanel();
    if (!fromHash) { writeHash(); slots.panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  }

  async function build() {
    root.replaceChildren(el('p', { class: 'status', text: 'Loading the permit data…' }));
    try { doc = await load('permit-fields'); } catch (e) {
      root.replaceChildren(el('div', { class: 'fail' }, el('p', { text: 'Could not load the permit data. Reload the page to try again.' })));
      return false;
    }
    slots.panel = el('div', { class: 'fx-panel-slot', 'aria-live': 'polite' });
    slots.matrix = el('div', {});
    const gseg = segmented({ label: 'Group of metrics', tabs: false, prefix: 'fxg', value: group, options: [{ id: 'all', label: 'All' }, ...doc.groups.map((g) => ({ id: g.id, label: g.label }))], onChange: (id) => { group = id; redraw(); writeHash(); } });
    const sseg = segmented({ label: 'Order of agencies', tabs: false, prefix: 'fxs', value: sort, options: [{ id: 'coverage', label: 'Most published first' }, { id: 'name', label: 'A to Z' }], onChange: (id) => { sort = id; redraw(); } });
    root._g = gseg;
    const card = el('section', { class: 'card nat-card reveal is-in' }, hdr('The matrix', 'layers', 'Agency by metric', 'Every cell is checked against the permit form or a real data file, and says which. “Not verified” is an honest answer, not a gap in the page.', el('div', { class: 'card-tools' }, sseg.el)),
      el('div', { class: 'fx-tools' }, gseg.el), legend(), slots.matrix);
    root.replaceChildren(el('div', { class: 'stack' }, figures(), card, el('section', { class: 'card nat-card reveal is-in' }, hdr('Detail', 'pin', 'Why a cell says what it says', null), slots.panel),
      el('p', { class: 'fine', text: 'Researched from each agency’s permit application and its published data, with the evidence named on every cell. An agency whose form or data could not be read from here says so; those cells read “not verified”.' })));
    redraw();
    return true;
  }
  return {
    async activate(params) {
      if (!started) { started = true; if (!(await build())) { started = false; return; } }
      const g = params && params.get('g');
      if (g && doc.groups.some((x) => x.id === g) && g !== group) { group = g; root._g.set(g, false); redraw(); }
      choose({ s: params && (params.get('s') || '').toUpperCase(), m: params && params.get('m') }, { fromHash: true });
    },
    deactivate() { hideTip(); },
  };
}
