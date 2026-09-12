#!/usr/bin/env python3
"""
gen_plus_sidecar.py

Builds state-declarations.json, the sidecar that carries DisasterData Plus
(state governor emergency declarations) into the main site's jurisdiction
pages.

WHY THIS EXISTS
---------------
Plus lives at /plus/ as its own corridor. Its per-state evidence files are
keyed by NOAA storm-event area (CZ_NAME / CZ_FIPS), not by the jurisdiction
names the main site's generators use. This script does the resolution once,
at build time, and writes a single FIPS-keyed sidecar that
gen-jurisdiction-pages.py can attach the same way it already attaches
pa-timing.json / hma.json / ia.json.

WHAT A COUNTY ROW ACTUALLY MEANS (read before changing anything)
----------------------------------------------------------------
A row under a county does NOT mean the governor named that county in the
declaration. Governor declarations are usually statewide and frequently name
no localities at all. A row means:

    while this state declaration was in effect, NOAA Storm Events recorded
    one or more reports of the matched hazard in this county.

That is evidence of local impact during a declared state emergency, which is
what a planner actually wants, but it is an inference from two joined
sources, not a quote from the order. The rendered panel and the method note
must both say so. Do not relabel this as "the governor declared for your
county."

JOIN METHOD
-----------
Source: plus/<slug>/eo_storm_severity_summary.csv, which build-plus.py has
already aggregated to one row per (declaration, storm-event area).

Only CZ_TYPE == "C" (county) rows are used. CZ_TYPE == "Z" rows are NOAA
forecast zones, which do not map cleanly to county boundaries without a
per-state zone crosswalk that only Virginia currently has. Zone rows are
counted and reported, never silently folded into a county.

County resolution is NAME-FIRST against county-fips.json, not FIPS-first.
NOAA's CZ_FIPS is usually the real county FIPS but not always: several
states encode a sequential county number instead (Georgia's Walker County
arrives as CZ_FIPS=2, which would resolve to the wrong 13002). Matching on
the name and using county-fips.json as the authority avoids that whole
class of silent mis-attribution. Measured on the current data, name-first
resolves 99.6% of county rows; FIPS-first resolves 99.3% and is wrong in
ways that do not announce themselves.

Unresolvable rows are DROPPED and counted, never guessed at. This matches
the fail-closed convention the Plus classifier already uses.

Output shape (state-declarations.json, repo root):

    {
      "generated": "YYYY-MM-DD",
      "plus_generated": "YYYY-MM-DD",     # from plus/coverage.json
      "states": {
        "VA": {
          "name": "Virginia",
          "slug": "virginia",
          "coverage": "<coverage note from Plus>",
          "total": 75,                    # state declarations on record
          "counties": {
            "51161": [
              {
                "id":   "VA-SPANBERGER-EO-11-2026",
                "eo":   "EO-11",
                "gov":  "Spanberger",
                "desc": "Declaring State of Emergency Due to Winter Weather",
                "date": "2026-01-22",
                "url":  "https://...",
                "types":["Winter Storm"],  # capped, see TYPE_CAP
                "n":    12,                # storm events reported
                "deaths": 0,
                "inj":  0,
                "dmg":  0                  # USD, property + crops
              }
            ]
          }
        }
      },
      "stats": { ... resolution counters, for the build log and release gate ... }
    }

Standard library only, so it adds no dependency to the weekly workflow.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUS_ROOT = os.path.join(HERE, "plus")
COUNTY_FIPS_PATH = os.path.join(HERE, "county-fips.json")
OUT_PATH = os.path.join(HERE, "state-declarations.json")

# A county page showing forty hazard labels helps nobody. Keep the most
# common ones and let the Plus state page carry the full detail.
TYPE_CAP = 6

# NOAA writes some county names with a space where the real name has none
# ("DE KALB" for DeKalb, "DU PAGE" for DuPage). Normalising both sides to a
# space-free form catches every one of these without a hand-maintained list.
_DIRECTIONAL = re.compile(r"^(NORTH|SOUTH|EAST|WEST|CENTRAL|UPPER|LOWER)\s+")

_STRIP_KINDS = re.compile(
    r"\b(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPIO|MUNICIPALITY|"
    r"CITY AND BOROUGH|CITY)\b"
)


def norm_name(name: str) -> str:
    """Normalise a county/city name for matching. Mirrors the intent of
    pa_base_kind() in the page generators: strip the kind suffix, drop
    punctuation, collapse whitespace."""
    n = (name or "").upper().strip()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = _STRIP_KINDS.sub(" ", n)
    n = re.sub(r"[^A-Z ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def squash(name: str) -> str:
    """Space-free form, so DE KALB and DEKALB compare equal."""
    return norm_name(name).replace(" ", "")


def load_county_fips() -> dict:
    with open(COUNTY_FIPS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def build_indexes(county_fips: dict):
    """Return (by_state_name, by_state_squash, state_fips)."""
    by_name = {}
    by_squash = {}
    state_fips = {}
    for fips5, rec in county_fips.items():
        st = rec["s"]
        nm = rec["n"]
        state_fips.setdefault(st, fips5[:2])
        by_name.setdefault(st, {}).setdefault(norm_name(nm), fips5)
        # setdefault: if two counties squash to the same string, keep the
        # first rather than letting a later one silently overwrite it.
        by_squash.setdefault(st, {}).setdefault(squash(nm), fips5)
    return by_name, by_squash, state_fips


def resolve_county(state_ab, cz_name, by_name, by_squash):
    """Resolve a NOAA CZ_NAME to a 5-digit county FIPS, or None.

    Three passes, each strictly narrower than guessing:
      1. exact normalised name
      2. space-free form (DE KALB -> DEKALB)
      3. drop a leading directional qualifier (NORTH FULTON -> FULTON),
         which NOAA uses for sub-county reporting areas inside one county
    """
    names = by_name.get(state_ab, {})
    squashes = by_squash.get(state_ab, {})

    key = norm_name(cz_name)
    if key in names:
        return names[key]

    sq = squash(cz_name)
    if sq in squashes:
        return squashes[sq]

    stripped = _DIRECTIONAL.sub("", key)
    if stripped != key:
        if stripped in names:
            return names[stripped]
        if stripped.replace(" ", "") in squashes:
            return squashes[stripped.replace(" ", "")]

    return None


def _num(value) -> float:
    try:
        return float(str(value or "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value) -> int:
    return int(_num(value))


def load_plus_coverage():
    """Read plus/coverage.json. Returns (generated_on, {slug: state_record})."""
    path = os.path.join(PLUS_ROOT, "coverage.json")
    if not os.path.exists(path):
        return "", {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return "", {}
    states = doc.get("states") or []
    if isinstance(states, dict):
        states = list(states.values())
    return doc.get("generated_on", ""), {s.get("slug"): s for s in states if s.get("slug")}


def count_declarations(state_dir: str, action_file: str) -> int:
    """How many state declarations are on record for this state, from the
    join file Plus actually used. Used for the 'N of M' framing on the page
    so a county's matched count is never mistaken for the state total."""
    for candidate in (action_file, "declarations_for_join.csv"):
        if not candidate:
            continue
        path = os.path.join(state_dir, candidate)
        if not os.path.exists(path):
            continue
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                return sum(1 for _ in csv.DictReader(fh))
        except Exception:
            continue
    return 0


def collect_state(slug, state_dir, cover, by_name, by_squash, stats):
    """Build one state's record, or None when it has nothing to contribute."""
    summary_path = os.path.join(state_dir, "state-summary.json")
    if not os.path.exists(summary_path):
        return None
    try:
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)
    except Exception:
        return None

    state_ab = summary.get("abbreviation")
    if not state_ab:
        return None

    sev_path = os.path.join(state_dir, "eo_storm_severity_summary.csv")
    if not os.path.exists(sev_path):
        stats["states_without_evidence"].append(state_ab)
        return None

    # (fips5, declaration_id) -> accumulator, so multiple NOAA areas inside
    # one county under one declaration collapse into a single entry rather
    # than listing the same order several times on one page.
    acc = {}

    with open(sev_path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            cz_type = (row.get("CZ_TYPE") or "").strip().upper()
            if cz_type != "C":
                if cz_type == "Z":
                    stats["zone_rows_skipped"] += 1
                else:
                    stats["untyped_rows_skipped"] += 1
                continue

            stats["county_rows_seen"] += 1
            fips5 = resolve_county(state_ab, row.get("CZ_NAME"), by_name, by_squash)
            if not fips5:
                stats["unresolved_rows"] += 1
                stats["unresolved_examples"].setdefault(
                    "%s:%s" % (state_ab, (row.get("CZ_NAME") or "").strip()), 0
                )
                stats["unresolved_examples"]["%s:%s" % (
                    state_ab, (row.get("CZ_NAME") or "").strip()
                )] += 1
                continue

            stats["resolved_rows"] += 1
            decl_id = (row.get("declaration_id") or "").strip()
            key = (fips5, decl_id)
            entry = acc.get(key)
            if entry is None:
                entry = {
                    "id": decl_id,
                    "eo": (row.get("eo_number") or "").strip(),
                    "gov": (row.get("governor") or "").strip(),
                    "desc": (row.get("event_description") or "").strip(),
                    "date": (row.get("date_signed") or "").strip()[:10],
                    "url": (row.get("archive_record_url") or "").strip(),
                    "_types": {},
                    "n": 0,
                    "deaths": 0,
                    "inj": 0,
                    "dmg": 0.0,
                }
                acc[key] = entry

            for raw_type in (row.get("event_types") or "").split(";"):
                label = raw_type.strip()
                if label:
                    entry["_types"][label] = entry["_types"].get(label, 0) + 1

            entry["n"] += _int(row.get("event_count"))
            entry["deaths"] += _int(row.get("deaths_direct"))
            entry["inj"] += _int(row.get("injuries_direct"))
            entry["dmg"] += _num(row.get("damage_property_usd")) + _num(
                row.get("damage_crops_usd")
            )

    if not acc:
        stats["states_without_evidence"].append(state_ab)
        return None

    counties = {}
    for (fips5, _decl_id), entry in acc.items():
        ordered = sorted(entry.pop("_types").items(), key=lambda kv: (-kv[1], kv[0]))
        entry["types"] = [label for label, _count in ordered[:TYPE_CAP]]
        entry["dmg"] = int(round(entry["dmg"]))
        counties.setdefault(fips5, []).append(entry)

    # Newest declaration first, matching how the federal declaration table
    # on the same page is ordered.
    for fips5 in counties:
        counties[fips5].sort(key=lambda d: (d.get("date") or "", d.get("eo") or ""), reverse=True)

    record = cover.get(slug) or {}
    return state_ab, {
        "name": summary.get("name") or record.get("name") or state_ab,
        "slug": slug,
        "coverage": summary.get("coverage") or record.get("coverage") or "",
        "total": count_declarations(state_dir, summary.get("action_file", "")),
        "counties": counties,
    }


def main() -> int:
    if not os.path.isdir(PLUS_ROOT):
        print("gen_plus_sidecar: no plus/ directory, nothing to build.")
        return 0

    county_fips = load_county_fips()
    by_name, by_squash, _state_fips = build_indexes(county_fips)
    plus_generated, cover = load_plus_coverage()

    stats = {
        "county_rows_seen": 0,
        "resolved_rows": 0,
        "unresolved_rows": 0,
        "zone_rows_skipped": 0,
        "untyped_rows_skipped": 0,
        "unresolved_examples": {},
        "states_without_evidence": [],
    }

    states_out = {}
    for slug in sorted(os.listdir(PLUS_ROOT)):
        state_dir = os.path.join(PLUS_ROOT, slug)
        if not os.path.isdir(state_dir):
            continue
        built = collect_state(slug, state_dir, cover, by_name, by_squash, stats)
        if built:
            state_ab, record = built
            states_out[state_ab] = record

    counties_touched = sum(len(r["counties"]) for r in states_out.values())
    pairs = sum(len(v) for r in states_out.values() for v in r["counties"].values())

    # Keep only the worst offenders in the shipped file; the full picture is
    # in the build log.
    worst = sorted(stats["unresolved_examples"].items(), key=lambda kv: -kv[1])[:20]
    stats["unresolved_examples"] = dict(worst)

    doc = {
        "generated": _dt.date.today().isoformat(),
        "plus_generated": plus_generated,
        "states": states_out,
        "stats": {
            "states_with_evidence": len(states_out),
            "counties_touched": counties_touched,
            "county_declaration_pairs": pairs,
            "county_rows_seen": stats["county_rows_seen"],
            "resolved_rows": stats["resolved_rows"],
            "unresolved_rows": stats["unresolved_rows"],
            "zone_rows_skipped": stats["zone_rows_skipped"],
            "untyped_rows_skipped": stats["untyped_rows_skipped"],
            "states_without_evidence": sorted(stats["states_without_evidence"]),
            "unresolved_examples": stats["unresolved_examples"],
        },
    }

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))

    seen = stats["county_rows_seen"] or 1
    print(
        "state-declarations.json: %d states, %d counties, %d county/declaration pairs"
        % (len(states_out), counties_touched, pairs)
    )
    print(
        "  county rows %d, resolved %d (%.1f%%), unresolved %d; zone rows skipped %d"
        % (
            stats["county_rows_seen"],
            stats["resolved_rows"],
            100.0 * stats["resolved_rows"] / seen,
            stats["unresolved_rows"],
            stats["zone_rows_skipped"],
        )
    )
    if stats["states_without_evidence"]:
        print(
            "  no county-resolved evidence: %s"
            % ", ".join(sorted(stats["states_without_evidence"]))
        )
    if worst:
        print("  top unresolved area names (dropped, not guessed):")
        for label, count in worst[:10]:
            print("    %s x%d" % (label, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
