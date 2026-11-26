"""New Mexico adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NM"
# Kept identical to the coverage_note in scripts/plus/state-manifest.json.
COVERAGE_NOTE = "2000-present: current-Governor index from January 2019 (many migrated document links are unavailable and are disclosed record-by-record), plus 12 weather declarations added by hand (manual_declarations.csv) by Governors Richardson (2004-2010) and Martinez (2011-2014), from executive orders reprinted in the press, the Martinez-era executive order list as captured by the End of Term web archive in 2016, and dated news coverage; the April 2004 storms and flooding (DR-1514) are matched by Richardson's declaration making four counties eligible for state disaster assistance, dated by a May 4, 2004 report that gives no signing day. Executive Order 2012-018, a statewide emergency for flood potential after wildfires signed four days before the June 2012 flooding, is counted for DR-4079 because it names the flood hazard and was in force when the flooding began. No state declaration was found for DR-1329 and EM-3154 (Cerro Grande Fire, May 2000)."
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Mexico Governor Executive Orders Archive (https://www.governor.state.nm.us/about-the-governor/executive-orders/executive-orders-archive/)",
    "structured_archive_coverage_start": "2019-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.governor.state.nm.us/about-the-governor/executive-orders/",
    "current_governor_source_start": "2019-01-01", "manual_only": False,
    "known_gaps": [
        "The current Governor's web archive begins in 2019. Most posted PDFs are image-only; they are read with OCR, and an order OCR cannot read stays unclassified.",
        "No public index of executive orders before 2019 was found: the New Mexico Register's 2006 cumulative index lists no executive orders, and the archived copy of the Martinez-era order page is closed to crawlers. Twelve 2004-2014 weather declarations by Governors Richardson and Martinez are kept in manual_declarations.csv, from executive orders reprinted in the press and dated news coverage; where a story does not give the day the order was signed, the row carries the date of the report.",
        "No state declaration was found for DR-1329 and EM-3154 (Cerro Grande Fire, May 2000). For DR-1514 (April 2004), a May 4, 2004 report of the federal declaration says the Governor had already declared the four counties eligible for state disaster assistance but gives no signing day, so that declaration carries the date of the report and is compared on the storms' first day.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nm_eo_scraper.py"), "--actions-out", str(workdir / "nm_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nm_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("New Mexico adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
