"""Iowa's 2020-2023 weather disaster proclamations, added by hand.

HSEMD's tables start in 2024. Each earlier row is one proclamation announced
in the Governor's newsroom, which begins in March 2020. Extensions, COVID-19,
avian influenza, harvest and fuel proclamations, and the 2023 building
collapse are left out.
"""
import csv
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
NEWSROOM = "https://governor.iowa.gov/press-release/"


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class HandAddedProclamationTests(unittest.TestCase):
    def test_rows_span_2020_to_2023_and_link_the_release_of_their_date(self):
        rows = csv_rows("manual_declarations.csv")
        self.assertEqual(len(rows), 39)
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            day = row["date_signed"]
            self.assertTrue("2020-03-01" <= day < "2024-01-01", row["declaration_id"])
            self.assertTrue(row["declaration_id"].startswith("IA-GOV-" + day + "-"), row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith(NEWSROOM + day + "/"), row["declaration_id"])
            self.assertEqual(row["governor"], "Kim Reynolds")

    def test_derecho_and_december_2021_proclamations(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        self.assertIn("Boone", rows["IA-GOV-2020-08-11-six-counties"]["event_description"])
        self.assertIn("43 counties", rows["IA-GOV-2021-12-16-43-counties"]["event_description"])

    def test_left_out_releases(self):
        urls = " ".join(r["archive_record_url"] for r in csv_rows("manual_declarations.csv"))
        for word in ("extends", "building-collapse", "covid", "signs-disaster-emergency-proclamation"):
            self.assertNotIn(word, urls)

    def test_each_has_a_reviewed_hazard_and_event_date(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        self.assertEqual(set(signed), set(overrides))
        for did, row in overrides.items():
            self.assertLessEqual(set(row["hazard_category_override"].split(",")), {"severe_storm", "wind", "flood"})
            if row["event_date"]:
                self.assertLessEqual(row["event_date"], signed[did], did)
                self.assertEqual(row["event_date"][:4], signed[did][:4], did)
        self.assertEqual(overrides["IA-GOV-2020-08-14-cass-guthrie"]["event_date"], "2020-08-10")
        self.assertEqual(overrides["IA-GOV-2023-04-24-10-counties"]["hazard_category_override"], "flood")


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2020(self):
        spec = importlib.util.spec_from_file_location("iowa_adapter", HERE / "iowa.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "IA"))
        self.assertTrue(re.match(r"2020-present", note))


if __name__ == "__main__":
    unittest.main()
