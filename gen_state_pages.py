#!/usr/bin/env python3
"""
gen_state_pages.py  --  Disaster Data per-state SEO page generator.

Reads the same STATES / DECLS / DENS / YOY data that the site already ships
(from data.js if present, else the baked fallback in index.html) and writes:

    states/index.html        the hub ("FEMA Disaster Declarations by State")
    states/<slug>.html        one crawlable page per state / territory (57)
    states/state.css          one shared stylesheet
    sitemap.xml               root sitemap listing every page
    robots.txt                points crawlers at the sitemap

It is deliberately decoupled from build.py's internals: run it as one extra
step in the weekly GitHub Action, AFTER build.py writes data.js:

    - run: python build.py
    - run: python gen_state_pages.py

No arguments needed. Re-running overwrites cleanly and is idempotent.
"""

import os, re, json, html, datetime

SITE = "https://www.disasterdata.io"
OUT_ROOT = os.environ.get("DD_OUT", ".")           # repo root (output)
SRC_ROOT = os.environ.get("DD_SRC", OUT_ROOT)      # where data.js / index.html live
STATES_DIR = os.path.join(OUT_ROOT, "states")

# ---------------------------------------------------------------- data loading
def _grab(text, name):
    """Pull a `let NAME = ...;` or `window.NAME = ...;` JSON literal out of JS."""
    m = re.search(r"(?:let|var|window\.)\s*" + name + r"\s*=\s*(\[.*?\]|\{.*?\});",
                  text, re.S)
    if not m:
        raise SystemExit("could not find %s in source" % name)
    return json.loads(m.group(1))

def load_data():
    for src in ("data.js", "index.html"):
        p = os.path.join(SRC_ROOT, src)
        if os.path.exists(p):
            t = open(p, encoding="utf-8").read()
            try:
                return (_grab(t, "STATES"), _grab(t, "DECLS"),
                        _grab(t, "DENS"), _grab(t, "YOY"))
            except SystemExit:
                continue
    raise SystemExit("no data.js or index.html with usable data found")

# ---------------------------------------------------------------- helpers
def slugify(name):
    s = name.lower().replace("&", "and").replace(".", "").replace(",", "")
    s = re.sub(r"[^\w\s/-]", "", s)
    s = re.sub(r"[\s/]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)

def fy_of(iso):                       # federal FY: Oct 1 .. Sep 30
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

TYPE_LONG = {"DR": "Major disaster", "EM": "Emergency", "FM": "Fire management"}

# ---------------------------------------------------------------- last complete FY
def last_complete_fy(YOY):
    now = datetime.date.today()
    cur_fy = now.year + 1 if now.month >= 10 else now.year
    avail = max((y for y, _ in YOY), default=cur_fy)
    return min(cur_fy - 1, avail)

# ---------------------------------------------------------------- per-state stats
def state_stats(ab, name, days, decls, dens, lcfy):
    complete = [r for r in decls if fy_of(r[3]) <= lcfy]
    by_type = {"DR": 0, "EM": 0, "FM": 0}
    haz = {}
    for r in complete:
        by_type[r[1]] = by_type.get(r[1], 0) + 1
        haz[r[2]] = haz.get(r[2], 0) + 1
    den_c = [d for d in dens if fy_of(d[3]) <= lcfy]
    decl = len(complete)
    den = len(den_c)
    rate = round(100.0 * den / (decl + den), 1) if (decl + den) else 0.0
    hazards = sorted(haz.items(), key=lambda kv: -kv[1])
    recent = sorted(decls, key=lambda r: r[3], reverse=True)[:40]
    return {
        "ab": ab, "name": name, "slug": slugify(name),
        "decl": decl, "dr": by_type["DR"], "em": by_type["EM"], "fm": by_type["FM"],
        "den": den, "rate": rate, "days": days,
        "hazards": hazards, "recent": recent,
        "recent_dens": sorted(den_c, key=lambda d: d[3], reverse=True)[:10],
    }

# ---------------------------------------------------------------- CSS
CSS = """
:root{--teal:#004c53;--cream:#f6f1e7;--paper:#fffdf7;--ink:#2b2b2b;--ink3:#6b6357;--rule:#e4dccb}
*{box-sizing:border-box}
body{margin:0;background:var(--cream);color:var(--ink);font-family:'Public Sans',system-ui,-apple-system,sans-serif;line-height:1.6}
a{color:var(--teal)}
.wrap{max-width:980px;margin:0 auto;padding:0 clamp(18px,4vw,40px)}
header.site{position:sticky;top:0;z-index:20;background:rgba(246,241,231,.9);backdrop-filter:saturate(140%) blur(8px);border-bottom:1px solid var(--rule)}
header.site .wrap{display:flex;align-items:center;justify-content:space-between;height:58px}
.brand{font-family:'Fraunces',Georgia,serif;font-weight:600;color:var(--teal);text-decoration:none;font-size:1.15rem}
.brand .beta{font:600 .6rem/1 'Public Sans',sans-serif;vertical-align:super;color:var(--ink3);margin-left:.25rem}
header.site nav a{margin-left:1.2rem;font-weight:600;font-size:.9rem;text-decoration:none}
main{padding:2rem 0 1rem}
.crumb{font-size:.82rem;color:var(--ink3);margin:0 0 1rem}
.crumb a{text-decoration:none}
h1{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:clamp(1.7rem,4vw,2.5rem);line-height:1.1;margin:.2rem 0 .6rem}
h2{font-family:'Fraunces',Georgia,serif;color:var(--teal);font-size:1.3rem;margin:2.2rem 0 .8rem}
.lede{font-size:1.08rem;max-width:62ch}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:.7rem;margin:1.5rem 0}
.stat{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:.85rem 1rem}
.stat .n{font-family:'Fraunces',Georgia,serif;font-size:1.7rem;color:var(--teal);font-weight:600;line-height:1}
.stat .l{font-size:.78rem;color:var(--ink3);margin-top:.3rem}
ul.haz{list-style:none;padding:0;margin:.5rem 0;display:flex;flex-wrap:wrap;gap:.5rem}
ul.haz li{background:var(--paper);border:1px solid var(--rule);border-radius:999px;padding:.3rem .8rem;font-size:.85rem}
ul.haz b{color:var(--teal)}
.tablewrap{overflow-x:auto;border:1px solid var(--rule);border-radius:12px;background:var(--paper)}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:560px}
th,td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.03em;color:var(--ink3);background:#faf6ec}
tr:last-child td{border-bottom:none}
.tag{font-weight:700;color:var(--teal)}
.audience{background:#eef4f4;border:1px solid #cfe0e0;border-radius:12px;padding:1rem 1.2rem;margin:2rem 0}
.method{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:1.2rem 1.4rem;margin:2rem 0;font-size:.92rem}
.method h2{margin-top:0;font-size:1.1rem}
.stategrid{display:flex;flex-wrap:wrap;gap:.4rem .7rem;margin:.6rem 0}
.stategrid a{font-size:.86rem;text-decoration:none}
ol.rank{padding-left:0;list-style:none;counter-reset:r}
ol.rank li{counter-increment:r;display:flex;align-items:baseline;gap:.7rem;padding:.45rem 0;border-bottom:1px solid var(--rule)}
ol.rank li::before{content:counter(r);font-family:'Fraunces',serif;color:var(--ink3);min-width:2.2ch;text-align:right}
ol.rank a{text-decoration:none;font-weight:600;flex:1}
ol.rank .c{color:var(--ink3);font-size:.9rem}
footer.site{border-top:1px solid var(--rule);margin-top:2rem;padding:1.5rem 0;color:var(--ink3);font-size:.85rem}
footer.site a{color:var(--ink3)}
@media(max-width:560px){header.site nav a{margin-left:.8rem}}
""".strip()

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
         '9..144,600&family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">')

HEAD = FONTS + "<style>" + CSS + "</style>"

def header_html():
    return ('<header class="site"><div class="wrap">'
            '<a class="brand" href="../index.html">Disaster Data</a>'
            '<nav><a href="../index.html">Explorer</a>'
            '<a href="../map.html">Map</a>'
            '<a href="index.html">By state</a>'
            '<a href="../about.html">About</a></nav></div></header>')

def method_html():
    return ('<section class="method"><h2>How these numbers are built</h2>'
            '<p>Every figure is drawn from FEMA\'s OpenFEMA datasets: the Disaster Declarations '
            'Summaries for declarations and the Declaration Denials dataset for turndowns, '
            'rebuilt automatically each week. A "declaration" is one unique combination of '
            'declaration type (DR / EM / FM), disaster number, and state, so a single disaster '
            'affecting five states counts as five declarations. Years are federal fiscal years '
            '(Oct 1 to Sep 30). Totals on this page cover complete fiscal years only; the current '
            'in-progress year may appear in the most-recent list but is not counted in the totals. '
            'Uses OpenFEMA data but is not endorsed by or affiliated with FEMA.</p></section>')

def footer_html():
    return ('<footer class="site"><div class="wrap">'
            'Disaster Data &middot; built from FEMA OpenFEMA, refreshed weekly &middot; '
            '<a href="../about.html">About and contact</a></div></footer>')


# ---------------------------------------------------------------- per-state page
def render_state_page(s, states, lcfy):
    name, ab, slug = s["name"], s["ab"], s["slug"]
    canonical = "%s/states/%s.html" % (SITE, slug)
    e = html.escape
    desc = ("%s has recorded %d federal disaster and emergency declarations since FY2000: "
            "%d major disasters, %d emergencies, and %d fire-management declarations. "
            "Denial rate %.1f%%. Full FEMA declaration history, mapped and ranked."
            % (name, s["decl"], s["dr"], s["em"], s["fm"], s["rate"]))

    ld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "%s FEMA disaster declarations (FY2000 to FY%d)" % (name, lcfy),
        "description": desc, "url": canonical, "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "Disaster Data", "url": SITE},
        "spatialCoverage": {"@type": "Place", "name": "%s, United States" % name},
        "temporalCoverage": "2000/%d" % lcfy,
        "isBasedOn": "https://www.fema.gov/about/openfema",
        "keywords": [name, "FEMA", "disaster declarations", "emergency management",
                     "federal disaster history", "%s disasters" % name],
    }

    # stat cards
    cards = [("%d" % s["decl"], "Declarations since FY2000"),
             ("%d" % s["dr"], "Major disasters (DR)"),
             ("%d" % s["em"], "Emergencies (EM)"),
             ("%d" % s["fm"], "Fire management (FM)"),
             ("%d" % s["den"], "Requests denied"),
             ("%.1f%%" % s["rate"], "Denial rate"),
             ("#%d" % s["rank"], "National rank by declarations")]
    if isinstance(s["days"], (int, float)) and s["days"] > 0:
        cards.append(("%.1f" % s["days"], "Avg days to a decision"))
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>'
                    % (v, l) for v, l in cards)

    # hazards
    haz = "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in s["hazards"][:8]) \
          or '<li>None recorded</li>'

    # recent declarations
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td><span class='tag' title='%s'>%s</span></td>"
        "<td>%s</td><td>%s</td></tr>"
        % (fmt_date(r[3]), e(r[0]), TYPE_LONG.get(r[1], r[1]), e(r[1]),
           e(r[2]), e(pretty_title(r[4])))
        for r in s["recent"])
    recent_tbl = ('<div class="tablewrap"><table><thead><tr><th>Date</th><th>Number</th>'
                  '<th>Type</th><th>Hazard</th><th>Title</th></tr></thead><tbody>'
                  + rows + '</tbody></table></div>')

    # denials
    if s["den"]:
        dn_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                          % (fmt_date(d[3]), e(d[1]), e(d[2])) for d in s["recent_dens"])
        denials = ('<p>FEMA turned down <b>%d</b> declaration request%s from %s since FY2000, '
                   'a denial rate of <b>%.1f%%</b>. Denials are tracked in a separate FEMA dataset '
                   'from approved declarations.</p>'
                   % (s["den"], "" if s["den"] == 1 else "s", name, s["rate"])
                   + ('<div class="tablewrap"><table><thead><tr><th>Date</th><th>Type</th>'
                      '<th>Hazard</th></tr></thead><tbody>' + dn_rows + '</tbody></table></div>'
                      if dn_rows else ''))
    else:
        denials = ('<p>No declaration requests from %s were turned down in complete fiscal years '
                   'through FY%d.</p>' % (name, lcfy))

    # lede
    if s["decl"]:
        top_haz = s["hazards"][0][0] if s["hazards"] else "disasters"
        lede = ("%s has recorded <b>%d</b> federal disaster and emergency declarations since FY2000 "
                "(through FY%d): %d major disasters, %d emergencies, and %d fire-management "
                "declarations. Its most common hazard is %s. It ranks #%d nationally by total "
                "declarations." % (name, s["decl"], lcfy, s["dr"], s["em"], s["fm"],
                                   e(top_haz.lower()), s["rank"]))
    else:
        lede = ("%s has no federal declarations recorded in complete fiscal years through FY%d."
                % (name, lcfy))

    # other states
    grid = "".join('<a href="%s.html">%s</a>' % (o["slug"], e(o["name"]))
                   for o in states if o["ab"] != ab)

    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s FEMA Disaster Declarations: Federal Disaster History Since FY2000</title>'
            '<meta name="description" content="%s">'
            '<link rel="canonical" href="%s">'
            '<meta property="og:title" content="%s: Federal Disaster Declarations">'
            '<meta property="og:description" content="%s">'
            '<meta property="og:type" content="website"><meta property="og:url" content="%s">'
            '<meta name="twitter:card" content="summary">'
            '%s'
            '<script type="application/ld+json">%s</script></head><body>'
            '%s<main><div class="wrap">'
            '<p class="crumb"><a href="../index.html">Disaster Data</a> / '
            '<a href="index.html">States</a> / %s</p>'
            '<h1>%s: Federal Disaster Declarations</h1>'
            '<p class="lede">%s</p>'
            '<div class="stats">%s</div>'
            '<h2>Most common hazards</h2><ul class="haz">%s</ul>'
            '<h2>Most recent declarations</h2>%s'
            '<h2>Denied requests</h2>%s'
            '<div class="audience"><strong>Built for emergency managers, grant writers, and '
            'analysts.</strong> Explore %s in the interactive tools: '
            '<a href="../map.html?state=%s">view the county map</a>, or '
            '<a href="../index.html">open the national explorer</a> to filter, chart, and export '
            'this data as CSV or JSON.</div>'
            '%s'
            '<h2>Browse another state</h2><nav class="stategrid">%s</nav>'
            '</div></main>%s</body></html>'
            % (e(name), e(desc), canonical, e(name), e(desc), canonical,
               HEAD, json.dumps(ld), header_html(),
               e(name), e(name), lede, stats, haz, recent_tbl, denials,
               e(name), ab, method_html(), grid, footer_html()))


# ---------------------------------------------------------------- hub
def render_hub(states, lcfy):
    e = html.escape
    total = sum(s["decl"] for s in states)
    rows = "".join('<li><a href="%s.html">%s</a><span class="c">%d declarations</span></li>'
                   % (s["slug"], e(s["name"]), s["decl"]) for s in states)
    desc = ("Federal disaster and emergency declarations for all 50 states, DC, and US "
            "territories since FY2000. %d declarations, ranked, mapped, and exportable. "
            "Built from FEMA OpenFEMA data." % total)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>FEMA Disaster Declarations by State (FY2000 to present) | Disaster Data</title>'
            '<meta name="description" content="%s">'
            '<link rel="canonical" href="%s/states/">'
            '<meta property="og:title" content="FEMA Disaster Declarations by State">'
            '<meta property="og:description" content="%s">'
            '<meta property="og:type" content="website">'
            '<meta property="og:url" content="%s/states/">'
            '<meta name="twitter:card" content="summary">'
            '%s</head><body>'
            '%s<main><div class="wrap">'
            '<p class="crumb"><a href="../index.html">Disaster Data</a> / States</p>'
            '<h1>FEMA Disaster Declarations by State</h1>'
            '<p class="lede">Every US state, the District of Columbia, and the territories, ranked '
            'by federal disaster and emergency declarations since FY2000 (through FY%d). '
            '%d declarations in all. Select a state for its full history, hazard breakdown, denial '
            'rate, and most recent declarations.</p>'
            '<ol class="rank">%s</ol>'
            '%s</div></main>%s</body></html>'
            % (e(desc), SITE, e(desc), SITE, HEAD, header_html(),
               lcfy, total, rows, method_html(), footer_html()))


# ---------------------------------------------------------------- sitemap + robots
def render_sitemap(states):
    # lastmod is derived from real data (each state's most recent declaration),
    # so the sitemap only changes when FEMA data does — no spurious weekly commits.
    def latest(s):
        return s["recent"][0][3] if s.get("recent") else None
    overall = max([d for d in (latest(s) for s in states) if d],
                  default=datetime.date.today().isoformat())
    def u(loc, lm):
        return "<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (loc, lm)
    parts = [u("%s/" % SITE, overall), u("%s/map.html" % SITE, overall),
             u("%s/about.html" % SITE, overall),
             u("%s/public-assistance-projects.html" % SITE, overall),
             u("%s/states/" % SITE, overall)]
    for s in states:
        parts.append(u("%s/states/%s.html" % (SITE, s["slug"]), latest(s) or overall))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
            % "".join(parts))

def render_robots():
    return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % SITE


# ---------------------------------------------------------------- main
def main():
    STATES, DECLS, DENS, YOY = load_data()
    lcfy = last_complete_fy(YOY)
    meta = {s["ab"]: s for s in STATES}

    rows = [state_stats(ab, m["name"], m.get("days", 0),
                        DECLS.get(ab, []), DENS.get(ab, []), lcfy)
            for ab, m in meta.items()]
    rows.sort(key=lambda s: -s["decl"])
    for i, s in enumerate(rows):
        s["rank"] = i + 1

    os.makedirs(STATES_DIR, exist_ok=True)
    for s in rows:
        open(os.path.join(STATES_DIR, s["slug"] + ".html"), "w", encoding="utf-8").write(
            render_state_page(s, rows, lcfy))
    open(os.path.join(STATES_DIR, "index.html"), "w", encoding="utf-8").write(
        render_hub(rows, lcfy))
    open(os.path.join(OUT_ROOT, "sitemap.xml"), "w", encoding="utf-8").write(
        render_sitemap(rows))
    open(os.path.join(OUT_ROOT, "robots.txt"), "w", encoding="utf-8").write(render_robots())

    print("generated %d state pages + hub, through FY%d" % (len(rows), lcfy))
    print("national total (complete FY): %d" % sum(s["decl"] for s in rows))

if __name__ == "__main__":
    main()
