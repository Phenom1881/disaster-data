"""Delaware adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "DE"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the Governor's state of emergency archive from October 2025, plus "
    "earlier storm states of emergency added by hand from the Governor's news releases "
    "(news.delaware.gov) and dated news coverage, and Minner's 2002 drought order from "
    'the Delaware Public Archives; no state declaration has been found for the February '
    '2003 snowstorm (EM-3183), the 2004 and 2006 floods (DR-1572, DR-1654) or Ida in 2021'
    ' (DR-4627), and the date of the Hurricane Isabel declaration is taken from news '
    'coverage'
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Delaware Governor State of Emergency Archive (https://governor.delaware.gov/state-of-emergency/)",
    "structured_archive_coverage_start": "2025-10-29", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.delaware.gov/state-of-emergency/",
    "current_governor_source_start": "2025-10-29", "manual_only": False,
    "known_gaps": ["The dedicated Governor State of Emergency archive begins October 29, 2025; earlier administrations' emergency declarations are not exposed through this structured page.", "Pre-2025 storm declarations are added by hand in manual_declarations.csv. Minner's states of emergency were not issued as numbered executive orders (the Delaware Public Archives list of her orders has none for storms), and the February 2010 archive on news.delaware.gov holds only Department of Justice releases, so 2001-2010 relies on dated news coverage. No state declaration was found for the February 2003 snowstorm (EM-3183), Tropical Storm Henri's flooding of September 15, 2003 (DR-1494; the Isabel declaration three days later falls in its comparison window), the September 2004 Jeanne flooding (DR-1572), the June 2006 flooding (DR-1654) or Ida (DR-4627, 2021). For February 2010 only the second declaration (effective February 10) was found, and a January 2015 storm declaration could not be confirmed."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "de_eo_scraper.py"), "--actions-out", str(workdir / "de_emergency_actions_all.csv"), "--relationships-out", str(workdir / "de_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Delaware adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
