#!/usr/bin/env python3
"""
Kansas disaster-declaration scraper for the DisasterData Plus corridor.

Source (real, structured, publicly accessible, confirmed fetchable - not
robots-blocked): the Kansas Adjutant General's Department (KDEM) page
    https://www.kansastag.gov/388/Kansas-Disaster-Declarations
which lists, grouped by year (2009-present), every State of Disaster
Emergency Proclamation with a direct link to the real signed PDF hosted
at kansastag.gov/DocumentCenter/View/<id>/<slug>.

This is Kansas's own emergency-management system of record, distinct
from (and a much more reliable machine-readable source than) the Kansas
Register's per-issue HTML pages at sos.ks.gov, which publish the same
proclamations but one issue at a time with no combined index.

CLI contract (matches every other Plus-corridor state adapter):
    --actions-out         <path>   raw per-row action records (debug/audit trail)
    --relationships-out   <path>   year -> declaration link graph (debug/audit trail)
    --join-out            <path>   declarations_for_join.csv (the file build-plus.py reads)
"""
import argparse
import csv
import re
import sys
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

STATE = "KS"
BASE = "https://www.kansastag.gov"
SOURCE_URL = f"{BASE}/388/Kansas-Disaster-Declarations"
SCOPE_START = datetime(2000, 1, 1)

# Kansas governors by inauguration date (month-precision is enough for
# every date range this page lists back to 2009).
GOVERNOR_BY_DATE = [
    (datetime(2009, 4, 28), "Mark Parkinson"),
    (datetime(2011, 1, 10), "Sam Brownback"),
    (datetime(2018, 1, 31), "Jeff Colyer"),
    (datetime(2019, 1, 14), "Laura Kelly"),
]

# Entries whose PDF filename/slug or bracketing text signals they are not
# a weather/disaster proclamation at all, or that the page itself appears
# to have a data-entry problem (see README / summary report). Left out of
# declarations_for_join.csv rather than silently included, and reported.
NON_WEATHER_OR_SUSPECT_SLUGS = {
    "hantavirus",
    "gas-leak",
    "world-cup",
    "explosion",
    "covid",
    "coronavirus",
}

# This scraper only parses the modern one-heading-per-event format the
# page uses for 2016-present. 2009-2015 group several declarations under
# a single combined "State Declaration (PDF)" per year with Federal
# DR/EM/FM references mixed in above it - a structurally different
# layout that this version does not attempt to parse (see known_gaps in
# kansas.py / the delivery's summary report, rather than risk silently
# mis-attributing a heading).
MODERN_FORMAT_MIN_YEAR = 2016

DOC_LINK_RE = re.compile(r"/DocumentCenter/View/(\d+)", re.IGNORECASE)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# A declaration's heading: its dates and a hazard in parentheses, e.g.
# "April 25 - April 27 (Severe Weather)" or "May 12 - Continuing (Drought)".
# The parenthesis must hold a hazard, not a file type ("State Declaration
# (PDF)" is a link label, not a heading), and a heading carries a date.
HEADING_RE = re.compile(r"\d[^()]*\((?!\s*(?:pdf|docx?|xlsx?)\s*\))[^()]*[A-Za-z][^()]*\)\s*$", re.I)
DECLARATION_LINK_RE = re.compile(r"declar|proclam", re.IGNORECASE)
SKIP_LINK_RE = re.compile(r"amend|federal|extension|rescind|terminat", re.IGNORECASE)
_LABEL_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "li", "span", "strong",
               "b", "p", "div", "dt", "summary", "label", "th", "td"}
_BLOCK_TAGS = ("li", "p", "div", "td", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6")


def governor_for(date_obj):
    gov = GOVERNOR_BY_DATE[0][1]
    for cutoff, name in GOVERNOR_BY_DATE:
        if date_obj >= cutoff:
            gov = name
    return gov


def fetch(url, session):
    resp = session.get(url, timeout=30, headers={"User-Agent": "DisasterData.io research crawler"})
    resp.raise_for_status()
    return resp.text


def _clean(text):
    return " ".join((text or "").split())


def _year_label(tag, max_year):
    """The year a tab, button or heading shows, if its whole text is a year."""
    if not isinstance(tag, Tag) or tag.name not in _LABEL_TAGS:
        return None
    text = _clean(tag.get_text(" ", strip=True))
    if YEAR_RE.fullmatch(text) and 2009 <= int(text) <= max_year:
        return int(text)
    return None


def _panel_years(soup, max_year):
    """{panel element id: year} for tab or accordion labels that point at
    their panel (href="#id", aria-controls, data-target). Tab labels sit
    together above the panels, so document order alone would give every
    panel the last label's year."""
    years = {}
    for tag in soup.find_all(True):
        year = _year_label(tag, max_year)
        if year is None:
            continue
        for attr in ("aria-controls", "data-target", "data-bs-target", "data-tab", "href"):
            target = (tag.get(attr) or "").strip()
            if attr == "href" and not target.startswith("#"):
                continue
            target = target.lstrip("#")
            if target:
                years.setdefault(target, year)
    return years


def _heading_like(text):
    """Shaped like an entry heading HEADING_RE did not accept: it starts with
    a month and day, or ends in a capitalized parenthesis ("Statewide
    (Drought)"). A note such as "Counties: Allen, Bourbon (see map)" is not."""
    return bool(re.match(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d", text, re.I)
                or re.search(r"^[^:]*\([A-Z][^()]*\)\s*$", text))


# Tab labels are links or buttons in a strip above the panels; a heading
# (h2, strong, p ...) sits right above its own entries.
_TAB_LABEL_TAGS = {"a", "button", "li"}


def _is_tab_label(tag):
    """A tab or accordion control, not a heading: a link, button or list item,
    or anything marked as a tab (role="tab", aria-controls, data-target), or
    inside such an element."""
    for el in [tag] + [p for p in tag.parents if isinstance(p, Tag)][:2]:
        if el.name in _TAB_LABEL_TAGS or el.get("role") == "tab" or any(
                el.get(a) for a in ("aria-controls", "data-target", "data-bs-target", "data-tab")):
            return True
    return False


def parse_declarations_page(html, max_year=None):
    """Parse the Kansas Disaster Declarations page into a list of dicts:
    {year, heading, pdf_url, doc_id}.

    Reads the page's HTML structure rather than a flattened text copy of it.
    The earlier version flattened the page and expected each year alone on a
    line, but kansastag.gov shows its years as tab labels (links), which
    flattened to "[2026](#...)" and never matched, so every run found 0
    records. A declaration's year now comes from the tab panel it sits in
    (matched by the label's target), or from the nearest year heading above
    it. Its heading is the "Dates (Hazard)" line right before its link: text
    is read line by line (a block, a <br>, or a link ends a line), and a
    heading is used for one link only, so an entry whose own heading is not
    understood is skipped rather than given its neighbour's.
    Deliberately tolerant of the page's inconsistent capitalization ("State
    Declaration" / "Sate Declaration") and its 2024 entries, which reuse the
    same DocumentCenter id for two different headings (a real error on
    kansastag.gov itself - see the summary report)."""
    max_year = max_year or datetime.now().year + 1
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    panel_years = _panel_years(soup, max_year)
    is_label = _year_label_child(max_year)

    records, seen_docs = [], set()
    st = {"year": None, "heading": None, "streak": 0}
    line, line_block = [], [None]

    def end_line():
        text = _clean(" ".join(line)).strip(" -\u2013\u2014:|,")
        line.clear()
        if not text or YEAR_RE.fullmatch(text):
            return
        st["streak"] = 0            # any text between year labels: not a tab strip
        if HEADING_RE.search(text):
            st["heading"] = text
        elif _heading_like(text):
            # An entry heading this parser does not understand: the heading
            # before it must not carry over to the link after it.
            st["heading"] = None

    for node in soup.descendants:
        if isinstance(node, Tag):
            if node.name == "br":
                end_line()
                continue
            year = _year_label(node, max_year)
            if year is not None and node.find(is_label) is None:
                end_line()
                if _is_tab_label(node):
                    st["streak"] += 1
                    # Two or more tab labels in a row with nothing between
                    # them are a tab strip, not a heading above its entries.
                    st["year"] = None if st["streak"] >= 2 else year
                else:
                    st["streak"], st["year"] = 0, year
                st["heading"] = None
                continue
            if node.name == "a" and DOC_LINK_RE.search(node.get("href", "")):
                end_line()
                st["streak"] = 0
                text = _clean(node.get_text(" ", strip=True))
                doc_id = DOC_LINK_RE.search(node["href"]).group(1)
                heading = text if HEADING_RE.search(text) else st["heading"]
                is_decl = bool(DECLARATION_LINK_RE.search(text)) or bool(HEADING_RE.search(text))
                if not is_decl or SKIP_LINK_RE.search(text) or not heading:
                    continue                 # an amended copy or a map does not use up the heading
                st["heading"] = None         # one declaration per heading
                year = next((panel_years[p["id"]] for p in node.parents
                             if isinstance(p, Tag) and p.get("id") in panel_years), st["year"])
                if year is None or year < MODERN_FORMAT_MIN_YEAR or doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                records.append({"year": str(year), "heading": heading,
                                "pdf_url": urljoin(BASE, node["href"]), "doc_id": doc_id})
            continue
        if not isinstance(node, NavigableString) or isinstance(node, Comment) or not node.strip():
            continue
        link = node.find_parent("a")
        if link is not None and DOC_LINK_RE.search(link.get("href", "")):
            continue
        block = node.find_parent(_BLOCK_TAGS + ("ul", "ol"))
        if block is not line_block[0]:
            end_line()
            line_block[0] = block
        line.append(str(node))
    end_line()
    return records


def _year_label_child(max_year):
    """Matcher for a descendant that is itself a year label, so only the
    innermost label element counts (a <li><a>2026</a></li> is one label)."""
    def match(tag):
        return _year_label(tag, max_year) is not None
    return match


def slug_years(pdf_url):
    """Years written in a PDF's file name, e.g. Jan-24-2026-Winter-Storm.
    Only the name after the document number counts: .../View/2019 is
    document 2019, not the year 2019."""
    m = re.search(r"/DocumentCenter/View/\d+/?([^?#]*)", pdf_url, re.I)
    slug = m.group(1) if m else ""
    return {int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", slug)}


def describe_page(html, limit=8):
    """A short outline of what the page held, printed when nothing parsed,
    so the run log shows the layout to fix against."""
    soup = BeautifulSoup(html, "html.parser")
    title = _clean(soup.title.get_text()) if soup.title else "(no title)"
    links = [a for a in soup.find_all("a", href=True) if DOC_LINK_RE.search(a["href"])]
    max_year = datetime.now().year + 1
    years = [t for t in soup.find_all(True) if _year_label(t, max_year) is not None
             and t.find(_year_label_child(max_year)) is None]
    lines = ["page %r, %d characters, %d DocumentCenter links, %d year labels"
             % (title, len(html), len(links), len(years))]
    def chain(tag):
        parts = []
        for anc in [tag] + list(tag.parents)[:6]:
            if not isinstance(anc, Tag) or anc.name in ("html", "[document]"):
                break
            ident = ("#" + anc["id"]) if anc.get("id") else ""
            cls = ("." + ".".join(anc.get("class"))) if anc.get("class") else ""
            parts.append(anc.name + ident + cls)
        return " < ".join(parts)

    for a in links[:limit]:
        prev = a.find_previous(string=lambda t: t.strip() and t.find_parent("a") is not a)
        lines.append("  link %r -> %s | in %s | text before: %r"
                     % (_clean(a.get_text(" ", strip=True))[:60], a["href"][:90], chain(a),
                        _clean(str(prev))[:70] if prev else ""))
    for t in years[:limit]:
        attrs = {k: v for k, v in t.attrs.items() if k in ("id", "href", "aria-controls", "data-target", "class")}
        lines.append("  year <%s %s> %s | in %s" % (t.name, attrs, _clean(t.get_text()), chain(t)))
    return "\n".join(lines)


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_DAY_RE = re.compile(
    r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s*(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE,
)


def parse_date_range(year, heading):
    """Best-effort start date from a heading like 'April 25 - April 27
    (Severe Weather)', 'January 24 (Winter Storms)', 'December 26-27
    (Winter Storm)' (no space around the hyphen), 'March 22nd and
    continuing (Fires)' (ordinal suffix + trailing text), or 'Feb 26
    -Mar 8 (Wildland Fires)' (irregular spacing, abbreviated month).
    Returns (date_str, hazard_text) or (None, hazard_text) if the heading
    genuinely has no recognizable month/day at its start."""
    hazard_match = re.search(r"\(([^)]+)\)\s*$", heading)
    hazard_text = hazard_match.group(1).strip() if hazard_match else heading
    date_part = heading[:hazard_match.start()].strip() if hazard_match else heading

    m = _MONTH_DAY_RE.search(date_part)
    if not m:
        return None, hazard_text
    month = _MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    try:
        dt = datetime(int(year), month, day)
    except ValueError:
        return None, hazard_text
    return dt.strftime("%Y-%m-%d"), hazard_text


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def saved_rows(join_out):
    """The join file's saved rows, by declaration_id."""
    try:
        with open(join_out, newline="", encoding="utf-8") as f:
            return {r["declaration_id"]: r for r in csv.DictReader(f) if r.get("declaration_id")}
    except (OSError, KeyError, csv.Error):
        return {}


# ---------------------------------------------------------------- news flash
# KDEM announces each declaration in its News Flash ("Governor Kelly issues
# state of disaster emergency for flooding"), which CivicPlus publishes as a
# standard RSS feed. It is the fallback when the declarations page cannot be
# read: an item counts only when its text or its news page links the signed
# declaration in the Document Center, so it gets the same KS-PROC-<document>
# id the page would give it and can never become a second record.
NEWS_FEED = f"{BASE}/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml"
NEWS_DECLARATION_RE = re.compile(
    r"\b(?:issues?|issued|declares?|declared|signs?|signed)\b[^.;:]{0,40}?\b(?:state of disaster emergency|"
    r"disaster emergency|disaster proclamation|disaster declaration|state of emergency)\b", re.I)
NEWS_EXCLUDE_RE = re.compile(r"\b(?:presidential|federal|fema|extend\w*|extension|amend\w*|renew\w*|expand\w*|"
                             r"updat\w*|rescind\w*|terminat\w*|approv\w*|request\w*)\b", re.I)
try:
    from zoneinfo import ZoneInfo
    _KS_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    from datetime import timezone as _tz, timedelta as _td
    _KS_TZ = _tz(_td(hours=-6))


def _declaration_doc_ids(html):
    """Document Center ids of links labelled as a declaration or proclamation
    in a piece of HTML (an item's description or a news article's body)."""
    soup = BeautifulSoup(html or "", "html.parser")
    ids = []
    for a in soup.find_all("a", href=True):
        m = DOC_LINK_RE.search(a["href"])
        if m and DECLARATION_LINK_RE.search(a.get_text(" ", strip=True)) and not SKIP_LINK_RE.search(a.get_text(" ", strip=True)):
            ids.append(m.group(1))
    return list(dict.fromkeys(ids))


def _article_body(html):
    """The news article itself, not the site's menus and footer."""
    soup = BeautifulSoup(html or "", "html.parser")
    for sel in ("#newsFlashDetail", ".detail", ".fr-view", "article", "main", "#moduleContent", ".moduleContentNew"):
        el = soup.select_one(sel)
        if el is not None:
            return str(el)
    return ""


def news_declarations(xml_bytes, session=None, saved_ids=(), review=None):
    """[{doc_id, pdf_url, title, date, news_url}] for News Flash items that
    announce a new weather declaration and link exactly one signed
    declaration not saved yet, in the item or the article's own body (never
    the page's menus). Anything less certain goes to review."""
    from email.utils import parsedate_to_datetime
    from xml.etree import ElementTree as ET
    review = [] if review is None else review
    out, seen = [], set(saved_ids)
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = _clean(item.findtext("title"))
        if not NEWS_DECLARATION_RE.search(title) or NEWS_EXCLUDE_RE.search(title):
            continue
        if any(bad in slugify(title) for bad in NON_WEATHER_OR_SUSPECT_SLUGS):
            continue
        try:
            stamp = parsedate_to_datetime(item.findtext("pubDate") or "")
            day = stamp.astimezone(_KS_TZ).date().isoformat() if stamp.tzinfo else stamp.date().isoformat()
        except (TypeError, ValueError, IndexError):
            continue
        link = (item.findtext("link") or "").strip()
        ids = _declaration_doc_ids(item.findtext("description") or "")
        if not ids and session is not None and link:
            try:
                ids = _declaration_doc_ids(_article_body(fetch(link, session)))
            except requests.RequestException:
                ids = []
        new = [i for i in ids if f"KS-PROC-{i}" not in seen]
        if not ids:
            review.append(f"{day} {title} (no declaration link found)")
            continue
        if len(new) != 1:
            if len(new) > 1:
                review.append(f"{day} {title} (links {len(new)} unsaved declarations)")
            continue
        seen.add(f"KS-PROC-{new[0]}")
        out.append({"doc_id": new[0], "pdf_url": f"{BASE}/DocumentCenter/View/{new[0]}",
                    "title": title, "date": day, "news_url": link})
    return out


def collect_from_news(session, join_out):
    """Declarations announced in the News Flash that are not saved yet."""
    resp = session.get(NEWS_FEED, timeout=30, headers={"User-Agent": "DisasterData.io research crawler",
                                                       "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5"})
    resp.raise_for_status()
    saved = saved_rows(join_out)
    review = []
    rows = []
    for d in news_declarations(resp.content, session, saved_ids=set(saved), review=review):
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        # The news item's link is kept as the record's source, which also marks
        # its date as the announcement's, not a reviewed signing date: when
        # the page is read again, the page's own date replaces it.
        rows.append({"declaration_id": f"KS-PROC-{d['doc_id']}", "governor": governor_for(dt), "eo_number": d["doc_id"],
                     "event_description": d["title"], "date_signed": d["date"],
                     "archive_record_url": d["news_url"] or d["pdf_url"]})
    for line in review:
        print(f"  REVIEW: Kansas News Flash item not recorded automatically: {line}", file=sys.stderr)
    return rows


def collect(actions_out, relationships_out, join_out):
    session = requests.Session()
    html = fetch(SOURCE_URL, session)
    raw_records = parse_declarations_page(html)
    if not raw_records:
        # The page has listed declarations every year since 2009, so zero
        # means the layout was not understood. Print what the page held, to
        # fix the parser against, then read the News Flash for new ones.
        print("Kansas: no declarations found on the page. Page outline:\n" + describe_page(html),
              file=sys.stderr)
        try:
            news_rows = collect_from_news(session, join_out)
        except Exception as exc:
            print(f"Kansas: News Flash feed not read either: {exc}", file=sys.stderr)
            raise SystemExit(1)
        saved = list(saved_rows(join_out).values())
        fields = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
        with open(join_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(saved + news_rows)
        print(f"Kansas: {len(news_rows)} new declaration(s) read from the KDEM News Flash "
              f"(declarations page not understood this run)")
        return len(saved) + len(news_rows)
    saved = saved_rows(join_out)
    # The page's files are often re-uploaded ("...-amended"), which gives the
    # same entry a new document number. The saved record already is that entry.
    saved_entries = {(r.get("date_signed", ""), r.get("event_description", "")): i for i, r in saved.items()}

    actions = []
    relationships = []
    declarations = []

    for rec in raw_records:
        actions.append({"year": rec["year"], "heading": rec["heading"], "pdf_url": rec["pdf_url"]})
        relationships.append({"source_page": SOURCE_URL, "declaration_url": rec["pdf_url"]})

        slug = slugify(rec["heading"])
        if any(bad in slug for bad in NON_WEATHER_OR_SUSPECT_SLUGS):
            continue

        date_signed, hazard_text = parse_date_range(rec["year"], rec["heading"])
        if not date_signed:
            continue
        # A year written in the PDF's own file name must agree with the tab
        # the entry sits under. When it does not, which of the two is wrong
        # cannot be told from here, so the saved record stands.
        years_in_name = slug_years(rec["pdf_url"])
        if years_in_name and int(rec["year"]) not in years_in_name:
            print("  NOTE: KS-PROC-%s is under %s but its file name says %s; left as saved"
                  % (rec["doc_id"], rec["year"], "/".join(map(str, sorted(years_in_name)))), file=sys.stderr)
            continue
        declaration_id = f"KS-PROC-{rec['doc_id']}"
        saved_row = saved.get(declaration_id, {})
        saved_date = saved_row.get("date_signed", "")
        from_news = "CivicAlerts" in saved_row.get("archive_record_url", "")
        if saved_date and saved_date != date_signed and not from_news:
            print("  NOTE: %s reads as %s but was saved as %s after review; kept the saved date"
                  % (declaration_id, date_signed, saved_date), file=sys.stderr)
            date_signed = saved_date
        same_entry = saved_entries.get((date_signed, f"{hazard_text} ({rec['heading']})"))
        if same_entry and same_entry != declaration_id:
            print("  NOTE: %s is a re-upload of saved %s (same heading and date); not counted again"
                  % (declaration_id, same_entry), file=sys.stderr)
            continue
        dt = datetime.strptime(date_signed, "%Y-%m-%d")
        if dt < SCOPE_START:
            continue

        declarations.append({
            "declaration_id": declaration_id,
            "governor": governor_for(dt),
            "eo_number": rec["doc_id"],
            "event_description": f"{hazard_text} ({rec['heading']})",
            "date_signed": date_signed,
            "archive_record_url": rec["pdf_url"],
        })

    with open(actions_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "heading", "pdf_url"])
        w.writeheader()
        for a in actions:
            w.writerow(a)

    with open(relationships_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source_page", "declaration_url"])
        w.writeheader()
        for r in relationships:
            w.writerow(r)

    with open(join_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["declaration_id", "governor", "eo_number", "event_description",
                        "date_signed", "archive_record_url"],
            lineterminator="\n",
        )
        w.writeheader()
        seen = set()
        for d in declarations:
            if d["declaration_id"] in seen:
                continue
            seen.add(d["declaration_id"])
            w.writerow(d)

    return len(declarations)


def main():
    parser = argparse.ArgumentParser(description="Scrape Kansas disaster declarations")
    parser.add_argument("--actions-out", required=True)
    parser.add_argument("--relationships-out", required=True)
    parser.add_argument("--join-out", required=True)
    args = parser.parse_args()

    try:
        n = collect(args.actions_out, args.relationships_out, args.join_out)
    except requests.RequestException as exc:
        raise SystemExit(f"Kansas: could not read {SOURCE_URL}: {exc}")
    print(f"Kansas: wrote {n} declaration(s) to {args.join_out}")


if __name__ == "__main__":
    main()
