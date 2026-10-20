import csv
import tempfile
import unittest
from pathlib import Path
import wa_eo_scraper as wa

class WashingtonScraperTests(unittest.TestCase):
    def action(self, number="21-18", title="Severe Weather Damage", text="I proclaim that a State of Emergency exists due to flooding"):
        return wa.Action(number,"2021-11-15",title,"https://governor.wa.gov/example.pdf",text=text)
    def test_original(self): self.assertEqual(wa.classify(self.action()),"declaration")
    def test_decimal_is_modifier(self): self.assertEqual(wa.classify(self.action("21-18.1","Severe Weather - Truck Driver Hours")),"amendment")
    def test_join_excludes_modifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); wa.write_outputs([self.action(),self.action("21-18.1","Severe Weather - Truck Driver Hours")],root/"a.csv",root/"r.csv",root/"j.csv")
            with (root/"j.csv").open() as f: rows=list(csv.DictReader(f)); self.assertEqual(tuple(rows[0]),wa.JOIN_FIELDS); self.assertEqual(len(rows),1)

ROAD_CLOSURES = ("WHEREAS, a severe winter storm began on December 18, 2015, and is forecast to continue, "
                 "causing hazardous driving conditions and extended road closures on mountain passes; "
                 "NOW, THEREFORE, I do hereby proclaim that a State of Emergency exists in Chelan County")


def proclamation(number, title, text, signed="2015-12-24"):
    return wa.Action(number, signed, title, "https://governor.wa.gov/example.pdf", text=text)


class RecitalWordingTests(unittest.TestCase):
    """Modifier words in a recital are not a modifier unless the opening cites another proclamation."""

    def test_a_new_declaration_that_recites_extended_closures_is_a_declaration(self):
        # 15-17, 17-01, 19-02 and 22-01 all say "extended road closures on mountain passes".
        for number, title in (("15-17", "State of Emergency (Winter Storm)"),
                              ("22-01", "Winter Weather and Flooding")):
            self.assertEqual(wa.classify(proclamation(number, title, ROAD_CLOSURES)), "declaration", number)

    def test_a_continuation_that_cites_the_earlier_proclamation_is_an_extension(self):
        # 17-02 opens by citing 17-01 and recites the same closures.
        text = ("WHEREAS, on January 13, 2017, I issued Proclamation 17-01, proclaiming a state of emergency; "
                "and WHEREAS, the storm has resulted in extended road closures")
        self.assertEqual(wa.classify(proclamation("17-02", "State of Emergency (Winter Storm)", text, "2017-01-19")),
                         "extension")

    def test_citing_only_its_own_number_does_not_make_it_a_modifier(self):
        text = "EMERGENCY PROCLAMATION 22-01 " + ROAD_CLOSURES
        self.assertEqual(wa.classify(proclamation("22-01", "Winter Weather and Flooding", text, "2022-01-07")),
                         "declaration")

    def test_an_amending_title_and_a_decimal_number_still_modify(self):
        self.assertEqual(wa.classify(proclamation("20-73", "Wildfires - Truck Driver Hours",
                                                  "AMENDING PROCLAMATION 20-68 WHEREAS, on August 19, 2020, "
                                                  "I issued Proclamation 20-68")), "amendment")
        self.assertEqual(wa.classify(proclamation("22-01.1", "Winter Weather and Driver Hours", ROAD_CLOSURES)),
                         "amendment")

    def test_saved_join_matches_the_saved_actions(self):
        here = Path(__file__).resolve().parent
        with (here / "wa_emergency_actions_all.csv").open(encoding="utf-8") as handle:
            actions = list(csv.DictReader(handle))
        with (here / "declarations_for_join.csv").open(encoding="utf-8") as handle:
            joined = [row["declaration_id"] for row in csv.DictReader(handle)]
        expected = [row["declaration_id"] for row in actions
                    if row["action_type"] == "declaration" and row["weather_related"] == "true"]
        self.assertEqual(joined, expected)
        for number in ("15-17", "17-01", "19-02", "22-01"):
            self.assertIn("WA-PROC-" + number, joined)


if __name__ == "__main__": unittest.main()
