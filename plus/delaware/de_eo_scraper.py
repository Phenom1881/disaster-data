"""Collect Delaware state-of-emergency declarations from the Governor archive."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ARCHIVE_URL = "https://governor.delaware.gov/state-of-emergency/"
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
    r"rain storm|hurricanes?|tropical storms?|cyclone|blizzard|winter storms?|"
    r"winter weather|snow(?:fall|storm)?|ice storm|nor['’]?easter|severe storms?|"
    r"severe weather|thunderstorms?|tornado(?:es)?|wind storms?|high winds?|"
    r"damaging winds?|wind gusts?)\b", re.I,
)


@dataclass
class Action:
    title: str
    date_signed: Optional[str]
    detail_url: str
    document_url: str = ""
    action_type: str = "declaration"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:56]
        return f"DE-SOE-{self.date_signed or 'UNDATED'}-{slug}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s+", " ", raw.strip())
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def classify_title(title: str) -> str:
    lowered = title.lower()
    if re.search(r"\b(termination|terminate[sd]?|rescission|rescind(?:ed|s)?)\b", lowered):
        return "termination"
    if re.search(r"\b(modification|modify|modified|amendment|amend(?:ed|s)?)\b", lowered):
        return "amendment"
    if re.search(r"\b(extension|extend(?:ed|s)?)\b", lowered):
        return "extension"
    return "declaration"


def parse_archive_page(html: str) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    for item in soup.select(".state-of-emergency-archive li"):
        link = item.select_one("a.text-primary[href]")
        if not link:
            continue
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        date_node = item.select_one("span")
        signed = normalize_date(date_node.get_text(" ", strip=True)) if date_node else None
        pdf = item.select_one('a[href*=".pdf" i]')
        action = Action(
            title=title,
            date_signed=signed,
            detail_url=urljoin(ARCHIVE_URL, link.get("href", "")),
            document_url=urljoin(ARCHIVE_URL, pdf.get("href", "")) if pdf else "",
        )
        action.action_type = classify_title(title)
        action.weather_related = bool(HAZARD_RE.search(title))
        actions.append(action)
    return actions


def collect() -> list[Action]:
    response = fetch(ARCHIVE_URL)
    if response is None:
        return []
    unique = {action.stable_id: action for action in parse_archive_page(response.text)}
    return sorted(unique.values(), key=lambda action: (action.date_signed or "", action.stable_id), reverse=True)


def build_relationships(actions: list[Action]) -> list[dict[str, str]]:
    declarations = [a for a in actions if a.action_type == "declaration"]
    rows: list[dict[str, str]] = []
    for action in actions:
        if action.action_type not in {"amendment", "extension", "termination"}:
            continue
        same_day = [target for target in declarations if target.date_signed == action.date_signed]
        candidates = same_day or [
            target for target in declarations
            if target.date_signed and action.date_signed and target.date_signed <= action.date_signed
            and bool(HAZARD_RE.search(target.title)) == bool(HAZARD_RE.search(action.title))
        ]
        if not candidates:
            continue
        target = max(candidates, key=lambda candidate: (candidate.date_signed or "", candidate.stable_id))
        relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
        rows.append({
            "source_order_id": action.stable_id,
            "target_order_id": target.stable_id,
            "relationship_type": relation,
            "relationship_text": action.title,
            "relationship_source": "official_archive_title_and_chronology",
            "confidence": "medium",
        })
    return rows


def action_row(action: Action) -> dict[str, str]:
    return {
        "declaration_id": action.stable_id,
        "state": "DE",
        "governor": "Matthew Meyer",
        "eo_number": "",
        "action_kind": "emergency_declaration",
        "action_type": action.action_type,
        "event_description": action.title,
        "date_signed": action.date_signed or "",
        "end_date": "",
        "weather_related": "true" if action.weather_related else "false",
        "source_scope": "meyer_state_of_emergency_archive",
        "document_format": "pdf" if action.document_url else "html",
        "detail_url": action.document_url or action.detail_url,
        "archive_record_url": action.detail_url,
    }


def write_csv(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions: list[Action], actions_out: str, relationships_out: str, join_out: str) -> None:
    action_rows = [action_row(action) for action in actions]
    write_csv(actions_out, ACTION_FIELDS, action_rows)
    write_csv(relationships_out, REL_FIELDS, build_relationships(actions))
    joins = [
        {field: row[field] for field in JOIN_FIELDS}
        for action, row in zip(actions, action_rows)
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
    joins = sum(a.action_type == "declaration" and a.weather_related for a in actions)
    print(f"Delaware: {len(actions)} actions, {len(build_relationships(actions))} relationships, {joins} weather declarations")


if __name__ == "__main__":
    main()
