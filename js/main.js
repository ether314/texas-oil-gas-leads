// Boot, hash routing and wiring. Every data-dependent block degrades on its own if its file is missing.
import { $, $$, el, load, loadOpt, parseHash, replaceHash, fmt, monthLabel, reduced } from './util.js';
import { initTheme } from './theme.js';
import { hideTip } from './tip.js';
import { fillMeta, renderSegments } from './overview.js';
import { createOverview } from './overview-view.js';
import { createMapView } from './map.js';
import { createTables } from './tables.js';
import { createDailyView } from './daily.js';
import { icon } from './icons.js';
import { initReveal, navIndicator, segmented } from './ui.js';
import { STATES, activeStates, setStates, onStates, parseStates, stateParam } from './states.js';

const VIEWS = { overview: 'Overview', map: 'Map', operators: 'Operators', companies: 'Companies', daily: 'Daily report', about: 'Sources & method' };
// the views that follow the Both / Texas / Oklahoma choice; the others show what they showed before (Texas) and hide the choice
const STATE_VIEWS = new Set(['overview', 'daily']);

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

// Sources & method is long: a sticky "on this page" list on wide screens. Buttons, not links, so the hash router is left alone.
function buildToc() {
  const prose = $('#view-about .prose');
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
  const overview = createOverview(meta);

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

  /* ---------- the states shown: one choice for every view that follows it, kept in the address as st=tx or st=ok ---------- */
  const choice = () => (activeStates().length === STATES.length ? 'all' : activeStates().length === 1 ? activeStates()[0] : 'all');
  const bar = segmented({
    label: 'States shown', tabs: false, prefix: 'sb', value: choice(),
    options: [{ id: 'all', label: 'All' }, ...STATES.map((x) => ({ id: x.id, label: x.name }))],
    onChange: (id) => setStates(id === 'all' ? STATES.map((x) => x.id) : [id]),
  });
  $('#statebar-seg').append(bar.el);
  // keeps the address bar in step with the choice without firing hashchange: st is only in it when the choice is not both
  function syncAddress() {
    const { view, params } = parseHash();
    const sp = stateParam(activeStates());
    if (sp) params.set('st', sp); else params.delete('st');
    replaceHash(view, params);
  }

  // what the bar says about the view on screen: the Daily report only has some states
  const note = $('#statebar-note');
  function setNote() {
    let text = '';
    if (shown === 'daily') {
      const have = daily.available();
      const missing = activeStates().filter((id) => have.length && !have.includes(id));
      if (missing.length) {
        const names = (ids) => ids.map((id) => STATES.find((x) => x.id === id).name).join(' and ');
        const shownIds = activeStates().filter((id) => have.includes(id));
        text = names(missing) + ' ' + (missing.length > 1 ? 'have' : 'has') + ' no Daily report yet; ' + (shownIds.length ? 'it shows ' + names(shownIds) + '.' : 'it shows ' + names(have) + ' instead.');
      }
    }
    note.textContent = text;
  }

  let shown = '';
  function show(moveFocus) {
    let { view, params, hasQuery } = parseHash();
    // the Oklahoma report is part of the Daily report now: an old link to it opens the Daily report showing Oklahoma
    if (view === 'oklahoma') {
      params.set('st', 'ok');
      history.replaceState(null, '', '#daily?' + params);
      view = 'daily'; hasQuery = true;
    }
    const id = Object.prototype.hasOwnProperty.call(VIEWS, view) ? view : 'overview';
    // an address that names the states sets the choice (quietly: this view is about to be drawn for it); one that does not keeps
    // the choice, and says so in the address
    if (params.has('st')) { if (setStates(parseStates(params.get('st')), true)) overview.stale(); } else if (stateParam(activeStates())) syncAddress();
    bar.set(choice(), false);
    const rest = new URLSearchParams(params); rest.delete('st');
    hasQuery = rest.toString() !== '';
    $('#statebar').hidden = !STATE_VIEWS.has(id);
    hideTip();
    Object.keys(VIEWS).forEach((v) => { $('#view-' + v).hidden = v !== id; });
    $$('.nav a').forEach((a) => {
      if (a.getAttribute('href') === '#' + id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    placeNav();
    document.title = (id === 'overview' ? '' : VIEWS[id] + ' · ') + 'Oil tracker';
    // a link with a query (a bar or tile on the overview) restarts that view from its defaults plus the query
    if (hasQuery && lazy[id]) lazy[id].t.ex.apply(params);
    if (id === 'map') { if (hasQuery) map.apply(params); map.activate(); } else if (shown === 'map') map.deactivate();
    ensure(id);
    if (id === 'overview') overview.show(activeStates());
    if (id === 'daily') daily.activate(params).then(() => { bar.set(choice(), false); setNote(); });
    if (id === 'about') fillProdNote();
    if (moveFocus) {
      if (shown !== id || hasQuery) window.scrollTo(0, 0);
      const h = $('#view-' + id + ' h1');
      h.setAttribute('tabindex', '-1');
      h.focus({ preventScroll: true });
    }
    shown = id;
    setNote();
  }
  // the choice changed on the page (the bar): the address follows, and the view on screen is drawn again
  onStates((ids) => {
    bar.set(choice(), false);
    syncAddress();
    overview.stale();
    if (shown === 'overview') overview.show(ids);
    else if (shown === 'daily') daily.setStates(ids);
    setNote();
  });
  window.addEventListener('hashchange', () => show(true));
  show(false);
  document.documentElement.classList.add('ready');
  if (new URLSearchParams(location.search).has('debug')) window.__app = { fmt, ov: overview.ov };
}

boot();
