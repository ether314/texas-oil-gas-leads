// How many oil permits the state agencies approved each day, so the Daily report can show them beside the frac wells (FracFocus) in its chart and summary, whatever share of them have a map location.
// Pure functions over files the site already publishes, so Node can test them; nothing here touches the page.
//
// What exists by day, and what does not (the repo's CLAUDE.md: say what is not known): only Texas, Oklahoma and New Mexico publish a list of permits each day, and this site has read them since
// 2026-08-01 (the nightly captures' permit series, `daily/permits-series.json` and `daily-nm/permits-series.json`; Oklahoma's is counted from its permit points file, which holds every Oklahoma permit
// with its approval day and agrees with the capture on every day they can be compared). Every other state's permits are counted by the month on the National page. So a day outside those captures, or a
// state that is not one of the three, has no count: the pages say "not available", never zero. These are new-drill permits (the measure the National page uses for the three), not the spuds New Mexico's
// and the offshore's Map files hold, and never added to the frac wells: a permit is the right to drill, and its well may be fractured weeks or months later, or never.

export const OIL_STATES = [{ id: 'TX', name: 'Texas' }, { id: 'OK', name: 'Oklahoma' }, { id: 'NM', name: 'New Mexico' }];
export const OIL_IDS = OIL_STATES.map((s) => s.id);
const DAY = 864e5;
const isoMs = (iso) => Date.parse(iso + 'T00:00:00Z');
const isoOf = (ms) => new Date(ms).toISOString().slice(0, 10);

// counts({ tx, nm, okPoints }): the new-drill permits approved each day, by state: { per: { TX: Map(iso -> n), OK, NM }, first, last }, where first and last are the days ALL three states have a count.
// tx and nm are the permit series files (days, newDrill); Oklahoma's is counted from its permit points file (t0, asOf, pts with the day in column 3), which has every permit and so an exact count with
// the zeros in it, until its asOf. A weekend with no permit is a zero the file shows, not a missing day.
export function counts({ tx, nm, okPoints }) {
  const per = { TX: new Map(), OK: new Map(), NM: new Map() };
  tx.days.forEach((d, i) => per.TX.set(d, tx.newDrill[i]));
  nm.days.forEach((d, i) => per.NM.set(d, nm.newDrill[i]));
  const t0 = isoMs(okPoints.t0); const span = Math.round((isoMs(okPoints.asOf) - t0) / DAY); const ok = new Array(span + 1).fill(0);
  for (const r of okPoints.pts) if (r[3] >= 0 && r[3] <= span) ok[r[3]]++;
  ok.forEach((n, d) => per.OK.set(isoOf(t0 + d * DAY), n));
  const firsts = OIL_IDS.map((id) => [...per[id].keys()].sort()[0]); const lasts = OIL_IDS.map((id) => [...per[id].keys()].sort().pop());
  return { per, first: firsts.reduce((a, b) => (a > b ? a : b)), last: lasts.reduce((a, b) => (a < b ? a : b)) };
}
// the permits approved on `iso`: [{ id, name, n }] for the three states, or null when the day is outside the days all three have (or one of them has no count that day)
export function permitsOn(c, iso) {
  if (!c || iso < c.first || iso > c.last) return null;
  const rows = OIL_STATES.map((s) => ({ id: s.id, name: s.name, n: c.per[s.id].get(iso) }));
  return rows.every((r) => Number.isInteger(r.n)) ? rows : null;
}
// the days of a window ([iso0, iso0 + n - 1]) as an array, for the chart's line: all three states added (id null) or one state's, and null for a day without a count (a state that is not one of the
// three has none)
export function valuesOver(c, iso0, n, id = null) {
  const out = []; const t0 = isoMs(iso0);
  for (let i = 0; i < n; i++) {
    const rows = permitsOn(c, isoOf(t0 + i * DAY));
    out.push(!rows ? null : id ? (rows.find((r) => r.id === id) || { n: null }).n : rows.reduce((t, r) => t + r.n, 0));
  }
  return out;
}
