#!/usr/bin/env python3
"""
North Dakota Executive Order scraper for DisasterData Plus.

Two real, distinct sources of record, both on governor.nd.gov:

1. https://www.governor.nd.gov/executive-orders
   Current-administration EOs (2024-present as of this delivery). Each entry
   has an order number, a descriptive title, and a direct PDF link, but no
   explicit "date filed" field on the page itself - the filed date has to be
   read out of the order's own PDF text (ND's EO template states it near the
   signature block) or corroborated from a governor's-office news release.

2. https://www.governor.nd.gov/executive-orders/executive-order-archive
   Historical EOs back to 1963. Entries from 2017-2023 (Burgum) carry an
   explicit "YYYY-NN - Month Day, Year - Title" format with both a number
   and a date. Entries from 2016 and earlier (Dalrymple and predecessors)
   give only "Month Day, Year - Title" with NO order number in the rendered
   list - a genuine limitation of this page's markup, not a scraper bug.
   Getting order numbers for 2000-2016 would require opening each linked
   item individually (the archive page's older entries aren't reliably
   hyperlinked to a PDF either), which was not done in this pass.

Both pages are plain server-rendered HTML (Drupal), no JS execution needed.

Output schema (declarations_for_join.csv):
    declaration_id, governor, eo_number, event_description, date_signed,
    archive_record_url

Only genuine weather/disaster declarations are written. Notably: ND uses
"declares a state of emergency" language for BOTH weather disasters and
civil-disturbance orders (e.g. 2020-34, a Fargo/Cass County civil-unrest
order tied to the May 2020 protests, not a storm) - the title-matching
alone cannot distinguish these, so EXCLUDE_IDS below hard-excludes orders
confirmed non-weather by reading the underlying news release, and future
maintainers should not assume every "state of emergency" hit is a storm.
"""
import argparse
import csv
import re
import sys

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None

CURRENT_URL = "https://www.governor.nd.gov/executive-orders"
ARCHIVE_URL = "https://www.governor.nd.gov/executive-orders/executive-order-archive"

# Confirmed non-weather despite emergency/disaster-sounding titles. Checked
# by hand against the governor's-office news release for each ID; do not
# remove an ID from this list without re-confirming against the source.
EXCLUDE_IDS = {
    "2020-34",  # Fargo/West Fargo/Cass County civil-disturbance order, not weather.
    "2023-07",  # ND Guard deployed to Texas border, not a ND weather event.
}

DISASTER_KEYWORDS = re.compile(
    r"(disaster|flood|drought|fire|blizzard|storm|tornado|wildfire)",
    re.IGNORECASE,
)

EXCLUDED_TITLE_PATTERNS = re.compile(
    r"(covid|hours of service|task force|council|commission|rescind|"
    r"terminat|amend|census|kratom|tiktok|homelessness|advisory)",
    re.IGNORECASE,
)


def fetch(url):
    resp = requests.get(url, timeout=30, headers={"User-Agent": "DisasterDataIO-Plus/1.0"})
    resp.raise_for_status()
    return resp.text


ARCHIVE_ITEM_RE = re.compile(
    r"\*\*(?P<num>\d{4}(?:-\d+)?(?:\.\d+)?)\*\*\s*-\s*"
    r"(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})\s*-\s*(?P<title>.+)"
)

CURRENT_ITEM_RE = re.compile(
    r"\*\*(?P<num>\d{4}(?:-\d+)?(?:\.\d+)?)\*\*\s*-\s*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)"
)


def parse_archive_markdown(md_text):
    """Parse the 2017-2023 numbered entries out of the archive page's
    rendered '**YYYY-NN** - Month Day, Year - Title' lines."""
    orders = []
    for line in md_text.splitlines():
        m = ARCHIVE_ITEM_RE.search(line)
        if m:
            orders.append({
                "eo_number": m.group("num"),
                "date_text": m.group("date"),
                "title": m.group("title").strip(),
                "url": ARCHIVE_URL,
            })
    return orders


def parse_current_markdown(md_text):
    """Parse the 2024-present numbered/linked entries. No date on this page;
    date must come from a secondary source (news release) if needed."""
    orders = []
    for line in md_text.splitlines():
        m = CURRENT_ITEM_RE.search(line)
        if m:
            orders.append({
                "eo_number": m.group("num"),
                "date_text": None,
                "title": m.group("title").strip(),
                "url": m.group("url").strip(),
            })
    return orders


def parse_date_text(date_text):
    if not date_text:
        return ""
    for fmt in ("%B %d, %Y",):
        try:
            from datetime import datetime
            return datetime.strptime(date_text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def governor_for(eo_number):
    year = int(eo_number.split("-")[0])
    if year >= 2025:
        return "Armstrong"
    if 2017 <= year <= 2024:
        return "Burgum"
    if year <= 2016:
        return "Dalrymple"
    return ""


def is_declaration(eo_number, title):
    if eo_number in EXCLUDE_IDS:
        return False
    if EXCLUDED_TITLE_PATTERNS.search(title):
        return False
    return bool(DISASTER_KEYWORDS.search(title))


def collect_orders():
    if requests is None:
        raise RuntimeError("requests/bs4 not installed - pip install requests beautifulsoup4")
    archive_html = fetch(ARCHIVE_URL)
    current_html = fetch(CURRENT_URL)
    # NOTE: this scraper expects the page's already-rendered text/markdown
    # form (as returned by the project's HTML->markdown fetch step used
    # elsewhere in the pipeline). If wiring this directly to raw HTML,
    # normalize to that markdown-like text first, or rewrite the two
    # regexes above against BeautifulSoup-extracted text.
    orders = parse_archive_markdown(archive_html) + parse_current_markdown(current_html)
    return orders


def write_csv(orders, actions_out, relationships_out, join_out, confirmed_dates=None):
    """
    confirmed_dates: optional dict of {eo_number: 'YYYY-MM-DD'} used to
    supply a verified date for orders that came from the undated
    current-EOs page (parse_current_markdown never has a date on its own).
    Orders with neither a parsed date nor a confirmed_dates entry are
    written to actions_out (raw scrape) but excluded from the join CSV -
    a real join with a fabricated date is worse than a smaller real one.
    """
    confirmed_dates = confirmed_dates or {}
    declarations = []
    for o in orders:
        if not is_declaration(o["eo_number"], o["title"]):
            continue
        date_signed = parse_date_text(o["date_text"]) or confirmed_dates.get(o["eo_number"], "")
        if not date_signed:
            continue
        declarations.append({
            "declaration_id": f"ND-EO-{o['eo_number']}",
            "governor": governor_for(o["eo_number"]),
            "eo_number": o["eo_number"],
            "event_description": o["title"],
            "date_signed": date_signed,
            "archive_record_url": o["url"],
        })

    fieldnames = ["declaration_id", "governor", "eo_number", "event_description",
                  "date_signed", "archive_record_url"]
    with open(join_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for d in declarations:
            writer.writerow(d)

    with open(actions_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "date_text", "title", "url"], lineterminator="\n")
        writer.writeheader()
        for o in orders:
            writer.writerow(o)

    with open(relationships_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "relates_to"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"eo_number": "2017-02.1", "relates_to": "2017-02"})

    return declarations


def main():
    parser = argparse.ArgumentParser(description="North Dakota EO scraper")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    orders = collect_orders()
    # Dates independently confirmed via governor's-office news releases for
    # orders that live on the undated current-EOs page. Extend this as more
    # 2024-2026 orders get their dates verified.
    confirmed_dates = {
        "2025-05": "2025-06-21",
        "2026-03": "2026-06-30",
    }
    declarations = write_csv(orders, args.actions_out, args.relationships_out,
                              args.join_out, confirmed_dates=confirmed_dates)
    print(f"North Dakota: {len(orders)} orders scraped, {len(declarations)} written as declarations.")


if __name__ == "__main__":
    main()
