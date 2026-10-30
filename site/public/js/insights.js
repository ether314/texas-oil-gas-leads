// Insights: a few plain-English reads computed from the files already loaded. Nothing here is asserted without a number behind it,
// and each number links to where it lives (the map, a table, or the chart).
import { el, fmt, halves, signed, monthLabel, lastIdx, toObjects } from './util.js';
import { icon } from './icons.js';
import { opsLink } from './overview.js';

const a = (text, href) => el('a', { href, text });
const btn = (text, fn) => el('button', { type: 'button', class: 'link', onclick: fn, text });
const ymOf = (t) => { const d = new Date(t); return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'); };

export function renderInsights(card, { cp, G, B, ops, extras, meta, prod, R, selectGroup }) {
  const items = [];
  const push = (ic, color, ...parts) => items.push({ ic, color, parts });

  // 1. counties growing fastest (complete months, a base big enough to mean something)
  if (cp && G) {
    const rows = Object.entries(cp.counties).filter(([f]) => G.byFips.has(f)).map(([f, c]) => ({ f, h: halves(c.m) }))
      .filter((r) => r.h.b >= 40 && r.h.f !== Infinity && r.h.f > 0).sort((x, y) => y.h.f - x.h.f).slice(0, 3);
    if (rows.length === 3) {
      const link = (r) => [a(G.byFips.get(r.f).n, '#map?county=' + r.f), ' (', a(signed(r.h.f), '#map?metric=chg&county=' + r.f), ')'];
      push('trend', 'var(--s2)', 'Permits are growing fastest in ', ...link(rows[0]), ', ', ...link(rows[1]), ' and ', ...link(rows[2]),
        ': the last 12 full months against the 12 before, among counties with at least 40 permits in the earlier period.');
    }
  }
  // 2. the Permian's share of permits (and of oil, when production is loaded)
  if (cp && B && B.byId.has('permian')) {
    const pb = B.byId.get('permian');
    const all = Object.values(cp.counties).reduce((t, c) => t + c.p12, 0);
    const mine = pb.fips.reduce((t, f) => t + (cp.counties[f] ? cp.counties[f].p12 : 0), 0);
    if (all > 0 && mine > 0) {
      let oil = null;
      if (prod) {
        const tot = Object.values(prod.counties).reduce((t, c) => t + c.o12, 0);
        const pm = pb.fips.reduce((t, f) => t + (prod.counties[f] ? prod.counties[f].o12 : 0), 0);
        if (tot > 0) oil = Math.round((pm / tot) * 100);
      }
      push('layers', 'var(--s2)', a('Permian Basin counties', '#map?basin=permian'), ' filed ', a(fmt.format(mine), '#map?basin=permian'), ' of the ', fmt.format(all),
        ' county-assigned new-drill permits in the last 12 months (', a(Math.round((mine / all) * 100) + '%', '#map?basin=permian'), ')',
        oil != null ? ' and account for ' + oil + '% of the oil reported in the 12 months to ' + monthLabel(prod.months[prod.months.length - 1]) + '.' : '.');
    }
  }
  // 3. operators stepping up the most
  if (ops && extras) {
    const names = new Map(toObjects(ops).map((r) => [r.num, r.name]));
    const rows = toObjects(extras).map((r) => ({ r, h: halves(r.m24), name: names.get(r.num) })).filter((x) => x.name && x.h.a >= 20 && x.h.a > x.h.b)
      .sort((p, q) => (q.h.a - q.h.b) - (p.h.a - p.h.b)).slice(0, 3);
    if (rows.length === 3) {
      const parts = [];
      rows.forEach((x, i) => { parts.push(i ? (i === 2 ? ' and ' : ', ') : '', a(x.name, opsLink(x.name)), ' (+' + (x.h.a - x.h.b) + ' permits, ' + x.h.b + ' to ' + x.h.a + ')'); });
      push('rig', 'var(--s3)', 'Operators ramping up the most: ', ...parts, '. Permits in the last 12 full months against the 12 before.');
    }
  }
  // 4. new entities
  if (meta && meta.companies) {
    const c = meta.companies;
    push('building', 'var(--s7)', a(fmt.format(c.newEntities), '#companies?isNew=1'), ' oil and gas entities in the company pool were chartered with the Texas Secretary of State in the last 24 months, ',
      Math.round((c.newEntities / c.shown) * 100) + '% of the pool. Open the list to see who they are.');
  }
  // 5. the price move, and where EIA sees it going
  if (R && R.wti) {
    const i = lastIdx(R.wti.v); const j = i - 12;
    if (i >= 12 && R.wti.v[j]) {
      const f = R.wti.v[i] / R.wti.v[j] - 1; const fc = R.fcWti; const fm = R.fcMeta;
      push('chart', 'var(--s1)', 'WTI averaged ', btn('$' + R.wti.v[i].toFixed(2), () => selectGroup('prices')), ' in ' + monthLabel(ymOf(R.wti.t[i])) + ', '
        + (Math.abs(f) < 0.005 ? 'level with' : f > 0 ? 'up ' + Math.round(f * 100) + '% from' : 'down ' + Math.round(-f * 100) + '% from') + ' a year earlier'
        + (fc && fm ? '; the EIA outlook issued in ' + monthLabel(fm.issued) + ' puts it at $' + fc.v[fc.v.length - 1].toFixed(0) + ' by ' + monthLabel(fm.end) + '. That is a forecast, not data.' : '.'));
    }
  }
  const list = card.querySelector('#ins-list');
  if (!items.length) { card.hidden = true; return; }
  list.replaceChildren(...items.slice(0, 5).map((it) => {
    const ic = el('span', { class: 'insight-ic' }, icon(it.ic, 19)); ic.style.setProperty('--c', it.color);
    return el('li', { class: 'insight' }, ic, el('p', {}, ...it.parts));
  }));
  card.hidden = false;
}
