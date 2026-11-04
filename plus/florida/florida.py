"""Florida adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "FL"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Florida Governor Executive Orders (https://www.flgov.com/eog/news/executive-orders)",
    "structured_archive_coverage_start": "2020-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.flgov.com/eog/news/executive-orders",
    "current_governor_source_start": "2020-01-01", "manual_only": False,
    "known_gaps": [
        "The State Library's official year indexes (edocs.dos.fl.gov) reach back to 1971, but its robots.txt disallows all crawlers, so it is not read.",
        "For 2004-2019, weather emergency orders are kept in manual_declarations.csv: Governor Bush and Crist orders catalogued with dates by the FSU College of Law collection on Florida Government Documents (flgovdocs.omeka.net), and later or uncatalogued orders dated from order copies on FMCSA, Division of Emergency Management and DEP sites, archived Governor pages, and news coverage.",
        "No state declaration was found for DR-1595 (Hurricane Dennis, 2005) or DR-4138 (July 2013 flooding). EM-3259 (Hurricane Rita, 2005) counts as matched only because its incident period, which FEMA lists through October 23, 2005, takes in the Wilma declaration; no dated Rita declaration was found. 2000-2003 is not covered: the FSU collection starts in 2004.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "fl_eo_scraper.py"), "--actions-out", str(workdir / "fl_emergency_actions_all.csv"), "--relationships-out", str(workdir / "fl_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Florida adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2004-present: structured Governor archive from 2020; 2004-2019 weather emergency orders added by hand from the FSU College of Law order collection, FMCSA, Division of Emergency Management and DEP order copies, archived Governor pages and dated news coverage, kept in manual_declarations.csv; 2000-2003 not covered"
