import unittest

import vt_eo_scraper as vt


LISTING = """
<h2><a href="/document/executive-order-no-03-23">EXECUTIVE ORDER NO. 03-23</a></h2>
<nav class="pager"><a href="?page=13">Last</a></nav>
"""
DETAIL = """
<h1>EXECUTIVE ORDER NO. 03-23</h1><time datetime="2023-07-09T12:00:00Z"></time>
<div class="field--name-body">Declaration of State of Emergency in Response to Anticipated Storm-Related Damage and Flooding</div>
<a href="/files/eo-03-23.pdf">PDF</a>
"""


class VermontTests(unittest.TestCase):
    def test_listing_and_last_page(self):
        urls, last = vt.parse_listing(LISTING)
        self.assertEqual(last, 13); self.assertEqual(urls, ["https://governor.vermont.gov/document/executive-order-no-03-23"])

    def test_detail_and_weather_declaration(self):
        action = vt.parse_detail(DETAIL, "https://governor.vermont.gov/document/executive-order-no-03-23")
        self.assertEqual(action.number, "03-23"); self.assertEqual(action.date_signed, "2023-07-09")
        vt.classify(action); self.assertEqual(action.action_type, "declaration"); self.assertTrue(action.weather_related)

    def test_amended_order_excluded_from_declarations(self):
        action = vt.Action("03-23", "Amended and Restated Executive Order 03-23 for July 2024 flooding", "2024-07-09", "x")
        vt.classify(action); self.assertEqual(action.action_type, "amendment")

    def test_emergency_housing_is_not_declaration(self):
        action = vt.Action("03-25", "General Assistance Emergency Housing", "2025-03-28", "x")
        vt.classify(action); self.assertEqual(action.action_type, "administrative"); self.assertFalse(action.weather_related)


if __name__ == "__main__": unittest.main()
