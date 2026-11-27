"""Texas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "TX"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: current-Governor proclamation archive from January 2015, plus 42 weather declarations "
    "added by hand (manual_declarations.csv): 2001-2014 proclamations from archived copies of the Governor's "
    "proclamation pages (governor.state.tx.us, via the Wayback Machine) and, for the July 15, 2003 Hurricane "
    "Claudette proclamation (DR-1479), which those pages do not list, the Legislative Reference Library's "
    "governors' documents database, and 2000, 2001, 2002, 2007, 2011, 2015 and 2025 declarations from dated "
    "news, National Guard and TDEM coverage. The December 2010 statewide wildfire proclamation, renewed month "
    "by month, is counted for DR-1999 through its dated April 15, 2011 renewal and for DR-4029 through the "
    "September 6, 2011 release saying it had been reissued nine times and was in force; DR-1730 (Tropical "
    "Storm Erin, August 2007) counts as matched only because the Hurricane Dean proclamation of August 17 "
    "falls within three weeks of it. No state declaration was found for DR-1356 (December 2000 ice storm) "
    "or DR-1658 (El Paso flooding, 2006)."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Office of the Texas Governor Proclamation Archive (https://gov.texas.gov/news/category/proclamation)",
    "structured_archive_coverage_start": "2015-01-20", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://gov.texas.gov/news/category/proclamation",
    "current_governor_source_start": "2015-01-20", "manual_only": False,
    "known_gaps": [
        "The current Governor proclamation archive covers the Abbott administration beginning January 2015. For 2001-2014, weather disaster proclamations by Governor Perry (and one by Acting Governor Dewhurst) are kept in manual_declarations.csv, each linked to its archived copy of governor.state.tx.us on the Wayback Machine, except the July 15, 2003 Hurricane Claudette proclamation, which those indexes do not list and which is linked to the Legislative Reference Library's governors' documents database; the Governor's archive indexes run from September 2001 to November 2014. A few 2000, 2001, 2002, 2007, 2011, 2015 and 2025 declarations are dated from news, National Guard and TDEM coverage.",
        "Renewals and extensions are not added as declarations, so DR-1999 and DR-4029 (2011 wildfires), which fell under the December 21, 2010 wildfire proclamation and its monthly renewals, show as gaps.",
        "The Governor's 2001-2014 index lists no proclamation for DR-1356 (December 2000 ice storm), DR-1425 (June-July 2002 floods), DR-1479 (Hurricane Claudette, 2003), DR-1658 (El Paso flooding, 2006), DR-1709 (June 2007 floods), or DR-1730 and EM-3277 (Erin and Dean, August 2007). DR-1425, DR-1709, EM-3277 and DR-1730 are matched from news and National Guard reports, and DR-1479 from the Legislative Reference Library's record of the July 15, 2003 proclamation; no state declaration was found for DR-1356 or DR-1658.",
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
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
