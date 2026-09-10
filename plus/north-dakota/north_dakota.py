"""
North Dakota adapter wrapper for scripts/build-plus.py.

Exposes STATE, CAPABILITIES, and collect() per the Plus adapter contract.
"""
import subprocess
import sys
from pathlib import Path

STATE = "ND"

CAPABILITIES = {
    "structured_archive_coverage_start": "2017-02-15",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.governor.nd.gov/executive-orders",
    "current_governor_source_start": "2024-01-11",
    "manual_only": False,
    "known_gaps": [
        "governor.nd.gov's Executive Order Archive gives order numbers "
        "alongside dates only from 2017 (Burgum) forward; 2000-2016 entries "
        "(Dalrymple and earlier) are listed as date+title only, with no "
        "order number in the rendered page - the archive itself goes back "
        "to 1963, but numbered/dated coverage for join purposes starts 2017.",
        "The live /executive-orders page (2024-present) lists order number, "
        "title, and a PDF link, but NO filed date - only the archive page "
        "(which stops covering current-administration orders after 2023) "
        "carries dates directly. Dates for 2024-2026 orders were confirmed "
        "one at a time against governor's-office news releases where found "
        "(2025-05, 2026-03 confirmed this pass); undated entries are "
        "deliberately excluded from declarations_for_join.csv rather than "
        "guessed - see REVIEW_NOTES.md for the full excluded list.",
        "ND uses 'declares a state of emergency' language for both weather "
        "disasters and non-weather orders (civil disturbance, interstate "
        "Guard deployments) - EXCLUDE_IDS in nd_eo_scraper.py hard-excludes "
        "confirmed non-weather IDs found during this pass (2020-34, 2023-07); "
        "any newly-scraped 'emergency' title should be spot-checked against "
        "its news release before being trusted, not assumed weather-related.",
    ],
}


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(scripts_dir / "nd_eo_scraper.py"),
        "--actions-out", str(workdir / "nd_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "nd_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("North Dakota adapter: scrape failed")

    return workdir / "declarations_for_join.csv", (
        "2017-present numbered/dated Governor archive plus current-EOs page "
        "(dates confirmed per-order against news releases); 2000-2016 order "
        "numbers and undated 2024-2026 orders backfill pending"
    )
