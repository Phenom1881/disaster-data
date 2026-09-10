#!/usr/bin/env python3
"""
Montana Executive Order scraper for DisasterData Plus.

Montana's EO record is split across THREE separate, real sites depending on
administration - there is no single archive covering 2000-present:

1. https://gov.mt.gov/Documents/GovernorsOffice/executiveorders/
   Current administration (Gianforte, 2021-present). Each entry gives
   title, "Executive Order No. N-YYYY", and a filed date, e.g.:
       Declaring a Disaster to Exist in the State of Montana
       Executive Order 9-2025
       December 11, 2025
   This page appears to be a curated/paginated list rather than a strict
   sequential index (some individual EO numbers were only found via direct
   web search of their PDFs, not by scrolling this page - e.g. EO 10-2025
   and EO 11-2025 in December 2025). A production scraper MUST paginate
   this endpoint (?page=N) and should not assume the first page is
   complete - not verified end-to-end against live pagination in this pass.

2. https://formergovernors.mt.gov/bullock/ExecutiveOrders.html
   Bullock administration (2013-2020). Static per-year sections with
   title + "Executive Order No. N-YYYY" and a direct PDF link, but NO
   explicit date in the rendered list text itself (unlike the current
   Gianforte page) - the date lives inside each linked PDF.

3. https://formergovernors.mt.gov/schweitzer/eo/<year>.asp
   Schweitzer administration (2005-2013), per-year pages. Not deeply
   parsed in this pass beyond confirming the URL pattern exists and
   returns real per-year EO listings - treat as a known, real, but
   unimplemented source for a future backfill pass.

Output schema (declarations_for_join.csv):
    declaration_id, governor, eo_number, event_description, date_signed,
    archive_record_url

Montana's disaster EOs are almost all titled with the same boilerplate,
"Declaring a Disaster to Exist in the State of Montana" - the title alone
carries NO hazard keyword, so essentially every Montana disaster EO needs a
hazard_overrides.csv entry sourced from the governor's-office news release
or the order's own PDF text. This is a structural property of Montana's EO
drafting convention, not a scraper defect - do not expect title-only
classification to work for this state the way it does for ND or SD.
"""
import argparse
import csv
import re
import sys
from datetime import datetime

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

CURRENT_URL = "https://gov.mt.gov/Documents/GovernorsOffice/executiveorders/"
BULLOCK_URL = "https://formergovernors.mt.gov/bullock/ExecutiveOrders.html"

DISASTER_KEYWORDS = re.compile(
    r"(disaster|drought|flood|fire|wind|blizzard|winter|"
    r"wildland fire|tornado)",
    re.IGNORECASE,
)

# Montana's boilerplate disaster title has no hazard keyword at all, so it
# must be positively recognized on its own (not just by DISASTER_KEYWORDS)
# and routed to hazard_overrides.csv rather than auto-classified.
BOILERPLATE_DISASTER_TITLE = re.compile(
    r"^declaring a disaster to exist (in|within) the state of montana",
    re.IGNORECASE,
)

EXCLUDED_TITLE_PATTERNS = re.compile(
    r"(continuing|creating|rescind|task force|council|commission|"
    r"advisory|vaccine passport|licensing reform|property tax|"
    r"housing advisory|hours of service|fertilizer)",
    re.IGNORECASE,
)

# Current-page entry regex, matching the rendered
# "Title\nExecutive Order No. N-YYYY\nMonth D, YYYY" triplet.
CURRENT_ENTRY_RE = re.compile(
    r"(?P<title>[^\n]+)\n\s*Executive Order(?: No\.?)?\s*(?P<num>\d+-\d{4})\s*\n\s*"
    r"(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})",
)

BULLOCK_ENTRY_RE = re.compile(
    r"\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*-{1,2}\s*Executive\s*"
    r"Order No\.?\s*(?P<num>\d+-\d{4})",
    re.IGNORECASE,
)


def fetch(url):
    resp = requests.get(url, timeout=30, headers={"User-Agent": "DisasterDataIO-Plus/1.0"})
    resp.raise_for_status()
    return resp.text


def parse_current_page(text):
    orders = []
    for m in CURRENT_ENTRY_RE.finditer(text):
        orders.append({
            "eo_number": m.group("num"),
            "title": m.group("title").strip(),
            "date_text": m.group("date"),
            "url": CURRENT_URL,
        })
    return orders


def parse_bullock_page(text):
    """Bullock-era entries have title + number but NO date in the list
    text; date_text is always None here and must come from a supplemental
    per-PDF read (not implemented) before these can join declarations_for_join.csv."""
    orders = []
    for m in BULLOCK_ENTRY_RE.finditer(text):
        orders.append({
            "eo_number": m.group("num"),
            "title": m.group("title").strip(),
            "date_text": None,
            "url": m.group("url").strip(),
        })
    return orders


def parse_date_text(date_text):
    if not date_text:
        return ""
    try:
        return datetime.strptime(date_text, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def governor_for(eo_number):
    year = int(eo_number.split("-")[1])
    if year >= 2021:
        return "Gianforte"
    if 2013 <= year <= 2020:
        return "Bullock"
    if 2005 <= year <= 2012:
        return "Schweitzer"
    return ""


def classify_title(title):
    """Returns (is_declaration, needs_hazard_override)."""
    if EXCLUDED_TITLE_PATTERNS.search(title):
        return False, False
    if BOILERPLATE_DISASTER_TITLE.search(title):
        return True, True  # real declaration, but title has no hazard word
    if DISASTER_KEYWORDS.search(title):
        return True, False
    return False, False


def collect_orders():
    if requests is None:
        raise RuntimeError("requests not installed - pip install requests")
    current_text = fetch(CURRENT_URL)
    bullock_text = fetch(BULLOCK_URL)
    orders = parse_current_page(current_text) + parse_bullock_page(bullock_text)
    return orders


def write_csv(orders, actions_out, relationships_out, join_out, confirmed_dates=None):
    confirmed_dates = confirmed_dates or {}
    declarations = []
    needs_override = []
    for o in orders:
        is_decl, needs_override_flag = classify_title(o["title"])
        if not is_decl:
            continue
        date_signed = parse_date_text(o["date_text"]) or confirmed_dates.get(o["eo_number"], "")
        if not date_signed:
            continue
        row = {
            "declaration_id": f"MT-EO-{o['eo_number']}",
            "governor": governor_for(o["eo_number"]),
            "eo_number": o["eo_number"],
            "event_description": o["title"],
            "date_signed": date_signed,
            "archive_record_url": o["url"],
        }
        declarations.append(row)
        if needs_override_flag:
            needs_override.append(row["declaration_id"])

    fieldnames = ["declaration_id", "governor", "eo_number", "event_description",
                  "date_signed", "archive_record_url"]
    with open(join_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for d in declarations:
            writer.writerow(d)

    with open(actions_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "title", "date_text", "url"], lineterminator="\n")
        writer.writeheader()
        for o in orders:
            writer.writerow(o)

    with open(relationships_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "relates_to"], lineterminator="\n")
        writer.writeheader()
        # EO 10-2025 (hours-of-service waiver) is a narrow companion order
        # riding alongside the Dec 2025 flooding/wind disasters (9-2025,
        # 11-2025), not a distinct declaration in its own right.
        writer.writerow({"eo_number": "10-2025", "relates_to": "9-2025;11-2025"})

    if needs_override:
        print(f"NOTE: {len(needs_override)} declarations need hazard_overrides.csv "
              f"entries (boilerplate title, no hazard keyword): {needs_override}",
              file=sys.stderr)

    return declarations


def main():
    parser = argparse.ArgumentParser(description="Montana EO scraper")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    orders = collect_orders()
    # Dates/entries independently confirmed via direct PDF/news-release
    # search during this delivery, for orders not reliably surfaced by the
    # current page's own pagination.
    confirmed_dates = {
        "10-2025": "2025-12-17",
        "11-2025": "2025-12-18",
    }
    declarations = write_csv(orders, args.actions_out, args.relationships_out,
                              args.join_out, confirmed_dates=confirmed_dates)
    print(f"Montana: {len(orders)} orders scraped, {len(declarations)} written as declarations.")


if __name__ == "__main__":
    main()
