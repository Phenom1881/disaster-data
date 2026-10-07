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
import time
from datetime import datetime
from urllib.parse import urljoin

import requests

STATE = "NE"
SOURCE_URL = "https://govdocs.nebraska.gov/docs/pilot/pubs/eoindex.html"
# The Library Commission links the index as EOIndex.html, over http, so
# both spellings are tried when the usual one fails.
INDEX_URLS = (
    SOURCE_URL,
    "https://govdocs.nebraska.gov/docs/pilot/pubs/EOIndex.html",
    "http://govdocs.nebraska.gov/docs/pilot/pubs/EOIndex.html",
)
HEADER_SETS = (
    {"User-Agent": "DisasterData.io research crawler"},
    {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"},
)
RETRY_WAITS = (0, 20)    # seconds before each round of tries
TIMEOUT = 30
# The index lists about 300 orders since 1965; a page with far fewer rows is
# an error or block page, or a cut-off download, not the index.
MIN_INDEX_ROWS = 100
WAYBACK_AVAILABLE = "https://archive.org/wayback/available"
SOURCE_NOTE = ""   # set when the index came from the Internet Archive


class IndexUnavailable(RuntimeError):
    """Neither the index nor an archived copy of it could be read."""
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

# Candidates that are not weather emergencies in Nebraska: COVID-19 orders,
# and fuel/propane supply shortages unless the title names a Nebraska
# weather cause (EO 24-01 "Fuel Supply Shortages Due to Extreme Cold
# Temperatures" stays; EO 05-8 "Hurricane impact on fuel supply" is an
# out-of-state hurricane and goes).
NOT_WEATHER_RE = re.compile(r"coronavirus|covid|pandemic|unemployment insurance", re.IGNORECASE)
SUPPLY_RE = re.compile(r"supply shortage|fuel shortage|fuel supply|propane|heating fuel|gasoline|diesel", re.IGNORECASE)
WEATHER_CAUSE_RE = re.compile(r"extreme cold|winter storm|blizzard|ice storm|flood|tornado|severe weather", re.IGNORECASE)


def is_weather_candidate(description):
    text = description or ""
    if not DECLARATION_KEYWORDS_RE.search(text) or NOT_WEATHER_RE.search(text):
        return False
    if SUPPLY_RE.search(text) and not WEATHER_CAUSE_RE.search(text):
        return False
    return True


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
    resp = session.get(url, timeout=TIMEOUT, headers=HEADER_SETS[0])
    resp.raise_for_status()
    return resp.text


def wayback_copy(url, session):
    """(html, YYYY-MM-DD) of the Internet Archive's latest copy of url, as
    originally served, or (None, "")."""
    try:
        lookup = session.get(WAYBACK_AVAILABLE, params={"url": url}, headers=HEADER_SETS[0], timeout=TIMEOUT)
        lookup.raise_for_status()
        closest = (lookup.json().get("archived_snapshots") or {}).get("closest") or {}
        stamp = str(closest.get("timestamp") or "")
        if not closest.get("available") or not re.fullmatch(r"\d{14}", stamp):
            return None, ""
        resp = session.get(f"https://web.archive.org/web/{stamp}id_/{url}", headers=HEADER_SETS[0], timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text, f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
    except (requests.RequestException, ValueError) as exc:
        print(f"warning: Internet Archive copy of {url} not read: {exc}", file=sys.stderr)
        return None, ""


def fetch_index(session, sleep=time.sleep):
    """The index's rows, from the live page or, failing that, the Internet
    Archive's latest copy. Raises IndexUnavailable with what went wrong.

    The live page is tried at both of its addresses, with the crawler's
    User-Agent and a browser's, then the usual address again 20 seconds
    later. On
    2026-10-07 one 30-second try with no retry failed the run and its retry,
    and the health report said only "scrape failed"."""
    global SOURCE_NOTE
    problems = []
    for wait in RETRY_WAITS:
        if wait:
            sleep(wait)
        # Every address on the first round; the usual one again on the
        # second. At most 8 tries of 30 seconds, since the build retries a
        # failed state once more and the whole run has a time limit.
        for url in (INDEX_URLS if not wait else INDEX_URLS[:1]):
            for headers in HEADER_SETS:
                try:
                    resp = session.get(url, timeout=TIMEOUT, headers=headers)
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    problems.append(f"{url}: {type(exc).__name__} {getattr(getattr(exc, 'response', None), 'status_code', '') or ''}".strip())
                    continue
                rows = parse_index_table(resp.text)
                if len(rows) >= MIN_INDEX_ROWS:
                    return rows
                problems.append(f"{url}: only {len(rows)} rows ({len(resp.text)} bytes)")
    for url in INDEX_URLS[:2]:
        html, copy_date = wayback_copy(url, session)
        rows = parse_index_table(html) if html else []
        if len(rows) >= MIN_INDEX_ROWS:
            SOURCE_NOTE = f"Internet Archive copy from {copy_date}"
            print(f"Nebraska: index read from the {SOURCE_NOTE} (the live index could not be read)")
            return rows
    seen = list(dict.fromkeys(problems))
    raise IndexUnavailable("Nebraska executive order index not read: " + "; ".join(seen[:4])
                           + "; no usable Internet Archive copy")


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
    and why.

    Read cell by cell with an HTML parser. The earlier single regex let a
    description run across cell and row boundaries wherever the index has
    an unclosed cell, so EO 15-03 swallowed four later rows and a 2008 date
    (found 2026-09-26). The parser closes such cells the way a browser
    does, so each row keeps its own text and date."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # lxml missing: the stdlib parser is close enough
        soup = BeautifulSoup(html, "html.parser")
    records = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        link = cells[0].find("a", href=True) or cells[1].find("a", href=True)
        href = link["href"] if link else ""
        eo_number = cells[0].get_text(" ", strip=True)
        description = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))
        dt = parse_date(cells[2].get_text(" ", strip=True))
        # The index links each order relatively ("eofiles/26-20.pdf"), which
        # was broken once shown on disasterdata.io, so resolve it here.
        pdf_url = urljoin(SOURCE_URL, href.strip()) if href else None
        records.append({
            "eo_number": eo_number,
            "description": description,
            "date": dt.strftime("%Y-%m-%d") if dt else None,
            "pdf_url": pdf_url,
        })
    return records


def collect(actions_out, relationships_out, join_out):
    session = requests.Session()
    all_rows = fetch_index(session)

    actions = []
    relationships = []
    declarations = []

    for row in all_rows:
        is_candidate = is_weather_candidate(row["description"])
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

    try:
        n = collect(args.actions_out, args.relationships_out, args.join_out)
    except IndexUnavailable as exc:
        raise SystemExit(str(exc))
    print(f"Nebraska: wrote {n} declaration(s) to {args.join_out}")


if __name__ == "__main__":
    main()
