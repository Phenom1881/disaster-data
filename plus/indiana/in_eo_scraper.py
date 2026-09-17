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

Date extraction (fetch_signed_date): confirmed 2026-09-16 that Indiana's
older PDFs (at minimum EO 18-01, likely more of the pre-2020 batch) are
scanned images with no text layer, which is why every one of the 15
declarations currently in declarations_for_join.csv has a blank
date_signed -- not a scraper bug, pdfplumber was correctly reporting no
text to find. OCR is now tried as a second, honest attempt when native
extraction returns nothing; see fetch_signed_date's docstring below.
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

try:
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError:
    pytesseract = None
    convert_from_bytes = None

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
    date_via_ocr: bool = False


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
# Indiana's own attestation language ("this 29th day of September, 2022")
# never matched DATE_RE above -- that pattern only covers "Month Day, Year".
# Confirmed as a real, pre-existing gap on 2026-09-17 (EO 22-15 checked
# directly: the WHEREAS clause's "September 3, 2022" was being returned as
# the signing date because it was the only shape DATE_RE could see; the
# real signature line, "this 29th day of September, 2022," used a shape
# this regex never covered at all). New Mexico's scraper already handles
# both shapes; Indiana's never did.
#
# The suffix after the day number is deliberately permissive ([^\d\s]{0,3}
# rather than a fixed st|nd|rd|th list): confirmed the same day, against
# EO 22-15's real OCR output, that Tesseract misread the superscript "th"
# in "29th" as "29%". A fixed suffix list would have kept missing dates
# like this one every time OCR garbles a small superscript ordinal, which
# is common. Allowing up to 3 non-digit, non-space characters between the
# day number and "day" catches "th"/"st"/"nd"/"rd" and this kind of OCR
# artifact alike, without being so loose it could swallow an unrelated
# number.
DATE_RE_DAY_OF = re.compile(
    r"([0-9]{1,2})[^\d\s]{0,3}\s+day\s+of\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[,]?\s+([0-9]{4})",
    re.IGNORECASE,
)
# Phrases that mark the actual attestation/signature block, distinct from
# a WHEREAS clause that happens to mention a date. Searching for a date
# AFTER one of these anchors (when present) is far more reliable than
# assuming the last date in the whole document is the signing date --
# especially once OCR is involved, since OCR doesn't reliably preserve
# a document's true reading order the way native text extraction does.
SIGNATURE_ANCHOR_RE = re.compile(
    r"(?:IN\s+TESTIMONY\s+WHEREOF|GIVEN\s+under\s+my\s+hand|hereunto\s+set\s+my\s+hand)",
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


def _ocr_pdf_text(pdf_bytes: bytes, max_pages: int = 3, dpi: int = 300) -> str:
    """Second attempt at getting text out of a PDF, used ONLY when native
    pdfplumber extraction already returned nothing. Confirmed 2026-09-16
    that at least Indiana's older EOs are scanned images with no text
    layer (EO 18-01 checked directly against the live source).

    Never guesses: returns "" if OCR isn't installed, the PDF can't be
    rendered, or OCR itself produces no text. A blank result here flows
    through exactly the same way a blank native-extraction result always
    has -- date_signed stays blank, the declaration is correctly skipped
    by eo_storm_join.py, same fail-closed behavior as before this existed.
    """
    if pytesseract is None or convert_from_bytes is None:
        return ""
    try:
        images = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=1, last_page=max_pages)
    except Exception as exc:
        print(f"  OCR fallback: could not render PDF to images: {exc}", file=sys.stderr)
        return ""
    parts = []
    for image in images:
        try:
            parts.append(pytesseract.image_to_string(image))
        except Exception as exc:
            print(f"  OCR fallback: tesseract failed on a page: {exc}", file=sys.stderr)
    return "\n".join(parts)


def _date_from_text(text: str) -> str:
    """Find the signing date within a block of text, trying both date
    shapes Indiana's real PDFs use ("Month Day, Year" and "Nth day of
    Month, Year"). Returns "" if neither pattern matches anywhere in the
    given text. This is a pure helper with no anchor logic of its own --
    fetch_signed_date decides WHICH slice of the document to hand it.
    """
    for month_name, day, year in reversed(DATE_RE.findall(text)):
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}"
            except ValueError:
                pass
    for day, month_name, year in reversed(DATE_RE_DAY_OF.findall(text)):
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}"
            except ValueError:
                pass
    return ""


def fetch_signed_date(session: requests.Session, pdf_url: str) -> tuple[str, bool]:
    """Extract the real signing date from the order's own PDF text.

    Never inferred from the EO number or file name -- read from the
    document's own attestation language ("IN TESTIMONY WHEREOF ... this
    __ day of ___, 20__" or "GIVEN under my hand ... [Month] [Day], [Year]").
    Returns ("", False) if the PDF can't be fetched or parsed even after
    the OCR fallback, or if no date can be confidently attributed to the
    signature block; a blank date_signed is a correct, honest outcome
    rather than a fabricated one.

    Confirmed 2026-09-17 (EO 22-15): searching the WHOLE document for the
    last date-shaped string is not safe. That document's WHEREAS clause
    mentions a flood date ("September 3, 2022") that is NOT the signing
    date; the real signing date ("29th day of September, 2022") appears
    only in the attestation block, in a date SHAPE the old pattern never
    covered at all. Fix: when an attestation anchor phrase is present,
    search only the text AFTER it. Only when no such anchor can be found
    does this fall back to searching the whole document, which is no
    worse than the original behavior and still better than giving up.

    Returns (date_signed, via_ocr) so callers can record honestly whether
    the date came from the PDF's native text or from OCR.
    """
    if pdfplumber is None:
        return "", False
    try:
        resp = session.get(pdf_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return "", False

    via_ocr = False
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        text = ""

    if not text.strip():
        # Native extraction found nothing -- likely a scanned image PDF,
        # confirmed to be the case for at least one Indiana EO already.
        # Try OCR before giving up.
        text = _ocr_pdf_text(resp.content)
        via_ocr = bool(text.strip())

    if not text.strip():
        return "", False

    anchor = SIGNATURE_ANCHOR_RE.search(text)
    if anchor:
        date = _date_from_text(text[anchor.end():])
        if date:
            return date, via_ocr
        # Anchor found but no date matched right after it (OCR garble on
        # exactly that line is plausible) -- fall through to the
        # whole-document search below rather than giving up immediately.

    date = _date_from_text(text)
    return date, via_ocr


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
                action.date_signed, action.date_via_ocr = fetch_signed_date(session, action.pdf_url)
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
    n_dated = sum(1 for a in actions if a.is_original_weather_declaration and a.date_signed)
    n_ocr = sum(1 for a in actions if a.date_via_ocr)
    print(f"Indiana: {len(actions)} actions scraped, {n_join} routed to join CSV, {n_dated} with a resolved date_signed ({n_ocr} via OCR).")


if __name__ == "__main__":
    main()
