"""Virginia's current-governor scraper (va_eo_scraper.py) reads the Governor's
listing of executive actions. These tests use the titles and PDF links the
listing gives for Governor Spanberger's 2026 emergency orders: EO 11 (winter
weather), EO 21 (drought) and EO 23 (the November 2026 coastal storm).

Stdlib and pandas only.  Run:  python -m unittest test_va_eo_scraper
"""
import csv
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import va_eo_scraper as va
import va_historical_eo_scraper as historical

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = "https://www.governor.virginia.gov/media/governorvirginiagov/governor-of-virginia/pdf/eo/"
FIELDS = ("eo_number", "short_title", "date_signed", "detail_url")

EO_11 = ("EO-11", "Declaring State of Emergency", "2026-01-22",
         PDF + "EO-11-Declaring-State-of-Emergency---2026-January-Winter-Weather.pdf")
EO_21 = ("EO-21", "Declaration of Emergency Due to Severe Drought Impacts on Farms and the Necessity of "
         "Hay Transportation Waivers", "2026-09-16",
         PDF + "eo-21-declaration-of-emergency-due-to-severe-drought.pdf")
# As the listing gives it: signed November 27, 2026, effective that day for 30 days.
EO_23 = ("EO-23", "Declaration of a State of Emergency Due to Severe Coastal Storm", "2026-11-27",
         PDF + "eo-23-declaration-of-a-state-of-emergency-due-to-severe-coastal-storm.pdf")


def saved_rows(name, key):
    with open(os.path.join(HERE, name), newline="", encoding="utf-8") as handle:
        return {row[key]: row for row in csv.DictReader(handle)}


class DeclarationTitleTests(unittest.TestCase):
    def test_a_title_that_names_its_cause_is_kept_as_it_is(self):
        _, title, _, url = EO_23
        description, weather, _ = va.declaration_metadata(title, url)
        self.assertTrue(va.is_declaration_candidate(title))
        self.assertTrue(weather)
        self.assertEqual(description, "Declaration of a State of Emergency Due to Severe Coastal Storm")

    def test_the_generic_label_takes_its_cause_from_the_pdf_name(self):
        # EO 11's listing title is only "Declaring State of Emergency".
        _, title, _, url = EO_11
        self.assertEqual(va.declaration_metadata(title, url)[0],
                         "Declaring State of Emergency Due to Winter Weather")
        self.assertEqual(saved_rows("va_emergency_declarations_all.csv", "eo_number")["EO-11"]["event_description"],
                         va.declaration_metadata(title, url)[0])
        # If EO 23 is listed under a generic label, its cause still comes from the file name, once.
        self.assertEqual(va.declaration_metadata("Declaring State of Emergency", EO_23[3])[0],
                         "Declaring State of Emergency Due to Severe Coastal Storm")
        self.assertEqual(va.declaration_metadata("Declaration of a State of Emergency", EO_23[3])[0],
                         "Declaration of a State of Emergency Due to Severe Coastal Storm")

    def test_a_drought_declaration_of_emergency_is_a_weather_declaration(self):
        _, title, _, url = EO_21
        self.assertTrue(va.is_declaration_candidate(title))
        description, weather, _ = va.declaration_metadata(title, url)
        self.assertTrue(weather)
        self.assertEqual(description, title)
        listed = saved_rows("va_all_orders_raw.csv", "eo_number")["EO-21"]
        self.assertEqual(tuple(listed[field] for field in FIELDS), EO_21)

    def test_follow_on_procedural_and_other_orders_are_not_new_declarations(self):
        for title in (
            "Extending the State of Emergency Due to Severe Coastal Storm",
            "Amending Executive Order 23 (2026), Declaration of a State of Emergency Due to Severe Coastal Storm",
            "Rescinding the Declaration of Emergency Due to Severe Drought",
            "Delegating the Authority to Declare a State of Emergency",
            "Delegating Emergency and Succession Authority of the Governor",
            "Keeping Virginia Covered",
        ):
            self.assertFalse(va.is_declaration_candidate(title), title)
        # A cause that is itself "extended" or "continued", or a word that only
        # contains one of those verbs, is still a new declaration.
        self.assertTrue(va.is_declaration_candidate("Declaration of a State of Emergency Due to Extended Drought"))
        self.assertTrue(va.is_declaration_candidate("Declaring a State of Emergency Due to Continued Flooding"))
        self.assertTrue(va.is_declaration_candidate(
            "Declaration of a State of Emergency Due to the Discontinuation of Ferry Service"))


class RefreshTests(unittest.TestCase):
    """main() on the saved listing with EO 23 added, as the next refresh will see it."""

    def run_refresh(self, listing):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {name: os.path.join(tmp, name + ".csv") for name in ("raw", "all", "join")}
            argv = ["va_eo_scraper.py", "--raw-out", paths["raw"], "--all-out", paths["all"],
                    "--join-out", paths["join"]]
            with mock.patch.object(va, "parse_listing", return_value=listing), \
                    mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new_callable=io.StringIO):
                va.main()
            with open(paths["join"], newline="", encoding="utf-8") as handle:
                join = list(csv.DictReader(handle))
            current = historical.current_rows(paths["join"])
        return join, {row["declaration_id"]: row for row in current.to_dict("records")}

    def test_the_next_refresh_writes_eo_21_and_eo_23_once_each(self):
        listing = list(saved_rows("va_all_orders_raw.csv", "eo_number").values())
        listing.insert(0, dict(zip(FIELDS, EO_23)))
        join, current = self.run_refresh(listing)
        self.assertEqual(sorted(row["eo_number"] for row in join), ["EO-11", "EO-21", "EO-23"])
        expected = {
            "VA-SPANBERGER-EO-23-2026": ("Executive Order 23 (2026) Declaration of a State of Emergency Due to "
                                         "Severe Coastal Storm", "2026-11-27", EO_23[3]),
            "VA-SPANBERGER-EO-21-2026": ("Executive Order 21 (2026) Declaration of Emergency Due to Severe Drought "
                                         "Impacts on Farms and the Necessity of Hay Transportation Waivers",
                                         "2026-09-16", EO_21[3]),
        }
        for declaration_id, values in expected.items():
            row = current[declaration_id]
            self.assertEqual((row["event_description"], row["date_signed"], row["archive_record_url"]), values)
        # EO 11 comes out exactly as the saved merged join file has it.
        saved = saved_rows("declarations_for_join_2002_present.csv", "declaration_id")["VA-SPANBERGER-EO-11-2026"]
        self.assertEqual(current["VA-SPANBERGER-EO-11-2026"]["event_description"], saved["event_description"])
        # The storm join can classify both new titles.
        spec = importlib.util.spec_from_file_location("va_eo_storm_join", os.path.join(HERE, "eo_storm_join.py"))
        join_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(join_module)
        self.assertIn("Coastal Flood",
                      join_module.compatible_event_types(current["VA-SPANBERGER-EO-23-2026"]["event_description"]))
        self.assertEqual(set(join_module.compatible_event_types(current["VA-SPANBERGER-EO-21-2026"]["event_description"])),
                         {"Drought"})


if __name__ == "__main__":
    unittest.main()
