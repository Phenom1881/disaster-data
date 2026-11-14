"""Alabama's 2000-2017 states of emergency, added by hand.

November 2009 to April 2017 rows are proclamations in the Secretary of
State's Record of Proclamations, which links a scan of each proclamation
from 2007. Earlier rows come from dated news coverage and, for October 2000,
a Jefferson County order that cites the Governor's declaration. Only the
original weather declaration is kept.
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
REGISTER = "https://arc-sos.state.al.us/PPC/VOL{}P{}.PDF"
GOVERNORS = [("1999-01-18", "Don Siegelman"), ("2003-01-20", "Bob Riley"), ("2011-01-17", "Robert Bentley"), ("2017-04-10", "Kay Ivey")]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


class RegisterRowTests(unittest.TestCase):
    def test_dates_read_from_the_register(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            "AL-SOS-13-1144": "2009-11-09", "AL-SOS-13-1146": "2009-12-16",
            # The register's date column reads 03/24/2010 for the April 24 tornadoes.
            "AL-SOS-13-1158": "2010-04-24", "AL-SOS-13-1110": "2011-04-27",
            "AL-SOS-14-1368": "2014-04-28", "AL-SOS-14-1704": "2017-04-04",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_ids_match_the_register_page(self):
        rows = [r for r in csv_rows("manual_declarations.csv") if r["declaration_id"].startswith("AL-SOS-")]
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            match = re.fullmatch(r"AL-SOS-(\d+)-(\d+)", row["declaration_id"])
            self.assertTrue(match, row["declaration_id"])
            self.assertEqual(row["archive_record_url"], REGISTER.format(*match.groups()))

    def test_non_weather_and_follow_on_entries_are_left_out(self):
        ids = {r["declaration_id"] for r in csv_rows("manual_declarations.csv")}
        left_out = {"AL-SOS-13-1154",  # 2010 UAH shooting
                    "AL-SOS-13-1160",  # Deepwater Horizon
                    "AL-SOS-13-1136",  # sinkhole
                    "AL-SOS-14-1484",  # Hurricane Matthew, out of state
                    "AL-SOS-13-1145", "AL-SOS-13-1102", "AL-SOS-13-1111", "AL-SOS-14-1429"}
        self.assertEqual(ids & left_out, set())

    def test_governor_in_office_and_rows_before_the_newsroom(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])
            if row["declaration_id"].startswith("AL-SOS-"):
                self.assertTrue("2009-11-01" <= row["date_signed"] < "2017-04-10", row["declaration_id"])
            else:
                self.assertEqual(row["declaration_id"], "AL-SOE-" + row["date_signed"])

    def test_each_has_a_reviewed_hazard(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            override = overrides[row["declaration_id"]]
            self.assertLessEqual(set(override["hazard_category_override"].split(",")),
                                 {"severe_storm", "flood", "winter", "tropical", "fire", "drought"})
            if override["event_date"] and row["declaration_id"] != "AL-SOS-13-1158":
                self.assertLessEqual(override["event_date"], row["date_signed"])
        self.assertEqual(overrides["AL-SOS-13-1262"]["event_date"], "2012-08-26")


class NewsCoverageRowTests(unittest.TestCase):
    """Declarations the register does not list, from dated news coverage."""

    def test_news_rows(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        expected = {"AL-SOE-2004-09-13": ("Bob Riley", "Ivan"),
                    "AL-SOE-2005-08-26": ("Bob Riley", "Katrina"),
                    "AL-SOE-2007-03-02": ("Bob Riley", "Enterprise"),
                    "AL-SOE-2008-08-24": ("Bob Riley", "Fay"),
                    "AL-SOE-2005-07-08": ("Bob Riley", "Dennis"),
                    "AL-SOE-2008-08-29": ("Bob Riley", "Gustav"),
                    "AL-SOE-2009-03-30": ("Bob Riley", "Houston County"),
                    "AL-SOE-2015-12-24": ("Robert Bentley", "flooding"),
                    "AL-SOE-2000-10-13": ("Don Siegelman", "drought"),
                    "AL-SOE-2000-12-16": ("Don Siegelman", "Tuscaloosa"),
                    "AL-SOE-2002-09-26": ("Don Siegelman", "Isidore"),
                    "AL-SOE-2002-11-06": ("Don Siegelman", "Abbeville"),
                    "AL-SOE-2003-05-08": ("Bob Riley", "Jefferson County")}
        for did, (governor, word) in expected.items():
            self.assertEqual(rows[did]["governor"], governor)
            self.assertIn(word, rows[did]["event_description"])

    def test_2000_2003_rows_quote_their_report(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            if row["date_signed"] < "2004-01-01":
                note = overrides[row["declaration_id"]]["review_note"]
                self.assertRegex(note, r"'[^']*(Siegelman|Riley)[^']*(declared|called) (a|this)", row["declaration_id"])
                self.assertEqual(overrides[row["declaration_id"]]["source_url"], row["archive_record_url"])


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("alabama_adapter", HERE / "alabama.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "AL"))
        self.assertTrue(note.startswith("2000-present"))
        for gap in ("DR-1317", "DR-1322", "DR-1362", "DR-1399", "DR-1842", "DR-4052", "DR-4632", "EM-3618"):
            self.assertEqual(note.count(gap), 1, gap)


if __name__ == "__main__":
    unittest.main()
