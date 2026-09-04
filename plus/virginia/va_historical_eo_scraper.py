"""Build a Virginia executive-order inventory for completed administrations.

The Library of Virginia's Executive Orders Digital Collection covers every
completed administration beginning with Mark Warner (2002).  Its public Primo
feed exposes full item titles, exact creation dates, and stable record IDs, so
metadata collection does not require OCR.

Outputs are intentionally separated:

* va_eo_archive_all.csv -- every archived EO/ED record
* va_emergency_actions_2002_2026.csv -- emergency declarations and lifecycle actions
* va_weather_emergency_actions_2002_2026.csv -- weather-related emergency actions
* declarations_for_join_2002_present.csv -- initial weather declarations, optionally
  combined with a current-administration CSV supplied via --current-csv

Usage:
  python va_historical_eo_scraper.py \
    --current-csv declarations_for_join.csv
"""

import argparse
import re
import time
from urllib.parse import urlencode

import pandas as pd
import requests


SEARCH_URL = "https://lva.primo.exlibrisgroup.com/primaws/rest/pub/pnxs"
VIEW_ID = "01LVA_INST:01LVA"
PAGE_SIZE = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterData-research/1.0)"}

COLLECTIONS = [
    ("Mark R. Warner", "2002-2006", "warner", "81116276840005756"),
    ("Timothy M. Kaine", "2006-2010", "kaine", "81116276830005756"),
    ("Robert F. McDonnell", "2010-2014", "mcdonnell", "81116276820005756"),
    ("Terry McAuliffe", "2014-2018", "mcauliffe", "81116276810005756"),
    ("Ralph S. Northam", "2018-2022", "northam", "81116196030005756"),
    ("Glenn Youngkin", "2022-2026", "youngkin", "81187807320005756"),
]

ORDER_PATTERN = re.compile(
    r"^Executive\s+(Order|Directive)\s+(?:Number\s+)?([A-Za-z0-9-]+)\s*"
    r"(?:\((\d{4})\))?\s*(.*)$",
    flags=re.I,
)

PROCEDURAL_PATTERNS = [
    r"delegat(?:e|es|ed|ing|ion)",
    r"authority to declare",
    r"succession authority",
    r"when the governor is out",
]

WEATHER_PATTERNS = {
    "cold": r"\b(?:extreme |severe )?cold\b|\bwind chill\b",
    "drought": r"\bdrought\b",
    "fire": r"\b(?:wildfire|forest fire|brush fire)s?\b",
    "flood": r"\bflood(?:ing|s|ed)?\b",
    "freeze": r"\bfreez(?:e|ing)\b|\bfrost\b",
    "hail": r"\bhail\b",
    "heat": r"\b(?:extreme |excessive )?heat\b",
    "hurricane": r"\bhurricane\b",
    "ice": r"\bice\b|\bicing\b|\bsleet\b",
    "landslide": r"\b(?:landslide|mudslide)s?\b",
    "rain": r"\brain(?:fall)?\b",
    "snow": r"\bsnow(?:fall|storm)?s?\b|\bblizzard\b",
    "storm": r"\b(?:severe |winter )?storm(?:s)?\b",
    "tornado": r"\btornado(?:es)?\b",
    "tropical": r"\btropical (?:storm|depression|cyclone)\b",
    "wind": r"\b(?:high |strong |straight-line )?winds?\b",
    "winter weather": r"\bwinter weather\b",
}


def first(mapping, key, default=""):
    value = mapping.get(key, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def fetch_collection(collection_id, session):
    offset = 0
    documents = []
    total = None
    while total is None or offset < total:
        params = {
            "vid": VIEW_ID,
            "inst": "01LVA_INST",
            "scope": "browse_search",
            "tab": "default_tab",
            "q": f"cdparentid,exact,{collection_id}",
            "offset": offset,
            "limit": PAGE_SIZE,
            "lang": "en",
            "isCDSearch": "true",
            "skipDelivery": "Y",
        }
        response = session.get(SEARCH_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        page = payload.get("docs", [])
        total = int(payload.get("info", {}).get("total", len(page)))
        if not page:
            break
        documents.extend(page)
        offset += len(page)
        time.sleep(0.15)
    return documents, total or 0


def parse_order_title(title):
    match = ORDER_PATTERN.match(title.strip())
    if not match:
        return {"document_type": "", "eo_number": "", "title_year": "", "subject": title}
    kind, number, year, subject = match.groups()
    prefix = "EO" if kind.lower() == "order" else "ED"
    return {
        "document_type": f"Executive {kind.title()}",
        "eo_number": f"{prefix}-{number}",
        "title_year": year or "",
        "subject": subject.strip().rstrip("."),
    }


def classify_action(title):
    lowered = title.lower()
    procedural = any(re.search(pattern, lowered) for pattern in PROCEDURAL_PATTERNS)
    emergency = "state of emergency" in lowered or "emergency declaration" in lowered
    if procedural:
        action_type = "procedural"
    elif re.search(r"\b(?:rescind|rescission|terminate|termination|expire|expiration)", lowered):
        action_type = "termination"
    elif re.search(r"\b(?:modify|modification|amend|extension|extend|continuing|continuation|renew)", lowered):
        action_type = "modification_or_extension"
    elif emergency:
        action_type = "declaration"
    else:
        action_type = "other"

    hazards = [name for name, pattern in WEATHER_PATTERNS.items() if re.search(pattern, lowered)]
    support_signal = bool(
        re.search(
            r"\bin support of\b|\bemergency management assistance compact\b|"
            r"\bgulf coast states\b|\bstates affected by\b",
            lowered,
        )
    )
    virginia_cause_signal = bool(
        re.search(r"\bdue to\b|\bin response to\b|\bas a result of\b", lowered)
    )
    external_assistance_only = bool(
        emergency and not procedural and hazards and support_signal and not virginia_cause_signal
    )
    return {
        "is_emergency_action": bool(emergency and not procedural),
        "action_type": action_type,
        "weather_related": bool(emergency and not procedural and hazards),
        "weather_hazards": "; ".join(hazards),
        "external_assistance_only": external_assistance_only,
    }


def archive_record_url(record_id):
    query = urlencode(
        {
            "docid": record_id,
            "context": "L",
            "vid": VIEW_ID,
            "lang": "en",
        }
    )
    return f"https://lva.primo.exlibrisgroup.com/discovery/fulldisplay?{query}"


def document_to_row(document, governor, administration, governor_key, collection_id):
    pnx = document.get("pnx", {})
    display = pnx.get("display", {})
    control = pnx.get("control", {})
    title = str(first(display, "title")).strip()
    parsed = parse_order_title(title)
    classification = classify_action(title)
    record_id = str(first(control, "recordid"))
    date_signed = str(first(display, "creationdate"))
    year = parsed["title_year"] or (date_signed[:4] if date_signed else "")
    declaration_id = "-".join(
        part.upper() for part in ["VA", governor_key, parsed["eo_number"], year] if part
    )
    return {
        "declaration_id": declaration_id,
        "governor": governor,
        "administration": administration,
        "governor_key": governor_key,
        "collection_id": collection_id,
        "record_id": record_id,
        "document_type": parsed["document_type"],
        "eo_number": parsed["eo_number"],
        "year": year,
        "date_signed": date_signed,
        "event_description": title,
        "subject": parsed["subject"],
        **classification,
        "format": str(first(display, "format")),
        "archive_record_url": archive_record_url(record_id),
        "document_url": str(first(display, "lds14")),
        "source": "Library of Virginia Executive Orders Digital Collection",
    }


def current_rows(path):
    if not path:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    required = {"eo_number", "event_description", "date_signed"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("Current CSV is missing: " + ", ".join(sorted(missing)))
    frame = frame.copy()
    frame["year"] = frame["date_signed"].astype(str).str[:4]
    frame["declaration_id"] = (
        "VA-SPANBERGER-" + frame["eo_number"].astype(str) + "-" + frame["year"]
    ).str.upper()
    frame["governor"] = "Abigail D. Spanberger"
    frame["action_type"] = "declaration"
    frame["external_assistance_only"] = False
    frame["version_count"] = 1
    frame["archive_record_url"] = ""
    return frame[
        [
            "declaration_id",
            "eo_number",
            "governor",
            "event_description",
            "date_signed",
            "action_type",
            "external_assistance_only",
            "version_count",
            "archive_record_url",
        ]
    ]


def consolidate_declaration_versions(frame):
    """Collapse revised copies of the same EO while retaining the original date."""
    rows = []
    for _, group in frame.groupby("declaration_id", sort=False):
        group = group.copy()
        group["_quality"] = (
            (~group["external_assistance_only"]).astype(int) * 10000
            + group["event_description"].str.contains(r"\bdue to\b", case=False, regex=True).astype(int) * 1000
            + group["event_description"].str.len()
        )
        best = group.sort_values("_quality", ascending=False).iloc[0].drop(labels="_quality").copy()
        valid_dates = pd.to_datetime(group["date_signed"], errors="coerce").dropna()
        if not valid_dates.empty:
            best["date_signed"] = valid_dates.min().date().isoformat()
        best["version_count"] = len(group)
        best["external_assistance_only"] = bool(group["external_assistance_only"].all())
        best["archive_record_urls"] = "; ".join(
            sorted(set(group["archive_record_url"].dropna().astype(str)))
        )
        rows.append(best)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Scrape Virginia EO archive, 2002-2026")
    parser.add_argument("--all-out", default="va_eo_archive_all.csv")
    parser.add_argument("--emergency-out", default="va_emergency_actions_2002_2026.csv")
    parser.add_argument("--weather-out", default="va_weather_emergency_actions_2002_2026.csv")
    parser.add_argument("--join-out", default="declarations_for_join_2002_present.csv")
    parser.add_argument("--current-csv", default="")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)
    rows = []
    for governor, administration, governor_key, collection_id in COLLECTIONS:
        documents, reported_total = fetch_collection(collection_id, session)
        print(f"{governor} ({administration}): fetched {len(documents)} of {reported_total} items")
        rows.extend(
            document_to_row(document, governor, administration, governor_key, collection_id)
            for document in documents
        )

    all_orders = pd.DataFrame(rows).drop_duplicates(subset=["record_id"])
    all_orders.to_csv(args.all_out, index=False)

    emergency = all_orders[all_orders["is_emergency_action"]].copy()
    emergency.to_csv(args.emergency_out, index=False)

    weather = emergency[emergency["weather_related"]].copy()
    weather.to_csv(args.weather_out, index=False)

    initial_versions = weather[weather["action_type"] == "declaration"].copy()
    consolidated_initial = consolidate_declaration_versions(initial_versions)
    initial = consolidated_initial[~consolidated_initial["external_assistance_only"]].copy()
    join_columns = [
        "declaration_id",
        "eo_number",
        "governor",
        "event_description",
        "date_signed",
        "action_type",
        "external_assistance_only",
        "version_count",
        "archive_record_url",
    ]
    join_frame = initial[join_columns]
    if args.current_csv:
        join_frame = pd.concat([join_frame, current_rows(args.current_csv)], ignore_index=True)
    join_frame = join_frame.drop_duplicates(subset=["declaration_id"]).sort_values("date_signed")
    join_frame.to_csv(args.join_out, index=False)

    print(f"\nWrote {len(all_orders)} archived records to {args.all_out}")
    print(f"Wrote {len(emergency)} emergency actions to {args.emergency_out}")
    print(f"Wrote {len(weather)} weather emergency actions to {args.weather_out}")
    print(f"Wrote {len(join_frame)} initial declarations to {args.join_out}")
    print("\nInitial weather declarations by governor:")
    print(join_frame.groupby("governor").size().to_string())

    followups = weather[weather["action_type"] != "declaration"]
    if not followups.empty:
        print(
            f"\nReview {len(followups)} weather-related modifications, extensions, "
            f"or terminations in {args.weather_out}; they are not treated as new incidents."
        )

    aid_only = consolidated_initial[consolidated_initial["external_assistance_only"]]
    if not aid_only.empty:
        print(
            f"Review {len(aid_only)} interstate-assistance declarations in "
            f"{args.weather_out}; they are excluded from Virginia locality matching."
        )


if __name__ == "__main__":
    main()
