"""Collect emergency-relevant New Mexico executive orders from the Governor archive."""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

try:
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError:
    pytesseract = None
    convert_from_bytes = None

CURRENT_URL = "https://www.governor.state.nm.us/about-the-governor/executive-orders/"
ARCHIVE_URL = "https://www.governor.state.nm.us/about-the-governor/executive-orders/executive-orders-archive/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 90
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
HAZARD_RE = re.compile(r"\b(wildfires?|forest fires?|fire emergency|flood(?:s|ing)?|flash flood(?:s|ing)?|severe (?:storms?|weather)|winter storms?|winter weather|snow(?:fall)?|ice|freez(?:e|ing)|drought|extreme heat|tornado(?:es)?|hail|heavy rain(?:fall)?|high winds?|mudslides?|debris flows?|monsoon|hurricanes?|tropical storms?)\b", re.I)
RELEVANT_RE = re.compile(r"\b(state of emergency|public health emergency|disaster|emergency declaration|emergency response|emergency funds?|national guard)\b", re.I)
MODIFIER_RE = re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|revok(?:e|es|ed|ing))\b", re.I)
OPERATIONAL_RE = re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|transportation waiver|suspension of regulations?)\b", re.I)
HAZARD_OVERRIDES = {}

# Same lesson learned from Indiana on 2026-09-17, applied here before this
# scraper was ever run for real: taking the LAST date-shaped string in a
# document is not safe, because a WHEREAS clause can describe an earlier
# event date in the same year as the order's own signing date. Anchoring
# to the actual attestation language first, and only falling back to the
# old whole-document search when no anchor is found, avoids that trap.
#
# CONFIRMED WRONG on a real New Mexico order the same day (EO 2020-077):
# the anchor list above only covered Indiana's phrasing ("GIVEN under my
# hand" / "IN TESTIMONY WHEREOF" / "hereunto set my hand"). New Mexico's
# real attestation line reads "WITNESS MY HAND AND THE GREAT SEAL OF THE
# STATE OF NEW MEXICO", which matched none of those, so the anchor search
# silently found nothing and fell back to the whole-document search --
# which is exactly what returned the wrong WHEREAS-clause date. Added
# "WITNESS my hand" below. This is not guaranteed complete: New Mexico's
# archive spans 2000-present across multiple governors, and different
# administrations may phrase their attestation differently. A missed
# phrasing fails safe (falls back to the old behavior, no worse than
# before), but does mean a wrong date is still possible on an
# administration/era not yet seen. Spot-check across eras, not just one.
SIGNATURE_ANCHOR_RE = re.compile(
    r"(?:IN\s+TESTIMONY\s+WHEREOF|GIVEN\s+under\s+my\s+hand|hereunto\s+set\s+my\s+hand|"
    r"WITNESS\s+my\s+hand)",
    re.IGNORECASE,
)


def _date_candidates(text, year):
    """Both date shapes New Mexico's real orders use, restricted to the
    EO's own numbered year. The day-of-month suffix ([^\\d\\s]{0,3} rather
    than a fixed st|nd|rd|th list) is deliberately permissive: confirmed
    against a real Indiana OCR output on 2026-09-17 that Tesseract can
    misread a small superscript "th" as "%", which a fixed suffix list
    would silently miss. New Mexico needs OCR for 1,205 of its 1,206
    records, so this same artifact is at least as likely to show up here.
    """
    month = r"January|February|March|April|May|June|July|August|September|October|November|December"
    candidates = []
    for match in re.finditer(rf"\b({month})\s+(\d{{1,2}})[^\d\s]{{0,3}},?\s+({year})\b", text, re.I):
        candidates.append((match.start(), match.group(1), match.group(2), match.group(3)))
    for match in re.finditer(rf"\b(\d{{1,2}})[^\d\s]{{0,3}}\s+day\s+of\s+({month})[,]?\s+({year})\b", text, re.I):
        candidates.append((match.start(), match.group(2), match.group(1), match.group(3)))
    return candidates


@dataclass(frozen=True)
class Action:
    number: str
    title: str
    date: str
    url: str
    text: str
    extraction_ok: bool = True
    retrieval_ok: bool = True
    via_ocr: bool = False

    @property
    def stable_id(self):
        return "NM-" + self.number


def get(url):
    last = None
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            if attempt < 3:
                time.sleep(0.5 * (attempt + 1))
    raise last


def parse_index(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for anchor in soup.select("a[href]"):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        match = re.search(r"Executive Order\s+(20\d{2}-\d{3})\b", label, re.I)
        if match and ".pdf" in anchor.get("href", "").lower():
            href = anchor["href"]
            # The migrated index prepends /assets/ to legacy absolute-host paths.
            # Those rewritten links 404; the same official files remain live on
            # the Governor's canonical non-www WordPress host.
            if href.startswith("/assets/www.governor.state.nm.us/"):
                href = "https://governor.state.nm.us/" + href.split("/assets/www.governor.state.nm.us/", 1)[1]
            found.append((match.group(1), urljoin(base_url, href)))
    return found


def _ocr_pdf_text(data: bytes, max_pages: int = 3, dpi: int = 300) -> str:
    """Second attempt at getting text out of a PDF, used ONLY when native
    pdfplumber extraction already returned nothing. New Mexico's archive is
    1,206 records, 1,205 of which are scanned images with no text layer
    (confirmed directly against the live source, 2026-09-16); this is the
    single largest reason so few of them currently reach the join file.

    Never guesses: returns "" if OCR isn't installed, the PDF can't be
    rendered, or OCR itself produces nothing. A blank result here flows
    through exactly the same way a blank native-extraction result always
    has -- the record stays in actions_out for visibility but is excluded
    from the join, same as before this function existed.
    """
    if pytesseract is None or convert_from_bytes is None:
        return ""
    try:
        images = convert_from_bytes(data, dpi=dpi, first_page=1, last_page=max_pages)
    except Exception as exc:
        print(f"  OCR fallback: could not render PDF to images: {exc}", file=sys.stderr)
        return ""
    parts = []
    for image in images:
        try:
            parts.append(pytesseract.image_to_string(image))
        except Exception as exc:
            print(f"  OCR fallback: tesseract failed on a page: {exc}", file=sys.stderr)
    return re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()


def extract_pdf(data):
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if text:
            return text, True, False
    except Exception:
        pass
    # Native extraction found no text layer (scanned image) or failed
    # outright. Try OCR before giving up. This is the ONLY new behavior;
    # everything above this line is unchanged from before OCR was added.
    ocr_text = _ocr_pdf_text(data)
    return ocr_text, bool(ocr_text), bool(ocr_text)


def extract_title(text, number):
    compact = re.sub(r"\s+", " ", text)
    start = re.search(rf"(?:EXECUTIVE\s+ORDER(?:\s+NO\.?)?\s*)?{re.escape(number)}", compact, re.I)
    tail = compact[start.end():] if start else compact[:1600]
    tail = re.split(r"\bWHEREAS\b", tail, maxsplit=1, flags=re.I)[0]
    tail = re.sub(r"^(?:STATE OF NEW MEXICO|OFFICE OF THE GOVERNOR|MICHELLE LUJAN GRISHAM|GOVERNOR|EXECUTIVE ORDER)\s*", "", tail, flags=re.I)
    tail = re.sub(r"\s+", " ", tail).strip(" :-\n")
    return tail[:500] or f"Executive Order {number} (text unavailable)"


def extract_date(text, number):
    year = number[:4]
    anchor = SIGNATURE_ANCHOR_RE.search(text)
    if anchor:
        # Multi-column signature blocks (the Secretary of State's attest
        # column next to the Governor's own signature column) get flattened
        # by OCR in raster/line order, which can put the date-bearing line
        # BEFORE the anchor phrase in the extracted text even though both
        # belong to the same signature block. Confirmed directly against
        # EO 2020-077's real OCR output on 2026-09-17: "DONE AT THE
        # EXECUTIVE OFFICE THIS [5]TH DAY OF NOVEMBER 2020" appears before
        # "WITNESS MY HAND" because they sit in side-by-side columns.
        # Searching a window around the anchor, not only after it, catches
        # this.
        window_start = max(0, anchor.start() - 400)
        window_end = min(len(text), anchor.end() + 400)
        windowed = _date_candidates(text[window_start:window_end], year)
        if windowed:
            anchor_pos_in_window = anchor.start() - window_start
            _, name, day, yr = min(windowed, key=lambda c: abs(c[0] - anchor_pos_in_window))
            return datetime.strptime(f"{name} {day} {yr}", "%B %d %Y").strftime("%Y-%m-%d")
        # An anchor was found but nothing matched within the window around
        # it. Deliberately NOT falling back to a whole-document search here:
        # that fallback is exactly what produced the wrong WHEREAS-clause
        # date on this same document before this fix. Once a real signature
        # block has been located, a missing date near it (e.g. "5TH"
        # misread by OCR as "STH", a digit-to-letter confusion this code
        # will not try to guess-correct) is far more likely a genuine OCR
        # failure than a sign the real date is elsewhere in the document.
        # An honest blank here is correct; a fabricated or wrong-clause
        # date is not.
        return ""
    # No attestation anchor found anywhere in the document -- the EO's own
    # year-filtered candidates are the only signal left. This whole-document
    # fallback is unavoidable when there is truly no anchor, but is never
    # reached for any document where an anchor DOES exist, which is what
    # avoids the exact trap found in EO 2020-077 (and Indiana's EO 22-15 /
    # EO 24-8 before that).
    candidates = _date_candidates(text, year)
    if not candidates:
        return ""
    _, name, day, yr = max(candidates)  # last match in the document (original behavior)
    return datetime.strptime(f"{name} {day} {yr}", "%B %d %Y").strftime("%Y-%m-%d")


def parse_document(number, url):
    try:
        response = get(url)
        retrieval_ok = response.content.startswith(b"%PDF")
        text, ok, via_ocr = extract_pdf(response.content) if retrieval_ok else ("", False, False)
    except requests.RequestException:
        text, ok, via_ocr, retrieval_ok = "", False, False, False
    return Action(number, extract_title(text, number), extract_date(text, number), url, text, ok, retrieval_ok, via_ocr)


def collect():
    pairs = []
    for source in (CURRENT_URL, ARCHIVE_URL):
        pairs.extend(parse_index(get(source).text, source))
    unique = dict(pairs)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda pair: parse_document(*pair), unique.items()))
    return sorted(records, key=lambda item: item.number, reverse=True)


def classify(action):
    if not action.extraction_ok:
        return "unclassified"
    evidence = action.title + " " + action.text
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "terminat", "revok")):
            return "termination"
        if word.startswith(("renew", "extend")):
            return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title):
        return "administrative"
    if re.search(r"^\s*DECLAR(?:ING|ATION OF)\b.{0,180}\b(?:STATE OF EMERGENCY|DISASTER|AN EMERGENCY)\b", action.title, re.I):
        return "declaration"
    return "administrative"


def relationships(actions):
    known = {item.number for item in actions}
    rows = []
    for action in actions:
        kind = classify(action)
        if kind not in {"amendment", "extension", "termination"}:
            continue
        for target in sorted(set(re.findall(r"\b20\d{2}-\d{3}\b", action.title + " " + action.text)) - {action.number}):
            if target in known:
                rows.append({"source_order_id": action.stable_id, "target_order_id": "NM-" + target, "relationship_type": kind, "relationship_text": action.title, "relationship_source": action.url, "confidence": "high"})
    return rows


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(actions, actions_out, relationships_out, join_out):
    rows, joins = [], []
    for action in actions:
        evidence = action.title + " " + action.text
        kind = classify(action)
        relevant = bool(RELEVANT_RE.search(evidence) or HAZARD_RE.search(evidence))
        if not relevant and action.extraction_ok:
            continue
        weather = kind == "declaration" and bool(HAZARD_RE.search(evidence))
        if action.extraction_ok and action.via_ocr:
            document_format = "pdf_ocr"
        elif action.extraction_ok:
            document_format = "pdf"
        elif action.retrieval_ok:
            document_format = "pdf_ocr_required"
        else:
            document_format = "pdf_unavailable"
        row = {"declaration_id": action.stable_id, "state": "NM", "governor": "Michelle Lujan Grisham", "eo_number": action.number, "action_kind": "executive_order", "action_type": kind, "event_description": action.title, "date_signed": action.date, "end_date": "", "weather_related": str(weather).lower(), "source_scope": "new_mexico_governor_executive_orders_2019_present", "document_format": document_format, "detail_url": action.url, "archive_record_url": action.url}
        rows.append(row)
        if weather and kind == "declaration" and action.date:
            joins.append({field: row[field] for field in JOIN_FIELDS})
    write_csv(actions_out, ACTION_FIELDS, rows)
    write_csv(relationships_out, REL_FIELDS, relationships(actions))
    write_csv(join_out, JOIN_FIELDS, joins)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    actions = collect()
    write_outputs(actions, args.actions_out, args.relationships_out, args.join_out)
    n_ocr = sum(1 for a in actions if a.via_ocr)
    n_still_blocked = sum(1 for a in actions if not a.extraction_ok and a.retrieval_ok)
    print(f"New Mexico: {len(actions)} actions scraped, {n_ocr} recovered via OCR, {n_still_blocked} still image-only with no usable text.")


if __name__ == "__main__":
    main()
