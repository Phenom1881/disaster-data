import csv, tempfile, unittest
from datetime import date
from unittest import mock
import requests
import tx_eo_scraper as tx

DETAIL='''<main><h1>Governor Abbott Issues Severe Storm Disaster Proclamation</h1><p>June 15, 2026 | Austin, Texas | Proclamation</p><p>WHEREAS severe storms included heavy rainfall, flash flooding, hail and tornado threats; I do hereby certify that this event is a disaster.</p></main>'''
LISTING='''<html><head><title>News Archive | Office of the Texas Governor</title></head><body>
<h3><a href="/news/post/governor-abbott-issues-severe-storm-disaster-proclamation-in-june-2026">Governor Abbott Issues Severe Storm Disaster Proclamation In June 2026</a></h3>
<h3><a href="/news/post/governor-abbott-announces-jobs">Governor Abbott Announces Jobs</a></h3></body></html>'''
EMPTY_LISTING='''<html><head><title>News Archive | Office of the Texas Governor</title></head><body><h3><a href="/news/post/jobs">Governor Abbott Announces Jobs</a></h3></body></html>'''
CHANGED_LAYOUT='''<html><head><title>Just a moment...</title></head><body><div>Checking your browser</div></body></html>'''

class FakeResponse:
    def __init__(self,text,status=200): self.text=text; self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400: raise requests.HTTPError(f"{self.status_code} for url")

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
    def test_month_urls_stop_at_the_current_month(self):
        urls=tx.month_urls(date(2026,9,26))
        self.assertEqual(urls[0],"https://gov.texas.gov/news/archive/2015/01")
        self.assertEqual(urls[-1],"https://gov.texas.gov/news/archive/2026/09")
        self.assertEqual(len(urls),11*12+9)
    def test_county_addition_excluded(self):
        action=tx.Action("PROCLAMATION-2015-01-01-test","Disaster Proclamation issued for North Texas Storms Adding Wichita County","2015-01-01","https://gov.texas.gov/news/post/test",BeautifulText)
        self.assertEqual(tx.classify(action),"amendment")

class CollectTests(unittest.TestCase):
    """collect() against a fake site, so no network is used."""
    def setUp(self):
        patcher=mock.patch.object(tx,"month_urls",return_value=[tx.MONTH_URL.format(year=2026,month=m) for m in range(1,10)])
        patcher.start(); self.addCleanup(patcher.stop)
        sleeper=mock.patch.object(tx.time,"sleep"); sleeper.start(); self.addCleanup(sleeper.stop)

    def _site(self,listing_for):
        def fake_get(url,headers=None,timeout=None):
            if "/news/post/" in url: return FakeResponse(DETAIL)
            return listing_for(url)
        return mock.patch.object(tx.requests,"get",side_effect=fake_get)

    def test_one_failing_month_is_skipped_not_fatal(self):
        # Sep 25: a single 500 on one month used to fail all of Texas.
        with self._site(lambda url: FakeResponse("",500) if url.endswith("/2026/03") else FakeResponse(LISTING)):
            stats={}; actions=tx.collect(stats)
        self.assertEqual(len(actions),1)
        self.assertEqual(stats["months_failed"],1); self.assertEqual(stats["months_read"],8)

    def test_retry_recovers_a_transient_500(self):
        calls={"n":0}
        def listing(url):
            if url.endswith("/2026/08"):
                calls["n"]+=1
                if calls["n"]==1: return FakeResponse("",500)
            return FakeResponse(LISTING)
        with self._site(listing):
            stats={}; tx.collect(stats)
        self.assertEqual(stats["months_failed"],0)

    def test_pages_with_no_proclamations_anywhere_is_an_error_not_an_empty_state(self):
        with self._site(lambda url: FakeResponse(EMPTY_LISTING)):
            with self.assertRaisesRegex(RuntimeError,"found no proclamation posts"):
                tx.collect({})

    def test_changed_layout_names_the_page_it_got(self):
        with self._site(lambda url: FakeResponse(CHANGED_LAYOUT)):
            with self.assertRaisesRegex(RuntimeError,"Just a moment"):
                tx.collect({})

    def test_site_down_fails_fast(self):
        with self._site(lambda url: FakeResponse("",503)):
            with self.assertRaisesRegex(RuntimeError,"did not answer"):
                tx.collect({})

BeautifulText="severe storms, heavy rainfall, flash flooding, hail and tornado threats; I do hereby certify that this event is a disaster"
if __name__=="__main__": unittest.main()
