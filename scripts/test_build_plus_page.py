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
