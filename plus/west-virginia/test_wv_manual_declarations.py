"""West Virginia's 2001-2024 weather declarations, added by hand.

The Governor's news archive starts in 2025. Earlier declarations are the
Governor's state of emergency proclamations in the Secretary of State's
Executive Journal, each read from its scan. Only the original declaration for
an event is kept: amendments that add counties, extensions, terminations and
States of Preparedness are left out, as are non-weather emergencies (the 2014
chemical spill, the 2015 train derailment, COVID-19).
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
JOURNAL = "https://apps.sos.wv.gov/adlaw/executivejournal/readpdf.aspx?DocID="

# Governors and the day each took office.
GOVERNORS = [("2001-01-15", "Bob Wise"), ("2005-01-17", "Joe Manchin III"),
             ("2010-11-15", "Earl Ray Tomblin"), ("2017-01-16", "Jim Justice")]


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
    def test_dates_read_from_the_proclamations(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            "WV-SOE-2001-07-08": "2001-07-08",  # recited in Executive Order 14-01
            "WV-PROC-16524": "2002-05-02", "WV-PROC-16655": "2003-02-16",
            "WV-PROC-16730": "2003-09-18", "WV-PROC-16926": "2004-09-17",
            "WV-PROC-17941": "2009-12-21", "WV-PROC-32324": "2012-02-07",
            "WV-PROC-33144": "2012-06-30", "WV-PROC-33685": "2012-10-29",
            "WV-PROC-88743": "2019-06-30", "WV-PROC-97201": "2024-10-01",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_follow_on_and_non_weather_proclamations_are_left_out(self):
        ids = {r["declaration_id"] for r in csv_rows("manual_declarations.csv")}
        left_out = {
            # Later proclamations for the February 15, 2003 snow and ice storm.
            "WV-PROC-16788", "WV-PROC-16659", "WV-PROC-16658",
            # Counties added to an earlier declaration, and a duplicate filing.
            "WV-PROC-16711", "WV-PROC-16760", "WV-PROC-16762", "WV-PROC-16806",
            # States of Preparedness, followed by declarations that are kept.
            "WV-PROC-38770", "WV-PROC-52209",
            # Evacuee aid, chemical spill, train derailment, fire, water, COVID-19.
            "WV-PROC-17489", "WV-PROC-36487", "WV-PROC-38711", "WV-PROC-86041",
            "WV-PROC-89322", "WV-PROC-89491", "WV-PROC-96159",
        }
        self.assertEqual(ids & left_out, set())

    def test_ids_match_the_journal_document(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            did = row["declaration_id"]
            if did.startswith("WV-SOE-"):
                self.assertEqual(did, "WV-SOE-" + row["date_signed"])
                self.assertEqual(row["archive_record_url"], JOURNAL + "24121")
                continue
            match = re.fullmatch(r"WV-PROC-(\d+)", did)
            self.assertTrue(match, did)
            self.assertEqual(row["archive_record_url"], JOURNAL + match.group(1), did)

    def test_rows_stop_where_the_news_archive_starts(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertTrue("2001-01-01" <= row["date_signed"] < "2025-01-01", row["declaration_id"])

    def test_governor_in_office_on_each_date(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_has_a_reviewed_hazard_and_event_date_before_signing(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        self.assertEqual(set(signed) - set(overrides), set())
        allowed = {"flood", "severe_storm", "winter", "tropical", "drought", "fire", "wind"}
        for did, row in overrides.items():
            self.assertIn(did, signed)
            self.assertLessEqual(set(row["hazard_category_override"].split(",")), allowed, did)
            if row["event_date"]:
                self.assertLessEqual(row["event_date"], signed[did], did)
        self.assertEqual(overrides["WV-PROC-32324"]["event_date"], "2011-11-21")
        self.assertEqual(overrides["WV-PROC-89196"]["event_date"], "2019-06-29")


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("west_virginia_adapter", HERE / "west_virginia.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "WV"))
        self.assertTrue(note.startswith("2000-present"))
        self.assertIn("DR-1319", note)


if __name__ == "__main__":
    unittest.main()
