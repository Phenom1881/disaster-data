"""Connecticut adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "CT"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Connecticut Governor Executive Orders (https://portal.ct.gov/governor/governors-actions/executive-orders)",
    "structured_archive_coverage_start": "1971-06-16", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://portal.ct.gov/governor/governors-actions/executive-orders",
    "current_governor_source_start": "2019-01-09", "manual_only": False,
    "known_gaps": ["The public executive-order archive reaches 1971 but is not represented as a guaranteed complete historical series.", "The DEMHS civil-preparedness declaration table currently spans 2005-2020 and may omit newer unnumbered declarations.", "Some older PDFs may require OCR."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ct_eo_scraper.py"), "--actions-out", str(workdir / "ct_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ct_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Connecticut adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "1971-present Governor executive-order archive plus 2005-2020 DEMHS civil-preparedness declaration table"
