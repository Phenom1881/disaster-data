"""Rhode Island adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "RI"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the Governor's executive order archive from 2015, plus 2005-2013 storm "
    "declarations (Carcieri and Chafee) from the Governor's press releases on ri.gov and "
    "FMCSA's copy of Executive Order 13-02; Almond's and Carcieri's other orders are in the "
    'State Archives only as scans not yet read, so declarations for the February 2003 '
    "snowstorm, the April 2007 nor'easter and the March 2010 floods are not listed"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Rhode Island Governor Executive Order Archive (https://governor.ri.gov/executive-order-archive)",
    "structured_archive_coverage_start": "2015-01-06", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.ri.gov/executive-order-archive",
    "current_governor_source_start": "2021-03-02", "manual_only": False,
    "known_gaps": ["The Governor's web archive begins in 2015. 2005-2013 storm declarations are added by hand from ri.gov press releases and FMCSA (manual_declarations.csv).", "The State Archives' digital archive holds every Governor's executive orders by year (https://sosri.access.preservica.com/index.php?name=SO_6e66d4ba-687b-4a0d-85da-983ebcb11507), but as scanned PDFs with no text or signing date in the catalog. Executive Order 06, 2010 is filed as 06_disaster_emergency, followed by three supplemental orders; it has not been read, so its date is unknown. Until the scans are read, FEMA's EM-3182 (February 2003), DR-1704 (April 2007) and DR-1894 and EM-3311 (March 2010) show with no state declaration."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ri_eo_scraper.py"), "--actions-out", str(workdir / "ri_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ri_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Rhode Island adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
