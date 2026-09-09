"""Georgia adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "GA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Georgia Governor Executive Order Archives (https://gov.georgia.gov/executive-action/executive-orders/executive-order-archives)",
    "structured_archive_coverage_start": "2011-01-10", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://gov.georgia.gov/executive-action/executive-orders/executive-order-archives",
    "current_governor_source_start": "2019-01-14", "manual_only": False,
    "known_gaps": ["The web archive starts with Governor Nathan Deal in 2011. Georgia Archives permanently retains older Executive Minutes and unbound executive orders, but does not expose them through the structured Governor pages."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ga_eo_scraper.py"), "--actions-out", str(workdir / "ga_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ga_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Georgia adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2011-present structured Governor archives; Georgia Archives pre-2011 holdings require archival backfill"
