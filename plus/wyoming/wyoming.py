import subprocess
import sys
from pathlib import Path

STATE = 'WY'
COVERAGE_NOTE = (
    "2000-present: the Governor CMS executive-order archive from 2019, plus declarations added by hand fr"
    "om official announcements, order text and dated news coverage (manual_declarations.csv): Governor Fr"
    "eudenthal's June 2010 Fremont County flood disaster declaration and Governor Mead's flood declaratio"
    "ns (2011, 2015, February 2017). No archive of earlier Wyoming governors' orders exists, and no state"
    " declaration has been found for the November 2000 winter storm (DR-1351), the August 2005 Wright tor"
    "nado (DR-1599), the June 2017 floods (DR-4327) or the June 2023 Casper flood (DR-4739)"
)

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
                'uncertain signatures remain excluded.',
                'No archive of Wyoming governors\' orders before 2019 has been found (the Legislature '
                'was still considering an executive order repository in 2024), so earlier declarations '
                'are added by hand in manual_declarations.csv from official announcements, order text '
                'and dated news coverage. None has been found for the November 2000 winter storm '
                '(DR-1351), the August 2005 Wright tornado (DR-1599), the June 2017 floods (DR-4327) '
                'or the June 2023 Casper flood (DR-4739).']}

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
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
