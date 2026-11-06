"""Ohio's hand-added proclamations (manual_declarations.csv).

Ohio's weather actions are ORC 5502.22 proclamations with no published list.
Most rows come from Ohio EMA's Gubernatorial Declarations History Chart, in
Appendix A of the 2024 State of Ohio Enhanced Hazard Mitigation Plan; the rest
from dated news coverage. Each row has to reach the storm join and the page
the way a collected declaration does.

Run:  python -m unittest test_oh_manual_declarations
"""
import csv
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN = HERE / "declarations_for_join.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"flood", "winter", "severe_storm", "tropical", "wind"}
CHART = ("https://services.dps.ohio.gov/MIP/PublicSite/StatePlan/GetDocument?fileUploadID=5335"
         "&filename=Appendix%20A%20to%20I.pdf")
CHART_QUOTE = re.compile(r"Gubernatorial Declarations History Chart \(updated 03/05/24\), PDF page [1-5]: "
                         r"'([A-Z][a-z]+) (\d{1,2})(?: and \d{1,2})?, (\d{4})[ ;(|]")
NEWS = {
    "https://www.irontontribune.com/?p=25090",
    "https://www.firehouse.com/home/news/10573955/violent-storms-kill-10-in-tenn-ohio",
    "https://vindyarchives.com/news/2004/aug/28/floods-raise-havoc",
    "https://vindyarchives.com/news/2004/sep/10/frances-delivers-another-blow-to-counties-in-ohio",
}
GOVERNORS = [("1999-01-11", "Bob Taft"), ("2007-01-08", "Ted Strickland"),
             ("2011-01-10", "John Kasich"), ("2019-01-14", "Mike DeWine")]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
GAPS = ("DR-1321", "EM-3286", "DR-4098")

_SPEC = importlib.util.spec_from_file_location("oh_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


def notes():
    return {row["declaration_id"]: row for row in read(OVERRIDES)}


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_dated_and_not_already_collected(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {row["declaration_id"] for row in read(JOIN)})
        for row in read(MANUAL):
            self.assertRegex(row["declaration_id"], r"^OH-PROC-\d{4}-\d{2}-\d{2}(-\d)?$")
            self.assertEqual(row["declaration_id"][8:18], row["date_signed"], row["declaration_id"])
            self.assertEqual(row["eo_number"], "", row["declaration_id"])

    def test_governor_in_office_on_each_date(self):
        for row in read(MANUAL):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])
            self.assertGreaterEqual(row["date_signed"], "2000-01-01", row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])
            self.assertNotRegex(row["event_description"],
                                r"(?i)\b(renew|extend|extension|amend|rescind|terminat|waiver|EMAC|H1N1|COVID)")

    def test_every_row_has_a_reviewed_override_from_its_own_source(self):
        reviewed = notes()
        for row in read(MANUAL):
            note = reviewed.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertIn(row["archive_record_url"], NEWS | {CHART}, row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_chart_rows_quote_the_chart_with_their_signing_date(self):
        found = 0
        for row in read(MANUAL):
            if row["archive_record_url"] != CHART:
                continue
            note = notes()[row["declaration_id"]]["review_note"]
            quoted = CHART_QUOTE.search(note)
            self.assertTrue(quoted, row["declaration_id"])
            month, day, year = quoted.groups()
            signed = date(int(year), MONTHS.index(month) + 1, int(day))
            self.assertEqual(signed.isoformat(), row["date_signed"], row["declaration_id"])
            self.assertIn("may not include every gubernatorial declaration", note)
            found += 1
        self.assertGreater(found, 0)

    def test_news_rows_quote_the_governor_declaring(self):
        for row in read(MANUAL):
            if row["archive_record_url"] in NEWS:
                self.assertRegex(notes()[row["declaration_id"]]["review_note"],
                                 r"'[^']*(?:Gov\.|Governor) Bob Taft (?:has )?declared a state of emergency")

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, HERE / "ohio.py", Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


class CoverageStartTests(unittest.TestCase):
    def test_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("ohio_adapter", HERE / "ohio.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(note, next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "OH"))
        self.assertTrue(note.startswith("manual_only - 2000-present: "), note)
        build_spec = importlib.util.spec_from_file_location("build_plus_oh", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(build_spec)
        sys.modules[build_spec.name] = build
        build_spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("OH", note), 2000)
        for gap in GAPS:
            self.assertEqual(note.count(gap), 1, gap)


if __name__ == "__main__":
    unittest.main()
