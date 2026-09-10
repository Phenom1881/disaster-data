"""
South Dakota adapter wrapper for scripts/build-plus.py.

Exposes STATE, CAPABILITIES, and collect() per the Plus adapter contract.
"""
import subprocess
import sys
from pathlib import Path

STATE = "SD"

CAPABILITIES = {
    "structured_archive_coverage_start": "2020-01-07",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://sdsos.gov/general-information/executive-actions/executive-orders/search/Default.aspx",
    "current_governor_source_start": "2020-01-07",
    "manual_only": False,
    "known_gaps": [
        "The SD Secretary of State's Executive Orders registry renders 2020-present "
        "directly in the page's initial HTML; years 2000-2019 exist in the same "
        "system but sit behind an ASP.NET WebForms postback search form "
        "(__VIEWSTATE/__EVENTVALIDATION), not a plain query-string GET. The "
        "scraper includes an --include-prior-years code path for this, but it "
        "was written from standard ASP.NET WebForms conventions and has NOT "
        "been exercised against the live site (no outbound access to *.gov "
        "domains in the environment that produced this delivery) - verify "
        "field names against the live page before trusting 2000-2019 output.",
        "Recurring 'State of Emergency - Transportation Exemptions' orders "
        "(SD's standing mechanism for blanket motor-carrier hours-of-service "
        "relief, e.g. 2022-09, 2023-01, 2023-09, 2024-02, 2025-05, 2025-09) "
        "are deliberately excluded from declarations_for_join.csv - they are "
        "not tied to a single identifiable storm event and would be "
        "unclassifiable (correctly ambiguous) by the real hazard classifier.",
    ],
}


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
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("South Dakota adapter: scrape failed")

    return workdir / "declarations_for_join.csv", (
        "2020-present structured SD Secretary of State registry; "
        "2000-2019 exists behind an unverified ASP.NET postback form, backfill pending"
    )
