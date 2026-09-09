import csv
import tempfile
import unittest

import ct_eo_scraper as ct


EO_FIXTURE = """
<div id="resultsAnnounced">Page 1 of 1</div>
<article class="new-cg-c-press-rel__item"><div class="new-cg-c-press-rel__date">8/5/2020</div>
<a class="cg-c-button-link" href="/eo-7.pdf">Executive Order No. 7A</a>
<div class="new-cg-c-press-rel__desc">Extends Executive Order No. 7 due to Tropical Storm Isaias</div></article>
"""
EMERGENCY_FIXTURE = """
<table><tr><th>Declaration Date</th><th>Governor</th><th>Reason for Declaration</th></tr>
<tr><td>August 5, 2020</td><td>Lamont</td><td><a href="/isaias.pdf">Tropical Storm Isaias</a></td></tr></table>
"""


class ConnecticutScraperTests(unittest.TestCase):
    def test_parse_executive_order(self):
        action = ct.parse_executive_order_page(EO_FIXTURE)[0]
        self.assertEqual(action.stable_id, "CT-NEDLAMONT-EO-7A")
        self.assertEqual(action.date_issued, "2020-08-05")
        self.assertEqual(ct.classify_action(action), "extension")

    def test_parse_civil_preparedness_declaration(self):
        action = ct.parse_emergency_page(EMERGENCY_FIXTURE)[0]
        self.assertEqual(action.stable_id, "CT-PROC-2020-08-05")
        self.assertEqual(action.governor, "Ned Lamont")
        self.assertEqual(ct.classify_action(action), "declaration")
        self.assertTrue(ct.is_weather_related(action))

    def test_join_excludes_extension(self):
        declaration = ct.parse_emergency_page(EMERGENCY_FIXTURE)[0]
        declaration.action_type = "declaration"; declaration.weather_related = True
        extension = ct.parse_executive_order_page(EO_FIXTURE)[0]
        extension.action_type = "extension"; extension.weather_related = True
        with tempfile.TemporaryDirectory() as tmp:
            paths = [f"{tmp}/{name}" for name in ("a.csv", "r.csv", "j.csv")]
            ct.write_outputs([declaration, extension], [], *paths)
            with open(paths[2], newline="") as handle: rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), ct.JOIN_FIELDS)

    def test_order_mentioning_declaration_is_not_original(self):
        action = ct.CTAction("executive_order", "7MMM", "Takes emergency actions in response to COVID-19", "2020-08-09", "Ned Lamont", "x", "x", "test")
        action.document_text = "Pursuant to the civil preparedness declaration for COVID-19 and prior storm orders."
        self.assertNotEqual(ct.classify_action(action), "declaration")


if __name__ == "__main__": unittest.main()
