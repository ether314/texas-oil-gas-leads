// Insights: a few plain-English reads computed from the files already loaded. Nothing here is asserted without a number behind it,
// and each number links to where it lives (the map, a table, or the chart).
import { el, fmt, halves, signed, monthLabel, lastIdx, toObjects, fmtDate } from './util.js';
import { icon } from './icons.js';
import { opsLink } from './overview.js';
import { countyLabel } from './overview-data.js';
import { stateOf, countyState, measureOf, sameMeasure } from './states.js';

const a = (text, href) => el('a', { href, text });
const btn = (text, fn) => el('button', { type: 'button', class: 'link', onclick: fn, text });
const ymOf = (t) => { const d = new Date(t); return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'); };

// states: the ones shown. cp and G cover them (every state but Texas keyed OK:001 ...); cpTx is Texas's own county file, which the Permian
// share needs, rows the other states' operator rows (with their 24 monthly counts) for the operators that are stepping up, and wells each
// other state's active wells ({ OK: { n, day } }).
export function renderInsights(card, { cp, G, B, ops, extras, meta, prod, R, selectGroup, states = ['TX'], cpTx = cp, rows: otherRows = [], wells = {} }) {
  const items = [];
  const push = (ic, color, ...parts) => items.push({ ic, color, parts });
  const tx = states.includes('TX'); const others = states.filter((id) => id !== 'TX'); const multi = states.length > 1;

  // 1. counties growing fastest (complete months, a base big enough to mean something)
  if (cp && G) {
    const rows = Object.entries(cp.counties).filter(([f]) => G.byFips.has(f)).map(([f, c]) => ({ f, h: halves(c.m) }))
      .filter((r) => r.h.b >= 40 && r.h.f !== Infinity && r.h.f > 0).sort((x, y) => y.h.f - x.h.f).slice(0, 3);
    if (rows.length === 3) {
      const link = (r) => { const c = G.byFips.get(r.f); return [a(countyLabel(c.n, countyState(r.f), multi), '#map?county=' + r.f), ' (', a(signed(r.h.f), '#map?metric=chg&county=' + r.f), ')']; };
      push('trend', 'var(--s2)', (!sameMeasure(states) ? 'New wells are' : measureOf(states[0]).id === 'spuds' ? 'Wells spudded are' : 'Permits are') + ' growing fastest in ', ...link(rows[0]), ', ', ...link(rows[1]), ' and ', ...link(rows[2]),
        ': the last 12 full months against the 12 before, among counties with at least 40 ' + (sameMeasure(states) ? measureOf(states[0]).short : 'permits or spuds') + ' in the earlier period.');
    }
  }
  // 2. the Permian's share of permits (and of oil, when production is loaded)
  if (tx && cpTx && B && B.byId.has('permian')) {
    const pb = B.byId.get('permian');
    const all = Object.values(cpTx.counties).reduce((t, c) => t + c.p12, 0);
    const mine = pb.fips.reduce((t, f) => t + (cpTx.counties[f] ? cpTx.counties[f].p12 : 0), 0);
    if (all > 0 && mine > 0) {
      let oil = null;
      if (prod) {
        const tot = Object.values(prod.counties).reduce((t, c) => t + c.o12, 0);
        const pm = pb.fips.reduce((t, f) => t + (prod.counties[f] ? prod.counties[f].o12 : 0), 0);
        if (tot > 0) oil = Math.round((pm / tot) * 100);
      }
      push('layers', 'var(--s2)', a('Permian Basin counties', '#map?basin=permian'), ' filed ', a(fmt.format(mine), '#map?basin=permian'), ' of the ', fmt.format(all),
        ' county-assigned ' + (multi ? 'Texas ' : '') + 'new-drill permits in the last 12 months (', a(Math.round((mine / all) * 100) + '%', '#map?basin=permian'), ')',
        oil != null ? ' and account for ' + oil + '% of the oil reported in the 12 months to ' + monthLabel(prod.months[prod.months.length - 1]) + '.' : '.');
    }
  }
  // 3. operators stepping up the most
  if ((tx && ops && extras) || others.length) {
    const names = new Map(ops ? toObjects(ops).map((r) => [r.num, r.name]) : []);
    const cand = (tx && ops && extras ? toObjects(extras).map((r) => ({ r, h: halves(r.m24), name: names.get(r.num) })) : [])
      .concat(otherRows.filter((r) => states.includes(r.st)).map((r) => ({ r, h: halves(r.m24), name: r.name })));
    const rows = cand.filter((x) => x.name && x.h.a >= 20 && x.h.a > x.h.b)
      .sort((p, q) => (q.h.a - q.h.b) - (p.h.a - p.h.b)).slice(0, 3);
    if (rows.length === 3) {
      const parts = [];
      const unit = (x) => (x.r.st && measureOf(x.r.st).id === 'spuds' ? 'wells spudded' : 'permits');
      rows.forEach((x, i) => { parts.push(i ? (i === 2 ? ' and ' : ', ') : '', a(x.name, opsLink(x.name)), ' (+' + (x.h.a - x.h.b) + ' ' + unit(x) + ', ' + x.h.b + ' to ' + x.h.a + ')'); });
      push('rig', 'var(--s3)', 'Operators ramping up the most: ', ...parts, '. The last 12 full months against the 12 before.');
    }
  }
  // 4. new entities (the Texas Comptroller's pool)
  if (tx && meta && meta.companies) {
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
  // 6a. where a state's drilling is concentrated, when two counties hold most of it
  for (const id of others) {
    const mine = Object.entries(cp ? cp.counties : {}).filter(([f]) => countyState(f) === id).map(([f, c]) => ({ f, p: c.p12 })).sort((x, y) => y.p - x.p);
    const total = mine.reduce((t, x) => t + x.p, 0);
    if (mine.length >= 2 && total >= 100 && (mine[0].p + mine[1].p) / total >= 0.6 && G) {
      const q = stateOf(id); const c0 = G.byFips.get(mine[0].f); const c1 = G.byFips.get(mine[1].f);
      if (c0 && c1) push('layers', 'var(--st-' + id.toLowerCase() + ')', 'In ' + q.name + ', ', a(c0.n, '#map?county=' + mine[0].f), ' and ', a(c1.n, '#map?county=' + mine[1].f), ' hold ',
        a(Math.round(((mine[0].p + mine[1].p) / total) * 100) + '%', '#map?county=' + mine[0].f), ' of the ' + measureOf(id).noun + ' in the last 12 months (' + fmt.format(mine[0].p + mine[1].p) + ' of ' + fmt.format(total) + ').');
    }
  }
  // 6. each other state's crude and well inventory, which are what those states have beside the permits
  for (const id of others) {
    const ser = R && R.crude && R.crude[id]; const q = stateOf(id); const col = 'var(--st-' + id.toLowerCase() + ')';
    if (ser) {
      const i = lastIdx(ser.v); const j = i - 12;
      if (i >= 12 && ser.v[j]) {
        const f = ser.v[i] / ser.v[j] - 1;
        push('drop', col, q.name + ' produced ', btn(fmt.format(Math.round(ser.v[i] / 1e3)) + ' thousand barrels', () => selectGroup('production')), ' of crude oil in ' + monthLabel(ymOf(ser.t[i])) + ', '
          + (Math.abs(f) < 0.005 ? 'level with' : f > 0 ? 'up ' + Math.round(f * 100) + '% from' : 'down ' + Math.round(-f * 100) + '% from') + ' a year earlier (the EIA’s estimate, which it revises).');
      }
    }
    if (wells[id]) push('rig', col, 'The ' + q.agency + '’s well inventory lists ', a(fmt.format(wells[id].n), '#daily?st=' + id.toLowerCase()), ' active wells in ' + q.name + ' on ' + fmtDate(wells[id].day) + '.');
  }
  const list = card.querySelector('#ins-list');
  if (!items.length) { card.hidden = true; return; }
  list.replaceChildren(...items.slice(0, 5).map((it) => {
    const ic = el('span', { class: 'insight-ic' }, icon(it.ic, 19)); ic.style.setProperty('--c', it.color);
    return el('li', { class: 'insight' }, ic, el('p', {}, ...it.parts));
  }));
  card.hidden = false;
}
