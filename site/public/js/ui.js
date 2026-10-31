// Shared UI pieces: segmented tabs with a sliding thumb, toast, clipboard + share button, reveal-on-scroll, nav indicator.
import { $, $$, el, reduced } from './util.js';
import { icon } from './icons.js';
import { activeStates, stateParam } from './states.js';

/* segmented control. tabs=true: an ARIA tablist (arrow keys, roving tabindex); tabs=false: toggle buttons (aria-pressed) */
export function segmented({ label, options, value, onChange, tabs = true, prefix = 'seg' }) {
  const thumb = el('span', { class: 'seg-thumb', 'aria-hidden': 'true' });
  const btns = options.map((o) => el('button', {
    type: 'button', 'data-id': o.id, id: prefix + '-' + o.id, role: tabs ? 'tab' : null,
    'aria-selected': tabs ? 'false' : null, 'aria-pressed': tabs ? null : 'false', 'aria-controls': o.controls || null, tabindex: tabs ? '-1' : null,
  }, o.icon ? icon(o.icon, 15) : null, o.dot ? el('i', { class: 'seg-dot ' + o.dot, 'aria-hidden': 'true' }) : null, el('span', { text: o.label })));
  const root = el('div', { class: 'seg', role: tabs ? 'tablist' : 'group', 'aria-label': label }, thumb, btns);
  let cur = null;
  const place = () => {
    const b = btns.find((x) => x.dataset.id === cur);
    if (!b || !b.offsetWidth) return;
    root.style.setProperty('--tx', b.offsetLeft + 'px'); root.style.setProperty('--tw', b.offsetWidth + 'px');
  };
  function set(id, fire = true, focus = false) {
    if (!btns.some((b) => b.dataset.id === id)) return;
    cur = id;
    btns.forEach((b) => {
      const on = b.dataset.id === id;
      if (tabs) { b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; } else b.setAttribute('aria-pressed', String(on));
    });
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
  if ('ResizeObserver' in window) new ResizeObserver(place).observe(root);
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
  }, icon('share', 16), el('span', { text: label.split(' ')[0] }), label.includes(' ') ? el('span', { class: 'hide-sm', text: ' ' + label.split(' ').slice(1).join(' ') }) : null);
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

/* nav: a pill that slides to the current link */
export function navIndicator(nav) {
  const ind = el('span', { class: 'nav-ind snap', 'aria-hidden': 'true' });
  nav.prepend(ind);
  const place = () => {
    const a = $('a[aria-current="page"]', nav);
    if (!a || !a.offsetWidth) { ind.classList.remove('on'); return; }
    nav.style.setProperty('--nx', a.offsetLeft + 'px'); nav.style.setProperty('--nw', a.offsetWidth + 'px');
    ind.classList.add('on');
    if (nav.scrollWidth > nav.clientWidth) nav.scrollLeft = Math.max(0, a.offsetLeft - 40);
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
