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
        action = nh.Action("2014-99", "Declaration of State of Emergency", "Margaret Wood Hassan", "x")
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

    def test_filing_stamp_after_the_signature_is_not_the_signing_date(self):
        text = ("Given under my hand and seal at the Executive Chambers in Concord, this 26th day of January, "
                "in the year of Our Lord, two thousand and fifteen. Filed with the Secretary of State this 28th day of January, 2015.")
        self.assertEqual(nh.date_in_text(text, 2015), "2015-01-26")

    def test_short_signature_line_still_beats_a_filing_stamp(self):
        text = "Given under my hand this 26th day of January, 2015. Filed this 28th day of January, 2015."
        self.assertEqual(nh.date_in_text(text, 2015), "2015-01-26")

    def test_year_words(self):
        self.assertEqual(nh.words_to_year("two thousand and three"), 2003)
        self.assertEqual(nh.words_to_year("two thousand twenty-one"), 2021)
        self.assertEqual(nh.words_to_year("two thousand and twenty, and"), 2020)
        self.assertEqual(nh.words_to_year("nineteen hundred and ninety-nine"), 1999)
        self.assertEqual(nh.words_to_year("two thousand"), 2000)
        self.assertIsNone(nh.words_to_year("the independence"))

    def _collect(self, pdf_text):
        """collect() over two registry orders, with every fetch and PDF read faked."""
        from unittest import mock
        orders = [nh.Action("2013-08", "An Order Declaring a State of Emergency due to Severe Weather",
                            "Margaret Wood Hassan", "https://x/2013-08.pdf"),
                  nh.Action("2010-99", "An Order Declaring a State of Emergency Due to Severe Weather.",
                            "John H. Lynch", "https://x/2010-99.pdf")]   # not a real order: no confirmed date
        with mock.patch.object(nh, "fetch", return_value=mock.Mock(text="", content=b"")), \
             mock.patch.object(nh, "parse_registry", return_value=orders), \
             mock.patch.object(nh, "pdf_text", return_value=pdf_text):
            return {a.number: a for a in nh.collect()}

    def test_confirmed_date_fills_an_unreadable_pdf(self):
        actions = self._collect("")
        self.assertEqual(actions["2013-08"].date_signed, "2013-07-03")
        self.assertTrue(actions["2013-08"].weather_related)
        self.assertIsNone(actions["2010-99"].date_signed)   # no confirmed date: stays undated

    def test_date_read_from_the_order_beats_the_confirmed_list(self):
        actions = self._collect("Given under my hand this 2nd day of July, 2013.")
        self.assertEqual(actions["2013-08"].date_signed, "2013-07-02")

    def _collect_saved(self, saved, pdf_text=""):
        """collect() over three orders with saved rows from an earlier run."""
        from unittest import mock
        orders = [nh.Action("2013-08", "An Order Declaring a State of Emergency due to Severe Weather",
                            "Margaret Wood Hassan", "https://x/2013-08.pdf"),
                  nh.Action("2010-99", "An Order Declaring a State of Emergency Due to Severe Weather.",
                            "John H. Lynch", "https://x/2010-99.pdf"),
                  nh.Action("2014-99", "Declaration of State of Emergency", "Margaret Wood Hassan",
                            "https://x/2014-99.pdf")]   # neither is a real order: no confirmed dates
        with mock.patch.object(nh, "fetch", return_value=mock.Mock(text="", content=b"")), \
             mock.patch.object(nh, "parse_registry", return_value=orders), \
             mock.patch.object(nh, "fetch_document", return_value=mock.Mock(content=b"pdf")) as read, \
             mock.patch.object(nh, "pdf_text", return_value=pdf_text), \
             mock.patch("builtins.print"):
            actions = {a.number: a for a in nh.collect(saved)}
        return actions, [c.args[0] for c in read.call_args_list]

    def test_orders_dated_on_an_earlier_run_are_not_read_again(self):
        saved = {"NH-2013-08": {"date_signed": "2013-07-03", "weather_related": "true"},
                 "NH-2014-99": {"date_signed": "2014-11-26", "weather_related": "true"}}
        actions, read = self._collect_saved(saved)
        self.assertEqual(read, ["https://x/2010-99.pdf"])      # only the order with no date yet
        self.assertEqual(actions["2014-99"].date_signed, "2014-11-26")
        # A generic title has no hazard word; the earlier read of its PDF found one.
        self.assertTrue(actions["2014-99"].weather_related)
        self.assertTrue(actions["2013-08"].weather_related)

    def test_a_confirmed_date_still_wins_over_a_saved_one(self):
        actions, read = self._collect_saved({"NH-2013-08": {"date_signed": "2013-06-26", "weather_related": "true"}})
        self.assertEqual(actions["2013-08"].date_signed, "2013-07-03")
        self.assertNotIn("https://x/2013-08.pdf", read)

    def test_without_saved_rows_every_order_is_read(self):
        actions, read = self._collect_saved({}, "Given under my hand this 2nd day of July, 2013.")
        self.assertEqual(len(read), 3)
        self.assertFalse(actions["2014-99"].weather_related)   # nothing found: no hazard

    def test_archive_requests_are_spaced(self):
        from unittest import mock
        # Times read: before call 1, after it, before call 2 (2 s later), after it.
        clock = iter([100.0, 101.0, 103.0, 109.0])
        with mock.patch.object(nh.requests, "get", return_value="ok"), \
             mock.patch.object(nh.time, "monotonic", side_effect=lambda: next(clock)), \
             mock.patch.object(nh.time, "sleep") as sleep, \
             mock.patch.object(nh, "_ia_last", float("-inf")):
            nh.ia_get("https://web.archive.org/a")
            nh.ia_get("https://web.archive.org/b")
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], nh.IA_MIN_INTERVAL - 2.0)   # waits out the rest

    def test_unreachable_registry_raises(self):
        from unittest import mock
        with mock.patch.object(nh, "fetch", return_value=None), \
             mock.patch.object(nh, "wayback_copy", return_value=(None, "")):
            with self.assertRaises(nh.RegistryUnavailable):
                nh.collect()

    def test_block_page_with_no_orders_raises(self):
        from unittest import mock
        with mock.patch.object(nh, "fetch", return_value=mock.Mock(text="<html>Access denied</html>", content=b"")), \
             mock.patch.object(nh, "wayback_copy", return_value=(mock.Mock(text="<html>Access denied</html>"), "2026-09-01")):
            with self.assertRaises(nh.RegistryUnavailable):
                nh.collect()

    def test_blocked_registry_is_read_from_the_internet_archive(self):
        from unittest import mock
        archive = {nh.REGISTRY_URL: (mock.Mock(text=REGISTRY), "2026-09-30"),
                   nh.urljoin(nh.REGISTRY_URL, "/hassan-2015-1.pdf"): (mock.Mock(content=b"pdf"), "2026-09-30"),
                   nh.urljoin(nh.REGISTRY_URL, "/hassan-2015-2.pdf"): (mock.Mock(content=b"pdf"), "2026-09-30")}
        with mock.patch.object(nh, "fetch", return_value=None) as live, \
             mock.patch.object(nh, "wayback_copy", side_effect=lambda url: archive.get(url, (None, ""))), \
             mock.patch.object(nh, "pdf_text", return_value="Given under my hand this 26th day of January, 2015."), \
             mock.patch.object(nh, "SOURCE_NOTE", ""):
            actions = {a.number: a for a in nh.collect()}
            self.assertEqual(live.call_count, 1)                    # PDFs go straight to the archive
            self.assertEqual(actions["2015-01"].date_signed, "2015-01-26")
            self.assertTrue(actions["2015-01"].weather_related)
            self.assertIn("2026-09-30", nh.SOURCE_NOTE)
            self.assertIn("Internet Archive", nh.action_row(actions["2015-01"])["source_scope"])

    def test_wayback_lookup_builds_the_original_copy_url(self):
        from unittest import mock
        lookup = mock.Mock(json=lambda: {"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20260930120000", "url": "http://web.archive.org/web/20260930120000/x"}}})
        lookup.raise_for_status = lambda: None
        page = mock.Mock(); page.raise_for_status = lambda: None
        with mock.patch.object(nh.requests, "get", side_effect=[lookup, page]) as get, \
             mock.patch.object(nh, "IA_MIN_INTERVAL", 0):
            response, when = nh.wayback_copy(nh.REGISTRY_URL)
        self.assertIs(response, page)
        self.assertEqual(when, "2026-09-30")
        self.assertEqual(get.call_args_list[1].args[0],
                         "https://web.archive.org/web/20260930120000id_/" + nh.REGISTRY_URL)

    def test_saved_rows_the_registry_does_not_produce_are_written_back(self):
        order = nh.Action("2015-01", "An Order Declaring a State of Emergency Due to Severe Winter Storm",
                          "Margaret Wood Hassan", "https://x/2015-01.pdf", date_signed="2015-01-26")
        nh.classify(order)
        undated = nh.Action("2010-99", "An Order Declaring a State of Emergency Due to Severe Weather.",
                            "John H. Lynch", "https://x/2010-99.pdf")
        nh.classify(undated)
        saved = [{"declaration_id": "NH-PROC-2012-10-29", "governor": "John H. Lynch", "eo_number": "",
                  "event_description": "Sandy", "date_signed": "2012-10-29", "archive_record_url": "u"},
                 {"declaration_id": "NH-2010-99", "governor": "John H. Lynch", "eo_number": "2010-99",
                  "event_description": "Severe weather", "date_signed": "2010-02-25", "archive_record_url": "u"},
                 {"declaration_id": "NH-2015-01", "governor": "x", "eo_number": "2015-01",
                  "event_description": "old text", "date_signed": "2015-01-20", "archive_record_url": "u"}]
        rows = {r["declaration_id"]: r for r in nh.join_rows([order, undated], saved)}
        self.assertEqual(set(rows), {"NH-2015-01", "NH-PROC-2012-10-29", "NH-2010-99"})
        self.assertEqual(rows["NH-2015-01"]["date_signed"], "2015-01-26")   # the registry's own row wins
        self.assertEqual(rows["NH-2010-99"]["date_signed"], "2010-02-25")


# The 17 orders that never gave a date, with their registry titles.
UNDATED = {
    "2020-04 #72": "An order regarding travel guidance and extending Emergency Order #52 ( Exhibit A )",
    "2020-04 #61": "An order extending Emergency Order #52",
    "2020-04 #32": "Extension of Emergency Orders #1 and #19 (temporary remote instruction and support for public K-12 school districts)",
    "2018-02": "An order extending the effective period for Executive Order 2017-3",
    "2017-05": "An order amending Executive Order 2017-04 re. Governor's Commission on the Human Treatment of Animals",
    "2016-09": "An Order Amending Executive Order 2013-05",
    "2016-03": "An order for state government to continue to lead-by-example in energy efficiency, conservation, and renewable energy.",
    "2015-02": "An Order Declaring the State of Emergency Over",
    "2014-06": "Declaration of State of Emergency",
    "2013-09": "An Order Declaring the State of Emergency Over",
    "2013-04": "An Order Declaring the State of Emergency Over.",
    "2012-03": "An Order Amending Executive Order 2011-03.",
    "2012-02": "An Order Amending Executive Order 2006-11.",
    "2011-06": "An Order Amending Executive Order 2005-2.",
    "2011-01": "An Order for State Government to Continue to Lead-by-Example in Energy Efficiency.",
    "2010-01": "An Order Declaring a State of Emergency Due to Severe Weather.",
    "2003-09": "An order declaring a limited state of emergency.",
}


class ReviewedDateTests(unittest.TestCase):
    """Orders whose PDF never gives a date are dated from the reviewed list,
    so they are read once more and then never again."""

    def run_collect(self, saved, pdf_text=""):
        from unittest import mock
        orders = [nh.Action(number, title, "", f"https://x/{number}.pdf") for number, title in UNDATED.items()]
        with mock.patch.object(nh, "fetch", return_value=mock.Mock(text="", content=b"")), \
             mock.patch.object(nh, "parse_registry", return_value=orders), \
             mock.patch.object(nh, "fetch_document", return_value=mock.Mock(content=b"pdf")) as read, \
             mock.patch.object(nh, "pdf_text", return_value=pdf_text), \
             mock.patch("builtins.print"):
            actions = nh.collect(saved)
        return actions, [c.args[0] for c in read.call_args_list]

    def test_every_order_that_never_gave_a_date_is_dated(self):
        actions, read = self.run_collect({})
        self.assertEqual(len(read), len(UNDATED))                    # read one last time
        self.assertEqual({a.number: a.date_signed for a in actions},
                         {number: nh.CONFIRMED_DATES[number] for number in UNDATED})

    def test_the_next_run_reads_none_of_them(self):
        first, _ = self.run_collect({})
        saved = {row["declaration_id"]: row for row in (nh.action_row(a) for a in first)}
        second, read = self.run_collect(saved)
        self.assertEqual(read, [])
        self.assertEqual([a.date_signed for a in second], [a.date_signed for a in first])

    def test_2010_01_is_signed_the_day_after_the_storm_began(self):
        actions, _ = self.run_collect({})
        storm = next(a for a in actions if a.number == "2010-01")
        self.assertEqual(storm.date_signed, "2010-02-26")
        self.assertTrue(storm.weather_related)
        saved = [{"declaration_id": "NH-2010-01", "governor": "John H. Lynch", "eo_number": "2010-01",
                  "event_description": "Severe weather", "date_signed": "2010-02-25", "archive_record_url": "u"}]
        rows = {r["declaration_id"]: r for r in nh.join_rows(actions, saved)}
        self.assertEqual(rows["NH-2010-01"]["date_signed"], "2010-02-26")   # replaces the saved first day

    def test_the_public_health_emergency_is_not_weather(self):
        actions, _ = self.run_collect({})
        order = next(a for a in actions if a.number == "2014-06")
        self.assertEqual(order.action_type, "declaration")
        self.assertFalse(order.weather_related)
        self.assertNotIn("NH-2014-06", {r["declaration_id"] for r in nh.join_rows(actions, [])})

    def test_reviewed_dates_fall_in_the_orders_own_year(self):
        from datetime import date
        for number, day in nh.CONFIRMED_DATES.items():
            self.assertEqual(date.fromisoformat(day).year, int(number[:4]), number)


if __name__ == "__main__": unittest.main()
