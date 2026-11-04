#!/usr/bin/env python3
"""
Official-source links for the Declaration Tracker.

FEMA's Daily Operations Briefing used to show every pending request for a
federal disaster or emergency declaration. Since it stopped (after October
29, 2026), the people who announce those requests, and usually the decisions,
are the governors' offices themselves. This module reads their newsrooms once
a day, picks out releases about federal declarations, and links each one to
the request it is about, so every status on the tracker points at an official
source anyone can open.

How a release gets onto the page
  1. Newsrooms are listed in scripts/declaration_source_feeds.csv (an RSS
     feed or a plain HTML listing page). robots.txt is read first and obeyed,
     the crawler names itself, and each site gets at most one request every
     few seconds (longer if its robots.txt asks).
  2. Only releases whose headline is about a federal declaration are opened.
     State proclamations, SBA and USDA designations are left out.
  3. The release is classified (request, approval or denial; DR or EM) and
     matched to a tracked request from the same state.
  4. Strong matches go straight into archive/ops-briefings/
     declaration-sources.csv: the headline itself says what happened, the
     declaration type is clear, and exactly one tracked request fits. A new
     request (one the briefing never listed) is added the same way.
  5. Everything else waits in declaration-sources-review.csv. Put "accept"
     (or "reject") in its decision column; the next run moves it. A
     different request_id can be typed into suggested_request_id first.

Rows can also be added to declaration-sources.csv by hand (added_by
"manual") after reading the release.
"""

from __future__ import annotations

import csv
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
FEEDS_PATH = HERE / "declaration_source_feeds.csv"

FEED_FIELDS = ["code", "requester", "publisher", "kind", "url", "checked", "note"]
ACCEPTED_FIELDS = ["url", "request_id", "action", "type", "state", "requester", "publisher",
                   "title", "published", "added", "added_by", "note"]
REVIEW_FIELDS = ["decision", "url", "suggested_request_id", "action", "type", "state", "requester",
                 "publisher", "title", "published", "found", "reason"]

ACTIONS = ("request", "approved", "denied", "unclear")
MAX_RELEASES_PER_SOURCE = 5      # release pages opened per newsroom per run
MIN_INTERVAL = 3.0               # seconds between requests to one host
MAX_CRAWL_DELAY = 30.0           # cap on a robots.txt crawl-delay we honor
TIME_BUDGET = 12 * 60            # seconds for the whole crawl
TIMEOUT = 20

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}

# --------------------------------------------------------------------------
# Classifying a release
# --------------------------------------------------------------------------

HEADLINE = re.compile(
    r"(?i)\b(major\s+(presidential\s+)?disaster|presidential\s+(disaster|emergency|declaration)|"
    r"federal\s+(disaster|emergency|major)|disaster\s+declaration|emergency\s+declaration|"
    r"declaration\s+of\s+(a\s+)?major|FEMA)\b")
# Not federal declarations, whatever else the headline says.
NOT_FEMA = re.compile(
    r"(?i)\b(SBA|small\s+business\s+administration|USDA|department\s+of\s+agriculture|"
    r"agricultur\w*|secretarial|physical\s+disaster|drought\s+designation|disaster\s+designation|"
    r"public\s+law\s+84|PL\s*84-99|army\s+corps)\b")
FEDERAL = re.compile(r"(?i)\b(president\w*|FEMA|federal\s+emergency\s+management|federal|major\s+(presidential\s+)?disaster)\b")
DECLARATION = re.compile(r"(?i)\bdeclar\w*")
STATE_ONLY = re.compile(r"(?i)\b(state\s+of\s+(emergency|disaster)|disaster\s+proclamation|executive\s+order)\b")

DENIED = re.compile(r"(?i)\b(den(y|ies|ied|ial)|turn(s|ed)?\s+down|reject(s|ed|ion)?)\b")
APPROVED = re.compile(r"(?i)\b(approv(e|es|ed|al)|granted|grants\s+(the\s+|a\s+)?(request|declaration|major|emergency))\b")
APPROVED_WEAK = re.compile(r"(?i)\b(secures|secured|receives|received|wins|won|lands|landed)\b")
APPEALING = re.compile(r"(?i)\b(appeals|appealed|appealing|files?\s+(an\s+)?appeal|submits?\s+(an\s+)?appeal)\b")
REQUEST = re.compile(r"(?i)\b(request(s|ed|ing)?|ask(s|ed|ing)?|seek(s|ing)?|sought|submit(s|ted|ting)?|"
                     r"petition(s|ed)?|calls?\s+for|urges?)\b")
HYPOTHETICAL = re.compile(r"(?i)\b(if|would|once|should)\s+(the\s+)?(request\s+is\s+)?(approv|grant)\w*")
APPEAL = re.compile(r"(?i)\bappeal")

LEAD_DENIED = re.compile(r"(?i)(den(y|ies|ied)|turned\s+down|rejected)[^.]{0,120}declar\w*|declar\w*[^.]{0,80}(was|been|were)\s+(denied|turned\s+down|rejected)")
LEAD_APPROVED = re.compile(r"(?i)(approv(es|ed)|granted)[^.]{0,120}declar\w*|declar\w*[^.]{0,80}(was|been|were)\s+(approved|granted)")
LEAD_REQUEST = re.compile(r"(?i)(request(s|ed)|ask(s|ed)|seek(s|ing)|submitt(ed|ing))[^.]{0,120}declar\w*")

EM_WORDS = re.compile(r"(?i)\b(federal|presidential)?\s*emergency\s+declaration\b|\bdeclaration\s+of\s+(an?\s+)?emergency\b")
DR_WORDS = re.compile(r"(?i)\bmajor\s+(presidential\s+)?disaster\b|\bdeclaration\s+of\s+(a\s+)?major\b")
DISASTER_WORDS = re.compile(r"(?i)\b(federal|presidential)\s+disaster\s+declaration\b")
DR_PROGRAMS = re.compile(r"(?i)\b(public\s+assistance|individual\s+assistance|hazard\s+mitigation)\b")
PROGRAMS = {"IA": re.compile(r"(?i)\bindividual\s+assistance\b"),
            "PA": re.compile(r"(?i)\bpublic\s+assistance\b"),
            "HM": re.compile(r"(?i)\bhazard\s+mitigation\b")}


def is_candidate_headline(title: str) -> bool:
    """Worth opening: the headline talks about a federal declaration."""
    return bool(HEADLINE.search(title or "")) and not NOT_FEMA.search(title or "")


def _action(text: str) -> str | None:
    """Headline verbs, strongest first. "Appeals denial" is a new appeal
    (a request), not a denial; "requests ... to secure" is a request."""
    if APPEALING.search(text) and not re.search(r"(?i)appeal\w*\s+(is\s+|was\s+)?(denied|approved|granted|rejected)", text):
        return "request"
    if DENIED.search(text):
        return "denied"
    if APPROVED.search(text) and not HYPOTHETICAL.search(text):
        return "approved"
    if REQUEST.search(text):
        return "request"
    if APPROVED_WEAK.search(text):
        return "approved"
    return None


def declaration_type(title: str, lead: str) -> str | None:
    """DR or EM, from the headline first, then the opening paragraphs."""
    for text in (title, lead):
        dr, em = bool(DR_WORDS.search(text)), bool(EM_WORDS.search(text))
        if dr != em:
            return "DR" if dr else "EM"
        if dr and em:
            return None
    if DISASTER_WORDS.search(title + " " + lead) and DR_PROGRAMS.search(title + " " + lead):
        return "DR"
    return None


def classify(title: str, lead: str) -> dict | None:
    """What a release says, or None if it isn't about a federal declaration."""
    title, lead = title or "", (lead or "")[:1500]
    both = f"{title} {lead}"
    if NOT_FEMA.search(title):
        return None
    if not (FEDERAL.search(both) and DECLARATION.search(both)):
        return None
    if STATE_ONLY.search(title) and not FEDERAL.search(title):
        return None
    action, from_title = _action(title), True
    if action is None:
        from_title = False
        if LEAD_DENIED.search(lead):
            action = "denied"
        elif LEAD_APPROVED.search(lead) and not HYPOTHETICAL.search(lead[:400]):
            action = "approved"
        elif LEAD_REQUEST.search(lead):
            action = "request"
    if action is None:
        action, from_title = "unclear", False  # federal, but what happened needs a person
    return {
        "action": action,
        "from_title": from_title,
        "type": declaration_type(title, lead),
        "appeal": bool(APPEAL.search(both)),
        "programs": [p for p, rx in PROGRAMS.items() if rx.search(lead)],
    }


# --------------------------------------------------------------------------
# Reading pages
# --------------------------------------------------------------------------

class _PageParser(HTMLParser):
    """Pulls links, meta tags, <time> stamps and readable text out of HTML."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self.times: list[str] = []
        self.title = ""
        self._a: list | None = None
        self._skip = 0
        self._main = 0
        self._in_title = False
        self.text: list[str] = []
        self.main_text: list[str] = []
        self.jsonld: list[str] = []
        self._jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._a = [a["href"], ""]
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "time" and a.get("datetime"):
            self.times.append(a["datetime"])
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._jsonld = True
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("main", "article"):
            self._main += 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._add("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            self.links.append((self._a[0], re.sub(r"\s+", " ", self._a[1]).strip()))
            self._a = None
        elif tag == "title":
            self._in_title = False
        elif tag == "script":
            self._jsonld = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in ("main", "article") and self._main:
            self._main -= 1

    def handle_data(self, data):
        if self._jsonld:
            self.jsonld.append(data)
            return
        if self._in_title:
            self.title += data
        if self._a is not None:
            self._a[1] += data
        if not self._skip:
            self._add(data)

    def _add(self, data):
        self.text.append(data)
        if self._main:
            self.main_text.append(data)


def parse_html(html: str) -> _PageParser:
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001  (a broken page still yields what was read)
        pass
    return parser


def _clean(parts: list[str]) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parts))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _date_from_text(text: str) -> str | None:
    m = re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)\b", text)
    if not m:
        return None
    key = m.group(1).lower()
    month = next((v for k, v in MONTHS.items() if k.startswith(key[:3])), None)
    try:
        return date(int(m.group(3)), month, int(m.group(2))).isoformat()
    except (TypeError, ValueError):
        return None


def _iso(stamp: str | None) -> str | None:
    if not stamp:
        return None
    m = re.match(r"(20\d\d)-(\d\d)-(\d\d)", stamp.strip())
    if m:
        return "-".join(m.groups())
    try:
        return parsedate_to_datetime(stamp).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return _date_from_text(stamp)


def release_date(page: _PageParser, url: str) -> str | None:
    """The day a release went out. Feed dates can be edit dates, so the
    page itself is trusted first."""
    for key in ("article:published_time", "datepublished", "dcterms.date", "dc.date.issued",
                "dc.date", "date", "pubdate", "publish-date", "og:published_time"):
        if _iso(page.meta.get(key)):
            return _iso(page.meta[key])
    for blob in page.jsonld:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', blob)
        if m and _iso(m.group(1)):
            return _iso(m.group(1))
    for stamp in page.times:
        if _iso(stamp):
            return _iso(stamp)
    body = _clean(page.main_text) or _clean(page.text)
    m = re.search(r"(?i)(for\s+immediate\s+release|posted\s+on|released|published)[:\s]*([A-Za-z]+\.?\s+\d{1,2},?\s+20\d\d)", body)
    if m:
        return _date_from_text(m.group(2))
    found = _date_from_text(body[:800])
    if found:
        return found
    m = re.search(r"/(20\d\d)(\d\d)(\d\d)[a-z]?\.", url) or re.search(r"/(20\d\d)/(\d\d)/(\d\d)/", url)
    return "-".join(m.groups()) if m else None


def release_lead(page: _PageParser, title: str) -> str:
    """The opening of the release itself, not the menus or related links."""
    body = _clean(page.main_text) or _clean(page.text)
    cut = re.search(r"(?im)^\s*(related\s+(news|stories|posts|articles)|more\s+news|recent\s+news|share\s+this)\b", body)
    if cut:
        body = body[:cut.start()]
    return body[:2000]


def parse_listing(text: str, base: str, kind: str) -> list[dict]:
    """Releases on a newsroom page or feed: url, title, and the feed date if any."""
    items: list[dict] = []
    if kind == "rss":
        try:
            root = ElementTree.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
        except ElementTree.ParseError:
            return []
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag not in ("item", "entry"):
                continue
            get = {c.tag.rsplit("}", 1)[-1]: c for c in node}
            link = get.get("link")
            href = (link.get("href") if link is not None and link.get("href") else
                    (link.text or "").strip() if link is not None else "")
            title = (get["title"].text or "").strip() if "title" in get else ""
            stamp = None
            for key in ("pubDate", "published", "updated", "date"):
                if key in get and get[key].text:
                    stamp = get[key].text
                    break
            if href and title:
                items.append({"url": urljoin(base, href), "title": re.sub(r"\s+", " ", title),
                              "feed_date": _iso(stamp)})
        return items
    page = parse_html(text)
    host = urlparse(base).netloc.lower().removeprefix("www.")
    seen = set()
    for href, label in page.links:
        url = urldefrag(urljoin(base, href)).url
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or parts.netloc.lower().removeprefix("www.") != host:
            continue
        if re.search(r"(?i)\.(pdf|jpe?g|png|gif|docx?|xlsx?|mp4|zip)$", parts.path):
            continue
        label = re.sub(r"(?i)^(read\s+more\s+)?(about\s+the\s+article:\s*)", "", label).strip()
        if len(label) < 25 or url in seen or url.rstrip("/") == base.rstrip("/"):
            continue
        seen.add(url)
        items.append({"url": url, "title": label, "feed_date": None})
    return items


# --------------------------------------------------------------------------
# Fetching politely
# --------------------------------------------------------------------------

class Blocked(Exception):
    """robots.txt says no."""


class Fetcher:
    """One polite HTTP client: obeys robots.txt, names itself, spaces requests."""

    def __init__(self, user_agent: str, budget: float = TIME_BUDGET, session=None, sleep=time.sleep,
                 clock=time.monotonic):
        if session is None:
            import requests  # installed by the daily job
            session = requests.Session()
        self.session = session
        self.user_agent = user_agent
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last: dict[str, float] = {}
        self.sleep = sleep
        self.clock = clock
        self.deadline = clock() + budget

    def out_of_time(self) -> bool:
        return self.clock() > self.deadline

    def _robots(self, url: str) -> RobotFileParser | None:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.robots:
            rp = RobotFileParser()
            try:
                resp = self._raw(root + "/robots.txt")
                if resp.status_code in (401, 403):
                    rp.disallow_all = True
                elif resp.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(resp.text.splitlines())
            except Exception:  # noqa: BLE001  no robots.txt reachable: treat as no rules
                rp.allow_all = True
            self.robots[root] = rp
        return self.robots[root]

    def _wait(self, host: str, delay: float) -> None:
        gap = self.clock() - self.last.get(host, -1e9)
        if gap < delay:
            self.sleep(delay - gap)
        self.last[host] = self.clock()

    def _raw(self, url: str):
        self._wait(urlparse(url).netloc, MIN_INTERVAL)
        return self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": self.user_agent},
                                allow_redirects=True)

    def get(self, url: str) -> str:
        rp = self._robots(url)
        if rp is not None and not rp.can_fetch(self.user_agent, url):
            raise Blocked(url)
        delay = rp.crawl_delay(self.user_agent) if rp is not None else None
        host = urlparse(url).netloc
        self._wait(host, min(max(float(delay or 0), MIN_INTERVAL), MAX_CRAWL_DELAY))
        resp = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": self.user_agent},
                                allow_redirects=True)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        final = getattr(resp, "url", url) or url
        if final != url:  # a redirect lands on a page robots.txt may still forbid
            rp2 = self._robots(final)
            if rp2 is not None and not rp2.can_fetch(self.user_agent, final):
                raise Blocked(final)
        return resp.text


# --------------------------------------------------------------------------
# Matching a release to a request
# --------------------------------------------------------------------------

def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


OPENISH = {"open", "left_brief"}


def match(item: dict, requests: list[dict]) -> tuple[str | None, bool, str]:
    """(request id, "new", or None; strong?; reason) for a classified release."""
    pub, action, typ = item["published"], item["action"], item["type"]
    pool = [r for r in requests if r["state"] == item["state"] and not r.get("tribe")]
    if typ:
        pool = [r for r in pool if r["type"] == typ]
    certain = item["from_title"] and bool(typ)

    if action == "request":
        fits = [r for r in pool if -1 <= _days(pub, r["requested"]) <= 10]
        if item["appeal"] and any(r["appeal"] for r in fits):
            fits = [r for r in fits if r["appeal"]]
        if len(fits) == 1:
            return fits[0]["id"], certain, "request filed within 10 days before the release"
        if fits:
            return _closest(fits, pub), False, f"{len(fits)} tracked requests fit"
        near = [r for r in pool if r["status"] in OPENISH | {"open"} and abs(_days(pub, r["requested"])) <= 21]
        if near:
            return near[0]["id"], False, "no exact fit, but an open request from the same state is close in date"
        return "new", certain, "no tracked request fits: a new request"

    def fits_decision(r: dict) -> bool:
        if r["requested"] > pub:
            return False
        if r["status"] in OPENISH:
            if r["status"] == "left_brief" and r.get("last_seen") and _days(pub, r["last_seen"]) > 30:
                return False
            return True
        same = {"approved": ("declared", "approved_per_brief", "approved_per_source"),
                "denied": ("turned_down", "denied_per_brief", "denied_per_source")}[action]
        return r["status"] in same and r.get("decision_date") is not None and abs(_days(pub, r["decision_date"])) <= 7

    fits = [r for r in pool if fits_decision(r)]
    if item["appeal"] and any(r["appeal"] for r in fits):
        fits = [r for r in fits if r["appeal"]]
    if len(fits) == 1:
        return fits[0]["id"], item["from_title"], f"the only tracked request it can be {action}"
    if fits:
        return _closest(fits, pub), False, f"{len(fits)} tracked requests could be {action}"
    return None, False, f"no tracked request from {item['state']} fits this {action}"


def _closest(reqs: list[dict], pub: str) -> str:
    return min(reqs, key=lambda r: abs(_days(pub, r["requested"])))["id"]


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") or "" for k in fields})
    tmp.replace(path)


def load_feeds(path: Path = FEEDS_PATH) -> list[dict]:
    return [r for r in read_csv(path) if r.get("url")]


def apply_review_decisions(accepted_path: Path, review_path: Path, today: str) -> list[str]:
    """Move reviewed rows: accepted ones into the accepted file, rejected ones
    out of the queue. Returns the rejected URLs so they are never queued again."""
    accepted = read_csv(accepted_path)
    have = {r["url"] for r in accepted}
    keep, rejected = [], []
    for row in read_csv(review_path):
        decision = (row.get("decision") or "").strip().lower()
        if decision in ("accept", "accepted", "yes", "y"):
            if row["url"] not in have:
                accepted.append({**row, "request_id": row.get("suggested_request_id", ""),
                                 "added": today, "added_by": "review", "note": row.get("reason", "")})
                have.add(row["url"])
        elif decision in ("reject", "rejected", "no", "n"):
            rejected.append(row["url"])
        else:
            keep.append(row)
    write_csv(accepted_path, ACCEPTED_FIELDS, accepted)
    write_csv(review_path, REVIEW_FIELDS, keep)
    return rejected


# --------------------------------------------------------------------------
# Putting sources on requests
# --------------------------------------------------------------------------

def announced_id(row: dict) -> str:
    return f"{row['state'].lower()}-{row['type'].lower()}-{row['published']}-announced"


def announced_requests(accepted: list[dict], state_names: dict[str, str]) -> list[dict]:
    """Requests the briefing never listed, from accepted request releases."""
    out, seen = [], set()
    for row in accepted:
        if row.get("action") != "request" or row.get("request_id") != "new":
            continue
        if not (row.get("state") and row.get("type") in ("DR", "EM") and row.get("published")):
            continue
        rid = announced_id(row)
        if rid in seen:
            continue
        seen.add(rid)
        out.append({
            "id": rid, "code": row["state"], "state": row["state"], "tribe": None,
            "requester": row.get("requester") or state_names.get(row["state"], row["state"]),
            "type": row["type"], "appeal": "appeal" in (row.get("title") or "").lower(),
            "incident": "", "requested": row["published"], "requested_dates_listed": [row["published"]],
            "programs": None, "first_seen": None, "last_seen": None, "last_listed_pending": None,
            "days_listed": 0, "brief_status": None, "brief_status_date": None, "source": "announced",
        })
    return out


def attach(requests: list[dict], accepted: list[dict]) -> list[dict]:
    """Hang each accepted release on its request and let releases settle what
    OpenFEMA hasn't yet. Returns rows whose request could not be found."""
    by_id = {r["id"]: r for r in requests}
    orphans = []
    for req in requests:
        req["sources"] = []
    for row in accepted:
        rid = announced_id(row) if row.get("request_id") == "new" and row.get("action") == "request" \
            and row.get("type") and row.get("published") and row.get("state") else row.get("request_id")
        req = by_id.get(rid)
        if req is None:
            orphans.append(row)
            continue
        req["sources"].append({k: row.get(k, "") for k in
                               ("action", "url", "title", "publisher", "published", "added_by")})
    for req in requests:
        req["sources"].sort(key=lambda s: (s["published"] or "", s["action"]))
        if req["status"] not in OPENISH:
            continue
        for action, status in (("denied", "denied_per_source"), ("approved", "approved_per_source")):
            dates = sorted(s["published"] for s in req["sources"] if s["action"] == action and s["published"])
            if dates:
                req["status"], req["decision_date"] = status, dates[0]
                req["days"] = _days(dates[0], req["requested"])
                break
    return orphans


# --------------------------------------------------------------------------
# The daily crawl
# --------------------------------------------------------------------------

def crawl(feeds: list[dict], requests: list[dict], fetcher: Fetcher, accepted_path: Path,
          review_path: Path, ignored: set[str], today: str) -> list[dict]:
    """Read every newsroom, file what it finds, and report each source's health."""
    accepted = read_csv(accepted_path)
    review = read_csv(review_path)
    known = {r["url"] for r in accepted} | {r["url"] for r in review} | set(ignored)
    health = []
    for feed in feeds:
        report = {"code": feed["code"], "requester": feed.get("requester", ""), "publisher": feed.get("publisher", ""),
                  "url": feed["url"], "kind": feed.get("kind", ""), "status": "", "releases_listed": 0,
                  "opened": 0, "added": 0, "queued": 0, "checked_at": today}
        health.append(report)
        if feed.get("kind") == "skip":
            report["status"] = "skipped: " + (feed.get("note") or "not read")
            continue
        if fetcher.out_of_time():
            report["status"] = "not reached: the run's time limit was used up"
            continue
        try:
            listing = parse_listing(fetcher.get(feed["url"]), feed["url"], feed.get("kind", "html"))
        except Blocked:
            report["status"] = "blocked by robots.txt"
            continue
        except Exception as exc:  # noqa: BLE001
            report["status"] = f"could not be read ({type(exc).__name__}: {str(exc)[:60]})"
            continue
        report["releases_listed"] = len(listing)
        report["status"] = "ok" if listing else "no releases found on the page"
        fresh = [i for i in listing if is_candidate_headline(i["title"]) and i["url"] not in known]
        for item in fresh[:MAX_RELEASES_PER_SOURCE]:
            if fetcher.out_of_time():
                break
            try:
                html = fetcher.get(item["url"])
            except Blocked:
                ignored.add(item["url"])
                continue
            except Exception:  # noqa: BLE001  try again tomorrow
                continue
            report["opened"] += 1
            page = parse_html(html)
            title = item["title"] if len(item["title"]) >= 25 else (page.title or item["title"])
            title = re.sub(r"\s*[\u2013\u2014]\s*", " - ", title).strip()
            lead = release_lead(page, title)
            what = classify(title, lead)
            known.add(item["url"])
            if what is None:
                ignored.add(item["url"])
                continue
            found = {"url": item["url"], "title": title, "state": feed["code"],
                     "requester": feed.get("requester", ""), "publisher": feed.get("publisher", ""),
                     "published": release_date(page, item["url"]) or item.get("feed_date") or today,
                     **what}
            if found["action"] == "unclear":
                rid, strong, reason = None, False, "about a federal declaration, but it does not say requested, approved or denied"
            else:
                rid, strong, reason = match(found, requests)
            row = {**found, "type": found["type"] or ""}
            if strong and rid:
                accepted.append({**row, "request_id": rid, "added": today, "added_by": "auto", "note": reason})
                report["added"] += 1
            else:
                review.append({**row, "decision": "", "suggested_request_id": rid or "", "found": today,
                               "reason": reason + ("" if what["from_title"] else "; the headline alone does not say what happened")
                               + ("" if found["type"] else "; DR or EM is unclear")})
                report["queued"] += 1
    write_csv(accepted_path, ACCEPTED_FIELDS, accepted)
    write_csv(review_path, REVIEW_FIELDS, review)
    return health
