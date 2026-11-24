"""Massachusetts's hand-added storm states of emergency (manual_declarations.csv).

Most Massachusetts states of emergency were proclaimed outside the numbered
executive-order series, so the storm declarations are added by hand from dated
news coverage. Each row has to reach the storm join the way a collected
declaration does, and a row whose source gives no signing day carries the date
of the report and says so.

Run:  python -m unittest test_ma_manual_declarations
"""
import csv
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]

_SPEC = importlib.util.spec_from_file_location("ma_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_carry_the_signing_date(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        for row in read(MANUAL):
            self.assertEqual(row["declaration_id"], "MA-PROC-" + row["date_signed"], row["declaration_id"])

    def test_rows_are_in_date_order(self):
        days = [row["date_signed"] for row in read(MANUAL)]
        self.assertEqual(days, sorted(days))

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_rows_dated_by_a_report_say_so(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        dated = [row for row in read(MANUAL) if "the signing day is not given" in row["event_description"]]
        self.assertEqual([row["declaration_id"] for row in dated], ["MA-PROC-1987-04-08"])
        for row in dated:
            note = notes[row["declaration_id"]]
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertIn("so the row carries the date of the report", note["review_note"], row["declaration_id"])
            self.assertEqual(row["governor"], "Michael Dukakis", row["declaration_id"])

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
