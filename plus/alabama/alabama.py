"""Alabama adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AL"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2004-present: the Governor's newsroom from 2017, plus November 2009 to April 2017 "
    "states of emergency from the Secretary of State's Record of Proclamations and "
    '2004-2009 ones from dated news coverage (Ivan, Dennis, Katrina, the Enterprise '
    'tornado, Fay, Gustav, the March 2009 floods); no state declaration has been found '
    'for the May 2009 floods (DR-1842) or the January 2012 tornadoes (DR-4052), and '
    '2000-2003 is not compared yet'
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Alabama Governor State of Emergency Archive (https://governor.alabama.gov/newsroom/category/state-of-emergency/)",
    "structured_archive_coverage_start": "2017-04-12", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.alabama.gov/newsroom/category/state-of-emergency/",
    "current_governor_source_start": "2017-04-10", "manual_only": False,
    "known_gaps": ["The current Governor newsroom begins in April 2017.", "Weather states of emergency from November 2009 to April 2017 are added by hand in manual_declarations.csv from the Secretary of State's Record of Proclamations (arc-sos.state.al.us/cgi/proclist.mbr), the constitutional register of the Governor's acts, which links a scan of each proclamation from 2007. One row is kept for each original declaration; terminations, extensions, supplements and non-weather emergencies (sinkholes, the Deepwater Horizon spill, pipeline leaks, the 2010 UAH shooting, out-of-state hurricanes) are left out. The register lists no storm declaration before November 2009 (not even Hurricane Gustav in 2008), so earlier declarations and the December 24, 2015 flood declaration are added from dated news coverage: Ivan (September 13, 2004, WSFA), Dennis (July 8, 2005), Katrina (August 26, 2005, from the House select committee report), the Enterprise tornado (reported March 2, 2007), Fay (August 24, 2008), Gustav (August 29, 2008) and the March 30, 2009 floods. No declaration was found for Hurricane Ike (DR-1797, September 2008); it counts as matched only because the Gustav declaration falls in its comparison window. The page compares from 2004: no state declaration has been found for the May 2009 floods (DR-1842) or the January 2012 tornadoes (DR-4052), and Siegelman's 2000-2002 declarations and the May 2003 storms have not been found, so 2000-2003 is not compared."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "al_eo_scraper.py"), "--actions-out", str(workdir / "al_emergency_actions_all.csv"), "--relationships-out", str(workdir / "al_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        # Say why, so the health report's status line names the cause.
        lines = [l.strip() for l in (result.stderr or "").splitlines() if l.strip()]
        raise RuntimeError("Alabama adapter: scrape failed" + (f" ({lines[-1][:400]})" if lines else ""))
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
