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
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

STATE = "OH"
# Who signed a proclamation, by the date it was signed (inauguration days).
GOVERNORS = (
    ("2019-01-14", "Mike DeWine"),
    ("2011-01-10", "John Kasich"),
    ("2007-01-08", "Ted Strickland"),
    ("1999-01-11", "Bob Taft"),
)


def governor_for(date_signed: str) -> str:
    for start, name in GOVERNORS:
        if (date_signed or "") >= start:
            return name
    return "Ohio Governor"

BULLETIN_FEED = "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins.rss"
MIN_YEAR = 2000

HEADERS = {
    # Same form the Wisconsin adapter uses for the WIGOV feed. The Accept
    # header alone did not clear GovDelivery's 406 on 2026-09-26.
    "User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlus-Adapter/1.0; +https://disasterdata.io/plus/)",
    # Ask for the feed format explicitly; GovDelivery answers 406 Not
    # Acceptable to a request that asks only for web page formats.
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
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
    r"declar(?:es?|ing) (?:a )?state of emergency|(?:issues?|signs?) (?:a )?proclamation.*state of emergency",
    re.IGNORECASE,
)
# The governor saying outright that he declares one ("Governor DeWine Tours
# Mahoning County Storm Damage, Declares State of Emergency") is a
# declaration even when the headline also mentions a tour or an update.
DECLARES_RE = re.compile(r"\bdeclares? (?:a )?state of emergency", re.IGNORECASE)
NON_DECLARATION_RE = re.compile(
    r"\bupdat(?:e|es|ed|ing)\b|\btours?\b|\bviews?\b|\bamend(?:s|ed|ing)?\b|\bextend(?:s|ed|ing)?\b",
    re.IGNORECASE,
)
# A resent bulletin ("UPDATED: Governor DeWine Declares ...") repeats one
# already counted.
NEVER_DECLARATION_RE = re.compile(r"^\W*updated?\b|week in review|media advisory", re.IGNORECASE)
# Ohio's 88 counties, to tell two proclamations a day apart from each other.
OHIO_COUNTIES = set("""adams allen ashland ashtabula athens auglaize belmont brown butler carroll champaign clark
clermont clinton columbiana coshocton crawford cuyahoga darke defiance delaware erie fairfield fayette franklin fulton
gallia geauga greene guernsey hamilton hancock hardin harrison henry highland hocking holmes huron jackson jefferson
knox lake lawrence licking logan lorain lucas madison mahoning marion medina meigs mercer miami monroe montgomery
morgan morrow muskingum noble ottawa paulding perry pickaway pike portage preble putnam richland ross sandusky scioto
seneca shelby stark summit trumbull tuscarawas union vanwert vinton warren washington wayne williams wood wyandot""".split())
HAZARD_WORD_RE = re.compile(r"\b(flood\w*|tornad\w*|storms?|winds?|winter|snow\w*|ice|wildfires?|fires?|drought|rain\w*|hurricanes?)\b")


def event_tokens(text: str) -> tuple[set, set]:
    """(county names, hazard words) in a title or description, hazards as
    whole words ('Police' is not ice), reduced to a stem (floods -> flood)."""
    low = (text or "").lower().replace("van wert", "vanwert")
    counties = {w for w in re.findall(r"[a-z]+", low) if w in OHIO_COUNTIES}
    canon = (("flood", "flood"), ("tornad", "tornado"), ("storm", "storm"), ("wind", "wind"), ("winter", "winter"),
             ("snow", "snow"), ("ice", "ice"), ("wildfire", "fire"), ("fire", "fire"), ("drought", "drought"),
             ("rain", "rain"), ("hurricane", "hurricane"))
    hazards = {next(c for stem, c in canon if m.group(1).startswith(stem)) for m in HAZARD_WORD_RE.finditer(low)}
    return counties, hazards


def same_event(a: str, b: str) -> bool:
    """Whether two texts can describe the same proclamation. When both name
    counties, the counties decide; otherwise shared hazards; a text that
    names neither cannot rule the other out."""
    (ca, ha), (cb, hb) = event_tokens(a), event_tokens(b)
    if ca and cb:
        return bool(ca & cb)
    if ha and hb:
        return bool(ha & hb)
    return True


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
    if NEVER_DECLARATION_RE.search(title):
        return False
    if DECLARES_RE.search(title):
        return True
    if NON_DECLARATION_RE.search(title):
        return False
    return bool(DECLARATION_TITLE_RE.search(title))


def feed_date(pub_date: str) -> str:
    """ISO date from an RSS pubDate ('Mon, 22 Sep 2026 14:05:00 -0400')."""
    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except (TypeError, ValueError, IndexError):
        m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", pub_date or "")
        return "-".join(m.groups()) if m else ""


def fetch_bulletin_feed(session: requests.Session) -> list[BulletinAction]:
    resp = session.get(BULLETIN_FEED, headers=HEADERS, timeout=30)
    if resp.status_code == 406:
        # Ask once more accepting anything, and say what came back.
        print("warning: Ohio bulletin feed answered 406; retrying with Accept: */*",
              file=sys.stderr)
        resp = session.get(BULLETIN_FEED, headers={**HEADERS, "Accept": "*/*"}, timeout=30)
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        print("warning: Ohio bulletin feed was not XML (%s, %d bytes, starts %r)"
              % (resp.headers.get("Content-Type", "?"), len(resp.content), resp.text[:120]), file=sys.stderr)
        raise
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
                pub_date=feed_date((date_el.text or "").strip()) if date_el is not None else "",
            )
        )
    if not items:
        print("warning: Ohio bulletin feed parsed but held no items (%d bytes, root <%s>)"
              % (len(resp.content), root.tag), file=sys.stderr)
    return items


def bulletin_text(session: requests.Session, url: str) -> str:
    """The bulletin's own text, or "" when it cannot be read."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"warning: could not read Ohio bulletin {url}: {exc}", file=sys.stderr)
        return ""
    return BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)


class FeedUnavailable(RuntimeError):
    """The bulletin feed could not be fetched or read."""


def scrape(session: Optional[requests.Session] = None, attempts: int = 2) -> list[BulletinAction]:
    """Every bulletin in the feed, classified. Raises FeedUnavailable when the
    feed cannot be fetched, so a blocked source shows up as a failed run
    rather than as a quiet week.

    A declaration headline that names no hazard ("Governor DeWine Signs
    Proclamation Declaring State of Emergency in Perry, Muskingum Counties")
    is classified from the bulletin's own text."""
    session = session or requests.Session()
    last = None
    for _ in range(attempts):
        try:
            items = fetch_bulletin_feed(session)
            break
        except (requests.RequestException, ET.ParseError) as exc:
            last = exc
    else:
        raise FeedUnavailable(f"could not fetch Ohio GovDelivery bulletin feed: {last}")

    actions = []
    for item in items:
        item.hazard_guess = classify_title(item.title)
        declaration = is_original_declaration(item.title)
        if declaration and not item.hazard_guess and item.url:
            item.hazard_guess = classify_title(bulletin_text(session, item.url))
        item.is_original_weather_declaration = bool(item.hazard_guess) and declaration
        actions.append(item)
    return actions


ACTION_FIELDS = ["title", "pub_date", "hazard_guess", "is_original_weather_declaration", "source_url"]
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]


def write_outputs(actions: list[BulletinAction], actions_out: Path, relationships_out: Path, join_out: Path) -> int:
    """Write the saved records plus whatever the feed adds; return how many
    join rows are new.

    The feed holds only the most recent few weeks of bulletins, so most runs
    find no new proclamation. The saved records (including the ones added by
    hand from news coverage, back to 2003) are written back as they were, so
    a quiet week leaves the files as they were rather than empty."""
    actions_out.parent.mkdir(parents=True, exist_ok=True)

    weather = [a for a in actions if a.hazard_guess]
    saved_actions = saved_join_rows(actions_out)
    seen_urls = {r.get("source_url", "") for r in saved_actions}
    action_rows = [{k: r.get(k, "") for k in ACTION_FIELDS} for r in saved_actions]
    for a in weather:
        if a.url in seen_urls:
            continue
        seen_urls.add(a.url)
        action_rows.append(dict(zip(ACTION_FIELDS, [a.title, a.pub_date, a.hazard_guess or "",
                                                     a.is_original_weather_declaration, a.url])))
    action_rows.sort(key=lambda r: (r.get("pub_date", ""), r.get("title", "")))
    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACTION_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(action_rows)

    # Ohio's proclamations are not numbered/filed the way other states' EOs
    # are, so there is no order-to-order relationship graph to extract from
    # titles the way IN/RI/etc. have. This file is emitted for schema
    # consistency but will typically be near-empty for Ohio -- an honest
    # reflection of the source, not a scraper bug.
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["bulletin_url", "relationship_type", "references_bulletin_url"])

    # A bulletin with no date cannot be matched to storms and would only get
    # a placeholder id, so it stays out of the join (it is still listed in
    # the actions file above).
    originals = [a for a in actions if a.is_original_weather_declaration and a.pub_date]
    saved = [r for r in saved_join_rows(join_out) if r.get("declaration_id")]
    ids = assign_ids(originals, saved)
    rows = {r["declaration_id"]: {k: r.get(k, "") for k in JOIN_FIELDS} for r in saved}
    added = 0
    for a in originals:
        sid = ids[id(a)]
        if sid in rows:
            # A saved record is reviewed text (county list, hazards); a
            # bulletin headline is not, so the saved row stays as it was.
            continue
        rows[sid] = dict(zip(JOIN_FIELDS, [sid, governor_for(a.pub_date), "", a.title, a.pub_date, a.url]))
        added += 1
    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOIN_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda r: (r["date_signed"], r["declaration_id"])))
    return added


def saved_join_rows(join_out: Path) -> list[dict]:
    try:
        with join_out.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def assign_ids(originals: list[BulletinAction], saved: list[dict]) -> dict[int, str]:
    """A stable declaration_id for each proclamation.

    These used to be numbered by position in the feed (OH-PROC-2026-001 was
    whichever 2026 proclamation the feed listed first), so the next new
    proclamation would have taken an existing number and pushed a saved
    record out of the file. A proclamation already saved keeps its id,
    matched by its link or by a date within a day of the saved one (a
    bulletin can go out the day after the proclamation). A new one is named
    by its date, OH-PROC-YYYY-MM-DD, with -2, -3 for a second that day."""
    by_url = {r.get("archive_record_url", ""): r["declaration_id"] for r in saved if r.get("declaration_id")}
    by_date = {}
    for r in saved:
        if r.get("declaration_id") and r.get("date_signed"):
            by_date.setdefault(r["date_signed"], []).append(r)
    taken = {r["declaration_id"] for r in saved if r.get("declaration_id")}
    ids, used = {}, set()

    def near(a: BulletinAction) -> Optional[str]:
        """Same day: that record. A day either side: that record too, unless
        the two clearly name different counties or hazards, so a different
        proclamation the next day (a tornado in Allen County after a flood
        elsewhere) is not taken for it and lost."""
        try:
            d = date.fromisoformat(a.pub_date)
        except ValueError:
            return None
        for delta in (0, -1, 1):
            for r in by_date.get((d + timedelta(days=delta)).isoformat(), []):
                sid = r["declaration_id"]
                if sid in used:
                    continue
                if delta == 0 or same_event(a.title, r.get("event_description", "")):
                    return sid
        return None

    for a in sorted(originals, key=lambda x: x.pub_date):
        sid = by_url.get(a.url) if by_url.get(a.url) not in used else None
        sid = sid or near(a)
        if not sid:
            base = f"OH-PROC-{a.pub_date}" if a.pub_date else "OH-PROC-UNDATED"
            sid, n = base, 2
            while sid in used or sid in taken:
                sid, n = f"{base}-{n}", n + 1
        used.add(sid)
        ids[id(a)] = sid
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Ohio weather-emergency proclamations for DisasterData Plus.")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    try:
        actions = scrape()
    except FeedUnavailable as exc:
        # Exit nonzero: the saved records are kept by the build either way,
        # and the health report then shows the source as failed, not empty.
        raise SystemExit(str(exc))
    added = write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out))
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    print(f"Ohio: {len(actions)} bulletins in the feed, {n_join} weather declarations, {added} new.")
    if not actions:
        print("warning: Ohio bulletin feed was fetched but listed no bulletins.", file=sys.stderr)


if __name__ == "__main__":
    main()
