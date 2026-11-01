// The matrix view's data code: pure functions over permit-fields.json (d11_fields_build.py), so Node can test them. Nothing here touches the page.
// A cell is [status, evidence, note]. The statuses run from most to least available: data (a field in a downloadable file), query (a one-well-at-a-time
// lookup), form (asked for on the application, published nowhere), none (the permit does not capture it), unknown (not verified: said so, never guessed).
// A registry (FracFocus) answers the same questions about what a disclosure captures. It is a column of the matrix, shown first, but it is not an agency: the counts of
// agencies (`metricScore`, `headline`, `byStatus`) are over `doc.order` only, and `doc.registries` names the others.

export const CODES = [
  { id: 'data', label: 'Published as data', def: 'A field in a downloadable file or API.' },
  { id: 'query', label: 'In a lookup only', def: 'On the agency’s record page, one well at a time, not in a download.' },
  { id: 'form', label: 'On the form only', def: 'Asked for on the application or required by rule, but not published by the agency.' },
  { id: 'none', label: 'Not captured', def: 'The permit does not ask for it.' },
  { id: 'unknown', label: 'Not verified', def: 'Could not be checked from the form or a real file.' },
];
export const EVIDENCE = {
  file: 'seen in a real data file',
  doc: 'listed in the agency’s data documentation',
  form: 'read on the permit form',
  web: 'seen on an agency web page',
  none: 'not verified',
};
export const GRADES = {
  A: 'Bulk data with approval dates: monthly counts can be built',
  B: 'Bulk data, but only spud, completion or filing dates',
  C: 'Query forms, reports or totals only',
  D: 'Nothing public, blocked or paid',
};
export const REACH = {
  ok: 'open to anyone',
  'blocked-403': 'refused automated requests (403)',
  'blocked-proxy': 'could not be reached when researched (blocked or behind a login)',
  timeout: 'timed out',
  'not-tested': 'not tested',
};
export const GRAIN = { aggregate: 'totals only', well: 'one row a well', permit: 'one row a permit', disclosure: 'one row a disclosure', treatment: 'one row a treatment' };
export const FIELD_GROUPS = { well: 'The well and who filed', where: 'Where', job: 'The fracturing job', water: 'Water', chem: 'Chemicals' };
export const SHORT = { FO: 'Gulf', BL: 'BLM' };
export const shortCode = (id) => SHORT[id] || id;

export const cellOf = (doc, sid, key) => {
  const c = doc.states[sid] && doc.states[sid].cells[key];
  return c ? { s: c[0], e: c[1], n: c[2] } : null;
};

const zero = () => ({ data: 0, query: 0, form: 0, none: 0, unknown: 0 });
// what one state captures: counts of each status over every metric, and how many it asks for at all (data, query or form)
export function stateScore(doc, sid) {
  const t = zero();
  Object.values(doc.states[sid].cells).forEach((c) => { t[c[0]]++; });
  return { ...t, asked: t.data + t.query + t.form, total: doc.metrics.length };
}
// how many agencies give one metric each status
export function metricScore(doc, key) {
  const t = zero();
  doc.order.forEach((sid) => { t[doc.states[sid].cells[key][0]]++; });
  return { ...t, asked: t.data + t.query + t.form, total: doc.order.length };
}
// the registries of a file (FracFocus), those a file really holds
export const registries = (doc) => (doc.registries || []).filter((id) => doc.states[id]);
// the agencies' columns, most published first (data, then lookup, then form; ties by name) or A to Z
export function agencyColumns(doc, by = 'coverage') {
  const ids = doc.order.slice();
  const name = (id) => doc.states[id].name;
  if (by === 'name') return ids.sort((a, b) => name(a).localeCompare(name(b)));
  const sc = new Map(ids.map((id) => [id, stateScore(doc, id)]));
  return ids.sort((a, b) => (sc.get(b).data - sc.get(a).data) || (sc.get(b).query - sc.get(a).query) || (sc.get(b).form - sc.get(a).form) || name(a).localeCompare(name(b)));
}
// every column of the matrix: the registry first, whatever the order, then the agencies
export const columns = (doc, by = 'coverage') => [...registries(doc), ...agencyColumns(doc, by)];
export const metricsIn = (doc, group) => doc.metrics.filter((m) => !group || group === 'all' || m.group === group);
// the facts the top of the page states
export function headline(doc) {
  const ids = doc.order;
  const scores = ids.map((id) => [id, stateScore(doc, id)]).sort((a, b) => b[1].data - a[1].data || a[0].localeCompare(b[0]));
  const best = scores[0];
  const mets = doc.metrics.map((m) => [m, metricScore(doc, m.key)]).sort((a, b) => b[1].data - a[1].data || a[0].label.localeCompare(b[0].label));
  const cells = ids.length * doc.metrics.length;
  const unknown = ids.reduce((n, id) => n + stateScore(doc, id).unknown, 0);
  return { agencies: ids.length, metrics: doc.metrics.length, best: best && best[1].data > 0 ? { id: best[0], n: best[1].data } : null, topMetric: mets[0] && mets[0][1].data > 0 ? { m: mets[0][0], n: mets[0][1].data, tied: mets.filter((x) => x[1].data === mets[0][1].data).map((x) => x[0]) } : null, unknownShare: cells ? unknown / cells : 0 };
}
// the states that give a metric each status, for the metric panel
export function byStatus(doc, key) {
  const out = Object.fromEntries(CODES.map((c) => [c.id, []]));
  agencyColumns(doc, 'name').forEach((id) => { out[doc.states[id].cells[key][0]].push(id); });
  return out;
}
export const percent = (n, d) => (d ? Math.round((n / d) * 100) : 0);

// A registry's list of fields in groups, each with the permit metric it matches and how many agencies publish that metric as data (null when it matches none).
export function registryGroups(doc, rid) {
  const r = doc.states[rid];
  const rows = (r && r.fields) || [];
  return Object.keys(FIELD_GROUPS).map((id) => ({
    id, label: FIELD_GROUPS[id],
    fields: rows.filter((f) => f.group === id).map((f) => {
      const m = f.metric ? doc.metrics.find((x) => x.key === f.metric) : null;
      return { ...f, matches: m ? { key: m.key, label: m.label, ...metricScore(doc, m.key) } : null };
    }),
  })).filter((g) => g.fields.length);
}
// "Few" agencies: at most this share of them publish a metric as data.
export const FEW = 0.2;
// What a registry captures that few agencies publish as data: its metrics answered `data` that at most `few` of the agencies publish as data, fewest agencies first (ties by label).
export function registryAdds(doc, rid, few = FEW) {
  const total = doc.order.length;
  return doc.metrics.filter((m) => { const c = cellOf(doc, rid, m.key); return c && c.s === 'data'; })
    .map((m) => ({ m, n: metricScore(doc, m.key).data, total }))
    .filter((x) => x.n <= few * total)
    .sort((a, b) => a.n - b.n || a.m.label.localeCompare(b.m.label));
}
