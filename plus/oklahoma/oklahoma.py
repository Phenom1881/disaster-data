import subprocess
import sys
from pathlib import Path

STATE = "OK"

CAPABILITIES = {
    "structured_archive_coverage_start": "2016-01-01",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://oklahoma.gov/oem/emergencies-and-disasters.html",
    "current_governor_source_start": "2016-01-01",
    "manual_only": True,
    "known_gaps": [
        "The Secretary of State's own Executive Orders index (sos.ok.gov/gov/execorders.aspx), "
        "which is Oklahoma's legal system of record for EO text, returns HTTP 403 to automated "
        "requests (robots-disallowed, confirmed directly). This adapter instead crawls the "
        "Oklahoma Department of Emergency Management's 'Emergencies and Disasters' archive, "
        "which links out to the same underlying sos.ok.gov PDFs but only for events OEM chose "
        "to give a named event page.",
        "The OEM archive's per-year pages go back to 2016; a combined '2003-2015' archive page "
        "covers earlier years but was not exhaustively walked for this delivery. 2000-2002 is a "
        "disclosed gap (no OEM structured page covers it).",
        "Not every named OEM event page links to a formal 'Governor Declares' press page - some "
        "events (e.g. the February 18, 2025 winter storm) are tracked with situation-update pages "
        "only, and no distinct emergency-declaration page was found for them. See the delivery's "
        "summary report for the full companion-declaration audit.",
        "Two additional real 2026 disaster-emergency declarations (Creek/Ottawa/Okfuskee/Tulsa "
        "flooding, signed June 7, 2026; Cleveland/Washington severe storms, signed ~July 5, 2026) "
        "were found but are NOT in declarations_for_join.csv because their press pages do not "
        "state the Executive Order number in the body text - the number is only in the signed PDF, "
        "which requires a manual read before it can be added correctly.",
    ],
}


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(scripts_dir / "ok_eo_scraper.py"),
        "--actions-out", str(workdir / "ok_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ok_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Oklahoma adapter: scrape failed")
    return (
        workdir / "declarations_for_join.csv",
        "2016-present OEM emergencies-and-disasters archive (proxy for the robots-blocked SOS EO "
        "index); 2003-2015 archive page not exhaustively walked; 2000-2002 backfill pending",
    )
