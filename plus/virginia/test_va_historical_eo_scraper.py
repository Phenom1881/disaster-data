"""Virginia's historical scraper reads each Library of Virginia title the same
way its weather declarations are worded, including "Due to Severe Weather".

Stdlib and pandas only.  Run:  python -m unittest test_va_historical_eo_scraper
"""
import csv
import os
import unittest

import va_historical_eo_scraper as va

HERE = os.path.dirname(os.path.abspath(__file__))


class SevereWeatherTests(unittest.TestCase):
    def test_a_severe_weather_declaration_is_weather(self):
        for title in (
            "Executive Order 81 (2021) Declaration of a State of Emergency Due to Severe Weather",
            "Executive Order 13 (2002) Declaration of a State of Emergency Due to Severe Weather Across the Commonwealth.",
            "Executive Order 101 (2009) Declaration of a State of Emergency for the Commonwealth of Virginia "
            "Due to a Severe Weather Event throughout the Commonwealth.",
        ):
            result = va.classify_action(title)
            self.assertEqual(result["action_type"], "declaration", title)
            self.assertTrue(result["weather_related"], title)
            self.assertIn("severe weather", result["weather_hazards"], title)

    def test_other_emergencies_are_still_not_weather(self):
        for title in (
            "Executive Order 66 (2017) Declaration of a State of Emergency for the Commonwealth of Virginia Due to Civil Unrest",
            "Executive Order 38 (2011) Declaration of a State of Emergency for the Commowealth of Virginia Due to a "
            "5.8 Magnitude Earthquake and Aftershocks Affecting Localities",
            "Executive Order 78 (2021) Declaration of a State of Emergency Due to the Shutdown of the Colonial Pipeline",
        ):
            self.assertFalse(va.classify_action(title)["weather_related"], title)

    def test_a_follow_on_order_is_not_a_new_declaration(self):
        result = va.classify_action(
            "Executive Order 82 (2021) Extending the State of Emergency Due to Severe Weather")
        self.assertEqual(result["action_type"], "modification_or_extension")

    def test_the_saved_join_file_has_the_severe_weather_declarations(self):
        with open(os.path.join(HERE, "declarations_for_join_2002_present.csv"), encoding="utf-8") as handle:
            ids = {row["declaration_id"] for row in csv.DictReader(handle)}
        for key in ("VA-WARNER-EO-13-2002", "VA-KAINE-EO-65-2008", "VA-KAINE-EO-101-2009",
                    "VA-NORTHAM-EO-4-2018", "VA-NORTHAM-EO-5-2018", "VA-NORTHAM-EO-7-2018",
                    "VA-NORTHAM-EO-81-2021"):
            self.assertIn(key, ids)


if __name__ == "__main__":
    unittest.main()
