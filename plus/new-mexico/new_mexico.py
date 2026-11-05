"""New Mexico adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NM"
# Kept identical to the coverage_note in scripts/plus/state-manifest.json.
COVERAGE_NOTE = "2000-present: current-Governor index from January 2019 (many migrated document links are unavailable and are disclosed record-by-record), plus 7 weather declarations added by hand (manual_declarations.csv) by Governors Richardson (2006-2010) and Martinez (2011-2013), from executive orders reprinted in the press and dated news coverage. No state declaration was found for DR-1329 and EM-3154 (Cerro Grande Fire, May 2000), DR-1514 (April 2004 storms and flooding), DR-4047 (August 2011 flooding), DR-4079 (June 2012 flooding), DR-4197 (July 2014 storms and flooding) or DR-4199 (September 2014 storms and flooding)."
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Mexico Governor Executive Orders Archive (https://www.governor.state.nm.us/about-the-governor/executive-orders/executive-orders-archive/)",
    "structured_archive_coverage_start": "2019-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.governor.state.nm.us/about-the-governor/executive-orders/",
    "current_governor_source_start": "2019-01-01", "manual_only": False,
    "known_gaps": [
        "The current Governor's web archive begins in 2019. Most posted PDFs are image-only; they are read with OCR, and an order OCR cannot read stays unclassified.",
        "No public index of executive orders before 2019 was found: the New Mexico Register's 2006 cumulative index lists no executive orders, and the archived copy of the Martinez-era order page is closed to crawlers. Seven 2006-2013 weather declarations by Governors Richardson and Martinez are kept in manual_declarations.csv, from executive orders reprinted in the press and dated news coverage; where a story does not give the day the order was signed, the row carries the date of the report.",
        "No state declaration was found for DR-1329 and EM-3154 (Cerro Grande Fire, May 2000), DR-4047 (August 2011 flooding), DR-4079 (June 2012 flooding), DR-4197 (July 2014 storms and flooding) or DR-4199 (September 2014 storms and flooding). For DR-1514 (April 2004), a May 2004 report of the federal declaration says the Governor had already declared the four counties eligible for state disaster assistance, but no date for that declaration was found.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nm_eo_scraper.py"), "--actions-out", str(workdir / "nm_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nm_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("New Mexico adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
