import subprocess
import sys
from pathlib import Path

STATE = 'WY'

CAPABILITIES = {'structured_archive_coverage_start': '2019-07-22',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': True,
 'current_governor_source_available': True,
 'current_governor_source': 'https://governor.wyo.gov/state-government/executive-orders',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Website is a JavaScript shell; its public CMS API supplies the real archive '
                'entries.',
                'Most linked Google Drive orders are scans; hash-matched OCR is included, and '
                'uncertain signatures remain excluded.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "wy_eo_scraper.py"),
        "--actions-out", str(workdir / "wy_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "wy_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Wyoming adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2019-present Governor CMS executive-order archive; 2000-2018 backfill pending.'
