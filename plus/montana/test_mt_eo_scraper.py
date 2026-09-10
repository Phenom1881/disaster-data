"""
Unit tests for mt_eo_scraper.py against fixtures matching the real rendered
text of gov.mt.gov's current EO page and formergovernors.mt.gov/bullock.
"""
import csv
import os
import tempfile
import unittest

import mt_eo_scraper as scraper

CURRENT_FIXTURE = """
Declaring a Disaster to Exist in the State of Montana
Executive Order 9-2025
December 11, 2025

Creating the Energy Advisory Council
Executive Order No. 6-2025
September 10, 2025

Declaring Statewide Drought Emergency
Executive Order No. 11-2021
July 1, 2021
"""

BULLOCK_FIXTURE = """
## 2019 Executive Orders

- [Declaring a Winter Storm Emergency in Montana](https://formergovernors.mt.gov/bullock/docs/2019EOs/EO%2015-2019_Declaring%20a%20Winter%20Storm%20Emergency.pdf) - Executive Order No. 15-2019
- [Creating the Climate Solutions Council](https://formergovernors.mt.gov/bullock/docs/2019EOs/EO-08-2019_Creating%20Climate%20Solutions%20Council.pdf) - Executive Order No. 8-2019
"""


class CurrentPageParsingTests(unittest.TestCase):
    def test_parses_title_number_date_triplets(self):
        orders = scraper.parse_current_page(CURRENT_FIXTURE)
        self.assertEqual(len(orders), 3)
        self.assertEqual(orders[0]["eo_number"], "9-2025")
        self.assertEqual(orders[0]["date_text"], "December 11, 2025")

    def test_date_conversion(self):
        self.assertEqual(scraper.parse_date_text("December 11, 2025"), "2025-12-11")


class BullockPageParsingTests(unittest.TestCase):
    def test_parses_linked_entries_no_date(self):
        orders = scraper.parse_bullock_page(BULLOCK_FIXTURE)
        self.assertEqual(len(orders), 2)
        self.assertIsNone(orders[0]["date_text"])
        self.assertEqual(orders[0]["eo_number"], "15-2019")


class ClassificationTests(unittest.TestCase):
    def test_boilerplate_disaster_title_flagged_for_override(self):
        is_decl, needs_override = scraper.classify_title(
            "Declaring a Disaster to Exist in the State of Montana"
        )
        self.assertTrue(is_decl)
        self.assertTrue(needs_override)

    def test_drought_emergency_no_override_needed(self):
        is_decl, needs_override = scraper.classify_title("Declaring Statewide Drought Emergency")
        self.assertTrue(is_decl)
        self.assertFalse(needs_override)

    def test_council_excluded(self):
        is_decl, _ = scraper.classify_title("Creating the Energy Advisory Council")
        self.assertFalse(is_decl)

    def test_governor_lookup(self):
        self.assertEqual(scraper.governor_for("9-2025"), "Gianforte")
        self.assertEqual(scraper.governor_for("15-2019"), "Bullock")
        self.assertEqual(scraper.governor_for("3-2007"), "Schweitzer")


class WriteCsvTests(unittest.TestCase):
    def test_current_page_entries_written_with_dates(self):
        orders = scraper.parse_current_page(CURRENT_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "j.csv")
            declarations = scraper.write_csv(
                orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join_out
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("MT-EO-9-2025", ids)
            self.assertIn("MT-EO-11-2021", ids)
            self.assertNotIn("MT-EO-6-2025", ids)  # council, excluded

    def test_undated_bullock_entries_excluded_without_confirmed_date(self):
        orders = scraper.parse_bullock_page(BULLOCK_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            declarations = scraper.write_csv(
                orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                os.path.join(tmp, "j.csv"),
            )
            # "Declaring a Winter Storm Emergency" matches the keyword regex
            # but has no date in the Bullock-page fixture and none supplied
            # via confirmed_dates -> must be dropped, not guessed.
            self.assertEqual(len(declarations), 0)


if __name__ == "__main__":
    unittest.main()
