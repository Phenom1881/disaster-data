"""Gilmore's 2000-2001 weather emergency orders, added by hand.

The Library of Virginia collection the scraper reads starts with Governor
Warner in 2002. These orders come from the Virginia Register of Regulations,
which printed each one. Each order memorializes a state of emergency the
Governor declared verbally, and date_signed is that declaration date.
"""
import csv
import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class GilmoreOrderTests(unittest.TestCase):
    def test_dates_read_from_the_register(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        self.assertEqual(dates, {
            "VA-GILMORE-EO-63-2000": "2000-01-25",
            "VA-GILMORE-EO-77-2001": "2001-07-09",
            "VA-GILMORE-EO-82-2001": "2001-07-29",
        })

    def test_ids_match_order_number_and_year(self):
        for row in csv_rows("manual_declarations.csv"):
            number = row["eo_number"].split("-")[1]
            self.assertEqual(row["declaration_id"], f"VA-GILMORE-EO-{number}-{row['date_signed'][:4]}")
            self.assertEqual(row["governor"], "James S. Gilmore III")
            self.assertLess(row["date_signed"], "2002-01-12")

    def test_each_has_a_reviewed_hazard_and_register_source(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            override = overrides[row["declaration_id"]]
            self.assertTrue(row["archive_record_url"].startswith("https://register.dls.virginia.gov/"))
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertLessEqual(set(override["hazard_category_override"].split(",")), {"winter", "flood"})
            if override["event_date"]:
                self.assertLessEqual(override["event_date"], row["date_signed"])


class CoverageStartTests(unittest.TestCase):
    def test_virginia_compares_from_2000(self):
        spec = importlib.util.spec_from_file_location("build_plus_va", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = build
        spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("VA", "2000-present"), 2000)
        self.assertEqual(build.coverage_start_year("VA", "Virginia structured archive coverage begins in 2002"), 2000)


if __name__ == "__main__":
    unittest.main()
