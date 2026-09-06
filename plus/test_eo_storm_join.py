import unittest

import eo_storm_join as m


class CompatibleEventTypesTests(unittest.TestCase):
    """Regression coverage for compatible_event_types()'s storm_general
    fallback. storm_general must only ever fire when NO more specific
    hazard keyword matched - unioning it alongside a specific category
    (winter, tropical, flood, severe_storm, wind, fire, drought) silently
    reintroduces a "match nearly everything" failure, just through a
    different path than the original empty-keyword-set bug this module
    was built to fix. Confirmed in production: PA's "A complex winter
    storm system... heavy snow and strong winds" matched an NCEI Flood
    record in Armstrong County during the 2026-09-05 five-state retest,
    purely because the word "storm" co-occurs with "winter" in the same
    description.
    """

    def test_winter_storm_does_not_leak_flood_or_tornado(self):
        # The exact real-world case that surfaced this bug.
        desc = (
            "A complex winter storm system is expected to impact multiple "
            "counties with dangerous weather, including heavy snow and "
            "strong winds."
        )
        result = m.compatible_event_types(desc)
        self.assertNotIn("Flood", result)
        self.assertNotIn("Tornado", result)
        self.assertNotIn("Coastal Flood", result)
        self.assertIn("Winter Storm", result)

    def test_specific_categories_never_pick_up_storm_general_only_types(self):
        # storm_general's own set includes Blizzard/Winter Storm/Winter
        # Weather/Ice Storm - types no single one of these descriptions
        # should ever pull in, since none of them mention winter weather.
        cases = {
            "Declares a state of emergency due to tropical storm conditions": {"tropical"},
            "Declares a State of Emergency due to a severe storm with damaging winds": {
                "severe_storm",
                "wind",
            },
            "State of Emergency due to storms with flash flooding across the region": {"flood"},
        }
        for description, expected_categories in cases.items():
            with self.subTest(description=description):
                result = m.compatible_event_types(description)
                expected = set()
                for category in expected_categories:
                    expected |= m.HAZARD_EVENT_TYPES[category]
                self.assertEqual(result, expected)

    def test_generic_storm_language_still_falls_back_when_nothing_specific(self):
        # The whole point of storm_general: a description that is
        # genuinely generic (no recognizable specific hazard word) must
        # still resolve to something, not go ambiguous unnecessarily.
        cases = [
            "State of Emergency: Storm-Related Conditions",
            "Executive Order Declaring a Nor'easter Emergency",
            "State of Emergency due to Storm",
            "State of Emergency: Weather Related",
            "State of Emergency: weather conditions",
        ]
        for description in cases:
            with self.subTest(description=description):
                self.assertEqual(
                    m.compatible_event_types(description),
                    m.HAZARD_EVENT_TYPES["storm_general"],
                )

    def test_non_weather_descriptions_stay_ambiguous(self):
        for description in [
            "Declaration of a State of Emergency",
            "Statewide Vaccination Emergency Order",
        ]:
            with self.subTest(description=description):
                self.assertEqual(m.compatible_event_types(description), set())

    def test_multi_hazard_descriptions_still_union_correctly(self):
        # Two genuinely-present specific categories must still combine -
        # the fix only changes storm_general's behavior, not the ordinary
        # union of specific categories with each other.
        description = (
            "Hurricane Ida after-effects bring heavy rains and a serious "
            "threat of flash and riverine flooding"
        )
        result = m.compatible_event_types(description)
        expected = m.HAZARD_EVENT_TYPES["tropical"] | m.HAZARD_EVENT_TYPES["flood"]
        self.assertEqual(result, expected)

    def test_water_emergency_still_not_auto_classified(self):
        # Separate prior fix: "water emergency" alone must stay ambiguous
        # by default (McGreevey drought vs. Christie/Sandy are different
        # hazards a keyword can't safely distinguish) - confirm the
        # storm_general fix didn't accidentally revert this.
        self.assertEqual(
            m.compatible_event_types("Declaration of Water Emergency"), set()
        )


if __name__ == "__main__":
    unittest.main()
