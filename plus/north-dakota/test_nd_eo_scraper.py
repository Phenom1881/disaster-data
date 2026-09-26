"""
Unit tests for nd_eo_scraper.py against markdown-style fixtures matching the
real rendered text of governor.nd.gov's archive and current EO pages.
"""
import csv
import os
import tempfile
import unittest

import nd_eo_scraper as scraper

ARCHIVE_FIXTURE = """
## **2023**

- **2023-04** - April 10, 2023 - Burgum Declares Statewide Emergency for Spring Flooding
- **2023-03** - March 21, 2023 - Burgum Declares Winter Storm Disaster for January Fog and Ice Event
- **2023-07** - June 13, 2023 - Burgum Declares an Emergency and Authorizes the North Dakota National Guard to Help Texas Secure the U.S.-Mexico Border

## **2020**

- **2020-34** - May 30, 2020 - Burgum Declares State of Emergency in Fargo, West Fargo and Cass County, Activates North Dakota National Guard
- **2020-30** - April 24, 2020 - Burgum Declares Statewide Flood Emergency for Spring Flooding
"""

CURRENT_FIXTURE = """
## **2026**

- **2026-03** - [Armstrong Declares Statewide Disaster for Damage from Severe Storms](https://www.governor.nd.gov/sites/default/files/documents/Executive%20Order%202026-03.pdf)
- **2026-01** - [Armstrong Directs State Resources to Be Ready for America 250](https://www.governor.nd.gov/sites/default/files/documents/Executive%20Order%202026-01.pdf)
"""


# The same entries as served: raw HTML, which is what the scraper actually
# receives. Before Sep 2026 the patterns only matched the markdown form above,
# so every run from GitHub found 0 orders.
CURRENT_HTML = """<html><body><main><div class="field--name-body">
<h2><strong>2026</strong></h2>
<ul>
<li><strong>2026-07.1</strong> - <a href="/sites/default/files/documents/Executive%20Order%202026-07.1%20drought.pdf">Armstrong Expands Drought Relief Program to All Counties</a></li>
<li><strong>2026-07</strong> - <a href="/sites/default/files/documents/Executive%20Order%202026-07%20drought%20disaster%20declaration.pdf">Armstrong Declares Drought Disaster</a></li>
<li><strong>2026-06</strong> &ndash; <a href="/sites/default/files/documents/Executive%20Order%202026-06%20rescinding%20TikTok%20ban.pdf">Armstrong Rescinds Ban on TikTok on State-owned Devices</a></li>
<li><strong>2026-05</strong> - <a href="/sites/default/files/documents/Executive%20Order%202026-05%20statewide%20fire%20emergency.pdf">Armstrong Declares Statewide Fire Emergency</a></li>
</ul>
<h2><strong>2024</strong></h2>
<ul>
<li><strong>2024-02</strong> - <a href="https://www.governor.nd.gov/sites/www/files/documents/Executive%20Order%202024-02.pdf">Burgum Declares Emergency for Burleigh and Morton Counties Amid Threat of Ice Jam Flooding</a></li>
</ul>
</div></main></body></html>"""

ARCHIVE_HTML = """<html><body><main>
<h2><strong>2023</strong></h2>
<ul>
<li><strong>2023-04</strong> - April 10, 2023 - Burgum Declares Statewide Emergency for Spring Flooding</li>
<li><strong>2023-07</strong> - June 13, 2023 - Burgum Declares an Emergency and Authorizes the North Dakota National Guard to Help Texas Secure the U.S.-Mexico Border</li>
</ul>
<p>June 1, 2015 - Dalrymple Declares Flood Emergency</p>
</main></body></html>"""


class RawHtmlTests(unittest.TestCase):
    def test_current_page_html(self):
        orders = scraper.parse_current_markdown(CURRENT_HTML)
        self.assertEqual([o["eo_number"] for o in orders], ["2026-07.1", "2026-07", "2026-06", "2026-05", "2024-02"])
        by = {o["eo_number"]: o for o in orders}
        self.assertEqual(by["2026-07"]["title"], "Declares Drought Disaster")
        self.assertEqual(by["2026-07"]["governor"], "Armstrong")
        self.assertEqual(by["2024-02"]["governor"], "Burgum")
        self.assertEqual(by["2026-07"]["url"],
                         "https://www.governor.nd.gov/sites/default/files/documents/"
                         "Executive%20Order%202026-07%20drought%20disaster%20declaration.pdf")

    def test_archive_page_html(self):
        orders = scraper.parse_archive_markdown(ARCHIVE_HTML)
        self.assertEqual([o["eo_number"] for o in orders], ["2023-04", "2023-07"])   # unnumbered 2015 line skipped
        self.assertEqual(orders[0]["title"], "Declares Statewide Emergency for Spring Flooding")
        self.assertEqual(orders[0]["date_text"], "April 10, 2023")

    def test_undated_archive_entry_uses_confirmed_date(self):
        html = ARCHIVE_HTML.replace(
            "<ul>\n<li><strong>2023-04</strong>",
            "<ul>\n<li><strong>2023-10</strong> - Burgum Declares Statewide Emergency for Impacts of Ice Storm</li>\n"
            "<li><strong>2023-04</strong>")
        orders = scraper.parse_archive_markdown(html)
        by = {o["eo_number"]: o for o in orders}
        self.assertIsNone(by["2023-10"]["date_text"])
        self.assertEqual(by["2023-10"]["title"], "Declares Statewide Emergency for Impacts of Ice Storm")
        with tempfile.TemporaryDirectory() as tmp:
            decls = scraper.write_csv(orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                                      os.path.join(tmp, "j.csv"), confirmed_dates=scraper.CONFIRMED_DATES)
        self.assertIn({"id": "ND-EO-2023-10", "date": "2023-12-29"},
                      [{"id": d["declaration_id"], "date": d["date_signed"]} for d in decls])

    def test_every_current_page_declaration_has_a_confirmed_date(self):
        orders = scraper.parse_current_markdown(CURRENT_HTML)
        with tempfile.TemporaryDirectory() as tmp:
            decls = scraper.write_csv(orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                                      os.path.join(tmp, "j.csv"), confirmed_dates=scraper.CONFIRMED_DATES)
        self.assertEqual({d["declaration_id"]: d["date_signed"] for d in decls},
                         {"ND-EO-2026-07": "2026-08-18", "ND-EO-2026-05": "2026-08-07", "ND-EO-2024-02": "2024-02-29"})

    def test_expansion_order_is_not_a_second_declaration(self):
        self.assertFalse(scraper.is_declaration("2026-07.1", "Expands Drought Relief Program to All Counties"))
        self.assertTrue(scraper.is_declaration("2026-07", "Declares Drought Disaster"))
        self.assertTrue(scraper.is_declaration("2026-05", "Declares Statewide Fire Emergency"))

    def test_pdf_dates_feed_the_join(self):
        orders = scraper.parse_current_markdown(CURRENT_HTML)
        for o in orders:
            o["pdf_date"] = {"2026-07": "2026-08-04", "2026-05": "2026-04-17"}.get(o["eo_number"], "")
        with tempfile.TemporaryDirectory() as tmp:
            decls = scraper.write_csv(orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                                      os.path.join(tmp, "j.csv"))
        self.assertEqual({d["declaration_id"]: d["date_signed"] for d in decls},
                         {"ND-EO-2026-07": "2026-08-04", "ND-EO-2026-05": "2026-04-17"})   # 2024-02 has no date yet


class SignedDateTests(unittest.TestCase):
    def test_signature_clause(self):
        text = ("WHEREAS, on June 20, 2025, severe storms struck Enderlin ... "
                "Executed at the State Capitol in Bismarck, North Dakota, this 21st day of June, 2025.")
        self.assertEqual(scraper.signed_date_from_text(text, "2025-05"), "2025-06-21")

    def test_executed_on_date(self):
        text = "WHEREAS drought began May 1, 2026 ... Executed on August 4, 2026."
        self.assertEqual(scraper.signed_date_from_text(text, "2026-07"), "2026-08-04")

    def test_event_dates_alone_are_not_a_signing_date(self):
        self.assertEqual(scraper.signed_date_from_text("WHEREAS, on June 20, 2025, storms struck.", "2025-05"), "")

    def test_other_things_issued_on_a_date_are_not_the_signing_date(self):
        text = "WHEREAS, the National Weather Service issued a Red Flag Warning on August 4, 2026 ..."
        self.assertEqual(scraper.signed_date_from_text(text, "2026-05"), "")
        self.assertEqual(scraper.signed_date_from_text("WHEREAS on the 3rd day of August, 2026 fires began", "2026-05"), "")

    def test_order_on_both_pages_is_written_once(self):
        archive = scraper.parse_archive_markdown(
            "<ul><li><strong>2024-02</strong> - Burgum Declares Emergency for Burleigh and Morton Counties Amid "
            "Threat of Ice Jam Flooding</li></ul>")
        current = scraper.parse_current_markdown(CURRENT_HTML)
        with tempfile.TemporaryDirectory() as tmp:
            decls = scraper.write_csv(archive + current, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"),
                                      os.path.join(tmp, "j.csv"), confirmed_dates=scraper.CONFIRMED_DATES)
        rows = [d for d in decls if d["declaration_id"] == "ND-EO-2024-02"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["archive_record_url"].endswith(".pdf"))

    def test_this_the_nth_day_of(self):
        self.assertEqual(scraper.signed_date_from_text("Executed this the 18th day of August, 2026.", "2026-07"), "2026-08-18")

    def test_year_must_match_the_order_number(self):
        self.assertEqual(scraper.signed_date_from_text("this 3rd day of January, 2024", "2023-09"), "")


class ArchiveParsingTests(unittest.TestCase):
    def test_parses_numbered_dated_entries(self):
        orders = scraper.parse_archive_markdown(ARCHIVE_FIXTURE)
        self.assertEqual(len(orders), 5)
        first = orders[0]
        self.assertEqual(first["eo_number"], "2023-04")
        self.assertEqual(first["date_text"], "April 10, 2023")

    def test_date_conversion(self):
        self.assertEqual(scraper.parse_date_text("April 10, 2023"), "2023-04-10")


class CurrentPageParsingTests(unittest.TestCase):
    def test_parses_linked_entries(self):
        orders = scraper.parse_current_markdown(CURRENT_FIXTURE)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0]["eo_number"], "2026-03")
        self.assertTrue(orders[0]["url"].endswith(".pdf"))
        self.assertIsNone(orders[0]["date_text"])


class ClassificationTests(unittest.TestCase):
    def test_flood_emergency_is_declaration(self):
        self.assertTrue(scraper.is_declaration("2023-04", "Declares Statewide Emergency for Spring Flooding"))

    def test_civil_disturbance_excluded_despite_emergency_wording(self):
        # Regression: this is the exact case Claude's own verification pass
        # caught during research - a "state of emergency" title that is
        # actually a civil-disturbance order (May 2020 Fargo protests), not
        # weather. It must never reach declarations_for_join.csv.
        self.assertFalse(scraper.is_declaration(
            "2020-34",
            "Burgum Declares State of Emergency in Fargo, West Fargo and Cass County, "
            "Activates North Dakota National Guard",
        ))

    def test_texas_border_deployment_excluded(self):
        self.assertFalse(scraper.is_declaration(
            "2023-07",
            "Burgum Declares an Emergency and Authorizes the North Dakota National Guard "
            "to Help Texas Secure the U.S.-Mexico Border",
        ))

    def test_governor_lookup(self):
        self.assertEqual(scraper.governor_for("2020-30"), "Burgum")
        self.assertEqual(scraper.governor_for("2026-03"), "Armstrong")
        self.assertEqual(scraper.governor_for("2011-05"), "Dalrymple")


class WriteCsvTests(unittest.TestCase):
    def test_undated_current_page_entry_needs_confirmed_date(self):
        orders = scraper.parse_current_markdown(CURRENT_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            actions_out = os.path.join(tmp, "a.csv")
            rel_out = os.path.join(tmp, "r.csv")
            join_out = os.path.join(tmp, "j.csv")

            # Without a confirmed date, the storm EO must be dropped from
            # the join CSV rather than guessed.
            declarations = scraper.write_csv(orders, actions_out, rel_out, join_out)
            self.assertEqual(len(declarations), 0)

            # With a confirmed date supplied, it is included.
            declarations = scraper.write_csv(
                orders, actions_out, rel_out, join_out,
                confirmed_dates={"2026-03": "2026-06-30"},
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("ND-EO-2026-03", ids)

    def test_archive_entries_with_parsed_dates_included(self):
        orders = scraper.parse_archive_markdown(ARCHIVE_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "j.csv")
            declarations = scraper.write_csv(
                orders,
                os.path.join(tmp, "a.csv"),
                os.path.join(tmp, "r.csv"),
                join_out,
            )
            ids = {d["declaration_id"] for d in declarations}
            self.assertIn("ND-EO-2023-04", ids)
            self.assertIn("ND-EO-2023-03", ids)
            self.assertIn("ND-EO-2020-30", ids)
            self.assertNotIn("ND-EO-2020-34", ids)
            self.assertNotIn("ND-EO-2023-07", ids)

            with open(join_out, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
