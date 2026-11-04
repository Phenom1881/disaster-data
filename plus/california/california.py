"""California adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "CA"
COVERAGE_NOTE = (
    "2011-present: the current Governor archive from January 2019, plus the Brown administration's 2011-2"
    "018 weather states of emergency from its archived proclamations (archive.gov.ca.gov/archive/gov39), "
    "added by hand (manual_declarations.csv); declarations under Governors Davis and Schwarzenegger (2000"
    "-2010) are not added yet, so 2000-2010 is not compared"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "California Governor website search and proclamation records (https://www.gov.ca.gov/?s=state+of+emergency)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.gov.ca.gov/?s=state+of+emergency",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The live Governor site is a Newsom-administration publication archive that begins in January 2019.",
                   "The Brown administration's 2011-2018 weather states of emergency are added by hand in manual_declarations.csv from its archived proclamations (archive.gov.ca.gov/archive/gov39), one row per original proclamation. Proclamations that only add counties to an earlier one, requests to the President, and non-weather emergencies (earthquakes, the 2011 tsunami, oil spills, tanker crashes, the 2015 San Bernardino attack, hepatitis A, the fiscal emergency) are left out.",
                   "Declarations under Governors Davis and Schwarzenegger (2000-2010) are not added yet, so the page compares from 2011."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ca_eo_scraper.py"), "--actions-out", str(workdir / "ca_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ca_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("California adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
