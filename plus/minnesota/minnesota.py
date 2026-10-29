"""Minnesota adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MN"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Minnesota Legislative Reference Library executive order database, Governors Ventura, Pawlenty, Dayton and Walz (https://www.lrl.mn.gov/execorders/eoresults?gov=6, 7, 43 and 44)",
    "structured_archive_coverage_start": "2000-02-10", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.lrl.mn.gov/execorders/eoresults?gov=44",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["Covers 2000-present: Ventura (gov=6, orders numbered from 2000 on), Pawlenty (gov=7), Dayton (gov=43) and Walz (gov=44). Orders that only provide assistance for a weather event without declaring an emergency (for example Dayton's 13-03 for the April 2013 winter storm) are kept as actions but not counted as declarations, so FEMA's DR-4113 has no matching state declaration.", "Until Sep 2026 this adapter read the Governor's own site (mn.gov/governor), which is behind Radware's bot manager and intercepted every request from GitHub's runners. It now reads the Legislative Reference Library, the state's official archive of these orders; an anti-bot page from any source is still detected and fails rather than writing a false empty data set."],
}

# The page's coverage text. A refresh (build-plus.py --collect) uses this
# note, not the manifest's, so the two must say the same thing; the
# state's tests check that they do.
COVERAGE_NOTE = (
    "2000-present Legislative Reference Library executive order database "
    "(Ventura from 2000, Pawlenty, Dayton and Walz); weather orders that "
    "only provide assistance, without declaring an emergency, are not "
    "counted as declarations"
)

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "mn_eo_scraper.py"), "--actions-out", str(workdir / "mn_emergency_actions_all.csv"), "--relationships-out", str(workdir / "mn_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Minnesota adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
