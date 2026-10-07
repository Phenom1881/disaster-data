"""Collect Oregon executive orders from the Governor's official SharePoint list.

Signing dates. Oregon posts each signed order as a scanned image with no text
layer, so the date printed at the end of the order ("Done at Salem, Oregon,
this 7th day of August, 2026.") cannot be read as text. Until 2026-09-27 that
left 251 of Oregon's 252 declarations undated, and an undated declaration
gets no storm search. Now:

1. A date already found on an earlier run is reused (read from the saved
   or_emergency_actions_all.csv), so each PDF is downloaded and read only
   until its date is known, not every week.
2. A PDF that does have a text layer is read as text.
3. Otherwise its last pages are read with OCR (the tesseract program, which
   the Plus workflow installs). OCR has a time limit per run; orders it does
   not reach are read on the next run.

A date is accepted only if it falls in the order's own year (EO 26-24 was
signed in 2026) and is not in the future. Where each date came from is
recorded in the date_source column. Weather declarations still undated after
a run are listed in manual_or_ocr_review.csv with the reason.

Two fallbacks, added 2026-10-07 when 82 of 252 declarations were still
undated after OCR:

4. confirmed_signing_dates.csv: dates checked by hand against the order
   itself, the Governor's newsroom or dated news coverage, with the source.
   These win over everything else and need no download.
5. The date the order was posted to the Governor's list (the SharePoint
   "Created" field, in Pacific time), when OCR cannot read the scan. Orders
   are numbered in signing order, so a posted date is used only when it
   falls between the signing dates of the nearest dated orders before and
   after it that year, and at least one of those exists. A posted date is
   not kept between runs: OCR gets another try each time it is due, and a
   date it reads replaces the posted one.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import io
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import pdfplumber
import requests

STATE = "OR"
ARCHIVE = "https://www.oregon.gov/gov/Pages/executive-orders.aspx"
API = "https://www.oregon.gov/gov/_api/web/lists/GetByTitle(%27Executive%20Orders%27)/items"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)", "Accept": "application/json;odata=verbose"}
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url")
ACTION_FIELDS = ("declaration_id", "state", "governor", "eo_number", "action_kind", "action_type", "event_description", "date_signed", "date_source", "date_checked", "end_date", "weather_related", "source_scope", "document_format", "detail_url", "archive_record_url")
REL_FIELDS = ("source_order_id", "target_order_id", "relationship_type", "relationship_text", "relationship_source", "confidence")
REVIEW_FIELDS = ("declaration_id", "eo_number", "event_description", "archive_record_url", "review_reason")
HAZARD_RE = re.compile(r"\b(?:drought|wildfires?|wildland fires?|fires?|firefighting|conflagration|flood(?:ing)?|heavy rain|rain storms?|hurricanes?|tropical storms?|winter|snow|ice|blizzard|severe storms?|(?:severe|extreme) weather|atmospheric river|high winds?|windstorms?|tornado(?:es)?)\b", re.I)
DECLARATION_RE = re.compile(r"\b(?:determination|declaration|proclamation) of (?:a )?state of (?:drought |winter )?emergency\b|\binvocation of (?:the )?emergency conflagration act\b", re.I)
MODIFIER_RE = re.compile(r"\b(?:amend(?:s|ed|ing|ment)|extend(?:s|ed|ing)|extension|rescind(?:s|ed|ing)?|repeal(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|replacing)\b", re.I)

DATE_FROM_TEXT = "order text"
DATE_FROM_OCR = "order scan (OCR)"
DATE_FROM_POSTED = "date posted to the Governor's order list (approximate)"
DATE_CONFIRMED_PREFIX = "confirmed: "
CONFIRMED_DATES_FILE = Path(__file__).with_name("confirmed_signing_dates.csv")
PACIFIC = ZoneInfo("America/Los_Angeles")

# "this 7th day of August, 2026". OCR output is noisy, so the pattern allows
# the usual misreadings: "lst" for "1st", "2O26" for "2026", "clay" for
# "day", "ot" for "of", a split ordinal ("7t h"). The month is matched
# loosely below ("Auqust", "Septernber").
DAY_OF_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<day>[0-9lIO]{1,2})\s*(?:[a-z]\s?[a-z]?)?\s*[.,]?\s*"
    r"(?:day|dav|doy|clay)\s*(?:of|ot|0f|o\s+f)\s+"
    r"(?P<month>[A-Za-z]{3,10})\.?,?\s*(?P<year>(?:19|2[0O])[0-9O]{2})",
    re.I,
)
# "Done at Salem, Oregon, on August 7, 2026" (month first). Only accepted
# after "done", "dated" or "signed", since order text cites other dates too.
MONTH_FIRST_RE = re.compile(
    r"\b(?:d[o0]ne|dated|signed)\b[^.]{0,80}?\b(?P<month>[A-Za-z]{3,10})\.?\s+"
    r"(?P<day>[0-9lIO]{1,2}),?\s+(?P<year>(?:19|2[0O])[0-9O]{2})",
    re.I,
)
SIGNED_CUE_RE = re.compile(r"\b(?:d[o0]ne|dated|signed)\b", re.I)
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december")
_DIGIT_FIXES = str.maketrans({"l": "1", "I": "1", "i": "1", "L": "1", "O": "0", "o": "0"})

# OCR settings. Each PDF's last pages are tried, newest page first, with up
# to three image treatments; most scans read on the first try.
TESSERACT = shutil.which("tesseract")
OCR_LAST_PAGES = 3
OCR_PASSES = ((300, "median"), (300, "threshold"), (200, "plain"))
OCR_BUDGET_SECONDS = 15 * 60
_PDFIUM_LOCK = threading.Lock()   # pdfium is not safe to call from two threads at once

REVIEW_REASONS = {
    "download": "The order PDF could not be downloaded on this run.",
    "no_ocr": "The order PDF is a scan with no text layer, and OCR was not available on this run.",
    "budget": "The order PDF is a scan; OCR ran out of time on this run and continues on the next.",
    "ocr_error": "The order PDF is a scan and could not be converted to an image for OCR.",
    "not_found": "The order PDF is a scan and OCR could not read a signing date in its last pages.",
    "recent_miss": "The order PDF is a scan and OCR could not read a signing date in its last pages; it is tried again every four weeks.",
}


@dataclass
class Action:
    year: int
    number: str
    description: str
    pdf_url: str
    created: str = ""
    text: str = ""
    signed: str = ""
    date_source: str = ""
    date_note: str = ""
    date_checked: str = ""

    @property
    def eo_number(self) -> str:
        return f"{self.year % 100:02d}-{int(self.number):02d}"

    @property
    def stable_id(self) -> str:
        suffix = "-AMENDED" if "amended" in self.pdf_url.lower() or self.description.lower().startswith("(amended)") else ""
        return f"OR-EO-{self.eo_number}{suffix}"


# ---------------------------------------------------------------- signing date

def _as_date(day: str, month: str, year: str, order_year: int | None, today: date) -> date | None:
    found = difflib.get_close_matches(month.lower(), MONTH_NAMES, n=1, cutoff=0.75)
    if not found:
        return None
    try:
        value = date(int(year.translate(_DIGIT_FIXES)), MONTH_NAMES.index(found[0]) + 1,
                     int(day.translate(_DIGIT_FIXES)))
    except ValueError:
        return None
    if order_year and value.year != order_year:
        return None
    if value > today:
        return None
    return value


def find_signing_date(text: str, order_year: int | None = None, today: date | None = None) -> str:
    """The signing date in an order's text or OCR output, as YYYY-MM-DD, or ""
    if none is found. A date right after "Done at ..." wins; otherwise the
    last date in the text, since the signing line ends the order."""
    today = today or date.today()
    text = re.sub(r"\s+", " ", text or "")
    found = []
    for match in DAY_OF_RE.finditer(text):
        value = _as_date(match.group("day"), match.group("month"), match.group("year"), order_year, today)
        if value:
            cued = bool(SIGNED_CUE_RE.search(text[max(0, match.start() - 120):match.start()]))
            found.append((cued, match.start(), value))
    for match in MONTH_FIRST_RE.finditer(text):
        value = _as_date(match.group("day"), match.group("month"), match.group("year"), order_year, today)
        if value:
            found.append((True, match.start("month"), value))
    if not found:
        return ""
    cued = [item for item in found if item[0]]
    return max(cued or found, key=lambda item: item[1])[2].isoformat()


def pdf_text(content: bytes) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return re.sub(r"\s+", " ", " ".join((page.extract_text() or "") for page in pdf.pages))


def render_pages(content: bytes, dpi: int, last: int = OCR_LAST_PAGES) -> list:
    """Grayscale images of the last pages, newest page first."""
    import pypdfium2 as pdfium
    images = []
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(content)
        try:
            count = len(document)
            for index in range(count - 1, max(count - 1 - last, -1), -1):
                page = document[index]
                try:
                    images.append(page.render(scale=dpi / 72, grayscale=True).to_pil().copy())
                finally:
                    page.close()
        finally:
            document.close()
    return images


def prepare(image, treatment: str):
    from PIL import ImageFilter
    if treatment == "plain":
        return image
    cleaned = image.convert("L").filter(ImageFilter.MedianFilter(3))   # scanner speckle
    if treatment == "threshold":
        cleaned = cleaned.point(lambda value: 255 if value > 128 else 0)
    return cleaned


def run_tesseract(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    try:
        result = subprocess.run(
            [TESSERACT, "stdin", "stdout", "--psm", "3"], input=buffer.getvalue(),
            capture_output=True, timeout=120, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""


def ocr_signing_date(content: bytes, order_year: int | None, today: date | None = None,
                     deadline: float | None = None) -> tuple[str, str, str]:
    """Read a scanned order's signing date with OCR. Returns (date, text,
    note); note is "" when a date was found, else why not."""
    today = today or date.today()
    texts = []
    for dpi, treatment in OCR_PASSES:
        try:
            images = render_pages(content, dpi)
        except Exception:
            return "", " ".join(texts), "ocr_error"
        for image in images:
            if deadline is not None and time.monotonic() > deadline:
                return "", " ".join(texts), "budget"
            text = run_tesseract(prepare(image, treatment))
            texts.append(text)
            signed = find_signing_date(text, order_year, today)
            if signed:
                return signed, text, ""
    return "", " ".join(texts), "not_found"


# ---------------------------------------------------------------- collection

def load_saved_dates(path) -> dict[str, tuple[str, str]]:
    """Signing dates found on earlier runs, by declaration id."""
    try:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return {}
    return {row["declaration_id"]: (row.get("date_signed") or "", row.get("date_source") or "")
            for row in rows if row.get("declaration_id") and row.get("date_signed")}


# A scan OCR could not date is tried again after this many days rather than
# every week. On 2026-10-01 re-reading 132 such scans took about 8 minutes
# of a run that came within 6 minutes of the workflow's time limit.
RECHECK_AFTER_DAYS = 28


def load_checked_dates(path) -> dict[str, str]:
    """When each order's scan was last read by OCR without finding a date,
    for orders still undated or dated only by when they were posted."""
    try:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return {}
    checked = {}
    for row in rows:
        if row.get("declaration_id") and row.get("date_checked") and (
                not row.get("date_signed") or row.get("date_source") == DATE_FROM_POSTED):
            checked[row["declaration_id"]] = row["date_checked"]
    return checked


def load_recent_misses(path, today: date) -> set[str]:
    """Orders whose scan was read without finding a date in the last
    RECHECK_AFTER_DAYS days."""
    recent = set()
    for declaration_id, value in load_checked_dates(path).items():
        try:
            checked = date.fromisoformat(value)
        except ValueError:
            continue
        if (today - checked).days < RECHECK_AFTER_DAYS:
            recent.add(declaration_id)
    return recent


def load_confirmed_dates(path=CONFIRMED_DATES_FILE) -> dict[str, tuple[str, str]]:
    """Hand-checked signing dates by declaration id: (date, date_source)."""
    try:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return {}
    confirmed = {}
    for row in rows:
        try:
            date.fromisoformat(row.get("date_signed") or "")
        except ValueError:
            continue
        confirmed[row["declaration_id"]] = (row["date_signed"], DATE_CONFIRMED_PREFIX + (row.get("source_kind") or "hand check"))
    return confirmed


def posted_date(created: str) -> str:
    """The SharePoint Created timestamp ("2026-08-07T22:03:19Z") as a Pacific
    calendar date, or "" if it cannot be read."""
    try:
        moment = datetime.fromisoformat((created or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone(PACIFIC).date().isoformat()


def fill_posted_dates(actions: list[Action], today: date) -> int:
    """Date still-undated orders by when they were posted, where the posted
    date fits between the nearest dated orders of the same year (see the
    module notes). Returns how many were dated this way."""
    by_year: dict[int, list[Action]] = {}
    for action in actions:
        by_year.setdefault(action.year, []).append(action)
    filled = 0
    for year, group in by_year.items():
        group = sorted(group, key=lambda a: int(a.number))
        dated = [(int(a.number), a.signed) for a in group if a.signed and a.date_source != DATE_FROM_POSTED]
        for action in group:
            if action.signed or not (DECLARATION_RE.search(action.description) or MODIFIER_RE.search(action.description)):
                continue
            posted = posted_date(action.created)
            if not posted or posted[:4] != str(year) or posted > today.isoformat():
                continue
            number = int(action.number)
            before = [signed for n, signed in dated if n < number]
            after = [signed for n, signed in dated if n > number]
            low, high = (max(before) if before else None), (min(after) if after else None)
            if low is None and high is None:
                continue
            if (low and posted < low) or (high and posted > high):
                continue
            action.signed, action.date_source = posted, DATE_FROM_POSTED
            filled += 1
    return filled


def list_orders(session: requests.Session) -> list[Action]:
    params = {"$top": "5000", "$expand": "File", "$select": "Title,Document_x0020_Description,Year,Number,Order0,Created,File/ServerRelativeUrl,File/Name"}
    response = session.get(API, params=params, headers=HEADERS, timeout=60)
    response.raise_for_status()
    actions = []
    for item in response.json()["d"]["results"]:
        file_data = item.get("File") or {}
        relative = file_data.get("ServerRelativeUrl", "")
        if not relative:
            continue
        # The SharePoint Year/Number columns contain a handful of cataloging
        # errors (for example EO 20-50 was once numbered 59 in the list).
        # The official PDF filename and displayed EO title agree, so prefer
        # the filename's order number and fall back to the list fields.
        filename_match = re.search(r"(?i)(?:^|/)eo[_-]?(\d{2})[-_]?(\d{1,2})(?:\D|$)", relative)
        try:
            if filename_match:
                year, number = 2000 + int(filename_match.group(1)), str(int(filename_match.group(2)))
            else:
                year, number = int(item.get("Year")), str(int(item.get("Number")))
        except (TypeError, ValueError):
            continue
        if year < 2000:
            continue
        actions.append(Action(year, number, re.sub(r"\s+", " ", item.get("Document_x0020_Description") or item.get("Title") or "").strip(), urljoin("https://www.oregon.gov", relative), item.get("Created", "")))
    # One row per order, keeping the fuller description, before any PDF is
    # fetched, so a list entry that appears twice is not read twice.
    unique: dict[str, Action] = {}
    for action in actions:
        previous = unique.get(action.stable_id)
        if not previous or len(action.description) > len(previous.description):
            unique[action.stable_id] = action
    return list(unique.values())


def collect(session: requests.Session | None = None, saved: dict | None = None,
            today: date | None = None, ocr_budget: float = OCR_BUDGET_SECONDS,
            recent_misses: set | None = None, confirmed: dict | None = None,
            checked: dict | None = None) -> list[Action]:
    session = session or requests.Session()
    saved = saved or {}
    confirmed = confirmed or {}
    checked = checked or {}
    recent_misses = recent_misses or set()
    today = today or date.today()
    ocr_available = bool(TESSERACT)
    deadline = time.monotonic() + ocr_budget
    actions = list_orders(session)

    counts: dict[str, int] = {}
    failures: dict[str, int] = {}
    lock = threading.Lock()

    def count(key: str, table: dict | None = None) -> None:
        with lock:
            target = counts if table is None else table
            target[key] = target.get(key, 0) + 1

    def enrich(action: Action) -> Action:
        if not (DECLARATION_RE.search(action.description) or MODIFIER_RE.search(action.description)):
            return action
        signed, source = confirmed.get(action.stable_id, ("", ""))
        if signed[:4] == str(action.year):
            action.signed, action.date_source = signed, source
            count("confirmed")
            return action
        signed, source = saved.get(action.stable_id, ("", ""))
        # A posted date is only a stand-in until OCR reads the order, and a
        # hand-confirmed date that has since been removed is not kept either.
        if signed[:4] == str(action.year) and source != DATE_FROM_POSTED and not source.startswith(DATE_CONFIRMED_PREFIX):
            action.signed, action.date_source = signed, source
            count("saved")
            return action
        if action.stable_id in recent_misses:
            # Keep the day it was last read, so it is retried four weeks
            # after that read rather than the week after this run.
            action.date_checked = checked.get(action.stable_id, "")
            action.date_note = "recent_miss"
            count("recent_miss")
            return action
        content = None
        for attempt in (1, 2):
            try:
                response = session.get(action.pdf_url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
                response.raise_for_status()
                content = response.content
                break
            except Exception as exc:
                if attempt == 2:
                    cause = type(exc).__name__
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    count(f"{cause} {status}" if status else cause, failures)
                    action.date_note = "download"
                    return action
        try:
            action.text = pdf_text(content)
        except Exception:
            action.text = ""
        action.signed = find_signing_date(action.text, action.year, today)
        if action.signed:
            action.date_source = DATE_FROM_TEXT
            count("text")
            return action
        if not ocr_available:
            action.date_note = "no_ocr"
            count("no_ocr")
            return action
        if time.monotonic() > deadline:
            action.date_note = "budget"
            count("budget")
            return action
        try:
            signed, ocr_text, note = ocr_signing_date(content, action.year, today, deadline)
        except Exception:
            signed, ocr_text, note = "", "", "ocr_error"
        action.text = action.text or ocr_text
        if signed:
            action.signed, action.date_source = signed, DATE_FROM_OCR
            count("ocr")
        else:
            action.date_note = note
            count(note)
            if note == "not_found":
                action.date_checked = today.isoformat()
        return action

    with ThreadPoolExecutor(max_workers=4) as pool:
        actions = list(pool.map(enrich, actions))
    counts["posted"] = fill_posted_dates(actions, today)
    print(date_report(counts, failures))
    return sorted(actions, key=lambda x: (x.signed, x.year, int(x.number)), reverse=True)


def date_report(counts: dict, failures: dict) -> str:
    parts = [
        (counts.get("confirmed", 0), "from confirmed_signing_dates.csv"),
        (counts.get("saved", 0), "kept from earlier runs"),
        (counts.get("text", 0), "read from the PDF text"),
        (counts.get("ocr", 0), "read from the scan by OCR"),
        (counts.get("not_found", 0), "not found by OCR"),
        (counts.get("recent_miss", 0), "not found by OCR in the last four weeks, not retried yet"),
        (counts.get("ocr_error", 0), "not readable as an image"),
        (counts.get("budget", 0), "left for the next run (OCR time limit)"),
        (counts.get("no_ocr", 0), "not tried because OCR is not installed"),
        (counts.get("posted", 0), "of those undated, dated by when they were posted"),
    ]
    downloads = sum(failures.values())
    text = "; ".join(f"{number} {label}" for number, label in parts if number)
    if downloads:
        causes = ", ".join(f"{cause} x{number}" for cause, number in sorted(failures.items()))
        text += f"{'; ' if text else ''}{downloads} PDFs not downloaded ({causes})"
    return f"Oregon signing dates: {text or 'no orders needed a date'}"


# ---------------------------------------------------------------- output

def governor(action: Action) -> str:
    marker = action.signed or f"{action.year:04d}-12-31"
    if marker >= "2023-01-09": return "Tina Kotek"
    if marker >= "2015-02-18": return "Kate Brown"
    if marker >= "2011-01-10": return "John Kitzhaber"
    return "Ted Kulongoski"


def classify(action: Action) -> str:
    match = MODIFIER_RE.search(action.description)
    if match:
        word = match.group(0).lower()
        return "termination" if word.startswith(("rescind", "terminat", "repeal")) else "extension" if word.startswith("extend") else "amendment"
    return "declaration" if DECLARATION_RE.search(action.description) else "administrative"


def write_csv(path, fields, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def write_outputs(actions, actions_out, relationships_out, join_out, review_out=None) -> None:
    rows, relationships, joins, review = [], [], [], []
    known = {a.eo_number: a.stable_id for a in actions if "AMENDED" not in a.stable_id}
    for action in actions:
        kind = classify(action)
        weather = bool(HAZARD_RE.search(action.description))
        row = {"declaration_id": action.stable_id, "state": STATE, "governor": governor(action), "eo_number": action.eo_number, "action_kind": "emergency_declaration" if kind != "administrative" else "executive_order", "action_type": kind, "event_description": action.description, "date_signed": action.signed, "date_source": action.date_source if action.signed else "", "date_checked": action.date_checked, "end_date": "", "weather_related": str(kind == "declaration" and weather).lower(), "source_scope": "oregon_governor_executive_order_list", "document_format": "pdf", "detail_url": action.pdf_url, "archive_record_url": action.pdf_url}
        rows.append(row)
        if kind in {"amendment", "extension", "termination"}:
            relation = {"amendment": "amends", "extension": "extends", "termination": "terminates"}[kind]
            for target in re.findall(r"(?:Executive Order|EO)(?: No\.?)?\s*(\d{2}-\d{2})", f"{action.description} {action.text[:1200]}", re.I):
                if target != action.eo_number and target in known:
                    relationships.append({"source_order_id": action.stable_id, "target_order_id": known[target], "relationship_type": relation, "relationship_text": target, "relationship_source": action.pdf_url, "confidence": "high"})
        if kind == "declaration" and weather:
            joins.append({field: row[field] for field in JOIN_FIELDS})
            if not action.signed:
                review.append({"declaration_id": action.stable_id, "eo_number": action.eo_number, "event_description": action.description, "archive_record_url": action.pdf_url, "review_reason": REVIEW_REASONS.get(action.date_note, "No signing date was found for this order.")})
    write_csv(actions_out, ACTION_FIELDS, rows); write_csv(relationships_out, REL_FIELDS, relationships); write_csv(join_out, JOIN_FIELDS, joins)
    if review_out:
        write_csv(review_out, REVIEW_FIELDS, review)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    parser.add_argument("--review-out", help="list of weather declarations still undated, with the reason")
    args = parser.parse_args()
    saved = load_saved_dates(args.actions_out)
    misses = load_recent_misses(args.actions_out, date.today())
    write_outputs(collect(saved=saved, recent_misses=misses, confirmed=load_confirmed_dates(),
                          checked=load_checked_dates(args.actions_out)), args.actions_out, args.relationships_out, args.join_out, args.review_out)


if __name__ == "__main__": main()
