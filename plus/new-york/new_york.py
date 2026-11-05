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
    "page; plus 46 weather disaster orders added by hand: 9 Pataki orders "
    "(2000-2006), 1 Spitzer order (2007) and 5 Paterson orders (2008-2010) "
    "from 9 NYCRR Parts 5, 6 and 7, and 31 Cuomo orders, 26 of them "
    "(2011-2018) from 9 NYCRR Part 8 and 5 (2017-2020) from the New York "
    "State Register (manual_declarations.csv). Every federal declaration "
    "from 2011 on has a matching state order. No state order is kept yet "
    "for 13 federal declarations from 2000-2010: DR-1335, EM-3173, DR-1486, "
    "EM-3195, DR-1534, DR-1564, DR-1565 and DR-1670 (Pataki, 2000-2006; 9 "
    "NYCRR Part 5, read in full, has no disaster order for any of them); "
    "DR-1692, DR-1710 and DR-1724 (Spitzer, 2007); DR-1869 and DR-1957 "
    "(Paterson, 2009-2010). Four more match only by date, to orders for "
    "other storms: DR-1899 (the March 2010 nor'easter) to 9 NYCRR 7.37 "
    "(February 24-26, 2010), DR-1943 (the September 16, 2010 storms) to "
    "7.40 (September 29 to October 1, 2010), and DR-4031 and EM-3341 "
    "(Tropical Storm Lee, September 2011) to 8.17 (Hurricane Irene). 9 "
    "NYCRR Parts 6 and 7 have been read in part."
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
