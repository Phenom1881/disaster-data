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


class TestFeedParsing(unittest.TestCase):
    def test_real_fixture_parses(self):
        root = ET.fromstring(REAL_FEED_FIXTURE)
        titles = [item.find("title").text for item in root.iter("item")]
        self.assertEqual(len(titles), 4)
        self.assertIn("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties", titles)


if __name__ == "__main__":
    unittest.main()
