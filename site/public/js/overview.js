// Overview: hero KPI strip, hot counties, top operators, top producers, segments, data freshness.
import { $, el, fmt, compactFmt, stat, pct, share, fmtDate, monthLabel, countUp, toObjects } from './util.js';
import { barList, delta, spark } from './charts.js';
import { hideTip, showTip, tipRow } from './tip.js';
import { icon } from './icons.js';
import { permitTotals, ownTotals, countyLabel, topBy, newToDrilling } from './overview-data.js';
import { stateOf, countyState, measureOf, sameMeasure, measurePhrase } from './states.js';

export const opsLink = (name) => '#operators?' + new URLSearchParams({ q: name, band: 'all' });
const hide = (node) => { const c = node.closest('[data-card]'); (c || node).hidden = true; };

export function fillMeta(m, extra = {}) {
  const values = {
    built: fmtDate(m.built), p5: fmtDate(m.sources.p5), permits: fmtDate(m.sources.permits), latest_permit: fmtDate(m.sources.latest_permit),
    comptroller: fmtDate(m.sources.comptroller), registered: fmt.format(m.operators.registered), opsShown: fmt.format(m.operators.shown), ...extra,
  };
  document.querySelectorAll('[data-fill]').forEach((n) => { n.textContent = values[n.dataset.fill] || ''; });
}

/* hero KPI strip: each chip opens the records behind its number. `ctx`: states shown, meta, sp (the permit series of those states), rows (the
   operators of the other states, as objects), wells (each other state's active wells, or null). A figure a state cannot give says so: the
   company pool is the Texas Comptroller's, so it is Texas only, and a single state without Texas shows what its own files hold instead. */
export function renderKpis({ states, meta: m, sp, rows = [], wells = {} }) {
  const tx = states.includes('TX'); const multi = states.length > 1;
  const o = m.operators; const c = m.companies;
  const chips = [];
  if (sp) {
    const t = permitTotals(sp);
    const spud = sp.summed.length === 1 && measureOf(sp.summed[0]).id === 'spuds';
    // a state that counts something else (New Mexico's spuds) is not in the total: its own 12 months are said beside it
    const apart = sp.ids.filter((id) => !sp.summed.includes(id)).map((id) => { const o = ownTotals(sp, id); return fmt.format(o.last) + ' ' + measureOf(id).noun + ' in ' + stateOf(id).name + ' (to ' + monthLabel(o.to) + ')'; });
    chips.push({
      label: (spud ? 'Wells spudded' : 'New-drill permits') + ', last 12 months', value: t.last, hero: true, href: '#map',
      note: [delta(t.prior ? t.last / t.prior - 1 : null), ' vs the 12 months before'],
      sub: monthLabel(t.from) + ' to ' + monthLabel(t.to) + (apart.length ? ' · and ' + apart.join(', ') : ''),
    });
  }
  const mine = rows.filter((r) => states.includes(r.st) && r.st !== 'TX');
  const drilling = (tx ? (o.bands.A || 0) + (o.bands.B || 0) : 0) + mine.filter((r) => r.band === 'A' || r.band === 'B').length;
  chips.push({ label: 'Operators drilling now', value: drilling, note: (multi ? 'band A or B in every state shown' : 'band A or B') + ': ' + (states.every((id) => measureOf(id).id === 'spuds') ? 'wells spudded' : 'new-well permits') + ' in the last 12 months', href: '#operators?band=ab' });
  if (tx) {
    chips.push(
      { label: 'Companies in the pool', value: c.shown, note: pct(c.texas, c.shown) + ' with Texas addresses' + (multi ? ' · Texas only' : ''), href: '#companies?seg=all' },
      { label: 'New entities', value: c.newEntities, note: 'chartered in the last 24 months' + (multi ? ' · Texas only' : ''), href: '#companies?isNew=1' },
    );
  } else {
    chips.push({ label: 'New to drilling', value: newToDrilling(mine), note: 'operators whose first ' + (states.every((id) => measureOf(id).id === 'spuds') ? 'well was spudded' : 'drilling permit came') + ' in the last 24 months', href: '#operators?band=all' });
    const w = states.map((id) => wells[id]).filter(Boolean);
    if (w.length) chips.push({ label: 'Active wells', value: w.reduce((t, x) => t + x.n, 0), note: 'in the Commission’s well inventory, ' + fmtDate(w[0].day), href: '#daily' });
  }
  const small = chips.length - (sp ? 1 : 0);
  $('#kpis').replaceChildren(...chips.map((k, i) => {
    const num = el('strong', { class: 'kpi-num', 'aria-hidden': 'true', title: fmt.format(k.value) });
    const a = el('a', { class: 'kpi-chip' + (k.hero ? ' hero-fig' : '') + (small % 2 && i === chips.length - 1 ? ' span2' : ''), href: k.href },
      el('span', { class: 'kpi-chip-label', text: k.label }), num, el('span', { class: 'sr-only', text: fmt.format(k.value) }),
      el('span', { class: 'kpi-chip-note' }, k.note), k.sub ? el('span', { class: 'kpi-chip-sub', text: k.sub }) : null,
      el('span', { class: 'sr-only', text: 'View records' }));
    countUp(num, k.value, (v) => (k.hero ? fmt.format(v) : stat(v)));
    return a;
  }));
}

/* hot counties and top operators. One state: the top 10. Several: the top few of each under its own heading, on one scale, so no state hides
   the others behind its size. */
const PER = (states) => (states.length === 1 ? 10 : states.length === 2 ? 5 : 4); // 10 for one state, then 5 or 4 each, so the card stays about as long
function grouped(rows, states, key, build) {
  if (states.length < 2) return topBy(rows, key, PER(states)).map(build);
  // a heading per state, naming what it counts when the states do not count the same thing
  return states.flatMap((id) => [{ heading: stateOf(id).name + (sameMeasure(states) ? '' : ' · ' + measureOf(id).noun), st: id }, ...topBy(rows.filter((r) => r.st === id), key, PER(states)).map(build)]);
}
export function renderHot(cp, G, win, states = ['TX']) {
  const ul = $('#hot-bars');
  if (!cp || !G) { hide(ul); return; }
  const multi = states.length > 1;
  const rows = Object.entries(cp.counties).map(([f, v]) => ({ f, v, c: G.byFips.get(f), p12: v.p12, _i: 0, st: countyState(f) })).filter((r) => r.c && r.p12 > 0);
  const items = grouped(rows, states, 'p12', (r) => ({
    label: r.c.n, value: r.v.p12, href: '#map?county=' + r.f, aria: r.c.n + ' County' + (multi ? ', ' + r.st : '') + ': ' + fmt.format(r.v.p12) + ' new-drill permits. Open on the map.', r, st: r.st,
  }));
  barList(ul, items, {
    max: Math.max(1, ...rows.map((r) => r.p12)),
    tipFor: (it) => [tipRow(fmt.format(it.value), measureOf(it.st).noun + ', ' + countyLabel(it.label, it.st, multi) + ' County'),
      tipRow(fmt.format(it.r.v.p12prev), 'in the prior 12 months'), tipRow('Click to open the map', '')],
  });
  $('#hot-sub').textContent = (multi ? 'Top ' + PER(states) + ' counties of each state' : 'Top 10 counties') + ' by ' + (multi ? measurePhrase(states) : measureOf(states[0]).noun) + ', ' + win + '. Click a bar to open it on the map.';
}
// rows: the operators of the states shown, as objects (overview-data.operatorRows)
export function renderTopOps(rows, states = ['TX']) {
  const ul = $('#top-ops');
  if (!rows || !rows.length) { hide(ul); return; }
  const multi = states.length > 1;
  const items = grouped(rows, states, 'new12', (r) => ({
    label: r.name, value: r.new12, href: opsLink(r.name), aria: r.name + (multi ? ' (' + r.st + ')' : '') + ': ' + fmt.format(r.new12) + ' new-well permits. Open in Operators.', r, st: r.st,
  }));
  barList(ul, items, {
    max: Math.max(1, ...rows.map((r) => r.new12)),
    tipFor: (it) => [tipRow(fmt.format(it.value), (measureOf(it.st).id === 'spuds' ? 'wells spudded, ' : 'new-well permits, ') + it.label), tipRow(it.r.city ? it.r.city + ', ' + it.r.state : '', 'Band ' + it.r.band + (multi ? ' · ' + stateOf(it.st).name : '')), tipRow('Click to open the record', '')],
  });
  $('#top-sub').textContent = (multi ? 'Top ' + PER(states) + ' of each state' : 'Top 10') + ' by ' + (multi ? measurePhrase(states).replace('new-drill permits', 'new-well permits') : states.every((id) => measureOf(id).id === 'spuds') ? 'wells spudded' : 'new-well permits')
    + ' in the last 12 months. Click a bar to open the record.';
}

/* top producers: operators by crude oil and condensate over the newest 12 complete months of RRC reports. The file names every producing
   corporation, LLC or limited partnership whatever its P-5 status; those that are not current registrants (status other than A) get a small
   tag, and a row only links where there is something to open (a row in the Operators table, or permit points on the map). */
const P5_NOTE = { I: 'inactive', D: 'delinquent', S: 'marked "see remarks"' };
export function renderProducers(card, opProd, ops, hasPts = new Set()) {
  if (!opProd || !opProd.rows || !opProd.rows.length) { card.hidden = true; return false; }
  const listed = new Map(ops ? toObjects(ops).map((r) => [r.num, r]) : []);
  const rows = toObjects(opProd).map((r) => ({ ...r, who: r.name || (listed.get(r.num) && listed.get(r.num).name) || '' })).filter((r) => r.who && r.o12 > 0)
    .sort((a, b) => b.o12 - a.o12).slice(0, 10);
  if (!rows.length) { card.hidden = true; return false; }
  const m = opProd.months; const last = monthLabel(m[m.length - 1]); const win = monthLabel(m[m.length - 12]) + ' to ' + last;
  const share = opProd.nameableShare ? ' Named operators (corporations, LLCs and limited partnerships) hold ' + Math.round(opProd.nameableShare.oil * 100) + '% of the oil.' : '';
  $('#prod-sub', card).textContent = 'Top 10 operators by crude oil and condensate in the 12 months to ' + last + ' (' + win + '), the newest complete months of Railroad Commission reports; newer months are still being filled in.'
    + share + ' The chip compares the same 12 months with the 12 before. A big step is often an acquisition, because production follows the operator of record.';
  const heads = $('.prod-head', card).children;
  heads[2].textContent = 'Oil and condensate, 12 months to ' + last; heads[3].textContent = '24 months'; heads[4].textContent = 'vs 12 before';
  const max = rows[0].o12;
  const list = $('#prod-list', card);
  list.replaceChildren(...rows.map((r, i) => {
    const bar = el('span', { class: 'bar' }); bar.style.setProperty('--p', String(r.o12 / max));
    const f = r.o12p > 0 ? r.o12 / r.o12p - 1 : Infinity;
    const chip = f === Infinity
      ? el('span', { class: 'delta up' }, el('span', { class: 'arrow', 'aria-hidden': 'true', text: '▲' }), el('span', { text: 'new' })) : delta(f);
    const status = r.status || 'A';
    const href = listed.has(r.num) ? opsLink(r.who) : hasPts.has(r.num) ? '#map?op=' + r.num : null;
    const tag = status !== 'A' ? el('span', { class: 'badge', title: 'P-5 status ' + status + (P5_NOTE[status] ? ' (' + P5_NOTE[status] + ')' : ' (a status the Railroad Commission’s P-5 manual does not define)')
      + ': not a current registration, so this operator is not on the Operators page.', text: 'P-5 status ' + status }) : null;
    const kids = [el('span', { class: 'prod-rank', text: String(i + 1) }),
      el('span', { class: 'prod-who' }, el('span', { class: 'prod-name', text: r.who, title: r.who }), tag),
      el('span', { class: 'prod-bar' }, bar, el('span', { class: 'bar-value', text: compactFmt.format(r.o12) + ' bbl' })),
      el('span', { class: 'prod-spark' }, spark(r.mo, { w: 92, h: 28, color: 'var(--s3)', base: 'min', label: 'Monthly oil, last ' + r.mo.length + ' months' })),
      el('span', { class: 'prod-chip', title: '12 months to ' + last + ' against the 12 before' }, chip)];
    const row = href ? el('a', { class: 'prod-row', href, 'aria-label': (i + 1) + '. ' + r.who + ': ' + fmt.format(r.o12) + ' barrels of oil, ' + win + '. ' + (listed.has(r.num) ? 'Open in Operators.' : 'Show on the map.') }, kids)
      : el('div', { class: 'prod-row static' }, kids);
    const tip = (e) => {
      const rect = row.getBoundingClientRect();
      showTip([tipRow(fmt.format(r.o12), 'barrels of oil and condensate, ' + win), tipRow(fmt.format(r.o12p), 'in the 12 months before'),
        tipRow(fmt.format(Math.round(r.g12 / 1e6)), 'Bcf of gas, ' + fmt.format(r.leases) + ' producing leases'),
        tipRow(href ? (listed.has(r.num) ? 'Click to open the record' : 'Click to show its permits on the map') : 'Not a current P-5 registrant: no record page', '')],
      e.clientX || rect.left + 120, e.clientY || rect.top);
    };
    row.addEventListener('pointermove', tip); row.addEventListener('pointerleave', hideTip); row.addEventListener('focus', tip); row.addEventListener('blur', hideTip);
    return el('li', {}, row);
  }));
  card.hidden = false;
  return true;
}

/* segment bars, with a table twin */
export function renderSegments(m) {
  const data = m.companies.bySegment;
  const total = data.reduce((s, d) => s + d[1], 0);
  const link = (seg) => '#companies?seg=' + encodeURIComponent(seg);
  barList($('#seg-bars'), data.map(([seg, n]) => ({ label: seg, value: n, href: link(seg), aria: seg + ': ' + fmt.format(n) + ' companies. View records.' })), {
    max: data.length ? data[0][1] : 1,
    tipFor: (it) => [tipRow(fmt.format(it.value), it.label + ' · ' + share(it.value, total) + ' of the pool · click to list them')],
  });
  $('#seg-table tbody').replaceChildren(...data.map(([seg, n]) => el('tr', {},
    el('td', {}, el('a', { href: link(seg), text: seg })), el('td', { class: 'num', text: fmt.format(n) }), el('td', { class: 'num', text: share(n, total) }))));
  const toggle = $('#seg-toggle');
  toggle.addEventListener('click', () => {
    const table = toggle.getAttribute('aria-pressed') !== 'true';
    toggle.setAttribute('aria-pressed', String(table)); toggle.textContent = table ? 'Chart view' : 'Table view';
    $('#seg-bars').hidden = table; $('#seg-table-wrap').hidden = !table; hideTip();
  });
}

/* data freshness: every source with its own latest date and, where documented, how often the source publishes */
export function renderFreshness(ul, items) {
  const list = items.filter((x) => x && x.value);
  if (!list.length) { hide(ul); return; }
  ul.replaceChildren(...list.map((x) => el('li', {}, icon(x.icon || 'calendar', 16), el('div', {},
    el('b', { text: x.label }), el('span', { text: x.value }),
    x.cadence ? el('small', { class: 'fresh-cad', text: 'Publishes ' + x.cadence, title: 'The source publishes new data ' + x.cadence + '. This site is rebuilt by hand, so it can lag.' }) : null))));
}
