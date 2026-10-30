// Overview "Basins": a small county map and four snapshot cards (permits, production, rigs, busiest operators).
// Hover or focus a card and its counties light up on the map; a card opens #map?basin=ID.
import { $, el, fmt, compactFmt, halves, lastIdx, fmtDate, monthLabel } from './util.js';
import { delta } from './charts.js';
import { icon } from './icons.js';
import { isDark, onTheme } from './theme.js';
import { countyAt } from './geo.js';
import { opsLink } from './overview.js';

// basin identity colors (the cards also carry a name and the map labels it, so color is never the only cue)
const HUE = { permian: ['#eb6834', '#d95926'], eagleford: ['#1baf7a', '#199e70'], haynesville: ['#6250d6', '#9085e9'], barnett: ['#2a78d6', '#3987e5'] };
const FALLBACK = ['#898781', '#898781'];
export const basinColor = (id, dark) => (HUE[id] || FALLBACK)[dark ? 1 : 0];
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')'; };

const RIG_NOTE = {
  permian: 'Texas counties only; Baker Hughes’ Permian basin count also includes southeastern New Mexico',
  eagleford: 'Baker Hughes Eagle Ford basin',
  haynesville: 'Baker Hughes Haynesville basin: Texas and Louisiana together',
  barnett: 'Baker Hughes’ Barnett label, wider than the county list',
};
const RIG_SHORT = { permian: 'Texas counties', eagleford: 'Eagle Ford basin', haynesville: 'Texas and Louisiana', barnett: 'wider than the county list' };

/* the county map: all basins faintly shaded, the highlighted one strong */
function basinMap(host, G, B) {
  const canvas = el('canvas', { role: 'img', 'aria-label': 'Map of Texas with the Permian, Eagle Ford, Haynesville and Barnett basins shaded' });
  host.prepend(canvas);
  canvas.style.aspectRatio = G.W + ' / ' + G.H;
  const ctx = canvas.getContext('2d');
  let hot = null; let w = 0; let dpr = 1;
  function draw() {
    if (!w) return;
    const dark = isDark(); const k = w / G.W;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, G.H * k);
    ctx.setTransform(dpr * k, 0, 0, dpr * k, 0, 0); ctx.lineJoin = 'round';
    ctx.fillStyle = dark ? 'rgba(160,185,230,0.06)' : 'rgba(255,255,255,0.7)'; ctx.fill(G.outline);
    for (const b of B.list) {
      const col = basinColor(b.id, dark);
      ctx.fillStyle = rgba(col, hot === b.id ? (dark ? 0.72 : 0.62) : hot ? 0.1 : (dark ? 0.4 : 0.26)); ctx.fill(b.path);
    }
    ctx.lineWidth = 0.6 / k; ctx.strokeStyle = dark ? 'rgba(255,255,255,0.13)' : 'rgba(11,11,11,0.15)'; ctx.stroke(G.outline);
    ctx.lineWidth = 1.2 / k; ctx.strokeStyle = dark ? 'rgba(200,220,250,0.5)' : 'rgba(11,11,11,0.55)'; ctx.stroke(G.border);
    const hb = hot && B.byId.get(hot);
    if (hb) { ctx.lineWidth = 3.4 / k; ctx.strokeStyle = dark ? 'rgba(14,15,16,0.9)' : 'rgba(255,255,255,0.95)'; ctx.stroke(hb.boundary); ctx.lineWidth = 1.8 / k; ctx.strokeStyle = basinColor(hb.id, dark); ctx.stroke(hb.boundary); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.font = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineWidth = 3; ctx.lineJoin = 'round';
    for (const b of B.list) {
      const name = b.name.replace(/ \(.*\)| Basin/g, ''); const tw = ctx.measureText(name).width;
      const x = Math.min(Math.max(((b.bb[0] + b.bb[2]) / 2) * k, tw / 2 + 4), w - tw / 2 - 4); const y = ((b.bb[1] + b.bb[3]) / 2) * k;
      ctx.strokeStyle = dark ? 'rgba(14,15,16,0.85)' : 'rgba(252,252,251,0.9)'; ctx.fillStyle = dark ? '#f0efec' : '#0b0b0b';
      ctx.globalAlpha = hot && hot !== b.id ? 0.45 : 1; ctx.strokeText(name, x, y); ctx.fillText(name, x, y); ctx.globalAlpha = 1;
    }
  }
  function size() {
    const nw = host.clientWidth - 24; if (nw < 50) return;
    const nd = Math.min(window.devicePixelRatio || 1, 2.5);
    if (nw === w && nd === dpr) return;
    w = nw; dpr = nd; canvas.width = Math.round(w * dpr); canvas.height = Math.round(w * (G.H / G.W) * dpr); draw();
  }
  if ('ResizeObserver' in window) new ResizeObserver(size).observe(host);
  onTheme(draw);
  size();
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect(); const ci = countyAt(G, ((e.clientX - r.left) / r.width) * G.W, ((e.clientY - r.top) / r.height) * G.H);
    const b = ci >= 0 ? B.byFips.get(G.counties[ci].f) : null;
    canvas.style.cursor = b ? 'pointer' : 'default';
    api.onHot && api.onHot(b ? b.id : null);
  });
  canvas.addEventListener('pointerleave', () => api.onHot && api.onHot(null));
  canvas.addEventListener('click', (e) => {
    const r = canvas.getBoundingClientRect(); const ci = countyAt(G, ((e.clientX - r.left) / r.width) * G.W, ((e.clientY - r.top) / r.height) * G.H);
    const b = ci >= 0 ? B.byFips.get(G.counties[ci].f) : null;
    if (b) location.hash = '#map?basin=' + b.id;
  });
  const api = { set(id) { if (hot !== id) { hot = id; draw(); } }, onHot: null, size };
  return api;
}

function statsOf(b, cp, prod) {
  const m = new Array(cp.months.length).fill(0); let p12 = 0;
  const ops = new Map();
  for (const f of b.fips) {
    const c = cp.counties[f]; if (!c) continue;
    p12 += c.p12; c.m.forEach((v, i) => { m[i] += v; });
    for (const [name, num, n] of c.ops || []) { const o = ops.get(num) || { name, num, n: 0 }; o.n += n; ops.set(num, o); }
  }
  const s = { p12, h: halves(m), ops: [...ops.values()].sort((a, c) => c.n - a.n).slice(0, 3) };
  if (prod) {
    s.o12 = 0; s.o12p = 0; s.g12 = 0; s.g12p = 0; s.any = false;
    for (const f of b.fips) { const c = prod.counties[f]; if (!c) continue; s.any = true; s.o12 += c.o12; s.o12p += c.o12p; s.g12 += c.g12; s.g12p += c.g12p; }
  }
  return s;
}

export function renderBasins({ section, B, G, cp, prod, rigs, permitsThrough = '' }) {
  if (!B || !cp || !G) { section.hidden = true; return null; }
  const host = $('#basin-map'); const cardsHost = $('#basin-cards');
  const mapApi = basinMap(host, G, B);
  const totalP12 = Object.values(cp.counties).reduce((t, c) => t + c.p12, 0);
  const cards = new Map();
  const kpi = (label, value, sub, title) => el('div', { class: 'kpi', title: title || null }, el('span', { class: 'kpi-label', text: label }), el('strong', { class: 'kpi-value' }, value), sub ? el('span', { class: 'kpi-sub' }, sub) : null);
  const chg = (a, b) => (b > 0 ? a / b - 1 : null);
  const pEnd = prod ? monthLabel(prod.months[prod.months.length - 1]) : '';
  for (const b of B.list) {
    const s = statsOf(b, cp, prod);
    const kp = [kpi('Permits, 12 mo' + (permitsThrough ? ' to ' + permitsThrough : ''), fmt.format(s.p12), [delta(s.h.f === Infinity ? null : s.h.f), ' vs the 12 before'], 'New-drill permits (application type 01) in the 12 months to ' + (permitsThrough || 'the newest permit') + '; the change compares the last 12 full months with the 12 before')];
    const rg = rigs && rigs[b.id];
    if (prod && s.any) {
      kp.push(kpi('Oil, 12 mo to ' + pEnd, compactFmt.format(s.o12) + ' bbl', [delta(chg(s.o12, s.o12p)), ' vs the 12 before']),
        kpi('Gas, 12 mo to ' + pEnd, fmt.format(Math.round(s.g12 / 1e6)) + ' Bcf', [delta(chg(s.g12, s.g12p)), ' vs the 12 before']));
    } else kp.push(kpi('Share of Texas permits', Math.round((s.p12 / totalP12) * 100) + '%', fmt.format(b.fips.length) + ' counties'));
    if (rg) kp.push(kpi('Rigs drilling', fmt.format(rg.v), rg.sub, rg.title));
    else if (kp.length < 4) kp.push(kpi('Counties', fmt.format(b.fips.length), b.fips.length + ' on the map'));
    const col = basinColor(b.id, false);
    const key = el('i', { class: 'bcard-key', 'aria-hidden': 'true' });
    const card = el('article', { class: 'card bcard', 'data-basin': b.id },
      el('div', { class: 'bcard-head' }, key, el('h3', {}, el('a', { href: '#map?basin=' + b.id, 'aria-label': 'Open the ' + b.name + ' on the map', text: b.name }))),
      el('p', { class: 'bcard-sub', text: b.fips.length + ' counties' + (s.p12 && totalP12 ? ' · ' + Math.round((s.p12 / totalP12) * 100) + '% of Texas permits' : '') }),
      el('div', { class: 'bcard-kpis' }, kp.slice(0, 4)),
      s.ops.length ? el('div', {}, el('h4', { class: 'psec-h3', text: 'Most permits (county top lists)' }),
        el('ul', { class: 'bcard-ops' }, s.ops.map((o) => el('li', {}, el('a', { href: opsLink(o.name), text: o.name }))))) : null,
      el('span', { class: 'bcard-foot' }, 'Open on the map', icon('arrow', 15)));
    key.style.background = col; key.style.setProperty('--c', col);
    const on = () => { mapApi.set(b.id); };
    const off = () => { mapApi.set(null); };
    card.addEventListener('pointerenter', on); card.addEventListener('pointerleave', off);
    card.addEventListener('focusin', on); card.addEventListener('focusout', off);
    cards.set(b.id, card);
  }
  cardsHost.replaceChildren(...cards.values());
  mapApi.onHot = (id) => { mapApi.set(id); };
  const mark = () => { const d = isDark(); cards.forEach((c, id) => { const k = $('.bcard-key', c); k.style.background = basinColor(id, d); k.style.setProperty('--c', basinColor(id, d)); }); };
  onTheme(mark); mark();
  section.hidden = false;
  return mapApi;
}

/* rigs per basin for the cards: latest weekly count and its date */
export function basinRigs(R) {
  const out = {};
  const put = (id, ser) => {
    if (!ser) return; const i = lastIdx(ser.v); if (i < 0) return;
    const d = fmtDate(new Date(ser.t[i]).toISOString().slice(0, 10));
    out[id] = { v: ser.v[i], sub: d + ' · ' + RIG_SHORT[id], title: RIG_NOTE[id] + ' (' + d + ')' };
  };
  put('permian', R.rigPermian); put('eagleford', R.rigEF); put('haynesville', R.rigHay); put('barnett', R.rigBarnett);
  return out;
}
