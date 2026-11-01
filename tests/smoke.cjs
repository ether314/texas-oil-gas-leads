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
  ['#map?st=nm', '#map-root canvas', async (page) => (/^Wells spudded, [A-Z][a-z]{2} 1, \d{4} to [A-Z][a-z]{2} \d+, \d{4}$/.test(await page.locator('.lg-title').innerText()) ? null : 'the New Mexico map should say wells spudded, over 12 calendar months from the first of a month')],
  ['#overview?st=fo', '#kpis > *', async (page) => (/^BSEE spud reports through/.test(await page.locator('#hero-eyebrow').textContent()) ? null : 'the offshore\'s Overview should name BSEE')],
  ['#map?st=fo', '#map-root canvas', async (page) => (/^Wells spudded, [A-Z][a-z]{2} 1, \d{4} to [A-Z][a-z]{2} \d+, \d{4}$/.test(await page.locator('.lg-title').innerText()) ? null : 'the offshore map should say wells spudded, over 12 calendar months from the first of a month')],
  ['#operators?st=fo', '#ops-root table'],
  ['#daily?st=fo', '#daily-root .dr-hero'],
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
  ['#images', '#images-root .img-stage', async (page) => ((await page.locator('#images-root .img-stage').count()) === 3 ? null : 'the images view should show the three stages of a well')],
  ['#images?d=2026-10-30', '#images-root .img-pack', async (page) => ((await page.locator('#images-root .img-pack').count()) === 3 ? null : 'a day should show its three packs')],
  ['#national', '#national-root button.nat-tile', async (page) => ((await page.locator('#national-root button.nat-tile').count()) === 35 ? null : 'the national tile map should have one button for each of the 35 jurisdictions')],
  ['#fields', '#fields-root button.fx-c', async (page) => ((await page.locator('#fields-root tr[data-m]').count()) === 48 ? null : 'the matrix should have a row for each of the 48 metrics')],
  ['#fields?s=BL&g=when', '#fields-root .nat-panel h3', async (page) => (/Federal onshore/.test(await page.locator('#fields-root .nat-panel h3').first().innerText()) && (await page.locator('#fields-root tr[data-m]').count()) === 6 ? null : 'an address naming an agency and a group should open its panel and filter the rows')],
  ['#national?s=NM&m=spuds', '#national-root .nat-panel h3', async (page) => (/New Mexico/.test(await page.locator('#national-root .nat-panel h3').first().innerText()) ? null : 'an address naming New Mexico should open its panel')],
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
      check((await page.locator('#statebar .seg-dot').count()) === 5 && (await page.locator('#statebar .seg-dot.st-nm').count()) === 1 && (await page.locator('#statebar .seg-dot.st-fo').count()) === 1, 'each state wears its color in the bar (All the four together)');
      check(/^Permits and spuds through Oct \d+ \(Texas\), Oct \d+ \(Oklahoma\), Aug \d+ \(New Mexico\) and Aug \d+ \(Offshore\), \d{4}$/.test(await page.locator('#hero-eyebrow').textContent()), 'the hero names each state\'s last day once, with the year once, and says permits and spuds where the states count both');
      check(/\(Texas\).*\(Oklahoma\).*\(New Mexico\).*\(Offshore\)/.test(await eyebrow()) && (await page.locator('#hot-bars .bars-h').count()) === 4 && (await page.locator('#hot-h').textContent()) === 'Hot counties and areas', 'all states: the hero names each state\'s last day, the lists have a heading per state and the card says counties and areas');
      check(/New Mexico and the federal offshore count wells spudded, not permits \(their regulators publish no approval dates by well\)/.test(await page.locator('#hero-note').textContent()), 'and the note under the map says which states count wells spudded, once');
      check(/In the federal offshore a well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted\./.test(await page.locator('#hero-note').textContent()), 'and that a sidetrack offshore is not counted as a new well');
      await page.click('#statebar button[data-id="OK"]');
      await waitEyebrow(/Corporation Commission approvals through/);
      check(/st=ok/.test(await hash()) && (await pressed()) === 'Oklahoma', 'choosing Oklahoma puts st=ok in the address');
      check((await page.locator('#kpis').innerText()).includes('Active wells') && !(await page.locator('#seg-chart').isVisible()), 'Oklahoma alone: its own figures, and the cards only Texas can fill step aside');
      await page.click('#statebar button[data-id="NM"]');
      await waitEyebrow(/Oil Conservation Division spud reports through/);
      check(/st=nm/.test(await hash()) && (await page.locator('#kpis').innerText()).includes('Wells spudded, last 12 months'), 'New Mexico alone: its wells spudded, its own date, st=nm in the address');
      await page.click('#statebar button[data-id="FO"]');
      await waitEyebrow(/^BSEE spud reports through/);
      check(/st=fo/.test(await hash()) && (await page.locator('#kpis').innerText()).includes('Wells spudded, last 12 months') && !(await page.locator('#seg-chart').isVisible()) && (await page.locator('#hot-h').textContent()) === 'Hot areas', 'the federal offshore alone: its wells spudded, its own date, st=fo in the address, "Hot areas", and the cards only Texas can fill step aside');
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
      check((await counties()) === 254 + 77 + 33 + 63 && (await page.locator('.lg-st').count()) === 4 && /Permits and spuds/.test(await legend()), 'all states: 427 counties and areas on one map, the legend names the four dot colors and says permits and spuds');
      check(/Texas, Oklahoma, New Mexico and the federal offshore/.test(await page.locator('#map-lede').innerText()) && /^County and area activity/.test(await page.locator('#map-lede').innerText()), 'and the page says which states it covers, and that it has counties and areas');
      await page.click('#map-root button:has-text("Table view")');
      await page.waitForSelector('.map-table tbody tr', { timeout: 10000 });
      const th = await page.locator('.map-table thead th').allInnerTexts();
      check((await page.locator('.map-table tbody tr').count()) === 427 && th[0].trim() === 'County or area' && th[1].trim() === 'State', 'the table twin lists every county and area of the states shown, with a State column');
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
      // the federal offshore: protraction areas where the others have counties, wells spudded, no FIPS code, nothing of Texas's records
      await mapFor('FO', /^Wells spudded, /);
      check((await counties()) === 63 && /st=fo/.test(await page.evaluate(() => location.hash)) && (await page.locator('.map-actions').innerText()).includes('the Gulf drill') && /^Area activity/.test(await page.locator('#map-lede').innerText())
        && (await page.locator('.lchip-body', { hasText: 'Wells spudded' }).count()) === 1 && /top areas/i.test(await panel()), 'the federal offshore alone: 63 areas, the dots and the replay say wells spudded, "Watch the Gulf drill", "Top areas"');
      // the sentences that explain the map say what the offshore counts: spuds, well dots, areas, and what a sidetrack is
      check(/^Area activity and spud locations across the federal offshore\. Shading and counts use every spud; dots show the ones with a recorded location\./.test(await page.locator('#map-lede').innerText()), 'the offshore\'s map lede says spud locations and areas, not permit locations');
      const notes = (await page.locator('.map-note').allInnerTexts()).join(' ').replace(/\s+/g, ' ');
      check(/Area shading, counts and trends use every spud\./.test(notes) && /A well counts once, on its first borehole; sidetracks and bypasses/.test(notes) && !/County shading/.test(notes), 'and its notes say "Area shading ... every spud" and what a sidetrack is: ' + notes.slice(0, 140));
      await page.goto(base + '?debug#map?st=fo&metric=chg', { waitUntil: 'load' });
      await page.waitForFunction(() => /top areas: change/i.test(document.querySelector('.map-panel .panel-body')?.innerText || ''), null, { timeout: 25000 });
      const chgPanel = await panel();
      check(/top areas: change vs prior 12 mo \(5\+ spuds\)/i.test(chgPanel) && (await page.locator('.map-panel .mini-row').count()) >= 3 && /an area, a well dot/.test(chgPanel) && !/permit dot|20\+ permits/i.test(chgPanel),
        'the offshore\'s change list ranks the areas with 5 or more spuds (not the 20 permits no area has), is not empty, and says "a well dot": ' + chgPanel.slice(0, 200));
      await page.goto(base + '?debug#map?st=fo&county=FO:049', { waitUntil: 'load' });
      await page.waitForFunction(() => /Sabine Pass/.test(document.querySelector('.map-panel .panel-body')?.textContent || ''), null, { timeout: 25000 });
      const idle = await panel();
      check(/No wells were spudded in this area in the last 24 months/.test(idle) && !/published no location/.test(idle), 'an area with no wells says none were spudded, and does not blame the agency for a location: ' + idle.slice(-160));
      await page.goto(base + '?debug#map?st=fo&county=FO:024', { waitUntil: 'load' });
      await page.waitForFunction(() => /Green Canyon area/.test(document.querySelector('.map-panel .panel-body')?.textContent || ''), null, { timeout: 25000 });
      check(/Green Canyon area Protraction area/.test(await panel()) && !/FIPS/.test(await panel()) && /Zoom to area/.test(await panel()) && /not available for the federal offshore/.test(await panel()), 'an offshore area opens by its key (county=FO:024) as "Green Canyon area", with no FIPS code, and names what the offshore has no figure for: ' + (await panel()).slice(0, 120));
      await page.goto(base + '?debug#map', { waitUntil: 'load' });
      await mapFor('all', /^Permits and spuds, /);
      check(/Texas, Oklahoma, New Mexico and the federal offshore/.test(await page.locator('#map-lede').innerText()) && (await page.locator('.lg-st').count()) === 4, 'back to All: the sentence and the legend name the four states again');
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
      check(/Oil Conservation Division report/i.test(await eyebrow()) && kpis.length === 4 && /Horizontal wells/.test(kpis[1]) && /Active wells in the state/.test(kpis[2]) && !(await page.locator('#statebar-note').innerText()).trim(), 'New Mexico alone: its own report (four cards: permits, the horizontal share, the active wells, the files), and the bar has nothing to say about it');
      check(/still filling in/.test(kpis[0]) && !/vs the 20-day average/.test(kpis[0]), 'its newest day is not set against an average of days that have filled in: it says it is still filling in');
      check((await page.locator('#daily-root .dr-rb.nm').count()) > 30 && (await page.locator('#daily-root .dr-bar.nm').count()) > 0, 'its ribbon and pace chart are drawn in its color, with its 33 counties on the map');
      check(/fill in later/.test(await page.locator('#daily-root .dr-story').innerText()), 'the story says the layer is entered late, so the newest days run low');
      await page.goto(base + '#daily?st=nm&v=full', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-sec', { timeout: 25000 });
      const full = await page.locator('#daily-root').innerText();
      check(/Kinds of well/.test(full) && /Direction/.test(full) && /OCD districts/.test(full) && /Every well in the state/.test(full) && /Inventory · New Mexico/i.test(full) && !/Amended that day/.test(full) && !/Days to approval/.test(full) && !/Median planned depth/.test(full), 'the verbose report shows kinds of well, direction and districts, and no tile for what the Division does not publish, then its well inventory');
      await page.click('#statebar button[data-id="all"]');
      await page.waitForFunction(() => /Texas, Oklahoma and New Mexico report/i.test(document.querySelector('#daily-root .dr-hero .eyebrow').textContent), null, { timeout: 25000 });
      check((await page.locator('#daily-root .dr-dot.nm').count()) > 0 && (await page.locator('#daily-root .dr-mapwrap path.dr-county').count()) === 364 && /New Mexico: 2 of 2/.test(await page.locator('.dr-pills').innerText()), 'all three together: one map of 364 counties, New Mexico\'s files read named in the pills, its color in the legends');
      check(/New Mexico is still filling in/.test(await page.locator('#daily-root .dr-kpis .dr-kpi').first().innerText()), 'and the combined comparison says New Mexico\'s newest days are still filling in');
      // and the Companies table's Segment cell is a table cell (its class once collided with the segmented control's, which made each one a pill)
      await page.goto(base + '#companies?st=tx', { waitUntil: 'load' });
      await page.waitForSelector('#co-root td.segcell', { timeout: 25000 });
      check(await page.evaluate(() => getComputedStyle(document.querySelector('#co-root td.segcell')).display === 'table-cell'), 'the Companies table\'s Segment column is plain table cells, not the segmented control\'s pills');
      await page.goto(base + '#daily?st=nm&v=full', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-sec', { timeout: 25000 });
      check(!/Completion data/.test(await page.locator('#daily-root').innerText()), 'New Mexico alone has no completions card (the Division publishes none)');
    } catch (e) {
      check(false, 'the New Mexico Daily report: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the New Mexico Daily report loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 6. the tabs scroll sideways on a phone: a fade at an edge with more behind it (data-more), none where they all fit
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const more = () => page.evaluate(() => document.querySelector('.nav').dataset.more);
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nav a[aria-current="page"]', { timeout: 25000 });
      await page.waitForFunction(() => document.querySelector('.nav').dataset.more === 'end', null, { timeout: 10000 });
      check((await more()) === 'end', 'on a phone the tabs fade at the right edge while Sources is out of sight');
      await page.goto(base + '#about', { waitUntil: 'load' });
      await page.waitForFunction(() => document.querySelector('.nav').dataset.more === 'start', null, { timeout: 10000 });
      check((await more()) === 'start', 'and at the left edge once the current tab has been brought into view');
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.waitForFunction(() => document.querySelector('.nav').dataset.more === 'none', null, { timeout: 10000 });
      check((await more()) === 'none', 'and not at all where the tabs all fit');
      // the browser's bar takes the page's color in the theme chosen here (one tag once a theme is set; both themes' colors are the --page tokens)
      const bar = () => page.evaluate(() => [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => m.content).join(' '));
      await page.click('[data-theme-set="dark"]');
      const dark = await bar();
      await page.click('[data-theme-set="light"]');
      const light = await bar();
      const tokens = await page.evaluate(() => { const probe = document.createElement('i'); probe.style.cssText = 'color: var(--page); position: absolute'; document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; });
      check(dark === '#0d0d0d' && light === '#f9f9f7' && tokens === 'rgb(249, 249, 247)', 'the browser bar follows the theme: dark ' + dark + ', light ' + light + ' (the light page color is ' + tokens + ')');
    } catch (e) {
      check(false, 'the tabs on a phone: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 7. the Daily report on a phone with the three states: one pill each, cards that hold their text and sparkline, no card alone in half a row
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-kpis .dr-kpi', { timeout: 25000 });
      const pills = await page.locator('#daily-root .dr-pills .dr-pill').count();
      check(pills === 3 && (await page.locator('#daily-root .dr-pills .dr-pill.quiet').count()) === 0, 'the three states are three pills (the time each was read is inside it), not six: ' + pills);
      const out = await page.evaluate(() => [...document.querySelectorAll('#daily-root .dr-kpi')].flatMap((c) => {
        const r = c.getBoundingClientRect();
        return [...c.querySelectorAll('.dr-kpi-note, .dr-kpi-extra, .dr-kpi-spark svg')].filter((k) => k.getBoundingClientRect().right > r.right - 17).map((k) => (k.className.baseVal !== undefined ? k.className.baseVal : k.className) + ' of ' + c.querySelector('.dr-kpi-top').textContent.trim().slice(0, 24));
      }));
      check(!out.length, 'every card on a phone holds its note and its sparkline (none runs past the card\'s padding)' + (out.length ? ': ' + out.join(', ') : ''));
      const alone = await page.evaluate(() => {
        const cs = [...document.querySelectorAll('#daily-root .dr-kpis > .dr-kpi')];
        const full = cs[0].getBoundingClientRect().width;
        const top = (c) => c.getBoundingClientRect().top;
        return { cards: cs.length, alone: cs.filter((c) => c.getBoundingClientRect().width < full * 0.6 && !cs.some((o) => o !== c && Math.abs(top(o) - top(c)) < 2)).length };
      });
      check(alone.cards >= 3 && alone.alone === 0, 'no half-width card is left alone in its row (' + alone.cards + ' cards)');
    } catch (e) {
      check(false, 'the Daily report on a phone: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 8. the Operators CSV for all three states: a column that says which state, figures a state does not publish left blank (never zero), and a fall stays a number
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#operators', { waitUntil: 'load' });
      await page.waitForFunction(() => { const b = [...document.querySelectorAll('#ops-root button')].find((x) => /Download CSV/.test(x.textContent)); return b && !b.disabled; }, null, { timeout: 25000 });
      const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('#ops-root button', { hasText: 'Download CSV' }).click()]);
      const text = fs.readFileSync(await dl.path(), 'utf8').replace(/^\uFEFF/, '');
      // a small reader for quoted fields (a name can hold a comma)
      const table = [];
      { let row = [], cell = '', q = false;
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (q) { if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') q = false; else cell += ch; }
          else if (ch === '"') q = true;
          else if (ch === ',') { row.push(cell); cell = ''; }
          else if (ch === '\n') { row.push(cell.replace(/\r$/, '')); table.push(row); row = []; cell = ''; }
          else cell += ch;
        }
        if (cell || row.length) { row.push(cell); table.push(row); } }
      const head = table[0];
      const col = (name) => head.indexOf(name);
      const states = new Set(table.slice(1).map((r) => r[0]));
      check(head[0] === 'data_state' && ['TX', 'OK', 'NM'].every((x) => states.has(x)), 'the CSV says which state each row is, and holds all three: ' + [...states].sort().join(','));
      // New Mexico publishes no all-kinds permit count: the cell is empty, not 0
      const nm = table.slice(1).filter((r) => r[0] === 'NM');
      check(nm.length > 0 && nm.every((r) => r.length === head.length && r[col('all_permits_12m')] === '' && r[col('all_permits_24m')] === ''), 'a figure New Mexico does not publish is blank in its rows, not zero (' + nm.length + ' rows)');
      check(!/(^|,)'-?\d/.test(text), 'no number was turned into text by the spreadsheet guard (a fall such as -14.4 has no apostrophe)');
    } catch (e) {
      check(false, 'the Operators CSV: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 9. the archive's days render no "NaN", "undefined", "null" or "Infinity": the newest and oldest day, every tenth, and each day on which Texas's queue was empty
  // (a share of an empty queue was NaN%); read from the committed index files, so the days follow the archive as it rolls
  {
    const read = (dir) => { const j = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', dir, 'index.json'), 'utf8')); return j.days || j; };
    const tx = read('daily');
    const every = [...new Set([].concat(read('daily'), read('daily-ok'), read('daily-nm')).map((r) => r.d))].sort();
    const picks = new Set([every[0], every[every.length - 1], ...every.filter((d, i) => i % 10 === 5), ...tx.filter((r) => r.q === 0).map((r) => r.d)]);
    const emptyDays = tx.filter((r) => r.q === 0).length;
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const bad = [];
    let seen = 0;
    try {
      for (const d of picks) {
        for (const q of ['', '&st=tx']) {
          await page.goto(base + '#daily?d=' + d + '&v=full' + q, { waitUntil: 'load' });
          await page.waitForSelector('#daily-root .dr-sec', { timeout: 25000 });
          await page.waitForTimeout(150);
          const text = await page.locator('#daily-root').innerText();
          seen++;
          const m = text.match(/\b(NaN|undefined|null|Infinity)\b|\[object/);
          if (m) bad.push(d + q + ': "' + text.slice(Math.max(0, m.index - 30), m.index + 30).replace(/\s+/g, ' ') + '"');
        }
      }
    } catch (e) {
      check(false, 'the archive walk: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(seen >= 8 && !bad.length, seen + ' archive pages (' + emptyDays + ' with an empty Texas queue) show no NaN, undefined, null or Infinity' + (bad.length ? ': ' + bad.slice(0, 4).join(' | ') : ''));
    await ctx.close();
  }

  // 10. a map metric no county has a figure for (New Mexico publishes no depth) says so: no scale of "NaN ft", no empty list; and no metric of any state shows a NaN in its legend or panel
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#map?st=tx,ok,nm', { waitUntil: 'load' });
      await page.waitForSelector('#map-root canvas', { timeout: 25000 });
      const metrics = await page.$$eval('#map-metric option', (os) => os.map((o) => o.value)); // every metric the menu has (all states)
      const bad = [];
      for (const st of ['nm', 'ok', 'tx,ok,nm']) {
        for (const id of metrics) {
          await page.goto(base + '#map?metric=' + id + '&st=' + st, { waitUntil: 'load' });
          await page.waitForSelector('#map-root canvas', { timeout: 25000 });
          await page.waitForTimeout(120);
          const text = await page.evaluate(() => ((document.querySelector('.map-legend') || {}).innerText || '') + ' ' + ((document.querySelector('.psec') || {}).innerText || ''));
          if (/NaN|undefined|Infinity/.test(text)) bad.push(st + '/' + id);
        }
      }
      check(metrics.length >= 10 && !bad.length, 'every map metric under New Mexico, Oklahoma and all three states has a legend and a panel with no NaN (' + metrics.length + ' metrics)' + (bad.length ? ': ' + bad.join(', ') : ''));
      await page.goto(base + '#map?metric=depth&st=nm', { waitUntil: 'load' });
      await page.waitForSelector('#map-root canvas', { timeout: 25000 });
      await page.waitForTimeout(200);
      const lg = await page.locator('.map-legend').innerText();
      const panel = await page.locator('.psec').first().innerText();
      check(/No reported depth/.test(lg) && !(await page.locator('.map-legend .lg-ramp').count()) && /No county has a figure/.test(panel), 'New Mexico\'s depth map says no depth is reported: no scale, and the list says why it is empty');
    } catch (e) {
      check(false, 'the map metrics: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 11. the Daily report says so when its newest report is two or more days behind today's date (Central): the nightly capture may have failed; not otherwise
  {
    const days = [].concat(...['daily', 'daily-ok', 'daily-nm'].map((dir) => { const j = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', dir, 'index.json'), 'utf8')); return (j.days || j).map((r) => r.d); })).sort();
    const newest = days[days.length - 1];
    const at = (offsetDays, hour) => new Date(Date.parse(newest + 'T00:00:00Z') + offsetDays * 86400000 + hour * 3600000);
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.clock.setFixedTime(at(0, 18)); // noon Central on the newest report's day
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      check((await page.locator('#daily-root .dr-stale').count()) === 0, 'on the newest report\'s own day the Daily report has no warning');
      await page.clock.setFixedTime(at(5, 18)); // five days later
      await page.goto(base + '#daily?d=' + newest + '&st=tx', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      const note = (await page.locator('#daily-root .dr-stale').count()) ? await page.locator('#daily-root .dr-stale').innerText() : '';
      check(/newest report is [4-6] days old/.test(note) && /may have failed/.test(note), 'five days later it says the newest report is old and the capture may have failed: ' + note.slice(0, 80));
      // an older day is not "the newest report", so it carries no warning
      const older = days[Math.max(0, days.length - 10)];
      await page.goto(base + '#daily?d=' + older, { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' }); // a change of hash alone is not a new page: without this the check could run before the view has redrawn (it flaked once)
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      check((await page.locator('#daily-root .dr-stale').count()) === 0, 'and a day that is not the newest carries none');
    } catch (e) {
      check(false, 'the stale-report notice: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 12. printing (or saving as a PDF) the Daily report: light even when the page is dark, none of the screen-only parts, cards kept whole
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', colorScheme: 'dark' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-kpis .dr-kpi', { timeout: 25000 });
      await page.click('[data-theme-set="dark"]');
      const screen = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      await page.emulateMedia({ media: 'print' });
      const printed = await page.evaluate(() => {
        const gone = (sel) => [...document.querySelectorAll(sel)].every((e) => getComputedStyle(e).display === 'none');
        return { bg: getComputedStyle(document.body).backgroundColor, ink: getComputedStyle(document.body).color, header: gone('header.top'), bar: gone('#statebar'), controls: gone('#daily-root .dr-controls'), buttons: gone('#daily-root .btn'), keep: getComputedStyle(document.querySelector('#daily-root .dr-kpi')).breakInside };
      });
      check(screen !== 'rgb(255, 255, 255)' && printed.bg === 'rgb(255, 255, 255)' && printed.ink !== 'rgb(255, 255, 255)', 'a dark page prints light: the screen is ' + screen + ', the paper ' + printed.bg + ' with ' + printed.ink + ' ink');
      check(printed.header && printed.bar && printed.controls && printed.buttons && printed.keep === 'avoid', 'the header, the states bar, the controls and the buttons stay off the paper, and a card is not split across pages: ' + JSON.stringify(printed));
    } catch (e) {
      check(false, 'printing the Daily report: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 13. a dropped connection is tried once more (a phone between towers): the Map's first request for its permit file fails and it still draws; a missing file is not retried
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    let permitAsks = 0; let missingAsks = 0;
    await ctx.route('**/data/permits.json', (route) => { permitAsks++; if (permitAsks === 1) route.abort(); else route.continue(); });
    await ctx.route('**/data/daily-nm/1999-01-01.json', (route) => { missingAsks++; route.fulfill({ status: 404, body: 'not found' }); });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#map', { waitUntil: 'load' });
      await page.waitForSelector('#map-root canvas', { timeout: 25000 });
      check(permitAsks === 2, 'the Map draws although its first request for the permit file was dropped (it asked ' + permitAsks + ' times)');
      const miss = await page.evaluate(async () => { const m = await import('./js/util.js'); const t0 = performance.now(); const r = await m.loadOpt('daily-nm/1999-01-01'); return { r, ms: Math.round(performance.now() - t0) }; });
      check(miss.r === null && missingAsks === 1 && miss.ms < 600, 'a missing file is asked for once and answered at once, not retried: ' + missingAsks + ' ask, ' + miss.ms + ' ms');
    } catch (e) {
      check(false, 'the retry of a dropped request: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 14. what a state does not publish is never shown as a 0, and a figure that adds states says which: found by an independent review of the pages
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const hover = (st) => page.evaluate(async (st) => {
      const el = [...document.querySelectorAll('#daily-root .dr-mapwrap path.dr-county')].find((x) => x.dataset.f.startsWith(st + ':'));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      el.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
      await new Promise((done) => setTimeout(done, 100));
      return document.querySelector('#tip').innerText.replace(/\s+/g, ' ');
    }, st);
    const layer = async (name) => { await page.locator('#daily-root .dr-mapwrap').locator('xpath=ancestor::*[contains(@class,"card")][1]').getByRole('button', { name: new RegExp('^' + name) }).first().click(); await page.waitForTimeout(250); };
    try {
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-mapwrap path.dr-county', { timeout: 25000 });
      await layer('Completions');
      const nm = await hover('NM'); const tx = await hover('TX');
      check(/Not available/.test(nm || '') && !/ 0 /.test(nm || '') && /completions/.test(tx || ''), 'on the Daily map\'s Completions layer a New Mexico county says "Not available" (it publishes none), a Texas county gives its figure: "' + nm + '" / "' + tx + '"');
      await layer('Waiting');
      const ok = await hover('OK');
      check(/Not available/.test(ok || ''), 'and on the queue layer an Oklahoma county says so too: "' + ok + '"');
      await page.goto(base + '#daily?v=full', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-sec', { timeout: 25000 });
      const row = await page.evaluate(() => { const tr = [...document.querySelectorAll('#daily-root table tr')].find((r) => /^Other filings/.test(r.children[0].textContent.trim())); return tr ? [...tr.children].map((c) => c.textContent.trim()) : null; });
      const head = await page.evaluate(() => { const t = [...document.querySelectorAll('#daily-root table')].find((x) => /Other filings/.test(x.textContent)); return t ? [...t.querySelectorAll('thead th')].map((c) => c.textContent.trim()) : []; });
      const nmCol = head.indexOf('New Mexico');
      check(!row || nmCol < 0 || row[nmCol] === '—', 'New Mexico has no "other filings" (its permits are all new wells), so its cell is a dash, not 0: ' + JSON.stringify(row));
      const amended = await page.evaluate(() => { const t = [...document.querySelectorAll('#daily-root .dr-tile')].find((x) => /^Amended/.test(x.innerText.trim())); return t ? t.innerText.replace(/\s+/g, ' ') : null; });
      check(!amended || /only/.test(amended), 'the amended-permits figure (Texas and Oklahoma count them, New Mexico does not) names the states it adds: ' + amended);
      // an address that names two of the three states: nothing is highlighted in the bar, and a note says which are shown
      await page.goto(base + '#overview?st=tx,ok', { waitUntil: 'load' });
      await page.waitForSelector('#statebar-seg button', { timeout: 25000 });
      await page.waitForTimeout(400);
      const pair = await page.evaluate(() => ({ on: [...document.querySelectorAll('#statebar-seg button')].filter((b) => b.getAttribute('aria-pressed') === 'true').length, note: document.querySelector('#statebar-note').textContent }));
      check(pair.on === 0 && /Showing Texas and Oklahoma/.test(pair.note), 'two states named in the address: no segment of the bar is lit and the note says "' + pair.note.slice(0, 60) + '"');
      // wording that names New Mexico's different measure, and the Active wells chip naming each inventory
      await page.goto(base + '#overview?st=ok,nm', { waitUntil: 'load' });
      await page.waitForSelector('#kpis .kpi-chip', { timeout: 25000 });
      await page.waitForTimeout(900);
      const chips = await page.evaluate(() => [...document.querySelectorAll('#kpis .kpi-chip-note')].map((n) => n.textContent).join(' || '));
      check(/wells spudded in New Mexico/.test(chips) && /first spud in New Mexico/.test(chips) && /well inventories of Oklahoma and New Mexico/.test(chips), 'the Overview\'s chips for Oklahoma and New Mexico name its different measure and both inventories: ' + chips.slice(0, 160));
      // a Map operator panel never shows more dots than the operator has
      await page.goto(base + '#map?op=NM:7377&st=nm', { waitUntil: 'load' });
      await page.waitForSelector('.psec-op', { timeout: 25000 });
      const shown = await page.locator('.psec-op').innerText();
      const m = shown.match(/Showing ([\d,]+)(?: of ([\d,]+))?/);
      check(m && (!m[2] || +m[1].replace(/,/g, '') <= +m[2].replace(/,/g, '')), 'a Map operator panel never says it shows more than the operator has: "' + (m ? m[0] : shown.slice(0, 60)) + '"');
    } catch (e) {
      check(false, 'what a state does not publish: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 15. a button's words are one piece: a label split into two flex items ("Share" and "this view") gets the icon's gap between them, which reads as a double space
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    try {
      for (const v of ['#map', '#operators', '#companies', '#daily', '#map?st=nm']) {
        await page.goto(base + v, { waitUntil: 'load' });
        await page.waitForFunction(() => [...document.querySelectorAll('.btn')].some((b) => b.offsetParent), null, { timeout: 25000 }); // the first .btn in the page may sit in a view that is hidden
        await page.waitForTimeout(500);
        const split = await page.evaluate(() => [...document.querySelectorAll('.btn')].filter((b) => b.offsetParent).map((b) => ({ text: b.textContent.trim().replace(/\s+/g, ' '),
          pieces: [...b.children].filter((c) => c.tagName.toLowerCase() !== 'svg').length })).filter((b) => b.pieces > 1));
        check(split.length === 0, 'every button on ' + v + ' draws its words as one piece' + (split.length ? ': ' + split.map((b) => '"' + b.text + '"').join(', ') : ''));
      }
    } catch (e) {
      check(false, 'button labels: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 16. a file the report could not read is said to be unread: "no pending set recorded" and "no completion filings" are claims about the commission, not about a failed download
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      const txDays = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'daily', 'index.json'), 'utf8')).days.map((r) => r.d).sort();
      const day = txDays[txDays.length - 1];
      const real = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'daily', day + '.json'), 'utf8'));
      const broken = JSON.parse(JSON.stringify(real));
      for (const d of broken.datasets) if (d.id === 'pending' || d.id === 'completions') { d.error = 'could not be read'; d.file = null; d.dataDay = null; d.state = 'error'; }
      delete broken.pending; delete broken.completions; broken.status = 'partial';
      const notes = () => page.evaluate(() => [...document.querySelectorAll('#daily-root .dr-kpi')].map((k) => k.querySelector('.dr-kpi-top').textContent.trim() + ' | ' + ((k.querySelector('.dr-kpi-note') || {}).textContent || '')).join(' || '));
      await page.goto(base + '#daily?d=' + day + '&st=tx', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-kpi', { timeout: 25000 });
      const control = await notes();
      check(!/could not be read/.test(control), 'a day on which every file was read says nothing about unread files: ' + control.slice(0, 90));
      await page.route('**/data/daily/' + day + '.json', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(broken) }));
      await page.goto(base + '#daily?d=' + day + '&st=tx', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-kpi', { timeout: 25000 });
      const tx = await notes();
      check(/Waiting for approval \| The pending files could not be read/.test(tx) && !/No pending set recorded/.test(tx), 'Texas with its pending files unread says so, not "no pending set recorded": ' + tx.slice(0, 160));
      check(/Completions[^|]* \| Texas: the completion files could not be read/.test(tx) && !/No completion filings/.test(tx), 'and so for its completion files');
      await page.click('#statebar-seg button:has-text("All")'); // the bar keeps the last choice, so an address with no state is still Texas alone here
      await page.waitForFunction(() => document.querySelector('#daily-root .dr-kpi-top') && [...document.querySelectorAll('#daily-root .dr-kpi-top')].some((k) => /^Completions$/.test(k.textContent.trim())), null, { timeout: 25000 });
      const all = await notes();
      check(/Completions \|[^|]*Texas could not be read/.test(all), 'with all three states the completions card says which state could not be read: ' + all.slice(0, 200));
      // Oklahoma's transfers file, the same way
      const okDays = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'daily-ok', 'index.json'), 'utf8')).days.map((r) => r.d).sort();
      const okDay = okDays[okDays.length - 1];
      const okBroken = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'daily-ok', okDay + '.json'), 'utf8'));
      for (const d of okBroken.datasets) if (d.id === 'transfers') { d.error = 'could not be read'; d.file = null; d.dataDay = null; d.state = 'error'; }
      delete okBroken.transfers; okBroken.status = 'partial';
      await page.route('**/data/daily-ok/' + okDay + '.json', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(okBroken) }));
      await page.goto(base + '#daily?d=' + okDay + '&st=ok', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-kpi', { timeout: 25000 });
      const okNotes = await notes();
      check(/Wells changing operator \| The transfer file could not be read/.test(okNotes) && !/No transfers on file/.test(okNotes), 'Oklahoma with its transfers file unread says so, not "no transfers on file": ' + okNotes.slice(0, 200));
    } catch (e) {
      check(false, 'unread files: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 17. the federal offshore: the bar's five choices fit a 360 px phone (TX, OK, NM, Offshore) and keep their full names for a screen reader; the pages that
  // follow the bar say areas where it has areas and give its reason for having no Daily report; its operators are named by the same rule
  {
    const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const bar = () => page.evaluate(() => { const seg = document.querySelector('#statebar .seg'); const bs = [...seg.querySelectorAll('button')]; return { room: seg.scrollWidth - seg.clientWidth, shown: bs.map((b) => b.innerText.trim()), names: bs.map((b) => b.getAttribute('aria-label') || b.innerText.trim()) }; });
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('#statebar .seg button', { timeout: 25000 });
      const phone = await bar();
      check(phone.room <= 1 && phone.shown.join() === 'All,TX,OK,NM,Offshore', 'on a 360 px phone all five choices of the states bar are in view with no sideways scrolling (' + phone.shown.join(' ') + ', ' + phone.room + ' px to spare)');
      check(phone.names.join() === 'All,Texas (TX),Oklahoma (OK),New Mexico (NM),Federal offshore', 'each keeps its full name for a screen reader, which holds the visible label: ' + phone.names.join(' | '));
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.waitForTimeout(300);
      const wide = await bar();
      check(wide.shown.join() === 'All,Texas,Oklahoma,New Mexico,Offshore', 'on a wide screen the full names show again: ' + wide.shown.join(' '));
      // no width clips the bar, in whatever font the machine has: the bar measures itself and shows the full names while they fit, then the short ones, then tighter buttons
      const clipped = []; const fits = {};
      for (const w of [320, 330, 340, 390, 440, 441, 450, 460, 462, 463, 470, 520, 768, 1280]) {
        await page.setViewportSize({ width: w, height: 800 });
        await page.waitForTimeout(250);
        const b = await bar();
        fits[w] = await page.evaluate(() => document.querySelector('#statebar .seg').dataset.fit);
        if (b.room > 1) clipped.push(w + ' px (' + b.room + ' px)');
      }
      check(!clipped.length, 'the states bar is never clipped, at any width from 320 to 1280 px' + (clipped.length ? ': ' + clipped.join(', ') : ''));
      check(fits[1280] === 'full' && fits[320] !== 'full' && fits[390] !== 'full', 'the full names show on a wide screen and give way to the short ones on a phone (data-fit by width: ' + JSON.stringify(fits) + ')');
      // the Daily report: no report for the offshore, and it says why (its file is weekly)
      await page.goto(base + '#daily?st=fo', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      await page.waitForTimeout(300);
      const note = await page.locator('#statebar-note').innerText();
      check(/^The federal offshore has no Daily report \(BSEE’s file is weekly\); it shows Texas, Oklahoma and New Mexico instead\./.test(note), 'the Daily report for the offshore alone says it has none and why, and shows the three that have one: ' + note);
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dr-hero', { timeout: 25000 });
      await page.click('#statebar button[data-id="all"]');
      await page.waitForTimeout(400);
      check(/^The federal offshore has no Daily report \(BSEE’s file is weekly\); it shows Texas, Oklahoma and New Mexico\.$/.test(await page.locator('#statebar-note').innerText()), 'with all four chosen the Daily report shows the three and names the one with none');
      // Companies are the Texas Comptroller's: with the offshore alone the page says so in a sentence
      await page.goto(base + '#companies?st=fo', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#co-note', { state: 'visible', timeout: 25000 });
      check(/nothing to list for the federal offshore:/.test(await page.locator('#co-note').innerText()), 'Companies with the offshore alone says there is nothing to list for the federal offshore');
      // Operators: sixteen named corporations, a Top area column, no State column, no address, no permit counts
      await page.goto(base + '#operators?st=fo&band=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#ops-root table tbody tr', { timeout: 25000 });
      const heads = (await page.locator('#ops-root thead th:visible').allInnerTexts()).map((t) => t.trim());
      const rows = await page.locator('#ops-root tbody tr').count();
      check(rows === 16 && heads.includes('Top area') && !heads.includes('State') && !heads.includes('Top county') && !heads.includes('Location') && !heads.includes('Avg depth (ft)'), 'Operators with the offshore alone: 16 rows, "Top area", no State, Location or depth column: ' + rows + ' rows, ' + heads.join(' | '));
      check(/wells spudded/.test(await page.locator('#ops-what').innerText()) && /Aug \d+, \d{4}/.test(await page.locator('#ops-through').innerText()), 'and its lede says what is ranked and where the offshore\'s own data ends');
      check(/ A well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted\.$/.test(await page.locator('#ops-what').innerText()), 'and what a sidetrack is (an operator that sidetracks old wells ranks with none)');
      // what a band and the last-date column mean is said in the row's own measure: spuds, never permits
      const chipTitles = await page.locator('#ops-root tbody .chip').evaluateAll((els) => els.map((e) => e.title));
      check(chipTitles.length >= 16 && chipTitles.every((t) => /wells spudded/.test(t) && !/permit/i.test(t)) && chipTitles.some((t) => /^No wells spudded in the last 12 months, but some in the 12 before$/.test(t)) && heads.includes('Last spud') && !heads.includes('Last permit'),
        'the offshore\'s bands are described in wells spudded (band C had some in the 12 before) and the date column is "Last spud": ' + [...new Set(chipTitles)].join(' | ') + ' · ' + heads.filter((h) => /^Last/.test(h)).join());
      // the bands of a mixed list say permits for Texas rows and spuds for the offshore's
      await page.goto(base + '#operators?st=tx,fo&band=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#ops-root table tbody tr', { timeout: 25000 });
      const mixedHeads = (await page.locator('#ops-root thead th:visible').allInnerTexts()).map((t) => t.trim());
      const mixedTitles = new Set(await page.locator('#ops-root tbody .chip').evaluateAll((els) => els.map((e) => e.title)));
      check(mixedHeads.includes('Last permit or spud') && mixedTitles.has('10 or more new-well permits in the last 12 months') && mixedTitles.has('10 or more wells spudded in the last 12 months'), 'a list of Texas and the offshore describes each row\'s band in its own measure and calls the date "Last permit or spud": ' + mixedHeads.filter((h) => /^Last/.test(h)).join());
      // the Production note keeps a space between two states' sentences (they ran together when Texas was not shown) and names the offshore as a sentence does
      await page.goto(base + '#overview?st=nm,fo', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#pg-production', { timeout: 25000 });
      await page.click('#pg-production');
      const foot = (await page.locator('#pulse-root .pulse-foot').allInnerTexts()).join(' ');
      check(/here\. The federal offshore’s line is the EIA’s monthly estimate/.test(foot) && !/here\.[A-Z]/.test(foot) && /The federal offshore has no area or operator production file here/.test(foot), 'the Production note keeps a space between two states\' sentences and names the offshore as a sentence does: ' + foot.slice(-260));
      check(/^Wells spudded through Aug \d+ \(New Mexico\) and Aug \d+ \(Offshore\), \d{4}$/.test(await page.locator('#hero-eyebrow').textContent()), 'two states that both count spuds say "Wells spudded through ...", not "Permits": ' + (await page.locator('#hero-eyebrow').textContent()));
      // a state named inside a sentence is "the federal offshore"; a state with no well inventory at all is "not counted", not "none yet"
      await page.goto(base + '#overview?st=ok,fo', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#kpis .kpi-chip', { timeout: 25000 });
      await page.waitForTimeout(900);
      const foChips = await page.evaluate(() => [...document.querySelectorAll('#kpis .kpi-chip-note')].map((n) => n.textContent).join(' || '));
      check(/not counted for the federal offshore/.test(foChips) && !/none yet for/.test(foChips) && /first spud in the federal offshore/.test(foChips) && !/[a-z,] Federal offshore/.test(foChips), 'the chips name the offshore as a sentence does, and say its inventory is not counted: ' + foChips.slice(0, 260));
      await page.goto(base + '#overview?st=fo', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#ins-list li.insight', { timeout: 25000 });
      const foIns = await page.evaluate(() => [...document.querySelectorAll('#ins-list li.insight')].map((n) => n.textContent).join(' || '));
      check(/The federal offshore produced [\d,]+ thousand barrels of crude oil in/.test(foIns) && !/[a-z,] Federal offshore/.test(foIns), 'an insight that starts with the offshore capitalizes it, and none names it "Federal offshore" mid-sentence: ' + foIns.slice(0, 200));
      check(/^A well counts once|The federal offshore counts wells spudded, not permits \(its regulator publishes no approval dates by well\), and ends two months back because spud dates arrive late\. A well counts once, on its first borehole;/.test(await page.locator('#hero-note').textContent()), 'with the offshore alone the note under the map says what a sidetrack is without repeating its name');
      await page.goto(base + '#overview?st=tx,fo', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#statebar-note', { timeout: 25000 });
      await page.waitForTimeout(300);
      check(/^Showing Texas and the federal offshore\./.test(await page.locator('#statebar-note').innerText()), 'the bar\'s note says "Showing Texas and the federal offshore"');
      // the Sources page's offshore figures are filled from its files (the date the data ends, the year's wells, the operators, the EIA's month), none left empty
      await page.goto(base + '#about', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForFunction(() => [...document.querySelectorAll('[data-fill^="fo"]')].length === 6 && [...document.querySelectorAll('[data-fill^="fo"]')].every((n) => n.textContent.trim()), null, { timeout: 25000 });
      const fills = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('[data-fill^="fo"]')].map((n) => [n.dataset.fill, n.textContent.trim()])));
      check(/^[A-Z][a-z]{2} \d{4}$/.test(fills.foSince) && /^[A-Z][a-z]{2} \d+, \d{4}$/.test(fills.foThrough) && /^\d+$/.test(fills.foYear) && /^\d+$/.test(fills.foOps) && /^[A-Z][a-z]{2} \d{4}$/.test(fills.foEiaThrough) && /^about \d+ million barrels in [A-Z][a-z]{2} \d{4}$/.test(fills.foEiaNow),
        'the Sources page fills the offshore\'s date, wells, operators and EIA month from its files: ' + JSON.stringify(fills));
    } catch (e) {
      check(false, 'the federal offshore: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the federal offshore pages load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // the National report: the tile map, its panel, the count toggle and the ranking, with no NaN anywhere
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#national', { waitUntil: 'load' });
      await page.waitForSelector('#national-root button.nat-tile', { timeout: 25000 });
      check(/Texas/.test(await page.locator('#national-root .nat-panel h3').first().innerText()), 'the national panel opens on the biggest state counting permits (Texas)');
      await page.click('#national-root button.nat-tile[data-id="OK"]');
      check(/Oklahoma/.test(await page.locator('#national-root .nat-panel h3').first().innerText()) && /s=OK/.test(await page.evaluate(() => location.hash)), 'a tile opens its panel and puts the state in the address');
      check((await page.locator('#national-root button.nat-tile[aria-pressed="true"]').count()) === 1, 'exactly one tile is pressed');
      await page.click('#national-root button.nat-tile[data-id="NM"]');
      check(/not permits|spud/i.test(await page.locator('#national-root .nat-panel').innerText()), 'New Mexico\'s panel says it counts wells spudded');
      // a producing state that has no data yet says so, and never shows a figure
      const gapId = await page.evaluate(() => { const t = document.querySelector('#national-root button.nat-tile.t0'); return t ? t.dataset.id : null; });
      if (gapId) {
        await page.click('#national-root button.nat-tile[data-id="' + gapId + '"]');
        const txt = await page.locator('#national-root .nat-panel').innerText();
        check(/Not read yet/.test(txt) && /never as zero|not available/i.test(txt), 'a state with no data says "Not read yet" and that it is not available, never zero');
      }
      await page.click('#natm-spuds');
      await page.waitForTimeout(300);
      const keys = await page.locator('#national-root .nat-chart-keys').innerText();
      check(/New Mexico/.test(keys) && !/Texas/.test(keys), 'the Wells spudded chart stacks only the states that count spuds: ' + keys.replace(/\s+/g, ' '));
      check(/m=spuds/.test(await page.evaluate(() => location.hash)), 'the count toggle is kept in the address');
      const rows = await page.locator('#national-root .nat-row').count();
      check(rows >= 4, 'the ranking has a row for every state with data (' + rows + ')');
      await page.click('#national-root .nat-row >> nth=0');
      check((await page.locator('#national-root button.nat-tile[aria-pressed="true"]').count()) === 1, 'a ranking row selects its tile');
      const text = await page.locator('#view-national').innerText();
      check(!/NaN|undefined|Infinity|\bnull\b/.test(text), 'the national view shows no NaN, undefined, null or Infinity');
      await page.goto(base + '#national?s=ZZ', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#national-root button.nat-tile', { timeout: 25000 });
      check((await page.locator('#national-root .nat-panel h3').count()) >= 1, 'an unknown state in the address falls back to a panel');
    } catch (e) {
      check(false, 'the national report: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the national report loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // the Texas images view: the chart's days, the day list, a day's three packs, no NaN
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#images', { waitUntil: 'load' });
      await page.waitForSelector('#images-root .img-pack', { timeout: 25000 });
      check((await page.locator('#images-root .nat-hit').count()) >= 60, 'the day-by-day chart has a column for each report day');
      const options = await page.locator('#images-root select.img-day option').count();
      check(options >= 60, 'the day list holds the days that had a pack (' + options + ')');
      const first = await page.locator('#images-root select.img-day option').nth(options - 1).getAttribute('value');
      await page.selectOption('#images-root select.img-day', first);
      await page.waitForFunction((d) => location.hash.includes('d=' + d), first, { timeout: 10000 });
      check(/\d+(\.\d)? MB|GB/.test(await page.locator('#images-root .img-pack').first().innerText()) || /No pack listed/.test(await page.locator('#images-root .img-pack').first().innerText()), 'choosing a day shows its packs and puts the day in the address');
      const imgs = await page.evaluate(() => [...document.querySelectorAll('#images-root img')].map((i) => ({ ok: i.complete && i.naturalWidth > 0, src: i.getAttribute('src') })));
      check(imgs.every((i) => i.ok) && imgs.every((i) => /^data\/daily\/img\//.test(i.src)), 'any contact sheet on the page loaded, from the site itself (' + imgs.length + ')');
      const text = await page.locator('#view-images').innerText();
      check(!/NaN|undefined|Infinity|\bnull\b/.test(text), 'the images view shows no NaN, undefined, null or Infinity');
      check(/Not counted by kind yet|documents/.test(text), 'the stages say what is counted, or that it is not yet');
    } catch (e) {
      check(false, 'the Texas images view: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the Texas images view loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // the permit-data matrix: a cell, an agency and a metric each open their panel; the group tabs filter; no NaN
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#fields', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root button.fx-c', { timeout: 25000 });
      check((await page.locator('#fields-root button.fx-h').count()) >= 1, 'the matrix has a column for each agency researched');
      await page.click('#fields-root button.fx-c >> nth=0');
      check(/:/.test(await page.locator('#fields-root .nat-panel h3').first().innerText()) && (await page.locator('#fields-root button.fx-c[aria-pressed="true"]').count()) === 1, 'a cell opens its panel (agency: metric) and is the one pressed');
      check(/s=/.test(await page.evaluate(() => location.hash)) && /m=/.test(await page.evaluate(() => location.hash)), 'the cell is kept in the address');
      await page.click('#fields-root button.fx-h >> nth=0');
      check(/Grade [ABCD]/.test(await page.locator('#fields-root .nat-panel').innerText()), 'an agency\'s code opens its panel with its grade');
      await page.click('#fields-root button.fx-m >> nth=0');
      check(/as data/.test(await page.locator('#fields-root .nat-panel').innerText()), 'a metric opens the list of agencies');
      await page.click('#fxg-when');
      await page.waitForTimeout(200);
      check((await page.locator('#fields-root tr[data-m]').count()) === 6 && /g=when/.test(await page.evaluate(() => location.hash)), 'the When group shows its six metrics and is kept in the address');
      const text = await page.locator('#view-fields').innerText();
      check(!/NaN|undefined|Infinity|\bnull\b/.test(text), 'the matrix shows no NaN, undefined, null or Infinity');
      check(/Not verified/.test(text), 'the page says what it could not verify');
    } catch (e) {
      check(false, 'the permit-data matrix: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the permit-data matrix loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  await browser.close();
  server.close();
  console.log('\n' + (failures ? 'FAILED ' + failures : 'all passed'));
  process.exit(failures ? 1 : 0);
})();
