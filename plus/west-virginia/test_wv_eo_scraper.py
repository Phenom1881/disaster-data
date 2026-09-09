import csv
import tempfile
import unittest

import wv_eo_scraper as wv


ARCHIVE_FIXTURE = """
<div class="view-news-an"><div class="view-content">
<div class="views-row"><time datetime="2025-02-06T12:00:00Z">February 6, 2025</time><a href="/article/storm" title="Read article: Governor Morrisey Declares State of Emergency in Cabell and Kanawha Counties">read more</a></div>
<div class="views-row"><time datetime="2025-03-07T12:00:00Z">March 7, 2025</time><a href="/article/extend" title="Read article: Governor Morrisey Extends State of Emergency in Flood-Affected Counties">read more</a></div>
<div class="views-row"><time datetime="2025-03-08T12:00:00Z">March 8, 2025</time><a href="/article/other" title="Read article: Governor Morrisey Announces an Appointment">read more</a></div>
</div></div>
"""


class WestVirginiaScraperTests(unittest.TestCase):
    def test_news_archive_filters_and_classifies(self):
        declaration, extension = wv.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(declaration.date_signed, "2025-02-06")
        self.assertEqual(declaration.action_type, "declaration")
        self.assertEqual(extension.action_type, "extension")

    def test_direct_article_language_supplies_hazard(self):
        sentence = wv.hazard_sentence("The declaration follows severe rainstorms and flooding across two counties.")
        self.assertIn("flooding", sentence)

    def test_join_schema_and_modifier_filter(self):
        declaration, extension = wv.parse_archive_page(ARCHIVE_FIXTURE)
        declaration.description = declaration.title + " — severe rainstorms and flooding"
        declaration.weather_related = True
        extension.description = extension.title
        extension.weather_related = True
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            wv.write_outputs([declaration, extension], *paths)
            with open(paths[2], newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), list(wv.JOIN_FIELDS))


if __name__ == "__main__":
    unittest.main()
