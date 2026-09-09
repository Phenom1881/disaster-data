import unittest

import me_eo_scraper as me


MILLS = """
<h3>FY 23/24</h3><ul><li><a href="/order.pdf">Executive Order 7: An Order Establishing a Commission</a> - May 6, 2024</li></ul>
"""
LEPAGE = """
<ul><li>August 26, 2011: <a href="/detail?id=1">State of Emergency Declaration</a></li>
<li>July 4, 2017: <a href="/detail?id=2">An Order Rescinding The Civil Preparedness Emergency Executive Order Of July 3, 2017</a></li></ul>
"""


class MaineTests(unittest.TestCase):
    def test_mills_fiscal_number_and_date(self):
        action = me.parse_mills_page(MILLS)[0]
        self.assertEqual(action.eo_number, "23/24-7")
        self.assertEqual(action.date_signed, "2024-05-06")

    def test_lepage_archive_date(self):
        actions = me.parse_lepage_page(LEPAGE)
        self.assertEqual(actions[0].date_signed, "2011-08-26")

    def test_generic_declaration_requires_document_hazard(self):
        action = me.parse_lepage_page(LEPAGE)[0]
        me.classify(action)
        self.assertFalse(action.weather_related)
        action.document_text = "Hurricane Irene is expected to bring damaging winds and flooding."
        me.classify(action)
        self.assertTrue(action.weather_related)

    def test_administrative_wind_title_does_not_leak(self):
        action = me.Action("3", "An Order Concluding the Maine Wind Advisory Commission", "2019-02-14", "Janet T. Mills", "x", "x", "test")
        me.classify(action)
        self.assertFalse(action.weather_related)

    def test_rescission_not_a_join_declaration(self):
        action = me.parse_lepage_page(LEPAGE)[1]
        me.classify(action)
        self.assertEqual(action.action_type, "termination")


if __name__ == "__main__":
    unittest.main()
