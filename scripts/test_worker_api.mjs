// Offline test for worker-api.js: every site fetch is answered from this
// repository's own files, so the API is checked against the real data.
//   node scripts/test_worker_api.mjs
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let siteDown = false;

globalThis.fetch = async (url) => {
  if (siteDown) return new Response("down", { status: 503 });
  const rel = new URL(url).pathname.replace(/^\//, "");
  try {
    return new Response(await readFile(path.join(ROOT, rel)), { status: 200 });
  } catch {
    return new Response("not found", { status: 404 });
  }
};

const worker = (await import(path.join(ROOT, "worker-api.js"))).default;

async function get(p, env = {}, headers = {}) {
  const res = await worker.fetch(new Request(`https://api.disasterdata.io${p}`, { headers }), env);
  return { status: res.status, headers: res.headers, body: await res.json() };
}

let passed = 0;
async function test(name, fn) {
  await fn();
  passed += 1;
  console.log("ok  ", name);
}

await test("index lists the endpoints", async () => {
  const r = await get("/");
  assert.equal(r.status, 200);
  assert.ok(r.body.endpoints["/v1/states/{ST}/crosswalk"]);
  assert.equal(r.headers.get("access-control-allow-origin"), "*");
});

await test("state list covers states and territories", async () => {
  const r = await get("/v1/states");
  assert.equal(r.status, 200);
  assert.ok(r.body.count >= 57);
  const va = r.body.states.find((s) => s.state === "VA");
  assert.equal(va.name, "Virginia");
  assert.ok(va.state_declarations > 0);
  assert.equal(r.body.states.find((s) => s.state === "PR").state_declarations, null);
});

await test("state summary", async () => {
  const r = await get("/v1/states/tn");
  assert.equal(r.status, 200);
  assert.equal(r.body.state, "TN");
  assert.ok(r.body.federal.declarations > 50);
  assert.ok(r.body.links.crosswalk);
  const pr = await get("/v1/states/PR");
  assert.equal(pr.status, 200);
  assert.equal(pr.body.state_declarations, null);
});

await test("federal declarations with filters", async () => {
  const all = await get("/v1/states/TN/declarations");
  const em = await get("/v1/states/TN/declarations?type=em&since=2026-01-01");
  assert.ok(all.body.count > em.body.count);
  assert.ok(em.body.declarations.some((d) => d.fema_id === "EM-3635-TN"));
  assert.ok(em.body.declarations.every((d) => d.type === "EM" && d.date >= "2026-01-01"));
  assert.equal((await get("/v1/states/TN/declarations?since=January")).status, 400);
  assert.equal((await get("/v1/states/TN/declarations?type=XX")).status, 400);
});

await test("one declaration with its areas named", async () => {
  const r = await get("/v1/declarations/em-3635-tn");
  assert.equal(r.status, 200);
  assert.equal(r.body.declaration.end, "2026-01-27");
  assert.ok(r.body.declaration.areas.some((a) => a.name && a.name.startsWith("Putnam")));
  assert.equal((await get("/v1/declarations/DR-1-TN")).status, 404);
  assert.equal((await get("/v1/declarations/4898")).status, 400);
});

await test("county declarations include statewide ones", async () => {
  const r = await get("/v1/counties/47141");
  assert.equal(r.status, 200);
  assert.match(r.body.name, /Putnam/);
  assert.ok(r.body.declarations.some((d) => d.fema_id === "EM-3635-TN"));
  assert.ok(r.body.declarations.every((d) => !("fips" in d)));
  assert.equal((await get("/v1/counties/4714")).status, 400);
  assert.equal((await get("/v1/counties/99001")).status, 404);
});

await test("state declarations and crosswalk come from api.json", async () => {
  const a = await get("/v1/states/VA/actions");
  const c = await get("/v1/states/va/crosswalk");
  assert.equal(a.status, 200);
  assert.equal(a.body.count, c.body.count);
  const local = JSON.parse(await readFile(path.join(ROOT, "plus/virginia/api.json"), "utf8"));
  assert.equal(c.body.count, local.crosswalk.length);
  const em = c.body.crosswalk.find((row) => row.federal_declaration && row.federal_declaration.id === "EM-3631");
  assert.ok(em, "Virginia's Jan 2026 winter storm order matches EM-3631");
  assert.ok(em.noaa_match_count > 0);
});

await test("territory has no state declarations, clear message", async () => {
  const r = await get("/v1/states/PR/actions");
  assert.equal(r.status, 404);
  assert.match(r.body.error, /declarations/);
});

await test("unknown paths and states", async () => {
  assert.equal((await get("/v1/nope")).status, 404);
  assert.equal((await get("/v1/states/ZZ")).status, 404);
  assert.equal((await get("/v1/states/Virginia")).status, 404);
});

await test("rate limit answers 429 with Retry-After", async () => {
  const env = { API_RATE_LIMITER: { limit: async () => ({ success: false }) } };
  const r = await get("/v1/states", env, { "CF-Connecting-IP": "1.2.3.4" });
  assert.equal(r.status, 429);
  assert.equal(r.headers.get("retry-after"), "60");
  assert.equal((await get("/v1/health", env)).status, 200);
});

await test("site outage is a 502, not a crash", async () => {
  siteDown = true;
  const r = await get("/v1/states/TN");
  siteDown = false;
  assert.equal(r.status, 502);
});

await test("only GET", async () => {
  const res = await worker.fetch(new Request("https://api.disasterdata.io/v1/states", { method: "POST" }), {});
  assert.equal(res.status, 405);
});

await test("robots.txt is plain text", async () => {
  const res = await worker.fetch(new Request("https://api.disasterdata.io/robots.txt"), {});
  assert.equal(res.status, 200);
  assert.match(await res.text(), /User-agent: \*/);
});

console.log(`\n${passed} passed`);
