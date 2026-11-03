"""Georgia states of emergency for 2000-2009, added by hand.

Perdue's orders come from his archived executive order list, dated by the
order number. Barnes's 2000 declarations have no signing day in any source
found, so the date of the earliest report is used.
"""
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.rows = csv_rows("manual_declarations.csv")
        self.overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}

    def test_perdue_orders_are_dated_by_their_number(self):
        perdue = [r for r in self.rows if r["governor"] == "Sonny Perdue"]
        self.assertEqual(len(perdue), 7)
        for row in perdue:
            month, day, year, _ = row["eo_number"].split(".")
            self.assertEqual(row["date_signed"], "20%s-%s-%s" % (year, month, day))
            self.assertEqual(row["declaration_id"], "GA-EO-" + row["eo_number"].replace(".", "-"))
            self.assertTrue(row["archive_record_url"].startswith("https://sonnyperdue.georgia.gov/"))
            self.assertIn(row["eo_number"][-2:] + ".pdf", row["archive_record_url"])

    def test_barnes_rows_use_the_report_date(self):
        barnes = {r["declaration_id"]: r for r in self.rows if r["governor"] == "Roy Barnes"}
        self.assertEqual(set(barnes), {"GA-SOE-2000-01-24", "GA-SOE-2000-02-15"})
        for declaration_id, row in barnes.items():
            self.assertEqual(row["declaration_id"], "GA-SOE-" + row["date_signed"])
            self.assertIn("no signing day", self.overrides[declaration_id]["review_note"].lower())

    def test_each_has_a_reviewed_hazard_and_source(self):
        for row in self.rows:
            override = self.overrides[row["declaration_id"]]
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertLessEqual(set(override["hazard_category_override"].split(",")),
                                 {"winter", "severe_storm", "flood", "tropical"})
            if override["event_date"]:
                self.assertLessEqual(override["event_date"], row["date_signed"])

    def test_not_already_collected(self):
        collected = {r["declaration_id"] for r in csv_rows("ga_emergency_actions_all.csv")}
        for row in self.rows:
            self.assertNotIn(row["declaration_id"], collected)


class CoverageStartTests(unittest.TestCase):
    def test_note_matches_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("georgia_adapter", HERE / "georgia.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s for s in manifest["states"] if s["abbreviation"] == "GA")["coverage_note"]
        self.assertIn(note, (HERE / "georgia.py").read_text(encoding="utf-8").replace('"\n            "', ""))
        build_spec = importlib.util.spec_from_file_location("build_plus_ga", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(build_spec)
        sys.modules[build_spec.name] = build
        build_spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("GA", note), 2000)
        self.assertIn("DR-4579", note)


if __name__ == "__main__":
    unittest.main()
