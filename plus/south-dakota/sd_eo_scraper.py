#!/usr/bin/env python3
"""
South Dakota Executive Order scraper for DisasterData Plus.

Source of record: the South Dakota Secretary of State's "Executive Orders"
registry page:

    https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx

That page server-renders a table of executive orders per year, with a link
to the order's PDF for each entry. Loading the bare URL returns 2020-present
(confirmed: 2020 through 2026 rendered directly in the initial HTML, no
JavaScript required for that range). Years before 2020 sit behind the page's
"Search for Prior Years Orders" form, which is an ASP.NET WebForms postback
(__VIEWSTATE / __EVENTVALIDATION hidden fields, not a plain query-string
GET) - the code below implements that postback path in fetch_prior_years(),
but it has NOT been exercised against a live network in the environment
that produced this delivery (no outbound access to *.gov domains from that
sandbox). Run it once against the real network and diff the results before
trusting 2000-2019 coverage. See coverage note in south_dakota.py.

Output schema (declarations_for_join.csv):
    declaration_id, governor, eo_number, event_description, date_signed,
    archive_record_url

Only orders whose title clearly denotes a state-of-emergency / disaster /
drought / fire / flood / wind / winter storm declaration are written to
declarations_for_join.csv. Standing "State of Emergency - Transportation
Exemptions" orders (a recurring administrative mechanism SD uses to grant
blanket motor-carrier hours-of-service relief, not tied to a single
identifiable storm) and narrow companion orders (e.g. a motor-carrier-hours
waiver riding alongside a disaster declaration) are deliberately excluded -
see EXCLUDED_TITLE_PATTERNS. COVID-19 orders are excluded as non-weather.
"""
import argparse
import csv
import re
import sys
from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None

BASE_URL = "https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx"

# Governors covering the periods this scraper can reach.
GOVERNOR_BY_YEAR = {
    2020: "Noem", 2021: "Noem", 2022: "Noem", 2023: "Noem", 2024: "Noem",
    2025: "Rhoden", 2026: "Rhoden",
}

DISASTER_KEYWORDS = re.compile(
    r"(emergency|disaster|drought|fire|flood|wind|storm|blizzard|tornado)",
    re.IGNORECASE,
)

EXCLUDED_TITLE_PATTERNS = re.compile(
    r"(covid|transportation exemptions|motor carrier hours|census|"
    r"cybersecurity|tencent|tiktok|second amendment|workforce|"
    r"reorganization|rescind|amendment|task force|commission|council|"
    r"medication shortage)",
    re.IGNORECASE,
)


def fetch_current_page():
    """GET the registry page. Years 2020-present render directly in HTML."""
    resp = requests.get(BASE_URL, timeout=30, headers={"User-Agent": "DisasterDataIO-Plus/1.0"})
    resp.raise_for_status()
    return resp.text


def fetch_prior_years(session, year):
    """
    POST-back the ASP.NET search form for a year before 2020.

    NOT independently verified against the live site in this delivery -
    the __VIEWSTATE/__EVENTVALIDATION field names below were inferred from
    standard ASP.NET WebForms search-page conventions on sdsos.gov's sibling
    registries (Oaths of Office / General Appointments use the same
    template), not confirmed against this specific page's live markup.
    Treat as a starting point, not a verified implementation.
    """
    get_resp = session.get(BASE_URL, timeout=30)
    soup = BeautifulSoup(get_resp.text, "html.parser")

    def field(name, default=""):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag and tag.has_attr("value") else default

    payload = {
        "__VIEWSTATE": field("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": field("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": field("__EVENTVALIDATION"),
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "ctl00$MainContent$txtYear": str(year),
        "ctl00$MainContent$btnSearch": "Search",
    }
    resp = session.post(BASE_URL, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_orders(html):
    """Parse '| Order Number | Dated Filed | Title (link) |' rows."""
    soup = BeautifulSoup(html, "html.parser")
    orders = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            eo_number = cells[0].get_text(strip=True)
            date_filed = cells[1].get_text(strip=True)
            title_cell = cells[2]
            link = title_cell.find("a")
            if not re.match(r"^\d{4}-\d{2}", eo_number):
                continue
            title = (link.get_text(strip=True) if link else title_cell.get_text(strip=True))
            url = link["href"] if link and link.has_attr("href") else ""
            if url and url.startswith("/"):
                url = "https://sdsos.gov" + url
            orders.append({
                "eo_number": eo_number,
                "date_filed": date_filed,  # YYYYMMDD per site convention
                "title": title,
                "url": url,
            })
    return orders


def is_declaration(title):
    if EXCLUDED_TITLE_PATTERNS.search(title):
        return False
    return bool(DISASTER_KEYWORDS.search(title))


def to_iso_date(yyyymmdd):
    try:
        return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def governor_for(eo_number):
    year = int(eo_number.split("-")[0])
    return GOVERNOR_BY_YEAR.get(year, "")


def collect_orders(include_prior_years=False):
    if requests is None:
        raise RuntimeError("requests/bs4 not installed - pip install requests beautifulsoup4")
    session = requests.Session()
    html = fetch_current_page()
    all_orders = parse_orders(html)
    if include_prior_years:
        for year in range(2000, 2020):
            try:
                prior_html = fetch_prior_years(session, year)
                all_orders.extend(parse_orders(prior_html))
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: prior-year fetch failed for {year}: {exc}", file=sys.stderr)
    return all_orders


def write_csv(orders, actions_out, relationships_out, join_out):
    declarations = []
    for o in orders:
        if not is_declaration(o["title"]):
            continue
        iso_date = to_iso_date(o["date_filed"])
        if not iso_date:
            continue
        declarations.append({
            "declaration_id": f"SD-EO-{o['eo_number']}",
            "governor": governor_for(o["eo_number"]),
            "eo_number": o["eo_number"],
            "event_description": o["title"],
            "date_signed": iso_date,
            "archive_record_url": o["url"],
        })

    fieldnames = ["declaration_id", "governor", "eo_number", "event_description",
                  "date_signed", "archive_record_url"]

    with open(join_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for d in declarations:
            writer.writerow(d)

    # actions/relationships are pass-through artifacts of the raw scrape,
    # kept for parity with the multi-file contract other state scrapers use.
    with open(actions_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "date_filed", "title", "url"], lineterminator="\n")
        writer.writeheader()
        for o in orders:
            writer.writerow(o)

    with open(relationships_out, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["eo_number", "relates_to"], lineterminator="\n")
        writer.writeheader()
        # Companion-order relationships noted by hand during research for this
        # delivery (see REVIEW_NOTES.md); the live scraper does not yet infer
        # these automatically.
        writer.writerow({"eo_number": "2024-05", "relates_to": "2024-04"})

    return declarations


def main():
    parser = argparse.ArgumentParser(description="South Dakota EO scraper")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    parser.add_argument("--include-prior-years", action="store_true",
                         help="Attempt the 2000-2019 ASP.NET postback path (unverified live).")
    args = parser.parse_args()

    orders = collect_orders(include_prior_years=args.include_prior_years)
    declarations = write_csv(orders, args.actions_out, args.relationships_out, args.join_out)
    print(f"South Dakota: {len(orders)} orders scraped, {len(declarations)} written as declarations.")


if __name__ == "__main__":
    main()
