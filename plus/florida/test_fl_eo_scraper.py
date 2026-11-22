import contextlib, csv, io, os, sys, tempfile, unittest
from unittest import mock
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
    def test_storm_named_after_signing_gets_its_later_name(self):
        page=FIXTURE.replace("#2024-214 re: Emergency Management","#2026-202 re: Emergency Management").replace("Tropical Storm Milton","Tropical Depression Nine")
        original=fl.parse_page(page)[0]
        self.assertTrue(fl.listed_title(original).endswith("Tropical Depression Nine (later Hurricane Isaias)"))
        self.assertEqual(fl.classify(original),"declaration")
        with tempfile.TemporaryDirectory() as d:
            p=[f"{d}/{x}.csv" for x in "arj"]; fl.write_outputs([original],*p)
            with open(p[2],encoding="utf-8") as h: rows=list(csv.DictReader(h))
        self.assertEqual(rows[0]["event_description"].count("Isaias"),1)
        self.assertEqual(fl.listed_title(fl.parse_page(FIXTURE)[0]),fl.parse_page(FIXTURE)[0].title)

YEAR_SELECT='<form><select name="field_date_value" id="edit-field-date-value"><option value="All">- Any -</option><option value="8" selected="selected">2027</option><option value="1">2026</option></select></form>'

class FakeResponse:
    def __init__(self,text): self.text=text

class YearFilterTests(unittest.TestCase):
    def fetches(self,pages):
        """Run collect() against pages keyed by the year filter value (None for
        the first, unfiltered load); returns (orders, year values requested)."""
        asked=[]
        def fake_fetch(url,params=None):
            value=(params or {}).get(fl.YEAR_FILTER)
            if params is not None: asked.append(value)
            return FakeResponse(pages.get(value,"<table><tbody></tbody></table>"))
        with mock.patch.object(fl,"fetch",fake_fetch), contextlib.redirect_stderr(io.StringIO()):
            orders=fl.collect()
        return orders,asked
    def test_filter_values_come_from_the_page(self):
        self.assertEqual(fl.year_filter_values(YEAR_SELECT),("8","1"))
        self.assertEqual(fl.year_filter_values(FIXTURE),())
    def test_each_year_on_the_filter_is_read(self):
        orders,asked=self.fetches({None:YEAR_SELECT+FIXTURE,"8":FIXTURE})
        self.assertEqual(asked,["8","1"])
        self.assertEqual([o.number for o in orders],["2024-220","2024-214"])
    def test_without_the_filter_the_2026_values_are_read(self):
        orders,asked=self.fetches({None:FIXTURE,"3":FIXTURE})
        self.assertEqual(asked,[str(v) for v in range(1,8)])
        self.assertEqual(len(orders),2)
    def test_an_archive_with_no_orders_fails_and_says_what_came_back(self):
        page="<html><head><title>Site Maintenance</title></head><body>Back soon</body></html>"
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fl,"fetch",lambda url,params=None:FakeResponse(page)), \
                mock.patch.object(sys,"argv",["fl_eo_scraper.py","--actions-out",f"{d}/a.csv","--relationships-out",f"{d}/r.csv","--join-out",f"{d}/j.csv"]):
            err=io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop: fl.main()
            self.assertEqual(stop.exception.code,2)
            self.assertIn("0 orders parsed from the archive",err.getvalue()); self.assertIn("Site Maintenance",err.getvalue())
            self.assertFalse(any(os.path.exists(f"{d}/{x}.csv") for x in "arj"))
if __name__=="__main__": unittest.main()
