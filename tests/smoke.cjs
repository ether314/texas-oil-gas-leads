// Browser smoke test. Serves site/public, imports every JS module in Chromium, then loads every view at a desktop and a phone width and
// fails on any console error, page error, failed request or sideways scroll. node --check does not catch syntax errors in ES modules;
// this does (one that broke the whole site slipped through on 2026-10-31).
//
// Run: node tests/smoke.cjs
// Needs Playwright (preinstalled in the Claude sandbox). In CI: npm install --no-save playwright@1.63.0 && npx playwright install --with-deps chromium
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..', 'site', 'public');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.png': 'image/png', '.txt': 'text/plain; charset=utf-8' };

function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (p.endsWith('/')) p += 'index.html';
    const file = path.normalize(path.join(ROOT, p));
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, base: 'http://127.0.0.1:' + server.address().port + '/' })));
}

// [hash, a selector that appears once the view has drawn, an optional extra check]
const VIEWS = [
  ['#overview', '#kpis > *'],
  ['#map', '#map-root canvas'],
  ['#operators', '#ops-root table'],
  ['#companies', '#co-root table'],
  ['#daily', '#daily-root .dr-hero'],
  ['#daily?v=full', '#daily-root .dr-sec'],
  ['#daily?st=tx', '#daily-root .dr-hero'],
  ['#daily?st=ok', '#daily-root .dr-hero', async (page) => (await page.locator('#daily-root path.dr-county').count()) === 77 ? null : 'the Oklahoma map should have 77 counties'],
  ['#daily?st=ok&v=full', '#daily-root .dr-sec'],
  ['#oklahoma', '#daily-root .dr-hero', async (page) => (/st=ok/.test(await page.evaluate(() => location.hash)) ? null : 'an old #oklahoma link should open #daily?st=ok')],
  ['#about', '#view-about h1'],
];
const SIZES = [['desktop', 1280, 800], ['phone', 390, 844]];

(async () => {
  const { server, base } = await serve();
  const browser = await chromium.launch();
  let failures = 0;
  const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failures++; };

  // 1. every module parses and loads
  {
    const page = await browser.newPage();
    await page.goto(base + 'favicon.svg');
    const files = fs.readdirSync(path.join(ROOT, 'js')).filter((f) => f.endsWith('.js') && !['main.js', 'boot.js'].includes(f)).sort();
    const bad = [];
    for (const f of files) {
      const r = await page.evaluate(async (u) => { try { await import(u); return 'ok'; } catch (e) { return e.name + ': ' + e.message; } }, base + 'js/' + f);
      if (r !== 'ok') bad.push(f + ' ' + r);
    }
    check(!bad.length, files.length + ' modules import in the browser' + (bad.length ? ': ' + bad.join('; ') : ''));
    await page.close();
  }

  // 2. every view, desktop and phone
  for (const [label, w, h] of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    for (const [hash, ready, extra] of VIEWS) {
      const page = await ctx.newPage();
      const errs = [];
      page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
      page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
      page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
      let problem = null;
      try {
        await page.goto(base + hash, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        await page.waitForTimeout(1200);
        const dims = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
        if (dims.sw > dims.cw) problem = 'sideways scroll (' + dims.sw + ' of ' + dims.cw + ' px)';
        // the site is the Oil tracker: the name is in the tab title and the header on every view
        const brand = await page.evaluate(() => ({ title: document.title, name: (document.querySelector('.brand-name') || {}).textContent }));
        if (!problem && (!/Oil tracker$/.test(brand.title) || brand.name !== 'Oil tracker')) problem = 'the site is not named Oil tracker (title "' + brand.title + '", header "' + brand.name + '")';
        if (!problem && extra) problem = await extra(page);
      } catch (e) {
        problem = 'did not draw: ' + e.message.split('\n')[0].slice(0, 140);
      }
      const all = errs.concat(problem ? [problem] : []);
      check(!all.length, label.padEnd(7) + hash.padEnd(21) + (all.length ? all.join(' | ') : 'loads clean'));
      await page.close();
    }
    await ctx.close();
  }

  // 3. the states shown: one choice in a bar above the views that follow it, kept in the address, and followed by the Overview and the Daily report
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const pressed = () => page.locator('#statebar button[aria-pressed="true"]').innerText();
    const hash = () => page.evaluate(() => location.hash);
    const eyebrow = () => page.locator('#hero-eyebrow').textContent(); // innerText would be the capitals the page's CSS makes of it
    const dailyEyebrow = (re) => page.waitForFunction((src) => { const e = document.querySelector('#daily-root .dr-hero .eyebrow'); return !!e && new RegExp(src, 'i').test(e.textContent); }, re.source, { timeout: 25000 });
    const waitEyebrow = (re) => page.waitForFunction((src) => new RegExp(src).test(document.querySelector('#hero-eyebrow').textContent), re.source, { timeout: 20000 });
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('#hot-bars li', { timeout: 25000 });
      await page.waitForSelector('#ins-list li.insight', { timeout: 25000 });
      check((await pressed()) === 'All' && (await page.locator('#statebar').isVisible()), 'the states bar is on the Overview and starts on All');
      check(/\(Texas\).*\(Oklahoma\).*\(New Mexico\)/.test(await eyebrow()) && (await page.locator('#hot-bars .bars-h').count()) === 3, 'all states: the hero names each state\'s last day and the lists have a heading per state');
      await page.click('#statebar button[data-id="OK"]');
      await waitEyebrow(/Corporation Commission approvals through/);
      check(/st=ok/.test(await hash()) && (await pressed()) === 'Oklahoma', 'choosing Oklahoma puts st=ok in the address');
      check((await page.locator('#kpis').innerText()).includes('Active wells') && !(await page.locator('#seg-chart').isVisible()), 'Oklahoma alone: its own figures, and the cards only Texas can fill step aside');
      await page.click('#statebar button[data-id="NM"]');
      await waitEyebrow(/Oil Conservation Division spud reports through/);
      check(/st=nm/.test(await hash()) && (await page.locator('#kpis').innerText()).includes('Wells spudded, last 12 months'), 'New Mexico alone: its wells spudded, its own date, st=nm in the address');
      await page.click('#statebar button[data-id="TX"]');
      await waitEyebrow(/^Railroad Commission permits through/);
      check(/st=tx/.test(await hash()) && (await page.locator('#seg-chart').isVisible()) && (await page.locator('#hot-bars .bars-h').count()) === 0, 'Texas alone: the original Overview, st=tx in the address');
      await page.click('#statebar button[data-id="all"]');
      await waitEyebrow(/\(Oklahoma\)/);
      check(!/st=/.test(await hash()), 'choosing All takes st out of the address');
      await page.click('#statebar button[data-id="OK"]');
      await waitEyebrow(/Corporation Commission/);
      await page.click('.nav a[href="#daily"]');
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      await page.waitForTimeout(800);
      check(/st=ok/.test(await hash()) && (await pressed()) === 'Oklahoma' && (await page.locator('#daily-root path.dr-county').count()) === 77, 'going to the Daily report keeps the choice: Oklahoma\'s 77 counties, st=ok in the address');
      await page.click('#statebar button[data-id="NM"]');
      await page.waitForFunction(() => /no Daily report yet/.test(document.querySelector('#statebar-note').textContent), null, { timeout: 20000 });
      check((await page.locator('#statebar-note').textContent()).includes('New Mexico has no Daily report yet'), 'a state with no Daily report: the bar says so on the Daily report');
      await page.click('#statebar button[data-id="OK"]');
      await page.click('.nav a[href="#operators"]');
      await page.waitForSelector('#ops-root table', { timeout: 25000 });
      check(!(await page.locator('#statebar').isVisible()) && /st=ok/.test(await hash()), 'a view that does not follow the choice hides the bar and keeps it in the address');
      await page.goto(base + '#daily?st=tx', { waitUntil: 'load' });
      await dailyEyebrow(/Railroad Commission report/);
      check((await pressed()) === 'Texas', 'an address with st=tx opens the Daily report on Texas alone, and the bar says so');
      await page.click('#statebar button[data-id="all"]');
      await dailyEyebrow(/Texas and Oklahoma report/);
      check(!/st=/.test(await hash()) && (await pressed()) === 'All', 'choosing All on the Daily report shows the states together and leaves st out of the address');
    } catch (e) {
      check(false, 'the states bar: ' + e.message.split('\n')[0].slice(0, 160));
    }
    check(!errs.length, 'the states bar loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  await browser.close();
  server.close();
  console.log('\n' + (failures ? 'FAILED ' + failures : 'all passed'));
  process.exit(failures ? 1 : 0);
})();
