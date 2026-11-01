// A stubbed day of the Texas Daily archive that has readable previews, for the browser tests (smoke.cjs, a11y.cjs). No committed day has previews yet (they begin with the first
// capture after the change that made them), so the newest real day is copied and given: three permits whose filings are published (a letter and a plat each, but one plat
// has no preview), fourteen directional surveys with previews, and a release that says so (`previews`, `noPreview`). The GitHub hosts that previews are loaded from are answered
// here with a one-pixel PNG, so no test touches the network; one preview (BAD) answers 404, to see what a picture that does not load looks like.
'use strict';
const fs = require('fs');
const path = require('path');

const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC', 'base64'); // 1 x 1, white
const BAD = '0900003_W1.pdf.jpg'; // answers 404
const NO_PREVIEW = '0900002_Plat_1.pdf'; // a document the release holds no preview of

const isGithub = (url) => url.protocol === 'https:' && (url.hostname === 'github.com' || url.hostname.endsWith('.githubusercontent.com'));

function stubDay(root) {
  const days = JSON.parse(fs.readFileSync(path.join(root, 'data', 'daily', 'index.json'), 'utf8')).days.map((r) => r.d).sort();
  // the newest day that has a permits section: a day can have none (the first live capture of a month, when the Daily Permit File has no record yet: 2026-11-01), and the stub gives that section its rows
  const read = (d) => JSON.parse(fs.readFileSync(path.join(root, 'data', 'daily', d + '.json'), 'utf8'));
  const day = [...days].reverse().find((d) => read(d).permits);
  const stub = read(day);
  const row = (n, depth, lat, lon, docs) => ['09000' + n, '301', '08', '1', null, depth, 'H', '301001' + n, lat, lon, docs];
  stub.permits = Object.assign({}, stub.permits, { rows: [row('01', 9000, 31.80, -103.60, ['W1.pdf', 'Plat_1.pdf']), row('02', 9100, 31.81, -103.61, ['W1.pdf', 'Plat_1.pdf']), row('03', 9200, 31.82, -103.62, ['W1.pdf'])] });
  const surveys = [];
  for (let i = 0; i < 14; i++) surveys.push(['3010000' + (i % 10), '301', i % 2 ? 'O' : 'M', 9000, 9500, '2026-10-01', '2026-10-02', '1', String(5000000 + i), 31.8 + i / 1000, -103.6]);
  stub.surveys = { day: stub.permits.day, n: surveys.length, rows: surveys };
  const files = 5 + surveys.length;
  stub.release = { repo: 'o/r', tag: 'daily-' + day, files, bytes: 1234567, permits: 3, surveys: surveys.length, previews: files - 1, noPreview: [NO_PREVIEW] };
  return { day, stub };
}

// serve the stub for its day and answer GitHub; returns the addresses asked of GitHub so far, and a function that takes the routes off again
async function install(page, root, { failing = BAD } = {}) {
  const { day, stub } = stubDay(root);
  const asked = [];
  const dayRoute = (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(stub) });
  const ghRoute = (route) => {
    const u = route.request().url();
    asked.push(u);
    if (failing && u.endsWith('/' + failing)) return route.fulfill({ status: 404, contentType: 'text/plain', body: 'not found' });
    return route.fulfill({ status: 200, contentType: 'image/png', body: PNG });
  };
  await page.route('**/data/daily/' + day + '.json', dayRoute);
  await page.route(isGithub, ghRoute);
  return { day, stub, asked, off: async () => { await page.unroute('**/data/daily/' + day + '.json', dayRoute); await page.unroute(isGithub, ghRoute); } };
}

module.exports = { PNG, BAD, NO_PREVIEW, isGithub, stubDay, install };
