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
        "Montana's EO record is split across three separate real sites with "
        "no unified archive: gov.mt.gov (Gianforte, 2021-present, dated), "
        "formergovernors.mt.gov/bullock (2013-2020, numbered but UNDATED in "
        "the rendered list - date lives only inside each PDF), and "
        "formergovernors.mt.gov/schweitzer/eo/<year>.asp (2005-2013, "
        "confirmed to exist via one live-fetched page but not deeply parsed "
        "in this pass). Only the dated Gianforte-era range (2021-present) "
        "is in declarations_for_join.csv this delivery; Bullock and "
        "Schweitzer-era disaster EOs are real and identifiable but excluded "
        "pending per-PDF date confirmation - backfill pending.",
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
        "MT-EO-4-2021 ('Energy Emergency', Feb 12 2021, during the same week "
        "as the historic central-US cold snap) could plausibly be a winter-"
        "weather-driven declaration but was left OUT of hazard_overrides.csv "
        "in this pass because no independent citation was found confirming "
        "the cause - it is correctly left unclassified/ambiguous rather than "
        "guessed. Worth a follow-up PDF read.",
    ],
}


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
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Montana adapter: scrape failed")

    return workdir / "declarations_for_join.csv", (
        "2021-present dated Gianforte-era gov.mt.gov listing; Bullock "
        "(2013-2020) and Schweitzer (2005-2013) archives exist but are "
        "undated-in-listing / unparsed, backfill pending"
    )
