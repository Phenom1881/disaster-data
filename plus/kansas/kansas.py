import re
import subprocess
import sys
from pathlib import Path

STATE = "KS"

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
        "Declarations' link opens no further content, so 2000-2010 is a disclosed gap rather than a "
        "confirmed absence of declarations.",
        "For 2011-2016 the page links scanned state proclamations under labels the scraper cannot read "
        "(no hazard in parentheses); seven of them were read by eye and are kept in "
        "manual_declarations.csv with their signing dates, along with four declarations dated from "
        "Adjutant General releases and news coverage (2012, 2018, 2019, 2021).",
        "No state declaration was found for DR-4010, DR-4035 and EM-3324 (2011 storms and flooding), "
        "DR-4112 (February 2013 winter storm), DR-4654 (March 2022) or DR-4747 (summer 2023 storms).",
        "The Kansas Register (sos.ks.gov/publications/register/) independently publishes "
        "proclamations issue-by-issue and could serve as a cross-check or an earlier backfill source "
        "in a future pass.",
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
    note = ("2011-present: KDEM Kansas Disaster Declarations archive; 2011-2021 declarations the page "
            "does not label added by hand from its scanned proclamations and dated news coverage, kept in "
            "manual_declarations.csv; 2000-2010 not covered (the page's 2009-2010 tabs list only federal declarations)")
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
