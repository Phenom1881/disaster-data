"""New York adapter for the DisasterData Plus state-evidence pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STATE = "NY"

# Kept identical to scripts/plus/state-manifest.json; test_ny_manual_declarations checks it.
COVERAGE_NOTE = (
    "2000-present: comprehensive Governor archive from August 24, 2021, and "
    "selected earlier orders still in force from the Past Executive Orders "
    "page; plus 12 weather disaster orders added by hand: 7 Pataki orders "
    "(2000-2006) from 9 NYCRR Part 5 and 5 Cuomo orders (2017-2020) from "
    "the New York State Register (manual_declarations.csv). Every federal "
    "declaration from 2017 on has a matching state order. No state order is "
    "kept yet for 29 federal declarations from 2000-2014: DR-1335, EM-3173, "
    "DR-1486, EM-3195, DR-1534, DR-1564, DR-1565 and DR-1670 (Pataki, "
    "2000-2006); EM-3273, DR-1692, DR-1710 and DR-1724 (Spitzer, 2007); "
    "DR-1827, EM-3299, DR-1857, DR-1869, DR-1899, DR-1943 and DR-1957 "
    "(Paterson, 2008-2010); DR-1993, EM-3328, DR-4020, DR-4031, EM-3341, "
    "DR-4085, EM-3351, DR-4111, DR-4180 and DR-4204 (Cuomo, 2011-2014). The "
    "Spitzer, Paterson and 2011-2014 Cuomo orders are printed in 9 NYCRR "
    "Parts 6-8, which could not be read for this update."
)

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
