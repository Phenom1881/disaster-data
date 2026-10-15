import csv
import tempfile
import unittest
from pathlib import Path

import al_eo_scraper as al


def post(title, date="2023-07-13"):
    return {"title":{"rendered":title},"content":{"rendered":'<a href="/order.pdf">Download</a>'},"link":"https://governor.alabama.gov/newsroom/test/","date":date+"T12:00:00"}


class AlabamaScraperTests(unittest.TestCase):
    def test_embedded_event_date_is_preserved(self):
        action=al.parse_post(post("State of Emergency: June 10, 2023 Severe Weather"),"state_of_emergency")
        self.assertEqual(action.date,"2023-06-10")

    def test_subtropical_storm_is_weather(self):
        action=al.parse_post(post("State of Emergency: Subtropical Storm Alberto","2018-05-26"),"state_of_emergency")
        self.assertEqual(al.classify(action),"declaration")
        self.assertIsNotNone(al.HAZARD_RE.search(action.title))

    def test_supplemental_order_is_excluded_from_join(self):
        original=al.parse_post(post("State of Emergency: Hurricane Ida","2021-08-28"),"state_of_emergency")
        supplement=al.parse_post(post("First Supplemental State of Emergency: Hurricane Ida","2021-09-02"),"state_of_emergency")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); al.write_outputs([original,supplement],root/"a.csv",root/"r.csv",root/"j.csv")
            with open(root/"j.csv",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)


class _Resp:
    def __init__(self, posts=None, status=200, headers=None):
        self.posts = posts or []; self.status_code = status; self.headers = headers or {}
    def json(self): return self.posts
    def raise_for_status(self):
        if self.status_code >= 400: raise al.requests.HTTPError(str(self.status_code))


class _Site:
    """The WordPress posts API for one category: `pages` lists of posts,
    with or without the page-count headers."""
    def __init__(self, pages, headers=True):
        self.pages = pages; self.headers = headers; self.asked = []
    def get(self, url, params=None, **kw):
        page = params["page"]; self.asked.append(page)
        if page > len(self.pages): return _Resp(status=400)
        total = sum(len(p) for p in self.pages)
        return _Resp(self.pages[page - 1], headers={"X-WP-Total": str(total), "X-WP-TotalPages": str(len(self.pages))} if self.headers else {})


def posts(n, start=0):
    return [post(f"State of Emergency: Storm {i}", f"20{17 + i % 9:02d}-0{1 + i % 9}-1{i % 9}") for i in range(start, start + n)]


class AlabamaPagingTests(unittest.TestCase):
    """The API gives at most 100 posts a page; every page must be read."""

    def test_every_page_is_read(self):
        site = _Site([posts(100), posts(5, 100)])
        self.assertEqual(len(al.category_posts(19, site)), 105)
        self.assertEqual(site.asked, [1, 2])

    def test_without_page_headers_a_short_page_or_a_400_ends_it(self):
        site = _Site([posts(100), posts(100, 100), posts(7, 200)], headers=False)
        self.assertEqual(len(al.category_posts(19, site)), 207); self.assertEqual(site.asked, [1, 2, 3])
        site = _Site([posts(100)], headers=False)
        self.assertEqual(len(al.category_posts(19, site)), 100); self.assertEqual(site.asked, [1, 2])   # page 2 answered 400

    def test_a_failed_first_page_or_a_short_read_is_an_error(self):
        class Down:
            def get(self, url, params=None, **kw): return _Resp(status=503)
        with self.assertRaises(al.requests.HTTPError): al.category_posts(19, Down())
        class Short(_Site):
            def get(self, url, params=None, **kw):
                r = super().get(url, params, **kw)
                r.headers = dict(r.headers, **{"X-WP-Total": "250"}) if r.headers else r.headers
                return r
        with self.assertRaises(RuntimeError): al.category_posts(19, Short([posts(100), posts(100, 100)]))

    def test_collect_reads_both_categories_in_full(self):
        class Both:
            def __init__(self): self.sites = {19: _Site([posts(100), posts(5, 100)]), 11: _Site([[post("Executive Order 746", "2026-10-01")]])}
            def get(self, url, params=None, **kw): return self.sites[params["categories"]].get(url, params, **kw)
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            actions = al.collect(Both())
        self.assertEqual(len(actions), 106)
        self.assertIn("read 105 state of emergency posts and 1 executive orders posts", out.getvalue())


class AlabamaDescriptionTests(unittest.TestCase):
    def test_descriptions_use_no_dashes(self):
        eo = al.parse_post({"title": {"rendered": "Executive Order 704"}, "content": {"rendered": '<a href="/eo704.pdf">EO 2 Broadband</a>'},
                            "link": "https://governor.alabama.gov/newsroom/2017/04/eo-704/", "date": "2017-04-26T12:00:00"}, "executive_orders")
        self.assertEqual(eo.title, "Executive Order 704: EO 2 Broadband")
        st_clair = al.parse_post(post("State of Emergency: St. Clair County", "2023-01-18"), "state_of_emergency")
        self.assertEqual(st_clair.title, "State of Emergency: St. Clair County (smoldering underground landfill fire in St. Clair County)")
        self.assertEqual(st_clair.stable_id, "AL-SOE-2023-01-18-state-of-emergency-st-clair-county")   # id unchanged


if __name__ == "__main__": unittest.main()
