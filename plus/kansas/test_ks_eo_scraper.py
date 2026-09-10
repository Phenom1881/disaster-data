"""
Unit tests for ks_eo_scraper.py.

The fixture below reproduces the real headings, dates, and DocumentCenter
PDF ids found on https://www.kansastag.gov/388/Kansas-Disaster-Declarations
during this delivery's research fetch (2024/2025 tab content), wrapped in
CivicPlus-style nested <div>/<li> markup representative of the real page,
since the exact raw markup could not be captured from this environment
(no live network access to kansastag.gov - see the summary report).
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import ks_eo_scraper as scraper  # noqa: E402


FIXTURE_HTML = """
<div class="tabs">
<div class="tab-heading">2025</div>
<ul>
<li>January 4 - February 9 (Winter Storms)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3367/Gov-Declaration-Winter-Storm-Signed-01-10-2025">State Declaration (PDF)</a></li></ul>
</li>
<li>May 18 - 19 (Severe Storms)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3905/Severe-Storms-May-18-19-2025">State Declaration (PDF)</a></li></ul>
</li>
<li>May 12 - Current (Drought)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3844/State-Declaration-for-Drought-Conditions-for-2025">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2024</div>
<ul>
<li>June 7 (Drought)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3379/SOK-June-7-2024-Drought">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2018</div>
<ul>
<li>December 26-27 (Winter Storm)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/1181/December-26-27-State-Declaration-PDF">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2019</div>
<ul>
<li>July 22 - August 16 (Severe Storms and Flooding)
  <ul>
    <li><a href="https://www.kansastag.gov/DocumentCenter/View/1203/State-Declaration-PDF">State Declaration (PDF)</a></li>
    <li><a href="https://www.kansastag.gov/DocumentCenter/View/1204/Amended-State-Declaration-PDF">Amended State Declaration (PDF)</a></li>
  </ul>
</li>
</ul>
</div>
"""


class TestKansasScraper(unittest.TestCase):
    def test_parses_2025_events(self):
        records = scraper.parse_declarations_page(FIXTURE_HTML)
        headings_2025 = [r["heading"] for r in records if r["year"] == "2025"]
        self.assertIn("January 4 - February 9 (Winter Storms)", headings_2025)
        self.assertIn("May 18 - 19 (Severe Storms)", headings_2025)
        self.assertEqual(len(headings_2025), 3)

    def test_amended_declaration_is_not_double_counted(self):
        records = scraper.parse_declarations_page(FIXTURE_HTML)
        matches_2019 = [r for r in records if r["year"] == "2019"]
        # Only the original "State Declaration (PDF)" should be captured,
        # never the "Amended State Declaration (PDF)" as a second row.
        self.assertEqual(len(matches_2019), 1)
        self.assertEqual(matches_2019[0]["doc_id"], "1203")

    def test_governor_mapping(self):
        self.assertEqual(scraper.governor_for(datetime(2025, 1, 10)), "Laura Kelly")
        self.assertEqual(scraper.governor_for(datetime(2018, 1, 21)), "Sam Brownback")
        self.assertEqual(scraper.governor_for(datetime(2018, 3, 14)), "Jeff Colyer")
        self.assertEqual(scraper.governor_for(datetime(2013, 8, 1)), "Sam Brownback")

    def test_date_range_parsing(self):
        date_str, hazard = scraper.parse_date_range("2025", "January 4 - February 9 (Winter Storms)")
        self.assertEqual(date_str, "2025-01-04")
        self.assertEqual(hazard, "Winter Storms")

    def test_single_date_parsing(self):
        date_str, hazard = scraper.parse_date_range("2024", "June 7 (Drought)")
        self.assertEqual(date_str, "2024-06-07")
        self.assertEqual(hazard, "Drought")


if __name__ == "__main__":
    unittest.main()
