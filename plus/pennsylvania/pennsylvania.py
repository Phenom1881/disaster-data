"""Pennsylvania adapter for the DisasterData Plus state-evidence pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STATE = "PA"

COVERAGE_NOTE = (
    "2000-present: PEMA's linked proclamation history from 2018, plus 2001-2017 storm "
    "disaster proclamations (Ridge, Rendell, Corbett and Wolf) added by hand from the "
    "Pennsylvania Bulletin, PEMA records and press coverage; no dated proclamation has "
    "been found yet for November 2006, April 2011 or summer 2013 (DR-1684, DR-4003, "
    "DR-4149), and the August 2004 storms (DR-1538) match only through the September 2004"
    " Frances proclamation"
)

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
        "2001-2017 storm proclamations are added by hand in manual_declarations.csv. pacodeandbulletin.gov disallows all automated agents in robots.txt, so 2001-2010 dates come from the Pennsylvania Bulletin issues hosted by Villanova Law's digital repository and from PEMA's archived proclamation files. PEMA's 2009 disaster history lists Governor's proclamations in August 2004 and November 2006 whose signing days have not been found; none has been found for April 2011 or June-July 2013. DR-1538 (August 2004) counts as matched only because its incident period falls within the match window of the September 15, 2004 Frances proclamation.",
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
    coverage = COVERAGE_NOTE
    print("Pennsylvania adapter: coverage = " + coverage)
    return join_out, coverage


if __name__ == "__main__":
    parser = __import__("argparse").ArgumentParser(description="Run the Pennsylvania state-evidence adapter standalone")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    output, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(output))
    print("Coverage: " + coverage)
