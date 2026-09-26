#!/usr/bin/env python3
"""
gen_jurisdiction_pages.py  --  Disaster Data per-jurisdiction pages (Virginia pilot).

Reads LOCALITY_DATA + BROWSE from data.js and writes one crawlable page per
Virginia jurisdiction (counties, independent cities, and tribal areas), plus a
hub, into states/virginia/. Joins each jurisdiction's declaration IDs back to
BROWSE for full per-declaration detail, shown as one sortable table with Copy
table and CSV export for hazard mitigation plans.

Pilot is scoped to one state (STATE_AB below) but written to generalize.
"""

import os, re, json, html, datetime, hashlib
from urllib.parse import quote
from dd_classify import classify

SITE = "https://disasterdata.io"
OUT_ROOT = os.environ.get("DD_OUT", ".")
SRC_ROOT = os.environ.get("DD_SRC", OUT_ROOT)
STATE_AB = os.environ.get("DD_STATE", "VA").upper()
STATE_NAME = STATE_AB
STATE_SLUG = STATE_AB.lower()
OUT_DIR = os.path.join(OUT_ROOT, "states", STATE_SLUG)

# CARTO public basemap key used by the embedded Leaflet jurisdiction maps.
# Keep this in the generator so regenerated pages retain the authenticated
# basemap URL instead of falling back to an unkeyed tile request.
CARTO_BASEMAP_KEY = "cb1_2n1q_1_ad4306e45519c0e62979dcd7"


# ---------------------------------------------------------------- data loading
def _grab_js(text, name):
    m = re.search(r"window\." + re.escape(name) + r"\s*=\s*", text)
    if not m:
        raise SystemExit("could not find window.%s" % name)
    return json.JSONDecoder().raw_decode(text, m.end())[0]


def load_data():
    p = os.path.join(SRC_ROOT, "data.js")
    if not os.path.exists(p):
        raise SystemExit("data.js not found in %s" % SRC_ROOT)

    t = open(p, encoding="utf-8").read()

    try:
        pa_county = _grab_js(t, "PA_BY_COUNTY")
    except (Exception, SystemExit):
        pa_county = {}

    return (
        _grab_js(t, "LOCALITY_DATA"),
        _grab_js(t, "BROWSE"),
        _grab_js(t, "STATE_NAMES"),
        pa_county,
    )


def load_pa_timing():
    """
    Per (county, disaster) obligation timing written by build.py to
    pa-timing.json.

    {ST: {county: {disasterNumber: [declDate, firstObl, lastObl, obl, topCat]}}}

    Kept out of data.js so the client bundle stays small; baked into each
    static page at build time here.

    Returns {} when the file is absent.
    """
    p = os.path.join(SRC_ROOT, "pa-timing.json")
    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def load_hma():
    """
    Per-jurisdiction Hazard Mitigation Assistance rollup written by build.py
    to hma.json.

    {ST: {
        matchName: {
            "fed": int,
            "n": int,
            "prog": {code:[fed,n]},
            "props": int
        }
    }}

    Returns {} when the file is absent.
    """
    p = os.path.join(SRC_ROOT, "hma.json")
    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def load_ia_timing():
    """
    Per (county, disaster) Individual Assistance written by build.py to
    ia-timing.json.

    {ST: {rawCounty: {disasterNumber: [reg, app, ihp, rr, rent, ona]}}}

    rawCounty is OpenFEMA's "Name (Type)" string, e.g. "Lake (County)". It is
    converted to the same key ia.json uses before matching; see
    _ia_raw_to_match_name().

    Returns {} when the file is absent.
    """
    p = os.path.join(SRC_ROOT, "ia-timing.json")
    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def load_event_ids():
    """
    {disasterNumber: eventId} from events.json, the same event index
    disaster.html reads, so every "full event profile" link resolves to a real
    profile. (The Compare index in data/decl-index is not used for this: its
    eventId disagrees with events.json for about 2% of declarations.) The
    weekly workflow rebuilds events.json after this script runs, so a
    declaration that is brand new this week gets its link on the following
    build; every other declaration links right away. A missing or unreadable
    file means no links.
    """
    p = os.path.join(SRC_ROOT, "events.json")

    try:
        with open(p, encoding="utf-8") as fh:
            events = json.load(fh)
    except Exception:
        return {}

    out = {}

    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict) or not ev.get("id"):
            continue

        for dn in ev.get("dns") or []:
            out[str(dn)] = ev["id"]

    return out


def _ia_raw_to_match_name(raw):
    """
    OpenFEMA Housing Assistance county strings are "Name (Type)". Identical
    rule to build.py's _ia_match_name(), which is what builds the ia.json keys:
    an independent city becomes "<base>, City of", every other county
    equivalent becomes "<base> County". Using the same rule means a
    jurisdiction gets its per-disaster IA from the same match it already gets
    its IA totals from.
    """
    raw = (raw or "").strip()

    if not raw:
        return None

    base, kind = raw, ""

    if raw.endswith(")") and "(" in raw:
        i = raw.rfind("(")
        base = raw[:i].strip()
        kind = raw[i + 1:-1].strip().lower()

    if not base:
        return None

    if kind == "city":
        if base.lower().endswith(" city"):
            base = base[:-5].strip()
        return base + ", City of"

    return base + " County"


def load_ia():
    """
    Per-jurisdiction Individual Assistance rollup written by build.py to
    ia.json.

    {ST: {
        matchName: {
            "reg":int,
            "app":int,
            "ihp":int,
            "rr":int,
            "rent":int,
            "ona":int
        }
    }}

    Returns {} when the file is absent.
    """
    p = os.path.join(SRC_ROOT, "ia.json")
    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_STATE_DECLS_CACHE = None


def load_state_decls():
    """
    Governor (state) emergency declarations resolved to county FIPS, written
    by gen_plus_sidecar.py to state-declarations.json.

    {"states": {ST: {"name","slug","coverage","total",
                     "counties": {fips5: [ {id,eo,gov,desc,date,url,
                                            types[],n,deaths,inj,dmg} ]}}}}

    A county entry means NOAA Storm Events recorded reports of the matched
    hazard in that county while the declaration was in effect. It does NOT
    mean the governor named that county in the order. See gen_plus_sidecar.py
    and the rendered method note.

    Cached, because build_state() is called once per state and the file is
    read-only for the whole run. Returns {} when the file is absent, which is
    the same graceful-degradation contract as load_ia()/load_hma().
    """
    global _STATE_DECLS_CACHE

    if _STATE_DECLS_CACHE is not None:
        return _STATE_DECLS_CACHE

    p = os.path.join(SRC_ROOT, "state-declarations.json")

    if not os.path.exists(p):
        _STATE_DECLS_CACHE = {}
        return _STATE_DECLS_CACHE

    try:
        with open(p, encoding="utf-8") as fh:
            _STATE_DECLS_CACHE = json.load(fh)
    except Exception:
        _STATE_DECLS_CACHE = {}

    return _STATE_DECLS_CACHE


def _load_county_js(filename, window_name):
    """
    Load a FIPS-keyed county dataset assigned to ``window.<window_name>``.

    The SVI and NRI inputs are optional so jurisdictions without matching
    county-equivalent data (including tribal jurisdictions) still generate.
    """
    p = os.path.join(SRC_ROOT, filename)

    if not os.path.exists(p):
        print(
            "  NOTE: %s not found; matching jurisdiction context will be skipped"
            % filename
        )
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            data = _grab_js(fh.read(), window_name)

        if not isinstance(data, dict):
            raise ValueError("window.%s is not an object" % window_name)

        print(
            "  loaded %s (%s county records)"
            % (filename, format(len(data), ","))
        )
        return data

    except (Exception, SystemExit) as ex:
        print("  WARNING: could not read %s: %s" % (filename, ex))
        return {}


def load_svi():
    """Load CDC/ATSDR 2022 county SVI data keyed by five-digit FIPS."""
    return _load_county_js("county-svi.js", "COUNTY_SVI")


def load_nri():
    """Load FEMA county National Risk Index data keyed by five-digit FIPS."""
    return _load_county_js("county-nri.js", "COUNTY_NRI")


# ---------------------------------------------------------------- helpers
def fy_of(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return y + 1 if m >= 10 else y


def fmt_date(iso):
    try:
        return datetime.datetime.strptime(
            iso, "%Y-%m-%d"
        ).strftime("%b %-d, %Y")
    except Exception:
        return iso


def pretty_title(t):
    t = (t or "").strip()
    return t.title() if t.isupper() else t


def slugify(s):
    s = (
        s.lower()
        .replace("&", "and")
        .replace(".", "")
        .replace(",", "")
    )
    s = re.sub(r"[^\w\s/-]", "", s)
    s = re.sub(r"[\s/]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)


TYPE_LONG = {
    "DR": "Major disaster",
    "EM": "Emergency",
    "FM": "Fire management",
}


# Client-side filter + column sort.
FILTER_JS = """<script>
(function(){
  var box=document.getElementById('declbox');
  if(!box) return;

  var cap=box.querySelector('.decl-count');
  var chips=box.querySelectorAll('.decl-chip');
  var table=box.querySelector('table');
  var tbody=table.querySelector('tbody');
  var heads=table.querySelectorAll('thead th');
  var rows=Array.prototype.slice.call(tbody.querySelectorAll('tr'));

  var label={
    ALL:'declarations',
    DR:'major disaster declarations',
    EM:'emergency declarations',
    FM:'fire-management declarations'
  };

  function filter(t){
    var shown=0,i;

    for(i=0;i<rows.length;i++){
      var m=(t==='ALL'||rows[i].getAttribute('data-t')===t);
      rows[i].classList.toggle('hide',!m);
      if(m) shown++;
    }

    for(i=0;i<chips.length;i++){
      chips[i].setAttribute(
        'aria-pressed',
        chips[i].getAttribute('data-t')===t?'true':'false'
      );
    }

    if(cap){
      cap.textContent='Showing '+shown+' '+(label[t]||'declarations');
    }
  }

  box.addEventListener('click',function(ev){
    var c=ev.target.closest('.decl-chip');
    if(!c||c.classList.contains('off')) return;
    filter(c.getAttribute('data-t'));
  });

  function val(row,i,k){
    var td=row.children[i];

    if(k==='num'){
      var v=td.getAttribute('data-s');
      return v==null?0:(parseFloat(v)||0);
    }

    if(k==='date'){
      return td.getAttribute('data-s')||'';
    }

    return (td.textContent||'').trim().toLowerCase();
  }

  function sortCol(i,k,dir){
    var mul=dir==='descending'?-1:1;

    rows.sort(function(a,b){
      var x=val(a,i,k), y=val(b,i,k);

      if(k==='num'){
        return (x-y)*mul;
      }

      return (x<y?-1:x>y?1:0)*mul;
    });

    for(var n=0;n<rows.length;n++){
      tbody.appendChild(rows[n]);
    }
  }

  for(var h=0;h<heads.length;h++){
    (function(th,i){
      if(!th.classList.contains('sortable')) return;

      th.addEventListener('click',function(){
        var dir=
          th.getAttribute('aria-sort')==='ascending'
          ?'descending'
          :'ascending';

        for(var k=0;k<heads.length;k++){
          heads[k].removeAttribute('aria-sort');
        }

        th.setAttribute('aria-sort',dir);
        sortCol(i,th.getAttribute('data-k')||'text',dir);
      });
    })(heads[h],h);
  }

  filter('ALL');
})();
</script>"""


def type_chips(total, dr, em, fm):
    """Filter chips with baked-in counts."""

    def chip(t, n, pressed=False):
        off = "" if n else " off"
        pr = "true" if pressed else "false"

        return (
            '<button type="button" class="decl-chip%s" '
            'data-t="%s" aria-pressed="%s">%s '
            '<span class="n">%d</span></button>'
            % (
                off,
                t,
                pr,
                t if t != "ALL" else "All",
                n,
            )
        )

    return (
        '<div class="decl-filters" role="group" '
        'aria-label="Filter declarations by type">'
        + chip("ALL", total, True)
        + chip("DR", dr)
        + chip("EM", em)
        + chip("FM", fm)
        + "</div>"
    )


def decl_num(s):
    """Sortable integer inside a FEMA declaration string."""
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else "0"


PA_CAT_LABELS = {
    "A": "Debris removal",
    "B": "Emergency protective measures",
    "C": "Roads and bridges",
    "D": "Water control facilities",
    "E": "Buildings and equipment",
    "F": "Utilities",
    "G": "Parks and recreation",
    "Z": "Management costs",
}


HMA_PROG_LABELS = {
    "HMGP": "Hazard Mitigation Grant Program",
    "HMGP POST FIRE": "Hazard Mitigation Grant Program (Post Fire)",
    "FMA": "Flood Mitigation Assistance",
    "BRIC": "Building Resilient Infrastructure and Communities",
    "PDM": "Pre-Disaster Mitigation",
    "LPDM": "Legislative Pre-Disaster Mitigation",
    "RFC": "Repetitive Flood Claims",
    "SRL": "Severe Repetitive Loss",
    "FMA SWIFT CURRENT": "Flood Mitigation Assistance Swift Current",
}


_PA_COUNTY_SUFFIXES = [
    "City and Borough",
    "Census Area",
    "County",
    "Parish",
    "Borough",
    "Municipio",
    "Municipality",
    "Island",
    "District",
]


def pa_base_kind(name):
    """
    Normalize a place name to (base, kind) for PA matching.
    """
    low = name.strip().lower()

    for suf in _PA_COUNTY_SUFFIXES:
        s = " " + suf.lower()

        if low.endswith(s):
            return low[:-len(s)].strip(), "county"

    m = (
        re.match(r"^(.*),\s*city of$", low)
        or re.match(r"^city of\s+(.+)$", low)
    )

    if m:
        return m.group(1).strip(), "city"

    return low, "other"


# County-equivalent suffixes used when matching the generated jurisdiction
# names to the FIPS-keyed CDC SVI and FEMA NRI rows.
_RISK_SUFFIXES = [
    "city and borough",
    "census area",
    "county",
    "parish",
    "borough",
    "municipio",
    "municipality",
    "independent city",
    "city",
    "island",
    "district",
]


def _risk_base(name):
    """Return a normalized county/county-equivalent name for matching."""
    s = str(name or "").strip().lower()
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    s = s.split(",", 1)[0].strip()

    for suffix in _RISK_SUFFIXES:
        tail = " " + suffix

        if s.endswith(tail):
            s = s[:-len(tail)].strip()
            break

    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _risk_kind(fips, source_name):
    """
    Classify a county-equivalent risk row as county-like or independent city.

    County-equivalent FIPS codes 500 and above identify independent cities.
    The explicit ``city`` suffix is retained as a second safety check.
    """
    fp = str(fips or "").zfill(5)
    source = str(source_name or "").strip().lower()

    try:
        city_equivalent = int(fp[2:]) >= 500
    except (TypeError, ValueError):
        city_equivalent = False

    if source.endswith(" city") or source.endswith(" independent city"):
        city_equivalent = True

    return "city" if city_equivalent else "county"


def build_risk_lookup(dataset):
    """
    Convert FIPS-keyed SVI/NRI data to a jurisdiction matching lookup.

    Keys are ``(state abbreviation, normalized place name, county/city kind)``.
    Each matched record retains its canonical five-digit FIPS/GEOID.
    """
    lookup = {}

    for fips, raw in (dataset or {}).items():
        if not isinstance(raw, dict):
            continue

        state_ab = str(raw.get("state") or "").upper().strip()
        source_name = raw.get("county") or ""

        if not state_ab or not source_name:
            continue

        rec = dict(raw)
        rec["fips"] = str(fips).zfill(5)

        key = (
            state_ab,
            _risk_base(source_name),
            _risk_kind(fips, source_name),
        )
        lookup[key] = rec

    return lookup


def jurisdiction_risk_key(j, state_ab):
    """Return the SVI/NRI lookup key for a generated jurisdiction."""
    if j.get("kind") not in ("county", "city"):
        return None

    name = j.get("name", "")

    if j.get("kind") == "city":
        name = name.replace(" (city)", "")

    return (
        state_ab.upper(),
        _risk_base(name),
        "city" if j.get("kind") == "city" else "county",
    )


STATE_FIPS = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08",
    "CT":"09","DE":"10","DC":"11","FL":"12","GA":"13","HI":"15",
    "ID":"16","IL":"17","IN":"18","IA":"19","KS":"20","KY":"21",
    "LA":"22","ME":"23","MD":"24","MA":"25","MI":"26","MN":"27",
    "MS":"28","MO":"29","MT":"30","NE":"31","NV":"32","NH":"33",
    "NJ":"34","NM":"35","NY":"36","NC":"37","ND":"38","OH":"39",
    "OK":"40","OR":"41","PA":"42","RI":"44","SC":"45","SD":"46",
    "TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53",
    "WV":"54","WI":"55","WY":"56","AS":"60","GU":"66","MP":"69",
    "PR":"72","VI":"78",
}


def make_slug(c, state_ab):
    """
    State-qualified, type-aware slug.
    """
    st = "-" + state_ab.lower()

    if c["kind"] == "county":
        base = slugify(c["base"])
        noun = slugify(c["noun"])

        return (
            base
            if base.endswith("-" + noun) or base == noun
            else base + "-" + noun
        ) + st

    if c["kind"] == "city":
        return slugify(c["base"]) + "-city" + st

    return slugify(c["base"]) + st


def kind_label(c):
    if c["kind"] == "county":
        return c["noun"]

    if c["kind"] == "city":
        return "Independent city"

    return "Tribal nation"


def kind_phrase(js):
    """
    Adaptive state jurisdiction phrase.
    """
    cnouns = sorted({
        j["noun"]
        for j in js
        if j["kind"] == "county"
    })

    parts = []

    if cnouns:
        parts.append(
            cnouns[0].lower()
            if len(cnouns) == 1
            else "county or county-equivalent"
        )

    if any(j["kind"] == "city" for j in js):
        parts.append("independent city")

    if any(j["kind"] == "tribal" for j in js):
        parts.append("tribal nation")

    if not parts:
        return "jurisdiction"

    if len(parts) == 1:
        return parts[0]

    if len(parts) == 2:
        return parts[0] + " and " + parts[1]

    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def last_complete_fy(browse):
    now = datetime.date.today()
    cur = now.year + 1 if now.month >= 10 else now.year

    avail = max(
        (r.get("fyDeclared", 0) for r in browse),
        default=cur,
    )

    return min(cur - 1, avail)


def provenance_stamp_html(lcfy):
    """A compact, unmistakable line pairing every totals figure with the fiscal
    years it covers and the date this page was last rebuilt. Placed beside the
    stat cards themselves, not just in a methodology note further down, so the
    coverage window travels with the number even if a reader never scrolls
    that far. Shared wording with gen_state_pages.py so the site is consistent."""
    as_of = datetime.date.today().strftime("%b %-d, %Y")
    return ('<p class="prov-stamp" style="font:500 .82rem/1.5 \'Public Sans\',sans-serif;'
            'color:#6b6357;margin:.4rem 0 1.1rem">'
            'Totals: FY2000 to FY%d &middot; Page last rebuilt %s '
            '&middot; the current in-progress fiscal year is not included in totals</p>'
            % (lcfy, as_of))


# ---------------------------------------------------------------- gating and freshness
MIN_DISTINCT_DECLS = 2


def _is_nationwide(rec):
    """
    True for declarations that reached nearly every jurisdiction.
    """
    title = (rec.get("declarationTitle") or "").upper()

    return "COVID" in title or "PANDEMIC" in title


def is_thin(j):
    """
    Determine whether a jurisdiction page should remain noindex.
    """
    if (j.get("pa_obl") or 0) > 0:
        return False

    distinct = sum(
        1
        for r in j.get("hmp", [])
        if not _is_nationwide(r)
    )

    return distinct < MIN_DISTINCT_DECLS


def _content_hash(j):
    """
    Stable fingerprint of rendered jurisdiction data.
    """
    payload = {
        "decl": j.get("decl", 0),
        "dr": j.get("dr", 0),
        "em": j.get("em", 0),
        "fm": j.get("fm", 0),
        "latest": j.get("latest", ""),
        "pa_obl": j.get("pa_obl", 0),
        "pa_proj": j.get("pa_proj", 0),
        "pa_cats": j.get("pa_cats", {}),
        "hma_fed": (j.get("hma") or {}).get("fed", 0),
        "hma_prog": (j.get("hma") or {}).get("prog", {}),
        "ia_reg": (j.get("ia") or {}).get("reg", 0),
        "ia_ihp": (j.get("ia") or {}).get("ihp", 0),
        "svi": j.get("svi") or {},
        "nri": j.get("nri") or {},
        "recs": sorted(
            [
                r.get("femaDeclarationString", ""),
                r.get("declarationDate", "")[:10],
                r.get("declarationType", ""),
                r.get("incidentType", ""),
                pretty_title(
                    r.get("declarationTitle", "")
                ),
            ]
            for r in j.get("hmp", [])
        ),
    }

    blob = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )

    return hashlib.sha1(
        blob.encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------- per-jurisdiction stats
def juris_stats(entry, state_ab, c, by_id, lcfy):
    disp = c["display"]
    slug = make_slug(c, state_ab)
    kind = c["kind"]

    recs = [
        by_id[i]
        for i in entry.get("ids", [])
        if i in by_id
    ]

    # Counts (stat cards, lede, hazard tallies, hub ranking) use complete fiscal
    # years only. The lists built from "hmp" below (the declaration table, its
    # Copy table and CSV exports, and the summary paragraph) carry every
    # record, including the in-progress year, so a declaration made this year is
    # on the page the week it appears in OpenFEMA instead of after Sep 30. Before
    # this, "hmp" held complete years only, which hid every declaration made since
    # Oct 1 even while the "Most recent" card already showed its date.
    complete = [
        r
        for r in recs
        if r.get("fyDeclared", 9999) <= lcfy
    ]

    open_recs = [
        r
        for r in recs
        if r.get("fyDeclared", 9999) > lcfy
    ]

    list_type = {
        "DR": 0,
        "EM": 0,
        "FM": 0,
    }

    for r in recs:
        t = r.get("declarationType", "")
        list_type[t] = list_type.get(t, 0) + 1

    by_type = {
        "DR": 0,
        "EM": 0,
        "FM": 0,
    }

    haz = {}

    for r in complete:
        t = r.get("declarationType", "")
        by_type[t] = by_type.get(t, 0) + 1

        h = r.get("incidentType", "")
        haz[h] = haz.get(h, 0) + 1

    recent = sorted(
        recs,
        key=lambda r: r.get("declarationDate", ""),
        reverse=True,
    )

    latest = (
        recent[0].get("declarationDate", "")[:10]
        if recent
        else entry.get("l", "")
    )

    return {
        "name": disp,
        "slug": slug,
        "kind": kind,
        "noun": c["noun"],
        "label": kind_label(c),
        "decl": len(complete),
        "dr": by_type["DR"],
        "em": by_type["EM"],
        "fm": by_type["FM"],
        "days": entry.get("a", 0),
        "hazards": sorted(
            haz.items(),
            key=lambda kv: -kv[1],
        ),
        "recent": recent[:40],
        "allrecs": recs,
        "hmp": sorted(
            recs,
            key=lambda r: r.get(
                "declarationDate", ""
            ),
            reverse=True,
        ),
        "list_n": len(recs),
        "list_dr": list_type["DR"],
        "list_em": list_type["EM"],
        "list_fm": list_type["FM"],
        "open_n": len(open_recs),
        "open_fys": sorted(
            {
                _rec_fy(r)
                for r in open_recs
                if _rec_fy(r)
            }
        ),
        "lcfy": lcfy,
        # The "recent declarations" panel uses a rolling 12 months, not the
        # fiscal year, so an event declared in August stays in view after
        # Oct 1 while its recovery money is still moving.
        "recent12": [
            r
            for r in sorted(
                recs,
                key=lambda r: r.get("declarationDate", ""),
                reverse=True,
            )
            if (r.get("declarationDate") or "")[:10]
            >= (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
        ],
        "latest": latest,
    }


# ---------------------------------------------------------------- in-progress year
def _rec_fy(r):
    """Fiscal year of a declaration record: OpenFEMA's fyDeclared when present,
    else derived from the declaration date."""
    fy = r.get("fyDeclared")
    if isinstance(fy, int) and 1900 < fy < 9999:
        return fy
    try:
        return fy_of(
            (r.get("declarationDate") or "")[:10]
        )
    except Exception:
        return None


def _is_open(r, lcfy):
    """Same test juris_stats() uses to leave a record out of the totals."""
    return r.get("fyDeclared", 9999) > lcfy


def open_fy_label(fys):
    """'FY2026', or 'FY2025 and FY2026' in the rare case a data lag leaves more
    than one year outside the complete-year window."""
    labels = ["FY%d" % y for y in fys]
    if len(labels) <= 1:
        return labels[0] if labels else "the current fiscal year"
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def open_fy_window(fys):
    """How to name the fiscal years not in the totals yet: (name, since, until),
    e.g. ('FY2026', 'Oct 1, 2025', 'after that year ends on Sep 30, 2026')."""
    fys = sorted({y for y in fys if y})
    if not fys:
        return "the fiscal year under way", "", "after that year ends"
    name = open_fy_label(fys)
    if len(fys) == 1:
        return name, "Oct 1, %d" % (fys[0] - 1), "after that year ends on Sep 30, %d" % fys[0]
    return name, "Oct 1, %d" % (fys[0] - 1), "once those years are complete"


def open_fy_note_html(n, fys):
    """One plain line above the declaration table saying which listed
    declarations are not in the totals yet. It names them by date. Rows carry
    no tag: a coloured "In progress" and later "FY2026" tag on a row read as a
    status, as though the declaration were still open, when all it meant was
    that the fiscal year had not ended. Renders nothing when every listed
    declaration is from a complete year."""
    if not n:
        return ""
    name, since, until = open_fy_window(fys)
    which = ("made since %s (%s)" % (since, name)) if since else ("from %s" % name)
    return ('<p class="fy-note">The totals above count complete fiscal years only. This '
            'list also includes %s %s; %s added to the totals %s.</p>'
            % ("one declaration" if n == 1 else "%d declarations" % n, which,
               "it is" if n == 1 else "they are", until))


def open_fy_intro(n, n_open, fys):
    """The sentence in the past-12-months panel saying which of its rows are in
    the complete-year totals, by date rather than by a tag on the row."""
    if not n_open:
        return ("It falls in a complete fiscal year and is counted in the totals above."
                if n == 1 else
                "All of them fall in complete fiscal years and are counted in the totals above.")
    name, since, until = open_fy_window(fys)
    verb = "it is" if n_open == 1 else "they are"
    if n_open == n:
        who = "It is" if n == 1 else "All of them are"
    elif since:
        who = ("The one made since %s is" % since) if n_open == 1 else \
              ("The %d made since %s are" % (n_open, since))
    else:
        who = "The one is" if n_open == 1 else "The %d are" % n_open
    return "%s from %s, so %s added to the complete-year totals above %s." % (who, name, verb, until)


PERIODS = {}


def load_incident_periods():
    """{femaDeclarationString: (begin, end)} from data/decl-index, the committed
    index "gen decl index.py" writes from OpenFEMA's incident begin and end
    dates. That script runs after this one in the weekly build, so a
    declaration new this week gets its incident period on the next build.
    A missing or unreadable index means no incident periods are shown."""
    out = {}
    folder = os.path.join(SRC_ROOT, "data", "decl-index")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".json") or fn == "manifest.json":
            continue
        try:
            with open(os.path.join(folder, fn), encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        st = doc.get("state") if isinstance(doc, dict) else None
        if not st:
            continue
        for d in doc.get("declarations") or []:
            if isinstance(d, dict) and d.get("id"):
                out["%s-%s" % (d["id"], st)] = (d.get("begin") or "", d.get("end") or "")
    return out


def incident_period_html(period):
    """'Incident period Jan 22 to 27, 2026' under a declared date, so a
    finished incident reads as finished. Shown only when FEMA has recorded both
    dates; nothing otherwise, rather than anything that reads as pending."""
    if not period:
        return ""
    try:
        b = datetime.datetime.strptime((period[0] or "")[:10], "%Y-%m-%d").date()
        f = datetime.datetime.strptime((period[1] or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    if f < b:
        return ""
    if f == b:
        text = b.strftime("%b %-d, %Y")
    elif (f.year, f.month) == (b.year, b.month):
        text = "%s to %d, %d" % (b.strftime("%b %-d"), f.day, f.year)
    elif f.year == b.year:
        text = "%s to %s" % (b.strftime("%b %-d"), f.strftime("%b %-d, %Y"))
    else:
        text = "%s to %s" % (b.strftime("%b %-d, %Y"), f.strftime("%b %-d, %Y"))
    return '<small>Incident period %s</small>' % text


# ---------------------------------------------------------------- recent declarations
# The "right now" view for one jurisdiction: every declaration from the past
# 12 months that names it, with the Individual Assistance and
# Public Assistance FEMA has reported for it here to date, a comparison against
# this jurisdiction's own earlier disasters, and its share of the statewide
# total. Built only from sidecars build.py already writes (ia-timing.json and
# pa-timing.json), so it needs no new fetch and renders nothing without data.
# None of it feeds a total on the page.

def _nowfy_money(n):
    """One decimal in millions and billions ($63.7M rather than $64M), for
    amounts that are still moving week to week."""
    n = float(n or 0)
    if n >= 1e9:
        return ("$%.1fB" % (n / 1e9)).replace(".0B", "B")
    if n >= 1e6:
        return ("$%.1fM" % (n / 1e6)).replace(".0M", "M")
    if n >= 1e3:
        return "$%dK" % round(n / 1e3)
    return "$%d" % round(n)


def _nowfy_int(n):
    return "{:,}".format(int(round(float(n or 0))))


def _nowfy_ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)


def nowfy_compare_sentence(dn, app, ia_dn, meta, where):
    """One sentence placing a current declaration's households approved against
    every other disaster in the same place in FEMA's household assistance data,
    which begins in 2002. Uses household counts rather than dollars, so inflation
    cannot distort it. COVID-19 is left out because its household aid was
    funeral assistance, not help after physical damage.
    Returns (sentence, covid_was_excluded)."""
    own = (meta.get(dn) or ("",))[0] or ("Disaster %s" % dn)
    others, covid = [], False

    for odn, v in ia_dn.items():
        if odn == dn:
            continue
        try:
            oapp = int(round(float(v[1] or 0)))
        except (TypeError, ValueError, IndexError):
            continue
        if oapp <= 0:
            continue
        m = meta.get(odn)
        if m and m[2] == "Biological":
            covid = True
            continue
        others.append((oapp, odn))

    data = "FEMA's household assistance data, which begins in 2002"

    if not others:
        return (
            "%s has approved %s households for assistance so far, the first %s "
            "disaster with approved households in %s."
            % (own, _nowfy_int(app), where, data)
        ), covid

    others.sort(reverse=True)
    top_app, top_dn = others[0]
    tm = meta.get(top_dn)
    top_lbl = tm[0] if tm else "disaster number %s" % top_dn
    top_yr = (" in %s" % tm[3][:4]) if (tm and tm[3]) else ""

    if app > top_app:
        ratio = float(app) / top_app
        more = (
            "more than three times as many as" if ratio >= 3 else
            "more than twice as many as" if ratio >= 2 else
            "more than"
        )
        return (
            "%s has already approved %s households for assistance, %s any other "
            "%s disaster in %s. The previous high was %s%s, with %s."
            % (own, _nowfy_int(app), more, where, data, top_lbl, top_yr,
               _nowfy_int(top_app))
        ), covid

    if app == top_app:
        return (
            "%s has approved %s households for assistance so far, tied with %s%s "
            "for the most of any %s disaster in %s."
            % (own, _nowfy_int(app), top_lbl, top_yr, where, data)
        ), covid

    rank = 1 + sum(1 for a, _ in others if a > app)

    return (
        "%s has approved %s households for assistance so far, the %s most of any "
        "%s disaster in %s. The most was %s%s, with %s."
        % (own, _nowfy_int(app), _nowfy_ordinal(rank), where, data, top_lbl,
           top_yr, _nowfy_int(top_app))
    ), covid


def recent_aid_html(j):
    """The jurisdiction's "recent declarations" panel: every declaration from the
    past 12 months that names it, with the aid FEMA has reported here so far.
    Rows from the fiscal year still in progress carry the same fiscal-year tag
    as the declaration table. Renders nothing when there are none."""
    lcfy = j.get("lcfy")
    rows = j.get("recent12") or []

    if lcfy is None or not rows:
        return ""

    e = html.escape
    name = j["name"]
    # "Richmond (city)" reads badly mid-sentence; use "City of Richmond" there.
    where = name
    if where.endswith(" (city)"):
        where = "City of " + where[:-7].strip()
    ia_t = j.get("ia_timing") or {}
    pa_t = j.get("pa_timing") or {}
    st_ia = j.get("ia_dn_state") or {}
    meta = j.get("dn_meta") or {}
    ev_ids = j.get("event_ids") or {}
    periods = j.get("periods") or {}
    na = '<span class="nowfy-na">%s</span>'
    na_fm = (
        '<span class="nowfy-na" title="Fire management declarations do not '
        'include household assistance">Not applicable</span>'
    )

    tot_app = tot_ihp = tot_pa = 0.0
    trs, ia_hits, linked, open_fys = [], [], False, set()
    n_open = 0

    for r in rows:
        fds = r.get("femaDeclarationString", "")
        dn = decl_num(fds)
        t = r.get("declarationType", "")
        ia = ia_t.get(dn)
        is_open = _is_open(r, lcfy)

        if is_open:
            n_open += 1
            if _rec_fy(r):
                open_fys.add(_rec_fy(r))

        try:
            pa = float((pa_t.get(dn) or [0, 0, 0, 0])[3] or 0)
        except (TypeError, ValueError, IndexError):
            pa = 0.0

        ev = ev_ids.get(dn)

        if ev:
            linked = True
            num_html = (
                '<a href="../../disaster.html?event=%s">%s</a>'
                % (quote(str(ev), safe=""), e(fds))
            )
        else:
            num_html = e(fds)

        head = (
            "%s<small>%s &middot; %s</small>"
            % (num_html, e(TYPE_LONG.get(t, t)), e(r.get("incidentType", "") or ""))
        )

        declared = fmt_date(r.get("declarationDate", "")) + incident_period_html(
            periods.get(fds)
        )

        if t == "FM":
            hh = ihp_html = na_fm
        elif ia and (ia[0] > 0 or ia[1] > 0 or ia[2] > 0):
            hh = (
                "%s<small>of %s registered</small>"
                % (_nowfy_int(ia[1]), _nowfy_int(ia[0]))
            )
            ihp_html = _nowfy_money(ia[2]) if ia[2] > 0 else na % "None reported"
            tot_app += ia[1]
            tot_ihp += ia[2]
            if ia[1] > 0:
                ia_hits.append((int(round(ia[1])), dn))
        else:
            hh = ihp_html = na % "None reported"

        pa_html = _nowfy_money(pa) if pa > 0 else na % "None reported yet"
        tot_pa += pa

        trs.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (head, declared, hh, ihp_html, pa_html)
        )

    tiles = ""

    if tot_app or tot_ihp or tot_pa:
        tiles = '<div class="stats">%s</div>' % "".join(
            '<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>'
            % (v, l)
            for v, l in (
                (_nowfy_int(tot_app) if tot_app else "None yet",
                 "Households approved for assistance"),
                (_nowfy_money(tot_ihp) if tot_ihp else "None yet",
                 "Individual Assistance approved"),
                (_nowfy_money(tot_pa) if tot_pa else "None yet",
                 "Public Assistance obligated"),
            )
        )

    # One comparison, for the declaration with the most households approved
    # here so far, plus this jurisdiction's share of that declaration's
    # statewide total when more than one place received assistance.
    cmp_html = ""

    if ia_hits:
        app, dn = max(ia_hits)
        text, covid = nowfy_compare_sentence(dn, app, ia_t, meta, where)

        if covid:
            text += " COVID-19 funeral assistance is left out of this comparison."

        st = st_ia.get(dn)

        if st and float(st[1] or 0) > app:
            pct = 100.0 * app / float(st[1])
            share = ("%d%%" % round(pct)) if pct >= 1 else "less than 1%"
            text += (
                " %s's %s households are %s of the %s approved across %s under %s."
                % (where, _nowfy_int(app), share, _nowfy_int(st[1]), STATE_NAME,
                   (meta.get(dn) or ("",))[0] or "this declaration")
            )

        cmp_html = '<p class="cmp">%s</p>' % e(text)

    n = len(rows)
    intro = (
        "%s has been named in %d federal declaration%s in the past 12 months. "
        "The figures are what FEMA has reported for %s to date and grow as "
        "recovery continues. %s"
        % (e(name), n, "" if n == 1 else "s", e(name),
           open_fy_intro(n, n_open, open_fys))
    )

    src = (
        "Individual Assistance is FEMA's Individuals and Households Program, from "
        "OpenFEMA's Housing Assistance data for owners and renters. Public "
        "Assistance is the obligated federal share from OpenFEMA's grant award "
        "activity, which usually starts posting weeks to months after a "
        "declaration."
    )

    if linked:
        src += (
            " Select a declaration number to open its full event profile, "
            "with the same figures for every place it covers."
        )

    return (
        '<section class="nowfy" id="recent">'
        '<p class="kick">Past 12 months</p>'
        "<h2>Recent declarations and aid so far</h2>"
        "<p>%s</p>%s"
        '<div class="tablewrap"><table><thead><tr><th>Declaration</th>'
        "<th>Declared</th><th>Households approved</th>"
        "<th>Individual Assistance</th><th>Public Assistance obligated</th>"
        "</tr></thead><tbody>%s</tbody></table></div>"
        '%s<p class="src">%s</p></section>'
        % (intro, tiles, "".join(trs), cmp_html, e(src))
    )


# ---------------------------------------------------------------- CSS
CSS = """
:root{
  --teal:#004c53;
  --cream:#f6f1e7;
  --paper:#fffdf7;
  --ink:#2b2b2b;
  --ink3:#6b6357;
  --rule:#e4dccb
}

*{box-sizing:border-box}

body{
  margin:0;
  background:var(--cream);
  color:var(--ink);
  font-family:'Public Sans',system-ui,-apple-system,sans-serif;
  line-height:1.6
}

a{color:var(--teal)}

.wrap{
  max-width:980px;
  margin:0 auto;
  padding:0 clamp(18px,4vw,40px)
}

nav.ddnav{
  position:sticky;
  top:0;
  z-index:50;
  background:rgba(246,241,231,.86);
  backdrop-filter:saturate(140%) blur(10px);
  -webkit-backdrop-filter:saturate(140%) blur(10px);
  border-bottom:1px solid #e0d8c5;
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:0 clamp(18px,4vw,48px);
  height:60px
}

nav.ddnav .brand{
  display:flex;
  align-items:baseline;
  gap:10px
}

nav.ddnav .brand .mark{
  font-family:'Fraunces',Georgia,serif;
  font-weight:600;
  font-size:19px;
  letter-spacing:-.4px;
  color:#1d1813;
  text-decoration:none
}

nav.ddnav .navlinks{
  display:flex;
  align-items:center;
  gap:4px
}

nav.ddnav .navlinks a{
  font-size:13px;
  font-weight:500;
  color:#5b5346;
  text-decoration:none;
  padding:7px 12px;
  border-radius:6px;
  transition:.15s;
  letter-spacing:.2px
}

nav.ddnav .navlinks a:hover{
  color:#1d1813;
  background:#f1ead9
}

nav.ddnav .navlinks a.on{
  color:#004c53;
  background:#d7e9ea
}

nav.ddnav .navmeta{
  font-size:11px;
  color:#938a78;
  letter-spacing:.5px;
  font-variant-numeric:tabular-nums
}

main{padding:2rem 0 1rem}

.crumb{
  font-size:.82rem;
  color:var(--ink3);
  margin:0 0 1rem
}

.crumb a{text-decoration:none}

.badge{
  display:inline-block;
  font:600 .72rem 'Public Sans',sans-serif;
  text-transform:uppercase;
  letter-spacing:.04em;
  padding:.2rem .6rem;
  border-radius:999px;
  margin-bottom:.6rem
}

.badge.county{
  color:#004c53;
  background:#d7e9ea
}

.badge.city{
  color:#8a5a2b;
  background:#f3e4d2
}

.badge.tribal{
  color:#6a2f6a;
  background:#efddef
}

h1{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:clamp(1.7rem,4vw,2.5rem);
  line-height:1.1;
  margin:.2rem 0 .6rem
}

h2{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:1.3rem;
  margin:2.2rem 0 .8rem
}

.lede{
  font-size:1.08rem;
  max-width:62ch
}

.jsummary{
  margin:1.1rem 0 .4rem
}

.jsummary p{
  margin:0;
  font-size:1rem;
  color:var(--ink);
  max-width:66ch
}

.pasplit{margin:1.6rem 0}
.pasplit h2{margin-top:0}
.patotal{font-size:1.02rem;margin:.2rem 0 .8rem;font-variant-numeric:tabular-nums}
.patotal b{color:#004c53}
.pabar{display:flex;height:12px;border-radius:4px;overflow:hidden;margin:0 0 .7rem}
.pabar span{display:block;min-width:2px}
.paline{font-size:.92rem;margin:0 0 .6rem;max-width:68ch;font-variant-numeric:tabular-nums}
.paline b{color:#004c53}
.panote{font-size:.82rem;color:#6b6357;margin:0;max-width:68ch}
.kinds{background:#fffdf7;border:1px solid #e4dccb;border-radius:12px;padding:.9rem 1.2rem;margin:.5rem 0 .8rem;font-size:.9rem}
.kinds p{margin:.35rem 0}
.kinds b{color:#004c53}
.stats{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(135px,1fr));
  gap:.7rem;
  margin:1.5rem 0
}

.stat{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:12px;
  padding:.85rem 1rem
}

.stat .n{
  font-family:'Fraunces',Georgia,serif;
  font-size:1.7rem;
  color:var(--teal);
  font-weight:600;
  line-height:1
}

.stat .l{
  font-size:.78rem;
  color:var(--ink3);
  margin-top:.3rem
}

ul.haz{
  list-style:none;
  padding:0;
  margin:.5rem 0;
  display:flex;
  flex-wrap:wrap;
  gap:.5rem
}

ul.haz li{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:999px;
  padding:.3rem .8rem;
  font-size:.85rem
}

ul.haz b{color:var(--teal)}

.tablewrap{
  overflow-x:auto;
  border:1px solid var(--rule);
  border-radius:12px;
  background:var(--paper)
}

table{
  border-collapse:collapse;
  width:100%;
  font-size:.86rem;
  min-width:560px
}

th,td{
  text-align:left;
  padding:.55rem .8rem;
  border-bottom:1px solid var(--rule);
  vertical-align:top
}

th{
  font-size:.74rem;
  text-transform:uppercase;
  letter-spacing:.03em;
  color:var(--ink3);
  background:#faf6ec
}

tr:last-child td{border-bottom:none}

.tag{
  font-weight:700;
  color:var(--teal)
}

.copybtn{
  font:600 .8rem 'Public Sans',sans-serif;
  color:#004c53;
  background:none;
  border:1px solid #004c53;
  border-radius:8px;
  padding:.4rem .85rem;
  cursor:pointer;
  margin-top:.8rem
}

.decl-filters{
  display:flex;
  flex-wrap:wrap;
  gap:.4rem;
  margin:.2rem 0 .5rem
}

.decl-chip{
  font:700 .82rem/1 'Public Sans',sans-serif;
  color:var(--teal);
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:999px;
  padding:.42rem .72rem;
  cursor:pointer;
  display:inline-flex;
  align-items:center;
  gap:.42rem
}

.decl-chip .n{
  background:#eef3f2;
  border-radius:999px;
  padding:.06rem .44rem;
  font-size:.76rem;
  font-weight:700
}

.decl-chip[aria-pressed="true"]{
  background:var(--teal);
  color:#fff;
  border-color:var(--teal)
}

.decl-chip[aria-pressed="true"] .n{
  background:rgba(255,255,255,.22);
  color:#fff
}

.decl-chip.off{
  opacity:.42;
  cursor:default
}

.decl-count{
  font-size:.82rem;
  color:var(--ink3);
  margin:.05rem 0 .55rem
}

.fy-note{
  font-size:.84rem;
  color:var(--ink3);
  background:#fdf8f3;
  border:1px solid #efdccd;
  border-radius:10px;
  padding:.55rem .8rem;
  margin:.1rem 0 .6rem;
  max-width:72ch
}

.nowfy{
  background:#fffaf5;
  border:1px solid #efdccd;
  border-radius:14px;
  padding:1.1rem 1.25rem;
  margin:1.6rem 0
}

.nowfy h2{
  margin:.15rem 0 .5rem
}

.nowfy .kick{
  font:700 .7rem/1.2 'Public Sans',sans-serif;
  letter-spacing:.08em;
  text-transform:uppercase;
  color:#8f3f1a;
  margin:0
}

.nowfy>p{
  max-width:70ch;
  margin:.2rem 0 .8rem;
  font-size:.95rem
}

.nowfy .stats{
  margin:.9rem 0 1rem
}

.nowfy .stat{
  background:#fff
}

.nowfy td small{
  display:block;
  color:var(--ink3);
  font-size:.76rem;
  margin-top:.15rem
}

.nowfy .nowfy-na{
  color:var(--ink3);
  font-size:.82rem
}

.nowfy p.cmp{
  font-size:.93rem;
  margin:.9rem 0 0
}

.nowfy p.src{
  font-size:.8rem;
  color:var(--ink3);
  margin:.7rem 0 0
}

.tablewrap.scroll{
  max-height:430px;
  overflow-y:auto
}

.tablewrap.scroll thead th{
  position:sticky;
  top:0;
  z-index:1
}

tr.hide{display:none}

th.sortable{
  cursor:pointer;
  user-select:none;
  -webkit-user-select:none;
  white-space:nowrap
}

th.sortable::after{
  content:"↕";
  opacity:.32;
  margin-left:.35em;
  font-weight:400
}

th.sortable:hover{color:var(--teal)}

th[aria-sort="ascending"]::after{
  content:"↑";
  opacity:.95
}

th[aria-sort="descending"]::after{
  content:"↓";
  opacity:.95
}

.risk-section{margin:2.4rem 0}

.section-heading-row{
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:1rem;
  margin-bottom:1rem
}

.section-heading-row h2{margin:0 0 .25rem}

.section-deck{
  margin:0;
  color:var(--ink3);
  font-size:.92rem;
  max-width:66ch
}

.risk-fips{
  font-size:.72rem;
  font-weight:700;
  letter-spacing:.04em;
  text-transform:uppercase;
  color:var(--ink3);
  white-space:nowrap
}

.risk-grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:1rem
}

.risk-card{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:16px;
  padding:1.15rem 1.2rem;
  box-shadow:0 1px 0 rgba(43,43,43,.03)
}

.risk-card h3{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:1.18rem;
  line-height:1.2;
  margin:.15rem 0 0
}

.risk-kicker{
  font-size:.69rem;
  font-weight:800;
  letter-spacing:.09em;
  text-transform:uppercase;
  color:#8a5a2b
}

.risk-version{
  color:var(--ink3);
  font-size:.78rem;
  margin:.18rem 0 .9rem
}

.risk-score{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:2.15rem;
  font-weight:600;
  line-height:1
}

.risk-score.na{font-size:1.55rem}

.risk-score-label{
  color:var(--ink3);
  font-size:.76rem;
  margin-top:.2rem
}

.risk-interpret{
  color:var(--ink3);
  font-size:.83rem;
  margin:.7rem 0
}

.theme-list{margin-top:.9rem}

.theme-row{margin:.58rem 0}

.theme-head{
  display:flex;
  justify-content:space-between;
  gap:.8rem;
  font-size:.76rem
}

.theme-head b{
  color:var(--teal);
  font-variant-numeric:tabular-nums
}

.theme-track{
  height:6px;
  overflow:hidden;
  border-radius:999px;
  background:#e8e0d0;
  margin-top:.25rem
}

.theme-track span{
  display:block;
  height:100%;
  border-radius:inherit;
  background:#4c8b90
}

.nri-lead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:1rem
}

.risk-rating{
  display:inline-block;
  border-radius:999px;
  background:#f3e4d2;
  color:#7a4a20;
  font-size:.72rem;
  font-weight:700;
  padding:.3rem .62rem;
  text-align:center
}

.risk-mini-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:.55rem;
  margin-top:1rem
}

.risk-mini{
  border-top:1px solid var(--rule);
  padding-top:.55rem;
  min-width:0
}

.risk-mini span,
.risk-mini small{
  display:block;
  color:var(--ink3);
  font-size:.68rem;
  line-height:1.35
}

.risk-mini b{
  display:block;
  color:var(--teal);
  font-size:.95rem;
  margin:.18rem 0;
  overflow-wrap:anywhere
}

.risk-source{
  color:var(--ink3);
  font-size:.78rem;
  margin:.9rem 0 0
}

.risk-source a{font-weight:600}

.risk-caution{
  background:#eef4f4;
  border:1px solid #cfe0e0;
  border-radius:10px;
  padding:.8rem .9rem;
  margin-top:.8rem;
  color:#3f5557;
  font-size:.8rem
}

.method{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:12px;
  padding:1.2rem 1.4rem;
  margin:2rem 0;
  font-size:.92rem
}

.method h2{
  margin-top:0;
  font-size:1.1rem
}

/* Citation block */
.citation{
  background:#153c40;
  color:#eef9f8;
  border-radius:14px;
  padding:1.15rem 1.25rem;
  margin:2rem 0
}

.citation h2{
  color:#fff;
  margin:0 0 .45rem;
  font-size:1.2rem
}

.citation p{
  font-size:.84rem;
  color:#d6e9e7;
  margin:.2rem 0 .85rem;
  max-width:68ch
}

.cite-tabs{
  display:flex;
  flex-wrap:wrap;
  gap:.4rem;
  margin:0 0 .7rem
}

.citefmt{
  font:700 .78rem 'Public Sans',sans-serif;
  color:#d6e9e7;
  background:transparent;
  border:1px solid rgba(255,255,255,.28);
  border-radius:999px;
  padding:.38rem .72rem;
  cursor:pointer
}

.citefmt:hover{
  background:rgba(255,255,255,.08)
}

.citefmt[aria-pressed="true"]{
  background:#fff;
  color:#153c40;
  border-color:#fff
}

.cite-text{
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.14);
  border-radius:9px;
  padding:.85rem;
  font-size:.79rem;
  line-height:1.6;
  color:#fff
}

.citation .copybtn{
  color:#fff;
  border-color:#bcd8d5
}

.citation .copybtn:hover{
  background:rgba(255,255,255,.08)
}

.pa-note{
  font-size:.9rem;
  color:var(--ink3);
  max-width:64ch;
  margin:.4rem 0 .8rem
}

table.pa-cat tfoot td{
  font-weight:700;
  color:var(--teal);
  border-top:2px solid var(--rule);
  background:#faf6ec
}

.pa-cat .catcode{
  color:var(--ink3);
  font-weight:400;
  font-size:.85em;
  margin-left:.15em
}

table.pa-cat td:nth-child(2),
table.pa-cat th:nth-child(2),
table.pa-cat td:nth-child(3),
table.pa-cat th:nth-child(3){
  text-align:right;
  font-variant-numeric:tabular-nums;
  white-space:nowrap
}

.jgrid{
  display:flex;
  flex-wrap:wrap;
  gap:.4rem .7rem;
  margin:.6rem 0
}

.jgrid a{
  font-size:.86rem;
  text-decoration:none
}

ol.rank{
  padding-left:0;
  list-style:none;
  counter-reset:r
}

ol.rank li{
  counter-increment:r;
  display:flex;
  align-items:baseline;
  gap:.7rem;
  padding:.45rem 0;
  border-bottom:1px solid var(--rule)
}

ol.rank li::before{
  content:counter(r);
  font-family:'Fraunces',serif;
  color:var(--ink3);
  min-width:2.6ch;
  text-align:right
}

ol.rank a{
  text-decoration:none;
  font-weight:600
}

ol.rank .k{
  font-size:.7rem;
  text-transform:uppercase;
  letter-spacing:.04em;
  color:var(--ink3)
}

ol.rank .c{
  color:var(--ink3);
  font-size:.9rem;
  margin-left:auto
}

footer.site{
  border-top:1px solid var(--rule);
  margin-top:2rem;
  padding:1.5rem 0;
  color:var(--ink3);
  font-size:.85rem
}

footer.site a{color:var(--ink3)}

nav.ddnav .navburger{
  display:none;
  flex-direction:column;
  justify-content:center;
  gap:5px;
  width:40px;
  height:40px;
  background:none;
  border:0;
  cursor:pointer;
  padding:8px;
  border-radius:8px
}

nav.ddnav .navburger span{
  display:block;
  height:2px;
  width:100%;
  background:#1d1813;
  border-radius:2px;
  transition:.2s
}

nav.ddnav .navburger[aria-expanded="true"] span:nth-child(1){
  transform:translateY(7px) rotate(45deg)
}

nav.ddnav .navburger[aria-expanded="true"] span:nth-child(2){
  opacity:0
}

nav.ddnav .navburger[aria-expanded="true"] span:nth-child(3){
  transform:translateY(-7px) rotate(-45deg)
}

.mobilemenu{display:none}

@media(max-width:720px){
  .section-heading-row{
    align-items:flex-start;
    flex-direction:column
  }

  .risk-grid{grid-template-columns:1fr}

  .risk-mini-grid{grid-template-columns:1fr}

  nav.ddnav{
    flex-direction:row;
    align-items:center;
    justify-content:space-between;
    height:60px;
    padding-top:0;
    padding-bottom:0
  }

  nav.ddnav .navmeta{display:none}
  nav.ddnav .navlinks{display:none !important}
  nav.ddnav .navburger{display:flex}

  .mobilemenu:not([hidden]){
    display:flex;
    flex-direction:column;
    gap:2px;
    padding:10px clamp(18px,4vw,48px) 18px;
    background:#f6f1e7;
    border-bottom:1px solid #e0d8c5;
    position:sticky;
    top:60px;
    z-index:49
  }

  .mobilemenu>a{
    font-size:15px;
    font-weight:500;
    color:#1d1813;
    text-decoration:none;
    padding:11px 12px;
    border-radius:8px
  }

  .mobilemenu>a.on{
    color:#004c53;
    background:#d7e9ea
  }

  .mm-section{
    display:flex;
    flex-direction:column;
    gap:2px;
    padding:6px 0;
    margin:2px 0;
    border-top:1px solid #e0d8c5
  }

  .mm-label{
    font-size:11px;
    font-weight:700;
    letter-spacing:1.2px;
    text-transform:uppercase;
    color:#938a78;
    padding:6px 12px 2px
  }

  .mm-section a{
    font-size:15px;
    font-weight:500;
    color:#5b5346;
    text-decoration:none;
    padding:10px 12px 10px 22px;
    border-radius:8px
  }

  .mm-section a.on{
    color:#004c53;
    background:#d7e9ea
  }
}
""".strip()


FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600'
    '&family=Public+Sans:wght@400;500;600;700'
    '&display=swap" rel="stylesheet">'
)


HEAD = (
    FONTS
    + '<link rel="stylesheet" '
      'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
    + "<style>"
    + CSS
    + """
#locmap{
  height:320px;
  border-radius:10px;
  border:1px solid #e4dccb;
  margin:1rem 0 .5rem;
  background:#f6f1e7
}

@media(max-width:600px){
  #locmap{height:240px}
}

.locmap-cap{
  font:600 .86rem/1.3 'Public Sans',sans-serif;
  color:#004c53;
  margin:0 0 1.5rem;
  text-align:center
}

.locmap-cap b{font-weight:700}

.loc-lbl{
  background:transparent;
  border:none;
  box-shadow:none;
  color:#fff;
  font:700 12px/1 'Public Sans',sans-serif;
  padding:0;
  white-space:nowrap;
  pointer-events:none;
  text-shadow:
    0 1px 2px rgba(0,0,0,.6),
    0 0 3px rgba(0,0,0,.55)
}

.loc-lbl:before,
.loc-lbl:after{
  display:none !important
}
"""
    + "</style>"
)


def header_html():
    return '<script src="/nav.js"></script>'


def footer_html():
    return (
        '<footer class="site"><div class="wrap">'
        'Disaster Data &middot; built from FEMA OpenFEMA, '
        'refreshed weekly &middot; '
        '<a href="https://forms.gle/NZ6bSadoXrKYHjjH8" '
        'target="_blank" rel="noopener">Report a data issue</a>'
        ' &middot; '
        '<a href="../../about.html">About and contact</a>'
        '</div></footer>'
        '<!-- Cloudflare Web Analytics -->'
        '<script defer '
        'src="https://static.cloudflareinsights.com/beacon.min.js" '
        'data-cf-beacon=\'{"token": '
        '"ceea2416f66a424981ba37fcb9440d68"}\'></script>'
        '<!-- End Cloudflare Web Analytics -->'
        '<script>'
        '(function(){'
        'var b=document.querySelector(".navburger"),'
        'm=document.querySelector(".mobilemenu");'
        'if(b&&m){'
        'b.addEventListener("click",function(){'
        'var o=b.getAttribute("aria-expanded")==="true";'
        'b.setAttribute("aria-expanded",String(!o));'
        'if(o){'
        'm.setAttribute("hidden","");'
        '}else{'
        'm.removeAttribute("hidden");'
        '}'
        '});'
        '}'
        '})();'
        '</script>'
    )


def _oxford(items):
    items = [i for i in items]

    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return items[0] + " and " + items[1]

    return ", ".join(items[:-1]) + ", and " + items[-1]


def method_html(kind, spans=False):
    extra = {
        "county":
            "This page counts declarations that named this jurisdiction "
            "as a designated area.",

        "city":
            "Independent cities are counted separately from the counties "
            "around them, matching how FEMA designates them.",

        "tribal":
            (
                "Tribal areas are counted as their own jurisdictions, "
                "separate from the counties they sit within."
                + (
                    " Because this nation's lands cross state lines, the "
                    "declarations FEMA recorded for it in each state are "
                    "combined here so its record is not split across pages."
                    if spans
                    else ""
                )
            ),
    }[kind]

    return (
        '<section class="method">'
        '<h2>How these numbers are built</h2>'
        "<p>"
        "Drawn from FEMA's OpenFEMA Disaster Declarations Summaries, "
        "rebuilt each week. "
        "A declaration is counted here once for each designated area it "
        "names, so a single disaster covering many localities is counted "
        "in each one. For that reason these jurisdiction counts do not "
        "sum to %s's statewide total. "
        "%s "
        "Totals cover complete fiscal years (Oct 1 to Sep 30). "
        "Declarations from the fiscal year still in progress are listed in "
        "the tables on this page but are not counted in "
        "the totals until the year is complete. Uses OpenFEMA data but is not "
        "endorsed by or affiliated with FEMA."
        "</p>"
        "</section>"
        % (STATE_NAME, extra)
    )


# ---------------------------------------------------------------- citation feature
def citation_html(j, canonical):
    """
    Visible citation helper for a generated jurisdiction profile.

    The access date is filled in client-side so it reflects the day the
    reader actually uses the page rather than the date the static file
    was built.

    Keep the source statement limited to data this generator actually uses.
    """
    e = html.escape

    display_name = j["name"].replace(" (city)", "")

    title = (
        "%s, %s: Disaster Declarations, Federal Assistance, "
        "and Mitigation History"
        % (
            display_name,
            STATE_NAME,
        )
    )

    bibkey = "disasterdata_%s_%s" % (
        slugify(display_name).replace("-", "_"),
        STATE_AB.lower(),
    )

    return (
        '<section class="citation" id="cite" '
        'data-cite-title="%s" '
        'data-cite-url="%s" '
        'data-cite-key="%s">'

        '<h2>Cite this profile</h2>'

        '<p>'
        'Choose a citation style, then copy the formatted citation. '
        'This profile is derived from FEMA OpenFEMA data and is updated '
        'as the underlying Disaster Data build is refreshed.'
        '</p>'

        '<div class="cite-tabs" '
        'role="group" aria-label="Citation format">'

        '<button class="citefmt" type="button" '
        'data-fmt="apa" aria-pressed="true">'
        'APA'
        '</button>'

        '<button class="citefmt" type="button" '
        'data-fmt="chicago" aria-pressed="false">'
        'Chicago'
        '</button>'

        '<button class="citefmt" type="button" '
        'data-fmt="plain" aria-pressed="false">'
        'Plain text'
        '</button>'

        '<button class="citefmt" type="button" '
        'data-fmt="bibtex" aria-pressed="false">'
        'BibTeX'
        '</button>'

        '</div>'

        '<div class="cite-text" '
        'id="citationText" aria-live="polite"></div>'

        '<button class="copybtn citecopy" type="button">'
        'Copy citation'
        '</button>'

        '</section>'
        % (
            e(title, quote=True),
            e(canonical, quote=True),
            e(bibkey, quote=True),
        )
    )


# ---------------------------------------------------------------- PA category breakdown
def _money_short(n):
    n = float(n or 0)
    if n >= 1e9:
        return ("$%.1fB" % (n / 1e9)).replace(".0B", "B")
    if n >= 1e6:
        return "$%dM" % round(n / 1e6)
    if n >= 1e3:
        return "$%dK" % round(n / 1e3)
    return "$%d" % round(n)


# Segment order is the order they appear in the bar and in the sentence below it.
PA_SEGS = (
    ("dr",    "#004c53", "major disasters other than COVID-19"),
    ("em",    "#5a8f8c", "emergency declarations"),
    ("fm",    "#9fb8b6", "fire management assistance"),
    ("covid", "#a89a80", "COVID-19"),
    ("resid", "#d3cab5", "not tied to a single declaration"),
)

PA_CLAUSE = {
    "dr":    "<b>%s</b> followed major disasters other than COVID-19.",
    "em":    "<b>%s</b> followed emergency declarations, which cover debris removal "
             "and emergency protective work only.",
    "fm":    "<b>%s</b> went to fire management assistance grants.",
    "resid": "<b>%s</b> appears in FEMA's county totals but is not tied to a single "
             "declaration in the obligation timing file, so it is left unattributed "
             "here rather than assigned to a type.",
}


def juris_pa_split(j):
    """
    Public Assistance for one jurisdiction, split by the kind of declaration the
    money followed.

    The headline stays j["pa_obl"], which comes from PA_BY_COUNTY, so the split can
    never contradict the figure already shown in the stat card and the summary
    paragraph. The split itself comes from j["pa_timing"], the only source carrying
    a disaster number per obligation, and those are two separate passes in build.py
    with nothing guaranteeing they agree. Anything the split cannot attribute is
    reported as an explicit residual instead of being quietly dropped, so the
    segments always add up to the headline by construction.
    """
    total = float(j.get("pa_obl") or 0)
    timing = j.get("pa_timing") or {}

    meta = {}
    for r in j.get("allrecs") or j.get("hmp") or []:
        m = re.search(r"(\d+)", r.get("femaDeclarationString", "") or "")
        if m:
            meta[m.group(1)] = (
                r.get("declarationType", "") or "",
                r.get("incidentType", "") or "",
            )

    buckets = {"dr": 0.0, "em": 0.0, "fm": 0.0, "covid": 0.0}
    attributed = 0.0
    for dn, v in timing.items():
        try:
            obl = float(v[3] or 0)
        except (TypeError, ValueError, IndexError):
            continue
        if obl <= 0:
            continue
        dtype, itype = meta.get(str(dn), ("", ""))
        if itype == "Biological":      # every COVID declaration, DR and EM alike
            key = "covid"
        elif dtype == "DR":
            key = "dr"
        elif dtype == "EM":
            key = "em"
        elif dtype == "FM":
            key = "fm"
        else:
            continue                   # unknown declaration -> left in the residual
        buckets[key] += obl
        attributed += obl

    if attributed > total:
        total = attributed

    resid = total - attributed
    if resid < 1:
        resid = 0.0

    out = {"total": total, "attributed": attributed, "resid": resid}
    out.update(buckets)
    return out


def pa_split_html(j):
    """
    The split bar. Renders nothing when the jurisdiction has no PA on record, and
    each segment renders only when it is non-zero, so a place with no fire
    management grants never sees an empty sliver.
    """
    pa = juris_pa_split(j)
    total = pa["total"]
    if total <= 0:
        return ""

    segs = [
        (k, col, lab, pa.get(k) or 0.0)
        for k, col, lab in PA_SEGS
        if (pa.get(k) or 0.0) > 0
    ]
    if not segs:
        return ""

    bar = "".join(
        '<span style="flex:%.5f;background:%s" title="%s %s"></span>'
        % (v / total, col, _money_short(v), lab)
        for _k, col, lab, v in segs
    )

    clauses = []
    for k, _col, _lab, v in segs:
        if k == "covid":
            clauses.append(
                "<b>%s</b>, or %d%% of the total, was COVID-19, which every county "
                "in the country received."
                % (_money_short(v), round(100.0 * v / total))
            )
        else:
            clauses.append(PA_CLAUSE[k] % _money_short(v))

    return (
        '<section class="pasplit">'
        '<h2>Federal Public Assistance obligated</h2>'
        '<p class="patotal"><b>%s</b> has been obligated to %s in Public Assistance '
        'since FY2000.</p>'
        '<div class="pabar">%s</div>'
        '<p class="paline">%s</p>'
        '<p class="panote">Obligated is the committed share, not necessarily spent, '
        'and can be revised as projects close out.</p>'
        '</section>'
        % (_money_short(total), html.escape(j["name"]), bar, " ".join(clauses))
    )


def decl_kinds_html():
    """
    Plain-English explanation of the three declaration types, placed with the table
    it explains. The acronyms stay, demoted to the reference identifiers a
    practitioner needs rather than the label a reader has to decode.
    """
    return (
        '<div class="kinds">'
        '<p><b>Major disaster (DR).</b> The big one. Opens the full toolbox: repair '
        'money for public infrastructure, help for households, and mitigation '
        'funding to reduce the next loss.</p>'
        '<p><b>Emergency (EM).</b> Narrower and usually faster, for protective work '
        'before or during an incident. Capped, and rarely brings household '
        'assistance. Nearly every county has one from COVID-19.</p>'
        '<p><b>Fire management (FM).</b> Cost sharing to fight a wildfire as it '
        'burns. Not a disaster declaration, and it does not open recovery '
        'programs.</p>'
        '</div>'
    )


def pa_breakdown_html(j):
    """
    Per-jurisdiction Public Assistance category table.
    """
    cats = j.get("pa_cats") or {}

    if not cats:
        return ""

    rows_data = sorted(
        (
            [
                code,
                PA_CAT_LABELS.get(code, "Other"),
                vals[0],
                vals[1],
            ]
            for code, vals in cats.items()
        ),
        key=lambda x: -x[2],
    )

    total_obl = sum(r[2] for r in rows_data)
    total_proj = sum(r[3] for r in rows_data)

    money = lambda n: "$" + format(
        int(round(n)),
        ",",
    )

    body = "".join(
        (
            "<tr>"
            "<td>%s<span class='catcode'>(%s)</span></td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
        )
        % (
            html.escape(lbl),
            html.escape(code),
            format(proj, ","),
            money(obl),
        )
        for code, lbl, obl, proj in rows_data
    )

    foot = (
        "<tr>"
        "<td>All categories</td>"
        "<td>%s</td>"
        "<td>%s</td>"
        "</tr>"
        % (
            format(total_proj, ","),
            money(total_obl),
        )
    )

    return (
        '<section>'
        '<h2>Federal Public Assistance by category</h2>'

        '<p class="pa-note">'
        'Federal share obligated to this jurisdiction under FEMA Public '
        'Assistance since 2000, grouped by damage category. Figures are '
        'rounded to the nearest dollar and reflect obligations, which may '
        'change as projects close out.'
        '</p>'

        '<div class="tablewrap">'
        '<table class="pa-cat">'

        '<thead>'
        '<tr>'
        '<th>Category</th>'
        '<th>Projects</th>'
        '<th>Federal share obligated</th>'
        '</tr>'
        '</thead>'

        '<tbody>%s</tbody>'

        '<tfoot>%s</tfoot>'

        '</table>'
        '</div>'
        '</section>'
        % (
            body,
            foot,
        )
    )


# ---------------------------------------------------------------- data-driven prose
def _money_words(n):
    """
    Public Assistance dollars in readable words.
    """
    n = float(n or 0)

    if n >= 1e9:
        return "about $%.1f billion" % (n / 1e9)

    if n >= 1e6:
        return "about $%.1f million" % (n / 1e6)

    return "$" + format(
        int(round(n)),
        ",",
    )


def summary_html(j):
    """
    Short plain-language jurisdiction summary.
    """
    hmp = j.get("hmp", [])

    if not hmp:
        return ""

    e = html.escape
    name = e(j["name"])

    dates = sorted(
        r.get("declarationDate", "")[:10]
        for r in hmp
        if r.get("declarationDate")
    )

    if dates and dates[0][:4] != dates[-1][:4]:
        span = "between %s and %s" % (
            dates[0][:4],
            dates[-1][:4],
        )

    elif dates:
        span = "in %s" % dates[0][:4]

    else:
        span = "since FY2000"

    # hmp now carries the in-progress fiscal year too, so the span and the
    # "most recent major disaster" line below reach this year. The count stays
    # the complete-year total the lede and stat cards use, with any in-progress
    # declarations named separately so the two numbers never contradict.
    n_open = j.get("open_n", 0)
    open_lbl = open_fy_label(j.get("open_fys") or [])

    if n_open and j["decl"]:
        count_txt = (
            "covering %d declaration%s in complete fiscal years, plus %d "
            "so far in %s"
            % (
                j["decl"],
                "" if j["decl"] == 1 else "s",
                n_open,
                open_lbl,
            )
        )

    elif n_open:
        count_txt = (
            "covering %d declaration%s so far in %s"
            % (
                n_open,
                "" if n_open == 1 else "s",
                open_lbl,
            )
        )

    else:
        count_txt = (
            "covering %d declaration%s in all"
            % (
                j["decl"],
                "" if j["decl"] == 1 else "s",
            )
        )

    sents = [
        (
            "The federal disaster record for %s runs %s, %s."
            % (
                name,
                span,
                count_txt,
            )
        )
    ]

    drs = [
        r
        for r in hmp
        if r.get("declarationType") == "DR"
    ]

    if drs:
        title = pretty_title(
            drs[0].get("declarationTitle", "")
        ).strip()

        yr = drs[0].get(
            "declarationDate",
            "",
        )[:4]

        if title and yr:
            sents.append(
                "Its most recent major disaster declaration was %s in %s."
                % (
                    e(title),
                    yr,
                )
            )

    hz = j.get("hazards") or []

    if len(hz) >= 2:
        sents.append(
            "The hazards behind these declarations were most often %s."
            % _oxford(
                [
                    e(h.lower())
                    for h, _ in hz[:3]
                ]
            )
        )

    elif len(hz) == 1:
        sents.append(
            "Every one was tied to %s."
            % e(
                hz[0][0].lower()
            )
        )

    if (j.get("pa_obl") or 0) > 0:
        tail = (
            ", most of it for %s"
            % e(
                j["pa_top_cat"].lower()
            )
            if j.get("pa_top_cat")
            else ""
        )

        sents.append(
            "Since 2000, FEMA has obligated %s in Public Assistance "
            "funding to the jurisdiction%s."
            % (
                _money_words(
                    j["pa_obl"]
                ),
                tail,
            )
        )

    return (
        '<section class="jsummary">'
        '<p>%s</p>'
        '</section>'
        % " ".join(sents)
    )


def pa_timing_html(j):
    """
    Per-disaster federal obligation timing.
    """
    timing = j.get("pa_timing") or {}

    if not timing:
        return ""

    e = html.escape

    meta = {}

    for r in j.get("hmp", []):
        m = re.search(
            r"(\d+)",
            r.get(
                "femaDeclarationString",
                "",
            ),
        )

        if m:
            meta[m.group(1)] = (
                pretty_title(
                    r.get(
                        "declarationTitle",
                        "",
                    )
                )
                or r.get(
                    "incidentType",
                    "",
                )
            )

    def _days(d1, d2):
        try:
            a = datetime.datetime.strptime(
                d1,
                "%Y-%m-%d",
            )

            b = datetime.datetime.strptime(
                d2,
                "%Y-%m-%d",
            )

            return (b - a).days

        except Exception:
            return None

    rows = []

    for dn, v in timing.items():
        decl, first, last, obl, _tc = (
            list(v)
            + [
                "",
                "",
                "",
                0,
                "",
            ]
        )[:5]

        if not decl or not first:
            continue

        fd = _days(
            decl,
            first,
        )

        ld = _days(
            decl,
            last,
        )

        if fd is None or fd < 0:
            continue

        if ld is None or ld < fd:
            ld = fd

        rows.append({
            "decl": decl,
            "first": fd,
            "last": ld,
            "obl": float(
                obl or 0
            ),
            "name": meta.get(
                str(dn),
                "DR-" + str(dn),
            ),
        })

    if not rows:
        return ""

    rows.sort(
        key=lambda r: r["decl"],
        reverse=True,
    )

    rows = rows[:6]

    maxdays = max(
        (
            r["last"]
            for r in rows
        ),
        default=365,
    )

    years = max(
        1,
        (maxdays + 364) // 365,
    )

    scale = years * 365

    fs = sorted(
        r["first"]
        for r in rows
    )

    n = len(fs)

    med = (
        fs[n // 2]
        if n % 2
        else (
            fs[n // 2 - 1]
            + fs[n // 2]
        ) // 2
    )

    def _money(x):
        x = float(x or 0)

        if x >= 1e6:
            return "$%.1fM" % (
                x / 1e6
            )

        if x >= 1e3:
            return "$%.0fK" % (
                x / 1e3
            )

        return "$%d" % int(x)

    bars = []

    for r in rows:
        gapw = (
            r["first"]
            / scale
            * 100.0
        )

        floww = (
            (
                r["last"]
                - r["first"]
            )
            / scale
            * 100.0
        )

        bars.append(
            '<div class="ft-row">'

            '<div class="ft-top">'

            '<span class="ft-name">'
            '%s '
            '<span class="ft-date">%s</span>'
            '</span>'

            '<span class="ft-val">%s</span>'

            '</div>'

            '<div class="ft-track">'

            '<span class="ft-gap" '
            'style="width:%.1f%%">'
            '</span>'

            '<span class="ft-flow" '
            'style="left:%.1f%%;width:%.1f%%">'
            '</span>'

            '</div>'

            '<div class="ft-meta">'
            '<b>%d days</b> '
            'to first federal obligation'
            '</div>'

            '</div>'
            % (
                e(r["name"]),
                e(r["decl"][:4]),
                _money(r["obl"]),
                gapw,
                gapw,
                floww,
                r["first"],
            )
        )

    ticks = "".join(
        (
            '<span style="left:%.1f%%">%d yr</span>'
            % (
                yy
                * 365.0
                / scale
                * 100.0,
                yy,
            )
        )
        for yy in range(
            1,
            years + 1,
        )
    )

    css = (
        "<style>"

        ".ft-list{"
        "display:grid;"
        "gap:1px;"
        "background:#e2dccb;"
        "border:1px solid #cec7b6;"
        "border-radius:8px;"
        "overflow:hidden;"
        "margin:.6rem 0 .3rem"
        "}"

        ".ft-row{"
        "background:#f6f1e7;"
        "padding:.7rem .9rem"
        "}"

        ".ft-top{"
        "display:flex;"
        "justify-content:space-between;"
        "gap:.8rem;"
        "align-items:baseline"
        "}"

        ".ft-name{"
        "font-size:.92rem;"
        "color:#17211f;"
        "font-weight:600"
        "}"

        ".ft-date{"
        "color:#6b6357;"
        "font-weight:400"
        "}"

        ".ft-val{"
        "font-family:Fraunces,Georgia,serif;"
        "font-size:1rem;"
        "color:#004c53"
        "}"

        ".ft-track{"
        "position:relative;"
        "height:11px;"
        "margin:.5rem 0 .35rem;"
        "background:#ece7d8;"
        "border:1px solid #e2dccb;"
        "border-radius:6px;"
        "overflow:hidden"
        "}"

        ".ft-gap{"
        "position:absolute;"
        "top:0;"
        "left:0;"
        "height:100%;"
        "background:#c85c2e"
        "}"

        ".ft-flow{"
        "position:absolute;"
        "top:0;"
        "height:100%;"
        "background:#004c53"
        "}"

        ".ft-meta{"
        "font-size:.72rem;"
        "color:#6b6357"
        "}"

        ".ft-meta b{"
        "color:#c85c2e"
        "}"

        ".ft-axis{"
        "position:relative;"
        "height:1.1rem;"
        "margin:.15rem .9rem 0;"
        "font-size:.66rem;"
        "color:#6b6357"
        "}"

        ".ft-axis span{"
        "position:absolute;"
        "transform:translateX(-50%)"
        "}"

        ".ft-axis span:first-child{"
        "transform:none"
        "}"

        "</style>"
    )

    return (
        '<section>'

        '<h2>'
        'Recovery funding, how fast it came'
        '</h2>'

        '<p class="pa-note">'
        'For each disaster, the wait from the declaration to the first '
        'federal obligation (amber), then the federal share obligating '
        'after that (teal), on a shared %d-year scale. '
        'Typical wait to the first obligation here: about %d days. '
        'An obligation is the federal share committed to the recipient '
        'state, not funds disbursed to the locality, which comes later '
        'and is not shown.'
        '</p>'

        '%s'

        '<div class="ft-list">'
        '%s'
        '</div>'

        '<div class="ft-axis">'
        '<span style="left:0">Declared</span>'
        '%s'
        '</div>'

        '</section>'
        % (
            years,
            med,
            css,
            "".join(bars),
            ticks,
        )
    )


def hma_html(j):
    """
    Per-jurisdiction Hazard Mitigation Assistance summary.
    """
    hma = j.get("hma") or {}

    if not hma or not (
        hma.get("fed") or 0
    ):
        return ""

    e = html.escape

    money = lambda n: "$" + format(
        int(round(n or 0)),
        ",",
    )

    total_fed = hma.get(
        "fed",
        0,
    )

    n_proj = hma.get(
        "n",
        0,
    )

    props = hma.get(
        "props",
        0,
    )

    prog = (
        hma.get(
            "prog",
            {},
        )
        or {}
    )

    rows_data = sorted(
        (
            [
                HMA_PROG_LABELS.get(
                    code,
                    code,
                ),
                code,
                vals[0],
                vals[1],
            ]
            for code, vals in prog.items()
        ),
        key=lambda x: -x[2],
    )

    body = "".join(
        (
            "<tr>"
            "<td>%s<span class='catcode'>(%s)</span></td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
        )
        % (
            e(lbl),
            e(code),
            format(
                cnt,
                ",",
            ),
            money(obl),
        )
        for lbl, code, obl, cnt in rows_data
    )

    stat = (
        '<div class="hm-stats">'

        '<div class="hm-stat">'
        '<div class="hm-n">%s</div>'
        '<div class="hm-l">'
        'federal mitigation share'
        '</div>'
        '</div>'

        '<div class="hm-stat">'
        '<div class="hm-n">%s</div>'
        '<div class="hm-l">'
        'funded project%s'
        '</div>'
        '</div>'
        % (
            money(total_fed),
            format(
                n_proj,
                ",",
            ),
            ""
            if n_proj == 1
            else "s",
        )
    )

    if props > 0:
        stat += (
            '<div class="hm-stat">'
            '<div class="hm-n">%s</div>'
            '<div class="hm-l">'
            'propert%s mitigated'
            '</div>'
            '</div>'
            % (
                format(
                    props,
                    ",",
                ),
                "y"
                if props == 1
                else "ies",
            )
        )

    stat += "</div>"

    css = (
        "<style>"

        ".hm-stats{"
        "display:flex;"
        "flex-wrap:wrap;"
        "gap:1px;"
        "background:#e2dccb;"
        "border:1px solid #cec7b6;"
        "border-radius:8px;"
        "overflow:hidden;"
        "margin:.6rem 0 .9rem"
        "}"

        ".hm-stat{"
        "background:#f6f1e7;"
        "padding:.7rem 1rem;"
        "flex:1 1 130px"
        "}"

        ".hm-n{"
        "font-family:Fraunces,Georgia,serif;"
        "font-size:1.15rem;"
        "color:#004c53;"
        "letter-spacing:-.3px"
        "}"

        ".hm-l{"
        "font-size:.72rem;"
        "color:#6b6357;"
        "margin-top:.15rem"
        "}"

        "</style>"
    )

    return (
        '<section>'

        '<h2>'
        'Hazard mitigation, what has been funded here'
        '</h2>'

        '<p class="pa-note">'
        'Federal Hazard Mitigation Assistance obligated to this jurisdiction '
        'to reduce future disaster losses, across the FEMA mitigation '
        'programs. This is the record of past mitigation investment a local '
        'hazard mitigation plan documents. Figures are federal share '
        'obligated, reported through OpenFEMA and not audited, and are '
        'separate from the Public Assistance funding above.'
        '</p>'

        '%s'
        '%s'

        '<div class="tablewrap">'

        '<table class="pa-cat">'

        '<thead>'
        '<tr>'
        '<th>Program</th>'
        '<th>Projects</th>'
        '<th>Federal share obligated</th>'
        '</tr>'
        '</thead>'

        '<tbody>%s</tbody>'

        '</table>'

        '</div>'

        '</section>'
        % (
            css,
            stat,
            body,
        )
    )


def ia_html(j):
    """
    Per-jurisdiction Individual Assistance summary.
    """
    ia = j.get("ia") or {}

    if not ia or not (
        ia.get("reg")
        or ia.get("ihp")
    ):
        return ""

    e = html.escape

    money = lambda n: "$" + format(
        int(round(n or 0)),
        ",",
    )

    reg = ia.get(
        "reg",
        0,
    )

    app = ia.get(
        "app",
        0,
    )

    ihp = ia.get(
        "ihp",
        0,
    )

    parts = [
        (
            "Repair and replacement",
            ia.get(
                "rr",
                0,
            ),
        ),
        (
            "Rental assistance",
            ia.get(
                "rent",
                0,
            ),
        ),
        (
            "Other needs",
            ia.get(
                "ona",
                0,
            ),
        ),
    ]

    body = "".join(
        "<tr><td>%s</td><td>%s</td></tr>"
        % (
            e(lbl),
            money(amt),
        )
        for lbl, amt in parts
        if amt > 0
    )

    stat = (
        '<div class="ia-stats">'

        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">'
        'valid registration%s'
        '</div>'
        '</div>'

        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">'
        'household%s approved'
        '</div>'
        '</div>'

        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">'
        'total IHP approved'
        '</div>'
        '</div>'

        '</div>'
        % (
            format(
                reg,
                ",",
            ),
            ""
            if reg == 1
            else "s",

            format(
                app,
                ",",
            ),
            ""
            if app == 1
            else "s",

            money(ihp),
        )
    )

    table = (
        '<div class="tablewrap">'
        '<table class="pa-cat">'

        '<thead>'
        '<tr>'
        '<th>Assistance type</th>'
        '<th>Approved amount</th>'
        '</tr>'
        '</thead>'

        '<tbody>%s</tbody>'

        '</table>'
        '</div>'
        % body
    ) if body else ""

    css = (
        "<style>"

        ".ia-stats{"
        "display:flex;"
        "flex-wrap:wrap;"
        "gap:1px;"
        "background:#e2dccb;"
        "border:1px solid #cec7b6;"
        "border-radius:8px;"
        "overflow:hidden;"
        "margin:.6rem 0 .9rem"
        "}"

        ".ia-stat{"
        "background:#f6f1e7;"
        "padding:.7rem 1rem;"
        "flex:1 1 130px"
        "}"

        ".ia-n{"
        "font-family:Fraunces,Georgia,serif;"
        "font-size:1.15rem;"
        "color:#004c53;"
        "letter-spacing:-.3px"
        "}"

        ".ia-l{"
        "font-size:.72rem;"
        "color:#6b6357;"
        "margin-top:.15rem"
        "}"

        "</style>"
    )

    return (
        '<section>'

        '<h2>'
        'Assistance to households (Individual Assistance)'
        '</h2>'

        '<p class="pa-note">'
        'FEMA Individual Assistance to households in this jurisdiction, '
        'combined across the Housing Assistance owner and renter programs. '
        'Valid registrations are households that applied within a designated '
        'Individual Assistance area; approved counts and dollars are the '
        'households FEMA found eligible under the Individuals and Households '
        'Program. Figures are self-reported and drawn from NEMIS through '
        'OpenFEMA, not audited, and Individual Assistance exists only for '
        'disasters where it was designated, so many jurisdictions show none.'
        '</p>'

        '%s'
        '%s'
        '%s'

        '</section>'
        % (
            css,
            stat,
            table,
        )
    )


# ---------------------------------------------------------------- state declarations
def state_decl_html(j):
    """
    Governor (state) emergency declarations with storm evidence in this
    jurisdiction, from DisasterData Plus via state-declarations.json.

    Renders nothing when this county has no resolved evidence, which is the
    normal case for the eight states whose archives are zone-only or whose
    orders are image-only PDFs. Same convention as ia_html()/hma_html():
    absent data produces no section, not an empty one.
    """
    rows = j.get("statedecl") or []

    if not rows:
        return ""

    meta = j.get("statedecl_meta") or {}

    e = html.escape

    money = lambda n: "$" + format(
        int(round(n or 0)),
        ",",
    )

    total = meta.get("total") or 0

    matched = len(rows)

    # "N of M" framing so a county's matched count is never read as the
    # state's full declaration history.
    scope = (
        "%s of the %s state declaration%s on record"
        % (
            format(matched, ","),
            format(total, ","),
            "" if total == 1 else "s",
        )
        if total
        else "%s state declaration%s"
        % (
            format(matched, ","),
            "" if matched == 1 else "s",
        )
    )

    body = []

    for d in rows[:40]:
        types = ", ".join(d.get("types") or []) or "Not categorised"

        label = d.get("eo") or d.get("id") or ""

        desc = d.get("desc") or ""

        url = d.get("url") or ""

        title = (
            '<a href="%s" rel="nofollow noopener" target="_blank">%s</a>'
            % (
                e(url),
                e(desc),
            )
            if url
            else e(desc)
        )

        dmg = d.get("dmg") or 0

        body.append(
            "<tr>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
            % (
                e(fmt_date(d.get("date") or "")),
                e(label),
                title,
                e(types),
                money(dmg) if dmg else "Not reported",
            )
        )

    more = (
        '<p class="pa-note">Showing the 40 most recent. '
        'The full record for this state is on the '
        '<a href="/plus/%s/">Plus state page</a>.</p>'
        % e(meta.get("slug") or "")
        if len(rows) > 40
        else ""
    )

    css = (
        "<style>"

        ".sd-stats{"
        "display:flex;"
        "gap:.6rem;"
        "flex-wrap:wrap;"
        "margin:.6rem 0 .9rem"
        "}"

        ".sd-stat{"
        "border:1px solid #e4dcc9;"
        "background:#f6f1e7;"
        "padding:.7rem 1rem;"
        "flex:1 1 150px"
        "}"

        ".sd-n{"
        "font-family:Fraunces,Georgia,serif;"
        "font-size:1.15rem;"
        "color:#004c53;"
        "letter-spacing:-.3px"
        "}"

        ".sd-l{"
        "font-size:.72rem;"
        "color:#6b6357;"
        "margin-top:.15rem"
        "}"

        ".sd-wrap{"
        "overflow-x:auto;"
        "-webkit-overflow-scrolling:touch"
        "}"

        "table.sd-tbl td:last-child,"
        "table.sd-tbl th:last-child{"
        "text-align:right;"
        "font-variant-numeric:tabular-nums;"
        "white-space:nowrap"
        "}"

        "table.sd-tbl td:first-child,"
        "table.sd-tbl th:first-child{"
        "white-space:nowrap"
        "}"

        "</style>"
    )

    stat = (
        '<div class="sd-stats">'

        '<div class="sd-stat">'
        '<div class="sd-n">%s</div>'
        '<div class="sd-l">state declarations with local storm evidence</div>'
        '</div>'

        '<div class="sd-stat">'
        '<div class="sd-n">%s</div>'
        '<div class="sd-l">statewide on record</div>'
        '</div>'

        '</div>'
        % (
            format(matched, ","),
            format(total, ",") if total else "Not counted",
        )
    )

    coverage = (
        '<p class="pa-note">Archive coverage for %s: %s</p>'
        % (
            e(meta.get("name") or ""),
            e(meta.get("coverage") or "not stated"),
        )
        if meta.get("coverage")
        else ""
    )

    return (
        '<section>'

        '<h2>'
        'State declarations (governor)'
        '</h2>'

        '<p class="pa-note">'
        'Emergency declarations issued by the governor of this state, which '
        'are separate from and usually precede a federal declaration. A '
        'declaration is listed here when NOAA Storm Events recorded reports '
        'of the matched hazard in this jurisdiction while the order was in '
        'effect. That is evidence of local impact during a declared state '
        'emergency. It is not a statement that the governor named this '
        'jurisdiction in the order, since most state declarations apply '
        'statewide and name no localities at all. Hazard categories come '
        'from the order text. Damage figures are NOAA storm report estimates '
        'for this jurisdiction only, not the cost of the declaration.'
        '</p>'

        '%s'
        '%s'
        '%s'

        '<div class="sd-wrap">'
        '<table class="sd-tbl">'
        '<thead><tr>'
        '<th>Signed</th>'
        '<th>Order</th>'
        '<th>Declaration</th>'
        '<th>Hazards reported here</th>'
        '<th>Reported damage</th>'
        '</tr></thead>'
        '<tbody>%s</tbody>'
        '</table>'
        '</div>'

        '%s'

        '<p class="pa-note">'
        'Source: state executive order archives collected by DisasterData '
        'Plus, joined to NOAA Storm Events. See the '
        '<a href="/plus/">Plus overview</a> for per-state coverage and method.'
        '</p>'

        '</section>'
        % (
            css,
            stat,
            coverage,
            "".join(body),
            more,
        )
    )


# ---------------------------------------------------------------- SVI / NRI risk context
def _finite_number(value):
    """Return a finite float, or None for blank, sentinel, or invalid data."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number != number or number in (float("inf"), float("-inf")):
        return None

    return number


def _short_money(value):
    """Format a numeric dollar value compactly without turning missing into $0."""
    number = _finite_number(value)

    if number is None:
        return "N/A"

    if abs(number) >= 1e9:
        return "$%.1fB" % (number / 1e9)

    if abs(number) >= 1e6:
        return "$%.1fM" % (number / 1e6)

    if abs(number) >= 1e3:
        return "$%.0fK" % (number / 1e3)

    return "$%s" % format(int(round(number)), ",")


def _svi_percent(value):
    """Return a CDC SVI percentile on a 0-100 scale, or None if invalid."""
    number = _finite_number(value)

    if number is None or number < 0 or number > 1:
        return None

    return number * 100.0


def _first_value(record, *keys):
    """Return the first populated field, supporting older NRI field aliases."""
    for key in keys:
        value = record.get(key)

        if value is not None and str(value).strip() != "":
            return value

    return None


def _score_text(value):
    number = _finite_number(value)
    return "%.1f" % number if number is not None else "N/A"


def risk_context_html(j):
    """
    Render static county-level CDC SVI and FEMA NRI context.

    The two social-vulnerability measures remain explicitly separate because
    they use different methods and should not be interpreted as one score.
    """
    svi = j.get("svi") or {}
    nri = j.get("nri") or {}

    if not svi and not nri:
        return ""

    e = html.escape
    cards = []

    if svi:
        overall = _svi_percent(svi.get("overall"))

        if overall is None:
            overall_html = (
                '<div class="risk-score na">N/A</div>'
                '<div class="risk-score-label">overall percentile</div>'
            )
            interpretation = ""

        else:
            overall_html = (
                '<div class="risk-score">%.1f</div>'
                '<div class="risk-score-label">overall percentile nationally</div>'
                % overall
            )
            interpretation = (
                '<p class="risk-interpret">Approximately %.1f%% of U.S. '
                'counties have an equal or lower overall SVI ranking.</p>'
                % overall
            )

        themes = [
            ("Socioeconomic status", svi.get("socioeconomic")),
            ("Household characteristics", svi.get("household")),
            ("Racial and ethnic minority status", svi.get("minority")),
            (
                "Housing type and transportation",
                svi.get("housingTransportation"),
            ),
        ]

        theme_rows = []

        for theme_label, value in themes:
            percentile = _svi_percent(value)

            if percentile is None:
                continue

            theme_rows.append(
                '<div class="theme-row">'
                '<div class="theme-head"><span>%s</span><b>%.1f</b></div>'
                '<div class="theme-track"><span style="width:%.1f%%"></span></div>'
                '</div>'
                % (
                    e(theme_label),
                    percentile,
                    max(0, min(100, percentile)),
                )
            )

        cards.append(
            '<article class="risk-card">'
            '<div class="risk-kicker">CDC / ATSDR</div>'
            '<h3>Social Vulnerability Index</h3>'
            '<div class="risk-version">2022 county-level SVI</div>'
            '%s%s'
            '<div class="theme-list">%s</div>'
            '<p class="risk-source">Higher percentiles indicate greater '
            'relative social vulnerability within the CDC SVI framework. '
            '<a href="https://www.atsdr.cdc.gov/place-health/php/svi/'
            'svi-data-documentation-download.html">CDC SVI documentation</a>'
            '</p>'
            '</article>'
            % (
                overall_html,
                interpretation,
                "".join(theme_rows),
            )
        )

    if nri:
        risk_score = _score_text(nri.get("riskScore"))
        risk_rating = str(nri.get("riskRating") or "Not rated")
        version = str(nri.get("version") or "December 2025 county dataset")

        eal_value = _short_money(nri.get("ealValue"))
        eal_rating = str(nri.get("ealRating") or "Not rated")

        sovi_score = _score_text(
            _first_value(nri, "soviScore", "socialVulnerabilityScore")
        )
        sovi_rating = str(
            _first_value(nri, "soviRating", "socialVulnerabilityRating")
            or "Not rated"
        )

        resilience_score = _score_text(
            _first_value(nri, "reslScore", "resilienceScore")
        )
        resilience_rating = str(
            _first_value(nri, "reslRating", "resilienceRating")
            or "Not rated"
        )

        cards.append(
            '<article class="risk-card">'
            '<div class="risk-kicker">FEMA</div>'
            '<h3>National Risk Index</h3>'
            '<div class="risk-version">%s</div>'
            '<div class="nri-lead">'
            '<div><div class="risk-score">%s</div>'
            '<div class="risk-score-label">overall risk score</div></div>'
            '<span class="risk-rating">%s</span>'
            '</div>'
            '<div class="risk-mini-grid">'
            '<div class="risk-mini"><span>Expected annual loss</span>'
            '<b>%s</b><small>%s</small></div>'
            '<div class="risk-mini"><span>NRI social vulnerability</span>'
            '<b>%s</b><small>%s</small></div>'
            '<div class="risk-mini"><span>Community resilience</span>'
            '<b>%s</b><small>%s</small></div>'
            '</div>'
            '<p class="risk-source">The NRI combines expected annual loss, '
            'social vulnerability, and community resilience to describe '
            'relative natural-hazard risk. '
            '<a href="https://hazards.fema.gov/nri/">FEMA NRI documentation</a>'
            '</p>'
            '</article>'
            % (
                e(version),
                e(risk_score),
                e(risk_rating),
                e(eal_value),
                e(eal_rating),
                e(sovi_score),
                e(sovi_rating),
                e(resilience_score),
                e(resilience_rating),
            )
        )

    fips = (
        svi.get("fips")
        or nri.get("fips")
        or j.get("risk_fips")
        or ""
    )

    fips_note = (
        '<span class="risk-fips">County FIPS %s</span>' % e(str(fips))
        if fips
        else ""
    )

    return (
        '<section class="risk-section">'
        '<div class="section-heading-row">'
        '<div><h2>Risk and vulnerability context</h2>'
        '<p class="section-deck">Historical declarations show what has '
        'happened here. These national datasets add context about underlying '
        'natural-hazard risk and community vulnerability.</p></div>%s'
        '</div>'
        '<div class="risk-grid">%s</div>'
        '<div class="risk-caution"><b>About these measures:</b> CDC Social '
        'Vulnerability Index and FEMA National Risk Index Social Vulnerability '
        'are separate measures built with different methods. They are shown '
        'side by side for context and should not be interpreted as equivalent '
        'scores.</div>'
        '</section>'
        % (fips_note, "".join(cards))
    )


# ---------------------------------------------------------------- jurisdiction page
def render_page(j, others, lcfy):
    e = html.escape

    canonical = (
        "%s/states/%s/%s.html"
        % (
            SITE,
            STATE_SLUG,
            j["slug"],
        )
    )

    label = j["label"]

    robots = (
        '<meta name="robots" content="noindex,follow">'
        if j.get("thin")
        else ""
    )

    desc = (
        "%s, %s has had %d federal major disaster declarations since FY2000, "
        "plus %d emergency declarations and %d fire management declarations, "
        "%d in all. Full FEMA declaration history in a sortable table ready "
        "to copy into a hazard mitigation plan, with CDC SVI and FEMA NRI "
        "context where available."
        % (
            j["name"],
            STATE_NAME,
            j["dr"],
            j["em"],
            j["fm"],
            j["decl"],
        )
    )

    ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "%s, %s FEMA disaster declarations"
        % (
            j["name"],
            STATE_NAME,
        ),
        "description": desc,
        "url": canonical,
        "isAccessibleForFree": True,
        "creator": {
            "@type": "Organization",
            "name": "Disaster Data",
            "url": SITE,
        },
        "spatialCoverage": {
            "@type": "Place",
            "name": "%s, %s"
            % (
                j["name"],
                STATE_NAME,
            ),
        },
        "temporalCoverage": "2000/%d" % lcfy,
        "isBasedOn":
            "https://www.fema.gov/about/openfema",
        "keywords": [
            j["name"],
            STATE_NAME,
            "FEMA",
            "disaster declarations",
            "hazard mitigation plan",
            "previous occurrences",
            "CDC Social Vulnerability Index",
            "FEMA National Risk Index",
        ],
    }

    cards = [
        (
            "%d" % j["dr"],
            "Major disasters",
        ),
        (
            "%d" % j["em"],
            "Emergency declarations",
        ),
        (
            "%d" % j["fm"],
            "Fire management grants",
        ),
        (
            "%d" % j["decl"],
            "All declarations on record",
        ),
    ]

    if j["latest"]:
        try:
            mr = datetime.datetime.strptime(
                j["latest"],
                "%Y-%m-%d",
            ).strftime(
                "%b&nbsp;%Y"
            )
        except Exception:
            mr = j["latest"]

        cards.append(
            (
                mr,
                "Most recent",
            )
        )

    if j.get("pa_obl") and j["pa_obl"] > 0:
        obl = j["pa_obl"]

        if obl >= 1e9:
            pa_fmt = "$%.1fB" % (
                obl / 1e9
            )

        elif obl >= 1e6:
            pa_fmt = "$%.1fM" % (
                obl / 1e6
            )

        elif obl >= 1e3:
            pa_fmt = "$%.0fK" % (
                obl / 1e3
            )

        else:
            pa_fmt = "$%d" % obl

        pa_label = (
            "Federal PA obligated"
        )

        if j.get(
            "pa_top_cat"
        ):
            pa_label += (
                " (top: %s)"
                % j[
                    "pa_top_cat"
                ].lower()
            )

        cards.append(
            (
                pa_fmt,
                pa_label,
            )
        )

    stats = "".join(
        (
            '<div class="stat">'
            '<div class="n">%s</div>'
            '<div class="l">%s</div>'
            '</div>'
            % c
        )
        for c in cards
    )

    # embedded state map
    st_fips = STATE_FIPS.get(
        STATE_AB,
        "",
    )

    if (
        j["kind"] in (
            "county",
            "city",
        )
        and st_fips
    ):
        map_html = (
            '<div id="locmap" '
            'data-fips="%s" '
            'data-name="%s" '
            'data-st="%s" '
            'data-kind="%s">'
            '</div>'

            '<p class="locmap-cap">'
            'Highlighted: '
            '<b>%s, %s</b>'
            '</p>'
        ) % (
            st_fips,
            html.escape(
                j["name"].replace(
                    " (city)",
                    "",
                ),
                quote=True,
            ),
            STATE_AB,
            j["kind"],
            html.escape(
                j["name"],
                quote=True,
            ),
            STATE_AB,
        )

    else:
        map_html = ""

    haz = "".join(
        '<li>%s <b>%d</b></li>'
        % (
            e(h),
            n,
        )
        for h, n in j[
            "hazards"
        ][:8]
    ) or (
        "<li>"
        "None recorded"
        "</li>"
    )

    # Every declaration, newest first, including the in-progress fiscal year.
    # Those rows carry a fiscal-year tag (FY2026, say) and are not in the totals above.
    rows = "".join(
        (
            '<tr data-t="%s">'

            '<td data-s="%s">%s</td>'

            '<td data-s="%s">%s</td>'

            "<td>"
            "<span class='tag' title='%s'>%s</span>"
            "</td>"

            "<td>%s</td>"
            "<td>%s</td>"

            "</tr>"
        )
        % (
            e(
                r.get(
                    "declarationType",
                    "",
                )
            ),
            e(
                r.get(
                    "declarationDate",
                    "",
                )[:10]
            ),
            fmt_date(
                r.get(
                    "declarationDate",
                    "",
                )
            ),
            decl_num(
                r.get(
                    "femaDeclarationString",
                    "",
                )
            ),
            e(
                r.get(
                    "femaDeclarationString",
                    "",
                )
            ),
            TYPE_LONG.get(
                r.get(
                    "declarationType",
                    "",
                ),
                "",
            ),
            e(
                r.get(
                    "declarationType",
                    "",
                )
            ),
            e(
                r.get(
                    "incidentType",
                    "",
                )
            ),
            e(
                pretty_title(
                    r.get(
                        "declarationTitle",
                        "",
                    )
                )
            ),
        )
        for r in j["hmp"]
    )

    wrap_cls = (
        "tablewrap scroll"
        if len(
            j["hmp"]
        ) > 12
        else "tablewrap"
    )

    # Rows for the Copy table button: the table as shown, default order, with the
    # display date. Tab-separated on the clipboard, so it pastes straight into a
    # hazard mitigation plan's previous-occurrences section. This button used to
    # sit on a second, near-identical table above this one.
    copy_rows = [["Date", "Declaration", "Type", "Hazard", "Title"]] + [
        [
            fmt_date(r.get("declarationDate", "")),
            r.get("femaDeclarationString", ""),
            r.get("declarationType", ""),
            r.get("incidentType", ""),
            pretty_title(r.get("declarationTitle", "")),
        ]
        for r in j["hmp"]
    ]

    history = (
        '<div id="declbox">'

        + decl_kinds_html()

        # Chips and the "Showing" line count the rows actually in the table
        # (in-progress year included), so a filter click always shows exactly
        # the number on its chip. The stat cards above keep complete years.
        + type_chips(
            j["list_n"],
            j["list_dr"],
            j["list_em"],
            j["list_fm"],
        )

        + open_fy_note_html(
            j["open_n"],
            j["open_fys"],
        )

        + (
            '<p class="decl-count" aria-live="polite">'
            'Showing %d declarations'
            '</p>'
            % j["list_n"]
        )

        + '<div class="'
        + wrap_cls
        + '">'

        '<table>'

        '<thead>'
        '<tr>'

        '<th class="sortable" data-k="date">'
        'Date'
        '</th>'

        '<th class="sortable" data-k="num">'
        'Number'
        '</th>'

        '<th class="sortable" data-k="text">'
        'Type'
        '</th>'

        '<th class="sortable" data-k="text">'
        'Hazard'
        '</th>'

        '<th class="sortable" data-k="text">'
        'Title'
        '</th>'

        '</tr>'
        '</thead>'

        '<tbody>'
        + rows
        + '</tbody>'

        '</table>'

        '</div>'

        '<div class="export-bar" '
        'style="display:flex;flex-wrap:wrap;gap:.6rem;margin:.8rem 0 0">'

        '<button class="copybtn" type="button" data-hmp="'
        + e(json.dumps(copy_rows))
        + '">'
        'Copy table'
        '</button>'

        '<button class="copybtn csvbtn" type="button">'
        'Download CSV'
        '</button>'

        '</div>'

        '</div>'
        + FILTER_JS
    )

    # The fiscal year comes from lcfy, not a literal, so the lede rolls forward
    # with the totals on Oct 1 instead of claiming "through FY2025" forever.
    lede = (
        "%s recorded <b>%d</b> federal major disaster declarations since "
        "FY2000 (through FY%d), the federal government's fullest response "
        "to an event. Alongside those sit %d emergency declarations and "
        "%d fire management declarations, %d in all.%s"
        % (
            e(
                j["name"]
            ),
            j["dr"],
            lcfy,
            j["em"],
            j["fm"],
            j["decl"],
            (
                " Its most common hazard is %s."
                % e(
                    j["hazards"][0][0].lower()
                )
            )
            if j["hazards"]
            else "",
        )
    )

    if (
        j.get("spans")
        and len(
            j["spans"]
        ) > 1
    ):
        lede += (
            " This record covers the nation across %s."
            % e(
                _oxford(
                    j["spans"]
                )
            )
        )

    grid = "".join(
        (
            '<a href="%s.html">%s</a>'
            % (
                o["slug"],
                e(
                    o["name"]
                ),
            )
        )
        for o in others
        if o["slug"] != j["slug"]
    )

    csv_rows = [
        [
            "Date",
            "Declaration",
            "Type",
            "Hazard",
            "Title",
        ]
    ] + [
        [
            r.get(
                "declarationDate",
                "",
            )[:10],
            r.get(
                "femaDeclarationString",
                "",
            ),
            r.get(
                "declarationType",
                "",
            ),
            r.get(
                "incidentType",
                "",
            ),
            pretty_title(
                r.get(
                    "declarationTitle",
                    "",
                )
            ),
        ]
        for r in j["hmp"]
    ]

    csv_json = json.dumps(
        csv_rows
    )

    # ------------------------------------------------------------ copy/download/citation JS
    copyjs = (
        "<script>"

        "document.addEventListener('click',function(ev){"

        "var b=ev.target.closest('.copybtn');"
        "if(!b)return;"

        # Copy HMP table
        "if(b.getAttribute('data-hmp')){"

        "var rows=JSON.parse(b.getAttribute('data-hmp'));"

        "var t=rows.map(function(r){"
        "return r.join('\\t');"
        "}).join('\\n');"

        "function done(){"
        "var p=b.textContent;"
        "b.textContent='Copied';"
        "setTimeout(function(){"
        "b.textContent=p;"
        "},1500);"
        "}"

        "if(navigator.clipboard&&navigator.clipboard.writeText){"
        "navigator.clipboard.writeText(t).then("
        "done,"
        "function(){window.prompt('Copy:',t);}"
        ");"
        "}else{"
        "window.prompt('Copy:',t);"
        "}"

        "return;"
        "}"

        # Download CSV
        "if(b.classList.contains('csvbtn')){"

        "var d=%s;"

        "var csv=d.map(function(r){"
        "return r.map(function(c){"
        "return '\\\"'+String(c).replace(/\\\"/g,'\\\"\\\"')+'\\\"';"
        "}).join(',');"
        "}).join('\\n');"

        "var blob=new Blob([csv],{type:'text/csv'});"

        "var a=document.createElement('a');"

        "a.href=URL.createObjectURL(blob);"

        "a.download='%s-declarations.csv';"

        "a.click();"

        "URL.revokeObjectURL(a.href);"

        "return;"
        "}"

        # Copy currently selected citation
        "if(b.classList.contains('citecopy')){"

        "var out=document.getElementById('citationText');"

        "var cite=out?out.textContent:'';"

        "function cd(){"
        "var p=b.textContent;"
        "b.textContent='Copied';"
        "setTimeout(function(){"
        "b.textContent=p;"
        "},1500);"
        "}"

        "if(navigator.clipboard&&navigator.clipboard.writeText){"

        "navigator.clipboard.writeText(cite).then("
        "cd,"
        "function(){window.prompt('Citation:',cite);}"
        ");"

        "}else{"

        "window.prompt('Citation:',cite);"

        "}"

        "return;"
        "}"

        "});"

        # Citation format switching
        "(function(){"

        "var box=document.querySelector('.citation'),"
        "out=document.getElementById('citationText');"

        "if(!box||!out)return;"

        "var title=box.getAttribute('data-cite-title')||'',"
        "url=box.getAttribute('data-cite-url')||'',"
        "key=box.getAttribute('data-cite-key')||"
        "'disasterdata_profile';"

        "function pad(n){"
        "return String(n).padStart(2,'0');"
        "}"

        "function dates(){"

        "var d=new Date();"

        "return{"
        "iso:"
        "d.getFullYear()+'-'+"
        "pad(d.getMonth()+1)+'-'+"
        "pad(d.getDate()),"

        "long:d.toLocaleDateString("
        "'en-US',"
        "{"
        "year:'numeric',"
        "month:'long',"
        "day:'numeric'"
        "}"
        ")"
        "};"

        "}"

        "function text(fmt){"

        "var d=dates();"

        # Chicago
        "if(fmt==='chicago')"
        "return "
        "'Disaster Data. \"'+title+'\" "
        "DisasterData.IO. Accessed '+"
        "d.long+'. '+url+'.';"

        # Plain text
        "if(fmt==='plain')"
        "return "
        "'Disaster Data. '+title+'. "
        "DisasterData.IO. Derived from FEMA OpenFEMA. "
        "Accessed '+d.long+'. '+url;"

        # BibTeX
        "if(fmt==='bibtex')"
        "return "
        "'@misc{'+key+',\\n"
        "  author = {{Disaster Data}},\\n"
        "  title = {'+title+'},\\n"
        "  howpublished = {DisasterData.IO},\\n"
        "  url = {'+url+'},\\n"
        "  urldate = {'+d.iso+'},\\n"
        "  note = {Derived from FEMA OpenFEMA}\\n"
        "}';"

        # APA default
        "return "
        "'Disaster Data. (n.d.). '+title+'. "
        "Retrieved '+d.long+', from '+url;"

        "}"

        "function render(fmt){"

        "out.textContent=text(fmt);"

        "var bs=box.querySelectorAll('.citefmt');"

        "for(var i=0;i<bs.length;i++){"

        "bs[i].setAttribute("
        "'aria-pressed',"
        "bs[i].getAttribute('data-fmt')===fmt?"
        "'true':'false'"
        ");"

        "}"

        "}"

        "box.addEventListener('click',function(ev){"

        "var c=ev.target.closest('.citefmt');"

        "if(c){"
        "render(c.getAttribute('data-fmt'));"
        "}"

        "});"

        "render('apa');"

        "})();"

        "</script>"
        % (
            csv_json,
            j["slug"],
        )
    )

    # ------------------------------------------------------------ map scripts
    if map_html:
        mapjs = (
            '<script '
            'src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js">'
            '</script>'

            '<script '
            'src="https://unpkg.com/topojson-client@3">'
            '</script>'

            '<script src="../../county-names.js"></script>'

            '<script src="../../locality-index.js"></script>'

            '<script>'

            '(function(){'

            'var el=document.getElementById("locmap");'
            'if(!el)return;'

            'var sf=el.dataset.fips,'
            'sa=el.dataset.st,'
            'knd=(el.dataset.kind||"");'

            'var SX=['
            '"county",'
            '"parish",'
            '"borough",'
            '"census area",'
            '"municipio",'
            '"municipality",'
            '"city and borough",'
            '"island",'
            '"district"'
            '];'

            'function norm(s){'
            'return String(s||"")'
            '.replace(/\\s*\\([^)]*\\)/g,"")'
            '.trim()'
            '.toLowerCase();'
            '}'

            'function base(v){'

            'var s=norm(String(v).split(",")[0]);'

            'for(var i=0;i<SX.length;i++){'

            'if(s.endsWith(" "+SX[i])){'

            's=s.slice('
            '0,'
            '-(SX[i].length+1)'
            ').trim();'

            'break;'

            '}'

            '}'

            'return s;'

            '}'

            'var cnBase=base(el.dataset.name);'

            'function go(){'

            'if(!window.COUNTY_NAMES||!window.LOCALITY_INDEX){'
            'setTimeout(go,100);'
            'return;'
            '}'

            'var ul={};'

            'window.LOCALITY_INDEX.forEach(function(r){'

            'if(r[1]!==sa)return;'

            'var full=r[0]'
            '.replace(/ \\(city\\)$/i,"")'
            '.toLowerCase();'

            'ul[base(r[0])]=r[3];'
            'ul[full]=r[3];'

            '});'

            'fetch('
            '"https://unpkg.com/us-atlas@3/counties-10m.json"'
            ')'

            '.then(function(r){'
            'return r.json();'
            '})'

            '.then(function(topo){'

            'var fc={'
            'type:"FeatureCollection",'
            'features:topojson.feature('
            'topo,'
            'topo.objects.counties'
            ').features.filter(function(f){'
            'return String(f.id)'
            '.padStart(5,"0")'
            '.slice(0,2)===sf;'
            '})'
            '};'

            'var matches=fc.features.filter(function(f){'
            'return base('
            'window.COUNTY_NAMES['
            'String(f.id).padStart(5,"0")'
            ']||""'
            ')===cnBase;'
            '});'

            'var collide=matches.length>1;'

            'function isTarget(f){'

            'var fp=String(f.id).padStart(5,"0");'

            'if(base(window.COUNTY_NAMES[fp]||"")!==cnBase)'
            'return false;'

            'if(collide){'

            'var city=(+fp.slice(2))>=500;'

            'return (knd==="city")===city;'

            '}'

            'return true;'

            '}'

            'var map=L.map('
            '"locmap",'
            '{'
            'scrollWheelZoom:false,'
            'zoomControl:true,'
            'attributionControl:true'
            '}'
            ');'

            'L.tileLayer('
            '"https://{s}.basemaps.cartocdn.com/'
            f'light_nolabels/{{z}}/{{x}}/{{y}}{{r}}.png?key={CARTO_BASEMAP_KEY}",'
            '{'
            'maxZoom:13,'
            "attribution:'"
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            'OpenStreetMap</a> contributors &copy; '
            '<a href="https://carto.com/attributions">CARTO</a>'
            "'"
            '}'
            ').addTo(map);'

            'var targetLayer=null;'

            'var ly=L.geoJson(fc,{'

            'style:function(f){'

            'if(isTarget(f))'
            'return{'
            'fillColor:"#004c53",'
            'fillOpacity:.55,'
            'color:"#004c53",'
            'weight:2'
            '};'

            'return{'
            'fillColor:"#d7e9ea",'
            'fillOpacity:.35,'
            'color:"#938a78",'
            'weight:1'
            '};'

            '},'

            'onEachFeature:function(f,layer){'

            'var fp=String(f.id).padStart(5,"0"),'
            'lb=window.COUNTY_NAMES[fp]||"",'
            'nm=lb.split(",")[0].trim();'

            'var u='
            'ul[base(nm)]||'
            'ul[nm.toLowerCase()];'

            'if(isTarget(f)){'

            'targetLayer=layer;'

            'layer.bindTooltip('
            'nm,'
            '{'
            'permanent:true,'
            'direction:"center",'
            'className:"loc-lbl",'
            'offset:[0,0]'
            '}'
            ');'

            '}else{'

            'layer.bindTooltip('
            'nm,'
            '{sticky:true}'
            ');'

            '}'

            'if(u){'

            'layer.on("click",function(){'
            'window.location.href="../../"+u;'
            '});'

            'layer.on("mouseover",function(){'
            'this._path.style.cursor="pointer";'
            'this.setStyle({fillOpacity:.6});'
            '});'

            'layer.on("mouseout",function(){'
            'this.setStyle({'
            'fillOpacity:(this===targetLayer)?.55:.35'
            '});'
            '});'

            '}'

            '}'

            '}).addTo(map);'

            'map.fitBounds('
            'ly.getBounds(),'
            '{padding:[15,15]}'
            ');'

            '});'

            '}'

            'go();'

            '})();'

            '</script>'
        )

    else:
        mapjs = ""

    return (
        '<!doctype html>'
        '<html lang="en">'

        '<head>'

        '<meta charset="utf-8">'

        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1">'

        '%s'

        '<title>'
        'Disaster Data | %s, %s FEMA Disaster Declarations '
        'and Mitigation History'
        '</title>'

        '<meta name="description" content="%s">'

        '<link rel="canonical" href="%s">'

        '<meta property="og:title" '
        'content="%s, %s: Federal Disaster Declarations">'

        '<meta property="og:description" content="%s">'

        '<meta property="og:type" content="website">'

        '<meta property="og:url" content="%s">'

        '<meta name="twitter:card" content="summary">'

        '%s'

        '<script type="application/ld+json">'
        '%s'
        '</script>'

        '</head>'

        '<body>'

        '%s'

        '<main>'

        '<div class="wrap">'

        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / '
        '%s'
        '</p>'

        '<span class="badge %s">%s</span>'

        '<h1>%s, %s</h1>'

        '<p class="lede">%s</p>'

        '%s'

        '%s'

        '<div class="stats">%s</div>'

        '%s'

        '%s'

        '%s'

        '<h2>Most common hazards</h2>'

        '<ul class="haz">%s</ul>'

        '<h2>Every declaration on record</h2>'

        '%s'

        '<div style="margin:2rem 0">'

        '<a href="../%s.html">'
        '&larr; %s statewide overview'
        '</a> '

        '&middot; '

        '<a href="index.html">'
        'All %s jurisdictions'
        '</a>'

        '</div>'

        '%s'

        '<h2>Other %s jurisdictions</h2>'

        '<nav class="jgrid">'
        '%s'
        '</nav>'

        '</div>'

        '</main>'

        '%s'

        '%s'

        '%s'

        '</body>'

        '</html>'
        % (
            robots,

            e(j["name"]),
            STATE_NAME,

            e(desc),

            canonical,

            e(j["name"]),
            STATE_NAME,

            e(desc),

            canonical,

            HEAD,

            json.dumps(ld),

            header_html(),

            STATE_SLUG,
            STATE_NAME,
            e(j["name"]),

            j["kind"],
            label,

            e(j["name"]),
            STATE_NAME,

            lede,

            map_html,

            provenance_stamp_html(lcfy),

            stats,

            summary_html(j) + recent_aid_html(j),

            risk_context_html(j),

            (
                pa_split_html(j)
                + pa_breakdown_html(j)
                + pa_timing_html(j)
                + ia_html(j)
                + hma_html(j)
                + state_decl_html(j)
            ),

            haz,

            history,

            STATE_SLUG,
            STATE_NAME,
            STATE_NAME,

            (
                method_html(
                    j["kind"],
                    bool(
                        j.get("spans")
                    ),
                )
                + citation_html(
                    j,
                    canonical,
                )
            ),

            STATE_NAME,

            grid,

            footer_html(),

            copyjs,

            mapjs,
        )
    )


# ---------------------------------------------------------------- hub
def render_hub(js, stubs=(), lcfy=None):
    e = html.escape

    items = [
        (
            j["decl"],
            j["name"],
            j["label"],
            j["slug"] + ".html",
            "",
        )
        for j in js
    ]

    for s in stubs:
        rel = s[
            "canonical_url"
        ].replace(
            "states/",
            "../",
            1,
        )

        items.append(
            (
                s["decl"],
                s["name"],
                s["label"],
                rel,
                (
                    " &middot; full record on the %s page"
                    % e(
                        s[
                            "primary_name"
                        ]
                    )
                ),
            )
        )

    items.sort(
        key=lambda it: (
            -it[0],
            it[1],
        )
    )

    rows = "".join(
        (
            '<li>'
            '<a href="%s">%s</a> '
            '<span class="k">%s</span>'
            '<span class="c">'
            '%d declarations%s'
            '</span>'
            '</li>'
        )
        % (
            href,
            e(name),
            label,
            decl,
            note,
        )
        for (
            decl,
            name,
            label,
            href,
            note,
        ) in items
    )

    phrase = kind_phrase(
        js
    )

    desc = (
        "Federal disaster and emergency declaration history for every "
        "%s %s since FY2000, each in a sortable table ready to copy into a "
        "hazard mitigation plan."
        % (
            STATE_NAME,
            phrase,
        )
    )

    return (
        '<!doctype html>'
        '<html lang="en">'

        '<head>'

        '<meta charset="utf-8">'

        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1">'

        '<title>'
        'Disaster Data | %s Disaster Declarations by Jurisdiction'
        '</title>'

        '<meta name="description" content="%s">'

        '<link rel="canonical" href="%s/states/%s/">'

        '<meta property="og:title" '
        'content="%s Disaster Declarations by Jurisdiction">'

        '<meta property="og:description" content="%s">'

        '<meta property="og:type" content="website">'

        '<meta name="twitter:card" content="summary">'

        '%s'

        '</head>'

        '<body>'

        '%s'

        '<main>'

        '<div class="wrap">'

        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / '
        'Jurisdictions'
        '</p>'

        '<h1>%s, by jurisdiction</h1>'

        '<p class="lede">'
        'Every %s %s, ranked by federal disaster and emergency '
        'declarations since FY2000. Each page carries the full declaration '
        'history in a sortable table ready to copy into a local '
        'mitigation plan.'
        '</p>'

        '%s'

        '<ol class="rank">'
        '%s'
        '</ol>'

        '<div style="margin:2rem 0">'
        '<a href="../%s.html">'
        '&larr; Back to %s statewide overview'
        '</a>'
        '</div>'

        '</div>'

        '</main>'

        '%s'

        '</body>'

        '</html>'
        % (
            STATE_NAME,

            e(desc),

            SITE,
            STATE_SLUG,

            STATE_NAME,

            e(desc),

            HEAD,

            header_html(),

            STATE_SLUG,
            STATE_NAME,

            STATE_NAME,

            STATE_NAME,
            phrase,

            provenance_stamp_html(lcfy) if lcfy is not None else '',

            rows,

            STATE_SLUG,
            STATE_NAME,

            footer_html(),
        )
    )


# ---------------------------------------------------------------- tribal merge
def build_tribal_plan(LOCALITY, NAMES):
    """
    Aggregate every tribal jurisdiction across the states it appears in.

    Each tribe gets one canonical page on its primary state.
    """
    agg = {}

    for st, entries in LOCALITY.items():
        for en in entries:
            c = classify(
                st,
                en["n"],
            )

            if not (
                c["kind"] == "tribal"
                and c["keep"]
            ):
                continue

            d = (
                agg
                .setdefault(
                    c["display"],
                    {},
                )
                .setdefault(
                    st,
                    {
                        "c": 0,
                        "ids": set(),
                        "cls": c,
                    },
                )
            )

            d["c"] += en.get(
                "c",
                0,
            )

            d["ids"].update(
                en.get(
                    "ids",
                    [],
                )
            )

    plan = {}

    for disp, smap in agg.items():
        primary = sorted(
            smap.items(),
            key=lambda kv: (
                -kv[1]["c"],
                kv[0],
            ),
        )[0][0]

        pc = smap[
            primary
        ]["cls"]

        pname = NAMES.get(
            primary,
            primary,
        )

        purl = (
            "states/%s/%s.html"
            % (
                slugify(
                    pname
                ),
                make_slug(
                    pc,
                    primary,
                ),
            )
        )

        all_ids = sorted(
            set().union(
                *(
                    v["ids"]
                    for v in smap.values()
                )
            )
        )

        states = sorted(
            smap.keys(),
            key=lambda s: NAMES.get(
                s,
                s,
            ),
        )

        for st in smap:
            plan[
                (
                    st,
                    disp,
                )
            ] = {
                "role":
                    "primary"
                    if st == primary
                    else "secondary",

                "primary_name":
                    pname,

                "primary_url":
                    purl,

                "all_ids":
                    all_ids,

                "states":
                    states,
            }

    return plan


def render_stub(
    name,
    canonical_url,
    primary_name,
    spans,
):
    """
    Thin canonical-pointer page for cross-state tribal jurisdictions.
    """
    e = html.escape

    canonical = "%s/%s" % (
        SITE,
        canonical_url,
    )

    rel = canonical_url.replace(
        "states/",
        "../",
        1,
    )

    span_txt = _oxford(
        spans
    )

    desc = (
        "%s spans %s. Its full federal disaster and emergency declaration "
        "history and mitigation table are maintained on the %s page."
        % (
            name,
            span_txt,
            primary_name,
        )
    )

    return (
        '<!doctype html>'
        '<html lang="en">'

        '<head>'

        '<meta charset="utf-8">'

        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1">'

        '<title>'
        'Disaster Data | %s'
        '</title>'

        '<meta name="description" content="%s">'

        '<link rel="canonical" href="%s">'

        '<meta property="og:title" content="%s">'

        '<meta property="og:type" content="website">'

        '%s'

        '</head>'

        '<body>'

        '%s'

        '<main>'

        '<div class="wrap">'

        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / '
        '%s'
        '</p>'

        '<span class="badge tribal">'
        'Tribal nation'
        '</span>'

        '<h1>%s</h1>'

        '<p class="lede">'
        '%s spans %s. To keep its record whole rather than split across '
        'state lines, its full declaration history lives on one page.'
        '</p>'

        '<p style="margin:1.5rem 0">'

        '<a class="copybtn" href="%s">'
        'View the full %s record on the %s page &rarr;'
        '</a>'

        '</p>'

        '<div style="margin:2rem 0">'
        '<a href="index.html">'
        '&larr; All %s jurisdictions'
        '</a>'
        '</div>'

        '</div>'

        '</main>'

        '%s'

        '</body>'

        '</html>'
        % (
            e(name),

            e(desc),

            canonical,

            e(name),

            HEAD,

            header_html(),

            STATE_SLUG,
            STATE_NAME,
            e(name),

            e(name),

            e(name),
            e(span_txt),

            rel,
            e(name),
            e(primary_name),

            STATE_NAME,

            footer_html(),
        )
    )


# ---------------------------------------------------------------- build
def build_state(
    state_ab,
    LOCALITY,
    by_id,
    lcfy,
    NAMES,
    pa_county,
    pa_timing,
    hma,
    ia,
    svi_lookup,
    nri_lookup,
    tribal_plan,
    ia_timing=None,
    event_ids=None,
):
    """
    Generate all keep-localities plus hub for one state.
    """
    global STATE_AB
    global STATE_NAME
    global STATE_SLUG
    global OUT_DIR

    STATE_AB = state_ab

    STATE_NAME = NAMES.get(
        state_ab,
        state_ab,
    )

    STATE_SLUG = slugify(
        STATE_NAME
    )

    OUT_DIR = os.path.join(
        OUT_ROOT,
        "states",
        STATE_SLUG,
    )

    entries = LOCALITY.get(
        state_ab,
        [],
    )

    js = []
    stubs = []
    dropped = 0
    seen_tribal = set()

    for en in entries:
        c = classify(
            state_ab,
            en["n"],
        )

        if not c["keep"]:
            dropped += 1
            continue

        pinfo = (
            tribal_plan.get(
                (
                    state_ab,
                    c["display"],
                )
            )
            if c["kind"] == "tribal"
            else None
        )

        if pinfo:
            if c["display"] in seen_tribal:
                continue

            seen_tribal.add(
                c["display"]
            )

            if pinfo["role"] == "secondary":
                stubs.append({
                    "name":
                        c["display"],

                    "slug":
                        make_slug(
                            c,
                            state_ab,
                        ),

                    "canonical_url":
                        pinfo[
                            "primary_url"
                        ],

                    "primary_name":
                        pinfo[
                            "primary_name"
                        ],

                    "spans":
                        [
                            NAMES.get(
                                s,
                                s,
                            )
                            for s in pinfo[
                                "states"
                            ]
                        ],

                    "label":
                        kind_label(c),

                    "decl":
                        len(
                            pinfo[
                                "all_ids"
                            ]
                        ),
                })

                continue

            en = dict(en)

            en["ids"] = pinfo[
                "all_ids"
            ]

        s = juris_stats(
            en,
            state_ab,
            c,
            by_id,
            lcfy,
        )

        if (
            pinfo
            and pinfo["role"] == "primary"
            and len(
                pinfo["states"]
            ) > 1
        ):
            s["spans"] = [
                NAMES.get(
                    s2,
                    s2,
                )
                for s2 in pinfo[
                    "states"
                ]
            ]

        js.append(s)

    if not js and not stubs:
        return (
            0,
            dropped,
            0,
            [],
        )

    # ------------------------------------------------------------ PA matching
    pa_lookup = {}
    pa_exact = {}

    for pa_name, pa_val in pa_county.items():
        pa_exact[
            pa_name.strip().lower()
        ] = pa_val

        pa_lookup[
            pa_base_kind(
                pa_name
            )
        ] = pa_val

    for j in js:
        if j["kind"] == "city":
            key = (
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower(),
                "city",
            )

        elif j["kind"] == "county":
            key = (
                pa_base_kind(
                    j["name"]
                )[0],
                "county",
            )

        else:
            key = (
                j["name"]
                .strip()
                .lower(),
                "other",
            )

        pa = (
            pa_lookup.get(
                key
            )
            or pa_exact.get(
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower()
            )
        )

        if pa:
            j["pa_obl"] = pa[0]
            j["pa_proj"] = pa[1]

            j["pa_top_cat"] = (
                PA_CAT_LABELS.get(
                    pa[2],
                    pa[2],
                )
                if len(pa) > 2 and pa[2]
                else ""
            )

            j["pa_cats"] = (
                pa[3]
                if (
                    len(pa) > 3
                    and isinstance(
                        pa[3],
                        dict,
                    )
                )
                else {}
            )

        else:
            j["pa_obl"] = 0
            j["pa_proj"] = 0
            j["pa_top_cat"] = ""
            j["pa_cats"] = {}

    # ------------------------------------------------------------ PA timing
    pt_lookup = {}
    pt_exact = {}

    for pt_name, pt_val in pa_timing.items():
        pt_exact[
            pt_name.strip().lower()
        ] = pt_val

        pt_lookup[
            pa_base_kind(
                pt_name
            )
        ] = pt_val

    for j in js:
        if j["kind"] == "city":
            _k = (
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower(),
                "city",
            )

        elif j["kind"] == "county":
            _k = (
                pa_base_kind(
                    j["name"]
                )[0],
                "county",
            )

        else:
            _k = (
                j["name"]
                .strip()
                .lower(),
                "other",
            )

        j["pa_timing"] = (
            pt_lookup.get(
                _k
            )
            or pt_exact.get(
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower()
            )
            or {}
        )

    # ------------------------------------------------------------ HMA matching
    hm_lookup = {}
    hm_exact = {}

    for hm_name, hm_val in hma.items():
        hm_exact[
            hm_name.strip().lower()
        ] = hm_val

        hm_lookup[
            pa_base_kind(
                hm_name
            )
        ] = hm_val

    for j in js:
        if j["kind"] == "city":
            _k = (
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower(),
                "city",
            )

        elif j["kind"] == "county":
            _k = (
                pa_base_kind(
                    j["name"]
                )[0],
                "county",
            )

        else:
            _k = (
                j["name"]
                .strip()
                .lower(),
                "other",
            )

        j["hma"] = (
            hm_lookup.get(
                _k
            )
            or hm_exact.get(
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower()
            )
            or {}
        )

    # ------------------------------------------------------------ IA matching
    ia_lookup = {}
    ia_exact = {}

    for ia_name, ia_val in ia.items():
        ia_exact[
            ia_name.strip().lower()
        ] = ia_val

        ia_lookup[
            pa_base_kind(
                ia_name
            )
        ] = ia_val

    for j in js:
        if j["kind"] == "city":
            _k = (
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower(),
                "city",
            )

        elif j["kind"] == "county":
            _k = (
                pa_base_kind(
                    j["name"]
                )[0],
                "county",
            )

        else:
            _k = (
                j["name"]
                .strip()
                .lower(),
                "other",
            )

        j["ia"] = (
            ia_lookup.get(
                _k
            )
            or ia_exact.get(
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower()
            )
            or {}
        )

    # ------------------------------------------------------------ IA timing (per disaster)
    # ia-timing.json is keyed by OpenFEMA's raw "Name (Type)" county string.
    # Convert each key with the same rule build.py uses for ia.json, then
    # resolve it exactly the way the ia.json lookup above does, so a
    # jurisdiction gets per-disaster IA from the same match it already gets
    # its IA totals from. Two raw strings that resolve to one jurisdiction are
    # summed rather than one silently overwriting the other.
    it_lookup = {}
    it_exact = {}

    for raw_name, per_dn in (ia_timing or {}).items():
        mname = _ia_raw_to_match_name(
            raw_name
        )

        if not mname:
            continue

        for store, key in (
            (it_lookup, pa_base_kind(mname)),
            (it_exact, mname.strip().lower()),
        ):
            merged = store.setdefault(
                key,
                {},
            )

            for dn, v in (per_dn or {}).items():
                try:
                    vals = [float(x or 0) for x in list(v)[:6]]
                except (TypeError, ValueError):
                    continue

                if len(vals) < 6:
                    continue

                cur = merged.get(str(dn))

                merged[str(dn)] = (
                    vals
                    if cur is None
                    else [a + b for a, b in zip(cur, vals)]
                )

    for j in js:
        if j["kind"] == "city":
            _k = (
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower(),
                "city",
            )

        elif j["kind"] == "county":
            _k = (
                pa_base_kind(
                    j["name"]
                )[0],
                "county",
            )

        else:
            _k = (
                j["name"]
                .strip()
                .lower(),
                "other",
            )

        j["ia_timing"] = (
            it_lookup.get(
                _k
            )
            or it_exact.get(
                j["name"]
                .replace(
                    " (city)",
                    "",
                )
                .strip()
                .lower()
            )
            or {}
        )

    # Statewide sums by disaster (for "share of the statewide total"), plus the
    # declaration labels and event links the panel needs, shared by every page.
    st_ia_dn = {}

    for per_dn in (ia_timing or {}).values():
        for dn, v in (per_dn or {}).items():
            try:
                vals = [float(x or 0) for x in list(v)[:6]]
            except (TypeError, ValueError):
                continue

            if len(vals) < 6:
                continue

            acc = st_ia_dn.setdefault(
                str(dn),
                [0.0] * 6,
            )

            for i in range(6):
                acc[i] += vals[i]

    st_meta = {}

    for r in by_id.values():
        if r.get("state") != state_ab:
            continue

        fds = r.get("femaDeclarationString", "")

        st_meta[decl_num(fds)] = (
            fds,
            r.get("declarationType", ""),
            r.get("incidentType", ""),
            (r.get("declarationDate") or "")[:10],
        )

    for j in js:
        j["ia_dn_state"] = st_ia_dn
        j["dn_meta"] = st_meta
        j["event_ids"] = event_ids or {}
        j["periods"] = PERIODS

    # ------------------------------------------------------------ SVI / NRI matching
    for j in js:
        risk_key = jurisdiction_risk_key(
            j,
            state_ab,
        )

        if risk_key:
            j["svi"] = svi_lookup.get(
                risk_key,
                {},
            )
            j["nri"] = nri_lookup.get(
                risk_key,
                {},
            )
        else:
            j["svi"] = {}
            j["nri"] = {}

        j["risk_fips"] = (
            (j["svi"] or {}).get("fips")
            or (j["nri"] or {}).get("fips")
            or ""
        )

    # ------------------------------------------------ state (governor) declarations
    _sd_state = (
        (load_state_decls().get("states") or {}).get(state_ab)
        or {}
    )

    _sd_counties = _sd_state.get("counties") or {}

    for j in js:
        j["statedecl"] = (
            _sd_counties.get(
                str(j.get("risk_fips") or "")
            )
            or []
        )

        j["statedecl_meta"] = _sd_state if j["statedecl"] else {}

    for j in js:
        j["thin"] = is_thin(j)

        j["content_hash"] = _content_hash(
            j
        )

    seen = {}

    for j in js:
        if j["slug"] in seen:
            j["slug"] = (
                j["slug"]
                + "-2"
            )

        seen[
            j["slug"]
        ] = 1

    js.sort(
        key=lambda j: (
            -j["decl"],
            j["name"],
        )
    )

    os.makedirs(
        OUT_DIR,
        exist_ok=True,
    )

    for j in js:
        open(
            os.path.join(
                OUT_DIR,
                j["slug"]
                + ".html",
            ),
            "w",
            encoding="utf-8",
        ).write(
            render_page(
                j,
                js,
                lcfy,
            )
        )

    for stub in stubs:
        open(
            os.path.join(
                OUT_DIR,
                stub["slug"]
                + ".html",
            ),
            "w",
            encoding="utf-8",
        ).write(
            render_stub(
                stub["name"],
                stub["canonical_url"],
                stub["primary_name"],
                stub["spans"],
            )
        )

    open(
        os.path.join(
            OUT_DIR,
            "index.html",
        ),
        "w",
        encoding="utf-8",
    ).write(
        render_hub(
            js,
            stubs,
            lcfy,
        )
    )

    return (
        len(js),
        dropped,
        len(stubs),
        js,
    )


def main():
    LOCALITY, BROWSE, NAMES, PA_COUNTY = load_data()

    PA_TIMING = load_pa_timing()
    HMA = load_hma()
    IA = load_ia()
    IA_TIMING = load_ia_timing()
    EVENT_IDS = load_event_ids()
    global PERIODS
    PERIODS = load_incident_periods()
    SVI = load_svi()
    NRI = load_nri()

    SVI_LOOKUP = build_risk_lookup(
        SVI
    )
    NRI_LOOKUP = build_risk_lookup(
        NRI
    )

    by_id = {
        r[
            "femaDeclarationString"
        ]: r
        for r in BROWSE
    }

    lcfy = last_complete_fy(
        BROWSE
    )

    tribal_plan = build_tribal_plan(
        LOCALITY,
        NAMES,
    )

    one = os.environ.get(
        "DD_STATE"
    )

    if one:
        targets = [
            one.upper()
        ]

    else:
        targets = sorted(
            LOCALITY.keys(),
            key=lambda s: NAMES.get(
                s,
                s,
            ),
        )

    grand_pages = 0
    grand_states = 0
    grand_drop = 0
    grand_stubs = 0

    all_jurisdictions = []

    for st in targets:
        (
            kept,
            dropped,
            stubs_n,
            js,
        ) = build_state(
            st,
            LOCALITY,
            by_id,
            lcfy,
            NAMES,
            PA_COUNTY.get(
                st,
                {},
            ),
            PA_TIMING.get(
                st,
                {},
            ),
            HMA.get(
                st,
                {},
            ),
            IA.get(
                st,
                {},
            ),
            SVI_LOOKUP,
            NRI_LOOKUP,
            tribal_plan,
            ia_timing=IA_TIMING.get(
                st,
                {},
            ),
            event_ids=EVENT_IDS,
        )

        grand_drop += dropped
        grand_stubs += stubs_n

        if kept or stubs_n:
            grand_states += 1
            grand_pages += kept

            state_name = NAMES.get(
                st,
                st,
            )

            state_slug = slugify(
                state_name
            )

            for j in js:
                all_jurisdictions.append([
                    j["name"],
                    st,
                    state_name,
                    (
                        "states/%s/%s.html"
                        % (
                            state_slug,
                            j["slug"],
                        )
                    ),
                    j["decl"],
                    j["kind"],
                    j["noun"],
                    j.get(
                        "thin",
                        False,
                    ),
                    j.get(
                        "content_hash",
                        "",
                    ),
                ])

            if one:
                print(
                    "generated %d %s jurisdiction pages + hub "
                    "(+%d canonical pointers), through FY%d"
                    % (
                        kept,
                        STATE_NAME,
                        stubs_n,
                        lcfy,
                    )
                )

    # ------------------------------------------------------------ locality search index
    if not one:
        idx_path = os.path.join(
            OUT_ROOT,
            "locality-index.js",
        )

        idx_rows = [
            row[:7]
            for row in all_jurisdictions
        ]

        idx_js = (
            "window.LOCALITY_INDEX="
            + json.dumps(
                idx_rows,
                separators=(
                    ",",
                    ":",
                ),
            )
            + ";"
        )

        open(
            idx_path,
            "w",
            encoding="utf-8",
        ).write(
            idx_js
        )

        # -------------------------------------------------------- sitemap
        sitemap_path = os.path.join(
            OUT_ROOT,
            "sitemap.xml",
        )

        state_path = os.path.join(
            OUT_ROOT,
            "sitemap-state.json",
        )

        if os.path.exists(
            sitemap_path
        ):
            try:
                prev_state = json.load(
                    open(
                        state_path,
                        encoding="utf-8",
                    )
                )

            except Exception:
                prev_state = {}

            today = (
                datetime.date.today()
                .isoformat()
            )

            new_state = {}

            entries = []

            hub_lastmods = {}

            skipped_thin = 0

            for j in all_jurisdictions:
                url = "%s/%s" % (
                    SITE,
                    j[3],
                )

                thin = (
                    bool(
                        j[7]
                    )
                    if len(j) > 7
                    else False
                )

                chash = (
                    j[8]
                    if len(j) > 8
                    else ""
                )

                prev = prev_state.get(
                    url
                )

                lastmod = (
                    prev.get(
                        "lastmod",
                        today,
                    )
                    if (
                        prev
                        and prev.get(
                            "hash"
                        ) == chash
                    )
                    else today
                )

                new_state[
                    url
                ] = {
                    "hash":
                        chash,

                    "lastmod":
                        lastmod,
                }

                hub_url = "%s/%s/" % (
                    SITE,
                    "/".join(
                        j[3].split(
                            "/"
                        )[:2]
                    ),
                )

                if (
                    lastmod
                    > hub_lastmods.get(
                        hub_url,
                        "",
                    )
                ):
                    hub_lastmods[
                        hub_url
                    ] = lastmod

                if thin:
                    skipped_thin += 1
                    continue

                entries.append(
                    (
                        url,
                        lastmod,
                    )
                )

            for (
                hub_url,
                lastmod,
            ) in hub_lastmods.items():
                entries.append(
                    (
                        hub_url,
                        lastmod,
                    )
                )

            new_urls = "".join(
                (
                    "<url>"
                    "<loc>%s</loc>"
                    "<lastmod>%s</lastmod>"
                    "</url>"
                    % (
                        u,
                        lm,
                    )
                )
                for u, lm in entries
            )

            sm = open(
                sitemap_path,
                encoding="utf-8",
            ).read()

            sm = re.sub(
                (
                    r"<url>\s*<loc>"
                    + re.escape(
                        SITE
                    )
                    + r"/states/[^/<]+/[^<]*</loc>.*?</url>"
                ),
                "",
                sm,
                flags=re.S,
            )

            sm = sm.replace(
                "</urlset>",
                new_urls
                + "</urlset>",
            )

            open(
                sitemap_path,
                "w",
                encoding="utf-8",
            ).write(
                sm
            )

            json.dump(
                new_state,
                open(
                    state_path,
                    "w",
                    encoding="utf-8",
                ),
                separators=(
                    ",",
                    ":",
                ),
                sort_keys=True,
            )

            print(
                "extended sitemap.xml with %d indexed URLs "
                "(%d thin pages skipped)"
                % (
                    len(entries),
                    skipped_thin,
                )
            )

        print(
            "generated %d jurisdiction pages + %d canonical pointers "
            "+ %d hubs across %d states/territories, through FY%d "
            "(skipped %d non-locality entries)"
            % (
                grand_pages,
                grand_stubs,
                grand_states,
                grand_states,
                lcfy,
                grand_drop,
            )
        )

        print(
            "wrote locality-index.js (%d entries, %d KB)"
            % (
                len(
                    all_jurisdictions
                ),
                len(
                    idx_js
                ) // 1024,
            )
        )


if __name__ == "__main__":
    main()
