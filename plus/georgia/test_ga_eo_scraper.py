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

def page(*orders):
    rows="".join(f'<tr><td><a href="/document/{n}/download">{n}</a></td><td class="views-field-field-document-description">{d}</td></tr>' for n,d in orders)
    return f'<table id="datatable"><tbody>{rows}</tbody></table>'
YEAR="https://gov.georgia.gov/executive-action/executive-orders/2023"
FIRST=page(("01.18.23.01","Extending the State of Emergency for Tornadoes and Severe Storms"))
SECOND=page(("01.12.23.02","Declaring a State of Emergency for Tornadoes and Severe Storms"),("01.06.23.01","Renewing the State of Emergency for Supply Chain Disruptions"))
class PagedYearTests(unittest.TestCase):
    """A year's page lists at most 500 orders; the earliest weeks are on ?page=1 and after."""
    def getter(self,pages):
        calls=[]
        def get(url):
            calls.append(url)
            if url not in pages: raise ga.requests.HTTPError("404")
            return pages[url]
        return get,calls
    def test_later_pages_are_read(self):
        get,calls=self.getter({YEAR:FIRST,YEAR+"?page=1":SECOND,YEAR+"?page=2":page()})
        numbers=[a.number for a in ga.collect_year(YEAR,get)]
        self.assertEqual(numbers,["01.18.23.01","01.12.23.02","01.06.23.01"])
        self.assertEqual(calls,[YEAR,YEAR+"?page=1",YEAR+"?page=2"])
    def test_a_page_that_ignores_the_parameter_ends_the_year(self):
        get,calls=self.getter({YEAR:FIRST,YEAR+"?page=1":FIRST})
        self.assertEqual([a.number for a in ga.collect_year(YEAR,get)],["01.18.23.01"])
        self.assertEqual(len(calls),2)
    def test_a_missing_later_page_ends_the_year_and_a_missing_first_page_fails(self):
        get,_=self.getter({YEAR:FIRST})
        self.assertEqual(len(ga.collect_year(YEAR,get)),1)
        get,_=self.getter({})
        with self.assertRaises(ga.requests.HTTPError): ga.collect_year(YEAR,get)
    def test_orders_from_later_pages_keep_the_year_page_as_their_source(self):
        get,_=self.getter({YEAR:FIRST,YEAR+"?page=1":SECOND})
        tornado=next(a for a in ga.collect_year(YEAR,get) if a.number=="01.12.23.02")
        self.assertEqual(tornado.source,YEAR)
        self.assertEqual(tornado.url,"https://gov.georgia.gov/document/01.12.23.02/download")
        self.assertEqual((tornado.date,ga.classify(tornado)),("2023-01-12","declaration"))
if __name__=="__main__": unittest.main()
