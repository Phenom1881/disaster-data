"""Tests for scripts/plus_health.py: the grading rules, history, change
notes, and a full run over the repository's own 50 states.

    cd scripts && python -m unittest test_plus_health
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("plus_health", str(ROOT / "scripts" / "plus_health.py"))
health = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("plus_health", health)
_SPEC.loader.exec_module(health)

STATE = {"name": "Testland", "abbreviation": "XX", "slug": "testland"}
TODAY = date(2026, 9, 27)
GOOD = {"actions": 40, "dated": 40, "titled": 40, "linked": 40, "storm_matched": 30}


def summary(source="ok", count=40, federal=60, **extra):
    base = {"source_status": source, "metrics": {"action_count": count, "federal_declaration_count": federal},
            "generated_on": "2026-09-27", "collection_error": "", "kept_saved_records": 0, "retried": False}
    base.update(extra)
    return base


def history(*sources):
    return [{"at": f"run {i}", "source": s, "declarations": 40} for i, s in enumerate(sources)]


def grade(summary_, numbers=GOOD, hist=None, previous=None, since="Since 2000"):
    hist = hist if hist is not None else history(summary_.get("source_status", "ok"))
    return health.grade_state(STATE, summary_, numbers, hist, previous, TODAY, since)


class GradeTests(unittest.TestCase):
    def test_healthy_state_is_green(self):
        self.assertEqual(grade(summary())["grade"], "green")

    def test_source_that_returned_nothing_is_red_even_with_a_full_page(self):
        result = grade(summary(source="empty", retried=True, retry_status="empty"),
                       hist=history("empty", "empty", "empty"))
        self.assertEqual(result["grade"], "red")
        self.assertIn("returned nothing on this run and on the retry", result["reasons"][0])
        self.assertIn("3 runs in a row", result["reasons"][0])
        self.assertIn("saved from earlier runs", result["reasons"][0])

    def test_failed_source_names_the_error(self):
        result = grade(summary(source="failed", collection_error="Collection failed: 503 Server Error"))
        self.assertIn("(503 Server Error)", result["reasons"][0])

    def test_recovered_on_retry_is_green_with_a_note(self):
        result = grade(summary(source="ok", retried=True, retry_status="ok",
                               first_attempt={"status": "failed", "error": "timeout"}))
        self.assertEqual(result["grade"], "green")
        self.assertIn("recovered on the retry", result["notes"][0])

    def test_source_that_failed_recently_is_yellow(self):
        result = grade(summary(), hist=history("ok", "failed", "ok", "ok"))
        self.assertEqual(result["grade"], "yellow")
        self.assertIn("1 of the 3 runs", result["reasons"][0])

    def test_failures_older_than_the_window_do_not_count(self):
        self.assertEqual(grade(summary(), hist=history("failed", "ok", "ok", "ok", "ok"))["grade"], "green")

    def test_no_declarations_is_red(self):
        result = grade(summary(count=0), numbers=dict(GOOD, actions=0, dated=0, titled=0, linked=0),
                       since="Since 2023")
        self.assertEqual(result["grade"], "red")
        self.assertIn("since 2023", result["reasons"][0])

    def test_mostly_undated_is_red_and_partly_undated_is_yellow(self):
        self.assertEqual(grade(summary(), numbers=dict(GOOD, dated=10))["grade"], "red")
        partly = grade(summary(), numbers=dict(GOOD, dated=30))
        self.assertEqual(partly["grade"], "yellow")
        self.assertIn("10 of 40 declarations have no signing date", partly["reasons"][0])

    def test_one_missing_title_reads_correctly(self):
        result = grade(summary(count=5), numbers=dict(GOOD, actions=5, dated=5, titled=4, linked=5,
                                                      storm_matched=5))
        self.assertIn("1 of 5 declarations has no title.", result["reasons"])

    def test_thin_coverage_is_yellow(self):
        result = grade(summary(count=4, federal=259), numbers=dict(GOOD, actions=4, dated=4, titled=4,
                                                                   linked=4, storm_matched=4),
                       since="Since 2016")
        self.assertEqual(result["grade"], "yellow")
        self.assertIn("Only 4 declarations against 259 federal ones (since 2016)", result["reasons"][0])

    def test_low_storm_match_rate_is_yellow(self):
        result = grade(summary(count=208), numbers=dict(GOOD, actions=208, dated=208, titled=208,
                                                        linked=208, storm_matched=2))
        self.assertIn("Only 2 of 208 dated declarations matched any storm record.", result["reasons"])

    def test_small_partial_return_is_a_note_and_large_one_is_yellow(self):
        small = grade(summary(source="partial", kept_saved_records=1))
        self.assertEqual(small["grade"], "green")
        self.assertIn("left out 1 saved record", small["notes"][0])
        large = grade(summary(source="partial", kept_saved_records=10))
        self.assertEqual(large["grade"], "yellow")

    def test_drop_in_declarations(self):
        self.assertEqual(grade(summary(count=38), previous={"declarations": 40})["grade"], "yellow")
        self.assertEqual(grade(summary(count=20), previous={"declarations": 40})["grade"], "red")

    def test_page_not_rebuilt_this_run_is_red(self):
        result = grade(summary(generated_on="2026-09-20"))
        self.assertEqual(result["grade"], "red")
        self.assertIn("not rebuilt", result["reasons"][0])

    def test_missing_summary_is_red(self):
        result = health.grade_state(STATE, None, GOOD, [], None, TODAY, "")
        self.assertEqual(result["grade"], "red")


class SourceInferenceTests(unittest.TestCase):
    def test_recorded_status_wins(self):
        self.assertEqual(health.infer_source({"source_status": "partial"}), "partial")

    def test_retry_result_is_the_final_word(self):
        self.assertEqual(health.infer_source({"source_status": "failed", "retried": True,
                                              "retry_status": "ok"}), "ok")

    def test_older_summaries_are_read_from_their_numbers(self):
        self.assertEqual(health.infer_source({"collection_failed": True}), "failed")
        self.assertEqual(health.infer_source({"kept_saved_records": 6, "metrics": {"action_count": 6}}), "empty")
        self.assertEqual(health.infer_source({"kept_saved_records": 1, "metrics": {"action_count": 52}}), "partial")
        self.assertEqual(health.infer_source({"metrics": {"action_count": 5}}), "unknown")


class ChangesTests(unittest.TestCase):
    def test_grade_changes_are_listed_with_the_reason(self):
        states = [STATE]
        previous = {"generated_at_label": "last Sunday", "states": {"XX": {"grade": "green"}}}
        result = {"counts": {"green": 0, "yellow": 0, "red": 1},
                  "states": {"XX": {"name": "Testland", "grade": "red", "reasons": ["Site down."]}}}
        text = health.render_changes(result, previous, states)
        self.assertIn("**Testland** went from green to red. Site down.", text)

    def test_no_changes_means_no_comment(self):
        previous = {"states": {"XX": {"grade": "green"}}}
        result = {"counts": {"green": 1, "yellow": 0, "red": 0},
                  "states": {"XX": {"name": "Testland", "grade": "green", "reasons": []}}}
        self.assertEqual(health.render_changes(result, previous, [STATE]), "")


class FullRunTests(unittest.TestCase):
    def test_every_state_is_graded_and_the_reports_are_written(self):
        out = Path(tempfile.mkdtemp(prefix="health_"))
        try:
            issue, changes = out / "issue.md", out / "changes.md"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "plus_health.py"),
                            "--out-dir", str(out), "--issue-body-out", str(issue),
                            "--changes-out", str(changes)], check=True, capture_output=True)
            data = json.loads((out / "health.json").read_text())
            self.assertEqual(len(data["states"]), 50)
            self.assertEqual(sum(data["counts"].values()), 50)
            report = issue.read_text()
            self.assertIn("# Plus health report", report)
            table = report.split("## Every state", 1)[1].split("<details>", 1)[0]
            rows = [line for line in table.splitlines() if line.startswith("|")]
            self.assertEqual(len(rows), 52)                    # header, rule, 50 states
            self.assertEqual({row.count("|") for row in rows}, {12})
            self.assertNotIn("—", report)
            self.assertNotIn("–", report)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TimingReportTests(unittest.TestCase):
    def test_slowest_states_are_listed_with_totals(self):
        states = [{"abbreviation": ab, "name": ab} for ab in ("AA", "BB", "CC")]
        result = {"states": {"AA": {"collect_seconds": 30.0, "storm_join_seconds": 5.0},
                             "BB": {"collect_seconds": 400.0, "storm_join_seconds": 20.0},
                             "CC": {"collect_seconds": None, "storm_join_seconds": None}}}
        lines = health.render_timing(result, states)
        text = "\n".join(lines)
        self.assertIn("took 7.2 min in all", text)
        self.assertIn("| BB | 6.7 min | 20 s |", text)
        self.assertLess(text.index("| BB |"), text.index("| AA |"))
        self.assertNotIn("| CC |", text)

    def test_no_timing_means_no_section(self):
        result = {"states": {"AA": {}}}
        self.assertEqual(health.render_timing(result, [{"abbreviation": "AA", "name": "AA"}]), [])


if __name__ == "__main__":
    unittest.main()
