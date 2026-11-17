"""Connecticut adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "CT"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "1971-present Governor executive-order archive plus 2005-2020 DEMHS civil-preparedness declaration ta"
    "ble. Plus 11 declarations added by hand from official announcements, order text and dated news cover"
    "age (manual_declarations.csv), among them Governor Grasso's February 1978 blizzard emergency and Gove"
    "rnor O'Neill's June 1982 flood and July 1989 tornado emergencies. The Governor's archive keeps only 2"
    "2 orders from before 2011, and no state declaration has been found for EM-3176 and EM-3192 (the Febr"
    "uary and December 2003 snowstorms), EM-3200 (January 2005 blizzard), DR-1619 (October 2005 floods), "
    "EM-3266 (February 2006 snowstorm), DR-1700 (April 2007 nor'easter) or DR-4410 (September 2018 floods"
    "), nor for DR-608 (1979 Windsor Locks tornado), DR-711 (1984 floods), DR-747 (Hurricane Gloria, 1985"
    "), DR-916 (Hurricane Bob, 1991), DR-972 (December 1992 nor'easter), EM-3098 (March 1993 blizzard), D"
    "R-1092 (January 1996 blizzard) or DR-1302 (Tropical Storm Floyd, 1999). The congressional delegation"
    "'s letters backing Governor Rell's 2006 and 2007 requests say she activated the State Emergency Opera"
    "tions Center and, in 2007, executed the State Emergency Plan, and mention no declaration; Governor Ma"
    "lloy's 2018 request release mentions none."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Connecticut Governor Executive Orders (https://portal.ct.gov/governor/governors-actions/executive-orders)",
    "structured_archive_coverage_start": "1971-06-16", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://portal.ct.gov/governor/governors-actions/executive-orders",
    "current_governor_source_start": "2019-01-09", "manual_only": False,
    "known_gaps": [
        "The public executive-order archive reaches 1971 but is not represented as a guaranteed complete historical series.",
        "The DEMHS civil-preparedness declaration table currently spans 2005-2020 and may omit newer unnumbered declarations.",
        "Some older PDFs may require OCR.",
        "Before 2011 the archive keeps only 22 orders, and the DEMHS table lists one declaration before Governor Malloy's (July 7, 2005, London bombing). Declarations from those years are added by hand in manual_declarations.csv from dated news coverage and state reports.",
        "No state declaration has been found for EM-3176 or EM-3192 (the February 17 to 18 and December 5 to 7, 2003 snowstorms, Governor Rowland). The Office of Policy and Management's labor-relations notice for the February 18, 2003 storm records only a late opening for state workers.",
        "No state declaration has been found for EM-3200, DR-1619, EM-3266 or DR-1700 (Governor Rell, 2005 to 2007), and the DEMHS table lists none. The congressional delegation's March 10, 2006 and May 1, 2007 letters backing her requests say she activated the State Emergency Operations Center (February 12, 2006; April 15, 2007) and executed the State Emergency Plan (April 15, 2007), and mention no declaration.",
        "No state declaration has been found for DR-4410 (September 25 to 26, 2018). Governor Malloy's November 20, 2018 request release and FEMA's damage assessment report mention none, and the DEMHS table lists none between May 15, 2018 and the end of his term.",
        "Before 2000, no declaration has been found for DR-608, DR-711, DR-747, DR-916, DR-972, EM-3098, DR-1092 or DR-1302. After the October 3, 1979 tornado Governor Grasso ordered an 8 p.m. to 5 a.m. curfew in Windsor and Windsor Locks (AP, October 4 and 5, 1979), but no declaration for it has been found.",
    ],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "ct_eo_scraper.py"), "--actions-out", str(workdir / "ct_emergency_actions_all.csv"), "--relationships-out", str(workdir / "ct_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode: print(result.stderr, file=sys.stderr); raise RuntimeError("Connecticut adapter: scrape failed")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
