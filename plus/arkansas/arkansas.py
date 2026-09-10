"""Arkansas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AR"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Arkansas Governor Executive Orders (https://governor.arkansas.gov/executive-orders/)",
    "structured_archive_coverage_start": "2023-01-10", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.arkansas.gov/executive-orders/",
    "current_governor_source_start": "2023-01-10", "manual_only": False,
    "known_gaps": ["The current Governor website/API begins with the Sanders administration in January 2023; 2000-2022 is not present. State Library holdings are a possible future backfill and were not used."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ar_eo_scraper.py"), "--actions-out", str(workdir / "ar_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ar_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Arkansas adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2023-present structured current-Governor archive; 2000-2022 gap disclosed"
