// Shared UI pieces: segmented tabs with a sliding thumb, toast, clipboard + share button, reveal-on-scroll, nav indicator.
import { $, $$, el, reduced } from './util.js';
import { icon } from './icons.js';
import { activeStates, stateParam } from './states.js';

/* segmented control. tabs=true: an ARIA tablist (arrow keys, roving tabindex); tabs=false: toggle buttons (aria-pressed) */
export function segmented({ label, options, value, onChange, tabs = true, prefix = 'seg', wrap = false }) {
  const thumb = el('span', { class: 'seg-thumb', 'aria-hidden': 'true' });
  const btns = options.map((o) => el('button', {
    type: 'button', 'data-id': o.id, id: prefix + '-' + o.id, role: tabs ? 'tab' : null,
    'aria-selected': tabs ? 'false' : null, 'aria-pressed': tabs ? null : 'false', 'aria-controls': o.controls || null, tabindex: tabs ? '-1' : null,
    title: o.title || null, 'aria-label': o.title || null, // a short label that stands for a longer name ("Offshore": the federal offshore) says it in full to a screen reader
  }, o.icon ? icon(o.icon, 15) : null, o.dot ? el('i', { class: 'seg-dot ' + o.dot, 'aria-hidden': 'true' }) : null,
  // a label with a short form (a phone shows "OK" for Oklahoma, so every state fits the bar): the long one is hidden there, and the button's name stays the full one
  el('span', { class: o.abbr ? 'seg-l has-abbr' : null, text: o.label }), o.abbr ? el('span', { class: 'seg-a', 'aria-hidden': 'true', text: o.abbr }) : null));
  const root = el('div', { class: wrap ? 'seg wrap' : 'seg', role: tabs ? 'tablist' : 'group', 'aria-label': label }, thumb, btns);
  let cur = null;
  // a bar whose labels have short forms ("OK" for Oklahoma) shows the full labels while they fit and, when they do not, the short ones, then tighter buttons.
  // It measures instead of guessing from the page's width: the same words are wider in one system font than in another (the full names need 429 px in one, 466 in another)
  const hasAbbr = options.some((o) => o.abbr);
  function fit() {
    if (!hasAbbr) return;
    for (const f of ['full', 'short', 'tight']) {
      root.dataset.fit = f;
      if (root.scrollWidth <= root.clientWidth + 1) break;
    }
  }
  const place = () => {
    const b = btns.find((x) => x.dataset.id === cur);
    if (!b || !b.offsetWidth) return;
    root.style.setProperty('--tx', b.offsetLeft + 'px'); root.style.setProperty('--tw', b.offsetWidth + 'px');
  };
  function set(id, fire = true, focus = false) {
    if (id !== null && !btns.some((b) => b.dataset.id === id)) return;
    cur = id; // null: none chosen (the states bar when an address names two of the three states)
    btns.forEach((b) => {
      const on = id !== null && b.dataset.id === id;
      if (tabs) { b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; } else b.setAttribute('aria-pressed', String(on));
    });
    if (id === null) { root.style.setProperty('--tw', '0px'); return; }
    place();
    const b = btns.find((x) => x.dataset.id === id);
    if (focus) b.focus({ preventScroll: true });
    if (root.scrollWidth > root.clientWidth) root.scrollLeft = Math.max(0, b.offsetLeft - 24);
    if (fire && onChange) onChange(id);
  }
  root.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) set(b.dataset.id); });
  root.addEventListener('keydown', (e) => {
    if (!tabs) return;
    const i = btns.findIndex((b) => b.dataset.id === cur);
    const to = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? btns.length - 1 : null;
    if (to == null) return;
    e.preventDefault();
    set(btns[(to + btns.length) % btns.length].dataset.id, true, true);
  });
  const refit = () => { fit(); place(); };
  if ('ResizeObserver' in window) new ResizeObserver(refit).observe(root);
  if (hasAbbr) window.addEventListener('resize', refit); // the bar's own size does not change when the page grows wide enough for the full names again
  fit();
  set(value, false);
  return { el: root, set, place, buttons: btns, get value() { return cur; } };
}

/* toast: one polite live region at the bottom of the page */
let toastEl = null; let toastTimer = 0;
export function toast(message, { copy = '', ms = 2600 } = {}) {
  if (!toastEl) { toastEl = el('div', { class: 'toast', role: 'status', 'aria-live': 'polite' }); document.body.append(toastEl); }
  const field = copy ? el('input', { readonly: true, value: copy, 'aria-label': 'Link to copy' }) : null;
  toastEl.replaceChildren(...[icon('check', 18), el('span', { text: message }), field].filter(Boolean));
  toastEl.classList.add('on');
  if (field) { field.focus(); field.select(); }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('on'), copy ? 9000 : ms);
}

/* clipboard: the async API when the page is secure, a hidden textarea otherwise */
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch (e) { /* denied: fall through to the textarea */ }
  const ta = el('textarea', { readonly: true, 'aria-hidden': 'true', tabindex: '-1' });
  ta.value = text;
  ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '0'; ta.style.opacity = '0';
  document.body.append(ta); ta.select(); ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

export function shareButton(getUrl, label = 'Share this view') {
  return el('button', {
    type: 'button', class: 'btn', title: 'Copy a link to exactly what you see now',
    onclick: async () => {
      const url = getUrl();
      if (await copyText(url)) toast('Link copied to the clipboard'); else toast('Copy this link', { copy: url });
    },
  }, icon('share', 16), el('span', null, label.split(' ')[0], label.includes(' ') ? el('span', { class: 'hide-sm', text: ' ' + label.split(' ').slice(1).join(' ') }) : null)); // one label, so the gap is a word space and not the icon's gap
}
// a link to a hash that reopens what is on screen, the states shown included
export function absoluteLink(hash) {
  const sp = stateParam(activeStates());
  if (sp && !/[?&]st=/.test(hash)) hash += (hash.includes('?') ? '&' : '?') + 'st=' + sp;
  return location.origin + location.pathname + hash;
}

/* reveal-on-scroll: sections fade up once. Without IntersectionObserver or with reduced motion they simply show. */
export function initReveal() {
  const nodes = $$('.reveal');
  if (!('IntersectionObserver' in window) || reduced()) { nodes.forEach((n) => n.classList.add('is-in')); return; }
  let fired = false;
  const io = new IntersectionObserver((entries) => {
    fired = true;
    // a section already scrolled past (a reload mid-page, a quick jump) shows without a fade it would never be seen doing
    for (const e of entries) if (e.isIntersecting || e.boundingClientRect.bottom < 0) { e.target.classList.add('is-in'); io.unobserve(e.target); }
  }, { rootMargin: '0px 0px -5% 0px', threshold: 0.05 });
  nodes.forEach((n) => io.observe(n));
  // safety net: if the observer never reports (hidden pane), show everything rather than leave blanks
  setTimeout(() => { if (!fired) nodes.forEach((n) => n.classList.add('is-in')); }, 3000);
}

/* the header is one row (brand, tabs, theme toggle) while the three fit side by side at their natural widths: with the brand's tagline when there is room for it (full), without it
   (row), with tighter tabs (compact), and two rows (brand and theme toggle, then the tabs, which scroll) when even those do not fit (stack). It measures instead of using a breakpoint:
   every view added makes the tabs wider, and the same tabs are wider in some fonts (788 px in one, 874 in another, more in a third), so a width that fitted eight tabs pushed the theme
   toggle off the page (data-fit on the row; the measure-* values are the moment of measuring) */
function headerLayout(nav) {
  const row = nav.closest('.top-row');
  if (!row) return;
  const brand = row.querySelector('.brand'); const theme = row.querySelector('.theme');
  const fits = () => {
    const cs = getComputedStyle(row);
    const room = row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    return brand.offsetWidth + nav.offsetWidth + theme.offsetWidth + 2 * (parseFloat(cs.columnGap) || 0) <= room + 0.5;
  };
  const layout = () => {
    let mode = 'stack';
    for (const m of ['full', 'row', 'compact']) {
      row.dataset.fit = 'measure-' + m;
      if (fits()) { mode = m; break; }
    }
    row.dataset.fit = mode;
  };
  layout();
  // only a change of width needs a new layout: the header's own height changes when it stacks, which must not ask for another
  let lastWidth = row.clientWidth;
  if ('ResizeObserver' in window) new ResizeObserver(() => { if (row.clientWidth === lastWidth) return; lastWidth = row.clientWidth; layout(); }).observe(row);
}

/* nav: a pill that slides to the current link */
export function navIndicator(nav) {
  headerLayout(nav);
  const ind = el('span', { class: 'nav-ind snap', 'aria-hidden': 'true' });
  nav.prepend(ind);
  const place = () => {
    const a = $('a[aria-current="page"]', nav);
    if (!a || !a.offsetWidth) { ind.classList.remove('on'); return; }
    nav.style.setProperty('--nx', a.offsetLeft + 'px'); nav.style.setProperty('--nw', a.offsetWidth + 'px');
    ind.classList.add('on');
    // where the tabs scroll, the current tab is brought into view only when it is not already, with some of its neighbor showing: the first tabs stay put while they fit
    if (nav.scrollWidth > nav.clientWidth) {
      const left = a.offsetLeft; const right = left + a.offsetWidth; const pad = 28;
      if (left < nav.scrollLeft + pad) nav.scrollLeft = Math.max(0, left - pad);
      else if (right > nav.scrollLeft + nav.clientWidth - pad) nav.scrollLeft = right - nav.clientWidth + pad;
    }
    edges();
    requestAnimationFrame(() => ind.classList.remove('snap'));
  };
  // where the tabs scroll sideways (a phone), a fade at an edge with more behind it says so
  function edges() {
    const room = nav.scrollWidth - nav.clientWidth;
    const more = room > 2 && nav.scrollLeft < room - 2;
    const before = room > 2 && nav.scrollLeft > 2;
    nav.dataset.more = more ? (before ? 'both' : 'end') : (before ? 'start' : 'none');
  }
  nav.addEventListener('scroll', edges, { passive: true });
  if ('ResizeObserver' in window) new ResizeObserver(place).observe(nav);
  return place;
}
