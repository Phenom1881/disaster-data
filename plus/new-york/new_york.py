"""New York adapter for the DisasterData Plus state-evidence pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STATE = "NY"

CAPABILITIES = {
    "state": STATE,
    "structured_archive_available": True,
    "structured_archive_source": (
        "New York Governor Executive Orders "
        "(https://www.governor.ny.gov/executiveorders)"
    ),
    "structured_archive_coverage_start": "2021-08-24",
    "structured_archive_coverage_end": None,
    "pdf_text_available": False,
    "ocr_required": True,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.governor.ny.gov/executiveorders",
    "current_governor_source_start": "2021-08-24",
    "manual_only": False,
    "known_gaps": [
        "The current Governor archive is treated as comprehensive beginning "
        "with Kathy Hochul on August 24, 2021.",
        "The official Past Executive Orders page is not a complete historical "
        "archive. It lists selected orders from prior governors that remain "
        "in effect; those rows are retained with source_scope=selected_prior "
        "and must not be interpreted as complete historical coverage.",
        "Archived governor websites and 9 NYCRR may contain additional historical "
        "orders, but they require separate adapters and completeness validation.",
        "Decimal order numbers identify extensions or modifications. The scraper "
        "preserves the full decimal identifier and creates a relationship to its "
        "base order, but cross-administration relationships are not resolved "
        "automatically.",
        "Many linked PDFs, across both current and historical eras, are image-only. "
        "Current Hochul detail pages provide complete selectable HTML and are used "
        "instead. Full-text processing of selected prior orders requires OCR.",
    ],
    "notes": (
        "The scraper produces ny_emergency_actions_all.csv, "
        "ny_order_relationships.csv, and a Virginia-compatible "
        "declarations_for_join.csv. Generic disaster emergencies are not "
        "automatically treated as weather events; an explicit weather hazard "
        "term must be present. Current document text comes from each order's "
        "official HTML detail page because PDF text availability is inconsistent. "
        "Extensions, amendments, and terminations are "
        "excluded from the storm join file but retained in the full action and "
        "relationship outputs."
    ),
}


def _run(command: list[str], cwd: Path) -> bool:
    print("  running: " + " ".join(command))
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0 and result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)

    actions_out = workdir / "ny_emergency_actions_all.csv"
    relationships_out = workdir / "ny_order_relationships.csv"
    join_out = workdir / "declarations_for_join.csv"
    scraper = scripts_dir / "ny_eo_scraper.py"

    print("New York adapter: collecting executive orders...")
    ok = _run(
        [
            sys.executable,
            str(scraper),
            "--actions-out",
            str(actions_out),
            "--relationships-out",
            str(relationships_out),
            "--join-out",
            str(join_out),
        ],
        workdir,
    )
    if not ok or not join_out.exists():
        raise RuntimeError(
            "New York adapter: scrape failed; no declarations were collected. "
            "Review ny_eo_scraper.py output for the failing source."
        )

    coverage = (
        "2021-08-24-present comprehensive current archive; earlier official "
        "records are selected continuing orders only and are explicitly labeled"
    )
    print("New York adapter: coverage = " + coverage)
    return join_out, coverage


if __name__ == "__main__":
    parser = __import__("argparse").ArgumentParser(
        description="Run the New York state-evidence adapter standalone"
    )
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    output, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(output))
    print("Coverage: " + coverage)
