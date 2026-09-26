"""Unit tests for oh_eo_scraper.py, run offline against a real RSS-item
fixture built from titles independently confirmed via search/web_fetch
during this batch's research (not fabricated titles)."""
import unittest
from xml.etree import ElementTree as ET

from oh_eo_scraper import classify_title, is_original_declaration

REAL_FEED_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example1</link>
  <pubDate>Sat, 10 Aug 2024 12:00:00 -0400</pubDate>
</item>
<item>
  <title>Governor DeWine Issues Proclamation Declaring State of Emergency in Ohio</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example2</link>
  <pubDate>Sat, 24 Jan 2026 09:00:00 -0500</pubDate>
</item>
<item>
  <title>MEDIA ADVISORY: Governor DeWine, Lt. Governor Husted to Announce New BMV Services Available Online</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example3</link>
  <pubDate>Wed, 22 Jun 2022 10:00:00 -0400</pubDate>
</item>
<item>
  <title>Governor DeWine Updates Ohioans on Severe Weather</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example4</link>
  <pubDate>Tue, 01 Jul 2025 15:00:00 -0400</pubDate>
</item>
</channel></rss>
"""


class TestClassifyTitle(unittest.TestCase):
    def test_severe_weather(self):
        self.assertEqual(
            classify_title("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties Following Tornadoes"),
            "severe_storm",
        )

    def test_no_hazard(self):
        self.assertIsNone(classify_title("MEDIA ADVISORY: New BMV Services Available Online"))


class TestIsOriginalDeclaration(unittest.TestCase):
    def test_true_for_declares_state_of_emergency(self):
        self.assertTrue(is_original_declaration("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties"))

    def test_true_for_issues_proclamation(self):
        self.assertTrue(is_original_declaration("Governor DeWine Issues Proclamation Declaring State of Emergency in Ohio"))

    def test_false_for_update_bulletin(self):
        # "Updates Ohioans on Severe Weather" mentions weather but is a
        # status update, not itself a declaration -- must be excluded.
        self.assertFalse(is_original_declaration("Governor DeWine Updates Ohioans on Severe Weather"))

    def test_false_for_media_advisory(self):
        self.assertFalse(is_original_declaration("MEDIA ADVISORY: Governor DeWine to Announce New BMV Services"))


class TestStableIdsAndDates(unittest.TestCase):
    """Ids used to be numbered by feed position, so a new proclamation took
    an existing id and pushed a saved record out; and dates were left blank."""

    SAVED = [
        {"declaration_id": "OH-PROC-2024-002", "archive_record_url": "https://governor.ohio.gov/x/eight-counties",
         "date_signed": "2024-08-10"},
        {"declaration_id": "OH-PROC-2024-003", "archive_record_url": "https://governor.ohio.gov/x/four-counties",
         "date_signed": "2024-10-02"},
    ]

    def test_feed_date(self):
        from oh_eo_scraper import feed_date
        self.assertEqual(feed_date("Tue, 22 Sep 2026 14:05:00 -0400"), "2026-09-22")
        self.assertEqual(feed_date(""), "")

    def test_saved_proclamations_keep_their_ids_and_new_ones_do_not_collide(self):
        from oh_eo_scraper import BulletinAction, assign_ids
        old = BulletinAction("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties",
                             "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/abc", "2024-08-11")
        new = BulletinAction("Governor DeWine Declares State of Emergency in Several Ohio Counties",
                             "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/def", "2026-09-22")
        same_day = BulletinAction("Governor DeWine Declares State of Emergency in Two More Counties",
                                  "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/ghi", "2026-09-22")
        ids = assign_ids([new, old, same_day], self.SAVED)
        self.assertEqual(ids[id(old)], "OH-PROC-2024-002")          # matched a day off the saved date
        self.assertEqual(ids[id(new)], "OH-PROC-2026-09-22")
        self.assertEqual(ids[id(same_day)], "OH-PROC-2026-09-22-2")

    def test_join_rows_carry_dates(self):
        import csv, tempfile
        from pathlib import Path
        from oh_eo_scraper import BulletinAction, write_outputs
        a = BulletinAction("Governor DeWine Declares State of Emergency Following Flooding",
                           "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/def", "2026-09-22",
                           hazard_guess="flood", is_original_weather_declaration=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_outputs([a], tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["date_signed"], "2026-09-22")
        self.assertEqual(rows[0]["declaration_id"], "OH-PROC-2026-09-22")


class TestFeedParsing(unittest.TestCase):
    def test_real_fixture_parses(self):
        root = ET.fromstring(REAL_FEED_FIXTURE)
        titles = [item.find("title").text for item in root.iter("item")]
        self.assertEqual(len(titles), 4)
        self.assertIn("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties", titles)


if __name__ == "__main__":
    unittest.main()
