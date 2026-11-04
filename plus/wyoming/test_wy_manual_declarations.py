"""Wyoming's hand-added declarations (manual_declarations.csv).

No archive of Wyoming governors' orders before 2019 has been found, so these
rows come from official announcements, order text (FMCSA's copies) and dated
news coverage. Each row has to reach the storm join and the page the way a
collected declaration does.

Run:  python -m unittest test_wy_manual_declarations
"""
import csv
import importlib.util
import re
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]

# Governor (as written in the source) -> (first day in office, first day out).
TERMS = {
    "Jim Geringer": (date(1995, 1, 2), date(2003, 1, 6)),
    "Dave Freudenthal": (date(2003, 1, 6), date(2011, 1, 3)),
    "Matt Mead": (date(2011, 1, 3), date(2019, 1, 7)),
    "Matthew H. Mead": (date(2011, 1, 3), date(2019, 1, 7)),
    "Mark Gordon": (date(2019, 1, 7), date(2031, 1, 1)),
}

_SPEC = importlib.util.spec_from_file_location("wy_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read():
    with open(MANUAL, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_carry_the_date_or_order(self):
        ids = [row["declaration_id"] for row in read()]
        self.assertEqual(len(ids), len(set(ids)))
        for row in read():
            rid = row["declaration_id"]
            if rid.startswith("WY-SOE-"):
                self.assertEqual(rid, "WY-SOE-" + row["date_signed"])
                self.assertEqual(row["eo_number"], "", rid)
            else:
                self.assertEqual(rid, "WY-EO-" + row["eo_number"])
                self.assertEqual(row["eo_number"][:4], row["date_signed"][:4], rid)

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in read():
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read():
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_every_row_links_a_source(self):
        for row in read():
            self.assertRegex(row["archive_record_url"], r"^https://[^ ]+$", row["declaration_id"])

    def test_no_row_is_a_renewal_or_extension(self):
        for row in read():
            self.assertNotRegex(row["event_description"], r"(?i)\b(renew|extension of|extends the|amend|rescind|terminat)")

    def test_no_long_dashes(self):
        for path in (MANUAL, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
