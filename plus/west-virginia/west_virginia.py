"""West Virginia adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "WV"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "West Virginia Governor News Archive (https://governor.wv.gov/allnews/all)",
    "structured_archive_coverage_start": "2025-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.wv.gov/allnews/all",
    "current_governor_source_start": "2025-01-13", "manual_only": False,
    "known_gaps": ["Emergency declarations are Governor proclamations indexed in the news archive rather than the separate Executive Orders page; the package supplements the January 5, 2025 transition-period storm declaration from a later official Governor article that expressly identifies it, while earlier proclamations still require backfill."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "wv_eo_scraper.py"), "--actions-out", str(workdir / "wv_emergency_actions_all.csv"), "--relationships-out", str(workdir / "wv_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("West Virginia adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2025-present Governor news archive; pre-2025 emergency proclamations backfill pending"
