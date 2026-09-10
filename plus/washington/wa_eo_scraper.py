"""Collect Washington proclamations from the Governor's official archive."""
from __future__ import annotations

import argparse
import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

STATE = "WA"
ARCHIVE = "https://governor.wa.gov/office-governor/office/official-actions/proclamations"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
HAZARD_RE = re.compile(r"\b(?:drought|wildfires?|fires?|flood(?:ing)?|heavy rain|rain storms?|hurricanes?|tropical storms?|winter storms?|winter weather|snow|ice|blizzard|severe storms?|severe weather|atmospheric river|high winds?|windstorms?|bomb cyclone|tornado(?:es)?)\b", re.I)
MODIFIER_RE = re.compile(r"\b(?:amending|amended|amendment|extending|extended|extension|terminating|termination|rescinding|rescission)\b", re.I)
DECLARATION_TEXT_RE = re.compile(r"proclaim(?:ed|ing)? (?:that )?a State of Emergency|State of Emergency exists", re.I)


@dataclass
class Action:
    number: str
    signed: str
    title: str
    url: str
    status: str = ""
    text: str = ""

    @property
    def stable_id(self) -> str:
        return f"WA-PROC-{self.number}"


def extract_pdf(url: str, session: requests.Session | None = None) -> str:
    session = session or requests.Session()
    response = session.get(url, headers=HEADERS, timeout=60); response.raise_for_status()
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        return re.sub(r"\s+", " ", " ".join((page.extract_text() or "") for page in pdf.pages))


def collect(session: requests.Session | None = None) -> list[Action]:
    session = session or requests.Session(); actions = []; seen_pages = set()
    for page in range(100):
        response = session.get(ARCHIVE, params={"page": page}, headers=HEADERS, timeout=60); response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser"); batch = []
        for tr in soup.select("table tbody tr"):
            cells = tr.find_all("td"); link = tr.find("a", href=True)
            if len(cells) < 4 or not link: continue
            number = cells[0].get_text(" ", strip=True); raw_date = cells[1].get_text(" ", strip=True)
            try: signed = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
            except ValueError: signed = ""
            batch.append(Action(number, signed, cells[2].get_text(" ", strip=True), urljoin(ARCHIVE, link["href"]), cells[3].get_text(" ", strip=True)))
        signature = tuple((a.number, a.url) for a in batch)
        if not batch or signature in seen_pages: break
        seen_pages.add(signature); actions.extend(batch)
    unique = {}
    for action in actions:
        previous = unique.get(action.number)
        if not previous or "spanish" in previous.title.lower(): unique[action.number] = action

    def enrich(action: Action) -> Action:
        if re.search(r"state of emergency|emergency proclamation|storm|weather|wildfire|fire|flood|drought|wind|snow|ice|atmospheric", action.title, re.I):
            try: action.text = extract_pdf(action.url, session)
            except Exception: pass
        return action
    with ThreadPoolExecutor(max_workers=10) as pool:
        result = list(pool.map(enrich, unique.values()))
    return sorted(result, key=lambda x: (x.signed, x.number), reverse=True)


def governor(action: Action) -> str:
    return "Bob Ferguson" if action.signed >= "2025-01-15" else "Jay Inslee"


def classify(action: Action) -> str:
    evidence = f"{action.title} {action.text[:700]}"
    match = MODIFIER_RE.search(evidence)
    if "." in action.number or match:
        word = match.group(0).lower() if match else "amended"
        return "termination" if word.startswith(("terminat", "rescind")) else "extension" if word.startswith("extend") else "amendment"
    if DECLARATION_TEXT_RE.search(action.text) or re.search(r"\bstate of emergency\b|\bemergency proclamation\b", action.title, re.I):
        return "declaration"
    return "administrative"


def description(action: Action) -> str:
    if HAZARD_RE.search(action.title) or not action.text:
        return action.title
    clauses = re.findall(r"WHEREAS,\s*(.{1,700}?)(?=;\s*and\s+WHEREAS|\s+WHEREAS,|NOW, THEREFORE)", action.text, re.I)
    match = next((clause for clause in clauses if HAZARD_RE.search(clause)), "")
    if not match:
        nearby = re.search(r"([^.;]{0,240}\b(?:wildfires?|fires?|flood(?:ing)?|storms?|winter|snow|ice|drought|winds?)\b[^.;]{0,360})", action.text, re.I)
        match = nearby.group(1) if nearby else ""
    return f"{action.title} — {match.strip()}" if match else action.title


def write_csv(path, fields, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def write_outputs(actions, actions_out, relationships_out, join_out) -> None:
    rows, relationships, joins = [], [], []
    known = {a.number: a.stable_id for a in actions}
    for action in actions:
        kind = classify(action); desc = description(action); weather = bool(HAZARD_RE.search(f"{desc} {action.text[:2200]}"))
        row = {"declaration_id": action.stable_id, "state": STATE, "governor": governor(action), "eo_number": action.number, "action_kind": "emergency_proclamation" if kind != "administrative" else "proclamation", "action_type": kind, "event_description": desc, "date_signed": action.signed, "end_date": "", "weather_related": str(kind == "declaration" and weather).lower(), "source_scope": "washington_governor_proclamation_archive", "document_format": "pdf", "detail_url": action.url, "archive_record_url": action.url}
        rows.append(row)
        if kind in {"amendment", "extension", "termination"}:
            relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[kind]
            targets = set(re.findall(r"(?:Proclamation|proclamation)\s+(\d{2}-\d+(?:\.\d+)?)", action.text[:1800]))
            if "." in action.number: targets.add(action.number.split(".")[0])
            for target in sorted(targets):
                if target != action.number and target in known: relationships.append({"source_order_id": action.stable_id, "target_order_id": known[target], "relationship_type": relation, "relationship_text": target, "relationship_source": action.url, "confidence": "high"})
        if kind == "declaration" and weather: joins.append({field: row[field] for field in JOIN_FIELDS})
    write_csv(actions_out, ACTION_FIELDS, rows); write_csv(relationships_out, REL_FIELDS, relationships); write_csv(join_out, JOIN_FIELDS, joins)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    write_outputs(collect(), args.actions_out, args.relationships_out, args.join_out)


if __name__ == "__main__": main()
