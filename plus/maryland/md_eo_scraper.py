"""Collect Maryland executive orders from the Governor's official archive."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup


ARCHIVE_URL = "https://governor.maryland.gov/official-actions/executive-orders"
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
DECLARATION_RE = re.compile(r"\b(declaration of a state of (?:emergency|preparedness)|declaring a state of preparedness|state of preparedness)\b", re.I)
MODIFIER_RE = re.compile(r"\b(rescission|rescind(?:ing|ed|s)?|renewal|renew(?:ed|s|ing)?|extension|extend(?:ed|s|ing)?|amendment|amend(?:ed|s|ing)?)\b", re.I)
EO_RE = re.compile(r"\b01\.01\.\d{4}\.\d{1,2}\b")
OFFICIAL_HAZARD_EVIDENCE = {
    "01.01.2023.13": (
        "Tropical Storm Ophelia",
        "https://governor.maryland.gov/news/press-releases/governor-wes-moore-declares-state-emergency",
    ),
}


@dataclass
class Action:
    eo_number: str
    title: str
    date_signed: Optional[str]
    document_url: str
    archive_url: str
    governor: str
    document_text: str = ""
    description: str = ""
    action_type: str = "administrative"
    action_kind: str = "executive_order"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        if self.eo_number:
            return "MD-EO-" + self.eo_number.replace(".", "-")
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:48]
        return f"MD-ACTION-{self.date_signed or 'UNDATED'}-{slug}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*", "", raw.strip())
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def eo_number_from_title(title: str) -> str:
    matches = EO_RE.findall(title)
    if not matches:
        return ""
    marker = re.search(r"\(EO#?\s*(01\.01\.\d{4}\.\d{1,2})\)", title, re.I)
    return marker.group(1) if marker else matches[0]


def governor_for_date(date_signed: Optional[str]) -> str:
    return "Martin O'Malley" if date_signed and date_signed < "2015-01-21" else "Wes Moore"


def parse_archive_page(html: str, archive_url: str = ARCHIVE_URL) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    for item in soup.select("li.maryland-listing-item"):
        title_node = item.select_one(".maryland-link__document-title")
        link = item.select_one("a.maryland-listing-item__title[href]")
        if not title_node or not link:
            continue
        title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip()
        date_node = item.select_one(".maryland-listing-item__date")
        signed = normalize_date(date_node.get_text(" ", strip=True)) if date_node else None
        number = eo_number_from_title(title)
        actions.append(Action(number, title, signed, urljoin(archive_url, link.get("href", "")), archive_url, governor_for_date(signed)))
    return actions


def pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed: {exc}", file=sys.stderr)
        return ""


def classify_action(action: Action) -> str:
    modifier = MODIFIER_RE.search(action.title)
    emergency_context = bool(re.search(r"state of (?:emergency|preparedness)|executive order", action.title, re.I))
    if modifier and emergency_context:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "rescission")):
            return "termination"
        if word.startswith(("renew", "extension", "extend")):
            return "extension"
        return "amendment"
    if DECLARATION_RE.search(action.title):
        return "declaration"
    return "administrative"


def hazard_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    for sentence in re.split(r"(?<=[.;])\s+", clean):
        if HAZARD_RE.search(sentence):
            return sentence[:500].strip()
    return ""


def enrich(action: Action) -> None:
    action.action_type = classify_action(action)
    if action.action_type != "administrative":
        action.action_kind = "emergency_declaration"
    action.description = action.title
    evidence = action.title
    known = OFFICIAL_HAZARD_EVIDENCE.get(action.eo_number)
    if known:
        action.description = f"{action.title} — {known[0]}"
        evidence = known[0]
    elif action.action_type == "declaration" and "extreme heat" not in action.title.lower() and not HAZARD_RE.search(evidence):
        response = fetch(action.document_url)
        if response is not None:
            action.document_text = pdf_text(response.content)
            sentence = hazard_sentence(action.document_text)
            if sentence:
                action.description = f"{action.title} — {sentence}"
                evidence = sentence
            elif re.fullmatch(r"State of Preparedness \(EO#?\s*01\.01\.2023\.20\)", action.title, re.I):
                action.action_type = "administrative"
                action.action_kind = "executive_order"
    action.weather_related = action.action_type != "administrative" and bool(HAZARD_RE.search(evidence))


def collect() -> list[Action]:
    actions: list[Action] = []
    for page_number in range(20):
        page_url = f"{ARCHIVE_URL}?page={page_number}"
        response = fetch(page_url)
        if response is None:
            break
        parsed = parse_archive_page(response.text, page_url)
        if not parsed:
            break
        actions.extend(parsed)
        soup = BeautifulSoup(response.text, "html.parser")
        if not soup.select_one('a[rel="next"]'):
            break
    unique: dict[str, Action] = {}
    for action in actions:
        unique.setdefault(action.stable_id, action)
    for action in unique.values():
        enrich(action)
    return sorted(unique.values(), key=lambda action: (action.date_signed or "", action.stable_id), reverse=True)


def extract_relationships(action: Action) -> list[dict[str, str]]:
    if action.action_type not in {"amendment", "extension", "termination"}:
        return []
    relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
    rows = []
    for number in EO_RE.findall(action.title):
        target = "MD-EO-" + number.replace(".", "-")
        if target == action.stable_id:
            continue
        rows.append({
            "source_order_id": action.stable_id,
            "target_order_id": target,
            "relationship_type": relation,
            "relationship_text": number,
            "relationship_source": "official_archive_title",
            "confidence": "high",
        })
    return rows


def action_row(action: Action) -> dict[str, str]:
    return {
        "declaration_id": action.stable_id, "state": "MD", "governor": action.governor,
        "eo_number": action.eo_number, "action_kind": action.action_kind,
        "action_type": action.action_type, "event_description": action.description,
        "date_signed": action.date_signed or "", "end_date": "",
        "weather_related": "true" if action.weather_related else "false",
        "source_scope": "moore_executive_order_archive",
        "document_format": "pdf", "detail_url": action.document_url,
        "archive_record_url": action.archive_url,
    }


def write_csv(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions: list[Action], actions_out: str, relationships_out: str, join_out: str) -> None:
    rows = [action_row(action) for action in actions]
    write_csv(actions_out, ACTION_FIELDS, rows)
    relationships = [row for action in actions for row in extract_relationships(action)]
    write_csv(relationships_out, REL_FIELDS, relationships)
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
    relationships = sum(len(extract_relationships(action)) for action in actions)
    joins = sum(action.action_type == "declaration" and action.weather_related for action in actions)
    print(f"Maryland: {len(actions)} actions, {relationships} relationships, {joins} weather declarations")


if __name__ == "__main__":
    main()
