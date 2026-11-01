// The well finder at the top of the Texas images page: type an API number or choose a county, open a well, and read the scanned documents the Railroad Commission
// published about it (the permit letter and plat, the directional survey, the completion forms and logs), each with a readable picture of its first page and the whole
// document as filed. Data: data/wells/index.json and one data/wells/county/<fips>.json (d12_wells.py); the pictures and documents are files of GitHub releases.
// Nothing here is an address that opens a Commission page: the Commission has none for a single document (the links at the end are its look-up forms).
import { el, load, loadOpt, fmt, fmtDate } from './util.js';
import { icon } from './icons.js';
import * as W from './wells-data.js';

const PAGE = 40; // wells shown at a time in a county
const hdr = (eyebrow, ic, title, sub) => el('div', { class: 'card-head' }, el('div', {}, el('p', { class: 'eyebrow' }, icon(ic, 15), eyebrow), el('h2', { text: title }), sub ? el('p', { class: 'sub', text: sub }) : null));
const plural = (n, one, many) => fmt.format(n) + ' ' + (n === 1 ? one : many);
const go = (params) => { const q = new URLSearchParams(); Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v); }); location.hash = '#images' + (q.toString() ? '?' + q : ''); };

export function createWellsPanel() {
  let index = null; let ready = false; let seq = 0; let shown = PAGE; let last = {};
  const shards = new Map();
  const S = {}; // the nodes that change

  /* ---------- the viewer: page one, large, over the page ---------- */
  const viewer = el('dialog', { class: 'well-viewer', 'aria-labelledby': 'well-viewer-title' });
  viewer.addEventListener('click', (e) => { if (e.target === viewer) viewer.close(); });
  function readDoc(x, well) {
    const kind = x.k + ' of well ' + W.apiText(well.a);
    const close = el('button', { class: 'ibtn', type: 'button', 'aria-label': 'Close the document', onclick: () => viewer.close() }, icon('close', 18));
    const img = el('img', { src: x.preview, alt: 'Page 1 of the ' + kind + (x.pg > 1 ? ' (' + x.pg + ' pages)' : ''), decoding: 'async' });
    const page = el('div', { class: 'well-viewer-page' }, img);
    img.addEventListener('error', () => page.replaceChildren(el('p', { class: 'nd', text: 'The picture could not be loaded from GitHub. The document itself is linked below.' })));
    viewer.replaceChildren(
      el('div', { class: 'well-viewer-head' }, el('div', {}, el('h3', { id: 'well-viewer-title', text: x.k }), el('p', { class: 'fine', text: 'Well ' + W.apiText(well.a) + ' · ' + W.docMeta(x) })), close),
      page,
      el('div', { class: 'well-viewer-foot' },
        el('div', { class: 'well-doc-actions' }, x.file ? el('a', { class: 'btn primary sm', href: x.file, rel: 'noopener noreferrer' }, 'Download the whole document (' + x.x.toUpperCase() + ')') : null,
          x.pg > 1 ? el('span', { class: 'fine', text: 'This is page 1 of ' + x.pg + '.' }) : null),
        el('p', { class: 'fine', text: 'A scan of a public record, exactly as the Railroad Commission published it. It can carry the names, phone numbers and addresses of individuals.' })));
    if (typeof viewer.showModal === 'function') viewer.showModal(); else viewer.setAttribute('open', '');
  }

  /* ---------- the top: one line of figures, the form, the places to start ---------- */
  function summaryLine() {
    const h = W.headline(index);
    if (!h) return null;
    const when = covers();
    return el('p', { class: 'wells-summary' }, [plural(h.wells, 'well', 'wells') + ' in ' + plural(h.counties, 'county', 'counties'), plural(h.docs, 'document', 'documents'), W.bytesText(h.bytes) + ' on GitHub', when]
      .flatMap((t, i) => (i ? [el('span', { class: 'wells-sep', 'aria-hidden': 'true', text: '·' }), t] : [t])));
  }
  const covers = () => { const h = W.headline(index); return h.oldest !== h.newest ? 'the packs of ' + fmtDate(h.oldest) + ' to ' + fmtDate(h.newest) : 'the packs of ' + fmtDate(h.newest); };
  const stageKey = () => el('p', { class: 'well-key fine', 'aria-hidden': 'true' }, 'Documents per well:', W.STAGE_ORDER.map((k) => { const dot = el('i'); dot.style.setProperty('--c', W.STAGE[k].color); return el('span', {}, dot, W.STAGE[k].label); }));

  function search() {
    const text = S.input.value.trim();
    const api = W.parseApi(text);
    if (api && api.api8) return go({ well: api.api8 });
    if (api) return go({ c: api.county, q: api.digits.length > 3 ? api.digits : '' });
    if (S.select.value) return go({ c: S.select.value, q: text });
    S.status.textContent = 'Type an API number (at least the three digits of its county, like 42-283-37830) or choose a county.';
  }

  function landing() {
    const top = W.countyChoices(index).slice(0, 12);
    S.status.textContent = '';
    S.well.hidden = true; S.list.hidden = false;
    S.list.replaceChildren(el('p', { class: 'fine', text: 'Counties with the most wells' }),
      el('ul', { class: 'wells-chips' }, top.map((c) => el('li', {}, el('a', { href: '#images?c=' + c.fips }, c.name, el('small', { text: fmt.format(c.wells) }))))));
  }

  /* ---------- a county's wells ---------- */
  function counts(w) {
    const s = W.summary(w);
    return el('span', { class: 'well-counts', 'aria-label': W.STAGE_ORDER.map((k) => plural(s.n[k], W.STAGE[k].id + ' document', W.STAGE[k].id + ' documents')).join(', ') },
      W.STAGE_ORDER.map((k) => { const dot = el('i'); dot.style.setProperty('--c', W.STAGE[k].color); return el('span', { 'aria-hidden': 'true', title: W.STAGE[k].label }, dot, String(s.n[k])); }));
  }
  function renderList(shard, q) {
    const all = W.rank(W.matchWells(shard.wells, q));
    S.well.hidden = true; S.list.hidden = false;
    const head = el('div', { class: 'wells-head' }, el('h3', { text: shard.name + ' County' }), stageKey(), el('span', { class: 'fine', text: q ? plural(all.length, 'well', 'wells') + ' match “' + q + '” of ' + fmt.format(shard.wells.length) : plural(shard.wells.length, 'well', 'wells') + ' with filings' }));
    if (!all.length) {
      S.list.replaceChildren(head, el('p', { class: 'nd', text: 'No well in ' + shard.name + ' County matches that. Try the start of its API number, a field or an operator, or clear the search.' }));
      return;
    }
    const rows = all.slice(0, shown).map((w) => {
      const what = [w.fl ? w.fl : null, w.on ? w.on : w.o ? 'operator ' + w.o : null, w.di ? 'District ' + w.di : null].filter(Boolean).join(' · ');
      return el('li', {}, el('a', { class: 'well-row', href: '#images?well=' + w.a + '&c=' + shard.county }, el('span', { class: 'well-api', text: W.apiText(w.a) }), el('span', { class: 'well-what', text: what || 'No field or operator recorded' }), counts(w)));
    });
    const more = all.length > shown ? el('button', { class: 'btn', type: 'button', onclick: () => { shown += PAGE; renderList(shard, q); } }, 'Show ' + Math.min(PAGE, all.length - shown) + ' more') : null;
    S.list.replaceChildren(head, el('ul', { class: 'wells-list' }, rows), more);
    S.status.textContent = '';
  }

  /* ---------- one well ---------- */
  const lookups = () => el('div', { class: 'well-lookups' },
    el('p', { class: 'fine', text: 'Also at the Railroad Commission. Its look-up forms take the API number; it has no address that opens a single document, which is why the documents are kept here.' }),
    el('ul', { class: 'img-files' }, W.RRC_LOOKUPS.map((l) => el('li', {}, el('a', { href: l.href, rel: 'noopener noreferrer' }, l.label), el('small', { text: ' · takes the ' + l.takes })))));

  function docCard(x, well) {
    const meta = W.docMeta(x);
    const thumb = x.preview
      ? el('button', { class: 'well-thumb', type: 'button', 'aria-label': 'Read the ' + x.k + ' (' + meta + ')', onclick: () => readDoc(x, well) }, el('img', { src: x.preview, alt: '', loading: 'lazy', decoding: 'async', width: 84, height: 109 }))
      : el('div', { class: 'well-thumb none', 'aria-hidden': 'true' }, el('span', { text: x.x.toUpperCase() }));
    return el('li', { class: 'well-doc' }, thumb,
      el('div', { class: 'well-doc-body' }, el('strong', { text: x.k, title: W.KIND_INFO[x.k] || '' }), el('small', { text: meta }), el('small', { text: 'In the pack of ' + fmtDate(x.d) }),
        el('div', { class: 'well-doc-actions' }, x.preview ? el('button', { class: 'btn sm', type: 'button', onclick: () => readDoc(x, well) }, 'Read') : null,
          x.file ? el('a', { class: 'btn sm', href: x.file, rel: 'noopener noreferrer' }, 'Download ' + x.x.toUpperCase()) : null,
          !x.preview ? el('small', { text: 'No picture could be drawn' }) : null)));
  }

  function renderWell(shard, api) {
    const well = shard.wells.find((w) => w.a === api);
    S.list.hidden = true; S.well.hidden = false;
    const back = el('a', { class: 'more-link wells-back', href: '#images?c=' + shard.county + (last.q ? '&q=' + encodeURIComponent(last.q) : '') }, 'All wells in ' + shard.name + ' County');
    if (!well) {
      S.well.replaceChildren(back, el('h3', { text: 'Well ' + W.apiText(api) }),
        el('p', { class: 'nd', text: 'None of the packs read so far holds a document for this well. The archive holds ' + covers() + ', so a well whose filings are older, or not yet published, is not here.' }), lookups());
      return;
    }
    const docs = W.docsOf(index.repo, shard, well);
    const s = W.summary(well);
    const facts = [shard.name + ' County', well.di ? 'District ' + well.di : null, well.fl, well.on || (well.o ? 'Operator ' + well.o + ' (not named here)' : null)].filter(Boolean);
    const stages = W.byStage(docs).map((st, i) => el('li', { class: 'img-stage' },
      el('div', { class: 'img-st-head' }, el('span', { class: 'img-num', 'aria-hidden': 'true', text: String(i + 1) }), el('h3', { text: st.label }), el('span', { class: 'badge', text: String(st.docs.length) })),
      el('p', { class: 'img-blurb', text: W.blurb(st.stage) }),
      st.docs.length ? el('ul', { class: 'well-docs' }, st.docs.map((x) => docCard(x, well))) : el('p', { class: 'nd', text: 'Nothing of this kind in ' + covers() + '.' })));
    const title = el('h3', { class: 'well-title', tabindex: '-1', text: 'Well ' + W.apiText(well.a) });
    S.well.replaceChildren(back, title, el('p', { class: 'sub', text: facts.join(' · ') }),
      el('p', { class: 'fine', text: plural(s.docs, 'document', 'documents') + ', ' + W.bytesText(s.bytes) + ', newest from the pack of ' + fmtDate(s.newest) + '. Page one of each is shown here; the download is the whole document, exactly as filed.' }),
      el('ol', { class: 'img-life' }, stages), lookups());
    title.focus({ preventScroll: true });
  }

  /* ---------- the card ---------- */
  function build() {
    S.input = el('input', { class: 'input wells-q', type: 'search', placeholder: 'API number, like 42-283-37830', 'aria-label': 'API number, or the start of a field or operator name', autocomplete: 'off', enterkeyhint: 'search' });
    S.select = el('select', { class: 'input wells-county', 'aria-label': 'County' }, el('option', { value: '', text: 'Choose a county' }),
      W.countyChoices(index).map((c) => el('option', { value: c.fips, text: c.name + ' · ' + plural(c.wells, 'well', 'wells') })));
    S.select.addEventListener('change', () => { if (S.select.value) go({ c: S.select.value, q: S.input.value.trim() && !W.parseApi(S.input.value) ? S.input.value.trim() : '' }); });
    S.status = el('p', { class: 'status', 'aria-live': 'polite' });
    S.list = el('div', { class: 'wells-results' });
    S.well = el('div', { class: 'well-one', 'aria-live': 'polite', hidden: true });
    const form = el('form', { class: 'wells-form', role: 'search', 'aria-label': 'Find a well' }, S.input, S.select, el('button', { class: 'btn primary', type: 'submit' }, 'Find'));
    form.addEventListener('submit', (e) => { e.preventDefault(); search(); });
    return [hdr('Find a well', 'pin', 'Every scanned filing, tied to its well', 'Type an API number or choose a county, then open a well: its permit letter and plat, its directional survey and its completion forms and logs, readable here and downloadable as filed.'),
      form, summaryLine(), S.status, S.list, S.well, viewer];
  }

  const node = el('section', { class: 'card nat-card reveal is-in', id: 'wells-find' });

  async function ensure() {
    if (ready) return;
    node.replaceChildren(hdr('Find a well', 'pin', 'Every scanned filing, tied to its well'), el('p', { class: 'status', text: 'Loading the well archive…' }));
    index = await loadOpt('wells/index');
    ready = true;
    if (!index || !W.headline(index)) {
      node.replaceChildren(hdr('Find a well', 'pin', 'Every scanned filing, tied to its well', 'Each document the Railroad Commission publishes about a well will be listed under the well it belongs to.'),
        el('p', { class: 'nd', text: index ? 'The archive is empty so far: the first packs are read and published after the next run.' : 'The well archive could not be loaded. Reload the page to try again.' }));
      index = null;
      return;
    }
    node.replaceChildren(...build());
  }

  async function shardOf(fips) {
    if (!(index.counties || []).some((c) => c[0] === fips)) return null; // a county the index does not list has no file: no request, no 404
    if (!shards.has(fips)) shards.set(fips, load('wells/county/' + fips).catch(() => null));
    return shards.get(fips);
  }

  return {
    node,
    // params: {well: 8 digits, c: 3 digits, q: text}, from the address
    async show(p) {
      const mine = ++seq;
      await ensure();
      if (!index || mine !== seq) return;
      const well = /^\d{8}$/.test(p.well || '') ? p.well : null;
      const fips = well ? well.slice(0, 3) : /^\d{3}$/.test(p.c || '') ? p.c : null;
      const q = well ? '' : (p.q || '').slice(0, 60);
      if (last.fips !== fips || last.q !== q) shown = PAGE;
      last = { fips, q, well };
      S.select.value = fips && [...S.select.options].some((o) => o.value === fips) ? fips : '';
      S.input.value = well ? W.apiText(well) : q;
      if (!fips) { landing(); return; }
      S.status.textContent = 'Loading…';
      const shard = await shardOf(fips);
      if (mine !== seq) return;
      S.status.textContent = '';
      if (!shard) {
        S.well.hidden = true; S.list.hidden = false;
        S.list.replaceChildren(el('p', { class: 'nd', text: 'No document in the archive belongs to a well in county ' + fips + '. The archive holds ' + covers() + '.' }), lookups());
        node.scrollIntoView({ block: 'start' });
        return;
      }
      if (well) renderWell(shard, well); else renderList(shard, q);
      node.scrollIntoView({ block: 'start' });
    },
    hide() { if (viewer.open) viewer.close(); },
  };
}
