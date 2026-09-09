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
if __name__=="__main__": unittest.main()
