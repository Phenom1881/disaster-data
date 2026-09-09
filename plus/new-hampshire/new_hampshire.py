"""New Hampshire adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NH"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Hampshire Secretary of State Executive Order Registry (https://www.sos.nh.gov/executive-orders)",
    "structured_archive_coverage_start": "1990-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.sos.nh.gov/executive-orders",
    "current_governor_source_start": "2025-01-09", "manual_only": False,
    "known_gaps": ["The historical Governor registry is now maintained by the Secretary of State; some clients are blocked by the registry's edge security.", "Many older PDFs are marked non-ADA archival documents and may require manual or OCR review when they contain no extractable text.", "The registry notes that EO 1990-06 was never received from the Governor's Office; 1990-05 and 1990-02 were not used."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nh_eo_scraper.py"), "--actions-out", str(workdir / "nh_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nh_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("New Hampshire adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "1990-present official Secretary of State registry; older non-ADA PDFs may require OCR"
