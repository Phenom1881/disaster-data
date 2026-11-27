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
                'releases.',
                'The January 13, 2021 north Idaho windstorm (DR-4589) has no declaration of its own. The '
                'COVID-19 emergency declaration, extended December 31, 2020 (the Legislative Services '
                "Office's list of the Governor's COVID-19 proclamations), is added by hand "
                '(ID-SOE-2020-12-31) as a match by date only, for a different hazard.']}

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
    return workdir / "declarations_for_join.csv", "2000-present OARC EO metadata plus IDWR drought orders; non-drought proclamations have incomplete coverage; no state declaration has been found for the December 2005 to January 2006 Owyhee County storms (DR-1630), the May to June 2008 floods in Kootenai and Shoshone counties (DR-1781), the April 2024 storms and flooding (DR-4789) or the December 16 to 18, 2025 windstorm (DR-4905), and the January 13, 2021 north Idaho windstorm (DR-4589) counts as matched only because the Governor's COVID-19 emergency declaration, extended on December 31, 2020, was in force"
