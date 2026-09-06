import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_SPEC = importlib.util.spec_from_file_location("build_plus", str(Path(__file__).parent / "build-plus.py"))
bp = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("build_plus", bp)
_SPEC.loader.exec_module(bp)


IMPLEMENTED_STATE = {
    "name": "New Jersey",
    "abbreviation": "NJ",
    "slug": "new-jersey",
    "adapter_status": "implemented",
}
PLANNED_STATE = {
    "name": "Some Future State",
    "abbreviation": "XX",
    "slug": "some-future-state",
    "adapter_status": "planned",
}


class ConditionalStormJoinHardeningTests(unittest.TestCase):
    """A state marked 'implemented' is expected to have both
    eo_storm_join.py and a state-action CSV; their absence there means
    something broke and must hard-fail the build. A state that isn't
    'implemented' yet (e.g. 'planned') is still mid-rollout, so the same
    absence is a benign, expected skip. Either way, a soft-skipped state
    must never be treated as having produced fresh output this run -
    storm_pipeline_ran must stay False unless a join subprocess actually
    executed and succeeded.
    """

    def setUp(self):
        self.tmp_paths = []

    def _state_dir(self, name):
        path = Path(f"/tmp/_build_plus_test_{name}")
        path.mkdir(parents=True, exist_ok=True)
        self.tmp_paths.append(path)
        return path

    def tearDown(self):
        import shutil

        for path in self.tmp_paths:
            shutil.rmtree(path, ignore_errors=True)

    def test_implemented_missing_join_script_is_hard_failure(self):
        state_dir = self._state_dir("implemented_missing_script")
        note, failed, ran = bp.run_storm_pipeline(IMPLEMENTED_STATE, state_dir, Path("fake.csv"))
        self.assertTrue(failed)
        self.assertFalse(ran)
        self.assertIn("failed", note.lower())

    def test_implemented_missing_action_csv_is_hard_failure(self):
        repo_root = self._state_dir("implemented_missing_csv_repo")
        (repo_root / "plus" / "new-jersey").mkdir(parents=True, exist_ok=True)
        original = (bp.load_state_actions, bp.load_federal_declarations, bp.load_storm_match_rows, bp.load_severity_rows)
        bp.load_state_actions = lambda state, sd: ([], None)
        bp.load_federal_declarations = lambda repo_root, abbr: []
        bp.load_storm_match_rows = lambda sd: ([], None)
        bp.load_severity_rows = lambda sd: ([], None)
        try:
            summary = bp.process_state(
                IMPLEMENTED_STATE, repo_root, collect=False, join_storms=True, dry_run=False
            )
        finally:
            bp.load_state_actions, bp.load_federal_declarations, bp.load_storm_match_rows, bp.load_severity_rows = original
        self.assertTrue(summary["storm_pipeline_failed"])
        self.assertIn("failed", summary["storm_pipeline_note"].lower())

    def test_planned_missing_join_script_is_soft_skip_and_not_marked_ran(self):
        state_dir = self._state_dir("planned_missing_script")
        note, failed, ran = bp.run_storm_pipeline(PLANNED_STATE, state_dir, Path("fake.csv"))
        self.assertFalse(failed)
        self.assertFalse(ran)
        self.assertIn("skipped", note.lower())

    def test_planned_missing_action_csv_is_soft_skip_and_not_marked_ran(self):
        repo_root = self._state_dir("planned_missing_csv_repo")
        (repo_root / "plus" / "some-future-state").mkdir(parents=True, exist_ok=True)
        original = (bp.load_state_actions, bp.load_federal_declarations, bp.load_storm_match_rows, bp.load_severity_rows)
        bp.load_state_actions = lambda state, sd: ([], None)
        bp.load_federal_declarations = lambda repo_root, abbr: []
        bp.load_storm_match_rows = lambda sd: ([], None)
        bp.load_severity_rows = lambda sd: ([], None)
        try:
            summary = bp.process_state(
                PLANNED_STATE, repo_root, collect=False, join_storms=True, dry_run=False
            )
        finally:
            bp.load_state_actions, bp.load_federal_declarations, bp.load_storm_match_rows, bp.load_severity_rows = original
        self.assertFalse(summary["storm_pipeline_failed"])
        self.assertIn("skipped", summary["storm_pipeline_note"].lower())

    def test_soft_skipped_state_never_reads_stale_output_as_fresh(self):
        # The concrete failure mode this whole feature guards against: a
        # stale eo_storm_matches.csv sitting on disk from a prior run must
        # never be read via the "trust this as freshly generated" path
        # (read_csv_rows) just because this call happened to skip cleanly.
        state_dir_name = "stale_output_guard"
        repo_root = self._state_dir(f"{state_dir_name}_repo")
        state_dir = repo_root / "plus" / "some-future-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "eo_storm_matches.csv").write_text("declaration_id,EVENT_TYPE\nSTALE-1,Old Data\n")

        direct_read_calls = []
        filtered_read_calls = []
        original = (
            bp.read_csv_rows,
            bp.load_storm_match_rows,
            bp.load_severity_rows,
            bp.load_state_actions,
            bp.load_federal_declarations,
        )
        bp.read_csv_rows = lambda path: direct_read_calls.append(path) or []
        bp.load_storm_match_rows = lambda sd: (filtered_read_calls.append(sd) or [], None)
        bp.load_severity_rows = lambda sd: ([], None)
        bp.load_state_actions = lambda state, sd: ([], None)
        bp.load_federal_declarations = lambda repo_root, abbr: []
        try:
            summary = bp.process_state(
                PLANNED_STATE, repo_root, collect=False, join_storms=True, dry_run=False
            )
        finally:
            (
                bp.read_csv_rows,
                bp.load_storm_match_rows,
                bp.load_severity_rows,
                bp.load_state_actions,
                bp.load_federal_declarations,
            ) = original

        self.assertFalse(summary["storm_pipeline_failed"])
        self.assertEqual(
            len(direct_read_calls), 0, "read_csv_rows must not be called for a soft-skipped state"
        )
        self.assertEqual(
            len(filtered_read_calls), 1, "the normal filtered-preference loader must be used instead"
        )

    def test_successful_run_still_sets_ran_true(self):
        # Regression: the hardening must not break the ordinary success path.
        state_dir = self._state_dir("success_path")
        (state_dir / "eo_storm_join.py").write_text("# stub\n")
        action_path = state_dir / "declarations.csv"
        action_path.write_text("eo_number,event_description,date_signed\n")

        def fake_run(cmd, **kwargs):
            out_idx = cmd.index("--out")
            sev_idx = cmd.index("--severity-out")
            Path(cmd[out_idx + 1]).write_text("a\n")
            Path(cmd[sev_idx + 1]).write_text("b\n")
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        original_run = bp.subprocess.run
        bp.subprocess.run = fake_run
        try:
            note, failed, ran = bp.run_storm_pipeline(IMPLEMENTED_STATE, state_dir, action_path)
        finally:
            bp.subprocess.run = original_run
        self.assertFalse(failed)
        self.assertTrue(ran)


if __name__ == "__main__":
    unittest.main()
