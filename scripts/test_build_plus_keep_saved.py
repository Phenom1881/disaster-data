"""Tests for build-plus.py's keep-saved-records safeguard.

A --collect run must never let a failed or partial scrape erase state
declarations that were already saved. These run offline with fake adapters.

    cd scripts && python -m unittest test_build_plus_keep_saved
"""
import csv
import importlib.util
import io
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location("build_plus", str(Path(__file__).parent / "build-plus.py"))
bp = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("build_plus", bp)
_SPEC.loader.exec_module(bp)

HEADER = "declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
SAVED = HEADER + (
    "XX-EO-26-21,Gov,26-21,DECLARING A STATEWIDE DISASTER EMERGENCY DUE TO FLOODING,2026-08-13,https://x/26-21.pdf\n"
    "XX-EO-26-03,Gov,26-03,DECLARATION OF A STATEWIDE DISASTER EMERGENCY DUE TO A SEVERE WINTER STORM,2026-01-23,https://x/26-03.pdf\n"
    "XX-EO-24-4,Gov,24-4,\"DECLARING A DISASTER EMERGENCY IN DELAWARE, JEFFERSON, & RANDOLPH COUNTIES\",2024-03-21,https://x/24-4.pdf\n"
)
GARBLED = 'March 14 Wildfires&#34;}}" id="title-55d50c27e2" class="cmp-title"> <h1 class="cmp-title__text">Gov'

STATE = {"name": "Testland", "abbreviation": "XX", "slug": "testland",
         "adapter_status": "implemented", "adapter_file": "testland.py",
         "action_files": ["declarations_for_join.csv"]}


def rows_of(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


class KeepSavedRecordsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="keep_saved_"))
        self.state_dir = self.root / "plus" / STATE["slug"]
        self.state_dir.mkdir(parents=True)
        self.csv = self.state_dir / "declarations_for_join.csv"
        self.csv.write_text(SAVED, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _merge_after(self, new_text):
        saved = bp.snapshot_action_files(STATE, self.state_dir)
        if new_text is None:
            self.csv.unlink()
        else:
            self.csv.write_text(new_text, encoding="utf-8")
        return bp.keep_saved_actions(STATE, saved)

    def test_empty_scrape_keeps_every_saved_record(self):
        counts = self._merge_after(HEADER)
        self.assertEqual(counts["kept"], 3)
        self.assertEqual({r["declaration_id"] for r in rows_of(self.csv)},
                         {"XX-EO-26-21", "XX-EO-26-03", "XX-EO-24-4"})

    def test_partial_scrape_carries_missing_rows_and_fills_blank_dates(self):
        new = HEADER + "XX-EO-26-21,Gov,26-21,DECLARING A STATEWIDE DISASTER EMERGENCY DUE TO FLOODING,,https://x/new.pdf\n"
        counts = self._merge_after(new)
        rows = {r["declaration_id"]: r for r in rows_of(self.csv)}
        self.assertEqual(counts["kept"], 2)
        self.assertEqual(counts["filled"], 1)
        self.assertEqual(rows["XX-EO-26-21"]["date_signed"], "2026-08-13")          # saved date kept
        self.assertEqual(rows["XX-EO-26-21"]["archive_record_url"], "https://x/new.pdf")  # new value wins

    def test_new_values_win_when_present(self):
        new = SAVED.replace("2024-03-21", "2024-03-22")
        counts = self._merge_after(new)
        rows = {r["declaration_id"]: r for r in rows_of(self.csv)}
        self.assertEqual(rows["XX-EO-24-4"]["date_signed"], "2024-03-22")
        self.assertEqual(counts, {"kept": 0, "filled": 0, "cleaned": 0})

    def test_garbled_title_keeps_saved_clean_title(self):
        new = HEADER + "XX-EO-24-4,Gov,24-4,\"%s\",2024-03-21,https://x/24-4.pdf\n" % GARBLED.replace('"', '""')
        counts = self._merge_after(new)
        rows = {r["declaration_id"]: r for r in rows_of(self.csv)}
        self.assertEqual(counts["cleaned"], 1)
        self.assertEqual(rows["XX-EO-24-4"]["event_description"],
                         "DECLARING A DISASTER EMERGENCY IN DELAWARE, JEFFERSON, & RANDOLPH COUNTIES")

    def test_shared_order_numbers_are_not_conflated(self):
        # Different governors reuse order numbers. Matching is on declaration_id only.
        self.csv.write_text(HEADER + "NJ-MURPHY-EO-15,Murphy,15,FLOODING,2018-02-01,u\n", encoding="utf-8")
        counts = self._merge_after(HEADER + "NJ-SHERRILL-EO-15,Sherrill,15,WINTER STORM,,u\n")
        rows = {r["declaration_id"]: r for r in rows_of(self.csv)}
        self.assertEqual(set(rows), {"NJ-MURPHY-EO-15", "NJ-SHERRILL-EO-15"})
        self.assertEqual(rows["NJ-SHERRILL-EO-15"]["date_signed"], "")   # not borrowed from Murphy's order
        self.assertEqual(counts["kept"], 1)

    def test_deleted_file_is_recreated(self):
        counts = self._merge_after(None)
        self.assertEqual(counts["kept"], 3)
        self.assertEqual(len(rows_of(self.csv)), 3)

    def test_row_removed_from_committed_file_stays_removed(self):
        self.csv.write_text(SAVED.replace(
            "XX-EO-24-4,Gov,24-4,\"DECLARING A DISASTER EMERGENCY IN DELAWARE, JEFFERSON, & RANDOLPH COUNTIES\",2024-03-21,https://x/24-4.pdf\n", ""),
            encoding="utf-8")
        self._merge_after(HEADER)
        self.assertNotIn("XX-EO-24-4", {r["declaration_id"] for r in rows_of(self.csv)})

    def test_unchanged_scrape_leaves_file_bytes_alone(self):
        self._merge_after(SAVED)
        self.assertEqual(self.csv.read_text(encoding="utf-8"), SAVED)

    def test_merge_failure_restores_saved_bytes(self):
        saved = bp.snapshot_action_files(STATE, self.state_dir)
        self.csv.write_text(HEADER, encoding="utf-8")
        with mock.patch.object(bp, "_merge_saved_rows", side_effect=RuntimeError("boom")):
            bp.keep_saved_actions(STATE, saved)
        self.assertEqual(self.csv.read_text(encoding="utf-8"), SAVED)

    def test_field_larger_than_csv_default_limit_merges(self):
        # Wyoming's actions file carries whole order texts; one is over 128 KB.
        big = "WHEREAS flooding " * 12000                                   # about 200 KB
        self.csv.write_text(HEADER + 'XX-EO-26-40,Gov,26-40,"%s",2026-09-01,u\n' % big, encoding="utf-8")
        counts = self._merge_after(HEADER + "XX-EO-26-41,Gov,26-41,FLOODING,2026-09-20,u\n")
        rows = {r["declaration_id"]: r for r in rows_of(self.csv)}
        self.assertEqual(counts["kept"], 1)
        self.assertEqual(set(rows), {"XX-EO-26-40", "XX-EO-26-41"})     # new row not thrown away
        self.assertEqual(rows["XX-EO-26-40"]["event_description"], big)

    def test_form_feed_inside_a_field_stays_one_row(self):
        # PDF text often carries form feeds; they are not row breaks.
        self.csv.write_text(HEADER + "XX-EO-26-50,Gov,26-50,PAGE ONE\x0cPAGE TWO,2026-09-02,u\n", encoding="utf-8")
        self._merge_after(HEADER)
        rows = rows_of(self.csv)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_description"], "PAGE ONE\x0cPAGE TWO")

    def test_file_without_ids_does_not_collapse_into_one_row(self):
        # Ohio's bulletin list has no id, number or date column. Every row
        # used to get the key "OH", so the merge kept one row of eight.
        state = dict(STATE, action_files=["bulletins.csv"])
        path = self.state_dir / "bulletins.csv"
        header = "title,pub_date,hazard_guess,source_url\n"
        path.write_text(header + "Flood emergency,2026-09-22,flood,https://x/1\n"
                        "Tornado emergency,2026-07-07,severe_storm,https://x/2\n"
                        "Winter storm emergency,2026-01-24,winter,https://x/3\n", encoding="utf-8")
        saved = bp.snapshot_action_files(state, self.state_dir)
        path.write_text(header + "New storm emergency,2026-10-01,,https://x/4\n", encoding="utf-8")
        bp.keep_saved_actions(state, saved)
        rows = rows_of(path)
        self.assertEqual([r["source_url"] for r in rows], ["https://x/4", "https://x/1", "https://x/2", "https://x/3"])
        self.assertEqual(rows[0]["hazard_guess"], "")              # not borrowed from an unrelated row

    def test_an_id_listed_twice_keeps_both_rows(self):
        self.csv.write_text(HEADER + "XX-EO-9,Gov,9,FLOOD PART ONE,2020-01-01,u1\n"
                                     "XX-EO-9,Gov,9,FLOOD PART TWO,2020-01-02,u2\n", encoding="utf-8")
        counts = self._merge_after(HEADER)
        self.assertEqual(counts["kept"], 2)
        self.assertEqual([r["event_description"] for r in rows_of(self.csv)], ["FLOOD PART ONE", "FLOOD PART TWO"])

    def test_markup_detection(self):
        self.assertTrue(bp.looks_like_markup(GARBLED))
        self.assertFalse(bp.looks_like_markup("DECLARING A DISASTER EMERGENCY IN DELAWARE, JEFFERSON, & RANDOLPH COUNTIES"))
        self.assertFalse(bp.looks_like_markup("State of Emergency - Beaver, Texas, and Woodward counties (wildfires)"))


class ProcessStateTests(unittest.TestCase):
    """End to end through process_state() with a fake adapter."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="keep_saved_ps_"))
        self.state_dir = self.root / "plus" / STATE["slug"]
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "declarations_for_join.csv").write_text(SAVED, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _adapter(self, body):
        (self.state_dir / "testland.py").write_text(textwrap.dedent(body), encoding="utf-8")

    def test_adapter_that_writes_nothing_keeps_saved_records(self):
        self._adapter('''
            from pathlib import Path
            def collect(workdir=".", scripts_dir=None):
                p = Path(workdir) / "declarations_for_join.csv"
                p.write_text("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\\n")
                return p, "Test coverage note"
        ''')
        summary = bp.process_state(STATE, self.root, collect=True, join_storms=False, dry_run=True)
        self.assertEqual(summary["metrics"]["action_count"], 3)
        self.assertEqual(summary["kept_saved_records"], 3)
        self.assertIn("3 saved records kept", summary["coverage"])
        self.assertFalse(summary["collection_failed"])

    def test_adapter_that_truncates_then_raises_keeps_saved_records(self):
        self._adapter('''
            from pathlib import Path
            def collect(workdir=".", scripts_dir=None):
                (Path(workdir) / "declarations_for_join.csv").write_text("")
                raise RuntimeError("site unreachable")
        ''')
        summary = bp.process_state(STATE, self.root, collect=True, join_storms=False, dry_run=True)
        self.assertTrue(summary["collection_failed"])
        self.assertEqual(summary["metrics"]["action_count"], 3)

    def test_healthy_adapter_adds_new_records_and_reports_nothing_kept(self):
        self._adapter('''
            from pathlib import Path
            SAVED = Path(__file__).with_name("declarations_for_join.csv").read_text()
            def collect(workdir=".", scripts_dir=None):
                p = Path(workdir) / "declarations_for_join.csv"
                p.write_text(SAVED + "XX-EO-26-30,Gov,26-30,DECLARING A DISASTER EMERGENCY DUE TO FLOODING,2026-09-20,https://x/26-30.pdf\\n")
                return p, "Test coverage note"
        ''')
        summary = bp.process_state(STATE, self.root, collect=True, join_storms=False, dry_run=True)
        self.assertEqual(summary["metrics"]["action_count"], 4)
        self.assertEqual(summary["kept_saved_records"], 0)
        self.assertNotIn("saved record", summary["coverage"])


if __name__ == "__main__":
    unittest.main()
