import subprocess
import sys
from pathlib import Path

STATE = 'IL'

CAPABILITIES = {'structured_archive_coverage_start': '2003-06-11',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': True,
 'current_governor_source_available': True,
 'current_governor_source': 'https://www.illinois.gov/government/disaster-proclamations.html',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Numbered executive orders are not a complete archive of gubernatorial disaster '
                'proclamations.',
                'The separate current disaster-proclamation page does not supply 2000-2022 weather '
                'declarations.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "il_eo_scraper.py"),
        "--actions-out", str(workdir / "il_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "il_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Illinois adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2000-present numbered EO archive; separate disaster-proclamation listings yield weather records from 2023; earlier proclamation backfill remains pending.'
