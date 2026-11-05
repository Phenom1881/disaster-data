"""Vermont adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "VT"
# Kept identical to the coverage_note in scripts/plus/state-manifest.json.
COVERAGE_NOTE = "2000-present: structured Governor archive from 2017, plus 2011-2015 emergency orders from the Vermont Statutes appendix (3 V.S.A. App. ch. 20); orders from 2000-2010 were rescinded in 2015 and dropped from the current appendix, but the four still in force in 2011 (July 2000 and June 2002 floods, the April 2007 nor'easter, the December 2008 ice storm) are kept from the 2011-2014 editions. Plus 5 declarations added by hand from official announcements, order text and dated news coverage (manual_declarations.csv). No state emergency order was found for DR-1358, EM-3167, DR-1488, DR-1559, DR-1715, DR-1778, DR-1784, DR-1790 or DR-1951 (2000-2010; orders rescinded before 2011 are not published), nor for DR-4066, DR-4120, DR-4140, DR-4163, DR-4178, DR-4207 and DR-4232 (2012-2015), which are not among the orders in the statutes appendix, or for DR-4330, DR-4356, DR-4380, DR-4445, DR-4474, DR-4621, EM-3567 and DR-4695 (2017-2022), which are not in the Governor's numbered order list."
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Vermont Governor Phil Scott Executive Orders Archive (https://governor.vermont.gov/document-types/executive-orders)",
    "structured_archive_coverage_start": "2017-01-05", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.vermont.gov/document-types/executive-orders",
    "current_governor_source_start": "2017-01-05", "manual_only": False,
    "known_gaps": ["The Governor archive covers the Phil Scott administration from 2017 onward; it links prior administrations to the statutory appendix rather than preserving them in this structured Governor archive.", "Orders from before 2011 were rescinded in 2015 and dropped from the current appendix. The emergency orders that were still in force in 2011 (No. 05-00, 05-02, 04-07 and 05-08) are kept in manual_declarations.csv from the 2011-2014 editions of the appendix; orders rescinded earlier are not published there, so most 2000-2010 Vermont declarations remain unlisted."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "vt_eo_scraper.py"), "--actions-out", str(workdir / "vt_emergency_actions_all.csv"), "--relationships-out", str(workdir / "vt_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Vermont adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
