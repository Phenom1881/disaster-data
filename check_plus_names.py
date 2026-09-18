#!/usr/bin/env python3
"""Validate plus/ naming against the rules build-plus.py actually enforces.

Two separate conventions govern this tree, and nothing checked that they
were being followed until a run failed on a missing file:

  1. Directory names use hyphens. build-plus.py uses state["slug"] raw
     as the directory under plus/, so plus/new-jersey/.

  2. Adapter filenames use underscores. build-plus.py derives the name
     from state["name"] when the manifest does not set adapter_file:

         state["name"].lower().replace(" ", "_").replace("-", "_") + ".py"

     so plus/new-jersey/new_jersey.py. Hyphen directory, underscore file,
     same state. That pairing looks like a mistake and is not.

An adapter_file key in the manifest overrides rule 2, which is a legitimate
escape hatch but also a way for a typo to sit undetected: build-plus.py
treats a missing adapter as a warning and keeps going, so the state simply
reports no data rather than failing the run.

This script fails loudly instead. Run it before collection, not after.

Exit 0 clean, 1 on any error. Warnings alone do not fail the run.
"""

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = {"abbreviation", "name", "slug", "adapter_status"}


def derived_adapter_name(name: str) -> str:
    """Mirror of build-plus.py's fallback. Keep these two in sync."""
    return name.lower().replace(" ", "_").replace("-", "_") + ".py"


def derived_slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=Path("scripts/plus/state-manifest.json"))
    ap.add_argument("--plus-root", type=Path, default=Path("plus"),
                    help="directory holding the per-state folders")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    args = ap.parse_args()

    if not args.manifest.exists():
        print(f"ERROR manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    states = manifest.get("states", [])
    if not states:
        print("ERROR manifest has no states", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}

    for state in states:
        missing = REQUIRED_KEYS - set(state)
        if missing:
            errors.append(
                f"{state.get('abbreviation', '?')}: missing manifest keys "
                f"{', '.join(sorted(missing))}"
            )
            continue

        ab = state["abbreviation"]
        name = state["name"]
        slug = state["slug"]

        if ab in seen:
            errors.append(f"{ab}: duplicate abbreviation")
        seen[ab] = name

        if slug != derived_slug(name):
            warnings.append(
                f"{ab}: slug '{slug}' is not '{name}' lowercased with hyphens "
                f"('{derived_slug(name)}')"
            )

        if "_" in slug:
            errors.append(
                f"{ab}: slug '{slug}' uses an underscore. Directories use "
                f"hyphens; only the adapter filename uses underscores."
            )

        adapter_name = state.get("adapter_file") or derived_adapter_name(name)

        if "-" in adapter_name:
            errors.append(
                f"{ab}: adapter_file '{adapter_name}' uses a hyphen. "
                f"build-plus.py's fallback would produce "
                f"'{derived_adapter_name(name)}'."
            )

        if state.get("adapter_file") and state["adapter_file"] != derived_adapter_name(name):
            # Legal, but it means the manifest is the only thing keeping this
            # state wired up. Worth saying out loud.
            warnings.append(
                f"{ab}: adapter_file '{state['adapter_file']}' overrides the "
                f"derived name '{derived_adapter_name(name)}'"
            )

        state_dir = args.plus_root / slug
        adapter_path = state_dir / adapter_name

        if not state_dir.exists():
            errors.append(f"{ab}: state directory not found: {state_dir}")
            continue

        if not adapter_path.exists():
            # This is the failure build-plus.py currently swallows as a
            # warning, which is why a naming slip shows up as a state with
            # no data rather than as a broken build.
            near = sorted(p.name for p in state_dir.glob("*.py"))
            errors.append(
                f"{ab}: adapter not found: {adapter_path}"
                + (f" (present: {', '.join(near)})" if near else " (no .py files in directory)")
            )
            continue

        text = adapter_path.read_text(encoding="utf-8", errors="replace")
        if "def collect(" not in text:
            errors.append(
                f"{ab}: {adapter_path} does not define collect(); "
                f"build-plus.py's import_adapter() will reject it"
            )

        # Declaration counts on the Plus pages come from whichever file
        # candidate_action_files() finds FIRST, not from the all-actions
        # file. Checking that the first configured name exists catches the
        # case where a scraper writes its output under a name the manifest
        # does not list.
        configured = state.get("action_files", [])
        if configured and not any((state_dir / n).exists() for n in configured):
            warnings.append(
                f"{ab}: none of the configured action_files exist yet "
                f"({', '.join(configured)}); the state will fall back to "
                f"build-plus.py's defaults or report no data"
            )

    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}", file=sys.stderr)

    print(
        f"\nchecked {len(states)} states: "
        f"{len(errors)} error(s), {len(warnings)} warning(s)"
    )

    if errors:
        return 1
    if warnings and args.strict:
        print("failing on warnings because --strict was passed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
