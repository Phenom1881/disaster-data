"""Collect Massachusetts executive orders from the official State Library.

The DSpace collection contains the 1941-1947 first series and the numbered
series begun in 1950.  Only original orders whose official metadata or text
names a weather hazard enter ``declarations_for_join.csv``.  A generic state
of emergency is not treated as weather-related.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import requests


SEARCH_URL = "https://archives.lib.state.ma.us/server/api/discover/search/objects"
ARCHIVE_PAGE = "https://www.mass.gov/massachusetts-executive-orders"
SEARCH_QUERY = 'dc.relation.aggregation:"Executive Orders"'
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)"}
WEATHER_PATTERNS = (
    re.compile(r"\bdrought\b", re.I),
    re.compile(r"\b(?:wildfire|forest fire|brush fire|fire weather)\b", re.I),
    re.compile(r"\b(?:flash )?flood(?:ing|s)?\b|\brain ?storm\b", re.I),
    re.compile(r"\b(?:hurricane|tropical (?:storm|cyclone|depression))\b", re.I),
    re.compile(r"\b(?:blizzard|winter (?:storm|weather)|snow(?:fall|storm)?|ice storm|nor['’]?easter)\b", re.I),
    re.compile(r"\b(?:severe (?:storm|weather)|thunderstorm|tornado)\b", re.I),
    re.compile(r"\b(?:wind storm|high winds?|damaging winds?|wind gusts?)\b", re.I),
)
RELATIONSHIP_RE = re.compile(
    r"(?P<verb>amend(?:s|ed|ing)?|exten(?:d(?:s|ed|ing)?|sion)|continu(?:e|es|ed|ing)|"
    r"terminat(?:e|es|ed|ing)|rescind(?:s|ed|ing)?|revoke(?:s|d|ing)?|supersed(?:e|es|ed|ing))"
    r".{0,140}?executive\s+order(?:\s+(?:no\.?|number))?\s*(?P<number>\d+[A-Z]?)",
    re.I | re.S,
)


@dataclass
class MAOrder:
    number: str
    first_series: bool
    title: str
    description: str
    date_issued: Optional[str]
    governor: str
    item_url: str
    api_url: str
    action_kind: str = "executive_order"
    notes: str = ""
    document_text: str = ""
    action_type: str = "administrative"
    weather_related: bool = False
    end_date: Optional[str] = None

    @property
    def stable_id(self) -> str:
        if self.action_kind == "emergency_proclamation":
            return f"MA-PROC-{self.date_issued or 'UNDATED'}-{self.api_url.rstrip('/').rsplit('/', 1)[-1][:8]}"
        return f"MA-EO-{'1S-' if self.first_series else ''}{self.number.upper()}"


def fetch_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = str(raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def governor_for_date(value: Optional[str]) -> str:
    if not value:
        return ""
    periods = (
        ("2023-01-05", "Maura Healey"), ("2015-01-08", "Charlie Baker"),
        ("2007-01-04", "Deval Patrick"), ("2003-01-02", "Mitt Romney"),
        ("2001-04-10", "Jane Swift"), ("1997-07-29", "Paul Cellucci"),
        ("1991-01-03", "William Weld"), ("1983-01-06", "Michael Dukakis"),
        ("1979-01-04", "Edward King"), ("1975-01-02", "Michael Dukakis"),
        ("1969-01-02", "Francis Sargent"), ("1965-01-07", "John Volpe"),
        ("1963-01-03", "Endicott Peabody"), ("1961-01-05", "John Volpe"),
        ("1957-01-03", "Foster Furcolo"), ("1953-01-08", "Christian Herter"),
        ("1949-01-06", "Paul Dever"), ("1947-01-02", "Robert Bradford"),
        ("1945-01-04", "Maurice Tobin"), ("1939-01-05", "Leverett Saltonstall"),
    )
    for start, governor in periods:
        if value >= start:
            return governor
    return ""


def metadata_values(item: dict, key: str) -> list[str]:
    return [str(row.get("value") or "").strip() for row in item.get("metadata", {}).get(key, [])]


def parse_item(item: dict) -> Optional[MAOrder]:
    title = str(item.get("name") or "").strip()
    match = re.search(r"Executive Order(?: \(new series\))? No\.\s*(\d+[A-Z]?)\b", title, re.I)
    if not match:
        return None
    dates = metadata_values(item, "dc.date.issued")
    issued = normalize_date(dates[0]) if dates else None
    alternatives = metadata_values(item, "dc.title.alternative")
    notes = metadata_values(item, "dc.description") + metadata_values(item, "dc.description.note")
    description = " ".join(value for value in alternatives if value).strip() or title
    uuid = str(item.get("uuid") or item.get("id") or "")
    return MAOrder(
        number=match.group(1), first_series="new series" not in title.lower(),
        title=title, description=description, date_issued=issued,
        governor=governor_for_date(issued),
        item_url=f"https://archives.lib.state.ma.us/entities/journalfile/{uuid}",
        api_url=item.get("_links", {}).get("self", {}).get("href", ""),
        notes=" ".join(value for value in notes if value).strip(),
    )


def parse_emergency_item(item: dict) -> Optional[MAOrder]:
    title = str(item.get("name") or "").strip()
    authors = metadata_values(item, "dc.contributor.author")
    if "Massachusetts. Governor." not in authors:
        return None
    if not re.search(r"Governor .+ (?:Declares State of Emergency|Issues Emergency Declaration|Declares Emergency)", title, re.I):
        return None
    if not any(pattern.search(title) for pattern in WEATHER_PATTERNS):
        return None
    dates = metadata_values(item, "dc.date.issued")
    issued = normalize_date(dates[0]) if dates else None
    uuid = str(item.get("uuid") or item.get("id") or "")
    return MAOrder(
        number="", first_series=False, title=title, description=title,
        date_issued=issued, governor=governor_for_date(issued),
        item_url=f"https://archives.lib.state.ma.us/entities/journalfile/{uuid}",
        api_url=item.get("_links", {}).get("self", {}).get("href", ""),
        action_kind="emergency_proclamation", action_type="declaration",
        weather_related=True,
    )


def collect_orders() -> list[MAOrder]:
    orders, page = [], 0
    while True:
        payload = fetch_json(SEARCH_URL, {"query": SEARCH_QUERY, "size": 100, "page": page})
        if payload is None:
            break
        result = payload.get("_embedded", {}).get("searchResult", {})
        for wrapper in result.get("_embedded", {}).get("objects", []):
            order = parse_item(wrapper.get("_embedded", {}).get("indexableObject", {}))
            if order:
                orders.append(order)
        if page + 1 >= int(result.get("page", {}).get("totalPages") or 0):
            break
        page += 1
    for query in ('dc.title:"state of emergency"', 'dc.title:"emergency declaration"'):
        payload = fetch_json(SEARCH_URL, {"query": query, "size": 100})
        result = payload.get("_embedded", {}).get("searchResult", {}) if payload else {}
        for wrapper in result.get("_embedded", {}).get("objects", []):
            action = parse_emergency_item(wrapper.get("_embedded", {}).get("indexableObject", {}))
            if action:
                orders.append(action)
    return dedupe_orders(orders)


def fetch_document_text(order: MAOrder) -> str:
    payload = fetch_json(order.api_url + "/bundles") if order.api_url else None
    bundles = payload.get("_embedded", {}).get("bundles", []) if payload else []
    bundles.sort(key=lambda row: 0 if row.get("name") == "TEXT" else 1)
    for bundle in bundles:
        if bundle.get("name") not in {"TEXT", "ORIGINAL"}:
            continue
        href = bundle.get("_links", {}).get("bitstreams", {}).get("href", "")
        bits = fetch_json(href) if href else None
        for bit in bits.get("_embedded", {}).get("bitstreams", []) if bits else []:
            name = str(bit.get("name") or "").lower()
            content_url = bit.get("_links", {}).get("content", {}).get("href", "")
            if content_url and (bundle.get("name") == "TEXT" or name.endswith((".txt", ".html", ".htm"))):
                try:
                    response = requests.get(content_url, headers=HEADERS, timeout=TIMEOUT)
                    response.raise_for_status()
                    return response.text.strip()
                except requests.RequestException:
                    continue
    return ""


def classify_action(order: MAOrder) -> str:
    if order.action_kind == "emergency_proclamation":
        return "declaration"
    lead = f"{order.title} {order.description}"
    if re.search(r"\b(?:rescind|revoke|terminat|ending)\w*\b", lead, re.I):
        return "termination"
    if re.search(r"\b(?:amend|modif|revis)\w*\b", lead, re.I):
        return "amendment"
    if re.search(r"\b(?:extension|extend|extends|extended|extending|renew|renews|renewed|renewing|continuation)\b", lead, re.I):
        return "extension"
    if re.search(r"\bdeclaring\b.{0,100}\b(?:state of )?(?:disaster |public health )?emergency\b", lead, re.S | re.I):
        return "declaration"
    return "administrative"


def is_weather_related(order: MAOrder) -> bool:
    text = f"{order.title} {order.description} {order.document_text}"
    return any(pattern.search(text) for pattern in WEATHER_PATTERNS)


def relationship_type(verb: str) -> str:
    verb = verb.lower()
    if verb.startswith(("terminat", "rescind", "revoke")):
        return "terminates"
    if verb.startswith(("exten", "continu")):
        return "extends_duration"
    if verb.startswith("supersed"):
        return "supersedes"
    return "amends"


def extract_relationships(order: MAOrder) -> list[dict[str, str]]:
    rows = []
    for match in RELATIONSHIP_RE.finditer(f"{order.description} {order.document_text}"):
        rows.append({
            "source_order_id": order.stable_id,
            "target_order_id": f"MA-EO-{'1S-' if order.first_series else ''}{match.group('number').upper()}",
            "relationship_type": relationship_type(match.group("verb")),
            "relationship_text": re.sub(r"\s+", " ", match.group(0)).strip(),
            "relationship_source": "official_metadata_or_text", "confidence": "medium",
        })
    passive = re.compile(r"(?P<verb>amended|rescinded|revoked|terminated)\s+by\s+Executive Order(?: No\.)?\s*(?P<number>\d+[A-Z]?)", re.I)
    for match in passive.finditer(order.notes):
        verb = match.group("verb")
        rows.append({
            "source_order_id": f"MA-EO-{'1S-' if order.first_series else ''}{match.group('number').upper()}",
            "target_order_id": order.stable_id, "relationship_type": relationship_type(verb),
            "relationship_text": match.group(0), "relationship_source": "official_metadata", "confidence": "high",
        })
    return dedupe_relationships(rows)


def dedupe_orders(orders: Iterable[MAOrder]) -> list[MAOrder]:
    unique = {order.stable_id: order for order in orders}
    return sorted(unique.values(), key=lambda row: (row.date_issued or "", row.stable_id), reverse=True)


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result, seen = [], set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen and key[0] != key[1]:
            seen.add(key); result.append(row)
    return result


ACTION_FIELDS = ["declaration_id", "state", "governor", "eo_number", "action_type", "event_description", "date_signed", "end_date", "weather_related", "document_format", "archive_record_url"]
REL_FIELDS = ["source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence"]
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]


def write_outputs(orders: list[MAOrder], relationships: list[dict[str, str]], actions_path: str, relationships_path: str, join_path: str) -> None:
    with open(actions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTION_FIELDS); writer.writeheader()
        for order in orders:
            writer.writerow({"declaration_id": order.stable_id, "state": "MA", "governor": order.governor, "eo_number": order.number, "action_type": order.action_type, "event_description": order.description or order.title, "date_signed": order.date_issued or "", "end_date": order.end_date or "", "weather_related": order.weather_related, "document_format": "html", "archive_record_url": order.item_url})
    with open(relationships_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REL_FIELDS); writer.writeheader(); writer.writerows(relationships)
    with open(join_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOIN_FIELDS); writer.writeheader()
        for order in orders:
            if order.action_type == "declaration" and order.weather_related and order.date_issued:
                writer.writerow({"declaration_id": order.stable_id, "governor": order.governor, "eo_number": order.number, "event_description": order.description or order.title, "date_signed": order.date_issued, "archive_record_url": order.item_url})


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Massachusetts executive orders")
    parser.add_argument("--actions-out", default="ma_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="ma_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()
    print("Massachusetts scraper: collecting State Library executive-order records...")
    orders = collect_orders()
    if not orders:
        raise SystemExit("ERROR: no Massachusetts executive orders were collected")
    if not args.skip_document_fetch:
        candidates = [o for o in orders if o.action_kind == "executive_order" and re.search(r"emerg|storm|flood|drought|hurricane|tornado|snow|blizzard|fire|rescind|revoke|amend|extend|supersed", f"{o.title} {o.description} {o.notes}", re.I)]
        print(f"Massachusetts scraper: fetching official text for {len(candidates)} candidate record(s)...")
        for order in candidates:
            order.document_text = fetch_document_text(order)
    for order in orders:
        order.action_type = classify_action(order)
        order.weather_related = is_weather_related(order)
    relationships = dedupe_relationships(row for order in orders for row in extract_relationships(order))
    valid = {order.stable_id for order in orders}
    relationships = [row for row in relationships if row["target_order_id"] in valid]
    by_id = {order.stable_id: order for order in orders}
    for row in relationships:
        if row["relationship_type"] == "terminates" and by_id[row["source_order_id"]].date_issued:
            by_id[row["target_order_id"]].end_date = by_id[row["source_order_id"]].date_issued
    write_outputs(orders, relationships, args.actions_out, args.relationships_out, args.join_out)
    join_count = sum(o.action_type == "declaration" and o.weather_related and bool(o.date_issued) for o in orders)
    print(f"Done. {len(orders)} action(s), {len(relationships)} relationship(s), {join_count} original weather declaration(s).")


if __name__ == "__main__":
    main()
