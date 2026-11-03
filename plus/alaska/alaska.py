import subprocess
import sys
from pathlib import Path

STATE = 'AK'

CAPABILITIES = {'structured_archive_coverage_start': '2001-07-03',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': False,
 'current_governor_source_available': True,
 'current_governor_source': 'https://gov.alaska.gov/administrative-orders/',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['State disaster declarations from 2002 on are added by hand in '
                'manual_declarations.csv from DHS&EM\'s Disaster Cost Index as printed in the 2013 '
                'and 2018 State Hazard Mitigation Plans (Wayback Machine copies) and the 2023 plan, '
                'and from DHS&EM releases. The legislative journals that list every declaration '
                '(akleg.gov) and alaskapublic.org disallow Claude\'s crawlers, so they were not '
                'used. No dated declaration has been found for DR-4391 (May 2018) or DR-4638 '
                '(fall 2021).',
                'DHSEM Operations documents page supplies local declaration templates, not a '
                'complete signed state archive.',
                'Governor and DHSEM releases are proxies; only explicit same-day or explicitly '
                'stated issuance dates enter joins.',
                'Coverage before the earliest verified declaration is a gap, not evidence that '
                'Alaska had no disasters.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "ak_eo_scraper.py"),
        "--actions-out", str(workdir / "ak_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ak_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Alaska adapter: scrape failed")
    return workdir / "declarations_for_join.csv", 'Governor administrative orders plus Governor/DHSEM disaster-release proxies; no complete 2000-present signed proclamation archive verified.'
