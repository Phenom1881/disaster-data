"""
state-evidence/adapters/new_jersey.py  (also usable from scripts/plus/)

New Jersey adapter for the state-evidence / DisasterData Plus pipeline.

Mirrors virginia.py's contract exactly: declares CAPABILITIES and exposes
collect(workdir, scripts_dir) -> (path, coverage_note), so build-plus.py can
load this adapter via importlib.util.spec_from_file_location and call it the
same way it calls virginia.py, with no special-casing per state.

Research basis (ChatGPT, 2026-09-04): the NJ Governor's Executive Order
InfoBank (https://www.nj.gov/infobank/eo/) covers every administration back
to Hughes (1962) via one archive/index page per governor, but only the
Florio administration onward (1990-present) looks like a complete numbered
series - Hughes/Cahill/Byrne/Kean pages list only a handful of selected
orders each. Modern orders (roughly 2010-present) are text-selectable PDFs;
1990-2009 orders are mostly full-text HTML. There is no public JSON/API.

Design choice, same reasoning as virginia.py: this adapter runs
nj_eo_scraper.py as a SUBPROCESS rather than importing its internals, so the
scraper can be developed, tested, and rerun standalone, and so this file
stays a thin declaration-plus-orchestration layer rather than growing scraper
logic of its own.

Unlike Virginia, New Jersey does not need a current-vs-historical split: one
scraper walks the entire governor directory in a single pass, since the
official archive already treats all administrations (however incompletely
for pre-1990 ones) as instances of the same table structure. There is
therefore only one subprocess call here, not two.

UPDATE (2026-09-04): the first draft of nj_eo_scraper.py was live-tested and
found several real bugs (double-counted administrations, an unscoped nested
Cahill.hml -> Sherrill Archive link mixup, an unrecognized Murphy date
format, missed passive-voice relationship phrasing, and a document-banner
misclassification bug). All were patched in the scraper; see its module
docstring for the full list. Two things patched there but not yet
re-validated against the live site: dedup-by-administration-code and the
broadened relationship regexes. structured_archive_coverage_start below has
been corrected to 1990-01-18, confirmed directly from Florio EO 1's own
text ("the 18th day of January", 1990) rather than assumed.

Round 3 also handles shifted table cells (including Christie EO 109) and can
recover a missing table date from an order's signed GIVEN clause (including
Whitman EO 46). Whitman EOs 23 and 26 remain blank-dated because their own
official document signature fields are blank; no date is inferred.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STATE = "NJ"

CAPABILITIES = {
    "state": STATE,
    "structured_archive_available": True,
    "structured_archive_source": (
        "New Jersey Governor Executive Orders InfoBank "
        "(https://www.nj.gov/infobank/eo/)"
    ),
    "structured_archive_coverage_start": "1990-01-18",   # confirmed from Florio EO 1's own text
    "structured_archive_coverage_end": None,               # ongoing
    "pdf_text_available": True,
    "ocr_required": False,
    "current_governor_source_available": True,
    "current_governor_source": (
        "https://www.nj.gov/infobank/eo/057sherrill/approved/eo_archive.shtml"
    ),
    "current_governor_source_start": "2026-01-20",          # Sherrill inauguration
    "manual_only": False,
    "known_gaps": [
        "The official directory reaches back to 1962, but the Hughes, "
        "Cahill, Byrne, and Kean administration pages list only a handful "
        "of selected orders each, not a complete series. Automated "
        "comprehensive-candidate coverage begins with Florio in 1990.",
        "Pre-1962 executive orders are not represented in the public "
        "directory at all.",
        "Archive metadata has occasional incorrect governor labels, mixed "
        "date formats, date typos, blank descriptions, and cross-"
        "administration order-number collisions (numbering resets each "
        "administration); the linked document's own signer and date should "
        "be treated as authoritative over the surrounding table row when "
        "they conflict. This adapter does not currently perform that "
        "cross-check automatically - see notes.",
        "Whitman Executive Orders 23 and 26 have blank dates in both the "
        "archive table and the official document signature fields. They are "
        "retained without dates and excluded from date-window joins.",
        "Order relationships (terminates/extends/amends/etc.) are "
        "extracted with a best-effort regex pass over table descriptions "
        "and document text; NOT all relationships will be caught, "
        "especially for older, inconsistently-worded orders. Treat "
        "nj_order_relationships.csv as a candidate list, not a verified one.",
    ],
    "notes": (
        "New Jersey can be collected automatically without routine OCR, but "
        "unlike Virginia its order-relationship structure is many-to-many "
        "(one termination order can end several prior emergencies at once), "
        "so this adapter also produces nj_order_relationships.csv alongside "
        "the Virginia-style declarations_for_join.csv. Termination and "
        "rescission orders are excluded from the join file - they carry no "
        "storm to date-match against - but are used to backfill an end_date "
        "on the declaration(s) they terminate, where a relationship could "
        "be confidently extracted."
    ),
}


def _run(cmd, cwd):
    print("  running: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def collect(workdir=".", scripts_dir=None):
    """Run the New Jersey scraper and return (path, coverage_note) for the
    Virginia-compatible declarations_for_join.csv, ready for
    eo_storm_join.py.

    Unlike virginia.py there is only one scraper to run, so there is no
    partial-success branching to speak of: either it produces a join file
    (coverage = the 1990-present provisional range, with the known-gaps
    caveat surfaced in the coverage note) or it fails outright and this
    raises, matching virginia.py's behavior when both of its scrapes fail.
    """
    workdir = Path(workdir)
    scripts_dir = Path(scripts_dir) if scripts_dir else Path(__file__).resolve().parents[2]
    workdir.mkdir(parents=True, exist_ok=True)

    actions_out = workdir / "nj_emergency_actions_all.csv"
    relationships_out = workdir / "nj_order_relationships.csv"
    join_out = workdir / "declarations_for_join.csv"

    print("New Jersey adapter: collecting executive orders (1962-present, "
          "structured from 1990)...")
    ok = _run(
        [
            sys.executable, str(scripts_dir / "nj_eo_scraper.py"),
            "--actions-out", str(actions_out),
            "--relationships-out", str(relationships_out),
            "--join-out", str(join_out),
        ],
        cwd=workdir,
    )

    if not ok or not join_out.exists():
        raise RuntimeError(
            "New Jersey adapter: scrape failed; no declarations collected. "
            "Check nj_eo_scraper.py output above for the specific failure."
        )

    coverage = (
        "1990-present (structured, provisional start date - see adapter "
        "notes); 1962-1989 selectively represented only, not systematically "
        "collected"
    )
    print("New Jersey adapter: coverage = " + coverage)
    return join_out, coverage


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the New Jersey state-evidence adapter standalone")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    path, coverage = collect(workdir=args.workdir)
    print("\nDone. Declarations file: " + str(path))
    print("Coverage: " + coverage)
