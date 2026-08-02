/* One-time geometry baker for the Explorer map.
 *
 * Why this exists: us-atlas's pre-projected `counties-albers-10m.json` silently omits
 * Puerto Rico (78 municipios), American Samoa, N. Mariana Islands, USVI and Guam —
 * 1,668 county-declaration events, 3.4% of the data. Puerto Rico is the #2 recipient of
 * FEMA obligations ($39.7B) and home to Hurricane Maria, the largest single obligation
 * in the dataset, so dropping it is not acceptable. d3's geoAlbersUsa drops them too.
 *
 * So we project `counties-10m.json` (geographic) ourselves with a composite Albers that
 * carries insets for every territory, quantize to 1/4 px, delta-encode, and bake the
 * result into explore-geo.js. County borders effectively never change, so this is run
 * by hand — not part of the weekly build.
 *
 * Re-run:  npm i us-atlas@3 topojson-client@3 d3-geo@3 && node tools/bake-geo.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import * as topojson from 'topojson-client';
import { geoConicEqualArea } from 'd3-geo';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const REQ = path.resolve(process.env.GEO_MODULES || path.join(ROOT, 'node_modules'));

const W = 975, H = 610, K = 1070, Q = 4;      /* frame, base scale, 1/4-px quantization */

/* state FIPS prefix -> USPS abbreviation, for the county-name crosswalk emitted below */
const STAB = {'01':'AL','02':'AK','04':'AZ','05':'AR','06':'CA','08':'CO','09':'CT','10':'DE','11':'DC',
  '12':'FL','13':'GA','15':'HI','16':'ID','17':'IL','18':'IN','19':'IA','20':'KS','21':'KY','22':'LA',
  '23':'ME','24':'MD','25':'MA','26':'MI','27':'MN','28':'MS','29':'MO','30':'MT','31':'NE','32':'NV',
  '33':'NH','34':'NJ','35':'NM','36':'NY','37':'NC','38':'ND','39':'OH','40':'OK','41':'OR','42':'PA',
  '44':'RI','45':'SC','46':'SD','47':'TN','48':'TX','49':'UT','50':'VT','51':'VA','53':'WA','54':'WV',
  '55':'WI','56':'WY','60':'AS','66':'GU','69':'MP','72':'PR','78':'VI'};

/* region → conic equal-area projection, positioned inside the frame */
function conic(lon0, latc, p1, p2, k, tx, ty) {
  return geoConicEqualArea().parallels([p1, p2]).rotate([-lon0, 0])
    .center([0, latc]).scale(k).translate([tx, ty]);
}
const LOWER48 = conic(-96, 38.7, 29.5, 45.5, K, 487.5, 305);
const INSETS = {
  '02': conic(-152, 58.5, 55, 65, 0.35 * K, 150, 470),      /* Alaska   */
  '15': conic(-157, 19.9, 8, 18, K, 300, 540),              /* Hawaii   */
  '72': conic(-66.4, 18.2, 8, 18, 1.5 * K, 838, 545),       /* Puerto Rico */
  '78': conic(-66.4, 18.2, 8, 18, 1.5 * K, 838, 545),       /* USVI (shares PR frame) */
  '66': conic(144.8, 13.4, 8, 18, 1.2 * K, 60, 545),        /* Guam     */
  '69': conic(144.8, 13.4, 8, 18, 1.2 * K, 60, 545),        /* N. Marianas */
  '60': conic(-170.7, -14.3, -16, -12, 1.2 * K, 180, 565)   /* American Samoa */
};
function projFor(fips) { return INSETS[fips.slice(0, 2)] || LOWER48; }

const topo = JSON.parse(fs.readFileSync(path.join(REQ, 'us-atlas/counties-10m.json'), 'utf8'));
const counties = topojson.feature(topo, topo.objects.counties).features;
const statesMesh = topojson.mesh(topo, topo.objects.states, (a, b) => a !== b);
console.log(`source: ${counties.length} counties`);

/* Alaska's Aleutians cross the antimeridian; fold them back so they land in the inset. */
function fixLon(fips, lon) { return (fips.slice(0, 2) === '02' && lon > 0) ? lon - 360 : lon; }

function ringsOf(geom) {
  if (!geom) return [];
  if (geom.type === 'Polygon') return geom.coordinates;
  if (geom.type === 'MultiPolygon') return geom.coordinates.flat();
  return [];
}

const ids = [], names = [], ringCounts = [], ringLens = [], coords = [];
let dropped = 0, kept = 0;

for (const f of counties.slice().sort((a, b) => String(a.id).localeCompare(String(b.id)))) {
  const fips = String(f.id).padStart(5, '0');
  const p = projFor(fips);
  const out = [], tiny = [];
  for (const ring of ringsOf(f.geometry)) {
    const pts = [];
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const [lon, lat] of ring) {
      const xy = p([fixLon(fips, lon), lat]);
      if (!xy || !isFinite(xy[0]) || !isFinite(xy[1])) continue;
      const x = Math.round(xy[0] * Q), y = Math.round(xy[1] * Q);
      if (pts.length && pts[pts.length - 2] === x && pts[pts.length - 1] === y) continue;
      pts.push(x, y);
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
    if (pts.length < 6) { dropped++; continue; }                    /* degenerate */
    /* sub-pixel islet — drop it only if this county has other geometry to draw, so tiny
       jurisdictions (Virginia's independent cities) never vanish from the map entirely */
    if ((maxX - minX) < Q && (maxY - minY) < Q) { tiny.push(pts); dropped++; continue; }
    out.push(pts);
  }
  if (!out.length && tiny.length) { out.push(tiny[0]); dropped--; }
  if (!out.length) { console.warn(`  no geometry: ${fips}`); continue; }
  ids.push(fips);
  names.push((f.properties && f.properties.name) || fips);
  ringCounts.push(out.length);
  for (const r of out) { ringLens.push(r.length / 2); for (const v of r) coords.push(v); }
  kept++;
}
console.log(`projected: ${kept} counties, ${ringLens.length} rings, ${coords.length / 2} verts (dropped ${dropped} sub-pixel rings)`);

/* state mesh, same projection — lower 48 only for the hairlines is wrong, so project
   each segment with the projection appropriate to where it starts */
const meshOut = [];
for (const line of statesMesh.coordinates) {
  const pts = [];
  for (const [lon, lat] of line) {
    const xy = LOWER48([lon, lat]);
    if (xy && isFinite(xy[0]) && isFinite(xy[1])) pts.push(Math.round(xy[0] * Q), Math.round(xy[1] * Q));
  }
  if (pts.length >= 4) meshOut.push(pts);
}

/* delta-encode: ids (ascending) and the interleaved coordinate stream */
const idD = []; let prevId = 0;
for (const f of ids) { const n = +f; idD.push(n - prevId); prevId = n; }
const cD = []; let pv = 0;
for (const v of coords) { cD.push(v - pv); pv = v; }
const mD = []; let pm = 0;
for (const line of meshOut) for (const v of line) { mD.push(v - pm); pm = v; }

const payload = {
  q: Q, w: W, h: H, nm: names,
  idD, rc: ringCounts, rl: ringLens, d: cD,
  ml: meshOut.map(l => l.length / 2), md: mD
};
const inner = JSON.stringify(payload);
const js = 'window.EXPLORE_GEO=JSON.parse(' + JSON.stringify(inner) + ');\n';
fs.writeFileSync(path.join(ROOT, 'explore-geo.js'), js);
console.log(`explore-geo.js written: ${(js.length / 1024).toFixed(0)} KB raw`);

/* Crosswalk reference for build.py's money join: every county's FIPS, name and state.
   PA money is keyed by county NAME per state, so the build needs a complete name list —
   including counties that received money but never had a declaration of their own. */
const xwalk = {};
ids.forEach((f, i) => { xwalk[f] = { n: names[i], s: STAB[f.slice(0, 2)] || '' }; });
fs.writeFileSync(path.join(ROOT, 'county-fips.json'), JSON.stringify(xwalk));
console.log(`county-fips.json written: ${ids.length} counties`);

/* sanity: known locations should land where we expect */
const probes = { '53033': 'King, WA', '23019': 'Penobscot, ME', '06037': 'Los Angeles, CA',
                 '48201': 'Harris, TX', '12086': 'Miami-Dade, FL', '72127': 'San Juan, PR',
                 '02020': 'Anchorage, AK', '15003': 'Honolulu, HI', '66010': 'Guam' };
let ci = 0, ri = 0, idc = 0;
const pos = {};
for (let i = 0; i < ids.length; i++) {
  const nr = ringCounts[i];
  let sx = 0, sy = 0, sn = 0, base = ci;
  for (let r = 0; r < nr; r++) { const len = ringLens[ri + r]; if (r === 0) { for (let k = 0; k < len; k++) { sx += coords[base + k * 2]; sy += coords[base + k * 2 + 1]; sn++; } } base += len * 2; }
  for (let r = 0; r < nr; r++) ci += ringLens[ri + r] * 2;
  ri += nr;
  if (probes[ids[i]]) pos[ids[i]] = [Math.round(sx / sn / Q), Math.round(sy / sn / Q)];
}
console.log('\nprobe positions (x,y in a 975x610 frame):');
for (const k of Object.keys(probes)) console.log(`  ${probes[k].padEnd(18)} ${pos[k] ? pos[k].join(', ') : 'MISSING'}`);
