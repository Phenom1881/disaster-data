"""Indiana adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "IN"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present via current + historical governor archives (Braun, Holcomb 2017-2025); Pence-era (2013-"
    "2017) pages not yet independently re-verified; 2000-2004 checked against the Indiana Register's unda"
    "ted list of executive orders; plus 8 declarations added by hand (manual_declarations.csv): O'Bannon'"
    "s July 2003 and Labor Day 2003 flood emergencies, Kernan's May 2004 storm and December 2004 snow eme"
    "rgencies and Pence's January 2014 winter storm order from dated news (the Labor Day 2003 emergency, "
    "Executive Order 03-21 on the Register's list, is dated by the Indiana Daily Student report of Septem"
    "ber 4, 2003, which gives no signing day), Daniels's Executive Orders 06-15 and 08-16 read from the s"
    "canned orders (the archive lists only their year), and Braun's April 11, 2025 declaration from the G"
    "overnor's release. The Register's list also shows state disaster emergencies for the four federal de"
    "clarations still unmatched (Executive Orders 01-01 for EM-3162, 02-14 for DR-1418, 02-19 for DR-1433"
    " and 04-19, probably for DR-1542) and Executive Order 04-33 for DR-1573, which matches only by date "
    "to the December 23, 2004 snow emergency; the Register's texts from before July 2006, which carry the"
    " signing dates, are in print only, so those orders are not listed"
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Indiana Governor's Office Executive Orders and Reports (https://www.in.gov/gov/newsroom/executive-orders/) plus per-governor historical archives (Holcomb 2017-2025, Daniels 2005-2013) and the Indiana Register's Historical List of Executive Orders (linked from https://iar.iga.in.gov/)",
    "structured_archive_coverage_start": "2000-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": False,
    "current_governor_source_available": True, "current_governor_source": "https://www.in.gov/gov/newsroom/executive-orders/",
    "current_governor_source_start": "2025-01-13", "manual_only": False,
    "known_gaps": ["The 2013-2017 Pence-era executive-orders archive page was not independently walked in this batch; its per-year listing pattern should match the Holcomb/Braun structure and needs a follow-up verification pass.", "Pre-2005 (O'Bannon/Kernan, 2000-2004) orders have no per-year archive. The Indiana Register's historical list of executive orders (the 'historical list of executive orders' link on https://iar.iga.in.gov/; the old Historical-List-of-EOs.pdf address now returns only the site's JavaScript shell) was read for 2000-2005 on 2026-11-20. It names the disaster emergency orders 01-01, 02-14, 02-19, 03-18, 03-21, 04-16, 04-19, 04-30 and 04-33 but gives no dates, and the Register's texts, which carry the signing dates, are print-only before July 2006. 03-18, 03-21, 04-16 and 04-30 match the July 2003, Labor Day 2003, May 2004 and December 2004 declarations in manual_declarations.csv, which are dated from news reports (the Labor Day 2003 one by the date of the Indiana Daily Student report of September 4, 2003, which gives no signing day); the other five are left out until a dated source is found. 04-33 followed the January 5, 2005 ice storm (Daniels's EO 05-13 extends the utility service emergency declared for it), but its signing day is not known. DR-1573 counts as matched only because the December 23, 2004 snow emergency falls within 21 days of its January 1, 2005 start, not because its own order (04-33) is dated."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "in_eo_scraper.py"), "--actions-out", str(workdir / "in_emergency_actions_all.csv"), "--relationships-out", str(workdir / "in_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through. They used to be printed only
    # when the scraper exited nonzero, but a failed page or PDF fetch is a
    # warning the scraper skips past (exit 0), so those never reached
    # plus_build.log and a whole governor's orders could vanish without a trace.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Indiana adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
