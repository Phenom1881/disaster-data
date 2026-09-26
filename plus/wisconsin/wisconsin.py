"""Wisconsin adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "WI"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Wisconsin Governor Executive Orders (https://evers.wi.gov/pages/newsroom/executive-orders.aspx)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://evers.wi.gov/pages/newsroom/executive-orders.aspx",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The current Governor archive covers the Evers administration only, so the requested 2000-2018 period is not populated.", "Several early PDFs are image-only and need OCR for body-text review, although the structured archive exposes their titles and dates.", "evers.wi.gov does not answer GitHub's servers (connection timeouts, Sep 2026). When it cannot be reached, new declarations are read from the Governor's GovDelivery press releases (https://content.govdelivery.com/accounts/WIGOV/bulletins.rss); saved archive records are kept as they are."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "wi_eo_scraper.py"), "--actions-out", str(workdir / "wi_emergency_actions_all.csv"), "--relationships-out", str(workdir / "wi_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Wisconsin adapter: scrape failed")
    note = "2019-present structured Governor archive; 2000-2018 not covered; early PDFs may require OCR"
    if "read from the Governor's press releases" in (result.stdout or ""):
        # evers.wi.gov did not answer this run; the scraper read the
        # Governor's GovDelivery press releases for new declarations instead.
        note += "; archive not reachable this run, new declarations read from the Governor's press releases"
    return workdir / "declarations_for_join.csv", note
