// Accessibility test. Serves site/public and checks two things in a real browser.
//
// 1. Contrast: every view in the light and the dark theme at a desktop and a phone width; the WCAG contrast of every visible piece of text
//    against what is behind it, 4.5:1 (3:1 for large text: 24 px, or 18.66 px and bold). Text over a gradient is held to its worst color stop.
//    Disabled controls and hidden text are exempt, as in WCAG. It exists because three things had slipped through by eye on 2026-10-31: a
//    state's own color used as text (2.7 to 3.0:1), the "Publishes monthly" tags in a grey that is not themed (3.4:1) and the white text on the
//    primary button's gradient (3.5 to 4.6:1).
// 2. Keyboard: Tab through each view; every stop has a name and shows a focus ring, and focus never sticks on one element. Each page has a
//    language, one main landmark and a title that follows the view.
// 3. Reflow: at 360 px wide (the narrowest phone) no content is cut off by an overflow:hidden box (without an ellipsis) and no box sticks out
//    past the right edge outside a scroller, on every view and every set of states. It found a note and a sparkline cut off in the Daily report's
//    half-width cards (the card's one column had grown to the sparkline's fixed 160 px).
// 4. Target size: at the same width every button, field, tab and chip is at least 24 x 24 px (WCAG 2.2, 2.5.8; a checkbox counts with its label; links
//    inside text and in table cells are left out: spacing exempts them).
//
// Run: node tests/a11y.cjs
// Needs Playwright (preinstalled in the Claude sandbox; installed by .github/workflows/ci.yml).
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..', 'site', 'public');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.png': 'image/png', '.txt': 'text/plain; charset=utf-8' };

// the well archive is served from a fixture (tests/fixtures/wells.json), so these tests do not depend on what the nightly has published
const WELLS = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'wells.json'), 'utf8'));
function wellsFile(p) {
  if (p === '/data/wells/index.json') return WELLS.index;
  const m = /^\/data\/wells\/county\/(\d{3})\.json$/.exec(p);
  return m ? WELLS.counties[m[1]] || null : null;
}

function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (p.endsWith('/')) p += 'index.html';
    const fixture = wellsFile(p);
    if (fixture) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(fixture)); return; }
    const file = path.normalize(path.join(ROOT, p));
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, base: 'http://127.0.0.1:' + server.address().port + '/' })));
}

// [name, hash, a selector that appears once the view has drawn]
const VIEWS = [
  ['overview', '#overview', '#hot-bars .bar-row'],
  ['overview Oklahoma', '#overview?st=ok', '#hot-bars .bar-row'],
  ['map', '#map', '#map-root canvas'],
  ['operators', '#operators', '#ops-root table.grid tbody tr'],
  ['operators, three states', '#operators?st=tx,ok,nm', '#ops-root table.grid tbody tr'],
  ['companies', '#companies', '#co-root table.grid tbody tr'],
  ['daily', '#daily', '#daily-root .dr-hero'],
  ['daily, verbose', '#daily?v=full', '#daily-root .dr-sec'],
  ['daily Oklahoma, verbose', '#daily?st=ok&v=full', '#daily-root .dr-sec'],
  ['daily New Mexico, verbose', '#daily?st=nm&v=full', '#daily-root .dr-sec'],
  // the federal offshore last: the bar keeps its choice from one view to the next, and the views above are meant for the states they name
  ['overview, federal offshore', '#overview?st=fo', '#hot-bars .bar-row'],
  ['map, federal offshore', '#map?st=fo', '#map-root canvas'],
  ['operators, federal offshore', '#operators?st=fo', '#ops-root table.grid tbody tr'],
  ['sources', '#about', '#view-about h1'],
  ['national', '#national', '#national-root .nat-tile'],
  ['national, Oklahoma panel', '#national?s=OK', '#national-root .nat-panel h3'],
  ['texas images', '#images', '#images-root .img-pack'],
  ['texas images, a county', '#images?c=283', '#images-root a.well-row'],
  ['texas images, a well', '#images?well=28337830', '#images-root .well-doc'],
  ['permit data', '#fields', '#fields-root button.fx-c'],
  ['permit data, an agency', '#fields?s=BL', '#fields-root .nat-panel h3'],
];
const SIZES = [[1280, 800], [390, 844]];

// runs in the page: every visible text with a ratio under its threshold
function audit() {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const g = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (css) => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = css; g.fillRect(0, 0, 1, 1); const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (top, bot) => { const a = top[3] + bot[3] * (1 - top[3]); if (!a) return [0, 0, 0, 0]; return [0, 1, 2].map((i) => (top[i] * top[3] + bot[i] * bot[3] * (1 - top[3])) / a).concat([a]); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  let page = rgba(getComputedStyle(document.body).backgroundColor);
  if (page[3] < 1) page = over(page, [255, 255, 255, 1]);
  const COLOR = /(rgba?\([^)]*\)|color\([^)]*\)|oklab\([^)]*\)|oklch\([^)]*\)|lab\([^)]*\)|lch\([^)]*\)|hsla?\([^)]*\))/g;
  // a comma list split where the commas are not inside brackets (a gradient has its own)
  const splitTop = (str) => { const out = []; let depth = 0, from = 0; for (let i = 0; i < str.length; i++) { const ch = str[i]; if (ch === '(') depth++; else if (ch === ')') depth--; else if (ch === ',' && !depth) { out.push(str.slice(from, i).trim()); from = i + 1; } } out.push(str.slice(from).trim()); return out; };
  // the gradient layers that paint under an element's text: a layer clipped to the border box is only the hairline round a card (its padding box is
  // painted over it) when another layer is clipped inside it, so it is not what the text sits on
  const paintedImages = (cs) => {
    if (cs.backgroundImage === 'none') return [];
    const images = splitTop(cs.backgroundImage);
    const clips = splitTop(cs.backgroundClip);
    const inner = clips.some((c) => c !== 'border-box');
    const bordered = parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0;
    return images.filter((img, i) => img !== 'none' && !(inner && bordered && clips[i % clips.length] === 'border-box'));
  };
  // what is behind an element: the flat backgrounds composited, and every color stop of a gradient on the way (the worst one counts)
  const behind = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const c = rgba(cs.backgroundColor);
      const stops = paintedImages(cs).flatMap((img) => img.match(COLOR) || []).map(rgba);
      if (c[3] > 0 || stops.length) layers.push({ c, stops });
      if (c[3] >= 1) break;
    }
    let bases = [page];
    for (let i = layers.length - 1; i >= 0; i--) {
      const { c, stops } = layers[i];
      const next = [];
      for (const b of bases) { const flat = c[3] > 0 ? over(c, b) : b; if (stops.length) for (const s of stops) next.push(over(s, flat)); else next.push(flat); }
      bases = next;
    }
    return bases;
  };
  const out = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.nodeValue.trim();
    const el = n.parentElement;
    if (!t || !el || seen.has(el)) continue;
    seen.add(el);
    if (el.closest('script,style,noscript,[hidden],[aria-hidden="true"],.sr-only,:disabled,[aria-disabled="true"]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.right < 0 || r.bottom < 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    let opacity = 1;
    for (let e = el; e; e = e.parentElement) opacity *= +getComputedStyle(e).opacity;
    if (opacity === 0) continue;
    const tag = el.tagName.toLowerCase();
    if (el.closest('svg') && tag !== 'text' && tag !== 'tspan') continue;
    const paint = el.closest('svg') ? cs.fill : cs.color;
    if (!paint || paint === 'none') continue;
    const fg = rgba(paint);
    fg[3] *= opacity;
    const size = parseFloat(cs.fontSize);
    const weight = +cs.fontWeight || 400;
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    let worst = Infinity;
    for (const b of behind(el)) worst = Math.min(worst, ratio(over(fg, b), b));
    if (worst < need) {
      const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '';
      out.push({ id: tag + cls, text: t.slice(0, 36), ratio: +worst.toFixed(2), need });
    }
  }
  return out;
}

// runs in the page: content cut off by overflow, and boxes past the right edge of the viewport that no scroller holds
function reflow() {
  const out = [];
  const vw = document.documentElement.clientWidth;
  const name = (el) => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const clipsX = cs.overflowX === 'hidden' || cs.overflowX === 'clip';
    if (clipsX && cs.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && !el.matches('.sr-only,.map-stage,.dr-hero,.hero')) {
      out.push(name(el) + ' cuts off ' + (el.scrollWidth - el.clientWidth) + ' px: "' + (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"');
    }
    if (r.right > vw + 1) {
      let held = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') { held = true; break; } }
      if (!held) out.push(name(el) + ' runs ' + Math.round(r.right - vw) + ' px past the edge: "' + (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"');
    }
  }
  return out;
}

// runs in the page: controls under 24 x 24 CSS px
function targets() {
  const out = [];
  for (const el of document.querySelectorAll('button, select, input:not([type=hidden]), textarea, [role=tab], a.pill-link, a.more-link, a.btn')) {
    if (el.closest('[hidden], [aria-hidden="true"], .sr-only') || el.disabled) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    let r = el.getBoundingClientRect();
    if (el.matches('input[type=checkbox], input[type=radio]') && el.labels && el.labels[0]) r = el.labels[0].getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.width < 24 - 0.5 || r.height < 24 - 0.5) out.push(el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + ' is ' + Math.round(r.width) + ' x ' + Math.round(r.height) + ': "' + (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24) + '"');
  }
  return out;
}

(async () => {
  const { server, base } = await serve();
  const browser = await chromium.launch();
  let failures = 0;
  const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failures++; };

  for (const theme of ['light', 'dark']) {
    for (const [w, h] of SIZES) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce', colorScheme: theme, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const label = theme + ', ' + (w > 600 ? 'desktop' : 'phone');
      const bad = new Map();
      let read = 0;
      for (const [name, hash, ready] of VIEWS) {
        try {
          await page.goto(base + hash, { waitUntil: 'load' });
          await page.waitForSelector(ready, { timeout: 25000 });
          await page.waitForTimeout(600);
          for (const f of await page.evaluate(audit)) {
            const k = f.id + ' "' + f.text + '"';
            if (!bad.has(k)) bad.set(k, { ...f, where: [] });
            bad.get(k).where.push(name);
          }
          read++;
        } catch (e) {
          check(false, label + ': ' + name + ' did not draw: ' + e.message.split('\n')[0].slice(0, 160));
        }
      }
      check(bad.size === 0, label + ': text on ' + read + ' views meets 4.5:1 (3:1 for large text)');
      for (const [k, f] of bad) console.log('       ' + f.ratio + ' (needs ' + f.need + ')  ' + k + '  in ' + [...new Set(f.where)].join(', '));
      await ctx.close();
    }
  }

  // ---- reflow
  {
    const REFLOW = [
      ['overview', '#overview', '#hot-bars .bar-row'], ['overview, Oklahoma', '#overview?st=ok', '#hot-bars .bar-row'],
      ['map', '#map', '#map-root canvas'], ['operators', '#operators', '#ops-root table.grid tbody tr'], ['operators, New Mexico', '#operators?st=nm', '#ops-root table.grid tbody tr'],
      ['companies', '#companies?st=tx', '#co-root table.grid tbody tr'],
      ['daily', '#daily', '#daily-root .dr-hero'], ['daily, Texas', '#daily?st=tx', '#daily-root .dr-hero'], ['daily, Oklahoma', '#daily?st=ok', '#daily-root .dr-hero'], ['daily, New Mexico', '#daily?st=nm', '#daily-root .dr-hero'],
      ['daily, verbose', '#daily?v=full', '#daily-root .dr-sec'], ['daily Oklahoma, verbose', '#daily?st=ok&v=full', '#daily-root .dr-sec'], ['daily New Mexico, verbose', '#daily?st=nm&v=full', '#daily-root .dr-sec'],
      ['overview, federal offshore', '#overview?st=fo', '#hot-bars .bar-row'], ['map, federal offshore', '#map?st=fo', '#map-root canvas'], ['operators, federal offshore', '#operators?st=fo', '#ops-root table.grid tbody tr'],
      ['sources', '#about', '#view-about h1'], ['national', '#national', '#national-root .nat-tile'], ['national, New Mexico panel', '#national?s=NM&m=spuds', '#national-root .nat-panel h3'],
      ['texas images', '#images', '#images-root .img-pack'], ['texas images, a county', '#images?c=283', '#images-root a.well-row'], ['texas images, a well', '#images?well=28337830', '#images-root .well-doc'],
      ['permit data', '#fields', '#fields-root button.fx-c'], ['permit data, an agency', '#fields?s=BL', '#fields-root .nat-panel h3'],
    ];
    const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: 'reduce', colorScheme: 'light' });
    const page = await ctx.newPage();
    const bad = [];
    const small = [];
    for (const [name, hash, ready] of REFLOW) {
      try {
        await page.goto(base + hash, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        await page.waitForTimeout(600);
        for (const f of await page.evaluate(reflow)) bad.push(name + ': ' + f);
        for (const f of await page.evaluate(targets)) small.push(name + ': ' + f);
      } catch (e) {
        check(false, 'reflow, ' + name + ' did not draw: ' + e.message.split('\n')[0].slice(0, 160));
      }
    }
    check(!bad.length, 'at 360 px on ' + REFLOW.length + ' views nothing is cut off and nothing runs past the edge' + (bad.length ? '\n       ' + [...new Set(bad)].slice(0, 12).join('\n       ') : ''));
    check(!small.length, 'at 360 px every button, field, tab and chip is at least 24 x 24 px' + (small.length ? '\n       ' + [...new Set(small)].slice(0, 12).join('\n       ') : ''));
    await ctx.close();
  }

  // ---- keyboard
  // the stops of one view: [id, accessible name, ring shown, the same element as the stop before]
  const stopInfo = () => {
    const e = document.activeElement;
    if (!e || e === document.body) return null;
    const ring = (x) => { const c = getComputedStyle(x); return c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0 && c.outlineColor !== 'rgba(0, 0, 0, 0)'; };
    const labelled = e.getAttribute('aria-labelledby');
    const name = (e.getAttribute('aria-label') || (labelled && document.getElementById(labelled) && document.getElementById(labelled).textContent) || (e.labels && e.labels[0] && e.labels[0].textContent) || e.textContent || e.getAttribute('title') || e.value || e.placeholder || '').trim().replace(/\s+/g, ' ');
    // a map dot answers focus with a thicker outline of its own color (stroke), a layer chip with an outline on its label (the input is hidden)
    const shown = ring(e) || (e.tagName === 'INPUT' && !!e.nextElementSibling && ring(e.nextElementSibling)) || e.classList.contains('dr-pt');
    window.__kbSeen = window.__kbSeen || new WeakMap();
    const times = (window.__kbSeen.get(e) || 0) + 1;
    window.__kbSeen.set(e, times);
    const same = window.__kbPrev === e;
    window.__kbPrev = e;
    const cls = typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return { id: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + cls, name: name.slice(0, 40), shown, times, same };
  };
  const KB_VIEWS = [VIEWS[0], VIEWS[2], VIEWS[3], VIEWS[5], VIEWS[6], VIEWS[10]];
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce', colorScheme: 'light', deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    for (const [name, hash, ready] of KB_VIEWS) {
      try {
        await page.goto(base + hash, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        await page.waitForTimeout(600);
        await page.evaluate(() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); window.__kbSeen = new WeakMap(); window.__kbPrev = null; });
        const stops = [];
        for (let i = 0; i < 120; i++) {
          await page.keyboard.press('Tab');
          const s2 = await page.evaluate(stopInfo);
          if (!s2) { if (stops.length > 3) break; continue; }
          if (s2.times > 1 && !s2.same) break; // went all the way round
          stops.push(s2);
          if (s2.same) break;
        }
        const unnamed = stops.filter((x) => !x.name).map((x) => x.id);
        const bare = stops.filter((x) => !x.shown).map((x) => x.id + ' "' + x.name + '"');
        const stuck = stops.filter((x) => x.same).map((x) => x.id + ' "' + x.name + '"');
        check(stops.length >= 8 && !unnamed.length && !bare.length && !stuck.length,
          'keyboard, ' + name + ': ' + stops.length + ' stops, each named, each shows a ring, none sticks' + (unnamed.length ? ' [no name: ' + [...new Set(unnamed)].slice(0, 4).join(', ') + ']' : '') + (bare.length ? ' [no ring: ' + [...new Set(bare)].slice(0, 4).join(', ') + ']' : '') + (stuck.length ? ' [stuck on: ' + stuck.join(', ') + ']' : ''));
      } catch (e) {
        check(false, 'keyboard, ' + name + ' did not draw: ' + e.message.split('\n')[0].slice(0, 160));
      }
    }
    // the page itself
    await page.goto(base + '#overview', { waitUntil: 'load' });
    await page.waitForSelector('#hot-bars .bar-row', { timeout: 25000 });
    const doc = await page.evaluate(() => ({ lang: document.documentElement.lang, mains: document.querySelectorAll('main').length, h1s: [...document.querySelectorAll('h1')].filter((h) => h.offsetParent !== null).length, title: document.title }));
    check(doc.lang === 'en' && doc.mains === 1 && doc.h1s === 1, 'the page has a language, one main landmark and one visible h1: ' + JSON.stringify(doc));
    const titles = [];
    for (const hash of ['#map', '#operators', '#companies', '#daily', '#about']) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await page.waitForFunction((h) => document.title !== 'Oil tracker' || h === '#overview', hash, { timeout: 10000 }).catch(() => {});
      titles.push(await page.title());
    }
    check(new Set(titles).size === titles.length && titles.every((t) => /Oil tracker$/.test(t)) && !titles.includes('Oil tracker'), 'each view sets its own title: ' + titles.join(' | '));
    await ctx.close();
  }

  await browser.close();
  server.close();
  console.log(failures ? '\nFAILED ' + failures : '\nall passed');
  process.exit(failures ? 1 : 0);
})();
