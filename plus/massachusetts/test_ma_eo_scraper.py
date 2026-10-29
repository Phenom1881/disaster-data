import csv
import tempfile
import unittest

import ma_eo_scraper as ma


class MassachusettsScraperTests(unittest.TestCase):
    def test_parse_new_series_item(self):
        item = {"uuid": "abc", "name": "Executive Order (new series) No. 652", "metadata": {"dc.date.issued": [{"value": "2026-02-22"}], "dc.title.alternative": [{"value": "Temporary motor vehicle ban during a blizzard"}], "dc.description": [{"value": "Amended by Executive Order No. 653"}]}, "_links": {"self": {"href": "https://api.test/item"}}}
        order = ma.parse_item(item)
        self.assertEqual(order.stable_id, "MA-EO-652")
        self.assertEqual(order.governor, "Maura Healey")
        self.assertTrue(ma.is_weather_related(order))

    def test_first_series_ids_do_not_collide(self):
        item = {"uuid": "old", "name": "Executive Order No. 89", "metadata": {"dc.date.issued": [{"value": "1946-05-01"}]}}
        self.assertEqual(ma.parse_item(item).stable_id, "MA-EO-1S-89")

    def test_energy_winter_price_is_not_weather(self):
        order = ma.MAOrder("1", False, "Energy plan", "Mitigate winter price spikes", "2026-01-01", "Maura Healey", "x", "x")
        self.assertFalse(ma.is_weather_related(order))

    def test_join_excludes_termination(self):
        base = ma.MAOrder("142", False, "State of emergency", "Blizzard emergency", "1978-02-08", "Michael Dukakis", "x", "x", action_type="declaration", weather_related=True)
        end = ma.MAOrder("143", False, "Ending emergency", "Ending blizzard emergency", "1978-02-20", "Michael Dukakis", "y", "y", action_type="termination", weather_related=True)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            ma.write_outputs([base, end], [], *paths)
            with open(paths[2], newline="") as handle: rows = list(csv.DictReader(handle))
        self.assertEqual([row["declaration_id"] for row in rows], ["MA-EO-142"])
        self.assertEqual(list(rows[0]), ma.JOIN_FIELDS)


def item(number, issued, alternative):
    metadata = {"dc.title.alternative": [{"value": alternative}]}
    if issued:
        metadata["dc.date.issued"] = [{"value": issued}]
    return {"uuid": "u" + number, "name": f"Executive Order (new series) No. {number}", "metadata": metadata,
            "_links": {"self": {"href": "https://api.test/item"}}}


class TitledEmergencyTests(unittest.TestCase):
    """Orders named for the emergency itself, as the State Library catalogues them."""

    def test_an_order_named_state_of_emergency_is_a_declaration(self):
        for number, issued, title in (("239", "1984-03-31", "State of Emergency Due to Major Rain Storm in the Commonwealth of Massachusetts May 31,1984"),
                                      ("189", "1980-11-18", "State of Emergency Executive Order November 18, 1980"),
                                      ("238", "1984-05-11", "Declaration of Emergency - Peabody Fire, May 10, 1984")):
            self.assertEqual(ma.classify_action(ma.parse_item(item(number, issued, title))), "declaration", number)

    def test_follow_on_orders_keep_their_own_type(self):
        for title, kind in (("Rescinding the State of Emergency declared in Executive Order No. 142", "termination"),
                            ("Amending the State of Emergency declared in Executive Order No. 366", "amendment")):
            self.assertEqual(ma.classify_action(ma.parse_item(item("999", "1994-04-01", title))), kind)

    def test_an_undated_record_takes_the_date_in_its_title(self):
        blizzard = ma.parse_item(item("142", "", "State of Emergency Executive Order, February 9, 1978"))
        self.assertEqual((blizzard.date_issued, blizzard.governor), ("1978-02-09", "Michael Dukakis"))
        self.assertTrue(ma.is_weather_related(blizzard))   # reviewed: the Blizzard of 1978

    def test_a_reviewed_date_replaces_the_records(self):
        self.assertEqual(ma.parse_item(item("239", "1984-03-31", "State of Emergency Due to Major Rain Storm")).date_issued,
                         "1984-05-31")
        self.assertEqual(ma.parse_item(item("189", "1980-11-18", "State of Emergency Executive Order")).date_issued,
                         "1980-11-18")

    def test_other_titled_emergencies_are_not_weather_without_a_hazard(self):
        gas = ma.parse_item(item("191", "1981-01-15", "State of Emergency Resulting From Natural Gas Supply Shortage"))
        self.assertFalse(ma.is_weather_related(gas))

    def test_saved_join_has_the_blizzard_and_the_rain_storm(self):
        with open("declarations_for_join.csv", encoding="utf-8") as handle:
            joined = {row["declaration_id"]: row["date_signed"] for row in csv.DictReader(handle)}
        self.assertEqual((joined["MA-EO-142"], joined["MA-EO-239"]), ("1978-02-09", "1984-05-31"))
        with open("hazard_overrides.csv", encoding="utf-8") as handle:
            overrides = {row["declaration_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(overrides["MA-EO-142"]["hazard_category_override"], "winter")


if __name__ == "__main__": unittest.main()
