import subprocess
import sys
from pathlib import Path

STATE = 'IA'

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
                'OCR.']}

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
    return workdir / "declarations_for_join.csv", '2024-present HSEMD proclamation tables; 2000-2023 not collected.'
