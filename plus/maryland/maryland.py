"""Maryland adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MD"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the Governor's executive order archive from 2023, plus 2000-2022 "
    "weather declarations added by hand: 2000-2018 executive orders from the Department "
    "of Legislative Services' yearly compilations, and others from official "
    "announcements, order text and dated news coverage; no state declaration was found "
    "for the June 2006 flooding (DR-1652), and Tropical Storm Isaias in 2020 (DR-4583) "
    "counts as matched only because Governor Hogan's COVID-19 state of emergency, renewed "
    "on July 30, 2020, was in force when it struck"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Maryland Governor Executive Orders Archive (https://governor.maryland.gov/official-actions/executive-orders)",
    "structured_archive_coverage_start": "2023-01-19", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.maryland.gov/official-actions/executive-orders",
    "current_governor_source_start": "2023-01-18", "manual_only": False,
    "known_gaps": ["The Governor archive is continuous for the Moore administration from January 2023; three isolated 2007/2012 records appear after that sequence but do not constitute comprehensive earlier coverage.", "Earlier weather declarations are added by hand in manual_declarations.csv. The 2000-2018 executive orders come from the Department of Legislative Services' yearly compilations of the Governor's executive orders (dlslibrary.state.md.us for 2000-2006, mgaleg.maryland.gov from 2007), which print every numbered order; amendments, rescissions, hours of service relief and non-weather emergencies are left out. The 2019-2022 compilations do not include Governor Hogan's emergency orders, so those years rely on announcements and news coverage. The 2006 compilation has no emergency order for the June 2006 flooding (DR-1652), and no state declaration was found for Tropical Storm Isaias (DR-4583, August 2020).", "Tropical Storm Isaias (DR-4583, August 3 to 4, 2020) has no declaration of its own. The COVID-19 state of emergency, renewed July 30, 2020 (the Maryland Association of Counties lists each renewal date), is added by hand (MD-SOE-2020-07-30) as a match by date only, for a different hazard."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "md_eo_scraper.py"), "--actions-out", str(workdir / "md_emergency_actions_all.csv"), "--relationships-out", str(workdir / "md_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Maryland adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
