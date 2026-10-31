// Albers equal-area conic centered on Texas, plus every geometry the map and hero draw.
// World units: the shapes are 1000 wide, y grows southward. Views are transforms on these units.
// Each set of shapes (Texas, Oklahoma, both) is fitted to its own box and carries its own projection (G.toWorld); the module's
// toWorld is the Texas-fitted one that the Daily report's GPS map uses.
import { load, loadOpt, once } from './util.js';
import { POINT_BLOCK, stateOf, statesKey, countyKey } from './states.js';
import { mergePoints } from './overview-data.js';

const D2R = Math.PI / 180;
const L1 = 27.5; const L2 = 35; const L0 = 31; const LON0 = -100;
const N = (Math.sin(L1 * D2R) + Math.sin(L2 * D2R)) / 2;
const C = Math.cos(L1 * D2R) ** 2 + 2 * N * Math.sin(L1 * D2R);
const RHO0 = Math.sqrt(C - 2 * N * Math.sin(L0 * D2R)) / N;
const T = { minX: 0, maxY: 0, s: 1 };

function albers(lon, lat, out) {
  const rho = Math.sqrt(C - 2 * N * Math.sin(lat * D2R)) / N;
  const th = N * (lon - LON0) * D2R;
  out[0] = rho * Math.sin(th);
  out[1] = RHO0 - rho * Math.cos(th);
}
const tmp = [0, 0];
export function toWorld(lon, lat, out = [0, 0]) {
  albers(lon, lat, tmp);
  out[0] = (tmp[0] - T.minX) * T.s;
  out[1] = (T.maxY - tmp[1]) * T.s;
  return out;
}
// the same projection with its box fixed now, so shapes built later for another state cannot move it
function projector(box) {
  const { minX, maxY, s } = box;
  return (lon, lat, out = [0, 0]) => {
    albers(lon, lat, tmp);
    out[0] = (tmp[0] - minX) * s;
    out[1] = (maxY - tmp[1]) * s;
    return out;
  };
}

// city labels on the maps: name, latitude, longitude, state, priority (low is drawn first, and kept on a phone when it is 7 or less). A city that
// anchors two states' maps names both ('TX|FO': Houston is a Texas label, and the one that shows where the Gulf's federal waters begin)
const HUBS = [
  ['Houston', 29.7604, -95.3698, 'TX|FO', 0], ['Dallas', 32.7767, -96.797, 'TX', 1], ['San Antonio', 29.4241, -98.4936, 'TX', 2],
  ['El Paso', 31.7619, -106.485, 'TX', 3], ['Austin', 30.2672, -97.7431, 'TX', 4], ['Midland', 31.9973, -102.0779, 'TX', 5],
  ['Corpus Christi', 27.8006, -97.3964, 'TX|FO', 6], ['Fort Worth', 32.7555, -97.3308, 'TX', 7], ['Lubbock', 33.5779, -101.8552, 'TX', 8],
  ['Amarillo', 35.222, -101.8313, 'TX', 9], ['Odessa', 31.8457, -102.3676, 'TX', 10], ['Abilene', 32.4487, -99.7331, 'TX', 11],
  ['Laredo', 27.5306, -99.4803, 'TX', 12], ['San Angelo', 31.4638, -100.437, 'TX', 13], ['Victoria', 28.8053, -97.0036, 'TX', 14],
  ['Wichita Falls', 33.9137, -98.4934, 'TX', 15],
  ['Oklahoma City', 35.4676, -97.5164, 'OK', 1], ['Tulsa', 36.154, -95.9928, 'OK', 4], ['Lawton', 34.6036, -98.3959, 'OK', 9],
  ['Enid', 36.3956, -97.8784, 'OK', 10], ['Woodward', 36.4337, -99.3904, 'OK', 12],
  ['Albuquerque', 35.0844, -106.6504, 'NM', 3], ['Santa Fe', 35.687, -105.9378, 'NM', 7], ['Hobbs', 32.7026, -103.136, 'NM', 6],
  ['Carlsbad', 32.4207, -104.2288, 'NM', 8], ['Farmington', 36.7281, -108.2087, 'NM', 9], ['Roswell', 33.3943, -104.523, 'NM', 11],
  ['Las Cruces', 32.3199, -106.7637, 'NM', 12],
  ['New Orleans', 29.9511, -90.0715, 'FO', 2], ['Mobile', 30.6954, -88.0399, 'FO', 9], ['Tampa', 27.9506, -82.4572, 'FO', 10],
];

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

// the projection is module state: a second state's shapes are built against their own box, then the Texas box is put back
export function buildGeoIsolated(gj, hubStates) {
  const saved = { ...T };
  try { return buildGeo(gj, hubStates); } finally { Object.assign(T, saved); }
}

export function buildGeo(gj, hubStates = ['TX']) {
  const polys = gj.features.map((f) => (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates));
  let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity; let minLon = Infinity; let maxLon = -Infinity;
  for (const poly of polys) for (const rings of poly) for (const ring of rings) for (const p of ring) {
    if (p[0] < minLon) minLon = p[0];
    if (p[0] > maxLon) maxLon = p[0];
    albers(p[0], p[1], tmp);
    if (tmp[0] < minX) minX = tmp[0];
    if (tmp[0] > maxX) maxX = tmp[0];
    if (tmp[1] < minY) minY = tmp[1];
    if (tmp[1] > maxY) maxY = tmp[1];
  }
  T.minX = minX; T.maxY = maxY; T.s = 1000 / (maxX - minX);
  const W = 1000; const H = (maxY - minY) * T.s;
  const project = projector(T);

  const counties = []; const byFips = new Map();
  const outline = new Path2D(); const border = new Path2D();
  const edges = new Map();
  const o = [0, 0];
  gj.features.forEach((f, idx) => {
    const path = new Path2D(); const rings = [];
    const bb = [Infinity, Infinity, -Infinity, -Infinity];
    let best = null; let bestA = -1; let bx = 0; let by = 0;
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
      path.moveTo(xy[0], xy[1]);
      let a2 = 0; let cx = 0; let cy = 0;
      for (let j = 0; j < n; j++) {
        const k = (j + 1) % n;
        if (j) path.lineTo(xy[2 * j], xy[2 * j + 1]);
        const cr = xy[2 * j] * xy[2 * k + 1] - xy[2 * k] * xy[2 * j + 1];
        a2 += cr; cx += (xy[2 * j] + xy[2 * k]) * cr; cy += (xy[2 * j + 1] + xy[2 * k + 1]) * cr;
        // shared county borders appear twice; edges seen once are the state outline and the coast
        const va = Math.round(ring[j][0] * 1000) * 100000 + Math.round(ring[j][1] * 1000);
        const vb = Math.round(ring[k][0] * 1000) * 100000 + Math.round(ring[k][1] * 1000);
        const key = va < vb ? va + ':' + vb : vb + ':' + va;
        const e = edges.get(key);
        if (e) e[4]++;
        else edges.set(key, [xy[2 * j], xy[2 * j + 1], xy[2 * k], xy[2 * k + 1], 1]);
      }
      path.closePath();
      rings.push(xy);
      if (Math.abs(a2) > bestA && a2 !== 0) { bestA = Math.abs(a2); best = xy; bx = cx / (3 * a2); by = cy / (3 * a2); }
    }
    let lx = bx; let ly = by;
    if (!best || !inRing(best, lx, ly)) { lx = (bb[0] + bb[2]) / 2; ly = (bb[1] + bb[3]) / 2; }
    const c = { f: f.properties.f, n: f.properties.n, s: f.properties.s, i: idx, path, rings, bb, lx, ly };
    counties.push(c); byFips.set(c.f, c);
    outline.addPath(path);
  });
  for (const e of edges.values()) if (e[4] === 1) { border.moveTo(e[0], e[1]); border.lineTo(e[2], e[3]); }

  // the graticule covers -110 to -90 (every state on land), and further east when the shapes do (the Gulf's federal waters reach -80)
  const gLo = Math.min(-110, Math.floor(minLon / 2) * 2); const gHi = Math.max(-90, Math.ceil(maxLon / 2) * 2);
  const grat = new Path2D();
  for (let lat = 24; lat <= 38; lat += 2) {
    for (let lon = gLo; lon <= gHi; lon += 0.5) {
      project(lon, lat, o);
      if (lon === gLo) grat.moveTo(o[0], o[1]); else grat.lineTo(o[0], o[1]);
    }
  }
  for (let lon = gLo + 2; lon <= gHi - 2; lon += 2) {
    for (let lat = 23; lat <= 39; lat += 0.5) {
      project(lon, lat, o);
      if (lat === 23) grat.moveTo(o[0], o[1]); else grat.lineTo(o[0], o[1]);
    }
  }
  const hubs = HUBS.filter((h) => h[3].split('|').some((id) => hubStates.includes(id))).sort((a, b) => a[4] - b[4]).map(([n, lat, lon, , pri]) => { project(lon, lat, o); return { n, x: o[0], y: o[1], pri }; });
  return { counties, byFips, outline, border, grat, hubs, W, H, toWorld: project };
}

/* permits: parallel typed arrays, a recency flag and a spatial grid for hit-testing */
function finishPoints(a, G) {
  const { n, x, y, op } = a;
  const gs = 4; const gw = Math.ceil(G.W / gs) + 1; const gh = Math.ceil(G.H / gs) + 1;
  const heads = new Int32Array(gw * gh).fill(-1); const next = new Int32Array(n);
  const byOp = new Map();
  for (let i = 0; i < n; i++) {
    const cell = Math.min(gh - 1, Math.max(0, Math.floor(y[i] / gs))) * gw + Math.min(gw - 1, Math.max(0, Math.floor(x[i] / gs)));
    next[i] = heads[cell]; heads[cell] = i;
    if (op[i] >= 0) {
      let l = byOp.get(op[i]);
      if (!l) byOp.set(op[i], l = []);
      l.push(i);
    }
  }
  const sts = [...new Set(a.st)].sort((p, q) => p - q); // the states' numbers present, so a map can paint each in its own color
  return { ...a, gs, gw, gh, heads, next, byOp, sts };
}
export function buildPoints(pm, G) {
  const n = pm.pts.length;
  const a = {
    n, x: new Float32Array(n), y: new Float32Array(n), op: new Int16Array(n), t: new Int16Array(n),
    depth: new Uint16Array(n), fips: new Uint16Array(n), rec: new Uint8Array(n), st: new Uint8Array(n),
  };
  const day = 864e5;
  const t0 = Date.parse(pm.t0 + 'T00:00:00Z');
  const cut = Math.round((Date.parse(pm.asOf + 'T00:00:00Z') - t0) / day) - 365;
  const o = [0, 0];
  for (let i = 0; i < n; i++) {
    const p = pm.pts[i];
    G.toWorld(p[1] / 1e4, p[0] / 1e4, o);
    a.x[i] = o[0]; a.y[i] = o[1]; a.op[i] = p[2]; a.t[i] = p[3]; a.depth[i] = p[4]; a.fips[i] = p[5];
    // a merged set (both states) says per point whether it is recent, against its own state's last day; a single file against its asOf
    a.rec[i] = p.length > 6 ? p[6] : p[3] >= cut ? 1 : 0;
    a.st[i] = Math.floor(p[5] / POINT_BLOCK); // the state's number (states.js)
  }
  return { ...finishPoints(a, G), t0, cut };
}
// QA only: a synthetic set of the requested size, to prove the engine holds up past the real 9,404 points
export function stressPoints(P, total, G) {
  const a = {
    n: total, x: new Float32Array(total), y: new Float32Array(total), op: new Int16Array(total), t: new Int16Array(total),
    depth: new Uint16Array(total), fips: new Uint16Array(total), rec: new Uint8Array(total), st: new Uint8Array(total),
  };
  for (let i = 0; i < total; i++) {
    const s = i % P.n;
    a.x[i] = P.x[s] + (((i * 7919) % 97) / 97 - 0.5) * 6; a.y[i] = P.y[s] + (((i * 104729) % 89) / 89 - 0.5) * 6;
    a.op[i] = P.op[s]; a.t[i] = P.t[s]; a.depth[i] = P.depth[s]; a.fips[i] = P.fips[s]; a.rec[i] = P.rec[s]; a.st[i] = P.st[s];
  }
  return { ...finishPoints(a, G), t0: P.t0, cut: P.cut };
}

export function buildZips(zc, G) {
  const o = [0, 0];
  const list = zc.rows.map((r) => {
    G.toWorld(r[2], r[1], o);
    return { zip: r[0], x: o[0], y: o[1], total: r[3], likely: r[4], isNew: r[5], rrc: r[6] };
  }).sort((a, b) => b.total - a.total);
  return { list, max: list.length ? list[0].total : 1, byZip: new Map(list.map((z, i) => [z.zip, i])) };
}

export function buildInfra(inf, G) {
  const o = [0, 0];
  return (inf.layers || []).filter((l) => l.items && l.items.length).map((l) => ({
    id: l.id, label: l.label, unit: l.unit,
    items: l.items.map((it) => {
      G.toWorld(it.lon, it.lat, o);
      const ci = countyAt(G, o[0], o[1]);
      return { n: it.n, c: it.c, cap: it.cap, x: o[0], y: o[1], fips: ci < 0 ? '' : G.counties[ci].f };
    }),
  }));
}

/* basins: each region's counties, merged shape, outer boundary (edges used by one county only) and a dim path of everything else */
export function buildBasins(b, G) {
  const list = (b.basins || []).map((x) => {
    const idxs = x.fips.map((f) => G.byFips.get(f)).filter(Boolean).map((c) => c.i);
    const set = new Set(idxs);
    const path = new Path2D(); const bb = [Infinity, Infinity, -Infinity, -Infinity]; const edges = new Map();
    for (const i of idxs) {
      const c = G.counties[i]; path.addPath(c.path);
      bb[0] = Math.min(bb[0], c.bb[0]); bb[1] = Math.min(bb[1], c.bb[1]); bb[2] = Math.max(bb[2], c.bb[2]); bb[3] = Math.max(bb[3], c.bb[3]);
      for (const xy of c.rings) {
        const n = xy.length / 2;
        for (let j = 0; j < n; j++) {
          const k = (j + 1) % n;
          const a = xy[2 * j] + ',' + xy[2 * j + 1]; const q = xy[2 * k] + ',' + xy[2 * k + 1];
          const key = a < q ? a + '|' + q : q + '|' + a;
          const e = edges.get(key);
          if (e) e[4]++; else edges.set(key, [xy[2 * j], xy[2 * j + 1], xy[2 * k], xy[2 * k + 1], 1]);
        }
      }
    }
    const boundary = new Path2D();
    for (const e of edges.values()) if (e[4] === 1) { boundary.moveTo(e[0], e[1]); boundary.lineTo(e[2], e[3]); }
    let dim = null;
    return {
      id: x.id, name: x.name, note: x.note || '', fips: x.fips.filter((f) => G.byFips.has(f)), idxs, set, path, bb, boundary,
      get dim() { if (!dim) { dim = new Path2D(); for (const c of G.counties) if (!set.has(c.i)) dim.addPath(c.path); } return dim; },
    };
  });
  return { src: b.src, list, byId: new Map(list.map((x) => [x.id, x])), byFips: new Map(list.flatMap((x) => x.fips.map((f) => [f, x]))) };
}

/* shapes and permit points for a set of states. Texas alone is the original (plain county codes, the Texas-fitted box). With another state
   in, its counties are keyed OK:001, its points carry county codes offset by 1000 times its number and operator numbers prefixed OK:, and
   the shapes are fitted to whatever is shown without moving the Texas projection (states.js says where each state's files are). */
const TEXAS = ['TX'];
const texasOnly = (states) => states.length === 1 && states[0] === 'TX';
const geoName = (id) => (id === 'TX' ? 'counties.geo' : stateOf(id).files.geo);
const pointsName = (id) => (id === 'TX' ? 'permits' : stateOf(id).files.points);
async function shapesFor(states) {
  const features = [];
  for (const id of states) {
    const gj = await load(geoName(id));
    for (const f of gj.features) features.push({ type: 'Feature', properties: { f: countyKey(id, f.properties.f), n: f.properties.n, s: id }, geometry: f.geometry });
  }
  return { type: 'FeatureCollection', features };
}
async function pointsFor(states) {
  if (texasOnly(states)) return load('permits');
  const got = await Promise.all(states.map((id) => load(pointsName(id))));
  return mergePoints(states.map((id, i) => ({ id, pm: got[i] })));
}

/* memoized loaders shared by the hero, the map and the tables. The Texas ones are the default; a set of states is built once. */
export const getGeo = (states = TEXAS) => once(texasOnly(states) ? 'geo' : 'geo:' + statesKey(states), async () => (
  texasOnly(states) ? buildGeo(await load('counties.geo')) : buildGeoIsolated(await shapesFor(states), states)));
export const getPoints = (states = TEXAS) => once(texasOnly(states) ? 'pts' : 'pts:' + statesKey(states), async () => {
  const [pm, G] = await Promise.all([pointsFor(states), getGeo(states)]);
  return { pm, P: buildPoints(pm, G) };
});
// The company ZIPs, the plants and terminals and the basins are Texas's; they sit on whatever shapes are shown (Texas's own, or the set that has Texas in it).
const layerKey = (name, states) => (texasOnly(states) ? name : name + ':' + statesKey(states));
export const getZips = (states = TEXAS) => once(layerKey('zips', states), async () => {
  const [zc, G] = await Promise.all([loadOpt('zip-companies'), getGeo(states)]);
  return zc ? buildZips(zc, G) : null;
});
export const getInfra = (states = TEXAS) => once(layerKey('infra', states), async () => {
  const [inf, G] = await Promise.all([loadOpt('infra'), getGeo(states)]);
  return inf ? { src: inf.src, asOf: inf.asOf, layers: buildInfra(inf, G) } : null;
});
export const getBasins = (states = TEXAS) => once(layerKey('basins', states), async () => {
  const [b, G] = await Promise.all([loadOpt('basins'), getGeo(states)]);
  return b && b.basins && b.basins.length ? buildBasins(b, G) : null;
});
