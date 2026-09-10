"""Wisconsin adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "WI"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Wisconsin Governor Executive Orders (https://evers.wi.gov/pages/newsroom/executive-orders.aspx)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://evers.wi.gov/pages/newsroom/executive-orders.aspx",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The current Governor archive covers the Evers administration only, so the requested 2000-2018 period is not populated.", "Several early PDFs are image-only and need OCR for body-text review, although the structured archive exposes their titles and dates."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "wi_eo_scraper.py"), "--actions-out", str(workdir / "wi_emergency_actions_all.csv"), "--relationships-out", str(workdir / "wi_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Wisconsin adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2019-present structured Governor archive; 2000-2018 not covered; early PDFs may require OCR"
