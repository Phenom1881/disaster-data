"""Alabama adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AL"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the Governor's newsroom from 2017, plus November 2009 to April 2017 states of emergenc"
    "y from the Secretary of State's Record of Proclamations and 2000-2009 ones from dated news coverage "
    "and a Jefferson County order (among them the December 2000 Tuscaloosa tornado, Isidore, the November"
    " 2002 Abbeville tornado, the May 2003 storms, Ivan, Dennis, Katrina, the Enterprise tornado, Fay, Gu"
    "stav and the March 2009 floods); no state declaration has been found for the January 2000 winter sto"
    "rms (DR-1317), the March 2000 storms (DR-1322), the February 2001 floods (DR-1362), the November 200"
    "1 tornadoes (DR-1399), the May 2009 floods (DR-1842), the January 2012 tornadoes (DR-4052), the Octo"
    "ber 2021 storms (DR-4632) or Hurricane Helene in 2024 (EM-3618)"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Alabama Governor State of Emergency Archive (https://governor.alabama.gov/newsroom/category/state-of-emergency/)",
    "structured_archive_coverage_start": "2017-04-12", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.alabama.gov/newsroom/category/state-of-emergency/",
    "current_governor_source_start": "2017-04-10", "manual_only": False,
    "known_gaps": ["The current Governor newsroom begins in April 2017.", "Weather states of emergency from November 2009 to April 2017 are added by hand in manual_declarations.csv from the Secretary of State's Record of Proclamations (arc-sos.state.al.us/cgi/proclist.mbr), the constitutional register of the Governor's acts, which links a scan of each proclamation from 2007. One row is kept for each original declaration; terminations, extensions, supplements and non-weather emergencies (sinkholes, the Deepwater Horizon spill, pipeline leaks, the 2010 UAH shooting, out-of-state hurricanes) are left out. The register lists no storm declaration before November 2009 (not even Hurricane Gustav in 2008), so earlier declarations and the December 24, 2015 flood declaration are added from dated news coverage: Ivan (September 13, 2004, WSFA), Dennis (July 8, 2005), Katrina (August 26, 2005, from the House select committee report), the Enterprise tornado (reported March 2, 2007), Fay (August 24, 2008), Gustav (August 29, 2008) and the March 30, 2009 floods. No declaration was found for Hurricane Ike (DR-1797, September 2008); it counts as matched only because the Gustav declaration falls in its comparison window. 2000-2003 declarations are added the same way, each quoted in its review note: Jefferson County's October 24, 2000 water emergency order, which cites Governor Siegelman's October 13, 2000 drought declaration; the December 2000 Tuscaloosa tornado (Al Bawaba, December 17, 2000); Tropical Storm Isidore (AP, September 26, 2002); Abbeville, declared a disaster area the day after the November 5, 2002 tornado (AP); and Governor Riley's Jefferson County declaration for the May 2003 storms (AP, May 8, 2003). Where a report gives no signing day, its own date is used. A September 2002 Tropical Storm Hanna declaration is left out because no report dates it reliably. No state declaration has been found for the January 2000 winter storms (DR-1317), the March 2000 storms (DR-1322), the February 2001 floods (DR-1362), the November 2001 tornadoes (DR-1399, for which Siegelman asked for federal aid), the May 2009 floods (DR-1842) or the January 2012 tornadoes (DR-4052). The Governor's state of emergency archive lists no weather declaration from October 8, 2021 to January 2023 or from January 2024 to January 2025, so the October 2021 storms (DR-4632) and Hurricane Helene (EM-3618) have none either."],
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
