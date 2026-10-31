import csv
import os
import unittest

import nc_eo_scraper as nc

HERE = os.path.dirname(os.path.abspath(__file__))


ARCHIVE_FIXTURE = """
<main>
<table><tbody>
<tr><td><a href="/executive-order-22">Executive Order No. 22 Notice of Termination of Executive Order No. 20</a></td><td>August 25, 2025</td></tr>
<tr><td><a href="/eo20-concurrence">Gov. Stein Executive Order 20 COS Concurrence</a></td><td>August 19, 2025</td></tr>
<tr><td><a href="/executive-order-20">Executive Order No. 20: Declaration of a State of Emergency</a></td><td>August 19, 2025</td></tr>
<tr><td><a href="/eo20-spanish">Executive Order No. 20 Spanish</a></td><td>August 19, 2025</td></tr>
</tbody></table>
<nav><a rel="next" href="?page=1">Next</a></nav>
</main>
"""

DETAIL_FIXTURE = """
<main>
<h1>Executive Order No. 22 Notice of Termination of Executive Order No. 20</h1>
<a href="/executive-order-22/open">EO22_TerminationEO20.pdf</a>
<div>August 25, 2025 Executive Order No. 22 Notice of Termination of Executive Order No. 20.
Whereas Hurricane Erin impacted North Carolina. Executive Order No. 20 is hereby terminated.</div>
<div>Document Entity Terms Executive Order First Published August 25, 2025 Last Updated August 25, 2025</div>
</main>
"""


class NorthCarolinaScraperTests(unittest.TestCase):
    def test_archive_rows_and_dates(self):
        entries = nc.parse_archive_page(ARCHIVE_FIXTURE)
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0].order_number, "22")
        self.assertEqual(entries[0].date_issued, "2025-08-25")
        self.assertTrue(entries[1].supporting)
        self.assertTrue(nc._has_next_page(ARCHIVE_FIXTURE))

    def test_canonicalization_keeps_supporting_urls(self):
        orders = nc.canonicalize_entries(nc.parse_archive_page(ARCHIVE_FIXTURE))
        twenty = next(order for order in orders if order.order_number == "20")
        self.assertEqual(twenty.governor, "Josh Stein")
        self.assertEqual(twenty.detail_url, "https://governor.nc.gov/executive-order-20")
        self.assertEqual(len(twenty.supporting_urls), 2)
        self.assertEqual(twenty.stable_id, "NC-JOSHSTEIN-EO-20")

    def test_classification_and_weather(self):
        declaration = nc.NCOrder(
            governor="Josh Stein", order_number="20",
            title="Declaration of a State of Emergency",
            description="Anticipated impacts from Hurricane Erin",
            date_issued="2025-08-19", detail_url="x",
        )
        self.assertEqual(nc.classify_action(declaration), "declaration")
        self.assertTrue(nc.is_weather_related(declaration))
        administrative = nc.NCOrder(
            governor="Roy Cooper", order_number="242",
            title="Extending the State Emergency Response Commission",
            description="Commission membership", date_issued="2021-12-17",
            detail_url="x",
        )
        self.assertEqual(nc.classify_action(administrative), "extension")
        self.assertFalse(nc.is_weather_related(administrative))

    def test_multi_target_termination(self):
        one = nc.NCOrder("Roy Cooper", "1", "State of Emergency", "Winter storm", "2017-01-06", "one")
        two = nc.NCOrder("Roy Cooper", "2", "Transportation Waiver", "Winter storm", "2017-01-06", "two")
        three = nc.NCOrder("Roy Cooper", "3", "Notice of Termination of Executive Orders 1 and 2", "", "2017-01-10", "three")
        for order in (one, two, three):
            order.action_type = nc.classify_action(order)
        relationships = nc.build_relationships([one, two, three])
        self.assertEqual({row["target_order_id"] for row in relationships}, {one.stable_id, two.stable_id})
        self.assertTrue(all(row["relationship_type"] == "terminates" for row in relationships))

    def test_single_target_termination_and_end_date(self):
        base = nc.NCOrder("Josh Stein", "20", "Declaration of a State of Emergency", "Hurricane Erin", "2025-08-19", "base")
        end = nc.NCOrder("Josh Stein", "22", "Notice of Termination of Executive Order No. 20", "", "2025-08-25", "end")
        base.action_type = nc.classify_action(base)
        end.action_type = nc.classify_action(end)
        relationships = nc.build_relationships([base, end])
        self.assertEqual(len(relationships), 1)
        nc.apply_end_dates([base, end], relationships)
        self.assertEqual(base.end_date, "2025-08-25")

    def test_first_published_date(self):
        self.assertEqual(nc._first_published("First Published October 10, 2018 Last Updated"), "2018-10-10")

    def test_document_filename_can_supply_hazard(self):
        order = nc.NCOrder(
            "Roy Cooper", "74", "Declaration of a State of Emergency", "",
            "2018-10-10", "detail", document_label="EO74 Hurricane Michael.pdf",
        )
        self.assertTrue(nc.is_weather_related(order))

    def test_low_yield_threshold(self):
        self.assertEqual(nc.LOW_YIELD_PDF_CHARS, 250)


def order(number, description, title=None, governor="Roy Cooper", date="2024-09-25"):
    return nc.NCOrder(governor, number, title or f"Executive Order No. {number}", description, date, "x")


class DeclarationWordingTests(unittest.TestCase):
    """Headings as the archive's text gives them for Cooper's later orders."""

    def test_a_statewide_state_of_emergency_is_a_declaration(self):
        # EO 315, Helene
        helene = order("315", "DECLARATION OF A STATEWIDE STATE OF EMERGENCY AND TEMPORARY WAIVER "
                              "AND SUSPENSION OF MOTOR VE ID CLE REGULATIONS")
        self.assertEqual(nc.classify_action(helene), "declaration")

    def test_words_split_by_ocr_still_read_as_a_declaration(self):
        # EO 270 (Ian) and EO 274 (cold weather, December 2022)
        ian = order("270", "DECLARAT IO OF A STATE OF EMERGENCY AND TEMPORARY WAIVER AND "
                           "SUSPENSION OF MOTOR VEHICLE REGULAT IO S")
        cold = order("274", "DECLARATION OF A STAT E OF EMERGENCY AND TEMPORARY SUSPENSION OF "
                            "MOTOR VEHICLE REGULATIONS TO ENSURE ADEQUATE")
        self.assertEqual(nc.classify_action(ian), "declaration")
        self.assertEqual(nc.classify_action(cold), "declaration")

    def test_follow_on_orders_keep_their_own_type(self):
        cases = {
            "extension": "EXTENDING THE STATEWIDE STATE OF EMERGENCY DECLARED IN EXECUTIVE ORDER NO. 315",
            "amendment": "AMENDMENT TO EXECUTIVE ORDER NO. 313 EXPANDING THE EMERGENCY AREA",
            "termination": "NOTICE OF TERMINATION OF THE STATEWIDE STATE OF EMERGENCY DECLARED IN EO 311",
        }
        for expected, text in cases.items():
            self.assertEqual(nc.classify_action(order("999", text)), expected, text)

    def test_waivers_without_a_state_of_emergency_stay_administrative(self):
        # EO 100, 102 and 103 support relief for Dorian; EO 101 is the declaration.
        for number, text in (("100", "Declaration of Emergency to Suspend Motor Vehicle Regulations "
                                     "adn Support Relief Efforts"),
                             ("102", "Declaration of Temporary Suspension of Motor Vehicle Regulations"),
                             ("103", "Declaration of Temporary Suspension of Tolls")):
            self.assertEqual(nc.classify_action(order(number, text, date="2019-08-30")), "administrative")

    def test_a_potential_tropical_cyclone_is_weather(self):
        ptc = order("313", "Potential Tropical Cyclone Eight")
        self.assertTrue(nc.is_weather_related(ptc))


class ReviewedDeclarationTests(unittest.TestCase):
    def test_a_title_only_order_takes_the_reviewed_reading(self):
        # EO 115: the archive shows only "Executive Order No. 115" and posts it
        # on February 9, 2020; FMCSA's copy is a state of emergency signed on
        # February 7 for the storms of February 6 and 7.
        storms = order("115", "Executive Order No. 115", date="2020-02-09")
        storms.action_type = nc.classify_action(storms)
        storms.weather_related = nc.is_weather_related(storms)
        self.assertEqual((storms.action_type, storms.weather_related), ("administrative", False))
        nc.apply_review(storms)
        self.assertEqual((storms.action_type, storms.weather_related, storms.date_issued),
                         ("declaration", True, "2020-02-07"))

    def test_review_leaves_other_orders_alone(self):
        other = order("12", "Executive Order No. 12: Declaration of a State of Emergency", date="2017-07-27")
        other.action_type = nc.classify_action(other)
        other.weather_related = nc.is_weather_related(other)
        nc.apply_review(other)   # EO 12 is a transmission line failure, not weather
        self.assertEqual((other.action_type, other.weather_related, other.date_issued),
                         ("declaration", False, "2017-07-27"))

    def test_reviewed_orders_carry_their_governor_in_the_id(self):
        # Numbering restarts with each administration, so EO 9 is Cooper's here.
        self.assertIn("NC-ROYCOOPER-EO-9", nc.REVIEWED_DECLARATIONS)
        self.assertTrue(all(key.startswith(("NC-ROYCOOPER-EO-", "NC-JOSHSTEIN-EO-"))
                            for key in nc.REVIEWED_DECLARATIONS))

    def test_every_reviewed_order_has_a_cited_hazard(self):
        with open(os.path.join(HERE, "hazard_overrides.csv"), encoding="utf-8") as handle:
            overrides = {row["declaration_id"]: row for row in csv.DictReader(handle)}
        for key, reviewed in nc.REVIEWED_DECLARATIONS.items():
            row = overrides.get(key)
            self.assertIsNotNone(row, key)
            self.assertNotEqual(row["hazard_category_override"].strip().lower(), "exclude", key)
            self.assertTrue(row["source_url"].startswith("https://"), key)
            if reviewed.get("signed"):
                self.assertRegex(reviewed["signed"], r"^\d{4}-\d{2}-\d{2}$")

    def test_saved_join_file_matches_the_saved_actions(self):
        # The join file is the actions file's dated weather declarations.
        with open(os.path.join(HERE, "nc_emergency_actions_all.csv"), encoding="utf-8") as handle:
            actions = list(csv.DictReader(handle))
        with open(os.path.join(HERE, "declarations_for_join.csv"), encoding="utf-8") as handle:
            joined = [row["declaration_id"] for row in csv.DictReader(handle)]
        expected = [row["declaration_id"] for row in actions
                    if row["action_type"] == "declaration" and row["weather_related"] == "True"
                    and row["date_signed"]]
        self.assertEqual(joined, expected)
        for key in nc.REVIEWED_DECLARATIONS:
            self.assertIn(key, joined)



# Governors of North Carolina and the day each took office.
GOVERNOR_TERMS = (("2017-01-01", "Roy Cooper"), ("2013-01-05", "Pat McCrory"),
                  ("2009-01-10", "Bev Perdue"), ("2001-01-06", "Mike Easley"),
                  ("1993-01-09", "James B. Hunt Jr."))


def governor_on(day):
    return next(name for start, name in GOVERNOR_TERMS if day >= start)


def csv_rows(name):
    with open(os.path.join(HERE, name), newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        import importlib.util
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from unittest import mock
        spec = importlib.util.spec_from_file_location("north_carolina_adapter", os.path.join(HERE, "north_carolina.py"))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "declarations_for_join.csv").write_text("declaration_id\n")
            with mock.patch.object(adapter, "_run", return_value=True):
                _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((Path(HERE).parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "NC"))
        self.assertTrue(note.startswith("2000-present"))


class HandAddedDeclarationTests(unittest.TestCase):
    """manual_declarations.csv carries the 2000-2016 weather declarations,
    each dated by the State Archives record identifier, the Governor's
    dated press release, NCDPS or dated news coverage."""

    def test_dates_read_from_the_sources(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            "NC-SOE-2000-01-25": "2000-01-25", "NC-SOE-2002-12-05": "2002-12-05",
            "NC-SOE-2003-09-16": "2003-09-16", "NC-SOE-2004-09-07": "2004-09-07",
            "NC-SOE-2004-09-17": "2004-09-17", "NC-MIKEEASLEY-EO-88": "2005-09-11",
            "NC-MIKEEASLEY-EO-144": "2008-09-04", "NC-BEVPERDUE-EO-62": "2010-09-01",
            "NC-SOE-2011-04-17": "2011-04-17", "NC-SOE-2011-08-25": "2011-08-25",
            # McCrory's are the State Archives identifiers (McCrory_EO_NNN_YYYYMMDD).
            "NC-PATMCCRORY-EO-16": "2013-07-11", "NC-PATMCCRORY-EO-17": "2013-07-16",
            "NC-PATMCCRORY-EO-43": "2014-02-11", "NC-PATMCCRORY-EO-51": "2014-04-29",
            "NC-PATMCCRORY-EO-57": "2014-07-02", "NC-PATMCCRORY-EO-66": "2015-02-16",
            "NC-PATMCCRORY-EO-97": "2016-09-01", "NC-PATMCCRORY-EO-103": "2016-09-22",
            "NC-PATMCCRORY-EO-107": "2016-10-03", "NC-PATMCCRORY-EO-115": "2016-11-10",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_ids_carry_the_date_or_the_governor_and_number(self):
        rows = csv_rows("manual_declarations.csv")
        self.assertEqual(len(rows), len({r["declaration_id"] for r in rows}))
        for row in rows:
            did = row["declaration_id"]
            if did.startswith("NC-SOE-"):
                self.assertEqual(did, "NC-SOE-" + row["date_signed"])
                self.assertEqual(row["eo_number"], "")
            else:
                key = row["governor"].upper().replace(" ", "").replace(".", "")
                self.assertEqual(did, "NC-%s-EO-%s" % (key, row["eo_number"]))
                self.assertIn("Executive Order No. %s" % row["eo_number"], row["event_description"])

    def test_governor_in_office_on_each_date(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_names_its_hazard_and_links_its_source(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertRegex(row["event_description"].lower(),
                             r"snow|ice|storm|hurricane|flood|tornado|wildfire|cold|winter", row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])

    def test_they_only_fill_the_years_before_the_archive(self):
        hand = csv_rows("manual_declarations.csv")
        archive = csv_rows("declarations_for_join.csv")
        self.assertFalse({r["declaration_id"] for r in hand} & {r["declaration_id"] for r in archive})
        self.assertLess(max(r["date_signed"] for r in hand), "2017-01-01")

    def test_reviewed_event_dates_come_before_signing(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        events = {}
        for row in csv_rows("hazard_overrides.csv"):
            if row["declaration_id"] in signed:
                events[row["declaration_id"]] = row["event_date"]
                if row["event_date"]:
                    self.assertLessEqual(row["event_date"], signed[row["declaration_id"]])
        self.assertEqual(events["NC-PATMCCRORY-EO-17"], "2013-06-30")
        self.assertEqual(events["NC-SOE-2004-06-04"], "2004-01-26")

if __name__ == "__main__":
    unittest.main()
