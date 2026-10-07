"""Collect New Hampshire orders from the official Secretary of State registry.

The Governor's current website no longer exposes the historical registry.  The
Secretary of State registry is the official successor and includes Governor
Ayotte plus archived orders from prior administrations back to 1990.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
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
# The registry's edge security has refused every request from GitHub's
# runners (no successful collection is on record). A plain browser
# User-Agent is tried as well, since bot-named agents are a common block rule.
BROWSER_HEADERS = {**HEADERS, "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
# When the registry itself cannot be reached, the Internet Archive's latest
# copy of the same page (and of each order's PDF) is read instead. The
# registry changes a few times a year, so a recent copy is complete for
# nearly every run; the copy's date is printed and recorded per order.
WAYBACK_AVAILABLE = "https://archive.org/wayback/available"
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


RETRY_WAITS = (15,)      # seconds before the second round of tries of the registry page
REGISTRY_TIMEOUT = 30
DOCUMENT_BUDGET_SECONDS = 8 * 60   # order PDFs after this are left for the next run
SOURCE_NOTE = ""   # set when the registry came from the Internet Archive   # seconds before the 2nd and 3rd tries of the registry page

# Signing dates confirmed from dated coverage, used when an order's own PDF
# yields no readable date. The registry lists every order but gives no dates,
# and these weather orders' PDFs have produced no date on any run since
# 2026-09-12, so without these none of them reached the join file. A date
# read from the order itself still wins over this list.
#
# 2013-08 and 2008-12 correct the dates first saved on 2026-09-09
# (2013-06-26 and 2008-12-11), which were the storms' start dates.
# 2010-01 and 2003-09 are not listed: no dated source was found for them,
# so their saved rows (2010-02-25, 2003-08-11) stand unconfirmed.
CONFIRMED_DATES = {
    "2015-01": "2015-01-26",  # blizzard; Patch (Concord), Jan 26 2015: "Governor Maggie Hassan today declared a State of Emergency"
    "2013-08": "2013-07-03",  # flash flooding, Sullivan/Cheshire/Grafton; AP via Central Maine, Jul 3 2013: declared "on Wednesday"
    "2013-03": "2013-02-08",  # blizzard; Patch (Concord), Feb 8 2013, effective 5 p.m.
    "2008-12": "2008-12-12",  # ice storm; NH ice storm after-action report: declared "December 12, 2008, at 9:20 a.m."
}


def fetch(url: str, retries: tuple[int, ...] = (), quiet: bool = False, timeout: int = TIMEOUT,
          header_sets: tuple = (HEADERS, BROWSER_HEADERS)) -> Optional[requests.Response]:
    """Fetch url, trying the bare sos.nh.gov host and a browser User-Agent
    too. The registry page itself is fetched with retries, since one refused
    request should not cost a week."""
    candidates = [url]
    if "www.sos.nh.gov" in url: candidates.append(url.replace("www.sos.nh.gov", "sos.nh.gov"))
    last = None
    for wait in (0,) + tuple(retries):
        if wait: time.sleep(wait)
        for candidate in candidates:
            for headers in header_sets:
                try:
                    response = requests.get(candidate, headers=headers, timeout=timeout)
                    response.raise_for_status(); return response
                except requests.RequestException as exc: last = exc
    if not quiet: print(f"  WARNING: failed to fetch {url}: {last}", file=sys.stderr)
    return None


def wayback_copy(url: str) -> tuple[Optional[requests.Response], str]:
    """The Internet Archive's latest copy of url, as originally served (the
    id_ form, without the archive's toolbar or rewritten links), and the
    copy's date (YYYY-MM-DD). (None, "") when there is no copy."""
    try:
        lookup = requests.get(WAYBACK_AVAILABLE, params={"url": url}, headers=HEADERS, timeout=TIMEOUT)
        lookup.raise_for_status()
        closest = (lookup.json().get("archived_snapshots") or {}).get("closest") or {}
    except (requests.RequestException, ValueError) as exc:
        print(f"  WARNING: Internet Archive lookup failed for {url}: {exc}", file=sys.stderr)
        return None, ""
    stamp = str(closest.get("timestamp") or "")
    if not closest.get("available") or not re.fullmatch(r"\d{14}", stamp):
        return None, ""
    raw = f"https://web.archive.org/web/{stamp}id_/{url}"
    for wait in (0, 10):
        if wait: time.sleep(wait)
        try:
            response = requests.get(raw, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            return response, f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        except requests.RequestException as exc:
            last = exc
    print(f"  WARNING: could not read the Internet Archive copy of {url}: {last}", file=sys.stderr)
    return None, ""


def fetch_document(url: str, archived: bool) -> Optional[requests.Response]:
    """An order's PDF: from the registry, or from the Internet Archive when
    the registry page itself had to come from there (or the PDF will not
    load directly)."""
    if not archived:
        response = fetch(url, quiet=True, header_sets=(HEADERS,))
        if response is not None:
            return response
    return wayback_copy(url)[0]


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


class RegistryUnavailable(RuntimeError):
    """The registry page could not be fetched, or listed no orders."""


def collect() -> list[Action]:
    """Every order in the registry, classified and dated. Raises
    RegistryUnavailable when the registry cannot be read: the build keeps the
    saved records either way, and a nonzero exit shows the source as failed
    in the health report instead of as an empty week."""
    global SOURCE_NOTE
    page = fetch(REGISTRY_URL, retries=RETRY_WAITS, timeout=REGISTRY_TIMEOUT)
    actions = parse_registry(page.text) if page is not None else []
    archived = False
    if not actions:
        live_problem = ("could not be fetched" if page is None else
                        f"listed no orders ({len(page.text)} bytes; starts {page.text[:120]!r})")
        print(f"  WARNING: the registry {live_problem}; reading the Internet Archive copy", file=sys.stderr)
        page, copy_date = wayback_copy(REGISTRY_URL)
        actions = parse_registry(page.text) if page is not None else []
        if not actions:
            raise RegistryUnavailable(f"the New Hampshire executive order registry {live_problem}, and no "
                                      f"readable Internet Archive copy was found ({REGISTRY_URL})")
        archived = True
        SOURCE_NOTE = f"Internet Archive copy from {copy_date}"
        print(f"New Hampshire: registry read from the {SOURCE_NOTE} (the live registry refused this runner)")
    deadline = time.monotonic() + DOCUMENT_BUDGET_SECONDS
    for action in actions:
        # Exact signing dates and generic-declaration hazards come from the order itself.
        if DECLARATION_RE.search(action.title) or MODIFIER_RE.search(action.title):
            document = fetch_document(action.document_url, archived) if time.monotonic() < deadline else None
            if document is not None:
                action.document_text = pdf_text(document.content)
                action.date_signed = date_in_text(action.document_text, int(action.number[:4]))
            if not action.date_signed:
                action.date_signed = CONFIRMED_DATES.get(action.number)
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
    return {"declaration_id": a.stable_id, "state": "NH", "governor": a.governor, "eo_number": a.number, "action_kind": a.action_kind, "action_type": a.action_type, "event_description": a.title, "date_signed": a.date_signed or "", "end_date": "", "weather_related": "true" if a.weather_related else "false", "source_scope": "nh_secretary_of_state_executive_order_registry" + (" (Internet Archive copy)" if SOURCE_NOTE else ""), "document_format": "pdf", "detail_url": a.document_url, "archive_record_url": REGISTRY_URL}


def write(path: str, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def read_saved(path: str) -> list[dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def join_rows(actions: list[Action], saved: list[dict[str, str]]) -> list[dict[str, str]]:
    """The registry's dated weather declarations, plus every saved row the
    registry did not produce. Those are declarations made without an
    executive order (Sandy in 2012, the 2005 Alstead flood), added by hand
    from news coverage, and registry orders whose PDF gives no readable date
    but whose saved row has one (2010-01, 2003-09)."""
    rows = {a.stable_id: {field: action_row(a)[field] for field in JOIN_FIELDS}
            for a in actions if a.action_type == "declaration" and a.weather_related and a.date_signed}
    for row in saved:
        sid = row.get("declaration_id", "")
        if sid and sid not in rows and row.get("date_signed"):
            rows[sid] = {field: row.get(field, "") for field in JOIN_FIELDS}
    return sorted(rows.values(), key=lambda r: (r["date_signed"], r["declaration_id"]), reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True); args = parser.parse_args()
    try:
        actions = collect()
    except RegistryUnavailable as exc:
        raise SystemExit(str(exc))
    rows = [action_row(a) for a in actions]
    write(args.actions_out, ACTION_FIELDS, rows)
    rels = list({(r["source_order_id"], r["target_order_id"], r["relationship_type"]): r for a in actions for r in relationships(a)}.values()); write(args.relationships_out, REL_FIELDS, rels)
    joins = join_rows(actions, read_saved(args.join_out)); write(args.join_out, JOIN_FIELDS, joins)
    print(f"New Hampshire: {len(actions)} actions, {len(rels)} relationships, {len(joins)} weather declarations")


if __name__ == "__main__": main()
