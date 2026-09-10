import csv
import tempfile
import unittest
from pathlib import Path
import or_eo_scraper as ore

class OregonScraperTests(unittest.TestCase):
    def action(self, description="Determination of State of Emergency due to a Severe Winter Storm"):
        return ore.Action(2024,"5",description,"https://www.oregon.gov/gov/eo/eo-24-05.pdf",signed="2024-01-12")
    def test_original(self): self.assertEqual(ore.classify(self.action()),"declaration")
    def test_extension(self): self.assertEqual(ore.classify(self.action("Extending Executive Order 24-05")),"extension")
    def test_signature_date(self):
        old=ore.pdf_text_and_date
        self.assertRegex(ore.DATE_RE.search("DONE AT SALEM THIS 12th day of January, 2024").group(0),"January")
    def test_join_excludes_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ore.write_outputs([self.action(),self.action("Extending Executive Order 24-05")],root/"a.csv",root/"r.csv",root/"j.csv")
            with (root/"j.csv").open() as f: rows=list(csv.DictReader(f)); self.assertEqual(tuple(rows[0]),ore.JOIN_FIELDS); self.assertEqual(len(rows),1)

if __name__ == "__main__": unittest.main()
