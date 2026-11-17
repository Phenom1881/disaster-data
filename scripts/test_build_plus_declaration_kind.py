"""Lesser declarations count for matching but are labeled on the page.

Maryland's and West Virginia's "State of Preparedness" orders, energy and
heating fuel emergencies, Missouri's drought alerts and Tennessee's EOC Level
3 activations are matched with FEMA and NOAA like any declaration (ruling of
2026-11-17), but a reader should not take them for a governor's state of
emergency, so the page and the API mark them.

Run:  python -m unittest test_build_plus_declaration_kind
"""
import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build-plus.py")
SPEC = importlib.util.spec_from_file_location("build_plus_kind_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DeclarationKindTests(unittest.TestCase):
    def kind(self, title):
        return MODULE.declaration_kind(title)

    def test_preparedness(self):
        self.assertEqual(self.kind("Declaration of a State of Preparedness - Winter Storm (EO# 01.01.2026.04)"), "preparedness")
        self.assertEqual(self.kind("Governor Morrisey Declares State of Preparedness in All 55 counties Ahead of Winter Storm"), "preparedness")

    def test_energy_emergency_alone_is_labeled(self):
        self.assertEqual(self.kind("Statewide cold-weather heating fuel emergency"), "energy")
        self.assertEqual(self.kind("Winter Energy Emergency"), "energy")
        self.assertEqual(self.kind("Declares a limited state of energy emergency with regard to the supply of motor fuel"), "energy")

    def test_energy_emergency_with_a_state_of_emergency_is_an_emergency(self):
        self.assertEqual(self.kind("Proclamation of State of Civil Emergency and Energy Emergency for a winter storm"), "emergency")
        self.assertEqual(self.kind("Executive Order 2026-2: Declaration of State of Emergency and Energy Emergency"), "emergency")

    def test_drought_alert_and_level_3_activation(self):
        self.assertEqual(self.kind("Gov. Michael Parson declares a drought alert for 53 Missouri counties"), "drought_alert")
        self.assertEqual(self.kind("State of emergency for winter weather: the State Emergency Operations Center "
                                   "activated to Level 3, State of Emergency (TEMA Flash Report)"), "activation")

    def test_ordinary_and_limited_states_of_emergency_are_not_labeled(self):
        for title in ("Declaring a State of Emergency due to Severe Winter Storm",
                      "Limited State of Emergency in Sussex County for high winds and coastal flooding",
                      "Statewide civil preparedness emergency for Tropical Storm Henri", ""):
            self.assertEqual(self.kind(title), "emergency", title)

    def test_rows_carry_the_kind_and_the_page_shows_the_label(self):
        action = MODULE.normalized_action({"declaration_id": "MD-EO-1", "event_description":
                                           "Declaration of a State of Preparedness - Severe Weather",
                                           "date_signed": "2026-03-15"}, "MD")
        self.assertEqual(action["declaration_kind"], "preparedness")
        action["origin"] = MODULE.ORIGIN_STATE
        self.assertIn('<span class="kind-tag">State of preparedness</span>', MODULE.action_rows([action]))
        self.assertIn("1 labeled record.", MODULE.kind_note([action]))
        plain = MODULE.normalized_action({"declaration_id": "MD-EO-2", "event_description": "State of Emergency",
                                          "date_signed": "2026-03-16"}, "MD")
        plain["origin"] = MODULE.ORIGIN_STATE
        self.assertNotIn("kind-tag", MODULE.action_rows([plain]))
        self.assertEqual(MODULE.kind_note([plain]), "")


if __name__ == "__main__":
    unittest.main()
