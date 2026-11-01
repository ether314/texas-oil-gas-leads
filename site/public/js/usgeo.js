// The national map's geography: one projection for the whole country (an Albers equal-area conic for the lower 48, with Alaska drawn smaller in its own box
// below the Southwest, as every map of the country does), the 49 outlines of data/us-states.json turned into world units, and the projection of a well's point.
// Pure functions, no DOM: Node tests them against the committed files. World units are 1000 wide, y grows southward.
//
// Every point is projected by the state it is filed under, so a well in Alaska's North Slope lands in the inset and a Texas well in Texas.

const D2R = Math.PI / 180;

// an Albers equal-area conic with two standard parallels, the origin at (lat0, lon0); returns (lon, lat) -> [x, y] on the unit sphere, y north-up
function conic(p1, p2, lat0, lon0) {
  const n = (Math.sin(p1 * D2R) + Math.sin(p2 * D2R)) / 2;
  const c = Math.cos(p1 * D2R) ** 2 + 2 * n * Math.sin(p1 * D2R);
  const rho0 = Math.sqrt(c - 2 * n * Math.sin(lat0 * D2R)) / n;
  return (lon, lat) => {
    // the longitude difference is taken the short way round: the Aleutians' points at 172 degrees east sit next to -170
    const dl = ((((lon - lon0) % 360) + 540) % 360) - 180;
    const rho = Math.sqrt(c - 2 * n * Math.sin(lat * D2R)) / n;
    const th = n * dl * D2R;
    return [rho * Math.sin(th), rho0 - rho * Math.cos(th)];
  };
}
const LOWER = conic(29.5, 45.5, 37.5, -96);
const ALASKA = conic(55, 65, 50, -154);
const ALASKA_SCALE = 0.34; // Alaska is drawn at a third of its size, as on the usual maps

// the box of the lower 48 in the conic's own units, found once from the outlines' extremes (the same fixed numbers every time: no data is read here)
const LOWER_BOX = (() => {
  const pts = [[-124.7, 48.4], [-124.2, 40.4], [-117.1, 32.5], [-97.1, 25.9], [-82.2, 24.5], [-80.0, 26.5], [-81.0, 31.5], [-75.5, 35.2], [-70.0, 41.7], [-67.0, 44.8], [-69.0, 47.4], [-83.0, 46.0], [-95.2, 49.4], [-123.0, 49.0], [-104.0, 49.0], [-89.5, 48.0], [-106.6, 31.8], [-100.0, 28.0]];
  let a = Infinity; let b = Infinity; let c = -Infinity; let d = -Infinity;
  for (const [lo, la] of pts) { const [x, y] = LOWER(lo, la); a = Math.min(a, x); c = Math.max(c, x); b = Math.min(b, y); d = Math.max(d, y); }
  return { x0: a, y0: b, x1: c, y1: d };
})();
const W = 1000;
const SCALE = W / (LOWER_BOX.x1 - LOWER_BOX.x0);
const LOWER_H = (LOWER_BOX.y1 - LOWER_BOX.y0) * SCALE;
// the inset: Alaska's own conic scaled down, its bottom-left corner placed under California and Arizona, below the lower 48's southern border
const AK_ORIGIN = ALASKA(-168, 54.5); // roughly Alaska's southwest corner (the Aleutians' tail and the Alaska Peninsula)
const AK_SHIFT = { x: W * 0.102, y: LOWER_H * 0.995 };
export const H = Math.round(LOWER_H + W * 0.02);
export const WIDTH = W;

// (lon, lat, state) -> [x, y] in world units
export function project(lon, lat, state, out = [0, 0]) {
  if (state === 'AK') {
    const [x, y] = ALASKA(lon, lat);
    out[0] = AK_SHIFT.x + (x - AK_ORIGIN[0]) * SCALE * ALASKA_SCALE;
    out[1] = AK_SHIFT.y - (y - AK_ORIGIN[1]) * SCALE * ALASKA_SCALE;
    return out;
  }
  const [x, y] = LOWER(lon, lat);
  out[0] = (x - LOWER_BOX.x0) * SCALE;
  out[1] = (LOWER_BOX.y1 - y) * SCALE;
  return out;
}

// a point inside the ring for a label or a ring to sit on: the middle of its box when that is inside, else the inside point nearest the middle of the inside points (Louisiana's box middle is in Mississippi)
function insidePoint(r, box) {
  const mid = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  if (inRing(r, mid[0], mid[1])) return mid;
  const N = 28; const pts = []; let mx = 0; let my = 0;
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const x = box[0] + ((i + 0.5) * (box[2] - box[0])) / N; const y = box[1] + ((j + 0.5) * (box[3] - box[1])) / N;
    if (inRing(r, x, y)) { pts.push([x, y]); mx += x; my += y; }
  }
  if (!pts.length) return mid;
  mx /= pts.length; my /= pts.length;
  return pts.reduce((best, q) => (Math.hypot(q[0] - mx, q[1] - my) < Math.hypot(best[0] - mx, best[1] - my) ? q : best), pts[0]);
}
// the outlines in world units: { TX: { name, rings: [Float32Array x,y,x,y...], bb: [x0,y0,x1,y1], c: [cx, cy] } }, c a label point inside the biggest ring (the middle of its box, or the nearest inside point when that is outside it)
export function buildOutlines(doc) {
  const out = {};
  for (const [code, s] of Object.entries(doc.states)) {
    const rings = []; let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity; let big = 0; let bigBox = null; let bigRing = null;
    const p = [0, 0];
    for (const flat of s.rings) {
      const r = new Float32Array(flat.length);
      let a = Infinity; let b = Infinity; let c = -Infinity; let d = -Infinity;
      for (let i = 0; i < flat.length; i += 2) {
        project(flat[i], flat[i + 1], code, p);
        r[i] = p[0]; r[i + 1] = p[1];
        if (p[0] < a) a = p[0]; if (p[0] > c) c = p[0]; if (p[1] < b) b = p[1]; if (p[1] > d) d = p[1];
      }
      rings.push(r);
      x0 = Math.min(x0, a); y0 = Math.min(y0, b); x1 = Math.max(x1, c); y1 = Math.max(y1, d);
      const area = (c - a) * (d - b);
      if (area > big) { big = area; bigBox = [a, b, c, d]; bigRing = r; }
    }
    out[code] = { name: s.name, rings, bb: [x0, y0, x1, y1], c: bigBox ? insidePoint(bigRing, bigBox) : [0, 0] };
  }
  return out;
}

// is the world point inside one ring (even-odd)?
export function inRing(r, x, y) {
  let c = false;
  for (let i = 0, j = r.length - 2; i < r.length; j = i, i += 2) {
    const yi = r[i + 1]; const yj = r[j + 1];
    if ((yi > y) !== (yj > y) && x < ((r[j] - r[i]) * (y - yi)) / (yj - yi) + r[i]) c = !c;
  }
  return c;
}
// the state whose outline holds the world point, or null (open water, Canada, Mexico); the states' boxes are tried first
export function stateAt(outlines, x, y) {
  for (const [code, s] of Object.entries(outlines)) {
    if (x < s.bb[0] || x > s.bb[2] || y < s.bb[1] || y > s.bb[3]) continue;
    for (const r of s.rings) if (inRing(r, x, y)) return code;
  }
  return null;
}

// the box (world units) that frames a state with some air around it; Alaska's is its inset and Texas's is Texas
export function frameOf(outlines, code, pad = 0.12) {
  const s = outlines[code];
  if (!s) return { x0: 0, y0: 0, x1: W, y1: H };
  const [a, b, c, d] = s.bb;
  const w = c - a; const h = d - b;
  return { x0: a - w * pad, y0: b - h * pad, x1: c + w * pad, y1: d + h * pad };
}
