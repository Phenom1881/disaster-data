import unittest

import pa_eo_scraper as pa


COVEO_CONFIG_FIXTURE = """
<atomic-search-interface id="search" search-hub="OA-Policy Search With out IT-Policy"></atomic-search-interface>
<script>initialize({accessToken: 'token-value', organizationId: 'organization-value'});</script>
"""

PEMA_FIXTURE = """
<div class="cmp-teaser">
  <div class="cmp-teaser__eyebrow">August 9, 2024</div>
  <div class="cmp-teaser__title"><h2>Tropical Storm Debby</h2></div>
  <div class="cmp-teaser__text"><p>Severe weather and flooding.</p></div>
  <div class="cmp-teaser__actions">
    <a href="/files/2024.8.9-debby.pdf">Proclamation</a>
    <a href="/files/2024.8.20-debby-amendment.pdf">Amendment</a>
  </div>
</div>
<div class="cmp-accordion__item">
  <button><span class="cmp-accordion__title">COVID-19 Amendments</span></button>
  <div class="cmp-accordion__panel">
    <p><b>2021 Amendments</b></p>
    <p><a href="/files/covid-may20.pdf">May 20</a></p>
    <p><a href="/files/covid-feb19.pdf">February 19</a></p>
  </div>
</div>
"""


class PennsylvaniaScraperTests(unittest.TestCase):
    def test_coveo_config_discovery(self):
        config = pa.discover_coveo_config(COVEO_CONFIG_FIXTURE)
        self.assertEqual(config["access_token"], "token-value")
        self.assertEqual(config["organization_id"], "organization-value")
        self.assertEqual(config["search_hub"], "OA-Policy Search With out IT-Policy")

    def test_unknown_oa_title_uses_filename_number(self):
        action = pa.parse_oa_result({
            "title": "Unknown", "uri": "https://example.test/1980_18.pdf",
            "raw": {"copapwptitle": "Unknown", "copapwpissueyear": "1980", "copapwpissuemonth": "June"},
        })
        self.assertIsNotNone(action)
        self.assertEqual(action.action_number, "1980-18")
        self.assertEqual(action.stable_id, "PA-EO-1980-18")
        self.assertEqual(action.title, "Executive Order 1980-18")
        self.assertIsNone(action.date_issued)

    def test_teaser_and_amendment_relationship(self):
        actions = pa.parse_pema_page(PEMA_FIXTURE)
        debby = [action for action in actions if action.title.startswith("Tropical")]
        self.assertEqual(len(debby), 2)
        base, amendment = debby
        self.assertEqual(base.date_issued, "2024-08-09")
        self.assertEqual(amendment.date_issued, "2024-08-20")
        self.assertEqual(amendment.parent_id, base.stable_id)
        relation = pa.extract_relationships(amendment)[0]
        self.assertEqual(relation["relationship_type"], "amends")
        self.assertEqual(relation["target_order_id"], base.stable_id)

    def test_accordion_year_context(self):
        actions = pa.parse_pema_page(PEMA_FIXTURE)
        covid = [action for action in actions if action.title.startswith("COVID")]
        self.assertEqual([a.date_issued for a in covid], ["2021-05-20", "2021-02-19"])
        self.assertTrue(all(a.action_type == "amendment" for a in covid))

    def test_accordion_parent_resolves_when_base_is_present(self):
        fixture = PEMA_FIXTURE + """
        <div class="cmp-teaser">
          <div class="cmp-teaser__eyebrow">March 6, 2020</div>
          <div class="cmp-teaser__title"><h2>COVID-19</h2></div>
          <div class="cmp-teaser__actions"><a href="/files/covid-base.pdf">Proclamation</a></div>
        </div>
        """
        actions = pa.parse_pema_page(fixture)
        base = next(a for a in actions if a.title == "COVID-19")
        amendments = [a for a in actions if a.title == "COVID-19 Amendment"]
        self.assertTrue(amendments)
        self.assertTrue(all(a.parent_id == base.stable_id for a in amendments))

    def test_weather_requires_hazard(self):
        action = pa.PAAction(
            action_kind="emergency_proclamation", title="Disaster Emergency",
            description="A public-health emergency", date_issued="2020-03-06",
            document_url="x", source_page_url="x", source_scope="test",
        )
        self.assertFalse(pa.is_weather_related(action))
        action.description = "A disaster caused by a severe winter storm"
        self.assertTrue(pa.is_weather_related(action))

    def test_date_from_url_and_governor(self):
        self.assertEqual(pa.date_from_url("https://x/2024.8.20-debby.pdf"), "2024-08-20")
        self.assertEqual(pa.governor_for_date("2024-08-20"), "Josh Shapiro")
        self.assertEqual(pa.governor_for_date("2021-02-01"), "Tom Wolf")

    def test_relationship_dedup(self):
        row = {
            "source_order_id": "PA-EO-2024-2", "target_order_id": "PA-EO-2018-1",
            "relationship_type": "terminates", "relationship_text": "x",
            "relationship_source": "document_text", "confidence": "medium",
        }
        self.assertEqual(len(pa.dedupe_relationships([row, dict(row)])), 1)


if __name__ == "__main__":
    unittest.main()
