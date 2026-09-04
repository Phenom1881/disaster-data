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

# Weather/emergency keywords used to decide whether an order is in scope.
# Broad on purpose: false positives get filtered later by a human reviewing
# nj_emergency_actions_all.csv; false negatives (missing a real weather EO)
# are the worse failure mode, so this list errs wide.
WEATHER_KEYWORDS = [
    "emergency", "disaster", "storm", "winter", "snow", "ice", "flood",
    "flooding", "hurricane", "tropical", "wind", "tornado", "drought",
    "wildfire", "fire danger", "extreme cold", "extreme heat", "heat",
    "coastal", "nor'easter", "noreaster", "state of emergency",
]

# Matches "Executive Order", "E.O.", or bare "Order", each optionally
# followed by "No./Nos./Number", then one or more comma/and-separated
# numbers. Fix #5: earlier version required "executive order" + "no." both
# present in a fairly rigid order, which missed real phrasings like
# "Order No. 44" (no "executive") and "Executive Order Number 37" (spelled
# out "Number", not "No."). This fragment is reused for both the active
# ("X terminates ORDER_REF") and passive ("ORDER_REF is/are terminated")
# directions below.
ORDER_REF = r"(?:executive\s+order|e\.?o\.?|order)s?\s*(?:nos?\.?|number)?\s*#?\s*((?:\d+\s*(?:,|&|and)?\s*)+)"

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
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
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
            description = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""

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

            date_cell_text = cells[2].get_text(strip=True) if len(cells) > 2 else None
            date_issued = _normalize_date(date_cell_text) if date_cell_text else None

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
            return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Leave unparsed rather than guessing; downstream code treats a missing
    # date_signed as "exclude from NOAA date-window matching", which is
    # safer than a silently wrong date.
    return None


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
    if re.search(r"extend", text):
        return "extension"
    if re.search(r"amend", text):
        return "amendment"
    return "declaration"


def is_weather_related(order: NJOrder) -> bool:
    text = f"{order.description} {order.document_text}".lower()
    return any(kw in text for kw in WEATHER_KEYWORDS)


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

        for target_number in re.findall(r"\d+", "".join(
            m.group(1) for m in TERMINATED_BY_PATTERN.finditer(text)
        )):
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
                "relationship_text": "(terminated-by reference)",
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
    weather-related, non-termination orders with a parsed date, since a
    termination has no storm to match against and an undated row can't be
    windowed."""
    fieldnames = [
        "declaration_id", "governor", "eo_number", "event_description",
        "date_signed", "archive_record_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for order in orders:
            if order.action_type == "termination":
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
        for order in all_orders:
            order.document_text = fetch_document_text(order)
            if order.document_format == "pdf" and len(order.document_text.strip()) < 250:
                low_yield_count += 1
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
        if o.weather_related and o.action_type != "termination" and o.date_issued
    )
    print(
        f"\nDone. {len(all_orders)} total order(s), {weather_count} weather-related, "
        f"{join_count} written to the join file (excludes terminations and undated rows)."
    )


if __name__ == "__main__":
    main()
