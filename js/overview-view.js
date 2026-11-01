// The Overview: oil permits and fractured wells, side by side, for the whole country, on one page. It brings together what were three tabs (the Overview's wells map, the National report's
// state agencies and the Map's permit locations) and uses only what exists for every state:
//   oil permits    national.json: each state agency's own count (permits approved, or wells spudded where an agency publishes no approval dates), 33 jurisdictions
//   fractured wells  data/newwells/: FracFocus's registry, one GPS point for every fractured well in every state that reports, since 2011
// Each visual carries both, marked the same way everywhere: a hollow ring (an outlined bar, a line) is a state agency's oil permits, a filled dot (a filled bar) is a fractured well. The two
// are never added: a permit is the right to drill and a fracturing job comes after. The state-by-state and Texas-only layers of the old Map tab (production, jobs, companies, plants) are not here.
import { $, el, svg, load, loadOpt, fmt, stat, fmtDate, monthLabel, countUp, reduced } from './util.js';
import { icon } from './icons.js';
import { segmented } from './ui.js';
import { delta } from './charts.js';
import { tipRow } from './tip.js';
import { createTimelapse } from './timelapse.js';
import { renderFreshness } from './overview.js';
import * as G from './usgeo.js';
import * as D from './newwells-data.js';
import * as N from './national-data.js';
import * as C from './combined-data.js';
import { createUSMap } from './usmap.js';
import { put, hdr, ringKey, dotKey, rankingCard, monthsCard, leadersCards, coverageCard, freshnessItems } from './overview-cards.js';

const SOURCE = 'https://fracfocus.org/data-download';

export function createOverview(meta) {
  let loaded = null; let started = false; let sel = null; let seq = 0; let wantAll = false;
  let kinds = 'both'; let wantKinds = 'both'; // what the explorer draws: 'both', 'wells' (fractured wells only) or 'permits' (the agencies' rings only)
  const flags = () => ({ wells: kinds !== 'permits', permits: kinds !== 'wells' });
  const S = { map: null, hero: null, tl: null, rows: new Map(), chips: new Map(), panel: null, pick: null, all: false, years: null, status: null, kindsSeg: null, rank: null, leaders: null, watch: null };

  /* ---------- the data: the registry's summary and points, the outlines, and the national file of the agencies' counts ---------- */
  async function data() {
    if (loaded) return loaded;
    const [doc, pts, out, nat] = await Promise.all([load('newwells/summary'), load('newwells/points'), load('us-states'), load('national')]);
    const fields = nat.hasFields ? await loadOpt('permit-fields') : null; // the matrix file is only asked for once it exists
    const P = D.decode(pts); const outlines = G.buildOutlines(out);
    const list = C.jurisdictions(nat, doc);
    loaded = { doc, nat, fields, P, pts, outlines, list, rings: C.rings(nat), win: D.windowOf(doc), range: D.settledRange(P, doc), T: C.totals(nat, doc), reach: C.reach(nat, doc), full: null };
    return loaded;
  }
  // the earlier wells (every well with a point since 2011: about 2 MB), loaded when the explorer is asked for all the years and merged with the last two years' points
  async function loadHistory() {
    if (loaded.full) return loaded.full;
    const P = D.decode(D.mergePoints(loaded.pts, await load('newwells/points-history')));
    loaded.full = { P, range: D.settledRange(P, loaded.doc) };
    return loaded.full;
  }
  // the points and the 12 settled months' days the explorer and its panel work on: the last two years, or all the years once they are loaded
  const scope = (dt) => (S.all && dt.full ? dt.full : dt);
  const known = (dt, id) => !!id && dt.list.some((j) => j.id === id);
  const jur = (dt, id) => dt.list.find((j) => j.id === id) || null;

  /* ---------- the hero: eyebrow, lede, four figures, the note, and the map behind them ---------- */
  function hero(dt) {
    const { doc, T, P, win, range, reach } = dt;
    $('#hero-eyebrow').textContent = 'Oil permits and fractured wells, every state';
    $('#hero-lede').textContent = 'What each state agency approves to drill, and every well that was then fractured, side by side for the whole country: where it is, who is behind it and how big the job was. Public records only, built ' + fmtDate(meta.built) + '.';
    const chips = [
      { label: 'Oil permits approved, last 12 months', value: T.permits, hero: true, go: 'permits', note: [T.permitStates + ' state agencies', T.spuds ? ' · plus ' + fmt.format(T.spuds) + ' wells spudded in ' + T.spudStates + ' more' : ''], sub: 'each agency’s own count · never added to the wells' },
      { label: 'Fractured wells, last 12 months', value: T.wells, go: 'wells', note: [delta(T.wellsChange), ' vs the 12 months before'], sub: monthLabel(win.months[0]) + ' to ' + monthLabel(win.months[11]) + ' · settled months only' },
      { label: 'States with both', value: T.both, go: 'map', note: T.permitsOnly + ' more have oil permits only: the registry lists wells that were fractured' },
      { label: 'Newest fractured well', text: fmtDate(doc.asOf).replace(/, \d{4}$/, ''), go: 'map', note: 'permit files run to ' + (reach.permitsMedian ? monthLabel(reach.permitsMedian) : 'each agency’s own date') + ' for most agencies; the newest wells are still being disclosed' },
    ];
    $('#kpis').replaceChildren(...chips.map((k) => {
      const num = el('strong', { class: 'kpi-num', 'aria-hidden': k.text ? null : 'true', title: k.value != null ? fmt.format(k.value) : null });
      const a = el('a', { class: 'kpi-chip' + (k.hero ? ' hero-fig' : ''), href: '#overview', 'data-go': k.go }, el('span', { class: 'kpi-chip-label', text: k.label }), num,
        k.text ? null : el('span', { class: 'sr-only', text: k.value == null ? 'not available' : fmt.format(k.value) }), el('span', { class: 'kpi-chip-note' }, k.note), k.sub ? el('span', { class: 'kpi-chip-sub', text: k.sub }) : null);
      if (k.text) num.textContent = k.text;
      else if (k.value == null) num.textContent = 'n/a';
      else countUp(num, k.value, (v) => (k.hero ? fmt.format(v) : stat(v)));
      return a;
    }));
    $('#hero-note').textContent = 'Dots are the ' + fmt.format(P.n) + ' fractured wells of the last 24 months, each where it sits (every well in the registry has a usable point); brighter dots are the newest. Each ring is a state agency’s count of its oil permits over the last 12 months, its area the count; the rings are a different thing from the dots and are never added to them. The registry lists wells that were hydraulically fractured, nearly every new oil well; a well that was not fractured, and any disclosed after ' + fmtDate(doc.asOf) + ', is not in it. Figures use settled months only: ' + monthLabel(doc.settled.slice(0, 7)) + ' and before.';
  }
  function heroBox(host) {
    return (w, h) => {
      const kp = host.querySelector('.kpis'); const hi = host.querySelector('.hero-in');
      if (w >= 900) return { x0: Math.max(w * 0.38, hi ? hi.offsetLeft + hi.offsetWidth + 10 : 0), x1: w - 28, y0: 22, y1: kp ? kp.offsetTop - 16 : h - 22 };
      const reserve = (hi && parseFloat(getComputedStyle(hi).paddingBottom)) || 260; const bottom = kp ? kp.offsetTop - 8 : h - 8;
      return { x0: 6, x1: w - 6, y0: Math.max(0, bottom - reserve + 6), y1: bottom };
    };
  }
  const scrollTo = (node) => node && node.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });

  /* ---------- the state panel: the agency's figures and the registry's, one block each, then both as lines ---------- */
  const figure = (mark, label, big, note, change, sub) => el('div', { class: 'ov-fig' }, el('p', { class: 'ov-fig-h' }, mark, label),
    el('div', { class: 'nat-big' }, el('strong', { text: big }), el('span', { text: note }), change || null), sub ? el('p', { class: 'fine', text: sub }) : null);
  const bandBar = (m) => el('div', { class: 'nat-mix', role: 'img', 'aria-label': m.map((b) => b.label + ' ' + Math.round(b.share * 100) + '%').join(', ') }, m.map((b) => { const seg = el('i', { class: 'nat-seg' }); seg.style.setProperty('--p', String(b.share)); seg.style.setProperty('--c', b.color); return seg; }));
  // both counts over the last 36 months in one small chart: the agency's as a ring-ended line, the registry's as a filled line (dashed over the months still filling in)
  function dual(sm, name, color) {
    const W = 300; const H = 64; const n = sm.months.length;
    const vals = [...(sm.permits || []), ...(sm.wells || [])].filter((v) => v != null); const max = Math.max(1, ...vals);
    const x = (i) => 3 + (W - 6) * (n < 2 ? 0.5 : i / (n - 1)); const y = (v) => H - 4 - (H - 10) * (v / max);
    const path = (v, a, b) => { let d = ''; let on = false; for (let i = a; i <= b && i < n; i++) { if (v[i] == null) { on = false; continue; } d += (on ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v[i]).toFixed(1); on = true; } return d; };
    const g = svg('svg', { class: 'ov-dual', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': name + ', by month over the last ' + n + ' months: ' + (sm.permits ? 'oil permits (the ringed line)' : 'no agency count') + (sm.wells ? ' and fractured wells (the filled line, dashed where still filling in)' : ', no fractured wells in the registry') });
    g.style.setProperty('--c', color);
    g.append(svg('line', { class: 'grid', x1: 3, x2: W - 3, y1: H - 3.5, y2: H - 3.5 }));
    if (sm.wells) {
      const s = sm.settledAt < 0 ? n - 1 : sm.settledAt;
      g.append(svg('path', { class: 'ov-w-line', d: path(sm.wells, 0, s) }));
      if (s < n - 1) g.append(svg('path', { class: 'ov-w-line is-late', d: path(sm.wells, s, n - 1) }));
    }
    if (sm.permits) {
      const d = path(sm.permits, 0, n - 1);
      if (d) { g.append(svg('path', { class: 'ov-halo', d }), svg('path', { class: 'ov-p-line', d }));
        let last = -1; sm.permits.forEach((v, i) => { if (v != null) last = i; });
        g.append(svg('circle', { class: 'ov-p-end', cx: x(last).toFixed(1), cy: y(sm.permits[last]).toFixed(1), r: 3.6 })); }
    }
    return g;
  }
  function panel(dt, id) {
    const { doc, nat, T, fields } = dt; const { P, range } = scope(dt);
    const box = el('div', { class: 'nat-panel', 'aria-live': 'polite' });
    const settled = monthLabel(doc.settled.slice(0, 7));
    if (!id) {
      const land = D.landShare(P, range[0], range[1]);
      put(box, el('div', { class: 'nat-ph' }, el('h3', { text: 'All states' })),
        figure(ringKey(), 'Oil permits', fmt.format(T.permits), ' approved by ' + T.permitStates + ' state agencies in their last 12 months', null,
          (T.spuds ? fmt.format(T.spuds) + ' wells spudded in ' + T.spudStates + ' more (they publish no approval dates). ' : '') + (T.blm != null ? fmt.format(T.blm) + ' permits on federal land (the BLM, which overlap the states). ' : '') + 'Each is counted on its own and never added.'),
        figure(dotKey(), 'Fractured wells', fmt.format(T.wells), ' in the 12 months to ' + settled, T.wellsChange != null ? delta(T.wellsChange) : null,
          land.of ? fmt.format(land.n) + ' of the ' + fmt.format(land.of) + ' wells of that year (' + Math.round((land.n / Math.max(1, land.of)) * 100) + '%) are on federal or tribal land.' : null),
        el('p', { class: 'fine', text: 'Click a state on the map, or its name in the key, to zoom in and see both for it: its agency, its counties, its operators and how each count has moved. Hover or tap a dot for the well.' }),
        el('p', { class: 'fine', text: 'A permit is the right to drill and a fracturing job comes after it, so the two counts are different things: they are shown together and never added.' }));
      return box;
    }
    const j = jur(dt, id); const p = j.p; const g = j.g; const w = j.w; const wf = C.wellFigure(w); const pf = C.permitFigure(p);
    put(box, el('div', { class: 'nat-ph' }, el('h3', { text: j.name }), p ? el('span', { class: 'badge', text: N.measureOf(p.measure).name }) : g ? el('span', { class: 'badge', text: 'Permits not read yet' }) : null));
    // the agency
    if (p) {
      put(box, el('p', { class: 'nat-agency', text: p.agency + ' · counted by ' + p.basis }),
        pf.none
          ? figure(ringKey(p.measure), 'Oil permits', 'None recorded', ' in the 24 months to ' + monthLabel(p.through.slice(0, 7)) + ': the source has no ' + N.measureOf(p.measure).one.replace(/^new-drill /, '') + ' dated in them, which is not the same as none happening')
          : figure(ringKey(p.measure), 'Oil permits', fmt.format(pf.n), ' ' + pf.unit + ' in the 12 months to ' + monthLabel(p.through.slice(0, 7)), pf.change != null ? delta(pf.change) : (p.prev12 !== p.p12 ? el('span', { class: 'nat-base', text: '(' + fmt.format(p.prev12) + ' the 12 months before)' }) : null)));
    } else if (g) {
      put(box, g.agency ? el('p', { class: 'nat-agency', text: g.agency }) : null, el('div', { class: 'ov-fig' }, el('p', { class: 'ov-fig-h' }, ringKey(), 'Oil permits'), el('p', { text: g.why || 'Nothing has been built for this agency yet.' }), el('p', { class: 'fine', text: 'It is counted as not available, never as zero.' })));
    }
    // the registry
    const fedLand = id === C.BLM ? D.landShare(P, range[0], range[1]) : null; // the BLM is not a state: the registry's wells on federal or tribal land are the nearest thing it holds
    put(box, fedLand
      ? figure(dotKey(), 'Fractured wells', fmt.format(fedLand.n), ' on federal or tribal land in the 12 months to ' + settled, null, 'Of the ' + fmt.format(fedLand.of) + ' wells of that year. The registry counts wells by state, so they are in the states’ figures; the BLM’s permits above and these wells are different counts and are never added.')
      : wf
      ? figure(dotKey(), 'Fractured wells', fmt.format(wf.n), ' in the 12 months to ' + settled, wf.change != null ? delta(wf.change) : null, 'Newest job ' + fmtDate(wf.latest) + ' · counted by the day of the first job')
      : el('div', { class: 'ov-fig' }, el('p', { class: 'ov-fig-h' }, dotKey(), 'Fractured wells'), el('p', { class: 'nd', text: w ? 'None in the last 12 months' + (w.latest ? ' (the newest job in the registry is ' + monthLabel(w.latest.slice(0, 7)) + ')' : '') + '.' : 'Not in the registry.' }),
        el('p', { class: 'fine', text: 'The registry lists only wells that were hydraulically fractured, so this is not the same as no drilling' + (p ? ': ' + (id === C.BLM ? 'the BLM' : N.inName(id, j.name)) + '’s permits are counted above.' : '.') })));
    // both, over time
    const sm = C.stateMonthly(nat, doc, id, 36);
    if (sm.permits || sm.wells) put(box, el('div', { class: 'ov-dualbox' }, dual(sm, j.name, D.colorOf(id)),
      el('p', { class: 'ov-dualkey fine' }, sm.permits ? el('span', {}, ringKey(p.measure), ' oil permits') : null, sm.wells ? el('span', {}, dotKey(), ' fractured wells') : null, el('span', { text: 'the last ' + sm.months.length + ' months' }))));
    if (p) {
      const m = N.mix(p);
      if (m) put(box, el('div', { class: 'nat-sub' }, el('h4', { text: (N.measureOf(p.measure).family === 'permits' ? 'Kinds of permits' : 'Kinds of wells') + ', last 12 months' }), bandBar(m),
        el('ul', { class: 'nat-mixkeys' }, m.map((b) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', b.color); return el('li', {}, sw, b.label + ' ' + fmt.format(b.n)); }))));
      else put(box, el('p', { class: 'fine', text: 'Kinds of permits (re-entries, reworks, injection wells, amendments) are not split for ' + N.inName(id, p.name) + ' in this report.' }));
      const fl = N.fluidMix(p);
      if (fl) put(box, el('p', { class: 'fine', text: 'Oil or gas, where the agency records the fluid: ' + fl.parts.map((x) => fmt.format(x.n) + ' ' + x.id).join(', ') + (fl.unknown ? ', ' + fmt.format(fl.unknown) + ' not recorded' : '') + '.' }));
      if (p.note) put(box, el('p', { class: 'fine', text: p.note }));
    }
    if (wf) {
      const land = D.landShare(P, range[0], range[1], id);
      put(box, el('p', { class: 'fine', text: [w.tvd ? 'Median depth ' + fmt.format(w.tvd) + ' ft' : null, w.water ? 'median ' + w.water.toFixed(1) + ' million gallons of water' : null, land.of ? Math.round((land.n / land.of) * 100) + '% on federal or tribal land' : null].filter(Boolean).join(' · ') + ' (fractured wells).' }));
    }
    const links = el('p', { class: 'nat-links' });
    const f = fields && fields.states && fields.states[id];
    if (p) { const h = N.sourceHref(p, fields); if (h) links.append(el('a', { class: 'more-link', href: h.href, target: '_blank', rel: 'noopener noreferrer' }, 'Source: ' + p.source.name + (h.viaAgency ? ' (on the agency’s site)' : ''), icon('arrow', 16))); }
    if (f) links.append(el('a', { class: 'more-link', href: '#fields?s=' + id }, 'What its permit captures', icon('arrow', 16)));
    if (wf) links.append(el('a', { class: 'more-link', href: SOURCE, target: '_blank', rel: 'noopener noreferrer' }, 'Source: FracFocus', icon('arrow', 16)));
    put(box, links.childNodes.length ? links : null);
    return box;
  }
  // a state's hover on the map: both counts, each marked
  function stateTip(dt) {
    return (id, zoomed) => {
      const j = jur(dt, id); if (!j) return [];
      const pf = j.p ? C.permitFigure(j.p) : null; const wf = C.wellFigure(j.w);
      return [el('div', { class: 'tip-head', text: j.name }),
        pf ? (pf.none ? tipRow('None recorded', 'oil permits, last 24 months') : tipRow(fmt.format(pf.n), (pf.measure === 'permits' ? 'oil permits approved' : pf.unit) + ', last 12 months')) : tipRow(j.g ? 'Not read yet' : '–', 'oil permits'),
        wf ? tipRow(fmt.format(wf.n), 'fractured wells, last 12 months') : tipRow('None', 'fractured wells in the registry'),
        tipRow(zoomed ? '' : dt.outlines[id] ? 'Click to zoom in' : 'Click for its figures', '')];
    };
  }
  // the address: #overview?s=TX&y=all&k=wells (the state the map is zoomed to, every year since 2011 instead of the last two, and which layer)
  const addr = () => '#overview' + [sel ? 's=' + sel : null, S.all ? 'y=all' : null, kinds !== 'both' ? 'k=' + kinds : null].filter(Boolean).map((x, i) => (i ? '&' : '?') + x).join('');
  // the address says what the page shows: a jurisdiction that does not exist (s=ZZ), a layer that is not one, a lower-case state or the years that did not load are not left in it
  const settle = () => { const a = addr(); if (location.hash !== a) history.replaceState(null, '', a); };
  function select(id, { fromHash = false } = {}) {
    const dt = loaded; if (!dt) return;
    sel = known(dt, id) ? id : null;
    if (S.map) S.map.select(sel && dt.outlines[sel] ? sel : null, true);
    S.panel.replaceChildren(panel(dt, sel));
    S.rows.forEach((n, rid) => n.setAttribute('aria-current', String(rid === sel)));
    S.chips.forEach((n, cid) => n.setAttribute('aria-pressed', String(cid === sel)));
    if (S.pick) S.pick.value = sel || '';
    if (S.leaders) S.leaders.update(sel);
    if (!fromHash) {
      const next = addr();
      if (location.hash !== next) history.replaceState(null, '', next);
    }
  }

  /* ---------- the explorer: the map, its legend, the replay and the panel of the state it is zoomed to ---------- */
  function explorer(dt) {
    const { doc, outlines, nat } = dt; const { P } = scope(dt); const all = S.all; const first = doc.months[0].slice(0, 4);
    const watchLabel = all ? 'Watch ' + D.yearsOf(P) + ' years' : 'Watch 24 months';
    const canvas = el('canvas', { class: 'nw-canvas', role: 'img', 'aria-label': 'Map of the ' + fmt.format(P.n) + (all ? ' fractured wells with a GPS point since ' + first : ' fractured wells of the last 24 months') + ', one dot each, in ' + D.active(doc).length + ' states, and one ring for each of the ' + dt.rings.length + ' state agencies’ oil permits, its area the count. The ranking below lists the states in text; choose a state with the selector to zoom to it.' });
    const stage = el('div', { class: 'nw-stage' }, canvas);
    S.map = createUSMap({ canvas, host: stage, outlines, P, doc, rings: dt.rings, has: (id) => known(dt, id), stateTip: stateTip(dt), interactive: true, onSelect: (id) => select(id) });
    S.map.setKinds(flags());
    S.tl = createTimelapse({ engine: S.map, t0: P.t0, label: all ? 'Watch every fractured well since ' + first : 'Watch the fractured wells', seconds: all ? 28 : 12, thing: { one: 'fractured well', many: 'fractured wells' },
      lead: all ? D.yearsOf(P) + ' years of fractured wells.' : 'Two years of fractured wells.',
      note: (all ? ' Each dot appears on the day of its first job and glows for a month. Watch for the slowdowns of 2015 and 2016 and of 2020.' : ' Each dot appears on the day of its first job and glows for a month.') + ' The rings are the agencies’ counts for their last 12 months and stay as they are. The newest weeks are still being disclosed.' });
    const watch = el('button', { type: 'button', class: 'btn', 'aria-pressed': 'false' }, icon('play', 16), watchLabel);
    S.watch = watch;
    watch.addEventListener('click', () => {
      const on = !S.tl.open; if (on) S.tl.show(); else S.tl.hide();
      watch.setAttribute('aria-pressed', String(on)); watch.replaceChildren(icon(on ? 'close' : 'play', 16), on ? 'Close the replay' : watchLabel);
    });
    watch.disabled = kinds === 'permits'; watch.title = kinds === 'permits' ? 'The replay shows the fractured wells, which are hidden now' : '';
    S.pick = el('select', { class: 'nw-pick', 'aria-label': 'Zoom to a state' }, el('option', { value: '', text: 'All states' }),
      dt.list.filter((j) => j.p || j.g || C.wellFigure(j.w)).slice().sort((a, b) => a.name.localeCompare(b.name)).map((j) => el('option', { value: j.id, text: j.name })));
    S.pick.addEventListener('change', () => select(S.pick.value || null));
    S.years = segmented({ label: 'Years shown on the map', tabs: false, prefix: 'nwy', value: all ? 'all' : 'recent', options: [{ id: 'recent', label: 'Last 2 years' }, { id: 'all', label: 'Since ' + first }], onChange: (id) => switchYears(id === 'all') });
    S.status = el('p', { class: 'fine nw-status', role: 'status' });
    const keys = el('ul', { class: 'nw-keys', 'aria-label': 'States on the map: choose one to zoom to it' }, D.stack(doc).series.filter((x) => x.id !== 'other').map((x) => {
      const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', x.color);
      const b = el('button', { type: 'button', class: 'nw-chip', 'aria-pressed': 'false', onclick: () => select(sel === x.id ? null : x.id) }, sw, x.name);
      S.chips.set(x.id, b); return el('li', {}, b);
    }).concat([(() => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', D.OTHER_COLOR); return el('li', { class: 'nw-other' }, sw, el('span', { text: 'every other state' })); })()]));
    S.panel = el('div', { class: 'nat-panel-slot' });
    const card = el('section', { class: 'card nw-explore reveal is-in', id: 'explore', 'aria-labelledby': 'explore-h' });
    const head = hdr('The map', 'pin', 'Where permits are approved and wells are fractured',
      'Each dot is a fractured well' + (all ? ': every one in the registry with a GPS point, ' + fmt.format(P.n) + ' first jobs from ' + monthLabel(doc.months[0]) + ' to ' + fmtDate(doc.asOf) : ' whose first job was in the last 24 months') + ', in every state that reports to the registry. Each ring is a state agency’s count of oil permits in the last 12 months, its area the count.',
      el('div', { class: 'card-tools' }, S.pick, S.years.el, watch));
    head.querySelector('h2').id = 'explore-h';
    put(card, head, S.status, el('div', { class: 'nw-grid' }, el('div', { class: 'nw-mapcol' }, stage, S.tl.bar, layerLegend(dt), keys), S.panel));
    return card;
  }
  // which is which: a hollow ring is a state agency's oil permits (dashed: wells spudded; dotted: counted another way), a filled glowing dot is a fractured well; a switch shows both or either
  function layerLegend(dt) {
    S.kindsSeg = segmented({ label: 'What the map shows', tabs: false, prefix: 'nwk', value: kinds, options: [{ id: 'both', label: 'Both' }, { id: 'wells', label: 'Fractured wells' }, { id: 'permits', label: 'Oil permits' }], onChange: (id) => setKinds(id) });
    const have = new Set(dt.rings.map((r) => r.measure));
    const marks = el('ul', { class: 'nw-marks', 'aria-label': 'What the marks on the map are' },
      el('li', {}, dotKey(), 'Fractured well: the first fracturing job, every state that reports'),
      el('li', {}, ringKey('permits'), 'Oil permits approved: a state agency’s count, last 12 months'),
      have.has('spuds') ? el('li', {}, ringKey('spuds'), 'Wells spudded: for agencies that publish no approval dates') : null,
      [...have].some((m) => m !== 'permits' && m !== 'spuds') ? el('li', {}, ringKey('other'), 'Counted another way (applications filed, wells drilled)') : null);
    const note = el('p', { class: 'fine', text: 'A ring’s area is the state agency’s own count. The BLM’s federal-land permits overlap the states and are on the ranking, not on the map. Rings and dots are different things (a permit is the right to drill, a fracturing job comes after) and are never added together.' });
    return el('div', { class: 'nw-legend' }, S.kindsSeg.el, marks, note);
  }
  // 'both', 'wells' or 'permits': the map's layers follow; the replay is of the wells, so it closes while they are hidden
  function setKinds(id, { fromHash = false } = {}) {
    const next = id === 'wells' || id === 'permits' ? id : 'both';
    if (next === kinds || !S.map) return;
    kinds = next;
    if (kinds === 'permits' && S.tl && S.tl.open) S.watch.click();
    S.map.setKinds(flags()); if (S.kindsSeg) S.kindsSeg.set(kinds, false);
    if (S.watch) { S.watch.disabled = kinds === 'permits'; S.watch.title = kinds === 'permits' ? 'The replay shows the fractured wells, which are hidden now' : ''; }
    if (!fromHash) { const a = addr(); if (location.hash !== a) history.replaceState(null, '', a); }
  }
  // the explorer shows the last two years or every year since 2011: the earlier wells are fetched the first time they are asked for, then the map is built again over them
  let switching = false;
  async function switchYears(all) {
    const dt = loaded; if (!dt || all === S.all || switching) return;
    switching = true;
    const hadFocus = !!$('#explore') && $('#explore').contains(document.activeElement); // asked before the buttons are disabled for the load: a disabled button drops the keyboard
    try {
      if (all && !dt.full) {
        S.years.buttons.forEach((b) => { b.disabled = true; });
        S.status.textContent = 'Loading the earlier wells (about 2 MB)…';
        try { await loadHistory(); } catch (e) {
          S.years.buttons.forEach((b) => { b.disabled = false; }); S.years.set('recent', false);
          S.status.textContent = 'Could not load the earlier wells. Check the connection and choose “Since ' + dt.doc.months[0].slice(0, 4) + '” again.';
          return;
        }
      }
      S.all = all;
      const old = $('#explore');
      if (S.tl) S.tl.destroy();
      if (S.map) S.map.destroy();
      S.chips.clear();
      const next = explorer(dt); old.replaceWith(next);
      select(sel, { fromHash: true });
      if (location.hash !== addr()) history.replaceState(null, '', addr());
      if (hadFocus) { const b = S.years.buttons.find((x) => x.dataset.id === (all ? 'all' : 'recent')); if (b) b.focus({ preventScroll: true }); }
    } finally { switching = false; }
  }

  async function draw(mySeq) {
    let dt;
    try { dt = await data(); } catch (e) {
      $('#kpis').replaceChildren(el('p', { class: 'empty', text: 'Could not load the data. Reload the page to try again.' }));
      return;
    }
    if (mySeq !== seq) return;
    if (wantAll) { try { await loadHistory(); S.all = true; } catch (e) { /* the address asked for every year and the earlier wells did not load: the last two years */ } if (mySeq !== seq) return; }
    const host = $('#hero');
    hero(dt);
    S.hero = createUSMap({ canvas: $('#hero-canvas'), host, outlines: dt.outlines, P: dt.P, doc: dt.doc, rings: dt.rings, has: (id) => known(dt, id), interactive: false, box: heroBox(host) });
    host.classList.add('has-map');
    const slot = $('#nw-slot');
    kinds = wantKinds;
    const toMap = () => scrollTo($('#explore'));
    S.rank = rankingCard({ nat: dt.nat, doc: dt.doc, select: (id) => select(id), rows: S.rows, scrollTo: toMap, getSel: () => sel });
    S.leaders = leadersCards({ nat: dt.nat, doc: dt.doc, scope: () => scope(dt) });
    slot.replaceChildren(explorer(dt), S.rank.el, monthsCard({ nat: dt.nat, doc: dt.doc }).el, S.leaders.el, coverageCard({ nat: dt.nat, doc: dt.doc, select: (id) => select(id), scrollTo: toMap }));
    // the hero's buttons and figures: scroll to the explorer and open the replay, or to the ranking (a link to the page it is on would do nothing)
    $('#go-explore').addEventListener('click', (e) => { e.preventDefault(); toMap(); if (!S.tl.open && !S.watch.disabled) S.watch.click(); });
    $('#go-rank').addEventListener('click', (e) => { e.preventDefault(); S.rank.setBy('permits'); scrollTo($('#ranking')); });
    $('#kpis').addEventListener('click', (e) => {
      const a = e.target.closest('a[data-go]'); if (!a) return; e.preventDefault();
      if (a.dataset.go === 'map') toMap(); else { S.rank.setBy(a.dataset.go); scrollTo($('#ranking')); }
    });
    renderFreshness($('#fresh-list'), freshnessItems(dt.nat, dt.doc));
    started = true;
    select(sel, { fromHash: true }); settle();
    if (/[?&]debug\b/.test(location.search)) window.__nw = { get map() { return S.map; }, hero: S.hero, get P() { return scope(dt).P; }, doc: dt.doc, nat: dt.nat, D, C, years: switchYears };
  }

  return {
    // the address names a state (#overview?s=TX), the years (y=all: every year since 2011) and the layer (k=wells or k=permits): the explorer follows. Drawn on the first visit only; later visits just move the map.
    async show(params) {
      const want = ((params && params.get('s')) || '').toUpperCase() || null; const years = !!params && params.get('y') === 'all';
      const k = params && params.get('k'); const wk = k === 'wells' || k === 'permits' ? k : 'both';
      if (!started && !seq) { seq++; sel = want; wantAll = years; wantKinds = wk; await draw(seq); return; }
      if (started) { select(want, { fromHash: true }); if (years !== S.all) await switchYears(years); setKinds(wk, { fromHash: true }); settle(); } else { sel = want; wantAll = years; wantKinds = wk; }
    },
    get selected() { return sel; },
    pause() { if (S.tl && S.tl.open) S.tl.pause(); },
  };
}
