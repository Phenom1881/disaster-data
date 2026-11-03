"""Oregon adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "OR"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Oregon Governor Executive Orders (https://www.oregon.gov/gov/Pages/executive-orders.aspx)",
    "structured_archive_coverage_start": "2003-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.oregon.gov/gov/Pages/executive-orders.aspx",
    "current_governor_source_start": "2023-01-09", "manual_only": False,
    "known_gaps": ["The Governor resource page states that the online executive-order archive begins in 2003, leaving 2000-2002 outside the live source.", "EO 06-01 (December 2005 to January 2006 storms), which the Governor's list titles only 'Emergency Declaration' so the scraper files it as an undated administrative order, is added by hand in manual_declarations.csv from the Oregon Bulletin of February 2006 on the Secretary of State's records site. The 2004 and 2007 Bulletins carry no Governor's order for the December 2003 ice storm (DR-1510) or the December 2006 windstorm (DR-1683), and no declaration has been found for the December 2016 storms (DR-4296).", "The order PDFs are scans with no text layer, so signing dates are read from the scanned order with OCR. When OCR cannot read the date, a hand-checked date from confirmed_signing_dates.csv is used, or else the date the order was posted to the Governor's list when it fits between the nearest dated orders. A declaration still undated stays in the join file with a blank date (no storm search) and is listed in manual_or_ocr_review.csv."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "or_eo_scraper.py"), "--actions-out", str(workdir / "or_emergency_actions_all.csv"), "--relationships-out", str(workdir / "or_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv"), "--review-out", str(workdir / "manual_or_ocr_review.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        last = (result.stderr.strip().splitlines() or ["no error output"])[-1][:200]
        raise RuntimeError(f"Oregon adapter: scrape failed ({last})")
    return workdir / "declarations_for_join.csv", "2003-present structured Governor archive; 2000-2002 unavailable in live source"
