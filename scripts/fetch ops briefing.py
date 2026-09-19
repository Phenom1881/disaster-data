#!/usr/bin/env python3
"""
Fetch FEMA Daily Operations Briefing PDFs and archive them for DisasterData.IO.

Source order:
  1. Data Liberation Project public FEMA Daily Ops RSS feed
  2. Optional private kill-the-newsletter RSS feed via KTN_FEED_URL
  3. Disaster Center fixed PDF mirror as a last-resort fallback

The script never trusts a source date by itself. Every downloaded PDF is
opened and its briefing date is read from page 1 before it is archived.

Behavior:
  - Archives every missing valid briefing currently visible in the RSS source.
  - Keeps archive/ops-briefings/history.csv as the durable local record.
  - Treats an already-archived current briefing as a healthy success.
  - Tries fallback sources when the preferred source is unavailable or stale.
  - Returns a non-zero exit code if every configured source is unavailable,
    invalid, or stale. This prevents GitHub Actions from showing a false green
    run while the archive has silently stopped updating.

Environment variables:
  DD_OUT
      Root output directory. Default: archive

  DLP_FEED_URL
      Override the Data Liberation Project public RSS feed.

  KTN_FEED_URL
      Optional private kill-the-newsletter feed URL. Store this only as a
      GitHub Actions secret. Do not commit it to the repository.

  OPS_PDF_URL
      Override the Disaster Center fallback PDF URL.

  STALE_MAX_DAYS
      Maximum age allowed for the newest briefing before a source is treated
      as stale. Default: 3.

  REQUEST_TIMEOUT
      HTTP timeout in seconds. Default: 45.
"""

from __future__ import annotations

import csv
import html
import io
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader


DLP_FEED_URL = os.environ.get(
    "DLP_FEED_URL",
    "https://raw.githubusercontent.com/data-liberation-project/"
    "fema-daily-ops-email-to-rss/main/output/feed.rss",
)

KTN_FEED_URL = os.environ.get("KTN_FEED_URL", "").strip()

DISASTER_CENTER_URL = os.environ.get(
    "OPS_PDF_URL",
    "https://disastercenter.com/FEMA%20Daily%20Operation%20Brief.pdf",
)

OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
ARCHIVE_DIR = OUT_ROOT / "ops-briefings"
HISTORY_CSV = ARCHIVE_DIR / "history.csv"

HISTORY_FIELDS = ["date", "filename", "source_url", "archived_at"]

STALE_MAX_DAYS = int(os.environ.get("STALE_MAX_DAYS", "3"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "45"))

REQUEST_HEADERS = {
    "User-Agent": "DisasterData.IO FEMA Daily Ops Briefing archiver",
    "Accept": "*/*",
}

DATE_RE = re.compile(
    r"Daily Operations Briefing\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)

TITLE_DATE_RE = re.compile(
    r"FEMA\s+Daily\s+Ops(?:erations)?\s+Briefing\s+"
    r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})",
    re.IGNORECASE,
)

PDF_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    hinted_date: str | None = None
    entry_id: str | None = None


class SourceError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr, flush=True)


def error(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_history() -> dict[str, dict[str, str]]:
    if not HISTORY_CSV.exists():
        return {}

    rows: dict[str, dict[str, str]] = {}
    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_value = (row.get("date") or "").strip()
            if not date_value:
                continue
            rows[date_value] = {
                key: (row.get(key) or "") for key in HISTORY_FIELDS
            }
    return rows


def save_history(rows: dict[str, dict[str, str]]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda row: row["date"])

    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=HISTORY_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(ordered)


def get_bytes(url: str, *, label: str) -> bytes:
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceError(f"{label} request failed: {exc}") from exc

    return response.content


def get_text(url: str, *, label: str) -> str:
    data = get_bytes(url, label=label)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def normalize_url(value: str) -> str:
    return html.unescape(value.strip()).replace("&amp;", "&")


def title_date(title: str) -> str | None:
    match = TITLE_DATE_RE.search(title or "")
    if not match:
        return None

    month, day, year = match.groups()
    try:
        dt = datetime(int(year), int(month), int(day))
    except ValueError:
        return None

    return dt.strftime("%Y-%m-%d")


def extract_pdf_urls(text: str) -> list[str]:
    if not text:
        return []

    decoded = html.unescape(text)
    urls: list[str] = []

    for match in PDF_URL_RE.findall(decoded):
        cleaned = match.rstrip(").,;")
        if cleaned not in urls:
            urls.append(cleaned)

    return urls


def parse_rss_candidates(
    xml_text: str,
    *,
    source_name: str,
    prefer_govdelivery: bool,
) -> list[Candidate]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"{source_name} returned invalid RSS/XML: {exc}") from exc

    candidates: list[Candidate] = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        hinted_date = title_date(title)
        entry_id = (item.findtext("guid") or "").strip() or None

        fields: list[str] = []

        link_text = item.findtext("link")
        if link_text:
            fields.append(link_text)

        description = item.findtext("description")
        if description:
            fields.append(description)

        for child in list(item):
            if child.text and child.tag not in {"title", "link", "guid", "pubDate"}:
                fields.append(child.text)

        urls: list[str] = []
        for field in fields:
            direct = normalize_url(field)
            if direct.lower().startswith(("http://", "https://")) and ".pdf" in direct.lower():
                urls.append(direct)
            urls.extend(extract_pdf_urls(field))

        deduped: list[str] = []
        for url in urls:
            if url not in deduped:
                deduped.append(url)

        if prefer_govdelivery:
            govdelivery = [
                url for url in deduped
                if "content.govdelivery.com" in urlparse(url).netloc.lower()
            ]
            non_govdelivery = [
                url for url in deduped
                if url not in govdelivery
            ]
            deduped = govdelivery + non_govdelivery

        for url in deduped:
            candidates.append(
                Candidate(
                    url=url,
                    source=source_name,
                    hinted_date=hinted_date,
                    entry_id=entry_id,
                )
            )

    # RSS is usually newest first, but sort dated entries explicitly so that
    # a catch-up run archives older missing files before newer ones.
    candidates.sort(key=lambda c: c.hinted_date or "9999-99-99")
    return candidates


def extract_briefing_date(pdf_bytes: bytes) -> str | None:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None
        page_text = reader.pages[0].extract_text() or ""
    except Exception as exc:
        warn(f"could not read candidate PDF: {exc}")
        return None

    flat = re.sub(r"\s+", " ", page_text)
    match = DATE_RE.search(flat)
    if not match:
        warn("no FEMA Daily Operations Briefing date found on page 1")
        return None

    month_name, day, year = match.groups()

    try:
        dt = datetime.strptime(
            f"{month_name.title()} {day} {year}",
            "%B %d %Y",
        )
    except ValueError:
        warn(f"could not parse PDF date: {month_name} {day} {year}")
        return None

    return dt.strftime("%Y-%m-%d")


def age_days(date_str: str) -> int:
    briefing_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    return (utc_now().date() - briefing_dt.date()).days


def is_stale(date_str: str) -> bool:
    return age_days(date_str) > STALE_MAX_DAYS


def archive_pdf(
    *,
    pdf_bytes: bytes,
    date_str: str,
    source_url: str,
    history: dict[str, dict[str, str]],
) -> bool:
    filename = f"{date_str}.pdf"
    dest = ARCHIVE_DIR / filename

    if date_str in history or dest.exists():
        if date_str not in history and dest.exists():
            history[date_str] = {
                "date": date_str,
                "filename": filename,
                "source_url": source_url,
                "archived_at": utc_now().isoformat(timespec="seconds"),
            }
        return False

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf_bytes)

    history[date_str] = {
        "date": date_str,
        "filename": filename,
        "source_url": source_url,
        "archived_at": utc_now().isoformat(timespec="seconds"),
    }

    log(f"Archived {date_str} from {source_url}")
    return True


def process_rss_source(
    *,
    feed_url: str,
    source_name: str,
    history: dict[str, dict[str, str]],
    prefer_govdelivery: bool,
) -> tuple[int, str | None, bool]:
    """
    Returns:
      archived_count
      newest_verified_or_hinted_date
      source_was_reachable
    """
    log(f"Checking {source_name}...")

    try:
        xml_text = get_text(feed_url, label=source_name)
        candidates = parse_rss_candidates(
            xml_text,
            source_name=source_name,
            prefer_govdelivery=prefer_govdelivery,
        )
    except SourceError as exc:
        warn(str(exc))
        return 0, None, False

    if not candidates:
        warn(f"{source_name} contained no PDF candidates")
        return 0, None, True

    hinted_dates = [
        candidate.hinted_date
        for candidate in candidates
        if candidate.hinted_date
    ]
    newest_date = max(hinted_dates) if hinted_dates else None
    archived_count = 0

    # One RSS item can expose the same PDF in multiple fields. Also avoid
    # retrying a broken URL repeatedly in the same run.
    seen_urls: set[str] = set()

    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)

        # If the feed gives us a date already archived locally, skip the
        # download. The archive's durable record remains our authority.
        if candidate.hinted_date and candidate.hinted_date in history:
            continue

        try:
            pdf_bytes = get_bytes(
                candidate.url,
                label=f"{source_name} PDF",
            )
        except SourceError as exc:
            warn(str(exc))
            continue

        verified_date = extract_briefing_date(pdf_bytes)
        if not verified_date:
            continue

        if newest_date is None or verified_date > newest_date:
            newest_date = verified_date

        if (
            candidate.hinted_date
            and candidate.hinted_date != verified_date
        ):
            warn(
                f"{source_name} date mismatch for {candidate.url}: "
                f"feed says {candidate.hinted_date}, PDF says {verified_date}. "
                "Using the PDF date."
            )

        if archive_pdf(
            pdf_bytes=pdf_bytes,
            date_str=verified_date,
            source_url=candidate.url,
            history=history,
        ):
            archived_count += 1

    return archived_count, newest_date, True


def process_disaster_center(
    history: dict[str, dict[str, str]],
) -> tuple[int, str | None, bool]:
    source_name = "Disaster Center fallback"
    log(f"Checking {source_name}...")

    try:
        pdf_bytes = get_bytes(
            DISASTER_CENTER_URL,
            label=source_name,
        )
    except SourceError as exc:
        warn(str(exc))
        return 0, None, False

    verified_date = extract_briefing_date(pdf_bytes)
    if not verified_date:
        warn("Disaster Center PDF could not be validated")
        return 0, None, True

    if is_stale(verified_date):
        warn(
            f"Disaster Center is stale: latest validated briefing is "
            f"{verified_date} ({age_days(verified_date)} days old; "
            f"limit {STALE_MAX_DAYS})"
        )
        return 0, verified_date, True

    archived = archive_pdf(
        pdf_bytes=pdf_bytes,
        date_str=verified_date,
        source_url=DISASTER_CENTER_URL,
        history=history,
    )

    return (1 if archived else 0), verified_date, True


def newest_history_date(history: dict[str, dict[str, str]]) -> str | None:
    return max(history.keys()) if history else None


def main() -> int:
    history = load_history()
    starting_count = len(history)
    total_archived = 0
    source_dates: list[tuple[str, str]] = []
    any_source_reachable = False

    # Primary: DLP's public transformed RSS feed.
    count, newest, reachable = process_rss_source(
        feed_url=DLP_FEED_URL,
        source_name="Data Liberation Project public RSS",
        history=history,
        prefer_govdelivery=True,
    )
    total_archived += count
    any_source_reachable = any_source_reachable or reachable
    if newest:
        source_dates.append(("Data Liberation Project public RSS", newest))

    # Secondary: optional private KTN feed owned by DisasterData.
    if KTN_FEED_URL:
        count, newest, reachable = process_rss_source(
            feed_url=KTN_FEED_URL,
            source_name="DisasterData private KTN RSS",
            history=history,
            prefer_govdelivery=True,
        )
        total_archived += count
        any_source_reachable = any_source_reachable or reachable
        if newest:
            source_dates.append(("DisasterData private KTN RSS", newest))
    else:
        log("KTN_FEED_URL not configured. Skipping private KTN fallback.")

    # Decide whether a live fallback is needed.
    freshest_source_date = (
        max(date for _, date in source_dates)
        if source_dates
        else None
    )

    if freshest_source_date is None or is_stale(freshest_source_date):
        if freshest_source_date:
            warn(
                f"RSS sources appear stale. Freshest advertised/validated "
                f"briefing is {freshest_source_date} "
                f"({age_days(freshest_source_date)} days old)."
            )
        else:
            warn("No usable briefing date was found in the RSS sources.")

        count, newest, reachable = process_disaster_center(history)
        total_archived += count
        any_source_reachable = any_source_reachable or reachable
        if newest:
            source_dates.append(("Disaster Center fallback", newest))

    save_history(history)

    newest_local = newest_history_date(history)
    if newest_local:
        log(
            f"Local archive now contains {len(history)} briefing(s); "
            f"newest is {newest_local}."
        )
    else:
        log("Local archive is empty.")

    # Healthy if at least one source reports a briefing no older than the
    # configured stale limit. Duplicates are a normal healthy outcome.
    healthy_dates = [
        (name, date_value)
        for name, date_value in source_dates
        if not is_stale(date_value)
    ]

    if healthy_dates:
        name, date_value = max(healthy_dates, key=lambda item: item[1])
        log(
            f"Source health OK: {name} reports/validated {date_value}. "
            f"{total_archived} new briefing(s) archived this run."
        )
        return 0

    if total_archived > 0:
        # This is unusual, but preserve the files and flag the run so the
        # operator sees that every known source is still outside the freshness
        # window.
        error(
            f"Archived {total_archived} missing briefing(s), but no configured "
            f"source is current within {STALE_MAX_DAYS} days."
        )
        return 2

    if not any_source_reachable:
        error("No configured briefing source was reachable.")
    elif source_dates:
        freshest_name, freshest_date = max(
            source_dates,
            key=lambda item: item[1],
        )
        error(
            f"All configured sources are stale. Freshest result was "
            f"{freshest_date} from {freshest_name}, "
            f"{age_days(freshest_date)} days old."
        )
    else:
        error(
            "Sources were reachable, but no valid FEMA Daily Operations "
            "Briefing PDF could be discovered and validated."
        )

    log(
        f"Done. {total_archived} new briefing(s) archived. "
        f"{len(history)} total in history.csv "
        f"(started with {starting_count})."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
