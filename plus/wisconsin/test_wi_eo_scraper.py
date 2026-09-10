import json, unittest
from wi_eo_scraper import parse_archive


class WisconsinScraperTests(unittest.TestCase):
    def fixture(self, rows):
        return "<script>var WPQ1ListData = { \"Row\" :\n"+json.dumps(rows)+"};</script>"

    def test_parses_embedded_sharepoint_rows(self):
        page=self.fixture([{"Title2":"Gov. Evers Executive Order #256: Declaring a State of Emergency in Response to Severe Weather","URL":"/Documents/EO/EO256.pdf","Date":"4/1/2025"}])
        row=parse_archive(page)[0]
        self.assertEqual(row.eo_number,"256"); self.assertEqual(row.date_signed,"2025-04-01"); self.assertEqual(row.action_type,"declaration")

    def test_enriches_image_only_order_five_without_override(self):
        page=self.fixture([{"Title2":"Executive Order 5, Relating to Declaring a State of Emergency","URL":"/eo5.pdf","Date":"1/28/2019"}])
        row=parse_archive(page)[0]
        self.assertIn("Severe Winter Weather",row.title); self.assertEqual(row.hazard,"winter")

    def test_state_office_closure_is_operational_companion(self):
        page=self.fixture([{"Title2":"Executive Order 7, Relating to Declaring a State of Emergency and Closing State Office Buildings","URL":"/eo7.pdf","Date":"1/29/2019"}])
        self.assertEqual(parse_archive(page)[0].action_type,"operational")

if __name__=="__main__": unittest.main()
