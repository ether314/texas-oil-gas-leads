// Overview: hero KPI strip, hot counties, top operators, top producers, segments, data freshness.
import { $, el, fmt, compactFmt, stat, pct, share, fmtDate, monthLabel, countUp, sum, toObjects } from './util.js';
import { barList, delta, spark } from './charts.js';
import { hideTip, showTip, tipRow } from './tip.js';
import { icon } from './icons.js';

export const opsLink = (name) => '#operators?' + new URLSearchParams({ q: name, band: 'all' });
const hide = (node) => { const c = node.closest('[data-card]'); (c || node).hidden = true; };

export function fillMeta(m) {
  const values = {
    built: fmtDate(m.built), p5: fmtDate(m.sources.p5), permits: fmtDate(m.sources.permits), latest_permit: fmtDate(m.sources.latest_permit),
    comptroller: fmtDate(m.sources.comptroller), registered: fmt.format(m.operators.registered), opsShown: fmt.format(m.operators.shown),
  };
  document.querySelectorAll('[data-fill]').forEach((n) => { n.textContent = values[n.dataset.fill] || ''; });
}

/* hero KPI strip: each chip opens the records behind its number */
export function renderKpis(m, sp) {
  const o = m.operators; const c = m.companies;
  const chips = [];
  if (sp) {
    const n = sp.permits.length;
    const last = sum(sp.permits, n - 12, n); const prior = sum(sp.permits, n - 24, n - 12);
    chips.push({
      label: 'New-drill permits, last 12 months', value: last, hero: true, href: '#map',
      note: [delta(prior ? last / prior - 1 : null), ' vs the 12 months before'],
      sub: monthLabel(sp.months[n - 12]) + ' to ' + monthLabel(sp.months[n - 1]),
    });
  }
  chips.push(
    { label: 'Operators drilling now', value: (o.bands.A || 0) + (o.bands.B || 0), note: 'band A or B: new-well permits in the last 12 months', href: '#operators?band=ab' },
    { label: 'Companies in the pool', value: c.shown, note: pct(c.texas, c.shown) + ' with Texas addresses', href: '#companies?seg=all' },
    { label: 'New entities', value: c.newEntities, note: 'chartered in the last 24 months', href: '#companies?isNew=1' },
  );
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

/* hot counties and top operators */
export function renderHot(cp, G, win) {
  const ul = $('#hot-bars');
  if (!cp || !G) { hide(ul); return; }
  const rows = Object.entries(cp.counties).map(([f, v]) => ({ f, v, c: G.byFips.get(f) })).filter((r) => r.c)
    .sort((a, b) => b.v.p12 - a.v.p12).slice(0, 10);
  barList(ul, rows.map((r) => ({
    label: r.c.n, value: r.v.p12, href: '#map?county=' + r.f, aria: r.c.n + ' County: ' + fmt.format(r.v.p12) + ' new-drill permits. Open on the map.',
    r,
  })), {
    tipFor: (it) => [tipRow(fmt.format(it.value), 'new-drill permits, ' + it.label + ' County'),
      tipRow(fmt.format(it.r.v.p12prev), 'in the prior 12 months'), tipRow('Click to open the map', '')],
  });
  $('#hot-sub').textContent = 'Top 10 counties by new-drill permits, ' + win + '. Click a bar to open it on the map.';
}
export function renderTopOps(ops) {
  const ul = $('#top-ops');
  if (!ops) { hide(ul); return; }
  const rows = toObjects(ops).sort((a, b) => b.new12 - a.new12).slice(0, 10);
  barList(ul, rows.map((r) => ({
    label: r.name, value: r.new12, href: opsLink(r.name), aria: r.name + ': ' + fmt.format(r.new12) + ' new-well permits. Open in Operators.', r,
  })), {
    tipFor: (it) => [tipRow(fmt.format(it.value), 'new-well permits, ' + it.label), tipRow(it.r.city ? it.r.city + ', ' + it.r.state : '', 'Band ' + it.r.band), tipRow('Click to open the record', '')],
  });
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
