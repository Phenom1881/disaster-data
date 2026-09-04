"""Pull current Virginia executive orders and prepare weather declarations.

The Governor's listing links directly to PDF files.  This script therefore
uses the listing card for the signing date and the PDF filename (together
with the visible title) to classify a declaration as weather-related.  It
does not try to parse a PDF response as HTML.

Outputs:
  va_all_orders_raw.csv
  va_emergency_declarations_all.csv
  declarations_for_join.csv

Usage:
  python va_eo_scraper.py
"""

import argparse
import re
import sys
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


DEFAULT_URLS = ["https://www.governor.virginia.gov/executive-actions/"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EM-research-script/1.1)"}

NUMBER_PATTERN = re.compile(r"^(EO|ED)-(\d+)\s+(.*)$")
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
DATE_PATTERN = re.compile(rf"({MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
MONTH_TO_NUM = {
    month: f"{number:02d}"
    for number, month in enumerate(MONTHS.split("|"), start=1)
}

WEATHER_KEYWORDS = [
    "hurricane",
    "tropical storm",
    "tropical depression",
    "winter weather",
    "severe weather",
    "thunderstorm",
    "storm",
    "flooding",
    "flood",
    "snow",
    "ice",
    "blizzard",
    "tornado",
    "freezing rain",
    "wind",
]
PROCEDURAL_MARKERS = ["delegat", "authority to declare", "succession"]


def fetch_soup(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def iso_date(text):
    match = DATE_PATTERN.search(text or "")
    if not match:
        return None
    month, day, year = match.groups()
    return f"{year}-{MONTH_TO_NUM[month]}-{int(day):02d}"


def listing_date(anchor):
    """Read the date from the order card that contains the anchor."""
    card = anchor.find_parent("div", class_="eo-inner")
    if card:
        parsed = iso_date(card.get_text(" ", strip=True))
        if parsed:
            return parsed

    # Fallback for a future markup change: inspect nearby emphasis/time tags,
    # stopping before the next numbered order link.
    checked = 0
    for element in anchor.next_elements:
        if element is anchor:
            continue
        if getattr(element, "name", None) == "a":
            label = element.get_text(" ", strip=True)
            if NUMBER_PATTERN.match(label):
                break
        if isinstance(element, str):
            parsed = iso_date(element)
            if parsed:
                return parsed
        checked += 1
        if checked >= 40:
            break
    return None


def parse_listing(url):
    soup = fetch_soup(url)
    rows = []
    for anchor in soup.find_all("a"):
        text = anchor.get_text(" ", strip=True)
        match = NUMBER_PATTERN.match(text)
        if not match:
            continue
        kind, number, short_title = match.groups()
        href = anchor.get("href")
        if not href:
            continue
        rows.append(
            {
                "eo_number": f"{kind}-{number}",
                "short_title": short_title.strip(),
                "date_signed": listing_date(anchor),
                "detail_url": urljoin(url, href),
            }
        )
    return rows


def is_declaration_candidate(short_title):
    lowered = short_title.lower()
    return (
        "state of emergency" in lowered
        and not any(marker in lowered for marker in PROCEDURAL_MARKERS)
    )


def pdf_filename_text(detail_url):
    """Turn a descriptive PDF filename into searchable, readable text."""
    filename = PurePosixPath(unquote(urlparse(detail_url).path)).stem
    filename = re.sub(r"^(EO|ED)[-_]?\d+[-_]*", "", filename, flags=re.I)
    return re.sub(r"[-_]+", " ", filename).strip()


def declaration_metadata(short_title, detail_url):
    """Return an informative description, weather flag, and audit basis."""
    filename_text = pdf_filename_text(detail_url)
    classification_text = f"{short_title} {filename_text}".lower()
    weather = any(keyword in classification_text for keyword in WEATHER_KEYWORDS)

    description = short_title
    if weather:
        # The current listing uses the generic label "Declaring State of
        # Emergency", while the PDF filename contains the omitted cause.
        cause_match = re.search(
            r"state of emergency(?: due to)?\s+(.*)$", filename_text, flags=re.I
        )
        if cause_match:
            cause = cause_match.group(1)
            cause = re.sub(rf"\b(?:19|20)\d{{2}}\b|\b(?:{MONTHS})\b", "", cause,
                           flags=re.I)
            cause = re.sub(r"\s+", " ", cause).strip(" -")
            if cause:
                description = f"{short_title} Due to {cause.title()}"

    return description, weather, filename_text


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Virginia gubernatorial emergency declarations"
    )
    parser.add_argument("--urls", default=",".join(DEFAULT_URLS))
    parser.add_argument("--raw-out", default="va_all_orders_raw.csv")
    parser.add_argument("--all-out", default="va_emergency_declarations_all.csv")
    parser.add_argument("--join-out", default="declarations_for_join.csv")
    args = parser.parse_args()

    all_rows = []
    for url in [value.strip() for value in args.urls.split(",") if value.strip()]:
        try:
            parsed = parse_listing(url)
        except requests.RequestException as exc:
            print(f"Failed to fetch {url}: {exc}", file=sys.stderr)
            continue
        print(f"{url}: parsed {len(parsed)} order links")
        all_rows.extend(parsed)

    if not all_rows:
        print("No orders parsed. Check the listing URL in a browser.", file=sys.stderr)
        raise SystemExit(1)

    orders = pd.DataFrame(all_rows).drop_duplicates(subset=["eo_number"])
    orders.to_csv(args.raw_out, index=False)
    print(f"Wrote {len(orders)} unique orders to {args.raw_out}")

    candidates = orders[
        orders["short_title"].apply(is_declaration_candidate)
    ].copy()
    metadata = candidates.apply(
        lambda row: declaration_metadata(row["short_title"], row["detail_url"]),
        axis=1,
        result_type="expand",
    )
    if not candidates.empty:
        metadata.columns = ["event_description", "weather_related", "filename_text"]
        candidates = pd.concat([candidates, metadata], axis=1)
    else:
        candidates["event_description"] = pd.Series(dtype="object")
        candidates["weather_related"] = pd.Series(dtype="bool")
        candidates["filename_text"] = pd.Series(dtype="object")

    candidates.to_csv(args.all_out, index=False)
    print(f"Wrote {len(candidates)} emergency declarations to {args.all_out}")

    missing_dates = candidates[candidates["date_signed"].isna()]
    if not missing_dates.empty:
        print(
            f"Warning: {len(missing_dates)} declarations have no parsed date; "
            f"see {args.all_out}.",
            file=sys.stderr,
        )

    weather = candidates[
        candidates["weather_related"] & candidates["date_signed"].notna()
    ]
    weather[["eo_number", "event_description", "date_signed"]].to_csv(
        args.join_out, index=False
    )
    print(
        f"Wrote {len(weather)} weather declarations to {args.join_out} "
        "(ready for eo_storm_join.py)"
    )

    for _, row in weather.iterrows():
        print(
            f"  {row['eo_number']}: {row['date_signed']} — "
            f"{row['event_description']}"
        )


if __name__ == "__main__":
    main()
