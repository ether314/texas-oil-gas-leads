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

// the committed files the Overview is built from, read here so its checks compare the page with the data and not with itself
const NAT = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'national.json'), 'utf8')); // the state agencies' oil permits (each agency's own count)
const SUM = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'newwells', 'summary.json'), 'utf8')); // FracFocus's registry: the fractured wells
const FED = new Set(['BL']); // the BLM's federal-land permits overlap the states' own: shown apart, never added to them
const natOf = (id) => NAT.states.find((s) => s.id === id) || null;
const regOf = (id) => SUM.states.find((s) => s.id === id) || null;
const sumOf = (measure) => NAT.states.filter((s) => s.measure === measure && !FED.has(s.id)).reduce((t, s) => t + s.p12, 0);
const PERMITS_N = sumOf('permits'); const SPUDS_N = sumOf('spuds'); const BLM_N = natOf('BL').p12; // the agencies' counts, each within its own measure
const FRAC_N = SUM.states.reduce((t, s) => t + s.p12, 0); // the registry's wells of the last 12 settled months
const RING_STATES = NAT.states.filter((s) => !FED.has(s.id) && s.p12 > 0); // one ring each on the map (the BLM is not a place; a state with none dated in 24 months has none)
const nameOf = (id) => (natOf(id) || (NAT.gaps.find((g) => g.id === id)) || regOf(id) || {}).name;
// the totals that would add the two layers (or two measures) together: no element of the page may show one
const SUMS = [PERMITS_N + FRAC_N, PERMITS_N + SPUDS_N, PERMITS_N + SPUDS_N + FRAC_N, SPUDS_N + FRAC_N, PERMITS_N + BLM_N, PERMITS_N + SPUDS_N + BLM_N, PERMITS_N + FRAC_N + BLM_N];
const num = (n) => n.toLocaleString('en-US');
const hasNum = (text, n) => new RegExp('(?<![\\d,.])' + num(n).replace(/,/g, '\\,') + '(?![\\d,]|\\.\\d)').test(text); // the figure as its own number, not inside a longer one
const BAD_TEXT = /\b(NaN|undefined|null)\b|\bInfinity\b(?! [A-Z])/; // a value that leaked into a sentence ("Infinity Natural Resources" is an Ohio operator, not a leak)
// the counts the Overview is checked against (the committed files again, not the page)
const BOTH_N = NAT.states.filter((s) => !FED.has(s.id) && !(s.p12 === 0 && s.prev12 === 0) && (regOf(s.id) || {}).p12 > 0).length; // jurisdictions with a count of permits and a fractured well
const WITH_P = NAT.states.filter((s) => !FED.has(s.id) && !(s.p12 === 0 && s.prev12 === 0)).length; // jurisdictions with a count of permits dated in 24 months
const AGENCIES = NAT.states.filter((s) => s.measure === 'permits' && !FED.has(s.id)).length; const SPUD_AGENCIES = NAT.states.filter((s) => s.measure === 'spuds').length;
const ASOF = new Date(SUM.asOf + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }); // the registry's newest job, as the first figure writes it
// what a canvas shows: copied to a scratch canvas first (reading the page's own canvas again and again makes the browser warn, and a warning is a failure here)
const PX = (page, sel) => page.evaluate((q) => { // samples of ink
  const c = document.querySelector(q); const t = document.createElement('canvas'); t.width = c.width; t.height = c.height; const g = t.getContext('2d', { willReadFrequently: true }); g.drawImage(c, 0, 0);
  const d = g.getImageData(0, 0, t.width, t.height).data; let n = 0; for (let i = 3; i < d.length; i += 16) if (d[i] > 40) n++; return n;
}, sel);
const SNAP = (page, sel, key) => page.evaluate(([q, k]) => { // keeps what the canvas shows now under a name
  const c = document.querySelector(q); const t = document.createElement('canvas'); t.width = c.width; t.height = c.height; const g = t.getContext('2d', { willReadFrequently: true }); g.drawImage(c, 0, 0);
  (window.__snaps = window.__snaps || {})[k] = new Uint8ClampedArray(g.getImageData(0, 0, t.width, t.height).data);
}, [sel, key]);
const SNAPDIFF = (page, a, b) => page.evaluate(([x, y]) => { // the samples that differ between two kept snapshots
  const A = window.__snaps[x]; const B = window.__snaps[y]; let n = 0;
  for (let i = 0; i < A.length; i += 16) if (Math.abs(A[i] - B[i]) > 24 || Math.abs(A[i + 1] - B[i + 1]) > 24 || Math.abs(A[i + 2] - B[i + 2]) > 24 || Math.abs(A[i + 3] - B[i + 3]) > 24) n++;
  return n;
}, [a, b]);

// [hash, a selector that appears once the view has drawn, an optional extra check]
const OV_PANEL = '.nw-grid .nat-panel h3';
const hashNow = (page) => page.evaluate(() => location.hash);
const VIEWS = [
  ['#overview', '#kpis > *', async (page) => ((await page.locator('#kpis .kpi-chip').count()) === 4 && (await page.locator('.ov-row').count()) === 34 && (await page.locator('.nav a[href="#map"], .nav a[href="#national"]').count()) === 0 ? null : 'the Overview is one page: four figures, a ranking row for each of the 34 jurisdictions with a record, and no Map or National tab')],
  ['#overview?s=TX', OV_PANEL, async (page) => (/^Texas$/.test(await page.locator(OV_PANEL).first().innerText()) && /s=TX/.test(await hashNow(page)) ? null : 'an address naming Texas should zoom the explorer to it')],
  ['#overview?y=all', OV_PANEL, async (page) => ((await page.locator('#nwy-all').getAttribute('aria-pressed')) === 'true' ? null : 'an address with y=all should open every year since 2011')],
  ['#overview?s=IL', OV_PANEL, async (page) => (/^Illinois$/.test(await page.locator(OV_PANEL).first().innerText()) && /None in the last 12 months/.test(await page.locator('.nw-grid .nat-panel').innerText()) ? null : 'Illinois has permits and no fractured well: its panel should say "None in the last 12 months"')],
  ['#overview?s=FO', OV_PANEL, async (page) => (/^Federal offshore$/.test(await page.locator(OV_PANEL).first().innerText()) && /Not in the registry/.test(await page.locator('.nw-grid .nat-panel').innerText()) ? null : 'the federal offshore is not in the registry and its panel should say so')],
  ['#overview?s=BL', OV_PANEL, async (page) => (/^Federal onshore \(BLM\)$/.test(await page.locator(OV_PANEL).first().innerText()) ? null : 'an address naming the BLM should open its panel')],
  ['#overview?s=MO', OV_PANEL, async (page) => (/^Missouri$/.test(await page.locator(OV_PANEL).first().innerText()) && /never as zero/.test(await page.locator('.nw-grid .nat-panel').innerText()) ? null : 'Missouri has no source: its panel should say it is not available, never as zero')],
  ['#overview?k=permits', OV_PANEL, async (page) => ((await page.locator('#nwk-permits').getAttribute('aria-pressed')) === 'true' && (await page.locator('.nw-explore .card-tools .btn').isDisabled()) ? null : 'an address with k=permits should show the rings alone and switch the replay off')],
  ['#companies?s=FO', '#ops-root table'],
  ['#companies', '#ops-root table'],
  ['#operators?st=fo', '#ops-root table', async (page) => (/^#companies\?s=FO/.test(await page.evaluate(() => location.hash)) ? null : 'an old #operators link should open the Companies page on that state')],
  ['#daily', '#daily-root .dd-nav', async (page) => ((await page.locator('#daily-root .dd-nav').count()) === 1 && !(await page.locator('#statebar').isVisible()) ? null : 'the Daily report should be national: a day control and no states bar')],
  ['#daily?d=2026-02-02&s=TX', '#daily-root .dd-nav', async (page) => (/Monday, Feb 2, 2026/.test(await page.locator('#daily-root .dd-date').innerText()) && /in Texas/.test(await page.locator('#dd-table-h').innerText()) ? null : 'an address naming a day and Texas should open on them')],
  ['#oklahoma', '#daily-root .dd-nav', async (page) => (/s=OK/.test(await page.evaluate(() => location.hash)) ? null : 'an old #oklahoma link should open the Daily report on Oklahoma\'s wells')],
  ['#operators?top=1', '#ops-root table tbody tr', async (page) => { await page.waitForFunction(() => /top=1/.test(location.hash), null, { timeout: 5000 }).catch(() => {}); const h = await page.evaluate(() => location.hash); return /s=TX/.test(h) && /top=1/.test(h) && (await page.locator('#ops-root label.check', { hasText: 'Top producers' }).locator('input').isChecked()) && /^[\d,]+ of [\d,]+ rows match\. Top 100 by oil/.test(await page.locator('#ops-root .status').innerText()) ? null : 'an old #operators?top=1 link should open the operators on Texas with Top producers on, not lose the filter: ' + h; }],
  ['#companies?s=XX', '#ops-root table tbody tr', async (page) => (/^#companies$/.test(await page.evaluate(() => location.hash)) ? null : 'a state that is not one should leave the list on all states and out of the address')],
  ['#companies?kind=directory', '#co-root table'],
  ['#about', '#view-about h1'],
  ['#images', '#images-root .img-stage', async (page) => ((await page.locator('#images-root .img-stage').count()) === 3 ? null : 'the images view should show the three stages of a well')],
  ['#images?d=2026-10-30', '#images-root .img-pack', async (page) => ((await page.locator('#images-root .img-pack').count()) === 3 ? null : 'a day should show its three packs')],
  ['#fields', '#fields-root button.fx-c', async (page) => ((await page.locator('#fields-root tr[data-m]').count()) === 48 ? null : 'the matrix should have a row for each of the 48 metrics')],
  ['#fields?s=BL&g=when', '#fields-root .nat-panel h3', async (page) => (/Federal onshore/.test(await page.locator('#fields-root .nat-panel h3').first().innerText()) && (await page.locator('#fields-root tr[data-m]').count()) === 6 ? null : 'an address naming an agency and a group should open its panel and filter the rows')],
  // the National report and the Map were tabs of their own: their old addresses open the Overview, on the state they named (and the address says so)
  ['#national', OV_PANEL, async (page) => (/^#overview$/.test(await hashNow(page)) && /^All states$/.test(await page.locator(OV_PANEL).first().innerText()) ? null : 'an old #national link should open the Overview: ' + (await hashNow(page)))],
  ['#national?s=NM&m=spuds', OV_PANEL, async (page) => (/^#overview\?s=NM$/.test(await hashNow(page)) && /^New Mexico$/.test(await page.locator(OV_PANEL).first().innerText()) ? null : 'an old #national?s=NM&m=spuds link should open the Overview on New Mexico: ' + (await hashNow(page)))],
  ['#map', OV_PANEL, async (page) => (/^#overview$/.test(await hashNow(page)) ? null : 'an old #map link should open the Overview: ' + (await hashNow(page)))],
  ['#map?st=fo', OV_PANEL, async (page) => (/^#overview\?s=FO$/.test(await hashNow(page)) && /^Federal offshore$/.test(await page.locator(OV_PANEL).first().innerText()) ? null : 'an old #map?st=fo link should open the Overview on the federal offshore: ' + (await hashNow(page)))],
  ['#map?st=tx,ok', OV_PANEL, async (page) => (/^#overview$/.test(await hashNow(page)) && /^All states$/.test(await page.locator(OV_PANEL).first().innerText()) ? null : 'an old #map link naming two states should open the Overview on all of them: ' + (await hashNow(page)))],
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

  // 3. no view has a states bar any more (the Map, the last one that followed it, is part of the Overview); the Companies page is national and has a State filter of its own, kept in the address
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const hash = () => page.evaluate(() => location.hash);
    try {
      // no view has a states bar any more (the Map was the last one that followed it): the Overview, the Daily report, the permit-data matrix, the Texas images, Sources and Companies are national
      for (const [v, ready] of [['#overview', '.nw-canvas'], ['#daily', '#daily-root .dd-nav'], ['#fields', '#fields-root button.fx-c'], ['#images', '#images-root .img-stage'], ['#about', '#view-about h1'], ['#companies', '#ops-root tbody tr']]) {
        await page.goto(base + v, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        check((await page.locator('#statebar, #statebar-seg').count()) === 0, 'the ' + v.slice(1) + ' view is national: there is no states bar in the page');
      }
      // Companies: the operators of every state that names them, with a State filter of its own
      await page.click('.nav a[href="#companies"]');
      await page.waitForSelector('#ops-root tbody tr', { timeout: 25000 });
      check(!/st=/.test(await hash()) && (await page.locator('#ops-root tbody tr .st-tag').first().isVisible()), 'Companies is national: no st in the address, the State column showing');
      const stateSel = page.locator('#ops-root .field:has(> .field-label:text-is("State")) select');
      const stateOpts = await stateSel.locator('option').allInnerTexts();
      check(stateOpts[0] === 'All states' && stateOpts.length >= 28 && ['Texas', 'Oklahoma', 'New Mexico', 'Federal offshore', 'North Dakota', 'Utah', 'Pennsylvania', 'Colorado', 'Alaska'].every((n) => stateOpts.includes(n)) && !stateOpts.includes('Arizona'),
        'the State filter lists every state that names operators (' + stateOpts.length + ' choices) and no state that names none: ' + stateOpts.slice(0, 6).join(', ') + '...');
      const heads = async () => (await page.locator('#ops-root thead th:not([hidden])').allInnerTexts()).map((t) => t.trim());
      const allHeads = await heads();
      check(allHeads.includes('State') && allHeads.includes('Last permit or spud') && allHeads.includes('Top county or area') && !(await page.locator('#ops-root label.check', { hasText: 'Top producers' }).isVisible()) && !(await page.locator('#ops-root label.check', { hasText: 'New P-5' }).isVisible()),
        'all states: the State column, the date and the place named for permits or spuds and counties or areas, and the filters only Texas\'s records can answer hidden: ' + allHeads.slice(0, 9).join(' | '));
      const tags = await page.locator('#ops-root tbody tr .st-tag').evaluateAll((els) => els.map((e) => e.textContent));
      check(tags.includes('TX') && tags.includes('NM') && tags.includes('UT') && tags.includes('ND'), 'one ranking, the busiest operators of every state in the first rows (Texas, New Mexico, Utah and North Dakota among them): ' + [...new Set(tags)].join(','));
      const units = await page.locator('#ops-root tbody tr .cnt .unit').evaluateAll((els) => [...new Set(els.map((e) => e.textContent.trim()))]);
      check(units.includes('spuds'), 'a count of wells spudded says "spuds" beside the number; a permit count is a bare number: ' + units.join(','));
      await stateSel.selectOption({ label: 'Oklahoma' });
      await page.waitForFunction(() => /Oklahoma Corporation Commission/.test(document.querySelector('#ops-root .status').textContent), null, { timeout: 10000 });
      const okHeads = await heads();
      check(/s=OK/.test(await hash()) && !(await page.locator('#ops-root tbody tr .st-tag').first().isVisible()) && okHeads.includes('Location') && okHeads.includes('Last permit') && okHeads.includes('Top county') && !okHeads.includes('Spud (12 mo)') && !okHeads.includes('District') && !okHeads.includes('State'),
        'Oklahoma alone: s=OK in the address, no State column, no column of blanks (no Spud, no District), "Last permit" and "Top county": ' + okHeads.join(' | '));
      check(/counted by new-drill permits; data runs through [A-Z][a-z]{2} \d+, 2026\./.test(await page.locator('#ops-root .status').innerText()), 'and the line under the table says whose figures these are, what they count and how far Oklahoma\'s own data runs');
      await stateSel.selectOption({ label: 'New Mexico' });
      await page.waitForFunction(() => /Aug 31/.test(document.querySelector('#ops-root .status').textContent), null, { timeout: 10000 });
      const nmHeads = await heads();
      check(!nmHeads.includes('Location') && !nmHeads.includes('Permits (12 mo)') && !nmHeads.includes('Spud (12 mo)') && nmHeads.includes('Top county') && nmHeads.includes('Last spud'), 'New Mexico alone: no Location (no addresses), no permit counts (it counts spuds), no Spud column; its own end date under the table');
      await stateSel.selectOption({ label: 'North Dakota' });
      await page.waitForFunction(() => /North Dakota Industrial Commission/.test(document.querySelector('#ops-root .status').textContent), null, { timeout: 10000 });
      const ndHeads = await heads(); const ndRows = await page.locator('#ops-root tbody tr').count();
      check(ndRows === 15 && ndHeads.join('|') === 'Band|Operator|New wells (12 mo)' && /15 busiest operators are listed/.test(await page.locator('#ops-root .status').innerText()),
        'a state with only the 15 busiest listed (North Dakota): 15 rows, only the columns it can fill (band, operator, new wells), and the line says it is the 15 busiest: ' + ndHeads.join(' | '));
      await stateSel.selectOption({ label: 'Texas' });
      await page.waitForFunction(() => [...document.querySelectorAll('#ops-root label.check')].some((l) => /Top producers/.test(l.textContent) && !l.hidden), null, { timeout: 10000 });
      check((await page.locator('#ops-root label.check', { hasText: 'Top producers' }).isVisible()) && (await page.locator('#ops-root label.check', { hasText: 'New P-5' }).isVisible()), 'Texas alone brings back the filters only its registrations can answer');
      await stateSel.selectOption({ label: 'All states' });
      await page.waitForFunction(() => !/s=/.test(location.hash) || /s=all/.test(location.hash), null, { timeout: 10000 });
      check(!/s=/.test(await hash()), 'choosing All states leaves s out of the address');
      // the two lists behind one switch: the search carries over, the address names the list, the other list is Texas only and says so
      await page.fill('#ops-root input[type="search"]', 'pioneer');
      await page.waitForTimeout(400);
      await page.click('#cok-directory');
      await page.waitForSelector('#co-root tbody tr', { timeout: 25000 });
      check(!(await page.locator('#ops-root').isVisible()) && (await page.locator('#co-root').isVisible()) && /kind=directory/.test(await hash()) && (await page.locator('#co-root input[type="search"]').inputValue()) === 'pioneer' && /Texas only/.test(await page.locator('#co-note').innerText()),
        'the Texas directory is the other half of the page: the switch shows it, the address says kind=directory, what was typed in the search carries over, and the note says it is Texas only');
      await page.click('#cok-operators');
      await page.waitForSelector('#ops-root tbody tr', { timeout: 25000 });
      check((await page.locator('#ops-root').isVisible()) && !/kind=/.test(await hash()) && (await page.locator('#ops-root input[type="search"]').inputValue()) === 'pioneer', 'and back: the operators, no kind in the address, the search kept');
      await page.click('.nav a[href="#about"]');
      await page.waitForSelector('#view-about h1', { timeout: 25000 });
      check(!/st=/.test(await hash()), 'Sources has no state in its address');
    } catch (e) {
      check(false, 'the Companies page: ' + e.message.split('\n')[0].slice(0, 160));
    }
    check(!errs.length, 'the Companies page loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
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
      for (const v of ['#overview', '#fields', '#companies', '#daily', '#images', '#about']) {
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

  // 8. the Operators CSV for every state: a column that says which state, figures a state does not publish left blank (never zero), and a fall stays a number
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#companies?band=all', { waitUntil: 'load' });
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
      check(head[0] === 'data_state' && ['TX', 'OK', 'NM', 'FO', 'ND', 'UT', 'PA'].every((x) => states.has(x)) && states.size >= 27, 'the CSV says which state each row is, and holds every state that names operators (' + states.size + '): ' + [...states].sort().join(','));
      // a state that lists only its 15 busiest operators: what it counts is named, and what only a full file has is blank (never zero)
      const nd = table.slice(1).filter((r) => r[0] === 'ND'); const ut = table.slice(1).filter((r) => r[0] === 'UT');
      check(nd.length === 15 && nd.every((r) => r.length === head.length && r[col('counts_are_of')] === 'wells spudded' && r[col('all_permits_12m')] === '' && r[col('trend_pct_full_months')] === '' && r[col('top_county_24m')] === '' && Number(r[col('new_well_permits_12m')]) > 0)
        && ut.length > 0 && ut.every((r) => r[col('counts_are_of')] === 'new-drill permits'), 'North Dakota\'s 15 rows say they count wells spudded and leave the trend and county blank, Utah\'s count permits (' + nd.length + ', ' + ut.length + ' rows)');
      // New Mexico publishes no all-kinds permit count: the cell is empty, not 0
      const nm = table.slice(1).filter((r) => r[0] === 'NM');
      check(nm.length > 0 && nm.every((r) => r.length === head.length && r[col('all_permits_12m')] === '' && r[col('all_permits_24m')] === ''), 'a figure New Mexico does not publish is blank in its rows, not zero (' + nm.length + ' rows)');
      check(!/(^|,)'-?\d/.test(text), 'no number was turned into text by the spreadsheet guard (a fall such as -14.4 has no apostrophe)');
      check(!head.includes('on_map'), 'the CSV has no on_map column: the Map tab it pointed to is gone (' + head.length + ' columns)');
    } catch (e) {
      check(false, 'the Operators CSV: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
  }

  // 13. a dropped connection is tried once more (a phone between towers): the Overview's first request for the national file (the agencies' counts) fails and it still draws; a missing file is not retried;
  //     a missing optional file (the permit-data matrix, which only adds a link) leaves the Overview whole; and a registry file that is really gone says so and throws nothing
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    let nationalAsks = 0; let missingAsks = 0;
    await ctx.route('**/data/national.json', (route) => { nationalAsks++; if (nationalAsks === 1) route.abort(); else route.continue(); });
    await ctx.route('**/data/daily-nm/1999-01-01.json', (route) => { missingAsks++; route.fulfill({ status: 404, body: 'not found' }); });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      check(nationalAsks === 2 && (await page.locator('.ov-row').count()) === 34, 'the Overview draws although its first request for the national file was dropped (it asked ' + nationalAsks + ' times)');
      const miss = await page.evaluate(async () => { const m = await import('./js/util.js'); const t0 = performance.now(); const r = await m.loadOpt('daily-nm/1999-01-01'); return { r, ms: Math.round(performance.now() - t0) }; });
      check(miss.r === null && missingAsks === 1 && miss.ms < 600, 'a missing file is asked for once and answered at once, not retried: ' + missingAsks + ' ask, ' + miss.ms + ' ms');
    } catch (e) {
      check(false, 'the retry of a dropped request: ' + e.message.split('\n')[0].slice(0, 200));
    }
    await ctx.close();
    // an optional file that is gone: the matrix adds a link to a state's panel and nothing else, so the page is whole without it
    {
      const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
      await ctx2.route('**/data/permit-fields.json', (route) => route.fulfill({ status: 404, body: 'not found' }));
      const p2 = await ctx2.newPage();
      const errs = [];
      p2.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
      p2.on('console', (m) => { if (m.type() === 'error' && !(m.location().url || '').endsWith('/permit-fields.json')) errs.push('console: ' + m.text().slice(0, 160)); }); // the browser reports the 404 the test made
      try {
        await p2.goto(base + '#overview?s=TX', { waitUntil: 'load' });
        await p2.waitForSelector('.ov-row', { timeout: 25000 });
        await p2.waitForTimeout(500);
        const tx = await p2.locator('.nw-grid .nat-panel').innerText();
        check((await p2.locator('.ov-row').count()) === 34 && /Texas/.test(tx) && /OIL PERMITS/i.test(tx) && /FRACTURED WELLS/i.test(tx) && !BAD_TEXT.test(tx), 'without the permit-data file the Overview still draws its panel with both layers (the matrix link is the only thing missing)');
        check((await p2.locator('.nw-grid .nat-panel a[href^="#fields"]').count()) === 0 && (await p2.locator('.nw-grid .nat-panel a[target="_blank"]').count()) >= 1, 'and the panel keeps its source links, never a link to a matrix that did not load');
      } catch (e) {
        check(false, 'the Overview without the permit-data file: ' + e.message.split('\n')[0].slice(0, 200));
      }
      check(!errs.length, 'the Overview without the permit-data file throws no error' + (errs.length ? ': ' + errs.join(' | ') : ''));
      await ctx2.close();
    }
    // a required file that is really gone (the registry's points): the page says so in words, in place of its figures, and throws nothing
    {
      const ctx3 = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
      await ctx3.route('**/data/newwells/points.json', (route) => route.abort());
      const p3 = await ctx3.newPage();
      const errs = [];
      p3.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
      try {
        await p3.goto(base + '#overview', { waitUntil: 'load' });
        await p3.waitForSelector('#kpis .empty', { timeout: 25000 });
        check(/Could not load the data/.test(await p3.locator('#kpis').innerText()) && !BAD_TEXT.test(await p3.locator('#view-overview').innerText()), 'a registry file that cannot be loaded says "Could not load the data" in place of the figures, with no NaN or null');
      } catch (e) {
        check(false, 'the Overview without the registry: ' + e.message.split('\n')[0].slice(0, 200));
      }
      check(!errs.length, 'the Overview without the registry throws no error' + (errs.length ? ': ' + errs.join(' | ') : ''));
      await ctx3.close();
    }
  }

  // 15. a button's words are one piece: a label split into two flex items ("Share" and "this view") gets the icon's gap between them, which reads as a double space
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    try {
      for (const v of ['#overview', '#companies', '#companies?kind=directory', '#daily', '#overview?s=TX', '#overview?k=permits']) {
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

  // 17. the federal offshore on the Companies page, at 360 px: areas where it has areas, wells spudded where it counts spuds, its operators named by the same rule
  {
    const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      // Companies: sixteen named corporations, a Top area column, no State column, no address, no permit counts
      await page.goto(base + '#companies?s=FO&band=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#ops-root table tbody tr', { timeout: 25000 });
      const heads = (await page.locator('#ops-root thead th:visible').allInnerTexts()).map((t) => t.trim());
      const rows = await page.locator('#ops-root tbody tr').count();
      check(rows === 16 && heads.includes('Top area') && !heads.includes('State') && !heads.includes('Top county') && !heads.includes('Location') && !heads.includes('Avg depth (ft)'), 'Companies with the offshore alone: 16 rows, "Top area", no State, Location or depth column: ' + rows + ' rows, ' + heads.join(' | '));
      check(/counted by wells spudded; data runs through Aug \d+, \d{4}/.test(await page.locator('#ops-root .status').innerText()), 'and the line under the table says what is counted and where the offshore\'s own data ends');
      check(/ A well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted\.$/.test(await page.locator('#ops-root .status').innerText()), 'and what a sidetrack is (an operator that sidetracks old wells ranks with none)');
      // what a band and the last-date column mean is said in the row's own measure: spuds, never permits
      const chipTitles = await page.locator('#ops-root tbody .chip').evaluateAll((els) => els.map((e) => e.title));
      check(chipTitles.length >= 16 && chipTitles.every((t) => /wells spudded/.test(t) && !/permit/i.test(t)) && chipTitles.some((t) => /^No wells spudded in the last 12 months, but some in the 12 before$/.test(t)) && heads.includes('Last spud') && !heads.includes('Last permit'),
        'the offshore\'s bands are described in wells spudded (band C had some in the 12 before) and the date column is "Last spud": ' + [...new Set(chipTitles)].join(' | ') + ' · ' + heads.filter((h) => /^Last/.test(h)).join());
      // the bands of the whole list say permits for Texas rows and spuds for the offshore's
      await page.goto(base + '#companies?band=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('#ops-root table tbody tr', { timeout: 25000 });
      const mixedHeads = (await page.locator('#ops-root thead th:visible').allInnerTexts()).map((t) => t.trim());
      const mixedTitles = new Set(await page.locator('#ops-root tbody .chip').evaluateAll((els) => els.map((e) => e.title)));
      check(mixedHeads.includes('Last permit or spud') && mixedTitles.has('10 or more new-well permits in the last 12 months') && mixedTitles.has('10 or more wells spudded in the last 12 months'), 'the whole list describes each row\'s band in its own measure and calls the date "Last permit or spud": ' + mixedHeads.filter((h) => /^Last/.test(h)).join());
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
      // FracFocus, the registry of fracturing jobs: the first column, counted apart from the 35 agencies, with a card listing every field in its download
      await page.goto(base + '#fields', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root button.fx-c', { timeout: 25000 });
      const ffm = await page.evaluate(() => ({
        heads: [...document.querySelectorAll('#fields-root th.fx-col button.fx-h')].map((b) => b.textContent), reg: document.querySelectorAll('#fields-root th.fx-col.is-reg').length,
        regCells: document.querySelectorAll('#fields-root td.fx-cell.is-reg').length, rows: document.querySelectorAll('#fields-root tr[data-m]').length,
        total: document.querySelector('#fields-root tr[data-m="api_number"] td.fx-n:last-child').textContent, score: document.querySelector('#fields-root tr.fx-score td.fx-n.is-reg').textContent,
        label: document.querySelector('#fields-root tr[data-m="water"] td.fx-cell.is-reg button').getAttribute('aria-label'), kpis: document.querySelector('#fields-root .nat-kpis').innerText.replace(/\s+/g, ' ') }));
      check(ffm.heads.length === 36 && ffm.heads[0] === 'FracFocus' && ffm.reg === 1 && ffm.regCells === ffm.rows && ffm.rows === 48, 'the matrix has FracFocus as its first column, a cell on each of the 48 rows, and 35 agencies after it: ' + ffm.heads.slice(0, 3).join(','));
      check(/^\d+ of 35$/.test(ffm.total) && ffm.score === '9' && /published as data/.test(ffm.label) && /Agencies compared 35/.test(ffm.kpis) && /What FracFocus adds 3 metrics/.test(ffm.kpis) && /Hydraulic fracturing plan 0 of 35/.test(ffm.kpis),
        'FracFocus is not counted as an agency (a row still totals "of 35"), its score is 9 metrics as data and the figures say what it adds: ' + ffm.total + ' / ' + ffm.score + ' / ' + ffm.kpis.slice(0, 200));
      await page.goto(base + '#fields?s=FF', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root .nat-panel', { timeout: 25000 });
      const ffp = await page.locator('#fields-root .fx-panel-slot').innerText();
      const ffHref = await page.locator('#fields-root .fx-panel-slot a.more-link:not([target])').first().getAttribute('href');
      check(/What a disclosure captures/i.test(ffp) && /The disclosure/i.test(ffp) && !/The permit form/i.test(ffp) && /one row a disclosure/.test(ffp) && /one well at a time/.test(ffp) && ffHref === '#overview', 'FracFocus\'s panel speaks of a disclosure, not a permit, says what each file holds and links to the map: ' + ffHref);
      const card = await page.evaluate(() => ({ groups: document.querySelectorAll('#fx-registry .fx-rg').length, rows: document.querySelectorAll('#fx-registry li.fx-rf').length, text: document.querySelector('#fx-registry').innerText,
        links: [...document.querySelectorAll('#fx-registry .fx-rf-link button')].length, sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
      check(card.groups === 5 && card.rows === 34 && /CASNumber/.test(card.text) && /TotalBaseWaterVolume/.test(card.text) && /JobStartDate/.test(card.text) && /1 of 35 agencies publish it as data/.test(card.text) && /Not one of the permit metrics/.test(card.text) && card.links >= 15 && !card.sideways,
        'the card lists the registry\'s 34 fields in five groups, the permit metric each matches with how many agencies publish it, and the page does not scroll sideways: ' + card.rows + ' rows');
      await page.click('#fx-registry .fx-rf-link button >> nth=0');
      await page.waitForTimeout(200);
      const mp = await page.locator('#fields-root .fx-panel-slot').innerText();
      check(/API well number/.test(mp) && /a registry counted apart/i.test(mp) && /FracFocus on/.test(mp) && /of 35 as data/.test(mp), 'a field\'s metric opens its panel, which counts the agencies and names FracFocus apart: ' + mp.replace(/\s+/g, ' ').slice(0, 160));
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


  // 19. the Overview (2026-11-02): what were three tabs (the Overview's wells map, the National report's state agencies, the Map's permit locations) is one page for the whole country with two layers
  //     in every visual: the state agencies' oil permits (a ring) and the registry's fractured wells (a dot), never added. The explorer draws, answers hover and click, replays, and says what it does not know
  for (const [label, w, h] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const pixels = (sel) => PX(page, sel);
    try {
      await page.goto(base + '?debug#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForTimeout(700);
      const kpis = (await page.locator('#kpis .kpi-chip').allInnerTexts()).map((t) => t.replace(/\s+/g, ' '));
      check(kpis.length === 4 && /^Oil permits approved, last 12 months/.test(kpis[0]) && hasNum(kpis[0], PERMITS_N) && new RegExp(AGENCIES + ' state agencies').test(kpis[0]) && new RegExp('plus ' + num(SPUDS_N) + ' wells spudded in ' + SPUD_AGENCIES + ' more').test(kpis[0]) && /never added to the wells/.test(kpis[0]),
        label + ': the first figure is the agencies\' oil permits (' + num(PERMITS_N) + ' by ' + AGENCIES + ' agencies, the wells spudded in ' + SPUD_AGENCIES + ' more named apart) and says it is never added to the wells: ' + kpis[0].slice(0, 150));
      check(/^Fractured wells, last 12 months/.test(kpis[1]) && hasNum(kpis[1], FRAC_N) && /settled months only/.test(kpis[1]), label + ': the second is the registry\'s fractured wells (' + num(FRAC_N) + '), settled months only: ' + kpis[1].slice(0, 120));
      check(new RegExp('^States with both ' + BOTH_N + ' ' + BOTH_N + ' ' + (WITH_P - BOTH_N) + ' more have oil permits only').test(kpis[2]) && new RegExp('^Newest fractured well ' + ASOF + ' permit files run to [A-Z][a-z]{2} \\d{4}').test(kpis[3]),
        label + ': the third counts the states with both layers (' + BOTH_N + ') and the ones with permits only (' + (WITH_P - BOTH_N) + '), the fourth gives the newest well and how far the permit files run: ' + kpis[2].slice(0, 70) + ' | ' + kpis[3].slice(0, 80));
      const text = await page.locator('#view-overview').innerText();
      check(!BAD_TEXT.test(text), label + ': no NaN, undefined, null or Infinity anywhere on the Overview');
      check(SUMS.every((n) => !hasNum(text, n)), label + ': no total of the two layers, or of two measures, appears anywhere on the Overview (' + SUMS.map(num).join(', ') + ')');
      check(!(await page.locator('#statebar').isVisible()) && !(await page.locator('#ticker, #insights, #pulse-card, #prod-card, #basins, #seg-chart, #map-root, #national-root, #view-map, #view-national, #nw-slot .nat-tile').count()), label + ': no states bar, none of the cards only Texas could fill (markets, insights, producers, basins, companies) and none of the Map and National tabs\' roots');
      const [heroPx, mapPx] = [await pixels('#hero-canvas'), await pixels('.nw-canvas')];
      check(heroPx > 300 && mapPx > 300, label + ': the hero\'s backdrop and the explorer\'s map are drawn (' + heroPx + ' and ' + mapPx + ' samples of ink)');
      const n = await page.evaluate(() => window.__nw.P.n);
      const sub = await page.locator('.nw-explore .sub').innerText();
      check(n > 15000 && /every state that reports to the registry/.test(sub) && /Each ring is a state agency’s count of oil permits/.test(sub), label + ': the explorer holds the wells of the last 24 months (' + n + ') and its heading says what a dot and a ring are');
      check(/All states/.test(await page.locator(OV_PANEL).first().innerText()) && !/s=/.test(await hashNow(page)), label + ': it starts on all states');
      // the ranking: one row for each jurisdiction with a record, two cells in each, and a state with a handful of wells shows no percentage
      const rows = await page.locator('.ov-row').count();
      const rank = await page.locator('.ov-row').first().innerText();
      const kyW = await page.locator('.ov-row', { hasText: 'Kentucky' }).locator('.ov-w').innerText();
      check(rows === 34 && /Texas/.test(rank) && /n\/a/.test(kyW) && !/%/.test(kyW), label + ': the ranking lists ' + rows + ' jurisdictions, Texas first, and a state with a handful of wells says n/a, not "-57%": ' + kyW.replace(/\s+/g, ' '));
      const note = await page.locator('#ranking .ov-rank > .fine').innerText();
      check(/Missouri has no permit list this site can read and no fractured well in the registry/.test(note) && /never added/.test(note) && /not a state with no drilling/.test(note), label + ': the ranking names the jurisdiction with neither source (Missouri), says the layers are never added and that no fractured well is not no drilling');
      // hover a dot: its tooltip names the county, the day and the operator, and never an API number or a lease
      const pt = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'TX' && P.o[i] >= 0) { const [x, y] = map.screenOf(i); return { x, y, i }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); // the pointer can only reach a dot that is on screen
      await page.waitForTimeout(300);
      const box = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(box.x + pt.x - 20, box.y + pt.y - 20); await page.mouse.move(box.x + pt.x, box.y + pt.y);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      const tip = await page.locator('.tip').innerText();
      check(/County, Texas|Texas/.test(tip) && /first fracturing job/.test(tip) && /operator/.test(tip) && !/\d{10}/.test(tip), label + ': hovering a dot names its county, its first job and its operator, no API number: ' + tip.replace(/\s+/g, ' ').slice(0, 120));
      // choose a state in the key: the panel, the address, the row, the selector and the leaders agree
      await page.locator('.nw-chip', { hasText: 'North Dakota' }).click();
      await page.waitForFunction(() => /^North Dakota$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      const nd = await page.locator('.nw-grid .nat-panel').innerText();
      const where = await page.locator('section[aria-labelledby="ov-where-h"]').innerText();
      check(/s=ND/.test(await hashNow(page)) && /OIL PERMITS/i.test(nd) && /FRACTURED WELLS/i.test(nd) && hasNum(nd, natOf('ND').p12) && hasNum(nd, regOf('ND').p12) && (await page.locator('.nw-pick').inputValue()) === 'ND' && (await page.locator('.ov-row[aria-current="true"]').innerText()).includes('North Dakota') && /Williams|McKenzie/.test(where),
        label + ': choosing North Dakota zooms the map, fills its panel with both counts (' + natOf('ND').p12 + ' spuds, ' + regOf('ND').p12 + ' fractured wells), writes s=ND in the address, marks its row and lists its counties');
      check((await page.locator('.nw-grid .nat-panel a[href="#fields?s=ND"]').count()) === 1 && /Source: FracFocus/.test(nd) && /Source: /.test(nd), label + ': the state\'s panel links to what its permit captures and to both sources');
      await page.selectOption('.nw-pick', 'TX');
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check((await page.locator('a[href^="#map"], a[href^="#national"]').count()) === 0, label + ': nothing on the page links to the Map or National tabs that are gone');
      await page.selectOption('.nw-pick', '');
      await page.waitForFunction(() => /All states/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check(!/s=/.test(await hashNow(page)), label + ': back to all states takes s out of the address');
      // the replay: with reduced motion only the scrubber, which moves the clock; the count only grows
      await page.click('#go-explore'); // the hero's button opens the replay under the map
      await page.waitForSelector('.tl-range', { state: 'visible', timeout: 5000 });
      check((await page.locator('.nw-explore .btn[aria-pressed="true"]').innerText()).includes('Close the replay') && (await page.locator('#explore').boundingBox()).y < 400, label + ': "Watch the wells" in the hero scrolls to the explorer and opens the replay');
      const total = await page.evaluate(() => window.__nw.map.tlCount(window.__nw.map.tlRange[1]));
      await page.locator('.tl-range').fill(String(Math.round(await page.evaluate(() => window.__nw.map.tlRange[1] / 2))));
      const half = await page.evaluate(() => window.__nw.map.tlCount(window.__nw.map.tlRange[1] / 2));
      check(half > 0 && half < total && /fractured wells so far/.test(await page.locator('.tl-count').innerText()) && !(await page.locator('.tl-play').count()), label + ': the replay (scrubber only with reduced motion) shows ' + half + ' of ' + total + ' wells at the halfway day');
      await page.locator('.nw-explore .btn[aria-pressed="true"]').click();
      check(!(await page.locator('.tl-bar').isVisible()) && (await page.locator('.nw-explore .card-tools .btn').innerText()).trim() === 'Watch 24 months', label + ': the replay closes again with the same button');
      // every year since 2011: the earlier wells are fetched when asked for; a failed request leaves the two years as they were; then the same explorer draws, replays and answers over all of them
      const nRecent = await page.evaluate(() => window.__nw.P.n);
      check((await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && (await page.locator('#nwy-all').innerText()) === 'Since 2011', label + ': the explorer offers "Last 2 years" (chosen) and "Since 2011"');
      const errsBefore = errs.length;
      let historyAsks = 0;
      await page.route('**/newwells/points-history.json', (r) => { historyAsks++; r.abort(); });
      await page.locator('#nwy-all').click();
      await page.waitForFunction(() => /Could not load the earlier wells/.test((document.querySelector('.nw-status') || {}).textContent || ''), null, { timeout: 15000 });
      check((await page.evaluate(() => window.__nw.P.n)) === nRecent && (await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && !(await page.locator('#nwy-recent').isDisabled()) && !(await page.locator('#nwy-all').isDisabled()), label + ': when the earlier wells cannot be loaded the map keeps the last two years, says so, and the choice stays open');
      await page.unroute('**/newwells/points-history.json');
      errs.splice(errsBefore); // the dropped requests above were the point of the check
      let historyOk = 0;
      await page.route('**/newwells/points-history.json', (r) => { historyOk++; r.continue(); });
      await page.locator('#nwy-all').click();
      await page.waitForFunction(() => window.__nw.P.n > 200000 && window.__nw.map.ready, null, { timeout: 30000 });
      await page.waitForTimeout(500);
      const nAll = await page.evaluate(() => window.__nw.P.n);
      const sub2 = await page.locator('.nw-explore .sub').innerText();
      check(nAll > nRecent * 8 && /first jobs from Jan 2011 to /.test(sub2) && (await page.locator('#nwy-all').getAttribute('aria-pressed')) === 'true' && (await page.evaluate(() => document.activeElement && document.activeElement.id)) === 'nwy-all',
        label + ': "Since 2011" draws every well with a point (' + nAll + ' against ' + nRecent + '), says so under the heading, and keeps the keyboard on the control: ' + sub2.slice(0, 90));
      check(historyAsks === 2 && historyOk === 1, label + ': the earlier wells are asked for once when chosen (the dropped request was tried again by the retry, then one real load: ' + historyAsks + ' dropped, ' + historyOk + ' real)');
      check((await pixels('.nw-canvas')) > 300 && /^Watch 1[5-9] years$/.test((await page.locator('.nw-explore .card-tools .btn').innerText()).trim()) && !BAD_TEXT.test(await page.locator('#view-overview').innerText()) && (await PX(page, '#hero-canvas')) > 300, label + ': the map is drawn over all of them, the replay button names its length, and no NaN anywhere');
      await page.selectOption('.nw-pick', 'TX');
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 5000 });
      check((await page.locator('.nw-grid .nat-panel svg.ov-dual').count()) === 1 && /Martin|Midland/.test(await page.locator('section[aria-labelledby="ov-where-h"]').innerText()) && hasNum(await page.locator('.nw-grid .nat-panel').innerText(), natOf('TX').p12), label + ': with every year a state\'s panel still draws both of its lines and its figures, and the leaders list its counties');
      const ptA = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'TX' && P.day[i] < 400) { const [x, y] = map.screenOf(i); return { x, y }; } return null; });
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
      const boxA = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(boxA.x + ptA.x - 15, boxA.y + ptA.y - 15); await page.mouse.move(boxA.x + ptA.x, boxA.y + ptA.y);
      await page.waitForSelector('.tip', { state: 'visible', timeout: 5000 });
      const tipA = await page.locator('.tip').innerText();
      check(/20(11|12)/.test(tipA) && /first fracturing job/.test(tipA) && !/\d{10}/.test(tipA), label + ': hovering a well from 2011 or 2012 answers like any other, with no API number: ' + tipA.replace(/\s+/g, ' ').slice(0, 100));
      await page.selectOption('.nw-pick', '');
      await page.locator('.nw-explore .card-tools .btn').click();
      await page.waitForSelector('.tl-range', { state: 'visible', timeout: 5000 });
      const ends = await page.locator('.tl-ends').innerText();
      check(/Jan 1, 2011/.test(ends) && (await page.evaluate(() => window.__nw.map.tlRange[1] > 5000 && window.__nw.map.tlCount(window.__nw.map.tlRange[1]) === window.__nw.P.n)), label + ': the replay runs from Jan 1, 2011 and ends with every well: ' + ends.replace(/\s+/g, ' '));
      // the month chart is the agencies' months (since 2019) against the registry's, one bar for each, and its "still filling in" label is inside the drawing
      const axisN = NAT.months.filter((m) => SUM.months.includes(m)).length;
      const bars = await page.evaluate(() => ({ hits: document.querySelectorAll('svg.ov-chart .nat-hit').length, late: (() => { const t = document.querySelector('.nw-late-t'); const bb = t.getBBox(); const vb = t.ownerSVGElement.viewBox.baseVal; return bb.x >= 0 && bb.x + bb.width <= vb.width; })() }));
      check(bars.hits === axisN && axisN > 90 && bars.late, label + ': the month chart has a bar for each of the ' + axisN + ' months the two sources share and its "still filling in" label is inside the drawing');
      await page.locator('#nwy-recent').scrollIntoViewIfNeeded();
      await page.locator('#nwy-recent').click();
      await page.waitForFunction((k) => window.__nw.P.n === k && window.__nw.map.ready, nRecent, { timeout: 10000 });
      check((await page.locator('.nw-explore .card-tools .btn').innerText()).trim() === 'Watch 24 months' && (await page.locator('#nwy-recent').getAttribute('aria-pressed')) === 'true' && /last 24 months/.test(await page.locator('.nw-explore .sub').innerText()), label + ': "Last 2 years" puts the two years back, with the 24-month replay');
      // the address carries the choice: #overview?s=TX&y=all opens every year, zoomed to Texas, and choosing the two years takes y out of the address
      await page.goto(base + '?debug#overview?s=TX&y=all', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.P.n > 200000 && window.__nw.map.ready, null, { timeout: 30000 });
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 8000 });
      check((await page.locator('#nwy-all').getAttribute('aria-pressed')) === 'true' && /y=all/.test(await hashNow(page)) && /s=TX/.test(await hashNow(page)), label + ': an address with y=all opens every year, zoomed to the state it names');
      await page.locator('#nwy-recent').scrollIntoViewIfNeeded();
      await page.locator('#nwy-recent').click();
      await page.waitForFunction(() => window.__nw.P.n < 30000, null, { timeout: 10000 });
      check(!/y=all/.test(await hashNow(page)) && /s=TX/.test(await hashNow(page)), label + ': choosing the last two years takes y out of the address and keeps the state');
    } catch (e) {
      check(false, label + ': the Overview: ' + e.message.split('\n')[0].slice(0, 200));
    }
    check(!errs.length, label + ': the Overview loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 19b. the map carries both layers (2026-11-02): a ring for each state agency that counted oil permits (a hollow ring, its area the count) and a dot for each fractured well. "Fractured wells" hides the rings,
  //      "Oil permits" hides the dots and switches the replay off (it is a replay of the wells), "Both" brings them back, and the address follows; a hover on a ring gives both counts, each marked
  for (const [label, w, h] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const st = () => page.evaluate(() => ({ rings: window.__nw.map.drawnRings, hero: window.__nw.hero.drawnRings, pressed: ['both', 'wells', 'permits'].filter((k) => document.querySelector('#nwk-' + k).getAttribute('aria-pressed') === 'true').join(), watchOff: document.querySelector('.nw-explore .card-tools .btn').disabled, watchTitle: document.querySelector('.nw-explore .card-tools .btn').title, hash: location.hash }));
    const hover = async (x, y) => { // the tooltip left by a pointer that arrives at a point on the map (read at once: it is a text node tree in #tip)
      const box = await page.locator('.nw-canvas').boundingBox();
      await page.mouse.move(box.x + x - 25, box.y + y - 25); await page.mouse.move(box.x + x, box.y + y); await page.waitForTimeout(60);
      return page.evaluate(() => { const t = document.querySelector('#tip'); return t.hidden ? '' : t.innerText.replace(/\s+/g, ' ').trim(); });
    };
    try {
      await page.goto(base + '?debug#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForTimeout(600);
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
      const well = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'TX' && P.o[i] >= 0) { const [x, y] = map.screenOf(i); return { x, y }; } return null; });
      const kinds = new Set(RING_STATES.map((s) => s.measure));
      // both
      const a = await st(); await SNAP(page, '.nw-canvas', 'both');
      const tipBoth = await hover(well.x, well.y);
      check(a.rings === RING_STATES.length && a.rings >= 25 && a.hero === a.rings && a.pressed === 'both' && !a.watchOff && !/k=/.test(a.hash) && /first fracturing job/.test(tipBoth),
        label + ': the map draws one ring for each of the ' + RING_STATES.length + ' agencies that counted oil permits (the hero\'s backdrop too: ' + a.hero + ') and the dots: a dot answers a hover with its well, "Both" is chosen, the replay is on, no k in the address');
      // fractured wells only
      await page.locator('#nwk-wells').click();
      const b = await st(); await SNAP(page, '.nw-canvas', 'wells');
      const tipWells = await hover(well.x, well.y);
      check(b.rings === 0 && b.pressed === 'wells' && /k=wells/.test(b.hash) && !b.watchOff && /first fracturing job/.test(tipWells) && (await SNAPDIFF(page, 'both', 'wells')) > 100,
        label + ': "Fractured wells" draws no ring (the rings were ' + (await SNAPDIFF(page, 'both', 'wells')) + ' samples of the picture), keeps the dots and the replay, and writes k=wells in the address');
      // oil permits only
      await page.locator('#nwk-permits').click();
      const c = await st(); await SNAP(page, '.nw-canvas', 'permits');
      const tipPermits = await hover(well.x, well.y);
      check(c.rings === RING_STATES.length && c.pressed === 'permits' && /k=permits/.test(c.hash) && !/first fracturing job/.test(tipPermits) && (await SNAPDIFF(page, 'both', 'permits')) > 300 && (await SNAPDIFF(page, 'wells', 'permits')) > 300,
        label + ': "Oil permits" draws the rings and no dot (the same place that named a well now names the state: "' + tipPermits.slice(0, 50) + '"), and writes k=permits');
      check(c.watchOff && /fractured wells, which are hidden/.test(c.watchTitle), label + ': with only the rings the Watch button is off and says why: ' + c.watchTitle);
      await page.click('#go-explore');
      check(!(await page.locator('.tl-bar').isVisible()), label + ': and the hero\'s "Watch the wells" does not open a replay of wells that are hidden');
      // every ring answers a hover with both counts, each marked, and never a total (the rings alone: a dot under the pointer would answer instead)
      await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
      const bad = [];
      for (const s of RING_STATES) {
        const pos = await page.evaluate((id) => window.__nw.map.screenOfRing(id), s.id);
        const tip = await hover(pos[0], pos[1]);
        const reg = regOf(s.id);
        const wantW = reg && reg.p12 > 0 ? num(reg.p12) + ' fractured wells, last 12 months' : 'None fractured wells in the registry';
        if (!tip.startsWith(s.name) || !hasNum(tip, s.p12) || !tip.includes(wantW) || BAD_TEXT.test(tip) || SUMS.some((n) => hasNum(tip, n)) || (reg && reg.p12 > 0 && hasNum(tip, s.p12 + reg.p12))) bad.push(s.id + ': ' + tip.slice(0, 90));
      }
      check(!bad.length, label + ': hovering the ring of each of the ' + RING_STATES.length + ' agencies names its jurisdiction and gives the agency\'s count and the registry\'s (or "None fractured wells in the registry"), each marked, with no NaN and no total of the two' + (bad.length ? ' [' + bad.join(' | ') + ']' : ''));
      const fo = await (async () => { const pos = await page.evaluate(() => window.__nw.map.screenOfRing('FO')); return hover(pos[0], pos[1]); })();
      check(new RegExp('^Federal offshore ' + natOf('FO').p12 + ' wells spudded, last 12 months None fractured wells in the registry Click for its figures$').test(fo), label + ': the federal offshore (no outline: only its ring can be reached) says "' + fo + '"');
      // a state with none dated in 24 months has no ring and its hover says so, not a count of 0
      const quiet = NAT.states.filter((s) => s.p12 === 0 && s.prev12 === 0);
      await page.locator('#nwk-both').click();
      const badQuiet = [];
      for (const s of quiet) {
        await page.selectOption('.nw-pick', s.id);
        await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(250);
        const box = await page.locator('.nw-canvas').boundingBox(); let tip = '';
        for (let gx = 1; gx < 8 && !tip.startsWith(s.name); gx++) for (let gy = 1; gy < 8 && !tip.startsWith(s.name); gy++) tip = await hover(box.width * gx / 8, box.height * gy / 8);
        if (!tip.startsWith(s.name) || !/None recorded oil permits, last 24 months/.test(tip) || /(^|\s)0 /.test(tip) || BAD_TEXT.test(tip)) badQuiet.push(s.id + ': ' + tip.slice(0, 90));
      }
      check(quiet.length >= 3 && !badQuiet.length, label + ': ' + quiet.length + ' states with nothing dated in 24 months (' + quiet.map((s) => s.id).join(', ') + ') draw no ring and their hover says "None recorded", never 0' + (badQuiet.length ? ' [' + badQuiet.join(' | ') + ']' : ''));
      await page.selectOption('.nw-pick', '');
      // back to both
      await page.locator('#nwk-both').click();
      const d = await st(); await SNAP(page, '.nw-canvas', 'again');
      check(d.rings === RING_STATES.length && d.pressed === 'both' && !/k=/.test(d.hash) && !d.watchOff && (await SNAPDIFF(page, 'both', 'again')) < 40, label + ': "Both" puts the rings and the dots back exactly as they were, the Watch button on and k out of the address');
      // the legend says which mark is which, and that they are never added
      const legend = await page.locator('.nw-legend').innerText();
      const nDash = await page.locator('.nw-legend .dd-ringkey.is-dash').count(); const nDot = await page.locator('.nw-legend .dd-ringkey.is-dot').count();
      check((await page.locator('.nw-legend .dd-dotkey').count()) === 1 && (await page.locator('.nw-legend .dd-ringkey').count()) === 1 + (kinds.has('spuds') ? 1 : 0) + ([...kinds].some((m) => m !== 'permits' && m !== 'spuds') ? 1 : 0) && nDash === (kinds.has('spuds') ? 1 : 0) && nDot === ([...kinds].some((m) => m !== 'permits' && m !== 'spuds') ? 1 : 0) && /Fractured well: the first fracturing job/.test(legend) && /Oil permits approved/.test(legend) && /Wells spudded/.test(legend) && /Counted another way/.test(legend) && /never added together/.test(legend) && /BLM/.test(legend),
        label + ': the legend names the dot (a fractured well), the ring (oil permits approved), the dashed ring (wells spudded) and the dotted ring (counted another way), and says they are never added: ' + legend.replace(/\s+/g, ' ').slice(0, 120));
      // the address: k=wells opens on the dots alone, k=permits on the rings alone
      await page.goto(base + '?debug&again=1#overview?k=wells', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      const e1 = await st();
      await page.goto(base + '?debug&again=2#overview?k=permits', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      const e2 = await st();
      check(e1.rings === 0 && e1.pressed === 'wells' && e2.rings === RING_STATES.length && e2.pressed === 'permits' && e2.watchOff, label + ': an address with k=wells opens on the dots alone, one with k=permits on the rings alone with the replay off');
    } catch (e) {
      check(false, label + ': the Overview\'s layers: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, label + ': the Overview\'s layers load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 24. every visual of the Overview carries both layers (2026-11-02), each marked the way the map marks it (a ring or an outlined bar or a ringed line for an agency's oil permits, a dot or a filled bar for a
  //     fractured well), each from its own source and never added: the hero, the state panel (for the country and for every case the two sources treat differently), the ranking, the months chart and its table, the leaders and the coverage table
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const VOICE = /\b(this machine|from here|I tried|I read|I saw|the tracker|polite request|the brief|sandbox|WebFetch|HEAD request|reachable)\b/i;
    const readPanel = () => page.evaluate(() => {
      const box = document.querySelector('.nw-grid .nat-panel');
      return { h3: box.querySelector('h3').textContent, badge: (box.querySelector('.nat-ph .badge') || {}).textContent || null, heads: [...box.querySelectorAll('.ov-fig-h')].map((n) => n.textContent.trim()),
        marks: [...box.querySelectorAll('.ov-fig-h > i')].map((i) => i.className.replace(/\s*is-\w+/, '')), figs: [...box.querySelectorAll('.ov-fig')].map((n) => n.innerText.replace(/\s+/g, ' ').trim()), text: box.innerText.replace(/\s+/g, ' '),
        dual: box.querySelectorAll('svg.ov-dual').length, pLine: box.querySelectorAll('svg.ov-dual path.ov-p-line').length, wLine: box.querySelectorAll('svg.ov-dual path.ov-w-line').length, pEnd: box.querySelectorAll('svg.ov-dual .ov-p-end').length };
    });
    const panelOf = async (id) => { await page.selectOption('.nw-pick', id || ''); return readPanel(); };
    try {
      await page.goto(base + '?debug#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForTimeout(500);
      // the hero says what a dot and a ring are
      const heroText = (await page.locator('#hero-eyebrow').textContent()) + ' ' + (await page.locator('#hero-lede').textContent()) + ' ' + (await page.locator('#hero-note').textContent());
      check(/^Oil permits and fractured wells, every state/.test(heroText) && /Each ring is a state agency’s count of its oil permits/.test(heroText) && /Dots are the [\d,]+ fractured wells/.test(heroText) && /never added to them/.test(heroText) && (await page.locator('#hero-canvas').count()) === 1, 'the hero names both layers, says a ring is the agency\'s count and a dot a fractured well, and that they are never added');
      // ---- the state panel: a block for each layer (a ring mark, a dot mark), for the country and for every case the two sources treat differently
      const all = await panelOf(null);
      check(all.h3 === 'All states' && all.heads.join() === 'Oil permits,Fractured wells' && all.marks.join() === 'dd-ringkey,dd-dotkey' && hasNum(all.figs[0], PERMITS_N) && !hasNum(all.figs[0], FRAC_N) && hasNum(all.figs[1], FRAC_N) && !hasNum(all.figs[1], PERMITS_N)
        && hasNum(all.figs[0], SPUDS_N) && hasNum(all.figs[0], BLM_N) && /overlap the states/.test(all.figs[0]) && /never added/.test(all.figs[0]), 'All states: one block for the agencies\' ' + num(PERMITS_N) + ' oil permits (the ' + num(SPUDS_N) + ' wells spudded and the BLM\'s ' + num(BLM_N) + ' named apart) and one for the registry\'s ' + num(FRAC_N) + ' fractured wells, each with its mark, neither holding the other\'s number');
      const cases = {
        TX: (r) => r.heads.join() === 'Oil permits,Fractured wells' && hasNum(r.figs[0], natOf('TX').p12) && /new-drill permits/.test(r.figs[0]) && hasNum(r.figs[1], regOf('TX').p12) && r.dual === 1 && r.pLine === 1 && r.wLine >= 1 && r.pEnd === 1,
        ND: (r) => hasNum(r.figs[0], natOf('ND').p12) && /wells spudded/.test(r.figs[0]) && hasNum(r.figs[1], regOf('ND').p12) && r.pLine === 1 && r.wLine >= 1 && r.badge === 'Wells spudded',
        IL: (r) => hasNum(r.figs[0], natOf('IL').p12) && /None in the last 12 months/.test(r.figs[1]) && !/(^|\s)0(\s|$)/.test(r.figs[1]) && r.pLine === 1 && r.wLine === 0 && /not the same as no drilling/.test(r.figs[1]),
        FO: (r) => hasNum(r.figs[0], natOf('FO').p12) && /Not in the registry/.test(r.figs[1]) && r.pLine === 1 && r.wLine === 0 && /the federal offshore’s permits are counted above/.test(r.figs[1]) && !/[a-z0-9,;:] Federal (offshore|onshore)/.test(r.text),
        BL: (r) => hasNum(r.figs[0], BLM_N) && /APDs approved/.test(r.figs[0]) && /on federal or tribal land/.test(r.figs[1]) && !/Not in the registry/.test(r.figs[1]) && r.pLine === 1 && r.wLine === 0 && /never added to the states/.test(r.text) && !/\(BLM\)’s/.test(r.text) && !/[a-z0-9,;:] Federal (offshore|onshore)/.test(r.text),
        MO: (r) => r.figs.length === 2 && /never as zero/.test(r.figs[0]) && !/(^|\s)0(\s|$)/.test(r.figs[0]) && /Not in the registry/.test(r.figs[1]) && r.dual === 0,
        CA: (r) => hasNum(r.figs[0], natOf('CA').p12) && new RegExp('\\(' + natOf('CA').prev12 + ' the 12 months before\\)').test(r.figs[0]) && !/%/.test(r.figs[0]) && /None in the last 12 months/.test(r.figs[1]) && r.pLine === 1 && r.wLine === 0,
        AZ: (r) => /None recorded in the 24 months/.test(r.figs[0]) && !/\b0 wells spudded/.test(r.text) && /Not in the registry/.test(r.figs[1]) && r.badge === 'Wells spudded',
        VA: (r) => r.badge === 'Wells drilled' && /wells drilled/.test(r.figs[0]) && hasNum(r.figs[1], regOf('VA').p12) && !hasNum(r.text, natOf('VA').p12 + regOf('VA').p12),
      };
      for (const [id, ok] of Object.entries(cases)) {
        const r = await panelOf(id);
        const reg = regOf(id); const p = natOf(id);
        const sumTotal = p && reg && p.p12 > 0 && reg.p12 > 0 ? p.p12 + reg.p12 : null;
        check(r.h3 === nameOf(id) && r.heads.join() === 'Oil permits,Fractured wells' && r.marks.join() === 'dd-ringkey,dd-dotkey' && ok(r) && !BAD_TEXT.test(r.text) && !VOICE.test(r.text) && !SUMS.some((n) => hasNum(r.text, n)) && (sumTotal == null || sumTotal < 100 || !hasNum(r.text, sumTotal)),
          'the panel for ' + nameOf(id) + ' has its block for the agency and its block for the registry, each with its mark, and says what each source has: ' + r.figs.map((f) => f.slice(0, 70)).join(' | '));
      }
      // ---- the ranking: each jurisdiction's row says what the agency counted and what the registry holds, beside one another, each from the data
      await page.selectOption('.nw-pick', '');
      const ranking = await page.evaluate(() => [...document.querySelectorAll('.ov-row')].map((r) => { const code = r.querySelector('.nat-rc').textContent; const p = r.querySelector('.ov-p'); const w = r.querySelector('.ov-w');
        return { name: r.querySelector('.nat-rn').textContent.slice(code.length), pv: (p.querySelector('.nat-rv') || {}).textContent || null, pu: (p.querySelector('.ov-u') || {}).textContent || null, pNone: (p.querySelector('.ov-none') || {}).textContent || null, pRing: !!p.querySelector('.nat-rb.is-ring'), pFill: !!p.querySelector('.nat-rb:not(.is-ring)'),
          wv: (w.querySelector('.nat-rv') || {}).textContent || null, wu: (w.querySelector('.ov-u') || {}).textContent || null, wNone: (w.querySelector('.ov-none') || {}).textContent || null, wFill: !!w.querySelector('.nat-rb:not(.is-ring)'), wRing: !!w.querySelector('.nat-rb.is-ring'), label: r.getAttribute('aria-label'), text: r.innerText.replace(/\s+/g, ' ') }; }));
      const word = { permits: 'permit', spuds: 'spud', applications: 'application', drilled: 'drilled' };
      const badRows = [];
      for (const j of ranking) {
        const s = NAT.states.find((x) => x.name === j.name || (x.id === 'BL' && j.name === 'Federal onshore')); const reg = s ? regOf(s.id) : null;
        if (!s) { badRows.push(j.name + ': not in the national file'); continue; }
        const unit = s.measure === 'drilled' ? 'drilled' : s.p12 === 1 ? word[s.measure] : word[s.measure] + 's';
        const pOk = s.p12 === 0 && s.prev12 === 0 ? j.pNone === 'None recorded' && !j.pv : j.pv === num(s.p12) && j.pu === unit && j.pRing && !j.pFill;
        const wOk = FED.has(s.id) ? /overlaps the states: never added/.test(j.wNone || '') && !j.wv : reg && reg.p12 > 0 ? j.wv === num(reg.p12) && j.wu === (reg.p12 === 1 ? 'well' : 'wells') && j.wFill && !j.wRing : j.wNone === (reg ? 'None in 12 months' : 'Not in the registry') && !j.wv;
        if (!pOk || !wOk || /(^|\s)0 (permits|spuds|applications|drilled|wells?)\b/.test(j.text) || BAD_TEXT.test(j.text) || SUMS.some((n) => hasNum(j.text, n))) badRows.push(j.name + ': ' + j.text.slice(0, 80));
      }
      check(ranking.length === NAT.states.length && !badRows.length, 'each of the ' + ranking.length + ' ranking rows matches the data in both cells: the agency\'s count with its unit (an outlined bar) and the registry\'s wells (a filled bar), "None recorded", "None in 12 months" or "Not in the registry" where the source has no figure, the BLM\'s "overlaps the states: never added", never a bare 0' + (badRows.length ? ' [' + badRows.join(' | ') + ']' : ''));
      const orderOf = async (by) => { await page.locator('#ovr-' + by).click(); return page.evaluate(() => [...document.querySelectorAll('.ov-row')].slice(0, 4).map((r) => r.querySelector('.nat-rn').textContent.slice(r.querySelector('.nat-rc').textContent.length))); };
      const byP = NAT.states.filter((s) => !FED.has(s.id)).sort((a, b) => b.p12 - a.p12).slice(0, 4).map((s) => s.name);
      const byW = SUM.states.slice().sort((a, b) => b.p12 - a.p12).slice(0, 4).map((s) => s.name);
      const gotW = await orderOf('wells'); const gotP = await orderOf('permits');
      check(gotP.join() === byP.join() && gotW.join() === byW.join() && byP.join() !== byW.join(), 'the ranking sorts by the agencies\' count or by the registry\'s: the top four are ' + gotP.join(', ') + ' by oil permits and ' + gotW.join(', ') + ' by fractured wells, as the files say');
      // ---- the months chart: the agencies' counts as lines, the registry's wells as bars stacked by state, and the table twin with the same columns
      await page.locator('section[aria-labelledby="months-h"]').scrollIntoViewIfNeeded();
      const mc = await page.evaluate(() => { const c = document.querySelector('svg.ov-chart'); return { permitsLine: c.querySelectorAll('path.ov-line.ov-permits').length, spudsLine: c.querySelectorAll('path.ov-line.ov-spuds').length, ends: c.querySelectorAll('circle.ov-end').length, segs: c.querySelectorAll('rect.nat-bar-seg').length,
        keys: [...document.querySelectorAll('ul.ov-keys li')].map((li) => li.textContent.replace(/\s+/g, ' ').trim()), heads: [...document.querySelectorAll('details.nat-details thead th')].map((th) => th.textContent.trim()), label: c.getAttribute('aria-label') }; });
      check(mc.permitsLine === 1 && mc.spudsLine === 1 && mc.ends === 2 && mc.segs > 100 && mc.keys.some((k) => k === 'Oil permits approved (' + AGENCIES + ' agencies)') && mc.keys.some((k) => k === 'Oil wells spudded (' + SPUD_AGENCIES + ' agencies)') && mc.keys.some((k) => /^Fractured wells, by state:/.test(k)) && /fractured wells as bars stacked by state, the permits and spuds as lines/.test(mc.label),
        'the month chart draws the agencies\' permits and spuds as two lines and the registry\'s wells as ' + mc.segs + ' bars stacked by state, with a key for each');
      check(mc.heads[0] === 'Month' && mc.heads[1] === 'Oil permits approved' && mc.heads[2] === 'Oil wells spudded' && mc.heads.slice(3, -1).length >= 5 && mc.heads.slice(3, -1).every((t) => / \(fractured wells\)$/.test(t)) && mc.heads[mc.heads.length - 1] === 'All fractured wells', 'its table twin has the permits column, the spuds column, one column of fractured wells for each state and the registry\'s total: ' + mc.heads.slice(0, 4).join(' | ') + ' … ' + mc.heads[mc.heads.length - 1]);
      const twin = await page.evaluate(() => [...document.querySelectorAll('details.nat-details tbody tr')].map((tr) => [...tr.children].map((c) => c.textContent.replace(/,/g, ''))));
      const jun = twin.find((r) => r[0] === 'Jun 2025');
      const ix = NAT.months.indexOf('2025-06'); const jx = SUM.months.indexOf('2025-06');
      const wantP = NAT.states.filter((s) => s.measure === 'permits' && !FED.has(s.id)).reduce((t, s) => t + (s.bands.new[ix] || 0), 0); const wantS = NAT.states.filter((s) => s.measure === 'spuds').reduce((t, s) => t + (s.bands.new[ix] || 0), 0);
      const wantW = SUM.states.reduce((t, s) => t + (s.new[jx] || 0), 0);
      check(!!jun && +jun[1] === wantP && +jun[2] === wantS && +jun[jun.length - 1] === wantW && jun.slice(3, -1).reduce((t, v) => t + +v, 0) === wantW && twin.every((r) => r.slice(3, -1).reduce((t, v) => t + +v, 0) === +r[r.length - 1]) && twin.length === NAT.months.filter((m) => SUM.months.includes(m)).length,
        'a month of the table (Jun 2025) is the agencies\' ' + wantP + ' permits and ' + wantS + ' spuds beside the registry\'s ' + wantW + ' wells, as the files say, and in every month the states\' wells add up to the registry\'s total (the permits are in no total of wells)');
      const tipIx = 30;
      await page.locator('svg.ov-chart .nat-hit').nth(tipIx).hover();
      const mt = await page.evaluate(() => { const t = document.querySelector('#tip'); return t.hidden ? '' : t.innerText.replace(/\s+/g, ' ').trim(); });
      check(/oil permits approved/.test(mt) && /fractured wells in all/.test(mt) && !BAD_TEXT.test(mt) && SUMS.every((n) => !hasNum(mt, n)), 'a month\'s tooltip gives the permits and the fractured wells, each named: ' + mt.slice(0, 120));
      // ---- the leaders: two cards, each with the agencies' list (outlined bars) and the registry's (filled bars)
      const leaders = async (id) => { await page.selectOption('.nw-pick', id || ''); return page.evaluate(() => ['ov-where-h', 'ov-who-h'].map((hid) => { const card = document.getElementById(hid).closest('section');
        return { sub: card.querySelector('.sub').textContent, layers: [...card.querySelectorAll('.ov-layer')].map((l) => ({ ring: !!l.querySelector('h4 .dd-ringkey'), dot: !!l.querySelector('h4 .dd-dotkey'), title: l.querySelector('h4').textContent.trim(), rows: [...l.querySelectorAll('.ov-list li')].map((li) => li.innerText.replace(/\s+/g, ' ')), ringBars: l.querySelectorAll('.nat-lb.is-ring').length, fillBars: l.querySelectorAll('.nat-lb:not(.is-ring)').length, fine: (l.querySelector('.fine') || {}).textContent || null })) }; })); };
      const lAll = await leaders(null);
      check(lAll.every((c) => c.layers.length === 2 && c.layers[0].ring && !c.layers[0].dot && c.layers[1].dot && !c.layers[1].ring && c.layers.every((l) => l.rows.length === 8)) && lAll[0].layers.every((l) => l.rows.every((r) => /\d/.test(r))) && lAll[0].layers[0].ringBars === 8 && lAll[0].layers[0].fillBars === 0 && lAll[0].layers[1].fillBars === 8 && lAll[0].layers[1].ringBars === 0 && /Oil permits/.test(lAll[0].layers[0].title) && /Fractured wells/.test(lAll[0].layers[1].title),
        'the counties and the operators for the country each list eight of the agencies\' (outlined bars) and eight of the registry\'s (filled bars)');
      const lTx = await leaders('TX'); const lIl = await leaders('IL'); const lFo = await leaders('FO'); const lMo = await leaders('MO');
      const txTop = natOf('TX').counties[0];
      check(lTx.every((c) => /^Texas/.test(c.sub)) && lTx[0].layers[0].rows[0].startsWith(txTop[0] + ' ' + num(txTop[1])) && /Martin|Midland/.test(lTx[0].layers[1].rows[0]) && lTx.every((c) => c.layers.every((l) => l.rows.length >= 5)),
        'choosing Texas gives its own agency counties first (' + txTop[0] + ' ' + num(txTop[1]) + ') beside the registry\'s, and both cards say "Texas"');
      check(lIl.every((c) => /^Illinois/.test(c.sub)) && lIl[0].layers[0].rows.length >= 5 && lIl[0].layers[1].rows.length === 0 && /Not in the registry in the last 12 months/.test(lIl[0].layers[1].fine) && lIl[1].layers[1].rows.length === 0,
        'Illinois has a list of the agency\'s counties and operators and, for the registry, "Not in the registry in the last 12 months", never an empty list or a zero');
      check(lFo.every((c) => /^Federal offshore/.test(c.sub)) && /areas/.test(lFo[0].sub) && lFo[0].layers[0].rows.length >= 3 && lFo[0].layers[1].rows.length === 0 && /^Missouri/.test(lMo[0].sub) && lMo.every((c) => c.layers[0].rows.length === 0 && /No agency file is read for Missouri yet/.test(c.layers[0].fine) && c.layers[1].rows.length === 0),
        'the federal offshore\'s list says areas, and Missouri (no source in either) says "No agency file is read for Missouri yet", not an empty list');
      await page.selectOption('.nw-pick', '');
      // ---- the coverage table: a row for each jurisdiction, with a column for the agency's count and one for the registry's wells
      await page.locator('section[aria-labelledby="cover-h"]').scrollIntoViewIfNeeded();
      const cov = await page.evaluate(() => ({ heads: [...document.querySelectorAll('table.nat-cov thead th')].map((th) => th.textContent), rows: [...document.querySelectorAll('table.nat-cov tbody tr')].map((tr) => ({ gap: tr.classList.contains('is-gap'), cells: [...tr.children].map((c) => c.innerText.replace(/\s+/g, ' ').trim()) })), text: document.querySelector('table.nat-cov').innerText }));
      const covBad = [];
      for (const r of cov.rows) {
        const id = (NAT.states.concat(NAT.gaps).find((s) => s.name === r.cells[0] || (s.id === 'BL' && r.cells[0] === 'Federal onshore')) || {}).id; const reg = regOf(id);
        const wantW = FED.has(id) ? 'overlaps the states' : reg && reg.p12 > 0 ? num(reg.p12) : reg ? 'none in 12 months' : 'not in the registry';
        if (!id || r.cells[5] !== wantW || (id === 'MO' ? r.cells[1] !== 'Not read yet' || !r.gap : r.cells[1] === 'Not read yet')) covBad.push(r.cells[0] + ': ' + r.cells.join(' | ').slice(0, 100));
      }
      check(cov.heads.join('|') === 'State|Oil permits count|Agency|Data through|Updates|Fractured wells, 12 months' && cov.rows.length === NAT.states.length + NAT.gaps.length && !covBad.length && !VOICE.test(cov.text) && !BAD_TEXT.test(cov.text),
        'the coverage table has a row for each of the ' + cov.rows.length + ' jurisdictions (Missouri, which has no source, among them as "Not read yet") with the agency\'s count and the registry\'s wells in their own columns, none of them 0 where the source has no figure' + (covBad.length ? ' [' + covBad.join(' | ') + ']' : ''));
      const fresh = await page.locator('#fresh-list li').allInnerTexts();
      check(fresh.length === 2 && /FracFocus/.test(fresh[0]) && /Oil permits/.test(fresh[1]) && fresh.every((t) => /Publishes/.test(t.replace(/\s+/g, ' ')) || /read here/.test(t)), 'the freshness list has one line for each source, the registry\'s and the agencies\'');
    } catch (e) {
      check(false, 'both layers in every visual: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the Overview\'s visuals load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 25. one state, however it is chosen (2026-11-02): a click on a state with dots, on a ring (of a state with an outline, of one with permits and no wells, of the federal offshore, which has no outline), the selector, a key chip,
  //     a ranking row, a coverage row, a key press, the address (typed, followed, and one that names a jurisdiction that does not exist) all end in the same place: the panel, the selector, the address, the ranking row,
  //     the key chip, the leaders' subtitles and the map's zoom agree. (Found by clicking: the middle of Louisiana's box is in Mississippi, so a click on Louisiana's ring chose Mississippi.)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const NO_OUTLINE = new Set(['FO', 'BL']); // the federal offshore and the BLM are not on the state outlines: chosen without a zoom
    const snap = () => page.evaluate(() => ({
      h3: document.querySelector('.nw-grid .nat-panel h3').textContent, pick: document.querySelector('.nw-pick').value, hash: location.hash, sel: window.__nw.map.selected,
      rows: [...document.querySelectorAll('.ov-row[aria-current="true"]')].map((r) => r.querySelector('.nat-rn').textContent.slice(r.querySelector('.nat-rc').textContent.length)),
      chips: [...document.querySelectorAll('.nw-chip[aria-pressed="true"]')].map((c) => c.textContent.trim()), chipNames: [...document.querySelectorAll('.nw-chip')].map((c) => c.textContent.trim()),
      where: document.querySelector('#ov-where-h').closest('section').querySelector('.sub').textContent, who: document.querySelector('#ov-who-h').closest('section').querySelector('.sub').textContent,
    }));
    const agree = async (route, id) => {
      const s = await snap(); const name = id ? nameOf(id) : null; const hasRow = id && id !== 'MO'; const rowName = id === 'BL' ? 'Federal onshore' : name;
      const head = id ? s.h3 === name && s.pick === id && new RegExp('(\\?|&)s=' + id + '(&|$)').test(s.hash) && s.where.startsWith(name) && s.who.startsWith(name)
        : s.h3 === 'All states' && s.pick === '' && !/s=/.test(s.hash) && /^The top 8 across the country/.test(s.where) && /^The operators/.test(s.who);
      const ok = head && JSON.stringify(s.rows) === JSON.stringify(hasRow ? [rowName] : []) && JSON.stringify(s.chips) === JSON.stringify(id && s.chipNames.includes(name) ? [name] : []) && s.sel === (id && !NO_OUTLINE.has(id) ? id : null);
      check(ok, route + ' -> ' + (name || 'All states') + ': the panel, the selector, the address, the ranking row, the key chip, the leaders and the map\'s zoom agree' + (ok ? '' : ': ' + JSON.stringify(s).slice(0, 300)));
    };
    const reset = async () => { await page.selectOption('.nw-pick', ''); };
    const onMap = async () => { await page.locator('.nw-stage').scrollIntoViewIfNeeded(); await page.waitForTimeout(150); return page.locator('.nw-canvas').boundingBox(); };
    const click = async (x, y) => { const box = await onMap(); await page.mouse.move(box.x + x - 12, box.y + y - 12); await page.mouse.move(box.x + x, box.y + y); await page.mouse.click(box.x + x, box.y + y); };
    const ringClick = async (id) => { const pos = await page.evaluate((i) => window.__nw.map.screenOfRing(i), id); await click(pos[0], pos[1]); };
    try {
      await page.goto(base + '?debug#overview', { waitUntil: 'load' });
      await page.waitForSelector('.nw-canvas', { timeout: 25000 });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForTimeout(500);
      await agree('the start', null);
      // the map
      const well = await page.evaluate(() => { const { map, P } = window.__nw; for (let i = 0; i < P.n; i++) if (P.states[P.s[i]] === 'ND') { const [x, y] = map.screenOf(i); return [x, y]; } return null; });
      await click(well[0], well[1]); await agree('a click on a well of North Dakota', 'ND');
      await reset();
      await ringClick('UT'); await agree('a click on Utah\'s ring (a state with an outline, permits and wells)', 'UT');
      await reset();
      await ringClick('LA'); await agree('a click on Louisiana\'s ring (its middle was in Mississippi)', 'LA');
      await reset();
      await page.locator('#nwk-permits').click();
      await ringClick('IL'); await agree('a click on Illinois\'s ring (permits and no well in the registry)', 'IL');
      check(/None in the last 12 months/.test(await page.locator('.nw-grid .nat-panel').innerText()), 'and Illinois\'s panel says its fractured wells are "None in the last 12 months", not 0');
      await reset();
      await ringClick('FO'); await agree('a click on the federal offshore\'s ring (no outline: chosen, not zoomed)', 'FO');
      await reset();
      await page.locator('#nwk-both').click();
      // the map's own empty space takes the zoom back to the country
      await page.selectOption('.nw-pick', 'ND');
      await click(6, 6); await agree('a click on the empty corner of the map while zoomed to North Dakota', null);
      // the selector, the key and the table
      await page.selectOption('.nw-pick', 'BL'); await agree('the selector (the BLM)', 'BL');
      await page.selectOption('.nw-pick', 'MO'); await agree('the selector (Missouri, which has neither source)', 'MO');
      await reset();
      await page.locator('.nw-chip', { hasText: 'North Dakota' }).click(); await agree('the key chip', 'ND');
      await page.locator('.nw-chip', { hasText: 'North Dakota' }).click(); await agree('the same chip again (it toggles)', null);
      await page.locator('.ov-row', { hasText: 'Oklahoma' }).click(); await agree('a ranking row', 'OK');
      await page.locator('#ovr-wells').click(); await agree('the ranking sorted by fractured wells (the choice stays marked)', 'OK');
      await page.locator('.ov-row.is-fed').click(); await agree('the BLM\'s row', 'BL');
      await page.locator('.ov-row', { hasText: 'Arizona' }).click(); await agree('a row with "None recorded" (Arizona)', 'AZ');
      await page.locator('#ovr-permits').click();
      await page.locator('table.nat-cov button.link', { hasText: 'Illinois' }).click(); await agree('a coverage row (Illinois)', 'IL');
      await page.locator('table.nat-cov button.link', { hasText: 'Missouri' }).click(); await agree('a coverage row (Missouri: no ranking row to mark)', 'MO');
      await reset();
      // the keyboard: a ranking row is a button, Enter chooses it
      await page.locator('.ov-row', { hasText: 'Wyoming' }).focus(); await page.keyboard.press('Enter'); await agree('the keyboard (Enter on the Wyoming row)', 'WY');
      await page.locator('.ov-row', { hasText: 'Ohio' }).focus(); await page.keyboard.press('Space'); await agree('the keyboard (Space on the Ohio row)', 'OH');
      await reset();
      // the address, followed inside the page
      for (const [hash, id] of [['#overview?s=OH', 'OH'], ['#overview?s=FO', 'FO'], ['#overview?s=BL', 'BL'], ['#overview?s=MO', 'MO'], ['#overview', null]]) {
        await page.evaluate((h) => { location.hash = h; }, hash);
        await page.waitForFunction((n) => document.querySelector('.nw-grid .nat-panel h3').textContent === n, id ? nameOf(id) : 'All states', { timeout: 5000 });
        await agree('an address followed in the page (' + hash + ')', id);
      }
      // the address, typed: a fresh load names a state, any state, in capitals or not, and an unknown one is the country (with the address saying so)
      for (const [hash, id] of [['#overview?s=WY', 'WY'], ['#overview?s=FO', 'FO'], ['#overview?s=MO', 'MO'], ['#overview?s=ZZ', null], ['#overview?s=', null]]) {
        await page.goto('about:blank');
        await page.goto(base + '?debug' + hash, { waitUntil: 'load' });
        await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
        await page.waitForSelector('.nw-grid .nat-panel h3', { timeout: 10000 });
        await agree('an address typed (' + hash + ')', id);
      }
      await page.goto('about:blank');
      await page.goto(base + '?debug#overview?s=bl&k=wells', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      check((await page.locator('.nw-grid .nat-panel h3').first().innerText()) === 'Federal onshore (BLM)' && (await page.locator('.nw-pick').inputValue()) === 'BL' && (await page.locator('#nwk-wells').getAttribute('aria-pressed')) === 'true', 'an address in lower case (s=bl) names the same jurisdiction, and keeps the layer it names (k=wells)');
      // an unknown state beside a layer and years: the state goes, the rest stays
      await page.goto('about:blank');
      await page.goto(base + '?debug#overview?s=ZZ&k=permits', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      check(/^#overview\?k=permits$/.test(await hashNow(page)) && (await page.locator('.nw-grid .nat-panel h3').first().innerText()) === 'All states', 'an unknown state beside a layer (s=ZZ&k=permits) is dropped from the address and keeps the layer: ' + (await hashNow(page)));
    } catch (e) {
      check(false, 'choosing a state: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'choosing a state loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 26. one Overview and six tabs (2026-11-02): the Map and the National report are not tabs any more (nor is Operators: it is part of Companies, nor the states bar). The nav has exactly six, no section of either is left in the page, and their old addresses open the Overview
  //     on the state they named, whether typed (a fresh load) or followed inside the page (a link in a bookmark that the page meets as a hash change), with the address rewritten and no error
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      const nav = await page.evaluate(() => ({ hrefs: [...document.querySelectorAll('.nav a')].map((a) => a.getAttribute('href')), names: [...document.querySelectorAll('.nav a')].map((a) => a.textContent.replace(/\s+/g, ' ').trim()),
        views: [...document.querySelectorAll('[data-view]')].map((v) => v.id), gone: document.querySelectorAll('#view-map, #view-national, #view-operators, #map-root, #national-root, #ops-lede, #map-lede, #map-metric, .map-table, .nat-tile, #statebar').length, cur: [...document.querySelectorAll('.nav a[aria-current="page"]')].map((a) => a.getAttribute('href')) }));
      check(nav.hrefs.join() === '#overview,#fields,#companies,#daily,#images,#about' && nav.names.join('|') === 'Overview|Permit data|Companies|Daily|Texas images|Sources & method' && nav.cur.join() === '#overview',
        'the nav has exactly six tabs (' + nav.names.join(', ') + '), none of them the Map, the National report or Operators (it is part of Companies), and the Overview is the current one');
      check(nav.views.join() === 'view-overview,view-fields,view-companies,view-daily,view-images,view-about' && nav.gone === 0, 'the page has six views and no section, control, tile or states bar of the Map or the National report is left in it: ' + nav.views.join(','));
      const cases = [['#national', '#overview', 'All states'], ['#national?s=OK&m=spuds', '#overview?s=OK', 'Oklahoma'], ['#national?s=NM&m=permits', '#overview?s=NM', 'New Mexico'], ['#national?s=BL', '#overview?s=BL', 'Federal onshore (BLM)'],
        ['#map', '#overview', 'All states'], ['#map?st=tx', '#overview?s=TX', 'Texas'], ['#map?st=fo', '#overview?s=FO', 'Federal offshore'], ['#map?st=tx,ok', '#overview', 'All states'], ['#map?st=ok&county=OK:039', '#overview?s=OK', 'Oklahoma'], ['#map?metric=depth&st=nm', '#overview?s=NM', 'New Mexico']];
      const wrong = [];
      for (const [old, want, h3] of cases) {
        await page.goto('about:blank');
        await page.goto(base + old, { waitUntil: 'load' });
        await page.waitForSelector(OV_PANEL, { timeout: 25000 });
        const typed = [await hashNow(page), await page.locator(OV_PANEL).first().innerText(), await page.locator('#view-overview').isVisible(), await page.locator('#statebar').isVisible()];
        await page.evaluate(() => { location.hash = '#fields'; });
        await page.waitForSelector('#fields-root button.fx-c', { timeout: 15000 });
        await page.evaluate((o) => { location.hash = o; }, old);
        await page.waitForFunction((w) => location.hash === w, want, { timeout: 5000 }).catch(() => {});
        const followed = [await hashNow(page), await page.locator(OV_PANEL).first().innerText(), await page.locator('#view-overview').isVisible(), await page.locator('#statebar').isVisible()];
        for (const [how, r] of [['typed', typed], ['followed', followed]]) if (r[0] !== want || r[1] !== h3 || !r[2] || r[3]) wrong.push(old + ' ' + how + ' -> ' + r.join(' / '));
      }
      check(!wrong.length, 'each old address of the Map or the National report opens the Overview on the state it named, typed or followed, with the address rewritten and no states bar (' + cases.length + ' addresses)' + (wrong.length ? ' [' + wrong.join(' | ') + ']' : ''));
      // the states bar is gone from every view: its last view, the Map, is part of the Overview
      const bar = [];
      for (const [v, ready] of [['#overview', '.ov-row'], ['#companies', '#ops-root tbody tr'], ['#fields', '#fields-root button.fx-c']]) {
        await page.goto('about:blank');
        await page.goto(base + v, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        bar.push(v.slice(1) + ':' + (await page.locator('#statebar, #statebar-seg').count()));
      }
      check(bar.join() === 'overview:0,companies:0,fields:0', 'there is no states bar in the Overview, Companies or the matrix: ' + bar.join(' '));
      // nothing in any view links to a tab that is gone
      const links = [];
      for (const [v, ready] of [['#overview?s=TX', OV_PANEL], ['#companies', '#ops-root tbody tr'], ['#companies?kind=directory', '#co-root table'], ['#daily', '#daily-root .dd-nav'], ['#images', '#images-root .img-stage'], ['#fields?s=TX', '#fields-root .nat-panel h3'], ['#about', '#view-about h1']]) {
        await page.goto('about:blank');
        await page.goto(base + v, { waitUntil: 'load' });
        await page.waitForSelector(ready, { timeout: 25000 });
        await page.waitForTimeout(300);
        const n = await page.evaluate(() => [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href')).filter((h) => /^#(map|national)\b/.test(h) || /[?&]st=[a-z,]+#?map/.test(h)).length);
        if (n) links.push(v + ': ' + n);
      }
      check(!links.length, 'no link on any view points at the Map or the National report' + (links.length ? ' [' + links.join(', ') + ']' : ''));
      const fx = await (async () => { await page.goto('about:blank'); await page.goto(base + '#fields?s=TX', { waitUntil: 'load' }); await page.waitForSelector('#fields-root .nat-panel h3', { timeout: 25000 }); return page.locator('#fields-root .nat-panel a[href="#overview?s=TX"]').count(); })();
      check(fx === 1, 'the matrix\'s agency panel links to the agency\'s permits on the Overview (#overview?s=TX)');
    } catch (e) {
      check(false, 'the old tabs: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the old addresses and the nav load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 27. the Overview with the motion the visitor asked for (2026-11-02): both loads draw the map with its rings and dots, zoom to a state and back, and replay; with motion allowed the replay has its play button and the clock moves
  //     (pause holds it, the scrubber seeks, closing ends it); with reduced motion there is the scrubber alone. The same figures either way
  for (const [label, motion] of [['reduced motion', 'reduce'], ['normal motion', 'no-preference']]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: motion });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const count = () => page.locator('.tl-count').innerText().then((t) => +t.replace(/,/g, '').match(/^(\d+)/)[1]);
    try {
      await page.goto(base + '?debug#overview?s=TX', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready, null, { timeout: 25000 });
      await page.waitForFunction(() => /^Texas$/.test(document.querySelector('.nw-grid .nat-panel h3').textContent), null, { timeout: 8000 });
      await page.waitForTimeout(900); // a zoom takes half a second with motion allowed
      const z = await page.evaluate(() => ({ sel: window.__nw.map.selected, rings: window.__nw.map.drawnRings, hero: window.__nw.hero.drawnRings }));
      check(z.sel === 'TX' && z.rings === 0 && z.hero === RING_STATES.length && (await PX(page, '.nw-canvas')) > 300 && (await PX(page, '#hero-canvas')) > 300, label + ': the map zooms to Texas (the rings give way to the panel\'s figures, the hero\'s backdrop keeps its ' + z.hero + ') and is drawn');
      await page.selectOption('.nw-pick', '');
      await page.waitForFunction((n) => window.__nw.map.drawnRings === n, RING_STATES.length, { timeout: 5000 });
      check((await page.evaluate(() => window.__nw.map.selected)) === null, label + ': and back to the country: all ' + RING_STATES.length + ' rings are drawn again');
      await page.locator('.nw-explore .card-tools .btn').click();
      await page.waitForSelector('.tl-bar', { state: 'visible', timeout: 5000 });
      const total = await page.evaluate(() => window.__nw.map.tlCount(window.__nw.map.tlRange[1]));
      if (motion === 'reduce') {
        check((await page.locator('.tl-play').count()) === 0 && (await count()) === total, label + ': the replay has the scrubber alone and opens on every well (' + total + ')');
      } else {
        check((await page.locator('.tl-play').count()) === 1 && (await page.locator('.tl-bar.calm').count()) === 0, label + ': the replay has its play button and starts playing');
        await page.waitForTimeout(400); const c1 = await count(); await page.waitForTimeout(500); const c2 = await count();
        check(c2 > c1 && c2 <= total, label + ': the clock moves and the count only grows (' + c1 + ' then ' + c2 + ' of ' + total + ')');
        await page.locator('.tl-play').click();
        await page.waitForTimeout(150); const p1 = await count(); await page.waitForTimeout(500); const p2 = await count();
        check(p1 === p2 && (await page.locator('.tl-play').getAttribute('aria-label')) !== 'Pause', label + ': pause holds the clock at ' + p1 + ' wells');
        await page.locator('.tl-play').click(); await page.waitForTimeout(400);
        check((await count()) > p2, label + ': play goes on from there');
        await page.locator('.tl-play').click();
      }
      await page.locator('.tl-range').fill(String(Math.round((await page.evaluate(() => window.__nw.map.tlRange[1])) / 2)));
      const half = await count();
      check(half > 0 && half < total, label + ': the scrubber seeks (' + half + ' of ' + total + ' wells at the halfway day)');
      // the rings stay as they are while the wells replay: the agencies' counts are for their last 12 months
      check((await page.evaluate(() => window.__nw.map.drawnRings)) === RING_STATES.length, label + ': the rings stay while the wells replay (the agencies\' counts are for their last 12 months)');
      await page.locator('.nw-explore .card-tools .btn').click();
      await page.waitForFunction(() => document.querySelector('.tl-bar').hidden, null, { timeout: 5000 });
      check(!(await page.locator('.tl-bar').isVisible()) && (await page.evaluate(() => window.__nw.map.count())) === total, label + ': closing the replay brings every well back');
      const ovText = await page.locator('#view-overview').innerText();
      check(!BAD_TEXT.test(ovText) && SUMS.every((n) => !hasNum(ovText, n)), label + ': the same figures, no NaN and no total of the layers');
    } catch (e) {
      check(false, label + ': the Overview: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, label + ': the Overview loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 28. the ranking's two cells are side by side with a header on a wide page and stacked, each with its own label, on a narrow one (860 px and under): at 820, 390 and 360 px every row's words are whole,
  //     nothing runs past its row and the page does not scroll sideways; a row is a button the keyboard reaches and chooses; the hero's figures and buttons scroll to what they name instead of going anywhere
  for (const [label, w, h] of [['desktop', 1280, 900], ['tablet', 820, 900], ['phone', 390, 844], ['narrow phone', 360, 800]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      await page.waitForTimeout(400);
      const stacked = w <= 860;
      const lay = await page.evaluate(() => {
        const rows = [...document.querySelectorAll('.ov-row')]; const head = document.querySelector('.ov-head'); const bad = []; let sideBySide = 0; let stackedN = 0; let labs = 0; let barsTiny = 0;
        for (const r of rows) {
          const rr = r.getBoundingClientRect(); const p = r.querySelector('.ov-p').getBoundingClientRect(); const wc = r.querySelector('.ov-w').getBoundingClientRect();
          if (Math.abs(wc.top - p.top) < 4) sideBySide++; else if (wc.top > p.top + 4) stackedN++;
          const lab = r.querySelector('.ov-p .ov-lab'); if (lab && getComputedStyle(lab).display !== 'none' && lab.getBoundingClientRect().width > 0) labs++;
          const name = r.querySelector('.nat-rn').textContent.slice(r.querySelector('.nat-rc').textContent.length);
          if (r.scrollWidth > r.clientWidth + 1) bad.push(name + ': the row scrolls');
          for (const e of r.querySelectorAll('.nat-rn, .nat-rv, .ov-u, .nat-rd, .ov-none, .ov-lab, .ov-vu')) {
            const b = e.getBoundingClientRect(); if (!b.width) continue;
            if (b.right > rr.right + 1 || b.left < rr.left - 1) bad.push(name + ': ' + e.className + ' leaves its row');
            if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible') bad.push(name + ': ' + e.className + ' is clipped');
          }
          for (const b of r.querySelectorAll('.nat-rt')) if (b.getBoundingClientRect().width < 20) barsTiny++;
        }
        return { n: rows.length, head: getComputedStyle(head).display, sideBySide, stackedN, labs, barsTiny, bad: bad.slice(0, 6), doc: document.documentElement.scrollWidth > document.documentElement.clientWidth };
      });
      check(lay.n === NAT.states.length && !lay.bad.length && !lay.doc && lay.barsTiny === 0 && (stacked ? lay.head === 'none' && lay.stackedN >= lay.n - 1 && lay.sideBySide === 0 && lay.labs === lay.n : lay.head !== 'none' && lay.sideBySide >= lay.n - 1 && lay.stackedN === 0 && lay.labs === 0),
        label + ': the ranking\'s ' + lay.n + ' rows are ' + (stacked ? 'stacked, each cell with its own label ("Oil permits", "Fracked wells"), and the header is gone' : 'two cells side by side under a header') + '; every word whole, nothing past its row, no sideways scroll, every bar visible: ' + JSON.stringify(lay).slice(0, 200));
      // a row is a button, the keyboard reaches each one and Enter chooses it; its name says both counts
      const kb = await page.evaluate(() => { const rows = [...document.querySelectorAll('.ov-row')]; const lab = (r) => r.getAttribute('aria-label');
        return { buttons: rows.every((r) => r.tagName === 'BUTTON' && r.tabIndex === 0),
          names: rows.filter((r) => !r.classList.contains('is-fed')).every((r) => /fractured wells/.test(lab(r)) && /Show it on the map/.test(lab(r)) && /oil permits? approved|spuds|spudded|applications|drilled|not read|no oil permit|no oil permits recorded/.test(lab(r))) && rows.filter((r) => r.classList.contains('is-fed')).every((r) => /never added/.test(lab(r)) && /Show it/.test(lab(r))), first: lab(rows[0]) }; });
      check(kb.buttons && kb.names, label + ': every ranking row is a button the keyboard reaches, named with both counts: ' + kb.first.slice(0, 110));
      await page.locator('.ov-row').first().focus(); await page.keyboard.press('Tab');
      const next = await page.evaluate(() => { const rows = [...document.querySelectorAll('.ov-row')]; const a = document.activeElement; const cs = getComputedStyle(a); return { is: a === rows[1], ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 }; });
      check(next.is && next.ring, label + ': Tab goes from one row to the next and the row shows a focus ring');
      // the hero: a figure or a button scrolls to what it names, and never leaves the page (the address and the history stay)
      const hist0 = await page.evaluate(() => history.length);
      const scroll = [];
      for (const [i, target, by] of [[0, '#ranking', 'permits'], [1, '#ranking', 'wells'], [2, '#explore', null], [3, '#explore', null]]) {
        await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(80);
        await page.locator('#kpis .kpi-chip').nth(i).click(); await page.waitForTimeout(200);
        const r = await page.evaluate(([t, b]) => ({ top: Math.round(document.querySelector(t).getBoundingClientRect().top), y: Math.round(scrollY), hash: location.hash, by: b ? document.querySelector('#ovr-' + b).getAttribute('aria-pressed') : null }), [target, by]);
        scroll.push(r.y > 300 && r.top > -50 && r.top < 200 && r.hash === '#overview' && (by === null || r.by === 'true'));
      }
      await page.evaluate(() => window.scrollTo(0, 0)); await page.locator('#ovr-wells').scrollIntoViewIfNeeded(); await page.locator('#ovr-wells').click();
      await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(80); await page.click('#go-rank'); await page.waitForTimeout(200);
      const goRank = await page.evaluate(() => ({ top: Math.round(document.querySelector('#ranking').getBoundingClientRect().top), by: document.querySelector('#ovr-permits').getAttribute('aria-pressed'), hash: location.hash }));
      scroll.push(goRank.top > -50 && goRank.top < 200 && goRank.by === 'true' && goRank.hash === '#overview');
      check(scroll.every(Boolean) && (await page.evaluate(() => history.length)) === hist0, label + ': the four figures and "State by state" scroll to the ranking (sorted by the figure\'s own layer) or to the map, and leave the address and the history alone: ' + scroll.join());
    } catch (e) {
      check(false, label + ': the ranking: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, label + ': the ranking loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 29. every jurisdiction under every layer (2026-11-02): the Overview's panel and leaders for each of the 36 choices of the selector (the country, 34 jurisdictions and Missouri), with the map showing both layers, the
  //     dots alone and the rings alone, read for NaN, undefined, null and Infinity, the researchers' own words, a total of the two layers (the country's or the state's own), a capital "Federal offshore" inside a sentence and a
  //     zero where a source has no figure; with a page that has all of it (the BLM and Missouri among them)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const VOICE = /\b(this machine|from here|I tried|I read|I saw|the tracker|polite request|the brief|sandbox|WebFetch|HEAD request|reachable)\b/i;
    try {
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      const ids = await page.$$eval('.nw-pick option', (os) => os.map((o) => o.value));
      check(ids.length === 1 + NAT.states.length + NAT.gaps.length && ids[0] === '' && NAT.states.concat(NAT.gaps).every((s) => ids.includes(s.id)), 'the selector offers the country and each of the ' + (ids.length - 1) + ' jurisdictions with a record, Missouri and the BLM among them');
      const dirty = []; let n = 0;
      for (const kind of ['both', 'wells', 'permits']) {
        await page.locator('#nwk-' + kind).click();
        for (const id of ids) {
          await page.selectOption('.nw-pick', id);
          const r = await page.evaluate(() => ({ panel: document.querySelector('.nw-grid .nat-panel').innerText.replace(/\s+/g, ' '), subs: [...document.querySelectorAll('#ov-where-h, #ov-who-h')].map((h) => h.closest('section').querySelector('.sub').textContent), lists: [...document.querySelectorAll('.ov-layer')].map((l) => l.innerText.replace(/\s+/g, ' ')).join(' | '), all: document.querySelector('#view-overview').innerText }));
          n++;
          const p = natOf(id); const g = regOf(id);
          const own = p && g && p.p12 > 0 && g.p12 > 0 ? p.p12 + g.p12 : null;
          const why = [];
          if (BAD_TEXT.test(r.panel + r.subs.join(' ') + r.lists) || BAD_TEXT.test(r.all)) why.push('NaN or null');
          if (VOICE.test(r.panel + r.subs.join(' | '))) why.push('the researchers\' voice');
          if (SUMS.some((x) => hasNum(r.all, x))) why.push('a total of the layers');
          if (own != null && own >= 100 && hasNum(r.panel + r.subs.join(' ') + r.lists, own)) why.push('the state\'s two counts added (' + num(own) + ')');
          if (/[a-z0-9,;:] Federal (offshore|onshore)/.test(r.panel) || r.subs.some((x) => /[a-z0-9,;:] Federal (offshore|onshore)/.test(x))) why.push('"Federal offshore" inside a sentence');
          if (/\(BLM\)’s/.test(r.panel)) why.push('"(BLM)’s"');
          if (r.panel.length < 120) why.push('an empty panel');
          if (why.length) dirty.push(kind + '/' + (id || 'all') + ': ' + why.join(', '));
        }
      }
      check(!dirty.length, 'the panel, the leaders and the page read clean for all ' + n + ' choices (' + ids.length + ' jurisdictions under both layers, the dots alone and the rings alone)' + (dirty.length ? ' [' + dirty.slice(0, 6).join(' | ') + ']' : ''));
    } catch (e) {
      check(false, 'every jurisdiction under every layer: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the sweep loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 20. the Overview and the matrix speak to a visitor (2026-11-01, kept on the merged page): the researchers' own words (this machine, from here, I tried, the tracker) are not on the page, the federal offshore and the BLM
  //     are common nouns inside a sentence, a jurisdiction that is not read yet says why in plain words and what grade its data has, a panel's source link is a page and not a raw download, the matrix shows no producer
  //     plan, and the Sources page lists the state agencies from the report's own data (a file download is not a link)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    const VOICE = /\b(this machine|from here|I tried|I read|I saw|the tracker|polite request|the brief|sandbox|WebFetch|HEAD request|reachable)\b/i;
    try {
      const natDoc = NAT;
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('table.nat-cov', { timeout: 25000 });
      const page0 = await page.locator('#view-overview').innerText();
      check(!VOICE.test(page0) && !/[a-z0-9,;:] Federal (offshore|onshore)/.test(page0), 'the Overview has none of the researchers\' words and says "the federal offshore" and "the BLM" as common nouns inside a sentence');
      const cov = await page.locator('table.nat-cov').innerText();
      check(!VOICE.test(cov) && natDoc.gaps.every((g) => cov.includes(g.name)), 'the coverage table has a plain reason for every jurisdiction not read yet, with none of the researchers\' words');
      check(/Its published data, as researched \(grade [A-D]\): /.test(cov) && !/\bgrade [A-D]\s*$/m.test(cov), 'and a gap\'s grade is explained, not left as a bare letter in the Updates column');
      const rows = await page.evaluate(() => [...document.querySelectorAll('table.nat-cov tbody tr')].map((r) => ({ gap: r.classList.contains('is-gap'), upd: r.children[4].textContent.trim() })));
      check(rows.filter((r) => r.gap).every((r) => r.upd === '—') && rows.filter((r) => !r.gap).every((r) => /^(Publishes|Weekly|Monthly|Nightly|Daily|Irregular|Live|Quarterly|Monthly)/i.test(r.upd) || r.upd.length > 3), 'a jurisdiction not read yet has a dash under Updates; the others say how they update');
      await page.selectOption('.nw-pick', 'FO');
      const fo = await page.locator('.nw-grid .nat-panel').innerText();
      check(/the federal offshore’s permits are counted above/.test(fo) && /Source: /.test(fo) && !/[a-z0-9,;:] Federal offshore/.test(fo), 'a sentence in the federal offshore\'s panel names "the federal offshore"');
      for (const id of ['UT', 'FO', 'BL', 'AZ', 'ND', 'CA']) {
        await page.selectOption('.nw-pick', id);
        const hrefs = await page.locator('.nw-grid .nat-panel a[target="_blank"]').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
        check(hrefs.length >= 1 && hrefs.every((h) => /^https:\/\//.test(h) && !/\.(zip|csv|xlsx?)(\?|$)/i.test(h) && !/FeatureServer|MapServer|rest\/services/i.test(h)), 'the source links in ' + nameOf(id) + '\'s panel are pages, not raw downloads or a service root: ' + hrefs.join(' '));
      }
      await page.goto(base + '#fields?s=MO', { waitUntil: 'load' });
      await page.waitForSelector('#fields-root .nat-panel', { timeout: 25000 });
      const fx = await page.locator('#fields-root .nat-panel').innerText();
      check(!VOICE.test(fx) && !/How a monthly count could be built/.test(fx) && /Updated 2026-11-01/.test(fx), 'the matrix\'s panel for the one jurisdiction not read yet (Missouri) is in a visitor\'s words, shows no producer plan and says what changed since the first research: ' + fx.replace(/\s+/g, ' ').slice(0, 220));
      const ties = await page.locator('#fields-root .nat-kpis').innerText();
      check(/Published by the most agencies/.test(ties), 'the matrix\'s figures load: ' + ties.replace(/\s+/g, ' ').slice(0, 200));
      await page.goto(base + '#about', { waitUntil: 'load' });
      await page.waitForSelector('#src-national li', { timeout: 25000 });
      await page.waitForFunction(() => document.querySelectorAll('#src-national li').length > 5, null, { timeout: 15000 });
      const src = await page.evaluate(() => ({ n: document.querySelectorAll('#src-national li').length, hrefs: [...document.querySelectorAll('#src-national a')].map((a) => a.getAttribute('href')), text: document.querySelector('#src-national').innerText }));
      const wantRows = natDoc.states.filter((x) => !['TX', 'OK', 'NM', 'FO'].includes(x.id)).length + 2;
      check(src.n === wantRows && src.hrefs.every((h) => h && !/\.(zip|csv|xlsx?)(\?|$)/i.test(h) && !/FeatureServer|MapServer|rest\/services/i.test(h)) && !VOICE.test(src.text) && /Not read yet/.test(src.text),
        'the Sources page lists the state agencies behind the Overview\'s oil permit counts from its own data (' + src.n + ' lines for ' + (wantRows - 2) + ' agencies and the unread ones), none linked to a raw download');
      check(await page.evaluate(() => [...document.querySelectorAll('.toc button')].some((b) => /State agencies behind/.test(b.textContent))), 'and its heading is in the page\'s table of contents');
    } catch (e) {
      check(false, 'the wording block: ' + e.message.split('\n')[0].slice(0, 240));
    }
    check(!errs.length, 'the wording pages load clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 21. layout and keyboard of the Overview's lists and chart, and of the matrix (2026-11-01, from the other session's review): an operator's name is whole (it wrapped to a second line instead of ending in an ellipsis
  //     at 100 px), the month chart is drawn at the width it has and again when the window changes size (its axis text is not shrunk to a quarter on a phone: the card is built before it is on the page and has no width
  //     then), its axis tops near the data, the matrix has a few tab stops and not 1,680 (the arrow keys move between cells), its group strip wraps instead of hiding choices, and an address without a layer or a state
  //     shows both layers and the country (the page kept the last choice)
  for (const [label, size] of [['desktop', { width: 1280, height: 900 }], ['tablet', { width: 820, height: 900 }], ['phone', { width: 360, height: 800 }]]) {
    const ctx = await browser.newContext({ viewport: size, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('requestfailed', (r) => errs.push('request failed: ' + r.url()));
    try {
      await page.goto(base + '#overview?s=TX', { waitUntil: 'load' });
      await page.waitForSelector('.ov-layer .ov-list li', { timeout: 25000 });
      await page.waitForTimeout(300);
      const names = await page.evaluate(() => [...document.querySelectorAll('.ov-layer .nat-ln')].map((n) => ({ t: n.textContent, cut: n.scrollWidth > n.clientWidth + 1, lines: Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)) })));
      check(names.length > 24 && names.every((n) => !n.cut && n.lines <= 2) && !names.some((n) => /…$/.test(n.t)), label + ': every name in the leaders\' lists (counties and operators, the agency\'s and the registry\'s) is whole, on one or two lines (' + names.length + ' names, the longest ' + Math.max(...names.map((n) => n.t.length)) + ' characters)');
      const chart = () => page.evaluate(() => { const g = document.querySelector('svg.ov-chart'); const vb = g.viewBox.baseVal; const ax = g.querySelector('text.ax'); const k = g.getBoundingClientRect().width / vb.width;
        return { ratio: k, axis: parseFloat(getComputedStyle(ax).fontSize) * k, vbw: vb.width, ticks: [...g.querySelectorAll('text.ax')].map((t) => t.textContent.replace(/,/g, '')).filter((t) => /^\d+$/.test(t)).map(Number),
          twin: [...document.querySelectorAll('details.nat-details tbody tr')].map((tr) => [1, 2, tr.children.length - 1].map((i) => +tr.children[i].textContent.replace(/,/g, '') || 0)).flat() }; });
      const c0 = await chart();
      check(c0.ratio > 0.9 && c0.ratio < 1.1 && c0.axis >= 10, label + ': the month chart is drawn at the width it has (scale ' + c0.ratio.toFixed(2) + ', axis text ' + c0.axis.toFixed(1) + ' px, drawn ' + c0.vbw + ' wide)');
      check(Math.max(...c0.ticks) >= Math.max(...c0.twin) && Math.max(...c0.ticks) <= Math.max(...c0.twin) * 1.5, label + ': the axis tops at ' + Math.max(...c0.ticks) + ' for a tallest month of ' + Math.max(...c0.twin));
      // the window changes size: the chart is drawn again at the new width (and not for a change of a few pixels)
      const other = label === 'desktop' ? { width: 380, height: 800 } : { width: 1100, height: 900 };
      await page.setViewportSize(other);
      await page.waitForFunction((w) => Math.abs(document.querySelector('svg.ov-chart').viewBox.baseVal.width - w) > 100, c0.vbw, { timeout: 5000 });
      const c1 = await chart();
      check(c1.vbw !== c0.vbw && c1.ratio > 0.9 && c1.ratio < 1.1 && c1.axis >= 10, label + ': and drawn again when the window changes size (' + c0.vbw + ' wide, then ' + c1.vbw + ' at scale ' + c1.ratio.toFixed(2) + ', axis text ' + c1.axis.toFixed(1) + ' px)');
      await page.setViewportSize(size);
      // an address without a layer or a state shows both layers and the country, even after a visit to one layer of one state
      await page.goto(base + '#overview?s=TX&k=permits', { waitUntil: 'load' });
      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      await page.goto(base + '#fields', { waitUntil: 'load' });
      await page.goto(base + '#overview', { waitUntil: 'load' });
      await page.waitForSelector('.ov-row', { timeout: 25000 });
      check((await page.locator('#nwk-both').getAttribute('aria-pressed')) === 'true' && (await page.locator(OV_PANEL).first().innerText()) === 'All states' && (await hashNow(page)) === '#overview', label + ': #overview after a visit to Texas with only the permits shows both layers and all states again');
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
        check(right && down && right !== first0 && down.split(', ')[0] === right.split(', ')[0] && down !== right && end.stops === 1 && /\/?s=/.test(await hashNow(page)), 'the arrow keys move between cells (right: ' + right + ' / down: ' + down + ' / end: ' + end.label + '), the tab stop goes with the focus, and Enter chooses a cell');
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
      // the card's newest row is the newest day any of the three states has a report for (Texas's capture can end a day before Oklahoma's and New Mexico's), not Texas's newest
      const newestIdx = ['daily', 'daily-ok', 'daily-nm'].map((dir) => { const days = readIdx(dir); return days[days.length - 1].d; }).sort().pop();
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

  // 23. a change from a small base is not a percent (2026-11-01): California went from 2 permits to 372, which read "+18500%" in its panel; the panel says the base in words, and no ranking row, tile or tooltip shows the percent
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    try {
      await page.goto(base + '#overview?s=CA', { waitUntil: 'load' });
      await page.waitForSelector('.nw-grid .nat-panel .nat-big', { timeout: 25000 });
      const big = await page.locator('.nw-grid .nat-panel .nat-big').first().innerText();
      check(!/\+\s?\d{3,}\s?%/.test(big) && /\(\d[\d,]* the 12 months before\)/.test(big), 'California\'s panel gives its base in words and no percent from a base under 20: ' + big.replace(/\s+/g, ' ').slice(0, 120));
      const rows = await page.evaluate(() => [...document.querySelectorAll('.ov-row')].map((r) => r.innerText).filter((t) => /\+\d{4,}%/.test(t)));
      const caRow = await page.locator('.ov-row', { hasText: 'California' }).locator('.ov-p').innerText();
      check(rows.length === 0 && /n\/a/.test(caRow) && !/%/.test(caRow), 'no ranking row shows a percent over a thousand and California\'s says n/a: ' + caRow.replace(/\s+/g, ' '));
      // no tooltip does either: the ring of California, the month chart and every ranking row's own cells hold no percent from a base under 20
      const small = NAT.states.filter((s) => s.prev12 < 20 && s.p12 > 0).map((s) => s.id);
      const bad = [];
      for (const id of small) {
        const row = await page.evaluate((i) => { const s = [...document.querySelectorAll('.ov-row')].find((r) => r.querySelector('.nat-rn').textContent.endsWith(i)); return s ? s.querySelector('.ov-p').innerText : ''; }, nameOf(id).replace(/ \(BLM\)$/, ''));
        if (/[+−-]\d+%/.test(row)) bad.push(id + ': ' + row.replace(/\s+/g, ' '));
      }
      check(small.length >= 3 && !bad.length, 'the ' + small.length + ' agencies whose year before is under 20 (' + small.join(', ') + ') show no percent in the ranking' + (bad.length ? ' [' + bad.join(' | ') + ']' : ''));
    } catch (e) {
      check(false, 'a change from a small base: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the California panel loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 21c. zoomed to one state with only the oil permits shown, the map is not empty: that state's own ring is drawn (with the wells shown too the rings give way to the panel's figures, block 27)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push('page error: ' + e.message.slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    try {
      await page.goto(base + '?debug#overview?s=TX&k=permits', { waitUntil: 'load' });
      await page.waitForFunction(() => window.__nw && window.__nw.map.ready && window.__nw.map.selected === 'TX', null, { timeout: 25000 });
      await page.waitForTimeout(700);
      const one = await page.evaluate(() => ({ rings: window.__nw.map.drawnRings, at: window.__nw.map.screenOfRing('TX'), r: window.__nw.map.ringRadiusOf('TX') }));
      check(one.rings === 1 && (await PX(page, '.nw-canvas')) > 300, 'zoomed to Texas with only the oil permits shown, the map is not empty: Texas\'s own ring is drawn (' + one.rings + ' ring)');
      await page.locator('#nwk-both').click(); await page.waitForTimeout(300);
      check((await page.evaluate(() => window.__nw.map.drawnRings)) === 0, 'and with both layers the rings give way again (the panel gives the figures)');
    } catch (e) {
      check(false, 'zoomed with only the permits: ' + e.message.split('\n')[0].slice(0, 220));
    }
    check(!errs.length, 'the zoomed permits-only map loads clean' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close();
  }

  // 22. the Companies table's Segment cell is a table cell (its class once collided with the segmented control's, which made each one a pill)
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    try {
      await page.goto(base + '#companies?kind=directory', { waitUntil: 'load' });
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
