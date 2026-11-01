"""Nevada's pre-2023 declarations, added by hand from dated news coverage.

Nevada's emergencies are Governor proclamations, not numbered executive
orders, and no archive of Guinn's or Gibbons's proclamations was found.
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

GOVERNORS = [("1999-01-04", "Kenny Guinn"), ("2007-01-01", "Jim Gibbons"),
             ("2011-01-03", "Brian Sandoval"), ("2019-01-07", "Steve Sisolak")]


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
    def test_fernley_declaration(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        fernley = rows["NV-SOE-2008-01-05"]
        self.assertEqual(fernley["governor"], "Jim Gibbons")
        self.assertIn("Lyon County", fernley["event_description"])
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        self.assertEqual(overrides["NV-SOE-2008-01-05"]["hazard_category_override"], "flood,winter")

    def test_ids_carry_the_date_and_governor_was_in_office(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertEqual(row["declaration_id"], "NV-SOE-" + row["date_signed"])
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("nevada_adapter", HERE / "nevada.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "NV"))
        self.assertTrue(note.startswith("2000-present"))
        for gap in ("DR-1540", "EM-3202", "EM-3204", "DR-1583", "DR-1629"):
            self.assertIn(gap, note)


if __name__ == "__main__":
    unittest.main()
