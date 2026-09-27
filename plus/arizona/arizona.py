"""Arizona adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "AZ"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Arizona Governor news releases (https://azgovernor.gov/news-releases) and executive orders (https://azgovernor.gov/executive-orders)",
    "structured_archive_coverage_start": "2023-01-02", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://azgovernor.gov/news-releases",
    "current_governor_source_start": "2023-01-02", "manual_only": False,
    "known_gaps": ["Arizona's Governor declares emergencies by a Declaration of Emergency, not an executive order, and the declarations are not posted. They are collected from the Governor's news releases and dated by the release, which is usually the day the declaration was signed. A declaration announced without a release is not collected.", "The current Governor's site begins in 2023; 2000-2022 is outside the delivered coverage."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "az_eo_scraper.py"), "--actions-out", str(workdir / "az_emergency_actions_all.csv"), "--relationships-out", str(workdir / "az_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        last = (result.stderr.strip().splitlines() or ["no error output"])[-1][:200]
        raise RuntimeError(f"Arizona adapter: scrape failed ({last})")
    return workdir / "declarations_for_join.csv", "2023-present declarations from the Governor's news releases (dated by release) and executive orders; 2000-2022 gap disclosed"
