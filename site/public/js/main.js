// Boot, hash routing and wiring. Every data-dependent block degrades on its own if its file is missing.
import { $, $$, el, load, loadOpt, parseHash, replaceHash, fmt, fmtDate, monthLabel, reduced } from './util.js';
import { initTheme } from './theme.js';
import { hideTip } from './tip.js';
import { fillMeta } from './overview.js';
import { createOverview } from './overview-view.js';
import { createMapView } from './map.js';
import { createTables } from './tables.js';
import { createDailyView } from './daily.js';
import { createNationalView } from './national.js';
import { sourceHref } from './national-data.js';
import { createImagesView } from './images.js';
import { createFieldsView } from './fields.js';
import { icon } from './icons.js';
import { initReveal, navIndicator, segmented } from './ui.js';
import { STATES, activeStates, setStates, onStates, parseStates, stateParam, statesKey, statesIn, inName, shortName, placesOne, measurePhrase, measureAnd, everyOf, spudCaveat, ucFirst, listOr } from './states.js';

const VIEWS = { overview: 'Overview', national: 'National report', fields: 'Permit data', images: 'Texas images', map: 'Map', operators: 'Operators', companies: 'Companies', daily: 'Daily report', about: 'Sources & method' };
// the views that follow the states bar; the others (Sources) hide it
const STATE_VIEWS = new Set(['map', 'operators', 'companies']);

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

/* the Sources page's figures for the files a weekly refresh moves (the federal offshore's, New Mexico's end date) are read from those files, so the text moves with the refresh
   instead of going stale (a week that BSEE adds a month changes the date, the year's count and the operators; a missing file leaves a plain word, never an empty gap) */
async function fillFromFiles(meta) {
  const [ser, ops, eia, nm, eiaOk, eiaNm, nw] = await Promise.all([loadOpt('series-permits-fo'), loadOpt('operators-fo'), loadOpt('series-fo'), loadOpt('series-permits-nm'), loadOpt('series-ok'), loadOpt('series-nm'), loadOpt('newwells/summary')]);
  const extra = { foSince: 'the start of the record', foThrough: 'the last complete month', foYear: 'Fewer than a hundred', foOps: 'a few', foEiaThrough: 'the newest month', foEiaNow: 'the monthly total', nmThrough: 'the last complete month', okEiaThrough: 'the newest month', nmEiaThrough: 'the newest month', nwSettled: 'the last settled month' };
  if (nm && nm.through) extra.nmThrough = fmtDate(nm.through);
  if (nw && nw.settled) extra.nwSettled = monthLabel(nw.settled.slice(0, 7));
  if (eiaOk && eiaOk.latest) extra.okEiaThrough = monthLabel(eiaOk.latest);  // the EIA's monthly crude series (refreshed by hand each month): the month each one's file says it runs to
  if (eiaNm && eiaNm.latest) extra.nmEiaThrough = monthLabel(eiaNm.latest);
  if (ser && ser.months && ser.months.length) {
    extra.foSince = monthLabel(ser.months[0]); extra.foThrough = fmtDate(ser.through);
    extra.foYear = fmt.format(ser.permits.slice(-12).reduce((t, n) => t + n, 0));
  }
  if (ops && ops.rows && ops.rows.length) extra.foOps = fmt.format(ops.rows.length);
  if (eia && eia.foCrude && eia.latest) {
    const v = eia.foCrude[eia.foCrude.length - 1];
    extra.foEiaThrough = monthLabel(eia.latest);
    if (v) extra.foEiaNow = 'about ' + fmt.format(Math.round(v / 1000)) + ' million barrels in ' + monthLabel(eia.latest);
  }
  fillMeta(meta, extra);
}

/* the Sources page's list of the state agencies behind the National report is made from national.json (each state's source, cadence and what it counts), so it cannot go stale;
   the four jurisdictions that have their own entries above are left out, and a missing file leaves the one line of text that is already there */
async function fillNational() {
  const [doc, fields] = await Promise.all([loadOpt('national'), loadOpt('permit-fields')]);
  const ul = $('#src-national');
  if (!doc || !Array.isArray(doc.states) || !ul) return;
  const rows = doc.states.filter((s) => !['TX', 'OK', 'NM', 'FO'].includes(s.id)).map((s) => {
    const h = sourceHref(s, fields);
    return el('li', {}, el('small', { class: 'fresh-cad src-cad', text: s.cadence ? s.cadence.charAt(0).toUpperCase() + s.cadence.slice(1) : 'Irregular' }), ' ',
      h ? el('a', { href: h.href, rel: 'noopener noreferrer', text: s.agency }) : el('span', { text: s.agency }), ': ' + s.source.name + '; counted by ' + s.basis + '.');
  });
  const gaps = doc.gaps && doc.gaps.length ? [el('li', {}, 'Not read yet, with the reason for each in the report’s coverage table: ' + doc.gaps.map((g) => g.name).join(', ') + '.')] : [];
  ul.append(...rows, ...gaps);
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
  fillFromFiles(meta).catch(() => {});
  fillNational().catch(() => {});
  const overview = createOverview(meta);

  const tables = createTables(meta);
  const map = createMapView({ root: $('#map-root'), meta });
  const daily = createDailyView({ root: $('#daily-root') });
  const national = createNationalView({ root: $('#national-root') });
  const images = createImagesView({ root: $('#images-root') });
  const fields = createFieldsView({ root: $('#fields-root') });
  const lazy = { operators: { t: tables.operators, started: false, key: '' }, companies: { t: tables.companies, started: false, key: '' } };
  // loads a table the first time its view is shown, and the Operators again when the states shown have changed since
  function ensure(name) {
    const item = lazy[name];
    const key = name === 'operators' ? statesKey(activeStates()) : '';
    if (!item || (item.started && item.key === key)) return;
    item.started = true; item.key = key;
    item.t.load(activeStates()).catch(() => { item.started = false; item.key = ''; item.t.ex.fail('Could not load the data. Reload the page to try again.'); });
  }
  // what the Operators and Companies pages say about the states shown. Companies are the Texas Comptroller's records, so they are Texas only.
  const MAP_TX = 'County activity, permit locations and energy facilities across Texas. Shading and counts use every permit; dots show the ones with a recorded location.';
  const TX_WHAT = 'Active RRC registrants that are corporations, LLCs or limited partnerships, ranked by drilling permits.';
  function pageTexts() {
    const ids = activeStates();
    // the sentence on what the operators are; tables.js adds the dates each state's data runs to when its files are in
    // (what a state's count leaves out, where it has something to say: a sidetrack is not a new well offshore, so an operator that sidetracked ten times ranks with none)
    $('#ops-what').textContent = ids.length === 1 && ids[0] === 'TX' ? TX_WHAT
      : 'Operators that are corporations, LLCs or limited partnerships, ranked by ' + measurePhrase(ids) + ' in the last 12 months.' + (spudCaveat(ids) ? ' ' + spudCaveat(ids) : '');
    const tx = ids.includes('TX');
    // the dots are permits where a state counts permits and wells where it counts spuds, and a county is an area offshore
    $('#map-lede').textContent = ids.length === 1 && tx ? MAP_TX
      : ucFirst(placesOne(ids)) + ' activity and ' + measureAnd(ids) + ' locations across ' + statesIn(ids) + '. Shading and counts use ' + everyOf(ids)
        + '; dots show the ones with a recorded location.' + (tx ? ' Plants, company ZIPs and basins are Texas only.' : '');
    $('#co-root').hidden = !tx;
    const co = $('#co-note');
    co.hidden = tx && ids.length === 1;
    // with Texas among several states the note is a line under the heading; with none of them it is the page's empty state
    co.className = tx ? 'fine' : 'empty';
    co.textContent = !tx ? 'Companies come from the Texas Comptroller’s franchise-tax records, so there is nothing to list for ' + listOr(ids.map(inName))
      + ': no public bulk list like it exists there. Choose All or Texas to browse the Texas pool.' : ids.length > 1 ? 'The company pool is the Texas Comptroller’s, so this list is Texas only.' : '';
  }

  /* ---------- the states shown: one choice for every view that follows it, kept in the address as st=tx or st=ok ---------- */
  // the bar offers All and each state; an address can also name two of three (st=tx,ok): then the bar has none chosen, and the note below says which are shown
  const choice = () => (activeStates().length === STATES.length ? 'all' : activeStates().length === 1 ? activeStates()[0] : null);
  const bar = segmented({
    label: 'States shown', tabs: false, prefix: 'sb', value: choice(),
    options: [{ id: 'all', label: 'All', dot: 'st-all' },
      // the name a screen reader says holds the visible label ("Texas (TX)", "Federal offshore" for "Offshore"); a phone shows TX, OK, NM
      ...STATES.map((x) => ({ id: x.id, label: shortName(x.id), abbr: x.short ? null : x.id, title: x.short ? x.name : x.name + ' (' + x.id + ')', dot: 'st-' + x.id.toLowerCase() }))],
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

  // what the bar says when the address names two states of the four: which are shown
  const note = $('#statebar-note');
  function setNote() {
    let text = activeStates().length > 1 && activeStates().length < STATES.length ? 'Showing ' + statesIn(activeStates()) + '. Choose a state, or All, to change it.' : '';
    note.textContent = text;
  }

  let shown = '';
  function show(moveFocus) {
    let { view, params, hasQuery } = parseHash();
    // the Oklahoma report is part of the Daily report now: an old link to it opens the Daily report on Oklahoma's wells
    if (view === 'oklahoma') {
      params.set('s', 'OK');
      history.replaceState(null, '', '#daily?' + params);
      view = 'daily'; hasQuery = true;
    }
    const id = Object.prototype.hasOwnProperty.call(VIEWS, view) ? view : 'overview';
    // an address that names the states sets the choice (quietly: this view is about to be drawn for it); one that does not keeps
    // the choice, and says so in the address
    if (params.has('st')) setStates(parseStates(params.get('st')), true); else if (STATE_VIEWS.has(id) && stateParam(activeStates())) syncAddress();
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
    pageTexts();
    ensure(id);
    if (id === 'overview') overview.show(params); else if (shown === 'overview') overview.pause();
    if (id === 'daily') daily.activate(params); else if (shown === 'daily') daily.deactivate();
    if (id === 'national') national.activate(params); else if (shown === 'national') national.deactivate();
    if (id === 'images') images.activate(params); else if (shown === 'images') images.deactivate();
    if (id === 'fields') fields.activate(params); else if (shown === 'fields') fields.deactivate();
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
    pageTexts();
    if (shown === 'map') map.setStates();
    else if (shown === 'operators' || shown === 'companies') ensure(shown);
    setNote();
  });
  window.addEventListener('hashchange', () => show(true));
  show(false);
  document.documentElement.classList.add('ready');
  if (new URLSearchParams(location.search).has('debug')) window.__app = { fmt, overview };
}

boot();
