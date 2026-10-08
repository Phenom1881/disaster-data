"""Mississippi adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import csv
import subprocess
import sys
from pathlib import Path

STATE = "MS"
NOTE = ("January 2020-present structured Governor archive; 2008-2019 weather emergency orders read from the "
        "Secretary of State's order PDFs; 2000-2010 orders from the Secretary of State's executive order "
        "compilations (Musgrove and Barbour)")
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Mississippi Governor Tate Reeves Newsroom and Media Archive (https://governorreeves.ms.gov/) and the Secretary of State's executive order listing (https://www.sos.ms.gov/publications-external-affairs/executive-orders)",
    "structured_archive_coverage_start": "2008-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://governorreeves.ms.gov/",
    "current_governor_source_start": "2020-01-14", "manual_only": False,
    "known_gaps": ["2008-2019 orders are read from the Secretary of State's PDFs a few minutes at a time, so the first runs fill them in over several weeks; orders read are saved in ms_sos_orders.csv.",
                   "Orders that only extend, amend or end an earlier order are not added as separate declarations."],
}


def _ids(path: Path) -> list[str]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [row["declaration_id"] for row in csv.DictReader(handle) if row.get("declaration_id")]
    except (OSError, csv.Error, KeyError):
        return []


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    join = workdir / "declarations_for_join.csv"
    # Orders added by hand from the 2000-2010 compilations live in
    # manual_declarations.csv (shown and joined by build-plus.py, not counted
    # against the source); the Secretary of State step must not add them again.
    hand_saved = [i for i in _ids(workdir / "manual_declarations.csv") if i.startswith("MS-EO-")]
    cmd = [sys.executable, str(scripts_dir / "ms_eo_scraper.py"), "--actions-out", str(workdir / "ms_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ms_order_relationships.csv"), "--join-out", str(join)]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Mississippi adapter: scrape failed")
    # 2008-2019 from the Secretary of State. A failure here never fails the
    # state: the Reeves scrape above is already written, and orders read on
    # earlier runs are in the cache, so every weather order read so far is
    # written back each run and counts as returned by the source. Orders added
    # by hand are skipped.
    skip = [i for i in hand_saved if i[6:].isdigit() and int(i[6:]) < 1456]
    backfill = [sys.executable, str(scripts_dir / "ms_sos_backfill.py"), "--cache", str(workdir / "ms_sos_orders.csv"), "--join-out", str(join), "--skip-ids", ",".join(skip)]
    try:
        extra = subprocess.run(backfill, cwd=str(workdir), capture_output=True, text=True, timeout=15 * 60)
        if extra.stdout: print(extra.stdout)
        if extra.returncode: print("WARNING MS: Secretary of State backfill failed: " + (extra.stderr.strip().splitlines() or ["no output"])[-1][:200], file=sys.stderr)
        elif extra.stderr: print(extra.stderr, file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"WARNING MS: Secretary of State backfill did not finish: {exc}", file=sys.stderr)
    return join, NOTE
