import unittest
from mi_eo_scraper import Action, classify, parse_search_results


class MichiganScraperTests(unittest.TestCase):
    def test_parses_and_normalizes_official_search_card(self):
        payload={"Results":[{"Url":"/whitmer/news/state-orders-and-directives/2025/03/31/executive-order-2025-2-declaration-of-state-of-emergency","Html":"<h3>Executive Order 2025-02: Declaration of State of Emergency</h3><span>March 31, 2025</span>"}]}
        row=parse_search_results(payload)[0]
        self.assertEqual(row.eo_number,"2025-2"); self.assertEqual(row.date_signed,"2025-03-31")

    def test_original_weather_declaration(self):
        row=classify(Action("2025-2","Executive Order 2025-2: Declaration of State of Emergency","2025-03-31","https://example.gov"),"Northern Michigan experienced severe ice accumulation after a winter storm.")
        self.assertEqual(row.action_type,"declaration"); self.assertEqual(row.hazard,"winter")

    def test_expansion_is_not_joinable_original(self):
        body="On August 25, 2023, I issued Executive Order 2023-7 declaring a state of emergency. These same storms also caused damage in additional counties."
        row=classify(Action("2023-8","Executive Order 2023-8: Declaration of State of Emergency","2023-08-28","https://example.gov"),body)
        self.assertEqual(row.action_type,"amendment"); self.assertEqual(row.related_order,"2023-7")

if __name__=="__main__": unittest.main()
