#!/usr/bin/env python3
"""Write plus/<slug>/api.json for every state from the files already in the
repository, without collecting from any state source or rerunning the storm
join.

build-plus.py writes the same file on every Plus refresh, so this script is
only needed to publish the API files between refreshes (for example right
after the API first ships, or after a hand edit to a state's CSV). It uses
build-plus.py's own functions, so the output is what a refresh would write.

    python scripts/export_plus_api.py            # all states
    python scripts/export_plus_api.py --states VA,TN
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_plus", HERE / "build-plus.py")
bp = importlib.util.module_from_spec(spec)
sys.modules["build_plus"] = bp
spec.loader.exec_module(bp)


def storm_rows_for(state_dir: Path) -> list[dict]:
    # The weekly refresh renders each page from the storm join it just ran
    # (eo_storm_matches.csv), so prefer that file when it exists.
    fresh = state_dir / "eo_storm_matches.csv"
    if fresh.exists():
        return bp.read_csv_rows(fresh)
    rows, _ = bp.load_storm_match_rows(state_dir)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--states", default="all")
    parser.add_argument("--repo-root", type=Path, default=HERE.parent)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    states = bp.select_states(bp.load_manifest(bp.DEFAULT_MANIFEST), args.states)
    written = 0
    for state in states:
        state_dir = repo_root / "plus" / state["slug"]
        summary_path = state_dir / "state-summary.json"
        if not summary_path.exists():
            print(f"{state['abbreviation']}: no state-summary.json yet, skipped")
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        actions, _ = bp.load_state_actions(state, state_dir)
        federal = bp.load_federal_declarations(repo_root, state["abbreviation"])
        crosswalk = bp.build_crosswalk(actions, federal, bp.group_by_declaration(storm_rows_for(state_dir)))
        bp.write_api_file(state, state_dir, summary, actions, crosswalk)
        written += 1
        print(f"{state['abbreviation']}: {len(actions)} state declarations, "
              f"{sum(1 for row in crosswalk if row['federal_declaration'])} with a federal match")
    print(f"wrote {written} {bp.API_FILE} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
