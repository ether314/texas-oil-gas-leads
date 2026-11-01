// The National view: every state agency's drilling permits side by side. A tile map you click into, the months stacked by state, a ranking,
// the kinds of permits where a state can tell them, and a table of who is covered and who is not yet. Data: national.json (d11_nat_build.py).
import { $, el, svg, load, loadOpt, fmt, stat, monthLabel, fmtDate, chartWidth } from './util.js';
import { icon } from './icons.js';
import { segmented } from './ui.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { spark, delta } from './charts.js';
import * as N from './national-data.js';
import { GRADES } from './fields-data.js';

const MEASURE_NAME = Object.fromEntries(N.MEASURES.map((m) => [m.id, m.name]));
// what one count is: the BLM counts APDs approved by state office, Oregon applications filed, Virginia wells drilled; the others new-drill permits or wells spudded
const unitOf = (s) => s.unit || N.measureOf(s.measure).one;
const OWN_VIEW = { TX: 'tx', OK: 'ok', NM: 'nm', FO: 'fo' }; // the jurisdictions that also have the Map and Operators pages
// Element.append writes the word "null" for a null child, so nothing is appended without dropping the empty ones first
const put = (node, ...kids) => node.append(...kids.filter((k) => k != null && k !== false));
const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const sizeWord = ['', 'smallest', 'small', 'medium', 'large', 'largest'];

export function createNationalView({ root }) {
  let doc = null; let fields = null; let sel = null; let measure = 'permits'; let started = false;
  const tiles = new Map(); const rows = new Map();
  const slots = {};

  const onlyStates = (list) => list.filter((s) => !N.OVERLAP.has(s.id));
  const nameList = (measureId) => N.upFirst(N.listAnd(onlyStates(N.rankBy(doc, measureId)).map((s) => N.inName(s.id, s.name))));

  /* ---------- the hash: #national?s=ND&m=spuds ---------- */
  function writeHash() {
    const p = new URLSearchParams();
    if (sel) p.set('s', sel);
    if (measure !== 'permits') p.set('m', measure);
    const next = '#national' + (p.toString() ? '?' + p.toString() : '');
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ---------- the top: four figures ---------- */
  function figures() {
    const have = doc.states.length; const all = N.jurisdictions(doc);
    const t = doc.totals;
    const other = doc.states.filter((s) => !N.measureOf(s.measure).sum);
    return el('dl', { class: 'dr-tiles nat-kpis' }, [
      { label: 'Agencies with data', value: have + ' of ' + all, note: all - have + ' not read yet' },
      { label: 'Permits approved, last 12 months', value: fmt.format(t.permits12), note: nameList('permits') },
      t.spudStates ? { label: 'Wells spudded, last 12 months', value: fmt.format(t.spuds12), note: nameList('spuds') + ' (no approval dates by well)' } : null,
      other.length ? { label: 'Counted another way', value: String(other.length), note: N.listAnd(other.map((s) => s.name + ' (' + unitOf(s) + ')')) + ': shown, never added to the counts above' } : null,
      { label: 'Latest update', value: fmtDate(N.newest(doc)), note: 'the newest day any agency’s file was current to; each state’s own date is below' },
    ].filter(Boolean).map((x) => el('div', { class: 'dr-tile' }, el('dt', { text: x.label }), el('dd', { text: x.value }), el('small', { text: x.note }))));
  }

  // a link a visitor can open: a file download (.zip, .csv ...) or a map-service root is sent to the agency's own page instead, with the file's name in the words
  function sourceLink(s) {
    const h = N.sourceHref(s, fields);
    return h ? { href: h.href, text: 'Source: ' + s.source.name + (h.viaAgency ? ' (on the agency’s site)' : '') } : null;
  }

  /* ---------- the tile map and the state panel ---------- */
  function tileLabel(id, k) {
    if (k.kind === 'data') return k.s.name + ': ' + (N.noneRecorded(k.s) ? 'none recorded in the last 24 months' : fmt.format(k.s.p12) + ' ' + unitOf(k.s) + ' in the last 12 months') + (N.OVERLAP.has(id) ? ' (on federal land, overlaps the states)' : '');
    if (k.kind === 'gap') return k.g.name + ': producing state, no permit data read yet';
    return (N.QUIET_NAMES[id] || id) + ': no oil production in the EIA tables';
  }
  function tileMap() {
    const grid = el('div', { class: 'nat-tiles', role: 'group', 'aria-label': 'Drilling permits by state, last 12 months' });
    Object.entries(N.TILES).forEach(([id, [x, y]]) => {
      const k = N.tileKind(doc, id);
      const live = k.kind !== 'quiet';
      const cls = 'nat-tile ' + (k.kind === 'data' ? (k.size ? 't' + k.size : 'tz') + (k.s.measure === 'spuds' ? ' is-spud' : '') + (N.measureOf(k.s.measure).sum ? '' : ' is-own') + (N.OVERLAP.has(id) ? ' is-fed' : '') : k.kind === 'gap' ? 't0' : 'tq');
      const label = id === 'FO' ? 'Gulf' : id === 'BL' ? 'BLM' : id;
      const node = el(live ? 'button' : 'div', { class: cls, type: live ? 'button' : null, 'aria-label': live ? tileLabel(id, k) : null, 'aria-pressed': live ? 'false' : null, 'data-id': id },
        el('span', { class: 'nat-code', text: label }),
        k.kind === 'data' ? el('small', { class: 'nat-n', text: N.noneRecorded(k.s) ? '–' : stat(k.s.p12) }) : null);
      node.style.setProperty('--x', x + 1); node.style.setProperty('--y', y + 1);
      if (live) {
        node.addEventListener('click', () => select(id));
        const tip = (e) => { const r = node.getBoundingClientRect(); showTip(tipFor(id, k), e.clientX || r.left + 20, e.clientY || r.top); };
        node.addEventListener('pointermove', tip); node.addEventListener('pointerleave', hideTip); node.addEventListener('focus', tip); node.addEventListener('blur', hideTip);
      } else {
        node.setAttribute('title', tileLabel(id, k));
      }
      tiles.set(id, node); grid.append(node);
    });
    return grid;
  }
  function tipFor(id, k) {
    if (k.kind === 'data') {
      const s = k.s; const f = N.shownChange(s);
      if (N.noneRecorded(s)) return [el('div', { class: 'tip-head', text: s.name }), tipRow('None recorded', 'in the last 24 months'), tipRow(fmtDate(s.through), 'data through')];
      return [el('div', { class: 'tip-head', text: s.name }), tipRow(fmt.format(s.p12), unitOf(s) + ', last 12 months'),
        f != null ? tipRow((f > 0 ? '+' : f < 0 ? '−' : '') + Math.round(Math.abs(f) * 100) + '%', 'on the 12 months before') : null,
        tipRow(fmtDate(s.through), 'data through')];
    }
    if (k.kind === 'gap') return [el('div', { class: 'tip-head', text: k.g.name }), tipRow('Not read yet', k.g.grade ? 'grade ' + k.g.grade : '')];
    return [];
  }
  function legend() {
    const swatches = [1, 2, 3, 4, 5].map((c) => el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw t' + c, 'aria-hidden': 'true' }), el('span', { text: sizeWord[c] })));
    return el('div', { class: 'nat-legend' },
      el('ul', { class: 'nat-keys', 'aria-label': 'Tile shading, by size of the last 12 months against the biggest state in the same count' }, swatches),
      el('ul', { class: 'nat-keys' },
        el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw t3 is-spud', 'aria-hidden': 'true' }), el('span', { text: 'underlined: wells spudded, not permits' })),
        el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw t2 is-own', 'aria-hidden': 'true' }), el('span', { text: 'dotted: counted another way, never added (applications, wells drilled)' })),
        el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw tz', 'aria-hidden': 'true' }), el('span', { text: 'outlined, empty: read, and none in the 12 months' })),
        el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw t0', 'aria-hidden': 'true' }), el('span', { text: 'dashed: producing state, not read yet' })),
        el('li', { class: 'nat-key' }, el('i', { class: 'nat-sw tq', 'aria-hidden': 'true' }), el('span', { text: 'no oil production' }))));
  }

  function list(title, items, unit) {
    if (!items || !items.length) return null;
    const top = items[0][1];
    return el('div', { class: 'nat-list' }, el('h4', { text: title }), el('ul', {}, items.slice(0, 6).map(([name, n]) => {
      const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(n / top));
      return el('li', {}, el('span', { class: 'nat-ln', text: name, title: name }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: fmt.format(n), title: n + ' ' + N.unitFor(n, unit) }));
    })));
  }
  function bandBar(m) {
    const bar = el('div', { class: 'nat-mix', role: 'img', 'aria-label': m.map((b) => b.label + ' ' + Math.round(b.share * 100) + '%').join(', ') }, m.map((b) => {
      const seg = el('i', { class: 'nat-seg' }); seg.style.setProperty('--p', String(b.share)); seg.style.setProperty('--c', b.color); return seg;
    }));
    return bar;
  }
  function panel(id) {
    const k = N.tileKind(doc, id);
    const box = el('div', { class: 'nat-panel', 'aria-live': 'polite' });
    if (k.kind === 'quiet') {
      put(box, el('h3', { text: N.QUIET_NAMES[id] || id }), el('p', { class: 'nd', text: 'The EIA’s state tables show no oil production here, so there is no oil permit data to show. If that changes it is added.' }));
      return box;
    }
    const f = fields && fields.states && fields.states[id];
    const links = el('p', { class: 'nat-links' });
    if (k.kind === 'gap') {
      const g = k.g;
      put(box, el('div', { class: 'nat-ph' }, el('h3', { text: g.name }), el('span', { class: 'badge', text: 'Not read yet' })),
        g.agency ? el('p', { class: 'nat-agency', text: g.agency }) : null,
        el('p', { text: g.why || 'Nothing has been built for this agency yet.' }),
        el('p', { class: 'fine', text: 'It is counted as not available, never as zero.' }));
      if (f) links.append(el('a', { class: 'more-link', href: '#fields?s=' + id }, 'What its permit captures', icon('arrow', 16)));
      if (links.childNodes.length) put(box, links);
      return box;
    }
    const s = k.s; const c = N.shownChange(s);
    const first = s.bands.new.findIndex((v) => v != null);
    const vals = s.bands.new.slice(Math.max(first, s.bands.new.length - 36)).filter((v) => v != null);
    put(box, 
      el('div', { class: 'nat-ph' }, el('h3', { text: s.name }), el('span', { class: 'badge', text: MEASURE_NAME[s.measure] })),
      el('p', { class: 'nat-agency', text: s.agency + ' · counted by ' + s.basis }),
      N.noneRecorded(s)
        ? el('div', { class: 'nat-big' }, el('strong', { text: 'None recorded' }), el('span', { text: ' in the 24 months to ' + monthLabel(s.through.slice(0, 7)) + ': the source has no ' + N.measureOf(s.measure).one.replace(/^new-drill /, '') + ' dated in them, which is not the same as none happening' }))
        : el('div', { class: 'nat-big' }, el('strong', { text: fmt.format(s.p12) }), el('span', { text: ' ' + unitOf(s) + ' in the 12 months to ' + monthLabel(s.through.slice(0, 7)) }), c != null ? delta(c) : (s.prev12 !== s.p12 ? el('span', { class: 'nat-base', text: '(' + fmt.format(s.prev12) + ' the 12 months before)' }) : null)),
      vals.length > 3 ? el('div', { class: 'nat-spark' }, spark(vals, { w: 280, h: 44, color: N.SERIES_COLOR[id] || 'var(--s1)', label: s.name + ', ' + unitOf(s) + ' by month, last ' + vals.length + ' months' })) : null);
    const m = N.mix(s);
    if (m) put(box, el('div', { class: 'nat-sub' }, el('h4', { text: (N.measureOf(s.measure).family === 'permits' ? 'Kinds of permits' : 'Kinds of wells') + ', last 12 months' }), bandBar(m), el('ul', { class: 'nat-mixkeys' }, m.map((b) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', b.color); return el('li', {}, sw, b.label + ' ' + fmt.format(b.n)); }))));
    else put(box, el('p', { class: 'fine', text: 'Kinds of permits (re-entries, reworks, injection wells, amendments) are not split for ' + N.inName(id, s.name) + ' in this report.' }));
    const fl = N.fluidMix(s);
    if (fl) put(box, el('p', { class: 'fine', text: 'By fluid: ' + fl.parts.map((x) => fmt.format(x.n) + ' ' + x.id).join(', ') + (fl.unknown ? ', ' + fmt.format(fl.unknown) + ' not recorded' : '') + '.' }));
    put(box, 
      el('div', { class: 'nat-lists' }, list('Top ' + (s.place || 'counties'), s.counties, unitOf(s)), list('Top operators', s.operators, unitOf(s))),
      s.operators.length && s.namedShare != null ? el('p', { class: 'fine', text: 'Operators are named only when they are corporations, LLCs or partnerships: ' + Math.round(s.namedShare * 100) + '% of the year’s new wells.' }) : null,
      s.note ? el('p', { class: 'fine', text: s.note }) : null);
    if (OWN_VIEW[id]) links.append(el('a', { class: 'more-link', href: '#map?st=' + OWN_VIEW[id] }, 'Open ' + N.inName(id, s.name) + ' in the Map', icon('arrow', 16)));
    if (f) links.append(el('a', { class: 'more-link', href: '#fields?s=' + id }, 'What its permit captures', icon('arrow', 16)));
    const src = sourceLink(s);
    if (src) links.append(el('a', { class: 'more-link', href: src.href, target: '_blank', rel: 'noopener noreferrer' }, src.text, icon('arrow', 16)));
    put(box, links);
    return box;
  }
  function select(id, { fromHash = false } = {}) {
    sel = id && (N.byId(doc, id) || N.gapOf(doc, id) || N.TILES[id]) ? id : null;
    tiles.forEach((n, tid) => { if (n.tagName === 'BUTTON') n.setAttribute('aria-pressed', String(tid === sel)); });
    rows.forEach((n, rid) => n.setAttribute('aria-current', rid === sel ? 'true' : 'false'));
    slots.panel.replaceChildren(sel ? panel(sel) : el('div', { class: 'nat-panel' }, el('h3', { text: 'Choose a state' }), el('p', { class: 'nd', text: 'Click a tile, or a row below, for its agency, its months, the kinds of permits it files, and its top counties and operators.' })));
    if (!fromHash) writeHash();
  }

  /* ---------- the months, stacked by state ---------- */
  function monthsChart() {
    const st = N.stack(doc, measure);
    const W = chartWidth(slots.months, 1200); const H = W < 500 ? 220 : 260; const L = 42; const R = 6; const T = 10; const B = 24;
    const n = st.months.length; const slot = (W - L - R) / Math.max(1, n); const bw = Math.max(3, slot * 0.74);
    const { top, ticks } = N.niceMax(Math.max(...st.totals, 1));
    const y = (v) => T + (H - T - B) * (1 - v / top);
    const g = svg('svg', { class: 'nat-chart', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img',
      'aria-label': MEASURE_NAME[measure] + ' by month, ' + monthLabel(st.months[0]) + ' to ' + monthLabel(st.months[n - 1]) + ', stacked by state; the table below has the numbers' });
    ticks.forEach((t) => {
      g.append(svg('line', { class: t === 0 ? 'base' : 'grid', x1: L, x2: W - R, y1: y(t), y2: y(t) }), svg('text', { class: 'ax', x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: stat(t) }));
    });
    st.months.forEach((ym, i) => {
      const x = L + slot * i + (slot - bw) / 2;
      let acc = 0;
      st.series.forEach((s) => {
        const v = s.values[i]; if (!v) return;
        const seg = svg('rect', { class: 'nat-bar-seg', x: x.toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1), rx: 1.5 });
        seg.style.setProperty('--c', s.color); g.append(seg); acc += v;
      });
      if (ym.slice(5) === '01' || ym.slice(5) === '07') g.append(svg('text', { class: 'ax', x: x + bw / 2, y: H - 6, 'text-anchor': 'middle', text: monthLabel(ym).replace(/(\w+) (\d{4})/, (a, mo, yr) => mo + ' ’' + yr.slice(2)) }));
      const hit = svg('rect', { class: 'nat-hit', x: (L + slot * i).toFixed(1), y: T, width: slot.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: monthLabel(ym) }), ...st.series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name)), tipRow(fmt.format(st.totals[i]), 'in all')], e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      g.append(hit);
    });
    const key = el('ul', { class: 'nat-keys nat-chart-keys', 'aria-label': 'States in the chart' }, st.series.map((s) => {
      const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', s.color);
      return el('li', { class: 'nat-key' }, sw, el('span', { text: s.name + (s.count ? ' (' + s.count + ')' : '') }));
    }));
    const note = el('p', { class: 'fine', text: 'The chart ends in ' + monthLabel(st.end) + ', the newest month every state shown has. ' + (measure === 'spuds' ? 'Wells spudded are reported late, so these counts run two months behind the permits. ' : '') + (st.lagging.length ? N.listAnd(st.lagging) + (st.lagging.length > 1 ? ' end' : ' ends') + ' earlier, so the last months of the bars leave ' + (st.lagging.length > 1 ? 'them' : 'it') + ' out (not counted as zero). ' : '') + 'The BLM’s onshore permits are not added here: the states also permit most of those wells.' });
    const table = el('details', { class: 'nat-details' }, el('summary', { text: 'Show the numbers as a table' }),
      el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'Monthly counts by state' },
        el('table', { class: 'grid' }, el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: 'Month' }), st.series.map((s) => el('th', { scope: 'col', class: 'num', text: s.name })), el('th', { scope: 'col', class: 'num', text: 'All' }))),
          el('tbody', {}, st.months.map((ym, i) => el('tr', {}, el('th', { scope: 'row', text: monthLabel(ym) }), st.series.map((s) => el('td', { class: 'num', text: fmt.format(s.values[i]) })), el('td', { class: 'num', text: fmt.format(st.totals[i]) }))).reverse()))));
    return [key, g, note, table];
  }

  /* ---------- the ranking ---------- */
  function ranking() {
    const wrap = el('div', { class: 'nat-rank' });
    N.MEASURES.forEach((meas) => {
      const m = meas.id;
      const list = N.rankBy(doc, m); if (!list.length) return;
      const top = Math.max(1, ...list.map((s) => s.p12));
      wrap.append(el('h3', { class: 'nat-rh', text: meas.name + ' (' + meas.by + ')' + (meas.sum ? '' : ': counted another way, added to nothing') }),
        el('ul', { class: 'nat-rows' }, list.map((s) => {
          const bar = el('i', { class: 'nat-rb' }); bar.style.setProperty('--p', String(s.p12 / top)); bar.style.setProperty('--c', N.SERIES_COLOR[s.id] || 'var(--n-other)');
          const b = el('button', { type: 'button', class: 'nat-row', 'aria-current': 'false', 'aria-label': s.name + ', ' + (N.noneRecorded(s) ? 'none recorded in the last 24 months' : fmt.format(s.p12) + ' in the last 12 months') + '. Open its panel.' },
            el('span', { class: 'nat-rn' }, el('span', { class: 'nat-rc', text: s.id === 'FO' ? 'Gulf' : s.id === 'BL' ? 'BLM' : s.id }), s.name), el('span', { class: 'nat-rt' }, bar),
            el('span', { class: 'nat-rv', text: N.noneRecorded(s) ? '–' : fmt.format(s.p12) }), el('span', { class: 'nat-rd' }, N.shownChange(s) != null ? delta(N.shownChange(s)) : el('span', { class: 'nd', text: 'n/a' })),
            el('span', { class: 'nat-rw', text: 'to ' + monthLabel(s.through.slice(0, 7)) }));
          b.addEventListener('click', () => { select(s.id); slots.map.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
          rows.set(s.id, b);
          return el('li', {}, b);
        })));
    });
    wrap.append(el('p', { class: 'fine', text: 'Each state’s last 12 complete months against the 12 before. The BLM line counts permits on federal land, which the states also permit, so it is shown but never added to the states.' }));
    return wrap;
  }

  /* ---------- kinds of permits ---------- */
  function mixCard() {
    const withMix = N.statesWithMix(doc);
    if (!withMix.length) return null;
    const ul = el('ul', { class: 'nat-mixrows' }, withMix.sort((a, b) => b.p12 - a.p12).map((s) => {
      const m = N.mix(s); const bar = bandBar(m);
      return el('li', {}, el('button', { type: 'button', class: 'link nat-mn', text: s.name, onclick: () => { select(s.id); slots.map.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }), bar,
        el('span', { class: 'nat-mv', text: fmt.format(m.reduce((t, b) => t + b.n, 0)) + (N.measureOf(s.measure).family === 'permits' ? ' filings' : ' wells') }));
    }));
    const keys = el('ul', { class: 'nat-keys' }, N.BANDS.map((b) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', b.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: b.label })); }));
    const others = doc.states.filter((s) => !N.mix(s)).map((s) => N.inName(s.id, s.name));
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('Every kind of filing', 'layers', 'What the permits are for', 'New wells, injection and disposal wells, re-entries, reworks and amendments, for the states whose agencies tell them apart.'),
      keys, ul, others.length ? el('p', { class: 'fine', text: 'Not split in this report: ' + N.upFirst(N.listAnd(others)) + '.' }) : null);
  }

  /* ---------- who is covered ---------- */
  function coverageCard() {
    const order = N.MEASURES.flatMap((m) => N.rankBy(doc, m.id)).map((s) => s.id).concat(doc.gaps.map((g) => g.id).sort((a, b) => N.nameOf(doc, a).localeCompare(N.nameOf(doc, b))));
    const data = N.coverage(doc, order);
    const status = (r) => (r.status === 'gap' ? 'Not read yet' : MEASURE_NAME[r.status]);
    const table = el('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Which agencies the report covers' },
      el('table', { class: 'grid nat-cov' }, el('thead', {}, el('tr', {}, ['State', 'Counts', 'Agency', 'Data through', 'Updates'].map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, data.map((r) => el('tr', { class: r.status === 'gap' ? 'is-gap' : null },
          el('th', { scope: 'row' }, el('button', { type: 'button', class: 'link', text: r.name, onclick: () => { select(r.id); slots.map.scrollIntoView({ behavior: 'smooth', block: 'start' }); } })),
          el('td', { 'data-label': 'Counts' }, status(r)),
          el('td', { 'data-label': 'Agency' }, r.agency || el('span', { class: 'nd', text: 'not researched' }), r.status === 'gap' && r.why ? el('small', { class: 'nat-why', text: r.why }) : null,
            r.status === 'gap' && r.grade && GRADES[r.grade] ? el('small', { class: 'nat-why', text: 'Its published data, as researched (grade ' + r.grade + '): ' + GRADES[r.grade].replace(/^./, (c) => c.toLowerCase()) + '.' }) : null),
          el('td', { 'data-label': 'Data through', text: r.through ? monthLabel(r.through.slice(0, 7)) : '—' }),
          el('td', { 'data-label': 'Updates', text: r.cadence ? N.upFirst(r.cadence) : '—' }))))));
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('Coverage', 'building', 'Who is covered, and who is not yet', 'Every state with oil production is listed. A state with no data here is counted as not available, never as zero.'), table);
  }

  async function build() {
    root.replaceChildren(el('p', { class: 'status', text: 'Loading the national report…' }));
    try {
      doc = await load('national');
      fields = doc.hasFields ? await loadOpt('permit-fields') : null; // the matrix file is only asked for once it exists
    } catch (e) {
      root.replaceChildren(el('div', { class: 'fail' }, el('p', { text: 'Could not load the national data. Reload the page to try again.' })));
      return false;
    }
    slots.panel = el('div', { class: 'nat-panel-slot' });
    slots.map = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'nat-map-h' });
    const mapHead = hdr('The map', 'pin', 'Where the permits are', 'Each tile is a state, shaded by its last 12 months against the biggest state counting the same thing. Click one.');
    mapHead.querySelector('h2').id = 'nat-map-h';
    slots.map.append(mapHead, el('div', { class: 'nat-map-grid' }, el('div', {}, tileMap(), legend()), slots.panel));
    const seg = segmented({ label: 'What to count', tabs: false, prefix: 'natm', value: measure, options: [{ id: 'permits', label: 'Permits approved' }, { id: 'spuds', label: 'Wells spudded' }], onChange: (id) => { measure = id; drawMonths(); writeHash(); } });
    slots.months = el('div', { class: 'nat-months' });
    const monthsCard = el('section', { class: 'card nat-card reveal is-in' }, hdr('Month by month', 'chart', 'The last three years, stacked by state', 'Permits approved and wells spudded are different counts, so they are never in one stack.', el('div', { class: 'card-tools' }, seg.el)), slots.months);
    const rankCard = el('section', { class: 'card nat-card reveal is-in' }, hdr('State by state', 'trend', 'The ranking', 'Last 12 complete months, with the change on the 12 before.'), ranking());
    root.replaceChildren(el('div', { class: 'stack' }, figures(), slots.map, monthsCard, rankCard, mixCard(), coverageCard(), el('p', { class: 'fine', text: 'Public records only: business-, place- and market-level counts, no individuals. Public records can be wrong or stale; each agency’s date is shown.' })));
    root._seg = seg;
    drawMonths();
    return true;
  }
  function drawMonths() { slots.months.replaceChildren(...monthsChart()); drawnAt = chartWidth(slots.months, 1200); }
  // the chart is drawn at its container's width: a window that changes size draws it again (not on every pixel)
  let drawnAt = 0; let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (started && slots.months && slots.months.isConnected && slots.months.clientWidth && Math.abs(chartWidth(slots.months, 1200) - drawnAt) > 24) drawMonths(); }, 150);
  });

  return {
    async activate(params) {
      if (!started) { started = true; if (!(await build())) { started = false; return; } }
      const m = params && params.get('m'); const s = params && (params.get('s') || '').toUpperCase();
      const want = m === 'spuds' ? 'spuds' : 'permits'; // the address decides: one without a count is the permits (it kept the last choice, so a link to a state drew spuds after a visit to Wells spudded)
      if (want !== measure) { measure = want; root._seg.set(want, false); }
      drawMonths(); // at the width the page has now (the view may have been hidden, or the window resized, since it was drawn)
      select(s || sel || (N.rankBy(doc, 'permits')[0] || {}).id || null, { fromHash: true });
    },
    deactivate() { hideTip(); },
  };
}
