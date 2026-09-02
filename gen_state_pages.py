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
from dd_classify import classify

SITE = "https://disasterdata.io"
OUT_ROOT = os.environ.get("DD_OUT", ".")           # repo root (output)
SRC_ROOT = os.environ.get("DD_SRC", OUT_ROOT)      # where data.js / index.html live
STATES_DIR = os.path.join(OUT_ROOT, "states")

# ---------------------------------------------------------------- data loading
def _grab(text, name):
    """Pull a baked `let NAME = ...;` JSON literal out of index.html (fallback only)."""
    m = re.search(r"(?:let|var)\s+" + name + r"\s*=\s*(\[.*?\]|\{.*?\});", text, re.S)
    if not m:
        raise SystemExit("could not find %s" % name)
    return json.loads(m.group(1))

def _grab_js(text, name):
    """Pull a live `window.NAME = <json>;` value out of data.js (handles nesting + padding)."""
    m = re.search(r"window\." + re.escape(name) + r"\s*=\s*", text)
    if not m:
        raise ValueError("could not find window.%s" % name)
    return json.JSONDecoder().raw_decode(text, m.end())[0]

def build_from_live(text):
    """Reconstruct (STATES, DECLS, DENS, YOY, KEEP) from the live data.js variables.
    KEEP[ab] = {"ids": set of declaration strings that land on a jurisdiction page,
    "n": number of jurisdiction pages} -- used to find declarations that belong to
    no single locality (shown on the statewide page instead)."""
    names   = _grab_js(text, "STATE_NAMES")
    browse  = _grab_js(text, "BROWSE")
    denials = _grab_js(text, "DENIALS")
    summary = _grab_js(text, "SUMMARY")
    try:
        loc = _grab_js(text, "LOCALITY_DATA")
    except Exception:
        loc = {}
    KEEP = {}
    for ab, entries in loc.items():
        ids, n = set(), 0
        for en in entries:
            if classify(ab, en["n"])["keep"]:
                n += 1
                ids.update(en.get("ids", []))
        KEEP[ab] = {"ids": ids, "n": n}
    DECLS, DENS, day_sum, day_n = {}, {}, {}, {}
    for r in browse:
        ab = r["state"]
        DECLS.setdefault(ab, []).append([
            r.get("femaDeclarationString", ""), r.get("declarationType", ""),
            r.get("incidentType", ""), r.get("declarationDate", ""),
            r.get("declarationTitle", "")])
        d = r.get("days_to_approve")
        if isinstance(d, (int, float)):
            day_sum[ab] = day_sum.get(ab, 0) + d
            day_n[ab]   = day_n.get(ab, 0) + 1
    for d in denials:
        ab = d.get("stateAbbreviation", "")
        DENS.setdefault(ab, []).append([
            d.get("declarationRequestNumber", ""), d.get("declarationRequestType", ""),
            d.get("requestedIncidentTypes", ""), d.get("declarationRequestDate", "")])
    STATES = [{"ab": ab, "name": nm,
               "days": round(day_sum[ab] / day_n[ab], 1) if day_n.get(ab) else 0}
              for ab, nm in names.items()]
    YOY = [[row["fyDeclared"], row["declarations"]] for row in summary.get("yoy", [])]
    return STATES, DECLS, DENS, YOY, KEEP

def load_data():
    # live data.js first (fresh weekly data); baked index.html only as a fallback
    p = os.path.join(SRC_ROOT, "data.js")
    if os.path.exists(p):
        try:
            return build_from_live(open(p, encoding="utf-8").read())
        except Exception as e:
            print("live data.js unreadable (%s); falling back to index.html" % e)
    p = os.path.join(SRC_ROOT, "index.html")
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read()
        return (_grab(t, "STATES"), _grab(t, "DECLS"), _grab(t, "DENS"), _grab(t, "YOY"), {})
    raise SystemExit("no data.js or index.html found")

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

# ---------------------------------------------------------------- last complete FY
def last_complete_fy(YOY):
    now = datetime.date.today()
    cur_fy = now.year + 1 if now.month >= 10 else now.year
    avail = max((y for y, _ in YOY), default=cur_fy)
    return min(cur_fy - 1, avail)

# ---------------------------------------------------------------- provenance stamp
def provenance_stamp_html(lcfy):
    """A compact, unmistakable line pairing every totals figure with the fiscal
    years it covers and the date this page was last rebuilt. Placed beside the
    stat cards themselves, not just in the methodology section further down,
    so the coverage window travels with the number even if a reader never
    scrolls that far."""
    as_of = datetime.date.today().strftime("%b %-d, %Y")
    return ('<p class="prov-stamp" style="font:500 .82rem/1.5 \'Public Sans\',sans-serif;'
            'color:#6b6357;margin:.4rem 0 1.1rem">'
            'Totals: FY2000&ndash;FY%d &middot; Page last rebuilt %s '
            '&middot; the current in-progress fiscal year is not included in totals</p>'
            % (lcfy, as_of))

# ---------------------------------------------------------------- per-state stats
def state_stats(ab, name, days, decls, dens, lcfy, keep):
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
    keep_ids = keep.get("ids", set())
    orphans = sorted([r for r in complete if r[0] not in keep_ids],
                     key=lambda r: r[3], reverse=True)
    return {
        "ab": ab, "name": name, "slug": slugify(name),
        "decl": decl, "dr": by_type["DR"], "em": by_type["EM"], "fm": by_type["FM"],
        "den": den, "rate": rate, "days": days,
        "hazards": hazards, "recent": recent,
        "history": sorted(complete, key=lambda r: r[3], reverse=True),
        "recent_dens": sorted(den_c, key=lambda d: d[3], reverse=True)[:10],
        "orphans": orphans, "jur_n": keep.get("n", 0),
    }

# ---------------------------------------------------------------- CSS
CSS = """
:root{--teal:#004c53;--cream:#f6f1e7;--paper:#fffdf7;--ink:#2b2b2b;--ink3:#6b6357;--rule:#e4dccb}
*{box-sizing:border-box}
body{margin:0;background:var(--cream);color:var(--ink);font-family:'Public Sans',system-ui,-apple-system,sans-serif;line-height:1.6}
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
.decl-filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:.2rem 0 .5rem}
.decl-chip{font:700 .82rem/1 'Public Sans',sans-serif;color:var(--teal);background:var(--paper);border:1px solid var(--rule);border-radius:999px;padding:.42rem .72rem;cursor:pointer;display:inline-flex;align-items:center;gap:.42rem}
.decl-chip .n{background:#eef3f2;border-radius:999px;padding:.06rem .44rem;font-size:.76rem;font-weight:700}
.decl-chip[aria-pressed="true"]{background:var(--teal);color:#fff;border-color:var(--teal)}
.decl-chip[aria-pressed="true"] .n{background:rgba(255,255,255,.22);color:#fff}
.decl-chip.off{opacity:.42;cursor:default}
.decl-count{font-size:.82rem;color:var(--ink3);margin:.05rem 0 .55rem}
.tablewrap.scroll{max-height:460px;overflow-y:auto}
.tablewrap.scroll thead th{position:sticky;top:0;z-index:1}
tr.hide{display:none}
th.sortable{cursor:pointer;user-select:none;-webkit-user-select:none;white-space:nowrap}
th.sortable::after{content:"↕";opacity:.32;margin-left:.35em;font-weight:400}
th.sortable:hover{color:var(--teal)}
th[aria-sort="ascending"]::after{content:"↑";opacity:.95}
th[aria-sort="descending"]::after{content:"↓";opacity:.95}
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
nav.ddnav .navburger{display:none;flex-direction:column;justify-content:center;gap:5px;width:40px;height:40px;background:none;border:0;cursor:pointer;padding:8px;border-radius:8px}
nav.ddnav .navburger span{display:block;height:2px;width:100%;background:#1d1813;border-radius:2px;transition:.2s}
nav.ddnav .navburger[aria-expanded="true"] span:nth-child(1){transform:translateY(7px) rotate(45deg)}
nav.ddnav .navburger[aria-expanded="true"] span:nth-child(2){opacity:0}
nav.ddnav .navburger[aria-expanded="true"] span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}
.mobilemenu{display:none}
@media(max-width:720px){nav.ddnav{flex-direction:row;align-items:center;justify-content:space-between;height:60px;padding-top:0;padding-bottom:0}nav.ddnav .navmeta{display:none}nav.ddnav .navlinks{display:none !important}nav.ddnav .navburger{display:flex}
.mobilemenu:not([hidden]){display:flex;flex-direction:column;gap:2px;padding:10px clamp(18px,4vw,48px) 18px;background:#f6f1e7;border-bottom:1px solid #e0d8c5;position:sticky;top:60px;z-index:49}
.mobilemenu>a{font-size:15px;font-weight:500;color:#1d1813;text-decoration:none;padding:11px 12px;border-radius:8px}
.mobilemenu>a.on{color:#004c53;background:#d7e9ea}
.mm-section{display:flex;flex-direction:column;gap:2px;padding:6px 0;margin:2px 0;border-top:1px solid #e0d8c5}
.mm-label{font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#938a78;padding:6px 12px 2px}
.mm-section a{font-size:15px;font-weight:500;color:#5b5346;text-decoration:none;padding:10px 12px 10px 22px;border-radius:8px}
.mm-section a.on{color:#004c53;background:#d7e9ea}}
""".strip()

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;'
         '9..144,400;9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@300;400;500;600;700'
         '&display=swap" rel="stylesheet">')

HEAD = FONTS + "<style>" + CSS + "</style>"

def header_html():
    # use the site-wide canonical header; nav.js injects it and marks the active page
    return '<script src="/nav.js"></script>'

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
            '<a href="https://forms.gle/NZ6bSadoXrKYHjjH8" target="_blank" rel="noopener">Report a data issue</a>'
            ' &middot; <a href="../about.html">About and contact</a></div></footer>'
            '<!-- Cloudflare Web Analytics --><script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            'data-cf-beacon=\'{"token": "ceea2416f66a424981ba37fcb9440d68"}\'></script>'
            '<!-- End Cloudflare Web Analytics -->'
            '<script>(function(){var b=document.querySelector(".navburger"),m=document.querySelector(".mobilemenu");'
            'if(b&&m){b.addEventListener("click",function(){var o=b.getAttribute("aria-expanded")==="true";'
            'b.setAttribute("aria-expanded",String(!o));if(o){m.setAttribute("hidden","");}else{m.removeAttribute("hidden");}});}})();</script>')


# ---------------------------------------------------------------- per-state page
# ---- funding helpers: state-level Individual Assistance + Hazard Mitigation ----
# State pages aggregate their jurisdictions. hma.json / ia.json are keyed
# {ST: {jurisdiction: {...}}}, so summing a state's entries gives its totals with
# no new fetch. Both sections degrade to nothing when the file or the state's data
# is absent (IA in particular exists only where it was designated).

def money(n):
    n = float(n or 0)
    if n >= 1e9: return ("$%.1fB" % (n / 1e9)).replace(".0B", "B")
    if n >= 1e6: return "$%dM" % round(n / 1e6)
    if n >= 1e3: return "$%dK" % round(n / 1e3)
    return "$%d" % round(n)

def num(n):
    return "{:,}".format(int(round(float(n or 0))))

HMA_PROG_LABELS = {
    "HMGP": "Hazard Mitigation Grant Program",
    "HMGP POST FIRE": "Hazard Mitigation Grant Program (Post Fire)",
    "FMA": "Flood Mitigation Assistance",
    "FMA SWIFT CURRENT": "Flood Mitigation Assistance Swift Current",
    "BRIC": "Building Resilient Infrastructure and Communities",
    "PDM": "Pre-Disaster Mitigation",
    "LPDM": "Legislative Pre-Disaster Mitigation",
    "RFC": "Repetitive Flood Claims",
    "SRL": "Severe Repetitive Loss",
}

def _load_json(fname):
    p = os.path.join(SRC_ROOT, fname)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def load_hma():
    return _load_json("hma.json")

def load_ia():
    return _load_json("ia.json")

def agg_hma(state_dict):
    fed = n = props = 0
    prog = {}
    for rec in (state_dict or {}).values():
        fed += rec.get("fed", 0); n += rec.get("n", 0); props += rec.get("props", 0)
        for code, v in (rec.get("prog") or {}).items():
            p = prog.setdefault(code, [0, 0]); p[0] += v[0]; p[1] += v[1]
    return {"fed": fed, "n": n, "props": props, "prog": prog} if (fed or n) else {}

def agg_ia(state_dict):
    o = {"reg": 0, "app": 0, "ihp": 0, "rr": 0, "rent": 0, "ona": 0}
    for rec in (state_dict or {}).values():
        for k in o:
            o[k] += rec.get(k, 0)
    return o if (o["reg"] or o["ihp"]) else {}

def state_ia_html(s):
    ia = s.get("ia") or {}
    if not ia or not (ia.get("reg") or ia.get("ihp")):
        return ""
    e = html.escape
    tiles = [(num(ia["reg"]), "Valid registrations"),
             (num(ia["app"]), "Households approved"),
             (money(ia["ihp"]), "Total IHP approved")]
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % (v, l)
                    for v, l in tiles)
    parts = [("Repair and replacement", ia.get("rr", 0)),
             ("Rental assistance", ia.get("rent", 0)),
             ("Other needs", ia.get("ona", 0))]
    body = "".join("<tr><td>%s</td><td>%s</td></tr>" % (lbl, money(amt))
                   for lbl, amt in parts if amt > 0)
    table = ('<div class="tablewrap"><table><thead><tr><th>Assistance type</th>'
             '<th>Approved amount</th></tr></thead><tbody>%s</tbody></table></div>' % body) if body else ""
    return ('<h2>Individual Assistance to households</h2>'
            '<p>FEMA Individual Assistance to households across %s, combined across the Housing '
            'Assistance owner and renter programs. Valid registrations are households that applied '
            'within a designated Individual Assistance area; approved figures are those FEMA found '
            'eligible under the Individuals and Households Program. Self-reported, drawn from NEMIS '
            'through OpenFEMA, and present only where Individual Assistance was designated.</p>'
            '<div class="stats">%s</div>%s' % (e(s["name"]), stats, table))

def state_hma_html(s):
    hma = s.get("hma") or {}
    if not hma or not hma.get("fed"):
        return ""
    e = html.escape
    tiles = [(money(hma["fed"]), "Federal mitigation share"),
             (num(hma["n"]), "Projects funded"),
             (num(hma["props"]), "Properties mitigated")]
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % (v, l)
                    for v, l in tiles)
    progs = sorted((hma.get("prog") or {}).items(), key=lambda kv: -kv[1][0])
    body = "".join(
        '<tr><td>%s <span style="color:#938a78">(%s)</span></td><td>%s</td><td>%s</td></tr>'
        % (e(HMA_PROG_LABELS.get(c, c)), e(c), num(v[1]), money(v[0]))
        for c, v in progs)
    table = ('<div class="tablewrap"><table><thead><tr><th>Program</th><th>Projects</th>'
             '<th>Federal share obligated</th></tr></thead><tbody>%s</tbody></table></div>' % body)
    return ('<h2>Hazard mitigation funded</h2>'
            '<p>Federal Hazard Mitigation Assistance obligated across %s to reduce future disaster '
            'losses, by program. Figures are federal share obligated, reported through OpenFEMA and '
            'not audited.</p>'
            '<div class="stats">%s</div>%s' % (e(s["name"]), stats, table))


def render_state_page(s, states, lcfy):
    name, ab, slug = s["name"], s["ab"], s["slug"]
    canonical = "%s/states/%s.html" % (SITE, slug)
    e = html.escape
    desc = ("%s has recorded %d federal disaster and emergency declarations since FY2000: "
            "%d major disasters, %d emergencies, and %d fire-management declarations. "
            "Declaration-request denial rate %.1f%%. Full FEMA declaration history, mapped and ranked."
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
             ("%d" % s["den"], "Declaration requests denied"),
             ("%.1f%%" % s["rate"], "Declaration-request denial rate"),
             ("#%d" % s["rank"], "National rank by declarations")]
    if isinstance(s["days"], (int, float)) and s["days"] > 0:
        cards.append(("%.1f" % s["days"], "Avg days to a decision"))
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>'
                    % (v, l) for v, l in cards)

    # hazards
    haz = "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in s["hazards"][:8]) \
          or '<li>None recorded</li>'

    # recent declarations
    # Full declaration record (complete fiscal years), most recent first. data-t drives the filter.
    rows = "".join(
        "<tr data-t=\"%s\"><td data-s=\"%s\">%s</td><td data-s=\"%s\">%s</td><td><span class='tag' title='%s'>%s</span></td>"
        "<td>%s</td><td>%s</td></tr>"
        % (e(r[1]), e(r[3][:10]), fmt_date(r[3]), decl_num(r[0]), e(r[0]),
           TYPE_LONG.get(r[1], r[1]), e(r[1]),
           e(r[2]), e(pretty_title(r[4])))
        for r in s["history"])
    wrap_cls = "tablewrap scroll" if len(s["history"]) > 12 else "tablewrap"
    recent_tbl = ('<div id="declbox">'
                  '<p class="legend" style="font-size:.82rem;color:#6b6357;margin:.5rem 0 .6rem">'
                  '<b style="color:#004c53">DR</b> = Major disaster (Stafford Act) &middot; '
                  '<b style="color:#004c53">EM</b> = Emergency declaration &middot; '
                  '<b style="color:#004c53">FM</b> = Fire management assistance</p>'
                  + type_chips(s["decl"], s["dr"], s["em"], s["fm"]) +
                  '<p class="decl-count" aria-live="polite">Showing %d declarations</p>' % s["decl"] +
                  '<div class="' + wrap_cls + '"><table><thead><tr>'
                  '<th class="sortable" data-k="date">Date</th>'
                  '<th class="sortable" data-k="num">Number</th>'
                  '<th class="sortable" data-k="text">Type</th>'
                  '<th class="sortable" data-k="text">Hazard</th>'
                  '<th class="sortable" data-k="text">Title</th>'
                  '</tr></thead><tbody>'
                  + rows + '</tbody></table></div></div>' + FILTER_JS)

    # denials
    if s["den"]:
        dn_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                          % (fmt_date(d[3]), e(d[1]), e(d[2])) for d in s["recent_dens"])
        denials = ('<p>FEMA turned down <b>%d</b> declaration request%s from %s since FY2000, '
                   'a declaration-request denial rate of <b>%.1f%%</b>. This is the President denying a '
                   'governor or tribal leader\'s <em>request</em> for a declaration, tracked in a separate '
                   'FEMA dataset from approved declarations, and is not the same thing as an individual '
                   'being denied assistance under an approved declaration.</p>'
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

    # link down to the per-jurisdiction hub for this state
    jlink = ('<p class="jlink"><a href="%s/"><b>Browse all %d jurisdictions in %s</b>, each with '
             'its full declaration history and a ready-to-use mitigation-plan table &rarr;</a></p>'
             % (slug, s["jur_n"], e(name))) if s.get("jur_n") else ''

    # declarations that belong to no single locality -> listed here, on the state page
    if s["orphans"]:
        orows = "".join(
            "<tr><td>%s</td><td>%s</td><td><span class='tag' title='%s'>%s</span></td>"
            "<td>%s</td><td>%s</td></tr>"
            % (fmt_date(r[3]), e(r[0]), TYPE_LONG.get(r[1], r[1]), e(r[1]),
               e(r[2]), e(pretty_title(r[4])))
            for r in s["orphans"])
        n = len(s["orphans"])
        orphan_html = ('<h2>Declarations not attributed to a specific locality</h2>'
                       '<p>%d declaration%s in %s applied statewide, or to areas FEMA did not tie '
                       'to a single county or equivalent, such as wildfire management zones. They '
                       'are included in the state totals above but do not appear on any individual '
                       'jurisdiction page.</p>'
                       '<div class="tablewrap"><table><thead><tr><th>Date</th><th>Number</th>'
                       '<th>Type</th><th>Hazard</th><th>Title</th></tr></thead><tbody>%s'
                       '</tbody></table></div>'
                       % (n, "" if n == 1 else "s", e(name), orows))
    else:
        orphan_html = ''

    ia_sec  = state_ia_html(s)
    hma_sec = state_hma_html(s)

    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Disaster Data | %s FEMA Disaster Declarations: Federal Disaster History Since FY2000</title>'
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
            '%s'
            '<div class="stats">%s</div>'
            '%s'
            '<h2>Most common hazards</h2><ul class="haz">%s</ul>'
            '<h2>All declarations on record</h2>%s'
            '%s%s'
            '<h2>Denied requests</h2>%s'
            '%s'
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
               e(name), e(name), lede, provenance_stamp_html(lcfy), stats, jlink, haz, recent_tbl, ia_sec, hma_sec, denials, orphan_html,
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
            '<title>Disaster Data | FEMA Disaster Declarations by State (FY2000 to present)</title>'
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
            '%d declarations in all. Select a state for its full history, hazard breakdown, '
            'declaration-request denial rate, and most recent declarations.</p>'
            '%s'
            '<ol class="rank">%s</ol>'
            '%s</div></main>%s</body></html>'
            % (e(desc), SITE, e(desc), SITE, HEAD, header_html(),
               lcfy, total, provenance_stamp_html(lcfy), rows, method_html(), footer_html()))


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
    STATES, DECLS, DENS, YOY, KEEP = load_data()
    lcfy = last_complete_fy(YOY)
    meta = {s["ab"]: s for s in STATES}

    rows = [state_stats(ab, m["name"], m.get("days", 0),
                        DECLS.get(ab, []), DENS.get(ab, []), lcfy,
                        KEEP.get(ab, {"ids": set(), "n": 0}))
            for ab, m in meta.items()]
    rows.sort(key=lambda s: -s["decl"])
    for i, s in enumerate(rows):
        s["rank"] = i + 1

    HMA, IA = load_hma(), load_ia()
    for s in rows:
        s["hma"] = agg_hma(HMA.get(s["ab"], {}))
        s["ia"]  = agg_ia(IA.get(s["ab"], {}))

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
