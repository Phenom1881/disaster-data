"""Collect New Hampshire orders from the official Secretary of State registry.

The Governor's current website no longer exposes the historical registry.  The
Secretary of State registry is the official successor and includes Governor
Ayotte plus archived orders from prior administrations back to 1990.
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
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup, Tag


REGISTRY_URL = "https://www.sos.nh.gov/executive-orders"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)", "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")

HAZARD_RE = re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|rain storm|hurricanes?|tropical storms?|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice storm|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|wind storms?|high winds?|damaging winds?|wind gusts?)\b", re.I)
DECLARATION_RE = re.compile(
    r"\b(?:declar(?:e|es|ed|ing) (?:a |the )?(?:limited )?state of emergency|"
    r"declaration of (?:a |the )?(?:limited )?state of emergency)\b", re.I,
)
MODIFIER_RE = re.compile(r"\b(amend(?:ment|s|ed|ing)?|extend(?:s|ed|ing)?|extension|renew(?:al|s|ed|ing)?|continuation|continue[sd]?|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|revoke[sd]?|terminat(?:e|es|ed|ing|ion)|state of emergency over)\b", re.I)
REF_RE = re.compile(r"(?:executive|emergency) order(?:\s+(?:no\.?|number|#))?\s*(\d{4}-\d+|#?\d+)", re.I)


@dataclass
class Action:
    number: str
    title: str
    governor: str
    document_url: str
    date_signed: Optional[str] = None
    document_text: str = ""
    action_type: str = "administrative"
    action_kind: str = "executive_order"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        token = self.number.replace(" #", "-EO-").replace("#", "EO-").replace(" ", "-").upper()
        return f"NH-{token}"


def fetch(url: str) -> Optional[requests.Response]:
    candidates = [url]
    if "www.sos.nh.gov" in url: candidates.append(url.replace("www.sos.nh.gov", "sos.nh.gov"))
    last = None
    for candidate in candidates:
        try:
            response = requests.get(candidate, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status(); return response
        except requests.RequestException as exc: last = exc
    print(f"  WARNING: failed to fetch {url}: {last}", file=sys.stderr); return None


def governor_from_heading(text: str) -> str:
    for name in ("Kelly A. Ayotte", "Christopher Sununu", "Margaret Wood Hassan", "John H. Lynch", "Craig R. Benson", "Jeanne Shaheen", "Stephen Merrill", "Judd Gregg"):
        if name in text: return name
    return ""


def parse_registry(html: str) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions = []
    for row in soup.select("table tr"):
        cells = row.select("td")
        link = row.select_one("td a[href]")
        if not link or len(cells) < 2: continue
        label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        match = re.search(r"((?:19|20)\d{2}-\d+[A-Z]?)(?:\s*#\s*(\d+))?", label, re.I)
        if not match: continue
        number = match.group(1) + (f" #{int(match.group(2)):02d}" if match.group(2) else "")
        title = re.sub(r"\s+", " ", cells[-1].get_text(" ", strip=True))
        heading = row.find_previous(["h2", "h3", "button", "summary"])
        governor = governor_from_heading(heading.get_text(" ", strip=True) if isinstance(heading, Tag) else "")
        actions.append(Action(number, title, governor, urljoin(REGISTRY_URL, link.get("href", ""))))
    return list({a.stable_id: a for a in actions}.values())


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", re.sub(r"\s+", " ", raw.strip()), flags=re.I)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return None


def date_in_text(text: str, fallback_year: Optional[int] = None) -> Optional[str]:
    patterns = (
        r"(?:this|on)\s+(\d{1,2}(?:st|nd|rd|th)?\s+day of\s+(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+(?:in the year of Our Lord,?\s+)?(?:two thousand and [a-z-]+|\d{4}))",
        r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})\b",
    )
    match = re.search(patterns[1], text, re.I)
    if match: return normalize_date(match.group(1))
    if fallback_year:
        match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+day of\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b", text, re.I)
        if match: return normalize_date(f"{match.group(2)} {match.group(1)}, {fallback_year}")
    return None


def pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf: return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed: {exc}", file=sys.stderr); return ""


def classify(action: Action) -> None:
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "repeal", "revoke", "terminat")) or "over" in word: action.action_type = "termination"
        elif word.startswith("amend"): action.action_type = "amendment"
        else: action.action_type = "extension"
    elif DECLARATION_RE.search(action.title):
        action.action_type = "declaration"; action.action_kind = "emergency_declaration"
    evidence = action.title
    if action.action_type == "declaration" and not HAZARD_RE.search(evidence): evidence = action.document_text
    action.weather_related = action.action_type in {"declaration", "amendment", "extension", "termination"} and bool(HAZARD_RE.search(evidence))


def collect() -> list[Action]:
    page = fetch(REGISTRY_URL)
    if page is None: return []
    actions = parse_registry(page.text)
    for action in actions:
        # Exact signing dates and generic-declaration hazards come from the order itself.
        if DECLARATION_RE.search(action.title) or MODIFIER_RE.search(action.title):
            document = fetch(action.document_url)
            if document is not None:
                action.document_text = pdf_text(document.content)
                action.date_signed = date_in_text(action.document_text, int(action.number[:4]))
        classify(action)
    return sorted(actions, key=lambda a: (a.date_signed or "", a.number), reverse=True)


def relationships(action: Action) -> list[dict[str, str]]:
    if action.action_type not in {"amendment", "extension", "termination"}: return []
    relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
    rows = []
    for match in REF_RE.finditer(f"{action.title}\n{action.document_text[:6000]}"):
        raw = match.group(1).lstrip("#")
        if "-" not in raw and action.number.startswith("2020-04 #"): target = f"NH-2020-04-EO-{int(raw):02d}"
        else: target = f"NH-{raw.upper()}"
        if target != action.stable_id:
            rows.append({"source_order_id": action.stable_id, "target_order_id": target, "relationship_type": relation, "relationship_text": match.group(0), "relationship_source": "title_or_document_text", "confidence": "high"})
    return list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for r in rows}.values())


def action_row(a: Action) -> dict[str, str]:
    return {"declaration_id": a.stable_id, "state": "NH", "governor": a.governor, "eo_number": a.number, "action_kind": a.action_kind, "action_type": a.action_type, "event_description": a.title, "date_signed": a.date_signed or "", "end_date": "", "weather_related": "true" if a.weather_related else "false", "source_scope": "nh_secretary_of_state_executive_order_registry", "document_format": "pdf", "detail_url": a.document_url, "archive_record_url": REGISTRY_URL}


def write(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    actions = collect(); rows = [action_row(a) for a in actions]
    write(args.actions_out, ACTION_FIELDS, rows)
    rels = list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for a in actions for r in relationships(a)}.values()); write(args.relationships_out, REL_FIELDS, rels)
    joins = [{field: action_row(a)[field] for field in JOIN_FIELDS} for a in actions if a.action_type == "declaration" and a.weather_related and a.date_signed]; write(args.join_out, JOIN_FIELDS, joins)
    print(f"New Hampshire: {len(actions)} actions, {len(rels)} relationships, {len(joins)} weather declarations")


if __name__ == "__main__": main()
