// Hero backdrop: county outlines and every located permit as glowing dots, with a gentle pulse on a few.
// The still layers are painted once to an offscreen canvas; each frame only blits it and draws the pulses.
// The loop stops when the hero is off-screen, the tab is hidden, or reduced motion is on.
import { clamp, onReducedChange, reduced, whenVisible } from './util.js';
import { isDark, onTheme } from './theme.js';

const TAU = Math.PI * 2;
// Texas's permits are orange, Oklahoma's purple and New Mexico's green: the states' colors everywhere (--st-tx, --st-ok, --st-nm), in the order of STATES
const PALETTE = {
  dark: {
    grat: 'rgba(160,190,230,0.05)', line: 'rgba(150,180,220,0.14)', border: 'rgba(170,200,240,0.5)', glow: 'rgba(60,130,230,0.16)',
    fill: 'rgba(110,150,215,0.045)', ring: null,
    st: [
      { old: 'rgba(255,138,78,0.5)', fresh: 'rgba(255,176,118,0.98)', pulse: 'rgb(255,160,100)', halo: ['rgba(255,170,112,0.95)', 'rgba(240,108,52,0.4)', 'rgba(235,104,52,0)'] },
      { old: 'rgba(150,132,245,0.55)', fresh: 'rgba(192,178,255,0.98)', pulse: 'rgb(170,152,255)', halo: ['rgba(190,176,255,0.95)', 'rgba(128,108,238,0.4)', 'rgba(110,90,226,0)'] },
      { old: 'rgba(40,196,140,0.5)', fresh: 'rgba(120,232,186,0.98)', pulse: 'rgb(80,214,160)', halo: ['rgba(130,236,192,0.95)', 'rgba(30,178,126,0.4)', 'rgba(25,158,112,0)'] },
    ],
  },
  light: {
    grat: 'rgba(20,40,80,0.05)', line: 'rgba(20,45,90,0.15)', border: 'rgba(20,50,100,0.5)', glow: 'rgba(42,120,214,0.1)',
    fill: 'rgba(255,255,255,0.55)', ring: 'rgba(255,255,255,0.85)',
    st: [
      { old: 'rgba(235,104,52,0.42)', fresh: 'rgba(235,104,52,0.95)', pulse: 'rgb(235,104,52)', halo: ['rgba(255,170,112,0.95)', 'rgba(240,108,52,0.4)', 'rgba(235,104,52,0)'] },
      { old: 'rgba(98,80,214,0.42)', fresh: 'rgba(98,80,214,0.95)', pulse: 'rgb(98,80,214)', halo: ['rgba(160,146,245,0.95)', 'rgba(108,90,222,0.4)', 'rgba(98,80,214,0)'] },
      { old: 'rgba(27,175,122,0.42)', fresh: 'rgba(22,150,104,0.95)', pulse: 'rgb(22,150,104)', halo: ['rgba(110,214,170,0.95)', 'rgba(27,175,122,0.4)', 'rgba(27,175,122,0)'] },
    ],
  },
};

function rng(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createHero(canvas, host, G0, P0) {
  let G = G0; let P = P0; // the shapes and points can be swapped (update) when the states shown change
  const ctx = canvas.getContext('2d');
  const base = document.createElement('canvas'); const bctx = base.getContext('2d');
  let w = 0; let h = 0; let dpr = 1; let k = 1; let tx = 0; let ty = 0;
  let visible = true; let raf = 0; let dark = isDark();
  let pulses = [];
  function pick() {
    const rand = rng(7);
    const recent = [];
    for (let i = 0; i < P.n; i++) if (P.rec[i]) recent.push(i);
    pulses = [];
    for (let n = 0; n < 90 && recent.length; n++) {
      const i = recent[Math.floor(rand() * recent.length)];
      pulses.push({ i, st: P.st ? P.st[i] : 0, phase: rand(), period: 2600 + rand() * 1800, x: 0, y: 0 });
    }
  }
  pick();

  function sprite(halo) {
    const s = document.createElement('canvas'); s.width = s.height = 64;
    const g = s.getContext('2d'); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, halo[0]); gr.addColorStop(0.27, halo[1]); gr.addColorStop(1, halo[2]);
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    return s;
  }

  function layout() {
    let box;
    if (w >= 900) {
      // the map keeps clear of the KPI strip so no part of the state sits behind a chip
      const kp = host.querySelector('.kpis'); const hi = host.querySelector('.hero-in');
      box = { x0: Math.max(w * 0.4, hi ? hi.offsetLeft + hi.offsetWidth + 10 : 0), x1: w - 28, y0: 22, y1: kp ? kp.offsetTop - 16 : h - 22 };
    } else {
      // stacked layout: the map sits in the space the CSS reserves under the text, above the KPI strip
      const kp = host.querySelector('.kpis'); const hi = host.querySelector('.hero-in');
      const reserve = (hi && parseFloat(getComputedStyle(hi).paddingBottom)) || 260;
      const bottom = kp ? kp.offsetTop - 8 : h - 8;
      box = { x0: 6, x1: w - 6, y0: Math.max(0, bottom - reserve + 6), y1: bottom };
    }
    k = Math.min((box.x1 - box.x0) / G.W, (box.y1 - box.y0) / G.H);
    tx = (box.x0 + box.x1) / 2 - (G.W / 2) * k; ty = (box.y0 + box.y1) / 2 - (G.H / 2) * k;
    for (const p of pulses) { p.x = P.x[p.i] * k + tx; p.y = P.y[p.i] * k + ty; }
  }

  function paintBase() {
    const c = PALETTE[dark ? 'dark' : 'light'];
    base.width = Math.round(w * dpr); base.height = Math.round(h * dpr);
    bctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * tx, dpr * ty);
    bctx.lineJoin = 'round'; bctx.lineCap = 'round';
    bctx.lineWidth = 0.6 / k; bctx.strokeStyle = c.grat; bctx.stroke(G.grat);
    bctx.fillStyle = c.fill; bctx.fill(G.outline);
    bctx.lineWidth = 0.6 / k; bctx.strokeStyle = c.line; bctx.stroke(G.outline);
    bctx.lineWidth = 6 / k; bctx.strokeStyle = c.glow; bctx.stroke(G.border);
    bctx.lineWidth = 1.2 / k; bctx.strokeStyle = c.border; bctx.stroke(G.border);
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const rn = clamp(k * 2.7, 1.45, 3.1); const ro = rn * 0.8;
    const sps = c.st.map((q) => sprite(q.halo));
    const stOf = (i) => (P.st ? P.st[i] : 0);
    bctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
    for (let pass = 0; pass < 2; pass++) {
      const gr = (pass ? rn : ro) * 3.6;
      bctx.globalAlpha = dark ? (pass ? 0.55 : 0.26) : (pass ? 0.5 : 0.2);
      for (let i = 0; i < P.n; i++) if (P.rec[i] === pass) bctx.drawImage(sps[stOf(i)], P.x[i] * k + tx - gr, P.y[i] * k + ty - gr, gr * 2, gr * 2);
    }
    bctx.globalAlpha = 1; bctx.globalCompositeOperation = 'source-over';
    for (let pass = 0; pass < 2; pass++) {
      const r = pass ? rn : ro;
      for (let st = 0; st < c.st.length; st++) {
        bctx.beginPath();
        let any = false;
        for (let i = 0; i < P.n; i++) {
          if (P.rec[i] !== pass || stOf(i) !== st) continue;
          const x = P.x[i] * k + tx; const y = P.y[i] * k + ty;
          bctx.moveTo(x + r, y); bctx.arc(x, y, r, 0, TAU); any = true;
        }
        if (!any) continue;
        bctx.fillStyle = pass ? c.st[st].fresh : c.st[st].old; bctx.fill();
        if (pass && c.ring) { bctx.lineWidth = 0.8; bctx.strokeStyle = c.ring; bctx.stroke(); }
      }
    }
  }

  function blit() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(base, 0, 0, w, h);
  }
  function frame(now) {
    raf = 0;
    if (!visible || document.hidden || reduced()) return;
    blit();
    const c = PALETTE[dark ? 'dark' : 'light'];
    ctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
    ctx.lineWidth = 1.2;
    for (const p of pulses) {
      const u = (now / p.period + p.phase) % 1;
      ctx.strokeStyle = c.st[p.st].pulse;
      ctx.globalAlpha = 0.62 * (1 - u) * (1 - u);
      ctx.beginPath(); ctx.arc(p.x, p.y, 2 + 16 * u, 0, TAU); ctx.stroke();
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
    raf = requestAnimationFrame(frame);
  }
  function sync() {
    cancelAnimationFrame(raf); raf = 0;
    if (!w) return;
    blit();
    if (visible && !document.hidden && !reduced()) raf = requestAnimationFrame(frame);
  }
  function resize() {
    const nw = host.clientWidth; const nh = host.clientHeight;
    if (!nw || !nh) return;
    const nd = Math.min(window.devicePixelRatio || 1, 2.5);
    if (nw === w && nh === h && nd === dpr) return;
    w = nw; h = nh; dpr = nd;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    layout(); paintBase(); sync();
  }

  new ResizeObserver(resize).observe(host);
  // the KPI strip fills in after the data arrives and moves the map's keep-out line without resizing the card
  const strip = host.querySelector('.kpis');
  if (strip) new ResizeObserver(() => { if (w) { layout(); paintBase(); sync(); } }).observe(strip);
  whenVisible(host, (v) => { visible = v; sync(); }, { once: false, threshold: 0 });
  document.addEventListener('visibilitychange', sync);
  onReducedChange(sync);
  onTheme(() => { dark = isDark(); if (w) { paintBase(); sync(); } });
  resize();
  return {
    resize,
    update(nextG, nextP) {
      G = nextG; P = nextP; pick();
      if (w) { layout(); paintBase(); sync(); }
    },
  };
}
