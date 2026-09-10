#!/usr/bin/env python3
"""
Nebraska disaster-declaration scraper for the DisasterData Plus corridor.

Source (real, structured, publicly accessible, confirmed fetchable - not
robots-blocked): the Nebraska Library Commission's government-documents
mirror of the Governor's Executive Orders index at
    https://govdocs.nebraska.gov/docs/pilot/pubs/eoindex.html
a single HTML table listing every numbered Executive Order back to 1965
(plus a handful of older undated/unnumbered entries this scraper does not
attempt to parse), each linking to the real signed PDF at
    https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/<number>.pdf

Nebraska's numbered-EO track mixes routine administrative orders (bond
allocations, task forces, commemorative proclamations) with genuine
emergency/disaster orders in the same sequence - there is no separate
"disaster only" list. This scraper therefore keeps only rows whose
description contains an emergency/disaster/hazard-relief keyword, so the
join file reflects actual declarations rather than every order Nebraska
has ever issued.

CLI contract (matches every other Plus-corridor state adapter):
    --actions-out         <path>   every EO row examined, kept or not (debug/audit trail)
    --relationships-out   <path>   EO -> PDF link graph (debug/audit trail)
    --join-out            <path>   declarations_for_join.csv (the file build-plus.py reads)
"""
import argparse
import csv
import re
import sys
from datetime import datetime

import requests

STATE = "NE"
SOURCE_URL = "https://govdocs.nebraska.gov/docs/pilot/pubs/eoindex.html"
SCOPE_START = datetime(2000, 1, 1)

GOVERNOR_BY_DATE = [
    (datetime(1999, 1, 1), "Mike Johanns"),
    (datetime(2005, 1, 6), "Dave Heineman"),
    (datetime(2015, 1, 8), "Pete Ricketts"),
    (datetime(2023, 1, 5), "Jim Pillen"),
]

# A row's Description must contain one of these (case-insensitive) to be
# treated as an actual emergency/disaster-type order at all. This is
# deliberately broad - it decides whether a row becomes a *candidate*
# declaration row in the join CSV, not its hazard category (that's
# eo_storm_join.py's job downstream, aided by hazard_overrides.csv for
# genuinely ambiguous cases).
DECLARATION_KEYWORDS_RE = re.compile(
    r"emergency|disaster|relief due to|weather event|burn (?:ban|permit)|fire ban|"
    r"winter storm|flooding|wildfire|drought|hurricane|extreme cold|heat wave|"
    r"power (?:demand|outage)|supply shortage|propane|heating fuel",
    re.IGNORECASE,
)

ROW_RE = re.compile(
    r'<tr[^>]*>\s*<td[^>]*>\s*(?:<a[^>]+href="([^"]+)"[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</td>\s*'
    r'<td[^>]*>\s*(?:<a[^>]+href="[^"]+"[^>]*>)?\s*(.*?)\s*(?:</a>)?\s*</td>\s*'
    r'<td[^>]*>\s*([^<]*?)\s*</td>',
    re.IGNORECASE | re.DOTALL,
)


def governor_for(date_obj):
    gov = GOVERNOR_BY_DATE[0][1]
    for cutoff, name in GOVERNOR_BY_DATE:
        if date_obj >= cutoff:
            gov = name
    return gov


def fetch(url, session):
    resp = session.get(url, timeout=30, headers={"User-Agent": "DisasterData.io research crawler"})
    resp.raise_for_status()
    return resp.text


def parse_date(date_text):
    date_text = date_text.strip()
    for fmt in ("%m/%d/%y", "%m-%d-%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_text, fmt)
        except ValueError:
            continue
    return None


def parse_index_table(html):
    """Parse the eoindex.html table into a list of dicts:
    {eo_number, description, date, pdf_url}. Rows with no parseable date
    (mostly pre-1990 entries with "Undated" or narrative-only text in the
    Date column) are returned with date=None and are filtered out by the
    caller rather than here, so callers can still audit what was skipped
    and why."""
    records = []
    for m in ROW_RE.finditer(html):
        href, eo_number, description, date_text = m.groups()
        description = re.sub(r"<[^>]+>", "", description or "").strip()
        eo_number = (eo_number or "").strip()
        dt = parse_date(date_text or "")
        pdf_url = href if href else None
        records.append({
            "eo_number": eo_number,
            "description": description,
            "date": dt.strftime("%Y-%m-%d") if dt else None,
            "pdf_url": pdf_url,
        })
    return records


def collect(actions_out, relationships_out, join_out):
    session = requests.Session()
    html = fetch(SOURCE_URL, session)
    all_rows = parse_index_table(html)

    actions = []
    relationships = []
    declarations = []

    for row in all_rows:
        is_candidate = bool(DECLARATION_KEYWORDS_RE.search(row["description"] or ""))
        actions.append({
            "eo_number": row["eo_number"],
            "description": row["description"],
            "date": row["date"] or "",
            "kept_as_declaration_candidate": is_candidate,
        })
        if not is_candidate or not row["date"] or not row["pdf_url"]:
            continue
        dt = datetime.strptime(row["date"], "%Y-%m-%d")
        if dt < SCOPE_START:
            continue
        relationships.append({"eo_number": row["eo_number"], "pdf_url": row["pdf_url"]})
        declarations.append({
            "declaration_id": f"NE-EO-{row['eo_number']}",
            "governor": governor_for(dt),
            "eo_number": row["eo_number"],
            "event_description": row["description"],
            "date_signed": row["date"],
            "archive_record_url": row["pdf_url"],
        })

    with open(actions_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["eo_number", "description", "date", "kept_as_declaration_candidate"])
        w.writeheader()
        for a in actions:
            w.writerow(a)

    with open(relationships_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["eo_number", "pdf_url"])
        w.writeheader()
        for r in relationships:
            w.writerow(r)

    with open(join_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["declaration_id", "governor", "eo_number", "event_description",
                        "date_signed", "archive_record_url"],
            lineterminator="\n",
        )
        w.writeheader()
        seen = set()
        for d in declarations:
            if d["declaration_id"] in seen:
                continue
            seen.add(d["declaration_id"])
            w.writerow(d)

    return len(declarations)


def main():
    parser = argparse.ArgumentParser(description="Scrape Nebraska disaster/emergency declarations")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    n = collect(args.actions_out, args.relationships_out, args.join_out)
    print(f"Nebraska: wrote {n} declaration(s) to {args.join_out}")


if __name__ == "__main__":
    main()
