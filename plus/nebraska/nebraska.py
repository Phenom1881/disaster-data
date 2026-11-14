import subprocess
import sys
from pathlib import Path

STATE = "NE"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "2000-present from the Nebraska Library Commission mirror of the full 1965-present Governor's Executi"
    "ve Orders index, rows kept only when a hazard or emergency keyword matched, plus Governor declaratio"
    "ns made outside that index, added by hand from NEMA announcements, the Governor's proclamations as k"
    "ept by FMCSA and dated news coverage (manual_declarations.csv); no state declaration has been found "
    "yet for DR-1373, DR-1394, DR-1590, DR-1627, DR-1674, DR-1706, DR-1714, DR-1721, DR-1779, DR-1853, DR"
    "-1864, DR-1878, DR-1902, DR-1945, DR-4013, DR-4014, EM-3323, DR-4179, DR-4321 or DR-4662; some 2021-"
    "2026 fuel-supply orders left unclassified pending individual PDF review"
)

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
        "The index is tried at both of its addresses (eoindex.html and EOIndex.html) with two "
        "User-Agents; if none answers with a full index, the Internet Archive's latest copy is read "
        "and the coverage note says so. If that fails too the adapter exits with the reasons.",
        "Before 2017 Nebraska governors declared most weather emergencies outside the executive order "
        "index, so those declarations are added by hand in manual_declarations.csv: NEMA announcements, "
        "the Governor's proclamations as kept by FMCSA (May 7, 2015 and June 28, 2018), and dated news "
        "coverage for 2003-2024, each quoted in its hazard_overrides.csv note. Where a report gives no "
        "signing day, its own date is used. No state declaration was found for 20 federal declarations, "
        "most from the 2001-2011 Johanns and Heineman years, when the searches turned up only requests "
        "for federal aid; the coverage note names them.",
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
        reason = (result.stderr or "").strip().splitlines()
        raise RuntimeError("Nebraska adapter: " + (reason[-1][:300] if reason else "scrape failed"))
    return (
        workdir / "declarations_for_join.csv",
        COVERAGE_NOTE
        + ("; this run read the Internet Archive copy of the index" if "Internet Archive copy" in (result.stdout or "") else ""),
    )
