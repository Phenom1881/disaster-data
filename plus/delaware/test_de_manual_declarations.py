"""Delaware's pre-2025 declarations, added by hand.

The Governor's state of emergency archive starts in October 2025. Earlier
storm declarations come from the Governor's news releases and dated news
coverage; Minner's 2002 drought order comes from the Delaware Public Archives.
"""
import csv
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent

GOVERNORS = [("2001-01-03", "Ruth Ann Minner"), ("2009-01-20", "Jack Markell"),
             ("2017-01-17", "John Carney")]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


class HandAddedDeclarationTests(unittest.TestCase):
    def test_isabel_and_february_2010_declarations(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        self.assertEqual(rows["DE-SOE-2003-09-18"]["governor"], "Ruth Ann Minner")
        self.assertIn("Isabel", rows["DE-SOE-2003-09-18"]["event_description"])
        self.assertEqual(rows["DE-SOE-2010-02-10"]["governor"], "Jack Markell")
        self.assertIn("blizzard", rows["DE-SOE-2010-02-10"]["event_description"])

    def test_ids_carry_the_date_and_are_unique(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            if row["declaration_id"].startswith("DE-SOE-"):
                self.assertEqual(row["declaration_id"], "DE-SOE-" + row["date_signed"])

    def test_governor_in_office_on_each_date(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_links_its_source(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])

    def test_overrides_name_hand_rows_and_a_known_hazard(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        for row in csv_rows("hazard_overrides.csv"):
            self.assertIn(row["declaration_id"], signed)
            self.assertLessEqual(set(row["hazard_category_override"].split(",")),
                                 {"winter", "tropical", "flood", "severe_storm", "drought"})
            if row["event_date"]:
                self.assertLessEqual(row["event_date"], signed[row["declaration_id"]])


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("delaware_adapter", HERE / "delaware.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "DE"))
        self.assertTrue(note.startswith("2000-present"))
        for gap in ("EM-3183", "DR-1572", "DR-1654", "DR-4627"):
            self.assertIn(gap, note)


if __name__ == "__main__":
    unittest.main()
