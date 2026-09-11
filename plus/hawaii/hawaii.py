import subprocess
import sys
from pathlib import Path

STATE = 'HI'

CAPABILITIES = {'structured_archive_coverage_start': '2022-11-28',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': True,
 'current_governor_source_available': True,
 'current_governor_source': 'https://governor.hawaii.gov/category/newsroom/emergency-proclamations/',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['2000-2013 is not supplied by these sources; the procurement mirror is partial and '
                'some historical PDF links fail.',
                'Posted dates are not substituted for unreadable signing dates. Scanned or '
                'malformed signature dates remain listed for review.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "hi_eo_scraper.py"),
        "--actions-out", str(workdir / "hi_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "hi_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Hawaii adapter: scrape failed")
    return workdir / "declarations_for_join.csv", 'Current Governor emergency proclamations plus partial 2014-2022 State Procurement mirror; verified joining coverage is narrower.'
