"""Collect Pennsylvania state actions for DisasterData Plus.

The collector deliberately keeps two official source scopes separate:

* ``oa_issuance_index`` -- the Office of Administration's searchable index of
  Executive Orders.  It is a current issuance catalog, not a complete archive.
* ``pema_proclamation_history`` -- PEMA's emergency-proclamation history,
  which currently provides linked proclamation documents from 2018 onward.

Only original weather-related emergency proclamations enter
``declarations_for_join.csv``.  Administrative Executive Orders and later
amendments/terminations remain available in the full action output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag


OA_POLICIES_URL = "https://www.pa.gov/agencies/oa/policies/view-policies"
PEMA_PROCLAMATIONS_URL = "https://www.pa.gov/agencies/pema/resources/emergency-proclamations"
COVEO_SEARCH_URL = "https://platform.cloud.coveo.com/rest/search/v2"
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
    "flash flood", "flood", "freezing", "hail", "heat wave", "heavy rain",
    "hurricane", "ice storm", "nor'easter", "noreaster", "severe weather",
    "snow", "storm", "tornado", "tropical", "wildfire", "winter weather",
)

RELATIONSHIP_RE = re.compile(
    r"(?P<verb>amend(?:s|ed|ing)?|extend(?:s|ed|ing)?|continu(?:e|es|ed|ing)|"
    r"terminat(?:e|es|ed|ing)|rescind(?:s|ed|ing)?|revoke(?:s|d|ing)?)"
    r".{0,120}?(?:executive\s+order|proclamation)(?:\s+(?:no\.?|number))?\s*"
    r"(?P<number>\d{4}[-_]\d+(?:R\d+)?)",
    re.I | re.S,
)


@dataclass
class PAAction:
    action_kind: str
    title: str
    description: str
    date_issued: Optional[str]
    document_url: str
    source_page_url: str
    source_scope: str
    action_number: str = ""
    governor: str = ""
    document_format: str = "pdf"
    document_text: str = ""
    action_type: str = "administrative"
    weather_related: bool = False
    end_date: Optional[str] = None
    parent_id: str = ""

    @property
    def stable_id(self) -> str:
        if self.action_kind == "executive_order" and self.action_number:
            number = self.action_number.upper().replace("_", "-")
            return f"PA-EO-{number}"
        stamp = self.date_issued or "UNDATED"
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:36]
        slug = slug or "proclamation"
        digest = hashlib.sha1(self.document_url.encode("utf-8")).hexdigest()[:7]
        return f"PA-PROC-{stamp}-{slug}-{digest}"


def fetch(url: str) -> Optional[requests.Response]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"\s+", " ", raw).strip().replace("Sept.", "Sep")
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", raw, flags=re.I)
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y", "%m.%d.%Y",
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def date_from_url(url: str) -> Optional[str]:
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    patterns = (
        r"(?<!\d)(20\d{2})[._-](\d{1,2})[._-](\d{1,2})(?!\d)",
        r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)",
        r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, name)
        if not match:
            continue
        parts = [int(value) for value in match.groups()]
        year, month, day = parts if index != 1 else (parts[2], parts[0], parts[1])
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def governor_for_date(value: Optional[str]) -> str:
    if not value:
        return ""
    if value >= "2023-01-17":
        return "Josh Shapiro"
    if value >= "2015-01-20":
        return "Tom Wolf"
    if value >= "2011-01-18":
        return "Tom Corbett"
    if value >= "2003-01-21":
        return "Ed Rendell"
    if value >= "1995-01-17":
        return "Tom Ridge"
    return ""


def discover_coveo_config(html: str) -> dict[str, str]:
    """Read the public short-lived search configuration from the PA page."""
    soup = BeautifulSoup(html, "html.parser")
    interface = soup.select_one("atomic-search-interface#search") or soup.select_one(
        "atomic-search-interface[search-hub]"
    )
    search_hub = interface.get("search-hub", "") if interface else ""
    token = ""
    organization = ""
    token_match = re.search(r"accessToken\s*:\s*['\"]([^'\"]+)['\"]", html)
    org_match = re.search(r"organizationId\s*:\s*['\"]([^'\"]+)['\"]", html)
    if token_match:
        token = token_match.group(1)
    if org_match:
        organization = org_match.group(1)
    if not organization:
        org_match = re.search(r"organization(?:Id)?[=:/'\"]+([a-z0-9]{15,})", html, re.I)
        if org_match:
            organization = org_match.group(1)
    return {"access_token": token, "organization_id": organization, "search_hub": search_hub}


def collect_oa_results() -> list[dict]:
    page = fetch(OA_POLICIES_URL)
    if page is None:
        return []
    config = discover_coveo_config(page.text)
    if not config["access_token"] or not config["organization_id"]:
        print("  WARNING: could not discover the PA policy-search configuration", file=sys.stderr)
        return []
    payload = {
        "q": "",
        "aq": '@copapwpcategory=="Executive Order"',
        "searchHub": config["search_hub"] or "OA-Policy Search With out IT-Policy",
        "numberOfResults": 1000,
        "firstResult": 0,
        "fieldsToInclude": ["copapwptitle", "copapwpissueyear", "copapwpissuemonth", "copapwpcategory"],
    }
    try:
        response = requests.post(
            COVEO_SEARCH_URL,
            params={"organizationId": config["organization_id"]},
            headers={**HEADERS, "Authorization": f"Bearer {config['access_token']}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        print(f"  WARNING: PA policy search failed: {exc}", file=sys.stderr)
        return []


def _eo_number_from_result(result: dict) -> str:
    candidates = [
        str(result.get("title") or ""),
        str(result.get("raw", {}).get("copapwptitle") or ""),
        str(result.get("uri") or result.get("clickUri") or ""),
    ]
    for value in candidates:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})[-_ ](\d+(?:R\d+)?)", value, re.I)
        if match:
            return f"{match.group(1)}-{match.group(2).upper()}"
    return ""


def parse_oa_result(result: dict) -> Optional[PAAction]:
    raw = result.get("raw") or {}
    url = result.get("clickUri") or result.get("uri") or ""
    number = _eo_number_from_result(result)
    if not url or not number:
        return None
    raw_title = str(raw.get("copapwptitle") or result.get("title") or "").strip()
    title = raw_title if raw_title and raw_title.lower() != "unknown" else f"Executive Order {number}"
    # Never turn a year/month facet into a fictitious first-of-month date.
    # Use an exact Coveo date only when one exists; otherwise the linked PDF
    # may supply the issuance/revision date during document enrichment.
    issue_date = None
    # Coveo's generic ``date`` can be the search-index modification time, not
    # the legal issuance date, so only use a purpose-built source field here.
    exact_date = str(raw.get("copapwpissuedate") or "").strip()
    iso_match = re.match(r"((?:19|20)\d{2}-\d{2}-\d{2})", exact_date)
    if iso_match:
        issue_date = normalize_date(iso_match.group(1))
    return PAAction(
        action_kind="executive_order",
        action_number=number,
        title=title,
        description=title,
        date_issued=issue_date,
        governor=governor_for_date(issue_date),
        document_url=url,
        source_page_url=OA_POLICIES_URL,
        source_scope="oa_issuance_index",
    )


def collect_oa_actions() -> list[PAAction]:
    actions = [parse_oa_result(result) for result in collect_oa_results()]
    return dedupe_actions(action for action in actions if action is not None)


def _text(node: Optional[Tag]) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _link_type(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("termination", "terminate", "rescission", "rescind")):
        return "termination"
    if "amend" in lowered:
        return "amendment"
    if "extend" in lowered or "renew" in lowered:
        return "extension"
    return "declaration"


def _linked_date(link: Tag, fallback: Optional[str], year_hint: str = "") -> Optional[str]:
    label = _text(link)
    candidates = [label, link.get("title", "")]
    if year_hint:
        candidates.extend(f"{value}, {year_hint}" for value in (label, link.get("title", "")))
    for candidate in candidates:
        match = re.search(r"([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", candidate)
        if match:
            parsed = normalize_date(match.group(1))
            if parsed:
                return parsed
    return date_from_url(link.get("href", "")) or fallback


def parse_pema_page(html: str, page_url: str = PEMA_PROCLAMATIONS_URL) -> list[PAAction]:
    soup = BeautifulSoup(html, "html.parser")
    actions: list[PAAction] = []

    for card in soup.select("div.cmp-teaser"):
        title = _text(card.select_one(".cmp-teaser__title"))
        if not title:
            continue
        card_date = normalize_date(_text(card.select_one(".cmp-teaser__eyebrow")))
        description = _text(card.select_one(".cmp-teaser__text")) or title
        links = card.select(".cmp-teaser__actions a[href]")
        base: Optional[PAAction] = None
        for index, link in enumerate(links):
            link_label = _text(link)
            action_type = _link_type(f"{link_label} {link.get('href', '')}") if index else "declaration"
            item_title = title if action_type == "declaration" else f"{title} {action_type.title()}"
            item = PAAction(
                action_kind="emergency_proclamation",
                title=item_title,
                description=description,
                date_issued=_linked_date(link, card_date),
                governor=governor_for_date(_linked_date(link, card_date)),
                document_url=urljoin(page_url, link["href"]),
                source_page_url=page_url,
                source_scope="pema_proclamation_history",
                action_type=action_type,
            )
            if base is None:
                base = item
            elif action_type != "declaration":
                item.parent_id = base.stable_id
            actions.append(item)

    for panel in soup.select(".cmp-accordion__item"):
        panel_title = _text(panel.select_one(".cmp-accordion__title"))
        if not re.search(r"amend|extension|termination", panel_title, re.I):
            continue
        current_year = ""
        for node in panel.select(".cmp-accordion__panel p, .cmp-accordion__panel a[href]"):
            if node.name == "p":
                match = re.search(r"\b((?:19|20)\d{2})\b", _text(node))
                if match:
                    current_year = match.group(1)
                continue
            action_type = _link_type(f"{panel_title} {_text(node)} {node.get('href', '')}")
            issue_date = _linked_date(node, None, current_year)
            title = re.sub(r"\s+Amendments?\s*$", "", panel_title, flags=re.I).strip()
            actions.append(PAAction(
                action_kind="emergency_proclamation",
                title=f"{title} {action_type.title()}",
                description=f"{panel_title}: {_text(node)}",
                date_issued=issue_date,
                governor=governor_for_date(issue_date),
                document_url=urljoin(page_url, node["href"]),
                source_page_url=page_url,
                source_scope="pema_proclamation_history",
                action_type=action_type,
            ))
    actions = dedupe_actions(actions)
    # Accordions contain later amendments, while their originating
    # proclamation is a separate teaser card. Resolve that relationship only
    # when a unique, explicit base card is present.
    bases: dict[str, list[PAAction]] = {}
    for action in actions:
        if action.action_type != "declaration":
            continue
        key = re.sub(r"\s+", " ", action.title.lower()).strip()
        bases.setdefault(key, []).append(action)
    for action in actions:
        if action.action_type == "declaration" or action.parent_id:
            continue
        topic = re.sub(r"\s+(amendment|extension|termination)$", "", action.title, flags=re.I)
        matches = bases.get(re.sub(r"\s+", " ", topic.lower()).strip(), [])
        if len(matches) == 1:
            action.parent_id = matches[0].stable_id
    return actions


def collect_pema_actions() -> list[PAAction]:
    response = fetch(PEMA_PROCLAMATIONS_URL)
    return parse_pema_page(response.text) if response is not None else []


def fetch_document_text(action: PAAction) -> str:
    response = fetch(action.document_url)
    if response is None:
        return ""
    if "pdf" not in response.headers.get("content-type", "").lower() and not action.document_url.lower().split("?", 1)[0].endswith(".pdf"):
        return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed for {action.document_url}: {exc}", file=sys.stderr)
        return ""


def enrich_from_document(action: PAAction) -> None:
    text = action.document_text
    if not text:
        return
    if not action.date_issued or (action.action_kind == "executive_order" and action.date_issued.endswith("-01")):
        for pattern in (
            r"\bDate\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})\b",
        ):
            match = re.search(pattern, text, re.I)
            if match:
                parsed = normalize_date(match.group(1))
                if parsed:
                    action.date_issued = parsed
                    break
    signer = re.search(r"(?:By\s+Direction\s+of|Governor)\s*:?\s*([A-Z][A-Za-z .'-]{4,50})", text)
    if signer:
        candidate = re.sub(r"\s+", " ", signer.group(1)).strip(" ,")
        if len(candidate.split()) <= 5:
            action.governor = candidate
    if not action.governor:
        action.governor = governor_for_date(action.date_issued)


def classify_action(action: PAAction) -> str:
    if action.action_type != "administrative":
        return action.action_type
    title = action.title.lower()
    if re.search(r"\b(terminat|rescind|revok)", title):
        return "termination"
    if re.search(r"\b(amend|modif|revis)", title):
        return "amendment"
    if re.search(r"\b(extend|renew|continu)", title):
        return "extension"
    return "administrative" if action.action_kind == "executive_order" else "declaration"


def is_weather_related(action: PAAction) -> bool:
    text = f"{action.title} {action.description} {action.document_text}".lower()
    return any(keyword in text for keyword in WEATHER_KEYWORDS)


def _relationship_type(action_type: str) -> str:
    if action_type == "termination":
        return "terminates"
    if action_type == "extension":
        return "extends_duration"
    return "amends"


def extract_relationships(action: PAAction) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if action.parent_id:
        rows.append({
            "source_order_id": action.stable_id,
            "target_order_id": action.parent_id,
            "relationship_type": _relationship_type(action.action_type),
            "relationship_text": "Linked with the original proclamation on the official PEMA page",
            "relationship_source": "archive_structure",
            "confidence": "high",
        })
    if action.action_kind == "executive_order":
        for match in RELATIONSHIP_RE.finditer(action.document_text):
            target = f"PA-EO-{match.group('number').upper().replace('_', '-')}"
            rows.append({
                "source_order_id": action.stable_id,
                "target_order_id": target,
                "relationship_type": _relationship_type(_link_type(match.group("verb"))),
                "relationship_text": re.sub(r"\s+", " ", match.group(0)).strip(),
                "relationship_source": "document_text",
                "confidence": "medium",
            })
    return dedupe_relationships(rows)


def dedupe_actions(actions: Iterable[PAAction]) -> list[PAAction]:
    result: list[PAAction] = []
    seen: set[str] = set()
    for action in actions:
        if action.stable_id not in seen:
            seen.add(action.stable_id)
            result.append(action)
    return result


def dedupe_relationships(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key not in seen and row["source_order_id"] != row["target_order_id"]:
            seen.add(key)
            result.append(row)
    return result


def apply_end_dates(actions: list[PAAction], relationships: list[dict[str, str]]) -> None:
    by_id = {action.stable_id: action for action in actions}
    for row in relationships:
        if row["relationship_type"] != "terminates":
            continue
        source = by_id.get(row["source_order_id"])
        target = by_id.get(row["target_order_id"])
        if source and target and source.date_issued:
            target.end_date = source.date_issued


def write_actions(actions: list[PAAction], path: str) -> None:
    fields = [
        "declaration_id", "state", "governor", "eo_number", "action_kind",
        "action_type", "event_description", "date_signed", "end_date",
        "weather_related", "source_scope", "document_format", "detail_url",
        "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for action in actions:
            writer.writerow({
                "declaration_id": action.stable_id, "state": "PA",
                "governor": action.governor, "eo_number": action.action_number,
                "action_kind": action.action_kind, "action_type": action.action_type,
                "event_description": action.description or action.title,
                "date_signed": action.date_issued or "", "end_date": action.end_date or "",
                "weather_related": action.weather_related, "source_scope": action.source_scope,
                "document_format": action.document_format, "detail_url": action.source_page_url,
                "archive_record_url": action.document_url,
            })


def write_relationships(rows: list[dict[str, str]], path: str) -> None:
    fields = ["source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_join(actions: list[PAAction], path: str) -> None:
    fields = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for action in actions:
            if action.action_kind != "emergency_proclamation" or not action.weather_related or not action.date_issued:
                continue
            if action.action_type in {"termination", "extension", "amendment"}:
                continue
            writer.writerow({
                "declaration_id": action.stable_id, "governor": action.governor,
                "eo_number": action.action_number,
                "event_description": action.description or action.title,
                "date_signed": action.date_issued, "archive_record_url": action.document_url,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Pennsylvania executive orders and emergency proclamations")
    parser.add_argument("--actions-out", default="pa_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="pa_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument("--skip-document-fetch", action="store_true")
    args = parser.parse_args()

    print("Pennsylvania scraper: collecting Office of Administration issuances...")
    oa_actions = collect_oa_actions()
    print(f"    Office of Administration: {len(oa_actions)} row(s)")
    print("Pennsylvania scraper: collecting PEMA emergency proclamations...")
    pema_actions = collect_pema_actions()
    print(f"    PEMA proclamation history: {len(pema_actions)} linked document(s)")
    actions = dedupe_actions([*oa_actions, *pema_actions])
    if not actions:
        raise SystemExit("ERROR: no Pennsylvania actions were collected")

    if not args.skip_document_fetch:
        print("Pennsylvania scraper: fetching linked documents...")
        low_yield = 0
        for index, action in enumerate(actions, start=1):
            action.document_text = fetch_document_text(action)
            enrich_from_document(action)
            if action.document_format == "pdf" and len(action.document_text) < LOW_YIELD_PDF_CHARS:
                low_yield += 1
            if index % 50 == 0:
                print(f"    fetched {index}/{len(actions)}")
        if low_yield:
            print(f"  WARNING: {low_yield} PDF(s) yielded fewer than {LOW_YIELD_PDF_CHARS} characters and need OCR review", file=sys.stderr)

    for action in actions:
        action.action_type = classify_action(action)
        action.weather_related = is_weather_related(action)
        if not action.governor:
            action.governor = governor_for_date(action.date_issued)
    relationships = dedupe_relationships(rel for action in actions for rel in extract_relationships(action))
    valid_ids = {action.stable_id for action in actions}
    relationships = [row for row in relationships if row["source_order_id"] in valid_ids and row["target_order_id"] in valid_ids]
    apply_end_dates(actions, relationships)
    write_actions(actions, args.actions_out)
    write_relationships(relationships, args.relationships_out)
    write_join(actions, args.join_out)
    join_count = sum(
        a.action_kind == "emergency_proclamation" and a.weather_related and bool(a.date_issued)
        and a.action_type not in {"termination", "extension", "amendment"}
        for a in actions
    )
    print(f"Done. {len(actions)} action(s): {len(oa_actions)} OA issuances, {len(pema_actions)} PEMA documents; {join_count} original weather declarations written to join file.")


if __name__ == "__main__":
    main()
