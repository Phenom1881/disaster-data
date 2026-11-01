"""Maryland's earlier weather declarations, added by hand.

The Governor's archive starts in 2023. Earlier executive orders are read from
the Department of Legislative Services' yearly compilations, which print
every numbered order. Only an order that declares an emergency for weather is
kept: amendments, rescissions, hours of service relief and non-weather
emergencies (the 2001 attacks, the 2002 sniper shootings, the 2009
inauguration and influenza, the 2015 civil unrest) are left out.
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
DLS_LIBRARY = "https://dlslibrary.state.md.us/publications/OED/A/EO_{}.pdf"
DLS_LEGISLATURE = "https://mgaleg.maryland.gov/Pubs/LegisLegal/{}-executive-orders.pdf"

GOVERNORS = [("1995-01-18", "Parris N. Glendening"), ("2003-01-15", "Robert L. Ehrlich Jr."),
             ("2007-01-17", "Martin O'Malley"), ("2015-01-21", "Lawrence J. Hogan Jr.")]


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


def compiled_rows():
    """Hand rows read from the yearly compilations."""
    return [r for r in csv_rows("manual_declarations.csv")
            if "dlslibrary.state.md.us" in r["archive_record_url"]
            or "mgaleg.maryland.gov" in r["archive_record_url"]]


class CompiledOrderTests(unittest.TestCase):
    def test_orders_and_dates_read_from_the_compilations(self):
        dates = {r["eo_number"]: r["date_signed"] for r in compiled_rows()}
        expected = {
            "01.01.2000.02": "2000-01-25", "01.01.2001.15": "2001-09-24",
            "01.01.2002.04": "2002-04-05", "01.01.2002.06": "2002-04-29",
            "01.01.2004.51": "2004-09-19", "01.01.2008.11": "2008-09-04",
            "01.01.2009.16": "2009-11-12", "01.01.2009.21": "2009-12-19",
            "01.01.2010.03": "2010-02-05", "01.01.2010.17": "2010-09-01",
            "01.01.2010.19": "2010-09-29", "01.01.2010.24": "2010-12-25",
            "01.01.2011.02": "2011-03-10", "01.01.2011.17": "2011-09-08",
            # Headed June 13, 2014; the compilation's list misdates it April 1.
            "01.01.2014.09": "2014-06-13", "01.01.2018.01": "2018-01-03",
        }
        self.assertEqual(dates, expected)

    def test_follow_on_and_non_weather_orders_are_left_out(self):
        numbers = {r["eo_number"] for r in csv_rows("manual_declarations.csv")}
        left_out = {
            "01.01.2000.03", "01.01.2002.07", "01.01.2002.10", "01.01.2003.03",
            "01.01.2003.06", "01.01.2008.13", "01.01.2010.04", "01.01.2001.10",
            "01.01.2002.21", "01.01.2009.01", "01.01.2009.05", "01.01.2015.14",
        }
        self.assertEqual(numbers & left_out, set())

    def test_ids_numbers_and_sources_agree(self):
        ids = [r["declaration_id"] for r in csv_rows("manual_declarations.csv")]
        self.assertEqual(len(ids), len(set(ids)))
        for row in compiled_rows():
            match = re.fullmatch(r"01\.01\.(\d{4})\.\d\d", row["eo_number"])
            self.assertTrue(match, row["declaration_id"])
            year = int(match.group(1))
            self.assertEqual(row["declaration_id"], "MD-EO-" + row["eo_number"].replace(".", "-"))
            self.assertEqual(row["date_signed"][:4], str(year), row["declaration_id"])
            source = DLS_LIBRARY if year <= 2006 else DLS_LEGISLATURE
            self.assertEqual(row["archive_record_url"], source.format(year), row["declaration_id"])

    def test_governor_in_office_on_each_date(self):
        for row in compiled_rows():
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_has_a_reviewed_hazard(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        allowed = {"flood", "severe_storm", "winter", "tropical", "drought", "wind"}
        for row in compiled_rows():
            override = overrides[row["declaration_id"]]
            self.assertLessEqual(set(override["hazard_category_override"].split(",")), allowed)
            if override["event_date"]:
                self.assertLessEqual(override["event_date"], signed[row["declaration_id"]])
        self.assertEqual(overrides["MD-EO-01-01-2002-06"]["event_date"], "2002-04-28")


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("maryland_adapter", HERE / "maryland.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "MD"))
        self.assertTrue(note.startswith("2000-present"))
        for gap in ("DR-1652", "DR-4583"):
            self.assertIn(gap, note)


if __name__ == "__main__":
    unittest.main()
