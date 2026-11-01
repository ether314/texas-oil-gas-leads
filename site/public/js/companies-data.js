// The Companies page's data: the national list of operators. Pure functions (no DOM, no fetch), so they run under Node as well.
//
// Texas, Oklahoma, New Mexico and the federal offshore have a full operator file of their own (every operator with a recent permit or spud, with its
// months, depth and top county: the files the Map uses). Every other state is in the National report. Its state file (`nat/<ST>.json`) lists every operator it
// named in the last 12 months with the new wells each had (`operatorsAll`: [name, count], corporations, LLCs and partnerships only), once its producer has been
// run since 2026-11-01; `national.json` keeps only the 15 busiest (`states[].operators`), which a state whose file has no full list still shows here.
// `listedRows` makes table rows of those, with the cells that only a full file can fill left empty (never zero).

export const FULL = ['TX', 'OK', 'NM', 'FO'];
export const TOP = 15; // the operators the National report lists for a state: a list shorter than this is every operator the state named, whatever file it came from

// what a state's count is of, in the words of a table: the National report's four measures (a state counts one of them, and the counts are never added across measures)
const WHAT = { permits: 'new-drill permits', spuds: 'wells spudded', drilled: 'wells drilled', applications: 'permit applications' };
export const whatOf = (measure) => WHAT[measure] || WHAT.permits;
// a count of wells (spuds, drilled) is not a count of permits: a row says which it is
export const isPermit = (measure) => measure === 'permits';

// the Operators table's bands, from one number: A is 10 or more in the last 12 months, B is 1 to 9
export const bandOf = (n) => (n >= 10 ? 'A' : n >= 1 ? 'B' : '');

// A state file's full operator list (`operatorsAll`), or null when the file has none (written before 2026-11-01), is for another state, or any row is not [name, count]:
// a damaged list is not trusted, and the state shows the 15 the National report has
export function deepList(file, id) {
  if (!file || file.state !== id || !Array.isArray(file.operatorsAll) || !file.operatorsAll.length) return null;
  return file.operatorsAll.every((r) => Array.isArray(r) && r.length === 2 && typeof r[0] === 'string' && r[0] && Number.isInteger(r[1]) && r[1] > 0) ? file.operatorsAll : null;
}

// The listed operators of every state the National report names some for, except those that have a full file (the caller loads those): one row each, in the
// shape the Operators table uses. A state's own count (`new12`) is in its own measure (`measure`). `deep` is { ST: the full list } for the states that have one
// (deepList); a state with none lists the National report's operators, which are every operator it named when there are fewer than 15 (`complete`), and the 15 busiest when there are 15.
export function listedRows(doc, skip = FULL, deep = {}) {
  const out = [];
  if (!doc || !Array.isArray(doc.states)) return out;
  for (const s of doc.states) {
    if (skip.includes(s.id) || !Array.isArray(s.operators)) continue;
    const list = deep[s.id] || s.operators; const complete = deep[s.id] || list.length < TOP ? 1 : 0;
    for (const [name, n] of list) {
      out.push({
        st: s.id, stName: s.name, measure: s.measure, listed: 1, complete, band: bandOf(n), num: s.id + ':' + name, name, new12: n,
        type: '', city: '', state: '', zip: '', prev12: null, all12: null, all24: null, last: '', dist: '', roles: '', specialties: '', newDrill: 0, newP5: 0, m24: null,
      });
    }
  }
  return out;
}

// the states the table can be narrowed to: every one that has at least one row, by name ([id, name] pairs, A to Z); `rows` are all the table's rows
export function stateChoices(rows, doc) {
  const names = new Map(((doc && doc.states) || []).map((s) => [s.id, s.name]));
  const seen = new Map();
  for (const r of rows) if (!seen.has(r.st)) seen.set(r.st, names.get(r.st) || r.stName || r.st);
  return [...seen].sort((a, b) => a[1].localeCompare(b[1]));
}

// the National report's states that name no operator (a state that publishes none, or has had no new well in 24 months), by name: the page says so instead of listing nothing.
// The federal land of the BLM is not a state, and has no operators to name.
export function withoutOperators(doc) {
  return ((doc && doc.states) || []).filter((s) => s.id !== 'BL' && (!Array.isArray(s.operators) || !s.operators.length)).map((s) => s.name).sort((a, b) => a.localeCompare(b));
}

// one state's source, for the line under the filters: its agency, what its count is of, and how far its data runs ({ agency, what, asOf } or null)
export function sourceOf(doc, id) {
  const s = ((doc && doc.states) || []).find((q) => q.id === id);
  return s ? { name: s.name, agency: s.agency, what: whatOf(s.measure), measure: s.measure, asOf: s.asOf || null, listed: Array.isArray(s.operators) ? s.operators.length : 0 } : null;
}

// how many states the table covers (the federal offshore is counted apart: it is not a state), how many have a full file of their own (`full`: Texas, Oklahoma, New Mexico and the
// offshore), how many are listed from the National report (`listed`) and, of those, how many have every operator of the year (`deep`) and how many only the 15 busiest (`top15`)
export function coverage(rows) {
  const all = new Set(rows.map((r) => r.st));
  const listed = new Set(rows.filter((r) => r.listed).map((r) => r.st));
  const deep = new Set(rows.filter((r) => r.listed && r.complete).map((r) => r.st));
  const offshore = all.has('FO');
  return { states: all.size - (offshore ? 1 : 0), offshore, listed: listed.size, deep: deep.size, top15: listed.size - deep.size, full: all.size - (offshore ? 1 : 0) - listed.size };
}

// Which lens an address names. `kind=directory` (or `operators`) says so; an older link has no kind: the filters only the Texas directory has (a county, a segment,
// a fit, a new entity, an RRC match, Texas addresses only) mean the directory, and anything else the operators.
const DIRECTORY_ONLY = ['county', 'seg', 'fit', 'isNew', 'match', 'tx'];
export function kindOf(params) {
  const k = params.get('kind');
  if (k === 'directory' || k === 'operators') return k;
  return DIRECTORY_ONLY.some((id) => params.has(id)) ? 'directory' : 'operators';
}

// An old address translated to the page's: #operators?st=ok&q=x opens #companies?s=OK&q=x (the old states bar named one state or a list; one state narrows the table,
// anything else is all of them), and #operators?band=all keeps its band. Returns the new address's query as URLSearchParams.
export function fromOperators(params) {
  const out = new URLSearchParams(params);
  const st = (out.get('st') || '').split(/[,\s]+/).filter(Boolean);
  out.delete('st');
  if (st.length === 1 && !out.has('s')) out.set('s', st[0].toUpperCase());
  return out;
}

// The filters only Texas's registrations can answer (oil or gas operators, a new P-5, the top producers by oil): they are shown when Texas is the state chosen, so a link that
// names one without a state means Texas (an older #operators?top=1 listed all states, but only Texas has production, so the answer is the same)
export const TEXAS_ONLY = ['op', 'newP5', 'top'];
export function withTexasFilters(params) {
  const out = new URLSearchParams(params);
  if (!out.has('s') && TEXAS_ONLY.some((id) => out.get(id) === '1')) out.set('s', 'TX');
  return out;
}
