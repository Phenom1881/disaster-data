"""Massachusetts adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MA"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "1970-present from the official State Library executive-order collection (orders before 1970 left off"
    "), plus 20 storm states of emergency added by hand from dated news coverage and FMCSA's copy of the "
    "2015 declaration (manual_declarations.csv), among them Governor Dukakis's for Hurricane Gloria (1985"
    "), Acting Governor Cellucci's for Hurricane Bob (1991), Governor Weld's for the October 1991 and Dec"
    "ember 1992 coastal storms and the October 1996 floods, and Governor Cellucci's for the March 2001 sn"
    "owstorm. No state declaration has been found for EM-3175 and EM-3191 (the February and December 2003"
    " snowstorms), DR-1512 (April 2004 floods), DR-1701 (April 2007 nor'easter) or DR-4651 (January 2022 "
    "blizzard), nor for DR-325 (March 1972 storms), EM-3103 (March 1993 blizzard), DR-1090 (January 1996 "
    "blizzard) or DR-1224 (June 1998 floods). Governor Dukakis's emergency for the April 1987 floods (DR-"
    "790) is dated by the Christian Science Monitor report of April 8, 1987, which gives no day; other un"
    "numbered declarations are not listed."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "State Library of Massachusetts Executive Orders (https://archives.lib.state.ma.us/entities/aggregation/db64a731-fbc5-4ed7-ac61-5330b8b8e5ae)",
    "structured_archive_coverage_start": "1941-12-29", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.mass.gov/massachusetts-executive-orders",
    "current_governor_source_start": "2023-01-05", "manual_only": False,
    "known_gaps": [
        "Unnumbered emergency proclamations outside the executive-order collection are not systematically indexed by a single official archive.",
        "Mass.gov rejects routine non-browser requests; collection uses the State Library's official DSpace API.",
        "Most states of emergency were proclaimed outside the numbered executive-order series, and the collection holds three weather declarations before 2018 (orders 142, 239 and 366). Declarations from other years are added by hand in manual_declarations.csv from dated news coverage.",
        "No state declaration has been found for EM-3175 or EM-3191 (the February 17 to 18 and December 6 to 7, 2003 snowstorms) or DR-1512 (April 2004 floods), all under Governor Romney. Associated Press reports on the snowstorms (February 18, 2003 and December 8, 2003) and an April 29, 2004 report on the federal flood declaration mention none.",
        "No state declaration has been found for DR-1701 (the April 15 to 25, 2007 nor'easter and floods). Governor Patrick's May 7, 2007 release on the SBA disaster declaration for the storm mentions none, and the 2018 State Hazard Mitigation Plan's disaster history records none for it.",
        "No state declaration has been found for DR-4651 (the January 28 to 29, 2022 blizzard). Governor Baker's January 28, 2022 storm release announced a MassDOT tractor-trailer ban on interstates, National Guard standby and activation of the State Emergency Operations Center but no state of emergency, and FEMA's damage assessment report (his request of March 29, 2022) and MEMA's DR-4651 page mention none.",
        "DR-1364 (March 5 to April 16, 2001) is matched through the March 4, 2001 snowstorm declaration, because FEMA's incident period begins with that storm; no separate declaration has been found for the floods of late March and April 2001.",
        "Before 2000, no state declaration has been found for DR-325 (March 1972 storms), EM-3103 (March 1993 blizzard), DR-1090 (January 1996 blizzard) or DR-1224 (June 1998 floods). The Christian Science Monitor of April 8, 1987 reports that the governors of New Hampshire and Massachusetts declared emergencies for the April 1987 floods (DR-790) but gives no day, so the row carries the date of the report.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ma_eo_scraper.py"), "--actions-out", str(workdir / "ma_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ma_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Massachusetts adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
