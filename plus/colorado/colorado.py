import subprocess
import sys
from pathlib import Path

STATE = 'CO'

CAPABILITIES = {'structured_archive_coverage_start': '2000-01-06',
 'structured_archive_coverage_end': '2025-11-10',
 'pdf_text_available': True,
 'ocr_required': True,
 'current_governor_source_available': False,
 'current_governor_source': 'https://spl.cde.state.co.us/artemis/goserials/',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Governor executive-order page returned HTTP 403; official State Library is the '
                'fetchable mirror.',
                'D-series collection excludes separate appointments/boards series. Numerous old '
                'PDFs have blank or unreadable signature days; they remain outside joins.',
                'Library collection retrieved here stops in 2025.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "co_eo_scraper.py"),
        "--actions-out", str(workdir / "co_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "co_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Colorado adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2000-2025 State Publications Library D-series; current Governor page blocked; 2026 backfill pending.'
