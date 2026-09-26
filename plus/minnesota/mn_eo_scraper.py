"""Collect Governor Walz's Minnesota executive orders.

Source: the Minnesota Legislative Reference Library's executive order
database, https://www.lrl.mn.gov/execorders/eoresults?gov=44 (gov=44 is Tim
Walz). It lists every order on one page as a table: official number, a link
to the signed PDF, the title, the date signed and the date filed.

Until Sep 2026 this scraper read the Governor's own site (mn.gov/governor),
which sits behind Radware's bot manager. From GitHub's runners every request
was intercepted, so the state was never refreshed. The Library is the state's
official archive of these orders and has no such check. Its titles are the
orders' own, and its dates are the dates signed.

Coverage: 2019-present (Walz). The same database covers earlier governors
(Dayton, Pawlenty, Ventura) under other gov= numbers, for a later backfill.
"""
from __future__ import annotations
import argparse, csv, re, time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STATE = "MN"; GOVERNOR = "Tim Walz"
LRL_URL = "https://www.lrl.mn.gov/execorders/eoresults?gov=44"
HEADERS = {"User-Agent": "DisasterDataIO-Plus/1.0 (+https://disasterdata.io/plus/)"}
RETRY_WAITS = (10, 30)
HAZARDS = {"drought": r"\bdrought\b", "fire": r"\bwildfires?\b", "flood": r"\bflood(?:ing)?\b",
           "tropical": r"\bhurricanes?\b|\btropical storm\b",
           "winter": r"\bwinter storm\b|\bblizzard\b|\bsnow(?:fall|melt)?\b",
           "severe_storm": r"\bsevere storms?\b|\bsevere weather\b|\btornado(?:es)?\b|\bthunderstorms?\b",
           "wind": r"\bhurricane.force winds?\b|\bdamaging winds?\b"}
# These official titles are generic. The appended phrases come directly from
# the corresponding order text / Governor press release and keep a
# regenerated join from losing reviewed weather declarations.
TITLE_ENRICH = {
    "19-30": "Declaring a Peacetime Emergency after rapid snowmelt flooding and Winter Storm Wesley",
    "20-108": "Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists after a powerful winter storm",
    "22-23": "Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "23-01": "Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "25-06": "Declaring a Peacetime Emergency and Providing Storm Recovery Assistance in Beltrami County after severe storms and hurricane-force winds",
}
SIGNED_DATE_ENRICH = {"25-15": "2025-12-28"}
NUMBER_PREFIX_RE = re.compile(r"^(?:emergency\s+)?executive\s+order\s+\d{2}-\d+[a-z]?\s*[:.-]?\s*", re.I)


@dataclass
class Action:
    eo_number: str; title: str; date_signed: str; url: str
    action_type: str = "other"; hazard: str = ""; related_order: str = ""


def blocked(text, url=""):
    low = (text[:3000] + url).lower()
    return "radware bot manager" in low or "validate.perfdrive.com" in low


def _date(value):
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def classify(action):
    """Set hazard, action_type and related_order from the order's title."""
    action.title = TITLE_ENRICH.get(action.eo_number, NUMBER_PREFIX_RE.sub("", action.title).strip())
    action.date_signed = SIGNED_DATE_ENRICH.get(action.eo_number, action.date_signed)
    low = action.title.lower()
    action.hazard = next((c for c, p in HAZARDS.items() if re.search(p, action.title, re.I)), "")
    rm = re.search(r"(?:amending|extending|rescinding).*?Executive Order\s+(\d{2}-\d+)", action.title, re.I)
    action.related_order = rm.group(1) if rm else ""
    if re.search(r"\bamending\b|\bextending\b|\brescinding\b", low):
        action.action_type = "amendment"
    elif "declaring a peacetime emergency" in low and action.hazard:
        action.action_type = "declaration"
    elif re.search(r"providing (?:for )?(?:emergency )?relief|motor carriers|assistance to (?:the state of|stranded motorists)|national guard assistance", low):
        action.action_type = "operational"
    return action


def parse_table(page):
    """Rows of the Library's results table, found by its column names so a
    reordered or added column does not break it."""
    soup = BeautifulSoup(page, "html.parser")
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        names = [" ".join(c.get_text(" ", strip=True).split()).lower() for c in header.find_all(["th", "td"])]
        if "official number" not in names or "title" not in names:
            continue
        col = {name: i for i, name in enumerate(names)}
        out, seen = [], set()
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(names):
                continue
            number = cells[col["official number"]].get_text(" ", strip=True)
            if not re.fullmatch(r"\d{2}-\d+[A-Za-z]?", number) or number in seen:
                continue
            seen.add(number)
            link = None
            if "file" in col:
                link = cells[col["file"]].find("a", href=True)
            link = link or tr.find("a", href=re.compile(r"\.pdf$", re.I))
            signed = cells[col["date signed"]].get_text(" ", strip=True) if "date signed" in col else ""
            title = " ".join(cells[col["title"]].get_text(" ", strip=True).split())
            out.append(Action(number, title, _date(signed),
                              urljoin(LRL_URL, link["href"]) if link else LRL_URL))
        if out:
            return out
    raise ValueError("Minnesota Legislative Reference Library page had no executive order table")


def fetch(session, url):
    last = None
    for wait in (0,) + RETRY_WAITS:
        if wait:
            time.sleep(wait)
        try:
            r = session.get(url, headers=HEADERS, timeout=60); r.raise_for_status()
        except requests.RequestException as exc:
            last = exc; continue
        if blocked(r.text, r.url):
            raise ValueError(f"{url} returned an anti-bot page; refusing to emit an empty data set")
        return r
    raise last


def scrape(session=None):
    session = session or requests.Session()
    rows = [classify(a) for a in parse_table(fetch(session, LRL_URL).text)]
    return sorted(rows, key=lambda x: (x.date_signed, x.eo_number))


def write_outputs(rows, actions_out, relationships_out, join_out):
    for p in (actions_out, relationships_out, join_out): p.parent.mkdir(parents=True, exist_ok=True)
    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id", "eo_number", "title", "date_signed", "action_type", "related_order", "hazard_category", "archive_record_url"])
        for x in rows: w.writerow([f"MN-EO-{x.eo_number}", x.eo_number, x.title, x.date_signed, x.action_type, x.related_order, x.hazard, x.url])
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["source_declaration_id", "relationship_type", "target_declaration_id"])
        for x in rows:
            if x.related_order: w.writerow([f"MN-EO-{x.eo_number}", x.action_type, f"MN-EO-{x.related_order}"])
    joins = [x for x in rows if x.action_type == "declaration" and x.date_signed]
    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        for x in joins: w.writerow([f"MN-EO-{x.eo_number}", GOVERNOR, x.eo_number, x.title, x.date_signed, x.url])
    return len(joins)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--actions-out", required=True); p.add_argument("--relationships-out", required=True); p.add_argument("--join-out", required=True); a = p.parse_args()
    try: rows = scrape()
    except (requests.RequestException, ValueError) as exc: raise SystemExit(f"Minnesota archive scrape failed: {exc}")
    n = write_outputs(rows, Path(a.actions_out), Path(a.relationships_out), Path(a.join_out))
    print(f"Minnesota: {len(rows)} executive orders read from the Legislative Reference Library, {n} weather declarations")


if __name__ == "__main__": main()
