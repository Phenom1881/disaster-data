"""Louisiana adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "LA"
# Kept identical to the coverage_note in scripts/plus/state-manifest.json.
COVERAGE_NOTE = "2000-present: official State Register web indexes from January 2016, plus 36 weather declarations added by hand (manual_declarations.csv): 4 by Governor Foster (2000-2003), from his executive order printed in the Louisiana Register and dated news coverage, 13 by Governors Blanco and Jindal (2004-2015), from proclamations cited in the Louisiana Register and dated news coverage, and 19 by Governor Edwards (2016-2023). No state declaration was found for DR-1357 (December 2000 ice storm), DR-1521 (May 2004), DR-1601 (Cindy, 2005), DR-1668 (October 2006) or DR-4228 (Red River flooding, 2015)."
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Louisiana Division of Administration, Office of State Register Executive Orders (https://www.doa.la.gov/doa/osr/executive-orders/)",
    "structured_archive_coverage_start": "2016-01-11", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.doa.la.gov/doa/osr/executive-orders/",
    "current_governor_source_start": "2024-01-08", "manual_only": False,
    "known_gaps": [
        "The official web indexes begin with the Edwards administration in January 2016. For September 2004 to 2015, 13 weather declarations by Governors Blanco and Jindal are kept in manual_declarations.csv: proclamations whose number and date are cited by executive orders and emergency rules printed in the monthly Louisiana Register (doa.louisiana.gov/doa/osr/archives/), and otherwise dated news coverage of the declaration.",
        "No state declaration was found for DR-1357 (December 2000 ice storm), DR-1521 (May 2004 storms), DR-1601 (Hurricane Cindy, July 2005), DR-1668 (October 2006 storms) or DR-4228 (2015 Red River flooding).",
        "For 2000 to 2003, Governor Foster's weather declarations are kept in manual_declarations.csv: Executive Order MJF 00-3 (January 2000 ice storm), printed in the February 2000 Louisiana Register, and Associated Press reports of his declarations for Tropical Storm Allison (2001), Tropical Storm Isidore and Hurricane Lili (2002), dated by the report because the stories do not give the day he signed. His proclamations were not printed in the Register.",
        "Governor Edwards (January 2016 to January 2024) declared weather emergencies by proclamation (\"Proclamation Number 111 JBE 2016\"), not by executive order. Proclamations are not in the State Register's index or printed in the Louisiana Register, and the Governor's site keeps their PDFs with no index page. His weather declarations that FMCSA's archive does not carry are kept in manual_declarations.csv: dated from the proclamation itself where one could be found, otherwise from news coverage of the declaration on the day it was made.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "la_eo_scraper.py"), "--actions-out", str(workdir / "la_emergency_actions_all.csv"), "--relationships-out", str(workdir / "la_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Louisiana adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
