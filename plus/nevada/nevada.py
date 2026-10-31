"""Nevada adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NV"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the current Governor's executive and emergency-order archives from "
    'January 2023, plus 2008-2021 storm, flood and wildfire declarations (Gibbons, '
    "Sandoval and Sisolak) from news coverage and FMCSA's copy of the Tamarack order; no "
    'archive of earlier declarations was found, so the July 2004 Waterfall Fire, the '
    'winter 2004-2005 storms and the December 2005 floods (DR-1540, EM-3202, EM-3204, '
    'DR-1583, DR-1629) have no state declaration'
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Nevada Governor Executive Actions (https://www.gov.nv.gov/executive-actions/)",
    "structured_archive_coverage_start": "2023-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.gov.nv.gov/executive-actions/",
    "current_governor_source_start": "2023-01-02", "manual_only": False,
    "known_gaps": ["The current Governor's web archive begins in 2023. Emergency orders are a separate official collection and are included.", "Pre-2023 declarations are added by hand in manual_declarations.csv from dated news coverage and FMCSA's copies. Nevada's emergencies are Governor proclamations rather than numbered executive orders, and no archive of Guinn's or Gibbons's proclamations was found, so the 2004 Waterfall Fire and FEMA's 2004-2005 storm declarations (DR-1540, EM-3202, EM-3204, DR-1583, DR-1629) show as gaps. The January 2008 Fernley declaration is dated from the Review-Journal's report of that day."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nv_eo_scraper.py"), "--actions-out", str(workdir / "nv_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nv_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Nevada adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
