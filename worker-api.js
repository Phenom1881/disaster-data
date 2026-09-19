/**
 * DisasterData API worker (v1).
 *
 * A new, separate Worker from femaproxy. femaproxy proxies OpenFEMA's own
 * PA/HMA endpoints; this Worker serves DisasterData's own cleaned, joined
 * data (federal declarations plus state weather declarations plus NOAA
 * evidence, cross referenced) as a stable, versioned API. It reads only
 * from files this site already publishes on GitHub Pages, no database and
 * no build step of its own, so it can never drift from what a person
 * browsing disasterdata.io/plus/ actually sees.
 *
 * Mirrors the join logic in scripts/build-plus.py deliberately, field for
 * field, so a result from this API and a result on the live Plus page for
 * the same state can never disagree:
 *   - normalizedAction(): same fallback field priority as normalized_action()
 *   - findFederalMatch(): same FEDERAL_MATCH_WINDOW_DAYS=21 date-proximity
 *     rule as find_federal_match()
 *   - declaration_id: the row's own value if present, otherwise the same
 *     "<ABBR>-<action_number>-<date_signed>" fallback formula. This has to
 *     match exactly, because eo_storm_matches.csv was built by running
 *     eo_storm_join.py against a CSV that build-plus.py's own
 *     ensure_declaration_id_column() pre-populated with this exact formula
 *     whenever the source file had no declaration_id column of its own. A
 *     different formula here would silently find zero NOAA matches for
 *     every action in any state whose source CSV lacks its own
 *     declaration_id column, even though real matches exist in the file.
 *
 * If build-plus.py's FEDERAL_MATCH_WINDOW_DAYS or the declaration_id
 * fallback formula ever changes, change them here too, or this API's
 * crosswalk will quietly stop agreeing with the site's own generated pages.
 *
 * KNOWN GAP, ported from build-plus.py's own render tables and not yet
 * fixed here either: build-plus.py's federal_declaration_rows()/
 * noaa_event_rows() cap their HTML tables at 200/300 rows while the count
 * badge next to them shows the true uncapped total, so a state with more
 * records than the cap shows a badge that disagrees with its own table.
 * This Worker does NOT cap crosswalk rows or the federal/NOAA arrays it
 * returns (a JSON API has no reason to truncate the way an HTML table
 * does), so it does not reproduce that specific bug, but it is worth fixing
 * on the page side too since the two are meant to describe the same data.
 *
 * ASSUMPTION THAT NEEDS VERIFYING BEFORE THIS GOES LIVE: this Worker fetches
 * plus/<slug>/<action csv> and plus/<slug>/<matches csv> directly from the
 * live site (https://www.disasterdata.io/plus/<slug>/...csv). That only
 * works if those CSV files are actually included in the GitHub Pages build
 * output. If .gitignore or the Pages build excludes CSVs from plus/, these
 * fetches will 404 and every crosswalk response will come back with that
 * state's action list empty even though the real data exists in the repo.
 * Confirm by requesting one of these URLs directly in a browser before
 * wiring this up to anything real:
 *   https://www.disasterdata.io/plus/virginia/declarations_for_join_2002_present.csv
 *   https://www.disasterdata.io/plus/virginia/eo_storm_matches.csv
 *
 * Deploy as its own Worker (recommended, since its purpose and its data
 * source are both unrelated to femaproxy's OpenFEMA proxying):
 *
 *   wrangler.toml:
 *     name = "disasterdata-api"
 *     main = "worker-api.js"
 *     compatibility_date = "2026-01-01"
 *
 *   Route it at api.disasterdata.io/* separately from femaproxy's own route.
 *
 * Rate limiting: uses Cloudflare's native Rate Limiting binding (not a
 * hand-rolled counter, so it costs nothing extra and needs no storage of
 * its own). Keyed per client IP (CF-Connecting-IP), 60 requests per 60
 * seconds by default, generous enough for normal use and a real integrator
 * doing a full state pull, but enough to stop one runaway script from
 * hammering the free tier. The binding itself is declared in wrangler.toml,
 * not here, so raising or lowering the limit is a config change, not a
 * code change. A request over the limit gets a 429 with Retry-After, not a
 * silent drop, so a well-behaved client can back off correctly.
 */

const SITE_ORIGIN = "https://www.disasterdata.io";

// Kept identical to build-plus.py's own constant of the same name.
const FEDERAL_MATCH_WINDOW_DAYS = 21;

// Mirrors scripts/plus/state-manifest.json's slug field (state name,
// lowercased, spaces replaced with hyphens). Kept as a plain map here
// rather than fetched at request time, since it changes essentially never
// and a network dependency for something this static would only add a
// failure point. If a new state's slug is ever irregular, check the real
// manifest rather than assuming this formula.
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

// Same candidate order and names as candidate_action_files() in
// build-plus.py, minus the per-state "action_files" override from the real
// manifest (this Worker does not fetch the manifest at request time, see
// note above; the state-general defaults below cover every state whose
// CSV uses the standard naming, which is all of them as of this writing).
const ACTION_CSV_CANDIDATES = (abbr) => [
  "declarations_for_join_2002_present.csv",
  "declarations_for_join.csv",
  `${abbr.toLowerCase()}_weather_emergency_actions_2002_2026.csv`,
  `${abbr.toLowerCase()}_weather_emergency_actions.csv`,
  "state_actions.csv",
];

// Same candidate order as load_storm_match_rows() in build-plus.py
// (filtered/resolved variant preferred over the raw matches file).
const STORM_MATCH_CSV_CANDIDATES = [
  "eo_storm_matches_2002_present_filtered.csv",
  "eo_storm_matches.csv",
  "matches.csv",
];

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "cache-control": "public, max-age=86400",
};

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: JSON_HEADERS,
  });
}

function errorResponse(message, status) {
  return jsonResponse({ error: message }, status);
}

/**
 * Minimal RFC 4180 CSV parser. Handles quoted fields, escaped quotes
 * ("" inside a quoted field), and commas or newlines inside quotes, which a
 * naive split(",") would break on. NOAA's own episode/event narrative
 * fields routinely contain commas, so this matters here even though a
 * simpler split would look fine on a quick test against a short row.
 * Returns an array of objects keyed by the header row.
 */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    rows.push(row);
    row = [];
  };
  while (i < text.length) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += char;
      i += 1;
      continue;
    }
    if (char === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (char === ",") {
      pushField();
      i += 1;
      continue;
    }
    if (char === "\r") {
      i += 1;
      continue;
    }
    if (char === "\n") {
      pushRow();
      i += 1;
      continue;
    }
    field += char;
    i += 1;
  }
  // Final field/row if the file doesn't end with a trailing newline.
  if (field.length > 0 || row.length > 0) {
    pushRow();
  }
  if (rows.length === 0) {
    return [];
  }
  const header = rows[0];
  return rows.slice(1)
    .filter((r) => r.length === header.length && r.some((cell) => cell !== ""))
    .map((r) => Object.fromEntries(header.map((key, idx) => [key, r[idx]])));
}

function clean(value) {
  return (value || "").toString().trim();
}

/**
 * Same fallback declaration_id formula as normalized_action() in
 * build-plus.py: the row's own declaration_id if present, otherwise
 * "<ABBR>-<action_number>-<date_signed>" joined with hyphens, skipping any
 * part that is empty.
 */
function normalizedAction(row, abbreviation) {
  const actionNumber = clean(
    row.action_number || row.eo_number || row.order_number || row.proclamation_number
  );
  const signed = clean(row.date_signed || row.issued_date || row.date);
  const title = clean(
    row.event_description || row.title || row.subject || row.short_title
  );
  const sourceUrl = clean(
    row.archive_record_url || row.source_url || row.detail_url || row.document_url
  );
  let declarationId = clean(row.declaration_id);
  if (!declarationId) {
    declarationId = [abbreviation, actionNumber, signed].filter(Boolean).join("-");
  }
  return {
    state: abbreviation,
    declaration_id: declarationId,
    action_number: actionNumber,
    title,
    date_signed: signed,
    action_type: clean(row.action_type) || "declaration",
    governor: clean(row.governor),
    source_url: sourceUrl,
  };
}

function parseIsoDate(value) {
  const text = clean(value).slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) {
    return null;
  }
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date;
}

function daysBetween(a, b) {
  return Math.round((a.getTime() - b.getTime()) / 86400000);
}

/**
 * Same date proximity rule as find_federal_match() in build-plus.py: the
 * closest federal declaration whose incident window falls within
 * FEDERAL_MATCH_WINDOW_DAYS of the action's signing date, or null if
 * nothing is close enough. This is an automated candidate match, not a
 * confirmed link, exactly as build-plus.py's own docstring says.
 */
function findFederalMatch(action, federalDeclarations) {
  const signed = parseIsoDate(action.date_signed);
  if (!signed || federalDeclarations.length === 0) {
    return null;
  }
  let best = null;
  let bestGap = null;
  for (const declaration of federalDeclarations) {
    const begin = parseIsoDate(declaration.begin) || parseIsoDate(declaration.date);
    const end = parseIsoDate(declaration.end) || begin;
    if (!begin) {
      continue;
    }
    const windowStart = new Date(begin.getTime() - FEDERAL_MATCH_WINDOW_DAYS * 86400000);
    const windowEnd = new Date(end.getTime() + FEDERAL_MATCH_WINDOW_DAYS * 86400000);
    if (signed >= windowStart && signed <= windowEnd) {
      const gap = Math.min(Math.abs(daysBetween(signed, begin)), Math.abs(daysBetween(signed, end)));
      if (bestGap === null || gap < bestGap) {
        best = declaration;
        bestGap = gap;
      }
    }
  }
  return best;
}

async function fetchFirstOk(urls) {
  for (const url of urls) {
    const response = await fetch(url, { cf: { cacheTtl: 3600, cacheEverything: true } });
    if (response.ok) {
      return { url, text: await response.text() };
    }
  }
  return null;
}

async function fetchJson(url) {
  const response = await fetch(url, { cf: { cacheTtl: 3600, cacheEverything: true } });
  if (!response.ok) {
    return null;
  }
  try {
    return await response.json();
  } catch (err) {
    return null;
  }
}

async function loadFederalDeclarations(abbreviation) {
  const payload = await fetchJson(`${SITE_ORIGIN}/data/decl-index/${abbreviation.toUpperCase()}.json`);
  if (!payload) {
    return [];
  }
  const records = Array.isArray(payload) ? payload : payload.declarations || [];
  return records;
}

async function loadStateActions(abbreviation, slug) {
  const urls = ACTION_CSV_CANDIDATES(abbreviation).map((name) => `${SITE_ORIGIN}/plus/${slug}/${name}`);
  const found = await fetchFirstOk(urls);
  if (!found) {
    return { actions: [], sourceUrl: null };
  }
  const rows = parseCsv(found.text).map((row) => normalizedAction(row, abbreviation));
  const unique = new Map();
  for (const row of rows) {
    unique.set(row.declaration_id || JSON.stringify(row), row);
  }
  const actions = Array.from(unique.values()).sort((a, b) =>
    (b.date_signed || "").localeCompare(a.date_signed || "")
  );
  return { actions, sourceUrl: found.url };
}

async function loadStormMatches(slug) {
  const urls = STORM_MATCH_CSV_CANDIDATES.map((name) => `${SITE_ORIGIN}/plus/${slug}/${name}`);
  const found = await fetchFirstOk(urls);
  if (!found) {
    return { rows: [], sourceUrl: null };
  }
  return { rows: parseCsv(found.text), sourceUrl: found.url };
}

function groupByDeclaration(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const key = clean(row.declaration_id);
    if (!key) {
      continue;
    }
    if (!grouped.has(key)) {
      grouped.set(key, []);
    }
    grouped.get(key).push(row);
  }
  return grouped;
}

function buildCrosswalk(actions, federalDeclarations, stormRowsByDeclaration) {
  return actions.map((action) => {
    const matches = stormRowsByDeclaration.get(action.declaration_id) || [];
    const areas = Array.from(
      new Set(matches.map((row) => clean(row.CZ_NAME)).filter(Boolean))
    ).sort();
    const federal = findFederalMatch(action, federalDeclarations);
    return {
      state_action: action,
      noaa_match_count: matches.length,
      noaa_areas: areas,
      federal_declaration: federal,
      federal_status: federal ? "matched" : "no_federal_declaration_found",
    };
  });
}

async function handleCrosswalk(abbreviationRaw) {
  const abbreviation = abbreviationRaw.toUpperCase();
  const slug = STATE_SLUGS[abbreviation];
  if (!slug) {
    return errorResponse(`Unknown state abbreviation: ${abbreviationRaw}`, 404);
  }

  const [federalDeclarations, actionResult, stormResult] = await Promise.all([
    loadFederalDeclarations(abbreviation),
    loadStateActions(abbreviation, slug),
    loadStormMatches(slug),
  ]);

  const stormRowsByDeclaration = groupByDeclaration(stormResult.rows);
  const crosswalk = buildCrosswalk(actionResult.actions, federalDeclarations, stormRowsByDeclaration);

  return jsonResponse({
    state: abbreviation,
    slug,
    generated_at: new Date().toISOString(),
    federal_match_window_days: FEDERAL_MATCH_WINDOW_DAYS,
    counts: {
      federal_declarations: federalDeclarations.length,
      state_actions: actionResult.actions.length,
      noaa_match_rows: stormResult.rows.length,
    },
    sources: {
      federal_declarations: `${SITE_ORIGIN}/data/decl-index/${abbreviation}.json`,
      state_actions: actionResult.sourceUrl,
      noaa_matches: stormResult.sourceUrl,
    },
    note:
      "federal_declaration is an automated date-proximity candidate match, " +
      "not a confirmed legal link. A null federal_declaration with " +
      "federal_status 'no_federal_declaration_found' is an explicit result, " +
      "not a missing value.",
    crosswalk,
  });
}

async function handleStateActions(abbreviationRaw) {
  const abbreviation = abbreviationRaw.toUpperCase();
  const slug = STATE_SLUGS[abbreviation];
  if (!slug) {
    return errorResponse(`Unknown state abbreviation: ${abbreviationRaw}`, 404);
  }
  const { actions, sourceUrl } = await loadStateActions(abbreviation, slug);
  return jsonResponse({
    state: abbreviation,
    slug,
    generated_at: new Date().toISOString(),
    count: actions.length,
    source: sourceUrl,
    actions,
  });
}

async function handleFederalDeclarations(abbreviationRaw) {
  const abbreviation = abbreviationRaw.toUpperCase();
  if (!STATE_SLUGS[abbreviation]) {
    return errorResponse(`Unknown state abbreviation: ${abbreviationRaw}`, 404);
  }
  const declarations = await loadFederalDeclarations(abbreviation);
  return jsonResponse({
    state: abbreviation,
    generated_at: new Date().toISOString(),
    count: declarations.length,
    source: `${SITE_ORIGIN}/data/decl-index/${abbreviation}.json`,
    declarations,
  });
}

async function handleStateSummary(abbreviationRaw) {
  const abbreviation = abbreviationRaw.toUpperCase();
  const slug = STATE_SLUGS[abbreviation];
  if (!slug) {
    return errorResponse(`Unknown state abbreviation: ${abbreviationRaw}`, 404);
  }
  const [federalDeclarations, actionResult, stormResult] = await Promise.all([
    loadFederalDeclarations(abbreviation),
    loadStateActions(abbreviation, slug),
    loadStormMatches(slug),
  ]);
  return jsonResponse({
    state: abbreviation,
    slug,
    generated_at: new Date().toISOString(),
    counts: {
      federal_declarations: federalDeclarations.length,
      state_actions: actionResult.actions.length,
      noaa_match_rows: stormResult.rows.length,
    },
    sources: {
      federal_declarations: `${SITE_ORIGIN}/data/decl-index/${abbreviation}.json`,
      state_actions: actionResult.sourceUrl,
      noaa_matches: stormResult.sourceUrl,
    },
    links: {
      declarations: `/v1/states/${abbreviation}/declarations`,
      actions: `/v1/states/${abbreviation}/actions`,
      crosswalk: `/v1/states/${abbreviation}/crosswalk`,
      site_page: `${SITE_ORIGIN}/plus/${slug}/`,
    },
  });
}

/**
 * Applies the Rate Limiting binding, if one is configured, and returns a
 * 429 Response when the caller is over the limit, or null when the request
 * may proceed. Keyed per client IP so one noisy caller cannot exhaust the
 * limit for everyone else. If the binding is missing (e.g. running under
 * `wrangler dev` without ratelimits configured, or a deploy that hasn't
 * added it yet), this skips the check rather than failing the request,
 * since an unconfigured limiter is a deploy-config gap, not a reason to
 * take the whole API down.
 */
async function enforceRateLimit(request, env) {
  const limiter = env && env.API_RATE_LIMITER;
  if (!limiter) {
    return null;
  }
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const { success } = await limiter.limit({ key: ip });
  if (success) {
    return null;
  }
  return jsonResponse(
    {
      error: "Rate limit exceeded. Please slow down and retry shortly.",
    },
    429
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
        },
      });
    }

    if (path === "/v1/health") {
      return jsonResponse({ status: "ok" });
    }

    const limited = await enforceRateLimit(request, env);
    if (limited) {
      return limited;
    }

    let match;

    match = /^\/v1\/states\/([A-Za-z]{2})$/.exec(path);
    if (match) {
      return handleStateSummary(match[1]);
    }

    match = /^\/v1\/states\/([A-Za-z]{2})\/declarations$/.exec(path);
    if (match) {
      return handleFederalDeclarations(match[1]);
    }

    match = /^\/v1\/states\/([A-Za-z]{2})\/actions$/.exec(path);
    if (match) {
      return handleStateActions(match[1]);
    }

    match = /^\/v1\/states\/([A-Za-z]{2})\/crosswalk$/.exec(path);
    if (match) {
      return handleCrosswalk(match[1]);
    }

    return errorResponse("Not found", 404);
  },
};
