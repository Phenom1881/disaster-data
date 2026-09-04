import unittest

import nc_eo_scraper as nc


ARCHIVE_FIXTURE = """
<main>
<table><tbody>
<tr><td><a href="/executive-order-22">Executive Order No. 22 Notice of Termination of Executive Order No. 20</a></td><td>August 25, 2025</td></tr>
<tr><td><a href="/eo20-concurrence">Gov. Stein Executive Order 20 COS Concurrence</a></td><td>August 19, 2025</td></tr>
<tr><td><a href="/executive-order-20">Executive Order No. 20: Declaration of a State of Emergency</a></td><td>August 19, 2025</td></tr>
<tr><td><a href="/eo20-spanish">Executive Order No. 20 Spanish</a></td><td>August 19, 2025</td></tr>
</tbody></table>
<nav><a rel="next" href="?page=1">Next</a></nav>
</main>
"""

DETAIL_FIXTURE = """
<main>
<h1>Executive Order No. 22 Notice of Termination of Executive Order No. 20</h1>
<a href="/executive-order-22/open">EO22_TerminationEO20.pdf</a>
<div>August 25, 2025 Executive Order No. 22 Notice of Termination of Executive Order No. 20.
Whereas Hurricane Erin impacted North Carolina. Executive Order No. 20 is hereby terminated.</div>
<div>Document Entity Terms Executive Order First Published August 25, 2025 Last Updated August 25, 2025</div>
</main>
"""


class NorthCarolinaScraperTests(unittest.TestCase):
    def test_archive_rows_and_dates(self):
        entries = nc.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0].order_number, "22")
        self.assertEqual(entries[0].date_issued, "2025-08-25")
        self.assertTrue(entries[1].supporting)
        self.assertTrue(nc._has_next_page(ARCHIVE_FIXTURE))

    def test_canonicalization_keeps_supporting_urls(self):
        orders = nc.canonicalize_entries(nc.parse_archive_page(ARCHIVE_FIXTURE))
        twenty = next(order for order in orders if order.order_number == "20")
        self.assertEqual(twenty.governor, "Josh Stein")
        self.assertEqual(twenty.detail_url, "https://governor.nc.gov/executive-order-20")
        self.assertEqual(len(twenty.supporting_urls), 2)
        self.assertEqual(twenty.stable_id, "NC-JOSHSTEIN-EO-20")

    def test_classification_and_weather(self):
        declaration = nc.NCOrder(
            governor="Josh Stein", order_number="20",
            title="Declaration of a State of Emergency",
            description="Anticipated impacts from Hurricane Erin",
            date_issued="2025-08-19", detail_url="x",
        )
        self.assertEqual(nc.classify_action(declaration), "declaration")
        self.assertTrue(nc.is_weather_related(declaration))
        administrative = nc.NCOrder(
            governor="Roy Cooper", order_number="242",
            title="Extending the State Emergency Response Commission",
            description="Commission membership", date_issued="2021-12-17",
            detail_url="x",
        )
        self.assertEqual(nc.classify_action(administrative), "extension")
        self.assertFalse(nc.is_weather_related(administrative))

    def test_multi_target_termination(self):
        one = nc.NCOrder("Roy Cooper", "1", "State of Emergency", "Winter storm", "2017-01-06", "one")
        two = nc.NCOrder("Roy Cooper", "2", "Transportation Waiver", "Winter storm", "2017-01-06", "two")
        three = nc.NCOrder("Roy Cooper", "3", "Notice of Termination of Executive Orders 1 and 2", "", "2017-01-10", "three")
        for order in (one, two, three):
            order.action_type = nc.classify_action(order)
        relationships = nc.build_relationships([one, two, three])
        self.assertEqual({row["target_order_id"] for row in relationships}, {one.stable_id, two.stable_id})
        self.assertTrue(all(row["relationship_type"] == "terminates" for row in relationships))

    def test_single_target_termination_and_end_date(self):
        base = nc.NCOrder("Josh Stein", "20", "Declaration of a State of Emergency", "Hurricane Erin", "2025-08-19", "base")
        end = nc.NCOrder("Josh Stein", "22", "Notice of Termination of Executive Order No. 20", "", "2025-08-25", "end")
        base.action_type = nc.classify_action(base)
        end.action_type = nc.classify_action(end)
        relationships = nc.build_relationships([base, end])
        self.assertEqual(len(relationships), 1)
        nc.apply_end_dates([base, end], relationships)
        self.assertEqual(base.end_date, "2025-08-25")

    def test_first_published_date(self):
        self.assertEqual(nc._first_published("First Published October 10, 2018 Last Updated"), "2018-10-10")

    def test_document_filename_can_supply_hazard(self):
        order = nc.NCOrder(
            "Roy Cooper", "74", "Declaration of a State of Emergency", "",
            "2018-10-10", "detail", document_label="EO74 Hurricane Michael.pdf",
        )
        self.assertTrue(nc.is_weather_related(order))

    def test_low_yield_threshold(self):
        self.assertEqual(nc.LOW_YIELD_PDF_CHARS, 250)


if __name__ == "__main__":
    unittest.main()
