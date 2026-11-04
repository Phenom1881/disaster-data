"""Vermont's hand-added declarations (manual_declarations.csv).

Emergency orders from before 2011 were rescinded in 2015 and dropped from
the current statutes appendix, so the ones still in force in 2011 are kept
by hand from the 2011-2014 editions. Each row has to reach the storm join
and the page the way a collected declaration does.

Run:  python -m unittest test_vt_manual_declarations
"""
import csv
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
# Executive orders kept from the older appendix editions -> signing date.
PRE_2011_ORDERS = {"05-00": "2000-07-17", "05-02": "2002-06-12", "04-07": "2007-04-17", "05-08": "2008-12-15"}

_SPEC = importlib.util.spec_from_file_location("vt_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_pre_2011_appendix_order_is_present_with_its_date(self):
        rows = {row["eo_number"]: row for row in read(MANUAL)}
        for number, signed in PRE_2011_ORDERS.items():
            self.assertIn(number, rows)
            self.assertEqual(rows[number]["declaration_id"], "VT-EO-" + number)
            self.assertEqual(rows[number]["date_signed"], signed, number)
            self.assertTrue(rows[number]["archive_record_url"].startswith("https://law.justia.com/codes/vermont/20"), number)

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_the_2000_order_has_a_reviewed_override_with_its_event_date(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        note = notes["VT-EO-05-00"]
        self.assertEqual(note["hazard_category_override"], "flood")
        self.assertEqual(note["event_date"], "2000-07-14")
        self.assertIn("July 17, 2000", note["review_note"])

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
