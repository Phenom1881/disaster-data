"""Second source for thin Plus states: FMCSA's archive of state emergency
declarations.

When a governor declares an emergency that affects trucking (a winter
storm, a hurricane, a flood), the Federal Motor Carrier Safety
Administration posts a copy, because the declaration suspends hours-of-
service limits. Its yearly archive pages list them by state:

    https://www.fmcsa.dot.gov/emergency/archive-emergency-declarations-2023

    Maine
      Description: Maine Proclamation of Emergency for Hurricane Lee   (link)
      Effective: 09/14/2023
      Expires on: ...

This is not every declaration a state makes, only the ones that touch motor
carriers, but it reaches years the state's own site does not (Nevada's
archive starts in 2023, Maine's in 2011) and it keeps working when a state
site refuses us (Ohio, New Hampshire).

How it is used:
- refresh() reads the archive pages once per run and keeps every entry in
  plus/_fmcsa/entries.csv. An entry whose title names no hazard gets its
  FMCSA page read once, for a sentence that does. If FMCSA cannot be
  reached, the saved entries are used.
- supplement_rows(state, own_rows) returns that state's weather
  declarations, leaving out any within DUPLICATE_DAYS of a declaration the
  state's own source already has, plus extensions, amendments, county or
  city declarations, and non-weather emergencies.
- build-plus.py writes them to plus/<state>/fmcsa_declarations.csv for the
  states marked "fmcsa_supplement" in the manifest. That file is shown on
  the page and joined to storms alongside the state's own file, but kept
  separate so the state's own source is still judged on its own.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

BASE = "https://www.fmcsa.dot.gov"
FIRST_YEAR = 2017
ARCHIVE_URLS = {2017: f"{BASE}/emergency/archive-emergency-declarations-fy17"}
CURRENT_URL = f"{BASE}/emergency-declarations"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 60
REQUEST_PAUSE = 1.0
DUPLICATE_DAYS = 5
SUPPLEMENT_NAME = "fmcsa_declarations.csv"
ENTRY_FIELDS = ("entry_id", "state", "title", "effective", "url", "hazard_text", "archive_page")
JOIN_FIELDS = ("declaration_id", "governor", "eo_number", "event_description", "date_signed",
               "archive_record_url", "source_scope")

STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
          "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
          "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
          "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
          "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina",
          "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
          "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
          "Washington", "West Virginia", "Wisconsin", "Wyoming"]
# Longest names first, so "West Virginia" is not read as "Virginia".
STATE_RE = re.compile(r"^\W*(?:State of |Commonwealth of )?(" + "|".join(
    sorted((re.escape(s) for s in STATES), key=len, reverse=True)) + r")\b", re.I)
EFFECTIVE_RE = re.compile(r"Effective(?: date)?:?\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", re.I)
MODIFIER_RE = re.compile(r"\b(?:extend\w*|extension|amend\w*|renew\w*|rescind\w*|terminat\w*|"
                         r"modif\w*|supplement\w*|continu\w*)\b", re.I)
NOT_STATEWIDE_RE = re.compile(r"\b(?:county|counties of|city of|mayor|manager|parish president|"
                              r"regional emergency declaration|fmcsa|service center)\b", re.I)
NOT_WEATHER_RE = re.compile(r"\b(?:covid|coronavirus|pandemic|pipeline|propane|heating (?:fuel|oil)|"
                            r"fuel (?:shortage|supply|supplies)|gasoline|diesel|cyber|opioid|"
                            r"election|infrastructure failure|water system|bridge|protest|civil unrest)\b",
                            re.I)


def _join_module():
    path = Path(__file__).resolve().parents[1] / "plus" / "virginia" / "eo_storm_join.py"
    spec = importlib.util.spec_from_file_location("plus_fmcsa_join", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("plus_fmcsa_join", module)
    spec.loader.exec_module(module)
    return module


def hazard_types(text: str) -> set:
    return _join_module().compatible_event_types(text)


def archive_urls(today: date) -> dict[int, str]:
    urls = dict(ARCHIVE_URLS)
    for year in range(FIRST_YEAR + 1, today.year + 1):
        urls[year] = f"{BASE}/emergency/archive-emergency-declarations-{year}"
    return urls


def entry_id(url: str) -> str:
    return hashlib.sha1(urlparse(url).path.rstrip("/").encode()).hexdigest()[:12].upper()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("–", "-").replace("—", "-")).strip()


def parse_effective(text: str, page_year: int | None) -> str:
    match = EFFECTIVE_RE.search(text)
    if not match:
        return ""
    month, day, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000
    # Typos happen ("07/09/3023" on the 2023 page); a year far from the page's
    # own year is replaced by the page's year.
    if page_year and abs(year - page_year) > 1:
        year = page_year
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def parse_archive_page(html: str, page_url: str, page_year: int | None) -> list[dict]:
    """Every state entry on one archive page. The state comes from the
    title ("Maine Proclamation ...") or, failing that, the last state
    heading above the entry."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("nav, header, footer, script, style"):
        tag.decompose()
    entries: dict[str, dict] = {}
    heading_state = ""
    in_state_section = False
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "p", "a"]):
        own_text = _clean(node.get_text(" ", strip=True))
        if node.name != "a":
            if re.search(r"state emergency declarations", own_text, re.I):
                in_state_section = True
            exact = next((s for s in STATES if own_text.lower() == s.lower()), "")
            if exact:
                heading_state = exact
            continue
        href = node.get("href", "")
        url = urljoin(page_url, href).split("#")[0]
        if "/emergency/" not in urlparse(url).path or "archive-emergency-declarations" in url:
            continue
        title = own_text
        titled = STATE_RE.match(title)
        state = titled.group(1).title() if titled else (heading_state if in_state_section else "")
        if not state or not title:
            continue
        state = next(s for s in STATES if s.lower() == state.lower())
        # The Effective line follows the link inside the same entry block.
        block = node.find_parent(["li", "p", "div", "tr"]) or node
        text = _clean(block.get_text(" ", strip=True))
        after = text[text.find(title) + len(title):] if title in text else text
        if "Effective" not in after:
            sibling_text = []
            for sibling in node.find_all_next(string=True, limit=40):
                sibling_text.append(str(sibling))
                if "Expires" in str(sibling):
                    break
            after = _clean(" ".join(sibling_text))
        entries[url] = {"entry_id": entry_id(url), "state": state, "title": title,
                        "effective": parse_effective(after, page_year), "url": url,
                        "hazard_text": "", "archive_page": page_url}
    return list(entries.values())


def hazard_sentence(html: str) -> str:
    """The first sentence on an FMCSA declaration page that names a hazard."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("nav, header, footer, script, style, aside"):
        tag.decompose()
    body = soup.select_one("main") or soup.select_one("article") or soup
    text = _clean(body.get_text(" ", strip=True))
    for sentence in re.split(r"(?<=[.;!?])\s+", text):
        if 20 < len(sentence) < 400 and hazard_types(sentence) and not NOT_WEATHER_RE.search(sentence):
            return sentence
    return ""


def load_entries(path: Path) -> dict[str, dict]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return {row["url"]: row for row in csv.DictReader(handle)}
    except (OSError, csv.Error, KeyError):
        return {}


def write_csv(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def refresh(repo_root: Path, get=None, today: date | None = None, states=None) -> str:
    """Read FMCSA's archive pages and update plus/_fmcsa/entries.csv.
    Returns a line for the log. Never raises: a failure keeps the saved
    entries."""
    today = today or date.today()
    path = repo_root / "plus" / "_fmcsa" / "entries.csv"
    saved = load_entries(path)
    if get is None:
        import requests

        def get(url):
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            time.sleep(REQUEST_PAUSE)
            return response.text
    found: dict[str, dict] = {}
    failed = []
    pages = list(archive_urls(today).items()) + [(today.year, CURRENT_URL)]
    for year, url in pages:
        try:
            found.update({e["url"]: e for e in parse_archive_page(get(url), url, year)})
        except Exception as exc:  # one page failing must not lose the rest
            failed.append(f"{year} ({type(exc).__name__})")
    details = 0
    for url, entry in found.items():
        old = saved.get(url)
        if old:
            entry["hazard_text"] = old.get("hazard_text", "")
            entry["effective"] = entry["effective"] or old.get("effective", "")
            continue
        if states is not None and entry["state"] not in states:
            continue            # declaration pages are read only for states that use them
        if hazard_types(entry["title"]) or NOT_WEATHER_RE.search(entry["title"]) \
                or MODIFIER_RE.search(entry["title"]) or NOT_STATEWIDE_RE.search(entry["title"]):
            continue
        try:
            entry["hazard_text"] = hazard_sentence(get(url))
            details += 1
        except Exception:
            pass
    merged = dict(saved)
    merged.update(found)
    rows = sorted(merged.values(), key=lambda e: (e["state"], e["effective"], e["url"]))
    write_csv(path, ENTRY_FIELDS, rows)
    note = (f"FMCSA state declarations: {len(found)} entries read from {len(pages) - len(failed)} "
            f"page(s), {details} declaration page(s) read, {len(rows)} saved in all")
    if failed:
        note += "; pages not read: " + ", ".join(failed)
    return note


def _days_apart(a: str, b: str) -> int:
    try:
        return abs((datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days)
    except ValueError:
        return 10 ** 6


def supplement_rows(state: dict, own_rows: list[dict], entries: dict[str, dict]) -> list[dict]:
    """This state's FMCSA weather declarations not already in own_rows."""
    own_dates = [r.get("date_signed", "") for r in own_rows if r.get("date_signed")]
    rows = []
    for entry in entries.values():
        if entry["state"] != state["name"] or not entry["effective"]:
            continue
        title = entry["title"]
        if MODIFIER_RE.search(title) or NOT_STATEWIDE_RE.search(title) or NOT_WEATHER_RE.search(title):
            continue
        description = title
        if not hazard_types(title):
            if not entry.get("hazard_text"):
                continue
            description = f"{title}. From FMCSA's copy: {entry['hazard_text']}"
        if any(_days_apart(entry["effective"], d) <= DUPLICATE_DAYS for d in own_dates):
            continue
        rows.append({"declaration_id": f"{state['abbreviation']}-FMCSA-{entry['entry_id']}",
                     "governor": "", "eo_number": "", "event_description": description,
                     "date_signed": entry["effective"], "archive_record_url": entry["url"],
                     "source_scope": "fmcsa_state_emergency_declarations"})
    # Two FMCSA copies of one declaration a few days apart count once.
    rows.sort(key=lambda r: r["date_signed"])
    unique = []
    for row in rows:
        if unique and _days_apart(unique[-1]["date_signed"], row["date_signed"]) <= DUPLICATE_DAYS \
                and hazard_types(unique[-1]["event_description"]) & hazard_types(row["event_description"]):
            continue
        unique.append(row)
    return unique
