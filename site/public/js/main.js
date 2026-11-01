// Boot, hash routing and wiring. Every data-dependent block degrades on its own if its file is missing.
import { $, $$, el, load, loadOpt, parseHash, queryText, fmt, fmtDate, monthLabel, reduced } from './util.js';
import { initTheme } from './theme.js';
import { hideTip } from './tip.js';
import { fillMeta } from './overview.js';
import { createOverview } from './overview-view.js';
import { createCompaniesView } from './companies.js';
import { createDailyView } from './daily.js';
import { sourceHref } from './national-data.js';
import { createImagesView } from './images.js';
import { createFieldsView } from './fields.js';
import { icon } from './icons.js';
import { initReveal, navIndicator } from './ui.js';
import { fromOperators } from './companies-data.js';

const VIEWS = { overview: 'Overview', fields: 'Permit data', images: 'Texas images', companies: 'Companies', daily: 'Daily report', about: 'Sources & method' };
// the Overview is the old Overview, National report and Map in one: a link to either of the other two opens it, on the state the link named (the Map's st=fo, one state; two states or none: the country)
const OLD_VIEWS = { national: (p) => (p.get('s') || '').toUpperCase(), map: (p) => ((p.get('st') || '').split(',').length === 1 ? (p.get('st') || '').toUpperCase() : '') };

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

/* the Sources page's list of the state agencies behind the Overview’s oil permit counts is made from national.json (each state's source, cadence and what it counts), so it cannot go stale;
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
  const gaps = doc.gaps && doc.gaps.length ? [el('li', {}, 'Not read yet, with the reason for each in the Overview’s coverage table: ' + doc.gaps.map((g) => g.name).join(', ') + '.')] : [];
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

  const daily = createDailyView({ root: $('#daily-root') });
  const images = createImagesView({ root: $('#images-root') });
  const fields = createFieldsView({ root: $('#fields-root') });
  const companies = createCompaniesView({ meta });
  let shown = '';
  function show(moveFocus) {
    let { view, params, hasQuery } = parseHash();
    // the Oklahoma report is part of the Daily report now: an old link to it opens the Daily report on Oklahoma's wells
    if (view === 'oklahoma') {
      params.set('s', 'OK');
      history.replaceState(null, '', '#daily?' + params);
      view = 'daily'; hasQuery = true;
    }
    // the Operators list is part of the Companies page now (the states bar's choice becomes the page's State filter): an old link to it opens the page on the operators
    if (view === 'operators') {
      params = fromOperators(params);
      const q = queryText(params);
      history.replaceState(null, '', '#companies' + (q ? '?' + q : ''));
      view = 'companies'; hasQuery = q !== '';
    }
    // the National report and the Map are the Overview now: their old addresses open it (the state a link named stays chosen)
    if (Object.prototype.hasOwnProperty.call(OLD_VIEWS, view)) {
      const st = OLD_VIEWS[view](params); const q = new URLSearchParams(); if (st) q.set('s', st);
      history.replaceState(null, '', '#overview' + (q.toString() ? '?' + q : ''));
      view = 'overview'; params = q; hasQuery = !!st;
    }
    const id = Object.prototype.hasOwnProperty.call(VIEWS, view) ? view : 'overview';
    hideTip();
    Object.keys(VIEWS).forEach((v) => { $('#view-' + v).hidden = v !== id; });
    $$('.nav a').forEach((a) => {
      if (a.getAttribute('href') === '#' + id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    placeNav();
    document.title = (id === 'overview' ? '' : VIEWS[id] + ' · ') + 'Oil tracker';
    // a link with a query restarts the Companies lists from their defaults plus the query; with none the page opens as it was left
    if (id === 'companies') companies.activate(params, hasQuery); else if (shown === 'companies') companies.deactivate();
    if (id === 'overview') overview.show(params); else if (shown === 'overview') overview.pause();
    if (id === 'daily') daily.activate(params); else if (shown === 'daily') daily.deactivate();
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
  }
  window.addEventListener('hashchange', () => show(true));
  show(false);
  document.documentElement.classList.add('ready');
  if (new URLSearchParams(location.search).has('debug')) window.__app = { fmt, overview };
}

boot();
