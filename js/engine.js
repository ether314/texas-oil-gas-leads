// Canvas map engine: pan/zoom on projected world units, choropleth, point layers, labels, hit-testing.
// No libraries. Redraws only on demand through requestAnimationFrame.
import { clamp, reduced } from './util.js';
import { countyAt } from './geo.js';

const TAU = Math.PI * 2;
const ZMAX = 70;
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const EMPTY = [];

export function createEngine(canvas, host, G, P0, Z, F) {
  const ctx = canvas.getContext('2d');
  let P = P0;
  const st = { w: 0, h: 0, dpr: 1, k0: 1, k: 1, cx: G.W / 2, cy: G.H / 2, tk: 1, tcx: G.W / 2, tcy: G.H / 2, anchor: null };
  let th = null; let sprite = null; let freshSprite = null; let classPaths = [];
  const layers = { permits: true, zips: false };
  let opFilter = -1; let hover = null; let padB = 0; let basinSel = null;
  // time-lapse: points are replayed by issue day. Settled points (older than `fade` days) live in the cached layer, newer ones
  // are drawn each frame with a glow that cools as they age.
  const tl = { on: false, cur: 0, cut: -1, fade: 21, order: null, ts: null, forP: null, zero: null };
  const sel = { county: -1, zip: -1, pt: -1, fac: null };
  const handlers = {};
  const emit = (t, a, b, c) => { if (handlers[t]) handlers[t](a, b, c); };
  let raf = 0; let lastT = 0; let lastMs = 0; let busyUntil = 0; let idleT = 0; 
  const widths = new Map();
  // a camera request (deep link fit or focus) made before the map had a size; replayed on the first resize instead of
  // being overwritten by the default whole-state view
  let pendingView = null;
  const dbg = {}; // QA switches to time one stage at a time
  const clearHover = () => { if (hover) { hover = null; invalidate(); } emit('hover', null); };

  /* view */
  function clampCenter(cx, cy, k) {
    const vw = st.w / k; const vh = st.h / k;
    // the bottom limit gives back the strip a phone sheet covers, so the state's southern edge can be lifted above it
    const lx = vw * 0.35; const hx = G.W - vw * 0.35; const ly = vh * 0.35; const hy = G.H - vh * 0.35 + padB / k;
    return [lx > hx ? G.W / 2 : clamp(cx, lx, hx), ly > hy ? G.H / 2 : clamp(cy, ly, hy)];
  }
  function flyTo(cx, cy, k, instant) {
    const [ccx, ccy] = clampCenter(cx, cy, k);
    st.tk = k; st.tcx = ccx; st.tcy = ccy; st.anchor = null; clearHover();
    if (instant || reduced() || !st.w) { st.k = k; st.cx = ccx; st.cy = ccy; }
    invalidate();
  }
  function fitBox(bb, o = {}) {
    if (!st.w) { pendingView = () => fitBox(bb, { ...o, instant: true }); return; }
    const pad = o.pad == null ? 28 : o.pad;
    const aw = Math.max(40, st.w - 2 * pad); const ah = Math.max(40, st.h - 2 * pad - padB);
    const k = clamp(Math.min(aw / Math.max(bb[2] - bb[0], 1e-3), ah / Math.max(bb[3] - bb[1], 1e-3)), st.k0, st.k0 * (o.maxZoom || ZMAX));
    flyTo((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2 + padB / 2 / k, k, o.instant);
  }
  const reset = (instant) => fitBox([0, 0, G.W, G.H], { pad: 12, instant });
  function zoomAt(mx, my, f) {
    const wx = (mx - st.w / 2) / st.k + st.cx; const wy = (my - st.h / 2) / st.k + st.cy;
    st.tk = clamp(st.tk * f, st.k0, st.k0 * ZMAX);
    st.anchor = { mx, my, wx, wy };
    clearHover(); busy(); invalidate();
  }
  function step(dt) {
    const a = reduced() ? 1 : 1 - Math.exp(-dt / 110);
    const lk = Math.log(st.k); const lt = Math.log(st.tk);
    const nlk = lk + (lt - lk) * a;
    const nk = Math.abs(lt - nlk) < 0.0006 ? st.tk : Math.exp(nlk);
    let ncx; let ncy;
    if (st.anchor) {
      ncx = st.anchor.wx - (st.anchor.mx - st.w / 2) / nk; ncy = st.anchor.wy - (st.anchor.my - st.h / 2) / nk;
    } else {
      ncx = st.cx + (st.tcx - st.cx) * a; ncy = st.cy + (st.tcy - st.cy) * a;
    }
    st.k = nk;
    [st.cx, st.cy] = clampCenter(ncx, ncy, nk);
    const closeEnough = st.anchor || (Math.abs(st.tcx - st.cx) * nk < 0.3 && Math.abs(st.tcy - st.cy) * nk < 0.3);
    if (nk === st.tk && closeEnough) {
      if (!st.anchor) { st.cx = st.tcx; st.cy = st.tcy; }
      st.tcx = st.cx; st.tcy = st.cy; st.anchor = null;
      return false;
    }
    return true;
  }
  function panPx(dx, dy) {
    st.cx -= dx / st.k; st.cy -= dy / st.k;
    [st.cx, st.cy] = clampCenter(st.cx, st.cy, st.k);
    st.tcx = st.cx; st.tcy = st.cy; st.tk = st.k; st.anchor = null;
    busy(); invalidate();
  }
  function busy() {
    busyUntil = performance.now() + 220;
    clearTimeout(idleT);
    idleT = setTimeout(invalidate, 260);
  }
  function resize() {
    const w = host.clientWidth; const h = host.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    if (w === st.w && h === st.h && dpr === st.dpr) return;
    const first = !st.w;
    const zNow = st.k / st.k0; const zT = st.tk / st.k0;
    st.w = w; st.h = h; st.dpr = dpr;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    st.k0 = Math.min((w - 24) / G.W, (h - 24) / G.H);
    if (first) {
      reset(true);
      if (pendingView) {
        const run = pendingView; pendingView = null; run();
        st.k = st.tk; st.cx = st.tcx; st.cy = st.tcy; // open already framed, no fly-in
      }
    } else { st.k = zNow * st.k0; st.tk = zT * st.k0; }
    invalidate();
  }

  /* theme and data hooks */
  function setTheme(t) {
    th = t; widths.clear(); pc.ok = false;
    sprite = null; freshSprite = null;
    if (t.tlGlow) {
      freshSprite = document.createElement('canvas'); freshSprite.width = freshSprite.height = 64;
      const g = freshSprite.getContext('2d'); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      t.tlGlow.forEach(([at, c]) => gr.addColorStop(at, c));
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    }
    if (t.glow) {
      sprite = document.createElement('canvas'); sprite.width = sprite.height = 64;
      const g = sprite.getContext('2d'); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      t.glow.forEach(([at, c]) => gr.addColorStop(at, c));
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    }
    invalidate();
  }
  function setCountyColors(colors, noData) {
    const groups = new Map();
    colors.forEach((c, i) => {
      const key = c || '';
      let g = groups.get(key);
      if (!g) groups.set(key, g = new Path2D());
      g.addPath(G.counties[i].path);
    });
    classPaths = [...groups].map(([color, path]) => ({ color: color || noData, path }));
    invalidate();
  }

  /* drawing */
  const sx = (x) => (x - st.cx) * st.k + st.w / 2;
  const sy = (y) => (y - st.cy) * st.k + st.h / 2;
  const zipR = (z, zoom) => Math.max(2.4, 20 * Math.pow(zoom, 0.28) * Math.sqrt(z.total / Z.max));

  function draw() {
    const t0 = performance.now();
    const { w, h, dpr, k } = st;
    if (!w || !th) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * (w / 2 - st.cx * k), dpr * (h / 2 - st.cy * k));
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.lineWidth = 0.6 / k; ctx.strokeStyle = th.grat; ctx.stroke(G.grat);
    ctx.globalAlpha = opFilter !== -1 ? 0.4 : 1;
    if (!dbg.noFills) for (const c of classPaths) { ctx.fillStyle = c.color; ctx.fill(c.path); }
    ctx.globalAlpha = 1;
    if (basinSel) { ctx.fillStyle = th.dim; ctx.fill(basinSel.dim); }
    if (hover && hover.type === 'county') { ctx.fillStyle = th.hover; ctx.fill(G.counties[hover.i].path); }
    if (!dbg.noLines) { ctx.lineWidth = 0.7 / k; ctx.strokeStyle = th.line; ctx.stroke(G.outline); }
    if (!dbg.noBorder) {
      ctx.lineWidth = 4 / k; ctx.strokeStyle = th.halo2; ctx.stroke(G.border);
      ctx.lineWidth = 1.3 / k; ctx.strokeStyle = th.border; ctx.stroke(G.border);
    }
    if (basinSel) {
      ctx.lineWidth = 5 / k; ctx.strokeStyle = th.basinHalo; ctx.stroke(basinSel.boundary);
      ctx.lineWidth = 2.2 / k; ctx.strokeStyle = th.basin; ctx.stroke(basinSel.boundary);
    }
    if (hover && hover.type === 'county' && hover.i !== sel.county) {
      ctx.lineWidth = 1.5 / k; ctx.strokeStyle = th.ink; ctx.stroke(G.counties[hover.i].path);
    }
    if (sel.county >= 0) {
      const sp = G.counties[sel.county].path; // a halo under the ring keeps it visible on both the darkest and the lightest fills
      ctx.lineWidth = 5 / k; ctx.strokeStyle = th.selHalo; ctx.stroke(sp);
      ctx.lineWidth = 2.4 / k; ctx.strokeStyle = th.sel; ctx.stroke(sp);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (layers.zips && Z) drawZips();
    if (layers.permits && !dbg.noPoints) { paintPermits(); paintFresh(); }
    drawInfra();
    drawRings();
    if (!dbg.noLabels) drawLabels();
    lastMs = performance.now() - t0;
  }

  function drawZips() {
    const zoom = st.k / st.k0; const { w, h } = st;
    ctx.lineWidth = 1; ctx.fillStyle = th.zipFill; ctx.strokeStyle = th.zipLine;
    for (const zp of Z.list) {
      const x = sx(zp.x); const y = sy(zp.y); const r = zipR(zp, zoom);
      if (x < -r || x > w + r || y < -r || y > h + r) continue;
      ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill(); ctx.stroke();
    }
  }

  // Permit dots are painted into an offscreen layer with a margin and reused while the view pans or zooms
  // (translated and scaled), then repainted crisp once the motion settles. That keeps 25k+ glowing dots smooth.
  const pc = { cv: document.createElement('canvas'), ok: false, k: 1, cx: 0, cy: 0, m: 140, w: 0, h: 0, dpr: 1, tl: false, cut: null };
  let animating = false; let lastRenderMs = 0;
  /* tl helpers: points sorted by issue day; upper(x) = how many have t <= x */
  function buildOrder() {
    const n = P.n; const order = new Int32Array(n); for (let i = 0; i < n; i++) order[i] = i;
    order.sort((a, b) => P.t[a] - P.t[b]);
    const ts = new Int16Array(n); for (let q = 0; q < n; q++) ts[q] = P.t[order[q]];
    tl.order = order; tl.ts = ts; tl.forP = P; tl.zero = new Uint8Array(n);
  }
  const upper = (x) => { const ts = tl.ts; let lo = 0; let hi = ts.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (ts[mid] <= x) lo = mid + 1; else hi = mid; } return lo; };
  // a window (tLo, tHi] of the replay, or the whole set when the replay is off
  function drawPermits(g, ox, oy, cw, ch, tLo = -32768, tHi = 32767) {
    const zoom = st.k / st.k0;
    const list = opFilter !== -1 ? P.byOp.get(opFilter) || EMPTY : null;
    const useOrder = tl.on;
    let q0 = 0; let q1 = list ? list.length : P.n;
    if (useOrder) { q0 = tLo <= -32768 ? 0 : upper(tLo); q1 = upper(tHi); }
    const at = (q) => (useOrder ? tl.order[q] : list ? list[q] : q);
    const boost = opFilter !== -1 ? 1.45 : 1;
    const rn = clamp(1.55 * Math.pow(zoom, 0.34), 1.55, 5.4) * boost; const ro = rn * (opFilter !== -1 ? 0.9 : 0.78);
    const X = P.x; const Y = P.y; const R = useOrder ? tl.zero : P.rec; const k = st.k; const hx = st.w / 2 - st.cx * k + ox; const hy = st.h / 2 - st.cy * k + oy;
    const skip = (i) => useOrder && opFilter !== -1 && P.op[i] !== opFilter;
    if (sprite && !dbg.noGlow) {
      g.globalCompositeOperation = th.additive ? 'lighter' : 'source-over';
      for (let pass = 0; pass < 2; pass++) {
        const gr = (pass ? rn : ro) * 3.4;
        g.globalAlpha = pass ? th.glowNew : th.glowOld;
        for (let q = q0; q < q1; q++) {
          const i = at(q);
          if (R[i] !== pass || skip(i)) continue;
          const x = X[i] * k + hx; const y = Y[i] * k + hy;
          if (x < -gr || x > cw + gr || y < -gr || y > ch + gr) continue;
          g.drawImage(sprite, x - gr, y - gr, gr * 2, gr * 2);
        }
      }
      g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    }
    for (let pass = 0; pass < 2; pass++) {
      const r = pass ? rn : ro;
      g.beginPath();
      for (let q = q0; q < q1; q++) {
        const i = at(q);
        if (R[i] !== pass || skip(i)) continue;
        const x = X[i] * k + hx; const y = Y[i] * k + hy;
        if (x < -r || x > cw + r || y < -r || y > ch + r) continue;
        g.moveTo(x + r, y); g.arc(x, y, r, 0, TAU);
      }
      g.fillStyle = pass ? th.dotNew : th.dotOld; g.fill();
      if (pass) { g.lineWidth = 0.7; g.strokeStyle = th.dotRing; g.stroke(); }
    }
  }
  function paintPermits() {
    const interacting = animating || performance.now() < busyUntil;
    const f = pc.ok ? st.k / pc.k : 1;
    const ox = pc.ok ? (pc.cx - st.cx) * st.k : 0; const oy = pc.ok ? (pc.cy - st.cy) * st.k : 0;
    const stale = !pc.ok || pc.w !== st.w || pc.h !== st.h || pc.dpr !== st.dpr;
    const moved = Math.abs(f - 1) > 1e-4 || Math.abs(ox) > 0.5 || Math.abs(oy) > 0.5;
    const covered = f > 0.8 && f < 1.28 && Math.abs(ox) < pc.m * 0.6 && Math.abs(oy) < pc.m * 0.6;
    const tlNow = tl.on ? tl.cut : null;
    if (!stale && (pc.tl !== tl.on || pc.cut !== tlNow)) {
      if (pc.tl && tl.on && tlNow > pc.cut && !moved) {
        // the replay moved forward with the view unchanged: add only the points that just settled
        const g = pc.cv.getContext('2d'); g.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
        drawPermits(g, pc.m, pc.m, st.w + 2 * pc.m, st.h + 2 * pc.m, pc.cut, tlNow);
        pc.cut = tlNow;
      } else if (pc.tl !== tl.on || !moved || !(interacting && covered)) pc.ok = false; // rebuild; mid-pan the old layer is reused
    }
    if (!pc.ok || stale || (moved && !(interacting && covered))) {
      const t0 = performance.now(); const m = pc.m; const cw = st.w + 2 * m; const ch = st.h + 2 * m;
      const bw = Math.round(cw * st.dpr); const bh = Math.round(ch * st.dpr);
      if (pc.cv.width !== bw || pc.cv.height !== bh) { pc.cv.width = bw; pc.cv.height = bh; }
      const g = pc.cv.getContext('2d');
      g.setTransform(st.dpr, 0, 0, st.dpr, 0, 0); g.clearRect(0, 0, cw, ch);
      drawPermits(g, m, m, cw, ch, -32768, tl.on ? tl.cut : 32767);
      Object.assign(pc, { ok: true, k: st.k, cx: st.cx, cy: st.cy, w: st.w, h: st.h, dpr: st.dpr, tl: tl.on, cut: tlNow });
      lastRenderMs = performance.now() - t0;
    }
    const f2 = st.k / pc.k; const m = pc.m;
    ctx.drawImage(pc.cv, (-m - st.w / 2) * f2 + st.w / 2 + (pc.cx - st.cx) * st.k, (-m - st.h / 2) * f2 + st.h / 2 + (pc.cy - st.cy) * st.k,
      (st.w + 2 * m) * f2, (st.h + 2 * m) * f2);
  }

  // newest points of the replay: bright core and glow that cool toward the normal look as the days pass, plus a short ping
  function paintFresh() {
    if (!tl.on || !tl.order) return;
    const lo = upper(tl.cut); const hi = upper(tl.cur);
    if (hi <= lo) return;
    const zoom = st.k / st.k0; const boost = opFilter !== -1 ? 1.45 : 1;
    const rn = clamp(1.55 * Math.pow(zoom, 0.34), 1.55, 5.4) * boost; const k = st.k; const { w, h } = st;
    const hx = w / 2 - st.cx * k; const hy = h / 2 - st.cy * k;
    for (let q = lo; q < hi; q++) {
      const i = tl.order[q];
      if (opFilter !== -1 && P.op[i] !== opFilter) continue;
      const x = P.x[i] * k + hx; const y = P.y[i] * k + hy;
      if (x < -40 || x > w + 40 || y < -40 || y > h + 40) continue;
      const age = tl.cur - P.t[i]; const u = clamp(age / tl.fade, 0, 1);
      if (freshSprite) {
        const gr = rn * (7.2 - 3.4 * u); ctx.globalAlpha = 0.95 * (1 - u) * (1 - u * 0.4);
        ctx.drawImage(freshSprite, x - gr, y - gr, gr * 2, gr * 2);
      }
      ctx.globalAlpha = 1;
      if (age < 4) { ctx.beginPath(); ctx.arc(x, y, rn * (1.6 + 4.2 * (age / 4)), 0, TAU); ctx.lineWidth = 1.2; ctx.strokeStyle = th.tlRing; ctx.globalAlpha = 0.8 * (1 - age / 4); ctx.stroke(); ctx.globalAlpha = 1; }
      const r = rn * (1.75 - 0.75 * u);
      ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fillStyle = th.dotNew; ctx.fill();
      if (u < 0.85) { ctx.globalAlpha = 1 - u / 0.85; ctx.beginPath(); ctx.arc(x, y, r * 0.58, 0, TAU); ctx.fillStyle = th.tlHot; ctx.fill(); ctx.globalAlpha = 1; }
    }
  }

  function facShape(id, x, y, s) {
    ctx.beginPath();
    if (id === 'refinery') { ctx.moveTo(x, y - s * 1.2); ctx.lineTo(x + s * 1.2, y); ctx.lineTo(x, y + s * 1.2); ctx.lineTo(x - s * 1.2, y); }
    else if (id === 'lng') { ctx.moveTo(x, y - s * 1.15); ctx.lineTo(x + s * 1.2, y + s * 0.85); ctx.lineTo(x - s * 1.2, y + s * 0.85); }
    else ctx.rect(x - s * 0.85, y - s * 0.85, s * 1.7, s * 1.7);
    ctx.closePath();
  }
  function drawInfra() {
    if (!F || !F.length) return;
    const s0 = clamp(4.4 * Math.pow(st.k / st.k0, 0.16), 4.4, 7.5);
    ctx.lineWidth = 1.6; ctx.strokeStyle = th.ring; ctx.fillStyle = th.aqua;
    for (const l of F) {
      if (!layers[l.id]) continue;
      const s = s0 * (l.id === 'gasplant' ? 0.78 : l.id === 'lng' ? 1.2 : 1);
      for (const it of l.items) {
        const x = sx(it.x); const y = sy(it.y);
        if (x < -12 || x > st.w + 12 || y < -12 || y > st.h + 12) continue;
        facShape(l.id, x, y, s); ctx.stroke(); ctx.fill();
      }
    }
  }
  function ringAt(x, y, r, color, lw) {
    ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.lineWidth = lw; ctx.strokeStyle = color; ctx.stroke();
  }
  function ringHit(hit, color, lw) {
    if (!hit) return;
    if (hit.type === 'pt') ringAt(sx(P.x[hit.i]), sy(P.y[hit.i]), 8, color, lw);
    else if (hit.type === 'zip') { const z = Z.list[hit.j]; ringAt(sx(z.x), sy(z.y), zipR(z, st.k / st.k0) + 3, color, lw); }
    else if (hit.type === 'fac') {
      const l = F.find((q) => q.id === hit.layer); const it = l && l.items[hit.j];
      if (it) ringAt(sx(it.x), sy(it.y), 11, color, lw);
    }
  }
  function drawRings() {
    if (hover && hover.type !== 'county') ringHit(hover, th.ink, 1.5);
    if (sel.pt >= 0) ringHit({ type: 'pt', i: sel.pt }, th.sel, 2);
    if (sel.zip >= 0) ringHit({ type: 'zip', j: sel.zip }, th.sel, 2);
    if (sel.fac) ringHit({ type: 'fac', layer: sel.fac.layer, j: sel.fac.j }, th.sel, 2);
  }

  function textW(font, text) {
    const key = font + text;
    let v = widths.get(key);
    if (v == null) { ctx.font = font; v = ctx.measureText(text).width; widths.set(key, v); }
    return v;
  }
  function drawLabels() {
    const { w, h, k } = st; const zoom = k / st.k0;
    const boxes = [];
    const free = (a, b, c, d) => { for (const q of boxes) if (a < q[2] && c > q[0] && b < q[3] && d > q[1]) return false; return true; };
    ctx.textBaseline = 'middle'; ctx.lineJoin = 'round'; ctx.textAlign = 'left';
    const hubs = [];
    const hubFont = '600 12px ' + FONT;
    for (const hb of G.hubs) {
      if (hb.pri > 7 && zoom < 1.25 && w < 600) continue;
      const x = sx(hb.x); const y = sy(hb.y);
      if (x < 6 || x > w - 6 || y < 6 || y > h - 6) continue;
      const tw = textW(hubFont, hb.n);
      const spots = [[x + 7, y - 0.5], [x - 7 - tw, y - 0.5], [x - tw / 2, y - 11], [x - tw / 2, y + 12]];
      for (const [tx, ty] of spots) {
        const box = [tx - 2, ty - 8, tx + tw + 2, ty + 8];
        if (box[0] < 2 || box[2] > w - 2 || box[1] < 2 || box[3] > h - 2) continue;
        if (free(box[0], box[1], box[2], box[3])) { boxes.push(box); hubs.push([hb.n, x, y, tx, ty]); break; }
      }
    }
    if (zoom >= 2.1) {
      const font = '500 11px ' + FONT; let count = 0;
      ctx.font = font; ctx.fillStyle = th.countyLabel; ctx.strokeStyle = th.halo; ctx.lineWidth = 3;
      for (const c of G.counties) {
        if (count > 70) break;
        if ((c.bb[2] - c.bb[0]) * k < 62 || (c.bb[3] - c.bb[1]) * k < 20) continue;
        const x = sx(c.lx); const y = sy(c.ly);
        const tw = textW(font, c.n);
        const box = [x - tw / 2 - 2, y - 8, x + tw / 2 + 2, y + 8];
        if (box[0] < 0 || box[2] > w || box[1] < 0 || box[3] > h || !free(box[0], box[1], box[2], box[3])) continue;
        boxes.push(box); count++;
        ctx.strokeText(c.n, x - tw / 2, y); ctx.fillText(c.n, x - tw / 2, y);
      }
    }
    ctx.font = hubFont;
    for (const [n, x, y, tx, ty] of hubs) {
      ctx.beginPath(); ctx.arc(x, y, 2.4, 0, TAU); ctx.fillStyle = th.label; ctx.fill();
      ctx.strokeStyle = th.halo; ctx.lineWidth = 3.5; ctx.strokeText(n, tx, ty);
      ctx.fillStyle = th.label; ctx.fillText(n, tx, ty);
    }
  }

  /* loop */
  function invalidate() { if (!raf) raf = requestAnimationFrame(frame); }
  function frame(now) {
    raf = 0;
    const dt = lastT ? Math.min(60, now - lastT) : 16; lastT = now;
    let again = false;
    if (st.k !== st.tk || st.anchor || st.cx !== st.tcx || st.cy !== st.tcy) again = step(dt);
    animating = again;
    draw();
    emit('view', st.k / st.k0);
    if (again) invalidate(); else lastT = 0;
  }

  /* hit-testing */
  function nearestPoint(mx, my, rad) {
    const wx = (mx - st.w / 2) / st.k + st.cx; const wy = (my - st.h / 2) / st.k + st.cy; const r = rad / st.k;
    const gw = P.gw; const gs = P.gs;
    const c0 = Math.max(0, Math.floor((wx - r) / gs)); const c1 = Math.min(gw - 1, Math.floor((wx + r) / gs));
    const r0 = Math.max(0, Math.floor((wy - r) / gs)); const r1 = Math.min(P.gh - 1, Math.floor((wy + r) / gs));
    let best = -1; let bd = r * r;
    for (let cy = r0; cy <= r1; cy++) {
      for (let cx = c0; cx <= c1; cx++) {
        for (let i = P.heads[cy * gw + cx]; i >= 0; i = P.next[i]) {
          if (opFilter !== -1 && P.op[i] !== opFilter) continue;
          if (tl.on && P.t[i] > tl.cur) continue;
          const dx = P.x[i] - wx; const dy = P.y[i] - wy; const d = dx * dx + dy * dy;
          if (d < bd) { bd = d; best = i; }
        }
      }
    }
    return best;
  }
  function hitAt(mx, my, touch) {
    const rad = touch ? 22 : 12;
    let best = null; let bd = rad * rad;
    for (const l of F || EMPTY) {
      if (!layers[l.id]) continue;
      l.items.forEach((it, j) => {
        const dx = sx(it.x) - mx; const dy = sy(it.y) - my; const d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = { type: 'fac', layer: l.id, j }; }
      });
    }
    if (best) return best;
    if (layers.permits) { const i = nearestPoint(mx, my, rad); if (i >= 0) return { type: 'pt', i }; }
    if (layers.zips && Z) {
      let hit = null; let hr = Infinity; const zoom = st.k / st.k0;
      for (let j = 0; j < Z.list.length; j++) {
        const z = Z.list[j]; const dx = sx(z.x) - mx; const dy = sy(z.y) - my; const r = zipR(z, zoom) + 2;
        if (dx * dx + dy * dy < r * r && r < hr) { hit = { type: 'zip', j }; hr = r; }
      }
      if (hit) return hit;
    }
    const ci = countyAt(G, (mx - st.w / 2) / st.k + st.cx, (my - st.h / 2) / st.k + st.cy);
    return ci >= 0 ? { type: 'county', i: ci } : null;
  }
  const sameHit = (a, b) => (!a && !b) || (a && b && a.type === b.type && a.i === b.i && a.j === b.j && a.layer === b.layer);

  /* input */
  const ptrs = new Map(); let drag = null; let pinch = null;
  // pointer position in canvas CSS pixels, from client coordinates (also right for scripted events)
  const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  canvas.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* a pointer that is already gone, or a synthetic one */ }
    const [px, py] = pos(e);
    ptrs.set(e.pointerId, { x: px, y: py });
    if (ptrs.size === 1) drag = { x: px, y: py, moved: false, t: performance.now(), touch: e.pointerType !== 'mouse' };
    else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()];
      pinch = { d: Math.max(10, Math.hypot(a.x - b.x, a.y - b.y)), k: st.k, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
      drag = null;
    }
  });
  canvas.addEventListener('pointermove', (e) => {
    const p = ptrs.get(e.pointerId); const [px, py] = pos(e);
    if (p && ptrs.size === 2 && pinch) {
      p.x = px; p.y = py;
      const [a, b] = [...ptrs.values()];
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const wx = (pinch.mid.x - st.w / 2) / st.k + st.cx; const wy = (pinch.mid.y - st.h / 2) / st.k + st.cy;
      const nk = clamp(pinch.k * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d, st.k0, st.k0 * ZMAX);
      st.k = st.tk = nk;
      [st.cx, st.cy] = clampCenter(wx - (mid.x - st.w / 2) / nk, wy - (mid.y - st.h / 2) / nk, nk);
      st.tcx = st.cx; st.tcy = st.cy; st.anchor = null; pinch.mid = mid;
      busy(); invalidate(); return;
    }
    if (p && drag) {
      const dx = px - p.x; const dy = py - p.y;
      p.x = px; p.y = py;
      if (!drag.moved && Math.hypot(px - drag.x, py - drag.y) > (drag.touch ? 8 : 4)) {
        drag.moved = true; canvas.style.cursor = 'grabbing'; clearHover();
      }
      if (drag.moved) panPx(dx, dy);
      return;
    }
    if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
    const hit = hitAt(px, py, false);
    canvas.style.cursor = hit ? 'pointer' : 'grab';
    if (!sameHit(hit, hover)) { hover = hit; invalidate(); }
    emit('hover', hit, e.clientX, e.clientY);
  });
  const end = (e) => {
    const was = ptrs.has(e.pointerId);
    ptrs.delete(e.pointerId);
    if (ptrs.size < 2) pinch = null;
    if (!was) return;
    canvas.style.cursor = hover ? 'pointer' : 'grab';
    if (drag && !drag.moved && e.type === 'pointerup' && performance.now() - drag.t < 700) {
      const [px, py] = pos(e);
      emit('select', hitAt(px, py, drag.touch), e.clientX, e.clientY);
    }
    if (!ptrs.size) drag = null;
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('pointerleave', () => { if (hover) { hover = null; invalidate(); } emit('hover', null); });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    const [px, py] = pos(e);
    zoomAt(px, py, Math.exp(-dy * (e.ctrlKey ? 0.012 : 0.0022)));
    emit('hover', null);
  }, { passive: false });
  canvas.addEventListener('dblclick', (e) => { e.preventDefault(); const [px, py] = pos(e); zoomAt(px, py, e.shiftKey ? 0.5 : 2.2); });
  host.addEventListener('keydown', (e) => {
    if (e.target !== host || e.ctrlKey || e.metaKey || e.altKey) return;
    const pan = (e.shiftKey ? 0.6 : 0.25);
    const keys = {
      ArrowLeft: () => nudge(-pan * st.w, 0), ArrowRight: () => nudge(pan * st.w, 0),
      ArrowUp: () => nudge(0, -pan * st.h), ArrowDown: () => nudge(0, pan * st.h),
      '+': () => zoomBy(1.6), '=': () => zoomBy(1.6), '-': () => zoomBy(1 / 1.6), _: () => zoomBy(1 / 1.6),
      0: () => reset(),
    };
    const fn = keys[e.key];
    if (!fn) return;
    e.preventDefault(); fn(); emit('hover', null);
  });
  function nudge(dx, dy) {
    const nx = st.tcx + dx / st.k; const ny = st.tcy + dy / st.k;
    flyTo(nx, ny, st.tk);
  }
  function zoomBy(f) { zoomAt(st.w / 2, st.h / 2, f); }

  new ResizeObserver(resize).observe(host);
  window.addEventListener('resize', resize);

  /* QA: time pan frames the way a drag produces them (cached layer) and one crisp repaint, with a forced raster flush.
     Does not wait for requestAnimationFrame, so it also works in a background tab. */
  async function benchmark(frames = 120, zoom = 1) {
    const save = { ...st };
    const k = st.k0 * zoom; const cx = G.W * 0.42; const cy = G.H * 0.56;
    Object.assign(st, { k, tk: k, cx, cy, tcx: cx, tcy: cy, anchor: null });
    const flush = async () => { const b = await createImageBitmap(canvas); b.close(); };
    pc.ok = false; busyUntil = 0; draw(); await flush(); // warm: crisp layer at this view
    const full = [];
    for (let i = 0; i < frames; i++) {
      const a = (i / frames) * TAU * 2;
      st.cx = cx + Math.sin(a) * (30 / zoom + 6); st.cy = cy + Math.cos(a) * (24 / zoom + 6);
      busyUntil = performance.now() + 1000;
      const t0 = performance.now(); draw(); await flush(); full.push(performance.now() - t0);
    }
    busyUntil = 0; pc.ok = false;
    const t1 = performance.now(); draw(); await flush(); const settle = performance.now() - t1;
    Object.assign(st, save); pc.ok = false; invalidate();
    const q = (arr, p) => arr.slice().sort((x, y) => x - y)[Math.min(arr.length - 1, Math.floor(arr.length * p))];
    const avg = (arr) => arr.reduce((t, v) => t + v, 0) / arr.length;
    return {
      points: P.n, zoom, frames, panFrameMsAvg: +avg(full).toFixed(2), panFrameMsP95: +q(full, 0.95).toFixed(2),
      panFrameMsMax: +Math.max(...full).toFixed(2), crispRepaintMs: +settle.toFixed(2), layerRenderMs: +lastRenderMs.toFixed(2),
    };
  }

  return {
    resize, invalidate, setTheme, setCountyColors, benchmark, hitAt, dbg,
    on(t, fn) { handlers[t] = fn; },
    setLayers(o) { Object.assign(layers, o); pc.ok = false; clearHover(); invalidate(); },
    setOpFilter(i) { opFilter = i; pc.ok = false; clearHover(); invalidate(); },
    setBasin(b) { basinSel = b ? { boundary: b.boundary, get dim() { return b.dim; } } : null; invalidate(); },
    // replay by issue day: on/off and the current day (days since t0, fractional)
    setTimelapse(on, cur) {
      if (on && (!tl.order || tl.forP !== P)) buildOrder();
      if (tl.on !== !!on) { pc.ok = false; clearHover(); }
      tl.on = !!on;
      if (on) { tl.cur = cur; tl.cut = Math.floor(cur) - tl.fade; }
      invalidate();
    },
    // located permits shown so far in the replay (respects the operator filter)
    tlCount(cur) {
      if (!tl.order || tl.forP !== P) buildOrder();
      if (opFilter === -1) return upper(Math.floor(cur));
      const list = P.byOp.get(opFilter) || EMPTY; let n = 0;
      for (let q = 0; q < list.length; q++) if (P.t[list[q]] <= cur) n++;
      return n;
    },
    get tlRange() { if (!tl.order || tl.forP !== P) buildOrder(); return [tl.ts[0], tl.ts[tl.ts.length - 1]]; },
    setSelection(o) { Object.assign(sel, o); invalidate(); },
    setHover(hit) { if (!sameHit(hit, hover)) { hover = hit; invalidate(); } },
    setPadBottom(px) { padB = px; },
    // QA: run any pending zoom or pan animation to its end, synchronously
    settle() { let n = 0; while ((st.k !== st.tk || st.anchor || st.cx !== st.tcx || st.cy !== st.tcy) && n++ < 600) step(16); animating = false; draw(); },
    swapPoints(p) { P = p || P0; pc.ok = false; invalidate(); },
    zoomBy, reset, fitBox, flyTo,
    zoomTo(k) { zoomAt(st.w / 2, st.h / 2, clamp(k, 1, ZMAX) * st.k0 / st.tk); },
    pan: nudge,
    fitCounty(i) { fitBox(G.counties[i].bb, { pad: 36, maxZoom: 14 }); },
    fitOp(idx) {
      const l = P.byOp.get(idx);
      if (!l || !l.length) return false;
      const bb = [Infinity, Infinity, -Infinity, -Infinity];
      for (const i of l) {
        bb[0] = Math.min(bb[0], P.x[i]); bb[1] = Math.min(bb[1], P.y[i]); bb[2] = Math.max(bb[2], P.x[i]); bb[3] = Math.max(bb[3], P.y[i]);
      }
      fitBox(bb, { pad: 56, maxZoom: 9 });
      return true;
    },
    // center a point in the uncovered part of the map; keepZoom never zooms out from the current level
    focusXY(x, y, zoom, keepZoom) {
      if (!st.w) { pendingView = () => this.focusXY(x, y, zoom, keepZoom); return; }
      const z = keepZoom ? Math.max(zoom, st.tk / st.k0) : zoom; flyTo(x, y + padB / 2 / (st.k0 * z), st.k0 * z); },
    screenOf: (x, y) => [sx(x), sy(y)],
    get zoom() { return st.k / st.k0; },
    get stats() { return { lastMs, w: st.w, h: st.h, dpr: st.dpr, zoom: st.k / st.k0 }; },
  };
}
