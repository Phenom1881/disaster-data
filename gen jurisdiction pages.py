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

import os, re, json, html, datetime
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
    return _grab_js(t, "LOCALITY_DATA"), _grab_js(t, "BROWSE"), _grab_js(t, "STATE_NAMES")

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

# ---------------------------------------------------------------- per-jurisdiction stats
def juris_stats(entry, state_ab, by_id, lcfy):
    c = classify(state_ab, entry["n"])
    if not c["keep"]:
        return None
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
    return {
        "name": disp, "slug": slug, "kind": kind, "noun": c["noun"], "label": kind_label(c),
        "decl": len(complete), "dr": by_type["DR"], "em": by_type["EM"], "fm": by_type["FM"],
        "days": entry.get("a", 0),
        "hazards": sorted(haz.items(), key=lambda kv: -kv[1]),
        "recent": recent[:40],
        "hmp": sorted(complete, key=lambda r: r.get("declarationDate", ""), reverse=True),
        "latest": entry.get("l", ""),
    }

# ---------------------------------------------------------------- CSS (matches state pages)
CSS = """
:root{--teal:#004c53;--cream:#f6f1e7;--paper:#fffdf7;--ink:#2b2b2b;--ink3:#6b6357;--rule:#e4dccb}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--ink);font-family:'Public Sans',system-ui,-apple-system,sans-serif;line-height:1.6}
a{color:var(--teal)}
.wrap{max-width:980px;margin:0 auto;padding:0 clamp(18px,4vw,40px)}
nav.ddnav{position:sticky;top:0;z-index:50;background:rgba(246,241,231,.86);backdrop-filter:saturate(140%) blur(10px);-webkit-backdrop-filter:saturate(140%) blur(10px);border-bottom:1px solid #e0d8c5;display:flex;align-items:center;justify-content:space-between;padding:0 clamp(18px,4vw,48px);height:60px}
nav.ddnav .brand{display:flex;align-items:baseline;gap:10px}
nav.ddnav .brand .mark{font-family:'Fraunces',Georgia,serif;font-weight:600;font-size:19px;letter-spacing:-.4px;color:#1d1813;text-decoration:none}
nav.ddnav .navlinks{display:flex;align-items:center;gap:4px}
nav.ddnav .navlinks a{font-size:13px;font-weight:500;color:#5b5346;text-decoration:none;padding:7px 12px;border-radius:6px;transition:.15s;letter-spacing:.2px}
nav.ddnav .navlinks a:hover{color:#1d1813;background:#f1ead9}
nav.ddnav .navlinks a.on{color:#004c53;background:#d7e9ea}
nav.ddnav .navmeta{font-size:11px;color:#938a78;letter-spacing:.5px;font-variant-numeric:tabular-nums}
main{padding:2rem 0 1rem}
.crumb{font-size:.82rem;color:var(--ink3);margin:0 0 1rem}.crumb a{text-decoration:none}
.badge{display:inline-block;font:600 .72rem 'Public Sans',sans-serif;text-transform:uppercase;letter-spacing:.04em;padding:.2rem .6rem;border-radius:999px;margin-bottom:.6rem}
.badge.county{color:#004c53;background:#d7e9ea}.badge.city{color:#8a5a2b;background:#f3e4d2}.badge.tribal{color:#6a2f6a;background:#efddef}
h1{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:clamp(1.7rem,4vw,2.5rem);line-height:1.1;margin:.2rem 0 .6rem}
h2{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:1.3rem;margin:2.2rem 0 .8rem}
.lede{font-size:1.08rem;max-width:62ch}
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
.method{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:1.2rem 1.4rem;margin:2rem 0;font-size:.92rem}.method h2{margin-top:0;font-size:1.1rem}
.jgrid{display:flex;flex-wrap:wrap;gap:.4rem .7rem;margin:.6rem 0}.jgrid a{font-size:.86rem;text-decoration:none}
ol.rank{padding-left:0;list-style:none;counter-reset:r}
ol.rank li{counter-increment:r;display:flex;align-items:baseline;gap:.7rem;padding:.45rem 0;border-bottom:1px solid var(--rule)}
ol.rank li::before{content:counter(r);font-family:'Fraunces',serif;color:var(--ink3);min-width:2.6ch;text-align:right}
ol.rank a{text-decoration:none;font-weight:600}ol.rank .k{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3)}
ol.rank .c{color:var(--ink3);font-size:.9rem;margin-left:auto}
footer.site{border-top:1px solid var(--rule);margin-top:2rem;padding:1.5rem 0;color:var(--ink3);font-size:.85rem}footer.site a{color:var(--ink3)}
@media(max-width:720px){nav.ddnav{height:auto;flex-direction:column;align-items:stretch;gap:9px;padding-top:11px;padding-bottom:11px}nav.ddnav .navmeta{display:none}nav.ddnav .navlinks{flex-wrap:wrap}}
""".strip()

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
         '9..144,500;9..144,600&family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">')
HEAD = FONTS + "<style>" + CSS + "</style>"

# paths are two levels deep: states/virginia/<slug>.html -> site root is ../../
def header_html():
    return ('<nav class="ddnav">'
            '<div class="brand"><a class="mark" href="../../index.html">Disaster Data</a></div>'
            '<div class="navlinks">'
            '<a href="../../index.html">Overview</a>'
            '<a href="../../index.html#board">Explore</a>'
            '<a href="../../map.html">Map</a>'
            '<a href="../../states/index.html" class="on">States</a>'
            '<a href="../../public-assistance-projects.html">Funding</a>'
            '<a href="../../about.html">About</a></div>'
            '<div class="navmeta">FY 2000 to 2026 &middot; OpenFEMA</div></nav>')

def footer_html():
    return ('<footer class="site"><div class="wrap">Disaster Data &middot; built from FEMA OpenFEMA, '
            'refreshed weekly &middot; <a href="https://forms.gle/NZ6bSadoXrKYHjjH8" target="_blank" rel="noopener">Report a data issue</a>'
            ' &middot; <a href="../../about.html">About and contact</a></div></footer>'
            '<!-- Cloudflare Web Analytics --><script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            'data-cf-beacon=\'{"token": "ceea2416f66a424981ba37fcb9440d68"}\'></script>'
            '<!-- End Cloudflare Web Analytics -->')

def method_html(kind):
    extra = {
        "county": "This page counts declarations that named this jurisdiction as a designated area.",
        "city": "Independent cities are counted separately from the counties around them, matching how FEMA designates them.",
        "tribal": "Tribal areas are counted as their own jurisdictions, separate from the counties they sit within.",
    }[kind]
    return ('<section class="method"><h2>How these numbers are built</h2>'
            '<p>Drawn from FEMA\'s OpenFEMA Disaster Declarations Summaries, rebuilt each week. '
            'A declaration is counted here once for each designated area it names, so a single '
            'disaster covering many localities is counted in each one. For that reason these '
            f'jurisdiction counts do not sum to {STATE_NAME}\'s statewide total. ' + extra +
            ' Totals cover complete fiscal years (Oct 1 to Sep 30); the in-progress year may '
            'appear in the most-recent list but is not counted in the totals. Uses OpenFEMA data '
            'but is not endorsed by or affiliated with FEMA.</p></section>')

# ---------------------------------------------------------------- jurisdiction page
def render_page(j, others):
    e = html.escape
    canonical = "%s/states/%s/%s.html" % (SITE, STATE_SLUG, j["slug"])
    label = j["label"]
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
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % c for c in cards)

    haz = "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in j["hazards"][:8]) or '<li>None recorded</li>'

    rows = "".join("<tr><td>%s</td><td>%s</td><td><span class='tag' title='%s'>%s</span></td><td>%s</td><td>%s</td></tr>"
                   % (fmt_date(r.get("declarationDate", "")), e(r.get("femaDeclarationString", "")),
                      TYPE_LONG.get(r.get("declarationType", ""), ""), e(r.get("declarationType", "")),
                      e(r.get("incidentType", "")), e(pretty_title(r.get("declarationTitle", ""))))
                   for r in j["recent"])
    history = ('<p class="legend" style="font-size:.82rem;color:#6b6357;margin:.5rem 0 .6rem">'
               '<b style="color:#004c53">DR</b> = Major disaster (Stafford Act) &middot; '
               '<b style="color:#004c53">EM</b> = Emergency declaration &middot; '
               '<b style="color:#004c53">FM</b> = Fire management assistance</p>'
               '<div class="tablewrap"><table><thead><tr><th>Date</th><th>Number</th><th>Type</th>'
               '<th>Hazard</th><th>Title</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
               '<div class="export-bar" style="display:flex;flex-wrap:wrap;gap:.6rem;margin:.8rem 0 0">'
               '<button class="copybtn csvbtn" type="button">Download CSV</button>'
               '<button class="copybtn citebtn" type="button">Cite this page</button></div>')

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

    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
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
            '<h2>Most common hazards</h2><ul class="haz">%s</ul>'
            '%s'
            '<h2>Every declaration on record</h2>%s'
            f'<div style="margin:2rem 0"><a href="../{STATE_SLUG}.html">&larr; {STATE_NAME} statewide overview</a> '
            f'&middot; <a href="index.html">All {STATE_NAME} jurisdictions</a></div>'
            '%s'
            f'<h2>Other {STATE_NAME} jurisdictions</h2><nav class="jgrid">%s</nav>'
            '</div></main>%s%s</body></html>'
            % (e(j["name"]), e(desc), canonical, e(j["name"]), e(desc), canonical,
               HEAD, json.dumps(ld), header_html(),
               e(j["name"]), j["kind"], label, e(j["name"]), lede, stats, haz, hmp, history,
               method_html(j["kind"]), grid, footer_html(), copyjs))

# ---------------------------------------------------------------- hub
def render_hub(js):
    e = html.escape
    rows = "".join('<li><a href="%s.html">%s</a> <span class="k">%s</span>'
                   '<span class="c">%d declarations</span></li>'
                   % (j["slug"], e(j["name"]), j["label"], j["decl"]) for j in js)
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

# ---------------------------------------------------------------- build
def build_state(state_ab, LOCALITY, by_id, lcfy, NAMES):
    """Generate all keep-localities + hub for one state. Returns (kept, dropped)."""
    global STATE_AB, STATE_NAME, STATE_SLUG, OUT_DIR
    STATE_AB = state_ab
    STATE_NAME = NAMES.get(state_ab, state_ab)
    STATE_SLUG = slugify(STATE_NAME)
    OUT_DIR = os.path.join(OUT_ROOT, "states", STATE_SLUG)

    entries = LOCALITY.get(state_ab, [])
    stats = [juris_stats(en, state_ab, by_id, lcfy) for en in entries]
    js = [s for s in stats if s is not None]
    dropped = len(stats) - len(js)
    if not js:
        return (0, dropped, [])

    seen = {}
    for j in js:
        if j["slug"] in seen:
            j["slug"] = j["slug"] + "-2"
        seen[j["slug"]] = 1
    js.sort(key=lambda j: (-j["decl"], j["name"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    for j in js:
        open(os.path.join(OUT_DIR, j["slug"] + ".html"), "w", encoding="utf-8").write(render_page(j, js))
    open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(render_hub(js))
    return (len(js), dropped, js)

def main():
    LOCALITY, BROWSE, NAMES = load_data()
    by_id = {r["femaDeclarationString"]: r for r in BROWSE}
    lcfy = last_complete_fy(BROWSE)

    one = os.environ.get("DD_STATE")
    if one:
        targets = [one.upper()]
    else:
        # every state/territory that has at least one locality, in name order
        targets = sorted(LOCALITY.keys(), key=lambda s: NAMES.get(s, s))

    grand_pages = grand_states = grand_drop = 0
    all_jurisdictions = []
    for st in targets:
        kept, dropped, js = build_state(st, LOCALITY, by_id, lcfy, NAMES)
        grand_drop += dropped
        if kept:
            grand_states += 1
            grand_pages += kept
            state_name = NAMES.get(st, st)
            state_slug = slugify(state_name)
            for j in js:
                all_jurisdictions.append([
                    j["name"], st, state_name,
                    "states/%s/%s.html" % (state_slug, j["slug"]),
                    j["decl"], j["kind"], j["noun"]
                ])
            if one:
                print("generated %d %s jurisdiction pages + hub, through FY%d" % (kept, STATE_NAME, lcfy))

    # write search/map index (used by homepage search + map click-through)
    if not one:
        idx_path = os.path.join(OUT_ROOT, "locality-index.js")
        # compact JSON array: [name, stateAB, stateName, url, declCount, kind, noun]
        idx_js = "window.LOCALITY_INDEX=" + json.dumps(all_jurisdictions, separators=(",", ":")) + ";"
        open(idx_path, "w", encoding="utf-8").write(idx_js)

        # extend sitemap.xml with jurisdiction URLs
        sitemap_path = os.path.join(OUT_ROOT, "sitemap.xml")
        if os.path.exists(sitemap_path):
            sm = open(sitemap_path, encoding="utf-8").read()
            new_urls = []
            for j in all_jurisdictions:
                new_urls.append("<url><loc>%s/%s</loc></url>" % (SITE, j[3]))
            # also add each jurisdiction hub
            seen_hubs = set()
            for j in all_jurisdictions:
                parts = j[3].split("/")  # e.g. states/virginia/tazewell-county-va.html
                hub_url = "/".join(parts[:2]) + "/"  # states/virginia/
                if hub_url not in seen_hubs:
                    seen_hubs.add(hub_url)
                    new_urls.append("<url><loc>%s/%s</loc></url>" % (SITE, hub_url))
            sm = sm.replace("</urlset>", "".join(new_urls) + "</urlset>")
            open(sitemap_path, "w", encoding="utf-8").write(sm)
            print("extended sitemap.xml with %d jurisdiction URLs" % len(new_urls))

        print("generated %d jurisdiction pages + %d hubs across %d states/territories, "
              "through FY%d (skipped %d non-locality entries)"
              % (grand_pages, grand_states, grand_states, lcfy, grand_drop))
        print("wrote locality-index.js (%d entries, %d KB)"
              % (len(all_jurisdictions), len(idx_js) // 1024))

if __name__ == "__main__":
    main()
