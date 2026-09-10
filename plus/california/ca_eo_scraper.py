"""Collect California weather-emergency proclamations from the Governor's site."""
from __future__ import annotations

import argparse
import csv
import html
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE = "CA"
GOVERNOR = "Gavin Newsom"
ARCHIVE = "https://www.gov.ca.gov/?s=state+of+emergency"
API = "https://www.gov.ca.gov/wp-json/wp/v2/posts"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)", "Accept": "application/json"}
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
DECLARATION_RE = re.compile(r"\b(?:proclaims?|declares?|issues?)\b.*\bstate of emergency\b|\bstate of emergency\b.*\b(?:proclamation|proclaims?|declares?|issued?)\b", re.I)
NON_RECORD_RE = re.compile(r"^(?:what they(?:'|’)re saying|statement|readout|governor newsom visits)", re.I)
MODIFIER_RE = re.compile(r"\b(?:terminat(?:e|es|ed|ing|ion)|rescind(?:s|ed|ing)?|amend(?:s|ed|ing|ment)|extend(?:s|ed|ing)|extension)\b", re.I)
HAZARD_RE = re.compile(r"\b(?:drought|wildfires?|fires?|flood(?:ing)?|heavy rain|rainstorms?|storms?|hurricanes?|tropical storms?|winter storms?|snow|ice|blizzard|severe weather|atmospheric river|high winds?|wind event|bomb cyclone|tornado(?:es)?)\b", re.I)


@dataclass(frozen=True)
class Action:
    post_id: int
    title: str
    excerpt: str
    date: str
    url: str

    @property
    def stable_id(self) -> str:
        return f"CA-PROC-{self.post_id}"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html.unescape(value or ""), "html.parser").get_text(" ", strip=True)).strip()


def collect(session: requests.Session | None = None) -> list[Action]:
    session = session or requests.Session()
    found: dict[int, Action] = {}
    for page in range(1, 100):
        response = session.get(API, params={"search": "state of emergency", "per_page": 100, "page": page, "_fields": "id,date,link,title,excerpt"}, headers=HEADERS, timeout=60)
        if response.status_code == 400:
            break
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        for item in batch:
            date = str(item.get("date", ""))[:10]
            if date and date < "2019-01-07":
                continue
            found[int(item["id"])] = Action(int(item["id"]), clean(item.get("title", {}).get("rendered", "")), clean(item.get("excerpt", {}).get("rendered", "")), date, item.get("link", ""))
    return sorted(found.values(), key=lambda x: (x.date, x.post_id), reverse=True)


def classify(action: Action) -> str:
    if NON_RECORD_RE.search(action.title):
        return "administrative"
    if MODIFIER_RE.search(action.title):
        word = MODIFIER_RE.search(action.title).group(0).lower()
        return "termination" if word.startswith(("terminat", "rescind")) else "extension" if word.startswith("extend") else "amendment"
    if DECLARATION_RE.search(action.title):
        return "declaration"
    return "administrative"


def write_csv(path: str | Path, fields, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions: list[Action], actions_out, relationships_out, join_out) -> None:
    action_rows, joins = [], []
    for action in actions:
        kind = classify(action)
        description = action.title
        # Use the declaration headline itself. Incidental words in a summary
        # (for example, an earthquake that also caused small fires) must not
        # silently turn into a fire classification.
        weather = bool(HAZARD_RE.search(action.title))
        row = {"declaration_id": action.stable_id, "state": STATE, "governor": GOVERNOR, "eo_number": f"Proclamation {action.post_id}", "action_kind": "emergency_proclamation" if kind != "administrative" else "news_release", "action_type": kind, "event_description": description, "date_signed": action.date, "end_date": "", "weather_related": str(kind == "declaration" and weather).lower(), "source_scope": "california_governor_search", "document_format": "html", "detail_url": action.url, "archive_record_url": action.url}
        action_rows.append(row)
        if kind == "declaration" and weather:
            joins.append({field: row[field] for field in JOIN_FIELDS})
    write_csv(actions_out, ACTION_FIELDS, action_rows)
    write_csv(relationships_out, REL_FIELDS, [])
    write_csv(join_out, JOIN_FIELDS, joins)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    write_outputs(collect(), args.actions_out, args.relationships_out, args.join_out)


if __name__ == "__main__":
    main()
