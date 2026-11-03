"""Hawaii declarations dated by hand: Lingle's October 31, 2004 Manoa flood
proclamation, and the event date for Ige's April 21, 2020 Kauai flood
proclamation (rain on March 27 and 28, 2020)."""
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return {r["declaration_id"]: r for r in csv.DictReader(handle)}


class BackfillTests(unittest.TestCase):
    def test_manoa_flood_proclamation(self):
        row = csv_rows("manual_declarations.csv")["HI-SOE-2004-10-31"]
        self.assertEqual((row["governor"], row["date_signed"]), ("Linda Lingle", "2004-10-31"))
        override = csv_rows("hazard_overrides.csv")["HI-SOE-2004-10-31"]
        self.assertEqual((override["hazard_category_override"], override["event_date"]), ("flood", "2004-10-30"))
        self.assertEqual(override["source_url"], row["archive_record_url"])

    def test_kauai_flood_event_date(self):
        row = csv_rows("manual_declarations.csv")["HI-SOE-2020-04-21"]
        override = csv_rows("hazard_overrides.csv")["HI-SOE-2020-04-21"]
        self.assertEqual(override["event_date"], "2020-03-27")
        self.assertLess(override["event_date"], row["date_signed"])

    def test_compared_from_2000_with_the_gap_named(self):
        spec = importlib.util.spec_from_file_location("build_plus_hi", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = build
        spec.loader.exec_module(build)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s for s in manifest["states"] if s["abbreviation"] == "HI")["coverage_note"]
        self.assertEqual(build.coverage_start_year("HI", note), 2000)
        self.assertIn("DR-1348", note)
        self.assertIn("Plus %d declarations" % len(csv_rows("manual_declarations.csv")), note)


if __name__ == "__main__":
    unittest.main()
