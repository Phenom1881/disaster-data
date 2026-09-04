"""Pennsylvania adapter for the DisasterData Plus state-evidence pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STATE = "PA"

CAPABILITIES = {
    "state": STATE,
    "structured_archive_available": True,
    "structured_archive_source": (
        "Pennsylvania Emergency Management Agency Emergency Proclamations "
        "(https://www.pa.gov/agencies/pema/resources/emergency-proclamations)"
    ),
    "structured_archive_coverage_start": "2018-01-10",
    "structured_archive_coverage_end": None,
    "pdf_text_available": False,
    "ocr_required": True,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.pa.gov/agencies/pema/resources/emergency-proclamations",
    "current_governor_source_start": "2023-01-17",
    "manual_only": False,
    "known_gaps": [
        "PEMA's linked emergency-proclamation history provides web-page coverage from 2018 forward. Older proclamations published through the Pennsylvania Bulletin require a separate historical backfill.",
        "The Office of Administration policy search currently exposes Executive Order issuances back to the 1970s, but it is a maintained policy index rather than a complete historical archive. Revised or rescinded entries may replace original versions.",
        "Some amendment dates are listed on the PEMA page without linked documents. The scraper records only official linked artifacts and does not manufacture rows for unlinked dates.",
        "Pennsylvania proclamation PDFs have mixed text quality. Some are selectable, while others are image-only; complete full-text coverage therefore requires OCR.",
    ],
    "notes": (
        "The scraper combines two separately labeled official scopes and produces "
        "pa_emergency_actions_all.csv, pa_order_relationships.csv, and a "
        "Virginia-compatible declarations_for_join.csv. Only original, explicitly "
        "weather-related PEMA proclamations enter the join file. Administrative "
        "Executive Orders and later amendments, extensions, or terminations remain "
        "in the full action output."
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
    actions_out = workdir / "pa_emergency_actions_all.csv"
    relationships_out = workdir / "pa_order_relationships.csv"
    join_out = workdir / "declarations_for_join.csv"
    scraper = scripts_dir / "pa_eo_scraper.py"
    print("Pennsylvania adapter: collecting official state actions...")
    ok = _run([
        sys.executable, str(scraper), "--actions-out", str(actions_out),
        "--relationships-out", str(relationships_out), "--join-out", str(join_out),
    ], workdir)
    if not ok or not join_out.exists():
        raise RuntimeError("Pennsylvania adapter: scrape failed; review pa_eo_scraper.py output for the failing source.")
    coverage = "2018-present linked PEMA proclamation history; older Pennsylvania Bulletin backfill pending"
    print("Pennsylvania adapter: coverage = " + coverage)
    return join_out, coverage


if __name__ == "__main__":
    parser = __import__("argparse").ArgumentParser(description="Run the Pennsylvania state-evidence adapter standalone")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    output, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(output))
    print("Coverage: " + coverage)
