// The cards under the Overview's map. Every one carries both layers, each marked the way the map marks it: a hollow ring (and an outlined bar, a line) is a state agency's count of oil permits,
// a filled dot (and a filled bar) is a fractured well from FracFocus's registry. The two are shown side by side and never added. Data code: combined-data.js (tested under Node).
import { el, svg, fmt, stat, monthLabel, fmtDate, chartWidth } from './util.js';
import { icon } from './icons.js';
import { segmented } from './ui.js';
import { delta } from './charts.js';
import { showTip, hideTip, tipRow } from './tip.js';
import * as N from './national-data.js';
import * as D from './newwells-data.js';
import * as C from './combined-data.js';
import { GRADES } from './fields-data.js';

// Element.append writes the word "null" for a null child, so nothing is appended without dropping the empty ones first
export const put = (node, ...kids) => node.append(...kids.filter((k) => k != null && k !== false));
export const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
// the two marks: a ring for what an agency counts (dashed for wells spudded, dotted for another count), a dot for a fractured well
export const ringKey = (measure = 'permits') => el('i', { class: 'dd-ringkey' + (measure === 'spuds' ? ' is-dash' : measure === 'permits' ? '' : ' is-dot'), 'aria-hidden': 'true' });
export const dotKey = () => el('i', { class: 'dd-dotkey', 'aria-hidden': 'true' });
const cellNum = (v) => (v == null ? '–' : fmt.format(v));
const short = (id) => (id === 'FO' ? 'Gulf' : id === BL ? 'BLM' : id);
const BL = C.BLM;
const unit = (n, word) => (n === 1 ? word.replace(/s$/, '') : word);

/* ---------- a ranked list of counties or operators (the state panel's and the leaders' shape) ---------- */
export function listBlock(rows, what) {
  const top = rows[0].n;
  return el('ul', { class: 'ov-list' }, rows.map((r) => {
    const bar = el('i', { class: 'nat-lb' + (what === 'permits' ? ' is-ring' : '') }); bar.style.setProperty('--p', String(r.n / top));
    const label = r.label + (r.state && r.showState ? ', ' + r.state : '');
    return el('li', {}, el('span', { class: 'nat-ln', text: label, title: r.label }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: fmt.format(r.n), title: r.n + (what === 'permits' ? ' permits or spuds' : ' fractured wells') }));
  }));
}

/* ---------- the ranking: every state, its oil permits and its fractured wells in one row ---------- */
export function rankingCard({ nat, doc, select, rows: rowMap, scrollTo, getSel }) {
  let by = 'permits';
  const body = el('div', { class: 'ov-rank' });
  const seg = segmented({ label: 'Rank the states by', tabs: false, prefix: 'ovr', value: by, options: [{ id: 'permits', label: 'Oil permits' }, { id: 'wells', label: 'Fracked wells' }], onChange: (id) => { by = id; draw(); } });
  function cells(j, topP, topW) {
    // the agency's cell
    const p = j.p ? C.permitFigure(j.p) : null; const w = C.wellFigure(j.w);
    const pc = el('span', { class: 'ov-cell ov-p' }, el('span', { class: 'ov-lab' }, ringKey(p ? p.measure : 'permits'), 'Oil permits'));
    if (!p) put(pc, el('span', { class: 'ov-none', text: j.g ? 'Not read yet' : '–', title: j.g ? 'No agency file is read for this state yet' : '' }));
    else if (p.none) put(pc, el('span', { class: 'ov-none', text: 'None recorded', title: 'The source dates no record in the last 24 months, which is not the same as none happening' }));
    else {
      const bar = el('i', { class: 'nat-rb is-ring' + (p.measure === 'spuds' ? ' is-dash' : p.measure === 'permits' ? '' : ' is-dot') }); bar.style.setProperty('--p', String(p.n / topP));
      put(pc, el('span', { class: 'nat-rt' }, bar), el('span', { class: 'ov-vu' }, el('span', { class: 'nat-rv', text: fmt.format(p.n) }), el('span', { class: 'ov-u', text: unit(p.n, p.word) })), el('span', { class: 'nat-rd' }, p.change != null ? delta(p.change) : el('span', { class: 'nd', text: 'n/a' })));
    }
    const wc = el('span', { class: 'ov-cell ov-w' }, el('span', { class: 'ov-lab' }, dotKey(), 'Fracked wells'));
    if (!w) put(wc, el('span', { class: 'ov-none', text: j.w ? 'None in 12 months' : 'Not in the registry', title: 'FracFocus lists only wells that were hydraulically fractured: no fractured well here in the last 12 settled months is not the same as no drilling' }));
    else {
      const bar = el('i', { class: 'nat-rb' }); bar.style.setProperty('--p', String(w.n / topW)); bar.style.setProperty('--c', D.colorOf(j.id));
      put(wc, el('span', { class: 'nat-rt' }, bar), el('span', { class: 'ov-vu' }, el('span', { class: 'nat-rv', text: fmt.format(w.n) }), el('span', { class: 'ov-u', text: unit(w.n, 'wells') })), el('span', { class: 'nat-rd' }, w.change != null ? delta(w.change) : el('span', { class: 'nd', text: 'n/a' })));
    }
    return [pc, wc, p, w];
  }
  function row(j, topP, topW) {
    const [pc, wc, p, w] = cells(j, topP, topW);
    const said = (p ? (p.none ? 'no oil permits recorded in 24 months' : fmt.format(p.n) + ' ' + (p.measure === 'permits' ? 'oil permits approved' : p.word)) : j.g ? 'oil permits not read yet' : 'no oil permit data')
      + '; ' + (w ? fmt.format(w.n) + ' fractured wells' : 'no fractured wells in the registry');
    const b = el('button', { type: 'button', class: 'nat-row ov-row', 'aria-current': 'false', 'aria-label': j.name + ': ' + said + ', last 12 months. Show it on the map.' },
      el('span', { class: 'nat-rn' }, el('span', { class: 'nat-rc', text: short(j.id) }), j.name), pc, wc);
    b.addEventListener('click', () => { select(j.id); scrollTo(); });
    rowMap.set(j.id, b);
    return el('li', {}, b);
  }
  function draw() {
    const { rows, none, fed } = C.rankRows(nat, doc, by);
    rowMap.clear();
    const topP = Math.max(1, ...rows.map((j) => (j.p ? j.p.p12 : 0))); const topW = Math.max(1, ...rows.map((j) => (j.w ? j.w.p12 : 0)));
    const head = el('div', { class: 'ov-head', 'aria-hidden': 'true' }, el('span'), el('span', {}, ringKey(), 'Oil permits, last 12 months'), el('span', {}, dotKey(), 'Fractured wells, last 12 months'));
    const list = el('ul', { class: 'nat-rows' }, rows.map((j) => row(j, topP, topW)));
    const parts = [head, list];
    if (fed) {
      const fp = C.permitFigure(fed.p);
      const b = el('button', { type: 'button', class: 'nat-row ov-row is-fed', 'aria-current': 'false', 'aria-label': 'Federal onshore (BLM): ' + fmt.format(fp.n) + ' permits approved on federal land in the last 12 months. It overlaps the states, so it is shown on its own and never added. Show it.' },
        el('span', { class: 'nat-rn' }, el('span', { class: 'nat-rc', text: 'BLM' }), 'Federal onshore'), cells(fed, fp.n, topW)[0], el('span', { class: 'ov-cell ov-w' }, el('span', { class: 'ov-none', text: 'overlaps the states: never added' })));
      b.addEventListener('click', () => { select(BL); scrollTo(); });
      rowMap.set(BL, b);
      parts.push(el('ul', { class: 'nat-rows ov-fed' }, el('li', {}, b)));
    }
    parts.push(el('p', { class: 'fine', text: 'Each state’s last 12 complete months against the 12 before (a change is shown only from a base of 20 or more). An outlined bar is a state agency’s count of oil permits (dashed: wells spudded, for the agencies that publish no approval dates; dotted: counted another way), a filled bar is fractured wells from the registry: different things, never added. The registry lists only wells that were fractured, so a state with permits and no wells there is not a state with no drilling.'
      + (none.length ? ' ' + N.upFirst(N.listAnd(none.map((j) => j.name))) + ' ' + (none.length > 1 ? 'have' : 'has') + ' no permit list this site can read and no fractured well in the registry (see who is covered, below).' : '') }));
    body.replaceChildren(...parts);
    rowMap.forEach((n, id) => n.setAttribute('aria-current', String(id === getSel())));
  }
  draw();
  const card = el('section', { class: 'card nat-card reveal is-in', id: 'ranking', 'aria-labelledby': 'ranking-h' }, hdr('State by state', 'trend', 'Who is drilling', 'Every state with either source, its oil permits and its fractured wells side by side. Click a state to zoom the map to it.', el('div', { class: 'card-tools' }, seg.el)), body);
  card.querySelector('h2').id = 'ranking-h';
  return { el: card, setBy(id) { if (id !== by) { by = id; seg.set(id, false); draw(); } }, get by() { return by; }, redraw: draw };
}

/* ---------- the months: fractured wells as bars stacked by state, the agencies' oil permits as lines ---------- */
export function monthsCard({ nat, doc }) {
  const data = C.monthly(nat, doc);
  const slot = el('div', { class: 'nat-months' });
  let drawnAt = 0;
  const path = (vals, x, y) => { let d = ''; let on = false; vals.forEach((v, i) => { if (v == null) { on = false; return; } d += (on ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); on = true; }); return d; };
  function chart() {
    const { months, wells, permits, spuds } = data; const n = months.length;
    const W = chartWidth(slot, 1200); const H = W < 500 ? 236 : 288; const L = 42; const R = 8; const T = 14; const B = 24;
    const sl = (W - L - R) / n; const bw = Math.max(1.6, sl * 0.74);
    const top0 = Math.max(...wells.totals, ...permits.values.filter((v) => v != null), ...spuds.values.filter((v) => v != null), 1);
    const { top, ticks } = D.niceTop(top0);
    const y = (v) => T + (H - T - B) * (1 - v / top); const xc = (i) => L + sl * i + sl / 2;
    const g = svg('svg', { class: 'nat-chart ov-chart', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img',
      'aria-label': 'Oil permits approved, wells spudded and fractured wells by month, ' + monthLabel(months[0]) + ' to ' + monthLabel(months[n - 1]) + ': fractured wells as bars stacked by state, the permits and spuds as lines; the months after ' + monthLabel(months[wells.settledAt]) + ' are still filling in; the table below has the numbers' });
    ticks.forEach((t) => g.append(svg('line', { class: t === 0 ? 'base' : 'grid', x1: L, x2: W - R, y1: y(t), y2: y(t) }), svg('text', { class: 'ax', x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: stat(t) })));
    if (wells.settledAt < n - 1) {
      const x0 = L + sl * (wells.settledAt + 1);
      g.append(svg('rect', { class: 'nw-late', x: x0.toFixed(1), y: T, width: (W - R - x0).toFixed(1), height: H - T - B }), svg('text', { class: 'ax nw-late-t', x: (x0 - 6).toFixed(1), y: T + 12, 'text-anchor': 'end', text: 'wells still filling in' }));
    }
    months.forEach((ym, i) => {
      const x = L + sl * i + (sl - bw) / 2; let acc = 0; const late = i > wells.settledAt;
      wells.series.forEach((s) => {
        const v = s.values[i]; if (!v) return;
        const seg = svg('rect', { class: 'nat-bar-seg' + (late ? ' is-late' : ''), x: x.toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1), rx: 1.2 });
        seg.style.setProperty('--c', s.color); g.append(seg); acc += v;
      });
      if (ym.slice(5) === '01' && (n <= 60 || (+ym.slice(0, 4)) % 2 === 1)) g.append(svg('text', { class: 'ax', x: xc(i), y: H - 6, 'text-anchor': 'middle', text: monthLabel(ym).replace(/(\w+) (\d{4})/, (a, mo, yr) => mo + ' ’' + yr.slice(2)) }));
    });
    // the agencies' counts: a line each (permits approved solid, wells spudded dashed), a ring at the newest month, over a surface-colored halo so it reads over the bars
    [[spuds, 'ov-spuds'], [permits, 'ov-permits']].forEach(([ln, cls]) => {
      const d = path(ln.values, xc, y); if (!d) return;
      g.append(svg('path', { class: 'ov-halo', d }), svg('path', { class: 'ov-line ' + cls, d }));
      const last = ln.values.map((v, i) => (v == null ? -1 : i)).reduce((a, b) => Math.max(a, b), -1);
      if (last >= 0) g.append(svg('circle', { class: 'ov-end ' + cls, cx: xc(last).toFixed(1), cy: y(ln.values[last]).toFixed(1), r: 4 }));
    });
    months.forEach((ym, i) => {
      const late = i > wells.settledAt;
      const hit = svg('rect', { class: 'nat-hit', x: (L + sl * i).toFixed(1), y: T, width: sl.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: monthLabel(ym) }),
        permits.values[i] != null ? tipRow(fmt.format(permits.values[i]), 'oil permits approved') : null, spuds.values[i] != null ? tipRow(fmt.format(spuds.values[i]), 'oil wells spudded') : null,
        ...wells.series.filter((s) => s.values[i]).slice().reverse().map((s) => tipRow(fmt.format(s.values[i]), s.name + ', fractured')), tipRow(fmt.format(wells.totals[i]), 'fractured wells in all'),
        late ? tipRow('Wells still filling in', 'disclosures arrive late') : null].filter(Boolean), e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      g.append(hit);
    });
    const lineKey = (cls, text) => el('li', { class: 'nat-key' }, svg('svg', { class: 'ov-linekey', viewBox: '0 0 26 10', width: 26, height: 10, 'aria-hidden': 'true' }, svg('path', { class: 'ov-line ' + cls, d: 'M1 5H25' }), svg('circle', { class: 'ov-end ' + cls, cx: 21, cy: 5, r: 3.4 })), el('span', { text }));
    const keys = el('ul', { class: 'nat-keys nat-chart-keys ov-keys', 'aria-label': 'Lines and bars in the chart' },
      lineKey('ov-permits', 'Oil permits approved (' + C.totals(nat, doc).permitStates + ' agencies)'), lineKey('ov-spuds', 'Oil wells spudded (' + C.totals(nat, doc).spudStates + ' agencies)'),
      el('li', { class: 'nat-key ov-keylab' }, dotKey(), el('span', { text: 'Fractured wells, by state:' })),
      wells.series.map((s) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', s.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: s.name + (s.count ? ' (' + s.count + ')' : '') })); }));
    return [keys, g];
  }
  function notes() {
    const { permits, spuds, wells } = data;
    const lag = [...new Set([...permits.lagging])];
    return el('p', { class: 'fine', text: 'Each line ends where its agencies’ files do (' + (permits.end ? 'permits approved: ' + monthLabel(permits.end) : '') + (spuds.end ? '; wells spudded: ' + monthLabel(spuds.end) + ', reported about two months late' : '') + '), so a late agency does not read as a fall'
      + (lag.length ? ': ' + N.listAnd(lag) + (lag.length > 1 ? ' end' : ' ends') + ' earlier and are left out of the last months, not counted as zero' : '')
      + '. Fractured wells are dated by the first job and disclosed weeks to months afterwards, so the newest months (lighter) will rise. The lines are the agencies’ counts and the bars the registry’s wells: a permit is the right to drill and a fracturing job comes after, so they are never added and need not agree.' });
  }
  function table() {
    const { months, wells, permits, spuds } = data;
    return el('details', { class: 'nat-details' }, el('summary', { text: 'Show the numbers as a table' }),
      el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'Monthly oil permits, wells spudded and fractured wells' }, el('table', { class: 'grid' },
        el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: 'Month' }), el('th', { scope: 'col', class: 'num', text: 'Oil permits approved' }), el('th', { scope: 'col', class: 'num', text: 'Oil wells spudded' }),
          wells.series.map((s) => el('th', { scope: 'col', class: 'num', text: s.name + ' (fractured wells)' })), el('th', { scope: 'col', class: 'num', text: 'All fractured wells' }))),
        el('tbody', {}, months.map((ym, i) => el('tr', {}, el('th', { scope: 'row', text: monthLabel(ym) + (i > wells.settledAt ? ' (wells filling in)' : '') }), el('td', { class: 'num', text: cellNum(permits.values[i]) }), el('td', { class: 'num', text: cellNum(spuds.values[i]) }),
          wells.series.map((s) => el('td', { class: 'num', text: fmt.format(s.values[i]) })), el('td', { class: 'num', text: fmt.format(wells.totals[i]) }))).reverse()))));
  }
  const card = el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'months-h' }, hdr('Month by month', 'chart', 'Permits and fractured wells, since ' + data.months[0].slice(0, 4),
    'The lines are what the state agencies approved (or, where they publish no approval dates, wells spudded); the bars are the wells that were then fractured, stacked by state. Where the bars follow the lines, drilling follows approvals; where they do not, a state’s wells are mostly not fractured.'), slot);
  card.querySelector('h2').id = 'months-h';
  const redraw = () => { slot.replaceChildren(...chart()); drawnAt = chartWidth(slot, 1200); };
  redraw(); put(card, notes(), table());
  // the chart is drawn at its container's width: a window that changes size draws it again (not on every pixel), and so does a card that was hidden when it was built
  let timer = null;
  window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => { if (slot.isConnected && slot.clientWidth && Math.abs(chartWidth(slot, 1200) - drawnAt) > 24) redraw(); }, 150); });
  return { el: card, redraw };
}

/* ---------- who and where: the busiest counties and the top operators, for the country or the state chosen on the map ---------- */
export function leadersCards({ nat, doc, scope }) {
  const mk = (id, ic, eyebrow, title) => {
    const sub = el('p', { class: 'sub' }); const body = el('div', { class: 'ov-pair' });
    const card = el('section', { class: 'card', 'aria-labelledby': id }, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { id, text: title }), sub, body);
    return { card, sub, body };
  };
  const where = mk('ov-where-h', 'pin', 'Where', 'Busiest counties'); const who = mk('ov-who-h', 'rig', 'Who is drilling', 'Top operators');
  const layer = (what, title, rows, empty) => el('div', { class: 'nat-list ov-layer' }, el('h4', {}, what === 'permits' ? ringKey() : dotKey(), title), rows.length ? listBlock(rows, what) : el('p', { class: 'fine', text: empty }));
  function update(sel) {
    const { P, range } = scope(); const p = sel ? N.byId(nat, sel) : null; const g = sel ? N.gapOf(nat, sel) : null;
    const name = sel ? (p ? p.name : g ? g.name : N.nameOf(nat, sel)) : null;
    const pEmpty = !sel ? 'No agency lists these.' : g ? 'No agency file is read for ' + name + ' yet.' : 'The agency’s file lists none.';
    const wEmpty = 'Not in the registry in the last 12 months: it lists only wells that were fractured.';
    const cP = sel ? C.stateLeaders(p, 'counties', 8).map((r) => ({ ...r, showState: false })) : C.permitLeaders(nat, 'counties', 8).rows;
    const oP = sel ? C.stateLeaders(p, 'operators', 8) : C.permitLeaders(nat, 'operators', 8).rows;
    const cW = D.leaders(P, range[0], range[1], { state: sel, by: 'c', limit: 8 }); const oW = D.leaders(P, range[0], range[1], { state: sel, by: 'o', limit: 8 });
    cW.rows.forEach((r) => { r.showState = !sel; });
    const tag = p ? ' (' + (p.unit || N.measureOf(p.measure).one) + ')' : '';
    where.sub.textContent = sel ? name + ', the last 12 months. The agency’s own top ' + (p && p.place ? p.place : 'counties') + ' and the registry’s.' : 'The top 8 across the country in the last 12 months: where the agencies approved the most oil permits, and where the most wells were fractured.';
    where.body.replaceChildren(layer('permits', 'Oil permits' + (sel ? tag : ' (agencies that count permits approved)'), cP, pEmpty), layer('wells', 'Fractured wells (registry)', cW.rows, wEmpty));
    const named = oW.total ? Math.round((1 - oW.unnamed / oW.total) * 100) : null;
    who.sub.textContent = (sel ? name + ': the' : 'The') + ' operators with the most oil permits in the agencies’ own lists and the most fractured wells in the registry. Only corporations, LLCs and partnerships are named' + (named != null ? ': ' + named + '% of the registry’s wells' : '') + (p && p.namedShare != null ? '; ' + Math.round(p.namedShare * 100) + '% of the agency’s' : '') + '.';
    who.body.replaceChildren(layer('permits', 'Oil permits' + (sel ? tag : ' (each state’s top 15, added up by name)'), oP, pEmpty), layer('wells', 'Fractured wells (registry)', oW.rows, wEmpty));
  }
  return { el: el('div', { class: 'split reveal is-in' }, where.card, who.card), update };
}

/* ---------- who is covered ---------- */
export function coverageCard({ nat, doc, select, scrollTo }) {
  const { rows, none, fed } = C.rankRows(nat, doc, 'permits');
  const list = rows.concat(none, fed ? [fed] : []);
  const status = (j) => (j.p ? N.measureOf(j.p.measure).name : 'Not read yet');
  const table = el('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Which agencies and which registry wells the page covers' },
    el('table', { class: 'grid nat-cov' }, el('thead', {}, el('tr', {}, ['State', 'Oil permits count', 'Agency', 'Data through', 'Updates', 'Fractured wells, 12 months'].map((h) => el('th', { scope: 'col', text: h })))),
      el('tbody', {}, list.map((j) => {
        const w = C.wellFigure(j.w); const gap = !j.p;
        return el('tr', { class: gap ? 'is-gap' : null },
          el('th', { scope: 'row' }, el('button', { type: 'button', class: 'link', text: j.name, onclick: () => { select(j.id); scrollTo(); } })),
          el('td', { 'data-label': 'Oil permits count' }, status(j)),
          el('td', { 'data-label': 'Agency' }, j.p ? j.p.agency : (j.g && j.g.agency) || el('span', { class: 'nd', text: 'not researched' }), gap && j.g && j.g.why ? el('small', { class: 'nat-why', text: j.g.why }) : null,
            gap && j.g && j.g.grade && GRADES[j.g.grade] ? el('small', { class: 'nat-why', text: 'Its published data, as researched (grade ' + j.g.grade + '): ' + GRADES[j.g.grade].replace(/^./, (c) => c.toLowerCase()) + '.' }) : null),
          el('td', { 'data-label': 'Data through', text: j.p && j.p.through ? monthLabel(j.p.through.slice(0, 7)) : '—' }),
          el('td', { 'data-label': 'Updates', text: j.p && j.p.cadence ? N.upFirst(j.p.cadence) : '—' }),
          el('td', { 'data-label': 'Fractured wells, 12 months' }, w ? fmt.format(w.n) : el('span', { class: 'nd', text: j.id === BL ? 'overlaps the states' : j.w ? 'none in 12 months' : 'not in the registry' })));
      }))));
  return el('section', { class: 'card nat-card reveal is-in', 'aria-labelledby': 'cover-h' }, (() => { const h = hdr('Coverage', 'building', 'Who is covered, and who is not yet', 'Every state with oil production is listed with the agency behind its permit count and the wells the registry holds for it. A state with no data is counted as not available, never as zero.'); h.querySelector('h2').id = 'cover-h'; return h; })(), table);
}

/* ---------- when each source was current ---------- */
export function freshnessItems(nat, doc) {
  const r = C.reach(nat, doc);
  return [
    { icon: 'pin', label: 'Fractured wells with a GPS point (FracFocus)', value: 'First jobs to ' + fmtDate(doc.asOf) + ', settled to ' + fmtDate(doc.settled), cadence: 'daily at the source; read here daily' },
    { icon: 'calendar', label: 'Oil permits (each state agency)', value: nat.states.length + ' agencies read; most run to ' + (r.permitsMedian ? monthLabel(r.permitsMedian) : 'their own latest month') + ', each state’s own date is in the table above', cadence: 'weekly here' },
  ];
}
