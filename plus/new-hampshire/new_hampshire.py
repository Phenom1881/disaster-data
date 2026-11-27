"""New Hampshire adapter for the DisasterData Plus pipeline."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

STATE = "NH"

# Shown on the page after a refresh; scripts/plus/state-manifest.json carries the
# same text for builds without collection.
COVERAGE_NOTE = (
    "1990-present official Secretary of State registry; older non-ADA PDFs may require OCR. Weather emerg"
    "encies declared without an executive order are added by hand from news coverage (NH-PROC ids). The D"
    "epartment of Safety's emergency notices for fuel deliveries and utility repairs, signed by the Commi"
    "ssioner of Safety as the Governor's designee, come from FMCSA's copies (fmcsa_declarations.csv); its"
    " notice of March 14, 2017 for the heavy snow storm matches DR-4316. Governor Lynch's state of emerge"
    "ncy for Hurricane Irene (EM-3333, DR-4026) is dated by CNN's report of August 27, 2011, which gives "
    "no signing day. The August 19, 1991 state of emergency for Hurricane Bob (DR-917), called while Stat"
    "e Senator Edward Dupont was acting for Governor Gregg, is dated by the Hampton Union of August 23, 1"
    "991, whose sentence does not say who called it. Four federal declarations that Governor Sununu's own"
    " request letters say had no state declaration (DR-4624, DR-4693, DR-4740, DR-4771) are shown with th"
    "at statement instead of as gaps (no_state_declaration.csv). No dated state declaration has been foun"
    "d for the 2001 to 2005 snowstorms (EM-3166, EM-3177, EM-3193, EM-3207, EM-3208, EM-3211), the Septem"
    "ber 2008 floods (DR-1799), the 2011 storms (DR-4006, the October snowstorm DR-4049 and EM-3344), the"
    " May 2012 Cheshire County floods (DR-4065) or the 2017 to 2026 storms (DR-4329, DR-4370, DR-4371, DR"
    "-4457, DR-4622, DR-4761, DR-4812, DR-4947); FERC's report on the October 2011 snowstorm lists New Ha"
    "mpshire among the states that declared, but its source for that is Governor Lynch's request to FEMA,"
    " not a state order, and the 1990 to 1999 gaps have been searched only in part."
)
CAPABILITIES = {
    "state": STATE, "structured_archive_available": True,
    "structured_archive_source": "New Hampshire Secretary of State Executive Order Registry (https://www.sos.nh.gov/executive-orders)",
    "structured_archive_coverage_start": "1990-01-01", "structured_archive_coverage_end": None,
    "pdf_text_available": True, "ocr_required": True,
    "current_governor_source_available": True, "current_governor_source": "https://www.sos.nh.gov/executive-orders",
    "current_governor_source_start": "2025-01-09", "manual_only": False,
    "known_gaps": ["The historical Governor registry is now maintained by the Secretary of State; some clients are blocked by the registry's edge security.", "Many older PDFs are marked non-ADA archival documents and may require manual or OCR review when they contain no extractable text.", "The registry notes that EO 1990-06 was never received from the Governor's Office; 1990-05 and 1990-02 were not used.", "Most New Hampshire weather emergencies were declared without an executive order, so they are not in the registry. Those with a confirmed date were added by hand from news coverage (NH-PROC ids) and are written back on every run.", "Governor Lynch declared a state of emergency for Hurricane Irene without an executive order. CNN's state-by-state report of August 27, 2011 quotes his news release ('Governor John Lynch said New Hampshire was in a state of emergency'), and the U.S. Fire Administration's Executive Fire Officer paper on Bedford's damage assessment guideline cites the release, 'Governor Lynch Declares State of Emergency', at an address dated August 26, 2011. The row carries the date of the CNN report and matches EM-3333 and DR-4026.", "Hurricane Bob (DR-917, August 18 to 20, 1991) was declared without an executive order while Governor Gregg was in Seattle and State Senator Edward Dupont was acting for him. The Hampton Union of August 23, 1991 says 'A state of emergency was called Monday at 1 p.m. and was lifted early Tuesday morning' (Monday, August 19) without saying who called it; the row carries that day and is flagged for the passive wording.", "The Department of Safety's emergency notices under 49 CFR 390.23 (fuel deliveries, utility repairs) are signed by the Commissioner of Safety as the Governor's designee and are not in the registry. FMCSA keeps copies from 2013 on; its 2013 to 2017 archive page, which the yearly FMCSA harvest does not read, lists the March 14, 2017 notice for the heavy snow storm (in effect through March 28, 2017), added to the saved FMCSA entries by hand. It matches DR-4316.", "The registry refuses requests from GitHub's runners. When it cannot be read, the Internet Archive's latest copy of the registry page and of each order's PDF is read instead; the copy's date is shown in the coverage note. If neither can be read the adapter exits with an error, so the health report shows the source as failed."],
}

def collect(workdir=".", scripts_dir=None):
    workdir = Path(workdir); scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]; workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(scripts_dir / "nh_eo_scraper.py"), "--actions-out", str(workdir / "nh_emergency_actions_all.csv"), "--relationships-out", str(workdir / "nh_order_relationships.csv"), "--join-out", str(workdir / "declarations_for_join.csv")]
    result = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True)
    if result.stdout: print(result.stdout)
    # Always pass the scraper's warnings through (a page it could not fetch, a
    # block page). They go to stderr, which used to be printed only when the
    # scraper failed outright, so an empty week looked like a quiet one.
    if result.stderr: print(result.stderr, file=sys.stderr)
    if result.returncode:
        reason = (result.stderr or "").strip().splitlines()
        raise RuntimeError("New Hampshire adapter: " + (reason[-1] if reason else "scrape failed"))
    note = COVERAGE_NOTE
    archived = next((line for line in (result.stdout or "").splitlines() if "Internet Archive copy from" in line), "")
    if archived:
        note += "; this run read the " + archived.split("read from the ", 1)[-1]
    return workdir / "declarations_for_join.csv", note
