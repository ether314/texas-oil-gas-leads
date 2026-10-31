// The parts of the Daily report that only the Oklahoma Corporation Commission's files have: the wells that changed operator and the
// state's well inventory. daily.js puts them into the combined report. Operators are named only when the file says they are
// corporations, LLCs or partnerships; an unnamed one shows its Commission number.
import { el } from './util.js';
import { stack, rankList, fmtMd, fmtDow } from './daily-viz.js';
import { num, card, head, tiles, pctOf, signed } from './daily-kit.js';

export const OK_TITLES = { itd: 'Intent to drill', completions: 'Well completions', transfers: 'Well transfers', wells: 'Well inventory' };
export const OK_ICONS = { itd: 'pin', completions: 'drop', transfers: 'building', wells: 'rig' };
export const OK_WHAT = {
  itd: 'Intents to drill the Commission approved: the 7 complete days before the day the file is made, which is about 7:40 PM Central (ITD-wells-formations-daily.xlsx).',
  completions: 'Completion filings (Form 1002A), one row per casing string or test in the file, folded here to one filing per well and day (completions-wells-formations-daily.xlsx).',
  transfers: 'Wells that changed operator, about a month of them (well-transfers-daily.xlsx).',
  wells: 'Every well in the state, from the nightly well file (about 457,000 records). Counted here, never listed.',
};

const countyRows = (rows) => (rows || []).map(([f, name, n]) => ({ label: name, value: n }));
const opItems = (list) => (list || []).map(([op, name, n]) => ({ label: name || 'Operator #' + op, value: n }));

export function transfersSection(rep) {
  const t = rep.transfers;
  if (!t) return card('dr-sec', head('building', 'Ownership · Oklahoma', 'Well transfers'), el('p', { class: 'empty', text: 'No well changed operator on the day this report looks at, or the day is older than the month of transfers the Commission\'s file holds.' }));
  return card('dr-sec', head('building', 'Ownership · Oklahoma', 'Wells that changed operator ' + fmtDow(t.day), 'From the Commission\'s well-transfer file, which holds about a month. A few days carry one large sale, so the count swings more than permits do.'),
    tiles([{ label: 'Wells', value: num(t.wells), note: 'changed operator' }, { label: 'Buyers', value: num(t.buyerCount), note: 'operators taking wells' }, { label: 'Sellers', value: num(t.sellerCount), note: 'operators giving them up' }]),
    el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Buyers' }), rankList(opItems(t.buyers), { color: 'var(--s1)' })),
      el('div', {}, el('h3', { text: 'Sellers' }), rankList(opItems(t.sellers), { color: 'var(--s1)' }))),
    el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Counties' }), rankList(countyRows(t.counties), { color: 'var(--s1)' })),
      el('div', {}, el('h3', { text: 'Kinds of well' }), stack(t.types.map(([k, n]) => ({ label: k, value: n }))))));
}

// the inventory section's words for each state that has one: where the counts come from and what is said when a rebuilt day has none
const WELLS_TEXT = {
  OK: { name: 'Oklahoma', unread: 'The well inventory could not be read for this report.', rebuilt: 'The Commission publishes only the current well inventory, so a report rebuilt for an earlier day has none. Days captured live do.',
    source: 'The Commission\'s nightly well file' },
  NM: { name: 'New Mexico', unread: 'The well inventory could not be read for this report.', rebuilt: 'The Division\'s well layer holds only the current inventory, so a report rebuilt for an earlier day has none. Days captured live do.',
    source: 'The Division\'s well layer' },
};

export function wellsSection(rep) {
  const w = rep.wells; const T = WELLS_TEXT[rep.state] || WELLS_TEXT.OK;
  if (!w) {
    return card('dr-sec', head('rig', 'Inventory · ' + T.name, 'Wells in the state'), el('p', { class: 'empty', text: rep.kind === 'live' ? T.unread : T.rebuilt }));
  }
  const ch = w.change; const since = (k) => (ch ? signed(ch[k]) + ' since ' + fmtMd(ch.since) : '');
  return card('dr-sec', head('rig', 'Inventory · ' + T.name, 'Every well in the state', T.source + ', as of ' + fmtDow(w.asOf) + '. The wells are counted, never listed: no name, number or location of any well is kept here.'),
    tiles([{ label: 'Active wells', value: num(w.active), note: since('active') || pctOf(w.active, w.total) + ' of the records' }, { label: 'Plugged', value: num(w.plugged), note: since('plugged') || pctOf(w.plugged, w.total) + ' of the records' },
      { label: 'Records in all', value: num(w.total), note: ch ? signed(ch.total) + ' since ' + fmtMd(ch.since) : 'every status' }, { label: 'Counties with active wells', value: num(w.countyCount), note: w.counties[0] ? w.counties[0][1] + ' led' : '' },
      { label: 'Operators on record', value: num(w.operatorCount), note: 'with an active well' }]),
    el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Status of every record' }), stack(w.status.map(([k, n]) => ({ label: k, value: n })))),
      el('div', {}, el('h3', { text: 'Kinds of active well' }), stack(w.activeTypes.map(([k, n]) => ({ label: k, value: n }))))),
    el('div', { class: 'dr-cols' },
      el('div', {}, el('h3', { text: 'Active wells by county' }), rankList(countyRows(w.counties.slice(0, 12)), { color: 'var(--s7)' })),
      el('div', {}, el('h3', { text: 'Operators with the most active wells' }), rankList(w.operators.map(([name, n]) => ({ label: name, value: n })), { color: 'var(--s7)' }),
        el('p', { class: 'fine', text: 'Only corporations, LLCs and partnerships are named. ' + num(w.unnamed) + ' active wells belong to other operators and ' + num(w.unassigned) + ' have none assigned.' }))));
}
