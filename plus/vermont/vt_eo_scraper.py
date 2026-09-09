"""Collect executive orders from the official Vermont Governor archive."""

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


ARCHIVE_URL = "https://governor.vermont.gov/document-types/executive-orders"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)"}
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")

HAZARD_RE = re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|rain storm|hurricanes?|tropical storms?|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice storm|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|wind storms?|high winds?|damaging winds?|wind gusts?)\b", re.I)
DECLARATION_RE = re.compile(r"\b(declaration of (?:a )?state of emergency|declare[sd]? (?:a )?state of emergency)\b", re.I)
MODIFIER_RE = re.compile(r"\b(amended and restated|amend(?:ment|s|ed|ing)?|addendum|extend(?:s|ed|ing)?|extension|renew(?:al|s|ed|ing)?|continuation|continue[sd]?|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|revoke[sd]?|terminat(?:e|es|ed|ing|ion))\b", re.I)
REF_RE = re.compile(r"(?:executive order|order)(?:\s+(?:no\.?|number))?\s+(\d{2}-\d{2})", re.I)


@dataclass
class Action:
    number: str
    title: str
    date_signed: Optional[str]
    detail_url: str
    document_url: str = ""
    document_text: str = ""
    action_type: str = "administrative"
    action_kind: str = "executive_order"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        return f"VT-EO-{self.number.upper()}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status(); return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr); return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", re.sub(r"\s+", " ", raw.strip()), flags=re.I)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return None


def date_in_text(text: str) -> Optional[str]:
    for pattern in (r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\b", r"\b\d{1,2}/\d{1,2}/\d{4}\b"):
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_date(match.group())
            if value: return value
    return None


def parse_listing(html: str) -> tuple[list[str], Optional[int]]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for heading in soup.select("h2 a[href]"):
        if re.search(r"EXECUTIVE ORDER|\bEO\s*\d|ADDENDUM|DIRECTIVE", heading.get_text(" ", strip=True), re.I):
            urls.append(urljoin(ARCHIVE_URL, heading.get("href", "")))
    last = None
    for link in soup.select("a[href]"):
        if link.get_text(" ", strip=True).lower() == "last":
            match = re.search(r"[?&]page=(\d+)", link.get("href", "")); last = int(match.group(1)) if match else None
    return list(dict.fromkeys(urls)), last


def parse_detail(html: str, url: str) -> Optional[Action]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    text = soup.get_text(" ", strip=True)
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    number_match = re.search(r"(?:EXECUTIVE ORDER(?:\s+NO\.)?|\bEO)\s*(\d{2}-\d{2})", heading_text or text, re.I)
    if not number_match: return None
    date_node = soup.select_one("time[datetime], .field--name-field-date, .date")
    raw_date = date_node.get("datetime", "")[:10] if date_node and date_node.name == "time" else (date_node.get_text(" ", strip=True) if date_node else "")
    signed = normalize_date(raw_date) or date_in_text(text)
    pdf = soup.select_one('a[href$=".pdf" i], a[href*=".pdf?"]')
    document = urljoin(url, pdf.get("href", "")) if pdf else ""
    title = heading_text
    if re.fullmatch(r"EXECUTIVE ORDER(?:\s+NO\.)?\s+\d{2}-\d{2}", title, re.I): title = ""
    if not title:
        body_candidates = [node.get_text(" ", strip=True) for node in soup.select(".field--name-body, .field--name-field-description")]
        title = next((value for value in body_candidates if value and len(value) < 300 and "Contact the Governor" not in value and "Public Records Database" not in value), "")
    if not title: title = pdf.get_text(" ", strip=True) if pdf else ""
    title = re.sub(r"\s*\.pdf(?:\s*\([\d.]+\s*(?:KB|MB)\))?\s*$", "", title, flags=re.I)
    title = re.sub(r"^EO\s*\d{2}-\d{2}\s*[-–:]\s*", "", title, flags=re.I).strip()
    if not title:
        title = re.sub(r"^EXECUTIVE ORDER(?:\s+NO\.)?\s+\d{2}-\d{2}\s*", "", heading.get_text(" ", strip=True) if heading else "", flags=re.I).strip()
    base_number = number_match.group(1)
    extra = ""
    addendum = re.search(r"ADDENDUM\s+(\d+)", heading_text, re.I)
    directive = re.search(r"DIRECTIVE\s+(\d+)", heading_text, re.I)
    if addendum: extra = f"-ADDENDUM-{addendum.group(1)}"
    if re.search(r"AMENDMENT TO ADDENDUM", heading_text, re.I) and addendum: extra += "-AMENDMENT"
    elif directive: extra = f"-DIRECTIVE-{directive.group(1)}"
    elif re.search(r"AMENDED AND RESTATED", heading_text, re.I): extra = f"-AMENDED-RESTATED-{signed or 'UNDATED'}"
    return Action(base_number + extra, title or f"Executive Order {base_number}", signed, url, document)


def pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed: {exc}", file=sys.stderr); return ""


def classify(action: Action) -> None:
    title = action.title
    modifier = MODIFIER_RE.search(title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "repeal", "revoke", "terminat")): action.action_type = "termination"
        elif word.startswith(("amend", "addendum")): action.action_type = "amendment"
        else: action.action_type = "extension"
    elif DECLARATION_RE.search(title):
        action.action_type = "declaration"; action.action_kind = "emergency_declaration"
    evidence = title
    if action.action_type == "declaration" and not HAZARD_RE.search(evidence): evidence = action.document_text
    action.weather_related = action.action_type in {"declaration", "amendment", "extension", "termination"} and bool(HAZARD_RE.search(evidence))


def collect() -> list[Action]:
    first = fetch(ARCHIVE_URL)
    if first is None: return []
    urls, last = parse_listing(first.text)
    for page_no in range(1, (last or 0) + 1):
        page = fetch(f"{ARCHIVE_URL}?page={page_no}")
        if page is not None: urls.extend(parse_listing(page.text)[0])
    actions = []
    for url in dict.fromkeys(urls):
        page = fetch(url)
        action = parse_detail(page.text, url) if page is not None else None
        if not action: continue
        if action.document_url and (DECLARATION_RE.search(action.title) or MODIFIER_RE.search(action.title) or not action.date_signed):
            document = fetch(action.document_url)
            if document is not None:
                action.document_text = pdf_text(document.content)
                action.date_signed = action.date_signed or date_in_text(action.document_text)
        classify(action); actions.append(action)
    return sorted({a.stable_id: a for a in actions}.values(), key=lambda a: (a.date_signed or "", a.number), reverse=True)


def relationships(action: Action) -> list[dict[str, str]]:
    if action.action_type not in {"amendment", "extension", "termination"}: return []
    relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
    rows = []
    for match in REF_RE.finditer(f"{action.title}\n{action.document_text[:6000]}"):
        target = f"VT-EO-{match.group(1).upper()}"
        if target != action.stable_id:
            rows.append({"source_order_id": action.stable_id, "target_order_id": target, "relationship_type": relation, "relationship_text": match.group(0), "relationship_source": "title_or_document_text", "confidence": "high"})
    return list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for r in rows}.values())


def action_row(a: Action) -> dict[str, str]:
    return {"declaration_id": a.stable_id, "state": "VT", "governor": "Phil Scott", "eo_number": a.number, "action_kind": a.action_kind, "action_type": a.action_type, "event_description": a.title, "date_signed": a.date_signed or "", "end_date": "", "weather_related": "true" if a.weather_related else "false", "source_scope": "governor_scott_executive_orders", "document_format": "pdf" if a.document_url else "html", "detail_url": a.document_url or a.detail_url, "archive_record_url": a.detail_url}


def write(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    actions = collect(); rows = [action_row(a) for a in actions]
    write(args.actions_out, ACTION_FIELDS, rows)
    rels = list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for a in actions for r in relationships(a)}.values())
    write(args.relationships_out, REL_FIELDS, rels)
    joins = [{field: action_row(a)[field] for field in JOIN_FIELDS} for a in actions if a.action_type == "declaration" and a.weather_related and a.date_signed]
    write(args.join_out, JOIN_FIELDS, joins)
    print(f"Vermont: {len(actions)} actions, {len(rels)} relationships, {len(joins)} weather declarations")


if __name__ == "__main__": main()
