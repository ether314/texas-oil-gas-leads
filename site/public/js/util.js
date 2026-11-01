// Shared helpers: DOM building (text only, never innerHTML), formatting, data loading, small utilities.
import { activeStates, stateParam } from './states.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function build(node, attrs, kids) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') node.setAttribute('class', v);
    else if (k === 'text') node.textContent = v;
    else if (typeof v === 'function' && k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
// Names and labels come from data files, so they only ever go into the page as text.
export const el = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
export const svg = (tag, attrs, ...kids) => build(document.createElementNS(SVG_NS, tag), attrs, kids);

/* formatting */
export const fmt = new Intl.NumberFormat('en-US');
export const compactFmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
export const stat = (n) => (Math.abs(n) >= 10000 ? compactFmt.format(n) : fmt.format(n));
export const pct = (n, d) => (d ? Math.round((n / d) * 100) + '%' : '0%');
export const share = (n, d) => (d ? ((n / d) * 100).toFixed(1) + '%' : '0%');
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const fmtDate = (iso) => (iso
  ? new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  : '');
export const monthLabel = (ym) => MONTHS[+ym.slice(5, 7) - 1] + ' ' + ym.slice(0, 4);
export const dayLabel = (ms) => {
  const d = new Date(ms);
  return MONTHS[d.getUTCMonth()] + ' ' + d.getUTCDate() + ', ' + d.getUTCFullYear();
};
export const signed = (f) => {
  const p = Math.round(Math.abs(f) * 100);
  return (p === 0 ? '' : f > 0 ? '+' : '−') + p + '%';
};
export const sum = (a, from = 0, to = a.length) => {
  let s = 0;
  for (let i = from; i < to; i++) s += a[i] || 0;
  return s;
};

// Trend from complete calendar months: the last 12 against the 12 before. The day-window "12 month" counts stop at the
// newest permit in the RRC file, so they cover fewer days than the prior window and would read about 6% low.
export function halves(m) {
  const n = m ? m.length : 0;
  if (n < 24) return { a: 0, b: 0, f: null };
  const a = sum(m, n - 12, n); const b = sum(m, n - 24, n - 12);
  return { a, b, f: b > 0 ? (a - b) / b : a > 0 ? Infinity : null };
}

/* data */
const cache = new Map();
// a dropped connection (a phone between towers) or a server hiccup is tried once more after a moment; a missing file (HTTP 4xx) is not, since
// the optional files (a day with no report) are expected to be missing and must not be slowed
const fetchJson = (name, retry) => fetch('data/' + name + '.json').then((r) => {
  if (!r.ok) throw Object.assign(new Error(name + ': HTTP ' + r.status), { status: r.status });
  return r.json();
}).catch((e) => (retry && !(e.status >= 400 && e.status < 500)
  ? new Promise((done) => setTimeout(done, 700)).then(() => fetchJson(name, false))
  : Promise.reject(e)));
export function load(name) {
  if (!cache.has(name)) {
    const p = fetchJson(name, true);
    cache.set(name, p);
    p.catch(() => cache.delete(name));
  }
  return cache.get(name);
}
// optional files: a missing one hides its feature instead of breaking the page
export const loadOpt = (name) => load(name).catch(() => null);
export function toObjects(table) {
  return table.rows.map((row, i) => {
    const o = { _i: i };
    table.cols.forEach((c, j) => { o[c] = row[j]; });
    return o;
  });
}
const memo = new Map();
export function once(key, fn) {
  if (!memo.has(key)) {
    const p = Promise.resolve().then(fn);
    memo.set(key, p);
    p.catch(() => memo.delete(key));
  }
  return memo.get(key);
}

/* time series: monthly points sit on the first of the month (UTC), weekly ones on their publish date */
export const monthMs = (ym) => Date.UTC(+ym.slice(0, 4), +ym.slice(5, 7) - 1, 1);
export const dayMs = (iso) => Date.parse(iso + 'T00:00:00Z');
export function lastIdx(v) { for (let i = v.length - 1; i >= 0; i--) if (v[i] != null) return i; return -1; }
// index of the sample nearest to time t (arrays sorted by time); -1 when the series is empty
export function nearest(ts, t, end = ts.length - 1) {
  let lo = 0; let hi = end;
  if (hi < 0) return -1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (ts[mid] <= t) lo = mid; else hi = mid; }
  return Math.abs(ts[lo] - t) <= Math.abs(ts[hi] - t) ? lo : hi;
}
// change against the same time a year earlier (monthly or weekly alike); null when there is no comparable sample
export function yoy(ts, vs, i) {
  if (i < 1 || vs[i] == null) return null;
  const want = ts[i] - 365 * 864e5; const j = nearest(ts, want, i - 1);
  if (j < 0 || vs[j] == null || vs[j] === 0 || Math.abs(ts[j] - want) > 20 * 864e5) return null;
  return vs[i] / vs[j] - 1;
}

/* misc */
export const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export function debounce(fn, ms) {
  let t = 0;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
const motion = matchMedia('(prefers-reduced-motion: reduce)');
// ?still (QA only) behaves like reduced motion so screenshots are deterministic
export const STILL = /[?&]still\b/.test(location.search);
export const reduced = () => STILL || motion.matches;
export const onReducedChange = (fn) => motion.addEventListener('change', fn);

// calls back once (or on every change) when the node scrolls into view
export function whenVisible(node, cb, { once: one = true, threshold = 0.15 } = {}) {
  if (!('IntersectionObserver' in window)) { cb(true); return () => {}; }
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      cb(e.isIntersecting);
      if (one && e.isIntersecting) io.disconnect();
    }
  }, { threshold });
  io.observe(node);
  return () => io.disconnect();
}

export function countUp(node, to, format = (v) => fmt.format(v), ms = 1000) {
  node.textContent = format(to);
  if (reduced() || !(to > 0)) return;
  node.textContent = format(0);
  const finish = setTimeout(() => { node.textContent = format(to); }, ms + 2500);
  whenVisible(node, () => {
    clearTimeout(finish);
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / ms);
      node.textContent = format(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* hash routing: #view?key=value */
export function parseHash() {
  const raw = location.hash.slice(1);
  const cut = raw.indexOf('?');
  return {
    view: cut < 0 ? raw : raw.slice(0, cut),
    params: new URLSearchParams(cut < 0 ? '' : raw.slice(cut + 1)),
    hasQuery: cut >= 0,
  };
}
// a query as it reads in an address: commas (st=tx,nm) and the colon of a county key (county=OK:129) are left as they are
export const queryText = (params) => params.toString().replace(/%2C/gi, ',').replace(/%3A/gi, ':');
// keeps the address bar in step with the map without firing hashchange. The states shown (st=tx or st=ok, none for both) stay in it.
export function replaceHash(view, params) {
  const sp = stateParam(activeStates());
  if (sp && !params.has('st')) { params = new URLSearchParams(params); params.set('st', sp); }
  const q = queryText(params);
  const next = '#' + view + (q ? '?' + q : '');
  if (location.hash !== next) history.replaceState(null, '', next);
}

// the width (in px) an SVG chart is drawn at: its container's, between min and max, so a phone's chart is drawn at its own size and its text is not shrunk to a third (a fixed 720 wide viewBox
// scaled to 330 px made 11 px axis labels 4.5 px). A container that is hidden or not on the page yet has no width: the chart is drawn at max and drawn again when it is shown.
export const chartWidth = (node, max = 720, min = 300) => Math.max(min, Math.min(max, Math.round((node && node.clientWidth) || max)));
