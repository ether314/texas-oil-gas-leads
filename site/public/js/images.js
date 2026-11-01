// The Texas images view: the scanned filings the Railroad Commission publishes about each well, as three packs a business day. What a well leaves behind as images,
// by stage of its life (permit, drilling, completion), how much arrives each day, and, for any day, what its packs hold and which permits' filings are published.
// Data: the Daily archive's index and day files (d7_daily.py), and above them the well finder (wells.js: every document of the packs, tied to its well by d12_wells.py).
import { el, svg, load, loadOpt, fmt, fmtDate } from './util.js';
import { icon } from './icons.js';
import { showTip, hideTip, tipRow } from './tip.js';
import { niceMax } from './national-data.js';
import * as I from './images-data.js';
import { previewGrid } from './previews.js';
import { createWellsPanel } from './wells.js';
import { tieLine } from './wells-data.js';

const hdr = (eyebrow, ic, title, sub, tools) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null), tools || null);
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const short = (iso) => MONTH[+iso.slice(5, 7) - 1] + ' ' + +iso.slice(8);

export function createImagesView({ root }) {
  let rows = []; let building = null; let day = null; let latest = {}; // latest: the newest day each pack was counted by kind, {pack: {day, p}}
  const slots = {};
  const wells = createWellsPanel();
  let wantedDay;

  // the day goes into the address beside whatever else it holds (a well, a county)
  function writeHash() {
    const q = new URLSearchParams(location.hash.split('?')[1] || '');
    if (day) q.set('d', day); else q.delete('d');
    const next = '#images' + (q.toString() ? '?' + q : '');
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  /* ---------- the top ---------- */
  function figures() {
    const s = I.summary(rows);
    const found = Object.values(latest);
    const docs = found.reduce((t, x) => t + (x.p.n || 0), 0);
    const size = found.reduce((t, x) => t + (x.p.bytes || 0), 0);
    return el('dl', { class: 'dr-tiles nat-kpis' }, [
      { label: 'Packs a business day', value: '3', note: 'W-1 images, directional surveys and completion images' },
      found.length ? { label: 'Documents in the newest counts', value: fmt.format(docs), note: 'the newest day each pack was counted by kind' } : null,
      { label: 'Average day', value: I.sizeText(s.avgMB), note: 'over the ' + s.withPacks + ' days that had a pack' },
      s.peak ? { label: 'Busiest day', value: I.sizeText(I.dayTotal(s.peak)), note: fmtDate(s.peak.d) } : null,
      found.length ? { label: 'Those counts, in all', value: I.bytesText(size), note: 'on disk, as the packs are sent' } : null,
    ].filter(Boolean).map((x) => el('div', { class: 'dr-tile' }, el('dt', { text: x.label }), el('dd', { text: x.value }), el('small', { text: x.note }))));
  }

  /* ---------- the life of a well, in images ---------- */
  function lifeCard() {
    const packs = I.PACKS.map((p) => (latest[p.id] ? latest[p.id].p : { ...p, present: false }));
    const life = I.lifecycle(packs);
    const cols = life.map((s, i) => el('li', { class: 'img-stage' },
      el('div', { class: 'img-st-head' }, el('span', { class: 'img-num', 'aria-hidden': 'true', text: String(i + 1) }), el('h3', { text: s.label })),
      el('p', { class: 'img-blurb', text: s.blurb }),
      s.kinds ? el('ul', { class: 'img-kinds' }, s.kinds.map((k) => el('li', {}, el('span', { class: 'img-kn', text: k.k, title: I.kindInfo(k.k) }), el('span', { class: 'img-kv', text: fmt.format(k.n) }), el('small', { text: I.kindInfo(k.k) }))))
        : el('p', { class: 'nd', text: 'Not counted by kind yet.' }),
      s.present && s.n != null ? el('p', { class: 'fine', text: fmt.format(s.n) + ' documents' + (s.packets ? ' in ' + s.packets + ' packets' : '') + ', ' + I.bytesText(s.bytes) + ', counted for ' + fmtDate(latest[s.pack].day) + '.' }) : null));
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('A well, in images', 'rig', 'What a well leaves behind', 'Counted by kind for the newest day each pack was captured live. Documents are told apart by their file names.'),
      el('ol', { class: 'img-life' }, cols));
  }

  /* ---------- day by day ---------- */
  function chart() {
    const W = 720; const H = 230; const L = 52; const R = 6; const T = 8; const B = 22;
    const n = rows.length; const slot = (W - L - R) / Math.max(1, n); const bw = Math.max(2, slot * 0.78);
    const { top, ticks } = niceMax(Math.max(1, ...rows.map(I.dayTotal)));
    const y = (v) => T + (H - T - B) * (1 - v / top);
    const g = svg('svg', { class: 'nat-chart', viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'Size of the three image packs by report day, ' + short(rows[0].d) + ' to ' + short(rows[n - 1].d) + '; the day list below chooses a day' });
    ticks.forEach((t) => g.append(svg('line', { class: t === 0 ? 'base' : 'grid', x1: L, x2: W - R, y1: y(t), y2: y(t) }), svg('text', { class: 'ax', x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: t + ' MB' })));
    rows.forEach((r, i) => {
      const x = L + slot * i + (slot - bw) / 2; let acc = 0;
      I.PACKS.forEach((p) => {
        const v = r[p.id]; if (!v) return;
        const seg = svg('rect', { class: 'nat-bar-seg' + (r.d === day ? ' on' : ''), x: x.toFixed(1), width: bw.toFixed(1), y: y(acc + v).toFixed(1), height: Math.max(0.5, y(acc) - y(acc + v)).toFixed(1) });
        seg.style.setProperty('--c', p.color); g.append(seg); acc += v;
      });
      if (r.d.slice(8) === '01' || i === 0) g.append(svg('text', { class: 'ax', x: x + bw / 2, y: H - 6, 'text-anchor': i === 0 ? 'start' : 'middle', text: short(r.d) }));
      const hit = svg('rect', { class: 'nat-hit', x: (L + slot * i).toFixed(1), y: T, width: slot.toFixed(1), height: H - T - B });
      hit.addEventListener('pointermove', (e) => showTip([el('div', { class: 'tip-head', text: fmtDate(r.d) }), ...(I.havePacks(r) ? I.PACKS.map((p) => tipRow(I.sizeText(r[p.id]), p.label)) : [tipRow('No pack listed', '')])], e.clientX, e.clientY));
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('click', () => choose(r.d));
      g.append(hit);
    });
    const key = el('ul', { class: 'nat-keys nat-chart-keys', 'aria-label': 'The three packs' }, I.PACKS.map((p) => { const sw = el('i', { class: 'nat-sw' }); sw.style.setProperty('--c', p.color); return el('li', { class: 'nat-key' }, sw, el('span', { text: p.label })); }));
    return [key, g];
  }
  function dayCard() {
    const sel = el('select', { class: 'input img-day', 'aria-label': 'Choose a report day' }, rows.slice().reverse().filter(I.havePacks).map((r) => el('option', { value: r.d, text: fmtDate(r.d) + (r.live ? ' (captured live)' : '') })));
    sel.addEventListener('change', () => choose(sel.value));
    slots.select = sel;
    slots.chart = el('div', {});
    slots.chart.replaceChildren(...chart());
    return el('section', { class: 'card nat-card reveal is-in' }, hdr('Day by day', 'chart', 'How much arrives each day', 'Gaps are days with no pack listed (weekends, and packs that land the next morning): never zero. Click a day, or choose one.', el('div', { class: 'card-tools' }, sel)), slots.chart,
      el('details', { class: 'nat-details' }, el('summary', { text: 'Show the sizes as a table' }),
        el('div', { class: 'table-wrap tall', tabindex: '0', role: 'region', 'aria-label': 'Pack sizes by day' }, el('table', { class: 'grid' },
          el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: 'Report day' }), I.PACKS.map((p) => el('th', { scope: 'col', class: 'num', text: p.label + ' (MB)' })))),
          el('tbody', {}, rows.slice().reverse().map((r) => el('tr', {}, el('th', { scope: 'row', text: fmtDate(r.d) }), I.PACKS.map((p) => el('td', { class: 'num', text: r[p.id] == null ? '—' : String(r[p.id]) })))))))));
  }

  /* ---------- one day ---------- */
  const CODE = { w1images: 'w1', dirsurveys: 'ds', complimages: 'ci' };
  function tieNote(p, wi) {
    const t = wi && p.packDay ? tieLine(wi, p.packDay, CODE[p.id]) : null;
    if (!t) return null;
    return el('p', { class: 'fine', text: t.tied ? fmt.format(t.tied) + ' of its ' + fmt.format(t.docs) + ' documents are published under ' + fmt.format(t.wells) + ' wells (Find a well, above).' + (t.untied ? ' ' + fmt.format(t.untied) + ' could not be tied to a well and are not published.' : '') : 'None of its ' + fmt.format(t.docs) + ' documents could be tied to a well, so none is published.' });
  }
  function dayPanel(file, d, wi) {
    const packs = I.packsOf(file);
    const filed = I.filedPermits(file);
    const rel = file && file.release;
    const body = el('div', { class: 'img-day-body' }, packs.map((p) => {
      if (!p.present) return el('div', { class: 'img-pack' }, el('h3', { text: p.label }), el('p', { class: 'nd', text: 'No pack listed for this day.' }));
      const top = Math.max(1, ...p.districts.map((x) => x.bytes));
      return el('div', { class: 'img-pack' },
        el('h3', {}, p.label, el('span', { class: 'badge', text: I.bytesText(p.bytes) })),
        p.empty ? el('p', { class: 'nd', text: 'The pack was listed empty.' }) : null,
        p.kinds ? el('ul', { class: 'img-kinds compact' }, p.kinds.map((k) => el('li', {}, el('span', { class: 'img-kn', text: k.k, title: I.kindInfo(k.k) }), el('span', { class: 'img-kv', text: fmt.format(k.n) })))) : el('p', { class: 'fine', text: 'Documents are counted by kind only for days captured live.' }),
        tieNote(p, wi),
        p.districts.length ? el('div', { class: 'nat-list' }, el('h4', { text: 'Size by RRC district' }), el('ul', {}, p.districts.slice(0, 8).map((x) => {
          const bar = el('i', { class: 'nat-lb' }); bar.style.setProperty('--p', String(x.bytes / top));
          return el('li', {}, el('span', { class: 'nat-ln', text: 'District ' + x.d }), el('span', { class: 'nat-lt' }, bar), el('span', { class: 'nat-lv', text: I.bytesText(x.bytes) }));
        }))) : null,
        p.sheet ? el('figure', { class: 'img-sheet' }, el('img', { src: 'data/daily/img/' + p.sheet, alt: 'A contact sheet of the first pages of sixteen documents in the ' + p.label.toLowerCase() + ', shrunk and blurred so nothing can be read', loading: 'lazy' }), el('figcaption', { class: 'fine', text: 'First pages of sixteen documents, shrunk and blurred.' })) : null);
    }));
    // page one of each published document, readable (a click opens it larger, with a link to the original); only the documents the release was confirmed to hold a preview of
    const pages = (docs, title) => docs.filter((x) => x.preview).map((x) => ({ title, label: x.label, type: x.type, preview: x.preview, original: x.original }));
    const surveys = I.filedSurveys(file).filter((x) => x.doc.preview);
    const seen = filed.slice(0, 12).reduce((t, f) => t + pages(f.docs, '').length, 0) + Math.min(12, surveys.length);
    const files = filed.length ? el('div', { class: 'nat-sub' }, el('h4', { text: 'Permits whose filings are published (' + filed.length + ')' }),
      el('ul', { class: 'img-files' + (seen ? ' pv' : '') }, filed.slice(0, 12).map((f) => el('li', {}, el('a', { href: '#daily?st=tx&d=' + d + '&drill=' + f.permit, text: 'Permit ' + f.permit }), el('small', { text: ' county ' + f.county + ', district ' + f.district + ' · ' + f.files.map(I.fileKind).join(', ') }),
        pages(f.docs, 'Permit ' + f.permit).length ? previewGrid(pages(f.docs, 'Permit ' + f.permit)) : null))),
      filed.length > 12 ? el('p', { class: 'fine', text: 'and ' + (filed.length - 12) + ' more in the Daily report.' }) : null,
      rel ? el('p', { class: 'fine', text: 'The files are the Commission’s scans, on one GitHub release for the day (' + rel.files + ' files' + (rel.previews ? ', ' + rel.previews + ' with a readable preview' : '') + ').' }) : null) : null;
    const surveyBlock = surveys.length ? el('div', { class: 'nat-sub' }, el('h4', { text: 'Directional surveys with a preview (' + surveys.length + ')' }),
      previewGrid(surveys.slice(0, 12).map((x) => ({ title: 'Survey ' + x.id, label: x.doc.label, type: x.doc.type, preview: x.doc.preview, original: x.doc.original }))),
      surveys.length > 12 ? el('p', { class: 'fine', text: 'The first 12 of ' + surveys.length + '; each survey has a page of its own in the Daily report.' }) : null) : null;
    const privacy = seen ? el('p', { class: 'fine', text: 'Each preview is page one of a document the Commission publishes, drawn as a picture: readable, nothing blurred, cropped or hidden. They are public records and can carry the names, phone numbers and addresses of individuals. Click a page to enlarge it.' }) : null;
    return el('div', {}, body, files, surveyBlock, privacy, el('p', { class: 'nat-links' }, el('a', { class: 'more-link', href: '#daily?st=tx&d=' + d }, 'The Daily report for ' + fmtDate(d), icon('arrow', 16))));
  }
  async function choose(d, { fromHash = false } = {}) {
    const r = rows.find((x) => x.d === d && I.havePacks(x));
    day = r ? r.d : (rows.slice().reverse().find(I.havePacks) || {}).d || null;
    // an address that names a day the archive does not hold (or has no pack for) shows the newest day: the address says so too, and so does a line on the page
    const missed = !!d && day !== d;
    slots.note.textContent = missed && day ? 'The archive has no pack for ' + (/^\d{4}-\d\d-\d\d$/.test(d) ? fmtDate(d) : 'that day') + ' (it holds the last ' + rows.length + ' days). This is the newest day with one.' : '';
    if (slots.select && day) slots.select.value = day;
    slots.chart.replaceChildren(...chart());
    if (!day) { slots.day.replaceChildren(el('p', { class: 'nd', text: 'No day with a pack yet.' })); return; }
    slots.day.replaceChildren(el('p', { class: 'status', text: 'Loading ' + fmtDate(day) + '…' }));
    const mine = day;
    const [file, wi] = await Promise.all([loadOpt('daily/' + day), loadOpt('wells/index')]);
    if (mine !== day) return; // another day was chosen meanwhile
    slots.dayHead.textContent = fmtDate(day);
    slots.day.replaceChildren(file ? dayPanel(file, day, wi) : el('p', { class: 'nd', text: 'The report for this day could not be loaded.' }));
    if (!fromHash || missed) writeHash();
  }

  async function build() {
    slots.rest = el('div', { class: 'stack' }, el('p', { class: 'status', text: 'Loading the image archive…' }));
    root.replaceChildren(el('div', { class: 'stack' }, wells.node, slots.rest));
    let index;
    try { index = await load('daily/index'); } catch (e) {
      slots.rest.replaceChildren(el('div', { class: 'fail' }, el('p', { text: 'Could not load the day-by-day archive. Reload the page to try again.' })));
      return false;
    }
    rows = I.daySeries(index);
    // for each pack, the newest day captured live whose file counted its documents (the W-1 pack lands the morning after, so it is often a day behind the others)
    for (const d of I.liveCandidates(rows).slice(0, 6)) {
      if (Object.keys(latest).length === I.PACKS.length) break;
      const file = await loadOpt('daily/' + d);
      if (file) I.packsOf(file).filter((p) => p.kinds && !latest[p.id]).forEach((p) => { latest[p.id] = { day: d, p }; });
    }
    slots.day = el('div', {}); slots.dayHead = el('h2', { text: '' }); slots.note = el('p', { class: 'fine' });
    const dayBox = el('section', { class: 'card nat-card reveal is-in', 'aria-live': 'polite' }, el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon('calendar', 15), 'One day'), slots.dayHead, el('p', { class: 'sub', text: 'What the three packs of this report day hold.' }), slots.note)), slots.day);
    slots.rest.replaceChildren(figures(), lifeCard(), dayCard(), dayBox,
      el('p', { class: 'fine', text: 'The Railroad Commission’s filings are public records. The sheets here are shrunk and blurred; every document itself is published readable and unmodified under its well (Find a well, above), and can carry the names, phone numbers and addresses of individuals. A day’s permit letters, plats and surveys also show page one here and on their drill page in the Daily report.' }));
    return true;
  }
  return {
    async activate(params) {
      const well = wells.show({ well: params && params.get('well'), c: params && params.get('c'), q: params && params.get('q') });
      if (!building) building = build().then((ok) => { if (!ok) building = null; else wantedDay = undefined; return ok; });
      if (!(await building)) { await well; return; }
      const want = (params && params.get('d')) || null;
      if (want !== wantedDay || !day) { wantedDay = want; await choose(want, { fromHash: true }); } // a well or a county chosen does not reload the day
      await well;
    },
    deactivate() { hideTip(); wells.hide(); },
  };
}
