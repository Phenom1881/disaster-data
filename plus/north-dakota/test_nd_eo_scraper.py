"""
Unit tests for nd_eo_scraper.py against markdown-style fixtures matching the
real rendered text of governor.nd.gov's archive and current EO pages.
"""
import csv
import os
import tempfile
import unittest

import nd_eo_scraper as scraper

ARCHIVE_FIXTURE = """
## **2023**

- **2023-04** - April 10, 2023 - Burgum Declares Statewide Emergency for Spring Flooding
- **2023-03** - March 21, 2023 - Burgum Declares Winter Storm Disaster for January Fog and Ice Event
- **2023-07** - June 13, 2023 - Burgum Declares an Emergency and Authorizes the North Dakota National Guard to Help Texas Secure the U.S.-Mexico Border

## **2020**

- **2020-34** - May 30, 2020 - Burgum Declares State of Emergency in Fargo, West Fargo and Cass County, Activates North Dakota National Guard
- **2020-30** - April 24, 2020 - Burgum Declares Statewide Flood Emergency for Spring Flooding
"""

CURRENT_FIXTURE = """
## **2026**

- **2026-03** - [Armstrong Declares Statewide Disaster for Damage from Severe Storms](https://www.governor.nd.gov/sites/default/files/documents/Executive%20Order%202026-03.pdf)
- **2026-01** - [Armstrong Directs State Resources to Be Ready for America 250](https://www.governor.nd.gov/sites/default/files/documents/Executive%20Order%202026-01.pdf)
"""


class ArchiveParsingTests(unittest.TestCase):
    def test_parses_numbered_dated_entries(self):
        orders = scraper.parse_archive_markdown(ARCHIVE_FIXTURE)
        self.assertEqual(len(orders), 5)
        first = orders[0]
        self.assertEqual(first["eo_number"], "2023-04")
        self.assertEqual(first["date_text"], "April 10, 2023")

    def test_date_conversion(self):
        self.assertEqual(scraper.parse_date_text("April 10, 2023"), "2023-04-10")


class CurrentPageParsingTests(unittest.TestCase):
    def test_parses_linked_entries(self):
        orders = scraper.parse_current_markdown(CURRENT_FIXTURE)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0]["eo_number"], "2026-03")
        self.assertTrue(orders[0]["url"].endswith(".pdf"))
        self.assertIsNone(orders[0]["date_text"])


class ClassificationTests(unittest.TestCase):
    def test_flood_emergency_is_declaration(self):
        self.assertTrue(scraper.is_declaration("2023-04", "Declares Statewide Emergency for Spring Flooding"))

    def test_civil_disturbance_excluded_despite_emergency_wording(self):
        # Regression: this is the exact case Claude's own verification pass
        # caught during research - a "state of emergency" title that is
        # actually a civil-disturbance order (May 2020 Fargo protests), not
        # weather. It must never reach declarations_for_join.csv.
        self.assertFalse(scraper.is_declaration(
            "2020-34",
            "Burgum Declares State of Emergency in Fargo, West Fargo and Cass County, "
            "Activates North Dakota National Guard",
        ))

    def test_texas_border_deployment_excluded(self):
        self.assertFalse(scraper.is_declaration(
            "2023-07",
            "Burgum Declares an Emergency and Authorizes the North Dakota National Guard "
            "to Help Texas Secure the U.S.-Mexico Border",
        ))

    def test_governor_lookup(self):
        self.assertEqual(scraper.governor_for("2020-30"), "Burgum")
        self.assertEqual(scraper.governor_for("2026-03"), "Armstrong")
        self.assertEqual(scraper.governor_for("2011-05"), "Dalrymple")


class WriteCsvTests(unittest.TestCase):
    def test_undated_current_page_entry_needs_confirmed_date(self):
        orders = scraper.parse_current_markdown(CURRENT_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            actions_out = os.path.join(tmp, "a.csv")
            rel_out = os.path.join(tmp, "r.csv")
            join_out = os.path.join(tmp, "j.csv")

            # Without a confirmed date, the storm EO must be dropped from
            # the join CSV rather than guessed.
            declarations = scraper.write_csv(orders, actions_out, rel_out, join_out)
            self.assertEqual(len(declarations), 0)

            # With a confirmed date supplied, it is included.
            declarations = scraper.write_csv(
                orders, actions_out, rel_out, join_out,
                confirmed_dates={"2026-03": "2026-06-30"},
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("ND-EO-2026-03", ids)

    def test_archive_entries_with_parsed_dates_included(self):
        orders = scraper.parse_archive_markdown(ARCHIVE_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "j.csv")
            declarations = scraper.write_csv(
                orders,
                os.path.join(tmp, "a.csv"),
                os.path.join(tmp, "r.csv"),
                join_out,
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("ND-EO-2023-04", ids)
            self.assertIn("ND-EO-2023-03", ids)
            self.assertIn("ND-EO-2020-30", ids)
            self.assertNotIn("ND-EO-2020-34", ids)
            self.assertNotIn("ND-EO-2023-07", ids)

            with open(join_out, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
