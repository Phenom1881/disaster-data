import csv,tempfile,unittest
import ga_eo_scraper as ga

FIXTURE='''<table id="datatable"><tbody><tr><td><a href="/document/x/download">08.29.23.01</a></td><td class="views-field-field-document-description">Declaring a State of Emergency for Hurricane Idalia</td></tr><tr><td><a href="/document/y/download">08.29.23.02</a></td><td class="views-field-field-document-description">Regarding Commercial Vehicle Operations During the State of Emergency for Hurricane Idalia</td></tr></tbody></table>'''
class Tests(unittest.TestCase):
    def test_parse_and_narrow_companion(self):
        original,companion=ga.parse_current(FIXTURE,ga.ARCHIVE_URL); self.assertEqual(original.date,"2023-08-29"); self.assertEqual(ga.classify(original),"declaration"); self.assertEqual(ga.classify(companion),"administrative")
    def test_join_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=[f"{d}/{x}.csv" for x in "arj"]; ga.write_outputs(ga.parse_current(FIXTURE,ga.ARCHIVE_URL),*p)
            with open(p[2],encoding="utf-8") as h: rows=list(csv.DictReader(h))
        self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(ga.JOIN_FIELDS))
class ReviewedWeatherTests(unittest.TestCase):
    def test_a_county_only_title_takes_the_reviewed_reading(self):
        # 02.10.14.01 names 14 counties but no hazard; the Governor's release
        # gives the winter storm warning.
        reviewed=ga.Action("02.10.14.01","Declaring a State of Emergency for 14 counties in North Georgia","u","s")
        other=ga.Action("03.30.17.03","Declaring a State of Emergency in response to the I-85 bridge collapse","u","s")
        with tempfile.TemporaryDirectory() as d:
            p=[f"{d}/{x}.csv" for x in "arj"]; ga.write_outputs([reviewed,other],*p)
            with open(p[2],encoding="utf-8") as h: joined=[r["declaration_id"] for r in csv.DictReader(h)]
        self.assertEqual(joined,["GA-EO-02-10-14-01"])
    def test_an_expansion_is_not_reviewed_in(self):
        self.assertNotIn("GA-EO-12-30-15-01",ga.REVIEWED_WEATHER)
    def test_every_reviewed_order_has_a_cited_hazard(self):
        import os
        here=os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here,"hazard_overrides.csv"),encoding="utf-8") as h: overrides={r["declaration_id"]:r for r in csv.DictReader(h)}
        with open(os.path.join(here,"declarations_for_join.csv"),encoding="utf-8") as h: joined={r["declaration_id"] for r in csv.DictReader(h)}
        for key in ga.REVIEWED_WEATHER:
            self.assertIn(key,overrides); self.assertIn(key,joined)
            self.assertNotEqual(overrides[key]["hazard_category_override"].strip().lower(),"exclude")
            self.assertTrue(overrides[key]["source_url"].startswith("https://nathandeal.georgia.gov/press-releases/"))
if __name__=="__main__": unittest.main()
