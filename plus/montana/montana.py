"""
Montana adapter wrapper for scripts/build-plus.py.

Exposes STATE, CAPABILITIES, and collect() per the Plus adapter contract.
"""
import subprocess
import sys
from pathlib import Path

STATE = "MT"

CAPABILITIES = {
    "structured_archive_coverage_start": "2021-02-12",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://gov.mt.gov/Documents/GovernorsOffice/executiveorders/",
    "current_governor_source_start": "2021-02-12",
    "manual_only": False,
    "known_gaps": [
        "Montana's EO record is split across separate real sites with no "
        "unified archive: gov.mt.gov (Gianforte, 2021-present, dated, "
        "collected by the scraper), formergovernors.mt.gov/bullock "
        "(2013-2020, numbered but undated in the rendered list), "
        "formergovernors.mt.gov/schweitzer/eo/2005.asp (one page listing "
        "2005-2012) and the Martz and Racicot archives (2000-2004, text "
        "copies that leave the signing day blank). Weather orders from "
        "2000-2020 are in manual_declarations.csv, dated from the order "
        "text, the governor's press releases or dated news reports. Orders "
        "with no readable signing date are left blank rather than guessed; "
        "four of them carry a reviewed event_date in hazard_overrides.csv so "
        "they are still compared with FEMA's declarations. Scanned Bullock "
        "and Schweitzer orders with illegible dates, and Martz 2003-2004 "
        "orders, are still to be backfilled.",
        "Montana's disaster EOs almost all use the identical boilerplate "
        "title 'Declaring a Disaster to Exist in the State of Montana' with "
        "NO hazard word in the title itself - unlike SD/ND, most Montana "
        "declarations structurally require a hazard_overrides.csv entry "
        "sourced from the governor's-office news release, not just the odd "
        "exception. Any newly-scraped Montana disaster EO should be assumed "
        "to need a citation-backed override until proven otherwise.",
        "gov.mt.gov's current EO listing behaves like a curated/paginated "
        "feed rather than a strict sequential index - EO 10-2025 and "
        "11-2025 (December 2025) were only found via direct search of "
        "their PDFs, not by reading the listing page start-to-finish. A "
        "production run of this scraper must implement and verify real "
        "pagination (?page=N) before treating any single fetch as complete.",
        "MT-EO-4-2021 ('Energy Emergency', Feb 12 2021) is a winter-weather "
        "declaration: the governor's press release ties it to harsh winter "
        "weather, record cold and deep snow delaying propane and heating-oil "
        "deliveries (hazard_overrides.csv, winter). The scraper does not count "
        "energy emergencies as declarations, so this one is kept in "
        "manual_declarations.csv.",
    ],
}


# The page's coverage text. A refresh (build-plus.py --collect) uses this
# note, not the manifest's, so the two must say the same thing; the
# state's tests check that they do.
COVERAGE_NOTE = (
    "2000-present: dated Gianforte-era gov.mt.gov listing from 2021, "
    "plus Racicot (2000), Martz (2001-2002), Schweitzer (2006-2012) and "
    "Bullock (2013-2020) weather orders added by hand from the order "
    "texts, governor's press releases and dated news reports; four "
    "orders whose archive copies leave the signing day blank are "
    "compared with FEMA on their effective dates, and other orders with "
    "no readable signing date are still to be backfilled"
)


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(scripts_dir / "mt_eo_scraper.py"),
        "--actions-out", str(workdir / "mt_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "mt_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode: raise RuntimeError("Montana adapter: scrape failed")

    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
