"""Texas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "TX"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Office of the Texas Governor Proclamation Archive (https://gov.texas.gov/news/category/proclamation)",
    "structured_archive_coverage_start": "2015-01-20", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://gov.texas.gov/news/category/proclamation",
    "current_governor_source_start": "2015-01-20", "manual_only": False,
    "known_gaps": [
        "The current Governor proclamation archive covers the Abbott administration beginning January 2015. For 2001-2014, weather disaster proclamations by Governor Perry (and one by Acting Governor Dewhurst) are kept in manual_declarations.csv, each linked to its archived copy of governor.state.tx.us on the Wayback Machine; the Governor's archive indexes run from September 2001 to November 2014. A few 2000, 2001, 2015 and 2025 declarations are dated from news and TDEM coverage.",
        "Renewals and extensions are not added as declarations, so DR-1999 and DR-4029 (2011 wildfires), which fell under the December 21, 2010 wildfire proclamation and its monthly renewals, show as gaps.",
        "No state declaration was found for DR-1356 (December 2000 ice storm), DR-1425 (June-July 2002 floods), DR-1479 (Hurricane Claudette, 2003), DR-1658 (El Paso flooding, 2006), DR-1709 (June 2007 floods), or DR-1730 and EM-3277 (Erin and Dean, August 2007). The Governor's 2001-2014 index lists no proclamation for them.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "tx_eo_scraper.py"), "--actions-out", str(workdir / "tx_emergency_actions_all.csv"), "--relationships-out", str(workdir / "tx_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Texas adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2000-present: current-Governor proclamation archive from 2015; 2000-2014 weather disaster proclamations added by hand from archived copies of the Governor's proclamation pages and dated news coverage, kept in manual_declarations.csv"
