"""Kentucky's 2008-2024 states of emergency, added by hand.

The Secretary of State's Executive Journal blocks automated requests, so
each row comes from an executive order, an official release or a dated news
report. Where a report gives no signing day, the report's own date is used.
"""
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOVERNORS = [("2007-12-11", "Steve Beshear"), ("2015-12-08", "Matt Bevin"), ("2019-12-10", "Andy Beshear")]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


def named_rows():
    return [r for r in csv_rows("manual_declarations.csv") if r["governor"] != "Kentucky Governor"]


class HandAddedDeclarationTests(unittest.TestCase):
    def test_dates_read_from_the_sources(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            "KY-SOE-2008-09-14": "2008-09-14", "KY-SOE-2010-05-01": "2010-05-01",
            "KY-SOE-2011-04-25": "2011-04-25", "KY-SOE-2012-03-02": "2012-03-02",
            "KY-EO-2017-138": "2017-03-03", "KY-SOE-2023-02-24": "2023-02-24",
            "KY-EO-2024-379": "2024-05-26",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_ids_carry_the_date_or_order_number(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in named_rows():
            if row["declaration_id"].startswith("KY-SOE-"):
                self.assertEqual(row["declaration_id"], "KY-SOE-" + row["date_signed"])
            else:
                self.assertEqual(row["declaration_id"], "KY-EO-" + row["eo_number"])
                self.assertEqual(row["eo_number"][:4], row["date_signed"][:4])

    def test_governor_in_office_on_each_date(self):
        for row in named_rows():
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_has_a_reviewed_hazard_and_source(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in named_rows():
            override = overrides[row["declaration_id"]]
            self.assertTrue(row["archive_record_url"].startswith("https://"))
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertLessEqual(set(override["hazard_category_override"].split(",")),
                                 {"severe_storm", "flood", "winter", "wind", "tropical"})
            if override["event_date"]:
                self.assertLessEqual(override["event_date"], row["date_signed"])


class CoverageStartTests(unittest.TestCase):
    def test_note_and_start_year(self):
        spec = importlib.util.spec_from_file_location("kentucky_adapter", HERE / "kentucky.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "KY"))
        build_spec = importlib.util.spec_from_file_location("build_plus_ky", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(build_spec)
        sys.modules[build_spec.name] = build
        build_spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("KY", note), 2008)
        for gap in ("DR-1757", "DR-1841", "DR-1855", "DR-4008", "DR-4196", "DR-4848"):
            self.assertIn(gap, note)


if __name__ == "__main__":
    unittest.main()
