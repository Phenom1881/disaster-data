"""Louisiana adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "LA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Louisiana Division of Administration, Office of State Register Executive Orders (https://www.doa.la.gov/doa/osr/executive-orders/)",
    "structured_archive_coverage_start": "2016-01-11", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.doa.la.gov/doa/osr/executive-orders/",
    "current_governor_source_start": "2024-01-08", "manual_only": False,
    "known_gaps": ["The official web indexes begin with the Edwards administration in January 2016; 2000-2015 is outside the delivered web coverage. Older certified records may be requested from the Secretary of State as a future backfill."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "la_eo_scraper.py"), "--actions-out", str(workdir / "la_emergency_actions_all.csv"), "--relationships-out", str(workdir / "la_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Louisiana adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2016-present official State Register web indexes; 2000-2015 gap disclosed"
