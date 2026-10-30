"""Arkansas adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AR"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: the current Governor's executive order archive from January 2023, plus earli"
    "er weather declarations added by hand from the Governor's disaster proclamations catalogue"
    'd by the Arkansas State Library (2006-2011 and 2021) and dated news coverage; no declarati'
    "ons from 2000-2005 have been found yet, and FEMA's 2000-2004 declarations and those for Fe"
    'bruary and May 2008, December 2009, May 2011 and June 2019 still have no dated state decla'
    'ration'
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Arkansas Governor Executive Orders (https://governor.arkansas.gov/executive-orders/)",
    "structured_archive_coverage_start": "2023-01-10", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governor.arkansas.gov/executive-orders/",
    "current_governor_source_start": "2023-01-10", "manual_only": False,
    "known_gaps": ["The current Governor website/API begins with the Sanders administration in January 2023. Earlier declarations are added by hand in manual_declarations.csv, dated from the Arkansas State Library catalog of the Governor's DR proclamations (its 2010 amendments quote each original's date and event) and from dated news reports.", "No state declaration has been found for 2000-2005 (Huckabee), so FEMA's 2000-2004 weather declarations show as gaps, as do DR-1744 (February 2008), DR-1758 (May 2008), DR-1872 (December 2009), DR-4000 (May 2011) and DR-4460 (June 2019).", "The State Library also holds scanned 2019-2022 DR proclamations (for example DR 19-07, DR 19-08, DR 20-07, DR 20-08) whose text is not transcribed; they are not used until each one is read."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ar_eo_scraper.py"), "--actions-out", str(workdir / "ar_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ar_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Arkansas adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
