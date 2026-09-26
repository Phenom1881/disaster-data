#!/usr/bin/env python3
"""
North Dakota Executive Order scraper for DisasterData Plus.

Two real, distinct sources of record, both on governor.nd.gov:

1. https://www.governor.nd.gov/executive-orders
   Current-administration EOs (2024-present). Each entry is one list item,
   "2026-07 - Armstrong Declares Drought Disaster", with the title linking
   straight to the signed PDF. The page shows no date, so the date is read
   from the order's own PDF (its signature clause), or taken from
   CONFIRMED_DATES below when the PDF has none that can be read.

2. https://www.governor.nd.gov/executive-orders/executive-order-archive
   Historical EOs back to 1963. Entries from 2017-2023 (Burgum) read
   "2023-04 - April 10, 2023 - Burgum Declares Statewide Emergency for Spring
   Flooding", with both a number and a date. Entries from 2016 and earlier
   give only "Month Day, Year - Title" with no order number, a limitation of
   the page itself, so they are not used.

Both pages are plain server-rendered HTML (Drupal), no JS execution needed.

Why this file changed (Sep 2026): the parsing patterns below were written
against a markdown rendering of these pages ("**2026-07** - [Title](url)"),
but the scraper handed them the raw HTML, where that text never appears, so
every run from GitHub found 0 orders. page_markdown() now renders the HTML
into that same markdown shape first (bold as **...**, links as [text](url),
one block per line), and the patterns accept the number with or without the
bold markers.

Output schema (declarations_for_join.csv):
    declaration_id, governor, eo_number, event_description, date_signed,
    archive_record_url

Only genuine weather/disaster declarations are written. Notably: ND uses
"declares a state of emergency" language for BOTH weather disasters and
civil-disturbance orders (e.g. 2020-34, a Fargo/Cass County civil-unrest
order tied to the May 2020 protests, not a storm) - the title-matching
alone cannot distinguish these, so EXCLUDE_IDS below hard-excludes orders
confirmed non-weather by reading the underlying news release, and future
maintainers should not assume every "state of emergency" hit is a storm.
"""
import argparse
import csv
import io
import re
import sys
from datetime import datetime
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

CURRENT_URL = "https://www.governor.nd.gov/executive-orders"
ARCHIVE_URL = "https://www.governor.nd.gov/executive-orders/executive-order-archive"
HEADERS = {"User-Agent": "DisasterDataIO-Plus/1.0 (+https://disasterdata.io/plus/)"}

# Confirmed non-weather despite emergency/disaster-sounding titles. Checked
# by hand against the governor's-office news release for each ID; do not
# remove an ID from this list without re-confirming against the source.
EXCLUDE_IDS = {
    "2020-34",  # Fargo/West Fargo/Cass County civil-disturbance order, not weather.
    "2023-07",  # ND Guard deployed to Texas border, not a ND weather event.
}

# Dates independently confirmed via governor's-office news releases for
# orders on the undated current-EOs page. Used when the order's PDF has no
# signature date that can be read, and preferred over a date read from the
# PDF if the two ever disagree.
CONFIRMED_DATES = {
    "2025-05": "2025-06-21",
    "2026-03": "2026-06-30",
}

DISASTER_KEYWORDS = re.compile(
    r"(disaster|flood|drought|fire|blizzard|storm|tornado|wildfire)",
    re.IGNORECASE,
)

# "expand" and "extend" keep follow-on orders out, e.g. 2026-07.1 "Expands
# Drought Relief Program to All Counties", which widens the 2026-07 drought
# disaster rather than declaring a new one.
EXCLUDED_TITLE_PATTERNS = re.compile(
    r"(covid|hours of service|task force|council|commission|rescind|"
    r"terminat|amend|expand|extend|census|kratom|tiktok|homelessness|advisory)",
    re.IGNORECASE,
)

GOVERNOR_PREFIX_RE = re.compile(r"^(Armstrong|Burgum|Dalrymple|Hoeven)\s+(?=[A-Z])")
_DASH = r"\s*[-–—]\s*"
_NUM = r"(?:\*\*)?(?P<num>\d{4}-\d+(?:\.\d+)?)(?:\*\*)?"
_DATE = r"(?P<date>[A-Z][a-z]+\.? \d{1,2}, \d{4})"

ARCHIVE_ITEM_RE = re.compile(r"^(?:[-*]\s+)?" + _NUM + _DASH + _DATE + _DASH + r"(?P<title>.+)$")
CURRENT_ITEM_RE = re.compile(
    _NUM + _DASH + r"\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)"
)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")

_BLOCKS = ["p", "div", "li", "ul", "ol", "tr", "table", "section", "article", "header",
           "footer", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "br", "main",
           "nav", "aside", "td", "th", "blockquote"]


def fetch(url):
    resp = requests.get(url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    return resp


def page_markdown(html, base_url):
    """Render server HTML the way the page reads: one block per line, bold as
    **text**, links as [text](absolute url). Text that is already markdown
    (the test fixtures) passes through unchanged."""
    if "<" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        a.replace_with("[%s](%s)" % (text, urljoin(base_url, a["href"])) if text else "")
    for b in soup.find_all(["strong", "b"]):
        text = " ".join(b.get_text(" ", strip=True).split())
        b.replace_with("**%s**" % text if text else "")
    for tag in soup.find_all(_BLOCKS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def split_governor(title):
    """'Armstrong Declares Drought Disaster' -> ('Armstrong', 'Declares Drought
    Disaster'). The saved records carry titles without the name."""
    m = GOVERNOR_PREFIX_RE.match(title)
    return (m.group(1), title[m.end():]) if m else ("", title)


def parse_archive_markdown(md_text):
    """Parse the 2017-2023 numbered entries out of the archive page's
    rendered '**YYYY-NN** - Month Day, Year - Title' lines."""
    orders = []
    for line in page_markdown(md_text, ARCHIVE_URL).splitlines():
        m = ARCHIVE_ITEM_RE.search(line.strip())
        if m:
            title = m.group("title").strip()
            link = _MD_LINK_RE.search(title)
            gov, title = split_governor(_MD_LINK_RE.sub(r"\1", title).strip())
            orders.append({
                "eo_number": m.group("num"),
                "date_text": m.group("date"),
                "title": title,
                "url": link.group(2) if link and link.group(2).lower().endswith(".pdf") else ARCHIVE_URL,
                "governor": gov,
            })
    return orders


def parse_current_markdown(md_text):
    """Parse the 2024-present numbered/linked entries. No date on this page;
    the date comes from the order's PDF or CONFIRMED_DATES."""
    orders = []
    for line in page_markdown(md_text, CURRENT_URL).splitlines():
        m = CURRENT_ITEM_RE.search(line)
        if m:
            gov, title = split_governor(m.group("title").strip())
            orders.append({
                "eo_number": m.group("num"),
                "date_text": None,
                "title": title,
                "url": m.group("url").strip(),
                "governor": gov,
            })
    return orders


def parse_date_text(date_text):
    if not date_text:
        return ""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y"):
        try:
            return datetime.strptime(date_text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


_MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
           "November|December")
SIGNED_DAY_OF_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+(" + _MONTHS + r"),?\s+(\d{4})\b", re.I)
SIGNED_NEAR_RE = re.compile(
    r"\b(?:executed|signed|dated|issued|given)\b[^.]{0,60}?\b(" + _MONTHS + r")\s+(\d{1,2}),\s+(\d{4})\b", re.I)


def signed_date_from_text(text, eo_number):
    """The date an order was signed, from its own text: the last
    'this 21st day of June, 2025' clause, or a date right after 'Executed',
    'Signed' or 'Dated'. The year must match the order number's year
    (2025-05 was signed in 2025). Anything else returns '' rather than a
    guess; the WHEREAS clauses carry event dates that are not the signing date."""
    year = eo_number.split("-")[0]
    found = ""
    for day, month, yr in SIGNED_DAY_OF_RE.findall(text or ""):
        found = parse_date_text("%s %s, %s" % (month.title(), day, yr)) or found
    if not found:
        m = SIGNED_NEAR_RE.search(text or "")
        if m:
            found = parse_date_text("%s %s, %s" % (m.group(1).title(), m.group(2), m.group(3)))
    return found if found.startswith(year) else ""


def pdf_signed_date(url, eo_number):
    if pdfplumber is None:
        return ""
    try:
        content = fetch(url).content
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:  # a missing or unreadable PDF must not stop the state
        print("  WARNING: could not read ND order %s PDF (%s): %s" % (eo_number, url, exc), file=sys.stderr)
        return ""
    return signed_date_from_text(text, eo_number)


def governor_for(eo_number):
    year = int(eo_number.split("-")[0])
    if year >= 2025:
        return "Armstrong"
    if 2017 <= year <= 2024:
        return "Burgum"
    if year <= 2016:
        return "Dalrymple"
    return ""


def is_declaration(eo_number, title):
    if eo_number in EXCLUDE_IDS:
        return False
    if EXCLUDED_TITLE_PATTERNS.search(title):
        return False
    return bool(DISASTER_KEYWORDS.search(title))


def collect_orders():
    if requests is None:
        raise RuntimeError("requests/bs4 not installed - pip install requests beautifulsoup4")
    archive = parse_archive_markdown(fetch(ARCHIVE_URL).text)
    page = fetch(CURRENT_URL).text
    current = parse_current_markdown(page)
    if not archive:
        print("  WARNING: North Dakota archive page gave 0 numbered orders; the saved "
              "2017-2023 records stand", file=sys.stderr)
    if not current:
        # The current page always lists this administration's orders, so zero
        # means the layout was not understood. Stop; the saved records are kept.
        pdfs = len(re.findall(r'href="[^"]+\.pdf"', page, re.I))
        raise SystemExit("North Dakota: the current orders page gave 0 orders (%d characters, "
                         "%d PDF links); the page layout may have changed" % (len(page), pdfs))
    # Undated current-page declarations: read the date from each order's PDF.
    for o in current:
        if is_declaration(o["eo_number"], o["title"]) and o["url"].lower().endswith(".pdf"):
            o["pdf_date"] = pdf_signed_date(o["url"], o["eo_number"])
    return archive + current


def write_csv(orders, actions_out, relationships_out, join_out, confirmed_dates=None):
    """
    confirmed_dates: optional dict of {eo_number: 'YYYY-MM-DD'} used to
    supply a verified date for orders that came from the undated
    current-EOs page. Orders with neither a parsed date, a date read from
    their PDF, nor a confirmed_dates entry are written to actions_out (raw
    scrape) but excluded from the join CSV - a real join with a fabricated
    date is worse than a smaller real one.
    """
    confirmed_dates = confirmed_dates or {}
    declarations = []
    undated = []
    for o in orders:
        if not is_declaration(o["eo_number"], o["title"]):
            continue
        date_signed = (parse_date_text(o["date_text"]) or confirmed_dates.get(o["eo_number"], "")
                       or o.get("pdf_date", ""))
        if not date_signed:
            undated.append(o["eo_number"])
            continue
        declarations.append({
            "declaration_id": f"ND-EO-{o['eo_number']}",
            "governor": o.get("governor") or governor_for(o["eo_number"]),
            "eo_number": o["eo_number"],
            "event_description": o["title"],
            "date_signed": date_signed,
            "archive_record_url": o["url"],
        })
    if undated:
        print("  NOTE: North Dakota declarations left out for want of a readable signing date "
              "(add to CONFIRMED_DATES once checked): %s" % ", ".join(undated), file=sys.stderr)

    fieldnames = ["declaration_id", "governor", "eo_number", "event_description",
                  "date_signed", "archive_record_url"]
    with open(join_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for d in declarations:
            writer.writerow(d)

    with open(actions_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "date_text", "title", "url"],
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for o in orders:
            writer.writerow(o)

    with open(relationships_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "relates_to"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"eo_number": "2017-02.1", "relates_to": "2017-02"})
        writer.writerow({"eo_number": "2026-07.1", "relates_to": "2026-07"})

    return declarations


def main():
    parser = argparse.ArgumentParser(description="North Dakota EO scraper")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    orders = collect_orders()
    declarations = write_csv(orders, args.actions_out, args.relationships_out,
                             args.join_out, confirmed_dates=CONFIRMED_DATES)
    print(f"North Dakota: {len(orders)} orders scraped, {len(declarations)} written as declarations.")


if __name__ == "__main__":
    main()
