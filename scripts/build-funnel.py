#!/usr/bin/env python3
"""Build the per-state record funnel for DisasterData Plus.

Every state's data passes through several stages, and each stage legitimately
drops records. Because every stage gets called "declarations" in reports, two
true statements about the same state can look like a contradiction. This script
writes one artifact that names every stage explicitly, for all states, so the
counts can never drift apart again.

Stages, in order:

    collected        every row the scraper captured, weather or not
    weather_flagged  collected rows where weather_related is true
    joined           rows in declarations_for_join.csv
    date_resolved    joined rows with a parseable YYYY-MM-DD date_signed
    noaa_matched     distinct declarations appearing in eo_storm_matches.csv

It also records the SHA-256 of each state's eo_storm_join.py, so a stale or
forked copy of the shared classifier shows up in the same table rather than
waiting to be discovered by a crash.

Run from the repository root:

    python3 scripts/build-funnel.py
    python3 scripts/build-funnel.py --fail-on-drift
    python3 scripts/build-funnel.py --states oregon,new-mexico

Outputs plus/funnel.csv and plus/funnel.json, and prints a table.

Standard library only. No pandas, no network.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import glob
import hashlib
import json
import os
import sys

PLUS_DIR = "plus"
MANIFEST_PATH = os.path.join("scripts", "plus", "state-manifest.json")
OUT_CSV = os.path.join(PLUS_DIR, "funnel.csv")
OUT_JSON = os.path.join(PLUS_DIR, "funnel.json")

JOIN_FILE = "declarations_for_join.csv"
MATCH_FILE = "eo_storm_matches.csv"
OVERRIDE_FILE = "hazard_overrides.csv"
REVIEW_FILE = "excluded_and_review_records.csv"
CLASSIFIER_FILE = "eo_storm_join.py"
ACTIONS_GLOB = "*_emergency_actions_all.csv"
SUMMARY_FILE = "state-summary.json"

# A state with a real collected inventory but almost nothing reaching the join
# file is the New Mexico pattern: records are being captured and then lost
# before they can be used. Flagged for review, not treated as an error.
LOW_JOIN_MIN_COLLECTED = 25
LOW_JOIN_RATIO = 0.10

TRUE_VALUES = {"true", "t", "yes", "y", "1"}

COLUMNS = [
    "slug",
    "abbreviation",
    "adapter_status",
    "collected",
    "weather_flagged",
    "joined",
    "date_resolved",
    "noaa_matched",
    "review_records",
    "overrides",
    "join_retention_pct",
    "date_retention_pct",
    "classifier_sha256_short",
    "classifier_matches_reference",
    "flags",
]


def read_csv_rows(path):
    """Return a list of dict rows, or None if the file is absent."""
    if not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha256_of(path):
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_resolved_date(value):
    value = (value or "").strip()
    if not value:
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def load_manifest(path):
    """Return {slug: {...}}. The manifest is optional enrichment only.

    Schema is read defensively: this script never fails because the manifest
    is shaped differently than expected, it simply falls back to scanning the
    plus/ directory.
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}

    entries = []
    if isinstance(raw, dict):
        for key in ("states", "entries", "adapters"):
            if isinstance(raw.get(key), list):
                entries = raw[key]
                break
        else:
            for key, value in raw.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("slug", key)
                    entries.append(item)
    elif isinstance(raw, list):
        entries = raw

    out = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug") or entry.get("state_slug") or entry.get("directory")
        if not slug and entry.get("name"):
            slug = str(entry["name"]).lower().replace(" ", "-")
        if slug:
            out[str(slug)] = entry
    return out


def discover_state_dirs(plus_dir):
    """Every plus/<slug>/ folder that looks like a state adapter."""
    found = []
    if not os.path.isdir(plus_dir):
        return found
    for name in sorted(os.listdir(plus_dir)):
        path = os.path.join(plus_dir, name)
        if not os.path.isdir(path):
            continue
        markers = (JOIN_FILE, SUMMARY_FILE, CLASSIFIER_FILE)
        if any(os.path.isfile(os.path.join(path, marker)) for marker in markers):
            found.append(name)
    return found


def pct(part, whole):
    if not whole:
        return ""
    return round(100.0 * part / whole, 1)


def analyse_state(slug, plus_dir, manifest_entry, reference_hash):
    directory = os.path.join(plus_dir, slug)
    row = {column: "" for column in COLUMNS}
    row["slug"] = slug
    flags = []

    summary = {}
    summary_path = os.path.join(directory, SUMMARY_FILE)
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as handle:
                summary = json.load(handle)
        except (OSError, ValueError):
            flags.append("SUMMARY_UNREADABLE")

    row["abbreviation"] = (
        summary.get("abbreviation")
        or manifest_entry.get("abbreviation")
        or ""
    )
    row["adapter_status"] = (
        summary.get("adapter_status")
        or manifest_entry.get("adapter_status")
        or ""
    )

    # Stage 1: collected.
    action_paths = sorted(glob.glob(os.path.join(directory, ACTIONS_GLOB)))
    if len(action_paths) > 1:
        flags.append("MULTIPLE_ACTION_FILES")
    collected_rows = read_csv_rows(action_paths[0]) if action_paths else None

    if collected_rows is None:
        row["collected"] = ""
        weather_flagged = None
    else:
        row["collected"] = len(collected_rows)
        if collected_rows and "weather_related" not in collected_rows[0]:
            weather_flagged = None
            flags.append("NO_WEATHER_FLAG_COLUMN")
        else:
            weather_flagged = sum(
                1
                for record in collected_rows
                if str(record.get("weather_related", "")).strip().lower() in TRUE_VALUES
            )
        row["weather_flagged"] = "" if weather_flagged is None else weather_flagged

    # Stage 2 and 3: joined, then date resolved.
    join_rows = read_csv_rows(os.path.join(directory, JOIN_FILE))
    if join_rows is None:
        flags.append("NO_JOIN_FILE")
        joined = None
    else:
        joined = len(join_rows)
        row["joined"] = joined
        row["date_resolved"] = sum(
            1 for record in join_rows if is_resolved_date(record.get("date_signed"))
        )
        ids = [str(record.get("declaration_id", "")).strip() for record in join_rows]
        if len(ids) != len(set(ids)):
            flags.append("DUPLICATE_JOIN_IDS")
        if collected_rows is not None:
            collected_ids = {
                str(record.get("declaration_id", "")).strip()
                for record in collected_rows
            }
            orphans = len([i for i in ids if i and i not in collected_ids])
            if orphans:
                flags.append("JOIN_IDS_NOT_IN_COLLECTED=%d" % orphans)

    # Stage 4: NOAA matched.
    match_rows = read_csv_rows(os.path.join(directory, MATCH_FILE))
    if match_rows is not None:
        row["noaa_matched"] = len(
            {
                str(record.get("declaration_id", "")).strip()
                for record in match_rows
                if str(record.get("declaration_id", "")).strip()
            }
        )

    review_rows = read_csv_rows(os.path.join(directory, REVIEW_FILE))
    if review_rows is not None:
        row["review_records"] = len(review_rows)

    override_rows = read_csv_rows(os.path.join(directory, OVERRIDE_FILE))
    if override_rows is not None:
        row["overrides"] = len(override_rows)

    # Reconciliation: the weather flag upstream should agree with the join file.
    if weather_flagged is not None and joined is not None and weather_flagged != joined:
        flags.append("WEATHER_FLAG_VS_JOINED=%d/%d" % (weather_flagged, joined))

    if isinstance(row["collected"], int) and isinstance(joined, int):
        row["join_retention_pct"] = pct(joined, row["collected"])
        if (
            row["collected"] >= LOW_JOIN_MIN_COLLECTED
            and joined < row["collected"] * LOW_JOIN_RATIO
        ):
            flags.append("LOW_JOIN_RATIO")
    if isinstance(joined, int) and isinstance(row["date_resolved"], int):
        row["date_retention_pct"] = pct(row["date_resolved"], joined)

    # Classifier drift lands in the same table as the counts.
    classifier_hash = sha256_of(os.path.join(directory, CLASSIFIER_FILE))
    if classifier_hash is None:
        row["classifier_sha256_short"] = ""
        row["classifier_matches_reference"] = "missing"
        if row["adapter_status"] == "implemented":
            flags.append("CLASSIFIER_MISSING")
    else:
        row["classifier_sha256_short"] = classifier_hash[:12]
        if reference_hash:
            matches = classifier_hash == reference_hash
            row["classifier_matches_reference"] = "yes" if matches else "no"
            if not matches:
                flags.append("CLASSIFIER_DRIFT")
        else:
            row["classifier_matches_reference"] = "unchecked"

    row["flags"] = ";".join(flags)
    return row


def resolve_reference_hash(args, rows_dirs, plus_dir):
    """Reference hash comes from an explicit value, an explicit file, or the
    modal hash across all states. The modal fallback is reported plainly so it
    is never mistaken for an authoritative reference."""
    if args.reference_hash:
        return args.reference_hash.strip().lower(), "supplied value"
    if args.reference_file:
        if not os.path.isfile(args.reference_file):
            sys.stderr.write(
                "ERROR: reference file not found: %s\n" % args.reference_file
            )
            sys.exit(2)
        if os.path.getsize(args.reference_file) == 0:
            sys.stderr.write(
                "ERROR: reference file is empty: %s\n" % args.reference_file
            )
            sys.exit(2)
        return sha256_of(args.reference_file), "file %s" % args.reference_file

    counts = {}
    for slug in rows_dirs:
        digest = sha256_of(os.path.join(plus_dir, slug, CLASSIFIER_FILE))
        if digest:
            counts[digest] = counts.get(digest, 0) + 1
    if not counts:
        return None, "none available"
    total = sum(counts.values())
    best = max(counts.items(), key=lambda item: item[1])
    source = "most common across %d states (%d of them)" % (total, best[1])
    if best[1] * 2 <= total:
        # Without a clear majority the inferred reference is a coin flip, and a
        # wrong reference inverts every drift result. Say so loudly rather than
        # reporting confident-looking drift built on a guess.
        sys.stderr.write(
            "WARNING: no clear majority classifier hash (%d of %d states). "
            "The inferred reference may be wrong, which would invert every "
            "drift result. Pass --reference-file or --reference-hash.\n"
            % (best[1], total)
        )
        source += " [NO MAJORITY, inferred reference is unreliable]"
    return best[0], source


def print_table(rows):
    headers = [
        ("slug", 16),
        ("st", 3),
        ("collected", 9),
        ("wx_flag", 8),
        ("joined", 7),
        ("dated", 6),
        ("matched", 8),
        ("join%", 6),
        ("clf", 5),
    ]
    line = "  ".join(name.ljust(width) for name, width in headers)
    print(line)
    print("-" * len(line))
    for row in rows:
        cells = [
            str(row["slug"])[:16].ljust(16),
            str(row["abbreviation"])[:3].ljust(3),
            str(row["collected"]).rjust(9),
            str(row["weather_flagged"]).rjust(8),
            str(row["joined"]).rjust(7),
            str(row["date_resolved"]).rjust(6),
            str(row["noaa_matched"]).rjust(8),
            str(row["join_retention_pct"]).rjust(6),
            str(row["classifier_matches_reference"])[:5].ljust(5),
        ]
        print("  ".join(cells))
        if row["flags"]:
            print(" " * 4 + "! " + row["flags"])


def main():
    parser = argparse.ArgumentParser(
        description="Build the per-state record funnel for DisasterData Plus."
    )
    parser.add_argument(
        "--plus-dir", default=PLUS_DIR, help="path to the plus/ directory"
    )
    parser.add_argument(
        "--manifest", default=MANIFEST_PATH, help="path to state-manifest.json"
    )
    parser.add_argument(
        "--states", default="", help="comma separated slugs, default is all"
    )
    parser.add_argument(
        "--reference-hash", default="", help="expected eo_storm_join.py SHA-256"
    )
    parser.add_argument(
        "--reference-file", default="", help="file to hash as the reference"
    )
    parser.add_argument("--out-csv", default=OUT_CSV)
    parser.add_argument("--out-json", default=OUT_JSON)
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 if any state shows classifier drift or a reconciliation flag",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the table")
    args = parser.parse_args()

    plus_dir = args.plus_dir
    if not os.path.isdir(plus_dir):
        sys.stderr.write("ERROR: no such directory: %s\n" % plus_dir)
        return 2

    manifest = load_manifest(args.manifest)
    slugs = discover_state_dirs(plus_dir)
    for slug in manifest:
        if slug not in slugs and os.path.isdir(os.path.join(plus_dir, slug)):
            slugs.append(slug)
    slugs = sorted(set(slugs))

    if args.states:
        wanted = {s.strip() for s in args.states.split(",") if s.strip()}
        missing = wanted - set(slugs)
        if missing:
            sys.stderr.write(
                "ERROR: unknown state slug(s): %s\n" % ", ".join(sorted(missing))
            )
            return 2
        slugs = [s for s in slugs if s in wanted]

    if not slugs:
        sys.stderr.write("ERROR: no state folders found under %s\n" % plus_dir)
        return 2

    reference_hash, reference_source = resolve_reference_hash(args, slugs, plus_dir)

    rows = [
        analyse_state(slug, plus_dir, manifest.get(slug, {}), reference_hash)
        for slug in slugs
    ]

    generated_on = datetime.date.today().isoformat()

    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)
    with open(args.out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    payload = {
        "schema_version": 1,
        "generated_on": generated_on,
        "reference_classifier_sha256": reference_hash or "",
        "reference_source": reference_source,
        "stage_definitions": {
            "collected": "rows captured by the scraper, weather related or not",
            "weather_flagged": "collected rows marked weather_related",
            "joined": "rows in declarations_for_join.csv",
            "date_resolved": "joined rows with a parseable YYYY-MM-DD date_signed",
            "noaa_matched": "distinct declarations present in eo_storm_matches.csv",
        },
        "states": rows,
    }
    with open(args.out_json, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    flagged = [row for row in rows if row["flags"]]
    drifted = [row for row in rows if row["classifier_matches_reference"] == "no"]

    if not args.quiet:
        print("Reference classifier hash: %s" % (reference_hash or "none"))
        print("Reference source: %s" % reference_source)
        print("States analysed: %d" % len(rows))
        print("")
        print_table(rows)
        print("")
        print("Wrote %s and %s" % (args.out_csv, args.out_json))
        print(
            "States with flags: %d  |  classifier drift: %d"
            % (len(flagged), len(drifted))
        )

    if args.fail_on_drift and flagged:
        sys.stderr.write(
            "FAIL: %d state(s) carry a funnel or classifier flag.\n" % len(flagged)
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
