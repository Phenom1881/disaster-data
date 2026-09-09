"""Florida adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "FL"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Florida Governor Executive Orders (https://www.flgov.com/eog/news/executive-orders)",
    "structured_archive_coverage_start": "2020-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.flgov.com/eog/news/executive-orders",
    "current_governor_source_start": "2020-01-01", "manual_only": False,
    "known_gaps": ["The State Library's official year indexes reach back to 1971, but many older indexes expose only order numbers and scanned PDFs; a reliable pre-2020 hazard backfill requires PDF text extraction and OCR/manual review."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "fl_eo_scraper.py"), "--actions-out", str(workdir / "fl_emergency_actions_all.csv"), "--relationships-out", str(workdir / "fl_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Florida adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2020-present structured Governor archive; official State Library 1971-2019 OCR/manual backfill pending"
