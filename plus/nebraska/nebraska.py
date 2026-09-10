import subprocess
import sys
from pathlib import Path

STATE = "NE"

CAPABILITIES = {
    "structured_archive_coverage_start": "1965-08-13",
    "structured_archive_coverage_end": None,
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": "https://govdocs.nebraska.gov/docs/pilot/pubs/eoindex.html",
    "current_governor_source_start": "1965-08-13",
    "manual_only": False,
    "known_gaps": [
        "This adapter only keeps rows whose description contains an emergency/disaster/hazard "
        "keyword (see DECLARATION_KEYWORDS_RE in ne_eo_scraper.py); Nebraska's numbered-EO track "
        "mixes routine administrative orders (bond allocations, task forces, commemorative "
        "proclamations) into the same sequence as genuine disaster orders, so a small number of "
        "generic 'Commercial Motor Carrier Relief' and 'Fuel Supply Shortage' orders in 2021-2026 "
        "were kept as candidates but their underlying cause could not be confirmed as weather from "
        "the index page's description text alone; see the delivery's summary report for the full "
        "list left for a human PDF read.",
        "A handful of pre-1990 entries on the index page are narrative-only (no EO number, no PDF "
        "link, no parseable Date column - e.g. 'September 19, 1986 - Disaster emergency exists due "
        "to tornado action') and are outside 2000-present scope in any case, so were not pursued.",
    ],
}


def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(scripts_dir / "ne_eo_scraper.py"),
        "--actions-out", str(workdir / "ne_emergency_actions_all.csv"),
        "--relationships-out", str(workdir / "ne_order_relationships.csv"),
        "--join-out", str(workdir / "declarations_for_join.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Nebraska adapter: scrape failed")
    return (
        workdir / "declarations_for_join.csv",
        "1965-present structured Governor's Executive Orders index (Nebraska Library Commission "
        "mirror); rows kept only when a hazard/emergency keyword matched, 2000-present in scope",
    )
