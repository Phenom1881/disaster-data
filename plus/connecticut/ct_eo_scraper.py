"""Collect Connecticut executive orders and civil-preparedness declarations.

Sources are the Governor's paginated executive-order archive (1971-present)
and the Department of Emergency Services and Public Protection's official
table of civil-preparedness emergency declarations (2005-2020).  The two
source scopes remain labeled in the complete action output.
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


EO_ARCHIVE_URL = "https://portal.ct.gov/governor/governors-actions/executive-orders"
EMERGENCY_ARCHIVE_URL = "https://portal.ct.gov/demhs/emergency-management/legal-resources/civil-preparedness-emergency"
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
    r"(?P<verb>amend(?:s|ed|ing)?|exten(?:d(?:s|ed|ing)?|sion)|continu(?:e|es|ed|ing)|reissu(?:e|es|ed|ing)|"
    r"terminat(?:e|es|ed|ing)|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|supersed(?:e|es|ed|ing))"
    r".{0,160}?executive\s+order(?:\s+(?:no\.?|number))?\s*(?P<number>\d+(?:[-A-Z0-9.]*\d|[A-Z]+)?)",
    re.I | re.S,
)


@dataclass
class CTAction:
    action_kind: str
    number: str
    description: str
    date_issued: Optional[str]
    governor: str
    document_url: str
    source_page_url: str
    source_scope: str
    document_text: str = ""
    action_type: str = "administrative"
    weather_related: bool = False
    end_date: Optional[str] = None

    @property
    def stable_id(self) -> str:
        if self.action_kind == "executive_order":
            code = re.sub(r"[^A-Z]", "", self.governor.upper()) or "UNK"
            return f"CT-{code}-EO-{self.number.upper()}"
        return f"CT-PROC-{self.date_issued or 'UNDATED'}"


def fetch(url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def governor_for_date(value: Optional[str]) -> str:
    if not value:
        return ""
    for start, name in (
        ("2019-01-09", "Ned Lamont"), ("2011-01-05", "Dannel Malloy"),
        ("2004-07-01", "M. Jodi Rell"), ("1995-01-04", "John Rowland"),
        ("1991-01-09", "Lowell Weicker"), ("1980-12-31", "William O'Neill"),
        ("1975-01-08", "Ella Grasso"), ("1971-01-06", "Thomas Meskill"),
    ):
        if value >= start:
            return name
    return ""


def parse_executive_order_page(html: str, base_url: str = EO_ARCHIVE_URL) -> list[CTAction]:
    soup = BeautifulSoup(html, "html.parser")
    actions = []
    for article in soup.select("article.new-cg-c-press-rel__item"):
        link = article.select_one("a.cg-c-button-link[href]")
        if not link:
            continue
        label = " ".join(link.get_text(" ", strip=True).split())
        match = re.search(r"Executive Order(?: No\.)?\s*(\d+(?:[-A-Z0-9.]*\d|[A-Z]+)?)", label, re.I)
        if not match:
            continue
        date_node = article.select_one(".new-cg-c-press-rel__date")
        desc_node = article.select_one(".new-cg-c-press-rel__desc")
        issued = normalize_date(date_node.get_text(" ", strip=True) if date_node else "")
        description = " ".join(desc_node.get_text(" ", strip=True).split()) if desc_node else label
        actions.append(CTAction(
            action_kind="executive_order", number=match.group(1), description=description,
            date_issued=issued, governor=governor_for_date(issued),
            document_url=urljoin(base_url, link.get("href")), source_page_url=base_url,
            source_scope="governor_executive_order_archive",
        ))
    return actions


def collect_executive_orders() -> list[CTAction]:
    actions, page = [], 1
    while True:
        response = fetch(EO_ARCHIVE_URL, {"Page": page, "PageSize": 100})
        if response is None:
            break
        parsed = parse_executive_order_page(response.text)
        if not parsed:
            break
        actions.extend(parsed)
        soup = BeautifulSoup(response.text, "html.parser")
        total = soup.select_one("#resultsAnnounced")
        match = re.search(r"Page\s+\d+\s+of\s+(\d+)", total.get_text(" ", strip=True) if total else "")
        if not match or page >= int(match.group(1)):
            break
        page += 1
    return actions


def parse_emergency_page(html: str, base_url: str = EMERGENCY_ARCHIVE_URL) -> list[CTAction]:
    soup = BeautifulSoup(html, "html.parser")
    actions = []
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        headers = [cell.get_text(" ", strip=True).lower() for cell in first_row.find_all(["th", "td"])] if first_row else []
        if "declaration date" not in headers or "reason for declaration" not in headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            issued = normalize_date(cells[0].get_text(" ", strip=True))
            governor_label = cells[1].get_text(" ", strip=True)
            link = cells[2].find("a", href=True)
            description = " ".join(cells[2].get_text(" ", strip=True).split())
            if not issued or not link:
                continue
            governor = {"Lamont": "Ned Lamont", "Malloy": "Dannel Malloy", "Rell": "M. Jodi Rell"}.get(governor_label, governor_for_date(issued))
            actions.append(CTAction(
                action_kind="emergency_proclamation", number="", description=description,
                date_issued=issued, governor=governor,
                document_url=urljoin(base_url, link.get("href")), source_page_url=base_url,
                source_scope="demhs_civil_preparedness_emergencies",
            ))
    return actions


def collect_emergency_declarations() -> list[CTAction]:
    response = fetch(EMERGENCY_ARCHIVE_URL)
    return parse_emergency_page(response.text) if response else []


def fetch_document_text(action: CTAction) -> str:
    response = fetch(action.document_url)
    if response is None:
        return ""
    if "pdf" not in response.headers.get("content-type", "").lower() and not action.document_url.split("?", 1)[0].lower().endswith(".pdf"):
        return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception as exc:
        print(f"  WARNING: PDF text extraction failed for {action.document_url}: {exc}", file=sys.stderr)
        return ""


def classify_action(action: CTAction) -> str:
    text = f"{action.description} {action.document_text}"
    lead = action.description
    if re.search(r"\b(?:rescind|repeal|terminat|ending)\w*\b", lead, re.I): return "termination"
    if re.search(r"\b(?:amend|modif|revis)\w*\b", lead, re.I): return "amendment"
    if re.search(r"\b(?:extension|extend|extends|extended|extending|renew|renews|renewed|renewing|reissue|reissues|reissued|reissuing|continuation)\b", lead, re.I): return "extension"
    if action.action_kind == "emergency_proclamation": return "declaration"
    if re.search(r"\b(?:declare|proclaim)\w*.{0,100}\b(?:civil preparedness |public health |disaster )?emergenc", lead, re.I | re.S): return "declaration"
    return "administrative"


def is_weather_related(action: CTAction) -> bool:
    text = f"{action.description} {action.document_text}"
    return any(pattern.search(text) for pattern in WEATHER_PATTERNS)


def _rel_type(verb: str) -> str:
    verb = verb.lower()
    if verb.startswith(("terminat", "rescind", "repeal")): return "terminates"
    if verb.startswith(("exten", "continu", "reissu")): return "extends_duration"
    if verb.startswith("supersed"): return "supersedes"
    return "amends"


def extract_relationships(action: CTAction) -> list[dict[str, str]]:
    if action.action_kind != "executive_order": return []
    rows = []
    for match in RELATIONSHIP_RE.finditer(f"{action.description} {action.document_text}"):
        code = re.sub(r"[^A-Z]", "", action.governor.upper()) or "UNK"
        rows.append({"source_order_id": action.stable_id, "target_order_id": f"CT-{code}-EO-{match.group('number').upper()}", "relationship_type": _rel_type(match.group("verb")), "relationship_text": re.sub(r"\s+", " ", match.group(0)).strip(), "relationship_source": "official_description_or_text", "confidence": "medium"})
    return dedupe_relationships(rows)


def dedupe_actions(actions: Iterable[CTAction]) -> list[CTAction]:
    unique = {row.stable_id: row for row in actions}
    return sorted(unique.values(), key=lambda row: (row.date_issued or "", row.stable_id), reverse=True)


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result, seen = [], set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen and key[0] != key[1]: seen.add(key); result.append(row)
    return result


ACTION_FIELDS = ["declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url"]
REL_FIELDS = ["source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence"]
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]


def write_outputs(actions: list[CTAction], relationships: list[dict[str, str]], actions_path: str, relationships_path: str, join_path: str) -> None:
    with open(actions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTION_FIELDS); writer.writeheader()
        for row in actions:
            writer.writerow({"declaration_id": row.stable_id, "state": "CT", "governor": row.governor, "eo_number": row.number, "action_kind": row.action_kind, "action_type": row.action_type, "event_description": row.description, "date_signed": row.date_issued or "", "end_date": row.end_date or "", "weather_related": row.weather_related, "source_scope": row.source_scope, "document_format": "pdf" if row.document_url.split("?", 1)[0].lower().endswith(".pdf") else "html", "detail_url": row.source_page_url, "archive_record_url": row.document_url})
    with open(relationships_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REL_FIELDS); writer.writeheader(); writer.writerows(relationships)
    with open(join_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOIN_FIELDS); writer.writeheader()
        for row in actions:
            if row.action_type == "declaration" and row.weather_related and row.date_issued:
                writer.writerow({"declaration_id": row.stable_id, "governor": row.governor, "eo_number": row.number, "event_description": row.description, "date_signed": row.date_issued, "archive_record_url": row.document_url})


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Connecticut executive orders and emergency declarations")
    parser.add_argument("--actions-out", default="ct_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="ct_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()
    executive_orders = collect_executive_orders()
    declarations = collect_emergency_declarations()
    actions = dedupe_actions([*executive_orders, *declarations])
    if not actions: raise SystemExit("ERROR: no Connecticut actions were collected")
    if not args.skip_document_fetch:
        print(f"Connecticut scraper: fetching {len(actions)} official document(s)...")
        low_yield = 0
        for index, action in enumerate(actions, 1):
            action.document_text = fetch_document_text(action)
            if len(action.document_text) < 250: low_yield += 1
            if index % 50 == 0: print(f"    fetched {index}/{len(actions)}")
        if low_yield: print(f"  WARNING: {low_yield} document(s) yielded fewer than 250 characters and need manual/OCR review", file=sys.stderr)
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
    print(f"Done. {len(actions)} action(s): {len(executive_orders)} executive orders, {len(declarations)} civil-preparedness declarations; {join_count} original weather declaration(s).")


if __name__ == "__main__": main()
