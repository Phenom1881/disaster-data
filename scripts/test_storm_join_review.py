"""Tests for the shared eo_storm_join.py (reference copy: plus/virginia):
the hazard words added in the 2026-09-26 review and the optional event_date
column in hazard_overrides.csv.

    cd scripts && python -m unittest test_storm_join_review
"""
import hashlib
import importlib.util
import os
import shutil
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


class SharedStormFileTests(unittest.TestCase):
    """The per-run NOAA cache (PLUS_NCEI_CACHE_DIR) must return exactly what
    the uncached code returned, and download each yearly file only once."""

    def setUp(self):
        import pandas as pd
        self.pd = pd
        self.folder = tempfile.mkdtemp(prefix="ncei_cache_")
        self.national = pd.DataFrame({
            "STATE": ["VIRGINIA", "virginia", "NEW HAMPSHIRE", None, "TEXAS"],
            "EVENT_TYPE": ["Flood", "Hail", "Winter Storm", "Hail", "Tornado"],
            "BEGIN_DATE_TIME": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-01",
                                               "2020-03-01", "2020-04-01"]),
        })
        self.downloads = []
        self.original = (join.download_year_details, join._fetch_latest_filenames, dict(join._year_cache))
        join.download_year_details = lambda name: (self.downloads.append(name), self.national.copy())[1]
        join._year_cache.clear()

    def tearDown(self):
        join.download_year_details, join._fetch_latest_filenames, cache = self.original
        join._year_cache.clear()
        join._year_cache.update(cache)
        os.environ.pop(join.NCEI_CACHE_ENV, None)
        shutil.rmtree(self.folder, ignore_errors=True)

    def uncached(self, state):
        frame = self.national
        return frame[frame["STATE"].fillna("").str.upper() == state.upper()].copy()

    def test_each_yearly_file_is_downloaded_once_for_all_states(self):
        os.environ[join.NCEI_CACHE_ENV] = self.folder
        files = {"2020": "details_d2020_c20260323.csv.gz"}
        for state in ("VIRGINIA", "NEW HAMPSHIRE", "TEXAS", "OHIO"):
            join._year_cache.clear()          # each state runs in its own process
            got = join.get_year_events(2020, files, state)
            want = self.uncached(state)
            self.pd.testing.assert_frame_equal(got, want)
        self.assertEqual(self.downloads, ["details_d2020_c20260323.csv.gz"])

    def test_state_with_no_rows_gets_the_same_empty_frame(self):
        os.environ[join.NCEI_CACHE_ENV] = self.folder
        got = join.get_year_events(2020, {"2020": "f.csv.gz"}, "OHIO")
        self.assertTrue(got.empty)
        self.assertEqual(list(got.columns), list(self.national.columns))
        self.assertEqual(list(got.dtypes), list(self.national.dtypes))

    def test_a_revised_file_is_fetched_fresh(self):
        os.environ[join.NCEI_CACHE_ENV] = self.folder
        join.get_year_events(2020, {"2020": "d2020_c20260323.csv.gz"}, "TEXAS")
        join._year_cache.clear()
        join.get_year_events(2020, {"2020": "d2020_c20260918.csv.gz"}, "TEXAS")
        self.assertEqual(len(self.downloads), 2)

    def test_file_index_is_fetched_once_per_run(self):
        os.environ[join.NCEI_CACHE_ENV] = self.folder
        calls = []
        join._fetch_latest_filenames = lambda: (calls.append(1), {"2020": "f.csv.gz"})[1]
        self.assertEqual(join.get_latest_filenames_by_year(), {"2020": "f.csv.gz"})
        self.assertEqual(join.get_latest_filenames_by_year(), {"2020": "f.csv.gz"})
        self.assertEqual(len(calls), 1)

    def test_without_the_cache_folder_nothing_changes(self):
        files = {"2020": "f.csv.gz"}
        got = join.get_year_events(2020, files, "VIRGINIA")
        self.pd.testing.assert_frame_equal(got, self.uncached("VIRGINIA"))
        join._year_cache.clear()
        join.get_year_events(2020, files, "TEXAS")
        self.assertEqual(len(self.downloads), 2)
        self.assertEqual(os.listdir(self.folder), [])


if __name__ == "__main__":
    unittest.main()
