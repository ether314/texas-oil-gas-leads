// Tests for the pure JavaScript data code: which states are shown (states.js), what the Overview merges from them (overview-data.js, the
// permit points merge), the national wells map's geography and data code (usgeo.js, newwells-data.js). No browser, no network: synthetic files, plus the committed ones
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
const GEO = await imp('usgeo.js');
const NW = await imp('newwells-data.js');
const OD = await imp('oil-day-data.js');
const CB = await imp('combined-data.js');
const CD = await imp('companies-data.js');
const read = (n) => JSON.parse(fs.readFileSync(path.join(DATA, n + '.json'), 'utf8'));

let fails = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) fails++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---------- states.js: the four states that have files of their own ---------- */
const ids = S.STATES.map((s) => s.id);
const others = S.STATES.filter((s) => s.files);
check(ids.join() === 'TX,OK,NM,FO' && S.STATES[0].files === null && others.length === 3 && others.every((s) => s.files.series && s.files.county && s.files.operators && s.files.points && s.files.geo), 'Texas is first and has no files entry; every other state lists its geo, series, county, operators and points files');
check(S.countyKey('TX', '001') === '001' && S.countyKey('OK', '001') === 'OK:001' && S.countyKey('FO', '024') === 'FO:024' && S.statesKey(['TX', 'OK']) === 'TX+OK', 'county keys: Texas plain, every other state prefixed (the federal offshore\'s areas FO:024), and a set of states has one key');
// Texas and Oklahoma publish permits by approval date; New Mexico and the federal offshore publish none by well, so their files count wells spudded
check(S.measureOf('TX').id === 'permits' && S.measureOf('OK').id === 'permits' && S.measureOf('NM').id === 'spuds' && S.measureOf('FO').id === 'spuds' && S.stateOf('FO').name === 'Federal offshore' && S.stateOf('ZZ') === undefined, 'measures: Texas and Oklahoma count permits, New Mexico and the federal offshore wells spudded');
check(S.listAnd(['Texas']) === 'Texas' && S.listAnd(['Texas', 'Oklahoma']) === 'Texas and Oklahoma' && S.listAnd(['Texas', 'Oklahoma', 'New Mexico']) === 'Texas, Oklahoma and New Mexico' && S.listAnd([]) === '', 'listAnd: a list reads like English');
// a state named inside a sentence says "the federal offshore" (and capitalizes it at its start)
check(S.inName('FO') === 'the federal offshore' && S.inName('NM') === 'New Mexico' && S.ucFirst(S.inName('FO')) === 'The federal offshore' && S.ucFirst('') === '', 'a state named inside a sentence says "the federal offshore", and a sentence that starts with it capitalizes it');
const FO_CAVEAT = 'a well counts once, on its first borehole; sidetracks and bypasses of existing wells are drilling too, but are not counted.';
check(S.spudCaveat(['TX', 'OK', 'NM']) === '' && S.spudCaveat(['NM']) === '' && S.spudCaveat(['FO']) === FO_CAVEAT.replace(/^a/, 'A') && S.spudCaveat(ids) === 'In the federal offshore ' + FO_CAVEAT
  && S.spudCaveat(['NM', 'FO']) === S.spudCaveat(ids) && S.spudCaveat(['TX', 'FO']) === S.spudCaveat(ids), 'what the offshore\'s count leaves out (a sidetrack is not a new well) is said wherever the offshore is shown, naming it unless it is the only state, and nowhere else');

/* ---------- overview-data.js: the other states' operators, as the Companies page's tables read them ---------- */
{
  check(same(O.operatorExtras({ prev12: 3, depth: 9000, county: 'OK:003', counties: 4, m24: [1, 2], new12: 5, spud12: 7 }), { prev12: 3, spud12: null, depth: 9000, fips: 'OK:003', counties: 4, m24: [1, 2] }), 'operatorExtras: what only Texas has (a reported spud count, the new-well count) stays out, the rest keeps its names');
  const doc = { cols: ['band', 'num', 'name', 'new12', 'county', 'newDrill'], rows: [['A', '77', 'OKIE INC', 12, '003', 1], ['C', '78', 'OTHER LLC', 0, '', 0]] };
  const rows = O.stateOperatorRows('OK', doc);
  check(rows[0].num === 'OK:77' && rows[0].rawNum === '77' && rows[0].county === 'OK:003' && rows[1].county === '' && rows[0].st === 'OK' && rows[0]._i === 0, 'stateOperatorRows: objects like the Texas table\'s, number and county keyed by state');
  check(O.stateOperatorRows('OK', null).length === 0, 'stateOperatorRows: a state with no file gives no rows');
}

/* ---------- the committed files, together ---------- */
{
  for (const q of others) {
    const operators = read(q.files.operators); const geo = read(q.files.geo);
    const rows = O.stateOperatorRows(q.id, operators);
    const gk = new Set(geo.features.map((f) => S.countyKey(q.id, f.properties.f)));
    check(rows.length > 0 && rows.every((r) => r.county === '' || gk.has(r.county)) && new Set(rows.map((r) => r.num)).size === rows.length, q.name + ': ' + rows.length + ' operators, each top county on the map, numbers unique');
  }
  // a state with a crude file has it committed, under the key the page reads (okCrude, nmCrude, foCrude), one value a month
  for (const q of others.filter((x) => x.files.crude)) {
    const f = read(q.files.crude); const v = f[q.id.toLowerCase() + 'Crude'];
    check(Array.isArray(v) && v.length === f.months.length && v.every((x) => x === null || (typeof x === 'number' && x > 0)) && f.latest === f.months[f.months.length - 1], q.name + ': ' + q.files.crude + ' has ' + q.id.toLowerCase() + 'Crude, a positive number for each of its ' + f.months.length + ' months (to ' + f.latest + ')');
  }
}

/* ---------- national-data.js ---------- */
{
  const Nt = await imp('national-data.js');
  const mk = (id, measure, vals, extra = {}) => ({ id, name: id, measure, bands: { new: vals, inj: null, redrill: null, rework: null, amend: null, other: null }, p12: vals.filter((v) => v != null).slice(-12).reduce((a, b) => a + b, 0),
    prev12: vals.filter((v) => v != null).slice(-24, -12).reduce((a, b) => a + b, 0), mix12: { new: 1 }, through: '2026-09-30', asOf: '2026-10-01', ...extra });
  const months = Array.from({ length: 30 }, (_, i) => '2024-' + String(i % 12 + 1).padStart(2, '0'));
  const flat = (n, v) => Array.from({ length: n }, () => v);
  const doc = { months, states: [mk('TX', 'permits', flat(30, 10)), mk('ND', 'permits', flat(30, 4)), mk('BL', 'permits', flat(30, 3)), mk('NM', 'spuds', [...flat(28, 5), null, null]), mk('KS', 'permits', flat(30, 1))], gaps: [{ id: 'CO', name: 'Colorado' }] };
  check(Nt.total(doc, 'permits') === 12 * (10 + 4 + 1) && Nt.total(doc, 'spuds') === 60, 'national: totals add within a measure, and the BLM (an overlapping line) is never in them');
  // counts of another kind (Oregon's applications filed, Virginia's wells drilled by completion date): shown on their own lines, in no total, no chart and no shade
  const doc2 = { ...doc, states: [...doc.states, mk('OR', 'applications', flat(30, 0)), mk('VA', 'drilled', flat(30, 2))] };
  check(Nt.total(doc2, 'permits') === Nt.total(doc, 'permits') && Nt.total(doc2, 'spuds') === Nt.total(doc, 'spuds') && Nt.total(doc2, 'applications') === 0 && Nt.total(doc2, 'drilled') === 0 && Nt.summable(doc2, 'drilled').length === 0,
    'national: applications filed and wells drilled are in no total (a count of another kind is never added to permits or spuds)');
  check(Nt.stack(doc2, 'permits').series.every((s) => s.id !== 'OR') && Nt.stack(doc2, 'spuds').series.every((s) => s.id !== 'VA') && Nt.stack(doc2, 'spuds').totals.every((t) => t === 5 || t === 0), 'national: neither is in a chart');
  check(Nt.measureOf('drilled').sum === false && Nt.measureOf('spuds').sum === true && Nt.measureOf('nonsense').id === 'permits' && Nt.MEASURES.map((m) => m.id).join() === 'permits,spuds,applications,drilled', 'national: four measures, two that add');
  check(Nt.coverage(doc2, ['OR', 'VA', 'TX', 'NM']).map((r) => r.status).join() === 'applications,drilled,permits,spuds', 'national: the coverage table names each state\'s own count');
  check(Nt.inName('FO', 'Federal offshore') === 'the federal offshore' && Nt.inName('BL', 'Federal onshore (BLM)') === 'federal onshore (BLM)' && Nt.inName('TX', 'Texas') === 'Texas' && Nt.upFirst('the federal offshore') === 'The federal offshore' && Nt.upFirst('') === '', 'national: the offshore and the BLM are common nouns inside a sentence, and a list that starts with one is capitalized');
  check(Nt.unitFor(1, 'new-drill permits') === 'new-drill permit' && Nt.unitFor(1, 'wells spudded') === 'well spudded' && Nt.unitFor(1, 'APDs approved') === 'APD approved' && Nt.unitFor(1, 'applications filed') === 'application filed' && Nt.unitFor(2, 'new-drill permits') === 'new-drill permits' && Nt.unitFor(0, 'wells drilled') === 'wells drilled', 'national: one is "1 new-drill permit", never "1 permits"');
  const fl = { states: { OR: { agency: { url: 'https://agency.example/or' } }, KS: { agency: { url: 'https://agency.example/ks' } } } };
  check(Nt.sourceHref({ id: 'OR', source: { url: 'https://x.gov/files/permits.zip' } }, fl).href === 'https://agency.example/or' && Nt.sourceHref({ id: 'OR', source: { url: 'https://x.gov/files/permits.zip' } }, fl).viaAgency
    && Nt.sourceHref({ id: 'KS', source: { url: 'https://x.gov/arcgis/rest/services/Wells/MapServer/0' } }, fl).href === 'https://agency.example/ks' && Nt.sourceHref({ id: 'KS', source: { url: 'https://x.gov/permits' } }, fl).href === 'https://x.gov/permits'
    && Nt.sourceHref({ id: 'KS', source: { url: 'https://x.gov/a.zip' } }, null).href === 'https://x.gov/a.zip' && Nt.sourceHref({ id: 'KS' }, fl) === null, 'national: a source that is a raw download or a map-service root sends a visitor to the agency\'s own page; a page is linked as it is; nothing to link is null');
  check(Nt.noneRecorded({ p12: 0, prev12: 0 }) && !Nt.noneRecorded({ p12: 0, prev12: 3 }) && !Nt.noneRecorded({ p12: 2, prev12: 0 }), 'national: nothing in 24 months reads "none recorded"; a year with none after a year with some is a real zero');
  check(Nt.change({ p12: 12, prev12: 10 }) === 0.2 && Nt.change({ p12: 5, prev12: 0 }) === null, 'national: the change is null, never infinity, when the 12 before are zero');
  check(Nt.shownChange({ p12: 372, prev12: 2 }) === null && Nt.shownChange({ p12: 30, prev12: 20 }) === 0.5 && Nt.shownChange({ p12: 5, prev12: 0 }) === null, 'national: a change is shown only from a base of 20 (2 permits to 372 is not +18,500%)');
  const st = Nt.stack(doc, 'permits');
  check(st.series.map((s) => s.id).join() === 'TX,ND,other' && st.series.at(-1).count === 1 && st.totals.every((t) => t === 15) && st.months.length === 30, 'national: plotted states keep their color, the rest fold into Other states; the BLM is not stacked');
  const lag = Nt.stack({ ...doc, states: [...doc.states, mk('IL', 'permits', [...flat(26, 2), null, null, null, null])] }, 'permits');
  check(same(lag.lagging, ['IL']) && lag.series.at(-1).id === 'other' && lag.series.at(-1).values.at(-1) === 1 && same(st.lagging, []), 'national: a state that ends before the axis is named, and its missing months are left out of the Other bar, not drawn as zero');
  const sp = Nt.stack(doc, 'spuds');
  check(sp.series.length === 1 && sp.series[0].id === 'NM' && sp.months.length === 28 && sp.end === months[27], 'national: the spuds chart ends at the newest month its plotted state has (nulls are not zeros)');
  check(Nt.mix(doc.states[0]) === null && Nt.mix({ mix12: { new: 6, amend: 2, inj: 2 } }).length === 3 && Math.abs(Nt.mix({ mix12: { new: 6, amend: 2, inj: 2 } })[0].share - 0.6) < 1e-9, 'national: the mix needs two known bands, and shares add to one');
  check(Nt.fluidMix({ fluid: null }) === null && Nt.fluidMix({ fluid: { oil: 3, gas: 1, both: 0, other: 0, unknown: 1 } }).sum === 5, 'national: fluid mix is null where the state records none');
  check(Nt.listAnd(['a', 'b', 'c']) === 'a, b and c' && Nt.niceMax(0).top === 1 && Nt.niceMax(730).top >= 730 && Nt.niceMax(730).ticks[0] === 0, 'national: lists and axis scales');
  check(Nt.niceMax(1150).top === 1250 && Nt.niceMax(1150).ticks.join() === '0,250,500,750,1000,1250' && Nt.niceMax(120).top === 125 && Nt.niceMax(7).top === 8 && Nt.niceMax(1).ticks.join() === '0,1' && Nt.niceMax(11).ticks.join() === '0,5,10,15', 'national: an axis tops close to the data (1,150 tops at 1,250; it topped at 2,000)');
  let axisOk = true; let axisWhy = '';
  for (let v = 1; v <= 6000; v += 1) {
    const a = Nt.niceMax(v);
    const whole = a.ticks.every((t) => Number.isInteger(t));
    const tight = a.top >= v && (v < 6 || a.top <= v * 1.5);
    if (!(whole && tight && a.ticks.length >= 2 && a.ticks.length <= 7 && a.ticks[0] === 0 && a.ticks.at(-1) === a.top)) { axisOk = false; axisWhy = v + ' -> ' + JSON.stringify(a); break; }
  }
  check(axisOk, 'national: for every whole count from 1 to 6,000 the axis has whole ticks, at most 6 steps, and a top between the data and 1.5 times it ' + axisWhy);
  const cov = Nt.coverage(doc, ['TX', 'CO']);
  check(cov[0].status === 'permits' && cov[1].status === 'gap' && Nt.coverage(doc, ['NM'])[0].status === 'spuds', 'national: coverage rows say permits, spuds or not read yet');
  // the committed file
  const nat = read('national');
  const all = [...nat.states.map((s) => s.id), ...nat.gaps.map((g) => g.id)];
  check(nat.states.every((s) => s.bands.new.length === nat.months.length) && Nt.total(nat, 'permits') === nat.totals.permits12 && Nt.total(nat, 'spuds') === nat.totals.spuds12, 'national: the committed bands span the axis and the totals agree with the Python builder');
  check(nat.states.every((s) => Nt.change(s) === null || isFinite(Nt.change(s))) && Nt.stack(nat, 'permits').series.length >= 1, 'national: the committed file draws a stack with finite changes');
}

/* ---------- images-data.js ---------- */
{
  const Im = await imp('images-data.js');
  const rows = Im.daySeries({ days: [{ d: '2026-10-29', k: 'reconstructed', w1: 54.1, ds: 41.6, cm: 361.8 }, { d: '2026-10-30', k: 'live', w1: 31.2, ds: 27.0, cm: 306.0 }, { d: '2026-10-31', k: 'live', w1: null, ds: 39.3, cm: 446.8 }, { d: '2026-11-01', k: 'live', w1: null, ds: null, cm: null }] });
  check(rows[2].w1images === null && rows[1].live === true && rows[0].live === false, 'images: a pack not listed for a day is null, never zero');
  check(Math.abs(Im.dayTotal(rows[1]) - 364.2) < 1e-9 && Im.dayTotal(rows[2]) === 39.3 + 446.8 && Im.havePacks(rows[2]) && !Im.havePacks(rows[3]), 'images: a day\'s total adds the packs it has; a day with none has no packs');
  const sm = Im.summary(rows);
  check(sm.withPacks === 3 && sm.peak.d === '2026-10-31' && Math.abs(sm.avgMB - (457.5 + 364.2 + 486.1) / 3) < 1e-9, 'images: the summary averages only the days that had a pack and names the busiest');
  check(Im.summary([]).avgMB === null && Im.summary([]).peak === null, 'images: an empty archive has no average and no busiest day');
  check(Im.sizeText(null) === '—' && Im.sizeText(5.25) === '5.3 MB' && Im.sizeText(54.1) === '54 MB' && Im.sizeText(1536) === '1.50 GB' && Im.sizeText(1000) === '1000 MB' && Im.bytesText(32673628) === '31 MB' && Im.bytesText(41240494) === '39 MB' && Im.bytesText(468514243) === '447 MB', 'images: sizes read as MB (2^20 bytes, as the Commission lists them and the Daily archive stores them) or GB, and a missing size as a dash; 41,240,494 bytes are the same 39 MB the chart shows');
  const day = { images: { w1images: { day: '2026-10-29', bytes: 100, districts: [['08', 60], ['03', 40]], docs: { n: 168, types: [['Permit plat', 94], ['Approved W-1', 74]], packets: null }, sheet: { file: 'a.jpg' } }, dirsurveys: null, complimages: { bytes: 5, empty: true, docs: null } },
    permits: { rows: [['0919696', '301', '08', '1', 'X LLC', 100, 'H', null, null, null, ['W1.pdf', 'Plat_1.pdf']], ['0919697', '301', '08', '1', null, 100, 'H']] } };
  const pk = Im.packsOf(day);
  check(pk[0].present && pk[0].n === 168 && pk[0].kinds[0].k === 'Permit plat' && pk[0].districts[0].d === '08' && pk[0].sheet === 'a.jpg' && !pk[1].present && pk[2].present && pk[2].kinds === null && pk[2].empty === true, 'images: a day file\'s packs: documents by kind, districts, sheet; a missing pack and a pack with no counts are told apart');
  check(Im.packsOf(null).every((p) => !p.present) && Im.packsOf({}).length === 3, 'images: no day file means no packs, not an error');
  const f = Im.filedPermits(day);
  check(f.length === 1 && f[0].permit === '0919696' && Im.fileKind('W1.pdf') === 'W-1 letter' && Im.fileKind('Plat_1.pdf') === 'plat' && Im.fileKind('survey_5.pdf') === 'survey', 'images: only permits whose files are published are listed, and files are named by kind');
  // the release a day file names, the files it holds and the readable previews of them (2026-11-01)
  const rel = { repo: 'o/r', tag: 'daily-2026-10-30', files: 3, bytes: 9, permits: 1, surveys: 1 };
  check(Im.releaseOk(rel) && !Im.releaseOk(null) && !Im.releaseOk({ repo: 'o/r', tag: 'v1' }) && !Im.releaseOk({ repo: 'o r', tag: 'daily-2026-10-30' }) && !Im.releaseOk({ repo: 'o/r/x', tag: 'daily-2026-10-30' }), 'images: only a release named as a repository and a daily tag is trusted');
  check(Im.fileUrl(rel, '0919696_W1.pdf') === 'https://github.com/o/r/releases/download/daily-2026-10-30/0919696_W1.pdf' && Im.fileUrl(rel, '../x') === null && Im.fileUrl(rel, 'a b.pdf') === null && Im.fileUrl(rel, 'a/b') === null && Im.fileUrl(null, 'a.pdf') === null && Im.fileUrl(rel, 5) === null,
    'images: a file address is made only from a plain file name on a trusted release');
  check(Im.previewUrl(rel, '0919696_W1.pdf') === null && Im.previewUrl({ ...rel, previews: 0 }, '0919696_W1.pdf') === null && Im.previewUrl({ ...rel, previews: true }, '0919696_W1.pdf') === null,
    'images: a release that does not say it holds previews (an older day, a night without the tools) has none to link');
  const relP = { ...rel, previews: 2, noPreview: ['0919696_Plat_1.pdf'] };
  check(Im.previewUrl(relP, '0919696_W1.pdf') === 'https://github.com/o/r/releases/download/daily-2026-10-30/0919696_W1.pdf.jpg' && Im.previewUrl(relP, '0919696_Plat_1.pdf') === null && Im.previewUrl(relP, '../x') === null && Im.previewUrl({ ...relP, tag: 'x' }, '0919696_W1.pdf') === null,
    'images: a preview is linked only for a document the release holds one of, never from an odd name or an untrusted release');
  check(JSON.stringify(Im.docLabel('W1.pdf')) === '{"label":"Approved W-1 permit","type":"PDF"}' && Im.docLabel('Plat_2.tif').label === 'Permit plat 2' && Im.docLabel('Plat_2.tif').type === 'TIF' && Im.docLabel('x.pdf').label === 'Document', 'images: a file suffix is named as a letter or a plat, numbered when there are several');
  const dayP = { ...day, release: relP, permits: { rows: [['0919696', '301', '08', '1', 'X LLC', 100, 'H', null, null, null, ['W1.pdf', 'Plat_1.pdf']]] }, surveys: { day: '2026-10-29', n: 2, rows: [['42301', '301', 'M', null, null, null, null, null, '9936440', null, null], ['42302', '301', 'O', null, null, null, null, null, 'x/../9', null, null]] } };
  const fp = Im.filedPermits(dayP)[0];
  check(fp.docs.length === 2 && fp.docs[0].original.endsWith('/0919696_W1.pdf') && fp.docs[0].preview.endsWith('/0919696_W1.pdf.jpg') && fp.docs[1].original.endsWith('/0919696_Plat_1.pdf') && fp.docs[1].preview === null && fp.docs[1].label === 'Permit plat 1' && fp.files.length === 2,
    'images: each published file has its label, its address and its preview, or null where it has none');
  check(Im.filedPermits(day)[0].docs.every((x) => x.original === null && x.preview === null), 'images: a day file that names no release has no addresses, so the page links nothing');
  const sv = Im.filedSurveys({ ...dayP, release: { ...relP, noPreview: [] } });
  check(sv.length === 1 && sv[0].id === '9936440' && sv[0].doc.preview.endsWith('/dir_survey_9936440.pdf.jpg') && sv[0].doc.original.endsWith('/dir_survey_9936440.pdf') && sv[0].doc.label === 'Directional survey 9936440', 'images: a survey with an odd id is left out, the others get an address and a preview');
  check(Im.filedSurveys(day).length === 0 && Im.filedSurveys(null).length === 0 && Im.filedSurveys({ surveys: dayP.surveys }).length === 0, 'images: surveys are listed only for a day whose release is named');
  const lc = Im.lifecycle(pk);
  check(lc.map((s) => s.id).join() === 'permit,drilling,completion' && lc[0].n === 168 && lc[1].present === false && lc[1].kinds === null, 'images: the lifecycle has three stages, in order, and a stage with no pack has no kinds');
  check(Im.liveCandidates(rows).join() === '2026-11-01,2026-10-31,2026-10-30', 'images: live days are tried newest first');
  check(Im.PACKS.every((p) => Im.STAGES.some((s) => s.pack === p.id)) && Object.keys(Im.KIND_INFO).length >= 14 && Im.kindInfo('Well log').length > 10 && Im.kindInfo('nothing') === '', 'images: every pack has a stage, and the kinds are described');
  const idx = read('daily/index');
  const real = Im.daySeries(idx);
  const kinds = new Set();
  for (const d of idx.days.filter((x) => x.k === 'live')) for (const p of Im.packsOf(read('daily/' + d.d))) (p.kinds || []).forEach((k) => kinds.add(k.k));
  check(real.length === idx.days.length && [...kinds].every((k) => Im.KIND_INFO[k]), 'images: every kind in the committed live days has a description (' + [...kinds].filter((k) => !Im.KIND_INFO[k]).join(', ') + ')');
}

/* ---------- fields-data.js ---------- */
{
  const Fd = await imp('fields-data.js');
  const metrics = [{ key: 'a', label: 'A', group: 'g' }, { key: 'b', label: 'B', group: 'g' }, { key: 'c', label: 'C', group: 'h' }];
  const cells = (a, b, c) => ({ a: [a, 'file', ''], b: [b, 'form', ''], c: [c, 'none', ''] });
  const doc = { metrics, groups: [{ id: 'g', label: 'G' }, { id: 'h', label: 'H' }], order: ['ND', 'KS', 'CO'], states: {
    ND: { name: 'North Dakota', cells: cells('data', 'data', 'form') }, KS: { name: 'Kansas', cells: cells('data', 'query', 'unknown') }, CO: { name: 'Colorado', cells: cells('form', 'unknown', 'unknown') } } };
  check(same(Fd.stateScore(doc, 'ND'), { data: 2, query: 0, form: 1, none: 0, unknown: 0, asked: 3, total: 3 }) && Fd.stateScore(doc, 'CO').asked === 1, 'fields: a state\'s score counts each status and what it asks for at all');
  check(Fd.metricScore(doc, 'a').data === 2 && Fd.metricScore(doc, 'b').query === 1 && Fd.metricScore(doc, 'c').unknown === 2 && Fd.metricScore(doc, 'a').total === 3, 'fields: a metric\'s score counts the agencies');
  check(Fd.columns(doc).join() === 'ND,KS,CO' && Fd.columns(doc, 'name').join() === 'CO,KS,ND', 'fields: columns run most published first, or A to Z');
  check(Fd.metricsIn(doc, 'g').length === 2 && Fd.metricsIn(doc, 'all').length === 3 && Fd.metricsIn(doc, null).length === 3, 'fields: a group filters the rows');
  const h = Fd.headline(doc);
  check(h.best.id === 'ND' && h.best.n === 2 && h.topMetric.m.key === 'a' && Math.abs(h.unknownShare - 3 / 9) < 1e-9 && h.agencies === 3, 'fields: the headline names the best agency and metric and the share not verified');
  const tie = Fd.headline({ ...doc, states: { ND: { name: 'x', cells: cells('data', 'data', 'none') }, KS: { name: 'y', cells: cells('data', 'data', 'none') }, CO: doc.states.CO } });
  check(tie.topMetric.n === 2 && tie.topMetric.tied.map((m) => m.key).join() === 'a,b' && h.topMetric.tied.map((m) => m.key).join() === 'a', 'fields: metrics tied for most published are all named (a three-way tie is not one metric\'s win)');
  check(Fd.headline({ ...doc, states: { ND: { name: 'x', cells: cells('none', 'none', 'none') }, KS: doc.states.KS, CO: doc.states.CO } }).best.id === 'KS', 'fields: ties and zeros do not name an agency with nothing published');
  check(same(Fd.byStatus(doc, 'a'), { data: ['KS', 'ND'], query: [], form: ['CO'], none: [], unknown: [] }), 'fields: the agencies of each status for a metric, by name');
  check(Fd.cellOf(doc, 'ND', 'a').s === 'data' && Fd.cellOf(doc, 'ZZ', 'a') === null && Fd.shortCode('FO') === 'Gulf' && Fd.shortCode('BL') === 'BLM' && Fd.shortCode('ND') === 'ND', 'fields: a cell, no cell, and the short codes');
  check(Fd.CODES.map((c) => c.id).join() === 'data,query,form,none,unknown' && Object.keys(Fd.GRADES).join() === 'A,B,C,D', 'fields: five statuses and four grades');
  // a registry (FracFocus): the first column, never counted as an agency, with its list of fields tied to the permit metrics
  const reg = { ...doc, registries: ['FF'], states: { ...doc.states, FF: { name: 'FracFocus', kind: 'registry', cells: cells('data', 'none', 'data'), fields: [
    { column: 'Lat', label: 'Latitude', group: 'where', plain: 'p', metric: 'a' }, { column: 'Cas', label: 'CAS number', group: 'chem', plain: 'p', metric: '' },
    { column: 'Id', label: 'ID', group: 'well', plain: 'p', metric: '' }, { column: 'Gal', label: 'Water used', group: 'water', plain: 'p', metric: 'c' }] } } };
  check(Fd.registries(reg).join() === 'FF' && Fd.registries(doc).length === 0 && Fd.registries({ ...doc, registries: ['FF'] }).length === 0, 'fields: the registries are those the file names and really holds');
  check(Fd.columns(reg).join() === 'FF,ND,KS,CO' && Fd.columns(reg, 'name').join() === 'FF,CO,KS,ND' && Fd.columns(doc).join() === 'ND,KS,CO', 'fields: the registry is the first column however the agencies are ordered, and a file without one is unchanged');
  check(Fd.metricScore(reg, 'a').total === 3 && Fd.metricScore(reg, 'a').data === 2 && Fd.headline(reg).agencies === 3 && same(Fd.byStatus(reg, 'a'), Fd.byStatus(doc, 'a')) && Fd.headline(reg).unknownShare === h.unknownShare, 'fields: a registry is not counted as an agency (the counts, the headline and the lists are the agencies\')');
  check(Fd.stateScore(reg, 'FF').data === 2 && Fd.cellOf(reg, 'FF', 'a').s === 'data', 'fields: a registry has a score and cells like any column');
  const grp = Fd.registryGroups(reg, 'FF');
  check(grp.map((g) => g.id).join() === 'well,where,water,chem' && grp[1].fields[0].matches.key === 'a' && grp[1].fields[0].matches.data === 2 && grp[1].fields[0].matches.total === 3 && grp[3].fields[0].matches === null && Fd.registryGroups(doc, 'ND').length === 0,
    'fields: the registry\'s fields come in the page\'s order of groups, empty groups left out, each with how many agencies publish its metric as data (none when it matches no metric)');
  check(Fd.registryAdds(reg, 'FF').map((x) => x.m.key + x.n).join() === 'c0,a2' && Fd.registryAdds(reg, 'FF', 1).length === 1 && Fd.registryAdds(doc, 'ND').map((x) => x.m.key).join() === 'b,a' && Fd.registryAdds(reg, 'ZZ').length === 0, 'fields: what a registry adds are its data metrics that fewest agencies publish as data, fewest first');
  check(Object.keys(Fd.FIELD_GROUPS).join() === 'well,where,job,water,chem' && Fd.GRAIN.disclosure === 'one row a disclosure', 'fields: the groups of a registry\'s fields and a disclosure as a grain');
  const real = read('permit-fields');
  check(real.registries.join() === 'FF' && Fd.columns(real)[0] === 'FF' && Fd.columns(real).length === real.order.length + 1 && !real.order.includes('FF') && Fd.headline(real).agencies === 35, 'fields: in the real file FracFocus is the first column and not one of the 35 agencies');
  check(Fd.registryGroups(real, 'FF').reduce((n, g) => n + g.fields.length, 0) === real.states.FF.fields.length && Fd.registryAdds(real, 'FF')[0].m.key === 'fracture_plan' && Fd.registryAdds(real, 'FF').every((x) => x.n <= 4), 'fields: every field of the registry is in a group, and what it adds starts with the fracturing chemicals no agency publishes as data');
  check(real.order.every((id) => Fd.stateScore(real, id).total === real.metrics.length) && real.order.every((id) => Fd.stateScore(real, id).data + Fd.stateScore(real, id).query + Fd.stateScore(real, id).form + Fd.stateScore(real, id).none + Fd.stateScore(real, id).unknown === 48), 'fields: every committed state answers all 48 metrics');
}

/* ---------- wells-data.js ---------- */
{
  const Wd = await imp('wells-data.js');
  check(Wd.apiText('28337830') === '42-283-37830' && Wd.apiText('00335757') === '42-003-35757', 'wells: an API number is written the way the Commission writes it (42, county, well)');
  const ok = (t, api8, county) => { const r = Wd.parseApi(t); return r && r.api8 === api8 && r.county === county; };
  check(ok('42-283-37830', '28337830', '283') && ok('4228337830', '28337830', '283') && ok('28337830', '28337830', '283') && ok(' 283-37830 ', '28337830', '283') && ok('42-283-37830-00-00', '28337830', '283'), 'wells: an API number is read with or without the 42, the dashes and the sidetrack digits');
  check(ok('283', null, '283') && ok('42-283', null, '283') && ok('283-37', null, '283') && Wd.parseApi('28') === null && Wd.parseApi('abc') === null && Wd.parseApi('') === null && Wd.parseApi(null) === null, 'wells: the start of a number gives a county and no well; too little, or no digits, gives nothing');
  const U = (repo, tag, stem, ext) => Wd.assetUrl(repo, tag, stem, ext);
  check(U('o/r', 'wells-2026-10-29-ci-01', '28337830_c3', 'png') === 'https://github.com/o/r/releases/download/wells-2026-10-29-ci-01/28337830_c3.png', 'wells: a PNG document (a scan the Commission saved as .tif) is addressed as a .png');
  check(U('o/r', 'wells-2026-10-29-ci-01', '28337830_c1', 'pdf') === 'https://github.com/o/r/releases/download/wells-2026-10-29-ci-01/28337830_c1.pdf' && U('o/r', 'wells-2026-10-29-w1-02', '28337830_p12', 'jpg') !== null, 'wells: a document and its picture are addressed on the repository\'s releases');
  check([U('o/r/x', 'wells-2026-10-29-ci-01', '28337830_c1', 'pdf'), U('o/r', 'daily-2026-10-29', '28337830_c1', 'pdf'), U('o/r', 'wells-2026-10-29-ci-01', '../x', 'pdf'), U('o/r', 'wells-2026-10-29-ci-01', '28337830_c1', 'html'), U('o/r', 'wells-2026-10-29-ci-01', '28337830_c1', 'gif'), U('o r', 'wells-2026-10-29-ci-01', '28337830_c1', 'pdf'), U('', 'wells-2026-10-29-ci-01', '28337830_c1', 'pdf'), U('o/r', 'wells-2026-10-29-ci-01/../../x', '28337830_c1', 'pdf'), U('javascript:alert(1)//a/b', 'wells-2026-10-29-ci-01', '28337830_c1', 'pdf')].every((x) => x === null), 'wells: anything in the data that is not what the producer writes builds no address');
  const shard = { county: '283', name: 'La Salle', tags: ['wells-2026-10-28-ci-01', 'wells-2026-10-29-ci-01'], wells: [
    { a: '28337830', fl: 'EAGLEVILLE (EAGLE FORD-1)', di: '01', o: '102886', on: 'VERDUN OIL EF II LLC', docs: [
      { d: '2026-10-29', s: 'c', k: 'W-2 form', pg: 3, b: 24000, x: 'pdf', f: '28337830_c2', t: 1, v: 1 },
      { d: '2026-10-29', s: 'c', k: 'Plat', pg: null, b: 4200000, x: 'tif', f: '28337830_c1', t: 1, v: 0 },
      { d: '2026-10-28', s: 'p', k: 'Approved W-1', pg: 1, b: 9000, x: 'pdf', f: '28337830_p1', t: 0, v: 1 }] },
    { a: '28300001', fl: null, di: null, o: '999999', on: null, docs: [{ d: '2026-10-28', s: 'd', k: 'Directional survey', pg: 40, b: 800000, x: 'pdf', f: '28300001_d1', t: 0, v: 1 }] },
    { a: '28300002', fl: 'PHANTOM (WOLFCAMP)', di: '08', o: '102886', on: 'VERDUN OIL EF II LLC', docs: [{ d: '2026-10-28', s: 'c', k: 'P-4 form', pg: 1, b: 7000, x: 'pdf', f: '28300002_c1', t: 0, v: 1 }] }] };
  const well = shard.wells[0];
  const docs = Wd.docsOf('o/r', shard, well);
  check(docs[0].file === 'https://github.com/o/r/releases/download/wells-2026-10-29-ci-01/28337830_c2.pdf' && docs[0].preview.endsWith('/28337830_c2.jpg') && docs[1].preview === null && docs[1].file.endsWith('.tif') && docs[2].file.includes('wells-2026-10-28-ci-01'),
    'wells: each document has its address, and a picture only when one was drawn');
  const st = Wd.byStage(docs);
  check(st.map((x) => x.stage).join() === 'p,d,c' && st[0].docs.length === 1 && st[1].docs.length === 0 && st[2].docs.length === 2 && st[2].docs[0].f === '28337830_c1', 'wells: the stages run permit, drilling, completion; a stage with nothing is an empty list, not missing; a day\'s documents are in a fixed order');
  const sm = Wd.summary(well);
  check(sm.docs === 3 && sm.n.p === 1 && sm.n.d === 0 && sm.n.c === 2 && sm.bytes === 4233000 && sm.newest === '2026-10-29', 'wells: a well\'s summary counts its documents by stage, its bytes and its newest day');
  check(Wd.docMeta(docs[0]) === '3 pages · 23 KB' && Wd.docMeta({ pg: 2, b: 300 }) === '2 pages · 1 KB' && Wd.docMeta({ pg: 1, b: 4404019 }) === '1 page · 4.2 MB', 'wells: a document says its pages and size, in KB under a megabyte (never "0.0 MB")');
  check(Wd.docMeta(docs[1]) === Wd.sizeText(4200000 / 1048576) && !/page/.test(Wd.docMeta(docs[1])) && !/ 0 /.test(Wd.docMeta(docs[1])), 'wells: a file whose pages could not be counted says no page count, never 0 pages');
  check(Wd.docMeta({ pg: 1, b: 9000 }).startsWith('1 page · '), 'wells: one page is "1 page"');
  const names = (t) => Wd.matchWells(shard.wells, t).map((w) => w.a).join();
  check(names('') === '28337830,28300001,28300002' && names('283378') === '28337830' && names('37830') === '28337830' && names('283') === '28337830,28300001,28300002' && names('wolfcamp') === '28300002' && names('verdun') === '28337830,28300002' && names('999999') === '28300001' && names('district 08') === '28300002' && names('zzz') === '', 'wells: a search matches the start of an API number or of its own part, a field, an operator\'s name or number, or a district');
  check(Wd.rank(shard.wells).map((w) => w.a).join() === '28337830,28300001,28300002', 'wells: the wells with the most documents come first, then by API number');
  const idx = { repo: 'o/r', keepDays: 92, counties: [['283', 'La Salle', 3, 5], ['389', 'Reeves', 20, 100], ['003', 'Andrews', 20, 90]], totals: { wells: 43, docs: 195, bytes: 5000000000, stages: { p: 1, d: 1, c: 1 } },
    units: [{ d: '2026-10-29', p: 'ci', docs: 10, tied: 9, untied: 1, rejected: 0, wells: 4 }, { d: '2026-10-28', p: 'w1', docs: 5, tied: 5, untied: 0, rejected: 0, wells: 5 }] };
  check(Wd.countyChoices(idx).map((c) => c.fips).join() === '003,389,283', 'wells: the counties are listed most wells first, ties by name');
  check(same(Wd.tieLine(idx, '2026-10-29', 'ci'), { docs: 10, tied: 9, untied: 1, rejected: 0, wells: 4 }) && Wd.tieLine(idx, '2026-10-29', 'ds') === null && Wd.tieLine(idx, '2020-01-01', 'ci') === null, 'wells: what a pack held and tied is read from the index, and a pack not in the archive is null, not zero');
  const hl = Wd.headline(idx);
  check(hl.wells === 43 && hl.docs === 195 && hl.counties === 3 && hl.newest === '2026-10-29' && hl.oldest === '2026-10-28', 'wells: the headline is the totals and the days the archive covers');
  check(Wd.headline(null) === null && Wd.headline({ totals: { wells: 0, docs: 0 }, units: [] }) === null && Wd.headline({}) === null, 'wells: an empty or missing archive has no headline');
  check(Wd.RRC_LOOKUPS.length === 3 && Wd.RRC_LOOKUPS.every((l) => /^https:\/\/(webapps2?|rrcsearch3)\.(rrc\.texas\.gov|neubus\.com)\//.test(l.href) && !/\d{8}/.test(l.href)), 'wells: the Commission\'s look-up forms are linked without any API number in the address (it has none that opens one document)');
  check(Wd.STAGE_ORDER.every((k) => Wd.blurb(k).length > 20), 'wells: each stage has the same plain-words blurb as the images page');
  // the committed index and county files, whatever they hold, read cleanly
  const real = read('wells/index');
  check(real.repo === 'ether314/texas-oil-gas-leads' && Array.isArray(real.units) && real.counties.length === Wd.countyChoices(real).length, 'wells: the committed index names the repository and lists its counties');
  for (const [fips] of real.counties) {
    const sh = read('wells/county/' + fips);
    const bad = sh.wells.flatMap((w) => Wd.docsOf(real.repo, sh, w)).filter((x) => !x.file || (x.v && !x.preview));
    check(!bad.length, 'wells: every document in county ' + fips + ' has an address');
  }
}

/* ---------- usgeo.js and newwells-data.js: the national wells map ---------- */
{
  const doc = read('newwells/summary'); const pts = read('newwells/points'); const outlines = GEO.buildOutlines(read('us-states'));
  const P = NW.decode(pts);
  // the projection: Texas is south and east of Denver's side of the map, the lower 48 fill the frame, Alaska is an inset below the Southwest
  const at = (st, lon, lat) => GEO.project(lon, lat, st);
  const [midx, midy] = at('TX', -102, 31.9); const [dx, dy] = at('CO', -104.9, 39.7); const [ndx, ndy] = at('ND', -103.5, 47.9); const [pax, pay] = at('PA', -80.1, 40.4);
  check(midy > dy && dy > ndy && pax > midx && midx > dx - 100 && GEO.WIDTH === 1000 && GEO.H > 600 && GEO.H < 720, 'usgeo: Midland is south of Denver, Denver south of the Bakken, Pittsburgh east of both; the frame is 1000 wide');
  let lo = [1e9, 1e9]; let hi = [-1e9, -1e9];
  for (const s of Object.values(outlines)) { lo = [Math.min(lo[0], s.bb[0]), Math.min(lo[1], s.bb[1])]; hi = [Math.max(hi[0], s.bb[2]), Math.max(hi[1], s.bb[3])]; }
  check(lo[0] >= -10 && lo[1] >= -5 && hi[0] <= 1005 && hi[1] <= GEO.H, 'usgeo: all 49 outlines, Alaska\'s inset included, fall inside the frame: ' + lo.map(Math.round) + ' to ' + hi.map(Math.round));
  const ak = outlines.AK.bb; const tx = outlines.TX.bb;
  check(Object.keys(outlines).length === 49 && ak[0] < tx[0] && ak[2] < tx[0] && ak[1] > outlines.CA.bb[3] - 5, 'usgeo: 49 states; Alaska\'s inset is below California and to the left of Texas, not on top of either');
  check(GEO.stateAt(outlines, midx, midy) === 'TX' && GEO.stateAt(outlines, dx, dy) === 'CO' && GEO.stateAt(outlines, 500, 5) === null && GEO.stateAt(outlines, 600, 640) === null, 'usgeo: a point in Texas is Texas, in Colorado Colorado, and open water is no state');
  check(GEO.frameOf(outlines, 'TX').x1 - GEO.frameOf(outlines, 'TX').x0 > tx[2] - tx[0] && GEO.frameOf(outlines, 'ZZ').x1 === GEO.WIDTH, 'usgeo: a state\'s frame has air around it; an unknown state frames the country');
  // every committed well lands in the outline of the state it is filed under (nearly: the outlines are simplified to a kilometer, so a well on a border can fall just over it)
  let off = 0; const o = [0, 0];
  for (let i = 0; i < P.n; i++) { GEO.project(P.lon[i], P.lat[i], P.states[P.s[i]], o); if (GEO.stateAt(outlines, o[0], o[1]) !== P.states[P.s[i]]) off++; }
  check(off / P.n < 0.01, 'usgeo: ' + (P.n - off) + ' of the ' + P.n + ' committed wells project into the outline of their own state (' + off + ' sit on a border)');

  // newwells-data.js
  const i12 = NW.settledIndex(doc);
  check(i12 > 0 && doc.months[i12] === doc.settled.slice(0, 7) && NW.windowOf(doc).months.length === 12 && NW.windowOf(doc).months[11] === doc.months[i12] && NW.windowOf(doc).first === doc.months[i12 - 11] + '-01', 'newwells: the last 12 months end at the last settled month, not at the newest job');
  const T = NW.totals(doc);
  check(T.p12 === doc.states.reduce((t, x) => t + x.p12, 0) && T.change !== null && T.active === doc.states.filter((x) => x.p12 > 0).length && T.active < T.listed, 'newwells: the national total is the states\' sum, with a change, and counts the states that have wells (' + T.active + ' of ' + T.listed + ')');
  check(NW.change({ p12: 10, prev12: 0 }) === null && NW.change({ p12: 15, prev12: 10 }) === 0.5 && NW.shownChange({ p12: 3, prev12: 7 }) === null && NW.shownChange({ p12: 30, prev12: 20 }) === 0.5, 'newwells: a change is null from nothing (never infinity), and not shown from a base under 20 wells');
  const ranked = NW.active(doc);
  check(ranked.every((x, i) => i === 0 || ranked[i - 1].p12 >= x.p12) && ranked[0].id === 'TX', 'newwells: the states are ranked, Texas first');
  const st = NW.stack(doc);
  check(st.months.length === 36 && st.series.length >= 2 && st.series[st.series.length - 1].id === 'other' && st.settledAt === st.months.indexOf(doc.settled.slice(0, 7)) && st.settledAt < st.months.length - 1
    && st.totals.every((t, i) => t === st.series.reduce((a, s) => a + s.values[i], 0)) && st.series.filter((x) => x.id !== 'other').every((x) => NW.COLORS[x.id]), 'newwells: 36 months stacked, the colored states then "Other states", the settled month marked, the totals the sum of the stack');
  const allNew = doc.states.reduce((t, x) => t + x.new.slice(-36).reduce((a, b) => a + b, 0), 0);
  check(st.totals.reduce((a, b) => a + b, 0) === allNew, 'newwells: the stack loses no well (the colored states and the rest add up to every state\'s months)');
  const nice = NW.niceTop(1060);
  check(nice.top === 1250 && nice.ticks.length >= 4 && nice.ticks[0] === 0 && NW.niceTop(0).top === 1 && NW.niceTop(7).top >= 7 && NW.niceTop(23).ticks.every((t) => t <= NW.niceTop(23).top), 'newwells: a y axis tops at 1,250 for 1,060 (not 2,000) and handles zero');
  check(P.n === pts.n && P.day[0] >= 0 && P.span === P.day[P.n - 1] && NW.dayIso(NW.dayMs(P, P.span)) === pts.asOf && NW.dayIso(P.t0) === pts.t0, 'newwells: decode keeps every row, the days are days since t0 and the last is the as-of day');
  const [d0, d1] = NW.settledRange(P, doc);
  const byState = NW.perState(P, d0, d1);
  check(byState.length > 8 && byState[0].id === 'TX' && byState.every((x, i) => i === 0 || byState[i - 1].n >= x.n), 'newwells: wells per state over the settled year, ranked');
  const perDayAll = NW.perDay(P, 0, P.span);
  check(perDayAll.length === P.span + 1 && perDayAll.reduce((a, b) => a + b, 0) === P.n && NW.perDay(P, 5, 3).length === 0, 'newwells: wells per day add up to every point; an empty range is empty');
  const txShare = byState.find((x) => x.id === 'TX').n; const txSummary = NW.byId(doc, 'TX').p12;
  check(txShare <= txSummary && txShare >= 0.9 * txSummary, 'newwells: Texas\'s located wells in the settled year (' + txShare + ') are the summary\'s ' + txSummary + ' or just under (every well in the file has a point)');
  const co = NW.leaders(P, d0, d1, { by: 'c', limit: 10 }); const op = NW.leaders(P, d0, d1, { by: 'o', limit: 10 }); const opTx = NW.leaders(P, d0, d1, { state: 'TX', by: 'o', limit: 5 });
  check(co.rows.length === 10 && co.rows.every((r, i) => i === 0 || co.rows[i - 1].n >= r.n) && co.rows[0].state && op.rows.length === 10 && op.total === op.rows.reduce((a, r) => a + r.n, 0) + op.unnamed + (op.total - op.unnamed - op.rows.reduce((a, r) => a + r.n, 0)) && opTx.total <= op.total, 'newwells: the busiest counties carry their state, the operators are ranked, a state\'s list is within the nation\'s');
  check(!/\d{10}/.test(JSON.stringify(op.rows) + JSON.stringify(co.rows)) && op.unnamed >= 0 && op.unnamed < op.total, 'newwells: operators only where they may be named: the unnamed are counted, never listed');
  const land = NW.landShare(P, d0, d1);
  check(land.of > 5000 && land.n > 0 && land.n < land.of && NW.landShare(P, d0, d1, 'TX').of < land.of, 'newwells: the share on federal or tribal land (' + land.n + ' of ' + land.of + ')');
  const nw = NW.newest(P, 5); const nwTx = NW.newest(P, 5, 'ND');
  check(nw.length === 5 && P.day[nw[0]] === P.span && nw.every((i, k) => k === 0 || P.day[nw[k - 1]] >= P.day[i]) && nwTx.every((i) => P.states[P.s[i]] === 'ND'), 'newwells: the newest wells, newest first, one state\'s on request');
  const dayStates = NW.perDayByState(P, 0, P.span); const sumOfStates = [...dayStates.values()].reduce((t, v) => t + v.reduce((a, b) => a + b, 0), 0);
  check(sumOfStates === P.n && dayStates.get('TX').length === P.span + 1 && dayStates.get('TX').every((v, i) => v === NW.perDay(P, 0, P.span, 'TX')[i]) && NW.perDayByState(P, 5, 3).size === 0, 'newwells: wells per day for every state at once add up to every point and equal the one-state count');
  const busy = NW.lastBusyDay(P, 10);
  check(busy > 0 && busy <= P.span && NW.perDay(P, busy, busy)[0] >= 10 && NW.perDay(P, busy + 1, P.span).every((n) => n < 10) && NW.lastBusyDay(P, 1e9) === P.span, 'newwells: the Daily report opens on the newest day with ten or more wells (the newest days have a few so far), or on the last day when none has that many');
  check(NW.firstAtOrAfter(P, 0) === 0 && NW.firstAtOrAfter(P, P.span + 1) === P.n && P.day[NW.firstAtOrAfter(P, 100)] >= 100 && (NW.firstAtOrAfter(P, 100) === 0 || P.day[NW.firstAtOrAfter(P, 100) - 1] < 100), 'newwells: the first well at or after a day, by binary search');
  const q = NW.quiet(doc, [{ id: 'TX', name: 'Texas' }, { id: 'AL', name: 'Alabama' }, { id: 'ZZ', name: 'Nowhere' }]);
  check(q.length === 2 && q[0].id === 'AL' && q[0].latest === NW.byId(doc, 'AL').latest && q[1].latest === null, 'newwells: a producing state with no well in the last 12 months is "quiet" (with its last job, or none ever), a state with wells is not');
  check(NW.listAnd(['a']) === 'a' && NW.listAnd(['a', 'b']) === 'a and b' && NW.listAnd(['a', 'b', 'c']) === 'a, b and c' && NW.feet(95) === '9,500 ft' && NW.feet(0) === null && NW.gallons(210) === '21.0 million gal' && NW.gallons(0) === null, 'newwells: the wording helpers (a list, feet in hundreds, gallons in hundreds of thousands, nothing for zero)');
  check(NW.colorOf('TX') === 'var(--st-tx)' && NW.colorOf('NM') === 'var(--st-nm)' && NW.colorOf('OK') === 'var(--st-ok)' && NW.colorOf('WY') === NW.OTHER_COLOR, 'newwells: Texas, New Mexico and Oklahoma keep the colors the rest of the site gives them; every other state is slate');
  // arrivalRows: fractured wells found and oil well permits approved, day by day, side by side and never added
  const arrIn = { v: 1, since: '2026-10-30', against: { TX: { wells: 83, from: '2026-10-30' } }, days: [{ day: '2026-10-31', found: 41, removed: 0, states: [['TX', 25, 3], ['NM', 9, null], ['OK', 7, null]] }] };
  const rep = (rows) => ({ days: rows.map(([d, dd, pn, st]) => ({ d, dd, pn, s: st || 'ok' })) });
  const reports = { TX: rep([['2026-10-31', '2026-10-30', 36], ['2026-10-30', '2026-10-29', 30], ['2026-10-29', '2026-10-28', 28], ['2026-10-28', '2026-10-27', 99, 'partial']]), OK: rep([['2026-10-31', '2026-10-30', 7], ['2026-10-30', '2026-10-29', 2]]), NM: rep([['2026-10-31', '2026-10-29', 5]]) };
  const rows = NW.arrivalRows(arrIn, reports, 14); const r31 = rows[0]; const r30 = rows[1]; const r29 = rows[2];
  check(rows.map((r) => r.day).join() === '2026-10-31,2026-10-30,2026-10-29' && r31.fractured === 41 && r31.oilTotal === 48 && r31.oil.map((o) => o[0] + o[1]).join() === 'TX36,OK7,NM5' && r31.both === 3, 'arrivalRows: a day carries the wells found and, apart, each state\'s oil well permits in the order TX, OK, NM; the two are never added (41 and 48)');
  check(r30.fractured === 0 && r30.both === 0 && r30.oilTotal === 32 && r30.byState.length === 0, 'arrivalRows: a day that was compared and had nothing new is a real zero');
  check(r29.fractured === null && r29.both === null && r29.oilTotal === 28 && !rows.some((r) => r.day === '2026-10-28'), 'arrivalRows: a day before the comparison began has no number for the fractured side (null, not a zero) but keeps its oil permits, and a state report that was not read (status partial) is left out, not counted as none');
  check(NW.arrivalRows(null, reports, 14).every((r) => r.fractured === null && r.both === null) && NW.arrivalRows({ ...arrIn, since: null }, reports, 14).every((r) => r.fractured === null) && NW.arrivalRows(arrIn, null, 14).length === 1 && NW.arrivalRows(arrIn, reports, 2).length === 2, 'arrivalRows: no log, or a log that has not compared yet, gives no number for the fractured side; no state reports still lists the found day; n limits the days');
  check(NW.OIL_STATES.join() === 'TX,OK,NM' && rows.every((r) => !/\d{10}/.test(JSON.stringify(r))), 'arrivalRows: the oil side is the three states whose daily reports are kept, and no API number is in a row');

  // typicalDay: a day is set against the twelve months it sits in
  const tdNew = NW.typicalDay(doc, doc.asOf); const tdSettled = NW.typicalDay(doc, '2026-03-10'); const td14 = NW.typicalDay(doc, '2014-03-12'); const td11 = NW.typicalDay(doc, '2011-01-05'); const tdTx = NW.typicalDay(doc, '2014-03-12', 'TX');
  check(tdNew.latest && tdNew.to === doc.settled.slice(0, 7) && Math.abs(tdNew.perDay - NW.totals(doc).p12 / 365) < 0.01 && tdSettled.latest, 'newwells: the newest days are set against the last 12 settled months (the figure the page always had: p12 over 365)');
  check(!td14.latest && td14.from === '2013-10' && td14.to === '2014-09' && td14.perDay > 50 && td14.perDay < 120 && !td11.latest && td11.from === '2011-01' && td11.to === '2011-12' && tdTx.perDay > 0 && tdTx.perDay < td14.perDay,
    'newwells: a day in 2014 is set against Oct 2013 to Sep 2014 (' + td14.perDay.toFixed(1) + ' a day, not last year\'s ' + tdNew.perDay.toFixed(1) + '), the first days against the first twelve months, one state against its own');
  check(NW.typicalDay(doc, '2030-01-01').latest && NW.typicalDay(doc, '2001-01-01').from === '2011-01' && NW.drilled(NW.byId(doc, 'AL')) && !NW.drilled({ new: [0, 0] }), 'newwells: a day outside the series gets the nearest twelve months, and a state with a well only years ago counts as drilled');
  // profile: what a set of wells looks like (the Daily report's numbers card), on a handmade set whose answers are known, then on the committed wells
  const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
  const mk = (rows) => ({ v: 1, t0: '2026-01-01', asOf: '2026-01-02', n: rows.length, states: ['TX', 'NM'], counties: [['TX', 'Martin'], ['TX', 'Midland'], ['NM', 'Lea']], ops: ['A LLC', 'B LLC'],
    lat: rows.map((r) => r[0]), lon: rows.map((r) => r[1]), d: rows.map((r) => r[2]), s: rows.map((r) => r[3]), c: rows.map((r) => r[4]), o: rows.map((r) => r[5]), tvd: rows.map((r) => r[6]), h2o: rows.map((r) => r[7]), f: rows.map((r) => r[8]) });
  //            lat      lon       day state county op  tvd  h2o  land
  const H = NW.decode(mk([
    [320000, -1020000, 0, 0, 0, 0, 90, 200, 0], [320001, -1020000, 0, 0, 0, 0, 100, 210, 1], [320010, -1020000, 0, 0, 0, 1, 0, 0, 0], // a pad: 0.0001 and 0.0010 degrees north (11 m and 111 m)
    [320020, -1020000, 0, 0, 1, -1, 130, 300, 2], // 222 m from the first well but 111 m from the third: the same pad through a chain
    [326000, -1020000, 0, 1, 2, 1, 50, 10, 3], // 41 miles away, in New Mexico
    [320000, -1020000, 1, 0, 0, 0, 95, 205, 0]]));
  const pr = NW.profile(H, 0, 0, { hot: true }); const prNm = NW.profile(H, 0, 0, { state: 'NM', hot: true }); const prNone = NW.profile(H, 5, 3, { hot: true });
  check(pr.n === 5 && pr.states === 2 && pr.counties === 3 && pr.pads === 2 && NW.padsOf(H, NW.indexesOf(H, 0, 1)) === 3, 'profile: five wells in two states and three counties; four within 150 m of each other through a chain are one pad, so two pads that day (and the next day\'s well is its own pad, not the first day\'s: three over both days)');
  check(pr.depth.n === 4 && pr.depth.median === 9500 && pr.depth.max.ft === 13000 && pr.depth.max.county === 'Midland' && pr.depth.max.state === 'TX' && eq(pr.depth.bands, [1, 0, 1, 1, 1]), 'profile: depth is counted over the four wells that report one (a depth of nothing is not zero feet), the median is the middle of the four, the deepest names its county, and the bands add up');
  check(pr.water.n === 4 && Math.abs(pr.water.total - 72) < 1e-9 && pr.water.median === 20.5 && pr.water.max.mgal === 30 && Math.abs(pr.water.pools - 72e6 / NW.POOL_GAL) < 1e-9 && pr.water.pools > 100 && pr.water.pools < 120, 'profile: water is counted over the four wells that report it (units are 100,000 gallons: 72 million in all), the median, the most and the Olympic pools it fills');
  check(eq(pr.land.counts, [2, 1, 1, 1]) && pr.land.federalOrTribal === 3 && pr.operators.named === 2 && pr.operators.unnamed === 1 && eq(pr.operators.top, [{ label: 'A LLC', n: 2 }, { label: 'B LLC', n: 2 }]) && eq(pr.topCounties.map((c) => c.label + c.n), ['Martin3', 'Lea1', 'Midland1']) && pr.weekday[4] === 5 && pr.weekday.reduce((a, b) => a + b, 0) === 5, 'profile: land by class, the operators that may be named (the one that may not is counted, never named), counties ranked with ties by name, and the weekday of 2026-01-01 (a Thursday)');
  check(pr.hot && pr.hot.n === 4 && pr.hot.of === 5 && pr.hot.county === 'Martin' && pr.hot.state === 'TX' && NW.hotSpot(H, NW.indexesOf(H, 0, 0).slice(0, 2)) === null && prNm.n === 1 && prNm.pads === 1 && prNm.hot === null && NW.profile(H, 0, 0).hot === null, 'profile: the busiest spot is four of the five wells within 10 miles (around Martin County), none for under three wells, and only when asked; one state\'s wells are counted alone');
  check(prNone.n === 0 && prNone.pads === 0 && prNone.depth.median === null && prNone.water.median === null && prNone.water.total === 0 && prNone.depth.max === null && prNone.operators.top.length === 0 && prNone.hot === null && !/NaN|undefined|Infinity/.test(JSON.stringify(prNone)), 'profile: no wells gives no medians (null, not zero) and no NaN');
  const wholeYear = NW.profile(P, d0, d1); const wholeTx = NW.profile(P, d0, d1, { state: 'TX' });
  check(wholeYear.n === byState.reduce((t, x) => t + x.n, 0) && wholeYear.land.counts.reduce((a, b) => a + b, 0) === wholeYear.n && wholeYear.depth.bands.reduce((a, b) => a + b, 0) === wholeYear.depth.n && wholeYear.weekday.reduce((a, b) => a + b, 0) === wholeYear.n
    && wholeYear.depth.median > 8000 && wholeYear.depth.median < 11000 && wholeYear.water.median > 10 && wholeYear.water.median < 30 && wholeYear.states >= 8 && wholeTx.n < wholeYear.n && wholeTx.states === 1 && wholeYear.pads < wholeYear.n && wholeYear.pads > wholeYear.n / 4, 'profile: the settled year\'s wells on the committed file add up (every well has a land class, a weekday and at most one depth band), the median well is about 9,400 ft and 20 million gallons, and a pad is a few wells (' + wholeYear.pads + ' pads for ' + wholeYear.n + ' wells)');
  check(!/\d{10}/.test(JSON.stringify(wholeYear.operators) + JSON.stringify(wholeYear.topCounties)) && wholeYear.operators.top.every((r) => !/@|http|www\./i.test(r.label)) && wholeYear.operators.unnamed < wholeYear.n, 'profile: the operators it lists carry no number, address or web address, and the ones that may not be named are only counted');
  const trg = NW.typicalRange(P, doc, doc.asOf); const trgOld = NW.typicalRange(P, doc, '2024-12-15'); const trgGone = NW.typicalRange(P, doc, '2011-02-01');
  check(trg && !trg.clipped && trg.from === NW.windowOf(doc).first && trg.to === doc.settled && trg.d1 - trg.d0 === 364 && trgOld && trgOld.clipped && trgOld.d0 === 0 && trgGone === null, 'typicalRange: the newest days are set against the last 12 settled months in whole, a day near the start of the last two years against the months the points hold (clipped), and a day whose months are not in the points against none');
  const D0 = NW.dayOfIso(P, '2026-03-10'); const rk = NW.dayRank(P, D0, trg.d0, trg.d1); const rkNone = NW.dayRank(P, 3, 5, 3);
  check(rk && rk.days === 365 && rk.share >= 0 && rk.share <= 1 && rk.n === NW.perDay(P, D0, D0)[0] && P.states.includes('AL') && NW.dayRank(P, trg.d0, trg.d0, trg.d1, 'AL').share === 0 && rkNone === null, 'dayRank: the share of the days that had fewer wells (0 to 1) over the 365 days, null for an empty range, and a state with no wells never ranks above anyone');
  // monthPos: where a day sits on the month axis of the Daily report's overview strip (Jan 1, 2011 is 0, each month is one step, a day is its share of its month)
  const lastM = doc.months.length - 1;
  check(NW.monthPos(doc, '2011-01-01') === 0 && NW.monthPos(doc, '2011-02-01') === 1 && Math.abs(NW.monthPos(doc, '2011-01-16') - 15 / 31) < 1e-9 && Math.abs(NW.monthPos(doc, '2012-03-01') - 14) < 1e-9 && NW.monthPos(doc, '2010-12-01') === -1
    && NW.monthPos(doc, doc.months[lastM] + '-01') === lastM && Math.abs(NW.monthPos(doc, '2012-02-15') - (13 + 14 / 29)) < 1e-9 && NW.monthPos(doc, doc.asOf) > lastM - 1 && NW.monthPos(doc, doc.asOf) < lastM + 1,
    'newwells: monthPos puts a day on the strip\'s month axis (Jan 1, 2011 at 0, a month a step, leap February by its 29 days, the newest well inside the last month)');
  // decodePermits: the agencies' oil permits and spuds that have a point, on the wells' days (the Daily report draws them as rings beside the fracked wells)
  const pdocs = NW.PERMIT_SOURCES.map((x) => ({ id: x.id, pm: read(x.file) }));
  const dayOff = (pm, t0) => Math.round((Date.parse(pm.t0 + 'T00:00:00Z') - Date.parse(t0 + 'T00:00:00Z')) / 864e5);
  const Qp = NW.decodePermits(pdocs, pts.t0);
  const wantN = pdocs.reduce((t, d) => t + d.pm.pts.filter((r) => r[3] + dayOff(d.pm, pts.t0) >= 0).length, 0);
  check(Qp.n === wantN && wantN > 10000 && Qp.states.join() === 'TX,OK,NM,FO' && Qp.spud.join() === '0,0,1,1' && Qp.day.every((d, i) => i === 0 || d >= Qp.day[i - 1]) && Qp.day[0] >= 0,
    'permits: ' + Qp.n + ' points from the four agencies, sorted by day, none before the wells\' first day; Texas and Oklahoma count permits, New Mexico and the offshore spuds');
  const aDay = Qp.day[Math.floor(Qp.n / 2)]; const iso = NW.dayIso(NW.dayMs({ t0: Date.parse(pts.t0 + 'T00:00:00Z') }, aDay));
  const wantDay = pdocs.reduce((t, d) => t + d.pm.pts.filter((r) => r[3] + dayOff(d.pm, pts.t0) === aDay).length, 0);
  const perSt = NW.permitsPerState(Qp, aDay, aDay);
  check(wantDay > 0 && NW.permitsOfDay(Qp, aDay).length === wantDay && perSt.reduce((t, x) => t + x.n, 0) === wantDay && perSt.every((x, i) => i === 0 || perSt[i - 1].n >= x.n)
    && NW.permitsOfDay(Qp, aDay, perSt[0].id).length === perSt[0].n && NW.permitsOfDay(Qp, aDay, 'ND').length === 0 && NW.permitsOfDay(Qp, -5).length === 0,
    'permits: ' + iso + ' has ' + wantDay + ' in the files and in the decoder, ranked by state, and a state with no source has none');
  const named = Array.from({ length: Qp.n }, (_, i) => NW.permitOperator(Qp, i)).filter(Boolean);
  const pfo = pdocs.find((d) => d.id === 'FO').pm;
  check(named.length > 5000 && named.every((x) => typeof x === 'string') && Qp.op.some((o) => o < 0) && NW.permitWord(Qp, Qp.s.indexOf(2)) === 'Well spudded' && NW.permitWord(Qp, Qp.s.indexOf(0)) === 'Permit approved'
    && NW.permitStateName('FO') === 'Federal offshore' && Qp.last[3] === Math.max(...pfo.pts.map((r) => r[3])) + dayOff(pfo, pts.t0) && Qp.last.every((d) => d > 0),
    'permits: only named operators carry a name (the rest are -1), spuds and permits are told apart, and each state\'s newest day is its file\'s');
  const Qlate = NW.decodePermits(pdocs, '2025-06-01');
  check(Qlate.n < Qp.n && Qlate.day.every((d) => d >= 0) && Qlate.n === pdocs.reduce((t, d) => t + d.pm.pts.filter((r) => r[3] + dayOff(d.pm, '2025-06-01') >= 0).length, 0), 'permits: a later first day leaves out the permits before it and renumbers the rest from it');
  // the history: every well with a point since 2011, joined to the last two years' points
  const hist = read('newwells/points-history');
  const mp = NW.mergePoints(pts, hist); const PH = NW.decode(mp);
  const shift = Math.round((Date.parse(pts.t0 + 'T00:00:00Z') - Date.parse(hist.t0 + 'T00:00:00Z')) / 864e5);
  const kept = hist.d.filter((d) => d < shift).length;
  check(doc.months[0] === '2011-01' && NW.stack(doc, doc.months.length).months.length === doc.months.length && NW.stack(doc, doc.months.length).totals.reduce((a, b) => a + b, 0) === doc.states.reduce((t, x) => t + x.new.reduce((a, b) => a + b, 0), 0), 'newwells: the months run from 2011-01 and the all-years stack loses no well');
  check(PH.n === kept + pts.n && kept < hist.n && kept > 100000 && PH.n > 200000 && NW.dayIso(PH.t0) === '2011-01-01' && NW.dayIso(NW.dayMs(PH, PH.span)) === pts.asOf && NW.yearsOf(PH) >= 15, 'newwells: the history and the points make one set (' + PH.n + ' wells, ' + NW.yearsOf(PH) + ' years); the history\'s overlap with the points is dropped, not counted twice');
  let sorted = true; for (let i = 1; i < PH.n; i++) if (PH.day[i] < PH.day[i - 1]) { sorted = false; break; }
  check(sorted && PH.day[0] >= 0 && NW.firstAtOrAfter(PH, shift) === kept, 'newwells: the merged days are in order, and the points file\'s own wells start where the history\'s kept ones end');
  let same = true; // a sample of both halves keeps its place, day, state, county and operator through the merge
  for (const [src, base, idx] of [[hist, 0, [0, 1, 777, 5000, 90000, kept - 1]], [pts, kept, [0, 1, 500, 9000, pts.n - 1]]]) {
    for (const k of idx) {
      const i = base + k; const c = src.c[k]; const o = src.o[k];
      const day = (src === hist ? Date.parse(hist.t0 + 'T00:00:00Z') : Date.parse(pts.t0 + 'T00:00:00Z')) + src.d[k] * 864e5;
      if (Math.abs(PH.lat[i] - src.lat[k] / 1e4) > 1e-3 || Math.abs(PH.lon[i] - src.lon[k] / 1e4) > 1e-3 || NW.dayMs(PH, PH.day[i]) !== day || PH.states[PH.s[i]] !== src.states[src.s[k]]
        || NW.countyOf(PH, i) !== (c >= 0 ? src.counties[c][1] : null) || NW.operatorOf(PH, i) !== (o >= 0 ? src.ops[o] : null) || PH.tvd[i] !== src.tvd[k] || PH.h2o[i] !== src.h2o[k] || PH.f[i] !== src.f[k]) same = false;
    }
  }
  check(same, 'newwells: a sample of wells from the history and from the points keeps its place, day, state, county, operator, depth, water and land through the merge');
  check(PH.counties.every((c) => PH.states.includes(c[0])) && new Set(PH.counties.map((c) => c.join('|'))).size === PH.counties.length && new Set(PH.ops).size === PH.ops.length && PH.counties.length >= pts.counties.length && PH.ops.length >= pts.ops.length, 'newwells: the merged county and operator tables hold each name once, the points file\'s first');
  const perStateAll = NW.perState(PH, 0, PH.span); const wellsByState = new Map(doc.states.map((x) => [x.id, x.new.reduce((a, b) => a + b, 0)]));
  check(perStateAll.length > 20 && perStateAll.every((x) => x.n <= wellsByState.get(x.id) && x.n >= 0.97 * wellsByState.get(x.id)), 'newwells: every state\'s points since 2011 are its wells in the summary or just under (' + perStateAll.length + ' states)');
  const [h0, h1] = NW.settledRange(PH, doc);
  check(h1 - h0 > 300 && NW.dayMs(PH, h1) === NW.dayMs(P, d1) && NW.landShare(PH, h0, h1).of === land.of && NW.leaders(PH, h0, h1, { by: 'c', limit: 3 }).rows.map((r) => r.label + r.n).join() === NW.leaders(P, d0, d1, { by: 'c', limit: 3 }).rows.map((r) => r.label + r.n).join(),
    'newwells: the settled year over the merged points is the same year as over the points alone (the panel and the lists read the same wells either way)');
  check((() => { try { NW.mergePoints(pts, { ...hist, states: hist.states.slice().reverse() }); return false; } catch (e) { return /same read/.test(e.message); } })(), 'newwells: a history from another read than the points (other states) is refused');
}

/* ---------- oil-day-data.js: the permits the three daily-publishing states approved each day, for the Daily report's chart and summary ---------- */
{
  const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
  // a made-up week: Oklahoma's points (day in column 3) with a weekend in them, Texas's and New Mexico's series
  const okPts = { t0: '2026-01-01', asOf: '2026-01-10', pts: [[0, 0, 0, 0, 0, 39], [0, 0, 0, 5, 0, 39], [0, 0, 0, 5, 0, 17], [0, 0, 0, 6, 0, 39], [0, 0, 0, 20, 0, 39]] };
  const tx = { days: ['2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08'], newDrill: [0, 0, 30, 28, 25, 31] };
  const nm = { days: ['2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08', '2026-01-09'], newDrill: [2, 0, 0, 5, 4, 6, 7, 9] };
  const cn = OD.counts({ tx, nm, okPoints: okPts });
  check(cn.first === '2026-01-03' && cn.last === '2026-01-08' && cn.per.OK.get('2026-01-01') === 1 && cn.per.OK.get('2026-01-02') === 0 && cn.per.OK.get('2026-01-06') === 2 && cn.per.OK.get('2026-01-10') === 0 && cn.per.OK.size === 10, 'oil days: the days that count are the days all three states have (here Jan 3 to Jan 8), and Oklahoma\'s counts come from its permit points with the zeros in them (a point past the file\'s end is not counted)');
  check(eq(OD.permitsOn(cn, '2026-01-05'), [{ id: 'TX', name: 'Texas', n: 30 }, { id: 'OK', name: 'Oklahoma', n: 0 }, { id: 'NM', name: 'New Mexico', n: 5 }]) && OD.permitsOn(cn, '2026-01-02') === null && OD.permitsOn(cn, '2026-01-09') === null && OD.permitsOn(null, '2026-01-05') === null
    && OD.permitsOn(OD.counts({ tx, nm: { days: ['2026-01-02', '2026-01-04', '2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08'], newDrill: [2, 0, 5, 4, 6, 7] }, okPoints: okPts }), '2026-01-03') === null, 'oil days: a day inside the range has a count for each state; a day outside it, or one a state has no count for, has none (null), never zero');
  const vals = OD.valuesOver(cn, '2026-01-02', 8); const valsTx = OD.valuesOver(cn, '2026-01-02', 8, 'TX'); const valsNd = OD.valuesOver(cn, '2026-01-02', 8, 'ND');
  check(eq(vals, [null, 0, 0, 35, 34, 32, 38, null]) && eq(valsTx, [null, 0, 0, 30, 28, 25, 31, null]) && valsNd.every((v) => v === null), 'oil days: the chart\'s line is the three states added (Jan 5: 30 + 0 + 5; the weekend is a real zero), or one state\'s, null outside the days all three have, and all null for a state that is not one of the three');
  // the committed files: every day the counts cover has a count for all three states, and the sources agree where they overlap
  const txS = read('daily/permits-series'); const nmS = read('daily-nm/permits-series'); const okP = read('permits-ok'); const real = OD.counts({ tx: txS, nm: nmS, okPoints: okP });
  let allDays = true;
  for (let t = Date.parse(real.first + 'T00:00:00Z'); t <= Date.parse(real.last + 'T00:00:00Z'); t += 864e5) { const r = OD.permitsOn(real, new Date(t).toISOString().slice(0, 10)); if (!r || r.length !== 3 || r.some((x) => !Number.isInteger(x.n) || x.n < 0)) allDays = false; }
  const lastOf = (name) => { const m = new Map(); for (const r of read(name).days) if (r.dd) m.set(r.dd, r); return m; };
  const lastOk = lastOf('daily-ok/index'); const lastTx = lastOf('daily/index'); const lastNm = lastOf('daily-nm/index');
  check(real.first >= '2026-07-21' && real.last <= txS.days[txS.days.length - 1] && real.last >= '2026-10-01' && allDays
    && [...lastOk].every(([dd, r]) => real.per.OK.get(dd) === r.pn) && [...lastTx].every(([dd, r]) => !real.per.TX.has(dd) || real.per.TX.get(dd) === r.pn) && [...lastNm].every(([dd, r]) => !real.per.NM.has(dd) || real.per.NM.get(dd) === r.pn),
  'oil days: on the committed files every day from ' + real.first + ' to ' + real.last + ' has a count for Texas, Oklahoma and New Mexico, and each state\'s count equals its nightly capture\'s on every day the capture has (Oklahoma\'s from the permit points)');
  const wk = (iso) => new Date(iso + 'T00:00:00Z').getUTCDay(); let weekend = 0; let weekdays = 0;
  for (const [d, n] of real.per.OK) if (d >= real.first && d <= real.last) { if (wk(d) === 0 || wk(d) === 6) weekend += n; else weekdays += n; }
  check(weekdays > 20 && weekend <= weekdays / 10, 'oil days: Oklahoma approves on weekdays (' + weekdays + ' on weekdays and ' + weekend + ' on weekends in the covered days), so a weekend zero is a real zero and not a gap');
}

/* ---------- combined-data.js: the merged Overview's two national sources side by side ---------- */
{
  const nat = read('national'); const doc = read('newwells/summary'); const Nn = await imp('national-data.js');
  const list = CB.jurisdictions(nat, doc);
  const ids = list.map((j) => j.id);
  check(new Set(ids).size === ids.length && nat.states.every((s) => ids.includes(s.id)) && nat.gaps.every((g) => ids.includes(g.id)) && doc.states.every((s) => ids.includes(s.id)), 'combined: one list of every jurisdiction either source knows, each once (' + ids.length + ')');
  check(list.filter((j) => j.p).length === nat.states.length && list.filter((j) => j.w).length === doc.states.length && list.every((j) => !(j.p && j.g)), 'combined: each row holds the agency\'s record, the registry\'s record, or both, and a state is not both read and a gap');
  const T = CB.totals(nat, doc);
  check(T.permits === nat.totals.permits12 && T.spuds === nat.totals.spuds12 && T.permitStates === nat.totals.permitStates && T.spudStates === nat.totals.spudStates, 'combined: the permits and the wells spudded are the national report\'s totals, each within its own count');
  check(T.wells === doc.states.reduce((t, s) => t + s.p12, 0) && T.wellStates === doc.states.filter((s) => s.p12 > 0).length && !('all' in T) && !('total' in T), 'combined: the fractured wells are the registry\'s, and no total adds the two layers');
  check(T.both + T.permitsOnly === T.permitJurisdictions && T.both <= T.wellJurisdictions && T.blm === Nn.byId(nat, 'BL').p12, 'combined: the states with both, with permits only and the BLM add up and the BLM is apart');
  const pf = (id) => CB.permitFigure(Nn.byId(nat, id));
  check(pf('AZ').none === true && pf('CA').change === null && pf('TX').sum === true && pf('BL').sum === false && pf('BL').overlap === true && pf('VA').sum === false && pf('NM').word === 'spuds' && pf('TX').word === 'permits' && CB.permitFigure(null) === null,
    'combined: a figure says none recorded where the source dates nothing, shows no change from a small base, adds only permits and spuds (not the BLM, applications or wells drilled) and names what it counts');
  check(CB.wellFigure(Nn.byId(nat, 'TX') && doc.states.find((s) => s.id === 'TX')).n > 0 && CB.wellFigure(doc.states.find((s) => s.p12 === 0)) === null && CB.wellFigure(null) === null, 'combined: a state with no fractured well in 12 months has no figure (the page says "not in the registry", never 0)');
  for (const by of ['permits', 'wells']) {
    const R = CB.rankRows(nat, doc, by); const all = [...R.rows, ...R.none, R.fed].map((j) => j.id);
    const key = (j) => (by === 'wells' ? (CB.wellFigure(j.w) ? j.w.p12 : -1) : (j.p ? j.p.p12 : -1));
    check(all.length === ids.length && new Set(all).size === ids.length && R.fed.id === 'BL' && R.rows.every((j, i) => !i || key(R.rows[i - 1]) >= key(j)) && R.none.every((j) => !j.p && !CB.wellFigure(j.w)),
      'combined: ranked by ' + by + ', every jurisdiction is in exactly one place, in order, the BLM apart and the ones with nothing in neither source last');
  }
  const M = CB.monthly(nat, doc);
  const ps = Nn.stack(nat, 'permits', nat.months.length); const ss = Nn.stack(nat, 'spuds', nat.months.length);
  check(M.months[0] === nat.months[0] && M.months.length === M.wells.months.length && M.permits.values.length === M.months.length && M.spuds.values.length === M.months.length
    && M.months.every((m, i) => { const a = ps.months.indexOf(m); const b = ss.months.indexOf(m); return M.permits.values[i] === (a < 0 ? null : ps.totals[a]) && M.spuds.values[i] === (b < 0 ? null : ss.totals[b]); }),
    'combined: the month chart runs from the agencies\' first month, each line is the national report\'s stack for its own count (null after its end), and the bars are the registry\'s months');
  check(M.permits.end === ps.end && M.spuds.end === ss.end && M.permits.values[M.months.indexOf(M.permits.end)] != null && M.permits.values.slice(M.months.indexOf(M.permits.end) + 1).every((v) => v == null) && M.wells.settledAt >= 0, 'combined: a line ends where its agencies\' files do, so a late agency is never read as a fall');
  const sm = CB.stateMonthly(nat, doc, 'TX', 36); const tx = Nn.byId(nat, 'TX');
  check(sm.months.length === 36 && sm.permits.length === 36 && sm.wells.length === 36
    && sm.permits.slice(0, 20).every((v, i) => v === tx.bands.new[nat.months.indexOf(sm.months[i])]) && sm.wells.slice(0, 20).every((v, i) => v === doc.states.find((s) => s.id === 'TX').new[doc.months.indexOf(sm.months[i])]), 'combined: one state\'s two lines are its own monthly figures from each file');
  const al = CB.stateMonthly(nat, doc, 'AL', 12); const bl = CB.stateMonthly(nat, doc, 'BL', 12);
  check(al.wells === null && al.permits.length === 12 && bl.wells === null && bl.permits.length === 12 && CB.stateMonthly(nat, doc, 'MO', 12).permits === null, 'combined: a state with no fractured well has no wells line, and one with no agency file read has no permits line');
  // leaders: only the agencies that count permits approved, each state's top list, operators added up by name
  const fake = { months: ['2026-01'], states: [
    { id: 'AA', name: 'Aland', measure: 'permits', p12: 10, prev12: 9, counties: [['North', 6], ['South', 4]], operators: [['Big Oil, Inc.', 5], ['Small LLC', 3]], bands: { new: [10] } },
    { id: 'BB', name: 'Bland', measure: 'permits', p12: 9, prev12: 9, counties: [['North', 9]], operators: [['BIG OIL INC', 4]], bands: { new: [9] } },
    { id: 'CC', name: 'Cland', measure: 'spuds', p12: 99, prev12: 9, counties: [['Far', 99]], operators: [['Spud Co', 99]], bands: { new: [99] } },
    { id: 'BL', name: 'Federal', measure: 'permits', p12: 500, prev12: 9, counties: [['Fed', 500]], operators: [['Fed Co', 500]], bands: { new: [500] } },
  ], gaps: [] };
  const lc = CB.permitLeaders(fake, 'counties', 5); const lo = CB.permitLeaders(fake, 'operators', 5);
  check(lc.rows.map((r) => r.label + r.state + r.n).join() === 'NorthBB9,NorthAA6,SouthAA4' && lc.states === 2, 'combined: the busiest counties are kept apart by state, and a state that counts spuds and the BLM are left out');
  check(lo.rows.map((r) => r.n).join() === '9,3' && lo.rows[0].label === 'Big Oil, Inc.' && lo.rows[0].state === null, 'combined: the top operators add up one company across states by name (case and punctuation aside), never the spud states or the BLM');
  check(CB.stateLeaders({ counties: [['A', 3], ['B', 2]] }, 'counties', 1).length === 1 && CB.stateLeaders(null, 'counties').length === 0, 'combined: one agency\'s own top list, none for a state with no file');
  const R = CB.rings(nat);
  check(R.every((r) => r.n > 0 && r.id !== 'BL') && R.some((r) => r.id === 'FO') && !R.some((r) => r.id === 'AZ'), 'combined: a ring for every agency with something dated in 12 months, none for the BLM (not a place) or a state with none recorded');
  const Rc = CB.reach(nat, doc);
  check(/^\d{4}-\d{2}$/.test(Rc.permitsMedian) && Rc.permitsFirst <= Rc.permitsMedian && Rc.permitsMedian <= Rc.permitsLast && Rc.wells === doc.asOf, 'combined: how far each source runs is the registry\'s newest job and the month the agencies\' files end in');
}

/* ---------- companies-data.js: the Companies page's national operator list ---------- */
{
  const nat = read('national');
  const rows = CD.listedRows(nat);
  const others = nat.states.filter((q) => !CD.FULL.includes(q.id) && Array.isArray(q.operators));
  const want = others.reduce((t, q) => t + q.operators.length, 0);
  check(CD.FULL.join() === 'TX,OK,NM,FO' && same(CD.FULL, S.STATES.map((q) => q.id)), 'companies: the four jurisdictions with a full operator file are the site\'s four states, and they are the ones left out of the listed rows');
  check(rows.length === want && want > 150 && rows.every((r) => !CD.FULL.includes(r.st)) && new Set(rows.map((r) => r.st)).size === others.filter((q) => q.operators.length).length,
    'companies: every operator the National report names for another state is a row (' + rows.length + ' of ' + want + ', ' + new Set(rows.map((r) => r.st)).size + ' states), and none for the four full files');
  const byState = new Map(nat.states.map((q) => [q.id, q]));
  check(rows.every((r) => r.measure === byState.get(r.st).measure && r.stName === byState.get(r.st).name && r.new12 > 0 && Number.isInteger(r.new12) && r.band === (r.new12 >= 10 ? 'A' : 'B') && r.listed === 1)
    && same(rows.filter((r) => r.st === 'ND').map((r) => [r.name, r.new12]), byState.get('ND').operators) && rows.filter((r) => r.st === 'ND').every((r) => r.measure === 'spuds'),
    'companies: a row keeps its state\'s own measure (North Dakota\'s are wells spudded), the busiest first as the report lists them, and its band is 10 or more (A) or 1 to 9 (B)');
  check(rows.every((r) => r.m24 === null && r.all12 === null && r.all24 === null && r.prev12 === null && r.last === '' && r.city === '' && r.type === '' && r.newDrill === 0) && new Set(rows.map((r) => r.num)).size === rows.length,
    'companies: what only a full file has (months, trend, address, type, permit counts, last date) is null or empty in a listed row, never zero, and every row has its own key');
  check(CD.listedRows(null).length === 0 && CD.listedRows({}).length === 0 && CD.listedRows({ states: [{ id: 'ND', name: 'North Dakota', measure: 'spuds', operators: null }] }).length === 0
    && CD.listedRows(nat, []).length > rows.length && CD.listedRows(nat, []).some((r) => r.st === 'TX'), 'companies: no file, an empty one, or a state with no operator list gives no rows (never a crash), and skipping nothing includes Texas');
  check(CD.bandOf(0) === '' && CD.bandOf(1) === 'B' && CD.bandOf(9) === 'B' && CD.bandOf(10) === 'A' && CD.bandOf(641) === 'A'
    && CD.whatOf('spuds') === 'wells spudded' && CD.whatOf('drilled') === 'wells drilled' && CD.whatOf('permits') === 'new-drill permits' && CD.whatOf('nope') === 'new-drill permits' && CD.isPermit('permits') && !CD.isPermit('spuds') && !CD.isPermit('drilled'),
    'companies: bands (10 or more is A, 1 to 9 is B) and what each measure counts, in words');
  // the full lists of the state files (operatorsAll), once a producer has been run since 2026-11-01
  const natFiles = {}; for (const q of others) { try { natFiles[q.id] = read('nat/' + q.id); } catch (e) { /* no file */ } }
  const deep = {}; for (const q of others) { const l = CD.deepList(natFiles[q.id], q.id); if (l) deep[q.id] = l; }
  const deepRows = CD.listedRows(nat, CD.FULL, deep);
  const deepWant = others.reduce((t, q) => t + (deep[q.id] ? deep[q.id].length : q.operators.length), 0);
  check(Object.keys(deep).length >= 20 && deepRows.length === deepWant && deepRows.length > rows.length && deepRows.length >= 500, 'companies: with the state files\' full lists the table has more rows than the National report\'s 15 each (' + deepRows.length + ' against ' + rows.length + ', ' + Object.keys(deep).length + ' states with a full list)');
  check(others.filter((q) => deep[q.id]).every((q) => same(deep[q.id].slice(0, CD.TOP), q.operators) && deep[q.id].length >= q.operators.length && deep[q.id].every((r, i, a) => i === 0 || a[i - 1][1] >= r[1])), 'companies: every full list begins with the 15 the National report names, and is ranked');
  check(others.filter((q) => deep[q.id] && q.namedShare != null).every((q) => Math.abs(deep[q.id].reduce((t, r) => t + r[1], 0) / q.p12 - q.namedShare) < 0.0011), 'companies: the operators of a full list hold exactly the state\'s named share of its year (the lists leave out only people and unnamed operators)');
  check(deepRows.filter((r) => r.st === 'KS').length > 50 && deepRows.filter((r) => r.st === 'KS').every((r) => r.complete === 1 && r.listed === 1 && r.measure === 'permits') && new Set(deepRows.map((r) => r.num)).size === deepRows.length, 'companies: Kansas, which the 15 cut short, has every operator now, each a complete row with its own key');
  check(rows.filter((r) => r.complete === 1).every((r) => nat.states.find((q) => q.id === r.st).operators.length < CD.TOP) && rows.filter((r) => r.complete === 0).every((r) => nat.states.find((q) => q.id === r.st).operators.length === CD.TOP),
    'companies: with no full list, a state that names fewer than 15 operators is complete (the cut never bit) and one with 15 is not known to be');
  const cd = CD.coverage(deepRows.concat(CD.FULL.map((id) => ({ st: id }))));
  check(cd.top15 === 0 && cd.deep === cd.listed && cd.full === 3 && CD.coverage(rows).top15 > 0 && CD.coverage(rows).deep === CD.coverage(rows).listed - CD.coverage(rows).top15, 'companies: coverage says how many states have every operator and how many only the 15 busiest: ' + JSON.stringify(CD.coverage(rows)) + ' then ' + JSON.stringify(cd));
  const okFile = { state: 'ND', operatorsAll: [['A LLC', 5], ['B LLC', 1]] };
  check(CD.deepList(okFile, 'ND') !== null && CD.deepList(okFile, 'KS') === null && CD.deepList(null, 'ND') === null && CD.deepList({ state: 'ND' }, 'ND') === null && CD.deepList({ state: 'ND', operatorsAll: [] }, 'ND') === null
    && CD.deepList({ state: 'ND', operatorsAll: [['A LLC', 0]] }, 'ND') === null && CD.deepList({ state: 'ND', operatorsAll: [['A LLC', 1.5]] }, 'ND') === null && CD.deepList({ state: 'ND', operatorsAll: [['', 3]] }, 'ND') === null
    && CD.deepList({ state: 'ND', operatorsAll: [['A LLC']] }, 'ND') === null && CD.deepList({ state: 'ND', operatorsAll: 'A LLC' }, 'ND') === null, 'companies: a state file\'s full list is used only when it is for that state and every row is a name and a whole count above zero (a damaged list falls back to the 15)');
  // the State filter
  const full = CD.FULL.map((id) => ({ st: id, stName: byState.get(id).name }));
  const choices = CD.stateChoices(rows.concat(full), nat);
  check(choices.length === new Set(rows.map((r) => r.st)).size + 4 && choices.every((c, i) => i === 0 || choices[i - 1][1].localeCompare(c[1]) <= 0) && choices.some((c) => c[0] === 'ND' && c[1] === 'North Dakota') && choices.some((c) => c[0] === 'FO' && c[1] === 'Federal offshore')
    && !choices.some((c) => ['AZ', 'FL', 'NV', 'OR', 'SD', 'BL'].includes(c[0])), 'companies: the State filter lists each state that has rows once, by name, and none that names no operator (Arizona, Florida, Nevada, Oregon, South Dakota)');
  const without = CD.withoutOperators(nat);
  check(without.includes('Arizona') && without.includes('Florida') && without.includes('Nevada') && without.includes('Oregon') && without.includes('South Dakota') && !without.includes('Texas') && !without.includes('North Dakota')
    && !without.some((n) => /federal|BLM|onshore/i.test(n)) && without.every((n, i) => i === 0 || without[i - 1].localeCompare(n) <= 0) && without.length === nat.states.filter((q) => q.id !== 'BL' && !q.operators.length).length, 'companies: the states that name no operator are named, by name, and the BLM (federal land, not a state) is not one of them: ' + without.join(', '));
  const cov = CD.coverage(rows.concat(full));
  check(cov.offshore === true && cov.states === new Set(rows.map((r) => r.st)).size + 3 && cov.listed === new Set(rows.map((r) => r.st)).size && cov.full === 3 && CD.coverage(rows).offshore === false && CD.coverage([]).states === 0, 'companies: the page counts the states it covers (the offshore apart: it is not a state), how many list only their busiest and how many are full: ' + JSON.stringify(cov));
  const src = CD.sourceOf(nat, 'OK'); const nd = CD.sourceOf(nat, 'ND');
  check(src.what === 'new-drill permits' && /Oklahoma Corporation Commission/.test(src.agency) && /^\d{4}-\d\d-\d\d$/.test(src.asOf) && nd.what === 'wells spudded' && nd.listed === 15 && CD.sourceOf(nat, 'XX') === null && CD.sourceOf(null, 'OK') === null, 'companies: a state\'s source line has its agency, what it counts and how far it runs');
  // the address
  const P = (q) => new URLSearchParams(q);
  check(CD.kindOf(P('')) === 'operators' && CD.kindOf(P('q=pioneer&band=all&s=ND')) === 'operators' && CD.kindOf(P('kind=directory')) === 'directory' && CD.kindOf(P('kind=operators&county=001')) === 'operators' && CD.kindOf(P('kind=nonsense')) === 'operators'
    && ['county=001', 'seg=Drilling', 'fit=likely', 'isNew=1', 'match=1', 'tx=1'].every((q) => CD.kindOf(P(q)) === 'directory'), 'companies: an address names the list (kind=), and an older one with a filter only the Texas directory has (county, segment, fit, new entity, RRC match, Texas addresses) opens the directory');
  check(CD.fromOperators(P('st=ok&band=all')).toString() === 'band=all&s=OK' && CD.fromOperators(P('st=nm')).toString() === 's=NM' && CD.fromOperators(P('st=tx,ok')).toString() === '' && CD.fromOperators(P('st=tx,ok&q=x')).toString() === 'q=x'
    && CD.fromOperators(P('st=ok&s=ND')).toString() === 's=ND' && CD.fromOperators(P('q=pioneer&band=ab')).toString() === 'q=pioneer&band=ab' && CD.fromOperators(P('st=fo')).toString() === 's=FO',
    'companies: an old #operators address becomes the page\'s own (st=ok is s=OK, a list of states is all of them, the rest of the query is kept)');
  check(CD.withTexasFilters(P('top=1')).toString() === 'top=1&s=TX' && CD.withTexasFilters(P('newP5=1&band=all')).toString() === 'newP5=1&band=all&s=TX' && CD.withTexasFilters(P('op=1&s=OK')).toString() === 'op=1&s=OK' && CD.withTexasFilters(P('newDrill=1')).toString() === 'newDrill=1'
    && CD.withTexasFilters(P('top=0')).toString() === 'top=0' && CD.withTexasFilters(P('q=x')).toString() === 'q=x' && same(CD.TEXAS_ONLY, ['op', 'newP5', 'top']), 'companies: a link that names a filter only Texas can answer (top producers, a new P-5, oil or gas operators) and no state means Texas; one that names a state, or a filter every state has, is left as it is');
}

console.log('\n' + (fails ? 'FAILED ' + fails : 'all passed'));
process.exit(fails ? 1 : 0);
