#!/usr/bin/env python3
"""
Kansas disaster-declaration scraper for the DisasterData Plus corridor.

Source (real, structured, publicly accessible, confirmed fetchable - not
robots-blocked): the Kansas Adjutant General's Department (KDEM) page
    https://www.kansastag.gov/388/Kansas-Disaster-Declarations
which lists, grouped by year (2009-present), every State of Disaster
Emergency Proclamation with a direct link to the real signed PDF hosted
at kansastag.gov/DocumentCenter/View/<id>/<slug>.

This is Kansas's own emergency-management system of record, distinct
from (and a much more reliable machine-readable source than) the Kansas
Register's per-issue HTML pages at sos.ks.gov, which publish the same
proclamations but one issue at a time with no combined index.

CLI contract (matches every other Plus-corridor state adapter):
    --actions-out         <path>   raw per-row action records (debug/audit trail)
    --relationships-out   <path>   year -> declaration link graph (debug/audit trail)
    --join-out            <path>   declarations_for_join.csv (the file build-plus.py reads)
"""
import argparse
import csv
import re
import sys
from datetime import datetime

import requests

STATE = "KS"
BASE = "https://www.kansastag.gov"
SOURCE_URL = f"{BASE}/388/Kansas-Disaster-Declarations"
SCOPE_START = datetime(2000, 1, 1)

# Kansas governors by inauguration date (month-precision is enough for
# every date range this page lists back to 2009).
GOVERNOR_BY_DATE = [
    (datetime(2009, 4, 28), "Mark Parkinson"),
    (datetime(2011, 1, 10), "Sam Brownback"),
    (datetime(2018, 1, 31), "Jeff Colyer"),
    (datetime(2019, 1, 14), "Laura Kelly"),
]

# Entries whose PDF filename/slug or bracketing text signals they are not
# a weather/disaster proclamation at all, or that the page itself appears
# to have a data-entry problem (see README / summary report). Left out of
# declarations_for_join.csv rather than silently included, and reported.
NON_WEATHER_OR_SUSPECT_SLUGS = {
    "hantavirus",
    "gas-leak",
    "world-cup",
    "explosion",
    "covid",
    "coronavirus",
}

# This scraper only parses the modern one-heading-per-event format the
# page uses for 2016-present. 2009-2015 group several declarations under
# a single combined "State Declaration (PDF)" per year with Federal
# DR/EM/FM references mixed in above it - a structurally different
# layout that this version does not attempt to parse (see known_gaps in
# kansas.py / the delivery's summary report, rather than risk silently
# mis-attributing a heading).
MODERN_FORMAT_MIN_YEAR = 2016

# One (year_label, heading_text, pdf_url) tuple per proclamation, as they
# literally appear on the page. Populated by parse_declarations_page();
# kept as a module-level regex set here for clarity/testability.
YEAR_HEADING_RE = re.compile(r">\s*(\d{4})\s*<", re.IGNORECASE)
ENTRY_RE = re.compile(
    r'<li[^>]*>\s*([^<]+?)\s*(?:<[^>]+>\s*)*'
    r'<a[^>]+href="(https://www\.kansastag\.gov/DocumentCenter/View/(\d+)[^"]*)"[^>]*>'
    r'\s*(?:State |Sate )?Declaration \(PDF\)',
    re.IGNORECASE,
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


def _html_to_lines(html):
    """Flatten raw HTML to one logical line per block/list-item/link,
    turning <a href="URL">TEXT</a> into "[TEXT](URL)" first so links
    survive the flattening. kansastag.gov (CivicPlus) wraps each year's
    declarations in nested <div>/<li> tab-panel markup that varies enough
    year to year that matching it directly is brittle; flattening to text
    first and pattern-matching on content, the same way a human skimming
    the rendered page would, is the more robust approach and is what this
    scraper actually does at run time."""
    text = re.sub(
        r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f"[{re.sub(r'<[^>]+>', '', m.group(2)).strip()}]({m.group(1)})",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"</?(li|div|p|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [ln.strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def parse_declarations_page(html):
    """Parse the Kansas Disaster Declarations page into a list of dicts:
    {year, heading, pdf_url, doc_id}. Deliberately tolerant of the page's
    inconsistent capitalization ("State Declaration" / "Sate Declaration")
    and its 2024 entries, which reuse the same DocumentCenter id for two
    different headings (a real error on kansastag.gov itself - see the
    summary report)."""
    records = []
    current_year = None
    pending_heading = None
    for line in _html_to_lines(html):
        year_match = re.match(r"^(\d{4})$", line)
        if year_match:
            current_year = year_match.group(1)
            pending_heading = None
            continue
        # Only look at the link TEXT (inside the brackets) for "amended" /
        # "federal declaration" - several real PDF filenames contain the
        # word "amended" even though the link text itself is the plain,
        # original "State Declaration (PDF)" (e.g. 2026's April 13 Severe
        # Weather entry, whose file is named "...-amendeddocx"), and
        # checking the whole line would wrongly skip those.
        link_text_match = re.match(r"^\[([^\]]*)\]", line)
        if link_text_match and re.search(r"amend|federal declaration", link_text_match.group(1), re.IGNORECASE):
            continue
        pdf_match = re.search(
            r"\[(?:State |Sate )?Declaration \(PDF\)\]\((https://www\.kansastag\.gov/DocumentCenter/View/(\d+)[^)]*)\)",
            line,
        )
        if pdf_match and current_year and pending_heading and int(current_year) >= MODERN_FORMAT_MIN_YEAR:
            records.append({
                "year": current_year,
                "heading": pending_heading,
                "pdf_url": pdf_match.group(1),
                "doc_id": pdf_match.group(2),
            })
            pending_heading = None
            continue
        # A heading line is plain text (not a link, not a bare year) that
        # contains a parenthesised hazard tag, e.g. "April 25 - April 27
        # (Severe Weather)".
        if current_year and re.search(r"\([^)]+\)\s*$", line) and not line.startswith("["):
            pending_heading = line
    return records


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_DAY_RE = re.compile(
    r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s*(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE,
)


def parse_date_range(year, heading):
    """Best-effort start date from a heading like 'April 25 - April 27
    (Severe Weather)', 'January 24 (Winter Storms)', 'December 26-27
    (Winter Storm)' (no space around the hyphen), 'March 22nd and
    continuing (Fires)' (ordinal suffix + trailing text), or 'Feb 26
    -Mar 8 (Wildland Fires)' (irregular spacing, abbreviated month).
    Returns (date_str, hazard_text) or (None, hazard_text) if the heading
    genuinely has no recognizable month/day at its start."""
    hazard_match = re.search(r"\(([^)]+)\)\s*$", heading)
    hazard_text = hazard_match.group(1).strip() if hazard_match else heading
    date_part = heading[:hazard_match.start()].strip() if hazard_match else heading

    m = _MONTH_DAY_RE.search(date_part)
    if not m:
        return None, hazard_text
    month = _MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    try:
        dt = datetime(int(year), month, day)
    except ValueError:
        return None, hazard_text
    return dt.strftime("%Y-%m-%d"), hazard_text


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def collect(actions_out, relationships_out, join_out):
    session = requests.Session()
    html = fetch(SOURCE_URL, session)
    raw_records = parse_declarations_page(html)

    actions = []
    relationships = []
    declarations = []

    for rec in raw_records:
        actions.append({"year": rec["year"], "heading": rec["heading"], "pdf_url": rec["pdf_url"]})
        relationships.append({"source_page": SOURCE_URL, "declaration_url": rec["pdf_url"]})

        slug = slugify(rec["heading"])
        if any(bad in slug for bad in NON_WEATHER_OR_SUSPECT_SLUGS):
            continue

        date_signed, hazard_text = parse_date_range(rec["year"], rec["heading"])
        if not date_signed:
            continue
        dt = datetime.strptime(date_signed, "%Y-%m-%d")
        if dt < SCOPE_START:
            continue

        declarations.append({
            "declaration_id": f"KS-PROC-{rec['doc_id']}",
            "governor": governor_for(dt),
            "eo_number": rec["doc_id"],
            "event_description": f"{hazard_text} ({rec['heading']})",
            "date_signed": date_signed,
            "archive_record_url": rec["pdf_url"],
        })

    with open(actions_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "heading", "pdf_url"])
        w.writeheader()
        for a in actions:
            w.writerow(a)

    with open(relationships_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source_page", "declaration_url"])
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
    parser = argparse.ArgumentParser(description="Scrape Kansas disaster declarations")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    n = collect(args.actions_out, args.relationships_out, args.join_out)
    print(f"Kansas: wrote {n} declaration(s) to {args.join_out}")


if __name__ == "__main__":
    main()
