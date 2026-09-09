"""Tennessee adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "TN"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Tennessee Secretary of State Executive Orders (https://sos.tn.gov/products/division-publications/executive-orders)",
    "structured_archive_coverage_start": "2000-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://sos.tn.gov/products/division-publications/executive-orders-governor-bill-lee",
    "current_governor_source_start": "2019-01-19", "manual_only": False,
    "known_gaps": ["The Secretary of State catalog blocks unattended retrieval, so collection uses the University of Memphis government-publications mirror; legacy mirror records expose only a year and require manual PDF review for exact signed dates."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "tn_eo_scraper.py"), "--actions-out", str(workdir / "tn_emergency_actions_all.csv"), "--relationships-out", str(workdir / "tn_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Tennessee adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2000-present SOS catalog via state-university mirror; legacy exact-date review pending"
