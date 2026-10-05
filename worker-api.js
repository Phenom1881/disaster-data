/**
 * DisasterData API worker (v1), served at
 * https://disasterdata-api.disasterdata.workers.dev (api.disasterdata.io once
 * the domain is added to the Cloudflare account; see wrangler.toml).
 *
 * A separate Worker from femaproxy (worker.js), which proxies OpenFEMA's own
 * endpoints. This one serves DisasterData's own cleaned and joined data as a
 * stable, versioned, read-only JSON API.
 *
 * It has no database and no join logic of its own. Every response is read
 * from files the weekly builds already publish on the site:
 *
 *   data/decl-index/<ST>.json      federal declarations per state, with the
 *                                  counties each one names ("gen decl index.py")
 *   data/decl-index/manifest.json  which states and territories have one
 *   plus/coverage.json             every Plus state's counts and coverage note
 *   plus/<slug>/api.json           a state's own weather declarations and the
 *                                  crosswalk to federal declarations and NOAA
 *                                  storm reports, written by build-plus.py from
 *                                  the same data it renders the state page from
 *
 * So the API can never disagree with the site. An earlier draft re-implemented
 * build-plus.py's join here and had already drifted from it (it looked for
 * CSV names the manifest no longer uses); reading api.json removes that risk.
 *
 * Rate limiting uses Cloudflare's native Rate Limiting binding declared in
 * wrangler.toml (60 requests per minute per client IP by default).
 */

const SITE_ORIGIN = "https://www.disasterdata.io";
const API_VERSION = "v1";

const ATTRIBUTION =
  "DisasterData.IO, from OpenFEMA, NOAA NCEI Storm Events and state government sources. " +
  "Not endorsed by or affiliated with FEMA or NOAA.";

// Plus state pages, by postal abbreviation. Same slugs as
// scripts/plus/state-manifest.json (50 states; territories have federal data only).
const STATE_SLUGS = {
  AL: "alabama", AK: "alaska", AZ: "arizona", AR: "arkansas", CA: "california",
  CO: "colorado", CT: "connecticut", DE: "delaware", FL: "florida", GA: "georgia",
  HI: "hawaii", ID: "idaho", IL: "illinois", IN: "indiana", IA: "iowa",
  KS: "kansas", KY: "kentucky", LA: "louisiana", ME: "maine", MD: "maryland",
  MA: "massachusetts", MI: "michigan", MN: "minnesota", MS: "mississippi",
  MO: "missouri", MT: "montana", NE: "nebraska", NV: "nevada",
  NH: "new-hampshire", NJ: "new-jersey", NM: "new-mexico", NY: "new-york",
  NC: "north-carolina", ND: "north-dakota", OH: "ohio", OK: "oklahoma",
  OR: "oregon", PA: "pennsylvania", RI: "rhode-island", SC: "south-carolina",
  SD: "south-dakota", TN: "tennessee", TX: "texas", UT: "utah", VT: "vermont",
  VA: "virginia", WA: "washington", WV: "west-virginia", WI: "wisconsin",
  WY: "wyoming",
};

// State FIPS code to postal abbreviation, for /v1/counties/<fips>.
const FIPS_STATES = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
  "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
  "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
  "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
  "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
  "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
  "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
  "55": "WI", "56": "WY", "60": "AS", "64": "FM", "66": "GU", "68": "MH", "69": "MP",
  "70": "PW", "72": "PR", "78": "VI",
};

const BASE_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "x-api-version": API_VERSION,
};

// The data changes once a week, so responses can be cached for an hour at
// the edge and by clients without anyone seeing stale data for long.
const CACHE_SECONDS = 3600;

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function json(payload, status = 200, extraHeaders = {}) {
  const headers = { ...BASE_HEADERS, ...extraHeaders };
  if (status === 200) headers["cache-control"] = `public, max-age=${CACHE_SECONDS}`;
  return new Response(JSON.stringify(payload, null, 2), { status, headers });
}

function errorResponse(status, message) {
  return json({ api_version: API_VERSION, error: message, status }, status);
}

async function siteJson(path) {
  let response;
  try {
    response = await fetch(`${SITE_ORIGIN}/${path}`, {
      cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
    });
  } catch (err) {
    throw new ApiError(502, `Could not reach the site for ${path}.`);
  }
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ApiError(502, `The site answered ${response.status} for ${path}.`);
  }
  try {
    return await response.json();
  } catch (err) {
    throw new ApiError(502, `The site returned unreadable JSON for ${path}.`);
  }
}

function envelope(fields, sources) {
  return {
    api_version: API_VERSION,
    ...fields,
    sources: sources.map((path) => `${SITE_ORIGIN}/${path}`),
    attribution: ATTRIBUTION,
  };
}

function stateCode(raw) {
  const code = String(raw || "").toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) throw new ApiError(404, `Unknown state: ${raw}`);
  return code;
}

// ------------------------------------------------------------ federal data

async function federalIndex(code) {
  const index = await siteJson(`data/decl-index/${code}.json`);
  if (!index) throw new ApiError(404, `No federal declarations are published for ${code}.`);
  return index;
}

function withFemaId(declaration, code) {
  // decl-index ids omit the state ("DR-4898"); FEMA's own string adds it.
  return { fema_id: `${declaration.id}-${code}`, ...declaration };
}

function filterDeclarations(declarations, params) {
  const type = (params.get("type") || "").toUpperCase();
  const since = params.get("since") || "";
  const until = params.get("until") || "";
  for (const [name, value] of [["since", since], ["until", until]]) {
    if (value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new ApiError(400, `${name} must be a date written YYYY-MM-DD.`);
    }
  }
  if (type && !["DR", "EM", "FM"].includes(type)) {
    throw new ApiError(400, "type must be DR, EM or FM.");
  }
  return declarations.filter(
    (d) =>
      (!type || d.type === type) &&
      (!since || (d.date || "") >= since) &&
      (!until || (d.date || "") <= until)
  );
}

function newestFirst(a, b) {
  return (b.date || "").localeCompare(a.date || "");
}

async function stateDeclarations(code, params) {
  const index = await federalIndex(code);
  const declarations = filterDeclarations(index.declarations || [], params)
    .sort(newestFirst)
    .map((d) => withFemaId(d, code));
  return envelope(
    {
      state: code,
      data_date: index.generated || null,
      filters: Object.fromEntries(["type", "since", "until"].filter((k) => params.get(k)).map((k) => [k, params.get(k)])),
      count: declarations.length,
      note: "fips lists every county or equivalent the declaration names. statewide is true when FEMA designated the whole state.",
      declarations,
    },
    [`data/decl-index/${code}.json`]
  );
}

async function oneDeclaration(raw) {
  const match = /^(DR|EM|FM)-(\d+)-([A-Z]{2})$/.exec(String(raw).toUpperCase());
  if (!match) throw new ApiError(400, "Write a declaration as FEMA does, for example DR-4898-TN.");
  const [, type, number, code] = match;
  const index = await federalIndex(code);
  const found = (index.declarations || []).find((d) => d.id === `${type}-${Number(number)}`);
  if (!found) throw new ApiError(404, `${raw.toUpperCase()} is not in the published data.`);
  const names = Object.fromEntries((index.jurisdictions || []).map((j) => [j.fips, `${j.name} ${j.type || ""}`.trim()]));
  return envelope(
    {
      data_date: index.generated || null,
      declaration: {
        ...withFemaId(found, code),
        areas: (found.fips || []).map((fips) => ({ fips, name: names[fips] || null })),
      },
    },
    [`data/decl-index/${code}.json`]
  );
}

async function countyDeclarations(fips, params) {
  if (!/^\d{5}$/.test(fips)) throw new ApiError(400, "A county is five FIPS digits, for example 51770.");
  const code = FIPS_STATES[fips.slice(0, 2)];
  if (!code) throw new ApiError(404, `No state or territory has FIPS code ${fips.slice(0, 2)}.`);
  const index = await federalIndex(code);
  const place = (index.jurisdictions || []).find((j) => j.fips === fips) || null;
  const naming = (index.declarations || []).filter(
    (d) => d.statewide || (d.fips || []).includes(fips)
  );
  const declarations = filterDeclarations(naming, params)
    .sort(newestFirst)
    .map(({ fips: _all, ...rest }) => ({
      ...withFemaId(rest, code),
      designated: rest.statewide ? "statewide" : "county",
    }));
  if (!place && declarations.length === 0) {
    throw new ApiError(404, `No federal declarations name county ${fips}.`);
  }
  return envelope(
    {
      fips,
      state: code,
      name: place ? `${place.name} ${place.type || ""}`.trim() : null,
      data_date: index.generated || null,
      count: declarations.length,
      note: "Includes statewide declarations, which name every county in the state.",
      declarations,
    },
    [`data/decl-index/${code}.json`]
  );
}

// ------------------------------------------------------------ state (Plus) data

async function plusFile(code) {
  const slug = STATE_SLUGS[code];
  if (!slug) {
    throw new ApiError(404, `${code} has no state declaration data; federal data is at /v1/states/${code}/declarations.`);
  }
  const data = await siteJson(`plus/${slug}/api.json`);
  if (!data) throw new ApiError(503, `State declaration data for ${code} is not published yet.`);
  return { slug, data };
}

function plusMeta(code, slug, data) {
  return {
    state: code,
    name: data.name,
    generated_on: data.generated_on,
    coverage: data.coverage,
    official_source_url: data.official_source_url,
    site_page: `${SITE_ORIGIN}/plus/${slug}/`,
  };
}

async function stateActions(code) {
  const { slug, data } = await plusFile(code);
  return envelope(
    { ...plusMeta(code, slug, data), count: data.actions.length, actions: data.actions },
    [`plus/${slug}/api.json`]
  );
}

async function stateCrosswalk(code) {
  const { slug, data } = await plusFile(code);
  return envelope(
    {
      ...plusMeta(code, slug, data),
      federal_match_window_days: data.federal_match_window_days,
      count: data.crosswalk.length,
      note:
        "federal_declaration is an automated candidate: the closest federal declaration whose " +
        `incident period is within ${data.federal_match_window_days} days of the state signing date. ` +
        "It is not a confirmed legal link. federal_status no_federal_declaration_found is a result, " +
        "not missing data. noaa_areas are NOAA Storm Events zones and counties matched to the declaration.",
      crosswalk: data.crosswalk,
    },
    [`plus/${slug}/api.json`]
  );
}

async function stateSummary(code) {
  const [index, coverage] = await Promise.all([
    federalIndex(code),
    STATE_SLUGS[code] ? siteJson("plus/coverage.json") : Promise.resolve(null),
  ]);
  const plus = coverage ? (coverage.states || []).find((s) => s.abbreviation === code) : null;
  const decls = index.declarations || [];
  const byType = { DR: 0, EM: 0, FM: 0 };
  for (const d of decls) byType[d.type] = (byType[d.type] || 0) + 1;
  const links = { declarations: `/v1/states/${code}/declarations` };
  if (plus) {
    links.actions = `/v1/states/${code}/actions`;
    links.crosswalk = `/v1/states/${code}/crosswalk`;
    links.site_page = `${SITE_ORIGIN}/plus/${plus.slug}/`;
  }
  return envelope(
    {
      state: code,
      name: plus ? plus.name : null,
      data_date: index.generated || null,
      federal: {
        declarations: decls.length,
        by_type: byType,
        jurisdictions: (index.jurisdictions || []).length,
        latest: decls.slice().sort(newestFirst).slice(0, 1).map((d) => withFemaId(d, code))[0] || null,
      },
      state_declarations: plus
        ? {
            count: plus.metrics ? plus.metrics.action_count : null,
            noaa_match_rows: plus.metrics ? plus.metrics.storm_match_rows : null,
            coverage: plus.coverage,
            generated_on: plus.generated_on,
          }
        : null,
      links,
    },
    [`data/decl-index/${code}.json`].concat(plus ? ["plus/coverage.json"] : [])
  );
}

async function stateList() {
  const [manifest, coverage] = await Promise.all([
    siteJson("data/decl-index/manifest.json"),
    siteJson("plus/coverage.json"),
  ]);
  const plus = Object.fromEntries(((coverage && coverage.states) || []).map((s) => [s.abbreviation, s]));
  const states = ((manifest && manifest.states) || []).map((s) => ({
    state: s.state,
    name: plus[s.state] ? plus[s.state].name : null,
    federal_declarations: s.declarations,
    jurisdictions: s.jurisdictions,
    state_declarations: plus[s.state] && plus[s.state].metrics ? plus[s.state].metrics.action_count : null,
    href: `/v1/states/${s.state}`,
  }));
  return envelope(
    { data_date: manifest ? manifest.generated : null, count: states.length, states },
    ["data/decl-index/manifest.json", "plus/coverage.json"]
  );
}

function apiIndex() {
  return {
    api_version: API_VERSION,
    name: "DisasterData API",
    documentation: `${SITE_ORIGIN}/about.html#api`,
    rate_limit: "60 requests per minute per IP address",
    updated: "Weekly, with the site",
    endpoints: {
      "/v1/states": "Every state and territory with counts",
      "/v1/states/{ST}": "One state's federal and state declaration summary",
      "/v1/states/{ST}/declarations": "Federal declarations, with counties named. Filters: type=DR|EM|FM, since=YYYY-MM-DD, until=YYYY-MM-DD",
      "/v1/states/{ST}/actions": "The state's own weather emergency declarations (50 states)",
      "/v1/states/{ST}/crosswalk": "Each state declaration with its candidate federal declaration and matched NOAA storm areas",
      "/v1/declarations/{DR-4898-TN}": "One federal declaration and the areas it names",
      "/v1/counties/{FIPS}": "Federal declarations naming one county, including statewide ones. Same filters",
      "/v1/health": "Service check",
    },
    attribution: ATTRIBUTION,
  };
}

// ------------------------------------------------------------ routing

async function enforceRateLimit(request, env) {
  const limiter = env && env.API_RATE_LIMITER;
  if (!limiter) return null; // unconfigured (local dev): never block
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const { success } = await limiter.limit({ key: ip });
  if (success) return null;
  return json(
    { api_version: API_VERSION, error: "Rate limit exceeded. Wait a minute and retry.", status: 429 },
    429,
    { "retry-after": "60" }
  );
}

async function route(path, params) {
  if (path === "/" || path === "/v1") return apiIndex();
  if (path === "/v1/health") return { api_version: API_VERSION, status: "ok" };
  if (path === "/v1/states") return stateList();

  let m;
  if ((m = /^\/v1\/states\/([^/]+)$/.exec(path))) return stateSummary(stateCode(m[1]));
  if ((m = /^\/v1\/states\/([^/]+)\/declarations$/.exec(path))) return stateDeclarations(stateCode(m[1]), params);
  if ((m = /^\/v1\/states\/([^/]+)\/actions$/.exec(path))) return stateActions(stateCode(m[1]));
  if ((m = /^\/v1\/states\/([^/]+)\/crosswalk$/.exec(path))) return stateCrosswalk(stateCode(m[1]));
  if ((m = /^\/v1\/declarations\/([^/]+)$/.exec(path))) return oneDeclaration(decodeURIComponent(m[1]));
  if ((m = /^\/v1\/counties\/([^/]+)$/.exec(path))) return countyDeclarations(m[1], params);
  throw new ApiError(404, "Not found. See / for the list of endpoints.");
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
          "access-control-max-age": "86400",
        },
      });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return errorResponse(405, "Only GET is supported.");
    }
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (path !== "/v1/health") {
      const limited = await enforceRateLimit(request, env);
      if (limited) return limited;
    }
    try {
      return json(await route(path, url.searchParams));
    } catch (err) {
      if (err instanceof ApiError) return errorResponse(err.status, err.message);
      return errorResponse(500, "Unexpected error.");
    }
  },
};
