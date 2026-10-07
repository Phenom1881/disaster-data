"""New Hampshire adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NH"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Hampshire Secretary of State Executive Order Registry (https://www.sos.nh.gov/executive-orders)",
    "structured_archive_coverage_start": "1990-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.sos.nh.gov/executive-orders",
    "current_governor_source_start": "2025-01-09", "manual_only": False,
    "known_gaps": ["The historical Governor registry is now maintained by the Secretary of State; some clients are blocked by the registry's edge security.", "Many older PDFs are marked non-ADA archival documents and may require manual or OCR review when they contain no extractable text.", "The registry notes that EO 1990-06 was never received from the Governor's Office; 1990-05 and 1990-02 were not used.", "Most New Hampshire weather emergencies were declared without an executive order, so they are not in the registry. Those with a confirmed date were added by hand from news coverage (NH-PROC ids) and are written back on every run.", "The registry refuses requests from GitHub's runners. When it cannot be read, the Internet Archive's latest copy of the registry page and of each order's PDF is read instead; the copy's date is shown in the coverage note. If neither can be read the adapter exits with an error, so the health report shows the source as failed."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nh_eo_scraper.py"), "--actions-out", str(workdir / "nh_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nh_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode:
        reason = (result.stderr or "").strip().splitlines()
        raise RuntimeError("New Hampshire adapter: " + (reason[-1] if reason else "scrape failed"))
    note = "1990-present official Secretary of State registry; older non-ADA PDFs may require OCR"
    archived = next((line for line in (result.stdout or "").splitlines() if "Internet Archive copy from" in line), "")
    if archived:
        note += "; this run read the " + archived.split("read from the ", 1)[-1]
    return workdir / "declarations_for_join.csv", note
