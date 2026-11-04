"""Louisiana adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "LA"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Louisiana Division of Administration, Office of State Register Executive Orders (https://www.doa.la.gov/doa/osr/executive-orders/)",
    "structured_archive_coverage_start": "2016-01-11", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.doa.la.gov/doa/osr/executive-orders/",
    "current_governor_source_start": "2024-01-08", "manual_only": False,
    "known_gaps": [
        "The official web indexes begin with the Edwards administration in January 2016. For September 2004 to 2015, 13 weather declarations by Governors Blanco and Jindal are kept in manual_declarations.csv: proclamations whose number and date are cited by executive orders and emergency rules printed in the monthly Louisiana Register (doa.louisiana.gov/doa/osr/archives/), and otherwise dated news coverage of the declaration.",
        "No state declaration was found for DR-1521 (May 2004 storms), DR-1601 (Hurricane Cindy, July 2005), DR-1668 (October 2006 storms) or DR-4228 (2015 Red River flooding). 2000 to mid-2004 (DR-1314, DR-1357, DR-1380, DR-1435, DR-1437) is not covered: the Register of those years cites no weather proclamations, and older certified records may be requested from the Secretary of State as a future backfill.",
        "Governor Edwards (January 2016 to January 2024) declared weather emergencies by proclamation (\"Proclamation Number 111 JBE 2016\"), not by executive order. Proclamations are not in the State Register's index or printed in the Louisiana Register, and the Governor's site keeps their PDFs with no index page. His weather declarations that FMCSA's archive does not carry are kept in manual_declarations.csv: dated from the proclamation itself where one could be found, otherwise from news coverage of the declaration on the day it was made.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "la_eo_scraper.py"), "--actions-out", str(workdir / "la_emergency_actions_all.csv"), "--relationships-out", str(workdir / "la_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Louisiana adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "September 2004-present: official State Register web indexes from 2016; 2004-2023 weather proclamations by Governors Blanco, Jindal and Edwards added by hand from the proclamations, the Louisiana Register and dated news coverage, kept in manual_declarations.csv; 2000 to mid-2004 gap disclosed"
