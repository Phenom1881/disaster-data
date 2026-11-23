"""Tests for scripts/plus_health_preview.py: its grades are the health check's
own, what it says about a branch, and a full preview of a copy of this
repository with records removed.

    cd scripts && python -m unittest test_plus_health_preview
"""
import csv
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "plus_health_preview", str(ROOT / "scripts" / "plus_health_preview.py"))
preview = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preview)
grader = preview.load_grader(ROOT)

NOW = "2026-11-29T12:00:00+00:00"
STATE = {"name": "Testland", "abbreviation": "XX", "slug": "testland"}
NUMBERS = {"actions": 40, "dated": 40, "titled": 40, "linked": 40, "storm_matched": 30}


class FakeBuilder:
    @staticmethod
    def extract_coverage_start_label(abbreviation, coverage, count):
        return "Since 2000"


def summary(source="ok", count=40, **extra):
    base = {"source_status": source, "metrics": {"action_count": count, "federal_declaration_count": 60},
            "generated_on": "2026-11-08", "collection_error": "", "kept_saved_records": 0, "retried": False}
    base.update(extra)
    return base


def runs(*sources):
    return [{"at": f"2026-11-0{day} 12:00 UTC", "source": source, "declarations": 40}
            for day, source in enumerate(sources, start=1)]


def projection(state_summary, history, numbers=NUMBERS, last_good="2026-11-01 12:00 UTC"):
    now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    count = state_summary["metrics"]["action_count"]
    prior = {"declarations": count, "history": history, "last_good_collection": last_good}
    return preview.project(grader, FakeBuilder, STATE, state_summary, numbers, history, prior,
                           now.date(), now)


def row(grade="green", reasons=(), declarations=25, dated=None, gaps=(), clean_runs=None,
        source="ok", name="Testland", notes=()):
    upcoming = {"grade": grade, "reasons": list(reasons), "notes": list(notes), "source": source,
                "declarations": declarations, "dated": declarations if dated is None else dated,
                "titled": declarations, "linked": declarations, "storm_matched": 10, "excluded": 0,
                "last_good_collection": None, "history": []}
    return {"name": name, "next": upcoming, "gaps": list(gaps),
            "clean": clean_runs if clean_runs is not None else [{"grade": grade, "reasons": list(reasons)}]}


def prediction(**states):
    return {"at": "2026-11-29 12:00 UTC", "order": list(states), "states": states}


class SameAsTheHealthCheckTests(unittest.TestCase):
    def test_the_next_refresh_is_graded_as_plus_health_grades_it(self):
        out = Path(tempfile.mkdtemp(prefix="preview_health_"))
        try:
            committed = ROOT / "plus" / "_health" / "health.json"
            shutil.copy(committed, out / "health.json")
            subprocess.run([sys.executable, str(ROOT / "scripts" / "plus_health.py"),
                            "--out-dir", str(out), "--now", NOW], check=True, capture_output=True)
            expected = json.loads((out / "health.json").read_text(encoding="utf-8"))["states"]
            got = preview.predict(ROOT, json.loads(committed.read_text(encoding="utf-8")), ROOT,
                                  preview.parse_now(NOW), rebuild=False, clean_runs=0)["states"]
            self.assertEqual(sorted(got), sorted(expected))
            for ab, state in got.items():
                for key in preview.KEPT:
                    self.assertEqual(state["next"][key], expected[ab].get(key), f"{ab} {key}")
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_it_will_not_write_into_a_checkout(self):
        with self.assertRaises(SystemExit):
            preview.predict(ROOT, None, ROOT, preview.parse_now(NOW))


class CollectionTests(unittest.TestCase):
    def test_what_the_source_returned_last_time_is_carried_over(self):
        built = {"source_status": "not_collected", "retried": False, "coverage": "Since 2000",
                 "metrics": {"action_count": 41}}
        last = {"source_status": "failed", "retried": True, "retry_status": "failed",
                "collection_error": "403 Client Error", "kept_saved_records": 0,
                "metrics": {"action_count": 40}}
        got = preview.carry_collection(built, last)
        self.assertEqual(grader.infer_source(got), "failed")
        self.assertEqual(got["collection_error"], "403 Client Error")
        self.assertEqual(got["metrics"], {"action_count": 41})      # this build's count, not last time's
        self.assertEqual(preview.carry_collection(built, None)["source_status"], "not_collected")

    def test_a_failed_source_works_on_a_clean_run(self):
        failed = summary("failed", retried=True, retry_status="failed", collection_error="403",
                         collection_failed=True, kept_saved_records=3)
        got = preview.clean(grader, failed)
        self.assertEqual(grader.infer_source(got), "ok")
        self.assertEqual((got["kept_saved_records"], got["collection_error"]), (0, ""))
        self.assertNotIn("retry_status", got)
        self.assertEqual(failed["source_status"], "failed")        # the original is left alone

    def test_a_partial_source_is_taken_to_return_part_again(self):
        got = preview.clean(grader, summary("partial", count=81, kept_saved_records=12))
        self.assertEqual((grader.infer_source(got), got["kept_saved_records"]), ("partial", 12))


class ProjectionTests(unittest.TestCase):
    def test_a_failure_two_runs_back_clears_on_the_second_refresh(self):
        graded = projection(summary(), runs("ok", "empty", "ok", "ok"))
        self.assertEqual([run["grade"] for run in graded[:2]], ["yellow", "green"])
        self.assertEqual(preview.when_green(graded, False, []),
                         "Green on refresh 2 from now if collecting keeps working.")

    def test_a_source_failing_now_needs_four_clean_refreshes(self):
        failed = summary("failed", retried=True, retry_status="failed", collection_error="403")
        graded = projection(failed, runs("ok", "failed", "ok", "failed"))
        self.assertEqual([run["grade"] for run in graded[:4]], ["yellow", "yellow", "yellow", "green"])
        self.assertEqual(preview.when_green(graded, True, []),
                         "If collecting works from the next refresh on: green on refresh 4 from now.")

    def test_a_source_that_leaves_out_saved_records_does_not_clear_by_itself(self):
        graded = projection(summary("partial", count=81, kept_saved_records=12),
                            runs("partial", "partial", "partial", "partial"),
                            numbers=dict.fromkeys(("actions", "dated", "titled", "linked"), 81)
                            | {"storm_matched": 60})
        self.assertEqual({run["grade"] for run in graded}, {"yellow"})
        self.assertEqual(preview.when_green(graded, False, graded[-1]["reasons"]),
                         "Does not turn green on its own.")
        self.assertIn("left out 12 of 81", preview.when_green(graded, False, []))


class BranchChangeTests(unittest.TestCase):
    def test_a_fall_the_branch_causes_is_listed_with_its_reason(self):
        fall = "Declarations fell from 25 to 23 since the last run."
        base = prediction(CT=row(name="Connecticut"))
        branch = prediction(CT=row("yellow", [fall], declarations=23, name="Connecticut"))
        self.assertEqual(preview.branch_changes(base, branch),
                         ["- CT Connecticut: green without this branch, yellow with it. With it: "
                          + fall + " Declarations 25 to 23."])

    def test_closed_federal_gaps_are_named(self):
        base = prediction(IL=row(declarations=32, gaps=["EM-3161", "DR-1469", "DR-1416"], name="Illinois"))
        branch = prediction(IL=row(declarations=35, gaps=["EM-3161"], name="Illinois"))
        line, = preview.branch_changes(base, branch)
        self.assertIn("green either way.", line)
        self.assertIn("Federal declarations with no state declaration 3 to 1 (closes DR-1469, DR-1416).",
                      line)

    def test_counts_that_move_with_the_declarations_are_not_repeated(self):
        base = prediction(IL=row(declarations=32))
        self.assertEqual(preview.number_changes(base["states"]["IL"]["next"], row(declarations=35)["next"]),
                         "Declarations 32 to 35.")
        self.assertEqual(preview.number_changes(base["states"]["IL"]["next"],
                                                row(declarations=35, dated=33)["next"]),
                         "Declarations 32 to 35; with a signing date 32 to 33.")

    def test_a_state_the_branch_does_not_change_is_not_listed(self):
        same = prediction(FL=row("yellow", ["Collection failed or produced no declarations on 1 of the "
                                            "3 runs before this one."], name="Florida"))
        self.assertEqual(preview.branch_changes(same, same), [])
        report = preview.render(same, same, None, {"branch": "Branch x (abc)", "base": "origin/main (abc)"})
        self.assertIn("Nothing: every state grades the same", report)
        self.assertNotIn("\u2014", report)
        self.assertNotIn("\u2013", report)


class OutlookTests(unittest.TestCase):
    def test_a_failing_state_says_what_happens_either_way(self):
        reason = ("Collecting from the state source failed on this run and on the retry (403), 2 runs in "
                  "a row.")
        last = {"states": {"MO": {"grade": "yellow", "reasons": [reason.replace("2 runs", "1 run")]}}}
        clean_runs = [{"grade": "yellow", "reasons": ["x"]}] * 3 + [{"grade": "green", "reasons": []}]
        ahead = prediction(MO=row("yellow", [reason], source="failed", clean_runs=clean_runs, name="Missouri"))
        line, = preview.outlook(last, ahead)
        self.assertIn("Next refresh, if collecting fails again: yellow. If collecting works from the next "
                      "refresh on: green on refresh 4 from now.", line)

    def test_green_states_staying_green_are_left_out_and_a_fall_clears(self):
        fall = "Declarations fell from 25 to 23 since the last run."
        last = {"states": {"CT": {"grade": "yellow", "reasons": [fall]}, "VA": {"grade": "green", "reasons": []}}}
        ahead = prediction(CT=row(declarations=23, name="Connecticut"), VA=row(name="Virginia"))
        self.assertEqual(preview.outlook(last, ahead),
                         [f"- CT Connecticut: yellow now: {fall} Next refresh: green."])


class ChangedCodeTests(unittest.TestCase):
    def test_scraper_changes_are_named_and_tests_are_not(self):
        scratch = Path(tempfile.mkdtemp(prefix="preview_code_"))
        try:
            for tree, text in (("base", "A = 1\n"), ("branch", "A = 2\n")):
                folder = scratch / tree / "plus" / "testland"
                folder.mkdir(parents=True)
                (folder / "tl_scraper.py").write_text(text)
                (folder / "test_tl_scraper.py").write_text(text)
                (folder / "eo_storm_join.py").write_text("same\n")
            (scratch / "branch" / "plus" / "testland" / "tl_new.py").write_text("B = 1\n")
            self.assertEqual(preview.changed_code(scratch / "base", scratch / "branch"),
                             ["plus/testland/tl_new.py", "plus/testland/tl_scraper.py"])
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def csv_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_rows(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FullPreviewTests(unittest.TestCase):
    """A copy of this repository's last commit with three hand-added records
    removed from one state and two FMCSA entries from another, previewed
    against that commit: those two states are listed, and no other."""

    def test_records_a_branch_drops_are_listed_and_nothing_else_is(self):
        scratch = Path(tempfile.mkdtemp(prefix="preview_full_"))
        try:
            branch = scratch / "branch"
            preview.extract("HEAD", branch)
            states = grader.load_states(branch)

            def rows_in(state, name):
                path = branch / "plus" / state["slug"] / name
                return len(csv_rows(path)[1]) if path.exists() else 0

            by_hand = max((s for s in states if not s.get("fmcsa_supplement")),
                          key=lambda s: rows_in(s, "manual_declarations.csv"))
            by_fmcsa = max((s for s in states if s.get("fmcsa_supplement")),
                           key=lambda s: rows_in(s, "fmcsa_declarations.csv"))
            self.assertGreaterEqual(rows_in(by_hand, "manual_declarations.csv"), 5)
            self.assertGreaterEqual(rows_in(by_fmcsa, "fmcsa_declarations.csv"), 3)

            manual = branch / "plus" / by_hand["slug"] / "manual_declarations.csv"
            fields, rows = csv_rows(manual)
            write_rows(manual, fields, rows[:-3])
            _, supplement = csv_rows(branch / "plus" / by_fmcsa["slug"] / "fmcsa_declarations.csv")
            gone = {r["declaration_id"].split("-FMCSA-", 1)[1] for r in supplement[-2:]}
            entries = branch / "plus" / "_fmcsa" / "entries.csv"
            fields, rows = csv_rows(entries)
            write_rows(entries, fields, [r for r in rows if r["entry_id"] not in gone])

            report = subprocess.run([sys.executable, str(ROOT / "scripts" / "plus_health_preview.py"),
                                     "--branch-root", str(branch), "--base", "HEAD", "--now", NOW],
                                    check=True, capture_output=True, text=True).stdout
            section = report.split("## What this branch changes on the next refresh", 1)[1]
            section = section.split("\n## ", 1)[0]
            listed = {line.split()[1]: line for line in section.splitlines() if line.startswith("- ")}
            self.assertEqual(sorted(listed), sorted([by_hand["abbreviation"], by_fmcsa["abbreviation"]]))
            last = json.loads((branch / "plus" / "_health" / "health.json").read_text(encoding="utf-8"))
            for ab, line in listed.items():
                before, after = map(int, re.search(r"Declarations (\d+) to (\d+)[.;]", line).groups())
                self.assertLess(after, before, line)
                previous = last["states"][ab]["declarations"]
                if after < previous:
                    self.assertIn(f"Declarations fell from {previous} to {after} since the last run.", line)
            self.assertNotIn("\u2014", report)
            self.assertNotIn("\u2013", report)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
