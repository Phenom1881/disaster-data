import csv
import tempfile
import unittest
from pathlib import Path
import wa_eo_scraper as wa

class WashingtonScraperTests(unittest.TestCase):
    def action(self, number="21-18", title="Severe Weather Damage", text="I proclaim that a State of Emergency exists due to flooding"):
        return wa.Action(number,"2021-11-15",title,"https://governor.wa.gov/example.pdf",text=text)
    def test_original(self): self.assertEqual(wa.classify(self.action()),"declaration")
    def test_decimal_is_modifier(self): self.assertEqual(wa.classify(self.action("21-18.1","Severe Weather - Truck Driver Hours")),"amendment")
    def test_join_excludes_modifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); wa.write_outputs([self.action(),self.action("21-18.1","Severe Weather - Truck Driver Hours")],root/"a.csv",root/"r.csv",root/"j.csv")
            with (root/"j.csv").open() as f: rows=list(csv.DictReader(f)); self.assertEqual(tuple(rows[0]),wa.JOIN_FIELDS); self.assertEqual(len(rows),1)

if __name__ == "__main__": unittest.main()
