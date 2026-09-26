"""Tests for the shared eo_storm_join.py (reference copy: plus/virginia):
the hazard words added in the 2026-09-26 review and the optional event_date
column in hazard_overrides.csv.

    cd scripts && python -m unittest test_storm_join_review
"""
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("eo_storm_join", str(ROOT / "plus" / "virginia" / "eo_storm_join.py"))
join = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("eo_storm_join", join)
_SPEC.loader.exec_module(join)


class HazardWordTests(unittest.TestCase):
    def types(self, text):
        return join.compatible_event_types(text)

    def test_named_tropical_systems(self):
        self.assertIn("Tropical Storm", self.types('"Superstorm" Sandy'))
        self.assertIn("Tropical Storm", self.types("Potential Tropical Cyclone Nine"))

    def test_kansas_fire_titles(self):
        self.assertIn("Wildfire", self.types("Wildland Fire (April 14 - April 19 (Wildland Fire))"))
        self.assertIn("Wildfire", self.types("Red Flag Warning (March 20 - March 31 (Red Flag Warning))"))

    def test_heat_wave(self):
        self.assertEqual(self.types("Emergency Relief for Power Providers Due to Heat Wave"),
                         {"Heat", "Excessive Heat"})

    def test_non_weather_titles_still_match_nothing(self):
        for title in ("Fuel Shortage (April 30 - May 13 (Fuel Shortage))",
                      "Coronavirus - Emergency Unemployment Insurance Benefit Relief",
                      "Waiving Certain Requirements for Commercial Motor Carrier Vehicles"):
            self.assertEqual(self.types(title), set(), title)


class EventDateOverrideTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        handle.write(text)
        handle.close()
        return handle.name

    def test_event_date_is_loaded_and_applied(self):
        import pandas as pd
        path = self.write("declaration_id,hazard_category_override,review_note,source_url,event_date\n"
                          "NC-EO-174,flood,late signing,,2020-05-18\n")
        overrides = join.load_overrides(path)
        declarations = pd.DataFrame([{"declaration_id": "NC-EO-174", "event_description": "",
                                      "date_signed": "2020-10-30"}])
        merged = join.apply_overrides(declarations, overrides)
        self.assertEqual(merged.loc[0, "override_event_date"], "2020-05-18")

    def test_bad_event_date_stops_the_run(self):
        path = self.write("declaration_id,hazard_category_override,event_date\nX-1,flood,May 18\n")
        with self.assertRaises(ValueError):
            join.load_overrides(path)

    def test_files_without_event_date_still_load(self):
        path = self.write("declaration_id,hazard_category_override,review_note,source_url\nX-1,flood,,\n")
        self.assertEqual(len(join.load_overrides(path)), 1)


class CopiesMatchReferenceTests(unittest.TestCase):
    def test_every_state_runs_the_reference_join(self):
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        reference = digest(ROOT / "plus" / "virginia" / "eo_storm_join.py")
        stale = [p.parent.name for p in (ROOT / "plus").glob("*/eo_storm_join.py") if digest(p) != reference]
        self.assertEqual(stale, [], "copy plus/virginia/eo_storm_join.py to these states")


if __name__ == "__main__":
    unittest.main()
