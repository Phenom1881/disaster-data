"""
Unit tests for ne_eo_scraper.py.

The fixture reproduces real rows (EO number, description, date, and PDF
path) from https://govdocs.nebraska.gov/docs/pilot/pubs/eoindex.html,
verified via a direct fetch of the live page during this delivery's
research, in a plain HTML <table> matching the real page's structure
(a simple <tr><td> table, not JS-rendered).
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import ne_eo_scraper as scraper  # noqa: E402


FIXTURE_HTML = """
<table>
<tr><th>Date Filed</th><th>Description</th><th>Date</th></tr>
<tr>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/25-06.pdf">25-06</a></td>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/25-06.pdf">Emergency Relief Due to Power Outages Caused by Winter Storm</a></td>
  <td>03/25/25</td>
</tr>
<tr>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/25-05.pdf">25-05</a></td>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/25-05.pdf">Dynamic Pricing</a></td>
  <td>03/21/25</td>
</tr>
<tr>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/19-02.pdf">19-02</a></td>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/19-02.pdf">Emergency Relief Due to Weather Events</a></td>
  <td>03/15/19</td>
</tr>
<tr>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/17-01.pdf">17-01</a></td>
  <td><a href="https://govdocs.nebraska.gov/docs/pilot/pubs/eofiles/17-01.pdf">Emergency Relief for Damage Caused by Kansas Fires</a></td>
  <td>03/13/17</td>
</tr>
<tr>
  <td>March 25, 1987</td>
  <td>A State of emergency exists in eastern Nebraska because of heavy rains</td>
  <td></td>
</tr>
</table>
"""


class TestNebraskaScraper(unittest.TestCase):
    def test_parses_all_rows(self):
        rows = scraper.parse_index_table(FIXTURE_HTML)
        eo_numbers = [r["eo_number"] for r in rows]
        self.assertIn("25-06", eo_numbers)
        self.assertIn("25-05", eo_numbers)
        self.assertIn("19-02", eo_numbers)

    def test_keyword_filter_keeps_weather_drops_administrative(self):
        self.assertTrue(scraper.DECLARATION_KEYWORDS_RE.search("Emergency Relief Due to Power Outages Caused by Winter Storm"))
        self.assertTrue(scraper.DECLARATION_KEYWORDS_RE.search("Emergency Relief Due to Weather Events"))
        self.assertFalse(scraper.DECLARATION_KEYWORDS_RE.search("Dynamic Pricing"))

    def test_date_parsing(self):
        dt = scraper.parse_date("03/25/25")
        self.assertEqual(dt, datetime(2025, 3, 25))

    def test_governor_mapping(self):
        self.assertEqual(scraper.governor_for(datetime(2025, 3, 25)), "Jim Pillen")
        self.assertEqual(scraper.governor_for(datetime(2019, 3, 15)), "Pete Ricketts")
        self.assertEqual(scraper.governor_for(datetime(2017, 3, 13)), "Pete Ricketts")
        self.assertEqual(scraper.governor_for(datetime(2005, 1, 6)), "Dave Heineman")
        self.assertEqual(scraper.governor_for(datetime(2004, 12, 1)), "Mike Johanns")

    def test_undated_pre2000_row_is_not_crashed_on(self):
        # The 1987 narrative row has no href and no parseable Date field -
        # collect() must skip it cleanly rather than error.
        rows = scraper.parse_index_table(FIXTURE_HTML)
        undated = [r for r in rows if r["eo_number"].startswith("March 25")]
        self.assertEqual(len(undated), 1)
        self.assertIsNone(undated[0]["date"])


if __name__ == "__main__":
    unittest.main()
