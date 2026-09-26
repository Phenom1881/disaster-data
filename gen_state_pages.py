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
from urllib.parse import quote
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
    """Reconstruct (STATES, DECLS, DENS, YOY, KEEP, PA) from the live data.js variables.
    KEEP[ab] = {"ids": set of declaration strings that land on a jurisdiction page,
    "n": number of jurisdiction pages} -- used to find declarations that belong to
    no single locality (shown on the statewide page instead).
    PA = PA_BY_COUNTY, {ST: {county: [obligated, projects, topCat, cats]}}; the same
    figure the jurisdiction pages show, so a state and its counties never disagree."""
    names   = _grab_js(text, "STATE_NAMES")
    browse  = _grab_js(text, "BROWSE")
    denials = _grab_js(text, "DENIALS")
    summary = _grab_js(text, "SUMMARY")
    try:
        loc = _grab_js(text, "LOCALITY_DATA")
    except Exception:
        loc = {}
    try:
        pa_county = _grab_js(text, "PA_BY_COUNTY")
    except Exception:
        pa_county = {}
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
    return STATES, DECLS, DENS, YOY, KEEP, pa_county

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
        return (_grab(t, "STATES"), _grab(t, "DECLS"), _grab(t, "DENS"), _grab(t, "YOY"), {}, {})
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
            'Totals: FY2000 to FY%d &middot; Page last rebuilt %s '
            '&middot; the current in-progress fiscal year is not included in totals</p>'
            % (lcfy, as_of))

# ---------------------------------------------------------------- per-state stats
def state_stats(ab, name, days, decls, dens, lcfy, keep):
    # Two different jobs, deliberately kept apart.
    #
    # COUNTS (stat cards, lede, rank, hazard tallies, denial rate) use complete
    # fiscal years only, so a year that is still under way can never make one
    # state look quieter than another or move a rank mid-year.
    #
    # LISTS (the declaration table and the not-tied-to-a-locality table) show
    # every declaration FEMA has published, including the in-progress year, so a
    # declaration made last month is on the page the week it appears in OpenFEMA
    # instead of after Sep 30. Those rows carry no tag (a tag read as "still open") and are left out
    # of every total. Before this split the table was built from the complete-year
    # list, which hid every declaration made since Oct 1.
    complete = [r for r in decls if fy_of(r[3]) <= lcfy]
    open_rows = sorted([r for r in decls if fy_of(r[3]) > lcfy],
                       key=lambda r: r[3], reverse=True)
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
    listed = sorted(decls, key=lambda r: r[3], reverse=True)
    list_type = {"DR": 0, "EM": 0, "FM": 0}
    for r in listed:
        list_type[r[1]] = list_type.get(r[1], 0) + 1
    keep_ids = keep.get("ids", set())
    orphans = sorted([r for r in decls if r[0] not in keep_ids],
                     key=lambda r: r[3], reverse=True)
    # The "recent declarations" panel uses a rolling 12 months, not the fiscal
    # year, so an event declared in August stays in view after Oct 1 while its
    # recovery money is still moving.
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    recent12 = [r for r in listed if (r[3] or "")[:10] >= cutoff]
    return {
        "ab": ab, "name": name, "slug": slugify(name),
        "decl": decl, "dr": by_type["DR"], "em": by_type["EM"], "fm": by_type["FM"],
        "den": den, "rate": rate, "days": days,
        "hazards": hazards, "recent": recent,
        "history": listed,
        "list_n": len(listed), "list_dr": list_type["DR"],
        "list_em": list_type["EM"], "list_fm": list_type["FM"],
        "open_rows": open_rows, "open_n": len(open_rows), "recent12": recent12,
        "open_fys": sorted({fy_of(r[3]) for r in open_rows}),
        "recent_dens": sorted(den_c, key=lambda d: d[3], reverse=True)[:10],
        "orphans": orphans, "jur_n": keep.get("n", 0),
    }


# ---------------------------------------------------------------- in-progress year
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
.fy-note{font-size:.84rem;color:var(--ink3);background:#fdf8f3;border:1px solid #efdccd;border-radius:10px;padding:.55rem .8rem;margin:.1rem 0 .6rem;max-width:72ch}
.nowfy{background:#fffaf5;border:1px solid #efdccd;border-radius:14px;padding:1.1rem 1.25rem;margin:1.6rem 0}
.nowfy h2{margin:.15rem 0 .5rem}
.nowfy .kick{font:700 .7rem/1.2 'Public Sans',sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#8f3f1a;margin:0}
.nowfy>p{max-width:70ch;margin:.2rem 0 .8rem;font-size:.95rem}
.nowfy .stats{margin:.9rem 0 1rem}
.nowfy .stat{background:#fff}
.nowfy td small{display:block;color:var(--ink3);font-size:.76rem;margin-top:.15rem}
.nowfy .nowfy-na{color:var(--ink3);font-size:.82rem}
.nowfy p.cmp{font-size:.93rem;margin:.9rem 0 0}
.nowfy p.src{font-size:.8rem;color:var(--ink3);margin:.7rem 0 0}
.tablewrap.scroll{max-height:460px;overflow-y:auto}
.tablewrap.scroll thead th{position:sticky;top:0;z-index:1}
tr.hide{display:none}
th.sortable{cursor:pointer;user-select:none;-webkit-user-select:none;white-space:nowrap}
th.sortable::after{content:"↕";opacity:.32;margin-left:.35em;font-weight:400}
th.sortable:hover{color:var(--teal)}
th[aria-sort="ascending"]::after{content:"↑";opacity:.95}
th[aria-sort="descending"]::after{content:"↓";opacity:.95}
.pasplit{margin:1.6rem 0}
.pasplit h2{margin-top:0}
.patotal{font-size:1.02rem;margin:.2rem 0 .8rem;font-variant-numeric:tabular-nums}
.patotal b{color:var(--teal)}
.pabar{display:flex;height:12px;border-radius:4px;overflow:hidden;margin:0 0 .7rem}
.pabar span{display:block;min-width:2px}
.paline{font-size:.92rem;margin:0 0 .6rem;max-width:68ch;font-variant-numeric:tabular-nums}
.paline b{color:var(--teal)}
.panote{font-size:.82rem;color:var(--ink3);margin:0;max-width:68ch}
.kinds{background:var(--paper);border:1px solid var(--rule);border-radius:12px;padding:.9rem 1.2rem;margin:.6rem 0 1rem;font-size:.9rem}
.kinds p{margin:.35rem 0}
.kinds b{color:var(--teal)}
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
            '(Oct 1 to Sep 30). Totals, ranks, and rates on this page cover complete fiscal years '
            'only. Declarations from the fiscal year still in progress are listed in each '
            'state\'s declaration tables and its recent-declarations panel, but '
            'are not counted in any total until the year is complete. '
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

def load_pa_timing():
    """Per (county, disaster) obligation rows written by build.py. Shape:
    {ST: {county: {disasterNumber: [declDate, firstObl, lastObl, obligated, topCat]}}}.
    Returns {} when the file is absent, same graceful degradation as hma/ia."""
    return _load_json("pa-timing.json")

def load_ia_timing():
    """Per (county, disaster) Individual Assistance written by build.py. Shape:
    {ST: {rawCounty: {disasterNumber: [reg, app, ihp, rr, rent, ona]}}}, where
    rawCounty is OpenFEMA's "Name (Type)" string. Returns {} when absent."""
    return _load_json("ia-timing.json")

def load_event_ids():
    """{disasterNumber: eventId} from events.json, the same event index
    disaster.html reads, so every "full event profile" link resolves to a real
    profile. (The Compare index in data/decl-index is not used for this: its
    eventId disagrees with events.json for about 2% of declarations.) The weekly
    workflow rebuilds events.json after this script runs, so a declaration that is
    brand new this week gets its link on the following build; every other
    declaration links right away. A missing or unreadable file means no links."""
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

# Public Assistance, split by the kind of declaration the money followed.
#
# The headline total comes from PA_BY_COUNTY, which is the same figure the
# jurisdiction pages show, so a state page and its counties can never disagree.
# The split comes from pa-timing.json, the only source carrying a disaster number
# per obligation. Those are two separate passes in build.py and nothing guarantees
# they sum to the same number, so anything the split cannot account for is
# reported as an explicit residual instead of being quietly dropped. The segments
# always add up to the headline by construction.
def state_pa(decls, pa_county_state, pa_timing_state):
    total = 0.0
    for v in (pa_county_state or {}).values():
        try:
            total += float(v[0] or 0)
        except (TypeError, ValueError, IndexError):
            continue

    # disaster number -> (declaration type, incident type), from this state's own
    # declaration records; same digit-extraction join the jurisdiction pages use.
    meta = {}
    for r in decls:
        m = re.search(r"(\d+)", r[0] or "")
        if m:
            meta[m.group(1)] = (r[1] or "", r[2] or "")

    buckets = {"dr": 0.0, "em": 0.0, "fm": 0.0, "covid": 0.0}
    attributed = 0.0
    for county in (pa_timing_state or {}).values():
        for dn, v in (county or {}).items():
            try:
                obl = float(v[3] or 0)
            except (TypeError, ValueError, IndexError):
                continue
            if obl <= 0:
                continue
            dtype, itype = meta.get(str(dn), ("", ""))
            if itype == "Biological":     # every COVID declaration, DR and EM alike
                key = "covid"
            elif dtype == "DR":
                key = "dr"
            elif dtype == "EM":
                key = "em"
            elif dtype == "FM":
                key = "fm"
            else:
                continue                  # unknown declaration -> left in the residual
            buckets[key] += obl
            attributed += obl

    if attributed > total:
        # the timing file accounts for more than the county totals; report the
        # larger figure so the bar can never exceed its own stated total
        total = attributed

    resid = total - attributed
    if resid < 1:
        resid = 0.0

    out = {"total": total, "attributed": attributed, "resid": resid}
    out.update(buckets)
    return out

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

def pa_split_html(s, name):
    """Headline Public Assistance for the state, with the money split by the kind of
    declaration it followed. Renders nothing when the state has no PA on record, and
    each segment renders only when it is non-zero, so a state with no fire management
    grants never sees an empty sliver."""
    pa = s.get("pa") or {}
    total = float(pa.get("total") or 0)
    if total <= 0:
        return ""

    segs = [(k, col, lab, float(pa.get(k) or 0))
            for k, col, lab in PA_SEGS if float(pa.get(k) or 0) > 0]
    if not segs:
        return ""

    bar = "".join('<span style="flex:%.5f;background:%s" title="%s %s"></span>'
                  % (v / total, col, money(v), lab)
                  for _k, col, lab, v in segs)

    clauses = []
    for k, _col, _lab, v in segs:
        if k == "covid":
            clauses.append("<b>%s</b>, or %d%% of the total, was COVID-19, which every "
                           "state and county in the country received."
                           % (money(v), round(100.0 * v / total)))
        else:
            clauses.append(PA_CLAUSE[k] % money(v))

    return ('<section class="pasplit">'
            '<h2>Federal Public Assistance obligated</h2>'
            '<p class="patotal"><b>%s</b> has been obligated to %s in Public Assistance '
            'since FY2000.</p>'
            '<div class="pabar">%s</div>'
            '<p class="paline">%s</p>'
            '<p class="panote">Obligated is the committed share, not necessarily spent, '
            'and can be revised as projects close out. Totals are summed from funded '
            'localities, so a declaration administered entirely at state level may not '
            'appear here.</p>'
            '</section>'
            % (money(total), name, bar, " ".join(clauses)))

# ---------------------------------------------------------------- recent declarations
# The "right now" view: every declaration from the past 12 months, with
# the Individual Assistance and Public Assistance FEMA has reported for it to
# date, and a plain-language comparison against the state's earlier disasters.
# Built only from sidecars build.py already writes (ia-timing.json and
# pa-timing.json, summed across the state's counties by disaster number), so it
# needs no new fetch and renders nothing when a file or the data is absent.
# None of it feeds a total, rank, or rate on the page.

def money1(n):
    """One decimal in millions and billions ($108.6M rather than $109M), for
    amounts that are still moving week to week."""
    n = float(n or 0)
    if n >= 1e9: return ("$%.1fB" % (n / 1e9)).replace(".0B", "B")
    if n >= 1e6: return ("$%.1fM" % (n / 1e6)).replace(".0M", "M")
    if n >= 1e3: return "$%dK" % round(n / 1e3)
    return "$%d" % round(n)

def ia_by_dn(ia_timing_state):
    """{disasterNumber: [reg, app, ihp, rr, rent, ona, areas]} summed over a state's
    counties from ia-timing.json. 'areas' counts the counties with data."""
    out = {}
    for per_dn in (ia_timing_state or {}).values():
        for dn, v in (per_dn or {}).items():
            try:
                vals = [float(x or 0) for x in list(v)[:6]]
            except (TypeError, ValueError):
                continue
            if len(vals) < 6:
                continue
            acc = out.setdefault(str(dn), [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0])
            for i in range(6):
                acc[i] += vals[i]
            acc[6] += 1
    return out

def pa_by_dn(pa_timing_state):
    """{disasterNumber: obligated federal share} summed over a state's counties from
    pa-timing.json (index 3 of each entry)."""
    out = {}
    for per_dn in (pa_timing_state or {}).values():
        for dn, v in (per_dn or {}).items():
            try:
                obl = float(v[3] or 0)
            except (TypeError, ValueError, IndexError):
                continue
            if obl > 0:
                out[str(dn)] = out.get(str(dn), 0.0) + obl
    return out

def dn_meta(decls):
    """{disasterNumber: (declaration string, type, incident type, date)}."""
    return {decl_num(r[0]): (r[0], r[1], r[2], r[3]) for r in decls}

def _nowfy_ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suf)

def nowfy_compare_sentence(dn, app, ia_dn, meta, where):
    """One sentence placing a current declaration's households approved against every
    other disaster in the same place in FEMA's household assistance data, which begins
    in 2002. Uses household counts rather than dollars, so inflation cannot distort it.
    COVID-19 is left out because its household aid was funeral assistance, not help
    after physical damage. Returns (sentence, covid_was_excluded)."""
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
        return ("%s has approved %s households for assistance so far, the first %s disaster "
                "with approved households in %s." % (own, num(app), where, data)), covid
    others.sort(reverse=True)
    top_app, top_dn = others[0]
    tm = meta.get(top_dn)
    top_lbl = tm[0] if tm else "disaster number %s" % top_dn
    top_yr = (" in %s" % tm[3][:4]) if (tm and tm[3]) else ""
    if app > top_app:
        ratio = float(app) / top_app
        more = ("more than three times as many as" if ratio >= 3 else
                "more than twice as many as" if ratio >= 2 else "more than")
        return ("%s has already approved %s households for assistance, %s any other %s "
                "disaster in %s. The previous high was %s%s, with %s."
                % (own, num(app), more, where, data, top_lbl, top_yr, num(top_app))), covid
    if app == top_app:
        return ("%s has approved %s households for assistance so far, tied with %s%s for "
                "the most of any %s disaster in %s."
                % (own, num(app), top_lbl, top_yr, where, data)), covid
    rank = 1 + sum(1 for a, _ in others if a > app)
    return ("%s has approved %s households for assistance so far, the %s most of any %s "
            "disaster in %s. The most was %s%s, with %s."
            % (own, num(app), _nowfy_ordinal(rank), where, data, top_lbl, top_yr,
               num(top_app))), covid

def recent_aid_html(s, lcfy):
    """The state's "recent declarations" panel: every declaration from the past 12
    months with the aid FEMA has reported for it so far. Rows from the fiscal year
    still in progress carry the same fiscal-year tag as the declaration table.
    Renders nothing when the state has no declarations in that window."""
    rows = s.get("recent12") or []
    if not rows:
        return ""
    e = html.escape
    name = s["name"]
    ia_dn = s.get("ia_dn") or {}
    pa_dn = s.get("pa_dn") or {}
    ev_ids = s.get("event_ids") or {}
    meta = s.get("dn_meta") or {}
    periods = s.get("periods") or {}
    na = '<span class="nowfy-na">%s</span>'
    na_fm = ('<span class="nowfy-na" title="Fire management declarations do not include '
             'household assistance">Not applicable</span>')

    tot_app = tot_ihp = tot_pa = 0.0
    trs, ia_hits, linked, open_fys = [], [], False, set()
    for r in rows:
        dn, t = decl_num(r[0]), r[1]
        fy = fy_of(r[3])
        is_open = fy > lcfy
        if is_open:
            open_fys.add(fy)
        ia = ia_dn.get(dn)
        pa = float(pa_dn.get(dn) or 0)
        ev = ev_ids.get(dn)
        if ev:
            linked = True
            num_html = ('<a href="../disaster.html?event=%s">%s</a>'
                        % (quote(str(ev), safe=""), e(r[0])))
        else:
            num_html = e(r[0])
        head = ('%s<small>%s &middot; %s</small>'
                % (num_html, e(TYPE_LONG.get(t, t)), e(r[2] or "")))
        declared = fmt_date(r[3]) + incident_period_html(periods.get(r[0]))
        if t == "FM":
            hh = ihp_html = na_fm
        elif ia and (ia[0] > 0 or ia[1] > 0 or ia[2] > 0):
            hh = '%s<small>of %s registered</small>' % (num(ia[1]), num(ia[0]))
            ihp_html = money1(ia[2]) if ia[2] > 0 else na % "None reported"
            tot_app += ia[1]
            tot_ihp += ia[2]
            if ia[1] > 0:
                ia_hits.append((int(round(ia[1])), dn))
        else:
            hh = ihp_html = na % "None reported"
        pa_html = money1(pa) if pa > 0 else na % "None reported yet"
        tot_pa += pa
        trs.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (head, declared, hh, ihp_html, pa_html))

    tiles = ""
    if tot_app or tot_ihp or tot_pa:
        tiles = '<div class="stats">%s</div>' % "".join(
            '<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % (v, l)
            for v, l in ((num(tot_app) if tot_app else "None yet",
                          "Households approved for assistance"),
                         (money1(tot_ihp) if tot_ihp else "None yet",
                          "Individual Assistance approved"),
                         (money1(tot_pa) if tot_pa else "None yet",
                          "Public Assistance obligated")))

    # One comparison, for the declaration with the most households approved so
    # far, so the paragraph stays short when a state has several recent events.
    cmp_html = ""
    if ia_hits:
        app, dn = max(ia_hits)
        text, covid = nowfy_compare_sentence(dn, app, ia_dn, meta, name)
        if covid:
            text += " COVID-19 funeral assistance is left out of this comparison."
        cmp_html = '<p class="cmp">%s</p>' % e(text)

    n = len(rows)
    n_open = sum(1 for r in rows if fy_of(r[3]) > lcfy)
    intro = ("%s has had %d federal declaration%s in the past 12 months. The figures are "
             "what FEMA has reported to date and grow as recovery continues. %s"
             % (e(name), n, "" if n == 1 else "s", open_fy_intro(n, n_open, open_fys)))
    src = ("Individual Assistance is FEMA's Individuals and Households Program, from "
           "OpenFEMA's Housing Assistance data for owners and renters. Public Assistance is "
           "the obligated federal share from OpenFEMA's grant award activity, which usually "
           "starts posting weeks to months after a declaration.")
    if linked:
        src += " Select a declaration number to open its full event profile."
    return ('<section class="nowfy" id="recent">'
            '<p class="kick">Past 12 months</p>'
            '<h2>Recent declarations and aid so far</h2>'
            '<p>%s</p>%s'
            '<div class="tablewrap"><table><thead><tr><th>Declaration</th><th>Declared</th>'
            '<th>Households approved</th><th>Individual Assistance</th>'
            '<th>Public Assistance obligated</th></tr></thead><tbody>%s</tbody></table></div>'
            '%s<p class="src">%s</p></section>'
            % (intro, tiles, "".join(trs), cmp_html, e(src)))

def decl_kinds_html():
    """Plain-English explanation of the three declaration types, placed with the
    declaration table it explains. The acronyms stay, demoted to the reference
    identifiers a practitioner needs rather than the label a reader must decode."""
    return ('<div class="kinds">'
            '<p><b>Major disaster (DR).</b> The big one. Opens the full toolbox: repair '
            'money for public infrastructure, help for households, and mitigation funding '
            'to reduce the next loss.</p>'
            '<p><b>Emergency (EM).</b> Narrower and usually faster, for protective work '
            'before or during an incident. Capped, and rarely brings household assistance. '
            'Nearly every state and county has one from COVID-19.</p>'
            '<p><b>Fire management (FM).</b> Cost sharing to fight a wildfire as it burns. '
            'Not a disaster declaration, and it does not open recovery programs.</p>'
            '</div>')

def render_state_page(s, states, lcfy):
    name, ab, slug = s["name"], s["ab"], s["slug"]
    canonical = "%s/states/%s.html" % (SITE, slug)
    e = html.escape
    desc = ("%s has recorded %d major disaster declarations since FY2000, plus %d emergency "
            "declarations and %d fire management declarations, %d in all. "
            "Declaration-request denial rate %.1f%%. Full FEMA declaration history, mapped and ranked."
            % (name, s["dr"], s["em"], s["fm"], s["decl"], s["rate"]))

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
    cards = [("%d" % s["dr"], "Major disasters"),
             ("%d" % s["em"], "Emergency declarations"),
             ("%d" % s["fm"], "Fire management grants"),
             ("%d" % s["decl"], "All declarations on record")]
    if float((s.get("pa") or {}).get("total") or 0) > 0:
        cards.append((money(s["pa"]["total"]), "Federal PA obligated"))
    cards += [("%d" % s["den"], "Declaration requests denied"),
              ("%.1f%%" % s["rate"], "Declaration-request denial rate"),
              ("#%d" % s["rank"], "National rank by major disasters")]
    if isinstance(s["days"], (int, float)) and s["days"] > 0:
        cards.append(("%.1f" % s["days"], "Avg days to a decision"))
    stats = "".join('<div class="stat"><div class="n">%s</div><div class="l">%s</div></div>'
                    % (v, l) for v, l in cards)

    # hazards
    haz = "".join('<li>%s <b>%d</b></li>' % (e(h), n) for h, n in s["hazards"][:8]) \
          or '<li>None recorded</li>'

    # Full declaration record, most recent first, including the in-progress fiscal
    # year (marked, and not counted in the totals above). data-t drives the filter.
    # The chips and the "Showing" line count the rows actually in the table, so a
    # filter click always shows exactly the number on its chip.

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
                  + type_chips(s["list_n"], s["list_dr"], s["list_em"], s["list_fm"])
                  + open_fy_note_html(s["open_n"], s["open_fys"]) +
                  '<p class="decl-count" aria-live="polite">Showing %d declarations</p>' % s["list_n"] +
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
        lede = ("%s has recorded <b>%d</b> major disaster declarations since FY2000 "
                "(through FY%d), the federal government's fullest response to an event. "
                "Alongside those sit %d emergency declarations and %d fire management "
                "declarations, %d in all. Its most common hazard is %s. It ranks #%d "
                "nationally by major disasters."
                % (name, s["dr"], lcfy, s["em"], s["fm"], s["decl"],
                   e(top_haz.lower()), s["rank"]))
    else:
        lede = ("%s has no federal declarations recorded in complete fiscal years through FY%d."
                % (name, lcfy))

    # other states
    grid = "".join('<a href="%s.html">%s</a>' % (o["slug"], e(o["name"]))
                   for o in states if o["ab"] != ab)

    # link down to the per-jurisdiction hub for this state
    jlink = ('<p class="jlink"><a href="%s/"><b>Browse all %d jurisdictions in %s</b>, each with '
             'its full declaration history, sortable and ready to copy into a mitigation plan &rarr;</a></p>'
             % (slug, s["jur_n"], e(name))) if s.get("jur_n") else ''

    # declarations that belong to no single locality -> listed here, on the state page.
    # Like the main table this lists the in-progress year too, untagged.
    if s["orphans"]:
        orows = "".join(
            "<tr><td>%s</td><td>%s</td><td><span class='tag' title='%s'>%s</span></td>"
            "<td>%s</td><td>%s</td></tr>"
            % (fmt_date(r[3]), e(r[0]), TYPE_LONG.get(r[1], r[1]), e(r[1]),
               e(r[2]), e(pretty_title(r[4])))
            for r in s["orphans"])
        n = len(s["orphans"])
        o_fys = {fy_of(r[3]) for r in s["orphans"] if fy_of(r[3]) > lcfy}
        if o_fys:
            o_name, o_since, o_until = open_fy_window(o_fys)
            counted = ('They do not appear on any individual jurisdiction page. Those from '
                       'complete fiscal years are included in the state totals above; any made '
                       'since %s (%s) are added %s.' % (o_since, o_name, o_until))
        else:
            counted = ('They are included in the state totals above but do not appear on any '
                       'individual jurisdiction page.')
        orphan_html = ('<h2>Declarations not attributed to a specific locality</h2>'
                       '<p>%d declaration%s in %s applied statewide, or to areas FEMA did not tie '
                       'to a single county or equivalent, such as wildfire management zones. %s</p>'
                       '<div class="tablewrap"><table><thead><tr><th>Date</th><th>Number</th>'
                       '<th>Type</th><th>Hazard</th><th>Title</th></tr></thead><tbody>%s'
                       '</tbody></table></div>'
                       % (n, "" if n == 1 else "s", e(name), counted, orows))
    else:
        orphan_html = ''

    ia_sec  = state_ia_html(s)
    hma_sec = state_hma_html(s)
    pa_sec  = recent_aid_html(s, lcfy) + pa_split_html(s, e(name))
    kinds   = decl_kinds_html()

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
            '%s'
            '<h2>Most common hazards</h2><ul class="haz">%s</ul>'
            '<h2>All declarations on record</h2>%s%s'
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
               e(name), e(name), lede, provenance_stamp_html(lcfy), stats, pa_sec, jlink, haz, kinds, recent_tbl, ia_sec, hma_sec, denials, orphan_html,
               e(name), ab, method_html(), grid, footer_html()))


# ---------------------------------------------------------------- hub
def render_hub(states, lcfy):
    e = html.escape
    total = sum(s["dr"] for s in states)
    rows = "".join('<li><a href="%s.html">%s</a><span class="c">%d major disasters</span></li>'
                   % (s["slug"], e(s["name"]), s["dr"]) for s in states)
    desc = ("Federal major disaster declarations for all 50 states, DC, and US "
            "territories since FY2000. %d major disasters, ranked, mapped, and exportable. "
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
            'by federal major disaster declarations since FY2000 (through FY%d). '
            '%d major disasters in all. Emergency and fire management declarations are counted '
            'separately on each state page. Select a state for its full history, hazard breakdown, '
            'declaration-request denial rate, and Public Assistance obligated.</p>'
            '%s'
            '<ol class="rank">%s</ol>'
            '%s</div></main>%s</body></html>'
            % (e(desc), SITE, e(desc), SITE, HEAD, header_html(),
               lcfy, total, provenance_stamp_html(lcfy), rows, method_html(), footer_html()))


# ---------------------------------------------------------------- sitemap + robots
def render_sitemap(states):
    # lastmod is derived from real data (each state's most recent declaration),
    # so the sitemap only changes when FEMA data does, so there are no spurious weekly commits.
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
    STATES, DECLS, DENS, YOY, KEEP, PA_COUNTY = load_data()
    lcfy = last_complete_fy(YOY)
    meta = {s["ab"]: s for s in STATES}

    rows = [state_stats(ab, m["name"], m.get("days", 0),
                        DECLS.get(ab, []), DENS.get(ab, []), lcfy,
                        KEEP.get(ab, {"ids": set(), "n": 0}))
            for ab, m in meta.items()]
    rows.sort(key=lambda s: (-s["dr"], -s["decl"]))
    for i, s in enumerate(rows):
        s["rank"] = i + 1

    HMA, IA = load_hma(), load_ia()
    PA_TIMING = load_pa_timing()
    IA_TIMING = load_ia_timing()
    EVENT_IDS = load_event_ids()
    PERIODS = load_incident_periods()
    for s in rows:
        s["hma"] = agg_hma(HMA.get(s["ab"], {}))
        s["ia"]  = agg_ia(IA.get(s["ab"], {}))
        s["pa"]  = state_pa(DECLS.get(s["ab"], []),
                            PA_COUNTY.get(s["ab"], {}),
                            PA_TIMING.get(s["ab"], {}))
        # inputs for the "recent declarations" panel
        s["ia_dn"] = ia_by_dn(IA_TIMING.get(s["ab"], {}))
        s["pa_dn"] = pa_by_dn(PA_TIMING.get(s["ab"], {}))
        s["dn_meta"] = dn_meta(DECLS.get(s["ab"], []))
        s["event_ids"] = EVENT_IDS
        s["periods"] = PERIODS

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
    print("national total (complete FY): %d declarations, %d major disasters"
          % (sum(s["decl"] for s in rows), sum(s["dr"] for s in rows)))
    _pa_states = [s for s in rows if (s.get("pa") or {}).get("total", 0) > 0]
    _attr  = sum((s.get("pa") or {}).get("attributed", 0) for s in rows)
    _resid = sum((s.get("pa") or {}).get("resid", 0) for s in rows)
    print("PA: %d states with obligated dollars; $%.0f attributed to a declaration, "
          "$%.0f unattributed residual" % (len(_pa_states), _attr, _resid))
    _cur = [(s, r) for s in rows for r in s.get("recent12", [])]
    _cur_ia = sum(1 for s, r in _cur if (s["ia_dn"].get(decl_num(r[0])) or [0, 0])[1] > 0)
    _cur_pa = sum(1 for s, r in _cur if s["pa_dn"].get(decl_num(r[0]), 0) > 0)
    _cur_ln = sum(1 for s, r in _cur if decl_num(r[0]) in s["event_ids"])
    print("recent declarations panel (past 12 months): %d declarations across %d states/territories; "
          "%d with household assistance reported, %d with PA obligated, %d linked to an "
          "event profile" % (len(_cur), len({s["ab"] for s, _ in _cur}), _cur_ia, _cur_pa,
                             _cur_ln))

if __name__ == "__main__":
    main()
