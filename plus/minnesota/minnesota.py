"""Minnesota adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "MN"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Minnesota Governor Executive Orders (https://mn.gov/governor/newsroom/executive-orders/)",
    "structured_archive_coverage_start": "2019-01-07", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://mn.gov/governor/newsroom/executive-orders/",
    "current_governor_source_start": "2019-01-07", "manual_only": False,
    "known_gaps": ["The current Governor archive covers Governor Walz only, so 2000-2018 is not populated. The Minnesota Legislative Reference Library has deeper official holdings, retained only as a future backfill candidate under the standing scope rule.", "The archive's list endpoint can return a Radware anti-bot page; the scraper detects that condition and fails rather than writing a false empty data set."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "mn_eo_scraper.py"), "--actions-out", str(workdir / "mn_emergency_actions_all.csv"), "--relationships-out", str(workdir / "mn_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Minnesota adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2019-present current Governor archive; 2000-2018 not covered; anti-bot interception is detected explicitly"
