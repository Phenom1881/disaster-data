import subprocess
import sys
from pathlib import Path

STATE = "KS"

CAPABILITIES = {
    "structured_archive_coverage_start": "2009-03-26",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://www.kansastag.gov/388/Kansas-Disaster-Declarations",
    "current_governor_source_start": "2009-03-26",
    "manual_only": False,
    "known_gaps": [
        "The Kansas Adjutant General's Department (KDEM) disaster-declarations page lists "
        "proclamations back to 2009; it links to an 'Archived Declarations' widget that loads "
        "additional content via JavaScript, which was not reachable from a plain HTTP fetch, so "
        "the 2000-2008 window is a disclosed gap rather than a confirmed absence of declarations.",
        "The Kansas Register (sos.ks.gov/publications/register/) independently publishes the same "
        "proclamations issue-by-issue and could serve as a cross-check or a 2000-2008 backfill "
        "source in a future pass; not used here since KDEM's page is the more complete single "
        "source and is far easier to enumerate.",
    ],
}


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(scripts_dir / "ks_eo_scraper.py"),
        "--actions-out", str(workdir / "ks_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ks_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Kansas adapter: scrape failed")
    return (
        workdir / "declarations_for_join.csv",
        "2009-present KDEM Kansas Disaster Declarations archive; 2000-2008 backfill pending "
        "(JS-loaded 'Archived Declarations' widget not reachable via plain fetch)",
    )
