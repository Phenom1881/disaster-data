#!/usr/bin/env python3
"""
South Dakota Executive Order scraper for DisasterData Plus.

Source of record: the South Dakota Secretary of State's "Executive Orders"
registry page:

    https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx

The page lists 2020-present directly, one table per year, with a link to
each order's PDF. Earlier years sit behind the page's "Search for Prior
Years Orders" form, an ASP.NET WebForms postback: a "Year Filed:" box, a
"Title:" box and a Search button, plus the usual __VIEWSTATE and
__EVENTVALIDATION fields. Posting a year returns that year's orders in a
results table inside <span id="lbl_SearchInfo">, each linked to a scanned
copy of the signed order (Document.aspx?CabId=...&DocGuid=...).

Checked against the live page in a browser on 2026-10-29: the search
returned 333 orders for 2000-2019, from 10 to 42 a year. The two boxes
have generated names (FD_A723A07D was "Year Filed:" that day), so
search_form_fields() finds them by their labels instead of hard-coding
them. The registry's older titles are short and sometimes cut off
("Drought conditions-DOT overwei"), and a few rows carry a mistyped date or
number; see EXCLUDED_TITLE_PATTERNS and write_csv().

Output schema (declarations_for_join.csv):
    declaration_id, governor, eo_number, event_description, date_signed,
    archive_record_url

date_signed is the registry's "Date Filed", which for these orders is the
signing day or within a few days of it. Three filed dates that are typos
(a month off from the date on the signed order) are corrected by
FILED_DATE_FIXES.

Only orders whose title declares an emergency or disaster, or names a
weather hazard, are written to declarations_for_join.csv. Excluded, by
EXCLUDED_TITLE_PATTERNS:
- standing or operational orders: the recurring "State of Emergency -
  Transportation Exemptions" (blanket motor-carrier hours-of-service
  relief), permit and fee waivers, overwidth hay and fuel hauling, the
  yearly Black Hills fire-season authorizations of the Wildland Fire
  Suppression division, no-wake and boating closures;
- orders for other states' events (Hurricane Katrina, an Iowa blizzard);
- non-weather emergencies (propane supply, influenza, COVID-19).
Titles that say only "State of Emergency" are kept, and their hazards come
from the signed orders, recorded in hazard_overrides.csv.
"""
import argparse
import csv
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None

BASE_URL = "https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx"
HEADERS = {"User-Agent": "DisasterDataIO-Plus/1.0"}

# Years read through the "Search for Prior Years Orders" form.
PRIOR_YEARS = range(2000, 2020)
# Seconds between prior-year searches, to go easy on the registry.
PRIOR_YEAR_PAUSE = 1.0
# The registry sometimes answers with its "An Error Occurred" page for a few
# minutes (seen on 2026-10-29), so a failed year is tried again after these
# waits before it is reported.
PRIOR_YEAR_RETRY_WAITS = (10, 30)

# (first day in office, governor), newest first.
GOVERNOR_TERMS = (
    ("2025-01-25", "Rhoden"),
    ("2019-01-05", "Noem"),
    ("2011-01-08", "Daugaard"),
    ("2003-01-07", "Rounds"),
    ("1995-01-07", "Janklow"),
)

# Filed dates the registry has wrong, checked against the "Dated in Pierre"
# line of the signed order. Keyed on the wrong value too, so a corrected
# registry entry is taken as it stands.
FILED_DATE_FIXES = {
    ("2006-09", "20060621"): "2006-07-21",  # fire emergency from July 20, 2006
    ("2010-42", "20101130"): "2010-12-29",  # winter storm from December 30, 2010
    ("2013-05", "20130312"): "2013-04-12",  # winter storm from April 9, 2013
}

DISASTER_KEYWORDS = re.compile(
    r"(emergency|disaster|drought|fire|flood|wind|storm|blizzard|tornado|weather)",
    re.IGNORECASE,
)

EXCLUDED_TITLE_PATTERNS = re.compile(
    r"(covid|transportation exemptions|motor carrier hours|census|"
    r"cybersecurity|tencent|tiktok|second amendment|workforce|"
    r"reorganization|rescind|amendment|task force|commission|council|"
    r"medication shortage|"
    # 2000-2019 operational orders: fee and permit waivers, overwidth hay
    # hauling ("drought/overwidth vehicles", "Drought conditions-DOT
    # overwei"), fuel hauling and plate extensions after a blizzard.
    r"waive|overwidth|\bdot\b|transport fuels|license plate|"
    # The yearly fire-season authorizations of the Wildland Fire Suppression
    # division ("BH Nat Forest-Wildland Fire Su", "2017 Fire Season") and
    # other standing fire-fighting arrangements.
    r"fire su|suppr|fire protection|fire season|firefighting|"
    r"division of wildland fire|wildland fire division|\bseats\b|"
    # Plans, boating closures, other states' events, non-weather supply and
    # health emergencies, and an energy task force cut short to "Task".
    r"operations plan|no boating|katrina|\biowa\b|propane|influenza|wind power)",
    re.IGNORECASE,
)


LAST_PAGE = {}


def fetch(session, url, data=None):
    if data is None:
        resp = session.get(url, timeout=60, headers=HEADERS)
    else:
        resp = session.post(url, data=data, timeout=60, headers=HEADERS)
    resp.raise_for_status()
    return resp.text


def fetch_current_page(session):
    """GET the registry page. Years 2020-present render directly in HTML."""
    html = fetch(session, BASE_URL)
    LAST_PAGE["html"] = html
    return html


def search_form_fields(html):
    """The fields a prior-years search posts, and the name of the
    "Year Filed:" box, read from the registry page.

    Returns (fields, year_field). fields holds the page's hidden ASP.NET
    fields, an empty "Title:" box and the Search button. Raises ValueError
    when the page has no such form."""
    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form")
    if form is None:
        raise ValueError("South Dakota registry page has no form")
    fields = {}
    for tag in form.find_all("input", {"type": "hidden"}):
        if tag.get("name"):
            fields[tag["name"]] = tag.get("value", "")
    year_field = None
    for box in form.find_all(class_="fbox"):
        label = box.find(class_="title")
        entry = box.find("input")
        if label is None or entry is None or not entry.get("name"):
            continue
        text = label.get_text(" ", strip=True).lower()
        if text.startswith("year filed"):
            year_field = entry["name"]
        elif text.startswith("title"):
            fields[entry["name"]] = ""
    button = form.find("input", {"type": "submit"})
    if year_field is None or button is None or not button.get("name"):
        raise ValueError("South Dakota registry page has no 'Search for Prior Years Orders' form")
    fields[button["name"]] = button.get("value", "")
    return fields, year_field


def fetch_prior_year(session, fields, year_field, year):
    """POST the prior-years search for one year and return the page."""
    data = dict(fields)
    data[year_field] = str(year)
    return fetch(session, BASE_URL, data)


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
            url = link["href"].strip() if link and link.has_attr("href") else ""
            if url:
                # The registry links documents relatively ("../assets/2026
                # Executive Orders/2026-01.pdf"). Kept as-is, those links
                # pointed at disasterdata.io and were broken on the page.
                url = absolute_url(url)
            orders.append({
                "eo_number": eo_number,
                "date_filed": date_filed,  # YYYYMMDD per site convention
                "title": title,
                "url": url,
            })
    return orders


def parse_search_results(html):
    """The orders a prior-years search returned: the rows of the table
    inside <span id="lbl_SearchInfo">. The rest of the page repeats the
    2020-present tables, which are not read here.

    Cells start with a non-breaking space ("&nbsp;2019-01"). Rows whose
    number is not an order number (a 2000 bond order is listed as
    "20000627") are skipped. Raises ValueError when the page has no
    results block, which means the search itself did not run."""
    soup = BeautifulSoup(html or "", "html.parser")
    holder = soup.find(id="lbl_SearchInfo")
    if holder is None:
        raise ValueError("South Dakota prior-years search returned no results block")
    orders = []
    for row in holder.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        eo_number = cells[0].get_text(strip=True)
        if not re.match(r"^\d{4}-\d{2}$", eo_number):
            continue
        link = cells[2].find("a", href=True)
        orders.append({
            "eo_number": eo_number,
            "date_filed": cells[1].get_text(strip=True),
            "title": cells[2].get_text(strip=True),
            "url": absolute_url(link["href"]) if link else "",
        })
    return orders


def absolute_url(href):
    return urljoin(BASE_URL, href.strip()).replace(" ", "%20")


def describe_page(html):
    """A short account of a page that yielded no orders, for the run log."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    return ("%d bytes, title %r, %d table(s), %d table row(s), starts %r"
            % (len(html or ""), title[:80], len(soup.find_all("table")),
               len(soup.find_all("tr")), re.sub(r"\s+", " ", (html or "")[:160])))


def is_declaration(title):
    if EXCLUDED_TITLE_PATTERNS.search(title):
        return False
    return bool(DISASTER_KEYWORDS.search(title))


def to_iso_date(yyyymmdd):
    try:
        return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def governor_on(iso_date):
    """The governor in office on a 'YYYY-MM-DD' date ("" before 1995)."""
    for start, name in GOVERNOR_TERMS:
        if iso_date >= start:
            return name
    return ""


def unique_orders(orders):
    """Drop repeated listings of the same order (the registry lists 2013-06
    "Disaster Declaration" and 2018-08 twice, once for each scanned copy),
    keeping the first. Different orders that share a number are kept."""
    seen = set()
    out = []
    for order in orders:
        key = (order["eo_number"], order["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(order)
    return out


def collect_orders(include_prior_years=False, session=None, pause=PRIOR_YEAR_PAUSE):
    if requests is None:
        raise RuntimeError("requests/bs4 not installed - pip install requests beautifulsoup4")
    session = session or requests.Session()
    html = fetch_current_page(session)
    all_orders = parse_orders(html)
    if include_prior_years:
        try:
            fields, year_field = search_form_fields(html)
        except ValueError as exc:
            print(f"WARNING: prior years not searched: {exc}", file=sys.stderr)
        else:
            for count, year in enumerate(sorted(PRIOR_YEARS, reverse=True)):
                if count and pause:
                    time.sleep(pause)
                all_orders.extend(search_year(session, fields, year_field, year, pause))
    return unique_orders(all_orders)


def search_year(session, fields, year_field, year, pause=PRIOR_YEAR_PAUSE):
    """One year's orders from the prior-years search, tried again after
    PRIOR_YEAR_RETRY_WAITS (skipped when pause is 0, as in the tests).
    A year that still fails is reported and returns no orders; the build
    keeps the rows saved from earlier runs."""
    last = None
    for wait in (0,) + PRIOR_YEAR_RETRY_WAITS:
        if wait and pause:
            time.sleep(wait)
        try:
            return parse_search_results(fetch_prior_year(session, fields, year_field, year))
        except (requests.RequestException, ValueError) as exc:
            last = exc
    print(f"WARNING: prior-year search failed for {year}: {last}", file=sys.stderr)
    return []


def write_csv(orders, actions_out, relationships_out, join_out):
    declarations = []
    used = set()
    for o in orders:
        if not is_declaration(o["title"]):
            continue
        iso_date = (FILED_DATE_FIXES.get((o["eo_number"], o["date_filed"]))
                    or to_iso_date(o["date_filed"]))
        if not iso_date:
            # 2005-12 "Drought restrictions for feed" is filed as 20051313.
            continue
        declaration_id = f"SD-EO-{o['eo_number']}"
        suffix = 2
        while declaration_id in used:
            declaration_id = f"SD-EO-{o['eo_number']}-{suffix}"
            suffix += 1
        used.add(declaration_id)
        declarations.append({
            "declaration_id": declaration_id,
            "governor": governor_on(iso_date),
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
                        help="Also read 2000-2019 through the registry's prior-years search.")
    args = parser.parse_args()

    orders = collect_orders(include_prior_years=args.include_prior_years)
    if not orders:
        # An empty result is never a real finding here (the registry lists
        # every order since 2020), so stop before writing empty files and
        # fail loudly with what the page actually returned.
        print("South Dakota: 0 orders parsed from the registry page: "
              + describe_page(LAST_PAGE.get("html", "")), file=sys.stderr)
        sys.exit(2)
    declarations = write_csv(orders, args.actions_out, args.relationships_out, args.join_out)
    prior = sum(1 for o in orders if o["eo_number"][:4] < "2020")
    print(f"South Dakota: {len(orders)} orders scraped ({prior} from the 2000-2019 search), "
          f"{len(declarations)} written as declarations.")


if __name__ == "__main__":
    main()
