import re
import subprocess
import sys
from pathlib import Path

STATE = "KS"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present: KDEM disaster-declarations page from 2011, plus 34 declarations added by hand (manual_"
    "declarations.csv): seven 2011-2016 proclamations from scanned PDFs on that page, seven 2001-2007 dec"
    "larations cited by executive orders and legislation printed in the Kansas Register, two 2005 declara"
    "tions named in the Adjutant General's Department's 2005 annual report, which gives no signing days, "
    "so each carries the date of the storm it answered, and 2002-2022 declarations dated from Adjutant Ge"
    "neral releases (archived on the Wayback Machine), the Governor's releases and news coverage. No stat"
    "e declaration was found for DR-1327 (April 2000), DR-1535 and DR-1562 (2004), DR-1626 (November 2005"
    "), DR-1849 (April-May 2009), DR-1932 (June 2010) or DR-4747 (summer 2023)."
)

CAPABILITIES = {
    "structured_archive_coverage_start": "2009-03-26",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.kansastag.gov/388/Kansas-Disaster-Declarations",
    "current_governor_source_start": "2009-03-26",
    "manual_only": False,
    "known_gaps": [
        "The Kansas Adjutant General's Department (KDEM) disaster-declarations page has year tabs back "
        "to 2009, but its 2009 and 2010 tabs list only federal declarations and its 'Archived "
        "Declarations' link opens no further content.",
        "Declarations before 2011, and the 2011-2016 proclamations the page links without a hazard "
        "label, are kept in manual_declarations.csv: scanned KDEM proclamations read by eye; "
        "proclamation dates cited by executive orders and legislation printed in the Kansas Register "
        "(rules.ks.gov, 2000-2010 issues searched in full); Adjutant General news releases for "
        "2006-2013 from archived copies of kansastag.gov; the Adjutant General's Department's 2005 annual "
        "report, which names two 2005 declarations without their signing days; and dated news coverage.",
        "The Kansas Register does not print disaster proclamations themselves, only executive orders "
        "that cite some of them, so the 2000-2006 record is thin. No state declaration was found for "
        "DR-1327, DR-1535, DR-1562, DR-1626, DR-1849, DR-1932 or DR-4747.",
    ],
}


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(scripts_dir / "ks_eo_scraper.py"),
        "--actions-out", str(workdir / "ks_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ks_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Kansas adapter: scrape failed")
    note = COVERAGE_NOTE
    if "read from the KDEM News Flash" in (result.stdout or ""):
        # The declarations page was not understood this run; new declarations
        # came from KDEM's News Flash feed instead (see ks_eo_scraper.py).
        note += "; declarations page not read this run, new declarations read from the KDEM News Flash"
    copy = re.search(r"Internet Archive copy from (\d{4}-\d{2}-\d{2})", result.stdout or "")
    if copy:
        # kansastag.gov refused the request this run (see fetch_page() in
        # ks_eo_scraper.py), so the page was read as the Internet Archive kept it.
        note += "; the live page could not be read this run, so the Internet Archive copy from %s was read" % copy.group(1)
    return workdir / "declarations_for_join.csv", note
