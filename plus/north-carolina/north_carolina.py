"""North Carolina adapter for the DisasterData Plus state-evidence pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STATE = "NC"

CAPABILITIES = {
    "state": STATE,
    "structured_archive_available": True,
    "structured_archive_source": (
        "North Carolina Governor Executive Orders "
        "(https://governor.nc.gov/news/executive-orders)"
    ),
    "structured_archive_coverage_start": "2017-01-06",
    "structured_archive_coverage_end": None,
    "pdf_text_available": False,
    "ocr_required": True,
    "current_governor_source_available": True,
    "current_governor_source": "https://governor.nc.gov/news/executive-orders",
    "current_governor_source_start": "2025-01-01",
    "manual_only": False,
    "known_gaps": [
        "The Governor's structured web collection begins with Roy Cooper's first orders in January 2017 and continues through the current Stein administration.",
        "Pre-2017 executive orders are published in the North Carolina Register but require a separate issue-indexed historical adapter; they are not included in the current completeness claim.",
        "The archive mixes orders with Council of State concurrence records, FAQs, guidance, and Spanish duplicates. These are excluded as independent actions and retained as supporting URLs when they can be matched to a canonical order.",
        "PDF text quality is mixed. Some current detail pages reproduce complete selectable text, while some PDFs and older detail pages require OCR for full-text relationship extraction.",
    ],
    "notes": (
        "The scraper produces nc_emergency_actions_all.csv, "
        "nc_order_relationships.csv, and a Virginia-compatible "
        "declarations_for_join.csv. Governor names are part of stable IDs because "
        "North Carolina restarts executive-order numbering with each administration. "
        "Only original weather-related declarations enter the storm join; supporting "
        "documents, administrative actions, amendments, extensions, and terminations "
        "remain in the full action output."
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
    actions_out = workdir / "nc_emergency_actions_all.csv"
    relationships_out = workdir / "nc_order_relationships.csv"
    join_out = workdir / "declarations_for_join.csv"
    scraper = scripts_dir / "nc_eo_scraper.py"
    print("North Carolina adapter: collecting official Executive Orders...")
    ok = _run([
        sys.executable, str(scraper), "--actions-out", str(actions_out),
        "--relationships-out", str(relationships_out), "--join-out", str(join_out),
    ], workdir)
    if not ok or not join_out.exists():
        raise RuntimeError("North Carolina adapter: scrape failed; review nc_eo_scraper.py output for the failing source.")
    coverage = "2017-01-06-present structured Governor archive; North Carolina Register backfill pending"
    print("North Carolina adapter: coverage = " + coverage)
    return join_out, coverage


if __name__ == "__main__":
    parser = __import__("argparse").ArgumentParser(description="Run the North Carolina state-evidence adapter standalone")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    output, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(output))
    print("Coverage: " + coverage)
