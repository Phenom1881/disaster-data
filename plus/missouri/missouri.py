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
                'unresolved records are individually listed.',
                'The May 2020, June to July 2021 and December 2021 storms (DR-4552, DR-4612, DR-4636) '
                'have no order of their own. The COVID-19 state of emergency in force for each is added by '
                'hand in manual_declarations.csv (MO-SOE-2020-04-24, MO-SOE-2021-06-15, MO-SOE-2021-12-30) '
                'as matches by date only, for a different hazard; the last two are dated by the Missouri '
                "Register and the Governor's release, since no renewal falls within three weeks of them."]}

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
    return workdir / "declarations_for_join.csv", "2000-present Secretary of State year indexes and legal order text, plus three hand-added rows for the COVID-19 state of emergency (manual_declarations.csv). Orders signed weeks after the storm they declare are compared on the storm's first day. No weather order has been found for the May 2020 storms (DR-4552), the June and July 2021 storms and flooding (DR-4612) or the December 10, 2021 tornadoes (DR-4636): the year indexes list none. They count as matched only because the COVID-19 state of emergency (Executive Orders 20-02 and 21-09) was in force for each, though it does not name them: the rows are dated by Executive Order 20-09 of April 24, 2020, which extended it to June 15, 2020, the Missouri Register of June 15, 2021, which lists its extension to August 31, 2021, and the Governor's release of December 30, 2021 that it would expire on December 31."
