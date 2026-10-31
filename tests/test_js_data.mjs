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
check(S.listAnd(['Texas']) === 'Texas' && S.listAnd(['Texas', 'Oklahoma']) === 'Texas and Oklahoma' && S.listAnd(['Texas', 'Oklahoma', 'New Mexico']) === 'Texas, Oklahoma and New Mexico' && S.statesName(ids) === 'Texas, Oklahoma, New Mexico and Federal offshore' && S.statesIn(ids) === 'Texas, Oklahoma, New Mexico and the federal offshore' && S.listOr(['Oklahoma', 'New Mexico', 'the federal offshore']) === 'Oklahoma, New Mexico or the federal offshore' && S.listOr(['Texas']) === 'Texas', 'listAnd, statesName, statesIn and listOr: a list of states reads like English (a sentence says "the federal offshore")');
check(S.measureLabel(['TX']) === 'New-drill permits' && S.measureLabel(['TX', 'OK']) === 'New-drill permits' && S.measureLabel(['NM']) === 'Wells spudded' && S.measureLabel(['TX', 'NM']) === 'Permits and spuds' && S.measureLabel(ids) === 'Permits and spuds', 'measureLabel: what a map or a table calls its counts, and "Permits and spuds" when the states differ');
// the federal offshore: a fourth state that counts wells spudded, with areas where the others have counties, no FIPS code and no Daily report
check(ids.join() === 'TX,OK,NM,FO' && S.stateIndex('FO') === 3 && S.pointCountyKey(S.POINT_BLOCK * S.stateIndex('FO') + 24) === 'FO:024' && S.pointState(3 * S.POINT_BLOCK + 36) === 'FO' && S.countyState('FO:024') === 'FO' && S.countyKey('FO', '024') === 'FO:024'
  && same(S.parseStates('fo'), ['FO']) && same(S.parseStates('ok,fo'), ['OK', 'FO']) && S.stateParam(['FO']) === 'fo' && S.stateParam(['TX', 'OK', 'NM']) === 'tx,ok,nm', 'the federal offshore: its point counties (area 024 is 3024), its place in an address and in a list; the three land states alone are no longer "all"');
check(S.measureOf('FO').id === 'spuds' && S.sameMeasure(['NM', 'FO']) && !S.sameMeasure(['TX', 'FO']) && S.measurePhrase(['NM', 'FO']) === 'wells spudded' && S.measurePhrase(['TX', 'FO']) === 'new-drill permits (wells spudded in the federal offshore)'
  && S.measurePhrase(ids) === 'new-drill permits (wells spudded in New Mexico and the federal offshore)' && S.measureLabel(['NM', 'FO']) === 'Wells spudded' && S.measureLabel(ids) === 'Permits and spuds',
  'the federal offshore counts wells spudded like New Mexico: only like is added to like, and the states that count spuds are named together');
check(S.shortName('FO') === 'Offshore' && S.shortName('TX') === 'Texas' && S.inName('FO') === 'the federal offshore' && S.inName('NM') === 'New Mexico' && S.stateOf('FO').fips === null && S.stateOf('FO').drill === 'the Gulf drill',
  'the federal offshore: a short label for the bar, "the federal offshore" in a sentence, no FIPS code, "Watch the Gulf drill"');
check(S.placeTitle('TX', 'Midland') === 'Midland County' && S.placeTitle('FO', 'Green Canyon') === 'Green Canyon area' && S.placesWord(['TX']) === 'counties' && S.placesWord(['FO']) === 'areas' && S.placesWord(['TX', 'OK', 'NM']) === 'counties'
  && S.placesWord(ids) === 'counties and areas' && S.placesOne(ids) === 'county and area' && S.placesOr(ids) === 'county or area' && S.placesOr(['FO']) === 'area', 'a state\'s places are named for what they are: counties, but protraction areas offshore');
check(S.spudsNote(['TX', 'OK']) === '' && S.spudsNote(['NM']) === 'New Mexico counts wells spudded, not permits (its regulator publishes no approval dates by well)'
  && S.spudsNote(['FO']) === 'The federal offshore counts wells spudded, not permits (its regulator publishes no approval dates by well)'
  && S.spudsNote(ids) === 'New Mexico and the federal offshore count wells spudded, not permits (their regulators publish no approval dates by well)' && same(S.spudStates(ids), ['NM', 'FO']), 'spudsNote says once which states count wells spudded, and in the singular or plural');
check(same(S.dailyStates.map((q) => q.id), ['TX', 'OK', 'NM']) && !S.stateOf('FO').dir && typeof S.stateOf('FO').noDaily === 'string' && S.STATES.every((q) => q.dir || q.noDaily), 'the federal offshore has no Daily report (its file is weekly) and says why: every state has a Daily folder or a reason');
// "the last 12 months" starts where the state's own count starts: the first day of the month 11 back for a spud state's month-end file, 365 days back for the others
check(S.yearStart('FO', '2026-08-31') === Date.UTC(2025, 8, 1) && S.yearStart('NM', '2026-08-31') === Date.UTC(2025, 8, 1) && S.yearStart('FO', '2026-12-31') === Date.UTC(2026, 0, 1)
  && S.yearStart('FO', '2026-08-15') === Date.parse('2026-08-15T00:00:00Z') - 365 * 864e5 && S.yearStart('TX', '2026-10-07') === Date.parse('2025-10-07T00:00:00Z')
  && S.yearStart('OK', '2026-08-31') === Date.parse('2025-08-31T00:00:00Z'), 'yearStart: 12 calendar months from the first day for the states that count spuds at a month end, the 365 days that end on the day for the others');
// the wording helpers the pages share: a sentence names "the federal offshore" (and capitalizes it at its start), a count of one is "1 spud", and the dots, the counts
// and the ranking minimum are named for what the states shown count
check(S.ucFirst(S.inName('FO')) === 'The federal offshore' && S.ucFirst(S.statesIn(['FO'])) === 'The federal offshore' && S.statesIn(['TX', 'FO']) === 'Texas and the federal offshore'
  && S.statesIn(ids) === 'Texas, Oklahoma, New Mexico and the federal offshore' && S.ucFirst('') === '', 'a state named inside a sentence says "the federal offshore", and a sentence that starts with it capitalizes it');
check(S.countWord('FO', 1) === 'spud' && S.countWord('FO', 2) === 'spuds' && S.countWord('FO', 0) === 'spuds' && S.countWord('TX', 1) === 'permit' && S.countWord('OK', 12) === 'permits' && S.countWord('NM', 1) === 'spud',
  'a count of one is "1 spud" or "1 permit", never "1 spuds"');
check(S.measureAnd(['TX']) === 'permit' && S.measureAnd(['NM', 'FO']) === 'spud' && S.measureAnd(ids) === 'permit and spud' && S.everyOf(['FO']) === 'every spud' && S.everyOf(['TX', 'OK']) === 'every permit' && S.everyOf(ids) === 'every permit and every spud'
  && S.dotName(['TX']) === 'permit dot' && S.dotName(['FO']) === 'well dot' && S.dotName(['NM', 'FO']) === 'well dot' && S.dotName(['TX', 'FO']) === 'permit or well dot',
  'the dots and counts are named for what the states shown count: a permit dot, a well dot, or both');
const FO_CAVEAT = 'a well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted.';
check(S.spudCaveat(['TX', 'OK', 'NM']) === '' && S.spudCaveat(['NM']) === '' && S.spudCaveat(['FO']) === FO_CAVEAT.replace(/^a/, 'A') && S.spudCaveat(ids) === 'In the federal offshore ' + FO_CAVEAT
  && S.spudCaveat(['NM', 'FO']) === S.spudCaveat(ids) && S.spudCaveat(['TX', 'FO']) === S.spudCaveat(ids), 'what the offshore\'s count leaves out (a sidetrack is not a new well) is said wherever the offshore is shown, naming it unless it is the only state, and nowhere else');
// a place is ranked on its change from the 12 before only with enough in the last 12 months: 20 permits or spuds, 5 offshore (its busiest area has 14, so 20 would rank none)
check(S.chgMinOf('TX') === 20 && S.chgMinOf('OK') === 20 && S.chgMinOf('NM') === 20 && S.chgMinOf('FO') === 5 && S.chgMinPhrase(['TX']) === '20+ permits' && S.chgMinPhrase(['NM']) === '20+ spuds' && S.chgMinPhrase(['FO']) === '5+ spuds'
  && S.chgMinPhrase(['TX', 'OK']) === '20+ permits' && S.chgMinPhrase(['TX', 'FO']) === '20+ permits or spuds (5+ in the federal offshore)' && S.chgMinPhrase(ids) === '20+ permits or spuds (5+ in the federal offshore)',
  'the least an area needs to be ranked on its change is named for the states shown (20+ permits, 5+ spuds)');
{
  const cp = read('county-permits-fo'); const busiest = Math.max(...Object.values(cp.counties).map((c) => c.p12));
  const ranked = Object.values(cp.counties).filter((c) => c.p12 >= S.chgMinOf('FO') && c.p12 + c.p12prev >= 10).length;
  check(busiest < S.CHG_MIN && ranked >= 3, 'on the committed files: the offshore\'s busiest area (' + busiest + ' spuds) is under the 20 that ranks a land county, and ' + ranked + ' areas pass its own minimum, so the map\'s list is not empty');
}
check(S.stateOf('TX').fips === '48' && S.stateOf('OK').fips === '40' && S.stateOf('NM').fips === '35', 'each state knows its FIPS code (a county\'s FIPS is the state\'s and its three digits)');
check(S.dailyStates.map((q) => q.id).join() === 'TX,OK,NM' && S.STATES.find((q) => q.id === 'NM').dir === 'daily-nm' && S.STATES.every((q) => !q.dir || /^daily/.test(q.dir)), 'a state with a Daily report has a folder for it, and only those are asked for one');
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
  const fo = { months: ['2025-01', '2025-02', '2025-03'], permits: [4, 5, 6], asOf: '2026-08-31', through: '2026-08-31', counties: { '024': { p12: 14, p12prev: 12, m: [], depth: null, ops: [['SHELL OFFSHORE INC.', '3', 14]] } } };
  const spf = O.permitSeries(['TX', 'OK', 'NM', 'FO'], { TX: tx, OK: ok, NM: nm, FO: fo });
  check(same(spf.summed, ['TX', 'OK']) && same(spf.permits, [110, 121]) && same(spf.ids, ['TX', 'OK', 'NM', 'FO']) && same(spf.own.FO.permits, [4, 5, 6]) && O.ownTotals(spf, 'FO').last === 15 && same(O.permitSeries(['NM', 'FO'], { NM: nm, FO: fo }).summed, ['NM', 'FO']),
    'permitSeries: the federal offshore counts spuds too, so it is not added to the permits either, and with New Mexico alone it is the sum of the spud states');
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
  // a state with a crude file has it committed, under the key the page reads (okCrude, nmCrude, foCrude), one value a month
  for (const q of S.otherStates.filter((x) => x.files.crude)) {
    const f = read(q.files.crude); const v = f[q.id.toLowerCase() + 'Crude'];
    check(Array.isArray(v) && v.length === f.months.length && v.every((x) => x === null || (typeof x === 'number' && x > 0)) && f.latest === f.months[f.months.length - 1], q.name + ': ' + q.files.crude + ' has ' + q.id.toLowerCase() + 'Crude, a positive number for each of its ' + f.months.length + ' months (to ' + f.latest + ')');
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

/* ---------- national-data.js ---------- */
{
  const Nt = await imp('national-data.js');
  const mk = (id, measure, vals, extra = {}) => ({ id, name: id, measure, bands: { new: vals, inj: null, redrill: null, rework: null, amend: null, other: null }, p12: vals.filter((v) => v != null).slice(-12).reduce((a, b) => a + b, 0),
    prev12: vals.filter((v) => v != null).slice(-24, -12).reduce((a, b) => a + b, 0), mix12: { new: 1 }, through: '2026-09-30', asOf: '2026-10-01', ...extra });
  const months = Array.from({ length: 30 }, (_, i) => '2024-' + String(i % 12 + 1).padStart(2, '0'));
  const flat = (n, v) => Array.from({ length: n }, () => v);
  const doc = { months, states: [mk('TX', 'permits', flat(30, 10)), mk('ND', 'permits', flat(30, 4)), mk('BL', 'permits', flat(30, 3)), mk('NM', 'spuds', [...flat(28, 5), null, null]), mk('KS', 'permits', flat(30, 1))], gaps: [{ id: 'CO', name: 'Colorado' }] };
  check(Nt.total(doc, 'permits') === 12 * (10 + 4 + 1) && Nt.total(doc, 'spuds') === 60, 'national: totals add within a measure, and the BLM (an overlapping line) is never in them');
  check(Nt.rankBy(doc, 'permits').map((s) => s.id).join() === 'TX,ND,BL,KS' && Nt.rankBy(doc, 'spuds').map((s) => s.id).join() === 'NM', 'national: the ranking keeps measures apart and lists the BLM line');
  check(Nt.sizeClass(0, 10) === 0 && Nt.sizeClass(1, 0) === 0 && Nt.sizeClass(10, 10) === 5 && Nt.sizeClass(5, 10) === 5 && Nt.sizeClass(2, 10) === 4 && Nt.sizeClass(1, 10) === 3 && Nt.sizeClass(0.3, 10) === 2 && Nt.sizeClass(0.01, 10) === 1, 'national: five size classes against the biggest, nothing for zero');
  check(Nt.maxOf(doc, 'permits') === 120 && Nt.tileKind(doc, 'TX').kind === 'data' && Nt.tileKind(doc, 'CO').kind === 'gap' && Nt.tileKind(doc, 'GA').kind === 'quiet' && Nt.tileKind(doc, 'TX').size === 5, 'national: a tile is data, a gap or quiet');
  check(Nt.change({ p12: 12, prev12: 10 }) === 0.2 && Nt.change({ p12: 5, prev12: 0 }) === null, 'national: the change is null, never infinity, when the 12 before are zero');
  const st = Nt.stack(doc, 'permits');
  check(st.series.map((s) => s.id).join() === 'TX,ND,other' && st.series.at(-1).count === 1 && st.totals.every((t) => t === 15) && st.months.length === 30, 'national: plotted states keep their color, the rest fold into Other states; the BLM is not stacked');
  const sp = Nt.stack(doc, 'spuds');
  check(sp.series.length === 1 && sp.series[0].id === 'NM' && sp.months.length === 28 && sp.end === months[27], 'national: the spuds chart ends at the newest month its plotted state has (nulls are not zeros)');
  check(Nt.mix(doc.states[0]) === null && Nt.mix({ mix12: { new: 6, amend: 2, inj: 2 } }).length === 3 && Math.abs(Nt.mix({ mix12: { new: 6, amend: 2, inj: 2 } })[0].share - 0.6) < 1e-9, 'national: the mix needs two known bands, and shares add to one');
  check(Nt.fluidMix({ fluid: null }) === null && Nt.fluidMix({ fluid: { oil: 3, gas: 1, both: 0, other: 0, unknown: 1 } }).sum === 5, 'national: fluid mix is null where the state records none');
  check(Nt.listAnd(['a', 'b', 'c']) === 'a, b and c' && Nt.niceMax(0).top === 1 && Nt.niceMax(730).top >= 730 && Nt.niceMax(730).ticks[0] === 0, 'national: lists and axis scales');
  const cov = Nt.coverage(doc, ['TX', 'CO']);
  check(cov[0].status === 'permits' && cov[1].status === 'gap' && Nt.coverage(doc, ['NM'])[0].status === 'spuds', 'national: coverage rows say permits, spuds or not read yet');
  // the committed file
  const nat = read('national');
  const tileIds = Object.keys(Nt.TILES);
  const all = [...nat.states.map((s) => s.id), ...nat.gaps.map((g) => g.id)];
  check(all.every((id) => tileIds.includes(id)) && new Set(Object.values(Nt.TILES).map((t) => t.join())).size === tileIds.length, 'national: every jurisdiction in national.json has a tile, and no two tiles share a square');
  check(Object.values(Nt.TILES).every(([x, y]) => x >= 0 && x < Nt.COLS && y >= 0 && y < Nt.ROWS), 'national: every tile is inside the grid');
  check(nat.states.every((s) => s.bands.new.length === nat.months.length) && Nt.total(nat, 'permits') === nat.totals.permits12 && Nt.total(nat, 'spuds') === nat.totals.spuds12, 'national: the committed bands span the axis and the totals agree with the Python builder');
  check(nat.states.every((s) => Nt.change(s) === null || isFinite(Nt.change(s))) && Nt.stack(nat, 'permits').series.length >= 1, 'national: the committed file draws a stack with finite changes');
}

console.log('\n' + (fails ? 'FAILED ' + fails : 'all passed'));
process.exit(fails ? 1 : 0);
