import csv
import tempfile
import unittest

import md_eo_scraper as md


ARCHIVE_FIXTURE = """
<ul><li class="maryland-listing-item"><article><div>
<a class="maryland-listing-item__title" href="/media/1"><h3><span class="maryland-link__document-title">Declaration of a State of Emergency - Winter Storm (EO# 01.01.2025.02)</span></h3></a>
<div class="maryland-listing-item__date">Sunday, January 5, 2025</div></div></article></li>
<li class="maryland-listing-item"><article><div>
<a class="maryland-listing-item__title" href="/media/2"><h3><span class="maryland-link__document-title">Rescission of Executive Order 01.01.2025.02 (EO# 01.01.2025.03)</span></h3></a>
<div class="maryland-listing-item__date">Monday, January 6, 2025</div></div></article></li></ul>
"""


class MarylandScraperTests(unittest.TestCase):
    def test_archive_parsing_and_number_choice(self):
        declaration, rescission = md.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(declaration.eo_number, "01.01.2025.02")
        self.assertEqual(rescission.eo_number, "01.01.2025.03")
        self.assertEqual(md.classify_action(rescission), "termination")

    def test_relationship_targets_referenced_order(self):
        action = md.parse_archive_page(ARCHIVE_FIXTURE)[1]
        action.action_type = md.classify_action(action)
        relation = md.extract_relationships(action)[0]
        self.assertEqual(relation["target_order_id"], "MD-EO-01-01-2025-02")

    def test_generic_declaration_uses_direct_hazard_sentence(self):
        action = md.Action("01.01.2023.13", "Declaration of a State of Emergency", "2023-09-22", "https://example.test/order.pdf", md.ARCHIVE_URL, "Wes Moore")
        self.assertEqual(md.hazard_sentence("WHEREAS, a severe storm threatens Maryland. NOW THEREFORE"), "WHEREAS, a severe storm threatens Maryland.")

    def test_join_schema_and_filter(self):
        declaration, rescission = md.parse_archive_page(ARCHIVE_FIXTURE)
        for action in (declaration, rescission):
            action.action_type = md.classify_action(action)
            action.description = action.title
            action.weather_related = bool(md.HAZARD_RE.search(action.title))
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            md.write_outputs([declaration, rescission], *paths)
            with open(paths[2], newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), list(md.JOIN_FIELDS))


if __name__ == "__main__":
    unittest.main()
