#!/usr/bin/env python3
"""
gen_decl_index.py

Builds the per state declaration index that powers the Compare page on
DisasterData.IO. One JSON file per state or territory, each listing the
jurisdictions in that state and every declaration with the FIPS codes it
designated.

Output schema, one file per state at OUT_DIR/{ST}.json:

  {
    "state": "VA",
    "generated": "2026-07-23",
    "jurisdictions": [
      {"fips": "51021", "name": "Bland", "type": "County"}
    ],
    "declarations": [
      {"id": "DR-4863", "number": 4863, "type": "DR",
       "title": "Winter Storm Jett", "incidentType": "Severe Winter Storm",
       "date": "2025-02-24", "year": 2025, "statewide": false,
       "incidentBegin": "2025-02-15", "incidentEnd": "2025-02-17",
       "eventId": "winter-storm-jett-2025",
       "eventName": "Jett (2025)",
       "eventStates": ["VA", "WV"],
       "programs": ["IA", "PA", "HM"],
       "fips": ["51021", "51520"]}
    ]
  }

Event grouping: FEMA issues a separate disaster number per state for the
same storm, so a single event like Helene appears as several declarations
across state files. This builder clusters them into one event and stamps
every member with a shared eventId (plus a display eventName and the full
list of eventStates). Named storms are grouped by the storm name in the
title within a date window; unnamed events are grouped by incident type
where their incident windows overlap. The Compare page uses eventId to
collapse the per state pieces into one selectable event.

Usage:
  python gen_decl_index.py --out data/decl-index
  python gen_decl_index.py --out data/decl-index --states VA,TN,WV,KY,NC
  python gen_decl_index.py --out data/decl-index --source-file cache/dds.json
  python gen_decl_index.py --out data/decl-index --jurisdictions data/jurisdictions.json

Source: FEMA OpenFEMA DisasterDeclarationsSummaries v2.
This product uses the FEMA OpenFEMA API but is not endorsed by FEMA.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import date, datetime

API_BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
PAGE_SIZE = 10000          # OpenFEMA maximum per call
USER_AGENT = "DisasterData.IO index builder (contact via site)"

# Only the fields the index needs. Trimming the payload cuts the download
# from tens of megabytes to a few.
SELECT_FIELDS = [
    "disasterNumber",
    "state",
    "declarationType",
    "declarationDate",
    "fyDeclared",
    "incidentType",
    "declarationTitle",
    "incidentBeginDate",
    "incidentEndDate",
    "fipsStateCode",
    "fipsCountyCode",
    "designatedArea",
    "placeCode",
    "iaProgramDeclared",
    "ihProgramDeclared",
    "paProgramDeclared",
    "hmProgramDeclared",
    "tribalRequest",
]

# designatedArea arrives as "Bland (County)" or "Bristol (City)".
AREA_RE = re.compile(r"^\s*(.+?)\s*\(([^)]+)\)\s*$")

# Values that mean "the whole state" rather than a single jurisdiction.
STATEWIDE_TOKENS = {"statewide", "state-wide", "state wide"}


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------

def fetch_page(skip, page_size, states=None):
    """One paged call against OpenFEMA. Returns the record list."""
    params = [
        ("$select", ",".join(SELECT_FIELDS)),
        ("$top", str(page_size)),
        ("$skip", str(skip)),
        ("$orderby", "disasterNumber"),
    ]
    if states:
        clause = " or ".join("state eq '%s'" % s for s in states)
        params.append(("$filter", "(%s)" % clause))

    url = API_BASE + "?" + urllib.parse.urlencode(params, safe="$,'() ")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("DisasterDeclarationsSummaries", [])


def fetch_all(states=None, page_size=PAGE_SIZE, pause=1.0):
    """Page through the dataset until a short page comes back."""
    records = []
    skip = 0
    while True:
        batch = fetch_page(skip, page_size, states)
        records.extend(batch)
        sys.stderr.write("  fetched %d records (total %d)\n" % (len(batch), len(records)))
        sys.stderr.flush()
        if len(batch) < page_size:
            break
        skip += page_size
        time.sleep(pause)
    return records


def load_source_file(path):
    """Read a cached copy instead of hitting the API. JSON or CSV."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        return payload.get("DisasterDeclarationsSummaries", [])
    return payload


# ----------------------------------------------------------------------
# Normalizing
# ----------------------------------------------------------------------

def parse_area(designated_area):
    """'Bland (County)' becomes ('Bland', 'County')."""
    raw = (designated_area or "").strip()
    if not raw:
        return ("", "")
    match = AREA_RE.match(raw)
    if match:
        return (match.group(1).strip(), match.group(2).strip())
    return (raw, "")


def pad(value, width):
    """FIPS codes arrive as strings from JSON and as ints from CSV."""
    if value is None:
        return ""
    text = str(value).strip()
    if text in ("", "nan", "None"):
        return ""
    if text.isdigit():
        return text.zfill(width)
    return text


def is_statewide(record, county_code):
    area = (record.get("designatedArea") or "").strip().lower()
    if area in STATEWIDE_TOKENS:
        return True
    return county_code in ("", "000")


def iso_date(value):
    """OpenFEMA returns 2024-10-01T00:00:00.000Z. Keep the date only."""
    if not value:
        return ""
    text = str(value).strip()
    return text.split("T")[0][:10]


def to_date(value):
    """Parse an ISO date string to a date, or None."""
    text = iso_date(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


# Incident types that carry a storm name we can group on across states.
NAMED_TYPES = {"hurricane", "tropical storm", "tropical depression", "typhoon"}

# Grab the name after a storm keyword: "Hurricane Helene" -> "Helene".
STORM_RE = re.compile(r"\b(?:hurricane|tropical storm|tropical depression|typhoon)\b\s+([A-Za-z]+)", re.I)

# Words that follow the keyword but are not a storm name.
NAME_STOPWORDS = {"and", "or", "the", "flooding", "flood", "severe", "storms",
                  "storm", "related", "associated", "remnants", "system", "event"}

# How far apart two declarations' incident windows may sit and still count as
# the same event. Named storms get a wide window since states declare on a lag;
# unnamed events require near overlap so distinct events don't merge.
GAP_NAMED_DAYS = 60
GAP_UNNAMED_DAYS = 3


def extract_storm_name(title):
    """Return the storm name from a declaration title, or None."""
    if not title:
        return None
    m = STORM_RE.search(title)
    if not m:
        return None
    token = m.group(1).strip()
    if len(token) < 3 or token.lower() in NAME_STOPWORDS:
        return None
    return token[0].upper() + token[1:].lower()


def assign_events(all_decls):
    """
    Cluster declarations from every state into events and stamp each with a
    shared eventId, a display eventName, and the full list of eventStates.
    Mutates the declaration dicts in place; they are the same objects held in
    the per state output, so the stamp lands in every file.
    """
    from collections import defaultdict

    for d in all_decls:
        itype = (d.get("incidentType") or "").strip()
        name = extract_storm_name(d.get("title")) if itype.lower() in NAMED_TYPES else None
        d["_name"] = name
        d["_key"] = ("name:" + name.lower()) if name else ("type:" + itype.lower())

    groups = defaultdict(list)
    for d in all_decls:
        groups[d["_key"]].append(d)

    clusters = []
    for key, items in groups.items():
        named = key.startswith("name:")
        gap = GAP_NAMED_DAYS if named else GAP_UNNAMED_DAYS
        items.sort(key=lambda x: (x.get("_begin") or date.min, x.get("number") or 0))

        cur = []
        cur_end = None
        for d in items:
            begin = d.get("_begin") or d.get("_end")
            end = d.get("_end") or d.get("_begin")
            if cur and begin is not None and cur_end is not None and (begin - cur_end).days > gap:
                clusters.append(cur)
                cur = []
                cur_end = None
            cur.append(d)
            edge = end or begin
            if edge is not None:
                cur_end = edge if cur_end is None else max(cur_end, edge)
        if cur:
            clusters.append(cur)

    used = set()
    for cl in clusters:
        begins = [d["_begin"] for d in cl if d.get("_begin")]
        year = min(begins).year if begins else (cl[0].get("year") or 0)
        name = next((d["_name"] for d in cl if d.get("_name")), None)
        states = sorted(set(d["_state"] for d in cl))

        if name:
            base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + "-" + str(year)
            display = name + " (" + str(year) + ")"
        else:
            itype = (cl[0].get("incidentType") or "Event").strip()
            base = re.sub(r"[^a-z0-9]+", "-", itype.lower()).strip("-") + "-" + str(year)
            month = min(begins).strftime("%b") if begins else ""
            display = itype + ((" (" + month + " " + str(year) + ")") if month else (" (" + str(year) + ")"))

        slug = base
        n = 2
        while slug in used:
            slug = base + "-" + str(n)
            n += 1
        used.add(slug)

        for d in cl:
            d["eventId"] = slug
            d["eventName"] = display
            d["eventStates"] = states


def program_list(record):
    out = []
    for flag, label in (("iaProgramDeclared", "IA"),
                        ("ihProgramDeclared", "IH"),
                        ("paProgramDeclared", "PA"),
                        ("hmProgramDeclared", "HM")):
        raw = record.get(flag)
        if raw in (1, "1", True, "true", "True"):
            out.append(label)
    return out


def load_jurisdiction_override(path):
    """
    Optional canonical jurisdiction list, keyed by state.

    Accepts either a flat list of {fips, name, type} or an object keyed by
    state code. Without this, the jurisdiction universe is derived from
    every FIPS that has ever appeared in a declaration, which misses any
    county that has never been designated.
    """
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)

    by_state = {}
    if isinstance(payload, dict):
        for state, entries in payload.items():
            by_state[state] = {
                pad(e.get("fips"), 5): {
                    "fips": pad(e.get("fips"), 5),
                    "name": e.get("name", ""),
                    "type": e.get("type", ""),
                }
                for e in entries
            }
        return by_state

    for entry in payload:
        fips = pad(entry.get("fips"), 5)
        state = entry.get("state") or entry.get("stateAbbr")
        if not state or not fips:
            continue
        by_state.setdefault(state, {})[fips] = {
            "fips": fips,
            "name": entry.get("name", ""),
            "type": entry.get("type", ""),
        }
    return by_state


# ----------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------

def build_indexes(records, decl_types=None, jurisdiction_override=None):
    """
    Two passes. The first collects every real jurisdiction so that
    statewide declarations can be expanded against a complete list. The
    second attaches FIPS codes to each declaration.
    """
    jurisdictions = {}   # state -> fips -> {fips, name, type}
    declarations = {}    # state -> (type, number) -> record
    pending_statewide = []
    skipped = {"no_state": 0, "wrong_type": 0, "no_fips": 0}

    # Pass one: jurisdictions
    for rec in records:
        state = (rec.get("state") or "").strip().upper()
        if not state:
            skipped["no_state"] += 1
            continue
        county = pad(rec.get("fipsCountyCode"), 3)
        state_fips = pad(rec.get("fipsStateCode"), 2)
        if is_statewide(rec, county) or not state_fips:
            continue
        fips = state_fips + county
        if len(fips) != 5 or not fips.isdigit():
            continue
        name, area_type = parse_area(rec.get("designatedArea"))
        bucket = jurisdictions.setdefault(state, {})
        # Later records carry the current naming, so let them win.
        if fips not in bucket or (name and not bucket[fips]["name"]):
            bucket[fips] = {"fips": fips, "name": name, "type": area_type}

    if jurisdiction_override:
        for state, entries in jurisdiction_override.items():
            bucket = jurisdictions.setdefault(state, {})
            for fips, entry in entries.items():
                bucket[fips] = entry

    # Pass two: declarations
    for rec in records:
        state = (rec.get("state") or "").strip().upper()
        if not state:
            continue
        dtype = (rec.get("declarationType") or "").strip().upper()
        if decl_types and dtype not in decl_types:
            skipped["wrong_type"] += 1
            continue

        try:
            number = int(rec.get("disasterNumber"))
        except (TypeError, ValueError):
            continue

        key = (dtype, number)
        entry = declarations.setdefault(state, {}).get(key)
        if entry is None:
            declared = iso_date(rec.get("declarationDate"))
            try:
                year = int(rec.get("fyDeclared") or 0)
            except (TypeError, ValueError):
                year = 0
            if declared[:4].isdigit():
                year = int(declared[:4])
            entry = {
                "id": "%s-%d" % (dtype, number),
                "number": number,
                "type": dtype,
                "title": (rec.get("declarationTitle") or "").strip(),
                "incidentType": (rec.get("incidentType") or "Other").strip(),
                "date": declared,
                "year": year,
                "statewide": False,
                "tribal": rec.get("tribalRequest") in (1, "1", True, "true", "True"),
                "programs": program_list(rec),
                "_state": state,
                "_begin": to_date(rec.get("incidentBeginDate")),
                "_end": to_date(rec.get("incidentEndDate")),
                "_fips": set(),
            }
            declarations[state][key] = entry

        # Widen the incident window as more rows for this declaration arrive.
        rb = to_date(rec.get("incidentBeginDate"))
        re_ = to_date(rec.get("incidentEndDate"))
        if rb and (entry["_begin"] is None or rb < entry["_begin"]):
            entry["_begin"] = rb
        if re_ and (entry["_end"] is None or re_ > entry["_end"]):
            entry["_end"] = re_

        for label in program_list(rec):
            if label not in entry["programs"]:
                entry["programs"].append(label)

        county = pad(rec.get("fipsCountyCode"), 3)
        state_fips = pad(rec.get("fipsStateCode"), 2)

        if is_statewide(rec, county):
            entry["statewide"] = True
            pending_statewide.append((state, key))
            continue

        fips = state_fips + county
        if len(fips) != 5 or not fips.isdigit():
            skipped["no_fips"] += 1
            continue
        entry["_fips"].add(fips)

    # Expand statewide declarations across every jurisdiction in the state
    for state, key in pending_statewide:
        entry = declarations[state][key]
        for fips in jurisdictions.get(state, {}):
            entry["_fips"].add(fips)

    # Cluster declarations across every state into events. This mutates the
    # entry dicts in place, so eventId lands in each state's output.
    all_entries = []
    for state in declarations:
        for entry in declarations[state].values():
            all_entries.append(entry)
    assign_events(all_entries)

    # Freeze into output shape
    today = date.today().isoformat()
    out = {}
    for state in sorted(declarations):
        decls = []
        for key in sorted(declarations[state], key=lambda k: (-k[1], k[0])):
            entry = declarations[state][key]
            fips_list = sorted(entry.pop("_fips"))
            begin = entry.pop("_begin", None)
            end = entry.pop("_end", None)
            entry.pop("_state", None)
            entry.pop("_name", None)
            entry.pop("_key", None)
            entry["incidentBegin"] = begin.isoformat() if begin else ""
            entry["incidentEnd"] = end.isoformat() if end else ""
            entry.setdefault("eventId", entry["id"])
            entry.setdefault("eventName", entry["title"] or entry["id"])
            entry.setdefault("eventStates", [state])
            entry["fips"] = fips_list
            decls.append(entry)

        juris = sorted(jurisdictions.get(state, {}).values(),
                       key=lambda j: (j["name"], j["fips"]))
        out[state] = OrderedDict([
            ("state", state),
            ("generated", today),
            ("source", "FEMA OpenFEMA DisasterDeclarationsSummaries v2"),
            ("jurisdictions", juris),
            ("declarations", decls),
        ])

    sys.stderr.write("  skipped: %s\n" % json.dumps(skipped))
    return out


def write_indexes(indexes, out_dir, pretty=False):
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for state, index in sorted(indexes.items()):
        path = os.path.join(out_dir, "%s.json" % state)
        with open(path, "w", encoding="utf-8") as fh:
            if pretty:
                json.dump(index, fh, indent=2)
            else:
                json.dump(index, fh, separators=(",", ":"))
        manifest.append({
            "state": state,
            "file": "%s.json" % state,
            "jurisdictions": len(index["jurisdictions"]),
            "declarations": len(index["declarations"]),
            "bytes": os.path.getsize(path),
        })

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generated": date.today().isoformat(),
            "states": manifest,
        }, fh, indent=2)
    return manifest


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build per state declaration index files.")
    ap.add_argument("--out", default="data/decl-index",
                    help="Output directory (default data/decl-index)")
    ap.add_argument("--states", default="",
                    help="Comma separated state codes. Default is every state.")
    ap.add_argument("--decl-types", default="DR,EM,FM",
                    help="Declaration types to include (default DR,EM,FM)")
    ap.add_argument("--source-file", default="",
                    help="Read a cached JSON or CSV export instead of calling the API")
    ap.add_argument("--jurisdictions", default="",
                    help="Optional canonical jurisdiction list to override the derived one")
    ap.add_argument("--pretty", action="store_true",
                    help="Indent the JSON. Larger files, easier to diff.")
    args = ap.parse_args()

    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    decl_types = set(t.strip().upper() for t in args.decl_types.split(",") if t.strip())

    if args.source_file:
        sys.stderr.write("Reading %s\n" % args.source_file)
        records = load_source_file(args.source_file)
        sys.stderr.write("  %d records\n" % len(records))
    else:
        sys.stderr.write("Fetching DisasterDeclarationsSummaries\n")
        records = fetch_all(states or None)

    override = load_jurisdiction_override(args.jurisdictions) if args.jurisdictions else None

    sys.stderr.write("Building indexes\n")
    indexes = build_indexes(records, decl_types, override)

    if states:
        indexes = {k: v for k, v in indexes.items() if k in states}

    manifest = write_indexes(indexes, args.out, args.pretty)

    total = sum(m["bytes"] for m in manifest)
    sys.stderr.write("Wrote %d state files to %s (%.1f KB total)\n"
                     % (len(manifest), args.out, total / 1024.0))
    for m in manifest:
        if states or len(manifest) <= 10:
            sys.stderr.write("  %s: %d jurisdictions, %d declarations, %.1f KB\n"
                             % (m["state"], m["jurisdictions"],
                                m["declarations"], m["bytes"] / 1024.0))


if __name__ == "__main__":
    main()
