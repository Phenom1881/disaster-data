import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build-plus.py")
SPEC = importlib.util.spec_from_file_location("build_plus_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WeatherPageTests(unittest.TestCase):
    def test_page_leads_with_weather_and_collapses_large_evidence_tables(self):
        state = {
            "name": "New Jersey",
            "slug": "new-jersey",
            "official_source_url": "https://example.test/archive",
        }
        actions = [{
            "declaration_id": "NJ-TEST-EO-1",
            "action_number": "1",
            "title": "Winter storm emergency",
            "date_signed": "2026-01-01",
            "action_type": "declaration",
            "governor": "Test Governor",
            "source_url": "https://example.test/1",
        }]
        federal = [{
            "date": "2026-01-02", "number": "EM-9999", "type": "EM",
            "title": "Winter Storm", "incidentType": "Severe Storm",
            "begin": "2026-01-01", "end": "2026-01-03",
        }]
        metrics = {
            "action_count": 1,
            "federal_declaration_count": 1,
            "storm_match_rows": 0,
            "severity_rows": 0,
        }
        crosswalk = MODULE.build_crosswalk(actions, federal, {})
        page = MODULE.render_state_page(
            state, actions, federal, [], crosswalk, metrics, "Fixture coverage"
        )

        self.assertIn("Weather Emergency Declarations", page)
        self.assertIn('id="state-weather-table"', page)
        self.assertIn('<details class="layer">', page)
        self.assertIn("Federal FEMA declarations", page)
        self.assertIn('class="table-search"', page)
        self.assertIn('class="sort-button"', page)
        self.assertNotIn("loaded state-action records", page)


if __name__ == "__main__":
    unittest.main()
