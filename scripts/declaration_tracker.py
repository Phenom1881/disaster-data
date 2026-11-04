#!/usr/bin/env python3
"""
Declaration Tracker: an unofficial ledger of state, tribal and territorial
requests for a federal major disaster (DR) or emergency (EM) declaration,
from the day a request is filed to the day FEMA acts on it.

Why this exists
  OpenFEMA only shows a request once it is decided: an approved request
  becomes a declaration (with no request date), and a turned down request
  lands in Declaration Denials (in batches, weeks later). Requests that are
  still waiting appear nowhere in OpenFEMA. FEMA's Daily Operations Briefing
  carried a "Declaration Requests in Process" table that filled that gap,
  but the table stopped appearing after the October 29, 2026 briefing.

What this script does
  1. Reads the "Declaration Requests in Process" table out of every archived
     Daily Ops Briefing PDF (archive/ops-briefings/*.pdf). Each PDF is read
     once and cached in the ledger, so the daily run only parses new PDFs.
  2. Folds the daily rows into one record per request: who asked, DR or EM,
     appeal or not, programs requested, the date requested, and the first and
     last briefing that listed it.
  3. Checks every request against OpenFEMA (declarations and denials) and
     records the outcome, the decision date, and the days it waited.
  4. Writes archive/ops-briefings/declaration-tracker.json, which the
     /declaration-tracker.html page reads, and a cache file beside it
     (declaration-tracker-cache.json) holding the parsed rows of every
     briefing and the last OpenFEMA snapshot.

It runs at the end of "build ops pages.py" in the daily briefing job, so it
needs no workflow of its own. If OpenFEMA can't be reached, the last FEMA
snapshot saved in the ledger is reused and the page says how old it is.

Env vars
  DD_OUT                 Root data directory. Defaults to "archive".
  DD_TRACKER_FEMA_JSON   Optional path to a saved FEMA snapshot
                         ({"declarations": [...], "denials": [...]}) used
                         instead of calling OpenFEMA (local runs and tests).
  DD_TRACKER_TODAY       Optional YYYY-MM-DD to pin "today" (tests).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PARSER_VERSION = 1

OUT_ROOT = Path(os.environ.get("DD_OUT", "archive"))
BRIEF_DIR = OUT_ROOT / "ops-briefings"
LEDGER_PATH = BRIEF_DIR / "declaration-tracker.json"          # what the page reads
CACHE_PATH = BRIEF_DIR / "declaration-tracker-cache.json"     # parsed briefings + FEMA snapshot
SOURCES_PATH = BRIEF_DIR / "declaration-sources.csv"           # official releases linked to requests
REVIEW_PATH = BRIEF_DIR / "declaration-sources-review.csv"     # releases waiting for a person

OPENFEMA = "https://www.fema.gov/api/open"
USER_AGENT = "DisasterData.IO declaration tracker (+https://www.disasterdata.io/declaration-tracker.html)"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands", "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands", "FM": "Federated States of Micronesia", "MH": "Marshall Islands",
    "PW": "Palau",
}
# Codes the briefing uses that are not two-letter postal codes.
TERRITORY_CODES = {"CNMI": "MP", "USVI": "VI"}

# Tribal requesters seen in the briefing footnotes, and the state OpenFEMA
# files their declarations under. A tribe missing here is still tracked;
# it just can't be matched to OpenFEMA until it is added.
TRIBE_STATES = {
    "Rosebud Sioux Tribe": "SD",
    "Oglala Sioux Tribe": "SD",
    "Pueblo of Zuni": "NM",
    "Confederated Tribes and Bands of the Yakama Nation": "WA",
    "Confederated Tribes of the Colville Reservation": "WA",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

TABLE_HEAD = re.compile(r"Declaration\s+Requests?\s+in\s+Process", re.I)
ROW = re.compile(r"^(?P<desc>\S.*?)\s{2,}(?P<type>DR|EM)\b(?P<rest>.*)$")
REQ_DATE = re.compile(r"\b(?P<mon>[A-Z](?:\s?[a-z]){2,3})\.?\s+(?P<day>\d{1,2})\s*$")
DASH_SPLIT = re.compile(r"\s+[\u2013\u2014-]\s+")
STATUS = re.compile(r"^(approved|denied)$", re.I)
APPEAL = re.compile(r"^appeal$", re.I)
CODE = re.compile(r"^(?P<letters>[A-Z]{2,8})(?P<mark>\d|\*)?$")


# --------------------------------------------------------------------------
# Parsing one briefing
# --------------------------------------------------------------------------

def infer_request_date(mon: str, day: str, brief: date) -> str | None:
    """The table prints "Oct 27" with no year. Use the briefing's year unless
    that would put the request more than a week after the briefing."""
    month = MONTHS.get(mon.replace(" ", "")[:3].title())
    if not month:
        return None
    try:
        when = date(brief.year, month, int(day))
        if when > brief + timedelta(days=7):
            when = date(brief.year - 1, month, int(day))
    except ValueError:
        return None
    return when.isoformat()


def parse_footnotes(lines: list[str]) -> dict[str, str]:
    """Footnotes name the tribes behind codes like RST1 or OST*."""
    notes: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if s.startswith("*") and len(s) > 3:
            notes["*"] = s[1:].strip()
            continue
        if not re.match(r"^\d\s*[A-Z]", s):
            continue
        for piece in re.split(r"[;,]?\s*(?=\b\d\s*[A-Z])", s):
            m = re.match(r"^(\d)\s*(.+?)[;,\s]*$", piece.strip())
            if m:
                notes[m.group(1)] = re.sub(r"\s+", " ", m.group(2))
    return notes


def column_positions(header: str) -> dict[str, int]:
    return {m.group(0): m.start() for m in re.finditer(r"\b(?:IA|PA|HM)\b", header)}


def parse_page(text: str, brief_date: str) -> list[dict] | None:
    """Rows from one page of layout text, or None if the page has no table."""
    lines = text.splitlines()
    if not any(TABLE_HEAD.search(l) for l in lines):
        return None
    brief = date.fromisoformat(brief_date)
    notes = parse_footnotes(lines)
    cols: dict[str, int] = {}
    rows: list[dict] = []
    inside = False
    for line in lines:
        if TABLE_HEAD.search(line):
            inside = True
            continue
        if not inside:
            continue
        if "Incident Description" in line and "Type" in line:
            cols = column_positions(line)
            continue
        m = ROW.match(line.strip())
        if not m:
            continue
        parts = DASH_SPLIT.split(re.sub(r"\s+", " ", m.group("desc")).strip())
        code = CODE.match(parts[0].strip())
        if not code:
            continue
        status = None
        appeal = False
        kept = []
        for part in parts[1:]:
            if STATUS.match(part.strip()):
                status = part.strip().lower()
            elif APPEAL.match(part.strip()):
                appeal = True
            else:
                kept.append(part.strip())
        letters, mark = code.group("letters"), code.group("mark")
        state = TERRITORY_CODES.get(letters, letters if letters in STATE_NAMES else None)
        tribe = None
        if state is None:
            tribe = notes.get(mark or "", letters)
            state = TRIBE_STATES.get(tribe)
        when = REQ_DATE.search(m.group("rest"))
        programs = None
        if cols:
            offset = line.index(m.group("type"), len(line) - len(line.lstrip()) + len(m.group("desc")))
            found = set()
            for x in re.finditer(r"\bX\b", line):
                if x.start() <= offset:
                    continue
                name, pos = min(cols.items(), key=lambda kv: abs(kv[1] - x.start()))
                if abs(pos - x.start()) <= 6:
                    found.add(name)
            programs = [p for p in ("IA", "PA", "HM") if p in found] or None
        rows.append({
            "brief": brief_date,
            "code": letters,
            "state": state,
            "tribe": tribe,
            "type": m.group("type"),
            "incident": " - ".join(kept),
            "appeal": appeal,
            "status": status,
            "requested": infer_request_date(when.group("mon"), when.group("day"), brief) if when else None,
            "programs": programs,
        })
    return rows


def parse_pdf(path: Path, brief_date: str) -> dict:
    from pypdf import PdfReader  # installed by the daily job

    rows: list[dict] = []
    has_table = False
    for page in PdfReader(str(path)).pages:
        try:
            text = page.extract_text(extraction_mode="layout")
        except Exception:
            continue
        found = parse_page(text or "", brief_date)
        if found is not None:
            has_table = True
            rows.extend(found)
    return {"date": brief_date, "has_table": has_table, "rows": rows}


# --------------------------------------------------------------------------
# Folding daily rows into requests
# --------------------------------------------------------------------------

def norm_incident(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def requester_key(row: dict) -> str:
    return row["tribe"] or row["state"] or row["code"]


def request_id(row: dict) -> str:
    who = re.sub(r"[^a-z0-9]+", "-", requester_key(row).lower()).strip("-")
    return f"{who}-{row['type'].lower()}-{row['requested']}" + ("-appeal" if row["appeal"] else "")


def summarize(rows: list[dict]) -> dict:
    """Collapse the daily rows of one request into its record."""
    rows = sorted(rows, key=lambda r: r["brief"])
    dated = [r for r in rows if r["requested"]]
    latest = dated[-1] if dated else rows[-1]
    with_programs = [r for r in rows if r["programs"]]
    with_incident = [r for r in rows if r["incident"]]
    with_status = [r for r in rows if r["status"]]
    unresolved = [r["brief"] for r in rows if not r["status"]]
    req = {
        "id": "",
        "code": latest["code"],
        "state": latest["state"],
        "tribe": latest["tribe"],
        "requester": latest["tribe"] or STATE_NAMES.get(latest["state"] or "", latest["code"]),
        "type": latest["type"],
        "appeal": any(r["appeal"] for r in rows),
        "incident": with_incident[-1]["incident"] if with_incident else "",
        "requested": latest["requested"],
        "requested_dates_listed": sorted({r["requested"] for r in dated}),
        "programs": with_programs[-1]["programs"] if with_programs else None,
        "first_seen": rows[0]["brief"],
        "last_seen": rows[-1]["brief"],
        "last_listed_pending": unresolved[-1] if unresolved else None,
        "days_listed": len({r["brief"] for r in rows}),
        "brief_status": with_status[0]["status"] if with_status else None,
        "brief_status_date": with_status[0]["brief"] if with_status else None,
        "source": "ops_brief",
    }
    req["id"] = request_id(req)
    return req


def _contiguous(days: set[str], table_dates: list[str]) -> bool:
    """True if `days` covers every table date between its first and last."""
    lo, hi = min(days), max(days)
    return all(d in days for d in table_dates if lo <= d <= hi)


def _same_request(a: list[dict], b: list[dict], table_dates: list[str]) -> bool:
    """Two groups of rows are one request whose listing was edited midway: the
    same requester and type, never listed on the same day, and listed back to
    back. Either the requested date changed (same incident wording) or the
    "Appeal" tag came or went (same requested date)."""
    sa, sb = summarize(a), summarize(b)
    if requester_key(sa) != requester_key(sb) or sa["type"] != sb["type"]:
        return False
    days_a, days_b = {r["brief"] for r in a}, {r["brief"] for r in b}
    if days_a & days_b or not _contiguous(days_a | days_b, table_dates):
        return False
    first, second = (sa, sb) if sa["first_seen"] < sb["first_seen"] else (sb, sa)
    if first["brief_status"] and first["brief_status_date"] < second["first_seen"]:
        return False
    if sa["appeal"] == sb["appeal"]:
        # A changed date only counts as an edit across a short handoff; the
        # month-long gap after the July 19 briefing could hide a new request.
        handoff = (date.fromisoformat(second["first_seen"]) - date.fromisoformat(first["last_seen"])).days
        if not 0 < handoff <= 3:
            ends = sorted(days_a | days_b)
            if any((date.fromisoformat(b) - date.fromisoformat(a)).days > 3 for a, b in zip(ends, ends[1:])):
                return False
        return norm_incident(sa["incident"]) == norm_incident(sb["incident"])
    return sa["requested"] == sb["requested"]


def fold_requests(briefs: dict[str, dict]) -> tuple[list[dict], str | None]:
    """One record per request. Returns (requests, last date the table ran)."""
    table_dates = sorted(b["date"] for b in briefs.values() if b["has_table"])
    groups: dict[str, list[dict]] = {}
    undated: list[dict] = []
    for brief in sorted(briefs.values(), key=lambda b: b["date"]):
        for row in brief["rows"]:
            if row["requested"]:
                groups.setdefault(request_id(row), []).append(row)
            else:
                undated.append(row)

    # Rows whose requested date was cut off at the page edge (this happens on
    # many "Approved" and "Denied" rows) belong to the request with the same
    # requester, type, appeal flag and incident that was listed most recently.
    for row in undated:
        pool = []
        for key, rows in groups.items():
            s = summarize(rows)
            if requester_key(s) != requester_key(row) or s["type"] != row["type"] \
                    or s["appeal"] != row["appeal"] or s["requested"] > row["brief"]:
                continue
            named = norm_incident(s["incident"]) == norm_incident(row["incident"])
            recent = s["last_seen"] >= _shift(row["brief"], -3)
            if named or recent:
                pool.append((named, s["last_seen"], s["requested"], key))
        if pool:
            groups[max(pool)[3]].append(row)

    merged = True
    while merged:
        merged = False
        keys = sorted(groups)
        for i, ka in enumerate(keys):
            for kb in keys[i + 1:]:
                if _same_request(groups[ka], groups[kb], table_dates):
                    groups[ka].extend(groups.pop(kb))
                    merged = True
                    break
            if merged:
                break

    ordered = sorted((summarize(rows) for rows in groups.values()), key=lambda r: (r["requested"], r["id"]))
    seen: dict[str, int] = {}
    for req in ordered:  # ids stay unique even if two requests share one
        seen[req["id"]] = seen.get(req["id"], 0) + 1
        if seen[req["id"]] > 1:
            req["id"] += f"-{seen[req['id']]}"
    return ordered, (table_dates[-1] if table_dates else None)


def next_table_date(day: str, table_dates: list[str]) -> str | None:
    later = [d for d in table_dates if d > day]
    return later[0] if later else None


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------
# OpenFEMA outcomes
# --------------------------------------------------------------------------

def _get_all(endpoint: str, version: str, flt: str, select: str) -> list[dict]:
    import requests  # installed by the daily job

    rows: list[dict] = []
    skip = 0
    while True:
        params = {"$filter": flt, "$select": select, "$top": 1000, "$skip": skip, "$orderby": "id"}
        for attempt in range(3):
            try:
                resp = requests.get(f"{OPENFEMA}/{version}/{endpoint}", params=params, timeout=60,
                                    headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                batch = resp.json().get(endpoint, [])
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        skip += 1000


def fetch_fema(since: str) -> dict:
    """Declarations (DR and EM) declared on or after `since`, and denials of
    requests filed in the 60 days before it or later."""
    decl_rows = _get_all(
        "DisasterDeclarationsSummaries", "v2",
        f"declarationDate ge '{since}T00:00:00.000Z' and declarationType ne 'FM'",
        "femaDeclarationString,state,declarationType,declarationDate,declarationTitle,tribalRequest",
    )
    decls: dict[str, dict] = {}
    for r in decl_rows:
        key = r["femaDeclarationString"]
        if key not in decls:
            decls[key] = dict(r)
        elif r.get("tribalRequest"):
            decls[key]["tribalRequest"] = True
    denials = _get_all(
        "DeclarationDenials", "v1",
        f"declarationRequestDate ge '{_shift(since, -60)}T00:00:00.000Z'",
        "declarationRequestNumber,stateAbbreviation,tribalRequest,declarationRequestDate,"
        "declarationRequestType,incidentName,currentRequestStatus,requestStatusDate",
    )
    return {"declarations": list(decls.values()), "denials": denials}


def _day(stamp: str | None) -> str | None:
    return stamp[:10] if stamp else None


def _words(text: str) -> set[str]:
    skip = {"and", "the", "of", "severe", "storm", "storms", "a", "r1", "r2", "r3", "r4", "r5",
            "r6", "r7", "r8", "r9", "r10"}
    return {w for w in norm_incident(text).split() if w not in skip and not w.isdigit()}


DENIAL_TYPES = {"DR": "Major Disaster", "EM": "Emergency"}


def resolve(requests: list[dict], fema: dict, table_dates: list[str], today: str) -> None:
    """Fill each request's outcome in place.

    Order of evidence: an OpenFEMA turndown, then an OpenFEMA declaration,
    then what the briefing itself said (approved or denied), then whether the
    request was still on the last table the briefing ran.
    """
    last_table = table_dates[-1] if table_dates else None
    used_denials: set[int] = set()
    used_decls: set[str] = set()

    def window_end(req: dict) -> str | None:
        """Latest plausible decision date for a request that left the table."""
        if last_table and req["last_seen"] and req["last_seen"] < last_table:
            return _shift(next_table_date(req["last_seen"], table_dates), 2)
        return None

    for req in requests:
        req.update({"status": None, "decision_date": None, "declaration": None,
                    "denial_number": None, "days": None, "still_listed_after_declaration": False})

    def denial_ok(den: dict, req: dict) -> bool:
        return (den.get("declarationRequestNumber") not in used_denials
                and den.get("stateAbbreviation") == req["state"]
                and bool(den.get("tribalRequest")) == bool(req["tribe"])
                and den.get("declarationRequestType") == DENIAL_TYPES[req["type"]]
                and (den.get("currentRequestStatus") or "").lower() == "turndown")

    def take_denial(req: dict, den: dict) -> None:
        used_denials.add(den["declarationRequestNumber"])
        req.update({"status": "turned_down", "decision_date": _day(den.get("requestStatusDate")),
                    "denial_number": den["declarationRequestNumber"]})

    # 1a. Turndowns whose request date is within 3 days of the listed date.
    for req in requests:
        best = None
        for den in fema.get("denials", []):
            if not denial_ok(den, req):
                continue
            gap = abs((date.fromisoformat(_day(den["declarationRequestDate"])) - date.fromisoformat(req["requested"])).days)
            if gap <= 3 and (best is None or gap < best[0]):
                best = (gap, den)
        if best:
            take_denial(req, best[1])

    # 1b. Appeals and rows the briefing marked denied can carry the appeal
    #     date instead of the original request date, so match those on the
    #     turndown's decision date instead.
    for req in requests:
        if req["status"] or not (req["appeal"] or req["brief_status"] == "denied"):
            continue
        if req["brief_status"] == "denied":
            lo, hi = _shift(req["brief_status_date"], -10), _shift(req["brief_status_date"], 1)
        elif req["brief_status"] is None and window_end(req):
            lo, hi = _shift(req["last_seen"], -10), window_end(req)
        else:
            continue
        best = None
        for den in fema.get("denials", []):
            decided = _day(den.get("requestStatusDate"))
            if not denial_ok(den, req) or not decided or not lo <= decided <= hi:
                continue
            if _day(den["declarationRequestDate"]) > req["requested"]:
                continue
            score = -len(_words(req["incident"]) & _words(den.get("incidentName", "")))
            if best is None or score < best[0]:
                best = (score, den)
        if best:
            take_denial(req, best[1])

    # 2. Declarations: same requester and type, declared on or after the
    #    request, closest to the day the briefing marked it approved or
    #    dropped it, with matching incident words as a tie breaker.
    def anchor(req: dict) -> str:
        if req["brief_status"] == "approved":
            return req["brief_status_date"]
        if window_end(req):
            return _shift(req["last_seen"], 1)
        return today

    for req in sorted(requests, key=lambda r: (anchor(r), r["requested"])):
        if req["status"] or req["brief_status"] == "denied":
            continue
        point = date.fromisoformat(anchor(req))
        best = None
        for dec in fema.get("declarations", []):
            key = dec["femaDeclarationString"]
            if key in used_decls or dec.get("declarationType") != req["type"]:
                continue
            if dec.get("state") != req["state"] or bool(dec.get("tribalRequest")) != bool(req["tribe"]):
                continue
            declared = _day(dec["declarationDate"])
            if declared < req["requested"]:
                continue
            if req["brief_status"] == "approved":
                if not _shift(req["brief_status_date"], -10) <= declared <= _shift(req["brief_status_date"], 1):
                    continue
            elif window_end(req) and declared > window_end(req):
                continue
            score = abs((date.fromisoformat(declared) - point).days) \
                - 5 * len(_words(req["incident"]) & _words(dec.get("declarationTitle", "")))
            if req["first_seen"] and declared < req["first_seen"]:
                score += 30  # declared before the briefing ever listed it
            if best is None or score < best[0]:
                best = (score, dec)
        if best:
            dec = best[1]
            used_decls.add(dec["femaDeclarationString"])
            declared = _day(dec["declarationDate"])
            pending = req["last_listed_pending"]
            req.update({"status": "declared", "decision_date": declared,
                        "declaration": {"id": dec["femaDeclarationString"],
                                        "title": dec.get("declarationTitle", "")},
                        "still_listed_after_declaration": bool(pending and pending > _shift(declared, 2))})

    # 3. Everything else, from the briefing itself.
    for req in requests:
        if req["status"]:
            pass
        elif req["brief_status"] == "approved":
            req.update({"status": "approved_per_brief", "decision_date": req["brief_status_date"]})
        elif req["brief_status"] == "denied":
            req.update({"status": "denied_per_brief", "decision_date": req["brief_status_date"]})
        elif req.get("source") == "announced":
            req["status"] = "open"  # filed after the briefing dropped the table
        elif last_table and req["last_seen"] >= last_table:
            req["status"] = "open"
        else:
            req["status"] = "left_brief"
        if req["status"] == "open":
            end = today
        elif req["status"] == "left_brief":
            end = req["last_seen"]
        else:
            end = req["decision_date"]
        req["days"] = (date.fromisoformat(end) - date.fromisoformat(req["requested"])).days


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

def load_cache() -> dict:
    """Parsed briefings are reused only if the parser hasn't changed since."""
    if CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if data.get("parser_version") != PARSER_VERSION:
                data["briefs"] = {}
            return data
        except (OSError, ValueError):
            pass
    return {}


def brief_pdfs() -> dict[str, Path]:
    found = {}
    for pdf in sorted(BRIEF_DIR.glob("*.pdf")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pdf.stem):
            found[pdf.name] = pdf
    return found


def build(today: str | None = None, fema_override: dict | None = None, scrape: bool | None = None,
          fetcher=None) -> dict:
    today = today or os.environ.get("DD_TRACKER_TODAY") or datetime.now(timezone.utc).date().isoformat()
    old = load_cache()
    cache: dict[str, dict] = old.get("briefs", {})
    briefs: dict[str, dict] = {}
    parsed_now = 0
    for name, pdf in brief_pdfs().items():
        if name in cache:
            briefs[name] = cache[name]
        else:
            briefs[name] = parse_pdf(pdf, pdf.stem)
            parsed_now += 1

    requests, last_table = fold_requests(briefs)
    table_dates = sorted(b["date"] for b in briefs.values() if b["has_table"])

    fema, fetched_at, fema_note = None, None, ""
    snapshot = os.environ.get("DD_TRACKER_FEMA_JSON")
    if fema_override is not None:
        fema, fetched_at = fema_override, today + "T00:00:00Z"
    elif snapshot:
        fema = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        fetched_at = datetime.fromtimestamp(Path(snapshot).stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif requests:
        try:
            fema = fetch_fema(min(r["requested"] for r in requests))
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as exc:  # keep the last good snapshot
            fema_note = f"OpenFEMA could not be reached ({type(exc).__name__}); using the snapshot from {old.get('fema_fetched_at')}."
            fema, fetched_at = old.get("fema"), old.get("fema_fetched_at")
    # Official sources: releases from governors' newsrooms (see declaration_sources.py).
    import declaration_sources as ds

    if scrape is None:
        scrape = fema_override is None and os.environ.get("DD_TRACKER_SCRAPE", "1") == "1"
    accepted_path, review_path = BRIEF_DIR / SOURCES_PATH.name, BRIEF_DIR / REVIEW_PATH.name
    old_sources = old.get("sources") or {}
    ignored = set(old_sources.get("ignored", []))
    ignored |= set(ds.apply_review_decisions(accepted_path, review_path, today))
    brief_requests = requests

    def assemble() -> tuple[list[dict], list[dict]]:
        accepted = ds.read_csv(accepted_path)
        reqs = [dict(r) for r in brief_requests] + ds.announced_requests(accepted, STATE_NAMES)
        resolve(reqs, fema or {}, table_dates, today)
        orphans = ds.attach(reqs, accepted)
        reqs.sort(key=lambda r: (r["requested"], r["id"]))
        return reqs, orphans

    requests, orphans = assemble()
    health = old_sources.get("health", [])
    if scrape:
        try:
            health = ds.crawl(ds.load_feeds(), requests, fetcher or ds.Fetcher(USER_AGENT),
                              accepted_path, review_path, ignored, today)
        except Exception as exc:  # noqa: BLE001  a crawl failure never blocks the ledger
            print(f"WARNING: official sources not checked: {type(exc).__name__}: {exc}")
        requests, orphans = assemble()

    ledger = {
        "parser_version": PARSER_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": today,
        "unofficial": True,
        "about": ("Unofficial tracker of requests for federal disaster and emergency declarations, built by "
                  "DisasterData.IO from archived FEMA Daily Operations Briefings and OpenFEMA. Not affiliated "
                  "with or endorsed by FEMA."),
        "last_brief": max((b["date"] for b in briefs.values()), default=None),
        "last_brief_with_table": last_table,
        "briefs_read": len(briefs),
        "briefs_with_table": sum(1 for b in briefs.values() if b["has_table"]),
        "fema_fetched_at": fetched_at,
        "fema_note": fema_note,
        "sources_checked": health,
        "sources_waiting_review": len(ds.read_csv(review_path)),
        "sources_unmatched": orphans,
        "requests": requests,
    }
    ledger["_cache"] = {"parser_version": PARSER_VERSION, "fema_fetched_at": fetched_at,
                        "fema": fema, "briefs": briefs,
                        "sources": {"ignored": sorted(ignored), "health": health}}
    ledger["_parsed_now"] = parsed_now
    return ledger


def _write_json(path: Path, data: dict, indent: int | None) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def write(ledger: dict) -> None:
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(CACHE_PATH, ledger["_cache"], None)
    _write_json(LEDGER_PATH, {k: v for k, v in ledger.items() if not k.startswith("_")}, 1)


def main() -> int:
    ledger = build()
    write(ledger)
    counts: dict[str, int] = {}
    for req in ledger["requests"]:
        counts[req["status"]] = counts.get(req["status"], 0) + 1
    print(f"Declaration tracker: {len(ledger['requests'])} request(s) from {ledger['briefs_read']} briefing(s) "
          f"({ledger['_parsed_now']} newly read); {counts}. {ledger['fema_note']}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
