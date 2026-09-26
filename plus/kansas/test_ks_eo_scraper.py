"""
Unit tests for ks_eo_scraper.py.

The fixture below reproduces the real headings, dates, and DocumentCenter
PDF ids found on https://www.kansastag.gov/388/Kansas-Disaster-Declarations
during this delivery's research fetch (2024/2025 tab content), wrapped in
CivicPlus-style nested <div>/<li> markup representative of the real page,
since the exact raw markup could not be captured from this environment
(no live network access to kansastag.gov - see the summary report).
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import ks_eo_scraper as scraper  # noqa: E402


FIXTURE_HTML = """
<div class="tabs">
<div class="tab-heading">2025</div>
<ul>
<li>January 4 - February 9 (Winter Storms)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3367/Gov-Declaration-Winter-Storm-Signed-01-10-2025">State Declaration (PDF)</a></li></ul>
</li>
<li>May 18 - 19 (Severe Storms)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3905/Severe-Storms-May-18-19-2025">State Declaration (PDF)</a></li></ul>
</li>
<li>May 12 - Current (Drought)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3844/State-Declaration-for-Drought-Conditions-for-2025">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2024</div>
<ul>
<li>June 7 (Drought)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/3379/SOK-June-7-2024-Drought">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2018</div>
<ul>
<li>December 26-27 (Winter Storm)
  <ul><li><a href="https://www.kansastag.gov/DocumentCenter/View/1181/December-26-27-State-Declaration-PDF">State Declaration (PDF)</a></li></ul>
</li>
</ul>
<div class="tab-heading">2019</div>
<ul>
<li>July 22 - August 16 (Severe Storms and Flooding)
  <ul>
    <li><a href="https://www.kansastag.gov/DocumentCenter/View/1203/State-Declaration-PDF">State Declaration (PDF)</a></li>
    <li><a href="https://www.kansastag.gov/DocumentCenter/View/1204/Amended-State-Declaration-PDF">Amended State Declaration (PDF)</a></li>
  </ul>
</li>
</ul>
</div>
"""


# kansastag.gov shows each year as a tab. The tab labels are links that sit
# together above the panels, and the document links are relative. The old
# parser flattened this to "[2026](#...)" lines and matched nothing.
TABS_HTML = """<html><head><title>Kansas Disaster Declarations | KS Adjutant General</title></head><body>
<div class="tabbedWidget">
<ul class="tabs" role="tablist">
<li><a href="#tab2026" role="tab">2026</a></li><li><a href="#tab2025" role="tab">2025</a></li>
<li><a href="#tab2024" role="tab">2024</a></li><li><a href="#tab2023" role="tab">2023</a></li>
</ul>
<div id="tab2026" role="tabpanel"><ul>
<li>January 24 (Winter Storms)<ul><li><a href="/DocumentCenter/View/4126/Jan-24-2026-Winter-Storm-Disaster-Declaration">State Declaration (PDF)</a></li></ul></li>
<li>April 11 - April 26 (Wildland Fire)<ul><li><a href="/DocumentCenter/View/4221/SOK-Apr-11--Apr-26-2023-Wildland-Fire">State Declaration</a></li></ul></li>
<li>August 18 - Continuing (Severe Weather) - <a href="/DocumentCenter/View/4326/State-of-Disaster-Emergency-Proclamation_August-18-">State Declaration (PDF)</a></li>
<li>May 12 - Continuing (Hantavirus)<ul><li><a href="/DocumentCenter/View/4250/Hantavirus">State Declaration (PDF)</a></li></ul></li>
</ul></div>
<div id="tab2025" role="tabpanel"><ul>
<li>September 8 - September 12 (Flooding)<ul>
<li><a href="/DocumentCenter/View/4023/State-of-Disaster-Proclamation-September-8-12-2025">State Declaration (PDF)</a></li>
<li><a href="/DocumentCenter/View/4030/Amended">Amended State Declaration (PDF)</a></li></ul></li>
</ul></div>
<div id="tab2024" role="tabpanel"><p><strong>June 7 (Drought)</strong></p><p><a href="/DocumentCenter/View/3379/SOK-June-7-2024-Drought">Sate Declaration (PDF)</a></p></div>
<div id="tab2023" role="tabpanel"><ul><li>April 12-26 (Wildland Fires)<ul><li><a href="/DocumentCenter/View/2700/April-12-26">State Declaration (PDF)</a></li></ul></li></ul></div>
</div></body></html>"""

# The same tabs with no way to tell which panel belongs to which label.
UNMAPPED_TABS_HTML = TABS_HTML.replace('href="#tab', 'data-x="#tab').replace(' id="tab', ' class="tab')


class TestKansasPageLayouts(unittest.TestCase):
    def test_tab_panels_get_their_own_year(self):
        by_id = {r["doc_id"]: r for r in scraper.parse_declarations_page(TABS_HTML, max_year=2027)}
        self.assertEqual(by_id["4126"]["year"], "2026")
        self.assertEqual(by_id["4126"]["heading"], "January 24 (Winter Storms)")
        self.assertEqual(by_id["4126"]["pdf_url"],
                         "https://www.kansastag.gov/DocumentCenter/View/4126/Jan-24-2026-Winter-Storm-Disaster-Declaration")
        self.assertEqual(by_id["4023"]["year"], "2025")
        self.assertEqual(by_id["3379"]["year"], "2024")      # "Sate Declaration", bold heading in a <p>
        self.assertEqual(by_id["2700"]["year"], "2023")
        self.assertNotIn("4030", by_id)                       # amended copy is not a second record

    def test_heading_and_link_in_one_item(self):
        by_id = {r["doc_id"]: r for r in scraper.parse_declarations_page(TABS_HTML, max_year=2027)}
        self.assertEqual(by_id["4326"]["heading"], "August 18 - Continuing (Severe Weather)")

    def test_tabs_that_cannot_be_matched_to_panels_give_no_years(self):
        # Better no record than one filed under the wrong year.
        self.assertEqual(scraper.parse_declarations_page(UNMAPPED_TABS_HTML, max_year=2027), [])
        outline = scraper.describe_page(UNMAPPED_TABS_HTML)
        self.assertIn("DocumentCenter links", outline)
        self.assertIn("year <a", outline)

    def test_collect_checks_file_name_year_and_saved_dates(self):
        import csv as _csv, tempfile, os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            join = os.path.join(tmp, "j.csv")
            with open(join, "w", encoding="utf-8") as f:
                f.write("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                        "KS-PROC-4023,Laura Kelly,4023,Flooding,2025-09-09,u\n")
            with mock.patch.object(scraper, "fetch", return_value=TABS_HTML):
                n = scraper.collect(os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join)
            with open(join, encoding="utf-8") as f:
                rows = {r["declaration_id"]: r for r in _csv.DictReader(f)}
        self.assertNotIn("KS-PROC-4221", rows)                  # file name says 2023, tab says 2026
        self.assertNotIn("KS-PROC-4250", rows)                  # hantavirus is not weather
        self.assertEqual(rows["KS-PROC-4023"]["date_signed"], "2025-09-09")   # reviewed date kept
        self.assertEqual(rows["KS-PROC-4126"]["date_signed"], "2026-01-24")
        self.assertEqual(n, len(rows))

    def test_collect_stops_when_nothing_parses(self):
        import tempfile, os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(scraper, "fetch", return_value=UNMAPPED_TABS_HTML):
                with self.assertRaises(SystemExit):
                    scraper.collect(os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), os.path.join(tmp, "j.csv"))


class TestKansasEdgeCases(unittest.TestCase):
    """Cases an independent review found in the first version of the walk."""

    def parse(self, body):
        return scraper.parse_declarations_page(
            "<html><body><h2>2025</h2>%s</body></html>" % body, max_year=2027)

    def test_a_heading_is_used_for_one_link_only(self):
        # The amended-only entry's heading must not pass to the next entry,
        # whose own heading the parser does not understand.
        records = self.parse("""<ul>
        <li>April 1 - April 9 (Wildland Fire)<ul><li><a href="/DocumentCenter/View/3650/x">Amended State Declaration (PDF)</a></li></ul></li>
        <li>Statewide (Drought)<ul><li><a href="/DocumentCenter/View/3844/Drought-2025">State Declaration (PDF)</a></li></ul></li>
        </ul>""")
        self.assertEqual(records, [])

    def test_entries_separated_by_line_breaks(self):
        records = self.parse("""<p>June 7 (Drought) <a href="/DocumentCenter/View/3379/SOK-June-7-2025-Drought">State Declaration (PDF)</a><br>
        June 23 -26 (SG Fire) <a href="/DocumentCenter/View/2921/June-23-26-Sedgwick-Fire">State Declaration (PDF)</a></p>""")
        self.assertEqual([(r["doc_id"], r["heading"]) for r in records],
                         [("3379", "June 7 (Drought)"), ("2921", "June 23 -26 (SG Fire)")])

    def test_document_number_is_not_read_as_a_year(self):
        self.assertEqual(scraper.slug_years("https://www.kansastag.gov/DocumentCenter/View/2019"), set())
        self.assertEqual(scraper.slug_years("https://www.kansastag.gov/DocumentCenter/View/2019/Flood-May-2025"), {2025})

    def test_two_unmatched_tab_labels_give_no_years(self):
        html = TABS_HTML.replace('<li><a href="#tab2024" role="tab">2024</a></li><li><a href="#tab2023" role="tab">2023</a></li>', "")
        html = html.replace('href="#tab', 'data-x="#tab').replace(' id="tab', ' class="tab')
        self.assertEqual(scraper.parse_declarations_page(html, max_year=2027), [])

    def test_reupload_of_a_saved_entry_is_not_a_second_record(self):
        import csv as _csv, tempfile, os
        from unittest import mock
        page = TABS_HTML.replace("/DocumentCenter/View/4126/Jan-24-2026-Winter-Storm-Disaster-Declaration",
                                 "/DocumentCenter/View/4400/Jan-24-2026-Winter-Storm-Disaster-Declaration-amended")
        with tempfile.TemporaryDirectory() as tmp:
            join = os.path.join(tmp, "j.csv")
            with open(join, "w", encoding="utf-8") as f:
                f.write("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                        "KS-PROC-4126,Laura Kelly,4126,Winter Storms (January 24 (Winter Storms)),2026-01-24,u\n")
            with mock.patch.object(scraper, "fetch", return_value=page):
                scraper.collect(os.path.join(tmp, "a.csv"), os.path.join(tmp, "r.csv"), join)
            with open(join, encoding="utf-8") as f:
                ids = {r["declaration_id"] for r in _csv.DictReader(f)}
        self.assertNotIn("KS-PROC-4400", ids)


class TestKansasScraper(unittest.TestCase):
    def test_parses_2025_events(self):
        records = scraper.parse_declarations_page(FIXTURE_HTML)
        headings_2025 = [r["heading"] for r in records if r["year"] == "2025"]
        self.assertIn("January 4 - February 9 (Winter Storms)", headings_2025)
        self.assertIn("May 18 - 19 (Severe Storms)", headings_2025)
        self.assertEqual(len(headings_2025), 3)

    def test_amended_declaration_is_not_double_counted(self):
        records = scraper.parse_declarations_page(FIXTURE_HTML)
        matches_2019 = [r for r in records if r["year"] == "2019"]
        # Only the original "State Declaration (PDF)" should be captured,
        # never the "Amended State Declaration (PDF)" as a second row.
        self.assertEqual(len(matches_2019), 1)
        self.assertEqual(matches_2019[0]["doc_id"], "1203")

    def test_governor_mapping(self):
        self.assertEqual(scraper.governor_for(datetime(2025, 1, 10)), "Laura Kelly")
        self.assertEqual(scraper.governor_for(datetime(2018, 1, 21)), "Sam Brownback")
        self.assertEqual(scraper.governor_for(datetime(2018, 3, 14)), "Jeff Colyer")
        self.assertEqual(scraper.governor_for(datetime(2013, 8, 1)), "Sam Brownback")

    def test_date_range_parsing(self):
        date_str, hazard = scraper.parse_date_range("2025", "January 4 - February 9 (Winter Storms)")
        self.assertEqual(date_str, "2025-01-04")
        self.assertEqual(hazard, "Winter Storms")

    def test_single_date_parsing(self):
        date_str, hazard = scraper.parse_date_range("2024", "June 7 (Drought)")
        self.assertEqual(date_str, "2024-06-07")
        self.assertEqual(hazard, "Drought")


if __name__ == "__main__":
    unittest.main()
