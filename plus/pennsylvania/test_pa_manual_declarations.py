"""Pennsylvania's 2001-2017 storm proclamations, added by hand.

pacodeandbulletin.gov disallows all automated agents in its robots.txt, so
the 2001-2010 signing dates are read from the Pennsylvania Bulletin issues
hosted by Villanova Law's digital repository and from PEMA's own archived
proclamation files. Each date is the "Given under my hand" date.
"""
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOVERNORS = [
    ("1995-01-17", "Tom Ridge"), ("2001-10-05", "Mark Schweiker"), ("2003-01-21", "Ed Rendell"),
    ("2011-01-18", "Tom Corbett"), ("2015-01-20", "Tom Wolf"),
]
GAP_DECLARATIONS = ["DR-1684", "DR-4003", "DR-4149", "DR-1538"]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


class HandAddedProclamationTests(unittest.TestCase):
    def test_dates_read_from_the_proclamations(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            "PA-PROC-2001-06-20": "2001-06-20", "PA-PROC-2003-02-17": "2003-02-17",
            "PA-PROC-2003-08-06": "2003-08-06", "PA-PROC-2003-09-18": "2003-09-18",
            "PA-PROC-2004-09-15": "2004-09-15", "PA-PROC-2004-09-17": "2004-09-17",
            "PA-PROC-2005-04-03": "2005-04-03", "PA-PROC-2006-06-28": "2006-06-28",
            "PA-PROC-2010-02-06": "2010-02-06",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_ids_carry_the_signing_date(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertEqual(row["declaration_id"], "PA-PROC-" + row["date_signed"])

    def test_governor_in_office_on_each_date(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_backfilled_row_has_a_reviewed_hazard_and_source(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            if row["date_signed"] >= "2011":
                continue
            override = overrides[row["declaration_id"]]
            self.assertTrue(row["archive_record_url"].startswith("https://"))
            self.assertNotIn("pacodeandbulletin.gov", row["archive_record_url"])
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertLessEqual(set(override["hazard_category_override"].split(",")),
                                 {"severe_storm", "flood", "winter", "tropical"})
            if override["event_date"]:
                self.assertLessEqual(override["event_date"], row["date_signed"])


class CoverageStartTests(unittest.TestCase):
    def test_note_and_start_year(self):
        spec = importlib.util.spec_from_file_location("pennsylvania_adapter", HERE / "pennsylvania.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        state = next(s for s in manifest["states"] if s["abbreviation"] == "PA")
        self.assertEqual(state["coverage_note"], adapter.COVERAGE_NOTE)

        build_spec = importlib.util.spec_from_file_location("build_plus_pa", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(build_spec)
        sys.modules[build_spec.name] = build
        build_spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("PA", adapter.COVERAGE_NOTE), 2000)

    def test_note_names_every_remaining_gap(self):
        spec = importlib.util.spec_from_file_location("pennsylvania_adapter_gaps", HERE / "pennsylvania.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        for number in GAP_DECLARATIONS:
            self.assertIn(number, adapter.COVERAGE_NOTE)


if __name__ == "__main__":
    unittest.main()
