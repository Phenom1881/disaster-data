#!/usr/bin/env python3
"""Build DisasterData Plus coverage pages for one or more states.

This builder is deliberately safe to run nationally. It creates a page for
every selected state, reads any state pipeline outputs already present under
``plus/<state-slug>/``, and labels incomplete coverage honestly. It does not
pretend that a missing state adapter means the state has no emergencies.

Three layers are shown per state, kept visually and structurally distinct:
  1. Federal FEMA declarations, read from data/decl-index/<ABBR>.json
  2. State-issued emergency actions, read from the state's own action CSV
  3. NOAA/NWS Storm Events evidence, read from the state's eo_storm_join.py
     output (individual matched events, not just counts)

A combined event crosswalk then joins state actions to their NOAA matches and,
where one exists within the matching window, a federal declaration. When no
federal declaration falls in that window the crosswalk says so explicitly
("No corresponding federal declaration found") rather than leaving a blank
cell, since silence would be read as "not checked" rather than "checked, none
found."

The crosswalk here is an automated proximity match on date and state, exactly
like eo_storm_join.py's own NOAA matching. It is not the same thing as an
accepted, human-reviewed link, and the page says so. If a stricter
reviewed-only crosswalk is wanted later, gate this section on an accepted
review file the way the original state-evidence design proposed, rather than
publishing every automated candidate as-is.

Examples (run from the repository root):

    python scripts/build-plus.py --states all
    python scripts/build-plus.py --states VA,NY,NJ,PA
    python scripts/build-plus.py --states VA --collect --join-storms

An optional state adapter lives in the corresponding state directory and must
expose ``collect(workdir, scripts_dir) -> (csv_path, coverage_note)``. Virginia's
existing ``plus/virginia/virginia.py`` already follows that contract.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import html
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = SCRIPT_DIR / "plus" / "state-manifest.json"

# How far a state action's signing date may sit from a federal declaration's
# incident window and still be offered as a candidate match. Wider than
# eo_storm_join.py's own NOAA window (3 days) because a federal declaration
# is often filed weeks after the state emergency that preceded it.
FEDERAL_MATCH_WINDOW_DAYS = 21

# NOAA publishes Storm Events months after the fact, so a declaration signed
# after the newest published record cannot have a match yet. Showing those
# as "0 matches" reads as "no storm happened". The newest event date any
# state has matched stands in for how far NOAA's data runs; it is set once
# per run by noaa_data_through() and is "" when nothing has matched yet.
NOAA_DATA_THROUGH = ""


def noaa_data_through(repo_root: Path) -> str:
    """The latest NOAA event date (YYYY-MM-DD) found in any state's
    eo_storm_matches.csv, or "" when there are none."""
    latest = ""
    for path in sorted((repo_root / "plus").glob("*/eo_storm_matches.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    value = (row.get("BEGIN_DATE_TIME") or "")[:10]
                    if len(value) == 10 and value > latest:
                        latest = value
        except (OSError, csv.Error):
            continue
    return latest


def noaa_status(match_count: int, date_signed: str, through: str) -> str:
    """matched, pending (signed after NOAA's published data ends), or none."""
    if match_count:
        return "matched"
    if through and (date_signed or "")[:10] > through:
        return "pending"
    return "none"


def load_manifest(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    states = payload.get("states", [])
    if len(states) != 50:
        raise ValueError(f"Expected 50 states in {path}; found {len(states)}")
    required = {"abbreviation", "name", "slug", "adapter_status"}
    seen = set()
    for state in states:
        missing = required.difference(state)
        if missing:
            raise ValueError(
                f"Manifest entry is missing {', '.join(sorted(missing))}: {state}"
            )
        abbreviation = state["abbreviation"].upper()
        if abbreviation in seen:
            raise ValueError(f"Duplicate state abbreviation in manifest: {abbreviation}")
        seen.add(abbreviation)
    return states


def select_states(states: list[dict], requested: str) -> list[dict]:
    if requested.strip().lower() == "all":
        return states
    lookup = {}
    for state in states:
        lookup[state["abbreviation"].upper()] = state
        lookup[state["name"].lower()] = state
        lookup[state["slug"].lower()] = state
    selected = []
    unknown = []
    for token in requested.split(","):
        key = token.strip()
        if not key:
            continue
        state = lookup.get(key.upper()) or lookup.get(key.lower())
        if state is None:
            unknown.append(key)
        elif state not in selected:
            selected.append(state)
    if unknown:
        raise ValueError("Unknown state selection: " + ", ".join(unknown))
    if not selected:
        raise ValueError("No states selected")
    return selected


def import_adapter(path: Path):
    module_name = "disasterdata_plus_adapter_" + path.parent.name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "collect"):
        raise RuntimeError(f"Adapter does not expose collect(): {path}")
    return module


def candidate_action_files(state: dict) -> list[str]:
    configured = state.get("action_files", [])
    defaults = [
        "declarations_for_join_2002_present.csv",
        "declarations_for_join.csv",
        f"{state['abbreviation'].lower()}_weather_emergency_actions_2002_2026.csv",
        f"{state['abbreviation'].lower()}_weather_emergency_actions.csv",
        "state_actions.csv",
    ]
    return list(dict.fromkeys(configured + defaults))


def locate_first(state_dir: Path, names: list[str]) -> Path | None:
    for name in names:
        path = state_dir / name
        if path.exists() and path.is_file():
            return path
    return None


def read_csv_rows(path: Path | None) -> list[dict]:
    if path is None:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(value) -> str:
    return str(value or "").strip()


def normalized_action(row: dict, abbreviation: str) -> dict:
    action_number = clean(
        row.get("action_number")
        or row.get("eo_number")
        or row.get("order_number")
        or row.get("proclamation_number")
    )
    signed = clean(
        row.get("date_signed")
        or row.get("issued_date")
        or row.get("date")
    )
    title = clean(
        row.get("event_description")
        or row.get("title")
        or row.get("subject")
        or row.get("short_title")
    )
    source_url = clean(
        row.get("archive_record_url")
        or row.get("source_url")
        or row.get("detail_url")
        or row.get("document_url")
    )
    declaration_id = clean(row.get("declaration_id"))
    if not declaration_id:
        declaration_id = "-".join(
            part for part in [abbreviation, action_number, signed] if part
        )
    return {
        "state": abbreviation,
        "declaration_id": declaration_id,
        "action_number": action_number,
        "title": title,
        "date_signed": signed,
        "action_type": clean(row.get("action_type") or "declaration"),
        "governor": clean(row.get("governor")),
        "source_url": source_url,
    }


# State declarations signed before this year are left off the site. A few
# state archives reach further back (Massachusetts 1941, Nebraska 1965, South
# Carolina 1966), but the federal record and the NOAA storm data the join
# relies on are thin before 1970, so those older orders are dropped rather
# than shown without evidence. A row with no readable signing date is kept:
# it is waiting on a date, not known to be old.
EARLIEST_ACTION_YEAR = 1970


def signed_year(row: dict) -> int | None:
    """The year a state action was signed, or None when no date is readable.
    Reads the same fields normalized_action() does, in ISO (2026-01-07) or
    compact (20260107) form."""
    value = clean(row.get("date_signed") or row.get("issued_date") or row.get("date"))
    match = re.match(r"(\d{4})", value)
    return int(match.group(1)) if match else None


def before_cutoff(row: dict) -> bool:
    year = signed_year(row)
    return year is not None and year < EARLIEST_ACTION_YEAR


def drop_pre_cutoff_actions(state: dict, state_dir: Path) -> int:
    """Remove pre-1970 rows from the files the storm join and the pages read.
    Runs after keep_saved_actions(), so a saved copy cannot bring them back.
    That covers any raw archive a state lists in action_files (Massachusetts,
    New Jersey and South Carolina do); other raw archives are left whole."""
    dropped = 0
    for name in candidate_action_files(state):
        path = state_dir / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        fields, rows = _csv_rows_from_bytes(raw)
        keep = [row for row in rows if not before_cutoff(row)]
        if len(keep) == len(rows):
            continue
        newline = "\r\n" if b"\r\n" in raw[:4096] else "\n"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, restval="",
                                    extrasaction="ignore", lineterminator=newline)
            writer.writeheader()
            writer.writerows(keep)
        dropped += len(rows) - len(keep)
        print(f"{state['abbreviation']}: {name}: left off {len(rows) - len(keep)} "
              f"declaration(s) signed before {EARLIEST_ACTION_YEAR}")
    return dropped


# A second source for thin states (see scripts/plus_fmcsa.py): FMCSA's copies
# of state emergency declarations, written per state by write_fmcsa_supplement()
# for states marked "fmcsa_supplement" in the manifest. Kept in its own file
# so the state's own source is still judged on its own; shown on the page and
# joined to storms together with it.
FMCSA_SUPPLEMENT = "fmcsa_declarations.csv"
_fmcsa_module = None


def fmcsa():
    global _fmcsa_module
    if _fmcsa_module is None:
        spec = importlib.util.spec_from_file_location(
            "plus_fmcsa", str(Path(__file__).resolve().parent / "plus_fmcsa.py"))
        _fmcsa_module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("plus_fmcsa", _fmcsa_module)
        spec.loader.exec_module(_fmcsa_module)
    return _fmcsa_module


def write_fmcsa_supplement(state: dict, state_dir: Path, repo_root: Path) -> int:
    """Write this state's FMCSA declarations that its own source lacks.
    Returns how many. Removes the file for states not marked for it."""
    target = state_dir / FMCSA_SUPPLEMENT
    if not state.get("fmcsa_supplement"):
        target.unlink(missing_ok=True)
        return 0
    module = fmcsa()
    entries = module.load_entries(repo_root / "plus" / "_fmcsa" / "entries.csv")
    if not entries:
        return count_rows(target if target.exists() else None)
    own = read_csv_rows(locate_first(state_dir, candidate_action_files(state)))
    rows = module.supplement_rows(state, own, entries)
    module.write_csv(target, module.JOIN_FIELDS, rows)
    return len(rows)


def load_state_actions(state: dict, state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(state_dir, candidate_action_files(state))
    supplement = state_dir / FMCSA_SUPPLEMENT
    raw = read_csv_rows(path) + (read_csv_rows(supplement) if supplement.exists() else [])
    rows = [normalized_action(row, state["abbreviation"]) for row in raw
            if not before_cutoff(row)]
    unique = {}
    for row in rows:
        key = row["declaration_id"] or json.dumps(row, sort_keys=True)
        unique[key] = row
    actions = sorted(
        unique.values(), key=lambda row: row.get("date_signed", ""), reverse=True
    )
    return actions, path


def ensure_declaration_id_column(action_path: Path, abbreviation: str) -> Path:
    """Guarantee the CSV handed to eo_storm_join.py has an explicit
    declaration_id column, computed with the exact same formula
    normalized_action() uses above.

    Without this, a state whose source CSV has no declaration_id column ends
    up with TWO independently-synthesized ids: this file's own
    normalized_action() produces one shape (state-prefixed, e.g.
    "NJ-EO-5-2026-03-10"), while eo_storm_join.py's own internal fallback
    (declarations['eo_number'] + '-' + declarations['date_signed'], with no
    state prefix) produces a different one ("EO-5-2026-03-10"). Those never
    match, so build_crosswalk()'s lookup by declaration_id silently finds
    zero NOAA matches for every action in that state, even when
    eo_storm_join.py genuinely found real ones. Virginia is unaffected today
    only because its own CSV already supplies a real declaration_id column;
    this only matters once a state adapter's output does not.

    Writes a sibling file rather than mutating the original, and returns the
    original path unchanged if a declaration_id column is already present.
    """
    rows = read_csv_rows(action_path)
    if not rows or "declaration_id" in rows[0]:
        return action_path
    for row in rows:
        row["declaration_id"] = normalized_action(row, abbreviation)["declaration_id"]
    enriched_path = action_path.with_name(action_path.stem + "_with_id.csv")
    with enriched_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return enriched_path


def with_fmcsa_supplement(action_path: Path, state_dir: Path) -> Path:
    """The file handed to the storm join: the state's own declarations plus
    its FMCSA supplement, when it has one. Written to a temporary folder so
    it is never committed."""
    supplement = state_dir / FMCSA_SUPPLEMENT
    extra = read_csv_rows(supplement) if supplement.exists() else []
    if not extra:
        return action_path
    rows = read_csv_rows(action_path) + extra
    fields = list(dict.fromkeys(name for row in rows for name in row if name))
    folder = Path(tempfile.mkdtemp(prefix="plus_join_"))
    atexit.register(shutil.rmtree, folder, True)
    combined = folder / f"{state_dir.name}_declarations_with_fmcsa.csv"
    with combined.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return combined


def count_rows(path: Path | None) -> int:
    return len(read_csv_rows(path)) if path else 0


# ---------------------------------------------------------------- keep saved records
# A state's action CSV is the record of what its governor declared, and those
# declarations do not stop having happened. But each adapter rewrites its CSV
# from scratch on every --collect run, so a run where the state's site was
# unreachable, blocked the runner, or changed its layout used to replace a
# good file with an empty or shorter one, and the workflow then committed it.
# That silently erased every saved record for Kansas, Kentucky, Montana, New
# Hampshire, North Dakota, and Ohio on 2026-09-12 and for Texas on
# 2026-09-17, and dropped some of Indiana's and Oklahoma's.
#
# So the builder now snapshots every candidate action file before an adapter
# runs and, afterwards, merges the snapshot back in:
#   - a saved row the new scrape did not return is kept (carried forward);
#   - a field the new scrape left blank keeps its saved value (for example a
#     signing date that needed OCR the runner does not have);
#   - a text field the new scrape filled with page markup (a parser picking
#     up HTML attributes instead of the title) keeps its saved clean value.
# Rows are matched on declaration_id only. Order numbers repeat across
# governors (NJ-MURPHY-EO-15 and NJ-SHERRILL-EO-15 are different orders), so
# matching on the number alone would wrongly treat one as the other.
#
# To remove a record on purpose, delete its row from the committed CSV: the
# snapshot is taken from the file as committed, so a deleted row is not
# brought back unless the state's own source still lists it.

_TEXT_FIELDS = ("event_description", "title", "subject", "short_title")
_MARKUP_RE = re.compile(
    r"<\s*[A-Za-z/!]"                                # an HTML tag
    r"|\b(?:class|id|href|style|src)\s*=\s*[\"']"    # an HTML attribute
    r"|&#\d+;|&quot;|&lt;|&gt;"                      # escaped markup
    r"|\}\}"                                         # template or JSON residue
)


def looks_like_markup(value) -> bool:
    return bool(_MARKUP_RE.search(str(value or "")))


# Some action files carry an order's full text in a single field (Wyoming's
# does), which is larger than the csv module's default 128 KB field limit.
# Without this the merge below failed on that file and, by design, put the
# saved copy back, which also threw away whatever that run had just scraped.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _csv_rows_from_bytes(raw: bytes) -> tuple[list[str], list[dict]]:
    text = raw.decode("utf-8-sig", errors="replace")
    # Split rows the way csv expects (newline=""), on line breaks only. The
    # earlier str.splitlines() also split on form feeds and other separators
    # that PDF text often carries, which broke such a row in two.
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def protected_action_files(state: dict, state_dir: Path) -> list[str]:
    """Every file the safeguard covers: the candidate action files, plus any
    raw archive or order-relationship file an adapter keeps beside them
    (sd_emergency_actions_all.csv, nh_order_relationships.csv and the like).
    Those used to be left out because they are not listed in action_files,
    so on 2026-09-25 New Hampshire's 307 relationship rows were wiped, and on
    2026-09-26 an empty South Dakota scrape wiped its 102-order archive, even
    though declarations_for_join.csv was kept both times."""
    names = list(candidate_action_files(state))
    for pattern in ("*emergency_actions*.csv", "*order_relationships*.csv"):
        for path in sorted(state_dir.glob(pattern)):
            if path.name not in names:
                names.append(path.name)
    return names


def snapshot_action_files(state: dict, state_dir: Path) -> dict[Path, bytes]:
    """The exact bytes of every protected action file that exists right now."""
    saved = {}
    for name in protected_action_files(state, state_dir):
        path = state_dir / name
        if path.is_file():
            saved[path] = path.read_bytes()
    return saved


def _merge_saved_rows(path: Path, raw_old: bytes, abbreviation: str) -> dict:
    old_fields, old_rows = _csv_rows_from_bytes(raw_old)
    counts = {"kept": 0, "filled": 0, "cleaned": 0}
    if not old_rows:
        return counts
    if path.is_file():
        raw_new = path.read_bytes()
        new_fields, new_rows = _csv_rows_from_bytes(raw_new)
        newline = "\r\n" if b"\r\n" in raw_new[:4096] else "\n"
    else:
        new_fields, new_rows = [], []
        newline = "\r\n" if b"\r\n" in raw_old[:4096] else "\n"

    fields = list(new_fields) or list(old_fields)
    for name in old_fields:
        if name and name not in fields:
            fields.append(name)

    def key(row):
        k = clean(row.get("declaration_id")) or normalized_action(row, abbreviation)["declaration_id"]
        if k and k != abbreviation:
            return k
        # A file with no id, number or date to tell its rows apart (Ohio's
        # bulletin list) would give every row the bare state code, and the
        # whole file would collapse into one row. Use the row's link instead,
        # or failing that its whole content.
        # Raw archives name the link column "url" or "pdf_url" (Kansas and
        # Oklahoma have no order number to match on), so check those too.
        link = (normalized_action(row, abbreviation)["source_url"]
                or clean(row.get("url")) or clean(row.get("pdf_url")))
        if link:
            return "url:" + link
        return "row:" + json.dumps({n: clean(v) for n, v in row.items() if n}, sort_keys=True)

    # Rows are paired in order within a key, so a file that lists one id
    # twice (Virginia's and Wisconsin's audit files do) keeps both.
    current = {}
    for row in new_rows:
        current.setdefault(key(row), []).append(row)

    changed = False
    seen = {}
    for old in old_rows:
        k = key(old)
        if not k:
            continue
        nth = seen.get(k, 0)
        seen[k] = nth + 1
        matches = current.get(k, [])
        row = matches[nth] if nth < len(matches) else None
        if row is None:
            new_rows.append(dict(old))
            counts["kept"] += 1
            changed = True
            continue
        filled = cleaned = False
        for name, old_value in old.items():
            if not name or not clean(old_value):
                continue
            if not clean(row.get(name)):
                row[name] = old_value
                filled = True
            elif (name in _TEXT_FIELDS and looks_like_markup(row.get(name))
                  and not looks_like_markup(old_value)):
                row[name] = old_value
                cleaned = True
        counts["filled"] += int(filled)
        counts["cleaned"] += int(cleaned)
        changed = changed or filled or cleaned

    if changed or not path.is_file():
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, restval="",
                                    extrasaction="ignore", lineterminator=newline)
            writer.writeheader()
            writer.writerows(new_rows)
    return counts


def keep_saved_actions(state: dict, saved: dict[Path, bytes]) -> dict:
    """Merge the pre-collection snapshot back into each action file (see the
    notes above). If a merge itself fails, the saved file is put back exactly
    as it was, so a bug here can never cost data either. Returns totals for
    the file the page is built from."""
    abbreviation = state["abbreviation"]
    primary = None
    for name in candidate_action_files(state):
        if name in {p.name for p in saved}:
            primary = name
            break
    totals = {"kept": 0, "filled": 0, "cleaned": 0}
    for path, raw_old in saved.items():
        try:
            counts = _merge_saved_rows(path, raw_old, abbreviation)
        except Exception as exc:
            path.write_bytes(raw_old)
            print(f"WARNING {abbreviation}: could not merge saved records into {path.name} "
                  f"({exc}); restored the saved file unchanged", file=sys.stderr)
            continue
        if any(counts.values()):
            print(f"{abbreviation}: {path.name}: kept {counts['kept']} saved record(s) this "
                  f"run's scrape did not return, kept saved values for {counts['filled']} "
                  f"blank and {counts['cleaned']} garbled field set(s)")
        if path.name == primary:
            totals = counts
    return totals


# ---------------------------------------------------------------- source result
# What each state's source actually returned on this run, recorded in
# state-summary.json for the health check (scripts/plus_health.py).
#
# The keep-saved merge above protects the data, but it also hides failures:
# the page shows the saved records either way. New Hampshire's registry
# answered 503 on every run from 2026-09-25 on and its page still looked
# normal. So the rows the adapter itself wrote are counted before the merge,
# and every state gets one of these:
SOURCE_OK = "ok"                    # returned every record already saved, or more
SOURCE_PARTIAL = "partial"          # returned some records; saved ones it missed were kept
SOURCE_EMPTY = "empty"              # returned nothing although records were saved
SOURCE_FAILED = "failed"            # the adapter raised or is missing
SOURCE_NOT_COLLECTED = "not_collected"  # this run did not collect (no --collect)
SOURCE_BAD = (SOURCE_EMPTY, SOURCE_FAILED)


def adapter_path_for(state: dict, state_dir: Path) -> Path:
    name = state.get("adapter_file") or (
        state["name"].lower().replace(" ", "_").replace("-", "_") + ".py"
    )
    return state_dir / name


def primary_action_name(state: dict, state_dir: Path, saved: dict[Path, bytes]) -> str | None:
    """The file the page is built from, chosen the way keep_saved_actions()
    chooses it: the first candidate that was saved, else the first that
    exists now."""
    saved_names = {path.name for path in saved}
    for name in candidate_action_files(state):
        if name in saved_names:
            return name
    for name in candidate_action_files(state):
        if (state_dir / name).is_file():
            return name
    return None


def source_status(error: str, saved_rows: int, scraped_rows: int, kept: int) -> str:
    if error:
        return SOURCE_FAILED
    if saved_rows > 0 and scraped_rows == 0:
        return SOURCE_EMPTY
    if kept > 0:
        return SOURCE_PARTIAL
    return SOURCE_OK


def collect_with_safeguard(state: dict, state_dir: Path) -> dict:
    """Run one state's adapter inside the keep-saved safeguard and report
    what its source returned. Snapshot first, merge back after, even when
    the adapter raises partway through a write (see keep_saved_actions())."""
    started = time.monotonic()
    adapter_path = adapter_path_for(state, state_dir)
    if not adapter_path.exists():
        return {"note": "", "error": "No state-source adapter is installed",
                "kept": {"kept": 0, "filled": 0, "cleaned": 0},
                "saved_rows": 0, "scraped_rows": 0, "status": SOURCE_FAILED, "seconds": 0.0}
    saved = snapshot_action_files(state, state_dir)
    primary = primary_action_name(state, state_dir, saved)
    saved_rows = 0
    if primary and (state_dir / primary) in saved:
        saved_rows = len(_csv_rows_from_bytes(saved[state_dir / primary])[1])
    note, error, scraped_rows = "", "", 0
    kept = {"kept": 0, "filled": 0, "cleaned": 0}
    try:
        adapter = import_adapter(adapter_path)
        _, note = adapter.collect(workdir=state_dir, scripts_dir=state_dir)
    except (Exception, SystemExit) as exc:
        # SystemExit too: an adapter that calls sys.exit() must fail its own
        # state, not end the whole build.
        reason = (f"adapter exited with code {exc.code}" if isinstance(exc, SystemExit)
                  else str(exc))
        error = f"Collection failed: {reason}"
        print(f"WARNING {state['abbreviation']}: {error}", file=sys.stderr)
    finally:
        name = primary or primary_action_name(state, state_dir, {})
        path = state_dir / name if name else None
        try:
            if path and path.is_file():
                scraped_rows = len(_csv_rows_from_bytes(path.read_bytes())[1])
        except Exception:
            scraped_rows = 0
        kept = keep_saved_actions(state, saved)
        drop_pre_cutoff_actions(state, state_dir)
    status = source_status(error, saved_rows, scraped_rows, kept["kept"])
    return {"note": note or "", "error": error, "kept": kept, "saved_rows": saved_rows,
            "scraped_rows": scraped_rows, "status": status,
            "seconds": round(time.monotonic() - started, 1)}


def load_federal_declarations(repo_root: Path, abbreviation: str) -> list[dict]:
    path = repo_root / "data" / "decl-index" / f"{abbreviation.upper()}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    records = payload if isinstance(payload, list) else payload.get("declarations", [])
    return sorted(records, key=lambda row: row.get("date", "") or row.get("begin", ""), reverse=True)


def parse_iso_date(value) -> date | None:
    text = clean(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_storm_match_rows(state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(
        state_dir,
        [
            "eo_storm_matches_2002_present_filtered.csv",
            "eo_storm_matches.csv",
            "matches.csv",
        ],
    )
    return read_csv_rows(path), path


def load_severity_rows(state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(
        state_dir,
        [
            "eo_storm_severity_2002_present_filtered.csv",
            "eo_storm_severity_summary.csv",
            "severity_resolved.csv",
        ],
    )
    return read_csv_rows(path), path


def group_by_declaration(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = clean(row.get("declaration_id"))
        if not key:
            continue
        grouped.setdefault(key, []).append(row)
    return grouped


def state_metrics(
    state: dict,
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows: list[dict],
    severity_rows: list[dict],
) -> dict:
    return {
        "action_count": len(actions),
        "federal_declaration_count": len(federal_declarations),
        "storm_match_rows": len(storm_rows),
        "severity_rows": len(severity_rows),
    }


def find_federal_match(action: dict, federal_declarations: list[dict]) -> dict | None:
    signed = parse_iso_date(action.get("date_signed"))
    if signed is None or not federal_declarations:
        return None
    window = timedelta(days=FEDERAL_MATCH_WINDOW_DAYS)
    best = None
    best_gap = None
    for declaration in federal_declarations:
        begin = parse_iso_date(declaration.get("begin")) or parse_iso_date(declaration.get("date"))
        end = parse_iso_date(declaration.get("end")) or begin
        if begin is None:
            continue
        if begin - window <= signed <= end + window:
            gap = min(abs((signed - begin).days), abs((signed - end).days))
            if best_gap is None or gap < best_gap:
                best, best_gap = declaration, gap
    return best


def build_crosswalk(
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows_by_declaration: dict[str, list[dict]],
) -> list[dict]:
    rows = []
    for action in actions:
        matches = storm_rows_by_declaration.get(action["declaration_id"], [])
        areas = sorted({clean(row.get("CZ_NAME")) for row in matches if clean(row.get("CZ_NAME"))})
        federal = find_federal_match(action, federal_declarations)
        rows.append(
            {
                "action": action,
                "noaa_match_count": len(matches),
                "noaa_status": noaa_status(len(matches), action.get("date_signed", ""),
                                           NOAA_DATA_THROUGH),
                "noaa_areas": areas,
                "federal_declaration": federal,
                "federal_status": (
                    "matched" if federal is not None else "no_federal_declaration_found"
                ),
            }
        )
    return rows


def _promote_outputs(pairs: list[tuple[Path, Path]]) -> tuple[bool, str]:
    """Move each (tmp_path, final_path) into place, with rollback if any
    individual move fails partway through the set.

    Each single tmp -> final move is atomic (Path.replace()), but the set of
    moves together is not one atomic transaction - if a later move in the
    list raises after an earlier one already succeeded, the final files
    could briefly disagree with each other (e.g. a new eo_storm_matches.csv
    paired with an old severity_resolved.csv). To bound that risk, every
    final file that currently exists is first backed up to a sibling .bak
    path; if any replace() call raises, everything already promoted this
    call is reverted and every backup is restored, so the on-disk state
    returns to exactly what it was before this call rather than being left
    half-updated. Returns (True, "") on full success, or (False, message)
    after a full rollback.
    """
    backups: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for _, final_path in pairs:
            if final_path.exists():
                backup_path = final_path.with_name(final_path.name + ".bak")
                final_path.replace(backup_path)
                backups.append((backup_path, final_path))
        for tmp_path, final_path in pairs:
            tmp_path.replace(final_path)
            promoted.append(final_path)
    except OSError as exc:
        for final_path in promoted:
            final_path.unlink(missing_ok=True)
        for backup_path, original_path in backups:
            if backup_path.exists():
                backup_path.replace(original_path)
        for tmp_path, _ in pairs:
            tmp_path.unlink(missing_ok=True)
        return (
            False,
            "Storm join succeeded but promoting its output files failed "
            f"partway through ({exc}); previous outputs were restored",
        )
    for backup_path, _ in backups:
        backup_path.unlink(missing_ok=True)
    return (True, "")


def run_storm_pipeline(state: dict, state_dir: Path, action_path: Path) -> tuple[str, bool, bool]:
    """Returns (note, failed, ran). A state marked 'implemented' is expected
    to have eo_storm_join.py, so its absence there means something broke and
    fails the build. For a state still mid-rollout the same absence is an
    expected skip. ran is True only when a join actually executed and
    succeeded, so a skipped state is never read as having fresh output."""
    join_script = state_dir / "eo_storm_join.py"
    if not join_script.exists():
        if state.get("adapter_status") == "implemented":
            return ("Storm join failed: eo_storm_join.py is missing from the state folder", True, False)
        return ("Storm join skipped: eo_storm_join.py is not installed in the state folder", False, False)
    note, failed = _run_storm_join(state, state_dir, action_path)
    return note, failed, not failed


def preflight_overrides(states: list[dict], repo_root: Path) -> list[str]:
    """Check every selected state's reviewed hazard overrides before anything
    is collected, and return one message per problem.

    A malformed override fails that state's storm join, and a failed storm
    join fails the whole build. That check used to happen state by state
    after collection, so one bad cell (a blank hazard_category_override in
    plus/ohio/hazard_overrides.csv, 2026-10-07) failed the run 44 minutes in
    and nothing was committed. The same loader the join uses runs here, in
    seconds, before the first state is collected."""
    problems = []
    for state in states:
        state_dir = repo_root / "plus" / state["slug"]
        join_script = state_dir / "eo_storm_join.py"
        if not join_script.is_file():
            continue
        name = "disasterdata_plus_join_" + state["slug"].replace("-", "_")
        try:
            spec = importlib.util.spec_from_file_location(name, join_script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            problems.append(f"{state['abbreviation']}: eo_storm_join.py does not load ({exc})")
            continue
        overrides = state_dir / "hazard_overrides.csv"
        if overrides.is_file():
            try:
                module.load_overrides(str(overrides))
            except Exception as exc:
                problems.append(f"{state['abbreviation']}: {overrides.relative_to(repo_root)}: {exc}")
        # Inline overrides in the declarations file itself.
        for file_name in candidate_action_files(state):
            path = state_dir / file_name
            if not path.is_file():
                continue
            try:
                with path.open(newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        value = (row.get("hazard_category_override") or "").strip()
                        if value:
                            module.resolve_override(value)
            except Exception as exc:
                problems.append(f"{state['abbreviation']}: {path.relative_to(repo_root)}: {exc}")
            break
    return problems


def _run_storm_join(state: dict, state_dir: Path, action_path: Path) -> tuple[str, bool]:
    """Run eo_storm_join.py for one state, applying its reviewed sidecar
    overrides automatically when present.

    Returns (note, failed). failed is True whenever the join itself, the
    zone-resolution step, or the final file-promotion step fails - a
    malformed hazard_category_override (inline or in hazard_overrides.csv)
    must not be allowed to leave an automated build looking successful, so
    main() propagates this into the process exit code unconditionally, not
    only under --strict.

    eo_storm_join.py and resolve_zones_to_counties.py write to *.tmp paths
    here, never directly to eo_storm_matches.csv / eo_storm_severity_summary.csv
    / severity_resolved.csv. Those real paths are only overwritten once
    every step that was going to run has actually succeeded AND actually
    produced its expected file - a subprocess exiting 0 without producing
    its promised output is treated as a failure too, not silently promoted
    as empty/missing. Stale *.tmp files from a previous crashed run are
    deleted at the very start of this function, before anything runs, so a
    leftover file from an earlier attempt can never be mistaken for this
    run's output if a later step exits 0 without writing anything.
    """
    join_script = state_dir / "eo_storm_join.py"

    # All final and temporary paths are defined together, up front,
    # including the zone-resolution outputs (used only conditionally below)
    # so every one of them can be cleared before this run starts.
    matches = state_dir / "eo_storm_matches.csv"
    severity = state_dir / "eo_storm_severity_summary.csv"
    resolved = state_dir / "severity_resolved.csv"
    matches_tmp = state_dir / "eo_storm_matches.csv.tmp"
    severity_tmp = state_dir / "eo_storm_severity_summary.csv.tmp"
    resolved_tmp = state_dir / "severity_resolved.csv.tmp"

    for temporary_path in (matches_tmp, severity_tmp, resolved_tmp):
        temporary_path.unlink(missing_ok=True)

    cmd = [
        sys.executable,
        str(join_script),
        "--declarations",
        str(action_path),
        "--state",
        state["name"].upper(),
        "--out",
        str(matches_tmp),
        "--severity-out",
        str(severity_tmp),
    ]
    # Apply a state's durable, human-reviewed hazard overrides automatically
    # when present, so a rebuild can never silently run without them. This
    # file is the reviewed source of truth (see eo_storm_join.py's
    # load_overrides/apply_overrides) and is intentionally never generated
    # by collection - only added here when a reviewer has created it.
    # --unmatched-hazard-policy all is deliberately never added here or
    # anywhere else in this builder: that flag is global per run, not
    # per-declaration, and would reintroduce the original over-match risk
    # for every declaration in the state, not just the reviewed ones.
    overrides_path = state_dir / "hazard_overrides.csv"
    if overrides_path.exists():
        cmd.extend(["--overrides", str(overrides_path.resolve())])
    # Only hazard_overrides.csv is read. Reviewed overrides saved under another
    # name (hazard_overrides_kansas.csv, say) were silently never applied:
    # Kansas's 14 and Montana's last 2 sat unused until Sep 2026. Say so.
    stray = sorted(p.name for p in state_dir.glob("hazard_overrides*.csv")
                   if p.name != "hazard_overrides.csv" and not p.name.endswith(".tmp"))
    if stray:
        print(f"WARNING {state['abbreviation']}: {', '.join(stray)} is not read; reviewed "
              f"overrides must be in hazard_overrides.csv", file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(state_dir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        matches_tmp.unlink(missing_ok=True)
        severity_tmp.unlink(missing_ok=True)
        return (f"Storm join failed with exit code {result.returncode}", True)

    if not matches_tmp.exists() or not severity_tmp.exists():
        matches_tmp.unlink(missing_ok=True)
        severity_tmp.unlink(missing_ok=True)
        return (
            "Storm join reported success (exit code 0) but did not produce "
            f"its expected output files ({matches_tmp.name}, "
            f"{severity_tmp.name}) - treated as a failure",
            True,
        )

    resolver = state_dir / "resolve_zones_to_counties.py"
    zone_files = sorted(state_dir.glob("bp*.dbx"))
    if resolver.exists() and zone_files and severity_tmp.exists():
        resolve_cmd = [
            sys.executable,
            str(resolver),
            "--input",
            str(severity_tmp),
            "--zone-file",
            str(zone_files[-1]),
            "--out",
            str(resolved_tmp),
            "--state",
            state["abbreviation"],
        ]
        resolve_result = subprocess.run(
            resolve_cmd, cwd=str(state_dir), capture_output=True, text=True
        )
        if resolve_result.stdout:
            print(resolve_result.stdout)
        if resolve_result.returncode != 0:
            if resolve_result.stderr:
                print(resolve_result.stderr, file=sys.stderr)
            matches_tmp.unlink(missing_ok=True)
            severity_tmp.unlink(missing_ok=True)
            resolved_tmp.unlink(missing_ok=True)
            return (
                f"Storm join completed; zone resolution failed with exit code {resolve_result.returncode}",
                True,
            )
        if not resolved_tmp.exists():
            matches_tmp.unlink(missing_ok=True)
            severity_tmp.unlink(missing_ok=True)
            return (
                "Zone resolution reported success (exit code 0) but did not "
                f"produce its expected output file ({resolved_tmp.name}) - "
                "treated as a failure",
                True,
            )
        ok, message = _promote_outputs(
            [(matches_tmp, matches), (severity_tmp, severity), (resolved_tmp, resolved)]
        )
        if not ok:
            return (message, True)
        return ("Storm join and forecast-zone resolution completed", False)

    # No zone resolution was attempted - the join itself is the last step,
    # so its outputs move into place now.
    ok, message = _promote_outputs([(matches_tmp, matches), (severity_tmp, severity)])
    if not ok:
        return (message, True)
    return (
        "Storm join completed; forecast-zone resolution skipped because its script or crosswalk was unavailable",
        False,
    )


def coverage_label(state: dict, actions: list[dict], collection_note: str) -> str:
    if collection_note:
        return collection_note
    if actions and state["adapter_status"] == "implemented":
        return state.get("coverage_note") or "State-action data available"
    if actions:
        return "Imported state-action data available; adapter validation pending"
    if state["adapter_status"] == "implemented":
        return "Adapter available; no cached action file found"
    if state["adapter_status"] == "planned":
        return "State-source adapter planned; state-action coverage not yet available"
    return "State-source adapter not yet implemented"


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def action_rows(actions: list[dict]) -> str:
    if not actions:
        return (
            '<tr><td colspan="5" class="empty">No verified state-action records '
            "have been loaded for this state yet.</td></tr>"
        )
    output = []
    for action in actions:
        source = esc(action["source_url"])
        title = esc(action["title"] or "Untitled action")
        title_cell = f'<a href="{source}">{title}</a>' if source else title
        output.append(
            "<tr>"
            f"<td>{esc(action['date_signed'])}</td>"
            f"<td>{esc(action['action_number'])}</td>"
            f"<td>{title_cell}</td>"
            f"<td>{esc(action['action_type'])}</td>"
            f"<td>{esc(action['governor'])}</td>"
            "</tr>"
        )
    return "\n".join(output)


def federal_declaration_rows(federal_declarations: list[dict]) -> str:
    if not federal_declarations:
        return (
            '<tr><td colspan="6" class="empty">No federal FEMA declarations are loaded '
            "for this state yet.</td></tr>"
        )
    output = []
    for declaration in federal_declarations[:200]:
        number = esc(declaration.get("number") or declaration.get("id"))
        title = esc(declaration.get("title") or declaration.get("eventName") or "Untitled declaration")
        output.append(
            "<tr>"
            f"<td>{esc(declaration.get('date') or declaration.get('begin'))}</td>"
            f"<td>{number}</td>"
            f"<td>{esc(declaration.get('type'))}</td>"
            f"<td>{title}</td>"
            f"<td>{esc(declaration.get('incidentType'))}</td>"
            f"<td>{esc(declaration.get('begin'))} to {esc(declaration.get('end'))}</td>"
            "</tr>"
        )
    return "\n".join(output)


def noaa_event_rows(storm_rows: list[dict]) -> str:
    if not storm_rows:
        return (
            '<tr><td colspan="6" class="empty">No matched NOAA/NWS Storm Events '
            "are loaded for this state yet.</td></tr>"
        )
    output = []
    for row in storm_rows[:300]:
        output.append(
            "<tr>"
            f"<td>{esc(row.get('BEGIN_DATE_TIME'))}</td>"
            f"<td>{esc(row.get('CZ_NAME'))}</td>"
            f"<td>{esc(row.get('area_type'))}</td>"
            f"<td>{esc(row.get('EVENT_TYPE'))}</td>"
            f"<td>{esc(row.get('DEATHS_DIRECT'))} / {esc(row.get('INJURIES_DIRECT'))}</td>"
            f"<td>{esc(row.get('DAMAGE_PROPERTY'))}</td>"
            "</tr>"
        )
    return "\n".join(output)


def crosswalk_rows(crosswalk: list[dict]) -> str:
    if not crosswalk:
        return (
            '<tr><td colspan="4" class="empty">No state actions are loaded to cross-'
            "reference yet.</td></tr>"
        )
    output = []
    for row in crosswalk:
        action = row["action"]
        title = esc(action["title"] or "Untitled action")
        areas = ", ".join(row["noaa_areas"][:8]) if row["noaa_areas"] else "None matched"
        count_cell = str(row["noaa_match_count"])
        if row.get("noaa_status") == "pending":
            count_cell = '<span class="empty">Pending</span>'
            areas = "NOAA has not published storm data for this date yet"
        if row["federal_status"] == "matched":
            federal = row["federal_declaration"]
            federal_cell = esc(federal.get("number") or federal.get("id"))
        else:
            federal_cell = '<span class="empty">No corresponding federal declaration found</span>'
        output.append(
            "<tr>"
            f"<td>{esc(action['date_signed'])} &middot; {title}</td>"
            f"<td>{count_cell}</td>"
            f"<td>{esc(areas)}</td>"
            f"<td>{federal_cell}</td>"
            "</tr>"
        )
    return "\n".join(output)


def sortable_header(label: str, column: int) -> str:
    return (
        f'<th><button class="sort-button" type="button" data-column="{column}" '
        f'aria-label="Sort by {esc(label)}">{esc(label)} <span aria-hidden="true">↕</span>'
        "</button></th>"
    )


def table_filter(table_id: str, label: str) -> str:
    return (
        '<div class="table-tools">'
        f'<label for="filter-{esc(table_id)}">Filter {esc(label)}</label>'
        f'<input id="filter-{esc(table_id)}" class="table-search" '
        f'data-table="{esc(table_id)}" type="search" placeholder="Search this table…">'
        "</div>"
    )


def table_script() -> str:
    return """
<script>
document.querySelectorAll('.table-search').forEach((input) => {
  input.addEventListener('input', () => {
    const query = input.value.trim().toLocaleLowerCase();
    const table = document.getElementById(input.dataset.table);
    if (!table) return;
    table.querySelectorAll('tbody tr').forEach((row) => {
      row.hidden = query && !row.textContent.toLocaleLowerCase().includes(query);
    });
  });
});

document.querySelectorAll('table.sortable').forEach((table) => {
  table.querySelectorAll('.sort-button').forEach((button) => {
    button.addEventListener('click', () => {
      const column = Number(button.dataset.column);
      const ascending = button.dataset.direction !== 'asc';
      const body = table.tBodies[0];
      const rows = Array.from(body.rows);
      rows.sort((left, right) => {
        const a = left.cells[column]?.textContent.trim() || '';
        const b = right.cells[column]?.textContent.trim() || '';
        return a.localeCompare(b, undefined, {numeric: true, sensitivity: 'base'});
      });
      if (!ascending) rows.reverse();
      rows.forEach((row) => body.appendChild(row));
      table.querySelectorAll('.sort-button').forEach((other) => {
        delete other.dataset.direction;
        other.closest('th').removeAttribute('aria-sort');
        other.querySelector('span').textContent = '↕';
      });
      button.dataset.direction = ascending ? 'asc' : 'desc';
      button.closest('th').setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      button.querySelector('span').textContent = ascending ? '↑' : '↓';
    });
  });
});
</script>"""


def shared_css(prefix: str = "") -> str:
    """DisasterData.IO's site-wide design tokens, applied to the Plus pages.

    NOTE: these color/type tokens (--paper/--accent/--ember/--ink, Fraunces +
    Public Sans) were carried over from the live main site. If the main site
    keeps a single shared stylesheet (e.g. /styles.css) rather than repeating
    an inline block per generator, point this at that file instead so the
    Plus pages can never drift from the rest of DisasterData.IO again.
    """
    return f"""
    :root {{
      --paper:#f6f1e7; --paper-2:#fcfaf3; --paper-3:#f1ead9;
      --accent:#004c53; --accent-2:#0a6b73; --ember:#c85c2e;
      --ink:#1d1813; --muted:#6b6255; --line:#e1d8c6;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper);
      font-family:"Public Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:16px; line-height:1.55; }}
    h1,h2,h3,.eyebrow {{ font-family:"Fraunces","Georgia",serif; }}
    a {{ color:var(--accent-2); }}
    .dd-breadcrumb {{ background:var(--accent); color:var(--paper-2); padding:.85rem 1.25rem;
      font-size:.9rem; }}
    .dd-breadcrumb a {{ color:var(--paper-2); text-decoration:none; font-weight:600; }}
    .dd-breadcrumb a:hover {{ text-decoration:underline; }}
    main {{ max-width:1120px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
    h1 {{ line-height:1.15; margin:.25rem 0 .75rem; font-weight:600; }}
    h2 {{ margin-top:2rem; font-weight:600; }}
    .eyebrow {{ color:var(--ember); font-weight:700; letter-spacing:.05em;
      text-transform:uppercase; font-size:.8rem; }}
    .lede,.note {{ color:var(--muted); max-width:820px; }}
    .notice {{ background:var(--paper-3); border-left:5px solid var(--ember); padding:1rem;
      margin:1.25rem 0; }}
    .metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
      gap:1rem; margin:1.5rem 0; }}
    .metric,.state-card {{ background:var(--paper-2); border:1px solid var(--line);
      border-radius:10px; padding:1rem; }}
    .metric strong {{ display:block; font-family:"Fraunces",serif; font-size:1.8rem;
      color:var(--accent); }}
    .states {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(235px,1fr));
      gap:.8rem; }}
    .state-card a {{ color:var(--accent); font-weight:700; text-decoration:none; }}
    .card-count-row {{ display:flex; align-items:baseline; justify-content:space-between;
      gap:.5rem; flex-wrap:wrap; margin-top:.3rem; }}
    .since-badge {{ display:inline-block; flex-shrink:0; padding:.15rem .55rem;
      border-radius:99px; background:var(--accent); color:var(--paper-2);
      font-size:.75rem; font-weight:700; white-space:nowrap; }}
    .count-unclear {{ color:var(--muted); font-style:italic; }}
    .status {{ display:inline-block; margin-top:.5rem; padding:.15rem .5rem;
      border-radius:99px; background:var(--paper-3); color:var(--accent); font-size:.78rem; }}
    table {{ width:100%; border-collapse:collapse; background:var(--paper-2); font-size:.9rem; }}
    th,td {{ padding:.65rem; border-bottom:1px solid var(--line); text-align:left;
      vertical-align:top; }}
    th {{ background:var(--accent); color:var(--paper-2); font-weight:600; }}
    .sort-button {{ width:100%; border:0; padding:0; color:inherit; background:none;
      font:inherit; font-weight:600; text-align:left; cursor:pointer; }}
    td a {{ color:var(--accent-2); }} .empty {{ color:var(--muted); font-style:italic; }}
    .actions {{ overflow-x:auto; }}
    .layer {{ margin-top:2.5rem; padding-top:.5rem; border-top:3px solid var(--line); }}
    .layer h2 {{ margin-top:.5rem; }}
    .primary {{ background:var(--paper-2); border:1px solid var(--line); border-radius:12px;
      padding:1rem; }}
    .table-tools {{ display:flex; gap:.75rem; align-items:center; justify-content:flex-end;
      margin:.5rem 0; }}
    .table-tools label {{ color:var(--muted); font-size:.85rem; font-weight:600; }}
    .table-search {{ width:min(100%,320px); padding:.55rem .7rem; border:1px solid var(--line);
      border-radius:7px; font:inherit; background:var(--paper-2); color:var(--ink); }}
    details.layer {{ background:var(--paper-2); border:1px solid var(--line); border-radius:10px;
      padding:0; overflow:hidden; }}
    details.layer > summary {{ display:flex; justify-content:space-between; gap:1rem;
      padding:1rem; cursor:pointer; color:var(--accent); font-weight:700; }}
    details.layer[open] > summary {{ border-bottom:1px solid var(--line); }}
    details.layer > .details-body {{ padding:0 1rem 1rem; }}
    .count-badge {{ color:var(--muted); font-size:.85rem; font-weight:600; white-space:nowrap; }}
    [hidden] {{ display:none !important; }}
    @media (max-width:640px) {{
      main {{ padding:1.25rem .75rem 3rem; }}
      .table-tools {{ display:block; }}
      .table-tools label {{ display:block; margin-bottom:.25rem; }}
      .table-search {{ width:100%; }}
    }}
    footer {{ margin-top:3rem; padding-top:1rem; border-top:1px solid var(--line);
      color:var(--muted); font-size:.85rem; }}
    """


def brand_fonts() -> str:
    """Fraunces + Public Sans, matching the main site's typography.

    Swap this block for the exact font-loading snippet used elsewhere on
    DisasterData.IO (e.g. a self-hosted @font-face block) if the main site
    does not load these from Google Fonts, so every page requests fonts the
    same way.
    """
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
        '9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&display=swap" '
        'rel="stylesheet">'
    )


def brand_header(breadcrumb: str) -> str:
    """The site's one shared nav (served from /nav.js at the root) plus a
    Plus-specific breadcrumb underneath it, matching how the rest of the
    site carries only <script src="/nav.js"></script> and defines no nav of
    its own."""
    return f'<script src="/nav.js"></script><nav class="dd-breadcrumb">{breadcrumb}</nav>'


def noaa_through_note() -> str:
    if not NOAA_DATA_THROUGH:
        return ""
    return (f" NOAA's published Storm Events data used here runs through about "
            f"{esc(NOAA_DATA_THROUGH)}; declarations signed after that show as pending "
            "until NOAA publishes those months.")


def render_state_page(
    state: dict,
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows: list[dict],
    crosswalk: list[dict],
    metrics: dict,
    coverage: str,
) -> str:
    name = esc(state["name"])
    source = state.get("official_source_url", "")
    source_link = (
        f'<a href="{esc(source)}">Official state source</a>'
        if source
        else "Official source to be identified"
    )
    breadcrumb = (
        f'<a href="/">DisasterData.IO</a> / <a href="/plus/">Plus</a> / {name}'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Disaster Data | {name} Weather Emergency Declarations</title>
<meta name="description" content="Weather emergency declarations, federal disaster records, and matched NOAA/NWS evidence for {name}.">
{brand_fonts()}
<style>{shared_css()}</style></head>
<body>{brand_header(breadcrumb)}
<main><div class="eyebrow">DisasterData Plus</div>
<h1>{name}: Weather Emergency Declarations</h1>
<p class="lede">Original state weather-emergency declarations, compared with federal FEMA declarations and nearby NOAA/NWS Storm Events evidence.</p>
<div class="notice"><strong>Coverage:</strong> {esc(coverage)}. Absence from this page must not be interpreted as absence of a state emergency.</div>
<section class="metrics">
  <div class="metric"><strong>{metrics['federal_declaration_count']:,}</strong>federal FEMA declarations</div>
  <div class="metric"><strong>{metrics['action_count']:,}</strong>original state weather declarations</div>
  <div class="metric"><strong>{metrics['storm_match_rows']:,}</strong>matched NOAA event rows</div>
</section>
<p><a href="/states/{esc(state['slug'])}.html">Federal declaration overview</a> &middot; {source_link}</p>

<div class="layer primary">
<h2>State weather declarations</h2>
<p class="note">Original weather-related declarations only. Administrative orders, public-health orders, extensions, amendments, and terminations are excluded from this incident list.</p>
{table_filter('state-weather-table', 'state declarations')}
<div class="actions"><table id="state-weather-table" class="sortable"><thead><tr>{sortable_header('Date', 0)}{sortable_header('Number', 1)}{sortable_header('Action', 2)}{sortable_header('Type', 3)}{sortable_header('Governor', 4)}</tr></thead>
<tbody>{action_rows(actions)}</tbody></table></div>
</div>

<div class="layer">
<h2>Combined event crosswalk</h2>
<p class="note">Each state action, its matched NOAA evidence, and the closest federal declaration within {FEDERAL_MATCH_WINDOW_DAYS} days of its incident window, if one exists. A federal match is an automated date-proximity candidate, not a confirmed legal link.</p>
{table_filter('crosswalk-table', 'crosswalk')}
<div class="actions"><table id="crosswalk-table" class="sortable"><thead><tr>{sortable_header('State action', 0)}{sortable_header('NOAA matches', 1)}{sortable_header('Matched areas', 2)}{sortable_header('Federal declaration', 3)}</tr></thead>
<tbody>{crosswalk_rows(crosswalk)}</tbody></table></div>
</div>

<details class="layer">
<summary><span>Federal FEMA declarations</span><span class="count-badge">{metrics['federal_declaration_count']:,} records</span></summary>
<div class="details-body"><p class="note">DR, EM, and FM declarations for {name} from the site's national FEMA dataset.</p>
{table_filter('federal-table', 'federal declarations')}
<div class="actions"><table id="federal-table" class="sortable"><thead><tr>{sortable_header('Date', 0)}{sortable_header('Number', 1)}{sortable_header('Type', 2)}{sortable_header('Title', 3)}{sortable_header('Incident type', 4)}{sortable_header('Incident period', 5)}</tr></thead>
<tbody>{federal_declaration_rows(federal_declarations)}</tbody></table></div></div>
</details>

<details class="layer">
<summary><span>NOAA/NWS matched event details</span><span class="count-badge">{metrics['storm_match_rows']:,} rows</span></summary>
<div class="details-body"><p class="note">Storm Events matched within the configured date window of a state declaration's signing date. This is temporal and geographic evidence, not proof of causation or operational impact.</p>
{table_filter('noaa-table', 'NOAA events')}
<div class="actions"><table id="noaa-table" class="sortable"><thead><tr>{sortable_header('Date', 0)}{sortable_header('Area', 1)}{sortable_header('Area type', 2)}{sortable_header('Hazard', 3)}{sortable_header('Deaths / injuries', 4)}{sortable_header('Property damage', 5)}</tr></thead>
<tbody>{noaa_event_rows(storm_rows)}</tbody></table></div></div>
</details>

<details class="layer"><summary><span>Methodology and coverage</span></summary><div class="details-body">
<p class="note">Federal declarations are sourced from OpenFEMA via this site's national build. State declarations are limited by the coverage statement above. NOAA proximity matches identify potentially related observed events within a configured window of each state declaration's signing date; they do not independently prove operational impacts or legal causation.{noaa_through_note()} The federal crosswalk match uses a wider {FEDERAL_MATCH_WINDOW_DAYS} day window than the NOAA match, since a federal declaration is often filed weeks after the state action that preceded it.</p>
</div></details>
<footer>Generated {date.today().isoformat()} &middot; DisasterData.IO &middot; State and federal records remain subject to source verification. &middot; <a href="https://forms.gle/NZ6bSadoXrKYHjjH8" target="_blank" rel="noopener">Report a Data Issue</a></footer>
</main>{table_script()}</body></html>"""


_COVERAGE_START_MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)
_COVERAGE_START_PATTERN = re.compile(
    rf"^(?:(?:{_COVERAGE_START_MONTHS})\s+)?(\d{{4}})(?:-\d{{2}}-\d{{2}})?-present\b"
)
_COVERAGE_START_RANGE_PATTERN = re.compile(r"^(\d{4})-\d{4}\b")

# A handful of states' real coverage_note text doesn't fit the common
# "<year>-present" / "<Month year>-present" shape the regex above expects -
# either because the note uses a closed range ("2000-2025 ..."), states the
# start year in a full sentence rather than a leading date (Virginia), or
# because the disclosed sources are narrower/less certain than a single
# clean start year would honestly convey (Alaska, Hawaii, Ohio all
# explicitly say no complete archive was verified). Rather than let the
# regex either miss these or guess a misleading year, each is handled
# explicitly here, verified against what that state's real coverage_note
# actually says as of the date this was written.
_COVERAGE_START_OVERRIDES = {
    "CO": "2000",
    "KY": "2019",
    "VA": "2002",
}
_COVERAGE_START_NO_CLEAN_YEAR = {"AK", "HI", "OH"}


def extract_coverage_start_label(abbreviation: str, coverage_note: str, action_count: int) -> str:
    """A short, scannable label for how far back a state's real coverage
    goes - meant to sit next to the declaration count so a reader isn't
    misled into thinking a low count means "few disasters" when it may
    just mean "a narrow coverage window." Falls back to a neutral,
    honest label rather than guessing when the coverage_note text doesn't
    state a single clean start year.
    """
    # "Adapter available; no cached action file found" and similar mean no
    # data was loaded in this run at all - a different situation from a
    # narrow-but-real coverage window, so it gets a distinct label rather
    # than a fabricated or misleading date.
    if "no cached action file" in coverage_note.lower() or "adapter not yet implemented" in coverage_note.lower():
        return "No data loaded"
    if abbreviation in _COVERAGE_START_OVERRIDES:
        return f"Since {_COVERAGE_START_OVERRIDES[abbreviation]}"
    if abbreviation in _COVERAGE_START_NO_CLEAN_YEAR:
        return "Uneven coverage"
    match = (_COVERAGE_START_PATTERN.match(coverage_note)
             or _COVERAGE_START_RANGE_PATTERN.match(coverage_note))
    if match:
        # Nothing before EARLIEST_ACTION_YEAR is shown, so the badge never
        # claims an earlier start than the page can back up.
        return f"Since {max(int(match.group(1)), EARLIEST_ACTION_YEAR)}"
    return "See coverage note"


def render_landing(summaries: list[dict], all_states: list[dict]) -> str:
    by_abbreviation = {item["abbreviation"]: item for item in summaries}
    cards = []
    for state in all_states:
        summary = by_abbreviation.get(state["abbreviation"])
        count = summary["metrics"]["action_count"] if summary else 0
        coverage = summary["coverage"] if summary else "Not rebuilt in this run"
        coverage_base = summary.get("coverage_base") if summary else "Not rebuilt in this run"
        collection_error = summary.get("collection_error") if summary else ""
        collection_failed = bool(collection_error)
        start_label = extract_coverage_start_label(state["abbreviation"], coverage, count)
        # A "0" here is not a verified finding of zero qualifying declarations -
        # this dataset has no current mechanism to assert that, and every zero
        # count so far corresponds to a disclosed coverage gap or a failed
        # collection run, never a stated-complete archive with a real zero
        # result. Rather than print a bare number that reads as a confirmed
        # count either way, a zero is labeled as "not loaded" so a reader
        # can't mistake missing data for a finding. A nonzero count from a
        # run whose collection failed is still shown (it reflects real,
        # previously-collected data on disk), but flagged as not refreshed
        # this run so the reader knows it may be out of date.
        count_uncertain = count == 0
        if count_uncertain:
            count_html = f'<span class="count-unclear">No records loaded yet</span>'
        elif collection_failed:
            count_html = (
                f'<span>{count:,} original weather declarations</span> '
                f'<span class="count-unclear">(not refreshed this run)</span>'
            )
        else:
            count_html = f'<span>{count:,} original weather declarations</span>'
        # "Collection failed: <exception text>" is a technical detail meant
        # for a build log, not a first-read label. When today's collection
        # run failed, lead with a plain-language status and move the raw
        # error into a title attribute (visible on hover/long-press) rather
        # than the primary text; otherwise show the real coverage note as-is,
        # since that text is already written for a general reader.
        if collection_failed:
            status_display = "Latest update unsuccessful"
            status_title = f"{coverage_base}; {collection_error}" if coverage_base else collection_error
        else:
            status_display = coverage_base
            status_title = ""
        title_attr = f' title="{esc(status_title)}"' if status_title else ""
        cards.append(
            '<article class="state-card">'
            f'<a href="/plus/{esc(state["slug"])}/">{esc(state["name"])}</a>'
            f'<div class="card-count-row">'
            f"{count_html}"
            f'<span class="since-badge">{esc(start_label)}</span>'
            "</div>"
            f'<span class="status"{title_attr}>{esc(status_display)}</span>'
            "</article>"
        )
    loaded = sum(1 for item in summaries if item["metrics"]["action_count"] > 0)
    implemented = sum(1 for state in all_states if state["adapter_status"] == "implemented")
    breadcrumb = '<a href="/">DisasterData.IO</a> / Plus'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Disaster Data | State Emergency Evidence</title>
<meta name="description" content="State emergency actions and observed hazard evidence across the United States.">
{brand_fonts()}
<style>{shared_css()}</style></head>
<body>{brand_header(breadcrumb)}
<main><div class="eyebrow">DisasterData Plus</div><h1>State emergency evidence</h1>
<p class="lede">State declarations, executive actions, proclamations, and observed weather evidence supplementing the federal disaster record.</p>
<div class="notice">Coverage varies by state. A generated page is not evidence that its state-action archive is complete.</div>
<section class="metrics">
  <div class="metric"><strong>50</strong>states covered</div>
  <div class="metric"><strong>{implemented}</strong>data sources set up</div>
  <div class="metric"><strong>{loaded}</strong>states with records loaded right now</div>
</section>
<h2>Browse by state</h2><section class="states">{''.join(cards)}</section>
<footer>Generated {date.today().isoformat()} &middot; DisasterData.IO &middot; <a href="https://forms.gle/NZ6bSadoXrKYHjjH8" target="_blank" rel="noopener">Report a Data Issue</a></footer>
</main></body></html>"""


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- public API file
# plus/<slug>/api.json is what the DisasterData API (worker-api.js) serves for
# a state's state declarations and crosswalk. It is written here, from the same
# actions and crosswalk this run rendered the state page from, so the API and
# the page can never disagree. The Worker only reads and routes it; it carries
# no join logic of its own.
API_FILE = "api.json"
API_SCHEMA_VERSION = 1


def federal_reference(declaration: dict | None) -> dict | None:
    """The fields of a federal declaration an API caller needs to identify it,
    without the full county list (that is at /v1/states/<abbr>/declarations)."""
    if not declaration:
        return None
    keys = ("id", "number", "type", "title", "incidentType", "date", "begin", "end")
    return {key: declaration.get(key) for key in keys if key in declaration}


def api_payload(state: dict, summary: dict, actions: list[dict], crosswalk: list[dict]) -> dict:
    return {
        "schema_version": API_SCHEMA_VERSION,
        "state": state["abbreviation"],
        "name": state["name"],
        "slug": state["slug"],
        "generated_on": summary.get("generated_on") or date.today().isoformat(),
        "coverage": summary.get("coverage", ""),
        "official_source_url": state.get("official_source_url", ""),
        "source_status": summary.get("source_status"),
        "kept_saved_records": summary.get("kept_saved_records", 0),
        "federal_match_window_days": FEDERAL_MATCH_WINDOW_DAYS,
        "noaa_data_through": NOAA_DATA_THROUGH,
        "metrics": summary.get("metrics", {}),
        "actions": actions,
        "crosswalk": [
            {
                "declaration_id": row["action"]["declaration_id"],
                "date_signed": row["action"].get("date_signed", ""),
                "title": row["action"].get("title", ""),
                "noaa_match_count": row["noaa_match_count"],
                "noaa_status": row.get("noaa_status", ""),
                "noaa_areas": row["noaa_areas"],
                "federal_status": row["federal_status"],
                "federal_declaration": federal_reference(row["federal_declaration"]),
            }
            for row in crosswalk
        ],
    }


def write_api_file(state: dict, state_dir: Path, summary: dict,
                   actions: list[dict], crosswalk: list[dict]) -> None:
    write_json(state_dir / API_FILE, api_payload(state, summary, actions, crosswalk))


def process_state(
    state: dict,
    repo_root: Path,
    collect: bool,
    join_storms: bool,
    dry_run: bool,
    collected: dict | None = None,
) -> dict:
    """Collect (when asked), join and render one state. `collected` is the
    result of a collection already made, used by main()'s retry pass so a
    recovered state is rebuilt without being collected a second time."""
    state_dir = repo_root / "plus" / state["slug"]
    if collected is None and collect:
        collected = collect_with_safeguard(state, state_dir)
    if collected is not None:
        collection_note = collected["note"]
        collection_error = collected["error"]
        kept = collected["kept"]
    else:
        collection_note, collection_error = "", ""
        kept = {"kept": 0, "filled": 0, "cleaned": 0}

    fmcsa_count = 0
    if not dry_run:
        try:
            fmcsa_count = write_fmcsa_supplement(state, state_dir, repo_root)
        except Exception as exc:  # the second source must never break a state
            print(f"WARNING {state['abbreviation']}: FMCSA supplement not written ({exc})", file=sys.stderr)
    actions, action_path = load_state_actions(state, state_dir)
    storm_note = ""
    storm_failed = False
    storm_pipeline_ran = False
    join_started = time.monotonic()
    if join_storms:
        if dry_run:
            # --dry-run promises to validate and report without writing, but
            # the storm join always runs a real external subprocess (network
            # requests, its own temp files) and, on success, promotes real
            # output files - main() also rejects this combination up front,
            # but that check is guarded here too in case process_state() is
            # ever called directly rather than through main().
            storm_note = "Storm join skipped: --dry-run and --join-storms cannot be combined"
        elif action_path:
            storm_join_path = ensure_declaration_id_column(action_path, state["abbreviation"])
            storm_join_path = with_fmcsa_supplement(storm_join_path, state_dir)
            storm_note, storm_failed, storm_pipeline_ran = run_storm_pipeline(
                state, state_dir, storm_join_path)
        elif state.get("adapter_status") == "implemented":
            storm_note = "Storm join failed: no state-action CSV is available"
            storm_failed = True
        else:
            storm_note = "Storm join skipped: no state-action CSV is available"

    join_seconds = round(time.monotonic() - join_started, 1) if join_storms else None
    federal_declarations = load_federal_declarations(repo_root, state["abbreviation"])
    if storm_pipeline_ran:
        # Read this run's own freshly-generated, verified outputs directly,
        # bypassing load_storm_match_rows()/load_severity_rows()'s
        # preference for a *_filtered.csv variant. Those loaders exist for a
        # manually curated filtered dataset that predates this pipeline and
        # that nothing here regenerates - but that means a successful
        # --join-storms run could produce correct fresh data and then
        # immediately render the page from an old filtered file instead,
        # making a real fix look like it had no effect. When this call
        # itself just produced fresh, verified output, use it, full stop.
        matches_path = state_dir / "eo_storm_matches.csv"
        severity_path = state_dir / "eo_storm_severity_summary.csv"
        storm_rows = read_csv_rows(matches_path if matches_path.exists() else None)
        severity_rows = read_csv_rows(severity_path if severity_path.exists() else None)
    else:
        storm_rows, _ = load_storm_match_rows(state_dir)
        severity_rows, _ = load_severity_rows(state_dir)
    storm_rows_by_declaration = group_by_declaration(storm_rows)
    crosswalk = build_crosswalk(actions, federal_declarations, storm_rows_by_declaration)

    metrics = state_metrics(state, actions, federal_declarations, storm_rows, severity_rows)
    coverage_base = coverage_label(state, actions, collection_note)
    coverage = coverage_base
    if fmcsa_count:
        coverage += ("; plus %d weather declaration%s from FMCSA's archive of state emergency "
                     "declarations (2017-present)" % (fmcsa_count, "" if fmcsa_count == 1 else "s"))
    if collection_error:
        coverage += "; " + collection_error
    if kept["kept"]:
        # Said on the page itself, so a reader knows some records come from
        # earlier refreshes rather than from this week's check of the source.
        coverage += (
            "; %d saved record%s kept that this refresh's check of the state source "
            "did not return" % (kept["kept"], "" if kept["kept"] == 1 else "s")
        )

    summary = {
        "abbreviation": state["abbreviation"],
        "name": state["name"],
        "slug": state["slug"],
        "adapter_status": state["adapter_status"],
        "coverage": coverage,
        "coverage_base": coverage_base,
        "collection_error": collection_error,
        "collection_failed": bool(collection_error),
        "action_file": action_path.name if action_path else "",
        "metrics": metrics,
        "storm_pipeline_note": storm_note,
        "storm_pipeline_failed": storm_failed,
        "kept_saved_records": kept["kept"],
        "kept_saved_values": kept["filled"] + kept["cleaned"],
        # What the source returned this run; read by scripts/plus_health.py.
        "source_status": collected["status"] if collected else SOURCE_NOT_COLLECTED,
        "source_records_returned": collected["scraped_rows"] if collected else None,
        "source_records_saved_before": collected["saved_rows"] if collected else None,
        "retried": False,
        # Seconds spent on this state, so each run shows where its time went.
        "timing": {"collect_seconds": collected.get("seconds") if collected else None,
                   "storm_join_seconds": join_seconds},
        "generated_on": date.today().isoformat(),
    }
    if not dry_run:
        if storm_failed:
            print(
                f"Skipping page/summary rebuild for {state['abbreviation']}: "
                "storm pipeline failed, refusing to render a page from stale "
                "or partial data. The previous successful run's files (if "
                "any) under plus/" + state["slug"] + "/ are left untouched.",
                file=sys.stderr,
            )
        else:
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "index.html").write_text(
                render_state_page(
                    state, actions, federal_declarations, storm_rows, crosswalk, metrics, coverage
                ),
                encoding="utf-8",
            )
            write_json(state_dir / "state-summary.json", summary)
            try:
                write_api_file(state, state_dir, summary, actions, crosswalk)
            except Exception as exc:  # the API file must never break a state's page
                print(f"WARNING {state['abbreviation']}: {API_FILE} not written ({exc})",
                      file=sys.stderr)
    return summary


# A state site that fails once often answers a minute later: Minnesota,
# Texas, Wisconsin and Missouri each failed on some runs and not others, and
# on 2026-09-15 eleven states failed in the same run. So every state whose
# source failed or returned nothing gets one more try after the rest of the
# run, and a state that recovers is rebuilt from what the retry collected.
RETRY_DELAY_SECONDS = int(os.environ.get("PLUS_RETRY_DELAY", "60"))
NCEI_CACHE_ENV = "PLUS_NCEI_CACHE_DIR"   # read by each state's eo_storm_join.py


def retry_failed_sources(selected: list[dict], summaries: list[dict], repo_root: Path,
                         join_storms: bool) -> list[dict]:
    by_abbreviation = {state["abbreviation"]: state for state in selected}
    retry = [item for item in summaries if item.get("source_status") in SOURCE_BAD
             and adapter_path_for(by_abbreviation[item["abbreviation"]],
                                  repo_root / "plus" / item["slug"]).exists()]
    if not retry:
        return summaries
    print(f"\nRetrying {len(retry)} state(s) whose source failed or returned nothing, "
          f"after {RETRY_DELAY_SECONDS}s: " + ", ".join(item["abbreviation"] for item in retry))
    time.sleep(RETRY_DELAY_SECONDS)
    replaced = {}
    for first in retry:
        state = by_abbreviation[first["abbreviation"]]
        state_dir = repo_root / "plus" / state["slug"]
        result = collect_with_safeguard(state, state_dir)
        first_attempt = {"status": first["source_status"], "error": first.get("collection_error", ""),
                         "seconds": (first.get("timing") or {}).get("collect_seconds")}
        if result["status"] in SOURCE_BAD:
            print(f"RETRY {state['abbreviation']}: still {result['status']}"
                  + (f" ({result['error']})" if result["error"] else ""))
            updated = dict(first, retried=True, retry_status=result["status"],
                           retry_error=result["error"])
        else:
            print(f"RETRY {state['abbreviation']}: recovered ({result['status']}, "
                  f"{result['scraped_rows']} records returned); rebuilding")
            updated = process_state(state, repo_root, False, join_storms, False, collected=result)
            updated.update(retried=True, retry_status=result["status"], first_attempt=first_attempt)
        summary_path = state_dir / "state-summary.json"
        # process_state() writes the summary unless the storm join failed, in
        # which case the previous run's files are left alone on purpose.
        if not updated.get("storm_pipeline_failed") and summary_path.exists():
            write_json(summary_path, updated)
        replaced[state["abbreviation"]] = updated
        print(f"{state['abbreviation']}: {updated['metrics']['action_count']} actions, "
              f"{updated['metrics']['federal_declaration_count']} federal declarations; "
              f"{updated['coverage']}")
    return [replaced.get(item["abbreviation"], item) for item in summaries]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DisasterData Plus state pages")
    parser.add_argument("--states", default="all", help="all or comma-separated names/abbreviations")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root; normally detected automatically",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--collect",
        action="store_true",
        help="run installed state source adapters before building pages",
    )
    parser.add_argument(
        "--join-storms",
        action="store_true",
        help="run an installed eo_storm_join.py after reading state actions",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return an error when a selected state has neither an adapter nor cached actions",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="do not retry states whose source failed or returned nothing",
    )
    args = parser.parse_args()
    if args.dry_run and args.join_storms:
        parser.error(
            "--dry-run and --join-storms cannot be combined: --dry-run "
            "promises to validate and report without writing, but the "
            "storm join always executes an external subprocess with real "
            "side effects (network requests, its own temp files) when it "
            "runs, and a successful run promotes real output files. Run "
            "--join-storms on its own, without --dry-run, instead."
        )

    all_states = load_manifest(args.manifest)
    selected = select_states(all_states, args.states)
    repo_root = args.repo_root.resolve()
    if args.join_storms or args.dry_run:
        problems = preflight_overrides(selected, repo_root)
        if problems:
            print("Stopping before collection: these hazard overrides would fail the storm join "
                  "and with it the whole build:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
    global NOAA_DATA_THROUGH
    NOAA_DATA_THROUGH = noaa_data_through(repo_root)
    if args.join_storms and not os.environ.get(NCEI_CACHE_ENV):
        # One folder for the whole run, so each yearly NOAA storm file is
        # downloaded and parsed once instead of once per state (see
        # NCEI_CACHE_ENV in eo_storm_join.py). Removed when the run ends.
        shared = tempfile.mkdtemp(prefix="plus_ncei_")
        os.environ[NCEI_CACHE_ENV] = shared
        atexit.register(shutil.rmtree, shared, True)
    print(f"Repository root: {repo_root}")
    print(f"Selected states: {', '.join(state['abbreviation'] for state in selected)}")
    if args.collect and not args.dry_run and any(state.get("fmcsa_supplement") for state in selected):
        try:
            print(fmcsa().refresh(repo_root, states={state["name"] for state in selected
                                                      if state.get("fmcsa_supplement")}))
        except Exception as exc:  # the saved entries are used instead
            print(f"WARNING: FMCSA state declarations not refreshed ({exc})", file=sys.stderr)

    summaries = []
    incomplete = []
    storm_failures = []
    for state in selected:
        summary = process_state(
            state, repo_root, args.collect, args.join_storms, args.dry_run
        )
        summaries.append(summary)
        if summary["metrics"]["action_count"] == 0 and state["adapter_status"] != "implemented":
            incomplete.append(state["abbreviation"])
        if summary.get("storm_pipeline_failed"):
            storm_failures.append(state["abbreviation"])
        print(
            f"{state['abbreviation']}: {summary['metrics']['action_count']} actions, "
            f"{summary['metrics']['federal_declaration_count']} federal declarations; "
            f"{summary['coverage']}"
        )

    if args.collect and not args.dry_run and not args.no_retry:
        summaries = retry_failed_sources(selected, summaries, repo_root, args.join_storms)
        storm_failures = [item["abbreviation"] for item in summaries
                          if item.get("storm_pipeline_failed")]

    if not args.dry_run and not storm_failures:
        plus_dir = repo_root / "plus"
        plus_dir.mkdir(parents=True, exist_ok=True)
        summary_path = plus_dir / "coverage.json"
        existing = []
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text(encoding="utf-8")).get("states", [])
            except (json.JSONDecodeError, OSError):
                existing = []
        merged = {item["abbreviation"]: item for item in existing}
        merged.update({item["abbreviation"]: item for item in summaries})
        ordered = [merged[state["abbreviation"]] for state in all_states if state["abbreviation"] in merged]
        write_json(
            summary_path,
            {"generated_on": date.today().isoformat(), "states": ordered},
        )
        (plus_dir / "index.html").write_text(
            render_landing(ordered, all_states), encoding="utf-8"
        )
    elif not args.dry_run and storm_failures:
        print(
            "Skipping coverage.json and plus/index.html rebuild: storm join "
            "failed for " + ", ".join(storm_failures) + ". The previous "
            "successful run's landing page and coverage summary are left "
            "untouched rather than being rebuilt from a run that had a "
            "failure in it.",
            file=sys.stderr,
        )

    if incomplete:
        print(
            "Coverage pending for: " + ", ".join(incomplete)
            + ". Pages were generated with explicit incomplete-coverage notices."
        )

    timed = sorted(
        ((item["abbreviation"], (item.get("timing") or {}).get("collect_seconds") or 0,
          (item.get("timing") or {}).get("storm_join_seconds") or 0) for item in summaries),
        key=lambda row: row[1] + row[2], reverse=True)
    recorded = any((item.get("timing") or {}).get(key) is not None for item in summaries
                   for key in ("collect_seconds", "storm_join_seconds"))
    if timed and recorded:
        print("TIME total: collect %.0fs, storm join %.0fs. Slowest: %s" % (
            sum(row[1] for row in timed), sum(row[2] for row in timed),
            ", ".join("%s %.0fs+%.0fs" % row for row in timed[:10])))

    kept_states = [
        "%s (%d)" % (item["abbreviation"], item["kept_saved_records"])
        for item in summaries if item.get("kept_saved_records")
    ]
    if kept_states:
        # One greppable line: these states' sources returned fewer records
        # than were already saved, so the saved ones were kept. Worth a look
        # at each state's scraper, but nothing was lost.
        print("WARNING kept saved records the state source did not return: "
              + ", ".join(kept_states))

    if storm_failures:
        print(
            "Storm join failed for: " + ", ".join(storm_failures)
            + ". Treated as a build failure regardless of --strict - a "
            "malformed hazard_category_override (inline or in a state's "
            "hazard_overrides.csv sidecar) must not be allowed to leave a "
            "build looking successful.",
            file=sys.stderr,
        )

    return 1 if (storm_failures or (args.strict and incomplete)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
