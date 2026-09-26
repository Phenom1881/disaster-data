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

# GovDelivery bulletins feed, as the Governor's releases are published there.
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Office of the Governor</title>
<item><title>Press Release: Gov. Evers Declares State of Emergency in Response to Severe Storms throughout Eastern Wisconsin</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/42281e5</link>
<description>&lt;p&gt;Gov. Tony Evers today signed Executive Order #310 declaring a State of Emergency after severe storms.&lt;/p&gt;</description>
<pubDate>Wed, 02 Sep 2026 02:30:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Declares Emergency as State Prepares for Winter Storm</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/40e50fb</link>
<description>Snow and ice expected.</description><pubDate>Sat, 14 Mar 2026 18:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Declares State of Emergency Following Late June Storms</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/3a59cac</link>
<description>Storm damage.</description><pubDate>Tue, 28 Jul 2026 15:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Signs Executive Order Declaring State of Emergency, Period of Economic Disruption Due to the Ongoing Federal Government Shutdown</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/3f98f0a</link>
<description>FoodShare.</description><pubDate>Fri, 31 Oct 2025 15:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Announces Grants</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/1</link>
<description>Grants.</description><pubDate>Thu, 01 Oct 2026 15:00:00 +0000</pubDate></item>
</channel></rss>"""

SAVED_JOIN = ("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
              "WI-EO-286,Tony Evers,286,Gov. Evers Executive Order #286: Declaring a State of Emergency in Response to Severe Winter Weather,2026-03-14,https://evers.wi.gov/Documents/EO/EO286.pdf\n"
              "WI-EO-300,Tony Evers,300,Gov. Evers Executive Order #300: Declaring a State of Emergency in Response to Severe Weather,2026-07-28,https://evers.wi.gov/Documents/EO/EO300.pdf\n")


class WisconsinPressReleaseFallbackTests(unittest.TestCase):
    """evers.wi.gov does not answer GitHub's servers; releases fill the gap."""

    def test_only_releases_naming_their_order_are_recorded(self):
        # A record without the archive's id could never be reconciled with
        # it later, so releases without an order number go to review.
        from wi_eo_scraper import feed_releases
        review = []
        found = feed_releases(FEED, review)
        self.assertEqual([(r.date_signed, r.eo_number) for r in found], [("2026-09-01", "310")])   # Sep 2 02:30 GMT is Sep 1 in Wisconsin
        self.assertEqual(found[0].title, "Gov. Evers Declares State of Emergency in Response to Severe Storms throughout Eastern Wisconsin")
        self.assertEqual(len(review), 2)

    def test_the_announced_order_number_is_the_one_signed(self):
        from wi_eo_scraper import announced_order
        self.assertEqual(announced_order("Building on Executive Order #300, Gov. Evers today signed Executive Order #315 declaring a State of Emergency"), "315")
        self.assertEqual(announced_order("Executive Order #320, declaring a State of Emergency, takes effect"), "320")
        self.assertEqual(announced_order("See Executive Order #300 and Executive Order #301"), "")
        self.assertEqual(announced_order("Executive Order #330 declares a state of emergency"), "330")

    def test_amending_release_is_not_a_new_declaration(self):
        from wi_eo_scraper import feed_releases
        feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Press Release: Gov. Evers Declares State of Emergency for Additional Counties After Flooding</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/9</link>
<description>Executive Order #312, which amends Executive Order #310 and the state of emergency, adds counties.</description>
<pubDate>Fri, 04 Sep 2026 15:00:00 +0000</pubDate></item></channel></rss>"""
        review = []
        self.assertEqual(feed_releases(feed, review), [])
        self.assertEqual(len(review), 1)

    def test_fallback_keeps_saved_records_and_adds_the_new_order(self):
        import csv, tempfile
        from pathlib import Path
        from wi_eo_scraper import feed_releases, write_release_outputs
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "j.csv").write_text(SAVED_JOIN, encoding="utf-8")
            (tmp / "a.csv").write_text("declaration_id,eo_number,title,date_signed,action_type,hazard_category,archive_record_url\n", encoding="utf-8")
            added = write_release_outputs(feed_releases(FEED), tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                rows = {r["declaration_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(added, 1)
        self.assertEqual(set(rows), {"WI-EO-286", "WI-EO-300", "WI-EO-310"})
        self.assertEqual(rows["WI-EO-286"]["archive_record_url"], "https://evers.wi.gov/Documents/EO/EO286.pdf")   # saved row kept
        self.assertEqual(rows["WI-EO-310"]["date_signed"], "2026-09-01")

    def test_release_filters(self):
        from wi_eo_scraper import is_weather_emergency_release as ok
        self.assertTrue(ok("Press Release: Gov. Evers Declares State of Emergency for Severe Winter Weather in Northern Wisconsin"))
        self.assertFalse(ok("Press Release: Gov. Evers Declares Energy Emergency"))
        self.assertFalse(ok("Press Release: Gov. Evers Extends State of Emergency for Flood-Damaged Counties"))
        self.assertFalse(ok("Press Release: Gov. Evers Orders Flags to Half-Staff"))
        self.assertFalse(ok("Press Release: Gov. Evers Signs Bill to Support Emergency Responders After Tornadoes"))


if __name__=="__main__": unittest.main()
