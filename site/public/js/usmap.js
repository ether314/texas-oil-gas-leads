// The national wells map: the 49 state outlines and every new well of the last 24 months as a glowing dot, drawn on a canvas. Used twice: as the Overview's
// backdrop (nothing to touch) and as the explorer (hover a dot for its well, click a state to zoom in, replay two years with the shared replay bar).
// A second layer can ride on it (Q, the Daily report's oil permits and spuds, newwells-data.js decodePermits): a filled glowing dot is a fracked well, a hollow ring is an oil permit or spud, in the state's color.
// The still layers (outlines, settled dots) are painted once to offscreen canvases; each frame only blits them and draws the newest dots and the pulses.
// The loop runs only while something moves (a replay, a zoom, pulses on a visible map) and never with reduced motion.
import { clamp, reduced, onReducedChange, whenVisible, fmtDate, fmt, el } from './util.js';
import { isDark } from './theme.js';
import { showTip, hideTip, tipRow } from './tip.js';
import * as G from './usgeo.js';
import * as D from './newwells-data.js';

const TAU = Math.PI * 2;
const GLOW_DAYS = 30; // wells newer than this (before the replay's cursor) glow; older ones settle into the cached layer (the Daily report glows one day)
// each state's dot color, [on a dark page, on a light page]; the same hues as the stacked chart's colors (data's COLORS), every other state slate
const RGB = {
  TX: [[255, 138, 78], [235, 104, 52]], NM: [[48, 204, 148], [27, 175, 122]], OK: [[160, 142, 250], [98, 80, 214]], ND: [[96, 168, 252], [42, 120, 214]],
  CO: [[244, 192, 70], [214, 146, 0]], PA: [[240, 132, 176], [214, 80, 130]], LA: [[84, 206, 84], [0, 131, 0]], OH: [[244, 118, 118], [227, 73, 72]], other: [[112, 138, 170], [110, 124, 138]],
};
const KEYS = Object.keys(RGB);
const BASE = {
  dark: { line: 'rgba(150,180,220,0.22)', fill: 'rgba(110,150,215,0.05)', sel: 'rgba(190,215,250,0.95)', glow: 'rgba(60,130,230,0.09)', text: 'rgba(205,222,245,0.72)', ring: 'rgba(255,255,255,0.95)' },
  light: { line: 'rgba(20,45,90,0.26)', fill: 'rgba(255,255,255,0.55)', sel: 'rgba(20,70,150,0.95)', glow: 'rgba(42,120,214,0.07)', text: 'rgba(30,50,90,0.72)', ring: 'rgba(20,30,50,0.9)' },
};
function palette(rgb, dark) {
  const [r, g, b] = rgb; const mix = (c, t) => Math.round(c + (255 - c) * t);
  const rgba = (a, t = 0) => 'rgba(' + mix(r, t) + ',' + mix(g, t) + ',' + mix(b, t) + ',' + a + ')';
  return dark
    ? { old: rgba(0.55), fresh: rgba(0.98, 0.16), pulse: 'rgb(' + r + ',' + g + ',' + b + ')', halo: [rgba(0.95, 0.35), rgba(0.4), rgba(0)] }
    : { old: rgba(0.46), fresh: rgba(0.95), pulse: 'rgb(' + r + ',' + g + ',' + b + ')', halo: [rgba(0.95, 0.45), rgba(0.4), rgba(0)] };
}
function sprite(halo) {
  const s = document.createElement('canvas'); s.width = s.height = 64;
  const g = s.getContext('2d'); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  gr.addColorStop(0, halo[0]); gr.addColorStop(0.27, halo[1]); gr.addColorStop(1, halo[2]);
  g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
  return s;
}
function rng(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// canvas, host: the element that sizes it. outlines: usgeo.buildOutlines. P: newwells-data.decode. doc: the summary (for a state's figures).
// box(w, h): the drawing box in CSS px (the Overview's backdrop keeps clear of its text); default is the whole canvas with a margin.
export function createUSMap({ canvas, host, outlines, P, doc, Q = null, qOpen = false, interactive = false, box = null, onSelect = null, onHover = null, glowDays = GLOW_DAYS }) {
  const ctx = canvas.getContext('2d');
  const baseC = document.createElement('canvas'); const dotsC = document.createElement('canvas');
  const bctx = baseC.getContext('2d'); const dctx = dotsC.getContext('2d');
  const paths = {}; for (const [code, s] of Object.entries(outlines)) { const p = new Path2D(); for (const r of s.rings) { p.moveTo(r[0], r[1]); for (let i = 2; i < r.length; i += 2) p.lineTo(r[i], r[i + 1]); p.closePath(); } paths[code] = p; }
  // each well in world units, and its dot's color slot
  const wx = new Float32Array(P.n); const wy = new Float32Array(P.n); const slot = new Uint8Array(P.n);
  { const o = [0, 0]; const slotOf = P.states.map((id) => { const k = KEYS.indexOf(id); return k < 0 ? KEYS.length - 1 : k; });
    for (let i = 0; i < P.n; i++) { G.project(P.lon[i], P.lat[i], P.states[P.s[i]], o); wx[i] = o[0]; wy[i] = o[1]; slot[i] = slotOf[P.s[i]]; } }
  // the oil permits and spuds, in world units and a color slot by state; they share the wells' day numbers (Q was decoded against P's first day)
  const qn = Q ? Q.n : 0; const qx = new Float32Array(qn); const qy = new Float32Array(qn); const qslot = new Uint8Array(qn);
  if (Q) { const o = [0, 0]; const slotOf = Q.states.map((id) => { const k = KEYS.indexOf(id); return k < 0 ? KEYS.length - 1 : k; });
    for (let i = 0; i < qn; i++) { G.project(Q.lon[i], Q.lat[i], Q.states[Q.s[i]], o); qx[i] = o[0]; qy[i] = o[1]; qslot[i] = slotOf[Q.s[i]]; } }
  let showW = true; let showQ = !!Q; let hoverQ = -1; let lastWd = Infinity; let lastQd = Infinity; let drawnQ = 0;
  // a grid over the wells so the nearest dot to the pointer is found without looking at all of them
  const CELL = 8; const COLS = Math.ceil(G.WIDTH / CELL) + 2; const grid = new Map();
  for (let i = 0; i < P.n; i++) { const key = Math.floor(wy[i] / CELL) * COLS + Math.floor(wx[i] / CELL); const a = grid.get(key); if (a) a.push(i); else grid.set(key, [i]); }
  const cum = new Uint32Array(P.span + 2); for (let i = 0; i < P.n; i++) cum[P.day[i] + 1]++; for (let d = 1; d < cum.length; d++) cum[d] += cum[d - 1]; // wells up to and including day d: cum[d + 1]

  let w = 0; let h = 0; let dpr = 1; let dark = isDark();
  let view = { k: 1, tx: 0, ty: 0 }; let from = null; let to = null; let t0 = 0; const ZOOM_MS = 560;
  let selected = null; let hoverPt = -1; let hoverState = null; let cursor = P.span; let lo = 0;
  let drawnTo = 0; let dotsKey = ''; let raf = 0; let visible = true; let pulses = []; let tlOn = false;
  let pal = []; let sprites = [];
  const calm = () => reduced();
  const frame = () => (selected ? G.frameOf(outlines, selected) : { x0: 0, y0: 0, x1: G.WIDTH, y1: G.H });
  const boxPx = () => (box ? box(w, h) : { x0: 10, y0: 10, x1: w - 10, y1: h - 10 });
  function fit(f) {
    const b = boxPx(); const k = Math.min((b.x1 - b.x0) / (f.x1 - f.x0), (b.y1 - b.y0) / (f.y1 - f.y0));
    return { k, tx: (b.x0 + b.x1) / 2 - ((f.x0 + f.x1) / 2) * k, ty: (b.y0 + b.y1) / 2 - ((f.y0 + f.y1) / 2) * k };
  }
  const idxHi = () => cum[Math.min(P.span, Math.floor(cursor)) + 1]; // wells up to the cursor's day
  const idxLo = () => cum[Math.max(0, lo)]; // wells before the first visible day
  const glowFrom = () => Math.max(idxLo(), cum[Math.max(0, Math.floor(cursor) - glowDays) + 1]);
  const showing = (i) => !selected || P.states[P.s[i]] === selected;
  const showingQ = (j) => !selected || Q.states[Q.s[j]] === selected;
  // the last day the permit rings run to: the cursor, or with qOpen (the Overview) and no replay running, the newest permit there is (permits are published to later days than the wells are disclosed)
  const qCur = () => (qOpen && !tlOn && qn ? Math.max(Math.floor(cursor), Q.day[qn - 1]) : Math.floor(cursor));

  function loadPalette() {
    dark = isDark();
    pal = KEYS.map((k) => palette(RGB[k][dark ? 0 : 1], dark));
    sprites = pal.map((p) => sprite(p.halo));
  }
  const radius = () => clamp(view.k * 2.3, 1.3, 3.4) * (selected ? clamp(view.k / 2.2, 1, 2.1) : 1);

  function paintBase() {
    const c = BASE[dark ? 'dark' : 'light'];
    baseC.width = Math.round(w * dpr); baseC.height = Math.round(h * dpr);
    bctx.setTransform(dpr * view.k, 0, 0, dpr * view.k, dpr * view.tx, dpr * view.ty);
    bctx.lineJoin = 'round';
    const have = new Set(D.active(doc).map((s) => s.id));
    for (const code of Object.keys(paths)) {
      const sel = code === selected;
      bctx.fillStyle = sel ? c.fill : have.has(code) ? c.fill : 'rgba(0,0,0,0)';
      bctx.fill(paths[code]);
    }
    bctx.lineWidth = 5 / view.k; bctx.strokeStyle = c.glow;
    for (const code of Object.keys(paths)) bctx.stroke(paths[code]);
    bctx.lineWidth = 0.75 / view.k; bctx.strokeStyle = c.line;
    for (const code of Object.keys(paths)) if (code !== selected) bctx.stroke(paths[code]);
    if (selected) { bctx.lineWidth = 1.8 / view.k; bctx.strokeStyle = c.sel; bctx.stroke(paths[selected]); }
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // the settled dots: every well before the glow window, painted in order into a cached layer (appended while the cursor moves forward, repainted from the start otherwise)
  function paintSettled(cheap) {
    const key = [w, h, dpr, view.k.toFixed(4), view.tx.toFixed(1), view.ty.toFixed(1), selected, lo, dark ? 1 : 0, showW ? 1 : 0].join('|');
    const upto = glowFrom(); const first = idxLo();
    if (key !== dotsKey || upto < drawnTo) { dotsC.width = Math.round(w * dpr); dotsC.height = Math.round(h * dpr); drawnTo = first; dotsKey = key; }
    if (!showW) { drawnTo = upto; return; } // only the permits are shown: the wells' layer stays empty
    if (upto <= drawnTo) return;
    dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const rn = radius(); const margin = rn * 4;
    for (let i = drawnTo; i < upto; i++) {
      const x = wx[i] * view.k + view.tx; const y = wy[i] * view.k + view.ty;
      if (x < -margin || y < -margin || x > w + margin || y > h + margin) continue;
      const dim = !showing(i);
      const wr = rn * (0.78 + 0.5 * Math.min(1, P.h2o[i] / 400));
      if (cheap) { dctx.fillStyle = pal[slot[i]].old; dctx.fillRect(x - wr * 0.7, y - wr * 0.7, wr * 1.4, wr * 1.4); continue; }
      if (dim) { dctx.globalAlpha = 0.18; dctx.fillStyle = pal[slot[i]].old; dctx.beginPath(); dctx.arc(x, y, wr * 0.8, 0, TAU); dctx.fill(); dctx.globalAlpha = 1; continue; }
      dctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
      dctx.globalAlpha = dark ? 0.15 : 0.2;
      const gr = wr * 2.9; dctx.drawImage(sprites[slot[i]], x - gr, y - gr, gr * 2, gr * 2);
      dctx.globalAlpha = 1; dctx.globalCompositeOperation = 'source-over';
      dctx.fillStyle = pal[slot[i]].old; dctx.beginPath(); dctx.arc(x, y, wr, 0, TAU); dctx.fill();
    }
    dctx.globalAlpha = 1; dctx.globalCompositeOperation = 'source-over';
    drawnTo = upto;
  }

  // state letters on the states that have wells, the biggest first, over the dots (with a thin halo), so the map can be read without a legend
  function paintLabels() {
    if (selected || !interactive) return;
    const c = BASE[dark ? 'dark' : 'light'];
    ctx.font = '650 ' + (w < 520 ? 9 : 10.5) + 'px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round'; ctx.lineWidth = 3;
    ctx.strokeStyle = dark ? 'rgba(10,12,14,0.78)' : 'rgba(255,255,255,0.85)'; ctx.fillStyle = c.text;
    for (const s of doc.states.filter((x) => x.p12 > 0 && outlines[x.id]).slice(0, w < 520 ? 7 : 11)) {
      const [cx, cy] = outlines[s.id].c; const x = cx * view.k + view.tx; const y = cy * view.k + view.ty;
      ctx.strokeText(s.id, x, y); ctx.fillText(s.id, x, y);
    }
  }

  function pickPulses() {
    const rand = rng(11); const a = glowFrom(); const b = idxHi(); pulses = [];
    if (!showW || showQ) return; // no pulses beside permit rings: an expanding ring around a well must not read as a permit
    for (let n = 0; n < 70 && b > a; n++) { const i = a + Math.floor(rand() * (b - a)); if (showing(i)) pulses.push({ i, phase: rand(), period: 2400 + rand() * 1800 }); }
  }

  // the oil permits and spuds of the shown days: hollow rings in the state's color (a dark or light backing keeps a ring readable over a dense glow); the newest days are brighter and thicker
  function paintPermits(rn) {
    drawnQ = 0;
    if (!Q || !showQ) return;
    const cur = qCur(); const first = D.firstPermitAtOrAfter(Q, lo);
    // thousands of rings over the whole country (the Overview) are drawn small and thin, with no backing, so the fracked wells' dots under them stay readable; a few hundred (a day) or a state's view keep the full rings
    const dense = rn < 4.5 && Math.min(qn, D.firstPermitAtOrAfter(Q, cur + 1)) - first > 2500;
    const r0 = dense ? Math.max(2.3, rn * 1.1) : Math.max(3, rn * 1.7); const back = dark ? 'rgba(8,10,14,0.55)' : 'rgba(255,255,255,0.8)';
    if (dense) ctx.globalAlpha = 0.8;
    for (let j = first; j < qn && Q.day[j] <= cur; j++) {
      if (!showingQ(j)) continue;
      const x = qx[j] * view.k + view.tx; const y = qy[j] * view.k + view.ty;
      if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
      const fresh = Q.day[j] > cur - glowDays;
      ctx.beginPath(); ctx.arc(x, y, r0, 0, TAU);
      if (!dense) { ctx.lineWidth = fresh ? 4 : 3; ctx.strokeStyle = back; ctx.stroke(); }
      ctx.lineWidth = dense ? (fresh ? 1.4 : 1) : fresh ? 2 : 1.3; ctx.strokeStyle = fresh ? pal[qslot[j]].fresh : pal[qslot[j]].old; ctx.stroke();
      drawnQ++;
    }
    ctx.globalAlpha = 1;
  }

  function draw(now = 0) {
    if (!w) return;
    const cheap = !!from;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    ctx.drawImage(baseC, 0, 0, w, h);
    ctx.drawImage(dotsC, 0, 0, w, h);
    const rn = radius(); const hiI = showW ? idxHi() : 0; const gf = showW ? glowFrom() : 0;
    if (!cheap) {
      const c = BASE[dark ? 'dark' : 'light'];
      // the newest dots: bright, fading as they age, with the strongest halo
      ctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
      for (let i = gf; i < hiI; i++) {
        if (!showing(i)) continue;
        const x = wx[i] * view.k + view.tx; const y = wy[i] * view.k + view.ty;
        if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
        const age = Math.min(1, (Math.floor(cursor) - P.day[i]) / glowDays);
        const wr = rn * (0.78 + 0.5 * Math.min(1, P.h2o[i] / 400)) * (1.12 - 0.12 * age); const gr = wr * 3.6;
        ctx.globalAlpha = (dark ? 0.34 : 0.42) * (1 - 0.45 * age);
        ctx.drawImage(sprites[slot[i]], x - gr, y - gr, gr * 2, gr * 2);
      }
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      for (let i = gf; i < hiI; i++) {
        if (!showing(i)) continue;
        const x = wx[i] * view.k + view.tx; const y = wy[i] * view.k + view.ty;
        if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
        const wr = rn * (0.78 + 0.5 * Math.min(1, P.h2o[i] / 400));
        ctx.fillStyle = pal[slot[i]].fresh; ctx.beginPath(); ctx.arc(x, y, wr, 0, TAU); ctx.fill();
        if (!dark) { ctx.lineWidth = 0.7; ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.stroke(); }
      }
      if (!calm() && visible && !tlOn) { // a slow pulse on a few of the newest wells
        for (const p of pulses) {
          const t = ((now / p.period) + p.phase) % 1;
          const x = wx[p.i] * view.k + view.tx; const y = wy[p.i] * view.k + view.ty;
          ctx.globalAlpha = (1 - t) * 0.7; ctx.lineWidth = 1.2; ctx.strokeStyle = pal[slot[p.i]].pulse;
          ctx.beginPath(); ctx.arc(x, y, rn + t * 15, 0, TAU); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      paintPermits(rn);
      paintLabels();
      if (hoverState && !selected) { const c2 = BASE[dark ? 'dark' : 'light']; ctx.save(); ctx.setTransform(dpr * view.k, 0, 0, dpr * view.k, dpr * view.tx, dpr * view.ty); ctx.lineWidth = 1.6 / view.k; ctx.strokeStyle = c2.sel; ctx.stroke(paths[hoverState]); ctx.restore(); }
      if (hoverQ >= 0) {
        const x = qx[hoverQ] * view.k + view.tx; const y = qy[hoverQ] * view.k + view.ty;
        ctx.lineWidth = 2; ctx.strokeStyle = c.ring; ctx.beginPath(); ctx.arc(x, y, Math.max(3, rn * 1.7) + 5, 0, TAU); ctx.stroke();
      }
      if (hoverPt >= 0) {
        const x = wx[hoverPt] * view.k + view.tx; const y = wy[hoverPt] * view.k + view.ty;
        ctx.lineWidth = 2; ctx.strokeStyle = c.ring; ctx.beginPath(); ctx.arc(x, y, rn + 5, 0, TAU); ctx.stroke();
      }
    }
  }

  function render(now) {
    if (from) {
      const p = clamp((now - t0) / ZOOM_MS, 0, 1); const e = 1 - Math.pow(1 - p, 3);
      view = { k: from.k + (to.k - from.k) * e, tx: from.tx + (to.tx - from.tx) * e, ty: from.ty + (to.ty - from.ty) * e };
      paintBase(); paintSettled(true);
      if (p >= 1) { from = null; dotsKey = ''; paintBase(); paintSettled(false); pickPulses(); }
    } else paintSettled(false);
    draw(now);
  }
  function loop(now) {
    raf = 0;
    render(now);
    if (from || (!calm() && visible && !tlOn && pulses.length)) raf = requestAnimationFrame(loop);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(loop); }
  function repaintAll() { dotsKey = ''; paintBase(); render(performance.now()); kick(); }

  function size() {
    const r = host.getBoundingClientRect(); const nw = Math.round(r.width); const nh = Math.round(r.height);
    if (!nw || !nh) return;
    dpr = Math.min(2, window.devicePixelRatio || 1); w = nw; h = nh;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    view = fit(frame()); from = null; pickPulses(); repaintAll();
  }
  const ro = new ResizeObserver(() => size()); ro.observe(host);
  const onThemeChange = () => { loadPalette(); repaintAll(); };
  window.addEventListener('themechange', onThemeChange);
  onReducedChange(() => { pickPulses(); kick(); });
  const stopVisible = whenVisible(host, (v) => { visible = v; if (v) kick(); }, { once: false, threshold: 0.05 });
  const onHidden = () => { visible = !document.hidden; if (visible) kick(); };
  document.addEventListener('visibilitychange', onHidden);
  loadPalette(); size();

  /* ---------- hover and click ---------- */
  function worldAt(px, py) { return [(px - view.tx) / view.k, (py - view.ty) / view.k]; }
  function nearest(px, py) {
    const [x, y] = worldAt(px, py); const rad = Math.max(7, radius() * 2.6) / view.k; const cx = Math.floor(x / CELL); const cy = Math.floor(y / CELL); const span = Math.ceil(rad / CELL);
    const a = idxLo(); const b = idxHi(); let best = -1; let bd = rad * rad; lastWd = Infinity;
    if (!showW) return -1;
    for (let j = cy - span; j <= cy + span; j++) for (let i = cx - span; i <= cx + span; i++) {
      const cell = grid.get(j * COLS + i); if (!cell) continue;
      for (const q of cell) { if (q < a || q >= b || !showing(q)) continue; const dx = wx[q] - x; const dy = wy[q] - y; const d = dx * dx + dy * dy; if (d < bd) { bd = d; best = q; } }
    }
    lastWd = best >= 0 ? bd : Infinity;
    return best;
  }
  // the nearest oil permit or spud among the shown days (a few hundred at most: a plain scan)
  function nearestQ(px, py) {
    lastQd = Infinity;
    if (!Q || !showQ) return -1;
    const [x, y] = worldAt(px, py); const rad = Math.max(8, radius() * 3) / view.k; const cur = qCur(); let best = -1; let bd = rad * rad;
    for (let j = D.firstPermitAtOrAfter(Q, lo); j < qn && Q.day[j] <= cur; j++) {
      if (!showingQ(j)) continue;
      const dx = qx[j] - x; const dy = qy[j] - y; const d = dx * dx + dy * dy; if (d < bd) { bd = d; best = j; }
    }
    lastQd = best >= 0 ? bd : Infinity;
    return best;
  }
  const stateAtPx = (px, py) => { const [x, y] = worldAt(px, py); return G.stateAt(outlines, x, y); };
  function tipOf(i) {
    const county = D.countyOf(P, i); const st = D.stateOfPoint(P, i); const name = (doc.states.find((s) => s.id === st) || {}).name || st;
    const op = D.operatorOf(P, i);
    const size = [D.feet(P.tvd[i]), D.gallons(P.h2o[i]) && D.gallons(P.h2o[i]) + ' of water'].filter(Boolean).join(' · ');
    return [el('div', { class: 'tip-head', text: (county ? county + ' County, ' : '') + name }),
      tipRow(fmtDate(D.dayIso(D.dayMs(P, P.day[i]))), 'first fracturing job'),
      tipRow(op || 'Operator not named', op ? 'operator' : 'only companies are named'),
      size ? tipRow(size, '') : null,
      P.f[i] ? tipRow(D.LAND[P.f[i]].replace(/^./, (c) => c.toUpperCase()), '') : null];
  }
  function tipOfQ(j) {
    const spud = Q.spud[Q.s[j]] === 1; const op = D.permitOperator(Q, j); const ft = D.feet(Q.tvd[j]);
    return [el('div', { class: 'tip-head', text: (spud ? 'Oil well spudded · ' : 'Oil permit approved · ') + D.permitStateName(Q.states[Q.s[j]]) }),
      tipRow(fmtDate(D.dayIso(D.dayMs(P, Q.day[j]))), spud ? 'the well was spudded' : 'the day the permit was approved'),
      tipRow(op || 'Operator not named', op ? 'operator' : 'only companies are named'),
      ft ? tipRow(ft, 'permitted depth') : null].filter(Boolean);
  }
  function move(e) {
    if (!interactive || from) return;
    const r = canvas.getBoundingClientRect(); const px = e.clientX - r.left; const py = e.clientY - r.top;
    let i = nearest(px, py); const j = nearestQ(px, py); let q = -1;
    if (j >= 0 && (i < 0 || lastQd < lastWd)) { q = j; i = -1; } // a ring and a dot under the pointer: the nearer one answers
    const st = i < 0 && q < 0 ? stateAtPx(px, py) : null;
    const s = st && doc.states.find((x) => x.id === st && x.p12 > 0);
    if (i !== hoverPt || q !== hoverQ || st !== hoverState) { hoverPt = i; hoverQ = q; hoverState = s ? st : null; draw(performance.now()); }
    canvas.style.cursor = i >= 0 || q >= 0 || s || selected ? 'pointer' : 'default';
    if (i >= 0) showTip(tipOf(i), e.clientX, e.clientY);
    else if (q >= 0) showTip(tipOfQ(q), e.clientX, e.clientY);
    else if (s) showTip([el('div', { class: 'tip-head', text: s.name }), tipRow(fmt.format(s.p12), 'new wells in the last 12 months'), tipRow(selected ? '' : 'Click to zoom in', '')], e.clientX, e.clientY);
    else hideTip();
    if (onHover) onHover(i, st);
  }
  function leave() { hoverPt = -1; hoverQ = -1; hoverState = null; hideTip(); draw(performance.now()); }
  function click(e) {
    if (!interactive) return;
    const r = canvas.getBoundingClientRect(); const px = e.clientX - r.left; const py = e.clientY - r.top;
    const dot = nearest(px, py); const ring = nearestQ(px, py);
    if ((dot >= 0 || ring >= 0) && selected) { move(e); return; } // a tap on a dot of the state already zoomed to shows that well (a touch screen has no hover)
    let st = stateAtPx(px, py);
    if (!st && dot >= 0) st = D.stateOfPoint(P, dot);
    if (!st && ring >= 0) st = Q.states[Q.s[ring]];
    const have = st && doc.states.find((x) => x.id === st && x.p12 > 0);
    if (have && st !== selected) api.select(st); else if (selected) api.select(null);
  }
  if (interactive) { canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerleave', leave); canvas.addEventListener('click', click); }

  const api = {
    // the state the map is zoomed to (null: the country); the view moves there over half a second, or at once with reduced motion
    select(code, silent = false) {
      const next = code && outlines[code] ? code : null;
      if (next === selected) return;
      selected = next; hoverPt = -1; hoverQ = -1; hoverState = null; hideTip();
      const target = fit(frame());
      if (calm() || !w) { view = target; from = null; } else { from = { ...view }; to = target; t0 = performance.now(); }
      dotsKey = ''; paintBase(); pickPulses(); render(performance.now()); kick();
      if (!silent && onSelect) onSelect(selected);
    },
    get selected() { return selected; },
    // the replay bar's engine interface (timelapse.js): the days it runs over, how many wells are in by a day, and the cursor
    tlRange: [0, P.span],
    // with only the permits shown, the replay counts the permits (rings) up to the day, not the wells that are hidden
    tlCount(day) {
      if (!showW && Q) return D.firstPermitAtOrAfter(Q, Math.floor(day) + 1) - D.firstPermitAtOrAfter(Q, lo);
      return cum[Math.min(P.span, Math.max(0, Math.floor(day))) + 1] - idxLo();
    },
    setTimelapse(on, day) { tlOn = !!on; cursor = on ? clamp(day, 0, P.span) : P.span; pickPulses(); render(performance.now()); if (!on) kick(); },
    // the days shown: [first, cursor]; the Daily report shows a window, the Overview all of it
    setRange(a, b) { lo = clamp(a, 0, P.span); cursor = clamp(b, lo, P.span); dotsKey = ''; pickPulses(); render(performance.now()); kick(); },
    count: () => idxHi() - idxLo(),
    // which layers are drawn: the fracked wells (dots), the oil permits and spuds (rings); the permits only when the map was given them
    setKinds({ wells = true, permits = true } = {}) {
      showW = !!wells; showQ = !!Q && !!permits; hoverPt = -1; hoverQ = -1; hideTip();
      dotsKey = ''; pickPulses(); render(performance.now()); kick();
    },
    get kinds() { return { wells: showW, permits: showQ }; },
    get drawnPermits() { return drawnQ; }, // the rings painted in the last frame (QA)
    get pulsing() { return pulses.length; }, // wells chosen to pulse (QA): none while permit rings are shown
    // the permits and spuds in the shown days that the chosen state allows (QA and the Daily's counts)
    permitCount() { if (!Q || !showQ) return 0; let n = 0; const cur = qCur(); for (let j = D.firstPermitAtOrAfter(Q, lo); j < qn && Q.day[j] <= cur; j++) if (showingQ(j)) n++; return n; },
    screenOfQ: (j) => [qx[j] * view.k + view.tx, qy[j] * view.k + view.ty],
    // where a well is on the canvas, in CSS pixels (QA drives hovers and clicks with it)
    screenOf: (i) => [wx[i] * view.k + view.tx, wy[i] * view.k + view.ty],
    get ready() { return w > 0; },
    refresh: repaintAll,
    destroy() { ro.disconnect(); window.removeEventListener('themechange', onThemeChange); stopVisible(); document.removeEventListener('visibilitychange', onHidden); cancelAnimationFrame(raf); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerleave', leave); canvas.removeEventListener('click', click); hideTip(); },
  };
  return api;
}
