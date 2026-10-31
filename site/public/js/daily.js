// Daily report: what the Railroad Commission's nightly datasets held, one report per day for the last 92 days.
// A simple version for the daily look and a verbose one with everything. Each block hides itself if its data is missing.
import { el, load, loadOpt, reduced } from './util.js';
import { getGeo } from './geo.js';
import { icon } from './icons.js';
import { segmented, shareButton, absoluteLink } from './ui.js';
import { spark, delta } from './charts.js';
import { opsLink } from './overview.js';
import { trendBars, countyMap, ribbon, calendar, ring, stack, histogram, rankList, isWeekend, fmtMd, fmtDow, fmtLong, addDays, mb } from './daily-viz.js';
import { num, strong, listed, central, compare, rel, card, head, tiles, table, chip, kpi } from './daily-kit.js';

const TITLES = { permits: 'Drilling permits', pending: 'Permits pending approval', completions: 'Completion data', w1images: 'W-1 permit images', dirsurveys: 'Directional surveys', complimages: 'Completion images' };
const ICONS = { permits: 'pin', pending: 'clock', completions: 'drop', w1images: 'layers', dirsurveys: 'rig', complimages: 'building' };
const WHAT = {
  permits: 'New permits issued, from the nightly Drilling Permit Master and Trailer file (daf420.dat).',
  pending: 'W-1 applications submitted and not yet approved, from the twice-daily pending set.',
  completions: 'Completion forms (W-2, G-1, P-4 and others) submitted or approved that day.',
  w1images: 'Zipped images of every W-1 approved that day, by RRC district. The size is captured; live days also count the documents.',
  dirsurveys: 'Zipped directional survey images submitted that day. The size is captured; live days also count the documents.',
  complimages: 'Zipped completion form images. The size is captured; live days also count the documents.',
};
const KIND = { H: 'Horizontal', D: 'Directional', V: 'Vertical' };
const PERMIT_TYPE = { '01': 'New drill', '05': 'Other', '07': 'Re-entry', '09': 'Field transfer', '14': 'Recompletion', '15': 'Reclass' };

const METRICS = {
  permits: { label: 'New-drill permits issued', get: (r) => (r.pFresh ? r.pn : null), fmt: (v) => num(v) + ' new-drill permits issued', none: 'No permits issued (weekend or holiday)' },
  pending: { label: 'Waiting for approval', get: (r) => r.q, fmt: (v) => num(v) + ' applications waiting', none: 'No pending set recorded' },
  completions: { label: 'Completions approved', get: (r) => r.c, fmt: (v) => num(v) + ' completions approved', none: 'No completion file read' },
  volume: { label: 'Image pack volume', get: (r) => r.vol, fmt: (v) => Math.round(v) + ' MB of image packs', none: 'No pack sizes read' },
};

export function createDailyView({ root }) {
  const S = { index: null, series: null, G: null, rep: null, day: null, mode: 'simple', layer: 'permits', metric: 'permits', seq: 0, ready: false };
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
        p.rows.map((r) => [r[0], countyName(r[1]), r[2], opNode(r[3], r[4]), r[5] ? num(r[5]) : null, KIND[r[6]]]))));
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
    return card('dr-sec', head('layers', 'Inside the packs', 'What the packs held', 'On the night a day is captured the three zips are opened: documents are counted by kind, and page one of a spread of them is drawn. The pages are shrunk and blurred on purpose so that nothing can be read: the filings carry lease names, well numbers and the names of individuals, which this site leaves out. Days before previews began show sizes only.'), ...rows);
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
      li(strong('Permits. '), 'New-drill means application type 01, counted once per permit number, the same rule as the rest of this site. Monthly totals here match the site\'s own monthly series to within one permit. Only some recent permits carry surface coordinates.'),
      li(strong('Pending queue. '), 'Each set holds W-1s submitted since the previous run that were still waiting; it is not a running total, and a permit leaves it when approved.'),
      li(strong('Times. '), 'File times are shown as the RRC share lists them, which is Central time. The report date is the Central-time day the capture ran.'),
      li(strong('Privacy. '), 'Operators are named only when they are corporations, LLCs or limited partnerships. Lease names, well numbers and anything about individuals are left out.')));
  }

  /* ---------- page ---------- */
  function render() {
    const rep = S.rep;
    const ae = document.activeElement;
    const keep = ae && root.contains(ae) ? (ae.id || (ae.dataset && ae.dataset.act) || null) : null;
    const kids = [hero(rep), ribbonCard(), kpiRow(rep), el('div', { class: 'dr-grid2' }, el('div', { class: 'dr-col' }, trendCard(rep), storyCard(rep)), mapCard(rep)), statusStrip(rep)];
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
    document.title = fmtLong(day).replace(/, \d{4}$/, '') + ' · Daily report · Texas Oil & Gas Leads';
    const i = S.index.days.findIndex((r) => r.d === day);
    [i - 1, i + 1].forEach((k) => { if (S.index.days[k]) loadOpt('daily/' + S.index.days[k].d); });
  }

  function go(day, mode) {
    S.mode = mode;
    const latest = S.index.days[S.index.days.length - 1].d;
    const q = new URLSearchParams();
    if (day !== latest) q.set('d', day);
    if (mode === 'full') q.set('v', 'full');
    const hash = '#daily' + (q.toString() ? '?' + q : '');
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
      await show(day);
    },
  };
}
