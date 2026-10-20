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


def library_record(title, created, record_id="alma1"):
    return {"pnx": {"display": {"title": [title], "creationdate": [created]},
                    "control": {"recordid": [record_id]}}}


IRENE = ("Executive Order 40 (2011) Declaration of a State of Emergency for the Commonwealth of Virginia due "
         "to the Threat of Significant Flooding, Heavy Rains, and Wind Damage caused by Hurricane Irene")


class DeclaredDateTests(unittest.TestCase):
    """A written order signed after a verbal declaration takes the declaration's date."""

    def row(self, title, created):
        return va.document_to_row(library_record(title, created), "Robert F. McDonnell", "2010-2014",
                                  "mcdonnell", "81116276820005756")

    def test_irene_takes_the_date_it_was_declared(self):
        # Signed September 28, 2011, "effective retroactively to August 25".
        row = self.row(IRENE, "2011-09-28")
        self.assertEqual(row["declaration_id"], "VA-MCDONNELL-EO-40-2011")
        self.assertEqual(row["date_signed"], "2011-08-25")

    def test_other_orders_keep_the_library_date(self):
        quake = self.row("Executive Order 38 (2011) Declaration of a State of Emergency for the Commowealth of "
                         "Virginia Due to a 5.8 Magnitude Earthquake", "2011-08-31")
        self.assertEqual(quake["date_signed"], "2011-08-31")

    def test_reviewed_dates_are_iso_dates_with_a_note(self):
        for key, (declared, note) in va.REVIEWED_DECLARED_DATES.items():
            self.assertRegex(declared, r"^\d{4}-\d{2}-\d{2}$", key)
            self.assertTrue(note, key)

    def test_saved_files_carry_the_declared_date(self):
        for name in ("va_eo_archive_all.csv", "va_emergency_actions_2002_2026.csv",
                     "va_weather_emergency_actions_2002_2026.csv", "declarations_for_join_2002_present.csv"):
            with open(os.path.join(HERE, name), encoding="utf-8") as handle:
                rows = {row["declaration_id"]: row for row in csv.DictReader(handle)}
            for key, (declared, _) in va.REVIEWED_DECLARED_DATES.items():
                self.assertEqual(rows[key]["date_signed"], declared, name)


if __name__ == "__main__":
    unittest.main()
