"""Rhode Island adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "RI"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Rhode Island Governor Executive Order Archive (https://governor.ri.gov/executive-order-archive)",
    "structured_archive_coverage_start": "2015-01-06", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.ri.gov/executive-order-archive",
    "current_governor_source_start": "2021-03-02", "manual_only": False,
    "known_gaps": ["The Governor's web archive begins in 2015; the Rhode Island State Library reports holdings back to 1973, but those older records are not exposed through this structured page."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ri_eo_scraper.py"), "--actions-out", str(workdir / "ri_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ri_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Rhode Island adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2015-present structured Governor archive; State Library 1973-2014 backfill pending"
