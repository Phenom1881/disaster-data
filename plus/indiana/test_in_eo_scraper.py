"""Unit tests for in_eo_scraper.py.

These test the parsing/classification logic against real, hand-captured
HTML snippets (verified against the live in.gov pages), not against live
network calls -- so they run offline and deterministically.
"""
import unittest

import requests

import in_eo_scraper
from in_eo_scraper import (
    classify_title,
    is_original_declaration,
    _parse_listing_page,
    _year_from_eo_number,
)

REAL_LISTING_SNIPPET = """
<html><body>
<ul>
  <li>Executive Order 26-21<br>
    <a href="/gov/files/EO-26-21.pdf">DECLARING A STATEWIDE DISASTER EMERGENCY DUE TO FLOODING, SEVERE WEATHER, TORNADIC ACTIVITY AND A DERECHO</a>
  </li>
  <li>Executive Order 26-22<br>
    <a href="/gov/files/EO-26-22.pdf">SUPPLEMENTING EXECUTIVE ORDER 26-21 AND TEMPORARILY SUSPENDING CERTAIN FLOODWAY PERMIT REQUIREMENTS TO FACILITATE EMERGENCY REPAIRS</a>
  </li>
  <li>Executive Order 26-01<br>
    <a href="/gov/files/Executive-Order-26-01.pdf">UPDATING THE CODE OF ETHICS FOR THE INDIANA UTILITY REGULATORY COMMISSION AND PRIORITIZING HOOSIER RATEPAYERS</a>
  </li>
</ul>
</body></html>
"""


class TestClassifyTitle(unittest.TestCase):
    def test_flood_keyword(self):
        self.assertEqual(classify_title("DECLARING A DISASTER EMERGENCY DUE TO FLOODING"), "flood")

    def test_tornado_keyword(self):
        self.assertEqual(
            classify_title("DECLARING A DISASTER EMERGENCY DUE TO SEVERE WEATHER AND TORNADIC ACTIVITY"),
            "severe_storm",
        )

    def test_winter_keyword(self):
        self.assertEqual(classify_title("DECLARATION OF A STATEWIDE DISASTER EMERGENCY DUE TO A SEVERE WINTER STORM"), "winter")

    def test_no_keyword_returns_none(self):
        self.assertIsNone(classify_title("UPDATING THE CODE OF ETHICS FOR THE INDIANA UTILITY REGULATORY COMMISSION"))


class TestIsOriginalDeclaration(unittest.TestCase):
    def test_true_original(self):
        self.assertTrue(
            is_original_declaration("DECLARING A DISASTER EMERGENCY IN POSEY COUNTY DUE TO SEVERE AND TORNADIC ACTIVITY")
        )

    def test_false_for_supplement(self):
        self.assertFalse(
            is_original_declaration(
                "SUPPLEMENTING EXECUTIVE ORDER 26-21 AND TEMPORARILY SUSPENDING CERTAIN FLOODWAY PERMIT REQUIREMENTS"
            )
        )

    def test_false_for_waiver(self):
        self.assertFalse(
            is_original_declaration("WAIVER OF HOURS OF SERVICE REGULATIONS RELATING TO MOTOR CARRIERS AND DRIVERS TRANSPORTING PROPANE GAS")
        )

    def test_false_for_special_paid_leave(self):
        self.assertFalse(
            is_original_declaration("SPECIAL PAID LEAVE FOR STATE EMPLOYEES AFFECTED BY FLOODING, SEVERE WEATHER, TORNADIC ACTIVITY, AND A DERECHO")
        )

    def test_true_for_declaration_bundled_with_waiver(self):
        # EO 24-7's real title both declares a new emergency AND bundles a
        # waiver of hours-of-service for the same event in one order. A
        # naive "exclude anything mentioning waiver" rule would wrongly
        # drop a genuine original declaration -- caught during this
        # batch's own verification pass.
        self.assertTrue(
            is_original_declaration(
                "DECLARING A DISASTER EMERGENCY DUE TO SEVERE AND TORNADIC ACTIVITY WITH WAIVER OF HOURS OF SERVICE "
                "REGULATIONS RELATING TO MOTOR CARRIERS AND DRIVERS WORKING IN RESPONSE TO THE SEVERE WEATHER"
            )
        )

    def test_true_for_statewide_declaring_form(self):
        # EO 26-21, the August 2026 derecho and flooding. The old fixed-phrase
        # check had no "declaring a statewide ..." form and dropped it.
        self.assertTrue(
            is_original_declaration(
                "DECLARING A STATEWIDE DISASTER EMERGENCY DUE TO FLOODING, SEVERE WEATHER, "
                "TORNADIC ACTIVITY AND A DERECHO"
            )
        )

    def test_true_for_plural_emergencies(self):
        # EO 23-6.
        self.assertTrue(
            is_original_declaration(
                "DECLARING DISASTER EMERGENCIES IN DUBOIS WASHINGTON AND ORANGE COUNTIES DUE TO SEVERE WEATHER"
            )
        )

    def test_true_for_daniels_era_form(self):
        # EO 12-01.
        self.assertTrue(is_original_declaration("Disaster Declaration for Severe Storms and Tornados"))

    def test_true_for_declaration_of_statewide_form(self):
        # EO 26-03.
        self.assertTrue(
            is_original_declaration("DECLARATION OF A STATEWIDE DISASTER EMERGENCY DUE TO A SEVERE WINTER STORM")
        )

    def test_false_for_extension_even_if_it_says_declaration(self):
        self.assertFalse(
            is_original_declaration("EXTENSION OF EXECUTIVE ORDER 17-13: DECLARATION OF DISASTER EMERGENCY (EAST CHICAGO)")
        )


class TestYearFromEoNumber(unittest.TestCase):
    def test_four_digit_prefix(self):
        self.assertEqual(_year_from_eo_number("2020-42"), 2020)

    def test_two_digit_prefix_2000s(self):
        self.assertEqual(_year_from_eo_number("26-21"), 2026)

    def test_two_digit_prefix_1990s(self):
        self.assertEqual(_year_from_eo_number("90-05"), 1990)


class TestParseListingPage(unittest.TestCase):
    def test_parses_real_snippet(self):
        actions = _parse_listing_page(REAL_LISTING_SNIPPET, "https://www.in.gov/gov/newsroom/executive-orders/index.html")
        numbers = {a.eo_number for a in actions}
        self.assertEqual(numbers, {"26-21", "26-22", "26-01"})

    def test_pdf_urls_resolved_absolute(self):
        actions = _parse_listing_page(REAL_LISTING_SNIPPET, "https://www.in.gov/gov/newsroom/executive-orders/index.html")
        for a in actions:
            self.assertTrue(a.pdf_url.startswith("https://www.in.gov/"))


class TestJoinRouting(unittest.TestCase):
    def test_snippet_routes_only_26_21(self):
        # The fixture already carried EO 26-21 but nothing asserted it reached
        # the join, which is how the classifier gap went unnoticed.
        actions = _parse_listing_page(REAL_LISTING_SNIPPET, "https://www.in.gov/gov/newsroom/executive-orders/")
        routed = {
            a.eo_number for a in actions if classify_title(a.title) and is_original_declaration(a.title)
        }
        self.assertEqual(routed, {"26-21"})


class _FakeResponse:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%d error" % self.status_code)


class _FakeSession:
    """Serves the listing snippet at one URL, 404s everything else (including
    PDFs, so signing dates stay blank, which is the honest outcome)."""

    def __init__(self, listing_url):
        self.listing_url = listing_url
        self.requested = []

    def get(self, url, headers=None, timeout=None):
        self.requested.append(url)
        if url == self.listing_url:
            return _FakeResponse(200, REAL_LISTING_SNIPPET)
        return _FakeResponse(404)


class TestCurrentGovernorPage(unittest.TestCase):
    def test_canonical_url_is_tried_first(self):
        self.assertEqual(in_eo_scraper.CURRENT_EO_PAGES[0], "https://www.in.gov/gov/newsroom/executive-orders/")

    def test_falls_back_to_index_html(self):
        # Canonical URL 404s here; the index.html form still returns the page.
        session = _FakeSession("https://www.in.gov/gov/newsroom/executive-orders/index.html")
        actions = in_eo_scraper.scrape(session)
        self.assertEqual({a.eo_number for a in actions}, {"26-21", "26-22", "26-01"})
        routed = [a for a in actions if a.is_original_weather_declaration]
        self.assertEqual([a.eo_number for a in routed], ["26-21"])
        self.assertEqual(routed[0].date_signed, "")

    def test_no_current_page_is_survivable(self):
        session = _FakeSession("https://nowhere.invalid/")
        self.assertEqual(in_eo_scraper.scrape(session), [])


if __name__ == "__main__":
    unittest.main()
