#!/usr/bin/env python3
"""
Generate the FEMA Daily Ops Briefing Archive front-end pages from
archive/ops-briefings/history.csv.

Output (all under ops-briefings/, alongside the rest of the site):
  ops-briefings/index.html          Last 30 days, newest first
  ops-briefings/YYYY-MM-DD.html     One page per archived briefing
  ops-briefings/archive/index.html  Hub listing every month on record
  ops-briefings/archive/YYYY-MM.html  All days archived in that month
  ops-briefings/ops-briefings.css   Shared stylesheet for all of the above

The nav, fonts, and color tokens here are copied from the main site's
index.html so this section matches the rest of DisasterData.IO exactly,
rather than approximating the brand from memory.

This script only reads history.csv and writes HTML/CSS. It never touches
the PDFs themselves or archive/ops-briefings/history.csv.

Run this after fetch_ops_briefing.py in the same daily Action, so the
site rebuilds whenever a new briefing is archived.

Env vars:
  DD_OUT   Optional. Root data directory (where history.csv lives).
           Defaults to "archive", matching fetch_ops_briefing.py.
"""

import csv
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
HISTORY_CSV = OUT_ROOT / "ops-briefings" / "history.csv"

SITE_DIR = Path("ops-briefings")
ARCHIVE_HUB_DIR = SITE_DIR / "archive"

PDF_BASE_PATH = "/archive/ops-briefings"  # where fetch_ops_briefing.py puts PDFs
SUBSCRIBE_URL = "https://public.govdelivery.com/accounts/USDHSFEMA/subscriber/new"

LAST_N_DAYS_SHOWN = 30


def load_history() -> list[dict]:
    if not HISTORY_CSV.exists():
        return []
    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r["date"])
    return rows


def fmt_date_long(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")


def fmt_month_long(month_key: str) -> str:
    return datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")


# Design tokens, fonts, nav, and footer below are copied directly from
# the main site's index.html so this section is visually identical,
# not a reconstruction from memory.
CSS = """
:root{
  color-scheme:light;
  --paper:#f6f1e7;--paper-2:#fcfaf3;--paper-3:#f1ead9;
  --ink:#1d1813;--ink-2:#5b5346;--ink-3:#938a78;
  --rule:#e0d8c5;--rule-2:#cfc6b0;
  --accent:#004c53;--accent-2:#0a6b73;--accent-soft:#d7e9ea;
  --serif:'Fraunces',Georgia,serif;--sans:'Public Sans',-apple-system,BlinkMacSystemFont,sans-serif;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
::selection{background:var(--accent);color:#fff;}
.wrap{position:relative;z-index:1;}

nav{position:sticky;top:0;z-index:50;background:rgba(246,241,231,.86);backdrop-filter:saturate(140%) blur(10px);border-bottom:1px solid var(--rule);display:flex;align-items:center;justify-content:space-between;padding:0 clamp(18px,4vw,48px);height:60px;}
.brand{display:flex;align-items:baseline;gap:10px;}
.brand .mark{font-family:var(--serif);font-weight:600;font-size:19px;letter-spacing:-.4px;color:var(--accent);text-decoration:none;}
.navlinks{display:flex;align-items:center;gap:4px;}
.navlinks a{font-size:13px;font-weight:500;color:var(--ink-2);text-decoration:none;padding:7px 12px;border-radius:6px;transition:.15s;letter-spacing:.2px;}
.navlinks a:hover{color:var(--ink);background:var(--paper-3);}
.navlinks a.on{color:var(--accent);background:var(--accent-soft);}
@media(max-width:720px){nav{height:auto;flex-direction:column;align-items:stretch;justify-content:flex-start;gap:9px;padding-top:11px;padding-bottom:11px;}.navlinks{flex-wrap:wrap;gap:4px;}}

.container{max-width:1080px;margin:0 auto;padding:0 clamp(18px,4vw,48px);}
.section{padding:clamp(40px,6vw,72px) 0;}
.narrow{max-width:70ch;}

.kicker{font-size:12px;font-weight:600;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);margin-bottom:18px;}
h1.headline{font-family:var(--serif);font-weight:400;font-size:clamp(30px,5vw,52px);line-height:1.05;letter-spacing:-1.2px;margin-bottom:18px;}
.standfirst{font-size:clamp(15px,1.6vw,17px);color:var(--ink-2);max-width:64ch;line-height:1.6;}

.btn{display:inline-flex;align-items:center;gap:8px;font-family:var(--sans);font-size:14px;font-weight:600;color:#fff;background:var(--accent);border:1px solid var(--accent);border-radius:8px;padding:12px 22px;text-decoration:none;transition:.15s;}
.btn:hover{background:var(--accent-2);border-color:var(--accent-2);}

.subscribe-callout{background:var(--paper-2);border:1px solid var(--rule);border-radius:12px;padding:20px 24px;margin:28px 0 8px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
.subscribe-callout .label{font-weight:600;font-size:15px;}
.subscribe-callout .sub{font-size:13px;color:var(--ink-2);margin-top:2px;}

h2.section-h{font-family:var(--serif);font-weight:400;font-size:clamp(22px,3vw,30px);letter-spacing:-.6px;margin:44px 0 18px;}

.briefing-list{list-style:none;border-top:1px solid var(--rule);}
.briefing-list li{border-bottom:1px solid var(--rule);}
.briefing-list a{display:flex;justify-content:space-between;align-items:center;padding:14px 4px;text-decoration:none;color:var(--ink);font-size:15px;transition:.13s;}
.briefing-list a:hover{color:var(--accent);background:var(--paper-2);}
.briefing-list .arrow{color:var(--accent);font-weight:600;font-size:13px;}

.archive-link{display:inline-block;margin-top:24px;font-weight:600;color:var(--accent);text-decoration:none;font-size:14px;}
.archive-link:hover{text-decoration:underline;}

.day-nav{display:flex;justify-content:space-between;gap:16px;margin-top:40px;padding-top:20px;border-top:1px solid var(--rule);font-size:14px;}
.day-nav a{text-decoration:none;font-weight:600;color:var(--accent);}
.day-nav a:hover{text-decoration:underline;}

.meta{color:var(--ink-3);font-size:13px;}
.cite{font-size:13px;color:var(--ink-2);word-break:break-all;margin-top:10px;}
.cite a{color:var(--accent);}

footer{border-top:1px solid var(--rule);padding:40px 0 60px;margin-top:40px;}
.foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:18px;font-size:12px;color:var(--ink-3);line-height:1.7;}
.foot a{color:var(--accent);text-decoration:none;}
.foot a:hover{text-decoration:underline;}
.foot .disc{max-width:62ch;}
"""


NAV = """<nav>
  <div class="brand"><a class="mark" href="/">Disaster Data</a></div>
  <div class="navlinks"><a href="/#board">Explore</a><a href="/map.html">Map</a><a href="/states/index.html">States</a><a href="/public-assistance-projects.html">Funding</a><a href="/about.html">About</a><a href="/ops-briefings/index.html" class="on">FEMA Daily Operations Brief</a></div>
</nav>"""

FOOTER = """<footer>
  <div class="container">
    <div class="foot">
      <div class="disc">FEMA's Daily Operations Briefing is not published anywhere else online; it only goes out to GovDelivery subscribers. This archive captures each day's PDF as-is, with no text or table extraction.</div>
      <div style="text-align:right;">DisasterData.IO is part of <a href="https://www.compliaid.com" target="_blank" rel="noopener">CompliAid</a><br><a href="/">Back to Disaster Data</a></div>
    </div>
  </div>
</footer>"""


def page_shell(title: str, body: str, description: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/ops-briefings/ops-briefings.css">
</head>
<body>
<div class="wrap">
{NAV}
<div class="container">
<div class="section narrow">
{body}
</div>
</div>
{FOOTER}
</div>
</body>
</html>
"""


def subscribe_callout() -> str:
    return f"""<div class="subscribe-callout">
  <div>
    <div class="label">Want it in your own inbox?</div>
    <div class="sub">Subscribe directly to FEMA's Daily Operations Briefing.</div>
  </div>
  <a class="btn" href="{SUBSCRIBE_URL}">Subscribe &rarr;</a>
</div>"""


def build_index(rows: list[dict]) -> None:
    if not rows:
        body = """<div class="kicker">DisasterData.IO</div>
<h1 class="headline">FEMA Daily Operations Briefing Archive</h1>
<p class="standfirst">No briefings archived yet.</p>"""
        (SITE_DIR / "index.html").write_text(
            page_shell("FEMA Daily Ops Briefing Archive", body), encoding="utf-8"
        )
        return

    newest_first = list(reversed(rows))
    last_30 = newest_first[:LAST_N_DAYS_SHOWN]

    items = "\n".join(
        f'''<li><a href="/ops-briefings/{r["date"]}.html">
              <span>{fmt_date_long(r["date"])}</span>
              <span class="arrow">View briefing &rarr;</span>
            </a></li>'''
        for r in last_30
    )

    body = f"""<div class="kicker">DisasterData.IO</div>
<h1 class="headline">FEMA Daily Operations Briefing Archive</h1>
<p class="standfirst">FEMA does not publish these briefings anywhere online;
they only go out to GovDelivery subscribers. This archive captures each
day's PDF so anyone can look back and see what FEMA's National Watch
Center was reporting on any given day, including declaration requests
as they move through the process.</p>

{subscribe_callout()}

<h2 class="section-h">Last {LAST_N_DAYS_SHOWN} days</h2>
<ul class="briefing-list">
{items}
</ul>

<a class="archive-link" href="/ops-briefings/archive/">Browse the full archive by month &rarr;</a>
"""
    (SITE_DIR / "index.html").write_text(
        page_shell(
            "FEMA Daily Ops Briefing Archive",
            body,
            "A daily archive of FEMA's Daily Operations Briefing, otherwise unpublished anywhere online.",
        ),
        encoding="utf-8",
    )


def build_day_pages(rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        date_str = row["date"]
        prev_row = rows[i - 1] if i > 0 else None
        next_row = rows[i + 1] if i < len(rows) - 1 else None

        prev_link = (
            f'<a href="/ops-briefings/{prev_row["date"]}.html">&larr; {fmt_date_long(prev_row["date"])}</a>'
            if prev_row
            else "<span></span>"
        )
        next_link = (
            f'<a href="/ops-briefings/{next_row["date"]}.html">{fmt_date_long(next_row["date"])} &rarr;</a>'
            if next_row
            else "<span></span>"
        )

        pdf_url = f'{PDF_BASE_PATH}/{row["filename"]}'

        body = f"""<div class="kicker">FEMA Daily Operations Briefing</div>
<h1 class="headline">{fmt_date_long(date_str)}</h1>
<p class="meta">Archived {row.get("archived_at", "")[:10]}</p>

<p style="margin-top:24px;"><a class="btn" href="{pdf_url}">Open the PDF &rarr;</a></p>

<p class="cite">Cite this page: <a href="{pdf_url}">{pdf_url}</a></p>

<div class="day-nav">
  {prev_link}
  {next_link}
</div>
"""
        (SITE_DIR / f"{date_str}.html").write_text(
            page_shell(
                f"FEMA Daily Ops Briefing, {fmt_date_long(date_str)}",
                body,
                f"FEMA's Daily Operations Briefing for {fmt_date_long(date_str)}, archived by DisasterData.IO.",
            ),
            encoding="utf-8",
        )


def build_archive_hub(rows: list[dict]) -> None:
    by_month = defaultdict(list)
    for row in rows:
        month_key = row["date"][:7]  # YYYY-MM
        by_month[month_key].append(row)

    month_keys_desc = sorted(by_month.keys(), reverse=True)

    items = "\n".join(
        f'''<li><a href="/ops-briefings/archive/{mk}.html">
              <span>{fmt_month_long(mk)}</span>
              <span class="arrow">{len(by_month[mk])} briefing(s) &rarr;</span>
            </a></li>'''
        for mk in month_keys_desc
    )

    body = f"""<div class="kicker">DisasterData.IO</div>
<h1 class="headline">Full Ops Briefing Archive</h1>
<p class="standfirst">Every FEMA Daily Operations Briefing captured, grouped by month.</p>
<ul class="briefing-list">
{items}
</ul>
<a class="archive-link" href="/ops-briefings/">&larr; Back to last {LAST_N_DAYS_SHOWN} days</a>
"""
    ARCHIVE_HUB_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_HUB_DIR / "index.html").write_text(
        page_shell("Full FEMA Ops Briefing Archive", body),
        encoding="utf-8",
    )

    for mk in month_keys_desc:
        month_rows = sorted(by_month[mk], key=lambda r: r["date"], reverse=True)
        items = "\n".join(
            f'''<li><a href="/ops-briefings/{r["date"]}.html">
                  <span>{fmt_date_long(r["date"])}</span>
                  <span class="arrow">View briefing &rarr;</span>
                </a></li>'''
            for r in month_rows
        )
        body = f"""<div class="kicker">DisasterData.IO</div>
<h1 class="headline">{fmt_month_long(mk)}</h1>
<ul class="briefing-list">
{items}
</ul>
<a class="archive-link" href="/ops-briefings/archive/">&larr; Back to full archive</a>
"""
        (ARCHIVE_HUB_DIR / f"{mk}.html").write_text(
            page_shell(f"FEMA Ops Briefings, {fmt_month_long(mk)}", body),
            encoding="utf-8",
        )


def main() -> int:
    rows = load_history()

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "ops-briefings.css").write_text(CSS, encoding="utf-8")

    build_index(rows)
    build_day_pages(rows)
    build_archive_hub(rows)

    print(f"Built {len(rows)} day page(s), index, and archive hub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
