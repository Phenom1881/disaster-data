"""Kentucky adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "KY"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": False,
    "structured_archive_source": "The authoritative source, the KY Secretary of State's Executive Journal database (https://apps.sos.ky.gov/executive/journal/), blocks automated requests (bot detection) and could not be scraped in this batch. Individual orders are real and fetchable at the confirmed pattern https://governor.ky.gov/attachments/<YYYYMMDD>_Executive-Order_<YYYY-NNN>_<slug>.pdf, but no working non-blocked enumeration index for that pattern was found other than the Governor's own newsroom RSS feed (https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx), used here as a proxy index.",
    "structured_archive_coverage_start": None, "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://newsroom.ky.gov/GovernorBeshear/_layouts/15/Fwk.Webparts.Agency.Ui/newslistfeed.aspx",
    "current_governor_source_start": "unknown - newsroom feed retention window not confirmed, and only covers the Beshear administration (Dec 2019-present); pre-2019 governors (Bevin, back through 2000) have no equivalent feed identified yet", "manual_only": True,
    "known_gaps": ["No path found yet to the authoritative SOS Executive Journal without triggering bot detection -- this is the single biggest open item for Kentucky and should be revisited (e.g. checking whether the Journal exposes any unauthenticated API, or whether KY's Open Records process could obtain a bulk export).", "Pre-Beshear (2000-2019: Patton, Fletcher, Beshear-Sr., Bevin) coverage has no identified enumeration source yet.", "EO 2025-305 (State-of-Emergency-Related-to-Continuing-Weather-Event) is a real, deliberate exclusion pending manual review -- see hazard_overrides.csv and the summary report."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ky_eo_scraper.py"), "--actions-out", str(workdir / "ky_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ky_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Kentucky adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "manual_only - Beshear-era newsroom feed proxy only; SOS Executive Journal (authoritative) is bot-blocked and pre-2019 coverage is an open gap"
