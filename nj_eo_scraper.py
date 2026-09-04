"""
nj_eo_scraper.py

Scrapes the New Jersey Governor's Executive Order InfoBank
(https://www.nj.gov/infobank/eo/) and produces:

  1. nj_emergency_actions_all.csv   - every order found, across administrations
  2. nj_order_relationships.csv     - extracted order-to-order relationships
                                      (terminates / extends / amends / etc.)
  3. declarations_for_join.csv      - Virginia-compatible join file, ready
                                      for eo_storm_join.py

Research basis (ChatGPT, 2026-09-04, verified against sampled pages):
  - Master directory links one archive page per administration.
  - Modern administrations (~2018-present) use an
    /approved/eo_archive.shtml pattern; older ones use an administration
    index page. Either way the page body is one HTML table per
    administration: Number | Description/Subject | Date Issued, with each
    number linked to its order document.
  - 2018-present and most 2010-2018 orders are text-selectable PDFs.
    1990-2009 orders are mostly full-text HTML under /infobank/circular/.
    1962-1989 pages exist but are selective, not complete series.
  - There is no public JSON/API, so this script follows links rather than
    hard-coding every administration URL.

IMPORTANT - not yet tested against the live site by this adapter's author:
this sandbox's network allowlist does not include nj.gov. A first draft of
this script WAS live-tested externally (2026-09-04) and the following bugs
were found and patched here:
  - Discovery counted the same administration twice under different URLs,
    inflating the reported total (1,950 vs. a real ~1,253 orders). Fixed by
    canonicalizing on the administration code in the URL (e.g. "049florio")
    and keeping exactly one URL per code.
  - Nested eo_archive.shtml-link following was not scoped to the same
    administration, so a governor with no table of their own (Cahill)
    incorrectly inherited the current governor's (Sherrill's) rows. Fixed
    by requiring the nested link's administration code to match.
  - Murphy's YYYY/MM/DD date format was not recognized, leaving all 418
    Murphy rows blank-dated. Fixed by adding that format and extracting a
    leading date substring before parsing (so trailing annotation text
    after a date does not break every format attempt).
  - Appendix rows and duplicate order numbers within one table were
    counted as separate orders. Fixed by skipping "Appendix"-labeled rows
    and deduping by order number per page.
  - Relationship regexes missed spelled-out "Executive Order Number 37" /
    bare "Order No. 44" phrasing and entirely missed passive-plural
    phrasing ("Executive Order Nos. 73, 74 and 75 are rescinded"). Fixed
    with a shared ORDER_REF pattern reused for both active and passive
    voice, each is/are/was/were variant, and multi-target lists.
  - The same relationship was reported twice when it appeared in both the
    table description and the fetched document text. Fixed with a
    (source, target, type) dedup set.
  - Fetching an order's own document page could pull in a later-added
    archive banner ("has been terminated by...") that then misclassified
    the ORIGINAL declaration as a termination. Fixed by classifying
    action_type from the table description only; document_text is still
    used for relationship extraction, where that exact banner text is the
    useful signal.
  - The PDF low-yield warning threshold was raised from <50 to <250
    characters: real text-selectable PDFs extracted 7,700-20,000+
    characters, and 50 was shown to be too loose a bar to reliably catch a
    bad (e.g. scanned-image) extraction.
  - structured_archive_coverage_start corrected to 1990-01-18 (Florio EO 1's
    own text: "the 18th day of January", 1990), not 1990-01-16.

ROUND 2 PATCH (2026-09-04, second live-validation pass): two bugs remained
after round 1 and were fixed here:
  - The appendix filter checked the DESCRIPTION for the word "appendix",
    which incorrectly dropped real orders that merely mention an appendix
    in their substantive text (Murphy EO 159/170/178/275, Christie EO 47),
    while genuine attachment rows (Sherrill "EO 3 Appendix A", Murphy "2A")
    still got captured under the base order's number and silently replaced
    its real link. Fixed by checking only the first-cell label and the
    linked document URL, and by skipping a detected attachment entirely
    rather than adding it to seen_numbers.
  - Relationship deduplication only ran WITHIN a single order's extraction
    call, so the same pair found from two different orders' text (EO 46's
    "terminated by EO 48" banner and EO 48's own "terminates EO 46"/
    "rescinds EO 46" text) still produced duplicate rows - and "rescinds"
    vs "terminates" as different relationship_type values meant even a
    single-order dedup pass couldn't catch it. Fixed by (a) normalizing
    "rescinds" into "terminates" at extraction time and (b) adding a
    dedupe_relationships() pass that runs once on the FULL combined list
    in main(), not per-order.
  - Malformed rows can shift a date into the description cell (Christie EO
    109) or put relationship notes where the date normally belongs (Whitman
    EO 46). Dates are now detected across all non-number cells, and a missing
    table date can be recovered from a document's signed "GIVEN" clause.
Not yet re-validated against the live site after this round of fixes.

Design choices, matching the existing codebase conventions:
  - Runs standalone or via new_jersey.py's collect(), same pattern as
    va_eo_scraper.py / va_historical_eo_scraper.py.
  - Degrades rather than crashing: an administration page that fails to
    parse is skipped with a warning, not a hard failure, since the goal is
    a best-effort structured_archive that new_jersey.py can report an
    honest coverage note about.
  - Relationship extraction is regex-based over the description text and
    the order's own document text. It is best-effort: the research flagged
    that NJ's archive metadata has inconsistent labeling (wrong governor
    tags, date typos, blank descriptions), so relationships that cannot be
    confidently extracted are simply omitted rather than guessed.
  - Termination/rescission orders are EXCLUDED from declarations_for_join.csv
    (they should not be date-matched against NOAA storm events - a
    termination order does not correspond to a storm), but ARE still
    written to nj_emergency_actions_all.csv and used to backfill an
    end_date on the original declaration where a relationship was
    extracted.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

MASTER_DIRECTORY_URL = "https://www.nj.gov/infobank/eo/"
REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0; "
        "+https://disasterdata.io/plus/)"
    )
}

# Hazard-specific phrases used to decide whether an order is weather related.
# Generic legal terms such as "emergency" and "disaster" are intentionally
# absent: they occur in public-health and administrative orders as well as in
# boilerplate citations to emergency-management authority.  Every pattern is
# word/phrase bounded so a weather term such as "ice" cannot match inside
# unrelated words such as "practice", "service", "office", or "justice".
WEATHER_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:severe|extreme|inclement|hazardous)\s+weather\b",
        r"\bweather\s+(?:event|emergency|conditions?)\b",
        r"\b(?:winter|coastal|tropical|ice|snow|wind|thunder)\s*storms?\b",
        r"\b(?:major|severe)\s+storms?\b",
        r"\bnor(?:['\N{RIGHT SINGLE QUOTATION MARK}])?easters?\b",
        r"\bhurricanes?\b",
        r"\btropical\s+(?:storms?|cyclones?|depressions?)\b",
        r"\btornado(?:es|s)?\b",
        r"\bblizzards?\b",
        r"\bflood(?:s|ed|ing)?\b",
        r"\bflash\s+flood(?:s|ing)?\b",
        r"\bsnow(?:fall|storms?)?\b",
        r"\b(?:snow\s+(?:and|or)\s+ice|ice\s+(?:and|or)\s+snow|"
        r"ice\s+(?:accumulation|conditions?|hazards?))\b",
        r"\bsleet\b",
        r"\bfreezing\s+rain\b",
        r"\bdroughts?\b",
        r"\bwildfires?\b",
        r"\b(?:forest|brush)\s+fires?\b",
        r"\bfire\s+danger\b",
        r"\bextreme\s+(?:cold|heat)\b",
        r"\bheat\s+waves?\b",
        r"\bcoastal\s+flood(?:s|ing)?\b",
        r"\bhigh\s+winds?\b",
        r"\bwindstorms?\b",
    )
)

# Matches "Executive Order", "E.O.", or bare "Order", each optionally
# followed by "No./Nos./Number", then one or more comma/and-separated
# numbers. The separator is mandatory after the first number. An earlier
# form nested optional whitespace and optional separators inside a repeated
# group; on a long document that could trigger catastrophic backtracking and
# hold one CPU core indefinitely.
#
# Fix #5: an earlier version required "executive order" + "no." both
# present in a fairly rigid order, which missed real phrasings like
# "Order No. 44" (no "executive") and "Executive Order Number 37" (spelled
# out "Number", not "No."). This fragment is reused for both the active
# ("X terminates ORDER_REF") and passive ("ORDER_REF is/are terminated")
# directions below.
ORDER_NUMBER_LIST = (
    r"(\d+(?:(?:\s*,\s*(?:and\s+)?|\s*(?:&|and)\s*)\d+)*)"
)
ORDER_REF = (
    r"(?:executive\s+order|e\.?o\.?|order)s?\s*"
    r"(?:nos?\.?|number)?\s*#?\s*" + ORDER_NUMBER_LIST
)

# verb -> relationship_type
_VERB_TO_TYPE = {
    "terminat": "terminates",
    "rescind": "rescinds",
    "extend": "extends_duration",
    "amend": "amends",
    "supersed": "supersedes",
    "continu": "continues",
}

RELATIONSHIP_PATTERNS = []
for _verb, _rel_type in _VERB_TO_TYPE.items():
    # Active voice: "<verb> <ORDER_REF>", e.g. "terminates Executive Order No. 37"
    RELATIONSHIP_PATTERNS.append((
        _rel_type,
        re.compile(_verb + r"(?:es|s|ing|ed)?\s+(?:the\s+duration\s+of\s+)?" + ORDER_REF, re.I),
    ))
    # Passive voice: "<ORDER_REF> is/are/was/were <verb>ed", e.g.
    # "Executive Order Nos. 73, 74 and 75 are rescinded" - this is the
    # pattern that missed the EO 76 -> 73/74/75 case entirely before.
    RELATIONSHIP_PATTERNS.append((
        _rel_type,
        re.compile(ORDER_REF + r"\s+(?:is|are|was|were)\s+" + _verb + r"(?:ed|d)", re.I),
    ))

# "terminated by <ORDER_REF>" is a special passive case: the REFERENCED
# order is the one doing the terminating, so source/target are swapped
# relative to every other pattern above (handled in extract_relationships).
TERMINATED_BY_PATTERN = re.compile(r"terminated\s+by\s+" + ORDER_REF, re.I)

TERMINATION_TYPES = {"terminates", "rescinds"}


@dataclass
class NJOrder:
    governor: str
    order_number: str
    description: str
    date_issued: Optional[str]
    document_url: str
    document_format: str  # "pdf" or "html"
    document_text: str = ""
    action_type: str = "declaration"  # declaration | extension | amendment | termination
    end_date: Optional[str] = None
    weather_related: bool = False

    @property
    def stable_id(self) -> str:
        gov = re.sub(r"[^A-Z]", "", self.governor.upper()) or "UNK"
        return f"NJ-{gov}-EO-{self.order_number}"


def fetch(url: str) -> Optional[requests.Response]:
    """Fetch a URL, forcing UTF-8 decoding.

    nj.gov's older pages often omit a charset in their Content-Type header.
    requests then guesses Latin-1 by default, which silently mangles UTF-8
    curly quotes and apostrophes into garbage bytes (e.g. "children's"
    rendering as "childrenâ\x80\x99s" downstream). Every page sampled during
    validation was genuinely UTF-8, so force it explicitly rather than
    trusting requests' guess.
    """
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
        return None


ADMIN_CODE_RE = re.compile(r"/infobank/eo/(\d{3}[a-z]+)/", re.I)


def discover_administration_pages() -> list[tuple[str, str, str]]:
    """Return [(admin_code, governor_label, administration_page_url), ...]
    by parsing the master directory page's links. Falls back to an empty
    list (never hard-codes URLs) if the master page itself cannot be
    fetched or parsed, since a structural change there should surface as
    zero coverage, not a stack trace.

    Fix #1: canonicalize by administration code (e.g. "049florio") and keep
    exactly one URL per administration. Earlier this deduped only by exact
    URL string, so a governor whose master-page link and archive.shtml link
    pointed at different URLs got scraped twice under two different labels
    - the root cause of the reported ~1,950-vs-1,253 row discrepancy. When
    more than one URL is found for the same code, the one containing
    "eo_archive.shtml" is preferred, since that is the actual table page
    for modern administrations rather than a landing/index page."""
    resp = fetch(MASTER_DIRECTORY_URL)
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    by_code: dict[str, tuple[str, str]] = {}  # code -> (label, url)

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/infobank/eo/" not in href:
            continue
        code_match = ADMIN_CODE_RE.search(href)
        if not code_match:
            continue
        code = code_match.group(1).lower()
        full_url = requests.compat.urljoin(MASTER_DIRECTORY_URL, href)

        label = link.get_text(strip=True)
        if not label or label.lower().startswith(("http://", "https://")):
            # Fix: some modern links (bare eo_archive.shtml hrefs with no
            # useful anchor text) previously left the governor field as a
            # raw URL. Fall back to a title-cased version of the admin
            # code's alphabetic part (e.g. "049florio" -> "Florio").
            label = re.sub(r"^\d+", "", code).title() or code

        existing = by_code.get(code)
        if existing is None:
            by_code[code] = (label, full_url)
        elif "eo_archive.shtml" in full_url.lower() and "eo_archive.shtml" not in existing[1].lower():
            by_code[code] = (label, full_url)
        # else: keep the first URL found for this code; do not add a
        # second entry, which is what caused double-scraping before.

    return [(code, label, url) for code, (label, url) in by_code.items()]


def parse_administration_table(admin_code: str, governor_label: str, page_url: str) -> list[NJOrder]:
    """Parse one administration's archive/index page into NJOrder rows.

    The page may itself be an index that further links to an
    'approved/eo_archive.shtml'-style table (modern administrations) rather
    than containing the table directly - if no table rows are found on the
    given page but a plausible archive-link is present, follow it once.

    Fix #2: only follow a nested eo_archive.shtml link if it belongs to
    THIS SAME administration code. Earlier this followed the first such
    link found anywhere on the page, including shared site-navigation
    chrome - which is why an administration with no table of its own (e.g.
    Cahill) incorrectly inherited the current governor's (Sherrill's) 23
    rows instead of correctly showing zero."""
    resp = fetch(page_url)
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = _extract_order_rows(soup, page_url)

    if not rows:
        nested = soup.find("a", href=re.compile(r"eo_archive\.shtml", re.I))
        if nested and nested.get("href"):
            nested_url = requests.compat.urljoin(page_url, nested["href"])
            nested_code_match = ADMIN_CODE_RE.search(nested_url)
            same_administration = (
                nested_code_match is not None
                and nested_code_match.group(1).lower() == admin_code.lower()
            )
            if nested_url != page_url and same_administration:
                nested_resp = fetch(nested_url)
                if nested_resp is not None:
                    nested_soup = BeautifulSoup(nested_resp.text, "html.parser")
                    rows = _extract_order_rows(nested_soup, nested_url)

    orders = []
    for order_number, description, date_issued, doc_url in rows:
        if not doc_url:
            continue
        fmt = "pdf" if doc_url.lower().endswith(".pdf") else "html"
        orders.append(
            NJOrder(
                governor=governor_label,
                order_number=order_number,
                description=description,
                date_issued=date_issued,
                document_url=doc_url,
                document_format=fmt,
            )
        )
    return orders


def _extract_order_rows(soup: BeautifulSoup, base_url: str):
    """Pull (order_number, description, date_issued, document_url) tuples
    out of whatever table(s) are on the page. NJ's markup is not uniform
    across 60+ years of administrations, so this walks table rows
    generically rather than assuming a fixed column count or table id.

    Fix #4 (round 2): the first patch's `re.search(r"appendix", ...)`
    against the DESCRIPTION was overbroad - it dropped real orders whose
    substantive text merely mentions an appendix (Murphy EO 159/170/178/275,
    Christie EO 47), while an attachment whose label IS an appendix
    (Sherrill "EO 3 Appendix A", Murphy "2A") still got captured under the
    base order's number, silently replacing the real order's link with the
    attachment's. Now only the first-cell label and the linked document
    URL are checked for "appendix" - never the description - and a
    detected attachment row is skipped entirely rather than added to
    seen_numbers, so the base order (parsed later or earlier in table
    order) is retained rather than crowded out."""
    results = []
    seen_numbers: set[str] = set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            first_cell_text = cells[0].get_text(strip=True)
            non_number_cells = [cell.get_text(" ", strip=True) for cell in cells[1:]]
            parsed_dates = [
                parsed for parsed in (_normalize_date(text) for text in non_number_cells)
                if parsed
            ]
            date_issued = parsed_dates[0] if parsed_dates else None

            # A few malformed archive rows shift the date into column two
            # (Christie EO 109) or place relationship annotations in column
            # three (Whitman EO 46). Keep the first substantive non-date cell
            # as the description and detect the date independently.
            description = ""
            for text in non_number_cells:
                if _normalize_date(text):
                    continue
                if re.fullmatch(
                    r"(?:terminat(?:es|ed)?|rescind(?:s|ed)?|amend(?:s|ed)?|"
                    r"modif(?:y|ies|ied)|supersed(?:es|ed)?|continu(?:es|ed)?)?"
                    r"\s*(?:EO|Executive Order)?\s*#?\s*\d+\s*[A-Za-z .]*",
                    text,
                    re.I,
                ):
                    continue
                description = text
                break

            link_tag = cells[0].find("a", href=True) or (
                cells[1].find("a", href=True) if len(cells) > 1 else None
            )
            link_href = link_tag["href"] if link_tag else ""

            if re.search(r"appendix", first_cell_text, re.I) or re.search(r"appendix", link_href, re.I):
                continue

            number_match = re.search(r"\d+[A-Za-z]?", first_cell_text)
            if not number_match:
                continue
            order_number = number_match.group(0)
            if order_number in seen_numbers:
                continue
            seen_numbers.add(order_number)

            if not link_tag:
                continue
            doc_url = requests.compat.urljoin(base_url, link_href)

            results.append((order_number, description, date_issued, doc_url))
    return results


# Fix #3: Murphy's table uses YYYY/MM/DD, which the original format list
# did not include, so all 418 Murphy rows silently ended up with a blank
# date. Also extracts a single leading date-like substring first, since a
# date cell can carry trailing archive annotation text (e.g. a
# "(terminated ...)" note appended after the actual date) that would
# otherwise make every strptime format fail.
_DATE_SUBSTRING_RE = re.compile(
    r"(\d{4}/\d{1,2}/\d{1,2}"        # 2025/01/16
    r"|\d{1,2}/\d{1,2}/\d{2,4}"      # 1/16/1990 or 1/16/90
    r"|\d{4}-\d{1,2}-\d{1,2}"        # 1990-01-16
    r"|[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})"  # January 16, 1990 / Jan. 16, 1990
)


def _normalize_date(raw: str) -> Optional[str]:
    raw = raw.strip()
    match = _DATE_SUBSTRING_RE.search(raw)
    candidate = match.group(1) if match else raw
    candidate = candidate.replace(",", ",").strip()

    for fmt in (
        "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b. %d, %Y", "%b %d %Y",
        "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(candidate, fmt)
        except ValueError:
            continue

        if fmt == "%m/%d/%y":
            # Python's default two-digit-year pivot assumes 00-68 means
            # 2000-2068, which is wrong for this archive: NJ's site covers
            # 1962-present, so a 2-digit year here almost always means the
            # 1900s, not the 2000s. Without this correction, a genuine
            # Hughes-era date like "6/25/65" (1965) parses as 2065 and gets
            # published on a live page with an impossible date.
            if parsed.year > datetime.now().year:
                parsed = parsed.replace(year=parsed.year - 100)

        # General plausibility guard regardless of which format matched:
        # reject anything outside NJ's actual archive range rather than
        # publish a date nobody could have verified. A bad date is worse
        # than no date, since downstream code already treats "no date" as
        # "exclude from matching" - safe by design.
        if not (1900 <= parsed.year <= datetime.now().year + 1):
            return None

        return parsed.strftime("%Y-%m-%d")

    # Leave unparsed rather than guessing; downstream code treats a missing
    # date_signed as "exclude from NOAA date-window matching", which is
    # safer than a silently wrong date.
    return None


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}


def _number_from_words(raw: str) -> Optional[int]:
    """Convert the conventional number words used in NJ signature years."""
    tokens = re.findall(r"[A-Za-z]+", raw.lower())
    total = 0
    current = 0
    used = False
    for token in tokens:
        if token == "and":
            continue
        if token in _NUMBER_WORDS:
            current += _NUMBER_WORDS[token]
            used = True
        elif token == "hundred":
            current = max(current, 1) * 100
            used = True
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
            used = True
    return total + current if used else None


def recover_signature_date(text: str) -> Optional[str]:
    """Recover a date only from the signed GIVEN clause, never a recital.

    This intentionally leaves Whitman EOs 23 and 26 undated: their official
    documents contain blank signature-date fields, so assigning a neighboring
    order's date would be an unsupported guess.
    """
    match = re.search(
        r"\bthis\s+(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+([A-Za-z]+)"
        r"\s+in\s+the\s+Year\s+of\s+Our\s+Lord,?\s+(.{3,90}?)"
        r"(?:,?\s+and\s+of\s+the\s+Independence|[.;])",
        text,
        re.I | re.S,
    )
    if not match:
        return None
    year = _number_from_words(match.group(3))
    if year is None:
        return None
    return _normalize_date(f"{match.group(2)} {match.group(1)}, {year}")


# Recovers a blank archive-table description from the order's own document
# text, the same "pull it from the document since the table doesn't have it"
# approach as recover_signature_date() above. This exists because a lot of
# NJ's archive tables - old /infobank/circular/ index pages especially, but
# also some modern ones - only carry Number and Date columns, with NO
# Subject/Description column at all. When that's the case,
# _extract_order_rows() correctly finds no description cell to use (there
# isn't one), and the row is published downstream as "Untitled action"
# rather than a fabricated guess. Most NJ orders state their own subject
# plainly right after the "EXECUTIVE ORDER No. X" heading and before the
# first "WHEREAS," recital, so that span is a reasonable place to recover it
# from instead of leaving every such row unlabeled.
_TITLE_RE = re.compile(
    r"EXECUTIVE\s+ORDER\s*(?:NOS?\.?|NUMBER)?\s*#?\s*\d+[A-Za-z]?\s*[:\-]?\s*"
    r"(.{10,300}?)\s*(?=WHEREAS\b)",
    re.I | re.S,
)


def recover_title_from_document(text: str) -> Optional[str]:
    """Best-effort recovery of a subject/title from an order's own document
    text, for use only when the archive table itself has no description.

    HONEST CAVEAT: unlike recover_signature_date()'s tightly-anchored GIVEN
    clause (already validated against real NJ documents), this pattern has
    NOT been validated against a live-fetched nj.gov document in this
    sandbox (nj.gov is outside its network allowlist here). Treat this as a
    first draft needing the same live-validation pass the rest of this
    scraper's fixes went through, not a guaranteed fix. If it turns out
    NJ's real documents place the subject somewhere else relative to
    "WHEREAS," this pattern will simply find nothing (returning None) rather
    than extracting the wrong text, since the lookahead requires a literal
    "WHEREAS" to anchor against.
    """
    if not text or len(text.strip()) < 250:
        # Mirrors the low-yield PDF threshold used elsewhere in main(): a
        # document that barely extracted any text at all isn't a reliable
        # place to recover a title from either.
        return None
    match = _TITLE_RE.search(text)
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group(1)).strip(" .:-")
    if len(candidate) < 10:
        return None
    return candidate


def fetch_document_text(order: NJOrder) -> str:
    resp = fetch(order.document_url)
    if resp is None:
        return ""
    if order.document_format == "html":
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.get_text(" ", strip=True)
    # PDF: extract text; caller is responsible for flagging low-yield
    # extractions for OCR/manual review (see main()).
    try:
        import pdfplumber
        import io

        text_parts = []
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return " ".join(text_parts)
    except Exception as exc:  # pragma: no cover - depends on optional lib
        print(f"  WARNING: PDF text extraction failed for {order.document_url}: {exc}",
              file=sys.stderr)
        return ""


def classify_action_type(order: NJOrder) -> str:
    """Fix #7: classify from the archive table's DESCRIPTION only, not the
    order's own document text. A fetched HTML document page frequently
    carries a later-added archive banner ("has been terminated by EO 48")
    on top of the order's original operative text - using document_text
    here previously misclassified originating declarations like EO 37/46/73
    as terminations, when they are the ones BEING terminated, not doing the
    terminating. Relationship extraction still uses document_text (that is
    exactly where the useful "terminated by" reference lives); only this
    classification step is restricted to the table description."""
    text = order.description.lower()
    if re.search(r"terminat|rescind", text):
        return "termination"
    if re.search(r"\b(?:extend|continu|renew)", text):
        return "extension"
    if re.search(r"\b(?:amend|modify|modifies|modified)", text):
        return "amendment"
    return "declaration"


def is_weather_related(order: NJOrder) -> bool:
    text = f"{order.description} {order.document_text}"
    return any(pattern.search(text) for pattern in WEATHER_PATTERNS)


def extract_relationships(order: NJOrder) -> list[dict]:
    """Best-effort relationship extraction from description + document text.
    Returns rows matching the schema recommended in the NJ research:
    source_order_id, target_order_id, relationship_type, relationship_text,
    relationship_source, confidence.

    Fix #5/#6: broadened patterns (see ORDER_REF / RELATIONSHIP_PATTERNS
    above) to catch active AND passive phrasing with multiple targets, plus
    a dedup pass at the end by (source, target, type) - the earlier version
    reported the same EO 46->48 link twice (once from the description,
    once from the document text) because it never deduplicated across the
    two text sources."""
    seen: set[tuple[str, str, str]] = set()
    relationships = []
    combined = [
        ("description", order.description),
        ("document_text", order.document_text),
    ]
    for source_field, text in combined:
        if not text:
            continue

        for terminated_by_match in TERMINATED_BY_PATTERN.finditer(text):
            for target_number in re.findall(r"\d+", terminated_by_match.group(1)):
                src_id = f"NJ-{_gov_code(order)}-EO-{target_number}"
                tgt_id = order.stable_id
                key = (src_id, tgt_id, "terminates")
                if key in seen or src_id == tgt_id:
                    continue
                seen.add(key)
                relationships.append({
                    "source_order_id": src_id,
                    "target_order_id": tgt_id,
                    "relationship_type": "terminates",
                    "relationship_text": terminated_by_match.group(0).strip(),
                    "relationship_source": source_field,
                    "confidence": "medium",
                })

        for rel_type, pattern in RELATIONSHIP_PATTERNS:
            for match in pattern.finditer(text):
                numbers = re.findall(r"\d+", match.group(1))
                for target_number in numbers:
                    if target_number == order.order_number:
                        continue
                    # Fix (round 2, part b): normalize "rescinds" into
                    # "terminates" at creation time. Rescind and terminate
                    # both end an emergency; keeping them as separate
                    # relationship_type values was why EO 48 -> EO 46
                    # survived local dedup as two rows (one "terminates"
                    # from the archive banner, one "rescinds" from EO 48's
                    # own body) even though they describe the same fact.
                    # The original wording is preserved in relationship_text
                    # for anyone reviewing the extraction later.
                    stored_type = "terminates" if rel_type == "rescinds" else rel_type
                    src_id = order.stable_id
                    tgt_id = f"NJ-{_gov_code(order)}-EO-{target_number}"
                    key = (src_id, tgt_id, stored_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    relationships.append({
                        "source_order_id": src_id,
                        "target_order_id": tgt_id,
                        "relationship_type": stored_type,
                        "relationship_text": match.group(0).strip(),
                        "relationship_source": source_field,
                        "confidence": "medium",
                    })
    return relationships


def dedupe_relationships(rows):
    """Global dedup across every order's extracted relationships, keyed by
    (source, target, type). Fix (round 2): the first patch only deduped
    WITHIN a single call to extract_relationships(), so the same pair
    extracted from two different orders' text (e.g. EO 46's "terminated by
    EO 48" banner AND EO 48's own "terminates EO 46" description) still
    produced two rows. This must run once, after combining every order's
    relationships, not per-order."""
    seen: set[tuple[str, str, str]] = set()
    result = []
    for row in rows:
        key = (row["source_order_id"], row["target_order_id"], row["relationship_type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _gov_code(order: NJOrder) -> str:
    return re.sub(r"[^A-Z]", "", order.governor.upper()) or "UNK"


def write_actions_csv(orders: list[NJOrder], path: str) -> None:
    fieldnames = [
        "declaration_id", "state", "governor", "eo_number", "action_type",
        "event_description", "date_signed", "end_date", "weather_related",
        "document_format", "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for order in orders:
            writer.writerow({
                "declaration_id": order.stable_id,
                "state": "NJ",
                "governor": order.governor,
                "eo_number": order.order_number,
                "action_type": order.action_type,
                "event_description": order.description,
                "date_signed": order.date_issued or "",
                "end_date": order.end_date or "",
                "weather_related": order.weather_related,
                "document_format": order.document_format,
                "archive_record_url": order.document_url,
            })


def write_relationships_csv(relationships: list[dict], path: str) -> None:
    fieldnames = [
        "source_order_id", "target_order_id", "relationship_type",
        "relationship_text", "relationship_source", "confidence",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rel in relationships:
            writer.writerow(rel)


def write_join_csv(orders: list[NJOrder], path: str) -> None:
    """Virginia-compatible join file: eo_number, event_description,
    date_signed (+ declaration_id/governor/archive_record_url), limited to
    original weather declarations with a parsed date. Extensions,
    amendments, continuations, and terminations remain in the complete action
    archive but are not treated as new weather incidents for NOAA matching."""
    fieldnames = [
        "declaration_id", "governor", "eo_number", "event_description",
        "date_signed", "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for order in orders:
            if order.action_type != "declaration":
                continue
            if not order.weather_related:
                continue
            if not order.date_issued:
                continue
            writer.writerow({
                "declaration_id": order.stable_id,
                "governor": order.governor,
                "eo_number": order.order_number,
                "event_description": order.description,
                "date_signed": order.date_issued,
                "archive_record_url": order.document_url,
            })


def apply_termination_end_dates(orders: list[NJOrder], relationships: list[dict]) -> None:
    # "rescinds" is normalized to "terminates" at extraction time (see
    # extract_relationships), so checking only "terminates" here is
    # sufficient - this is not a remaining gap, just a note for anyone
    # reading this function in isolation.
    by_id = {o.stable_id: o for o in orders}
    for rel in relationships:
        if rel["relationship_type"] != "terminates":
            continue
        terminator = by_id.get(rel["source_order_id"])
        target = by_id.get(rel["target_order_id"])
        if terminator and target and terminator.date_issued:
            target.end_date = terminator.date_issued


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape New Jersey executive orders")
    parser.add_argument("--actions-out", default="nj_emergency_actions_all.csv")
    parser.add_argument("--relationships-out", default="nj_order_relationships.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    parser.add_argument(
        "--skip-document-fetch", action="store_true",
        help="Skip fetching each order's own document text (faster, but "
             "relationship extraction and weather-relevance detection will "
             "rely on the archive table's description column only).",
    )
    args = parser.parse_args()

    print("New Jersey scraper: discovering administration pages...")
    administrations = discover_administration_pages()
    if not administrations:
        print("ERROR: could not discover any administration pages from "
              f"{MASTER_DIRECTORY_URL}", file=sys.stderr)
        sys.exit(1)
    print(f"  found {len(administrations)} administration page(s)")

    all_orders: list[NJOrder] = []
    for admin_code, governor_label, page_url in administrations:
        print(f"  parsing {governor_label} [{admin_code}] ({page_url})")
        orders = parse_administration_table(admin_code, governor_label, page_url)
        print(f"    {len(orders)} order(s) found")
        all_orders.extend(orders)

    if not args.skip_document_fetch:
        print("New Jersey scraper: fetching document text for classification "
              "(this is the slow step)...")
        # Threshold raised from <50 to <250 chars per validation against
        # real samples: genuine text-selectable PDFs extracted 7,700-20,000+
        # characters, while a scanned document can still leak more than 50
        # characters from headers/metadata alone, so 50 was too loose to
        # reliably catch a bad extraction.
        low_yield_count = 0
        recovered_title_count = 0
        for order in all_orders:
            order.document_text = fetch_document_text(order)
            if not order.date_issued:
                order.date_issued = recover_signature_date(order.document_text)
            if not order.description.strip():
                recovered = recover_title_from_document(order.document_text)
                if recovered:
                    order.description = recovered
                    recovered_title_count += 1
            if order.document_format == "pdf" and len(order.document_text.strip()) < 250:
                low_yield_count += 1
        if recovered_title_count:
            print(f"  Recovered {recovered_title_count} blank archive-table "
                  "description(s) from each order's own document text.")
        if low_yield_count:
            print(f"  WARNING: {low_yield_count} PDF(s) yielded little/no text; "
                  "these likely need OCR or manual review, not automated "
                  "classification.", file=sys.stderr)

    for order in all_orders:
        order.action_type = classify_action_type(order)
        order.weather_related = is_weather_related(order)

    print("New Jersey scraper: extracting order relationships...")
    all_relationships: list[dict] = []
    for order in all_orders:
        all_relationships.extend(extract_relationships(order))
    all_relationships = dedupe_relationships(all_relationships)
    print(f"  {len(all_relationships)} relationship(s) extracted (after global dedup)")

    apply_termination_end_dates(all_orders, all_relationships)

    write_actions_csv(all_orders, args.actions_out)
    write_relationships_csv(all_relationships, args.relationships_out)
    write_join_csv(all_orders, args.join_out)

    weather_count = sum(1 for o in all_orders if o.weather_related)
    join_count = sum(
        1 for o in all_orders
        if o.weather_related and o.action_type == "declaration" and o.date_issued
    )
    print(
        f"\nDone. {len(all_orders)} total order(s), {weather_count} weather-related, "
        f"{join_count} original declarations written to the join file "
        "(excludes extensions, amendments, terminations, and undated rows)."
    )


if __name__ == "__main__":
    main()
