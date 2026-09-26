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

    def test_extension_uses_its_own_signing_date_not_the_original_emergency(self):
        # Every 2020-2021 COVID extension used to come out as 2020-03-13.
        text = ("Twenty-first Extension of the State of Emergency declared on March 13, 2020 in "
                "Executive Order 2020-04 ... Given under my hand and seal at the Executive Chambers "
                "in Concord, this 9th day of April, in the year of Our Lord, two thousand twenty-one, "
                "and the independence of the United States of America, two hundred and forty-five.")
        self.assertEqual(nh.date_in_text(text, 2021), "2021-04-09")

    def test_rescission_is_not_dated_by_the_order_it_rescinds(self):
        text = "An order rescinding Executive Order 74-3, issued April 29, 1974. Given this 5th day of January, 2023."
        self.assertEqual(nh.date_in_text(text, 2023), "2023-01-05")

    def test_plain_dates_prefer_the_orders_own_year(self):
        text = "This order extends the order of March 13, 2020. Signed April 9, 2021."
        self.assertEqual(nh.date_in_text(text, 2021), "2021-04-09")
        self.assertEqual(nh.date_in_text("Signed June 2, 2019.", None), "2019-06-02")
        self.assertIsNone(nh.date_in_text("No date here.", 2019))

    def test_year_split_across_lines_and_misread_years(self):
        text = "Given under my hand this 13th day of March, in the year of Our Lord, two thousand and twen-\nty."
        self.assertEqual(nh.date_in_text(text, 2020), "2020-03-13")
        self.assertEqual(nh.date_in_text("Given this 13th day of March, 1920.", 2020), "2020-03-13")

    def test_a_later_until_clause_is_not_the_signing_date(self):
        text = ("Given under my hand this 5th day of June, 2020. This order remains in effect until the "
                "30th day of November, 2020.")
        self.assertEqual(nh.date_in_text(text, 2020), "2020-06-05")

    def test_year_words(self):
        self.assertEqual(nh.words_to_year("two thousand and three"), 2003)
        self.assertEqual(nh.words_to_year("two thousand twenty-one"), 2021)
        self.assertEqual(nh.words_to_year("two thousand and twenty, and"), 2020)
        self.assertEqual(nh.words_to_year("nineteen hundred and ninety-nine"), 1999)
        self.assertEqual(nh.words_to_year("two thousand"), 2000)
        self.assertIsNone(nh.words_to_year("the independence"))


if __name__ == "__main__": unittest.main()
