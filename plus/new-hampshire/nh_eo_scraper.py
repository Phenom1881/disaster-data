"""Collect New Hampshire orders from the official Secretary of State registry.

The Governor's current website no longer exposes the historical registry.  The
Secretary of State registry is the official successor and includes Governor
Ayotte plus archived orders from prior administrations back to 1990.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup, Tag


REGISTRY_URL = "https://www.sos.nh.gov/executive-orders"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; +https://disasterdata.io/plus/)", "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")

HAZARD_RE = re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|rain storm|hurricanes?|tropical storms?|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice storm|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|wind storms?|high winds?|damaging winds?|wind gusts?)\b", re.I)
DECLARATION_RE = re.compile(
    r"\b(?:declar(?:e|es|ed|ing) (?:a |the )?(?:limited )?state of emergency|"
    r"declaration of (?:a |the )?(?:limited )?state of emergency)\b", re.I,
)
MODIFIER_RE = re.compile(r"\b(amend(?:ment|s|ed|ing)?|extend(?:s|ed|ing)?|extension|renew(?:al|s|ed|ing)?|continuation|continue[sd]?|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|revoke[sd]?|terminat(?:e|es|ed|ing|ion)|state of emergency over)\b", re.I)
REF_RE = re.compile(r"(?:executive|emergency) order(?:\s+(?:no\.?|number|#))?\s*(\d{4}-\d+|#?\d+)", re.I)


@dataclass
class Action:
    number: str
    title: str
    governor: str
    document_url: str
    date_signed: Optional[str] = None
    document_text: str = ""
    action_type: str = "administrative"
    action_kind: str = "executive_order"
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        token = self.number.replace(" #", "-EO-").replace("#", "EO-").replace(" ", "-").upper()
        return f"NH-{token}"


RETRY_WAITS = (10, 30)   # seconds before the 2nd and 3rd tries of the registry page


def fetch(url: str, retries: tuple[int, ...] = ()) -> Optional[requests.Response]:
    """Fetch url, trying the bare sos.nh.gov host too. The registry page itself
    is fetched with retries: from GitHub's runners it loads on some weeks and
    times out on others, and one refused request should not cost a week."""
    candidates = [url]
    if "www.sos.nh.gov" in url: candidates.append(url.replace("www.sos.nh.gov", "sos.nh.gov"))
    last = None
    for wait in (0,) + tuple(retries):
        if wait: time.sleep(wait)
        for candidate in candidates:
            try:
                response = requests.get(candidate, headers=HEADERS, timeout=TIMEOUT)
                response.raise_for_status(); return response
            except requests.RequestException as exc: last = exc
    print(f"  WARNING: failed to fetch {url}: {last}", file=sys.stderr); return None


def governor_from_heading(text: str) -> str:
    for name in ("Kelly A. Ayotte", "Christopher Sununu", "Margaret Wood Hassan", "John H. Lynch", "Craig R. Benson", "Jeanne Shaheen", "Stephen Merrill", "Judd Gregg"):
        if name in text: return name
    return ""


def parse_registry(html: str) -> list[Action]:
    soup = BeautifulSoup(html, "html.parser")
    actions = []
    for row in soup.select("table tr"):
        cells = row.select("td")
        link = row.select_one("td a[href]")
        if not link or len(cells) < 2: continue
        label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        match = re.search(r"((?:19|20)\d{2}-\d+[A-Z]?)(?:\s*#\s*(\d+))?", label, re.I)
        if not match: continue
        number = match.group(1) + (f" #{int(match.group(2)):02d}" if match.group(2) else "")
        title = re.sub(r"\s+", " ", cells[-1].get_text(" ", strip=True))
        heading = row.find_previous(["h2", "h3", "button", "summary"])
        governor = governor_from_heading(heading.get_text(" ", strip=True) if isinstance(heading, Tag) else "")
        actions.append(Action(number, title, governor, urljoin(REGISTRY_URL, link.get("href", ""))))
    return list({a.stable_id: a for a in actions}.values())


def normalize_date(raw: str) -> Optional[str]:
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", re.sub(r"\s+", " ", raw.strip()), flags=re.I)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return None


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# The signature clause of a New Hampshire order: "Given under my hand and seal
# ... this 13th day of March, in the year of Our Lord, two thousand and twenty".
# The year is usually in words, sometimes in digits, sometimes left out.
SIGNING_RE = re.compile(
    r"\bthis\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+(" + _MONTHS + r")\b[\s,]*"
    r"(?:(?:in\s+)?(?:the\s+)?year\s+of\s+(?:our\s+lord)?[\s,]*)?"
    r"(\d{4}|(?:nineteen\s+hundred|two\s+thousand)(?:[\s,-]+(?:and|[a-z]+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b)*)?",
    re.I,
)
PLAIN_DATE_RE = re.compile(r"\b((?:" + _MONTHS + r")\s+\d{1,2}(?:st|nd|rd|th)?,\s+(\d{4}))\b", re.I)
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}


def words_to_year(text: str) -> Optional[int]:
    """'two thousand and fifteen' -> 2015, 'two thousand twenty-one' -> 2021,
    'nineteen hundred and ninety-nine' -> 1999. None if it is not a year."""
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w != "and"]
    if words[:2] == ["two", "thousand"]:
        year, rest = 2000, words[2:]
    elif words[:2] == ["nineteen", "hundred"]:
        year, rest = 1900, words[2:]
    else:
        return None
    if rest and rest[0] in _TENS:
        year += _TENS[rest[0]]
        if len(rest) > 1 and 0 < _UNITS.get(rest[1], 0) < 10:
            year += _UNITS[rest[1]]
    elif rest and rest[0] in _UNITS:
        year += _UNITS[rest[0]]
    return year


def date_in_text(text: str, fallback_year: Optional[int] = None) -> Optional[str]:
    """The date an order was signed.

    The signature clause comes first, and the last one in the text wins, since
    it sits at the end of the order. Without one, a plain "Month D, YYYY" date
    from the order's own year (the year in its number) is used, then any plain
    date. Taking the first plain date in the text, as this used to, picked up
    the date of the emergency an extension extends (every 2020-2021 COVID
    extension came out as 2020-03-13) or of an old order being rescinded."""
    # PDF text breaks words across lines ("twen-\nty"); join them first.
    text = re.sub(r"(\w)-[ \t]*\r?\n[ \t]*(\w)", r"\1\2", text or "")

    def year_of(year_text):
        year = None
        if year_text:
            year = int(year_text) if year_text.isdigit() else words_to_year(year_text)
        # An order is signed in (or within a year of) the year in its number;
        # a year further off is a misread, so the number's year is used.
        if fallback_year and (not year or abs(year - fallback_year) > 1):
            year = fallback_year
        return year

    # "this 13th day of March, ...". The one in the "Given under my hand"
    # signature line is preferred; otherwise the last one, since the
    # signature sits at the end of the order. (A filing stamp after the
    # signature also says "this ... day of", which is why "hand" is checked.)
    signed = by_hand = None
    for match in SIGNING_RE.finditer(text):
        day, month, year_text = match.groups()
        year = year_of(year_text)
        if year:
            found = normalize_date(f"{month} {day}, {year}")
            signed = found or signed
            sentence = text[max(text.rfind(".", 0, match.start()) + 1, match.start() - 400):match.start()]
            if found and by_hand is None and re.search(r"\bhand\b", sentence, re.I):
                by_hand = found
    if by_hand or signed:
        return by_hand or signed
    if fallback_year:
        # No "this ... day of" clause: a bare "13th day of March" in the order's year.
        for match in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+(" + _MONTHS + r")\b", text, re.I):
            signed = normalize_date(f"{match.group(2)} {match.group(1)}, {fallback_year}") or signed
        if signed:
            return signed
    plain = [(m.group(1), int(m.group(2))) for m in PLAIN_DATE_RE.finditer(text)]
    for raw, year in plain:
        if fallback_year and year == fallback_year:
            return normalize_date(raw)
    return normalize_date(plain[0][0]) if plain else None


def pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf: return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"  WARNING: PDF extraction failed: {exc}", file=sys.stderr); return ""


def classify(action: Action) -> None:
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "repeal", "revoke", "terminat")) or "over" in word: action.action_type = "termination"
        elif word.startswith("amend"): action.action_type = "amendment"
        else: action.action_type = "extension"
    elif DECLARATION_RE.search(action.title):
        action.action_type = "declaration"; action.action_kind = "emergency_declaration"
    evidence = action.title
    if action.action_type == "declaration" and not HAZARD_RE.search(evidence): evidence = action.document_text
    action.weather_related = action.action_type in {"declaration", "amendment", "extension", "termination"} and bool(HAZARD_RE.search(evidence))


def collect() -> list[Action]:
    page = fetch(REGISTRY_URL, retries=RETRY_WAITS)
    if page is None: return []
    actions = parse_registry(page.text)
    for action in actions:
        # Exact signing dates and generic-declaration hazards come from the order itself.
        if DECLARATION_RE.search(action.title) or MODIFIER_RE.search(action.title):
            document = fetch(action.document_url)
            if document is not None:
                action.document_text = pdf_text(document.content)
                action.date_signed = date_in_text(action.document_text, int(action.number[:4]))
        classify(action)
    return sorted(actions, key=lambda a: (a.date_signed or "", a.number), reverse=True)


def relationships(action: Action) -> list[dict[str, str]]:
    if action.action_type not in {"amendment", "extension", "termination"}: return []
    relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[action.action_type]
    rows = []
    for match in REF_RE.finditer(f"{action.title}\n{action.document_text[:6000]}"):
        raw = match.group(1).lstrip("#")
        if "-" not in raw and action.number.startswith("2020-04 #"): target = f"NH-2020-04-EO-{int(raw):02d}"
        else: target = f"NH-{raw.upper()}"
        if target != action.stable_id:
            rows.append({"source_order_id": action.stable_id, "target_order_id": target, "relationship_type": relation, "relationship_text": match.group(0), "relationship_source": "title_or_document_text", "confidence": "high"})
    return list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for r in rows}.values())


def action_row(a: Action) -> dict[str, str]:
    return {"declaration_id": a.stable_id, "state": "NH", "governor": a.governor, "eo_number": a.number, "action_kind": a.action_kind, "action_type": a.action_type, "event_description": a.title, "date_signed": a.date_signed or "", "end_date": "", "weather_related": "true" if a.weather_related else "false", "source_scope": "nh_secretary_of_state_executive_order_registry", "document_format": "pdf", "detail_url": a.document_url, "archive_record_url": REGISTRY_URL}


def write(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    actions = collect(); rows = [action_row(a) for a in actions]
    write(args.actions_out, ACTION_FIELDS, rows)
    rels = list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for a in actions for r in relationships(a)}.values()); write(args.relationships_out, REL_FIELDS, rels)
    joins = [{field: action_row(a)[field] for field in JOIN_FIELDS} for a in actions if a.action_type == "declaration" and a.weather_related and a.date_signed]; write(args.join_out, JOIN_FIELDS, joins)
    print(f"New Hampshire: {len(actions)} actions, {len(rels)} relationships, {len(joins)} weather declarations")


if __name__ == "__main__": main()
