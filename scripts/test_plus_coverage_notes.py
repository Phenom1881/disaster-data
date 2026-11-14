"""The refresh note and the manifest note must give the same start year.

A build without collection (build-plus.py --states XX) shows the coverage note
in scripts/plus/state-manifest.json. The weekly refresh (build-plus.py --states
all --collect --join-storms) shows the note the state adapter's collect()
returns instead. The start year read from that note sets the page's "Since"
label and the year federal_without_state() starts comparing from, so when the
two notes disagree the federal-gap list changes from one build to the next.
Nebraska's adapter said "1965-present" while its manifest said "2000-present",
so every refresh compared FEMA's declarations back to 1970 against orders the
adapter only keeps from 2000 on, and listed 60 gaps out of 64.
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(__file__).with_name("build-plus.py")
SPEC = importlib.util.spec_from_file_location("build_plus_notes_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

# Some adapters check that their scraper wrote its output files before they
# return a note. The stand-in run below writes an empty file for every
# --*-out path it is given, so every adapter's collect() runs here. New
# York was once left out of this check, and its refresh note said 2021 while
# its manifest said 2000.
NEEDS_REAL_COLLECTION = set()
JOIN_HEADER = "declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"


def scraper_run(cmd, *args, **kwargs):
    """A scraper run that succeeds, prints nothing, and writes its output files."""
    for flag, value in zip(cmd, list(cmd)[1:]):
        if isinstance(flag, str) and flag.startswith("--") and flag.endswith("-out"):
            Path(value).parent.mkdir(parents=True, exist_ok=True)
            Path(value).write_text(JOIN_HEADER, encoding="utf-8")
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def manifest_states():
    manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
    states = manifest["states"] if isinstance(manifest, dict) else manifest
    return [state for state in states if state.get("adapter_file")]


def refresh_note(state):
    """The note collect() returns, with the scraper call replaced by a run
    that succeeds and prints nothing."""
    path = ROOT / "plus" / state["slug"] / state["adapter_file"]
    spec = importlib.util.spec_from_file_location(f"adapter_note_{state['abbreviation']}", path)
    adapter = importlib.util.module_from_spec(spec)
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet), \
            tempfile.TemporaryDirectory() as tmp, mock.patch("subprocess.run", side_effect=scraper_run):
        spec.loader.exec_module(adapter)
        _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
    return note


class RefreshNoteTests(unittest.TestCase):
    def test_refresh_and_manifest_notes_start_in_the_same_year(self):
        could_not_run = set()
        for state in manifest_states():
            abbreviation = state["abbreviation"]
            try:
                note = refresh_note(state)
            except Exception:  # an adapter that needs its scraper's real output
                could_not_run.add(abbreviation)
                continue
            with self.subTest(state=abbreviation):
                self.assertEqual(
                    MODULE.coverage_start_year(abbreviation, note),
                    MODULE.coverage_start_year(abbreviation, state.get("coverage_note", "")),
                    f"{abbreviation}: refresh note {note[:70]!r} and manifest note "
                    f"{state.get('coverage_note', '')[:70]!r} start in different years",
                )
        # A new adapter that cannot run here has to be looked at, not skipped.
        self.assertEqual(could_not_run, NEEDS_REAL_COLLECTION)

    def test_refresh_and_manifest_notes_match_exactly(self):
        # The page shows the refresh note after every weekly run, so a shorter
        # refresh note drops whatever the manifest note names (gaps, sources).
        for state in manifest_states():
            with self.subTest(state=state["abbreviation"]):
                self.assertEqual(refresh_note(state), state.get("coverage_note", ""))

    def test_backfilled_states_start_where_their_data_does(self):
        # Arizona compares from 2000: its 2000-2001 emergencies are known by
        # month only (Auditor General report 04-04), so DR-1347 shows as a gap.
        expected = {"AZ": 2000, "NE": 2000, "OK": 2000, "WV": 2000, "MD": 2000}
        for state in manifest_states():
            if state["abbreviation"] in expected:
                self.assertEqual(MODULE.coverage_start_year(state["abbreviation"], refresh_note(state)),
                                 expected[state["abbreviation"]], state["abbreviation"])


if __name__ == "__main__":
    unittest.main()
