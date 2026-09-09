"""Collect West Virginia emergency proclamations from the Governor news archive."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ARCHIVE_URL = "https://governor.wv.gov/allnews/all"
JANUARY_2025_SOE_URL = "https://governor.wv.gov/article/gov-morrisey-urges-caution-reminds-west-virginians-be-vigilant-and-prepare-expected-extreme"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)"}
ACTION_FIELDS = (
    "declaration_id", "state", "governor", "eo_number", "action_kind",
    "action_type", "event_description", "date_signed", "end_date",
    "weather_related", "source_scope", "document_format", "detail_url",
    "archive_record_url",
)
REL_FIELDS = (
    "source_order_id", "target_order_id", "relationship_type",
    "relationship_text", "relationship_source", "confidence",
)
JOIN_FIELDS = (
    "declaration_id", "governor", "eo_number", "event_description",
    "date_signed", "archive_record_url",
)
HAZARD_RE = re.compile(
    r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|"
    r"rain storm|rainstorms?|hurricanes?|tropical storms?|cyclone|blizzard|winter storms?|"
    r"winter weather|snow(?:fall|storm)?|ice storm|nor['’]?easter|severe storms?|"
    r"severe weather|thunderstorms?|tornado(?:es)?|wind storms?|high winds?|"
    r"damaging winds?|wind gusts?)\b", re.I,
)
RELEVANT_RE = re.compile(
    r"\b(declares? state of (?:emergency|preparedness)|state of preparedness|"
    r"extends? state of emergency|adds? .+ to state of emergency|"
    r"terminates? state of emergency|lifts? state of emergency)\b", re.I,
)


@dataclass
class Action:
    title: str
    date_signed: str
    detail_url: str
    archive_url: str
    governor: str = "Patrick Morrisey"
    source_scope: str = "morrisey_governor_news_archive"
    document_format: str = "html"
    description: str = ""
    document_text: str = ""
    action_type: str = "declaration"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        slug = re.sub(r"^governor-(?:patrick-)?morrisey-", "", slug)[:60]
        return f"WV-PROC-{self.date_signed}-{slug}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def classify_title(title: str) -> str:
    lowered = title.lower()
    if re.search(r"\b(terminates?|lifts?) state of emergency\b", lowered):
        return "termination"
    if re.search(r"\bextends? state of emergency\b", lowered):
        return "extension"
    if re.search(r"\badds? .+ to state of emergency\b", lowered):
        return "amendment"
    return "declaration"


def parse_archive_page(html: str, archive_url: str = ARCHIVE_URL) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    for row in soup.select(".view-news-an .view-content > .views-row"):
        link = row.select_one('a[href^="/article/"]')
        time = row.select_one("time[datetime]")
        if not link or not time:
            continue
        title = re.sub(r"^Read article:\s*", "", link.get("title", "") or "", flags=re.I)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or not RELEVANT_RE.search(title):
            continue
        signed = time.get("datetime", "")[:10]
        action = Action(title, signed, urljoin(archive_url, link.get("href", "")), archive_url)
        action.action_type = classify_title(title)
        actions.append(action)
    return actions


def hazard_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    for sentence in re.split(r"(?<=[.!?])\s+", clean):
        if HAZARD_RE.search(sentence):
            return sentence[:500].strip()
    return ""


def enrich(action: Action) -> None:
    action.description = action.title
    evidence = action.title
    if not HAZARD_RE.search(evidence):
        response = fetch(action.detail_url)
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            bodies = soup.select(".node--article--full .field--name-body")
            body = max(bodies, key=lambda node: len(node.get_text(" ", strip=True))) if bodies else soup.select_one("main")
            action.document_text = body.get_text(" ", strip=True) if body else ""
            sentence = hazard_sentence(action.document_text)
            if sentence:
                action.description = f"{action.title} — {sentence}"
                evidence = sentence
    action.weather_related = bool(HAZARD_RE.search(evidence))


def collect() -> list[Action]:
    actions: list[Action] = []
    for page_number in range(40):
        page_url = f"{ARCHIVE_URL}?page={page_number}"
        response = fetch(page_url)
        if response is None:
            break
        parsed = parse_archive_page(response.text, page_url)
        actions.extend(parsed)
        soup = BeautifulSoup(response.text, "html.parser")
        if not soup.select_one(".view-news-an .view-content > .views-row") or not soup.select_one('a[rel="next"]'):
            break
    unique = {action.stable_id: action for action in actions}
    transition_declaration = Action(
        "State of Emergency issued January 5, 2025 — extreme cold and winter weather",
        "2025-01-05",
        JANUARY_2025_SOE_URL,
        JANUARY_2025_SOE_URL,
        governor="Jim Justice",
        source_scope="official_governor_transition_article",
        document_format="html",
    )
    transition_declaration.weather_related = True
    transition_declaration.description = transition_declaration.title
    unique.setdefault(transition_declaration.stable_id, transition_declaration)
    for action in unique.values():
        if not action.description:
            enrich(action)
    return sorted(unique.values(), key=lambda action: (action.date_signed, action.stable_id), reverse=True)


def action_row(action: Action) -> dict[str, str]:
    return {
        "declaration_id": action.stable_id, "state": "WV", "governor": action.governor,
        "eo_number": "", "action_kind": "emergency_proclamation",
        "action_type": action.action_type, "event_description": action.description,
        "date_signed": action.date_signed, "end_date": "",
        "weather_related": "true" if action.weather_related else "false",
        "source_scope": action.source_scope, "document_format": action.document_format,
        "detail_url": action.detail_url, "archive_record_url": action.detail_url,
    }


def write_csv(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions: list[Action], actions_out: str, relationships_out: str, join_out: str) -> None:
    rows = [action_row(action) for action in actions]
    write_csv(actions_out, ACTION_FIELDS, rows)
    # Proclamations on this archive have no order numbers. Avoid inventing links between
    # concurrent county declarations and later extensions/amendments.
    write_csv(relationships_out, REL_FIELDS, [])
    joins = [
        {field: row[field] for field in JOIN_FIELDS}
        for action, row in zip(actions, rows)
        if action.action_type == "declaration" and action.weather_related and action.date_signed
    ]
    write_csv(join_out, JOIN_FIELDS, joins)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    actions = collect()
    write_outputs(actions, args.actions_out, args.relationships_out, args.join_out)
    joins = sum(action.action_type == "declaration" and action.weather_related for action in actions)
    print(f"West Virginia: {len(actions)} actions, 0 relationships, {joins} weather declarations")


if __name__ == "__main__":
    main()
