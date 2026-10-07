"""Ohio adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "OH"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": False,
    "structured_archive_source": "No structured, non-JS-rendered EO/proclamation index was found. governor.ohio.gov/media/executive-orders is IBM WebSphere Portal client-rendered content with no static listing. Ohio's weather-emergency actions are Governor's Proclamations under ORC 5502.22, a separate track from the numbered Executive Orders, announced only via press release. Best available public index used instead: the Ohio Governor's GovDelivery account bulletin feed (https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins.rss).",
    "structured_archive_coverage_start": None, "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins.rss",
    "current_governor_source_start": "rolling - the GovDelivery feed lists only the most recent bulletins, so it adds new proclamations as they are announced", "manual_only": True,
    "known_gaps": ["Proclamations from 2003 to 2026 were added by hand from news coverage and governor press releases (Taft, Strickland, Kasich, DeWine). No complete list of Ohio proclamations is published, so the backfill covers the declarations that were reported, not necessarily all of them.", "The feed adds new proclamations only; saved records are written back on every run, so a week with no proclamation leaves the data as it was. If the feed cannot be fetched the adapter exits with an error, so a blocked source shows as failed in the health report.", "Because Ohio's declarations are proclamations rather than filed/numbered orders, there is no eo_number to populate in declarations_for_join.csv; that field is intentionally left blank for every OH row.", "This adapter should be treated as manual_only / needs-verification, not on par with the 17 states with a genuine structured archive, until a real static index (or a working session-free path into the WebSphere content API) is found."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "oh_eo_scraper.py"), "--actions-out", str(workdir / "oh_emergency_actions_all.csv"), "--relationships-out", str(workdir / "oh_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode:
        reason = (result.stderr or "").strip().splitlines()
        raise RuntimeError("Ohio adapter: " + (reason[-1] if reason else "scrape failed"))
    return workdir / "declarations_for_join.csv", "manual_only - proclamations from 2003 on added by hand from news coverage; the GovDelivery bulletin feed adds new ones as they are announced"
