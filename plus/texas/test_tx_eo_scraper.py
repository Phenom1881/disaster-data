import csv, tempfile, unittest
import tx_eo_scraper as tx

DETAIL='''<main><h1>Governor Abbott Issues Severe Storm Disaster Proclamation</h1><p>June 15, 2026 | Austin, Texas | Proclamation</p><p>WHEREAS severe storms included heavy rainfall, flash flooding, hail and tornado threats; I do hereby certify that this event is a disaster.</p></main>'''

class TexasTests(unittest.TestCase):
    def test_listing(self):
        rows,next_url=tx.parse_listing('''<h3><a href="/news/post/example">Governor Abbott Issues Severe Storm Disaster Proclamation</a></h3><a class="pagination-next" href="/news/category/proclamation/P8">Next</a>''')
        self.assertEqual(len(rows),1); self.assertTrue(next_url.endswith("/P8"))
    def test_original_join_and_renewal_exclusion(self):
        original=tx.Action("PROCLAMATION-2026-06-15-test","Governor Abbott Issues Severe Storm Disaster Proclamation","2026-06-15","https://gov.texas.gov/news/post/test",BeautifulText)
        renewal=tx.Action("PROCLAMATION-2026-07-15-test","Governor Abbott Amends, Renews Severe Storm Disaster Proclamation","2026-07-15","https://gov.texas.gov/news/post/test2",BeautifulText)
        with tempfile.TemporaryDirectory() as root:
            paths=[root+f"/{n}.csv" for n in ("actions","rels","join")]; tx.write_outputs([original,renewal],*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(tx.JOIN_FIELDS))
    def test_no_overrides(self): self.assertEqual(tx.HAZARD_OVERRIDES,{})
    def test_county_addition_excluded(self):
        action=tx.Action("PROCLAMATION-2015-01-01-test","Disaster Proclamation issued for North Texas Storms Adding Wichita County","2015-01-01","https://gov.texas.gov/news/post/test",BeautifulText)
        self.assertEqual(tx.classify(action),"amendment")

BeautifulText="severe storms, heavy rainfall, flash flooding, hail and tornado threats; I do hereby certify that this event is a disaster"
if __name__=="__main__": unittest.main()
