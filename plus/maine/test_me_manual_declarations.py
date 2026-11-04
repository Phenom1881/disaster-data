"""Maine's hand-added declarations (manual_declarations.csv).

Governor Baldacci's weather emergency proclamations (2003-2010) come from
the Maine State Library's yearly archives of his press releases on Digital
Maine; later rows come from official announcements and dated news. Each row
has to reach the storm join and the page the way a collected declaration does.

Run:  python -m unittest test_me_manual_declarations
"""
import csv
import importlib.util
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought", "exclude"}

# Governor -> (first day in office, first day out).
TERMS = {
    "John E. Baldacci": (date(2003, 1, 1), date(2011, 1, 5)),
    "Paul R. LePage": (date(2011, 1, 5), date(2019, 1, 2)),
    "Janet T. Mills": (date(2019, 1, 2), date(2031, 1, 1)),
}
# The State Library's archive item for each year of Governor Baldacci's press releases.
BALDACCI_ARCHIVE = {2003: 18, 2004: 17, 2005: 16, 2006: 15, 2007: 14, 2008: 13, 2009: 12, 2010: 11}

_SPEC = importlib.util.spec_from_file_location("me_storm_join", HERE / "eo_storm_join.py")
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
            self.assertEqual(row["declaration_id"], "ME-SOE-" + row["date_signed"], row["declaration_id"])

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_archive_rows_link_the_press_release_archive_for_their_year(self):
        for row in read(MANUAL):
            if "digitalmaine.com/ogvn_docs/" not in row["archive_record_url"]:
                continue
            year = int(row["date_signed"][:4])
            self.assertEqual(row["governor"], "John E. Baldacci", row["declaration_id"])
            self.assertEqual(row["archive_record_url"],
                             f"https://digitalmaine.com/ogvn_docs/{BALDACCI_ARCHIVE[year]}", row["declaration_id"])

    def test_archive_rows_have_a_reviewed_override_naming_the_release(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            if "digitalmaine.com/ogvn_docs/" not in row["archive_record_url"]:
                continue
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertIn("archive of Governor Baldacci", note["review_note"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_no_row_is_a_renewal_or_extension(self):
        for row in read(MANUAL):
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extension of|extends the|amend|rescind|terminat)")

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
