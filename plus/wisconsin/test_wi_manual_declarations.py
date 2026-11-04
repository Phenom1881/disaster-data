"""Wisconsin's hand-added declarations (manual_declarations.csv).

The current Governor archive starts with the Evers administration in January
2019. The 2000-2018 weather states of emergency come from the Legislature's
executive order archive (docs.legis.wisconsin.gov/code/executive_orders), as
listed under States of Emergency in the Legislative Reference Bureau's Index
to Executive Orders. Each row has to reach the storm join and the page the
way a collected declaration does.

Run:  python -m unittest test_wi_manual_declarations
"""
import csv
import re
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought"}
ARCHIVE = re.compile(r"https://docs\.legis\.wisconsin\.gov/document/executiveorders/(\d{4})/(\d+)\.pdf")
# The live Governor archive, collected by the scraper, starts here.
SCRAPED_FROM = date(2019, 1, 7)

# Governor -> (first day in office, first day out).
TERMS = {
    "Tommy G. Thompson": (date(1987, 1, 5), date(2001, 2, 1)),
    "Scott McCallum": (date(2001, 2, 1), date(2003, 1, 6)),
    "Jim Doyle": (date(2003, 1, 6), date(2011, 1, 3)),
    "Scott Walker": (date(2011, 1, 3), date(2019, 1, 7)),
}


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_name_the_year_and_order(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        for row in read(MANUAL):
            self.assertEqual(row["declaration_id"], f"WI-EO-{row['date_signed'][:4]}-{row['eo_number']}")

    def test_every_order_is_signed_in_its_governors_term_before_the_scraped_archive(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            signed = date.fromisoformat(row["date_signed"])
            self.assertTrue(start <= signed < end, row["declaration_id"])
            self.assertLess(signed, SCRAPED_FROM, row["declaration_id"])

    def test_order_numbers_rise_with_the_date_within_each_administration(self):
        by_governor = {}
        for row in read(MANUAL):
            by_governor.setdefault(row["governor"], []).append((row["date_signed"], int(row["eo_number"])))
        for governor, orders in by_governor.items():
            orders.sort()
            numbers = [n for _, n in orders]
            self.assertEqual(numbers, sorted(numbers), governor)

    def test_every_row_links_its_order_in_the_legislatures_archive(self):
        for row in read(MANUAL):
            found = ARCHIVE.fullmatch(row["archive_record_url"])
            self.assertTrue(found, row["declaration_id"])
            self.assertEqual(found.group(1), row["date_signed"][:4], row["declaration_id"])
            self.assertEqual(found.group(2), row["eo_number"], row["declaration_id"])

    def test_every_row_has_a_reviewed_weather_override(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertIn(f"Executive Order {row['eo_number']} ", note["review_note"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_the_description_names_every_hazard_in_the_override(self):
        words = {"fire": r"\b(fire|wildfire)\b", "flood": r"\bflood", "drought": r"\bdrought\b",
                 "winter": r"\b(winter|snow|blizzard)", "severe_storm": r"\b(storms?|thunderstorms|tornado|winds?|severe weather)\b"}
        notes = {row["declaration_id"]: row["hazard_category_override"] for row in read(OVERRIDES)}
        for row in read(MANUAL):
            for hazard in notes[row["declaration_id"]].split(","):
                self.assertRegex(row["event_description"].lower(), words[hazard], row["declaration_id"])

    def test_no_row_is_an_amendment_or_a_non_weather_order(self):
        for row in read(MANUAL):
            self.assertTrue(row["event_description"].startswith("State of emergency: "), row["declaration_id"])
            self.assertNotRegex(row["event_description"],
                                r"(?i)\b(amend|extend|extension|supersed|incorporat|rescind|terminat|energy emergency|"
                                r"hurricane|permitting|hay|salt|closing)")

    def test_overrides_file_shape(self):
        with open(OVERRIDES, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames,
                             ["declaration_id", "hazard_category_override", "review_note", "source_url", "event_date"])
            ids = [row["declaration_id"] for row in reader]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
