// The other states' operators as the Companies page's tables read them. Pure functions (no DOM, no fetch), so they run under Node as well.
//
// Texas's files are keyed by plain county codes and P-5 operator numbers; every other state's by codes that repeat Texas's and by its own
// operator numbers, so another state's counties are keyed OK:001 and its operators OK:123 (states.js).
import { countyKey } from './states.js';

// Another state's operators as the objects the Texas table gives (toObjects), numbers and county keyed by state.
export function stateOperatorRows(id, doc) {
  if (!doc) return [];
  return doc.rows.map((row, i) => {
    const o = { _i: i, st: id };
    doc.cols.forEach((c, j) => { o[c] = row[j]; });
    o.rawNum = o.num; o.num = id + ':' + o.num; o.county = o.county ? countyKey(id, o.county) : '';
    return o;
  });
}
// What the operator pages know about another state's operator, in the shape Texas's operator-extras file gives (what only Texas has stays null)
export const operatorExtras = (r) => ({ prev12: r.prev12, spud12: null, depth: r.depth, fips: r.county, counties: r.counties, m24: r.m24 });
