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


def library_page(governor, rows):
    """A results page in the Library's format: (number, date, title, file)."""
    head = ("<table><tr><th>Official Number</th><th>File Number</th><th>File</th><th>Title</th>"
            "<th>Additional Info &amp; Notes</th><th>Date Signed</th><th>Date Filed</th><th>Related EO</th>"
            "<th>Governor</th></tr>")
    body = "".join(f'<tr><td>{n}</td><td>{f}</td><td><a href="/archive/execorders/{f}.pdf">PDF</a></td>'
                   f"<td>{t}</td><td></td><td>{d}</td><td></td><td></td><td>{governor}</td></tr>"
                   for n, d, t, f in rows)
    return "<html><body>" + head + body + "</table></body></html>"


# Titles as the Library shows them for earlier governors (Oct 2026).
VENTURA_PAGE = library_page("Jesse Ventura", [
    ("00-04", "06/26/2000", "Emergency Executive Order 00-04 Declaring A State Of Emergency In The State Of Minnesota "
     "(Regarding The Torrential Rain That Occurred On June 19, 2000)", "00-04"),
    ("00-7", "07/26/2000", "Emergency Executive Order 00-7 Providing For Assistance To The Yellow Medicine County Sheriff "
     "(In Providing Security, Traffic Control And Clearing Debris After A Tornado Ripped Through The City Of Granite)", "00-07"),
    ("02-12", "12/30/2002", "Emergency Executive Order #02-12 Providing Emergency Relief From Regulations To Motor Carriers "
     "And Drivers Operating In Minnesota (While Engaged In The Transportation Of Hay And Straw To Victims Of The Drought "
     "In South Dakota, North Dakota And Montana)", "02-12"),
    ("99-20", "12/14/1999", "Executive Order 99-20 Assigning Emergency Responsibilities To State Agencies", "99-20"),
])
PAWLENTY_PAGE = library_page("Tim Pawlenty", [
    ("05-10", "09/05/2005", "Emergency Executive Order No. 05-10 Providing For A Declaration Of Emergency (Due To The "
     "Immediate Response To Support The Care, Sheltering And Housing Of Displaced Persons As A Result Of Hurricane "
     "Katrina)", "05-10"),
    ("06-01", "01/14/2006", "Emergency Executive Order No. 06-01 Providing For A Declaration Of Peacetime Emergency And The "
     "Provision Of Emergency Relief (Due To The Technological Failures And Malfunctions Of The Federal Systems Responsible "
     "For Providing Prescription Drug Coverage For Dual Eligible Beneficiaries)", "06-01"),
    ("06-04", "03/31/2006", "Emergency Executive Order 06-04 Declaring A State Of Emergency In The State Of Minnesota "
     "(Related To Flooding In The Red River Valley)", "06-04"),
    ("06-05", "04/03/2006", "Emergency Executive Order 06-05 Declaring A State Of Emergency In The State Of Minnesota (In "
     "Response To Flooding In The Red River Valley And Extending Emergency Executive Order 06-04 To Roseau County)", "06-05"),
    ("10-10", "06/19/2010", "Emergency Executive Order 10-10 Declaring A State Of Emergency In The State Of Minnesota (In The "
     "Counties Of Faribault, Freeborn, Olmsted, Otter Tail, Polk, Steele, And Wadena)", "10-10"),
])
DAYTON_PAGE = library_page("Mark Dayton", [
    ("11-21", "07/09/2011", "Emergency Executive Order 11-21 Declaring A State Of Emergency In The State Of Minnesota (Due To "
     "Storm Damage In Anoka, Brown, Isanti, Kanabec, Lincoln, Lyon, McLeod, Meeker, Pine, Pipestone, Redwood, Renville, "
     "Scott, Stearns, Wright, and Yellow Medicine Counties)", "11-21"),
    ("12-10", "06/25/2012", "Emergency Executive Order 12-10 Declaring A State Of Emergency In The State Of Minnesota And "
     "Providing Assistance For Sheltering Displaced Residents (From An Apartment Fire In The City Of Marshall In Lyon "
     "County)", "12-10"),
    ("13-03", "04/10/2013", "Emergency Executive Order 13-03 Providing Assistance To Southern Minnesota (Due To A Winter "
     "Storm)", "13-03"),
    ("14-11", "06/19/2014", "Emergency Executive Order 14-11 Declaring a State of Peacetime Emergency in the State of "
     "Minnesota", "14-11"),
    ("14-12", "07/09/2014", "Emergency Executive Order 14-12 Supplementing Emergency Executive Order 14-11, Declaring a State "
     "of Peacetime Emergency in the State of Minnesota", "14-12"),
    ("15-09", "04/23/2015", "Emergency Executive Order 15-09 Declaring a State of Peacetime Emergency in the State of "
     "Minnesota (in response to avian flu)", "15-09"),
    ("18-03", "01/22/2018", "Emergency Executive Order 18-03 Declaring an Emergency and Providing Assistance to Shelter "
     "Stranded Motorists", "18-03"),
    ("18-07", "05/16/2018", "Emergency Executive Order 18-07 Declaring an Emergency and Providing for Relief from Regulations "
     "to Motor Carriers and Drivers Operating in the State of Minnesota", "18-07"),
])
PAGES = {"6": VENTURA_PAGE, "7": PAWLENTY_PAGE, "43": DAYTON_PAGE, "44": LRL_PAGE}


class FakeResponse:
    def __init__(self, text, url):
        self.text, self.url = text, url

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url, headers=None, timeout=None):
        self.asked.append(url)
        return FakeResponse(self.pages[url.rsplit("=", 1)[1]], url)


class EarlierGovernorTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession(PAGES)
        self.counts = {}
        self.rows = {a.eo_number: a for a in mn.scrape(self.session, counts=self.counts)}

    def test_reads_every_governor_from_2000(self):
        self.assertEqual(self.session.asked, [mn.LRL_BASE + g for g in ("6", "7", "43", "44")])
        self.assertNotIn("99-20", self.rows)
        self.assertEqual(self.counts, {"Jesse Ventura": 3, "Tim Pawlenty": 5, "Mark Dayton": 8, "Tim Walz": 7})
        self.assertEqual(self.rows["00-04"].governor, "Jesse Ventura")
        self.assertEqual(self.rows["11-21"].governor, "Mark Dayton")
        self.assertEqual(self.rows["26-08"].governor, "Tim Walz")
        self.assertEqual(self.rows["00-7"].url, "https://www.lrl.mn.gov/archive/execorders/00-07.pdf")

    def test_older_declarations(self):
        for number, hazard in (("00-04", "flood"), ("05-10", "tropical"), ("06-04", "flood"),
                               ("10-10", "severe_storm"), ("11-21", "severe_storm"), ("14-11", "flood"),
                               ("18-03", "winter")):
            self.assertEqual((self.rows[number].action_type, self.rows[number].hazard), ("declaration", hazard), number)
        self.assertIn("overland flooding", self.rows["00-04"].title)
        self.assertIn("tornadoes on June 17, 2010", self.rows["10-10"].title)

    def test_older_orders_that_are_not_declarations(self):
        self.assertEqual(self.rows["06-05"].action_type, "amendment"); self.assertEqual(self.rows["06-05"].related_order, "06-04")
        self.assertEqual(self.rows["14-12"].action_type, "amendment"); self.assertEqual(self.rows["14-12"].related_order, "14-11")
        self.assertEqual(self.rows["18-07"].action_type, "operational")
        self.assertEqual(self.rows["02-12"].action_type, "operational")
        for number in ("00-7", "06-01", "12-10", "13-03", "15-09"):
            self.assertNotEqual(self.rows[number].action_type, "declaration", number)

    def test_walz_stranded_motorist_orders_of_2019_are_winter_declarations(self):
        for number in ("19-03", "19-05"):
            order = mn.classify(mn.Action(number, f"Emergency Executive Order {number} Declaring a Peacetime Emergency "
                                          "and Providing Assistance to Stranded Motorists", "2019-02-08", ""))
            self.assertEqual((order.action_type, order.hazard), ("declaration", "winter"), number)
            self.assertIn("blizzard", order.title)

    def test_carrier_relief_with_a_hazard_is_still_operational(self):
        relief = mn.classify(mn.Action("07-11", "Emergency Executive Order 07-11 Declaring an Emergency and Providing "
                                       "for Relief from Regulations to Motor Carriers and Drivers Operating in Minnesota "
                                       "(While Transporting Flood Related Waste)", "2007-08-27", ""))
        self.assertEqual((relief.action_type, relief.hazard), ("operational", "flood"))

    def test_number_prefixes_come_off(self):
        self.assertTrue(self.rows["02-12"].title.startswith("Providing Emergency Relief"))
        self.assertTrue(self.rows["05-10"].title.startswith("Providing For A Declaration Of Emergency"))

    def test_join_file_names_each_governor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mn.write_outputs(sorted(self.rows.values(), key=lambda x: (x.date_signed, x.eo_number)),
                             tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                governors = {r["eo_number"]: r["governor"] for r in csv.DictReader(f)}
        self.assertEqual(governors["00-04"], "Jesse Ventura")
        self.assertEqual(governors["05-10"], "Tim Pawlenty")
        self.assertEqual(governors["18-03"], "Mark Dayton")
        self.assertEqual(governors["26-04"], "Tim Walz")

    def test_an_unreadable_earlier_page_fails_the_run(self):
        pages = dict(PAGES, **{"7": "<title>Radware Bot Manager Captcha</title>"})
        with self.assertRaises(ValueError):
            mn.scrape(FakeSession(pages))


class CommittedDataTests(unittest.TestCase):
    def test_committed_join_reaches_back_to_2000(self):
        here = Path(__file__).resolve().parent
        with (here / "declarations_for_join.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        years = sorted(r["date_signed"][:4] for r in rows)
        self.assertEqual(years[0], "2000")
        self.assertEqual(len({r["declaration_id"] for r in rows}), len(rows))
        self.assertEqual({r["governor"] for r in rows}, {"Jesse Ventura", "Tim Pawlenty", "Mark Dayton", "Tim Walz"})


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest(self):
        """A refresh (build-plus.py --collect) shows the note collect()
        returns, and a build without collection shows the manifest's."""
        import importlib.util
        import json
        import subprocess
        from unittest import mock
        here = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("minnesota_adapter", here / "minnesota.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((here.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        states = manifest["states"] if isinstance(manifest, dict) else manifest
        self.assertEqual(note, next(st["coverage_note"] for st in states if st["abbreviation"] == "MN"))
        self.assertTrue(note.startswith("2000-present"))


if __name__ == "__main__": unittest.main()
