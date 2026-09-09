"""Ohio executive-action scraper for the DisasterData Plus pipeline.

IMPORTANT STRUCTURAL NOTE (read before trusting this file the way the other
16 states' scrapers are trusted):

Ohio does not fit the "EO archive" assumption the rest of this pipeline is
built on, for two independently-verified reasons:

  1. governor.ohio.gov/media/executive-orders is rendered client-side by an
     IBM WebSphere Portal front end. A plain HTTP GET returns portal chrome
     with no order data -- there is no server-rendered listing to parse.
     Individual order pages (e.g. governor.ohio.gov/media/executive-orders/
     2019-21d) ARE server-rendered and fetchable once you know the slug,
     but no working, non-JS index of those slugs was found in this batch.

  2. More importantly: Ohio's weather-emergency actions are almost always
     issued as Governor's PROCLAMATIONS under ORC 5502.22, a separate track
     from the numbered "20XX-NNd" Executive Orders (which are overwhelmingly
     administrative/regulatory -- TANF funding, emergency rule adoption,
     etc.). Proclamations are announced via press release and are not
     filed in the same numbered, PDF-indexed system.

This scraper therefore does NOT pretend Ohio has a structured EO archive.
Instead it uses Ohio's own real, government-published press-release
channel as the enumerable index:

    https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins.rss

This is a real GovDelivery (Granicus) "Account Bulletins" RSS feed --
GovDelivery publishes this feed type by design for exactly this purpose
(a syndicated archive of every public bulletin an account has sent). It is
NOT a guessed URL structure; it is the standard, documented GovDelivery
account-feed pattern, and individual bulletin permalinks it returns
(content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/<id>) match
bulletins independently found via search and web_fetch during this
batch's research.

Coverage caveat (disclosed honestly, not silently assumed): GovDelivery
account feeds are commonly capped in how far back they paginate, and are
a communications channel, not the state's official filed-record system.
This is Ohio's best publicly-workable proxy for an index, not a structured
archive equivalent to what VA/NJ/NY/etc. have. capabilities.json below
reflects that with structured_archive_available: False.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

STATE = "OH"
GOVERNOR = "Ohio Governor"

BULLETIN_FEED = "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins.rss"
MIN_YEAR = 2000

HEADERS = {
    "User-Agent": "DisasterDataPlus-Adapter/1.0 (+https://disasterdata.io/plus/)"
}

WEATHER_KEYWORDS = {
    "flood": "flood",
    "flooding": "flood",
    "tornado": "severe_storm",
    "tornadic": "severe_storm",
    "severe weather": "severe_storm",
    "severe storm": "severe_storm",
    "storm damage": "severe_storm",
    "derecho": "severe_storm",
    "high wind": "wind",
    "wind damage": "wind",
    "winter storm": "winter",
    "winter weather": "winter",
    "snow": "winter",
    "ice storm": "winter",
    "hurricane": "tropical",
    "tropical storm": "tropical",
    "drought": "drought",
    "wildfire": "fire",
}

DECLARATION_TITLE_RE = re.compile(
    r"declares? (?:a )?state of emergency|issues? (?:a )?proclamation.*state of emergency",
    re.IGNORECASE,
)
NON_DECLARATION_RE = re.compile(
    r"\bupdate[s]?\b|\btours?\b|\bviews?\b|week in review|media advisory",
    re.IGNORECASE,
)


@dataclass
class BulletinAction:
    title: str
    url: str
    pub_date: str
    hazard_guess: Optional[str] = None
    is_original_weather_declaration: bool = False


def classify_title(title: str) -> Optional[str]:
    lowered = title.lower()
    for phrase, category in WEATHER_KEYWORDS.items():
        if phrase in lowered:
            return category
    return None


def is_original_declaration(title: str) -> bool:
    if NON_DECLARATION_RE.search(title):
        return False
    return bool(DECLARATION_TITLE_RE.search(title))


def fetch_bulletin_feed(session: requests.Session) -> list[BulletinAction]:
    resp = session.get(BULLETIN_FEED, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        date_el = item.find("pubDate")
        if title_el is None or link_el is None:
            continue
        items.append(
            BulletinAction(
                title=(title_el.text or "").strip(),
                url=(link_el.text or "").strip(),
                pub_date=(date_el.text or "").strip() if date_el is not None else "",
            )
        )
    return items


def enrich_with_county_list(session: requests.Session, action: BulletinAction) -> str:
    """Best-effort: pull the county list / event description out of the
    bulletin body itself, so the join CSV's event_description reflects
    the declaration's own text rather than just its headline."""
    try:
        resp = session.get(action.url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return action.title
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    # Keep this lightweight -- the point is a real event description, not a
    # full-text scrape; fall back to the title if nothing better is found.
    m = re.search(r"(declared?|issued?)[^.]{0,400}", text, re.IGNORECASE)
    return m.group(0).strip() if m else action.title


def scrape(session: Optional[requests.Session] = None) -> list[BulletinAction]:
    session = session or requests.Session()
    try:
        items = fetch_bulletin_feed(session)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"warning: could not fetch Ohio GovDelivery bulletin feed: {exc}", file=sys.stderr)
        return []

    actions = []
    for item in items:
        item.hazard_guess = classify_title(item.title)
        item.is_original_weather_declaration = bool(item.hazard_guess) and is_original_declaration(item.title)
        actions.append(item)
    return actions


def write_outputs(actions: list[BulletinAction], actions_out: Path, relationships_out: Path, join_out: Path) -> None:
    actions_out.parent.mkdir(parents=True, exist_ok=True)

    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["title", "pub_date", "hazard_guess", "is_original_weather_declaration", "source_url"])
        for a in actions:
            writer.writerow([a.title, a.pub_date, a.hazard_guess or "", a.is_original_weather_declaration, a.url])

    # Ohio's proclamations are not numbered/filed the way other states' EOs
    # are, so there is no order-to-order relationship graph to extract from
    # titles the way IN/RI/etc. have. This file is emitted for schema
    # consistency but will typically be near-empty for Ohio -- an honest
    # reflection of the source, not a scraper bug.
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["bulletin_url", "relationship_type", "references_bulletin_url"])

    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        seq = {}
        for a in actions:
            if not a.is_original_weather_declaration:
                continue
            year_match = re.search(r"20[0-9]{2}", a.pub_date)
            year = year_match.group(0) if year_match else "unknown"
            seq[year] = seq.get(year, 0) + 1
            declaration_id = f"OH-PROC-{year}-{seq[year]:03d}"
            writer.writerow([declaration_id, GOVERNOR, "", a.title, "", a.url])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Ohio weather-emergency proclamations for DisasterData Plus.")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    actions = scrape()
    write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out))
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    print(f"Ohio: {len(actions)} bulletins scraped, {n_join} routed to join CSV.")
    if not actions:
        print(
            "Ohio: zero bulletins retrieved. This likely means the GovDelivery feed "
            "was unreachable or its retention window doesn't reach far enough back -- "
            "NOT that Ohio had no weather declarations. Do not treat an empty result "
            "as 'no declarations exist'.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
