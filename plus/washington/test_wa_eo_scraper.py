import csv
import re
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


class ReviewedEventDateTests(unittest.TestCase):
    """hazard_overrides.csv event dates for proclamations signed after the storm."""

    def test_each_event_date_comes_before_its_proclamation(self):
        from datetime import date
        here = Path(__file__).resolve().parent
        with (here / "wa_emergency_actions_all.csv").open(encoding="utf-8") as handle:
            actions = {row["declaration_id"]: row for row in csv.DictReader(handle)}
        with (here / "hazard_overrides.csv").open(encoding="utf-8") as handle:
            overrides = [row for row in csv.DictReader(handle) if row.get("event_date")]
        self.assertTrue(overrides)
        for row in overrides:
            action = actions[row["declaration_id"]]
            self.assertEqual((action["action_type"], action["weather_related"]), ("declaration", "true"),
                             row["declaration_id"])
            days = (date.fromisoformat(action["date_signed"]) - date.fromisoformat(row["event_date"])).days
            self.assertTrue(0 <= days <= 120, (row["declaration_id"], days))
            self.assertTrue(row["source_url"].startswith("https://governor.wa.gov/"), row["declaration_id"])

    def test_hand_added_pre_2013_proclamations(self):
        with open(Path(__file__).parent / "manual_declarations.csv", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        ids = [row["declaration_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        dates = {row["declaration_id"]: row["date_signed"] for row in rows}
        self.assertEqual(dates["WA-PROC-07-02"], "2007-03-06")
        self.assertEqual(dates["WA-SOE-2006-11-09"], "2006-11-09")
        # The scan of the February 2003 order says January 8, 2002 in error; the termination dates it February 12, 2003.
        self.assertEqual(dates["WA-SOE-2003-02-12"], "2003-02-12")
        self.assertNotIn("WA-SOE-2002-02-12", dates)
        for row in rows:
            self.assertRegex(row["date_signed"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertLess(row["date_signed"], "2013-04-22", row["declaration_id"])
            self.assertTrue(wa.HAZARD_RE.search(row["event_description"]) or re.search(r"\b(?:rainfall|landslides?)\b", row["event_description"]), row["declaration_id"])
            if row["declaration_id"].startswith("WA-SOE-"):
                self.assertTrue(row["declaration_id"].endswith(row["date_signed"]), row["declaration_id"])


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest(self):
        """A refresh (build-plus.py --collect) shows the note collect()
        returns, and a build without collection shows the manifest's. They
        must agree, or the page's start year and federal comparison change
        from one build to the next."""
        import importlib.util
        import json
        import subprocess
        from unittest import mock
        here = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("washington_adapter", here / "washington.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((here.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        states = manifest["states"] if isinstance(manifest, dict) else manifest
        expected = next(st["coverage_note"] for st in states if st["abbreviation"] == "WA")
        self.assertEqual(note, expected)
        self.assertTrue(note.startswith("2000-present"))


if __name__ == "__main__": unittest.main()
