// The Overview page, drawn for the states shown and drawn again when they change. Every state's files are loaded once; each draw merges what
// the states shown have (overview-data.js) into the shapes the cards already take, and the cards that only Texas's records can fill
// (producers, basins, companies) show for Texas and for several states together and step aside when Texas is not shown.
import { $, loadOpt, dayLabel, fmtDate, monthLabel, lastIdx } from './util.js';
import { getGeo, getPoints, getBasins } from './geo.js';
import { createHero } from './hero.js';
import { renderKpis, renderHot, renderTopOps, renderProducers, renderFreshness } from './overview.js';
import { loadMarketData, initMarkets } from './pulse.js';
import { renderBasins, basinRigs } from './basins.js';
import { renderInsights } from './insights.js';
import { STATES, otherStates, stateOf, statesKey, measureOf, sameMeasure } from './states.js';
import { permitSeries, countyPermits, operatorRows, activeWells } from './overview-data.js';

const LEDE = {
  TX: 'New-drill permits from the Permian to the Eagle Ford, the operators filing them and the companies that serve them.',
  OK: 'New-drill permits across Oklahoma, from the Anadarko Basin to the rest of the state, and the operators filing them.',
  NM: 'Wells spudded across New Mexico, from the Delaware Basin to the San Juan Basin, and the operators drilling them.',
  MANY: 'New-drill permits from the Permian to the Anadarko Basin, the operators filing them and, for Texas, the companies that serve them.',
};
// what each state's permit window is called in the hero's eyebrow
const SOURCE = { TX: 'Railroad Commission permits', OK: 'Corporation Commission approvals', NM: 'Oil Conservation Division spud reports' };

const pct = (x) => (x >= 1 ? '100%' : Math.min(99, Math.round(x * 100)) + '%'); // 99.6% is not 100%

export function createOverview(meta) {
  // docs[kind][id] is one state's file of that kind, loaded once; wells[id] is a state's active wells from its Daily report index
  const ov = { meta, raw: null, ops: null, ex: null, docs: { series: {}, county: {}, operators: {} }, wells: {}, daily: null, B: null, prod: null, opProd: null, extra: {}, markets: null, lazy: false };
  let hero = null; let seq = 0; let drawn = ''; let core2 = null; let waveStarted = false; let states = STATES.map((s) => s.id);
  const has = (id) => states.includes(id);
  const others = () => states.filter((id) => id !== 'TX');
  const through = (id) => (id === 'TX' ? meta.sources.latest_permit : ov.docs.series[id] ? ov.docs.series[id].through : meta.sources.latest_permit);

  /* ---------- text that depends on the states ---------- */
  function texts() {
    const many = states.length > 1;
    $('#hero-eyebrow').textContent = many
      ? 'Permits through ' + states.map((id) => fmtDate(through(id)) + ' (' + stateOf(id).name + ')').join(' and ')
      : SOURCE[states[0]] + ' through ' + fmtDate(through(states[0]));
    $('#hero-lede').textContent = (many ? LEDE.MANY : LEDE[states[0]]) + ' Public records only, built ' + fmtDate(meta.built) + '.';
    $('#view-overview').dataset.states = statesKey(states);
    // the cards only Texas's records can fill
    $('#seg-chart').hidden = !has('TX');
    $('#seg-title').textContent = many ? 'Companies by segment, Texas' : 'Companies by segment';
    $('#prod-h').textContent = many ? 'Top producers, Texas' : 'Top producers';
    $('#basins-h').textContent = many ? 'The main producing regions of Texas' : 'The main producing regions';
    if (!has('TX')) { $('#prod-card').hidden = true; $('#basins').hidden = true; }
  }

  /* ---------- the hero's map and its note ---------- */
  async function backdrop(mySeq) {
    const host = $('#hero'); const note = $('#hero-note'); const canvas = $('#hero-canvas');
    try {
      const [G, { P, pm }] = await Promise.all([getGeo(states), getPoints(states)]);
      if (mySeq !== seq) return;
      if (hero) hero.update(G, P); else hero = createHero(canvas, host, G, P);
      const cov = (id) => (pm.coverageBy ? pm.coverageBy[id] : pm.coverage);
      const share = (id) => { const c = cov(id); return pct(c.share24) + ' of the last 24 months, ' + pct(c.share12) + ' of the last 12'; };
      note.textContent = 'Dots are ' + (sameMeasure(states) ? measureOf(states[0]).noun : 'permits and spuds') + ' with a recorded surface location: ' + (states.length > 1 ? states.map((id) => stateOf(id).name + ' ' + share(id)).join('; ') : share(states[0]))
        + '. Brighter dots are the last 12 months. Counts and trends use every one.'
        + (states.some((id) => measureOf(id).id === 'spuds') ? ' New Mexico counts wells spudded, not permits (its regulator publishes no approval dates), and ends two months back because spud dates arrive late.' : '');
      host.classList.add('has-map');
    } catch (err) { note.textContent = 'The map backdrop could not be loaded.'; }
  }

  /* ---------- data ---------- */
  // the small files the first paint needs: Texas's permit series, and each other state's series, operators and Daily report index
  async function core() {
    if (ov.coreLoaded) return;
    ov.docs.series.TX = await loadOpt('series-permits');
    await Promise.all(otherStates.map(async (q) => {
      const [series, operators, index] = await Promise.all([loadOpt(q.files.series), loadOpt(q.files.operators), q.dir ? loadOpt(q.dir + '/index') : null]);
      ov.docs.series[q.id] = series; ov.docs.operators[q.id] = operators; ov.wells[q.id] = activeWells(index);
    }));
    ov.coreLoaded = true;
  }
  function more() {
    if (!core2) {
      const n = otherStates.length;
      core2 = Promise.all([loadMarketData(), loadOpt('operators'), loadOpt('county-permits'), loadOpt('operator-extras'), loadOpt('daily/index'), getBasins().catch(() => null),
        ...otherStates.map((q) => loadOpt(q.files.county))])
        .then((got) => {
          const [raw, ops, cpTx, ex, daily, B] = got;
          Object.assign(ov, { raw, ops, ex, daily, B });
          ov.docs.county.TX = cpTx;
          otherStates.forEach((q, i) => { ov.docs.county[q.id] = got[6 + i]; });
          return n;
        });
    }
    return core2;
  }

  /* ---------- one draw ---------- */
  async function draw(next) {
    states = next.slice();
    const mySeq = ++seq; const key = statesKey(states);
    await core();
    if (mySeq !== seq) return;
    texts();
    renderKpis({ states, meta, sp: permitSeries(states, ov.docs.series), rows: operatorRows(states, null, ov.docs.operators), wells: ov.wells });
    backdrop(mySeq);
    await more();
    if (mySeq !== seq) return;
    const G = await getGeo(states).catch(() => null);
    if (mySeq !== seq) return;
    const cp = countyPermits(states, ov.docs.county);
    const rows = operatorRows(states, ov.ops, ov.docs.operators);
    const ticker = $('#ticker');
    ov.markets = initMarkets({ ticker, card: $('#pulse-card'), raw: ov.raw, states });
    ticker.setAttribute('aria-busy', 'false');
    const from = cp ? dayLabel(Date.parse(cp.asOf + 'T00:00:00Z') - 365 * 864e5) : '';
    const win = !cp ? '' : states.length > 1 ? 'the last 12 months (to ' + states.map((id) => fmtDate(through(id)) + ' in ' + stateOf(id).name).join(', ') + ')'
      : from + ' to ' + fmtDate(through(states[0]));
    renderHot(cp, G, win, states);
    renderTopOps(rows, states);
    const paint = () => renderInsights($('#insights'), {
      cp, G, B: has('TX') ? ov.B : null, ops: ov.ops, extras: ov.ex, meta, prod: ov.prod, R: ov.markets.registry || {}, selectGroup: (id) => ov.markets.select(id, true),
      states, cpTx: ov.docs.county.TX, rows: rows.filter((r) => r.st !== 'TX'), wells: ov.wells,
    });
    ov.paint = paint;
    paint();
    renderFreshness($('#fresh-list'), freshnessItems());
    drawn = key;
    scheduleWave(mySeq);
  }

  // the larger Texas files, the basin cards and the county files that only name a year: when the first card below the fold nears the
  // viewport, or after a pause so slow scrollers still get everything. Loaded once; drawn on every draw that includes Texas.
  async function wave() {
    if (!ov.lazy) {
      ov.lazy = true;
      const [opProd, prod, lab, cbp, min] = await Promise.all([loadOpt('operator-production'), loadOpt('county-production'), loadOpt('county-labor'), loadOpt('county-business'), loadOpt('county-minerals')]);
      Object.assign(ov, { opProd, prod, extra: { lab, cbp, min } });
    }
    paintWave();
  }
  async function paintWave() {
    if (!ov.lazy) return;
    if (has('TX')) {
      const gTx = await getGeo().catch(() => null);
      const pts = await getPoints().catch(() => null);
      renderProducers($('#prod-card'), ov.opProd, ov.ops, new Set(pts ? pts.pm.opNums : []));
      renderBasins({ section: $('#basins'), B: ov.B, G: gTx, cp: ov.docs.county.TX, prod: ov.prod, rigs: ov.markets && ov.markets.registry ? basinRigs(ov.markets.registry) : {}, permitsThrough: monthLabel(meta.sources.latest_permit.slice(0, 7)) });
      $('#basin-cap').textContent = ov.B ? 'Counties from the EIA Drilling Productivity Report; Barnett from the Railroad Commission.' : '';
    }
    if (ov.paint) ov.paint();
    renderFreshness($('#fresh-list'), freshnessItems());
  }
  function scheduleWave(mySeq) {
    if (waveStarted) { if (ov.lazy) paintWave(); return; }
    waveStarted = true;
    const sentinel = $('#pulse-card');
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); wave(); } }, { rootMargin: '700px 0px' });
      io.observe(sentinel);
    }
    setTimeout(wave, 5000);
    ov.wave = wave;
    return mySeq;
  }

  /* ---------- the freshness list: every source with its own latest date ---------- */
  function freshnessItems() {
    const { raw, extra, prod, opProd } = ov; const last = (arr) => arr[lastIdx(arr)];
    const items = [];
    if (!raw) return items;
    if (has('TX')) {
      items.push({ icon: 'pin', label: 'Permits, monthly master (Railroad Commission)', value: 'Issued to ' + fmtDate(meta.sources.latest_permit), cadence: 'monthly' });
      const dl = ov.daily && ov.daily.days[ov.daily.days.length - 1];
      if (dl && dl.dd) items.push({ icon: 'pin', label: 'Permits, nightly file (Daily report)', value: 'Issued to ' + fmtDate(dl.dd), cadence: 'nightly' });
    }
    for (const id of others()) {
      const s = ov.docs.series[id]; const q = stateOf(id);
      if (s) items.push({ icon: 'pin', label: (measureOf(id).id === 'spuds' ? 'Wells spudded' : 'Permits') + ' (' + q.agency + ')', value: measureOf(id).verb + ' to ' + fmtDate(s.through), cadence: s.cadence || 'daily' });
      if (ov.wells[id]) items.push({ icon: 'rig', label: 'Well inventory (' + q.agency + ')', value: 'Counted ' + fmtDate(ov.wells[id].day), cadence: 'nightly' });
    }
    const sr = raw['series-production']; const pf = prod || opProd || sr;
    if (has('TX') && pf) {
      const thru = pf.completeThrough || pf.months[pf.months.length - 1];
      items.push({ icon: 'drop', label: 'Production (Railroad Commission)', value: 'Complete to ' + monthLabel(thru) + (pf.newest && pf.newest > thru ? '; newer months still filling in' : ''), cadence: 'monthly' });
    }
    const rg = raw['series-rigs']; if (has('TX') && rg) items.push({ icon: 'rig', label: 'Rig counts (Baker Hughes)', value: 'Week of ' + fmtDate(rg.through), cadence: 'weekly' });
    const sm = raw['series-markets'];
    if (sm && sm.wti) items.push({ icon: 'chart', label: 'WTI and Henry Hub (EIA)', value: 'Monthly, to ' + monthLabel(sm.months[lastIdx(sm.wti)]), cadence: 'monthly' });
    if (has('TX') && sm && sm.txCrude) items.push({ icon: 'pipe', label: 'Texas crude estimate (EIA)', value: 'Estimates to ' + monthLabel(sm.months[lastIdx(sm.txCrude)]), cadence: 'monthly' });
    for (const id of others()) {
      const q = stateOf(id); const f = q.files.crude && raw[q.files.crude];
      if (f) items.push({ icon: 'pipe', label: q.name + ' crude estimate (EIA)', value: 'Estimates to ' + monthLabel(f.latest), cadence: 'monthly' });
    }
    const ol = raw['series-outlook']; if (ol) items.push({ icon: 'trend', label: 'Price outlook (EIA forecast)', value: 'Issued ' + monthLabel(ol.issued) + ', to ' + monthLabel(ol.months[ol.months.length - 1]), cadence: 'monthly' });
    const tx = raw['series-tax']; if (has('TX') && tx) items.push({ icon: 'dollar', label: 'Production tax (Comptroller)', value: 'Collected to ' + monthLabel(tx.months[tx.months.length - 1]), cadence: 'monthly' });
    const jb = raw['series-jobs']; if (has('TX') && jb) items.push({ icon: 'jobs', label: 'Oil and gas jobs (BLS)', value: 'To ' + monthLabel(jb.latest || last(jb.months)) + ', first print', cadence: 'monthly' });
    if (has('TX') && extra.lab) items.push({ icon: 'jobs', label: 'County jobs and wages (BLS)', value: 'Annual averages, ' + extra.lab.year, cadence: 'annually' });
    if (has('TX') && extra.cbp) items.push({ icon: 'building', label: 'Establishments (Census)', value: 'County Business Patterns ' + extra.cbp.year, cadence: 'annually' });
    if (has('TX') && extra.min) items.push({ icon: 'gem', label: 'Mineral values (Comptroller)', value: 'Tax year ' + extra.min.year, cadence: 'annually' });
    if (has('TX')) items.push({ icon: 'building', label: 'Company records (Comptroller)', value: 'Updated ' + fmtDate(meta.sources.comptroller) });
    return items;
  }

  return {
    ov,
    // draws for these states unless that is what is already there
    show(next) { if (statesKey(next) !== drawn || seq === 0) return draw(next); return Promise.resolve(); },
    // the states changed: draw again now when the Overview is on screen, otherwise the next time it is shown
    stale() { drawn = ''; },
    draw,
  };
}
