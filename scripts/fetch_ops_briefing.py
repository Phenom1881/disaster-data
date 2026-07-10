#!/usr/bin/env python3
"""
Fetch FEMA's Daily Operations Briefing PDF and archive it.

Source: a private kill-the-newsletter.com RSS feed subscribed to FEMA's
"Daily Operations Briefing" GovDelivery list. Each feed entry is one day's
briefing email, which contains a link to a PDF hosted on
content.govdelivery.com.

This script:
  1. Fetches the private feed (URL comes from an env var / GitHub secret,
     never committed to the repo).
  2. Extracts the PDF link and the briefing date from each entry.
  3. Downloads any PDF not already in the archive.
  4. Appends a row to history.csv, the durable record of every briefing
     ever captured (the RSS feed itself only holds the most recent ~42
     entries, so history.csv is the source of truth going forward).

Design choice: archive the raw PDF only. No text/table extraction at
capture time, since FEMA's layout can change and a brittle parser would
risk breaking the daily job.

Env vars:
  KTN_FEED_URL   Required. The private kill-the-newsletter feed URL.
  DD_OUT         Optional. Root output directory. Defaults to "archive".
"""

import csv
import html
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

FEED_URL = os.environ.get("KTN_FEED_URL")
OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
ARCHIVE_DIR = OUT_ROOT / "ops-briefings"
HISTORY_CSV = ARCHIVE_DIR / "history.csv"
HISTORY_FIELDS = ["date", "filename", "source_url", "archived_at", "feed_entry_id"]

PDF_URL_RE = re.compile(
    r"https://content\.govdelivery\.com/attachments/USDHSFEMA/"
    r"(\d{4})/(\d{2})/(\d{2})/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {"User-Agent": "DisasterData.IO ops-briefing archiver"}


def load_history() -> dict:
    """Return existing history rows keyed by date (YYYY-MM-DD)."""
    if not HISTORY_CSV.exists():
        return {}
    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        return {row["date"]: row for row in csv.DictReader(f)}


def save_history(rows: dict) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: r["date"])
    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def extract_pdf_link(entry):
    """Find the PDF URL and its YYYY-MM-DD date inside a feed entry."""
    blob = " ".join(
        filter(
            None,
            [
                entry.get("title", ""),
                entry.get("summary", ""),
                *[c.get("value", "") for c in entry.get("content", [])],
            ],
        )
    )
    blob = html.unescape(blob)
    match = PDF_URL_RE.search(blob)
    if not match:
        return None
    year, month, day = match.groups()
    date_str = f"{year}-{month}-{day}"
    return match.group(0), date_str


def download_pdf(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! download failed for {url}: {exc}", file=sys.stderr)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def main() -> int:
    if not FEED_URL:
        print("KTN_FEED_URL is not set", file=sys.stderr)
        return 1

    feed = feedparser.parse(FEED_URL)
    if feed.bozo and not feed.entries:
        print(f"Could not parse feed: {feed.bozo_exception}", file=sys.stderr)
        return 1

    history = load_history()
    new_count = 0

    for entry in feed.entries:
        found = extract_pdf_link(entry)
        if not found:
            continue
        pdf_url, date_str = found

        if date_str in history:
            continue

        filename = f"{date_str}.pdf"
        dest = ARCHIVE_DIR / filename

        if dest.exists():
            # File is already on disk but missing from history.csv;
            # backfill the row without re-downloading.
            history[date_str] = {
                "date": date_str,
                "filename": filename,
                "source_url": pdf_url,
                "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "feed_entry_id": entry.get("id", ""),
            }
            continue

        print(f"Fetching {date_str} briefing ...")
        if download_pdf(pdf_url, dest):
            history[date_str] = {
                "date": date_str,
                "filename": filename,
                "source_url": pdf_url,
                "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "feed_entry_id": entry.get("id", ""),
            }
            new_count += 1
            time.sleep(1)  # be polite to content.govdelivery.com

    save_history(history)
    print(f"Done. {new_count} new briefing(s) archived. {len(history)} total in history.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
