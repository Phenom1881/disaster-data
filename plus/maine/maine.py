"""Maine adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "ME"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Maine Governor Mills Official Documents and Governor LePage Executive Orders Archive (https://www.maine.gov/governor/mills/official_documents)",
    "structured_archive_coverage_start": "2011-01-06", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.maine.gov/governor/mills/official_documents",
    "current_governor_source_start": "2019-01-02", "manual_only": False,
    "known_gaps": ["The Governor sources used cover the LePage and Mills administrations from 2011 onward. For 2003-2010, Governor Baldacci's weather emergency proclamations are kept in manual_declarations.csv, taken from the Maine State Library's yearly archives of his press releases (digitalmaine.com/ogvn_docs), which quote or describe each proclamation. Releases that mention a declaration without its date (Oxford County, July 2007) are not added.", "No state declaration was found for EM-3174, EM-3190, EM-3194, EM-3209, EM-3210, DR-1591, EM-3265, DR-1716, DR-1788 or DR-1852. 2000-2002 (Governor King) is not covered: no press release archive for those years was found, and the Maine State Archives' 1975-2000 executive proclamations collection on Digital Maine was not searched for this backfill.", "Some LePage emergency records are preserved as HTML records without conventional executive-order numbers."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "me_eo_scraper.py"), "--actions-out", str(workdir / "me_emergency_actions_all.csv"), "--relationships-out", str(workdir / "me_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Maine adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "January 2003-present: 2011-present Governor archives (LePage and Mills); 2003-2010 Baldacci weather emergency proclamations added by hand from the State Library's archives of his press releases, kept in manual_declarations.csv; 2000-2002 not covered"
