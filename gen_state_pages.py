#!/usr/bin/env python3
"""
gen_state_pages.py  --  Disaster Data per-state SEO page generator.

Primary data source: data.js written by build.py each week.
  Reads: STATE_SUMMARY, STATE_INC, BROWSE, DENIALS, STATE_NAMES, DATA_DATE
  (build.py guarantees BROWSE count == sum of STATE_SUMMARY.declarations,
  so per-state totals always reconcile with the homepage figure.)

Fallback: baked snapshots in index.html (STATES, DECLS, DENS, YOY).

Writes:
    states/index.html          hub page ("FEMA Disaster Declarations by State")
    states/<slug>.html         one crawlable page per state / territory (57)
    sitemap.xml                root-level sitemap
    robots.txt                 points crawlers at the sitemap

Run AFTER build.py:
    python build.py
    python gen_state_pages.py

No arguments needed. Re-running overwrites cleanly; output is idempotent.
"""

import os
import re
import json
import html
import datetime
from collections import defaultdict

SITE       = "https://www.disasterdata.io"
OUT_ROOT   = os.environ.get("DD_OUT", ".")        # repo root (output target)
SRC_ROOT   = os.environ.get("DD_SRC", OUT_ROOT)   # where data.js / index.html live
STATES_DIR = os.path.join(OUT_ROOT, "states")


# =========================================================================
# Data loading
# =========================================================================

def _load_data_js(path):
    """Parse data.js into {VAR_NAME: python_object}.

    build.py writes one compact-JSON assignment per line:
        window.VARNAME=<json>
    No semicolons, no embedded newlines in values.
    """
    result = {}
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line.startswith("window."):
                continue
            eq   = line.index("=")
            name = line[7:eq].strip()       # drop "window." + surrounding whitespace
            val  = line[eq + 1:].strip()
            try:
                result[name] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
    return result


def _grab_fallback(text, name):
    """Extract `let/var/window.NAME = ...;` JSON literal from inline JS text."""
    m = re.search(
        r"(?:let|var|window\.)\s*" + name + r"\s*=\s*(\[.*?\]|\{.*?\});",
        text, re.S
    )
    if not m:
        raise KeyError("variable not found in source: %s" % name)
    return json.loads(m.group(1))


def load_data():
    """Return (source_type, data_dict).
    source_type: 'live' (data.js) | 'fallback' (index.html)
    """
    djs = os.path.join(SRC_ROOT, "data.js")
    if os.path.exists(djs):
        try:
            d = _load_data_js(djs)
            required = (
                "STATE_SUMMARY", "STATE_INC", "BROWSE",
                "DENIALS", "STATE_NAMES", "DATA_DATE",
            )
            missing = [k for k in required if k not in d]
            if not missing:
                browse_n = len(d["BROWSE"])
                print("[gen] source: data.js  (%d BROWSE records)" % browse_n)
                return "live", d
            print("[gen] data.js found but missing %s; trying fallback" % missing)
        except Exception as exc:
            print("[gen] data.js error: %s; trying fallback" % exc)

    idx = os.path.join(SRC_ROOT, "index.html")
    if os.path.exists(idx):
        try:
            t   = open(idx, encoding="utf-8").read()
            d   = {k: _grab_fallback(t, k) for k in ("STATES", "DECLS", "DENS", "YOY")}
            total = sum(len(v) for v in d["DECLS"].values())
            print("[gen] source: index.html fallback (%d DECLS records)" % total)
            return "fallback", d
        except Exception as exc:
            print("[gen] index.html error: %s" % exc)

    raise SystemExit("[gen] no usable data source found (data.js or index.html)")


# =========================================================================
# Shared helpers
# =========================================================================

def slugify(name):
    s = name.lower().replace("&", "and").replace(".", "").replace(",", "")
    s = re.sub(r"[^\w\s/-]", "", s)
    s = re.sub(r"[\s/]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)


def fmt_date(iso):
    if not iso:
        return ""
    try:
        return datetime.datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except Exception:
        return iso[:10]


def pretty_title(t):
    t = (t or "").strip()
    return t.title() if t.isupper() else t


def last_complete_fy(date_str):
    """Last fully-closed federal fiscal year relative to date_str (YYYY-MM-DD).
    Federal FY Y runs Oct 1 of year Y-1 through Sep 30 of year Y.
    If today is before Sep 30 of year Y, FY Y is still in progress.
    """
    y, m = int(date_str[:4]), int(date_str[5:7])
    current_fy = y if m < 10 else y + 1
    return current_fy - 1


TYPE_LONG = {"DR": "Major disaster", "EM": "Emergency", "FM": "Fire management"}


# =========================================================================
# Build per-state dicts from live data.js
# =========================================================================

def build_states_live(data):
    """Construct per-state dicts from data.js variables.

    Uses STATE_SUMMARY for pre-computed totals so per-state declaration counts
    exactly match the homepage figure (build.py asserts BROWSE == STATE_SUMMARY sum).
    DR / EM / FM breakdown is computed from BROWSE by filtering on state + declarationType.
    Hazard breakdown comes from STATE_INC (pre-sorted descending by count).
    Recent declaration list comes from BROWSE (most recent 40 per state).
    Denial list comes from DENIALS (most recent 10 per state).
    """
    names    = data["STATE_NAMES"]                               # {AB: "Full Name"}
    sm_idx   = {s["state"]: s for s in data["STATE_SUMMARY"]}   # keyed by state AB
    s_inc    = data.get("STATE_INC", {})                         # {AB: [{t, c}, ...]}
    browse   = data["BROWSE"]                                    # list of declaration dicts
    denials  = data["DENIALS"]                                   # list of denial dicts
    ddate    = data["DATA_DATE"]                                 # "YYYY-MM-DD"
    lcfy     = last_complete_fy(ddate)

    # Index BROWSE by state
    by_st = defaultdict(list)
    for r in browse:
        by_st[r["state"]].append(r)

    # Index DENIALS by stateAbbreviation
    den_by_st = defaultdict(list)
    for r in denials:
        ab = (r.get("stateAbbreviation") or "").strip()
        if ab:
            den_by_st[ab].append(r)

    rows = []
    for ab, name in names.items():
        sm = sm_idx.get(ab, {
            "declarations":   0,
            "denials":        0,
            "total_requests": 0,
            "denial_rate":    0.0,
            "avg_days":       0.0,
            "top_incident":   "",
        })

        # DR / EM / FM counts from BROWSE (consistent with STATE_SUMMARY totals)
        type_ct = defaultdict(int)
        for r in by_st[ab]:
            type_ct[r.get("declarationType", "")] += 1

        # Hazards: STATE_INC already sorted descending by count
        hazards = [(h["t"], h["c"]) for h in s_inc.get(ab, [])]

        # Most recent 40 declarations for this state
        recent = sorted(
            by_st[ab],
            key=lambda r: r.get("declarationDate", ""),
            reverse=True,
        )[:40]

        # Most recent 10 denials; sort by decision date (requestStatusDate), fallback to request date
        recent_dens = sorted(
            den_by_st[ab],
            key=lambda r: (
                r.get("requestStatusDate") or r.get("declarationRequestDate") or ""
            ),
            reverse=True,
        )[:10]

        rows.append({
            "ab":          ab,
            "name":        name,
            "slug":        slugify(name),
            "decl":        sm["declarations"],
            "dr":          type_ct["DR"],
            "em":          type_ct["EM"],
            "fm":          type_ct["FM"],
            "den":         sm["denials"],
            "rate":        sm["denial_rate"],
            "days":        sm["avg_days"],
            "hazards":     hazards,
            "recent":      recent,         # BROWSE-shaped dicts
            "recent_dens": recent_dens,    # DENIALS-shaped dicts
            "ddate":       ddate,
            "lcfy":        lcfy,
            "mode":        "live",
        })

    return rows


# =========================================================================
# Build per-state dicts from index.html fallback (old baked variables)
# =========================================================================

def _fy_of(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return y + 1 if m >= 10 else y


def build_states_fallback(data):
    """Construct per-state dicts from index.html baked variables (STATES, DECLS, DENS, YOY).
    Converts tuple record format to the same dict shape as build_states_live(),
    so render_state_page() can be called identically for both paths.
    """
    meta  = {s["ab"]: s for s in data["STATES"]}
    DECLS = data["DECLS"]
    DENS  = data["DENS"]
    YOY   = data["YOY"]

    now    = datetime.date.today()
    cur_fy = now.year + 1 if now.month >= 10 else now.year
    avail  = max((y for y, _ in YOY), default=cur_fy)
    lcfy   = min(cur_fy - 1, avail)
    ddate  = now.isoformat()

    rows = []
    for ab, m in meta.items():
        name  = m["name"]
        decls = DECLS.get(ab, [])
        dens  = DENS.get(ab, [])

        compl = [r for r in decls if _fy_of(r[3]) <= lcfy]
        den_c = [d for d in dens  if _fy_of(d[3]) <= lcfy]

        type_ct = defaultdict(int)
        haz_ct  = defaultdict(int)
        for r in compl:
            type_ct[r[1]] += 1
            haz_ct[r[2] or "Unknown"] += 1

        decl_n = len(compl)
        den_n  = len(den_c)
        total_r = decl_n + den_n
        rate    = round(100.0 * den_n / total_r, 1) if total_r else 0.0
        hazards = sorted(haz_ct.items(), key=lambda kv: -kv[1])

        # Convert tuple lists to BROWSE / DENIALS dict shapes
        recent_dicts = [
            {
                "femaDeclarationString": r[0],
                "declarationType":       r[1],
                "incidentType":          r[2],
                "declarationDate":       r[3],
                "declarationTitle":      r[4],
                "days_to_approve":       -1,
            }
            for r in sorted(decls, key=lambda r: r[3], reverse=True)[:40]
        ]
        den_dicts = [
            {
                "declarationRequestType":  d[1],
                "requestedIncidentTypes":  d[2],
                "requestStatusDate":       d[3],
            }
            for d in sorted(den_c, key=lambda d: d[3], reverse=True)[:10]
        ]

        rows.append({
            "ab":          ab,
            "name":        name,
            "slug":        slugify(name),
            "decl":        decl_n,
            "dr":          type_ct["DR"],
            "em":          type_ct["EM"],
            "fm":          type_ct["FM"],
            "den":         den_n,
            "rate":        rate,
            "days":        m.get("days", 0),
            "hazards":     hazards,
            "recent":      recent_dicts,
            "recent_dens": den_dicts,
            "ddate":       ddate,
            "lcfy":        lcfy,
            "mode":        "fallback",
        })

    return rows


# =========================================================================
# Static HTML fragments (CSS, head, header, footer)
# =========================================================================

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

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
    '9..144,600&family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">'
)

HEAD = FONTS + "<style>" + CSS + "</style>"


def header_html():
    return (
        '<header class="site"><div class="wrap">'
        '<a class="brand" href="../index.html">Disaster Data</a>'
        '<nav>'
        '<a href="../index.html">Explorer</a>'
        '<a href="../map.html">Map</a>'
        '<a href="index.html">By state</a>'
        '<a href="../about.html">About</a>'
        '</nav></div></header>'
    )


def method_html(ddate):
    return (
        '<section class="method"><h2>How these numbers are built</h2>'
        '<p>Every figure is drawn from FEMA\'s OpenFEMA datasets: the Disaster Declarations '
        'Summaries for approved declarations and the Declaration Denials dataset for '
        'turndowns, rebuilt automatically each week. A "declaration" is one unique '
        'combination of declaration type (DR / EM / FM), disaster number, and state, so '
        'a single disaster affecting five states counts as five declarations. Years are '
        'federal fiscal years (Oct 1 to Sep 30). Data is current as of %s. '
        'Uses OpenFEMA data but is not endorsed by or affiliated with FEMA.</p></section>'
        % (ddate or "latest build")
    )


def footer_html():
    return (
        '<footer class="site"><div class="wrap">'
        'Disaster Data &middot; built from FEMA OpenFEMA, refreshed weekly &middot; '
        '<a href="../about.html">About and contact</a>'
        '</div></footer>'
    )


# =========================================================================
# Per-state page renderer
# =========================================================================

def render_state_page(s, all_states):
    """Render a complete HTML page for one state.

    s["recent"]      is a list of BROWSE-shaped dicts (or converted dicts in fallback mode).
    s["recent_dens"] is a list of DENIALS-shaped dicts (or converted dicts in fallback mode).
    """
    name, ab, slug = s["name"], s["ab"], s["slug"]
    canonical = "%s/states/%s.html" % (SITE, slug)
    e     = html.escape
    ddate = s.get("ddate", datetime.date.today().isoformat())
    lcfy  = s.get("lcfy", datetime.date.today().year - 1)

    # ---- meta description -----------------------------------------------
    desc = (
        "%s has recorded %d federal disaster and emergency declarations since FY2000: "
        "%d major disasters, %d emergencies, and %d fire-management declarations. "
        "Denial rate %.1f%%. Full FEMA declaration history, mapped and ranked."
        % (name, s["decl"], s["dr"], s["em"], s["fm"], s["rate"])
    )

    # ---- JSON-LD --------------------------------------------------------
    ld = {
        "@context": "https://schema.org",
        "@type":    "Dataset",
        "name":     "%s FEMA disaster declarations (FY2000 to FY%d)" % (name, lcfy),
        "description": desc,
        "url":      canonical,
        "isAccessibleForFree": True,
        "creator":  {"@type": "Organization", "name": "Disaster Data", "url": SITE},
        "spatialCoverage":  {"@type": "Place", "name": "%s, United States" % name},
        "temporalCoverage": "2000/%d" % lcfy,
        "isBasedOn": "https://www.fema.gov/about/openfema",
        "keywords": [
            name, "FEMA", "disaster declarations", "emergency management",
            "federal disaster history", "%s disasters" % name,
        ],
    }

    # ---- stat cards -----------------------------------------------------
    cards = [
        ("%d"     % s["decl"],  "Declarations since FY2000"),
        ("%d"     % s["dr"],    "Major disasters (DR)"),
        ("%d"     % s["em"],    "Emergencies (EM)"),
        ("%d"     % s["fm"],    "Fire management (FM)"),
        ("%d"     % s["den"],   "Requests denied"),
        ("%.1f%%" % s["rate"],  "Denial rate"),
        ("#%d"    % s["rank"],  "National rank by declarations"),
    ]
    if s["days"] and float(s["days"]) > 0:
        cards.append(("%.1f" % s["days"], "Avg days to a decision"))
    stats = "".join(
        '<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>'
        % (v, l) for v, l in cards
    )

    # ---- hazards --------------------------------------------------------
    haz = (
        "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in s["hazards"][:8])
        or '<li>None recorded</li>'
    )

    # ---- recent declarations table --------------------------------------
    def _dec_row(r):
        return (
            "<tr>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td><span class='tag' title='%s'>%s</span></td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "</tr>"
            % (
                fmt_date(r.get("declarationDate", "")),
                e(r.get("femaDeclarationString", "")),
                TYPE_LONG.get(r.get("declarationType", ""), r.get("declarationType", "")),
                e(r.get("declarationType", "")),
                e(r.get("incidentType", "") or ""),
                e(pretty_title(r.get("declarationTitle", "") or "")),
            )
        )

    dec_rows = "".join(_dec_row(r) for r in s["recent"])
    recent_tbl = (
        '<div class="tablewrap"><table>'
        '<thead><tr><th>Date</th><th>Number</th><th>Type</th><th>Hazard</th><th>Title</th></tr></thead>'
        '<tbody>' + dec_rows + '</tbody>'
        '</table></div>'
    )

    # ---- denials section ------------------------------------------------
    if s["den"]:
        def _den_row(d):
            date_val = (
                d.get("requestStatusDate")
                or d.get("declarationRequestDate")
                or ""
            )
            return "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                fmt_date(date_val),
                e(d.get("declarationRequestType", "") or ""),
                e(d.get("requestedIncidentTypes",  "") or ""),
            )

        dn_rows = "".join(_den_row(d) for d in s["recent_dens"])
        denials = (
            '<p>FEMA turned down <b>%d</b> declaration request%s from %s since FY2000, '
            'a denial rate of <b>%.1f%%</b>. Denials are tracked in a separate FEMA '
            'dataset from approved declarations.</p>'
            % (s["den"], "" if s["den"] == 1 else "s", name, s["rate"])
            + (
                '<div class="tablewrap"><table>'
                '<thead><tr><th>Date</th><th>Type</th><th>Hazard</th></tr></thead>'
                '<tbody>' + dn_rows + '</tbody></table></div>'
                if dn_rows else ""
            )
        )
    else:
        denials = (
            '<p>No declaration requests from %s have been turned down in the '
            'available data through FY%d.</p>' % (name, lcfy)
        )

    # ---- lede -----------------------------------------------------------
    if s["decl"]:
        top_haz = s["hazards"][0][0] if s["hazards"] else "disasters"
        lede = (
            "%s has recorded <b>%d</b> federal disaster and emergency declarations "
            "since FY2000 (data as of %s): %d major disasters, %d emergencies, and "
            "%d fire-management declarations. Its most common hazard is %s. "
            "It ranks #%d nationally by total declarations."
            % (
                name, s["decl"], ddate,
                s["dr"], s["em"], s["fm"],
                e(top_haz.lower()),
                s["rank"],
            )
        )
    else:
        lede = (
            "%s has no federal declarations recorded in the available data "
            "through FY%d." % (name, lcfy)
        )

    # ---- other states nav -----------------------------------------------
    grid = "".join(
        '<a href="%s.html">%s</a>' % (o["slug"], e(o["name"]))
        for o in all_states if o["ab"] != ab
    )

    # ---- assemble -------------------------------------------------------
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>%s FEMA Disaster Declarations: Federal Disaster History Since FY2000</title>'
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s">'
        '<meta property="og:title" content="%s: Federal Disaster Declarations">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:type" content="website">'
        '<meta property="og:url" content="%s">'
        '<meta name="twitter:card" content="summary">'
        '%s'
        '<script type="application/ld+json">%s</script>'
        '</head><body>'
        '%s'
        '<main><div class="wrap">'
        '<p class="crumb">'
        '<a href="../index.html">Disaster Data</a> / '
        '<a href="index.html">States</a> / %s'
        '</p>'
        '<h1>%s: Federal Disaster Declarations</h1>'
        '<p class="lede">%s</p>'
        '<div class="stats">%s</div>'
        '<h2>Most common hazards</h2>'
        '<ul class="haz">%s</ul>'
        '<h2>Most recent declarations</h2>%s'
        '<h2>Denied requests</h2>%s'
        '<div class="audience">'
        '<strong>Built for emergency managers, grant writers, and analysts.</strong> '
        'Explore %s in the interactive tools: '
        '<a href="../map.html?state=%s">view the county map</a>, or '
        '<a href="../index.html">open the national explorer</a> to filter, chart, '
        'and export this data as CSV or JSON.'
        '</div>'
        '%s'
        '<h2>Browse another state</h2>'
        '<nav class="stategrid">%s</nav>'
        '</div></main>'
        '%s'
        '</body></html>'
        % (
            e(name), e(desc), canonical,
            e(name), e(desc), canonical,
            HEAD, json.dumps(ld),
            header_html(),
            e(name), e(name), lede, stats, haz,
            recent_tbl, denials,
            e(name), ab,
            method_html(ddate), grid,
            footer_html(),
        )
    )


# =========================================================================
# Hub page renderer
# =========================================================================

def render_hub(states):
    e     = html.escape
    total = sum(s["decl"] for s in states)
    ddate = states[0].get("ddate", "") if states else ""
    lcfy  = states[0].get("lcfy", 0)   if states else 0

    rows = "".join(
        '<li><a href="%s.html">%s</a>'
        '<span class="c">%d declarations</span></li>'
        % (s["slug"], e(s["name"]), s["decl"])
        for s in states
    )
    desc = (
        "Federal disaster and emergency declarations for all 50 states, DC, and US "
        "territories since FY2000. %d declarations, ranked, mapped, and exportable. "
        "Built from FEMA OpenFEMA data." % total
    )
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>FEMA Disaster Declarations by State (FY2000 to present) | Disaster Data</title>'
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s/states/">'
        '<meta property="og:title" content="FEMA Disaster Declarations by State">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:type" content="website">'
        '<meta property="og:url" content="%s/states/">'
        '<meta name="twitter:card" content="summary">'
        '%s'
        '</head><body>'
        '%s'
        '<main><div class="wrap">'
        '<p class="crumb"><a href="../index.html">Disaster Data</a> / States</p>'
        '<h1>FEMA Disaster Declarations by State</h1>'
        '<p class="lede">'
        'Every US state, the District of Columbia, and the territories, ranked by '
        'federal disaster and emergency declarations since FY2000 (data as of %s). '
        '%d declarations in all. Select a state for its full history, hazard breakdown, '
        'denial rate, and most recent declarations.'
        '</p>'
        '<ol class="rank">%s</ol>'
        '%s'
        '</div></main>'
        '%s'
        '</body></html>'
        % (
            e(desc), SITE, e(desc), SITE,
            HEAD,
            header_html(),
            ddate, total, rows,
            method_html(ddate),
            footer_html(),
        )
    )


# =========================================================================
# Sitemap and robots.txt
# =========================================================================

def render_sitemap(states):
    # lastmod is derived from real data (most recent declaration per state),
    # so the sitemap only changes when FEMA data does -- no spurious weekly commits.
    def latest_date(s):
        recs = s.get("recent", [])
        dates = [r.get("declarationDate", "")[:10]
                 for r in recs if r.get("declarationDate")]
        return max(dates) if dates else None

    overall = max(
        (d for d in (latest_date(s) for s in states) if d),
        default=datetime.date.today().isoformat(),
    )

    def u(loc, lm):
        return "<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (loc, lm or overall)

    parts = [
        u("%s/"                                % SITE, overall),
        u("%s/map.html"                        % SITE, overall),
        u("%s/about.html"                      % SITE, overall),
        u("%s/public-assistance-projects.html" % SITE, overall),
        u("%s/states/"                         % SITE, overall),
    ]
    for s in states:
        parts.append(
            u("%s/states/%s.html" % (SITE, s["slug"]), latest_date(s) or overall)
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
        % "".join(parts)
    )


def render_robots():
    return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % SITE


# =========================================================================
# Main
# =========================================================================

def main():
    src_type, data = load_data()

    if src_type == "live":
        rows = build_states_live(data)
    else:
        rows = build_states_fallback(data)

    # Sort descending by declaration count; break ties by name
    rows.sort(key=lambda s: (-s["decl"], s["name"]))
    for i, s in enumerate(rows):
        s["rank"] = i + 1

    os.makedirs(STATES_DIR, exist_ok=True)

    # Per-state pages
    for s in rows:
        path = os.path.join(STATES_DIR, s["slug"] + ".html")
        open(path, "w", encoding="utf-8").write(render_state_page(s, rows))

    # Hub
    open(os.path.join(STATES_DIR, "index.html"), "w", encoding="utf-8").write(
        render_hub(rows)
    )

    # Root-level sitemap + robots.txt
    open(os.path.join(OUT_ROOT, "sitemap.xml"), "w", encoding="utf-8").write(
        render_sitemap(rows)
    )
    open(os.path.join(OUT_ROOT, "robots.txt"), "w", encoding="utf-8").write(
        render_robots()
    )

    total = sum(s["decl"] for s in rows)
    ddate = rows[0].get("ddate", "") if rows else ""
    lcfy  = rows[0].get("lcfy",  0) if rows else 0

    print("[gen] wrote %d state pages + hub + sitemap  (source: %s)"
          % (len(rows), src_type))
    print("[gen] national total: %d declarations  (data as of %s, complete FY through FY%d)"
          % (total, ddate, lcfy))


if __name__ == "__main__":
    main()
