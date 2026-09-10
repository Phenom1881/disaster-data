#!/usr/bin/env python3
"""
Oklahoma disaster-declaration scraper for the DisasterData Plus corridor.

Source (real, structured, publicly accessible): the Oklahoma Department of
Emergency Management's "Emergencies and Disasters" archive at
    https://oklahoma.gov/oem/emergencies-and-disasters.html
which links to one index page per year (2016-present) plus a combined
"2003-2015" archive page. Each year page links to one page per named
event; some event pages in turn link to a "Governor Declares State of
Emergency" / "Governor Declares Disaster Emergency" press page, which is
where the actual Executive Order number, affected counties, and a link to
the signed PDF live.

The Secretary of State's own Executive Orders index (sos.ok.gov/gov/
execorders.aspx) is the state's *legal* system of record for EO text, but
it returns HTTP 403 to automated fetches (confirmed directly, not
assumed) and is therefore not used as the crawl source here. The PDF
links this scraper finds are hosted at sos.ok.gov/documents/Executive/,
i.e. the same underlying legal documents, just discovered via the OEM
index instead of a blocked listing page.

Only pages whose title/link text signals an actual gubernatorial
emergency/disaster declaration are followed past the event level -
situation updates, resource pages, and price-gouging-statute notices are
left alone.

CLI contract (matches every other Plus-corridor state adapter):
    --actions-out         <path>   raw per-page action records (debug/audit trail)
    --relationships-out   <path>   event -> declaration link graph (debug/audit trail)
    --join-out            <path>   declarations_for_join.csv (the file build-plus.py reads)
"""
import argparse
import csv
import re
import sys
from datetime import datetime

import requests

STATE = "OK"
GOVERNOR = "Kevin Stitt"
BASE = "https://oklahoma.gov"
INDEX_URL = f"{BASE}/oem/emergencies-and-disasters.html"
ARCHIVE_URL = f"{BASE}/oem/emergencies-and-disasters/archive-emer-disasters.html"
YEARS = list(range(2016, 2027))
SCOPE_START = datetime(2000, 1, 1)

# A page is a candidate "declaration" page if its own link text (as shown
# on the event page) matches one of these - deliberately narrow so we
# don't follow situation updates, resource pages, or unrelated news.
DECLARATION_LINK_RE = re.compile(
    r"(governor\s+(?:declares|signs).{0,40}(?:state of emergency|disaster emergency)"
    r"|declares?\s+(?:a\s+)?(?:state of emergency|disaster emergency))",
    re.IGNORECASE,
)

EO_NUMBER_RE = re.compile(r"Executive\s+Order\s+(\d{4}-\d{1,2})", re.IGNORECASE)
DATELINE_RE = re.compile(
    r"([A-Z][a-z]+ \d{1,2},\s*\d{4})"
)
COUNTIES_RE = re.compile(
    r"declar(?:ing|es|ed)\s+(?:a\s+)?(?:state of emergency|disaster emergency)\s+"
    r"(?:in|for)\s+([^.]+?)\s+count(?:y|ies)",
    re.IGNORECASE | re.DOTALL,
)
PDF_HREF_RE = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.IGNORECASE)


def fetch(url, session):
    resp = session.get(url, timeout=30, headers={"User-Agent": "DisasterData.io research crawler"})
    resp.raise_for_status()
    return resp.text


def parse_year_index(html, year_url):
    """Return [(event_title, absolute_event_url), ...] from a year index page."""
    events = []
    for href, text in _iter_links(html):
        if not href or not text:
            continue
        if "/emergencies-and-disasters/" not in href:
            continue
        if href.rstrip("/").endswith(".html") and re.search(r"/\d{4}/[^/]+\.html$", href):
            events.append((text.strip(), _absolutize(href)))
    return events


def parse_archive_index(html):
    """The 2003-2015 combined archive page uses the same link pattern."""
    events = []
    for href, text in _iter_links(html):
        if not href or not text:
            continue
        if "/emergencies-and-disasters/" in href and re.search(r"/\d{4}/[^/]+\.html$", href):
            events.append((text.strip(), _absolutize(href)))
    return events


def parse_event_page(html):
    """Return [(link_text, absolute_url), ...] for links that look like an
    actual governor's declaration, found on an event's own page."""
    candidates = []
    for href, text in _iter_links(html):
        if not href or not text:
            continue
        if DECLARATION_LINK_RE.search(text):
            candidates.append((text.strip(), _absolutize(href)))
    return candidates


def parse_declaration_page(html, url):
    """Extract eo_number / date_signed / county description / pdf link from
    a real 'Governor Declares ...' press page. Returns None if the page
    doesn't actually contain a resolvable EO number (left for manual
    review rather than guessed)."""
    eo_match = EO_NUMBER_RE.search(html)
    if not eo_match:
        return None
    eo_number = eo_match.group(1)

    # Prefer the longest match: a page's <h1> headline sometimes says
    # something generic like "...in twelve counties" while the real body
    # paragraph names the counties individually - take whichever match
    # actually names the most, since that's the descriptive one.
    counties_matches = COUNTIES_RE.findall(html)
    event_description = None
    if counties_matches:
        event_description = re.sub(r"\s+", " ", max(counties_matches, key=len)).strip()

    date_match = DATELINE_RE.search(html)
    date_signed = None
    if date_match:
        try:
            date_signed = datetime.strptime(date_match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            date_signed = None

    pdf_match = PDF_HREF_RE.search(html)
    pdf_url = pdf_match.group(1) if pdf_match else url

    return {
        "eo_number": eo_number,
        "date_signed": date_signed,
        "event_description": event_description or "Declaration text requires manual review",
        "archive_record_url": pdf_url,
        "source_page": url,
    }


def _iter_links(html):
    """Very small dependency-free (href, text) link extractor. Real crawls
    should prefer BeautifulSoup if available; falls back to regex so this
    file has zero hard runtime dependencies beyond `requests`."""
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = m.group(1)
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        yield href, text


def _absolutize(href):
    if href.startswith("http"):
        return href
    return BASE + href


def collect(actions_out, relationships_out, join_out):
    session = requests.Session()
    actions = []
    relationships = []
    declarations = []

    year_pages = [(y, f"{BASE}/oem/emergencies-and-disasters/{y}.html") for y in YEARS]
    year_pages.append(("2003-2015", ARCHIVE_URL))

    for label, year_url in year_pages:
        try:
            html = fetch(year_url, session)
        except requests.RequestException as exc:
            print(f"WARNING: could not fetch {year_url}: {exc}", file=sys.stderr)
            continue
        events = parse_archive_index(html) if label == "2003-2015" else parse_year_index(html, year_url)
        for event_title, event_url in events:
            actions.append({"level": "event", "title": event_title, "url": event_url})
            try:
                event_html = fetch(event_url, session)
            except requests.RequestException as exc:
                print(f"WARNING: could not fetch {event_url}: {exc}", file=sys.stderr)
                continue
            decl_links = parse_event_page(event_html)
            for link_text, decl_url in decl_links:
                relationships.append({"event_url": event_url, "declaration_url": decl_url, "link_text": link_text})
                try:
                    decl_html = fetch(decl_url, session)
                except requests.RequestException as exc:
                    print(f"WARNING: could not fetch {decl_url}: {exc}", file=sys.stderr)
                    continue
                record = parse_declaration_page(decl_html, decl_url)
                actions.append({"level": "declaration", "title": link_text, "url": decl_url,
                                 "resolved": bool(record)})
                if not record or not record["date_signed"]:
                    continue
                try:
                    if datetime.strptime(record["date_signed"], "%Y-%m-%d") < SCOPE_START:
                        continue
                except ValueError:
                    continue
                declarations.append(record)

    with open(actions_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["level", "title", "url", "resolved"])
        w.writeheader()
        for a in actions:
            a.setdefault("resolved", "")
            w.writerow(a)

    with open(relationships_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_url", "declaration_url", "link_text"])
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
            decl_id = f"{STATE}-EO-{d['eo_number']}"
            if decl_id in seen:
                continue
            seen.add(decl_id)
            w.writerow({
                "declaration_id": decl_id,
                "governor": GOVERNOR,
                "eo_number": d["eo_number"],
                "event_description": d["event_description"],
                "date_signed": d["date_signed"],
                "archive_record_url": d["archive_record_url"],
            })

    return len(declarations)


def main():
    parser = argparse.ArgumentParser(description="Scrape Oklahoma disaster/emergency declarations")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    n = collect(args.actions_out, args.relationships_out, args.join_out)
    print(f"Oklahoma: wrote {n} declaration(s) to {args.join_out}")


if __name__ == "__main__":
    main()
