"""West Virginia adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "WV"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the Governor's news archive from 2025, plus 2001-2024 weather "
    "declarations added by hand from the Governor's state of emergency proclamations in "
    "the Secretary of State's Executive Journal (and Executive Order 14-01 for the July "
    '2001 flooding); the Journal holds no proclamations from Governor Underwood, so '
    'DR-1319 (February 2000) has no state declaration'
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "West Virginia Governor News Archive (https://governor.wv.gov/allnews/all)",
    "structured_archive_coverage_start": "2025-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.wv.gov/allnews/all",
    "current_governor_source_start": "2025-01-13", "manual_only": False,
    "known_gaps": ["Emergency declarations are Governor proclamations indexed in the news archive rather than the separate Executive Orders page; the package supplements the January 5, 2025 transition-period storm declaration from a later official Governor article that expressly identifies it.", "Emergency declarations from 2001 to 2024 are added by hand in manual_declarations.csv from the Governor's proclamations in the Secretary of State's Executive Journal (https://apps.sos.wv.gov/adlaw/executivejournal/searchproclamations.aspx), one row for each original weather declaration; amendments, extensions, terminations, States of Preparedness and non-weather emergencies are left out. The July 8, 2001 flooding declaration is known from Executive Order 14-01, which recites it. The Journal holds no proclamations or weather executive orders from Governor Underwood, so DR-1319 (February 2000) shows as a gap."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "wv_eo_scraper.py"), "--actions-out", str(workdir / "wv_emergency_actions_all.csv"), "--relationships-out", str(workdir / "wv_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("West Virginia adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
