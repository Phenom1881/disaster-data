"""Oregon declarations added by hand that the Governor's online archive lacks."""
import csv
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_eo_06_01_dated_from_the_oregon_bulletin(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        row = rows["OR-SOE-2006-01-13"]
        self.assertEqual(row["date_signed"], "2006-01-13")
        self.assertEqual(row["eo_number"], "06-01")
        self.assertEqual(row["governor"], "Theodore R. Kulongoski")
        self.assertEqual(row["archive_record_url"], "https://www.oregon.gov/gov/eo/eo0601.pdf")

    def test_each_manual_row_has_a_reviewed_override(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            if row["declaration_id"] != "OR-SOE-2006-01-13":
                continue
            override = overrides[row["declaration_id"]]
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertEqual(set(override["hazard_category_override"].split(",")), {"flood", "severe_storm"})
            self.assertEqual(override["event_date"], "2005-12-22")

    def test_eo_06_01_is_not_already_a_joined_declaration(self):
        joined = {r["eo_number"] for r in csv_rows("declarations_for_join.csv")}
        self.assertNotIn("06-01", joined)
        self.assertIn("Record/4539413", {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}["OR-SOE-2006-01-13"]["review_note"])


if __name__ == "__main__":
    unittest.main()
