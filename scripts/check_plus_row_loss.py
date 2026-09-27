"""Last check before a Plus refresh is committed: no saved state record may
disappear.

build-plus.py already merges saved records back after each state's scrape
(keep_saved_actions). This runs once more over the finished tree as a
backstop, for any path that merge does not reach: a new file type, an
adapter that writes somewhere unexpected, or a bug in the merge itself.

For every protected state file (declarations_for_join*, *emergency_actions*,
*order_relationships*, state_actions.csv) it compares the working copy with
the last commit, puts back any committed row the refresh dropped, and prints
one line per file it repaired. Rows signed before 1970 are not put back
into the files the site reads, since it leaves those off on purpose. It never fails the run; it only
restores.

    python -u scripts/check_plus_row_loss.py [--repo-root .]
"""
from __future__ import annotations

import argparse
import csv
import io
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROTECTED_PATTERNS = (
    "declarations_for_join*.csv",
    "*emergency_actions*.csv",
    "*order_relationships*.csv",
    "state_actions.csv",
)


def load_builder(repo_root: Path):
    spec = importlib.util.spec_from_file_location(
        "build_plus", str(repo_root / "scripts" / "build-plus.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_plus", module)
    spec.loader.exec_module(module)
    return module


def committed_bytes(repo_root: Path, path: Path) -> bytes | None:
    relative = path.relative_to(repo_root).as_posix()
    result = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=repo_root,
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    bp = load_builder(repo_root)

    manifest = json.loads((repo_root / "scripts" / "plus" / "state-manifest.json").read_text())
    states = manifest if isinstance(manifest, list) else manifest["states"]

    repaired = 0
    for state in states:
        state_dir = repo_root / "plus" / state["slug"]
        if not state_dir.is_dir():
            continue
        paths = sorted({p for pattern in PROTECTED_PATTERNS for p in state_dir.glob(pattern)})
        for path in paths:
            old = committed_bytes(repo_root, path)
            if not old:
                continue
            old_fields, old_rows = bp._csv_rows_from_bytes(old)
            cutoff_applies = path.name in bp.candidate_action_files(state)
            if cutoff_applies and any(bp.before_cutoff(r) for r in old_rows):
                # Rows before 1970 are left off on purpose, so they are not
                # "lost". Compare against the committed copy without them;
                # otherwise this reported them as put back on 2026-09-26
                # even though the cutoff removed them again straight after.
                kept_rows = [r for r in old_rows if not bp.before_cutoff(r)]
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=old_fields, restval="",
                                        extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                writer.writerows(kept_rows)
                old = buffer.getvalue().encode("utf-8")
                old_rows = kept_rows
            if not old_rows:
                continue
            try:
                counts = bp._merge_saved_rows(path, old, state["abbreviation"])
            except Exception as exc:
                path.write_bytes(old)
                print(f"WARNING {state['abbreviation']}: {path.name}: could not compare "
                      f"({exc}); put back the committed copy", file=sys.stderr)
                repaired += 1
                continue
            if counts["kept"]:
                print(f"WARNING {state['abbreviation']}: {path.name}: put back "
                      f"{counts['kept']} committed row(s) this refresh dropped")
                repaired += 1

    print(f"Row-loss check: {repaired} file(s) repaired." if repaired
          else "Row-loss check: no saved rows lost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
