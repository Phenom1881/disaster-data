"""Unit tests for ky_eo_scraper.py, run offline against real
governor.ky.gov/attachments/ filenames independently confirmed via
search/web_fetch during this batch's research."""
import unittest

from ky_eo_scraper import classify_text, extract_attachment_links, is_original_declaration

REAL_LINKS_FIXTURE = """
<html><body>
<a href="https://governor.ky.gov/attachments/20250104_Executive-Order_2025-007_State-of-Emergency-Related-to-Winter-Weather-Event.pdf">EO 2025-007</a>
<a href="https://governor.ky.gov/attachments/20250516_Executive-Order_2025-305_State-of-Emergency-Related-to-Continuing-Weather-Event.pdf">EO 2025-305</a>
<a href="https://governor.ky.gov/attachments/20260609_Executive-Order_2026-347_1st-Extension-of-State-of-Emergency-Related-to-Gas-Prices.pdf">EO 2026-347</a>
<a href="https://governor.ky.gov/attachments/20240523_Executive-Order_2024-155_Juneteenth-Executive-Branch-Holiday.pdf">EO 2024-155</a>
<a href="https://governor.ky.gov/attachments/20250402_Executive-Order_2025-210_State-of-Emergency_Weather.pdf">EO 2025-210</a>
</body></html>
"""


class TestClassifyText(unittest.TestCase):
    def test_winter_weather(self):
        self.assertEqual(classify_text("State of Emergency Related to Winter Weather Event"), "winter")

    def test_no_hazard(self):
        self.assertIsNone(classify_text("Juneteenth Executive Branch Holiday"))


class TestIsOriginalDeclaration(unittest.TestCase):
    def test_true_for_state_of_emergency_slug(self):
        self.assertTrue(is_original_declaration("State-of-Emergency-Related-to-Winter-Weather-Event"))

    def test_false_for_extension_slug(self):
        self.assertFalse(is_original_declaration("1st-Extension-of-State-of-Emergency-Related-to-Gas-Prices"))


class TestExtractAttachmentLinks(unittest.TestCase):
    def test_extracts_all_five(self):
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        numbers = {a.eo_number for a in actions}
        self.assertEqual(numbers, {"2025-007", "2025-305", "2026-347", "2024-155", "2025-210"})

    def test_dates_parsed_correctly(self):
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertEqual(by_number["2025-007"].date_signed, "2025-01-04")
        self.assertEqual(by_number["2026-347"].date_signed, "2026-06-09")

    def test_winter_weather_order_is_original(self):
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertTrue(by_number["2025-007"].is_original_weather_declaration)

    def test_continuing_weather_event_is_excluded_not_guessed(self):
        # EO 2025-305's real filename says "Related-to-Continuing-Weather-
        # Event". Whether that's a fresh declaration for an ongoing storm
        # or effectively an extension of an earlier one isn't decidable
        # from the filename alone -- the fail-closed rule means this gets
        # excluded from the automatic join rather than guessed either way.
        # It is exactly the kind of case that belongs in a manual
        # hazard_overrides.csv entry once someone reads the actual PDF.
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertFalse(by_number["2025-305"].is_original_weather_declaration)

    def test_gas_price_extension_excluded(self):
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertFalse(by_number["2026-347"].is_original_weather_declaration)

    def test_holiday_order_not_weather(self):
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertIsNone(by_number["2024-155"].hazard_guess)

    def test_underscore_separated_slug_is_extracted(self):
        # Real filename: State-of-Emergency_Weather.pdf -- mixes a hyphen
        # and an underscore. Caught during this batch's own verification
        # pass; the original regex/word-splitting missed underscores,
        # which would have silently dropped this real order entirely.
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertIn("2025-210", by_number)

    def test_bare_word_weather_is_correctly_ambiguous(self):
        # The slug alone just says "Weather" with no specific hazard word
        # (flood/tornado/wind/winter/etc). That's genuinely not enough to
        # classify from the filename -- this must stay unclassified/
        # excluded rather than assumed, per the fail-closed rule. The real
        # hazard (documented elsewhere as a spring 2025 storm/flooding
        # event) belongs in hazard_overrides.csv with a citation to the
        # order's own text, not guessed here from the filename.
        actions = extract_attachment_links(REAL_LINKS_FIXTURE)
        by_number = {a.eo_number: a for a in actions}
        self.assertIsNone(by_number["2025-210"].hazard_guess)
        self.assertFalse(by_number["2025-210"].is_original_weather_declaration)


# The newsroom feed as served (Sep 2026): items link to kentucky.gov release
# pages, never to the signed PDFs, which is why the attachment pattern alone
# found 0 orders on every run.
FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Kentucky.gov newsroom</title>
<item><title>Gov. Beshear Creates Office To Support Live Music</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2853</link>
<pubDate>Fri, 25 Sep 2026 23:02:57 GMT</pubDate><description>Music office.</description></item>
<item><title>Gov. Beshear Declares State of Emergency Ahead of Severe Storms and Flash Flooding</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2801</link>
<pubDate>Sat, 29 Aug 2026 01:15:00 GMT</pubDate><description>Heavy rain expected statewide.</description></item>
<item><title>Gov. Beshear Declares State of Emergency Following Severe Storms</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2700</link>
<pubDate>Sat, 27 Jun 2026 20:00:00 GMT</pubDate><description>Storms caused flooding.</description></item>
<item><title>Gov. Beshear Extends State of Emergency Related to Gas Prices</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2650</link>
<pubDate>Tue, 09 Jun 2026 15:00:00 GMT</pubDate><description>Gas prices.</description></item>
<item><title>Gov. Beshear Declares State of Emergency to Protect Kentuckians From Price Gouging</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2600</link>
<pubDate>Tue, 05 May 2026 15:00:00 GMT</pubDate><description>Price gouging during the weather event.</description></item>
</channel></rss>"""


class TestNewsroomReleases(unittest.TestCase):
    def test_weather_emergency_releases_are_found(self):
        from ky_eo_scraper import feed_items, release_declarations
        found = release_declarations(feed_items(FEED))
        # Oldest first, dated in Kentucky: 01:15 GMT on Aug 29 is the evening of Aug 28 there.
        self.assertEqual([(r.date_signed, r.url[-4:]) for r in found], [("2026-06-27", "2700"), ("2026-08-28", "2801")])

    def test_join_reuses_the_saved_record_and_names_a_new_one_by_date(self):
        import csv, tempfile
        from pathlib import Path
        from ky_eo_scraper import feed_items, release_declarations, write_outputs
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            join = tmp / "j.csv"
            join.write_text("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                            "KY-EO-2026-400,Kentucky Governor,2026-400,State Of Emergency (severe weather system with heavy rain "
                            "thunderstorms and isolated strong winds causing flooding and flash flooding),2026-06-27,"
                            "https://governor.ky.gov/attachments/20260627_Executive-Order_2026-400_SOE-Relating-to-Continuting-Storms.pdf\n",
                            encoding="utf-8")
            write_outputs([], tmp / "a.csv", tmp / "r.csv", join, release_declarations(feed_items(FEED)))
            with join.open(encoding="utf-8") as f:
                rows = {r["declaration_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(set(rows), {"KY-EO-2026-400", "KY-SOE-2026-08-28"})
        self.assertIn("isolated strong winds", rows["KY-EO-2026-400"]["event_description"])   # reviewed text kept
        self.assertEqual(rows["KY-SOE-2026-08-28"]["event_description"],
                         "Gov. Beshear Declares State of Emergency Ahead of Severe Storms and Flash Flooding")

    def test_headline_filters(self):
        from ky_eo_scraper import is_weather_declaration_release as ok
        self.assertTrue(ok("Gov. Beshear Declares State of Emergency, Activates Price Gouging Laws Ahead of Winter Storm"))
        self.assertTrue(ok("Gov. Beshear Declares a Statewide Emergency Ahead of Flooding"))
        self.assertTrue(ok("Gov. Beshear Declares State of Emergency", "Heavy rain and flash flooding expected."))
        self.assertFalse(ok("Gov. Beshear Says State of Emergency Likely as Storms Approach"))
        self.assertFalse(ok("Gov. Beshear Signs Order Expanding State of Emergency to 20 More Counties After Flooding"))
        self.assertFalse(ok("Gov. Beshear on Flood Recovery Issues; State of Emergency Remains in Effect"))
        self.assertFalse(ok("Gov. Beshear Declares State of Emergency to Stop Price Gouging", "after the winter storm"))
        self.assertFalse(ok("Significant Progress on Roads; Gov. Beshear Reviews State of Emergency Response"))

    def test_follow_up_release_is_the_same_declaration(self):
        from ky_eo_scraper import feed_items, release_declarations
        feed = FEED.replace("</channel>", """<item><title>Gov. Beshear Signs Executive Order Declaring State of Emergency as Storms Arrive</title>
<link>https://kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&amp;prId=2802</link>
<pubDate>Sun, 30 Aug 2026 16:00:00 GMT</pubDate><description>Flooding.</description></item></channel>""")
        found = release_declarations(feed_items(feed))
        self.assertEqual([r.date_signed for r in found], ["2026-06-27", "2026-08-28"])


if __name__ == "__main__":
    unittest.main()
