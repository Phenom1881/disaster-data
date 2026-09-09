"""Vermont adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "VT"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Vermont Governor Phil Scott Executive Orders Archive (https://governor.vermont.gov/document-types/executive-orders)",
    "structured_archive_coverage_start": "2017-01-05", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.vermont.gov/document-types/executive-orders",
    "current_governor_source_start": "2017-01-05", "manual_only": False,
    "known_gaps": ["The Governor archive covers the Phil Scott administration from 2017 onward; it links prior administrations to the statutory appendix rather than preserving them in this structured Governor archive."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "vt_eo_scraper.py"), "--actions-out", str(workdir / "vt_emergency_actions_all.csv"), "--relationships-out", str(workdir / "vt_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Vermont adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2017-present structured Governor archive; pre-2017 statutory-appendix backfill pending"
