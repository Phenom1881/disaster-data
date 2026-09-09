import unittest

import nh_eo_scraper as nh


REGISTRY = """
<h2>Governor Margaret Wood Hassan Executive Orders - Archived</h2><table>
<tr><td><a href="/hassan-2015-1.pdf">2015-01</a></td><td>An Order Declaring a State of Emergency Due to Severe Winter Storm</td></tr>
<tr><td><a href="/hassan-2015-2.pdf">2015-02</a></td><td>An Order Declaring the State of Emergency Over</td></tr>
</table><h2>Governor Christopher Sununu Executive Orders - Archived</h2><table>
<tr><td><a href="/sununu-2020-04-17.pdf">2020-04 #17</a></td><td>Closure of non-essential businesses</td></tr>
</table>
"""


class NewHampshireTests(unittest.TestCase):
    def test_registry_numbers_and_governors(self):
        actions = nh.parse_registry(REGISTRY)
        self.assertEqual(actions[0].number, "2015-01"); self.assertEqual(actions[0].governor, "Margaret Wood Hassan")
        self.assertEqual(actions[2].stable_id, "NH-2020-04-EO-17")

    def test_original_and_termination(self):
        first, second, _ = nh.parse_registry(REGISTRY)
        nh.classify(first); nh.classify(second)
        self.assertEqual(first.action_type, "declaration"); self.assertTrue(first.weather_related)
        self.assertEqual(second.action_type, "termination")

    def test_generic_declaration_needs_direct_pdf_hazard(self):
        action = nh.Action("2014-06", "Declaration of State of Emergency", "Margaret Wood Hassan", "x")
        nh.classify(action); self.assertFalse(action.weather_related)
        action.document_text = "The severe storm caused flooding and damaging winds."
        nh.classify(action); self.assertTrue(action.weather_related)

    def test_flood_in_administrative_title_does_not_leak(self):
        action = nh.Action("2017-03", "Suspending physician licensing requirements due to flooding at a facility", "Christopher Sununu", "x")
        nh.classify(action); self.assertEqual(action.action_type, "administrative"); self.assertFalse(action.weather_related)

    def test_archival_signature_date_uses_order_year(self):
        text = "Given under my hand this 26th day of January, in the year of Our Lord, two thousand and fifteen."
        self.assertEqual(nh.date_in_text(text, 2015), "2015-01-26")


if __name__ == "__main__": unittest.main()
