"""Oregon adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "OR"

# Kept identical to scripts/plus/state-manifest.json; test_or_manual_declarations checks it.
COVERAGE_NOTE = (
    "2000-present: structured Governor archive from 2003, plus 38 weather "
    "emergency orders from 2000-2002 (Governor Kitzhaber's flood, wildfire "
    "and drought orders) read from the Oregon State Archives copy of his "
    "website, which holds his complete executive order index and order "
    "texts, and declarations added by hand from the Oregon Bulletin and "
    "official announcements (manual_declarations.csv). No state declaration "
    "is kept for DR-1405 (February 2002 windstorm): Kitzhaber's complete "
    "2000-2002 order index has no order for it. The 2004 and 2007 Oregon "
    "Bulletins carry no Governor's order for DR-1510 (December 2003 ice "
    "storm) or DR-1683 (December 2006 windstorm), and no declaration has "
    "been found for DR-4296 (December 2016 storms). Three spring 2001 "
    "drought orders signed with the day left blank (01-03, 01-04, 01-05) "
    "and the 2002 statewide wildfire order 02-06 (index entry only) are "
    "left out because they cannot be dated. Nine later orders are shown "
    "without a signing date and are not matched to storms, because OCR "
    "cannot read their scans and no dated copy has been found: 07-18, "
    "08-01, 08-02, 08-22, 08-27, 08-28, 12-06, 15-17 and 23-24."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "Oregon Governor Executive Orders (https://www.oregon.gov/gov/Pages/executive-orders.aspx)",
    "structured_archive_coverage_start": "2003-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": False, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.oregon.gov/gov/Pages/executive-orders.aspx",
    "current_governor_source_start": "2023-01-09", "manual_only": False,
    "known_gaps": ["The Governor resource page states that the online executive-order archive begins in 2003. Governor Kitzhaber's 2000-2002 weather orders are added by hand in manual_declarations.csv from the Oregon State Archives copy of his website (January 13, 2003, Record APD/18/19), which holds his complete executive order index and the order texts.", "EO 06-01 (December 2005 to January 2006 storms), which the Governor's list titles only 'Emergency Declaration' so the scraper files it as an undated administrative order, is added by hand in manual_declarations.csv from the Oregon Bulletin of February 2006 on the Secretary of State's records site. The 2004 and 2007 Bulletins carry no Governor's order for the December 2003 ice storm (DR-1510) or the December 2006 windstorm (DR-1683), and no declaration has been found for the December 2016 storms (DR-4296).", "The order PDFs are scans with no text layer, so signing dates are read from the scanned order with OCR. When OCR cannot read the date, a hand-checked date from confirmed_signing_dates.csv is used, or else the date the order was posted to the Governor's list when it fits between the nearest dated orders. A declaration still undated stays in the join file with a blank date (no storm search) and is listed in manual_or_ocr_review.csv.", "Nine declarations are still undated after a search of the Oregon Bulletin, the State Fire Marshal's list of Governor-declared conflagrations, the Governor's archived releases and dated news coverage. What is known: 07-18 (Grant County drought) was signed in October 2007, but the day is unreadable on the scan and on the archived copy of the Governor's 2009 website. 08-01 and 08-02 (Umatilla and Union counties, winter storm and high winds; the Pendleton weather office reports damaging winds in both counties on January 4, 2008) come before 08-03, signed January 24, 2008. 08-22 (Sherman County drought) is numbered between 08-21 (September 17, 2008) and 08-23 (September 24, 2008). For 08-27 and 08-28 (December 2008 winter weather in Multnomah, Columbia and Clackamas counties), Columbia County's emergency board minutes of December 23, 2008 say the Governor intended to sign the declaration. 12-06 (13 counties, winds, rain and landslides) is numbered between 12-04 (February 24, 2012) and 12-09 (June 13, 2012); 15-17 (wildfire effects and rule suspensions) between 15-14 (August 14, 2015) and 15-19 (September 3, 2015); and 23-24 (Harney and Malheur storm) between 23-23 (September 5, 2023) and 23-25 (October 19, 2023). The Bulletin issues that would print the 2007 to 2015 orders were not located, and Bulletins after October 2017 are kept in the Oregon Administrative Rules Database.", "The Governor's list titles EO 06-12 'McClean Creek Fire in Deschutes County'. The order itself invokes the Conflagration Act for the Black Crater Fire (findings made July 27, 2006); McClean Creek, in Baker County, is EO 06-11. The page keeps the list's title."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "or_eo_scraper.py"), "--actions-out", str(workdir / "or_emergency_actions_all.csv"), "--relationships-out", str(workdir / "or_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv"), "--review-out", str(workdir / "manual_or_ocr_review.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        last = (result.stderr.strip().splitlines() or ["no error output"])[-1][:200]
        raise RuntimeError(f"Oregon adapter: scrape failed ({last})")
    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
