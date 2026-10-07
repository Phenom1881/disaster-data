"""Unit tests for oh_eo_scraper.py, run offline against a real RSS-item
fixture built from titles independently confirmed via search/web_fetch
during this batch's research (not fabricated titles)."""
import unittest
from xml.etree import ElementTree as ET

from oh_eo_scraper import classify_title, is_original_declaration

REAL_FEED_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example1</link>
  <pubDate>Sat, 10 Aug 2024 12:00:00 -0400</pubDate>
</item>
<item>
  <title>Governor DeWine Issues Proclamation Declaring State of Emergency in Ohio</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example2</link>
  <pubDate>Sat, 24 Jan 2026 09:00:00 -0500</pubDate>
</item>
<item>
  <title>MEDIA ADVISORY: Governor DeWine, Lt. Governor Husted to Announce New BMV Services Available Online</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example3</link>
  <pubDate>Wed, 22 Jun 2022 10:00:00 -0400</pubDate>
</item>
<item>
  <title>Governor DeWine Updates Ohioans on Severe Weather</title>
  <link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/example4</link>
  <pubDate>Tue, 01 Jul 2025 15:00:00 -0400</pubDate>
</item>
</channel></rss>
"""


class TestClassifyTitle(unittest.TestCase):
    def test_severe_weather(self):
        self.assertEqual(
            classify_title("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties Following Tornadoes"),
            "severe_storm",
        )

    def test_no_hazard(self):
        self.assertIsNone(classify_title("MEDIA ADVISORY: New BMV Services Available Online"))


class TestIsOriginalDeclaration(unittest.TestCase):
    def test_true_for_declares_state_of_emergency(self):
        self.assertTrue(is_original_declaration("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties"))

    def test_true_for_issues_proclamation(self):
        self.assertTrue(is_original_declaration("Governor DeWine Issues Proclamation Declaring State of Emergency in Ohio"))

    def test_false_for_update_bulletin(self):
        # "Updates Ohioans on Severe Weather" mentions weather but is a
        # status update, not itself a declaration -- must be excluded.
        self.assertFalse(is_original_declaration("Governor DeWine Updates Ohioans on Severe Weather"))

    def test_false_for_media_advisory(self):
        self.assertFalse(is_original_declaration("MEDIA ADVISORY: Governor DeWine to Announce New BMV Services"))


class TestStableIdsAndDates(unittest.TestCase):
    """Ids used to be numbered by feed position, so a new proclamation took
    an existing id and pushed a saved record out; and dates were left blank."""

    SAVED = [
        {"declaration_id": "OH-PROC-2024-002", "archive_record_url": "https://governor.ohio.gov/x/eight-counties",
         "date_signed": "2024-08-10"},
        {"declaration_id": "OH-PROC-2024-003", "archive_record_url": "https://governor.ohio.gov/x/four-counties",
         "date_signed": "2024-10-02"},
    ]

    def test_feed_date(self):
        from oh_eo_scraper import feed_date
        self.assertEqual(feed_date("Tue, 22 Sep 2026 14:05:00 -0400"), "2026-09-22")
        self.assertEqual(feed_date(""), "")

    def test_saved_proclamations_keep_their_ids_and_new_ones_do_not_collide(self):
        from oh_eo_scraper import BulletinAction, assign_ids
        old = BulletinAction("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties",
                             "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/abc", "2024-08-11")
        new = BulletinAction("Governor DeWine Declares State of Emergency in Several Ohio Counties",
                             "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/def", "2026-09-22")
        same_day = BulletinAction("Governor DeWine Declares State of Emergency in Two More Counties",
                                  "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/ghi", "2026-09-22")
        ids = assign_ids([new, old, same_day], self.SAVED)
        self.assertEqual(ids[id(old)], "OH-PROC-2024-002")          # matched a day off the saved date
        self.assertEqual(ids[id(new)], "OH-PROC-2026-09-22")
        self.assertEqual(ids[id(same_day)], "OH-PROC-2026-09-22-2")

    def test_join_rows_carry_dates(self):
        import csv, tempfile
        from pathlib import Path
        from oh_eo_scraper import BulletinAction, write_outputs
        a = BulletinAction("Governor DeWine Declares State of Emergency Following Flooding",
                           "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/def", "2026-09-22",
                           hazard_guess="flood", is_original_weather_declaration=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_outputs([a], tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["date_signed"], "2026-09-22")
        self.assertEqual(rows[0]["declaration_id"], "OH-PROC-2026-09-22")


class TestNextDayMatching(unittest.TestCase):
    SAVED = [{"declaration_id": "OH-PROC-2026-09-22", "archive_record_url": "https://governor.ohio.gov/x",
              "date_signed": "2026-09-22",
              "event_description": "Governor DeWine declares state of emergency in 21 counties (Athens Vinton) after "
                                   "severe weather and significant flooding"}]

    def test_a_different_proclamation_the_next_day_keeps_its_own_id(self):
        from oh_eo_scraper import BulletinAction, assign_ids
        tornado = BulletinAction("Governor DeWine Declares State of Emergency in Allen County Following Tornado",
                                 "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/zzz", "2026-09-23")
        self.assertEqual(assign_ids([tornado], self.SAVED)[id(tornado)], "OH-PROC-2026-09-23")

    def test_a_shared_generic_hazard_word_does_not_merge_two_counties(self):
        from oh_eo_scraper import BulletinAction, assign_ids, same_event
        saved = [{"declaration_id": "OH-PROC-2026-07-07", "archive_record_url": "https://governor.ohio.gov/m",
                  "date_signed": "2026-07-07",
                  "event_description": "Governor DeWine tours Mahoning County storm damage and declares state of emergency after severe storms and a tornado"}]
        allen = BulletinAction("Governor DeWine Declares State of Emergency in Allen County Following Severe Storms",
                               "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/q", "2026-07-08")
        self.assertEqual(assign_ids([allen], saved)[id(allen)], "OH-PROC-2026-07-08")
        from oh_eo_scraper import event_tokens
        self.assertEqual(event_tokens("Governor Thanks Police Services")[1], set())     # 'Police' is not ice
        self.assertTrue(same_event("Flooding in Several Ohio Counties", "21 counties after significant flooding"))
        self.assertTrue(same_event("High Winds Across Ohio", "damaging wind"))

    def test_updated_resend_is_not_a_new_declaration(self):
        from oh_eo_scraper import is_original_declaration
        self.assertFalse(is_original_declaration("UPDATED: Governor DeWine Declares State of Emergency in Several Ohio Counties"))


class TestSavedRowsKept(unittest.TestCase):
    def test_bulletin_matching_a_saved_record_writes_the_reviewed_row_back(self):
        # A headline like "... in Several Ohio Counties" names no hazard, so
        # letting it replace the reviewed description would drop the record
        # from the storm join.
        import csv, tempfile
        from pathlib import Path
        from oh_eo_scraper import BulletinAction, write_outputs
        a = BulletinAction("Governor DeWine Declares State of Emergency in Several Ohio Counties Following Flooding",
                           "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/abc", "2026-09-22",
                           hazard_guess="flood", is_original_weather_declaration=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            join = tmp / "j.csv"
            join.write_text("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                            "OH-PROC-2026-09-22,Ohio Governor,,Governor DeWine declares state of emergency in 21 counties "
                            "after severe weather and significant flooding,2026-09-22,https://governor.ohio.gov/x\n", encoding="utf-8")
            write_outputs([a], tmp / "a.csv", tmp / "r.csv", join)
            with join.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertIn("21 counties", rows[0]["event_description"])
        self.assertEqual(rows[0]["archive_record_url"], "https://governor.ohio.gov/x")


class TestCollectionHealth(unittest.TestCase):
    """The feed lists only recent bulletins, so most weeks it has no new
    proclamation. That used to empty the join file, and the health report
    showed Ohio's source as empty for weeks at a time; a feed that could not
    be fetched looked the same."""

    SAVED = ("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
             "OH-PROC-2012-06-30,John Kasich,,Statewide state of emergency after the derecho,2012-06-30,https://woub.org/x\n"
             "OH-PROC-2026-09-22,Mike DeWine,,21 counties after significant flooding,2026-09-22,https://governor.ohio.gov/x\n")

    def run_outputs(self, actions):
        import csv, tempfile
        from pathlib import Path
        from oh_eo_scraper import write_outputs
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            join = tmp / "j.csv"
            join.write_text(self.SAVED, encoding="utf-8")
            added = write_outputs(actions, tmp / "a.csv", tmp / "r.csv", join)
            with join.open(encoding="utf-8") as f:
                return added, list(csv.DictReader(f))

    def test_quiet_week_keeps_every_saved_record(self):
        from oh_eo_scraper import BulletinAction
        news = BulletinAction("Governor DeWine Announces New Workforce Grants",
                              "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/n", "2026-10-06")
        added, rows = self.run_outputs([news])
        self.assertEqual(added, 0)
        self.assertEqual([r["declaration_id"] for r in rows], ["OH-PROC-2012-06-30", "OH-PROC-2026-09-22"])

    def test_new_proclamation_is_added_beside_the_saved_ones(self):
        from oh_eo_scraper import BulletinAction
        a = BulletinAction("Governor DeWine Declares State of Emergency in Allen County Following Tornado",
                           "https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/t", "2026-10-06",
                           hazard_guess="severe_storm", is_original_weather_declaration=True)
        added, rows = self.run_outputs([a])
        self.assertEqual(added, 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[-1]["declaration_id"], rows[-1]["governor"]), ("OH-PROC-2026-10-06", "Mike DeWine"))

    def test_unreachable_feed_raises(self):
        import requests
        from oh_eo_scraper import FeedUnavailable, scrape

        class Broken:
            calls = 0

            def get(self, *_, **__):
                Broken.calls += 1
                raise requests.ConnectionError("refused")

        with self.assertRaises(FeedUnavailable):
            scrape(Broken())
        self.assertEqual(Broken.calls, 2)

    def test_headline_without_a_hazard_is_classified_from_the_bulletin(self):
        from oh_eo_scraper import scrape

        class Response:
            def __init__(self, body, status=200):
                self.content, self.text, self.status_code = body.encode(), body, status
                self.headers = {}

            def raise_for_status(self):
                pass

        feed = ("<rss><channel><item><title>Governor DeWine Signs Proclamation Declaring State of Emergency in "
                "Perry, Muskingum Counties</title><link>https://content.govdelivery.com/accounts/OHIOGOVERNOR/"
                "bulletins/p</link><pubDate>Tue, 11 Aug 2026 16:00:00 -0400</pubDate></item></channel></rss>")
        page = "<html><body>The proclamation was issued due to severe flooding.</body></html>"

        class Session:
            def get(self, url, **_):
                return Response(feed if url.endswith(".rss") else page)

        [action] = scrape(Session())
        self.assertEqual(action.hazard_guess, "flood")
        self.assertTrue(action.is_original_weather_declaration)

    def test_governor_by_date(self):
        from oh_eo_scraper import governor_for
        self.assertEqual(governor_for("2004-12-28"), "Bob Taft")
        self.assertEqual(governor_for("2008-09-15"), "Ted Strickland")
        self.assertEqual(governor_for("2018-02-24"), "John Kasich")
        self.assertEqual(governor_for("2019-01-14"), "Mike DeWine")

    def test_tour_headline_that_declares_is_a_declaration(self):
        from oh_eo_scraper import is_original_declaration
        self.assertTrue(is_original_declaration(
            "Governor DeWine Tours Mahoning County Storm Damage, Declares State of Emergency"))
        self.assertFalse(is_original_declaration("Governor DeWine Amends State of Emergency to Add Franklin County"))


class TestFeedParsing(unittest.TestCase):
    def test_real_fixture_parses(self):
        root = ET.fromstring(REAL_FEED_FIXTURE)
        titles = [item.find("title").text for item in root.iter("item")]
        self.assertEqual(len(titles), 4)
        self.assertIn("Governor DeWine Declares State of Emergency for Eight Northeast Ohio Counties", titles)


if __name__ == "__main__":
    unittest.main()
