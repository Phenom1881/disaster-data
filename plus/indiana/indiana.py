"""Indiana adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "IN"
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Indiana Governor's Office Executive Orders and Reports (https://www.in.gov/gov/newsroom/executive-orders/) plus per-governor historical archives (Holcomb 2017-2025, Daniels 2005-2013) and the Indiana Register's Historical List of Executive Orders (https://iar.iga.in.gov/Historical-List-of-EOs.pdf)",
    "structured_archive_coverage_start": "2000-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.in.gov/gov/newsroom/executive-orders/",
    "current_governor_source_start": "2025-01-13", "manual_only": False,
    "known_gaps": ["The 2013-2017 Pence-era executive-orders archive page was not independently walked in this batch; its per-year listing pattern should match the Holcomb/Braun structure and needs a follow-up verification pass.", "Pre-2005 (O'Bannon/Kernan, 2000-2004) entries are covered only via the Indiana Register's historical PDF listing rather than a native per-year HTML archive, and that PDF was not exhaustively cross-checked against every 2000-2004 order in this batch."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "in_eo_scraper.py"), "--actions-out", str(workdir / "in_emergency_actions_all.csv"), "--relationships-out", str(workdir / "in_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Indiana adapter: scrape failed")
    return workdir / "declarations_for_join.csv", "2000-present via current + historical governor archives; Pence-era (2013-2017) page structure not yet independently re-verified"
