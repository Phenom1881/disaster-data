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


class TestDanielsIndexFallback(unittest.TestCase):
    def test_year_links_read_from_archive_page_when_index_is_gone(self):
        archive = ('<p>Executive Order Archives: <a href="3635.htm">2011</a> | '
                   '<a href="3359.htm">2009</a> | <a href="2417.htm">2007</a></p>')

        class Session:
            def get(self, url, headers=None, timeout=None):
                if url == in_eo_scraper.DANIELS_INDEX_FALLBACKS[0]:
                    return _FakeResponse(200, archive)
                return _FakeResponse(404)

        urls = in_eo_scraper._discover_daniels_year_pages(Session())
        self.assertEqual(urls, [
            "https://www.in.gov/governorhistory/mitchdaniels/3635.htm",
            "https://www.in.gov/governorhistory/mitchdaniels/3359.htm",
            "https://www.in.gov/governorhistory/mitchdaniels/2417.htm",
        ])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- 2026-09-27
# Dates: OCR through the tesseract program, the order's own year, saved
# dates reused, and every failure counted.
import io as _io
import random as _random
import requests as _requests
import in_eo_scraper as _ies


def _scanned(lines, dpi=200):
    from PIL import Image, ImageDraw, ImageFont
    _random.seed(3)
    page = Image.new("L", (int(8.5 * dpi), int(11 * dpi)), 255)
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("DejaVuSerif.ttf", int(dpi * 0.15))
    except OSError:
        font = ImageFont.load_default(size=int(dpi * 0.15))
    for i, line in enumerate(lines):
        draw.text((dpi, dpi + i * int(dpi * 0.3)), line, font=font, fill=0)
    out = _io.BytesIO()
    page.rotate(0.5, fillcolor=255).save(out, "PDF", resolution=dpi)
    return out.getvalue()


class _Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"{self.status_code}", response=self)


class _Session:
    def __init__(self, status=200, content=b""):
        self.status, self.content, self.calls = status, content, 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        return _Resp(self.status, self.content)


ATTESTED = ["EXECUTIVE ORDER 18-01", "DECLARING A DISASTER EMERGENCY DUE TO FLOODING",
            "WHEREAS, flooding began on February 20, 2018;", "",
            "IN TESTIMONY WHEREOF, I have hereunto set my hand",
            "this 24th day of February, 2018.", "", "Eric J. Holcomb, Governor"]


class DateTests(unittest.TestCase):
    def setUp(self):
        _ies.DATE_PROBLEMS.clear()

    @unittest.skipUnless(_ies.TESSERACT, "tesseract is not installed")
    def test_scanned_order_is_dated_by_ocr_from_the_attestation(self):
        date, via_ocr = _ies.fetch_signed_date(_Session(content=_scanned(ATTESTED)), "u", 2018)
        self.assertEqual((date, via_ocr), ("2018-02-24", True))

    @unittest.skipUnless(_ies.TESSERACT, "tesseract is not installed")
    def test_a_date_outside_the_order_year_is_refused(self):
        date, _ = _ies.fetch_signed_date(_Session(content=_scanned(ATTESTED)), "u", 2019)
        self.assertEqual(date, "")
        self.assertIn("read, but no signing date found (OCR)", _ies.DATE_PROBLEMS)

    def test_without_ocr_a_scan_is_counted(self):
        saved, _ies.TESSERACT = _ies.TESSERACT, None
        try:
            self.assertEqual(_ies.fetch_signed_date(_Session(content=_scanned(ATTESTED)), "u", 2018), ("", False))
        finally:
            _ies.TESSERACT = saved
        self.assertEqual(_ies.DATE_PROBLEMS["scanned, OCR not installed"], 1)

    def test_a_refused_download_is_retried_once_and_counted(self):
        session = _Session(status=403)
        self.assertEqual(_ies.fetch_signed_date(session, "u", 2018), ("", False))
        self.assertEqual(session.calls, 2)
        self.assertEqual(_ies.DATE_PROBLEMS["download failed (HTTPError 403)"], 1)

    def test_saved_dates_are_read_from_the_join_file(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as tmp:
            path = _P(tmp) / "j.csv"
            path.write_text("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                            "IN-EO-26-21,G,26-21,Flood,2026-08-13,u\nIN-EO-26-08,G,26-08,Storm,,u\n")
            self.assertEqual(_ies.load_saved_dates(path), {"26-21": "2026-08-13"})


class ListingFormsTests(unittest.TestCase):
    """2026-10-07: "Executive Order 23- 6" was not read, so seven 2023 orders
    were missing; Daniels-era links read only "Executive Order 12-01"."""

    def test_spaced_and_numbered_headings(self):
        html = """<ul>
        <li>Executive Order 23- 6 <a href="/dA/x/Executive-Order-23-06.pdf">DECLARING DISASTER EMERGENCIES IN DUBOIS,
        WASHINGTON, AND ORANGE COUNTIES DUE TO SEVERE WEATHER</a></li>
        <li>Executive Order No. 18-01 <a href="/dA/y/EO_18-01.pdf">DECLARING A DISASTER EMERGENCY DUE TO FLOODING</a></li>
        </ul>"""
        actions = {a.eo_number: a for a in in_eo_scraper._parse_listing_page(html, "https://www.in.gov/x/")}
        self.assertEqual(set(actions), {"23-6", "18-01"})
        self.assertTrue(in_eo_scraper.is_original_declaration(actions["23-6"].title))

    def test_daniels_title_comes_from_the_file_name(self):
        html = """<ul><li><a href="files/EO_12-01_Disaster_Declaration_for_Severe_Storms_and_Tornados.pdf">Executive Order 12-01</a></li>
        <li><a href="files/20120314134421549.pdf">Executive Order 12-03</a></li></ul>"""
        actions = {a.eo_number: a for a in in_eo_scraper._parse_listing_page(html, "https://www.in.gov/governorhistory/mitchdaniels/2419.htm")}
        self.assertEqual(actions["12-01"].title, "Disaster Declaration for Severe Storms and Tornados")
        self.assertEqual(in_eo_scraper.classify_title(actions["12-01"].title), "severe_storm")
        self.assertEqual(actions["12-03"].title, "Executive Order 12-03")      # nothing better to read

    def test_governor_by_date(self):
        self.assertEqual(in_eo_scraper.governor_for("2012-03-03"), "Mitch Daniels")
        self.assertEqual(in_eo_scraper.governor_for("", 2013), "Mike Pence")
        self.assertEqual(in_eo_scraper.governor_for("2023-04-05"), "Eric J. Holcomb")
        self.assertEqual(in_eo_scraper.governor_for("2025-06-01"), "Mike Braun")



class EventDateTests(unittest.TestCase):
    """2026-10-08: ten Daniels-era scans have no readable signing date."""

    def test_event_dates_stay_in_the_orders_year(self):
        for number, day in in_eo_scraper.EVENT_DATES.items():
            self.assertEqual(day[2:4], number[:2], number)
        self.assertNotIn("12-04", in_eo_scraper.EVENT_DATES)   # 2011 floods, signed in 2012
