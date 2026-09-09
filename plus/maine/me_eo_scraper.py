"""Collect Maine executive orders and weather emergency declarations.

Official source scopes are kept explicit: Governor Mills' current official-
documents page and Governor LePage's preserved executive-order archive.
Only original, weather-related declarations enter declarations_for_join.csv.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlsplit

import pdfplumber
import requests
from bs4 import BeautifulSoup, Tag


MILLS_URL = "https://www.maine.gov/governor/mills/official_documents"
LEPAGE_URL = "https://www.maine.gov/governor/lepage/official-documents/executive-orders-archive.html"
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
DECLARATION_RE = re.compile(
    r"\b(state of (?:civil )?emergency declaration|civil preparedness emergency|"
    r"emergency proclamation|declar(?:e|es|ed|ing) (?:a )?(?:state of )?emergency)\b", re.I,
)
MODIFIER_RE = re.compile(
    r"\b(amend(?:ment|s|ed|ing)?|extend(?:s|ed|ing|ing the effectiveness)?|"
    r"extension|renew(?:al|s|ed|ing)?|continuation|continue[sd]?|"
    r"rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|revoke[sd]?|"
    r"terminat(?:e|es|ed|ing|ion)|concluding)\b", re.I,
)
NUMBER_REF_RE = re.compile(
    r"(?:executive order|order)(?:\s+(?:no\.?|number))?\s+"
    r"(?P<num>\d+(?:[-A-Z]\w*)?)\s*(?:FY\s*)?(?P<fy>\d{2}\s*/\s*\d{2})?",
    re.I,
)


@dataclass
class Action:
    eo_number: str
    title: str
    date_signed: Optional[str]
    governor: str
    detail_url: str
    archive_url: str
    source_scope: str
    document_url: str = ""
    document_text: str = ""
    action_type: str = "administrative"
    action_kind: str = "executive_order"
    weather_related: bool = False
    end_date: str = ""

    @property
    def stable_id(self) -> str:
        token = re.sub(r"[^A-Z0-9]+", "-", self.eo_number.upper()).strip("-")
        if token:
            return f"ME-EO-{token}"
        date = self.date_signed or "UNDATED"
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:42]
        return f"ME-ACTION-{date}-{slug}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", raw.strip(), flags=re.I)
    raw = re.sub(r"\s+", " ", raw).replace("Sept.", "Sep")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def date_in_text(text: str) -> Optional[str]:
    patterns = (
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_date(match.group())
            if value:
                return value
    return None


def fiscal_context(link: Tag) -> str:
    heading = link.find_previous(["h2", "h3", "h4"])
    if not heading:
        return ""
    match = re.search(r"FY\s*(\d{2})\s*/\s*(\d{2})", heading.get_text(" ", strip=True), re.I)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def number_from_title(title: str, fiscal: str = "") -> str:
    match = re.search(r"Executive Order\s*(\d+(?:[-A-Z]\w*)?)", title, re.I)
    if not match:
        return ""
    number = match.group(1).upper()
    return f"{fiscal}-{number}" if fiscal else number


def parse_mills_page(html: str) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    seen: set[str] = set()
    for link in soup.select('a[href]'):
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
        href = urljoin(MILLS_URL, link.get("href", ""))
        if not title or not ("Executive Order" in title or DECLARATION_RE.search(title)):
            continue
        if href in seen or "accessible" in title.lower() or title.lower() in {"pdf", "word"}:
            continue
        seen.add(href)
        container = link.find_parent("li") or link.parent
        direct_tail = " ".join(str(node) for node in link.next_siblings if not isinstance(node, Tag))
        context = direct_tail or (container.get_text(" ", strip=True) if container else title)
        matches = re.findall(
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}",
            context,
        )
        signed = normalize_date(matches[-1]) if matches else None
        fiscal = fiscal_context(link)
        number = number_from_title(title, fiscal)
        actions.append(Action(number, re.sub(r"\s*\(PDF.*$", "", title, flags=re.I), signed,
                              "Janet T. Mills", href, MILLS_URL, "mills_official_documents",
                              document_url=href if urlsplit(href).path.lower().endswith(".pdf") else ""))
    return actions


def parse_lepage_page(html: str) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    for li in soup.select("li"):
        link = li.select_one("a[href]")
        if not link:
            continue
        text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        match = re.match(r"(.+?\d{4}):\s*(.+)", text)
        if not match:
            continue
        signed = normalize_date(match.group(1))
        title = match.group(2).strip()
        detail = urljoin(LEPAGE_URL, link.get("href", ""))
        number_match = re.search(r"Executive Order\s*(?:No\.?\s*)?(\d+(?:[-A-Z]\w*)?)", title, re.I)
        actions.append(Action(number_match.group(1).upper() if number_match else "", title, signed,
                              "Paul R. LePage", detail, LEPAGE_URL, "lepage_executive_order_archive"))
    return actions


def pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed: {exc}", file=sys.stderr)
        return ""


def enrich(action: Action) -> None:
    if not action.document_url:
        page = fetch(action.detail_url)
        if page is not None:
            soup = BeautifulSoup(page.text, "html.parser")
            action.document_text = soup.get_text(" ", strip=True)
            candidate = soup.select_one('a[href$=".pdf" i], a[href*=".pdf?"]')
            if candidate:
                action.document_url = urljoin(action.detail_url, candidate.get("href", ""))
    if action.document_url and (not action.date_signed or DECLARATION_RE.search(action.title) or MODIFIER_RE.search(action.title)):
        response = fetch(action.document_url)
        if response is not None:
            action.document_text = pdf_text(response.content)
            action.date_signed = action.date_signed or date_in_text(action.document_text)
    classify(action)


def classify(action: Action) -> None:
    title = action.title
    modifier = MODIFIER_RE.search(title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "repeal", "revoke", "terminat", "concluding")):
            action.action_type = "termination"
        elif word.startswith("amend"):
            action.action_type = "amendment"
        else:
            action.action_type = "extension"
    elif DECLARATION_RE.search(title):
        action.action_type = "declaration"
        action.action_kind = "emergency_declaration"
    evidence = title
    if action.action_type == "declaration" and not HAZARD_RE.search(evidence):
        evidence = action.document_text
    action.weather_related = action.action_type in {"declaration", "termination", "extension", "amendment"} and bool(HAZARD_RE.search(evidence))


def extract_relationships(action: Action) -> list[dict[str, str]]:
    if action.action_type not in {"amendment", "extension", "termination"}:
        return []
    text = f"{action.title}\n{action.document_text[:6000]}"
    rows = []
    for match in NUMBER_REF_RE.finditer(text):
        number = match.group("num").upper()
        fy = re.sub(r"\s+", "", match.group("fy") or "")
        target = f"ME-EO-{fy.replace('/', '-') + '-' if fy else ''}{number}"
        relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
        rows.append({
            "source_order_id": action.stable_id, "target_order_id": target,
            "relationship_type": relation, "relationship_text": match.group(0),
            "relationship_source": "title_or_document_text", "confidence": "high",
        })
    return dedupe_relationships(rows)


def dedupe_relationships(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    found = {}
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if row["source_order_id"] != row["target_order_id"]:
            found[key] = row
    return list(found.values())


def collect() -> list[Action]:
    actions: list[Action] = []
    for url, parser in ((MILLS_URL, parse_mills_page), (LEPAGE_URL, parse_lepage_page)):
        page = fetch(url)
        if page is not None:
            actions.extend(parser(page.text))
    unique = {action.stable_id: action for action in actions}
    for action in unique.values():
        enrich(action)
    return sorted(unique.values(), key=lambda a: (a.date_signed or "", a.stable_id), reverse=True)


def action_row(action: Action) -> dict[str, str]:
    return {
        "declaration_id": action.stable_id, "state": "ME", "governor": action.governor,
        "eo_number": action.eo_number, "action_kind": action.action_kind,
        "action_type": action.action_type, "event_description": action.title,
        "date_signed": action.date_signed or "", "end_date": action.end_date,
        "weather_related": "true" if action.weather_related else "false",
        "source_scope": action.source_scope,
        "document_format": "pdf" if action.document_url else "html",
        "detail_url": action.document_url or action.detail_url,
        "archive_record_url": action.archive_url,
    }


def write_csv(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    actions = collect()
    write_csv(args.actions_out, ACTION_FIELDS, [action_row(a) for a in actions])
    relationships = dedupe_relationships([r for a in actions for r in extract_relationships(a)])
    write_csv(args.relationships_out, REL_FIELDS, relationships)
    joins = [{field: action_row(a)[field] for field in JOIN_FIELDS} for a in actions
             if a.action_type == "declaration" and a.weather_related and a.date_signed]
    write_csv(args.join_out, JOIN_FIELDS, joins)
    print(f"Maine: {len(actions)} actions, {len(relationships)} relationships, {len(joins)} weather declarations")


if __name__ == "__main__":
    main()
