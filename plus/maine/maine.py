"""Maine adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "ME"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Maine Governor Mills Official Documents and Governor LePage Executive Orders Archive (https://www.maine.gov/governor/mills/official_documents)",
    "structured_archive_coverage_start": "2011-01-06", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.maine.gov/governor/mills/official_documents",
    "current_governor_source_start": "2019-01-02", "manual_only": False,
    "known_gaps": ["The Governor sources used cover the LePage and Mills administrations from 2011 onward; the Maine Legislature reports a broader historical collection, but pre-2011 records are outside this adapter's Governor-archive scope.", "Some LePage emergency records are preserved as HTML records without conventional executive-order numbers."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "me_eo_scraper.py"), "--actions-out", str(workdir / "me_emergency_actions_all.csv"), "--relationships-out", str(workdir / "me_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Maine adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2011-present Governor archives (LePage and Mills); pre-2011 historical backfill pending"
