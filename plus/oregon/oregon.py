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
    "pdf_text_available": False, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.oregon.gov/gov/Pages/executive-orders.aspx",
    "current_governor_source_start": "2023-01-09", "manual_only": False,
    "known_gaps": ["The Governor resource page states that the online executive-order archive begins in 2003, leaving 2000-2002 outside the live source.", "The order PDFs are scans with no text layer, so signing dates are read from the scanned order with OCR. A declaration whose date OCR cannot read stays in the join file with a blank date (no storm search) and is listed in manual_or_ocr_review.csv."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "or_eo_scraper.py"), "--actions-out", str(workdir / "or_emergency_actions_all.csv"), "--relationships-out", str(workdir / "or_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv"), "--review-out", str(workdir / "manual_or_ocr_review.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        last = (result.stderr.strip().splitlines() or ["no error output"])[-1][:200]
        raise RuntimeError(f"Oregon adapter: scrape failed ({last})")
    return workdir / "declarations_for_join.csv", "2003-present structured Governor archive; 2000-2002 unavailable in live source"
