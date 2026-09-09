"""Collect Rhode Island executive orders from the Governor's official archive.

The archive supplies a single complete HTML table and a detail page with the
order text for each record from 2015 onward.  Original weather declarations
alone enter the NOAA join file; extensions, amendments, and terminations stay
in the complete action and relationship outputs.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ARCHIVE_URL = "https://governor.ri.gov/executive-order-archive"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)"}
WEATHER_PATTERNS = (
    re.compile(r"\bdrought\b", re.I), re.compile(r"\b(?:wildfire|forest fire|brush fire|fire weather)\b", re.I),
    re.compile(r"\b(?:flash )?flood(?:ing|s)?\b|\brain ?storm\b", re.I),
    re.compile(r"\b(?:hurricane|superstorm|tropical (?:storm|cyclone|depression))\b", re.I),
    re.compile(r"\b(?:blizzard|winter (?:storm|weather)|snow(?:fall|storm)?|ice storm|nor['’]?easter)\b", re.I),
    re.compile(r"\b(?:severe (?:storm|weather)|thunderstorm|tornado(?:es)?)\b", re.I),
    re.compile(r"\b(?:wind storm|high winds?|damaging winds?|wind gusts?)\b", re.I),
)
RELATIONSHIP_RE = re.compile(
    r"(?P<verb>amend(?:s|ed|ing)?|exten(?:d(?:s|ed|ing)?|sion)|continu(?:e|es|ed|ing)|"
    r"terminat(?:e|es|ed|ing)|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|supersed(?:e|es|ed|ing))"
    r".{0,180}?executive\s+order(?:\s+(?:no\.?|number))?\s*(?P<number>\d{2}-\d+(?:\.\d+)?)",
    re.I | re.S,
)


@dataclass
class RIAction:
    number: str
    title: str
    description: str
    date_issued: Optional[str]
    governor: str
    detail_url: str
    action_kind: str = "executive_order"
    document_text: str = ""
    document_url: str = ""
    action_type: str = "administrative"
    weather_related: bool = False
    end_date: Optional[str] = None

    @property
    def stable_id(self) -> str:
        if self.number:
            return f"RI-EO-{self.number.upper()}"
        return f"RI-PROC-{self.date_issued or 'UNDATED'}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return None


def governor_for_date(value: Optional[str]) -> str:
    if not value: return ""
    return "Daniel J. McKee" if value >= "2021-03-02" else "Gina M. Raimondo"


def parse_archive_page(html: str, base_url: str = ARCHIVE_URL) -> list[RIAction]:
    soup = BeautifulSoup(html, "html.parser")
    actions = []
    for table in soup.find_all("table"):
        headers = [cell.get_text(" ", strip=True).lower() for cell in table.find_all("th")]
        if not any("executive order long title" in value for value in headers):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3: continue
            issued = normalize_date(cells[0].get_text(" ", strip=True))
            link = cells[1].find("a", href=True)
            if not issued or not link: continue
            title = " ".join(link.get_text(" ", strip=True).split())
            description = " ".join(cells[2].get_text(" ", strip=True).split())
            number_match = re.search(r"Executive Order\s+(\d{2}-\d+(?:\.\d+)?)", title, re.I)
            actions.append(RIAction(
                number=number_match.group(1) if number_match else "", title=title,
                description=description, date_issued=issued, governor=governor_for_date(issued),
                detail_url=urljoin(base_url, link.get("href")),
                action_kind="executive_order" if number_match else "gubernatorial_proclamation",
            ))
    return actions


def collect_actions() -> list[RIAction]:
    response = fetch(ARCHIVE_URL)
    return dedupe_actions(parse_archive_page(response.text)) if response else []


def enrich_detail(action: RIAction) -> None:
    response = fetch(action.detail_url)
    if response is None: return
    soup = BeautifulSoup(response.text, "html.parser")
    main = soup.find("main") or soup
    action.document_text = " ".join(main.get_text(" ", strip=True).split())
    pdf = next((a for a in main.find_all("a", href=True) if ".pdf" in a.get("href", "").lower()), None)
    action.document_url = urljoin(action.detail_url, pdf.get("href")) if pdf else action.detail_url
    if pdf and "contents of the executive order can be found in the attached pdf" in action.document_text.lower():
        pdf_response = fetch(action.document_url)
        if pdf_response is not None:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(pdf_response.content)) as document:
                    extracted = " ".join(page.extract_text() or "" for page in document.pages).strip()
                if extracted:
                    action.document_text = extracted
            except Exception as exc:
                print(f"  WARNING: PDF text extraction failed for {action.document_url}: {exc}", file=sys.stderr)
    if action.description.strip().lower() == "declaration of disaster emergency":
        for sentence in re.split(r"(?<=[.!?;])\s+", action.document_text):
            if any(pattern.search(sentence) for pattern in WEATHER_PATTERNS):
                action.description = f"Declaration of Disaster Emergency: {sentence.strip()}"
                break


def classify_action(action: RIAction) -> str:
    lead = f"{action.title} {action.description}"
    if re.search(r"\b(?:rescind|repeal|revoke|terminat|ending)\w*\b", lead, re.I): return "termination"
    if re.search(r"\b(?:amend|modif|revis)\w*\b", lead, re.I): return "amendment"
    if re.search(r"\b(?:extension|extend|extends|extended|extending|renew|renews|renewed|renewing|continuation)\b", lead, re.I): return "extension"
    if re.search(r"\b(?:declaration|declaring|declare|proclaim)\b.{0,100}\b(?:disaster )?emergency\b", lead, re.I | re.S): return "declaration"
    return "administrative"


def is_weather_related(action: RIAction) -> bool:
    text = f"{action.description} {action.document_text}"
    return any(pattern.search(text) for pattern in WEATHER_PATTERNS)


def _rel_type(verb: str) -> str:
    verb = verb.lower()
    if verb.startswith(("terminat", "rescind", "repeal")): return "terminates"
    if verb.startswith(("exten", "continu")): return "extends_duration"
    if verb.startswith("supersed"): return "supersedes"
    return "amends"


def extract_relationships(action: RIAction) -> list[dict[str, str]]:
    rows = []
    for match in RELATIONSHIP_RE.finditer(f"{action.description} {action.document_text}"):
        rows.append({"source_order_id": action.stable_id, "target_order_id": f"RI-EO-{match.group('number').upper()}", "relationship_type": _rel_type(match.group("verb")), "relationship_text": re.sub(r"\s+", " ", match.group(0)).strip(), "relationship_source": "official_archive_or_text", "confidence": "medium"})
    return dedupe_relationships(rows)


def dedupe_actions(actions: Iterable[RIAction]) -> list[RIAction]:
    unique = {row.stable_id: row for row in actions}
    return sorted(unique.values(), key=lambda row: (row.date_issued or "", row.stable_id), reverse=True)


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result, seen = [], set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen and key[0] != key[1]: seen.add(key); result.append(row)
    return result


ACTION_FIELDS = ["declaration_id", "state", "governor", "eo_number", "action_type", "event_description", "date_signed", "end_date", "weather_related", "document_format", "archive_record_url"]
REL_FIELDS = ["source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence"]
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]


def write_outputs(actions: list[RIAction], relationships: list[dict[str, str]], actions_path: str, relationships_path: str, join_path: str) -> None:
    with open(actions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTION_FIELDS); writer.writeheader()
        for row in actions:
            writer.writerow({"declaration_id": row.stable_id, "state": "RI", "governor": row.governor, "eo_number": row.number, "action_type": row.action_type, "event_description": row.description, "date_signed": row.date_issued or "", "end_date": row.end_date or "", "weather_related": row.weather_related, "document_format": "html", "archive_record_url": row.detail_url})
    with open(relationships_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REL_FIELDS); writer.writeheader(); writer.writerows(relationships)
    with open(join_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOIN_FIELDS); writer.writeheader()
        for row in actions:
            if row.action_type == "declaration" and row.weather_related and row.date_issued:
                writer.writerow({"declaration_id": row.stable_id, "governor": row.governor, "eo_number": row.number, "event_description": row.description, "date_signed": row.date_issued, "archive_record_url": row.detail_url})


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Rhode Island executive orders")
    parser.add_argument("--actions-out", default="ri_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="ri_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()
    actions = collect_actions()
    if not actions: raise SystemExit("ERROR: no Rhode Island actions were collected")
    if not args.skip_document_fetch:
        candidates = [action for action in actions if re.search(r"\b(?:declaration|declaring)\b.{0,80}\bemergency\b", action.description, re.I)]
        print(f"Rhode Island scraper: fetching {len(candidates)} ambiguous declaration detail page(s)...")
        for index, action in enumerate(candidates, 1):
            enrich_detail(action)
            if index % 25 == 0: print(f"    fetched {index}/{len(candidates)}")
    for action in actions:
        action.action_type = classify_action(action); action.weather_related = is_weather_related(action)
    relationships = dedupe_relationships(row for action in actions for row in extract_relationships(action))
    valid = {row.stable_id for row in actions}; relationships = [row for row in relationships if row["target_order_id"] in valid]
    by_id = {row.stable_id: row for row in actions}
    for rel in relationships:
        if rel["relationship_type"] == "terminates" and by_id[rel["source_order_id"]].date_issued:
            by_id[rel["target_order_id"]].end_date = by_id[rel["source_order_id"]].date_issued
    write_outputs(actions, relationships, args.actions_out, args.relationships_out, args.join_out)
    join_count = sum(row.action_type == "declaration" and row.weather_related and bool(row.date_issued) for row in actions)
    print(f"Done. {len(actions)} action(s), {len(relationships)} relationship(s), {join_count} original weather declaration(s).")


if __name__ == "__main__": main()
