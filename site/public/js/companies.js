// The Companies page: one tab for who is drilling and who serves them. A switch between two tables, each loaded the first time it is shown:
//   Operators  every operator the state agencies name, nationally (Texas, Oklahoma, New Mexico and the federal offshore with every operator, the other states with the
//              15 busiest the National report names), narrowed by a State filter inside the table
//   Directory  the Texas Comptroller's oil and gas companies, with RRC activity where a name matched (Texas only: no other state publishes a list like it)
// The address is #companies (the operators) or #companies?kind=directory; an older #operators or #companies link is translated (companies-data.js).
import { $, el, fmtDate } from './util.js';
import { segmented } from './ui.js';
import { createTables } from './tables.js';
import { kindOf, fromOperators, withTexasFilters } from './companies-data.js';
import { STATES, listAnd, spudCaveat } from './states.js';

const KINDS = ['operators', 'directory'];

export function createCompaniesView({ meta }) {
  const tables = createTables(meta);
  const lens = { operators: { t: tables.operators, root: $('#ops-root'), started: false, info: null }, directory: { t: tables.directory, root: $('#co-root'), started: false, info: null } };
  const lede = $('#co-lede'); const note = $('#co-note');
  let kind = 'operators';
  let shown = false;

  const bar = segmented({
    label: 'What to list', prefix: 'cok', value: kind,
    options: [{ id: 'operators', label: 'Operators', title: 'Operators: who is drilling, in every state', controls: 'ops-root' }, { id: 'directory', label: 'Texas directory', title: 'Texas directory: oil and gas companies from the Comptroller’s records', controls: 'co-root' }],
    onChange: (id) => choose(id, true),
  });
  $('#co-switch').append(bar.el);

  // the lines under the heading and the switch: what the list is and what it leaves out, said once (the figures come from the data once it has loaded)
  const more = $('#co-more'); const moreText = $('#co-more-text');
  function words() {
    if (kind === 'directory') {
      lede.textContent = 'The oil and gas companies registered in Texas, from the Comptroller’s franchise-tax records, with RRC drilling activity where a name matched.';
      note.textContent = 'Texas Comptroller data updated ' + fmtDate(meta.sources.comptroller) + '. Texas only: no other state publishes a public bulk list of its oil and gas companies, so the directory is not national. The Operators list is.';
      more.hidden = true;
      return;
    }
    lede.textContent = 'Who is drilling for oil in every state that publishes its permits, ranked by new wells in the last 12 months, and the Texas companies that serve them.';
    more.hidden = false;
    const info = lens.operators.info;
    if (!info) { note.textContent = 'Loading the operators of every state…'; moreText.textContent = 'Operators are named only when they are corporations, LLCs or limited partnerships, never a person trading under a name.'; return; }
    const c = info.coverage;
    note.textContent = fmtN(c.states) + ' states' + (c.offshore ? ' and the federal offshore' : '') + '. Texas, Oklahoma, New Mexico and the federal offshore list every operator with a recent permit or spud; for the other ' + fmtN(c.listed)
      + ' states, the ' + info.listedMax + ' busiest each.';
    moreText.replaceChildren('A state counts permits approved or, where it publishes no approval dates by well, wells spudded or drilled (marked beside the number); the two are never added. ' + spudCaveat(STATES.map((x) => x.id)) + ' Only corporations, LLCs and limited partnerships are named, never a person trading under a name. '
      + (info.without.length ? 'No operator list yet for ' + listAnd(info.without) + ': ' : ''), info.without.length ? el('a', { href: '#national', text: 'the National report’s coverage table' }) : '', info.without.length ? ' says why. ' : '',
    info.prodEnd ? 'Oil and gas columns are Texas’s, for the 12 months to ' + info.prodEnd + '.' : '');
  }
  const fmtN = (n) => new Intl.NumberFormat('en-US').format(n);

  function ensure(k) {
    const l = lens[k];
    if (l.started) return;
    l.started = true;
    l.t.load().then((info) => { l.info = info || null; if (shown && kind === k) words(); })
      .catch(() => { l.started = false; l.t.ex.fail('Could not load the data. Reload the page to try again.'); });
  }

  // shows one table; `fromBar` carries what was typed in the search box to the other (an address that names the kind starts it from its own query)
  function choose(next, fromBar) {
    if (!KINDS.includes(next)) next = 'operators';
    const was = kind;
    if (fromBar && was !== next) lens[next].t.ex.setQuery(lens[was].t.ex.query);
    kind = next;
    for (const k of KINDS) { lens[k].root.hidden = k !== kind; lens[k].t.ex.setActive(shown && k === kind); }
    bar.set(kind, false);
    words();
    ensure(kind);
  }

  return {
    // the address says which list: a plain #companies is the operators (also from the Directory's own address: the tab brings you back to the page's start); an address with a
    // query starts that list from its defaults plus the query; with none, the list keeps the search and filters it was left with
    activate(params, hasQuery) {
      shown = true;
      const k = kindOf(params);
      if (hasQuery) {
        const q = withTexasFilters(params);
        if (q.has('s')) q.set('s', q.get('s').toUpperCase());
        lens[k].t.ex.apply(q);
      }
      choose(k, false);
    },
    deactivate() { shown = false; for (const k of KINDS) lens[k].t.ex.setActive(false); },
    // an older #operators address, in the page's own words
    fromOperators,
  };
}
