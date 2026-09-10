"""Collect Oregon executive orders from the Governor's official SharePoint list."""
from __future__ import annotations

import argparse
import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests

STATE = "OR"
ARCHIVE = "https://www.oregon.gov/gov/Pages/executive-orders.aspx"
API = "https://www.oregon.gov/gov/_api/web/lists/GetByTitle(%27Executive%20Orders%27)/items"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)", "Accept": "application/json;odata=verbose"}
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
HAZARD_RE = re.compile(r"\b(?:drought|wildfires?|wildland fires?|fires?|firefighting|conflagration|flood(?:ing)?|heavy rain|rain storms?|hurricanes?|tropical storms?|winter|snow|ice|blizzard|severe storms?|(?:severe|extreme) weather|atmospheric river|high winds?|windstorms?|tornado(?:es)?)\b", re.I)
DECLARATION_RE = re.compile(r"\b(?:determination|declaration|proclamation) of (?:a )?state of (?:drought |winter )?emergency\b|\binvocation of (?:the )?emergency conflagration act\b", re.I)
MODIFIER_RE = re.compile(r"\b(?:amend(?:s|ed|ing|ment)|extend(?:s|ed|ing)|extension|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|replacing)\b", re.I)
DATE_RE = re.compile(r"(?:signed|done|dated)?\s*(?:at[^,]{0,80},?\s*)?(?:this\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+day of\s+([A-Za-z]+),?\s+(20\d{2})", re.I)
MONTHS = {name.lower(): i for i, name in enumerate(("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if name}


@dataclass
class Action:
    year: int
    number: str
    description: str
    pdf_url: str
    created: str = ""
    text: str = ""
    signed: str = ""

    @property
    def eo_number(self) -> str:
        return f"{self.year % 100:02d}-{int(self.number):02d}"

    @property
    def stable_id(self) -> str:
        suffix = "-AMENDED" if "amended" in self.pdf_url.lower() or self.description.lower().startswith("(amended)") else ""
        return f"OR-EO-{self.eo_number}{suffix}"


def pdf_text_and_date(url: str, session: requests.Session | None = None) -> tuple[str, str]:
    session = session or requests.Session()
    response = session.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
    response.raise_for_status()
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        text = " ".join((page.extract_text() or "") for page in pdf.pages)
    text = re.sub(r"\s+", " ", text)
    match = DATE_RE.search(text)
    signed = ""
    if match and match.group(2).lower() in MONTHS:
        try:
            signed = date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))).isoformat()
        except ValueError:
            pass
    return text, signed


def collect(session: requests.Session | None = None) -> list[Action]:
    session = session or requests.Session()
    params = {"$top": "5000", "$expand": "File", "$select": "Title,Document_x0020_Description,Year,Number,Order0,Created,File/ServerRelativeUrl,File/Name"}
    response = session.get(API, params=params, headers=HEADERS, timeout=60)
    response.raise_for_status()
    actions = []
    for item in response.json()["d"]["results"]:
        file_data = item.get("File") or {}
        relative = file_data.get("ServerRelativeUrl", "")
        if not relative:
            continue
        # The SharePoint Year/Number columns contain a handful of cataloging
        # errors (for example EO 20-50 was once numbered 59 in the list).
        # The official PDF filename and displayed EO title agree, so prefer
        # the filename's order number and fall back to the list fields.
        filename_match = re.search(r"(?i)(?:^|/)eo[_-]?(\d{2})[-_]?(\d{1,2})(?:\D|$)", relative)
        try:
            if filename_match:
                year, number = 2000 + int(filename_match.group(1)), str(int(filename_match.group(2)))
            else:
                year, number = int(item.get("Year")), str(int(item.get("Number")))
        except (TypeError, ValueError):
            continue
        if year < 2000:
            continue
        actions.append(Action(year, number, re.sub(r"\s+", " ", item.get("Document_x0020_Description") or item.get("Title") or "").strip(), urljoin("https://www.oregon.gov", relative), item.get("Created", "")))

    def enrich(action: Action) -> Action:
        if DECLARATION_RE.search(action.description) or MODIFIER_RE.search(action.description):
            try:
                action.text, action.signed = pdf_text_and_date(action.pdf_url, session)
            except Exception:
                pass
        return action

    with ThreadPoolExecutor(max_workers=10) as pool:
        actions = list(pool.map(enrich, actions))
    unique = {}
    for action in actions:
        previous = unique.get(action.stable_id)
        if not previous or len(action.description) > len(previous.description):
            unique[action.stable_id] = action
    return sorted(unique.values(), key=lambda x: (x.signed, x.year, int(x.number)), reverse=True)


def governor(action: Action) -> str:
    marker = action.signed or f"{action.year:04d}-12-31"
    if marker >= "2023-01-09": return "Tina Kotek"
    if marker >= "2015-02-18": return "Kate Brown"
    if marker >= "2011-01-10": return "John Kitzhaber"
    return "Ted Kulongoski"


def classify(action: Action) -> str:
    match = MODIFIER_RE.search(action.description)
    if match:
        word = match.group(0).lower()
        return "termination" if word.startswith(("rescind", "terminat", "repeal")) else "extension" if word.startswith("extend") else "amendment"
    return "declaration" if DECLARATION_RE.search(action.description) else "administrative"


def write_csv(path, fields, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def write_outputs(actions, actions_out, relationships_out, join_out) -> None:
    rows, relationships, joins = [], [], []
    known = {a.eo_number: a.stable_id for a in actions if "AMENDED" not in a.stable_id}
    for action in actions:
        kind = classify(action)
        weather = bool(HAZARD_RE.search(action.description))
        row = {"declaration_id": action.stable_id, "state": STATE, "governor": governor(action), "eo_number": action.eo_number, "action_kind": "emergency_declaration" if kind != "administrative" else "executive_order", "action_type": kind, "event_description": action.description, "date_signed": action.signed, "end_date": "", "weather_related": str(kind == "declaration" and weather).lower(), "source_scope": "oregon_governor_executive_order_list", "document_format": "pdf", "detail_url": action.pdf_url, "archive_record_url": action.pdf_url}
        rows.append(row)
        if kind in {"amendment", "extension", "termination"}:
            relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[kind]
            for target in re.findall(r"(?:Executive Order|EO)(?: No\.?)?\s*(\d{2}-\d{2})", f"{action.description} {action.text[:1200]}", re.I):
                if target != action.eo_number and target in known:
                    relationships.append({"source_order_id": action.stable_id, "target_order_id": known[target], "relationship_type": relation, "relationship_text": target, "relationship_source": action.pdf_url, "confidence": "high"})
        if kind == "declaration" and weather:
            joins.append({field: row[field] for field in JOIN_FIELDS})
    write_csv(actions_out, ACTION_FIELDS, rows); write_csv(relationships_out, REL_FIELDS, relationships); write_csv(join_out, JOIN_FIELDS, joins)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    write_outputs(collect(), args.actions_out, args.relationships_out, args.join_out)


if __name__ == "__main__": main()
