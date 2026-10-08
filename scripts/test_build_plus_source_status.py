"""Tests for what build-plus.py records about each state's source, and for
the end-of-run retry of states whose source failed or returned nothing.
Offline, with fake adapters.

    cd scripts && python -m unittest test_build_plus_source_status
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

os.environ["PLUS_RETRY_DELAY"] = "0"
_SPEC = importlib.util.spec_from_file_location("build_plus", str(Path(__file__).parent / "build-plus.py"))
bp = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("build_plus", bp)
_SPEC.loader.exec_module(bp)
bp.RETRY_DELAY_SECONDS = 0

HEADER = "declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
SAVED = HEADER + (
    "XX-EO-26-21,Gov,26-21,FLOODING,2026-08-13,https://x/26-21.pdf\n"
    "XX-EO-26-03,Gov,26-03,WINTER STORM,2026-01-23,https://x/26-03.pdf\n"
)
STATE = {"name": "Testland", "abbreviation": "XX", "slug": "testland",
         "adapter_status": "implemented", "adapter_file": "testland.py",
         "action_files": ["declarations_for_join.csv"]}

WRITES_EVERYTHING = '''
    from pathlib import Path
    SAVED = Path(__file__).with_name("declarations_for_join.csv").read_text()
    def collect(workdir=".", scripts_dir=None):
        p = Path(workdir) / "declarations_for_join.csv"
        p.write_text(SAVED)
        return p, "note"
'''
WRITES_ONE = '''
    from pathlib import Path
    def collect(workdir=".", scripts_dir=None):
        p = Path(workdir) / "declarations_for_join.csv"
        p.write_text("{header}XX-EO-26-21,Gov,26-21,FLOODING,2026-08-13,https://x/26-21.pdf\\n")
        return p, "note"
'''.replace("{header}", HEADER.replace("\n", "\\n"))
WRITES_NOTHING = '''
    from pathlib import Path
    def collect(workdir=".", scripts_dir=None):
        p = Path(workdir) / "declarations_for_join.csv"
        p.write_text("{header}")
        return p, "note"
'''.replace("{header}", HEADER.replace("\n", "\\n"))
RAISES = '''
    def collect(workdir=".", scripts_dir=None):
        raise RuntimeError("503 Server Error")
'''
EXITS = '''
    import sys
    def collect(workdir=".", scripts_dir=None):
        sys.exit(2)
'''


class SourceStatusTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="source_status_"))
        self.state_dir = self.root / "plus" / STATE["slug"]
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "declarations_for_join.csv").write_text(SAVED, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_with(self, body):
        (self.state_dir / "testland.py").write_text(textwrap.dedent(body), encoding="utf-8")
        return bp.process_state(STATE, self.root, collect=True, join_storms=False, dry_run=True)

    def test_source_that_returns_everything_is_ok(self):
        summary = self.run_with(WRITES_EVERYTHING)
        self.assertEqual(summary["source_status"], "ok")
        self.assertEqual(summary["source_records_returned"], 2)
        self.assertEqual(summary["source_records_saved_before"], 2)

    def test_source_that_misses_a_saved_record_is_partial(self):
        summary = self.run_with(WRITES_ONE)
        self.assertEqual(summary["source_status"], "partial")
        self.assertEqual(summary["metrics"]["action_count"], 2)

    def test_source_that_returns_nothing_is_empty_even_though_the_page_looks_full(self):
        # New Hampshire's case: saved records kept, page unchanged, source dead.
        summary = self.run_with(WRITES_NOTHING)
        self.assertEqual(summary["source_status"], "empty")
        self.assertEqual(summary["metrics"]["action_count"], 2)
        self.assertFalse(summary["collection_failed"])

    def test_adapter_error_is_failed(self):
        summary = self.run_with(RAISES)
        self.assertEqual(summary["source_status"], "failed")
        self.assertIn("503", summary["collection_error"])

    def test_state_kept_by_hand_reports_manual_not_failed(self):
        # Ohio's case: the feed answers 406; its records are kept by hand.
        (self.state_dir / "testland.py").write_text(textwrap.dedent(RAISES), encoding="utf-8")
        summary = bp.process_state(dict(STATE, manual_source=True), self.root, collect=True,
                                   join_storms=False, dry_run=True)
        self.assertEqual(summary["source_status"], "manual")
        self.assertEqual(summary["metrics"]["action_count"], 2)
        self.assertIn("503", summary["collection_error"])

    def test_state_kept_by_hand_still_reports_a_working_source(self):
        (self.state_dir / "testland.py").write_text(textwrap.dedent(WRITES_EVERYTHING), encoding="utf-8")
        summary = bp.process_state(dict(STATE, manual_source=True), self.root, collect=True,
                                   join_storms=False, dry_run=True)
        self.assertEqual(summary["source_status"], "ok")

    def test_hand_added_rows_show_but_do_not_count_against_the_source(self):
        # manual_declarations.csv rows are on the page, but the source is
        # judged only on its own file, so it still returned everything.
        (self.state_dir / "manual_declarations.csv").write_text(
            HEADER + "XX-SOE-2011-05-27,Gov,,FLOODING BY HAND,2011-05-27,https://news/x\n", encoding="utf-8")
        summary = self.run_with(WRITES_EVERYTHING)
        self.assertEqual(summary["source_status"], "ok")
        self.assertEqual(summary["metrics"]["action_count"], 3)

    def test_adapter_calling_sys_exit_fails_its_state_not_the_build(self):
        summary = self.run_with(EXITS)
        self.assertEqual(summary["source_status"], "failed")

    def test_no_collection_is_recorded_as_such(self):
        summary = bp.process_state(STATE, self.root, collect=False, join_storms=False, dry_run=True)
        self.assertEqual(summary["source_status"], "not_collected")
        self.assertIsNone(summary["source_records_returned"])


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="retry_"))
        self.state_dir = self.root / "plus" / STATE["slug"]
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "declarations_for_join.csv").write_text(SAVED, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def first_pass(self, body):
        (self.state_dir / "testland.py").write_text(textwrap.dedent(body), encoding="utf-8")
        return bp.process_state(STATE, self.root, collect=True, join_storms=False, dry_run=False)

    def test_state_that_recovers_on_retry_is_rebuilt_and_marked(self):
        first = self.first_pass(RAISES)
        self.assertEqual(first["source_status"], "failed")
        (self.state_dir / "testland.py").write_text(textwrap.dedent(WRITES_EVERYTHING), encoding="utf-8")
        [after] = bp.retry_failed_sources([STATE], [first], self.root, join_storms=False)
        self.assertEqual(after["source_status"], "ok")
        self.assertTrue(after["retried"])
        self.assertEqual(after["first_attempt"]["status"], "failed")
        saved = json.loads((self.state_dir / "state-summary.json").read_text())
        self.assertTrue(saved["retried"])
        self.assertEqual(saved["source_status"], "ok")

    def test_state_that_fails_again_keeps_its_saved_records_and_says_so(self):
        first = self.first_pass(WRITES_NOTHING)
        [after] = bp.retry_failed_sources([STATE], [first], self.root, join_storms=False)
        self.assertEqual(after["source_status"], "empty")
        self.assertEqual(after["retry_status"], "empty")
        self.assertEqual(after["metrics"]["action_count"], 2)
        self.assertEqual(len((self.state_dir / "declarations_for_join.csv").read_text().splitlines()), 3)

    def test_healthy_states_are_not_retried(self):
        first = self.first_pass(WRITES_EVERYTHING)
        [after] = bp.retry_failed_sources([STATE], [first], self.root, join_storms=False)
        self.assertIs(after, first)
        self.assertFalse(after["retried"])


FAKE_JOIN = """
import argparse, os
from pathlib import Path
parser = argparse.ArgumentParser()
for flag in ("--declarations", "--state", "--out", "--severity-out", "--overrides"):
    parser.add_argument(flag)
args, _ = parser.parse_known_args()
folder = os.environ.get("PLUS_NCEI_CACHE_DIR", "")
Path(args.out).with_name("seen_cache.txt").write_text(f"{folder}|{Path(folder).is_dir() if folder else False}")
Path(args.out).write_text("declaration_id,EVENT_TYPE\\n")
Path(args.severity_out).write_text("declaration_id\\n")
"""


class SharedStormFolderTests(unittest.TestCase):
    """End to end through build-plus.py: every state's storm join in one run
    sees the same NOAA folder, and the folder is gone when the run ends."""

    def test_states_share_one_folder_that_is_removed_after_the_run(self):
        import subprocess
        root = Path(tempfile.mkdtemp(prefix="shared_join_"))
        try:
            for slug in ("delaware", "rhode-island"):
                folder = root / "plus" / slug
                folder.mkdir(parents=True)
                (folder / "declarations_for_join.csv").write_text(SAVED, encoding="utf-8")
                (folder / "eo_storm_join.py").write_text(FAKE_JOIN, encoding="utf-8")
            env = dict(os.environ)
            env.pop("PLUS_NCEI_CACHE_DIR", None)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "build-plus.py"), "--repo-root", str(root),
                 "--states", "DE,RI", "--join-storms"],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            seen = {(root / "plus" / slug / "seen_cache.txt").read_text() for slug in ("delaware", "rhode-island")}
            self.assertEqual(len(seen), 1, seen)                 # the same folder for both states
            folder, existed = seen.pop().split("|")
            self.assertEqual(existed, "True")
            self.assertFalse(Path(folder).exists())                # removed at the end of the run
            summary = json.loads((root / "plus" / "delaware" / "state-summary.json").read_text())
            self.assertIsNotNone(summary["timing"]["storm_join_seconds"])
            self.assertIn("TIME total:", result.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TimingTests(unittest.TestCase):
    def test_collection_time_is_recorded(self):
        root = Path(tempfile.mkdtemp(prefix="timing_"))
        try:
            state_dir = root / "plus" / STATE["slug"]
            state_dir.mkdir(parents=True)
            (state_dir / "declarations_for_join.csv").write_text(SAVED, encoding="utf-8")
            (state_dir / "testland.py").write_text(textwrap.dedent(WRITES_EVERYTHING), encoding="utf-8")
            summary = bp.process_state(STATE, root, collect=True, join_storms=False, dry_run=True)
            self.assertGreaterEqual(summary["timing"]["collect_seconds"], 0)
            self.assertIsNone(summary["timing"]["storm_join_seconds"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
