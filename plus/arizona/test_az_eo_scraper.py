import csv, tempfile, unittest
import az_eo_scraper as az

class ArizonaTests(unittest.TestCase):
    def test_listing_and_number_normalization(self):
        html='''<div><h4>Extreme Heat Planning and Preparedness</h4><h3>Executive Order: 16</h3><span>August 11, 2023</span><a href="/office-arizona-governor/executive-order/16">Learn More</a></div>'''
        rows=az.parse_listing(html)
        self.assertEqual(rows[0][:3],("2023-16","Extreme Heat Planning and Preparedness","2023-08-11"))
    def test_heat_plan_not_declaration(self):
        action=az.Action("2023-16","Extreme Heat Planning and Preparedness","2023-08-11","https://example.gov/16","directing agencies to prepare for extreme heat")
        self.assertEqual(az.classify(action),"administrative")
    def test_declaration_and_join_schema(self):
        action=az.Action("2023-99","Declaring a State of Emergency Due to Wildfires","2023-06-01","https://example.gov/99","I hereby declare a state of emergency due to wildfires")
        with tempfile.TemporaryDirectory() as root:
            paths=[root+"/"+n for n in ("a.csv","r.csv","j.csv")]; az.write_outputs([action],*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1); self.assertEqual(tuple(rows[0]),az.JOIN_FIELDS)
    def test_no_overrides(self): self.assertEqual(az.HAZARD_OVERRIDES,{})
if __name__=="__main__": unittest.main()
