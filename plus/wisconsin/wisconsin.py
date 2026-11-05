"""Wisconsin adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

STATE = "WI"
COVERAGE_NOTE = (
    "2000-present: the current Governor archive from January 2019, plus the 2000-2018 weather states of e"
    "mergency (Governors Thompson, McCallum, Doyle and Walker) read from the Legislature's executive orde"
    "r archive (docs.legis.wisconsin.gov), as listed under States of Emergency in the Legislative Referen"
    "ce Bureau's Index to Executive Orders, added by hand (manual_declarations.csv); early PDFs may requi"
    "re OCR"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Wisconsin Governor Executive Orders (https://evers.wi.gov/pages/newsroom/executive-orders.aspx)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://evers.wi.gov/pages/newsroom/executive-orders.aspx",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The current Governor archive covers the Evers administration only. The 2000-2018 weather states of emergency are added by hand in manual_declarations.csv from the Legislature's executive order archive (docs.legis.wisconsin.gov/code/executive_orders), one row per original order, as listed under States of Emergency in the Legislative Reference Bureau's Index to Executive Orders. Amendments, extensions, orders that only incorporate or supersede an earlier one, energy and propane emergencies, office closings, out-of-state hurricane assistance, and permitting, hay and salt transport orders are left out.", "Several early PDFs are image-only and need OCR for body-text review, although the structured archive exposes their titles and dates.", "evers.wi.gov does not answer some of GitHub's servers (connect timeouts on about a third of refresh runs since September 2026; a later try from the same server has never got through). On those runs the archive is read from an Internet Archive copy of the same page made in the last day, or made on request through Save Page Now; an older copy is never used. Failing that, new declarations are read from the Governor's GovDelivery press releases (https://content.govdelivery.com/accounts/WIGOV/bulletins.rss), which have answered 406 to every request from GitHub's servers so far; saved archive records are kept as they are."],
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
    if result.returncode:
        # Say why: which of the sources failed and how. Without this the
        # status page only read "scrape failed" and the cause was in the log.
        lines = [l.strip() for l in (result.stderr or "").splitlines() if l.strip()]
        reason = lines[-1][:400] if lines else ""
        raise RuntimeError("Wisconsin adapter: scrape failed" + (f" ({reason})" if reason else ""))
    note = COVERAGE_NOTE
    copy = re.search(r"read from the Internet Archive's copy made ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC)", result.stdout or "")
    if copy:
        # evers.wi.gov did not answer this run; the scraper read a current
        # Internet Archive copy of the same archive page instead.
        note += f"; the Governor's site did not answer this run, so the archive was read from the Internet Archive's copy made {copy.group(1)}"
    elif "read from the Governor's press releases" in (result.stdout or ""):
        # evers.wi.gov did not answer this run; the scraper read the
        # Governor's GovDelivery press releases for new declarations instead.
        note += "; archive not reachable this run, new declarations read from the Governor's press releases"
    return workdir / "declarations_for_join.csv", note
