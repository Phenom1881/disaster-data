#!/usr/bin/env python3
"""
gen_jurisdiction_pages.py  --  Disaster Data per-jurisdiction pages (Virginia pilot).

Reads LOCALITY_DATA + BROWSE from data.js and writes one crawlable page per
Virginia jurisdiction (counties, independent cities, and tribal areas), plus a
hub, into states/virginia/. Joins each jurisdiction's declaration IDs back to
BROWSE for full per-declaration detail, and emits an HMP "previous occurrences"
table for each one.

Pilot is scoped to one state (STATE_AB below) but written to generalize.
"""

import os, re, json, html, datetime, hashlib
from dd_classify import classify

SITE = "https://www.disasterdata.io"
OUT_ROOT = os.environ.get("DD_OUT", ".")
SRC_ROOT = os.environ.get("DD_SRC", OUT_ROOT)
STATE_AB = os.environ.get("DD_STATE", "VA").upper()
STATE_NAME = STATE_AB        # resolved from data in main()
STATE_SLUG = STATE_AB.lower()  # resolved from data in main()
OUT_DIR = os.path.join(OUT_ROOT, "states", STATE_SLUG)  # recomputed in main()

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
    return _grab_js(t, "LOCALITY_DATA"), _grab_js(t, "BROWSE"), _grab_js(t, "STATE_NAMES"), pa_county

# ---------------------------------------------------------------- helpers
def fy_of(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return y + 1 if m >= 10 else y

def fmt_date(iso):
    try:
        return datetime.datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d, %Y")
    except Exception:
        return iso

def pretty_title(t):
    t = (t or "").strip()
    return t.title() if t.isupper() else t

def slugify(s):
    s = s.lower().replace("&", "and").replace(".", "").replace(",", "")
    s = re.sub(r"[^\w\s/-]", "", s)
    s = re.sub(r"[\s/]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)

TYPE_LONG = {"DR": "Major disaster", "EM": "Emergency", "FM": "Fire management"}

# Client-side filter + column sort (scoped to #declbox so other tables are untouched).
FILTER_JS = """<script>
(function(){
  var box=document.getElementById('declbox'); if(!box) return;
  var cap=box.querySelector('.decl-count');
  var chips=box.querySelectorAll('.decl-chip');
  var table=box.querySelector('table');
  var tbody=table.querySelector('tbody');
  var heads=table.querySelectorAll('thead th');
  var rows=Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  var label={ALL:'declarations',DR:'major disaster declarations',EM:'emergency declarations',FM:'fire-management declarations'};

  function filter(t){
    var shown=0,i;
    for(i=0;i<rows.length;i++){
      var m=(t==='ALL'||rows[i].getAttribute('data-t')===t);
      rows[i].classList.toggle('hide',!m);
      if(m) shown++;
    }
    for(i=0;i<chips.length;i++) chips[i].setAttribute('aria-pressed', chips[i].getAttribute('data-t')===t?'true':'false');
    if(cap) cap.textContent='Showing '+shown+' '+(label[t]||'declarations');
  }
  box.addEventListener('click',function(ev){
    var c=ev.target.closest('.decl-chip'); if(!c||c.classList.contains('off')) return;
    filter(c.getAttribute('data-t'));
  });

  function val(row,i,k){
    var td=row.children[i];
    if(k==='num'){ var v=td.getAttribute('data-s'); return v==null?0:(parseFloat(v)||0); }
    if(k==='date'){ return td.getAttribute('data-s')||''; }
    return (td.textContent||'').trim().toLowerCase();
  }
  function sortCol(i,k,dir){
    var mul=dir==='descending'?-1:1;
    rows.sort(function(a,b){
      var x=val(a,i,k), y=val(b,i,k);
      if(k==='num') return (x-y)*mul;
      return (x<y?-1:x>y?1:0)*mul;
    });
    for(var n=0;n<rows.length;n++) tbody.appendChild(rows[n]);
  }
  for(var h=0;h<heads.length;h++){ (function(th,i){
    if(!th.classList.contains('sortable')) return;
    th.addEventListener('click',function(){
      var dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';
      for(var k=0;k<heads.length;k++) heads[k].removeAttribute('aria-sort');
      th.setAttribute('aria-sort',dir);
      sortCol(i, th.getAttribute('data-k')||'text', dir);
    });
  })(heads[h],h); }

  filter('ALL');
})();
</script>"""

def type_chips(total, dr, em, fm):
    """Filter chips with baked-in counts. Zero-count types render disabled."""
    def chip(t, n, pressed=False):
        off = "" if n else " off"
        pr = "true" if pressed else "false"
        return ('<button type="button" class="decl-chip%s" data-t="%s" aria-pressed="%s">%s '
                '<span class="n">%d</span></button>' % (off, t, pr, t if t != "ALL" else "All", n))
    return ('<div class="decl-filters" role="group" aria-label="Filter declarations by type">'
            + chip("ALL", total, True) + chip("DR", dr) + chip("EM", em) + chip("FM", fm)
            + '</div>')

def decl_num(s):
    """Sortable integer inside a FEMA declaration string, e.g. DR-4644-VA -> 4644."""
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else "0"

# FEMA Public Assistance damage-category codes (sentence case, dash-free).
# Shared by the per-jurisdiction PA card and the PA category breakdown table.
PA_CAT_LABELS = {
    "A": "Debris removal", "B": "Emergency protective measures",
    "C": "Roads and bridges", "D": "Water control facilities",
    "E": "Buildings and equipment", "F": "Utilities",
    "G": "Parks and recreation", "Z": "Management costs",
}

# County-equivalent suffixes, longest-first so "City and Borough" is not read as "Borough".
_PA_COUNTY_SUFFIXES = ["City and Borough", "Census Area", "County", "Parish",
                       "Borough", "Municipio", "Municipality", "Island", "District"]

def pa_base_kind(name):
    """Normalize a place name to (base, kind) for PA matching. kind is
    'county', 'city', or 'other'. This keeps an independent city and a like-named
    county in separate buckets: the PA county field lists Virginia's independent
    cities as 'Lynchburg, City of', and VA has Fairfax, Franklin, Richmond, and
    Roanoke as BOTH a county and a city, so a name-only match would cross them."""
    low = name.strip().lower()
    for suf in _PA_COUNTY_SUFFIXES:
        s = " " + suf.lower()
        if low.endswith(s):
            return low[:-len(s)].strip(), "county"
    m = re.match(r"^(.*),\s*city of$", low) or re.match(r"^city of\s+(.+)$", low)
    if m:
        return m.group(1).strip(), "city"
    return low, "other"

STATE_FIPS = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09","DE":"10",
    "DC":"11","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17","IN":"18","IA":"19",
    "KS":"20","KY":"21","LA":"22","ME":"23","MD":"24","MA":"25","MI":"26","MN":"27",
    "MS":"28","MO":"29","MT":"30","NE":"31","NV":"32","NH":"33","NJ":"34","NM":"35",
    "NY":"36","NC":"37","ND":"38","OH":"39","OK":"40","OR":"41","PA":"42","RI":"44",
    "SC":"45","SD":"46","TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53",
    "WV":"54","WI":"55","WY":"56","AS":"60","GU":"66","MP":"69","PR":"72","VI":"78",
}

def make_slug(c, state_ab):
    """State-qualified, type-aware slug. county->tazewell-county-va,
    orleans-parish-la, utuado-municipio-pr, st-croix-island-vi;
    city->alexandria-city-va; tribal->pamunkey-indian-reservation-va."""
    st = "-" + state_ab.lower()
    if c["kind"] == "county":
        base = slugify(c["base"]); noun = slugify(c["noun"])
        return (base if base.endswith("-" + noun) or base == noun else base + "-" + noun) + st
    if c["kind"] == "city":
        return slugify(c["base"]) + "-city" + st
    return slugify(c["base"]) + st

def kind_label(c):
    if c["kind"] == "county":
        return c["noun"]            # County / Parish / Borough / Municipio / Island / District ...
    if c["kind"] == "city":
        return "Independent city"
    return "Tribal nation"

def kind_phrase(js):
    """Adaptive 'every Louisiana parish' / 'every Virginia county, independent city,
    and tribal nation' phrase from the kinds actually present."""
    cnouns = sorted({j["noun"] for j in js if j["kind"] == "county"})
    parts = []
    if cnouns:
        parts.append(cnouns[0].lower() if len(cnouns) == 1 else "county or county-equivalent")
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
    avail = max((r.get("fyDeclared", 0) for r in browse), default=cur)
    return min(cur - 1, avail)

# ---------------------------------------------------------------- gating and freshness
# A jurisdiction is treated as "thin" (noindex, and left out of the sitemap) when its
# only federal disaster history is the nationwide declarations that reached nearly every
# county, and it never received federal Public Assistance money. Raw declaration count is
# a poor gate because the COVID-19 pandemic was declared for essentially every
# jurisdiction, so a place with one COVID line and nothing else is not substantive on its
# own. Pages that clear the gate are indexed normally; thin pages stay reachable by users
# and by crawlers (robots noindex,follow) but are not advertised in the sitemap, which
# concentrates crawl budget on the pages that carry real, distinguishing data.
MIN_DISTINCT_DECLS = 2   # non-nationwide declarations needed to index on count alone

def _is_nationwide(rec):
    """True for declarations that reached nearly every jurisdiction and so do not
    distinguish this place (currently the COVID-19 pandemic declarations)."""
    title = (rec.get("declarationTitle") or "").upper()
    return "COVID" in title or "PANDEMIC" in title

def is_thin(j):
    """Thin only if the jurisdiction has no federal PA money AND fewer than
    MIN_DISTINCT_DECLS declarations that are not nationwide. Lower the threshold to 1
    to index every place that has any distinguishing declaration at all."""
    if (j.get("pa_obl") or 0) > 0:
        return False
    distinct = sum(1 for r in j.get("hmp", []) if not _is_nationwide(r))
    return distinct < MIN_DISTINCT_DECLS

def _content_hash(j):
    """Stable fingerprint of everything that renders on a jurisdiction page, so the
    sitemap lastmod only advances when this jurisdiction's data actually changes and
    not on every weekly rebuild."""
    payload = {
        "decl": j.get("decl", 0), "dr": j.get("dr", 0),
        "em": j.get("em", 0), "fm": j.get("fm", 0), "latest": j.get("latest", ""),
        "pa_obl": j.get("pa_obl", 0), "pa_proj": j.get("pa_proj", 0),
        "pa_cats": j.get("pa_cats", {}),
        "recs": sorted(
            [r.get("femaDeclarationString", ""), r.get("declarationDate", "")[:10],
             r.get("declarationType", ""), r.get("incidentType", ""),
             pretty_title(r.get("declarationTitle", ""))]
            for r in j.get("hmp", [])),
    }
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

# ---------------------------------------------------------------- per-jurisdiction stats
def juris_stats(entry, state_ab, c, by_id, lcfy):
    disp, slug, kind = c["display"], make_slug(c, state_ab), c["kind"]
    recs = [by_id[i] for i in entry.get("ids", []) if i in by_id]
    complete = [r for r in recs if r.get("fyDeclared", 9999) <= lcfy]
    by_type = {"DR": 0, "EM": 0, "FM": 0}
    haz = {}
    for r in complete:
        t = r.get("declarationType", "")
        by_type[t] = by_type.get(t, 0) + 1
        h = r.get("incidentType", "")
        haz[h] = haz.get(h, 0) + 1
    recent = sorted(recs, key=lambda r: r.get("declarationDate", ""), reverse=True)
    latest = recent[0].get("declarationDate", "")[:10] if recent else entry.get("l", "")
    return {
        "name": disp, "slug": slug, "kind": kind, "noun": c["noun"], "label": kind_label(c),
        "decl": len(complete), "dr": by_type["DR"], "em": by_type["EM"], "fm": by_type["FM"],
        "days": entry.get("a", 0),
        "hazards": sorted(haz.items(), key=lambda kv: -kv[1]),
        "recent": recent[:40],
        "hmp": sorted(complete, key=lambda r: r.get("declarationDate", ""), reverse=True),
        "latest": latest,
    }

# ---------------------------------------------------------------- CSS (matches state pages)
CSS = """
:root{--teal:#004c53;--cream:#f6f1e7;--paper:#fffdf7;--ink:#2b2b2b;--ink3:#6b6357;--rule:#e4dccb}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--ink);font-family:'Public Sans',system-ui,-apple-system,sans-serif;line-height:1.6}
a{color:var(--teal)}
.wrap{max-width:980px;margin:0 auto;padding:0 clamp(18px,4vw,40px)}
main{padding:2rem 0 1rem}
.crumb{font-size:.82rem;color:var(--ink3);margin:0 0 1rem}.crumb a{text-decoration:none}
.badge{display:inline-block;font:600 .72rem 'Public Sans',sans-serif;text-transform:uppercase;letter-spacing:.04em;padding:.2rem .6rem;border-radius:999px;margin-bottom:.6rem}
.badge.county{color:#004c53;background:#d7e9ea}.badge.city{color:#8a5a2b;background:#f3e4d2}.badge.tribal{color:#6a2f6a;background:#efddef}
h1{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:clamp(1.7rem,4vw,2.5rem);line-height:1.1;margin:.2rem 0 .6rem}
h2{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:1.3rem;margin:2.2rem 0 .8rem}
.lede{font-size:1.08rem;max-width:62ch}
.jsummary{margin:1.1rem 0 .4rem}.jsummary p{margin:0;font-size:1rem;color:var(--ink);max-width:66ch}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:.7rem;margin:1.5rem 0}
.stat{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:.85rem 1rem}
.stat .n{font-family:'Fraunces',Georgia,serif;font-size:1.7rem;color:var(--teal);font-weight:600;line-height:1}
.stat .l{font-size:.78rem;color:var(--ink3);margin-top:.3rem}
ul.haz{list-style:none;padding:0;margin:.5rem 0;display:flex;flex-wrap:wrap;gap:.5rem}
ul.haz li{background:var(--paper);border:1px solid var(--rule);border-radius:999px;padding:.3rem .8rem;font-size:.85rem}ul.haz b{color:var(--teal)}
.tablewrap{overflow-x:auto;border:1px solid var(--rule);border-radius:12px;background:var(--paper)}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:560px}
th,td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.03em;color:var(--ink3);background:#faf6ec}
tr:last-child td{border-bottom:none}.tag{font-weight:700;color:var(--teal)}
.hmp{background:#eef4f4;border:1px solid #cfe0e0;border-radius:12px;padding:1.1rem 1.3rem;margin:1rem 0}
.hmp p{margin:.2rem 0 .9rem;font-size:.92rem}
.copybtn{font:600 .8rem 'Public Sans',sans-serif;color:#004c53;background:none;border:1px solid #004c53;border-radius:8px;padding:.4rem .85rem;cursor:pointer;margin-top:.8rem}
.decl-filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:.2rem 0 .5rem}
.decl-chip{font:700 .82rem/1 'Public Sans',sans-serif;color:var(--teal);background:var(--paper);border:1px solid var(--rule);border-radius:999px;padding:.42rem .72rem;cursor:pointer;display:inline-flex;align-items:center;gap:.42rem}
.decl-chip .n{background:#eef3f2;border-radius:999px;padding:.06rem .44rem;font-size:.76rem;font-weight:700}
.decl-chip[aria-pressed="true"]{background:var(--teal);color:#fff;border-color:var(--teal)}
.decl-chip[aria-pressed="true"] .n{background:rgba(255,255,255,.22);color:#fff}
.decl-chip.off{opacity:.42;cursor:default}
.decl-count{font-size:.82rem;color:var(--ink3);margin:.05rem 0 .55rem}
.tablewrap.scroll{max-height:430px;overflow-y:auto}
.tablewrap.scroll thead th{position:sticky;top:0;z-index:1}
tr.hide{display:none}
th.sortable{cursor:pointer;user-select:none;-webkit-user-select:none;white-space:nowrap}
th.sortable::after{content:"↕";opacity:.32;margin-left:.35em;font-weight:400}
th.sortable:hover{color:var(--teal)}
th[aria-sort="ascending"]::after{content:"↑";opacity:.95}
th[aria-sort="descending"]::after{content:"↓";opacity:.95}
.method{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:1.2rem 1.4rem;margin:2rem 0;font-size:.92rem}.method h2{margin-top:0;font-size:1.1rem}
.pa-note{font-size:.9rem;color:var(--ink3);max-width:64ch;margin:.4rem 0 .8rem}
table.pa-cat tfoot td{font-weight:700;color:var(--teal);border-top:2px solid var(--rule);background:#faf6ec}
.pa-cat .catcode{color:var(--ink3);font-weight:400;font-size:.85em;margin-left:.15em}
table.pa-cat td:nth-child(2),table.pa-cat th:nth-child(2),table.pa-cat td:nth-child(3),table.pa-cat th:nth-child(3){text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.jgrid{display:flex;flex-wrap:wrap;gap:.4rem .7rem;margin:.6rem 0}.jgrid a{font-size:.86rem;text-decoration:none}
ol.rank{padding-left:0;list-style:none;counter-reset:r}
ol.rank li{counter-increment:r;display:flex;align-items:baseline;gap:.7rem;padding:.45rem 0;border-bottom:1px solid var(--rule)}
ol.rank li::before{content:counter(r);font-family:'Fraunces',serif;color:var(--ink3);min-width:2.6ch;text-align:right}
ol.rank a{text-decoration:none;font-weight:600}ol.rank .k{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3)}
ol.rank .c{color:var(--ink3);font-size:.9rem;margin-left:auto}
footer.site{border-top:1px solid var(--rule);margin-top:2rem;padding:1.5rem 0;color:var(--ink3);font-size:.85rem}footer.site a{color:var(--ink3)}
""".strip()

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
         '9..144,500;9..144,600&family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">')
HEAD = (FONTS + '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
        "<style>" + CSS +
        "#locmap{height:320px;border-radius:10px;border:1px solid #e4dccb;margin:1rem 0 .5rem;background:#f6f1e7}"
        "@media(max-width:600px){#locmap{height:240px}}"
        ".locmap-cap{font:600 .86rem/1.3 'Public Sans',sans-serif;color:#004c53;margin:0 0 1.5rem;text-align:center}"
        ".locmap-cap b{font-weight:700}"
        ".loc-lbl{background:transparent;border:none;box-shadow:none;color:#fff;font:700 12px/1 'Public Sans',sans-serif;padding:0;white-space:nowrap;pointer-events:none;text-shadow:0 1px 2px rgba(0,0,0,.6),0 0 3px rgba(0,0,0,.55)}"
        ".loc-lbl:before,.loc-lbl:after{display:none !important}"
        "</style>")

# paths are two levels deep: states/virginia/<slug>.html -> site root is ../../
def header_html():
    # The header lives in exactly one place: /nav.js at the site root.
    # Never put nav markup here. Edit nav.js to change the bar sitewide.
    return '<script src="/nav.js"></script>'


def footer_html():
    return ('<footer class="site"><div class="wrap">Disaster Data &middot; built from FEMA OpenFEMA, '
            'refreshed weekly &middot; <a href="https://forms.gle/NZ6bSadoXrKYHjjH8" target="_blank" rel="noopener">Report a data issue</a>'
            ' &middot; <a href="../../about.html">About and contact</a></div></footer>'
            '<!-- Cloudflare Web Analytics --><script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            'data-cf-beacon=\'{"token": "ceea2416f66a424981ba37fcb9440d68"}\'></script>'
            '<!-- End Cloudflare Web Analytics -->')

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
        "county": "This page counts declarations that named this jurisdiction as a designated area.",
        "city": "Independent cities are counted separately from the counties around them, matching how FEMA designates them.",
        "tribal": ("Tribal areas are counted as their own jurisdictions, separate from the counties they sit within."
                   + (" Because this nation's lands cross state lines, the declarations FEMA recorded for it in "
                      "each state are combined here so its record is not split across pages." if spans else "")),
    }[kind]
    return ('<section class="method"><h2>How these numbers are built</h2>'
            '<p>Drawn from FEMA\'s OpenFEMA Disaster Declarations Summaries, rebuilt each week. '
            'A declaration is counted here once for each designated area it names, so a single '
            'disaster covering many localities is counted in each one. For that reason these '
            f'jurisdiction counts do not sum to {STATE_NAME}\'s statewide total. ' + extra +
            ' Totals cover complete fiscal years (Oct 1 to Sep 30); the in-progress year may '
            'appear in the most-recent list but is not counted in the totals. Uses OpenFEMA data '
            'but is not endorsed by or affiliated with FEMA.</p></section>')

# ---------------------------------------------------------------- PA category breakdown
def pa_breakdown_html(j):
    """Per-jurisdiction Public Assistance category table. Returns "" when there is
    no PA match, or when data.js predates the breakdown (3-element PA entries)."""
    cats = j.get("pa_cats") or {}
    if not cats:
        return ""
    rows_data = sorted(
        ([code, PA_CAT_LABELS.get(code, "Other"), vals[0], vals[1]]
         for code, vals in cats.items()),
        key=lambda x: -x[2])
    total_obl  = sum(r[2] for r in rows_data)
    total_proj = sum(r[3] for r in rows_data)
    money = lambda n: "$" + format(int(round(n)), ",")
    body = "".join(
        "<tr><td>%s<span class='catcode'>(%s)</span></td><td>%s</td><td>%s</td></tr>"
        % (html.escape(lbl), html.escape(code), format(proj, ","), money(obl))
        for code, lbl, obl, proj in rows_data)
    foot = ("<tr><td>All categories</td><td>%s</td><td>%s</td></tr>"
            % (format(total_proj, ","), money(total_obl)))
    return ('<section><h2>Federal Public Assistance by category</h2>'
            '<p class="pa-note">Federal share obligated to this jurisdiction under FEMA Public '
            'Assistance since 2000, grouped by damage category. Figures are rounded to the nearest '
            'dollar and reflect obligations, which may change as projects close out.</p>'
            '<div class="tablewrap"><table class="pa-cat"><thead><tr>'
            '<th>Category</th><th>Projects</th><th>Federal share obligated</th></tr></thead>'
            '<tbody>%s</tbody><tfoot>%s</tfoot></table></div></section>'
            % (body, foot))

# ---------------------------------------------------------------- data-driven prose
def _money_words(n):
    """Public Assistance dollars in words, dash-free, for the summary paragraph."""
    n = float(n or 0)
    if n >= 1e9:
        return "about $%.1f billion" % (n / 1e9)
    if n >= 1e6:
        return "about $%.1f million" % (n / 1e6)
    return "$" + format(int(round(n)), ",")

def summary_html(j):
    """A short, plain-language paragraph built entirely from this jurisdiction's own
    records. It gives the page substantive, unique text beyond the tables so search
    engines have a reason to index it, and gives readers the record in prose."""
    hmp = j.get("hmp", [])
    if not hmp:
        return ""
    e = html.escape
    name = e(j["name"])
    dates = sorted(r.get("declarationDate", "")[:10] for r in hmp if r.get("declarationDate"))
    if dates and dates[0][:4] != dates[-1][:4]:
        span = "between %s and %s" % (dates[0][:4], dates[-1][:4])
    elif dates:
        span = "in %s" % dates[0][:4]
    else:
        span = "since FY2000"
    sents = ["The federal disaster record for %s runs %s, covering %d declaration%s in all."
             % (name, span, j["decl"], "" if j["decl"] == 1 else "s")]

    drs = [r for r in hmp if r.get("declarationType") == "DR"]
    if drs:
        title = pretty_title(drs[0].get("declarationTitle", "")).strip()
        yr = drs[0].get("declarationDate", "")[:4]
        if title and yr:
            sents.append("Its most recent major disaster declaration was %s in %s." % (e(title), yr))

    hz = j.get("hazards") or []
    if len(hz) >= 2:
        sents.append("The hazards behind these declarations were most often %s."
                     % _oxford([e(h.lower()) for h, _ in hz[:3]]))
    elif len(hz) == 1:
        sents.append("Every one was tied to %s." % e(hz[0][0].lower()))

    if (j.get("pa_obl") or 0) > 0:
        tail = (", most of it for %s" % e(j["pa_top_cat"].lower())) if j.get("pa_top_cat") else ""
        sents.append("Since 2000, FEMA has obligated %s in Public Assistance funding to the jurisdiction%s."
                     % (_money_words(j["pa_obl"]), tail))

    return '<section class="jsummary"><p>%s</p></section>' % " ".join(sents)

# ---------------------------------------------------------------- jurisdiction page
def render_page(j, others):
    e = html.escape
    canonical = "%s/states/%s/%s.html" % (SITE, STATE_SLUG, j["slug"])
    label = j["label"]
    robots = '<meta name="robots" content="noindex,follow">' if j.get("thin") else ''
    desc = ("%s, %s has had %d federal disaster and emergency declarations since FY2000 "
            "(%d major disasters, %d emergencies, %d fire-management). Full FEMA declaration "
            "history and a ready-to-use previous-occurrences table for hazard mitigation planning."
            % (j["name"], STATE_NAME, j["decl"], j["dr"], j["em"], j["fm"]))
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": "%s, %s FEMA disaster declarations" % (j["name"], STATE_NAME),
          "description": desc, "url": canonical, "isAccessibleForFree": True,
          "creator": {"@type": "Organization", "name": "Disaster Data", "url": SITE},
          "spatialCoverage": {"@type": "Place", "name": "%s, %s" % (j["name"], STATE_NAME)},
          "temporalCoverage": "2000/2025", "isBasedOn": "https://www.fema.gov/about/openfema",
          "keywords": [j["name"], STATE_NAME, "FEMA", "disaster declarations",
                       "hazard mitigation plan", "previous occurrences"]}

    cards = [("%d" % j["decl"], "Declarations since FY2000"),
             ("%d" % j["dr"], "Major disasters (DR)"),
             ("%d" % j["em"], "Emergencies (EM)"),
             ("%d" % j["fm"], "Fire management (FM)")]
    if j["latest"]:
        try:
            mr = datetime.datetime.strptime(j["latest"], "%Y-%m-%d").strftime("%b&nbsp;%Y")
        except Exception:
            mr = j["latest"]
        cards.append((mr, "Most recent"))
    if j.get("pa_obl") and j["pa_obl"] > 0:
        obl = j["pa_obl"]
        if obl >= 1e9:
            pa_fmt = "$%.1fB" % (obl / 1e9)
        elif obl >= 1e6:
            pa_fmt = "$%.1fM" % (obl / 1e6)
        elif obl >= 1e3:
            pa_fmt = "$%.0fK" % (obl / 1e3)
        else:
            pa_fmt = "$%d" % obl
        pa_label = "Federal PA obligated"
        if j.get("pa_top_cat"):
            pa_label += " (top: %s)" % j["pa_top_cat"].lower()
        cards.append((pa_fmt, pa_label))
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % c for c in cards)

    # embedded state map (county-level, only for county/city kinds with a FIPS match)
    st_fips = STATE_FIPS.get(STATE_AB, "")
    if j["kind"] in ("county", "city") and st_fips:
        map_html = ('<div id="locmap" data-fips="%s" data-name="%s" data-st="%s" data-kind="%s"></div>'
                    '<p class="locmap-cap">Highlighted: <b>%s, %s</b></p>') % (
            st_fips, html.escape(j["name"].replace(" (city)", ""), quote=True), STATE_AB, j["kind"],
            html.escape(j["name"], quote=True), STATE_AB)
    else:
        map_html = ""

    haz = "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in j["hazards"][:8]) or '<li>None recorded</li>'

    # Full declaration record (complete fiscal years), most recent first. Row carries its
    # type in data-t so the filter can show or hide it client-side.
    rows = "".join("<tr data-t=\"%s\"><td data-s=\"%s\">%s</td><td data-s=\"%s\">%s</td><td><span class='tag' title='%s'>%s</span></td><td>%s</td><td>%s</td></tr>"
                   % (e(r.get("declarationType", "")),
                      e(r.get("declarationDate", "")[:10]), fmt_date(r.get("declarationDate", "")),
                      decl_num(r.get("femaDeclarationString", "")), e(r.get("femaDeclarationString", "")),
                      TYPE_LONG.get(r.get("declarationType", ""), ""), e(r.get("declarationType", "")),
                      e(r.get("incidentType", "")), e(pretty_title(r.get("declarationTitle", ""))))
                   for r in j["hmp"])
    # Scroll once the list gets long; short records stay a plain table.
    wrap_cls = "tablewrap scroll" if len(j["hmp"]) > 12 else "tablewrap"
    history = ('<div id="declbox">'
               '<p class="legend" style="font-size:.82rem;color:#6b6357;margin:.5rem 0 .6rem">'
               '<b style="color:#004c53">DR</b> = Major disaster (Stafford Act) &middot; '
               '<b style="color:#004c53">EM</b> = Emergency declaration &middot; '
               '<b style="color:#004c53">FM</b> = Fire management assistance</p>'
               + type_chips(j["decl"], j["dr"], j["em"], j["fm"]) +
               '<p class="decl-count" aria-live="polite">Showing %d declarations</p>' % j["decl"] +
               '<div class="' + wrap_cls + '"><table><thead><tr>'
               '<th class="sortable" data-k="date">Date</th>'
               '<th class="sortable" data-k="num">Number</th>'
               '<th class="sortable" data-k="text">Type</th>'
               '<th class="sortable" data-k="text">Hazard</th>'
               '<th class="sortable" data-k="text">Title</th>'
               '</tr></thead><tbody>' + rows + '</tbody></table></div>'
               '<div class="export-bar" style="display:flex;flex-wrap:wrap;gap:.6rem;margin:.8rem 0 0">'
               '<button class="copybtn csvbtn" type="button">Download CSV</button>'
               '<button class="copybtn citebtn" type="button">Cite this page</button></div>'
               '</div>' + FILTER_JS)

    hmp_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                       % (e(r.get("incidentType", "")), fmt_date(r.get("declarationDate", "")),
                          e(r.get("femaDeclarationString", "")), e(r.get("declarationType", "")))
                       for r in j["hmp"])
    # structured rows for the copy button (parsed + tab-joined in JS, avoids escape issues)
    hmp_data = [["Hazard", "Date", "FEMA declaration", "Type"]] + [
        [r.get("incidentType", ""), fmt_date(r.get("declarationDate", "")),
         r.get("femaDeclarationString", ""), r.get("declarationType", "")] for r in j["hmp"]]
    hmp = ('<section><h2>Previous occurrences, for your mitigation plan</h2>'
           '<div class="hmp"><p>Every local hazard mitigation plan must document previous '
           'occurrences of each hazard. Here is that record for %s, sourced to OpenFEMA and '
           'refreshed weekly. Copy it straight into your plan.</p>'
           '<div class="tablewrap"><table><thead><tr><th>Hazard</th><th>Date</th>'
           '<th>FEMA declaration</th><th>Type</th></tr></thead><tbody>%s</tbody></table></div>'
           '<button class="copybtn" type="button" data-hmp="%s">Copy table</button></div></section>'
           % (e(j["name"]), hmp_rows, e(json.dumps(hmp_data))))

    lede = ("%s recorded <b>%d</b> federal disaster and emergency declarations since FY2000 "
            "(through FY2025): %d major disasters, %d emergencies, and %d fire-management "
            "declarations.%s" % (e(j["name"]), j["decl"], j["dr"], j["em"], j["fm"],
            (" Its most common hazard is %s." % e(j["hazards"][0][0].lower())) if j["hazards"] else ""))
    if j.get("spans") and len(j["spans"]) > 1:
        lede += " This record covers the nation across %s." % e(_oxford(j["spans"]))

    grid = "".join('<a href="%s.html">%s</a>' % (o["slug"], e(o["name"])) for o in others if o["slug"] != j["slug"])

    # CSV data for download button
    csv_rows = [["Date", "Declaration", "Type", "Hazard", "Title"]] + [
        [r.get("declarationDate", "")[:10], r.get("femaDeclarationString", ""),
         r.get("declarationType", ""), r.get("incidentType", ""),
         pretty_title(r.get("declarationTitle", ""))] for r in j["hmp"]]
    csv_json = json.dumps(csv_rows)

    copyjs = ("<script>"
              "document.addEventListener('click',function(ev){"
              "var b=ev.target.closest('.copybtn');"
              "if(!b)return;"
              # Copy HMP table
              "if(b.getAttribute('data-hmp')){"
              "var rows=JSON.parse(b.getAttribute('data-hmp'));"
              "var t=rows.map(function(r){return r.join('\\t');}).join('\\n');"
              "function done(){var p=b.textContent;b.textContent='Copied';setTimeout(function(){b.textContent=p;},1500);}"
              "if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,"
              "function(){window.prompt('Copy:',t);});}else{window.prompt('Copy:',t);}return;}"
              # Download CSV
              "if(b.classList.contains('csvbtn')){"
              "var d=%s;"
              "var csv=d.map(function(r){return r.map(function(c){return '\"'+String(c).replace(/\"/g,'\"\"')+'\"';}).join(',');}).join('\\n');"
              "var blob=new Blob([csv],{type:'text/csv'});"
              "var a=document.createElement('a');a.href=URL.createObjectURL(blob);"
              "a.download='%s-declarations.csv';a.click();URL.revokeObjectURL(a.href);return;}"
              # Cite this page
              "if(b.classList.contains('citebtn')){"
              "var today=new Date().toISOString().slice(0,10);"
              "var cite='Disaster Data. \"%s, %s: FEMA Disaster Declarations.\" DisasterData.io. Accessed '+today+'. %s';"
              "function cd(){var p=b.textContent;b.textContent='Copied';setTimeout(function(){b.textContent=p;},1500);}"
              "if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(cite).then(cd);}else{window.prompt('Citation:',cite);}}"
              "});</script>"
              % (csv_json, j["slug"],
                 j["name"].replace("'", "\\'"), STATE_NAME.replace("'", "\\'"), canonical))

    # map scripts (only when map_html is not empty)
    if map_html:
        mapjs = ('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
                 '<script src="https://unpkg.com/topojson-client@3"></script>'
                 '<script src="../../county-names.js"></script>'
                 '<script src="../../locality-index.js"></script>'
                 '<script>'
                 '(function(){'
                 'var el=document.getElementById("locmap");if(!el)return;'
                 'var sf=el.dataset.fips,sa=el.dataset.st,knd=(el.dataset.kind||"");'
                 'var SX=["county","parish","borough","census area","municipio","municipality","city and borough","island","district"];'
                 'function norm(s){return String(s||"").replace(/\\s*\\([^)]*\\)/g,"").trim().toLowerCase();}'
                 'function base(v){var s=norm(String(v).split(",")[0]);for(var i=0;i<SX.length;i++){if(s.endsWith(" "+SX[i])){s=s.slice(0,-(SX[i].length+1)).trim();break;}}return s;}'
                 'var cnBase=base(el.dataset.name);'
                 'function go(){'
                 'if(!window.COUNTY_NAMES||!window.LOCALITY_INDEX){setTimeout(go,100);return;}'
                 'var ul={};window.LOCALITY_INDEX.forEach(function(r){'
                 'if(r[1]!==sa)return;'
                 'var full=r[0].replace(/ \\(city\\)$/i,"").toLowerCase();'
                 'ul[base(r[0])]=r[3];ul[full]=r[3];'
                 '});'
                 'fetch("https://unpkg.com/us-atlas@3/counties-10m.json").then(function(r){return r.json()}).then(function(topo){'
                 'var fc={type:"FeatureCollection",features:topojson.feature(topo,topo.objects.counties).features.filter(function(f){return String(f.id).padStart(5,"0").slice(0,2)===sf})};'
                 'var matches=fc.features.filter(function(f){return base(window.COUNTY_NAMES[String(f.id).padStart(5,"0")]||"")===cnBase;});'
                 'var collide=matches.length>1;'
                 'function isTarget(f){var fp=String(f.id).padStart(5,"0");if(base(window.COUNTY_NAMES[fp]||"")!==cnBase)return false;if(collide){var city=(+fp.slice(2))>=500;return (knd==="city")===city;}return true;}'
                 'var map=L.map("locmap",{scrollWheelZoom:false,zoomControl:true,attributionControl:false});'
                 'L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",{maxZoom:13}).addTo(map);'
                 'var targetLayer=null;'
                 'var ly=L.geoJson(fc,{'
                 'style:function(f){'
                 'if(isTarget(f))return{fillColor:"#004c53",fillOpacity:.55,color:"#004c53",weight:2};'
                 'return{fillColor:"#d7e9ea",fillOpacity:.35,color:"#938a78",weight:1};'
                 '},'
                 'onEachFeature:function(f,layer){'
                 'var fp=String(f.id).padStart(5,"0"),lb=window.COUNTY_NAMES[fp]||"",nm=lb.split(",")[0].trim();'
                 'var u=ul[base(nm)]||ul[nm.toLowerCase()];'
                 'if(isTarget(f)){targetLayer=layer;layer.bindTooltip(nm,{permanent:true,direction:"center",className:"loc-lbl",offset:[0,0]});}'
                 'else{layer.bindTooltip(nm,{sticky:true});}'
                 'if(u){layer.on("click",function(){window.location.href="../../"+u});'
                 'layer.on("mouseover",function(){this._path.style.cursor="pointer";this.setStyle({fillOpacity:.6})});'
                 'layer.on("mouseout",function(){this.setStyle({fillOpacity:(this===targetLayer)?.55:.35})});}'
                 '}'
                 '}).addTo(map);'
                 'map.fitBounds(ly.getBounds(),{padding:[15,15]});'
                 '});}'
                 'go();'
                 '})();'
                 '</script>')
    else:
        mapjs = ""

    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">%s'
            f'<title>%s, {STATE_NAME} FEMA Disaster Declarations and Mitigation History</title>'
            '<meta name="description" content="%s"><link rel="canonical" href="%s">'
            f'<meta property="og:title" content="%s, {STATE_NAME}: Federal Disaster Declarations">'
            '<meta property="og:description" content="%s"><meta property="og:type" content="website">'
            '<meta property="og:url" content="%s"><meta name="twitter:card" content="summary">'
            '%s<script type="application/ld+json">%s</script></head><body>'
            '%s<main><div class="wrap">'
            '<p class="crumb"><a href="../../index.html">Disaster Data</a> / '
            '<a href="../../states/index.html">States</a> / '
            f'<a href="../{STATE_SLUG}.html">{STATE_NAME}</a> / %s</p>'
            '<span class="badge %s">%s</span>'
            f'<h1>%s, {STATE_NAME}</h1><p class="lede">%s</p>'
            '<div class="stats">%s</div>'
            '%s'
            '%s'
            '%s'
            '<h2>Most common hazards</h2><ul class="haz">%s</ul>'
            '%s'
            '<h2>Every declaration on record</h2>%s'
            f'<div style="margin:2rem 0"><a href="../{STATE_SLUG}.html">&larr; {STATE_NAME} statewide overview</a> '
            f'&middot; <a href="index.html">All {STATE_NAME} jurisdictions</a></div>'
            '%s'
            f'<h2>Other {STATE_NAME} jurisdictions</h2><nav class="jgrid">%s</nav>'
            '</div></main>%s%s%s</body></html>'
            % (robots, e(j["name"]), e(desc), canonical, e(j["name"]), e(desc), canonical,
               HEAD, json.dumps(ld), header_html(),
               e(j["name"]), j["kind"], label, e(j["name"]), lede, stats, summary_html(j), map_html,
               pa_breakdown_html(j),
               haz, hmp, history,
               method_html(j["kind"], bool(j.get("spans"))), grid, footer_html(), copyjs, mapjs))

# ---------------------------------------------------------------- hub
def render_hub(js, stubs=()):
    e = html.escape
    items = [(j["decl"], j["name"], j["label"], j["slug"] + ".html", "") for j in js]
    for s in stubs:
        rel = s["canonical_url"].replace("states/", "../", 1)   # states/<sec>/ -> ../<primary>/
        items.append((s["decl"], s["name"], s["label"], rel,
                      " &middot; full record on the %s page" % e(s["primary_name"])))
    items.sort(key=lambda it: (-it[0], it[1]))
    rows = "".join('<li><a href="%s">%s</a> <span class="k">%s</span>'
                   '<span class="c">%d declarations%s</span></li>'
                   % (href, e(name), label, decl, note)
                   for decl, name, label, href, note in items)
    phrase = kind_phrase(js)
    desc = ("Federal disaster and emergency declaration history for every %s %s since FY2000, "
            "with a ready-to-use previous-occurrences table for hazard mitigation planning."
            % (STATE_NAME, phrase))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{STATE_NAME} Disaster Declarations by Jurisdiction | Disaster Data</title>'
            f'<meta name="description" content="%s"><link rel="canonical" href="%s/states/{STATE_SLUG}/">'
            f'<meta property="og:title" content="{STATE_NAME} Disaster Declarations by Jurisdiction">'
            '<meta property="og:description" content="%s"><meta property="og:type" content="website">'
            '<meta name="twitter:card" content="summary">'
            '%s</head><body>%s<main><div class="wrap">'
            '<p class="crumb"><a href="../../index.html">Disaster Data</a> / '
            f'<a href="../../states/index.html">States</a> / <a href="../{STATE_SLUG}.html">{STATE_NAME}</a> / Jurisdictions</p>'
            f'<h1>{STATE_NAME}, by jurisdiction</h1>'
            f'<p class="lede">Every {STATE_NAME} {phrase}, ranked '
            'by federal disaster and emergency declarations since FY2000. Each page carries the full '
            'declaration history and a previous-occurrences table built for local mitigation plans.</p>'
            '<ol class="rank">%s</ol>'
            f'<div style="margin:2rem 0"><a href="../{STATE_SLUG}.html">&larr; Back to {STATE_NAME} statewide overview</a></div>'
            '</div></main>%s</body></html>'
            % (e(desc), SITE, e(desc), HEAD, header_html(), rows, footer_html()))

# ---------------------------------------------------------------- tribal merge
def build_tribal_plan(LOCALITY, NAMES):
    """Aggregate every tribal jurisdiction across the states it appears in.
    Returns plan[(state_ab, display)] -> role info. Each tribe gets ONE canonical
    page on its primary state (most declarations; ties broken by state code); the
    same tribe in other states becomes a canonical-pointer stub. Duplicate entries
    for one tribe within a single state are merged."""
    agg = {}
    for st, entries in LOCALITY.items():
        for en in entries:
            c = classify(st, en["n"])
            if not (c["kind"] == "tribal" and c["keep"]):
                continue
            d = agg.setdefault(c["display"], {}).setdefault(st, {"c": 0, "ids": set(), "cls": c})
            d["c"] += en.get("c", 0)
            d["ids"].update(en.get("ids", []))
    plan = {}
    for disp, smap in agg.items():
        primary = sorted(smap.items(), key=lambda kv: (-kv[1]["c"], kv[0]))[0][0]
        pc = smap[primary]["cls"]
        pname = NAMES.get(primary, primary)
        purl = "states/%s/%s.html" % (slugify(pname), make_slug(pc, primary))
        all_ids = sorted(set().union(*(v["ids"] for v in smap.values())))
        states = sorted(smap.keys(), key=lambda s: NAMES.get(s, s))
        for st in smap:
            plan[(st, disp)] = {
                "role": "primary" if st == primary else "secondary",
                "primary_name": pname, "primary_url": purl,
                "all_ids": all_ids, "states": states,
            }
    return plan

def render_stub(name, canonical_url, primary_name, spans):
    """Thin canonical-pointer page for a tribe whose full record lives on its
    primary state's page. rel=canonical consolidates ranking; a visible link
    sends people to the full record. No auto-redirect."""
    e = html.escape
    canonical = "%s/%s" % (SITE, canonical_url)
    rel = canonical_url.replace("states/", "../", 1)
    span_txt = _oxford(spans)
    desc = ("%s spans %s. Its full federal disaster and emergency declaration history and "
            "mitigation table are maintained on the %s page." % (name, span_txt, primary_name))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s | Disaster Data</title>'
            '<meta name="description" content="%s"><link rel="canonical" href="%s">'
            '<meta property="og:title" content="%s"><meta property="og:type" content="website">'
            '%s</head><body>%s<main><div class="wrap">'
            '<p class="crumb"><a href="../../index.html">Disaster Data</a> / '
            f'<a href="../../states/index.html">States</a> / <a href="../{STATE_SLUG}.html">{STATE_NAME}</a> / %s</p>'
            '<span class="badge tribal">Tribal nation</span>'
            '<h1>%s</h1>'
            '<p class="lede">%s spans %s. To keep its record whole rather than split across '
            'state lines, the full declaration history and previous-occurrences table live on one page.</p>'
            '<p style="margin:1.5rem 0"><a class="copybtn" href="%s">View the full %s record on the %s page &rarr;</a></p>'
            f'<div style="margin:2rem 0"><a href="index.html">&larr; All {STATE_NAME} jurisdictions</a></div>'
            '</div></main>%s</body></html>'
            % (e(name), e(desc), canonical, e(name),
               HEAD, header_html(), e(name),
               e(name), e(name), e(span_txt),
               rel, e(name), e(primary_name),
               footer_html()))

# ---------------------------------------------------------------- build
def build_state(state_ab, LOCALITY, by_id, lcfy, NAMES, pa_county, tribal_plan):
    """Generate all keep-localities + hub for one state.
    Returns (kept, dropped, stubs_written, js)."""
    global STATE_AB, STATE_NAME, STATE_SLUG, OUT_DIR
    STATE_AB = state_ab
    STATE_NAME = NAMES.get(state_ab, state_ab)
    STATE_SLUG = slugify(STATE_NAME)
    OUT_DIR = os.path.join(OUT_ROOT, "states", STATE_SLUG)

    entries = LOCALITY.get(state_ab, [])
    js = []
    stubs = []
    dropped = 0
    seen_tribal = set()
    for en in entries:
        c = classify(state_ab, en["n"])
        if not c["keep"]:
            dropped += 1
            continue
        pinfo = tribal_plan.get((state_ab, c["display"])) if c["kind"] == "tribal" else None
        if pinfo:
            if c["display"] in seen_tribal:
                continue                      # collapse duplicate entries for one tribe in this state
            seen_tribal.add(c["display"])
            if pinfo["role"] == "secondary":
                stubs.append({
                    "name": c["display"], "slug": make_slug(c, state_ab),
                    "canonical_url": pinfo["primary_url"], "primary_name": pinfo["primary_name"],
                    "spans": [NAMES.get(s, s) for s in pinfo["states"]],
                    "label": kind_label(c), "decl": len(pinfo["all_ids"]),
                })
                continue
            en = dict(en); en["ids"] = pinfo["all_ids"]   # primary: aggregate every state's records
        s = juris_stats(en, state_ab, c, by_id, lcfy)
        if pinfo and pinfo["role"] == "primary" and len(pinfo["states"]) > 1:
            s["spans"] = [NAMES.get(s2, s2) for s2 in pinfo["states"]]
        js.append(s)

    if not js and not stubs:
        return (0, dropped, 0, [])

    # match PA county data to jurisdictions, keyed by (base name, kind) so an
    # independent city and a like-named county never cross-match.
    pa_lookup = {}   # (base, kind) -> pa_val
    pa_exact  = {}   # full lowercased PA name -> pa_val (safety net for exact hits)
    for pa_name, pa_val in pa_county.items():
        pa_exact[pa_name.strip().lower()] = pa_val
        pa_lookup[pa_base_kind(pa_name)] = pa_val
    for j in js:
        if j["kind"] == "city":
            key = (j["name"].replace(" (city)", "").strip().lower(), "city")
        elif j["kind"] == "county":
            key = (pa_base_kind(j["name"])[0], "county")
        else:
            key = (j["name"].strip().lower(), "other")
        pa = pa_lookup.get(key) or pa_exact.get(j["name"].replace(" (city)", "").strip().lower())
        if pa:
            j["pa_obl"] = pa[0]
            j["pa_proj"] = pa[1]
            j["pa_top_cat"] = PA_CAT_LABELS.get(pa[2], pa[2]) if len(pa) > 2 and pa[2] else ""
            j["pa_cats"] = pa[3] if len(pa) > 3 and isinstance(pa[3], dict) else {}
        else:
            j["pa_obl"] = 0
            j["pa_proj"] = 0
            j["pa_top_cat"] = ""
            j["pa_cats"] = {}

    for j in js:
        j["thin"] = is_thin(j)
        j["content_hash"] = _content_hash(j)

    seen = {}
    for j in js:
        if j["slug"] in seen:
            j["slug"] = j["slug"] + "-2"
        seen[j["slug"]] = 1
    js.sort(key=lambda j: (-j["decl"], j["name"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    for j in js:
        open(os.path.join(OUT_DIR, j["slug"] + ".html"), "w", encoding="utf-8").write(render_page(j, js))
    for stub in stubs:
        open(os.path.join(OUT_DIR, stub["slug"] + ".html"), "w", encoding="utf-8").write(
            render_stub(stub["name"], stub["canonical_url"], stub["primary_name"], stub["spans"]))
    open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(render_hub(js, stubs))
    return (len(js), dropped, len(stubs), js)

def main():
    LOCALITY, BROWSE, NAMES, PA_COUNTY = load_data()
    by_id = {r["femaDeclarationString"]: r for r in BROWSE}
    lcfy = last_complete_fy(BROWSE)
    tribal_plan = build_tribal_plan(LOCALITY, NAMES)

    one = os.environ.get("DD_STATE")
    if one:
        targets = [one.upper()]
    else:
        # every state/territory that has at least one locality, in name order
        targets = sorted(LOCALITY.keys(), key=lambda s: NAMES.get(s, s))

    grand_pages = grand_states = grand_drop = grand_stubs = 0
    all_jurisdictions = []
    for st in targets:
        kept, dropped, stubs_n, js = build_state(st, LOCALITY, by_id, lcfy, NAMES, PA_COUNTY.get(st, {}), tribal_plan)
        grand_drop += dropped
        grand_stubs += stubs_n
        if kept or stubs_n:
            grand_states += 1
            grand_pages += kept
            state_name = NAMES.get(st, st)
            state_slug = slugify(state_name)
            for j in js:
                all_jurisdictions.append([
                    j["name"], st, state_name,
                    "states/%s/%s.html" % (state_slug, j["slug"]),
                    j["decl"], j["kind"], j["noun"],
                    j.get("thin", False), j.get("content_hash", ""),
                ])
            if one:
                print("generated %d %s jurisdiction pages + hub (+%d canonical pointers), through FY%d"
                      % (kept, STATE_NAME, stubs_n, lcfy))

    # write search/map index (used by homepage search + map click-through)
    if not one:
        idx_path = os.path.join(OUT_ROOT, "locality-index.js")
        # compact JSON array: [name, stateAB, stateName, url, declCount, kind, noun]
        # (internal rows also carry [thin, content_hash] for the sitemap; drop them here)
        idx_rows = [row[:7] for row in all_jurisdictions]
        idx_js = "window.LOCALITY_INDEX=" + json.dumps(idx_rows, separators=(",", ":")) + ";"
        open(idx_path, "w", encoding="utf-8").write(idx_js)

        # extend sitemap.xml with jurisdiction + hub URLs.
        # Thin pages (see is_thin) are left out so crawl budget goes to substantive
        # pages. Each URL carries a lastmod that only advances when that page's data
        # actually changed, tracked in sitemap-state.json across runs, so a weekly
        # rebuild that changes nothing does not reset every lastmod.
        sitemap_path = os.path.join(OUT_ROOT, "sitemap.xml")
        state_path = os.path.join(OUT_ROOT, "sitemap-state.json")
        if os.path.exists(sitemap_path):
            try:
                prev_state = json.load(open(state_path, encoding="utf-8"))
            except Exception:
                prev_state = {}
            today = datetime.date.today().isoformat()
            new_state = {}
            entries = []          # (url, lastmod) for indexed jurisdiction pages
            hub_lastmods = {}     # hub_url -> most recent member lastmod
            skipped_thin = 0

            for j in all_jurisdictions:
                url = "%s/%s" % (SITE, j[3])
                thin = bool(j[7]) if len(j) > 7 else False
                chash = j[8] if len(j) > 8 else ""
                prev = prev_state.get(url)
                lastmod = prev.get("lastmod", today) if (prev and prev.get("hash") == chash) else today
                new_state[url] = {"hash": chash, "lastmod": lastmod}
                # a hub is refreshed whenever any of its members changed
                hub_url = "%s/%s/" % (SITE, "/".join(j[3].split("/")[:2]))
                if lastmod > hub_lastmods.get(hub_url, ""):
                    hub_lastmods[hub_url] = lastmod
                if thin:
                    skipped_thin += 1
                    continue
                entries.append((url, lastmod))

            for hub_url, lastmod in hub_lastmods.items():
                entries.append((hub_url, lastmod))

            new_urls = "".join(
                "<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (u, lm)
                for u, lm in entries)

            sm = open(sitemap_path, encoding="utf-8").read()
            # drop any jurisdiction/hub entries from a previous run so reruns stay
            # idempotent; this matches only /states/<slug>/... so state overview pages
            # like /states/virginia.html and /states/index.html are left untouched.
            sm = re.sub(r"<url>\s*<loc>" + re.escape(SITE) + r"/states/[^/<]+/[^<]*</loc>.*?</url>",
                        "", sm, flags=re.S)
            sm = sm.replace("</urlset>", new_urls + "</urlset>")
            open(sitemap_path, "w", encoding="utf-8").write(sm)
            json.dump(new_state, open(state_path, "w", encoding="utf-8"),
                      separators=(",", ":"), sort_keys=True)
            print("extended sitemap.xml with %d indexed URLs (%d thin pages skipped)"
                  % (len(entries), skipped_thin))

        print("generated %d jurisdiction pages + %d canonical pointers + %d hubs across %d states/territories, "
              "through FY%d (skipped %d non-locality entries)"
              % (grand_pages, grand_stubs, grand_states, grand_states, lcfy, grand_drop))
        print("wrote locality-index.js (%d entries, %d KB)"
              % (len(all_jurisdictions), len(idx_js) // 1024))

if __name__ == "__main__":
    main()
