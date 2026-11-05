import subprocess
import sys
from pathlib import Path

STATE = 'IA'

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = "2000-present: HSEMD proclamation tables from 2024, plus the Governor's weather disaster proclamations added by hand (manual_declarations.csv): 39 from 2020-2023 from the Governor's press releases (governor.iowa.gov), plus 26 from 2000-2019 from dated news coverage, mostly Radio Iowa, since no list of the earlier proclamations has been found. No state proclamation was found for DR-1854 (July 2009 storm), DR-1928 (May 2010 storms and flooding) or DR-4135 (June 2013 storms and flooding). DR-4018 (July 27-29, 2011 storms and flooding) counts as matched only because the proclamations for the July 9-14 storms fall within three weeks of it, and DR-4114 (April 2013 winter storm) only because the April 19 flooding proclamation does."

CAPABILITIES = {'structured_archive_coverage_start': '2024-01-08',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': True,
 'current_governor_source_available': True,
 'current_governor_source': 'https://homelandsecurity.iowa.gov/disasters/governors-disaster-proclamations',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['The linked 2008-2023 legacy archive fails TLS certificate validation in this '
                'environment.',
                '2000-2007 is not exposed by the collected tables; scanned signatures require '
                'OCR.',
                "The Governor's 2020-2023 weather disaster proclamations are added by hand in manual_declarations.csv, one row for each proclamation announced in the Governor's newsroom (governor.iowa.gov/newsroom), which begins in March 2020. Extensions, COVID-19, avian influenza, harvest, fuel and the 2023 Davenport building collapse are left out. HSEMD's archive page now lists only 2024 and 2025.",
                "No list of the 2000-2019 proclamations has been found. For each federal weather declaration from 2000-2019, a dated news report of the Governor's proclamation was looked for, mostly in Radio Iowa's archive; 26 are kept in manual_declarations.csv. Where the story does not give the day the proclamation was signed, the row carries the date of the report and its review note says so."]}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "ia_eo_scraper.py"),
        "--actions-out", str(workdir / "ia_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ia_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Iowa adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
