#!/usr/bin/env python3
"""
Fetch FEMA's Daily Operations Briefing PDF and archive it.

Source: the Disaster Center mirror, which republishes the current FEMA
Daily Operations Briefing at a single fixed URL and overwrites it each
day. No email, inbox, subscription, or credentials are involved.

Why not email: pulling from a fixed public URL removes the entire
mail-delivery layer (subscriptions, confirmations, bounce suppression,
provider account suspensions) that a GovDelivery-to-inbox pipeline
depends on. There is nothing to authenticate and nothing to keep
subscribed.

This script:
  1. Downloads the PDF from the fixed Disaster Center URL.
  2. Reads the briefing date FROM THE PDF ITSELF (the "Daily Operations
     Briefing / <Weekday>, <Month> <Day>, <Year>" line on page 1), not
     from the URL or today's date.
  3. Skips if that date is already archived, or if it looks stale (the
     mirror has not updated in several days), so a frozen upstream never
     causes an old briefing to be posted under a fresh date.
  4. Otherwise saves the PDF as YYYY-MM-DD.pdf and appends a row to
     history.csv, the durable record of every briefing captured.

Design choice: archive the raw PDF only. No text/table extraction
beyond reading the date, so the daily job stays resilient to FEMA
changing the briefing's internal layout.

Env vars:
  DD_OUT          Optional. Root output directory. Defaults to "archive".
  OPS_PDF_URL     Optional. Override the source URL.
  STALE_MAX_DAYS  Optional. If the PDF's own date is older than this many
                  days relative to today (UTC), treat the mirror as stale
                  and archive nothing. Defaults to 3.
"""

import csv
import io
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from pypdf import PdfReader

SOURCE_URL = os.environ.get(
    "OPS_PDF_URL",
    "https://disastercenter.com/FEMA%20Daily%20Operation%20Brief.pdf",
)

OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
ARCHIVE_DIR = OUT_ROOT / "ops-briefings"
HISTORY_CSV = ARCHIVE_DIR / "history.csv"
HISTORY_FIELDS = ["date", "filename", "source_url", "archived_at"]

STALE_MAX_DAYS = int(os.environ.get("STALE_MAX_DAYS", "3"))

REQUEST_TIMEOUT = 45
REQUEST_HEADERS = {"User-Agent": "DisasterData.IO ops-briefing archiver"}

# Matches "Daily Operations Briefing <Weekday>, <Month> <Day>, <Year>"
# across the newlines that appear at the top of every briefing PDF.
DATE_RE = re.compile(
    r"Daily Operations Briefing\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)


def load_history() -> dict:
    if not HISTORY_CSV.exists():
        return {}
    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        rows = {}
        for row in csv.DictReader(f):
            # Keep only the fields the current schema knows about, so
            # rows written by earlier versions (which had extra columns
            # such as message_id or feed_entry_id) don't break the
            # writer. Any missing current field defaults to "".
            rows[row["date"]] = {k: row.get(k, "") for k in HISTORY_FIELDS}
        return rows


def save_history(rows: dict) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: r["date"])
    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)


def download_pdf_bytes(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! download failed for {url}: {exc}", file=sys.stderr)
        return None
    return resp.content


def extract_briefing_date(pdf_bytes: bytes) -> str | None:
    """Read the briefing's own date off page 1. Returns YYYY-MM-DD."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_text = reader.pages[0].extract_text() or ""
    except Exception as exc:
        print(f"  ! could not read PDF text: {exc}", file=sys.stderr)
        return None

    # Collapse whitespace so the regex spans line breaks cleanly.
    flat = re.sub(r"\s+", " ", page_text)
    match = DATE_RE.search(flat)
    if not match:
        print("  ! no briefing date found on page 1", file=sys.stderr)
        return None

    month_name, day, year = match.groups()
    try:
        dt = datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y")
    except ValueError:
        print(f"  ! unparseable date: {month_name} {day} {year}", file=sys.stderr)
        return None
    return dt.strftime("%Y-%m-%d")


def main() -> int:
    history = load_history()

    pdf_bytes = download_pdf_bytes(SOURCE_URL)
    if pdf_bytes is None:
        # Network/HTTP failure; nothing archived this run, retry next run.
        save_history(history)
        print(f"Done. 0 new briefing(s) archived. {len(history)} total in history.csv.")
        return 0

    date_str = extract_briefing_date(pdf_bytes)
    if date_str is None:
        print("Could not determine the briefing date; archiving nothing.", file=sys.stderr)
        save_history(history)
        print(f"Done. 0 new briefing(s) archived. {len(history)} total in history.csv.")
        return 0

    # Staleness guard: if the mirror is serving an old briefing, don't
    # treat it as current. history dedup already prevents re-saving the
    # same date, but this also logs clearly when upstream has frozen.
    briefing_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - briefing_dt).days
    if age_days > STALE_MAX_DAYS:
        print(
            f"Mirror looks stale: latest briefing is {date_str} "
            f"({age_days} days old, limit {STALE_MAX_DAYS}). Archiving nothing.",
            file=sys.stderr,
        )
        save_history(history)
        print(f"Done. 0 new briefing(s) archived. {len(history)} total in history.csv.")
        return 0

    filename = f"{date_str}.pdf"
    dest = ARCHIVE_DIR / filename

    if date_str in history or dest.exists():
        print(f"Already archived {date_str}; nothing to do.")
        save_history(history)
        print(f"Done. 0 new briefing(s) archived. {len(history)} total in history.csv.")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf_bytes)
    history[date_str] = {
        "date": date_str,
        "filename": filename,
        "source_url": SOURCE_URL,
        "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    print(f"Archived {date_str} briefing.")

    save_history(history)
    print(f"Done. 1 new briefing(s) archived. {len(history)} total in history.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
