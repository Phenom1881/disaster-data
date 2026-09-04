import unittest

import ny_eo_scraper as ny


CURRENT_FIXTURE = """
<article class="node node--type-executive-order">
  <h3 class="content-title"><a href="/executive-order/no-561-test">No. 56.1: Modifying a Disaster Emergency</a></h3>
  <div class="content-dates"><span>Jan 20, 2026</span><span>| 1:00 PM EST</span></div>
  <div class="content-description">Modifying the declaration in Executive Order Number 56.</div>
  <div class="content-document"><a href="/files/eo_56.1.pdf">Download Executive Order</a></div>
</article>
"""

PAST_FIXTURE = """
<div class="t-section__wrapper">
  <h2 class="t-section__title">Governor Andrew M Cuomo</h2>
  <div class="t-section__content">
    <a href="/files/eo198.pdf">Executive Order No. 198, issued November 20, 2019 (Declaring a Flood Disaster)</a>
  </div>
</div>
"""


class NewYorkScraperTests(unittest.TestCase):
    def test_current_decimal_record(self):
        order = ny.parse_current_page(CURRENT_FIXTURE, ny.CURRENT_URL)[0]
        self.assertEqual(order.order_number, "56.1")
        self.assertEqual(order.date_issued, "2026-01-20")
        self.assertEqual(order.document_url, "https://www.governor.ny.gov/files/eo_56.1.pdf")
        self.assertEqual(ny.classify_action(order), "amendment")

    def test_selected_prior_scope(self):
        order = ny.parse_selected_prior(PAST_FIXTURE)[0]
        self.assertEqual(order.governor, "Andrew M Cuomo")
        self.assertEqual(order.order_number, "198")
        self.assertEqual(order.date_issued, "2019-11-20")
        self.assertEqual(order.source_scope, "selected_prior")

    def test_decimal_parent_relationship(self):
        order = ny.parse_current_page(CURRENT_FIXTURE, ny.CURRENT_URL)[0]
        order.action_type = ny.classify_action(order)
        relationships = ny.extract_relationships(order)
        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0]["target_order_id"], "NY-KATHYHOCHUL-EO-56")
        self.assertEqual(relationships[0]["relationship_type"], "amends")

    def test_weather_requires_hazard(self):
        order = ny.NYOrder(
            governor="Kathy Hochul", order_number="1", title="Disaster Emergency",
            description="A public-health emergency", date_issued="2021-08-24",
            detail_url="", document_url="", document_format="html",
            source_scope="current_complete",
        )
        self.assertFalse(ny.is_weather_related(order))
        order.description = "A disaster emergency caused by a severe winter storm"
        self.assertTrue(ny.is_weather_related(order))

    def test_relationship_dedup(self):
        row = {
            "source_order_id": "NY-A-EO-2.1", "target_order_id": "NY-A-EO-2",
            "relationship_type": "extends_duration", "relationship_text": "x",
            "relationship_source": "metadata", "confidence": "medium",
        }
        self.assertEqual(len(ny.dedupe_relationships([row, dict(row)])), 1)


if __name__ == "__main__":
    unittest.main()
