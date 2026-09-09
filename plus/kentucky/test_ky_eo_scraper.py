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


if __name__ == "__main__":
    unittest.main()
