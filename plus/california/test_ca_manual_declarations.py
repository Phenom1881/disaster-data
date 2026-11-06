"""California's hand-added declarations (manual_declarations.csv).

The current Governor archive begins in January 2019. The Brown
administration's 2011-2018 weather states of emergency come from its
archived proclamations (archive.gov.ca.gov/archive/gov39). Governor
Schwarzenegger's 2004-2010 ones come from Governor Brown's May 18, 2011
proclamation ending the states of emergency still in force, which lists each
original proclamation by hazard, date and jurisdiction, and Governor Davis's
October 2003 fire declaration from his own account on CNN. Each row has to
reach the storm join and the page the way a collected declaration does.

Run:  python -m unittest test_ca_manual_declarations
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
ARCHIVE = re.compile(r"https://www\.archive\.gov\.ca\.gov/archive/gov39/(\d{4})/(\d{2})/(\d{2})/[a-z0-9-]+/index\.html")
# The live Governor archive, collected by the scraper, starts here.
SCRAPED_FROM = date(2019, 1, 7)

GOVERNOR = "Edmund G. Brown Jr."
GOVERNOR_TERM = (date(2011, 1, 3), date(2019, 1, 7))
# Governors in office before Brown, by start of term.
EARLIER = [("Gray Davis", date(1999, 1, 4)), ("Arnold Schwarzenegger", date(2003, 11, 17))]
# Proclamations signed by an acting governor while the Governor was out of
# state, by signing date.
ACTING = {
    "2010-01-21": "Edmund G. Brown Jr.",
    "2013-07-19": "Gavin Newsom",
    "2015-07-22": "Gavin Newsom",
    "2016-07-26": "Tom Torlakson",
    "2018-11-08": "Gavin Newsom",
    "2018-11-09": "Gavin Newsom",
}
# Governor Brown's May 18, 2011 proclamation ending the states of emergency
# still in force; it lists each original one as 'Hazard MM/DD/YY Places'.
ENDING_LIST = "https://www.archive.gov.ca.gov/archive/gov39/2011/05/18/news17040/index.html"
LISTED = re.compile(r"lists the original proclamation as '[A-Za-z ()]+ (\d{2})/(\d{2})/(\d{2}|\d{4}) [^']+'\.")
DAVIS_2003 = "https://www.cnn.com/TRANSCRIPTS/0310/26/sun.11.html"


def governor_on(signed):
    if signed >= GOVERNOR_TERM[0]:
        return GOVERNOR
    current = None
    for name, start in EARLIER:
        if signed >= start:
            current = name
    return current


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
            self.assertRegex(row["declaration_id"], r"^CA-SOE-\d{4}-\d{2}-\d{2}(-\d)?$")
            self.assertEqual(row["declaration_id"][7:17], row["date_signed"], row["declaration_id"])

    def test_every_row_is_signed_before_the_scraped_archive(self):
        for row in read(MANUAL):
            signed = date.fromisoformat(row["date_signed"])
            self.assertTrue(date(2000, 1, 1) <= signed < GOVERNOR_TERM[1], row["declaration_id"])
            self.assertLess(signed, SCRAPED_FROM, row["declaration_id"])

    def test_signers_are_the_governor_in_office_except_the_known_acting_governors(self):
        acting = {}
        for row in read(MANUAL):
            signed = date.fromisoformat(row["date_signed"])
            expected = ACTING.get(row["date_signed"], governor_on(signed))
            self.assertEqual(row["governor"], expected, row["declaration_id"])
            if row["date_signed"] in ACTING:
                acting[row["date_signed"]] = row["governor"]
        self.assertEqual(acting, ACTING)

    def test_brown_rows_link_their_archived_proclamation_dated_the_day_it_was_signed(self):
        for row in read(MANUAL):
            if date.fromisoformat(row["date_signed"]) < GOVERNOR_TERM[0]:
                continue
            found = ARCHIVE.fullmatch(row["archive_record_url"])
            self.assertTrue(found, row["declaration_id"])
            self.assertEqual("-".join(found.groups()), row["date_signed"], row["declaration_id"])

    def test_earlier_rows_quote_the_ending_list_with_their_signing_date(self):
        notes = {row["declaration_id"]: row["review_note"] for row in read(OVERRIDES)}
        listed = 0
        for row in read(MANUAL):
            if date.fromisoformat(row["date_signed"]) >= GOVERNOR_TERM[0]:
                continue
            if row["archive_record_url"] == DAVIS_2003:
                self.assertEqual(row["governor"], "Gray Davis", row["declaration_id"])
                self.assertIn("I signed a declaration of emergency", notes[row["declaration_id"]])
                continue
            self.assertEqual(row["archive_record_url"], ENDING_LIST, row["declaration_id"])
            found = LISTED.search(notes[row["declaration_id"]])
            self.assertTrue(found, row["declaration_id"])
            month, day, year = found.groups()
            year = int(year) + (2000 if len(year) == 2 else 0)
            self.assertEqual(date(year, int(month), int(day)).isoformat(), row["date_signed"], row["declaration_id"])
            listed += 1
        self.assertGreater(listed, 0)

    def test_every_row_has_a_reviewed_weather_override(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertIn(note["hazard_category_override"], HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            if row["archive_record_url"] != DAVIS_2003:
                self.assertIn("archive.gov.ca.gov/archive/gov39", note["review_note"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_the_description_names_the_hazard_in_the_override(self):
        words = {"fire": r"\b(fire|fires|wildfires?)\b", "flood": r"\bflood", "drought": r"\bdrought\b",
                 "wind": r"\bwinds?\b", "severe_storm": r"\b(rainstorms?|storms?)\b",
                 "winter": r"\b(freeze|winter|snow)\b"}
        notes = {row["declaration_id"]: row["hazard_category_override"] for row in read(OVERRIDES)}
        for row in read(MANUAL):
            self.assertRegex(row["event_description"].lower(), words[notes[row["declaration_id"]]], row["declaration_id"])

    def test_no_row_is_an_add_on_request_or_non_weather_emergency(self):
        for row in read(MANUAL):
            self.assertNotRegex(row["event_description"],
                                r"(?i)\b(renew|extend|extension|amend|adding|terminat|request|earthquake|tsunami|"
                                r"oil spill|tanker|hepatitis|fiscal|attack)")

    def test_every_override_row_is_complete(self):
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
