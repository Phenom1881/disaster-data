"""Maine adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "ME"
COVERAGE_NOTE = (
    "2000-present: 2011-present Governor executive-order archives (LePage and Mills), plus storm emergenc"
    "y proclamations from 2013-2024 taken from the Governor's proclamations and news releases; the adapte"
    "r does not yet read the Mills proclamations listing. Plus declarations added by hand from official a"
    "nnouncements, order text and dated news coverage (manual_declarations.csv), including Governor Balda"
    "cci's 2004-2010 weather emergency proclamations from the Maine State Library's yearly archives of hi"
    "s press releases. No state declaration has been found for Governor King's years: DR-1326 (spring 200"
    "0 flooding and ice jams), EM-3164 and DR-1371 (March 2001 snow and flooding) and DR-1468 (2002-2003 "
    "winter cold and frost); the State Archives' 1975-2000 proclamation collection on Digital Maine did n"
    "ot return his items. Nor for EM-3174, EM-3190 and EM-3194 (2003 snowstorms), EM-3209, EM-3210 and DR"
    "-1591 (March 2005 snow), EM-3265 (December 2005), DR-1716 (Oxford County, July 2007: declared, but n"
    "o date found), DR-1788 (July 2008), DR-1852 (June 2009), DR-4367 (March 2018), DR-4647 (October 2021"
    "), DR-4696 (December 2022) or DR-4719 (spring 2023); Governor Mills's request letters for the last t"
    "wo describe activating the State Emergency Operations Center and mention no declaration."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Maine Governor Mills Official Documents and Governor LePage Executive Orders Archive (https://www.maine.gov/governor/mills/official_documents)",
    "structured_archive_coverage_start": "2011-01-06", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.maine.gov/governor/mills/official_documents",
    "current_governor_source_start": "2019-01-02", "manual_only": False,
    "known_gaps": ["The Governor sources used cover the LePage and Mills administrations from 2011 onward. For 2003-2010, Governor Baldacci's weather emergency proclamations are kept in manual_declarations.csv, taken from the Maine State Library's yearly archives of his press releases (digitalmaine.com/ogvn_docs), which quote or describe each proclamation. Releases that mention a declaration without its date (Oxford County, July 2007) are not added.", "No state declaration was found for EM-3174, EM-3190, EM-3194, EM-3209, EM-3210, DR-1591, EM-3265, DR-1716, DR-1788 or DR-1852. 2000-2002 (Governor King) is not covered: no press release archive for those years was found, and the Maine State Archives' 1975-2000 executive proclamations collection on Digital Maine was not searched for this backfill.", "Some LePage emergency records are preserved as HTML records without conventional executive-order numbers.", "Governor King's 2000-2002 emergency proclamations have not been found. The State Archives' 1975-2000 proclamation collection on Digital Maine (digitalmaine.com/arc_executive_proclamations_2000) did not return his items, and the Archives' own site (digitalarchives.maine.gov) sits behind a bot check that DisasterData.IO does not get around, so the page compares from 2000 and names the four federal declarations of those years as gaps."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "me_eo_scraper.py"), "--actions-out", str(workdir / "me_emergency_actions_all.csv"), "--relationships-out", str(workdir / "me_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Maine adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
