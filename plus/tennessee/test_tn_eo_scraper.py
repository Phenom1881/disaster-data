import csv
import tempfile
import unittest
from pathlib import Path

import tn_eo_scraper as tn


class TennesseeScraperTests(unittest.TestCase):
    def action(self, governor="Bill Lee", number="105", title="No. 105 An Order to Provide Relief to Victims of Severe Weather and Flooding in Tennessee", date="2024-09-27"):
        return tn.Action(number, title, date, governor, "https://example.test/record", "https://example.test/order.pdf", "https://example.test/notice")

    def test_ids_include_governor_to_prevent_number_collisions(self):
        self.assertEqual(self.action().stable_id, "TN-BILLLEE-EO-105")
        self.assertNotEqual(self.action().stable_id, self.action("Bill Haslam").stable_id)

    def test_officially_corroborated_weather_order_is_declaration(self):
        self.assertEqual(tn.classify(self.action()), "declaration")

    def test_amendment_is_not_a_declaration(self):
        action=self.action(number="106", title="No. 106 An Order Amending Executive Order No. 105")
        self.assertEqual(tn.classify(action), "amendment")

    def test_join_excludes_modifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base=self.action(); amendment=self.action(number="106",title="No. 106 An Order Amending Executive Order No. 105")
            tn.write_outputs([base,amendment],root/"a.csv",root/"r.csv",root/"j.csv")
            with open(root/"j.csv",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual([row["declaration_id"] for row in rows],[base.stable_id])

    def test_hay_transport_reissues_count_as_declarations(self):
        for number, date in (("09", "2012-01-24"), ("44", "2015-02-18"), ("64", "2017-01-26")):
            self.assertEqual(tn.OFFICIAL_DECLARATIONS[("Bill Haslam", number)][0], date)
        here=Path(__file__).parent
        with open(here/"declarations_for_join.csv",encoding="utf-8") as handle:
            joined={row["declaration_id"]: row["date_signed"] for row in csv.DictReader(handle)}
        self.assertEqual(joined["TN-BILLHASLAM-EO-44"], "2015-02-18")
        self.assertEqual(joined["TN-BILLHASLAM-EO-64"], "2017-01-26")
        self.assertNotIn("TN-BILLHASLAM-EO-17", joined)

    def test_hand_added_winter_supply_orders(self):
        with open(Path(__file__).parent/"manual_declarations.csv",encoding="utf-8") as handle:
            rows=list(csv.DictReader(handle))
        ids=[row["declaration_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        dates={row["declaration_id"]: row["date_signed"] for row in rows}
        self.assertEqual(dates["TN-BILLHASLAM-EO-36"], "2014-02-19")
        self.assertEqual(dates["TN-SOE-2018-01-19"], "2018-01-19")
        for row in rows:
            self.assertRegex(row["date_signed"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(tn.HAZARD_RE.search(row["event_description"]), row["declaration_id"])


class OrderNumberTests(unittest.TestCase):
    def test_the_no0_7_typo_is_order_7_and_leading_zeros_are_kept(self):
        self.assertEqual(tn.NUMBER_RE.search("No0.7 An Emergency Order").group(1), "7")
        self.assertEqual(tn.NUMBER_RE.search("No.09 An Emergency Order").group(1), "09")
        self.assertEqual(tn.NUMBER_RE.search("No. 110 An Order").group(1), "110")
        self.assertIn(("Bill Lee", "7"), tn.OFFICIAL_DECLARATIONS)
        self.assertNotIn(("Bill Lee", "0"), tn.OFFICIAL_DECLARATIONS)


class StateOfEmergencyRowTests(unittest.TestCase):
    """Hand-added states of emergency TEMA declared by activating the
    state plan, each dated by a TEMA flash report or the proclamation
    that ended it."""

    def rows(self):
        import csv, os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "manual_declarations.csv"), newline="", encoding="utf-8") as handle:
            return {r["declaration_id"]: r for r in csv.DictReader(handle)}

    def test_dates_and_sources(self):
        rows = self.rows()
        expected = {"TN-SOE-2012-02-29": ("2012-02-29", "Bill Haslam", "104.pdf"),
                    "TN-SOE-2022-01-06": ("2022-01-06", "Bill Lee", "2022/1/6/"),
                    "TN-SOE-2022-02-03": ("2022-02-03", "Bill Lee", "2022/2/3/"),
                    "TN-SOE-2022-12-23": ("2022-12-23", "Bill Lee", "2022/12/23/")}
        for key, (day, governor, source) in expected.items():
            self.assertEqual((rows[key]["date_signed"], rows[key]["governor"]), (day, governor), key)
            self.assertIn(source, rows[key]["archive_record_url"], key)
            self.assertTrue(rows[key]["archive_record_url"].startswith("https://"), key)

    def test_coverage_note_matches_the_manifest(self):
        import importlib.util, json, os, subprocess, tempfile
        from pathlib import Path
        from unittest import mock
        here = Path(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location("tennessee_adapter", here / "tennessee.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((here.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "TN"))
        self.assertTrue(note.startswith("2000-present"))


if __name__ == "__main__": unittest.main()
