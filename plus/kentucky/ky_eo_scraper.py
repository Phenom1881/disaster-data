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
from datetime import date, timedelta, timezone
from email.utils import parsedate_to_datetime
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


# The newsroom feed (checked Sep 2026) is a working RSS feed of the
# Governor's releases, about eight months deep, but its items link to
# kentucky.gov release pages, not to the signed PDFs, so the attachment
# pattern above finds nothing in it. That is why every run reported
# "0 orders scraped". A release that announces a weather state of emergency
# is therefore read as a declaration in its own right: its title and date
# are the Governor's own, and it gets the order number only if a PDF link
# does appear with it.
SOE_TITLE_RE = re.compile(
    r"\b(?:declares?|declared|declaring|issues|issued|signs|signed)\b.{0,60}?\b(?:state of emergency|statewide emergency)\b",
    re.I)
# Follow-ups and near-misses: an extension, an amendment, an update, "remains
# in effect", "likely", and orders that end one.
SOE_EXCLUDE_RE = re.compile(
    r"\b(?:extend\w*|extension|renew\w*|amend\w*|expand\w*|updat\w*|remain\w*|likely|possible|"
    r"consider\w*|lift\w*|end(?:s|ed|ing)?|rescind\w*|terminat\w*)\b", re.I)
# Orders whose subject is not the weather itself (gas prices, price gouging
# on its own) count only when the headline itself names the weather.
SOE_OFF_TOPIC_RE = re.compile(r"\b(?:price[- ]gouging|gas prices|fuel|opioid\w*|overdose\w*|cyber\w*|shutdown|snap|food)\b", re.I)
SOE_WEATHER_RE = re.compile(r"\b(?:weather|storms?|flood\w*|tornad\w*|winter|snow\w*|ice|winds?|rain\w*|"
                            r"wildfires?|drought|landslides?)\b", re.I)
SAME_EVENT_DAYS = 3   # releases this close together are one declaration


@dataclass
class ReleaseDeclaration:
    title: str
    url: str
    date_signed: str


def feed_items(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as exc:
        print(f"warning: Kentucky newsroom feed was not XML: {exc}", file=sys.stderr)
        return []
    items = []
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(tag) or "").strip()
        items.append({"title": get("title"), "link": get("link"), "pubDate": get("pubDate"),
                      "description": get("description")})
    return items


try:
    from zoneinfo import ZoneInfo
    _KY_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - no tz database; Eastern standard time is close enough
    _KY_TZ = timezone(timedelta(hours=-5))


def release_date(pub_date: str) -> str:
    """The release's date in Kentucky. The feed stamps items in GMT, so an
    evening release would otherwise carry the next day's date."""
    try:
        stamp = parsedate_to_datetime(pub_date)
    except (TypeError, ValueError, IndexError):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(_KY_TZ).date().isoformat()


def is_weather_declaration_release(title: str, description: str = "") -> bool:
    if not SOE_TITLE_RE.search(title) or SOE_EXCLUDE_RE.search(title):
        return False
    if SOE_OFF_TOPIC_RE.search(title):
        return bool(SOE_WEATHER_RE.search(title))
    return bool(SOE_WEATHER_RE.search(title + " " + description))


def release_declarations(items: list[dict]) -> list[ReleaseDeclaration]:
    """Weather state-of-emergency releases, oldest first. Releases within
    SAME_EVENT_DAYS of an earlier one are follow-ups on the same declaration
    ("... as Winter Storm Arrives") and are not counted again."""
    found = []
    for it in items:
        title = " ".join(it["title"].split())
        if is_weather_declaration_release(title, it.get("description", "")):
            day = release_date(it["pubDate"])
            if day:
                found.append(ReleaseDeclaration(title, it["link"], day))
    out = []
    for r in sorted(found, key=lambda x: x.date_signed):
        if not _near(r.date_signed, {x.date_signed for x in out}, SAME_EVENT_DAYS):
            out.append(r)
    return out


def scrape(session: Optional[requests.Session] = None, stats: Optional[dict] = None):
    """(orders found by PDF link, weather state-of-emergency releases)."""
    session = session or requests.Session()
    stats = {} if stats is None else stats
    try:
        resp = session.get(NEWSROOM_FEED, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"warning: could not fetch Kentucky newsroom feed: {exc}", file=sys.stderr)
        return [], []

    actions = extract_attachment_links(resp.text)
    items = feed_items(resp.text)
    releases = release_declarations(items)
    stats.update(feed_items=len(items), releases=len(releases))

    # De-duplicate by EO number; keep earliest-seen date.
    dedup: dict[str, OrderAction] = {}
    for a in actions:
        if a.eo_number not in dedup:
            dedup[a.eo_number] = a
    result = [a for a in dedup.values() if int(a.date_signed[:4]) >= MIN_YEAR]
    # A release announcing an order already found by its PDF is the same declaration.
    pdf_days = {a.date_signed for a in result if a.is_original_weather_declaration}
    releases = [r for r in releases if not _near(r.date_signed, pdf_days)]
    return result, releases


def _near(day: str, days: set, window: int = SAME_EVENT_DAYS) -> Optional[str]:
    """The entry of days closest to day within window days, if any (the
    order and its releases can be a few days apart: one ahead of a storm,
    one as it arrives)."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    for delta in sorted(range(-window, window + 1), key=abs):
        cand = (d + timedelta(days=delta)).isoformat()
        if cand in days:
            return cand
    return None


def saved_join(join_out: Path) -> list[dict]:
    try:
        with join_out.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def write_outputs(actions: list[OrderAction], actions_out: Path, relationships_out: Path, join_out: Path,
                  releases: Optional[list] = None) -> None:
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

    # Weather state-of-emergency releases. One that matches a saved record
    # by date (within a day) is that record, written back unchanged, so a
    # reviewed description is not replaced by a headline. A new one is named
    # by its date, KY-SOE-YYYY-MM-DD, until someone adds its order number.
    saved = saved_join(join_out)
    saved_by_day = {}
    for r in saved:
        saved_by_day.setdefault(r.get("date_signed", ""), r)
    release_rows = []
    for r in sorted(releases or [], key=lambda x: x.date_signed):
        hit = _near(r.date_signed, set(saved_by_day))
        if hit:
            row = saved_by_day[hit]
            release_rows.append([row["declaration_id"], row["governor"], row["eo_number"],
                                 row["event_description"], row["date_signed"], row["archive_record_url"]])
        else:
            release_rows.append([f"KY-SOE-{r.date_signed}", GOVERNOR, "", r.title, r.date_signed, r.url])

    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        written = set()
        for a in sorted(actions, key=lambda x: x.date_signed):
            if not a.is_original_weather_declaration:
                continue
            declaration_id = f"KY-EO-{a.eo_number}"
            written.add(declaration_id)
            writer.writerow([declaration_id, GOVERNOR, a.eo_number, a.slug.title(), a.date_signed, a.url])
        for row in release_rows:
            if row[0] not in written:
                written.add(row[0])
                writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Kentucky executive orders for DisasterData Plus.")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    stats = {}
    actions, releases = scrape(stats=stats)
    write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out), releases)
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    print(f"Kentucky: {stats.get('feed_items', 0)} newsroom releases read, {len(actions)} orders found by PDF link "
          f"({n_join} routed to join CSV), {len(releases)} weather state-of-emergency releases.")
    if not actions and not stats.get("feed_items"):
        print(
            "Kentucky: zero orders retrieved from the newsroom feed. The feed's "
            "retention window is unconfirmed and known to lean recent -- do not "
            "treat an empty result as 'Kentucky had no weather declarations'.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
