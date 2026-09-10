"""Nevada adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NV"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Nevada Governor Executive Actions (https://www.gov.nv.gov/executive-actions/)",
    "structured_archive_coverage_start": "2023-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.gov.nv.gov/executive-actions/",
    "current_governor_source_start": "2023-01-02", "manual_only": False,
    "known_gaps": ["The current Governor's web archive begins in 2023; 2000-2022 is outside the delivered coverage. Emergency orders are a separate official collection and are included."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nv_eo_scraper.py"), "--actions-out", str(workdir / "nv_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nv_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Nevada adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2023-present current-Governor executive and emergency-order archives; 2000-2022 gap disclosed"
