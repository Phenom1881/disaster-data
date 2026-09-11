import subprocess
import sys
from pathlib import Path

STATE = 'UT'

CAPABILITIES = {'structured_archive_coverage_start': '2000-01-18',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': False,
 'current_governor_source_available': True,
 'current_governor_source': 'https://rules.utah.gov/publications/executive-documents/',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Repeated statewide fire-danger management orders are excluded rather than counted '
                'as separate fires.',
                'An explicitly dated current-index snapshot is a fallback only if live index '
                'discovery fails; it cannot discover newer records.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "ut_eo_scraper.py"),
        "--actions-out", str(workdir / "ut_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ut_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Utah adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2000-present Office of Administrative Rules executive-document indexes and legal texts.'
