"""Minnesota adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MN"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Minnesota Legislative Reference Library executive order database, Governor Walz (https://www.lrl.mn.gov/execorders/eoresults?gov=44)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.lrl.mn.gov/execorders/eoresults?gov=44",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["Covers Governor Walz (2019-present) only, so 2000-2018 is not populated. The same Legislative Reference Library database holds Dayton, Pawlenty and Ventura orders under other gov= numbers, a backfill candidate under the standing 2000-present scope rule.", "Until Sep 2026 this adapter read the Governor's own site (mn.gov/governor), which is behind Radware's bot manager and intercepted every request from GitHub's runners. It now reads the Legislative Reference Library, the state's official archive of these orders; an anti-bot page from any source is still detected and fails rather than writing a false empty data set."],
}

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
    return workdir / "declarations_for_join.csv", "2019-present Legislative Reference Library executive order database (Walz); 2000-2018 not covered"
