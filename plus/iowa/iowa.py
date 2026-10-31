import subprocess
import sys
from pathlib import Path

STATE = 'IA'

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2020-present: HSEMD proclamation tables from 2024, plus the Governor's 2020-2023 "
    "weather disaster proclamations added by hand from the Governor's press releases "
    '(governor.iowa.gov); the newsroom starts in March 2020 and no archive of earlier '
    'proclamations has been found, so 2000-2019 is not covered yet'
)

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
                "The Governor's 2020-2023 weather disaster proclamations are added by hand in manual_declarations.csv, one row for each proclamation announced in the Governor's newsroom (governor.iowa.gov/newsroom), which begins in March 2020. Extensions, COVID-19, avian influenza, harvest, fuel and the 2023 Davenport building collapse are left out. HSEMD's archive page now lists only 2024 and 2025, and no list of the 2000-2019 proclamations has been found, so the page compares from 2020."]}

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
