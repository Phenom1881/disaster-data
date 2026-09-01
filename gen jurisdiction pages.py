#!/usr/bin/env python3
"""
gen_jurisdiction_pages.py
-------------------------

Build DisasterData.IO jurisdiction pages for counties, county-equivalents,
independent cities, and tribal areas.

Inputs
------
data.js
    window.LOCALITY_DATA
    window.BROWSE
    window.STATE_NAMES
    window.PA_BY_COUNTY

pa-timing.json
    Public Assistance obligation timing produced by build.py.

hma.json
    Hazard Mitigation Assistance rollups produced by build.py.

ia.json
    Individual Assistance rollups produced by build.py.

county-svi.js
    window.COUNTY_SVI
    CDC/ATSDR Social Vulnerability Index 2022, keyed by 5-digit FIPS/GEOID.

county-nri.js
    window.COUNTY_NRI
    FEMA National Risk Index county data, keyed by 5-digit FIPS/GEOID.

Outputs
-------
states/<state-slug>/<jurisdiction-slug>.html
states/<state-slug>/index.html
locality-index.js
updated sitemap.xml / sitemap-state.json

The SVI and NRI data are baked directly into the generated static HTML so
jurisdiction pages do not depend on JavaScript loading those data files in
the visitor's browser.
"""

import os
import re
import json
import html
import datetime
import hashlib

from dd_classify import classify


# =============================================================================
# SITE / PATH CONFIGURATION
# =============================================================================

SITE = "https://disasterdata.io"

OUT_ROOT = os.environ.get("DD_OUT", ".")
SRC_ROOT = os.environ.get("DD_SRC", OUT_ROOT)

STATE_AB = os.environ.get("DD_STATE", "VA").upper()
STATE_NAME = STATE_AB
STATE_SLUG = STATE_AB.lower()

OUT_DIR = os.path.join(OUT_ROOT, "states", STATE_SLUG)


# =============================================================================
# DATA LOADING
# =============================================================================

def _grab_js(text, name):
    """
    Extract JSON assigned to window.<name> from a JavaScript data file.
    """
    m = re.search(r"window\." + re.escape(name) + r"\s*=\s*", text)

    if not m:
        raise SystemExit("could not find window.%s" % name)

    return json.JSONDecoder().raw_decode(text, m.end())[0]


def load_data():
    """
    Read the core DisasterData data.js bundle.
    """
    p = os.path.join(SRC_ROOT, "data.js")

    if not os.path.exists(p):
        raise SystemExit("data.js not found in %s" % SRC_ROOT)

    text = open(p, encoding="utf-8").read()

    try:
        pa_county = _grab_js(text, "PA_BY_COUNTY")
    except (Exception, SystemExit):
        pa_county = {}

    return (
        _grab_js(text, "LOCALITY_DATA"),
        _grab_js(text, "BROWSE"),
        _grab_js(text, "STATE_NAMES"),
        pa_county,
    )


def load_pa_timing():
    """
    Per-jurisdiction Public Assistance obligation timing.

    Shape:
    {
        ST: {
            county: {
                disasterNumber:
                    [declDate, firstObl, lastObl, obl, topCat]
            }
        }
    }
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
    Hazard Mitigation Assistance rollup.

    Shape:
    {
        ST: {
            matchName: {
                "fed": int,
                "n": int,
                "prog": {code: [fed, n]},
                "props": int
            }
        }
    }
    """
    p = os.path.join(SRC_ROOT, "hma.json")

    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def load_ia():
    """
    Individual Assistance rollup.

    Shape:
    {
        ST: {
            matchName: {
                "reg": int,
                "app": int,
                "ihp": int,
                "rr": int,
                "rent": int,
                "ona": int
            }
        }
    }
    """
    p = os.path.join(SRC_ROOT, "ia.json")

    if not os.path.exists(p):
        return {}

    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _load_county_js(filename, window_name):
    """
    Load one of the FIPS-keyed static county data files.

    Expected:

        window.COUNTY_SVI = {...};

    or:

        window.COUNTY_NRI = {...};

    Missing optional files do not stop jurisdiction generation.
    """
    p = os.path.join(SRC_ROOT, filename)

    if not os.path.exists(p):
        print(
            "  NOTE: %s not found; matching jurisdiction risk section will be skipped"
            % filename
        )
        return {}

    try:
        text = open(p, encoding="utf-8").read()
        data = _grab_js(text, window_name)

        print(
            "  loaded %s (%s county records)"
            % (filename, format(len(data), ","))
        )

        return data

    except (Exception, SystemExit) as ex:
        print("  WARNING: could not read %s: %s" % (filename, ex))
        return {}


def load_svi():
    """
    CDC/ATSDR Social Vulnerability Index 2022.
    """
    return _load_county_js(
        "county-svi.js",
        "COUNTY_SVI",
    )


def load_nri():
    """
    FEMA National Risk Index county data.
    """
    return _load_county_js(
        "county-nri.js",
        "COUNTY_NRI",
    )


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def fy_of(iso):
    """
    Convert YYYY-MM-DD to federal fiscal year.
    """
    try:
        y = int(iso[:4])
        m = int(iso[5:7])

        return y + 1 if m >= 10 else y

    except Exception:
        return 0


def fmt_date(iso):
    """
    Readable date without relying on platform-specific %-d.
    """
    try:
        d = datetime.datetime.strptime(iso[:10], "%Y-%m-%d")
        return "%s %d, %d" % (
            d.strftime("%b"),
            d.day,
            d.year,
        )

    except Exception:
        return iso


def pretty_title(t):
    t = (t or "").strip()
    return t.title() if t.isupper() else t


def slugify(s):
    s = str(s or "").lower()
    s = s.replace("&", "and")
    s = s.replace(".", "")
    s = s.replace(",", "")

    s = re.sub(r"[^\w\s/-]", "", s)
    s = re.sub(r"[\s/]+", "-", s).strip("-")

    return re.sub(r"-+", "-", s)


def decl_num(s):
    """
    Sortable integer inside FEMA declaration string.
    """
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else "0"


def _money_full(n):
    """
    Full-dollar format.
    """
    try:
        return "$" + format(int(round(float(n or 0))), ",")
    except Exception:
        return "$0"


def _money_short(n):
    """
    Compact money format for top-level metrics.
    """
    try:
        n = float(n or 0)
    except Exception:
        n = 0

    if n >= 1e9:
        return "$%.1fB" % (n / 1e9)

    if n >= 1e6:
        return "$%.1fM" % (n / 1e6)

    if n >= 1e3:
        return "$%.0fK" % (n / 1e3)

    return "$%s" % format(int(round(n)), ",")


def _money_words(n):
    """
    Human-readable Public Assistance dollars for narrative text.
    """
    try:
        n = float(n or 0)
    except Exception:
        n = 0

    if n >= 1e9:
        return "about $%.1f billion" % (n / 1e9)

    if n >= 1e6:
        return "about $%.1f million" % (n / 1e6)

    return "$" + format(int(round(n)), ",")


def _oxford(items):
    items = list(items)

    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return items[0] + " and " + items[1]

    return ", ".join(items[:-1]) + ", and " + items[-1]


TYPE_LONG = {
    "DR": "Major disaster",
    "EM": "Emergency",
    "FM": "Fire management",
}


# =============================================================================
# DECLARATION FILTER JAVASCRIPT
# =============================================================================

FILTER_JS = """<script>
(function(){
  var box=document.getElementById('declbox');
  if(!box) return;

  var cap=box.querySelector('.decl-count');
  var chips=box.querySelectorAll('.decl-chip');
  var table=box.querySelector('table');

  if(!table) return;

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
      var x=val(a,i,k);
      var y=val(b,i,k);

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

        sortCol(
          i,
          th.getAttribute('data-k')||'text',
          dir
        );
      });
    })(heads[h],h);
  }

  filter('ALL');
})();
</script>"""


def type_chips(total, dr, em, fm):
    """
    Declaration filter chips.
    """
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
        '<div class="decl-filters" '
        'role="group" aria-label="Filter declarations by type">'
        + chip("ALL", total, True)
        + chip("DR", dr)
        + chip("EM", em)
        + chip("FM", fm)
        + "</div>"
    )


# =============================================================================
# PROGRAM LABELS / STATE FIPS
# =============================================================================

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


STATE_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "AS": "60",
    "GU": "66",
    "MP": "69",
    "PR": "72",
    "VI": "78",
}


# =============================================================================
# JURISDICTION NAME MATCHING
# =============================================================================

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
    Normalize PA/IA/HMA names to (base, kind).

    This intentionally keeps independent cities separate from like-named
    counties.
    """
    low = str(name or "").strip().lower()

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


def make_slug(c, state_ab):
    """
    State-qualified, type-aware slug.
    """
    st = "-" + state_ab.lower()

    if c["kind"] == "county":
        base = slugify(c["base"])
        noun = slugify(c["noun"])

        if base.endswith("-" + noun) or base == noun:
            return base + st

        return base + "-" + noun + st

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
    Adaptive state hub wording.
    """
    cnouns = sorted(
        {j["noun"] for j in js if j["kind"] == "county"}
    )

    parts = []

    if cnouns:
        if len(cnouns) == 1:
            parts.append(cnouns[0].lower())
        else:
            parts.append("county or county-equivalent")

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


# =============================================================================
# SVI / NRI MATCHING
# =============================================================================

_RISK_SUFFIXES = [
    "city and borough",
    "census area",
    "county",
    "parish",
    "borough",
    "municipio",
    "municipality",
    "island",
    "district",
    "city",
]


def _risk_base(name):
    """
    Normalize a county-equivalent name for SVI/NRI matching.
    """
    s = str(name or "").strip().lower()

    # Remove parenthetical city labels from generated jurisdiction names.
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)

    # Strip comma-delimited add-ons.
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
    Classify FIPS county-equivalent as county-like or independent city.

    Virginia independent-city county-equivalent FIPS values have county
    components 500 and above. Explicit 'city' suffix is a second check.
    """
    fp = str(fips or "").zfill(5)
    source = str(source_name or "").strip().lower()

    city_equivalent = False

    try:
        city_equivalent = int(fp[2:]) >= 500
    except Exception:
        pass

    if source.endswith(" city"):
        city_equivalent = True

    return "city" if city_equivalent else "county"


def build_risk_lookup(dataset):
    """
    Convert FIPS-keyed SVI/NRI data to:

        (state, normalized name, county/city) -> record

    The FIPS code is copied into the record.
    """
    lookup = {}

    for fips, raw in (dataset or {}).items():

        if not isinstance(raw, dict):
            continue

        st = str(raw.get("state") or "").upper().strip()
        source_name = raw.get("county") or ""

        if not st or not source_name:
            continue

        rec = dict(raw)
        rec["fips"] = str(fips).zfill(5)

        key = (
            st,
            _risk_base(source_name),
            _risk_kind(fips, source_name),
        )

        lookup[key] = rec

    return lookup


def jurisdiction_risk_key(j, state_ab):
    """
    Build the lookup key for a generated county or independent city.
    """
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


# =============================================================================
# FISCAL YEAR / THIN PAGE / CONTENT HASH
# =============================================================================

def last_complete_fy(browse):
    now = datetime.date.today()

    cur = now.year + 1 if now.month >= 10 else now.year

    avail = max(
        (r.get("fyDeclared", 0) for r in browse),
        default=cur,
    )

    return min(cur - 1, avail)


MIN_DISTINCT_DECLS = 2


def _is_nationwide(rec):
    """
    Nationwide declarations such as COVID do not meaningfully distinguish
    one jurisdiction from another.
    """
    title = (rec.get("declarationTitle") or "").upper()

    return (
        "COVID" in title
        or "PANDEMIC" in title
    )


def is_thin(j):
    """
    Preserve the existing thin-page rule.

    SVI/NRI do not automatically change this SEO gate.
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
    Stable fingerprint of everything material rendered on a jurisdiction
    page.

    SVI and NRI are included so sitemap lastmod advances when those source
    records change.
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
        "hma": j.get("hma", {}),
        "ia": j.get("ia", {}),
        "svi": j.get("svi", {}),
        "nri": j.get("nri", {}),
        "risk_fips": j.get("risk_fips", ""),
        "recs": sorted(
            [
                r.get("femaDeclarationString", ""),
                r.get("declarationDate", "")[:10],
                r.get("declarationType", ""),
                r.get("incidentType", ""),
                pretty_title(r.get("declarationTitle", "")),
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


# =============================================================================
# JURISDICTION BASE STATISTICS
# =============================================================================

def juris_stats(entry, state_ab, c, by_id, lcfy):
    disp = c["display"]
    slug = make_slug(c, state_ab)
    kind = c["kind"]

    recs = [
        by_id[i]
        for i in entry.get("ids", [])
        if i in by_id
    ]

    complete = [
        r
        for r in recs
        if r.get("fyDeclared", 9999) <= lcfy
    ]

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

        if h:
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

        "hmp": sorted(
            complete,
            key=lambda r: r.get("declarationDate", ""),
            reverse=True,
        ),

        "latest": latest,
        "lcfy": lcfy,
    }


# =============================================================================
# PAGE CSS
# =============================================================================

CSS = """
:root{
  --teal:#004c53;
  --teal2:#0f6870;
  --teal-soft:#d7e9ea;
  --cream:#f6f1e7;
  --paper:#fffdf7;
  --ink:#2b2b2b;
  --ink2:#4e493f;
  --ink3:#6b6357;
  --rule:#e4dccb;
  --amber:#c85c2e;
  --shadow:0 8px 28px rgba(47,40,27,.055);
}

*{box-sizing:border-box}

html{scroll-behavior:smooth}

body{
  margin:0;
  background:var(--cream);
  color:var(--ink);
  font-family:'Public Sans',system-ui,-apple-system,sans-serif;
  line-height:1.6;
}

a{color:var(--teal)}

.wrap{
  max-width:1080px;
  margin:0 auto;
  padding:0 clamp(18px,4vw,44px);
}

main{padding:2rem 0 1rem}

.crumb{
  font-size:.82rem;
  color:var(--ink3);
  margin:0 0 1.2rem;
}

.crumb a{text-decoration:none}

.badge{
  display:inline-block;
  font:700 .7rem 'Public Sans',sans-serif;
  text-transform:uppercase;
  letter-spacing:.055em;
  padding:.24rem .65rem;
  border-radius:999px;
}

.badge.county{
  color:#004c53;
  background:#d7e9ea;
}

.badge.city{
  color:#8a5a2b;
  background:#f3e4d2;
}

.badge.tribal{
  color:#6a2f6a;
  background:#efddef;
}

.hero{
  padding:.4rem 0 .7rem;
}

.hero-top{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:1rem;
}

.hero-actions{
  display:flex;
  flex-wrap:wrap;
  justify-content:flex-end;
  gap:.5rem;
}

.hero-link{
  display:inline-flex;
  align-items:center;
  gap:.35rem;
  text-decoration:none;
  font-size:.8rem;
  font-weight:700;
  border:1px solid #b7cfce;
  background:#edf5f4;
  color:var(--teal);
  border-radius:999px;
  padding:.42rem .75rem;
  white-space:nowrap;
}

.hero-link:hover{
  background:#dcebea;
}

h1{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:clamp(2rem,5vw,3.05rem);
  line-height:1.04;
  letter-spacing:-.035em;
  margin:.42rem 0 .75rem;
}

h2{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:1.45rem;
  line-height:1.2;
  letter-spacing:-.015em;
  margin:2.4rem 0 .7rem;
}

h3{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:1.16rem;
  line-height:1.25;
  margin:0 0 .35rem;
}

.lede{
  margin:.25rem 0 0;
  font-size:1.08rem;
  max-width:72ch;
  color:var(--ink2);
}

.current-note{
  margin:.8rem 0 0;
  max-width:72ch;
  font-size:.79rem;
  color:var(--ink3);
}

.overview-grid{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:.8rem;
  margin:1.55rem 0 1.2rem;
}

.overview-card{
  min-height:122px;
  display:flex;
  flex-direction:column;
  justify-content:space-between;
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:16px;
  padding:1rem 1.05rem;
  box-shadow:var(--shadow);
}

.overview-kicker{
  font-size:.68rem;
  font-weight:800;
  letter-spacing:.075em;
  text-transform:uppercase;
  color:var(--ink3);
}

.overview-value{
  font-family:'Fraunces',Georgia,serif;
  font-size:1.85rem;
  line-height:1;
  letter-spacing:-.035em;
  color:var(--teal);
  margin:.35rem 0 .28rem;
}

.overview-label{
  color:var(--ink3);
  font-size:.78rem;
  line-height:1.35;
}

.jsummary{
  margin:1.15rem 0 .5rem;
}

.jsummary p{
  margin:0;
  font-size:1rem;
  max-width:74ch;
}

.major-section{
  margin:2.5rem 0;
}

.section-head{
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:1rem;
  margin-bottom:1rem;
}

.section-head h2{
  margin:0 0 .25rem;
}

.section-deck{
  max-width:72ch;
  margin:0;
  color:var(--ink3);
  font-size:.9rem;
}

.section-meta{
  flex:none;
  font-size:.7rem;
  font-weight:800;
  text-transform:uppercase;
  letter-spacing:.055em;
  color:var(--ink3);
  white-space:nowrap;
}

.risk-grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:1rem;
}

.risk-card{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:18px;
  padding:1.15rem 1.2rem 1.25rem;
  box-shadow:var(--shadow);
}

.risk-kicker{
  font-size:.68rem;
  font-weight:800;
  letter-spacing:.085em;
  text-transform:uppercase;
  color:var(--ink3);
}

.risk-version{
  margin:.05rem 0 .95rem;
  font-size:.75rem;
  color:var(--ink3);
}

.svi-lead,
.nri-lead{
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:1rem;
  margin:.65rem 0 .95rem;
}

.risk-score{
  font-family:'Fraunces',Georgia,serif;
  color:var(--teal);
  font-size:2.15rem;
  line-height:.95;
  letter-spacing:-.04em;
}

.risk-score-label{
  margin-top:.28rem;
  font-size:.72rem;
  color:var(--ink3);
}

.risk-rating{
  display:inline-flex;
  align-items:center;
  border-radius:999px;
  background:#edf5f4;
  color:var(--teal);
  border:1px solid #cfe0df;
  font-size:.72rem;
  font-weight:800;
  padding:.3rem .6rem;
  white-space:nowrap;
}

.risk-interpret{
  font-size:.83rem;
  color:var(--ink2);
  margin:.3rem 0 .95rem;
}

.theme-list{
  display:grid;
  gap:.65rem;
  margin-top:.9rem;
}

.theme-head{
  display:flex;
  justify-content:space-between;
  align-items:baseline;
  gap:.8rem;
  font-size:.76rem;
}

.theme-head span{
  color:var(--ink2);
}

.theme-head b{
  color:var(--teal);
  font-variant-numeric:tabular-nums;
}

.theme-track{
  height:6px;
  border-radius:999px;
  background:#ebe5d8;
  overflow:hidden;
  margin-top:.25rem;
}

.theme-track span{
  display:block;
  height:100%;
  background:#2d7d83;
  border-radius:999px;
}

.risk-mini-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:.55rem;
  margin-top:.8rem;
}

.risk-mini{
  background:#faf7ef;
  border:1px solid #ece5d7;
  border-radius:11px;
  padding:.7rem;
}

.risk-mini span{
  display:block;
  color:var(--ink3);
  font-size:.67rem;
  line-height:1.3;
}

.risk-mini b{
  display:block;
  margin-top:.2rem;
  color:var(--teal);
  font-family:'Fraunces',Georgia,serif;
  font-size:1rem;
  line-height:1.15;
}

.risk-mini small{
  display:block;
  color:var(--ink3);
  font-size:.63rem;
  line-height:1.25;
  margin-top:.12rem;
}

.risk-source{
  margin:.9rem 0 0;
  font-size:.74rem;
  color:var(--ink3);
}

.risk-caution{
  margin-top:.8rem;
  padding:.72rem .85rem;
  border:1px solid #d6dfdc;
  border-radius:11px;
  background:#f0f6f5;
  font-size:.77rem;
  color:#4b5b58;
}

.map-shell{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:18px;
  padding:1rem;
  box-shadow:var(--shadow);
  margin:1rem 0;
}

#locmap{
  height:330px;
  border-radius:12px;
  border:1px solid #e4dccb;
  background:#f6f1e7;
}

.locmap-cap{
  font:600 .8rem/1.3 'Public Sans',sans-serif;
  color:#004c53;
  margin:.65rem 0 .05rem;
  text-align:center;
}

.locmap-cap b{
  font-weight:700;
}

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
    0 0 3px rgba(0,0,0,.55);
}

.loc-lbl:before,
.loc-lbl:after{
  display:none !important;
}

ul.haz{
  list-style:none;
  padding:0;
  margin:.65rem 0 0;
  display:flex;
  flex-wrap:wrap;
  gap:.5rem;
}

ul.haz li{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:999px;
  padding:.32rem .78rem;
  font-size:.82rem;
}

ul.haz b{
  color:var(--teal);
  margin-left:.15rem;
}

.assistance-stack{
  display:grid;
  gap:1rem;
  margin-top:1rem;
}

.data-panel{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:16px;
  padding:1.05rem 1.1rem 1.15rem;
  box-shadow:var(--shadow);
}

.data-panel h3{
  margin-top:0;
}

.pa-note{
  font-size:.86rem;
  color:var(--ink3);
  max-width:74ch;
  margin:.3rem 0 .85rem;
}

.hm-stats,
.ia-stats{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:1px;
  background:#e2dccb;
  border:1px solid #cec7b6;
  border-radius:10px;
  overflow:hidden;
  margin:.65rem 0 .9rem;
}

.hm-stat,
.ia-stat{
  background:#faf7ef;
  padding:.75rem .9rem;
}

.hm-n,
.ia-n{
  font-family:'Fraunces',Georgia,serif;
  font-size:1.15rem;
  color:#004c53;
  letter-spacing:-.3px;
}

.hm-l,
.ia-l{
  font-size:.7rem;
  color:#6b6357;
  margin-top:.15rem;
}

.tablewrap{
  overflow-x:auto;
  border:1px solid var(--rule);
  border-radius:12px;
  background:var(--paper);
}

table{
  border-collapse:collapse;
  width:100%;
  font-size:.84rem;
  min-width:560px;
}

th,
td{
  text-align:left;
  padding:.58rem .8rem;
  border-bottom:1px solid var(--rule);
  vertical-align:top;
}

th{
  font-size:.71rem;
  text-transform:uppercase;
  letter-spacing:.035em;
  color:var(--ink3);
  background:#faf6ec;
}

tr:last-child td{
  border-bottom:none;
}

.tag{
  font-weight:700;
  color:var(--teal);
}

table.pa-cat tfoot td{
  font-weight:700;
  color:var(--teal);
  border-top:2px solid var(--rule);
  background:#faf6ec;
}

.pa-cat .catcode{
  color:var(--ink3);
  font-weight:400;
  font-size:.85em;
  margin-left:.15em;
}

table.pa-cat td:nth-child(2),
table.pa-cat th:nth-child(2),
table.pa-cat td:nth-child(3),
table.pa-cat th:nth-child(3){
  text-align:right;
  font-variant-numeric:tabular-nums;
  white-space:nowrap;
}

.ft-list{
  display:grid;
  gap:1px;
  background:#e2dccb;
  border:1px solid #cec7b6;
  border-radius:10px;
  overflow:hidden;
  margin:.6rem 0 .3rem;
}

.ft-row{
  background:#faf7ef;
  padding:.72rem .9rem;
}

.ft-top{
  display:flex;
  justify-content:space-between;
  gap:.8rem;
  align-items:baseline;
}

.ft-name{
  font-size:.88rem;
  color:#17211f;
  font-weight:600;
}

.ft-date{
  color:#6b6357;
  font-weight:400;
}

.ft-val{
  font-family:Fraunces,Georgia,serif;
  font-size:1rem;
  color:#004c53;
}

.ft-track{
  position:relative;
  height:11px;
  margin:.5rem 0 .35rem;
  background:#ece7d8;
  border:1px solid #e2dccb;
  border-radius:6px;
  overflow:hidden;
}

.ft-gap{
  position:absolute;
  top:0;
  left:0;
  height:100%;
  background:#c85c2e;
}

.ft-flow{
  position:absolute;
  top:0;
  height:100%;
  background:#004c53;
}

.ft-meta{
  font-size:.7rem;
  color:#6b6357;
}

.ft-meta b{
  color:#c85c2e;
}

.ft-axis{
  position:relative;
  height:1.1rem;
  margin:.15rem .9rem 0;
  font-size:.64rem;
  color:#6b6357;
}

.ft-axis span{
  position:absolute;
  transform:translateX(-50%);
}

.ft-axis span:first-child{
  transform:none;
}

.hmp{
  background:#eef4f4;
  border:1px solid #cfe0e0;
  border-radius:14px;
  padding:1.1rem 1.2rem;
  margin:1rem 0;
}

.hmp p{
  margin:.1rem 0 .9rem;
  font-size:.88rem;
}

.copybtn{
  display:inline-flex;
  align-items:center;
  font:700 .78rem 'Public Sans',sans-serif;
  color:#004c53;
  background:none;
  border:1px solid #004c53;
  border-radius:8px;
  padding:.42rem .8rem;
  cursor:pointer;
  margin-top:.8rem;
  text-decoration:none;
}

.copybtn:hover{
  background:#e6f0ef;
}

.decl-filters{
  display:flex;
  flex-wrap:wrap;
  gap:.4rem;
  margin:.2rem 0 .5rem;
}

.decl-chip{
  font:700 .78rem/1 'Public Sans',sans-serif;
  color:var(--teal);
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:999px;
  padding:.42rem .7rem;
  cursor:pointer;
  display:inline-flex;
  align-items:center;
  gap:.4rem;
}

.decl-chip .n{
  background:#eef3f2;
  border-radius:999px;
  padding:.06rem .42rem;
  font-size:.73rem;
  font-weight:700;
}

.decl-chip[aria-pressed="true"]{
  background:var(--teal);
  color:#fff;
  border-color:var(--teal);
}

.decl-chip[aria-pressed="true"] .n{
  background:rgba(255,255,255,.22);
  color:#fff;
}

.decl-chip.off{
  opacity:.42;
  cursor:default;
}

.decl-count{
  font-size:.8rem;
  color:var(--ink3);
  margin:.05rem 0 .55rem;
}

.tablewrap.scroll{
  max-height:430px;
  overflow-y:auto;
}

.tablewrap.scroll thead th{
  position:sticky;
  top:0;
  z-index:1;
}

tr.hide{
  display:none;
}

th.sortable{
  cursor:pointer;
  user-select:none;
  -webkit-user-select:none;
  white-space:nowrap;
}

th.sortable::after{
  content:"↕";
  opacity:.32;
  margin-left:.35em;
  font-weight:400;
}

th.sortable:hover{
  color:var(--teal);
}

th[aria-sort="ascending"]::after{
  content:"↑";
  opacity:.95;
}

th[aria-sort="descending"]::after{
  content:"↓";
  opacity:.95;
}

.method{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:16px;
  padding:1.15rem 1.25rem;
  margin:2rem 0;
  font-size:.86rem;
}

.method h2{
  margin-top:0;
  font-size:1.15rem;
}

.jgrid{
  display:flex;
  flex-wrap:wrap;
  gap:.4rem .7rem;
  margin:.6rem 0;
}

.jgrid a{
  font-size:.83rem;
  text-decoration:none;
}

ol.rank{
  padding-left:0;
  list-style:none;
  counter-reset:r;
}

ol.rank li{
  counter-increment:r;
  display:flex;
  align-items:baseline;
  gap:.7rem;
  padding:.45rem 0;
  border-bottom:1px solid var(--rule);
}

ol.rank li::before{
  content:counter(r);
  font-family:'Fraunces',serif;
  color:var(--ink3);
  min-width:2.6ch;
  text-align:right;
}

ol.rank a{
  text-decoration:none;
  font-weight:600;
}

ol.rank .k{
  font-size:.7rem;
  text-transform:uppercase;
  letter-spacing:.04em;
  color:var(--ink3);
}

ol.rank .c{
  color:var(--ink3);
  font-size:.86rem;
  margin-left:auto;
}

footer.site{
  border-top:1px solid var(--rule);
  margin-top:2rem;
  padding:1.5rem 0;
  color:var(--ink3);
  font-size:.82rem;
}

footer.site a{
  color:var(--ink3);
}

@media(max-width:860px){
  .overview-grid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .risk-mini-grid{
    grid-template-columns:1fr;
  }
}

@media(max-width:720px){
  .hero-top{
    display:block;
  }

  .hero-actions{
    justify-content:flex-start;
    margin-top:.65rem;
  }

  .risk-grid{
    grid-template-columns:1fr;
  }

  .section-head{
    display:block;
  }

  .section-meta{
    margin-top:.45rem;
  }
}

@media(max-width:600px){
  .overview-grid{
    grid-template-columns:1fr 1fr;
  }

  .overview-card{
    min-height:112px;
  }

  #locmap{
    height:245px;
  }

  .hm-stats,
  .ia-stats{
    grid-template-columns:1fr;
  }
}
""".strip()


FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600'
    '&family=Public+Sans:wght@400;500;600;700&display=swap" '
    'rel="stylesheet">'
)


HEAD = (
    FONTS
    + '<link rel="stylesheet" '
      'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
    + "<style>"
    + CSS
    + "</style>"
)


# =============================================================================
# SHARED PAGE CHROME
# =============================================================================

def header_html():
    return '<script src="/nav.js"></script>'


def footer_html():
    return (
        '<footer class="site"><div class="wrap">'
        'Disaster Data &middot; built from FEMA OpenFEMA, CDC/ATSDR SVI, '
        'and FEMA National Risk Index data &middot; refreshed as source data are updated'
        ' &middot; <a href="https://forms.gle/NZ6bSadoXrKYHjjH8" '
        'target="_blank" rel="noopener">Report a data issue</a>'
        ' &middot; <a href="../../about.html">About and contact</a>'
        '</div></footer>'
        '<!-- Cloudflare Web Analytics -->'
        '<script defer '
        'src="https://static.cloudflareinsights.com/beacon.min.js" '
        'data-cf-beacon=\'{"token":"ceea2416f66a424981ba37fcb9440d68"}\'>'
        '</script>'
        '<!-- End Cloudflare Web Analytics -->'
    )


# =============================================================================
# SUMMARY / METHODOLOGY
# =============================================================================

def summary_html(j):
    """
    Data-driven summary paragraph.
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

    sents = [
        "The federal disaster record for %s runs %s, covering %d declaration%s "
        "in completed fiscal years."
        % (
            name,
            span,
            j["decl"],
            "" if j["decl"] == 1 else "s",
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
            "Every declaration in the completed-year record was tied to %s."
            % e(hz[0][0].lower())
        )

    if (j.get("pa_obl") or 0) > 0:
        tail = ""

        if j.get("pa_top_cat"):
            tail = (
                ", with the largest category being %s"
                % e(j["pa_top_cat"].lower())
            )

        sents.append(
            "Since 2000, FEMA has obligated %s in Public Assistance "
            "funding to the jurisdiction%s."
            % (
                _money_words(j["pa_obl"]),
                tail,
            )
        )

    if (j.get("ia") or {}).get("ihp", 0) > 0:
        sents.append(
            "FEMA Individual Assistance records show %s approved through "
            "the Individuals and Households Program."
            % _money_words(
                (j.get("ia") or {}).get("ihp", 0)
            )
        )

    return (
        '<section class="jsummary"><p>%s</p></section>'
        % " ".join(sents)
    )


def method_html(j):
    """
    Page-specific methodology text.
    """
    kind = j["kind"]
    spans = bool(j.get("spans"))

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
                "separate from counties."
                + (
                    " Because this nation's lands cross state lines, FEMA "
                    "declarations recorded for it in multiple states are "
                    "combined here so the record is not split."
                    if spans
                    else ""
                )
            ),
    }[kind]

    risk_text = ""

    if j.get("svi") or j.get("nri"):
        risk_text = (
            " Risk and vulnerability context is joined at the county-equivalent "
            "level using the five-digit Census/FIPS GEOID. CDC/ATSDR SVI and "
            "FEMA National Risk Index Social Vulnerability are different measures "
            "and are not treated as interchangeable."
        )

    return (
        '<section class="method">'
        '<h2>How these numbers are built</h2>'
        '<p>'
        "Declaration history comes from FEMA's OpenFEMA Disaster Declarations "
        "Summaries and is rebuilt with the site data pipeline. A declaration is "
        "counted once for each designated area it names, so a single disaster "
        "covering many localities is counted in each locality. For that reason, "
        "jurisdiction counts do not sum to %s's statewide total. %s "
        "Headline declaration totals cover completed federal fiscal years "
        "(Oct. 1 through Sept. 30). Activity from the current fiscal year may "
        "appear as the most recent event before it is included in those totals.%s "
        "Public Assistance, Individual Assistance, and Hazard Mitigation figures "
        "reflect the underlying federal datasets and may change as records are "
        "updated or projects close out. DisasterData.IO uses federal source data "
        "but is not endorsed by or affiliated with FEMA, CDC, or ATSDR."
        '</p></section>'
        % (
            STATE_NAME,
            extra,
            risk_text,
        )
    )


# =============================================================================
# TOP-OF-PAGE OVERVIEW CARDS
# =============================================================================

def hero_cards_html(j):
    """
    Modern four-card overview.

    IA appears only where IA exists. NRI appears only where matched.
    """
    cards = []

    common_hazard = (
        j["hazards"][0][0]
        if j.get("hazards")
        else "No dominant hazard"
    )

    cards.append(
        (
            "Federal disaster history",
            format(j.get("decl", 0), ","),
            "%s most common" % common_hazard,
        )
    )

    nri = j.get("nri") or {}

    if nri:
        try:
            score = "%.1f" % float(nri.get("riskScore"))
        except Exception:
            score = "N/A"

        rating = nri.get(
            "riskRating",
            "Not rated",
        )

        cards.append(
            (
                "Natural-hazard risk",
                score,
                "FEMA NRI · %s" % rating,
            )
        )

    elif j.get("latest"):
        cards.append(
            (
                "Most recent",
                fmt_date(j["latest"]),
                "Newest declaration activity",
            )
        )

    else:
        cards.append(
            (
                "Major disasters",
                format(j.get("dr", 0), ","),
                "Stafford Act DR declarations",
            )
        )

    ia = j.get("ia") or {}
    pa = j.get("pa_obl") or 0

    if ia.get("ihp", 0) > 0:
        cards.append(
            (
                "Individual Assistance",
                _money_short(ia.get("ihp", 0)),
                "%s households approved"
                % format(ia.get("app", 0), ","),
            )
        )

        if pa > 0:
            cards.append(
                (
                    "Public Assistance",
                    _money_short(pa),
                    "%s projects"
                    % format(j.get("pa_proj", 0), ","),
                )
            )

        elif j.get("latest"):
            cards.append(
                (
                    "Most recent",
                    fmt_date(j["latest"]),
                    "Newest declaration activity",
                )
            )

        else:
            cards.append(
                (
                    "Major disasters",
                    format(j.get("dr", 0), ","),
                    "Stafford Act DR declarations",
                )
            )

    elif pa > 0:
        cards.append(
            (
                "Public Assistance",
                _money_short(pa),
                "%s projects"
                % format(j.get("pa_proj", 0), ","),
            )
        )

        if j.get("latest") and nri:
            cards.append(
                (
                    "Most recent",
                    fmt_date(j["latest"]),
                    "Newest declaration activity",
                )
            )

        else:
            cards.append(
                (
                    "Major disasters",
                    format(j.get("dr", 0), ","),
                    "Stafford Act DR declarations",
                )
            )

    else:
        cards.append(
            (
                "Major disasters",
                format(j.get("dr", 0), ","),
                "Stafford Act DR declarations",
            )
        )

        cards.append(
            (
                "Emergencies",
                format(j.get("em", 0), ","),
                "Federal EM declarations",
            )
        )

    cards = cards[:4]

    return (
        '<div class="overview-grid">'
        + "".join(
            (
                '<article class="overview-card">'
                '<div class="overview-kicker">%s</div>'
                '<div>'
                '<div class="overview-value">%s</div>'
                '<div class="overview-label">%s</div>'
                '</div>'
                '</article>'
            )
            % (
                html.escape(str(kicker)),
                html.escape(str(value)),
                html.escape(str(label)),
            )
            for kicker, value, label in cards
        )
        + "</div>"
    )


# =============================================================================
# SVI / NRI SECTION
# =============================================================================

def _svi_percent(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None

    # CDC missing-value sentinel values should not render.
    if v < 0 or v > 1:
        return None

    return v * 100.0


def risk_context_html(j):
    """
    Static risk and vulnerability context.
    """
    svi = j.get("svi") or {}
    nri = j.get("nri") or {}

    if not svi and not nri:
        return ""

    e = html.escape

    cards = []

    # ---------------------------------------------------------------- SVI
    if svi:

        overall_raw = svi.get("overall")
        overall_pct = _svi_percent(overall_raw)

        if overall_pct is not None:

            try:
                overall_value = "%.4f" % float(overall_raw)
            except Exception:
                overall_value = "N/A"

            lead = (
                '<div class="svi-lead">'
                '<div>'
                '<div class="risk-score">%s</div>'
                '<div class="risk-score-label">overall SVI score</div>'
                '</div>'
                '<span class="risk-rating">%.1fth percentile</span>'
                '</div>'
                % (
                    e(overall_value),
                    overall_pct,
                )
            )

            interpretation = (
                '<p class="risk-interpret">'
                "This places the jurisdiction at approximately the %.1fth "
                "percentile nationally for overall social vulnerability. "
                "Higher SVI percentiles indicate greater relative vulnerability."
                "</p>"
                % overall_pct
            )

        else:
            lead = (
                '<div class="svi-lead">'
                '<div>'
                '<div class="risk-score">N/A</div>'
                '<div class="risk-score-label">overall SVI</div>'
                '</div>'
                '</div>'
            )

            interpretation = ""

        themes = [
            (
                "Socioeconomic status",
                svi.get("socioeconomic"),
            ),
            (
                "Household characteristics",
                svi.get("household"),
            ),
            (
                "Racial & ethnic minority status",
                svi.get("minority"),
            ),
            (
                "Housing type & transportation",
                svi.get("housingTransportation"),
            ),
        ]

        theme_rows = []

        for label, value in themes:

            pct = _svi_percent(value)

            if pct is None:
                continue

            width = max(
                0,
                min(100, pct),
            )

            theme_rows.append(
                '<div class="theme-row">'
                '<div class="theme-head">'
                '<span>%s</span>'
                '<b>%.1f</b>'
                '</div>'
                '<div class="theme-track">'
                '<span style="width:%.1f%%"></span>'
                '</div>'
                '</div>'
                % (
                    e(label),
                    pct,
                    width,
                )
            )

        cards.append(
            '<article class="risk-card">'
            '<div class="risk-kicker">CDC / ATSDR</div>'
            '<h3>Social Vulnerability Index</h3>'
            '<div class="risk-version">2022 county-level SVI</div>'
            '%s'
            '%s'
            '<div class="theme-list">%s</div>'
            '<p class="risk-source">'
            "CDC/ATSDR SVI is a percentile-based measure used to identify "
            "communities that may need additional support before, during, "
            "or after hazardous events."
            '</p>'
            '</article>'
            % (
                lead,
                interpretation,
                "".join(theme_rows),
            )
        )

    # ---------------------------------------------------------------- NRI
    if nri:

        try:
            risk_score = "%.1f" % float(
                nri.get("riskScore")
            )
        except Exception:
            risk_score = "N/A"

        risk_rating = str(
            nri.get("riskRating")
            or "Not rated"
        )

        version = str(
            nri.get("version")
            or "County-level NRI"
        )

        try:
            eal = _money_short(
                nri.get("ealValue")
            )
        except Exception:
            eal = "N/A"

        try:
            sv_score = "%.1f" % float(
                nri.get(
                    "socialVulnerabilityScore"
                )
            )
        except Exception:
            sv_score = "N/A"

        sv_rating = str(
            nri.get(
                "socialVulnerabilityRating"
            )
            or "Not rated"
        )

        try:
            res_score = "%.1f" % float(
                nri.get("resilienceScore")
            )
        except Exception:
            res_score = "N/A"

        res_rating = str(
            nri.get("resilienceRating")
            or "Not rated"
        )

        try:
            eal_score = "%.1f" % float(
                nri.get("ealScore")
            )
        except Exception:
            eal_score = "N/A"

        eal_rating = str(
            nri.get("ealRating")
            or "Not rated"
        )

        cards.append(
            '<article class="risk-card">'
            '<div class="risk-kicker">FEMA</div>'
            '<h3>National Risk Index</h3>'
            '<div class="risk-version">%s</div>'
            '<div class="nri-lead">'
            '<div>'
            '<div class="risk-score">%s</div>'
            '<div class="risk-score-label">overall risk score</div>'
            '</div>'
            '<span class="risk-rating">%s</span>'
            '</div>'
            '<div class="risk-mini-grid">'
            '<div class="risk-mini">'
            '<span>Expected annual loss</span>'
            '<b>%s</b>'
            '<small>Score %s · %s</small>'
            '</div>'
            '<div class="risk-mini">'
            '<span>NRI social vulnerability</span>'
            '<b>%s</b>'
            '<small>%s</small>'
            '</div>'
            '<div class="risk-mini">'
            '<span>Community resilience</span>'
            '<b>%s</b>'
            '<small>%s</small>'
            '</div>'
            '</div>'
            '<p class="risk-source">'
            "The FEMA National Risk Index describes relative natural-hazard "
            "risk using Expected Annual Loss, Social Vulnerability, and "
            "Community Resilience."
            '</p>'
            '</article>'
            % (
                e(version),
                e(risk_score),
                e(risk_rating),
                e(eal),
                e(eal_score),
                e(eal_rating),
                e(sv_score),
                e(sv_rating),
                e(res_score),
                e(res_rating),
            )
        )

    fips = (
        svi.get("fips")
        or nri.get("fips")
        or j.get("risk_fips")
        or ""
    )

    meta = ""

    if fips:
        meta = (
            '<div class="section-meta">'
            "County FIPS %s"
            "</div>"
            % e(str(fips))
        )

    return (
        '<section class="major-section">'
        '<div class="section-head">'
        '<div>'
        '<h2>Risk and vulnerability context</h2>'
        '<p class="section-deck">'
        "Historical declarations describe what has happened here. "
        "CDC SVI and FEMA NRI add context about community vulnerability "
        "and underlying natural-hazard risk."
        "</p>"
        "</div>"
        "%s"
        "</div>"
        '<div class="risk-grid">%s</div>'
        '<div class="risk-caution">'
        '<b>About these measures:</b> '
        "CDC/ATSDR Social Vulnerability Index and FEMA National Risk Index "
        "Social Vulnerability are separate measures built using different "
        "methods. They are shown together for context and should not be "
        "interpreted as equivalent scores."
        "</div>"
        "</section>"
        % (
            meta,
            "".join(cards),
        )
    )


# =============================================================================
# PUBLIC ASSISTANCE
# =============================================================================

def pa_breakdown_html(j):
    cats = j.get("pa_cats") or {}

    if not cats:
        return ""

    rows_data = sorted(
        (
            [
                code,
                PA_CAT_LABELS.get(
                    code,
                    "Other",
                ),
                vals[0],
                vals[1],
            ]
            for code, vals in cats.items()
        ),
        key=lambda x: -x[2],
    )

    total_obl = sum(
        r[2]
        for r in rows_data
    )

    total_proj = sum(
        r[3]
        for r in rows_data
    )

    body = "".join(
        (
            "<tr>"
            "<td>%s<span class='catcode'> (%s)</span></td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
        )
        % (
            html.escape(lbl),
            html.escape(code),
            format(proj, ","),
            _money_full(obl),
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
            _money_full(total_obl),
        )
    )

    return (
        '<section class="data-panel">'
        '<h3>Public Assistance by category</h3>'
        '<p class="pa-note">'
        "Federal share obligated to this jurisdiction under FEMA Public "
        "Assistance since 2000, grouped by damage category. Obligations may "
        "change as projects are amended or closed."
        "</p>"
        '<div class="tablewrap">'
        '<table class="pa-cat">'
        '<thead><tr>'
        "<th>Category</th>"
        "<th>Projects</th>"
        "<th>Federal share obligated</th>"
        "</tr></thead>"
        "<tbody>%s</tbody>"
        "<tfoot>%s</tfoot>"
        "</table>"
        "</div>"
        "</section>"
        % (
            body,
            foot,
        )
    )


# =============================================================================
# PA OBLIGATION TIMING
# =============================================================================

def pa_timing_html(j):
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

        rows.append(
            {
                "decl": decl,
                "first": fd,
                "last": ld,
                "obl": float(obl or 0),
                "name": meta.get(
                    str(dn),
                    "DR-" + str(dn),
                ),
            }
        )

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
            "%s "
            '<span class="ft-date">%s</span>'
            "</span>"
            '<span class="ft-val">%s</span>'
            "</div>"
            '<div class="ft-track">'
            '<span class="ft-gap" style="width:%.1f%%"></span>'
            '<span class="ft-flow" '
            'style="left:%.1f%%;width:%.1f%%"></span>'
            "</div>"
            '<div class="ft-meta">'
            "<b>%d days</b> to first federal obligation"
            "</div>"
            "</div>"
            % (
                e(r["name"]),
                e(r["decl"][:4]),
                _money_short(r["obl"]),
                gapw,
                gapw,
                floww,
                r["first"],
            )
        )

    ticks = "".join(
        '<span style="left:%.1f%%">%d yr</span>'
        % (
            yy
            * 365.0
            / scale
            * 100.0,
            yy,
        )
        for yy in range(
            1,
            years + 1,
        )
    )

    return (
        '<section class="data-panel">'
        '<h3>Recovery funding: how fast it came</h3>'
        '<p class="pa-note">'
        "For each recent disaster, amber shows the wait from declaration "
        "to the first federal obligation and teal shows the obligation "
        "period after that. Typical wait to first obligation here was about "
        "%d days. An obligation is the federal share committed to the "
        "recipient; it is not the same as a local cash disbursement."
        "</p>"
        '<div class="ft-list">%s</div>'
        '<div class="ft-axis">'
        '<span style="left:0">Declared</span>%s'
        "</div>"
        "</section>"
        % (
            med,
            "".join(bars),
            ticks,
        )
    )


# =============================================================================
# INDIVIDUAL ASSISTANCE
# =============================================================================

def ia_html(j):
    ia = j.get("ia") or {}

    if not ia:
        return ""

    if not (
        ia.get("reg")
        or ia.get("ihp")
    ):
        return ""

    e = html.escape

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
            _money_full(amt),
        )
        for lbl, amt in parts
        if amt > 0
    )

    stat = (
        '<div class="ia-stats">'
        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">valid registrations</div>'
        "</div>"
        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">households approved</div>'
        "</div>"
        '<div class="ia-stat">'
        '<div class="ia-n">%s</div>'
        '<div class="ia-l">total IHP approved</div>'
        "</div>"
        "</div>"
        % (
            format(reg, ","),
            format(app, ","),
            _money_full(ihp),
        )
    )

    table = ""

    if body:
        table = (
            '<div class="tablewrap">'
            '<table class="pa-cat">'
            '<thead><tr>'
            "<th>Assistance type</th>"
            "<th>Approved amount</th>"
            "</tr></thead>"
            "<tbody>%s</tbody>"
            "</table>"
            "</div>"
            % body
        )

    return (
        '<section class="data-panel">'
        '<h3>Individual Assistance to households</h3>'
        '<p class="pa-note">'
        "FEMA Individual Assistance records for households in this "
        "jurisdiction. IA exists only when a disaster receives an Individual "
        "Assistance designation, so many jurisdictions have no IA section. "
        "Registrations, approvals, and dollars reflect the underlying "
        "OpenFEMA/NEMIS records and may be revised."
        "</p>"
        "%s%s"
        "</section>"
        % (
            stat,
            table,
        )
    )


# =============================================================================
# HAZARD MITIGATION ASSISTANCE
# =============================================================================

def hma_html(j):
    hma = j.get("hma") or {}

    if not hma:
        return ""

    if not (
        hma.get("fed")
        or 0
    ):
        return ""

    e = html.escape

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
        hma.get("prog")
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
            "<td>%s<span class='catcode'> (%s)</span></td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
        )
        % (
            e(lbl),
            e(code),
            format(cnt, ","),
            _money_full(obl),
        )
        for lbl, code, obl, cnt in rows_data
    )

    stat = (
        '<div class="hm-stats">'
        '<div class="hm-stat">'
        '<div class="hm-n">%s</div>'
        '<div class="hm-l">federal mitigation share</div>'
        "</div>"
        '<div class="hm-stat">'
        '<div class="hm-n">%s</div>'
        '<div class="hm-l">funded projects</div>'
        "</div>"
        % (
            _money_full(total_fed),
            format(n_proj, ","),
        )
    )

    if props > 0:
        stat += (
            '<div class="hm-stat">'
            '<div class="hm-n">%s</div>'
            '<div class="hm-l">properties mitigated</div>'
            "</div>"
            % format(props, ",")
        )

    else:
        stat += (
            '<div class="hm-stat">'
            '<div class="hm-n">—</div>'
            '<div class="hm-l">properties reported</div>'
            "</div>"
        )

    stat += "</div>"

    return (
        '<section class="data-panel">'
        '<h3>Hazard mitigation investment</h3>'
        '<p class="pa-note">'
        "Federal Hazard Mitigation Assistance obligated to this "
        "jurisdiction to reduce future disaster losses. These figures "
        "represent federal mitigation investment and are separate from "
        "Public Assistance recovery funding."
        "</p>"
        "%s"
        '<div class="tablewrap">'
        '<table class="pa-cat">'
        '<thead><tr>'
        "<th>Program</th>"
        "<th>Projects</th>"
        "<th>Federal share obligated</th>"
        "</tr></thead>"
        "<tbody>%s</tbody>"
        "</table>"
        "</div>"
        "</section>"
        % (
            stat,
            body,
        )
    )


def federal_assistance_html(j):
    """
    Combine the existing IA / PA / timing / HMA sections into one modern
    page region.
    """
    parts = [
        ia_html(j),
        pa_breakdown_html(j),
        pa_timing_html(j),
        hma_html(j),
    ]

    parts = [
        p
        for p in parts
        if p
    ]

    if not parts:
        return ""

    return (
        '<section class="major-section">'
        '<div class="section-head">'
        '<div>'
        '<h2>Federal assistance and recovery</h2>'
        '<p class="section-deck">'
        "Federal assistance records show how households, public facilities, "
        "and mitigation projects have been supported following disasters "
        "affecting this jurisdiction."
        "</p>"
        "</div>"
        "</div>"
        '<div class="assistance-stack">%s</div>'
        "</section>"
        % "".join(parts)
    )


# =============================================================================
# EMBEDDED JURISDICTION MAP
# =============================================================================

def jurisdiction_map_html(j):
    if j.get("kind") not in (
        "county",
        "city",
    ):
        return ""

    st_fips = STATE_FIPS.get(
        STATE_AB,
        "",
    )

    if not st_fips:
        return ""

    e = html.escape

    target_fips = j.get(
        "risk_fips",
        "",
    )

    map_link = ""

    if target_fips:
        map_link = (
            '<a class="hero-link" '
            'href="../../map.html?county=%s">'
            "View on national map &rarr;"
            "</a>"
            % e(str(target_fips))
        )

    return (
        '<section class="major-section">'
        '<div class="section-head">'
        '<div>'
        '<h2>Disaster history</h2>'
        '<p class="section-deck">'
        "See the jurisdiction in geographic context, then review the "
        "declaration hazards and complete federal record below."
        "</p>"
        "</div>"
        "%s"
        "</div>"
        '<div class="map-shell">'
        '<div id="locmap" '
        'data-state-fips="%s" '
        'data-target-fips="%s" '
        'data-name="%s" '
        'data-st="%s" '
        'data-kind="%s"></div>'
        '<p class="locmap-cap">'
        "Highlighted: <b>%s, %s</b>"
        "</p>"
        "</div>"
        "</section>"
        % (
            map_link,
            e(st_fips),
            e(str(target_fips)),
            html.escape(
                j["name"].replace(
                    " (city)",
                    "",
                ),
                quote=True,
            ),
            e(STATE_AB),
            e(j["kind"]),
            e(j["name"]),
            e(STATE_AB),
        )
    )


def jurisdiction_map_js(map_html):
    if not map_html:
        return ""

    return (
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
        '<script src="https://unpkg.com/topojson-client@3"></script>'
        '<script src="../../county-names.js"></script>'
        '<script src="../../locality-index.js"></script>'
        "<script>"
        "(function(){"
        'var el=document.getElementById("locmap");'
        "if(!el)return;"

        "var sf=el.dataset.stateFips||'';"
        "var tf=el.dataset.targetFips||'';"
        "var sa=el.dataset.st||'';"
        "var knd=el.dataset.kind||'';"

        'var SX=["county","parish","borough","census area",'
        '"municipio","municipality","city and borough","island","district"];'

        "function norm(s){"
        "return String(s||'')"
        ".replace(/\\s*\\([^)]*\\)/g,'')"
        ".trim().toLowerCase();"
        "}"

        "function base(v){"
        "var s=norm(String(v).split(',')[0]);"
        "for(var i=0;i<SX.length;i++){"
        "if(s.endsWith(' '+SX[i])){"
        "s=s.slice(0,-(SX[i].length+1)).trim();"
        "break;"
        "}"
        "}"
        "return s;"
        "}"

        "var cnBase=base(el.dataset.name);"

        "function go(){"

        "if(!window.COUNTY_NAMES||!window.LOCALITY_INDEX){"
        "setTimeout(go,100);"
        "return;"
        "}"

        "var ul={};"

        "window.LOCALITY_INDEX.forEach(function(r){"
        "if(r[1]!==sa)return;"
        "var full=r[0].replace(/ \\(city\\)$/i,'').toLowerCase();"
        "ul[base(r[0])]=r[3];"
        "ul[full]=r[3];"
        "});"

        'fetch("https://unpkg.com/us-atlas@3/counties-10m.json")'
        ".then(function(r){return r.json();})"
        ".then(function(topo){"

        "var features=topojson.feature("
        "topo,topo.objects.counties"
        ").features;"

        "var fc={"
        'type:"FeatureCollection",'
        "features:features.filter(function(f){"
        "return String(f.id).padStart(5,'0').slice(0,2)===sf;"
        "})"
        "};"

        "var matches=fc.features.filter(function(f){"
        "var fp=String(f.id).padStart(5,'0');"
        "return base(window.COUNTY_NAMES[fp]||'')===cnBase;"
        "});"

        "var collide=matches.length>1;"

        "function isTarget(f){"
        "var fp=String(f.id).padStart(5,'0');"

        "if(tf){"
        "return fp===tf;"
        "}"

        "if(base(window.COUNTY_NAMES[fp]||'')!==cnBase){"
        "return false;"
        "}"

        "if(collide){"
        "var city=(+fp.slice(2))>=500;"
        "return (knd==='city')===city;"
        "}"

        "return true;"
        "}"

        'var map=L.map("locmap",{'
        "scrollWheelZoom:false,"
        "zoomControl:true,"
        "attributionControl:false"
        "});"

        'L.tileLayer('
        '"https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",'
        "{maxZoom:13}"
        ").addTo(map);"

        "var targetLayer=null;"

        "var ly=L.geoJson(fc,{"

        "style:function(f){"
        "if(isTarget(f)){"
        "return{"
        'fillColor:"#004c53",'
        "fillOpacity:.58,"
        'color:"#004c53",'
        "weight:2"
        "};"
        "}"

        "return{"
        'fillColor:"#d7e9ea",'
        "fillOpacity:.34,"
        'color:"#938a78",'
        "weight:1"
        "};"
        "},"

        "onEachFeature:function(f,layer){"

        "var fp=String(f.id).padStart(5,'0');"
        "var lb=window.COUNTY_NAMES[fp]||'';"
        "var nm=lb.split(',')[0].trim();"
        "var u=ul[base(nm)]||ul[nm.toLowerCase()];"

        "if(isTarget(f)){"
        "targetLayer=layer;"
        "layer.bindTooltip("
        "nm,"
        "{"
        "permanent:true,"
        'direction:"center",'
        'className:"loc-lbl",'
        "offset:[0,0]"
        "}"
        ");"
        "}"
        "else{"
        "layer.bindTooltip(nm,{sticky:true});"
        "}"

        "if(u){"
        "layer.on('click',function(){"
        "window.location.href='../../'+u;"
        "});"

        "layer.on('mouseover',function(){"
        "if(this._path)this._path.style.cursor='pointer';"
        "this.setStyle({fillOpacity:.62});"
        "});"

        "layer.on('mouseout',function(){"
        "this.setStyle({"
        "fillOpacity:(this===targetLayer)?.58:.34"
        "});"
        "});"
        "}"
        "}"

        "}).addTo(map);"

        "map.fitBounds("
        "ly.getBounds(),"
        "{padding:[15,15]}"
        ");"

        "});"
        "}"

        "go();"

        "})();"
        "</script>"
    )


# =============================================================================
# PREVIOUS OCCURRENCES / DECLARATION RECORD
# =============================================================================

def mitigation_history_html(j):
    e = html.escape

    hmp_rows = "".join(
        (
            "<tr>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
        )
        % (
            e(r.get("incidentType", "")),
            fmt_date(
                r.get(
                    "declarationDate",
                    "",
                )
            ),
            e(
                r.get(
                    "femaDeclarationString",
                    "",
                )
            ),
            e(
                r.get(
                    "declarationType",
                    "",
                )
            ),
        )
        for r in j.get("hmp", [])
    )

    hmp_data = [
        [
            "Hazard",
            "Date",
            "FEMA declaration",
            "Type",
        ]
    ] + [
        [
            r.get("incidentType", ""),
            fmt_date(
                r.get(
                    "declarationDate",
                    "",
                )
            ),
            r.get(
                "femaDeclarationString",
                "",
            ),
            r.get(
                "declarationType",
                "",
            ),
        ]
        for r in j.get("hmp", [])
    ]

    return (
        '<section class="major-section">'
        '<div class="section-head">'
        '<div>'
        '<h2>Previous occurrences for mitigation planning</h2>'
        '<p class="section-deck">'
        "A ready-to-use federal declaration history for documenting "
        "previous hazard occurrences in local hazard mitigation planning."
        "</p>"
        "</div>"
        "</div>"
        '<div class="hmp">'
        "<p>"
        "This table contains the completed-fiscal-year FEMA declaration "
        "record for %s. Copy the table or download the full declaration "
        "record below."
        "</p>"
        '<div class="tablewrap">'
        "<table>"
        "<thead><tr>"
        "<th>Hazard</th>"
        "<th>Date</th>"
        "<th>FEMA declaration</th>"
        "<th>Type</th>"
        "</tr></thead>"
        "<tbody>%s</tbody>"
        "</table>"
        "</div>"
        '<button class="copybtn" type="button" data-hmp="%s">'
        "Copy table"
        "</button>"
        "</div>"
        "</section>"
        % (
            e(j["name"]),
            hmp_rows,
            e(
                json.dumps(
                    hmp_data
                )
            ),
        )
    )


def declaration_history_html(j):
    e = html.escape

    rows = "".join(
        (
            '<tr data-t="%s">'
            '<td data-s="%s">%s</td>'
            '<td data-s="%s">%s</td>'
            "<td><span class='tag' title='%s'>%s</span></td>"
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
        for r in j.get("hmp", [])
    )

    wrap_cls = (
        "tablewrap scroll"
        if len(
            j.get(
                "hmp",
                [],
            )
        ) > 12
        else "tablewrap"
    )

    return (
        '<section class="major-section">'
        '<div class="section-head">'
        '<div>'
        '<h2>Every declaration on record</h2>'
        '<p class="section-deck">'
        "Filter or sort the completed-fiscal-year declaration record, "
        "download it as CSV, or copy a citation for this jurisdiction page."
        "</p>"
        "</div>"
        "</div>"
        '<div id="declbox">'
        '<p style="font-size:.79rem;color:#6b6357;margin:.5rem 0 .6rem">'
        '<b style="color:#004c53">DR</b> = Major disaster '
        "&middot; "
        '<b style="color:#004c53">EM</b> = Emergency '
        "&middot; "
        '<b style="color:#004c53">FM</b> = Fire management assistance'
        "</p>"
        "%s"
        '<p class="decl-count" aria-live="polite">'
        "Showing %d declarations"
        "</p>"
        '<div class="%s">'
        "<table>"
        "<thead><tr>"
        '<th class="sortable" data-k="date">Date</th>'
        '<th class="sortable" data-k="num">Number</th>'
        '<th class="sortable" data-k="text">Type</th>'
        '<th class="sortable" data-k="text">Hazard</th>'
        '<th class="sortable" data-k="text">Title</th>'
        "</tr></thead>"
        "<tbody>%s</tbody>"
        "</table>"
        "</div>"
        '<div style="display:flex;flex-wrap:wrap;gap:.6rem;margin:.8rem 0 0">'
        '<button class="copybtn csvbtn" type="button">'
        "Download CSV"
        "</button>"
        '<button class="copybtn citebtn" type="button">'
        "Cite this page"
        "</button>"
        "</div>"
        "</div>"
        "%s"
        "</section>"
        % (
            type_chips(
                j["decl"],
                j["dr"],
                j["em"],
                j["fm"],
            ),
            j["decl"],
            wrap_cls,
            rows,
            FILTER_JS,
        )
    )


# =============================================================================
# MAIN JURISDICTION PAGE
# =============================================================================

def render_page(j, others):
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

    lcfy = j.get(
        "lcfy",
        2025,
    )

    desc = (
        "%s, %s federal disaster history through FY%d, including FEMA "
        "declarations, Public Assistance, Individual Assistance where "
        "designated, mitigation investment, and county risk and vulnerability "
        "context where available."
        % (
            j["name"],
            STATE_NAME,
            lcfy,
        )
    )

    keywords = [
        j["name"],
        STATE_NAME,
        "FEMA",
        "disaster declarations",
        "hazard mitigation plan",
        "previous occurrences",
        "Public Assistance",
        "Individual Assistance",
    ]

    if j.get("svi"):
        keywords.extend(
            [
                "CDC SVI",
                "Social Vulnerability Index",
            ]
        )

    if j.get("nri"):
        keywords.extend(
            [
                "FEMA National Risk Index",
                "NRI",
            ]
        )

    ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name":
            "%s, %s disaster history and risk context"
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
            "name":
                "%s, %s"
                % (
                    j["name"],
                    STATE_NAME,
                ),
        },
        "temporalCoverage":
            "2000/%d"
            % lcfy,
        "isBasedOn":
            "https://www.fema.gov/about/openfema",
        "keywords": keywords,
    }

    # ---------------------------------------------------------------- lede

    lede = (
        "%s recorded <b>%d</b> federal disaster and emergency declarations "
        "in completed fiscal years from FY2000 through FY%d: %d major "
        "disasters, %d emergencies, and %d fire-management declarations."
        % (
            e(j["name"]),
            j["decl"],
            lcfy,
            j["dr"],
            j["em"],
            j["fm"],
        )
    )

    if j.get("hazards"):
        lede += (
            " Its most frequently declared hazard is %s."
            % e(
                j["hazards"][0][0].lower()
            )
        )

    if (
        j.get("spans")
        and len(j["spans"]) > 1
    ):
        lede += (
            " This record covers the tribal nation across %s."
            % e(
                _oxford(
                    j["spans"]
                )
            )
        )

    # ---------------------------------------------------------------- current-year note

    current_note = ""

    latest_fy = fy_of(
        j.get(
            "latest",
            "",
        )
    )

    if (
        latest_fy
        and latest_fy > lcfy
    ):
        current_note = (
            '<p class="current-note">'
            "<b>Current-year activity:</b> the most recent declaration shown "
            "on this page falls in FY%d. Headline declaration totals currently "
            "cover completed fiscal years through FY%d."
            "</p>"
            % (
                latest_fy,
                lcfy,
            )
        )

    # ---------------------------------------------------------------- map links / actions

    hero_actions = ""

    if j.get("risk_fips"):
        hero_actions = (
            '<div class="hero-actions">'
            '<a class="hero-link" '
            'href="../../map.html?county=%s">'
            "View on map &rarr;"
            "</a>"
            "</div>"
            % e(
                str(
                    j["risk_fips"]
                )
            )
        )

    # ---------------------------------------------------------------- hazard chips

    haz = "".join(
        "<li>%s <b>%d</b></li>"
        % (
            e(h),
            n,
        )
        for h, n in j.get(
            "hazards",
            [],
        )[:8]
    )

    if not haz:
        haz = "<li>None recorded</li>"

    # ---------------------------------------------------------------- sections

    risk_html = risk_context_html(j)

    map_html = jurisdiction_map_html(j)

    assistance_html = federal_assistance_html(j)

    mitigation_html = mitigation_history_html(j)

    history_html = declaration_history_html(j)

    # ---------------------------------------------------------------- downloads / citation JS

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
        for r in j.get(
            "hmp",
            [],
        )
    ]

    csv_json = json.dumps(
        csv_rows
    )

    copyjs = (
        "<script>"
        "document.addEventListener('click',function(ev){"

        "var b=ev.target.closest('.copybtn');"
        "if(!b)return;"

        "if(b.getAttribute('data-hmp')){"
        "var rows=JSON.parse(b.getAttribute('data-hmp'));"
        "var t=rows.map(function(r){return r.join('\\t');}).join('\\n');"

        "function done(){"
        "var p=b.textContent;"
        "b.textContent='Copied';"
        "setTimeout(function(){b.textContent=p;},1500);"
        "}"

        "if(navigator.clipboard&&navigator.clipboard.writeText){"
        "navigator.clipboard.writeText(t).then(done,function(){"
        "window.prompt('Copy:',t);"
        "});"
        "}"
        "else{"
        "window.prompt('Copy:',t);"
        "}"
        "return;"
        "}"

        "if(b.classList.contains('csvbtn')){"
        "var d=%s;"
        "var csv=d.map(function(r){"
        "return r.map(function(c){"
        "return '\"'+String(c).replace(/\"/g,'\"\"')+'\"';"
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

        "if(b.classList.contains('citebtn')){"
        "var today=new Date().toISOString().slice(0,10);"
        "var cite='Disaster Data. "
        "\\\"%s, %s: Disaster History and Risk Context.\\\" "
        "DisasterData.io. Accessed '+today+'. %s';"

        "function cd(){"
        "var p=b.textContent;"
        "b.textContent='Copied';"
        "setTimeout(function(){b.textContent=p;},1500);"
        "}"

        "if(navigator.clipboard&&navigator.clipboard.writeText){"
        "navigator.clipboard.writeText(cite).then(cd);"
        "}"
        "else{"
        "window.prompt('Citation:',cite);"
        "}"
        "}"

        "});"
        "</script>"
        % (
            csv_json,
            j["slug"],
            j["name"].replace(
                "'",
                "\\'",
            ),
            STATE_NAME.replace(
                "'",
                "\\'",
            ),
            canonical,
        )
    )

    mapjs = jurisdiction_map_js(
        map_html
    )

    # ---------------------------------------------------------------- other jurisdictions

    grid = "".join(
        '<a href="%s.html">%s</a>'
        % (
            o["slug"],
            e(o["name"]),
        )
        for o in others
        if o["slug"] != j["slug"]
    )

    # ---------------------------------------------------------------- final HTML

    return (
        '<!doctype html>'
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "%s"
        "<title>"
        "Disaster Data | %s, %s Disaster History, Assistance, SVI and NRI"
        "</title>"
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s">'
        '<meta property="og:title" '
        'content="%s, %s: Disaster History and Risk Context">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:type" content="website">'
        '<meta property="og:url" content="%s">'
        '<meta name="twitter:card" content="summary">'
        "%s"
        '<script type="application/ld+json">%s</script>'
        "</head>"
        "<body>"
        "%s"
        "<main>"
        '<div class="wrap">'

        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / '
        "%s"
        "</p>"

        '<section class="hero">'
        '<div class="hero-top">'
        "<div>"
        '<span class="badge %s">%s</span>'
        "<h1>%s, %s</h1>"
        "</div>"
        "%s"
        "</div>"
        '<p class="lede">%s</p>'
        "%s"
        "%s"
        "%s"
        "</section>"

        "%s"

        "%s"

        '<section class="major-section">'
        '<div class="section-head">'
        "<div>"
        "<h2>Most common hazards</h2>"
        '<p class="section-deck">'
        "Hazard categories are based on FEMA incident types in this "
        "jurisdiction's completed-fiscal-year declaration record."
        "</p>"
        "</div>"
        "</div>"
        '<ul class="haz">%s</ul>'
        "</section>"

        "%s"

        "%s"

        "%s"

        '<div style="margin:2rem 0">'
        '<a href="../%s.html">&larr; %s statewide overview</a> '
        "&middot; "
        '<a href="index.html">All %s jurisdictions</a>'
        "</div>"

        "%s"

        "<h2>Other %s jurisdictions</h2>"
        '<nav class="jgrid">%s</nav>'

        "</div>"
        "</main>"
        "%s"
        "%s"
        "%s"
        "</body>"
        "</html>"
        % (
            robots,

            e(j["name"]),
            e(STATE_NAME),

            e(desc),
            canonical,

            e(j["name"]),
            e(STATE_NAME),

            e(desc),

            canonical,

            HEAD,

            json.dumps(ld),

            header_html(),

            STATE_SLUG,
            e(STATE_NAME),
            e(j["name"]),

            e(j["kind"]),
            e(label),

            e(j["name"]),
            e(STATE_NAME),

            hero_actions,

            lede,

            current_note,

            hero_cards_html(j),

            summary_html(j),

            risk_html,

            map_html,

            haz,

            assistance_html,

            mitigation_html,

            history_html,

            STATE_SLUG,
            e(STATE_NAME),
            e(STATE_NAME),

            method_html(j),

            e(STATE_NAME),
            grid,

            footer_html(),
            copyjs,
            mapjs,
        )
    )


# =============================================================================
# STATE JURISDICTION HUB
# =============================================================================

def render_hub(js, stubs=()):
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

        rel = s["canonical_url"].replace(
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
                " &middot; full record on the %s page"
                % e(
                    s["primary_name"]
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
            '<span class="c">%d declarations%s</span>'
            "</li>"
        )
        % (
            href,
            e(name),
            e(label),
            decl,
            note,
        )
        for decl, name, label, href, note in items
    )

    phrase = kind_phrase(js)

    desc = (
        "Federal disaster declaration history, assistance, risk, and "
        "vulnerability context for every %s %s."
        % (
            STATE_NAME,
            phrase,
        )
    )

    return (
        '<!doctype html>'
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>"
        "Disaster Data | %s Disaster History by Jurisdiction"
        "</title>"
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s/states/%s/">'
        '<meta property="og:title" '
        'content="%s Disaster History by Jurisdiction">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:type" content="website">'
        '<meta name="twitter:card" content="summary">'
        "%s"
        "</head>"
        "<body>"
        "%s"
        "<main>"
        '<div class="wrap">'
        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / Jurisdictions'
        "</p>"
        "<h1>%s, by jurisdiction</h1>"
        '<p class="lede">'
        "Explore federal disaster histories for every %s %s. "
        "County-equivalent pages also include CDC Social Vulnerability Index "
        "and FEMA National Risk Index context where those datasets provide "
        "a matching FIPS record."
        "</p>"
        '<ol class="rank">%s</ol>'
        '<div style="margin:2rem 0">'
        '<a href="../%s.html">&larr; Back to %s statewide overview</a>'
        "</div>"
        "</div>"
        "</main>"
        "%s"
        "</body>"
        "</html>"
        % (
            e(STATE_NAME),

            e(desc),

            SITE,
            STATE_SLUG,

            e(STATE_NAME),

            e(desc),

            HEAD,

            header_html(),

            STATE_SLUG,
            e(STATE_NAME),

            e(STATE_NAME),

            e(STATE_NAME),
            e(phrase),

            rows,

            STATE_SLUG,
            e(STATE_NAME),

            footer_html(),
        )
    )


# =============================================================================
# TRIBAL MERGE / CANONICAL POINTERS
# =============================================================================

def build_tribal_plan(LOCALITY, NAMES):
    """
    Aggregate tribal jurisdictions that appear in multiple states.
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

        pc = smap[primary]["cls"]

        pname = NAMES.get(
            primary,
            primary,
        )

        purl = (
            "states/%s/%s.html"
            % (
                slugify(pname),
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
    e = html.escape

    canonical = (
        "%s/%s"
        % (
            SITE,
            canonical_url,
        )
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
        "%s spans %s. Its complete DisasterData.IO jurisdiction record "
        "is maintained on the %s page."
        % (
            name,
            span_txt,
            primary_name,
        )
    )

    return (
        '<!doctype html>'
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Disaster Data | %s</title>"
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s">'
        '<meta property="og:title" content="%s">'
        '<meta property="og:type" content="website">'
        "%s"
        "</head>"
        "<body>"
        "%s"
        "<main>"
        '<div class="wrap">'
        '<p class="crumb">'
        '<a href="../../index.html">Disaster Data</a> / '
        '<a href="../../states/index.html">States</a> / '
        '<a href="../%s.html">%s</a> / %s'
        "</p>"
        '<span class="badge tribal">Tribal nation</span>'
        "<h1>%s</h1>"
        '<p class="lede">'
        "%s spans %s. To keep the federal record whole rather than split "
        "across state lines, the full declaration and mitigation history "
        "is maintained on one canonical jurisdiction page."
        "</p>"
        '<p style="margin:1.5rem 0">'
        '<a class="copybtn" href="%s">'
        "View the full %s record on the %s page &rarr;"
        "</a>"
        "</p>"
        '<div style="margin:2rem 0">'
        '<a href="index.html">&larr; All %s jurisdictions</a>'
        "</div>"
        "</div>"
        "</main>"
        "%s"
        "</body>"
        "</html>"
        % (
            e(name),

            e(desc),

            canonical,

            e(name),

            HEAD,

            header_html(),

            STATE_SLUG,
            e(STATE_NAME),
            e(name),

            e(name),

            e(name),
            e(span_txt),

            rel,
            e(name),
            e(primary_name),

            e(STATE_NAME),

            footer_html(),
        )
    )


# =============================================================================
# BUILD ONE STATE
# =============================================================================

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
):
    """
    Generate all jurisdiction pages + state jurisdiction hub.
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

    # ----------------------------------------------------------------
    # Build base jurisdiction statistics
    # ----------------------------------------------------------------

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

                stubs.append(
                    {
                        "name":
                            c["display"],

                        "slug":
                            make_slug(
                                c,
                                state_ab,
                            ),

                        "canonical_url":
                            pinfo["primary_url"],

                        "primary_name":
                            pinfo["primary_name"],

                        "spans":
                            [
                                NAMES.get(
                                    s,
                                    s,
                                )
                                for s in pinfo["states"]
                            ],

                        "label":
                            kind_label(c),

                        "decl":
                            len(
                                pinfo["all_ids"]
                            ),
                    }
                )

                continue

            en = dict(en)
            en["ids"] = pinfo["all_ids"]

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
                for s2 in pinfo["states"]
            ]

        js.append(s)

    if not js and not stubs:
        return (
            0,
            dropped,
            0,
            [],
        )

    # ----------------------------------------------------------------
    # Public Assistance
    # ----------------------------------------------------------------

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
            pa_lookup.get(key)
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

    # ----------------------------------------------------------------
    # PA timing
    # ----------------------------------------------------------------

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

        j["pa_timing"] = (
            pt_lookup.get(key)
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

    # ----------------------------------------------------------------
    # HMA
    # ----------------------------------------------------------------

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

        j["hma"] = (
            hm_lookup.get(key)
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

    # ----------------------------------------------------------------
    # IA
    # ----------------------------------------------------------------

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

        j["ia"] = (
            ia_lookup.get(key)
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

    # ----------------------------------------------------------------
    # CDC SVI / FEMA NRI
    # ----------------------------------------------------------------

    svi_matches = 0
    nri_matches = 0

    for j in js:

        risk_key = jurisdiction_risk_key(
            j,
            state_ab,
        )

        if risk_key is None:
            j["svi"] = {}
            j["nri"] = {}
            j["risk_fips"] = ""
            continue

        svi_rec = (
            svi_lookup.get(
                risk_key
            )
            or {}
        )

        nri_rec = (
            nri_lookup.get(
                risk_key
            )
            or {}
        )

        j["svi"] = svi_rec
        j["nri"] = nri_rec

        if svi_rec:
            svi_matches += 1

        if nri_rec:
            nri_matches += 1

        j["risk_fips"] = (
            svi_rec.get("fips")
            or nri_rec.get("fips")
            or ""
        )

    if js:
        print(
            "  %s risk matches: SVI %s / NRI %s across %s generated jurisdictions"
            % (
                state_ab,
                format(
                    svi_matches,
                    ",",
                ),
                format(
                    nri_matches,
                    ",",
                ),
                format(
                    len(js),
                    ",",
                ),
            )
        )

    # ----------------------------------------------------------------
    # SEO gate / page hash
    # ----------------------------------------------------------------

    for j in js:
        j["thin"] = is_thin(j)
        j["content_hash"] = _content_hash(j)

    # ----------------------------------------------------------------
    # De-duplicate slugs
    # ----------------------------------------------------------------

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

    # ----------------------------------------------------------------
    # Write state output
    # ----------------------------------------------------------------

    os.makedirs(
        OUT_DIR,
        exist_ok=True,
    )

    for j in js:

        page_path = os.path.join(
            OUT_DIR,
            j["slug"] + ".html",
        )

        with open(
            page_path,
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write(
                render_page(
                    j,
                    js,
                )
            )

    for stub in stubs:

        stub_path = os.path.join(
            OUT_DIR,
            stub["slug"] + ".html",
        )

        with open(
            stub_path,
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write(
                render_stub(
                    stub["name"],
                    stub["canonical_url"],
                    stub["primary_name"],
                    stub["spans"],
                )
            )

    hub_path = os.path.join(
        OUT_DIR,
        "index.html",
    )

    with open(
        hub_path,
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            render_hub(
                js,
                stubs,
            )
        )

    return (
        len(js),
        dropped,
        len(stubs),
        js,
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("Loading jurisdiction page inputs...")

    LOCALITY, BROWSE, NAMES, PA_COUNTY = load_data()

    PA_TIMING = load_pa_timing()
    HMA = load_hma()
    IA = load_ia()

    # New jurisdiction risk / vulnerability datasets
    SVI_RAW = load_svi()
    NRI_RAW = load_nri()

    SVI_LOOKUP = build_risk_lookup(
        SVI_RAW
    )

    NRI_LOOKUP = build_risk_lookup(
        NRI_RAW
    )

    print(
        "  SVI lookup: %s normalized county-equivalent records"
        % format(
            len(SVI_LOOKUP),
            ",",
        )
    )

    print(
        "  NRI lookup: %s normalized county-equivalent records"
        % format(
            len(NRI_LOOKUP),
            ",",
        )
    )

    by_id = {
        r["femaDeclarationString"]: r
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

        kept, dropped, stubs_n, js = build_state(
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

                all_jurisdictions.append(
                    [
                        j["name"],
                        st,
                        state_name,
                        "states/%s/%s.html"
                        % (
                            state_slug,
                            j["slug"],
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
                    ]
                )

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

    # =========================================================================
    # FULL NATIONAL RUN: locality-index + sitemap
    # =========================================================================

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
                separators=(",", ":"),
            )
            + ";"
        )

        with open(
            idx_path,
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write(
                idx_js
            )

        # ---------------------------------------------------------------------
        # Sitemap
        # ---------------------------------------------------------------------

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
                datetime.date
                .today()
                .isoformat()
            )

            new_state = {}

            entries = []
            hub_lastmods = {}

            skipped_thin = 0

            for j in all_jurisdictions:

                url = (
                    "%s/%s"
                    % (
                        SITE,
                        j[3],
                    )
                )

                thin = (
                    bool(j[7])
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

                if (
                    prev
                    and prev.get("hash") == chash
                ):
                    lastmod = prev.get(
                        "lastmod",
                        today,
                    )

                else:
                    lastmod = today

                new_state[url] = {
                    "hash": chash,
                    "lastmod": lastmod,
                }

                hub_url = (
                    "%s/%s/"
                    % (
                        SITE,
                        "/".join(
                            j[3].split("/")[:2]
                        ),
                    )
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

            for hub_url, lastmod in hub_lastmods.items():

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
                )
                % (
                    u,
                    lm,
                )
                for u, lm in entries
            )

            sm = open(
                sitemap_path,
                encoding="utf-8",
            ).read()

            # Remove jurisdiction/hub URLs from previous run so this remains
            # idempotent. State overview pages such as /states/virginia.html
            # are not matched.
            sm = re.sub(
                (
                    r"<url>\s*<loc>"
                    + re.escape(SITE)
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

            with open(
                sitemap_path,
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(sm)

            with open(
                state_path,
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(
                    new_state,
                    fh,
                    separators=(",", ":"),
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
                len(idx_js) // 1024,
            )
        )


if __name__ == "__main__":
    main()