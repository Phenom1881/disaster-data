"""Washington adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "WA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Washington Governor Proclamations (https://governor.wa.gov/office-governor/office/official-actions/proclamations)",
    "structured_archive_coverage_start": "2013-04-22", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.wa.gov/office-governor/office/official-actions/proclamations",
    "current_governor_source_start": "2025-01-15", "manual_only": False,
    "known_gaps": ["The live Governor proclamation table begins with Proclamation 13-02 on April 22, 2013; 2000 through April 21, 2013 is not exposed and is not backfilled from deeper archival holdings."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "wa_eo_scraper.py"), "--actions-out", str(workdir / "wa_emergency_actions_all.csv"), "--relationships-out", str(workdir / "wa_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Washington adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2013-present structured Governor proclamation archive; 2000-2012 unavailable"
