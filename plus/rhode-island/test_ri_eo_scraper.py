import csv
import tempfile
import unittest

import ri_eo_scraper as ri


ARCHIVE_FIXTURE = """
<table><tr><th>Date</th><th>Executive Order</th><th>Executive Order Long Title</th></tr>
<tr><td>2024-02-12</td><td><a href="/executive-orders/24-03">Executive Order 24-03</a></td><td>Declaration of Disaster Emergency</td></tr>
<tr><td>2024-03-01</td><td><a href="/executive-orders/24-03-1">Executive Order 24-03.1</a></td><td>Extension of Executive Order 24-03</td></tr></table>
"""


class RhodeIslandScraperTests(unittest.TestCase):
    def test_archive_parsing_and_relationship(self):
        base, extension = ri.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(base.stable_id, "RI-EO-24-03")
        self.assertEqual(extension.stable_id, "RI-EO-24-03.1")
        self.assertEqual(ri.classify_action(extension), "extension")
        relation = ri.extract_relationships(extension)[0]
        self.assertEqual(relation["target_order_id"], base.stable_id)

    def test_weather_requires_explicit_hazard(self):
        action = ri.parse_archive_page(ARCHIVE_FIXTURE)[0]
        self.assertFalse(ri.is_weather_related(action))
        action.document_text = "Heavy snow and wind gusts will affect Rhode Island."
        self.assertTrue(ri.is_weather_related(action))

    def test_generic_declaration_uses_official_hazard_sentence(self):
        action = ri.parse_archive_page(ARCHIVE_FIXTURE)[0]
        html = '<main>Executive Order 24-03. WHEREAS, a winter storm with heavy snow is forecast.</main>'
        class Response:
            text = html
        original = ri.fetch
        try:
            ri.fetch = lambda _url: Response()
            ri.enrich_detail(action)
        finally:
            ri.fetch = original
        self.assertIn("winter storm", action.description)

    def test_extensive_flooding_is_not_an_extension(self):
        action = ri.parse_archive_page(ARCHIVE_FIXTURE)[0]
        action.description += ": high winds and extensive flooding"
        self.assertEqual(ri.classify_action(action), "declaration")

    def test_join_schema_and_filter(self):
        base, extension = ri.parse_archive_page(ARCHIVE_FIXTURE)
        base.action_type = "declaration"; base.weather_related = True
        extension.action_type = "extension"; extension.weather_related = True
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            ri.write_outputs([base, extension], [], *paths)
            with open(paths[2], newline="") as handle: rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), ri.JOIN_FIELDS)


if __name__ == "__main__": unittest.main()
