// The Daily report's numbers: what the chosen day's wells look like on the facts every state's FracFocus disclosures carry for every well (where: a GPS point and a county; how deep;
// how much water; whose land; who drilled), each set against the twelve months the day sits in. The counting is `newwells-data.js` `profile` (pure, tested under Node); this draws it.
// Nothing here is a figure only some states have. A fact a well does not report is counted over the wells that do, and says how many; an operator is named only when it may be.
import { el, fmt, monthLabel } from './util.js';
import * as D from './newwells-data.js';

const MIN_TYPICAL = 30; // a state with fewer wells than this in the twelve months has no "typical" to set a day against
const cache = new WeakMap(); // P -> Map(key -> the twelve months' profile): it is the same for every day of a month, so it is counted once
function typicalOf(P, doc, iso, state) {
  const rg = D.typicalRange(P, doc, iso); if (!rg) return null;
  let m = cache.get(P); if (!m) { m = new Map(); cache.set(P, m); }
  const key = rg.d0 + ':' + rg.d1 + ':' + (state || '');
  if (!m.has(key)) m.set(key, D.profile(P, rg.d0, rg.d1, { state }));
  const profile = m.get(key);
  return profile.n >= MIN_TYPICAL ? { ...rg, profile } : null;
}

const plural = (n, one, many) => fmt.format(n) + ' ' + (n === 1 ? one : many);
const tile = (cls, title, ...kids) => el('section', { class: 'dd-stat ' + cls, 'aria-label': title }, el('h3', { text: title }), ...kids);
const big = (value, unit) => el('div', { class: 'nat-big' }, el('strong', { text: value }), unit ? el('span', { text: unit }) : null);
const fine = (text) => el('p', { class: 'fine', text });
const whereOf = (w) => (w && w.county ? w.county + ', ' + w.state : w ? w.state : '');
const oneDec = (v) => v.toFixed(1);

// a ranked list of bars: rows of { label, n, color? }, longest first; the bar is the share of the longest
function rankBars(rows, label) {
  const top = Math.max(1, ...rows.map((r) => r.n));
  return el('ul', { class: 'dd-bars', 'aria-label': label }, rows.map((r) => {
    const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(r.n / top)); if (r.color) bar.style.setProperty('--c', r.color);
    return el('li', {}, el('span', { class: 'nat-ln', text: r.label }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: r.text || fmt.format(r.n) }));
  }));
}
// two bars: this day against the typical one, on one scale
function against(label, dayV, typV, show) {
  return rankBars([{ label: 'This day', n: dayV, text: show(dayV) }, { label: 'Typical', n: typV, text: show(typV), color: 'var(--n-other)' }], label);
}

export function renderStats({ P, doc, day, sel, late }) {
  const iso = D.dayIso(D.dayMs(P, day)); const p = D.profile(P, day, day, { state: sel, hot: true }); const n = p.n;
  const stateName = sel ? (D.byId(doc, sel) || {}).name : null;
  if (!n) return { sub: '', nodes: [el('p', { class: 'nd', text: 'No well had its first job this day' + (stateName ? ' in ' + stateName : '') + (late ? ' yet' : '') + ', so there is nothing to describe. It is shown as none, not as a figure the registry lacks.' })] };
  const t = typicalOf(P, doc, iso, sel); const tp = t && t.profile;
  const window = t ? monthLabel(t.from.slice(0, 7)) + ' to ' + monthLabel(t.to.slice(0, 7)) : '';
  const sub = 'The facts every state’s disclosures carry for every well: where, how deep, how much water, whose land and who drilled' + (t ? ', set against the typical well of ' + window + (t.clipped ? ' (the months the page has loaded)' : '') + '.' : '.')
    + (late ? ' This day is still being disclosed: these are the wells so far.' : '') + (n < 5 ? ' With ' + plural(n, 'well', 'wells') + ' this is a sample, not a trend.' : '');
  const nodes = [];

  // where: counties and the busiest ones
  const topC = p.topCounties.map((c) => ({ label: sel ? c.label : c.label + ', ' + c.state, n: c.n }));
  nodes.push(tile('dd-where', 'Where',
    big(plural(p.counties, 'county', 'counties'), sel ? 'in ' + stateName : 'in ' + plural(p.states, 'state', 'states')),
    topC.length ? rankBars(topC, 'Counties with the most wells') : fine('No well names a county.')));

  // pads and the busiest spot, from the GPS points
  const per = n / p.pads; const typPer = tp ? tp.n / tp.pads : null; const hot = p.hot;
  nodes.push(tile('dd-pads', 'Pads and spots',
    big(oneDec(per), 'wells a pad'),
    fine(plural(n, 'well', 'wells') + ' on ' + plural(p.pads, 'pad', 'pads') + '. Wells fractured the same day within ' + D.PAD_M + ' m of each other count as one pad.'),
    typPer ? against('Wells a pad: this day and a typical one', per, typPer, oneDec) : null,
    hot ? fine('Busiest spot: ' + plural(hot.n, 'well', 'wells') + ' of the day’s ' + fmt.format(hot.of) + ' lie within ' + D.HOT_MILES + ' miles of each other' + (hot.county ? ', around ' + hot.county + ' County, ' + hot.state : '') + '.') : null));

  // depth: the median, the deepest and the day's wells by band against the typical shares
  const d = p.depth;
  const shares = D.DEPTH_BANDS.map((_, k) => (d.n ? d.bands[k] / d.n : 0)); const typShares = D.DEPTH_BANDS.map((_, k) => (tp && tp.depth.n ? tp.depth.bands[k] / tp.depth.n : null));
  const scale = Math.max(0.01, ...shares, ...typShares.filter((v) => v != null)); // the tallest column fills its track, the rest are in proportion
  const bandNodes = D.DEPTH_BANDS.map(([, , name], k) => {
    const share = shares[k]; const typShare = typShares[k];
    const bar = el('i', { class: 'dd-hbar' }); bar.style.setProperty('--p', String(share / scale));
    const col = el('li', { class: 'dd-hcol', title: name + ' ft: ' + plural(d.bands[k], 'well', 'wells') }, el('span', { class: 'dd-hv', text: fmt.format(d.bands[k]) }), el('span', { class: 'dd-htrack' }, bar, typShare == null ? null : el('b', { class: 'dd-htyp' })), el('span', { class: 'dd-hl', text: ['<6k', '6–8k', '8–10k', '10–12k', '12k+'][k] }));
    if (typShare != null) col.querySelector('.dd-htyp').style.setProperty('--t', String(typShare / scale));
    return col;
  });
  nodes.push(tile('dd-depth', 'How deep',
    d.n ? big(fmt.format(d.median) + ' ft', 'median depth') : big('Not reported'),
    d.n ? fine('True vertical depth' + (d.n < n ? ', of the ' + fmt.format(d.n) + ' wells that report one' : '') + (tp && tp.depth.median ? '. A typical well: ' + fmt.format(tp.depth.median) + ' ft' : '') + (d.max ? '. Deepest: ' + fmt.format(d.max.ft) + ' ft in ' + whereOf(d.max) : '') + '.') : fine('None of the day’s wells reports a depth. It is not counted as zero.'),
    d.n ? el('div', { class: 'dd-hist', role: 'img', 'aria-label': 'Wells by depth in feet: ' + D.DEPTH_BANDS.map(([, , name], k) => name + ' ' + d.bands[k]).join(', ') + (tp ? '. A mark in each column shows the typical share.' : '') }, el('ul', { 'aria-hidden': 'true' }, bandNodes)) : null,
    d.n && tp ? fine('The mark in each column is the typical share of wells in that band.') : null));

  // water: the day's total, in swimming pools, and the median well against the typical one
  const w = p.water;
  nodes.push(tile('dd-water', 'How much water',
    w.n ? big(fmt.format(Math.round(w.total)), 'million gallons') : big('Not reported'),
    w.n ? fine('About ' + fmt.format(Math.round(w.pools)) + ' Olympic swimming pools' + (w.n < n ? ', counting the ' + fmt.format(w.n) + ' wells that report water' : '') + (w.max ? '. Most: ' + oneDec(w.max.mgal) + ' million gallons in ' + whereOf(w.max) : '') + '.') : fine('None of the day’s wells reports water. It is not counted as zero.'),
    w.n && tp && tp.water.median ? against('Median well: this day and a typical one, million gallons', w.median, tp.water.median, oneDec) : null));

  // land: the share on federal or tribal land, split in four, against the typical share
  const fed = p.land.federalOrTribal; const typShare = tp ? tp.land.federalOrTribal / tp.n : null;
  const LAND = [['Private or state', 'var(--n-other)'], ['Federal', 'var(--s1)'], ['Tribal', 'var(--s2)'], ['Federal and tribal', 'var(--s7)']];
  const mix = el('div', { class: 'nat-mix', role: 'img', 'aria-label': 'Wells by land: ' + LAND.map(([name], k) => name + ' ' + p.land.counts[k]).join(', ') },
    LAND.map(([, c], k) => { if (!p.land.counts[k]) return null; const s = el('i', { class: 'nat-seg' }); s.style.setProperty('--p', String(p.land.counts[k])); s.style.setProperty('--c', c); return s; }));
  nodes.push(tile('dd-land', 'Whose land',
    big(Math.round((fed / n) * 100) + '%', 'on federal or tribal land'),
    fine(plural(fed, 'well', 'wells') + ' of ' + fmt.format(n) + (typShare != null ? '. A typical day: ' + Math.round(typShare * 100) + '%' : '') + '.'),
    mix,
    el('ul', { class: 'nat-mixkeys' }, LAND.map(([name, c], k) => { if (!p.land.counts[k]) return null; const s = el('i', { class: 'nat-sw' }); s.style.setProperty('--c', c); return el('li', {}, s, name + ' ' + fmt.format(p.land.counts[k])); }))));

  // who: the operators that may be named
  const o = p.operators;
  nodes.push(tile('dd-who', 'Who drilled',
    big(plural(o.named, 'operator', 'operators'), 'named'),
    o.top.length ? rankBars(o.top.map((r) => ({ label: r.label, n: r.n })), 'Operators with the most wells') : fine('No operator may be named.'),
    o.unnamed ? fine(plural(o.unnamed, 'well', 'wells') + (o.unnamed === 1 ? ' has' : ' have') + ' an operator that is not named: a person, or none given.') : null));

  return { sub, nodes };
}
