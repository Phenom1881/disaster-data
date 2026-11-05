"""Kentucky adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "KY"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "manual_only - 2000-present: the Governor's newsroom releases and executive orders, plus states of em"
    "ergency added by hand: 2000-2007 ones (Governors Patton and Fletcher) from Appendix A of Beshear v. "
    "Acree (Ky. 2020), which lists every declaration of emergency filed in the Executive Journal by filin"
    "g date and order number, and 2008-2024 ones from executive orders, official releases and dated news "
    "coverage; the Secretary of State's Executive Journal (authoritative) blocks automated requests, and "
    "no dated declaration has been found for April 2008, May and August 2009, June 2011, August 2014 or H"
    "elene in 2024 (DR-1757, DR-1841, DR-1855, DR-4008, DR-4196, DR-4848)"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": False,
    "structured_archive_source": "The authoritative source, the KY Secretary of State's Executive Journal database (https://apps.sos.ky.gov/executive/journal/), blocks automated requests (bot detection) and could not be scraped in this batch. Individual orders are real and fetchable at the confirmed pattern https://governor.ky.gov/attachments/<YYYYMMDD>_Executive-Order_<YYYY-NNN>_<slug>.pdf, but no working non-blocked enumeration index for that pattern was found other than the Governor's own newsroom RSS feed (https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx), used here as a proxy index.",
    "structured_archive_coverage_start": None, "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx",
    "current_governor_source_start": "unknown - newsroom feed retention window not confirmed, and only covers the Beshear administration (Dec 2019-present); pre-2019 governors (Bevin, back through 2000) have no equivalent feed identified yet", "manual_only": True,
    "known_gaps": ["No path found yet to the authoritative SOS Executive Journal without triggering bot detection -- this is the single biggest open item for Kentucky and should be revisited (e.g. checking whether the Journal exposes any unauthenticated API, or whether KY's Open Records process could obtain a bulk export).", "Bevin (2015-2019) and Steve Beshear (2007-2015) coverage has no identified enumeration source yet; their declarations are added by hand.", "The filename classifier deliberately leaves out titles it cannot read a hazard from ('...Weather', '...Continuing Weather Event'). EO 2025-210, 2025-305 and 2026-047 were reviewed by hand in Sep 2026 and added to declarations_for_join.csv, the first two with sourced hazard_overrides.csv rows; the saved-records safeguard keeps them across refreshes.", "2008-2024 states of emergency are added by hand in manual_declarations.csv from executive orders, official releases and dated news coverage. Where a report gives no signing day, the report's own date is used and the review note says so. The Governor issued a state disaster declaration for the June 2011 storms (Representative Rogers' July 14, 2011 release says so) but its date was not found, so DR-4008 shows as a gap; no dated declaration was found for April 2008 (DR-1757), May and August 2009 (DR-1841, DR-1855) or August 2014 (DR-4196), and on September 27, 2024 the Governor had not declared one for Helene (DR-4848).",
                   "Patton's and Fletcher's 2000-2007 declarations are added by hand from Appendix A of Beshear v. Acree, No. 2020-SC-0313-OA (Ky. Nov. 12, 2020), PDF pages 95-97, which lists every declaration of emergency filed in the Executive Journal from 1996 with its filing date, order number and subject. Its dates are filing dates, which the appendix says can trail the declaration by a few days. One row per weather order is kept, including later orders for the same episode (August 20, 2001; December 29, 2004; October 23, 2007), since the appendix lists each as its own declaration. Water system failures, contamination, the 2002 National Guard readiness orders, the 2007 Bullitt County derailment, the Wolf Creek Dam orders and the 2001 truck weight order are left out. The appendix prints order number 1998-0012 for the January 5, 2000 order; it is kept as printed until the Executive Journal entry is checked. With these rows every FEMA weather declaration for Kentucky from 2000 to 2007 has a state match."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ky_eo_scraper.py"), "--actions-out", str(workdir / "ky_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ky_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Kentucky adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
