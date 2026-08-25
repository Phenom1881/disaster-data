"""
build.py
Fetches live data from the FEMA OpenFEMA API, processes it,
and writes a self-contained index.html dashboard.

Run locally:  python build.py
Run in CI:    same command — GitHub Actions uses this directly.
"""

import json
import time
import os
import datetime
import urllib.request
import urllib.parse
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────────
API_ROOT   = "https://www.fema.gov/api/open"
BASE_URL   = f"{API_ROOT}/v2"   # most datasets are v2
START_YEAR = 2000          # filter records from this fiscal year forward
PAGE_SIZE  = 5000          # records per page (moderate, so a dropped transfer retries cheaply)
SLEEP_SEC  = 0.5           # polite pause between paginated requests
TODAY      = datetime.date.today().isoformat()

# Federal fiscal year: Oct 1 – Sep 30.  If we're in Oct–Dec, FY = calendar year + 1.
_today      = datetime.date.today()
CURRENT_FY  = _today.year if _today.month < 10 else _today.year + 1


# ═════════════════════════════════════════════════════════════════════════
# 1. FETCH FROM API
# ═════════════════════════════════════════════════════════════════════════

def fetch_all(endpoint, extra_filter="", fields=None, version="v2"):
    """Page through an OpenFEMA endpoint and return all records."""
    records = []
    skip    = 0
    total   = None
    base_filter = f"fyDeclared ge {START_YEAR}" if endpoint == "DisasterDeclarationsSummaries" else f"declarationRequestDate ge '{START_YEAR}-01-01T00:00:00.000Z'"

    filt = base_filter
    if extra_filter:
        filt = f"{base_filter} and {extra_filter}"

    select_param = ""
    if fields:
        select_param = "&$select=" + ",".join(fields)

    print(f"  Fetching {endpoint}...")

    while True:
        params = (
            f"?$top={PAGE_SIZE}"
            f"&$skip={skip}"
            f"&$filter={urllib.parse.quote(filt)}"
            f"&$inlinecount=allpages"
            f"&$orderby=id%20asc"
            + select_param
        )
        url = f"{API_ROOT}/{version}/{endpoint}{params}"

        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "UWSWVA-FEMA-Explorer/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                break
            except Exception as e:
                if attempt == 4:
                    raise
                wait = 10 * (attempt + 1)
                print(f"    Retry {attempt+1}/4 after error: {e} (waiting {wait}s)")
                time.sleep(wait)

        batch = data.get(endpoint, [])
        records.extend(batch)

        if total is None:
            total = int(data.get("metadata", {}).get("count", 0))
            print(f"    Total records: {total}")

        skip += len(batch)
        print(f"    Fetched {skip}/{total}")

        if not batch or (total and skip >= total):
            break
        time.sleep(SLEEP_SEC)

    return records


# Declarations — only fields we need
DEC_FIELDS = [
    "femaDeclarationString", "disasterNumber", "state", "declarationType",
    "declarationDate", "fyDeclared", "incidentType", "declarationTitle",
    "incidentBeginDate", "designatedArea", "tribalRequest", "region", "id",
    "fipsStateCode", "fipsCountyCode"
]

# Denials — only fields we need
DEN_FIELDS = [
    "declarationRequestNumber", "stateAbbreviation", "state",
    "declarationRequestType", "incidentName", "requestedIncidentTypes",
    "declarationRequestDate", "requestStatusDate", "currentRequestStatus",
    "region", "id"
]

print("Fetching declarations...")
try:
    raw_dec = fetch_all("DisasterDeclarationsSummaries", fields=DEC_FIELDS)
    print(f"  → {len(raw_dec)} declaration records\n")
except Exception as e:
    print(f"  ERROR: Declarations fetch failed after retries: {e}")
    print("  Cannot continue without declarations data — exiting.")
    raise SystemExit(1)

print("Fetching denials...")
raw_den = []
try:
    # Declaration Denials is a v1-ONLY dataset — must not be requested from v2.
    raw_den = fetch_all("DeclarationDenials", extra_filter="currentRequestStatus eq 'Turndown'", fields=DEN_FIELDS, version="v1")
    print(f"  → {len(raw_den)} denial records (Turndown filter)")
    if not raw_den:
        # Filter matched nothing (e.g. status value changed) — pull all denials instead.
        print("  Turndown filter returned 0 — fetching all denials...")
        raw_den = fetch_all("DeclarationDenials", fields=DEN_FIELDS, version="v1")
        print(f"  → {len(raw_den)} denial records (unfiltered)\n")
    else:
        print()
except Exception as e:
    print(f"  WARNING: Denials fetch failed: {e}")
    print("  Trying without status filter...")
    try:
        raw_den = fetch_all("DeclarationDenials", fields=DEN_FIELDS, version="v1")
        print(f"  → {len(raw_den)} denial records\n")
    except Exception as e2:
        print(f"  WARNING: Denials unavailable: {e2}\n")
        raw_den = []


# ═════════════════════════════════════════════════════════════════════════
# 2. PROCESS DATA
# ═════════════════════════════════════════════════════════════════════════

def parse_date(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None

def days_between(d1, d2):
    if d1 and d2:
        delta = (d2 - d1).days
        return delta if delta >= 0 else None
    return None

def safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


print("Processing declarations...")
dec_processed = []
for r in raw_dec:
    fy = safe_int(r.get("fyDeclared"))
    if not fy or fy < START_YEAR or fy > CURRENT_FY:
        continue
    dec_date    = parse_date(r.get("declarationDate"))
    begin_date  = parse_date(r.get("incidentBeginDate"))
    days_app    = days_between(begin_date, dec_date)
    dec_processed.append({
        "femaDeclarationString": r.get("femaDeclarationString", ""),
        "state":                 r.get("state", ""),
        "declarationType":       r.get("declarationType", ""),
        "declarationDate":       dec_date.isoformat() if dec_date else "",
        "fyDeclared":            fy,
        "incidentType":          r.get("incidentType", ""),
        "declarationTitle":      r.get("declarationTitle", ""),
        "designatedArea":        r.get("designatedArea", ""),
        "tribalRequest":         1 if r.get("tribalRequest") in (True, 1, "true", "True", "1") else 0,
        "region":                r.get("region"),
        "days_to_approve":       days_app if days_app is not None else -1,
    })

print(f"  → {len(dec_processed)} processed\n")

print("Processing denials...")
den_processed = []
for r in raw_den:
    req_date = parse_date(r.get("declarationRequestDate"))
    sta_date = parse_date(r.get("requestStatusDate"))
    days_den = days_between(req_date, sta_date)
    state_ab = (r.get("stateAbbreviation") or "").strip()
    den_processed.append({
        "declarationRequestNumber": str(r.get("declarationRequestNumber", "")),
        "stateAbbreviation":        state_ab,
        "declarationRequestType":   r.get("declarationRequestType", ""),
        "requestedIncidentTypes":   r.get("requestedIncidentTypes", ""),
        "declarationRequestDate":   req_date.isoformat() if req_date else "",
        "requestStatusDate":        sta_date.isoformat() if sta_date else "",
        "currentRequestStatus":     r.get("currentRequestStatus", ""),
        "region":                   r.get("region"),
        "days_to_deny":             days_den if days_den is not None else -1,
    })

print(f"  → {len(den_processed)} processed\n")



# ═════════════════════════════════════════════════════════════════════════
# 2b. FETCH PUBLIC ASSISTANCE NATIONAL SUMMARY
# ═════════════════════════════════════════════════════════════════════════

PA_BASE    = "https://www.fema.gov/api/open/v2"
PA_FIELDS  = [
    "disasterNumber", "stateAbbreviation", "federalShareObligated",
    "totalObligated", "damageCategoryCode", "damageCategoryDescrip",
    "declarationDate", "incidentType", "county"
]

def fetch_pa_all():
    """Fetch all PA funded projects details (2000+) for national summary."""
    records = []
    skip    = 0
    total   = None
    filt    = urllib.parse.quote("declarationDate ge '2000-01-01T00:00:00.000Z'")
    select  = ",".join(PA_FIELDS)
    print("  Fetching PublicAssistanceFundedProjectsDetails (national)...")

    while True:
        url = (f"{PA_BASE}/PublicAssistanceFundedProjectsDetails"
               f"?$top={PAGE_SIZE}&$skip={skip}"
               f"&$filter={filt}"
               f"&$select={select}"
               f"&$inlinecount=allpages")

        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "DisasterData-Explorer/1.0"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read())
                break
            except Exception as e:
                if attempt == 4:
                    raise
                wait = 10 * (attempt + 1)
                print(f"    Retry {attempt+1}/4: {e} (waiting {wait}s)")
                time.sleep(wait)

        batch = data.get("PublicAssistanceFundedProjectsDetails", [])
        records.extend(batch)

        if total is None:
            total = int(data.get("metadata", {}).get("count", 0))
            print(f"    Total PA records: {total:,}")

        skip += len(batch)
        if skip % 50000 == 0 or skip >= total:
            print(f"    Fetched {skip:,}/{total:,}")

        if not batch or (total and skip >= total):
            break
        time.sleep(SLEEP_SEC)

    return records

print("Fetching PA data (this may take several minutes)...")
try:
    raw_pa = fetch_pa_all()
    print(f"  → {len(raw_pa):,} PA project records\n")
    PA_AVAILABLE = True
except Exception as e:
    print(f"  WARNING: PA fetch failed: {e}")
    print("  PA national summary will be skipped.\n")
    raw_pa = []
    PA_AVAILABLE = False

# Build PA national summary aggregates
pa_national = {}
pa_county_out = {}
if raw_pa:
    pa_by_state   = {}
    pa_by_cat     = {}
    pa_by_disaster = {}
    pa_by_year    = {}
    pa_state_dis  = {}   # state -> {disasterNumber -> {obl, proj, inc, year}} (drill-down)
    pa_by_county  = {}   # state -> {county_name -> {obl, proj, cats:{code:obl}}} (jurisdiction pages)

    # disasterNumber -> declaration title (from declarations fetched earlier)
    dn_title = {}
    for _d in raw_dec:
        _dn = _d.get("disasterNumber")
        if _dn is not None and _dn not in dn_title:
            dn_title[_dn] = (_d.get("declarationTitle") or "").strip()
    pa_total_obl  = 0
    pa_total_proj = 0
    pa_disasters  = set()

    DCC_LABELS = {
        "A":"Debris Removal","B":"Emergency Protective Measures",
        "C":"Roads & Bridges","D":"Water Control Facilities",
        "E":"Buildings & Equipment","F":"Utilities",
        "G":"Parks, Recreational, and Other Items","Z":"Management Costs"
    }

    for r in raw_pa:
        st   = r.get("stateAbbreviation") or "Unknown"
        obl  = float(r.get("federalShareObligated") or 0)
        tot  = float(r.get("totalObligated") or 0)
        code = (r.get("damageCategoryCode") or "?").strip().upper()
        dn   = r.get("disasterNumber")
        yr   = (r.get("declarationDate") or "")[:4]

        pa_total_obl  += obl
        pa_total_proj += 1
        if dn: pa_disasters.add(dn)

        if st not in pa_by_state:
            pa_by_state[st] = {"obl": 0, "tot": 0, "proj": 0}
        pa_by_state[st]["obl"]  += obl
        pa_by_state[st]["tot"]  += tot
        pa_by_state[st]["proj"] += 1

        if code not in pa_by_cat:
            pa_by_cat[code] = {"obl": 0, "proj": 0}
        pa_by_cat[code]["obl"]  += obl
        pa_by_cat[code]["proj"] += 1

        if yr.isdigit():
            pa_by_year[yr] = pa_by_year.get(yr, 0) + obl

        if dn is not None:
            if dn not in pa_by_disaster:
                pa_by_disaster[dn] = {"obl": 0, "proj": 0,
                                      "inc": r.get("incidentType") or "",
                                      "year": yr if yr.isdigit() else ""}
            pa_by_disaster[dn]["obl"]  += obl
            pa_by_disaster[dn]["proj"] += 1

            # per-state disaster rollup (powers state → disasters drill-down)
            _sd = pa_state_dis.setdefault(st, {})
            _e  = _sd.get(dn)
            if _e is None:
                _e = _sd[dn] = {"obl": 0, "proj": 0,
                                "inc": r.get("incidentType") or "",
                                "year": yr if yr.isdigit() else ""}
            _e["obl"]  += obl
            _e["proj"] += 1

        # per-state per-county rollup (powers jurisdiction PA cards + category breakdown)
        cty = (r.get("county") or "").strip()
        if cty and cty.lower() != "statewide":
            _sc = pa_by_county.setdefault(st, {})
            _ce = _sc.get(cty)
            if _ce is None:
                _ce = _sc[cty] = {"obl": 0, "proj": 0, "cats": {}}
            _ce["obl"]  += obl
            _ce["proj"] += 1
            _cc = _ce["cats"].get(code)          # per category: [obligated, projects]
            if _cc is None:
                _cc = _ce["cats"][code] = [0, 0]
            _cc[0] += obl
            _cc[1] += 1

    # Top 15 states by federal share
    top_states = sorted(
        [{"state": k, "obl": round(v["obl"],2), "proj": v["proj"]} for k,v in pa_by_state.items()],
        key=lambda x: -x["obl"]
    )

    # All categories sorted by federal share
    top_cats = sorted(
        [{"code": k, "cat": DCC_LABELS.get(k, "Other"), "obl": round(v["obl"],2), "proj": v["proj"]} for k,v in pa_by_cat.items()],
        key=lambda x: -x["obl"]
    )

    by_year = sorted(
        [{"year": int(k), "obl": round(v,2)} for k,v in pa_by_year.items()],
        key=lambda x: x["year"]
    )

    top_disasters = sorted(
        [{"num": k,
          "name": dn_title.get(k) or ((v["inc"] + (" " + v["year"] if v["year"] else "")).strip()) or f"DR-{k}",
          "inc":  v["inc"], "year": v["year"],
          "obl":  round(v["obl"],2), "proj": v["proj"]}
         for k,v in pa_by_disaster.items()],
        key=lambda x: -x["obl"]
    )[:10]

    # state -> its disasters, each sorted by federal share (names from declarations)
    state_disasters = {}
    for _st, _sd in pa_state_dis.items():
        state_disasters[_st] = sorted(
            [{"num":  k,
              "name": dn_title.get(k) or ((v["inc"] + (" " + v["year"] if v["year"] else "")).strip()) or f"DR-{k}",
              "inc":  v["inc"], "year": v["year"],
              "obl":  round(v["obl"], 2), "proj": v["proj"]}
             for k, v in _sd.items()],
            key=lambda x: -x["obl"]
        )

    # Largest single project
    largest = max((float(r.get("federalShareObligated") or 0) for r in raw_pa), default=0)

    pa_national = {
        "totalObligated":  round(pa_total_obl, 2),
        "totalProjects":   pa_total_proj,
        "totalDisasters":  len(pa_disasters),
        "largestProject":  round(largest, 2),
        "topState":        top_states[0]["state"] if top_states else "—",
        "topCategory":     top_cats[0]["cat"] if top_cats else "—",
        "topStates":       top_states,
        "topCategories":   top_cats,
        "byYear":          by_year,
        "topDisasters":    top_disasters,
        "stateDisasters":  state_disasters,
    }
    print(f"  PA summary: ${pa_total_obl/1e9:.1f}B total, {len(pa_disasters):,} disasters, {pa_total_proj:,} projects")

    # ---- Per (disaster, state) project snapshots -----------------------------
    # Archived fallback the projects page loads when the live OpenFEMA browser
    # fetch is blocked by CORS. One JSON per disaster-state pair, capped to the
    # largest PA_SNAP_TOP projects by federal share. Deterministic ordering keeps
    # unchanged files byte-identical week to week (no needless git churn).
    PA_SNAP_TOP = 200
    _snap = {}
    for r in raw_pa:
        _dn = r.get("disasterNumber"); _st = r.get("stateAbbreviation")
        if _dn is None or not _st:
            continue
        _e = _snap.get((_dn, _st))
        if _e is None:
            _e = _snap[(_dn, _st)] = {"rows": [], "count": 0}
        _e["count"] += 1
        _e["rows"].append(r)

    os.makedirs("pa-projects", exist_ok=True)
    snap_keys = []
    for (_dn, _st), _e in _snap.items():
        _rows = sorted(
            _e["rows"],
            key=lambda r: (-(float(r.get("federalShareObligated") or 0)),
                           (r.get("county") or ""),
                           (r.get("damageCategoryCode") or ""))
        )[:PA_SNAP_TOP]
        # Applicant names are not queryable in this OpenFEMA dataset, so label each
        # project by its county / applicant area. The projects page reads applicantName.
        _projects = [{
            "damageCategoryCode":    (r.get("damageCategoryCode") or "").strip().upper(),
            "applicantName":         (r.get("county") or "").strip(),
            "federalShareObligated": round(float(r.get("federalShareObligated") or 0), 2),
        } for r in _rows]
        _out = {"disasterNumber": _dn, "state": _st, "count": _e["count"], "projects": _projects}
        with open(f"pa-projects/{_dn}-{_st}.json", "w", encoding="utf-8") as _f:
            json.dump(_out, _f, separators=(",", ":"))
        snap_keys.append(f"{_dn}-{_st}")

    snap_keys.sort()
    pa_national["projectSnapshots"] = snap_keys
    print(f"  PA snapshots: {len(snap_keys):,} disaster-state files (top {PA_SNAP_TOP} each) in pa-projects/")

    # Build per-county PA output: {ST: {county: [obl, proj, topCatCode, {code:[obl,proj]}]}}
    # Element 4 (category breakdown) powers the per-jurisdiction PA category table.
    # Per-category obligated is rounded to whole dollars to keep data.js compact;
    # the element-1 total keeps cents so the card figure stays exact.
    pa_county_out = {}
    for _st, _counties in pa_by_county.items():
        _co = {}
        for _cn, _cv in _counties.items():
            top_cat = max(_cv["cats"], key=lambda k: _cv["cats"][k][0]) if _cv["cats"] else ""
            cat_bd  = {code: [round(v[0]), v[1]] for code, v in _cv["cats"].items()}
            _co[_cn] = [round(_cv["obl"], 2), _cv["proj"], top_cat, cat_bd]
        pa_county_out[_st] = _co
    _cty_count = sum(len(v) for v in pa_county_out.values())
    _cat_cells = sum(len(c[3]) for s in pa_county_out.values() for c in s.values())
    print(f"  PA by county: {_cty_count:,} counties across {len(pa_county_out)} states "
          f"({_cat_cells:,} category rows)")



# ═════════════════════════════════════════════════════════════════════════
# 2c. FETCH PA OBLIGATION TIMING (Grant Award Activities) -> pa-timing.json
# ═════════════════════════════════════════════════════════════════════════
# PublicAssistanceFundedProjectsDetails (fetched above) carries obligated
# dollars but NO obligation dates. The per-disaster "how fast the money came"
# timing baked into each jurisdiction page needs dateObligated, which lives
# only in PublicAssistanceGrantAwardActivities. This pull rolls obligations up
# per (state, county, disaster) and writes pa-timing.json, keyed by the same
# raw county string as PA_BY_COUNTY so the generator matches them. The
# generator reads pa-timing.json at build time and skips the section entirely
# if it is absent, so any failure here degrades quietly and never breaks the
# build. (Field names verified against the working build_ttm.py fetch.)

GA_BASE   = "https://www.fema.gov/api/open/v2"
GA_FIELDS = [
    "disasterNumber", "stateAbbreviation", "county", "damageCategoryCode",
    "federalShareObligated", "dateObligated", "declarationDate", "fundingStatus",
]

def fetch_ga_all():
    """Page through PublicAssistanceGrantAwardActivities (START_YEAR+).
    Mirrors fetch_pa_all(): same paging, retry, and pacing."""
    records = []
    skip    = 0
    total   = None
    filt    = urllib.parse.quote("declarationDate ge '%d-01-01T00:00:00.000Z'" % START_YEAR)
    select  = ",".join(GA_FIELDS)
    print("  Fetching PublicAssistanceGrantAwardActivities (national)...")

    while True:
        url = (f"{GA_BASE}/PublicAssistanceGrantAwardActivities"
               f"?$top={PAGE_SIZE}&$skip={skip}"
               f"&$filter={filt}"
               f"&$select={select}"
               f"&$inlinecount=allpages")

        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "DisasterData-Explorer/1.0"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read())
                break
            except Exception as e:
                if attempt == 4:
                    raise
                wait = 10 * (attempt + 1)
                print(f"    Retry {attempt+1}/4: {e} (waiting {wait}s)")
                time.sleep(wait)

        batch = data.get("PublicAssistanceGrantAwardActivities", [])
        records.extend(batch)

        if total is None:
            total = int(data.get("metadata", {}).get("count", 0))
            print(f"    Total GA records: {total:,}")

        skip += len(batch)
        if skip % 50000 == 0 or (total and skip >= total):
            print(f"    Fetched {skip:,}/{total:,}")

        if not batch or (total and skip >= total):
            break
        time.sleep(SLEEP_SEC)

    return records


def _iso_day(v):
    """OpenFEMA datetime -> 'YYYY-MM-DD', or '' if unusable."""
    if not v:
        return ""
    s = str(v)
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else ""


print("Fetching PA obligation timing (Grant Award Activities; may take several minutes)...")
try:
    raw_ga = fetch_ga_all()
    print(f"  -> {len(raw_ga):,} Grant Award Activity records\n")
    GA_AVAILABLE = True
except Exception as e:
    print(f"  WARNING: Grant Award Activities fetch failed: {e}")
    print("  pa-timing.json will not be written; the funding-timing section simply will not render.\n")
    raw_ga = []
    GA_AVAILABLE = False

if raw_ga:
    # accumulate per (state, county, disaster)
    _ga_acc = {}   # (st, cty, dn) -> {decl, first, last, obl, cats:{code:obl}}
    for r in raw_ga:
        if not str(r.get("fundingStatus") or "").upper().startswith("O"):
            continue                                  # obligated rows only
        do = _iso_day(r.get("dateObligated"))
        if not do:
            continue                                  # must carry an obligation date
        st  = (r.get("stateAbbreviation") or "").strip()
        cty = (r.get("county") or "").strip()
        dn  = str(r.get("disasterNumber") or "").strip()
        if not st or not cty or not dn:
            continue
        try:
            fs = float(r.get("federalShareObligated") or 0)
        except (TypeError, ValueError):
            fs = 0.0
        decl = _iso_day(r.get("declarationDate"))
        cat  = (r.get("damageCategoryCode") or "").strip() or "-"

        rec = _ga_acc.get((st, cty, dn))
        if rec is None:
            rec = {"decl": decl, "first": do, "last": do, "obl": 0.0, "cats": {}}
            _ga_acc[(st, cty, dn)] = rec
        if decl and not rec["decl"]:
            rec["decl"] = decl
        if do < rec["first"]:
            rec["first"] = do
        if do > rec["last"]:
            rec["last"] = do
        rec["obl"] += fs
        rec["cats"][cat] = rec["cats"].get(cat, 0.0) + fs

    # shape into {ST: {county: {disasterNumber: [decl, first, last, obl, topCat]}}}
    pa_timing_out = {}
    for (st, cty, dn), rec in _ga_acc.items():
        if not rec["decl"] or not rec["first"]:
            continue                                  # need a declaration + first obligation to draw a bar
        top_cat = max(rec["cats"].items(), key=lambda kv: kv[1])[0] if rec["cats"] else "-"
        pa_timing_out.setdefault(st, {}).setdefault(cty, {})[dn] = [
            rec["decl"], rec["first"], rec["last"], round(rec["obl"]), top_cat,
        ]

    with open("pa-timing.json", "w", encoding="utf-8") as _f:
        json.dump(pa_timing_out, _f, separators=(",", ":"))

    _pt_states   = len(pa_timing_out)
    _pt_counties = sum(len(v) for v in pa_timing_out.values())
    _pt_pairs    = sum(len(d) for v in pa_timing_out.values() for d in v.values())
    print(f"  pa-timing.json: {_pt_pairs:,} county-disaster pairs across "
          f"{_pt_counties:,} counties in {_pt_states} states\n")
else:
    print("  Skipping pa-timing.json (no Grant Award Activities data).\n")



# ═════════════════════════════════════════════════════════════════════════
# 2d. FETCH HAZARD MITIGATION (HMA Projects) -> hma.json
# ═════════════════════════════════════════════════════════════════════════
# Completes the county lifecycle arc: declaration -> PA (rebuild) -> HM (reduce
# the next one). HazardMitigationAssistanceProjects (v4) is county-level, so it
# rolls up per jurisdiction like PA does. Keeps only FUNDED rows
# (federalShareObligated > 0) and writes hma.json, keyed so the generator can
# match it with the SAME pa_base_kind (base, kind) logic used for PA and
# pa-timing: independent cities (county FIPS >= 510) are written as
#   "<name>, City of", all other county-equivalents as "<name> County".
# The generator skips the section entirely if hma.json is absent, so any
# failure here degrades quietly and never breaks the build.
#
# VERIFY ON FIRST RUN (mirrors how the GA fetch was confirmed):
#   - endpoint version is v4 (current dataset version)
#   - server-side filter 'federalShareObligated gt 0'; if the API rejects it,
#     drop the &$filter and rely on the client-side fed>0 guard below.

HMA_BASE   = "https://www.fema.gov/api/open/v4"
HMA_FIELDS = [
    "programArea", "federalShareObligated", "county", "countyCode",
    "stateNumberCode", "numberOfFinalProperties",
]

# 2-digit state/territory FIPS -> USPS abbreviation (reverse of the generator's map).
FIPS2ABBR = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT","10":"DE",
    "11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL","18":"IN","19":"IA",
    "20":"KS","21":"KY","22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN",
    "28":"MS","29":"MO","30":"MT","31":"NE","32":"NV","33":"NH","34":"NJ","35":"NM",
    "36":"NY","37":"NC","38":"ND","39":"OH","40":"OK","41":"OR","42":"PA","44":"RI",
    "45":"SC","46":"SD","47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA",
    "54":"WV","55":"WI","56":"WY","60":"AS","66":"GU","69":"MP","72":"PR","78":"VI",
}

# County-equivalent suffixes some names already carry, so we do not double them.
_HMA_SUFFIXES = (" county", " parish", " borough", " municipio", " municipality",
                 " island", " district", " census area", " city and borough")

def _hma_match_name(name, county_code):
    """Build a key that the generator's pa_base_kind() resolves to the SAME
    (base, kind) as the jurisdiction. Independent cities (county FIPS >= 510)
    become '<base>, City of'; every other county-equivalent becomes
    '<name> County' unless it already carries a county-type suffix."""
    nm = (name or "").strip()
    low = nm.lower()
    if county_code >= 510:
        if low.endswith(" city"):
            nm = nm[:-5].strip()
        return nm + ", City of"
    if low.endswith(_HMA_SUFFIXES):
        return nm
    return nm + " County"

def fetch_hma_all():
    """Page through HazardMitigationAssistanceProjects (funded rows only).
    Mirrors fetch_ga_all(): same paging, retry, and pacing."""
    records = []
    skip    = 0
    total   = None
    filt    = urllib.parse.quote("federalShareObligated gt 0")
    select  = ",".join(HMA_FIELDS)
    print("  Fetching HazardMitigationAssistanceProjects (national)...")

    while True:
        url = (f"{HMA_BASE}/HazardMitigationAssistanceProjects"
               f"?$top={PAGE_SIZE}&$skip={skip}"
               f"&$filter={filt}"
               f"&$select={select}"
               f"&$inlinecount=allpages")

        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "DisasterData-Explorer/1.0"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read())
                break
            except Exception as e:
                if attempt == 4:
                    raise
                wait = 10 * (attempt + 1)
                print(f"    Retry {attempt+1}/4: {e} (waiting {wait}s)")
                time.sleep(wait)

        batch = data.get("HazardMitigationAssistanceProjects", [])
        records.extend(batch)

        if total is None:
            total = int(data.get("metadata", {}).get("count", 0))
            print(f"    Total HMA funded records: {total:,}")

        skip += len(batch)
        if skip % 50000 == 0 or (total and skip >= total):
            print(f"    Fetched {skip:,}/{total:,}")

        if not batch or (total and skip >= total):
            break
        time.sleep(SLEEP_SEC)

    return records


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


print("Fetching Hazard Mitigation projects (HMA; may take a few minutes)...")
try:
    raw_hma = fetch_hma_all()
    print(f"  -> {len(raw_hma):,} HMA funded project records\n")
    HMA_AVAILABLE = True
except Exception as e:
    print(f"  WARNING: HMA fetch failed: {e}")
    print("  hma.json will not be written; the hazard-mitigation section simply will not render.\n")
    raw_hma = []
    HMA_AVAILABLE = False

if raw_hma:
    _hma_acc = {}   # st -> {name -> {"fed":float,"n":int,"prog":{p:[fed,n]},"props":int}}
    _hma_skipped = 0
    for r in raw_hma:
        try:
            fed = float(r.get("federalShareObligated") or 0)
        except (TypeError, ValueError):
            fed = 0.0
        if fed <= 0:
            continue
        st_fips = _digits(r.get("stateNumberCode")).zfill(2)[:2]
        abbr = FIPS2ABBR.get(st_fips)
        cc   = _digits(r.get("countyCode"))
        name = (r.get("county") or "").strip()
        if not abbr or not cc or not name:
            _hma_skipped += 1
            continue
        cc3 = cc[-3:] if len(cc) >= 3 else cc.zfill(3)
        try:
            code = int(cc3)
        except ValueError:
            _hma_skipped += 1
            continue
        key  = _hma_match_name(name, code)
        prog = (r.get("programArea") or "").strip().upper() or "OTHER"
        try:
            props = int(float(r.get("numberOfFinalProperties") or 0))
        except (TypeError, ValueError):
            props = 0

        _sc = _hma_acc.setdefault(abbr, {})
        rec = _sc.get(key)
        if rec is None:
            rec = {"fed": 0.0, "n": 0, "prog": {}, "props": 0}
            _sc[key] = rec
        rec["fed"]   += fed
        rec["n"]     += 1
        rec["props"] += props
        pr = rec["prog"].get(prog)
        if pr is None:
            rec["prog"][prog] = [fed, 1]
        else:
            pr[0] += fed
            pr[1] += 1

    hma_out = {}
    for st, names in _hma_acc.items():
        _co = {}
        for name, rec in names.items():
            _co[name] = {
                "fed":   round(rec["fed"]),
                "n":     rec["n"],
                "prog":  {p: [round(v[0]), v[1]] for p, v in rec["prog"].items()},
                "props": rec["props"],
            }
        hma_out[st] = _co

    with open("hma.json", "w", encoding="utf-8") as _f:
        json.dump(hma_out, _f, separators=(",", ":"))

    _hm_states = len(hma_out)
    _hm_names  = sum(len(v) for v in hma_out.values())
    _hm_fed    = sum(c["fed"] for v in hma_out.values() for c in v.values())
    _hm_proj   = sum(c["n"]   for v in hma_out.values() for c in v.values())
    print(f"  hma.json: {_hm_names:,} jurisdictions across {_hm_states} states, "
          f"{_hm_proj:,} funded projects, ${_hm_fed:,.0f} federal share "
          f"(skipped {_hma_skipped:,} rows with no usable county)\n")
else:
    print("  Skipping hma.json (no HMA data).\n")

# ═════════════════════════════════════════════════════════════════════════
# 3. AGGREGATE SUMMARY DATA
# ═════════════════════════════════════════════════════════════════════════

print("Building aggregates...")

# Filter valid processing times (used ONLY for timing averages)
dec_valid = [r for r in dec_processed if r["days_to_approve"] >= 0]
den_valid = [r for r in den_processed if r["days_to_deny"] >= 0]

# Deduplicate to ONE row per declaration. The summaries dataset returns one row per
# county/designated area, so per-row counting inflates totals, while filtering on a valid
# begin date (dec_valid) silently drops legitimate declarations. dec_unique is the complete,
# deduplicated set used for ALL counts; timing averages still ignore missing begin dates via avg().
dec_unique = list({r["femaDeclarationString"]: r for r in dec_processed}.values())

# ── DATA INTEGRITY REPORT ─────────────────────────────────────────────────
from collections import Counter as _Counter
_dropped = sum(1 for r in dec_unique if r["days_to_approve"] < 0)
_bytype  = _Counter(r["declarationType"] for r in dec_unique)
_byfy    = _Counter(r["fyDeclared"] for r in dec_unique)
print("\n──────── DATA INTEGRITY ────────")
print(f"Rows fetched (per county/area): {len(dec_processed)}")
print(f"Unique declarations:            {len(dec_unique)}")
print(f"  by type: {dict(_bytype)}")
print(f"  missing begin-date:           {_dropped}  (counted; excluded from timing averages only)")
print("  by fiscal year:")
for _y in sorted(_byfy):
    print(f"    FY{_y}: {_byfy[_y]}")
print("────────────────────────────────\n")

def avg(lst):
    vals = [x for x in lst if x is not None and x >= 0]
    return round(sum(vals) / len(vals), 1) if vals else 0

# Year-over-year
yoy_dec = defaultdict(lambda: {"declarations": 0, "days": []})
for r in dec_unique:
    fy = r["fyDeclared"]
    if fy <= CURRENT_FY:
        yoy_dec[fy]["declarations"] += 1
        yoy_dec[fy]["days"].append(r["days_to_approve"])

yoy_den = defaultdict(lambda: {"denials": 0, "days": []})
for r in den_valid:
    yr = int(r["declarationRequestDate"][:4]) if r["declarationRequestDate"] else 0
    if 2000 <= yr <= CURRENT_FY:
        yoy_den[yr]["denials"] += 1
        yoy_den[yr]["days"].append(r["days_to_deny"])

all_years = sorted(set(list(yoy_dec.keys()) + list(yoy_den.keys())))
yoy = []
for yr in all_years:
    d  = yoy_dec.get(yr, {})
    dn = yoy_den.get(yr, {})
    yoy.append({
        "fyDeclared":    yr,
        "declarations":  d.get("declarations", 0),
        "avg_days":      avg(d.get("days", [])),
        "denials":       dn.get("denials", 0),
        "avg_days_deny": avg(dn.get("days", [])),
    })

# By incident type
inc_map = defaultdict(lambda: {"count": 0, "days": []})
for r in dec_unique:
    it = r["incidentType"] or "Unknown"
    inc_map[it]["count"] += 1
    inc_map[it]["days"].append(r["days_to_approve"])
by_incident = sorted(
    [{"incidentType": k, "count": v["count"], "avg_days": avg(v["days"])} for k, v in inc_map.items()],
    key=lambda x: -x["count"]
)

# By state
state_map = defaultdict(lambda: {"count": 0, "days": []})
for r in dec_unique:
    state_map[r["state"]]["count"] += 1
    state_map[r["state"]]["days"].append(r["days_to_approve"])
by_state = sorted(
    [{"state": k, "count": v["count"], "avg_days": avg(v["days"])} for k, v in state_map.items()],
    key=lambda x: -x["count"]
)

# By declaration type
dec_type_map = defaultdict(lambda: {"count": 0, "days": []})
for r in dec_unique:
    dec_type_map[r["declarationType"]]["count"] += 1
    dec_type_map[r["declarationType"]]["days"].append(r["days_to_approve"])
by_dec_type = [{"declarationType": k, "count": v["count"], "avg_days": avg(v["days"])} for k, v in dec_type_map.items()]

# Denials by type
den_inc_map = defaultdict(int)
for r in den_valid:
    den_inc_map[r["requestedIncidentTypes"] or "Unknown"] += 1
denials_by_type = sorted([{"requestedIncidentTypes": k, "count": v} for k, v in den_inc_map.items()], key=lambda x: -x["count"])

# Denials by state
den_state_map = defaultdict(lambda: {"count": 0, "days": []})
for r in den_valid:
    st = r["stateAbbreviation"]
    den_state_map[st]["count"] += 1
    den_state_map[st]["days"].append(r["days_to_deny"])
denials_by_state = sorted(
    [{"stateAbbreviation": k, "count": v["count"], "avg_days": avg(v["days"])} for k, v in den_state_map.items()],
    key=lambda x: -x["count"]
)

summary = {
    "yoy":            yoy,
    "byIncidentType": by_incident,
    "byState":        by_state,
    "byDecType":      by_dec_type,
    "denialsByType":  denials_by_type,
    "denialsByState": denials_by_state,
    "lastUpdated":    TODAY,
}

# ── State-level aggregates ────────────────────────────────────────────────
swva = ['Bland','Buchanan','Carroll','Craig','Dickenson','Floyd','Giles',
        'Grayson','Henry','Highland','Lee','Montgomery','Patrick','Pulaski',
        'Russell','Scott','Smyth','Tazewell','Washington','Wise','Wythe',
        'Bristol','Galax','Norton','Radford']

state_dec_map  = defaultdict(lambda: {"declarations": 0, "days": [], "incidents": defaultdict(int), "top_incident": ""})
for r in dec_unique:
    st = r["state"]
    if r["fyDeclared"] <= CURRENT_FY:
        state_dec_map[st]["declarations"] += 1
        state_dec_map[st]["days"].append(r["days_to_approve"])
        state_dec_map[st]["incidents"][r["incidentType"] or "Unknown"] += 1

state_den_map = defaultdict(lambda: {"denials": 0, "days": []})
for r in den_valid:
    yr = int(r["declarationRequestDate"][:4]) if r["declarationRequestDate"] else 0
    if yr <= CURRENT_FY:
        st = r["stateAbbreviation"]
        state_den_map[st]["denials"] += 1
        state_den_map[st]["days"].append(r["days_to_deny"])

state_summary = []
for st, d in state_dec_map.items():
    dn       = state_den_map.get(st, {})
    decl     = d["declarations"]
    denials  = dn.get("denials", 0)
    total_r  = decl + denials
    top_inc  = max(d["incidents"], key=d["incidents"].get) if d["incidents"] else ""
    state_summary.append({
        "state":         st,
        "declarations":  decl,
        "denials":       denials,
        "total_requests": total_r,
        "denial_rate":   round(denials / total_r * 100, 2) if total_r else 0,
        "avg_days":      avg(d["days"]),
        "avg_deny_days": avg(dn.get("days", [])),
        "top_incident":  top_inc,
    })

# State YoY
state_yoy_map = defaultdict(list)
for r in dec_unique:
    if r["fyDeclared"] <= CURRENT_FY:
        state_yoy_map[r["state"]].append(r["fyDeclared"])

state_yoy = {}
for st, years_list in state_yoy_map.items():
    from collections import Counter
    yr_counts = Counter(years_list)
    state_yoy[st] = [{"y": yr, "c": cnt} for yr, cnt in sorted(yr_counts.items())]

# State incident breakdown
state_inc_map2 = defaultdict(lambda: defaultdict(int))
for r in dec_unique:
    if r["fyDeclared"] <= CURRENT_FY:
        state_inc_map2[r["state"]][r["incidentType"] or "Unknown"] += 1

state_inc = {
    st: sorted([{"t": inc, "c": cnt} for inc, cnt in incs.items()], key=lambda x: -x["c"])
    for st, incs in state_inc_map2.items()
}

# State disaster list (unique per femaDeclarationString)
state_disasters = defaultdict(list)
seen = set()
for r in sorted(dec_valid, key=lambda x: x["declarationDate"], reverse=True):
    if r["fyDeclared"] > CURRENT_FY:
        continue
    key = r["femaDeclarationString"]
    if key in seen:
        continue
    seen.add(key)
    state_disasters[r["state"]].append({
        "id":    r["femaDeclarationString"],
        "dt":    r["declarationType"],
        "date":  r["declarationDate"],
        "fy":    r["fyDeclared"],
        "inc":   r["incidentType"],
        "title": r["declarationTitle"],
        "days":  r["days_to_approve"],
        "reg":   r["region"],
    })

# Browse list (unique disasters, national)
browse = []
seen2 = set()
for r in sorted(dec_unique, key=lambda x: x["declarationDate"], reverse=True):
    if r["fyDeclared"] > CURRENT_FY:
        continue
    key = r["femaDeclarationString"]
    if key in seen2:
        continue
    seen2.add(key)
    browse.append({
        "femaDeclarationString": r["femaDeclarationString"],
        "state":                 r["state"],
        "declarationType":       r["declarationType"],
        "declarationDate":       r["declarationDate"],
        "fyDeclared":            r["fyDeclared"],
        "incidentType":          r["incidentType"],
        "declarationTitle":      r["declarationTitle"],
        "region":                r["region"],
        "days_to_approve":       r["days_to_approve"],
        "tribal":                r.get("tribalRequest", 0),
        "area":                  r.get("designatedArea", "") if r.get("tribalRequest") else "",
    })

# ── Presidential era aggregates ───────────────────────────────────────────
ERA_MAP = {
    2001:"Bush T1",2002:"Bush T1",2003:"Bush T1",2004:"Bush T1",
    2005:"Bush T2",2006:"Bush T2",2007:"Bush T2",2008:"Bush T2",
    2009:"Obama T1",2010:"Obama T1",2011:"Obama T1",2012:"Obama T1",
    2013:"Obama T2",2014:"Obama T2",2015:"Obama T2",2016:"Obama T2",
    2017:"Trump T1",2018:"Trump T1",2019:"Trump T1",2020:"Trump T1",
    2021:"Biden",2022:"Biden",2023:"Biden",2024:"Biden",
    **{fy: "Trump T2" for fy in range(2025, CURRENT_FY + 1)},
}

era_dec_map = defaultdict(lambda: {"declarations": 0, "days": [], "incidents": defaultdict(int)})
for r in dec_valid:
    era = ERA_MAP.get(r["fyDeclared"])
    if not era:
        continue
    era_dec_map[era]["declarations"] += 1
    era_dec_map[era]["days"].append(r["days_to_approve"])
    era_dec_map[era]["incidents"][r["incidentType"] or "Unknown"] += 1

era_den_map = defaultdict(lambda: {"denials": 0, "days": []})
for r in den_valid:
    yr = int(r["declarationRequestDate"][:4]) if r["declarationRequestDate"] else 0
    era = ERA_MAP.get(yr)
    if not era:
        continue
    era_den_map[era]["denials"] += 1
    era_den_map[era]["days"].append(r["days_to_deny"])

def build_era_row(key, dec_d, den_d):
    decl    = dec_d.get("declarations", 0)
    denials = den_d.get("denials", 0)
    total_r = decl + denials
    return {
        "era":           key,
        "declarations":  decl,
        "denials":       denials,
        "total_requests": total_r,
        "denial_rate":   round(denials / total_r * 100, 2) if total_r else 0,
        "avg_days":      avg(dec_d.get("days", [])),
        "avg_deny_days": avg(den_d.get("days", [])),
    }

TERM_KEYS = ["Bush T1","Bush T2","Obama T1","Obama T2","Trump T1","Biden","Trump T2"]
era_rows  = {k: build_era_row(k, era_dec_map.get(k, {}), era_den_map.get(k, {})) for k in TERM_KEYS}

def combined_era(label, keys):
    all_dec  = sum(era_rows[k]["declarations"]  for k in keys if k in era_rows)
    all_den  = sum(era_rows[k]["denials"]        for k in keys if k in era_rows)
    all_tr   = all_dec + all_den
    all_d_days = [d for k in keys for d in era_dec_map.get(k, {}).get("days", [])]
    all_n_days = [d for k in keys for d in era_den_map.get(k, {}).get("days", [])]
    return {
        "era": label, "declarations": all_dec, "denials": all_den,
        "total_requests": all_tr,
        "denial_rate":    round(all_den / all_tr * 100, 2) if all_tr else 0,
        "avg_days":       avg(all_d_days),
        "avg_deny_days":  avg(all_n_days),
    }

era_ordered = [
    era_rows["Bush T1"], era_rows["Bush T2"], combined_era("Bush Total", ["Bush T1","Bush T2"]),
    era_rows["Obama T1"], era_rows["Obama T2"], combined_era("Obama Total", ["Obama T1","Obama T2"]),
    era_rows["Trump T1"], era_rows["Biden"],
    era_rows["Trump T2"], combined_era("Trump Total", ["Trump T1","Trump T2"]),
]

# Era incident breakdown
era_inc = {}
for key in list(TERM_KEYS) + ["Bush Total","Obama Total","Trump Total"]:
    src_keys = (["Bush T1","Bush T2"] if "Bush Total" in key else
                ["Obama T1","Obama T2"] if "Obama Total" in key else
                ["Trump T1","Trump T2"] if "Trump Total" in key else [key])
    combined_inc = defaultdict(int)
    for k in src_keys:
        for inc, cnt in era_dec_map.get(k, {}).get("incidents", {}).items():
            combined_inc[inc] += cnt
    era_inc[key] = sorted([{"type": inc, "count": cnt} for inc, cnt in combined_inc.items()],
                           key=lambda x: -x["count"])[:6]

# Era YoY
yoy_era = []
for r in dec_valid:
    era = ERA_MAP.get(r["fyDeclared"])
    if era:
        yoy_era.append({"fyDeclared": r["fyDeclared"], "era": era})

from collections import Counter
yoy_era_counts = Counter((r["fyDeclared"], r["era"]) for r in yoy_era)
yoy_era_list = [{"fyDeclared": fy, "era": era, "count": cnt}
                for (fy, era), cnt in sorted(yoy_era_counts.items())]

# Era disaster lists
era_disasters = {}
for key in list(TERM_KEYS) + ["Bush Total","Obama Total","Trump Total"]:
    src_keys = (["Bush T1","Bush T2"] if "Bush Total" in key else
                ["Obama T1","Obama T2"] if "Obama Total" in key else
                ["Trump T1","Trump T2"] if "Trump Total" in key else [key])
    recs = []
    seen3 = set()
    for r in sorted(dec_valid, key=lambda x: x["declarationDate"], reverse=True):
        era = ERA_MAP.get(r["fyDeclared"])
        if era not in src_keys:
            continue
        fid = r["femaDeclarationString"]
        if fid in seen3:
            continue
        seen3.add(fid)
        recs.append({"id":r["femaDeclarationString"],"state":r["state"],"dt":r["declarationType"],
                     "date":r["declarationDate"],"fy":r["fyDeclared"],"inc":r["incidentType"],
                     "title":r["declarationTitle"],"days":r["days_to_approve"],"reg":r["region"]})
    era_disasters[key] = recs

era_data = {
    "eraOrdered":   era_ordered,
    "eraInc":       era_inc,
    "yoyEra":       yoy_era_list,
    "eraDisasters": era_disasters,
    "eraDenials":   {},   # kept for schema compatibility
}

print("Aggregation complete.\n")


# ═════════════════════════════════════════════════════════════════════════

# Helper for grouping by state
def groupby_state(records):
    from collections import defaultdict
    state_map = defaultdict(list)
    for r in records:
        state_map[r.get("state","")].append(r)
    return state_map.items()

# 4. BUILD data.js
# ═════════════════════════════════════════════════════════════════════════

print("Building data.js...")

import re, os

STATE_NAMES = {
    "AK":"Alaska","AL":"Alabama","AR":"Arkansas","AS":"American Samoa","AZ":"Arizona",
    "CA":"California","CO":"Colorado","CT":"Connecticut","DC":"Washington D.C.","DE":"Delaware",
    "FL":"Florida","FM":"Fed. States of Micronesia","GA":"Georgia","GU":"Guam","HI":"Hawaii",
    "IA":"Iowa","ID":"Idaho","IL":"Illinois","IN":"Indiana","KS":"Kansas","KY":"Kentucky",
    "LA":"Louisiana","MA":"Massachusetts","MD":"Maryland","ME":"Maine","MI":"Michigan",
    "MN":"Minnesota","MO":"Missouri","MP":"N. Mariana Islands","MS":"Mississippi","MT":"Montana",
    "NC":"North Carolina","ND":"North Dakota","NE":"Nebraska","NH":"New Hampshire","NJ":"New Jersey",
    "NM":"New Mexico","NV":"Nevada","NY":"New York","OH":"Ohio","OK":"Oklahoma","OR":"Oregon",
    "PA":"Pennsylvania","PR":"Puerto Rico","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota",
    "TN":"Tennessee","TX":"Texas","UT":"Utah","VA":"Virginia","VI":"U.S. Virgin Islands",
    "VT":"Vermont","WA":"Washington","WI":"Wisconsin","WV":"West Virginia","WY":"Wyoming",
}

# Presidential term FY mapping (for client-side era filtering)
ERA_FY_MAP = {
    2001:"bush_t1",2002:"bush_t1",2003:"bush_t1",2004:"bush_t1",
    2005:"bush_t2",2006:"bush_t2",2007:"bush_t2",2008:"bush_t2",
    2009:"obama_t1",2010:"obama_t1",2011:"obama_t1",2012:"obama_t1",
    2013:"obama_t2",2014:"obama_t2",2015:"obama_t2",2016:"obama_t2",
    2017:"trump_t1",2018:"trump_t1",2019:"trump_t1",2020:"trump_t1",
    2021:"biden",2022:"biden",2023:"biden",2024:"biden",
    **{fy: "trump_t2" for fy in range(2025, CURRENT_FY + 1)},
}
ERA_TOTAL_KEYS = {
    "bush_total":  ["bush_t1","bush_t2"],
    "obama_total": ["obama_t1","obama_t2"],
    "trump_total": ["trump_t1","trump_t2"],
}

# Build era_data for PRES_DATA (without disaster lists — those come from BROWSE)
era_dec_map  = defaultdict(lambda: {"declarations": 0, "days": []})
era_den_map  = defaultdict(lambda: {"denials": 0, "days": []})

for r in dec_valid:
    era = ERA_FY_MAP.get(r["fyDeclared"])
    if era:
        era_dec_map[era]["declarations"] += 1
        era_dec_map[era]["days"].append(r["days_to_approve"])

for r in den_valid:
    yr  = int(r["declarationRequestDate"][:4]) if r["declarationRequestDate"] else 0
    era = ERA_FY_MAP.get(yr)
    if era:
        era_den_map[era]["denials"] += 1
        era_den_map[era]["days"].append(r["days_to_deny"])

def era_stats_dict(keys):
    d  = sum(era_dec_map[k]["declarations"] for k in keys)
    dn = sum(era_den_map[k]["denials"]      for k in keys)
    tr = d + dn
    dd = [x for k in keys for x in era_dec_map[k]["days"]]
    nd = [x for k in keys for x in era_den_map[k]["days"]]
    return {
        "declarations": d, "denials": dn, "total_requests": tr,
        "denial_rate":  round(dn/tr*100, 2) if tr else 0,
        "avg_days":     round(sum(dd)/len(dd), 1) if dd else 0,
        "avg_deny_days":round(sum(nd)/len(nd), 1) if nd else 0,
    }

_t2_start = 2025
_t2_label = f"{_t2_start}–{CURRENT_FY}" if CURRENT_FY > _t2_start else f"{_t2_start} (partial)"
_t2_total = f"2017–2020 + {_t2_start}–{CURRENT_FY}" if CURRENT_FY > _t2_start else f"2017–2020 + {_t2_start}"

YEARS_MAP = {
    "bush_t1":"2001–2004","bush_t2":"2005–2008","bush_total":"2001–2008",
    "obama_t1":"2009–2012","obama_t2":"2013–2016","obama_total":"2009–2016",
    "trump_t1":"2017–2020","biden":"2021–2024",
    "trump_t2": _t2_label,
    "trump_total": _t2_total,
}
LABEL_MAP = {
    "bush_t1":"Bush T1","bush_t2":"Bush T2","bush_total":"Bush Total",
    "obama_t1":"Obama T1","obama_t2":"Obama T2","obama_total":"Obama Total",
    "trump_t1":"Trump T1","biden":"Biden",
    "trump_t2":"Trump T2","trump_total":"Trump Total",
}
TERM_KEYS = ["bush_t1","bush_t2","obama_t1","obama_t2","trump_t1","biden","trump_t2"]

pres_data = {}
for group_keys, key in [
    (["bush_t1"],              "bush_t1"),
    (["bush_t2"],              "bush_t2"),
    (["bush_t1","bush_t2"],    "bush_total"),
    (["obama_t1"],             "obama_t1"),
    (["obama_t2"],             "obama_t2"),
    (["obama_t1","obama_t2"],  "obama_total"),
    (["trump_t1"],             "trump_t1"),
    (["biden"],                "biden"),
    (["trump_t2"],             "trump_t2"),
    (["trump_t1","trump_t2"],  "trump_total"),
]:
    stats = era_stats_dict(group_keys)
    # Top incident types for this era
    inc_counter = defaultdict(int)
    for r in dec_valid:
        if ERA_FY_MAP.get(r["fyDeclared"]) in group_keys:
            inc_counter[r["incidentType"] or "Unknown"] += 1
    top_inc = sorted([{"type":k,"count":v} for k,v in inc_counter.items()],
                     key=lambda x: -x["count"])[:6]
    pres_data[key] = {
        "label":         LABEL_MAP[key],
        "years":         YEARS_MAP[key],
        "declarations":  stats["declarations"],
        "denials":       stats["denials"],
        "total":         stats["total_requests"],
        "denial_rate":   stats["denial_rate"],
        "avg_days":      stats["avg_days"],
        "avg_deny_days": stats["avg_deny_days"],
        "top_incidents": top_inc,
        # disasters intentionally omitted — filtered from BROWSE client-side
    }

PRES_ORDER = [
    ["bush_t1","Bush — Term 1","2001–2004"],
    ["bush_t2","Bush — Term 2","2005–2008"],
    ["bush_total","Bush — Total","2001–2008"],
    ["obama_t1","Obama — Term 1","2009–2012"],
    ["obama_t2","Obama — Term 2","2013–2016"],
    ["obama_total","Obama — Total","2009–2016"],
    ["trump_t1","Trump — Term 1","2017–2020"],
    ["biden","Biden","2021–2024"],
    ["trump_t2", f"Trump — Term 2", _t2_label],
    ["trump_total","Trump — Total", _t2_total],
]

# Build locality data (compact: IDs only, client looks up in BROWSE)
locality_data = defaultdict(list)
for state, grp in groupby_state(dec_valid):
    loc_map = defaultdict(lambda: {"rows": [], "ids": set()})
    for r in grp:
        area = r.get("designatedArea", "") or ""
        loc_map[area]["rows"].append(r)
        loc_map[area]["ids"].add(r["femaDeclarationString"])
    locs = []
    for area, v in loc_map.items():
        rows = v["rows"]
        top_inc = max(set(r["incidentType"] for r in rows if r["incidentType"]),
                      key=lambda x: sum(1 for r in rows if r["incidentType"]==x),
                      default="")
        locs.append({
            "n":   area,
            "c":   len(rows),
            "d":   len(v["ids"]),
            "a":   round(sum(r["days_to_approve"] for r in rows)/len(rows), 1),
            "l":   max(r["declarationDate"] for r in rows),
            "t":   top_inc,
            "ids": sorted(v["ids"]),
        })
    locality_data[state] = sorted(locs, key=lambda x: -x["c"])

# ── Integrity guardrail: counts MUST reconcile before writing data.js ─────
_browse_n  = len(browse)
_state_sum = sum(s["declarations"] for s in state_summary)
_uniq_n    = len({r["femaDeclarationString"] for r in dec_processed})
assert _browse_n == _uniq_n,   f"BROWSE ({_browse_n}) != unique declarations ({_uniq_n}) — refusing to write data.js"
assert _browse_n == _state_sum, f"BROWSE ({_browse_n}) != per-state total ({_state_sum}) — refusing to write data.js"
print(f"  integrity OK: {_browse_n} unique declarations reconcile across BROWSE and per-state totals")

# Write data.js — all window.VAR = ... assignments
lines = [
    f'window.SUMMARY          ={json.dumps(summary,         separators=(",",":"))}',
    f'window.STATE_SUMMARY    ={json.dumps(state_summary,   separators=(",",":"))}',
    f'window.STATE_YOY        ={json.dumps(state_yoy,       separators=(",",":"))}',
    f'window.STATE_INC        ={json.dumps(state_inc,       separators=(",",":"))}',
    f'window.STATE_DISASTERS  ={{}}',
    f'window.DENIALS          ={json.dumps(den_processed,   separators=(",",":"))}',
    f'window.BROWSE           ={json.dumps(browse,          separators=(",",":"))}',
    f'window.STATE_NAMES      ={json.dumps(STATE_NAMES,     separators=(",",":"))}',
    f'window.LOCALITY_DATA    ={json.dumps(dict(locality_data), separators=(",",":"))}',
    f'window.PRES_DATA        ={json.dumps(pres_data,       separators=(",",":"))}',
    f'window.PRES_ORDER       ={json.dumps(PRES_ORDER,      separators=(",",":"))}',
    f'window.ERA_FY_MAP       ={json.dumps(ERA_FY_MAP,      separators=(",",":"))}',
    f'window.ERA_TOTAL_KEYS   ={json.dumps(ERA_TOTAL_KEYS,  separators=(",",":"))}',
    f'window.DATA_DATE        ="{TODAY}"',
    f'window.PA_NATIONAL      ={json.dumps(pa_national,  separators=(",",":"))}',
    f'window.PA_BY_COUNTY     ={json.dumps(pa_county_out, separators=(",",":"))}',
    "document.dispatchEvent(new Event('dataReady'));",
]

data_js_content = "\n".join(lines)

with open("data.js", "w", encoding="utf-8") as f:
    f.write(data_js_content)

data_kb = len(data_js_content) // 1024
print(f"  data.js written ({data_kb} KB)")

# ── Build map-data.js (county choropleth + per-county declaration lists) ──────
# map.html loads this instead of embedding ~8 MB of county data inline, so the
# map refreshes on the same schedule as the home page. If anything here fails,
# data.js is already written — the home page still refreshes; only the map lags.
def _clean_area(area):
    return re.sub(r"\s*\([^)]*\)\s*$", "", area or "").strip()

def build_map_data(rows, start_year, current_fy):
    from collections import defaultdict
    nd_set  = lambda: defaultdict(lambda: defaultdict(set))
    nd_set2 = lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    nd_int  = lambda: defaultdict(lambda: defaultdict(int))
    nd_int2 = lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    ud_o = defaultdict(set); ud_y = nd_set(); ud_t = nd_set(); ud_yt = nd_set2()
    dar_o = defaultdict(int); dar_y = nd_int(); dar_t = nd_int(); dar_yt = nd_int2()
    cde = defaultdict(dict); labels = {}
    det_o = set(); det_y = defaultdict(set); det_t = defaultdict(set); det_yt = nd_set()
    county_rows = 0; statewide = 0; decls_county = set(); years_seen = set()
    for r in rows:
        try:
            fy = int(r.get("fyDeclared"))
        except (TypeError, ValueError):
            continue
        if fy < start_year or fy > current_fy:
            continue
        dn = r.get("femaDeclarationString")
        if not dn:
            continue
        ty = (r.get("declarationType") or "").strip()
        det_o.add(dn)                                   # overall = every distinct declaration (county + statewide)
        date = (r.get("declarationDate") or "")[:10]
        if not date:
            continue
        yr = date[:4]; years_seen.add(yr)
        det_y[yr].add(dn); det_t[ty].add(dn); det_yt[yr][ty].add(dn)
        cc = (r.get("fipsCountyCode") or "")
        if not cc or cc.zfill(3) == "000":             # statewide / jurisdiction-wide row — not on the county map
            statewide += 1
            continue
        fips = (r.get("fipsStateCode") or "").zfill(2) + cc.zfill(3)
        county_rows += 1; decls_county.add(dn)
        label = f"{_clean_area(r.get('designatedArea'))}, {r.get('state','')}"
        labels[fips] = label
        dar_o[fips] += 1; dar_y[yr][fips] += 1; dar_t[ty][fips] += 1; dar_yt[yr][ty][fips] += 1
        ud_o[fips].add(dn); ud_y[yr][fips].add(dn); ud_t[ty][fips].add(dn); ud_yt[yr][ty][fips].add(dn)
        if dn not in cde[fips]:
            cde[fips][dn] = {"declarationNumber": dn, "type": ty, "year": int(yr),
                             "date": date, "title": r.get("incidentType", ""), "countyLabel": label}
    sl  = lambda d: {k: len(v) for k, v in d.items()}
    sl2 = lambda d: {k: sl(v) for k, v in d.items()}
    sl3 = lambda d: {k: sl2(v) for k, v in d.items()}
    pd2 = lambda d: {k: dict(v) for k, v in d.items()}
    pd3 = lambda d: {k: pd2(v) for k, v in d.items()}
    counts = {
        "uniqueDeclarations":    {"overall": sl(ud_o),  "byYear": sl2(ud_y),  "byType": sl2(ud_t),  "byYearType": sl3(ud_yt)},
        "designatedAreaRecords": {"overall": dict(dar_o), "byYear": pd2(dar_y), "byType": pd2(dar_t), "byYearType": pd3(dar_yt)},
    }
    det = {"overall": len(det_o), "byYear": sl(det_y), "byType": sl(det_t), "byYearType": sl2(det_yt)}
    top = sorted(({"fips": f, "label": labels[f], "value": counts["uniqueDeclarations"]["overall"][f]} for f in labels),
                 key=lambda x: (-x["value"], x["fips"]))[:10]
    cde_out = {f: sorted(ev.values(), key=lambda e: (-e["year"], e["declarationNumber"])) for f, ev in cde.items()}
    return {
        "counts": counts,
        "countyDeclarationEvents": cde_out,
        "countyLabels": labels,
        "years": sorted(int(y) for y in years_seen),
        "topCounties": top,
        "declarationEventTotals": det,
        "summary": {"countyRows": county_rows, "statewideExcluded": statewide,
                    "countyFipsWithData": len(labels), "uniqueDeclarations": len(decls_county)},
    }

try:
    print("Building map-data.js...")
    map_data = build_map_data(raw_dec, START_YEAR, CURRENT_FY)
    _det = map_data["declarationEventTotals"]["overall"]
    _brw = len(browse)
    if _det != _brw:
        print(f"  NOTE: map declaration events ({_det}) != home declarations ({_brw}); these are expected to match.")
    map_js = "window.MAP_DATA = " + json.dumps(map_data, separators=(",", ":")) + ";\n"
    with open("map-data.js", "w", encoding="utf-8") as f:
        f.write(map_js)
    print(f"  map-data.js written ({len(map_js)//1024} KB) — "
          f"{map_data['summary']['countyFipsWithData']:,} counties, "
          f"{_det:,} declaration events, "
          f"{map_data['summary']['uniqueDeclarations']:,} county-mapped declarations")

    # Write lightweight county-names.js for jurisdiction page maps
    cn_js = "window.COUNTY_NAMES=" + json.dumps(map_data["countyLabels"], separators=(",", ":")) + ";"
    with open("county-names.js", "w", encoding="utf-8") as f:
        f.write(cn_js)
    print(f"  county-names.js written ({len(cn_js)//1024} KB, {len(map_data['countyLabels']):,} counties)")
except Exception as e:
    print(f"  WARNING: map-data.js build failed: {e} (home-page data.js still updated)")

# ═════════════════════════════════════════════════════════════════════════
# LATEST DECLARATIONS  (homepage teaser cards + /latest page snapshot)
# Reuses the already-fetched, integrity-checked dec_processed rows — no extra
# API calls. dec_processed is one row per designated area, so we aggregate by
# femaDeclarationString to dedupe to distinct declarations and count areas.
# ═════════════════════════════════════════════════════════════════════════

LATEST_HOME_COUNT = 5      # cards baked into the homepage
LATEST_PAGE_COUNT = 25     # declarations written to latest-data.js for /latest

# Internal links from each card to your state pages. OFF until the slug in
# state_page_url() matches your real structure, so no 404s ship.
ENABLE_STATE_LINKS = False

def state_page_url(abbr):
    # EDIT to match your real state-page URLs, then set ENABLE_STATE_LINKS = True.
    name = STATE_NAMES.get(abbr, abbr)
    slug = name.lower().replace(" ", "-").replace(".", "")
    return "/state/" + slug + "/"

def _esc(s):
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))

def _disaster_num(fema_string):
    # "DR-4830-VA" -> "4830"
    parts = str(fema_string or "").split("-")
    return parts[1] if len(parts) >= 2 else str(fema_string or "")

def _fmt_latest_date(iso):
    if not iso:
        return ""
    try:
        d = datetime.datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")
    except Exception:
        return str(iso)[:10]

def latest_declarations(dec_rows, n):
    """Aggregate per-area rows into distinct declarations, newest first."""
    agg = {}
    for r in dec_rows:
        key = r.get("femaDeclarationString")
        if not key:
            continue
        d = agg.get(key)
        if d is None:
            agg[key] = {
                "disasterNumber":   _disaster_num(key),
                "declarationType":  r.get("declarationType", ""),
                "declarationDate":  r.get("declarationDate", "") or "",
                "state":            r.get("state", ""),
                "declarationTitle": r.get("declarationTitle", ""),
                "incidentType":     r.get("incidentType", ""),
                "areaCount":        1,
            }
        else:
            d["areaCount"] += 1
            dd = r.get("declarationDate", "") or ""
            if dd > d["declarationDate"]:
                d["declarationDate"] = dd

    def _numkey(x):
        try:
            return int(x["disasterNumber"])
        except (TypeError, ValueError):
            return -1

    ordered = sorted(agg.values(),
                     key=lambda x: (x["declarationDate"], _numkey(x)),
                     reverse=True)
    return ordered[:n]

def render_latest_cards_html(items):
    """Static HTML for the homepage teaser. Cards bake in at build time so
    crawlers and first paint both get fresh content; the live client refresh
    lives only on /latest."""
    parts = []
    newest = items[0]["declarationDate"] if items else ""
    if newest:
        parts.append('<p class="ll-updated">Data current through ' + _fmt_latest_date(newest) + '</p>')
    parts.append('<div class="ll-grid">')
    for d in items:
        t     = _esc(d.get("declarationType", ""))
        num   = _esc(d.get("disasterNumber", ""))
        abbr  = d.get("state", "") or ""
        sname = _esc(STATE_NAMES.get(abbr, abbr))
        head  = ('<a href="' + state_page_url(abbr) + '">' + sname + '</a>') \
                if (ENABLE_STATE_LINKS and abbr) else sname
        cnt   = d.get("areaCount", 1) or 1
        areas = (str(cnt) + " areas") if cnt > 1 else "1 area"
        inc   = d.get("incidentType")
        inc_c = ('<span>' + _esc(inc) + '</span>') if inc else ''
        full  = _esc(d.get("declarationTitle", ""))
        parts.append(
            '<div class="ll-card" title="' + full + '">'
            '<span class="ll-badge ' + t + '">' + t + '</span>'
            '<div class="ll-body">'
            '<div class="ll-title">' + head + '</div>'
            '<div class="ll-meta">'
            '<span class="ll-num">' + t + '-' + num + '</span>'
            + inc_c +
            '<span>' + areas + '</span>'
            '<a href="https://www.fema.gov/disaster/' + num + '" target="_blank" rel="noopener">FEMA &#8599;</a>'
            '</div></div>'
            '<div class="ll-date">' + _fmt_latest_date(d.get("declarationDate")) + '</div>'
            '</div>'
        )
    parts.append('</div>')
    return "\n".join(parts)

# Build both views from the in-memory declarations
_latest_page = latest_declarations(dec_processed, LATEST_PAGE_COUNT)
_latest_home = _latest_page[:LATEST_HOME_COUNT]
_latest_cards_html = render_latest_cards_html(_latest_home)

# Write the /latest snapshot (fallback data for the /latest page)
_latest_built = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open("latest-data.js", "w", encoding="utf-8") as f:
    f.write("window.LATEST_DECLARATIONS = " +
            json.dumps(_latest_page, ensure_ascii=False, separators=(",", ":")) + ";\n")
    f.write('window.LATEST_BUILT = "' + _latest_built + '";\n')
print(f"  latest-data.js written ({len(_latest_page)} declarations)")


# Update index.html: inject PA_NATIONAL and refresh last-updated stamp
if os.path.exists("index.html"):
    with open("index.html", encoding="utf-8") as f:
        html = f.read()
    # Update last-updated stamp
    html = re.sub(r'Last updated:.*?</span>', f'Last updated: <span id="about-last-updated">{TODAY}</span>', html)
    # Inject PA_NATIONAL using line-based replacement
    # (regex approach breaks when JSON contains semicolons in string values)
    pa_json = json.dumps(pa_national, separators=(",",":"))
    lines_out = []
    for line in html.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith('let PA_NATIONAL') and stripped.endswith(';'):
            line = f'let PA_NATIONAL = {pa_json};\n'
        lines_out.append(line)
    html = ''.join(lines_out)

    # Inject the latest-declarations cards between the homepage markers
    _ls, _le = "<!-- LATEST:START -->", "<!-- LATEST:END -->"
    if _ls in html and _le in html:
        _pre, _rest = html.split(_ls, 1)
        _drop, _post = _rest.split(_le, 1)
        html = _pre + _ls + "\n" + _latest_cards_html + "\n    " + _le + _post
        print(f"  index.html latest block updated ({len(_latest_home)} cards)")
    else:
        print("  NOTE: LATEST markers not found in index.html - cards injection skipped")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  index.html updated with PA_NATIONAL and last-updated stamp")

print(f"\nDone. Data as of {TODAY}.")
print(f"  Declarations: {len(dec_processed):,}")
print(f"  Denials:      {len(den_processed):,}")
print(f"  Browse items: {len(browse):,}")
print(f"  Localities:   {sum(len(v) for v in locality_data.values()):,}")
