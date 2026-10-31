"""Tennessee Governor's state of emergency proclamations.

The Secretary of State's Division of Publications lists every proclamation
the Governor signs at https://tnsos.net/publications/proclamations/
(Title | Governor | Date Signed, newest first, about 25 to a page). Most are
observances. A state of emergency is titled by its event, for example
"State of Emergency May 8, 2024": No. 2700, signed by Governor Lee on August
14, 2024 for the tornadoes, storms and flooding of May 8 in 14 counties,
under Tenn. Code Ann. 58-2-107(b). Tennessee's executive orders, which the
rest of this adapter reads, do not include these, so storms Tennessee
declared only by proclamation were missing from the page.

Each "State of Emergency" row becomes a declaration dated by its Date
Signed, with the event date its title gives. The proclamation's PDF names
the hazards; one whose PDF cannot be read, or names none, is kept in the
actions file but not offered as a weather declaration.

The site cannot be reached from where this was written, so the parser is
written against the page as read on October 28, 2026 and checked by the next
refresh: the run prints how many rows, pages and state of emergency titles
it found.
"""
from __future__ import annotations

import io
import re
import sys
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

INDEX_URL = "https://tnsos.net/publications/proclamations/index.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 60
MAX_PAGES = 300
# "State of Emergency May 8, 2024", but also "Campbell County State of
# Emergency August 11, 2022": the phrase can come anywhere in the title.
TITLE_RE = re.compile(r"\bState of Emergency\b", re.I)
# The index's own search (?Search=...) returns every state of emergency
# title on one page, instead of walking all 115 pages of proclamations.
SEARCH_PARAMS = {"Search": "State of Emergency"}

# Proclamations read on October 31, 2026. Most are scanned with no text, so
# the PDF cannot name the hazard; each was read on the page instead. A
# reviewed entry gives the hazards (none for an order that is not a weather
# declaration) and the first day of the event, which the title often does
# not (its date is sometimes the signing date).
REVIEWED = {
    "2700": {"hazards": ["tornadoes", "severe storms", "flooding"], "event_date": "2024-05-08",
             "note": "Severe weather of May 8, 2024 in 14 counties."},
    "2346": {"hazards": [], "note": "Slope failure on Interstate 75 in Campbell County, August 2, 2022; no weather named."},
    "2294": {"hazards": [], "note": "Rockslide on Interstate 75 in Campbell County, April 18, 2022; no weather named."},
    "1922": {"hazards": ["tornadoes", "severe storms", "flooding"], "event_date": "2020-03-03",
             "note": "Adds the March 3, 2020 tornadoes to the state of emergency of March 10 for storms and rain since January 2020."},
    "1912": {"hazards": ["severe storms", "heavy rain", "flooding", "slope failures"], "event_date": "2020-02-06",
             "note": "Storms and rain since January 2020; slope failures and flooding beginning February 6, 2020."},
    "1805": {"hazards": ["heavy rain", "severe storms", "straight-line winds", "flash flooding"], "event_date": "2019-02-06",
             "note": "Heavy rain, storms and flooding beginning February 6, 2019 (Executive Order No. 7 declared it March 7)."},
    "1772": {"hazards": ["heavy rain", "landslide"], "event_date": "2019-07-11",
             "note": "A heavy rain event caused a slide on Interstate 75 in Campbell County, July 11, 2019."},
    "1606": {"hazards": [], "note": "Rockfall on Interstate 24 in Marion County, November 27, 2018; no weather named."},
    "1605": {"hazards": [], "note": "Roadway collapse on SR-111 in Hamilton County caused by a failed pipe."},
    "1510": {"hazards": [], "note": "Truck strike on the Interstate 40 bridge in Nashville, April 27, 2018."},
    "1435": {"hazards": [], "note": "Truck strike on an Interstate 840 bridge in Rutherford County, March 2, 2018."},
    "1264": {"hazards": ["severe storms", "heavy rain", "hail", "straight-line winds"], "event_date": "2017-05-27",
             "note": "Severe storms of May 27, 2017 across the state."},
    "1254": {"hazards": ["severe storms", "rain", "landslide"], "event_date": "2017-05-13",
             "note": "Storms and rain in April and May 2017; slide on State Route 70 in Hawkins County, May 13, 2017."},
    "1237": {"hazards": ["severe storms", "rain", "landslide"], "event_date": "2017-04-23",
             "note": "Storms and rain in April 2017; slides beginning April 23, 2017 in Anderson, Scott and Union counties."},
    "1053": {"hazards": ["winter storms", "rain", "slope failure"], "event_date": "2016-02-12",
             "note": "Winter storms and rain in January and February 2016; slope failure in Bledsoe County from February 12, 2016."},
    "994": {"hazards": ["winter storms", "rain", "rock slide"], "event_date": "2016-02-26",
            "note": "Winter storms and rain in February 2016; rock slide on Interstate 75 in Campbell County, February 26, 2016."},
    "850": {"hazards": [], "note": "Reissues the June 30, 2014 proclamation (No. 591) for April 28-May 11, 2014 and rescinds it; counted once, as 591."},
    "639": {"hazards": [], "note": "Tanker truck crash and fire at the Peytonsville Road bridge, August 15, 2014."},
    "591": {"hazards": ["severe storms", "heavy rain", "flash flooding", "tornadoes"], "event_date": "2014-04-28",
            "note": "Storms from April 28, 2014; the Emergency Management Plan was activated that day, declaring a state of emergency."},
    "414": {"hazards": ["torrential rain", "flash flooding"], "event_date": "2013-08-08",
            "note": "Torrential rain and flash flooding in Davidson County, August 8, 2013."},
    "105": {"hazards": [], "note": "Landslide on Interstate 75 and rockslide on U.S. 129, March 2012; no weather named."},
    "104": {"hazards": [], "note": "Terminates the state of emergency of February 29-March 2, 2012; the declaration itself is a hand-added row."},
}
SIGNED_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
EVENT_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})(?:\s*(?:-|to|and|&)\s*(?:[A-Z][a-z]+\s+)?\d{1,2})?,?\s+(\d{4})\b")
FILE_NUMBER_RE = re.compile(r"/files/(\d+)\.pdf\b", re.I)


def fetch(url, session=None, params=None):
    response = (session or requests).get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def signed_date(text):
    match = SIGNED_RE.search(text or "")
    if not match:
        return ""
    month, day, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def event_date(title):
    """The first day of the event a title names: "State of Emergency May 8,
    2024" is 2024-05-08, "State of Emergency March 31 - April 1, 2023" is
    2023-03-31."""
    match = EVENT_DATE_RE.search(title or "")
    if not match:
        return ""
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_index(html, page_url=INDEX_URL):
    """Every proclamation row on one index page: [{title, governor, signed, url}]."""
    rows = []
    for tr in BeautifulSoup(html, "html.parser").select("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
        signed = next((signed_date(text) for text in reversed(texts) if signed_date(text)), "")
        link = next((a["href"] for a in tr.find_all("a", href=True)
                     if a["href"].lower().endswith(".pdf") or "/files/" in a["href"]), "")
        if not texts[0] or not signed:
            continue
        rows.append({"title": texts[0], "governor": texts[1] if len(texts) > 2 else "",
                     "signed": signed, "url": urljoin(page_url, link) if link else ""})
    return rows


def collect_index(get=None, sleep=None):
    """All index rows, page by page, until a page adds nothing new (a page
    that ignores ?page= ends the walk at once). The first page failing is an
    error; a later one ends the walk."""
    get = get or (lambda url, params=None: fetch(url, params=params).text)
    rows, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        try:
            html = get(INDEX_URL, params=dict(SEARCH_PARAMS) if page == 1 else {**SEARCH_PARAMS, "page": page})
        except requests.RequestException:
            if page == 1:
                raise
            break
        new = [row for row in parse_index(html) if (row["title"], row["signed"], row["url"]) not in seen]
        if not new:
            break
        seen.update((row["title"], row["signed"], row["url"]) for row in new)
        rows.extend(new)
    print(f"Tennessee proclamations: {len(rows)} index rows over {page} page(s)")
    return rows


def pdf_text(url, session=None):
    try:
        import pdfplumber
        data = fetch(url, session).content
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return " ".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # one unreadable PDF must not stop the rest
        print(f"  WARNING: Tennessee proclamation not read: {url}: {exc}", file=sys.stderr)
        return ""


def proclamation_id(row):
    number = FILE_NUMBER_RE.search(row.get("url") or "")
    return f"TN-PROC-{number.group(1)}" if number else f"TN-PROC-{row['signed']}"


def emergencies(rows, hazard_re, read=None):
    """[{declaration_id, title, signed, event_date, url, hazards, governor}] for
    each State of Emergency row, hazards read from its PDF."""
    read = read or pdf_text
    out = []
    for row in rows:
        if not TITLE_RE.search(row["title"]):
            continue
        number = FILE_NUMBER_RE.search(row.get("url") or "")
        reviewed = REVIEWED.get(number.group(1)) if number else None
        if reviewed is not None:
            hazards = sorted(reviewed["hazards"])
            when = reviewed.get("event_date") or event_date(row["title"])
        else:
            text = read(row["url"]) if row["url"] else ""
            hazards = sorted({m.group(0).lower() for m in hazard_re.finditer(text)})
            when = event_date(row["title"])
        out.append({"declaration_id": proclamation_id(row), "title": row["title"], "signed": row["signed"],
                    "event_date": when, "url": row["url"], "hazards": hazards,
                    "governor": row["governor"]})
    print(f"Tennessee proclamations: {len(out)} state of emergency title(s), "
          f"{sum(1 for e in out if e['hazards'])} naming a weather hazard")
    return out
