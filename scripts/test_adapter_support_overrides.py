"""A scrape must not delete reviewed overrides for hand-added declarations.

Nine states share plus/<state>/_adapter_support.py. Its run() used to rebuild
hazard_overrides.csv from review_decisions.json alone, and deleted the file
when the reviews held no overrides, so the 2026-11-01 refresh removed all 40
of Iowa's reviewed rows for its hand-added proclamations. merge_overrides()
now keeps rows for declarations the scraper does not collect.

Run:  python -m unittest test_adapter_support_overrides
"""
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIES = sorted(ROOT.glob("plus/*/_adapter_support.py"))


def load(path):
    spec = importlib.util.spec_from_file_location("adapter_support_" + path.parent.name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class MergeOverridesTests(unittest.TestCase):
    def setUp(self):
        self.support = load(COPIES[0])
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "hazard_overrides.csv"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, rows, fields):
        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_every_state_copy_is_identical(self):
        self.assertGreater(len(COPIES), 1)
        digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in COPIES}
        self.assertEqual(len(digests), 1, [str(p) for p in COPIES])

    def test_hand_rows_survive_and_scraper_rows_follow_the_reviews(self):
        fields = ["declaration_id", "hazard_category_override", "review_note", "source_url", "event_date"]
        self.write([
            {"declaration_id": "XX-HAND-1", "hazard_category_override": "flood", "review_note": "hand", "source_url": "u1", "event_date": "2001-02-03"},
            {"declaration_id": "XX-EO-1", "hazard_category_override": "fire", "review_note": "old", "source_url": "u2", "event_date": "2010-01-01"},
            {"declaration_id": "XX-EO-2", "hazard_category_override": "winter", "review_note": "stale", "source_url": "u3", "event_date": ""},
        ], fields)
        generated = [
            {"declaration_id": "XX-EO-1", "hazard_category_override": "wind", "review_note": "new", "source_url": "u2"},
            {"declaration_id": "XX-EO-3", "hazard_category_override": "tropical", "review_note": "added", "source_url": "u4"},
        ]
        rows, out_fields = self.support.merge_overrides(self.path, generated, {"XX-EO-1", "XX-EO-2", "XX-EO-3"})
        self.assertIn("event_date", out_fields)
        self.assertEqual([r["declaration_id"] for r in rows], ["XX-HAND-1", "XX-EO-1", "XX-EO-3"])
        self.assertEqual(rows[0]["review_note"], "hand")
        self.assertEqual(rows[1]["hazard_category_override"], "wind")
        self.assertEqual(rows[1]["event_date"], "2010-01-01")

    def test_nothing_to_keep_means_no_rows(self):
        rows, _ = self.support.merge_overrides(self.path, [], {"XX-EO-1"})
        self.assertEqual(rows, [])

    def test_no_hand_added_override_would_be_lost_on_a_refresh(self):
        for copy in COPIES:
            state = copy.parent
            overrides, manual = state / "hazard_overrides.csv", state / "manual_declarations.csv"
            if not overrides.exists() or not manual.exists():
                continue
            hand = {r["declaration_id"] for r in read(manual)}
            reviews_path = state / "review_decisions.json"
            reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
            generated = [{"declaration_id": k, "hazard_category_override": v["hazard_category_override"],
                          "review_note": v.get("reason", ""), "source_url": v.get("source_url", "")}
                         for k, v in reviews.items() if v.get("hazard_category_override")]
            collected = {r["declaration_id"] for r in read(state / "declarations_for_join.csv")} - hand
            rows, _ = self.support.merge_overrides(overrides, generated, collected)
            kept = {r["declaration_id"] for r in rows}
            before = {r["declaration_id"] for r in read(overrides)}
            self.assertFalse((before & hand) - kept, state.name)


class FetchFailureTests(unittest.TestCase):
    """Colorado's 2000-2006 library PDFs began returning 404 on 2026-11-15.
    That refresh reclassified 120 Owens orders from blank text and dropped
    the two reviewed out-of-state exclusions (D-2005-008, D-2005-010)."""

    URL = "https://example.test/order.pdf"

    def setUp(self):
        self.support = load(COPIES[0])
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()
        self.support._PREVIOUS.clear()

    def record(self, title="Order"):
        return self.support.make_record("XX", title, self.URL, number="D-2005-008")

    def write_previous(self, **extra):
        row = dict.fromkeys(self.support.ACTION_FIELDS, "")
        row.update(declaration_id=self.record()["declaration_id"], document_url=self.URL,
                   full_text="Executive Order sending Colorado National Guard to Louisiana after Hurricane Katrina " * 2,
                   date_signed="2005-09-02", date_evidence="signature line", governor="Bill Owens")
        row.update(extra)
        with open(self.base / "xx_emergency_actions_all.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.support.ACTION_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)

    def test_a_failed_fetch_keeps_the_previous_text_and_date(self):
        self.write_previous()
        self.support.load_previous_records(self.base)
        r = self.record()
        self.assertTrue(self.support.keep_previous_text(r))
        self.assertIn("Katrina", r["full_text"])
        self.assertEqual(r["date_signed"], "2005-09-02")
        self.assertEqual(r["governor"], "Bill Owens")
        self.assertIn("previous refresh", r["date_evidence"])

    def test_enrich_record_falls_back_when_the_fetch_fails(self):
        self.write_previous()
        self.support.load_previous_records(self.base)
        original = self.support.fetch

        def refuse(url):
            raise RuntimeError("404 Client Error: Not Found for url: " + url)

        self.support.fetch = refuse
        try:
            r = self.support.enrich_record(self.record())
        finally:
            self.support.fetch = original
        self.assertIn("404", r["fetch_error"])
        self.assertEqual(r["date_signed"], "2005-09-02")

    def test_previous_text_is_not_reused_for_a_different_document(self):
        self.write_previous(document_url="https://example.test/other.pdf")
        self.support.load_previous_records(self.base)
        r = self.record()
        self.assertFalse(self.support.keep_previous_text(r))
        self.assertEqual(r["full_text"], "")

    def test_a_previous_failure_is_not_a_source(self):
        self.write_previous(fetch_error="404 Client Error")
        self.support.load_previous_records(self.base)
        self.assertFalse(self.support.keep_previous_text(self.record()))

    def test_a_reviewed_exclusion_keeps_its_override_without_a_readable_date(self):
        (self.base / "review_decisions.json").write_text(json.dumps({self.record()["declaration_id"]: {
            "decision": "override_exclude", "hazard_category_override": "exclude",
            "reason": "Sends assistance to another state", "source_url": self.URL}}))
        records, _, overrides = self.support.finalize([self.record()], self.base)
        self.assertEqual(records[0]["decision"], "override_exclude")
        self.assertEqual([o["hazard_category_override"] for o in overrides], ["exclude"])

    def test_an_undated_reviewed_exclusion_stays_out_of_the_join_file(self):
        import sys
        from unittest import mock
        (self.base / "review_decisions.json").write_text(json.dumps({self.record()["declaration_id"]: {
            "decision": "override_exclude", "hazard_category_override": "exclude",
            "reason": "Sends assistance to another state", "source_url": self.URL}}))
        argv = ["x", "--actions-out", str(self.base / "a.csv"), "--relationships-out", str(self.base / "r.csv"),
                "--join-out", str(self.base / "declarations_for_join.csv")]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            self.support.run(lambda: [self.record()], self.base)
        self.assertEqual(read(self.base / "declarations_for_join.csv"), [])
        self.assertEqual([r["hazard_category_override"] for r in read(self.base / "hazard_overrides.csv")], ["exclude"])

    def test_an_undated_declaration_still_goes_to_review(self):
        (self.base / "review_decisions.json").write_text(json.dumps({self.record()["declaration_id"]: {"decision": "include"}}))
        records, _, overrides = self.support.finalize([self.record()], self.base)
        self.assertEqual(records[0]["decision"], "review")


if __name__ == "__main__":
    unittest.main()
