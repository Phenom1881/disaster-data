"""California adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "CA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "California Governor website search and proclamation records (https://www.gov.ca.gov/?s=state+of+emergency)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.gov.ca.gov/?s=state+of+emergency",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The live Governor site is a Newsom-administration publication archive; the requested 2000-2018 period is not exposed there and is not backfilled from prior-governor archives."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ca_eo_scraper.py"), "--actions-out", str(workdir / "ca_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ca_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("California adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2019-present current Governor publication archive; 2000-2018 not exposed"
