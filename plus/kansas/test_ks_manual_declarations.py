"""Kansas's hand-added declarations (manual_declarations.csv).

KDEM's disaster-declarations page links 2011-2016 state proclamations as
scanned PDFs under labels the scraper cannot read, so those were read by eye
and kept by hand. Earlier declarations come from proclamation dates cited in
the Kansas Register, archived Adjutant General releases and news coverage. Each row has to reach the storm join and the page the way a
collected declaration does.

Run:  python -m unittest test_ks_manual_declarations
"""
import csv
import importlib.util
import re
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN = HERE / "declarations_for_join.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought", "exclude"}
# Governor, or lieutenant governor acting for the governor -> (first day in office, first day out).
TERMS = {
    "Bill Graves": (date(1995, 1, 9), date(2003, 1, 13)),
    "Kathleen Sebelius": (date(2003, 1, 13), date(2009, 4, 28)),
    "John Moore": (date(2003, 1, 13), date(2006, 5, 31)),
    "Mark Parkinson": (date(2009, 4, 28), date(2011, 1, 10)),
    "Troy Findley": (date(2009, 5, 1), date(2011, 1, 10)),
    "Sam Brownback": (date(2011, 1, 10), date(2018, 1, 31)),
    "Jeff Colyer": (date(2018, 1, 31), date(2019, 1, 14)),
    "Laura Kelly": (date(2019, 1, 14), date(2027, 1, 11)),
}

_SPEC = importlib.util.spec_from_file_location("ks_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_not_already_collected(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        collected = {row["declaration_id"] for row in read(JOIN)}
        self.assertFalse(set(ids) & collected)

    def test_kdem_rows_are_named_for_their_document(self):
        for row in read(MANUAL):
            found = re.fullmatch(r"https://www\.kansastag\.gov/DocumentCenter/View/(\d+)/.+", row["archive_record_url"])
            if found:
                self.assertEqual(row["declaration_id"], "KS-PROC-" + found.group(1))
                self.assertEqual(row["eo_number"], found.group(1))
            else:
                self.assertEqual(row["declaration_id"], "KS-SOE-" + row["date_signed"])

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_every_row_has_a_reviewed_override(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_register_rows_quote_the_register(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            if row["archive_record_url"].startswith("https://rules.ks.gov/browse/collections/"):
                self.assertIn("Kansas Register", notes[row["declaration_id"]]["review_note"], row["declaration_id"])

    def test_the_2005_annual_report_rows_carry_the_storm_they_answered(self):
        # The Adjutant General's 2005 annual report names both declarations
        # without a signing day, so each row carries the last day of the storm
        # it answered and is compared on the first.
        report = "https://media.defense.gov/2022/Feb/11/2002937782/-1/-1/0/ANNUAL%20REPORT%202005.PDF"
        manual = {row["declaration_id"]: row for row in read(MANUAL)}
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        expected = {"KS-SOE-2005-07-01": ("2005-06-30", "DR-1600"), "KS-SOE-2005-10-02": ("2005-10-01", "DR-1615")}
        for key, (first_day, federal) in expected.items():
            row, note = manual[key], notes[key]
            self.assertEqual(row["governor"], "Kathleen Sebelius", key)
            self.assertEqual(row["archive_record_url"], report, key)
            self.assertIn("2005 annual report; the signing day is not given, so the date of the", row["event_description"], key)
            self.assertEqual(note["event_date"], first_day, key)
            self.assertEqual(note["hazard_category_override"], "severe_storm,flood", key)
            self.assertIn("2005 annual report", note["review_note"], key)
            self.assertIn(federal, note["review_note"], key)
            self.assertRegex(note["review_note"], r"The (?:signing day is not given|report gives neither the signing day)", key)
        self.assertIn("'Gov. Sebelius issued a declaration of a State of Disaster Emergency for 10 Kansas counties due to the storms of June 30 and July 1",
                      notes["KS-SOE-2005-07-01"]["review_note"])
        self.assertIn("'Several counties were named in a State of Disaster Emergency declared by Gov. Sebelius",
                      notes["KS-SOE-2005-10-02"]["review_note"])

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
