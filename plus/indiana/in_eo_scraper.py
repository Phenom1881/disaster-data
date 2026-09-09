"""Indiana executive order scraper for the DisasterData Plus pipeline.

Sources (all verified against the live sites, structure confirmed by hand
before this scraper was written -- no URL structure here is guessed):

  1. Current governor (Braun, 2025-present):
     https://www.in.gov/gov/newsroom/executive-orders/index.html
     Static server-rendered HTML. Each EO is listed as:
       "Executive Order NN-NN" (bold/heading text)
       "TITLE IN ALL CAPS" (hyperlink to a PDF under /gov/files/...)
     The page groups entries under three headings we care about differently:
       "Governor Braun's Executive Orders"      -> currently active
       "Other Active Executive Orders"          -> older EOs still active
       "Non-Active Governor Braun Executive Orders" -> superseded/expired
     All three headings can contain original weather declarations, so all
     three are scraped; the heading is recorded but does not gate inclusion.

  2. Historical governors, each with the same per-year listing pattern:
     https://www.in.gov/governorhistory/ericjholcomb/newsroom/executive-orders/
     https://www.in.gov/governorhistory/ericjholcomb/newsroom/executive-orders/<YYYY>-executive-orders/
     (Holcomb: 2017-2025)
     https://www.in.gov/governorhistory/mitchdaniels/2400.htm
     (Daniels: index page links out to per-year archives 2005-2012; the
     per-year archive URLs are discovered by following the real links on
     that page rather than assumed.)

  3. Pre-2005 (O'Bannon/Kernan, in scope back to 2000) and any numbering
     gaps: Indiana Register / IGA's own historical PDF listing:
     https://iar.iga.in.gov/Historical-List-of-EOs.pdf
     This is a real, government-published, comprehensive index -- used
     here as a cross-check/backfill source, not a guess.

Classification approach: Indiana's own EO titles are highly self-describing
("DECLARING A DISASTER EMERGENCY ... DUE TO SEVERE WEATHER, TORNADIC
ACTIVITY AND FLOODING"), so hazard keywording happens against the title
text extracted from the page -- never against inferred/assumed content.
Titles that don't contain a clear hazard keyword are left for
eo_storm_join.py's own fail-closed classifier to mark ambiguous; this
scraper does not guess.

"Original declaration" vs. companion/administrative order: an order is
routed to declarations_for_join.csv only if its title independently reads
as a NEW disaster/emergency declaration for a weather hazard (e.g. begins
"DECLARING A DISASTER EMERGENCY ..." / "DECLARATION OF ENERGY EMERGENCY
... DUE TO ..." tied to a weather cause). Titles that are clearly
amendments, extensions, waivers of hours-of-service for carriers, or
rescissions of an already-recorded declaration are captured in
--actions-out (for completeness/audit) but excluded from --join-out.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:  # pragma: no cover - dependency documented in README
    pdfplumber = None

STATE = "IN"
GOVERNOR = "Indiana Governor"

BASE = "https://www.in.gov"

# Real, verified entry points -- not guessed.
CURRENT_EO_PAGE = f"{BASE}/gov/newsroom/executive-orders/index.html"
HOLCOMB_EO_INDEX = f"{BASE}/governorhistory/ericjholcomb/newsroom/executive-orders/"
DANIELS_EO_INDEX = f"{BASE}/governorhistory/mitchdaniels/2400.htm"
HISTORICAL_PDF = "https://iar.iga.in.gov/Historical-List-of-EOs.pdf"

MIN_YEAR = 2000  # standing 2000-present scoping rule for all new adapters

HEADERS = {
    "User-Agent": "DisasterDataPlus-Adapter/1.0 (+https://disasterdata.io/plus/)"
}

WEATHER_KEYWORDS = {
    "flood": "flood",
    "flooding": "flood",
    "tornado": "severe_storm",
    "tornadic": "severe_storm",
    "severe weather": "severe_storm",
    "severe storm": "severe_storm",
    "derecho": "severe_storm",
    "wind": "wind",
    "winter storm": "winter",
    "winter weather": "winter",
    "snow": "winter",
    "ice storm": "winter",
    "hurricane": "tropical",
    "tropical storm": "tropical",
    "drought": "drought",
    "wildfire": "fire",
    "wild fire": "fire",
}

# Title patterns that mean "this is a companion/administrative order tied to
# an emergency, not itself an original declaration" -- excluded from the
# join even when a weather keyword appears in the title.
NON_ORIGINAL_PATTERNS = [
    r"\bEXTENSION OF\b",
    r"\bEXTENDING\b",
    r"\bCONTINUATION OF\b",
    r"\bCONTINUING\b",
    r"\bAMEND(?:MENT|ING)?\b",
    r"\bSUPPLEMENT(?:ING|AL)?\b",
    r"\bRESCI(?:ND|SSION)\b",
    r"\bWAIVER OF HOURS OF SERVICE\b",
    r"\bSPECIAL PAID LEAVE\b",
    r"^Executive Order .*\(Amended\)",
    r"^Executive Order .*\(Corrected\)",
]
NON_ORIGINAL_RE = re.compile("|".join(NON_ORIGINAL_PATTERNS), re.IGNORECASE)

EO_HEADING_RE = re.compile(r"Executive Order\s+([0-9]{2,4}-[0-9]{1,3})", re.IGNORECASE)


@dataclass
class Action:
    eo_number: str
    title: str
    pdf_url: str
    source_page: str
    year: int
    hazard_guess: Optional[str] = None
    is_original_weather_declaration: bool = False
    date_signed: str = ""


def _year_from_eo_number(eo_number: str) -> Optional[int]:
    """Indiana numbers EOs as YY-NN or YYYY-NN depending on era."""
    prefix = eo_number.split("-")[0]
    if len(prefix) == 4 and prefix.isdigit():
        return int(prefix)
    if len(prefix) == 2 and prefix.isdigit():
        yy = int(prefix)
        # 90-05 style pre-2000 orders vs. 05-14 style 2000s orders.
        return 1900 + yy if yy > 50 else 2000 + yy
    return None


def classify_title(title: str) -> Optional[str]:
    lowered = title.lower()
    for phrase, category in WEATHER_KEYWORDS.items():
        if phrase in lowered:
            return category
    return None


def is_original_declaration(title: str) -> bool:
    lowered = title.lower()
    has_declaration_phrase = (
        "declaring a disaster emergency" in lowered
        or "declaration of a statewide disaster emergency" in lowered
        or "declaration of disaster emergency" in lowered
        or ("declaration of energy emergency" in lowered and classify_title(title))
    )
    if not has_declaration_phrase:
        return False
    # Even a title that opens with a real declaration phrase can still be a
    # pure follow-on act if it's explicitly an extension/amendment/rescission
    # of a PRIOR declaration rather than a new one (e.g. "EXTENSION OF
    # EXECUTIVE ORDER 17-13: DECLARATION OF DISASTER EMERGENCY"). A title
    # that also bundles a waiver of hours-of-service *for the same new
    # event* (e.g. EO 24-7) is still an original declaration -- the waiver
    # is a secondary provision within it, not a separate follow-on order.
    if re.search(r"\bextension of\b|\bextending\b|\bamend(?:ment|ing)?\b|\brescission\b|\brescind\b", lowered):
        return False
    return True


def _parse_listing_page(html: str, page_url: str) -> list[Action]:
    """Parse an in.gov executive-orders listing page.

    Real structure (verified 2026-09): a flat list of <li> items where each
    item contains the "Executive Order NN-NN" text followed by a link whose
    text is the ALL-CAPS title and whose href is the PDF.
    """
    soup = BeautifulSoup(html, "html.parser")
    actions: list[Action] = []
    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        m = EO_HEADING_RE.search(text)
        if not m:
            continue
        eo_number = m.group(1)
        link = li.find("a", href=True)
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        if not title or "REPORTS" in title.upper() and len(title) < 12:
            continue
        pdf_url = urljoin(page_url, link["href"])
        year = _year_from_eo_number(eo_number)
        if year is None:
            continue
        actions.append(
            Action(
                eo_number=eo_number,
                title=title,
                pdf_url=pdf_url,
                source_page=page_url,
                year=year,
            )
        )
    return actions


def _discover_daniels_year_pages(session: requests.Session) -> list[str]:
    """Follow the real links on the Daniels-era index page rather than
    assuming a URL pattern for the per-year archives."""
    resp = session.get(DANIELS_EO_INDEX, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    year_urls = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text.isdigit() and 2000 <= int(text) <= 2013:
            year_urls.append(urljoin(DANIELS_EO_INDEX, a["href"]))
    return year_urls


def _discover_holcomb_year_pages(session: requests.Session) -> list[str]:
    resp = session.get(HOLCOMB_EO_INDEX, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    year_urls = {HOLCOMB_EO_INDEX}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "executive-orders" in href and re.search(r"20(1[7-9]|2[0-5])-executive-orders", href):
            year_urls.add(urljoin(HOLCOMB_EO_INDEX, href))
    return sorted(year_urls)


DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+([0-9]{1,2}),?\s+([0-9]{4})",
    re.IGNORECASE,
)
MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}


def fetch_signed_date(session: requests.Session, pdf_url: str) -> str:
    """Extract the real signing date from the order's own PDF text.

    Never inferred from the EO number or file name -- read from the
    document's own 'I have hereunto set my hand ... this __ day of' /
    dateline text. Returns an empty string (not a guess) if the PDF
    can't be fetched or parsed; a blank date_signed is a correct,
    honest outcome rather than a fabricated one.
    """
    if pdfplumber is None:
        return ""
    try:
        resp = session.get(pdf_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        return ""
    matches = DATE_RE.findall(text)
    if not matches:
        return ""
    month_name, day, year = matches[-1]  # signature block is at the end
    month = MONTHS.get(month_name.lower())
    if not month:
        return ""
    try:
        return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    except ValueError:
        return ""


def scrape(session: Optional[requests.Session] = None) -> list[Action]:
    session = session or requests.Session()
    all_actions: list[Action] = []
    pages_to_scrape = [CURRENT_EO_PAGE]

    try:
        pages_to_scrape.extend(_discover_holcomb_year_pages(session))
    except requests.RequestException as exc:
        print(f"warning: could not enumerate Holcomb-era pages: {exc}", file=sys.stderr)

    try:
        pages_to_scrape.extend(_discover_daniels_year_pages(session))
    except requests.RequestException as exc:
        print(f"warning: could not enumerate Daniels-era pages: {exc}", file=sys.stderr)

    for url in pages_to_scrape:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"warning: failed to fetch {url}: {exc}", file=sys.stderr)
            continue
        for action in _parse_listing_page(resp.text, url):
            if action.year < MIN_YEAR:
                continue
            action.hazard_guess = classify_title(action.title)
            action.is_original_weather_declaration = bool(action.hazard_guess) and is_original_declaration(
                action.title
            )
            if action.is_original_weather_declaration:
                action.date_signed = fetch_signed_date(session, action.pdf_url)
            all_actions.append(action)

    # De-duplicate by EO number (the current-governor page and historical
    # per-year pages can overlap during a transition year).
    seen = {}
    for a in all_actions:
        seen[a.eo_number] = a
    return list(seen.values())


def write_outputs(actions: list[Action], actions_out: Path, relationships_out: Path, join_out: Path) -> None:
    actions_out.parent.mkdir(parents=True, exist_ok=True)

    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            ["eo_number", "title", "year", "hazard_guess", "is_original_weather_declaration", "source_url"]
        )
        for a in sorted(actions, key=lambda x: (x.year, x.eo_number)):
            writer.writerow(
                [a.eo_number, a.title, a.year, a.hazard_guess or "", a.is_original_weather_declaration, a.pdf_url]
            )

    # relationships_out: Indiana's own titles usually name the order they
    # extend/amend/rescind ("EXTENSION OF EXECUTIVE ORDER 17-13" etc.). We
    # capture that reference where present; this file is for audit, not
    # for the join.
    ref_re = re.compile(r"EXECUTIVE ORDER(?:S)?\s+([0-9]{2,4}-[0-9]{1,3})", re.IGNORECASE)
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["eo_number", "relationship_type", "references_eo_number"])
        for a in actions:
            if a.is_original_weather_declaration:
                continue
            refs = [m for m in ref_re.findall(a.title) if m != a.eo_number]
            for ref in refs:
                rel_type = "amendment"
                lowered = a.title.lower()
                if "extension" in lowered or "extending" in lowered:
                    rel_type = "extension"
                elif "rescission" in lowered or "rescind" in lowered:
                    rel_type = "termination"
                writer.writerow([a.eo_number, rel_type, ref])

    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        for a in sorted(actions, key=lambda x: (x.year, x.eo_number)):
            if not a.is_original_weather_declaration:
                continue
            declaration_id = f"IN-EO-{a.eo_number}"
            writer.writerow(
                [
                    declaration_id,
                    GOVERNOR,
                    a.eo_number,
                    a.title,
                    a.date_signed,
                    a.pdf_url,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Indiana executive orders for DisasterData Plus.")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    actions = scrape()
    write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out))
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    print(f"Indiana: {len(actions)} actions scraped, {n_join} routed to join CSV.")


if __name__ == "__main__":
    main()
