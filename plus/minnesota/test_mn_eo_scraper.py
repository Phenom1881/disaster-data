import unittest
from mn_eo_scraper import Action, blocked, parse_detail, parse_list


class MinnesotaScraperTests(unittest.TestCase):
    def test_parses_official_document_list_links(self):
        page='<ul><li><a href="/governor/newsroom/executive-orders/?id=1055-671424">Executive Order 25-03</a></li></ul>'
        row=parse_list(page)[0]
        self.assertEqual(row.eo_number,"25-03"); self.assertIn("1055-671424",row.url)

    def test_parses_detail_and_weather_declaration(self):
        page='<main><h2>Executive Order 25-03</h2><p>Declaring a Peacetime Emergency and Providing National Guard Assistance in Response to a Severe Winter Storm</p><p>Last Modified: March 5, 2025</p></main>'
        row=parse_detail(Action("25-03","","","https://example.gov"),page)
        self.assertEqual(row.action_type,"declaration"); self.assertEqual(row.hazard,"winter"); self.assertEqual(row.date_signed,"2025-03-05")

    def test_detects_radware_instead_of_returning_empty(self):
        self.assertTrue(blocked("<title>Radware Bot Manager Captcha</title>","https://validate.perfdrive.com/"))

    def test_reviewed_generic_heading_keeps_source_hazard(self):
        page='<main><h2>Executive Order 20-108</h2><p>Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists</p><p>Last Modified: December 24, 2020</p></main>'
        row=parse_detail(Action("20-108","","","https://example.gov"),page)
        self.assertEqual(row.action_type,"declaration"); self.assertEqual(row.hazard,"winter")

if __name__=="__main__": unittest.main()
