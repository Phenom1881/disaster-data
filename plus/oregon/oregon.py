"""Oregon adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "OR"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Oregon Governor Executive Orders (https://www.oregon.gov/gov/Pages/executive-orders.aspx)",
    "structured_archive_coverage_start": "2003-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.oregon.gov/gov/Pages/executive-orders.aspx",
    "current_governor_source_start": "2023-01-09", "manual_only": False,
    "known_gaps": ["The Governor resource page states that the online executive-order archive begins in 2003, leaving 2000-2002 outside the live source.", "Some older PDFs are image-only or do not expose a machine-readable signature date and remain in the action inventory but are withheld from the join file until OCR/manual date review."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "or_eo_scraper.py"), "--actions-out", str(workdir / "or_emergency_actions_all.csv"), "--relationships-out", str(workdir / "or_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Oregon adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2003-present structured Governor archive; 2000-2002 unavailable in live source"
