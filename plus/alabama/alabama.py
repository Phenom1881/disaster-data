"""Alabama adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AL"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Alabama Governor State of Emergency Archive (https://governor.alabama.gov/newsroom/category/state-of-emergency/)",
    "structured_archive_coverage_start": "2017-04-12", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.alabama.gov/newsroom/category/state-of-emergency/",
    "current_governor_source_start": "2017-04-10", "manual_only": False,
    "known_gaps": ["The current Governor newsroom begins in April 2017; 2000-April 2017 is not represented in the delivered data."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "al_eo_scraper.py"), "--actions-out", str(workdir / "al_emergency_actions_all.csv"), "--relationships-out", str(workdir / "al_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Alabama adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "April 2017-present structured Governor archive; 2000-April 2017 gap disclosed"
