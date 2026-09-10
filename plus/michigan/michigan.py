"""Michigan adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MI"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Michigan Governor State Orders and Directives (https://www.michigan.gov/whitmer/news/state-orders-and-directives)",
    "structured_archive_coverage_start": "2019-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.michigan.gov/whitmer/news/state-orders-and-directives",
    "current_governor_source_start": "2019-01-01", "manual_only": False,
    "known_gaps": ["The current Governor archive covers the Whitmer administration only, so the requested 2000-2018 period is not populated; older official holdings are a future backfill candidate outside this batch."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "mi_eo_scraper.py"), "--actions-out", str(workdir / "mi_emergency_actions_all.csv"), "--relationships-out", str(workdir / "mi_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Michigan adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2019-present structured Governor archive; 2000-2018 not covered by the current Governor source"
