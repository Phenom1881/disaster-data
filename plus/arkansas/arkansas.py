"""Arkansas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AR"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the current Governor's executive order archive from January 2023, plus earlier weather"
    " declarations added by hand from the Governor's disaster proclamations catalogued by the Arkansas St"
    "ate Library (2006-2011 and 2021) and dated news coverage; the only 2000-2005 declaration found so fa"
    "r is Governor Huckabee's state of emergency for the December 2000 ice storms (DR-1354, EM-3159), dat"
    "ed by an Associated Press report of December 28, 2000 that gives no signing day, and FEMA's 2001-200"
    "4 declarations and those for May 2011 and June 2019 still have no dated state declaration; the Decem"
    "ber 2009 declaration (DR-1872) is dated by a January 6, 2010 report that gives no signing day"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Arkansas Governor Executive Orders (https://governor.arkansas.gov/executive-orders/)",
    "structured_archive_coverage_start": "2023-01-10", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.arkansas.gov/executive-orders/",
    "current_governor_source_start": "2023-01-10", "manual_only": False,
    "known_gaps": ["The current Governor website/API begins with the Sanders administration in January 2023. Earlier declarations are added by hand in manual_declarations.csv, dated from the Arkansas State Library catalog of the Governor's DR proclamations (its 2010 amendments quote each original's date and event) and from dated news reports.", "No state declaration has been found for 2001-2005 (Huckabee), so FEMA's 2001-2004 weather declarations show as gaps, as do DR-4000 (May 2011) and DR-4460 (June 2019). DR-1354 and EM-3159 (the December 2000 ice storms) are matched by Governor Huckabee's state of emergency, dated by an Associated Press report of December 28, 2000 (carried by WaterWorld on December 29, 2000) that gives no signing day, and DR-1872 (December 2009) by a declaration dated by a January 6, 2010 report that gives no signing day.", "The State Library also holds scanned 2019-2022 DR proclamations (for example DR 19-07, DR 19-08, DR 20-07, DR 20-08) whose text is not transcribed; they are not used until each one is read."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ar_eo_scraper.py"), "--actions-out", str(workdir / "ar_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ar_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Arkansas adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
