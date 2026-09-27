"""Collect Arizona emergency declarations and executive orders from the
current Governor's official site.

Arizona's Governor declares an emergency by signing a Declaration of
Emergency, not an executive order, and the declarations themselves are not
posted online. Each one is announced in a news release ("Governor Katie
Hobbs Declares State of Emergency for Gila County Flooding"). Until
2026-09-27 this scraper read only the executive order archive, which holds
no declarations at all, so Arizona showed none. Now:

- Emergency declarations come from the Governor's news releases
  (https://azgovernor.gov/news-releases). A release counts when its title
  says the Governor declared, issued, signed, expanded, extended or ended a
  state of emergency or declaration of emergency. Its date is the release
  date, which is usually the day the declaration was signed. The release
  text's own declaration sentence is added to the description when the
  title names no hazard ("Declares Heat State of Emergency").
- The first run reads every page of releases back to January 2023. Later
  runs read the newest pages only and keep every declaration saved before,
  so the site is asked for a few pages a week, not the whole archive.
- Executive orders still come from https://azgovernor.gov/executive-orders.
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ARCHIVE_URL = "https://azgovernor.gov/executive-orders"
NEWS_URL = "https://azgovernor.gov/news-releases"
NEWS_PAGE_URL = NEWS_URL + "?type%5Bpanopoly_news_article%5D=panopoly_news_article&page={page}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT = 90
REQUEST_PAUSE = 0.5          # seconds between requests to the Governor's site
WEEKLY_NEWS_PAGES = 5        # about four months of releases
MAX_NEWS_PAGES = 150         # the whole archive was 49 pages in September 2026
TERM_START = "2023-01-02"    # Governor Hobbs took office
GOVERNOR = "Katie Hobbs"
EO_SCOPE = "arizona_governor_executive_orders_2023_present"
NEWS_SCOPE = "arizona_governor_news_releases"
ACTION_FIELDS = ("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS = ("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS = ("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE = re.compile(r"\b(wildfires?|forest fires?|wildland fires?|flood(?:s|ing)?|flash flood(?:s|ing)?|severe (?:storms?|weather)|winter storms?|winter weather|snow|ice|freez(?:e|ing)|drought|extreme heat|excessive heat|heat emergency|heat ?waves?|tornado(?:es)?|hail|heavy rain(?:fall)?|high winds?|dust storms?|monsoon|hurricanes?|tropical storms?)\b", re.I)
# A named fire in a declaration title ("Declares State of Emergency Over
# Greer Fire") is a wildfire, though the title never says so.
NAMED_FIRE_RE = re.compile(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)? Fires?\b(?! (?:Marshal|Department|District|Chief|Station|Academy))")
MODIFIER_RE = re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|replac(?:e|es|ed|ing)|terminat(?:e|es|ed|ing|ion)|revok(?:e|es|ed|ing))\b", re.I)
OPERATIONAL_RE = re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|transportation waiver|suspension of regulations?)\b", re.I)
HAZARD_OVERRIDES = {}

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_TEXT_RE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s+(20\d{{2}})\b")
NEWS_PATH_RE = re.compile(r"/news/(20\d{2})/(\d{2})/([^/?#]+?)/?$")
MORE_LINK_RE = re.compile(r"(?i)^(?:learn|read) more\b.*|^more$|^continue reading$")
# The Governor declaring, issuing, signing, widening, extending or ending a
# state emergency. Federal actions ("SBA Approves Disaster Declaration",
# "Condemns FEMA Denial of Disaster Declaration") do not match: their verbs
# are not in this list, and a federal word between the verb and the
# emergency words disqualifies the title.
DECLARATION_TITLE_RE = re.compile(
    r"\b(?P<verb>declares?|declared|issues?|issued|signs?|signed|expands?|expanded|amends?|amended|"
    r"extends?|extended|renews?|renewed|terminates?|terminated|rescinds?|rescinded|lifts?|lifted)\b"
    r"[^.]{0,60}?\b(?:states? of emergency|declarations? of emergency|emergency declarations?)\b",
    re.I)
FEDERAL_RE = re.compile(r"\b(?:FEMA|SBA|USDA|federal|president(?:ial)?|major disaster|statement)\b", re.I)
GOVERNOR_RE = re.compile(r"\b(?:Governor|Hobbs)\b")
BODY_DECLARED_RE = re.compile(
    r"\b(?:declared|declares|declaring|issued|issues|signed|signs|proclaimed|proclaims|expanded|expands|extended|extends)\b"
    r"[^.]{0,60}?\b(?:states? of emergency|declarations? of emergency|emergency declarations?)\b", re.I)


# ---------------------------------------------------------------- fetching

_last_request = [0.0]


def fetch(url: str) -> str:
    """GET a page politely: a pause between requests, and one retry after a
    short wait on a server error or dropped connection."""
    for attempt in (1, 2):
        wait = REQUEST_PAUSE - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            _last_request[0] = time.monotonic()
            if response.status_code < 500 or attempt == 2:
                response.raise_for_status()
                return response.text
        except (requests.ConnectionError, requests.Timeout):
            _last_request[0] = time.monotonic()
            if attempt == 2:
                raise
        time.sleep(5)
    raise RuntimeError(f"could not fetch {url}")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u2013", "-").replace("\u2014", "-")).strip()


def iso_date(match) -> str:
    return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")


# ---------------------------------------------------------------- executive orders

@dataclass(frozen=True)
class Action:
    number: str; title: str; date: str; url: str; text: str
    @property
    def stable_id(self): return "AZ-" + self.number

def normalize_number(raw, date):
    match = re.search(r"20\d{2}-\d{1,2}", raw)
    if match: return match.group(0)
    digits = re.search(r"\b(\d{1,2})\b", raw)
    return f"{date[:4]}-{int(digits.group(1)):02d}" if digits and date else raw.strip()

def parse_listing(html, base_url=ARCHIVE_URL):
    soup = BeautifulSoup(html, "html.parser"); out = []
    seen = set()
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, anchor["href"])
        if "/executive-order/" not in urlparse(href).path or href in seen: continue
        seen.add(href); block = anchor.find_parent(["article", "li", "div"]) or anchor
        blob = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        number_match = re.search(r"Executive Order:\s*(?:Executive Order\s*)?([^\s]+(?:\s+\d+)?)", blob, re.I)
        date_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", blob)
        if not number_match or not date_match: continue
        date = datetime.strptime(date_match.group(0), "%B %d, %Y").strftime("%Y-%m-%d")
        raw_number = number_match.group(1)
        number = normalize_number(raw_number, date)
        title = re.split(r"Executive Order:", blob, maxsplit=1, flags=re.I)[0].strip()
        out.append((number, title, date, href))
    return out

def parse_detail(number, title, date, url, get=fetch):
    soup = BeautifulSoup(get(url), "html.parser"); main = soup.select_one("main") or soup
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    return Action(number, title, date, url, text)

def collect(get=fetch):
    records = []
    for page in range(5):
        url = ARCHIVE_URL + (f"?page={page}" if page else "")
        records.extend(parse_listing(get(url), url))
    unique = {row[0]: row for row in records}
    return sorted((parse_detail(*row, get=get) for row in unique.values()), key=lambda item:(item.date,item.number), reverse=True)

def classify(action):
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind","terminat","revok")): return "termination"
        if word.startswith(("renew","extend")): return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title): return "administrative"
    evidence = action.title + " " + action.text
    if re.search(r"\b(?:hereby|do)\s+(?:declare|proclaim)\b.{0,120}\b(?:state of emergency|disaster)\b", evidence, re.I) or re.search(r"\bdeclar(?:ing|ation of)\b.{0,100}\b(?:state of emergency|disaster)\b", action.title, re.I): return "declaration"
    return "administrative"

def relationships(actions):
    known = {item.number for item in actions}; rows=[]
    for action in actions:
        kind=classify(action)
        if kind not in {"amendment","extension","termination"}: continue
        for target in sorted(set(re.findall(r"\b20\d{2}-\d{1,2}\b", action.title+" "+action.text))-{action.number}):
            if target in known: rows.append({"source_order_id":action.stable_id,"target_order_id":"AZ-"+target,"relationship_type":kind,"relationship_text":action.title,"relationship_source":action.url,"confidence":"high"})
    return rows

def order_rows(actions):
    rows = []
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and bool(HAZARD_RE.search(evidence))
        rows.append({"declaration_id":action.stable_id,"state":"AZ","governor":GOVERNOR,"eo_number":action.number,"action_kind":"executive_order","action_type":kind,"event_description":action.title,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":EO_SCOPE,"document_format":"html","detail_url":action.url,"archive_record_url":action.url})
    return rows


# ---------------------------------------------------------------- news releases

def nearby_date(anchor) -> str:
    """The release date printed next to a listing link: the date in the
    smallest block around the link that holds exactly one date. A block
    holding two or more dates spans several releases, so the search stops
    there rather than borrow a neighbor's date."""
    node = anchor
    for _ in range(8):
        node = node.parent
        if node is None:
            return ""
        dates = {match.group(0) for match in DATE_TEXT_RE.finditer(node.get_text(" ", strip=True))}
        if len(dates) == 1:
            return iso_date(DATE_TEXT_RE.search(node.get_text(" ", strip=True)))
        if len(dates) > 1:
            return ""
    return ""


def parse_news_listing(html, base_url=NEWS_URL) -> list[dict]:
    """Every release linked on one listing page: url, title, date (the
    printed date, or "" if none could be tied to it), and the year and month
    from its address."""
    soup = BeautifulSoup(html, "html.parser")
    items: dict[str, dict] = {}
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, anchor["href"]).split("#")[0]
        match = NEWS_PATH_RE.search(urlparse(href).path)
        if not match:
            continue
        item = items.setdefault(href, {"url": href, "year": int(match.group(1)), "month": int(match.group(2)),
                                       "slug": match.group(3), "title": "", "date": ""})
        text = clean(anchor.get_text(" ", strip=True))
        if text and not MORE_LINK_RE.match(text) and len(text) > len(item["title"]):
            item["title"] = text
        if not item["date"]:
            item["date"] = nearby_date(anchor)
    return list(items.values())


def news_id(url: str) -> str:
    match = NEWS_PATH_RE.search(urlparse(url).path)
    return f"AZ-DECL-{match.group(1)}-{match.group(2)}-{match.group(3)}"


def declaration_kind(title: str) -> str:
    """"declaration", "amendment", "extension" or "termination" when a
    release title announces a state emergency action by the Governor,
    else ""."""
    match = DECLARATION_TITLE_RE.search(title)
    if not match or FEDERAL_RE.search(match.group(0)) or not GOVERNOR_RE.search(title[:match.start()] or title):
        return ""
    verb = match.group("verb").lower()
    if verb.startswith(("terminat", "rescind", "lift")):
        return "termination"
    if verb.startswith(("extend", "renew")):
        return "extension"
    if verb.startswith(("expand", "amend")):
        return "amendment"
    return "declaration"


def parse_news_detail(html) -> tuple[str, str]:
    """(release text, release date) from a release page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style"):
        tag.decompose()
    dated = soup.select_one("article") or soup.select_one("main") or soup
    match = DATE_TEXT_RE.search(clean(dated.get_text(" ", strip=True)))
    for tag in soup.select("nav, aside, footer, form"):
        tag.decompose()
    body = None
    for selector in (".field-name-body", ".field--name-body", "article", "main", "#main-content"):
        body = soup.select_one(selector)
        if body:
            break
    text = clean((body or soup).get_text(" ", strip=True))
    return text, iso_date(match) if match else ""


def declaration_sentence(text: str) -> str:
    """The release's own sentence saying the Governor declared the emergency,
    without a dateline ("PHOENIX - ")."""
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text):
        match = BODY_DECLARED_RE.search(sentence)
        if not match:
            continue
        before = sentence[:match.start()]
        if GOVERNOR_RE.search(before) and not FEDERAL_RE.search(before):
            return re.sub(r"^[A-Z][A-Z .,]*\s*-+\s*", "", sentence).strip()
    return ""


def news_row(item: dict, kind: str, text: str, detail_date: str) -> dict:
    title = item["title"]
    sentence = declaration_sentence(text)
    description = title
    if sentence and not HAZARD_RE.search(title) and HAZARD_RE.search(sentence):
        description = f"{title}. From the release: {sentence}"
    weather = bool(HAZARD_RE.search(description) or NAMED_FIRE_RE.search(title))
    return {"declaration_id": news_id(item["url"]), "state": "AZ", "governor": GOVERNOR, "eo_number": "",
            "action_kind": "emergency_declaration", "action_type": kind, "event_description": description,
            "date_signed": item["date"] or detail_date, "end_date": "", "weather_related": str(weather).lower(),
            "source_scope": NEWS_SCOPE, "document_format": "html", "detail_url": item["url"],
            "archive_record_url": item["url"]}


def news_page_url(page: int) -> str:
    return NEWS_URL if page == 0 else NEWS_PAGE_URL.format(page=page)


def collect_news(saved_rows: list[dict], get=fetch, full: bool = False) -> tuple[list[dict], str]:
    """Emergency declaration rows from the news releases, with the saved ones
    carried forward, and a one-line report for the log."""
    saved = {row["declaration_id"]: row for row in saved_rows}
    backfill = full or not saved
    limit = MAX_NEWS_PAGES if backfill else WEEKLY_NEWS_PAGES
    rows: dict[str, dict] = {}
    seen: set[str] = set()
    pages = releases = 0
    for page in range(limit):
        items = parse_news_listing(get(news_page_url(page)), news_page_url(page))
        pages += 1
        if not items and page == 0:
            raise RuntimeError("Arizona news releases: no releases found on the first page; "
                               "the page layout may have changed")
        # Past the last page the site may still show links it shows on every
        # page (a sidebar, say), so stop at the first page with nothing new.
        items = [item for item in items if item["url"] not in seen]
        if not items:
            break
        seen.update(item["url"] for item in items)
        in_term = [item for item in items if (item["year"], item["month"]) >= (2023, 1)
                   and (not item["date"] or item["date"] >= TERM_START)]
        releases += len(in_term)
        for item in in_term:
            kind = declaration_kind(item["title"])
            if not kind:
                continue
            row_id = news_id(item["url"])
            if row_id in saved and not full:
                rows[row_id] = saved[row_id]
                continue
            text, detail_date = parse_news_detail(get(item["url"]))
            rows[row_id] = news_row(item, kind, text, detail_date)
        if not in_term:
            break               # past the start of the term
    new = [row_id for row_id in rows if row_id not in saved]
    for row_id, row in saved.items():
        rows.setdefault(row_id, row)
    report = (f"Arizona news releases: read {pages} page(s), {releases} release(s) since {TERM_START}"
              f"{' (full archive)' if backfill else ''}; {len(new)} new emergency declaration(s), "
              f"{len(rows)} in all")
    return list(rows.values()), report


# ---------------------------------------------------------------- output

def write_csv(path, fields, rows):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n",extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)

def load_saved_news(path) -> list[dict]:
    try:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            return [row for row in csv.DictReader(handle) if row.get("source_scope") == NEWS_SCOPE]
    except (OSError, csv.Error):
        return []

def write_outputs(actions, actions_out, relationships_out, join_out, news_rows=()):
    rows = order_rows(actions) + list(news_rows)
    rows.sort(key=lambda row: (row["date_signed"], row["declaration_id"]), reverse=True)
    joins = [{field: row[field] for field in JOIN_FIELDS} for row in rows
             if row["action_type"] == "declaration" and row["weather_related"] == "true" and row["date_signed"]]
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,relationships(actions)); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    parser.add_argument("--full-news", action="store_true", help="read every news release page again, not only the newest")
    args=parser.parse_args()
    news_rows, report = collect_news(load_saved_news(args.actions_out), full=args.full_news)
    actions = collect()
    print(report)
    write_outputs(actions,args.actions_out,args.relationships_out,args.join_out,news_rows)
if __name__=="__main__": main()
