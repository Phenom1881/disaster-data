"""Indiana executive order scraper for the DisasterData Plus pipeline.

Sources (all verified against the live sites, structure confirmed by hand
before this scraper was written -- no URL structure here is guessed):

  1. Current governor (Braun, 2025-present):
     https://www.in.gov/gov/newsroom/executive-orders/
     (the canonical listing URL; the explicit .../index.html form is kept
     only as a fallback, see CURRENT_EO_PAGES below)
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

import os
import shutil
import subprocess
from collections import Counter

# OCR runs the tesseract program directly (the Plus workflow installs it)
# and renders pages with pypdfium2, which pdfplumber already installs. The
# old route needed pytesseract, pdf2image and poppler, none of which the
# workflow ever installed, so OCR never ran on GitHub: every run from
# 2026-09-12 to 2026-09-27 logged "0 with a resolved date_signed (0 via OCR)".
TESSERACT = shutil.which("tesseract")

# Why each declaration's PDF gave no date on this run, reported in the log.
DATE_PROBLEMS: Counter = Counter()

STATE = "IN"
GOVERNOR = "Indiana Governor"

BASE = "https://www.in.gov"

# Real, verified entry points -- not guessed.
#
# The current governor's listing is tried at its canonical URL first (the one
# in.gov itself links to and search engines index, confirmed live on
# 2026-09-25 to list EO 26-21), then at the explicit index.html form this
# scraper originally used. Every Plus run from 2026-09-17 on came back with no
# 2025-2026 orders at all while the Holcomb per-year pages, which are linked
# without index.html, kept working. Whichever URL returns orders first wins.
CURRENT_EO_PAGES = [
    f"{BASE}/gov/newsroom/executive-orders/",
    f"{BASE}/gov/newsroom/executive-orders/index.html",
]
CURRENT_EO_PAGE = CURRENT_EO_PAGES[0]
HOLCOMB_EO_INDEX = f"{BASE}/governorhistory/ericjholcomb/newsroom/executive-orders/"
DANIELS_EO_INDEX = f"{BASE}/governorhistory/mitchdaniels/2400.htm"
HISTORICAL_PDF = "https://iar.iga.in.gov/Historical-List-of-EOs.pdf"

MIN_YEAR = 2000  # standing 2000-present scoping rule for all new adapters

HEADERS = {
    "User-Agent": "DisasterDataPlus-Adapter/1.0 (+https://disasterdata.io/plus/)"
}
# Order PDFs are requested the way a browser would ask. The listing pages
# answer the adapter's own name, but no PDF has ever produced a date on a
# GitHub run, and each failure was swallowed without a word.
PDF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)",
    "Accept": "application/pdf,*/*",
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

# Every shape of an ORIGINAL disaster declaration title seen on Indiana's own
# pages. The earlier fixed-phrase check only knew "declaring a disaster
# emergency" and two "declaration of" forms, so it silently dropped:
#   "DECLARING A STATEWIDE DISASTER EMERGENCY ..."  EO 26-21 (Aug 2026 derecho)
#   "DECLARING DISASTER EMERGENCIES IN ..."          EO 23-5, EO 23-6
#   "Disaster Declaration for ..."                   EO 12-01 (Daniels era)
ORIGINAL_DECLARATION_RE = re.compile(
    r"\bdeclar(?:ing|ation\s+of)\s+(?:an?\s+)?(?:statewide\s+)?"
    r"disaster\s+emergenc(?:y|ies)\b"
    r"|\bdisaster\s+declaration\s+for\b",
    re.IGNORECASE,
)


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
        bool(ORIGINAL_DECLARATION_RE.search(lowered))
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


# 2400.htm answered 404 on 2026-09-26. The per-year archive pages are still
# published, and several carry the same "Executive Order Archives: 2012 |
# 2011 | ... | 2005" links, so they stand in for the index when it is gone.
DANIELS_INDEX_FALLBACKS = [
    f"{BASE}/governorhistory/mitchdaniels/2419.htm",
    f"{BASE}/governorhistory/mitchdaniels/2938.htm",
]


def _daniels_year_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    year_urls = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text.isdigit() and 2000 <= int(text) <= 2013:
            url = urljoin(page_url, a["href"])
            if url not in year_urls:
                year_urls.append(url)
    return year_urls


def _discover_daniels_year_pages(session: requests.Session) -> list[str]:
    """Follow the real links on the Daniels-era index page rather than
    assuming a URL pattern for the per-year archives. When the index itself
    is gone, read the same links off an archive page that carries them."""
    last_error = None
    for page_url in [DANIELS_EO_INDEX] + DANIELS_INDEX_FALLBACKS:
        try:
            resp = session.get(page_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            last_error = exc
            continue
        year_urls = _daniels_year_links(resp.text, page_url)
        if year_urls:
            if page_url != DANIELS_EO_INDEX:
                print(f"note: Daniels-era index unavailable; year links read from {page_url}",
                      file=sys.stderr)
            return year_urls
    if last_error:
        raise last_error
    return []


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
    """Text of a scanned PDF read with OCR: the first page and the last
    max_pages pages, since the attestation ("IN TESTIMONY WHEREOF ...")
    closes the order. Returns "" when tesseract is not installed or nothing
    could be read, so an unreadable order stays undated rather than guessed.
    """
    if not TESSERACT:
        return ""
    try:
        import pypdfium2 as pdfium
        from PIL import ImageFilter
        document = pdfium.PdfDocument(pdf_bytes)
        try:
            count = len(document)
            indexes = sorted({0, *range(max(count - max_pages, 0), count)})
            images = []
            for index in indexes:
                page = document[index]
                try:
                    images.append(page.render(scale=dpi / 72, grayscale=True).to_pil().copy())
                finally:
                    page.close()
        finally:
            document.close()
    except Exception as exc:
        print(f"  OCR fallback: could not render PDF to images: {exc}", file=sys.stderr)
        return ""
    parts = []
    for image in images:
        buffer = io.BytesIO()
        image.convert("L").filter(ImageFilter.MedianFilter(3)).save(buffer, "PNG")
        try:
            result = subprocess.run([TESSERACT, "stdin", "stdout", "--psm", "3"], input=buffer.getvalue(),
                                    capture_output=True, timeout=120,
                                    env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  OCR fallback: tesseract failed on a page: {exc}", file=sys.stderr)
            continue
        if result.returncode == 0:
            parts.append(result.stdout.decode("utf-8", "replace"))
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


def fetch_signed_date(session: requests.Session, pdf_url: str,
                      expected_year: Optional[int] = None) -> tuple[str, bool]:
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
        DATE_PROBLEMS["pdfplumber not installed"] += 1
        return "", False
    resp = None
    for attempt in (1, 2):
        try:
            resp = session.get(pdf_url, headers=PDF_HEADERS, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == 2:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                DATE_PROBLEMS[f"download failed ({type(exc).__name__}{' ' + str(status) if status else ''})"] += 1
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
        DATE_PROBLEMS["scanned, OCR not installed" if not TESSERACT else "scanned, OCR read nothing"] += 1
        return "", False

    def plausible(date: str) -> str:
        # An order is numbered by the year it is signed (EO 18-01 in 2018).
        return date if date and (expected_year is None or date[:4] == str(expected_year)) else ""

    anchor = SIGNATURE_ANCHOR_RE.search(text)
    if anchor:
        date = plausible(_date_from_text(text[anchor.end():]))
        if date:
            return date, via_ocr
        # Anchor found but no date matched right after it (OCR garble on
        # exactly that line is plausible) -- fall through to the
        # whole-document search below rather than giving up immediately.

    date = plausible(_date_from_text(text))
    if not date:
        DATE_PROBLEMS["read, but no signing date found" + (" (OCR)" if via_ocr else "")] += 1
    return date, via_ocr


def _fetch_current_governor_page(session: requests.Session) -> list[Action]:
    """Read the current governor's listing, trying CURRENT_EO_PAGES in order and
    stopping at the first URL that returns at least one order. An empty result
    is reported on stdout, not just stderr, so it shows up in plus_build.log
    even if a caller drops stderr."""
    for url in CURRENT_EO_PAGES:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"warning: failed to fetch {url}: {exc}", file=sys.stderr)
            continue
        actions = _parse_listing_page(resp.text, url)
        if actions:
            print(f"Indiana: {len(actions)} orders read from the current governor's page ({url}).")
            return actions
        print(f"warning: {url} returned a page with no executive orders on it", file=sys.stderr)
    print(
        "WARNING Indiana: no orders could be read from the current governor's page; "
        "2025-present Indiana orders are missing from this run."
    )
    return []


def load_saved_dates(join_path: Path) -> dict[str, str]:
    """Signing dates already found, by EO number, from the saved join file,
    so an order's PDF is read only until its date is known."""
    try:
        with Path(join_path).open(newline="", encoding="utf-8") as handle:
            return {row["eo_number"]: row["date_signed"] for row in csv.DictReader(handle)
                    if row.get("eo_number") and row.get("date_signed")}
    except (OSError, csv.Error, KeyError):
        return {}


def scrape(session: Optional[requests.Session] = None, saved_dates: Optional[dict] = None) -> list[Action]:
    session = session or requests.Session()
    saved_dates = saved_dates or {}
    all_actions: list[Action] = []
    pages_to_scrape = []

    try:
        pages_to_scrape.extend(_discover_holcomb_year_pages(session))
    except requests.RequestException as exc:
        print(f"warning: could not enumerate Holcomb-era pages: {exc}", file=sys.stderr)

    try:
        pages_to_scrape.extend(_discover_daniels_year_pages(session))
    except requests.RequestException as exc:
        print(f"warning: could not enumerate Daniels-era pages: {exc}", file=sys.stderr)

    # (listing actions, page url) batches: the current governor first, then the
    # historical per-year pages, same order as before.
    batches = [_fetch_current_governor_page(session)]
    for url in pages_to_scrape:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"warning: failed to fetch {url}: {exc}", file=sys.stderr)
            continue
        batches.append(_parse_listing_page(resp.text, url))

    for batch in batches:
        for action in batch:
            if action.year < MIN_YEAR:
                continue
            action.hazard_guess = classify_title(action.title)
            action.is_original_weather_declaration = bool(action.hazard_guess) and is_original_declaration(
                action.title
            )
            if action.is_original_weather_declaration:
                year = _year_from_eo_number(action.eo_number)
                saved = saved_dates.get(action.eo_number, "")
                if saved and (year is None or saved[:4] == str(year)):
                    action.date_signed = saved
                    DATE_PROBLEMS["kept from earlier runs"] += 1
                else:
                    action.date_signed, action.date_via_ocr = fetch_signed_date(session, action.pdf_url, year)
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

    actions = scrape(saved_dates=load_saved_dates(Path(args.join_out)))
    write_outputs(actions, Path(args.actions_out), Path(args.relationships_out), Path(args.join_out))
    n_join = sum(1 for a in actions if a.is_original_weather_declaration)
    n_dated = sum(1 for a in actions if a.is_original_weather_declaration and a.date_signed)
    n_ocr = sum(1 for a in actions if a.date_via_ocr)
    print(f"Indiana: {len(actions)} actions scraped, {n_join} routed to join CSV, {n_dated} with a resolved date_signed ({n_ocr} via OCR).")
    if DATE_PROBLEMS:
        print("Indiana signing dates: " + "; ".join(f"{n} {why}" for why, n in DATE_PROBLEMS.most_common()))


if __name__ == "__main__":
    main()
