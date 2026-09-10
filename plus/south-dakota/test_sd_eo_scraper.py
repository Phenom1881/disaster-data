"""
Unit tests for sd_eo_scraper.py. These test the pure parsing/classification
logic against saved-in-code HTML fixtures - they do not hit the live network.
"""
import csv
import os
import tempfile
import unittest

import sd_eo_scraper as scraper

SAMPLE_HTML = """
<html><body>
<h2>2024 Executive Orders</h2>
<table>
<tr><th>Order Number</th><th>Dated Filed</th><th>Title</th></tr>
<tr><td>2024-01</td><td>20240109</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-01.PDF">Bureau of Human Resources and Administration Reorganization</a></td></tr>
<tr><td>2024-02</td><td>20240112</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-02.PDF">State of Emergency - Transportation Exemptions</a></td></tr>
<tr><td>2024-04</td><td>20240622</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-04.PDF">State of Emergency - Flood Relief</a></td></tr>
<tr><td>2024-06</td><td>20240726</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-06.pdf">Disaster Declaration</a></td></tr>
</table>
</body></html>
"""


class ParseOrdersTests(unittest.TestCase):
    def test_parses_all_rows(self):
        orders = scraper.parse_orders(SAMPLE_HTML)
        self.assertEqual(len(orders), 4)
        self.assertEqual(orders[0]["eo_number"], "2024-01")
        self.assertEqual(orders[0]["date_filed"], "20240109")

    def test_url_is_absolute(self):
        orders = scraper.parse_orders(SAMPLE_HTML)
        for o in orders:
            self.assertTrue(o["url"].startswith("https://sdsos.gov/"))


class ClassificationTests(unittest.TestCase):
    def test_flood_relief_is_declaration(self):
        self.assertTrue(scraper.is_declaration("State of Emergency - Flood Relief"))

    def test_disaster_declaration_is_declaration(self):
        self.assertTrue(scraper.is_declaration("Disaster Declaration"))

    def test_transportation_exemptions_excluded(self):
        # Regression: the recurring standing motor-carrier hours mechanism
        # must never be treated as a storm-specific declaration.
        self.assertFalse(scraper.is_declaration("State of Emergency - Transportation Exemptions"))

    def test_reorganization_excluded(self):
        self.assertFalse(scraper.is_declaration("Bureau of Human Resources and Administration Reorganization"))

    def test_covid_excluded(self):
        self.assertFalse(scraper.is_declaration("COVID-19: Statewide Disaster Declaration"))


class DateAndGovernorTests(unittest.TestCase):
    def test_iso_date_conversion(self):
        self.assertEqual(scraper.to_iso_date("20240622"), "2024-06-22")

    def test_iso_date_bad_input(self):
        self.assertEqual(scraper.to_iso_date("not-a-date"), "")

    def test_governor_lookup_noem(self):
        self.assertEqual(scraper.governor_for("2023-08"), "Noem")

    def test_governor_lookup_rhoden(self):
        self.assertEqual(scraper.governor_for("2026-04"), "Rhoden")


class WriteCsvTests(unittest.TestCase):
    def test_only_declarations_written_to_join_csv(self):
        orders = scraper.parse_orders(SAMPLE_HTML)
        with tempfile.TemporaryDirectory() as tmp:
            actions_out = os.path.join(tmp, "actions.csv")
            rel_out = os.path.join(tmp, "rel.csv")
            join_out = os.path.join(tmp, "join.csv")
            declarations = scraper.write_csv(orders, actions_out, rel_out, join_out)

            # Only 2024-04 and 2024-06 are genuine declarations in the fixture.
            self.assertEqual(len(declarations), 2)
            ids = {d["declaration_id"] for d in declarations}
            self.assertEqual(ids, {"SD-EO-2024-04", "SD-EO-2024-06"})

            with open(join_out, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["governor"], "Noem")


if __name__ == "__main__":
    unittest.main()
