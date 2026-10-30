"""South Carolina adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "SC"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "South Carolina State Library Executive Orders (https://dc.statelibrary.sc.gov/handle/10827/22)",
    "structured_archive_coverage_start": "1966-02-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.governor.sc.gov/executive-branch/executive-orders",
    "current_governor_source_start": "2017-01-24", "manual_only": False,
    "known_gaps": ["The State Library collection begins in 1966. Some early records have no order number or descriptive abstract; those remain in the action inventory but cannot be safely treated as weather declarations without document review.", "Two FEMA weather declarations since 2000 have no state declaration, checked October 2026 against both executive order indexes (the State Library collection and the Legislature's https://www.scstatehouse.gov/Archives/ExecutiveOrders/execrpts.php): DR-1625 (December 15-16, 2005 ice storm), where Sanford's orders go from 2005-26 (December 5) to 2005-27 (December 22) with no emergency order; and DR-4479 (February 6-7, 2020 storms), where McMaster's only order that month about weather, 2020-04, grants state employees leave with pay and the SCEMD release of February 7 mentions no state of emergency."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "sc_eo_scraper.py"), "--actions-out", str(workdir / "sc_emergency_actions_all.csv"), "--relationships-out", str(workdir / "sc_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("South Carolina adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "1970-present from the official State Library collection (orders before 1970 left off), enriched from the 2017-present Governor archive"
