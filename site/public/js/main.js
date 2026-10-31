// Boot, hash routing and wiring. Every data-dependent block degrades on its own if its file is missing.
import { $, $$, el, load, loadOpt, parseHash, dayLabel, fmt, fmtDate, monthLabel, lastIdx, reduced } from './util.js';
import { initTheme } from './theme.js';
import { hideTip } from './tip.js';
import { getGeo, getPoints, getBasins } from './geo.js';
import { createHero } from './hero.js';
import { fillMeta, renderKpis, renderHot, renderTopOps, renderSegments, renderProducers, renderFreshness } from './overview.js';
import { loadMarketData, initMarkets } from './pulse.js';
import { renderBasins, basinRigs } from './basins.js';
import { renderInsights } from './insights.js';
import { createMapView } from './map.js';
import { createTables } from './tables.js';
import { createDailyView } from './daily.js';
import { icon } from './icons.js';
import { initReveal, navIndicator } from './ui.js';

const VIEWS = { overview: 'Overview', map: 'Map', operators: 'Operators', companies: 'Companies', daily: 'Daily report', about: 'Sources & method' };

function startHero() {
  const canvas = $('#hero-canvas'); const host = $('#hero');
  Promise.all([getGeo(), getPoints()]).then(([G, { P, pm }]) => {
    createHero(canvas, host, G, P);
    const cv = pm.coverage;
    $('#hero-note').textContent = 'Dots are permits with a recorded surface location: ' + Math.round(cv.share24 * 100) + '% of the last 24 months, '
      + Math.round(cv.share12 * 100) + '% of the last 12. Brighter dots are the last 12 months. Counts and trends use every permit.';
    host.classList.add('has-map');
  }).catch(() => { $('#hero-note').textContent = 'The map backdrop could not be loaded.'; });
}

const ov = { meta: null, raw: null, markets: null, ops: null, cp: null, ex: null, G: null, B: null, prod: null, opProd: null, extra: {}, lazy: false, daily: null };

/* sources note for the production file, filled from the file itself so it never claims more than was pulled */
async function fillProdNote() {
  const [cpr, opr, sr] = await Promise.all([loadOpt('county-production'), loadOpt('operator-production'), loadOpt('series-production')]);
  const li = $('#src-prod'); const slot = $('[data-fill-src="production"]');
  if (!cpr && !opr && !sr) { li.hidden = true; $('#src-prod2').hidden = true; $('#src-p5').hidden = true; return; }
  const parts = [];
  if (sr && sr.months) parts.push('Statewide monthly totals from ' + monthLabel(sr.months[0]) + ' to ' + monthLabel(sr.completeThrough || sr.months[sr.months.length - 1]) + ' (complete months only).');
  if (cpr) parts.push('Monthly figures for the latest ' + cpr.months.length + ' complete months in ' + fmt.format(Object.keys(cpr.counties).length) + ' producing counties.');
  if (opr) parts.push('The latest ' + opr.months.length + ' complete months for the ' + fmt.format(opr.rows.length) + ' named operators with output' + (opr.nameableShare ? ', who hold ' + (opr.nameableShare.oil * 100).toFixed(1) + '% of the oil and ' + (opr.nameableShare.gas * 100).toFixed(1) + '% of the gas' : '') + '.');
  const nw = (sr && sr.newest) || (cpr && cpr.newest);
  if (nw && ((sr && sr.completeThrough) || (cpr && cpr.completeThrough)) && nw > ((sr && sr.completeThrough) || cpr.completeThrough)) parts.push('The file runs to ' + monthLabel(nw) + ', but months after ' + monthLabel((sr && sr.completeThrough) || cpr.completeThrough) + ' are still being filled in by operators (they run below the EIA estimate), so they are left out.');
  slot.textContent = parts.join(' ');
  li.hidden = false; $('#src-prod2').hidden = false; $('#src-p5').hidden = !opr;
}

function freshnessItems() {
  const { meta, raw, extra, prod, opProd } = ov; const last = (arr) => arr[lastIdx(arr)];
  // cadence is how often the source publishes (from the pipeline notes), not how often this static site is rebuilt
  const items = [{ icon: 'pin', label: 'Permits, monthly master (Railroad Commission)', value: 'Issued to ' + fmtDate(meta.sources.latest_permit), cadence: 'monthly' }];
  const dl = ov.daily && ov.daily.days[ov.daily.days.length - 1];
  if (dl && dl.dd) items.push({ icon: 'pin', label: 'Permits, nightly file (Daily report)', value: 'Issued to ' + fmtDate(dl.dd), cadence: 'nightly' });
  const sr = raw['series-production']; const pf = prod || opProd || sr;
  if (pf) {
    const thru = pf.completeThrough || pf.months[pf.months.length - 1];
    items.push({ icon: 'drop', label: 'Production (Railroad Commission)', value: 'Complete to ' + monthLabel(thru) + (pf.newest && pf.newest > thru ? '; newer months still filling in' : ''), cadence: 'monthly' });
  }
  const rg = raw['series-rigs']; if (rg) items.push({ icon: 'rig', label: 'Rig counts (Baker Hughes)', value: 'Week of ' + fmtDate(rg.through), cadence: 'weekly' });
  const sm = raw['series-markets'];
  if (sm && sm.wti) items.push({ icon: 'chart', label: 'WTI and Henry Hub (EIA)', value: 'Monthly, to ' + monthLabel(sm.months[lastIdx(sm.wti)]), cadence: 'monthly' });
  if (sm && sm.txCrude) items.push({ icon: 'pipe', label: 'Texas crude estimate (EIA)', value: 'Estimates to ' + monthLabel(sm.months[lastIdx(sm.txCrude)]), cadence: 'monthly' });
  const ol = raw['series-outlook']; if (ol) items.push({ icon: 'trend', label: 'Price outlook (EIA forecast)', value: 'Issued ' + monthLabel(ol.issued) + ', to ' + monthLabel(ol.months[ol.months.length - 1]), cadence: 'monthly' });
  const tx = raw['series-tax']; if (tx) items.push({ icon: 'dollar', label: 'Production tax (Comptroller)', value: 'Collected to ' + monthLabel(tx.months[tx.months.length - 1]), cadence: 'monthly' });
  const jb = raw['series-jobs']; if (jb) items.push({ icon: 'jobs', label: 'Oil and gas jobs (BLS)', value: 'To ' + monthLabel(jb.latest || last(jb.months)) + ', first print', cadence: 'monthly' });
  if (extra.lab) items.push({ icon: 'jobs', label: 'County jobs and wages (BLS)', value: 'Annual averages, ' + extra.lab.year, cadence: 'annually' });
  if (extra.cbp) items.push({ icon: 'building', label: 'Establishments (Census)', value: 'County Business Patterns ' + extra.cbp.year, cadence: 'annually' });
  if (extra.min) items.push({ icon: 'gem', label: 'Mineral values (Comptroller)', value: 'Tax year ' + extra.min.year, cadence: 'annually' });
  items.push({ icon: 'building', label: 'Company records (Comptroller)', value: 'Updated ' + fmtDate(meta.sources.comptroller) });
  return items;
}

async function loadOverview(meta) {
  ov.meta = meta;
  const sp = await loadOpt('series-permits');
  renderKpis(meta, sp);
  const [raw, ops, cp, ex, G, B, daily] = await Promise.all([loadMarketData(), loadOpt('operators'), loadOpt('county-permits'), loadOpt('operator-extras'),
    getGeo().catch(() => null), getBasins().catch(() => null), loadOpt('daily/index')]);
  Object.assign(ov, { raw, ops, cp, ex, G, B, daily });
  const ticker = $('#ticker');
  const markets = initMarkets({ ticker, card: $('#pulse-card'), raw });
  ticker.setAttribute('aria-busy', 'false');
  ov.markets = markets;
  const win = cp ? dayLabel(Date.parse(cp.asOf + 'T00:00:00Z') - 365 * 864e5) + ' to ' + fmtDate(meta.sources.latest_permit) : '';
  renderHot(cp, G, win);
  renderTopOps(ops);
  const paint = () => renderInsights($('#insights'), { cp, G, B, ops, extras: ex, meta, prod: ov.prod, R: markets.registry || {}, selectGroup: (id) => markets.select(id, true) });
  paint();
  renderFreshness($('#fresh-list'), freshnessItems());

  // second wave: the larger production files, the basin cards and the county files that only name a year
  async function wave() {
    if (ov.lazy) return;
    ov.lazy = true;
    const [opProd, prod, lab, cbp, min] = await Promise.all([loadOpt('operator-production'), loadOpt('county-production'), loadOpt('county-labor'), loadOpt('county-business'), loadOpt('county-minerals')]);
    Object.assign(ov, { opProd, prod, extra: { lab, cbp, min } });
    const pts = await getPoints().catch(() => null);
    renderProducers($('#prod-card'), opProd, ops, new Set(pts ? pts.pm.opNums : []));
    renderBasins({ section: $('#basins'), B, G, cp, prod, rigs: markets.registry ? basinRigs(markets.registry) : {}, permitsThrough: monthLabel(meta.sources.latest_permit.slice(0, 7)) });
    $('#basin-cap').textContent = B ? 'Counties from the EIA Drilling Productivity Report; Barnett from the Railroad Commission.' : '';
    paint();
    renderFreshness($('#fresh-list'), freshnessItems());
    fillProdNote();
  }
  ov.wave = wave;
  // start when the first card below the fold nears the viewport, or after a pause so slow scrollers still get everything
  const sentinel = $('#pulse-card');
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); wave(); } }, { rootMargin: '700px 0px' });
    io.observe(sentinel);
  }
  setTimeout(wave, 5000);
}

// Sources & method is long: a sticky "on this page" list on wide screens. Buttons, not links, so the hash router is left alone.
function buildToc() {
  const prose = $('#about .prose');
  if (!prose) return;
  const heads = $$('h2, h3', prose);
  const nav = el('nav', { class: 'toc', 'aria-label': 'On this page' }, el('p', { class: 'eyebrow', text: 'On this page' }),
    el('ul', {}, heads.map((h) => el('li', { class: h.tagName === 'H3' ? 'sub' : null }, el('button', {
      type: 'button', class: 'link', text: h.textContent, onclick: () => h.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' }),
    })))));
  const wrap = el('div', { class: 'prose-grid' });
  prose.replaceWith(wrap); wrap.append(prose, nav);
}

function hydrateIcons() {
  $$('[data-icon]').forEach((n) => { const i = icon(n.dataset.icon, n.closest('.more-link') ? 16 : 15); if (i) n.replaceWith(i); });
}

async function boot() {
  initTheme();
  hydrateIcons();
  buildToc();
  initReveal();
  const placeNav = navIndicator($('.nav'));
  let meta;
  try {
    meta = await load('meta');
  } catch (err) {
    $('#kpis').replaceChildren(el('p', { class: 'empty', text: 'Could not load the data. Reload the page to try again.' }));
    return;
  }
  fillMeta(meta);
  renderSegments(meta);
  startHero();
  loadOverview(meta).catch(() => { /* each block already hides itself when its file is missing */ });

  const tables = createTables(meta);
  const map = createMapView({ root: $('#map-root'), meta });
  const daily = createDailyView({ root: $('#daily-root') });
  const lazy = { operators: { t: tables.operators, started: false }, companies: { t: tables.companies, started: false } };
  function ensure(name) {
    const item = lazy[name];
    if (!item || item.started) return;
    item.started = true;
    item.t.load().catch(() => { item.started = false; item.t.ex.fail('Could not load the data. Reload the page to try again.'); });
  }

  let shown = '';
  function show(moveFocus) {
    const { view, params, hasQuery } = parseHash();
    const id = Object.prototype.hasOwnProperty.call(VIEWS, view) ? view : 'overview';
    hideTip();
    Object.keys(VIEWS).forEach((v) => { $('#' + v).hidden = v !== id; });
    $$('.nav a').forEach((a) => {
      if (a.getAttribute('href') === '#' + id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    placeNav();
    document.title = (id === 'overview' ? '' : VIEWS[id] + ' · ') + 'Texas Oil & Gas Leads';
    // a link with a query (a bar or tile on the overview) restarts that view from its defaults plus the query
    if (hasQuery && lazy[id]) lazy[id].t.ex.apply(params);
    if (id === 'map') { if (hasQuery) map.apply(params); map.activate(); } else if (shown === 'map') map.deactivate();
    ensure(id);
    if (id === 'daily') daily.activate(params);
    if (id === 'about') fillProdNote();
    if (moveFocus) {
      if (shown !== id || hasQuery) window.scrollTo(0, 0);
      const h = $('#' + id + ' h1');
      h.setAttribute('tabindex', '-1');
      h.focus({ preventScroll: true });
    }
    shown = id;
  }
  window.addEventListener('hashchange', () => show(true));
  show(false);
  document.documentElement.classList.add('ready');
  if (new URLSearchParams(location.search).has('debug')) window.__app = { fmt, ov };
}

boot();
