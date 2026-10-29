"""Collect Minnesota governors' executive orders from 2000 on.

Source: the Minnesota Legislative Reference Library's executive order
database. Each governor's orders are on one page, eoresults?gov=N: Jesse
Ventura is gov=6, Tim Pawlenty gov=7, Mark Dayton gov=43 and Tim Walz gov=44.
Each page is a table: official number, a link to the signed PDF, the title,
the date signed, the date filed and the governor.

Until Sep 2026 this scraper read the Governor's own site (mn.gov/governor),
which sits behind Radware's bot manager. From GitHub's runners every request
was intercepted, so the state was never refreshed. The Library is the state's
official archive of these orders and has no such check. Its titles are the
orders' own, and its dates are the dates signed.

Coverage: 2000-present. Ventura's page starts in 1999; orders numbered
before 2000 are left out under the 2000-present scope. Older titles say
"Declaring A State Of Emergency In The State Of Minnesota (Due To ...)" where
Walz's say "Declaring a Peacetime Emergency", and both count.
"""
from __future__ import annotations
import argparse, csv, re, time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STATE = "MN"; GOVERNOR = "Tim Walz"
LRL_BASE = "https://www.lrl.mn.gov/execorders/eoresults?gov="
LRL_URL = LRL_BASE + "44"
# (gov= number, governor) in the Library's database, oldest first.
GOVERNORS = (("6", "Jesse Ventura"), ("7", "Tim Pawlenty"), ("43", "Mark Dayton"), ("44", "Tim Walz"))
FIRST_YEAR = 2000
HEADERS = {"User-Agent": "DisasterDataIO-Plus/1.0 (+https://disasterdata.io/plus/)"}
RETRY_WAITS = (10, 30)
# "Storm damage" is how the Library titles Dayton's 11-21 and 13-09.
HAZARDS = {"drought": r"\bdrought\b", "fire": r"\bwildfires?\b", "flood": r"\bflood(?:ing)?\b",
           "tropical": r"\bhurricanes?\b|\btropical storm\b",
           "winter": r"\bwinter storm\b|\bblizzard\b|\bsnow(?:fall|melt)?\b",
           "severe_storm": r"\bsevere storms?\b|\bsevere weather\b|\btornado(?:es)?\b|\bthunderstorms?\b"
                           r"|\bstorm damage\b",
           "wind": r"\bhurricane.force winds?\b|\bdamaging winds?\b"}
# These official titles are generic. The appended phrases come directly from
# the corresponding order text / Governor press release and keep a
# regenerated join from losing reviewed weather declarations.
TITLE_ENRICH = {
    "19-30": "Declaring a Peacetime Emergency after rapid snowmelt flooding and Winter Storm Wesley",
    "20-108": "Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists after a powerful winter storm",
    "22-23": "Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "23-01": "Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "25-06": "Declaring a Peacetime Emergency and Providing Storm Recovery Assistance in Beltrami County after severe storms and hurricane-force winds",
    "19-03": "Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists during a powerful winter storm with blizzard conditions",
    "19-05": "Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists during a powerful winter storm with blizzard conditions",
    # Dayton, Pawlenty and Ventura orders whose Library titles name no hazard
    # (or only "torrential rain"); the phrase added is the order's own.
    "18-11": "Declaring a State of Peacetime Emergency after severe summer storms with flooding, high winds and tornadoes beginning June 9, 2018",
    "18-06": "Declaring an Emergency in the State of Minnesota and Providing Assistance for Emergency Sheltering, Search and Rescue, and Sheltering of Stranded Motorists during a major wind and snow storm",
    "18-03": "Declaring an Emergency and Providing Assistance to Shelter Stranded Motorists during a powerful winter storm",
    "16-08": "Declaring a State of Peacetime Emergency after flooding from deluge rains beginning September 21, 2016",
    "15-01": "Declaring a State of Emergency in Minnesota and Providing Assistance to Stranded Motorists during a winter storm",
    "14-11": "Declaring a State of Peacetime Emergency after severe summer storms with flooding, landslides and high winds beginning June 11, 2014",
    "14-06": "Declaring a State of Emergency in Minnesota and Providing Assistance to Stranded Motorists during a winter storm",
    "14-03": "Declaring an Emergency in the State of Minnesota and Providing Assistance for Search and Rescue, and Sheltering of Stranded Motorists during a winter storm with white-out conditions",
    "10-10": "Declaring A State Of Emergency In The State Of Minnesota after severe thunderstorms and tornadoes on June 17, 2010 in the Counties Of Faribault, Freeborn, Olmsted, Otter Tail, Polk, Steele, And Wadena",
    "04-09": "Declaring A State Of Emergency In The State Of Minnesota (Regarding The Torrential Rain That Fell In Southern Minnesota September 14-15, 2004), which resulted in flooding",
    "00-04": "Declaring A State Of Emergency In The State Of Minnesota (Regarding The Torrential Rain That Occurred On June 19, 2000) and the overland flooding that followed",
}
SIGNED_DATE_ENRICH = {"25-15": "2025-12-28"}
NUMBER_PREFIX_RE = re.compile(r"^(?:emergency\s+)?executive\s+order\s+(?:no\.?\s*|#\s*)?\d{2}-\d+[a-z]?\s*[:.-]?\s*", re.I)
# "Declaring a Peacetime Emergency" (Walz), "Declaring A State Of Emergency"
# and "Declaring a State of Peacetime Emergency" (Dayton and earlier), and
# "Providing For A Declaration Of Emergency" (Pawlenty) all declare one.
DECLARING_RE = re.compile(r"\bdeclar(?:ing|ation\s+of)\s+(?:a\s+)?(?:state\s+of\s+)?(?:peacetime\s+)?"
                          r"(?:state\s+of\s+)?emergency\b", re.I)
# "Declaring an Emergency" also heads orders that only waive motor carrier
# rules ("Declaring an Emergency and Providing for Relief from Regulations to
# Motor Carriers"), which stay operational, as Walz's 19-36 always has.
DECLARING_AN_RE = re.compile(r"\bdeclaring\s+an\s+emergency\b", re.I)
CARRIER_RELIEF_RE = re.compile(r"relief from regulations|motor carriers", re.I)


@dataclass
class Action:
    eo_number: str; title: str; date_signed: str; url: str
    action_type: str = "other"; hazard: str = ""; related_order: str = ""
    governor: str = ""


def blocked(text, url=""):
    low = (text[:3000] + url).lower()
    return "radware bot manager" in low or "validate.perfdrive.com" in low


def _date(value):
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def classify(action):
    """Set hazard, action_type and related_order from the order's title."""
    action.title = TITLE_ENRICH.get(action.eo_number, NUMBER_PREFIX_RE.sub("", action.title).strip())
    action.date_signed = SIGNED_DATE_ENRICH.get(action.eo_number, action.date_signed)
    low = action.title.lower()
    action.hazard = next((c for c, p in HAZARDS.items() if re.search(p, action.title, re.I)), "")
    rm = re.search(r"(?:amending|extending|rescinding|supplementing).*?Executive Order\s+(\d{2}-\d+)", action.title, re.I)
    action.related_order = rm.group(1) if rm else ""
    declares = DECLARING_RE.search(low) or (DECLARING_AN_RE.search(low) and not CARRIER_RELIEF_RE.search(low))
    if re.search(r"\bamending\b|\bextending\b|\brescinding\b|\bsupplementing\b", low):
        action.action_type = "amendment"
    elif declares and action.hazard:
        action.action_type = "declaration"
    elif re.search(r"providing (?:for )?(?:emergency )?relief|motor carriers|assistance to (?:the state of|stranded motorists)|national guard assistance", low):
        action.action_type = "operational"
    return action


def order_year(number):
    """The year in an official number: 00-04 is 2000, 99-20 is 1999."""
    yy = int(number[:2])
    return 2000 + yy if yy < 70 else 1900 + yy


def parse_table(page, base=LRL_URL, governor=GOVERNOR):
    """Rows of the Library's results table, found by its column names so a
    reordered or added column does not break it."""
    soup = BeautifulSoup(page, "html.parser")
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        names = [" ".join(c.get_text(" ", strip=True).split()).lower() for c in header.find_all(["th", "td"])]
        if "official number" not in names or "title" not in names:
            continue
        col = {name: i for i, name in enumerate(names)}
        out, seen = [], set()
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(names):
                continue
            number = cells[col["official number"]].get_text(" ", strip=True)
            if not re.fullmatch(r"\d{2}-\d+[A-Za-z]?", number) or number in seen:
                continue
            seen.add(number)
            link = None
            if "file" in col:
                link = cells[col["file"]].find("a", href=True)
            link = link or tr.find("a", href=re.compile(r"\.pdf$", re.I))
            signed = cells[col["date signed"]].get_text(" ", strip=True) if "date signed" in col else ""
            title = " ".join(cells[col["title"]].get_text(" ", strip=True).split())
            out.append(Action(number, title, _date(signed),
                              urljoin(base, link["href"]) if link else base, governor=governor))
        if out:
            return out
    raise ValueError("Minnesota Legislative Reference Library page had no executive order table")


def fetch(session, url):
    last = None
    for wait in (0,) + RETRY_WAITS:
        if wait:
            time.sleep(wait)
        try:
            r = session.get(url, headers=HEADERS, timeout=60); r.raise_for_status()
        except requests.RequestException as exc:
            last = exc; continue
        if blocked(r.text, r.url):
            raise ValueError(f"{url} returned an anti-bot page; refusing to emit an empty data set")
        return r
    raise last


def scrape(session=None, counts=None):
    """Every governor's page, oldest first. Orders numbered before
    FIRST_YEAR are left out. A page that cannot be read fails the whole
    run, so a refresh never replaces the saved orders with a partial set.
    counts, when given, is filled with orders kept per governor."""
    session = session or requests.Session()
    rows, seen = [], set()
    for gov, name in GOVERNORS:
        url = LRL_BASE + gov
        kept = 0
        for action in parse_table(fetch(session, url).text, url, name):
            if action.eo_number in seen or order_year(action.eo_number) < FIRST_YEAR:
                continue
            seen.add(action.eo_number)
            rows.append(classify(action))
            kept += 1
        if counts is not None:
            counts[name] = kept
    return sorted(rows, key=lambda x: (x.date_signed, x.eo_number))


def write_outputs(rows, actions_out, relationships_out, join_out):
    for p in (actions_out, relationships_out, join_out): p.parent.mkdir(parents=True, exist_ok=True)
    with actions_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id", "eo_number", "title", "date_signed", "action_type", "related_order", "hazard_category", "archive_record_url"])
        for x in rows: w.writerow([f"MN-EO-{x.eo_number}", x.eo_number, x.title, x.date_signed, x.action_type, x.related_order, x.hazard, x.url])
    with relationships_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["source_declaration_id", "relationship_type", "target_declaration_id"])
        for x in rows:
            if x.related_order: w.writerow([f"MN-EO-{x.eo_number}", x.action_type, f"MN-EO-{x.related_order}"])
    joins = [x for x in rows if x.action_type == "declaration" and x.date_signed]
    with join_out.open("w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"])
        for x in joins: w.writerow([f"MN-EO-{x.eo_number}", x.governor or GOVERNOR, x.eo_number, x.title, x.date_signed, x.url])
    return len(joins)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--actions-out", required=True); p.add_argument("--relationships-out", required=True); p.add_argument("--join-out", required=True); a = p.parse_args()
    counts = {}
    try: rows = scrape(counts=counts)
    except (requests.RequestException, ValueError) as exc: raise SystemExit(f"Minnesota archive scrape failed: {exc}")
    n = write_outputs(rows, Path(a.actions_out), Path(a.relationships_out), Path(a.join_out))
    per = ", ".join(f"{name} {count}" for name, count in counts.items())
    print(f"Minnesota: {len(rows)} executive orders read from the Legislative Reference Library ({per}), {n} weather declarations")


if __name__ == "__main__": main()
