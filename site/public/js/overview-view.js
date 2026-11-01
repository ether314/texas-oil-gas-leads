// The Overview: the country's new wells, the same for every state. A hero with the map as its backdrop and four figures, the explorer (every well of the last two years as a
// dot: hover one for its well, click a state to zoom in, replay the two years), the states ranked, the months stacked by state, the top counties and operators, and when
// each source was current. Everything here is drawn from data/newwells/ (FracFocus: one GPS point per fractured well), the one source that has the same facts for every
// state that reports to it; nothing is shown that only some states can give. The permits themselves, by each agency's own count, are the National page.
import { $, el, svg, load, loadOpt, fmt, stat, fmtDate, monthLabel, countUp, reduced } from './util.js';
import { icon } from './icons.js';
import { spark, delta } from './charts.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { createTimelapse } from './timelapse.js';
import { renderFreshness } from './overview.js';
import * as G from './usgeo.js';
import * as D from './newwells-data.js';
import { createUSMap } from './usmap.js';

const put = (node, ...kids) => node.append(...kids.filter((k) => k != null && k !== false));
const SOURCE = 'https://fracfocus.org/data-download';
const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const OWN_MAP = { TX: 'tx', OK: 'ok', NM: 'nm' }; // the states the Map and Operators tabs also cover

export function createOverview(meta) {
  let loaded = null; let started = false; let sel = null; let seq = 0;
  const S = { map: null, hero: null, tl: null, rows: new Map(), chips: new Map(), panel: null, pick: null };

  /* ---------- the data: one summary, one set of points, the outlines, and the national file for the list of producing states ---------- */
  async function data() {
    if (loaded) return loaded;
    const [doc, pts, out, nat] = await Promise.all([load('newwells/summary'), load('newwells/points'), load('us-states'), loadOpt('national')]);
    const P = D.decode(pts); const outlines = G.buildOutlines(out);
    const producing = nat ? [...nat.states, ...nat.gaps].filter((s) => !['FO', 'BL'].includes(s.id)).map((s) => ({ id: s.id, name: s.name })) : [];
    const win = D.windowOf(doc); const range = D.settledRange(P, doc);
    loaded = { doc, P, outlines, nat, producing, win, range, T: D.totals(doc) };
    return loaded;
  }

  /* ---------- the hero: eyebrow, lede, four figures, the note, and the map behind them ---------- */
  function hero(dt) {
    const { doc, T, P, win, range } = dt;
    $('#hero-eyebrow').textContent = 'FracFocus registry, wells through ' + fmtDate(doc.asOf);
    $('#hero-lede').textContent = 'Every new well in America with a GPS point, from every state that reports it: where it is, who drilled it and how big the job was. Public records only, built ' + fmtDate(meta.built) + '.';
    const land = D.landShare(P, range[0], range[1]);
    const top3 = D.listAnd(D.active(doc).slice(0, 3).map((s) => s.name));
    const chips = [
      { label: 'New wells, last 12 months', value: T.p12, hero: true, href: '#daily', note: [delta(T.change), ' vs the 12 months before'], sub: monthLabel(win.months[0]) + ' to ' + monthLabel(win.months[11]) + ' · settled months only' },
      { label: 'States with new wells', value: T.active, href: '#national', note: top3 + ' and ' + (T.active - 3) + ' more · fractured wells only' },
      { label: 'On federal or tribal land', value: land.of ? Math.round((land.n / land.of) * 100) : null, suffix: '%', href: '#national?s=BL', note: 'of the year’s wells; the BLM’s own permits are on the National page' },
      { label: 'Newest well', text: fmtDate(doc.asOf).replace(/, \d{4}$/, ''), href: '#daily', note: 'the last four months are still filling in: wells are disclosed weeks late' },
    ];
    $('#kpis').replaceChildren(...chips.map((k) => {
      const num = el('strong', { class: 'kpi-num', 'aria-hidden': k.text ? null : 'true', title: k.value != null ? fmt.format(k.value) + (k.suffix || '') : null });
      const a = el('a', { class: 'kpi-chip' + (k.hero ? ' hero-fig' : ''), href: k.href }, el('span', { class: 'kpi-chip-label', text: k.label }), num,
        k.text ? null : el('span', { class: 'sr-only', text: k.value == null ? 'not available' : fmt.format(k.value) + (k.suffix || '') }), el('span', { class: 'kpi-chip-note' }, k.note), k.sub ? el('span', { class: 'kpi-chip-sub', text: k.sub }) : null, el('span', { class: 'sr-only', text: 'Open' }));
      if (k.text) num.textContent = k.text;
      else if (k.value == null) num.textContent = 'n/a';
      else countUp(num, k.value, (v) => (k.hero ? fmt.format(v) : stat(v)) + (k.suffix || ''));
      return a;
    }));
    $('#hero-note').textContent = 'Dots are the ' + fmt.format(P.n) + ' wells of the last 24 months, each where it sits (every well in the registry has a usable point). Brighter dots are the newest. FracFocus lists wells that were hydraulically fractured, nearly every new oil well; a well that was not fractured, and any well disclosed after ' + fmtDate(doc.asOf) + ', is not in it. Figures use settled months only: ' + monthLabel(doc.settled.slice(0, 7)) + ' and before.';
  }
  function heroBox(host) {
    return (w, h) => {
      const kp = host.querySelector('.kpis'); const hi = host.querySelector('.hero-in');
      if (w >= 900) return { x0: Math.max(w * 0.38, hi ? hi.offsetLeft + hi.offsetWidth + 10 : 0), x1: w - 28, y0: 22, y1: kp ? kp.offsetTop - 16 : h - 22 };
      const reserve = (hi && parseFloat(getComputedStyle(hi).paddingBottom)) || 260; const bottom = kp ? kp.offsetTop - 8 : h - 8;
      return { x0: 6, x1: w - 6, y0: Math.max(0, bottom - reserve + 6), y1: bottom };
    };
  }

  /* ---------- the explorer: the map, its legend, the replay and the panel of the state it is zoomed to ---------- */
  const listBlock = (title, rows, unit) => {
    if (!rows.length) return null;
    const top = rows[0].n;
    return el('div', { class: 'nat-list' }, el('h4', { text: title }), el('ul', {}, rows.map((r) => {
      const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(r.n / top));
      return el('li', {}, el('span', { class: 'nat-ln', text: r.label + (r.state && r.showState ? ', ' + r.state : ''), title: r.label }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: fmt.format(r.n), title: r.n + ' ' + unit }));
    })));
  };
  function panel(dt, id) {
    const { doc, P, range, win, T } = dt; const box = el('div', { class: 'nat-panel', 'aria-live': 'polite' });
    if (!id) {
      const land = D.landShare(P, range[0], range[1]);
      put(box, el('div', { class: 'nat-ph' }, el('h3', { text: 'All states' }), el('span', { class: 'badge', text: 'Fractured wells' })),
        el('p', { class: 'nat-agency', text: 'FracFocus registry · counted by the day of the first job' }),
        el('div', { class: 'nat-big' }, el('strong', { text: fmt.format(T.p12) }), el('span', { text: ' new wells in the 12 months to ' + monthLabel(doc.settled.slice(0, 7)) }), T.change != null ? delta(T.change) : null),
        el('p', { class: 'nd', text: 'Click a state on the map, or its name in the key, to zoom in and see its counties, its operators and how it has moved. Hover or tap a dot for the well.' }),
        el('p', { class: 'fine', text: fmt.format(land.n) + ' of the ' + fmt.format(land.of) + ' wells of that year (' + Math.round((land.n / Math.max(1, land.of)) * 100) + '%) are on federal or tribal land.' }));
      return box;
    }
    const s = D.byId(doc, id); const c = D.shownChange(s);
    const i = D.settledIndex(doc); const vals = s.new.slice(Math.max(0, i - 35), i + 1);
    const co = D.leaders(P, range[0], range[1], { state: id, by: 'c', limit: 6 }); const op = D.leaders(P, range[0], range[1], { state: id, by: 'o', limit: 6 });
    const land = D.landShare(P, range[0], range[1], id);
    put(box, el('div', { class: 'nat-ph' }, el('h3', { text: s.name }), el('span', { class: 'badge', text: 'Fractured wells' })),
      el('p', { class: 'nat-agency', text: 'Newest job ' + fmtDate(s.latest) + ' · counted by the day of the first job' }),
      el('div', { class: 'nat-big' }, el('strong', { text: fmt.format(s.p12) }), el('span', { text: ' new wells in the 12 months to ' + monthLabel(doc.settled.slice(0, 7)) }), c != null ? delta(c) : null),
      vals.length > 3 ? el('div', { class: 'nat-spark' }, spark(vals, { w: 280, h: 44, color: D.colorOf(id), label: s.name + ', new wells by month, last ' + vals.length + ' settled months' })) : null,
      el('div', { class: 'nat-lists' }, listBlock('Top counties', co.rows, 'wells'), listBlock('Top operators', op.rows, 'wells')),
      op.total ? el('p', { class: 'fine', text: 'Operators are named only when they are corporations, LLCs or partnerships: ' + Math.round((1 - op.unnamed / op.total) * 100) + '% of the year’s wells.' }) : null,
      el('p', { class: 'fine', text: [s.tvd ? 'Median depth ' + fmt.format(s.tvd) + ' ft' : null, s.water ? 'median ' + s.water.toFixed(1) + ' million gallons of water' : null, land.of ? Math.round((land.n / land.of) * 100) + '% on federal or tribal land' : null].filter(Boolean).join(' · ') + '.' }));
    const links = el('p', { class: 'nat-links' });
    links.append(el('a', { class: 'more-link', href: '#national?s=' + id }, 'Its permits, by the agency’s own count', icon('arrow', 16)));
    if (OWN_MAP[id]) links.append(el('a', { class: 'more-link', href: '#map?st=' + OWN_MAP[id] }, 'Open ' + s.name + ' in the Map', icon('arrow', 16)));
    links.append(el('a', { class: 'more-link', href: SOURCE, target: '_blank', rel: 'noopener noreferrer' }, 'Source: FracFocus', icon('arrow', 16)));
    put(box, links);
    return box;
  }
  function select(id, { fromHash = false } = {}) {
    const dt = loaded; if (!dt) return;
    sel = id && D.byId(dt.doc, id) && D.byId(dt.doc, id).p12 > 0 ? id : null;
    if (S.map) S.map.select(sel, true);
    S.panel.replaceChildren(panel(dt, sel));
    S.rows.forEach((n, rid) => n.setAttribute('aria-current', String(rid === sel)));
    S.chips.forEach((n, cid) => n.setAttribute('aria-pressed', String(cid === sel)));
    if (S.pick) S.pick.value = sel || '';
    if (!fromHash) {
      const next = '#overview' + (sel ? '?s=' + sel : '');
      if (location.hash !== next) history.replaceState(null, '', next);
    }
  }
  function explorer(dt) {
    const { doc, P, outlines } = dt;
    const canvas = el('canvas', { class: 'nw-canvas', role: 'img', 'aria-label': 'Map of the ' + fmt.format(P.n) + ' new wells of the last 24 months, one dot each, in ' + D.active(doc).length + ' states. The ranking below lists the states in text; choose a state with the selector to zoom to it.' });
    const stage = el('div', { class: 'nw-stage' }, canvas);
    S.map = createUSMap({ canvas, host: stage, outlines, P, doc, interactive: true, onSelect: (id) => select(id) });
    S.tl = createTimelapse({ engine: S.map, t0: P.t0, label: 'Watch the new wells', thing: { one: 'well', many: 'wells' }, lead: 'Two years of new wells.', note: ' Each dot appears on the day of its first job and glows for a month. The newest weeks are still being disclosed.' });
    const watch = el('button', { type: 'button', class: 'btn', 'aria-pressed': 'false' }, icon('play', 16), 'Watch 24 months');
    watch.addEventListener('click', () => {
      const on = !S.tl.open; if (on) S.tl.show(); else S.tl.hide();
      watch.setAttribute('aria-pressed', String(on)); watch.replaceChildren(icon(on ? 'close' : 'play', 16), on ? 'Close the replay' : 'Watch 24 months');
    });
    S.pick = el('select', { class: 'nw-pick', 'aria-label': 'Zoom to a state' }, el('option', { value: '', text: 'All states' }), D.active(doc).map((s) => el('option', { value: s.id, text: s.name })));
    S.pick.addEventListener('change', () => select(S.pick.value || null));
    const keys = el('ul', { class: 'nw-keys', 'aria-label': 'States on the map: choose one to zoom to it' }, D.stack(doc).series.filter((x) => x.id !== 'other').map((x) => {
      const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', x.color);
      const b = el('button', { type: 'button', class: 'nw-chip', 'aria-pressed': 'false', onclick: () => select(sel === x.id ? null : x.id) }, sw, x.name);
      S.chips.set(x.id, b); return el('li', {}, b);
    }).concat([(() => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', D.OTHER_COLOR); return el('li', { class: 'nw-other' }, sw, el('span', { text: 'every other state' })); })()]));
    S.panel = el('div', { class: 'nat-panel-slot' });
    const card = el('section', { class: 'card nw-explore reveal is-in', id: 'explore', 'aria-labelledby': 'explore-h' });
    const head = hdr('The map', 'pin', 'Every new well, where it sits', 'Each dot is a well whose first fracturing job was in the last 24 months, in every state that reports to the registry.', el('div', { class: 'card-tools' }, S.pick, watch));
    head.querySelector('h2').id = 'explore-h';
    put(card, head, el('div', { class: 'nw-grid' }, el('div', { class: 'nw-mapcol' }, stage, S.tl.bar, keys), S.panel));
    return card;
  }

  /* ---------- the ranking ---------- */
  function ranking(dt) {
    const { doc, producing } = dt; const list = D.active(doc); const top = Math.max(1, ...list.map((s) => s.p12));
    const rows = el('ul', { class: 'nat-rows' }, list.map((s) => {
      const bar = el('i', { class: 'nat-rb' }); bar.style.setProperty('--p', String(s.p12 / top)); bar.style.setProperty('--c', D.colorOf(s.id));
      const c = D.shownChange(s);
      const b = el('button', { type: 'button', class: 'nat-row', 'aria-current': 'false', 'aria-label': s.name + ', ' + fmt.format(s.p12) + ' new wells in the last 12 months. Zoom the map to it.' },
        el('span', { class: 'nat-rn' }, el('span', { class: 'nat-rc', text: s.id }), s.name), el('span', { class: 'nat-rt' }, bar), el('span', { class: 'nat-rv', text: fmt.format(s.p12) }),
        el('span', { class: 'nat-rd' }, c != null ? delta(c) : el('span', { class: 'nd', text: 'n/a' })), el('span', { class: 'nat-rw', text: fmtDate(s.latest).replace(/, \d{4}$/, ''), title: 'the newest job in the registry' }));
      b.addEventListener('click', () => { select(s.id); $('#explore').scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' }); });
      S.rows.set(s.id, b);
      return el('li', {}, b);
    }));
    const none = D.quiet(doc, producing);
    const note = none.length ? 'Producing states with no new well in the registry in the last 12 months: ' + D.listAnd(none.map((x) => x.name + (x.latest ? ' (last job ' + monthLabel(x.latest.slice(0, 7)) + ')' : ''))) + '. The registry lists only wells that were fractured; their permits are on the National page, and they are not counted as zero.' : '';
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('State by state', 'trend', 'Who is drilling', 'New wells in the last 12 settled months, with the change on the 12 before. Click a state to zoom the map to it.'),
      el('div', { class: 'nat-rank' }, rows), note ? el('p', { class: 'fine', text: note }) : null);
  }

  /* ---------- the months, stacked by state; the newest months are drawn lighter: still filling in ---------- */
  function months(dt) {
    const { doc } = dt; const st = D.stack(doc);
    const W = 720; const H = 260; const L = 42; const R = 6; const T = 12; const B = 24;
    const n = st.months.length; const slot = (W - L - R) / n; const bw = Math.max(3, slot * 0.74);
    const { top, ticks } = D.niceTop(Math.max(...st.totals, 1));
    const y = (v) => T + (H - T - B) * (1 - v / top);
    const g = svg('svg', { class: 'nat-chart', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img',
      'aria-label': 'New wells by month, ' + monthLabel(st.months[0]) + ' to ' + monthLabel(st.months[n - 1]) + ', stacked by state; the months after ' + monthLabel(st.months[st.settledAt]) + ' are still filling in; the table below has the numbers' });
    ticks.forEach((t) => g.append(svg('line', { class: t === 0 ? 'base' : 'grid', x1: L, x2: W - R, y1: y(t), y2: y(t) }), svg('text', { class: 'ax', x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: stat(t) })));
    if (st.settledAt < n - 1) {
      const x0 = L + slot * (st.settledAt + 1);
      g.append(svg('rect', { class: 'nw-late', x: x0.toFixed(1), y: T, width: (W - R - x0).toFixed(1), height: H - T - B }), svg('text', { class: 'ax nw-late-t', x: (x0 + 6).toFixed(1), y: T + 12, text: 'still filling in' }));
    }
    st.months.forEach((ym, i) => {
      const x = L + slot * i + (slot - bw) / 2; let acc = 0; const late = i > st.settledAt;
      st.series.forEach((s) => {
        const v = s.values[i]; if (!v) return;
        const seg = svg('rect', { class: 'nat-bar-seg' + (late ? ' is-late' : ''), x: x.toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1), rx: 1.5 });
        seg.style.setProperty('--c', s.color); g.append(seg); acc += v;
      });
      if (ym.slice(5) === '01' || ym.slice(5) === '07') g.append(svg('text', { class: 'ax', x: x + bw / 2, y: H - 6, 'text-anchor': 'middle', text: monthLabel(ym).replace(/(\w+) (\d{4})/, (a, mo, yr) => mo + ' ’' + yr.slice(2)) }));
      const hit = svg('rect', { class: 'nat-hit', x: (L + slot * i).toFixed(1), y: T, width: slot.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: monthLabel(ym) }), ...st.series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name)), tipRow(fmt.format(st.totals[i]), 'in all'), late ? tipRow('Still filling in', 'disclosures arrive late') : null], e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      g.append(hit);
    });
    const key = el('ul', { class: 'nat-keys nat-chart-keys', 'aria-label': 'States in the chart' }, st.series.map((s) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', s.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: s.name + (s.count ? ' (' + s.count + ')' : '') })); }));
    const table = el('details', { class: 'nat-details' }, el('summary', { text: 'Show the numbers as a table' }),
      el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'Monthly new wells by state' }, el('table', { class: 'grid' },
        el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: 'Month' }), st.series.map((s) => el('th', { scope: 'col', class: 'num', text: s.name })), el('th', { scope: 'col', class: 'num', text: 'All' }))),
        el('tbody', {}, st.months.map((ym, i) => el('tr', {}, el('th', { scope: 'row', text: monthLabel(ym) + (i > st.settledAt ? ' (filling in)' : '') }), st.series.map((s) => el('td', { class: 'num', text: fmt.format(s.values[i]) })), el('td', { class: 'num', text: fmt.format(st.totals[i]) }))).reverse()))));
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('Month by month', 'chart', 'The last three years, stacked by state', 'Wells by the day of their first job. A well is disclosed weeks to months afterwards, so the newest months are lighter and will rise.'),
      key, g, el('p', { class: 'fine', text: 'The 12-month figures above use months to ' + monthLabel(doc.settled.slice(0, 7)) + ' only: a month is settled once 120 days have passed since the newest job in the registry.' }), table);
  }

  /* ---------- who and where, for the whole country ---------- */
  function leaders(dt) {
    const { P, range } = dt;
    const co = D.leaders(P, range[0], range[1], { by: 'c', limit: 10 }); const op = D.leaders(P, range[0], range[1], { by: 'o', limit: 10 });
    const bars = (rows, unit, showState) => {
      const top = rows.length ? rows[0].n : 1;
      return el('ul', { class: 'bars' }, rows.map((r) => {
        const bar = el('span', { class: 'bar' }); bar.style.setProperty('--p', String(r.n / top));
        const label = r.label + (showState ? ', ' + r.state : '');
        return el('li', {}, el('div', { class: 'bar-row' }, el('span', { class: 'bar-label', text: label, title: label }), el('span', { class: 'bar-track' }, bar, el('span', { class: 'bar-value', text: fmt.format(r.n), title: r.n + ' ' + unit }))));
      }));
    };
    const named = op.total ? Math.round((1 - op.unnamed / op.total) * 100) : 0;
    return el('div', { class: 'split reveal is-in' },
      el('section', { class: 'card', 'aria-labelledby': 'nw-where-h' }, el('p', { class: 'eyebrow' }, icon('pin', 15), 'Where'), el('h2', { id: 'nw-where-h', text: 'Busiest counties' }),
        el('p', { class: 'sub', text: 'Top 10 counties in the country by new wells, ' + monthLabel(dt.win.months[0]) + ' to ' + monthLabel(dt.win.months[11]) + '.' }), bars(co.rows, 'wells', true)),
      el('section', { class: 'card', 'aria-labelledby': 'nw-who-h' }, el('p', { class: 'eyebrow' }, icon('rig', 15), 'Who is drilling'), el('h2', { id: 'nw-who-h', text: 'Top operators' }),
        el('p', { class: 'sub', text: 'Top 10 by new wells in the same 12 months. Only corporations, LLCs and partnerships are named: ' + named + '% of the wells.' }), bars(op.rows, 'wells', false)));
  }

  /* ---------- when each source was current ---------- */
  function freshness(dt) {
    const { doc, nat } = dt;
    const items = [
      { icon: 'pin', label: 'New wells with a GPS point (FracFocus)', value: 'First jobs to ' + fmtDate(doc.asOf) + ', settled to ' + fmtDate(doc.settled), cadence: 'daily at the source; read here weekly' },
    ];
    if (nat) {
      const newest = nat.states.reduce((m, s) => (s.asOf > m ? s.asOf : m), '');
      items.push({ icon: 'calendar', label: 'Permits (each state agency)', value: nat.states.length + ' agencies read, the newest record ' + fmtDate(newest), cadence: 'weekly here' });
    }
    renderFreshness($('#fresh-list'), items);
  }

  async function draw(mySeq) {
    let dt;
    try { dt = await data(); } catch (e) {
      $('#kpis').replaceChildren(el('p', { class: 'empty', text: 'Could not load the new-wells data. Reload the page to try again.' }));
      return;
    }
    if (mySeq !== seq) return;
    const host = $('#hero');
    hero(dt);
    S.hero = createUSMap({ canvas: $('#hero-canvas'), host, outlines: dt.outlines, P: dt.P, doc: dt.doc, interactive: false, box: heroBox(host) });
    host.classList.add('has-map');
    const slot = $('#nw-slot');
    slot.replaceChildren(explorer(dt), ranking(dt), months(dt), leaders(dt));
    freshness(dt);
    started = true;
    select(sel, { fromHash: true });
    if (/[?&]debug\b/.test(location.search)) window.__nw = { map: S.map, hero: S.hero, P: dt.P, doc: dt.doc, D };
  }

  return {
    // the address names a state (#overview?s=TX): the explorer zooms to it. Drawn on the first visit only; later visits just move the map.
    async show(params) {
      const want = ((params && params.get('s')) || '').toUpperCase() || null;
      if (!started && !seq) { seq++; sel = want; await draw(seq); return; }
      if (started) select(want, { fromHash: true });
      else sel = want;
    },
    get selected() { return sel; },
    pause() { if (S.tl && S.tl.open) S.tl.pause(); },
  };
}
