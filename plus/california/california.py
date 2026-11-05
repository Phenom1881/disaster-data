"""California adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "CA"
COVERAGE_NOTE = (
    "2000-present: the current Governor archive from January 2019, plus weather states of emergency added"
    " by hand (manual_declarations.csv): the Brown administration's 2011-2018 ones from its archived proc"
    "lamations (archive.gov.ca.gov/archive/gov39), Governor Schwarzenegger's 2004-2010 ones from Governor"
    " Brown's May 18, 2011 proclamation ending those still in force, and Governor Davis's October 2003 fi"
    "re declaration from his own account on CNN; that 2011 list leaves out states of emergency already en"
    "ded by May 2011, and no other Davis proclamation from 2000-2003 has been added"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "California Governor website search and proclamation records (https://www.gov.ca.gov/?s=state+of+emergency)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.gov.ca.gov/?s=state+of+emergency",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The live Governor site is a Newsom-administration publication archive that begins in January 2019.",
                   "The Brown administration's 2011-2018 weather states of emergency are added by hand in manual_declarations.csv from its archived proclamations (archive.gov.ca.gov/archive/gov39), one row per original proclamation. Proclamations that only add counties to an earlier one, requests to the President, and non-weather emergencies (earthquakes, the 2011 tsunami, oil spills, tanker crashes, the 2015 San Bernardino attack, hepatitis A, the fiscal emergency) are left out.",
                   "Governor Schwarzenegger's 2004-2010 weather states of emergency are added by hand from Governor Brown's May 18, 2011 proclamation (archive.gov.ca.gov/archive/gov39/2011/05/18/news17040), which ends the states of emergency still in force and lists each original proclamation by hazard, date and jurisdiction. Later proclamations for the same storm that only reach more counties (January 15, 2005; January 3 and 12, 2006; April 13, May 2 and May 10, 2006; the January 16 to 26, 2007 freeze; January 7, 9 and 14, 2008; January 22 and 27, 2010; December 23, 24 and 30, 2010) are left out, as are the June 2004 Jones Tract levee failure, the February 2006 levee emergency, the October 2007 San Diego landslide, a December 2007 Humboldt roadway emergency, the 2010 San Bruno gas explosion and the non-weather emergencies on the list. The list names no signer, so each row names the Governor in office, except January 21, 2010, which Attorney General Brown signed as acting governor (Arcadia Weekly, January 22, 2010). The March 16, 2005 proclamation carries the February 12, 2005 start of the storms behind it (Santa Paula Times, March 30, 2005).",
                   "States of emergency ended before May 2011 are not on that list, and Governor Davis's 2000-2003 proclamations have no comparable list; only his October 2003 fire declaration is added, from his own account on CNN that day ('Late last night around midnight I signed a declaration of emergency for San Bernardino County and for Ventura County'). With these rows every FEMA weather declaration for California from 2000 to 2010 has a state match."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ca_eo_scraper.py"), "--actions-out", str(workdir / "ca_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ca_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("California adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
