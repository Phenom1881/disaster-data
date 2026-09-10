import csv
import tempfile
import unittest
from pathlib import Path
import ca_eo_scraper as ca

class CaliforniaScraperTests(unittest.TestCase):
    def action(self, title="Governor Newsom declares state of emergency due to winter storms"):
        return ca.Action(123, title, "Flooding and high winds", "2024-02-04", "https://www.gov.ca.gov/example/")
    def test_declaration(self): self.assertEqual(ca.classify(self.action()), "declaration")
    def test_commentary_not_declaration(self): self.assertEqual(ca.classify(self.action("What they’re saying: Governor Newsom’s state of emergency")), "administrative")
    def test_join_schema_and_modifier_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ca.write_outputs([self.action(), self.action("Governor terminates state of emergency for winter storms")],root/"a.csv",root/"r.csv",root/"j.csv")
            with (root/"j.csv").open() as f: rows=list(csv.DictReader(f)); self.assertEqual(tuple(rows[0]),ca.JOIN_FIELDS); self.assertEqual(len(rows),1)

if __name__ == "__main__": unittest.main()
