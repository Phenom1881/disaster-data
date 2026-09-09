import csv
import tempfile
import unittest
from pathlib import Path

import tn_eo_scraper as tn


class TennesseeScraperTests(unittest.TestCase):
    def action(self, governor="Bill Lee", number="105", title="No. 105 An Order to Provide Relief to Victims of Severe Weather and Flooding in Tennessee", date="2024-09-27"):
        return tn.Action(number, title, date, governor, "https://example.test/record", "https://example.test/order.pdf", "https://example.test/notice")

    def test_ids_include_governor_to_prevent_number_collisions(self):
        self.assertEqual(self.action().stable_id, "TN-BILLLEE-EO-105")
        self.assertNotEqual(self.action().stable_id, self.action("Bill Haslam").stable_id)

    def test_officially_corroborated_weather_order_is_declaration(self):
        self.assertEqual(tn.classify(self.action()), "declaration")

    def test_amendment_is_not_a_declaration(self):
        action=self.action(number="106", title="No. 106 An Order Amending Executive Order No. 105")
        self.assertEqual(tn.classify(action), "amendment")

    def test_join_excludes_modifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base=self.action(); amendment=self.action(number="106",title="No. 106 An Order Amending Executive Order No. 105")
            tn.write_outputs([base,amendment],root/"a.csv",root/"r.csv",root/"j.csv")
            with open(root/"j.csv",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual([row["declaration_id"] for row in rows],[base.stable_id])


if __name__ == "__main__": unittest.main()
