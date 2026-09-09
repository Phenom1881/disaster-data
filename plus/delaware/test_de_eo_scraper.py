import csv
import tempfile
import unittest

import de_eo_scraper as de


ARCHIVE_FIXTURE = """
<div class="state-of-emergency-archive"><ul>
<li data-year="2026"><a class="text-primary fw-semibold" href="/state-of-emergency/storm/">Declaration of a State of Emergency Due to a Severe Winter Storm</a><div><span>January 23, 2026</span><a href="/storm.pdf">View PDF</a></div></li>
<li data-year="2026"><a class="text-primary fw-semibold" href="/state-of-emergency/end/">Termination of State of Emergency Due to a Severe Winter Storm</a><div><span>January 26, 2026</span><a href="/end.pdf">View PDF</a></div></li>
</ul></div>
"""


class DelawareScraperTests(unittest.TestCase):
    def test_archive_parsing_and_classification(self):
        declaration, termination = de.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(declaration.date_signed, "2026-01-23")
        self.assertEqual(declaration.action_type, "declaration")
        self.assertTrue(declaration.weather_related)
        self.assertEqual(termination.action_type, "termination")

    def test_relationship_uses_matching_prior_declaration(self):
        actions = de.parse_archive_page(ARCHIVE_FIXTURE)
        relation = de.build_relationships(actions)[0]
        self.assertEqual(relation["target_order_id"], actions[0].stable_id)
        self.assertEqual(relation["relationship_type"], "terminates")

    def test_extensive_does_not_mean_extension(self):
        self.assertEqual(de.classify_title("Declaration after extensive flooding"), "declaration")

    def test_join_schema_and_filter(self):
        actions = de.parse_archive_page(ARCHIVE_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            de.write_outputs(actions, *paths)
            with open(paths[2], newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), list(de.JOIN_FIELDS))


if __name__ == "__main__":
    unittest.main()
