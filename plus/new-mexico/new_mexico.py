"""New Mexico adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NM"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Mexico Governor Executive Orders Archive (https://www.governor.state.nm.us/about-the-governor/executive-orders/executive-orders-archive/)",
    "structured_archive_coverage_start": "2019-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.governor.state.nm.us/about-the-governor/executive-orders/",
    "current_governor_source_start": "2019-01-01", "manual_only": False,
    "known_gaps": ["The current Governor's web archive begins in 2019; 2000-2018 is outside the delivered web coverage. Most posted PDFs are image-only and remain explicitly unclassified pending OCR."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nm_eo_scraper.py"), "--actions-out", str(workdir / "nm_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nm_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("New Mexico adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2019-present structured current-Governor archive; 2000-2018 gap disclosed"
