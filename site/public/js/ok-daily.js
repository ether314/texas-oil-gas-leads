// Oklahoma daily report: what the Oklahoma Corporation Commission's daily files held, one report per day for the last 92 days.
// The same shape as the Texas report (daily.js): a simple version for the daily look and a verbose one with everything.
// Each block hides itself if its data is missing. Operators are named only when the file says they are corporations, LLCs or partnerships.
import { el, load, loadOpt, reduced } from './util.js';
import { buildGeoIsolated } from './geo.js';
import { icon } from './icons.js';
import { segmented, shareButton, absoluteLink } from './ui.js';
import { delta } from './charts.js';
import { trendBars, countyMap, ribbon, calendar, stack, rankList, isWeekend, fmtMd, fmtDow, fmtLong, addDays, mb } from './daily-viz.js';
import { num, strong, listed, central, compare, rel, card, head, tiles, table, chip, kpi } from './daily-kit.js';

const TITLES = { itd: 'Intent to drill', completions: 'Well completions', transfers: 'Well transfers', wells: 'Well inventory' };
const ICONS = { itd: 'pin', completions: 'drop', transfers: 'building', wells: 'rig' };
const WHAT = {
  itd: 'Intents to drill the Commission approved: the 7 complete days before the file is made, about 7:40 PM Central (ITD-wells-formations-daily.xlsx).',
  completions: 'Completion filings (Form 1002A), one row per casing string or test in the file, folded here to one filing per well and day (completions-wells-formations-daily.xlsx).',
  transfers: 'Wells that changed operator, about a month of them (well-transfers-daily.xlsx).',
  wells: 'Every well in the state, from the nightly well file (about 457,000 records). Counted here, never listed.',
};
const WORDS = { permits: 'new-drill permits approved', queue: null, completions: 'completion filings', transfers: 'wells changed operator' };
const DEEP = 'Deep, 12,000 ft or more';
const pl = (n, one, many = one + 's') => num(n) + ' ' + (n === 1 ? one : many);
const signed = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + num(Math.abs(n));

const METRICS = {
  permits: { label: 'New-drill permits approved', key: ['dd', 'pn'], fmt: (v) => num(v) + ' new-drill permits approved', none: 'No new-drill permits approved (weekend or holiday)' },
  completions: { label: 'Completions filed', key: ['cd', 'c'], fmt: (v) => num(v) + ' completion filings', none: 'No completion filings' },
  transfers: { label: 'Wells changing operator', key: ['td', 't'], fmt: (v) => num(v) + ' wells changed operator', none: 'No transfers on file for this day' },
};

export function createOkDailyView({ root }) {
  const S = { index: null, ps: null, G: null, rep: null, day: null, mode: 'simple', layer: 'permits', metric: 'permits', seq: 0, ready: false, rb: null };
  const h1 = el('h1', { id: 'ok-h1', class: 'dr-title', tabindex: '-1' });
  root.replaceChildren(h1, el('p', { class: 'empty', text: 'Loading the Oklahoma report…' }));

  /* ---------- data ---------- */
  async function boot() {
    const idx = await load('daily-ok/index');
    idx.days.forEach((r, i) => { r.pFresh = i === 0 || r.dd !== idx.days[i - 1].dd; });
    S.index = idx;
    S.ps = permitSeries(idx.days);
    // the shapes are built against their own box, so the Texas map (hero, Map view) keeps its projection
    S.G = await loadOpt('counties-ok.geo').then((gj) => (gj ? buildGeoIsolated(gj) : null)).catch(() => null);
    S.ready = true;
  }

  // one point per approval day: a day with permits is the day a later report shows, so it is in the index; weekdays between
  // two such days with none are holidays (zero)
  function permitSeries(days) {
    const seen = new Map();
    days.forEach((r) => { if (r.dd && !seen.has(r.dd)) seen.set(r.dd, { n: r.pn || 0, deep: r.pd || 0, total: r.p || 0 }); });
    const keys = [...seen.keys()].sort();
    const out = { days: [], n: [], deep: [], total: [] };
    if (!keys.length) return out;
    for (let d = keys[0]; d <= keys[keys.length - 1]; d = addDays(d, 1)) {
      if (isWeekend(d) && !seen.has(d)) continue;
      const v = seen.get(d) || { n: 0, deep: 0, total: 0 };
      out.days.push(d); out.n.push(v.n); out.deep.push(v.deep); out.total.push(v.total);
    }
    return out;
  }
  // the last `count` business days of new-drill permits up to and including `until`
  function biz(until, count) {
    const s = S.ps; let hi = s.days.length;
    while (hi > 0 && s.days[hi - 1] > until) hi--;
    const lo = Math.max(0, hi - count);
    return { days: s.days.slice(lo, hi), total: s.n.slice(lo, hi), deep: s.deep.slice(lo, hi) };
  }
  // average of the 20 business days before `day`, leaving out weekdays with no permits at all (holidays)
  function avgBefore(day, n = 20) {
    const s = S.ps; const v = [];
    for (let i = s.days.length - 1; i >= 0 && v.length < n; i--) {
      if (s.days[i] >= day || !s.total[i]) continue;
      v.push(s.n[i]);
    }
    return v.length >= 5 ? v.reduce((a, x) => a + x, 0) / v.length : null;
  }
  function monthToDate(day) {
    const s = S.ps;
    if (!s.days.length) return null;
    const ym = day.slice(0, 7); const dd = day.slice(8);
    const prevYm = addDays(ym + '-01', -1).slice(0, 7);
    let a = 0; let b = 0;
    s.days.forEach((d, i) => {
      if (d.slice(0, 7) === ym && d <= day) a += s.n[i];
      if (d.slice(0, 7) === prevYm && d.slice(8) <= dd) b += s.n[i];
    });
    // last month is only a fair comparison when the archive reaches back to its first days (a month can start on a weekend)
    return { a, b: s.days[0] <= addDays(prevYm + '-01', 3) ? b : null };
  }
  const hist = (key, cut) => S.index.days.slice(Math.max(0, cut - 29), cut + 1).map((r) => r[key]).filter((v) => v != null);
  const countyRows = (rows) => (rows || []).map(([f, name, n]) => ({ label: name, value: n }));
  // operators are named only when the file says so; an unnamed one shows its Commission number
  const opItems = (list) => (list || []).map(([op, name, n]) => ({ label: name || 'Operator #' + op, value: n }));
  const pctOf = (n, d) => (d ? Math.round((n / d) * 100) + '%' : '—');

  /* ---------- header, ribbon, KPIs ---------- */
  function hero(rep) {
    const days = S.index.days; const i = days.findIndex((r) => r.d === rep.date);
    const live = rep.kind === 'live';
    const ds = rep.datasets.filter((d) => !d.absent);
    const read = ds.filter((d) => !d.error).length; const cmp = compare(rep);
    const status = live ? (rep.status === 'ok' ? 'good' : rep.status === 'partial' ? 'warn' : 'bad') : 'info';
    const pills = [chip(status, live ? read + ' of ' + ds.length + ' daily files read' : 'Reconstructed from Commission file history')];
    if (live && rep.capturedAt) pills.push(chip('quiet', 'Captured ' + central(rep.capturedAt)));
    if (live && cmp.ok && cmp.fresh) pills.push(chip('quiet', cmp.fresh + ' updated since the last report'));
    if (live && !cmp.ok) pills.push(chip('quiet', 'First live capture'));
    const step = (n) => go(days[i + n].d, S.mode);
    const nav = el('div', { class: 'dr-nav' },
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'earlier', disabled: i === 0, 'aria-label': 'Earlier day', onclick: () => step(-1) }, icon('arrow', 14, 'flip'), 'Earlier'),
      el('button', { type: 'button', class: 'btn sm', 'data-act': 'later', disabled: i === days.length - 1, 'aria-label': 'Later day', onclick: () => step(1) }, 'Later', icon('arrow', 14)),
      i === days.length - 1 ? null : el('button', { type: 'button', class: 'btn sm primary', 'data-act': 'latest', onclick: () => go(days[days.length - 1].d, S.mode) }, 'Latest'),
      shareButton(() => absoluteLink(location.hash || '#oklahoma'), 'Copy link'));
    const seg = segmented({ label: 'Report version', options: [{ id: 'simple', label: 'Simple' }, { id: 'full', label: 'Verbose' }], value: S.mode, tabs: false, prefix: 'okv', onChange: (id) => go(S.day, id) });
    h1.textContent = fmtLong(rep.date).replace(/, \d{4}$/, '');
    return el('header', { class: 'dr-hero' },
      el('div', { class: 'dr-radar', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')),
      el('div', { class: 'dr-hero-in' },
        el('p', { class: 'eyebrow' }, el('span', { class: 'live-dot', 'aria-hidden': 'true' }), 'Daily Oklahoma Corporation Commission report · ', el('span', { text: rep.date.slice(0, 4) })),
        h1,
        el('p', { class: 'dr-lede', text: S.mode === 'simple'
          ? 'The daily look: what the Oklahoma Corporation Commission published overnight, in a minute.'
          : 'Everything the Commission refreshes daily or nightly, captured and read.' }),
        el('div', { class: 'dr-pills' }, pills)),
      el('div', { class: 'dr-controls' }, seg.el, nav));
  }

  function ribbonCard() {
    const rb = ribbon({ days: S.index.days, selected: S.day, onPick: (d) => go(d, S.mode), words: WORDS });
    S.rb = rb; // positioned again once it is in the page, so a phone opens on the selected day
    return card('dr-ribbon-card', el('div', { class: 'dr-ribbon-head' }, el('p', { class: 'eyebrow' }, icon('calendar', 15), 'Last 3 months'),
      el('small', { text: 'One bar per report day. Height is the new-drill permits approved that business day; weekends have none.' })), rb.el);
  }

  function kpiRow(rep) {
    const p = rep.permits; const c = rep.completions; const t = rep.transfers; const w = rep.wells;
    const avg = p ? avgBefore(p.day) : null; const bs = p ? biz(p.day, 20) : { total: [] };
    const cut = S.index.days.findIndex((r) => r.d === rep.date);
    return el('div', { class: 'dr-kpis' },
      kpi({ ic: 'pin', label: 'New-drill permits approved', value: p && p.newDrill, hero: true, color: 'var(--s2)', vals: bs.total,
        note: p ? fmtDow(p.day) + ' · ' + num(p.total) + (p.total === 1 ? ' permit' : ' permits') + ' of all kinds' : 'No permit file was read for this day',
        extra: p && avg ? [delta((p.newDrill - avg) / avg), ' vs the 20-day average of ' + avg.toFixed(1)] : null }),
      kpi({ ic: 'drop', label: 'Completions filed', value: c && c.filed, color: 'var(--s3)', vals: hist('c', cut),
        note: c ? pl(c.amended, 'amended filing') + ' · ' + fmtDow(c.day) : 'No completion filings for this day' }),
      kpi({ ic: 'building', label: 'Wells changing operator', value: t && t.wells, color: 'var(--s1)', vals: hist('t', cut),
        note: t ? t.buyerCount + (t.buyerCount === 1 ? ' buyer' : ' buyers') + ' · ' + fmtDow(t.day) : 'No transfers on file for this day' }),
      kpi({ ic: 'rig', label: 'Active wells in the state', value: w && w.active, color: 'var(--accent)',
        note: w ? (w.change ? signed(w.change.active) + ' since ' + fmtMd(w.change.since) : 'As of ' + fmtMd(w.asOf)) : 'The inventory is counted on the night of each live capture' }));
  }

  /* ---------- permits per day and the map ---------- */
  function trendCard(rep) {
    const p = rep.permits;
    const bs = p ? biz(p.day, 30) : null;
    if (!p || !bs || bs.days.length < 5) return null;
    const avg = avgBefore(p.day);
    return card('dr-trend', head('trend', 'Pace', 'New-drill permits per business day', 'Last 30 business days to ' + fmtMd(p.day) + '. Holidays show as empty days.'),
      el('div', { class: 'dr-legend-inline' }, el('i', { class: 'dr-dot horiz' }), el('span', { text: DEEP }), el('i', { class: 'dr-dot rest' }), el('span', { text: 'Shallower' })),
      trendBars({ days: bs.days, total: bs.total, horiz: bs.deep, avg, avgText: avg ? avg.toFixed(1) : null, unit: 'new-drill permits', sub: 'planned 12,000 ft or deeper',
        label: 'Bar chart of new-drill permits approved per business day from ' + fmtMd(bs.days[0]) + ' to ' + fmtMd(p.day) + '. ' + fmtDow(p.day) + ' had ' + p.newDrill + (avg ? ', against an average of ' + avg.toFixed(1) : '') + '.' }));
  }

  function mapCard(rep) {
    const layers = {}; const defs = []; const names = {};
    const lay = (id, label, rows) => {
      if (!rows || !rows.length) return;
      layers[id] = { map: new Map(rows.map((x) => [x[0], x[2]])) }; names[id] = new Map(rows.map((x) => [x[0], x[1]]));
      defs.push({ id, label });
    };
    lay('permits', 'Permits', rep.permits && rep.permits.counties);
    lay('completions', 'Completions', rep.completions && rep.completions.counties);
    lay('transfers', 'Transfers', rep.transfers && rep.transfers.counties);
    lay('wells', 'Wells', rep.wells && rep.wells.counties);
    if (!defs.length) return null;
    if (!layers[S.layer]) S.layer = defs[0].id;
    const colors = { permits: 'var(--s2)', completions: 'var(--s3)', transfers: 'var(--s1)', wells: 'var(--s7)' };
    const unit = { permits: 'new-drill permits approved', completions: 'completion filings', transfers: 'wells that changed operator', wells: 'active wells' };
    const list = el('div', { class: 'dr-maplist' });
    const wrap = el('div', { class: 'dr-mapwrap' });
    const map = S.G ? countyMap(S.G, layers, S.layer, { state: 'Oklahoma', unit }) : null;
    if (map) wrap.append(map.el);
    const paint = () => {
      wrap.style.setProperty('--lc', colors[S.layer]);
      const top = [...layers[S.layer].map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
      list.replaceChildren(el('p', { class: 'dr-maplist-h', text: 'Top counties · ' + unit[S.layer] }),
        rankList(top.map(([f, n]) => ({ label: names[S.layer].get(f) || f, value: n })), { color: colors[S.layer], empty: 'No county detail for this layer.' }));
    };
    const seg = segmented({ label: 'Map layer', options: defs, value: S.layer, tabs: false, prefix: 'okm', onChange: (id) => { S.layer = id; if (map) map.set(id); paint(); } });
    paint();
    return card('dr-mapcard', head('pin', 'Where', 'Oklahoma, by county', 'Bubbles grow with the count; hover a county for its number.'), el('div', { class: 'dr-maptools tight' }, seg.el), wrap, list);
  }

  /* ---------- what changed: plain-English bullets ---------- */
  function storyCard(rep) {
    const out = []; const p = rep.permits; const c = rep.completions; const t = rep.transfers; const w = rep.wells;
    const add = (ic, color, ...kids) => { const li = el('li', { class: 'insight' }, el('span', { class: 'insight-ic' }, icon(ic, 18)), el('div', {}, el('p', {}, ...kids))); li.firstChild.style.setProperty('--c', color); out.push(li); };
    if (p && p.newDrill) {
      const avg = avgBefore(p.day);
      add('pin', 'var(--s2)', strong(num(p.newDrill)), p.newDrill === 1 ? ' new-drill permit was approved on ' : ' new-drill permits were approved on ', strong(fmtDow(p.day)),
        avg ? [', ', strong(rel(p.newDrill, avg)), ' the 20-business-day average of ' + avg.toFixed(1) + '.'] : '.',
        p.total - p.newDrill === 1 ? ' Another 1 was an amendment, recompletion or other filing.' : p.total > p.newDrill ? ' Another ' + (p.total - p.newDrill) + ' were amendments, recompletions or other filings.' : '');
      if (p.counties.length) {
        const tc = p.counties.slice(0, 3);
        add('layers', 'var(--s2)', strong(tc[0][1]), ' led with ', strong(num(tc[0][2])), tc.length > 1 ? [', then ' + tc.slice(1).map((x) => x[1] + ' (' + x[2] + ')').join(' and ')] : '', '. ',
          p.countyCount + (p.countyCount === 1 ? ' county had' : ' counties had') + ' at least one.');
      }
      const named = p.operators.filter((o) => o[1]);
      if (named.length) add('building', 'var(--s2)', strong(named[0][1]), ' filed the most among operators that can be named (', strong(num(named[0][2])), '). ', p.namedShare != null ? Math.round(p.namedShare * 100) + '% of the day\'s new-drill permits went to named operators.' : '');
      add('rig', 'var(--s2)', strong(pctOf(p.deep, p.newDrill) + ' planned 12,000 ft or deeper'), p.depth ? [' · median planned depth ', strong(num(p.depth.median) + ' ft'), ', deepest ' + num(p.depth.max) + ' ft'] : '',
        p.wait ? ' · median ' + p.wait.median + (p.wait.median === 1 ? ' day' : ' days') + ' from filing to approval.' : '.');
    } else if (p) {
      add('pin', 'var(--s2)', 'No new-drill permits were approved on ', strong(fmtDow(p.day)), p.total ? ' (' + p.total + ' other filings were).' : '.');
    }
    if (c) {
      const best = c.tests[0];
      add('drop', 'var(--s3)', strong(num(c.filed)), c.filed === 1 ? ' completion was filed on ' : ' completions were filed on ', strong(fmtDow(c.day)), c.amended ? ', and ' + (c.amended === 1 ? '1 earlier filing was' : num(c.amended) + ' earlier filings were') + ' amended' : '', '.',
        best ? [' Best first test: ', strong(num(best.oil || best.gas) + (best.oil ? ' bbl of oil a day' : ' mcf of gas a day')), ' in ' + best.county + ' County' + (best.operator ? ' (' + best.operator + ')' : '') + '.'] : '');
    }
    if (t) {
      const b = t.buyers.find((x) => x[1]); const sb = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
      add('building', 'var(--s1)', strong(num(t.wells)), t.wells === 1 ? ' well changed operator on ' : ' wells changed operator on ', strong(fmtDow(t.day)),
        b ? [': ', strong(b[1]), ' took ' + num(b[2])] : '', ' (' + sb(t.sellerCount, 'seller') + ', ' + sb(t.buyerCount, 'buyer') + ').');
    }
    if (w) {
      add('rig', 'var(--accent)', strong(num(w.active)), ' active wells in the state inventory', w.change ? [' (', strong(signed(w.change.active)), ' since ' + fmtMd(w.change.since) + ')'] : '', ', ', num(w.plugged) + ' plugged, of ' + num(w.total) + ' records.');
    }
    if (rep.kind === 'live') {
      const cmp = compare(rep); const same = cmp.same; const err = rep.datasets.filter((d) => d.error);
      if (!cmp.ok && !err.length) add('check', 'var(--accent)', strong('First live capture. '), 'From the next report this line says which files changed overnight.');
      else if (err.length) add('close', 'var(--down)', strong(err.length + ' of ' + rep.datasets.length + ' files could not be read: '), err.map((d) => TITLES[d.id]).join(', ') + '.');
      else if (same.length) add('clock', 'var(--accent)', strong(same.length + ' file' + (same.length > 1 ? 's' : '') + ' did not change'), ' since the last report: ' + same.map((d) => TITLES[d.id]).join(', ') + '.');
      else add('check', 'var(--up)', strong('Every daily file changed'), ' since the last report.');
    }
    if (!out.length) return null;
    return card('dr-story', head('bulb', 'In short', 'What the files say'), el('ul', { class: 'dr-bullets' }, out));
  }

  function statusStrip(rep) {
    const live = rep.kind === 'live';
    return el('div', { class: 'dr-strip four', role: 'list', 'aria-label': 'Daily datasets' }, rep.datasets.map((d) => {
      const st = d.error ? 'bad' : d.absent ? 'quiet' : d.state === 'new' ? 'good' : d.state === 'same' ? 'warn' : 'quiet';
      const c = el('div', { class: 'dr-ds ' + st, role: 'listitem' }, el('span', { class: 'dr-ds-ic' }, icon(ICONS[d.id], 17)),
        el('div', {}, el('b', { text: TITLES[d.id] }),
          el('small', { text: d.error ? 'Could not be read' : d.absent ? 'Only the current inventory is published' : d.dataDay ? 'Data for ' + fmtMd(d.dataDay) : 'Nothing for this day' }),
          el('small', { class: 'dr-ds-st', text: d.error ? 'Error' : d.absent ? 'Live days only' : live ? (d.state === 'new' ? 'Updated · ' + listed(d.file && d.file.modified) : d.state === 'same' ? 'No change since the last report' : 'Read · ' + listed(d.file && d.file.modified)) : 'Reconstructed' })));
      c.title = WHAT[d.id];
      return c;
    }));
  }

  /* ---------- verbose sections ---------- */
  function permitsSection(rep) {
    const p = rep.permits;
    if (!p) return card('dr-sec', head('pin', 'Permits', 'Intents to drill'), el('p', { class: 'empty', text: 'No permit file was read for this day.' }));
    const m = monthToDate(p.day);
    const kids = [];
    kids.push(tiles([
      { label: 'New-drill permits', value: num(p.newDrill), note: 'of ' + num(p.total) + ' approved' },
      { label: 'Planned 12,000 ft or deeper', value: pctOf(p.deep, p.newDrill), note: num(p.deep) + ' of ' + num(p.newDrill) },
      { label: 'Median planned depth', value: p.depth ? num(p.depth.median) + ' ft' : '—', note: p.depth ? 'deepest ' + num(p.depth.max) + ' ft' : '' },
      { label: 'Days to approval', value: p.wait ? String(p.wait.median) : '—', note: p.wait ? 'median · longest ' + p.wait.max : 'filing to approval' },
      { label: 'Operators', value: num(p.operatorCount), note: p.namedShare != null ? Math.round(p.namedShare * 100) + '% can be named' : '' },
      { label: 'Counties', value: num(p.countyCount), note: p.counties[0] ? p.counties[0][1] + ' led' : '' },
      { label: 'Amended that day', value: num(p.amended), note: 'earlier permits changed' },
      m ? { label: 'Month to date', value: num(m.a), note: m.b != null ? 'vs ' + num(m.b) + ' by the same date last month' : 'new-drill permits' } : null]));
    kids.push(el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Kinds of filing' }), stack(p.types.map(([k, n]) => ({ label: k, value: n })))),
      el('div', {}, el('h3', { text: 'Planned depth' }), p.newDrill ? rankList(p.bands.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s2)', max: Math.max(1, ...p.bands.map((b) => b[1])) }) : el('p', { class: 'fine', text: 'No new-drill permits.' }))));
    kids.push(el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Counties' }), rankList(countyRows(p.counties), { color: 'var(--s2)', empty: 'No county on file for these permits.' })),
      el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(p.operators), { color: 'var(--s2)' }),
        p.classes.length ? [el('h3', { class: 'dr-h3-gap', text: 'Kinds of well' }), stack(p.classes.map(([k, n]) => ({ label: k, value: n })))] : null)));
    return card('dr-sec', head('pin', 'Permits', 'Intents to drill approved ' + fmtDow(p.day), 'From the Commission\'s daily intent-to-drill file. Approvals happen on business days, so Saturday, Sunday and Monday reports show Friday. Depth is the planned total depth: the file does not say which permits are horizontal.'), ...kids);
  }

  function completionsSection(rep) {
    const c = rep.completions;
    if (!c) return card('dr-sec', head('drop', 'Completions', 'Completion filings'), el('p', { class: 'empty', text: 'No completion filings were in the daily file for this day.' }));
    const testBox = c.tests.length ? el('div', { class: 'dr-tests' }, c.tests.slice(0, 4).map((t, i) => el('div', { class: 'dr-test' },
      el('small', { text: i === 0 ? 'Best first test' : 'Test #' + (i + 1) }), el('b', { text: num(t.oil || t.gas) }), el('span', { text: t.oil ? 'bbl of oil a day' : 'mcf of gas a day' }),
      el('small', { text: t.county + ' County' + (t.horizontal ? ' · horizontal' : '') + (t.oil && t.gas ? ' · ' + num(t.gas) + ' mcf of gas' : '') + (t.operator ? ' · ' + t.operator : '') })))) : null;
    return card('dr-sec', head('drop', 'Completions', 'Completions filed ' + fmtDow(c.day), 'Completion forms (1002A) filed that day. The file holds a row for every casing string and test, so each well is counted once per filing day; amended filings are counted apart.'),
      tiles([{ label: 'Filed', value: num(c.filed), note: c.amended ? 'plus ' + num(c.amended) + ' amended' : 'none amended' }, { label: 'Horizontal', value: num(c.horizontal), note: c.filed ? pctOf(c.horizontal, c.filed) + ' of filings' : '' },
        { label: 'Filed after first production', value: c.lag ? pl(c.lag.median, 'day') : '—', note: c.lag ? 'median · longest ' + c.lag.max : 'where a first-production date is on file' },
        { label: 'Spud to first production', value: c.spudToProd ? pl(c.spudToProd.median, 'day') : '—', note: 'median, where both dates are on file' },
        { label: 'Operators', value: num(c.operatorCount), note: c.namedShare != null ? Math.round(c.namedShare * 100) + '% can be named' : '' }, { label: 'Counties', value: num(c.countyCount), note: c.counties[0] ? c.counties[0][1] + ' led' : '' }]),
      testBox,
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Kinds of well' }), stack(c.types.map(([k, n]) => ({ label: k, value: n })))),
        el('div', {}, el('h3', { text: 'Formations' }), c.formations.length ? rankList(c.formations.map(([k, n]) => ({ label: k, value: n })), { color: 'var(--s3)' }) : el('p', { class: 'fine', text: 'No formation is named on these filings.' }))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Counties' }), rankList(countyRows(c.counties), { color: 'var(--s3)' })),
        el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(c.operators), { color: 'var(--s3)' }))));
  }

  function transfersSection(rep) {
    const t = rep.transfers;
    if (!t) return card('dr-sec', head('building', 'Ownership', 'Well transfers'), el('p', { class: 'empty', text: 'No well changed operator on the day this report looks at, or the day is older than the month of transfers the Commission\'s file holds.' }));
    return card('dr-sec', head('building', 'Ownership', 'Wells that changed operator ' + fmtDow(t.day), 'From the Commission\'s well-transfer file, which holds about a month. A few days carry one large sale, so the count swings more than permits do.'),
      tiles([{ label: 'Wells', value: num(t.wells), note: 'changed operator' }, { label: 'Buyers', value: num(t.buyerCount), note: 'operators taking wells' }, { label: 'Sellers', value: num(t.sellerCount), note: 'operators giving them up' }]),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Buyers' }), rankList(opItems(t.buyers), { color: 'var(--s1)' })),
        el('div', {}, el('h3', { text: 'Sellers' }), rankList(opItems(t.sellers), { color: 'var(--s1)' }))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Counties' }), rankList(countyRows(t.counties), { color: 'var(--s1)' })),
        el('div', {}, el('h3', { text: 'Kinds of well' }), stack(t.types.map(([k, n]) => ({ label: k, value: n }))))));
  }

  function wellsSection(rep) {
    const w = rep.wells;
    if (!w) {
      return card('dr-sec', head('rig', 'Inventory', 'Wells in the state'), el('p', { class: 'empty', text: rep.kind === 'live'
        ? 'The well inventory could not be read for this report.'
        : 'The Commission publishes only the current well inventory, so a report rebuilt for an earlier day has none. Days captured live do.' }));
    }
    const ch = w.change; const since = (k) => (ch ? signed(ch[k]) + ' since ' + fmtMd(ch.since) : '');
    return card('dr-sec', head('rig', 'Inventory', 'Every well in the state', 'The Commission\'s nightly well file, as of ' + fmtDow(w.asOf) + '. The wells are counted, never listed: no name, number or location of any well is kept here.'),
      tiles([{ label: 'Active wells', value: num(w.active), note: since('active') || pctOf(w.active, w.total) + ' of the records' }, { label: 'Plugged', value: num(w.plugged), note: since('plugged') || pctOf(w.plugged, w.total) + ' of the records' },
        { label: 'Records in all', value: num(w.total), note: ch ? signed(ch.total) + ' since ' + fmtMd(ch.since) : 'every status' }, { label: 'Counties with active wells', value: num(w.countyCount), note: w.counties[0] ? w.counties[0][1] + ' led' : '' },
        { label: 'Operators on record', value: num(w.operatorCount), note: 'with an active well' }]),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Status of every record' }), stack(w.status.map(([k, n]) => ({ label: k, value: n })))),
        el('div', {}, el('h3', { text: 'Kinds of active well' }), stack(w.activeTypes.map(([k, n]) => ({ label: k, value: n }))))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Active wells by county' }), rankList(countyRows(w.counties.slice(0, 12)), { color: 'var(--s7)' })),
        el('div', {}, el('h3', { text: 'Operators with the most active wells' }), rankList(w.operators.map(([name, n]) => ({ label: name, value: n })), { color: 'var(--s7)' }),
          el('p', { class: 'fine', text: 'Only corporations, LLCs and partnerships are named. ' + num(w.unnamed) + ' active wells belong to other operators and ' + num(w.unassigned) + ' have none assigned.' }))));
  }

  function healthSection(rep) {
    const live = rep.kind === 'live';
    const chipFor = (d) => (d.error ? chip('bad', 'Error') : d.absent ? chip('quiet', 'Live days only') : d.state === 'new' ? chip('good', 'Updated') : d.state === 'same' ? chip('warn', 'No change') : d.state === 'first' ? chip('quiet', 'First capture') : chip('quiet', 'Reconstructed'));
    const rows = rep.datasets.map((d) => [el('span', { class: 'dr-dsname' }, icon(ICONS[d.id], 15), TITLES[d.id]), d.cadence || '—', d.dataDay ? fmtMd(d.dataDay) : '—', d.file ? el('code', { text: d.file.name }) : '—',
      d.file ? listed(d.file.modified) : '—', d.file && d.file.bytes != null ? mb(d.file.bytes) : '—', chipFor(d)]);
    const kids = [table([{ t: 'Dataset' }, { t: 'Commission says' }, { t: 'Data day' }, { t: 'Newest file' }, { t: 'Listed' }, { t: 'Size', num: true }, { t: 'Status' }], rows, { cap: 'dr-table flat' })];
    if (live && rep.catalog) {
      const c = rep.catalog; const read = rep.datasets.length;
      kids.push(el('p', { class: 'fine', text: 'The Commission\'s data page lists ' + c.nightly.length + ' files it refreshes daily or nightly; this report reads the ' + read + ' that carry drilling and well activity' +
        (c.unknown.length ? '. New ones it does not read: ' + c.unknown.join('; ') + '.' : '. The rest are master copies of the same records, a map copy of the well file, an incident list that runs weeks behind and contact lists this site does not use.') }));
    }
    return card('dr-sec', head('check', 'Source health', 'Is everything arriving?', live ? 'What each daily file looked like when it was read.' : 'This day was rebuilt from the Commission\'s master files, so file times are not available.'), ...kids);
  }

  // one cell per calendar day: each figure sits on the day it belongs to and opens the next day's report, which is the one that shows it
  function calCells(id) {
    const [dk, vk] = METRICS[id].key; const days = S.index.days; const byDay = new Map(days.map((r) => [r.d, r])); const seen = new Map();
    days.forEach((r) => { if (r[dk] && !seen.has(r[dk])) seen.set(r[dk], r[vk]); });
    return [...seen.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([d, v]) => {
      const open = addDays(d, 1); const rp = byDay.get(open);
      return { d, v: v > 0 ? v : null, open: rp ? open : null, live: !!rp && rp.k === 'live' };
    });
  }

  function archiveSection() {
    const days = S.index.days;
    const host = el('div', { class: 'dr-cal-host' });
    const paint = () => {
      const m = METRICS[S.metric]; const cells = calCells(S.metric);
      host.replaceChildren(cells.length > 1 ? calendar({ cells, selected: S.day, label: m.label + ' by day', format: m.fmt, none: m.none, onPick: (d) => { go(d, S.mode); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }); } }) : el('p', { class: 'empty', text: 'Nothing to show yet.' }),
        el('p', { class: 'fine', text: 'Paler is lower, deeper is higher. Select a day to open its report. Each figure sits on the day it belongs to and opens the next day\'s report. Bordered days were captured live; the rest were rebuilt from the Commission\'s master files. Transfers reach back only as far as the Commission\'s file does.' }));
    };
    const seg = segmented({ label: 'Calendar figure', options: Object.entries(METRICS).map(([id, m]) => ({ id, label: m.label })), value: S.metric, tabs: false, prefix: 'okc', onChange: (id) => { S.metric = id; paint(); } });
    paint();
    return card('dr-sec', head('calendar', 'Archive', 'Every day, three months', 'Pick a figure and a day. ' + days.length + ' reports from ' + fmtMd(days[0].d) + ' to ' + fmtMd(days[days.length - 1].d) + '.'), el('div', { class: 'dr-maptools' }, seg.el), host);
  }

  function notesSection() {
    const li = (...k) => el('li', {}, ...k);
    return card('dr-sec dr-notes', head('bulb', 'How to read this', 'Notes and limits'), el('ul', { class: 'plain' },
      li(strong('What a day shows. '), 'A report shows the newest day before it on which the Commission\'s files hold anything, so Monday\'s report shows Friday\'s approvals, filings and transfers. Only whole days are shown: the Commission\'s daily files are made around 7:40 PM Central, and a day is not counted until it is over. Each card says which day its data is from.'),
      li(strong('Rebuilt days. '), 'Days marked reconstructed were rebuilt by the same rule from the Commission\'s master files of intents to drill and completions, and from the transfer file for as far back as it goes (about a month). The well inventory cannot be rebuilt: only days captured live have it.'),
      li(strong('Permits. '), 'New-drill means application type DR with an approval date; rejected and deleted applications are left out. Times in the files are UTC and are turned into Central days. The file does not say which permits are horizontal, so the report shows planned depth instead and calls a well planned to 12,000 feet or more deep (about three in four of the new-drill permits in this archive). Oklahoma approves far fewer permits a day than Texas, so single days swing a lot; read the averages.'),
      li(strong('Completions. '), 'The completion file holds a row for every casing string and test. Rows are folded to one filing per well and day, and amended filings are counted apart. A filing is dated by the day it was created.'),
      li(strong('Transfers. '), 'A well counts when its operator changed. One sale can move hundreds of wells in a day.'),
      li(strong('Well inventory. '), 'The nightly well file has a record for every well ever drilled in the state, about 457,000, most of them plugged. Active wells are the ones with status AC. It is counted, never listed.'),
      li(strong('Privacy. '), 'Operators are named only when they are corporations, LLCs or limited partnerships. Lease names, well numbers, API numbers, locations and anything about individuals are left out, and the Commission\'s operator, purchaser and plugger contact lists are not read.')));
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
      kids.push(permitsSection(rep), completionsSection(rep), transfersSection(rep), wellsSection(rep), healthSection(rep), archiveSection(), notesSection());
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
    try { rep = await load('daily-ok/' + day); } catch (e) { root.replaceChildren(h1, el('p', { class: 'empty', text: 'That day\'s report could not be loaded. Reload the page to try again.' })); return; }
    if (seq !== S.seq) return;
    S.rep = rep;
    render();
    document.title = fmtLong(day).replace(/, \d{4}$/, '') + ' · Oklahoma daily report · Texas Oil & Gas Leads';
    const i = S.index.days.findIndex((r) => r.d === day);
    [i - 1, i + 1].forEach((k) => { if (S.index.days[k]) loadOpt('daily-ok/' + S.index.days[k].d); });
  }

  function go(day, mode) {
    S.mode = mode;
    const latest = S.index.days[S.index.days.length - 1].d;
    const q = new URLSearchParams();
    if (day !== latest) q.set('d', day);
    if (mode === 'full') q.set('v', 'full');
    const hash = '#oklahoma' + (q.toString() ? '?' + q : '');
    if (location.hash !== hash) history.pushState(null, '', hash);
    return show(day);
  }

  return {
    async activate(params) {
      if (!S.ready) {
        try { await boot(); } catch (e) {
          h1.textContent = 'Oklahoma daily report';
          root.replaceChildren(h1, el('p', { class: 'empty', text: 'The Oklahoma report has no data yet. It appears after the first nightly capture.' }));
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
