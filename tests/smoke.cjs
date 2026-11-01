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
const previewStub = require('./preview-stub.cjs');

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

// [hash, a selector that appears once the view has drawn, an optional extra check]
const VIEWS = [
  ['#overview', '#kpis > *'],
  ['#map', '#map-root canvas'],
  ['#map?st=tx', '#map-root canvas', async (page) => (/^New-drill permits, /.test(await page.locator('.lg-title').innerText()) ? null : 'Texas alone should keep its own legend')],
  ['#map?st=ok', '#map-root canvas', async (page) => (/^New-drill permits, /.test(await page.locator('.lg-title').innerText()) && (await page.locator('.lg-states').count()) === 0 ? null : 'the Oklahoma map should say permits and need no state legend')],
  ['#map?st=nm', '#map-root canvas', async (page) => (/^Wells spudded, [A-Z][a-z]{2} 1, \d{4} to [A-Z][a-z]{2} \d+, \d{4}$/.test(await page.locator('.lg-title').innerText()) ? null : 'the New Mexico map should say wells spudded, over 12 calendar months from the first of a month')],
  ['#overview?s=TX', '.nw-grid .nat-panel h3', async (page) => (/^Texas$/.test(await page.locator('.nw-grid .nat-panel h3').first().innerText()) && /s=TX/.test(await page.evaluate(() => location.hash)) ? null : 'an address naming Texas should zoom the explorer to it')],
  ['#map?st=fo', '#map-root canvas', async (page) => (/^Wells spudded, [A-Z][a-z]{2} 1, \d{4} to [A-Z][a-z]{2} \d+, \d{4}$/.test(await page.locator('.lg-title').innerText()) ? null : 'the offshore map should say wells spudded, over 12 calendar months from the first of a month')],
  ['#operators?st=fo', '#ops-root table'],
  ['#operators', '#ops-root table'],
  ['#daily', '#daily-root .dd-nav', async (page) => ((await page.locator('#daily-root .dd-nav').count()) === 1 && !(await page.locator('#statebar').isVisible()) ? null : 'the Daily report should be national: a day control and no states bar')],
  ['#daily?d=2026-02-02&s=TX', '#daily-root .dd-nav', async (page) => (/Monday, Feb 2, 2026/.test(await page.locator('#daily-root .dd-date').innerText()) && /in Texas/.test(await page.locator('#dd-table-h').innerText()) ? null : 'an address naming a day and Texas should open on them')],
  ['#oklahoma', '#daily-root .dd-nav', async (page) => (/s=OK/.test(await page.evaluate(() => location.hash)) ? null : 'an old #oklahoma link should open the Daily report on Oklahoma\'s wells')],
  ['#companies', '#co-root table'],
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

  // 3. the states shown: one choice in a bar above the views that follow it (the Map, Operators and Companies), kept in the address
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const pressed = () => page.locator('#statebar button[aria-pressed="true"]').innerText();
    const hash = () => page.evaluate(() => location.hash);
    try {
      // the Overview and the Daily report are national and have no states bar; the Map, Operators and Companies follow it
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      check(!(await page.locator('#statebar').isVisible()), 'the Overview is the same for every state: it has no states bar');
      await page.goto(base + '#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-nav', { timeout: 25000 });
      check(!(await page.locator('#statebar').isVisible()), 'the Daily report is national too: no states bar');
      await page.goto(base + '#map', { waitUntil: 'load' });
      await page.waitForSelector('#map-root canvas', { timeout: 25000 });
      check((await pressed()) === 'All' && (await page.locator('#statebar').isVisible()), 'the states bar is on the Map and starts on All');
      check((await page.locator('#statebar .seg-dot').count()) === 5 && (await page.locator('#statebar .seg-dot.st-nm').count()) === 1 && (await page.locator('#statebar .seg-dot.st-fo').count()) === 1, 'each state wears its color in the bar (All the four together)');
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
      check(!(await page.locator('#statebar').isVisible()) && !/st=/.test(await hash()), 'a view that does not follow the choice (Sources) hides the bar and has no state in its address');
      await page.click('.nav a[href="#operators"]');
      await page.waitForSelector('#ops-root tbody tr', { timeout: 25000 });
      check((await pressed()) === 'New Mexico' && /st=nm/.test(await hash()), 'and the choice is still there when you come back to a view that follows it');
      await page.goto(base + '#map?st=tx', { waitUntil: 'load' });
      await page.waitForFunction(() => /^New-drill permits, /.test((document.querySelector('.lg-title') || {}).textContent || ''), null, { timeout: 25000 });
      check((await pressed()) === 'Texas', 'an address with st=tx opens the Map on Texas alone, and the bar says so');
      await page.click('#statebar button[data-id="all"]');
      await page.waitForFunction(() => /^Permits and spuds, /.test((document.querySelector('.lg-title') || {}).textContent || ''), null, { timeout: 25000 });
      check(!/st=/.test(await hash()) && (await pressed()) === 'All', 'choosing All on the Map shows the states together and leaves st out of the address');
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
      // the current tab is always whole in the tabs' window, and the tabs do not move for a tab that is already in view (the first ones stay put while they fit)
      const seen = [];
      for (const v of ['#overview', '#national', '#fields', '#map', '#operators', '#companies', '#daily', '#images', '#about']) {
        await page.evaluate((h) => { location.hash = h; }, v);
        await page.waitForTimeout(250);
        seen.push(await page.evaluate((h) => {
          const nav = document.querySelector('.nav'); const a = nav.querySelector('a[aria-current="page"]');
          if (!a) return h + ': no current tab';
          const left = a.offsetLeft; const right = left + a.offsetWidth;
          const whole = left >= nav.scrollLeft - 1 && right <= nav.scrollLeft + nav.clientWidth + 1;
          const needless = nav.scrollLeft > 1 && right <= nav.clientWidth - 28; // it was in view without moving the tabs
          return whole && !needless ? '' : h + (whole ? ': the tabs moved for a tab already in view' : ': the current tab is cut off');
        }, v));
      }
      check(seen.every((s) => !s), 'on a phone the current tab is whole in the tabs\' window for every view, and the tabs move only for a tab that is out of it' + (seen.filter(Boolean).length ? ': ' + seen.filter(Boolean).join(' | ') : ''));
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

  // 14. an address that names two states, and a Map operator panel that never shows more dots than the operator has (found by an independent review of the pages)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      // an address that names two of the three states: nothing is highlighted in the bar, and a note says which are shown
      await page.goto(base + '#map?st=tx,ok', { waitUntil: 'load' });
      await page.waitForSelector('#statebar-seg button', { timeout: 25000 });
      await page.waitForTimeout(400);
      const pair = await page.evaluate(() => ({ on: [...document.querySelectorAll('#statebar-seg button')].filter((b) => b.getAttribute('aria-pressed') === 'true').length, note: document.querySelector('#statebar-note').textContent }));
      check(pair.on === 0 && /Showing Texas and Oklahoma/.test(pair.note), 'two states named in the address: no segment of the bar is lit and the note says "' + pair.note.slice(0, 60) + '"');
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

  // 16b. the header, at any width and in any font: its three parts are all on the page (the theme toggle is not pushed off it), nothing makes the page scroll sideways, the tagline shows
  // only when it fits whole, and every tab is reachable (the row holds them on one line, or scrolls them). The header measures itself and is one row, one row without the tagline, or two rows
  // (found by looking at 761 to 1000 px after two tabs were added: the tabs and the toggle ran off the page)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.top-row[data-fit]', { timeout: 25000 });
      const bad = []; const modes = {};
      for (const w of [360, 390, 640, 761, 820, 900, 1000, 1100, 1180, 1200, 1280, 1440, 1920]) {
        await page.setViewportSize({ width: w, height: 800 });
        await page.waitForTimeout(250);
        const r = await page.evaluate(() => {
          const row = document.querySelector('.top-row'); const nav = document.querySelector('.nav'); const theme = document.querySelector('.theme').getBoundingClientRect();
          const sub = document.querySelector('.brand-sub'); const links = [...nav.querySelectorAll('a')];
          const oneLine = new Set(links.map((a) => a.offsetTop)).size === 1;
          const clipped = nav.scrollWidth > nav.clientWidth + 1;
          return {
            fit: row.dataset.fit, doc: document.documentElement.scrollWidth > document.documentElement.clientWidth, toggle: theme.left >= 0 && theme.right <= window.innerWidth,
            subCut: sub.offsetParent !== null && sub.scrollWidth > sub.clientWidth + 1, oneLine, unreachable: clipped && !['auto', 'scroll'].includes(getComputedStyle(nav).overflowX), tabs: links.length,
          };
        });
        modes[w] = r.fit;
        const why = [r.doc ? 'the page scrolls sideways' : '', r.toggle ? '' : 'the theme toggle is off the page', r.subCut ? 'the tagline is cut' : '', r.oneLine ? '' : 'the tabs wrap', r.unreachable ? 'a tab is cut off and cannot be scrolled to' : ''].filter(Boolean);
        if (why.length) bad.push(w + ' px: ' + why.join(', '));
      }
      check(!bad.length, 'the header at 13 widths from 360 to 1920 px keeps its toggle on the page, its tabs on one line and reachable, and never cuts its tagline' + (bad.length ? ': ' + bad.join(' | ') : ''));
      // the width at which the header gets its one row depends on the font (the tabs need 788 px in one and more in another), so only what holds in every font is asserted: a phone
      // stacks, every mode is a known one, and a wider page never has less room than a narrower one (stack, compact, row, full in that order)
      const rank = { stack: 0, compact: 1, row: 2, full: 3 }; const order = Object.keys(modes).map(Number).sort((a, b) => a - b);
      check(modes[360] === 'stack' && modes[390] === 'stack' && order.every((w) => w in modes && modes[w] in rank) && order.every((w, i) => !i || rank[modes[w]] >= rank[modes[order[i - 1]]]),
        'a phone gets the tabs on a row of their own, and a wider page never gets a smaller layout than a narrower one (header layout by width: ' + JSON.stringify(modes) + ')');
    } catch (e) {
      check(false, 'the header: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, 'the header sweep loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 17. the federal offshore: the bar's five choices fit a 360 px phone (TX, OK, NM, Offshore) and keep their full names for a screen reader; the pages that
  // follow the bar say areas where it has areas its operators are named by the same rule
  {
    const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const bar = () => page.evaluate(() => { const seg = document.querySelector('#statebar .seg'); const bs = [...seg.querySelectorAll('button')]; return { room: seg.scrollWidth - seg.clientWidth, shown: bs.map((b) => b.innerText.trim()), names: bs.map((b) => b.getAttribute('aria-label') || b.innerText.trim()) }; });
    try {
      await page.goto(base + '#map', { waitUntil: 'load' });
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
      await page.goto(base + '#map?st=tx,fo', { waitUntil: 'load' });
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
      const eiaMonths = await page.evaluate(() => ['okEiaThrough', 'nmEiaThrough'].map((k) => (document.querySelector('[data-fill="' + k + '"]') || {}).textContent || ''));
      check(eiaMonths.every((t) => /^[A-Z][a-z]{2} \d{4}$/.test(t.trim())), 'and the month the EIA series for Oklahoma and New Mexico run to, from their files: ' + eiaMonths.join(', '));
      const nmEnd = await page.evaluate(() => (document.querySelector('[data-fill="nmThrough"]') || {}).textContent || '');
      check(/^[A-Z][a-z]{2} \d+, \d{4}$/.test(nmEnd.trim()) && !/%/.test(await page.evaluate(() => document.querySelector('#view-about').innerText.match(/depth for [^.]*\./)?.[0] || '')), 'and New Mexico\'s end date, which the weekly refresh moves, from its file (and no percentage of wells with a depth that would go stale): "' + nmEnd + '"');
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
      // a state read with none in the 12 months is drawn apart from one not read yet (dashed), and a count of another kind (applications filed, wells drilled) is dotted, ranked on its own and added to nothing
      const natDoc = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'national.json'), 'utf8'));
      const drawn = await page.evaluate(() => { const ids = (q) => [...document.querySelectorAll('#national-root button.nat-tile' + q)].map((t) => t.dataset.id).sort().join(); return { gap: ids('.t0'), zero: ids('.tz'), own: ids('.is-own') }; });
      const wantZero = natDoc.states.filter((x) => x.p12 === 0).map((x) => x.id).sort().join();
      const wantOwn = natDoc.states.filter((x) => x.measure === 'applications' || x.measure === 'drilled').map((x) => x.id).sort().join();
      check(wantZero.length > 0 && drawn.zero === wantZero && drawn.gap === natDoc.gaps.map((g) => g.id).sort().join() && drawn.own === wantOwn && wantOwn === 'OR,VA', 'tiles: a state read with none is outlined (' + drawn.zero + '), apart from the ones not read yet (' + drawn.gap.split(',').length + ' dashed), and Oregon and Virginia are dotted: ' + JSON.stringify(drawn));
      const tile = (label) => page.evaluate((l) => { const t = [...document.querySelectorAll('#national-root .nat-kpis .dr-tile')].find((x) => x.querySelector('dt').textContent.startsWith(l)); return t ? t.textContent : ''; }, label);
      const another = await tile('Counted another way'); const spudTile = await tile('Wells spudded');
      check(/Oregon \(applications filed\)/.test(another) && /Virginia \(wells drilled\)/.test(another) && /^Wells spudded/.test(spudTile) && !/(?<!West )Virginia|Oregon/.test(spudTile) && !/(?<!West )Virginia|Oregon/.test(await tile('Permits approved')), 'the top figures name the two counted another way, and neither is in the permits or the wells spudded figure: ' + JSON.stringify({ another: another.slice(0, 160), spud: spudTile.slice(0, 160) }));
      const heads = await page.locator('#national-root .nat-rh').allInnerTexts();
      check(heads.length === 4 && /^Applications filed .*added to nothing$/.test(heads[2]) && /^Wells drilled .*added to nothing$/.test(heads[3]), 'the ranking has a section for each of the four counts, the last two marked as added to nothing: ' + JSON.stringify(heads));
      await page.click('#national-root button.nat-tile[data-id="AZ"]');
      const az = await page.locator('#national-root .nat-panel').innerText();
      check(/None recorded/.test(az) && !/\b0 wells spudded/.test(az), 'Arizona (no spud dated in 24 months) says "None recorded", not a count of 0 wells spudded: ' + az.replace(/\s+/g, ' ').slice(0, 200));
      const azTile = await page.evaluate(() => { const t = document.querySelector('#national-root button.nat-tile[data-id="AZ"]'); return { n: t.querySelector('.nat-n').textContent, label: t.getAttribute('aria-label') }; });
      check(azTile.n === '–' && /none recorded in the last 24 months/.test(azTile.label), 'and its tile shows a dash and says so to a screen reader, not a 0: ' + JSON.stringify(azTile));
      await page.click('#national-root button.nat-tile[data-id="VA"]');
      check(/Wells drilled/.test(await page.locator('#national-root .nat-panel .badge').innerText()), 'Virginia\'s panel is badged Wells drilled');
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
      // every tile's panel, one after the other (a state with no operators printed the word null once: native append writes it for a null child)
      const ids = await page.evaluate(() => [...document.querySelectorAll('#national-root button.nat-tile')].map((b) => b.dataset.id));
      const dirty = [];
      for (const id of ids) {
        await page.click('#national-root button.nat-tile[data-id="' + id + '"]');
        const t = await page.locator('#national-root .nat-panel').innerText();
        if (/NaN|undefined|Infinity|\bnull\b/.test(t) || t.trim().length < 20) dirty.push(id);
      }
      check(ids.length === 35 && !dirty.length, 'the panel of every one of the ' + ids.length + ' tiles reads clean' + (dirty.length ? ' (not: ' + dirty.join(', ') + ')' : ''));
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
      // one pack, one size: the chart's table and the day panel are the same number for the same day (the index stores bytes / 2^20 and the panel once divided by 10^6: 39.3 against 41)
      const newest = await page.locator('#images-root select.img-day option').first().getAttribute('value');
      await page.selectOption('#images-root select.img-day', newest);
      await page.waitForFunction((d) => location.hash.includes('d=' + d), newest, { timeout: 10000 });
      await page.waitForTimeout(600);
      const pairs = await page.evaluate(() => {
        const label = document.querySelector('#images-root select.img-day').selectedOptions[0].textContent.split(' (')[0];
        const row = [...document.querySelectorAll('#images-root .nat-details tbody tr')].find((r) => r.querySelector('th').textContent === label);
        const cells = [...row.querySelectorAll('td')].map((c) => c.textContent);
        return [...document.querySelectorAll('#images-root .img-pack')].map((p, i) => [cells[i], (p.querySelector('h3 .badge') || {}).textContent || null]).filter((x) => x[1]);
      });
      check(pairs.length >= 1 && pairs.every(([cell, badge]) => /MB$/.test(badge) && Math.abs(parseFloat(badge) - parseFloat(cell)) <= 0.6), 'the day panel and the chart table give a pack the same size (' + JSON.stringify(pairs) + ')');
      // an address naming a day the archive does not hold shows the newest day, says so, and the address says the same
      await page.evaluate(() => { location.hash = '#images?d=2025-01-01'; });
      await page.waitForFunction(() => /no pack for Jan 1, 2025/.test(document.querySelector('#view-images').innerText), null, { timeout: 10000 });
      const addr = await page.evaluate(() => location.hash);
      check(addr === '#images?d=' + newest, 'a day the archive does not hold is replaced in the address by the day shown (' + addr + ') and the page says so');
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

  // the well finder on the Texas images page (the archive is the fixture tests/fixtures/wells.json; the pictures are files of GitHub releases, answered here by a stub that sends them the way GitHub does:
  // application/octet-stream, nosniff). An API number or a county opens a list, a well opens its documents by stage, a picture opens large; every address works as a deep link
  for (const [label, w, h] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const asked = [];
    await ctx.route('https://github.com/**', (route) => { asked.push(route.request().url()); route.fulfill({ status: 200, contentType: 'application/octet-stream', headers: { 'x-content-type-options': 'nosniff', 'content-disposition': 'attachment' }, body: Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCABTAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDsaKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA/9k=', 'base64') }); });
    const page = await ctx.newPage();
    const errs = [];
    const asked404 = [];
    page.on('response', (r) => { if (r.status() === 404 && /\/data\/wells\//.test(r.url())) asked404.push(r.url()); });
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const tag = 'the well finder, ' + label + ': ';
    try {
      await page.goto(base + '#images', { waitUntil: 'load' });
      await page.waitForSelector('#wells-find .wells-chips a', { timeout: 25000 });
      const top = await page.locator('#wells-find').innerText();
      check(/3 wells in 2 counties/.test(top) && /8 documents/.test(top) && /the packs of Oct 29, 2026/.test(top), tag + 'the top says how many wells, documents and which packs are in the archive');
      check((await page.locator('#wells-find select.wells-county option').count()) === 3 && (await page.locator('#wells-find .wells-chips a').count()) === 2, tag + 'every county with a well is a choice and a link');
      await page.fill('#wells-find input.wells-q', '42-283-37830');
      await page.click('#wells-find button[type=submit]');
      await page.waitForSelector('#wells-find .well-doc', { timeout: 10000 });
      check(/well=28337830/.test(await page.evaluate(() => location.hash)), tag + 'an API number opens its well and goes in the address');
      check((await page.locator('#wells-find .img-stage').count()) === 3 && (await page.locator('#wells-find .well-doc').count()) === 6, tag + 'the well shows its three stages and its six documents');
      const stages = await page.locator('#wells-find .img-stage').allInnerTexts();
      check(/Permit[\s\S]*2/.test(stages[0]) && /Drilling[\s\S]*1/.test(stages[1]) && /Completion[\s\S]*3/.test(stages[2]), tag + 'the documents are under the stage they belong to');
      await page.waitForFunction(() => [...document.querySelectorAll('#wells-find .well-thumb img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 10000 });
      const thumbs = await page.evaluate(() => [...document.querySelectorAll('#wells-find .well-thumb img')].map((i) => i.getAttribute('src')));
      check(thumbs.length === 5 && thumbs.every((s) => /^https:\/\/github\.com\/o\/r\/releases\/download\/wells-2026-10-29-(ci|ds|w1)-01\/28337830_[pdc]\d\.jpg$/.test(s)), tag + 'five of the six documents have a picture, loaded from the repository\'s releases (the page\'s own policy allows it): ' + thumbs.length);
      const noPic = await page.locator('#wells-find .well-doc', { hasText: 'No picture could be drawn' }).count();
      check(noPic === 1 && (await page.locator('#wells-find .well-doc', { hasText: 'No picture could be drawn' }).locator('a.btn').getAttribute('href')).endsWith('28337830_c2.tif'), tag + 'a document with no picture says so and offers only the download of the file as filed');
      const text = await page.locator('#wells-find').innerText();
      check(/Well 42-283-37830/.test(text) && /La Salle County/.test(text) && /District 01/.test(text) && /VERDUN OIL EF II LLC/.test(text) && /3 pages/.test(text) && !/(^|\D)0 pages|NaN|undefined|Infinity|\bnull\b/.test(text), tag + 'the well names its county, district, field and operator, and no figure is NaN or 0 pages');
      check((await page.locator('#wells-find .well-lookups a').count()) === 3 && (await page.locator('#wells-find .well-lookups a').evaluateAll((a) => a.every((x) => /^https:\/\/(webapps2?|rrcsearch3)\./.test(x.href) && !/\d{8}/.test(x.href)))), tag + 'the Commission\'s own look-ups are linked, with no API number in their addresses');
      await page.click('#wells-find .well-thumb >> nth=0');
      await page.waitForSelector('dialog.well-viewer[open] img', { timeout: 5000 });
      check(await page.evaluate(() => { const i = document.querySelector('dialog.well-viewer[open] img'); return i.complete && i.naturalWidth > 0; }), tag + 'a document opens large, over the page');
      check((await page.locator('dialog.well-viewer[open] a.btn').getAttribute('href')).startsWith('https://github.com/o/r/releases/download/') && /public record/.test(await page.locator('dialog.well-viewer[open]').innerText()), tag + 'the large view links the whole document and says what the scan is');
      await page.keyboard.press('Escape');
      check((await page.locator('dialog.well-viewer[open]').count()) === 0, tag + 'Escape closes it');
      const dims = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
      check(dims.sw <= dims.cw, tag + 'no sideways scroll (' + dims.sw + ' of ' + dims.cw + ' px)');
      // a county, by its chip, and by the start of an API number; a well from the list; back
      await page.goto(base + '#images?c=283', { waitUntil: 'load' });
      await page.waitForSelector('#wells-find a.well-row', { timeout: 15000 });
      const rows = await page.locator('#wells-find a.well-row').allInnerTexts();
      check(rows.length === 2 && /42-283-37830/.test(rows[0]) && /VERDUN/.test(rows[0]) && /operator 999999/.test(rows[1]), tag + 'a county lists its wells, the one with the most documents first; an operator that is not named shows its number');
      await page.fill('#wells-find input.wells-q', '283-3');
      await page.click('#wells-find button[type=submit]');
      await page.waitForFunction(() => document.querySelectorAll('#wells-find a.well-row').length === 1, null, { timeout: 10000 });
      check(/q=283/.test(await page.evaluate(() => location.hash)), tag + 'the start of an API number narrows the county and goes in the address');
      await page.click('#wells-find a.well-row');
      await page.waitForSelector('#wells-find .well-doc', { timeout: 10000 });
      await page.goBack();
      await page.waitForSelector('#wells-find a.well-row', { timeout: 10000 });
      check(true, tag + 'back returns from a well to its county');
      await page.goto(base + '#images?well=28337830', { waitUntil: 'load' });
      await page.waitForSelector('#wells-find .well-doc', { timeout: 15000 });
      check(true, tag + 'a well\'s address opens it directly');
      await page.goto(base + '#images?well=28399999', { waitUntil: 'load' });
      await page.waitForFunction(() => /None of the packs read so far/.test(document.querySelector('#wells-find').innerText), null, { timeout: 15000 });
      check((await page.locator('#wells-find .well-lookups a').count()) === 3, tag + 'a well with no document in the archive says so, and points at the Commission\'s look-ups rather than saying it has none');
      await page.goto(base + '#images?c=999', { waitUntil: 'load' });
      await page.waitForFunction(() => /No document in the archive belongs to a well in county 999/.test(document.querySelector('#wells-find').innerText), null, { timeout: 15000 });
      check(!asked404.length, tag + 'a county with no file says so, without asking for the file (no 404 in the console)');
      await page.goto(base + '#images', { waitUntil: 'load' });
      await page.waitForSelector('#wells-find input.wells-q', { timeout: 15000 });
      await page.fill('#wells-find input.wells-q', 'x');
      await page.click('#wells-find button[type=submit]');
      await page.waitForFunction(() => /Type an API number/.test(document.querySelector('#wells-find').innerText), null, { timeout: 5000 });
      check(true, tag + 'a search with nothing to go on says what to type');
      await page.goto(base + '#images', { waitUntil: 'load' });
      await page.waitForSelector('#images-root .img-pack, #images-root .nat-hit', { timeout: 25000 });
      await page.waitForFunction(() => /documents are published under|packs of/.test(document.querySelector('#view-images').innerText), null, { timeout: 15000 });
      check(!asked.some((u) => !/^https:\/\/github\.com\/o\/r\/releases\/download\/wells-\d{4}-\d\d-\d\d-(w1|ds|ci)-\d\d\/\d{8}_[pdc]\d+\.(jpg|pdf|tif)$/.test(u)), tag + 'the only outside addresses the page asked for are files of the repository\'s well releases');
    } catch (e) {
      check(false, tag + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, tag + 'it loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // the finder with no archive: an empty one says the first packs are not read yet; one that cannot be loaded says so; the rest of the page still draws
  {
    for (const [label, handler] of [['empty', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ v: 1, generated: 'x', repo: 'o/r', keepDays: 92, units: [], counties: [], totals: { wells: 0, docs: 0, bytes: 0, stages: { p: 0, d: 0, c: 0 } } }) })],
                                    ['missing', (route) => route.fulfill({ status: 404, body: 'not found' })]]) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
      await ctx.route('**/data/wells/index.json', handler);
      const page = await ctx.newPage();
      const errs = [];
      page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
      try {
        await page.goto(base + '#images', { waitUntil: 'load' });
        await page.waitForSelector('#images-root .img-pack', { timeout: 25000 });
        const t = await page.locator('#wells-find').innerText();
        check(label === 'empty' ? /archive is empty so far/.test(t) && !/NaN|undefined/.test(t) : /could not be loaded/.test(t), 'the finder with ' + label + ' archive says so, and the rest of the page still draws');
        check((await page.locator('#wells-find form').count()) === 0, 'and offers no search it cannot answer (' + label + ')');
      } catch (e) {
        check(false, 'the finder with ' + label + ' archive: ' + e.message.split('\n')[0].slice(0, 200));
      }
      check(!errs.length, 'the finder with ' + label + ' archive throws no error' + (errs.length ? ': ' + errs.join(' | ') : ''));
      await ctx.close();
    }
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

  // 18. readable previews of the Texas filings (2026-11-01): the page's policy allows GitHub's image hosts for img-src and nothing else changed; a day whose release holds previews shows
  //     a lazy thumbnail of each, a click opens the page larger in a dialog that the keyboard closes and gives focus back from, a picture that does not load says so and keeps its link,
  //     a day with no previews shows none and asks GitHub for nothing. GitHub is answered by the test (a one-pixel PNG): nothing here touches the network.
  {
    const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
    const csp = (/http-equiv="Content-Security-Policy" content="([^"]*)"/.exec(html) || [])[1] || '';
    const dirs = Object.fromEntries(csp.split(';').map((x) => x.trim()).filter(Boolean).map((x) => [x.split(/\s+/)[0], x.split(/\s+/).slice(1).join(' ')]));
    check(JSON.stringify(dirs) === JSON.stringify({ 'default-src': "'self'", 'img-src': "'self' data: https://github.com https://*.githubusercontent.com", 'base-uri': "'none'", 'form-action': "'none'" }),
      'the Content-Security-Policy is default-src \'self\' with img-src also allowing github.com and *.githubusercontent.com, and no other directive changed: ' + csp);
    for (const [label, size] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
      const ctx = await browser.newContext({ viewport: size, reducedMotion: 'reduce' });
      const page = await ctx.newPage();
      const errs = [];
      page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
      // the one preview the test answers with 404 is expected to be reported by the browser; nothing else may be
      page.on('console', (m) => { if (m.type() === 'error' && !(m.location().url || '').endsWith('/' + previewStub.BAD)) errs.push('console: ' + m.text().slice(0, 160)); });
      page.on('requestfailed', (r) => { if (!r.url().endsWith('/' + previewStub.BAD)) errs.push('request failed: ' + r.url()); });
      try {
        const st = await previewStub.install(page, ROOT);
        const rel = st.stub.release;
        await page.goto(base + '#images?d=' + st.day, { waitUntil: 'load' });
        await page.waitForSelector('#images-root .pv-tile', { timeout: 25000 });
        const tiles = await page.locator('#images-root .pv-tile').count();
        check(tiles === 4 + 12, label + ': the day panel has a tile for each of the 3 permits\' filings that has a preview (4 of 5: the release holds none of one plat) and for the first 12 of 14 surveys (' + tiles + ')');
        for (let i = 0, n = await page.locator('#images-root .pv-thumb').count(); i < n; i++) await page.locator('#images-root .pv-thumb').nth(i).scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {}); // a thumbnail whose picture failed is replaced meanwhile
        await page.waitForFunction(() => [...document.querySelectorAll('#images-root .pv-img')].every((i) => i.complete), null, { timeout: 15000 });
        const shown = await page.evaluate(() => ({
          thumbs: [...document.querySelectorAll('#images-root .pv-img')].map((i) => ({ ok: i.naturalWidth > 0, src: i.currentSrc, lazy: i.getAttribute('loading'), alt: i.getAttribute('alt') })),
          misses: [...document.querySelectorAll('#images-root .pv-miss')].map((m) => ({ text: m.textContent.trim(), hasLink: !!m.closest('li').querySelector('a.pv-orig[href]') })),
          inline: document.querySelectorAll('#images-root .pv-grid [style], #images-root .pv-grid[style], dialog.pv-dialog [style], dialog.pv-dialog[style]').length,
          sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          small: [...document.querySelectorAll('#images-root .pv-thumb')].filter((b) => b.getBoundingClientRect().width < 24 || b.getBoundingClientRect().height < 24).length,
        }));
        check(shown.thumbs.length === tiles - 1 && shown.thumbs.every((t) => t.ok && t.lazy === 'lazy' && t.alt === '' && /^https:\/\/github\.com\/o\/r\/releases\/download\/daily-\d{4}-\d\d-\d\d\/[\w.-]+\.jpg$/.test(t.src)),
          label + ': every thumbnail loaded (from the release address, lazily; its button carries the name) except the one the test answered 404 (' + shown.thumbs.filter((t) => t.ok).length + ' of ' + (tiles - 1) + ')');
        check(shown.misses.length === 1 && shown.misses[0].text === 'Preview unavailable' && shown.misses[0].hasLink, label + ': a picture that does not load says "Preview unavailable" and its original stays linked: ' + JSON.stringify(shown.misses));
        check(!st.asked.some((u) => u.includes(previewStub.NO_PREVIEW + '.jpg')) && st.asked.every((u) => /^https:\/\/github\.com\/o\/r\/releases\/download\/daily-[\d-]+\/[\w.-]+\.pdf\.jpg$/.test(u)) && st.asked.length >= tiles,
          label + ': GitHub is asked only for previews the release holds, by their addresses (' + st.asked.length + ' requests)');
        check(!shown.inline && !shown.sideways && !shown.small, label + ': no inline style, no sideways scroll, every thumbnail is at least 24 px (' + JSON.stringify({ inline: shown.inline, sideways: shown.sideways, small: shown.small }) + ')');
        if (label === 'phone') {
          const lefts = await page.evaluate(() => [...new Set([...document.querySelectorAll('#images-root .img-files li:first-child .pv-tile')].map((t) => Math.round(t.getBoundingClientRect().left)))]);
          check(lefts.length === 2, 'phone: the thumbnails of a permit sit two to a row (' + lefts.length + ' columns)');
        }
        // the enlarged page: opened with the keyboard, closed with Escape, focus given back
        const first = page.locator('#images-root .pv-thumb').first();
        await first.focus();
        await page.keyboard.press('Enter');
        await page.waitForSelector('dialog.pv-dialog[open]', { timeout: 5000 });
        await page.waitForFunction(() => { const i = document.querySelector('dialog.pv-dialog .pv-large'); return !!i && i.complete && i.naturalWidth > 0; }, null, { timeout: 5000 });
        const dlg = await page.evaluate(() => {
          const d = document.querySelector('dialog.pv-dialog');
          const a = d.querySelector('a.pv-open');
          return { title: d.querySelector('.pv-title').textContent, inside: d.contains(document.activeElement), href: a.getAttribute('href'), link: a.textContent, label: d.getAttribute('aria-labelledby'), titleId: d.querySelector('.pv-title').id, alt: d.querySelector('.pv-large').alt, closeSize: d.querySelector('.pv-close').getBoundingClientRect().height };
        });
        check(dlg.title === 'Permit 0900001 · Approved W-1 permit' && dlg.inside && dlg.href === 'https://github.com/o/r/releases/download/' + rel.tag + '/0900001_W1.pdf' && dlg.link === 'Open the original PDF' && dlg.label === dlg.titleId && /^Page one of the approved w-1 permit/i.test(dlg.alt) && dlg.closeSize >= 24,
          label + ': Enter on a thumbnail opens the page larger in a dialog named for its permit, focus inside, with a link to the original: ' + JSON.stringify({ title: dlg.title, href: dlg.href, link: dlg.link }));
        const trapped = [];
        for (let i = 0; i < 6; i++) { await page.keyboard.press('Tab'); trapped.push(await page.evaluate(() => document.querySelector('dialog.pv-dialog').contains(document.activeElement) || document.activeElement === document.body)); } // past its last control focus goes to the browser's own bar
        check(trapped.every(Boolean), label + ': Tab never reaches the page behind the open dialog');
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => !document.querySelector('dialog.pv-dialog[open]'), null, { timeout: 5000 });
        check(await page.evaluate(() => !!document.activeElement && document.activeElement.classList.contains('pv-thumb') && /Permit 0900001, approved W-1 permit$/.test(document.activeElement.getAttribute('aria-label'))), label + ': Escape closes it and focus goes back to the thumbnail that opened it');
        await first.click();
        await page.waitForSelector('dialog.pv-dialog[open]', { timeout: 5000 });
        await page.click('dialog.pv-dialog .pv-close');
        await page.waitForFunction(() => !document.querySelector('dialog.pv-dialog[open]'), null, { timeout: 5000 });
        check(await page.evaluate(() => !!document.activeElement && document.activeElement.classList.contains('pv-thumb')), label + ': the Close button closes it too, focus back on the thumbnail');
        await first.click();
        await page.waitForSelector('dialog.pv-dialog[open]', { timeout: 5000 });
        await page.mouse.click(2, 2); // outside the dialog: on the backdrop
        await page.waitForFunction(() => !document.querySelector('dialog.pv-dialog[open]'), null, { timeout: 5000 });
        check(true, label + ': a click on the backdrop closes it');
        // an enlarged page that does not load: the words, and the link stays
        await first.click();
        await page.waitForSelector('dialog.pv-dialog[open] .pv-large', { timeout: 5000 });
        await page.evaluate(() => document.querySelector('dialog.pv-dialog .pv-large').dispatchEvent(new Event('error')));
        const gone = await page.evaluate(() => ({ text: (document.querySelector('dialog.pv-dialog .pv-stage .pv-miss') || {}).textContent, link: !!document.querySelector('dialog.pv-dialog a.pv-open[href]') && document.querySelector('dialog.pv-dialog a.pv-open').offsetParent !== null }));
        check(/^Preview unavailable/.test(gone.text || '') && gone.link, label + ': an enlarged page that does not load says "Preview unavailable" and keeps the link to the original: ' + JSON.stringify(gone));
        // reduced motion: the dialog does not animate in
        check(await page.evaluate(() => getComputedStyle(document.querySelector('dialog.pv-dialog')).animationName === 'none'), label + ': with reduced motion the dialog does not animate');
        await page.keyboard.press('Escape');
        await st.off();
      } catch (e) {
        check(false, label + ': the previews: ' + e.message.split('\n')[0].slice(0, 220));
      }
      check(!errs.length, label + ': the previews load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
      await ctx.close();
    }
    // a real day (no previews in its release yet): no tile, and nothing asked of GitHub
    {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
      const page = await ctx.newPage();
      const asked = [];
      page.on('request', (r) => { if (previewStub.isGithub(new URL(r.url()))) asked.push(r.url()); });
      try {
        const days = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'daily', 'index.json'), 'utf8')).days.map((r) => r.d).sort();
        await page.goto(base + '#images?d=' + days[days.length - 1], { waitUntil: 'load' });
        await page.waitForSelector('#images-root .img-pack', { timeout: 25000 });
        await page.waitForTimeout(500);
        check((await page.locator('#images-root .pv-tile').count()) === 0 && !asked.length && (await page.locator('dialog.pv-dialog').count()) === 0, 'a day whose release holds no previews shows none, makes no dialog and asks GitHub for nothing (' + asked.length + ' requests)');
      } catch (e) {
        check(false, 'a day with no previews: ' + e.message.split('\n')[0].slice(0, 200));
      }
      await ctx.close();
    }
    // with motion allowed the dialog fades in (the reduced-motion rule is a media query, not a removal)
    {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'no-preference' });
      const page = await ctx.newPage();
      try {
        const st = await previewStub.install(page, ROOT);
        await page.goto(base + '#images?d=' + st.day, { waitUntil: 'load' });
        await page.waitForSelector('#images-root .pv-thumb', { timeout: 25000 });
        await page.locator('#images-root .pv-thumb').first().click();
        await page.waitForSelector('dialog.pv-dialog[open]', { timeout: 5000 });
        check(await page.evaluate(() => getComputedStyle(document.querySelector('dialog.pv-dialog')).animationName === 'pv-in'), 'with motion allowed the dialog fades in');
      } catch (e) {
        check(false, 'the dialog with motion allowed: ' + e.message.split('\n')[0].slice(0, 200));
      }
      await ctx.close();
    }
  }


  // 19. the national Overview (2026-11-01): every figure from the one source that has the same facts for every state; the explorer draws, answers hover and click, replays, and says what it does not know
  for (const [label, w, h] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const pixels = (sel) => page.evaluate((q) => { const c = document.querySelector(q); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 16) if (d[i] > 40) n++; return n; }, sel);
    try {
      await page.goto(base + '?debug#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForTimeout(700);
      const kpis = await page.locator('#kpis .kpi-chip').allInnerTexts();
      check(kpis.length === 4 && /New wells, last 12 months/.test(kpis[0]) && /States with new wells/.test(kpis[1]) && /federal or tribal land/.test(kpis[2]) && /Newest well/.test(kpis[3]), label + ': four figures, the first the last 12 months\' new wells');
      const text = await page.locator('#view-overview').innerText();
      check(!/\b(NaN|undefined|null|Infinity)\b/.test(text), label + ': no NaN, undefined, null or Infinity anywhere on the Overview');
      check(!(await page.locator('#statebar').isVisible()) && !(await page.locator('#ticker, #insights, #pulse-card, #prod-card, #basins, #seg-chart').count()), label + ': no states bar and none of the cards only Texas could fill (markets, insights, producers, basins, companies)');
      const [heroPx, mapPx] = [await pixels('#hero-canvas'), await pixels('.nw-canvas')];
      check(heroPx > 300 && mapPx > 300, label + ': the hero\'s backdrop and the explorer\'s map are drawn (' + heroPx + ' and ' + mapPx + ' samples of ink)');
      const n = await page.evaluate(() => window.__nw.P.n);
      check(n > 15000 && /every state that reports to the registry/.test(await page.locator('.nw-explore .sub').innerText()), label + ': the explorer holds the wells of the last 24 months (' + n + ')');
      check(/All states/.test(await page.locator('.nw-grid .nat-panel h3').first().innerText()) && !/\/#/.test(await page.evaluate(() => location.hash)), label + ': it starts on all states');
      // the ranking is the table twin of the map: one row for each state with wells, none for a state with no well, and a state with a handful of wells shows no percentage
      const rows = await page.locator('.nat-rows .nat-row').count();
      const rank = await page.locator('.nat-rows .nat-row').first().innerText();
      check(rows >= 12 && /Texas/.test(rank) && (await page.locator('.nat-rows .nat-row', { hasText: 'Kentucky' }).innerText()).includes('n/a'), label + ': the ranking lists ' + rows + ' states, Texas first, and a state with a handful of wells says n/a, not "-57%"');
      check(/not counted as zero/.test(await page.locator('#nw-slot .nat-rank + .fine').innerText()) && /Alabama/.test(await page.locator('#nw-slot .nat-rank + .fine').innerText()), label + ': the producing states with no well in the registry are named, and are not counted as zero');
      // hover a dot: its tooltip names the county, the day and the operator, and never an API number or a lease
      const pt = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'TX' && P.o[i] >= 0) { const [x, y] = map.screenOf(i); return { x, y, i }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); // the pointer can only reach a dot that is on screen
      await page.waitForTimeout(300);
      const box = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(box.x + pt.x - 20, box.y + pt.y - 20); await page.mouse.move(box.x + pt.x, box.y + pt.y);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      const tip = await page.locator('.tip').innerText();
      check(/County, Texas|Texas/.test(tip) && /first fracturing job/.test(tip) && /operator/.test(tip) && !/\d{10}/.test(tip), label + ': hovering a dot names its county, its first job and its operator, no API number: ' + tip.replace(/\s+/g, ' ').slice(0, 120));
      // choose a state in the key: the panel, the address, the rows and the chips agree; the selector reads the same
      await page.locator('.nw-chip', { hasText: 'North Dakota' }).click();
      await page.waitForFunction(() => /^North Dakota$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      const nd = await page.locator('.nw-grid .nat-panel').innerText();
      check(/s=ND/.test(await page.evaluate(() => location.hash)) && /top counties/i.test(nd) && /top operators/i.test(nd) && /Williams|McKenzie/.test(nd) && (await page.locator('.nw-pick').inputValue()) === 'ND' && (await page.locator('.nat-row[aria-current="true"]').innerText()).includes('North Dakota'), label + ': choosing North Dakota zooms the map, fills its panel, writes s=ND in the address and marks its row');
      check(/Its permits, by the agency/.test(nd) && (await page.locator('.nw-grid .nat-panel a[href="#national?s=ND"]').count()) === 1, label + ': the state\'s panel links to its permits on the National page, which count something else');
      await page.selectOption('.nw-pick', 'TX');
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(await page.locator('.nw-grid .nat-panel a[href="#map?st=tx"]').count() === 1, label + ': Texas, Oklahoma and New Mexico link to the Map that goes deeper');
      await page.selectOption('.nw-pick', '');
      await page.waitForFunction(() => /All states/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(!/s=/.test(await page.evaluate(() => location.hash)), label + ': back to all states takes s out of the address');
      // the replay: with reduced motion only the scrubber, which moves the clock; the count only grows
      await page.click('#go-explore'); // the hero's button opens the replay under the map
      await page.waitForSelector('.tl-range', { state: 'visible', timeout: 5000 });
      check((await page.locator('.nw-explore .btn[aria-pressed="true"]').innerText()).includes('Close the replay') && (await page.locator('#explore').boundingBox()).y < 400, label + ': "Watch the wells" in the hero scrolls to the explorer and opens the replay');
      const total = await page.evaluate(() => window.__nw.map.tlCount(window.__nw.map.tlRange[1]));
      await page.locator('.tl-range').fill(String(Math.round(await page.evaluate(() => window.__nw.map.tlRange[1] / 2))));
      const half = await page.evaluate(() => window.__nw.map.tlCount(window.__nw.map.tlRange[1] / 2));
      check(half > 0 && half < total && /wells so far/.test(await page.locator('.tl-count').innerText()) && !(await page.locator('.tl-play').count()), label + ': the replay (scrubber only with reduced motion) shows ' + half + ' of ' + total + ' wells at the halfway day');
      // every year since 2011 (2026-11-01): the earlier wells are fetched when asked for; a failed request leaves the two years as they were; then the same explorer draws, replays and answers over all of them
      const nRecent = await page.evaluate(() => window.__nw.P.n);
      check((await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && (await page.locator('#nwy-all').innerText()) === 'Since 2011', label + ': the explorer offers "Last 2 years" (chosen) and "Since 2011"');
      const errsBefore = errs.length;
      await page.route('**/newwells/points-history.json', (r) => r.abort());
      await page.locator('#nwy-all').click();
      await page.waitForFunction(() => /Could not load the earlier wells/.test((document.querySelector('.nw-status') || {}).textContent || ''), null, { timeout: 15000 });
      check((await page.evaluate(() => window.__nw.P.n)) === nRecent && (await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && !(await page.locator('#nwy-recent').isDisabled()) && !(await page.locator('#nwy-all').isDisabled()), label + ': when the earlier wells cannot be loaded the map keeps the last two years, says so, and the choice stays open');
      await page.unroute('**/newwells/points-history.json');
      errs.splice(errsBefore); // the dropped requests above were the point of the check
      await page.locator('#nwy-all').click();
      await page.waitForFunction(() => window.__nw.P.n > 200000 && window.__nw.map.ready, null, { timeout: 30000 });
      await page.waitForTimeout(500);
      const nAll = await page.evaluate(() => window.__nw.P.n);
      const sub = await page.locator('.nw-explore .sub').innerText();
      check(nAll > nRecent * 8 && /first fracturing jobs from Jan 2011 to /.test(sub) && (await page.locator('#nwy-all').getAttribute('aria-pressed')) === 'true' && (await page.evaluate(() => document.activeElement && document.activeElement.id)) === 'nwy-all',
        label + ': "Since 2011" draws every well with a point (' + nAll + ' against ' + nRecent + '), says so under the heading, and keeps the keyboard on the control: ' + sub.slice(0, 90));
      check((await pixels('.nw-canvas')) > 300 && /^Watch 1[5-9] years$/.test((await page.locator('.nw-explore .btn').innerText()).trim()) && !/\b(NaN|undefined|null|Infinity)\b/.test(await page.locator('#view-overview').innerText()), label + ': the map is drawn over all of them, the replay button names its length, and no NaN anywhere');
      await page.selectOption('.nw-pick', 'TX');
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(/since Jan 2011/.test(await page.locator('.nw-grid .nat-panel svg.spark').getAttribute('aria-label')) && /Martin|Midland/.test(await page.locator('.nw-grid .nat-panel').innerText()), label + ': a state\'s panel draws its months since 2011 and still lists the year\'s counties and operators');
      const ptA = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'TX' && P.day[i] < 400) { const [x, y] = map.screenOf(i); return { x, y }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
      const boxA = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(boxA.x + ptA.x - 15, boxA.y + ptA.y - 15); await page.mouse.move(boxA.x + ptA.x, boxA.y + ptA.y);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      const tipA = await page.locator('.tip').innerText();
      check(/20(11|12)/.test(tipA) && /first fracturing job/.test(tipA) && !/\d{10}/.test(tipA), label + ': hovering a well from 2011 or 2012 answers like any other, with no API number: ' + tipA.replace(/\s+/g, ' ').slice(0, 100));
      await page.selectOption('.nw-pick', '');
      await page.locator('.nw-explore .btn').click();
      await page.waitForSelector('.tl-range', { state: 'visible', timeout: 5000 });
      const ends = await page.locator('.tl-ends').innerText();
      check(/Jan 1, 2011/.test(ends) && (await page.evaluate(() => window.__nw.map.tlRange[1] > 5000 && window.__nw.map.tlCount(window.__nw.map.tlRange[1]) === window.__nw.P.n)), label + ': the replay runs from Jan 1, 2011 and ends with every well: ' + ends.replace(/\s+/g, ' '));
      const bars = await page.evaluate(() => ({ hits: document.querySelectorAll('.nat-chart .nat-hit').length, months: window.__nw.doc.months.length, late: (() => { const t = document.querySelector('.nw-late-t'); const bb = t.getBBox(); const vb = t.ownerSVGElement.viewBox.baseVal; return bb.x >= 0 && bb.x + bb.width <= vb.width; })() }));
      check(bars.hits === bars.months && bars.months > 180 && bars.late, label + ': the monthly chart has a bar for every month since 2011 (' + bars.months + ') and its "still filling in" label is inside the drawing');
      await page.locator('#nwy-recent').scrollIntoViewIfNeeded();
      await page.locator('#nwy-recent').click();
      await page.waitForFunction((n) => window.__nw.P.n === n && window.__nw.map.ready, nRecent, { timeout: 10000 });
      check((await page.locator('.nw-explore .btn').innerText()).trim() === 'Watch 24 months' && (await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && /last 24 months/.test(await page.locator('.nw-explore .sub').innerText()), label + ': "Last 2 years" puts the two years back, with the 24-month replay');
      // the address carries the choice: #overview?s=TX&y=all opens every year, zoomed to Texas, and choosing the two years takes y out of the address
      await page.goto(base + '?debug#overview?s=TX&y=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.P.n > 200000 && window.__nw.map.ready, null, { timeout: 30000 });
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 8000 });
      check((await page.locator('#nwy-all').getAttribute('aria-pressed')) === 'true' && /y=all/.test(await page.evaluate(() => location.hash)) && /s=TX/.test(await page.evaluate(() => location.hash)), label + ': an address with y=all opens every year, zoomed to the state it names');
      await page.locator('#nwy-recent').scrollIntoViewIfNeeded();
      await page.locator('#nwy-recent').click();
      await page.waitForFunction(() => window.__nw.P.n < 30000, null, { timeout: 10000 });
      check(!/y=all/.test(await page.evaluate(() => location.hash)) && /s=TX/.test(await page.evaluate(() => location.hash)), label + ': choosing the last two years takes y out of the address and keeps the state');
      // the oil permits and spuds beside the fracked wells (2026-11-02): rings and dots on one map, a switch, a legend that says which is which, a panel line that is never added to the wells
      await page.goto(base + '?debug&fresh=10#overview', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready && window.__nw.Q, null, { timeout: 30000 });
      await page.waitForTimeout(600);
      const rings0 = await page.evaluate(() => ({ n: window.__nw.map.drawnPermits, k: window.__nw.map.kinds, total: window.__nw.Q.n }));
      check(rings0.total > 1000 && rings0.n === rings0.total && rings0.k.wells && rings0.k.permits && !(await page.evaluate(() => !!window.__nw.hero && window.__nw.hero.drawnPermits > 0)), label + ': the explorer draws the oil permits and spuds as rings beside the fracked wells\' dots (' + rings0.n + ' rings of ' + rings0.total + ' records: every one, including the permits newer than the newest well), and the hero\'s backdrop stays wells only');
      const legend = await page.locator('.nw-legend').innerText();
      check((await page.locator('.nw-legend .dd-dotkey').count()) === 1 && (await page.locator('.nw-legend .dd-ringkey').count()) === 1 && /Fracked well/.test(legend) && /Oil permit or spud/.test(legend) && /never added together/.test(legend) && /About \d+% of Texas/.test(legend) && (await page.locator('#nwk-both').getAttribute('aria-pressed')) === 'true',
        label + ': the legend says which is which (a filled dot, a hollow ring), that Texas gives a location for part of its permits, and that the two are never added');
      const ringLine = (await page.locator('.nw-grid .nw-ringline').innerText()).replace(/,/g, '');
      const ringTotal = await page.evaluate(() => { const { P, doc, D, Q } = window.__nw; const [a, b] = D.settledRange(P, doc); return D.permitsPerState(Q, a, b).reduce((t, r) => t + r.n, 0); });
      check(ringTotal > 1000 && ringLine.startsWith(String(ringTotal)) && /not added to the fracked wells/.test(ringLine), label + ': the panel counts the rings of the same 12 months apart from the wells (' + ringTotal + '), and says they are not added to them');
      await page.locator('#nwk-wells').scrollIntoViewIfNeeded(); await page.locator('#nwk-wells').click();
      const onlyWells = await page.evaluate(() => ({ n: window.__nw.map.drawnPermits, k: window.__nw.map.kinds }));
      check(onlyWells.k.wells && !onlyWells.k.permits && onlyWells.n === 0 && /k=wells/.test(await page.evaluate(() => location.hash)) && (await page.locator('#nwk-wells').getAttribute('aria-pressed')) === 'true', label + ': "Fracked wells" hides the rings and writes k=wells in the address');
      await page.locator('#nwk-permits').click();
      const onlyRings = await page.evaluate(() => ({ n: window.__nw.map.drawnPermits, k: window.__nw.map.kinds }));
      check(!onlyRings.k.wells && onlyRings.k.permits && onlyRings.n > 1000 && /k=permits/.test(await page.evaluate(() => location.hash)) && (await pixels('.nw-canvas')) > 300, label + ': "Oil permits" draws the rings alone (' + onlyRings.n + ') and writes k=permits');
      const ring = await page.evaluate(() => { const { map, Q } = window.__nw; for (let j = Q.n - 1; j >= 0; j--) if (Q.states[Q.s[j]] === 'TX') { const [x, y] = map.screenOfQ(j); return { x, y }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
      const rbox = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(rbox.x + ring.x - 15, rbox.y + ring.y - 15); await page.mouse.move(rbox.x + ring.x, rbox.y + ring.y);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      const ringTip = await page.locator('.tip').innerText();
      check(/Oil permit approved · Texas/.test(ringTip) && !/\d{10}/.test(ringTip), label + ': hovering a ring says what it is, with no API number: ' + ringTip.replace(/\s+/g, ' ').slice(0, 100));
      await page.locator('.nw-explore .btn', { hasText: 'Watch' }).click();
      await page.waitForSelector('.tl-range', { state: 'visible', timeout: 5000 });
      const permitsSoFar = await page.locator('.tl-count').innerText();
      await page.locator('#nwk-both').click();
      const bothSoFar = await page.locator('.tl-count').innerText();
      check(/oil permits? and spuds? so far/.test(permitsSoFar) && /fracked wells? so far/.test(bothSoFar), label + ': the replay counts what the map shows: ' + permitsSoFar + ' with only the rings, ' + bothSoFar + ' with both');
      await page.locator('.nw-explore .btn', { hasText: 'Close the replay' }).click();
      await page.selectOption('.nw-pick', 'ND');
      await page.waitForFunction(() => /^North Dakota$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(/North Dakota publishes no oil permit locations/.test(await page.locator('.nw-grid .nw-ringline').innerText()), label + ': a state with no permit locations says so, not a zero');
      await page.selectOption('.nw-pick', 'NM');
      await page.waitForFunction(() => /^New Mexico$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(/oil wells spudded with a map location/.test(await page.locator('.nw-grid .nw-ringline').innerText()), label + ': New Mexico\'s rings are wells spudded, not permits approved');
      await page.selectOption('.nw-pick', '');
      await page.locator('#nwy-all').click();
      await page.waitForFunction(() => window.__nw.P.n > 200000 && window.__nw.map.ready && window.__nw.map.drawnPermits > 1000, null, { timeout: 30000 });
      check((await page.locator('.nw-legend .dd-ringkey').count()) === 1 && (await page.locator('#nwk-both').getAttribute('aria-pressed')) === 'true', label + ': with every year since 2011 the rings are still drawn (the permit files start in 2024) and the switch keeps its place');
      await page.goto(base + '?debug&fresh=11#overview?s=TX&k=permits', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready && window.__nw.Q, null, { timeout: 30000 });
      await page.waitForFunction(() => /^Texas$/.test((document.querySelector('.nw-grid .nat-panel h3') || {}).textContent || ''), null, { timeout: 8000 });
      check(await page.evaluate(() => !window.__nw.map.kinds.wells && window.__nw.map.kinds.permits) && (await page.locator('#nwk-permits').getAttribute('aria-pressed')) === 'true' && /k=permits/.test(await page.evaluate(() => location.hash)) && /s=TX/.test(await page.evaluate(() => location.hash)) && /oil permits approved with a map location/.test(await page.locator('.nw-grid .nw-ringline').innerText()),
        label + ': an address with k=permits opens on the rings alone, and a state\'s line counts permits approved');
    } catch (e) {
      check(false, label + ': the national Overview: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, label + ': the national Overview loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 20. the National report and the matrix speak to a visitor (2026-11-01): the researchers' own words (this machine, from here, I tried, the tracker) are not on the pages, the offshore and the BLM are common nouns inside a sentence,
  //     a state that is not read yet says why in plain words and what grade its data has, the matrix shows no producer plan, and the Sources page lists the state agencies from the report's own data (a file download is not a link)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const VOICE = /\b(this machine|from here|I tried|I read|I saw|the tracker|polite request|the brief|sandbox|WebFetch|HEAD request|reachable)\b/i;
    try {
      const natDoc = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'national.json'), 'utf8'));
      await page.goto(base + '#national', { waitUntil: 'load' });
      await page.waitForSelector('#national-root .nat-cov', { timeout: 25000 });
      const kpiText = await page.locator('#national-root .nat-kpis').innerText();
      check(/the federal offshore/.test(kpiText) && !/, Federal offshore|and Federal offshore/.test(kpiText), 'the top figures say "the federal offshore" inside a sentence: ' + kpiText.replace(/\s+/g, ' ').slice(0, 260));
      const cov = await page.locator('#national-root .nat-cov').innerText();
      check(!VOICE.test(cov) && natDoc.gaps.every((g) => cov.includes(g.name)), 'the coverage table has a plain reason for every state not read yet, with none of the researchers\' words');
      check(/Its published data, as researched \(grade [A-D]\): /.test(cov) && !/\bgrade [A-D]\s*$/m.test(cov), 'and a gap\'s grade is explained, not left as a bare letter in the Updates column');
      const rows = await page.evaluate(() => [...document.querySelectorAll('#national-root .nat-cov tbody tr')].map((r) => ({ gap: r.classList.contains('is-gap'), upd: r.children[4].textContent.trim() })));
      check(rows.filter((r) => r.gap).every((r) => r.upd === '—') && rows.filter((r) => !r.gap).every((r) => /^(Publishes|Weekly|Monthly|Nightly|Daily|Irregular|Live|Quarterly|Monthly)/i.test(r.upd) || r.upd.length > 3), 'a state not read yet has a dash under Updates; the others say how they update');
      await page.click('#national-root button.nat-tile[data-id="FO"]');
      check(/Open the federal offshore in the Map/.test(await page.locator('#national-root .nat-panel').innerText()), 'a link inside a sentence names "the federal offshore"');
      await page.click('#national-root button.nat-tile[data-id="UT"]');
      const href = await page.locator('#national-root .nat-panel a[target="_blank"]').first().getAttribute('href');
      check(!!href && !/\.(zip|csv|xlsx?)(\?|$)/i.test(href) && !/FeatureServer|MapServer|rest\/services/i.test(href), 'a panel\'s source link is a page, not a raw download or a service root: ' + href);
      await page.goto(base + '#fields?s=MO', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root .nat-panel', { timeout: 25000 });
      const fx = await page.locator('#fields-root .nat-panel').innerText();
      check(!VOICE.test(fx) && !/How a monthly count could be built/.test(fx) && /Updated 2026-11-01/.test(fx), 'the matrix\'s panel for the one state not read yet (Missouri) is in a visitor\'s words, shows no producer plan and says what changed since the first research: ' + fx.replace(/\s+/g, ' ').slice(0, 220));
      const ties = await page.locator('#fields-root .nat-kpis').innerText();
      check(!/\d\d?\s+of\s+\d+ agencies as data\s*$/.test('x') && /Published by the most agencies/.test(ties), 'the matrix\'s figures load: ' + ties.replace(/\s+/g, ' ').slice(0, 200));
      await page.goto(base + '#about', { waitUntil: 'load' });
      await page.waitForSelector('#src-national li', { timeout: 25000 });
      await page.waitForFunction(() => document.querySelectorAll('#src-national li').length > 5, null, { timeout: 15000 });
      const src = await page.evaluate(() => ({ n: document.querySelectorAll('#src-national li').length, hrefs: [...document.querySelectorAll('#src-national a')].map((a) => a.getAttribute('href')), text: document.querySelector('#src-national').innerText }));
      const wantRows = natDoc.states.filter((x) => !['TX', 'OK', 'NM', 'FO'].includes(x.id)).length + 2;
      check(src.n === wantRows && src.hrefs.every((h) => h && !/\.(zip|csv|xlsx?)(\?|$)/i.test(h) && !/FeatureServer|MapServer|rest\/services/i.test(h)) && !VOICE.test(src.text) && /Not read yet/.test(src.text),
        'the Sources page lists the state agencies behind the National report from its own data (' + src.n + ' lines for ' + (wantRows - 2) + ' agencies and the unread ones), none linked to a raw download');
      check(await page.evaluate(() => [...document.querySelectorAll('.toc button')].some((b) => /State agencies behind the National report/.test(b.textContent))), 'and its heading is in the page\'s table of contents');
    } catch (e) {
      check(false, 'the wording block: ' + e.message.split('\n')[0].slice(0, 240));
    }
    check(!errs.length, 'the wording pages load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 21. layout and keyboard of the National report and the matrix (2026-11-01, from the other session's review): an operator's name is whole (it wrapped to a second line instead of ending in an ellipsis at 100 px),
  //     the chart is drawn at the width it has (its axis text is not shrunk to a third on a phone), its axis tops near the data, the matrix has a few tab stops and not 1,680 (the arrow keys move between cells),
  //     its group strip wraps instead of hiding choices, and an address without a count or a group shows the permits and every group (the page kept the last choice)
  for (const [label, size] of [['desktop', { width: 1280, height: 900 }], ['tablet', { width: 820, height: 900 }], ['phone', { width: 360, height: 800 }]]) {
    const ctx = await browser.newContext({ viewport: size, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#national?s=TX', { waitUntil: 'load' });
      await page.waitForSelector('#national-root .nat-list li', { timeout: 25000 });
      const names = await page.evaluate(() => [...document.querySelectorAll('#national-root .nat-panel .nat-ln')].map((n) => ({ t: n.textContent, cut: n.scrollWidth > n.clientWidth + 1, lines: Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)) })));
      check(names.length > 6 && names.every((n) => !n.cut && n.lines <= 2) && !names.some((n) => /…$/.test(n.t)), label + ': every name in a panel\'s lists is whole, on one or two lines (' + names.length + ' names, the longest ' + Math.max(...names.map((n) => n.t.length)) + ' characters)');
      const chart = await page.evaluate(() => { const g = document.querySelector('#national-root .nat-chart'); const vb = g.viewBox.baseVal; const ax = g.querySelector('text.ax'); return { ratio: g.getBoundingClientRect().width / vb.width, axis: parseFloat(getComputedStyle(ax).fontSize) * (g.getBoundingClientRect().width / vb.width), ticks: [...g.querySelectorAll('text.ax')].slice(0, 8).map((t) => t.textContent), vbw: vb.width }; });
      check(chart.ratio > 0.9 && chart.ratio < 1.1 && chart.axis >= 10, label + ': the chart is drawn at the width it has (scale ' + chart.ratio.toFixed(2) + ', axis text ' + chart.axis.toFixed(1) + ' px, drawn ' + chart.vbw + ' wide)');
      // the axis tops near the biggest bar: the top tick is at most 1.5 times the tallest month
      const tall = await page.evaluate(() => { const g = document.querySelector('#national-root .nat-chart'); const ticks = [...g.querySelectorAll('text.ax')].map((t) => t.textContent.replace(/,/g, '')).filter((t) => /^\d+$/.test(t)).map(Number); return { top: Math.max(...ticks), rows: [...document.querySelectorAll('#national-root .nat-details tbody tr')].slice(0, 36).map((tr) => +tr.lastElementChild.textContent.replace(/,/g, '')) }; });
      check(tall.top >= Math.max(...tall.rows) && tall.top <= Math.max(...tall.rows) * 1.5, label + ': the axis tops at ' + tall.top + ' for a tallest month of ' + Math.max(...tall.rows));
      // an address without a count shows the permits, even after a visit to the wells spudded
      await page.click('#natm-spuds');
      await page.goto(base + '#fields', { waitUntil: 'load' });
      await page.goto(base + '#national', { waitUntil: 'load' });
      await page.waitForSelector('#national-root .nat-chart', { timeout: 25000 });
      check((await page.locator('#natm-permits').getAttribute('aria-pressed')) === 'true' && !/m=spuds/.test(await page.evaluate(() => location.hash)), label + ': #national after a visit to Wells spudded shows the permits again');
      // the matrix
      await page.goto(base + '#fields?g=where', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root table.fx', { timeout: 25000 });
      const groupRows = await page.locator('#fields-root tr.fx-group').count();
      await page.goto(base + '#fields', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root table.fx', { timeout: 25000 });
      check(groupRows === 1 && (await page.locator('#fields-root tr.fx-group').count()) > 1 && (await page.locator('#fxg-all').getAttribute('aria-pressed')) === 'true', label + ': #fields after #fields?g=where shows every group again');
      const strip = await page.evaluate(() => { const s = document.querySelector('#fields-root .fx-tools .seg'); const r = s.getBoundingClientRect(); return { fits: s.scrollWidth <= s.clientWidth + 1, buttons: [...s.querySelectorAll('button')].every((b) => { const q = b.getBoundingClientRect(); return q.left >= r.left - 1 && q.right <= r.right + 1; }), wrap: s.classList.contains('wrap') }; });
      check(strip.wrap && strip.fits && strip.buttons, label + ': the group strip wraps, and every choice is inside it: ' + JSON.stringify(strip));
      const stops = await page.evaluate(() => [...document.querySelectorAll('#fields-root table.fx button')].filter((b) => b.tabIndex >= 0).length);
      const total = await page.evaluate(() => document.querySelectorAll('#fields-root table.fx button.fx-c').length);
      check(total > 1000 && stops <= 1 + 50 + 40 && (await page.evaluate(() => [...document.querySelectorAll('#fields-root table.fx button.fx-c')].filter((b) => b.tabIndex >= 0).length)) === 1, label + ': the matrix has ' + stops + ' tab stops among its buttons, one of them in the ' + total + ' cells');
      if (label === 'desktop') {
        const first = page.locator('#fields-root table.fx button.fx-c').first();
        await first.focus();
        await page.keyboard.press('ArrowRight');
        const right = await page.evaluate(() => document.activeElement.getAttribute('aria-label'));
        await page.keyboard.press('ArrowDown');
        const down = await page.evaluate(() => document.activeElement.getAttribute('aria-label'));
        await page.keyboard.press('End');
        const end = await page.evaluate(() => ({ label: document.activeElement.getAttribute('aria-label'), stops: [...document.querySelectorAll('#fields-root table.fx button.fx-c')].filter((b) => b.tabIndex >= 0).length }));
        await page.keyboard.press('Enter');
        await page.waitForTimeout(200);
        const first0 = await first.getAttribute('aria-label');
        check(right && down && right !== first0 && down.split(', ')[0] === right.split(', ')[0] && down !== right && end.stops === 1 && /\/?s=/.test(await page.evaluate(() => location.hash)), 'the arrow keys move between cells (right: ' + right + ' / down: ' + down + ' / end: ' + end.label + '), the tab stop goes with the focus, and Enter chooses a cell');
      }
    } catch (e) {
      check(false, label + ': the layout block: ' + e.message.split('\n')[0].slice(0, 240));
    }
    check(!errs.length, label + ': the layout pages load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 21b. the Texas images chart is drawn again when the window changes size (it was drawn once at the width it had)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#images', { waitUntil: 'load' });
      await page.waitForSelector('#images-root svg.nat-chart', { timeout: 25000 });
      const width = () => page.evaluate(() => { const g = document.querySelector('#images-root svg.nat-chart'); return { vb: g.viewBox.baseVal.width, px: g.getBoundingClientRect().width }; });
      const wide = await width();
      await page.setViewportSize({ width: 380, height: 800 });
      await page.waitForFunction((w) => document.querySelector('#images-root svg.nat-chart').viewBox.baseVal.width < w - 100, wide.vb, { timeout: 5000 });
      const narrow = await width();
      check(narrow.vb < wide.vb && narrow.px / narrow.vb > 0.9 && narrow.px / narrow.vb < 1.1, 'the images chart is drawn again at the new width (' + wide.vb + ' wide, then ' + narrow.vb + ' at scale ' + (narrow.px / narrow.vb).toFixed(2) + ')');
    } catch (e) {
      check(false, 'the images chart on a resize: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 22. the national Daily report (2026-11-01): one day of new wells, nationwide, the same for every state; the day can be chosen four ways, the newest days say they are filling in,
  //     a state can be chosen, a day with no well says none, and nothing is a figure only some states have
  for (const [label, w, h] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const head = () => page.locator('#daily-root .nat-panel h3').first().innerText();
    const tableHead = () => page.locator('#dd-table-h').innerText();
    const hash = () => page.evaluate(() => location.hash);
    // the numbers card describes the wells the table lists: its pad line counts the same wells, its land line the same, and a day with none says so
    const statsAgree = async (what) => {
      const n = +(await tableHead()).match(/^([\d,]+) (?:fracked )?well/)[1].replace(/,/g, '');
      if (!n) return (await page.locator('#daily-root .dd-stat').count()) === 0 && /nothing to describe/.test(await page.locator('#daily-root .dd-stats').innerText()) ? null : what + ': a day with no well should say there is nothing to describe, not draw six panels';
      const pads = +(await page.locator('#daily-root .dd-pads .fine').first().innerText()).match(/^([\d,]+) wells? on/)[1].replace(/,/g, '');
      const land = +(await page.locator('#daily-root .dd-land .fine').first().innerText()).match(/of ([\d,]+)/)[1].replace(/,/g, '');
      return pads === n && land === n ? null : what + ': the numbers describe ' + pads + ' and ' + land + ' wells but the table lists ' + n;
    };
    try {
      await page.goto(base + '?debug#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-nav', { timeout: 25000 });
      await page.waitForTimeout(900);
      const text = await page.locator('#view-daily').innerText();
      check(!/\b(NaN|undefined|null|Infinity)\b/.test(text), label + ': no NaN, undefined, null or Infinity anywhere on the Daily report');
      check((await page.locator('#daily-root .dr-tile').count()) === 4 && !(await page.locator('#statebar').isVisible()) && !(await page.locator('#ticker, #insights, #pulse-card, #seg-chart').count()), label + ': four figures, no states bar, none of the Texas-only cards');
      check(!/\d{10}/.test(text) && !/API/.test(text.replace(/No API number/, '').replace(/(matched by|without) API numbers?/g, '')), label + ': no API number, well name or lease anywhere on the page');
      const ink = await page.evaluate(() => { const c = document.querySelector('#daily-root .nw-canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 16) if (d[i] > 40) n++; return n; });
      check(ink > 300, label + ': the map is drawn (' + ink + ' samples of ink)');
      const first = await page.locator('#daily-root .dd-date').innerText();
      const n0 = +(await tableHead()).match(/^([\d,]+) (?:fracked )?well/)[1].replace(/,/g, '');
      const titles = await page.locator('#daily-root .dd-stat h3').allTextContents();
      check(titles.join('|') === 'Where|Pads and spots|How deep|How much water|Whose land|Who drilled', label + ': the day in numbers has its six panels: ' + titles.join(', '));
      check(!(await statsAgree(label + ' (opening day)')), (await statsAgree(label)) || label + ': the numbers describe the same wells as the table on the opening day');
      const bars = await page.evaluate(() => [...document.querySelectorAll('#daily-root .dd-stat .nat-lb, #daily-root .dd-hbar')].map((b) => parseFloat(getComputedStyle(b).getPropertyValue('--p')) || 0));
      check(bars.length >= 8 && bars.every((v) => v >= 0 && v <= 1.0001) && bars.some((v) => v === 1), label + ': the panels draw bars (' + bars.length + ') on a scale of 0 to 1, the longest full');
      check(/Susquehanna|Lea|Eddy|Pecos|, [A-Z]{2}/.test(await page.locator('#daily-root .dd-where').innerText()) && /Typical/.test(await page.locator('#daily-root .dd-pads').innerText()) && /Olympic swimming pools/.test(await page.locator('#daily-root .dd-water').innerText()) && /federal or tribal/.test(await page.locator('#daily-root .dd-land').innerText()), label + ': the panels name where (county and state), set pads against a typical day, give water in pools and say whose land');
      // every permit approved each day (Texas, Oklahoma and New Mexico publish a list daily), counted in the summary and drawn as a line of rings in the chart: beside the rings of the permits that have a location
      const dots = () => page.locator('#daily-root .dd-chart .dd-oil-dot').count();
      const appr = (await page.locator('#daily-root .dd-approved').first().innerText()).replace(/\s+/g, ' ');
      const apprN = +appr.match(/Approved that day: ([\d,]+) new-drill permits?/)[1].replace(/,/g, ''); const apprParts = [...appr.matchAll(/(Texas|Oklahoma|New Mexico) ([\d,]+)/g)].map((m) => +m[2].replace(/,/g, ''));
      check(apprParts.length === 3 && apprParts.reduce((a, b) => a + b, 0) === apprN && apprN >= 1, label + ': the summary counts every permit approved that day, by state, and the parts add up (' + appr.slice(0, 120) + ')');
      check((await dots()) > 40 && (await page.locator('#daily-root .dd-chart .dd-oil-line').count()) >= 1 && /line of rings/.test(await page.locator('#daily-root .dd-oilkey').innerText()) && /not added/.test(await page.locator('#daily-root .dd-chartbox').locator('xpath=..').innerText()), label + ': the chart has the permits approved each day as a line of rings beside the bars, with a key, and says they are not added to the wells');
      await page.click('#ddk-wells');
      check((await dots()) === 0 && (await page.locator('#daily-root .dd-oilkey').count()) === 0 && (await page.locator('#daily-root .dd-approved').count()) === 0 && !/\b(null|undefined|NaN)\b/.test(await page.locator('#daily-root .dd-chartbox').innerText()), label + ': "Fracked wells" takes the line, its key and the approvals out, and leaves no "null" in the chart');
      await page.click('#ddk-permits');
      check((await dots()) > 40 && (await page.locator('#daily-root .dd-approved').count()) === 1, label + ': "Oil permits" keeps them');
      await page.click('#ddk-both');
      await page.selectOption('#daily-root select.nw-pick', 'TX');
      await page.waitForFunction(() => /Approved that day in Texas/.test((document.querySelector('#daily-root .dd-approved') || {}).textContent || ''), null, { timeout: 8000 });
      check((await dots()) > 40 && !/Oklahoma/.test(await page.locator('#daily-root .dd-approved').first().innerText()), label + ': choosing Texas counts Texas\'s permits alone, in the summary and in the line');
      await page.selectOption('#daily-root select.nw-pick', 'ND');
      await page.waitForFunction(() => /not published by day for this state/.test((document.querySelector('#daily-root .dd-oilkey') || {}).textContent || ''), null, { timeout: 8000 });
      check((await dots()) === 0 && (await page.locator('#daily-root .dd-approved').count()) === 0, label + ': a state that publishes no daily list has no line and no count, said in the key, never zeros');
      await page.selectOption('#daily-root select.nw-pick', '');
      await page.fill('#daily-root input[type=date]', '2026-03-10'); await page.locator('#daily-root input[type=date]').dispatchEvent('change');
      await page.waitForFunction(() => /starts on Aug 1, 2026/.test((document.querySelector('#daily-root .dd-approved') || {}).textContent || ''), null, { timeout: 8000 });
      check((await dots()) === 0 && /none by day for these days/.test(await page.locator('#daily-root .dd-oilkey').innerText()), label + ': a day before the daily lists were read says the count of every permit starts on Aug 1, 2026 and draws no line there, not zeros');
      await page.goto(base + '?debug&again=1#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-nav', { timeout: 25000 });
      await page.waitForTimeout(900);
      check(n0 >= 10 && /Still filling in/.test(await page.locator('#daily-root .nat-panel .badge').first().innerText()), label + ': it opens on the newest day with ten or more wells (' + first + ', ' + n0 + ' wells), and says that day is still filling in');
      check(/typical settled day has about \d+\.\d/.test(await page.locator('#daily-root .nat-panel').innerText()), label + ': a day still filling in is set against a typical day and not called slow');
      // four ways to choose a day: the arrows, the slider, the date box, a bar of the chart
      await page.click('button[aria-label="The day before"]');
      check((await page.locator('#daily-root .dd-date').innerText()) !== first && /d=\d{4}-\d\d-\d\d/.test(await hash()), label + ': the arrow moves a day and writes it in the address');
      check(!(await statsAgree(label + ' (day before)')), (await statsAgree(label + ' (day before)')) || label + ': the numbers follow the arrow: they describe the day\'s wells');
      await page.locator('#daily-root .tl-range').fill(await page.evaluate(() => String(document.querySelector('#daily-root .tl-range').min)));
      check(/Jun|May/.test(await page.locator('#daily-root .dd-date').innerText()), label + ': the slider reaches the start of the chart: ' + (await page.locator('#daily-root .dd-date').innerText()));
      await page.fill('#daily-root input[type=date]', '2026-03-10'); await page.locator('#daily-root input[type=date]').dispatchEvent('change');
      check(/Tuesday, Mar 10, 2026/.test(await page.locator('#daily-root .dd-date').innerText()) && /^Settled$/.test(await page.locator('#daily-root .nat-panel .badge').first().innerText()) && /d=2026-03-10/.test(await hash()), label + ': the date box opens a day, and a day long past is settled');
      await page.locator('#daily-root .dd-chartbox').scrollIntoViewIfNeeded();
      await page.locator('#daily-root .dd-chart .nat-hit').nth(100).dispatchEvent('click');
      check(!/Mar 10/.test(await page.locator('#daily-root .dd-date').innerText()), label + ': a click on the chart opens that day');
      // a state: the table, the chart and the summary agree
      await page.selectOption('#daily-root select.nw-pick', 'TX');
      await page.waitForFunction(() => /in Texas$/.test(document.querySelector('#dd-table-h').textContent), null, { timeout: 5000 });
      const states = await page.evaluate(() => [...document.querySelectorAll('#daily-root .table-wrap.tall tbody tr td:nth-child(2)')].map((t) => t.textContent));
      check(/s=TX/.test(await hash()) && states.length > 0 && states.every((x) => x === 'Texas') && (await page.locator('#daily-root .dd-chartbox .nat-keys:not(.dd-oilkey) li').count()) === 1, label + ': choosing Texas keeps only Texas in the table and the chart (' + states.length + ' wells), and writes s=TX');
      check(!(await statsAgree(label + ' (Texas)')) && /in Texas/.test(await page.locator('#daily-root .dd-where').innerText()), (await statsAgree(label + ' (Texas)')) || label + ': choosing Texas makes the numbers Texas\'s own');
      // a day with no well says none, rather than a figure the registry lacks
      await page.selectOption('#daily-root select.nw-pick', 'ND');
      await page.fill('#daily-root input[type=date]', '2026-06-24'); await page.locator('#daily-root input[type=date]').dispatchEvent('change');
      await page.waitForFunction(() => /^0 fracked wells/.test(document.querySelector('#dd-table-h').textContent), null, { timeout: 5000 });
      check(/No well had its first fracturing job this day/.test(await page.locator('#daily-root .nat-panel').innerText()) && /No fracked well/.test(await page.locator('#daily-root #dd-table-h + div').innerText()), label + ': a day with no well in the chosen state says "No well", not a table of blanks');
      check(!(await statsAgree(label + ' (empty day)')) && (await page.locator('#daily-root .dd-stats.is-empty').count()) === 1, (await statsAgree(label + ' (empty day)')) || label + ': a day with no well in the chosen state: the numbers say there is nothing to describe');
      // freshness: each state's newest well, and the producing states with none in the registry named, not counted as zero
      const fresh = await page.locator('#daily-root .nat-cov, #daily-root table').last().innerText();
      check(/Texas/.test(fresh) && /Days behind the newest/i.test(fresh) && /not counted as zero/.test(await page.locator('#daily-root').innerText()), label + ': the freshness table names each state\'s newest well and the states with none');
      await page.goto(base + '#daily?d=2026-02-02&s=TX', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-nav', { timeout: 25000 });
      await page.waitForFunction(() => /in Texas$/.test((document.querySelector('#dd-table-h') || {}).textContent || ''), null, { timeout: 10000 });
      check(/Monday, Feb 2, 2026/.test(await page.locator('#daily-root .dd-date').innerText()), label + ': an address with a day and a state opens on them');
      await page.click('#daily-root button:has-text("Newest day")');
      check(/Wednesday, Oct 14, 2026|Oct 14, 2026/.test(await page.locator('#daily-root .dd-date').innerText()), label + ': "Newest day" opens the newest well\'s day: ' + (await page.locator('#daily-root .dd-date').innerText()));
      // older days (2026-11-01): the chart and the slider hold 150 days and page back with Earlier and Later; a day before the last two years loads the earlier wells first
      await page.goto(base + '?fresh=1#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-nav', { timeout: 25000 });
      await page.waitForTimeout(500);
      const title = () => page.locator('#daily-root section.nat-card').filter({ hasText: 'Day by day' }).locator('h2').first().innerText();
      const slider = () => page.evaluate(() => { const r = document.querySelector('#daily-root .tl-range'); return { min: +r.min, max: +r.max, value: +r.value }; });
      const newestDay = await page.locator('#daily-root .dd-date').innerText();
      check(/^The last 150 days/.test(await title()) && await page.locator('#daily-root button:has-text("Later")').isDisabled() && !(await page.locator('#daily-root button:has-text("Earlier")').isDisabled()) && (await page.locator('#daily-root input[type=date]').getAttribute('min')) === '2011-01-01', label + ': the chart opens on the last 150 days (Later is off, Earlier is on) and the date box reaches back to 2011-01-01');
      check(!(await page.locator('#daily-root select.nw-pick option[value="AL"]').count()), label + ': before the earlier wells load, the state list holds the states with wells in the last year');
      await page.locator('#daily-root button:has-text("Earlier")').click();
      await page.waitForFunction((d) => document.querySelector('#daily-root .dd-date').textContent !== d, newestDay, { timeout: 10000 });
      const sl = await slider();
      check(/^The 150 days from /.test(await title()) && !(await page.locator('#daily-root button:has-text("Later")').isDisabled()) && sl.max - sl.min === 149 && sl.value >= sl.min && sl.value <= sl.max, label + ': Earlier pages the chart and the day back 150 days together, and the slider covers that page: ' + (await title()));
      await page.locator('#daily-root button:has-text("Later")').click();
      check(/^The last 150 days/.test(await title()) && (await page.locator('#daily-root .dd-date').innerText()) === newestDay, label + ': Later brings the chart and the day back to where they were');
      // the earlier wells cannot be loaded: the day stays and the page says so
      const errsBefore = errs.length;
      await page.route('**/newwells/points-history.json', (r) => r.abort());
      await page.fill('#daily-root input[type=date]', '2014-03-12'); await page.locator('#daily-root input[type=date]').dispatchEvent('change');
      await page.waitForFunction(() => /Could not load the earlier wells/.test((document.querySelector('#daily-root .nw-status') || {}).textContent || ''), null, { timeout: 15000 });
      check((await page.locator('#daily-root .dd-date').innerText()) === newestDay, label + ': when the earlier wells cannot be loaded the day stays and the page says so');
      await page.unroute('**/newwells/points-history.json');
      errs.splice(errsBefore); // the dropped requests above were the point of the check
      const hist = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'newwells', 'points-history.json'), 'utf8'));
      const dayNo = Math.round((Date.UTC(2014, 2, 12) - Date.UTC(2011, 0, 1)) / 864e5); const want = hist.d.filter((d) => d === dayNo).length;
      await page.fill('#daily-root input[type=date]', '2014-03-12'); await page.locator('#daily-root input[type=date]').dispatchEvent('change');
      await page.waitForFunction(() => /Mar 12, 2014/.test(document.querySelector('#daily-root .dd-date').textContent), null, { timeout: 30000 });
      await page.waitForTimeout(400);
      const sl2 = await slider();
      check(want > 20 && new RegExp('^' + want + ' fracked wells on Mar 12, 2014$').test(await tableHead()) && /Mar 12, 2014/.test(await head()) && /^Settled$/.test(await page.locator('#daily-root .nat-panel .badge').first().innerText()) && /d=2014-03-12/.test(await hash()),
        label + ': a date in 2014 loads the earlier wells and opens that day with the same ' + want + ' wells the file holds: ' + (await tableHead()));
      check(/A typical day in the 12 months Oct 2013 to Sep 2014 had about \d+\.\d/.test(await page.locator('#daily-root .nat-panel').innerText()) && /^The 150 days from /.test(await title()) && sl2.max - sl2.min === 149 && (await page.locator('#daily-root .dd-chart .dd-marker').evaluate((n) => n.style.display !== 'none')),
        label + ': a day in 2014 is set against 2014, the chart and the slider hold the 150 days around it, and the day is marked');
      check((await page.locator('#daily-root select.nw-pick option[value="AL"]').count()) === 1 && (await page.evaluate(() => document.activeElement && document.activeElement.type)) === 'date', label + ': the state list now holds every state that has had a well, and the keyboard stays on the date box');
      await page.selectOption('#daily-root select.nw-pick', 'ND');
      await page.waitForFunction(() => /in North Dakota$/.test(document.querySelector('#dd-table-h').textContent), null, { timeout: 5000 });
      await page.locator('#daily-root button:has-text("Earlier")').click();
      await page.waitForFunction(() => /2013/.test(document.querySelector('#daily-root .dd-date').textContent), null, { timeout: 5000 });
      check(/s=ND/.test(await hash()) && /d=2013-/.test(await hash()) && /in North Dakota$/.test(await tableHead()), label + ': paging back keeps the chosen state');
      await page.goto(base + '?fresh=2#daily?d=2011-01-01&s=ND', { waitUntil: 'load' });
      await page.waitForFunction(() => /Jan 1, 2011/.test((document.querySelector('#daily-root .dd-date') || {}).textContent || ''), null, { timeout: 30000 });
      check(await page.locator('button[aria-label="The day before"]').isDisabled() && /in North Dakota$/.test(await tableHead()) && /Saturday, Jan 1, 2011/.test(await page.locator('#daily-root .dd-date').innerText()), label + ': an address with a day in 2011 opens on it with the arrow back switched off at the first day');
      check(!/\b(NaN|undefined|null|Infinity)\b/.test(await page.locator('#view-daily').innerText()), label + ': no NaN, undefined, null or Infinity on a day in 2011');
      // the strip of every month since 2011 (2026-11-02): a bar a month from the summary (no download), the chart's 150 days as a band, the chosen day as a line; a click on a month opens it,
      // a failed fetch of the earlier wells says so right there, and a state chosen redraws it
      await page.goto(base + '?fresh=3#daily', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .dd-ychart', { timeout: 25000 });
      await page.waitForTimeout(300);
      const sumDoc = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'newwells', 'summary.json'), 'utf8'));
      const strip = () => page.evaluate(() => {
        const g = document.querySelector('#daily-root .dd-ychart'); const w = g.querySelector('.dd-ywin'); const d = g.querySelector('.dd-yday'); const box = document.querySelector('#daily-root .dd-years'); const t = [...g.querySelectorAll('text.ax')].map((n) => n.textContent);
        return { hits: g.querySelectorAll('.nat-hit').length, W: +g.getAttribute('width'), x: +w.getAttribute('x'), w: +w.getAttribute('width'), dx: +d.getAttribute('x1'), fits: box.scrollWidth <= box.clientWidth + 1, top: t[0], years: t.filter((x) => /^20\d\d$/.test(x)) };
      });
      const s0 = await strip();
      check(s0.hits === sumDoc.months.length && s0.hits > 180 && s0.years[0] === '2011' && s0.fits && s0.x + s0.w > s0.W * 0.9 && s0.dx >= s0.x - 1 && s0.dx <= s0.x + s0.w + 1 && /^Every month since Jan 2011, all states/.test(await page.locator('#daily-root .dd-ycap').innerText()),
        label + ': the chart card opens with a bar for every month since 2011 (' + s0.hits + '), labeled from 2011, fitting the card, with the chart\'s days as a band at the newest end and the day inside it');
      const errsStrip = errs.length;
      await page.route('**/newwells/points-history.json', (r) => r.abort());
      await page.locator('#daily-root .dd-ychart .nat-hit').nth(26).click();
      await page.waitForFunction(() => /Could not load the earlier wells/.test((document.querySelector('#daily-root .dd-yearsbox .nw-status') || {}).textContent || ''), null, { timeout: 15000 });
      check((await page.locator('#daily-root .dd-date').innerText()) === newestDay, label + ': a click on a month that cannot be loaded says so above the strip, where the click was, and the day stays');
      await page.unroute('**/newwells/points-history.json');
      errs.splice(errsStrip);
      await page.locator('#daily-root .dd-ychart .nat-hit').nth(26).click();
      await page.waitForFunction(() => /Mar 1, 2013/.test(document.querySelector('#daily-root .dd-date').textContent), null, { timeout: 30000 });
      await page.waitForTimeout(300);
      const s1 = await strip();
      check(/d=2013-03-01/.test(await hash()) && /^The 150 days from /.test(await title()) && s1.hits === s0.hits && s1.x < s0.x - 100 && s1.dx >= s1.x && s1.dx <= s1.x + s1.w && s1.fits,
        label + ': a click on March 2013 loads the earlier wells and opens Mar 1, 2013; the band moved back to it and holds the day line (' + Math.round(s0.x) + ' to ' + Math.round(s1.x) + ')');
      await page.selectOption('#daily-root select.nw-pick', 'ND');
      await page.waitForFunction(() => /in North Dakota/.test((document.querySelector('#daily-root .dd-ycap') || {}).textContent || ''), null, { timeout: 5000 });
      const s2 = await strip();
      check(s2.hits === s0.hits && s2.top !== s1.top && s2.x === s1.x && s2.fits, label + ': choosing a state draws the strip again for that state alone, on its own scale (' + s1.top + ' to ' + s2.top + ') and with the band where it was');
      await page.locator('#daily-root .dd-ychart .nat-hit').nth(0).click();
      await page.waitForFunction(() => /Jan 1, 2011/.test(document.querySelector('#daily-root .dd-date').textContent), null, { timeout: 5000 });
      const s3 = await strip();
      check(await page.locator('button[aria-label="The day before"]').isDisabled() && s3.x <= 41 && /s=ND/.test(await hash()) && /in North Dakota$/.test(await tableHead()), label + ': the first bar opens Jan 1, 2011 with the band at the start of the strip, and the state stays');
      check(/no usable GPS point/.test(await page.locator('#view-daily').innerText()) && !/\b(NaN|undefined|null|Infinity)\b/.test(await page.locator('#view-daily').innerText()), label + ': the page says that a few wells have no point, and shows no NaN, undefined, null or Infinity');
      // fracked wells and oil permits on one map (2026-11-01): a filled dot is a fracked well, a hollow ring is an oil permit or spud, a switch shows both or either, and every count agrees with the files
      await page.goto(base + '?debug&fresh=4#daily?d=2025-06-12', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .nw-marks', { timeout: 25000 });
      await page.waitForFunction(() => window.__dd && window.__dd.map && window.__dd.map.ready && window.__dd.map.drawnPermits > 0, null, { timeout: 15000 });
      const rd = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'data', f + '.json'), 'utf8'));
      const dayAt = (iso, t0) => Math.round((Date.parse(iso + 'T00:00:00Z') - Date.parse(t0 + 'T00:00:00Z')) / 864e5);
      const nw = rd('newwells/points'); const pfiles = ['permits', 'permits-ok', 'permits-nm', 'permits-fo'].map(rd);
      const wellsOn = (iso) => nw.d.filter((d) => d === dayAt(iso, nw.t0)).length;
      const permitsOn = (iso, last = 0) => pfiles.reduce((t, f) => t + f.pts.filter((r) => r[3] <= dayAt(iso, f.t0) && r[3] >= dayAt(iso, f.t0) - last).length, 0);
      const wW = wellsOn('2025-06-12'); const wP = permitsOn('2025-06-12'); const wWin = permitsOn('2025-06-12', 13);
      const bigs = await page.locator('#daily-root .nat-panel .nat-big').allInnerTexts();
      check(wW > 5 && wP > 5 && bigs.length === 2 && new RegExp('^' + wW + '\\s+new fracked wells?$').test(bigs[0].replace(/\s+/g, ' ').trim()) && new RegExp('^' + wP + '\\s+oil permits? and spuds? with a location|^' + wP + '\\s+oil permit or spud with a location').test(bigs[1].replace(/\s+/g, ' ').trim()),
        label + ': a day shows both counts, ' + wW + ' fracked wells and ' + wP + ' oil permits and spuds, the same as the files hold: ' + bigs.join(' | ').replace(/\s+/g, ' '));
      check(new RegExp('^' + wW + ' fracked wells? and ' + wP + ' oil permits? and spuds? on Jun 12, 2025$').test(await tableHead()) && (await page.locator('#daily-root .table-wrap.tall thead th').first().innerText()) === 'Kind', label + ': the table names both kinds and has a Kind column: ' + (await tableHead()));
      const marks = await page.locator('#daily-root .nw-marks li').allInnerTexts();
      const seg = await page.locator('#daily-root #ddk-both, #daily-root #ddk-wells, #daily-root #ddk-permits').evaluateAll((bs) => bs.map((b) => b.textContent + ':' + b.getAttribute('aria-pressed')));
      check(marks.length === 2 && /Fracked well/.test(marks[0]) && /Oil permit or spud/.test(marks[1]) && seg.join(',') === 'Both:true,Fracked wells:false,Oil permits:false', label + ': the legend names the two marks (a dot and a ring) and the switch offers Both, Fracked wells and Oil permits: ' + seg.join(', '));
      const mapNow = () => page.evaluate(() => ({ kinds: window.__dd.map.kinds, count: window.__dd.map.permitCount(), drawn: window.__dd.map.drawnPermits, pulsing: window.__dd.map.pulsing }));
      const m0 = await mapNow();
      check(m0.kinds.wells && m0.kinds.permits && m0.count === wWin && m0.drawn > 0 && m0.drawn <= m0.count && m0.pulsing === 0, label + ': the map holds the ' + wWin + ' permits and spuds of the two weeks to that day, has painted rings for ' + m0.drawn + ' of them (the offshore\'s may lie off the frame) and pulses nothing beside them');
      await page.click('#ddk-wells');
      const m1 = await mapNow(); const bigs1 = await page.locator('#daily-root .nat-panel .nat-big').allInnerTexts();
      check(!m1.kinds.permits && m1.drawn === 0 && m1.pulsing > 0 && bigs1.length === 1 && /fracked well/.test(bigs1[0]) && /k=wells/.test(await hash()) && !/oil permit/.test(await tableHead()), label + ': "Fracked wells" draws no ring, shows one count and writes k=wells in the address');
      await page.click('#ddk-permits');
      const m2 = await mapNow(); const bigs2 = await page.locator('#daily-root .nat-panel .nat-big').allInnerTexts();
      const kindCells = await page.evaluate(() => [...document.querySelectorAll('#daily-root .table-wrap.tall tbody tr td:first-child')].map((t) => t.textContent));
      check(!m2.kinds.wells && m2.drawn > 0 && bigs2.length === 1 && /oil permit/.test(bigs2[0]) && !(await page.locator('#daily-root .nat-panel .badge').count()) && /k=permits/.test(await hash()) && kindCells.length === wP && kindCells.every((k) => /^(Permit approved|Well spudded)$/.test(k)),
        label + ': "Oil permits" draws only rings, shows one count, drops the "still filling in" badge (permits are not disclosed late) and lists ' + kindCells.length + ' permits and spuds');
      // a ring answers a hover with its own words, and never an API number
      const ring = await page.evaluate(() => { const { map, dt, D } = window.__dd; const day = D.dayOfIso(dt.P, '2025-06-12'); for (let j = 0; j < dt.Q.n; j++) if (dt.Q.day[j] === day) { const [x, y] = map.screenOfQ(j); return { x, y, state: dt.Q.states[dt.Q.s[j]] }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
      const boxR = await page.locator('.nw-canvas').boundingBox();
      if (ring) { await page.mouse.move(boxR.x + ring.x - 12, boxR.y + ring.y - 12); await page.mouse.move(boxR.x + ring.x, boxR.y + ring.y); await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 }); }
      const tipR = ring ? await page.locator('.tip').innerText() : '';
      check(!!ring && /Oil (permit approved|well spudded) · /.test(tipR) && /(May|Jun) \d+, 2025/.test(tipR) && !/\d{10}/.test(tipR), label + ': hovering a ring says what it is, its state, its day and its operator, with no API number: ' + tipR.replace(/\s+/g, ' ').slice(0, 110));
      // the address: a day opened with k=permits comes up showing permits only, and k=wells wells only
      await page.goto(base + '?debug&fresh=5#daily?d=2025-06-12&k=permits', { waitUntil: 'load' });
      await page.waitForSelector('#daily-root .nw-marks', { timeout: 25000 });
      await page.waitForFunction(() => window.__dd && window.__dd.map && !window.__dd.map.kinds.wells, null, { timeout: 10000 });
      check((await page.locator('#ddk-permits').getAttribute('aria-pressed')) === 'true' && /k=permits/.test(await hash()), label + ': an address with k=permits opens on the permits only, with that button pressed');
      // not available is not zero: before the records start, and for a state that publishes no location
      await page.goto(base + '?debug&fresh=6#daily?d=2023-05-10', { waitUntil: 'load' });
      await page.waitForFunction(() => /May 10, 2023/.test((document.querySelector('#daily-root .dd-date') || {}).textContent || ''), null, { timeout: 30000 });
      const early = await page.locator('#daily-root .nat-panel').innerText();
      check(/Oil permit and spud locations start on \w+ \d+, 2024/.test(early) && !/oil permits and spuds with a location/.test(early) && new RegExp('^[\\d,]+ fracked wells? on May 10, 2023$').test(await tableHead()),
        label + ': a day before the permit records says they start later, and shows no count of none');
      await page.goto(base + '?debug&fresh=7#daily?d=2025-06-12&s=ND', { waitUntil: 'load' });
      await page.waitForFunction(() => /in North Dakota$/.test((document.querySelector('#dd-table-h') || {}).textContent || ''), null, { timeout: 30000 });
      const nd = await page.locator('#daily-root .nat-panel').innerText();
      check(/North Dakota publishes no oil permit locations/.test(nd) && !/oil permits and spuds with a location/.test(nd) && !/oil permit/.test(await tableHead()), label + ': a state that publishes no location says so instead of showing none');
      // fractured wells found and oil well permits approved, day by day, marked and never added (2026-11-02)
      const readIdx = (d) => JSON.parse(fs.readFileSync(path.join(ROOT, 'data', d, 'index.json'), 'utf8')).days;
      const idxTx = readIdx('daily'); const newestIdx = idxTx[idxTx.length - 1].d;
      const oilOf = (d) => ['daily', 'daily-ok', 'daily-nm'].map((dir) => { const e = readIdx(dir).find((x) => x.d === d && x.s === 'ok'); return e ? e.pn : 0; });
      const arrCard = page.locator('section[aria-labelledby="dd-arr-h"]');
      await page.goto(base + '?fresh=8#daily', { waitUntil: 'load' });
      await page.waitForSelector('#dd-arr-h', { timeout: 25000 });
      const baseText = await arrCard.innerText();
      const committed = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'newwells', 'arrivals.json'), 'utf8'));
      check((await arrCard.locator('.mk-frac').count()) >= 2 && (await arrCard.locator('.mk-oil').count()) >= 2 && (await arrCard.locator('.mk-both').count()) >= 2 && /Fractured wells found \(FracFocus\)/.test(baseText) && /Oil well permits approved \(state agencies\)/.test(baseText),
        label + ': the card marks which is which: a filled dot for fractured wells (FracFocus), a hollow ring for oil well permits (state agencies), a ring with a dot for the same well in both');
      const firstRow = (await arrCard.locator('tbody tr').first().innerText()).replace(/\s+/g, ' ');
      check(committed.since ? true : (/begins with the next download/.test(baseText) && (await arrCard.locator('tbody tr td:nth-child(2)').allInnerTexts()).every((x) => x.trim() === '—') && !/\b(NaN|undefined|null|Infinity)\b/.test(baseText)),
        label + ': before the first comparison no day is counted: the fractured column is a dash (never a zero), and the card says the comparison begins with the next download');
      check(/different things/.test(baseText) && /never added together/.test(baseText) && /cannot be checked against them/.test(baseText) && !/\d{10}/.test(baseText), label + ': it says the two are never added, that Oklahoma and New Mexico cannot be checked, and holds no API number');
      const fixture = { v: 1, checked: newestIdx, since: newestIdx, against: { TX: { wells: 83, from: '2026-10-30' } }, days: [{ day: newestIdx, found: 41, removed: 1, states: [['TX', 25, 3], ['NM', 9, null], ['OK', 5, null], ['ND', 2, null]] }] };
      await page.route('**/newwells/arrivals.json', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(fixture) }));
      await page.goto(base + '?fresh=9#daily', { waitUntil: 'load' });
      await page.waitForSelector('#dd-arr-h', { timeout: 25000 });
      const cells = await arrCard.locator('tbody tr').first().locator('th, td').allInnerTexts();
      const oil = oilOf(newestIdx); const rows2 = await arrCard.locator('tbody tr').allInnerTexts();
      check(/^41/.test(cells[1].trim()) && /Texas 25/.test(cells[1]) && /North Dakota 2/.test(cells[1]) && cells[2].trim().startsWith(String(oil[0] + oil[1] + oil[2])) && cells[3].trim() === '3', label + ': a day with a comparison shows the 41 fractured wells found, the ' + (oil[0] + oil[1] + oil[2]) + ' oil well permits the three state reports approved, and the 3 wells in both, side by side: ' + cells.join(' | ').replace(/\s+/g, ' ').slice(0, 140));
      check(/^—/.test(rows2[1].split('\t')[1] || '—') && /Texas’s daily reports are matched by API number \(83 wells, from Oct 30, 2026\)/.test(await arrCard.innerText()), label + ': the day before the comparison has a dash, not a zero, and the card says what the Texas match covers (83 wells, from Oct 30)');
      await page.unroute('**/newwells/arrivals.json');
    } catch (e) {
      check(false, label + ': the national Daily report: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, label + ': the national Daily report loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 23. a change from a small base is not a percent (2026-11-01): California went from 2 permits to 372, which read "+18500%" in its panel; the panel says the base in words, and no tile or row shows the percent
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    try {
      await page.goto(base + '#national?s=CA', { waitUntil: 'load' });
      await page.waitForSelector('#national-root .nat-panel .nat-big', { timeout: 25000 });
      const big = await page.locator('#national-root .nat-panel .nat-big').innerText();
      check(!/\+\s?\d{3,}\s?%/.test(big) && /\(\d[\d,]* the 12 months before\)/.test(big), 'California\'s panel gives its base in words and no percent from a base under 20: ' + big.replace(/\s+/g, ' ').slice(0, 120));
      const rows = await page.evaluate(() => [...document.querySelectorAll('#national-root .nat-row')].map((r) => r.innerText).filter((t) => /\+\d{4,}%/.test(t)));
      check(rows.length === 0, 'no ranking row shows a percent over a thousand: ' + rows.join(' | ').slice(0, 120));
    } catch (e) {
      check(false, 'a change from a small base: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the California panel loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 22. the Companies table's Segment cell is a table cell (its class once collided with the segmented control's, which made each one a pill)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#companies?st=tx', { waitUntil: 'load' });
      await page.waitForSelector('#co-root td.segcell', { timeout: 25000 });
      check(await page.evaluate(() => getComputedStyle(document.querySelector('#co-root td.segcell')).display === 'table-cell'), 'the Companies table\'s Segment column is plain table cells, not the segmented control\'s pills');
    } catch (e) {
      check(false, 'the Companies segment cell: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  await browser.close();
  server.close();
  console.log('\n' + (failures ? 'FAILED ' + failures : 'all passed'));
  process.exit(failures ? 1 : 0);
})();
