"""Michigan adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MI"
# Kept identical to the coverage_note in scripts/plus/state-manifest.json.
COVERAGE_NOTE = "2000-present: structured Governor archive from 2019, plus 5 weather declarations added by hand (manual_declarations.csv) by Governors Granholm and Snyder (2008-2018), from the former Governors' archive on michigan.gov (orders and press releases) and dated news coverage. No state declaration was found for DR-1346 (September 2000 flooding), EM-3160 (December 2000 snowstorm), DR-1413 (April 2002 flooding) or DR-1527 (May 2004 storms): the archive keeps no Engler records and no Granholm declaration for May 2004."
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Michigan Governor State Orders and Directives (https://www.michigan.gov/whitmer/news/state-orders-and-directives)",
    "structured_archive_coverage_start": "2019-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.michigan.gov/whitmer/news/state-orders-and-directives",
    "current_governor_source_start": "2019-01-01", "manual_only": False,
    "known_gaps": [
        "The current Governor archive covers the Whitmer administration only (2019 on).",
        "For 2000-2018, weather declarations behind federal declarations are kept in manual_declarations.csv, from the former Governors' archive on michigan.gov (Granholm 2003-2010 orders and press releases, Snyder 2011-2018 press releases) and dated news coverage. The archive keeps no Engler (1991-2002) records.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "mi_eo_scraper.py"), "--actions-out", str(workdir / "mi_emergency_actions_all.csv"), "--relationships-out", str(workdir / "mi_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Michigan adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
