"""Maryland adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MD"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Maryland Governor Executive Orders Archive (https://governor.maryland.gov/official-actions/executive-orders)",
    "structured_archive_coverage_start": "2023-01-19", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.maryland.gov/official-actions/executive-orders",
    "current_governor_source_start": "2023-01-18", "manual_only": False,
    "known_gaps": ["The Governor archive is continuous for the Moore administration from January 2023; three isolated 2007/2012 records appear after that sequence but do not constitute comprehensive earlier coverage."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "md_eo_scraper.py"), "--actions-out", str(workdir / "md_emergency_actions_all.csv"), "--relationships-out", str(workdir / "md_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Maryland adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2023-present structured Governor archive; three isolated 2007/2012 records are not continuous older coverage"
