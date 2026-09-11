import subprocess
import sys
from pathlib import Path

STATE = 'MO'

CAPABILITIES = {'structured_archive_coverage_start': '2000-01-20',
 'structured_archive_coverage_end': None,
 'pdf_text_available': True,
 'ocr_required': False,
 'current_governor_source_available': True,
 'current_governor_source': 'https://www.sos.mo.gov/library/reference/orders/default',
 'current_governor_source_start': None,
 'manual_only': False,
 'known_gaps': ['Operational waivers are retained separately; unresolved primary declarations are '
                'listed in the relationship ledger.',
                'Some source descriptions or dates need manual reconciliation; exclusions and '
                'unresolved records are individually listed.']}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir).resolve()
    scripts_dir = Path(scripts_dir).resolve() if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(scripts_dir / "mo_eo_scraper.py"),
        "--actions-out", str(workdir / "mo_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "mo_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Missouri adapter: scrape failed")
    return workdir / "declarations_for_join.csv", '2000-present Secretary of State year indexes and legal order text.'
