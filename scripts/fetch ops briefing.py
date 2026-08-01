#!/usr/bin/env python3
"""
Fetch FEMA's Daily Operations Briefing PDF and archive it.

Source: a dedicated Gmail inbox subscribed to FEMA's "Daily Operations
Briefing" GovDelivery list, read directly over IMAP. No third-party
email-to-RSS service in the loop.

This script:
  1. Connects to the Gmail inbox via IMAP.
  2. Searches for unread FEMA Daily Operations Briefing emails.
  3. Extracts the PDF link and briefing date from each email body.
  4. Downloads any PDF not already in the archive.
  5. Appends a row to history.csv, the durable record of every briefing
     ever captured.
  6. Marks processed emails as read, so the next run's search only
     covers new mail. A missed run is picked up next time, since unread
     mail accumulates.

Design choice: archive the raw PDF only. No text/table extraction at
capture time, since FEMA's layout can change and a brittle parser would
risk breaking the daily job.

Env vars:
  GMAIL_ADDRESS       Required. The dedicated Gmail address.
  GMAIL_APP_PASSWORD  Required. A Gmail App Password (not the account
                      password; requires 2-Step Verification enabled).
  DD_OUT              Optional. Root output directory. Defaults to
                      "archive".
"""

import csv
import email
import html
import imaplib
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

import requests

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Credentials come from environment variables (GitHub Actions secrets).
# The address has a sensible default, but the password must never be
# hardcoded or committed. Empty/blank env values are treated the same
# as unset, so a misconfigured secret gives a clear error rather than a
# confusing login failure.
GMAIL_ADDRESS = (os.environ.get("GMAIL_ADDRESS") or "disasterdata.io@gmail.com").strip()
GMAIL_APP_PASSWORD = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()

OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
ARCHIVE_DIR = OUT_ROOT / "ops-briefings"
HISTORY_CSV = ARCHIVE_DIR / "history.csv"
HISTORY_FIELDS = ["date", "filename", "source_url", "archived_at", "message_id"]

SUBJECT_HINT = "Daily Operations Briefing"

PDF_URL_RE = re.compile(
    r"https://content\.govdelivery\.com/attachments/USDHSFEMA/"
    r"(\d{4})/(\d{2})/(\d{2})/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)

# GovDelivery wraps links in redirect URLs. The real PDF URL is often
# percent-encoded inside a links-N.govdelivery.com wrapper, so we also
# scan an unescaped/unquoted copy of the body to catch those.
import urllib.parse

REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {"User-Agent": "DisasterData.IO ops-briefing archiver"}


def load_history() -> dict:
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


def decode_subject(raw_subject: str) -> str:
    parts = decode_header(raw_subject or "")
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def get_email_body_text(msg) -> str:
    """Concatenate all text/plain and text/html parts into one blob."""
    chunks = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    chunks.append(payload.decode(charset, errors="replace"))
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            chunks.append(payload.decode(charset, errors="replace"))
        except Exception:
            pass
    return " ".join(chunks)


def extract_pdf_link(body_text: str):
    """Find the PDF URL and its YYYY-MM-DD date in the email body.

    Checks the raw body, an HTML-unescaped copy, and a percent-decoded
    copy, so it catches direct links as well as ones buried inside
    GovDelivery redirect wrappers.
    """
    candidates = [
        body_text,
        html.unescape(body_text),
        urllib.parse.unquote(body_text),
        urllib.parse.unquote(html.unescape(body_text)),
    ]
    for blob in candidates:
        match = PDF_URL_RE.search(blob)
        if match:
            year, month, day = match.groups()
            return match.group(0), f"{year}-{month}-{day}"
    return None


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
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must both be set", file=sys.stderr)
        return 1

    history = load_history()
    new_count = 0

    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select("INBOX")

        # Only unread mail, so each run's search space stays small and a
        # missed day is simply picked up on the next run.
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            print(f"IMAP search failed: {status}", file=sys.stderr)
            return 1

        message_ids = data[0].split()
        if not message_ids:
            print("No unread mail.")
            save_history(history)
            print(f"Done. 0 new briefing(s) archived. {len(history)} total in history.csv.")
            return 0

        for msg_id in message_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = decode_subject(msg.get("Subject", ""))

            if SUBJECT_HINT.lower() not in subject.lower():
                # Not a briefing email (could be a confirmation notice or
                # anything else); leave it unread and untouched.
                continue

            body_text = get_email_body_text(msg)
            found = extract_pdf_link(body_text)

            if not found:
                print(f"  ! matched subject but found no PDF link: {subject!r}", file=sys.stderr)
                continue

            pdf_url, date_str = found
            filename = f"{date_str}.pdf"
            dest = ARCHIVE_DIR / filename
            message_id = msg.get("Message-ID", "")

            if date_str in history or dest.exists():
                print(f"  already archived: {date_str}, marking read")
                imap.store(msg_id, "+FLAGS", "\\Seen")
                continue

            print(f"Fetching {date_str} briefing ...")
            if download_pdf(pdf_url, dest):
                history[date_str] = {
                    "date": date_str,
                    "filename": filename,
                    "source_url": pdf_url,
                    "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "message_id": message_id,
                }
                new_count += 1
                imap.store(msg_id, "+FLAGS", "\\Seen")
                time.sleep(1)  # be polite to content.govdelivery.com
            # If download failed, leave the email unread so the next run
            # retries it.

    finally:
        try:
            imap.logout()
        except Exception:
            pass

    save_history(history)
    print(f"Done. {new_count} new briefing(s) archived. {len(history)} total in history.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
