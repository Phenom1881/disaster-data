import csv
import tempfile
import unittest

import ma_eo_scraper as ma


class MassachusettsScraperTests(unittest.TestCase):
    def test_parse_new_series_item(self):
        item = {"uuid": "abc", "name": "Executive Order (new series) No. 652", "metadata": {"dc.date.issued": [{"value": "2026-02-22"}], "dc.title.alternative": [{"value": "Temporary motor vehicle ban during a blizzard"}], "dc.description": [{"value": "Amended by Executive Order No. 653"}]}, "_links": {"self": {"href": "https://api.test/item"}}}
        order = ma.parse_item(item)
        self.assertEqual(order.stable_id, "MA-EO-652")
        self.assertEqual(order.governor, "Maura Healey")
        self.assertTrue(ma.is_weather_related(order))

    def test_first_series_ids_do_not_collide(self):
        item = {"uuid": "old", "name": "Executive Order No. 89", "metadata": {"dc.date.issued": [{"value": "1946-05-01"}]}}
        self.assertEqual(ma.parse_item(item).stable_id, "MA-EO-1S-89")

    def test_energy_winter_price_is_not_weather(self):
        order = ma.MAOrder("1", False, "Energy plan", "Mitigate winter price spikes", "2026-01-01", "Maura Healey", "x", "x")
        self.assertFalse(ma.is_weather_related(order))

    def test_join_excludes_termination(self):
        base = ma.MAOrder("142", False, "State of emergency", "Blizzard emergency", "1978-02-08", "Michael Dukakis", "x", "x", action_type="declaration", weather_related=True)
        end = ma.MAOrder("143", False, "Ending emergency", "Ending blizzard emergency", "1978-02-20", "Michael Dukakis", "y", "y", action_type="termination", weather_related=True)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            ma.write_outputs([base, end], [], *paths)
            with open(paths[2], newline="") as handle: rows = list(csv.DictReader(handle))
        self.assertEqual([row["declaration_id"] for row in rows], ["MA-EO-142"])
        self.assertEqual(list(rows[0]), ma.JOIN_FIELDS)


if __name__ == "__main__": unittest.main()
