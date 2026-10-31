// Daily report: what the Railroad Commission's nightly datasets held, one report per day for the last 92 days.
// A simple version for the daily look and a verbose one with everything. Each block hides itself if its data is missing.
import { el, load, loadOpt, fmt, countUp, reduced } from './util.js';
import { getGeo } from './geo.js';
import { icon } from './icons.js';
import { segmented, shareButton, absoluteLink } from './ui.js';
import { spark, delta } from './charts.js';
import { opsLink } from './overview.js';
import { trendBars, countyMap, gpsMap, ribbon, calendar, ring, stack, histogram, rankList, isWeekend, fmtMd, fmtDow, fmtLong, addDays, mb } from './daily-viz.js';

const TITLES = { permits: 'Drilling permits', pending: 'Permits pending approval', completions: 'Completion data', w1images: 'W-1 permit images', dirsurveys: 'Directional surveys', complimages: 'Completion images' };
const ICONS = { permits: 'pin', pending: 'clock', completions: 'drop', w1images: 'layers', dirsurveys: 'rig', complimages: 'building' };
const WHAT = {
  permits: 'New permits issued, from the nightly Drilling Permit Master and Trailer file (daf420.dat).',
  pending: 'W-1 applications submitted and not yet approved, from the twice-daily pending set.',
  completions: 'Completion forms (W-2, G-1, P-4 and others) submitted or approved that day.',
  w1images: 'Zipped images of every W-1 approved that day, by RRC district. The size is captured; live days also count the documents, and the W-1 letters and plats of the day\'s new-drill permits are published for each drill\'s page.',
  dirsurveys: 'Zipped directional survey images submitted that day. The size is captured; live days also count the documents and publish the surveys, each with its own page.',
  complimages: 'Zipped completion form images. The size is captured; live days also count the documents.',
};
const KIND = { H: 'Horizontal', D: 'Directional', V: 'Vertical' };
const PERMIT_TYPE = { '01': 'New drill', '05': 'Other', '07': 'Re-entry', '09': 'Field transfer', '14': 'Recompletion', '15': 'Reclass' };
const num = (v) => fmt.format(v);
const strong = (t) => el('strong', { text: t });
const listed = (iso) => (iso ? new Date(iso + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }) : '—');
const central = (utc) => new Date(utc).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' }) + ' Central';
// 'first' means the previous report was not captured live, so there is nothing to compare a file with
const compare = (rep) => { const ds = rep.datasets; return { ok: ds.some((d) => d.state === 'new' || d.state === 'same'), fresh: ds.filter((d) => d.state === 'new').length, same: ds.filter((d) => d.state === 'same') }; };
const rel = (v, avg) => { const p = Math.round(Math.abs(v / avg - 1) * 100); return p < 3 ? 'in line with' : p + '% ' + (v > avg ? 'above' : 'below'); };

const METRICS = {
  permits: { label: 'New-drill permits issued', get: (r) => (r.pFresh ? r.pn : null), fmt: (v) => num(v) + ' new-drill permits issued', none: 'No permits issued (weekend or holiday)' },
  pending: { label: 'Waiting for approval', get: (r) => r.q, fmt: (v) => num(v) + ' applications waiting', none: 'No pending set recorded' },
  completions: { label: 'Completions approved', get: (r) => r.c, fmt: (v) => num(v) + ' completions approved', none: 'No completion file read' },
  volume: { label: 'Image pack volume', get: (r) => r.vol, fmt: (v) => Math.round(v) + ' MB of image packs', none: 'No pack sizes read' },
};

export function createDailyView({ root }) {
  const S = { index: null, series: null, G: null, rep: null, day: null, mode: 'simple', layer: 'permits', metric: 'permits', seq: 0, ready: false, sel: null, open: null, gpsEl: null };
  const h1 = el('h1', { id: 'dr-h1', class: 'dr-title', tabindex: '-1' });
  root.replaceChildren(h1, el('p', { class: 'empty', text: 'Loading the daily report…' }));

  /* ---------- data ---------- */
  async function boot() {
    const idx = await load('daily/index');
    idx.days.forEach((r, i) => {
      r.pFresh = i === 0 || r.dd !== idx.days[i - 1].dd;
      r.vol = [r.w1, r.ds, r.cm].some((v) => v != null) ? (r.w1 || 0) + (r.ds || 0) + (r.cm || 0) : null;
    });
    S.index = idx;
    [S.series, S.G] = await Promise.all([loadOpt('daily/permits-series'), getGeo().catch(() => null)]);
    S.ready = true;
  }
  const countyName = (f) => (S.G && S.G.byFips.get(f) ? S.G.byFips.get(f).n : f || 'Unknown');

  // the last `count` business days of new-drill permits up to and including `until`
  function biz(until, count) {
    const s = S.series; const out = { days: [], total: [], horiz: [] };
    if (!s) return out;
    for (let i = s.days.length - 1; i >= 0 && out.days.length < count; i--) {
      if (s.days[i] > until || isWeekend(s.days[i])) continue;
      out.days.unshift(s.days[i]); out.total.unshift(s.newDrill[i]); out.horiz.unshift(s.horizontal[i]);
    }
    return out;
  }
  // average of the 20 business days before `day`, leaving out weekdays with no permits at all (holidays)
  function avgBefore(day, n = 20) {
    const s = S.series; const v = [];
    if (!s) return null;
    for (let i = s.days.length - 1; i >= 0 && v.length < n; i--) {
      if (s.days[i] >= day || isWeekend(s.days[i]) || !s.total[i]) continue;
      v.push(s.newDrill[i]);
    }
    return v.length >= 5 ? v.reduce((a, x) => a + x, 0) / v.length : null;
  }
  function monthToDate(day) {
    const s = S.series;
    if (!s) return null;
    const ym = day.slice(0, 7); const dd = day.slice(8);
    const prevYm = addDays(ym + '-01', -1).slice(0, 7);
    let a = 0; let b = 0; let haveFirst = false;
    s.days.forEach((d, i) => {
      if (d.slice(0, 7) === ym && d <= day) a += s.newDrill[i];
      if (d.slice(0, 7) === prevYm && d.slice(8) <= dd) b += s.newDrill[i];
      if (d === prevYm + '-01') haveFirst = true;
    });
    return { a, b: haveFirst ? b : null, ym, prevYm };
  }
  const tally = (rows, i) => { const m = new Map(); rows.forEach((r) => { if (r[i]) m.set(r[i], (m.get(r[i]) || 0) + 1); }); return m; };

  /* ---------- small builders ---------- */
  const card = (cls, ...kids) => el('section', { class: 'card dr-card ' + cls }, ...kids);
  const head = (ic, eyebrow, title, sub) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null));
  const tiles = (items) => el('dl', { class: 'dr-tiles' }, items.filter(Boolean).map((t) => el('div', { class: 'dr-tile' }, el('dt', { text: t.label }), el('dd', { text: t.value }), t.note ? el('small', { text: t.note }) : null)));
  const table = (cols, rows, { cap = 'dr-table' } = {}) => el('div', { class: 'table-wrap ' + cap },
    el('table', { class: 'grid' }, el('thead', {}, el('tr', {}, cols.map((c) => el('th', { scope: 'col', class: c.num ? 'num' : null, text: c.t })))),
      el('tbody', {}, rows.map((r) => el('tr', {}, r.map((v, i) => el('td', { class: cols[i].num ? 'num' : null }, v == null ? '—' : v)))))));
  const chip = (cls, text) => el('span', { class: 'dr-pill ' + cls }, el('i', { class: 'dr-led' }), text);
  const opNode = (op, name) => (name ? el('a', { href: opsLink(name), text: name }) : el('span', { class: 'muted', text: 'Operator #' + op }));
  const opItems = (list) => list.map(([op, name, n]) => ({ label: name || 'Operator #' + op, value: n, href: name ? opsLink(name) : null }));
  const countyItems = (list) => list.map(([f, name, n]) => ({ label: name, value: n }));

  /* ---------- header, ribbon, KPIs ---------- */
  function hero(rep) {
    const days = S.index.days; const i = days.findIndex((r) => r.d === rep.date);
    const live = rep.kind === 'live';
    const read = rep.datasets.filter((d) => !d.error).length; const cmp = compare(rep);
    const status = live ? (rep.status === 'ok' ? 'good' : rep.status === 'partial' ? 'warn' : 'bad') : 'info';
    const pills = [chip(status, live ? read + ' of ' + rep.datasets.length + ' nightly files read' : 'Reconstructed from RRC file history')];
    if (live && rep.capturedAt) pills.push(chip('quiet', 'Captured ' + central(rep.capturedAt)));
    if (live && cmp.ok && cmp.fresh) pills.push(chip('quiet', cmp.fresh + ' updated since the last report'));
    if (live && !cmp.ok) pills.push(chip('quiet', 'First live capture'));
    const step = (n) => go(days[i + n].d, S.mode);
    const nav = el('div', { class: 'dr-nav' },
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'earlier', disabled: i === 0, 'aria-label': 'Earlier day', onclick: () => step(-1) }, icon('arrow', 14, 'flip'), 'Earlier'),
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'later', disabled: i === days.length - 1, 'aria-label': 'Later day', onclick: () => step(1) }, 'Later', icon('arrow', 14)),
      i === days.length - 1 ? null : el('button', { type: 'button', class: 'btn sm primary', 'data-act': 'latest', onclick: () => go(days[days.length - 1].d, S.mode) }, 'Latest'),
      shareButton(() => absoluteLink(location.hash || '#daily'), 'Copy link'));
    const seg = segmented({ label: 'Report version', options: [{ id: 'simple', label: 'Simple' }, { id: 'full', label: 'Verbose' }], value: S.mode, tabs: false, prefix: 'drv', onChange: (id) => go(S.day, id) });
    h1.textContent = fmtLong(rep.date).replace(/, \d{4}$/, '');
    return el('header', { class: 'dr-hero' },
      el('div', { class: 'dr-radar', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')),
      el('div', { class: 'dr-hero-in' },
        el('p', { class: 'eyebrow' }, el('span', { class: 'live-dot', 'aria-hidden': 'true' }), 'Daily Railroad Commission report · ', el('span', { text: rep.date.slice(0, 4) })),
        h1,
        el('p', { class: 'dr-lede', text: S.mode === 'simple'
          ? 'The daily look: what the Railroad Commission published overnight, in a minute.'
          : 'Everything the Railroad Commission lists as nightly or twice daily, captured and read.' }),
        el('div', { class: 'dr-pills' }, pills)),
      el('div', { class: 'dr-controls' }, seg.el, nav));
  }

  function ribbonCard() {
    const rb = ribbon({ days: S.index.days, selected: S.day, onPick: (d) => go(d, S.mode) });
    S.rb = rb; // positioned again once it is in the page, so a phone opens on the selected day
    return card('dr-ribbon-card', el('div', { class: 'dr-ribbon-head' }, el('p', { class: 'eyebrow' }, icon('calendar', 15), 'Last 3 months'),
      el('small', { text: 'One bar per report day. Height is the new-drill permits issued that business day; weekends have none.' })), rb.el);
  }

  function kpi({ ic, label, value, note, extra, vals, color, hero: big, gauge }) {
    const n = el('strong', { class: 'dr-kpi-num' });
    const c = el('div', { class: 'dr-kpi' + (big ? ' lead' : '') },
      el('div', { class: 'dr-kpi-top' }, icon(ic, 16), el('span', { text: label })),
      gauge ? el('div', { class: 'dr-kpi-gauge' }, gauge) : n,
      note ? el('div', { class: 'dr-kpi-note' }, note) : null,
      extra ? el('div', { class: 'dr-kpi-extra' }, extra) : null,
      vals && vals.length > 3 ? el('div', { class: 'dr-kpi-spark' }, spark(vals, { w: 160, h: 34, color, label: label + ', recent days' })) : null);
    c.style.setProperty('--kc', color);
    if (value == null) n.textContent = '—'; else countUp(n, value);
    return c;
  }
  function kpiRow(rep) {
    const p = rep.permits; const q = rep.pending; const c = rep.completions;
    const avg = p ? avgBefore(p.day) : null; const bs = p ? biz(p.day, 20) : { total: [] };
    const cut = S.index.days.findIndex((r) => r.d === rep.date);
    const hist = (key) => S.index.days.slice(Math.max(0, cut - 29), cut + 1).map((r) => r[key]).filter((v) => v != null);
    const live = rep.kind === 'live';
    const read = rep.datasets.filter((d) => !d.error).length; const cmp = compare(rep); const cmpOk = live && cmp.ok;
    return el('div', { class: 'dr-kpis' },
      kpi({ ic: 'pin', label: 'New-drill permits issued', value: p && p.newDrill, hero: true, color: 'var(--s2)', vals: bs.total,
        note: p ? fmtDow(p.day) + ' · ' + num(p.total) + ' permits of all types' : 'No permit file was read for this day',
        extra: p && avg ? [delta((p.newDrill - avg) / avg), ' vs the 20-day average of ' + Math.round(avg)] : null }),
      kpi({ ic: 'clock', label: 'Waiting for approval', value: q && q.total, color: 'var(--s1)', vals: hist('q'),
        note: q ? num(q.expedite) + ' expedited · ' + num(q.horizontal) + ' horizontal' : 'No pending set recorded for this day' }),
      kpi({ ic: 'drop', label: 'Completions approved', value: c && c.approved, color: 'var(--s3)', vals: hist('c'),
        note: c ? num(c.initial) + ' first tests of new wells · ' + fmtDow(c.day) : 'No completion file for this day' }),
      kpi({ ic: 'check', label: cmpOk ? 'Nightly files updated' : 'Nightly files read', value: cmpOk ? cmp.fresh : read, color: 'var(--accent)', gauge: ring(cmpOk ? cmp.fresh : read, rep.datasets.length),
        note: cmpOk ? (cmp.fresh === rep.datasets.length ? 'Every dataset changed since the last report' : num(cmp.same.length) + ' unchanged since the last report')
          : live ? 'First live capture: changes show from the next report' : 'Rebuilt from the RRC file history' }));
  }

  /* ---------- permits per day and the map ---------- */
  function trendCard(rep) {
    const p = rep.permits;
    const bs = p ? biz(p.day, 30) : null;
    if (!p || !bs || bs.days.length < 5) return null;
    const avg = avgBefore(p.day);
    return card('dr-trend', head('trend', 'Pace', 'New-drill permits per business day', 'Last 30 business days to ' + fmtMd(p.day) + '. Holidays show as empty days.'),
      el('div', { class: 'dr-legend-inline' }, el('i', { class: 'dr-dot horiz' }), el('span', { text: 'Horizontal' }), el('i', { class: 'dr-dot rest' }), el('span', { text: 'Other' })),
      trendBars({ days: bs.days, total: bs.total, horiz: bs.horiz, avg, label: 'Bar chart of new-drill permits per business day from ' + fmtMd(bs.days[0]) + ' to ' + fmtMd(p.day) + '. ' + fmtDow(p.day) + ' had ' + p.newDrill + (avg ? ', against an average of ' + Math.round(avg) : '') + '.' }));
  }

  function mapCard(rep) {
    const layers = {}; const defs = [];
    if (rep.permits) { layers.permits = { map: tally(rep.permits.rows, 1) }; defs.push({ id: 'permits', label: 'Issued' }); }
    if (rep.pending) { layers.pending = { map: tally(rep.pending.rows, 2) }; defs.push({ id: 'pending', label: 'Waiting' }); }
    if (rep.completions) { layers.completions = { map: new Map(rep.completions.counties.map((x) => [x[0], x[2]])) }; defs.push({ id: 'completions', label: 'Completions' }); }
    if (!defs.length) return null;
    if (!layers[S.layer]) S.layer = defs[0].id;
    const colors = { permits: 'var(--s2)', pending: 'var(--s1)', completions: 'var(--s3)' };
    const names = { permits: 'new-drill permits issued', pending: 'applications waiting for approval', completions: 'completions approved' };
    const list = el('div', { class: 'dr-maplist' });
    const wrap = el('div', { class: 'dr-mapwrap' });
    const map = S.G ? countyMap(S.G, layers, S.layer) : null;
    if (map) wrap.append(map.el);
    const paint = () => {
      wrap.style.setProperty('--lc', colors[S.layer]);
      const top = [...layers[S.layer].map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
      list.replaceChildren(el('p', { class: 'dr-maplist-h', text: 'Top counties · ' + names[S.layer] }),
        rankList(top.map(([f, n]) => ({ label: countyName(f), value: n })), { color: colors[S.layer], empty: 'No county detail for this layer.' }));
    };
    const seg = segmented({ label: 'Map layer', options: defs, value: S.layer, tabs: false, prefix: 'drm', onChange: (id) => { S.layer = id; if (map) map.set(id); paint(); } });
    paint();
    return card('dr-mapcard', head('pin', 'Where', 'Texas, by county', 'Bubbles grow with the count; hover a county for its number.'), el('div', { class: 'dr-maptools' }, seg.el), wrap, list);
  }

  /* ---------- the GPS map, and a page (a URL) for each well with its filings ---------- */
  const fmtApi = (a) => '42-' + a.slice(0, 3) + '-' + a.slice(3); // state 42, county, well
  const hashFor = (day, mode, sel) => {
    const q = new URLSearchParams();
    if (day !== S.index.days[S.index.days.length - 1].d) q.set('d', day);
    if (mode === 'full') q.set('v', 'full');
    if (sel) q.set(sel.t === 'p' ? 'drill' : 'survey', sel.id);
    return '#daily' + (q.toString() ? '?' + q : '');
  };
  // the release a report links to is validated before it becomes a link: names come from a data file
  const relOk = (r) => !!r && /^[\w.-]+\/[\w.-]+$/.test(r.repo) && /^daily-\d{4}-\d\d-\d\d$/.test(r.tag);
  const fileUrl = (rep, name) => (relOk(rep.release) && /^[\w.-]+$/.test(name) ? 'https://github.com/' + rep.release.repo + '/releases/download/' + rep.release.tag + '/' + name : null);
  const releaseUrl = (rep) => (relOk(rep.release) ? 'https://github.com/' + rep.release.repo + '/releases/tag/' + rep.release.tag : null);
  const gpsText = (lat, lon) => lat.toFixed(5) + ', ' + lon.toFixed(5);
  const mapsUrl = (lat, lon) => 'https://www.google.com/maps/search/?api=1&query=' + lat.toFixed(5) + ',' + lon.toFixed(5);
  function docLabel(suffix) {
    const m = /^(W1|Plat)(?:_(\d+))?\.(\w+)$/.exec(suffix);
    if (!m) return { label: 'Document', type: '' };
    return { label: (m[1] === 'W1' ? 'Approved W-1 permit' : 'Permit plat') + (m[2] ? ' ' + m[2] : ''), type: m[3].toUpperCase() };
  }
  const docList = (items) => el('ul', { class: 'dr-docs' }, items.map((d) => el('li', {}, d.href
    ? el('a', { class: 'btn dr-doc', href: d.href, rel: 'noopener noreferrer' }, icon('layers', 15), el('span', { text: d.label }), d.type ? el('small', { text: d.type }) : null)
    : el('span', { class: 'dr-doc off', text: d.label }))));

  function drillPanel(rep, sel, { close }) {
    const pr = rep.permits; const sv = rep.surveys;
    const row = sel.t === 'p' && pr ? pr.rows.find((r) => r[0] === sel.id) : null;
    const srow = sel.t === 's' && sv ? sv.rows.find((r) => r[8] === sel.id) : null;
    const closeBtn = el('button', { type: 'button', class: 'btn sm', onclick: close }, icon('close', 14), 'Close');
    if (!row && !srow) {
      return el('div', { class: 'dr-drill missing' }, el('p', { text: 'That drill is not in the report for ' + fmtDow(rep.date) + '. A page exists for each new-drill permit of the day and for each directional survey filed that day.' }), closeBtn);
    }
    const head2 = (title, sub) => el('div', { class: 'dr-drill-head' },
      el('div', {}, el('p', { class: 'eyebrow' }, icon('pin', 15), 'Drill page'), el('h3', { text: title }), el('p', { class: 'sub', text: sub })),
      el('div', { class: 'dr-drill-act' }, shareButton(() => absoluteLink(hashFor(S.day, S.mode, sel)), 'Copy link'), closeBtn));
    const lat = row ? row[8] : srow[9]; const lon = row ? row[9] : srow[10];
    const gps = lat != null ? { label: 'GPS (NAD83)', value: gpsText(lat, lon), note: 'surface location, RRC map' } : { label: 'GPS', value: 'No point', note: 'the RRC map has none for this well' };
    const where = lat != null ? el('p', { class: 'fine' }, el('a', { href: mapsUrl(lat, lon), rel: 'noopener noreferrer', text: 'Open this point in a maps app' }), ' (leaves this site).') : null;
    const more = releaseUrl(rep) ? el('a', { href: releaseUrl(rep), rel: 'noopener noreferrer', text: 'All of this day\'s filings on GitHub' }) : null;
    const privacy = el('p', { class: 'fine', text: 'These are the Railroad Commission\'s scans, unmodified. They are public records and can carry the names, phone numbers and addresses of individuals.' });
    if (row) {
      const own = (row[10] || []).map((suffix) => Object.assign(docLabel(suffix), { href: fileUrl(rep, row[0] + '_' + suffix) }));
      const surveys = row[7] && sv ? sv.rows.filter((r) => r[0] === row[7]).map((r) => ({ label: 'Directional survey ' + r[8], type: 'PDF', href: fileUrl(rep, 'dir_survey_' + r[8] + '.pdf') })) : [];
      const docs = own.concat(surveys).filter((d) => d.href);
      return el('div', { class: 'dr-drill' }, head2('Permit ' + row[0], (row[4] || 'Operator #' + row[3]) + ' · ' + countyName(row[1]) + ' County · District ' + row[2]),
        tiles([{ label: 'Planned depth', value: row[5] ? num(row[5]) + ' ft' : '—', note: KIND[row[6]] + ' well' }, { label: 'Permit issued', value: fmtDow(pr.day), note: 'new-drill permit' },
          row[7] ? { label: 'API number', value: fmtApi(row[7]), note: 'state · county · well' } : null, gps]),
        where,
        el('h4', { class: 'dr-h4', text: 'Filings for this drill' }),
        docs.length ? [docList(docs), el('p', { class: 'fine' }, more, ' · PDF files download from GitHub.'), privacy]
          : el('p', { class: 'fine', text: 'No filings are published for this drill. They are copied on the night a report is captured live, so a day rebuilt afterward, or captured before publishing was switched on, has none.' }));
    }
    const twin = pr && srow[0] ? pr.rows.find((r) => r[7] === srow[0]) : null;
    return el('div', { class: 'dr-drill' }, head2('Directional survey ' + srow[8], srow[1] ? countyName(srow[1]) + ' County · API ' + fmtApi(srow[0]) : 'Well not identified'),
      tiles([{ label: 'Survey', value: srow[2] === 'M' ? 'MWD' : 'Other', note: 'directional survey' }, { label: 'Depth surveyed', value: srow[3] && srow[4] ? num(srow[3]) + '–' + num(srow[4]) + ' ft' : '—', note: srow[7] ? 'lateral ' + srow[7] : '' },
        { label: 'Survey dates', value: srow[5] && srow[6] ? fmtMd(srow[5]) + ' to ' + fmtMd(srow[6]) : '—', note: srow[6] ? srow[6].slice(0, 4) : '' }, { label: 'Filed', value: fmtDow(sv.day || rep.date), note: 'survey pack' }, gps]),
      where,
      twin ? el('p', { class: 'fine' }, 'The same well was permitted this day: ', el('a', { href: hashFor(S.day, S.mode, { t: 'p', id: twin[0] }), onclick: (e) => { e.preventDefault(); S.open({ t: 'p', id: twin[0] }); }, text: 'permit ' + twin[0] }), '.') : null,
      el('h4', { class: 'dr-h4', text: 'Filing' }),
      fileUrl(rep, 'dir_survey_' + srow[8] + '.pdf') ? [docList([{ label: 'Directional survey', type: 'PDF', href: fileUrl(rep, 'dir_survey_' + srow[8] + '.pdf') }]), el('p', { class: 'fine' }, more, ' · PDF files download from GitHub.'), privacy]
        : el('p', { class: 'fine', text: 'This survey\'s file is not published.' }));
  }

  function gpsCard(rep) {
    S.open = null; S.gpsEl = null;
    const pr = rep.permits; const sv = rep.surveys;
    const prows = pr ? pr.rows : []; const srows = sv ? sv.rows : [];
    const prow = prows.filter((r) => r.length >= 10 && r[8] != null); const srow = srows.filter((r) => r[9] != null);
    if (!S.G || (!prow.length && !srow.length)) return null;
    const pts = [
      ...prow.map((r) => ({ key: 'p' + r[0], layer: 'permits', f: r[1], lat: r[8], lon: r[9], aria: 'Permit ' + r[0] + ', ' + countyName(r[1]) + ' County. Press Enter for its page.',
        tip: [['Permit ' + r[0], countyName(r[1]) + ' County'], [r[4] || 'Operator #' + r[3], ''], [r[5] ? num(r[5]) + ' ft' : 'Depth not given', KIND[r[6]].toLowerCase()]] })),
      ...srow.map((r) => ({ key: 'w' + r[8], layer: 'surveys', f: r[1], lat: r[9], lon: r[10], aria: 'Directional survey ' + r[8] + ', ' + countyName(r[1]) + ' County. Press Enter for its page.',
        tip: [['Directional survey', countyName(r[1]) + ' County'], ['API ' + fmtApi(r[0]), ''], [r[3] && r[4] ? num(r[3]) + '–' + num(r[4]) + ' ft' : 'Depth not given', '']] })),
    ];
    const keyOf = (sel) => (sel ? (sel.t === 'p' ? 'p' : 'w') + sel.id : null);
    const host = el('div', { class: 'dr-drill-host', 'aria-live': 'polite' });
    const map = gpsMap(S.G, pts, { onPick: (key) => pick({ t: key[0] === 'p' ? 'p' : 's', id: key.slice(1) }) });
    const paint = () => host.replaceChildren(...[S.sel ? drillPanel(rep, S.sel, { close: () => pick(null) }) : null].filter(Boolean));
    function pick(sel, { fly = false } = {}) {
      S.sel = sel; map.mark(keyOf(sel));
      if (fly && sel) map.focusOn(keyOf(sel));
      paint();
      history.replaceState(null, '', hashFor(S.day, S.mode, sel)); // in-page picks do not add history entries, like the Map tab
      if (sel) host.scrollIntoView({ block: 'nearest', behavior: reduced() ? 'auto' : 'smooth' });
    }
    const on = { permits: true, surveys: true };
    const layerBtn = (id, label, n) => (n ? el('button', { type: 'button', class: 'btn sm dr-lay', 'aria-pressed': 'true', onclick: (e) => {
      on[id] = !on[id]; e.currentTarget.setAttribute('aria-pressed', String(on[id])); map.setLayer(id, on[id]); map.fit();
    } }, el('i', { class: 'dr-sw ' + id, 'aria-hidden': 'true' }), label + ' · ' + n) : null);
    const tools = el('div', { class: 'dr-gps-tools' },
      el('div', { class: 'dr-gps-layers', role: 'group', 'aria-label': 'Layers' }, layerBtn('permits', 'New-drill permits', prow.length), layerBtn('surveys', 'Directional surveys', srow.length)),
      el('div', { class: 'dr-gps-zoom', role: 'group', 'aria-label': 'Map view' },
        el('button', { type: 'button', class: 'btn sm', onclick: map.fit }, 'Zoom to wells'), el('button', { type: 'button', class: 'btn sm', onclick: map.all }, 'All Texas'),
        el('button', { type: 'button', class: 'btn sm', 'aria-label': 'Zoom in', onclick: map.zoomIn, text: '+' }), el('button', { type: 'button', class: 'btn sm', 'aria-label': 'Zoom out', onclick: map.zoomOut, text: '−' })));
    const link = (sel, text) => el('a', { href: hashFor(S.day, S.mode, sel), text, onclick: (e) => { e.preventDefault(); S.open(sel); } });
    const gpsCell = (a, b) => (a != null ? gpsText(a, b) : '—');
    const tables = [];
    if (prows.length) {
      tables.push(table([{ t: 'Permit' }, { t: 'County' }, { t: 'Operator' }, { t: 'Depth (ft)', num: true }, { t: 'Well' }, { t: 'GPS' }, { t: 'Filings', num: true }],
        prows.map((r) => [link({ t: 'p', id: r[0] }, r[0]), countyName(r[1]), opNode(r[3], r[4]), r[5] ? num(r[5]) : null, KIND[r[6]], gpsCell(r[8], r[9]), r[10] ? num(r[10].length) : '—'])));
    }
    if (srows.length) {
      tables.push(el('h3', { class: 'dr-h3-gap', text: 'Directional surveys filed' }),
        table([{ t: 'Survey' }, { t: 'API' }, { t: 'County' }, { t: 'Kind' }, { t: 'Depth (ft)' }, { t: 'GPS' }],
          srows.map((r) => [link({ t: 's', id: r[8] }, r[8]), r[0] ? fmtApi(r[0]) : null, r[1] ? countyName(r[1]) : null, r[2] === 'M' ? 'MWD' : 'Other', r[3] && r[4] ? num(r[3]) + '–' + num(r[4]) : null, gpsCell(r[9], r[10])])));
    }
    const card2 = card('dr-gps-card', head('pin', 'GPS map', 'Where the wells are', 'Surface locations from the Railroad Commission\'s public map service, matched by API number. Select a point to open that drill\'s page and its filings.'),
      tools, map.el,
      el('p', { class: 'fine', text: num(prow.length) + ' of ' + num(prows.length) + ' new-drill permits have a point' + (srows.length ? ' and ' + num(srow.length) + ' of ' + num(srows.length) + ' surveys' : '') + '. Drag to pan; Ctrl or ⌘ plus scroll, a trackpad pinch or the buttons zoom.' }),
      host,
      el('details', { class: 'dr-details' }, el('summary', { text: 'The same wells as a table' + (rep.release ? ', with a page for each' : '') }), ...tables));
    S.gpsEl = card2;
    S.open = (sel) => { pick(sel, { fly: true }); card2.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' }); };
    if (S.sel) { map.mark(keyOf(S.sel)); map.focusOn(keyOf(S.sel)); paint(); }
    return card2;
  }

  /* ---------- what changed: plain-English bullets ---------- */
  function storyCard(rep) {
    const out = []; const p = rep.permits; const q = rep.pending; const c = rep.completions;
    const add = (ic, color, ...kids) => { const li = el('li', { class: 'insight' }, el('span', { class: 'insight-ic' }, icon(ic, 18)), el('div', {}, el('p', {}, ...kids))); li.firstChild.style.setProperty('--c', color); out.push(li); };
    if (p && p.newDrill) {
      const avg = avgBefore(p.day);
      add('pin', 'var(--s2)', strong(num(p.newDrill)), ' new-drill permits were issued on ', strong(fmtDow(p.day)), avg ? [', ', strong(rel(p.newDrill, avg)), ' the 20-business-day average of ' + Math.round(avg) + '.'] : '.',
        p.total > p.newDrill ? ' Another ' + (p.total - p.newDrill) + ' were re-entries, recompletions or other filings.' : '');
      if (p.counties.length) {
        const t = p.counties.slice(0, 3);
        add('layers', 'var(--s2)', strong(t[0][1]), ' led with ', strong(num(t[0][2])), t.length > 1 ? [', then ' + t.slice(1).map((x) => x[1] + ' (' + x[2] + ')').join(' and ')] : '', '. ', p.countyCount + ' counties had at least one.');
      }
      const named = p.operators.filter((o) => o[1]);
      if (named.length) add('building', 'var(--s2)', el('a', { href: opsLink(named[0][1]), text: named[0][1] }), ' filed the most among operators that can be named (', strong(num(named[0][2])), '). ', p.namedShare != null ? Math.round(p.namedShare * 100) + '% of the day\'s new-drill permits went to named operators.' : '');
      add('rig', 'var(--s2)', strong(Math.round((p.horizontal / p.newDrill) * 100) + '% horizontal'), p.depth ? [' · median planned depth ', strong(num(p.depth.median) + ' ft'), ', deepest ' + num(p.depth.max) + ' ft'] : '', p.wait ? ' · median ' + p.wait.median + ' days from receipt to approval.' : '.');
    } else if (p) {
      add('pin', 'var(--s2)', 'No new-drill permits were issued on ', strong(fmtDow(p.day)), '.');
    }
    if (q) {
      const d = q.districts[0];
      add('clock', 'var(--s1)', strong(num(q.total)), ' applications are waiting for approval, ', strong(num(q.expedite)), ' flagged to expedite', d ? [', most of them in District ' + d[0] + ' (' + d[1] + ').'] : '.');
    }
    if (c) {
      const best = c.topTests[0];
      add('drop', 'var(--s3)', strong(num(c.approved)), ' completions were approved on ', strong(fmtDow(c.day)), '; ', strong(num(c.initial)), ' were first tests of new wells (' + c.oil + ' oil, ' + c.gas + ' gas).',
        best ? [' Best oil test: ', strong(num(best.rate) + ' bbl a day'), ' in ' + best.county + ' County' + (best.operator ? ' (' + best.operator + ')' : '') + '.'] : '');
    }
    if (rep.kind === 'live') {
      const cmp = compare(rep); const same = cmp.same; const err = rep.datasets.filter((d) => d.error);
      if (!cmp.ok && !err.length) add('check', 'var(--accent)', strong('First live capture. '), 'From the next report this line says which files changed overnight.');
      else if (err.length) add('close', 'var(--down)', strong(err.length + ' of ' + rep.datasets.length + ' files could not be read: '), err.map((d) => d.title).join(', ') + '.');
      else if (same.length) add('clock', 'var(--accent)', strong(same.length + ' file' + (same.length > 1 ? 's' : '') + ' did not change'), ' since the last report: ' + same.map((d) => d.title).join(', ') + '.');
      else add('check', 'var(--up)', strong('Every nightly file changed'), ' since the last report.');
      const newer = (rep.monthly || []).filter((m) => m.newer);
      if (newer.length) add('calendar', 'var(--down)', strong('A newer monthly file is waiting: '), newer.map((m) => m.title).join(', ') + '. The site\'s monthly tables were built from the older one and are due for a rebuild.');
    }
    if (!out.length) return null;
    return card('dr-story', head('bulb', 'In short', 'What the files say'), el('ul', { class: 'dr-bullets' }, out));
  }

  function statusStrip(rep) {
    const live = rep.kind === 'live';
    return el('div', { class: 'dr-strip', role: 'list', 'aria-label': 'Nightly datasets' }, rep.datasets.map((d) => {
      const st = d.error ? 'bad' : d.state === 'new' ? 'good' : d.state === 'same' ? 'warn' : 'quiet';
      const c = el('div', { class: 'dr-ds ' + st, role: 'listitem' }, el('span', { class: 'dr-ds-ic' }, icon(ICONS[d.id], 17)),
        el('div', {}, el('b', { text: TITLES[d.id] }), el('small', { text: d.error ? 'Could not be read' : d.dataDay ? 'Data for ' + fmtMd(d.dataDay) : 'Nothing for this day' }),
          el('small', { class: 'dr-ds-st', text: d.error ? 'Error' : live ? (d.state === 'new' ? 'Updated · ' + listed(d.file && d.file.modified) : d.state === 'same' ? 'No change since the last report' : 'Read · ' + listed(d.file && d.file.modified)) : 'Reconstructed' })));
      c.title = WHAT[d.id];
      return c;
    }));
  }

  /* ---------- verbose sections ---------- */
  function permitsSection(rep) {
    const p = rep.permits;
    if (!p) return card('dr-sec', head('pin', 'Permits', 'Drilling permits'), el('p', { class: 'empty', text: 'No permit file was read for this day.' }));
    const m = monthToDate(p.day);
    const pending = [];
    const tl = tiles([
      { label: 'New-drill permits', value: num(p.newDrill), note: 'of ' + num(p.total) + ' issued' },
      { label: 'Horizontal', value: p.newDrill ? Math.round((p.horizontal / p.newDrill) * 100) + '%' : '—', note: num(p.horizontal) + ' of ' + num(p.newDrill) + (p.directional ? ' · ' + p.directional + ' directional' : '') },
      { label: 'Median planned depth', value: p.depth ? num(p.depth.median) + ' ft' : '—', note: p.depth ? 'deepest ' + num(p.depth.max) + ' ft' : '' },
      { label: 'Days to approval', value: p.wait ? String(p.wait.median) : '—', note: p.wait ? 'median · longest ' + p.wait.max : 'receipt to issue' },
      { label: 'Operators', value: num(p.operatorCount), note: p.namedShare != null ? Math.round(p.namedShare * 100) + '% can be named' : '' },
      { label: 'Counties', value: num(p.countyCount), note: p.counties[0] ? p.counties[0][1] + ' led' : '' },
      { label: 'Amended that day', value: num(p.amended), note: 'earlier permits changed' },
      m ? { label: 'Month to date', value: num(m.a), note: m.b != null ? 'vs ' + num(m.b) + ' by the same date last month' : 'new-drill permits' } : null]);
    pending.push(tl);
    pending.push(el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Application types' }), stack(p.types.map(([k, n]) => ({ label: PERMIT_TYPE[k] || 'Type ' + k, value: n })))),
      el('div', {}, el('h3', { text: 'Planned depth' }), histogram(p.rows.map((r) => r[5]).filter((v) => v > 0), [0, 5000, 7500, 10000, 12500, 15000], ['<5k', '5–7.5k', '7.5–10k', '10–12.5k', '12.5–15k', '15k+'], { unit: 'new-drill permits' }))));
    pending.push(el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Counties' }), rankList(countyItems(p.counties), { color: 'var(--s2)' })),
      el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(p.operators), { color: 'var(--s2)' }), el('h3', { class: 'dr-h3-gap', text: 'RRC districts' }), rankList(p.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s2)' }))));
    pending.push(el('details', { class: 'dr-details' }, el('summary', { text: 'All ' + num(p.rows.length) + ' new-drill permits' + (p.newDrill > p.rows.length ? ' (the first ' + p.rows.length + ')' : '') }),
      table([{ t: 'Permit' }, { t: 'County' }, { t: 'District' }, { t: 'Operator' }, { t: 'Depth (ft)', num: true }, { t: 'Well' }],
        p.rows.map((r) => [S.open ? el('a', { href: hashFor(S.day, S.mode, { t: 'p', id: r[0] }), onclick: (e) => { e.preventDefault(); S.open({ t: 'p', id: r[0] }); }, text: r[0] }) : r[0], countyName(r[1]), r[2], opNode(r[3], r[4]), r[5] ? num(r[5]) : null, KIND[r[6]]]))));
    return card('dr-sec', head('pin', 'Permits', 'Drilling permits issued ' + fmtDow(p.day), 'From the nightly Drilling Permit Master and Trailer file. No permits are issued on weekends, so Saturday, Sunday and Monday reports show Friday.'), ...pending);
  }

  function pendingSection(rep) {
    const q = rep.pending;
    if (!q) return card('dr-sec', head('clock', 'Queue', 'Permits pending approval'), el('p', { class: 'empty', text: 'No pending-approval set reached the RRC share on this day. The RRC copies a set to the share after 11 AM and after 5 PM, and skips some holidays.' }));
    return card('dr-sec', head('clock', 'Queue', 'Applications waiting for approval', 'W-1s submitted since the previous run that were still pending when each set was written (' + q.sets.map((s) => (s.at.slice(0, 10) === rep.date ? '' : fmtDow(s.at.slice(0, 10)).split(',')[0] + ' ') + s.label + ': ' + s.n).join(', ') + ').'),
      tiles([{ label: 'Waiting', value: num(q.total), note: 'from ' + q.operatorCount + ' operators' }, { label: 'Flagged to expedite', value: num(q.expedite), note: Math.round((q.expedite / q.total) * 100) + '% of the queue' },
        { label: 'Horizontal', value: num(q.horizontal), note: Math.round((q.horizontal / q.total) * 100) + '%' }, { label: 'Amendments', value: num(q.amendments), note: 'changes to earlier permits' },
        { label: 'Median planned depth', value: q.depth ? num(q.depth.median) + ' ft' : '—', note: q.depth ? 'deepest ' + num(q.depth.max) + ' ft' : '' }]),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'RRC districts' }), rankList(q.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s1)' })),
        el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(q.operators), { color: 'var(--s1)' }))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Counties' }), rankList(countyItems(q.counties), { color: 'var(--s1)', empty: 'County detail was not recorded for this set.' })),
        el('div', {}, el('h3', { text: 'When they were submitted' }), stack(q.submitted.map(([d, n]) => ({ label: fmtDow(d), value: n }))),
          el('h3', { class: 'dr-h3-gap', text: 'Kinds of well' }), stack([{ label: 'Horizontal', value: q.horizontal }, { label: 'Directional', value: q.directional }, { label: 'Vertical', value: Math.max(0, q.total - q.horizontal - q.directional) }].filter((p) => p.value > 0)))),
      el('details', { class: 'dr-details' }, el('summary', { text: 'The ' + num(q.rows.length) + ' applications' }),
        table([{ t: 'Operator' }, { t: 'County' }, { t: 'District' }, { t: 'Depth (ft)', num: true }, { t: 'Well' }, { t: 'Expedite' }],
          q.rows.map((r) => [opNode(r[0], r[1]), r[2] ? countyName(r[2]) : null, r[3], r[4] ? num(r[4]) : null, KIND[r[5]], r[6] ? 'Yes' : 'No']))));
  }

  function completionsSection(rep) {
    const c = rep.completions;
    if (!c) return card('dr-sec', head('drop', 'Completions', 'Completion data'), el('p', { class: 'empty', text: 'No completion file landed on this day.' }));
    return card('dr-sec', head('drop', 'Completions', 'Completions ' + fmtDow(c.day), 'Forms submitted or approved that day: W-2 (oil), G-1 (gas), P-4, L-1, G-5, G-10, P-15 and W-12.'),
      tiles([{ label: 'Approved', value: num(c.approved), note: num(c.submitted) + ' more submitted' }, { label: 'First tests of new wells', value: num(c.initial), note: 'initial potential filings' },
        { label: 'Oil · gas', value: c.oil + ' · ' + c.gas, note: 'among first tests' }, { label: 'Horizontal', value: num(c.horizontal), note: c.initial ? Math.round((c.horizontal / c.initial) * 100) + '% of first tests' : '' },
        { label: 'Operators', value: num(c.operatorCount), note: 'filed approved completions' }]),
      c.topTests.length ? el('div', { class: 'dr-tests' }, c.topTests.slice(0, 4).map((t, i) => el('div', { class: 'dr-test' }, el('small', { text: i === 0 ? 'Best oil test' : 'Oil test #' + (i + 1) }), el('b', { text: num(t.rate) }), el('span', { text: 'bbl a day' }),
        el('small', { text: t.county + ' · District ' + t.district + (t.horizontal ? ' · horizontal' : '') + (t.operator ? ' · ' + t.operator : '') })))) : null,
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Why they were filed' }), stack(c.purpose.map(([k, n]) => ({ label: k, value: n })))),
        el('div', {}, el('h3', { text: 'Kinds of first test' }), stack(c.ctype.map(([k, n]) => ({ label: k, value: n }))))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Forms in approved packets' }), rankList(c.forms.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s3)' })),
        el('div', {}, el('h3', { text: 'RRC districts' }), rankList(c.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s3)' }))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Counties' }), rankList(countyItems(c.counties), { color: 'var(--s3)' })),
        el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(c.operators), { color: 'var(--s3)' }))));
  }

  function imagesSection(rep) {
    const im = rep.images || {};
    const cut = S.index.days.findIndex((r) => r.d === rep.date);
    const defs = [['w1images', 'w1', 'W-1 permit images', 'var(--s2)'], ['dirsurveys', 'ds', 'Directional surveys', 'var(--s7)'], ['complimages', 'cm', 'Completion images', 'var(--s3)']];
    const cards = defs.map(([id, key, title, color]) => {
      const s = im[id]; const hist = S.index.days.slice(Math.max(0, cut - 29), cut + 1).map((r) => r[key]).filter((v) => v != null);
      const med = hist.length > 4 ? [...hist].sort((a, b) => a - b)[Math.floor(hist.length / 2)] : null;
      const w1 = id === 'w1images' && s && s.districts.length ? stack(s.districts.slice(0, 6).map(([d, n]) => ({ label: 'District ' + d, value: n })), { format: mb }) : null;
      const box = el('div', { class: 'dr-img' }, el('p', { class: 'eyebrow' }, icon(ICONS[id], 15), title),
        s ? el('b', { class: 'dr-img-num', text: mb(s.bytes) }) : el('b', { class: 'dr-img-num', text: '—' }),
        el('small', { text: s ? (s.empty ? 'An empty pack: nothing filed for ' + fmtMd(s.day) : 'Pack for ' + fmtDow(s.day)) + (med ? ' · 30-day median ' + Math.round(med) + ' MB' : '') : 'Nothing landed this day' }),
        hist.length > 3 ? spark(hist, { w: 220, h: 40, color, label: title + ' size, last 30 days' }) : null, w1);
      return box;
    });
    return card('dr-sec', head('layers', 'Image packs', 'The three image packs', 'The RRC publishes these as zips of PDF and TIFF images. The size of each is read for every day, so volume stands in for filing activity; days captured live also open the zip (next section).'), el('div', { class: 'dr-imgs' }, cards));
  }

  // what the packs held that day: documents by kind and a sheet of first pages shrunk and blurred so nothing reads (live days since previews began)
  function packPagesSection(rep) {
    const im = rep.images || {};
    const defs = [['w1images', 'W-1 permit images', 'var(--s2)'], ['dirsurveys', 'Directional surveys', 'var(--s7)'], ['complimages', 'Completion images', 'var(--s3)']];
    const rows = defs.filter(([id]) => im[id] && im[id].docs && im[id].docs.n).map(([id, title, color]) => {
      const s = im[id]; const d = s.docs;
      const info = el('div', { class: 'dr-pack-info' }, el('p', { class: 'eyebrow' }, icon(ICONS[id], 15), title),
        el('b', { class: 'dr-img-num', text: num(d.n) + (d.n === 1 ? ' document' : ' documents') }),
        el('small', { text: 'Pack for ' + fmtDow(s.day) + (d.packets ? ' · from ' + num(d.packets) + ' completion packets' : '') }),
        rankList(d.types.map(([k, n]) => ({ label: k, value: n })), { color }));
      const ok = s.sheet && /^[\w.-]+\.jpg$/.test(s.sheet.file);
      const fig = ok ? el('figure', { class: 'dr-pack-fig' },
        el('img', { class: 'dr-sheet', src: 'data/daily/img/' + s.sheet.file, width: s.sheet.w, height: s.sheet.h, loading: 'lazy', decoding: 'async',
          alt: 'Contact sheet: blurred page one of ' + s.sheet.tiles + ' documents from the ' + title + ' pack, too small to read.' }),
        el('figcaption', { text: 'Page one of ' + s.sheet.tiles + ' of the ' + num(d.n) + ' documents, one kind after another, shrunk to ' + s.sheet.px + ' pixels wide' + (s.sheet.blur ? ' and blurred' : '') + '.' }))
        : el('p', { class: 'fine', text: 'No page preview could be drawn for this pack.' });
      return el('div', { class: 'dr-pack' }, info, fig);
    });
    if (!rows.length) return null;
    return card('dr-sec', head('layers', 'Inside the packs', 'What the packs held', 'On the night a day is captured the three zips are opened: documents are counted by kind, and page one of a spread of them is drawn. These sheets are shrunk and blurred on purpose so that nothing can be read, and the completion images are never published. The W-1 letters and plats of the day\'s new-drill permits and the day\'s directional surveys are different: they are published readable, each on its drill\'s page (GPS map above). Days before previews began show sizes only.'), ...rows);
  }

  function healthSection(rep) {
    const live = rep.kind === 'live';
    const chipFor = (d) => (d.error ? chip('bad', 'Error') : d.state === 'new' ? chip('good', 'Updated') : d.state === 'same' ? chip('warn', 'No change') : d.state === 'first' ? chip('quiet', 'First capture') : chip('quiet', 'Reconstructed'));
    const rows = rep.datasets.map((d) => [el('span', { class: 'dr-dsname' }, icon(ICONS[d.id], 15), TITLES[d.id]), d.cadence ? el('span', { title: d.cadence, text: d.cadence.replace(/,.*$/, '') }) : '—', d.dataDay ? fmtMd(d.dataDay) : '—', d.file ? el('code', { text: d.file.name }) : '—',
      d.file ? listed(d.file.modified) : '—', d.file && d.file.bytes != null ? mb(d.file.bytes) : '—', d.files != null ? num(d.files) : '—', chipFor(d)]);
    const kids = [table([{ t: 'Dataset' }, { t: 'RRC says' }, { t: 'Data day' }, { t: 'Newest file' }, { t: 'Listed' }, { t: 'Size', num: true }, { t: 'Files on share', num: true }, { t: 'Status' }], rows, { cap: 'dr-table flat' })];
    if (live && rep.catalog) {
      const c = rep.catalog;
      kids.push(el('p', { class: 'fine', text: 'The RRC page lists ' + c.datasets + ' data sets; ' + c.nightly.length + ' are nightly or twice daily' + (c.unknown.length ? '. New nightly sets this report does not read: ' + c.unknown.join('; ') + '.' : ', the same ones this report reads.') }));
    }
    if (live && rep.monthly) {
      kids.push(el('h3', { class: 'dr-h3-gap', text: 'Monthly files the site is built from' }),
        table([{ t: 'File' }, { t: 'Newest on the RRC share' }, { t: 'Listed' }, { t: 'Site built from' }, { t: 'Status' }],
          rep.monthly.map((m) => [m.title, m.file ? el('code', { text: m.file }) : '—', listed(m.modified), m.siteBuilt || '—', m.error ? chip('bad', 'Not read') : m.newer ? chip('bad', 'Newer file waiting') : m.siteBuilt ? chip('good', 'Current') : chip('quiet', 'Not tracked')]), { cap: 'dr-table flat' }),
        el('p', { class: 'fine', text: 'The site\'s county, operator and company tables come from these monthly files. When a newer one appears, those tables are due for a rebuild; the daily report above does not depend on it.' }));
    }
    return card('dr-sec', head('check', 'Source health', 'Is everything arriving?', live ? 'What each nightly file looked like when it was read.' : 'This day was rebuilt from the RRC file history, so file times are not available.'), ...kids);
  }

  // one cell per calendar day: permits by the day they were issued (the next report shows them), the rest by report day
  function calCells(id) {
    const days = S.index.days; const byDay = new Map(days.map((r) => [r.d, r]));
    if (id === 'permits' && S.series) {
      const s = S.series;
      return s.days.map((d, i) => { const next = addDays(d, 1); const open = byDay.has(next) ? next : null; return { d, v: s.newDrill[i] > 0 ? s.newDrill[i] : null, open, live: !!open && byDay.get(open).k === 'live' }; });
    }
    return days.map((r) => ({ d: r.d, v: METRICS[id].get(r), open: r.d, live: r.k === 'live' }));
  }

  function archiveSection() {
    const days = S.index.days;
    const host = el('div', { class: 'dr-cal-host' });
    const paint = () => {
      const m = METRICS[S.metric];
      host.replaceChildren(calendar({ cells: calCells(S.metric), selected: S.day, label: m.label + ' by day', format: m.fmt, none: m.none, onPick: (d) => { go(d, S.mode); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }); } }),
        el('p', { class: 'fine', text: 'Paler is lower, deeper is higher. Select a day to open its report. Permits sit on the day they were issued and open the next day\'s report. Bordered days were captured live; the rest were rebuilt from the RRC file history.' }));
    };
    const seg = segmented({ label: 'Calendar figure', options: Object.entries(METRICS).map(([id, m]) => ({ id, label: m.label })), value: S.metric, tabs: false, prefix: 'drc', onChange: (id) => { S.metric = id; paint(); } });
    paint();
    return card('dr-sec', head('calendar', 'Archive', 'Every day, three months', 'Pick a figure and a day. ' + days.length + ' reports from ' + fmtMd(days[0].d) + ' to ' + fmtMd(days[days.length - 1].d) + '.'), el('div', { class: 'dr-maptools' }, seg.el), host);
  }

  function notesSection(rep) {
    const li = (...k) => el('li', {}, ...k);
    return card('dr-sec dr-notes', head('bulb', 'How to read this', 'Notes and limits'), el('ul', { class: 'plain' },
      li(strong('What a day shows. '), 'A report holds what landed on each RRC file share that day, Central time, judged by the time the share lists. Pending sets: the previous evening\'s 5 PM set, which is copied after midnight, and the day\'s 11 AM set. Completions and the image packs are posted the next morning (about 2:20 AM for completions and completion images, 7:55 for surveys, 10:20 for W-1 images), so a report shows the day before\'s, and a day on which nothing landed shows nothing (there is no W-1 pack for a weekend, so Sunday and Monday have none). Permits are the newest issue date before the day. Each card says which day its data is from.'),
      li(strong('Rebuilt days. '), 'Days marked reconstructed were rebuilt from the RRC\'s file history by the same rule: permits from the month-end and nightly files, completions, image packs and pending sets from what had landed on the share that day. The catalog check and file states only exist for days captured live.'),
      li(strong('Permits. '), 'New-drill means application type 01, counted once per permit number, the same rule as the rest of this site. Monthly totals here match the site\'s own monthly series to within one permit. GPS points come from the Railroad Commission\'s public map service (its Well Locations layer, matched by API number), so a permit can have none until the RRC maps it.'),
      li(strong('Pending queue. '), 'Each set holds W-1s submitted since the previous run that were still waiting; it is not a running total, and a permit leaves it when approved.'),
      li(strong('Times. '), 'File times are shown as the RRC share lists them, which is Central time. The report date is the Central-time day the capture ran.'),
      li(strong('Privacy. '), 'Operators are named only when they are corporations, LLCs or limited partnerships, and this site\'s own pages leave out lease names, well numbers and anything about individuals. One deliberate exception: each drill\'s page links to the Railroad Commission\'s scanned W-1 letter, plat and directional survey, published unmodified as GitHub release files. They are public records and can carry the names, phone numbers and addresses of individuals; nothing is redacted. Completion images stay blurred and unpublished.')));
  }

  /* ---------- page ---------- */
  function render() {
    const rep = S.rep;
    const ae = document.activeElement;
    const keep = ae && root.contains(ae) ? (ae.id || (ae.dataset && ae.dataset.act) || null) : null;
    const kids = [hero(rep), ribbonCard(), kpiRow(rep), el('div', { class: 'dr-grid2' }, el('div', { class: 'dr-col' }, trendCard(rep), storyCard(rep)), mapCard(rep)), gpsCard(rep), statusStrip(rep)];
    if (S.mode === 'simple') {
      kids.push(el('p', { class: 'dr-more' }, el('button', { type: 'button', class: 'btn', onclick: () => go(S.day, 'full') }, 'Open the verbose report', icon('arrow', 15))));
    } else {
      kids.push(permitsSection(rep), pendingSection(rep), completionsSection(rep), imagesSection(rep), packPagesSection(rep), healthSection(rep), archiveSection(), notesSection(rep));
    }
    const nodes = kids.filter(Boolean);
    nodes.forEach((n, i) => n.style.setProperty('--d', String(Math.min(i, 9))));
    root.replaceChildren(...nodes);
    if (S.rb) S.rb.mark(S.day);
    if (keep) { const t = root.querySelector('[data-act="' + keep + '"]') || document.getElementById(keep); if (t && !t.disabled) t.focus({ preventScroll: true }); }
  }

  async function show(day) {
    const seq = ++S.seq;
    S.day = day;
    let rep;
    try { rep = await load('daily/' + day); } catch (e) { root.replaceChildren(h1, el('p', { class: 'empty', text: 'That day\'s report could not be loaded. Reload the page to try again.' })); return; }
    if (seq !== S.seq) return;
    S.rep = rep;
    render();
    if (S.sel && S.gpsEl) requestAnimationFrame(() => S.gpsEl.scrollIntoView({ block: 'start', behavior: 'auto' })); // a shared drill link opens on its page
    document.title = fmtLong(day).replace(/, \d{4}$/, '') + ' · Daily report · Texas Oil & Gas Leads';
    const i = S.index.days.findIndex((r) => r.d === day);
    [i - 1, i + 1].forEach((k) => { if (S.index.days[k]) loadOpt('daily/' + S.index.days[k].d); });
  }

  function go(day, mode) {
    S.mode = mode;
    if (day !== S.day) S.sel = null; // a drill belongs to its day; switching between the simple and verbose report keeps it
    const hash = hashFor(day, mode, S.sel);
    if (location.hash !== hash) history.pushState(null, '', hash);
    return show(day);
  }

  return {
    async activate(params) {
      if (!S.ready) {
        try { await boot(); } catch (e) {
          h1.textContent = 'Daily report';
          root.replaceChildren(h1, el('p', { class: 'empty', text: 'The daily report has no data yet. It appears after the first nightly capture.' }));
          return;
        }
      }
      const want = params.get('d'); const days = S.index.days;
      const day = days.some((r) => r.d === want) ? want : days[days.length - 1].d;
      S.mode = params.get('v') === 'full' ? 'full' : 'simple';
      const dr = params.get('drill'); const sv = params.get('survey');
      S.sel = dr && /^\d{7}$/.test(dr) ? { t: 'p', id: dr } : sv && /^\d{1,12}$/.test(sv) ? { t: 's', id: sv } : null;
      await show(day);
    },
  };
}
