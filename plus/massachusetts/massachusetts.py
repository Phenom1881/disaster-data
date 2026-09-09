"""Massachusetts adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "State Library of Massachusetts Executive Orders (https://archives.lib.state.ma.us/entities/aggregation/db64a731-fbc5-4ed7-ac61-5330b8b8e5ae)",
    "structured_archive_coverage_start": "1941-12-29", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.mass.gov/massachusetts-executive-orders",
    "current_governor_source_start": "2023-01-05", "manual_only": False,
    "known_gaps": ["Unnumbered emergency proclamations outside the executive-order collection are not systematically indexed by a single official archive.", "Mass.gov rejects routine non-browser requests; collection uses the State Library's official DSpace API."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ma_eo_scraper.py"), "--actions-out", str(workdir / "ma_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ma_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Massachusetts adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "1941-present official State Library executive-order collection; unnumbered proclamation backfill pending"
