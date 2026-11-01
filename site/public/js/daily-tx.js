// The parts of the Daily report that only the Railroad Commission of Texas has: the pending-approval queue, the three image packs,
// and the GPS map with a page (a URL) for each well and its filings. daily.js puts them into the combined report.
//
// ctx is what the combined view shares: S (its state: the days, the selected day and well, the Texas shapes in S.gTx), cname(f)
// (a Texas county's name from its FIPS code), hashFor(day, mode, sel) (the address of a view) and multi() (both states shown).
import { el, reduced } from './util.js';
import { icon } from './icons.js';
import { shareButton, absoluteLink } from './ui.js';
import { spark } from './charts.js';
import { opsLink } from './overview.js';
import { gpsMap, rankList, stack, fmtMd, fmtDow, mb } from './daily-viz.js';
import { num, card, head, tiles, table, pctOf } from './daily-kit.js';
import { releaseOk as relOk, fileUrl as releaseFile, previewUrl, docLabel } from './images-data.js';
import { previewGrid } from './previews.js';

export const TX_TITLES = { permits: 'Drilling permits', pending: 'Permits pending approval', completions: 'Completion data', w1images: 'W-1 permit images', dirsurveys: 'Directional surveys', complimages: 'Completion images' };
export const TX_ICONS = { permits: 'pin', pending: 'clock', completions: 'drop', w1images: 'layers', dirsurveys: 'rig', complimages: 'building' };
export const TX_WHAT = {
  permits: 'New permits issued, from the nightly Drilling Permit Master and Trailer file (daf420.dat).',
  pending: 'W-1 applications submitted and not yet approved, from the twice-daily pending set.',
  completions: 'Completion forms (W-2, G-1, P-4 and others) submitted or approved that day.',
  w1images: 'Zipped images of every W-1 approved that day, by RRC district. The size is captured; live days also count the documents, and the W-1 letters and plats of the day\'s new-drill permits are published for each drill\'s page.',
  dirsurveys: 'Zipped directional survey images submitted that day. The size is captured; live days also count the documents and publish the surveys, each with its own page.',
  complimages: 'Zipped completion form images. The size is captured; live days also count the documents.',
};
export const KIND = { H: 'Horizontal', D: 'Directional', V: 'Vertical' };
export const PERMIT_TYPE = { '01': 'New drill', '05': 'Other', '07': 'Re-entry', '09': 'Field transfer', '14': 'Recompletion', '15': 'Reclass' };

// an operator is a link to the Operators tab when the report names it; an unnamed one shows its Commission number
export const txOpNode = (op, name) => (name ? el('a', { href: opsLink(name), text: name }) : el('span', { class: 'muted', text: 'Operator #' + op }));

export function texasParts(ctx) {
  const { S, cname, hashFor } = ctx;
  const idxDays = () => (S.idx.TX ? S.idx.TX.days : []);

  function pendingSection(rep) {
    const q = rep.pending;
    if (!q) return card('dr-sec', head('clock', 'Queue · Texas', 'Permits pending approval'), el('p', { class: 'empty', text: 'No pending-approval set reached the RRC share on this day. The RRC copies a set to the share after 11 AM and after 5 PM, and skips some holidays.' }));
    const opItems = (list) => list.map(([op, name, n]) => ({ label: name || 'Operator #' + op, value: n, href: name ? opsLink(name) : null }));
    return card('dr-sec', head('clock', 'Queue · Texas', 'Applications waiting for approval', 'W-1s submitted since the previous run that were still pending when each set was written (' + q.sets.map((s) => (s.at.slice(0, 10) === rep.date ? '' : fmtDow(s.at.slice(0, 10)).split(',')[0] + ' ') + s.label + ': ' + s.n).join(', ') + ').'),
      tiles([{ label: 'Waiting', value: num(q.total), note: 'from ' + q.operatorCount + ' operators' }, { label: 'Flagged to expedite', value: num(q.expedite), note: q.total ? pctOf(q.expedite, q.total) + ' of the queue' : '' },
        { label: 'Horizontal', value: num(q.horizontal), note: q.total ? pctOf(q.horizontal, q.total) : '' }, { label: 'Amendments', value: num(q.amendments), note: 'changes to earlier permits' },
        { label: 'Median planned depth', value: q.depth ? num(q.depth.median) + ' ft' : '—', note: q.depth ? 'deepest ' + num(q.depth.max) + ' ft' : '' }]),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'RRC districts' }), rankList(q.districts.map(([d, n]) => ({ label: 'District ' + d, value: n })), { color: 'var(--s1)' })),
        el('div', {}, el('h3', { text: 'Operators' }), rankList(opItems(q.operators), { color: 'var(--s1)' }))),
      el('div', { class: 'dr-cols' },
        el('div', {}, el('h3', { text: 'Counties' }), rankList(q.counties.map(([f, name, n]) => ({ label: name, value: n })), { color: 'var(--s1)', empty: 'County detail was not recorded for this set.' })),
        el('div', {}, el('h3', { text: 'When they were submitted' }), stack(q.submitted.map(([d, n]) => ({ label: fmtDow(d), value: n }))),
          el('h3', { class: 'dr-h3-gap', text: 'Kinds of well' }), stack([{ label: 'Horizontal', value: q.horizontal }, { label: 'Directional', value: q.directional }, { label: 'Vertical', value: Math.max(0, q.total - q.horizontal - q.directional) }].filter((p) => p.value > 0)))),
      el('details', { class: 'dr-details' }, el('summary', { text: 'The ' + num(q.rows.length) + ' applications' }),
        table([{ t: 'Operator' }, { t: 'County' }, { t: 'District' }, { t: 'Depth (ft)', num: true }, { t: 'Well' }, { t: 'Expedite' }],
          q.rows.map((r) => [txOpNode(r[0], r[1]), r[2] ? cname(r[2]) : null, r[3], r[4] ? num(r[4]) : null, KIND[r[5]], r[6] ? 'Yes' : 'No']))));
  }

  function imagesSection(rep) {
    const im = rep.images || {};
    const days = idxDays();
    const cut = days.findIndex((r) => r.d === rep.date);
    const defs = [['w1images', 'w1', 'W-1 permit images', 'var(--s2)'], ['dirsurveys', 'ds', 'Directional surveys', 'var(--s7)'], ['complimages', 'cm', 'Completion images', 'var(--s3)']];
    const cards = defs.map(([id, key, title, color]) => {
      const s = im[id]; const hist = days.slice(Math.max(0, cut - 29), cut + 1).map((r) => r[key]).filter((v) => v != null);
      const med = hist.length > 4 ? [...hist].sort((a, b) => a - b)[Math.floor(hist.length / 2)] : null;
      const w1 = id === 'w1images' && s && s.districts.length ? stack(s.districts.slice(0, 6).map(([d, n]) => ({ label: 'District ' + d, value: n })), { format: mb }) : null;
      return el('div', { class: 'dr-img' }, el('p', { class: 'eyebrow' }, icon(TX_ICONS[id], 15), title),
        s ? el('b', { class: 'dr-img-num', text: mb(s.bytes) }) : el('b', { class: 'dr-img-num', text: '—' }),
        el('small', { text: s ? (s.empty ? 'An empty pack: nothing filed for ' + fmtMd(s.day) : 'Pack for ' + fmtDow(s.day)) + (med ? ' · 30-day median ' + Math.round(med) + ' MB' : '') : 'Nothing landed this day' }),
        hist.length > 3 ? spark(hist, { w: 220, h: 40, color, label: title + ' size, last 30 days' }) : null, w1);
    });
    return card('dr-sec', head('layers', 'Image packs · Texas', 'The three image packs', 'The RRC publishes these as zips of PDF and TIFF images. The size of each is read for every day, so volume stands in for filing activity; days captured live also open the zip (next section).'), el('div', { class: 'dr-imgs' }, cards));
  }

  // what the packs held that day: documents by kind and a sheet of first pages shrunk and blurred so nothing reads (live days since previews began)
  function packPagesSection(rep) {
    const im = rep.images || {};
    const defs = [['w1images', 'W-1 permit images', 'var(--s2)'], ['dirsurveys', 'Directional surveys', 'var(--s7)'], ['complimages', 'Completion images', 'var(--s3)']];
    const rows = defs.filter(([id]) => im[id] && im[id].docs && im[id].docs.n).map(([id, title, color]) => {
      const s = im[id]; const d = s.docs;
      const info = el('div', { class: 'dr-pack-info' }, el('p', { class: 'eyebrow' }, icon(TX_ICONS[id], 15), title),
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
    return card('dr-sec', head('layers', 'Inside the packs · Texas', 'What the packs held', 'On the night a day is captured the three zips are opened: documents are counted by kind, and page one of a spread of them is drawn. These sheets are shrunk and blurred on purpose so that nothing can be read. The W-1 letters and plats of the day\'s new-drill permits and the day\'s directional surveys are different: they are published readable, each on its drill\'s page (GPS map above). Page one of every completion document is published readable too, on the Texas images page, for the newest 31 days. Days before previews began show sizes only.'), ...rows);
  }

  /* ---------- the GPS map, and a page (a URL) for each well with its filings ---------- */
  const fmtApi = (a) => '42-' + a.slice(0, 3) + '-' + a.slice(3); // state 42, county, well
  // the release a report links to is validated before it becomes a link: names come from a data file (images-data.js)
  const fileUrl = (rep, name) => releaseFile(rep.release, name);
  const releaseUrl = (rep) => (relOk(rep.release) ? 'https://github.com/' + rep.release.repo + '/releases/tag/' + rep.release.tag : null);
  const gpsText = (lat, lon) => lat.toFixed(5) + ', ' + lon.toFixed(5);
  const mapsUrl = (lat, lon) => 'https://www.google.com/maps/search/?api=1&query=' + lat.toFixed(5) + ',' + lon.toFixed(5);
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
      const own = (row[10] || []).map((suffix) => Object.assign(docLabel(suffix), { href: fileUrl(rep, row[0] + '_' + suffix), preview: previewUrl(rep.release, row[0] + '_' + suffix) }));
      const surveys = row[7] && sv ? sv.rows.filter((r) => r[0] === row[7]).map((r) => ({ label: 'Directional survey ' + r[8], type: 'PDF', href: fileUrl(rep, 'dir_survey_' + r[8] + '.pdf'), preview: previewUrl(rep.release, 'dir_survey_' + r[8] + '.pdf') })) : [];
      const docs = own.concat(surveys).filter((d) => d.href);
      const pages = docs.filter((d) => d.preview).map((d) => ({ title: 'Permit ' + row[0], label: d.label, type: d.type, preview: d.preview, original: d.href }));
      return el('div', { class: 'dr-drill' }, head2('Permit ' + row[0], (row[4] || 'Operator #' + row[3]) + ' · ' + cname(row[1]) + ' County · District ' + row[2]),
        tiles([{ label: 'Planned depth', value: row[5] ? num(row[5]) + ' ft' : '—', note: KIND[row[6]] + ' well' }, { label: 'Permit issued', value: fmtDow(pr.day), note: 'new-drill permit' },
          row[7] ? { label: 'API number', value: fmtApi(row[7]), note: 'state · county · well' } : null, gps]),
        where,
        el('h4', { class: 'dr-h4', text: 'Filings for this drill' }),
        docs.length ? [pages.length ? previewGrid(pages) : null, docList(docs), el('p', { class: 'fine' }, more, ' · PDF files download from GitHub.'), privacy]
          : el('p', { class: 'fine', text: 'No filings are published for this drill. They are copied on the night a report is captured live, so a day rebuilt afterward, or captured before publishing was switched on, has none.' }));
    }
    const twin = pr && srow[0] ? pr.rows.find((r) => r[7] === srow[0]) : null;
    return el('div', { class: 'dr-drill' }, head2('Directional survey ' + srow[8], srow[1] ? cname(srow[1]) + ' County · API ' + fmtApi(srow[0]) : 'Well not identified'),
      tiles([{ label: 'Survey', value: srow[2] === 'M' ? 'MWD' : 'Other', note: 'directional survey' }, { label: 'Depth surveyed', value: srow[3] && srow[4] ? num(srow[3]) + '–' + num(srow[4]) + ' ft' : '—', note: srow[7] ? 'lateral ' + srow[7] : '' },
        { label: 'Survey dates', value: srow[5] && srow[6] ? fmtMd(srow[5]) + ' to ' + fmtMd(srow[6]) : '—', note: srow[6] ? srow[6].slice(0, 4) : '' }, { label: 'Filed', value: fmtDow(sv.day || rep.date), note: 'survey pack' }, gps]),
      where,
      twin ? el('p', { class: 'fine' }, 'The same well was permitted this day: ', el('a', { href: hashFor(S.day, S.mode, { t: 'p', id: twin[0] }), onclick: (e) => { e.preventDefault(); S.open({ t: 'p', id: twin[0] }); }, text: 'permit ' + twin[0] }), '.') : null,
      el('h4', { class: 'dr-h4', text: 'Filing' }),
      fileUrl(rep, 'dir_survey_' + srow[8] + '.pdf') ? [previewUrl(rep.release, 'dir_survey_' + srow[8] + '.pdf') ? previewGrid([{ title: 'Survey ' + srow[8], label: 'Directional survey', type: 'PDF', preview: previewUrl(rep.release, 'dir_survey_' + srow[8] + '.pdf'), original: fileUrl(rep, 'dir_survey_' + srow[8] + '.pdf') }]) : null,
        docList([{ label: 'Directional survey', type: 'PDF', href: fileUrl(rep, 'dir_survey_' + srow[8] + '.pdf') }]), el('p', { class: 'fine' }, more, ' · PDF files download from GitHub.'), privacy]
        : el('p', { class: 'fine', text: 'This survey\'s file is not published.' }));
  }

  function gpsCard(rep) {
    S.open = null; S.gpsEl = null;
    const pr = rep.permits; const sv = rep.surveys;
    const prows = pr ? pr.rows : []; const srows = sv ? sv.rows : [];
    const prow = prows.filter((r) => r.length >= 10 && r[8] != null); const srow = srows.filter((r) => r[9] != null);
    if (!S.gTx || (!prow.length && !srow.length)) return null;
    const pts = [
      ...prow.map((r) => ({ key: 'p' + r[0], layer: 'permits', f: r[1], lat: r[8], lon: r[9], aria: 'Permit ' + r[0] + ', ' + cname(r[1]) + ' County. Press Enter for its page.',
        tip: [['Permit ' + r[0], cname(r[1]) + ' County'], [r[4] || 'Operator #' + r[3], ''], [r[5] ? num(r[5]) + ' ft' : 'Depth not given', KIND[r[6]].toLowerCase()]] })),
      ...srow.map((r) => ({ key: 'w' + r[8], layer: 'surveys', f: r[1], lat: r[9], lon: r[10], aria: 'Directional survey ' + r[8] + ', ' + cname(r[1]) + ' County. Press Enter for its page.',
        tip: [['Directional survey', cname(r[1]) + ' County'], ['API ' + fmtApi(r[0]), ''], [r[3] && r[4] ? num(r[3]) + '–' + num(r[4]) + ' ft' : 'Depth not given', '']] })),
    ];
    const keyOf = (sel) => (sel ? (sel.t === 'p' ? 'p' : 'w') + sel.id : null);
    const host = el('div', { class: 'dr-drill-host', 'aria-live': 'polite' });
    const map = gpsMap(S.gTx, pts, { onPick: (key) => pick({ t: key[0] === 'p' ? 'p' : 's', id: key.slice(1) }) });
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
        prows.map((r) => [link({ t: 'p', id: r[0] }, r[0]), cname(r[1]), txOpNode(r[3], r[4]), r[5] ? num(r[5]) : null, KIND[r[6]], gpsCell(r[8], r[9]), r[10] ? num(r[10].length) : '—'])));
    }
    if (srows.length) {
      tables.push(el('h3', { class: 'dr-h3-gap', text: 'Directional surveys filed' }),
        table([{ t: 'Survey' }, { t: 'API' }, { t: 'County' }, { t: 'Kind' }, { t: 'Depth (ft)' }, { t: 'GPS' }],
          srows.map((r) => [link({ t: 's', id: r[8] }, r[8]), r[0] ? fmtApi(r[0]) : null, r[1] ? cname(r[1]) : null, r[2] === 'M' ? 'MWD' : 'Other', r[3] && r[4] ? num(r[3]) + '–' + num(r[4]) : null, gpsCell(r[9], r[10])])));
    }
    const card2 = card('dr-gps-card', head('pin', 'GPS map · Texas', 'Where the wells are', 'Surface locations from the Railroad Commission\'s public map service, matched by API number. Select a point to open that drill\'s page and its filings.' + (ctx.multi() ? ' Oklahoma\'s files carry no coordinates, so this map is Texas only.' : '')),
      tools, map.el,
      el('p', { class: 'fine', text: num(prow.length) + ' of ' + num(prows.length) + ' new-drill permits have a point' + (srows.length ? ' and ' + num(srow.length) + ' of ' + num(srows.length) + ' surveys' : '') + '. Drag to pan; Ctrl or ⌘ plus scroll, a trackpad pinch or the buttons zoom.' }),
      host,
      el('details', { class: 'dr-details' }, el('summary', { text: 'The same wells as a table' + (rep.release ? ', with a page for each' : '') }), ...tables));
    S.gpsEl = card2;
    S.open = (sel) => { pick(sel, { fly: true }); card2.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' }); };
    if (S.sel) { map.mark(keyOf(S.sel)); map.focusOn(keyOf(S.sel)); paint(); }
    return card2;
  }

  // the table of every new-drill permit of the day, each linking to its drill page when the GPS card is on the page
  function permitRows(rep) {
    const p = rep.permits;
    return el('details', { class: 'dr-details' }, el('summary', { text: 'Texas: all ' + num(p.rows.length) + ' new-drill permits' + (p.newDrill > p.rows.length ? ' (the first ' + p.rows.length + ')' : '') }),
      table([{ t: 'Permit' }, { t: 'County' }, { t: 'District' }, { t: 'Operator' }, { t: 'Depth (ft)', num: true }, { t: 'Well' }],
        p.rows.map((r) => [S.open ? el('a', { href: hashFor(S.day, S.mode, { t: 'p', id: r[0] }), onclick: (e) => { e.preventDefault(); S.open({ t: 'p', id: r[0] }); }, text: r[0] }) : r[0], cname(r[1]), r[2], txOpNode(r[3], r[4]), r[5] ? num(r[5]) : null, KIND[r[6]]])));
  }

  return { pendingSection, imagesSection, packPagesSection, gpsCard, permitRows };
}
