import csv
import tempfile
import unittest
from pathlib import Path

import mn_eo_scraper as mn

# Rows as the Legislative Reference Library serves them (Sep 2026).
LRL_PAGE = """<html><body><table class="table">
<tr><th>Official Number</th><th>File Number</th><th>File</th><th>Title</th><th>Additional Info &amp; Notes</th>
<th>Date Signed</th><th>Date Filed</th><th>Related EO</th><th>Governor</th></tr>
<tr><td>26-08</td><td>2026-08</td><td><a href="/archive/execorders/2026-08.pdf">PDF</a></td>
<td>Emergency Executive Order 26-08 Declaring a Peacetime Emergency and Continuing Assistance to Communities Impacted by Wildfires</td>
<td>Includes Executive Council Resolution on Executive Order 26-08</td><td>07/12/2026</td><td>07/12/2026</td><td></td><td>Tim Walz</td></tr>
<tr><td>26-06</td><td>2026-06</td><td><a href="/archive/execorders/2026-06.pdf">PDF</a></td>
<td>Emergency Executive Order 26-06 Providing Assistance to Winona County</td><td></td><td>04/07/2026</td><td>04/07/2026</td><td></td><td>Tim Walz</td></tr>
<tr><td>26-04</td><td>2026-04</td><td><a href="/archive/execorders/2026-04.pdf">PDF</a></td>
<td>Emergency Executive Order 26-04 Declaring a Peacetime Emergency and Providing National Guard Assistance in Response to a Severe Winter Storm</td>
<td></td><td>03/13/2026</td><td>03/13/2026</td><td></td><td>Tim Walz</td></tr>
<tr><td>25-14</td><td>2025-14</td><td><a href="/archive/execorders/2025-14.pdf">PDF</a></td>
<td>Executive Order 25-14 Providing for Emergency Relief to Motor Carriers and Drivers Transporting Propane and Diesel in Minnesota</td>
<td></td><td>12/23/2025</td><td>12/23/2025</td><td></td><td>Tim Walz</td></tr>
<tr><td>25-07</td><td>2025-07</td><td><a href="/archive/execorders/2025-07.pdf">PDF</a></td>
<td>Emergency Executive Order 25-07 Amending Executive Order 25-06 and Authorizing Disaster Relief Financial Assistance to Veterans under the State Soldiers Assistance Program</td>
<td></td><td>07/08/2025</td><td>07/08/2025</td><td></td><td>Tim Walz</td></tr>
<tr><td>25-06</td><td>2025-06</td><td><a href="/archive/execorders/2025-06.pdf">PDF</a></td>
<td>Emergency Executive Order 25-06 Declaring a Peacetime Emergency and to Provide Storm Recovery Assistance in Beltrami County</td>
<td></td><td>06/27/2025</td><td>06/27/2025</td><td></td><td>Tim Walz</td></tr>
<tr><td>20-108</td><td>20-108</td><td><a href="/archive/execorders/20-108.pdf">PDF</a></td>
<td>Emergency Executive Order 20-108 Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists</td>
<td></td><td>12/24/2020</td><td>12/24/2020</td><td></td><td>Tim Walz</td></tr>
</table></body></html>"""


class MinnesotaLibraryTests(unittest.TestCase):
    def setUp(self):
        self.rows = {a.eo_number: mn.classify(a) for a in mn.parse_table(LRL_PAGE)}

    def test_reads_every_row_with_pdf_and_signed_date(self):
        self.assertEqual(len(self.rows), 7)
        self.assertEqual(self.rows["26-08"].url, "https://www.lrl.mn.gov/archive/execorders/2026-08.pdf")
        self.assertEqual(self.rows["26-08"].date_signed, "2026-07-12")

    def test_weather_declarations(self):
        self.assertEqual(self.rows["26-08"].action_type, "declaration"); self.assertEqual(self.rows["26-08"].hazard, "fire")
        self.assertEqual(self.rows["26-04"].action_type, "declaration"); self.assertEqual(self.rows["26-04"].hazard, "winter")
        self.assertEqual(self.rows["26-04"].title,
                         "Declaring a Peacetime Emergency and Providing National Guard Assistance in Response to a Severe Winter Storm")

    def test_amendments_and_operational_orders_are_not_declarations(self):
        self.assertEqual(self.rows["25-07"].action_type, "amendment"); self.assertEqual(self.rows["25-07"].related_order, "25-06")
        self.assertEqual(self.rows["25-14"].action_type, "operational")
        self.assertNotEqual(self.rows["26-06"].action_type, "declaration")

    def test_reviewed_generic_titles_keep_their_hazard(self):
        self.assertEqual(self.rows["20-108"].action_type, "declaration"); self.assertEqual(self.rows["20-108"].hazard, "winter")
        self.assertIn("hurricane-force winds", self.rows["25-06"].title)

    def test_join_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            n = mn.write_outputs(sorted(self.rows.values(), key=lambda x: x.date_signed),
                                 tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(n, 4)
        self.assertEqual({r["declaration_id"] for r in rows}, {"MN-EO-26-08", "MN-EO-26-04", "MN-EO-25-06", "MN-EO-20-108"})

    def test_page_without_the_table_is_an_error(self):
        with self.assertRaises(ValueError):
            mn.parse_table("<html><body><p>Search the executive orders</p></body></html>")

    def test_detects_radware_instead_of_returning_empty(self):
        self.assertTrue(mn.blocked("<title>Radware Bot Manager Captcha</title>", "https://validate.perfdrive.com/"))


if __name__ == "__main__": unittest.main()
