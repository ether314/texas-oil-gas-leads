// The Texas images view's data code: pure functions over the Daily archive's index and day files, so Node can test them. Nothing here touches the page.
// What the Railroad Commission publishes each business day as scanned filings is three packs: W-1 images (the approved permit letters and plats), directional surveys, and
// completion images (the forms and attachments filed when a well is completed). The index gives each pack's size for every day; a day captured live also has its documents counted by kind.

export const PACKS = [
  { id: 'w1images', key: 'w1', label: 'W-1 images', color: 'var(--s1)', stage: 'permit' },
  { id: 'dirsurveys', key: 'ds', label: 'Directional surveys', color: 'var(--s3)', stage: 'drilling' },
  { id: 'complimages', key: 'cm', label: 'Completion images', color: 'var(--s7)', stage: 'completion' },
];

export const STAGES = [
  { id: 'permit', label: 'Permit', pack: 'w1images', blurb: 'Before drilling: the Commission approves where and how a well may be drilled.' },
  { id: 'drilling', label: 'Drilling', pack: 'dirsurveys', blurb: 'While drilling: where the wellbore actually went, for a deviated or horizontal well.' },
  { id: 'completion', label: 'Completion', pack: 'complimages', blurb: 'After drilling: what the well produced when tested, and the paperwork behind it.' },
];

// what each kind of document is, in plain words (the kinds are told apart by file name, see d7_packs.py)
export const KIND_INFO = {
  'Approved W-1': 'The approved application to drill, deepen, recomplete or re-enter a well (Form W-1): the permit letter.',
  'Permit plat': 'The map that goes with the permit: the lease, the well’s surface location and its distances to the lease lines.',
  'Directional survey': 'The measured path of a wellbore that does not go straight down: how far it drifted, and where it ended.',
  'W-2 form': 'The oil well completion report (Form W-2): the potential test, the zones and the casing.',
  'G-1 form': 'The gas well completion report (Form G-1): the back-pressure test and the zones.',
  'L-1 form': 'The electric log status report (Form L-1): which logs were run.',
  'P-4 form': 'The certificate of compliance (Form P-4): who is allowed to take the oil or gas from the lease.',
  'Well log': 'A log of what the instruments read on the way down: rock, porosity, resistivity.',
  'Cementing report (W-15)': 'The cementing report (Form W-15): how the casing was cemented in.',
  'Acreage designation (P-16)': 'The acreage designation (Form P-16): the land assigned to the well.',
  'Inclination report (W-12)': 'The inclination report (Form W-12): how far the hole strayed from vertical.',
  Plat: 'A plat filed with the completion.',
  'Other form': 'A form made by the Commission’s system that is none of the above.',
  'Other attachment': 'Whatever else the operator attached to the completion.',
  Other: 'A document the name pattern does not place.',
};

const MB = 1 << 20; // the Commission's "MB" and the Daily archive's: the share lists sizes in units of 2^20 bytes and the index stores bytes / 2^20, so the chart and the day panel must divide by the same number
// one row a report day: the size of each pack in MB, null where no pack was listed that day (a weekend, or a pack that had not landed yet): never zero
export function daySeries(index) {
  return (index.days || []).map((d) => ({ d: d.d, live: d.k === 'live', w1images: d.w1 ?? null, dirsurveys: d.ds ?? null, complimages: d.cm ?? null }));
}
export const dayTotal = (r) => PACKS.reduce((t, p) => t + (r[p.id] || 0), 0);
export const havePacks = (r) => PACKS.some((p) => r[p.id] != null);
export const sizeText = (mb) => (mb == null ? '—' : mb >= 1024 ? (mb / 1024).toFixed(2) + ' GB' : mb >= 10 ? Math.round(mb) + ' MB' : mb.toFixed(1) + ' MB');
export const bytesText = (b) => sizeText(b / MB);

// the busiest day and the average of the days that had any pack
export function summary(rows) {
  const have = rows.filter(havePacks);
  const total = have.reduce((t, r) => t + dayTotal(r), 0);
  const peak = have.reduce((m, r) => (dayTotal(r) > dayTotal(m) ? r : m), have[0] || null);
  return { days: rows.length, withPacks: have.length, avgMB: have.length ? total / have.length : null, peak, totalMB: total };
}

// a day file's images, ready to show: for each pack its size, its districts (W-1 only), the documents counted by kind (live days only), its sheet
export function packsOf(day) {
  const im = (day && day.images) || {};
  return PACKS.map((p) => {
    const x = im[p.id];
    if (!x || typeof x !== 'object') return { ...p, present: false };
    const docs = x.docs && typeof x.docs === 'object' ? x.docs : null;
    return {
      ...p, present: true, packDay: x.day, bytes: x.bytes, empty: !!x.empty, modified: x.modified, districts: (x.districts || []).map(([d, b]) => ({ d, bytes: b })),
      n: docs ? docs.n : null, kinds: docs && docs.types ? docs.types.map(([k, n]) => ({ k, n })) : null, packets: docs ? docs.packets : null, sheet: x.sheet ? x.sheet.file : null,
    };
  });
}
// The files of a day are on one GitHub release, which the day file names ({ repo, tag, files, ... }); names come from a data file, so an address is made only from
// names that are plain file names. A readable preview of a document (<document>.jpg, page one) exists only when the release says so: `previews` is how many the
// release's listing confirmed (absent when none), and `noPreview` the documents that have none. The page links a preview only then.
export const releaseOk = (r) => !!r && typeof r.repo === 'string' && /^[\w.-]+\/[\w.-]+$/.test(r.repo) && typeof r.tag === 'string' && /^daily-\d{4}-\d\d-\d\d$/.test(r.tag);
export const fileUrl = (rel, name) => (releaseOk(rel) && typeof name === 'string' && /^[\w.-]+$/.test(name) ? 'https://github.com/' + rel.repo + '/releases/download/' + rel.tag + '/' + name : null);
export const hasPreview = (rel, name) => releaseOk(rel) && Number.isInteger(rel.previews) && rel.previews > 0 && !(Array.isArray(rel.noPreview) && rel.noPreview.includes(name));
export const previewUrl = (rel, name) => (hasPreview(rel, name) ? fileUrl(rel, name + '.jpg') : null);
// 'W1.pdf' is the approved W-1 permit, 'Plat_2.pdf' the second permit plat; type is the file's own (PDF, or TIF for a scan the Commission sent as one)
export function docLabel(suffix) {
  const m = /^(W1|Plat)(?:_(\d+))?\.(\w+)$/.exec(suffix);
  if (!m) return { label: 'Document', type: '' };
  return { label: (m[1] === 'W1' ? 'Approved W-1 permit' : 'Permit plat') + (m[2] ? ' ' + m[2] : ''), type: m[3].toUpperCase() };
}
const docOf = (rel, name, label) => ({ name, ...label, original: fileUrl(rel, name), preview: previewUrl(rel, name) });
// the permits of a day whose filings are published (the day's rows carry the suffixes of their files); each file with its label, its address and its preview's address (or null)
export function filedPermits(day) {
  const rows = (day && day.permits && day.permits.rows) || [];
  const rel = day && day.release;
  return rows.filter((r) => Array.isArray(r[10]) && r[10].length).map((r) => ({ permit: r[0], county: r[1], district: r[2], files: r[10], docs: r[10].map((s) => docOf(rel, r[0] + '_' + s, docLabel(s))) }));
}
// the directional surveys of a day whose files are published, each with the address of its file and of its preview (or null)
export function filedSurveys(day) {
  const rows = (day && day.surveys && day.surveys.rows) || [];
  const rel = day && day.release;
  return rows.filter((r) => /^\d+$/.test(String(r[8])) && fileUrl(rel, 'dir_survey_' + r[8] + '.pdf')).map((r) => ({ id: String(r[8]), county: r[1], doc: docOf(rel, 'dir_survey_' + r[8] + '.pdf', { label: 'Directional survey ' + r[8], type: 'PDF' }) }));
}
export const fileKind = (suffix) => (/^W1/i.test(suffix) ? 'W-1 letter' : /^Plat/i.test(suffix) ? 'plat' : /^dir|survey/i.test(suffix) ? 'survey' : 'file');

// the newest day, from the newest first, that was captured live and counted its documents: the index says which days were live
export const liveCandidates = (rows) => rows.filter((r) => r.live).map((r) => r.d).reverse();
// the lifecycle: the kinds of each stage with the counts of one day, in the order of that day's counts
export function lifecycle(packs) {
  return STAGES.map((s) => {
    const p = packs.find((x) => x.id === s.pack);
    return { ...s, present: !!(p && p.present), n: p ? p.n : null, kinds: p && p.kinds ? p.kinds : null, bytes: p ? p.bytes : null, packets: p ? p.packets : null };
  });
}
export const kindInfo = (k) => KIND_INFO[k] || '';
