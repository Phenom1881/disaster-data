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

TEAL = "#004c53"
CREAM = "#faf6ee"


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


CSS = f"""
:root {{
  --teal: {TEAL};
  --cream: {CREAM};
  --ink: #1a1a1a;
  --line: #e2ddd0;
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background: var(--cream);
  color: var(--ink);
  font-family: "Public Sans", -apple-system, BlinkMacSystemFont, sans-serif;
  line-height: 1.5;
}}

h1, h2, h3 {{
  font-family: "Fraunces", Georgia, serif;
  font-weight: 600;
  color: var(--teal);
}}

a {{ color: var(--teal); }}

.wrap {{
  max-width: 760px;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}}

.top-nav {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--line);
  background: rgba(250, 246, 238, 0.85);
  backdrop-filter: blur(6px);
  position: sticky;
  top: 0;
}}

.top-nav a {{
  text-decoration: none;
  font-weight: 600;
  color: var(--teal);
}}

.eyebrow {{
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.75rem;
  color: #6b6b6b;
  margin-bottom: 0.25rem;
}}

.subscribe-callout {{
  background: white;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  margin: 1.5rem 0 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}}

.subscribe-callout .btn {{
  background: var(--teal);
  color: white;
  text-decoration: none;
  padding: 0.55rem 1.1rem;
  border-radius: 6px;
  font-weight: 600;
  white-space: nowrap;
}}

.briefing-list {{
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--line);
}}

.briefing-list li {{
  border-bottom: 1px solid var(--line);
}}

.briefing-list a {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.85rem 0.25rem;
  text-decoration: none;
  color: var(--ink);
}}

.briefing-list a:hover {{ color: var(--teal); }}

.briefing-list .arrow {{ color: var(--teal); font-weight: 600; }}

.archive-link {{
  display: inline-block;
  margin-top: 1.5rem;
  font-weight: 600;
}}

.day-nav {{
  display: flex;
  justify-content: space-between;
  margin-top: 2.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
}}

.day-nav a {{ text-decoration: none; font-weight: 600; }}

.pdf-button {{
  display: inline-block;
  background: var(--teal);
  color: white;
  text-decoration: none;
  padding: 0.75rem 1.4rem;
  border-radius: 6px;
  font-weight: 600;
  margin: 1rem 0 0.5rem;
}}

.meta {{
  color: #6b6b6b;
  font-size: 0.9rem;
}}
"""


def page_shell(title: str, body: str, description: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@500;600&family=Public+Sans:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/ops-briefings/ops-briefings.css">
</head>
<body>
<nav class="top-nav">
  <a href="/">Disaster Data</a>
  <a href="/ops-briefings/">Ops Briefing Archive</a>
</nav>
<div class="wrap">
{body}
</div>
</body>
</html>
"""


def subscribe_callout() -> str:
    return f"""<div class="subscribe-callout">
  <div>
    <strong>Want it in your own inbox?</strong><br>
    <span class="meta">Subscribe directly to FEMA's Daily Operations Briefing.</span>
  </div>
  <a class="btn" href="{SUBSCRIBE_URL}">Subscribe</a>
</div>"""


def build_index(rows: list[dict]) -> None:
    if not rows:
        body = "<h1>FEMA Daily Operations Briefing Archive</h1><p>No briefings archived yet.</p>"
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

    body = f"""<div class="eyebrow">DisasterData.IO</div>
<h1>FEMA Daily Operations Briefing Archive</h1>
<p>FEMA does not publish these briefings anywhere online; they only
go out to GovDelivery subscribers. This archive captures each day's
PDF so anyone can look back and see what FEMA's National Watch Center
was reporting on any given day, including declaration requests as
they move through the process.</p>

{subscribe_callout()}

<h2>Last {LAST_N_DAYS_SHOWN} days</h2>
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

        body = f"""<div class="eyebrow">FEMA Daily Operations Briefing</div>
<h1>{fmt_date_long(date_str)}</h1>
<p class="meta">Archived {row.get("archived_at", "")[:10]}</p>

<a class="pdf-button" href="{pdf_url}">Open the PDF &rarr;</a>

<p><a href="{pdf_url}">Cite this page</a>: {pdf_url}</p>

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

    body = f"""<div class="eyebrow">DisasterData.IO</div>
<h1>Full Ops Briefing Archive</h1>
<p>Every FEMA Daily Operations Briefing captured, grouped by month.</p>
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
        body = f"""<div class="eyebrow">DisasterData.IO</div>
<h1>{fmt_month_long(mk)}</h1>
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
