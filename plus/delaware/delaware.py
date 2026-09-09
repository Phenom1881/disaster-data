"""Delaware adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "DE"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Delaware Governor State of Emergency Archive (https://governor.delaware.gov/state-of-emergency/)",
    "structured_archive_coverage_start": "2025-10-29", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.delaware.gov/state-of-emergency/",
    "current_governor_source_start": "2025-10-29", "manual_only": False,
    "known_gaps": ["The dedicated Governor State of Emergency archive begins October 29, 2025; earlier administrations' emergency declarations are not exposed through this structured page and require backfill."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "de_eo_scraper.py"), "--actions-out", str(workdir / "de_emergency_actions_all.csv"), "--relationships-out", str(workdir / "de_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Delaware adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "October 2025-present structured Governor declaration archive; earlier emergency declarations backfill pending"
