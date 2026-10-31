// Tests for the pure JavaScript data code: which states are shown (states.js), what the Overview merges from them (overview-data.js, the
// permit points merge) and the Daily report's merge rules (daily-data.js). No browser, no network: synthetic files, plus the committed ones
// for shape and consistency checks.
//
// Run: node tests/test_js_data.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(HERE, '..', 'site', 'public', 'js');
const DATA = path.join(HERE, '..', 'site', 'public', 'data');
const imp = (f) => import(pathToFileURL(path.join(JS, f)).href);
const S = await imp('states.js');
const O = await imp('overview-data.js');
const D = await imp('daily-data.js');
const read = (n) => JSON.parse(fs.readFileSync(path.join(DATA, n + '.json'), 'utf8'));

let fails = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) fails++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---------- states.js ---------- */
const ids = S.STATES.map((s) => s.id);
check(ids[0] === 'TX' && S.STATES[0].files === null && S.otherStates.every((s) => s.files && s.files.series && s.files.county && s.files.operators && s.files.points && s.files.geo), 'Texas is first and has no files entry; every other state lists its geo, series, county, operators and points files');
check(same(S.parseStates('ok'), ['OK']) && same(S.parseStates('TX'), ['TX']) && same(S.parseStates(null), ids) && same(S.parseStates(''), ids) && same(S.parseStates('xx'), ids), 'parseStates: one state, none, and anything that is not a state (all of them)');
check(same(S.parseStates('tx,ok'), ['TX', 'OK']) && same(S.parseStates('ok, tx'), ['TX', 'OK']), 'parseStates: a list, in the order of STATES');
check(S.stateParam(ids) === null && S.stateParam(['OK']) === 'ok' && S.stateParam(['TX']) === 'tx', 'stateParam: nothing for all of them, the lowercase id for one');
check(S.countyKey('TX', '001') === '001' && S.countyKey('OK', '001') === 'OK:001' && S.countyState('001') === 'TX' && S.countyState('OK:001') === 'OK' && S.countyCode('OK:001') === '001' && S.countyCode('001') === '001', 'county keys: Texas plain, every other state prefixed, and back again');
check(S.pointCountyKey(48) === '048' && S.pointCountyKey(S.POINT_BLOCK * S.stateIndex('OK') + 129) === 'OK:129' && S.pointState(S.POINT_BLOCK + 1) === 'OK', 'permit point counties: the state number times 1000 plus the code');
check(S.pointCountyKey(S.POINT_BLOCK * S.stateIndex('NM') + 45) === 'NM:045' && S.pointState(2 * S.POINT_BLOCK) === 'NM' && same(S.parseStates('nm'), ['NM']) && same(S.parseStates('tx,nm'), ['TX', 'NM']) && S.stateParam(['TX', 'NM']) === 'tx,nm', 'New Mexico: its point counties, its place in an address and in a list');
check(S.measureOf('TX').id === 'permits' && S.measureOf('OK').id === 'permits' && S.measureOf('NM').id === 'spuds' && S.sameMeasure(['TX', 'OK']) && !S.sameMeasure(['OK', 'NM']) && S.sameMeasure(['NM']), 'measures: Texas and Oklahoma count permits, New Mexico wells spudded, and only like is added to like');
check(S.measurePhrase(['TX']) === 'new-drill permits' && S.measurePhrase(['NM']) === 'wells spudded' && S.measurePhrase(['TX', 'OK']) === 'new-drill permits' && S.measurePhrase(['TX', 'OK', 'NM']) === 'new-drill permits (wells spudded in New Mexico)' && S.measurePhrase(['NM', 'TX']) === 'new-drill permits (wells spudded in New Mexico)', 'measurePhrase names what a mixed set counts');
check(S.listAnd(['Texas']) === 'Texas' && S.listAnd(['Texas', 'Oklahoma']) === 'Texas and Oklahoma' && S.listAnd(['Texas', 'Oklahoma', 'New Mexico']) === 'Texas, Oklahoma and New Mexico' && S.statesName(ids) === 'Texas, Oklahoma and New Mexico', 'listAnd and statesName: a list of states reads like English');
check(S.measureLabel(['TX']) === 'New-drill permits' && S.measureLabel(['TX', 'OK']) === 'New-drill permits' && S.measureLabel(['NM']) === 'Wells spudded' && S.measureLabel(['TX', 'NM']) === 'Permits and spuds' && S.measureLabel(ids) === 'Permits and spuds', 'measureLabel: what a map or a table calls its counts, and "Permits and spuds" when the states differ');
check(S.stateOf('TX').fips === '48' && S.stateOf('OK').fips === '40' && S.stateOf('NM').fips === '35', 'each state knows its FIPS code (a county\'s FIPS is the state\'s and its three digits)');
check(S.dailyStates.map((q) => q.id).join() === 'TX,OK,NM' && S.STATES.find((q) => q.id === 'NM').dir === 'daily-nm' && S.STATES.every((q) => !q.dir || /^daily/.test(q.dir)), 'every state has a Daily report folder (a state with none would have a null one, and nothing would ask for it)');
{
  const heard = [];
  const off = S.onStates((x) => heard.push(x.join('+')));
  const before = S.activeStates().join('+');
  check(S.setStates(['OK']) === true && heard.length === 1 && heard[0] === 'OK' && S.activeStates().join() === 'OK', 'setStates tells its subscribers once, with the new list');
  check(S.setStates(['OK']) === false && heard.length === 1, 'setting what is already set tells nobody');
  check(S.setStates([]) === false && S.setStates(['ZZ']) === false && S.activeStates().join() === 'OK', 'an empty list or no known state changes nothing');
  check(S.setStates(ids, true) === true && heard.length === 1 && S.activeStates().join('+') === before, 'a quiet set changes the choice without telling anybody');
  off();
  S.setStates(['TX']); check(heard.length === 1, 'an unsubscribed listener hears nothing more');
  S.setStates(ids, true);
}

/* ---------- overview-data.js, on synthetic files ---------- */
const tx = { months: ['2025-01', '2025-02', '2025-03'], permits: [100, 110, 120], asOf: '2026-10-29', counties: { '003': { p12: 5, p12prev: 4, m: [], depth: 1, ops: [['ACME LLC', '100', 5]] } } };
const ok = { months: ['2025-01', '2025-02'], permits: [10, 11], asOf: '2026-10-30', through: '2026-10-30', counties: { '003': { p12: 7, p12prev: 6, m: [], depth: 2, ops: [['OKIE INC', '77', 7]] } } };
{
  const sp = O.permitSeries(['TX', 'OK'], { TX: tx, OK: ok });
  check(same(sp.months, ['2025-01', '2025-02']) && same(sp.permits, [110, 121]) && same(sp.by.TX, [100, 110]) && same(sp.by.OK, [10, 11]) && same(sp.ids, ['TX', 'OK']), 'permitSeries: the months every state has (a lagging file ends the series, a missing month is not counted as zero), summed, and each state\'s own');
  check(same(O.permitSeries(['TX'], { TX: tx, OK: ok }).permits, [100, 110, 120]) && O.permitSeries(['OK'], { TX: tx }) === null && same(O.permitSeries(['TX', 'OK'], { TX: tx }).ids, ['TX']), 'permitSeries: one state is its own series; a state with no file is left out, none at all is null');
  const nm = { months: ['2025-01', '2025-02', '2025-03', '2025-04'], permits: [1, 2, 3, 4], asOf: '2026-08-31', through: '2026-08-31', counties: { '025': { p12: 9, p12prev: 8, m: [], depth: null, ops: [['EOG INC', '7377', 9]] } } };
  const spn = O.permitSeries(['TX', 'OK', 'NM'], { TX: tx, OK: ok, NM: nm });
  check(same(spn.summed, ['TX', 'OK']) && same(spn.permits, [110, 121]) && same(spn.ids, ['TX', 'OK', 'NM']) && same(spn.own.NM.permits, [1, 2, 3, 4]) && same(spn.own.TX.months, tx.months), 'permitSeries: New Mexico counts something else, so it is not added in (the sum is Texas and Oklahoma on their common months) and keeps its own series on its own months');
  const only = O.permitSeries(['NM'], { NM: nm });
  check(same(only.summed, ['NM']) && same(only.permits, [1, 2, 3, 4]), 'permitSeries: with only New Mexico shown, its own spuds are the series');
  check(O.ownTotals(spn, 'NM').to === '2025-04' || O.ownTotals({ own: { NM: { months: Array.from({ length: 24 }, (_, i) => 'm' + i), permits: Array(24).fill(2) } } }, 'NM').last === 24, 'ownTotals reads a state\'s own last 12 months');
  const cpn = O.countyPermits(['TX', 'OK', 'NM'], { TX: tx, OK: ok, NM: nm });
  check(same(cpn.monthsBy.TX, tx.months) && same(cpn.monthsBy.NM, nm.months) && cpn.asOfBy.NM === '2026-08-31' && cpn.asOfBy.TX === '2026-10-29' && cpn.asOf === '2026-10-30', 'countyPermits: each state keeps its own months and last day (the files end on different days), asOf is still the latest');
  check(same(O.operatorExtras({ prev12: 3, depth: 9000, county: 'OK:003', counties: 4, m24: [1, 2], new12: 5, spud12: 7 }), { prev12: 3, spud12: null, depth: 9000, fips: 'OK:003', counties: 4, m24: [1, 2] }), 'operatorExtras: what only Texas has (a reported spud count) is null for another state, never a copy of the permit count');
  check(same(Object.keys(cpn.counties), ['003', 'OK:003', 'NM:025']) && cpn.counties['NM:025'].ops[0][1] === 'NM:7377', 'countyPermits: New Mexico\'s counties and operators are keyed NM:');
  const t = O.permitTotals({ months: Array.from({ length: 24 }, (_, i) => 'm' + i), permits: [...Array(12).fill(1), ...Array(12).fill(3)] });
  check(t.last === 36 && t.prior === 12 && t.from === 'm12' && t.to === 'm23', 'permitTotals: the last 12 months and the 12 before');
  const cp = O.countyPermits(['TX', 'OK'], { TX: tx, OK: ok });
  check(same(Object.keys(cp.counties), ['003', 'OK:003']) && cp.counties['003'].p12 === 5 && cp.counties['OK:003'].p12 === 7 && cp.asOf === '2026-10-30', 'countyPermits: Texas keeps its plain codes, Oklahoma\'s are prefixed, and asOf is the later day');
  check(cp.counties['OK:003'].ops[0][1] === 'OK:77' && cp.counties['003'].ops[0][1] === '100' && ok.counties['003'].ops[0][1] === '77', 'countyPermits: another state\'s operator numbers are prefixed, without changing the file');
  const doc = { cols: ['band', 'num', 'name', 'new12', 'county', 'newDrill'], rows: [['A', '77', 'OKIE INC', 12, '003', 1], ['C', '78', 'OTHER LLC', 0, '', 0]] };
  const rows = O.stateOperatorRows('OK', doc);
  check(rows[0].num === 'OK:77' && rows[0].rawNum === '77' && rows[0].county === 'OK:003' && rows[1].county === '' && rows[0].st === 'OK' && rows[0]._i === 0, 'stateOperatorRows: objects like the Texas table\'s, number and county keyed by state');
  const txTable = { cols: ['band', 'num', 'name', 'new12'], rows: [['A', '100', 'ACME LLC', 20], ['B', '101', 'BETA INC', 3]] };
  const all = O.operatorRows(['TX', 'OK'], txTable, { OK: doc });
  check(all.length === 4 && all[0].st === 'TX' && all[2].st === 'OK' && O.operatorRows(['OK'], txTable, { OK: doc }).length === 2 && O.operatorRows(['OK'], null, {}).length === 0, 'operatorRows: the states shown, each row tagged, a missing file gives none');
  check(O.drillingNow(all) === 3 && O.newToDrilling(all) === 1, 'drillingNow counts bands A and B; newToDrilling the first-time drillers');
  const tie = [{ v: 5, _i: 2 }, { v: 9, _i: 1 }, { v: 5, _i: 0 }];
  check(same(O.topBy(tie, 'v', 3).map((r) => r._i), [1, 0, 2]), 'topBy: biggest first, ties in file order');
  check(O.countyLabel('Midland', 'TX', false) === 'Midland' && O.countyLabel('Midland', 'TX', true) === 'Midland, TX', 'countyLabel names the state only when several are shown');
  const idx = { days: [{ d: '2026-10-29', k: 'live', w: 100 }, { d: '2026-10-30', k: 'live' }, { d: '2026-10-31', k: 'reconstructed', w: 5 }] };
  check(same(O.activeWells(idx), { n: 100, day: '2026-10-29' }) && O.activeWells({ days: [{ d: 'x', k: 'live' }] }) === null && O.activeWells(null) === null, 'activeWells: the newest live day that counted wells');
}

/* ---------- the permit points merge ---------- */
{
  const pm = (asOf, ops, pts) => ({ asOf, t0: '2024-01-01', ops, opNums: ops.map((_, i) => String(i + 1)), cols: ['lat', 'lon', 'op', 't', 'depth', 'fips'], pts, coverage: { share12: 0.4, share24: 0.7 } });
  const txp = pm('2026-10-29', ['A CO', 'B CO'], [[300000, -1000000, 0, 100, 50, 301], [300000, -1000000, -1, 1000, 60, 3]]);
  const okp = pm('2026-10-30', ['C INC'], [[350000, -980000, 0, 1001, 70, 129], [350000, -980000, -1, 5, 70, 17]]);
  check(O.mergePoints([{ id: 'TX', pm: txp }]) === txp, 'mergePoints: Texas alone is the Texas file itself');
  const m = O.mergePoints([{ id: 'TX', pm: txp }, { id: 'OK', pm: okp }]);
  check(same(m.ops, ['A CO', 'B CO', 'C INC']) && same(m.opNums, ['1', '2', 'OK:1']) && m.pts[2][2] === 2 && m.pts[3][2] === -1, 'mergePoints: operator indexes follow the merged list, unnamed stay -1, another state\'s numbers are prefixed');
  check(m.pts[2][5] === 1129 && m.pts[3][5] === 1017 && m.pts[0][5] === 301, 'mergePoints: Oklahoma\'s county codes are offset by 1000, Texas\'s are untouched');
  // 2026-10-29 is day 972 from 2024-01-01 (cut 607); 2026-10-30 is day 973 (cut 608)
  check(m.pts[1][6] === 1 && m.pts[0][6] === 0 && m.pts[2][6] === 1 && m.pts[3][6] === 0, 'mergePoints: whether a point is recent is against its own state\'s last day');
  check(same(Object.keys(m.coverageBy), ['TX', 'OK']) && m.asOf === '2026-10-30' && m.coverage === undefined, 'mergePoints: coverage per state, the later asOf');
  let threw = false;
  try { O.mergePoints([{ id: 'TX', pm: txp }, { id: 'OK', pm: { ...okp, t0: '2025-01-01' } }]); } catch (e) { threw = true; }
  check(threw, 'mergePoints refuses files that count days from different starts');
}

/* ---------- the committed files, together ---------- */
{
  const files = Object.fromEntries(S.STATES.map((s) => [s.id, null]));
  files.TX = { series: read('series-permits'), county: read('county-permits'), points: read('permits'), geo: read('counties.geo') };
  for (const q of S.otherStates) files[q.id] = { series: read(q.files.series), county: read(q.files.county), points: read(q.files.points), geo: read(q.files.geo), operators: read(q.files.operators) };
  const docs = (kind) => Object.fromEntries(S.STATES.map((s) => [s.id, files[s.id][kind]]));
  const sp = O.permitSeries(ids, docs('series'));
  const total = sp.permits.reduce((a, b) => a + b, 0);
  check(sp.months.length >= 24 && total === sp.summed.reduce((t, id) => t + sp.by[id].reduce((a, b) => a + b, 0), 0) && sp.ids.length === ids.length && ids.every((id) => sp.own[id].months.length >= 24), 'the committed series merge into one of at least 24 months that adds up (' + sp.summed.join(' + ') + '): ' + sp.months[0] + ' to ' + sp.months[sp.months.length - 1]);
  const cp = O.countyPermits(ids, docs('county'));
  const geoKeys = new Set(S.STATES.flatMap((s) => files[s.id].geo.features.map((f) => S.countyKey(s.id, f.properties.f))));
  check(Object.keys(cp.counties).every((k) => geoKeys.has(k)), 'every county with permits (' + Object.keys(cp.counties).length + ') is a county on the map');
  for (const q of S.otherStates) {
    const rows = O.stateOperatorRows(q.id, files[q.id].operators);
    const gk = new Set(files[q.id].geo.features.map((f) => S.countyKey(q.id, f.properties.f)));
    check(rows.length > 0 && rows.every((r) => r.county === '' || gk.has(r.county)) && new Set(rows.map((r) => r.num)).size === rows.length, q.name + ': ' + rows.length + ' operators, each top county on the map, numbers unique');
  }
  const pm = O.mergePoints(ids.map((id) => ({ id, pm: files[id].points })));
  const keyOk = pm.pts.every((p) => geoKeys.has(S.pointCountyKey(p[5])));
  check(pm.pts.length === ids.reduce((t, id) => t + files[id].points.pts.length, 0) && keyOk, 'the merged permit points (' + pm.pts.length + ') all fall in a county on the map');
}

/* ---------- the Daily report's merge rules are still the same after the states moved into states.js ---------- */
{
  // the Daily report's permits by day: from the state's own file where it has one (Texas, New Mexico), else from the report index
  const idx = { days: [{ d: '2026-10-27', dd: '2026-10-26', pn: 4, p: 5, pd: 3 }, { d: '2026-10-28', dd: '2026-10-27', pn: 6, p: 6, pd: 6 }, { d: '2026-10-29', dd: '2026-10-27', pn: 2, p: 2, pd: 2 }] };
  const own = { days: ['2026-10-26', '2026-10-27', '2026-10-28'], newDrill: [9, 8, 7], total: [9, 8, 7], horizontal: [9, 7, 7] };
  const nm = D.permitSeries('NM', idx, own);
  check(same(nm.get('2026-10-27'), { n: 8, total: 8, h: 7 }) && nm.lo === '2026-10-26' && nm.hi === '2026-10-28' && nm.get('2026-10-29') === null && nm.get('2026-10-25') === null, 'permitSeries: a state with its own file of permits by day reads it (New Mexico\'s, rewritten each night), and a day past its last is no data, not zero');
  const okIdx = D.permitSeries('OK', idx, null);
  check(same(okIdx.get('2026-10-26'), { n: 4, total: 5, h: 3 }) && same(okIdx.get('2026-10-27'), { n: 6, total: 6, h: 6 }) && okIdx.get('2026-10-29') === null, 'permitSeries: with no file the days come from the index, the first report to list a permit day counting it');
  const gap = D.permitSeries('NM', idx, { days: ['2026-10-20', '2026-10-23'], newDrill: [3, 4], total: [3, 4], horizontal: [3, 4] });
  check(same(gap.get('2026-10-21'), { n: 0, total: 0, h: 0 }), 'permitSeries: a day inside the window with no row (a weekend or a holiday) is a zero');
  const days = D.mergeDays({ TX: { days: [{ d: '2026-10-29', k: 'live', pFresh: true, pn: 30 }] }, OK: { days: [{ d: '2026-10-29', k: 'live', pFresh: true, pn: 7 }] }, NM: { days: [{ d: '2026-10-28', k: 'reconstructed', pFresh: true, pn: 5 }, { d: '2026-10-29', k: 'live', pFresh: true, pn: 5 }] } }, ['TX', 'OK', 'NM']);
  check(days.length === 2 && days[1].total === 42 && !days[1].partial && days[0].partial && days[0].total === 5 && days[1].live, 'mergeDays: three states in one list of days, a day one of them has no report for is partial, and the total adds what there is');
}
check(D.STATES === S.STATES && D.parseStates === S.parseStates && D.ck('OK', '001') === 'OK:001', 'daily-data.js re-exports the states and keys the Daily report\'s counties by state, Texas too');

console.log('\n' + (fails ? 'FAILED ' + fails : 'all passed'));
process.exit(fails ? 1 : 0);
