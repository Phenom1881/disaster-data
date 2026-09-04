"""
state-evidence/adapters/virginia.py

Virginia adapter for the state-evidence pipeline.

Declares this state's data-collection capabilities (CAPABILITIES, below) and
exposes collect(workdir) -> (path, coverage_note), which orchestrates the two
existing, independently-tested Virginia scrapers and returns the path to a
single merged CSV of weather emergency declarations, ready for
eo_storm_join.py.

Design choice: this adapter runs the two scrapers as SUBPROCESSES rather than
importing their internals. Both scripts are already tested and working
standalone; reusing them unchanged (instead of refactoring their logic into
shared importable functions) keeps this adapter from introducing new bugs
into code that already works, and matches the rest of this codebase's own
convention of decoupled scripts communicating through files on disk (see
gen_state_pages.py's own docstring: "deliberately decoupled... run it as one
extra step").

Loading note: this file lives under a hyphenated directory (state-evidence),
so it is not meant to be imported as a dotted Python package
(import state_evidence.adapters.virginia would fail on the hyphen).
build_state_evidence.py should load it either by running it as a subprocess
(as va_eo_scraper.py/va_historical_eo_scraper.py already are), or via
importlib.util.spec_from_file_location, which loads a module from an
explicit file path and does not care about the folder name.

This adapter is unusually well covered and is NOT the template every future
state adapter must match:
  - va_eo_scraper.py covers the CURRENT administration (Jan 2026-present) by
    scraping governor.virginia.gov directly.
  - va_historical_eo_scraper.py covers six COMPLETED administrations
    (2002-2026) via the Library of Virginia's Primo metadata API, no OCR
    needed since that archive exposes structured titles/dates directly.
A state with no equivalent metadata archive, or one whose historical orders
exist only as scanned image PDFs, needs a different adapter shape entirely;
CAPABILITIES exists so build_state_evidence.py can tell the difference at run
time instead of assuming every state looks like Virginia.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STATE = "VA"

CAPABILITIES = {
    "state": STATE,
    "structured_archive_available": True,
    "structured_archive_source": "Library of Virginia Primo API (lva.primo.exlibrisgroup.com)",
    "structured_archive_coverage_start": "2002-01-17",   # Warner inauguration
    "structured_archive_coverage_end": None,              # ongoing, updated per administration
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.governor.virginia.gov/executive-actions/",
    "current_governor_source_start": "2026-01-17",         # Spanberger inauguration
    "manual_only": False,
    "known_gaps": [
        "Gilmore administration, 2000-2002, not covered by the LVA collection",
    ],
    "notes": (
        "Virginia has unusually complete coverage: a structured historical "
        "archive plus a scrapeable current-governor source, so both scrapers "
        "here run automatically with no manual collection step required."
    ),
}


def _run(cmd, cwd):
    print("  running: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def collect(workdir=".", scripts_dir=None):
    """Run both Virginia scrapers and return (path, coverage_note) for the
    merged CSV of weather emergency declarations, ready for eo_storm_join.py.

    Degrades rather than fails outright if the historical scrape breaks: a
    current-only declarations file is still usable, just missing 2002-2026.
    Callers must check the returned coverage note, not just assume the path
    means full coverage.
    """
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)

    current_join = workdir / "declarations_for_join.csv"
    merged_join = workdir / "declarations_for_join_2002_present.csv"

    print("Virginia adapter: collecting current-administration declarations...")
    current_ok = _run(
        [
            sys.executable, str(scripts_dir / "va_eo_scraper.py"),
            "--raw-out", str(workdir / "va_all_orders_raw.csv"),
            "--all-out", str(workdir / "va_emergency_declarations_all.csv"),
            "--join-out", str(current_join),
        ],
        cwd=workdir,
    )
    if not current_ok:
        print("  WARNING: current-administration scrape failed; historical-only "
              "coverage will be used if available.", file=sys.stderr)

    print("Virginia adapter: collecting historical declarations (2002-2026)...")
    hist_cmd = [
        sys.executable, str(scripts_dir / "va_historical_eo_scraper.py"),
        "--all-out", str(workdir / "va_eo_archive_all.csv"),
        "--emergency-out", str(workdir / "va_emergency_actions_2002_2026.csv"),
        "--weather-out", str(workdir / "va_weather_emergency_actions_2002_2026.csv"),
        "--join-out", str(merged_join),
    ]
    if current_ok and current_join.exists():
        hist_cmd += ["--current-csv", str(current_join)]
    hist_ok = _run(hist_cmd, cwd=workdir)

    if hist_ok and merged_join.exists():
        coverage = "2002-present" if current_ok else "2002-2026 (current administration missing)"
        result_path = merged_join
    elif current_ok and current_join.exists():
        coverage = "current administration only (2026-present); historical scrape failed"
        result_path = current_join
    else:
        raise RuntimeError(
            "Virginia adapter: both the current and historical scrapes failed; "
            "no declarations collected."
        )

    print("Virginia adapter: coverage = " + coverage)
    return result_path, coverage


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Virginia state-evidence adapter standalone")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    path, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(path))
    print("Coverage: " + coverage)
