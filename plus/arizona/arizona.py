"""Arizona adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AZ"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    '2000-present: 2002-2022 weather emergencies from the Department of Emergency and Military '
    'Affairs annual and State Emergency Council reports, with 2014 and 2021-2022 dates from new'
    "s coverage of each declaration; January 2023-present from the Governor's news releases (da"
    "ted by release) and executive orders. Governor Hull's 2000-2001 weather emergencies (Mohav"
    'e County windstorm, August 2000; Wenden flood and rain from Hurricane Olivia, October 2000'
    '; southwest Arizona monsoon, August 2001) are known only by month from the Auditor General'
    "'s 2004 report and are not listed, and some 2014-2017 and 2021-2023 declarations named in "
    "Governor's Emergency Fund reports have no published date and are not listed"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Arizona Governor news releases (https://azgovernor.gov/news-releases) and executive orders (https://azgovernor.gov/executive-orders)",
    "structured_archive_coverage_start": "2023-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://azgovernor.gov/news-releases",
    "current_governor_source_start": "2023-01-02", "manual_only": False,
    "known_gaps": ["Arizona's Governor declares emergencies by a Declaration of Emergency, not an executive order, and the declarations are not posted. They are collected from the Governor's news releases and dated by the release, which is usually the day the declaration was signed. A declaration announced without a release is not collected.", "The current Governor's site begins in 2023. 2002-2022 declarations are added by hand from DEMA annual and State Emergency Council reports. For 2000-2001 the only list found is Table 2 of the Auditor General's 2004 report 04-04 (https://www.azauditor.gov/sites/default/files/2023-11/04-04.pdf), which dates each emergency by month only, so Hull's 2000-2001 weather emergencies are not listed and FEMA's DR-1347 (October 2000 floods) shows with no state declaration. DEMA's FY2004 annual report (Arizona Memory Project, https://azmemory.azlibrary.gov/nodes/view/146939) confirms the La Paz / Maricopa County Storm Emergency (account 21104) for the storms of October 21 to November 8, 2000 but gives no declaration date, and the Project holds no DEMA annual report for FY2000-2003 (its 1999 report is followed by 2004)."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "az_eo_scraper.py"), "--actions-out", str(workdir / "az_emergency_actions_all.csv"), "--relationships-out", str(workdir / "az_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        last = (result.stderr.strip().splitlines() or ["no error output"])[-1][:200]
        raise RuntimeError(f"Arizona adapter: scrape failed ({last})")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
