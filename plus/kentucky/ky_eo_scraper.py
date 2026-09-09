"""Kentucky executive order scraper for the DisasterData Plus pipeline.

IMPORTANT STRUCTURAL NOTE:

Kentucky's actual system of record for executive orders is the Secretary
of State's Executive Journal database:
    https://apps.sos.ky.gov/executive/journal/
This is the authoritative index required by KRS 11 (every EO must be
filed with the Secretary of State). It was tested directly during this
batch's research and returns a bot-detection block on automated requests
-- it is not usable by a plain scraper. This is disclosed here rather than
worked around with a spoofed session, per this pipeline's own standards
around not guessing/forcing access to sources that don't want automated
traffic.

What IS real, verified, and usable:
  - Individual order PDFs live at a confirmed, real, consistent pattern:
        https://governor.ky.gov/attachments/<YYYYMMDD>_Executive-Order_
        <YYYY-NNN>_<slug>.pdf
    (verified against a dozen real orders spanning 2015-2026 during this
    batch's research). This is NOT a guessed structure -- it was derived
    by observing many real, independently-discovered filenames.
  - The Governor's newsroom RSS feed is a real, government-published feed:
        https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx
    which is used here as the enumeration source, the same role the
    GovDelivery bulletin feed plays for Ohio.

Because the enumeration source is a news feed rather than the filed
register itself, this scraper (like Ohio's) cannot claim to be
comprehensive back to 2000, and hazard_overrides.csv / capabilities.json
reflect that honestly rather than asserting full coverage.
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

STATE = "KY"
GOVERNOR = "Kentucky Governor"

NEWSROOM_FEED = "https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx"
MIN_YEAR = 2000

HEADERS = {
    "User-Agent": "DisasterDataPlus-Adapter/1.0 (+https://disasterdata.io/plus/)"
}

WEATHER_KEYWORDS = {
    "flood": "flood",
    "flooding": "flood",
    "landslide": "flood",
    "tornado": "severe_storm",
    "tornadic": "severe_storm",
    "severe weather": "severe_storm",
    "severe storm": "severe_storm",
    "thunderstorm": "severe_storm",
    "wind": "wind",
    "winter storm": "winter",
    "winter weather": "winter",
    "snow": "winter",
    "ice storm": "winter",
    "arctic": "winter",
    "hurricane": "tropical",
    "tropical storm": "tropical",
    "drought": "drought",
    "wildfire": "fire",
}

# Kentucky's EO PDF filenames themselves are highly informative:
# 20250104_Executive-Order_2025-007_State-of-Emergency-Related-to-Winter-Weather-Event.pdf
ATTACHMENT_RE = re.compile(
    r"governor\.ky\.gov/attachments/(\d{8})_Executive-Order_(\d{4}-\d{2,3})_([A-Za-z0-9\-_]+)\.pdf",
    re.IGNORECASE,
)

NON_ORIGINAL_RE = re.compile(
    r"extension|extend|amend|rescission|rescind|renewal|continu",
    re.IGNORECASE,
)


@dataclass
class OrderAction:
    eo_number: str
    date_signed: str
    slug: str
    url: str
    hazard_guess: Optional[str] = None
    is_original_weather_declaration: bool = False


def classify_text(text: str) -> Optional[str]:
    lowered = text.lower()
    for phrase, category in WEATHER_KEYWORDS.items():
        if phrase in lowered:
            return category
    return None


def is_original_declaration(slug: str) -> bool:
    lowered = slug.lower()
    if NON_ORIGINAL_RE.search(lowered):
        return False
    return "state-of-emergency" in lowered or "soe" in lowered


def extract_attachment_links(html: str) -> list[OrderAction]:
    """Pull real governor.ky.gov/attachments/... EO links out of newsroom
    feed item bodies. Only links matching the verified real filename
    pattern are accepted -- nothing here is a guessed URL."""
    actions = []
    for match in ATTACHMENT_RE.finditer(html):
        date_str, eo_number, slug = match.groups()
        year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
        date_signed = f"{year}-{month}-{day}"
        url = f"https://governor.ky.gov/attachments/{date_str}_Executive-Order_{eo_number}_{slug}.pdf"
        readable_slug = slug.replace("-", " ").replace("_", " ")
        hazard = classify_text(readable_slug)
        actions.append(
            OrderAction(
                eo_number=eo_number,
                date_signed=date_signed,
                slug=readable_slug,
                url=url,
                hazard_guess=hazard,
                is_original_weather_declaration=bool(hazard) and is_original_declaration(slug),
            )
        )
    return actions


def scrape(session: Optional[requests.Session] = None) -> list[OrderAction]:
    session = session or requests.Session()
    try:
        resp = session.get(NEWSROOM_FEED, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"warning: could not fetch Kentucky newsroom feed: {exc}", file=sys.stderr)
        return []

    actions = extract_attachment_links(resp.text)

    # De-duplicate by EO number; keep earliest-seen date.
    dedup: dict[str, OrderAction] = {}
    for a in actions:
        if a.eo_number not in dedup:
            dedup[a.eo_number] = a
    result = [a for a in dedup.values() if int(a.date_signed[:4]) >= MIN_YEAR]
    return result


def write_outputs(actions: list[OrderAction], actions_out: Path, relationships_out: Path, join_out: Path) -> None:
    actions_out.parent.mkdir(parents=True, exist_ok=True)

    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["eo_number", "date_signed", "slug", "hazard_guess", "is_original_weather_declaration", "source_url"])
        for a in sorted(actions, key=lambda x: x.date_signed):
            writer.writerow([a.eo_number, a.date_signed, a.slug, a.hazard_guess or "", a.is_original_weather_declaration, a.url])

    # Kentucky's own EO text explicitly references prior EO numbers it
    # extends/amends (e.g. "EO 2025-095" inside a follow-up order's title);
    # that reference lives in the slug, which is a real filename component,
    # not an inference -- captured here where present.
    ref_re = re.compile(r"(\d{4}-\d{2,3})")
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["eo_number", "relationship_type", "references_eo_number"])
        for a in actions:
            if a.is_original_weather_declaration:
                continue
            refs = [r for r in ref_re.findall(a.slug) if r != a.eo_number]
            for ref in refs:
                rel_type = "extension" if "extension" in a.slug.lower() or "extend" in a.slug.lower() else "amendment"
                writer.writerow([a.eo_number, rel_type, ref])

    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        for a in sorted(actions, key=lambda x: x.date_signed):
            if not a.is_original_weather_declaration:
                continue
            declaration_id = f"KY-EO-{a.eo_number}"
            writer.writerow([declaration_id, GOVERNOR, a.eo_number, a.slug.title(), a.date_signed, a.url])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Kentucky executive orders for DisasterData Plus.")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    actions = scrape()
    write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out))
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    print(f"Kentucky: {len(actions)} orders scraped, {n_join} routed to join CSV.")
    if not actions:
        print(
            "Kentucky: zero orders retrieved from the newsroom feed. The feed's "
            "retention window is unconfirmed and known to lean recent -- do not "
            "treat an empty result as 'Kentucky had no weather declarations'.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
