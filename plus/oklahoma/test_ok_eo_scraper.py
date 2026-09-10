"""
Unit tests for ok_eo_scraper.py.

These test the parsing functions in isolation against fixture HTML built
from the real page content and text verified via manual research fetches
of oklahoma.gov during this delivery (the raw markup itself could not be
captured from this environment, which has no live network access to
oklahoma.gov - see the delivery's summary report). The fixtures below
reproduce the exact real link text, dates, county lists, and PDF paths
found on the live pages, wrapped in representative HTML anchor/paragraph
tags, so the regex/extraction logic is exercised against real content.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import ok_eo_scraper as scraper  # noqa: E402


YEAR_INDEX_FIXTURE = """
<html><body>
<a href="/oem/emergencies-and-disasters/2025/february-18-winter-storm.html">Winter Storm</a> - February 18, 2025
<a href="/oem/emergencies-and-disasters/2025/march-14-wildfires.html">Wildfires</a> - March 14, 2025
<a href="/oem/emergencies-and-disasters/2026.html">2026</a>
</body></html>
"""

EVENT_PAGE_FIXTURE = """
<html><body>
<a href="/oem/emergencies-and-disasters/2025/march-14-wildfires/wildfire-resources-march-14-2025.html">Wildfire Resources</a> - Find resources for wildfire survivors
<a href="/oem/news/newsroom/wildfire-situation-update-1---mar-14-2025.html">Situation Update 1</a> - March 14, 2025
<a href="/oem/emergencies-and-disasters/2025/march-14-wildfires/governor-declares-state-of-emergency-march-15-2025.html">Governor Declares State of Emergency</a> - March 15, 2025
</body></html>
"""

DECLARATION_PAGE_FIXTURE = """
<html><body>
<h1>Governor Stitt declares a state of emergency in twelve counties.</h1>
<p>Monday, March 17, 2025</p>
<p>Today, Governor Stitt signed Executive Order 2025-06 declaring a State of Emergency in
Cleveland, Creek, Dewey, Grady, Lincoln, Logan, Oklahoma, Pawnee, Payne, Pottawatomie,
Roger Mills, and Stephens counties following devastating fires across the state.</p>
<p>Executive Order 2025-06 will remain in effect for 30 days and can be read in full
<a href="https://www.sos.ok.gov/documents/Executive/2140.pdf">here</a>.</p>
</body></html>
"""

NO_DECLARATION_EVENT_FIXTURE = """
<html><body>
<a href="/governor/newsroom/newsroom/2025/governor-s-office-provides-preparedness-update-ahead-of-winter-s.html">Governor's Office Provides Preparedness Update Ahead of Winter Storm Event</a> - Tuesday, February 17
<a href="/oem/news/newsroom/winter-weather-situation-update-1---feb-18-2025.html">Storm Situation 1</a> - Tuesday, February 18
<a href="/oem/news/newsroom/winter-weather-situation-update-2---feb-19-2025.html">Situation Update 2</a> - Wednesday, February 19
</body></html>
"""


class TestOklahomaScraper(unittest.TestCase):
    def test_parse_year_index_finds_event_pages(self):
        events = scraper.parse_year_index(YEAR_INDEX_FIXTURE, "https://oklahoma.gov/oem/emergencies-and-disasters/2025.html")
        urls = [u for _, u in events]
        self.assertIn("https://oklahoma.gov/oem/emergencies-and-disasters/2025/march-14-wildfires.html", urls)
        self.assertIn("https://oklahoma.gov/oem/emergencies-and-disasters/2025/february-18-winter-storm.html", urls)
        # the "2026" year-nav link itself is not a dated event page and must not be picked up
        self.assertNotIn("https://oklahoma.gov/oem/emergencies-and-disasters/2026.html", urls)

    def test_parse_event_page_finds_declaration_link_only(self):
        candidates = scraper.parse_event_page(EVENT_PAGE_FIXTURE)
        self.assertEqual(len(candidates), 1)
        text, url = candidates[0]
        self.assertIn("Governor Declares State of Emergency", text)
        self.assertTrue(url.endswith("governor-declares-state-of-emergency-march-15-2025.html"))

    def test_parse_event_page_with_no_declaration_returns_empty(self):
        # This is the real February 18, 2025 winter storm event page, which
        # has no "Governor Declares..." link at all - a genuine missing
        # companion declaration, not a parsing failure.
        candidates = scraper.parse_event_page(NO_DECLARATION_EVENT_FIXTURE)
        self.assertEqual(candidates, [])

    def test_parse_declaration_page_extracts_real_fields(self):
        record = scraper.parse_declaration_page(
            DECLARATION_PAGE_FIXTURE,
            "https://oklahoma.gov/governor/newsroom/newsroom/2025/governor-stitt-declares-a-state-of-emergency-in-twelve-counties-.html",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["eo_number"], "2025-06")
        self.assertEqual(record["date_signed"], "2025-03-17")
        self.assertIn("Cleveland", record["event_description"])
        self.assertIn("Stephens", record["event_description"])
        self.assertEqual(record["archive_record_url"], "https://www.sos.ok.gov/documents/Executive/2140.pdf")

    def test_parse_declaration_page_without_eo_number_returns_none(self):
        # e.g. the June 7, 2026 flooding press page, which never states an
        # EO number in the body text - must not be guessed.
        html = "<html><body><p>Today, Governor Kevin Stitt signed an executive order declaring a disaster emergency for Creek, Ottawa, Okfuskee, and Tulsa counties.</p></body></html>"
        record = scraper.parse_declaration_page(html, "https://oklahoma.gov/some/page.html")
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
