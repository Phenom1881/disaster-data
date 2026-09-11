import subprocess
import sys
from pathlib import Path

STATE = 'ID'

CAPABILITIES = {'structured_archive_coverage_start': '2000-06-28',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': False,
 'current_governor_source_available': True,
 'current_governor_source': 'https://adminrules.idaho.gov/executive-orders/',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Numbered EOs do not comprehensively contain disaster proclamations. '
                'Governor-approved IDWR drought orders provide the historical disaster records.',
                'IDWR Date Declared is used for historical orders; detected conflicts with a '
                'readable Governor approval clause are withheld.',
                'Other disaster proclamations are limited to individually verified Governor/IOEM '
                'releases.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "id_eo_scraper.py"),
        "--actions-out", str(workdir / "id_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "id_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Idaho adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2000-present OARC EO metadata plus IDWR drought orders; non-drought proclamations have incomplete coverage.'
