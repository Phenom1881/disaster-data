"""Scrape Michigan Governor executive orders for weather declarations."""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STATE = "MI"
GOVERNOR = "Gretchen Whitmer"
ARCHIVE_URL = "https://www.michigan.gov/whitmer/news/state-orders-and-directives"
SEARCH_URL = "https://www.michigan.gov/whitmer/sxa/search/results/"
SEARCH_PARAMS = {
    "v": "{66B61C4F-96A9-41F3-A608-4CBBC5A3AC74}",
    "s": "{C9013E3C-454C-49EA-B55C-DF2B4CC1F0A6}|{62E9FB6A-7717-4EF1-832C-E5ECBB9BB2D9}",
    "p": "500",
    "itemid": "{43F87B23-1E6B-407D-868A-F04B024FDDBA}",
    "o": "Article Date,Descending",
}
HEADERS = {"User-Agent": "DisasterDataPlus-Adapter/1.0", "Referer": ARCHIVE_URL, "X-Requested-With": "XMLHttpRequest"}
HAZARDS = {
    "drought": r"\bdrought\b", "fire": r"\bwildfires?\b|\bforest fires?\b",
    "flood": r"\bflood(?:ing|waters?)?\b|\bdam failure\b|\bice jam\b",
    "tropical": r"\bhurricanes?\b|\btropical storms?\b",
    "winter": r"\bblizzards?\b|\bwinter (?:storms?|weather)\b|\bsnow(?:fall|melt)?\b|\bice(?: storms?| accumulation)?\b|\bfreezing rain\b|\bwind chills?\b|\bextreme(?:ly)? cold\b",
    "severe_storm": r"\bsevere (?:weather|storms?)\b|\bthunderstorms?\b|\btornado(?:es)?\b|\bderecho\b",
    "wind": r"\bhigh winds?\b|\bdamaging winds?\b|\bwindstorms?\b",
}


@dataclass
class Action:
    eo_number: str
    title: str
    date_signed: str
    url: str
    description: str = ""
    action_type: str = "other"
    hazard: str = ""
    related_order: str = ""


def _date(text: str) -> str:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse_search_results(payload: dict) -> list[Action]:
    found: dict[str, Action] = {}
    for row in payload.get("Results", []):
        soup = BeautifulSoup(row.get("Html", ""), "html.parser")
        text = soup.get_text(" ", strip=True)
        m = re.search(r"Executive Order(?: No\.?|\s*)\s*(20\d{2}[-–]\d+)", text, re.I)
        dm = re.search(r"([A-Z][a-z]+ \d{1,2}, 20\d{2})\s*$", text)
        url = urljoin("https://www.michigan.gov", row.get("Url", ""))
        if not m or "/state-orders-and-directives/" not in url or "directive" in text.lower():
            continue
        year, number = m.group(1).replace("–", "-").split("-", 1)
        eo = f"{year}-{int(number)}"
        item = Action(eo, re.sub(r"\s+", " ", text[: dm.start()] if dm else text).strip(), _date(dm.group(1)) if dm else "", url)
        # Results are newest-first. Retain the first copy when a migrated item is duplicated.
        found.setdefault(eo, item)
    return sorted(found.values(), key=lambda x: (x.date_signed, x.eo_number))


def parse_detail(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#pagebody") or soup.select_one("main") or soup
    return re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()


def classify(action: Action, body: str) -> Action:
    title = re.sub(r"\s+-\s+RESCINDED\s*$", "", action.title, flags=re.I)
    lead = body[:2400]
    action.description = title
    for sentence in re.split(r"(?<=[.!?])\s+", lead):
        if any(re.search(pat, sentence, re.I) for pat in HAZARDS.values()):
            action.description = f"{title} — {sentence[:500]}"
            break
    action.hazard = next((cat for cat, pat in HAZARDS.items() if re.search(pat, action.description, re.I)), "")
    ref = re.search(r"(?:Executive Order|EO)\s+(20\d{2}[-–]\d+)", lead, re.I)
    if ref:
        ry, rn = ref.group(1).replace("–", "-").split("-", 1)
        normalized_ref = f"{ry}-{int(rn)}"
        action.related_order = normalized_ref if normalized_ref != action.eo_number else ""
    low = (title + " " + lead).lower()
    if re.search(r"\btermination\b|\brescission of executive order\b|\brescind(?:s|ing)? executive order\b", low):
        action.action_type = "termination"
    elif re.search(r"\bamended declaration\b|\bamending\b|\bexpanded declaration\b|\bextension of\b", low):
        action.action_type = "amendment"
    elif action.related_order and re.search(r"\badditional\b|\bexpand(?:s|ed|ing)?\b|\bextend(?:s|ed|ing)?\b|\bthis same\b|\bthese same\b|\bon .* I (?:issued|declared)\b", lead, re.I):
        action.action_type = "amendment"
    elif re.search(r"declaration of (?:a )?state(?:s)? of emergency", title, re.I):
        action.action_type = "declaration"
    elif "energy emergency" in title.lower() or re.search(r"suspension of rules|hours.of.service|motor (?:drivers|carriers)", title, re.I):
        action.action_type = "operational"
    return action


def scrape(session: requests.Session | None = None) -> list[Action]:
    session = session or requests.Session()
    response = session.get(SEARCH_URL, params=SEARCH_PARAMS, headers=HEADERS, timeout=45)
    response.raise_for_status()
    actions = parse_search_results(response.json())
    for action in actions:
        if re.search(r"emergency|disaster", action.title, re.I):
            detail = session.get(action.url, headers=HEADERS, timeout=30)
            detail.raise_for_status()
            classify(action, parse_detail(detail.text))
    return actions


def write_outputs(actions: list[Action], actions_out: Path, relationships_out: Path, join_out: Path) -> None:
    for p in (actions_out, relationships_out, join_out): p.parent.mkdir(parents=True, exist_ok=True)
    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id","eo_number","title","date_signed","action_type","related_order","hazard_category","archive_record_url"])
        for a in actions: w.writerow([f"MI-EO-{a.eo_number}",a.eo_number,a.title,a.date_signed,a.action_type,a.related_order,a.hazard,a.url])
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["source_declaration_id","relationship_type","target_declaration_id"])
        for a in actions:
            if a.related_order: w.writerow([f"MI-EO-{a.eo_number}",a.action_type,f"MI-EO-{a.related_order}"])
    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id","governor","eo_number","event_description","date_signed","archive_record_url"])
        for a in actions:
            if a.action_type == "declaration" and a.hazard: w.writerow([f"MI-EO-{a.eo_number}",GOVERNOR,a.eo_number,a.description,a.date_signed,a.url])


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args()
    try: rows=scrape()
    except (requests.RequestException, ValueError) as exc: raise SystemExit(f"Michigan archive scrape failed: {exc}")
    write_outputs(rows,Path(a.actions_out),Path(a.relationships_out),Path(a.join_out)); print(f"Michigan: {len(rows)} executive orders processed")


if __name__ == "__main__": main()
