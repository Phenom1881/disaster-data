"""Collect North Carolina Executive Orders for DisasterData Plus.

Official structured source:
    https://governor.nc.gov/news/executive-orders

The paginated collection covers the Cooper administration (January 2017-
December 2024) and the current Stein administration.  It also mixes true
orders with Council of State concurrence records, translations, FAQs, and
guidance.  This collector canonicalizes one English record per governor/order
number and retains the other URLs as supporting documents.

Pre-2017 orders published in the North Carolina Register require a separate
historical backfill and are not represented as complete coverage here.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag


ARCHIVE_URL = "https://governor.nc.gov/news/executive-orders"
REQUEST_TIMEOUT = 60
LOW_YIELD_PDF_CHARS = 250
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; "
        "+https://disasterdata.io/plus/)"
    )
}

WEATHER_KEYWORDS = (
    "blizzard", "coastal flood", "drought", "extreme cold", "extreme heat",
    "flash flood", "flood", "freezing rain", "hail", "heavy rain",
    "hurricane", "ice storm", "nor'easter", "noreaster", "severe weather",
    "snow", "storm surge", "tornado", "tropical depression",
    "tropical storm", "wildfire", "winter storm", "winter weather",
)

NUMBER_RE = re.compile(
    r"(?:executive\s+order(?:\s+(?:no\.?|number))?|\bEO)\s*[#.: -]*"
    r"(?P<number>\d+)",
    re.I,
)
DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.??"
    r"\s+\d{1,2},\s+\d{4}\b",
    re.I,
)
SUPPORT_RE = re.compile(
    r"\b(spanish|espa[nñ]ol|faq|guidance|concurrence|cos\s*vote|translation)\b",
    re.I,
)
ORDER_LIST_RE = re.compile(
    r"(?:executive\s+orders?|e\.?o\.?s?)\s*"
    r"(?:nos?\.?|numbers?)?\s*([0-9][0-9,\s]*(?:and|&|-)?[0-9,\s]*)",
    re.I,
)


@dataclass
class ArchiveEntry:
    order_number: str
    title: str
    date_issued: Optional[str]
    detail_url: str
    supporting: bool = False


@dataclass
class NCOrder:
    governor: str
    order_number: str
    title: str
    description: str
    date_issued: Optional[str]
    detail_url: str
    document_url: str = ""
    document_label: str = ""
    document_format: str = "html"
    supporting_urls: list[str] = field(default_factory=list)
    document_text: str = ""
    action_type: str = "administrative"
    weather_related: bool = False
    end_date: Optional[str] = None

    @property
    def stable_id(self) -> str:
        governor_key = re.sub(r"[^A-Z]", "", self.governor.upper()) or "UNKNOWN"
        return f"NC-{governor_key}-EO-{self.order_number}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"\bSept?\.\s*", "Sep ", raw, flags=re.I)
    raw = re.sub(r"\b([A-Za-z]{3,8})\.\s*", r"\1 ", raw)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def governor_for_date(value: Optional[str]) -> str:
    if not value:
        return ""
    if value >= "2025-01-01":
        return "Josh Stein"
    if value >= "2017-01-01":
        return "Roy Cooper"
    return ""


def _row_for_link(link: Tag) -> Tag:
    row = link.find_parent("tr")
    if row:
        return row
    row = link.find_parent(class_=re.compile(r"views-row|document-row|item-list", re.I))
    if row:
        return row
    node: Tag = link
    for _ in range(5):
        parent = node.parent
        if not isinstance(parent, Tag):
            break
        text = parent.get_text(" ", strip=True)
        if DATE_RE.search(text) and len(text) < 2500:
            return parent
        node = parent
    return link


def parse_archive_page(html: str, page_url: str = ARCHIVE_URL) -> list[ArchiveEntry]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("main") or soup
    entries: list[ArchiveEntry] = []
    seen_urls: set[str] = set()
    for link in root.select("a[href]"):
        title = link.get_text(" ", strip=True)
        match = NUMBER_RE.search(title)
        if not match:
            continue
        url = urljoin(page_url, link["href"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        row = _row_for_link(link)
        row_text = row.get_text(" ", strip=True)
        date_match = DATE_RE.search(row_text)
        entries.append(ArchiveEntry(
            order_number=match.group("number"),
            title=title,
            date_issued=normalize_date(date_match.group(0)) if date_match else None,
            detail_url=url,
            supporting=bool(SUPPORT_RE.search(title)),
        ))
    return entries


def _has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one('a[rel="next"]')
        or soup.select_one(".pager__item--next a")
        or soup.find("a", string=re.compile(r"(?:Next|››)", re.I))
    )


def collect_archive_entries() -> list[ArchiveEntry]:
    collected: list[ArchiveEntry] = []
    known_urls: set[str] = set()
    page = 0
    while page < 100:
        page_url = _with_page(ARCHIVE_URL, page)
        response = fetch(page_url)
        if response is None:
            break
        page_entries = parse_archive_page(response.text, page_url)
        new_entries = [entry for entry in page_entries if entry.detail_url not in known_urls]
        for entry in new_entries:
            known_urls.add(entry.detail_url)
        collected.extend(new_entries)
        print(f"    page {page + 1}: {len(page_entries)} candidate(s), {len(new_entries)} new")
        if not page_entries or not _has_next_page(response.text):
            break
        page += 1
    return collected


def _canonical_rank(entry: ArchiveEntry) -> tuple[int, int, int]:
    title = entry.title.lower()
    return (
        0 if entry.supporting else 1,
        1 if re.search(r"executive\s+order\s+(?:no\.?\s*)?\d+", title) else 0,
        -len(title),
    )


def canonicalize_entries(entries: Iterable[ArchiveEntry]) -> list[NCOrder]:
    groups: dict[tuple[str, str], list[ArchiveEntry]] = {}
    for entry in entries:
        governor = governor_for_date(entry.date_issued)
        if not governor:
            continue
        groups.setdefault((governor, entry.order_number), []).append(entry)

    orders: list[NCOrder] = []
    for (governor, number), members in groups.items():
        primary_candidates = [entry for entry in members if not entry.supporting]
        if not primary_candidates:
            continue
        primary = max(primary_candidates, key=_canonical_rank)
        supporting_urls = sorted({entry.detail_url for entry in members if entry.detail_url != primary.detail_url})
        orders.append(NCOrder(
            governor=governor,
            order_number=number,
            title=primary.title,
            description=primary.title,
            date_issued=primary.date_issued,
            detail_url=primary.detail_url,
            supporting_urls=supporting_urls,
        ))
    return sorted(orders, key=lambda order: (order.date_issued or "", int(order.order_number)))


def _first_published(text: str) -> Optional[str]:
    match = re.search(r"First\s+Published\s+(" + DATE_RE.pattern + r")", text, re.I)
    return normalize_date(match.group(1)) if match else None


def _document_link(soup: BeautifulSoup, page_url: str) -> tuple[str, str]:
    for link in soup.select("main a[href], article a[href]"):
        label = link.get_text(" ", strip=True)
        href = link.get("href", "")
        combined = f"{label} {href}".lower()
        if "spanish" in combined or "español" in combined:
            continue
        if ".pdf" in combined or href.endswith("/open") or "/download" in href:
            return urljoin(page_url, href), label
    return "", ""


def fetch_pdf_text(url: str) -> str:
    response = fetch(url)
    if response is None:
        return ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed for {url}: {exc}", file=sys.stderr)
        return ""


def enrich_order(order: NCOrder, fetch_pdf: bool = True) -> None:
    response = fetch(order.detail_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, "html.parser")
    heading = soup.select_one("main h1") or soup.select_one("h1")
    if heading:
        order.title = heading.get_text(" ", strip=True)
    main = soup.select_one("main") or soup.select_one("article")
    page_text = main.get_text(" ", strip=True) if main else ""
    published = _first_published(page_text)
    if published:
        order.date_issued = published
        order.governor = governor_for_date(published) or order.governor
    order.document_url, order.document_label = _document_link(soup, order.detail_url)
    order.document_format = "pdf" if order.document_url else "html"

    # Some newer detail pages reproduce the complete order as HTML; older
    # records often contain metadata only. Strip the metadata tail before using
    # page text for classification and relationship extraction.
    body_text = re.split(r"\bDocument\s+Entity\s+Terms\b|\bFirst\s+Published\b", page_text, maxsplit=1, flags=re.I)[0]
    if len(body_text) >= LOW_YIELD_PDF_CHARS:
        order.document_text = body_text
    if fetch_pdf and order.document_url and len(order.document_text) < LOW_YIELD_PDF_CHARS:
        order.document_text = fetch_pdf_text(order.document_url)

    number_heading = re.search(
        r"EXECUTIVE\s+ORDER\s+(?:NO\.?\s*)?" + re.escape(order.order_number)
        + r"\s+(.{5,220}?)(?=\bWHEREAS\b|\bSection\s+1\b)",
        order.document_text,
        re.I | re.S,
    )
    if number_heading:
        description = re.sub(r"\s+", " ", number_heading.group(1)).strip(" :-")
        if description:
            order.description = description


def classify_action(order: NCOrder) -> str:
    text = f"{order.title} {order.description}".lower()
    if re.search(r"\b(notice\s+of\s+termination|terminat|rescind|revok)", text):
        return "termination"
    if re.search(r"\b(amend|modif)", text):
        return "amendment"
    if re.search(r"\b(extend|renew|continuing\s+the\s+state\s+of\s+emergency)", text):
        return "extension"
    if re.search(r"\b(declaration\s+of\s+(?:a\s+)?state\s+of\s+emergency|disaster\s+declaration|declare[sd]?\s+(?:a\s+)?state\s+of\s+emergency)", text):
        return "declaration"
    return "administrative"


def is_weather_related(order: NCOrder) -> bool:
    # File labels carry essential hazard names for older generic records such
    # as "Executive Order No. 74: Declaration of a State of Emergency."
    text = f"{order.title} {order.description} {order.document_label} {order.document_text}".lower()
    return any(keyword in text for keyword in WEATHER_KEYWORDS)


def _relationship_type(action_type: str) -> str:
    if action_type == "termination":
        return "terminates"
    if action_type == "extension":
        return "extends_duration"
    return "amends"


def referenced_numbers(order: NCOrder) -> list[str]:
    if order.action_type not in {"termination", "extension", "amendment"}:
        return []
    text = f"{order.title} {order.description} {order.document_text}"
    numbers: list[str] = []
    for match in ORDER_LIST_RE.finditer(text):
        for number in re.findall(r"\d+", match.group(1)):
            if number != order.order_number and number not in numbers:
                numbers.append(number)
    return numbers


def build_relationships(orders: list[NCOrder]) -> list[dict[str, str]]:
    by_governor_number = {(order.governor, order.order_number): order for order in orders}
    rows: list[dict[str, str]] = []
    for source in orders:
        for number in referenced_numbers(source):
            target = by_governor_number.get((source.governor, number))
            if target is None:
                # Resolve a cross-administration reference only when exactly one
                # earlier collected order has that number.
                candidates = [
                    order for order in orders
                    if order.order_number == number
                    and (order.date_issued or "") < (source.date_issued or "")
                ]
                if len(candidates) == 1:
                    target = candidates[0]
            if target is None or target.stable_id == source.stable_id:
                continue
            rows.append({
                "source_order_id": source.stable_id,
                "target_order_id": target.stable_id,
                "relationship_type": _relationship_type(source.action_type),
                "relationship_text": f"References Executive Order {number}",
                "relationship_source": "title_or_document_text",
                "confidence": "high" if target.governor == source.governor else "medium",
            })
    return dedupe_relationships(rows)


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def apply_end_dates(orders: list[NCOrder], relationships: list[dict[str, str]]) -> None:
    by_id = {order.stable_id: order for order in orders}
    for row in relationships:
        if row["relationship_type"] != "terminates":
            continue
        source = by_id.get(row["source_order_id"])
        target = by_id.get(row["target_order_id"])
        if source and target and source.date_issued:
            target.end_date = source.date_issued


def write_actions(orders: list[NCOrder], path: str) -> None:
    fields = [
        "declaration_id", "state", "governor", "eo_number", "action_type",
        "event_description", "date_signed", "end_date", "weather_related",
        "source_scope", "document_format", "detail_url", "archive_record_url",
        "supporting_urls",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for order in orders:
            writer.writerow({
                "declaration_id": order.stable_id, "state": "NC",
                "governor": order.governor, "eo_number": order.order_number,
                "action_type": order.action_type,
                "event_description": order.description or order.title,
                "date_signed": order.date_issued or "", "end_date": order.end_date or "",
                "weather_related": order.weather_related,
                "source_scope": "governor_archive_2017_present",
                "document_format": order.document_format,
                "detail_url": order.detail_url,
                "archive_record_url": order.document_url or order.detail_url,
                "supporting_urls": "|".join(order.supporting_urls),
            })


def write_relationships(rows: list[dict[str, str]], path: str) -> None:
    fields = ["source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_join(orders: list[NCOrder], path: str) -> None:
    fields = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for order in orders:
            if not order.weather_related or not order.date_issued or order.action_type != "declaration":
                continue
            writer.writerow({
                "declaration_id": order.stable_id, "governor": order.governor,
                "eo_number": order.order_number,
                "event_description": order.description or order.title,
                "date_signed": order.date_issued,
                "archive_record_url": order.document_url or order.detail_url,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect North Carolina Executive Orders")
    parser.add_argument("--actions-out", default="nc_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="nc_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()

    print("North Carolina scraper: walking official Executive Orders archive...")
    entries = collect_archive_entries()
    orders = canonicalize_entries(entries)
    if not orders:
        raise SystemExit("ERROR: no canonical North Carolina Executive Orders were collected")
    print(f"    {len(entries)} archive item(s); {len(orders)} canonical order(s)")

    if not args.skip_document_fetch:
        print("North Carolina scraper: enriching official detail records...")
        low_yield = 0
        for index, order in enumerate(orders, start=1):
            enrich_order(order, fetch_pdf=True)
            if order.document_format == "pdf" and len(order.document_text) < LOW_YIELD_PDF_CHARS:
                low_yield += 1
            if index % 50 == 0:
                print(f"    enriched {index}/{len(orders)}")
        if low_yield:
            print(f"  WARNING: {low_yield} PDF-backed record(s) yielded fewer than {LOW_YIELD_PDF_CHARS} characters and need OCR review", file=sys.stderr)

    for order in orders:
        order.action_type = classify_action(order)
        order.weather_related = is_weather_related(order)
    relationships = build_relationships(orders)
    apply_end_dates(orders, relationships)
    write_actions(orders, args.actions_out)
    write_relationships(relationships, args.relationships_out)
    write_join(orders, args.join_out)
    weather_declarations = sum(o.weather_related and o.action_type == "declaration" and bool(o.date_issued) for o in orders)
    print(f"Done. {len(orders)} canonical order(s); {len(relationships)} relationship(s); {weather_declarations} original weather declaration(s) written to join file.")


if __name__ == "__main__":
    main()
