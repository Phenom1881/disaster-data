"""Mississippi adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MS"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Mississippi Governor Tate Reeves Newsroom and Media Archive (https://governorreeves.ms.gov/)",
    "structured_archive_coverage_start": "2020-01-14", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governorreeves.ms.gov/",
    "current_governor_source_start": "2020-01-14", "manual_only": False,
    "known_gaps": ["The current Governor site begins with the Reeves administration in January 2020; 2000-2019 is not represented in the delivered data."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ms_eo_scraper.py"), "--actions-out", str(workdir / "ms_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ms_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Mississippi adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "January 2020-present structured Governor archive; 2000-2019 gap disclosed"
