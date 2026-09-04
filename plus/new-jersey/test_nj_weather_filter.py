import csv
import importlib.util
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


# Classification and CSV tests do not perform network or HTML work. Lightweight
# stand-ins keep the fixture runnable in minimal Python environments where the
# scraper's optional runtime dependencies are not installed.
if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.Response = object
    requests_stub.compat = types.SimpleNamespace(urljoin=lambda base, href: href)
    requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
    requests_stub.RequestException = Exception
    requests_stub.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub
if "bs4" not in sys.modules:
    bs4_stub = types.ModuleType("bs4")
    bs4_stub.BeautifulSoup = object
    sys.modules["bs4"] = bs4_stub


MODULE_PATH = Path(__file__).with_name("nj_eo_scraper.py")
SPEC = importlib.util.spec_from_file_location("nj_eo_scraper_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def order(description, *, action_type="declaration", number="1"):
    return MODULE.NJOrder(
        governor="Test Governor",
        order_number=number,
        description=description,
        date_issued="2026-01-01",
        document_url="https://example.test/order",
        document_format="html",
        action_type=action_type,
    )


class WeatherClassificationTests(unittest.TestCase):
    def test_ice_does_not_match_inside_unrelated_words(self):
        for description in (
            "Adopts the Governor's Code of Fair Practices",
            "Improves children's mental health services",
            "Creates an Office of Regulatory Affairs",
            "Advances environmental justice initiatives",
            "Directs state cooperation with ICE officials",
        ):
            with self.subTest(description=description):
                self.assertFalse(MODULE.is_weather_related(order(description)))

    def test_generic_emergency_language_is_not_weather(self):
        self.assertFalse(
            MODULE.is_weather_related(
                order("Declares a state of emergency related to public health and safety")
            )
        )

    def test_specific_weather_hazards_are_matched(self):
        for description in (
            "State of emergency due to a winter storm",
            "Emergency conditions caused by snow and ice",
            "Coastal flooding following a nor'easter",
            "Extreme heat and drought conditions",
        ):
            with self.subTest(description=description):
                self.assertTrue(MODULE.is_weather_related(order(description)))

    def test_continuation_is_an_extension(self):
        self.assertEqual(
            MODULE.classify_action_type(order("Continues the winter storm emergency")),
            "extension",
        )

    def test_join_file_contains_only_original_weather_declarations(self):
        rows = [
            order("Winter storm emergency", number="1"),
            order("Extends the winter storm emergency", action_type="extension", number="2"),
            order("Amends the winter storm emergency", action_type="amendment", number="3"),
            order("Terminates the winter storm emergency", action_type="termination", number="4"),
            order("Public health emergency", number="5"),
        ]
        for item in rows:
            item.weather_related = MODULE.is_weather_related(item)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "declarations_for_join.csv"
            MODULE.write_join_csv(rows, str(output))
            with output.open(encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual([row["eo_number"] for row in written], ["1"])

    def test_relationship_patterns_handle_multiple_targets(self):
        for wording in (
            "Executive Order Nos. 73, 74 and 75 are rescinded",
            "Executive Order Nos. 73, 74, and 75 are rescinded",
        ):
            with self.subTest(wording=wording):
                item = order(wording, number="76")
                relationships = MODULE.extract_relationships(item)
                targets = {row["target_order_id"] for row in relationships}
                self.assertEqual(
                    targets,
                    {
                        "NJ-TESTGOVERNOR-EO-73",
                        "NJ-TESTGOVERNOR-EO-74",
                        "NJ-TESTGOVERNOR-EO-75",
                    },
                )

    def test_relationship_scan_does_not_backtrack_on_long_text(self):
        item = order("Administrative order", number="999")
        item.document_text = (
            "Executive Order No. 123 " + (" " * 100_000) + "remains in force."
        )
        started = time.perf_counter()
        MODULE.extract_relationships(item)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
