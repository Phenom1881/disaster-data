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
import os
import tempfile
import unittest
from datetime import date
from unittest import mock
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

    def test_a_previous_failure_with_no_text_is_not_a_source(self):
        self.write_previous(fetch_error="404 Client Error", full_text="")
        self.support.load_previous_records(self.base)
        self.assertFalse(self.support.keep_previous_text(self.record()))

    def test_text_kept_once_is_kept_again_on_the_next_refresh(self):
        # 2026-11-18 and 2026-11-20: the rows kept on 2026-11-15 carried both
        # the text and that refresh's fetch_error, were skipped as failures,
        # and 120 Colorado orders came back blank a second time.
        note = "; text and date kept from the previous refresh because the document could not be fetched"
        self.write_previous(fetch_error="404 Client Error", date_evidence="signature line" + note)
        self.support.load_previous_records(self.base)
        r = self.record()
        self.assertTrue(self.support.keep_previous_text(r))
        self.assertIn("Katrina", r["full_text"])
        self.assertEqual(r["date_evidence"].count(note), 1)

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


class ReuseReadingTests(unittest.TestCase):
    """2026-11-22: every refresh downloaded every document again (about 2,900
    across these nine states), and Missouri's archive refused the runner on
    the run and on the retry. A clean earlier reading is now reused."""

    URL = "https://example.test/order.pdf"
    TODAY = date(2026, 11, 22)

    def setUp(self):
        self.support = load(COPIES[0])
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.calls = []
        self.original_fetch = self.support.fetch

        def counting_fetch(url, payload=None, headers=None):
            self.calls.append(url)
            raise RuntimeError("network not used in this test")

        self.support.fetch = counting_fetch
        self.support.REUSE_READINGS = True
        os.environ.pop("DDPLUS_REREAD_ALL", None)

    def tearDown(self):
        self.support.fetch = self.original_fetch
        self.support.REUSE_READINGS = False
        self.support._PREVIOUS.clear()
        os.environ.pop("DDPLUS_REREAD_ALL", None)
        self.dir.cleanup()

    def number_off_rotation(self):
        for n in range(1, 400):
            rid = self.support.make_record("XX", "Order", self.URL, number="D-2005-%03d" % n)["declaration_id"]
            slot = int(hashlib.sha256(rid.encode()).hexdigest(), 16) % self.support.REREAD_WEEKS
            if slot != self.TODAY.isocalendar()[1] % self.support.REREAD_WEEKS:
                return "D-2005-%03d" % n
        raise AssertionError("no number off this week's rotation")

    def number_on_rotation(self):
        for n in range(1, 400):
            rid = self.support.make_record("XX", "Order", self.URL, number="D-2005-%03d" % n)["declaration_id"]
            slot = int(hashlib.sha256(rid.encode()).hexdigest(), 16) % self.support.REREAD_WEEKS
            if slot == self.TODAY.isocalendar()[1] % self.support.REREAD_WEEKS:
                return "D-2005-%03d" % n
        raise AssertionError("no number on this week's rotation")

    def previous(self, number, **extra):
        r = self.support.make_record("XX", "Order", self.URL, number=number)
        row = dict.fromkeys(self.support.ACTION_FIELDS, "")
        row.update(declaration_id=r["declaration_id"], document_url=self.URL,
                   full_text="I, Bill Owens, Governor of the State of Colorado, order assistance after the flood " * 2,
                   date_signed="2005-09-02", date_evidence="listing; PDF/legal signature: this 2nd day of September, 2005")
        row.update(extra)
        with open(self.base / "xx_emergency_actions_all.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.support.ACTION_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)
        self.support.load_previous_records(self.base)
        return self.support.make_record("XX", "Order", self.URL, number=number)

    def test_a_clean_old_reading_is_reused_without_a_download(self):
        r = self.previous(self.number_off_rotation())
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [])
        self.assertIn("order assistance after the flood", r["full_text"])
        self.assertEqual(r["date_signed"], "2005-09-02")
        self.assertEqual(r["governor"], "Bill Owens")
        self.assertEqual(r["fetch_error"], "")

    def test_an_undated_reading_follows_the_rotation(self):
        r = self.previous(self.number_off_rotation(), date_signed="", date_evidence="listing")
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [])
        self.assertIn("order assistance after the flood", r["full_text"])
        self.calls.clear()
        r = self.previous(self.number_on_rotation(), date_signed="", date_evidence="listing")
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [self.URL])

    def test_a_scan_without_text_is_always_read(self):
        r = self.previous(self.number_off_rotation(), full_text="EXECUTIVE ORDER")
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [self.URL])

    def test_a_listing_date_is_not_carried_over(self):
        r = self.previous(self.number_off_rotation(), date_evidence="listing date", date_signed="2005-09-02")
        r["date_signed"] = "2005-09-03"
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [])
        self.assertEqual(r["date_signed"], "2005-09-03")

    def test_documents_are_read_again_when_due(self):
        cases = {
            "recent order": dict(number=self.number_off_rotation(), date_signed="2026-11-01"),
            "earlier failure": dict(number=self.number_off_rotation(), fetch_error="404 Client Error"),
            "this week's rotation": dict(number=self.number_on_rotation()),
        }
        for name, extra in cases.items():
            self.calls.clear()
            number = extra.pop("number")
            r = self.previous(number, **extra)
            with mock.patch("builtins.print"):
                self.support.enrich([r], today=self.TODAY)
            self.assertEqual(self.calls, [self.URL], name)

    def test_reread_all_and_direct_calls_read_every_document(self):
        number = self.number_off_rotation()
        os.environ["DDPLUS_REREAD_ALL"] = "1"
        r = self.previous(number)
        with mock.patch("builtins.print"):
            self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [self.URL])
        os.environ.pop("DDPLUS_REREAD_ALL")
        self.calls.clear()
        self.support.REUSE_READINGS = False
        r = self.previous(number)
        self.support.enrich([r], today=self.TODAY)
        self.assertEqual(self.calls, [self.URL])

    def test_run_turns_reuse_on(self):
        import sys
        argv = ["x", "--actions-out", str(self.base / "a.csv"), "--relationships-out", str(self.base / "r.csv"),
                "--join-out", str(self.base / "j.csv")]
        self.support.REUSE_READINGS = False
        seen = []
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            self.support.run(lambda: seen.append(self.support.REUSE_READINGS) or [self.support.make_record("XX", "Order", self.URL, number="D-2005-001")], self.base)
        self.assertEqual(seen, [True])



class RefusalTests(unittest.TestCase):
    """A refused request fails at once, and the error names who refused."""

    def setUp(self):
        self.support = load(COPIES[0])
        self.dir = tempfile.TemporaryDirectory()
        self.support.CACHE = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def refuse(self, status, headers, text):
        import requests
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response._content = text.encode()
        response.url = "https://example.gov/orders"
        return response

    def test_a_403_names_the_firewall_and_is_not_tried_again(self):
        response = self.refuse(403, {"Server": "AkamaiGHost", "Content-Type": "text/html"},
                               "<html><body><h1>Access Denied</h1> Reference #18.abc</body></html>")
        with mock.patch.object(self.support.requests, "get", return_value=response) as get:
            with self.assertRaises(RuntimeError) as failure:
                self.support.fetch("https://example.gov/orders")
        self.assertEqual(get.call_count, 1)
        message = str(failure.exception)
        self.assertIn("403", message)
        self.assertIn("Server=AkamaiGHost", message)
        self.assertIn("Access Denied", message)

    def test_a_404_is_reported_without_refusal_details(self):
        response = self.refuse(404, {"Server": "nginx"}, "Not Found")
        with mock.patch.object(self.support.requests, "get", return_value=response) as get:
            with self.assertRaises(RuntimeError) as failure:
                self.support.fetch("https://example.gov/missing")
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("Server=", str(failure.exception))

if __name__ == "__main__":
    unittest.main()
