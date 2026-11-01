// Readable previews of the scanned filings the Railroad Commission publishes about a well (decided 2026-11-01, README, Privacy): page one of a W-1 letter, a plat or a
// directional survey, drawn to a JPEG by the nightly capture (site/pipeline/d7_packs.py) and kept as a file of the day's GitHub release, beside the PDF itself.
// This module only draws them: a grid of small pages, and one native <dialog> that opens a page larger, with a link to the original. A preview that does not load
// says so quietly and leaves the link. Texts go in as text (el()), never as HTML; the pictures are the only thing the page takes from another host (img-src in the CSP).
import { el } from './util.js';
import { icon } from './icons.js';

const MISSING = 'Preview unavailable';
const lower = (t) => t.charAt(0).toLowerCase() + t.slice(1); // a label in the middle of a sentence ("approved W-1 permit"): only its first letter changes
let dlg = null;

// one dialog for the page, made the first time a preview is enlarged
function dialog() {
  if (dlg) return dlg;
  const title = el('h3', { class: 'pv-title', id: 'pv-title' });
  const closeBtn = el('button', { type: 'button', class: 'btn sm pv-close' }, icon('close', 14), 'Close');
  const stage = el('div', { class: 'pv-stage', tabindex: '0', role: 'region', 'aria-label': 'The page, scrollable' });
  const open = el('a', { class: 'btn sm pv-open', rel: 'noopener noreferrer' });
  const note = el('p', { class: 'fine pv-note', text: 'Page one only, as the Commission publishes it, drawn as a picture and nothing more. It is a public record and can carry the names, phone numbers and addresses of individuals.' });
  const d = el('dialog', { class: 'pv-dialog', 'aria-labelledby': 'pv-title' }, el('div', { class: 'pv-head' }, title, closeBtn), stage, el('div', { class: 'pv-foot' }, open, note));
  const state = { opener: null };
  closeBtn.addEventListener('click', () => d.close());
  d.addEventListener('click', (e) => { if (e.target === d) d.close(); }); // a click on the backdrop
  d.addEventListener('close', () => {
    stage.replaceChildren();
    const back = state.opener; state.opener = null;
    if (back && back.isConnected) back.focus(); // the browser does this too; stated so it holds where it does not
  });
  window.addEventListener('hashchange', () => { if (d.open) d.close(); }); // the Back button, or a link in the page: the page behind is another view now
  document.body.append(d);
  dlg = { d, title, stage, open, state };
  return dlg;
}

function enlarge(item, opener) {
  const x = dialog();
  x.state.opener = opener;
  x.title.textContent = item.title + ' · ' + item.label;
  const big = el('img', { class: 'pv-large', src: item.preview, alt: 'Page one of the ' + lower(item.label) + ', ' + lower(item.title), decoding: 'async', referrerpolicy: 'no-referrer' });
  big.addEventListener('error', () => big.replaceWith(el('p', { class: 'pv-miss', text: MISSING + '. The original is linked below.' })));
  x.stage.replaceChildren(big);
  x.stage.scrollTop = 0;
  if (item.original) { x.open.setAttribute('href', item.original); x.open.replaceChildren('Open the original ' + (item.type || 'PDF')); x.open.hidden = false; } else x.open.hidden = true;
  if (!x.d.open) x.d.showModal();
}

// items: [{ title: 'Permit 0919696', label: 'Approved W-1 permit', type: 'PDF', preview: <https address of the JPEG>, original: <address of the document> }]
export function previewGrid(items) {
  return el('ul', { class: 'pv-grid' }, items.map((item) => {
    const img = el('img', { class: 'pv-img', src: item.preview, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
    const thumb = el('button', { type: 'button', class: 'pv-thumb', 'aria-label': 'Enlarge the preview: ' + item.title + ', ' + lower(item.label) }, img);
    thumb.addEventListener('click', () => enlarge(item, thumb));
    // a picture that does not load leaves the words and the link: the page is still there to open
    img.addEventListener('error', () => thumb.replaceWith(el('p', { class: 'pv-miss', text: MISSING })));
    return el('li', { class: 'pv-tile' }, thumb,
      el('div', { class: 'pv-cap' }, el('span', { class: 'pv-label', text: item.label }),
        item.original ? el('a', { class: 'pv-orig', href: item.original, rel: 'noopener noreferrer', 'aria-label': 'Original ' + (item.type || 'PDF') + ': ' + item.title + ', ' + lower(item.label), text: 'Original ' + (item.type || 'PDF') }) : null));
  }));
}
