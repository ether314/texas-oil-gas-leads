// The county shapes and ZIP centers that the Companies tables name counties by: an Albers equal-area conic, the counties' rings and boxes in world units (1000 wide, y grows southward),
// and the point-in-county test that puts a ZIP code's center in its county. No drawing: the maps are usmap.js's (the states' outlines, usgeo.js).
import { load, loadOpt, once } from './util.js';
import { stateOf, statesKey, countyKey } from './states.js';

const D2R = Math.PI / 180;
const L1 = 27.5; const L2 = 35; const L0 = 31; const LON0 = -100;
const N = (Math.sin(L1 * D2R) + Math.sin(L2 * D2R)) / 2;
const C = Math.cos(L1 * D2R) ** 2 + 2 * N * Math.sin(L1 * D2R);
const RHO0 = Math.sqrt(C - 2 * N * Math.sin(L0 * D2R)) / N;

const tmp = [0, 0];
function albers(lon, lat, out) {
  const rho = Math.sqrt(C - 2 * N * Math.sin(lat * D2R)) / N;
  const th = N * (lon - LON0) * D2R;
  out[0] = rho * Math.sin(th);
  out[1] = RHO0 - rho * Math.cos(th);
}
// the projection fitted to a box: each set of shapes is fitted to its own, so one state's shapes never move another's
function projector({ minX, maxY, s }) {
  return (lon, lat, out = [0, 0]) => {
    albers(lon, lat, tmp);
    out[0] = (tmp[0] - minX) * s;
    out[1] = (maxY - tmp[1]) * s;
    return out;
  };
}

function inRing(xy, x, y) {
  let c = false;
  for (let i = 0, j = xy.length - 2; i < xy.length; j = i, i += 2) {
    const yi = xy[i + 1]; const yj = xy[j + 1];
    if ((yi > y) !== (yj > y) && x < ((xy[j] - xy[i]) * (y - yi)) / (yj - yi) + xy[i]) c = !c;
  }
  return c;
}
export function inCounty(c, x, y) {
  if (x < c.bb[0] || x > c.bb[2] || y < c.bb[1] || y > c.bb[3]) return false;
  for (const r of c.rings) if (inRing(r, x, y)) return true;
  return false;
}
export function countyAt(G, x, y) {
  const cs = G.counties;
  for (let i = 0; i < cs.length; i++) if (inCounty(cs[i], x, y)) return i;
  return -1;
}

// the counties of a GeoJSON file of county shapes ({ f: key, n: name, s: state } a feature), in world units fitted to the shapes: { counties, byFips, toWorld }
export function buildGeo(gj) {
  const polys = gj.features.map((f) => (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates));
  let minX = Infinity; let maxX = -Infinity; let maxY = -Infinity; let minY = Infinity;
  for (const poly of polys) for (const rings of poly) for (const ring of rings) for (const p of ring) {
    albers(p[0], p[1], tmp);
    if (tmp[0] < minX) minX = tmp[0];
    if (tmp[0] > maxX) maxX = tmp[0];
    if (tmp[1] < minY) minY = tmp[1];
    if (tmp[1] > maxY) maxY = tmp[1];
  }
  const project = projector({ minX, maxY, s: 1000 / (maxX - minX) });
  const counties = []; const byFips = new Map(); const o = [0, 0];
  gj.features.forEach((f, idx) => {
    const rings = []; const bb = [Infinity, Infinity, -Infinity, -Infinity];
    for (const poly of polys[idx]) for (const ring of poly) {
      const last = ring[ring.length - 1];
      const n = ring.length - (ring[0][0] === last[0] && ring[0][1] === last[1] ? 1 : 0);
      const xy = new Float32Array(n * 2);
      for (let j = 0; j < n; j++) {
        project(ring[j][0], ring[j][1], o);
        xy[2 * j] = o[0]; xy[2 * j + 1] = o[1];
        if (o[0] < bb[0]) bb[0] = o[0];
        if (o[1] < bb[1]) bb[1] = o[1];
        if (o[0] > bb[2]) bb[2] = o[0];
        if (o[1] > bb[3]) bb[3] = o[1];
      }
      rings.push(xy);
    }
    const c = { f: f.properties.f, n: f.properties.n, s: f.properties.s, i: idx, rings, bb };
    counties.push(c); byFips.set(c.f, c);
  });
  return { counties, byFips, toWorld: project };
}

// the company ZIP codes (the Comptroller's pool), each at the Census center of its ZIP, in the same world units as the counties
export function buildZips(zc, G) {
  const o = [0, 0];
  const list = zc.rows.map((r) => {
    G.toWorld(r[2], r[1], o);
    return { zip: r[0], x: o[0], y: o[1], total: r[3], likely: r[4], isNew: r[5], rrc: r[6] };
  }).sort((a, b) => b.total - a.total);
  return { list, max: list.length ? list[0].total : 1, byZip: new Map(list.map((z, i) => [z.zip, i])) };
}

/* the county shapes for a set of states. Texas alone is the original (plain county codes); with another state in, its counties are keyed OK:001 (states.js says where each state's file is) */
const TEXAS = ['TX'];
const texasOnly = (states) => states.length === 1 && states[0] === 'TX';
const geoName = (id) => (id === 'TX' ? 'counties.geo' : stateOf(id).files.geo);
async function shapesFor(states) {
  const features = [];
  for (const id of states) {
    const gj = await load(geoName(id));
    for (const f of gj.features) features.push({ type: 'Feature', properties: { f: countyKey(id, f.properties.f), n: f.properties.n, s: id }, geometry: f.geometry });
  }
  return { type: 'FeatureCollection', features };
}
// memoized: a set of states is built once
export const getGeo = (states = TEXAS) => once(texasOnly(states) ? 'geo' : 'geo:' + statesKey(states), async () => (
  texasOnly(states) ? buildGeo(await load('counties.geo')) : buildGeo(await shapesFor(states))));
export const getZips = (states = TEXAS) => once(texasOnly(states) ? 'zips' : 'zips:' + statesKey(states), async () => {
  const [zc, G] = await Promise.all([loadOpt('zip-companies'), getGeo(states)]);
  return zc ? buildZips(zc, G) : null;
});
