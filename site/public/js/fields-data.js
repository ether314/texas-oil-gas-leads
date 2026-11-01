// The matrix view's data code: pure functions over permit-fields.json (d11_fields_build.py), so Node can test them. Nothing here touches the page.
// A cell is [status, evidence, note]. The statuses run from most to least available: data (a field in a downloadable file), query (a one-well-at-a-time
// lookup), form (asked for on the application, published nowhere), none (the permit does not capture it), unknown (not verified: said so, never guessed).

export const CODES = [
  { id: 'data', label: 'Published as data', def: 'A field in a downloadable file or API.' },
  { id: 'query', label: 'In a lookup only', def: 'On the agency’s record page, one well at a time, not in a download.' },
  { id: 'form', label: 'On the form only', def: 'Asked for on the application, but published nowhere.' },
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
  ok: 'reachable from here',
  'blocked-403': 'refused this machine (HTTP 403)',
  'blocked-proxy': 'not reachable from here (blocked or behind a login)',
  timeout: 'timed out',
  'not-tested': 'not tested',
};
export const SHORT = { FO: 'Gulf', BL: 'BLM' };
export const shortCode = (id) => SHORT[id] || id;

export const cellOf = (doc, sid, key) => {
  const c = doc.states[sid] && doc.states[sid].cells[key];
  return c ? { s: c[0], e: c[1], n: c[2] } : null;
};

const zero = () => ({ data: 0, query: 0, form: 0, none: 0, unknown: 0 });
// what one state captures: counts of each status over the 48 metrics, and how many it asks for at all (data, query or form)
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
// the columns, most published first (data, then lookup, then form; ties by name) or A to Z
export function columns(doc, by = 'coverage') {
  const ids = doc.order.slice();
  const name = (id) => doc.states[id].name;
  if (by === 'name') return ids.sort((a, b) => name(a).localeCompare(name(b)));
  const sc = new Map(ids.map((id) => [id, stateScore(doc, id)]));
  return ids.sort((a, b) => (sc.get(b).data - sc.get(a).data) || (sc.get(b).query - sc.get(a).query) || (sc.get(b).form - sc.get(a).form) || name(a).localeCompare(name(b)));
}
export const metricsIn = (doc, group) => doc.metrics.filter((m) => !group || group === 'all' || m.group === group);
// the facts the top of the page states
export function headline(doc) {
  const ids = doc.order;
  const scores = ids.map((id) => [id, stateScore(doc, id)]).sort((a, b) => b[1].data - a[1].data || a[0].localeCompare(b[0]));
  const best = scores[0];
  const mets = doc.metrics.map((m) => [m, metricScore(doc, m.key)]).sort((a, b) => b[1].data - a[1].data || a[0].label.localeCompare(b[0].label));
  const cells = ids.length * doc.metrics.length;
  const unknown = ids.reduce((n, id) => n + stateScore(doc, id).unknown, 0);
  return { agencies: ids.length, metrics: doc.metrics.length, best: best && best[1].data > 0 ? { id: best[0], n: best[1].data } : null, topMetric: mets[0] && mets[0][1].data > 0 ? { m: mets[0][0], n: mets[0][1].data } : null, unknownShare: cells ? unknown / cells : 0 };
}
// the states that give a metric each status, for the metric panel
export function byStatus(doc, key) {
  const out = Object.fromEntries(CODES.map((c) => [c.id, []]));
  columns(doc, 'name').forEach((id) => { out[doc.states[id].cells[key][0]].push(id); });
  return out;
}
export const percent = (n, d) => (d ? Math.round((n / d) * 100) : 0);
