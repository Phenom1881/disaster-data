"""Collect New York executive orders for DisasterData Plus.

Sources
-------
* Current, comprehensive Hochul listing (2021-08-24-present):
  https://www.governor.ny.gov/executiveorders
* Official selected prior orders still in effect (1970-present, incomplete):
  https://www.governor.ny.gov/past-executive-orders

The current listing is paginated and uses decimal order numbers for extensions
and modifications (for example, 52.1 and 52.2).  Decimal identifiers are kept
as strings.  The historical page is deliberately tagged ``selected_prior``;
it is not a complete archive of earlier administrations.
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
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


CURRENT_URL = "https://www.governor.ny.gov/executiveorders"
PAST_URL = "https://www.governor.ny.gov/past-executive-orders"
REQUEST_TIMEOUT = 45
ITEMS_PER_PAGE = 100
LOW_YIELD_PDF_CHARS = 250
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; "
        "+https://disasterdata.io/plus/)"
    )
}

# Do not treat the generic word "emergency" as proof of weather.  New York
# uses disaster-emergency orders for health care, corrections, migration,
# gun violence, and other non-weather subjects.
WEATHER_KEYWORDS = (
    "blizzard", "coastal flooding", "drought", "extreme cold",
    "extreme heat", "flash flood", "flood", "flooding", "freeze",
    "hail", "heat wave", "heavy rain", "hurricane", "ice storm",
    "lake effect", "nor'easter", "noreaster", "severe storm", "snow",
    "storm surge", "thunderstorm", "tornado", "tropical storm",
    "wildfire", "windstorm", "winter storm",
)

ORDER_NUMBER = r"\d+(?:\.\d+)?"
ORDER_REF_RE = re.compile(
    rf"(?:executive\s+order|e\.?o\.?)s?\s*"
    rf"(?:nos?\.?|numbers?)?\s*#?\s*({ORDER_NUMBER})",
    re.I,
)
ACTIVE_REL_RE = re.compile(
    rf"(?P<verb>extend(?:s|ed|ing)?|continu(?:e|es|ed|ing)|"
    rf"modif(?:y|ies|ied|ying)|amend(?:s|ed|ing)?|"
    rf"terminat(?:e|es|ed|ing)|rescind(?:s|ed|ing)?|"
    rf"revoke(?:s|d|ing)?)\s+(?:the\s+duration\s+of\s+)?"
    rf"(?:executive\s+order|e\.?o\.?)s?\s*"
    rf"(?:nos?\.?|numbers?)?\s*#?\s*(?P<number>{ORDER_NUMBER})",
    re.I,
)


@dataclass
class NYOrder:
    governor: str
    order_number: str
    title: str
    description: str
    date_issued: Optional[str]
    detail_url: str
    document_url: str
    document_format: str
    source_scope: str  # current_complete | selected_prior
    document_text: str = ""
    action_type: str = "declaration"
    weather_related: bool = False
    end_date: Optional[str] = None

    @property
    def stable_id(self) -> str:
        gov = re.sub(r"[^A-Z]", "", self.governor.upper()) or "UNK"
        return f"NY-{gov}-EO-{self.order_number}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def _with_query(url: str, **updates: object) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in updates.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s*\|.*$", "", raw).strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_number_and_title(text: str) -> tuple[Optional[str], str]:
    match = re.match(
        rf"\s*(?:executive\s+order\s+)?(?:no\.?\s*)?"
        rf"(?P<number>{ORDER_NUMBER})\s*:?[\s-]*(?P<title>.*)$",
        text,
        re.I,
    )
    if not match:
        return None, text.strip()
    return match.group("number"), match.group("title").strip()


def parse_current_page(html: str, page_url: str) -> list[NYOrder]:
    soup = BeautifulSoup(html, "html.parser")
    orders: list[NYOrder] = []
    for article in soup.select("article.node--type-executive-order"):
        title_link = article.select_one("h3.content-title a[href]")
        if title_link is None:
            continue
        heading = title_link.get_text(" ", strip=True)
        number, title = _parse_number_and_title(heading)
        if number is None:
            continue

        date_node = article.select_one(".content-dates")
        date_issued = normalize_date(date_node.get_text(" ", strip=True)) if date_node else None
        description_node = article.select_one(".content-description")
        description = description_node.get_text(" ", strip=True) if description_node else title
        document_link = article.select_one(".content-document a[href]")
        document_url = urljoin(page_url, document_link["href"]) if document_link else ""
        detail_url = urljoin(page_url, title_link["href"])
        fmt = "pdf" if document_url.lower().split("?", 1)[0].endswith(".pdf") else "html"
        orders.append(
            NYOrder(
                governor="Kathy Hochul",
                order_number=number,
                title=title,
                description=description,
                date_issued=date_issued,
                detail_url=detail_url,
                document_url=document_url or detail_url,
                document_format=fmt,
                source_scope="current_complete",
            )
        )
    return orders


def collect_current_orders() -> list[NYOrder]:
    """Walk every current-listing page until the pager ends or repeats."""
    collected: list[NYOrder] = []
    seen_ids: set[str] = set()
    page = 0
    while True:
        page_url = _with_query(CURRENT_URL, items_per_page=ITEMS_PER_PAGE, page=page)
        response = fetch(page_url)
        if response is None:
            break
        page_orders = parse_current_page(response.text, page_url)
        new_count = 0
        for order in page_orders:
            if order.stable_id in seen_ids:
                continue
            seen_ids.add(order.stable_id)
            collected.append(order)
            new_count += 1
        print(f"    current page {page + 1}: {len(page_orders)} row(s), {new_count} new")
        if not page_orders or new_count == 0 or len(page_orders) < ITEMS_PER_PAGE:
            break
        page += 1
        if page > 100:  # structural-change guard, not an expected limit
            print("  WARNING: current archive exceeded 100 pages; stopping", file=sys.stderr)
            break
    return collected


def parse_selected_prior(html: str, page_url: str = PAST_URL) -> list[NYOrder]:
    """Parse the official, explicitly selective prior-orders page."""
    soup = BeautifulSoup(html, "html.parser")
    orders: list[NYOrder] = []
    seen_ids: set[str] = set()
    for section in soup.select("div.t-section__wrapper"):
        heading = section.select_one("h2.t-section__title")
        if heading is None:
            continue
        governor = re.sub(r"^Governor\s+", "", heading.get_text(" ", strip=True), flags=re.I)
        if not governor:
            continue
        for link in section.select(".t-section__content a[href]"):
            text = link.get_text(" ", strip=True)
            match = re.search(
                rf"Executive\s+Order\s+No\.?\s*(?P<number>{ORDER_NUMBER})"
                rf"\s*,?\s*issued\s+(?P<date>[A-Za-z]+\s+\d{{1,2}},\s+\d{{4}})"
                rf"\s*\((?P<title>[^)]*)\)",
                text,
                re.I,
            )
            if not match:
                continue
            number = match.group("number")
            title = match.group("title").strip()
            document_url = urljoin(page_url, link["href"])
            order = NYOrder(
                governor=governor,
                order_number=number,
                title=title,
                description=title,
                date_issued=normalize_date(match.group("date")),
                detail_url=page_url,
                document_url=document_url,
                document_format="pdf" if document_url.lower().split("?", 1)[0].endswith(".pdf") else "html",
                source_scope="selected_prior",
            )
            if order.stable_id not in seen_ids:
                seen_ids.add(order.stable_id)
                orders.append(order)
    return orders


def collect_selected_prior_orders() -> list[NYOrder]:
    response = fetch(PAST_URL)
    return parse_selected_prior(response.text, PAST_URL) if response is not None else []


def fetch_document_text(order: NYOrder) -> str:
    # The current archive's PDFs are inconsistent: many are image-only, but
    # the corresponding detail page contains the complete order as selectable
    # HTML.  Prefer that authoritative HTML representation and avoid needless
    # OCR for comprehensive Hochul-era coverage.
    if order.source_scope == "current_complete" and order.detail_url:
        detail = fetch(order.detail_url)
        if detail is not None:
            soup = BeautifulSoup(detail.text, "html.parser")
            body = soup.select_one(".o-wysiwyg.executive_order")
            if body is not None:
                text = body.get_text(" ", strip=True)
                if len(text) >= LOW_YIELD_PDF_CHARS:
                    return text

    response = fetch(order.document_url)
    if response is None:
        return ""
    content_type = response.headers.get("content-type", "").lower()
    if order.document_format != "pdf" and "application/pdf" not in content_type:
        return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed for {order.document_url}: {exc}", file=sys.stderr)
        return ""


def classify_action(order: NYOrder) -> str:
    # Listing metadata is used intentionally; later annotations in a document
    # must not transform the original declaration into a termination.
    title = order.title.lower()
    text = f"{order.title} {order.description}".lower()
    # Lead verbs in the official title describe what this order does.  They
    # take priority over incidental references in the summary; EO 6.1, for
    # example, continues some orders while mentioning that others were revoked.
    if re.match(r"\s*(terminat|rescind|revok)", title):
        return "termination"
    if re.match(r"\s*(amend|modif)", title):
        return "amendment"
    if re.match(r"\s*(extend|continu)", title):
        return "extension"
    if re.search(r"\b(terminat|rescind|revok)", text) and "." not in order.order_number:
        return "termination"
    if re.search(r"\b(amend|modif)", text):
        return "amendment"
    if re.search(r"\b(extend|continu)", text) or "." in order.order_number:
        return "extension"
    return "declaration"


def is_weather_related(order: NYOrder) -> bool:
    text = f"{order.title} {order.description} {order.document_text}".lower()
    return any(keyword in text for keyword in WEATHER_KEYWORDS)


def _relationship_type(verb: str) -> str:
    verb = verb.lower()
    if verb.startswith(("terminat", "rescind", "revok")):
        return "terminates"
    if verb.startswith(("modif", "amend")):
        return "amends"
    return "extends_duration"


def extract_relationships(order: NYOrder) -> list[dict[str, str]]:
    """Extract same-governor relationships and deterministic decimal parents."""
    relationships: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(target_number: str, rel_type: str, rel_text: str, source: str) -> None:
        target_id = f"NY-{re.sub(r'[^A-Z]', '', order.governor.upper())}-EO-{target_number}"
        key = (order.stable_id, target_id, rel_type)
        if target_id == order.stable_id or key in seen:
            return
        seen.add(key)
        relationships.append({
            "source_order_id": order.stable_id,
            "target_order_id": target_id,
            "relationship_type": rel_type,
            "relationship_text": rel_text,
            "relationship_source": source,
            "confidence": "high" if source == "decimal_series" else "medium",
        })

    metadata = f"{order.title} {order.description}"
    for source, text in (("metadata", metadata), ("document_text", order.document_text)):
        for match in ACTIVE_REL_RE.finditer(text):
            add(match.group("number"), _relationship_type(match.group("verb")), match.group(0), source)

    if "." in order.order_number:
        parent = order.order_number.split(".", 1)[0]
        if order.action_type == "amendment":
            rel_type = "amends"
        else:
            rel_type = "extends_duration"
        add(parent, rel_type, f"Decimal-series child of Executive Order {parent}", "decimal_series")
    return relationships


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def apply_end_dates(orders: list[NYOrder], relationships: list[dict[str, str]]) -> None:
    by_id = {order.stable_id: order for order in orders}
    for rel in relationships:
        if rel["relationship_type"] != "terminates":
            continue
        source = by_id.get(rel["source_order_id"])
        target = by_id.get(rel["target_order_id"])
        if source and target and source.date_issued:
            target.end_date = source.date_issued


def write_actions(orders: list[NYOrder], path: str) -> None:
    fields = [
        "declaration_id", "state", "governor", "eo_number", "action_type",
        "event_description", "date_signed", "end_date", "weather_related",
        "source_scope", "document_format", "detail_url", "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for order in orders:
            writer.writerow({
                "declaration_id": order.stable_id,
                "state": "NY",
                "governor": order.governor,
                "eo_number": order.order_number,
                "action_type": order.action_type,
                "event_description": order.description or order.title,
                "date_signed": order.date_issued or "",
                "end_date": order.end_date or "",
                "weather_related": order.weather_related,
                "source_scope": order.source_scope,
                "document_format": order.document_format,
                "detail_url": order.detail_url,
                "archive_record_url": order.document_url,
            })


def write_relationships(rows: list[dict[str, str]], path: str) -> None:
    fields = [
        "source_order_id", "target_order_id", "relationship_type",
        "relationship_text", "relationship_source", "confidence",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_join(orders: list[NYOrder], path: str) -> None:
    fields = [
        "declaration_id", "governor", "eo_number", "event_description",
        "date_signed", "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for order in orders:
            if not order.weather_related or not order.date_issued:
                continue
            if order.action_type in {"termination", "extension", "amendment"}:
                continue
            writer.writerow({
                "declaration_id": order.stable_id,
                "governor": order.governor,
                "eo_number": order.order_number,
                "event_description": order.description or order.title,
                "date_signed": order.date_issued,
                "archive_record_url": order.document_url,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape New York executive orders")
    parser.add_argument("--actions-out", default="ny_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="ny_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()

    print("New York scraper: collecting current executive orders...")
    orders = collect_current_orders()
    current_count = len(orders)
    if not args.current_only:
        print("New York scraper: collecting selected prior orders...")
        prior = collect_selected_prior_orders()
        print(f"    selected prior: {len(prior)} row(s)")
        orders.extend(prior)

    if not orders:
        raise SystemExit("ERROR: no New York executive orders were collected")

    if not args.skip_document_fetch:
        print("New York scraper: fetching linked documents...")
        low_yield = 0
        for index, order in enumerate(orders, start=1):
            order.document_text = fetch_document_text(order)
            if order.document_format == "pdf" and len(order.document_text.strip()) < LOW_YIELD_PDF_CHARS:
                low_yield += 1
            if index % 50 == 0:
                print(f"    fetched {index}/{len(orders)}")
        if low_yield:
            print(f"  WARNING: {low_yield} PDF(s) yielded fewer than {LOW_YIELD_PDF_CHARS} characters", file=sys.stderr)

    for order in orders:
        order.action_type = classify_action(order)
        order.weather_related = is_weather_related(order)

    relationships = dedupe_relationships(
        rel for order in orders for rel in extract_relationships(order)
    )
    # Do not manufacture same-governor targets for references to an order from
    # a prior administration.  Cross-governor resolution needs signer-aware
    # logic and is intentionally deferred; only relationships whose endpoints
    # are actually present in this collection are emitted.
    valid_ids = {order.stable_id for order in orders}
    relationships = [
        rel for rel in relationships
        if rel["source_order_id"] in valid_ids and rel["target_order_id"] in valid_ids
    ]
    apply_end_dates(orders, relationships)
    write_actions(orders, args.actions_out)
    write_relationships(relationships, args.relationships_out)
    write_join(orders, args.join_out)

    weather_count = sum(order.weather_related for order in orders)
    join_count = sum(
        order.weather_related and bool(order.date_issued)
        and order.action_type not in {"termination", "extension", "amendment"}
        for order in orders
    )
    print(
        f"Done. {len(orders)} total row(s): {current_count} complete current, "
        f"{len(orders) - current_count} selected prior; {weather_count} weather-related; "
        f"{join_count} written to join file."
    )


if __name__ == "__main__":
    main()
