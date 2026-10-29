"""
South Dakota adapter wrapper for scripts/build-plus.py.

Exposes STATE, CAPABILITIES, and collect() per the Plus adapter contract.
"""
import subprocess
import sys
from pathlib import Path

STATE = "SD"

CAPABILITIES = {
    "structured_archive_coverage_start": "2000-04-12",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx",
    "current_governor_source_start": "2020-01-07",
    "manual_only": False,
    "known_gaps": [
        "The SD Secretary of State's Executive Orders registry renders 2020-present "
        "directly in the page's initial HTML; years 2000-2019 sit behind its "
        "'Search for Prior Years Orders' form, an ASP.NET WebForms postback. "
        "The scraper posts one year at a time (--include-prior-years, which "
        "collect() passes); the form was checked against the live page in a "
        "browser on 2026-10-29, when it returned 333 orders for 2000-2019. "
        "Those orders link to scanned copies, so the hazard for a title that "
        "says only 'State of Emergency' comes from reading the signed order "
        "(hazard_overrides.csv).",
        "Among Janklow's 2000-2002 and Rounds's 2003-2004 orders the registry "
        "has no weather emergency declarations, only fee, size and hours "
        "waivers for hay and fuel hauling (checked: EO 2000-08, 2002-03) and "
        "fire-season authorizations (EO 2004-06), so federal declarations "
        "from those years show no state match.",
        "Recurring 'State of Emergency - Transportation Exemptions' orders "
        "(SD's standing mechanism for blanket motor-carrier hours-of-service "
        "relief, e.g. 2022-09, 2023-01, 2023-09, 2024-02, 2025-05, 2025-09) "
        "are deliberately excluded from declarations_for_join.csv - they are "
        "not tied to a single identifiable storm event and would be "
        "unclassifiable (correctly ambiguous) by the real hazard classifier.",
    ],
}


# The page's coverage text. A refresh (build-plus.py --collect) uses this
# note, not the manifest's, so the two must say the same thing; the
# state's tests check that they do.
COVERAGE_NOTE = (
    "2000-present SD Secretary of State executive order registry: 2020-present "
    "from its yearly tables and 2000-2019 through its prior-years search, with "
    "the hazard for each older order read from the signed copy; it lists no "
    "weather emergency declarations for 2000-2004, only waivers for hay and "
    "fuel hauling and fire-season orders"
)


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parent
    workdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(scripts_dir / "sd_eo_scraper.py"),
        "--actions-out", str(workdir / "sd_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "sd_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
        "--include-prior-years",
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("South Dakota adapter: scrape failed")

    return workdir / "declarations_for_join.csv", COVERAGE_NOTE
