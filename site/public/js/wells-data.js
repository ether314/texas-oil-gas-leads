// The well finder's data code: pure functions over data/wells/index.json and one county's file, so Node can test them. Nothing here touches the page.
// d12_wells.py ties every scanned document of the Railroad Commission's three image packs to the well (API number) it is about and publishes it as a file of a GitHub
// release; a county's file lists each well and its documents: stage (p permit, d drilling, c completion), kind, pages, bytes, file name, release.
import { sizeText, bytesText, STAGES as LIFE, KIND_INFO } from './images-data.js';

export { sizeText, bytesText, KIND_INFO };

// stage letter -> what the image view calls it, in the order of a well's life
export const STAGE_ORDER = ['p', 'd', 'c'];
export const STAGE = {
  p: { id: 'permit', label: 'Permit', color: 'var(--s1)' },
  d: { id: 'drilling', label: 'Drilling', color: 'var(--s3)' },
  c: { id: 'completion', label: 'Completion', color: 'var(--s7)' },
};
export const blurb = (letter) => (LIFE.find((s) => s.id === STAGE[letter].id) || {}).blurb || '';

const REPO = /^[\w.-]+\/[\w.-]+$/;
const TAG = /^wells-\d{4}-\d\d-\d\d-(w1|ds|ci)-\d\d$/;
const STEM = /^\d{8}_[pdc]\d{1,4}$/;

// 28337830 -> "42-283-37830" (Texas is state 42; the county code, then the well's own number)
export const apiText = (api8) => '42-' + api8.slice(0, 3) + '-' + api8.slice(3);

// What someone types for an API number, as digits: "42-283-37830", "4228337830", "283-37830", "28337830", "283". Returns
// {api8, county, digits}: api8 only when the whole well is given (8 digits, or 10 with the state's 42, or 12/14 with the sidetrack and completion
// suffix the Commission adds, which the first 10 already name); county only when at least the three digits of the county are there; null for anything else.
export function parseApi(text) {
  const raw = String(text || '').trim();
  let d = raw.replace(/\D/g, '');
  if ((d.length > 8 && d.startsWith('42')) || /^42\D/.test(raw)) d = d.slice(2); // the state's 42, whole or with a separator after it
  if (d.length > 8) d = d.slice(0, 8);
  if (d.length < 3) return null;
  return { api8: d.length === 8 ? d : null, county: d.slice(0, 3), digits: d };
}

// the address of a document or its page-one picture on GitHub, or null when anything in the data is not what the producer writes (a bad file must not build a link)
export function assetUrl(repo, tag, stem, ext) {
  if (!REPO.test(repo || '') || !TAG.test(tag || '') || !STEM.test(stem || '') || !/^(pdf|tif|png|jpg)$/.test(ext || '')) return null;
  return 'https://github.com/' + repo + '/releases/download/' + tag + '/' + stem + '.' + ext;
}

// a well's documents with their addresses: file (the document as filed) and preview (page one as a picture, or null)
export function docsOf(repo, shard, well) {
  return well.docs.map((x) => {
    const tag = shard.tags[x.t];
    return { ...x, tag, kindText: x.k, file: assetUrl(repo, tag, x.f, x.x), preview: x.v ? assetUrl(repo, tag, x.f, 'jpg') : null };
  });
}

// the documents of a well by stage, newest first, in the order of a well's life; a stage with none is an empty list (not "none exist": the archive holds only recent packs)
export function byStage(docs) {
  return STAGE_ORDER.map((s) => ({ stage: s, ...STAGE[s], docs: docs.filter((x) => x.s === s).sort((a, b) => (a.d < b.d ? 1 : a.d > b.d ? -1 : a.f < b.f ? -1 : 1)) }));
}

export function summary(well) {
  const n = { p: 0, d: 0, c: 0 };
  let bytes = 0; let newest = '';
  for (const x of well.docs) { n[x.s] += 1; bytes += x.b || 0; if (x.d > newest) newest = x.d; }
  return { docs: well.docs.length, n, bytes, newest };
}

// "3 pages · 24 KB" for a document; the page count is unknown for a file poppler could not read, and then it is left out (never 0)
const smallSize = (b) => (b < 1 << 20 ? Math.max(1, Math.round(b / 1024)) + ' KB' : sizeText(b / (1 << 20))); // a form of 30 KB is not "0.0 MB"; the same 1,024 as the rest of the page
export const docMeta = (x) => [x.pg ? x.pg + (x.pg === 1 ? ' page' : ' pages') : null, smallSize(x.b)].filter(Boolean).join(' · ');

// the wells of a county that match what was typed: an API number or its start, a field, an operator's name or number, or a district (all lower-cased substrings)
export function matchWells(wells, text) {
  const q = String(text || '').trim().toLowerCase();
  if (!q) return wells.slice();
  const digits = q.replace(/\D/g, '');
  return wells.filter((w) => (digits.length >= 3 && (w.a.startsWith(digits) || w.a.slice(3).startsWith(digits)))
    || (w.fl || '').toLowerCase().includes(q) || (w.on || '').toLowerCase().includes(q) || (w.o || '') === q || ('district ' + (w.di || '')).toLowerCase() === q);
}

// the wells in the order a person looks for them: the ones with the most documents first, then by API number
export const rank = (wells) => wells.slice().sort((a, b) => b.docs.length - a.docs.length || (a.a < b.a ? -1 : 1));

// counties for the picker, most wells first; the index carries [fips, name, wells, documents]
export const countyChoices = (index) => (index.counties || []).slice().sort((a, b) => b[2] - a[2] || (a[1] < b[1] ? -1 : 1)).map(([fips, name, wells, docs]) => ({ fips, name, wells, docs }));

// what the packs held that could not be tied to a well, for a day and a pack ('w1', 'ds', 'ci'): honest counts from the index, or null when that pack is not in the archive
export function tieLine(index, day, pack) {
  const u = (index.units || []).find((x) => x.d === day && x.p === pack);
  return u ? { docs: u.docs, tied: u.tied, untied: u.untied, rejected: u.rejected, wells: u.wells } : null;
}

// where the Commission's own look-ups are (they take the API number in a form; none has an address that opens a single document)
export const RRC_LOOKUPS = [
  { label: 'Drilling permit (W-1) query', href: 'https://webapps2.rrc.texas.gov/EWA/drillingPermitsQueryAction.do', takes: 'API number or permit number' },
  { label: 'Oil and gas completions query', href: 'https://webapps.rrc.texas.gov/CMPL/publicHomeAction.do', takes: 'API number' },
  { label: 'Well records and logs (imaged records)', href: 'https://rrcsearch3.neubus.com/esd3-rrc/index.php?_module_=esd&_action_=keysearch&profile=17', takes: 'API number' },
];

// the totals the top of the page shows, from the index; null when nothing is published yet
export function headline(index) {
  const t = index && index.totals;
  if (!t || !t.docs) return null;
  const days = (index.units || []).map((u) => u.d);
  return { wells: t.wells, docs: t.docs, bytes: t.bytes, counties: (index.counties || []).length, newest: days.length ? days.reduce((m, d) => (d > m ? d : m)) : null, oldest: days.length ? days.reduce((m, d) => (d < m ? d : m)) : null };
}
