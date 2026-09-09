import csv, tempfile, unittest
import fl_eo_scraper as fl

FIXTURE='''<table><tbody><tr><td class="views-field-field-file-upload"><a href="/orders/EO.pdf">#2024-214 re: Emergency Management – Tropical Storm Milton</a></td><td><time datetime="2024-10-05T12:00:00Z">10/05/2024</time></td></tr><tr><td class="views-field-field-file-upload"><a href="/orders/X.pdf">#2024-220 extends Executive Order 2024-214 – Hurricane Milton</a></td><td><time datetime="2024-12-01T12:00:00Z">12/01/2024</time></td></tr></tbody></table>'''
class Tests(unittest.TestCase):
    def test_parse_classify_and_relationship(self):
        original,extension=fl.parse_page(FIXTURE); self.assertEqual(fl.classify(original),"declaration"); self.assertEqual(fl.classify(extension),"extension"); self.assertEqual(fl.relationships(extension,"extension")[0]["target_order_id"],"FL-EO-2024-214")
    def test_join_schema_excludes_extension(self):
        with tempfile.TemporaryDirectory() as d:
            p=[f"{d}/{x}.csv" for x in "arj"]; fl.write_outputs(fl.parse_page(FIXTURE),*p)
            with open(p[2],encoding="utf-8") as h: rows=list(csv.DictReader(h))
        self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(fl.JOIN_FIELDS))
if __name__=="__main__": unittest.main()
