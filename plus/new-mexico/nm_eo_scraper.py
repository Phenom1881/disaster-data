"""Collect emergency-relevant New Mexico executive orders from the Governor archive."""
from __future__ import annotations

import argparse
import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.governor.state.nm.us/about-the-governor/executive-orders/"
ARCHIVE_URL = "https://www.governor.state.nm.us/about-the-governor/executive-orders/executive-orders-archive/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 90
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
HAZARD_RE = re.compile(r"\b(wildfires?|forest fires?|fire emergency|flood(?:s|ing)?|flash flood(?:s|ing)?|severe (?:storms?|weather)|winter storms?|winter weather|snow(?:fall)?|ice|freez(?:e|ing)|drought|extreme heat|tornado(?:es)?|hail|heavy rain(?:fall)?|high winds?|mudslides?|debris flows?|monsoon|hurricanes?|tropical storms?)\b", re.I)
RELEVANT_RE = re.compile(r"\b(state of emergency|public health emergency|disaster|emergency declaration|emergency response|emergency funds?|national guard)\b", re.I)
MODIFIER_RE = re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|revok(?:e|es|ed|ing))\b", re.I)
OPERATIONAL_RE = re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|transportation waiver|suspension of regulations?)\b", re.I)
HAZARD_OVERRIDES = {}


@dataclass(frozen=True)
class Action:
    number: str
    title: str
    date: str
    url: str
    text: str
    extraction_ok: bool = True
    retrieval_ok: bool = True

    @property
    def stable_id(self):
        return "NM-" + self.number


def get(url):
    last = None
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            if attempt < 3:
                time.sleep(0.5 * (attempt + 1))
    raise last


def parse_index(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for anchor in soup.select("a[href]"):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        match = re.search(r"Executive Order\s+(20\d{2}-\d{3})\b", label, re.I)
        if match and ".pdf" in anchor.get("href", "").lower():
            href = anchor["href"]
            # The migrated index prepends /assets/ to legacy absolute-host paths.
            # Those rewritten links 404; the same official files remain live on
            # the Governor's canonical non-www WordPress host.
            if href.startswith("/assets/www.governor.state.nm.us/"):
                href = "https://governor.state.nm.us/" + href.split("/assets/www.governor.state.nm.us/", 1)[1]
            found.append((match.group(1), urljoin(base_url, href)))
    return found


def extract_pdf(data):
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages)
        return re.sub(r"[ \t]+", " ", text).strip(), bool(text.strip())
    except Exception:
        return "", False


def extract_title(text, number):
    compact = re.sub(r"\s+", " ", text)
    start = re.search(rf"(?:EXECUTIVE\s+ORDER(?:\s+NO\.?)?\s*)?{re.escape(number)}", compact, re.I)
    tail = compact[start.end():] if start else compact[:1600]
    tail = re.split(r"\bWHEREAS\b", tail, maxsplit=1, flags=re.I)[0]
    tail = re.sub(r"^(?:STATE OF NEW MEXICO|OFFICE OF THE GOVERNOR|MICHELLE LUJAN GRISHAM|GOVERNOR|EXECUTIVE ORDER)\s*", "", tail, flags=re.I)
    tail = re.sub(r"\s+", " ", tail).strip(" :-\n")
    return tail[:500] or f"Executive Order {number} (text unavailable)"


def extract_date(text, number):
    year = number[:4]
    month = r"January|February|March|April|May|June|July|August|September|October|November|December"
    candidates = []
    for match in re.finditer(rf"\b({month})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+({year})\b", text, re.I):
        candidates.append((match.start(), match.group(1), match.group(2), match.group(3)))
    for match in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+day\s+of\s+({month})[,]?\s+({year})\b", text, re.I):
        candidates.append((match.start(), match.group(2), match.group(1), match.group(3)))
    if not candidates:
        return ""
    _, name, day, yr = max(candidates)
    return datetime.strptime(f"{name} {day} {yr}", "%B %d %Y").strftime("%Y-%m-%d")


def parse_document(number, url):
    try:
        response = get(url)
        retrieval_ok = response.content.startswith(b"%PDF")
        text, ok = extract_pdf(response.content) if retrieval_ok else ("", False)
    except requests.RequestException:
        text, ok, retrieval_ok = "", False, False
    return Action(number, extract_title(text, number), extract_date(text, number), url, text, ok, retrieval_ok)


def collect():
    pairs = []
    for source in (CURRENT_URL, ARCHIVE_URL):
        pairs.extend(parse_index(get(source).text, source))
    unique = dict(pairs)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda pair: parse_document(*pair), unique.items()))
    return sorted(records, key=lambda item: item.number, reverse=True)


def classify(action):
    if not action.extraction_ok:
        return "unclassified"
    evidence = action.title + " " + action.text
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "terminat", "revok")):
            return "termination"
        if word.startswith(("renew", "extend")):
            return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title):
        return "administrative"
    if re.search(r"^\s*DECLAR(?:ING|ATION OF)\b.{0,180}\b(?:STATE OF EMERGENCY|DISASTER|AN EMERGENCY)\b", action.title, re.I):
        return "declaration"
    return "administrative"


def relationships(actions):
    known = {item.number for item in actions}
    rows = []
    for action in actions:
        kind = classify(action)
        if kind not in {"amendment", "extension", "termination"}:
            continue
        for target in sorted(set(re.findall(r"\b20\d{2}-\d{3}\b", action.title + " " + action.text)) - {action.number}):
            if target in known:
                rows.append({"source_order_id": action.stable_id, "target_order_id": "NM-" + target, "relationship_type": kind, "relationship_text": action.title, "relationship_source": action.url, "confidence": "high"})
    return rows


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions, actions_out, relationships_out, join_out):
    rows, joins = [], []
    for action in actions:
        evidence = action.title + " " + action.text
        kind = classify(action)
        relevant = bool(RELEVANT_RE.search(evidence) or HAZARD_RE.search(evidence))
        if not relevant and action.extraction_ok:
            continue
        weather = kind == "declaration" and bool(HAZARD_RE.search(evidence))
        document_format = "pdf" if action.extraction_ok else ("pdf_ocr_required" if action.retrieval_ok else "pdf_unavailable")
        row = {"declaration_id": action.stable_id, "state": "NM", "governor": "Michelle Lujan Grisham", "eo_number": action.number, "action_kind": "executive_order", "action_type": kind, "event_description": action.title, "date_signed": action.date, "end_date": "", "weather_related": str(weather).lower(), "source_scope": "new_mexico_governor_executive_orders_2019_present", "document_format": document_format, "detail_url": action.url, "archive_record_url": action.url}
        rows.append(row)
        if weather and kind == "declaration" and action.date:
            joins.append({field: row[field] for field in JOIN_FIELDS})
    write_csv(actions_out, ACTION_FIELDS, rows)
    write_csv(relationships_out, REL_FIELDS, relationships(actions))
    write_csv(join_out, JOIN_FIELDS, joins)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    write_outputs(collect(), args.actions_out, args.relationships_out, args.join_out)


if __name__ == "__main__":
    main()
