// Operators and Companies: filterable, sortable tables with CSV export and deep links (ported from v1, then extended).
import { $, el, fmt, fmtDate, halves, load, loadOpt, toObjects, once, parseHash, replaceHash, monthLabel } from './util.js';
import { spark, delta } from './charts.js';
import { getGeo, getPoints, getZips, countyAt } from './geo.js';
import { shareButton, absoluteLink } from './ui.js';

const BAND_ORDER = { A: 0, B: 1, C: 2, D: 3, '': 4 };
const BAND_TITLES = {
  A: '10 or more new-well permits in the last 12 months', B: '1 to 9 new-well permits in the last 12 months',
  C: 'RRC operator with no new-well permit in the last 12 months', D: 'No RRC match', '': 'Not ranked',
};
const TYPE_SHORT = { LLC: 'LLC', corporation: 'Corp', 'limited partnership': 'LP' };
const ROLE_LABELS = {
  'OPRS/O': 'Oil operator', 'OPRS/G': 'Gas operator', 'G/PUR': 'Gas purchaser', 'GTHS/G': 'Gas gatherer',
  'GTHS/O': 'Oil gatherer', 'GTHS/C': 'Condensate gatherer', 'CSGD/G': 'Casinghead gas gatherer',
  'CSGD/P': 'Casinghead purchaser', 'G/NOM': 'Gas nominator',
};
const SPECIALTY_LABELS = {
  DIRSUR: 'Directional surveying', GASPLT: 'Gas plant', OILNOM: 'Crude oil nominator', 'PIPE-A': 'Pipeline affiliate',
  'PIPE-L': 'Pipeline operator', PLUGGR: 'Plugging cementer', RECLPL: 'Reclaiming plant', REFINE: 'Refinery',
  RESPIT: 'Reserve pit cleaner', SWDP18: 'Skim oil recovery', SWHAUL: 'Salt water hauler', TRANSP: 'Crude or condensate transport',
};
const MATCH_LABELS = { exact: 'exact name', prefix: 'name prefix', 'fuzzy+zip': 'similar name, same ZIP' };

const bandLabel = (band) => (band === 'D' ? 'No RRC match' : band ? 'Band ' + band : 'Not ranked');
function chip(band) {
  const ranked = band && band !== 'D';
  return el('span', { class: 'chip ' + (ranked ? band.toLowerCase() : 'none'), text: ranked ? band : '–', title: BAND_TITLES[band] || '', 'aria-label': bandLabel(band) });
}
const place = (r) => [r.city, r.state].filter(Boolean).join(', ');
function roleList(r) {
  const out = [];
  r.roles.split(',').forEach((c) => { const l = ROLE_LABELS[c]; if (l && !out.includes(l)) out.push(l); });
  r.specialties.split(',').forEach((c) => { const l = SPECIALTY_LABELS[c]; if (l && !out.includes(l)) out.push(l); });
  return out.sort((a, b) => (/operator/.test(a) ? 0 : 1) - (/operator/.test(b) ? 0 : 1));
}
const roleText = (r) => roleList(r).join(', ');
const tag = (text) => el('span', { class: 'tag', text });
const mapLink = (href, label) => el('a', { class: 'pill-link', href, 'aria-label': label, title: label, text: 'Map' });

export function explorer(cfg, meta) {
  const root = $(cfg.root);
  const state = { rows: [], q: '', values: {}, sortKey: null, dir: 1, limit: 100, view: [] };
  const inputs = {}; let loaded = false; let pending = {};

  const search = el('input', { type: 'search', class: 'input', placeholder: cfg.placeholder, 'aria-label': 'Search' });
  const controls = [el('label', { class: 'field grow' }, el('span', { class: 'field-label', text: 'Search' }), search)];
  const optionNodes = (f) => f.options.map(([v, t]) => el('option', { value: v, text: t }));
  cfg.filters.forEach((f) => {
    state.values[f.id] = f.initial;
    if (f.type === 'select') {
      const sel = el('select', { class: 'input' }, optionNodes(f));
      sel.value = f.initial; inputs[f.id] = sel;
      sel.addEventListener('change', () => { state.values[f.id] = sel.value; refresh(); });
      controls.push(el('label', { class: 'field' }, el('span', { class: 'field-label', text: f.label }), sel));
    } else {
      const box = el('input', { type: 'checkbox' });
      box.checked = Boolean(f.initial); inputs[f.id] = box;
      box.addEventListener('change', () => { state.values[f.id] = box.checked; refresh(); });
      controls.push(el('label', { class: 'check' }, box, el('span', { text: f.label })));
    }
  });

  const ths = cfg.cols.map((c) => {
    const th = el('th', { scope: 'col', class: c.align === 'right' ? 'num' : '', title: c.hint });
    if (c.sort) {
      const first = c.desc ? -1 : 1;
      const b = el('button', { type: 'button', class: 'sort', text: c.label });
      b.addEventListener('click', () => {
        if (state.sortKey !== c.key) { state.sortKey = c.key; state.dir = first; }
        else if (state.dir === first) state.dir = -first;
        else { state.sortKey = null; state.dir = 1; }
        refresh();
      });
      th.append(b);
    } else th.textContent = c.label;
    return th;
  });
  const tbody = el('tbody');
  const status = el('p', { class: 'status', 'aria-live': 'polite', text: 'Loading…' });
  const empty = el('p', { class: 'empty', text: 'No rows match these filters.', hidden: true });
  const more = el('button', { type: 'button', class: 'btn', hidden: true });
  const csvBtn = el('button', { type: 'button', class: 'btn', disabled: true, text: 'Download CSV' });
  const shareBtn = shareButton(() => absoluteLink('#' + cfg.view + (serialize().toString() ? '?' + serialize().toString().replace(/%2C/g, ',') : '')));
  const table = el('table', { class: 'grid' }, el('caption', { class: 'sr-only', text: cfg.caption }), el('thead', {}, el('tr', {}, ths)), tbody);
  const wrap = el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': cfg.caption }, table);
  root.append(el('div', { class: 'filters' }, controls), status, wrap, empty, el('div', { class: 'actions' }, more, csvBtn, shareBtn));

  function compute() {
    const terms = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let rows = state.rows.filter((r) => terms.every((t) => r._q.includes(t)) && cfg.filters.every((f) => f.test(r, state.values[f.id])));
    if (state.sortKey) {
      const c = cfg.cols.find((x) => x.key === state.sortKey);
      const keyed = rows.map((r) => [c.sort(r), r]);
      const have = keyed.filter((k) => k[0] != null).sort((a, b) => {
        const cmp = a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;
        return cmp ? cmp * state.dir : a[1]._i - b[1]._i;
      });
      // rows with no value (for example operators with no extras) always sort last, never as zero
      rows = have.concat(keyed.filter((k) => k[0] == null)).map((k) => k[1]);
    }
    state.view = rows;
  }
  function render() {
    if (!loaded) return;
    const total = state.rows.length; const n = state.view.length; const shown = Math.min(n, state.limit);
    status.textContent = (n === total ? fmt.format(n) + ' rows' : fmt.format(n) + ' of ' + fmt.format(total) + ' rows match')
      + (n > shown ? ', showing the first ' + fmt.format(shown) : '') + (cfg.note ? cfg.note(state.values) : '');
    tbody.replaceChildren(...state.view.slice(0, shown).map((r) => el('tr', {}, cfg.cols.map((c) => {
      const cls = [c.align === 'right' ? 'num' : '', c.cls || ''].filter(Boolean).join(' ');
      return el('td', { class: cls }, c.render(r));
    }))));
    empty.hidden = n !== 0; more.hidden = n <= shown;
    more.textContent = 'Show ' + fmt.format(Math.min(100, n - shown)) + ' more';
    csvBtn.disabled = n === 0; csvBtn.textContent = 'Download CSV (' + fmt.format(n) + ' rows)';
    ths.forEach((th, i) => {
      if (!cfg.cols[i].sort) return;
      const on = state.sortKey === cfg.cols[i].key;
      th.setAttribute('aria-sort', on ? (state.dir === 1 ? 'ascending' : 'descending') : 'none');
    });
  }
  // the current search, filters and sort as link parameters (defaults left out), so a shared link reopens this exact view
  function serialize() {
    const p = new URLSearchParams();
    if (state.q.trim()) p.set('q', state.q.trim());
    cfg.filters.forEach((f) => {
      const v = state.values[f.id];
      if (f.type === 'check') { if (v) p.set(f.id, '1'); } else if (v !== f.initial && v != null) p.set(f.id, v);
    });
    if (state.sortKey) { p.set('sort', state.sortKey); p.set('dir', state.dir === 1 ? 'asc' : 'desc'); }
    return p;
  }
  function syncUrl() { if (loaded && parseHash().view === cfg.view) replaceHash(cfg.view, serialize()); }
  function refresh() { compute(); state.limit = 100; render(); syncUrl(); }

  let timer = 0;
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { state.q = search.value; refresh(); }, 150); });
  more.addEventListener('click', () => { state.limit += 100; render(); });
  // a name that starts with = + - or @ would run as a formula in a spreadsheet, so defuse it
  const csvCell = (v) => {
    let s = v == null ? '' : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  csvBtn.addEventListener('click', () => {
    const lines = [cfg.csv.map((c) => c[0]).join(',')].concat(state.view.map((r) => cfg.csv.map((c) => csvCell(c[1](r))).join(',')));
    const url = URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' }));
    const link = el('a', { href: url, download: cfg.csvName + '-' + meta.built + '.csv' });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  function setFilter(f, v) {
    state.values[f.id] = v;
    if (f.type === 'select') inputs[f.id].value = v; else inputs[f.id].checked = Boolean(v);
  }
  return {
    setRows(rows) {
      rows.forEach((r) => { r._q = cfg.text(r).toLowerCase(); });
      state.rows = rows; loaded = true; refresh();
    },
    fail(message) { status.textContent = message; },
    // options that arrive after the rows (the county list), applied to a link that named one before they were known
    setOptions(id, options) {
      const f = cfg.filters.find((q) => q.id === id);
      f.options = options; inputs[id].replaceChildren(...optionNodes(f));
      const want = pending[id] != null ? pending[id] : state.values[id];
      setFilter(f, options.some((o) => o[0] === want) ? want : f.initial);
      delete pending[id];
      if (loaded) refresh();
    },
    // restart from the default filters, then apply the ones named in a link's query (filter ids, plus q for search)
    apply(params) {
      search.value = params.get('q') || ''; state.q = search.value; state.sortKey = null; state.dir = 1; pending = {};
      cfg.filters.forEach((f) => {
        let v = f.initial;
        if (params.has(f.id)) {
          const raw = params.get(f.id);
          if (f.type === 'check') v = raw === '1';
          else if (f.options.some((o) => o[0] === raw)) v = raw;
          else if (f.lazy) pending[f.id] = raw;
        }
        setFilter(f, v);
      });
      const col = params.has('sort') ? cfg.cols.find((c) => c.key === params.get('sort') && c.sort) : null;
      if (col) { state.sortKey = col.key; state.dir = params.get('dir') === 'asc' ? 1 : params.get('dir') === 'desc' ? -1 : (col.desc ? -1 : 1); }
      refresh();
    },
    // retitle a column once its data window is known (for example the newest complete production month)
    relabel(key, text, hint) {
      const i = cfg.cols.findIndex((c) => c.key === key); if (i < 0) return;
      cfg.cols[i].label = text; if (hint) { cfg.cols[i].hint = hint; ths[i].title = hint; }
      const b = ths[i].querySelector('.sort'); if (b) b.textContent = text; else ths[i].textContent = text;
    },
    // remove columns (and their CSV fields) a missing optional file cannot fill; also hides a filter that depends on it
    dropCols(keys, csvNames = [], filterIds = []) {
      keys.forEach((k) => { const i = cfg.cols.findIndex((c) => c.key === k); if (i >= 0) { cfg.cols.splice(i, 1); ths.splice(i, 1); } });
      cfg.csv = cfg.csv.filter((c) => !csvNames.includes(c[0]));
      $('thead tr', table).replaceChildren(...ths);
      filterIds.forEach((id) => { const idx = cfg.filters.findIndex((f) => f.id === id); if (idx >= 0) { inputs[id].closest('label').hidden = true; cfg.filters.splice(idx, 1); delete state.values[id]; } });
    },
  };
}

/* operators */
function trendCell(r) {
  if (!r.x) return null;
  const h = r.h;
  const title = fmt.format(h.a) + ' permits in the last 12 full months against ' + fmt.format(h.b) + ' in the 12 before';
  if (h.f === Infinity) return el('span', { class: 'delta up', title }, el('span', { class: 'arrow', 'aria-hidden': 'true', text: '▲' }), el('span', { text: 'new' }));
  const d = delta(h.f); d.setAttribute('title', title);
  return d;
}
function prodTrendCell(r) {
  const p = r.p;
  if (!p || (p.o12 === 0 && p.o12p === 0)) return null;
  const f = p.o12p > 0 ? p.o12 / p.o12p - 1 : Infinity;
  const title = fmt.format(p.o12) + ' barrels in the latest 12 months against ' + fmt.format(p.o12p) + ' in the 12 before';
  const chip = f === Infinity ? el('span', { class: 'delta up', title }, el('span', { class: 'arrow', 'aria-hidden': 'true', text: '▲' }), el('span', { text: 'new' })) : delta(f);
  if (f !== Infinity) chip.setAttribute('title', title);
  return el('span', { class: 'cell-prod' }, chip, spark(p.mo, { w: 64, h: 22, color: 'var(--s3)', base: 'min', label: 'Monthly oil, last ' + p.mo.length + ' months' }));
}
function operatorNotes(r) {
  const frag = document.createDocumentFragment();
  if (r.newDrill) frag.append(tag('New to drilling'));
  if (r.newP5) frag.append(tag('New P-5'));
  const roles = roleList(r);
  if (roles.length) {
    const extra = roles.length - 3;
    frag.append(el('span', { class: 'note', title: roles.join(', '), text: roles.slice(0, 3).join(', ') + (extra > 0 ? ' +' + extra + ' more' : '') }));
  }
  return frag;
}
function operatorsConfig(ctx) {
  const cname = (f) => (ctx.G && ctx.G.byFips.has(f) ? ctx.G.byFips.get(f).n : '');
  return {
    root: '#ops-root', view: 'operators', caption: 'Operators', csvName: 'operators', placeholder: 'Search name, city, ZIP or operator number',
    note: (v) => (v.top ? '. Top 100 by oil among the operators listed here; some of the largest producers hold expired registrations, so they show on the Overview but not on this page.' : ''),
    text: (r) => [r.name, r.city, r.state, r.zip, r.num].join(' '),
    cols: [
      { key: 'band', label: 'Band', hint: 'Drilling activity band', render: (r) => chip(r.band), sort: (r) => BAND_ORDER[r.band] },
      {
        key: 'name', label: 'Operator', cls: 'name', sort: (r) => r.name.toLowerCase(),
        render: (r) => el('span', { class: 'op-name' }, r.name, ctx.hasPts.has(r.num) ? mapLink('#map?op=' + r.num, 'Show ' + r.name + ' on the map') : null),
      },
      { key: 'type', label: 'Type', render: (r) => TYPE_SHORT[r.type] || r.type, sort: (r) => r.type },
      { key: 'loc', label: 'Location', cls: 'loc', render: place, sort: (r) => (r.state + r.city).toLowerCase() },
      { key: 'new12', label: 'New wells (12 mo)', align: 'right', desc: true, render: (r) => fmt.format(r.new12), sort: (r) => r.new12 },
      {
        key: 'trend', label: 'Trend', hint: 'Permits in the last 12 full calendar months against the 12 before. "new" means none in the prior 12.',
        cls: 'trend', render: trendCell, desc: true, sort: (r) => (r.x && r.h.f != null ? (r.h.f === Infinity ? 1e9 : r.h.f) : null),
      },
      { key: 'm24', label: '24 months', hint: 'Monthly new-drill permits, last 24 full months', render: (r) => (r.x ? spark(r.x.m24, { w: 84, h: 24, label: 'Monthly new-drill permits, last 24 months' }) : null) },
      {
        key: 'oil12', label: 'Oil (12 mo)', hint: 'Crude oil plus condensate in barrels reported to the RRC over the latest 12 complete months. Blank: no production figure for this operator.',
        align: 'right', desc: true, render: (r) => (r.p ? fmt.format(r.p.o12) : null), sort: (r) => (r.p ? r.p.o12 : null),
      },
      {
        key: 'gas12', label: 'Gas (12 mo)', hint: 'Gas-well plus casinghead gas in mcf over the same 12 months. Blank: no production figure.',
        align: 'right', desc: true, render: (r) => (r.p ? fmt.format(r.p.g12) : null), sort: (r) => (r.p ? r.p.g12 : null),
      },
      {
        key: 'ptrend', label: 'Production trend', hint: 'Oil over the latest 12 months against the 12 before, with a 24-month line. "new" means none before.', cls: 'trend', desc: true,
        render: prodTrendCell, sort: (r) => (r.p && (r.p.o12 || r.p.o12p) ? (r.p.o12p > 0 ? r.p.o12 / r.p.o12p - 1 : 1e9) : null),
      },
      { key: 'all12', label: 'Permits (12 mo)', align: 'right', desc: true, render: (r) => fmt.format(r.all12), sort: (r) => r.all12 },
      { key: 'all24', label: 'Permits (24 mo)', align: 'right', desc: true, render: (r) => fmt.format(r.all24), sort: (r) => r.all24 },
      {
        key: 'spud', label: 'Spud (12 mo)', hint: 'New-drill permits whose reported spud date falls in the last 12 months', align: 'right', desc: true,
        render: (r) => (r.x ? fmt.format(r.x.spud12) : ''), sort: (r) => (r.x ? r.x.spud12 : null),
      },
      {
        key: 'depth', label: 'Avg depth (ft)', hint: 'Mean total depth of permits in the last 24 months', align: 'right', desc: true,
        render: (r) => (r.x && r.x.depth ? fmt.format(r.x.depth) : ''), sort: (r) => (r.x && r.x.depth ? r.x.depth : null),
      },
      {
        key: 'county', label: 'Top county', hint: 'County with the most of its permits in the last 24 months', cls: 'loc',
        render: (r) => (!r.x ? null : r.x.fips && cname(r.x.fips) ? el('a', { href: '#map?county=' + r.x.fips, text: cname(r.x.fips) }) : 'n/a'),
        sort: (r) => (r.x ? (r.x.fips ? cname(r.x.fips).toLowerCase() : '￿') : null),
      },
      { key: 'last', label: 'Last permit', cls: 'loc', desc: true, render: (r) => fmtDate(r.last), sort: (r) => r.last },
      { key: 'dist', label: 'District', hint: 'RRC district with the most permits in 24 months', render: (r) => r.dist, sort: (r) => r.dist },
      { key: 'notes', label: 'Notes', cls: 'notes', render: operatorNotes },
    ],
    filters: [
      {
        id: 'band', type: 'select', label: 'Band', initial: 'abc',
        options: [['abc', 'Bands A to C'], ['ab', 'Bands A and B'], ['A', 'Band A'], ['B', 'Band B'], ['C', 'Band C'], ['all', 'All registrants']],
        test: (r, v) => (v === 'all' ? true : v === 'abc' ? r.band !== '' : v === 'ab' ? r.band === 'A' || r.band === 'B' : r.band === v),
      },
      { id: 'op', type: 'check', label: 'Oil or gas operators only', initial: false, test: (r, v) => !v || r.roles.includes('OPRS') },
      { id: 'newDrill', type: 'check', label: 'New to drilling', initial: false, test: (r, v) => !v || r.newDrill === 1 },
      { id: 'newP5', type: 'check', label: 'New P-5', initial: false, test: (r, v) => !v || r.newP5 === 1 },
      { id: 'top', type: 'check', label: 'Top producers (100 largest by oil)', initial: false, test: (r, v) => !v || (r.p && r.p.rank != null && r.p.rank <= 100) },
    ],
    csv: [
      ['band', (r) => r.band], ['operator_number', (r) => r.num], ['name', (r) => r.name], ['type', (r) => r.type],
      ['city', (r) => r.city], ['state', (r) => r.state], ['zip', (r) => r.zip],
      ['new_well_permits_12m', (r) => r.new12], ['all_permits_12m', (r) => r.all12], ['all_permits_24m', (r) => r.all24],
      ['last_permit_date', (r) => r.last], ['top_district_24m', (r) => r.dist], ['roles', roleText],
      ['new_to_drilling', (r) => (r.newDrill ? 'Y' : '')], ['new_p5_24m', (r) => (r.newP5 ? 'Y' : '')],
      ['new_well_permits_prior_12m', (r) => (r.x ? r.x.prev12 : '')],
      ['permits_last_12_full_months', (r) => (r.x ? r.h.a : '')], ['permits_prior_12_full_months', (r) => (r.x ? r.h.b : '')],
      ['trend_pct_full_months', (r) => (!r.x || r.h.f == null ? '' : r.h.f === Infinity ? 'new' : Math.round(r.h.f * 1000) / 10)],
      ['spud_12m', (r) => (r.x ? r.x.spud12 : '')], ['avg_depth_ft_24m', (r) => (r.x && r.x.depth ? r.x.depth : '')],
      ['top_county_24m', (r) => (r.x && r.x.fips ? cname(r.x.fips) : '')], ['top_county_fips', (r) => (r.x ? r.x.fips : '')],
      ['counties_24m', (r) => (r.x ? r.x.counties : '')], ['on_map', (r) => (ctx.hasPts.has(r.num) ? 'Y' : '')],
      ['oil_bbl_12m', (r) => (r.p ? r.p.o12 : '')], ['gas_mcf_12m', (r) => (r.p ? r.p.g12 : '')],
      ['oil_bbl_prior_12m', (r) => (r.p ? r.p.o12p : '')], ['gas_mcf_prior_12m', (r) => (r.p ? r.p.g12p : '')],
      ['oil_trend_pct', (r) => (!r.p || (!r.p.o12 && !r.p.o12p) ? '' : r.p.o12p > 0 ? Math.round((r.p.o12 / r.p.o12p - 1) * 1000) / 10 : 'new')],
      ['producing_leases_12m', (r) => (r.p ? r.p.leases : '')], ['top_producer_rank_oil', (r) => (r.p && r.p.rank != null ? r.p.rank : '')],
    ],
  };
}

/* companies */
function companyNotes(r) {
  const frag = document.createDocumentFragment();
  if (r.isNew) frag.append(tag('New entity'));
  if (r.match) frag.append(tag('RRC match: ' + (MATCH_LABELS[r.match] || r.match)));
  if (r.reason) frag.append(el('span', { class: 'note', text: r.reason }));
  return frag;
}
function companiesConfig(m, ctx) {
  const segments = [['all', 'All segments']].concat(m.companies.bySegment.map(([s]) => [s, s]));
  return {
    root: '#co-root', view: 'companies', caption: 'Companies', csvName: 'companies', placeholder: 'Search name, city, ZIP, segment or NAICS code',
    text: (r) => [r.name, r.city, r.state, r.zip, r.seg, r.naics, r.word].join(' '),
    note: (v) => (v.county !== 'all' ? '. County comes from the center of each ZIP code, so counts can differ from the map, which uses the Comptroller county code.' : ''),
    cols: [
      { key: 'name', label: 'Company', cls: 'name', render: (r) => r.name, sort: (r) => r.name.toLowerCase() },
      { key: 'seg', label: 'Segment', cls: 'seg', render: (r) => r.seg, sort: (r) => r.seg },
      {
        key: 'loc', label: 'Location', cls: 'loc', sort: (r) => (r.state + r.city).toLowerCase(),
        render: (r) => el('span', { class: 'op-name' }, place(r), r.state === 'TX' && ctx.zipSet.has(r.zip) ? mapLink('#map?zip=' + r.zip, 'Show ZIP ' + r.zip + ' on the map') : null),
      },
      {
        key: 'fit', label: 'Fit', hint: 'Likely: no warning signs. Check: verify first.', sort: (r) => (r.fit === 'likely' ? 0 : 1),
        render: (r) => el('span', { class: 'chip ' + (r.fit === 'likely' ? 'likely' : 'none'), text: r.fit === 'likely' ? 'Likely' : 'Check' }),
      },
      { key: 'band', label: 'RRC band', render: (r) => chip(r.band), sort: (r) => BAND_ORDER[r.band] },
      { key: 'new12', label: 'New wells (12 mo)', align: 'right', desc: true, render: (r) => fmt.format(r.new12), sort: (r) => r.new12 },
      { key: 'yrs', label: 'Years since charter', align: 'right', render: (r) => (r.yrs === '' ? '' : String(r.yrs)), sort: (r) => (r.yrs === '' ? 1e9 : Number(r.yrs)) },
      { key: 'notes', label: 'Notes', cls: 'notes', render: companyNotes },
    ],
    filters: [
      { id: 'seg', type: 'select', label: 'Segment', initial: 'all', options: segments, test: (r, v) => v === 'all' || r.seg === v },
      { id: 'fit', type: 'select', label: 'Fit', initial: 'all', options: [['all', 'Likely and check'], ['likely', 'Likely only']], test: (r, v) => v === 'all' || r.fit === v },
      { id: 'county', type: 'select', label: 'County (by ZIP)', initial: 'all', lazy: true, options: [['all', 'All counties']], test: (r, v) => v === 'all' || r.county === v },
      { id: 'tx', type: 'check', label: 'Texas addresses only', initial: false, test: (r, v) => !v || r.state === 'TX' },
      { id: 'isNew', type: 'check', label: 'New entity (24 mo)', initial: false, test: (r, v) => !v || r.isNew === 1 },
      { id: 'match', type: 'check', label: 'Matched to an RRC operator', initial: false, test: (r, v) => !v || r.match !== '' },
    ],
    csv: [
      ['fit', (r) => r.fit], ['fit_reason', (r) => r.reason], ['segment', (r) => r.seg], ['name', (r) => r.name],
      ['city', (r) => r.city], ['state', (r) => r.state], ['zip', (r) => r.zip], ['county_by_zip_center', (r) => r.countyName || ''],
      ['naics', (r) => r.naics], ['name_match', (r) => r.word], ['new_entity', (r) => (r.isNew ? 'Y' : '')], ['years_since_charter', (r) => r.yrs],
      ['rrc_band', (r) => r.band], ['new_well_permits_12m', (r) => r.new12], ['all_permits_12m', (r) => r.all12],
      ['rrc_match', (r) => r.match], ['rrc_operator_number', (r) => r.rrcNum],
    ],
  };
}

// each ZIP's center falls in one county: the County filter uses that, since company rows carry only a ZIP
const zipCounties = () => once('zipcounty', async () => {
  const [G, Z] = await Promise.all([getGeo(), getZips()]);
  const map = new Map();
  if (Z) for (const z of Z.list) { const i = countyAt(G, z.x, z.y); if (i >= 0) map.set(z.zip, G.counties[i]); }
  return { G, Z, map };
});

export function createTables(meta) {
  const ctx = { G: null, hasPts: new Set(), zipSet: new Set() };
  const operators = explorer(operatorsConfig(ctx), meta);
  const companies = explorer(companiesConfig(meta, ctx), meta);
  return {
    operators: {
      ex: operators,
      async load() {
        const [t, extras, G, pts, prod] = await Promise.all([load('operators'), loadOpt('operator-extras'), getGeo().catch(() => null), getPoints().catch(() => null), loadOpt('operator-production')]);
        ctx.G = G; ctx.hasPts = new Set(pts ? pts.pm.opNums : []);
        const by = new Map(extras ? toObjects(extras).map((r) => [r.num, r]) : []);
        // production by operator number, ranked by oil; an operator with no row here gets blank cells, never zeros
        const pb = new Map();
        if (prod && prod.rows) toObjects(prod).filter((r) => r.o12 + r.g12 > 0).forEach((r) => pb.set(r.num, r));
        const rows = toObjects(t);
        rows.forEach((r) => { r.x = by.get(r.num) || null; r.h = r.x ? halves(r.x.m24) : null; r.p = pb.get(r.num) || null; });
        // rank by oil among the operators this table lists
        rows.filter((r) => r.p && r.p.o12 > 0).sort((a, b) => b.p.o12 - a.p.o12).forEach((r, i) => { r.p.rank = i + 1; });
        if (prod && prod.months) {
          const end = monthLabel(prod.months[prod.months.length - 1]); const w = '12 months to ' + end + ', the newest complete months of RRC production reports';
          operators.relabel('oil12', 'Oil (12 mo to ' + end + ')', 'Crude oil plus condensate in barrels, ' + w + '. Blank: no production figure for this operator.');
          operators.relabel('gas12', 'Gas (12 mo to ' + end + ')', 'Gas-well plus casinghead gas in mcf, ' + w + '. Blank: no production figure.');
          operators.relabel('ptrend', 'Production trend', 'Oil in the ' + w + ', against the 12 months before, with the monthly line for the last ' + prod.months.length + ' months. A step is often an acquisition: production follows the operator of record. "new" means none in the 12 before.');
          const note = $('#ops-prod-note'); if (note) { note.textContent = ' Oil and gas figures are the ' + w + '; permits run to a later date.'; note.hidden = false; }
        }
        if (!pb.size) operators.dropCols(['oil12', 'gas12', 'ptrend'], ['oil_bbl_12m', 'gas_mcf_12m', 'oil_bbl_prior_12m', 'gas_mcf_prior_12m', 'oil_trend_pct', 'producing_leases_12m', 'top_producer_rank_oil'], ['top']);
        operators.setRows(rows);
      },
    },
    companies: {
      ex: companies,
      async load() {
        const [t, zc] = await Promise.all([load('companies'), zipCounties().catch(() => ({ map: new Map(), Z: null }))]);
        ctx.zipSet = new Set(zc.Z ? zc.Z.list.map((z) => z.zip) : []);
        const rows = toObjects(t); const used = new Map();
        rows.forEach((r) => {
          const c = zc.map.get(r.zip);
          r.county = c ? c.f : ''; r.countyName = c ? c.n : '';
          if (c) used.set(c.f, c.n);
        });
        companies.setRows(rows);
        companies.setOptions('county', [['all', 'All counties']].concat([...used].sort((a, b) => a[1].localeCompare(b[1])).map(([f, n]) => [f, n + ' County'])));
      },
    },
  };
}
