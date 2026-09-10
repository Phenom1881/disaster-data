"""Texas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "TX"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Office of the Texas Governor Proclamation Archive (https://gov.texas.gov/news/category/proclamation)",
    "structured_archive_coverage_start": "2015-01-20", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://gov.texas.gov/news/category/proclamation",
    "current_governor_source_start": "2015-01-20", "manual_only": False,
    "known_gaps": ["The current Governor proclamation archive covers the Abbott administration beginning January 2015; 2000-2014 is not present and was not backfilled from historical holdings."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "tx_eo_scraper.py"), "--actions-out", str(workdir / "tx_emergency_actions_all.csv"), "--relationships-out", str(workdir / "tx_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Texas adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2015-present current-Governor proclamation archive; 2000-2014 gap disclosed"
