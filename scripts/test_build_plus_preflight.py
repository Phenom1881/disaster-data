"""A malformed hazard override fails the storm join, and that fails the whole
build. The preflight finds it before collection starts, so the run stops in
seconds instead of after 45 minutes of collecting (2026-10-07)."""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
spec = importlib.util.spec_from_file_location("build_plus", HERE / "build-plus.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

STATE = {"abbreviation": "OH", "name": "Ohio", "slug": "ohio", "action_files": ["declarations_for_join.csv"]}
HEADER = "declaration_id,hazard_category_override,review_note,source_url,event_date\n"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / "plus" / "ohio"
        self.dir.mkdir(parents=True)
        shutil.copy(REPO / "plus" / "ohio" / "eo_storm_join.py", self.dir / "eo_storm_join.py")
        (self.dir / "declarations_for_join.csv").write_text(
            "declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
            "OH-PROC-2024-003,Mike DeWine,,Storms,2024-10-02,u\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def overrides(self, row):
        (self.dir / "hazard_overrides.csv").write_text(HEADER + row + "\n", encoding="utf-8")

    def test_good_overrides_pass(self):
        self.overrides('OH-PROC-2024-003,"wind,flood",note,u,2024-09-27')
        self.assertEqual(bp.preflight_overrides([STATE], self.root), [])

    def test_blank_category_is_caught(self):
        self.overrides("OH-PROC-2024-003,,note,u,2024-09-27")
        [problem] = bp.preflight_overrides([STATE], self.root)
        self.assertIn("blank hazard_category_override", problem)
        self.assertTrue(problem.startswith("OH: plus/ohio/hazard_overrides.csv"))

    def test_bad_event_date_and_unknown_category_are_caught(self):
        self.overrides("OH-PROC-2024-003,flood,note,u,09/27/2024")
        self.assertEqual(len(bp.preflight_overrides([STATE], self.root)), 1)
        self.overrides("OH-PROC-2024-003,hail storm,note,u,")
        self.assertEqual(len(bp.preflight_overrides([STATE], self.root)), 1)

    def test_bad_inline_override_is_caught(self):
        (self.dir / "declarations_for_join.csv").write_text(
            "declaration_id,eo_number,event_description,date_signed,hazard_category_override\n"
            "OH-PROC-2024-003,,Storms,2024-10-02,not a hazard\n", encoding="utf-8")
        self.assertEqual(len(bp.preflight_overrides([STATE], self.root)), 1)

    def test_every_committed_state_passes(self):
        states = bp.load_manifest(bp.DEFAULT_MANIFEST)
        self.assertEqual(bp.preflight_overrides(states, REPO), [])


if __name__ == "__main__":
    unittest.main()
