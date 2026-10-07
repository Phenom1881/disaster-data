"""Read Mississippi's 2008-2019 executive orders from the Secretary of State.

The Governor's own site starts in January 2020 (ms_eo_scraper.py). Earlier
orders are kept by the Secretary of State as one PDF per order, listed on a
single page with the order number, the PDF and its date:

    https://www.sos.ms.gov/publications-external-affairs/executive-orders

Each run reads that page, then reads the PDFs it has not read before (up to a
time limit, so a slow run finishes on the next one). Barbour's orders have a
text layer; any PDF without one is read with OCR (tesseract, which the Plus
workflow installs). What each order turned out to be is saved in
ms_sos_orders.csv, so every PDF is read once and later runs only add new rows.

An order counts as a weather emergency when its text names a weather hazard
and an emergency (a state of emergency, a disaster or a National Guard
call-out), and it is not a flags order, a pardon, a burning ban, or an order
that only extends, amends or ends an earlier one. Those orders are added to
the join file with the hazards the order names, so the storm match can read
them.

    python ms_sos_backfill.py --cache ms_sos_orders.csv --join-out declarations_for_join.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.sos.ms.gov/publications-external-affairs/executive-orders"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 60
FIRST_DATE = "2008-01-01"     # the listing starts in 2008
LAST_DATE = "2019-12-31"      # the Governor's own site covers 2020 on
BRYANT_FIRST = 1290           # Bryant took office with order 1290 (March 2012)
REEVES_FIRST = 1456           # Reeves took office with order 1456 (March 2020)
BUDGET_SECONDS = 8 * 60
TESSERACT = shutil.which("tesseract")
OCR_PAGES = 2
MIN_TEXT = 200                # fewer characters than this means a scan
# Bumped whenever classify() changes. A cached order marked as a weather
# emergency under an older version is read again, so a tighter rule can
# take back an order the old one let through.
CLASSIFIER_VERSION = "2"

CACHE_FIELDS = ("order_number", "governor", "date_signed", "pdf_url", "text_source",
                "weather_declaration", "hazards", "summary", "checked_on", "classifier")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description",
               "date_signed", "archive_record_url")

HAZARD_RE = re.compile(
    r"\b(drought|wildfires?|forest fires?|brush fires?|flood(?:s|ing|waters?)?|rainfall|heavy rains?|"
    r"hurricanes?|tropical storms?|tropical depressions?|blizzards?|winter storms?|winter weather|"
    r"snow(?:fall)?|ice storms?|icing|sleet|freezing rain|extreme cold|severe storms?|severe weather|"
    r"thunderstorms?|tornado(?:es|s)?|straight[- ]line winds?|high winds?|damaging winds?|hail)\b",
    re.I)
EMERGENCY_RE = re.compile(r"\bstate of emergency\b|\bemergency\b|\bnational guard\b|\bdisaster\b", re.I)
NOT_WEATHER_RE = re.compile(
    r"half[- ]staff|\bflags?\b[^.;]{0,60}\b(?:flown|lowered|fly)\b|\bpardon|\bburn(?:ing)? bans?\b",
    re.I)
# Clemency orders: Barbour suspended the sentences of inmates who worked on
# storm cleanup (orders 1048, 1056-1063 and 1068 in 2011-2012). They describe
# the storm in their first clause but declare nothing. Storm orders can
# mention inmate labor too, so both halves must appear.
INMATES_RE = re.compile(r"\binmates?\b|\boffenders?\b", re.I)
CLEMENCY_RE = re.compile(r"\bsentences?\b|\bclemency\b|\bcommut(?:e|ed|ation)\b|\bsuspen(?:d|ded|sion)\b|"
                         r"\breleased?\b|\bparole\b", re.I)
MODIFIES_RE = re.compile(
    r"\bhereby\s+(?:rescind|rescinds|terminate|terminates|extend|extends|amend|amends)\b|"
    r"\b(?:rescinding|terminating|extending|amending)\s+executive order\b", re.I)


def governor_for(number: int) -> str:
    if number >= REEVES_FIRST:
        return "Tate Reeves"
    if number >= BRYANT_FIRST:
        return "Phil Bryant"
    return "Haley Barbour"


def parse_date(text: str) -> str:
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text or "")
    if not match:
        return ""
    try:
        return date(int(match.group(3)), int(match.group(1)), int(match.group(2))).isoformat()
    except ValueError:
        return ""


def parse_listing(page_html: str, base: str = LISTING_URL) -> list[dict]:
    """Every order row on the listing page: number, PDF link and date. A row
    covering several orders ("1069-1073") is kept under its first number."""
    soup = BeautifulSoup(page_html, "html.parser")
    rows, seen = [], set()
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not href.lower().endswith(".pdf"):
            continue
        row = link.find_parent("tr")
        cells = row.find_all(["td", "th"]) if row else []
        text = " ".join(c.get_text(" ", strip=True) for c in cells) if cells else link.get_text(" ", strip=True)
        first = cells[0].get_text(" ", strip=True) if cells else link.get_text(" ", strip=True)
        number = re.match(r"\s*(\d{3,4})", first) or re.search(r"(\d{3,4})(?!.*\d{3,4})", href.rsplit("/", 1)[-1].split(".pdf")[0])
        if not number:
            continue
        signed = parse_date(" ".join(c.get_text(" ", strip=True) for c in cells[1:])) if cells else ""
        url = urljoin(base, href)
        key = (int(number.group(1)), url)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"order_number": str(key[0]), "date_signed": signed, "pdf_url": url,
                     "pardons": "pardon" in text.lower() or "pardon" in href.lower()})
    return rows


def wanted(row: dict) -> bool:
    number = int(row["order_number"])
    return (not row["pardons"] and number < REEVES_FIRST and row["date_signed"]
            and FIRST_DATE <= row["date_signed"] <= LAST_DATE)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def pdf_text(content: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return clean(" ".join((page.extract_text() or "") for page in pdf.pages[:4]))


def ocr_text(content: bytes, deadline: float) -> str:
    if not TESSERACT:
        return ""
    import pypdfium2 as pdfium
    texts = []
    document = pdfium.PdfDocument(content)
    try:
        for index in range(min(OCR_PAGES, len(document))):
            if time.monotonic() > deadline:
                break
            page = document[index]
            try:
                image = page.render(scale=300 / 72, grayscale=True).to_pil()
            finally:
                page.close()
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            try:
                result = subprocess.run([TESSERACT, "stdin", "stdout", "--psm", "3"],
                                        input=buffer.getvalue(), capture_output=True, timeout=120,
                                        env=dict(os.environ, OMP_THREAD_LIMIT="1"))
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode == 0:
                texts.append(result.stdout.decode("utf-8", "replace"))
    finally:
        document.close()
    return clean(" ".join(texts))


def summarize(text: str) -> str:
    """The order's first WHEREAS clause, which says what the order is about."""
    # OCR reads WHEREAS as "WI:IEREAS", "WHERBAS" and the like.
    whereas = r"\bW\S{0,3}E\S{0,2}AS\b"
    match = re.search(whereas + r"[,:.]?\s*(.+?)(?:;|" + whereas + r"|\bNOW,? THEREFORE\b)", text, re.I | re.S)
    clause = clean(match.group(1)) if match else clean(text)[:240]
    if len(clause) > 280:
        clause = clause[:280].rsplit(" ", 1)[0] + "..."
    return clause.rstrip(" ,")


def hazards_named(text: str) -> list[str]:
    found = []
    for match in HAZARD_RE.finditer(text):
        word = match.group(1).lower()
        if word not in found:
            found.append(word)
    return found[:6]


def classify(text: str) -> tuple[bool, list[str]]:
    hazards = hazards_named(text)
    clemency = bool(INMATES_RE.search(text) and CLEMENCY_RE.search(text))
    weather = bool(hazards and EMERGENCY_RE.search(text) and not NOT_WEATHER_RE.search(text)
                   and not MODIFIES_RE.search(text) and not clemency)
    return weather, hazards


def read_order(row: dict, session, deadline: float) -> dict:
    out = {"order_number": row["order_number"], "governor": governor_for(int(row["order_number"])),
           "date_signed": row["date_signed"], "pdf_url": row["pdf_url"], "text_source": "error",
           "weather_declaration": "false", "hazards": "", "summary": "",
           "checked_on": date.today().isoformat(), "classifier": CLASSIFIER_VERSION}
    try:
        response = session.get(row["pdf_url"], headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        content = response.content
    except requests.RequestException as exc:
        out["summary"] = f"download failed: {exc.__class__.__name__}"
        return out
    try:
        text, source = pdf_text(content), "text"
    except Exception:
        text, source = "", "text"
    if len(text) < MIN_TEXT:
        if not TESSERACT:
            out["text_source"] = "no_ocr"
            return out
        try:
            text, source = ocr_text(content, deadline), "ocr"
        except Exception:
            text = ""
        if len(text) < MIN_TEXT:
            out["text_source"] = "unreadable"
            return out
    weather, hazards = classify(text)
    out.update({"text_source": source, "weather_declaration": str(weather).lower(),
                "hazards": "; ".join(hazards), "summary": summarize(text)})
    return out


def load_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def write_csv(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def join_row(order: dict) -> dict:
    hazards = order.get("hazards", "")
    description = f"Executive Order {order['order_number']}. {order['summary']}"
    if hazards:
        description += f" Hazards named in the order: {hazards.replace('; ', ', ')}."
    return {"declaration_id": f"MS-EO-{order['order_number']}", "governor": order["governor"],
            "eo_number": order["order_number"], "event_description": description,
            "date_signed": order["date_signed"], "archive_record_url": order["pdf_url"]}


def add_to_join(join_path: Path, cache: list[dict], skip_ids=()) -> int:
    """Add the weather orders to the join file. Ids in skip_ids are rows saved
    by hand (the 2000-2010 compilation backfill); those stay as written."""
    rows = load_csv(join_path)
    ids = {r.get("declaration_id") for r in rows} | set(skip_ids)
    added = 0
    for order in sorted(cache, key=lambda o: (o["date_signed"], int(o["order_number"]))):
        if order.get("weather_declaration") != "true":
            continue
        new = join_row(order)
        if new["declaration_id"] in ids:
            continue
        rows.append(new)
        ids.add(new["declaration_id"])
        added += 1
    write_csv(join_path, JOIN_FIELDS, rows)
    return added


def run(cache_path: Path, join_path: Path, budget: float = BUDGET_SECONDS, session=None,
        listing_html: str | None = None, skip_ids=()) -> dict:
    session = session or requests.Session()
    cache = {r["order_number"]: r for r in load_csv(cache_path) if r.get("order_number")}
    stats = {"listed": 0, "read": 0, "left": 0, "weather": 0, "added": 0, "listing_error": ""}
    try:
        if listing_html is None:
            response = session.get(LISTING_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            listing_html = response.text
        listing = [r for r in parse_listing(listing_html) if wanted(r)]
    except Exception as exc:
        listing = []
        stats["listing_error"] = f"{exc.__class__.__name__}: {exc}"[:200]
    stats["listed"] = len(listing)
    deadline = time.monotonic() + budget
    for row in listing:
        done = cache.get(row["order_number"])
        if done and done.get("text_source") in ("text", "ocr") and not (
                done.get("weather_declaration") == "true"
                and done.get("classifier") != CLASSIFIER_VERSION):
            continue
        if time.monotonic() > deadline:
            stats["left"] += 1
            continue
        cache[row["order_number"]] = read_order(row, session, deadline)
        stats["read"] += 1
    rows = sorted(cache.values(), key=lambda r: int(r["order_number"]))
    write_csv(cache_path, CACHE_FIELDS, rows)
    stats["weather"] = sum(1 for r in rows if r.get("weather_declaration") == "true")
    stats["added"] = add_to_join(join_path, rows, skip_ids)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--join-out", required=True, type=Path)
    parser.add_argument("--budget-seconds", type=float, default=BUDGET_SECONDS)
    parser.add_argument("--skip-ids", default="", help="comma-separated ids saved by hand")
    args = parser.parse_args()
    skip = [s for s in args.skip_ids.split(",") if s]
    stats = run(args.cache, args.join_out, args.budget_seconds, skip_ids=skip)
    print("Mississippi SOS orders 2008-2019: {listed} listed, {read} read this run, "
          "{left} left for the next run, {weather} weather emergencies, {added} added to the join file"
          .format(**stats))
    if stats["listing_error"]:
        print(f"WARNING Mississippi SOS listing could not be read: {stats['listing_error']}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
