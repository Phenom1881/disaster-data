import csv
import tempfile
import unittest
import nm_eo_scraper as nm

TEXT = """STATE OF NEW MEXICO EXECUTIVE ORDER 2024-100 DECLARING A STATE OF EMERGENCY DUE TO SEVERE STORMS AND FLOODING WHEREAS heavy rainfall caused flooding; I hereby declare a state of emergency. Signed this 20th day of June, 2024."""

class NewMexicoTests(unittest.TestCase):
    def test_index(self):
        rows = nm.parse_index('<a href="/files/a.pdf">Executive Order 2024-100</a>', nm.ARCHIVE_URL)
        self.assertEqual(rows[0][0], "2024-100")

    def test_date_title_and_classification(self):
        action = nm.Action("2024-100", nm.extract_title(TEXT, "2024-100"), nm.extract_date(TEXT, "2024-100"), "https://example.gov/a.pdf", TEXT)
        self.assertEqual(action.date, "2024-06-20")
        self.assertEqual(nm.classify(action), "declaration")

    def test_modifier_excluded_from_join(self):
        original = nm.Action("2024-100", "Declaring a State of Emergency Due to Severe Storms and Flooding", "2024-06-20", "https://example.gov/a.pdf", TEXT)
        renewal = nm.Action("2024-101", "Renewing the State of Emergency Due to Severe Storms and Flooding", "2024-07-20", "https://example.gov/b.pdf", TEXT)
        with tempfile.TemporaryDirectory() as root:
            paths = [root + "/" + name for name in ("actions.csv", "rels.csv", "join.csv")]
            nm.write_outputs([original, renewal], *paths)
            with open(paths[2], encoding="utf-8") as handle: rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(tuple(rows[0]), nm.JOIN_FIELDS)

    def test_no_overrides(self):
        self.assertEqual(nm.HAZARD_OVERRIDES, {})

    def test_scan_is_unclassified(self):
        action = nm.Action("2024-999", "Executive Order 2024-999 (text unavailable)", "", "https://example.gov/scan.pdf", "", False, True)
        self.assertEqual(nm.classify(action), "unclassified")

if __name__ == "__main__": unittest.main()
