"""
Unit tests for sd_eo_scraper.py. These test the pure parsing/classification
logic against saved-in-code HTML fixtures - they do not hit the live network.
"""
import contextlib
import csv
import io
import os
import tempfile
import unittest

import sd_eo_scraper as scraper

HERE = os.path.dirname(os.path.abspath(__file__))

SAMPLE_HTML = """
<html><body>
<h2>2024 Executive Orders</h2>
<table>
<tr><th>Order Number</th><th>Dated Filed</th><th>Title</th></tr>
<tr><td>2024-01</td><td>20240109</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-01.PDF">Bureau of Human Resources and Administration Reorganization</a></td></tr>
<tr><td>2024-02</td><td>20240112</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-02.PDF">State of Emergency - Transportation Exemptions</a></td></tr>
<tr><td>2024-04</td><td>20240622</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-04.PDF">State of Emergency - Flood Relief</a></td></tr>
<tr><td>2024-06</td><td>20240726</td>
    <td><a href="/general-information/executive-actions/executive-orders/assets/2024 Executive Orders/2024-06.pdf">Disaster Declaration</a></td></tr>
</table>
</body></html>
"""

# The registry page as served on 2026-10-29, cut down: one year table, the
# "Search for Prior Years Orders" form with its generated box names, and the
# empty results block a plain GET returns.
FORM_PAGE = """
<html><body>
<form method="post" action="./Default.aspx" id="form1">
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="aoXeZyAcaHCk" />
<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="DE4F22F7" />
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="5O0DX4hTmXhp" />
<h3><em>2020 Executive Orders</em></h3>
<table><tbody>
<tr><td>2020-27</td><td>20200528</td>
<td><a href="/general-information/executive-actions/executive-orders/assets/2020-27.PDF" target="_blank">Day County Emergency Declaration</a></td></tr>
</tbody></table>
<h2 class="blue_box_header"><u>Search for Prior Years Orders</u></h2>
<p>&nbsp;</p>
<div class="fbox">
<span class="title">Year Filed:  </span> <input name="FD_A723A07D" type="text" id="FD_A723A07D" />
</div>
<div class="fbox">
<span class="title">Title:  </span> <input name="FD_7710F879" type="text" id="FD_7710F879" />
</div>
<input type="submit" name="cmdSubmit" value="Search" id="cmdSubmit" />
<span id="lbl_SearchInfo"></span>
</form>
</body></html>
"""

RESULT_ROWS = {
    2019: """<tr><td>&nbsp;2019-04</td><td>&nbsp;20190315</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=20190315-2123-1189-1761-d689c4fec9ad">Severe Winter Storm</a></td></tr>
<tr><td>&nbsp;2019-05</td><td>&nbsp;20190319</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=20190319-2131-5610-6812-4117182b4a37">Recreational Use &amp; Navigation Prohibited</a></td></tr>""",
    2013: """<tr><td>&nbsp;2013-06</td><td>&nbsp;20130506</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=f9dbac87-2bae-44c0-96ef-b437b4df1562">Disaster Declaration</a></td></tr>
<tr><td>&nbsp;2013-05</td><td>&nbsp;20130312</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=c6b37497-c911-479b-820c-ebbed93d4512">State of Emergency</a></td></tr>
<tr><td>&nbsp;2013-06</td><td>&nbsp;20130506</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=20180216-2037-1513-0116-b350688cf0d6">Disaster Declaration</a></td></tr>""",
    2000: """<tr><td>&nbsp;2000-08</td><td>&nbsp;20001214</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=65c921fe-2127-4f5e-85ae-2600c5e553cc">ext hours/carriers</a></td></tr>
<tr><td>&nbsp;20000627</td><td>&nbsp;20000627</td><td><a href="Document.aspx?CabId=523E2A2A&DocGuid=ee2ec975-70ad-4446-97d7-6f4a500607b1">Order Approving an Issue of Bo</a></td></tr>""",
}


def results_page(year):
    """FORM_PAGE as the registry answers a search: the year tables again,
    then the results inside lbl_SearchInfo."""
    rows = RESULT_ROWS.get(year, "")
    table = ('<table><tr><th>Order Number</th><th>Date Filed</th><th>Title</th></tr>'
             + rows + '</table>')
    return FORM_PAGE.replace('<span id="lbl_SearchInfo"></span>',
                             '<span id="lbl_SearchInfo">' + table + '</span>')


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


ERROR_PAGE = "<html><head><title>South Dakota Secretary of State</title></head><body><h1>An Error Occurred</h1></body></html>"


class FakeSession:
    """Answers the GET with FORM_PAGE and each POST with that year's
    results. A year in fail_years raises like a network error every time;
    a year in flaky_years gets the registry's error page the first time."""

    def __init__(self, fail_years=(), flaky_years=()):
        self.posts = []
        self.fail_years = set(fail_years)
        self.flaky_years = set(flaky_years)

    def get(self, url, **kwargs):
        return FakeResponse(FORM_PAGE)

    def post(self, url, data=None, **kwargs):
        self.posts.append(dict(data))
        year = int(data["FD_A723A07D"])
        if year in self.fail_years:
            raise scraper.requests.ConnectionError("connection reset")
        if year in self.flaky_years:
            self.flaky_years.discard(year)
            return FakeResponse(ERROR_PAGE)
        return FakeResponse(results_page(year))


class ParseOrdersTests(unittest.TestCase):
    def test_parses_all_rows(self):
        orders = scraper.parse_orders(SAMPLE_HTML)
        self.assertEqual(len(orders), 4)
        self.assertEqual(orders[0]["eo_number"], "2024-01")
        self.assertEqual(orders[0]["date_filed"], "20240109")

    def test_url_is_absolute(self):
        orders = scraper.parse_orders(SAMPLE_HTML)
        for o in orders:
            self.assertTrue(o["url"].startswith("https://sdsos.gov/"))

    def test_relative_document_link_is_made_absolute(self):
        # The live registry links "../assets/<year> Executive Orders/<n>.pdf".
        html = ('<table><tr><td>2026-01</td><td>20260107</td><td>'
                '<a href="../assets/2026 Executive Orders/2026-01.pdf">Windstorm Declaration</a>'
                '</td></tr></table>')
        self.assertEqual(scraper.parse_orders(html)[0]["url"],
                         "https://sdsos.gov/general-information/executive-actions/"
                         "executive-orders/assets/2026%20Executive%20Orders/2026-01.pdf")

    def test_empty_page_is_described_for_the_log(self):
        note = scraper.describe_page("<html><head><title>Access Denied</title></head></html>")
        self.assertIn("Access Denied", note)
        self.assertIn("0 table(s)", note)


class PriorYearsSearchTests(unittest.TestCase):
    def test_form_fields_are_found_by_their_labels(self):
        fields, year_field = scraper.search_form_fields(FORM_PAGE)
        self.assertEqual(year_field, "FD_A723A07D")
        self.assertEqual(fields, {
            "__VIEWSTATE": "aoXeZyAcaHCk", "__VIEWSTATEGENERATOR": "DE4F22F7",
            "__EVENTVALIDATION": "5O0DX4hTmXhp", "FD_7710F879": "", "cmdSubmit": "Search"})

    def test_renamed_boxes_are_still_found(self):
        page = FORM_PAGE.replace("FD_A723A07D", "FD_0B1C2D3E").replace("FD_7710F879", "FD_99999999")
        fields, year_field = scraper.search_form_fields(page)
        self.assertEqual(year_field, "FD_0B1C2D3E")
        self.assertIn("FD_99999999", fields)

    def test_page_without_the_form_is_an_error(self):
        with self.assertRaises(ValueError):
            scraper.search_form_fields(SAMPLE_HTML)
        with self.assertRaises(ValueError):
            scraper.search_form_fields(FORM_PAGE.replace("Year Filed:", "Date:"))

    def test_results_are_read_from_the_search_block_only(self):
        orders = scraper.parse_search_results(results_page(2019))
        self.assertEqual([o["eo_number"] for o in orders], ["2019-04", "2019-05"])
        self.assertEqual(orders[0], {
            "eo_number": "2019-04", "date_filed": "20190315", "title": "Severe Winter Storm",
            "url": "https://sdsos.gov/general-information/executive-actions/executive-orders/"
                   "search/Document.aspx?CabId=523E2A2A&DocGuid=20190315-2123-1189-1761-d689c4fec9ad"})
        self.assertEqual(orders[1]["title"], "Recreational Use & Navigation Prohibited")

    def test_rows_without_an_order_number_are_skipped(self):
        orders = scraper.parse_search_results(results_page(2000))
        self.assertEqual([o["eo_number"] for o in orders], ["2000-08"])

    def test_a_page_without_the_results_block_is_an_error(self):
        with self.assertRaises(ValueError):
            scraper.parse_search_results(SAMPLE_HTML)

    def test_collect_searches_each_prior_year_newest_first(self):
        session = FakeSession()
        orders = scraper.collect_orders(include_prior_years=True, session=session, pause=0)
        years = [int(p["FD_A723A07D"]) for p in session.posts]
        self.assertEqual(years, list(range(2019, 1999, -1)))
        for post in session.posts:
            self.assertEqual(post["__VIEWSTATE"], "aoXeZyAcaHCk")
            self.assertEqual(post["__EVENTVALIDATION"], "5O0DX4hTmXhp")
            self.assertEqual(post["cmdSubmit"], "Search")
        self.assertEqual([o["eo_number"] for o in orders],
                         ["2020-27", "2019-04", "2019-05", "2013-06", "2013-05", "2000-08"])

    def test_a_failed_year_is_reported_and_the_rest_kept(self):
        session = FakeSession(fail_years={2013})
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            orders = scraper.collect_orders(include_prior_years=True, session=session, pause=0)
        self.assertIn("prior-year search failed for 2013", log.getvalue())
        self.assertEqual([int(p["FD_A723A07D"]) for p in session.posts].count(2013),
                         1 + len(scraper.PRIOR_YEAR_RETRY_WAITS))
        self.assertEqual([o["eo_number"] for o in orders], ["2020-27", "2019-04", "2019-05", "2000-08"])

    def test_a_year_that_fails_once_is_tried_again(self):
        session = FakeSession(flaky_years={2013})
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            orders = scraper.collect_orders(include_prior_years=True, session=session, pause=0)
        self.assertEqual([int(p["FD_A723A07D"]) for p in session.posts].count(2013), 2)
        self.assertIn("2013-05", [o["eo_number"] for o in orders])
        self.assertEqual(log.getvalue(), "")

    def test_without_the_flag_only_the_page_is_read(self):
        session = FakeSession()
        orders = scraper.collect_orders(session=session, pause=0)
        self.assertEqual(session.posts, [])
        self.assertEqual([o["eo_number"] for o in orders], ["2020-27"])


class ClassificationTests(unittest.TestCase):
    def test_flood_relief_is_declaration(self):
        self.assertTrue(scraper.is_declaration("State of Emergency - Flood Relief"))

    def test_disaster_declaration_is_declaration(self):
        self.assertTrue(scraper.is_declaration("Disaster Declaration"))

    def test_transportation_exemptions_excluded(self):
        # Regression: the recurring standing motor-carrier hours mechanism
        # must never be treated as a storm-specific declaration.
        self.assertFalse(scraper.is_declaration("State of Emergency - Transportation Exemptions"))

    def test_reorganization_excluded(self):
        self.assertFalse(scraper.is_declaration("Bureau of Human Resources and Administration Reorganization"))

    def test_covid_excluded(self):
        self.assertFalse(scraper.is_declaration("COVID-19: Statewide Disaster Declaration"))

    def test_older_declaration_titles(self):
        # Registry titles from 2005-2016, checked against the signed orders.
        for title in ("Blizzard-Emergency Management", "Emergency Management Law 7/200",
                      "Extreme Weather ER", "State of Emergency", "Meade County Disaster",
                      "West River Drought", "DisasterWinter Storm", "Emergency West SD",
                      "May 5th rain & tornado disaste"):
            self.assertTrue(scraper.is_declaration(title), title)

    def test_older_operational_and_other_titles(self):
        for title in ("drought/overwidth vehicles", "Drought conditions-DOT overwei",
                      "Drought conditions - waive fee", "Blizzard-waive permits #1",
                      "Blizzard-transport fuels #2", "Blizzard-License Plate extensi",
                      "BH Nat Forest-Wildland Fire Su", "2017 Fire Season", "Wildland Fire Suppression",
                      "SD Division of Wildland Fire", "South Dakota Wildland Fire Division",
                      "Rangeland Firefighting Functions", "SEATS-prevent prairie fires",
                      "Hurri Katrina-Disaster Revenue", "Iowa blizzard-SD Nat Guard",
                      "Lake Mitchell-no boating-flood", "Propane Emergency", "Influenza Emergency",
                      "SD Emergency Operations Plan", "Wind Power/Energy Task"):
            self.assertFalse(scraper.is_declaration(title), title)


class DateAndGovernorTests(unittest.TestCase):
    def test_iso_date_conversion(self):
        self.assertEqual(scraper.to_iso_date("20240622"), "2024-06-22")

    def test_iso_date_bad_input(self):
        self.assertEqual(scraper.to_iso_date("not-a-date"), "")
        self.assertEqual(scraper.to_iso_date("20051313"), "")

    def test_governor_on_each_side_of_a_change(self):
        cases = {"2000-06-27": "Janklow", "2003-01-06": "Janklow", "2003-01-07": "Rounds",
                 "2011-01-07": "Rounds", "2011-01-08": "Daugaard", "2019-01-04": "Daugaard",
                 "2019-01-05": "Noem", "2023-08-08": "Noem", "2025-01-24": "Noem",
                 "2025-01-25": "Rhoden", "2026-04-13": "Rhoden", "1990-01-01": ""}
        for day, name in cases.items():
            self.assertEqual(scraper.governor_on(day), name, day)


class WriteCsvTests(unittest.TestCase):
    @staticmethod
    def write(orders):
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "join.csv")
            declarations = scraper.write_csv(orders, os.path.join(tmp, "actions.csv"),
                                             os.path.join(tmp, "rel.csv"), join_out)
            with open(join_out, newline="", encoding="utf-8") as f:
                return declarations, list(csv.DictReader(f))

    def test_only_declarations_written_to_join_csv(self):
        declarations, rows = self.write(scraper.parse_orders(SAMPLE_HTML))
        # Only 2024-04 and 2024-06 are genuine declarations in the fixture.
        self.assertEqual(len(declarations), 2)
        self.assertEqual({d["declaration_id"] for d in declarations}, {"SD-EO-2024-04", "SD-EO-2024-06"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["governor"], "Noem")

    def test_known_filed_date_typos_are_corrected(self):
        orders = [{"eo_number": "2013-05", "date_filed": "20130312", "title": "State of Emergency", "url": ""},
                  {"eo_number": "2010-42", "date_filed": "20101130", "title": "Winter Storm", "url": ""},
                  {"eo_number": "2006-09", "date_filed": "20060621", "title": "Drought Emergency", "url": ""},
                  {"eo_number": "2013-08", "date_filed": "20130531", "title": "Rainfall Emergency", "url": ""}]
        _, rows = self.write(orders)
        self.assertEqual({r["eo_number"]: r["date_signed"] for r in rows},
                         {"2013-05": "2013-04-12", "2010-42": "2010-12-29",
                          "2006-09": "2006-07-21", "2013-08": "2013-05-31"})
        # A corrected registry entry is taken as it stands.
        _, rows = self.write([dict(orders[0], date_filed="20130413")])
        self.assertEqual(rows[0]["date_signed"], "2013-04-13")

    def test_ids_stay_unique_and_unreadable_dates_are_skipped(self):
        orders = [{"eo_number": "2010-50", "date_filed": "20100101", "title": "Flooding Emergency", "url": ""},
                  {"eo_number": "2010-50", "date_filed": "20100102", "title": "Storm Emergency", "url": ""},
                  {"eo_number": "2005-12", "date_filed": "20051313", "title": "Drought Emergency", "url": ""}]
        _, rows = self.write(orders)
        self.assertEqual([r["declaration_id"] for r in rows], ["SD-EO-2010-50", "SD-EO-2010-50-2"])


class CommittedFilesTests(unittest.TestCase):
    """The committed join file is what write_csv makes of the committed
    action file, so a refresh with the same registry changes nothing."""

    @staticmethod
    def read(name):
        with open(os.path.join(HERE, name), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_join_file_matches_the_rules(self):
        orders = self.read("sd_emergency_actions_all.csv")
        with tempfile.TemporaryDirectory() as tmp:
            join_out = os.path.join(tmp, "join.csv")
            scraper.write_csv(orders, os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join_out)
            with open(join_out, newline="", encoding="utf-8") as f:
                rebuilt = list(csv.DictReader(f))
        self.assertEqual(rebuilt, self.read("declarations_for_join.csv"))

    def test_action_file_reaches_back_to_2000(self):
        orders = self.read("sd_emergency_actions_all.csv")
        years = {o["eo_number"][:4] for o in orders}
        self.assertTrue({str(y) for y in range(2000, 2027)} <= years)
        self.assertEqual(len({(o["eo_number"], o["title"]) for o in orders}), len(orders))


class ReviewedOverridesTests(unittest.TestCase):
    """Each 2000-2019 declaration's hazard was read from its signed order,
    whose scanned copy is the row's source."""
    CATEGORIES = {"drought", "fire", "flood", "tropical", "winter", "severe_storm",
                  "wind", "heat", "storm_general", "water"}

    @staticmethod
    def read(name):
        with open(os.path.join(HERE, name), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_every_older_declaration_was_reviewed_against_its_order(self):
        join = {r["declaration_id"]: r for r in self.read("declarations_for_join.csv")}
        overrides = {r["declaration_id"]: r for r in self.read("hazard_overrides.csv")}
        older = [i for i, r in join.items() if r["date_signed"] < "2020"]
        self.assertEqual(len(older), 64)
        for declaration_id in older:
            row = overrides.get(declaration_id)
            self.assertIsNotNone(row, declaration_id)
            self.assertEqual(row["source_url"], join[declaration_id]["archive_record_url"], declaration_id)
            self.assertRegex(row["review_note"], r"(?i)(dated|filed) [A-Z][a-z]+ \d{1,2}, (19|20)\d\d",
                             declaration_id)

    def test_override_values_and_event_dates(self):
        join = {r["declaration_id"]: r for r in self.read("declarations_for_join.csv")}
        for row in self.read("hazard_overrides.csv"):
            value = row["hazard_category_override"]
            if value != "exclude":
                self.assertTrue(set(value.split(",")) <= self.CATEGORIES, row["declaration_id"])
            if row["event_date"]:
                self.assertRegex(row["event_date"], r"^20\d\d-\d\d-\d\d$")
                self.assertLess(row["event_date"], join[row["declaration_id"]]["date_signed"])

    def test_a_registry_title_that_misdescribes_the_order_is_excluded(self):
        overrides = {r["declaration_id"]: r for r in self.read("hazard_overrides.csv")}
        # Filed as "Weather State of Emergency"; the order rescinds a no-wake zone.
        self.assertEqual(overrides["SD-EO-2010-29"]["hazard_category_override"], "exclude")


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest(self):
        """A refresh (build-plus.py --collect) shows the note collect()
        returns, and a build without collection shows the manifest's."""
        import importlib.util
        import json
        import subprocess
        from pathlib import Path
        from unittest import mock
        here = Path(HERE)
        spec = importlib.util.spec_from_file_location("south_dakota_adapter", here / "south_dakota.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(adapter.subprocess, "run", return_value=done) as run:
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        self.assertIn("--include-prior-years", run.call_args.args[0])
        manifest = json.loads((here.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        states = manifest["states"] if isinstance(manifest, dict) else manifest
        self.assertEqual(note, next(st["coverage_note"] for st in states if st["abbreviation"] == "SD"))
        self.assertTrue(note.startswith("2000-present"))


if __name__ == "__main__":
    unittest.main()
