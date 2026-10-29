"""
Unit tests for mt_eo_scraper.py against fixtures matching the real rendered
text of gov.mt.gov's current EO page and formergovernors.mt.gov/bullock.
"""
import csv
import os
import tempfile
import unittest

import mt_eo_scraper as scraper

CURRENT_FIXTURE = """
Declaring a Disaster to Exist in the State of Montana
Executive Order 9-2025
December 11, 2025

Creating the Energy Advisory Council
Executive Order No. 6-2025
September 10, 2025

Declaring Statewide Drought Emergency
Executive Order No. 11-2021
July 1, 2021
"""

BULLOCK_FIXTURE = """
## 2019 Executive Orders

- [Declaring a Winter Storm Emergency in Montana](https://formergovernors.mt.gov/bullock/docs/2019EOs/EO%2015-2019_Declaring%20a%20Winter%20Storm%20Emergency.pdf) - Executive Order No. 15-2019
- [Creating the Climate Solutions Council](https://formergovernors.mt.gov/bullock/docs/2019EOs/EO-08-2019_Creating%20Climate%20Solutions%20Council.pdf) - Executive Order No. 8-2019
"""


# The same kind of entries as served: raw HTML. Until Sep 2026 the pattern was
# run on this directly and matched nothing, so every run found 0 orders.
CURRENT_HTML = """<html><body><main><div class="documents">
<div class="doc"><a href="View?doc=EO-2-2026.pdf"><h3>Continuing the Youth Justice Advisory Council</h3>
<p>Executive Order No. 2-2026</p><p>March 1, 2026</p></a></div>
<div class="doc"><a href="View?doc=241211EODisasterDeclarationFlooding.pdf"><h3>Declaring a Disaster to Exist in the State of Montana</h3>
<p>Executive Order 9-2025</p><p>December 11, 2025</p></a></div>
<div class="doc"><h3>Winter Energy Emergency</h3><span>Executive Order No. 2-2024</span><time>January 19, 2024</time></div>
</div></main></body></html>"""

BULLOCK_HTML = """<ul><li><a href="docs/2019EOs/EO%2015-2019_Declaring%20a%20Winter%20Storm%20Emergency.pdf">Declaring a Winter Storm Emergency in Montana</a> - Executive Order No. 15-2019</li></ul>"""


class RawHtmlTests(unittest.TestCase):
    def test_current_page_html(self):
        orders = scraper.parse_current_page(CURRENT_HTML)
        self.assertEqual([o["eo_number"] for o in orders], ["2-2026", "9-2025", "2-2024"])
        by = {o["eo_number"]: o for o in orders}
        self.assertEqual(by["9-2025"]["title"], "Declaring a Disaster to Exist in the State of Montana")
        self.assertEqual(by["9-2025"]["date_text"], "December 11, 2025")
        self.assertEqual(by["9-2025"]["url"], scraper.CURRENT_URL + "View?doc=241211EODisasterDeclarationFlooding.pdf")
        self.assertEqual(by["2-2024"]["url"], scraper.CURRENT_URL)      # no link around that entry

    def test_title_naming_another_order_does_not_take_its_link(self):
        html = CURRENT_HTML.replace('<div class="doc"><a href="View?doc=241211EODisasterDeclarationFlooding.pdf">',
                                    '<div class="doc"><a href="View?doc=EO-12-2025.pdf"><h3>Amending Executive Order 9-2025</h3>'
                                    '<p>Executive Order No. 12-2025</p><p>December 22, 2025</p></a></div>'
                                    '<div class="doc"><a href="View?doc=241211EODisasterDeclarationFlooding.pdf">')
        by = {o["eo_number"]: o for o in scraper.parse_current_page(html)}
        self.assertTrue(by["12-2025"]["url"].endswith("EO-12-2025.pdf"))
        self.assertTrue(by["9-2025"]["url"].endswith("241211EODisasterDeclarationFlooding.pdf"))

    def test_plain_span_inside_a_title_does_not_split_it(self):
        html = ('<div class="doc"><h3>Declaring Statewide <span>Drought</span> Emergency</h3>'
                '<p>Executive Order No. 11-2021</p><p>July 1, 2021</p></div>')
        self.assertEqual(scraper.parse_current_page(html)[0]["title"], "Declaring Statewide Drought Emergency")

    def test_bullock_page_html(self):
        orders = scraper.parse_bullock_page(BULLOCK_HTML)
        self.assertEqual(orders[0]["eo_number"], "15-2019")
        self.assertTrue(orders[0]["url"].startswith("https://formergovernors.mt.gov/bullock/docs/2019EOs/"))

    def test_saved_specific_url_is_kept_over_the_listing_address(self):
        orders = scraper.parse_current_page(CURRENT_HTML)
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "j.csv")
            with open(join_out, "w", encoding="utf-8") as f:
                f.write("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                        "MT-EO-2-2024,Gianforte,2-2024,Winter Energy Emergency,2024-01-19,"
                        "https://www.fmcsa.dot.gov/emergency/montana-executive-order-2-2024\n")
            decls = scraper.write_csv(orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join_out)
        by = {d["declaration_id"]: d for d in decls}
        self.assertEqual(by["MT-EO-2-2024"]["archive_record_url"],
                         "https://www.fmcsa.dot.gov/emergency/montana-executive-order-2-2024")
        self.assertNotIn("MT-EO-2-2026", by)                            # a council, not a declaration


class CurrentPageParsingTests(unittest.TestCase):
    def test_parses_title_number_date_triplets(self):
        orders = scraper.parse_current_page(CURRENT_FIXTURE)
        self.assertEqual(len(orders), 3)
        self.assertEqual(orders[0]["eo_number"], "9-2025")
        self.assertEqual(orders[0]["date_text"], "December 11, 2025")

    def test_date_conversion(self):
        self.assertEqual(scraper.parse_date_text("December 11, 2025"), "2025-12-11")


class BullockPageParsingTests(unittest.TestCase):
    def test_parses_linked_entries_no_date(self):
        orders = scraper.parse_bullock_page(BULLOCK_FIXTURE)
        self.assertEqual(len(orders), 2)
        self.assertIsNone(orders[0]["date_text"])
        self.assertEqual(orders[0]["eo_number"], "15-2019")


class ClassificationTests(unittest.TestCase):
    def test_boilerplate_disaster_title_flagged_for_override(self):
        is_decl, needs_override = scraper.classify_title(
            "Declaring a Disaster to Exist in the State of Montana"
        )
        self.assertTrue(is_decl)
        self.assertTrue(needs_override)

    def test_drought_emergency_no_override_needed(self):
        is_decl, needs_override = scraper.classify_title("Declaring Statewide Drought Emergency")
        self.assertTrue(is_decl)
        self.assertFalse(needs_override)

    def test_council_excluded(self):
        is_decl, _ = scraper.classify_title("Creating the Energy Advisory Council")
        self.assertFalse(is_decl)

    def test_governor_lookup(self):
        self.assertEqual(scraper.governor_for("9-2025"), "Gianforte")
        self.assertEqual(scraper.governor_for("15-2019"), "Bullock")
        self.assertEqual(scraper.governor_for("3-2007"), "Schweitzer")


class WriteCsvTests(unittest.TestCase):
    def test_current_page_entries_written_with_dates(self):
        orders = scraper.parse_current_page(CURRENT_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "j.csv")
            declarations = scraper.write_csv(
                orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join_out
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("MT-EO-9-2025", ids)
            self.assertIn("MT-EO-11-2021", ids)
            self.assertNotIn("MT-EO-6-2025", ids)  # council, excluded

    def test_undated_bullock_entries_excluded_without_confirmed_date(self):
        orders = scraper.parse_bullock_page(BULLOCK_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            declarations = scraper.write_csv(
                orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                os.path.join(tmp, "j.csv"),
            )
            # "Declaring a Winter Storm Emergency" matches the keyword regex
            # but has no date in the Bullock-page fixture and none supplied
            # via confirmed_dates -> must be dropped, not guessed.
            self.assertEqual(len(declarations), 0)


class HandAddedDeclarationTests(unittest.TestCase):
    """manual_declarations.csv carries the 2000-2020 weather orders the
    scraper does not collect. A blank date_signed means the signing day
    could not be read; such a row must carry a reviewed event_date in
    hazard_overrides.csv, or it would drop out of the federal comparison."""

    @staticmethod
    def rows():
        path = os.path.join(os.path.dirname(__file__), "manual_declarations.csv")
        with open(path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def event_dates():
        path = os.path.join(os.path.dirname(__file__), "hazard_overrides.csv")
        with open(path, newline="", encoding="utf-8") as handle:
            return {r["declaration_id"]: r["event_date"] for r in csv.DictReader(handle)
                    if r.get("event_date")}

    def test_ids_are_unique_and_dates_are_iso_or_blank(self):
        rows = self.rows()
        ids = [row["declaration_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            if row["date_signed"]:
                self.assertRegex(row["date_signed"], r"^20\d\d-\d\d-\d\d$", row["declaration_id"])
            if row["eo_number"]:
                self.assertTrue(row["declaration_id"].endswith(row["eo_number"]), row["declaration_id"])

    def test_dates_fall_in_each_governors_term(self):
        terms = {"Marc Racicot": ("2000", "2001-01"), "Judy Martz": ("2001-01", "2005-01"),
                 "Brian Schweitzer": ("2005-01", "2013-01"), "Steve Bullock": ("2013-01", "2021-01")}
        for row in self.rows():
            term = terms.get(row["governor"])
            if term and row["date_signed"]:
                self.assertTrue(term[0] <= row["date_signed"] < term[1], row["declaration_id"])

    def test_undated_rows_say_so_and_carry_an_event_date(self):
        event_dates = self.event_dates()
        undated = [row for row in self.rows() if not row["date_signed"]]
        self.assertEqual({row["declaration_id"] for row in undated},
                         {"MT-EO-31-00", "MT-EO-16-01", "MT-EO-13-02", "MT-EO-5-2019"})
        for row in undated:
            self.assertRegex(row["event_description"], r"signing day (?:is )?blank", row["declaration_id"])
            self.assertRegex(event_dates.get(row["declaration_id"], ""), r"^20\d\d-\d\d-\d\d$",
                             row["declaration_id"])

    def test_dates_read_from_the_sources(self):
        by_id = {r["declaration_id"]: r["date_signed"] for r in self.rows()}
        expected = {
            "MT-EO-18-00": "2000-07-28", "MT-EO-20-00": "2000-08-16", "MT-EO-24-00": "2000-08-25",
            "MT-EO-9-01": "2001-05-18", "MT-EO-13-2007": "2007-06-26", "MT-EO-9-2012": "2012-08-29",
            "MT-EO-11-2012": "2012-09-17", "MT-EO-4-2013": "2013-06-05", "MT-EO-8-2013": "2013-08-19",
            "MT-EO-3-2014": "2014-03-10", "MT-EO-7-2015": "2015-07-08", "MT-EO-5-2018": "2018-02-26",
            "MT-EO-11-2018": "2018-04-18", "MT-EO-12-2018": "2018-05-02", "MT-EO-15-2019": "2019-09-29",
        }
        for key, day in expected.items():
            self.assertEqual(by_id.get(key), day, key)
        event_dates = self.event_dates()
        self.assertEqual(event_dates["MT-EO-9-01"], "2001-04-02")
        self.assertEqual(event_dates["MT-EO-5-2019"], "2019-03-20")

    def test_schweitzer_rows_link_the_order_itself(self):
        for row in self.rows():
            if row["governor"] == "Brian Schweitzer":
                self.assertRegex(row["archive_record_url"],
                                 r"^https://formergovernors\.mt\.gov/schweitzer/eo/EO-.+\.pdf$",
                                 row["declaration_id"])

if __name__ == "__main__":
    unittest.main()
