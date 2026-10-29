import csv
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build-plus.py")
SPEC = importlib.util.spec_from_file_location("build_plus_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed",
               "archive_record_url"]
METRICS = {"action_count": 1, "federal_declaration_count": 1, "storm_match_rows": 0,
           "severity_rows": 0}
STATE = {"name": "New Jersey", "slug": "new-jersey", "abbreviation": "NJ",
         "official_source_url": "https://example.test/archive",
         "action_files": ["declarations_for_join.csv"]}


def action(declaration_id, date_signed, origin=None):
    row = {"declaration_id": declaration_id, "action_number": "1", "title": "Winter storm emergency",
           "date_signed": date_signed, "action_type": "declaration", "governor": "Test Governor",
           "source_url": "https://example.test/1"}
    if origin:
        row["origin"] = origin
    return row


def federal(identifier, begin, end, kind="DR", incident="Flood", tribal=False):
    return {"id": identifier, "number": identifier, "type": kind, "title": f"{incident} {identifier}",
            "incidentType": incident, "date": begin, "begin": begin, "end": end, "tribal": tribal}


def write(path, rows, fields=JOIN_FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def text(page):
    """The page's words, without its markup."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


class WeatherPageTests(unittest.TestCase):
    def test_page_leads_with_weather_and_collapses_large_evidence_tables(self):
        actions = [action("NJ-TEST-EO-1", "2026-01-01")]
        federal_rows = [{
            "date": "2026-01-02", "number": "EM-9999", "type": "EM",
            "title": "Winter Storm", "incidentType": "Severe Storm",
            "begin": "2026-01-01", "end": "2026-01-03",
        }]
        crosswalk = MODULE.build_crosswalk(actions, federal_rows, {})
        page = MODULE.render_state_page(
            STATE, actions, federal_rows, [], crosswalk, METRICS, "Fixture coverage"
        )

        self.assertIn("Weather Emergency Declarations", page)
        self.assertIn('id="state-weather-table"', page)
        self.assertIn('<details class="layer">', page)
        self.assertIn("Federal FEMA declarations", page)
        self.assertIn('class="table-search"', page)
        self.assertIn('class="sort-button"', page)
        self.assertNotIn("loaded state-action records", page)


class SourceBreakdownTests(unittest.TestCase):
    """Each declaration says which file it came from, and the page adds them up."""

    def row(self, declaration_id, date_signed="2025-05-01", title="Tornado"):
        return {"declaration_id": declaration_id, "governor": "G", "eo_number": "1",
                "event_description": title, "date_signed": date_signed, "archive_record_url": "u"}

    def test_each_row_says_where_it_came_from_and_the_page_adds_them_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder / "declarations_for_join.csv",
                  [self.row("NJ-1"), self.row("NJ-2", title="Fuel shortage"),
                   self.row("NJ-OLD", date_signed="1965-03-01")])
            write(folder / "manual_declarations.csv", [self.row("NJ-HAND-1", "2010-02-10")])
            write(folder / "fmcsa_declarations.csv", [self.row("NJ-FMCSA-1", "2019-01-20")])
            write(folder / "hazard_overrides.csv",
                  [{"declaration_id": "NJ-2", "hazard_category_override": "exclude"}],
                  ["declaration_id", "hazard_category_override", "review_note", "source_url"])

            actions, _ = MODULE.load_state_actions(STATE, folder)
            origins = {a["declaration_id"]: a["origin"] for a in actions}
            self.assertEqual(origins, {"NJ-1": "state", "NJ-HAND-1": "hand", "NJ-FMCSA-1": "fmcsa"})

            crosswalk = MODULE.build_crosswalk(actions, [], {"NJ-1": [{"CZ_NAME": "OCEAN"}]})
            sources = MODULE.source_breakdown(STATE, folder, actions, crosswalk)
            self.assertEqual(sources["state_archive"], 1)
            self.assertEqual(sources["added_by_hand"], 1)
            self.assertEqual(sources["fmcsa_archive"], 1)
            self.assertEqual(sources["reviewed_not_weather"], 1)   # NJ-2; the 1965 row is not counted
            self.assertEqual(sources["noaa_matched"], 1)
            self.assertEqual(sources["federal_matched"], 0)

            page = MODULE.render_state_page(STATE, actions, [], [], crosswalk,
                                            dict(METRICS, action_count=3), "Fixture coverage",
                                            sources=sources)
        words = text(page)
        self.assertIn("1 from the state's own archive", words)
        self.assertIn("1 added by hand", words)
        self.assertIn("1 from FMCSA's archive", words)
        self.assertIn("1 record from these sources was reviewed as not a weather emergency", words)
        for label in ("State archive", "Added by hand", "FMCSA archive"):
            self.assertIn(f"<td>{label}</td>", page)
        self.assertIn("Source", words)

    def test_a_source_the_state_does_not_use_is_not_listed(self):
        sources = {"state_archive": 4, "added_by_hand": 0, "fmcsa_archive": 0,
                   "reviewed_not_weather": 0}
        html = MODULE.sources_html(sources)
        self.assertIn("4", html)
        self.assertNotIn("by hand", html)
        self.assertNotIn("FMCSA", html)
        self.assertNotIn("reviewed", html)

    def test_the_crosswalk_says_its_totals(self):
        sources = {"noaa_matched": 2, "noaa_pending": 1, "noaa_none": 1, "federal_matched": 1}
        self.assertEqual(
            text(MODULE.crosswalk_summary_html(sources, 4)).strip(),
            "2 of the 4 declarations on this page have NOAA storm reports nearby, and 1 is too "
            "recent for NOAA's published data. 1 has a FEMA declaration within 21 days.")
        one = {"noaa_matched": 0, "noaa_pending": 0, "noaa_none": 1, "federal_matched": 1}
        self.assertEqual(text(MODULE.crosswalk_summary_html(one, 1)).strip(),
                         "It has no NOAA storm reports nearby. It has a FEMA declaration within 21 days.")
        self.assertEqual(MODULE.crosswalk_summary_html(sources, 0), "")


class ReviewedEventDateTests(unittest.TestCase):
    """An order signed weeks after its event is compared on the event's date."""

    # Washington 15-14: signed September 21, 2015 for the August 29 windstorm.
    WINDSTORM = [federal("DR-4242", "2015-08-29", "2015-08-29", incident="Severe Storm")]
    LATE = action("WA-PROC-15-14", "2015-09-21")

    def overrides(self, folder, rows):
        write(folder / "hazard_overrides.csv", rows,
              ["declaration_id", "hazard_category_override", "review_note", "source_url", "event_date"])

    def test_event_dates_are_read_from_the_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(MODULE.reviewed_event_dates(folder), {})
            self.overrides(folder, [
                {"declaration_id": "WA-PROC-15-14", "hazard_category_override": "wind",
                 "event_date": "2015-08-29"},
                {"declaration_id": "WA-PROC-16-01", "hazard_category_override": "flood", "event_date": ""},
                {"declaration_id": "WA-PROC-16-02", "hazard_category_override": "exclude"},
            ])
            self.assertEqual(MODULE.reviewed_event_dates(folder), {"WA-PROC-15-14": "2015-08-29"})

    def test_a_collected_event_date_counts_and_a_reviewed_one_wins(self):
        # Tennessee's proclamations carry the event date their titles give.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder / "declarations_for_join.csv",
                  [{"declaration_id": "TN-PROC-2700", "date_signed": "2024-08-14", "event_date": "2024-05-08"},
                   {"declaration_id": "TN-PROC-9", "date_signed": "2024-08-14", "event_date": "2024-05-08"},
                   {"declaration_id": "TN-EO-1", "date_signed": "2024-01-01", "event_date": ""}],
                  ["declaration_id", "date_signed", "event_date"])
            self.overrides(folder, [{"declaration_id": "TN-PROC-9", "hazard_category_override": "flood",
                                     "event_date": "2024-05-09"}])
            self.assertEqual(MODULE.reviewed_event_dates(folder),
                             {"TN-PROC-2700": "2024-05-08", "TN-PROC-9": "2024-05-09"})

    def test_a_late_order_matches_the_event_it_declares(self):
        events = {"WA-PROC-15-14": "2015-08-29"}
        self.assertIsNone(MODULE.find_federal_match(self.LATE, self.WINDSTORM))
        self.assertEqual(MODULE.find_federal_match(self.LATE, self.WINDSTORM, events)["id"], "DR-4242")
        self.assertEqual(len(MODULE.federal_without_state(self.WINDSTORM, [self.LATE], 2013)[0]), 1)
        self.assertEqual(MODULE.federal_without_state(self.WINDSTORM, [self.LATE], 2013, events), ([], 1))

    def test_the_event_date_replaces_the_signing_date(self):
        # Washington 24-01: signed January 24, 2024 for the atmospheric river of
        # December 3, 2023. FEMA's DR-4775 is for storms from January 5, 2024.
        january = [federal("DR-4775", "2024-01-05", "2024-01-29", incident="Severe Storm")]
        december = action("WA-PROC-24-01", "2024-01-24")
        events = {"WA-PROC-24-01": "2023-12-06"}
        self.assertEqual(MODULE.find_federal_match(december, january)["id"], "DR-4775")
        self.assertIsNone(MODULE.find_federal_match(december, january, events))
        self.assertEqual(len(MODULE.federal_without_state(january, [december], 2013, events)[0]), 1)

    def test_the_crosswalk_uses_them(self):
        rows = MODULE.build_crosswalk([self.LATE], self.WINDSTORM, {}, {"WA-PROC-15-14": "2015-08-29"})
        self.assertEqual(rows[0]["federal_status"], "matched")
        self.assertEqual(MODULE.build_crosswalk([self.LATE], self.WINDSTORM, {})[0]["federal_status"],
                         "no_federal_declaration_found")


class WeatherOnlyMatchTests(unittest.TestCase):
    """A state weather declaration is paired only with a federal weather declaration."""

    FLOOD = action("NC-1", "2020-05-20")

    def test_covid_is_not_a_match(self):
        covid = federal("DR-4487", "2020-01-20", "2023-05-11", incident="Biological")
        self.assertIsNone(MODULE.find_federal_match(self.FLOOD, [covid]))
        eta = federal("DR-4588", "2020-05-18", "2020-05-22", incident="Severe Storm")
        self.assertEqual(MODULE.find_federal_match(self.FLOOD, [covid, eta])["id"], "DR-4588")

    def test_other_non_weather_declarations_are_not_matches(self):
        for incident in ("Earthquake", "Volcanic Eruption", "Other"):
            self.assertIsNone(MODULE.find_federal_match(
                self.FLOOD, [federal("DR-9", "2020-05-19", "2020-05-19", incident=incident)]), incident)

    def test_a_dam_failure_in_a_storm_and_a_fire_still_match(self):
        midland = federal("DR-4547", "2020-05-16", "2020-05-22", incident="Dam/Levee Break")
        self.assertEqual(MODULE.find_federal_match(self.FLOOD, [midland])["id"], "DR-4547")
        fire = federal("FM-1", "2020-05-19", "2020-05-25", "FM", "Fire")
        self.assertEqual(MODULE.find_federal_match(self.FLOOD, [fire])["id"], "FM-1")


class EvacueeHostingTests(unittest.TestCase):
    """An emergency for sheltering another state's evacuees is not a storm in this state."""

    def katrina(self, identifier, title, incident="Hurricane"):
        row = federal(identifier, "2005-08-29", "2005-10-01", "EM", incident)
        row["title"] = title
        row["eventName"] = "Katrina"
        return row

    def test_a_host_states_evacuation_emergency_is_not_a_gap(self):
        oregon = [self.katrina("EM-3228", "HURRICANE KATRINA EVACUATION", "Coastal Storm")]
        nebraska = [self.katrina("EM-3245", "HURRICANE KATRINA EVACUEES")]
        self.assertEqual(MODULE.federal_without_state(oregon, [], 2003), ([], 0))
        self.assertEqual(MODULE.federal_without_state(nebraska, [], 2003), ([], 0))

    def test_the_three_untitled_host_emergencies_are_not_gaps(self):
        # FEMA titles Idaho EM-3244, Kentucky EM-3231 and Pennsylvania EM-3235 only "HURRICANE KATRINA",
        # but each was declared to assist evacuees from the area struck by the storm.
        for identifier in ("EM-3244", "EM-3231", "EM-3235"):
            host = [self.katrina(identifier, "HURRICANE KATRINA")]
            self.assertEqual(MODULE.federal_without_state(host, [], 2003), ([], 0), identifier)
        flood = action("ID-1", "2005-09-12")
        self.assertIsNone(MODULE.find_federal_match(flood, [self.katrina("EM-3244", "HURRICANE KATRINA")]))

    def test_the_storms_own_emergency_still_is(self):
        louisiana = [self.katrina("EM-3212", "HURRICANE KATRINA")]
        missing, compared = MODULE.federal_without_state(louisiana, [], 2003)
        self.assertEqual(([row["id"] for row in missing], compared), (["EM-3212"], 1))

    def test_an_evacuation_emergency_matches_only_an_order_about_that_storm(self):
        hosting = [self.katrina("EM-3240", "HURRICANE KATRINA EVACUATION")]
        flood = action("VA-WARNER-EO-98-2005", "2005-09-12")   # Ophelia, flooding and wind
        self.assertIsNone(MODULE.find_federal_match(flood, hosting))
        relief = dict(action("NE-EO-05-5", "2005-09-02"),
                      title="Emergency relief for damage caused by Hurricane Katrina")
        self.assertEqual(MODULE.find_federal_match(relief, hosting)["id"], "EM-3240")

    def test_the_storms_own_emergency_matches_any_order_near_it(self):
        flood = action("LA-1", "2005-09-10")
        self.assertEqual(MODULE.find_federal_match(flood, [self.katrina("EM-3212", "HURRICANE KATRINA")])["id"],
                         "EM-3212")


class StructureFireTests(unittest.TestCase):
    """A city or building fire is not a weather declaration."""

    def fire(self, identifier, title, begin="1999-12-03"):
        row = federal(identifier, begin, begin, "EM", "Fire")
        row["title"] = title
        return row

    def test_structure_fires_are_neither_gaps_nor_matches(self):
        for title in ("WAREHOUSE FIRE.", "URBAN FIRE", "FIRE (CITY OF CHELSEA)", "FIRES AND EXPLOSIONS"):
            row = self.fire("EM-1", title)
            self.assertEqual(MODULE.federal_without_state([row], [], 1970), ([], 0), title)
            self.assertIsNone(MODULE.find_federal_match(action("A", "1999-12-05"), [row]), title)

    def test_wildfires_still_count(self):
        for title in ("WILDFIRES, FLOODING, AND MUDSLIDES", "FIRE", "BUNKER FIRE"):
            row = self.fire("DR-2", title)
            self.assertEqual(len(MODULE.federal_without_state([row], [], 1970)[0]), 1, title)
            self.assertEqual(MODULE.find_federal_match(action("A", "1999-12-05"), [row])["id"], "DR-2", title)


class ExtendedEmergencyTests(unittest.TestCase):
    """A FEMA declaration that falls while a later order keeps a state declaration in force is covered."""

    REL_FIELDS = ["source_order_id", "target_order_id", "relationship_type"]
    ACT_FIELDS = ["declaration_id", "date_signed"]

    def folder(self, tmp, links, dates):
        folder = Path(tmp)
        write(folder / "mo_order_relationships.csv",
              [dict(zip(self.REL_FIELDS, link)) for link in links], self.REL_FIELDS)
        write(folder / "mo_emergency_actions_all.csv",
              [{"declaration_id": k, "date_signed": v} for k, v in dates.items()], self.ACT_FIELDS)
        return folder

    # Missouri 2025: 25-19 declared March 14; 25-22 extends it; 25-23 extends 25-22.
    LINKS = [("MO-EO-25-22", "MO-EO-25-19", "explicit_order_citation"),
             ("MO-EO-25-23", "MO-EO-25-22", "extends"),
             ("MO-EO-25-30", "MO-EO-25-19", "terminates"),
             ("MO-EO-25-40", "MO-EO-25-99", "extends")]
    DATES = {"MO-EO-25-19": "2025-03-14", "MO-EO-25-22": "2025-04-14", "MO-EO-25-23": "2025-05-13",
             "MO-EO-25-30": "2025-08-31", "MO-EO-25-40": "2025-05-14", "MO-EO-25-99": "2025-05-01"}

    def test_a_chain_of_follow_on_orders_leads_back_to_the_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders = MODULE.extension_orders(self.folder(tmp, self.LINKS, self.DATES),
                                             [action("MO-EO-25-19", "2025-03-14")])
        self.assertEqual([(o["order"], o["declaration"]) for o in orders],
                         [("MO-EO-25-22", "MO-EO-25-19"), ("MO-EO-25-23", "MO-EO-25-19")])

    def test_a_termination_or_an_order_for_another_emergency_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders = MODULE.extension_orders(self.folder(tmp, self.LINKS, self.DATES),
                                             [action("MO-EO-25-19", "2025-03-14")])
        self.assertNotIn("MO-EO-25-30", [o["order"] for o in orders])   # terminates
        self.assertNotIn("MO-EO-25-40", [o["order"] for o in orders])   # extends an order not on the page

    def test_a_storm_during_the_extension_is_covered_and_named(self):
        storm = federal("DR-4877", "2025-05-16", "2025-05-16", incident="Severe Storm")
        later = federal("DR-4999", "2025-09-20", "2025-09-21", incident="Flood")
        with tempfile.TemporaryDirectory() as tmp:
            orders = MODULE.extension_orders(self.folder(tmp, self.LINKS, self.DATES),
                                             [action("MO-EO-25-19", "2025-03-14")])
        missing, compared = MODULE.federal_without_state([storm, later], [action("MO-EO-25-19", "2025-03-14")], 2000)
        self.assertEqual(([row["id"] for row in missing], compared), (["DR-4999", "DR-4877"], 2))
        remaining, covered = MODULE.covered_by_extension(missing, orders)
        self.assertEqual([row["id"] for row in remaining], ["DR-4999"])
        self.assertEqual(covered, [{"id": "DR-4877", "order": "MO-EO-25-23", "order_date": "2025-05-13",
                                    "declaration": "MO-EO-25-19"}])
        page = text(MODULE.federal_gap_section("Missouri", remaining, compared, 2000, covered))
        self.assertIn("1 more FEMA declaration fell while a state emergency declared on this page was kept "
                      "in force by a later order", page)
        self.assertIn("DR-4877 (order MO-EO-25-23 of 2025-05-13, continuing MO-EO-25-19)", page)

    def test_with_no_gaps_left_the_page_still_names_them(self):
        covered = [{"id": "DR-4877", "order": "MO-EO-25-23", "order_date": "2025-05-13",
                    "declaration": "MO-EO-25-19"}]
        page = text(MODULE.federal_gap_section("Missouri", [], 3, 2000, covered))
        self.assertIn("or fell while one was kept in force", page)
        self.assertIn("DR-4877 (order MO-EO-25-23", page)
        self.assertNotIn("kept in force", text(MODULE.federal_gap_section("Missouri", [], 3, 2000)))

    def test_no_relationship_file_covers_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(MODULE.extension_orders(Path(tmp), [action("A", "2025-01-01")]), [])


class FederalWithoutStateTests(unittest.TestCase):
    """FEMA weather declarations with no state declaration on the page."""

    FEDERAL = [
        federal("DR-1", "2020-05-01", "2020-05-05"),                       # state action 5 days after
        federal("EM-2", "2021-08-01", "2021-08-03", "EM", "Hurricane"),    # nothing near
        federal("FM-3", "2021-09-01", "2021-09-30", "FM", "Fire"),         # fire grants need no declaration
        federal("DR-4", "2021-10-01", "2021-10-02", tribal=True),          # requested by a tribe
        federal("EM-5", "2021-11-01", "2021-11-30", "EM", "Biological"),   # not weather
        federal("DR-6", "2018-03-01", "2018-03-05"),                       # before the page's coverage
        federal("DR-7", "2022-01-10", "", "DR", "Snowstorm"),              # no end: 23 days is too far
    ]
    ACTIONS = [action("A-1", "2020-05-10"), action("A-2", "2022-02-02"), action("A-3", "2018-03-02")]

    def test_only_weather_major_disasters_and_emergencies_in_coverage_are_compared(self):
        missing, compared = MODULE.federal_without_state(self.FEDERAL, self.ACTIONS, 2019)
        self.assertEqual([row["id"] for row in missing], ["DR-7", "EM-2"])   # newest first
        self.assertEqual(compared, 3)                                        # DR-1, EM-2, DR-7

    def test_the_window_is_the_crosswalks(self):
        window = MODULE.FEDERAL_MATCH_WINDOW_DAYS
        flood = [federal("DR-1", "2020-05-01", "2020-05-05")]
        edge = [action("A", f"2020-05-{5 + window:02d}")]
        past = [action("A", f"2020-05-{6 + window:02d}")]
        self.assertEqual(MODULE.federal_without_state(flood, edge, 2019), ([], 1))
        self.assertEqual(len(MODULE.federal_without_state(flood, past, 2019)[0]), 1)
        # find_federal_match() pairs the same two records from the other side.
        self.assertIsNotNone(MODULE.find_federal_match(edge[0], flood))
        self.assertIsNone(MODULE.find_federal_match(past[0], flood))

    def test_an_unknown_coverage_start_compares_nothing(self):
        self.assertEqual(MODULE.federal_without_state(self.FEDERAL, [], None), ([], 0))

    def test_the_start_year_is_the_pages_since_badge(self):
        self.assertEqual(MODULE.coverage_start_year(
            "LA", "2016-present official State Register web indexes; 2000-2015 gap disclosed"), 2016)
        self.assertEqual(MODULE.coverage_start_year(
            "MA", "1941-present Governor archive"), MODULE.EARLIEST_ACTION_YEAR)
        self.assertEqual(MODULE.coverage_start_year("VT", "2017-present structured archive"), 2011)
        self.assertIsNone(MODULE.coverage_start_year("NJ", "Adapter available; no cached action file found"))

    def render(self, gaps, compared, start=2019):
        return MODULE.render_state_page(STATE, [], [], [], [], METRICS, "Fixture coverage",
                                        federal_gaps=gaps, federal_compared=compared,
                                        coverage_start=start)

    def test_the_page_lists_them(self):
        missing, compared = MODULE.federal_without_state(self.FEDERAL, self.ACTIONS, 2019)
        page = self.render(missing, compared)
        words = text(page)
        self.assertIn("FEMA declarations with no state declaration on this page", words)
        self.assertIn("2 of 3 since 2019", words)
        self.assertIn('id="federal-gap-table"', page)
        self.assertIn("DR-7", words)
        self.assertNotIn("FM-3", words)

    def test_none_missing_and_none_to_compare_say_so(self):
        self.assertIn("Every one of the 3 major disaster and emergency declarations",
                      text(self.render([], 3)))
        self.assertIn("FEMA made no major disaster or emergency declarations", text(self.render([], 0)))
        self.assertNotIn("federal-gap-table", self.render([], 3))
        self.assertNotIn("no state declaration on this page", self.render([], 0, start=None))


class VisitorNoteTests(unittest.TestCase):
    def test_the_coverage_note_shows_no_file_names(self):
        note = ("2017-present structured Governor archive; 2002-2015 emergency orders added by hand, "
                "kept in manual_declarations.csv; plus 1 weather declaration from FMCSA's archive")
        page = MODULE.render_state_page(STATE, [], [], [], [], METRICS, note)
        self.assertNotIn("manual_declarations.csv", page)
        self.assertIn("added by hand; plus 1 weather declaration", text(page))

    def test_the_api_file_carries_the_breakdown_and_the_federal_gaps(self):
        gaps = [federal("EM-2", "2021-08-01", "2021-08-03", "EM", "Hurricane")]
        summary = {"coverage": "note", "sources": {"state_archive": 1},
                   "federal_without_state": {"since": 2019, "compared": 3, "count": 1, "ids": ["EM-2"]}}
        payload = MODULE.api_payload(STATE, summary, [], [], gaps)
        self.assertEqual(payload["sources"], {"state_archive": 1})
        self.assertEqual(payload["federal_without_state"]["since"], 2019)
        self.assertEqual(payload["federal_without_state"]["compared"], 3)
        self.assertEqual([row["id"] for row in payload["federal_without_state"]["declarations"]], ["EM-2"])


if __name__ == "__main__":
    unittest.main()
