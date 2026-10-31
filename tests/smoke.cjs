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
  ['#map?st=tx', '#map-root canvas', async (page) => (/^New-drill permits, /.test(await page.locator('.lg-title').innerText()) ? null : 'Texas alone should keep its own legend')],
  ['#map?st=ok', '#map-root canvas', async (page) => (/^New-drill permits, /.test(await page.locator('.lg-title').innerText()) && (await page.locator('.lg-states').count()) === 0 ? null : 'the Oklahoma map should say permits and need no state legend')],
  ['#map?st=nm', '#map-root canvas', async (page) => (/^Wells spudded, /.test(await page.locator('.lg-title').innerText()) ? null : 'the New Mexico map should say wells spudded')],
  ['#operators', '#ops-root table'],
  ['#companies', '#co-root table'],
  ['#daily', '#daily-root .dr-hero'],
  ['#daily?v=full', '#daily-root .dr-sec'],
  ['#daily?st=tx', '#daily-root .dr-hero'],
  ['#daily?st=ok', '#daily-root .dr-hero', async (page) => (await page.locator('#daily-root path.dr-county').count()) === 77 ? null : 'the Oklahoma map should have 77 counties'],
  ['#daily?st=ok&v=full', '#daily-root .dr-sec'],
  ['#daily?st=nm', '#daily-root .dr-hero', async (page) => (await page.locator('#daily-root path.dr-county').count()) === 33 ? null : 'the New Mexico map should have 33 counties'],
  ['#daily?st=nm&v=full', '#daily-root .dr-sec'],
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
    // New Mexico has a Daily report now; it is answered with an empty index here, so the page's handling of a state with none stays exercised (block 5 has the real one)
    await page.route('**/data/daily-nm/index.json', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"generated":"x","keep":92,"days":[]}' }));
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
      await page.waitForSelector('#ops-root tbody tr', { timeout: 25000 });
      check((await page.locator('#statebar').isVisible()) && /st=ok/.test(await hash()) && !(await page.locator('#ops-root tbody tr .st-tag').first().isVisible()), 'the Operators page follows the choice: Oklahoma alone has no State column, st=ok stays in the address');
      const lede = await page.locator('#ops-lede').innerText();
      check(/ranked by new-drill permits in the last 12 months/.test(lede) && /Data runs through [A-Z][a-z]{2} \d+, 2026\./.test(lede) && !/New Mexico/.test(lede), 'and its lede says what is ranked and how far Oklahoma\'s own data runs');
      check(!(await page.locator('#ops-root label.check', { hasText: 'Top producers' }).isVisible()) && !(await page.locator('#ops-root label.check', { hasText: 'New P-5' }).isVisible()), 'the filters only Texas\'s records can answer are hidden without Texas');
      const heads = async () => (await page.locator('#ops-root thead th:not([hidden])').allInnerTexts()).map((t) => t.trim());
      const okHeads = await heads();
      check(okHeads.includes('Location') && !okHeads.includes('Spud (12 mo)') && !okHeads.includes('District') && !okHeads.includes('State'), 'Oklahoma alone: no column of blanks (no Spud, no District, no State)');
      await page.click('#statebar button[data-id="NM"]');
      await page.waitForFunction(() => /Aug 31/.test(document.querySelector('#ops-lede').textContent), null, { timeout: 25000 });
      const nmHeads = await heads();
      check(!nmHeads.includes('Location') && !nmHeads.includes('Permits (12 mo)') && !nmHeads.includes('Spud (12 mo)') && nmHeads.includes('Top county'), 'New Mexico alone: no Location (no addresses), no permit counts (it counts spuds), no Spud column; its own end date in the lede');
      await page.click('#statebar button[data-id="all"]');
      await page.waitForFunction(() => { const t = [...document.querySelectorAll('#ops-root tbody tr .st-tag')].map((e) => e.textContent); return t.includes('NM') && t.includes('OK') && t.includes('TX'); }, null, { timeout: 25000 });
      check(await page.locator('#ops-root tbody tr .st-tag').first().isVisible(), 'all states: one ranking with the State column showing, the busiest operators of every state in the first rows');
      const lede3 = await page.locator('#ops-lede').innerText();
      check(/wells spudded in New Mexico/.test(lede3) && /\(New Mexico\)/.test(lede3) && /\(Oklahoma\)/.test(lede3) && (await page.locator('#ops-root label.check', { hasText: 'Top producers' }).isVisible()), 'and its lede names each state\'s own end date and measure; the Texas filters are back');
      await page.click('#statebar button[data-id="NM"]');
      await page.click('.nav a[href="#companies"]');
      await page.waitForSelector('#co-note:not([hidden])', { timeout: 25000 });
      check(!(await page.locator('#co-root').isVisible()) && /Texas Comptroller/.test(await page.locator('#co-note').innerText()), 'Companies with no Texas in the choice: no table, and a note on why');
      await page.click('.nav a[href="#about"]');
      await page.waitForSelector('#view-about h1', { timeout: 25000 });
      check(!(await page.locator('#statebar').isVisible()) && /st=nm/.test(await hash()), 'a view that does not follow the choice (Sources) hides the bar and keeps it in the address');
      await page.click('.nav a[href="#overview"]');
      await page.waitForSelector('#hot-bars li', { timeout: 25000 });
      await page.click('#statebar button[data-id="OK"]');
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

  // 4. the Map follows the states bar: shapes, dots, legend and panels for the states shown, deep links with a state's county and operator keys
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const legend = async () => (await page.locator('.lg-title').innerText()).replace(/\s+/g, ' ');
    const panel = async () => (await page.locator('.map-panel .panel-body').innerText()).replace(/\s+/g, ' ');
    const counties = () => page.evaluate(() => window.__map.S.G.counties.length);
    const mapFor = async (id, text) => { // choose a state on the bar and wait for the legend to name it
      await page.click('#statebar button[data-id="' + id + '"]');
      await page.waitForFunction((src) => { const t = document.querySelector('.lg-title'); return !!t && new RegExp(src).test(t.textContent); }, text.source, { timeout: 25000 });
    };
    try {
      await page.goto(base + '?debug#map', { waitUntil: 'load' });
      await page.waitForSelector('.lg-states', { timeout: 25000 });
      check((await counties()) === 254 + 77 + 33 && (await page.locator('.lg-st').count()) === 3 && /Permits and spuds/.test(await legend()), 'all states: 364 counties on one map, the legend names the three dot colors and says permits and spuds');
      check(/Texas, Oklahoma and New Mexico/.test(await page.locator('#map-lede').innerText()), 'and the page says which states it covers');
      await page.click('#map-root button:has-text("Table view")');
      await page.waitForSelector('.map-table tbody tr', { timeout: 10000 });
      const th = await page.locator('.map-table thead th').allInnerTexts();
      check((await page.locator('.map-table tbody tr').count()) === 364 && th[1].trim() === 'State', 'the table twin lists every county of the states shown, with a State column');
      await page.click('#map-root button:has-text("Map view")');
      await mapFor('OK', /^New-drill permits, /);
      check(/across Oklahoma\./.test(await page.locator('#map-lede').innerText()), 'choosing a state on the Map changes the page\'s own sentence too');
      check((await counties()) === 77 && /st=ok/.test(await page.evaluate(() => location.hash)) && (await page.locator('.lchip-body', { hasText: /^Permits$/ }).count()) === 1, 'Oklahoma alone: 77 counties, st=ok in the address, the dots are permits');
      await mapFor('NM', /^Wells spudded, /);
      check((await counties()) === 33 && (await page.locator('.lchip-body', { hasText: 'Wells spudded' }).count()) === 1 && (await page.locator('.map-actions').innerText()).includes('New Mexico drill'), 'New Mexico alone: 33 counties, the dots and the replay say wells spudded');
      // a dot of New Mexico: its tooltip and its page say spudded, in its county
      const pt = await page.evaluate(() => {
        const { engine, S } = window.__map; const P = S.P;
        for (let i = 0; i < P.n; i++) { const [sx, sy] = engine.screenOf(P.x[i], P.y[i]); if (sx > 120 && sx < 700 && sy > 60 && sy < 500) return { sx, sy }; }
        return null;
      });
      const box = await page.locator('.map-canvas').boundingBox();
      await page.mouse.move(box.x + pt.sx - 25, box.y + pt.sy - 25); await page.mouse.move(box.x + pt.sx, box.y + pt.sy);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      check(/Spudded/.test(await page.locator('.tip').innerText()), 'hovering a New Mexico dot says Spudded, not Issued');
      await page.mouse.click(box.x + pt.sx, box.y + pt.sy);
      await page.waitForFunction(() => /Well spudded/.test(document.querySelector('.map-panel .panel-body').textContent), null, { timeout: 5000 });
      check(/FIPS 35\d{3}/.test(await panel()) && /Texas figures: not available for New Mexico/.test(await panel()), 'its page and its county say so, and name what New Mexico has no figure for');
      await mapFor('all', /^Permits and spuds, /);
      check(/Texas, Oklahoma and New Mexico/.test(await page.locator('#map-lede').innerText()) && (await page.locator('.lg-st').count()) === 3, 'back to All: the sentence and the legend name the three states again');
      await mapFor('TX', /^New-drill permits, /);
      check((await counties()) === 254 && (await page.locator('.lg-states').count()) === 0 && (await page.locator('.lchip').count()) === 5, 'Texas alone: its 254 counties and all five layers, no state legend');
      await page.goto(base + '?debug#map?st=ok&county=OK:039', { waitUntil: 'load' });
      await page.waitForFunction(() => /Custer County/.test(document.querySelector('.map-panel .panel-body')?.textContent || ''), null, { timeout: 25000 });
      check(/Custer County FIPS 40039/.test(await panel()) && /county=OK:039/.test(await page.evaluate(() => location.hash)), 'an Oklahoma county opens by its key (county=OK:039), in a readable address');
      await page.goto(base + '?debug#map?st=nm&op=NM:7377', { waitUntil: 'load' });
      await page.waitForFunction(() => /New Mexico operator 7377/.test(document.querySelector('.map-panel .panel-body')?.textContent || ''), null, { timeout: 25000 });
      check(/Wells spudded, 12 mo/.test(await panel()), 'a New Mexico operator opens by its key (op=NM:7377) and counts wells spudded');
      await page.goto(base + '?debug#map?st=tx&county=OK:039', { waitUntil: 'load' });
      await page.waitForSelector('.lg-title', { timeout: 25000 });
      check(/Texas at a glance/.test(await panel()), 'a county of a state that is not shown is ignored, not an error');
    } catch (e) {
      check(false, 'the Map and the states bar: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the Map and the states bar load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 5. New Mexico's Daily report: on its own (permits and what goes with them, nothing it does not publish) and with the other two
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const eyebrow = () => page.locator('#daily-root .dr-hero .eyebrow').textContent();
    try {
      await page.goto(base + '#daily?st=nm', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      const kpis = await page.locator('#daily-root .dr-kpis .dr-kpi').allInnerTexts();
      check(/Oil Conservation Division report/i.test(await eyebrow()) && kpis.length === 3 && /Horizontal wells/.test(kpis[1]) && !(await page.locator('#statebar-note').innerText()).trim(), 'New Mexico alone: its own report (three cards, the horizontal share), and the bar has nothing to say about it');
      check((await page.locator('#daily-root .dr-rb.nm').count()) > 30 && (await page.locator('#daily-root .dr-bar.nm').count()) > 0, 'its ribbon and pace chart are drawn in its color, with its 33 counties on the map');
      check(/fill in later/.test(await page.locator('#daily-root .dr-story').innerText()), 'the story says the layer is entered late, so the newest days run low');
      await page.goto(base + '#daily?st=nm&v=full', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-sec', { timeout: 25000 });
      const full = await page.locator('#daily-root').innerText();
      check(/Kinds of well/.test(full) && /Direction/.test(full) && /OCD districts/.test(full) && !/Amended that day/.test(full) && !/Days to approval/.test(full) && !/Median planned depth/.test(full), 'the verbose report shows kinds of well, direction and districts, and no tile for what the Division does not publish');
      await page.click('#statebar button[data-id="all"]');
      await page.waitForFunction(() => /Texas, Oklahoma and New Mexico report/i.test(document.querySelector('#daily-root .dr-hero .eyebrow').textContent), null, { timeout: 25000 });
      check((await page.locator('#daily-root .dr-dot.nm').count()) > 0 && (await page.locator('#daily-root .dr-mapwrap path.dr-county').count()) === 364 && /New Mexico: 1 of 1/.test(await page.locator('.dr-pills').innerText()), 'all three together: one map of 364 counties, New Mexico\'s files read named in the pills, its color in the legends');
    } catch (e) {
      check(false, 'the New Mexico Daily report: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the New Mexico Daily report loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  await browser.close();
  server.close();
  console.log('\n' + (failures ? 'FAILED ' + failures : 'all passed'));
  process.exit(failures ? 1 : 0);
})();
